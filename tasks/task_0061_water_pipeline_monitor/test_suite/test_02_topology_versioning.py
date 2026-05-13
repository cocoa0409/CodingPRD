"""Topology versioning, governance, and segregation of duties.

Covers PRD §3.2 (TopologyVersion DRAFT → UNDER_REVIEW → PUBLISHED /
REJECTED), SoD on approve/reject, dangling-reference rules on segments,
and the rollback lifecycle.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS, build_user_headers,
    TA, TA_ALT, TE, TE_ALT, CO,
    add_node, add_segment, approve_topology, create_dma,
    create_draft_topology, create_network, get_network,
    iso_z, post_reading, submit_topology,
    create_topology_version_payload, create_node_payload,
    create_segment_payload,
    setup_published_network_with_one_segment,
    setup_under_review_version, setup_two_published_versions,
    setup_v2_removes_node_with_device_and_alert,
    make_topology_engineer_headers, make_topology_approver_headers,
    validate_error, validate_success,
)


class TestTopologyVersionCreation:

    def test_first_draft_version_number_one(self, api):
        """PRD §3.2: "version_number is assigned monotonically per
        network, starting at 1 on the first draft."

        Claim: the very first draft has version_number == 1.
        """
        net = create_network(api)
        version = create_draft_topology(api, net["id"])
        assert version["status"] == "DRAFT"
        assert version["version_number"] == 1

    def test_second_draft_increments_version_number(self, api):
        """PRD §3.2: "version_number is assigned monotonically per
        network, starting at 1 on the first draft."
        """
        net = create_network(api)
        v1 = create_draft_topology(api, net["id"])
        v2 = create_draft_topology(api, net["id"],
                                   parent_version_id=v1["id"])
        assert v2["version_number"] == v1["version_number"] + 1


class TestSegmentDanglingReference:

    def test_segment_with_unknown_endpoint_rejected(self, api):
        """PRD §3.2: "A segment endpoint that does not resolve to a node
        in the same topology version, or a segment with identical
        from_node_code and to_node_code, is rejected with
        ERR_TOPOLOGY_DANGLING_REFERENCE and HTTP 422."

        Claim: posting a segment with from_node_code that does not exist
        in the version → ERR_TOPOLOGY_DANGLING_REFERENCE.
        """
        net = create_network(api)
        dma = create_dma(api, net["id"])
        version = create_draft_topology(api, net["id"])
        j_known = add_node(api, net["id"], version["id"],
                           dma_id=dma["id"], kind="JUNCTION")
        payload = create_segment_payload(
            from_node_code="UNKNOWN-CODE",
            to_node_code=j_known["node_code"],
        )
        resp = api.create_segment(net["id"], version["id"], payload, TE)
        validate_error(resp,
                       ApiErrorId.ERR_TOPOLOGY_DANGLING_REFERENCE.value)

    def test_segment_with_equal_from_and_to_rejected(self, api):
        """PRD §3.2: "A segment endpoint that does not resolve to a node
        in the same topology version, or a segment with identical
        from_node_code and to_node_code, is rejected with
        ERR_TOPOLOGY_DANGLING_REFERENCE and HTTP 422."
        """
        net = create_network(api)
        dma = create_dma(api, net["id"])
        version = create_draft_topology(api, net["id"])
        j = add_node(api, net["id"], version["id"],
                     dma_id=dma["id"], kind="JUNCTION")
        payload = create_segment_payload(
            from_node_code=j["node_code"],
            to_node_code=j["node_code"],
        )
        resp = api.create_segment(net["id"], version["id"], payload, TE)
        validate_error(resp,
                       ApiErrorId.ERR_TOPOLOGY_DANGLING_REFERENCE.value)


class TestSubmitTopology:

    def test_happy_path_draft_to_under_review(self, api):
        """PRD §3.2: "A TopologyEngineer submits a draft for review,
        transitioning the version from DRAFT to UNDER_REVIEW."

        Claim: a fully-formed draft submits successfully and status flips.
        """
        env = setup_under_review_version(api)
        assert env["version"]["status"] == "UNDER_REVIEW"


class TestApproveTopology:

    def test_approver_must_differ_from_submitter(self, api):
        """PRD §2.1: "the TopologyApprover who approves or rejects a
        TopologyVersion must not be the same X-User-ID recorded in that
        version's submitted_by."

        PRD §5 maps ERR_SEGREGATION_OF_DUTIES to HTTP 403.
        Claim: approving as the same opaque X-User-ID as the submitter →
        ERR_SEGREGATION_OF_DUTIES.
        """
        env = setup_under_review_version(api)
        # Build approver headers with the SAME opaque id used by the
        # submitter (USER_IDS['topology_engineer']) but with the
        # TopologyApprover role; PRD §2.1 SoD is on X-User-ID only.
        clash_headers = build_user_headers(
            USER_IDS["topology_engineer"], "TopologyApprover",
        )
        resp = api.approve_topology_version(
            env["network"]["id"], env["version"]["id"], clash_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_happy_path_under_review_to_published(self, api):
        """PRD §3.2: "Approval by a TopologyApprover transitions the
        version from UNDER_REVIEW to PUBLISHED."
        """
        env = setup_under_review_version(api)
        resp = api.approve_topology_version(
            env["network"]["id"], env["version"]["id"], TA,
        )
        approved = validate_success(resp, expected_status=200)
        assert approved["status"] == "PUBLISHED"

    def test_approve_repoints_network_active_topology(self, api):
        """PRD §3.2: "the network's active_topology_version_id is
        repointed to the newly approved version."
        """
        base = setup_published_network_with_one_segment(api)
        # Network.active_topology_version_id must now be the just-approved
        # version.
        net = get_network(api, base["network"]["id"])
        assert net["active_topology_version_id"] == base["version"]["id"]

    def test_approving_v2_supersedes_v1(self, api):
        """PRD §3.2: "any other version of the same network that was
        previously in PUBLISHED status transitions to SUPERSEDED."
        """
        env = setup_two_published_versions(api)
        # Fetch V1 fresh to confirm it transitioned.
        resp = api.get_topology_version(env["network"]["id"],
                                        env["v1"]["id"], TA)
        v1 = validate_success(resp)
        assert v1["status"] == "SUPERSEDED"
        assert env["v2"]["status"] == "PUBLISHED"


class TestRejectTopology:

    def test_reject_requires_non_empty_reason(self, api):
        """PRD §3.2: "the request body must supply a non-empty
        rejection_reason."

        Claim: rejecting with an empty reason → ERR_BAD_REQUEST.
        """
        env = setup_under_review_version(api)
        resp = api.reject_topology_version(
            env["network"]["id"], env["version"]["id"],
            {"rejection_reason": ""}, TA,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_reject_happy_path(self, api):
        """PRD §3.2: "Rejection by a TopologyApprover transitions the
        version from UNDER_REVIEW to REJECTED."
        """
        env = setup_under_review_version(api)
        resp = api.reject_topology_version(
            env["network"]["id"], env["version"]["id"],
            {"rejection_reason": "needs more nodes"}, TA,
        )
        rejected = validate_success(resp)
        assert rejected["status"] == "REJECTED"


class TestTopologyApprovalCascade:
    """Difficulty design: topology_approval_three_hop_cascade."""

    def test_v2_approval_cascades_to_device_and_alert(self, api):
        """PRD §3.2: "any Device whose mounted_on_node_code no longer
        exists in the new active version transitions back to PROVISIONED
        with its mounted_on_node_code cleared."
        PRD §3.2: "any open Alert whose trigger_device_id is on a
        pipeline segment that has been removed in the new version
        transitions to SUPPRESSED with resolution_note='TOPOLOGY_SUPERSEDED'."

        # difficulty: transitive_cascade/topology_approval_three_hop_cascade
        Claim: approving V2 (which removes J1) cascades to DV1 (→
        PROVISIONED, mount cleared) and A1 (→ SUPPRESSED).
        """
        env = setup_v2_removes_node_with_device_and_alert(api)
        # Approve V2 with TA (distinct from the TE submitter — SoD ok).
        resp = api.approve_topology_version(
            env["network"]["id"], env["v2"]["id"], TA,
        )
        validate_success(resp)

        # Verify Device cascaded back to PROVISIONED.
        dev_resp = api.get_device(env["network"]["id"], env["device"]["id"],
                                  CO)
        dev = validate_success(dev_resp)
        assert dev["status"] == "PROVISIONED", \
            f"Device should revert to PROVISIONED after V2 removed its mount; got {dev['status']!r}"
        assert dev.get("mounted_on_node_code") in (None, "", ), \
            f"Device.mounted_on_node_code should be cleared; got {dev.get('mounted_on_node_code')!r}"

        # Verify Alert cascaded to SUPPRESSED.
        alert_resp = api.get_alert(env["network"]["id"],
                                   env["alert"]["id"], CO)
        alert = validate_success(alert_resp)
        assert alert["status"] == "SUPPRESSED", \
            f"Alert should be SUPPRESSED after segment removed; got {alert['status']!r}"


class TestRollback:
    """PRD §3.2 rollback lifecycle."""

    def test_rollback_re_publishes_v1_and_supersedes_v2(self, api):
        """PRD §3.2: "the current PUBLISHED version transitions to
        SUPERSEDED, the target version transitions from SUPERSEDED to
        PUBLISHED, and the network's active_topology_version_id is
        repointed."

        # difficulty: non_linear_state_machine/topology_version_cycle_rollback
        # difficulty: compensating_invariant/topology_rollback_preserves_active_version_count
        Claim: rollback flips V1 → PUBLISHED and V2 → SUPERSEDED and
        re-points the network. PRD invariant: count(PUBLISHED) stays at 1.
        """
        env = setup_two_published_versions(api)
        net_id = env["network"]["id"]
        v1_id = env["v1"]["id"]
        v2_id = env["v2"]["id"]

        resp = api.rollback_topology_version(net_id, v1_id, TA)
        validate_success(resp)

        v1 = validate_success(
            api.get_topology_version(net_id, v1_id, TA),
        )
        v2 = validate_success(
            api.get_topology_version(net_id, v2_id, TA),
        )
        net = get_network(api, net_id)

        assert v1["status"] == "PUBLISHED"
        assert v2["status"] == "SUPERSEDED"
        assert net["active_topology_version_id"] == v1_id

    def test_rollback_keeps_published_count_at_one(self, api):
        """PRD §3.2: "the current PUBLISHED version transitions to
        SUPERSEDED, the target version transitions from SUPERSEDED to
        PUBLISHED, and the network's active_topology_version_id is
        repointed."

        # difficulty: compensating_invariant/topology_rollback_preserves_active_version_count
        Conserved quantity: COUNT(status=PUBLISHED for this Network) ==
        1 before AND after rollback. PRD prose pins the cycle: forward
        action plus compensating action net to zero change.
        """
        env = setup_two_published_versions(api)
        net_id = env["network"]["id"]
        v1_id = env["v1"]["id"]
        v2_id = env["v2"]["id"]

        # Pre: exactly one PUBLISHED (V2).
        v1_pre = validate_success(
            api.get_topology_version(net_id, v1_id, TA),
        )
        v2_pre = validate_success(
            api.get_topology_version(net_id, v2_id, TA),
        )
        pre_published = sum(1 for v in (v1_pre, v2_pre)
                            if v["status"] == "PUBLISHED")
        assert pre_published == 1

        api.rollback_topology_version(net_id, v1_id, TA)

        v1_post = validate_success(
            api.get_topology_version(net_id, v1_id, TA),
        )
        v2_post = validate_success(
            api.get_topology_version(net_id, v2_id, TA),
        )
        post_published = sum(1 for v in (v1_post, v2_post)
                             if v["status"] == "PUBLISHED")
        assert post_published == 1, \
            f"PUBLISHED count should remain 1 post-rollback, got {post_published}"


class TestApproveRejectStateValidation:
    """Priority-pair: state vs business_safety on approve (DRAFT version).

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_conflict_on_approve
    """

    def test_approve_draft_returns_invalid_state(self, api):
        """PRD §3.10: priority order places state ("ERR_INVALID_STATE")
        ahead of business_safety ("ERR_SEGREGATION_OF_DUTIES").
        PRD §3.2: approve "transitions the version from UNDER_REVIEW to
        PUBLISHED" — DRAFT is therefore not a valid from-state.

        Claim: approving a DRAFT version with X-User-ID identical to the
        notional submitter still returns ERR_INVALID_STATE (state check
        wins because V1.status != UNDER_REVIEW).
        """
        net = create_network(api)
        # DRAFT version with no submitted_by yet.
        version = create_draft_topology(api, net["id"])
        # Try to approve with X-User-ID that would clash if it had been
        # submitted by that id; state check must fire first.
        clash_headers = build_user_headers(
            USER_IDS["topology_engineer"], "TopologyApprover",
        )
        resp = api.approve_topology_version(
            net["id"], version["id"], clash_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
