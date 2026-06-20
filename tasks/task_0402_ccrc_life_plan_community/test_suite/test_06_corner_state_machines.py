"""Corner (breadth) tests for state-machine guards and invalid transitions.

Queue (B) corner-design instances from the `state_machines` section (PRD §3.2-
§3.8). The three excluded_because stubs in this section are NOT translated; their
assertions are owned by the cited queue-(A) difficulty instances.
"""
from test_helpers import (
    activate_residency,
    create_council,
    create_resolution,
    create_unit,
    enqueue_waitlist,
    get_residency,
    hold_bed,
    make_resident_headers,
    open_residency,
    propose_and_apply_transition,
    reserve_residency_via_assign,
    setup_active_residency,
    setup_community_and_plan,
    AD,
    FO,
)
from test_helpers.api_client import api_client
from test_helpers import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_care_transition_payload


def _AD():
    from test_helpers import make_admissions_director_headers
    return make_admissions_director_headers()


def _CC():
    from test_helpers import make_care_coordinator_headers
    return make_care_coordinator_headers()


# ─── terminate_from_terminal_state_returns_residency_not_active ──────────────

def test_second_terminate_on_terminated_residency_rejected(api):
    """PRD §3.7: "The residency must be `ACTIVE`, else `ERR_RESIDENCY_NOT_ACTIVE`."

    A second terminate on an already TERMINATED_VOLUNTARY residency is rejected
    with ERR_RESIDENCY_NOT_ACTIVE.

    Design: Corner/state_machines/terminate_from_terminal_state_returns_residency_not_active
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Term",
        plan_overrides={"name": "Tp", "second_person_fee_cents": 0},
    )
    fresh = get_residency(active["id"])
    terminated = validate_success(api_client.terminate_residency(
        fresh["id"], {"reason": "VOLUNTARY", "expected_residency_version": fresh["version"]}, _AD(),
    ))
    resp = api_client.terminate_residency(
        fresh["id"],
        {"reason": "VOLUNTARY", "expected_residency_version": terminated["version"]}, _AD(),
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_NOT_ACTIVE.value)


# ─── assign_unit_on_reserved_returns_not_deposit_held ───────────────────────

def test_assign_unit_on_reserved_residency_rejected(api):
    """PRD §3.2: "The residency must currently be in `DEPOSIT_HELD`, or the action is
    rejected with `ERR_RESIDENCY_NOT_DEPOSIT_HELD`."

    Design: Corner/state_machines/assign_unit_on_reserved_returns_not_deposit_held
    """
    community, plan = setup_community_and_plan(
        community_name="AsgT", plan_overrides={"name": "Ap", "second_person_fee_cents": 0},
    )
    u1 = create_unit(community["id"], unit_number="AA1", care_level="INDEPENDENT")
    u2 = create_unit(community["id"], unit_number="AA2", care_level="INDEPENDENT")
    reserved = reserve_residency_via_assign(community, plan, u1)
    resp = api_client.assign_unit(reserved["id"], {"unit_id": u2["id"]}, _AD())
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_NOT_DEPOSIT_HELD.value)


# ─── assign_skilled_unit_to_independent_residency_returns_care_level_mismatch ─

def test_assign_skilled_unit_rejected_with_care_level_mismatch(api):
    """PRD §3.2: "the target unit's `care_level` must be `INDEPENDENT`, or the action
    is rejected with `ERR_UNIT_CARE_LEVEL_MISMATCH`."

    Design: Corner/state_machines/assign_skilled_unit_to_independent_residency_returns_care_level_mismatch
    """
    community, plan = setup_community_and_plan(
        community_name="MisT", plan_overrides={"name": "Mp", "second_person_fee_cents": 0},
    )
    skilled = create_unit(community["id"], unit_number="MS", care_level="SKILLED", bed_capacity=1)
    residency = open_residency(community, plan, resident_name="Mo M")
    resp = api_client.assign_unit(residency["id"], {"unit_id": skilled["id"]}, _AD())
    validate_error(resp, ApiErrorId.ERR_UNIT_CARE_LEVEL_MISMATCH.value)


# ─── activate_reserved_without_unit_is_unreachable_no_unit_assigned ──────────

def test_activate_freshly_reserved_residency_succeeds_with_unit(api):
    """PRD §3.2: "Once a residency holds a reserved unit, the `AdmissionsDirector`
    activates it, driving `RESERVED` to `ACTIVE`."

    A freshly RESERVED residency (assign-unit always set unit_id) activates
    successfully and its unit_id is non-null, so the defensive
    ERR_NO_UNIT_ASSIGNED guard is not triggered.

    Design: Corner/state_machines/activate_reserved_without_unit_is_unreachable_no_unit_assigned
    """
    community, plan = setup_community_and_plan(
        community_name="NoU", plan_overrides={"name": "Np", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="NU1", care_level="INDEPENDENT")
    reserved = reserve_residency_via_assign(community, plan, unit)
    activated = validate_success(api_client.activate_residency(
        reserved["id"], {"expected_residency_version": reserved["version"]}, _AD(),
    ))
    assert activated["status"] == "ACTIVE", f"expected ACTIVE, got {activated['status']}"
    assert activated["unit_id"] == unit["id"], (
        f"unit_id must be the assigned unit (non-null), got {activated['unit_id']}"
    )


# ─── care_transition_apply_twice_returns_not_proposed ───────────────────────

def test_apply_already_applied_care_transition_rejected(api):
    """PRD §3.4: "The transition must currently be `PROPOSED`, else
    `ERR_CARE_TRANSITION_NOT_PROPOSED`".

    Design: Corner/state_machines/care_transition_apply_twice_returns_not_proposed
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Idem", plan_overrides={"name": "Ip", "second_person_fee_cents": 0},
    )
    proposed = validate_success(api_client.create_care_transition(
        create_care_transition_payload(active["id"], "ASSISTED"), _CC(),
    ), expected_status=201)
    validate_success(api_client.apply_care_transition(proposed["id"], _CC()))
    resp = api_client.apply_care_transition(proposed["id"], _CC())
    validate_error(resp, ApiErrorId.ERR_CARE_TRANSITION_NOT_PROPOSED.value)


# ─── occupy_released_bed_returns_not_held ───────────────────────────────────

def test_occupy_released_bed_reservation_rejected(api):
    """PRD §3.5: "Occupying a held reservation requires it to be `HELD`, else
    `ERR_BED_RESERVATION_NOT_HELD`".

    Design: Corner/state_machines/occupy_released_bed_returns_not_held
    """
    community, skilled, brid = _active_with_held_bed("BedR")
    validate_success(api_client.release_bed_reservation(brid, _CC()))
    resp = api_client.occupy_bed_reservation(brid, _CC())
    validate_error(resp, ApiErrorId.ERR_BED_RESERVATION_NOT_HELD.value)


# ─── release_already_released_bed_returns_not_releasable ────────────────────

def test_release_already_released_bed_rejected(api):
    """PRD §3.5: "Releasing an `OCCUPIED` reservation requires it to be `OCCUPIED`,
    else `ERR_BED_RESERVATION_NOT_RELEASABLE`".

    A second release on a HELD-then-RELEASED reservation (terminal RELEASED) is
    rejected with ERR_BED_RESERVATION_NOT_RELEASABLE.

    Design: Corner/state_machines/release_already_released_bed_returns_not_releasable
    """
    community, skilled, brid = _active_with_held_bed("RelR")
    validate_success(api_client.release_bed_reservation(brid, _CC()))
    resp = api_client.release_bed_reservation(brid, _CC())
    validate_error(resp, ApiErrorId.ERR_BED_RESERVATION_NOT_RELEASABLE.value)


def _active_with_held_bed(name: str):
    community, plan = setup_community_and_plan(
        community_name=name,
        plan_overrides={"name": "Bp", "contract_type": "TYPE_A", "second_person_fee_cents": 0},
    )
    ind = create_unit(community["id"], unit_number=f"{name[:2]}I", care_level="INDEPENDENT")
    skilled = create_unit(community["id"], unit_number=f"{name[:2]}S",
                          care_level="SKILLED", bed_capacity=1)
    active = activate_residency(reserve_residency_via_assign(community, plan, ind))
    br = hold_bed(active["id"], skilled["id"], 10)
    return community, skilled, br["id"]


# ─── open_already_open_resolution_returns_not_draft ─────────────────────────

def test_open_already_open_resolution_rejected(api):
    """PRD §3.8: "Opening a resolution drives it from `DRAFT` to `OPEN`; the
    resolution must be `DRAFT`, else `ERR_RESOLUTION_NOT_DRAFT`."

    Design: Corner/state_machines/open_already_open_resolution_returns_not_draft
    """
    community = _community_only("OpenT")
    council = create_council(community["id"])
    resolution = create_resolution(council["id"], title="Topic")
    validate_success(api_client.open_resolution(resolution["id"], FO))
    resp = api_client.open_resolution(resolution["id"], FO)
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_NOT_DRAFT.value)


# ─── vote_on_draft_resolution_returns_not_open ──────────────────────────────

def test_vote_on_draft_resolution_rejected(api):
    """PRD §3.8: "The resolution must be `OPEN` to accept a vote, else
    `ERR_RESOLUTION_NOT_OPEN`."

    Design: Corner/state_machines/vote_on_draft_resolution_returns_not_open
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="VDraft",
        plan_overrides={"name": "Vp", "entrance_fee_cents": 100_000,
                        "monthly_service_fee_cents": 1000, "second_person_fee_cents": 0},
    )
    council = create_council(active["community_id"])
    resolution = create_resolution(council["id"], title="Topic")  # left DRAFT
    headers = make_resident_headers(active["_primary_resident_id"])
    resp = api_client.cast_vote(
        resolution["id"], {"residency_id": active["id"], "choice": "YES"}, headers,
    )
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_NOT_OPEN.value)


# ─── duplicate_vote_same_residency_returns_duplicate_vote ───────────────────

def test_duplicate_vote_same_residency_rejected(api):
    """PRD §3.8: "A residency may cast at most one vote per resolution and must be
    `ACTIVE` to vote; a second vote from the same residency, or a vote from a
    non-`ACTIVE` residency, is rejected with `ERR_DUPLICATE_VOTE`."

    Design: Corner/state_machines/duplicate_vote_same_residency_returns_duplicate_vote
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Dup",
        plan_overrides={"name": "Dp", "entrance_fee_cents": 100_000,
                        "monthly_service_fee_cents": 1000, "second_person_fee_cents": 0},
    )
    council = create_council(active["community_id"])
    resolution = create_resolution(council["id"], title="Topic")
    validate_success(api_client.open_resolution(resolution["id"], FO))
    headers = make_resident_headers(active["_primary_resident_id"])
    validate_success(api_client.cast_vote(
        resolution["id"], {"residency_id": active["id"], "choice": "YES"}, headers,
    ), expected_status=201)
    resp = api_client.cast_vote(
        resolution["id"], {"residency_id": active["id"], "choice": "NO"}, headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE.value)


# ─── enqueue_waitlist_twice_returns_duplicate_entry ─────────────────────────

def test_enqueue_waitlist_twice_rejected(api):
    """PRD §3.3: "the residency must not already have a `PENDING` waitlist entry,
    else `ERR_DUPLICATE_WAITLIST_ENTRY`."
    PRD §3.3: "The residency must be in `DEPOSIT_HELD`, else
    `ERR_RESIDENCY_NOT_DEPOSIT_HELD`".

    A residency already WAITLISTED (one PENDING entry) re-enqueued is rejected;
    either guard (duplicate-entry or no-longer-DEPOSIT_HELD) is PRD-faithful.

    Design: Corner/state_machines/enqueue_waitlist_twice_returns_duplicate_entry
    """
    community, plan = setup_community_and_plan(
        community_name="WDup", plan_overrides={"name": "Wp", "second_person_fee_cents": 0},
    )
    residency = open_residency(community, plan, resident_name="Win W")
    enqueue_waitlist(community, residency, "INDEPENDENT")
    resp = api_client.create_waitlist_entry(
        {"community_id": community["id"], "residency_id": residency["id"],
         "target_care_level": "INDEPENDENT"}, _AD(),
    )
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_DUPLICATE_WAITLIST_ENTRY.value,
        ApiErrorId.ERR_RESIDENCY_NOT_DEPOSIT_HELD.value,
    ])


# ─── offer_non_head_waitlist_entry_returns_not_head ─────────────────────────

def test_offer_non_head_waitlist_entry_rejected(api):
    """PRD §3.3: "Only the entry whose `rank` is 1 — the head of the queue — may be
    offered or placed; an attempt to offer or place any non-head entry is rejected
    with `ERR_WAITLIST_NOT_HEAD`."

    Design: Corner/state_machines/offer_non_head_waitlist_entry_returns_not_head
    """
    community, plan = setup_community_and_plan(
        community_name="Head", plan_overrides={"name": "Hp", "second_person_fee_cents": 0},
    )
    r1 = open_residency(community, plan, resident_name="H1", dob="1930-01-01", priority_score=0)
    r2 = open_residency(community, plan, resident_name="H2", dob="1929-01-01", priority_score=0)
    enqueue_waitlist(community, r1, "INDEPENDENT")  # rank 1
    w2 = enqueue_waitlist(community, r2, "INDEPENDENT")  # rank 2
    resp = api_client.offer_waitlist_entry(w2["id"], _AD())
    validate_error(resp, ApiErrorId.ERR_WAITLIST_NOT_HEAD.value)


# ─── withdraw_placed_entry_returns_not_withdrawable ─────────────────────────

def test_withdraw_placed_entry_rejected(api):
    """PRD §3.3: "Withdrawal is permitted only from `PENDING` or `OFFERED`, else
    `ERR_WAITLIST_ENTRY_NOT_WITHDRAWABLE`."

    Design: Corner/state_machines/withdraw_placed_entry_returns_not_withdrawable
    """
    community, plan = setup_community_and_plan(
        community_name="WWd", plan_overrides={"name": "Wwp", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="WW1", care_level="INDEPENDENT")
    residency = open_residency(community, plan, resident_name="Wd W")
    wid = enqueue_waitlist(community, residency, "INDEPENDENT")
    validate_success(api_client.place_waitlist_entry(wid["id"], {"unit_id": unit["id"]}, _AD()))
    resp = api_client.withdraw_waitlist_entry(wid["id"], _AD())
    validate_error(resp, ApiErrorId.ERR_WAITLIST_ENTRY_NOT_WITHDRAWABLE.value)


# ─── place_placed_entry_returns_not_placeable ───────────────────────────────

def test_place_already_placed_entry_rejected(api):
    """PRD §3.3: "Placement requires the entry to be in `OFFERED` or `PENDING`, else
    `ERR_WAITLIST_ENTRY_NOT_PLACEABLE`".

    Design: Corner/state_machines/place_placed_entry_returns_not_placeable
    """
    community, plan = setup_community_and_plan(
        community_name="WPl", plan_overrides={"name": "Wpl", "second_person_fee_cents": 0},
    )
    u1 = create_unit(community["id"], unit_number="WP1", care_level="INDEPENDENT")
    u2 = create_unit(community["id"], unit_number="WP2", care_level="INDEPENDENT")
    residency = open_residency(community, plan, resident_name="Wp W")
    wid = enqueue_waitlist(community, residency, "INDEPENDENT")
    validate_success(api_client.place_waitlist_entry(wid["id"], {"unit_id": u1["id"]}, _AD()))
    resp = api_client.place_waitlist_entry(wid["id"], {"unit_id": u2["id"]}, _AD())
    validate_error(resp, ApiErrorId.ERR_WAITLIST_ENTRY_NOT_PLACEABLE.value)


# ─── offer_placed_entry_returns_not_pending ─────────────────────────────────

def test_offer_already_placed_entry_rejected(api):
    """PRD §3.3: "Offering the head entry advances it from `PENDING` to `OFFERED`; the
    entry must currently be `PENDING`, else `ERR_WAITLIST_ENTRY_NOT_PENDING`".

    Offering an entry already PLACED (not PENDING) is rejected with
    ERR_WAITLIST_ENTRY_NOT_PENDING.

    Design: Corner/state_machines/offer_placed_entry_returns_not_pending
    """
    community, plan = setup_community_and_plan(
        community_name="WOf", plan_overrides={"name": "Wof", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="WO1", care_level="INDEPENDENT")
    residency = open_residency(community, plan, resident_name="Wo W")
    wid = enqueue_waitlist(community, residency, "INDEPENDENT")
    validate_success(api_client.place_waitlist_entry(wid["id"], {"unit_id": unit["id"]}, _AD()))
    resp = api_client.offer_waitlist_entry(wid["id"], _AD())
    validate_error(resp, ApiErrorId.ERR_WAITLIST_ENTRY_NOT_PENDING.value)


def _community_only(name: str):
    from test_helpers import create_community
    return create_community(name=name)
