"""TreatmentSession routes: book / commit / resolve / cancel / no-show
(PRD §3.4, §3.6, §3.7)."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import ApiError
from middleware import require_roles
from helpers import (get_json_body, require_string, require_int, optional_int,
                     paginate)
from response import success_object, success_array
import domain
from routes.plans import _release_session_reservations

bp = Blueprint("sessions", __name__)


def _base_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --------------------------------------------------------------------------
# Book a session (FEFO reservation) — PRD §3.4
# --------------------------------------------------------------------------
@bp.route("/aesthetics/treatment-sessions", methods=["POST"])
@require_roles("Provider")
def book_session():
    body = get_json_body()
    treatment_plan_id = require_string(body, "treatment_plan_id")
    standing_order_id = require_string(body, "standing_order_id")
    injector_provider_id = require_string(body, "injector_provider_id")
    injectable_lot_id = require_string(body, "injectable_lot_id")
    planned_units = require_int(body, "planned_units", positive=True)
    loyalty_points_redeemed = optional_int(body, "loyalty_points_redeemed",
                                           default=0, minimum=0)

    # priority 4: body FK existence (order: plan, standing order, injector, lot)
    plan = db.treatment_plans.get(treatment_plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Treatment plan not found")
    order = db.standing_orders.get(standing_order_id)
    if order is None:
        raise ApiError("ERR_STANDING_ORDER_NOT_FOUND", "Standing order not found")
    injector = db.providers.get(injector_provider_id)
    if injector is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    lot = db.injectable_lots.get(injectable_lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Injectable lot not found")

    # priority 7: plan source state
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Plan not ACTIVE")
    # priority 6: OCC on plan
    expected = require_int(body, "expected_treatment_plan_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION", "Stale plan version")

    # Domain safety checks in PRD §3.4 order.
    # Standing order active.
    if not domain.standing_order_active(order):
        raise ApiError("ERR_STANDING_ORDER_INACTIVE", "Standing order inactive")
    # Good-faith exam exists + fresh.
    consultation = db.consultations.get(plan["consultation_id"])
    if consultation is None or consultation["status"] != "EXAM_COMPLETE":
        raise ApiError("ERR_NO_GOOD_FAITH_EXAM", "No good-faith exam on record")
    if not domain.exam_fresh(consultation):
        raise ApiError("ERR_GOOD_FAITH_EXAM_EXPIRED", "Good-faith exam expired")
    # Product agreement across order/plan/lot.
    if not (order["product"] == plan["product"] == lot["product"]):
        raise ApiError("ERR_PRODUCT_MISMATCH", "Product mismatch")
    # Units authorized.
    if planned_units > order["max_units_authorized"]:
        raise ApiError("ERR_UNITS_EXCEED_ORDER", "Planned units exceed order")
    # Injector eligible.
    if injector["role_kind"] != "INJECTOR" or injector["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ELIGIBLE", "Injector not eligible")
    # Segregation of duties.
    if injector_provider_id == order["director_provider_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Injector cannot be the signing director")
    # Consent photo on file.
    patient = db.patients.get(plan["patient_id"])
    if not (patient and patient.get("photo_consent_on_file") is True):
        raise ApiError("ERR_CONSENT_PHOTO_REQUIRED", "Signed consent photo required")
    # Inventory: enough remaining over AVAILABLE non-expired lots of product.
    if domain.available_units(plan["product"]) < planned_units:
        raise ApiError("ERR_INSUFFICIENT_LOT_UNITS", "Insufficient lot units")

    # All preconditions passed: FEFO reserve.
    reservations = _fefo_reserve(plan["product"], planned_units)

    session = _base_common()
    session.update({
        "treatment_plan_id": treatment_plan_id,
        "standing_order_id": standing_order_id,
        "injector_provider_id": injector_provider_id,
        "injectable_lot_id": injectable_lot_id,
        "planned_units": planned_units,
        "actual_units": None,
        "loyalty_points_redeemed": loyalty_points_redeemed,
        "final_charge_cents": 0,
        "balance_due_cents": 0,
        "points_earned_cents_basis": 0,
        "status": "BOOKED",
        "_reservations": reservations,
    })
    db.treatment_sessions[session["id"]] = session

    # Bump plan version + recompute provisional cost.
    domain.recompute_plan_provisional(plan)
    domain.touch(plan)
    return success_object(domain.serialize(session, "TreatmentSession"), 201)


def _fefo_reserve(product, need):
    """Reserve `need` units across FEFO-ordered lots. Returns {lot_id: qty}."""
    reservations = {}
    for lot in domain.fefo_candidates(product):
        if need <= 0:
            break
        take = min(need, lot["remaining_units"])
        if take <= 0:
            continue
        lot["reserved_units"] += take
        domain.recompute_lot_remaining(lot)
        domain.touch(lot)
        reservations[lot["id"]] = reservations.get(lot["id"], 0) + take
        need -= take
    return reservations


@bp.route("/aesthetics/treatment-sessions", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_sessions():
    f = request.args
    records = list(db.treatment_sessions.values())
    for key in ("treatment_plan_id", "standing_order_id", "injector_provider_id",
                "injectable_lot_id", "status"):
        val = f.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "TreatmentSession") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/treatment-sessions/<sid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_session(sid):
    session = db.treatment_sessions.get(sid)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")
    return success_object(domain.serialize(session, "TreatmentSession"))


# --------------------------------------------------------------------------
# Commit — PRD §3.6
# --------------------------------------------------------------------------
@bp.route("/aesthetics/treatment-sessions/<sid>/commit", methods=["POST"])
@require_roles("Provider")
def commit_session(sid):
    session = db.treatment_sessions.get(sid)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")
    body = get_json_body()
    actual_units = optional_int(body, "actual_units", default=None, positive=True)
    if actual_units is None:
        actual_units = session["planned_units"]

    # priority 7: state
    if session["status"] != "BOOKED":
        raise ApiError("ERR_SESSION_NOT_BOOKED", "Session not BOOKED")
    # Units authorized at commit.
    order = db.standing_orders.get(session["standing_order_id"])
    if order is not None and actual_units > order["max_units_authorized"]:
        raise ApiError("ERR_UNITS_EXCEED_ORDER", "Actual units exceed order")
    # BEFORE photo required.
    has_before = any(
        p["treatment_session_id"] == sid and p["kind"] == "BEFORE"
        for p in db.consent_photos.values()
    )
    if not has_before:
        raise ApiError("ERR_BEFORE_PHOTO_REQUIRED", "BEFORE photo required")

    plan = db.treatment_plans.get(session["treatment_plan_id"])

    # Settle inventory: convert reserved -> consumed for actual_units in FEFO
    # order across the lots this session reserved; release leftover.
    _consume_reservations(session, actual_units)

    # Compute charge.
    patient = db.patients.get(plan["patient_id"])
    member_discount_pct = 0
    if patient and patient.get("membership_id"):
        membership = db.membership_packages.get(patient["membership_id"])
        if membership is not None:
            member_discount_pct = membership["member_discount_pct"]

    final_charge = domain.compute_final_charge(
        actual_units, plan["list_price_per_unit_cents"],
        member_discount_pct, session["loyalty_points_redeemed"])

    deposit_allocated = min(final_charge, plan["deposit_paid_cents"])
    balance_due = max(0, final_charge - deposit_allocated)
    points_basis = final_charge // 100

    session["actual_units"] = actual_units
    session["final_charge_cents"] = final_charge
    session["balance_due_cents"] = balance_due
    session["points_earned_cents_basis"] = points_basis
    session["status"] = "COMMITTED"
    domain.touch(session)

    # Loyalty ledger.
    account = domain.loyalty_account_for_patient(plan["patient_id"])
    if account is not None:
        account["points_earned"] += points_basis
        account["points_redeemed"] += session["loyalty_points_redeemed"]
        domain.recompute_loyalty_balance(account)
        domain.touch(account)

    # Plan ledger sync.
    plan["finalized_series_cost_cents"] += final_charge
    plan["sessions_committed"] += 1
    domain.recompute_plan_provisional(plan)
    domain.touch(plan)

    # Provider counts.
    injector = db.providers.get(session["injector_provider_id"])
    if injector is not None:
        domain.recompute_provider_counts(injector)
        domain.touch(injector)

    return success_object(domain.serialize(session, "TreatmentSession"))


def _consume_reservations(session, actual_units):
    """Convert reserved->consumed for actual_units in FEFO order across the
    session's reserved lots; release leftover (planned - actual)."""
    reservations = session.get("_reservations", {})
    # Order lot ids by the lot's FEFO key (expiration ASC, created_at ASC, seq).
    lot_items = []
    for lot_id, qty in reservations.items():
        lot = db.injectable_lots.get(lot_id)
        if lot is None:
            continue
        lot_items.append((lot, qty))
    lot_items.sort(key=lambda t: (t[0]["_expiration_dt"], t[0]["created_at"], t[0]["_seq"]))

    need = actual_units
    for lot, reserved_qty in lot_items:
        consume = min(need, reserved_qty)
        leftover = reserved_qty - consume
        # Release the entire reservation for this lot, then re-apply consumed.
        lot["reserved_units"] -= reserved_qty
        lot["consumed_units"] += consume
        domain.recompute_lot_remaining(lot)
        domain.touch(lot)
        need -= consume
        # leftover is implicitly released back to remaining_units (already done).
    session["_reservations"] = {}


# --------------------------------------------------------------------------
# Resolve (happy path) — PRD §3.7
# --------------------------------------------------------------------------
@bp.route("/aesthetics/treatment-sessions/<sid>/resolve", methods=["POST"])
@require_roles("Provider")
def resolve_session(sid):
    session = db.treatment_sessions.get(sid)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")
    if session["status"] != "COMMITTED":
        raise ApiError("ERR_SESSION_NOT_COMMITTED", "Session not COMMITTED")
    has_after = any(
        p["treatment_session_id"] == sid and p["kind"] == "AFTER"
        for p in db.consent_photos.values()
    )
    if not has_after:
        raise ApiError("ERR_AFTER_PHOTO_REQUIRED", "AFTER photo required")
    open_case = any(
        c["treatment_session_id"] == sid and c["status"] in ("OPEN", "IN_TOUCHUP")
        for c in db.complication_cases.values()
    )
    if open_case:
        raise ApiError("ERR_COMPLICATION_OPEN", "Open complication exists")

    session["status"] = "RESOLVED"
    domain.touch(session)
    return success_object(domain.serialize(session, "TreatmentSession"))


# --------------------------------------------------------------------------
# Cancel a booked session — PRD §3.4
# --------------------------------------------------------------------------
@bp.route("/aesthetics/treatment-sessions/<sid>/cancel", methods=["POST"])
@require_roles("ClinicAdmin")
def cancel_session(sid):
    session = db.treatment_sessions.get(sid)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")
    if session["status"] != "BOOKED":
        raise ApiError("ERR_SESSION_NOT_BOOKED", "Session not BOOKED")
    _release_session_reservations(session)
    session["status"] = "CANCELLED"
    domain.touch(session)
    plan = db.treatment_plans.get(session["treatment_plan_id"])
    if plan is not None:
        domain.recompute_plan_provisional(plan)
        domain.touch(plan)
    return success_object(domain.serialize(session, "TreatmentSession"))


# --------------------------------------------------------------------------
# No-show — PRD §3.4
# --------------------------------------------------------------------------
@bp.route("/aesthetics/treatment-sessions/<sid>/no-show", methods=["POST"])
@require_roles("ClinicAdmin")
def no_show_session(sid):
    session = db.treatment_sessions.get(sid)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")
    if session["status"] != "BOOKED":
        raise ApiError("ERR_SESSION_NOT_BOOKED", "Session not BOOKED")
    _release_session_reservations(session)
    session["status"] = "NO_SHOW"
    domain.touch(session)
    plan = db.treatment_plans.get(session["treatment_plan_id"])
    if plan is not None:
        domain.recompute_plan_provisional(plan)
        domain.touch(plan)
    return success_object(domain.serialize(session, "TreatmentSession"))
