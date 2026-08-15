"""Engagement contracting: creation rules, lifecycle gates, amendment chain, OCC."""
from test_helpers import (
    ACCOUNTANT,
    CLERK,
    NON_EXISTENT_UUID,
    SUPERVISOR,
    ApiErrorId,
    assert_engagement,
    create_agreement,
    create_draft_engagement,
    create_engagement_payload,
    create_performer,
    create_ratified_agreement,
    create_shooting_production,
    get_engagement,
    get_success_data,
    list_all_engagements,
    setup_standard,
    validate_error,
    validate_success,
)


class TestEngagementCreation:
    def test_create_mints_system_fields(self, api):
        """PRD §2.4: "Every persisted resource carries an `id` — a server-minted
        UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC
        format with three fractional digits. Most resources additionally carry
        `updated_at` (same format) and `version` (an integer starting at 1 and
        incrementing by 1 on every mutation)."
        PRD §3.4: "The engagement is created in `DRAFT` status."

        Design: Corner/entities/engagement_create_system_fields_server_minted
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = validate_success(
            api.create_engagement(
                create_engagement_payload(prod["id"], agr["id"], perf["id"]),
                ACCOUNTANT),
            expected_status=201)
        assert_engagement(eng)
        assert eng["version"] == 1, "version starts at 1 on creation"
        assert eng["status"] == "DRAFT"
        # Aggregates are sums over empty sets at creation.
        assert eng["accrued_penalty_cents"] == 0
        assert eng["accrued_adjustment_cents"] == 0
        assert eng["ytd_paid_cents"] == 0

    def test_get_unknown_engagement_returns_404(self, api):
        """PRD §2.7: "Existence of referenced identifiers (path parameters first,
        then foreign-key body fields, left to right); a missing identifier is
        rejected with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/engagement_get_not_found_returns_404
        """
        resp = api.get_engagement(NON_EXISTENT_UUID, CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_with_missing_production_returns_404(self, api):
        """PRD §2.7: "Existence of referenced identifiers (path parameters first,
        then foreign-key body fields, left to right); a missing identifier is
        rejected with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/engagement_create_with_missing_production_returns_404
        """
        agr = create_ratified_agreement()
        perf = create_performer()
        payload = create_engagement_payload(NON_EXISTENT_UUID, agr["id"], perf["id"])
        resp = api.create_engagement(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_unknown_tier_rejected(self, api):
        """PRD §3.4: "The `tier_code` must match a `tier_code` present in the
        referenced agreement's `rate_tiers`; a mismatch is rejected with
        `ERR_TIER_NOT_FOUND`."

        Design: Corner/validations/engagement_create_unknown_tier_rejected
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        payload = create_engagement_payload(prod["id"], agr["id"], perf["id"],
                                            tier_code="T9")
        resp = api.create_engagement(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_TIER_NOT_FOUND)

    def test_create_loan_out_field_mismatch_rejected(self, api):
        """PRD §3.4: "When `payee_type` is `DIRECT`, the performer is paid with tax
        withholding and garnishment exposure, and both `loan_out_legal_name` and
        `loan_out_tax_id` must be absent. When `payee_type` is `LOAN_OUT`, the
        loan-out corporation is paid gross — zero tax withholding, zero garnishment
        — and both `loan_out_legal_name` and `loan_out_tax_id` are required.
        Violating either conditional requirement is rejected with
        `ERR_LOAN_OUT_FIELDS`."

        Design: Corner/validations/engagement_create_loan_out_field_mismatch_rejected
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()

        # DIRECT must not carry loan-out fields.
        payload_direct = create_engagement_payload(
            prod["id"], agr["id"], perf["id"],
            loan_out_legal_name="Should Not Be Here Inc")
        resp1 = api.create_engagement(payload_direct, ACCOUNTANT)
        validate_error(resp1, ApiErrorId.ERR_LOAN_OUT_FIELDS)

        # LOAN_OUT without the required loan-out fields.
        payload_loan_out = create_engagement_payload(
            prod["id"], agr["id"], perf["id"], payee_type="LOAN_OUT")
        resp2 = api.create_engagement(payload_loan_out, ACCOUNTANT)
        validate_error(resp2, ApiErrorId.ERR_LOAN_OUT_FIELDS)


class TestEngagementLifecycleGates:
    def test_submit_with_draft_agreement_rejected(self, api):
        """PRD §3.4: "Submission requires the referenced union agreement to be
        `RATIFIED`; otherwise the submission is rejected with
        `ERR_AGREEMENT_NOT_RATIFIED`."

        Design: Corner/validations/engagement_submit_with_draft_agreement_rejected
        """
        agr = create_agreement()  # DRAFT, never ratified
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        resp = api.submit_engagement(eng["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_RATIFIED)
        assert get_engagement(eng["id"])["status"] == "DRAFT"

    def test_approve_from_draft_rejected(self, api):
        """PRD §3.4: "Submission against an engagement not in `DRAFT` status is
        rejected with `ERR_ENGAGEMENT_INVALID_STATE`; the same code rejects
        approve or reject against an engagement not in `PENDING_APPROVAL`."

        Design: Corner/validations/engagement_approve_from_draft_rejected
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        resp = api.approve_engagement(eng["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE)


class TestDoubleBooking:
    def _setup_active_plus_draft_successor(self, api):
        """E1 ACTIVE [2026-08-03, 2026-09-11]; E2 DRAFT [2026-09-11, 2026-10-09]
        for the same performer — the windows share the boundary date 2026-09-11."""
        ctx = setup_standard()
        eng2 = create_draft_engagement(
            ctx["prod"]["id"], ctx["agr"]["id"], ctx["perf"]["id"],
            start_date="2026-09-11", end_date="2026-10-09", guaranteed_days=15)
        return ctx, eng2

    def test_shared_boundary_date_conflicts(self, api):
        """PRD §3.4: "Submission also runs a performer double-booking check: the
        submission is rejected with `ERR_PERFORMER_DOUBLE_BOOKED` when another
        engagement exists for the same performer with status `PENDING_APPROVAL`,
        `ACTIVE`, or `AMENDMENT_PENDING` and a closed-interval date overlap — that
        is, the other's `start_date` is on or before this engagement's `end_date`
        and this engagement's `start_date` is on or before the other's `end_date`,
        so a shared boundary date counts as a conflict."

        Design: Difficulty/resource_temporal_overlap/engagement_submit_closed_interval_double_booking
        """
        _ctx, eng2 = self._setup_active_plus_draft_successor(api)
        resp = api.submit_engagement(eng2["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_PERFORMER_DOUBLE_BOOKED)

    def test_double_booking_rejection_leaves_engagement_draft(self, api):
        """PRD §3.4: "the submission is rejected with `ERR_PERFORMER_DOUBLE_BOOKED`
        when another engagement exists for the same performer with status
        `PENDING_APPROVAL`, `ACTIVE`, or `AMENDMENT_PENDING` and a closed-interval
        date overlap". A rejected submission leaves the engagement in DRAFT.

        Design: Difficulty/resource_temporal_overlap/engagement_submit_closed_interval_double_booking
        """
        _ctx, eng2 = self._setup_active_plus_draft_successor(api)
        validate_error(api.submit_engagement(eng2["id"], ACCOUNTANT),
                       ApiErrorId.ERR_PERFORMER_DOUBLE_BOOKED)
        eng2_after = get_engagement(eng2["id"])
        assert_engagement(eng2_after)
        assert eng2_after["status"] == "DRAFT"


class TestAmendmentChain:
    def _create_amendment(self, api, ctx, expected_version, **overrides):
        options = dict(
            tier_code="T2", weekly_guarantee_cents=400000,
            supersedes_engagement_id=ctx["eng"]["id"],
            expected_engagement_version=expected_version)
        options.update(overrides)
        payload = create_engagement_payload(
            ctx["prod"]["id"], ctx["agr"]["id"], ctx["perf"]["id"],
            **options)
        return api.create_engagement(payload, ACCOUNTANT)

    def test_amendment_approval_supersedes_target(self, api):
        """PRD §3.4: "When the amendment create succeeds, the target engagement
        transitions from `ACTIVE` to `AMENDMENT_PENDING` and its `version`
        increments by 1."
        PRD §3.4: "If the engagement carries `supersedes_engagement_id`, approval
        simultaneously transitions the target from `AMENDMENT_PENDING` to
        `SUPERSEDED` and increments the target's `version`."
        PRD §3.4: "The engagement named by `supersedes_engagement_id` is excluded
        from this check, since an amendment is supposed to overlap its target."

        Design: Corner/state_machines/amendment_approval_supersedes_target
        """
        ctx = setup_standard()
        e1 = ctx["eng"]
        e1_version = e1["version"]

        resp = self._create_amendment(api, ctx, e1_version)
        eng2 = validate_success(resp, expected_status=201)
        e1_after_create = get_engagement(e1["id"])
        assert e1_after_create["status"] == "AMENDMENT_PENDING"
        assert e1_after_create["version"] == e1_version + 1, (
            "amendment create bumps the target's version by 1")

        # The amendment may submit over the identical window: the supersede
        # target is excluded from the double-booking check.
        get_success_data(api.submit_engagement(eng2["id"], ACCOUNTANT))
        approved = get_success_data(api.approve_engagement(eng2["id"], SUPERVISOR))
        assert approved["status"] == "ACTIVE"
        assert get_engagement(e1["id"])["status"] == "SUPERSEDED"

    def test_amendment_reject_restores_target(self, api):
        """PRD §3.4: "Rejection by a `PayrollSupervisor` moves the engagement from
        `PENDING_APPROVAL` back to `DRAFT` and increments its `version`; if the
        engagement carries `supersedes_engagement_id`, rejection compensates the
        create-time side effect by transitioning the target from
        `AMENDMENT_PENDING` back to `ACTIVE` and incrementing the target's
        `version`."

        Design: Corner/state_machines/engagement_reject_restores_amendment_target
        """
        ctx = setup_standard()
        e1 = ctx["eng"]
        resp = self._create_amendment(api, ctx, e1["version"])
        eng2 = validate_success(resp, expected_status=201)
        get_success_data(api.submit_engagement(eng2["id"], ACCOUNTANT))

        rejected = get_success_data(api.reject_engagement(eng2["id"], SUPERVISOR))
        assert rejected["status"] == "DRAFT"
        e1_after = get_engagement(e1["id"])
        assert e1_after["status"] == "ACTIVE", (
            "rejecting the amendment restores the target to ACTIVE")

    def test_amendment_create_with_stale_version_rejected(self, api):
        """PRD §2.6: "If the target's current `version` does not match, the create
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "the product legitimately permits a new amendment to supersede
        the target and the version guard is what prevents a client from overwriting
        an amendment it has not observed."

        Design: Corner/cross_cutting_layers/amendment_create_with_stale_version_rejected
        """
        ctx = setup_standard()
        e1 = ctx["eng"]
        observed_version = e1["version"]

        # Amendment A with the current version succeeds and bumps the target.
        resp_a = self._create_amendment(api, ctx, observed_version)
        eng_a = validate_success(resp_a, expected_status=201)
        assert get_engagement(e1["id"])["version"] == observed_version + 1

        # Restore the target to ACTIVE by withdrawing amendment A
        # (submit + reject), so the stale create below violates ONLY the
        # version guard — PRD §2.7 evaluates state/shape rules before OCC.
        get_success_data(api.submit_engagement(eng_a["id"], ACCOUNTANT))
        get_success_data(api.reject_engagement(eng_a["id"], SUPERVISOR))
        e1_restored = get_engagement(e1["id"])
        assert e1_restored["status"] == "ACTIVE"
        assert e1_restored["version"] == observed_version + 2

        # Amendment B carrying the earlier observed version is stale.
        resp_b = self._create_amendment(api, ctx, observed_version,
                                        weekly_guarantee_cents=450000)
        validate_error(resp_b, ApiErrorId.ERR_STALE_VERSION)

        e1_after = get_engagement(e1["id"])
        assert e1_after["status"] == "ACTIVE", (
            "the stale create must not transition the target")
        assert e1_after["version"] == observed_version + 2, (
            "the stale create must not bump the target's version")
        remaining = list_all_engagements()
        assert len(remaining) == 2, (
            "no second amendment engagement is persisted after the stale create")
        assert {e["id"] for e in remaining} == {e1["id"], eng_a["id"]}
