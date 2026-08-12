"""Compliance (breach, fines), availability windows, cross-entity state gates,
validation priority pairs, and optimistic concurrency (PRD §2.6, §2.7, §3.3,
§3.5, §3.6, §3.7, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_application,
    begin_review,
    create_application,
    create_application_payload,
    create_org,
    create_recording_grant_payload,
    create_rental_for,
    create_rental_payload,
    create_restriction_payload,
    create_title,
    current_application_version,
    fund_agreement_for_activation,
    get_success_data,
    make_applicant_headers,
    reset_clock,
    setup_active_agreement,
    setup_active_agreement_with_grant,
    setup_breached_agreement,
    setup_pending_agreement,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _admin():
    from test_helpers import TEST_USERS

    return TEST_USERS["rights_admin_headers"]


def _officer():
    from test_helpers import TEST_USERS

    return TEST_USERS["licensing_officer_headers"]


def _clerk():
    from test_helpers import TEST_USERS

    return TEST_USERS["materials_clerk_headers"]


def _finance():
    from test_helpers import TEST_USERS

    return TEST_USERS["finance_officer_headers"]


def _fines_for(api, org_id, **filters):
    params = {"organization_id": org_id}
    params.update(filters)
    data, _meta = validate_paginated(api.list_fines(_finance(), params=params))
    return data


# ---------------------------------------------------------------------------
# Breach cascade (depth 3): agreement -> grant -> fine -> org standing
# ---------------------------------------------------------------------------


class TestBreachCascade:
    def _setup(self, api):
        ctx = setup_active_agreement_with_grant(
            grant_overrides={
                "grant_kind": "CAST_RECORDING_AUDIO",
                "distribution_scope": "CAST_CREW_ONLY",
            }
        )
        # CAST_RECORDING_AUDIO x1.00, CAST_CREW_ONLY unchanged: 30000
        assert ctx["grant"]["recording_royalty_cents"] == 30000
        assert ctx["grant"]["status"] == "APPROVED"
        return ctx

    def test_breach_flips_agreement_creates_fine_suspends_org(self, api):
        """PRD §3.5: "The agreement moves from `ACTIVE` to `BREACHED`. A `Fine`
        is created with `fine_kind` mapped from the breach reason to
        `UNAUTHORIZED_ALTERATION` or `UNAUTHORIZED_RECORDING` and `status`
        `ASSESSED` ... The organization's `standing` flips to `SUSPENDED` until
        the fine is resolved."

        Design: Difficulty/transitive_cascade/breach_cascade_three_deep_agreement_grant_fine_org
        """
        ctx = self._setup(api)
        breached = validate_success(
            api.declare_breach(
                ctx["agreement"]["id"],
                {"breach_reason": "UNAUTHORIZED_ALTERATION"},
                _admin(),
            ),
            expected_status=200,
        )
        assert breached["license_status"] == "BREACHED"
        fines = _fines_for(api, ctx["org"]["id"], fine_kind="UNAUTHORIZED_ALTERATION")
        assert len(fines) == 1
        assert fines[0]["status"] == "ASSESSED"
        # breach-fine rule: larger of 500000 floor and 2x quoted (2*50000)
        assert fines[0]["amount_cents"] == 500000
        org = get_success_data(api.get_organization(ctx["org"]["id"], _admin()))
        assert org["standing"] == "SUSPENDED"

    def test_breach_revokes_grant_and_reverses_royalty_debit(self, api):
        """PRD §3.5: "Every `RecordingGrant` on the agreement moves to
        `REVOKED`." PRD §3.7: "every `APPROVED` grant moves to `REVOKED` and
        the agreement's `royalty_balance_cents` is decremented by the grant's
        `recording_royalty_cents` to reverse the earlier debit."

        Design: Difficulty/transitive_cascade/breach_cascade_three_deep_agreement_grant_fine_org
        """
        ctx = self._setup(api)
        before = get_success_data(api.get_agreement(ctx["agreement"]["id"], _admin()))
        # balance after grant approval = (quoted - activation payment) + grant
        # quoted 50000, fixture pays floor(50000/2)=25000 (PRD §3.4 partial-
        # payment activation), so 25000 + grant 30000
        assert before["royalty_balance_cents"] == 55000
        breached = validate_success(
            api.declare_breach(
                ctx["agreement"]["id"],
                {"breach_reason": "UNAUTHORIZED_ALTERATION"},
                _admin(),
            ),
            expected_status=200,
        )
        grant = get_success_data(api.get_recording_grant(ctx["grant"]["id"], _admin()))
        assert grant["status"] == "REVOKED"
        # revoke reverses the 30000 debit: 55000 - 30000 = 25000
        assert breached["royalty_balance_cents"] == 25000


# ---------------------------------------------------------------------------
# Compensating invariant: royalty balance conserved across approve + revoke
# ---------------------------------------------------------------------------


class TestRoyaltyBalanceConservation:
    def _setup(self, api):
        ctx = setup_active_agreement_with_grant(
            grant_overrides={
                "grant_kind": "CAST_RECORDING_AUDIO",
                "distribution_scope": "CAST_CREW_ONLY",
            },
            app_overrides={
                "first_performance_date": "2026-07-01T19:00:00Z",
                "last_performance_date": "2026-07-01T19:00:00Z",
            },
        )
        return ctx

    def test_grant_approve_increments_balance(self, api):
        """PRD §3.7: "When approval lands, the grant's `recording_royalty_cents`
        is computed by the recording-royalty rule and the agreement's
        `royalty_balance_cents` is incremented by that amount."

        Design: Difficulty/compensating_invariant/royalty_balance_conserved_across_grant_approve_and_revoke
        """
        ctx = self._setup(api)
        # quoted 50000 at issuance; fixture activation payment 25000 (PRD §3.4
        # partial-payment rule); grant approval added 30000
        agreement = get_success_data(
            api.get_agreement(ctx["agreement"]["id"], _admin())
        )
        assert agreement["royalty_balance_cents"] == 25000 + 30000

    def test_revoke_on_cancel_restores_balance(self, api):
        """PRD §3.7: "when the parent agreement transitions to `CANCELLED` or
        `BREACHED`, every `APPROVED` grant moves to `REVOKED` and the
        agreement's `royalty_balance_cents` is decremented by the grant's
        `recording_royalty_cents` to reverse the earlier debit."

        Design: Difficulty/compensating_invariant/royalty_balance_conserved_across_grant_approve_and_revoke
        """
        ctx = self._setup(api)
        cancelled = validate_success(
            api.cancel_agreement(ctx["agreement"]["id"], {"reason": "Cancel"}, _admin()),
            expected_status=200,
        )
        grant = get_success_data(api.get_recording_grant(ctx["grant"]["id"], _admin()))
        assert grant["status"] == "REVOKED"
        # net drift across approve + revoke is zero: back to the post-activation
        # balance of 25000 (quoted 50000 minus the 25000 activation payment)
        assert cancelled["royalty_balance_cents"] == 25000


# ---------------------------------------------------------------------------
# Priority pairs (PRD §2.7 ordering)
# ---------------------------------------------------------------------------


class TestStateBeatsBusinessSafety:
    def _draft_app(self, api, withdraw=False):
        reset_clock()
        title = create_title()
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        app = create_application(title["id"], org["id"], applicant)
        if withdraw:
            get_success_data(api.withdraw_title(title["id"], _admin()))
        return title, org, applicant, app

    def test_state_error_wins_over_withdrawn_title(self, api):
        """PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`).
        Only after all of those pass do domain business rules fire —
        organization standing (`ERR_ORG_SUSPENDED`), title status
        (`ERR_TITLE_WITHDRAWN`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_approve_on_withdrawn_title
        """
        _t, _o, _ap, app = self._draft_app(api, withdraw=True)
        resp = api.approve_application(
            app["id"],
            {"expected_application_version": app["version"]},
            _officer(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_state_error_fires_in_isolation(self, api):
        """PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`)".
        PRD §3.3: approval is defined from `UNDER_REVIEW` ("Approval then
        evaluates three availability preconditions" after review begins).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_approve_on_withdrawn_title
        """
        _t, _o, _ap, app = self._draft_app(api, withdraw=False)
        resp = api.approve_application(
            app["id"],
            {"expected_application_version": app["version"]},
            _officer(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestStandingCheckedOnNewApplications:
    def _suspended_org(self, api):
        ctx = setup_breached_agreement(breach_reason="UNAUTHORIZED_ALTERATION")
        assert ctx["agreement"]["license_status"] == "BREACHED"
        assert ctx["org"]["standing"] == "SUSPENDED"
        return ctx

    def test_suspended_org_application_rejected_with_valid_payload(self, api):
        """PRD §3.2: "while an organization is `SUSPENDED`, it cannot file new
        applications ... each of those attempts is rejected with
        `ERR_ORG_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_payment_when_suspended
        """
        ctx = self._suspended_org(api)
        payload = create_application_payload(ctx["title"]["id"], ctx["org"]["id"])
        resp = api.create_application(payload, ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED, expected_status=409)


# ---------------------------------------------------------------------------
# Cross-entity state gates
# ---------------------------------------------------------------------------


class TestPerformanceDeclarationGate:
    def test_declare_performance_requires_active_agreement(self, api):
        """PRD §3.5: "Once an agreement is `ACTIVE`, the applicant declares
        performances." A PENDING_PAYMENT agreement is not ACTIVE, so the
        from-state check rejects the declaration.
        PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/performance_report_blocked_when_agreement_not_active
        """
        ctx = setup_pending_agreement()  # PENDING_PAYMENT, never activated
        resp = api.create_performance(
            ctx["agreement"]["id"],
            {"performance_at": "2026-06-01T19:00:00Z"},
            ctx["applicant"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_declare_performance_succeeds_once_active(self, api):
        """PRD §3.5: "Once an agreement is `ACTIVE`, the applicant declares
        performances. A performance-declaration request names the agreement and
        supplies a `performance_at` datetime."

        Design: Difficulty/cross_entity_state_dependency/performance_report_blocked_when_agreement_not_active
        """
        ctx = setup_pending_agreement()
        resp = api.create_performance(
            ctx["agreement"]["id"],
            {"performance_at": "2026-06-01T19:00:00Z"},
            ctx["applicant"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # PRD §3.4: activation requires funding (partial-payment rule)
        fund_agreement_for_activation(ctx["agreement"]["id"])
        get_success_data(api.activate_agreement(ctx["agreement"]["id"], _admin()))
        perf = validate_success(
            api.create_performance(
                ctx["agreement"]["id"],
                {"performance_at": "2026-06-01T19:00:00Z"},
                ctx["applicant"],
            ),
            expected_status=201,
        )
        assert perf["status"] == "SCHEDULED"
        assert perf["gross_reported"] is False


class TestRentalShipGate:
    def test_rental_ship_blocked_when_agreement_breached(self, api):
        """PRD §3.6: "Shipping is a clerk action that requires the rental to be
        `RESERVED`, the agreement `ACTIVE`, the organization in `GOOD`
        standing, and the deposit to be held".
        PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`).
        Only after all of those pass do domain business rules fire —
        organization standing (`ERR_ORG_SUSPENDED`)".

        Design: Difficulty/cross_entity_state_dependency/rental_ship_blocked_when_agreement_breached
        """
        ctx = setup_active_agreement()
        rental = create_rental_for(ctx["agreement"]["id"])
        get_success_data(
            api.declare_breach(
                ctx["agreement"]["id"],
                {"breach_reason": "UNAUTHORIZED_ALTERATION"},
                _admin(),
            )
        )
        resp = api.ship_rental(rental["id"], _clerk())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rental_ship_succeeds_when_agreement_active(self, api):
        """PRD §3.6: "Shipping is a clerk action that requires the rental to be
        `RESERVED`, the agreement `ACTIVE`, the organization in `GOOD`
        standing, and the deposit to be held — `deposit_status` `HELD`. ...
        When it lands, the rental moves from `RESERVED` to `SHIPPED`."

        Design: Difficulty/cross_entity_state_dependency/rental_ship_blocked_when_agreement_breached
        """
        ctx = setup_active_agreement()
        rental = create_rental_for(ctx["agreement"]["id"])
        assert rental["status"] == "RESERVED"
        assert rental["deposit_status"] == "HELD"
        shipped = validate_success(api.ship_rental(rental["id"], _clerk()), 200)
        assert shipped["status"] == "SHIPPED"


# ---------------------------------------------------------------------------
# Availability windows: closed vs half-open interval semantics
# ---------------------------------------------------------------------------


class TestTerritoryRestrictionClosedInterval:
    def test_touching_window_is_blocked(self, api):
        """PRD §2.4: "on `TerritoryRestriction` both endpoints are inclusive
        (closed interval)". PRD §3.3: "First, the latest `AvailabilitySnapshot`
        for the application must have `available` true, otherwise the approval
        is rejected with `ERR_TITLE_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/territory_restriction_closed_interval_blocks_touching_window
        """
        reset_clock()
        title = create_title()
        get_success_data(
            api.create_restriction(
                title["id"],
                create_restriction_payload(
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-10T00:00:00Z",
                ),
                _admin(),
            )
        )
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        # requested window starts exactly at the restriction's inclusive end
        app = create_application(
            title["id"],
            org["id"],
            applicant,
            first_performance_date="2026-06-10T00:00:00Z",
            last_performance_date="2026-06-12T19:00:00Z",
        )
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        resp = api.approve_application(
            app["id"],
            {"expected_application_version": current_application_version(app["id"])},
            _officer(),
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_UNAVAILABLE, expected_status=409)

    def test_snapshot_records_blocking_restriction(self, api):
        """PRD §3.3: "The snapshot's verdict is captured in `available` and the
        snapshot records the blocking identifiers in `blocking_restriction_ids`
        and `blocking_agreement_ids` so a reviewer can see exactly which
        restrictions or exclusive runs are in the way".
        PRD §2.4: "on `TerritoryRestriction` both endpoints are inclusive
        (closed interval)".

        Design: Difficulty/resource_temporal_overlap/territory_restriction_closed_interval_blocks_touching_window
        """
        reset_clock()
        title = create_title()
        restriction = get_success_data(
            api.create_restriction(
                title["id"],
                create_restriction_payload(
                    window_start="2026-06-01T00:00:00Z",
                    window_end="2026-06-10T00:00:00Z",
                ),
                _admin(),
            )
        )
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        app = create_application(
            title["id"],
            org["id"],
            applicant,
            first_performance_date="2026-06-10T00:00:00Z",
            last_performance_date="2026-06-12T19:00:00Z",
        )
        submit_application(app["id"], applicant)
        snapshot = get_success_data(
            api.get_application_availability(app["id"], _officer())
        )
        assert snapshot["available"] is False
        assert restriction["id"] in snapshot["blocking_restriction_ids"]


class TestExclusiveRunHalfOpenInterval:
    def _setup_adjacent(self, api):
        """Agreement 1 ACTIVE covering window ending exactly when agreement 2's
        requested window starts (seconds granularity, PRD §2.4)."""
        reset_clock()
        title = create_title()
        org1 = create_org(legal_name="Org One")
        applicant1 = make_applicant_headers(org1["id"])
        app1 = create_application(
            title["id"],
            org1["id"],
            applicant1,
            first_performance_date="2026-06-01T19:00:00Z",
            last_performance_date="2026-06-10T19:00:00Z",
        )
        submit_application(app1["id"], applicant1)
        begin_review(app1["id"])
        agr1 = approve_application(app1["id"])
        # PRD §3.4: activation requires funding (partial-payment rule)
        fund_agreement_for_activation(agr1["id"])
        get_success_data(api.activate_agreement(agr1["id"], _admin()))
        org2 = create_org(legal_name="Org Two")
        applicant2 = make_applicant_headers(org2["id"])
        app2 = create_application(
            title["id"],
            org2["id"],
            applicant2,
            first_performance_date="2026-06-10T19:00:00Z",
            last_performance_date="2026-06-15T19:00:00Z",
        )
        submit_application(app2["id"], applicant2)
        begin_review(app2["id"])
        return title, org2, applicant2, app2

    def test_adjacent_window_approval_succeeds(self, api):
        """PRD §2.4: "on `TerritoryRestriction` both endpoints are inclusive
        (closed interval), whereas on an exclusive-run `LicenseAgreement`
        availability test the window is treated as half-open at the end."

        Design: Difficulty/resource_temporal_overlap/exclusive_run_half_open_interval_allows_adjacent_window
        """
        _t, _o, _ap, app2 = self._setup_adjacent(api)
        agreement = validate_success(
            api.approve_application(
                app2["id"],
                {
                    "expected_application_version": current_application_version(
                        app2["id"]
                    )
                },
                _officer(),
            ),
            expected_status=201,
        )
        assert agreement["license_status"] == "PENDING_PAYMENT"

    def test_snapshot_has_no_blocking_agreements(self, api):
        """PRD §2.4: "on an exclusive-run `LicenseAgreement` availability test
        the window is treated as half-open at the end."
        PRD §3.3: "the snapshot records the blocking identifiers in
        `blocking_restriction_ids` and `blocking_agreement_ids`".

        Design: Difficulty/resource_temporal_overlap/exclusive_run_half_open_interval_allows_adjacent_window
        """
        _t, _o, _ap, app2 = self._setup_adjacent(api)
        snapshot = get_success_data(
            api.get_application_availability(app2["id"], _officer())
        )
        assert snapshot["available"] is True
        assert snapshot["blocking_agreement_ids"] == []
        assert snapshot["blocking_restriction_ids"] == []


# ---------------------------------------------------------------------------
# Recording royalty multiplier (corner) + fine waiver restriction (corner)
# ---------------------------------------------------------------------------


class TestRecordingRoyaltyRule:
    def test_recording_royalty_streaming_public_free_multiplier(self, api):
        """PRD §3.7: "The multiplier depends on `grant_kind`: 1.00 for
        `CAST_RECORDING_AUDIO`, 0.50 for `ARCHIVAL_VIDEO`, and 2.00 for
        `STREAMING_VIDEO`. The multiplier is then adjusted by
        `distribution_scope`: a `PUBLIC_FREE` scope multiplies by 1.50 ... The
        final `recording_royalty_cents` is the base times the final multiplier,
        rounded half-up to integer cents."

        Design: Corner/calculations/recording_royalty_streaming_public_free_multiplier
        """
        ctx = setup_active_agreement()
        grant = get_success_data(
            api.create_recording_grant(
                create_recording_grant_payload(
                    ctx["agreement"]["id"],
                    grant_kind="STREAMING_VIDEO",
                    distribution_scope="PUBLIC_FREE",
                ),
                ctx["applicant"],
            )
        )
        approved = validate_success(
            api.approve_recording_grant(grant["id"], _admin()), 200
        )
        # 30000 * 2.00 * 1.50 = 90000
        assert approved["recording_royalty_cents"] == 90000
        agreement = get_success_data(
            api.get_agreement(ctx["agreement"]["id"], _admin())
        )
        # post-activation balance 25000 (quoted 50000 - 25000 payment) + 90000
        assert agreement["royalty_balance_cents"] == 25000 + 90000


class TestBreachFineNotWaivable:
    def test_waive_breach_fine_rejected(self, api):
        """PRD §3.8: "breach fines of kind `UNAUTHORIZED_ALTERATION` and
        `UNAUTHORIZED_RECORDING` are never waivable, and the waiver is rejected
        with `ERR_FINE_NOT_WAIVABLE`."

        Design: Corner/validations/waive_breach_fine_rejected
        """
        ctx = setup_breached_agreement(breach_reason="UNAUTHORIZED_ALTERATION")
        fines = _fines_for(api, ctx["org"]["id"], fine_kind="UNAUTHORIZED_ALTERATION")
        assert len(fines) == 1
        resp = api.waive_fine(fines[0]["id"], _finance())
        validate_error(resp, ApiErrorId.ERR_FINE_NOT_WAIVABLE, expected_status=409)


# ---------------------------------------------------------------------------
# Report timing (corner)
# ---------------------------------------------------------------------------


class TestReportTooEarly:
    def test_report_before_performance_at_rejected(self, api):
        """PRD §3.5: "The report is rejected with `ERR_REPORT_TOO_EARLY` if the
        current clock has not yet reached `performance_at`."

        Design: Corner/validations/report_before_performance_at_rejected
        """
        from test_helpers import setup_active_agreement_with_performance

        ctx = setup_active_agreement_with_performance(
            performance_at="2026-06-01T19:00:00Z"
        )
        reset_clock("2026-05-15T00:00:00Z")
        resp = api.report_performance(
            ctx["performance"]["id"],
            {"reported_attendance": 100, "reported_gross_cents": 50000},
            ctx["applicant"],
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_TOO_EARLY, expected_status=409)


# ---------------------------------------------------------------------------
# Optimistic concurrency (corner)
# ---------------------------------------------------------------------------


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_amendment(self, api):
        """PRD §2.6: "Applying an amendment to a `LicenseAgreement` requires the
        caller to supply `expected_agreement_version` carrying the agreement's
        `version` as last observed by the caller; a mismatch against the
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_amendment
        """
        ctx = setup_active_agreement()
        agreement_id = ctx["agreement"]["id"]
        snapshot = get_success_data(api.get_agreement(agreement_id, _admin()))
        v = snapshot["version"]
        validate_success(
            api.create_amendment(
                agreement_id,
                {"expected_agreement_version": v, "amendment_note": "first"},
                _admin(),
            ),
            expected_status=200,
        )
        resp = api.create_amendment(
            agreement_id,
            {"expected_agreement_version": v, "amendment_note": "second stale"},
            _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_stale_version_on_approve(self, api):
        """PRD §2.6: "Approving a `LicenseApplication` requires the caller to
        supply `expected_application_version` carrying the application's
        `version` as last observed; a mismatch against the current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), capturing the case where
        a return-for-info or resubmission has legitimately superseded the
        reviewing officer's snapshot."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_approve
        """
        reset_clock()
        title = create_title()
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        app = create_application(title["id"], org["id"], applicant)
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        v_snapshot = current_application_version(app["id"])
        # officer's snapshot goes stale via a return-for-info + resubmit cycle
        get_success_data(
            api.return_for_info_application(app["id"], {"notes": "bump"}, _officer())
        )
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        resp = api.approve_application(
            app["id"], {"expected_application_version": v_snapshot}, _officer()
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
