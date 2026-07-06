"""Role-based access control, Customer ownership, unauthenticated requests, and optimistic
concurrency on scope creation (PRD §2.1, §2.7, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_draft_quote,
    setup_sent_quote,
    setup_in_progress_job,
    create_lead,
    create_completed_inspection,
    create_draft_scope,
    create_scope_payload,
    complete_job_payload,
    make_customer_headers,
    build_user_headers,
    api_client,
    SALES,
    ENGINEER,
    ApiErrorId,
)


class TestRbac:
    def test_customer_cannot_send_quote(self, api):
        """PRD §2.1: "When a recognized role attempts an operation it is not permitted to
        perform, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_cannot_send_quote_forbidden
        """
        ctx = setup_draft_quote(financing_plan="CASH")
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.send_quote(ctx["quote"]["id"], headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_salesagent_cannot_complete_job(self, api):
        """PRD §2.1: "When a recognized role attempts an operation it is not permitted to
        perform, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/salesagent_cannot_complete_job_forbidden
        """
        ctx = setup_in_progress_job(soil_class="STABLE")
        res = api.complete_job(ctx["job"]["id"], complete_job_payload(), SALES)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_customer_accepting_foreign_leads_quote_forbidden(self, api):
        """PRD §2.1: "Ownership is then enforced on every customer-scoped mutation — the
        caller's `X-User-ID` must equal the `Lead.id` that owns the target resource."
        PRD §2.1: "A customer acting on a resource belonging to a different lead is rejected
        with `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_accept_foreign_lead_forbidden
        """
        ctx = setup_sent_quote(financing_plan="CASH")  # quote owned by lead A
        lead_b = create_lead(region_code="NORTH", customer_name="Owner B")
        foreign = make_customer_headers(lead_b["id"])
        res = api.accept_quote(ctx["quote"]["id"], foreign)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_unrecognized_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing `X-User-Role`, or presenting a value that is not one
        of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_role_returns_unauthenticated
        """
        headers = build_user_headers("test-nobody", "Nobody")
        res = api.create_lead(
            {"customer_name": "No Role", "property_address": "27 Nr St",
             "contact_email": "no@x.com", "region_code": "NORTH"},
            headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestScopeCreationConcurrency:
    def test_stale_expected_lead_version_rejected(self, api):
        """PRD §2.7: "If another writer has already created a superseding scope (and thereby
        advanced the lead's `version`) since this client last read the lead, the supplied
        `expected_lead_version` no longer matches the lead's current `version`, the caller's
        view is stale, and the creation is rejected with `ERR_STALE_VERSION` at HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_scope_create_stale_version_conflict
        """
        lead = create_lead(region_code="NORTH")  # version 1
        inspection = create_completed_inspection(lead["id"], soil_class="STABLE")
        stale_version = lead["version"]
        # Scope A advances Lead.version past stale_version.
        create_draft_scope(lead, inspection["id"], pier_count=8)
        # Scope B still carries the now-stale expected_lead_version.
        res = api.create_scope(
            create_scope_payload(lead["id"], inspection["id"], stale_version,
                                 pier_count=10, avg_pier_depth_ft=20),
            ENGINEER,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    def test_fresh_version_supersedes_prior_scope(self, api):
        """PRD §3.2: "any prior `EngineeringScope` for the same lead that is currently in
        `DRAFT` or `ENGINEERED` is transitioned to the terminal `SUPERSEDED` state, and the
        lead's `version` is incremented by one."
        PRD §3.2: "A new scope opens in `DRAFT`."

        Design: Corner/cross_cutting_complexity_layers/occ_scope_create_fresh_version_supersedes
        """
        lead = create_lead(region_code="NORTH")
        inspection = create_completed_inspection(lead["id"], soil_class="STABLE")
        scope_a = create_draft_scope(lead, inspection["id"], pier_count=8)
        # Re-read the lead's advanced version before creating the superseding scope.
        fresh = validate_success(api.get_lead(lead["id"], ENGINEER), 200)
        scope_b = get_success_data(
            api.create_scope(
                create_scope_payload(lead["id"], inspection["id"], fresh["version"],
                                     pier_count=10, avg_pier_depth_ft=20),
                ENGINEER,
            )
        )
        scope_a_after = validate_success(api.get_scope(scope_a["id"], ENGINEER), 200)
        assert scope_a_after["status"] == "SUPERSEDED", scope_a_after
        assert scope_b["status"] == "DRAFT", scope_b
