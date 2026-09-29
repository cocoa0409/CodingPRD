"""The posture axis: exposure points, open audits, overrides and the escalation cascade."""

from test_helpers import (
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    add_design_factor,
    api_client,
    assert_design_score,
    assert_instant,
    assert_service_posture_ladder,
    create_integration,
    mixed_audience_service,
    published_notice,
    read_integration,
    read_service,
    run_determination,
    set_integration_status,
    set_posture_override,
    validate_error,
)


class TestServiceParallelAxes:
    """The determination axis and the posture axis move independently on the same row."""

    def test_01_override_moves_the_posture_without_touching_the_determination(self):
        """A manual override changes only the posture axis.

        "An `OnlineService` row carries two enumerated state fields that evolve
        independently of one another, on the same row, at the same time", and the
        determination axis "is written by exactly one operation — the determination run
        described in §3.2 — and by nothing else." While the override is non-null it "wins
        over the computation outright."

        Design: Difficulty/non_linear_state_machine/service_parallel_axes_move_independently
        """
        service = mixed_audience_service(name="Parallel Axes Service")
        assert service["determination_status"] == "MIXED_AUDIENCE"

        overridden = set_posture_override(service["id"], "RESTRICTED")

        assert overridden["posture_override"] == "RESTRICTED"
        assert overridden["compliance_posture"] == "RESTRICTED", (
            "a non-null override is exactly the posture, got "
            f"{overridden['compliance_posture']}"
        )
        assert overridden["determination_status"] == "MIXED_AUDIENCE", (
            "setting the posture override must leave the determination axis alone, got "
            f"{overridden['determination_status']}"
        )

    def test_02_appending_evidence_refreshes_the_score_but_not_the_determination(self):
        """Fresh evidence changes the computed score while the conclusion waits.

        "Appending evidence immediately refreshes the service's `design_score` and
        `audience_child_share` and advances the service's `version` by one — but it
        deliberately does **not** change `determination_status`." Only the latest row per
        factor code participates, so a second `SUBJECT_MATTER` row replaces the first.

        Design: Difficulty/non_linear_state_machine/service_parallel_axes_move_independently
        """
        service = mixed_audience_service(name="Evidence Refresh Service")
        set_posture_override(service["id"], "RESTRICTED")

        row = add_design_factor(service["id"], "SUBJECT_MATTER", "INCIDENTAL")

        assert row["evidence_sequence"] == 2, (
            f"the replacement factor row is the second row, got {row['evidence_sequence']}"
        )
        refreshed = read_service(service["id"])
        assert_design_score(refreshed, 0.25)
        assert refreshed["determination_status"] == "MIXED_AUDIENCE", (
            "appending evidence must not move the determination axis, got "
            f"{refreshed['determination_status']}"
        )

    def test_03_re_determination_moves_backwards_while_the_override_holds_the_posture(self):
        """The determination axis may move backwards; the override keeps the posture put.

        "A determination run may move the axis between any pair of its values, so a
        service that was `CHILD_DIRECTED_PRIMARY` can be re-determined down to
        `GENERAL_AUDIENCE` when fresh evidence supports it." Meanwhile clause 1 of the
        posture computation still reads "If `posture_override` is not null, the posture is
        exactly that override value."

        Design: Difficulty/non_linear_state_machine/service_parallel_axes_move_independently
        """
        service = mixed_audience_service(name="Backward Determination Service")
        set_posture_override(service["id"], "RESTRICTED")
        add_design_factor(service["id"], "SUBJECT_MATTER", "INCIDENTAL")

        re_determined = run_determination(service["id"])

        assert re_determined["determination_status"] == "GENERAL_AUDIENCE", (
            "a score of 0.25 re-determines the service down to GENERAL_AUDIENCE, got "
            f"{re_determined['determination_status']}"
        )
        assert re_determined["compliance_posture"] == "RESTRICTED", (
            "the override still governs the posture, got "
            f"{re_determined['compliance_posture']}"
        )
        assert re_determined["posture_override"] == "RESTRICTED"

    def test_04_clearing_the_override_hands_the_posture_back_to_the_computation(self):
        """Clearing the override returns the posture to the computed value.

        `posture_override` is "one of `OPEN`, `RESTRICTED`, `FROZEN`, or null to hand
        control back to the computation", after which "Otherwise, the posture is `OPEN`"
        applies to a service with no exposure, no open audits and no lapse.

        Design: Difficulty/non_linear_state_machine/service_parallel_axes_move_independently
        """
        service = mixed_audience_service(name="Cleared Override Service")
        set_posture_override(service["id"], "RESTRICTED")
        add_design_factor(service["id"], "SUBJECT_MATTER", "INCIDENTAL")
        run_determination(service["id"])

        cleared = set_posture_override(service["id"], None)

        assert cleared["posture_override"] is None, (
            f"the override must be cleared to null, got {cleared['posture_override']}"
        )
        assert cleared["compliance_posture"] == "OPEN", (
            f"the computed posture is OPEN, got {cleared['compliance_posture']}"
        )
        assert cleared["determination_status"] == "GENERAL_AUDIENCE"
        assert cleared["determination_variant_applied"] == "DESIGN_FIRST"
        assert_design_score(cleared, 0.25)


class TestExposurePointBoundaries:
    """Only approved integrations contribute, and exactly forty points restricts."""

    def test_05_a_declared_and_audited_integration_contributes_nothing(self):
        """Points join the total only once the integration is approved.

        "The service's `third_party_exposure_points` is the sum of `exposure_points` over
        only those of its integrations whose `status` is `APPROVED`. Integrations that are
        `DECLARED`, `AUDIT_PENDING` or `BLOCKED` contribute nothing". While the audit is
        open, clause 3 of the posture computation restricts the service.

        Design: Difficulty/boundary_precision_check/exposure_points_exact_forty_restricts_and_zero_point_cdn_does_not
        """
        service = mixed_audience_service(name="Exposure Boundary Service")
        published_notice(service["id"], disclosed_integration_vendors=["SocialGram Widget"])
        integration = create_integration(
            service["id"],
            vendor_name="SocialGram Widget",
            integration_type="SOCIAL_PLUGIN",
            collects_persistent_identifier=False,
            placement_area="GENERAL_AREA",
        )

        assert integration["exposure_points"] == 25, (
            "a SOCIAL_PLUGIN without a persistent identifier carries 25 points, got "
            f"{integration['exposure_points']}"
        )
        declared_service = read_service(service["id"])
        assert declared_service["third_party_exposure_points"] == 0, (
            "a freshly declared integration raises the total by zero, got "
            f"{declared_service['third_party_exposure_points']}"
        )

        set_integration_status(integration["id"], "AUDIT_PENDING")
        in_audit = read_service(service["id"])
        assert in_audit["third_party_exposure_points"] == 0
        assert in_audit["open_audit_count"] == 1
        assert in_audit["compliance_posture"] == "RESTRICTED", (
            "one open audit restricts the service, got "
            f"{in_audit['compliance_posture']}"
        )
        assert in_audit["audit_decision_count"] == 0, (
            "sending an integration into audit is not an audit decision, got "
            f"{in_audit['audit_decision_count']}"
        )

    def test_06_a_zero_point_cdn_approval_leaves_the_total_untouched(self):
        """A CDN carries no weight even when it collects a persistent identifier.

        Each integration's points are "the integration type's base weight —
        `BEHAVIORAL_AD_NETWORK` 40, `SOCIAL_PLUGIN` 25, `ANALYTICS` 15,
        `CONTEXTUAL_AD_NETWORK` 5 and `CDN` 0 — doubled when
        `collects_persistent_identifier` is true and taken as-is when it is false", which for
        a CDN is zero either way. Approval adds "this integration's `exposure_points`
        into the service's `third_party_exposure_points`".

        Design: Difficulty/boundary_precision_check/exposure_points_exact_forty_restricts_and_zero_point_cdn_does_not
        """
        service = mixed_audience_service(name="Zero Point CDN Service")
        published_notice(
            service["id"],
            disclosed_integration_vendors=["SocialGram Widget", "EdgeCache CDN"],
        )
        plugin = create_integration(
            service["id"],
            vendor_name="SocialGram Widget",
            integration_type="SOCIAL_PLUGIN",
            collects_persistent_identifier=False,
            placement_area="GENERAL_AREA",
        )
        set_integration_status(plugin["id"], "AUDIT_PENDING")
        set_integration_status(plugin["id"], "APPROVED")

        cdn = create_integration(
            service["id"],
            vendor_name="EdgeCache CDN",
            integration_type="CDN",
            collects_persistent_identifier=True,
            placement_area="GENERAL_AREA",
        )
        assert cdn["exposure_points"] == 0, (
            f"a CDN carries 0 exposure points, got {cdn['exposure_points']}"
        )
        set_integration_status(cdn["id"], "AUDIT_PENDING")
        set_integration_status(cdn["id"], "APPROVED")

        after = read_service(service["id"])
        assert after["third_party_exposure_points"] == 25, (
            "approving a zero-point CDN leaves the total at 25, got "
            f"{after['third_party_exposure_points']}"
        )
        assert after["compliance_posture"] == "OPEN", (
            f"25 points is below the restriction threshold, got {after['compliance_posture']}"
        )

    def test_07_a_total_of_exactly_forty_points_restricts_without_freezing(self):
        """Forty points restricts the service and does not freeze it.

        "Both numeric boundaries are inclusive: an exposure total of exactly 80 freezes
        the service, and an exposure total of exactly 40 restricts it." Every audit is
        closed, so clause 3 cannot be the reason.

        Design: Difficulty/boundary_precision_check/exposure_points_exact_forty_restricts_and_zero_point_cdn_does_not
        """
        service = mixed_audience_service(name="Exactly Forty Points Service")
        published_notice(
            service["id"],
            disclosed_integration_vendors=[
                "SocialGram Widget",
                "EdgeCache CDN",
                "MetricPulse",
            ],
        )
        for vendor, integration_type, persistent in (
            ("SocialGram Widget", "SOCIAL_PLUGIN", False),
            ("EdgeCache CDN", "CDN", True),
            ("MetricPulse", "ANALYTICS", False),
        ):
            integration = create_integration(
                service["id"],
                vendor_name=vendor,
                integration_type=integration_type,
                collects_persistent_identifier=persistent,
                placement_area="GENERAL_AREA",
            )
            set_integration_status(integration["id"], "AUDIT_PENDING")
            set_integration_status(integration["id"], "APPROVED")

        final = read_service(service["id"])
        assert final["third_party_exposure_points"] == 40, (
            "25 plus 0 plus 15 is exactly 40, got "
            f"{final['third_party_exposure_points']}"
        )
        assert final["open_audit_count"] == 0
        assert final["compliance_posture"] == "RESTRICTED", (
            "an exposure total of exactly 40 restricts the service, got "
            f"{final['compliance_posture']}"
        )
        assert final["audit_decision_count"] == 3, (
            "three accepted approvals are three audit decisions, got "
            f"{final['audit_decision_count']}"
        )
        assert final["determination_status"] == "MIXED_AUDIENCE"
        assert_service_posture_ladder(final)


class TestExposureReversesWhileAuditDecisionsAccumulate:
    """Points come and go; the count of decisions taken never does."""

    def test_08_approval_adds_points_and_records_one_decision(self):
        """Approval is the moment the points and the decision are both recorded.

        "A successful approval stamps `last_audit_decision_at` with the current
        logical-clock instant, advances the service's `audit_decision_count` by one, adds
        this integration's `exposure_points` into the service's
        `third_party_exposure_points`".

        Design: Difficulty/compensating_invariant/exposure_points_reverse_on_block_while_audit_decision_count_never_does
        """
        service = mixed_audience_service(name="Analytics Exposure Service")
        published_notice(service["id"], disclosed_integration_vendors=["MetricPulse"])
        integration = create_integration(
            service["id"],
            vendor_name="MetricPulse",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )

        assert integration["exposure_points"] == 30, (
            "an ANALYTICS integration collecting a persistent identifier carries 30 points, "
            f"got {integration['exposure_points']}"
        )
        assert integration["disclosed_in_notice"] is True, (
            "the published notice names this vendor, so disclosed_in_notice is true"
        )
        assert integration["status"] == "DECLARED"

        set_integration_status(integration["id"], "AUDIT_PENDING")
        approved = set_integration_status(integration["id"], "APPROVED")

        assert approved["exposure_points"] == 30
        assert_instant(
            approved["last_audit_decision_at"], STARTUP_CLOCK, "last_audit_decision_at"
        )
        after = read_service(service["id"])
        assert after["third_party_exposure_points"] == 30, (
            f"the approved points join the total, got {after['third_party_exposure_points']}"
        )
        assert after["open_audit_count"] == 0
        assert after["audit_decision_count"] == 1
        assert after["compliance_posture"] == "OPEN"

    def test_09_blocking_reverses_the_points_but_the_decision_count_only_grows(self):
        """A block withdraws the points from the total while counting as a decision.

        "`third_party_exposure_points` is recomputed so that a previously approved
        integration's points drop out of the total ... `audit_decision_count` therefore
        counts every accepted approval and every accepted block for the service and is
        monotonically non-decreasing". The integration keeps its own weight, because
        `exposure_points` is "computed from its declaration".

        Design: Difficulty/compensating_invariant/exposure_points_reverse_on_block_while_audit_decision_count_never_does
        """
        service = mixed_audience_service(name="Blocked Analytics Service")
        published_notice(service["id"], disclosed_integration_vendors=["MetricPulse"])
        integration = create_integration(
            service["id"],
            vendor_name="MetricPulse",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")

        blocked = set_integration_status(integration["id"], "BLOCKED")

        assert blocked["status"] == "BLOCKED"
        assert blocked["exposure_points"] == 30, (
            "the integration keeps the weight of its own declaration, got "
            f"{blocked['exposure_points']}"
        )
        after = read_service(service["id"])
        assert after["third_party_exposure_points"] == 0, (
            "a blocked integration's points drop out of the total, got "
            f"{after['third_party_exposure_points']}"
        )
        assert after["audit_decision_count"] == 2, (
            "one approval plus one block is two decisions, got "
            f"{after['audit_decision_count']}"
        )
        assert after["open_audit_count"] == 0
        assert after["compliance_posture"] == "OPEN"

    def test_10_a_blocked_integration_cannot_be_approved_directly(self):
        """Approval is reachable only from an open audit.

        "Clearing an audit — `AUDIT_PENDING → APPROVED` — is where the substantive checks
        live", and for a transition the current status does not permit "Where no more
        specific code applies the response is `ERR_INVALID_STATE`".

        Design: Difficulty/compensating_invariant/exposure_points_reverse_on_block_while_audit_decision_count_never_does
        """
        service = mixed_audience_service(name="Block Then Approve Service")
        published_notice(service["id"], disclosed_integration_vendors=["MetricPulse"])
        integration = create_integration(
            service["id"],
            vendor_name="MetricPulse",
            integration_type="ANALYTICS",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")
        set_integration_status(integration["id"], "BLOCKED")

        validate_error(
            api_client.set_third_party_integration_status(
                integration["id"], {"to_status": "APPROVED"}, OFFICER_HEADERS
            ),
            "ERR_INVALID_STATE",
        )

        after = read_service(service["id"])
        assert after["third_party_exposure_points"] == 0
        assert after["audit_decision_count"] == 2, (
            "a refused transition is not a decision, got "
            f"{after['audit_decision_count']}"
        )
        assert read_integration(service["id"], integration["id"])["status"] == "BLOCKED"


class TestDeterminationEscalationCascade:
    """An escalation to primary forces re-audit and then locks the override open."""

    def test_11_escalation_forces_child_directed_integrations_back_into_audit(self):
        """Landing on primary from an assessed status re-opens the audits.

        "every third-party integration of this service that is currently `APPROVED` and
        whose `placement_area` is `CHILD_DIRECTED_AREA` is moved `APPROVED →
        AUDIT_PENDING`, and each such integration's `audit_note` is set to `re-audit
        forced by child-directed determination`."

        Design: Difficulty/transitive_cascade/determination_escalation_forces_integration_reaudit_and_locks_override
        """
        service = mixed_audience_service(name="Escalating Service")
        published_notice(
            service["id"], disclosed_integration_vendors=["PlaySafe Contextual"]
        )
        integration = create_integration(
            service["id"],
            vendor_name="PlaySafe Contextual",
            integration_type="CONTEXTUAL_AD_NETWORK",
            collects_persistent_identifier=False,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")
        approved_service = read_service(service["id"])
        assert approved_service["third_party_exposure_points"] == 5
        assert approved_service["compliance_posture"] == "OPEN"
        assert approved_service["audit_decision_count"] == 1

        add_design_factor(service["id"], "VISUAL_CONTENT", "STRONG")
        escalated = run_determination(service["id"])

        assert escalated["determination_status"] == "CHILD_DIRECTED_PRIMARY", (
            "a score of 0.76 escalates the service to CHILD_DIRECTED_PRIMARY, got "
            f"{escalated['determination_status']}"
        )
        re_audited = read_integration(service["id"], integration["id"])
        assert re_audited["status"] == "AUDIT_PENDING", (
            "the child-directed integration is forced back into audit, got "
            f"{re_audited['status']}"
        )
        assert re_audited["audit_note"] == "re-audit forced by child-directed determination", (
            f"the cascade sets the documented audit_note, got {re_audited['audit_note']!r}"
        )
        assert escalated["third_party_exposure_points"] == 0, (
            "the re-audited integration's points drop out, got "
            f"{escalated['third_party_exposure_points']}"
        )
        assert escalated["open_audit_count"] == 1
        assert escalated["compliance_posture"] == "RESTRICTED", (
            f"one open audit restricts the service, got {escalated['compliance_posture']}"
        )
        assert escalated["audit_decision_count"] == 1, (
            "a forced re-audit is not an audit decision, got "
            f"{escalated['audit_decision_count']}"
        )

    def test_12_appending_evidence_before_the_escalation_leaves_the_audit_closed(self):
        """The new factor row changes the score without triggering the cascade.

        "Appending evidence immediately refreshes the service's `design_score` and
        `audience_child_share` and advances the service's `version` by one — but it
        deliberately does **not** change `determination_status`." The escalation consequences
        therefore cannot have fired yet.

        Design: Difficulty/transitive_cascade/determination_escalation_forces_integration_reaudit_and_locks_override
        """
        service = mixed_audience_service(name="Pre Escalation Service")
        published_notice(
            service["id"], disclosed_integration_vendors=["PlaySafe Contextual"]
        )
        integration = create_integration(
            service["id"],
            vendor_name="PlaySafe Contextual",
            integration_type="CONTEXTUAL_AD_NETWORK",
            collects_persistent_identifier=False,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")

        row = add_design_factor(service["id"], "VISUAL_CONTENT", "STRONG")

        assert row["evidence_sequence"] == 2
        after = read_service(service["id"])
        assert_design_score(after, 0.76)
        assert after["determination_status"] == "MIXED_AUDIENCE", (
            "the determination axis waits for a determination run, got "
            f"{after['determination_status']}"
        )
        assert after["open_audit_count"] == 0, (
            f"no audit has been re-opened yet, got {after['open_audit_count']}"
        )
        assert read_integration(service["id"], integration["id"])["status"] == "APPROVED"

    def test_13_override_to_open_is_refused_while_an_audit_remains_open(self):
        """The escalation locks the operator out of overriding the posture open.

        "an override of `OPEN` is refused with `ERR_OPEN_AUDITS_PRESENT` (HTTP 409) unless
        `open_audit_count` is exactly 0."

        Design: Difficulty/transitive_cascade/determination_escalation_forces_integration_reaudit_and_locks_override
        """
        service = mixed_audience_service(name="Locked Override Service")
        published_notice(
            service["id"], disclosed_integration_vendors=["PlaySafe Contextual"]
        )
        integration = create_integration(
            service["id"],
            vendor_name="PlaySafe Contextual",
            integration_type="CONTEXTUAL_AD_NETWORK",
            collects_persistent_identifier=False,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")
        add_design_factor(service["id"], "VISUAL_CONTENT", "STRONG")
        run_determination(service["id"])

        validate_error(
            api_client.set_posture(
                service["id"], {"posture_override": "OPEN"}, OFFICER_HEADERS
            ),
            "ERR_OPEN_AUDITS_PRESENT",
        )

        after = read_service(service["id"])
        assert after["posture_override"] is None, (
            f"the refused override must not be stored, got {after['posture_override']}"
        )
        assert after["compliance_posture"] == "RESTRICTED"
        assert after["determination_variant_applied"] == "DESIGN_FIRST"
