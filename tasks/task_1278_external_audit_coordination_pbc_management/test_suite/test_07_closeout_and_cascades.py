"""Closeout chain: cancel cascades, issue-report gates, rep-letter SoD."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    complete_fieldwork,
    create_adjustment,
    create_fee_change,
    create_fieldwork_engagement,
    create_pbc,
    create_rep_letter,
    create_sampling,
    create_submitted_pbc,
    create_visit,
    engagement_version,
    get_adjustment,
    get_engagement,
    get_fee_change,
    get_sampling,
    get_visit,
    is_iso8601_timestamp,
    make_auditor_headers,
    make_controller_headers,
    make_preparer_headers,
    pass_adjustment,
    setup_closing_engagement,
    setup_pending_rep_letter,
    setup_signed_engagement,
    sign_rep_letter,
    upload_evidence,
    validate_error,
    validate_success,
)
from test_helpers.constants import VALID_SHA256_C

CONTROLLER = TEST_USERS["controller_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _get_pbc(pbc_id):
    return validate_success(api_client.get_pbc_request(pbc_id, CONTROLLER))


def _get_upload(upload_id):
    return validate_success(api_client.get_evidence_upload(upload_id,
                                                           CONTROLLER))


def _get_letter(letter_id):
    return validate_success(
        api_client.get_representation_letter(letter_id, CONTROLLER))


class TestCancelCascade:

    def test_cancel_cascades_to_pbc_evidence_and_fee(self):
        """PRD §3.1: "Cancellation lands on `CANCELLED` and cascades through
        every child aggregate: every PBC request not yet in a terminal state
        (`OPEN`, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED`) becomes `FROZEN`;
        every evidence upload still `PENDING_REVIEW` becomes `INVALIDATED`;
        every sampling request in `DRAFT`, `DISPATCHED`, or `IN_PROGRESS`
        becomes `CANCELLED`; every `SCHEDULED` fieldwork visit becomes
        `CANCELLED`; every `PROPOSED` adjustment becomes `REJECTED` with its
        `disposition_rationale` set to `ENGAGEMENT_CANCELLED`; and every
        `PROPOSED` fee change request becomes `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/engagement_cancel_cascades_to_pbc_evidence_fee
        """
        eng, _loc = create_fieldwork_engagement(client_name="EtaCo")
        pbc = create_pbc(eng["id"], owner="prep1", title="In-progress PBC")
        upload = upload_evidence(pbc["id"], eng["id"], owner="prep1",
                                 file_name="doc.pdf", sha256=VALID_SHA256_C)
        fee = create_fee_change(eng["id"], 100_000, proposer="auditor",
                                scope_description="Extra scope")
        resp = api_client.cancel_engagement(eng["id"], CONTROLLER)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert _get_pbc(pbc["id"])["status"] == "FROZEN", (
            "cascade link 1: engagement cancel freezes the open PBC request"
        )
        assert _get_upload(upload["id"])["status"] == "INVALIDATED", (
            "cascade link 2: the still-PENDING_REVIEW upload is invalidated"
        )
        assert get_fee_change(fee["id"])["status"] == "WITHDRAWN", (
            "parallel cascade: the PROPOSED fee change is withdrawn"
        )

    def test_cancel_cascades_to_sampling_visit_and_adjustment(self):
        """PRD §3.1: "every sampling request in `DRAFT`, `DISPATCHED`, or
        `IN_PROGRESS` becomes `CANCELLED`; every `SCHEDULED` fieldwork visit
        becomes `CANCELLED`; every `PROPOSED` adjustment becomes `REJECTED`
        with its `disposition_rationale` set to `ENGAGEMENT_CANCELLED`".

        Design: Difficulty/transitive_cascade/engagement_cancel_cascades_to_pbc_evidence_fee
        """
        eng, loc = create_fieldwork_engagement(client_name="EtaCo")
        sampling = create_sampling(eng["id"], [loc["id"]], title="S1")
        visit = create_visit(eng["id"], loc["id"], auditor_user="aud1")
        adj = create_adjustment(eng["id"], 5_000, description="AdjA")
        resp = api_client.cancel_engagement(eng["id"], CONTROLLER)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert get_sampling(sampling["id"])["status"] == "CANCELLED"
        assert get_visit(visit["id"])["status"] == "CANCELLED"
        adj_after = get_adjustment(adj["id"])
        assert adj_after["disposition"] == "REJECTED"
        assert adj_after["disposition_rationale"] == "ENGAGEMENT_CANCELLED", (
            f"cancel cascade pins the rationale, got "
            f"{adj_after['disposition_rationale']!r}"
        )


class TestIssueReportGateOrdering:

    def test_state_gate_beats_fiscal_gate(self):
        """PRD §3.8: "Three gates guard it, in the precedence order of §2.10:
        the engagement must be in `FIELDWORK_COMPLETE`
        (`ERR_ENGAGEMENT_NOT_CLOSING`); the representation letter must be
        `SIGNED` (`ERR_REP_LETTER_NOT_SIGNED`); and the passed-adjustment
        total must clear materiality".
        PRD §2.10: "Fifth, target-state preconditions for the requested
        transition — the `ERR_..._NOT_...` 409 family, such as
        `ERR_PBC_NOT_UNDER_REVIEW` or `ERR_FEE_CHANGE_NOT_PROPOSED`." ...
        "Twelfth, the passed-adjustment materiality gate
        (`ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_issue_report
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="IotaInc", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 100_000, description="Big miss")
        pass_adjustment(adj["id"], rationale="Client refuses")
        # Engagement stays in FIELDWORK (never completed); passed total would
        # also fail the fiscal gate — the state gate fires first.
        resp = api_client.issue_report(eng["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_CLOSING)
        assert get_engagement(eng["id"])["status"] == "FIELDWORK", \
            "rejected issuance leaves the engagement status unchanged"

    def test_rep_letter_gate_beats_fiscal_gate(self):
        """PRD §3.8: "Three gates guard it, in the precedence order of §2.10:
        the engagement must be in `FIELDWORK_COMPLETE`
        (`ERR_ENGAGEMENT_NOT_CLOSING`); the representation letter must be
        `SIGNED` (`ERR_REP_LETTER_NOT_SIGNED`); and the passed-adjustment
        total must clear materiality".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_issue_report
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="IotaInc", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 100_000, description="Big miss")
        pass_adjustment(adj["id"], rationale="Client refuses")
        complete_fieldwork(eng["id"])
        create_rep_letter(eng["id"], preparer_user="prep_a")  # stays DRAFT
        resp = api_client.issue_report(eng["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_REP_LETTER_NOT_SIGNED)
        assert get_engagement(eng["id"])["status"] == "FIELDWORK_COMPLETE"


class TestRepLetterSegregationOfDuties:

    def test_sign_by_drafter_rejected_sod(self):
        """PRD §3.8: "The letter must be in `PENDING_SIGNATURE`
        (`ERR_REP_LETTER_NOT_PENDING`), and segregation of duties forbids the
        signer from being the drafter: if `X-User-ID` equals
        `prepared_by_user_id`, the signing is rejected with
        `ERR_REP_LETTER_SOD_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_rep_sign
        """
        ctx = setup_closing_engagement(client_name="KappaCo")
        eng_id = ctx["engagement"]["id"]
        letter = setup_pending_rep_letter(eng_id, preparer_user="user_x")
        assert letter["prepared_by_user_id"] == "user_x"
        resp = api_client.sign_representation_letter(
            letter["id"],
            {"expected_engagement_version": engagement_version(eng_id)},
            make_controller_headers("user_x"),
        )
        validate_error(resp, ApiErrorId.ERR_REP_LETTER_SOD_VIOLATION)
        assert _get_letter(letter["id"])["status"] == "PENDING_SIGNATURE", \
            "rejected signing leaves the letter PENDING_SIGNATURE"

    def test_sign_by_other_controller_succeeds(self):
        """PRD §3.8: "Signing records `signed_by_user_id`, stamps `signed_at`
        from the logical clock, moves the letter to its terminal `SIGNED`
        state, recomputes the engagement's `posture` to `LOCKED`, increments
        the engagement's `version` by one, and cascades".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_rep_sign
        """
        ctx = setup_closing_engagement(client_name="KappaCo")
        eng_id = ctx["engagement"]["id"]
        letter = setup_pending_rep_letter(eng_id, preparer_user="user_x")
        version_before = engagement_version(eng_id)
        resp = api_client.sign_representation_letter(
            letter["id"],
            {"expected_engagement_version": version_before},
            make_controller_headers("ctrl_b"),
        )
        signed = validate_success(resp)
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == "ctrl_b"
        assert is_iso8601_timestamp(signed["signed_at"]), \
            "signed_at stamped from the logical clock"
        after = get_engagement(eng_id)
        assert after["posture"] == "LOCKED", \
            "signing recomputes posture to LOCKED"
        assert after["version"] == version_before + 1, (
            f"signing increments the engagement version by one "
            f"({version_before} -> {after['version']})"
        )


class TestCloseoutGuards:

    def test_complete_fieldwork_with_open_pbc_rejected(self):
        """PRD §3.8: "Completing fieldwork — an `ExternalAuditor` action
        moving the engagement from `FIELDWORK` to `FIELDWORK_COMPLETE` —
        demands a clean desk: the engagement must be in `FIELDWORK`
        (`ERR_ENGAGEMENT_NOT_IN_FIELDWORK`), no PBC request may remain in
        `OPEN`, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED`
        (`ERR_UNRESOLVED_PBC_REQUESTS`)".

        Design: Corner/errors/error_complete_fieldwork_unresolved_pbc
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        create_pbc(eng["id"], owner="prep1", title="T")
        resp = api_client.complete_fieldwork(eng["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_PBC_REQUESTS)
        assert get_engagement(eng["id"])["status"] == "FIELDWORK"

    def test_issue_report_without_signed_letter_rejected(self):
        """PRD §3.8: "Three gates guard it, in the precedence order of §2.10:
        the engagement must be in `FIELDWORK_COMPLETE`
        (`ERR_ENGAGEMENT_NOT_CLOSING`); the representation letter must be
        `SIGNED` (`ERR_REP_LETTER_NOT_SIGNED`)".

        Design: Corner/errors/error_rep_letter_not_signed_blocks_issue_report
        """
        ctx = setup_closing_engagement(client_name="C",
                                       materiality_cents=100_000)
        eng_id = ctx["engagement"]["id"]
        create_rep_letter(eng_id, preparer_user="prep_a")  # DRAFT, not signed
        resp = api_client.issue_report(eng_id, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_REP_LETTER_NOT_SIGNED)

    def test_auditor_cannot_sign_rep_letter(self):
        """PRD §2.1: "Each endpoint admits a defined set of roles (§4); a
        request whose role is not admitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/api/representation-letters/{id}/sign` | Sign the
        letter (SoD-checked, OCC-guarded) | Controller |".

        Design: Corner/rbac/auditor_cannot_sign_rep_letter
        """
        ctx = setup_closing_engagement(client_name="C",
                                       materiality_cents=100_000)
        eng_id = ctx["engagement"]["id"]
        letter = setup_pending_rep_letter(eng_id, preparer_user="prep_a")
        resp = api_client.sign_representation_letter(
            letter["id"],
            {"expected_engagement_version": engagement_version(eng_id)},
            make_auditor_headers("aud-9"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert _get_letter(letter["id"])["status"] == "PENDING_SIGNATURE"
