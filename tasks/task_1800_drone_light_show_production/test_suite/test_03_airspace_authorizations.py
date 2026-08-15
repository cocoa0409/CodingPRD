"""Airspace authorization lifecycle: review cycle, half-open overlap,
decision-time revalidation, expiry sweep, and the authorize gates."""
from test_helpers import (
    ApiErrorId,
    approve_safety_config,
    authorize_show,
    create_authorization,
    create_authorization_payload,
    create_design,
    create_safety_config,
    create_show,
    create_site,
    decide_authorization,
    get_show,
    get_success_data,
    lock_design,
    record_simulation,
    set_clock,
    setup_authorized_show,
    setup_show_with_locked_design,
    submit_authorization,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_authority_headers

PLANNER = TEST_USERS["planner_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _design_locked_with_approved_config():
    """Show in DESIGN_LOCKED with an APPROVED safety configuration."""
    ctx = setup_show_with_locked_design()
    config = create_safety_config(ctx["show"]["id"])
    approve_safety_config(config["id"])
    ctx["config"] = config
    return ctx


class TestAuthorizationReviewCycle:
    def test_under_review_info_requested_cycle(self, api):
        """PRD: "an `AuthorityOfficer` may park an `UNDER_REVIEW` application by
        requesting more information (optionally carrying an `info_note`), moving
        it to `INFO_REQUESTED`; the planner answers by resubmitting (optionally
        with an `amendment_note`), which returns it to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/authorization_review_info_cycle_and_reopen
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        auth = create_authorization(show["id"], waiver_types=["NIGHT_OPS"])
        assert auth["status"] == "DRAFT"

        submitted = submit_authorization(auth["id"])
        assert submitted["status"] == "UNDER_REVIEW"
        parked = validate_success(api.request_info(
            auth["id"], make_authority_headers("ao-1"),
            payload={"info_note": "Need noise study"}))
        assert parked["status"] == "INFO_REQUESTED"
        resubmitted = validate_success(api.resubmit_authorization(
            auth["id"], PLANNER, payload={"amendment_note": "Noise study attached"}))
        assert resubmitted["status"] == "UNDER_REVIEW", \
            "the same application traverses UNDER_REVIEW a second time"

    def test_denied_revise_reopen_to_approved(self, api):
        """PRD: "A `DENIED` application is not dead: the planner may revise it
        back to `DRAFT`, optionally supplying amended `window_start`,
        `window_end`, or `altitude_ceiling_ft` values; revision clears
        `decided_at` and `decided_by` so the refiled application carries no
        stale adjudication metadata."

        Design: Difficulty/non_linear_state_machine/authorization_review_info_cycle_and_reopen
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        auth = create_authorization(show["id"], waiver_types=["NIGHT_OPS"])
        submit_authorization(auth["id"])

        denied = decide_authorization(auth["id"], "DENIED", officer_user_id="ao-1")
        assert denied["status"] == "DENIED"
        assert denied["decided_at"] and denied["decided_by"] == "ao-1"

        revised = validate_success(api.revise_authorization(
            auth["id"], PLANNER, payload={"altitude_ceiling_ft": 400}))
        assert revised["status"] == "DRAFT", "DENIED reopens to DRAFT"
        assert revised["altitude_ceiling_ft"] == 400, "amended ceiling applied"
        assert revised["decided_at"] is None and revised["decided_by"] is None

        resubmitted = submit_authorization(auth["id"])
        assert resubmitted["status"] == "UNDER_REVIEW"
        approved = decide_authorization(auth["id"], "APPROVED", officer_user_id="ao-2")
        assert approved["status"] == "APPROVED"
        assert approved["decided_by"] == "ao-2"


class TestAuthorizeGates:
    def test_authorize_from_planning_returns_invalid_state(self, api):
        """PRD: "Authorizing also requires the show to actually be
        `DESIGN_LOCKED` (else `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/authorize_from_planning_returns_invalid_state
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        auth = create_authorization(show["id"])
        submit_authorization(auth["id"])
        decide_authorization(auth["id"], "APPROVED")

        resp = api.authorize_show(show["id"], {"authorization_id": auth["id"]},
                                  PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_authorize_with_under_review_authorization_rejected(self, api):
        """PRD: "The request names an `authorization_id`; that identifier must
        resolve to an authorization whose `show_event_id` is this show (else
        `ERR_AUTHORIZATION_NOT_FOUND`), whose status is `APPROVED` (else
        `ERR_AUTHORIZATION_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/authorize_requires_approved_authorization
        """
        ctx = _design_locked_with_approved_config()
        auth = create_authorization(ctx["show"]["id"])
        submit_authorization(auth["id"])  # UNDER_REVIEW, not APPROVED

        resp = api.authorize_show(ctx["show"]["id"],
                                  {"authorization_id": auth["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_APPROVED)

    def test_authorize_with_approved_authorization_succeeds(self, api):
        """PRD: "whose status is `APPROVED` (else
        `ERR_AUTHORIZATION_NOT_APPROVED`)" and "On success the show's
        `pinned_authorization_id` is set to the named authorization, the
        posture is recomputed, and the show's version increments."

        Design: Difficulty/cross_entity_state_dependency/authorize_requires_approved_authorization
        """
        ctx = _design_locked_with_approved_config()
        auth = create_authorization(ctx["show"]["id"])
        submit_authorization(auth["id"])
        decide_authorization(auth["id"], "APPROVED")

        show = authorize_show(ctx["show"]["id"], auth["id"])
        assert show["lifecycle_status"] == "AUTHORIZED"
        assert show["pinned_authorization_id"] == auth["id"]

    def test_authorize_without_approved_config_rejected(self, api):
        """PRD: "a pinned safety configuration in `APPROVED` status (else
        `ERR_SAFETY_CONFIG_NOT_APPROVED`)"

        Design: Corner/validations/authorize_without_approved_config_rejected
        """
        ctx = setup_show_with_locked_design()
        # Configuration created but left DRAFT (never approved).
        create_safety_config(ctx["show"]["id"])
        auth = create_authorization(ctx["show"]["id"])
        submit_authorization(auth["id"])
        decide_authorization(auth["id"], "APPROVED")

        resp = api.authorize_show(ctx["show"]["id"],
                                  {"authorization_id": auth["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_SAFETY_CONFIG_NOT_APPROVED)

    def test_cross_show_authorization_returns_not_found(self, api):
        """PRD: "an `authorization_id` supplied to the authorize action must
        reference an authorization whose `show_event_id` is that very show,
        failing as `ERR_AUTHORIZATION_NOT_FOUND` when it is not."

        Design: Corner/validations/cross_show_authorization_returns_not_found
        """
        ctx = _design_locked_with_approved_config()
        site = ctx["site"]
        show_b = create_show(site["id"], name="Show B",
                             window_start="2026-08-12T19:00:00Z",
                             window_end="2026-08-12T19:30:00Z",
                             drone_count_planned=5)
        auth_b = create_authorization(
            show_b["id"], window_start="2026-08-12T18:00:00Z",
            window_end="2026-08-12T21:00:00Z")
        submit_authorization(auth_b["id"])
        decide_authorization(auth_b["id"], "APPROVED")

        resp = api.authorize_show(ctx["show"]["id"],
                                  {"authorization_id": auth_b["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND)

    def test_authorize_revalidates_coverage_after_reschedule(self, api):
        """PRD: "whose window covers the show's window — plus the backup window
        when one is set and unconsumed (else
        `ERR_AUTHORIZATION_WINDOW_INSUFFICIENT`)"
        PRD: "Both paths land the show in `PLANNING`, and both then recompute:
        if the pinned design is still `LOCKED`, the show immediately advances to
        `DESIGN_LOCKED` without further operator action"

        Design: Corner/cross_cutting_layers/authorize_revalidates_coverage_after_reschedule
        """
        ctx = setup_authorized_show()
        show = ctx["show"]
        auth = ctx["auth"]

        validate_success(api.postpone_show(show["id"], PLANNER))
        moved = validate_success(api.reschedule_show(
            show["id"], {"window_start": "2026-08-20T19:00:00Z",
                         "window_end": "2026-08-20T19:30:00Z"}, PLANNER))
        assert moved["lifecycle_status"] == "DESIGN_LOCKED", \
            "pinned design still LOCKED, so the rescheduled show auto-advances"

        # The APPROVED window (Aug 10 18:00-21:00) no longer covers Aug 20.
        resp = api.authorize_show(show["id"], {"authorization_id": auth["id"]},
                                  PLANNER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_INSUFFICIENT)


class TestAuthorizeExistenceScope:
    def test_unknown_show_path_returns_not_found_before_state(self, api):
        """PRD: "Path identifiers — `siteId`, `showEventId`,
        `authorizationId`, `designId`, `simulationRunId`, `configId`,
        `droneId`, `chargeBayId`, `chargeSessionId`, `assignmentId`,
        `weatherReadingId`, `evaluationId`, `incidentId`, and `flightLogId` —
        are validated first, in left-to-right order as they appear in the path;
        the first identifier that does not resolve produces the corresponding
        404 error and no further validation runs."

        Design: Corner/validations/unknown_show_path_returns_not_found_before_state
        """
        unknown_show = "11111111-1111-4111-8111-111111111111"
        unknown_auth = "22222222-2222-4222-8222-222222222222"
        # The path show id does not resolve and neither does the body
        # authorization id: path existence is validated first.
        resp = api.authorize_show(unknown_show,
                                  {"authorization_id": unknown_auth}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_SHOW_NOT_FOUND)


class TestAuthorizationWindowRules:
    def test_adjacent_windows_do_not_conflict(self, api):
        """PRD: "overlap uses half-open interval semantics, so two windows that
        merely touch — one ending exactly when the other begins — do not
        conflict"

        Design: Difficulty/resource_temporal_overlap/authorization_half_open_adjacency_allowed
        """
        site = create_site()
        set_clock()
        show_a = create_show(site["id"], name="Show A")
        auth_a = create_authorization(show_a["id"])
        submit_authorization(auth_a["id"])

        show_b = create_show(site["id"], name="Show B",
                             window_start="2026-08-10T21:30:00Z",
                             window_end="2026-08-10T22:00:00Z",
                             drone_count_planned=5)
        auth_b = create_authorization(
            show_b["id"], window_start="2026-08-10T21:00:00Z",
            window_end="2026-08-10T23:00:00Z")
        # 21:00 start exactly equals auth A's 21:00 end: half-open adjacency.
        submitted = submit_authorization(auth_b["id"])
        assert submitted["status"] == "UNDER_REVIEW"

    def test_truly_overlapping_window_rejected(self, api):
        """PRD: "any strict interleaving of one window's start before the
        other's end and the other's start before the first's end is rejected
        with `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/authorization_half_open_adjacency_allowed
        """
        site = create_site()
        set_clock()
        show_a = create_show(site["id"], name="Show A")
        auth_a = create_authorization(show_a["id"])
        submit_authorization(auth_a["id"])

        show_c = create_show(site["id"], name="Show C",
                             window_start="2026-08-11T00:30:00Z",
                             window_end="2026-08-11T01:00:00Z",
                             drone_count_planned=5)
        auth_c = create_authorization(
            show_c["id"], window_start="2026-08-10T20:00:00Z",
            window_end="2026-08-11T01:30:00Z")
        # 20:00 < 21:00 (auth A's end): a true overlap.
        resp = api.submit_authorization(auth_c["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP)

    def test_short_window_insufficient_at_submit(self, api):
        """PRD: "The requested window must fully cover the show's window —
        starting no later than the show's start and ending no earlier than the
        show's end — and must likewise cover the backup window when one is set
        and not yet consumed, else `ERR_AUTHORIZATION_WINDOW_INSUFFICIENT`."

        Design: Corner/validations/authorization_short_window_insufficient_at_submit
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])  # window 19:00-19:30
        auth = create_authorization(show["id"],
                                    window_end="2026-08-10T19:15:00Z")
        resp = api.submit_authorization(auth["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_INSUFFICIENT)

    def test_ceiling_violation_beats_window_overlap(self, api):
        """PRD: "When several validations could reject the same request, they
        are evaluated in a fixed priority order, and the first failing check
        produces the response." — safety and regulatory limits (item 8) precede
        temporal window rules (item 9).
        PRD: "The requested ceiling must not exceed the `site_max_altitude_ft`
        of the venue hosting the parent show, else
        `ERR_ALTITUDE_CEILING_EXCEEDS_SITE`."

        Design: Difficulty/priority_pair_validation_conflict/authorization_ceiling_safety_precedes_window_overlap
        """
        site = create_site()
        set_clock()
        show_a = create_show(site["id"], name="Show A")
        auth_a = create_authorization(show_a["id"])
        submit_authorization(auth_a["id"])

        show_b = create_show(site["id"], name="Show B",
                             window_start="2026-08-10T22:00:00Z",
                             window_end="2026-08-10T22:30:00Z",
                             drone_count_planned=5)
        auth_b = create_authorization(
            show_b["id"], window_start="2026-08-10T20:30:00Z",
            window_end="2026-08-10T22:45:00Z", altitude_ceiling_ft=600)
        # Ceiling 600 > site max 500 AND window overlaps auth A: safety wins.
        resp = api.submit_authorization(auth_b["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_ALTITUDE_CEILING_EXCEEDS_SITE)

    def test_window_overlap_fires_when_ceiling_legal(self, api):
        """PRD: "the requested window must not overlap any other application
        serving a show at the same site that is `UNDER_REVIEW` or `APPROVED`:
        overlap uses half-open interval semantics"

        Design: Difficulty/priority_pair_validation_conflict/authorization_ceiling_safety_precedes_window_overlap
        """
        site = create_site()
        set_clock()
        show_a = create_show(site["id"], name="Show A")
        auth_a = create_authorization(show_a["id"])
        submit_authorization(auth_a["id"])

        show_b = create_show(site["id"], name="Show B",
                             window_start="2026-08-10T22:00:00Z",
                             window_end="2026-08-10T22:30:00Z",
                             drone_count_planned=5)
        auth_b = create_authorization(
            show_b["id"], window_start="2026-08-10T20:30:00Z",
            window_end="2026-08-10T22:45:00Z", altitude_ceiling_ft=450)
        # Ceiling is legal; only the overlap remains to fail.
        resp = api.submit_authorization(auth_b["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP)


class TestAuthorizationWithdrawalAndSweep:
    def test_withdrawn_authorization_cannot_be_submitted(self, api):
        """PRD: "A submission attempted from any status other than `DRAFT` is
        `ERR_INVALID_STATE`." and "A `DRAFT` application may instead be
        withdrawn outright, moving it to `WITHDRAWN`."

        Design: Corner/state_machines/withdrawn_authorization_cannot_be_submitted
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        auth = create_authorization(show["id"])

        withdrawn = validate_success(api.withdraw_authorization(auth["id"], PLANNER))
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.submit_authorization(auth["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_sweep_expires_authorization_past_window_end(self, api):
        """PRD: "The sweep transitions every `APPROVED` airspace authorization
        whose window end is strictly before the current logical-clock reading to
        `EXPIRED`, with the show-downgrade cascade described in §3.3. The sweep
        response reports two arrays: `expired_authorization_ids` and
        `downgraded_show_ids`."

        Design: Difficulty/transitive_cascade/authorization_expiry_sweep_cascade
        """
        ctx = setup_authorized_show()
        auth = ctx["auth"]
        assert ctx["show"]["lifecycle_status"] == "AUTHORIZED", "setup held"
        set_clock("2026-08-11T00:00:00Z")  # past the 2026-08-10T21:00 window end

        sweep = get_success_data(api.run_sweep(OPS))
        assert auth["id"] in sweep["expired_authorization_ids"]
        after = validate_success(api.get_authorization(auth["id"], PLANNER))
        assert after["status"] == "EXPIRED", "link 1: APPROVED -> EXPIRED"

    def test_sweep_expiry_downgrades_pinning_show(self, api):
        """PRD: "The same `APPROVED`-to-`EXPIRED` fate with the identical
        cascade arrives via the operations sweep once the logical clock has
        passed the authorization's window end" — "every show whose
        `pinned_authorization_id` names this authorization and whose lifecycle
        is `DESIGN_LOCKED`, `AUTHORIZED`, `READY`, or `GO_CERTIFIED` is dropped
        back to `PLANNING` with `readiness_posture` `NOT_READY`"

        Design: Difficulty/transitive_cascade/authorization_expiry_sweep_cascade
        """
        ctx = setup_authorized_show()
        show = ctx["show"]
        set_clock("2026-08-11T00:00:00Z")

        sweep = get_success_data(api.run_sweep(OPS))
        assert show["id"] in sweep["downgraded_show_ids"]
        after = get_show(show["id"])
        assert after["lifecycle_status"] == "PLANNING", \
            "link 2: expiry downgrades the pinning show"
        assert after["readiness_posture"] == "NOT_READY"
