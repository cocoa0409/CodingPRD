"""Leak surveys and leak lifecycle guards: survey-stage gating, cancellation
child guard, withdraw, and repair-completion prerequisites (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assert_leak,
    assert_leak_survey,
    create_dma,
    create_in_field_survey,
    create_leak_payload,
    create_verified_leak,
    get_dma,
    make_field_supervisor_headers,
    make_regulator_liaison_headers,
    report_leak,
    validate_error,
    validate_success,
)

FS = TEST_DEFAULTS["FIELD_SUPERVISOR"]
RL = TEST_DEFAULTS["REGULATOR_LIAISON"]


class TestVerifyGatedOnSurveyStage:
    def test_verify_rejected_after_survey_completed(self, api):
        """PRD §3.4: "Verification moves a leak from `REPORTED` to `VERIFIED` —
        permitted only while the parent survey is still `IN_FIELD` — and
        recomputes the score and band."
        PRD §2.7: "State-machine validity — the target entity is in a from-state
        that permits the invoked transition, and terminal states reject every
        transition; failure yields `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "Completion is permitted regardless of whether the survey's
        leaks remain open — leaks in `REPORTED`, `VERIFIED`, `REPAIR_SCHEDULED`,
        or `REOPENED` do not block completion; it is the coverage figure, not
        the repair pipeline, that completion freezes."

        Design: Difficulty/cross_entity_state_dependency/leak_verify_gated_on_survey_in_field
        """
        dma = create_dma(code="DMA-CE1", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"], method="NOISE_LOGGER")
        leak = report_leak(survey["id"], location_description="Hydrant 4",
                           detected_at="2026-08-02T04:00:00Z")
        completed = validate_success(
            api.complete_leak_survey(
                survey["id"], {"coverage_pct": 80.0},
                make_field_supervisor_headers(FS),
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["coverage_pct"] == pytest.approx(80.0, abs=1e-9)

        res = api.verify_leak(leak["id"], make_field_supervisor_headers(FS))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        reread = validate_success(
            api.get_leak(leak["id"], make_field_supervisor_headers(FS)), 200
        )
        assert reread["status"] == "REPORTED"

    def test_verify_succeeds_while_survey_in_field(self, api):
        """PRD §3.4: "Verification moves a leak from `REPORTED` to `VERIFIED` —
        permitted only while the parent survey is still `IN_FIELD` — and
        recomputes the score and band."

        Design: Difficulty/cross_entity_state_dependency/leak_verify_gated_on_survey_in_field
        """
        dma = create_dma(code="DMA-CE1B", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"])
        leak = report_leak(survey["id"], estimated_loss_lps=1.0,
                           repair_cost_estimate=4000)

        verified = validate_success(
            api.verify_leak(leak["id"], make_field_supervisor_headers(FS)), 200
        )
        assert_leak(verified)
        assert verified["status"] == "VERIFIED"
        # annualized = 1.0 * 86400 * 365 / 1000 = 31536; value = 37843.2;
        # ratio = 37843.2 / 4000 = 9.4608; base score = 9.4608 * 2.0 = 18.92
        assert verified["repair_priority_score"] == pytest.approx(18.92, abs=0.01)
        assert verified["priority_band"] == "P3"


class TestWithdraw:
    def test_verified_leak_can_be_withdrawn(self, api, field_supervisor_headers):
        """PRD §3.4: "Finally, a leak reported in error can be withdrawn from
        either `REPORTED` or `VERIFIED` into the terminal `WITHDRAWN` state,
        recomputing `open_leak_count`."
        PRD §3.1: "`open_leak_count` counts the DMA's leaks — across all of its
        surveys — whose status sits in the open set `REPORTED`, `VERIFIED`,
        `REPAIR_SCHEDULED`, or `REOPENED`"

        Design: Corner/state_machines/leak_withdraw_from_verified
        """
        dma = create_dma(code="DMA-SM2", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"])
        leak = create_verified_leak(survey["id"], location_description="Main & 5th")
        assert get_dma(dma["id"])["open_leak_count"] == 1

        withdrawn = validate_success(
            api.withdraw_leak(leak["id"], field_supervisor_headers), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_dma(dma["id"])["open_leak_count"] == 0


class TestInvalidTransition:
    def test_complete_repair_from_reported_rejected(self, api,
                                                    field_supervisor_headers):
        """PRD §3.4: "Completing the repair moves it from `REPAIR_SCHEDULED` to
        `REPAIRED` and requires the request to supply the `actual_repair_cost`
        (at least zero)"
        PRD §2.7: "State-machine validity — the target entity is in a from-state
        that permits the invoked transition, and terminal states reject every
        transition; failure yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/leak_invalid_transition_from_reported_to_complete_repair
        """
        dma = create_dma(code="DMA-SM3", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"])
        leak = report_leak(survey["id"], location_description="Main & 6th")

        res = api.complete_leak_repair(
            leak["id"], {"actual_repair_cost": 3000}, field_supervisor_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        reread = validate_success(
            api.get_leak(leak["id"], field_supervisor_headers), 200
        )
        assert reread["status"] == "REPORTED"


class TestSurveyCancelChildGuard:
    def test_cancel_blocked_by_open_leak_then_succeeds_after_withdraw(
        self, api, field_supervisor_headers
    ):
        """PRD §3.3: "Cancelling a `PLANNED` survey requires that no leak rows
        exist under it at all; cancelling an `IN_FIELD` survey requires that
        every leak under it has reached a terminal state (`VERIFIED_REPAIR` or
        `WITHDRAWN`). A cancellation attempted against leaks in any other
        configuration is rejected with `ERR_CHILDREN_OPEN` (HTTP 409); a
        successful cancellation moves the survey to `CANCELLED` and appends an
        audit event."

        Design: Corner/state_machines/leak_survey_cancel_blocked_by_open_children
        """
        dma = create_dma(code="DMA-SM4", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"])
        leak = report_leak(survey["id"], location_description="Main & 7th")

        blocked = api.cancel_leak_survey(survey["id"], field_supervisor_headers)
        validate_error(blocked, ApiErrorId.ERR_CHILDREN_OPEN, expected_status=409)

        validate_success(api.withdraw_leak(leak["id"], field_supervisor_headers), 200)
        cancelled = validate_success(
            api.cancel_leak_survey(survey["id"], field_supervisor_headers), 200
        )
        assert_leak_survey(cancelled)
        assert cancelled["status"] == "CANCELLED"


class TestCompleteRepairPrerequisite:
    def test_complete_repair_without_actual_cost_rejected(self, api,
                                                          field_supervisor_headers):
        """PRD §3.4: "Completing the repair moves it from `REPAIR_SCHEDULED` to
        `REPAIRED` and requires the request to supply the `actual_repair_cost`
        (at least zero); a completion attempted without it is rejected with
        `ERR_MISSING_PREREQUISITE` (HTTP 422)."

        Design: Corner/validations/complete_repair_requires_actual_cost
        """
        dma = create_dma(code="DMA-VAL4", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"])
        leak = create_verified_leak(survey["id"], location_description="Main & 8th")
        scheduled = validate_success(
            api.schedule_leak_repair(leak["id"], field_supervisor_headers), 200
        )
        assert scheduled["status"] == "REPAIR_SCHEDULED"

        res = api.complete_leak_repair(leak["id"], {}, field_supervisor_headers)
        validate_error(res, ApiErrorId.ERR_MISSING_PREREQUISITE, expected_status=422)

        reread = validate_success(
            api.get_leak(leak["id"], field_supervisor_headers), 200
        )
        assert reread["status"] == "REPAIR_SCHEDULED"


class TestRbacOnLeakReport:
    def test_regulator_liaison_cannot_create_leak(self, api):
        """PRD §2.1: "A request whose role is recognized but not on the
        endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/regulator_liaison_cannot_create_leak
        """
        dma = create_dma(code="DMA-RB2", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        survey = create_in_field_survey(dma["id"])

        res = api.create_leak(
            create_leak_payload(survey["id"], location_description="Rogue"),
            make_regulator_liaison_headers(RL),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
