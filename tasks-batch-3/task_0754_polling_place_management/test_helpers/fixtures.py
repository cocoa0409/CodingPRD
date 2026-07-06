"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints, because the
server database is empty at the start of every test. Setup calls use the lenient
get_success_data() validator so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_election_payload,
    create_polling_place_payload,
    create_equipment_payload,
    create_poll_worker_payload,
    create_assignment_payload,
    create_supply_kit_payload,
    create_shift_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


# --------------------------------------------------------------------------- #
# Single-entity builders
# --------------------------------------------------------------------------- #

def create_election(api=api_client, *, open_voting=False, **overrides) -> dict:
    """Create an election; optionally advance it to VOTING_OPEN."""
    el = get_success_data(api.create_election(create_election_payload(**overrides), ADMIN))
    if open_voting:
        el = get_success_data(api.open_voting(el["id"], ADMIN))
    return el


def create_place(api=api_client, *, election_id, **overrides) -> dict:
    return get_success_data(
        api.create_polling_place(create_polling_place_payload(election_id, **overrides), ADMIN)
    )


def deploy_equipment(api=api_client, *, place_id, serial_number="SN-1",
                     equipment_type="SCANNER") -> dict:
    """Create a warehouse unit and deploy it OPERATIONAL to the place."""
    eq = get_success_data(
        api.create_equipment(
            create_equipment_payload(serial_number=serial_number, equipment_type=equipment_type),
            ADMIN,
        )
    )
    eq = get_success_data(api.deploy_equipment(eq["id"], {"polling_place_id": place_id}, ADMIN))
    return eq


def create_kit_at_place(api=api_client, *, election_id, place_id, ballot_count=500,
                        seal_number="SEAL-1") -> dict:
    """Prepare a kit and drive it PREPARED -> ISSUED -> IN_TRANSIT -> AT_PLACE."""
    kit = get_success_data(
        api.create_supply_kit(
            create_supply_kit_payload(election_id, ballot_count=ballot_count,
                                      seal_number=seal_number),
            CUSTODY,
        )
    )
    kid = kit["id"]
    get_success_data(api.create_custody_event(kid, {"event_type": "ISSUE"}, CUSTODY))
    get_success_data(api.create_custody_event(kid, {"event_type": "DISPATCH"}, CUSTODY))
    get_success_data(
        api.create_custody_event(kid, {"event_type": "RECEIVE", "polling_place_id": place_id},
                                 CUSTODY)
    )
    return get_success_data(api.get_supply_kit(kid, CUSTODY))


def create_certified_worker(api=api_client, *, full_name="Jane Poll", email="jane@x.com") -> dict:
    w = get_success_data(
        api.create_poll_worker(create_poll_worker_payload(full_name=full_name, email=email), ADMIN)
    )
    w = get_success_data(api.complete_training(w["id"], ADMIN))
    return w


def create_active_assignment(api=api_client, *, worker_id, place_id, is_lead=False) -> dict:
    a = get_success_data(
        api.create_assignment(
            create_assignment_payload(worker_id, place_id, is_lead=is_lead), CAPTAIN
        )
    )
    a = get_success_data(api.activate_assignment(a["id"], CAPTAIN))
    return a


# --------------------------------------------------------------------------- #
# Composite scenarios
# --------------------------------------------------------------------------- #

def setup_staffed_place(api=api_client, *, initial_ballot_stock=10000, min_workers_required=1,
                        staffing_capacity=5, station_capacity=5, is_lead=False, open_voting=True,
                        with_equipment=True, with_kit=True, worker_name="Jane Poll",
                        worker_email="jane@x.com") -> dict:
    """Election (VOTING_OPEN) + place + deployed scanner + kit AT_PLACE + one certified worker
    on an ACTIVE assignment. The place is left in SETUP (not yet opened).

    Returns a dict of the created resource payloads keyed by entity name.
    """
    el = create_election(api, open_voting=open_voting, initial_ballot_stock=initial_ballot_stock)
    pp = create_place(api, election_id=el["id"], min_workers_required=min_workers_required,
                      staffing_capacity=staffing_capacity, station_capacity=station_capacity)
    eq = deploy_equipment(api, place_id=pp["id"]) if with_equipment else None
    kit = create_kit_at_place(api, election_id=el["id"], place_id=pp["id"]) if with_kit else None
    worker = create_certified_worker(api, full_name=worker_name, email=worker_email)
    assignment = create_active_assignment(api, worker_id=worker["id"], place_id=pp["id"],
                                          is_lead=is_lead)
    pp = get_success_data(api.get_polling_place(pp["id"], ADMIN))
    return {
        "election": el, "place": pp, "equipment": eq, "kit": kit,
        "worker": worker, "assignment": assignment,
    }


def setup_open_place(api=api_client, **kwargs) -> dict:
    """setup_staffed_place, then transition the place SETUP -> OPEN.

    Accepts the same keyword overrides as setup_staffed_place.
    """
    ctx = setup_staffed_place(api, **kwargs)
    ctx["place"] = get_success_data(api.open_place(ctx["place"]["id"], CAPTAIN))
    return ctx


def setup_shift_scheduled(api=api_client, *, scheduled_start, scheduled_end, is_lead=False,
                          station_capacity=5, **kwargs) -> dict:
    """Open place + a SCHEDULED shift for its worker over [scheduled_start, scheduled_end)."""
    ctx = setup_open_place(api, is_lead=is_lead, station_capacity=station_capacity, **kwargs)
    shift = get_success_data(
        api.create_shift(
            create_shift_payload(ctx["assignment"]["id"], scheduled_start, scheduled_end), CAPTAIN
        )
    )
    ctx["shift"] = shift
    return ctx


def worked_shift_gross_pay(api=api_client, *, scheduled_start, scheduled_end,
                           check_in_iso, check_out_iso, is_lead=False, **kwargs) -> dict:
    """Full path to a CHECKED_OUT shift: open place, schedule the shift, set clock to
    check_in_iso and check in, set clock to check_out_iso and check out.

    Returns ctx with the final 'shift' (CHECKED_OUT) and refreshed 'place'/'worker'.
    """
    ctx = setup_shift_scheduled(api, scheduled_start=scheduled_start, scheduled_end=scheduled_end,
                                is_lead=is_lead, **kwargs)
    sid = ctx["shift"]["id"]
    get_success_data(api.set_clock(check_in_iso, ADMIN))
    get_success_data(api.check_in(sid, CAPTAIN))
    get_success_data(api.set_clock(check_out_iso, ADMIN))
    ctx["shift"] = get_success_data(api.check_out(sid, CAPTAIN))
    ctx["place"] = get_success_data(api.get_polling_place(ctx["place"]["id"], ADMIN))
    ctx["worker"] = get_success_data(api.get_poll_worker(ctx["worker"]["id"], ADMIN))
    return ctx


def setup_closed_place_ready_to_reconcile(api=api_client, **kwargs) -> dict:
    """Open place with no shifts, then close it. Returns ctx with 'place' CLOSED and its
    'version' captured for the OCC reconcile field."""
    ctx = setup_open_place(api, **kwargs)
    ctx["place"] = get_success_data(api.close_place(ctx["place"]["id"], CAPTAIN))
    return ctx
