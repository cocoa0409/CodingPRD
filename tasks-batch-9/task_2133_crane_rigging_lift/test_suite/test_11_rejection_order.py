"""The order of rejection: which of two live failures the server must report,
and the cross-entity gate that stands between a plan and its rigging."""

from test_helpers import (
    ApiErrorId,
    DISPATCHER,
    LIFT_DIRECTOR,
    approve_plan,
    build_standard_world,
    create_gear_assignment_payload,
    inspect_gear,
    open_plan,
    read_gear,
    read_permit,
    read_plan,
    set_clock,
    set_credit_hold,
    setup_configured_plan,
    survey_plan,
    validate_error,
    validate_success,
)

EXPIRING_OPERATOR = {"certification_expires_on": "2026-09-01T00:00:00Z"}


class TestReleaseRejectionOrder:
    """Difficulty rule: priority_pair_validation_conflict."""

    def test_release_from_configured_reports_the_plan_state_failure(self, api):
        """PRD 2.7: "When a request violates more than one rule, the response is never
        ambiguous: checks run in a strict ascending priority order, and the **first**
        rule that fails determines both the `error_id` in the body and the HTTP
        status."
        PRD 2.7: "The target resource's own current state is a legal starting state
        for the requested transition, producing `ERR_INVALID_PLAN_STATE`,
        `ERR_INVALID_FIELD_STATE`, `ERR_INVALID_GEAR_STATE`,
        `ERR_INVALID_REVIEW_STATE`, `ERR_INVALID_PERMIT_STATE` or
        `ERR_INVALID_INVOICE_STATE` at HTTP 409."
        PRD 3.8: "It too takes no payload, and moves the plan `APPROVED → RELEASED`
        only if all of the following hold."

        Design: Difficulty/priority_pair_validation_conflict/release_plan_state_error_beats_operator_cert_expiry
        """
        world = build_standard_world(operator=EXPIRING_OPERATOR)
        ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-6200"})
        assert ctx["plan"]["plan_status"] == "CONFIGURED"

        validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                       ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)

    def test_plan_state_failure_pre_empts_the_certification_gate(self, api):
        """PRD 2.7: "Certification and qualification at release, at HTTP 422:
        `ERR_OPERATOR_CERT_EXPIRED`, `ERR_OPERATOR_ENDORSEMENT_INSUFFICIENT` and
        `ERR_RIGGER_QUALIFICATION_INSUFFICIENT`. Guards
        `POST /lift-plans/{id}/release` only."
        PRD 2.7: "A later, more interesting failure never masks an earlier one, and
        an earlier failure never yields to a later one because it seems less
        important."

        Design: Difficulty/priority_pair_validation_conflict/release_plan_state_error_beats_operator_cert_expiry
        """
        world = build_standard_world(operator=EXPIRING_OPERATOR)
        ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-6200"})

        error = validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                               ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_OPERATOR_CERT_EXPIRED.value
        assert read_plan(ctx["plan_id"])["plan_status"] == "CONFIGURED"

    def test_release_reports_the_expired_operator_certificate(self, api):
        """PRD 3.8: "The assigned operator's `certification_expires_on` must be
        strictly after the plan's `window_start` — a certificate that lapses partway
        through the window is not good enough — or the release fails with
        `ERR_OPERATOR_CERT_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/release_operator_cert_error_beats_customer_credit_hold
        """
        world = build_standard_world(operator=EXPIRING_OPERATOR)
        ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-6201"})
        approved = approve_plan(ctx["plan_id"])
        assert approved["plan_status"] == "APPROVED"
        held = set_credit_hold(world["cust_id"], True, "two invoices past NET_30")
        assert held["credit_hold"] is True

        validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                       ApiErrorId.ERR_OPERATOR_CERT_EXPIRED.value, 422)

    def test_certification_failure_pre_empts_the_credit_hold_check(self, api):
        """PRD 2.7: "Second, the credit-hold check at step 22 runs **after** every
        certification, permit and gear gate — so a release that fails both the
        operator's endorsement and the customer's credit standing reports the
        endorsement failure."
        PRD 3.8: "As §2.7 sets out, the credit check runs last of all, so a plan
        failing both a safety gate and the credit gate reports the safety gate."

        Design: Difficulty/priority_pair_validation_conflict/release_operator_cert_error_beats_customer_credit_hold
        """
        world = build_standard_world(operator=EXPIRING_OPERATOR)
        ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-6201"})
        approve_plan(ctx["plan_id"])
        set_credit_hold(world["cust_id"], True, "two invoices past NET_30")

        error = validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                               ApiErrorId.ERR_OPERATOR_CERT_EXPIRED.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value
        assert read_plan(ctx["plan_id"])["plan_status"] == "APPROVED"


class TestPermitSubmitRejectionOrder:
    """Difficulty rule: priority_pair_validation_conflict."""

    def test_permit_filing_reports_the_jurisdiction_mismatch(self, api):
        """PRD 3.7: "First, the permit's own `jurisdiction_code` must equal the
        `jurisdiction_code` of the site owning the permit's lift plan; a mismatch is
        `ERR_JURISDICTION_MISMATCH`."
        PRD 3.7: "The permit's `required_lead_days` is a base lead time determined by
        `permit_type` — 10 days for a `ROAD_CLOSURE`, 7 days for an
        `OVERSIZE_ESCORT`, and 3 days for a `CRANE_PLACEMENT` — plus a further 5 days
        when `escort_required` is true."

        Design: Difficulty/priority_pair_validation_conflict/permit_submit_jurisdiction_error_beats_lead_time_shortfall
        """
        world = build_standard_world()
        plan = open_plan(world, job_reference="JOB-6202", road_closure_requested=True)
        permit = validate_success(api.create_permit(
            {"lift_plan_id": plan["id"], "permit_type": "ROAD_CLOSURE",
             "jurisdiction_code": "NY-ROCKLAND"}, DISPATCHER), 201)
        assert permit["escort_required"] is False
        assert permit["required_lead_days"] == 10

        set_clock("2026-09-05T06:00:00Z")
        validate_error(api.submit_permit(permit["id"], DISPATCHER),
                       ApiErrorId.ERR_JURISDICTION_MISMATCH.value, 422)

    def test_jurisdiction_failure_pre_empts_the_lead_time_shortfall(self, api):
        """PRD 3.7: "Second, there must be enough runway: the interval from the
        logical clock to the plan's `window_start` must be at least
        `required_lead_days` multiplied by 24 hours, measured inclusively, so a filing
        that lands exactly on the lead time is accepted and one that lands a minute
        inside it is refused with `ERR_PERMIT_LEAD_TIME_SHORT`."
        PRD 3.7: "Because jurisdiction is checked first, an application that is both
        mis-addressed and too late reports the jurisdiction failure."
        PRD 3.7: "A successful filing moves the permit to `SUBMITTED` and stamps
        `submitted_at` with the logical clock; when the prior posture was `DENIED`,
        the stale `denial_reason` is cleared back to null in the same step."

        Design: Difficulty/priority_pair_validation_conflict/permit_submit_jurisdiction_error_beats_lead_time_shortfall
        """
        world = build_standard_world()
        plan = open_plan(world, job_reference="JOB-6202", road_closure_requested=True)
        permit = validate_success(api.create_permit(
            {"lift_plan_id": plan["id"], "permit_type": "ROAD_CLOSURE",
             "jurisdiction_code": "NY-ROCKLAND"}, DISPATCHER), 201)
        set_clock("2026-09-05T06:00:00Z")

        error = validate_error(api.submit_permit(permit["id"], DISPATCHER),
                               ApiErrorId.ERR_JURISDICTION_MISMATCH.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_PERMIT_LEAD_TIME_SHORT.value

        stored = read_permit(permit["id"])
        assert stored["status"] == "DRAFT"
        assert stored["submitted_at"] is None


class TestGearServiceabilityGate:
    """Difficulty rule: cross_entity_state_dependency."""

    def test_commitment_refused_while_the_gear_is_due_for_inspection(self, api):
        """PRD 3.2: "**New gear may not be committed to a plan until it has passed an
        inspection** — that is the whole point of starting it at `DUE_INSPECTION`."
        PRD 3.4: "Gear may only be committed while its posture is `SERVICEABLE`;
        committing gear that is due for inspection, quarantined or retired is refused
        with `ERR_GEAR_NOT_SERVICEABLE`."

        Design: Difficulty/cross_entity_state_dependency/gear_assignment_rejected_while_gear_is_not_serviceable
        """
        world = build_standard_world(serviceable_gear=False)
        plan = open_plan(world, job_reference="JOB-6400")
        survey_plan(world, plan["id"])

        gear = read_gear(world["gear_id"])
        assert gear["status"] == "DUE_INSPECTION"
        assert gear["version"] == 1

        payload = create_gear_assignment_payload(plan["id"], world["gear_id"], gear["version"])
        validate_error(api.create_gear_assignment(payload, DISPATCHER),
                       ApiErrorId.ERR_GEAR_NOT_SERVICEABLE.value, 409)

    def test_identical_commitment_succeeds_once_the_gear_passes_inspection(self, api):
        """PRD 3.2: "A `PASS` moves the gear to `SERVICEABLE`, whether it came from
        `DUE_INSPECTION`, from `QUARANTINED`, or from `SERVICEABLE` (re-inspecting
        already-serviceable gear is legal and simply refreshes the cadence)."
        PRD 3.4: "A new commitment is created `ACTIVE`. It permanently snapshots the
        gear's current derated limit into its own `effective_wll_lb`, resolves its
        `load_angle_factor` from the sling angle, and leaves `leg_tension_lb` at 0
        until the owning plan is next configured."
        PRD 3.4: "Creating the commitment recomputes the gear item's
        `committed_assignment_count` and increments that gear item's `version` by
        one."

        Design: Difficulty/cross_entity_state_dependency/gear_assignment_rejected_while_gear_is_not_serviceable
        """
        world = build_standard_world(serviceable_gear=False)
        plan = open_plan(world, job_reference="JOB-6400")
        survey_plan(world, plan["id"])

        stale = read_gear(world["gear_id"])["version"]
        validate_error(api.create_gear_assignment(
            create_gear_assignment_payload(plan["id"], world["gear_id"], stale), DISPATCHER),
            ApiErrorId.ERR_GEAR_NOT_SERVICEABLE.value, 409)

        inspect_gear(world["gear_id"], "PASS")
        serviceable = read_gear(world["gear_id"])
        assert serviceable["status"] == "SERVICEABLE"

        assignment = validate_success(api.create_gear_assignment(
            create_gear_assignment_payload(plan["id"], world["gear_id"],
                                           serviceable["version"]), DISPATCHER), 201)
        assert assignment["status"] == "ACTIVE"
        assert assignment["effective_wll_lb"] == 30_000
        assert read_gear(world["gear_id"])["committed_assignment_count"] == 1
