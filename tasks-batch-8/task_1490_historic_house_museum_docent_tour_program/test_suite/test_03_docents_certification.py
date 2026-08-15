"""Docent recruitment, training-driven readiness, certification gates,
deactivation cascade, and shift ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_shift,
    create_certified_docent,
    create_docent,
    create_route,
    create_room,
    create_slot,
    create_trainee_with_training,
    get_docent,
    get_slot,
    log_training,
    make_docent_headers,
    setup_active_route_no_script,
    setup_staffed_scheduled_slot,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["docent_coordinator_headers"]
ADMIN = TEST_USERS["museum_admin_headers"]


class TestDocentAdvancement:

    def test_docent_advance_applicant_to_trainee(self):
        """PRD section 3.3: "Moving an `APPLICANT` to `TRAINEE` has no
        threshold."

        Design: Corner/state_machines/docent_advance_applicant_to_trainee
        """
        docent = create_docent()
        resp = api_client.advance_docent(
            docent["id"], {"to_status": "TRAINEE"}, COORDINATOR)
        data = validate_success(resp)
        assert data["status"] == "TRAINEE"


class TestReadinessScoreVariants:
    """Identical training fields, two weighted scores."""

    def test_readiness_standard_score_uses_standard_weights(self):
        """PRD section 3.3: "Both share the same three inputs: the hours term
        is `training_hours` capped at 30 hours and then divided by 30; the
        shadow term is `shadow_tours_completed` capped at 5 and divided by 5;
        the quiz term is `quiz_score` divided by 100, treating a null quiz as
        zero. The `readiness_standard_score` weights those terms at
        three-tenths hours, three-tenths shadow, and four-tenths quiz; the
        weighted sum is multiplied by 100 and rounded half-up to an integer
        between 0 and 100."

        Design: Difficulty/dual_variant_calc/docent_readiness_track_variants
        """
        docent = create_trainee_with_training(hours=21, shadow_tours=4,
                                              quiz_score=90)
        data = get_docent(docent["id"])
        # 0.3*(21/30) + 0.3*(4/5) + 0.4*(90/100) = 0.21 + 0.24 + 0.36 = 0.81
        assert data["readiness_standard_score"] == 81, (
            f"standard-track readiness must be 81, "
            f"got {data['readiness_standard_score']}"
        )

    def test_readiness_apprentice_score_differs_on_same_inputs(self):
        """PRD section 3.3: "The `readiness_apprentice_score` uses the
        identical inputs with weights of one-half hours, four-tenths shadow,
        and one-tenth quiz — the same data, a different number — and is
        reported alongside the standard score but never gates certification."

        Design: Difficulty/dual_variant_calc/docent_readiness_track_variants
        """
        docent = create_trainee_with_training(hours=21, shadow_tours=4,
                                              quiz_score=90)
        data = get_docent(docent["id"])
        # 0.5*(21/30) + 0.4*(4/5) + 0.1*(90/100) = 0.35 + 0.32 + 0.09 = 0.76
        assert data["readiness_apprentice_score"] == 76, (
            f"apprentice-track readiness must be 76, "
            f"got {data['readiness_apprentice_score']}"
        )
        assert data["readiness_standard_score"] \
            != data["readiness_apprentice_score"], (
                "the two tracks must report different scores for the same "
                "training inputs"
            )


class TestCertificationQuizBoundary:

    def test_quiz_84_fails_certification_despite_readiness(self):
        """PRD section 3.3: "Moving a `TRAINEE` to `CERTIFIED` is
        threshold-gated on all four fronts: `training_hours` of at least 20,
        `shadow_tours_completed` of at least 3, a `quiz_score` of at least
        85, and a `readiness_standard_score` of at least 70 — failing any one
        rejects the advance with `ERR_CERTIFICATION_NOT_MET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/quiz_threshold_boundary
        """
        room = create_room()
        route = create_route([room["id"]])
        docent = create_trainee_with_training(hours=30, shadow_tours=3,
                                              quiz_score=84)
        current = get_docent(docent["id"])
        # 0.3*(30/30) + 0.3*(3/5) + 0.4*(84/100) = 0.816 -> 82 >= 70
        assert current["readiness_standard_score"] == 82
        resp = api_client.advance_docent(
            docent["id"],
            {"to_status": "CERTIFIED", "route_ids": [route["id"]]},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_MET)
        after = get_docent(docent["id"])
        assert after["status"] == "TRAINEE"

    def test_quiz_85_passes_certification_and_records_routes(self):
        """PRD section 3.3: "Moving a `TRAINEE` to `CERTIFIED` is
        threshold-gated on all four fronts: `training_hours` of at least 20,
        `shadow_tours_completed` of at least 3, a `quiz_score` of at least
        85, and a `readiness_standard_score` of at least 70 — failing any one
        rejects the advance with `ERR_CERTIFICATION_NOT_MET` (HTTP 422)."
        PRD section 3.3: "The certification request must also carry a
        non-empty `route_ids` array, which becomes the docent's
        `certified_route_ids`, the routes they are qualified to lead."

        Design: Difficulty/boundary_precision_check/quiz_threshold_boundary
        """
        room = create_room()
        route = create_route([room["id"]])
        docent = create_trainee_with_training(hours=30, shadow_tours=3,
                                              quiz_score=84)
        # The exact quiz boundary: 85 passes where 84 failed.
        log_training(docent["id"], "QUIZ", 85)
        resp = api_client.advance_docent(
            docent["id"],
            {"to_status": "CERTIFIED", "route_ids": [route["id"]]},
            COORDINATOR,
        )
        data = validate_success(resp)
        assert data["status"] == "CERTIFIED"
        assert data["certified_route_ids"] == [route["id"]], (
            f"certified_route_ids must record the request's route_ids, "
            f"got {data['certified_route_ids']}"
        )


class TestDeactivationCascade:

    def test_deactivation_cancels_future_shifts(self):
        """PRD section 3.3: "Deactivation moves a `TRAINEE` or `CERTIFIED`
        docent to the terminal `INACTIVE` state, increments the docent's
        `version`, and ripples outward in two hops within the same request:
        first, every shift assignment of this docent still in `ASSIGNED` or
        `CONFIRMED` whose slot starts after the logical clock is cancelled;
        second, each affected slot recomputes its `staffing_status`, so a
        `STAFFED` slot that loses its only confirmed lead drops to
        `UNSTAFFED`."

        Design: Difficulty/transitive_cascade/docent_decertification_cascade
        """
        ctx = setup_staffed_scheduled_slot()
        resp = api_client.deactivate_docent(ctx["docent_id"], COORDINATOR)
        data = validate_success(resp)
        assert data["status"] == "INACTIVE"
        shifts = validate_success(
            api_client.list_docent_shifts(ctx["docent_id"], COORDINATOR))
        by_id = {s["id"]: s for s in shifts}
        assert by_id[ctx["shift"]["id"]]["status"] == "CANCELLED", (
            f"hop 1: the docent's future CONFIRMED shift must be CANCELLED, "
            f"got {by_id[ctx['shift']['id']]['status']}"
        )

    def test_deactivation_drops_slot_staffing_to_unstaffed(self):
        """PRD section 3.3: "Deactivation moves a `TRAINEE` or `CERTIFIED`
        docent to the terminal `INACTIVE` state, increments the docent's
        `version`, and ripples outward in two hops within the same request:
        first, every shift assignment of this docent still in `ASSIGNED` or
        `CONFIRMED` whose slot starts after the logical clock is cancelled;
        second, each affected slot recomputes its `staffing_status`, so a
        `STAFFED` slot that loses its only confirmed lead drops to
        `UNSTAFFED`."
        PRD section 3.4: "`STAFFED` when a `CONFIRMED` `LEAD` shift exists,
        `NEEDS_LEAD` when a non-terminal `ASSIGNED` `LEAD` exists but none is
        confirmed, and `UNSTAFFED` otherwise."

        Design: Difficulty/transitive_cascade/docent_decertification_cascade
        """
        ctx = setup_staffed_scheduled_slot()
        slot_pre = get_slot(ctx["slot_id"])
        assert slot_pre["staffing_status"] == "STAFFED", (
            f"precondition: slot must be STAFFED before deactivation, "
            f"got {slot_pre['staffing_status']}"
        )
        resp = api_client.deactivate_docent(ctx["docent_id"], COORDINATOR)
        validate_success(resp)
        slot_post = get_slot(ctx["slot_id"])
        assert slot_post["staffing_status"] == "UNSTAFFED", (
            f"hop 2: losing its only confirmed lead must drop the slot to "
            f"UNSTAFFED, got {slot_post['staffing_status']}"
        )
        assert slot_post["status"] == "SCHEDULED", (
            f"deactivation must not cancel the slot itself, "
            f"got {slot_post['status']}"
        )


class TestShiftOwnership:

    def test_docent_cannot_confirm_others_shift_forbidden(self):
        """PRD section 2.1: "When `X-User-Role` is `Docent`, `X-User-ID` is
        the `id` of the acting `Docent`; ownership checks on a shift
        assignment compare the shift's `docent_id` to `X-User-ID`, so a
        docent confirming or declining a shift that belongs to someone else
        is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/docent_cannot_confirm_others_shift_forbidden
        """
        ctx = setup_active_route_no_script()
        d1 = create_certified_docent([ctx["route_id"]], email="dee@x.org")
        d2 = create_docent(full_name="Pat Guide", email="pat@x.org")
        slot = create_slot(ctx["route_id"])
        shift = assign_shift(d1["id"], slot["id"], "LEAD")
        resp = api_client.confirm_shift_assignment(
            shift["id"], make_docent_headers(d2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
