"""Quote revision loop, Job's two independent state dimensions, and related transitions
(PRD §3.3, §3.4, §3.5, §2.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_sent_quote,
    setup_draft_quote,
    setup_accepted_job,
    approve_permit_for_job,
    make_customer_headers,
    api_client,
    SALES,
    OPS,
    ApiErrorId,
)


class TestQuoteRevisionCycle:
    def test_revise_moves_sent_to_revised(self, api):
        """PRD §3.3: "revising it transitions it from `SENT` to `REVISED`, optionally
        updating the `financing_plan`, and leaves its pricing stale until it is sent again."

        Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_revised_sent
        """
        ctx = setup_sent_quote(financing_plan="CASH")
        revised = validate_success(
            api.revise_quote(ctx["quote"]["id"], {"financing_plan": "PLAN_12"}, SALES), 200
        )
        assert revised["status"] == "REVISED", revised

    def test_resend_returns_revised_to_sent(self, api):
        """PRD §3.3: "Sending the quote transitions it from `DRAFT` to `SENT` (and re-sending
        a revised quote transitions it from `REVISED` back to `SENT`)"

        Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_revised_sent
        """
        ctx = setup_sent_quote(financing_plan="CASH")
        api.revise_quote(ctx["quote"]["id"], {"financing_plan": "PLAN_12"}, SALES)
        resent = validate_success(api.send_quote(ctx["quote"]["id"], SALES), 200)
        assert resent["status"] == "SENT", resent


class TestJobParallelDimensions:
    def test_permit_dimension_advances_to_approved(self, api):
        """PRD §2.8: "Opening a permit sets the parent job's `permit_status` to `PENDING`,
        and deciding the permit bubbles the decision up onto the job's `permit_status`."

        Design: Difficulty/non_linear_state_machine/job_parallel_permit_vs_fulfillment
        """
        ctx = setup_accepted_job(financing_plan="CASH")
        approve_permit_for_job(ctx["job"]["id"])
        job = validate_success(api.get_job(ctx["job"]["id"], OPS), 200)
        assert job["permit_status"] == "APPROVED", job

    def test_fulfillment_dimension_stays_unscheduled(self, api):
        """PRD §3.5: "The two dimensions advance without ordering constraints between them,
        except that scheduling reads `permit_status`."

        Design: Difficulty/non_linear_state_machine/job_parallel_permit_vs_fulfillment
        """
        ctx = setup_accepted_job(financing_plan="CASH")
        approve_permit_for_job(ctx["job"]["id"])
        job = validate_success(api.get_job(ctx["job"]["id"], OPS), 200)
        # permit_status advanced independently; fulfillment_status untouched.
        assert job["fulfillment_status"] == "UNSCHEDULED", job


class TestInvalidTransitions:
    def test_accept_from_draft_returns_invalid_state(self, api):
        """PRD §3.4: "Attempting any of these transitions from a non-`SENT` state is an
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/quote_accept_from_draft_returns_invalid_state
        """
        ctx = setup_draft_quote(financing_plan="CASH")
        headers = make_customer_headers(ctx["lead"]["id"])
        res = api.accept_quote(ctx["quote"]["id"], headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_from_unscheduled_returns_invalid_state(self, api):
        """PRD §3.5: "Once scheduled, an `OpsCoordinator` starts the install, moving the job
        from `SCHEDULED` to `IN_PROGRESS` with no additional preconditions."
        PRD §2.10: "(6) the legal-state check for the requested transition, yielding
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/job_start_from_unscheduled_returns_invalid_state
        """
        ctx = setup_accepted_job(financing_plan="CASH")
        res = api.start_job(ctx["job"]["id"], OPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestQuoteAndPermitActions:
    def test_reject_sent_quote_sets_rejected(self, api):
        """PRD §3.4: "A `Customer` accepts a sent quote, transitioning it from `SENT` to
        `ACCEPTED`, or rejects it, transitioning it from `SENT` to `REJECTED`."

        Design: Corner/endpoints/quote_reject_sets_rejected
        """
        ctx = setup_sent_quote(financing_plan="CASH")
        headers = make_customer_headers(ctx["lead"]["id"])
        rejected = validate_success(api.reject_quote(ctx["quote"]["id"], headers), 200)
        assert rejected["status"] == "REJECTED", rejected

    def test_permit_reject_bubbles_to_job(self, api):
        """PRD §3.5: "a rejection moves the permit from `PENDING` to `REJECTED` and sets the
        parent job's `permit_status` to `REJECTED`."

        Design: Corner/endpoints/permit_reject_bubbles_to_job
        """
        ctx = setup_accepted_job(financing_plan="CASH")
        permit = get_success_data(
            api.create_permit({"job_id": ctx["job"]["id"], "permit_type": "STANDARD"}, OPS)
        )
        validate_success(api.decide_permit(permit["id"], {"decision": "REJECT"}, OPS), 200)
        job = validate_success(api.get_job(ctx["job"]["id"], OPS), 200)
        assert job["permit_status"] == "REJECTED", job
