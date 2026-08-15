"""Composite setup helpers for the gleaning program tests.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data() is used inside setup steps so failures surface as
clear "Setup step failed" errors.

Common preamble shared by most event workflows: farm -> vehicle -> certified
crew leader + coordinator referee -> offer -> event -> publish -> one filler
volunteer confirmed (a start from OPEN requires at least one confirmed crew
member, PRD section 3.3) -> clock -> start -> containers -> lots.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_agency_payload,
    create_assignment_payload,
    create_container_payload,
    create_distribution_payload,
    create_event_payload,
    create_farm_payload,
    create_incident_payload,
    create_lot_payload,
    create_offer_payload,
    create_templog_payload,
    create_vehicle_payload,
    create_volunteer_payload,
    create_waiver_payload,
)
from .test_users import (
    TEST_USERS,
    make_crew_leader_headers,
    make_volunteer_headers,
)

_email_seq = itertools.count(1)
_label_seq = itertools.count(1)
_plate_seq = itertools.count(1)


def unique_email(prefix="vol"):
    return f"{prefix}-{next(_email_seq)}@example.org"


def unique_label(prefix="BIN"):
    return f"{prefix}-{next(_label_seq)}"


def unique_plate(prefix="PLATE"):
    return f"{prefix}-{next(_plate_seq)}"


def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


def officer_headers():
    return TEST_USERS["officer_headers"]


def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creation primitives (all lenient-validated)
# ---------------------------------------------------------------------------

def new_farm(**overrides) -> dict:
    return get_success_data(
        api_client.create_farm(create_farm_payload(**overrides), coordinator_headers())
    )


def new_vehicle(**overrides) -> dict:
    overrides.setdefault("plate", unique_plate())
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(**overrides), coordinator_headers())
    )


def new_volunteer(**overrides) -> dict:
    overrides.setdefault("email", unique_email())
    overrides.setdefault("full_name", "Volunteer")
    return get_success_data(
        api_client.create_volunteer(create_volunteer_payload(**overrides), coordinator_headers())
    )


def new_crew_leader(**overrides) -> dict:
    overrides["crew_leader_certified"] = True
    overrides.setdefault("full_name", "Crew Lead")
    return new_volunteer(**overrides)


def new_agency(**overrides) -> dict:
    return get_success_data(
        api_client.create_agency(create_agency_payload(**overrides), coordinator_headers())
    )


def new_container(**overrides) -> dict:
    overrides.setdefault("label", unique_label())
    return get_success_data(
        api_client.create_container(create_container_payload(**overrides), coordinator_headers())
    )


def new_offer(farm_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_offer(create_offer_payload(farm_id, **overrides), coordinator_headers())
    )


def new_event(offer_id, lead_id, vehicle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_event(
            create_event_payload(offer_id, lead_id, vehicle_id, **overrides),
            coordinator_headers(),
        )
    )


def publish_event(event_id) -> dict:
    return get_success_data(api_client.publish_event(event_id, coordinator_headers()))


def invite(event_id, volunteer_id) -> dict:
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(event_id, volunteer_id), coordinator_headers()
        )
    )


def sign_waiver(event_id, volunteer_id, witness_id) -> dict:
    """Volunteer signs own waiver; the crew leader witnesses (PRD section 3.2)."""
    return get_success_data(
        api_client.create_waiver(
            create_waiver_payload(volunteer_id, event_id, witness_id),
            make_volunteer_headers(volunteer_id),
        )
    )


def confirm_assignment(assignment_id, volunteer_id) -> dict:
    return get_success_data(
        api_client.confirm_assignment(assignment_id, make_volunteer_headers(volunteer_id))
    )


def decline_assignment(assignment_id, volunteer_id) -> dict:
    return get_success_data(
        api_client.decline_assignment(assignment_id, make_volunteer_headers(volunteer_id))
    )


def invite_and_confirm(event_id, witness_id, **vol_overrides) -> tuple:
    """Create a volunteer, invite, sign waiver (witnessed), confirm. Returns (volunteer, assignment)."""
    vol = new_volunteer(**vol_overrides)
    asg = invite(event_id, vol["id"])
    sign_waiver(event_id, vol["id"], witness_id)
    asg = confirm_assignment(asg["id"], vol["id"])
    return vol, asg


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, coordinator_headers()))


def start_event(event_id, lead_id) -> dict:
    return get_success_data(
        api_client.start_event(event_id, make_crew_leader_headers(lead_id))
    )


def record_lot(event_id, container_id, recorded_by_id, *, gross, cull=0.0, tare=None) -> dict:
    overrides = {"gross_lbs": gross, "cull_lbs": cull}
    if tare is not None:
        overrides["tare_lbs"] = tare
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(event_id, container_id, recorded_by_id, **overrides),
            make_crew_leader_headers(recorded_by_id),
        )
    )


def verify_lot(lot_id, coordinator_volunteer_id) -> dict:
    return get_success_data(
        api_client.verify_lot(
            lot_id, {"verified_by_coordinator_id": coordinator_volunteer_id},
            coordinator_headers(),
        )
    )


def reject_lot(lot_id) -> dict:
    return get_success_data(api_client.reject_lot(lot_id, coordinator_headers()))


def finish_event(event_id, lead_id) -> dict:
    return get_success_data(
        api_client.finish_event(event_id, make_crew_leader_headers(lead_id))
    )


def reconcile_event(event_id) -> dict:
    return get_success_data(api_client.reconcile_event(event_id, coordinator_headers()))


def get_offer(offer_id) -> dict:
    return get_success_data(api_client.get_offer(offer_id, coordinator_headers()))


def get_event(event_id) -> dict:
    return get_success_data(api_client.get_event(event_id, coordinator_headers()))


def get_farm(farm_id) -> dict:
    return get_success_data(api_client.get_farm(farm_id, coordinator_headers()))


def get_volunteer(volunteer_id) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, coordinator_headers()))


def get_agency(agency_id) -> dict:
    return get_success_data(api_client.get_agency(agency_id, coordinator_headers()))


def get_container(container_id) -> dict:
    return get_success_data(api_client.get_container(container_id, coordinator_headers()))


def get_vehicle(vehicle_id) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, coordinator_headers()))


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, coordinator_headers()))


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_lot(lot_id, coordinator_headers()))


def get_distribution(distribution_id) -> dict:
    return get_success_data(api_client.get_distribution(distribution_id, coordinator_headers()))


def get_incident(incident_id) -> dict:
    return get_success_data(api_client.get_incident(incident_id, coordinator_headers()))


def get_report(report_id) -> dict:
    return get_success_data(api_client.get_report(report_id, coordinator_headers()))


def cancel_event(event_id) -> dict:
    return get_success_data(api_client.cancel_event(event_id, coordinator_headers()))


def close_offer(offer_id) -> dict:
    """OCC-guarded close: reads the current offer version, then closes (PRD section 2.9)."""
    offer = get_offer(offer_id)
    return get_success_data(
        api_client.close_offer(
            offer_id, {"expected_offer_version": offer["version"]}, coordinator_headers()
        )
    )


def create_distribution(event_id, agency_id, planned_lbs, delivery_date=DEFAULTS["DELIVERY_DATE"]) -> dict:
    """OCC-guarded create: reads the current event version, then creates (PRD section 2.9)."""
    event = get_event(event_id)
    payload = create_distribution_payload(
        event_id, agency_id, event["version"],
        planned_lbs=planned_lbs, delivery_date=delivery_date,
    )
    return get_success_data(api_client.create_distribution(payload, coordinator_headers()))


def deliver_distribution(distribution_id, lead_id, delivered_lbs) -> dict:
    return get_success_data(
        api_client.deliver_distribution(
            distribution_id, {"delivered_lbs": delivered_lbs},
            make_crew_leader_headers(lead_id),
        )
    )


def cancel_distribution(distribution_id) -> dict:
    return get_success_data(api_client.cancel_distribution(distribution_id, coordinator_headers()))


def open_incident(event_id, reporter_id, *, severity="MINOR", condemned_lbs=5.0) -> dict:
    return get_success_data(
        api_client.create_incident(
            create_incident_payload(
                event_id, reporter_id, severity=severity, condemned_lbs=condemned_lbs
            ),
            officer_headers(),
        )
    )


def resolve_incident(incident_id, disposition="COMPOST") -> dict:
    return get_success_data(
        api_client.resolve_incident(incident_id, {"disposition": disposition}, officer_headers())
    )


def record_templog(event_id, temp_f, recorded_at=DEFAULTS["TEMP_RECORDED_AT"], as_officer=True) -> dict:
    headers = officer_headers() if as_officer else coordinator_headers()
    return get_success_data(
        api_client.create_templog(
            create_templog_payload(event_id, recorded_at=recorded_at, temp_f=temp_f), headers
        )
    )


def get_offer_receipts(offer_id) -> list:
    return get_success_data(api_client.get_offer_receipt(offer_id, coordinator_headers()))


# ---------------------------------------------------------------------------
# Tier 1-3: the event lifecycle master builder
# ---------------------------------------------------------------------------

def run_event_lifecycle(
    *,
    stop_at="closed",
    farm_over=None,
    offer_over=None,
    vehicle_over=None,
    container_over=None,
    container_count=1,
    agency_over=None,
    crew_capacity=1,
    event_start=DEFAULTS["EVENT_START"],
    event_end=DEFAULTS["EVENT_END"],
    clock_iso="2026-08-10T09:00:00Z",
    lot_specs=None,
    incident_specs=None,
    distribution_specs=None,
    county_code="AAA",
    shared=None,
) -> dict:
    """Drive one offer/event through its lifecycle.

    stop_at: "created" | "open" | "in_progress" | "harvested" | "reconciled" | "closed"
    lot_specs: [{"gross": x, "cull": y, "tare": optional, "verify": bool, "reject": bool,
                 "container_index": int}]
    incident_specs: [{"severity", "condemned_lbs", "disposition": optional}] — opened after
        the event is HARVESTED; resolved immediately when disposition is given.
    distribution_specs: [{"planned_lbs", "delivery_date", "deliver": optional lbs,
                          "cancel": bool}] — created after incidents, before reconcile.
    shared: optional dict with keys farm/vehicle/lead/coord to reuse across several
        events (multi-event scenarios); missing entries are created fresh.
    """
    shared = shared or {}
    if "farm" in shared:
        farm = shared["farm"]
    else:
        farm_defaults = {"county_code": county_code}
        farm_defaults.update(farm_over or {})
        farm = new_farm(**farm_defaults)
    offer_defaults = {"estimated_lbs": 150.0}
    offer_defaults.update(offer_over or {})
    offer = new_offer(farm["id"], **offer_defaults)
    if "vehicle" in shared:
        vehicle = shared["vehicle"]
    else:
        veh_defaults = {}
        if offer.get("requires_refrigeration"):
            veh_defaults["refrigerated"] = True
        veh_defaults.update(vehicle_over or {})
        vehicle = new_vehicle(**veh_defaults)
    lead = shared.get("lead") or new_crew_leader(email=unique_email("lead"))
    coord = shared.get("coord") or new_volunteer(
        full_name="Coordinator Ref", email=unique_email("coord")
    )

    ctx = {
        "farm": farm, "offer": offer, "vehicle": vehicle,
        "lead": lead, "coord": coord, "containers": [], "lots": [],
        "incidents": [], "distributions": [], "fillers": [],
        "event": None, "agency": None, "receipt": None,
    }

    event = new_event(
        offer["id"], lead["id"], vehicle["id"],
        scheduled_start=event_start, scheduled_end=event_end,
        crew_capacity=crew_capacity,
    )
    ctx["event"] = event
    if stop_at == "created":
        return ctx

    ctx["event"] = publish_event(event["id"])
    if stop_at == "open":
        return ctx

    # A start from OPEN requires at least one confirmed crew member (PRD 3.3).
    filler, filler_asg = invite_and_confirm(event["id"], witness_id=lead["id"])
    ctx["fillers"].append((filler, filler_asg))
    set_clock(clock_iso)
    ctx["event"] = start_event(event["id"], lead["id"])
    if stop_at == "in_progress":
        # Lots may still be recorded while IN_PROGRESS.
        _record_lots(ctx, lot_specs or [], container_over, container_count, offer)
        return ctx

    _record_lots(ctx, lot_specs or [{"gross": 110.0, "cull": 0.0, "verify": True}],
                 container_over, container_count, offer)
    ctx["event"] = finish_event(event["id"], lead["id"])
    if stop_at == "harvested":
        return ctx

    for spec in incident_specs or []:
        inc = open_incident(
            event["id"], lead["id"],
            severity=spec.get("severity", "MINOR"),
            condemned_lbs=spec.get("condemned_lbs", 5.0),
        )
        if spec.get("disposition"):
            inc = resolve_incident(inc["id"], spec["disposition"])
        ctx["incidents"].append(inc)

    if agency_over is not None:
        ctx["agency"] = new_agency(**agency_over)

    for spec in distribution_specs or []:
        if ctx["agency"] is None:
            ctx["agency"] = new_agency(county_code=county_code)
        dist = create_distribution(
            event["id"], ctx["agency"]["id"], spec["planned_lbs"],
            delivery_date=spec.get("delivery_date", DEFAULTS["DELIVERY_DATE"]),
        )
        if spec.get("cancel"):
            dist = cancel_distribution(dist["id"])
        elif spec.get("deliver") is not None:
            dist = deliver_distribution(dist["id"], lead["id"], spec["deliver"])
        ctx["distributions"].append(dist)

    ctx["event"] = reconcile_event(event["id"])
    if stop_at == "reconciled":
        return ctx

    ctx["offer"] = close_offer(offer["id"])
    receipts = get_offer_receipts(offer["id"])
    ctx["receipt"] = receipts[0] if receipts else None
    return ctx


def _record_lots(ctx, lot_specs, container_over, container_count, offer):
    while len(ctx["containers"]) < max(container_count, len(lot_specs)):
        cov = {"tare_lbs": DEFAULTS["CONTAINER_TARE_LBS"]}
        if offer.get("requires_refrigeration"):
            cov["refrigerated"] = True
        cov.update(container_over or {})
        cov["label"] = unique_label()
        ctx["containers"].append(new_container(**cov))
    for i, spec in enumerate(lot_specs):
        cont = ctx["containers"][spec.get("container_index", min(i, len(ctx["containers"]) - 1))]
        lot = record_lot(
            ctx["event"]["id"], cont["id"], ctx["lead"]["id"],
            gross=spec["gross"], cull=spec.get("cull", 0.0), tare=spec.get("tare"),
        )
        if spec.get("verify"):
            lot = verify_lot(lot["id"], ctx["coord"]["id"])
        elif spec.get("reject"):
            lot = reject_lot(lot["id"])
        ctx["lots"].append(lot)


# ---------------------------------------------------------------------------
# Tier 4/5: named composite scenarios used by several tests
# ---------------------------------------------------------------------------

def setup_in_progress_event(**kwargs) -> dict:
    kwargs["stop_at"] = "in_progress"
    return run_event_lifecycle(**kwargs)


def setup_harvested_event(*, agency_over=None, **kwargs) -> dict:
    kwargs["stop_at"] = "harvested"
    ctx = run_event_lifecycle(**kwargs)
    if agency_over is not None:
        ctx["agency"] = new_agency(**agency_over)
    return ctx


def setup_reconciled_event(**kwargs) -> dict:
    kwargs["stop_at"] = "reconciled"
    return run_event_lifecycle(**kwargs)


def setup_closed_offer(**kwargs) -> dict:
    kwargs["stop_at"] = "closed"
    return run_event_lifecycle(**kwargs)


def harvest_event_leaving_pending_no_show(target_volunteer_id, *, farm=None, lead=None,
                                          coord=None, vehicle=None,
                                          window_start, window_end,
                                          event_start, event_end, clock_iso,
                                          lot_gross=60.0, county_code="VVV") -> dict:
    """One offer+event harvested while `target_volunteer_id` sits PENDING (never confirms),
    so the finish sweep marks the assignment NO_SHOW (PRD 3.3). A filler volunteer is
    confirmed first so the OPEN event may start."""
    farm = farm or new_farm(county_code=county_code)
    vehicle = vehicle or new_vehicle()
    lead = lead or new_crew_leader(email=unique_email("lead"))
    coord = coord or new_volunteer(full_name="Coordinator Ref", email=unique_email("coord"))
    offer = new_offer(farm["id"], estimated_lbs=50.0,
                      window_start=window_start, window_end=window_end)
    event = new_event(offer["id"], lead["id"], vehicle["id"],
                      scheduled_start=event_start, scheduled_end=event_end,
                      crew_capacity=3)
    publish_event(event["id"])
    target_asg = invite(event["id"], target_volunteer_id)
    invite_and_confirm(event["id"], witness_id=lead["id"])
    set_clock(clock_iso)
    start_event(event["id"], lead["id"])
    container = new_container()
    lot = record_lot(event["id"], container["id"], lead["id"], gross=lot_gross)
    verify_lot(lot["id"], coord["id"])
    event = finish_event(event["id"], lead["id"])
    return {
        "farm": farm, "offer": offer, "vehicle": vehicle, "lead": lead, "coord": coord,
        "event": event, "target_assignment": get_assignment(target_asg["id"]),
        "container": container, "lot": lot,
    }
