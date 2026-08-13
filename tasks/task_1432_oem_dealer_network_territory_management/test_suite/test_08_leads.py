"""Lead routing: eligibility, ranking, decline/expiry loops, and listing."""
from test_helpers import (
    ApiErrorId,
    assert_lead,
    create_assignment,
    create_lead,
    make_dealer_user_headers,
    route_lead,
    set_clock,
    setup_active_dealer,
    setup_active_dealer_with_assignment,
    setup_routed_lead,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDeclineAndRerouteCycle:
    """ROUTED -> DECLINED -> ROUTED: the decliner is excluded from the
    re-route, so the lead moves to the other covered dealer."""

    def _setup_two_shared_dealers(self, api):
        first_ctx = setup_active_dealer_with_assignment(
            "DL-F1", "T-100", coverage_type="SHARED")
        second_ctx = setup_active_dealer_with_assignment(
            "DL-F2", "T-100", coverage_type="SHARED")
        return first_ctx, second_ctx

    def test_initial_route_tie_breaks_by_earliest_created_dealer(
            self, api, sales_ops_headers, oem_admin_headers):
        """PRD section 3.7: "Among the candidates, the winner is the dealer with the fewest currently open leads — leads in `ROUTED` status routed to that dealer — and ties are broken in favor of the dealer with the earliest `created_at`. When a winner exists, the lead moves to `ROUTED`, its `routed_dealer_id` and `routed_assignment_id` are set to the winning dealer and the assignment that qualified them, and `routed_at` is stamped with the current logical clock."

        Design: Difficulty/non_linear_state_machine/lead_decline_and_reroute_cycle
        """
        first_ctx, second_ctx = self._setup_two_shared_dealers(api)
        lead = create_lead("T-100", product_line="EXCAVATOR",
                           estimated_value_cents=500000, contact_name="Sam")

        routed = validate_success(api.route_lead(lead["id"],
                                                 sales_ops_headers), 200)
        assert_lead(routed)
        assert routed["status"] == "ROUTED"
        assert routed["routed_dealer_id"] == first_ctx["dealer"]["id"], (
            "both dealers tie at zero open leads; the earliest-created "
            "dealer must win"
        )
        assert routed["routed_assignment_id"] == first_ctx["assignment"]["id"]
        assert routed["routed_at"] is not None

    def test_decline_excludes_dealer_from_reroute(self, api,
                                                  sales_ops_headers,
                                                  oem_admin_headers):
        """PRD section 3.7: "A `response` of `DECLINE` moves it to `DECLINED`, appends the dealer's `id` to `declined_dealer_ids`, and clears the routing fields."
        PRD section 3.7: "Re-routing a previously `DECLINED` or `EXPIRED` lead follows the same selection, with the prior decliner or expired dealer excluded through `declined_dealer_ids`."

        Design: Difficulty/non_linear_state_machine/lead_decline_and_reroute_cycle
        """
        first_ctx, second_ctx = self._setup_two_shared_dealers(api)
        first_dealer = first_ctx["dealer"]
        second_dealer = second_ctx["dealer"]
        lead = create_lead("T-100", product_line="EXCAVATOR",
                           estimated_value_cents=500000, contact_name="Sam")
        routed = route_lead(lead["id"])
        assert routed["routed_dealer_id"] == first_dealer["id"]

        declined = validate_success(
            api.respond_lead(lead["id"], {"response": "DECLINE"},
                             make_dealer_user_headers(first_dealer["id"])),
            200)
        assert declined["status"] == "DECLINED"
        assert first_dealer["id"] in declined["declined_dealer_ids"]
        assert declined["routed_dealer_id"] is None

        rerouted = validate_success(api.route_lead(lead["id"],
                                                   sales_ops_headers), 200)
        assert rerouted["status"] == "ROUTED"
        assert rerouted["routed_dealer_id"] == second_dealer["id"], (
            "the decliner must be excluded from the re-route"
        )

        accepted = validate_success(
            api.respond_lead(lead["id"], {"response": "ACCEPT"},
                             make_dealer_user_headers(second_dealer["id"])),
            200)
        assert accepted["status"] == "ACCEPTED"


class TestEmptyCandidatePool:
    """Routing with zero eligible dealers orphans the lead without error."""

    def test_empty_candidate_pool_orphans_lead_without_error(
            self, api, sales_ops_headers):
        """PRD section 3.7: "When the pool is empty, the lead moves to `ORPHANED` instead — this is a normal outcome, not an error — and its routing fields remain null."

        Design: Difficulty/boundary_precision_check/lead_route_empty_pool_orphans
        """
        lead = create_lead("T-EMPTY", product_line="CRANE",
                           estimated_value_cents=900000, contact_name="Rae")
        # No dealer covers T-EMPTY: the candidate pool is empty.
        routed = validate_success(api.route_lead(lead["id"],
                                                 sales_ops_headers), 200)
        assert routed["status"] == "ORPHANED"
        assert routed["routed_dealer_id"] is None
        assert routed["routed_assignment_id"] is None
        assert routed["routed_at"] is None

    def test_orphaned_lead_routes_once_coverage_exists(
            self, api, sales_ops_headers):
        """PRD section 3.7: "Routing is a selection, not a guess, and it may be invoked from any routable state — `NEW`, `ORPHANED`, `DECLINED`, or `EXPIRED` (`ERR_LEAD_INVALID_STATE` otherwise)."

        Design: Difficulty/boundary_precision_check/lead_route_empty_pool_orphans
        """
        lead = create_lead("T-EMPTY", product_line="CRANE",
                           estimated_value_cents=900000, contact_name="Rae")
        orphaned = route_lead(lead["id"])
        assert orphaned["status"] == "ORPHANED"

        ctx = setup_active_dealer("DL-L1", name="Dealer L1")
        create_assignment(ctx["dealer"]["id"], ctx["agreement"]["id"],
                          "T-EMPTY", coverage_type="EXCLUSIVE")

        routed = validate_success(api.route_lead(lead["id"],
                                                 sales_ops_headers), 200)
        assert routed["status"] == "ROUTED"
        assert routed["routed_dealer_id"] == ctx["dealer"]["id"]


class TestLeadRanking:

    def test_lead_selector_ranks_by_open_lead_count(self, api,
                                                    sales_ops_headers):
        """PRD section 3.7: "Among the candidates, the winner is the dealer with the fewest currently open leads — leads in `ROUTED` status routed to that dealer — and ties are broken in favor of the dealer with the earliest `created_at`."

        Design: Corner/calculations/lead_selector_ranks_by_open_lead_count
        """
        first_ctx = setup_active_dealer_with_assignment(
            "DL-CC2", "T-150", coverage_type="SHARED")
        second_ctx = setup_active_dealer_with_assignment(
            "DL-CC3", "T-150", coverage_type="SHARED")

        lead1 = create_lead("T-150", product_line="LOADER",
                            estimated_value_cents=100000, contact_name="One")
        routed1 = route_lead(lead1["id"])
        assert routed1["routed_dealer_id"] == first_ctx["dealer"]["id"], (
            "with zero open leads on both sides the earliest-created "
            "dealer wins the tie-break"
        )

        lead2 = create_lead("T-150", product_line="LOADER",
                            estimated_value_cents=200000, contact_name="Two")
        routed2 = validate_success(api.route_lead(lead2["id"],
                                                  sales_ops_headers), 200)
        assert routed2["routed_dealer_id"] == second_ctx["dealer"]["id"], (
            "the first dealer already carries one ROUTED lead, so the "
            "second dealer wins on open_lead_count 0 < 1"
        )


class TestLeadStateRules:

    def test_lead_route_from_accepted_terminal_lockdown(
            self, api, sales_ops_headers, oem_admin_headers):
        """PRD section 3.7: "Routing is a selection, not a guess, and it may be invoked from any routable state — `NEW`, `ORPHANED`, `DECLINED`, or `EXPIRED` (`ERR_LEAD_INVALID_STATE` otherwise)."

        Design: Corner/state_machines/lead_route_from_accepted_terminal_lockdown
        """
        ctx = setup_routed_lead("DL-SM5", "T-SM")
        dealer_id = ctx["dealer"]["id"]
        lead_id = ctx["lead"]["id"]
        accepted = validate_success(
            api.respond_lead(lead_id, {"response": "ACCEPT"},
                             make_dealer_user_headers(dealer_id)), 200)
        assert accepted["status"] == "ACCEPTED"

        resp = api.route_lead(lead_id, sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_LEAD_INVALID_STATE)

        unchanged = validate_success(api.get_lead(lead_id, oem_admin_headers),
                                     200)
        assert unchanged["status"] == "ACCEPTED"

    def test_lead_expire_before_sla_rejected(self, api, sales_ops_headers,
                                             oem_admin_headers):
        """PRD section 3.7: "If the dealer simply lets the clock run, `OemSalesOps` may expire the lead once the current logical datetime is more than 72 hours past `routed_at` (`ERR_LEAD_NOT_YET_EXPIRED` before then): the lead moves to `EXPIRED`, the unresponsive dealer is appended to `declined_dealer_ids` just as if they had declined, and the routing fields are cleared."

        Design: Corner/validations/lead_expire_before_sla_rejected
        """
        # Routed at the startup clock of 2026-08-01T00:00:00Z.
        ctx = setup_routed_lead("DL-LE1", "T-LE")
        lead_id = ctx["lead"]["id"]
        # One hour later: far inside the 72-hour response window.
        set_clock("2026-08-01T01:00:00Z")

        resp = api.expire_lead(lead_id, sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_LEAD_NOT_YET_EXPIRED)

        unchanged = validate_success(api.get_lead(lead_id, oem_admin_headers),
                                     200)
        assert unchanged["status"] == "ROUTED"


class TestLeadAccessRules:

    def test_auditor_cannot_route_leads(self, api, auditor_headers,
                                        oem_admin_headers):
        """PRD section 2.1: "Beyond header presence, each operation is restricted to specific roles; a caller whose role is not permitted for the endpoint receives `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: "| POST | `/network/leads/{leadId}/route` | Route or re-route via eligibility, ranking, tie-break; empty pool yields `ORPHANED` | OemSalesOps |"

        Design: Corner/rbac/auditor_cannot_route_leads
        """
        lead = create_lead("T-RB", product_line="DOZER",
                           estimated_value_cents=100000, contact_name="Bo")

        resp = api.route_lead(lead["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        unchanged = validate_success(api.get_lead(lead["id"],
                                                  oem_admin_headers), 200)
        assert unchanged["status"] == "NEW"

    def test_non_routed_dealer_cannot_respond_to_lead(
            self, api, oem_admin_headers):
        """PRD section 3.7: "The responding `DealerUser` must be the dealer the lead is currently routed to (`ERR_LEAD_NOT_ROUTED_TO_DEALER`), and the lead must be `ROUTED` (`ERR_LEAD_INVALID_STATE`)."

        Design: Corner/rbac/non_routed_dealer_cannot_respond_to_lead
        """
        first_ctx = setup_active_dealer_with_assignment(
            "DL-RN1", "T-RN", coverage_type="SHARED")
        second_ctx = setup_active_dealer_with_assignment(
            "DL-RN2", "T-RN", coverage_type="SHARED")
        lead = create_lead("T-RN", product_line="DOZER",
                           estimated_value_cents=100000, contact_name="Cy")
        routed = route_lead(lead["id"])
        assert routed["routed_dealer_id"] == first_ctx["dealer"]["id"]

        resp = api.respond_lead(
            lead["id"], {"response": "ACCEPT"},
            make_dealer_user_headers(second_ctx["dealer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LEAD_NOT_ROUTED_TO_DEALER)

        unchanged = validate_success(api.get_lead(lead["id"],
                                                  oem_admin_headers), 200)
        assert unchanged["status"] == "ROUTED"
        assert unchanged["routed_dealer_id"] == first_ctx["dealer"]["id"]


class TestLeadListing:

    def test_leads_pagination_limit_offset_interaction(
            self, api, sales_ops_headers, oem_admin_headers):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD section 2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/leads_pagination_limit_offset_interaction
        """
        create_lead("T-PG", estimated_value_cents=100000, contact_name="L1")
        create_lead("T-PG", estimated_value_cents=110000, contact_name="L2")
        create_lead("T-PG", product_line="LOADER",
                    estimated_value_cents=120000, contact_name="L3")

        data1, meta1 = validate_paginated(
            api.list_leads(oem_admin_headers, params={"limit": 2,
                                                      "offset": 0}))
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_leads(oem_admin_headers, params={"limit": 2,
                                                      "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
