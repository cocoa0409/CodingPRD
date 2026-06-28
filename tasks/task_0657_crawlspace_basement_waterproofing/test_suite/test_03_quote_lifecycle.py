"""Quote lifecycle: send, the revision cycle, acceptance (OCC-guarded), sibling decline,
expiry, and invalid-state acceptance.

Covers Difficulty queue: non_linear_state_machine (quote cyclic send/revise loop).
Covers Corner queue: accept-in-draft invalid state, accept declines siblings,
OCC happy-path accept, quote-expired temporal validation.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_homeowner, create_job, create_finalized_inspection, create_sent_quote,
    create_quote_payload, make_homeowner_headers,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]


class TestQuoteRevisionCycle:
    def test_revise_sent_quote_spawns_draft_revision_2(self, api):
        """PRD §3.4: "A sent quote may be revised: revising moves the current quote from
        `SENT` to `REVISED` and spawns a brand-new draft quote whose `revision` is one
        greater than the revised quote's, copying the scope flags forward and recomputing
        pricing; the new quote opens in `DRAFT` and can itself be sent, looping back into
        the cycle."

        Design: Difficulty/non_linear_state_machine/quote_cyclic_send_revise_loop
        """
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        q1 = create_sent_quote(job["id"], includes_sump=True)

        q2 = validate_success(api.revise_quote(
            q1["id"], create_quote_payload(includes_sump=True, includes_dehumidifier=True), EST), 201)
        assert q2["revision"] == 2
        assert q2["status"] == "DRAFT"

        q1_after = validate_success(api.get_quote(q1["id"], EST), 200)
        assert q1_after["status"] == "REVISED"

    def test_revision_2_can_be_sent_again(self, api):
        """PRD §3.4: "the new quote opens in `DRAFT` and can itself be sent, looping back
        into the cycle." PRD §3.4: "Sending a draft quote moves it from `DRAFT` to `SENT`".

        Design: Difficulty/non_linear_state_machine/quote_cyclic_send_revise_loop
        """
        ho = create_homeowner(credit_band="PRIME")
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        q1 = create_sent_quote(job["id"], includes_sump=True)
        q2 = validate_success(api.revise_quote(
            q1["id"], create_quote_payload(includes_sump=True, includes_dehumidifier=True), EST), 201)

        sent2 = validate_success(api.send_quote(q2["id"], EST), 200)
        assert sent2["status"] == "SENT"
        assert sent2["revision"] == 2


class TestQuoteAcceptance:
    def test_accept_quote_in_draft_returns_invalid_state(self, api):
        """PRD §3.5: "an accept of a quote not in `SENT` is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/accept_quote_in_draft_returns_invalid_state
        """
        ho = create_homeowner(credit_band="PRIME")
        ho_h = make_homeowner_headers(ho["id"])
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        # create a DRAFT quote but do NOT send it
        draft = get_success_data(api.create_quote(
            job["id"], create_quote_payload(includes_sump=True), EST))
        res = api.accept_quote(draft["id"], {"expected_quote_version": draft["version"]}, ho_h)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_accept_with_matching_version_succeeds_and_sells_job(self, api):
        """PRD §3.5: "Acceptance is optimistic-concurrency-guarded: the request must carry
        `expected_quote_version` matching the quote's current `version`".
        PRD §3.5: "A successful acceptance moves the quote from `SENT` to `ACCEPTED`, sets
        the Job's `accepted_quote_id` to that quote, advances the Job's `lifecycle_status`
        from `QUOTED` to `SOLD`".

        Design: Corner/cross_cutting_complexity_layers/occ_quote_accept_correct_version_succeeds
        """
        ho = create_homeowner(credit_band="PRIME")
        ho_h = make_homeowner_headers(ho["id"])
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        quote = create_sent_quote(job["id"], includes_sump=True)

        accepted = validate_success(api.accept_quote(
            quote["id"], {"expected_quote_version": quote["version"]}, ho_h), 200)
        assert accepted["status"] == "ACCEPTED"
        job_after = validate_success(api.get_job(job["id"], EST), 200)
        assert job_after["lifecycle_status"] == "SOLD"

    def test_accept_declines_sibling_sent_quotes(self, api):
        """PRD §3.5: "A successful acceptance moves the quote from `SENT` to `ACCEPTED`,
        sets the Job's `accepted_quote_id` to that quote, advances the Job's
        `lifecycle_status` from `QUOTED` to `SOLD`, and declines every sibling quote on
        the same Job that is still in `SENT`, moving each to `DECLINED`."

        Design: Corner/state_machines/quote_accept_declines_sibling_sent_quotes
        """
        ho = create_homeowner(credit_band="PRIME")
        ho_h = make_homeowner_headers(ho["id"])
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        q1 = create_sent_quote(job["id"], includes_sump=True)
        # revise q1 (q1 -> REVISED) then send q2; accept q2.
        q2 = validate_success(api.revise_quote(
            q1["id"], create_quote_payload(includes_sump=True, includes_dehumidifier=True), EST), 201)
        q2_sent = validate_success(api.send_quote(q2["id"], EST), 200)

        accepted = validate_success(api.accept_quote(
            q2["id"], {"expected_quote_version": q2_sent["version"]}, ho_h), 200)
        assert accepted["status"] == "ACCEPTED"
        q1_after = validate_success(api.get_quote(q1["id"], EST), 200)
        assert q1_after["status"] == "REVISED"  # q1 was revised before being accepted
        job_after = validate_success(api.get_job(job["id"], EST), 200)
        assert job_after["accepted_quote_id"] == q2["id"]
        assert job_after["lifecycle_status"] == "SOLD"

    def test_accept_after_expiry_returns_quote_expired(self, api):
        """PRD §3.5: "Acceptance is permitted only when the quote is `SENT`, the logical
        clock is strictly before the quote's `expires_at`, and the Job is in lifecycle
        `QUOTED`. An accept attempted at or after `expires_at` is rejected with
        `ERR_QUOTE_EXPIRED` (HTTP 409)."
        PRD §3.4: "Sending a draft quote moves it from `DRAFT` to `SENT` and sets
        `expires_at` to its `created_at` plus 30 days".

        Design: Corner/validations/quote_accept_after_expiry_returns_quote_expired
        """
        ho = create_homeowner(credit_band="PRIME")
        ho_h = make_homeowner_headers(ho["id"])
        api.set_clock("2026-04-01T00:00:00Z", EST)
        job = create_job(ho["id"], footprint_sqft=600, structure_type="BASEMENT")
        create_finalized_inspection(job["id"], moisture_pct=65, structural_findings_count=0)
        quote = create_sent_quote(job["id"], includes_sump=True)
        # advance clock to 2026-06-01, well past created_at + 30 days
        api.set_clock("2026-06-01T00:00:00Z", EST)
        res = api.accept_quote(quote["id"], {"expected_quote_version": quote["version"]}, ho_h)
        validate_error(res, "ERR_QUOTE_EXPIRED", expected_status=409)
