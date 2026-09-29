"""The auto-flag threshold is inclusive on the flagging side.

Two documents are uploaded against the same file within one setup: one whose
declared signals weigh 25 + 20 + 15 and one whose signals weigh 25 + 20 + 10.
Sixty flags; fifty-five does not.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_score_2dp


@pytest.fixture()
def two_scored_documents(client):
    """One document exactly on the threshold and one five points under it."""
    agency = fx.register_agency(client)
    fx.clear_agency(client, agency["id"])
    program = fx.create_program(client)
    application = fx.create_application(
        client,
        agency["id"],
        program["id"],
        student_ref="STU-4001",
        student_residence_country="IN",
    )

    at_threshold = fx.upload_document(
        client,
        agency["id"],
        application["id"],
        doc_type=C.DOC_TRANSCRIPT,
        content_hash="hash-transcript-4001",
        issuer_name="Regional Board",
        declared_signals=[
            C.SIGNAL_ISSUER_UNVERIFIED,
            C.SIGNAL_TRANSCRIPT_ANOMALY,
            C.SIGNAL_TRANSLATION_MISMATCH,
        ],
    )
    below_threshold = fx.upload_document(
        client,
        agency["id"],
        application["id"],
        doc_type=C.DOC_ENGLISH_TEST,
        content_hash="hash-english-4001",
        issuer_name="Test Centre 44",
        declared_signals=[
            C.SIGNAL_ISSUER_UNVERIFIED,
            C.SIGNAL_TRANSCRIPT_ANOMALY,
            C.SIGNAL_DATE_INCONSISTENCY,
        ],
    )

    return {
        "agency_id": agency["id"],
        "application_id": application["id"],
        "at_threshold_id": at_threshold["id"],
        "below_threshold_id": below_threshold["id"],
    }


class TestFraudIndexBoundary:
    @pytest.mark.parametrize(
        "document_key,expected_index,expected_state",
        [
            ("at_threshold_id", 60, C.VERIFICATION_FLAGGED),
            ("below_threshold_id", 55, C.VERIFICATION_PENDING),
        ],
    )
    def test_sixty_flags_at_upload_and_fifty_five_stays_pending(
        self,
        client,
        two_scored_documents,
        document_key,
        expected_index,
        expected_state,
    ):
        """The comparison is greater-than-or-equal against sixty.

        "`fraud_index` is then the sum of the weights of the distinct signals in
        `fraud_signals`, capped at 100."

        "A document whose index reaches 60 is auto-flagged at upload: it lands in
        `verification_state` `FLAGGED` rather than `PENDING`"

        "The boundary is inclusive on the flagging side — an index of exactly 60
        flags, and 59 does not."

        Design: Difficulty/boundary_precision_check/fraud_index_flag_boundary_at_exactly_sixty
        """
        document = fx.read_document(client, two_scored_documents[document_key])
        assert document["fraud_index"] == expected_index
        assert document["verification_state"] == expected_state

    def test_distinct_content_hashes_on_one_file_raise_no_duplicate_signal(
        self, client, two_scored_documents
    ):
        """Nothing beyond the declared signals is added here.

        "`fraud_signals` is the declared set plus, when applicable, the additional
        signal `HASH_DUPLICATE`: that signal is added when some other document
        already recorded carries the identical `content_hash` and belongs to a
        *different* application of the *same* agency."

        Design: Difficulty/boundary_precision_check/fraud_index_flag_boundary_at_exactly_sixty
        """
        env = two_scored_documents

        for key in ("at_threshold_id", "below_threshold_id"):
            document = fx.read_document(client, env[key])
            assert C.SIGNAL_HASH_DUPLICATE not in document["fraud_signals"]

    def test_only_the_flagged_document_counts_as_reviewed_and_a_flag_is_not_risk(
        self, client, two_scored_documents
    ):
        """The hold goes up, but no incident exists to score.

        "the owning application's `integrity_hold` is set to true, which
        recomputes the agency's `reviewed_document_count`"

        "the reviewed count spans documents on all of that agency's applications
        whose `verification_state` is `VERIFIED`, `FLAGGED`, `CONFIRMED_FRAUD` or
        `CLEARED`"

        "Two risk figures are maintained on every agency from the same underlying
        data, and only incidents in `CONFIRMED` contribute"

        Design: Difficulty/boundary_precision_check/fraud_index_flag_boundary_at_exactly_sixty
        """
        env = two_scored_documents

        application = fx.read_application(client, env["application_id"])
        assert application["integrity_hold"] is True

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["reviewed_document_count"] == 1
        assert agency["confirmed_fraud_document_count"] == 0
        assert_score_2dp(agency["rolling_risk_score"], 0.00, "rolling_risk_score")
