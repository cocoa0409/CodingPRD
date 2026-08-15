"""Violations: detection, notice, cure, escalation, and the clock-sweep cascade
(PRD §3.3, §2.5, §2.10)."""
from test_helpers import (
    ApiErrorId,
    STANDARD_MATRIX,
    create_recorded_easement,
    create_requested_use_authorization,
    create_violation_payload,
    decide_use_authorization_payload,
    get_easement,
    make_coordinator_headers,
    make_field_monitor_headers,
    make_landowner_headers,
    set_clock,
    setup_open_violation,
    setup_violation_cure_in_progress,
    setup_violation_notice_sent,
    validate_error,
    validate_paginated,
    validate_success,
)


def _get_violation(api, violation_id, headers):
    return validate_success(api.get_violation(violation_id, headers), 200)


class TestViolationStateRules:
    def test_violation_resolve_from_open_rejected(self, api, trust_admin_headers):
        """PRD §3.3: "A coordinator then verifies the cure, moving the violation
        from `CURE_IN_PROGRESS` to `RESOLVED`"
        PRD §2.9: "State — the target resource must be in a state from which the
        requested transition exists: `ERR_INVALID_BASELINE_STATE`,
        `ERR_INVALID_VISIT_STATE`, `ERR_INVALID_VIOLATION_STATE`,
        `ERR_INVALID_AMENDMENT_STATE`, `ERR_INVALID_USE_AUTHORIZATION_STATE`,
        `ERR_INVALID_ENFORCEMENT_STATE`, `ERR_INVALID_NOTICE_STATE`, or
        `ERR_INVALID_APPRAISAL_STATE` (all 409)."

        Design: Corner/state_machines/violation_resolve_from_open_rejected
        """
        ctx = setup_open_violation(severity="MINOR", violation_type="SUBDIVISION")
        resp = api.resolve_violation(
            ctx["violation"]["id"], make_coordinator_headers("coord-2")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VIOLATION_STATE)
        assert _get_violation(api, ctx["violation"]["id"], trust_admin_headers)["status"] == "OPEN"

    def test_manual_escalate_from_cure_in_progress_rejected(self, api, trust_admin_headers):
        """PRD §3.3: "A coordinator may manually escalate a `NOTICE_SENT`
        violation, recording `escalated_by` as `MANUAL`."
        PRD §3.3: "Manual escalation from any state other than `NOTICE_SENT` is
        rejected with `ERR_INVALID_VIOLATION_STATE`."

        Design: Corner/state_machines/manual_escalate_from_cure_in_progress_rejected
        """
        ctx = setup_violation_cure_in_progress(severity="MINOR", violation_type="SUBDIVISION")
        resp = api.escalate_violation(
            ctx["violation"]["id"], make_coordinator_headers("coord-1")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VIOLATION_STATE)
        assert (
            _get_violation(api, ctx["violation"]["id"], trust_admin_headers)["status"]
            == "CURE_IN_PROGRESS"
        )


class TestViolationCreationRules:
    def test_violation_against_permitted_use_rejected(self, api, coordinator_headers):
        """PRD §3.3: "The `violation_type` must be a key of the easement's
        current `permitted_use_matrix` — an unknown key is rejected with
        `ERR_INVALID_REQUEST` — and the matrix cell must be `PROHIBITED` or
        `DISCRETIONARY`: opening a violation against a `PERMITTED` cell is
        rejected with `ERR_USE_PERMITTED_NOT_VIOLABLE` (422)."

        Design: Corner/validations/violation_against_permitted_use_rejected
        """
        ctx = create_recorded_easement(name="E-VP", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        resp = api.create_violation(
            create_violation_payload(
                ctx["easement"]["id"], violation_type="AGRICULTURE", severity="MINOR",
                detected_on="2026-08-02",
            ),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_USE_PERMITTED_NOT_VIOLABLE)

    def test_field_monitor_cannot_create_violation(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST `/stewardship/violations` ... StewardshipCoordinator".

        Design: Corner/rbac/field_monitor_cannot_create_violation
        """
        ctx = create_recorded_easement(name="E-R1", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        resp = api.create_violation(
            create_violation_payload(
                ctx["easement"]["id"], detected_by_user_id="mon-1",
                violation_type="SUBDIVISION", severity="MINOR",
                detected_on="2026-08-02",
            ),
            make_field_monitor_headers("mon-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_violation_create_marks_active_authorization_breached(self, api,
                                                                  coordinator_headers,
                                                                  trust_admin_headers):
        """PRD §3.3: "If an active use authorization (one still `REQUESTED`,
        `APPROVED`, or `APPROVED_WITH_CONDITIONS`) covers the same use type on
        the same easement, its `conditions_breached` flag is set to true."
        PRD §3.3: "Creation immediately recomputes the easement's
        `open_violation_count` — the count of violations in `OPEN`,
        `NOTICE_SENT`, `CURE_IN_PROGRESS`, or `ESCALATED` — refreshes `posture`,
        and advances the easement's `version` by one."
        PRD §2.5: "Failing that, it is `VIOLATION_OPEN` when any violation on the
        easement is `OPEN`, `NOTICE_SENT`, `CURE_IN_PROGRESS`, or `ESCALATED`."

        Design: Corner/endpoints/violation_create_marks_active_authorization_breached
        """
        ctx = create_recorded_easement(name="E-CB", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "TIMBER_HARVEST": "DISCRETIONARY"})
        easement_id = ctx["easement"]["id"]
        landowner_id = ctx["landowner"]["id"]
        authorization = create_requested_use_authorization(
            easement_id, landowner_id, use_type="TIMBER_HARVEST"
        )
        decided = validate_success(
            api.decide_use_authorization(
                authorization["id"],
                decide_use_authorization_payload(
                    "APPROVED_WITH_CONDITIONS",
                    conditions=["erosion control plan", "winter-only harvest"],
                ),
                coordinator_headers,
            ),
            200,
        )
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"
        assert decided["conditions_breached"] is False

        violation = validate_success(
            api.create_violation(
                create_violation_payload(
                    easement_id, violation_type="TIMBER_HARVEST", severity="MATERIAL",
                    detected_on="2026-08-05",
                ),
                coordinator_headers,
            ),
            201,
        )
        assert violation["status"] == "OPEN"

        auth_after = validate_success(
            api.get_use_authorization(authorization["id"], trust_admin_headers), 200
        )
        assert auth_after["conditions_breached"] is True

        easement = get_easement(easement_id)
        assert easement["posture"] == "VIOLATION_OPEN"
        assert easement["open_violation_count"] == 1


class TestCureAndResolve:
    def test_current_landowner_can_start_cure(self, api):
        """PRD §3.3: "The current landowner begins curing by moving the violation
        from `NOTICE_SENT` to `CURE_IN_PROGRESS`; the caller's `X-User-ID` must
        equal the easement's `current_landowner_id`, else
        `ERR_NOT_CURRENT_LANDOWNER`"
        PRD §2.1: "When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of
        the acting `Landowner` record"

        Design: Corner/rbac/current_landowner_can_start_cure
        """
        ctx = setup_violation_notice_sent(severity="MINOR", violation_type="SUBDIVISION")
        cured = validate_success(
            api.start_violation_cure(
                ctx["violation"]["id"],
                make_landowner_headers(ctx["landowner"]["id"]),
            ),
            200,
        )
        assert cured["status"] == "CURE_IN_PROGRESS"

    def test_resolve_by_detector_sod_rejected(self, api, trust_admin_headers):
        """PRD §3.3: "A coordinator then verifies the cure, moving the violation
        from `CURE_IN_PROGRESS` to `RESOLVED`; the verifier must not be the
        detector — an `X-User-ID` matching `detected_by_user_id` is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.3: "Resolution stamps `resolved_on` with the clock date, records
        the verifier in `resolution_verified_by_user_id`, recomputes
        `open_violation_count` and `posture`, and advances the easement's
        `version` by one."

        Design: Corner/errors/resolve_by_detector_sod_rejected
        """
        ctx = setup_violation_cure_in_progress(
            severity="MINOR", violation_type="SUBDIVISION", detected_by="coord-9"
        )
        resp = api.resolve_violation(
            ctx["violation"]["id"], make_coordinator_headers("coord-9")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert (
            _get_violation(api, ctx["violation"]["id"], trust_admin_headers)["status"]
            == "CURE_IN_PROGRESS"
        )

        resolved = validate_success(
            api.resolve_violation(
                ctx["violation"]["id"], make_coordinator_headers("coord-2")
            ),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_verified_by_user_id"] == "coord-2"

    def test_posture_reconciled_after_violation_resolve(self, api):
        """PRD §2.5: "Posture — and, where relevant, `open_violation_count` — is
        recomputed whenever a violation opens or resolves, when an escalation
        spawns an enforcement action, when an enforcement action completes, when
        a monitoring visit completes, at recordation, and during the clock
        sweep."
        PRD §2.5: "an easement whose violations have all resolved and whose
        monitoring is current settles back to `GOOD_STANDING`."

        Design: Corner/cross_cutting_layers/posture_reconciled_after_violation_resolve
        """
        ctx = setup_open_violation(severity="MINOR", violation_type="SUBDIVISION")
        easement_id = ctx["easement"]["id"]
        easement_open = get_easement(easement_id)
        assert easement_open["posture"] == "VIOLATION_OPEN"
        assert easement_open["open_violation_count"] == 1

        violation_id = ctx["violation"]["id"]
        validate_success(
            api.send_violation_notice(violation_id, make_coordinator_headers("coord-1")),
            200,
        )
        validate_success(
            api.start_violation_cure(
                violation_id, make_landowner_headers(ctx["landowner"]["id"])
            ),
            200,
        )
        validate_success(
            api.resolve_violation(violation_id, make_coordinator_headers("coord-2")),
            200,
        )

        easement_end = get_easement(easement_id)
        assert easement_end["posture"] == "GOOD_STANDING"
        assert easement_end["open_violation_count"] == 0


class TestCureDeadlineSweep:
    def test_cure_deadline_escalation_strictly_after_deadline(self, api, trust_admin_headers):
        """PRD §3.3: "`cure_deadline_on` is the notice date plus the cure period
        for the severity — ninety days for `MINOR`, thirty days for `MATERIAL`,
        and seven days for `IRREPARABLE`."
        PRD §3.3: "the clock sweep escalates any violation in `NOTICE_SENT` or
        `CURE_IN_PROGRESS` once the clock date is strictly later than
        `cure_deadline_on` — the deadline day itself is still curable —
        recording `escalated_by` as `CLOCK_SWEEP`."

        Design: Corner/calculations/cure_deadline_escalation_strictly_after_deadline
        """
        ctx = setup_open_violation(
            severity="MINOR", violation_type="SUBDIVISION", detected_on="2026-08-09",
            clock="2026-08-10T00:00:00Z",
        )
        violation_id = ctx["violation"]["id"]
        noticed = validate_success(
            api.send_violation_notice(violation_id, make_coordinator_headers("coord-1")),
            200,
        )
        assert noticed["notice_served_on"] == "2026-08-10"
        assert noticed["cure_deadline_on"] == "2026-11-08", "notice + 90 MINOR days"

        set_clock("2026-11-08T00:00:00Z")
        on_deadline = _get_violation(api, violation_id, trust_admin_headers)
        assert on_deadline["status"] == "NOTICE_SENT", "the deadline day itself is still curable"

        set_clock("2026-11-09T00:00:00Z")
        past_deadline = _get_violation(api, violation_id, trust_admin_headers)
        assert past_deadline["status"] == "ESCALATED"
        assert past_deadline["escalated_by"] == "CLOCK_SWEEP"

    def test_clock_sweep_escalates_violation_past_cure_deadline(self, api, trust_admin_headers):
        """PRD §2.10: "Setting the clock runs a sweep with three effects: any
        violation in `NOTICE_SENT` or `CURE_IN_PROGRESS` whose cure deadline has
        passed escalates, spawning enforcement and flipping easement posture as
        described in §3.3; any succession notice still `NOTICE_GIVEN` past its
        acknowledgment deadline expires as described in §3.7; and every
        easement's monitoring posture is recomputed against the new date per
        §2.5."
        PRD §3.3: "Either route runs the same three-link cascade: the violation
        moves to `ESCALATED`; a new enforcement action is created in `PROPOSED`
        carrying this violation's `violation_id` and its `easement_id`
        denormalized from the violation; and that creation flips the easement's
        `posture` to `ENFORCEMENT_ACTIVE` and advances the easement's `version`
        by one."

        Design: Difficulty/transitive_cascade/clock_sweep_escalation_spawns_enforcement_and_flips_posture
        """
        ctx = setup_open_violation(
            severity="MATERIAL", violation_type="SUBDIVISION",
            detected_on="2026-08-10", clock="2026-08-10T00:00:00Z",
            parcel_acreage=500, matrix=STANDARD_MATRIX,
        )
        violation_id = ctx["violation"]["id"]
        noticed = validate_success(
            api.send_violation_notice(violation_id, make_coordinator_headers("coord-1")),
            200,
        )
        assert noticed["cure_deadline_on"] == "2026-09-09", "notice 2026-08-10 + 30 MATERIAL days"

        set_clock("2026-09-10T00:00:00Z")
        swept = _get_violation(api, violation_id, trust_admin_headers)
        assert swept["status"] == "ESCALATED", "cascade link 1: sweep escalates the violation"
        assert swept["escalated_by"] == "CLOCK_SWEEP"

    def test_clock_sweep_spawns_enforcement_and_flips_posture(self, api, trust_admin_headers):
        """PRD §3.3: "Either route runs the same three-link cascade: the
        violation moves to `ESCALATED`; a new enforcement action is created in
        `PROPOSED` carrying this violation's `violation_id` and its `easement_id`
        denormalized from the violation; and that creation flips the easement's
        `posture` to `ENFORCEMENT_ACTIVE` and advances the easement's `version`
        by one."
        PRD §2.5: "It is `ENFORCEMENT_ACTIVE` when any enforcement action on the
        easement is `PROPOSED`, `EXECUTED`, or `BREACHED`."

        Design: Difficulty/transitive_cascade/clock_sweep_escalation_spawns_enforcement_and_flips_posture
        """
        ctx = setup_open_violation(
            severity="MATERIAL", violation_type="SUBDIVISION",
            detected_on="2026-08-10", clock="2026-08-10T00:00:00Z",
            parcel_acreage=500, matrix=STANDARD_MATRIX,
        )
        easement_id = ctx["easement"]["id"]
        violation_id = ctx["violation"]["id"]
        validate_success(
            api.send_violation_notice(violation_id, make_coordinator_headers("coord-1")),
            200,
        )

        set_clock("2026-09-10T00:00:00Z")

        # Cascade link 2: exactly one PROPOSED enforcement action, denormalized.
        actions, meta = validate_paginated(api.list_enforcement_actions(trust_admin_headers))
        assert meta["total_count"] == 1
        action = actions[0]
        assert action["status"] == "PROPOSED"
        assert action["violation_id"] == violation_id
        assert action["easement_id"] == easement_id

        # Cascade link 3: posture flipped by the enforcement creation.
        easement = get_easement(easement_id)
        assert easement["posture"] == "ENFORCEMENT_ACTIVE"
