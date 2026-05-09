"""Cycle state machine and date overlap (PRD §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_cycle_payload,
    create_cycle, create_open_cycle, open_cycle,
    setup_org,
)


# ---------------------------------------------------------------------------
# Cycle creation and lifecycle
# ---------------------------------------------------------------------------

class TestCycleLifecycle:
    def test_create_cycle_starts_in_draft(self, api, admin_headers):
        """PRD §3.1: "A new cycle starts in `DRAFT` status."""
        payload = create_cycle_payload(cycle_code="2026-Q1-LCA")
        resp = api.create_cycle(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["cycle_code"] == "2026-Q1-LCA"

    def test_open_cycle_advances_draft_to_open(self, api, admin_headers):
        """PRD §3.1: "Opening a cycle advances `OKRCycle.status` from `DRAFT` to `OPEN`"."""
        cycle = create_cycle(cycle_code="2026-LCB")
        assert cycle["status"] == "DRAFT"
        resp = api.open_cycle(cycle["id"], admin_headers)
        data = validate_success(resp)
        assert data["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty-design: cycle_half_open_interval_overlap
# ---------------------------------------------------------------------------

class TestCycleHalfOpenOverlap:
    """# difficulty: resource_temporal_overlap/cycle_half_open_interval_overlap"""

    def test_adjacent_cycles_do_not_overlap(self, api, admin_headers):
        """PRD §3.1: "the half-open semantics mean that one cycle ending exactly when the next begins is **not** an overlap."

        Claim: existing OPEN cycle [2080-01-01, 2080-04-01); a new cycle starting exactly at
        2080-04-01 is permitted because A.end == B.start is not an overlap.
        # difficulty: resource_temporal_overlap/cycle_half_open_interval_overlap
        """
        # Existing OPEN cycle (use distinct far-future year to avoid collision with other tests)
        c1 = create_open_cycle(
            cycle_code="2080-Q1-ADJ",
            year=2080, quarter=1,
            start="2080-01-01T00:00:00.000Z",
            end="2080-04-01T00:00:00.000Z",
        )
        # Adjacent cycle
        payload = create_cycle_payload(
            cycle_code="2080-Q2-ADJ", year=2080, quarter=2,
            start_date="2080-04-01T00:00:00.000Z",
            end_date="2080-07-01T00:00:00.000Z",
        )
        resp = api.create_cycle(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"

    def test_interior_overlap_rejected_with_err_cycle_overlap(self, api, admin_headers):
        """PRD §3.1: "an attempted overlap is rejected with `ERR_CYCLE_OVERLAP`."

        Claim: existing OPEN cycle [2081-01-01, 2081-04-01); a new cycle whose interval
        intersects the interior is rejected with ERR_CYCLE_OVERLAP.
        # difficulty: resource_temporal_overlap/cycle_half_open_interval_overlap
        """
        c1 = create_open_cycle(
            cycle_code="2081-Q1-INT",
            year=2081, quarter=1,
            start="2081-01-01T00:00:00.000Z",
            end="2081-04-01T00:00:00.000Z",
        )
        payload = create_cycle_payload(
            cycle_code="2081-Q1B-INT", year=2081, quarter=1,
            start_date="2081-03-15T00:00:00.000Z",
            end_date="2081-06-15T00:00:00.000Z",
        )
        resp = api.create_cycle(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP.value)


# ---------------------------------------------------------------------------
# Cycle archive cascade — second instance of difficulty-design transitive_cascade
# ---------------------------------------------------------------------------

class TestCycleArchiveCascade:
    """# difficulty: transitive_cascade/cycle_archive_cascade_to_links"""

    def test_archive_cascades_objectives_and_breaks_accepted_link(self, api, admin_headers):
        """PRD §3.1: "the archive cascade transitions every objective in the cycle to `ARCHIVED`, every `ACCEPTED` `AlignmentLink` whose upstream or downstream now sits in an archived objective transitions to `BROKEN`".

        Claim: archive a LOCKED cycle that has 2 objectives and 1 ACCEPTED link →
        cycle ARCHIVED, both objectives ARCHIVED, link BROKEN.
        # difficulty: transitive_cascade/cycle_archive_cascade_to_links
        """
        from test_helpers import setup_locked_cycle_with_two_objectives_and_link
        s = setup_locked_cycle_with_two_objectives_and_link()
        # Archive the cycle
        resp = api.archive_cycle(s["cycle"]["id"], admin_headers)
        data = validate_success(resp)
        assert data["status"] == "ARCHIVED"
        # Verify objectives ARCHIVED
        a = validate_success(api.get_objective(s["objective_a"]["id"], admin_headers))
        b = validate_success(api.get_objective(s["objective_b"]["id"], admin_headers))
        assert a["status"] == "ARCHIVED"
        assert b["status"] == "ARCHIVED"
        # Verify link BROKEN
        link_resp = api.list_alignment_links(
            admin_headers, params={"upstream_objective_id": s["objective_a"]["id"]}
        )
        link_body = link_resp.json()
        our_link = next((l for l in link_body["data"] if l["id"] == s["link"]["id"]), None)
        assert our_link is not None, "link must remain readable after archive"
        assert our_link["status"] == "BROKEN"


# ---------------------------------------------------------------------------
# Cycle lock requires every ReviewScore to be LOCKED
# ---------------------------------------------------------------------------

class TestCycleLockGate:
    def test_cycle_lock_requires_every_review_locked(self, api, admin_headers):
        """PRD §3.1: "Locking a cycle advances it from `IN_REVIEW` to `LOCKED`; this is only permitted once every `ReviewScore` for objectives in this cycle is itself in `LOCKED` status."

        Claim: cycle in IN_REVIEW with at least one non-LOCKED ReviewScore → POST /cycles/{id}/lock fails.
        """
        from test_helpers import setup_review_at_pending_self
        s = setup_review_at_pending_self()
        resp = api.lock_cycle(s["cycle"]["id"], admin_headers)
        # The PRD doesn't pin the exact error_id here (could be ERR_INVALID_STATE),
        # but the call must NOT succeed and the cycle must remain IN_REVIEW.
        assert resp.status_code >= 400, "lock must fail when not all reviews are LOCKED"
        body = resp.json()
        assert body["response_type"] == "error"
        # cycle still IN_REVIEW
        cycle = validate_success(api.get_cycle(s["cycle"]["id"], admin_headers))
        assert cycle["status"] == "IN_REVIEW"
