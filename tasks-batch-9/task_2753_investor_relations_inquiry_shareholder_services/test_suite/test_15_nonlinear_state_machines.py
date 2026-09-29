"""Non-linear state machines: the draft revision cycle and the contact's two dimensions.

Neither machine is a forward-only pipeline. A ResponseDraft walks
DRAFT -> IN_REVIEW -> CHANGES_REQUESTED -> DRAFT on the same row while dragging
its parent inquiry backwards, and a Contact carries two independent dimensions —
model access and threat level — that never gate each other.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    COVERAGE_INITIATED,
    DECISION_REQUEST_CHANGES,
    DISCLOSURE_OFFICER,
    DISCLOSURE_OFFICER_USER_ID,
    DRAFT_CHANGES_REQUESTED,
    DRAFT_DRAFT,
    INQUIRY_DRAFTING,
    IR_ANALYST,
    MODEL_ACCESS_GRANTED,
    MODEL_ACCESS_REVOKED,
    POSTURE_OPEN,
    QUEUE_IR_DESK,
    SERVICING_REVOKE_MODEL_ACCESS,
    THREAT_CRITICAL,
    THREAT_NONE,
    TOPIC_OTHER,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local composite setup for the revision cycle
# ---------------------------------------------------------------------------


def _build_review_cycle_world(api: ApiClient):
    """One IR_DESK inquiry whose only draft is sitting IN_REVIEW.

    The clock is pinned at 2026-08-10T09:00:00Z so that every recomputed
    ``sla_due_at`` is 72 hours later, at 2026-08-13T09:00:00.000Z.
    """
    fixtures.set_clock(api, "2026-08-10T09:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="CYC",
        legal_name="Cycle Holdings Inc",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        30000,
        display_name="Cycle Holder",
        email="cyc@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_OTHER,
        subject="Where can I find the latest fact sheet?",
        headers=IR_ANALYST,
    )
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="The fact sheet is on the IR website.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
        headers=IR_ANALYST,
    )
    draft = fixtures.submit_for_review(api, draft["id"], IR_ANALYST)
    return {
        "company": company,
        "inquiry_id": inquiry["id"],
        "draft_id": draft["id"],
    }


def _request_changes(api: ApiClient, world, note: str):
    return fixtures.decide_review(
        api,
        world["draft_id"],
        world["inquiry_id"],
        decision=DECISION_REQUEST_CHANGES,
        reviewer_note=note,
        headers=DISCLOSURE_OFFICER,
    )


class TestResponseDraftRevisionCycle:
    """CHANGES_REQUESTED and the return to DRAFT on the same row."""

    def test_request_changes_rewinds_the_inquiry_and_stores_the_reviewer_note(
        self, api: ApiClient
    ):
        """PRD §3.6: "The branch moves the draft `IN_REVIEW` → `CHANGES_REQUESTED`, stores the supplied note as `reviewer_note`, and rewinds the parent inquiry `AWAITING_APPROVAL` → `DRAFTING` with `sla_due_at` recomputed from the logical clock and the inquiry's current queue allowance."

        PRD §3.6: "Both branches stamp the acting user as `reviewer_user_id` and increment both the draft's `version` and the parent inquiry's `version` by 1."

        PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."

        Design: Difficulty/non_linear_state_machine/response_draft_revision_cycle_returns_to_draft
        """
        world = _build_review_cycle_world(api)

        decided = _request_changes(
            api, world, "Cite the published fact sheet explicitly."
        )
        assertions.assert_response_draft(
            decided,
            status=DRAFT_CHANGES_REQUESTED,
            reviewer_note="Cite the published fact sheet explicitly.",
            reviewer_user_id=DISCLOSURE_OFFICER_USER_ID,
            pinned_disclosure_version=None,
            revision_round=1,
            version=3,
        )

        inquiry = fixtures.read_inquiry(api, world["inquiry_id"])
        assertions.assert_inquiry(
            inquiry,
            status=INQUIRY_DRAFTING,
            routing_queue=QUEUE_IR_DESK,
            version=5,
        )
        assertions.assert_ts_equals(
            inquiry["sla_due_at"], "2026-08-13T09:00:00.000Z", "sla_due_at"
        )

    def test_revise_returns_the_row_to_draft_and_clears_the_review_fields(
        self, api: ApiClient
    ):
        """PRD §3.6: "Revising is the author's station on the way back round, and it closes the `DRAFT` → `IN_REVIEW` → `CHANGES_REQUESTED` → `DRAFT` cycle."

        PRD §3.6: "A permitted revision returns the draft to `DRAFT`, increases `revision_round` by 1, clears `blocked_reason` back to null, clears `reviewer_note` back to null, clears `pinned_disclosure_version` back to null, and replaces `body_text`, `disclosure_class` and `cited_disclosure_id` with whichever of those three the author supplied, leaving the others as they were."

        PRD §3.6: "The parent inquiry remains in `DRAFTING` throughout — revision touches only the draft's own `version`."

        Design: Difficulty/non_linear_state_machine/response_draft_revision_cycle_returns_to_draft
        """
        world = _build_review_cycle_world(api)
        _request_changes(api, world, "Cite the published fact sheet explicitly.")

        revised = fixtures.revise_draft(
            api,
            world["draft_id"],
            body_text="The fact sheet is on the IR website, see the 2026-08 posting.",
            headers=IR_ANALYST,
        )
        assertions.assert_response_draft(
            revised,
            status=DRAFT_DRAFT,
            revision_round=2,
            reviewer_note=None,
            blocked_reason=None,
            pinned_disclosure_version=None,
            body_text="The fact sheet is on the IR website, see the 2026-08 posting.",
            disclosure_class=CLASS_PUBLIC_DOMAIN,
            version=4,
        )

        inquiry = fixtures.read_inquiry(api, world["inquiry_id"])
        assertions.assert_inquiry(inquiry, status=INQUIRY_DRAFTING, version=5)

    def test_the_cycle_is_bounded_at_revision_round_three(self, api: ApiClient):
        """PRD §3.6: "The cycle is bounded: a revision is refused with `ERR_REVISION_LIMIT_REACHED` once `revision_round` has already reached 3, so a draft that has consumed all three authoring rounds is dead and the inquiry needs a fresh draft instead."

        PRD §3.6: "A permitted revision returns the draft to `DRAFT`, increases `revision_round` by 1, clears `blocked_reason` back to null, clears `reviewer_note` back to null, clears `pinned_disclosure_version` back to null, and replaces `body_text`, `disclosure_class` and `cited_disclosure_id` with whichever of those three the author supplied, leaving the others as they were."

        Design: Difficulty/non_linear_state_machine/response_draft_revision_cycle_returns_to_draft
        """
        world = _build_review_cycle_world(api)

        _request_changes(api, world, "First pass: cite the posting.")
        second_round = fixtures.revise_draft(
            api, world["draft_id"], body_text="Second attempt.", headers=IR_ANALYST
        )
        assert second_round["revision_round"] == 2

        fixtures.submit_for_review(api, world["draft_id"], IR_ANALYST)
        _request_changes(api, world, "Second pass: tighten the wording.")
        third_round = fixtures.revise_draft(
            api, world["draft_id"], body_text="Third attempt.", headers=IR_ANALYST
        )
        assert third_round["revision_round"] == 3

        fixtures.submit_for_review(api, world["draft_id"], IR_ANALYST)
        _request_changes(api, world, "Third pass: still not publishable.")

        refused = api.revise_draft(
            world["draft_id"],
            factories.revise_payload(body_text="Fourth attempt."),
            IR_ANALYST,
        )
        validate_error(refused, ApiErrorId.REVISION_LIMIT_REACHED.value)

        dead = fixtures.read_draft(api, world["draft_id"])
        assertions.assert_response_draft(
            dead, status=DRAFT_CHANGES_REQUESTED, revision_round=3
        )
        assert dead["body_text"] == "Third attempt."


# ---------------------------------------------------------------------------
# Local composite setup for the two-dimensional contact
# ---------------------------------------------------------------------------


def _build_parallel_dimension_world(api: ApiClient):
    """An issuer with no blackout window and one non-activist covering analyst."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="PAR",
        legal_name="Parallel Dimensions Corp",
        shares_outstanding=1000000,
    )
    analyst = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Parallel Analyst",
        email="par@banks.test",
        nda_on_file=True,
        coverage_status=COVERAGE_INITIATED,
    )
    return company, analyst


def _revoke_model_access(api: ApiClient, contact_id: str):
    return validate_success(
        api.servicing(
            contact_id,
            factories.servicing_payload(SERVICING_REVOKE_MODEL_ACCESS),
            DISCLOSURE_OFFICER,
        )
    )


class TestContactParallelDimensions:
    """model_access_status and threat_level move independently on one row."""

    def test_granting_model_access_moves_only_the_access_dimension(self, api: ApiClient):
        """PRD §3.3: "Granting model access moves `model_access_status` from `NONE` to `GRANTED`, and equally from `REVOKED` back to `GRANTED` — the re-grant closing a `GRANTED` → `REVOKED` → `GRANTED` cycle on that dimension."

        PRD §3.3: "A successful grant increments the contact's `version` by 1 and touches nothing else."

        PRD §3.2: "Three fields are seeded by the system and cannot be supplied at creation: `model_access_status` starts at `NONE`, `threat_level` starts at `NONE`, and `dividend_received_cents` starts at 0."

        Design: Difficulty/non_linear_state_machine/contact_parallel_model_access_and_threat_dimensions
        """
        company, analyst = _build_parallel_dimension_world(api)
        assertions.assert_contact(
            analyst,
            model_access_status="NONE",
            threat_level=THREAT_NONE,
            dividend_received_cents=0,
            version=1,
        )

        granted = fixtures.grant_model_access(api, analyst["id"], DISCLOSURE_OFFICER)
        assertions.assert_contact(
            granted,
            model_access_status=MODEL_ACCESS_GRANTED,
            threat_level=THREAT_NONE,
            version=2,
        )
        # The grant touches nothing else, so the issuer row has not moved.
        assertions.assert_company(
            fixtures.read_company(api, company["id"]),
            disclosure_posture=POSTURE_OPEN,
            version=1,
        )

    def test_setting_a_threat_level_moves_only_the_threat_dimension(self, api: ApiClient):
        """PRD §3.3: "Any threat level may be set from any other, in either direction, and this is the only mechanism by which a threat level can be lowered."

        PRD §3.3: "The first stores the supplied value and increments the contact's `version` by 1."

        PRD §3.3: "The second, caused by the first, re-derives the issuer's `disclosure_posture` per §2.7, stamps `posture_recomputed_at`, and increments the issuer's `version` by 1."

        PRD §2.7: "The second source is activist pressure, read from the `threat_level` of every contact of that issuer whose `activist_flag` is true; the threat level of a contact that is not flagged as an activist is ignored entirely."

        Design: Difficulty/non_linear_state_machine/contact_parallel_model_access_and_threat_dimensions
        """
        company, analyst = _build_parallel_dimension_world(api)
        fixtures.grant_model_access(api, analyst["id"], DISCLOSURE_OFFICER)

        escalated = fixtures.set_threat_level(
            api, analyst["id"], THREAT_CRITICAL, DISCLOSURE_OFFICER
        )
        assertions.assert_contact(
            escalated,
            threat_level=THREAT_CRITICAL,
            model_access_status=MODEL_ACCESS_GRANTED,
            activist_flag=False,
            version=3,
        )

        issuer = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            issuer, disclosure_posture=POSTURE_OPEN, version=2
        )
        assertions.assert_ts_equals(
            issuer["posture_recomputed_at"],
            "2026-08-01T00:00:00.000Z",
            "posture_recomputed_at",
        )

    def test_the_access_dimension_completes_a_revoke_and_regrant_cycle_at_critical(
        self, api: ApiClient
    ):
        """PRD §3.3: "The two dimensions are genuinely independent and never gate each other: an analyst whose access is `REVOKED` can still be escalated to `CRITICAL`, and a contact already at `CRITICAL` can still be granted model access."

        PRD §3.3: "Revoking model access moves `model_access_status` from `GRANTED` to `REVOKED` and requires the current value to be exactly `GRANTED`; revoking an access that was never granted, or revoking twice, is refused with `ERR_MODEL_ACCESS_NOT_ELIGIBLE`."

        PRD §3.3: "A successful revocation increments the contact's `version` by 1."

        Design: Difficulty/non_linear_state_machine/contact_parallel_model_access_and_threat_dimensions
        """
        company, analyst = _build_parallel_dimension_world(api)
        fixtures.grant_model_access(api, analyst["id"], DISCLOSURE_OFFICER)
        fixtures.set_threat_level(
            api, analyst["id"], THREAT_CRITICAL, DISCLOSURE_OFFICER
        )

        revoked = _revoke_model_access(api, analyst["id"])
        assertions.assert_contact(
            revoked,
            model_access_status=MODEL_ACCESS_REVOKED,
            threat_level=THREAT_CRITICAL,
            version=4,
        )

        regranted = fixtures.grant_model_access(api, analyst["id"], DISCLOSURE_OFFICER)
        assertions.assert_contact(
            regranted,
            model_access_status=MODEL_ACCESS_GRANTED,
            threat_level=THREAT_CRITICAL,
            version=5,
        )
        assertions.assert_company(
            fixtures.read_company(api, company["id"]),
            disclosure_posture=POSTURE_OPEN,
        )
