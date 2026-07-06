"""Military honors capacity/entitlement, flag conservation, and marker orders.

Covers difficulty boundary_precision (honors capacity), compensating_invariant
(daily squad count), cross_entity_state_dependency (honors confirm requires
scheduled), combinatorial_formula (marker charge), priority_pair (unit-kind before
inscription is SKIPPED), plus corner marker/honors/validation instances.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cemetery_with_gravesite,
    setup_assigned_case,
    setup_scheduled_case,
    create_cemetery,
    create_in_ground_section,
    create_gravesite,
    open_and_approve_case,
    assign_plot_auto,
    assign_plot_explicit,
    create_schedule,
    request_honors,
    confirm_honors,
    create_marker,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["eligibility_officer_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]
MARKER = TEST_USERS["marker_clerk_headers"]
HONORS = TEST_USERS["honors_coordinator_headers"]


def _setup_two_scheduled_cases_same_date(cem_capacity):
    """Cemetery(cap) + two STANDARD gravesites + two VETERAN cases scheduled on 2026-06-10.
    Returns (cem, sec, case1, sched1, case2, sched2)."""
    cem, sec, grv1 = setup_cemetery_with_gravesite(
        depth_capacity=1, honors_squad_capacity=cem_capacity, grid_ref="R1C1"
    )
    grv2 = create_gravesite(cem["id"], sec["id"], grid_ref="R1C2", gravesite_class="STANDARD", depth_capacity=1)
    case1 = open_and_approve_case(cem["id"])
    assign_plot_explicit(cem["id"], case1["id"], grv1["id"], "GRAVESITE", grv1["version"])
    sched1 = create_schedule(cem["id"], case1["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    case2 = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case2["id"])
    sched2 = create_schedule(cem["id"], case2["id"], "2026-06-10T14:00:00Z", "2026-06-10T15:00:00Z")
    return cem, sec, case1, sched1, case2, sched2


# ===========================================================================
# boundary_precision — honors daily capacity '>=' boundary
# ===========================================================================
def test_honors_capacity_second_confirm_rejected(api):
    """PRD §3.8: "count the confirmed honors on the same honors_date at the same
    cemetery, and if that count is already at or above the cemetery's
    honors_squad_capacity, the confirmation is rejected with ERR_HONORS_CAPACITY_FULL
    — the boundary is inclusive, so when capacity is N the Nth already-confirmed
    detail leaves no room for another."

    Design: Difficulty/boundary_precision_check/honors_capacity_ge_boundary_on_confirm
    """
    cem, sec, case1, sched1, case2, sched2 = _setup_two_scheduled_cases_same_date(cem_capacity=1)
    hon1 = request_honors(cem["id"], sched1["id"], detail_size="TWO_PERSON")
    confirm_honors(cem["id"], hon1["id"])  # first confirm on the date -> 0 < 1 succeeds
    hon2 = request_honors(cem["id"], sched2["id"], detail_size="TWO_PERSON")
    resp = api.confirm_military_honors(cem["id"], hon2["id"], HONORS)
    validate_error(resp, ApiErrorId.ERR_HONORS_CAPACITY_FULL, expected_status=409)
    hon1_read = validate_success(api.get_military_honors(cem["id"], hon1["id"], HONORS))
    assert hon1_read["status"] == "CONFIRMED"


def test_honors_first_confirm_under_capacity_succeeds(api):
    """PRD §3.8: "The cemetery's daily honors capacity must not be exhausted: count
    the confirmed honors on the same honors_date at the same cemetery, and if that
    count is already at or above the cemetery's honors_squad_capacity, the
    confirmation is rejected with ERR_HONORS_CAPACITY_FULL"

    Design: Difficulty/boundary_precision_check/honors_capacity_ge_boundary_on_confirm
    """
    cem, sec, case1, sched1, case2, sched2 = _setup_two_scheduled_cases_same_date(cem_capacity=1)
    hon1 = request_honors(cem["id"], sched1["id"], detail_size="TWO_PERSON")
    confirmed = validate_success(api.confirm_military_honors(cem["id"], hon1["id"], HONORS))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["flag_issued"] is True


# ===========================================================================
# compensating_invariant — confirm+cancel conserves daily squad slot
# ===========================================================================
def test_honors_confirm_cancel_frees_daily_slot(api):
    """PRD §3.8: "A coordinator may also cancel a detail from either REQUESTED or
    CONFIRMED, moving it to CANCELLED; if the flag had been issued, flag_issued is
    reset to false."
    PRD §3.8: "count the confirmed honors on the same honors_date at the same
    cemetery, and if that count is already at or above the cemetery's
    honors_squad_capacity, the confirmation is rejected with ERR_HONORS_CAPACITY_FULL"

    Design: Difficulty/compensating_invariant/honors_confirm_cancel_conserves_daily_squad_count
    """
    cem, sec, case1, sched1, case2, sched2 = _setup_two_scheduled_cases_same_date(cem_capacity=1)
    hon1 = request_honors(cem["id"], sched1["id"], detail_size="TWO_PERSON")
    confirm_honors(cem["id"], hon1["id"])
    validate_success(api.cancel_military_honors(cem["id"], hon1["id"], HONORS))  # frees the slot
    hon2 = request_honors(cem["id"], sched2["id"], detail_size="TWO_PERSON")
    confirmed = validate_success(api.confirm_military_honors(cem["id"], hon2["id"], HONORS))
    assert confirmed["status"] == "CONFIRMED"
    hon1_read = validate_success(api.get_military_honors(cem["id"], hon1["id"], HONORS))
    assert hon1_read["status"] == "CANCELLED"


def test_honors_cancel_resets_flag(api):
    """PRD §3.8: "A coordinator may also cancel a detail from either REQUESTED or
    CONFIRMED, moving it to CANCELLED; if the flag had been issued, flag_issued is
    reset to false."

    Design: Difficulty/compensating_invariant/honors_confirm_cancel_conserves_daily_squad_count
    """
    cem, sec, case1, sched1, case2, sched2 = _setup_two_scheduled_cases_same_date(cem_capacity=1)
    hon1 = request_honors(cem["id"], sched1["id"], detail_size="TWO_PERSON")
    confirmed = confirm_honors(cem["id"], hon1["id"])
    assert confirmed["flag_issued"] is True
    cancelled = validate_success(api.cancel_military_honors(cem["id"], hon1["id"], HONORS))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["flag_issued"] is False


# ===========================================================================
# cross_entity_state_dependency — honors confirm requires scheduled interment
# ===========================================================================
def test_honors_confirm_after_schedule_cancelled_invalid_state(api):
    """PRD §3.7: "As a cascade, any linked military-honors record in REQUESTED or
    CONFIRMED is driven to CANCELLED"
    PRD §2.6: "the target resource's state is checked against the requested
    transition, yielding ERR_INVALID_STATE when the transition is not defined from
    the current state."

    Design: Difficulty/cross_entity_state_dependency/honors_confirm_requires_scheduled_interment
    """
    cem, sec, grv, case, sched = setup_scheduled_case(
        window_start="2026-06-10T10:00:00Z", window_end="2026-06-10T12:00:00Z",
        depth_capacity=1, honors_squad_capacity=2,
    )
    hon = request_honors(cem["id"], sched["id"], detail_size="TWO_PERSON")
    validate_success(api.cancel_interment_schedule(cem["id"], sched["id"], CLERK))  # cascades honors -> CANCELLED
    resp = api.confirm_military_honors(cem["id"], hon["id"], HONORS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    hon_read = validate_success(api.get_military_honors(cem["id"], hon["id"], HONORS))
    assert hon_read["status"] == "CANCELLED"


def test_honors_confirm_on_scheduled_interment_succeeds(api):
    """PRD §3.8: "Confirming a requested detail moves it from REQUESTED to CONFIRMED
    and is gated by three conditions. The linked interment schedule must still be
    SCHEDULED."

    Design: Difficulty/cross_entity_state_dependency/honors_confirm_requires_scheduled_interment
    """
    cem, sec, grv, case, sched = setup_scheduled_case(
        window_start="2026-06-10T10:00:00Z", window_end="2026-06-10T12:00:00Z",
        depth_capacity=1, honors_squad_capacity=2,
    )
    hon = request_honors(cem["id"], sched["id"], detail_size="TWO_PERSON")
    confirmed = validate_success(api.confirm_military_honors(cem["id"], hon["id"], HONORS))
    assert confirmed["status"] == "CONFIRMED"


# ===========================================================================
# combinatorial_formula — marker charge sum-then-allowance rounding order
# ===========================================================================
def test_marker_charge_sum_then_allowance_rounding(api):
    """PRD §3.6: "First, count the exact number of characters in each line of
    inscription_lines, then sum those per-line counts into a single total across all
    lines. If an emblem_of_belief is present, add a further 15 characters to that
    total; otherwise add nothing. From this figure subtract a free allowance of 60
    characters, and if the result is negative treat it as zero — the allowance is
    applied once against the summed total, never per line."
    PRD §3.6: "divide the billable characters by a block size of 10 characters, round
    up to the next whole block, and multiply the number of whole blocks by 250 cents;
    the product is marker_charge_cents."

    Design: Difficulty/combinatorial_formula/marker_charge_sum_then_allowance_rounding_order
    """
    cem, sec, grv, case = setup_assigned_case(depth_capacity=1, honors_squad_capacity=1)
    mk = create_marker(
        cem["id"], case["id"], marker_type="UPRIGHT_MARBLE",
        inscription_lines=[
            "JOHN QUINCY ADAMS PATRIOT VETERAN OF THE",  # 40
            "UNITED STATES ARMY SERVED WITH HONOR AND",  # 40
            "DEVOTION FOREVER REMEM",                    # 22
        ],
        emblem_of_belief="CHRISTIAN_CROSS",
    )
    submitted = validate_success(api.submit_marker_order(cem["id"], mk["id"], MARKER))
    # 102 + 15 emblem - 60 = 57 billable; ceil(57/10)=6 blocks * 250 = 1500
    assert submitted["billable_characters"] == 57
    assert submitted["marker_charge_cents"] == 1500
    assert submitted["status"] == "SUBMITTED"


def test_marker_charge_allowance_applied_once_not_per_line(api):
    """PRD §3.6: "From this figure subtract a free allowance of 60 characters, and if
    the result is negative treat it as zero — the allowance is applied once against
    the summed total, never per line."
    PRD §3.6: "divide the billable characters by a block size of 10 characters, round
    up to the next whole block, and multiply the number of whole blocks by 250 cents;
    the product is marker_charge_cents."

    Design: Difficulty/combinatorial_formula/marker_charge_sum_then_allowance_rounding_order
    """
    cem, sec, grv, case = setup_assigned_case(depth_capacity=1, honors_squad_capacity=1)
    # Three 30-char lines = 90 total, no emblem. Sum-then-allowance: 90-60=30
    # -> ceil(30/10)=3 blocks * 250 = 750. Per-line allowance would zero every line.
    mk = create_marker(
        cem["id"], case["id"], marker_type="FLAT_GRANITE",
        inscription_lines=["A" * 30, "B" * 30, "C" * 30],
    )
    submitted = validate_success(api.submit_marker_order(cem["id"], mk["id"], MARKER))
    assert submitted["billable_characters"] == 30
    assert submitted["marker_charge_cents"] == 750


def test_marker_charge_free_allowance_boundary_zero(api):
    """PRD §3.6: "From this figure subtract a free allowance of 60 characters, and if
    the result is negative treat it as zero — the allowance is applied once against
    the summed total, never per line."

    Design: Corner/calculations/marker_charge_free_allowance_boundary_zero
    """
    cem, sec, grv, case = setup_assigned_case(depth_capacity=1, honors_squad_capacity=1)
    mk = create_marker(
        cem["id"], case["id"], marker_type="FLAT_BRONZE",
        inscription_lines=["A" * 40, "B" * 20],  # exactly 60, no emblem
    )
    submitted = validate_success(api.submit_marker_order(cem["id"], mk["id"], MARKER))
    assert submitted["billable_characters"] == 0
    assert submitted["marker_charge_cents"] == 0


# ===========================================================================
# Corner: validations — inscription line too long, full-squad entitlement
# ===========================================================================
def test_inscription_line_too_long_rejected(api):
    """PRD §3.6: "The inscription must be within limits: no more than 6 lines, and
    each individual line no longer than 40 characters; a violation is rejected with
    ERR_INSCRIPTION_LIMIT_EXCEEDED."

    Design: Corner/validations/inscription_line_too_long_rejected
    """
    cem, sec, grv, case = setup_assigned_case(depth_capacity=1, honors_squad_capacity=1)
    mk = create_marker(
        cem["id"], case["id"], marker_type="UPRIGHT_MARBLE",
        inscription_lines=["A" * 41],  # 41 > 40
    )
    resp = api.submit_marker_order(cem["id"], mk["id"], MARKER)
    validate_error(resp, ApiErrorId.ERR_INSCRIPTION_LIMIT_EXCEEDED, expected_status=422)


def test_full_squad_honors_entitlement_insufficient(api):
    """PRD §3.8: "And a FULL_SQUAD detail requires that the case's entitlement_score
    be at least 110; a lesser score is rejected with
    ERR_HONORS_ENTITLEMENT_INSUFFICIENT."

    Design: Corner/validations/full_squad_honors_entitlement_insufficient
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=2)
    vet = open_and_approve_case(cem["id"])
    # DEPENDENT case: own discharge is ignored; score derives from the sponsor.
    dep_payload = {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "DEPENDENT",
        "requested_class": "STANDARD", "reserving_case_id": vet["id"], "service_days": 0,
    }
    dep = get_success_data(api.create_burial_case(cem["id"], dep_payload, OFFICER))
    api.run_eligibility(cem["id"], dep["id"], OFFICER)
    dep = validate_success(api.get_burial_case(cem["id"], dep["id"], OFFICER))
    # dependent score = 40 + sponsor service 30 + sponsor honorable 10 = 80 < 110
    assign_plot_auto(cem["id"], dep["id"])
    sched = create_schedule(cem["id"], dep["id"], "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z")
    hon = request_honors(cem["id"], sched["id"], detail_size="FULL_SQUAD")
    resp = api.confirm_military_honors(cem["id"], hon["id"], HONORS)
    validate_error(resp, ApiErrorId.ERR_HONORS_ENTITLEMENT_INSUFFICIENT, expected_status=422)


# ===========================================================================
# Corner: state_machines — engrave before case INTERRED
# ===========================================================================
def test_engrave_before_case_interred_invalid_state(api):
    """PRD §3.6: "Engraving a submitted order moves it from SUBMITTED to ENGRAVED,
    and is permitted only once the linked burial case has reached INTERRED."

    Design: Corner/state_machines/engrave_marker_before_case_interred_invalid_state
    """
    cem, sec, grv, case = setup_assigned_case(depth_capacity=1, honors_squad_capacity=1)
    mk = create_marker(
        cem["id"], case["id"], marker_type="FLAT_GRANITE", inscription_lines=["A VETERAN"]
    )
    validate_success(api.submit_marker_order(cem["id"], mk["id"], MARKER))
    resp = api.engrave_marker_order(cem["id"], mk["id"], MARKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
