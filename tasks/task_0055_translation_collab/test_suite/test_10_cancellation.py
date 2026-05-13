"""Project cancellation, segment cascade, and document archive cascade.

PRD §3.8 (Cancellation and Reversal Paths), §3.2 (Document archive).
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
    cancel_project,
    get_segment,
    setup_client_and_project_in_draft,
    setup_quoted_project_with_one_word_segment,
)


# ===========================================================================
# Cancellation from DRAFT
# ===========================================================================
class TestCancelFromDraft:

    def test_cancel_draft_project_transitions_to_cancelled(self):
        """PRD §3.8: "A project manager may cancel a project at any time
        while it is in DRAFT or ACTIVE."

        Claim: POST /projects/{id}/cancel from DRAFT -> state == "CANCELLED".
        """
        _, project = setup_client_and_project_in_draft()
        cancelled = cancel_project(project["id"])
        assert cancelled["state"] == "CANCELLED"

    def test_cancel_draft_sets_segments_to_rejected(self):
        """PRD §3.8: "On cancellation from DRAFT, every segment is set to
        REJECTED."

        Claim: every segment under a cancelled DRAFT project ends in
        Segment.state == "REJECTED".
        """
        # We use a DRAFT project (not QUOTED, not ACTIVE) with one segment.
        # Build manually.
        from test_helpers import (
            setup_client_and_project_in_draft, upload_document,
            split_document, build_words_text,
        )
        _, project = setup_client_and_project_in_draft()
        doc = upload_document(project["id"], raw_text=build_words_text(5))
        ds = split_document(doc["id"])
        segments = ds.get("segments") or doc.get("segments") or []
        assert segments, "Setup must yield at least one segment"
        cancel_project(project["id"])
        for s in segments:
            seg = get_segment(s["id"])
            assert seg["state"] == "REJECTED", (
                "PRD §3.8: 'On cancellation from DRAFT, every segment is "
                "set to REJECTED.'"
            )
