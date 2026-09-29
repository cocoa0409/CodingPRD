"""Settlement: the issued clean audit it depends on, and the lock it leaves behind."""

from typing import Any, Dict

import pytest
from test_helpers import (
    DIMENSION_FINANCIAL,
    ERR_SETTLEMENT_BLOCKED,
    ERR_TURNOVER_SETTLED_LOCKED,
    FINDING_CLEAN,
    FUNDING_METHOD_CASH_FLOW,
    POSTURE_OWNER_CONTROL_OPEN,
    POSTURE_SETTLED_LOCKED,
    TRIGGER_BASIS_FIXED_DATE,
    ApiClient,
    advance_payload,
    assert_dimensions,
    do_advance_financial,
    do_advance_governance,
    do_certify_trigger,
    do_issue_engagement,
    make_transition_committee_headers,
    read_turnover_case,
    reserve_study_payload,
    seed_association,
    seed_audit_engagement,
    seed_owner_elected_director,
    seed_turnover_case,
    validate_error,
    validate_paginated,
)


@pytest.fixture
def stonegate(api: ApiClient) -> Dict[str, Any]:
    """A three-seat board already in OWNER_CONTROL with the audit still open."""
    association = seed_association(
        api,
        name="Stonegate",
        total_planned_lots=12,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=600000,
        reserve_claim_pool_cents=800000,
        declarant_monthly_subsidy_cents=60000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    engagement = seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    do_certify_trigger(api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE)
    for name in ("Ana Ruiz", "Bo Nakamura"):
        seed_owner_elected_director(api, case["id"], full_name=name)
    do_advance_governance(api, case["id"], association["id"])
    case = do_advance_financial(
        api, case["id"], association["id"], "2026-09-01T00:00:00Z"
    )
    return {
        "association": association,
        "case": case,
        "engagement": engagement,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestSettlementDependsOnTheAudit:
    """The blocker lives on a different entity than the one being advanced."""

    def test_settlement_is_refused_while_the_engagement_is_only_engaged(
        self, api: ApiClient, stonegate: Dict[str, Any]
    ) -> None:
        """Every seat and stage precondition holds; the report has simply not issued.

        "`settlement_blocked` is false and at least one audit engagement of the
        association is `ISSUED` with `finding_status` `CLEAN`, else
        `ERR_SETTLEMENT_BLOCKED`"

        Design: Difficulty/cross_entity_state_dependency/settlement_depends_on_issued_clean_audit_then_locks_the_association
        """
        case = stonegate["case"]
        assert case["owner_elected_seats_required"] == 2, (
            "Two thirds of a three-seat board, rounded up, is two seats"
        )
        assert_dimensions(
            case,
            governance="OWNER_CONTROL",
            financial="AUDIT_IN_PROGRESS",
            posture=POSTURE_OWNER_CONTROL_OPEN,
        )
        assert case["settlement_blocked"] is False
        assert stonegate["engagement"]["status"] == "ENGAGED"

        validate_error(
            api.advance_case(
                case["id"],
                advance_payload(DIMENSION_FINANCIAL),
                stonegate["committee_headers"],
            ),
            ERR_SETTLEMENT_BLOCKED,
        )

        unchanged = read_turnover_case(api, case["id"])
        assert unchanged["financial_status"] == "AUDIT_IN_PROGRESS"

    def test_issuing_the_clean_report_unblocks_settlement_and_locks_the_posture(
        self, api: ApiClient, stonegate: Dict[str, Any]
    ) -> None:
        """A zero delta is CLEAN, and settlement then derives SETTLED_LOCKED.

        "When all of them hold, `financial_status` moves `AUDIT_IN_PROGRESS →
        SETTLED`, and because governance is already `OWNER_CONTROL` the re-derived
        `turnover_posture` becomes `SETTLED_LOCKED`"

        Design: Difficulty/cross_entity_state_dependency/settlement_depends_on_issued_clean_audit_then_locks_the_association
        """
        association_id = stonegate["association"]["id"]
        case_id = stonegate["case"]["id"]

        validate_error(
            api.advance_case(
                case_id, advance_payload(DIMENSION_FINANCIAL), stonegate["committee_headers"]
            ),
            ERR_SETTLEMENT_BLOCKED,
        )

        issued = do_issue_engagement(api, stonegate["engagement"]["id"])
        assert issued["status"] == "ISSUED"
        assert issued["unreconciled_delta_cents"] == 0
        assert issued["finding_status"] == FINDING_CLEAN

        settled = do_advance_financial(api, case_id, association_id)
        assert_dimensions(
            settled,
            governance="OWNER_CONTROL",
            financial="SETTLED",
            posture=POSTURE_SETTLED_LOCKED,
        )

    def test_the_settled_lock_refuses_a_new_reserve_study(
        self, api: ApiClient, stonegate: Dict[str, Any]
    ) -> None:
        """Opening a study is one of the gated operations.

        "While the association's case stands in that posture, fifteen operations
        are refused with `ERR_TURNOVER_SETTLED_LOCKED`"

        Design: Difficulty/cross_entity_state_dependency/settlement_depends_on_issued_clean_audit_then_locks_the_association
        """
        association_id = stonegate["association"]["id"]
        committee = stonegate["committee_headers"]

        do_issue_engagement(api, stonegate["engagement"]["id"])
        settled = do_advance_financial(api, stonegate["case"]["id"], association_id)
        assert settled["turnover_posture"] == POSTURE_SETTLED_LOCKED

        validate_error(
            api.create_reserve_study(
                reserve_study_payload(
                    association_id,
                    FUNDING_METHOD_CASH_FLOW,
                    planned_annual_contribution_cents=500000,
                    projected_annual_expenditure_cents=100000,
                ),
                committee,
            ),
            ERR_TURNOVER_SETTLED_LOCKED,
        )

        _rows, meta = validate_paginated(
            api.list_reserve_studies(association_id, committee)
        )
        assert meta["total_count"] == 0, "The refused creation persisted nothing"
