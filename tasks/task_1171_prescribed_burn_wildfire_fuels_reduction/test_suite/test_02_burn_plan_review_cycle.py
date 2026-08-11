"""Burn plan review cycle, plan-creation gates, and auth/ownership denials (PRD §2.1, §2.7, §2.8, §3.1, §3.2)."""
from test_helpers import (
    ANY_READER_HEADERS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_burn_plan_payload,
    create_parcel_payload,
    ctx_add_boss,
    ctx_add_parcel,
    ctx_add_plan,
    ctx_author,
    ctx_landowner,
    ctx_reviewer,
    default_treatment_lines,
    make_burn_boss_headers,
    make_landowner_headers,
    make_reviewer_headers,
    setup_registry,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPlanRevisionCycle:
    """Difficulty instance: cyclic DRAFT -> SUBMITTED -> REVISION_REQUESTED -> DRAFT loop."""

    def test_plan_revision_cycle_full_lap(self, api):
        """PRD §3.2: "The review loop is cyclic and may repeat without bound."
        PRD §2.4: "`version` — an integer that starts at its initial value on creation
        and increments by exactly one on every mutation, including system-driven state
        transitions."

        Design: Difficulty/non_linear_state_machine/burn_plan_revision_cycle
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx)
        s1 = validate_success(api.submit_plan(plan["id"], ctx_author(ctx)), 200)
        assert s1["status"] == "SUBMITTED" and s1["version"] == plan["version"] + 1
        s2 = validate_success(api.request_plan_revision(plan["id"], ctx_reviewer(ctx)), 200)
        assert s2["status"] == "REVISION_REQUESTED" and s2["version"] == s1["version"] + 1
        s3 = validate_success(api.revise_plan(plan["id"], ctx_author(ctx)), 200)
        assert s3["status"] == "DRAFT" and s3["version"] == s2["version"] + 1
        s4 = validate_success(api.submit_plan(plan["id"], ctx_author(ctx)), 200)
        assert s4["status"] == "SUBMITTED" and s4["version"] == s3["version"] + 1
        s5 = validate_success(api.approve_plan(plan["id"], ctx_reviewer(ctx)), 200)
        assert s5["status"] == "APPROVED" and s5["version"] == s4["version"] + 1
        assert s5["approved_by_boss_id"] == ctx["boss_r"]["id"]

    def test_plan_revision_loop_rejects_wrong_states(self, api):
        """PRD §3.2: "An `AgencyReviewer` may send a `SUBMITTED` plan back to
        `REVISION_REQUESTED` (any other state: `ERR_PLAN_NOT_SUBMITTED`), from which the
        author alone pulls it back to `DRAFT` via revision (`ERR_PLAN_NOT_IN_REVISION`
        otherwise, `ERR_NOT_RESOURCE_OWNER` for non-authors)."
        PRD §3.2: "The author submits a `DRAFT` plan, moving it to `SUBMITTED` —
        attempting this on anything but a `DRAFT` fails with `ERR_PLAN_NOT_DRAFT`"

        Design: Difficulty/non_linear_state_machine/burn_plan_revision_cycle
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        # revise requires REVISION_REQUESTED
        validate_error(api.revise_plan(plan["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_PLAN_NOT_IN_REVISION)
        # request-revision requires SUBMITTED: move back to DRAFT is impossible here,
        # so probe request-revision on a fresh DRAFT plan on a second parcel
        ctx_add_parcel(ctx, key="parcel_b", name="PB", airshed_id="ASH-2")
        plan_b = ctx_add_plan(ctx, key="plan_b", parcel_key="parcel_b")
        validate_error(api.request_plan_revision(plan_b["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_PLAN_NOT_SUBMITTED)
        # submit requires DRAFT: walk plan_b to REVISION_REQUESTED, then submit again
        submitted_b = validate_success(api.submit_plan(plan_b["id"], ctx_author(ctx)), 200)
        assert submitted_b["status"] == "SUBMITTED"
        rr = validate_success(api.request_plan_revision(plan_b["id"], ctx_reviewer(ctx)), 200)
        assert rr["status"] == "REVISION_REQUESTED"
        validate_error(api.submit_plan(plan_b["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_PLAN_NOT_DRAFT)


class TestPlanApprovalAndCancelGates:
    def test_approve_draft_plan_rejected(self, api):
        """PRD §3.2: "Approval is the consequential move: an `AgencyReviewer` approves a
        `SUBMITTED` plan to `APPROVED`"
        PRD §3.2: "An `AgencyReviewer` may send a `SUBMITTED` plan back to
        `REVISION_REQUESTED` (any other state: `ERR_PLAN_NOT_SUBMITTED`)"

        Design: Corner/state_machines/approve_draft_plan_rejected
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx)
        validate_error(api.approve_plan(plan["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_PLAN_NOT_SUBMITTED)
        after = validate_success(api.get_burn_plan(plan["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "DRAFT"

    def test_cancelled_plan_submit_rejected_terminal_lockdown(self, api):
        """PRD §3.2: "The author may cancel a plan while it is in `DRAFT`, `SUBMITTED`,
        `REVISION_REQUESTED`, or `APPROVED`; cancelling a terminal plan is rejected with
        `ERR_PLAN_NOT_CANCELLABLE`"
        PRD §3.2: "The author submits a `DRAFT` plan, moving it to `SUBMITTED` —
        attempting this on anything but a `DRAFT` fails with `ERR_PLAN_NOT_DRAFT`"

        Design: Corner/state_machines/cancelled_plan_submit_rejected_terminal_lockdown
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx)
        cancelled = validate_success(api.cancel_plan(plan["id"], ctx_author(ctx)), 200)
        assert cancelled["status"] == "CANCELLED"
        validate_error(api.submit_plan(plan["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_PLAN_NOT_DRAFT)


class TestPlanCreationGates:
    def test_occ_burn_plan_create_stale_parcel_version(self, api):
        """PRD §2.8: "If the parcel's current `version` differs — for example because
        another writer has just created a plan on the same parcel, which itself advances
        the parcel's version — the create is rejected with `ERR_STALE_VERSION` and HTTP
        status 412"

        Design: Corner/cross_cutting_layers/occ_burn_plan_create_stale_parcel_version
        """
        ctx = setup_registry()
        parcel = ctx_add_parcel(ctx)
        stale_version = parcel["version"]
        ctx_add_plan(ctx)  # advances the parcel's version
        resp = api.create_burn_plan(
            create_burn_plan_payload(parcel["id"], stale_version,
                                     planned_acres=50,
                                     planned_window_start="2026-06-01",
                                     planned_window_end="2026-06-30",
                                     treatment_lines=default_treatment_lines(50)),
            ctx_author(ctx))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_second_active_plan_rejected_for_parcel(self, api):
        """PRD §3.2: "A parcel may host at most one plan in an active status — `DRAFT`,
        `SUBMITTED`, `REVISION_REQUESTED`, or `APPROVED`; a second is rejected with
        `ERR_ACTIVE_PLAN_EXISTS_FOR_PARCEL`"

        Design: Corner/errors/second_active_plan_rejected_for_parcel
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        ctx_add_plan(ctx)  # plan A stays DRAFT; parcel version advanced
        parcel = validate_success(api.get_parcel(ctx["parcel"]["id"], ANY_READER_HEADERS), 200)
        resp = api.create_burn_plan(
            create_burn_plan_payload(parcel["id"], parcel["version"],
                                     planned_acres=50,
                                     planned_window_start="2026-06-01",
                                     planned_window_end="2026-06-30",
                                     treatment_lines=default_treatment_lines(50)),
            ctx_author(ctx))
        # OCC satisfied by the re-read version, so the uniqueness rule fires
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS_FOR_PARCEL)

    def test_burn_plan_create_missing_required_field(self, api):
        """PRD §3.2: "Malformed bodies, missing or unknown fields, type mismatches, empty
        `treatment_lines`, or line acreage not summing to `planned_acres` are rejected
        with `ERR_INVALID_REQUEST`"

        Design: Corner/entities/burn_plan_create_missing_required_field
        """
        ctx = setup_registry()
        parcel = ctx_add_parcel(ctx)
        payload = create_burn_plan_payload(parcel["id"], parcel["version"])
        del payload["min_rh_pct"]
        validate_error(api.create_burn_plan(payload, ctx_author(ctx)),
                       ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_parcel_create_rejects_unknown_field(self, api):
        """PRD §3.2: "Malformed bodies, missing or unknown fields, type mismatches, empty
        `treatment_lines`, or line acreage not summing to `planned_acres` are rejected
        with `ERR_INVALID_REQUEST`"

        Design: Corner/entities/parcel_create_rejects_unknown_field
        """
        ctx = setup_registry()
        payload = create_parcel_payload(ctx["landowner"]["id"])
        payload["hazard_score"] = 1  # computed server-side; an undeclared input
        validate_error(api.create_parcel(payload, ctx_landowner(ctx)),
                       ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_plan_get_not_found_returns_404(self, api):
        """PRD §2.6: "Existence failures carry resource-specific error codes —
        `ERR_ASSOCIATION_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`,
        `ERR_BOSS_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`,
        `ERR_SMOKE_APPROVAL_NOT_FOUND`, `ERR_CONTINGENCY_NOT_FOUND`,
        `ERR_IGNITION_PLAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_EXECUTION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` — with `ERR_NOT_FOUND` as the
        generic fallback."

        Design: Corner/entities/plan_get_not_found_returns_404
        """
        setup_registry()
        validate_error(api.get_burn_plan(NON_EXISTENT_UUID, ANY_READER_HEADERS),
                       ApiErrorId.ERR_PLAN_NOT_FOUND, expected_status=404)

    def test_plan_rejected_on_inverted_prescription(self, api):
        """PRD §3.2: "The prescription itself is six numbers: `max_wind_mph`,
        `min_fuel_moisture_pct` and `max_fuel_moisture_pct`, `min_rh_pct`, `min_temp_f`
        and `max_temp_f`, and `min_mixing_height_ft`; every minimum must not exceed its
        paired maximum."
        PRD §3.2: "inverted prescription ranges or windows and non-positive acreage with
        `ERR_INVALID_PRESCRIPTION_PARAMS`"

        Design: Corner/validations/plan_rejected_on_inverted_prescription
        """
        ctx = setup_registry()
        parcel = ctx_add_parcel(ctx)
        payload = create_burn_plan_payload(parcel["id"], parcel["version"],
                                           min_temp_f=90, max_temp_f=40)
        validate_error(api.create_burn_plan(payload, ctx_author(ctx)),
                       ApiErrorId.ERR_INVALID_PRESCRIPTION_PARAMS, expected_status=400)


class TestAuthAndOwnership:
    def test_non_author_cannot_submit_plan(self, api):
        """PRD §3.2: "The author submits a `DRAFT` plan, moving it to `SUBMITTED` —
        attempting this on anything but a `DRAFT` fails with `ERR_PLAN_NOT_DRAFT`, and
        only the author may submit, else `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/non_author_cannot_submit_plan
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx)
        boss_b = ctx_add_boss(ctx)
        validate_error(api.submit_plan(plan["id"], make_burn_boss_headers(boss_b["id"])),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        after = validate_success(api.get_burn_plan(plan["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "DRAFT"

    def test_author_cannot_approve_own_plan(self, api):
        """PRD §3.2: "an `AgencyReviewer` approves a `SUBMITTED` plan to `APPROVED`, but
        the reviewer's `X-User-ID` must differ from the plan's `author_boss_id` — a
        reviewer approving their own authored work is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/validations/author_cannot_approve_own_plan
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        # Same BurnBoss id acting in the reviewer capacity
        validate_error(api.approve_plan(plan["id"], make_reviewer_headers(ctx["boss_a"]["id"])),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        after = validate_success(api.get_burn_plan(plan["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "SUBMITTED"

    def test_role_violation_beats_not_found(self, api):
        """PRD §2.7: "the server evaluates them in a fixed order so that the surfaced
        error is deterministic: first the presence of the two authentication headers;
        second role authorization for the endpoint; third left-to-right existence of
        path resources"
        PRD §2.1: "A request whose role is not authorized for the target endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/validations/role_violation_beats_not_found
        """
        ctx = setup_registry()
        # Landowner role on a BurnBoss-only action against a non-existent plan id:
        # role authorization (layer 2) fires before existence (layer 3).
        validate_error(api.submit_plan(NON_EXISTENT_UUID, ctx_landowner(ctx)),
                       ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_landowner_cannot_approve_plan(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/landowner_cannot_approve_plan
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        validate_error(api.approve_plan(plan["id"], ctx_landowner(ctx)),
                       ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_parcel_creation_rejected_without_waiver(self, api):
        """PRD §3.1: "the waiver must be on file: a caller whose `liability_waiver_signed`
        is not true is rejected with `ERR_LANDOWNER_WAIVER_UNSIGNED`."

        Design: Corner/validations/parcel_creation_rejected_without_waiver
        """
        ctx = setup_registry(waiver_signed=False)
        validate_error(api.create_parcel(
            create_parcel_payload(ctx["landowner"]["id"]), ctx_landowner(ctx)),
            ApiErrorId.ERR_LANDOWNER_WAIVER_UNSIGNED, expected_status=403)


class TestCertificationGate:
    def test_certification_tier_boundary_70_passes_71_rejected(self, api):
        """PRD §3.2: "an `RXB2` boss only when `planned_acres` is at most 200 and the
        `hazard_score` is at most 70"
        PRD §3.2: "All bounds are inclusive, and a violation is rejected with
        `ERR_BOSS_CERTIFICATION_INSUFFICIENT`."

        Design: Corner/calculations/certification_tier_boundary_70_passes_71_rejected
        """
        ctx = setup_registry()
        ctx_add_boss(ctx, key="boss_b2", certification_tier="RXB2")
        boss_b2_h = make_burn_boss_headers(ctx["boss_b2"]["id"])
        # hazard = BRUSH 35 + STEEP 20 + drought 15 = 70 (inclusive ceiling: passes)
        parcel_a = ctx_add_parcel(ctx, key="parcel_a", name="PA", acreage=300,
                                  slope_class="STEEP", drought_index=15)
        assert parcel_a["hazard_score"] == 70
        plan_a = validate_success(api.create_burn_plan(
            create_burn_plan_payload(parcel_a["id"], parcel_a["version"],
                                     planned_acres=150,
                                     treatment_lines=[{"category": "BROADCAST",
                                                       "rate_class": "BRUSH",
                                                       "acres": 150}]),
            boss_b2_h), 201)
        assert plan_a["status"] == "DRAFT"
        # hazard 71 (> 70): rejected
        parcel_b = ctx_add_parcel(ctx, key="parcel_b", name="PB", acreage=300,
                                  slope_class="STEEP", drought_index=16)
        assert parcel_b["hazard_score"] == 71
        validate_error(api.create_burn_plan(
            create_burn_plan_payload(parcel_b["id"], parcel_b["version"],
                                     planned_acres=150,
                                     treatment_lines=[{"category": "BROADCAST",
                                                       "rate_class": "BRUSH",
                                                       "acres": 150}]),
            boss_b2_h),
            ApiErrorId.ERR_BOSS_CERTIFICATION_INSUFFICIENT, expected_status=403)
