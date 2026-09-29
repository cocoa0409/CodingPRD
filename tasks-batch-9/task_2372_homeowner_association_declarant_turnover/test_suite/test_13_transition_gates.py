"""The stage, records, amenity, audit and contract gates on the two dimensions."""

from typing import Any, Dict

import pytest
from test_helpers import (
    CONTRACT_ACTION_CANCEL,
    DIMENSION_FINANCIAL,
    DIMENSION_GOVERNANCE,
    ERR_ASSIGNMENT_CONSENT_REQUIRED,
    ERR_CANCELLATION_WINDOW_CLOSED,
    ERR_CONTRACT_STATE_INVALID,
    ERR_RECORDS_INCOMPLETE,
    ERR_TRANSITION_AUDIT_MISSING,
    ERR_TURNOVER_STAGE_INVALID,
    ERR_UNBUILT_AMENITY_OUTSTANDING,
    FORECAST_STALE,
    POSTURE_OWNER_CONTROL_OPEN,
    POSTURE_SETTLED_LOCKED,
    POSTURE_TRANSITION_RESTRICTED,
    TRIGGER_BASIS_FIXED_DATE,
    ApiClient,
    advance_payload,
    assert_cancellation_window,
    assert_dimensions,
    assert_instant,
    assert_pct,
    certify_trigger_payload,
    contract_action_payload,
    do_accept_item,
    do_advance_financial,
    do_advance_governance,
    do_build_complete,
    do_cancel_contract,
    do_certify_trigger,
    do_consent,
    do_deliver_item,
    do_issue_engagement,
    do_request_assignment,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    seed_association,
    seed_audit_engagement,
    seed_component,
    seed_owner_elected_director,
    seed_records_item,
    seed_turnover_case,
    seed_vendor_contract,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Rushmere: advancing out of turn ───────────────────────────────────


@pytest.fixture
def rushmere(api: ApiClient) -> Dict[str, Any]:
    """A three-seat case whose declaration date has already passed."""
    association = seed_association(
        api,
        name="Rushmere",
        total_planned_lots=8,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=18000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    return {
        "association": association,
        "case": case,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestWrongStageCalls:
    """Each dimension only accepts its own next step."""

    def test_governance_cannot_be_handed_over_before_the_election_is_held(
        self, api: ApiClient, rushmere: Dict[str, Any]
    ) -> None:
        """The same request is refused from DECLARANT_CONTROL and from ELECTION_CALLED.

        "It is legal only from `ELECTION_HELD` (otherwise
        `ERR_TURNOVER_STAGE_INVALID`), requires
        `records_transfer_completeness_pct` to be at or above 80.00 (otherwise
        `ERR_RECORDS_INCOMPLETE`), and requires that no overdue unbuilt amenity
        remains (otherwise `ERR_UNBUILT_AMENITY_OUTSTANDING`)."

        Design: Corner/state_machines/certify_and_advance_calls_from_the_wrong_stage_are_rejected
        """
        association_id = rushmere["association"]["id"]
        case_id = rushmere["case"]["id"]
        committee = rushmere["committee_headers"]

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_GOVERNANCE), committee),
            ERR_TURNOVER_STAGE_INVALID,
        )

        certified = do_certify_trigger(
            api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE
        )
        assert certified["governance_status"] == "ELECTION_CALLED"

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_GOVERNANCE), committee),
            ERR_TURNOVER_STAGE_INVALID,
        )

        case = read_turnover_case(api, case_id)
        assert_dimensions(
            case,
            governance="ELECTION_CALLED",
            financial="SUBSIDY_ACTIVE",
            posture=POSTURE_TRANSITION_RESTRICTED,
        )

    def test_certifying_a_second_time_is_refused_and_keeps_the_first_stamp(
        self, api: ApiClient, rushmere: Dict[str, Any]
    ) -> None:
        """Certification is a one-way door out of DECLARANT_CONTROL.

        "The case must be in `DECLARANT_CONTROL`, else
        `ERR_TURNOVER_STAGE_INVALID`."

        Design: Corner/state_machines/certify_and_advance_calls_from_the_wrong_stage_are_rejected
        """
        association_id = rushmere["association"]["id"]
        case_id = rushmere["case"]["id"]
        committee = rushmere["committee_headers"]

        certified = do_certify_trigger(
            api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE
        )
        first_stamp = certified["trigger_certified_at"]
        assert_instant(first_stamp, "2026-08-01T00:00:00Z", "trigger_certified_at")

        set_clock(api, "2026-09-01T00:00:00Z")
        validate_error(
            api.certify_trigger(
                case_id,
                certify_trigger_payload(trigger_basis=TRIGGER_BASIS_FIXED_DATE),
                committee,
            ),
            ERR_TURNOVER_STAGE_INVALID,
        )

        case = read_turnover_case(api, case_id)
        assert case["governance_status"] == "ELECTION_CALLED"
        assert case["trigger_basis"] == TRIGGER_BASIS_FIXED_DATE
        assert_instant(
            case["trigger_certified_at"], first_stamp, "trigger_certified_at"
        )


# ─── Saltmarsh Quay: no audit, no subsidy end ─────────────────────────


@pytest.fixture
def saltmarsh_quay(api: ApiClient) -> Dict[str, Any]:
    """A subsidised community with no audit engagement at all."""
    association = seed_association(
        api,
        name="Saltmarsh Quay",
        total_planned_lots=10,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=40000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    return {
        "association": association,
        "case": case,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestFinancialAdvanceNeedsAnEngagement:
    """Ending the subsidy and opening the audit window are one event."""

    def test_the_subsidy_cannot_end_until_an_engagement_exists(
        self, api: ApiClient, saltmarsh_quay: Dict[str, Any]
    ) -> None:
        """The refused advance writes no end date; the identical retry then succeeds.

        "from `SUBSIDY_ACTIVE` the request must carry a `subsidy_end_date`
        (otherwise `ERR_INVALID_REQUEST`) and at least one audit engagement of the
        association must exist in `ENGAGED` or `ISSUED` (otherwise
        `ERR_TRANSITION_AUDIT_MISSING`)"

        Design: Corner/state_machines/advance_financial_without_any_audit_engagement_is_rejected
        """
        association_id = saltmarsh_quay["association"]["id"]
        case_id = saltmarsh_quay["case"]["id"]
        committee = saltmarsh_quay["committee_headers"]

        request = advance_payload(DIMENSION_FINANCIAL)
        request["subsidy_end_date"] = "2026-10-01T00:00:00Z"

        validate_error(
            api.advance_case(case_id, request, committee),
            ERR_TRANSITION_AUDIT_MISSING,
        )

        blocked = read_association(api, association_id)
        assert blocked["subsidy_end_date"] is None, (
            "The refused advance wrote no end date"
        )
        assert read_turnover_case(api, case_id)["financial_status"] == "SUBSIDY_ACTIVE"

        engagement = seed_audit_engagement(
            api, association_id, "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
        )
        assert engagement["status"] == "ENGAGED"

        advanced = validate_success(api.advance_case(case_id, request, committee))
        assert_dimensions(
            advanced,
            governance="DECLARANT_CONTROL",
            financial="AUDIT_IN_PROGRESS",
            posture=POSTURE_TRANSITION_RESTRICTED,
        )

        association = read_association(api, association_id)
        assert_instant(
            association["subsidy_end_date"], "2026-10-01T00:00:00Z", "subsidy_end_date"
        )
        assert association["budget_forecast_status"] == FORECAST_STALE


# ─── Thistledown: the eighty percent records gate ─────────────────────


@pytest.fixture
def thistledown(api: ApiClient) -> Dict[str, Any]:
    """An elected board and five required documents plus one optional one."""
    association = seed_association(
        api,
        name="Thistledown",
        total_planned_lots=11,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=22000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    do_certify_trigger(api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE)
    for name in ("Tova Lindqvist", "Umar Diallo"):
        seed_owner_elected_director(api, case["id"], full_name=name)
    required = [
        seed_records_item(api, case["id"], category, required=True)
        for category in (
            "FINANCIAL_RECORDS",
            "WARRANTIES",
            "PLANS_AND_SPECS",
            "VENDOR_CONTRACTS",
            "PERMITS",
        )
    ]
    optional = seed_records_item(api, case["id"], "PERMITS", required=False)
    for item in required[:3]:
        do_deliver_item(api, item["id"])
        do_accept_item(api, item["id"], association["id"])
    return {
        "association": association,
        "case": case,
        "required": required,
        "optional": optional,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestRecordsThresholdGate:
    """Three of five required items is not enough; four is exactly enough."""

    def test_sixty_percent_complete_refuses_the_governance_handover(
        self, api: ApiClient, thistledown: Dict[str, Any]
    ) -> None:
        """The board is seated and the election held, so only the records gate answers.

        "requires `records_transfer_completeness_pct` to be at or above 80.00
        (otherwise `ERR_RECORDS_INCOMPLETE`)"

        Design: Corner/state_machines/governance_advance_below_the_records_threshold_is_rejected
        """
        case_id = thistledown["case"]["id"]
        committee = thistledown["committee_headers"]

        case = read_turnover_case(api, case_id)
        assert case["governance_status"] == "ELECTION_HELD"
        assert_pct(
            case["records_transfer_completeness_pct"],
            60.00,
            "records_transfer_completeness_pct",
        )

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_GOVERNANCE), committee),
            ERR_RECORDS_INCOMPLETE,
        )

        unchanged = read_turnover_case(api, case_id)
        assert unchanged["governance_status"] == "ELECTION_HELD"

    def test_the_fourth_acceptance_reaches_the_threshold_and_hands_over(
        self, api: ApiClient, thistledown: Dict[str, Any]
    ) -> None:
        """The optional sixth item never enters the divisor, so four of five is 80.00.

        "Items flagged `required` false never move the percentage in either
        direction, no matter what happens to them."

        Design: Corner/state_machines/governance_advance_below_the_records_threshold_is_rejected
        """
        association_id = thistledown["association"]["id"]
        case_id = thistledown["case"]["id"]
        committee = thistledown["committee_headers"]

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_GOVERNANCE), committee),
            ERR_RECORDS_INCOMPLETE,
        )

        fourth = thistledown["required"][3]
        do_deliver_item(api, fourth["id"])
        do_accept_item(api, fourth["id"], association_id)

        case = read_turnover_case(api, case_id)
        assert_pct(
            case["records_transfer_completeness_pct"],
            80.00,
            "records_transfer_completeness_pct",
        )

        advanced = do_advance_governance(api, case_id, association_id)
        assert_dimensions(
            advanced,
            governance="OWNER_CONTROL",
            financial="SUBSIDY_ACTIVE",
            posture=POSTURE_OWNER_CONTROL_OPEN,
        )

        rows, _meta = validate_paginated(api.list_records_items(case_id, committee))
        outstanding = {
            row["id"] for row in rows if row["status"] == "OUTSTANDING"
        }
        assert thistledown["required"][4]["id"] in outstanding
        assert thistledown["optional"]["id"] in outstanding


# ─── Umberfield: the overdue amenity gate ─────────────────────────────


@pytest.fixture
def umberfield(api: ApiClient) -> Dict[str, Any]:
    """One overdue amenity, one overdue non-amenity and one amenity not yet due."""
    association = seed_association(
        api,
        name="Umberfield",
        total_planned_lots=9,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=16000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    splash_pad = seed_component(
        api,
        association["id"],
        name="Splash Pad",
        category="AMENITY",
        replacement_cost_cents=400000,
        useful_life_years=15,
        effective_age_years=0,
        promised_completion_date="2026-03-01T00:00:00Z",
    )
    storm_drain = seed_component(
        api,
        association["id"],
        name="Storm Drain Phase 2",
        category="INFRASTRUCTURE",
        replacement_cost_cents=250000,
        useful_life_years=25,
        effective_age_years=0,
        promised_completion_date="2026-03-01T00:00:00Z",
    )
    dog_park = seed_component(
        api,
        association["id"],
        name="Dog Park",
        category="AMENITY",
        replacement_cost_cents=90000,
        useful_life_years=10,
        effective_age_years=0,
        promised_completion_date="2027-03-01T00:00:00Z",
    )
    do_certify_trigger(api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE)
    for name in ("Vera Ionescu", "Wren Ashby"):
        seed_owner_elected_director(api, case["id"], full_name=name)
    return {
        "association": association,
        "case": case,
        "splash_pad": splash_pad,
        "storm_drain": storm_drain,
        "dog_park": dog_park,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestOverdueAmenityGate:
    """Only a late amenity blocks; a late pipe and a future amenity do not."""

    def test_the_overdue_splash_pad_blocks_the_governance_handover(
        self, api: ApiClient, umberfield: Dict[str, Any]
    ) -> None:
        """Records are vacuously complete, so the amenity is the only objection.

        "An `AMENITY` component whose `build_status` is still `UNBUILT` or
        `IN_PROGRESS` and whose `promised_completion_date` is earlier than the
        logical clock is *overdue*, and while any such component exists the
        association cannot complete either the transfer of governance or the final
        settlement — both are refused with `ERR_UNBUILT_AMENITY_OUTSTANDING`."

        Design: Corner/state_machines/governance_advance_blocked_by_an_overdue_unbuilt_amenity
        """
        case_id = umberfield["case"]["id"]
        committee = umberfield["committee_headers"]

        case = read_turnover_case(api, case_id)
        assert case["governance_status"] == "ELECTION_HELD"
        assert_pct(
            case["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_GOVERNANCE), committee),
            ERR_UNBUILT_AMENITY_OUTSTANDING,
        )

        assert read_turnover_case(api, case_id)["governance_status"] == "ELECTION_HELD"

    def test_completing_it_clears_the_gate_while_the_others_stay_unbuilt(
        self, api: ApiClient, umberfield: Dict[str, Any]
    ) -> None:
        """The late storm drain and the not-yet-due dog park block nothing.

        "A component that is late but not an amenity, and an amenity that is late
        but already `COMPLETE`, block nothing."

        Design: Corner/state_machines/governance_advance_blocked_by_an_overdue_unbuilt_amenity
        """
        association_id = umberfield["association"]["id"]
        case_id = umberfield["case"]["id"]
        committee = umberfield["committee_headers"]

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_GOVERNANCE), committee),
            ERR_UNBUILT_AMENITY_OUTSTANDING,
        )

        completed = do_build_complete(
            api, umberfield["splash_pad"]["id"], "2026-07-20T00:00:00Z"
        )
        assert completed["build_status"] == "COMPLETE"

        advanced = do_advance_governance(api, case_id, association_id)
        assert_dimensions(
            advanced,
            governance="OWNER_CONTROL",
            financial="SUBSIDY_ACTIVE",
            posture=POSTURE_OWNER_CONTROL_OPEN,
        )

        rows, _meta = validate_paginated(api.list_components(association_id, committee))
        by_id = {row["id"]: row for row in rows}
        assert by_id[umberfield["storm_drain"]["id"]]["build_status"] == "UNBUILT"
        assert by_id[umberfield["dog_park"]["id"]]["build_status"] == "UNBUILT"


# ─── Vanbrugh Court: the cancellation window's two edges ──────────────


@pytest.fixture
def vanbrugh_court(api: ApiClient) -> Dict[str, Any]:
    """Two affiliated contracts made cancellable by certification, and one independent."""
    association = seed_association(
        api,
        name="Vanbrugh Court",
        total_planned_lots=24,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=200000,
        reserve_claim_pool_cents=400000,
        declarant_monthly_subsidy_cents=35000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    components = {
        name: seed_component(
            api,
            association["id"],
            name=name,
            category="STRUCTURE",
            replacement_cost_cents=100000,
            useful_life_years=20,
            effective_age_years=1,
            promised_completion_date="2026-01-01T00:00:00Z",
        )
        for name in ("Lobby", "Garage", "Elevators")
    }
    affiliated_one = seed_vendor_contract(
        api,
        association["id"],
        components["Lobby"]["id"],
        vendor_name="Declarant Facility Group",
        developer_affiliated=True,
        annual_cost_cents=120000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-01T00:00:00Z",
    )
    affiliated_two = seed_vendor_contract(
        api,
        association["id"],
        components["Garage"]["id"],
        vendor_name="Declarant Parking LLC",
        developer_affiliated=True,
        annual_cost_cents=60000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-01T00:00:00Z",
    )
    independent = seed_vendor_contract(
        api,
        association["id"],
        components["Elevators"]["id"],
        vendor_name="Independent Lift Care",
        developer_affiliated=False,
        annual_cost_cents=45000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-01T00:00:00Z",
    )
    certified = do_certify_trigger(
        api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE
    )
    return {
        "association": association,
        "case": case,
        "certified": certified,
        "affiliated_one": affiliated_one,
        "affiliated_two": affiliated_two,
        "independent": independent,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestCancellationWindowEdges:
    """An independent contract is never cancellable, and the window closes hard."""

    def test_cancelling_an_active_independent_contract_is_rejected(
        self, api: ApiClient, vanbrugh_court: Dict[str, Any]
    ) -> None:
        """Certification moved only the two affiliated contracts.

        "Only a contract that certification moved into `CANCELLABLE` may be
        cancelled, and only while the logical clock is at or before its
        `cancellation_window_end`; a late attempt is
        `ERR_CANCELLATION_WINDOW_CLOSED`, and an attempt on a contract that is not
        `CANCELLABLE` is `ERR_CONTRACT_STATE_INVALID`."

        Design: Corner/state_machines/vendor_cancel_from_active_and_after_the_window_are_rejected
        """
        committee = vanbrugh_court["committee_headers"]
        certified_at = vanbrugh_court["certified"]["trigger_certified_at"]

        independent = validate_success(
            api.get_vendor_contract(vanbrugh_court["independent"]["id"], committee)
        )
        assert independent["status"] == "ACTIVE"
        assert independent["cancellation_window_end"] is None

        validate_error(
            api.vendor_contract_action(
                independent["id"],
                contract_action_payload(CONTRACT_ACTION_CANCEL),
                committee,
            ),
            ERR_CONTRACT_STATE_INVALID,
        )

        affiliated = validate_success(
            api.get_vendor_contract(vanbrugh_court["affiliated_one"]["id"], committee)
        )
        assert affiliated["status"] == "CANCELLABLE"
        assert_cancellation_window(affiliated, "2026-08-01T00:00:00Z")
        assert_instant(certified_at, "2026-08-01T00:00:00Z", "trigger_certified_at")

    def test_the_window_admits_its_last_instant_and_closes_one_second_later(
        self, api: ApiClient, vanbrugh_court: Dict[str, Any]
    ) -> None:
        """One second past 2026-10-30 the surviving affiliated contract is stuck.

        "A successful `CANCEL` moves `status` `CANCELLABLE → CANCELLED`, sets
        `budget_forecast_status` to `STALE`, advances the association's `version`,
        and — as a consequence of that staleness — supersedes every `DRAFT`
        assessment schedule of the association, oldest first."

        Design: Corner/state_machines/vendor_cancel_from_active_and_after_the_window_are_rejected
        """
        association_id = vanbrugh_court["association"]["id"]
        committee = vanbrugh_court["committee_headers"]

        set_clock(api, "2026-10-30T00:00:00Z")
        cancelled = do_cancel_contract(
            api, vanbrugh_court["affiliated_one"]["id"], association_id
        )
        assert cancelled["status"] == "CANCELLED"

        association = read_association(api, association_id)
        assert association["budget_forecast_status"] == FORECAST_STALE

        set_clock(api, "2026-10-30T00:00:01Z")
        validate_error(
            api.vendor_contract_action(
                vanbrugh_court["affiliated_two"]["id"],
                contract_action_payload(CONTRACT_ACTION_CANCEL),
                committee,
            ),
            ERR_CANCELLATION_WINDOW_CLOSED,
        )

        stuck = validate_success(
            api.get_vendor_contract(vanbrugh_court["affiliated_two"]["id"], committee)
        )
        assert stuck["status"] == "CANCELLABLE", "The late attempt moved nothing"


# ─── Ashcombe: the last blocker on settlement ─────────────────────────


@pytest.fixture
def ashcombe(api: ApiClient) -> Dict[str, Any]:
    """A community ready to settle except for one cancellable affiliated contract."""
    association = seed_association(
        api,
        name="Ashcombe",
        total_planned_lots=12,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=26000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    component = seed_component(
        api,
        association["id"],
        name="Private Road",
        category="INFRASTRUCTURE",
        replacement_cost_cents=400000,
        useful_life_years=25,
        effective_age_years=2,
        promised_completion_date="2026-01-01T00:00:00Z",
    )
    contract = seed_vendor_contract(
        api,
        association["id"],
        component["id"],
        vendor_name="Declarant Road Services",
        developer_affiliated=True,
        annual_cost_cents=80000,
        service_window_start="2026-01-01T00:00:00Z",
        service_window_end="2026-12-01T00:00:00Z",
    )
    engagement = seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    do_issue_engagement(api, engagement["id"])
    do_certify_trigger(api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE)
    for name in ("Bex Ferrand", "Cai Mwangi"):
        seed_owner_elected_director(api, case["id"], full_name=name)
    do_advance_governance(api, case["id"], association["id"])
    advanced = do_advance_financial(
        api, case["id"], association["id"], "2026-09-01T00:00:00Z"
    )
    return {
        "association": association,
        "case": advanced,
        "component": component,
        "contract": contract,
        "engagement": engagement,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestSettlementNeedsTheAffiliatedContractResolved:
    """Consent is not a resolution; only cancellation or refusal is."""

    def test_consenting_to_the_assignment_does_not_unblock_settlement(
        self, api: ApiClient, ashcombe: Dict[str, Any]
    ) -> None:
        """The contract is CONSENTED and still CANCELLABLE, so settlement is refused twice.

        "Note carefully that consenting to a contract's assignment does *not*
        remove it from the cancellable set: only cancellation or refusal of
        consent does."

        Design: Corner/state_machines/settlement_blocked_by_an_unresolved_developer_affiliated_contract
        """
        association_id = ashcombe["association"]["id"]
        case_id = ashcombe["case"]["id"]
        committee = ashcombe["committee_headers"]
        contract_id = ashcombe["contract"]["id"]

        assert_dimensions(
            ashcombe["case"],
            governance="OWNER_CONTROL",
            financial="AUDIT_IN_PROGRESS",
            posture=POSTURE_OWNER_CONTROL_OPEN,
        )

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_FINANCIAL), committee),
            ERR_ASSIGNMENT_CONSENT_REQUIRED,
        )

        do_request_assignment(api, contract_id)
        consented = do_consent(api, contract_id, association_id)
        assert consented["assignment_status"] == "CONSENTED"
        assert consented["status"] == "CANCELLABLE", (
            "Consent leaves the contract in the cancellable set"
        )

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_FINANCIAL), committee),
            ERR_ASSIGNMENT_CONSENT_REQUIRED,
        )
        assert read_turnover_case(api, case_id)["financial_status"] == "AUDIT_IN_PROGRESS"

    def test_cancelling_it_clears_the_last_blocker_and_settles(
        self, api: ApiClient, ashcombe: Dict[str, Any]
    ) -> None:
        """Everything else already held; the contract was the only objection left.

        "no developer-affiliated vendor contract of the association is still
        `CANCELLABLE`, else `ERR_ASSIGNMENT_CONSENT_REQUIRED`"

        Design: Corner/state_machines/settlement_blocked_by_an_unresolved_developer_affiliated_contract
        """
        association_id = ashcombe["association"]["id"]
        case_id = ashcombe["case"]["id"]
        committee = ashcombe["committee_headers"]

        validate_error(
            api.advance_case(case_id, advance_payload(DIMENSION_FINANCIAL), committee),
            ERR_ASSIGNMENT_CONSENT_REQUIRED,
        )

        cancelled = do_cancel_contract(api, ashcombe["contract"]["id"], association_id)
        assert cancelled["status"] == "CANCELLED"

        settled = do_advance_financial(api, case_id, association_id)
        assert_dimensions(
            settled,
            governance="OWNER_CONTROL",
            financial="SETTLED",
            posture=POSTURE_SETTLED_LOCKED,
        )
        assert settled["settlement_blocked"] is False
