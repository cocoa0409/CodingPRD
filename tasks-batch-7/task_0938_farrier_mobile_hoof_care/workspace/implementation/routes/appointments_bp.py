"""Appointments: creation, the visit lifecycle and the warranty revisit."""

from flask import Blueprint

from core.auth import authenticate, require_client_owner
from core.constants import (
    ADVANCE_CANCEL_MIN_LEAD_DAYS,
    CERT_LEVEL_TO_ALLOWED_SERVICE_TYPES,
    LATE_CANCEL_FEE_CENTS,
    NO_SHOW_FEE_CENTS,
    ONSITE_CANCEL_FEE_CENTS,
    WARRANTY_REASONS,
    WARRANTY_WINDOW_DAYS,
)
from core.errors import ApiError
from core.store import db, order_key
from core.timeutil import clock, day_difference, parse_iso_date
from core.validate import bad, body, enum, opt_bool, req_date, req_list
from domain.clients import refresh_client_standing
from domain.gates import (
    ELIGIBLE,
    gate1_farrier,
    gate3_client,
    gate4_horse_hold,
    gate5_appointment,
)
from domain.invoices import mint_invoice
from domain.lookup import (
    guard_appointment,
    must,
    must_ref,
)
from domain.rates import select_rate_card
from domain.reservations import commit_reservations, release_reservations
from domain.routecalc import recompute_stop_minutes
from domain.routeops import detach_appointment, settle_route
from domain.rollups import (
    line_labor_cents,
    lines_of,
    recompute_appointment_rollups,
)
from domain.scheduling import (
    derive_next_due,
    mint_reminders,
    refresh_next_due,
    reminders_of,
    snap_forward,
)

from ._common import ALL_ROLES, listing, single

bp = Blueprint("appointments", __name__)


def new_appointment(horse, scheduled_date, **overrides):
    fields = {
        "horse_id": horse["id"],
        "route_stop_id": None,
        "origin_appointment_id": None,
        "rate_card_id": None,
        "scheduled_date": scheduled_date,
        "visit_kind": "ROUTINE",
        "warranty_reason": None,
        "cycle_source": None,
        "status": "UNROUTED",
        "billing_status": "UNBILLED",
        "vet_present": False,
        "service_units": 0,
        "service_minutes": 0,
        "estimated_total_cents": 0,
        "cancellation_fee_cents": 0,
        "trip_fee_share_cents": 0,
        "completed_on": None,
    }
    fields.update(overrides)
    # Section 3.5 states the minted shape without qualification: a new
    # appointment's "service_units, service_minutes, estimated_total_cents,
    # cancellation_fee_cents and trip_fee_share_cents all start at 0".  The
    # roll-up recomputation is scoped by the same section to run "after every
    # change to the line set", and minting is not such a change, so the handling
    # term must not be folded in until the first line arrives.
    return db.mint("appointments", fields)


@bp.post("/appointments")
def create_appointment():
    authenticate(("Dispatcher", "ClientUser"))
    data = body()
    horse = must_ref("horses", data.get("horse_id"))
    if horse is None:
        bad("Field horse_id is required.")
    require_client_owner(horse["client_id"])
    scheduled_date = req_date(data, "scheduled_date")
    vet_present = opt_bool(data, "vet_present", default=False)

    client = db.get("clients", horse["client_id"])
    gate3_client(client)
    gate4_horse_hold(horse, None, on_creation=True)
    if horse["requires_sedation"] and not vet_present:
        raise ApiError("ERR_SEDATION_VET_REQUIRED")

    appointment = new_appointment(horse, scheduled_date, vet_present=vet_present)
    return single(appointment, 201)


@bp.get("/appointments")
def list_appointments():
    return listing(
        "appointments",
        {
            "horse_id": "horse_id",
            "route_stop_id": "route_stop_id",
            "origin_appointment_id": "origin_appointment_id",
            "rate_card_id": "rate_card_id",
            "status": "status",
            "billing_status": "billing_status",
            "scheduled_date": "scheduled_date",
        },
        ALL_ROLES,
    )


@bp.get("/appointments/<appointment_id>")
def read_appointment(appointment_id):
    authenticate(ALL_ROLES)
    appointment = must("appointments", appointment_id)
    guard_appointment(appointment)
    return single(appointment)


@bp.post("/appointments/<appointment_id>/start")
def start_appointment(appointment_id):
    authenticate(("Farrier",))
    appointment = must("appointments", appointment_id)
    guard_appointment(appointment)
    horse = db.get("horses", appointment["horse_id"])
    stop = db.get("route_stops", appointment.get("route_stop_id"))
    route = db.get("routes", stop["route_id"]) if stop else None
    farrier = db.get("farriers", route["farrier_id"]) if route else None

    gate1_farrier(farrier)
    gate4_horse_hold(horse, appointment)
    gate5_appointment(appointment, ELIGIBLE["start"])
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE")
    allowed = CERT_LEVEL_TO_ALLOWED_SERVICE_TYPES[farrier["certification_level"]]
    for line in lines_of(appointment):
        if line["service_type"] not in allowed:
            raise ApiError("ERR_CREDENTIAL_INSUFFICIENT")

    appointment["status"] = "IN_PROGRESS"
    db.touch(appointment)
    return single(appointment)


def _apply_limb_transition(line, limb_state, sku_code):
    """One performed line moves its limb (PRD 3.7)."""
    service_type = line["service_type"]
    if service_type == "TRIM":
        limb_state["shoeing_state"] = "BAREFOOT"
        limb_state["current_sku_code"] = None
        limb_state["consecutive_reset_count"] = 0
    elif service_type == "RESET":
        # A RESET reuses the shoe already there: state and sku are untouched.
        limb_state["consecutive_reset_count"] += 1
    elif service_type == "GLUE_ON":
        limb_state["shoeing_state"] = "GLUED"
        limb_state["current_sku_code"] = sku_code
        limb_state["consecutive_reset_count"] = 0
    else:  # NEW_SHOES or CORRECTIVE
        limb_state["shoeing_state"] = "SHOD_WITH_PAD" if line["with_pad"] else "SHOD"
        limb_state["current_sku_code"] = sku_code
        limb_state["consecutive_reset_count"] = 0
    limb_state["last_serviced_on"] = clock.today_iso
    db.touch(limb_state)


@bp.post("/appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    authenticate(("Farrier",))
    appointment = must("appointments", appointment_id)
    guard_appointment(appointment)

    data = body()
    raw_ids = data.get("performed_service_line_ids")
    # rung 16 -- every named id must be a PLANNED line of THIS appointment.
    if isinstance(raw_ids, list):
        for value in raw_ids:
            line = db.get("service_lines", value) if isinstance(value, str) else None
            if (
                line is None
                or line["appointment_id"] != appointment["id"]
                or line["status"] != "PLANNED"
            ):
                raise ApiError("ERR_SERVICE_LINE_NOT_FOUND")
    performed_ids = req_list(data, "performed_service_line_ids", non_empty=False)
    for value in performed_ids:
        if not isinstance(value, str):
            bad("performed_service_line_ids must contain identifiers.")

    horse = db.get("horses", appointment["horse_id"])
    stop = db.get("route_stops", appointment.get("route_stop_id"))
    route = db.get("routes", stop["route_id"]) if stop else None
    farrier = db.get("farriers", route["farrier_id"]) if route else None

    gate1_farrier(farrier)
    gate5_appointment(appointment, ELIGIBLE["complete"])

    if farrier is not None:
        allowed = CERT_LEVEL_TO_ALLOWED_SERVICE_TYPES[farrier["certification_level"]]
        for line in lines_of(appointment):
            if line["service_type"] not in allowed:
                raise ApiError("ERR_CREDENTIAL_INSUFFICIENT")

    completed_on = clock.today_iso
    card = select_rate_card(completed_on, required=True)

    # 1. lines settle, each performed line prices itself and drives its limb.
    chosen = set(performed_ids)
    for line in sorted(
        [l for l in db.service_lines.values() if l["appointment_id"] == appointment["id"]],
        key=order_key,
    ):
        if line["status"] != "PLANNED":
            continue
        if line["id"] in chosen:
            line["status"] = "PERFORMED"
            line["labor_cents"] = line_labor_cents(
                appointment, horse, card, line["service_type"]
            )
            db.touch(line)
            limb_state = db.get("limb_states", line["limb_state_id"])
            sku = db.get("shoe_skus", line.get("sku_id"))
            if limb_state is not None:
                _apply_limb_transition(line, limb_state, sku["sku_code"] if sku else None)
        else:
            line["status"] = "OMITTED"
            line["labor_cents"] = 0
            db.touch(line)

    # 2. reservations commit.
    commit_reservations(appointment)

    # 3. the appointment itself.
    appointment["status"] = "COMPLETED"
    appointment["completed_on"] = completed_on
    appointment["rate_card_id"] = card["id"]
    recompute_appointment_rollups(appointment, horse)
    db.touch(appointment)

    # 4. the client's loyalty counter, counted BEFORE the invoice is priced.
    client = db.get("clients", horse["client_id"])
    client["completed_visit_count"] += 1
    db.touch(client)

    # 5. the invoice, then the billing axis -- a second declared mutation step
    #    of the appointment row (PRD 2.4 names this very case).
    mint_invoice(appointment, card)
    appointment["billing_status"] = "INVOICED"
    db.touch(appointment)

    # 6. the horse's cycle.
    horse["last_completed_on"] = completed_on
    refresh_next_due(horse)
    db.touch(horse)

    # 7. the successor visit and its two reminders.
    next_due, cycle_source = derive_next_due(horse)
    barn = db.get("barns", horse["barn_id"])
    successor_date = snap_forward(next_due, barn) if next_due else None
    if successor_date:
        # Adjudication of friction 9: the auto-minted successor carries
        # vet_present true for a horse that requires sedation.  No endpoint can
        # edit an appointment's vet_present, so the default-false reading would
        # strand every sedation horse's successor permanently unattachable
        # (rung 47 would refuse it forever); mirroring the sedation rule keeps
        # the successor usable and strands nothing.
        successor = new_appointment(
            horse,
            successor_date,
            cycle_source=cycle_source,
            vet_present=bool(horse["requires_sedation"]),
        )
        mint_reminders(successor)

    if stop is not None and recompute_stop_minutes(stop):
        db.touch(stop)
    if route is not None:
        settle_route(route)
    return single(appointment)


def _fail_reminders(appointment):
    for reminder in reminders_of(appointment["id"]):
        if reminder["status"] in ("PENDING", "SENT"):
            reminder["status"] = "FAILED"
            db.touch(reminder)


@bp.post("/appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    authenticate(("ClientUser", "Dispatcher"))
    appointment = must("appointments", appointment_id)
    guard_appointment(appointment)
    gate5_appointment(appointment, ELIGIBLE["cancel"])
    # rung 53 -- the ladder names appointment cancellation without qualifying
    # the tier, so an unpriceable visit is refused whichever tier it falls in.
    card = select_rate_card(appointment["scheduled_date"], required=True)

    stop = db.get("route_stops", appointment.get("route_stop_id"))
    lead_days = day_difference(parse_iso_date(appointment["scheduled_date"]), clock.today)
    if lead_days >= ADVANCE_CANCEL_MIN_LEAD_DAYS:
        tier = "ADVANCE"
    elif lead_days >= 1:
        tier = "LATE"
    elif stop is not None and stop["status"] == "ARRIVED":
        tier = "ONSITE"
    else:
        # Adjudication of friction 8: an UNROUTED visit cancelled with less than
        # three days' lead FOLLOWS THE TIER and becomes CANCELLED_LATE with the
        # 3500-cent fee and a fee-only invoice.  Refusing it with
        # ERR_APPOINTMENT_NOT_ELIGIBLE would contradict gate 5, which explicitly
        # admits UNROUTED for cancellation, and would strand such a visit with
        # no exit at all -- the lead only shrinks, so it could never be
        # cancelled later either.
        tier = "LATE"

    route = db.get("routes", stop["route_id"]) if stop else None
    if tier == "ADVANCE":
        appointment["cancellation_fee_cents"] = 0
        detach_appointment(appointment, "CANCELLED_ADVANCE")
        _fail_reminders(appointment)
        db.touch(appointment)
        settle_route(route)
    elif tier == "LATE":
        appointment["cancellation_fee_cents"] = LATE_CANCEL_FEE_CENTS
        appointment["rate_card_id"] = card["id"]
        detach_appointment(appointment, "CANCELLED_LATE")
        db.touch(appointment)
        settle_route(route)
        mint_invoice(appointment, card, fee_kind="CANCELLATION_FEE")
        appointment["billing_status"] = "INVOICED"
        db.touch(appointment)
    else:
        appointment["cancellation_fee_cents"] = ONSITE_CANCEL_FEE_CENTS
        appointment["rate_card_id"] = card["id"]
        appointment["status"] = "CANCELLED_ONSITE"
        release_reservations(appointment)
        db.touch(appointment)
        settle_route(route)
        mint_invoice(appointment, card, fee_kind="CANCELLATION_FEE")
        appointment["billing_status"] = "INVOICED"
        db.touch(appointment)
    return single(appointment)


@bp.post("/appointments/<appointment_id>/no-show")
def record_no_show(appointment_id):
    authenticate(("Farrier",))
    appointment = must("appointments", appointment_id)
    guard_appointment(appointment)
    stop = db.get("route_stops", appointment.get("route_stop_id"))
    route = db.get("routes", stop["route_id"]) if stop else None
    farrier = db.get("farriers", route["farrier_id"]) if route else None

    gate1_farrier(farrier)
    gate5_appointment(appointment, ELIGIBLE["no_show"])
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE")
    card = select_rate_card(appointment["scheduled_date"], required=True)

    appointment["cancellation_fee_cents"] = NO_SHOW_FEE_CENTS
    appointment["status"] = "NO_SHOW"
    appointment["completed_on"] = clock.today_iso
    appointment["rate_card_id"] = card["id"]
    release_reservations(appointment)
    db.touch(appointment)
    settle_route(route)

    mint_invoice(appointment, card, fee_kind="NO_SHOW_FEE")
    appointment["billing_status"] = "INVOICED"
    db.touch(appointment)

    horse = db.get("horses", appointment["horse_id"])
    client = db.get("clients", horse["client_id"])
    refresh_client_standing(client)
    db.touch(client)
    return single(appointment)


@bp.post("/appointments/<appointment_id>/warranty-revisit")
def warranty_revisit(appointment_id):
    authenticate(("ClientUser", "Dispatcher"))
    origin = must("appointments", appointment_id)
    guard_appointment(origin)
    data = body()
    reason = data.get("warranty_reason")
    if not isinstance(reason, str) or not reason:
        bad("Field warranty_reason is required.")
    scheduled_date = req_date(data, "scheduled_date")
    enum(reason, WARRANTY_REASONS, "warranty_reason")

    horse = db.get("horses", origin["horse_id"])
    client = db.get("clients", horse["client_id"])
    # Gate 3 guards warranty-revisit creation; gate 4 does not (PRD 2.6).
    gate3_client(client)
    gate5_appointment(origin, ELIGIBLE["warranty_revisit"])

    completed_on = parse_iso_date(origin.get("completed_on"))
    days_since = day_difference(clock.today, completed_on) if completed_on else None
    if days_since is None or days_since < 0 or days_since > WARRANTY_WINDOW_DAYS:
        raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED")

    revisit = new_appointment(
        horse,
        scheduled_date,
        visit_kind="WARRANTY_REVISIT",
        warranty_reason=reason,
        origin_appointment_id=origin["id"],
        vet_present=bool(horse["requires_sedation"]),
    )
    return single(revisit, 201)
