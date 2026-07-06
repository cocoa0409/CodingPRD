"""Conserved-quantity invariants and assignment activation ordering.

Queue A (difficulty): compensating_invariant, priority_pair_validation_conflict.
Queue B (validations): insufficient ballot stock, no open slots.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_election, create_place, create_certified_worker, create_active_assignment,
    create_supply_kit_payload, create_poll_worker_payload, create_assignment_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]


# ---- compensating_invariant / ballot_stock_conserved_on_issue_then_void ----

def _issued_kit(api, *, initial_ballot_stock=10000, ballot_count=500):
    el = create_election(api, initial_ballot_stock=initial_ballot_stock)
    kit = get_success_data(api.create_supply_kit(
        create_supply_kit_payload(el["id"], ballot_count=ballot_count), CUSTODY))
    get_success_data(api.create_custody_event(kit["id"], {"event_type": "ISSUE"}, CUSTODY))
    return el, kit


def test_issue_debits_unallocated_ballot_stock(api):
    """PRD §2.10: "Committing a kit's `ballot_count` to it (issuing the kit) decrements
    `unallocated_ballot_stock` by that count; voiding that issuance restores it by the same
    count."

    Design: Difficulty/compensating_invariant/ballot_stock_conserved_on_issue_then_void
    """
    el, kit = _issued_kit(api, initial_ballot_stock=10000, ballot_count=500)
    election = get_success_data(api.get_election(el["id"], ADMIN))
    assert election["unallocated_ballot_stock"] == 9500, (
        f"10000 - 500 issued = 9500, got {election['unallocated_ballot_stock']}"
    )


def test_void_issue_restores_unallocated_ballot_stock(api):
    """PRD §3.6: "VOID_ISSUE (`ISSUED → PREPARED`): the compensating reversal of an issue; the
    election's `unallocated_ballot_stock` is increased back by `ballot_count`."

    Design: Difficulty/compensating_invariant/ballot_stock_conserved_on_issue_then_void
    """
    el, kit = _issued_kit(api, initial_ballot_stock=10000, ballot_count=500)
    get_success_data(api.create_custody_event(kit["id"], {"event_type": "VOID_ISSUE"}, CUSTODY))
    election = get_success_data(api.get_election(el["id"], ADMIN))
    kit_now = get_success_data(api.get_supply_kit(kit["id"], CUSTODY))
    assert election["unallocated_ballot_stock"] == 10000, (
        f"VOID_ISSUE must restore stock to 10000, got {election['unallocated_ballot_stock']}"
    )
    assert kit_now["custody_state"] == "PREPARED"


# ---- compensating_invariant / staffing_slots_conserved_on_activate_then_withdraw ----

def test_activate_fills_staffing_slot(api):
    """PRD §2.10: "activating an assignment increments `slots_filled` and decrements
    `slots_open` by one; withdrawing an active assignment does the reverse."

    Design: Difficulty/compensating_invariant/staffing_slots_conserved_on_activate_then_withdraw
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"], staffing_capacity=5)
    w = create_certified_worker(api)
    create_active_assignment(api, worker_id=w["id"], place_id=pp["id"])
    place = get_success_data(api.get_polling_place(pp["id"], ADMIN))
    assert place["slots_filled"] == 1
    assert place["slots_open"] == 4, f"5 - 1 filled = 4 open, got {place['slots_open']}"


def test_withdraw_active_assignment_releases_slot(api):
    """PRD §3.4: "Withdrawing an `ACTIVE` assignment releases its slot — `slots_filled`
    decreases by one and `slots_open` increases by one — whereas withdrawing a `PROPOSED`
    assignment releases no slot, because none was ever filled."

    Design: Difficulty/compensating_invariant/staffing_slots_conserved_on_activate_then_withdraw
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"], staffing_capacity=5)
    w = create_certified_worker(api)
    a = create_active_assignment(api, worker_id=w["id"], place_id=pp["id"])
    withdrawn = validate_success(api.withdraw_assignment(a["id"], CAPTAIN))
    place = get_success_data(api.get_polling_place(pp["id"], ADMIN))
    assert withdrawn["status"] == "WITHDRAWN"
    assert place["slots_filled"] == 0
    assert place["slots_open"] == 5, f"withdraw must restore slots_open to 5, got {place['slots_open']}"


# ---- priority_pair_validation_conflict / activate_referential_beats_constraint ----

def _place_full_with_pending_second_worker(api):
    """staffing_capacity=1: a certified worker fills the only slot; a second, still-PENDING
    worker has a PROPOSED assignment. Returns the PROPOSED assignment id of the pending worker."""
    el = create_election(api)
    pp = create_place(api, election_id=el["id"], staffing_capacity=1)
    wc = create_certified_worker(api, full_name="Certified W", email="cw@x.com")
    create_active_assignment(api, worker_id=wc["id"], place_id=pp["id"])  # slots_open now 0
    wp = get_success_data(api.create_poll_worker(
        create_poll_worker_payload(full_name="Pending W", email="pw@x.com"), ADMIN))  # PENDING
    ap = get_success_data(api.create_assignment(
        create_assignment_payload(wp["id"], pp["id"]), CAPTAIN))
    return ap


def test_activate_uncertified_full_place_reports_not_certified(api):
    """PRD §3.4: "Activating an assignment takes it `PROPOSED → ACTIVE` and consumes a staffing
    slot; it requires that the assignment be `PROPOSED`, that the named worker's
    `training_status` be `CERTIFIED` (otherwise `ERR_WORKER_NOT_CERTIFIED`, 422), and that the
    place have at least one open slot, i.e. `slots_open` greater than or equal to one
    (otherwise `ERR_NO_OPEN_SLOTS`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/activate_referential_beats_constraint
    """
    ap = _place_full_with_pending_second_worker(api)
    resp = api.activate_assignment(ap["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_WORKER_NOT_CERTIFIED)


def test_activate_referential_rejection_leaves_assignment_proposed(api):
    """PRD §3.4: "it requires that the assignment be `PROPOSED`, that the named worker's
    `training_status` be `CERTIFIED` (otherwise `ERR_WORKER_NOT_CERTIFIED`, 422), and that the
    place have at least one open slot, i.e. `slots_open` greater than or equal to one
    (otherwise `ERR_NO_OPEN_SLOTS`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/activate_referential_beats_constraint
    """
    ap = _place_full_with_pending_second_worker(api)
    validate_error(api.activate_assignment(ap["id"], CAPTAIN), ApiErrorId.ERR_WORKER_NOT_CERTIFIED)
    still = get_success_data(api.get_assignment(ap["id"], ADMIN))
    assert still["status"] == "PROPOSED", "a rejected activation must not change assignment status"


# ---- validations / error_insufficient_ballot_stock_on_issue ----

def test_issue_beyond_stock_is_insufficient(api):
    """PRD §3.6: "ISSUE (`PREPARED → ISSUED`): permitted only from `PREPARED`, and only if the
    election's `unallocated_ballot_stock` is greater than or equal to the kit's `ballot_count`
    (otherwise `ERR_INSUFFICIENT_BALLOT_STOCK`, 422)."

    Design: Corner/validations/error_insufficient_ballot_stock_on_issue
    """
    el = create_election(api, initial_ballot_stock=100)
    kit = get_success_data(api.create_supply_kit(
        create_supply_kit_payload(el["id"], ballot_count=500), CUSTODY))
    resp = api.create_custody_event(kit["id"], {"event_type": "ISSUE"}, CUSTODY)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALLOT_STOCK)


# ---- validations / error_no_open_slots_on_activate_certified_worker ----

def test_activate_certified_worker_when_place_full_is_no_open_slots(api):
    """PRD §3.4: "and that the place have at least one open slot, i.e. `slots_open` greater
    than or equal to one (otherwise `ERR_NO_OPEN_SLOTS`, 422)."

    Design: Corner/validations/error_no_open_slots_on_activate_certified_worker
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"], staffing_capacity=1)
    w1 = create_certified_worker(api, full_name="W1", email="w1@x.com")
    create_active_assignment(api, worker_id=w1["id"], place_id=pp["id"])  # fills only slot
    w2 = create_certified_worker(api, full_name="W2", email="w2@x.com")
    a2 = get_success_data(api.create_assignment(create_assignment_payload(w2["id"], pp["id"]), CAPTAIN))
    resp = api.activate_assignment(a2["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_NO_OPEN_SLOTS)
