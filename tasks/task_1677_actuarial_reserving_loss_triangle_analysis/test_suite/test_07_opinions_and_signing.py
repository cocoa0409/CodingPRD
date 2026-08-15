"""Statement of actuarial opinion: attachment gates, signing checks in tier
order (segregation of duties, attachment minimum, filing deadline), the
signing side effects, and the SIGNED terminal state (PRD §2.10, §3.7, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    create_opinion,
    create_study,
    make_actuarial_analyst_headers,
    make_appointed_actuary_headers,
    set_logical_clock,
    setup_approved_study_with_attached_opinion,
    setup_main_book_with_run,
    setup_minimal_book_study,
    sign_opinion_as,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAttachmentGate:
    def test_opinion_attach_gated_on_study_approved(self, api, appointed_actuary_headers):
        """PRD §3.8: "Attachment is possible only while the opinion is in
        `DRAFT`, requires the study to be `APPROVED` (a study in any other
        status is refused with `ERR_STUDY_NOT_APPROVED`), and requires the
        study to be unattached — a study already carrying an opinion is refused
        with `ERR_STUDY_ATTACHED`."

        Design: Difficulty/cross_entity_state_dependency/opinion_attach_gated_on_study_approved
        """
        ctx = setup_main_book_with_run(include_claim_d=False)
        study = create_study(ctx["segment"]["id"], "2025-Q3", "CHAIN_LADDER", "PAID")
        set_logical_clock("2025-10-15T00:00:00Z")
        opinion = create_opinion(statement_date="2025-09-30", actuary_user_id="aa-1")

        resp = api.attach_study(
            opinion["id"], {"study_id": study["id"]}, appointed_actuary_headers
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_APPROVED)

    def test_opinion_attach_rejection_leaves_study_unattached(
        self, api, appointed_actuary_headers, actuarial_analyst_headers
    ):
        """PRD §3.8: "the actuary attaches a study by its `study_id`, which
        sets the study's `opinion_id` to this opinion."

        Design: Difficulty/cross_entity_state_dependency/opinion_attach_gated_on_study_approved
        """
        ctx = setup_main_book_with_run(include_claim_d=False)
        study = create_study(ctx["segment"]["id"], "2025-Q3", "CHAIN_LADDER", "PAID")
        set_logical_clock("2025-10-15T00:00:00Z")
        opinion = create_opinion(statement_date="2025-09-30", actuary_user_id="aa-1")

        resp = api.attach_study(
            opinion["id"], {"study_id": study["id"]}, appointed_actuary_headers
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_APPROVED)

        data = validate_success(api.get_study(study["id"], actuarial_analyst_headers))
        assert data["opinion_id"] is None, (
            "a refused attachment must not set the study's opinion_id"
        )
        assert data["status"] == "DRAFT"


class TestSigningChecks:
    def test_sign_sod_precedes_no_studies_referential(
        self, api, appointed_actuary_headers
    ):
        """PRD §3.8: "Signature moves the opinion from `DRAFT` to its terminal
        `SIGNED` state and applies its checks in their tier order. Segregation
        of duties comes first: the signer must differ from the opinion's
        drafter and from the creator and the most recent reviewer of every
        attached study, else `ERR_SOD_SIGNER_CONFLICT`. The attachment checks
        follow: at least one study must be attached, else
        `ERR_OPINION_NO_STUDIES`, and every attached study must be `APPROVED`,
        else `ERR_STUDY_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/sign_sod_precedes_no_studies_referential
        """
        set_logical_clock("2025-10-15T00:00:00Z")
        opinion = create_opinion(statement_date="2025-09-30", actuary_user_id="aa-1")

        # Signed by the drafter while zero studies are attached: the
        # segregation-of-duties check fires before the attachment minimum.
        resp = api.sign_opinion(opinion["id"], appointed_actuary_headers)
        validate_error(resp, ApiErrorId.ERR_SOD_SIGNER_CONFLICT)

    def test_sign_sod_conflict_leaves_opinion_draft(
        self, api, appointed_actuary_headers
    ):
        """PRD §2.10: "signing is rejected with `ERR_SOD_SIGNER_CONFLICT` (403)
        when the signer's `X-User-ID` equals the opinion's
        `created_by_user_id`, or equals the `created_by_user_id` or
        `reviewed_by_user_id` of any study attached to the opinion."

        Design: Difficulty/priority_pair_validation_conflict/sign_sod_precedes_no_studies_referential
        """
        set_logical_clock("2025-10-15T00:00:00Z")
        opinion = create_opinion(statement_date="2025-09-30", actuary_user_id="aa-1")

        resp = api.sign_opinion(opinion["id"], appointed_actuary_headers)
        validate_error(resp, ApiErrorId.ERR_SOD_SIGNER_CONFLICT)

        data = validate_success(api.get_opinion(opinion["id"], appointed_actuary_headers))
        assert data["status"] == "DRAFT", "a rejected signature changes nothing"
        assert data["signed_by_user_id"] is None

    def test_sign_opinion_without_studies_rejected(self, api):
        """PRD §3.8: "The attachment checks follow: at least one study must be
        attached, else `ERR_OPINION_NO_STUDIES`, and every attached study must
        be `APPROVED`, else `ERR_STUDY_NOT_APPROVED`."

        Design: Corner/validations/sign_opinion_without_studies_rejected
        """
        set_logical_clock("2025-10-15T00:00:00Z")
        opinion = create_opinion(statement_date="2025-09-30", actuary_user_id="aa-1")

        # A clean, non-conflicting signer still cannot sign an empty opinion.
        resp = api.sign_opinion(
            opinion["id"], make_appointed_actuary_headers("aa-2")
        )
        validate_error(resp, ApiErrorId.ERR_OPINION_NO_STUDIES)

    def test_sign_after_filing_deadline_rejected(self, api):
        """PRD §3.8: "The draft starts in `DRAFT`, records its drafter in
        `created_by_user_id`, and immediately fixes its `filing_deadline_date`
        as the calendar date sixty days after the statement date."
        PRD §3.8: "The temporal check comes last: the logical clock's date must
        be on or before the `filing_deadline_date`, and signing after the
        deadline is refused with `ERR_FILING_DEADLINE_PASSED`."

        Design: Corner/validations/sign_after_filing_deadline_rejected
        """
        ctx = setup_approved_study_with_attached_opinion(
            book="minimal", statement_date="2025-09-30", actuary_user_id="aa-1"
        )
        opinion = validate_success(
            api.get_opinion(ctx["opinion"]["id"], make_appointed_actuary_headers("aa-1"))
        )
        assert opinion["filing_deadline_date"] == "2025-11-29", (
            "statement_date 2025-09-30 plus sixty calendar days"
        )

        set_logical_clock("2025-12-01T00:00:00Z")
        resp = api.sign_opinion(
            ctx["opinion"]["id"], make_appointed_actuary_headers("aa-2")
        )
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED)


class TestSigningSideEffects:
    def test_opinion_sign_locks_attached_studies(self, api, appointed_actuary_headers):
        """PRD §3.8: "A successful signature records `signed_by_user_id`,
        stamps `signed_at` from the current logical clock, and moves every
        attached study from `APPROVED` to `LOCKED`, rendering it immutable."

        Design: Corner/endpoints/opinion_sign_locks_attached_studies
        """
        ctx = setup_approved_study_with_attached_opinion(
            book="minimal", statement_date="2025-09-30", actuary_user_id="aa-1"
        )
        set_logical_clock("2025-10-15T00:00:00Z")
        resp = api.sign_opinion(
            ctx["opinion"]["id"], make_appointed_actuary_headers("aa-2")
        )
        data = validate_success(resp, 200)
        assert data["status"] == "SIGNED"
        assert data["signed_by_user_id"] == "aa-2"
        assert isinstance(data["signed_at"], str) and data["signed_at"].startswith(
            "2025-10-15T00:00:00"
        ), "signed_at is stamped from the logical clock"

        study = validate_success(
            api.get_study(ctx["study"]["id"], make_actuarial_analyst_headers("analyst-1"))
        )
        assert study["status"] == "LOCKED", "signing locks every attached study"

    def test_opinion_sign_twice_returns_invalid_state(self, api):
        """PRD §3.8: "Signing an opinion that is not in `DRAFT` is refused with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/opinion_sign_twice_returns_invalid_state
        """
        ctx = setup_approved_study_with_attached_opinion(
            book="main", statement_date="2025-09-30", actuary_user_id="aa-1"
        )
        set_logical_clock("2025-10-15T00:00:00Z")
        first = sign_opinion_as(ctx["opinion"]["id"], "aa-2")
        assert first["status"] == "SIGNED"

        # A second sign, even by a fresh non-conflicting actuary, is refused.
        resp = api.sign_opinion(
            ctx["opinion"]["id"], make_appointed_actuary_headers("aa-3")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(
            api.get_opinion(
                ctx["opinion"]["id"], make_appointed_actuary_headers("aa-1")
            )
        )
        assert data["signed_by_user_id"] == "aa-2", (
            "the rejected second signature must not overwrite the signer"
        )


class TestGovernanceLocks:
    def test_withdraw_of_attached_approved_study_rejected(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.7: "Withdrawal moves a study to the terminal `WITHDRAWN`
        state from `DRAFT`, `IN_REVIEW`, or `APPROVED`; withdrawing an
        `APPROVED` study is allowed only while it is unattached — a study whose
        `opinion_id` is set is refused with `ERR_STUDY_ATTACHED` — and
        withdrawal clears `opinion_id` when it is set, a situation reachable
        only for non-approved studies since approved ones must be unattached to
        withdraw."

        Design: Corner/validations/withdraw_of_attached_approved_study_rejected
        """
        ctx = setup_approved_study_with_attached_opinion(
            book="minimal", statement_date="2025-03-31", actuary_user_id="aa-1"
        )
        resp = api.withdraw_study(ctx["study"]["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_STUDY_ATTACHED)

        study = validate_success(
            api.get_study(ctx["study"]["id"], actuarial_analyst_headers)
        )
        assert study["status"] == "APPROVED"

    def test_pattern_withdraw_blocked_by_approved_study(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "A `SELECTED` pattern withdraws only while no `APPROVED`
        or `LOCKED` study of the same segment has a valuation quarter inside
        the pattern's window; otherwise the withdrawal is refused with
        `ERR_PATTERN_IN_USE`."

        Design: Corner/validations/pattern_withdraw_blocked_by_approved_study
        """
        ctx = setup_minimal_book_study(status="APPROVED")  # study at 2025-Q1
        resp = api.withdraw_development_pattern(
            ctx["pattern"]["id"], actuarial_analyst_headers
        )
        validate_error(resp, ApiErrorId.ERR_PATTERN_IN_USE)

        pattern = validate_success(
            api.get_development_pattern(ctx["pattern"]["id"], actuarial_analyst_headers)
        )
        assert pattern["status"] == "SELECTED"

    def test_studies_filtered_list_by_opinion_id(self, api, appointed_actuary_headers):
        """PRD §3.7: "Studies can be read individually or listed with
        `segment_id`, `opinion_id`, `status`, and `valuation_quarter` filters."
        PRD §3.8: "the actuary attaches a study by its `study_id`, which sets
        the study's `opinion_id` to this opinion."

        Design: Corner/endpoints/studies_filtered_list_by_opinion_id
        """
        ctx = setup_approved_study_with_attached_opinion(
            book="minimal", statement_date="2025-03-31", actuary_user_id="aa-1"
        )
        data, meta = validate_paginated(
            api.list_studies(
                appointed_actuary_headers,
                params={"opinion_id": ctx["opinion"]["id"]},
            )
        )
        assert len(data) == 1, "exactly the attached study is reachable by opinion_id"
        assert data[0]["id"] == ctx["study"]["id"]
