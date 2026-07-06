"""Disposition cascade (assignment close -> load -> attorney status) and
recoupment: SCHEDULE-vs-ACTUAL assessment, collection lockdown, and
segregation-of-duties on waiver."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import make_supervising_attorney_headers

COORD = TEST_USERS["assignment_coordinator_headers"]
SUPER = TEST_USERS["supervising_attorney_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]


# ===========================================================================
# Difficulty: dispose cascade — assignment CLOSED -> load drops -> AT_CAPACITY reverts (depth 3)
# ===========================================================================

def test_dispose_closes_assignment_and_drops_load(api):
    """PRD 3.3: "if that load reaches or exceeds `max_weighted_caseload` the
    attorney's `status` flips to `AT_CAPACITY`."
    PRD 3.8: "Disposition then cascades in a chain: the case's `ACTIVE`
    `Assignment` closes (transitions to `CLOSED`); because that assignment
    closed, the holding attorney's `current_weighted_load` decreases by that
    assignment's `assigned_weight`; and because that load dropped, if the
    attorney was `AT_CAPACITY` and their load now sits below their
    `max_weighted_caseload`, the attorney reverts to `ACTIVE`."

    Design: Difficulty/transitive_cascade/dispose_cascade_assignment_load_status_depth3
    """
    ctx = fx.setup_assigned_case(attorney_overrides={"max_weighted_caseload": 4.0},
                                 case_overrides={"charge_class": "FELONY_A"},
                                 screening_overrides={"household_income_cents": 500_000})
    att_id = ctx["attorney"]["id"]
    before = validate_success(api.get_attorney(att_id, CLERK), 200)
    assert before["current_weighted_load"] == pytest.approx(4.0)
    assert before["status"] == "AT_CAPACITY"

    validate_success(api.dispose_case(ctx["case"]["id"], {"disposition_type": "DISMISSED"}, COORD), 200)

    asg = validate_success(api.get_assignment(ctx["assignment"]["id"], CLERK), 200)
    assert asg["status"] == "CLOSED"
    att = validate_success(api.get_attorney(att_id, CLERK), 200)
    assert att["current_weighted_load"] == pytest.approx(0.0)


def test_dispose_reverts_attorney_from_at_capacity_to_active(api):
    """PRD 3.8: "because that load dropped, if the attorney was `AT_CAPACITY` and
    their load now sits below their `max_weighted_caseload`, the attorney reverts
    to `ACTIVE`."

    Design: Difficulty/transitive_cascade/dispose_cascade_assignment_load_status_depth3
    """
    ctx = fx.setup_assigned_case(attorney_overrides={"max_weighted_caseload": 4.0},
                                 case_overrides={"charge_class": "FELONY_A"},
                                 screening_overrides={"household_income_cents": 500_000})
    att_id = ctx["attorney"]["id"]
    validate_success(api.dispose_case(ctx["case"]["id"], {"disposition_type": "DISMISSED"}, COORD), 200)
    att = validate_success(api.get_attorney(att_id, CLERK), 200)
    assert att["status"] == "ACTIVE"


# ===========================================================================
# Difficulty: recoupment SCHEDULE vs ACTUAL basis
# ===========================================================================

def test_recoupment_schedule_basis_uses_statutory_schedule(api):
    """PRD 3.8: "If the case's decided `FinancialScreening` had a `result` of
    `PARTIAL`, the server automatically creates a `RecoupmentOrder` against the
    case in `status` `ASSESSED`, with `collected_amount_cents` 0."
    PRD 3.8: "Under a `SCHEDULE` basis the assessed amount is the flat statutory
    figure for the charge class — $500 (50,000 cents) for `FELONY_A`, $400
    (40,000 cents) for `FELONY_B`, $150 (15,000 cents) for `MISDEMEANOR`, $100
    (10,000 cents) for `JUVENILE`, and $350 (35,000 cents) for `APPEAL`."

    Design: Difficulty/dual_variant_calc/recoupment_schedule_vs_actual
    """
    # MISDEMEANOR PARTIAL case (income 3000000, size 2, asset 500000) under SCHEDULE.
    ctx = fx.setup_partial_case_recoupment(office_overrides={"recoupment_basis": "SCHEDULE"})
    order = ctx["recoupment_order"]
    assert order is not None, "PARTIAL disposition must auto-create a RecoupmentOrder"
    assert order["basis"] == "SCHEDULE"
    assert order["assessed_amount_cents"] == 15_000


def test_recoupment_actual_basis_uses_screening_contribution(api):
    """PRD 3.8: "Under an `ACTUAL` basis the assessed amount is the means-based
    `contribution_amount_cents` from the case's decided screening, which can
    differ from the schedule figure for identical case data."

    Design: Difficulty/dual_variant_calc/recoupment_schedule_vs_actual
    """
    # Same PARTIAL case data (contribution 50000) under an ACTUAL office.
    ctx = fx.setup_partial_case_recoupment(office_overrides={"recoupment_basis": "ACTUAL"})
    order = ctx["recoupment_order"]
    assert order is not None, "PARTIAL disposition must auto-create a RecoupmentOrder"
    assert order["basis"] == "ACTUAL"
    assert order["assessed_amount_cents"] == 50_000


# ===========================================================================
# Corner: collect on a SATISFIED order is not collectible
# ===========================================================================

def test_recoupment_collect_on_satisfied_not_collectible(api):
    """PRD 3.8: "A single payment at or above the full assessed amount takes an
    `ASSESSED` order straight to `SATISFIED`."
    PRD 3.8: "Collection is allowed only while the order is `ASSESSED` or
    `PARTIALLY_COLLECTED` (else `ERR_RECOUPMENT_NOT_COLLECTIBLE`) and the amount
    must be positive."

    Design: Corner/errors/recoupment_collect_on_satisfied_not_collectible
    """
    ctx = fx.setup_partial_case_recoupment(office_overrides={"recoupment_basis": "SCHEDULE"})
    ro_id = ctx["recoupment_order"]["id"]
    satisfied = validate_success(api.collect_recoupment(ro_id, {"amount_cents": 15_000}, SUPER), 200)
    assert satisfied["status"] == "SATISFIED"
    assert satisfied["collected_amount_cents"] == 15_000
    resp = api.collect_recoupment(ro_id, {"amount_cents": 1_000}, SUPER)
    validate_error(resp, ApiErrorId.ERR_RECOUPMENT_NOT_COLLECTIBLE.value)


# ===========================================================================
# Corner: recoupment waiver segregation of duties
# ===========================================================================

def test_recoupment_waive_segregation_of_duties(api):
    """PRD 3.8: "Alternatively, a `SupervisingAttorney` may waive an outstanding
    order, which requires the order to be `ASSESSED` or `PARTIALLY_COLLECTED`
    (else `ERR_RECOUPMENT_NOT_COLLECTIBLE`) and moves it to the terminal
    `WAIVED`, recording the waiving user into `waived_by_user_id`."
    PRD 3.8: "Waiver enforces segregation of duties: the `X-User-ID` performing
    the waiver must differ from the `decided_by_user_id` recorded on that case's
    `FinancialScreening`."

    Design: Corner/rbac/recoupment_waive_segregation_of_duties
    """
    # The screening was decided by user 'u1'; recoupment order in ASSESSED.
    ctx = fx.setup_partial_case_recoupment(office_overrides={"recoupment_basis": "SCHEDULE"},
                                           officer_user_id="u1")
    ro_id = ctx["recoupment_order"]["id"]
    # Waiving as 'u1' (== decided_by_user_id) is blocked.
    resp = api.waive_recoupment(ro_id, make_supervising_attorney_headers("u1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    # Waiving as a different user 'u2' succeeds.
    waived = validate_success(api.waive_recoupment(ro_id, make_supervising_attorney_headers("u2")), 200)
    assert waived["status"] == "WAIVED"
    assert waived["waived_by_user_id"] == "u2"
