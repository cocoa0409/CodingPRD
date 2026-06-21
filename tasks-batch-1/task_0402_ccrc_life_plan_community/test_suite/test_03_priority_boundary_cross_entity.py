"""Priority-pair, boundary-precision, and cross-entity-dependency tests.

Queue (A) difficulty instances covering validation precedence (PRD §2.10, §3.2,
§3.4), exact-threshold boundaries on quorum and the bed hold window (PRD §3.8,
§3.5), and cross-entity state gates on care apply and waitlist place (PRD §3.4,
§3.3).
"""
from test_helpers import (
    activate_residency,
    advance_clock,
    cast_vote,
    create_unit,
    get_residency,
    hold_bed,
    open_residency,
    reserve_residency_via_assign,
    setup_active_residency,
    setup_community_and_plan,
    setup_open_resolution_with_active_residencies,
    enqueue_waitlist,
    AD,
    FO,
)
from test_helpers.api_client import api_client
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId


def _AD():
    from test_helpers import make_admissions_director_headers
    return make_admissions_director_headers()


def _CC():
    from test_helpers import make_care_coordinator_headers
    return make_care_coordinator_headers()


# ─────────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / activate_frozen_beats_not_reserved_state
# ─────────────────────────────────────────────────────────────────────────────

def test_activate_deposit_held_in_frozen_community_reports_not_reserved(api):
    """PRD §3.2: "Activation requires the `expected_residency_version` guard described
    in Section 2.8, checked first; the residency must currently be `RESERVED`, else
    `ERR_RESIDENCY_NOT_RESERVED`; it must have a `unit_id` set, else
    `ERR_NO_UNIT_ASSIGNED`; and the community must not be frozen, else
    `ERR_ADMISSIONS_FROZEN`."

    A DEPOSIT_HELD residency in a frozen community: the RESERVED state check
    precedes the frozen check, so the response is ERR_RESIDENCY_NOT_RESERVED.

    Design: Difficulty/priority_pair_validation_conflict/activate_frozen_beats_not_reserved_state
    """
    community, deposit_held = _frozen_community_with_deposit_held("Frost")
    resp = api_client.activate_residency(
        deposit_held["id"],
        {"expected_residency_version": deposit_held["version"]},
        _AD(),
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_NOT_RESERVED.value)


def test_frozen_community_flag_is_actually_set(api):
    """PRD §3.6: "when `funded_ratio_bps` falls strictly below the floor of the
    community's `target_funded_ratio_bps` divided by 2 — that is, below half the
    target — the community's `is_admissions_frozen` is set to true".

    Confirms the community is genuinely frozen, so the frozen check would fire if
    the earlier state check did not pre-empt it.

    Design: Difficulty/priority_pair_validation_conflict/activate_frozen_beats_not_reserved_state
    """
    community, _deposit_held = _frozen_community_with_deposit_held("Frost2")
    fresh = validate_success(api_client.get_community(community["id"], FO))
    assert fresh["is_admissions_frozen"] is True, (
        f"community must be frozen after deficient report, got "
        f"is_admissions_frozen={fresh['is_admissions_frozen']}"
    )


def _frozen_community_with_deposit_held(name: str):
    """Community frozen via a deficient reserve report (one ACTIVE residency),
    plus a second still-DEPOSIT_HELD residency. Returns (community, deposit_held)."""
    community, plan = setup_community_and_plan(
        community_name=name,
        actuarial_discount_rate_bps=0,
        reserve_assets_cents=0,
        target_funded_ratio_bps=10000,
        plan_overrides={
            "name": "Fr Plan", "contract_type": "TYPE_C",
            "entrance_fee_cents": 100_000, "refund_plan": "DECLINING",
            "monthly_service_fee_cents": 1000, "second_person_fee_cents": 0,
            "declining_nonrefundable_bps": 400,
        },
    )
    unit_a = create_unit(community["id"], unit_number="F1", care_level="INDEPENDENT")
    reserved = reserve_residency_via_assign(community, plan, unit_a,
                                            resident_name="Fred A")
    activate_residency(reserved)
    # second residency stays DEPOSIT_HELD
    deposit_held = open_residency(community, plan, resident_name="Frank B",
                                 dob="1929-01-01")
    # generate the deficient report → freezes admissions
    validate_success(api_client.create_reserve_report(community["id"], {}, FO),
                     expected_status=201)
    return community, deposit_held


# ─────────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / care_apply_invalid_step_beats_no_bed_occupied
# ─────────────────────────────────────────────────────────────────────────────

def test_care_apply_skip_to_skilled_reports_invalid_care_step(api):
    """PRD §3.4: "the requested `to_level` must be exactly one step away from
    `from_level` ... a jump such as `INDEPENDENT` straight to `SKILLED` is rejected
    with `ERR_INVALID_CARE_STEP`. Furthermore, if `to_level` is `SKILLED`, the
    residency must already hold an `OCCUPIED` bed reservation, else the apply is
    rejected with `ERR_NO_BED_OCCUPIED`."

    An INDEPENDENT residency proposing SKILLED (a skip) with no occupied bed fails
    both checks; the invalid-step check (PRD §2.10 validation order: body
    well-formedness before business-referential) wins → ERR_INVALID_CARE_STEP.

    Design: Difficulty/priority_pair_validation_conflict/care_apply_invalid_step_beats_no_bed_occupied
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Sage",
        plan_overrides={"name": "Sg Plan", "second_person_fee_cents": 0},
    )
    proposed = validate_success(api_client.create_care_transition(
        {"residency_id": active["id"], "to_level": "SKILLED"}, _CC(),
    ), expected_status=201)
    resp = api_client.apply_care_transition(proposed["id"], _CC())
    validate_error(resp, ApiErrorId.ERR_INVALID_CARE_STEP.value)


def test_care_apply_invalid_step_not_masked_by_no_bed_occupied(api):
    """PRD §3.4: "a jump such as `INDEPENDENT` straight to `SKILLED` is rejected with
    `ERR_INVALID_CARE_STEP`."

    A second isolated assertion that the skip from INDEPENDENT to SKILLED yields
    ERR_INVALID_CARE_STEP — never the cross-entity ERR_NO_BED_OCCUPIED — confirming
    the step-validity check pre-empts the bed-occupancy check.

    Design: Difficulty/priority_pair_validation_conflict/care_apply_invalid_step_beats_no_bed_occupied
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Sage2",
        plan_overrides={"name": "Sg Plan", "second_person_fee_cents": 0},
    )
    proposed = validate_success(api_client.create_care_transition(
        {"residency_id": active["id"], "to_level": "SKILLED"}, _CC(),
    ), expected_status=201)
    resp = api_client.apply_care_transition(proposed["id"], _CC())
    body = validate_error(resp, ApiErrorId.ERR_INVALID_CARE_STEP.value)
    assert body["error_id"] != ApiErrorId.ERR_NO_BED_OCCUPIED.value


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / quorum_met_at_exact_threshold_votes
# ─────────────────────────────────────────────────────────────────────────────

def test_resolution_closes_passed_at_exact_quorum_threshold(api):
    """PRD §3.8: "quorum is met when the total votes cast — `yes_votes` plus
    `no_votes` — multiplied by 10000 is at least the `eligible_voter_count`
    multiplied by the council's `quorum_pct_bps`".
    PRD §3.8: "if `yes_votes` is strictly greater than `no_votes`, the resolution
    closes `PASSED`".

    4 ACTIVE residencies, quorum 5000bps, exactly 2 YES votes: 2*10000 == 4*5000,
    quorum met exactly; yes 2 > no 0 → PASSED.

    Design: Difficulty/boundary_precision_check/quorum_met_at_exact_threshold_votes
    """
    _community, _council, resolution, residencies = (
        setup_open_resolution_with_active_residencies(
            num_residencies=4, quorum_pct_bps=5000, community_name="Vote Town",
        )
    )
    assert resolution["eligible_voter_count"] == 4, (
        f"eligible_voter_count must snapshot 4 ACTIVE residencies, "
        f"got {resolution['eligible_voter_count']}"
    )
    cast_vote(resolution["id"], residencies[0], "YES")
    cast_vote(resolution["id"], residencies[1], "YES")
    closed = validate_success(api_client.close_resolution(resolution["id"], FO))
    assert closed["status"] == "PASSED", (
        f"resolution at exact quorum with yes>no must close PASSED, "
        f"got {closed['status']}"
    )


def test_resolution_below_quorum_threshold_rejected(api):
    """PRD §3.8: "if that threshold is not reached, the close is rejected with
    `ERR_QUORUM_NOT_MET`."

    Same 4 ACTIVE residencies, quorum 5000bps, only 1 vote cast: 1*10000 < 4*5000,
    quorum NOT met → close is rejected (the just-below pole of the exact boundary).

    Design: Difficulty/boundary_precision_check/quorum_met_at_exact_threshold_votes
    """
    _community, _council, resolution, residencies = (
        setup_open_resolution_with_active_residencies(
            num_residencies=4, quorum_pct_bps=5000, community_name="Vote Town 2",
        )
    )
    cast_vote(resolution["id"], residencies[0], "YES")
    resp = api_client.close_resolution(resolution["id"], FO)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value)


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / bed_occupy_at_exact_expiry_period_succeeds
# ─────────────────────────────────────────────────────────────────────────────

def test_bed_occupy_at_exact_expiry_period_succeeds(api):
    """PRD §3.5: "Occupying a held reservation requires it to be `HELD`, else
    `ERR_BED_RESERVATION_NOT_HELD`; the community's `current_period_index` must not
    exceed the reservation's `hold_expiry_period`, else `ERR_BED_RESERVATION_EXPIRED`".

    hold_expiry_period=3; advancing to period 3 then occupying succeeds because
    current_period_index (3) does not exceed hold_expiry_period (3).

    Design: Difficulty/boundary_precision_check/bed_occupy_at_exact_expiry_period_succeeds
    """
    community, skilled_unit, brid = _held_bed_at_period("Clock Town", expiry=3, advance_to=3)
    occupied = validate_success(api_client.occupy_bed_reservation(brid, _CC()))
    assert occupied["status"] == "OCCUPIED", (
        f"occupy at period == expiry must succeed, got {occupied['status']}"
    )


def test_bed_occupy_at_exact_expiry_marks_unit_occupied(api):
    """PRD §3.5: "Occupying stamps the reservation's `occupied_start_period` with the
    current `current_period_index` and flips the skilled unit's `status` to
    `OCCUPIED`, consuming the bed."

    At the exact expiry boundary (period 3 == hold_expiry_period 3) the skilled
    unit's status is OCCUPIED after a successful occupy.

    Design: Difficulty/boundary_precision_check/bed_occupy_at_exact_expiry_period_succeeds
    """
    community, skilled_unit, brid = _held_bed_at_period("Clock Town 2", expiry=3, advance_to=3)
    validate_success(api_client.occupy_bed_reservation(brid, _CC()))
    from test_helpers import get_unit
    unit = get_unit(skilled_unit["id"])
    assert unit["status"] == "OCCUPIED", (
        f"skilled unit must be OCCUPIED after occupy, got {unit['status']}"
    )


def _held_bed_at_period(name: str, expiry: int, advance_to: int):
    """ACTIVE residency, a HELD bed with the given expiry, clock advanced to
    `advance_to`. Returns (community, skilled_unit, brid)."""
    community, plan = setup_community_and_plan(
        community_name=name,
        plan_overrides={"name": "T Plan", "contract_type": "TYPE_A",
                        "second_person_fee_cents": 0},
    )
    ind_unit = create_unit(community["id"], unit_number="TI", care_level="INDEPENDENT")
    skilled_unit = create_unit(community["id"], unit_number="TS",
                               care_level="SKILLED", bed_capacity=1)
    reserved = reserve_residency_via_assign(community, plan, ind_unit)
    active = activate_residency(reserved)
    br = hold_bed(active["id"], skilled_unit["id"], expiry)
    advance_clock(community["id"], advance_to)
    return community, skilled_unit, br["id"]


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / care_apply_requires_residency_active
# ─────────────────────────────────────────────────────────────────────────────

def test_care_apply_on_terminated_residency_reports_not_active(api):
    """PRD §3.4: "the parent residency must still be `ACTIVE`, else
    `ERR_RESIDENCY_NOT_ACTIVE`".

    A care transition proposed while the residency was ACTIVE, then applied after
    the residency was terminated, is rejected with ERR_RESIDENCY_NOT_ACTIVE — the
    cross-entity gate re-checks the residency state at apply time.

    Design: Difficulty/cross_entity_state_dependency/care_apply_requires_residency_active
    """
    _community, _plan, _unit, active = setup_active_residency(
        community_name="Holly2",
        plan_overrides={"name": "H Plan", "second_person_fee_cents": 0},
    )
    proposed = validate_success(api_client.create_care_transition(
        {"residency_id": active["id"], "to_level": "ASSISTED"}, _CC(),
    ), expected_status=201)
    fresh = get_residency(active["id"])
    from test_helpers import terminate_residency
    terminate_residency(fresh["id"], "VOLUNTARY", fresh["version"])
    resp = api_client.apply_care_transition(proposed["id"], _CC())
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_NOT_ACTIVE.value)


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency /
#   waitlist_place_requires_residency_waitlisted_and_unit_available
# ─────────────────────────────────────────────────────────────────────────────

def test_waitlist_place_rejected_when_target_unit_occupied(api):
    """PRD §3.3: "the target unit named by `unit_id` must be `AVAILABLE` and of
    `care_level` `INDEPENDENT`, else `ERR_UNIT_NOT_AVAILABLE`".

    Placing the head waitlist entry into the only INDEPENDENT unit, when that unit
    is already OCCUPIED by a different RESERVED residency, is rejected with
    ERR_UNIT_NOT_AVAILABLE — the place transition depends on the Unit's state.

    Design: Difficulty/cross_entity_state_dependency/waitlist_place_requires_residency_waitlisted_and_unit_available
    """
    community, plan = setup_community_and_plan(
        community_name="Juniper",
        plan_overrides={"name": "J Plan", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="J1", care_level="INDEPENDENT")
    r1 = open_residency(community, plan, resident_name="Jo One", dob="1925-01-01")
    r2 = open_residency(community, plan, resident_name="Jo Two", dob="1924-01-01")
    # r2 takes the only unit (RESERVED), r1 goes onto the waitlist (rank 1)
    validate_success(api_client.assign_unit(r2["id"], {"unit_id": unit["id"]}, _AD()))
    w1 = enqueue_waitlist(community, r1, "INDEPENDENT")
    resp = api_client.place_waitlist_entry(w1["id"], {"unit_id": unit["id"]}, _AD())
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)


def test_waitlist_place_rejected_leaves_residency_waitlisted(api):
    """PRD §3.3: "the parent residency must be in `WAITLISTED`, else
    `ERR_RESIDENCY_NOT_WAITLISTED`".

    When the place is rejected because the target unit is unavailable, the parent
    residency remains WAITLISTED (the failed transition leaves the cross-entity
    state untouched).

    Design: Difficulty/cross_entity_state_dependency/waitlist_place_requires_residency_waitlisted_and_unit_available
    """
    community, plan = setup_community_and_plan(
        community_name="Juniper2",
        plan_overrides={"name": "J Plan", "second_person_fee_cents": 0},
    )
    unit = create_unit(community["id"], unit_number="J1", care_level="INDEPENDENT")
    r1 = open_residency(community, plan, resident_name="Jo One", dob="1925-01-01")
    r2 = open_residency(community, plan, resident_name="Jo Two", dob="1924-01-01")
    validate_success(api_client.assign_unit(r2["id"], {"unit_id": unit["id"]}, _AD()))
    w1 = enqueue_waitlist(community, r1, "INDEPENDENT")
    api_client.place_waitlist_entry(w1["id"], {"unit_id": unit["id"]}, _AD())
    r1_after = get_residency(r1["id"])
    assert r1_after["status"] == "WAITLISTED", (
        f"residency must remain WAITLISTED after a rejected place, "
        f"got {r1_after['status']}"
    )
