"""Attorney assignment, caseload weighting, reassignment, and concurrency."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

CLERK = TEST_USERS["intake_clerk_headers"]
OFFICER = TEST_USERS["screening_officer_headers"]
COORD = TEST_USERS["assignment_coordinator_headers"]
SUPER = TEST_USERS["supervising_attorney_headers"]


# ===========================================================================
# Corner: provisional weight (FELONY_B)
# ===========================================================================

def test_provisional_case_weight_felony_b_value(api):
    """PRD 3.3: "On a successful assignment the case's provisional weight is
    computed as the base weight for its charge class alone — `FELONY_A` is 4.0,
    `FELONY_B` is 2.5, `MISDEMEANOR` is 1.0, `JUVENILE` is 1.5, and `APPEAL` is
    3.0 — and this becomes the case's `case_weight` with `weight_basis`
    `PROVISIONAL`."
    PRD 3.3: "A new `Assignment` is created in `ACTIVE` status whose
    `assigned_weight` snapshots that provisional `case_weight` at the moment it
    becomes active."

    Design: Corner/calculations/provisional_case_weight_felony_b_value
    """
    ctx = fx.setup_screened_case(case_overrides={"charge_class": "FELONY_B"},
                                 screening_overrides={"household_income_cents": 500_000})
    resp = api.create_assignment(
        {"case_id": ctx["case"]["id"], "attorney_id": ctx["attorney"]["id"]}, COORD)
    asg = validate_success(resp, 201)
    assert asg["assigned_weight"] == pytest.approx(2.5)
    case = validate_success(api.get_case(ctx["case"]["id"], CLERK), 200)
    assert case["case_weight"] == pytest.approx(2.5)
    assert case["weight_basis"] == "PROVISIONAL"
    att = validate_success(api.get_attorney(ctx["attorney"]["id"], CLERK), 200)
    assert att["current_weighted_load"] == pytest.approx(2.5)


# ===========================================================================
# Difficulty: dual-variant case weight (provisional vs actual)
# ===========================================================================

def test_provisional_weight_snapshot_at_assignment(api):
    """PRD 3.3: "A new `Assignment` is created in `ACTIVE` status whose
    `assigned_weight` snapshots that provisional `case_weight` at the moment it
    becomes active."

    Design: Difficulty/dual_variant_calc/case_weight_provisional_vs_actual
    """
    ctx = fx.setup_screened_case(attorney_overrides={"max_weighted_caseload": 10.0},
                                 case_overrides={"charge_class": "MISDEMEANOR"},
                                 screening_overrides={"household_income_cents": 1_000_000,
                                                      "asset_value_cents": 100_000})
    asg = validate_success(api.create_assignment(
        {"case_id": ctx["case"]["id"], "attorney_id": ctx["attorney"]["id"]}, COORD), 201)
    assert asg["assigned_weight"] == pytest.approx(1.0)
    case = validate_success(api.get_case(ctx["case"]["id"], CLERK), 200)
    assert case["weight_basis"] == "PROVISIONAL"


def test_adjust_weight_recomputes_actual_basis(api):
    """PRD 3.4: "Adjustment recomputes the case to the actual basis: multiply
    the charge class's base weight by the complexity multiplier — `STANDARD` is
    1.0, `COMPLEX` is 1.5, `CAPITAL` is 2.0 — then add a co-defendant increment
    of 0.25 for each co-defendant, and round the total half up to two decimal
    places."
    PRD 3.4: "Because the weight changed, the case's `ACTIVE` `Assignment` has
    its `assigned_weight` updated to the new value and the holding attorney's
    `current_weighted_load` is recomputed."

    Design: Difficulty/dual_variant_calc/case_weight_provisional_vs_actual
    """
    ctx = fx.setup_assigned_case(attorney_overrides={"max_weighted_caseload": 10.0},
                                 case_overrides={"charge_class": "MISDEMEANOR"},
                                 screening_overrides={"household_income_cents": 1_000_000,
                                                      "asset_value_cents": 100_000})
    # MISDEMEANOR base 1.0 * COMPLEX 1.5 + 0.25*2 = 2.0
    resp = api.adjust_weight(ctx["case"]["id"],
                             {"complexity_tier": "COMPLEX", "co_defendant_count": 2}, COORD)
    case = validate_success(resp, 200)
    assert case["case_weight"] == pytest.approx(2.0)
    assert case["weight_basis"] == "ACTUAL"
    att = validate_success(api.get_attorney(ctx["attorney"]["id"], CLERK), 200)
    assert att["current_weighted_load"] == pytest.approx(2.0)


# ===========================================================================
# Difficulty: caseload capacity inclusive-at-max boundary
# ===========================================================================

def test_assignment_accepted_when_load_lands_exactly_at_max(api):
    """PRD 3.3: "Capacity is judged inclusively: the attorney's current active
    load plus the provisional weight of this case must be no greater than the
    attorney's `max_weighted_caseload`; a load landing exactly at the maximum is
    allowed, and only a result strictly above it is rejected."
    PRD 3.3: "if that load reaches or exceeds `max_weighted_caseload` the
    attorney's `status` flips to `AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/caseload_capacity_inclusive_max
    """
    ctx = fx.setup_screened_case(attorney_overrides={"max_weighted_caseload": 4.0},
                                 case_overrides={"charge_class": "FELONY_A"},
                                 screening_overrides={"household_income_cents": 500_000})
    validate_success(api.create_assignment(
        {"case_id": ctx["case"]["id"], "attorney_id": ctx["attorney"]["id"]}, COORD), 201)
    att = validate_success(api.get_attorney(ctx["attorney"]["id"], CLERK), 200)
    assert att["current_weighted_load"] == pytest.approx(4.0)
    assert att["status"] == "AT_CAPACITY"


def test_assignment_rejected_when_load_would_exceed_max(api):
    """PRD 3.3: "Capacity is judged inclusively: the attorney's current active
    load plus the provisional weight of this case must be no greater than the
    attorney's `max_weighted_caseload`; a load landing exactly at the maximum is
    allowed, and only a result strictly above it is rejected."
    PRD 3.3: "the attorney must have room, else `ERR_CASELOAD_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/caseload_capacity_inclusive_max
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], max_weighted_caseload=4.0)
    # First fill to exactly 4.0 with a FELONY_A.
    ca = fx.create_case(office["id"], defendant_name="Fa", charge_class="FELONY_A")
    sa = fx.submit_screening(ca["id"], household_income_cents=500_000)
    fx.decide_screening(sa["id"])
    fx.create_conflict_check(ca["id"], attorney["id"])
    fx.create_assignment(ca["id"], attorney["id"])
    # Second MISDEMEANOR (1.0) would push to 5.0 > 4.0.
    cb = fx.create_case(office["id"], defendant_name="Mi", charge_class="MISDEMEANOR")
    sb = fx.submit_screening(cb["id"], household_income_cents=500_000)
    fx.decide_screening(sb["id"])
    fx.create_conflict_check(cb["id"], attorney["id"])
    resp = api.create_assignment({"case_id": cb["id"], "attorney_id": attorney["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_CASELOAD_CAPACITY_EXCEEDED.value)
    att = validate_success(api.get_attorney(attorney["id"], CLERK), 200)
    assert att["current_weighted_load"] == pytest.approx(4.0)


# ===========================================================================
# Difficulty: assignment requires attorney not suspended
# ===========================================================================

def test_assign_suspended_attorney_rejected(api):
    """PRD 3.3: "the target attorney must not be `SUSPENDED`, else
    `ERR_ATTORNEY_NOT_ACTIVE`;"

    Design: Difficulty/cross_entity_state_dependency/assign_requires_attorney_not_suspended
    """
    ctx = fx.setup_screened_case(screening_overrides={"household_income_cents": 800_000})
    validate_success(api.suspend_attorney(ctx["attorney"]["id"], SUPER), 200)
    resp = api.create_assignment(
        {"case_id": ctx["case"]["id"], "attorney_id": ctx["attorney"]["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_ATTORNEY_NOT_ACTIVE.value)


def test_assign_suspended_attorney_leaves_case_screened(api):
    """PRD 3.3: "the case must be in `SCREENED` status, else
    `ERR_CASE_NOT_SCREENED`; the target attorney must not be `SUSPENDED`, else
    `ERR_ATTORNEY_NOT_ACTIVE`;"

    Design: Difficulty/cross_entity_state_dependency/assign_requires_attorney_not_suspended
    """
    ctx = fx.setup_screened_case(screening_overrides={"household_income_cents": 800_000})
    validate_success(api.suspend_attorney(ctx["attorney"]["id"], SUPER), 200)
    api.create_assignment(
        {"case_id": ctx["case"]["id"], "attorney_id": ctx["attorney"]["id"]}, COORD)
    case = validate_success(api.get_case(ctx["case"]["id"], CLERK), 200)
    assert case["status"] == "SCREENED"
    body = api.list_assignments(COORD, params={"case_id": ctx["case"]["id"]}).json()
    assert body["meta"]["total_count"] == 0


# ===========================================================================
# Difficulty: validation precedence — state beats conflict-safety
# ===========================================================================

def test_assign_referred_case_returns_state_error_not_conflict(api):
    """PRD 3.3: "the case must be in `SCREENED` status, else
    `ERR_CASE_NOT_SCREENED`; the target attorney must not be `SUSPENDED`, else
    `ERR_ATTORNEY_NOT_ACTIVE`; a `ConflictCheck` for exactly this case and
    attorney with `result` `CLEAR` must already exist, else
    `ERR_CONFLICT_NOT_CLEARED`;"

    Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_safety
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"])
    # Case is still REFERRED (no decided screening) and has NO conflict check.
    case = fx.create_case(office["id"], defendant_name="Pre")
    resp = api.create_assignment({"case_id": case["id"], "attorney_id": attorney["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_SCREENED.value)


def test_assign_referred_case_creates_no_assignment(api):
    """PRD 2.7: "(5) The target resource is in the correct state for the
    operation, else the operation's state error (for example
    `ERR_CASE_NOT_SCREENED` ... (7) Conflict clearance for assignment, else
    `ERR_CONFLICT_NOT_CLEARED`."

    Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_safety
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"])
    case = fx.create_case(office["id"], defendant_name="Pre2")
    api.create_assignment({"case_id": case["id"], "attorney_id": attorney["id"]}, COORD)
    body = api.list_assignments(COORD, params={"case_id": case["id"]}).json()
    assert body["meta"]["total_count"] == 0


# ===========================================================================
# Difficulty: caseload weight conserved on reassign
# ===========================================================================

def test_reassign_moves_load_from_prior_to_new_attorney(api):
    """PRD 3.3: "the prior `ACTIVE` `Assignment` transitions to `REASSIGNED` and
    the prior attorney's `current_weighted_load` decreases by that assignment's
    weight ... a new `Assignment` is created `ACTIVE` with `assigned_weight`
    equal to the case's current `case_weight`, the new attorney's
    `current_weighted_load` increases accordingly"

    Design: Difficulty/compensating_invariant/caseload_weight_conserved_on_reassign
    """
    office = fx.create_office()
    att_a = fx.create_attorney(office["id"], name="Ia", bar_number="II1")
    att_b = fx.create_attorney(office["id"], name="Ib", bar_number="II2")
    case = fx.create_case(office["id"], defendant_name="In", charge_class="MISDEMEANOR")
    scr = fx.submit_screening(case["id"])
    fx.decide_screening(scr["id"])
    fx.create_conflict_check(case["id"], att_a["id"])
    fx.create_conflict_check(case["id"], att_b["id"])
    fx.create_assignment(case["id"], att_a["id"])
    cv = validate_success(api.get_case(case["id"], COORD), 200)["version"]
    validate_success(api.reassign_case(
        case["id"], {"new_attorney_id": att_b["id"], "expected_case_version": cv}, COORD), 200)
    a = validate_success(api.get_attorney(att_a["id"], CLERK), 200)
    b = validate_success(api.get_attorney(att_b["id"], CLERK), 200)
    assert a["current_weighted_load"] == pytest.approx(0.0)
    assert b["current_weighted_load"] == pytest.approx(1.0)


def test_reassign_conserves_total_load(api):
    """PRD 2.5: "An `Attorney`'s `current_weighted_load` always equals the sum
    of `assigned_weight` across that attorney's `Assignment` records in `ACTIVE`
    status; it starts at 0, rises when an assignment becomes active, and falls
    when one leaves the active state."

    Design: Difficulty/compensating_invariant/caseload_weight_conserved_on_reassign
    """
    office = fx.create_office()
    att_a = fx.create_attorney(office["id"], name="Ja", bar_number="JJ1")
    att_b = fx.create_attorney(office["id"], name="Jb", bar_number="JJ2")
    case = fx.create_case(office["id"], defendant_name="Jn", charge_class="MISDEMEANOR")
    scr = fx.submit_screening(case["id"])
    fx.decide_screening(scr["id"])
    fx.create_conflict_check(case["id"], att_a["id"])
    fx.create_conflict_check(case["id"], att_b["id"])
    fx.create_assignment(case["id"], att_a["id"])
    cv = validate_success(api.get_case(case["id"], COORD), 200)["version"]
    validate_success(api.reassign_case(
        case["id"], {"new_attorney_id": att_b["id"], "expected_case_version": cv}, COORD), 200)
    a = validate_success(api.get_attorney(att_a["id"], CLERK), 200)
    b = validate_success(api.get_attorney(att_b["id"], CLERK), 200)
    assert a["current_weighted_load"] + b["current_weighted_load"] == pytest.approx(1.0)


# ===========================================================================
# Corner: reassign stale case version (OCC)
# ===========================================================================

def test_reassign_stale_case_version_occ_conflict(api):
    """PRD 2.8: "Its value must equal the target `Case`'s current `version`. If
    another writer has already advanced the case's version since the client last
    read it — for instance because a prior reassignment succeeded and
    legitimately superseded the earlier assignment — then the client's view is
    stale, and the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP
    status 412."

    Design: Corner/cross_cutting_complexity_layers/reassign_stale_case_version_occ_conflict
    """
    office = fx.create_office()
    att_a = fx.create_attorney(office["id"], name="Oa", bar_number="O1")
    att_b = fx.create_attorney(office["id"], name="Ob", bar_number="O2")
    att_c = fx.create_attorney(office["id"], name="Oc", bar_number="O3")
    case = fx.create_case(office["id"], defendant_name="Oo", charge_class="MISDEMEANOR")
    scr = fx.submit_screening(case["id"])
    fx.decide_screening(scr["id"])
    for a in (att_a, att_b, att_c):
        fx.create_conflict_check(case["id"], a["id"])
    fx.create_assignment(case["id"], att_a["id"])
    cv = validate_success(api.get_case(case["id"], COORD), 200)["version"]
    # First reassign with fresh version succeeds and advances version.
    validate_success(api.reassign_case(
        case["id"], {"new_attorney_id": att_b["id"], "expected_case_version": cv}, COORD), 200)
    # Second reassign carrying the stale version is rejected.
    resp = api.reassign_case(
        case["id"], {"new_attorney_id": att_c["id"], "expected_case_version": cv}, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION.value)
    c = validate_success(api.get_attorney(att_c["id"], CLERK), 200)
    assert c["current_weighted_load"] == pytest.approx(0.0)


# ===========================================================================
# Corner: conflict check detects conflict, blocks assignment
# ===========================================================================

def test_conflict_check_detects_conflict_blocks_assignment(api):
    """PRD 3.3: "it is `CONFLICT` if any supplied co-defendant name equals the
    `defendant_name` of some other case that currently has an `ACTIVE`
    `Assignment` to that same attorney, and `CLEAR` otherwise."
    PRD 3.3: "a `ConflictCheck` for exactly this case and attorney with `result`
    `CLEAR` must already exist, else `ERR_CONFLICT_NOT_CLEARED`;"

    Design: Corner/errors/conflict_check_detects_conflict_blocks_assignment
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Er", bar_number="E1")
    # caseX with defendant 'Zoe' actively assigned to the attorney.
    cx = fx.create_case(office["id"], defendant_name="Zoe", charge_class="MISDEMEANOR")
    sx = fx.submit_screening(cx["id"])
    fx.decide_screening(sx["id"])
    fx.create_conflict_check(cx["id"], attorney["id"])
    fx.create_assignment(cx["id"], attorney["id"])
    # caseY screened; conflict check naming 'Zoe' -> CONFLICT.
    cy = fx.create_case(office["id"], defendant_name="Yan", charge_class="MISDEMEANOR")
    sy = fx.submit_screening(cy["id"])
    fx.decide_screening(sy["id"])
    cc = fx.create_conflict_check(cy["id"], attorney["id"], co_defendant_names=["Zoe"])
    assert cc["result"] == "CONFLICT"
    resp = api.create_assignment({"case_id": cy["id"], "attorney_id": attorney["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_CONFLICT_NOT_CLEARED.value)


# ===========================================================================
# Corner: attorney status suspend/reactivate
# ===========================================================================

def test_suspend_then_reactivate_valid_transition(api):
    """PRD 3.4: "a `SupervisingAttorney` may suspend an attorney (from either
    `ACTIVE` or `AT_CAPACITY`) ... A `SupervisingAttorney` may reactivate a
    suspended attorney; on reactivation the attorney returns to `ACTIVE`, unless
    the current `current_weighted_load` already meets or exceeds
    `max_weighted_caseload`, in which case they resolve to `AT_CAPACITY`
    instead."

    Design: Corner/state_machines/suspend_then_reactivate_valid_transition
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Sy", bar_number="S3")
    suspended = validate_success(api.suspend_attorney(attorney["id"], SUPER), 200)
    assert suspended["status"] == "SUSPENDED"
    reactivated = validate_success(api.reactivate_attorney(attorney["id"], SUPER), 200)
    assert reactivated["status"] == "ACTIVE"


# ===========================================================================
# Corner: RBAC — IntakeClerk cannot create assignment
# ===========================================================================

def test_intake_clerk_cannot_create_assignment(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/intake_clerk_cannot_create_assignment
    """
    ctx = fx.setup_screened_case(screening_overrides={"household_income_cents": 800_000})
    resp = api.create_assignment(
        {"case_id": ctx["case"]["id"], "attorney_id": ctx["attorney"]["id"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    body = api.list_assignments(COORD, params={"case_id": ctx["case"]["id"]}).json()
    assert body["meta"]["total_count"] == 0


# ===========================================================================
# Corner: consistency — assignment side effects visible immediately
# ===========================================================================

def test_assignment_side_effects_visible_immediately(api):
    """PRD 3.3: "The case advances to `ASSIGNED` and its `assigned_attorney_id`
    is set to the attorney."
    PRD 2.5: "the derived status fields that depend on that aggregate
    (`Attorney.status`, `DefenderOffice.budget_status`) are re-evaluated in the
    same operation so the stored value never lags the aggregate."

    Design: Corner/consistency_model/assignment_side_effects_visible_immediately
    """
    ctx = fx.setup_assigned_case(screening_overrides={"household_income_cents": 800_000})
    case = validate_success(api.get_case(ctx["case"]["id"], COORD), 200)
    assert case["status"] == "ASSIGNED"
    assert case["assigned_attorney_id"] == ctx["attorney"]["id"]
