"""EVV visits and service authorizations: state gates, spans, exhaustion,
waterfall all-or-nothing, geo exception start, DAY-unit threshold.

PRD 3.3 (authorizations) and 3.8 (EVV).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_isp,
    create_and_verify_visit,
    create_authorization_payload,
    create_evv_visit_payload,
    create_isp_draft,
    get_success_data,
    make_case_manager_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_billable_pipeline,
    setup_enrolled_individual,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestAuthorizationExhaustionAtEquality:
    """consumed == authorized triggers EXHAUSTED at exact equality (PRD 3.8)."""

    def _setup_two_verified_eight_unit_visits(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        create_and_verify_visit(ctx, "2026-06-02T06:00:00Z", "2026-06-02T08:00:00Z")
        create_and_verify_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T11:00:00Z")
        # Third 120-minute visit still PENDING.
        v3 = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T12:00:00Z", check_out_at="2026-06-02T14:00:00Z",
            ), ctx["d1_headers"],
        ))
        return ctx, v3

    def test_third_verify_succeeds_and_consumes_to_exact_equality(self, api):
        """PRD 3.8: "each candidate's `consumed_units` is incremented by its
        allocated amount; and any candidate whose `consumed_units` reaches or
        exceeds its `authorized_units` (equality is the trigger) transitions to
        `EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/authorization_exhaustion_at_exact_equality
        """
        ctx, v3 = self._setup_two_verified_eight_unit_visits(api)
        verified = get_success_data(api_client.verify_evv_visit(v3["id"], ctx["q_headers"]))
        assert verified["final_units"] == 8
        assert verified["verification_status"] == "VERIFIED"
        auth = get_success_data(api_client.get_authorization(ctx["auth"]["id"], ANY))
        assert auth["consumed_units"] == 24
        assert auth["remaining_units"] == 0

    def test_authorization_status_exhausted_at_equality(self, api):
        """PRD 3.8: "any candidate whose `consumed_units` reaches or exceeds its
        `authorized_units` (equality is the trigger) transitions to
        `EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/authorization_exhaustion_at_exact_equality
        """
        ctx, v3 = self._setup_two_verified_eight_unit_visits(api)
        get_success_data(api_client.verify_evv_visit(v3["id"], ctx["q_headers"]))
        auth = get_success_data(api_client.get_authorization(ctx["auth"]["id"], ANY))
        assert auth["status"] == "EXHAUSTED"


class TestWaterfallFailureRejectsEntireVerify:
    """All-or-nothing waterfall: no partial debit on failure (PRD 3.8)."""

    def _setup_exhausted_pool_with_pending_visit(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        # PRD 3.8 gates EVV creation on the authorization being ACTIVE, so the
        # fourth visit is created up front; the pool is then exhausted by
        # verifying the first three (3 x 8 units = 24 -> EXHAUSTED).
        v4 = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T15:00:00Z", check_out_at="2026-06-02T16:00:00Z",
            ), ctx["d1_headers"],
        ))
        create_and_verify_visit(ctx, "2026-06-02T06:00:00Z", "2026-06-02T08:00:00Z")
        create_and_verify_visit(ctx, "2026-06-02T09:00:00Z", "2026-06-02T11:00:00Z")
        create_and_verify_visit(ctx, "2026-06-02T12:00:00Z", "2026-06-02T14:00:00Z")
        return ctx, v4

    def test_verify_fails_when_pool_cannot_absorb_units(self, api):
        """PRD 3.8: "If, after all candidates have been considered, any
        unallocated units remain, the entire allocation is rejected with
        `ERR_AUTHORIZATION_UNITS_EXHAUSTED` (HTTP 409) - there is no partial
        debit."

        Design: Corner/validations/waterfall_failure_rejects_entire_verify
        """
        ctx, v4 = self._setup_exhausted_pool_with_pending_visit(api)
        resp = api_client.verify_evv_visit(v4["id"], ctx["q_headers"])
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_UNITS_EXHAUSTED)

    def test_failed_verify_leaves_no_partial_debit_and_visit_pending(self, api):
        """PRD 3.8: "there is no partial debit" — the failed verify mutates
        neither the authorization ledger nor the visit's state.

        Design: Corner/validations/waterfall_failure_rejects_entire_verify
        """
        ctx, v4 = self._setup_exhausted_pool_with_pending_visit(api)
        validate_error(
            api_client.verify_evv_visit(v4["id"], ctx["q_headers"]),
            ApiErrorId.ERR_AUTHORIZATION_UNITS_EXHAUSTED,
        )
        auth = get_success_data(api_client.get_authorization(ctx["auth"]["id"], ANY))
        assert auth["consumed_units"] == 24
        assert auth["status"] == "EXHAUSTED"
        _data, meta = validate_paginated(api_client.list_evv_visits(
            ANY, params={"authorization_id": ctx["auth"]["id"], "verification_status": "PENDING"},
        ))
        assert meta["total_count"] == 1


class TestEvvCreateRequiresActiveAuthorization:
    """EVV create against a PENDING authorization rejected (PRD 3.8)."""

    def _setup_pending_authorization(self, api):
        ctx = setup_billable_pipeline()
        # Fresh authorization, never approved (stays PENDING).
        auth = get_success_data(api_client.create_authorization(
            create_authorization_payload(ctx["individual"]["id"], ctx["isp"]["id"]),
            ctx["cm_headers"],
        ))
        return ctx, auth

    def test_authorization_was_pending_at_creation(self, api):
        """PRD 3.3: "A successfully created authorization starts in `PENDING`
        status with `consumed_units` equal to zero."

        Design: Corner/validations/evv_create_requires_active_authorization
        """
        _ctx, auth = self._setup_pending_authorization(api)
        assert auth["status"] == "PENDING"

    def test_visit_against_pending_authorization_rejected(self, api):
        """PRD 3.8: "must be `ACTIVE` (otherwise `ERR_AUTHORIZATION_NOT_ACTIVE`,
        HTTP 409)".

        Design: Corner/validations/evv_create_requires_active_authorization
        """
        ctx, auth = self._setup_pending_authorization(api)
        resp = api_client.create_evv_visit(
            create_evv_visit_payload(ctx["individual"]["id"], auth["id"]),
            ctx["d1_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_ACTIVE)


class TestEvvServiceDateSpanContainment:
    """EVV service_date inside the authorization's closed span (PRD 3.8)."""

    def _setup_short_span_authorization(self, api):
        ctx = setup_billable_pipeline(span_start="2026-01-01", span_end="2026-06-30")
        return ctx

    def test_service_date_past_span_end_rejected(self, api):
        """PRD 3.8: "the `service_date` must lie inside the authorization's
        closed span from `span_start` to `span_end` (otherwise
        `ERR_OUT_OF_SPAN`, HTTP 422)."

        Design: Corner/validations/evv_service_date_outside_authorization_span_rejected
        """
        ctx = self._setup_short_span_authorization(api)
        resp = api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                service_date="2026-07-01",
                check_in_at="2026-07-01T09:00:00Z", check_out_at="2026-07-01T10:00:00Z",
            ), ctx["d1_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_SPAN)

    def test_service_date_on_span_end_accepted(self, api):
        """PRD 3.8: "closed span from `span_start` to `span_end`" — the span_end
        date itself is inside the span.

        Design: Corner/validations/evv_service_date_outside_authorization_span_rejected
        """
        ctx = self._setup_short_span_authorization(api)
        visit = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                service_date="2026-06-30",
                check_in_at="2026-06-30T09:00:00Z", check_out_at="2026-06-30T10:00:00Z",
            ), ctx["d1_headers"],
        ))
        assert visit["service_date"] == "2026-06-30"


class TestEvvGeoFailureStartsInException:
    """geo_within_radius=false creates the visit in EXCEPTION (PRD 3.8)."""

    def test_geo_failure_starts_exception(self, api):
        """PRD 3.8: "If `geo_within_radius` is `false`, the new visit enters
        `EXCEPTION` status instead of `PENDING`."

        Design: Corner/state_machines/evv_geo_failure_starts_in_exception
        """
        ctx = setup_billable_pipeline()
        visit = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"], geo_within_radius=False,
            ), ctx["d1_headers"],
        ))
        assert visit["verification_status"] == "EXCEPTION"

    def test_geo_failure_still_unbilled_with_provisional_units(self, api):
        """PRD 3.8: "The new visit's `billing_status` starts as `UNBILLED`" and
        provisional units are "computed ... from the raw timestamps" (60 minutes
        -> round_half_up(60/15) = 4).

        Design: Corner/state_machines/evv_geo_failure_starts_in_exception
        """
        ctx = setup_billable_pipeline()
        visit = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"], geo_within_radius=False,
            ), ctx["d1_headers"],
        ))
        assert visit["billing_status"] == "UNBILLED"
        assert visit["provisional_units"] == 4


class TestDayUnitThreshold360:
    """DAY unit_type: 360-minute inclusive threshold (PRD 3.8)."""

    def _setup_respite_day_auth(self, api):
        ctx = setup_billable_pipeline(
            service_code="RESPITE", unit_type="DAY",
            authorized_units=10, rate_cents=2000,
        )
        return ctx

    def test_359_minute_visit_bills_zero_units(self, api):
        """PRD 3.8: "When the authorization's `unit_type` is `DAY`,
        `provisional_units` is 1 if the duration is at least 360 minutes and 0
        otherwise."

        Design: Corner/calculations/day_unit_threshold_360_minutes
        """
        ctx = self._setup_respite_day_auth(api)
        v1 = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T05:00:00Z", check_out_at="2026-06-02T10:59:00Z",
            ), ctx["d1_headers"],
        ))
        assert v1["provisional_units"] == 0
        verified = get_success_data(api_client.verify_evv_visit(v1["id"], ctx["q_headers"]))
        assert verified["final_units"] == 0

    def test_360_minute_visit_bills_exactly_one_unit(self, api):
        """PRD 3.8: "`provisional_units` is 1 if the duration is at least 360
        minutes" — the boundary is inclusive.

        Design: Corner/calculations/day_unit_threshold_360_minutes
        """
        ctx = self._setup_respite_day_auth(api)
        v2 = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T12:00:00Z", check_out_at="2026-06-02T18:00:00Z",
            ), ctx["d1_headers"],
        ))
        assert v2["provisional_units"] == 1
        verified = get_success_data(api_client.verify_evv_visit(v2["id"], ctx["q_headers"]))
        assert verified["final_units"] == 1
        auth = get_success_data(api_client.get_authorization(ctx["auth"]["id"], ANY))
        assert auth["consumed_units"] == 1


class TestEvvParallelDimensions:
    """verification_status and billing_status move independently (PRD 3.8)."""

    def _setup_pending_visit(self, api):
        ctx = setup_billable_pipeline(authorized_units=24, rate_cents=1500)
        visit = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(ctx["individual"]["id"], ctx["auth"]["id"]),
            ctx["d1_headers"],
        ))
        return ctx, visit

    def test_verification_axis_moves_alone_through_exception(self, api):
        """PRD 3.8: "A `QIDP` may instead flag a `PENDING` visit, moving it to
        `EXCEPTION`" and "The billing-sweep and claim-void flows ... mutate a
        visit's `billing_status` independently of its `verification_status`".

        Design: Difficulty/non_linear_state_machine/evv_parallel_dimensions_verification_x_billing
        """
        ctx, visit = self._setup_pending_visit(api)
        flagged = get_success_data(api_client.flag_evv_exception(visit["id"], ctx["q_headers"]))
        assert flagged["verification_status"] == "EXCEPTION"
        assert flagged["billing_status"] == "UNBILLED"
        resolved = get_success_data(api_client.resolve_evv_exception(
            visit["id"],
            {"adjusted_minutes": 60, "resolution_note": "Verified from case notes"},
            ctx["q_headers"],
        ))
        assert resolved["verification_status"] == "VERIFIED"
        assert resolved["billing_status"] == "UNBILLED"

    def test_billing_axis_moves_alone_under_sweep_and_void(self, api):
        """PRD 3.8: "the sweep flips `UNBILLED` to `BILLED` and sets
        `billed_claim_id`; the void flips `BILLED` back to `UNBILLED` and clears
        `billed_claim_id`."

        Design: Difficulty/non_linear_state_machine/evv_parallel_dimensions_verification_x_billing
        """
        from test_helpers import make_billing_headers, setup_claim_for_individual, submit_claim_as
        ctx, visit = self._setup_pending_visit(api)
        get_success_data(api_client.verify_evv_visit(visit["id"], ctx["q_headers"]))
        claim = setup_claim_for_individual(ctx)
        assert claim["total_amount_cents"] == 6000
        submit_claim_as(claim["id"], "bill-1")
        get_success_data(api_client.post_claim_payment(
            claim["id"], {"paid_amount_cents": 6000}, make_billing_headers("bill-2"),
        ))
        billed = get_success_data(api_client.get_evv_visit(visit["id"], ANY))
        assert billed["billing_status"] == "BILLED"
        assert billed["verification_status"] == "VERIFIED"
        get_success_data(api_client.void_claim(claim["id"], make_billing_headers("bill-1")))
        unbilled = get_success_data(api_client.get_evv_visit(visit["id"], ANY))
        assert unbilled["billing_status"] == "UNBILLED"
        assert unbilled["verification_status"] == "VERIFIED"


class TestAuthorizationRequiresActiveIsp:
    """Authorization creation gated on the anchored ISP's state (PRD 3.3)."""

    def _setup_pending_review_isp(self, api):
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        isp = create_isp_draft(ind, base["cm"])
        get_success_data(api_client.submit_isp_review(
            isp["id"], make_case_manager_headers(base["cm"]["id"]),
        ))
        return base, ind, isp

    def test_create_against_pending_review_isp_rejected(self, api):
        """PRD 3.3: "The `isp_id` must reference an ISP that is currently
        `ACTIVE`; otherwise the create is rejected with `ERR_ISP_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/authorization_create_requires_isp_active
        """
        base, ind, isp = self._setup_pending_review_isp(api)
        resp = api_client.create_authorization(
            create_authorization_payload(ind["id"], isp["id"]),
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ISP_NOT_ACTIVE)

    def test_create_succeeds_once_isp_active(self, api):
        """PRD 3.3: "Service authorizations allocate waiver units against an
        `ACTIVE` ISP." After activation the same create succeeds.

        Design: Difficulty/cross_entity_state_dependency/authorization_create_requires_isp_active
        """
        base, ind, isp = self._setup_pending_review_isp(api)
        q_h = make_qidp_headers(base["q"]["id"])
        get_success_data(api_client.approve_isp(isp["id"], q_h))
        get_success_data(api_client.activate_isp(isp["id"], q_h))
        auth = get_success_data(api_client.create_authorization(
            create_authorization_payload(ind["id"], isp["id"]),
            make_case_manager_headers(base["cm"]["id"]),
        ))
        assert auth["status"] == "PENDING"


class TestAuthorizationSpanOutsideIspYear:
    """Authorization span must lie inside the ISP plan year (PRD 3.3)."""

    def test_span_end_past_plan_year_end_rejected(self, api):
        """PRD 3.3: "`span_end` must be on or after `span_start` and on or
        before the linked ISP's `plan_year_end`; a span that escapes the plan
        year is rejected with `ERR_OUT_OF_SPAN` (HTTP 422)."

        Design: Corner/validations/authorization_span_outside_isp_year_rejected
        """
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        isp = create_active_isp(ind, base["cm"], base["q"])
        resp = api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"],
                span_start="2026-06-01", span_end="2027-01-15",
            ),
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_SPAN)


class TestResumeBlockedWhileIspExpired:
    """Resume guard: linked ISP must be ACTIVE (PRD 3.3)."""

    def _setup_suspended_by_expiry(self, api):
        ctx = setup_billable_pipeline(
            clock_iso="2026-06-01T00:00:00Z",
            span_start="2026-01-01", span_end="2026-06-30",
            plan_year_start="2026-01-01", plan_year_end="2026-06-30",
        )
        set_clock("2026-07-01T00:00:00Z")
        return ctx

    def test_resume_with_expired_isp_rejected(self, api):
        """PRD 3.3: "From `SUSPENDED`, a `QIDP` may resume the authorization
        back to `ACTIVE`, but only when the linked ISP is itself `ACTIVE`
        (otherwise `ERR_ISP_NOT_ACTIVE`)".

        Design: Corner/state_machines/authorization_resume_blocked_while_isp_expired
        """
        ctx = self._setup_suspended_by_expiry(api)
        auth = get_success_data(api_client.get_authorization(ctx["auth"]["id"], ANY))
        assert auth["status"] == "SUSPENDED"
        resp = api_client.resume_authorization(ctx["auth"]["id"], ctx["q_headers"])
        validate_error(resp, ApiErrorId.ERR_ISP_NOT_ACTIVE)


class TestFiscalCaps:
    """Per-authorization and per-individual fiscal caps (PRD 3.3)."""

    def _setup_active_isp(self, api):
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        isp = create_active_isp(ind, base["cm"], base["q"])
        return base, ind, isp

    def test_authorization_above_per_auth_cap_rejected(self, api):
        """PRD 3.3: "the per-authorization cap, which requires that the product
        of `authorized_units` and `rate_cents` be no greater than 5000000 cents
        and rejects with `ERR_UNIT_CAP_EXCEEDED` (HTTP 422)".

        Design: Corner/validations/per_authorization_cap_pure_fiscal_rejection
        """
        base, ind, isp = self._setup_active_isp(api)
        resp = api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], service_code="RESPITE", unit_type="DAY",
                authorized_units=300, rate_cents=20000,
            ),
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_CAP_EXCEEDED)

    def test_authorization_exactly_at_cap_accepted(self, api):
        """PRD 3.3: "no greater than 5000000 cents" — exactly equal satisfies
        the cap (250 * 20000 = 5,000,000).

        Design: Corner/validations/per_authorization_cap_pure_fiscal_rejection
        """
        base, ind, isp = self._setup_active_isp(api)
        auth = get_success_data(api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], service_code="RESPITE", unit_type="DAY",
                authorized_units=250, rate_cents=20000,
            ),
            make_case_manager_headers(base["cm"]["id"]),
        ))
        assert auth["status"] == "PENDING"

    def test_individual_annual_cap_aggregate_rejected(self, api):
        """PRD 3.3: "the per-individual annual cap, which requires that the
        sum, over all of the individual's non-`CANCELLED` authorizations
        including the new one, of each authorization's product of
        `authorized_units` and `rate_cents` be no greater than 20000000 cents
        and rejects with `ERR_INDIVIDUAL_CAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/individual_annual_cap_aggregate_rejection
        """
        base, ind, isp = self._setup_active_isp(api)
        cm_h = make_case_manager_headers(base["cm"]["id"])
        for code, utype in [("DAY_PROG", "FIFTEEN_MIN"), ("RESPITE", "DAY"),
                            ("RES_HAB", "DAY"), ("SUPPORTED_EMPLOYMENT", "FIFTEEN_MIN")]:
            get_success_data(api_client.create_authorization(
                create_authorization_payload(
                    ind["id"], isp["id"], service_code=code, unit_type=utype,
                    authorized_units=5000, rate_cents=900,
                    span_start="2026-01-01", span_end="2026-06-30",
                ), cm_h,
            ))
        # Aggregate is now 4 * 4,500,000 = 18,000,000; +4,500,000 -> 22.5M > 20M.
        resp = api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], service_code="DAY_PROG", unit_type="FIFTEEN_MIN",
                authorized_units=5000, rate_cents=900,
                span_start="2026-07-01", span_end="2026-12-31",
            ), cm_h,
        )
        validate_error(resp, ApiErrorId.ERR_INDIVIDUAL_CAP_EXCEEDED)


class TestValidationPriorityPairs:
    """Cross-category priority: earlier failure surfaces first (PRD 2.6)."""

    def test_state_gate_alone_rejects_even_when_fiscal_would_pass(self, api):
        """PRD 2.6: "Domain-specific state preconditions (individual-enrolled,
        ISP-active, home-active, authorization-active,
        medication-order-active), then business-safety checks (certification,
        witness), then business-temporal checks (shift overlap, bed overlap,
        vehicle overlap, span containment)". The ISP-state gate is reachable on
        its own: with a fiscally-clean request against a DRAFT ISP, the same
        `ERR_ISP_NOT_ACTIVE` surfaces.

        Design: Difficulty/priority_pair_validation_conflict/state_isp_inactive_beats_fiscal_unit_cap
        """
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        isp = create_isp_draft(ind, base["cm"])  # left DRAFT
        resp = api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], authorized_units=24, rate_cents=1500,
            ),
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ISP_NOT_ACTIVE)

    def test_isp_not_active_beats_unit_cap(self, api):
        """PRD 2.6: "Domain-specific state preconditions (individual-enrolled,
        ISP-active, home-active, authorization-active,
        medication-order-active), then business-safety checks (certification,
        witness), then business-temporal checks (shift overlap, bed overlap,
        vehicle overlap, span containment)". Business-fiscal checks come later
        in the same ordered list, so a request violating both surfaces the
        ISP-state error.

        Design: Difficulty/priority_pair_validation_conflict/state_isp_inactive_beats_fiscal_unit_cap
        """
        base = setup_agency_with_core_staff()
        ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
        set_clock("2026-06-01T00:00:00Z")
        isp = create_isp_draft(ind, base["cm"])  # left DRAFT
        resp = api_client.create_authorization(
            create_authorization_payload(
                ind["id"], isp["id"], service_code="RESPITE", unit_type="DAY",
                authorized_units=400, rate_cents=20000,
            ),
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ISP_NOT_ACTIVE)
        _data, meta = validate_paginated(api_client.list_authorizations(
            ANY, params={"individual_id": ind["id"]},
        ))
        assert meta["total_count"] == 0

    def test_certification_missing_fires_alone_without_overlap(self, api):
        """PRD 3.4: "When `requires_med_pass` is `true`, the assigned staff
        member must hold the `MED_CERT` certification; if not, the create is
        rejected with `ERR_CERTIFICATION_MISSING` (HTTP 403)." The safety check
        is reachable in isolation when no rest-buffer conflict exists.

        Design: Difficulty/priority_pair_validation_conflict/safety_certification_beats_temporal_shift_overlap
        """
        from test_helpers import create_shift_payload, setup_home, setup_staff
        base = setup_agency_with_core_staff()
        d2 = setup_staff(base["agency"]["id"], "DSP", full_name="Dee Sptwo")  # CPR only
        home = setup_home(base["agency"], certified_bed_count=2)
        set_clock("2026-06-01T00:00:00Z")
        admin = TEST_USERS["agency_admin_headers"]
        # No prior shift: only the certification rule can fail.
        resp = api_client.create_shift(
            create_shift_payload(
                home["id"], d2["id"],
                window_start="2026-06-02T22:00:00Z", window_end="2026-06-03T06:00:00Z",
                shift_type="NIGHT", requires_med_pass=True,
            ), admin,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING)

    def test_certification_missing_beats_shift_overlap(self, api):
        """PRD 2.6: "then business-safety checks (certification, witness), then
        business-temporal checks (shift overlap, bed overlap, vehicle overlap,
        span containment)". A request violating both surfaces the certification
        error.

        Design: Difficulty/priority_pair_validation_conflict/safety_certification_beats_temporal_shift_overlap
        """
        from test_helpers import create_shift_payload, setup_home, setup_staff
        base = setup_agency_with_core_staff()
        d2 = setup_staff(base["agency"]["id"], "DSP", full_name="Dee Sptwo")  # CPR only
        home = setup_home(base["agency"], certified_bed_count=2)
        set_clock("2026-06-01T00:00:00Z")
        admin = TEST_USERS["agency_admin_headers"]
        get_success_data(api_client.create_shift(
            create_shift_payload(
                home["id"], d2["id"],
                window_start="2026-06-02T07:00:00Z", window_end="2026-06-02T15:00:00Z",
            ), admin,
        ))
        # 22:00 start is only 7h after the prior 15:00 end (overlap) AND the
        # shift requires med pass which D2 lacks (certification).
        resp = api_client.create_shift(
            create_shift_payload(
                home["id"], d2["id"],
                window_start="2026-06-02T22:00:00Z", window_end="2026-06-03T06:00:00Z",
                shift_type="NIGHT", requires_med_pass=True,
            ), admin,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING)
        _data, meta = validate_paginated(api_client.list_shifts(
            ANY, params={"staff_member_id": d2["id"]},
        ))
        assert meta["total_count"] == 1
