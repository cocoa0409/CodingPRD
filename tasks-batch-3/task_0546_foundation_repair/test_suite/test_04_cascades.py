"""Cascading side effects (PRD §2.8, §3.6, §3.8): install->warranty->visit->lead counter,
and claim-approve->remediation-job->warranty counter; plus warranty/claim actions."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_completed_install,
    setup_approved_claim,
    setup_claim_under_review,
    make_customer_headers,
    create_claim_payload,
    api_client,
    OPS,
    ADJUSTER,
    ApiErrorId,
)


class TestInstallCompletionCascade:
    def test_install_complete_activates_warranty(self, api):
        """PRD §3.6: "first, a `Warranty` is created in `ACTIVE` status with its
        `holder_name` set to the lead's `customer_name`, its `covered_pier_count` copied
        from the job's `piers_installed`, and its `activated_at` set to the current logical
        clock"

        Design: Difficulty/transitive_cascade/install_complete_warranty_visit_leadcounter_depth3
        """
        ctx = setup_completed_install(soil_class="STABLE", pier_count=8, piers_installed=8)
        assert ctx["warranty"] is not None, "warranty should be created on install complete"
        assert ctx["warranty"]["status"] == "ACTIVE", ctx["warranty"]

    def test_warranty_activation_books_visit_and_bumps_lead_counter(self, api):
        """PRD §3.6: "second, activating that warranty books the warranty's first
        `MaintenanceVisit` in `SCHEDULED` status, dated at `activated_at` plus
        `VISIT_INTERVAL_DAYS` (365 days); third, creating that visit increments the owning
        lead's `active_visit_count` by one."

        Design: Difficulty/transitive_cascade/install_complete_warranty_visit_leadcounter_depth3
        """
        ctx = setup_completed_install(soil_class="STABLE", pier_count=8, piers_installed=8)
        visits = get_success_data(
            api.list_visits(OPS, params={"warranty_id": ctx["warranty"]["id"]})
        )
        scheduled = [v for v in visits if v["status"] == "SCHEDULED"]
        assert len(scheduled) == 1, visits
        lead = validate_success(api.get_lead(ctx["lead"]["id"], OPS), 200)
        assert lead["active_visit_count"] == 1, lead


class TestClaimApprovalCascade:
    def test_approve_creates_remediation_job(self, api):
        """PRD §3.8: "it creates a remediation `Job` with a null `quote_id`, its
        `source_claim_id` set to this claim, its `lead_id` copied from the warranty's
        `lead_id`, and `fulfillment_status` of `UNSCHEDULED`" ... "the claim's
        `remediation_job_id` is set to point at the new job."

        Design: Difficulty/transitive_cascade/claim_approve_remediation_warrantycount_depth2
        """
        ctx = setup_approved_claim(reported_settlement_inches=1.0)
        assert ctx["claim"]["remediation_job_id"] is not None, ctx["claim"]

    def test_approve_increments_warranty_remediation_count(self, api):
        """PRD §3.8: "creating that job increments the warranty's `remediation_count` by
        one"

        Design: Difficulty/transitive_cascade/claim_approve_remediation_warrantycount_depth2
        """
        ctx = setup_approved_claim(reported_settlement_inches=1.0)
        warranty = validate_success(api.get_warranty(ctx["warranty"]["id"], OPS), 200)
        assert warranty["remediation_count"] == 1, warranty


class TestWarrantyAndClaimActions:
    def test_transfer_updates_holder_and_count_keeps_active(self, api):
        """PRD §3.7: "the transfer keeps the warranty in `ACTIVE` (an `ACTIVE`-to-`ACTIVE`
        self-transition), sets `holder_name` to the supplied `new_holder_name`, and
        increments `transfer_count` by one."

        Design: Corner/endpoints/warranty_transfer_increments_count
        """
        ctx = setup_completed_install()
        headers = make_customer_headers(ctx["lead"]["id"])
        transferred = validate_success(
            api.transfer_warranty(ctx["warranty"]["id"], {"new_holder_name": "New Owner"},
                                  headers),
            200,
        )
        assert transferred["holder_name"] == "New Owner", transferred
        assert transferred["transfer_count"] == 1, transferred
        assert transferred["status"] == "ACTIVE", transferred

    def test_needs_info_then_resubmit_returns_under_review(self, api):
        """PRD §3.8: "the adjuster requests more information, moving it from `UNDER_REVIEW`
        to `NEEDS_INFO`, and a `Customer` resubmits, moving it from `NEEDS_INFO` back to
        `UNDER_REVIEW`."

        Design: Corner/state_machines/claim_needs_info_resubmit_returns_under_review
        """
        ctx = setup_claim_under_review(reported_settlement_inches=1.0)
        validate_success(api.request_info_claim(ctx["claim"]["id"], ADJUSTER), 200)
        headers = make_customer_headers(ctx["lead"]["id"])
        resubmitted = validate_success(api.resubmit_claim(ctx["claim"]["id"], headers), 200)
        assert resubmitted["status"] == "UNDER_REVIEW", resubmitted

    def test_approve_from_filed_returns_invalid_state(self, api):
        """PRD §3.8: "Any of these transitions attempted from an illegal source state is an
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_approve_from_filed_returns_invalid_state
        """
        ctx = setup_completed_install()
        headers = make_customer_headers(ctx["lead"]["id"])
        claim = get_success_data(
            api.create_claim(create_claim_payload(ctx["warranty"]["id"]), headers)
        )
        # Claim is FILED (review skipped); approve requires UNDER_REVIEW.
        res = api.approve_claim(claim["id"], ADJUSTER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
