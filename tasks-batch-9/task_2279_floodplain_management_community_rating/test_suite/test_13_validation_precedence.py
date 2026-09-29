"""Validation precedence: which rule speaks when a request breaks two at once.

Every case here is grounded in the §2.8 numbered sequence, whose ordering the PRD
makes part of the contract, and each pair is exercised from both sides so that the
losing check is shown to be live rather than absent.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_property,
    add_structure,
    appeal_case,
    make_appeals_board_headers,
    make_property_owner_headers,
    open_cycle,
    raise_community_to_suspension,
    register_community,
    review_permit,
    set_clock,
    setup_approved_permit,
    setup_determined_case,
    setup_issued_permit,
    setup_submitted_standard,
    start_permit,
    submit_cycle,
    submit_permit,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["administrator_headers"]


# ==========================================================================
# Scenario builders
# ==========================================================================

def _suspended_community_with_issued_permit() -> dict:
    """An ISSUED permit whose community has since accumulated three CRITICAL
    violations — 36 raw points, `SUSPENDED`."""
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 70_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 2018,
            "market_value_usd": 320_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["violations"] = raise_community_to_suspension(scenario["property"]["id"])
    return scenario


def _determined_case_by_fpa_01() -> dict:
    """A `DETERMINED` `SUBSTANTIAL_IMPROVEMENT` case whose `determined_by_user_id`
    is `fpa-01`, inside an open appeal window."""
    return setup_determined_case(
        records=[
            {
                "record_type": "IMPROVEMENT",
                "event_date": "2026-05-01T00:00:00Z",
                "cost_usd": 120_000.00,
            }
        ],
        method="CUMULATIVE",
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": True,
            "construction_year": 1962,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )


def _approved_permit_and_a_stranger_parcel() -> dict:
    """An `APPROVED` permit on parcel one, plus a second parcel in the same
    community whose owner identifier is a stranger to that permit."""
    scenario = setup_approved_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 80_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 2015,
            "market_value_usd": 260_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["other_property"] = add_property(
        scenario["community"]["id"], scenario["panel"]["id"]
    )
    return scenario


def _past_due_clock_over_submitted_cycle(with_open_sibling: bool = False) -> dict:
    """A `SUBMITTED` 2026 cycle whose `due_at` of 2026-09-30 the clock has passed,
    in a community holding one `SUBMITTED` documentation package; optionally a
    still-`OPEN` 2027 cycle carrying the same passed deadline."""
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    scenario = {"community": community}
    scenario["standard"] = setup_submitted_standard(
        community["id"],
        activity_code="A430_FREEBOARD",
        documentation_cycle_year=2026,
        claimed_points=100,
    )
    cycle = open_cycle(
        community["id"],
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )
    scenario["cycle"] = submit_cycle(cycle["id"])
    if with_open_sibling:
        scenario["sibling_cycle"] = open_cycle(
            community["id"],
            cycle_year=2027,
            cycle_start_date="2027-01-01T00:00:00Z",
            cycle_end_date="2027-12-31T00:00:00Z",
            due_at="2026-09-30T00:00:00Z",
        )
    set_clock("2026-10-01T00:00:00Z")
    return scenario


# ==========================================================================
# Permit issuance: own-state gate (step 9) before the sanction gates (step 15)
# ==========================================================================

class TestIssuanceStateBeforeSanctionGate:

    def test_reissuing_an_issued_permit_reports_the_state_gate_not_suspension(self, api):
        """PRD §2.8: "Because a single request can violate several rules at once, the
        order in which checks run is part of the contract. The server evaluates in the
        following sequence and returns on the first failure."  Step 9: "**Own-state
        transition gate** — the target resource must be in a state that admits the
        requested transition, each endpoint raising its own HTTP 409:
        `ERR_PANEL_NOT_PENDING`, `ERR_PERMIT_NOT_SUBMITTABLE`,
        `ERR_PERMIT_NOT_UNDER_REVIEW`, `ERR_PERMIT_NOT_APPROVED`,
        `ERR_PERMIT_NOT_ISSUED`, `ERR_CERTIFICATE_NOT_REVIEWABLE`,
        `ERR_CERTIFICATE_NOT_DEFICIENT`, `ERR_DETERMINATION_NOT_OPEN`,
        `ERR_DETERMINATION_NOT_DETERMINED`, `ERR_APPEAL_NOT_PENDING`,
        `ERR_INSPECTION_NOT_SCHEDULED`, `ERR_INSPECTION_NOT_ASSESSED`,
        `ERR_VIOLATION_NOT_ACTIONABLE`, `ERR_ORDER_NOT_ACTIONABLE`,
        `ERR_LOSS_AREA_NOT_DESIGNATED`, `ERR_OUTREACH_NOT_IN_PROGRESS`,
        `ERR_OUTREACH_ALREADY_IN_PROGRESS`, `ERR_STANDARD_NOT_DRAFT`,
        `ERR_STANDARD_NOT_SUBMITTED`, `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_SUBMITTED`,
        and `ERR_CYCLE_NOT_CERTIFIABLE`."  Step 15: "**Community sanction gates** —
        suspension first (`ERR_COMMUNITY_SUSPENDED`), then probation
        (`ERR_COMMUNITY_ON_PROBATION`), both HTTP 403 and both evaluated only at permit
        issuance."  §3.4 states both checks of this endpoint together: "Issuance is
        refused unless the permit is `APPROVED` (`ERR_PERMIT_NOT_APPROVED`) and is gated
        on the community's enforcement posture."

        Design: Difficulty/priority_pair_validation_conflict/issue_state_precondition_outranks_community_suspension_gate
        """
        scenario = _suspended_community_with_issued_permit()

        validate_error(
            api.issue_permit(scenario["permit"]["id"], ADMIN),
            ApiErrorId.ERR_PERMIT_NOT_APPROVED,
        )

        permit = validate_success(api.get_permit(scenario["permit"]["id"], ADMIN))
        assert permit["status"] == "ISSUED"
        community = validate_success(api.get_community(scenario["community"]["id"], ADMIN))
        assert community["sanction_risk_points"] == 36
        assert community["compliance_posture"] == "SUSPENDED"

    def test_suspension_still_blocks_a_genuinely_approved_permit(self, api):
        """PRD §3.4: "A `SUSPENDED` community cannot issue any permit at all
        (`ERR_COMMUNITY_SUSPENDED`)."  §2.8 step 15: "**Community sanction gates** —
        suspension first (`ERR_COMMUNITY_SUSPENDED`), then probation
        (`ERR_COMMUNITY_ON_PROBATION`), both HTTP 403 and both evaluated only at permit
        issuance."  The tier that puts the community there is fixed: "The tier rule is
        inclusive on the worse side: a score of 25 points or more is `SUSPENDED`, a
        score of 10 points or more is `ON_PROBATION`, and anything lower is
        `GOOD_STANDING`."

        Design: Difficulty/priority_pair_validation_conflict/issue_state_precondition_outranks_community_suspension_gate
        """
        scenario = _suspended_community_with_issued_permit()
        second_structure = add_structure(
            scenario["property"]["id"],
            structure_use="RESIDENTIAL",
            pre_firm=False,
            construction_year=2020,
            market_value_usd=180_000.00,
            highest_adjacent_grade_ft=10.0,
        )
        second_permit = start_permit(
            scenario["property"]["id"],
            second_structure["id"],
            scenario["owner_headers"],
            project_type="NEW_CONSTRUCTION",
            declared_project_cost_usd=40_000.00,
            proposed_lowest_floor_elevation_ft=20.0,
        )
        submit_permit(second_permit["id"], scenario["owner_headers"])
        approved = review_permit(second_permit["id"], "APPROVE")
        assert approved["status"] == "APPROVED"

        validate_error(
            api.issue_permit(approved["id"], ADMIN),
            ApiErrorId.ERR_COMMUNITY_SUSPENDED,
        )

        permit = validate_success(api.get_permit(approved["id"], ADMIN))
        assert permit["status"] == "APPROVED"
        assert permit["issued_at"] is None


# ==========================================================================
# Appeal decision: own-state gate (step 9) before segregation of duties (step 17)
# ==========================================================================

class TestAppealDecisionStateBeforeSegregationOfDuties:

    def test_self_decision_on_a_determined_case_reports_the_state_gate(self, api):
        """PRD §2.8: "The server evaluates in the following sequence and returns on the
        first failure."  Step 9: "**Own-state transition gate** — the target resource
        must be in a state that admits the requested transition, each endpoint raising
        its own HTTP 409: `ERR_PANEL_NOT_PENDING`, `ERR_PERMIT_NOT_SUBMITTABLE`,
        `ERR_PERMIT_NOT_UNDER_REVIEW`, `ERR_PERMIT_NOT_APPROVED`,
        `ERR_PERMIT_NOT_ISSUED`, `ERR_CERTIFICATE_NOT_REVIEWABLE`,
        `ERR_CERTIFICATE_NOT_DEFICIENT`, `ERR_DETERMINATION_NOT_OPEN`,
        `ERR_DETERMINATION_NOT_DETERMINED`, `ERR_APPEAL_NOT_PENDING`,
        `ERR_INSPECTION_NOT_SCHEDULED`, `ERR_INSPECTION_NOT_ASSESSED`,
        `ERR_VIOLATION_NOT_ACTIONABLE`, `ERR_ORDER_NOT_ACTIONABLE`,
        `ERR_LOSS_AREA_NOT_DESIGNATED`, `ERR_OUTREACH_NOT_IN_PROGRESS`,
        `ERR_OUTREACH_ALREADY_IN_PROGRESS`, `ERR_STANDARD_NOT_DRAFT`,
        `ERR_STANDARD_NOT_SUBMITTED`, `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_SUBMITTED`,
        and `ERR_CYCLE_NOT_CERTIFIABLE`."  Step 17: "**Segregation of duties** — an
        appeal decision by the same identifier recorded in `determined_by_user_id` is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."  §3.7 names both checks
        of this endpoint in one sentence: "The appeal is decided by an
        `AppealsBoardMember` with a `decision` of `SUSTAIN` or `DENY` and an optional
        `decision_note`, and only while the case is `APPEALED`, else
        `ERR_APPEAL_NOT_PENDING`."

        Design: Difficulty/priority_pair_validation_conflict/appeal_decision_state_precondition_outranks_segregation_of_duties
        """
        scenario = _determined_case_by_fpa_01()
        case_id = scenario["case"]["id"]
        assert scenario["case"]["determined_by_user_id"] == "fpa-01"

        validate_error(
            api.decide_appeal(
                case_id, {"decision": "DENY"}, make_appeals_board_headers("fpa-01")
            ),
            ApiErrorId.ERR_APPEAL_NOT_PENDING,
        )

        case = validate_success(api.get_determination_case(case_id, ADMIN))
        assert case["status"] == "DETERMINED"
        assert case["appeal_decided_by_user_id"] is None
        structure = validate_success(api.get_structure(scenario["structure"]["id"], ADMIN))
        assert structure["substantial_status"] == "SUBSTANTIAL_IMPROVEMENT"

    def test_segregation_of_duties_still_bites_once_the_case_is_appealed(self, api):
        """PRD §3.7: "Segregation of duties is absolute: the deciding identifier must
        differ from the `determined_by_user_id` recorded on the case, and a
        self-decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."  §2.8 step 17:
        "**Segregation of duties** — an appeal decision by the same identifier recorded
        in `determined_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."  The filing that puts the case in reach of that check: "Filing moves the
        case to `APPEALED` and stamps `appealed_at`."

        Design: Difficulty/priority_pair_validation_conflict/appeal_decision_state_precondition_outranks_segregation_of_duties
        """
        scenario = _determined_case_by_fpa_01()
        case_id = scenario["case"]["id"]
        appealed = appeal_case(case_id, scenario["owner_headers"])
        assert appealed["status"] == "APPEALED"

        validate_error(
            api.decide_appeal(
                case_id, {"decision": "DENY"}, make_appeals_board_headers("fpa-01")
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        case = validate_success(api.get_determination_case(case_id, ADMIN))
        assert case["status"] == "APPEALED"
        assert case["appeal_decided_by_user_id"] is None


# ==========================================================================
# Permit submit: ownership (step 4) before the own-state gate (step 9)
# ==========================================================================

class TestSubmitOwnershipBeforeStateGate:

    def test_a_stranger_resubmitting_an_approved_permit_reports_ownership(self, api):
        """PRD §2.8: "The server evaluates in the following sequence and returns on the
        first failure."  Step 4: "**Property-owner ownership** — when the acting role is
        `PropertyOwner`, the owning property must match `X-User-ID`, else
        `ERR_NOT_PROPERTY_OWNER`. This check guards exactly five operations: permit
        creation, permit submit or resubmit, elevation certificate filing, certificate
        amendment, and appeal filing."  Step 9: "**Own-state transition gate** — the
        target resource must be in a state that admits the requested transition, each
        endpoint raising its own HTTP 409: `ERR_PANEL_NOT_PENDING`,
        `ERR_PERMIT_NOT_SUBMITTABLE`, `ERR_PERMIT_NOT_UNDER_REVIEW`,
        `ERR_PERMIT_NOT_APPROVED`, `ERR_PERMIT_NOT_ISSUED`,
        `ERR_CERTIFICATE_NOT_REVIEWABLE`, `ERR_CERTIFICATE_NOT_DEFICIENT`,
        `ERR_DETERMINATION_NOT_OPEN`, `ERR_DETERMINATION_NOT_DETERMINED`,
        `ERR_APPEAL_NOT_PENDING`, `ERR_INSPECTION_NOT_SCHEDULED`,
        `ERR_INSPECTION_NOT_ASSESSED`, `ERR_VIOLATION_NOT_ACTIONABLE`,
        `ERR_ORDER_NOT_ACTIONABLE`, `ERR_LOSS_AREA_NOT_DESIGNATED`,
        `ERR_OUTREACH_NOT_IN_PROGRESS`, `ERR_OUTREACH_ALREADY_IN_PROGRESS`,
        `ERR_STANDARD_NOT_DRAFT`, `ERR_STANDARD_NOT_SUBMITTED`, `ERR_CYCLE_NOT_OPEN`,
        `ERR_CYCLE_NOT_SUBMITTED`, and `ERR_CYCLE_NOT_CERTIFIABLE`."  §3.4 states the
        submit endpoint's own two rules: "A submission is accepted from `DRAFT` or from
        `REVISION_REQUIRED`; from any other status it is rejected with
        `ERR_PERMIT_NOT_SUBMITTABLE`. The submitting owner's identifier must equal the
        permit's `property_id`."

        Design: Difficulty/priority_pair_validation_conflict/permit_submit_owner_check_outranks_state_precondition
        """
        scenario = _approved_permit_and_a_stranger_parcel()
        permit_id = scenario["permit"]["id"]
        stranger = make_property_owner_headers(scenario["other_property"]["id"])

        validate_error(
            api.submit_permit(permit_id, stranger),
            ApiErrorId.ERR_NOT_PROPERTY_OWNER,
        )

        permit = validate_success(api.get_permit(permit_id, ADMIN))
        assert permit["status"] == "APPROVED"
        assert permit["revision_round"] == 0

    def test_the_rightful_owner_meets_the_submittable_state_gate(self, api):
        """PRD §3.4: "A submission is accepted from `DRAFT` or from
        `REVISION_REQUIRED`; from any other status it is rejected with
        `ERR_PERMIT_NOT_SUBMITTABLE`."  And the resubmission counter only moves on an
        admitted resubmission: "On a resubmission out of `REVISION_REQUIRED`,
        `revision_round` first increases by one, and all three snapshots are refreshed
        from current community and panel state before the requirement is recomputed."

        Design: Difficulty/priority_pair_validation_conflict/permit_submit_owner_check_outranks_state_precondition
        """
        scenario = _approved_permit_and_a_stranger_parcel()
        permit_id = scenario["permit"]["id"]

        validate_error(
            api.submit_permit(permit_id, scenario["owner_headers"]),
            ApiErrorId.ERR_PERMIT_NOT_SUBMITTABLE,
        )

        permit = validate_success(api.get_permit(permit_id, ADMIN))
        assert permit["status"] == "APPROVED"
        assert permit["revision_round"] == 0


# ==========================================================================
# Cycle submit: own-state gate (step 9) before the due-date window (step 16)
# ==========================================================================

class TestCycleSubmitStateBeforePastDueWindow:

    def test_resubmitting_a_submitted_cycle_past_due_reports_the_state_gate(self, api):
        """PRD §2.8: "The server evaluates in the following sequence and returns on the
        first failure."  Step 9: "**Own-state transition gate** — the target resource
        must be in a state that admits the requested transition, each endpoint raising
        its own HTTP 409: `ERR_PANEL_NOT_PENDING`, `ERR_PERMIT_NOT_SUBMITTABLE`,
        `ERR_PERMIT_NOT_UNDER_REVIEW`, `ERR_PERMIT_NOT_APPROVED`,
        `ERR_PERMIT_NOT_ISSUED`, `ERR_CERTIFICATE_NOT_REVIEWABLE`,
        `ERR_CERTIFICATE_NOT_DEFICIENT`, `ERR_DETERMINATION_NOT_OPEN`,
        `ERR_DETERMINATION_NOT_DETERMINED`, `ERR_APPEAL_NOT_PENDING`,
        `ERR_INSPECTION_NOT_SCHEDULED`, `ERR_INSPECTION_NOT_ASSESSED`,
        `ERR_VIOLATION_NOT_ACTIONABLE`, `ERR_ORDER_NOT_ACTIONABLE`,
        `ERR_LOSS_AREA_NOT_DESIGNATED`, `ERR_OUTREACH_NOT_IN_PROGRESS`,
        `ERR_OUTREACH_ALREADY_IN_PROGRESS`, `ERR_STANDARD_NOT_DRAFT`,
        `ERR_STANDARD_NOT_SUBMITTED`, `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_SUBMITTED`,
        and `ERR_CYCLE_NOT_CERTIFIABLE`."  Step 16: "**Temporal windows** — the appeal
        window (`ERR_APPEAL_WINDOW_CLOSED`), then the inspection assessment window
        (`ERR_INSPECTION_WINDOW_CLOSED`), then the remaining clock comparisons:
        recertification submitted past due raises `ERR_CYCLE_PAST_DUE`, a lapse recorded
        while the clock is at or before the deadline raises `ERR_CYCLE_NOT_PAST_DUE`, a
        default recorded while the clock is at or before the order deadline raises
        `ERR_ORDER_DEADLINE_NOT_PASSED`, a ledger record dated after the clock raises
        `ERR_EVENT_DATE_IN_FUTURE`, an order deadline that is not strictly in the future
        raises `ERR_DEADLINE_NOT_IN_FUTURE`, and a backwards clock target raises
        `ERR_CLOCK_NOT_MONOTONIC`."  §3.10 states both of this endpoint's checks in one
        sentence: "Submitting the recertification is the `FloodplainAdministrator`'s
        filing, admitted only from `OPEN` (`ERR_CYCLE_NOT_OPEN`), only while the logical
        clock is at or before `due_at` (`ERR_CYCLE_PAST_DUE`), and only when at least
        one `HigherStandard` of the community has `documentation_status` `SUBMITTED` or
        `VERIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/cycle_submit_state_precondition_outranks_past_due_window
        """
        scenario = _past_due_clock_over_submitted_cycle()
        cycle_id = scenario["cycle"]["id"]

        validate_error(
            api.submit_crs_cycle(cycle_id, ADMIN),
            ApiErrorId.ERR_CYCLE_NOT_OPEN,
        )

        cycle = validate_success(api.get_crs_cycle(cycle_id, ADMIN))
        assert cycle["status"] == "SUBMITTED"

    def test_the_rejected_resubmission_leaves_the_frozen_totals_alone(self, api):
        """PRD §3.10: "Submission moves the cycle to `SUBMITTED`, stamps `submitted_at`,
        freezes `total_claimed_points` from the community's `crs_credit_points_claimed`
        and `prior_class` from its `crs_class`, computes `provisional_class`, and
        recomputes `verification_visit_required`."  The class those points buy is
        bounded: "The class formula subtracts, from 10, the number of whole 500-point
        blocks the points total contains, truncating any partial block downward; the
        result is then raised to 1 if it came out lower, since 1 is the best attainable
        class; and if the community's `compliance_posture` is anything other than
        `GOOD_STANDING`, the class is instead forced to 10 outright — no credit accrues
        to a community on probation or under suspension."

        Design: Difficulty/priority_pair_validation_conflict/cycle_submit_state_precondition_outranks_past_due_window
        """
        scenario = _past_due_clock_over_submitted_cycle()
        cycle_id = scenario["cycle"]["id"]

        validate_error(
            api.submit_crs_cycle(cycle_id, ADMIN),
            ApiErrorId.ERR_CYCLE_NOT_OPEN,
        )

        cycle = validate_success(api.get_crs_cycle(cycle_id, ADMIN))
        assert cycle["total_claimed_points"] == 100
        assert cycle["prior_class"] == 10
        assert cycle["provisional_class"] == 10
        assert cycle["total_verified_points"] == 0

    def test_the_past_due_window_still_bites_an_open_cycle(self, api):
        """PRD §3.10: "Submitting the recertification is the
        `FloodplainAdministrator`'s filing, admitted only from `OPEN`
        (`ERR_CYCLE_NOT_OPEN`), only while the logical clock is at or before `due_at`
        (`ERR_CYCLE_PAST_DUE`), and only when at least one `HigherStandard` of the
        community has `documentation_status` `SUBMITTED` or `VERIFIED`."  §2.8 step 16:
        "**Temporal windows** — the appeal window (`ERR_APPEAL_WINDOW_CLOSED`), then the
        inspection assessment window (`ERR_INSPECTION_WINDOW_CLOSED`), then the
        remaining clock comparisons: recertification submitted past due raises
        `ERR_CYCLE_PAST_DUE`, a lapse recorded while the clock is at or before the
        deadline raises `ERR_CYCLE_NOT_PAST_DUE`, a default recorded while the clock is
        at or before the order deadline raises `ERR_ORDER_DEADLINE_NOT_PASSED`, a ledger
        record dated after the clock raises `ERR_EVENT_DATE_IN_FUTURE`, an order
        deadline that is not strictly in the future raises `ERR_DEADLINE_NOT_IN_FUTURE`,
        and a backwards clock target raises `ERR_CLOCK_NOT_MONOTONIC`."

        Design: Difficulty/priority_pair_validation_conflict/cycle_submit_state_precondition_outranks_past_due_window
        """
        scenario = _past_due_clock_over_submitted_cycle(with_open_sibling=True)
        sibling_id = scenario["sibling_cycle"]["id"]

        validate_error(
            api.submit_crs_cycle(sibling_id, ADMIN),
            ApiErrorId.ERR_CYCLE_PAST_DUE,
        )

        sibling = validate_success(api.get_crs_cycle(sibling_id, ADMIN))
        assert sibling["status"] == "OPEN"
        assert sibling["submitted_at"] is None
        assert sibling["total_claimed_points"] == 0
