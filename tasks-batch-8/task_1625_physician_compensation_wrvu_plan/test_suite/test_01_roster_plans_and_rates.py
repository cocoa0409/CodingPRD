"""Physician roster, plan drafting/review/activation, rate windows, and OCC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_comp_plan,
    create_active_plan,
    create_comp_plan_payload,
    create_cpt_rate_payload,
    create_draft_plan,
    create_pending_review_plan,
    create_physician_payload,
    get_success_data,
    make_physician_headers,
    register_physician,
    review_decision_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
COMMITTEE = TEST_USERS["committee_headers"]


class TestPhysicianRegistration:
    def test_missing_npi_rejected(self, api):
        """PRD §3.1: "Registration captures the clinician's `npi` (a National Provider Identifier of exactly 10 digits, unique across all physicians)"
        PRD §3.1: "Payload-shape failures on any of these inputs — a missing required field, a wrong type, an out-of-range enum, an `fte` outside the allowed band, a malformed date — are rejected with `ERR_VALIDATION`."

        Design: Corner/entities/physician_create_missing_required_npi
        """
        payload = create_physician_payload()
        del payload["npi"]
        resp = api.create_physician(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_provider_type_enum_rejected(self, api):
        """PRD §3.1: "`provider_type` (one of `PHYSICIAN` or `APP` — a physician can supervise and holds a compensation agreement, while an advanced-practice provider's production can generate supervision credits)"
        PRD §3.1: "Payload-shape failures on any of these inputs — a missing required field, a wrong type, an out-of-range enum, an `fte` outside the allowed band, a malformed date — are rejected with `ERR_VALIDATION`."

        Design: Corner/entities/physician_create_invalid_enum_provider_type
        """
        resp = api.create_physician(
            create_physician_payload(npi="1000000201", provider_type="DO"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_fte_outside_allowed_band_rejected(self, api):
        """PRD §3.1: "clinical `fte` (a fraction greater than 0 and at most 1.0, used to prorate tier thresholds)"
        PRD §3.1: "Payload-shape failures on any of these inputs — a missing required field, a wrong type, an out-of-range enum, an `fte` outside the allowed band, a malformed date — are rejected with `ERR_VALIDATION`."

        Design: Corner/entities/physician_create_invalid_fte_range
        """
        resp = api.create_physician(
            create_physician_payload(npi="1000000202", fte=1.5), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_nonexistent_physician_returns_404(self, api):
        """PRD §2.9: "Existence follows: path parameters and body foreign-key references must resolve to existing resources, validated left to right along the path, otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/physician_get_not_found_returns_404
        """
        resp = api.get_physician(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPlanCreation:
    def test_plan_create_applies_defaults(self, api):
        """PRD §3.1: "a `credit_attribution_mode` of `SERVICE_DATE` or `POSTING_DATE` defaulting to `SERVICE_DATE` when omitted, a `quality_model` of `ALL_OR_NOTHING` or `SLIDING_SCALE` defaulting to `ALL_OR_NOTHING`"
        PRD §3.1: "A plan is born in `DRAFT` status with `version` 1"
        PRD §3.2: "stamps `activated_at` with the logical-clock timestamp (the field stays null until this moment)"

        Design: Corner/entities/plan_create_defaults_applied
        """
        payload = create_comp_plan_payload(name="Defaults Plan")
        assert "credit_attribution_mode" not in payload
        assert "quality_model" not in payload
        resp = api.create_comp_plan(payload, ANALYST)
        plan = validate_success(resp, 201)
        assert_comp_plan(plan)
        assert plan["credit_attribution_mode"] == "SERVICE_DATE", "default attribution mode"
        assert plan["quality_model"] == "ALL_OR_NOTHING", "default quality model"
        assert plan["status"] == "DRAFT", "A plan is born in DRAFT status"
        assert plan["version"] == 1, "A plan is born with version 1"
        assert plan["activated_at"] is None, "activated_at stays null until activation"

    def test_non_increasing_tier_thresholds_rejected(self, api):
        """PRD §3.1: "The tier schedule must contain at least one tier, its first `threshold_wrvu` must be 0, and thresholds must be strictly increasing; a schedule violating any of these is rejected with `ERR_TIER_ORDER_INVALID`."

        Design: Corner/entities/plan_create_invalid_tier_order
        """
        bad_tiers = [
            {"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4500,
             "tier_bonus_cents": 0},
            {"tier_code": "T2", "threshold_wrvu": 5000, "conversion_factor_cents": 5500,
             "tier_bonus_cents": 0},
            {"tier_code": "T3", "threshold_wrvu": 4000, "conversion_factor_cents": 6500,
             "tier_bonus_cents": 0},
        ]
        resp = api.create_comp_plan(
            create_comp_plan_payload(name="BadTiers", tiers=bad_tiers), ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_TIER_ORDER_INVALID)


class TestRateRows:
    def test_rate_row_under_nonexistent_plan_returns_404(self, api):
        """PRD §2.10: "On any nested request, path parameters are validated from left to right: the parent must exist, then the child must exist and belong to that parent, and the first failure yields `ERR_NOT_FOUND`."

        Design: Corner/entities/cpt_rate_parent_not_found
        """
        resp = api.create_cpt_rate(NON_EXISTENT_UUID, create_cpt_rate_payload(), ANALYST)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_overlapping_window_rejected_and_other_code_allowed(self, api):
        """PRD §3.1: "Two rows on the same plan with the same `cpt_code` may not have overlapping windows — adjacency, where one row's `effective_to` equals the next row's `effective_from`, is allowed — and an overlapping addition is rejected with `ERR_RATE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cpt_rate_window_half_open_overlap
        """
        plan, _ = create_draft_plan(name="Window Plan")
        # Interior overlap with the seeded 99213 [2026-01-01, 2027-01-01) window.
        resp_overlap = api.create_cpt_rate(
            plan["id"],
            create_cpt_rate_payload(wrvu_value=1.05, effective_from="2026-06-01",
                                    effective_to="2027-06-01"),
            ANALYST,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)
        # Overlap rule is scoped to (plan, cpt_code): another code may share the window.
        resp_other = api.create_cpt_rate(
            plan["id"],
            create_cpt_rate_payload(cpt_code="99215", wrvu_value=1.50,
                                    effective_from="2026-06-01", effective_to="2027-06-01"),
            ANALYST,
        )
        validate_success(resp_other, 201)

    def test_adjacent_window_allowed_and_listed(self, api):
        """PRD §3.1: "the row covers service dates from `effective_from` inclusive up to but not including `effective_to`"
        PRD §3.1: "adjacency, where one row's `effective_to` equals the next row's `effective_from`, is allowed"
        PRD §3.1: "The plan's rate listing supports an optional `cpt_code` filter alongside `limit` and `offset`."

        Design: Difficulty/resource_temporal_overlap/cpt_rate_window_half_open_overlap
        """
        plan, rate_ids = create_draft_plan(name="Adjacent Plan")
        resp_adjacent = api.create_cpt_rate(
            plan["id"],
            create_cpt_rate_payload(wrvu_value=1.05, effective_from="2027-01-01",
                                    effective_to="2028-01-01"),
            ANALYST,
        )
        adjacent = validate_success(resp_adjacent, 201)
        rows, meta = validate_paginated(
            api.list_cpt_rates(plan["id"], ANALYST, params={"cpt_code": "99213"})
        )
        assert meta["total_count"] == 2, "original row plus the adjacent row"
        assert {r["id"] for r in rows} == {rate_ids[0], adjacent["id"]}


class TestPlanLifecycle:
    def test_activate_from_draft_rejected(self, api):
        """PRD §3.2: "a `CompCommittee` member activates an `FMV_APPROVED` plan"
        PRD §3.2: "Attempting activation from any other status is rejected with `ERR_PLAN_NOT_FMV_APPROVED`"

        Design: Corner/state_machines/plan_activate_from_draft_rejected
        """
        plan, _ = create_draft_plan(name="Skip Plan")
        resp = api.activate_plan(plan["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FMV_APPROVED)
        after = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        assert after["status"] == "DRAFT", "rejected activation must not change state"

    def test_review_reject_reverts_to_draft_and_editable(self, api):
        """PRD §3.2: "a `REJECTED` decision sends it back to `DRAFT` for editing — the review loop branches and reverts rather than terminating."
        PRD §2.6: "A compensation plan's configuration — its name, attribution mode, quality model, tier schedule, quality pool, FMV cap — and its rate rows are mutable only while the plan is in `DRAFT` or `PENDING_REVIEW` status."

        Design: Corner/state_machines/plan_review_reject_reverts_to_draft
        """
        plan, _ = create_pending_review_plan(name="Revert Plan")
        resp = api.plan_review_decision(
            plan["id"], review_decision_payload("REJECTED"), OFFICER
        )
        rejected = validate_success(resp, 200)
        assert rejected["status"] == "DRAFT", "REJECTED sends PENDING_REVIEW back to DRAFT"
        current = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        resp_put = api.update_comp_plan(
            plan["id"],
            {"expected_comp_plan_version": current["version"], "quality_pool_cents": 150000},
            ANALYST,
        )
        edited = validate_success(resp_put, 200)
        assert edited["quality_pool_cents"] == 150000, "the plan is editable again in DRAFT"

    def test_submit_review_without_rates_rejected(self, api):
        """PRD §3.2: "Submitting a plan with no rate rows at all is rejected with `ERR_RATE_COVERAGE_INCOMPLETE`, as is any later activation attempt in that condition."

        Design: Corner/state_machines/plan_submit_review_without_rates_rejected
        """
        plan, _ = create_draft_plan(name="Bare Plan", rates=[])
        resp = api.submit_plan_review(plan["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_RATE_COVERAGE_INCOMPLETE)
        after = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        assert after["status"] == "DRAFT", "rejected submission must not change state"

    def test_plan_immutable_after_activation(self, api):
        """PRD §2.6: "A compensation plan's configuration — its name, attribution mode, quality model, tier schedule, quality pool, FMV cap — and its rate rows are mutable only while the plan is in `DRAFT` or `PENDING_REVIEW` status. Any attempt to edit the plan configuration, add a rate row, or delete a rate row once the plan has left those statuses is rejected with `ERR_PLAN_IMMUTABLE` (HTTP 409)."

        Design: Corner/validations/plan_immutable_after_activation
        """
        set_clock()
        plan, _ = create_active_plan(name="Frozen Plan")
        current = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        resp_put = api.update_comp_plan(
            plan["id"],
            {"expected_comp_plan_version": current["version"], "quality_pool_cents": 200000},
            ANALYST,
        )
        validate_error(resp_put, ApiErrorId.ERR_PLAN_IMMUTABLE)
        resp_rate = api.create_cpt_rate(
            plan["id"], create_cpt_rate_payload(cpt_code="99214", wrvu_value=1.5), ANALYST
        )
        validate_error(resp_rate, ApiErrorId.ERR_PLAN_IMMUTABLE)
        after = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        assert after["quality_pool_cents"] == 100000, "rejected edits must not apply"


class TestAuthLadder:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, carrying an undeclared role, or — for the `Physician` role — carrying an `X-User-ID` that is not the `id` of an existing physician is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_physician(create_physician_payload(npi="1000000230"), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_role_denied_before_existence_check(self, api):
        """PRD §2.9: "Authentication comes first (missing, malformed, or unresolvable identity — `ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then physician ownership (`ERR_NOT_OWN_RESOURCE`). Existence follows"
        PRD §4: GET /comp/comp-plans/{id} is authorized for CompAnalyst, CompCommittee, ComplianceOfficer — Physician is not listed.

        Design: Corner/validations/role_denied_before_existence_check
        """
        physician = register_physician(npi="1000000231", full_name="Dr Nope")
        resp = api.get_comp_plan(NON_EXISTENT_UUID, make_physician_headers(physician["id"]))
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert resp.status_code == 403, "role gate fires before the existence check (no 404 leak)"
        assert err["error_id"] != "ERR_NOT_FOUND"

    def test_physician_cannot_create_plan(self, api):
        """PRD §4: POST /comp/comp-plans is authorized for CompAnalyst only.
        PRD §2.1: "A request whose role is not listed among the roles authorized for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/physician_cannot_create_plan
        """
        physician = register_physician(npi="1000000270", full_name="Dr Rbac")
        resp = api.create_comp_plan(
            create_comp_plan_payload(name="Nope Plan"),
            make_physician_headers(physician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestPlanOcc:
    def test_stale_version_update_rejected(self, api):
        """PRD §2.6: "Editing a plan's configuration requires the request to carry `expected_comp_plan_version`, the plan `version` the client last observed. If the plan's current `version` has advanced beyond that value — because another writer submitted the plan for review, edited it, or otherwise mutated it in the meantime — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than applied over changes the client never saw."
        PRD §2.5: "`version`, an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource"

        Design: Corner/cross_cutting_layers/occ_plan_update_stale_version
        """
        plan, _ = create_draft_plan(name="OCC Plan", rates=[])
        observed = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        resp_first = api.update_comp_plan(
            plan["id"],
            {"expected_comp_plan_version": observed["version"], "quality_pool_cents": 150000},
            ANALYST,
        )
        updated = validate_success(resp_first, 200)
        assert updated["version"] == observed["version"] + 1, "first write increments version"
        resp_stale = api.update_comp_plan(
            plan["id"],
            {"expected_comp_plan_version": observed["version"], "quality_pool_cents": 175000},
            ANALYST,
        )
        validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api.get_comp_plan(plan["id"], ANALYST))
        assert after["quality_pool_cents"] == 150000, "only the first write may apply"
