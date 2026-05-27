"""Validation-priority conflicts (PRD §2.11) and resource temporal overlap
(PRD §3.7 election window; §3.8 reserve study uniqueness)."""
from test_helpers import (
    ApiErrorId,
    apply_payment,
    bootstrap_acc_request_on_suspended_property,
    bootstrap_election_open_with_voters,
    bootstrap_paid_assessment,
    bootstrap_tenant,
    create_acc_request,
    create_assessment,
    create_community,
    create_election,
    create_reserve_component,
    create_reserve_study,
    get_assessment,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_acc_member_headers,
    make_board_president_headers,
    make_board_secretary_headers,
    make_treasurer_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 5 instance 1: state vs business_fiscal priority — paid + overpay
# ─────────────────────────────────────────────────────────────────────────────

def test_overpay_on_paid_assessment_returns_invalid_state_not_overpayment(api):
    """PRD §2.11: "State-machine eligibility (`ERR_INVALID_STATE`) is checked
    before any business rule."
    PRD §3.2: "When `outstanding_cents` reaches zero by either of the two
    paths (a payment on a `DUE` assessment or on an `OVERDUE` assessment),
    the assessment transitions to `PAID`."

    Setup: Assessment fully paid → status == PAID. Submit another payment
    with amount way over the (already-zero) remaining outstanding. Two
    rules are violated simultaneously: the state precondition (PAID is
    terminal, not a from-state for payment) and the fiscal cap
    (overpayment). PRD §2.11 says state fires first → ERR_INVALID_STATE,
    NOT ERR_OVERPAYMENT.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_overpay_on_already_paid_returns_invalid_state
    """
    _community, _owner, _prop, paid = bootstrap_paid_assessment(
        community_name="Prio1", unit_label="P-1",
    )
    assert paid["status"] == "PAID"
    resp = api.create_payment(
        {
            "assessment_id": paid["id"],
            "amount_cents": 999999,
            "expected_assessment_version": paid["version"],
        },
        make_treasurer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 5 instance 2: business_safety vs business_temporal — ACC approve on
# suspended property in window returns ERR_PROPERTY_SUSPENDED.
# ─────────────────────────────────────────────────────────────────────────────

def test_acc_approve_on_suspended_property_returns_property_suspended(api):
    """PRD §3.6: "They may approve, but only when the underlying property's
    `compliance_posture` is not `SUSPENDED` — a suspended property's ACC
    approval is refused with `ERR_PROPERTY_SUSPENDED`."
    PRD §2.11: "Within the business tier, safety beats temporal beats
    referential beats fiscal beats constraint — so on an attempted ACC
    approval, a `SUSPENDED` property surfaces as `ERR_PROPERTY_SUSPENDED`
    before any other business rule fires."

    Setup: Property forced to SUSPENDED via lien cascade; SUBMITTED ACC
    request on that property. Approve must reject with ERR_PROPERTY_SUSPENDED.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_acc_approve_on_suspended_property_in_window_returns_property_suspended
    """
    _community, _owner, _prop, acc, _lien = (
        bootstrap_acc_request_on_suspended_property(
            community_name="Susp", scope="LANDSCAPING",
            description="Plant olive tree",
        )
    )
    resp = api.approve_acc_request(acc["id"], make_acc_member_headers())
    validate_error(resp, ApiErrorId.ERR_PROPERTY_SUSPENDED)


def test_payment_on_due_assessment_with_overpayment_returns_overpayment(api):
    """PRD §3.2: "The system first verifies that `amount_cents` does not
    exceed `principal_cents + late_fee_cents - paid_cents` on the target
    assessment; if it does, the payment is rejected with `ERR_OVERPAYMENT`
    (no partial application — the entire request is refused)."

    Inverse companion of the priority test above: when the state precondition
    is satisfied (assessment in DUE), the fiscal cap fires correctly — proving
    the state-vs-fiscal precedence above isn't an artifact of always-failing
    fiscal checks.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_overpay_on_already_paid_returns_invalid_state
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Prio1-inv",
        owner_email="i@x.com",
        owner_name="I",
        unit_label="I-1",
        regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2027-06-01T00:00:00Z",
    )
    resp = api.create_payment(
        {
            "assessment_id": a["id"],
            "amount_cents": 15000,
            "expected_assessment_version": a["version"],
        },
        make_treasurer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


# ─────────────────────────────────────────────────────────────────────────────
# Rule 8 instance 1: ReserveStudy uniqueness per (community, fiscal_year)
# ─────────────────────────────────────────────────────────────────────────────

def test_duplicate_reserve_study_same_year_rejected(api):
    """PRD §3.8: "The pair `(community_id, fiscal_year)` must be unique;
    a duplicate yields `ERR_DUPLICATE_RESERVE_STUDY`."

    Setup: Create one ReserveStudy for 2026. A second study for the same
    community + fiscal_year must be refused with ERR_DUPLICATE_RESERVE_STUDY.

    Design: Difficulty/resource_temporal_overlap/reserve_study_uniqueness_per_community_year_unique_collision
    """
    community = create_community(name="Overlap1")
    create_reserve_component(
        community["id"], label="RoofA", useful_life_years=20,
        remaining_life_years=5, replacement_cost_cents=500000,
    )
    first = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=100000,
    )
    assert first["fiscal_year"] == 2026
    resp = api.create_reserve_study(
        {
            "community_id": community["id"],
            "fiscal_year": 2026,
            "method": "CASH_FLOW",
            "accumulated_funds_cents": 200000,
        },
        make_board_president_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESERVE_STUDY)


def test_distinct_fiscal_year_reserve_studies_both_succeed(api):
    """PRD §3.8: "The pair `(community_id, fiscal_year)` must be unique;
    a duplicate yields `ERR_DUPLICATE_RESERVE_STUDY`."

    Boundary partner: distinct fiscal_years for the same community must
    BOTH succeed — the uniqueness scope is the pair, not the community
    alone.

    Design: Difficulty/resource_temporal_overlap/reserve_study_uniqueness_per_community_year_unique_collision
    """
    community = create_community(name="Overlap1Inv")
    create_reserve_component(
        community["id"], label="RoofA", useful_life_years=20,
        remaining_life_years=5, replacement_cost_cents=500000,
    )
    rs1 = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=100000,
    )
    rs2 = create_reserve_study(
        community["id"], fiscal_year=2027, method="CASH_FLOW",
        accumulated_funds_cents=100000,
    )
    assert rs1["fiscal_year"] == 2026
    assert rs2["fiscal_year"] == 2027
    assert rs1["id"] != rs2["id"], "Distinct studies must have distinct ids"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 8 instance 2: BoardElection window must be ≥14 days
# ─────────────────────────────────────────────────────────────────────────────

def test_election_open_with_window_shorter_than_fourteen_days_rejected(api):
    """PRD §3.7: "The OPEN transition demands three preconditions in addition
    to the OCC requirement detailed in §2.8: the election is in `DRAFT`,
    the current wall clock `current_utc` is strictly before `opens_at`,
    and the ballot window `closes_at - opens_at` is at least 14 days. A
    window shorter than 14 days, or a request submitted after `opens_at`
    has already passed, is refused with `ERR_INVALID_ELECTION_WINDOW`."

    Setup: 9-day window (opens 02-01, closes 02-10). OPEN must reject
    with ERR_INVALID_ELECTION_WINDOW.

    Design: Difficulty/resource_temporal_overlap/election_window_must_be_at_least_14_days_aggregate_capacity_check
    """
    community, _o, _p = bootstrap_tenant(
        community_name="Overlap2",
        owner_email="ov2@x.com",
        owner_name="OV2",
        unit_label="OV2-1",
    )
    set_clock("2026-01-15T00:00:00Z")
    election = create_election(
        community["id"], cycle_label="FY-short",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-10T00:00:00Z",
    )
    resp = api.open_election(
        election["id"], community["version"], make_board_secretary_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ELECTION_WINDOW)


def test_election_open_after_opens_at_already_passed_rejected(api):
    """PRD §3.7: "The OPEN transition demands three preconditions in addition
    to the OCC requirement detailed in §2.8: the election is in `DRAFT`,
    the current wall clock `current_utc` is strictly before `opens_at`,
    and the ballot window `closes_at - opens_at` is at least 14 days. A
    window shorter than 14 days, or a request submitted after `opens_at`
    has already passed, is refused with `ERR_INVALID_ELECTION_WINDOW`."

    Setup: Window is 30 days (valid duration), but clock is advanced past
    `opens_at` before OPEN is called. OPEN must reject with
    ERR_INVALID_ELECTION_WINDOW per PRD's "or" branch.

    Design: Difficulty/resource_temporal_overlap/election_window_must_be_at_least_14_days_aggregate_capacity_check
    """
    community, _o, _p = bootstrap_tenant(
        community_name="OvLate", owner_email="ovl@x.com", owner_name="OVL",
        unit_label="OVL-1",
    )
    set_clock("2026-01-15T00:00:00Z")
    election = create_election(
        community["id"], cycle_label="FY-Late",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-03-15T00:00:00Z",
    )
    set_clock("2026-02-15T00:00:00Z")
    resp = api.open_election(
        election["id"], community["version"], make_board_secretary_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ELECTION_WINDOW)
