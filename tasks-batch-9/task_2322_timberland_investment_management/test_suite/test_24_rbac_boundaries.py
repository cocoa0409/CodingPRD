"""Role boundaries: authentication, the endpoint role lists and the segregation comparisons."""

from test_helpers import (
    ApiErrorId,
    assert_bps,
    assert_fund_cash,
    assert_instant_equals,
    assert_money,
    assert_tons,
    validate_error,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import fund_payload, market_appraisal_submit_payload
from test_helpers.fixtures import (
    audit_with_open_findings,
    create_case,
    cruised_stand,
    owned_tract,
    read_audit,
    read_case,
    read_finding,
    read_fund,
    read_property,
    submit_appraisal,
    submit_case,
)
from test_helpers.test_users import (
    make_analyst_headers,
    make_appraiser_headers,
    make_auditor_headers,
    make_committee_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
    make_headers_without_user_id,
    make_unknown_role_headers,
)


class TestAuthenticationPrecedesEverything:
    """An undeclared role and a missing operator identifier are both unauthenticated."""

    def test_an_undeclared_role_and_an_absent_user_id_are_both_rejected(self, api):
        """Neither malformed caller creates a fund, and a well-formed one does.

        PRD: "Both headers present and `X-User-Role` one of the seven declared roles, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/rbac/unknown_role_and_absent_user_id_are_both_unauthenticated
        """
        unknown_role = api.create_fund(fund_payload(), make_unknown_role_headers())
        no_user_id = api.create_fund(fund_payload(), make_headers_without_user_id())

        validate_error(unknown_role, ApiErrorId.UNAUTHENTICATED.value, 401)
        validate_error(no_user_id, ApiErrorId.UNAUTHENTICATED.value, 401)

        fund = validate_success(
            api.create_fund(fund_payload(), make_fund_admin_headers()), 201
        )

        assert_money(fund["cash_balance_usd"], 400000.00, "cash_balance_usd")
        assert_bps(fund["cash_yield_bps"], 0, "cash_yield_bps")
        assert fund["version"] == 1


class TestOnlyTheCommitteeDecidesACase:
    """The analyst who prepared the case cannot also rule on it."""

    def test_an_acquisition_analyst_is_unauthorized_to_decide(self, api):
        """The analyst is turned away on role, not on segregation of duties.

        PRD: "The `InvestmentCommittee` then issues a decision on a `SUBMITTED` case, supplying a `decision` of `APPROVE`, `REJECT` or `REQUEST_REVISION` and an optional `decision_note` recording the rationale."

        Design: Corner/rbac/an_acquisition_analyst_cannot_decide_a_case
        """
        ctx = cruised_stand(api)
        case = create_case(api, ctx.property_id, author="analyst-1")
        submit_case(api, case["id"], author="analyst-1")

        response = api.decide_underwriting_case(
            case["id"], {"decision": "APPROVE"}, make_analyst_headers("analyst-1")
        )

        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)
        refused = read_case(api, case["id"])
        assert refused["status"] == "SUBMITTED"
        assert refused["decided_by_user_id"] is None
        assert read_property(api, ctx.property_id)["status"] == "UNDER_UNDERWRITING"

    def test_the_committee_member_carries_the_same_decision_through(self, api):
        """The committee approves and its identifier is stamped on the case.

        PRD: "the server stamps `decided_by_user_id` with the caller's `X-User-ID` and increments the property's `version`."

        Design: Corner/rbac/an_acquisition_analyst_cannot_decide_a_case
        """
        ctx = cruised_stand(api)
        case = create_case(api, ctx.property_id, author="analyst-1")
        submit_case(api, case["id"], author="analyst-1")
        api.decide_underwriting_case(
            case["id"], {"decision": "APPROVE"}, make_analyst_headers("analyst-1")
        )

        decided = validate_success(
            api.decide_underwriting_case(
                case["id"], {"decision": "APPROVE"}, make_committee_headers("ic-1")
            ),
            200,
        )

        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "ic-1"
        assert decided["authored_by_user_id"] == "analyst-1"
        assert decided["revision_count"] == 0
        assert read_property(api, ctx.property_id)["status"] == "APPROVED_FOR_BID"


class TestTheCorrectiveActionCycleIsSplitBetweenTwoRoles:
    """The manager writes the corrective action; only the auditor rules on it."""

    def test_a_forest_manager_can_submit_but_cannot_reject_or_close(self, api):
        """Each half of the cycle refuses the other role's caller.

        PRD: "A `CertificationAuditor` — and only a `CertificationAuditor` — resolves the submission."

        Design: Corner/rbac/a_forest_manager_cannot_reject_a_corrective_action
        """
        ctx = owned_tract(api)
        audit = audit_with_open_findings(api, ctx.property_id, ("MINOR",))

        manager_closes = api.transition_audit_finding(
            audit.finding_id,
            {"action": "VERIFY_CLOSE"},
            make_forest_manager_headers("manager-1"),
        )
        auditor_submits = api.transition_audit_finding(
            audit.finding_id,
            {"action": "SUBMIT_CAR", "car_text": "Buffer strip re-flagged."},
            make_auditor_headers("ca-1"),
        )

        validate_error(manager_closes, ApiErrorId.UNAUTHORIZED.value, 403)
        validate_error(auditor_submits, ApiErrorId.UNAUTHORIZED.value, 403)

        submitted = validate_success(
            api.transition_audit_finding(
                audit.finding_id,
                {"action": "SUBMIT_CAR", "car_text": "Buffer strip re-flagged."},
                make_forest_manager_headers("manager-1"),
            ),
            200,
        )
        assert submitted["status"] == "CAR_SUBMITTED"
        assert submitted["car_submitted_by_user_id"] == "manager-1"

        manager_rejects = api.transition_audit_finding(
            audit.finding_id,
            {"action": "REJECT_CAR"},
            make_forest_manager_headers("manager-1"),
        )

        validate_error(manager_rejects, ApiErrorId.UNAUTHORIZED.value, 403)
        finding = read_finding(api, audit.finding_id)
        assert finding["status"] == "CAR_SUBMITTED"
        assert finding["rejection_count"] == 0
        assert finding["closed_by_user_id"] is None
        parent = read_audit(api, audit.audit_id)
        assert parent["status"] == "CAR_REVIEW"
        assert parent["open_minor_count"] == 1


class TestCountersigningIsSegregatedTwice:
    """The signer may be neither the submitter nor an author of underwriting work."""

    def test_neither_the_submitter_nor_the_case_author_may_countersign(self, api):
        """A third appraiser signs, and the stamp records the clock instant.

        PRD: "the caller's `X-User-ID` must differ from `appraisal_submitted_by_user_id`, and must not equal the `authored_by_user_id` of *any* underwriting case on that property, whatever that case's state."

        Design: Corner/rbac/the_same_appraiser_cannot_sign_its_own_submission
        """
        ctx = cruised_stand(api)
        create_case(api, ctx.property_id, author="analyst-1")
        submitted = submit_appraisal(
            api,
            ctx.property_id,
            market_appraisal_submit_payload(),
            submitter="appraiser-1",
        )
        assert_money(
            submitted["appraised_value_usd"], 3900000.00, "appraised_value_usd"
        )

        self_sign = api.appraisal_action(
            ctx.property_id, {"action": "SIGN"}, make_appraiser_headers("appraiser-1")
        )
        author_signs = api.appraisal_action(
            ctx.property_id, {"action": "SIGN"}, make_appraiser_headers("analyst-1")
        )

        validate_error(self_sign, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
        validate_error(author_signs, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        signed = validate_success(
            api.appraisal_action(
                ctx.property_id,
                {"action": "SIGN"},
                make_appraiser_headers("appraiser-2"),
            ),
            200,
        )

        assert signed["appraisal_status"] == "SIGNED"
        assert signed["appraisal_signed_by_user_id"] == "appraiser-2"
        assert signed["appraisal_submitted_by_user_id"] == "appraiser-1"
        assert_instant_equals(
            signed["appraisal_signed_at"], DEFAULT_CLOCK_UTC, "appraisal_signed_at"
        )
        assert read_fund(api, ctx.fund_id)["valuation_basis_stale_count"] == 0


class TestTheInvestorPackIsNarrowlyReadable:
    """Three roles see the reporting pack; the other four are refused."""

    def test_only_the_declared_three_roles_read_the_investor_report(self, api):
        """The analyst and the manager are refused while the appraiser is served.

        PRD: "The investor reporting pack is restricted to `FundAdmin`, `InvestmentCommittee`, and `IndependentAppraiser`; the other four roles receive `ERR_UNAUTHORIZED` on it."

        Design: Corner/rbac/an_analyst_cannot_read_the_investor_report
        """
        ctx = owned_tract(api)

        analyst_report = api.get_investor_report(
            ctx.fund_id, make_analyst_headers("analyst-1")
        )
        manager_report = api.get_investor_report(
            ctx.fund_id, make_forest_manager_headers("fm-1")
        )

        validate_error(analyst_report, ApiErrorId.UNAUTHORIZED.value, 403)
        validate_error(manager_report, ApiErrorId.UNAUTHORIZED.value, 403)

        plain_fund = validate_success(
            api.get_fund(ctx.fund_id, make_analyst_headers("analyst-1")), 200
        )
        assert_fund_cash(plain_fund, cash_balance_usd=300000.00)

        report = validate_success(
            api.get_investor_report(
                ctx.fund_id, make_appraiser_headers("appraiser-1")
            ),
            200,
        )

        assert_money(report["nav_usd"], 4200000.00, "nav_usd")
        assert report["owned_property_count"] == 1
        assert report["valuation_basis_stale_count"] == 0
        assert_tons(
            report["standing_inventory_tons"], 4647.12, "standing_inventory_tons"
        )
