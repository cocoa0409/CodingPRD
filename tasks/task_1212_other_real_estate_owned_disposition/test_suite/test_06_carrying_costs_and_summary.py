"""Carrying costs (capitalized vs expensed, rounding at posting), the summary
reconciliation read, and the immediate-consistency guarantee."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property,
    create_property_with_certified_appraisal,
    create_carrying_cost_payload,
    create_appraiser,
    create_draft_appraisal,
    submit_appraisal,
    certify_appraisal,
    get_property,
    get_property_summary,
    list_write_downs,
    setup_settled_sale,
    assert_property_summary_invariants,
    set_clock,
    make_oreo_committee_headers,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
PM = TEST_USERS["property_manager_headers"]
COMMITTEE = TEST_USERS["oreo_committee_headers"]


class TestCarryingCostAccounting:
    def test_carrying_cost_capitalized_vs_expensed_accounting(self, api):
        """PRD §3.2: "Posting rounds the amount half-up to two decimal places
        and stores it at that precision; the rounding order is pinned per
        entry, so aggregates sum the already-rounded stored values. Posting a
        cost appends a CARRYING_COST ledger entry carrying the negative of the
        posted amount, increments the parent property's version by one, and
        updates the two running totals: amounts with cost_type
        CAPITAL_IMPROVEMENT accumulate into capitalized_cost_total and
        therefore raise carrying_value, while every other cost type accumulates
        into expensed_cost_total and never touches carrying_value."

        Design: Corner/calculations/carrying_cost_capitalized_vs_expensed_accounting
        """
        prop = create_property()
        # capital improvement
        r1 = api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=prop["id"],
                cost_type="CAPITAL_IMPROVEMENT",
                amount=10000.00,
                incurred_date="2026-07-01",
                description="Roof replacement",
            ),
            PM,
        )
        cc1 = validate_success(r1, expected_status=201)
        assert cc1["amount"] == 10000.00

        # taxes with 3dp — rounds half-up at posting
        r2 = api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=prop["id"],
                cost_type="TAXES",
                amount=2500.456,
                incurred_date="2026-07-15",
            ),
            PM,
        )
        cc2 = validate_success(r2, expected_status=201)
        assert cc2["amount"] == 2500.46

        summary = get_property_summary(prop["id"])
        assert summary["capitalized_cost_total"] == 10000.00
        assert summary["expensed_cost_total"] == 2500.46
        # carrying raises only by the capitalized portion
        assert summary["carrying_value"] == 378000.00

    def test_mutations_visible_immediately_in_responses(self, api):
        """PRD §3.2: "Posting rounds the amount half-up to two decimal places
        and stores it at that precision"; the very next read must agree (PRD
        §2.4 version / §3.2 immediate identity). The create response and the
        next read agree with no reconciliation lag.

        Design: Corner/consistency_model/mutations_visible_immediately_in_responses
        """
        prop = create_property()
        r = api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=prop["id"],
                cost_type="TAXES",
                amount=2500.456,
                incurred_date="2026-06-15",
            ),
            PM,
        )
        cc = validate_success(r, expected_status=201)
        assert cc["amount"] == 2500.46
        # immediately following read reflects the rounding + totals
        after = get_property(prop["id"])
        assert after["expensed_cost_total"] == 2500.46
        assert after["carrying_value"] == 368000.00

    def test_list_carrying_costs_filtered_by_property(self, api):
        """PRD §3.12: "the carrying-cost list filters by property_id and
        cost_type".

        Design: Corner/endpoints/list_carrying_costs_filtered_by_property
        """
        p1 = create_property(address="1 A St")
        p2 = create_property(
            address="2 B St",
            county="Marin",
            property_type="COMMERCIAL",
            acquisition_date="2026-05-12",
            bpo_value=800000.00,
            foreclosure_debt=790000.00,
        )
        api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=p1["id"], cost_type="TAXES", amount=1200.00
            ),
            PM,
        )
        api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=p2["id"],
                cost_type="INSURANCE",
                amount=3400.00,
                incurred_date="2026-06-16",
            ),
            PM,
        )
        resp = api.list_carrying_costs(ADMIN, params={"property_id": p1["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["property_id"] == p1["id"]
        assert data[0]["amount"] == 1200.00

    def test_carrying_cost_on_disposed_property_returns_terminal_error(self, api):
        """PRD §3.2: "Carrying costs may only be posted against a non-terminal
        property; targeting a DISPOSED or CHARGED_OFF property is rejected with
        ERR_PROPERTY_ALREADY_TERMINAL."

        Design: Corner/validations/carrying_cost_on_disposed_property_returns_terminal_error
        """
        ctx = setup_settled_sale()  # property DISPOSED
        prop = ctx["property"]
        resp = api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=prop["id"],
                cost_type="TAXES",
                amount=1200.00,
                incurred_date="2026-09-01",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_ALREADY_TERMINAL)


class TestSummaryReconciliation:
    def test_summary_reconciles_carrying_value_components(self, api):
        """PRD §3.1: "A property's carrying_value is never a stored number that
        drifts; it is always the reconciliation identity acquisition_basis plus
        capitalized_cost_total minus the sum of amount over all POSTED
        write-downs, and the summary read recomputes and reports it alongside
        posted_write_down_total, current_fair_value, net_realizable_value, and
        the various open-issue and listing counts."

        Design: Corner/endpoints/summary_reconciles_carrying_value_components
        """
        prop = create_property()
        set_clock("2026-12-10T00:00:00Z")
        # capitalize 10000
        api.create_carrying_cost(
            create_carrying_cost_payload(
                property_id=prop["id"],
                cost_type="CAPITAL_IMPROVEMENT",
                amount=10000.00,
                incurred_date="2026-07-01",
                description="Roof replacement",
            ),
            PM,
        )
        appraiser = create_appraiser()
        # appraisal is outside the 180-day window (2026-05-10 + 180 = 2026-11-06)
        prop_now = get_property(prop["id"])
        a = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop_now["version"],
            effective_date="2026-12-10",
            appraised_value=350000.00,
        )
        submit_appraisal(a["id"], appraiser["id"])
        certify_appraisal(a["id"])

        # auto-created PROPOSED write-down: carrying 378000 - NRV(350000) 322000 = 56000
        wds = list_write_downs(prop["id"])
        assert len(wds) == 1
        wd = wds[0]
        # approve it
        approve_resp = api.approve_write_down(
            wd["id"], make_oreo_committee_headers("committee-1")
        )
        validate_success(approve_resp, expected_status=200)

        summary = get_property_summary(prop["id"])
        assert summary["acquisition_basis"] == 368000.00
        assert summary["capitalized_cost_total"] == 10000.00
        assert summary["posted_write_down_total"] == 56000.00
        assert summary["carrying_value"] == 322000.00
        # carrying reconciles exactly with NRV after the write-down
        assert summary["net_realizable_value"] == 322000.00
        assert summary["pending_write_down_count"] == 0
        assert summary["open_environmental_issue_count"] == 0
        assert_property_summary_invariants(summary)
