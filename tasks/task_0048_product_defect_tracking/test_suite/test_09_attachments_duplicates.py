"""DefectAttachment uploads (per-type size caps), DuplicateLink invariants."""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ATTACHMENT_SIZE_CAP,
    ApiErrorId,
    api_client,
    assert_attachment,
    assert_duplicate_link,
    attachment_payload,
    create_defect,
    duplicate_link_payload,
    fetch_defect,
    setup_basic_module,
    setup_defect_in_state,
)


class TestAttachmentSizeCaps:
    @pytest.mark.parametrize("attachment_type,limit_bytes", [
        ("SCREENSHOT", 5_242_880),    # 5 MB
        ("LOG", 10_485_760),          # 10 MB
        ("VIDEO", 209_715_200),       # 200 MB
    ])
    def test_attachment_at_limit_accepted(self, attachment_type, limit_bytes):
        """PRD §3.11: "Per-type size caps are enforced: a SCREENSHOT may
        be at most 5 megabytes (5,242,880 bytes), a LOG may be at most
        10 megabytes (10,485,760 bytes), and a VIDEO may be at most 200
        megabytes (209,715,200 bytes)".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        resp = api_client.upload_attachment(
            defect["id"],
            attachment_payload(
                attachment_type=attachment_type,
                filename=f"file.{attachment_type.lower()}",
                size_bytes=limit_bytes,
            ),
            team.developer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_attachment(data)
        assert data["size_bytes"] == limit_bytes

    @pytest.mark.parametrize("attachment_type,limit_bytes", [
        ("SCREENSHOT", 5_242_880),
        ("LOG", 10_485_760),
        ("VIDEO", 209_715_200),
    ])
    def test_attachment_one_byte_over_limit_rejected(
        self, attachment_type, limit_bytes,
    ):
        """PRD §3.11: "an upload exceeding the cap is rejected with
        ERR_ATTACHMENT_TOO_LARGE."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        resp = api_client.upload_attachment(
            defect["id"],
            attachment_payload(
                attachment_type=attachment_type,
                filename=f"file.{attachment_type.lower()}",
                size_bytes=limit_bytes + 1,
            ),
            team.developer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ATTACHMENT_TOO_LARGE.value)


class TestDuplicateLinkInvariants:
    def test_self_link_rejected(self):
        """PRD §3.11: "the duplicate_defect_id must not equal the
        canonical_defect_id (no self-link)".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        resp = api_client.create_duplicate_link(
            duplicate_link_payload(
                duplicate_defect_id=defect["id"],
                canonical_defect_id=defect["id"],
                similarity_score=0.9,
            ),
            team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_DUPLICATE_LINK.value,
        )

    def test_similarity_below_threshold_rejected(self):
        """PRD §3.11: "the similarity_score must be at least 0.5 (scores
        below 0.5 are rejected as too weak to justify the link)".
        """
        team, module = setup_basic_module()
        d1 = create_defect(team, module, title="dup")
        d2 = create_defect(team, module, title="canonical")
        resp = api_client.create_duplicate_link(
            duplicate_link_payload(
                duplicate_defect_id=d1["id"],
                canonical_defect_id=d2["id"],
                similarity_score=0.49,
            ),
            team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_DUPLICATE_LINK.value,
        )

    def test_link_when_duplicate_not_new_rejected(self):
        """PRD §3.11: "the duplicate defect must currently be in status
        NEW".
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        d_canonical = create_defect(team, module, title="canonical")
        # Drive d1 out of NEW.
        d_assigned = setup_defect_in_state(team, module, "ASSIGNED")
        resp = api_client.create_duplicate_link(
            duplicate_link_payload(
                duplicate_defect_id=d_assigned["id"],
                canonical_defect_id=d_canonical["id"],
                similarity_score=0.9,
            ),
            team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_DUPLICATE_LINK.value,
        )

    def test_successful_duplicate_link_sets_canonical_id(self):
        """PRD §3.11: "On a successful link the duplicate defect's
        canonical_defect_id is set to the canonical defect's id, and the
        duplicate defect retains its NEW status".
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        d_dup = create_defect(team, module, title="dup")
        d_canon = create_defect(team, module, title="canonical")
        resp = api_client.create_duplicate_link(
            duplicate_link_payload(
                duplicate_defect_id=d_dup["id"],
                canonical_defect_id=d_canon["id"],
                similarity_score=0.9,
            ),
            team.triage_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_duplicate_link(data)
        d_dup_after = fetch_defect(team, d_dup["id"])
        assert d_dup_after["canonical_defect_id"] == d_canon["id"]
        assert d_dup_after["status"] == "NEW"

    def test_chained_duplicate_link_rejected(self):
        """PRD §3.11: "the canonical defect itself must not already be a
        duplicate of something else — that is, its own
        canonical_defect_id must be null (no chained duplicate links)".
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        a = create_defect(team, module, title="A")
        b = create_defect(team, module, title="B")
        c = create_defect(team, module, title="C")
        # Link B -> A (B is dup, A is canonical).
        api_client.create_duplicate_link(
            duplicate_link_payload(
                duplicate_defect_id=b["id"],
                canonical_defect_id=a["id"],
                similarity_score=0.9,
            ),
            team.triage_headers,
        )
        # Try to link C -> B (B's canonical_defect_id is now non-null).
        resp = api_client.create_duplicate_link(
            duplicate_link_payload(
                duplicate_defect_id=c["id"],
                canonical_defect_id=b["id"],
                similarity_score=0.9,
            ),
            team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_DUPLICATE_LINK.value,
        )
