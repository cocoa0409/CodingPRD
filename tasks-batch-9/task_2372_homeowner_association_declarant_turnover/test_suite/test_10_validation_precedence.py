"""Rejection precedence: which of two simultaneous violations the server reports."""

from typing import Any, Dict

import pytest
from test_helpers import (
    CLAIM_ACTION_NOTICE,
    CLAIM_ACTION_RESERVE,
    DECLARANT_HEADERS,
    ERR_CLAIM_RESERVE_INSUFFICIENT,
    ERR_CLAIM_STATE_INVALID,
    ERR_COMPONENT_NOT_CONVEYED,
    ERR_RECORDS_ITEM_STATE_INVALID,
    ERR_REPOSE_PERIOD_EXPIRED,
    ERR_ROLE_NOT_PERMITTED,
    MILESTONE_CONVEYANCE_ACCEPTED,
    RECORDS_ACTION_DELIVER,
    VALUATION_BASIS_REPAIR_COST,
    ApiClient,
    assert_claim_pool_conserved,
    assert_instant,
    assert_pct,
    build_conveyed_component,
    claim_action_payload,
    do_accept_item,
    do_build_complete,
    do_deed_tendered,
    do_deliver_item,
    make_transition_committee_headers,
    milestone_payload,
    read_association,
    read_turnover_case,
    records_transition_payload,
    seed_association,
    seed_component,
    seed_defect_claim,
    seed_records_item,
    seed_turnover_case,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Jasper Mill: the state check outranks the money check ─────────────


@pytest.fixture
def jasper_mill(api: ApiClient) -> Dict[str, Any]:
    """A claim far too large for the pool, still sitting in INVESTIGATING."""
    association = seed_association(
        api,
        name="Jasper Mill",
        total_planned_lots=22,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2028-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=200000,
        reserve_claim_pool_cents=100000,
        declarant_monthly_subsidy_cents=50000,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2022-02-01T00:00:00Z",
        name="Bridge Deck",
        category="STRUCTURE",
        replacement_cost_cents=8000000,
        useful_life_years=40,
        effective_age_years=4,
        promised_completion_date="2022-02-01T00:00:00Z",
    )
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Bridge deck spalling and exposed rebar",
        repair_cost_estimate_cents=5000000,
        diminution_value_cents=3000000,
    )
    return {
        "association": association,
        "claim": claim,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestClaimStateOutranksTheFiscalShortfall:
    """Both rules are broken at once; the earlier rung answers."""

    def test_reserving_from_investigating_reports_the_state_not_the_shortfall(
        self, api: ApiClient, jasper_mill: Dict[str, Any]
    ) -> None:
        """A reserve far larger than the 100,000 cent pool still reports the state.

        "`RESERVE` is legal from either `NOTICED` or `REJECTED_BY_DEVELOPER` — the
        two edges behave identically — and requires a `valuation_basis` in the
        payload, either `REPAIR_COST` or `DIMINUTION`."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_check_outranks_reserve_fiscal_shortfall
        """
        assert jasper_mill["claim"]["status"] == "INVESTIGATING"

        validate_error(
            api.defect_claim_action(
                jasper_mill["claim"]["id"],
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                jasper_mill["committee_headers"],
            ),
            ERR_CLAIM_STATE_INVALID,
        )

        association = read_association(api, jasper_mill["association"]["id"])
        assert association["reserve_claim_committed_cents"] == 0
        assert association["reserve_claim_available_cents"] == 100000
        assert_claim_pool_conserved(association)

    def test_the_shortfall_surfaces_only_once_the_state_is_legal(
        self, api: ApiClient, jasper_mill: Dict[str, Any]
    ) -> None:
        """Noticing the claim exposes the money rule underneath.

        "anything larger is `ERR_CLAIM_RESERVE_INSUFFICIENT`, evaluated after
        every other check on the request"

        Design: Difficulty/priority_pair_validation_conflict/claim_state_check_outranks_reserve_fiscal_shortfall
        """
        association_id = jasper_mill["association"]["id"]
        committee = jasper_mill["committee_headers"]
        claim_id = jasper_mill["claim"]["id"]

        reserve_request = claim_action_payload(
            CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
        )
        validate_error(
            api.defect_claim_action(claim_id, reserve_request, committee),
            ERR_CLAIM_STATE_INVALID,
        )

        noticed = validate_success(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            )
        )
        assert noticed["status"] == "NOTICED"

        validate_error(
            api.defect_claim_action(claim_id, reserve_request, committee),
            ERR_CLAIM_RESERVE_INSUFFICIENT,
        )

        claim = validate_success(api.get_defect_claim(claim_id, committee))
        assert claim["status"] == "NOTICED", "The refused reserve moved no state"
        assert claim["reserved_amount_cents"] == 0
        assert claim["valuation_basis"] is None

        association = read_association(api, association_id)
        assert association["reserve_claim_committed_cents"] == 0
        assert association["reserve_claim_available_cents"] == 100000


# ─── Kestrel Landing: referential outranks temporal ────────────────────


@pytest.fixture
def kestrel_landing(api: ApiClient) -> Dict[str, Any]:
    """A long-expired claim whose component has only been tendered."""
    association = seed_association(
        api,
        name="Kestrel Landing",
        total_planned_lots=14,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=300000,
        reserve_claim_pool_cents=2000000,
        declarant_monthly_subsidy_cents=40000,
    )
    component = seed_component(
        api,
        association["id"],
        name="Community Dock",
        category="AMENITY",
        replacement_cost_cents=1800000,
        useful_life_years=20,
        effective_age_years=10,
        promised_completion_date="2016-01-01T00:00:00Z",
    )
    do_build_complete(api, component["id"], "2016-01-10T00:00:00Z")
    do_deed_tendered(api, component["id"])
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Dock pilings undermined by scour",
        repair_cost_estimate_cents=600000,
        diminution_value_cents=400000,
    )
    return {
        "association": association,
        "component": component,
        "claim": claim,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestConveyanceOutranksRepose:
    """The cross-entity precondition is judged before the statutory clock."""

    def test_notice_reports_the_unconveyed_component_not_the_expired_period(
        self, api: ApiClient, kestrel_landing: Dict[str, Any]
    ) -> None:
        """The deadline ran out in 2024, yet the conveyance rule answers first.

        "**Cross-entity state preconditions** (HTTP 409). Serving notice requires
        the claim's component to have been conveyed
        (`ERR_COMPONENT_NOT_CONVEYED`)"

        Design: Difficulty/priority_pair_validation_conflict/component_conveyance_referential_outranks_repose_temporal
        """
        claim = kestrel_landing["claim"]
        assert_instant(
            claim["repose_deadline"], "2024-01-10T00:00:00Z", "repose_deadline"
        )

        validate_error(
            api.defect_claim_action(
                claim["id"],
                claim_action_payload(CLAIM_ACTION_NOTICE),
                kestrel_landing["committee_headers"],
            ),
            ERR_COMPONENT_NOT_CONVEYED,
        )

    def test_accepting_the_conveyance_reveals_the_expired_repose_period(
        self, api: ApiClient, kestrel_landing: Dict[str, Any]
    ) -> None:
        """Removing the referential objection exposes the temporal one.

        "A claim noticed too late, or noticed with no deadline at all, is refused
        with `ERR_REPOSE_PERIOD_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/component_conveyance_referential_outranks_repose_temporal
        """
        committee = kestrel_landing["committee_headers"]
        claim_id = kestrel_landing["claim"]["id"]

        validate_error(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            ),
            ERR_COMPONENT_NOT_CONVEYED,
        )

        component = validate_success(
            api.record_milestone(
                kestrel_landing["component"]["id"],
                milestone_payload(MILESTONE_CONVEYANCE_ACCEPTED),
                committee,
            )
        )
        assert component["conveyance_status"] == "CONVEYED"

        validate_error(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_NOTICE), committee
            ),
            ERR_REPOSE_PERIOD_EXPIRED,
        )

        claim = validate_success(api.get_defect_claim(claim_id, committee))
        assert claim["status"] == "INVESTIGATING", "Neither refusal moved the claim"


# ─── Larchmont Green: the role discriminator outranks the state ────────


@pytest.fixture
def larchmont_green(api: ApiClient) -> Dict[str, Any]:
    """One required financial-records item already delivered and accepted."""
    association = seed_association(
        api,
        name="Larchmont Green",
        total_planned_lots=11,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-02-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=100000,
        reserve_claim_pool_cents=500000,
        declarant_monthly_subsidy_cents=30000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    item = seed_records_item(api, case["id"], "FINANCIAL_RECORDS", required=True)
    delivered = do_deliver_item(api, item["id"])
    accepted = do_accept_item(api, item["id"], association["id"])
    return {
        "association": association,
        "case": case,
        "item": accepted,
        "delivered_at": delivered["delivered_at"],
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestRoleDiscriminatorOutranksTerminalState:
    """DELIVER is the declarant's word, and that is checked before the state."""

    def test_the_committee_is_refused_on_the_role_not_on_the_state(
        self, api: ApiClient, larchmont_green: Dict[str, Any]
    ) -> None:
        """The item is in a state DELIVER cannot leave, yet the role answers first.

        "This runs *before* any state check, so a wrong-role request against a
        resource that is also in the wrong state reports the role problem."

        Design: Difficulty/priority_pair_validation_conflict/role_discriminator_outranks_records_item_terminal_state
        """
        assert larchmont_green["item"]["status"] == "ACCEPTED"

        validate_error(
            api.records_item_transition(
                larchmont_green["item"]["id"],
                records_transition_payload(RECORDS_ACTION_DELIVER),
                larchmont_green["committee_headers"],
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

    def test_the_declarant_reaches_the_state_check_and_is_refused_there(
        self, api: ApiClient, larchmont_green: Dict[str, Any]
    ) -> None:
        """The same payload from the entitled role reports the illegal edge.

        "Any of the three actions attempted from a status the edge does not allow
        is `ERR_RECORDS_ITEM_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/role_discriminator_outranks_records_item_terminal_state
        """
        item_id = larchmont_green["item"]["id"]

        validate_error(
            api.records_item_transition(
                item_id,
                records_transition_payload(RECORDS_ACTION_DELIVER),
                larchmont_green["committee_headers"],
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.records_item_transition(
                item_id,
                records_transition_payload(RECORDS_ACTION_DELIVER),
                DECLARANT_HEADERS,
            ),
            ERR_RECORDS_ITEM_STATE_INVALID,
        )

        rows, _meta = validate_paginated(
            api.list_records_items(
                larchmont_green["case"]["id"], larchmont_green["committee_headers"]
            )
        )
        assert rows[0]["status"] == "ACCEPTED", "Neither refusal moved the item"
        assert_instant(
            rows[0]["delivered_at"],
            larchmont_green["delivered_at"],
            "delivered_at",
        )

        case = read_turnover_case(api, larchmont_green["case"]["id"])
        assert_pct(
            case["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )
