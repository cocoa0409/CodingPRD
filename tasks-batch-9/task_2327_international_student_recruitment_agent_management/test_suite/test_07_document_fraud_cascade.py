"""One verification outcome propagates five hops.

A flagged transcript is confirmed as fraudulent.  That appends an incident on its
own authority, the incident plus the newly non-zero fraud-document rate lands the
rolling figure exactly on the probation floor, probation suspends the contract,
and the suspension releases the territory and tears down the draft disclosure.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_score_2dp


@pytest.fixture()
def flagged_transcript_file(client):
    """A partner one confirmation short of the probation band."""
    agency = fx.register_agency(client)
    fx.clear_agency(client, agency["id"])
    program = fx.create_program(client)
    contract = fx.draft_contract(client, agency["id"])
    fx.append_schedule(client, contract["id"], contract["version"])
    territory = fx.assign_territory(client, contract["id"])
    fx.activate_contract(client, agency["id"], contract["id"])

    application = fx.create_application(
        client,
        agency["id"],
        program["id"],
        student_ref="STU-1001",
        student_residence_country="IN",
    )
    clean = fx.upload_document(
        client,
        agency["id"],
        application["id"],
        doc_type=C.DOC_PASSPORT,
        content_hash="hash-passport-1001",
        issuer_name="MEA India",
    )
    fx.verify_document(client, clean["id"], C.VERIFICATION_VERIFIED)

    # 25 + 20 + 15 lands the index exactly on the auto-flag boundary.
    transcript = fx.upload_document(
        client,
        agency["id"],
        application["id"],
        doc_type=C.DOC_TRANSCRIPT,
        content_hash="hash-transcript-1001",
        issuer_name="Unverified Board of Studies",
        declared_signals=[
            C.SIGNAL_ISSUER_UNVERIFIED,
            C.SIGNAL_TRANSCRIPT_ANOMALY,
            C.SIGNAL_TRANSLATION_MISMATCH,
        ],
    )
    fx.issue_and_acknowledge_disclosure(
        client, agency["id"], application["id"], "applicant-1001"
    )

    incident = fx.file_incident(
        client,
        agency["id"],
        application_id=application["id"],
        category=C.INCIDENT_MISREPRESENTATION,
        severity=C.SEVERITY_MEDIUM,
        occurred_on=C.DEFAULT_CLOCK_DATE,
        source=C.SOURCE_STUDENT_COMPLAINT,
    )
    fx.resolve_incident(client, incident["id"], C.RESOLUTION_CONFIRM)

    return {
        "agency_id": agency["id"],
        "contract_id": contract["id"],
        "assignment_id": territory["id"],
        "application_id": application["id"],
        "clean_document_id": clean["id"],
        "transcript_id": transcript["id"],
    }


@pytest.fixture()
def confirmed_fraud(client, flagged_transcript_file):
    """Fire the confirmation that opens the cascade."""
    fx.verify_document(
        client,
        flagged_transcript_file["transcript_id"],
        C.VERIFICATION_CONFIRMED_FRAUD,
        note="Issuer confirmed the transcript was never issued",
    )
    return flagged_transcript_file


class TestDocumentFraudCascade:
    def test_confirmation_appends_its_own_incident_with_fixed_attributes(
        self, client, confirmed_fraud
    ):
        """Hops one and two: the document turns, and an incident is written.

        "First, an integrity incident is appended automatically, with `category`
        `DOCUMENT_FRAUD`, `severity` `HIGH`, `source` `DOCUMENT_REVIEW`, `status`
        already `CONFIRMED`, `occurred_on` set to the current logical-clock date,
        and both `document_id` and `application_id` populated from the document
        under review."

        "`HASH_DUPLICATE` weighs 45, `ISSUER_UNVERIFIED` weighs 25,
        `TRANSCRIPT_ANOMALY` weighs 20, `TRANSLATION_MISMATCH` weighs 15, and
        `DATE_INCONSISTENCY` weighs 10"

        Design: Difficulty/transitive_cascade/document_fraud_confirmation_five_hop_cascade
        """
        env = confirmed_fraud

        document = fx.read_document(client, env["transcript_id"])
        assert document["fraud_index"] == 60
        assert document["verification_state"] == C.VERIFICATION_CONFIRMED_FRAUD

        derived = [
            i
            for i in fx.read_incidents(client, agency_id=env["agency_id"])
            if i["category"] == C.INCIDENT_DOCUMENT_FRAUD
        ]
        assert len(derived) == 1, f"expected one derived incident, got {derived!r}"
        incident = derived[0]
        assert incident["severity"] == C.SEVERITY_HIGH
        assert incident["source"] == C.SOURCE_DOCUMENT_REVIEW
        assert incident["status"] == C.INCIDENT_CONFIRMED
        assert incident["occurred_on"] == C.DEFAULT_CLOCK_DATE
        assert incident["document_id"] == env["transcript_id"]
        assert incident["application_id"] == env["application_id"]

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["confirmed_incident_count"] == 2

    def test_the_fraud_document_rate_term_lands_the_rolling_figure_on_probation(
        self, client, confirmed_fraud
    ):
        """Hop three: 15.00 plus 30.00 plus forty times one half is 65.00.

        "the fraud rate is zero when the agency's `reviewed_document_count` is
        zero, and otherwise is `confirmed_fraud_document_count` divided by
        `reviewed_document_count`, where the reviewed count spans documents on
        all of that agency's applications whose `verification_state` is
        `VERIFIED`, `FLAGGED`, `CONFIRMED_FRAUD` or `CLEARED`"

        "Forty points are allocated to that term."

        "a rolling figure at or above 85.00 targets `SUSPENDED`, at or above
        65.00 but below 85.00 targets `PROBATION`"

        Design: Difficulty/transitive_cascade/document_fraud_confirmation_five_hop_cascade
        """
        env = confirmed_fraud

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["reviewed_document_count"] == 2
        assert agency["confirmed_fraud_document_count"] == 1
        assert_score_2dp(agency["rolling_risk_score"], 65.00, "rolling_risk_score")
        assert agency["compliance_posture"] == C.POSTURE_PROBATION
        assert agency["vetting_state"] == C.VETTING_CLEARED

    def test_probation_suspends_the_contract_and_strips_territory_and_disclosure(
        self, client, confirmed_fraud
    ):
        """Hops four and five, driven by nothing but the document outcome.

        "Third, an escalation that reaches `PROBATION` or `SUSPENDED` suspends
        the agency's contracts that are in `ACTIVE`. Fourth, each suspended
        contract releases its territory assignments still in `ACTIVE` and
        invalidates the disclosures on that agency's `DRAFT` applications."

        Design: Difficulty/transitive_cascade/document_fraud_confirmation_five_hop_cascade
        """
        env = confirmed_fraud

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_SUSPENDED
        assert (
            contract["suspension_reason"] == C.SUSPENSION_REASON_POSTURE_PROBATION
        )

        assignments = fx.read_assignments(client, env["contract_id"])
        released = [a for a in assignments if a["id"] == env["assignment_id"]]
        assert len(released) == 1, f"expected the one assignment, got {assignments!r}"
        assert released[0]["status"] == C.ASSIGNMENT_RELEASED
        assert released[0]["released_on"] == C.DEFAULT_CLOCK_DATE

        application = fx.read_application(client, env["application_id"])
        assert application["disclosure_state"] == C.DISCLOSURE_INVALIDATED
        assert application["disclosure_ack_token"] is None

    def test_the_hold_stays_and_the_clean_sibling_document_is_untouched(
        self, client, confirmed_fraud
    ):
        """Confirming fraud never lifts a hold, and never reaches a sibling.

        "Throughout, the owning application's `integrity_hold` stays true —
        confirming fraud never lifts a hold."

        "A document whose index reaches 60 is auto-flagged at upload: it lands in
        `verification_state` `FLAGGED` rather than `PENDING`, and the owning
        application's `integrity_hold` is set to true"

        Design: Difficulty/transitive_cascade/document_fraud_confirmation_five_hop_cascade
        """
        env = confirmed_fraud

        application = fx.read_application(client, env["application_id"])
        assert application["integrity_hold"] is True
        assert application["status"] == C.APPLICATION_DRAFT

        clean = fx.read_document(client, env["clean_document_id"])
        assert clean["verification_state"] == C.VERIFICATION_VERIFIED

    def test_the_boundary_index_flags_at_upload_before_any_officer_acts(
        self, client, flagged_transcript_file
    ):
        """The pre-trigger position: flagged on arrival, no escalation yet.

        "The boundary is inclusive on the flagging side — an index of exactly 60
        flags, and 59 does not."

        "The incident lands in `status` `REPORTED` and contributes nothing to
        risk until it is adjudicated."

        Design: Difficulty/transitive_cascade/document_fraud_confirmation_five_hop_cascade
        """
        env = flagged_transcript_file

        transcript = fx.read_document(client, env["transcript_id"])
        assert transcript["fraud_index"] == 60
        assert transcript["verification_state"] == C.VERIFICATION_FLAGGED

        agency = fx.read_agency(client, env["agency_id"])
        assert_score_2dp(agency["rolling_risk_score"], 15.00, "rolling_risk_score")
        assert agency["compliance_posture"] == C.POSTURE_GOOD_STANDING

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["status"] == C.CONTRACT_ACTIVE
