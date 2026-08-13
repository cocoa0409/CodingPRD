"""1099 tax form generation, thresholds, year-boundary bases, lifecycle (PRD §3.9)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_tax_form_payload,
    setup_active_agent, setup_agent_on_plan, setup_settled_deal,
    get_leg_by_type, authorize_and_release_leg,
    make_transaction_coordinator_headers, make_office_manager_headers,
)


def _settle_two_deals_and_release_both(api, agent_id, gross_list):
    """Settle N deals and release each AGENT leg. Returns (settlement_ids, nets)."""
    settlements = []
    for i, gross in enumerate(gross_list):
        settlement, _deal = setup_settled_deal(
            agent_id, gross_commission_cents=gross, closing_date=f"2026-01-{15+i:02d}",
            poster_user_id="tc-1")
        settlements.append(settlement)
    for s in settlements:
        leg = get_leg_by_type(s["id"], "AGENT")
        authorize_and_release_leg(leg["id"], authorizer="om-1", releaser="om-2")
    return settlements


class TestTax1099CashVsAccrual:
    def test_cash_zero_when_legs_release_in_later_year(self, api):
        """PRD §3.9: "The filed figure is cash-basis: gross_paid_cents sums the
        amount_cents of every disbursement leg payable to the agent ... that
        stands RELEASED with a released_at on or after January 1 of the tax year
        and strictly before January 1 of the following year." And "a December
        settlement whose legs release in January counts in the earlier year on
        the accrual basis and in the later year on the cash basis."

        Design: Difficulty/dual_variant_calc/tax_1099_cash_basis_vs_accrual_basis_across_year_boundary
        """
        get_success_data(api.set_clock({"to_iso8601": "2026-12-20T00:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        agent, plan, _e = setup_agent_on_plan(agent_name="Betty Basis")
        settlement, deal = setup_settled_deal(
            agent["id"], address="9 Year-End Ln", gross_commission_cents=1000000,
            closing_date="2026-12-20", poster_user_id="tc-77")
        leg = get_leg_by_type(settlement["id"], "AGENT")
        get_success_data(api.set_clock({"to_iso8601": "2027-01-05T00:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        authorize_and_release_leg(leg["id"], authorizer="om-1", releaser="om-2")
        form = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert form["gross_paid_cents"] == 0
        assert form["accrual_gross_cents"] == 658000
        assert form["filing_required"] is False

    def test_cash_and_accrual_diverge_by_year_end_agent_gross(self, api):
        """PRD §3.9: "The informational figure is accrual-basis:
        accrual_gross_cents sums the agent_gross_cents of the agent's own
        settlements that stand POSTED with a posted_at inside the calendar year
        ... Across a year boundary the two legitimately diverge".

        Design: Difficulty/dual_variant_calc/tax_1099_cash_basis_vs_accrual_basis_across_year_boundary
        """
        get_success_data(api.set_clock({"to_iso8601": "2026-12-20T00:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        agent, plan, _e = setup_agent_on_plan(agent_name="Betty Basis")
        settlement, deal = setup_settled_deal(
            agent["id"], gross_commission_cents=1000000, closing_date="2026-12-20",
            poster_user_id="tc-77")
        leg = get_leg_by_type(settlement["id"], "AGENT")
        get_success_data(api.set_clock({"to_iso8601": "2027-01-05T00:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        authorize_and_release_leg(leg["id"], authorizer="om-1", releaser="om-2")
        form2026 = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        # cash basis lands in 2027 (released there), accrual in 2026
        assert form2026["gross_paid_cents"] == 0
        assert form2026["accrual_gross_cents"] == 658000
        assert form2026["accrual_gross_cents"] - form2026["gross_paid_cents"] == 658000


class TestTax1099FilingThreshold:
    def test_filing_threshold_inclusive_at_60000(self, api):
        """PRD §3.9: "filing_required is true exactly when gross_paid_cents
        reaches the reporting threshold of sixty thousand cents — the 600-dollar
        bar — inclusive."

        Design: Difficulty/boundary_precision_check/tax_1099_filing_threshold_inclusive_at_60000
        """
        u1, plan, _e = setup_agent_on_plan(agent_name="Sixty Kane")
        u2, _p, _e2 = setup_agent_on_plan(agent_name="Fifty Nine")
        _settle_two_deals_and_release_both(api, u1["id"], [100000, 85411])
        _settle_two_deals_and_release_both(api, u2["id"], [100000, 85409])
        form1 = get_success_data(api.create_tax_form(
            u1["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        form2 = get_success_data(api.create_tax_form(
            u2["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert form1["gross_paid_cents"] == 60000
        assert form1["filing_required"] is True
        assert form2["gross_paid_cents"] == 59999
        assert form2["filing_required"] is False

    def test_one_cent_below_threshold_stays_not_required(self, api):
        """PRD §3.9: "filing_required is true exactly when gross_paid_cents
        reaches the reporting threshold of sixty thousand cents — the 600-dollar
        bar — inclusive."

        Design: Difficulty/boundary_precision_check/tax_1099_filing_threshold_inclusive_at_60000
        """
        u2, _p, _e2 = setup_agent_on_plan(agent_name="Fifty Nine")
        _settle_two_deals_and_release_both(api, u2["id"], [100000, 85409])
        form2 = get_success_data(api.create_tax_form(
            u2["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert form2["gross_paid_cents"] == 59999
        assert form2["filing_required"] is False


class TestTaxFormDraftSupersede:
    def test_regeneration_supersedes_existing_draft(self, api):
        """PRD §3.9: "If a DRAFT form already exists for the same agent and year,
        it is superseded — moved to VOIDED — and replaced by the new draft".

        Design: Corner/endpoints/tax_form_draft_supersede_and_regeneration
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Regen Rhonda")
        s1, _d1 = setup_settled_deal(agent["id"], gross_commission_cents=100000,
                                     closing_date="2026-01-15", poster_user_id="tc-1")
        s2, _d2 = setup_settled_deal(agent["id"], gross_commission_cents=85411,
                                     closing_date="2026-01-20", poster_user_id="tc-1")
        authorize_and_release_leg(get_leg_by_type(s1["id"], "AGENT")["id"])
        tf1 = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert tf1["gross_paid_cents"] == 34800
        authorize_and_release_leg(get_leg_by_type(s2["id"], "AGENT")["id"])
        tf2 = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        tf1_after = get_success_data(api.get_tax_form(tf1["id"], TEST_USERS["broker_admin_headers"]))
        assert tf1_after["status"] == "VOIDED"
        assert tf2["gross_paid_cents"] == 60000
        assert tf2["status"] == "DRAFT"

    def test_regeneration_recomputes_snapshot(self, api):
        """PRD §3.9: "Generation computes the figures as of that instant."

        Design: Corner/endpoints/tax_form_draft_supersede_and_regeneration
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Regen Rhonda")
        s1, _d1 = setup_settled_deal(agent["id"], gross_commission_cents=100000,
                                     closing_date="2026-01-15", poster_user_id="tc-1")
        authorize_and_release_leg(get_leg_by_type(s1["id"], "AGENT")["id"])
        tf1 = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        # Regenerate with no further activity: figures recomputed identically
        tf2 = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert tf2["gross_paid_cents"] == tf1["gross_paid_cents"]
        assert get_success_data(api.get_tax_form(tf1["id"], TEST_USERS["broker_admin_headers"]))["status"] == "VOIDED"


class TestTaxFormFinalizedLock:
    def test_finalized_blocks_regeneration_until_voided(self, api):
        """PRD §3.9: "if a FINALIZED, non-voided form exists for the same pair,
        generation is blocked outright with ERR_TAX_FORM_FINALIZED_EXISTS (HTTP
        409)."

        Design: Corner/endpoints/tax_form_finalized_blocks_then_void_allows
        """
        agent = setup_active_agent(name="Lock Lois")
        tf = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        finalized = get_success_data(api.finalize_tax_form(tf["id"], TEST_USERS["broker_admin_headers"]))
        assert finalized["status"] == "FINALIZED"
        resp = api.create_tax_form(agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_TAX_FORM_FINALIZED_EXISTS, expected_status=409)
        voided = get_success_data(api.void_tax_form(tf["id"], TEST_USERS["broker_admin_headers"]))
        assert voided["status"] == "VOIDED"
        regen = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert regen["status"] == "DRAFT"

    def test_finalize_moves_draft_to_finalized(self, api):
        """PRD §3.9: "Finalizing moves it from DRAFT to FINALIZED, locking the
        snapshot for filing; voiding moves it from either DRAFT or FINALIZED to
        the terminal VOIDED state".

        Design: Corner/endpoints/tax_form_finalized_blocks_then_void_allows
        """
        agent = setup_active_agent(name="Lock Lois")
        tf = get_success_data(api.create_tax_form(
            agent["id"], {"tax_year": 2026}, TEST_USERS["broker_admin_headers"]))
        assert tf["status"] == "DRAFT"
        finalized = get_success_data(api.finalize_tax_form(tf["id"], TEST_USERS["broker_admin_headers"]))
        assert finalized["status"] == "FINALIZED"
        voided = get_success_data(api.void_tax_form(finalized["id"], TEST_USERS["broker_admin_headers"]))
        assert voided["status"] == "VOIDED"


class TestTaxYearRange:
    def test_tax_year_before_join_year_and_after_clock_year_rejected(self, api):
        """PRD §3.9: the tax_year "must fall no earlier than the calendar year of
        the agent's joined_at and no later than the year of the clock date, else
        ERR_TAX_YEAR_INVALID (HTTP 422)."

        Design: Corner/endpoints/tax_year_range_validation
        """
        agent = setup_active_agent(joined_at="2025-09-01", name="Year Yara")
        resp1 = api.create_tax_form(agent["id"], {"tax_year": 2024}, TEST_USERS["broker_admin_headers"])
        validate_error(resp1, ApiErrorId.ERR_TAX_YEAR_INVALID, expected_status=422)
        resp2 = api.create_tax_form(agent["id"], {"tax_year": 2027}, TEST_USERS["broker_admin_headers"])
        validate_error(resp2, ApiErrorId.ERR_TAX_YEAR_INVALID, expected_status=422)

    def test_join_year_and_clock_year_are_accepted(self, api):
        """PRD §3.9: the tax_year "must fall no earlier than the calendar year of
        the agent's joined_at and no later than the year of the clock date" —
        both bounds are inclusive of valid years.

        Design: Corner/endpoints/tax_year_range_validation
        """
        agent = setup_active_agent(joined_at="2025-09-01", name="Year Yara")
        f1 = get_success_data(api.create_tax_form(agent["id"], {"tax_year": 2025},
                                                  TEST_USERS["broker_admin_headers"]))
        assert f1["status"] == "DRAFT"
        f2 = get_success_data(api.create_tax_form(agent["id"], {"tax_year": 2026},
                                                  TEST_USERS["broker_admin_headers"]))
        assert f2["status"] == "DRAFT"
