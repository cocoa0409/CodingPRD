"""Cross-cutting layers: optimistic concurrency on the partnership, and filtered paging."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_bursar_headers,
    make_partner_account_lead_headers,
    make_provost_headers,
)

AMENDED_TIERS = [
    {"through_cents": 100000, "partner_rate": 0.60},
    {"through_cents": 200000, "partner_rate": 0.50},
    {"through_cents": None, "partner_rate": 0.40},
]


class TestStatementCreateConcurrency:
    def test_a_statement_cut_against_a_superseded_version_is_refused(self, api):
        """An amendment slipped between the read and the cut, so the stale cut writes nothing.

        PRD: "`POST /partnerships/{id}/remittance-statements` likewise requires
        `expected_partnership_version` as a non-optional input field carrying the client's last
        observed `version` of the parent `Partnership`, and a value that does not equal the
        partnership's current `version` is rejected with `ERR_STALE_PARTNERSHIP_VERSION` and HTTP
        412."
        PRD: "It becomes 1 at registration and increments by one on each contract action, on each
        terms amendment, on each `Program` creation under that partnership, and on each settlement
        statement creation."

        Design: Corner/cross_cutting_complexity_layers/stale_partnership_version_on_statement_create_returns_412
        """
        context = fixtures.build_paid_enrollment(api, final_clock=fixtures.CLOCK_OCT_1)
        ps_id = context["ps_id"]

        observed_version = fixtures.current_partnership_version(api, ps_id)
        amended = validate_success(
            api.amend_partnership_terms(
                ps_id,
                {
                    "expected_partnership_version": observed_version,
                    "revenue_share_tiers": AMENDED_TIERS,
                },
                headers=make_partner_account_lead_headers(ps_id),
            ),
            200,
        )
        assert amended["version"] == observed_version + 1

        response = api.create_remittance_statement(
            ps_id,
            factories.statement_payload(observed_version),
            headers=make_bursar_headers(),
        )

        validate_error(response, ApiErrorId.STALE_PARTNERSHIP_VERSION.value, 412)

        assert fixtures.read_partnership(api, ps_id)["version"] == observed_version + 1
        summary = validate_success(
            api.get_revenue_summary(ps_id, headers=make_provost_headers())
        )
        assert summary["open_statement_count"] == 0


class TestPartnershipVersionCounter:
    def test_the_version_counts_writes_rather_than_status_changes(self, api):
        """Five contract-level writes each add one while the whole child chain adds none.

        PRD: "A `Partnership`'s `version` is the coordination point for the whole aggregate, so its
        advance is deliberately narrow. It becomes 1 at registration and increments by one on each
        contract action, on each terms amendment, on each `Program` creation under that partnership,
        and on each settlement statement creation. Recomputation of the partnership's derived ledger
        totals caused by a deeper child write — a tuition posting, a marketing entry, a remittance —
        refreshes `updated_at` on the partnership without advancing `version`, so a client holding a
        version number is only invalidated by writes that genuinely restate the contract or the
        settlement history."
        PRD: "A newly registered partnership is `DRAFT` with `version` 1."

        Design: Corner/cross_cutting_complexity_layers/partnership_version_increments_on_every_successful_write
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.register_partnership(api)
        ps_id = partnership["id"]
        assert partnership["version"] == 1
        assert fixtures.submit_partnership_for_review(api, ps_id)["version"] == 2
        assert fixtures.execute_partnership(api, ps_id)["version"] == 3

        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        assert fixtures.read_partnership(api, ps_id)["version"] == 4

        fixtures.create_approved_course(api, ps_id, pg_id)
        fixtures.assign_service_scope(api, pg_id, "MARKETING")
        fixtures.submit_program(api, ps_id, pg_id)
        fixtures.approve_program(api, pg_id)
        fixtures.launch_program(api, ps_id, pg_id)
        counselor = fixtures.create_eligible_counselor(api, ps_id)
        lead = fixtures.create_applied_lead(api, ps_id, pg_id, counselor["id"])
        enrollment = fixtures.enroll_lead(api, lead["id"])
        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)
        fixtures.post_tuition_entry(api, enrollment["id"])
        assert fixtures.read_partnership(api, ps_id)["version"] == 4

        fixtures.set_clock(api, fixtures.CLOCK_OCT_1)
        amended = validate_success(
            api.amend_partnership_terms(
                ps_id,
                {"expected_partnership_version": 4, "revenue_share_tiers": AMENDED_TIERS},
                headers=make_partner_account_lead_headers(ps_id),
            ),
            200,
        )
        assert amended["version"] == 5

        statement = validate_success(
            api.create_remittance_statement(
                ps_id, factories.statement_payload(5), headers=make_bursar_headers()
            ),
            201,
        )
        assert statement["status"] == "CALCULATED"

        stored = fixtures.read_partnership(api, ps_id)
        assert stored["version"] == 6
        assert stored["status"] == "EXECUTED"


class TestTermsAmendmentConcurrency:
    def test_a_replayed_amendment_computed_from_the_same_read_is_refused(self, api):
        """Two amendments off one read are state-identical, so only the version tells them apart.

        PRD: "`PATCH /partnerships/{id}/terms` requires `expected_partnership_version` as a
        non-optional input field carrying the client's last observed `version` of the target
        `Partnership`. If the supplied value does not equal the partnership's current `version`, the
        amendment is rejected with `ERR_STALE_PARTNERSHIP_VERSION` and HTTP 412."
        PRD: "Term amendments are legitimately repeatable — a second amendment observing the same
        partnership `status` would itself be a valid request — so state alone cannot distinguish a
        correct amendment from one computed against superseded tiers, a superseded marketing envelope
        or a superseded recognition method. The version check is the only deterministic guard."

        Design: Corner/cross_cutting_complexity_layers/stale_partnership_version_on_terms_patch_returns_412
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        observed_version = fixtures.current_partnership_version(api, ps_id)
        assert observed_version == 3

        first = validate_success(
            api.amend_partnership_terms(
                ps_id,
                {
                    "expected_partnership_version": observed_version,
                    "revenue_share_tiers": AMENDED_TIERS,
                },
                headers=make_partner_account_lead_headers(ps_id),
            ),
            200,
        )
        assert first["version"] == 4

        response = api.amend_partnership_terms(
            ps_id,
            {
                "expected_partnership_version": observed_version,
                "marketing_budget_cents": 5000000,
            },
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.STALE_PARTNERSHIP_VERSION.value, 412)

        stored = fixtures.read_partnership(api, ps_id)
        assert stored["version"] == 4
        assert stored["marketing_budget_cents"] == 4000000
        assert stored["revenue_share_tiers"] == AMENDED_TIERS


class TestFilteredPaging:
    def test_the_status_filter_is_applied_before_the_page_is_cut(self, api):
        """Of three leads only two are CONTACTED, and the total counts those two, not all three.

        PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the
        envelope's `meta` object, where `total_count` counts the records matching the request's
        filters before pagination is applied and `has_more` is true exactly when records remain
        beyond the returned page."
        PRD: "Unless a specific endpoint says otherwise, list results are ordered by `created_at`
        ascending."
        PRD: "Leads may be listed filtered by `program_id`, by `counselor_id` and by `status`."

        Design: Corner/cross_cutting_complexity_layers/lead_listing_combines_status_filter_with_offset_paging
        """
        context = fixtures.build_launched_program(api)
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

        first = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        fixtures.enroll_lead(api, first["id"])
        second = fixtures.create_lead(
            api, ps_id, pg_id, co_id, prospect_external_id="P-1002", source_channel="PAID_SOCIAL"
        )
        fixtures.contact_lead(api, ps_id, second["id"], 9)
        third = fixtures.create_lead(
            api, ps_id, pg_id, co_id, prospect_external_id="P-1003", source_channel="ORGANIC"
        )
        fixtures.contact_lead(api, ps_id, third["id"], 40)

        rows, meta = validate_paginated(
            api.list_leads(
                {"counselor_id": co_id, "status": "CONTACTED", "limit": 1, "offset": 1},
                headers=make_partner_account_lead_headers(ps_id),
            )
        )

        assert len(rows) == 1
        assert rows[0]["id"] == third["id"]
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 1
        assert meta["offset"] == 1
