"""The gates guarding the single most heavily gated transition in the system.

Submission takes no body, so every refusal here comes from state the caller
cannot see in the request: an unverified passport, a live fraud hold, a residence
country nobody was granted, a rate card that has run out, a training record the
clock retired, and an acknowledgement pinned to superseded paper.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_sweep_counts
from test_helpers.test_users import COMPLIANCE, make_applicant_headers


class TestTheIdentityGateAnswersBeforeTheFraudGate:
    @pytest.fixture()
    def file_failing_both_document_gates(self, client):
        """A student file with a PENDING passport and a flagged financial proof."""
        partner = fx.build_active_partner(
            client, legal_name="Two Gate Agency", contract_ref="CTR-001"
        )
        ready = fx.build_submission_ready_application(
            client, partner, student_ref="STU-001", verify_passport=False
        )
        financial = fx.upload_document(
            client,
            partner["agency_id"],
            ready["application_id"],
            C.DOC_FINANCIAL_PROOF,
            "hash-g-002",
            "Unknown Bank",
            [
                C.SIGNAL_ISSUER_UNVERIFIED,
                C.SIGNAL_TRANSCRIPT_ANOMALY,
                C.SIGNAL_TRANSLATION_MISMATCH,
                C.SIGNAL_DATE_INCONSISTENCY,
            ],
        )
        return {
            "partner": partner,
            "application_id": ready["application_id"],
            "passport_id": ready["passport_id"],
            "financial_id": financial["id"],
            "financial": financial,
        }

    def test_the_flagged_upload_holds_the_file_the_moment_it_lands(
        self, client, file_failing_both_document_gates
    ):
        """Four declared signals reach the flagging threshold on their own.

        "`HASH_DUPLICATE` weighs 45, `ISSUER_UNVERIFIED` weighs 25,
        `TRANSCRIPT_ANOMALY` weighs 20, `TRANSLATION_MISMATCH` weighs 15, and
        `DATE_INCONSISTENCY` weighs 10, and the index is always a whole number between 0
        and 100."

        "A document whose index reaches 60 is auto-flagged at upload: it lands in
        `verification_state` `FLAGGED` rather than `PENDING`, and the owning
        application's `integrity_hold` is set to true"

        Design: Corner/validations/submit_identity_check_precedes_fraud_hold
        """
        env = file_failing_both_document_gates

        assert env["financial"]["fraud_index"] == 70
        assert env["financial"]["verification_state"] == C.VERIFICATION_FLAGGED
        assert (
            fx.read_application(client, env["application_id"])["integrity_hold"] is True
        )

    def test_each_gate_surfaces_only_once_the_one_above_it_is_satisfied(
        self, client, file_failing_both_document_gates
    ):
        """Three submits of the identical empty body give three different answers.

        "Business-safety gates, in this internal order: vetting cleared
        (`ERR_AGENCY_NOT_CLEARED`); compliance posture
        (`ERR_AGENCY_POSTURE_BLOCKED`); training currency (`ERR_TRAINING_LAPSED`);
        verified identity document (`ERR_IDENTITY_DOCUMENT_UNVERIFIED`); fraud hold
        (`ERR_FRAUD_HOLD_ACTIVE`)"

        "the absence of a verified passport is `ERR_IDENTITY_DOCUMENT_UNVERIFIED`; a
        live fraud hold is `ERR_FRAUD_HOLD_ACTIVE`"

        "`CLEARED` moves `FLAGGED → CLEARED` and lifts the hold conditionally:
        `integrity_hold` returns to false only when no *other* document on that same
        application remains in `FLAGGED` or `CONFIRMED_FRAUD`."

        Design: Corner/validations/submit_identity_check_precedes_fraud_hold
        """
        env = file_failing_both_document_gates
        owner = env["partner"]["owner_headers"]

        both_broken = client.submit_application(env["application_id"], owner)
        validate_error(both_broken, E.ERR_IDENTITY_DOCUMENT_UNVERIFIED, 422)

        fx.verify_document(client, env["passport_id"], C.VERIFICATION_VERIFIED)
        hold_only = client.submit_application(env["application_id"], owner)
        validate_error(hold_only, E.ERR_FRAUD_HOLD_ACTIVE, 422)

        fx.verify_document(
            client,
            env["financial_id"],
            C.VERIFICATION_CLEARED,
            note="Bank confirmed the letter after all",
        )
        assert (
            fx.read_application(client, env["application_id"])["integrity_hold"] is False
        )

        accepted = validate_success(
            client.submit_application(env["application_id"], owner)
        )
        assert accepted["status"] == C.APPLICATION_SUBMITTED
        assert accepted["submitted_on"] == C.DEFAULT_CLOCK_DATE
        assert accepted["pinned_contract_id"] == env["partner"]["contract_id"]
        assert accepted["tier_snapshot_at_submission"] == C.TIER_UNRATED


class TestTerritoryIsReadFromTheStudentsCountry:
    def test_an_indian_agency_may_not_submit_a_vietnamese_student(self, client):
        """The grant covers IN; the student lives in VN, so the file stays DRAFT.

        "a territory assignment in `ACTIVE` exists on the pinned contract whose
        `country_code` equals the application's `student_residence_country` and whose
        window covers the current date"

        "an uncovered residence country is `ERR_TERRITORY_NOT_COVERED`"

        Design: Corner/validations/submit_outside_assigned_territory_rejected
        """
        partner = fx.build_active_partner(
            client,
            legal_name="Wrong Territory Agency",
            contract_ref="CTR-001",
            territory_country="IN",
        )
        ready = fx.build_submission_ready_application(
            client,
            partner,
            student_ref="STU-VN-1",
            student_residence_country="VN",
            passport_hash="hash-vn-001",
            passport_issuer="MOFA Vietnam",
        )

        refused = client.submit_application(
            ready["application_id"], partner["owner_headers"]
        )
        body = validate_error(refused, E.ERR_TERRITORY_NOT_COVERED, 422)
        assert body["error_id"] != E.ERR_SCHEDULE_NOT_EFFECTIVE, (
            "the rate card is effective; only the country grant is missing"
        )

        untouched = fx.read_application(client, ready["application_id"])
        assert untouched["status"] == C.APPLICATION_DRAFT
        assert untouched["submitted_on"] is None
        assert untouched["pinned_contract_id"] is None


class TestTheRateCardWindowIsHalfOpen:
    def test_the_first_uncovered_day_refuses_a_file_the_contract_still_welcomes(
        self, client
    ):
        """The contract runs to 2027 but its only card stops covering 2026-08-11.

        "a rate card on the pinned contract covers the current date in the same
        half-open sense, with `effective_from` at or before it and `effective_to`
        strictly after it."

        "the absence of an effective rate card is `ERR_SCHEDULE_NOT_EFFECTIVE`"

        Design: Corner/validations/submit_after_rate_card_lapses_rejected
        """
        partner = fx.build_active_partner(
            client,
            legal_name="Lapsed Card Agency",
            contract_ref="CTR-001",
            schedule_overrides={"effective_to": "2026-08-11"},
        )
        ready = fx.build_submission_ready_application(
            client, partner, student_ref="STU-001", passport_hash="hash-l-001"
        )
        fx.set_clock(client, "2026-08-11T00:00:00Z")

        refused = client.submit_application(
            ready["application_id"], partner["owner_headers"]
        )
        validate_error(refused, E.ERR_SCHEDULE_NOT_EFFECTIVE, 422)

        assert (
            fx.read_contract(client, partner["contract_id"])["status"]
            == C.CONTRACT_ACTIVE
        )
        cards = fx.read_schedules(client, partner["contract_id"])
        assert len(cards) == 1
        assert cards[0]["effective_to"] == "2026-08-11"

        untouched = fx.read_application(client, ready["application_id"])
        assert untouched["status"] == C.APPLICATION_DRAFT
        assert untouched["pinned_schedule_id"] is None


class TestTheShorterCertificationLapsesFirst:
    def test_the_sweep_retires_one_module_and_that_alone_blocks_the_submit(self, client):
        """Both records were issued the same day; only one is a half-year record.

        "`expires_on` is `issued_on` advanced by the module's validity period: one full
        year for `PROGRAM_ACCURACY`, half a year — 180 days — for `PROHIBITED_CLAIMS`,
        and one full year for `VISA_INTEGRITY`, where a full year is 365 days."

        "Every `TrainingCertification` still in `VALID` whose `expires_on` is on or
        before the current logical-clock date moves to `EXPIRED`."

        "a missing or lapsed `PROGRAM_ACCURACY` or `PROHIBITED_CLAIMS` certification is
        `ERR_TRAINING_LAPSED`, where lapsed means the current logical-clock date has
        reached `expires_on`"

        Design: Corner/validations/submit_with_lapsed_prohibited_claims_training_rejected
        """
        partner = fx.build_active_partner(
            client, legal_name="Lapsed Training Agency", contract_ref="CTR-001"
        )
        ready = fx.build_submission_ready_application(
            client, partner, student_ref="STU-001", passport_hash="hash-t-001"
        )

        sweep = fx.set_clock(client, "2027-01-28T00:00:00Z", COMPLIANCE)
        assert_sweep_counts(
            sweep,
            current_utc="2027-01-28T00:00:00Z",
            expired_contract_count=0,
            expired_assignment_count=0,
            expired_certification_count=1,
            risk_recomputed_agency_count=0,
        )

        by_module = {
            record["module_code"]: record
            for record in fx.read_certifications(client, partner["agency_id"])
        }
        assert by_module[C.MODULE_PROHIBITED_CLAIMS]["status"] == C.CERT_EXPIRED
        assert by_module[C.MODULE_PROHIBITED_CLAIMS]["expires_on"] == "2027-01-28"
        assert by_module[C.MODULE_PROGRAM_ACCURACY]["status"] == C.CERT_VALID
        assert by_module[C.MODULE_PROGRAM_ACCURACY]["expires_on"] == "2027-08-01"

        refused = client.submit_application(
            ready["application_id"], partner["owner_headers"]
        )
        validate_error(refused, E.ERR_TRAINING_LAPSED, 422)

        assert (
            fx.read_application(client, ready["application_id"])["disclosure_state"]
            == C.DISCLOSURE_ACKNOWLEDGED
        ), "the disclosure gate above is satisfied, so the training gate is the answer"


class TestAnAcknowledgementCanSurviveAndStillBeStale:
    @pytest.fixture()
    def acknowledged_against_superseded_paper(self, client):
        """A genuine acknowledgement at template version 1, then an amendment."""
        partner = fx.build_active_partner(
            client,
            legal_name="Stale Disclosure Agency",
            contract_ref="CTR-001",
            activate=False,
        )
        fx.send_contract_for_signature(client, partner["contract_id"])
        fx.agency_sign_contract(
            client, partner["agency_id"], partner["contract_id"]
        )

        ready = fx.build_submission_ready_application(
            client, partner, student_ref="STU-001", passport_hash="hash-s-001"
        )

        fx.request_amendment(
            client,
            partner["contract_id"],
            "Fee clause reworded after student feedback",
        )
        fx.activate_contract(client, partner["agency_id"], partner["contract_id"])

        return {"partner": partner, "application_id": ready["application_id"]}

    def test_the_amendment_spares_the_acknowledgement_but_advances_the_template(
        self, client, acknowledged_against_superseded_paper
    ):
        """The student's act stands; the paper underneath it has moved on.

        "It also reaches into the student files: every application of that agency whose
        `disclosure_state` is `ISSUED` is driven to `INVALIDATED`."

        "Deliberately, an application whose disclosure is already `ACKNOWLEDGED` keeps
        that state — it is *not* invalidated"

        "It increments `amendment_round`, increments `disclosure_template_version`, and
        clears `agency_signed_by_user_id` so the agency must sign the revised paper
        again."

        Design: Corner/validations/submit_with_stale_acknowledged_disclosure_rejected
        """
        env = acknowledged_against_superseded_paper

        application = fx.read_application(client, env["application_id"])
        assert application["disclosure_state"] == C.DISCLOSURE_ACKNOWLEDGED
        assert application["disclosure_template_version"] == 1

        contract = fx.read_contract(client, env["partner"]["contract_id"])
        assert contract["disclosure_template_version"] == 2
        assert contract["amendment_round"] == 1
        assert contract["status"] == C.CONTRACT_ACTIVE

    def test_the_stale_pin_is_its_own_refusal_not_a_missing_acknowledgement(
        self, client, acknowledged_against_superseded_paper
    ):
        """The two disclosure codes are not interchangeable.

        "its pinned `disclosure_template_version` equals the
        `disclosure_template_version` of the agency's contract that is currently in
        `ACTIVE`"

        "a template version behind the active contract's is
        `ERR_DISCLOSURE_VERSION_STALE`"

        Design: Corner/validations/submit_with_stale_acknowledged_disclosure_rejected
        """
        env = acknowledged_against_superseded_paper

        refused = client.submit_application(
            env["application_id"], env["partner"]["owner_headers"]
        )
        body = validate_error(refused, E.ERR_DISCLOSURE_VERSION_STALE, 409)
        assert body["error_id"] != E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED, (
            "the acknowledgement exists; it is merely pinned to superseded paper"
        )


class TestTheTokenAuthenticatesTheAcknowledgement:
    def test_a_fabricated_token_is_refused_and_the_issued_one_is_accepted(self, client):
        """The same applicant, the same endpoint, two different tokens.

        "the student presents `ack_token`, which must equal the application's current
        `disclosure_ack_token`, and the application moves `ISSUED → ACKNOWLEDGED` with
        `disclosure_acknowledged_at` stamped from the logical-clock instant. A wrong or
        superseded token is refused with `ERR_DISCLOSURE_TOKEN_INVALID` (HTTP 403)."

        Design: Corner/validations/acknowledge_with_wrong_token_rejected
        """
        agency = fx.register_agency(client, legal_name="Token Agency")
        fx.clear_agency(client, agency["id"])
        program = fx.create_program(client)
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        fx.append_schedule(client, contract["id"], contract["version"])
        fx.send_contract_for_signature(client, contract["id"])

        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )
        issued = fx.issue_disclosure(client, agency["id"], application["id"])
        assert issued["disclosure_state"] == C.DISCLOSURE_ISSUED

        applicant = make_applicant_headers("applicant-001")
        fabricated = client.application_disclosure(
            application["id"],
            F.disclosure_acknowledge_payload(NON_EXISTENT_UUID),
            applicant,
        )
        validate_error(fabricated, E.ERR_DISCLOSURE_TOKEN_INVALID, 403)
        assert (
            fx.read_application(client, application["id"])["disclosure_state"]
            == C.DISCLOSURE_ISSUED
        )

        accepted = validate_success(
            client.application_disclosure(
                application["id"],
                F.disclosure_acknowledge_payload(issued["disclosure_ack_token"]),
                applicant,
            )
        )
        assert accepted["disclosure_state"] == C.DISCLOSURE_ACKNOWLEDGED
        assert accepted["disclosure_acknowledged_at"] is not None
        assert accepted["disclosure_template_version"] == 1
