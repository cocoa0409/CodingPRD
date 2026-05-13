"""Terminology library lifecycle and project publish.

PRD §3.5 (Terminology Library Lifecycle), §3.7 (Publishing).
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
    approve_terminology,
    create_terminology,
    create_terminology_payload,
    find_sync_records,
    list_all_sync_records,
    publish_project,
    resolve_terminology,
    setup_full_pipeline_one_segment,
    setup_segment_at_reviewed,
)


# ===========================================================================
# Terminology lifecycle
# ===========================================================================
class TestTerminologyConflict:

    def test_duplicate_source_term_with_different_target_term_marks_conflict(self):
        """PRD §3.5: "when another entry with identical scope_type,
        scope_id, source_lang, target_lang, and source_term but a
        different target_term is already in PROPOSED or APPROVED, both
        rows transition to CONFLICT."

        Claim: two PROPOSED entries in the same scope with the same
        source_term but different target_term -> both end up in CONFLICT.
        """
        ctx = setup_segment_at_reviewed()
        project = ctx["project"]
        t1 = create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="bonjour",
        )
        t2 = create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="salut",
        )
        # Refresh both
        from test_helpers import api_client as ac
        r1 = ac.list_terminology(PM, params={
            "scope_type": "PROJECT", "scope_id": project["id"],
            "limit": 100,
        })
        body = r1.json()
        rows = body.get("data", [])
        states = {row["id"]: row["state"]
                  for row in rows if row["id"] in (t1["id"], t2["id"])}
        assert states.get(t1["id"]) == "CONFLICT", \
            "PRD §3.5: 'both rows transition to CONFLICT.'"
        assert states.get(t2["id"]) == "CONFLICT", \
            "PRD §3.5: 'both rows transition to CONFLICT.'"

    def test_resolve_without_loser_id_returns_required_loser(self):
        """PRD §3.5: "A request to resolve that omits or mis-identifies
        the loser is refused with ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER."

        Claim: POST /terminology/{id}/resolve with empty body ->
        ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER.
        """
        ctx = setup_segment_at_reviewed()
        project = ctx["project"]
        t1 = create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="bonjour",
        )
        t2 = create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="salut",
        )
        resp = api_client.resolve_terminology(t1["id"], {}, PM)
        validate_error(resp, ApiErrorId.ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER)


# ===========================================================================
# Publish — terminology gate
# ===========================================================================
class TestPublishTerminologyGate:

    def test_publish_blocked_by_conflict_terminology(self):
        """PRD §3.5: "Publish itself enforces that no project-scoped entry
        remains in CONFLICT — if any does, the publish call fails with
        ERR_TERMINOLOGY_CONFLICT."

        Claim: a CONFLICT terminology entry on the project blocks publish
        with ERR_TERMINOLOGY_CONFLICT.
        """
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        project = ctx["project"]
        # Force a CONFLICT pair
        create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="bonjour",
        )
        create_terminology(
            scope_type="PROJECT", scope_id=project["id"],
            source_term="hello", target_term="salut",
        )
        resp = api_client.publish_project(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TERMINOLOGY_CONFLICT)


# ===========================================================================
# Publish — happy path
# ===========================================================================
class TestPublishHappyPath:

    def test_publish_transitions_to_published(self):
        """PRD §3.7: "On success the project transitions from ALL_REVIEWED
        to PUBLISHED."

        Claim: Project.state becomes "PUBLISHED" after publish.
        """
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        proj = publish_project(ctx["project"]["id"])
        assert proj["state"] == "PUBLISHED"

    def test_publish_writes_final_payout_cents(self):
        """PRD §3.7: "The project's final_payout_cents is the larger of
        zero and the urgency-adjusted cents minus the total quality
        deduction."

        Claim: published project carries an integer final_payout_cents
        field.
        """
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        proj = publish_project(ctx["project"]["id"])
        assert isinstance(proj.get("final_payout_cents"), int)
        assert proj["final_payout_cents"] >= 0

    def test_publish_emits_three_sync_records(self):
        """PRD §3.7: "The platform creates three ExternalSyncRecord rows,
        one for each of PAYMENT, STORAGE, and IM, each with trigger_event
        PROJECT_PUBLISHED."

        Claim: after publish, ExternalSyncRecord rows exist for each of
        PAYMENT, STORAGE, and IM with trigger PROJECT_PUBLISHED.
        """
        ctx = setup_full_pipeline_one_segment(translator_grade="SENIOR")
        publish_project(ctx["project"]["id"])
        records = list_all_sync_records(project_id=ctx["project"]["id"])
        for target in ("PAYMENT", "STORAGE", "IM"):
            matches = find_sync_records(
                records, target_system=target,
                trigger_event="PROJECT_PUBLISHED",
            )
            assert matches, (
                f"PRD §3.7: ExternalSyncRecord for {target} / "
                f"PROJECT_PUBLISHED must be emitted."
            )
