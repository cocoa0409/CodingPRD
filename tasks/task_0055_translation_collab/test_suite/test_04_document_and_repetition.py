"""Document upload, splitting, and repetition_class classification.

PRD §2.9 (TM Leverage / Repetition), §3.2 (Document split, repetition
detection).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    api_client,
    assert_document,
    assert_segment,
    build_multi_sentence_text,
    build_repeated_sentence_text,
    build_words_text,
    create_client,
    create_project,
    setup_client_and_project_in_draft,
    setup_repetition_project,
    split_document,
    upload_document,
    upload_document_payload,
)


# ===========================================================================
# Document basics
# ===========================================================================
class TestDocumentUpload:

    def test_uploaded_document_state_is_uploaded(self):
        """PRD §3.2: "A newly uploaded document is in state UPLOADED;
        its segments are not materialised until the manager invokes the
        split operation."

        Claim: POST /projects/{id}/documents -> Document.state == "UPLOADED".
        """
        _, project = setup_client_and_project_in_draft()
        doc = upload_document(project["id"], raw_text="Hello world.")
        assert doc["state"] == "UPLOADED"
        assert_document(doc)


class TestDocumentSplit:

    def test_split_transitions_document_to_split(self):
        """PRD §3.2: "The document transitions to SPLIT."

        Claim: POST /documents/{id}/split -> Document.state == "SPLIT".
        """
        _, project = setup_client_and_project_in_draft()
        doc = upload_document(project["id"], raw_text="One sentence here.")
        result = split_document(doc["id"])
        assert result["state"] == "SPLIT"

    def test_split_recomputes_project_word_count(self):
        """PRD §3.2: "Splitting the document ... captures the per-segment
        source_text and computes its word_count (which must be at least 1),
        and writes the denormalized project_id onto each segment for query
        convenience."

        Claim: after split, Project.word_count is non-zero.
        """
        client, project = setup_client_and_project_in_draft()
        upload_document(project["id"], raw_text=build_words_text(10))
        # Use split via the helper's document handle
        from test_helpers import upload_document as upd
        from test_helpers import api_client as ac
        # Re-upload+split + verify via project GET
        doc = upd(project["id"], raw_text=build_words_text(10))
        split_document(doc["id"])
        resp = ac.get_project(project["id"], PM)
        proj = validate_success(resp)
        assert proj["word_count"] >= 10


# ===========================================================================
# Repetition detection (PRD §2.9, §3.2)
# ===========================================================================
class TestRepetitionDetection:

    def test_first_occurrence_classified_new(self):
        """PRD §2.9: "the earliest-ordinal segment for a given normalized
        source string within a project always retains the NEW classification
        — only its later siblings can match against it."

        Claim: when a sentence is repeated, the first segment is NEW.
        """
        # Two identical sentences in one document.
        _, _, _, segments = setup_repetition_project(
            repeated_word_count=5,
            repetitions=2,
        )
        # Sort by ordinal
        sorted_segs = sorted(segments, key=lambda s: (s["document_id"], s["ordinal"]))
        # The first segment (earliest) must be NEW; the second matches it.
        assert sorted_segs[0]["repetition_class"] == "NEW", \
            "first occurrence of a normalized source string is NEW"

    def test_exact_duplicate_classified_exact_repeat(self):
        """PRD §2.9: "When the exact-match count is at least 1 and the
        fuzzy-match percentage is exactly 100, the segment is classified
        as EXACT_REPEAT with tm_leverage_pct set to 100."

        Claim: a second identical sentence is classified EXACT_REPEAT with
        tm_leverage_pct == 100.
        """
        _, _, _, segments = setup_repetition_project(
            repeated_word_count=5,
            repetitions=2,
        )
        sorted_segs = sorted(segments, key=lambda s: (s["document_id"], s["ordinal"]))
        second = sorted_segs[1]
        assert second["repetition_class"] == "EXACT_REPEAT", \
            "duplicate-normalized source must classify EXACT_REPEAT"
        assert second["tm_leverage_pct"] == 100, \
            "EXACT_REPEAT carries tm_leverage_pct == 100"


# ===========================================================================
# Document archive (PRD §3.2)
# ===========================================================================
class TestDocumentArchive:

    def test_archive_document_zeros_project_word_count(self):
        """PRD §3.2: "archiving sets every child segment to REJECTED and
        recomputes both Document.word_count and Project.word_count."

        Claim: DELETE /documents/{id} drives Project.word_count back to 0
        when the project had only one document.
        """
        client, project = setup_client_and_project_in_draft()
        doc = upload_document(project["id"], raw_text=build_words_text(10))
        split_document(doc["id"])
        # Confirm the count is non-zero
        resp = api_client.get_project(project["id"], PM)
        proj = validate_success(resp)
        assert proj["word_count"] >= 10
        # Archive the document
        api_client.archive_document(doc["id"], PM)
        # Word count must drop
        resp2 = api_client.get_project(project["id"], PM)
        proj2 = validate_success(resp2)
        assert proj2["word_count"] == 0, \
            "Project.word_count must recompute to 0 after archive of sole doc"
