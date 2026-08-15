"""Design review cycle, variance relief, design-level authorization and OCC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_design,
    add_variance_request,
    api_client,
    approve_design,
    approve_variance,
    freeze_site,
    get_design,
    reject_design,
    revise_design_payload,
    setup_site_with_science,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRejectReviseResubmitCycle:
    def test_reject_then_revise_returns_to_draft_with_version_bump(self, api):
        """PRD section 3.4: "Rejection moves the design to `REJECTED` and requires
        a `decision_note` of at least 20 characters, else `ERR_INSUFFICIENT_NOTE`."
        PRD section 3.4: "The authoring designer may return a `REJECTED` design to
        `DRAFT` for rework — the cyclic edge of the design machine — through the
        revision action, which requires the OCC token `expected_design_version`
        equal to the design's current `version` per §2.7 and bumps `version` by
        one on success."

        Design: Difficulty/non_linear_state_machine/design_reject_revise_resubmit_cycle
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        rejected = reject_design(ctx, d["id"])
        assert rejected["status"] == "REJECTED"
        revised = validate_success(api_client.revise_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            revise_design_payload(rejected["version"]), ctx.designer))
        assert revised["status"] == "DRAFT"
        assert revised["version"] == rejected["version"] + 1, (
            "the loop back-edge bumped the OCC version")

    def test_resubmit_after_revise_reaches_approved(self, api):
        """PRD section 3.4: "The authoring designer may return a `REJECTED` design
        to `DRAFT` for rework — the cyclic edge of the design machine — through
        the revision action, which requires the OCC token `expected_design_version`
        equal to the design's current `version` per §2.7 and bumps `version` by
        one on success."
        PRD section 3.4: "Approval moves the design to `APPROVED`, a terminal
        state".

        Design: Difficulty/non_linear_state_machine/design_reject_revise_resubmit_cycle
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        rejected = reject_design(ctx, d["id"])
        revised = validate_success(api_client.revise_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            revise_design_payload(rejected["version"]), ctx.designer))
        assert revised["status"] == "DRAFT"
        resubmitted = submit_design(ctx, d["id"])
        assert resubmitted["status"] == "SUBMITTED"
        approved = approve_design(ctx, d["id"])
        assert approved["status"] == "APPROVED", "the cycle terminates in approval"


class TestApprovedDesignSingleton:
    def test_second_approval_restores_approved_singleton(self, api):
        """PRD section 3.4: "Approval moves the design to `APPROVED`, a terminal
        state, and triggers the supersession cascade of §2.8 — any other
        `APPROVED` design for the same site moves to `SUPERSEDED`, permits pinning
        it move to `SUSPENDED`, and their non-terminal installations are forced to
        `FAILED_HOLD`."

        Design: Difficulty/compensating_invariant/revise_resubmit_cycle_conserves_approved_design_singleton
        """
        ctx = setup_site_with_science()
        da = add_design(ctx, bedroom_count=3)
        db = add_design(ctx, bedroom_count=4)
        submit_design(ctx, da["id"])
        submit_design(ctx, db["id"])
        approve_design(ctx, da["id"])
        approved_b = approve_design(ctx, db["id"])
        assert approved_b["status"] == "APPROVED"
        assert get_design(ctx, da["id"])["status"] == "SUPERSEDED", (
            "the compensating supersession restored the singleton invariant")

    def test_approved_filter_lists_exactly_one_after_supersession(self, api):
        """PRD section 3.4: "Approval moves the design to `APPROVED`, a terminal
        state, and triggers the supersession cascade of §2.8 — any other
        `APPROVED` design for the same site moves to `SUPERSEDED`".
        PRD section 2.3: "Site, soil evaluation, percolation test, design, permit,
        installation, variance request, maintenance contract, and repair case
        lists accept a `status` filter".

        Design: Difficulty/compensating_invariant/revise_resubmit_cycle_conserves_approved_design_singleton
        """
        ctx = setup_site_with_science()
        da = add_design(ctx, bedroom_count=3)
        db = add_design(ctx, bedroom_count=4)
        submit_design(ctx, da["id"])
        submit_design(ctx, db["id"])
        approve_design(ctx, da["id"])
        approve_design(ctx, db["id"])
        approved, meta = validate_paginated(api_client.list_designs(
            ctx.cid, ctx.cu, ctx.s, ctx.manager, params={"status": "APPROVED"}))
        assert len(approved) == 1 and approved[0]["id"] == db["id"]
        assert meta["total_count"] == 1


class TestSubmitPrecedence:
    def test_submit_non_draft_on_frozen_site_reports_state_error(self, api):
        """PRD section 2.9: "When a single request violates more than one rule,
        the applicable checks are evaluated in a fixed precedence order and only
        the first failure is reported."
        PRD section 2.9: "(5) admissibility of the requested state transition —
        `ERR_INVALID_STATE`" is ordered before "(6) seasonal freeze blocking —
        `ERR_SITE_FROZEN`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_frozen_site_submit
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])  # no longer DRAFT
        freeze_site(ctx, 3)          # site now FROZEN too
        resp = api_client.submit_design(ctx.cid, ctx.cu, ctx.s, d["id"], ctx.designer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_submit_draft_on_frozen_site_reports_site_frozen(self, api):
        """PRD section 3.4: "The site must be `OPEN`; a submit against a `FROZEN`
        site is refused with `ERR_SITE_FROZEN`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_frozen_site_submit
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        freeze_site(ctx, 3)
        resp = api_client.submit_design(ctx.cid, ctx.cu, ctx.s, d["id"], ctx.designer)
        validate_error(resp, ApiErrorId.ERR_SITE_FROZEN)


class TestInvalidTransitionsOnDesign:
    def test_design_withdraw_from_submitted_rejected(self, api):
        """PRD section 3.4: "A designer may also withdraw a `DRAFT` design
        outright, moving it to `WITHDRAWN`".
        PRD section 2.9: "(5) admissibility of the requested state transition —
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/design_withdraw_from_submitted_rejected
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        resp = api_client.withdraw_design(ctx.cid, ctx.cu, ctx.s, d["id"], ctx.designer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_design(ctx, d["id"])["status"] == "SUBMITTED"

    def test_terminal_state_lockdown_on_approved_design(self, api):
        """PRD section 3.4: "Approval moves the design to `APPROVED`, a terminal
        state, and triggers the supersession cascade of §2.8".
        PRD section 2.9: "(5) admissibility of the requested state transition —
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/terminal_state_lockdown_on_approved_design
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        approved = approve_design(ctx, d["id"])
        assert approved["status"] == "APPROVED"

        resp_submit = api_client.submit_design(ctx.cid, ctx.cu, ctx.s, d["id"], ctx.designer)
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE)
        resp_withdraw = api_client.withdraw_design(ctx.cid, ctx.cu, ctx.s, d["id"], ctx.designer)
        validate_error(resp_withdraw, ApiErrorId.ERR_INVALID_STATE)
        resp_revise = api_client.revise_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            revise_design_payload(approved["version"]), ctx.designer)
        validate_error(resp_revise, ApiErrorId.ERR_INVALID_STATE)


class TestDecisionPayloadRules:
    def test_error_insufficient_note_on_reject(self, api):
        """PRD section 3.4: "Rejection moves the design to `REJECTED` and requires
        a `decision_note` of at least 20 characters, else `ERR_INSUFFICIENT_NOTE`."

        Design: Corner/validations/error_insufficient_note_on_reject
        """
        ctx = setup_site_with_science()
        da = add_design(ctx, bedroom_count=3)
        db = add_design(ctx, bedroom_count=4)
        submit_design(ctx, da["id"])
        submit_design(ctx, db["id"])

        resp = api_client.decide_design(
            ctx.cid, ctx.cu, ctx.s, da["id"],
            {"decision": "REJECT", "officer_id": ctx.h1, "decision_note": "too short"},
            ctx.officer)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_NOTE)
        assert get_design(ctx, da["id"])["status"] == "SUBMITTED"

        ok = validate_success(api_client.decide_design(
            ctx.cid, ctx.cu, ctx.s, db["id"],
            {"decision": "REJECT", "officer_id": ctx.h1,
             "decision_note": "exactly twenty chars"},
            ctx.officer))
        assert ok["status"] == "REJECTED", "a note of exactly 20 characters passes"

    def test_error_invalid_decision_enum_rejected(self, api):
        """PRD section 3.4: "Decision power over a submitted design rests with a
        `HealthOfficer`, who supplies a `decision` of `APPROVE` or `REJECT`
        together with an `officer_id`; any other decision value is
        `ERR_INVALID_DECISION` (HTTP 400)."

        Design: Corner/validations/error_invalid_decision_enum_rejected
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        resp = api_client.decide_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            {"decision": "MAYBE", "officer_id": ctx.h1}, ctx.officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_DECISION)
        assert get_design(ctx, d["id"])["status"] == "SUBMITTED"


class TestVarianceLifecycle:
    def test_variance_request_decide_and_withdraw_paths(self, api):
        """PRD section 3.4: "Approval moves the request to `APPROVED`, records
        `decided_by` as the deciding officer, and keeps any supplied
        `decision_note`; denial moves it to `DENIED` and requires a
        `decision_note` of at least 20 characters. A designer may also withdraw a
        still-`PENDING` request, moving it to `WITHDRAWN`."
        PRD section 2.9: "(5) admissibility of the requested state transition —
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/variance_request_decide_and_withdraw_paths
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        va = add_variance_request(
            ctx, d["id"], relief_kind="SETBACK_REDUCTION",
            justification="Well setback cannot be met otherwise")
        vb = add_variance_request(
            ctx, d["id"], relief_kind="AREA_REDUCTION",
            justification="Lot coverage forces a smaller field")

        denied = validate_success(api_client.decide_variance_request(
            ctx.cid, ctx.cu, ctx.s, va["id"],
            {"decision": "DENY", "officer_id": ctx.h1,
             "decision_note": "Setback relief not justified by soils"},
            ctx.officer))
        assert denied["status"] == "DENIED"
        assert denied["decided_by"] == ctx.h1

        withdrawn = validate_success(api_client.withdraw_variance_request(
            ctx.cid, ctx.cu, ctx.s, vb["id"], ctx.designer))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api_client.withdraw_variance_request(ctx.cid, ctx.cu, ctx.s, va["id"], ctx.designer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_error_variance_required_on_high_water_gravity_approval(self, api):
        """PRD section 3.4: "when the site's `high_water_table` flag is true and
        the design's `system_type` is `GRAVITY`, an `APPROVED` variance request of
        relief kind `HIGH_WATER_TABLE` must already exist for this design, else
        the approval fails with `ERR_VARIANCE_REQUIRED`."

        Design: Corner/errors/error_variance_required_on_high_water_gravity_approval
        """
        ctx = setup_site_with_science(
            soil_class="SAND", limiting_layer_inches=40, high_water_table=True,
            minutes_per_inch=5.0, test_pit_count=3)
        d = add_design(ctx, bedroom_count=3, system_type="GRAVITY")
        submit_design(ctx, d["id"])
        variance = add_variance_request(
            ctx, d["id"], relief_kind="HIGH_WATER_TABLE",
            justification="Seasonal water table documented by county")

        resp = api_client.decide_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            {"decision": "APPROVE", "officer_id": ctx.h1}, ctx.officer)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_REQUIRED)

        approve_variance(ctx, variance["id"])
        approved = approve_design(ctx, d["id"])
        assert approved["status"] == "APPROVED"


class TestForeignKeysAndRoleDenial:
    def test_error_fk_not_found_on_design_create(self, api):
        """PRD section 2.9: "(4) existence and same-company/same-site scope of
        every foreign key supplied in the request body (`evaluator_id`,
        `designer_id`, `soil_evaluation_id`, `percolation_test_id`, `permit_id`,
        `design_id`, `installation_id`, `inspector_id`, `officer_id`,
        `failed_installation_id`, `replacement_design_id`) — `ERR_FK_NOT_FOUND`
        (HTTP 422)".

        Design: Corner/validations/error_fk_not_found_on_design_create
        """
        ctx = setup_site_with_science()
        resp = api_client.create_design(
            ctx.cid, ctx.cu, ctx.s,
            {"designer_id": ctx.d1, "soil_evaluation_id": NON_EXISTENT_UUID,
             "percolation_test_id": ctx.pt1, "bedroom_count": 3,
             "system_type": "GRAVITY"},
            ctx.designer)
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)

    def test_designer_cannot_decide_own_or_any_design(self, api):
        """PRD section 2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: "| POST | /septic-ops/installer-companies/{cid}/customers/{cuid}/sites/{sid}/designs/{did}/decide | Approve or reject a SUBMITTED design | HealthOfficer |"

        Design: Corner/rbac/designer_cannot_decide_own_or_any_design
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        resp = api_client.decide_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            {"decision": "APPROVE", "officer_id": ctx.d1}, ctx.designer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_segregation_of_duties_same_person_cannot_approve_own_design(self, api):
        """PRD section 3.4: "the officer must not be the same person as the
        authoring designer, and a health officer row whose `badge_number` equals
        the authoring designer's `license_number` is treated as the same person,
        failing with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_same_person_cannot_approve_own_design
        """
        ctx = setup_site_with_science(
            designer_license="DSGN-DUAL", designer_name="Dana Dual",
            officer_badge="DSGN-DUAL", officer_name="Dana Dual",
            second_officer_badge="HO-1")
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        resp = api_client.decide_design(
            ctx.cid, ctx.cu, ctx.s, d["id"],
            {"decision": "APPROVE", "officer_id": ctx.h1}, ctx.officer)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = approve_design(ctx, d["id"], officer=ctx.h2, officer_headers=ctx.officer2)
        assert approved["status"] == "APPROVED"


class TestOccOnDesignRevise:
    def test_occ_stale_version_on_design_revise(self, api):
        """PRD section 2.7: "Returning a rejected design to draft requires
        `expected_design_version`, carrying the client's last observed `version`
        of that design. If the design's current `version` has advanced since — for
        instance because another writer already revised it, legitimately moving it
        back to `DRAFT` and bumping the version — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from revising a
        design it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_design_revise
        """
        ctx = setup_site_with_science()
        d = add_design(ctx, bedroom_count=3)
        submit_design(ctx, d["id"])
        rejected = reject_design(ctx, d["id"])
        v_rej = rejected["version"]
        revised = validate_success(api_client.revise_design(
            ctx.cid, ctx.cu, ctx.s, d["id"], revise_design_payload(v_rej), ctx.designer))
        assert revised["status"] == "DRAFT"
        submit_design(ctx, d["id"])
        rejected2 = reject_design(ctx, d["id"], decision_note="Still missing well setback line")
        v_rej2 = rejected2["version"]

        stale = api_client.revise_design(
            ctx.cid, ctx.cu, ctx.s, d["id"], revise_design_payload(v_rej), ctx.designer)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        ok = validate_success(api_client.revise_design(
            ctx.cid, ctx.cu, ctx.s, d["id"], revise_design_payload(v_rej2), ctx.designer))
        assert ok["status"] == "DRAFT"
        assert ok["version"] == v_rej2 + 1
