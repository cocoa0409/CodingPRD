"""Notice publish/retract protocol: half-open windows, depth-4 cascade,
retraction compensation, per-scope published-count conservation (PRD §3.2)."""
from test_helpers import (
    BO1,
    DS,
    LC1,
    PA,
    assert_notice,
    create_active_activity,
    create_element,
    create_notice_payload,
    create_published_notice,
    create_retention_policy,
    create_transfer_payload,
    get_success_data,
    publish_superseding_notice,
    setup_notice_supersede_landscape,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)


class TestNoticeWindows:
    def test_notice_window_half_open_adjacency(self, api):
        """PRD §3.2: "The publication window is half-open — effective_from is
        inclusive, effective_to is exclusive — and two notices whose windows
        share only a boundary instant are adjacent, not overlapping, and do not
        conflict."
        PRD §3.2: "If another PUBLISHED notice in the same scope has a window
        that overlaps this one, and that notice is not the declared
        supersedes_notice_id target, the publish is rejected with
        ERR_NOTICE_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/notice_window_half_open_adjacency
        """
        n1 = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="n1",
                                  effective_from="2026-01-01T00:00:00Z",
                                  effective_to="2027-01-01T00:00:00Z"), PA))
        n2 = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="n2",
                                  effective_from="2027-01-01T00:00:00Z",
                                  effective_to="2028-01-01T00:00:00Z"), PA))
        n3 = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="n3",
                                  effective_from="2026-06-01T00:00:00Z",
                                  effective_to="2026-09-01T00:00:00Z"), PA))

        assert get_success_data(api.publish_notice(n1["id"], PA))["status"] == "PUBLISHED"
        # adjacency at 2027-01-01T00:00:00Z is not overlap under half-open semantics
        assert get_success_data(api.publish_notice(n2["id"], PA))["status"] == "PUBLISHED"

        resp = api.publish_notice(n3["id"], PA)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_OVERLAP)
        after = get_success_data(api.get_notice(n3["id"], PA))
        assert after["status"] == "DRAFT", "a rejected publish leaves the notice DRAFT"

    def test_notice_overlap_rejected_while_other_scope_allows_same_window(self, api):
        """PRD §3.2: "If another PUBLISHED notice in the same scope has a window
        that overlaps this one, and that notice is not the declared
        supersedes_notice_id target, the publish is rejected with
        ERR_NOTICE_WINDOW_OVERLAP."
        PRD §3.2: "When all checks pass, the notice's status becomes PUBLISHED,
        published_at is set to the logical clock, and the notice's version
        increments."

        Design: Difficulty/resource_temporal_overlap/notice_window_half_open_adjacency
        """
        n1 = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="w1",
                                  effective_from="2026-01-01T00:00:00Z",
                                  effective_to="2027-01-01T00:00:00Z"), PA))
        get_success_data(api.publish_notice(n1["id"], PA))

        # Overlapping window in a DIFFERENT scope publishes fine.
        other_scope = get_success_data(api.create_notice(
            create_notice_payload(scope="EMPLOYEE", title="e1",
                                  effective_from="2026-01-01T00:00:00Z",
                                  effective_to="2027-01-01T00:00:00Z"), PA))
        assert get_success_data(api.publish_notice(other_scope["id"], PA))["status"] == "PUBLISHED"

        # Overlapping window in the SAME scope (WEBSITE) without a supersede
        # target is rejected.
        overlapping = get_success_data(api.create_notice(
            create_notice_payload(scope="WEBSITE", title="w2",
                                  effective_from="2026-06-01T00:00:00Z",
                                  effective_to="2028-01-01T00:00:00Z"), PA))
        resp = api.publish_notice(overlapping["id"], PA)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_OVERLAP)
        assert get_success_data(api.get_notice(overlapping["id"], PA))["status"] == "DRAFT"


class TestNoticePublishCascade:
    def test_notice_publish_cascade_depth4(self, api):
        """PRD §3.2: "If supersedes_notice_id was declared, that target notice
        transitions to SUPERSEDED with its superseded_by_notice_id set to the
        newly published notice's id. Every Purpose whose pinned_notice_id equals
        the superseded notice's id and whose status is DOCUMENTED transitions to
        CONSENT_STALE, processed in created_at ascending order. Every
        ProcessingActivity that owns at least one such stale purpose and whose
        status is ACTIVE transitions to COMPLIANCE_HOLD. Every
        CrossBorderTransfer whose activity_id is one of those held activities
        and whose status is APPROVED transitions to SUSPENDED with
        suspension_reason set to ACTIVITY_HOLD."

        Design: Difficulty/transitive_cascade/notice_publish_cascade_depth4
        """
        landscape = setup_notice_supersede_landscape()
        n1, purpose, activity, transfer = (landscape["n1"], landscape["purpose"],
                                           landscape["activity"], landscape["transfer"])
        assert purpose["pinned_notice_id"] == n1["id"]

        n2 = publish_superseding_notice(n1["id"])

        n1_after = get_success_data(api.get_notice(n1["id"], PA))
        assert n1_after["status"] == "SUPERSEDED"
        assert n1_after["superseded_by_notice_id"] == n2["id"]

        p_after = get_success_data(api.get_purpose(purpose["id"], DS))
        assert p_after["status"] == "CONSENT_STALE", (
            "hop 2: purpose pinned to the superseded notice goes stale"
        )

        a_after = get_success_data(api.get_activity(activity["id"], DS))
        assert a_after["status"] == "COMPLIANCE_HOLD", (
            "hop 3: the ACTIVE activity owning a stale purpose is held"
        )

        t_after = get_success_data(api.get_transfer(transfer["id"], LC1))
        assert t_after["status"] == "SUSPENDED"
        assert t_after["suspension_reason"] == "ACTIVITY_HOLD", (
            "hop 4: the APPROVED transfer on the held activity is suspended"
        )

    def test_notice_publish_cascade_multiple_purposes_all_stale(self, api):
        """PRD §3.2: "Every Purpose whose pinned_notice_id equals the superseded
        notice's id and whose status is DOCUMENTED transitions to CONSENT_STALE,
        processed in created_at ascending order."
        PRD §2.9: "Whenever this document describes a cascade, every entity
        touched by the cascade — including the root entity whose state changed —
        has its version incremented by exactly 1 and its updated_at refreshed."

        Design: Difficulty/transitive_cascade/notice_publish_cascade_depth4
        """
        from test_helpers import create_activity_payload, create_purpose_payload
        policy = create_retention_policy()
        element = create_element()
        n1 = create_published_notice(scope="WEBSITE", title="v1")

        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="CRM", business_unit="Sales",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[element["id"]]), DS))
        p1 = get_success_data(api.create_purpose(
            activity["id"], create_purpose_payload(
                purpose_type="MARKETING", legal_basis="CONSENT",
                retention_policy_id=policy["id"]), DS))
        p2 = get_success_data(api.create_purpose(
            activity["id"], create_purpose_payload(
                purpose_type="ANALYTICS", legal_basis="CONSENT",
                retention_policy_id=policy["id"]), DS))
        p3 = get_success_data(api.create_purpose(
            activity["id"], create_purpose_payload(
                purpose_type="SERVICE_DELIVERY", legal_basis="CONTRACT",
                retention_policy_id=policy["id"]), DS))
        get_success_data(api.activate_activity(activity["id"], DS))
        assert p1["pinned_notice_id"] == n1["id"]
        assert p2["pinned_notice_id"] == n1["id"]
        assert p3["pinned_notice_id"] is None, "non-CONSENT purposes pin nothing"
        v1, v3 = p1["version"], p3["version"]

        publish_superseding_notice(n1["id"])

        p1_after = get_success_data(api.get_purpose(p1["id"], DS))
        p2_after = get_success_data(api.get_purpose(p2["id"], DS))
        p3_after = get_success_data(api.get_purpose(p3["id"], DS))
        assert p1_after["status"] == "CONSENT_STALE"
        assert p2_after["status"] == "CONSENT_STALE"
        assert p3_after["status"] == "DOCUMENTED", (
            "the CONTRACT purpose has no pinned notice and is untouched by the cascade"
        )
        assert p1_after["version"] == v1 + 1, "each touched purpose gains exactly one version"
        assert p3_after["version"] == v3

        a_after = get_success_data(api.get_activity(activity["id"], DS))
        assert a_after["status"] == "COMPLIANCE_HOLD"


class TestNoticeRetractCompensation:
    def test_notice_publish_retract_conserves_published_count(self, api):
        """PRD §3.2: "When a PrivacyAdmin retracts a PUBLISHED notice, the
        retracted notice's status becomes RETRACTED. The notice that this one
        superseded — identified by its superseded_by_notice_id pointing back to
        the retracted notice — is restored to PUBLISHED if it is still
        SUPERSEDED."
        PRD §3.2: "When all checks pass, the notice's status becomes PUBLISHED,
        published_at is set to the logical clock, and the notice's version
        increments."

        Design: Difficulty/compensating_invariant/notice_publish_retract_conserves_published_count
        """
        n_a = get_success_data(api.create_notice(
            create_notice_payload(scope="LOYALTY_PROGRAM", title="loyalty v1",
                                  effective_from="2026-01-01T00:00:00Z",
                                  effective_to="2027-01-01T00:00:00Z"), PA))
        get_success_data(api.publish_notice(n_a["id"], PA))
        published, _ = validate_paginated(api.list_notices(
            PA, params={"scope": "LOYALTY_PROGRAM", "status": "PUBLISHED"}))
        assert [n["id"] for n in published] == [n_a["id"]], (
            "after publish(n_a): exactly one PUBLISHED notice in scope"
        )

        n_b = get_success_data(api.create_notice(
            create_notice_payload(scope="LOYALTY_PROGRAM", title="loyalty v2",
                                  effective_from="2026-06-01T00:00:00Z",
                                  effective_to="2028-01-01T00:00:00Z",
                                  supersedes_notice_id=n_a["id"]), PA))
        get_success_data(api.publish_notice(n_b["id"], PA))
        published, _ = validate_paginated(api.list_notices(
            PA, params={"scope": "LOYALTY_PROGRAM", "status": "PUBLISHED"}))
        assert [n["id"] for n in published] == [n_b["id"]], (
            "after publish(n_b superseding n_a): still exactly one PUBLISHED"
        )

        get_success_data(api.retract_notice(n_b["id"], PA))
        published, _ = validate_paginated(api.list_notices(
            PA, params={"scope": "LOYALTY_PROGRAM", "status": "PUBLISHED"}))
        assert [n["id"] for n in published] == [n_a["id"]], (
            "after retract(n_b): exactly one PUBLISHED and it is n_a again"
        )

    def test_retract_restores_purposes_and_resumes_activity(self, api):
        """PRD §3.2: "Every Purpose in CONSENT_STALE whose pinned_notice_id is
        the restored notice's id transitions back to DOCUMENTED, in created_at
        ascending order. Every ProcessingActivity in COMPLIANCE_HOLD that now has
        zero purposes in CONSENT_STALE and zero assessments in TRIGGERED,
        IN_REVIEW, or CHANGES_REQUESTED transitions back to ACTIVE. Every
        CrossBorderTransfer in SUSPENDED with suspension_reason equal to
        ACTIVITY_HOLD whose owning activity just resumed transitions back to
        APPROVED with suspension_reason cleared to null. Retraction therefore
        unwinds the staleness cascade that publication introduced."

        Design: Difficulty/compensating_invariant/notice_publish_retract_conserves_published_count
        """
        landscape = setup_notice_supersede_landscape()
        n1, purpose, activity, transfer = (landscape["n1"], landscape["purpose"],
                                           landscape["activity"], landscape["transfer"])
        n2 = publish_superseding_notice(n1["id"])

        # Mid-state: cascade has run.
        assert get_success_data(api.get_purpose(purpose["id"], DS))["status"] == "CONSENT_STALE"
        assert get_success_data(api.get_activity(activity["id"], DS))["status"] == "COMPLIANCE_HOLD"
        assert get_success_data(api.get_transfer(transfer["id"], LC1))["status"] == "SUSPENDED"

        retracted = get_success_data(api.retract_notice(n2["id"], PA))
        assert retracted["status"] == "RETRACTED"

        n1_after = get_success_data(api.get_notice(n1["id"], PA))
        assert n1_after["status"] == "PUBLISHED", "the superseded predecessor is restored"

        p_after = get_success_data(api.get_purpose(purpose["id"], DS))
        assert p_after["status"] == "DOCUMENTED"

        a_after = get_success_data(api.get_activity(activity["id"], DS))
        assert a_after["status"] == "ACTIVE"

        t_after = get_success_data(api.get_transfer(transfer["id"], LC1))
        assert t_after["status"] == "APPROVED"
        assert t_after["suspension_reason"] is None
