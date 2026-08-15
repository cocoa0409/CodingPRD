"""Split-night protocol: the one-shot decision, its multi-input eligibility
gate, and the completion requirements that follow from the recorded branch."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_STAMP,
    TEST_USERS,
    assert_sleep_study,
    get_order,
    get_study,
    make_sleep_technologist_headers,
    record_split_decision,
    setup_study_in_progress,
    setup_study_scheduled,
    validate_error,
    validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]


def _split_in_progress():
    return setup_study_in_progress(study_type="SPLIT_NIGHT")


def _split_payload(api, study_id, tech_id, **overrides):
    payload = {
        "intended_outcome": "CONVERT_TO_TITRATION",
        "diagnostic_minutes_observed": 130,
        "partial_ahi_observed": 45.0,
        "central_predominance_flag": False,
        "remaining_minutes_available": 200,
    }
    payload.update(overrides)
    return api.split_decision(
        study_id, payload, make_sleep_technologist_headers(tech_id))


class TestSplitOverrideBand:
    def test_override_band_rejected_without_reason(self, api):
        """PRD: "The partial AHI then gates conversion in three bands: at least
        40.0 qualifies outright; at least 20.0 but below 40.0 qualifies only
        when an `override_reason` of at least ten characters accompanies the
        request, and without one the request is rejected with
        `ERR_SPLIT_AHI_THRESHOLD_NOT_MET`; below 20.0 the request is always
        rejected with `ERR_SPLIT_AHI_THRESHOLD_NOT_MET`."

        Design: Difficulty/combinatorial_formula/split_night_multi_input_gate_override_band
        """
        ws = _split_in_progress()

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=130, partial_ahi_observed=35.0,
            remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_SPLIT_AHI_THRESHOLD_NOT_MET, 422)

        study = get_study(ws["study"]["id"])
        assert study["split_outcome"] is None, (
            "A rejected decision leaves the branch unrecorded")
        assert study["status"] == "IN_PROGRESS"

    def test_override_band_accepted_with_reason(self, api):
        """PRD: "The partial AHI then gates conversion in three bands: at least
        40.0 qualifies outright; at least 20.0 but below 40.0 qualifies only
        when an `override_reason` of at least ten characters accompanies the
        request, and without one the request is rejected with
        `ERR_SPLIT_AHI_THRESHOLD_NOT_MET`; below 20.0 the request is always
        rejected with `ERR_SPLIT_AHI_THRESHOLD_NOT_MET`."
        PRD: "Either outcome is stored on the study as `split_outcome`,
        alongside `split_diagnostic_minutes` and `split_partial_ahi` taken from
        the observed values; all three remain unset until the decision is
        recorded."

        Design: Difficulty/combinatorial_formula/split_night_multi_input_gate_override_band
        """
        ws = _split_in_progress()
        study_id, tech_id = ws["study"]["id"], ws["technologist"]["id"]

        # The identical inputs are first rejected without the override...
        resp = _split_payload(
            api, study_id, tech_id,
            diagnostic_minutes_observed=130, partial_ahi_observed=35.0,
            remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_SPLIT_AHI_THRESHOLD_NOT_MET, 422)

        # ...and accepted once a qualifying override_reason accompanies them.
        decided = _split_payload(
            api, study_id, tech_id,
            diagnostic_minutes_observed=130, partial_ahi_observed=35.0,
            remaining_minutes_available=200,
            override_reason="clinical judgment documented")
        study = validate_success(decided)
        assert_sleep_study(study)
        assert study["split_outcome"] == "CONVERT_TO_TITRATION"
        assert study["split_diagnostic_minutes"] == 130
        assert study["split_partial_ahi"] == 35.0


class TestSplitBoundaryPrecision:
    def test_all_boundaries_inclusive_qualifies(self, api):
        """PRD: "The diagnostic portion must have accumulated at least 120
        minutes; fewer minutes are rejected with
        `ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET`."
        PRD: "at least 40.0 qualifies outright"
        PRD: "Finally, at least 180 minutes must remain available for
        titration; fewer remaining minutes are rejected with
        `ERR_SPLIT_INSUFFICIENT_REMAINING`."

        Design: Difficulty/boundary_precision_check/split_minutes_exactly_120_qualifies
        """
        ws = _split_in_progress()

        decided = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=120, partial_ahi_observed=40.0,
            remaining_minutes_available=180)
        study = validate_success(decided)
        assert study["split_outcome"] == "CONVERT_TO_TITRATION"
        assert study["split_diagnostic_minutes"] == 120
        assert study["split_partial_ahi"] == 40.0

    def test_minutes_floor_inclusive_inside_override_band(self, api):
        """PRD: "An override never waives the other constraints: a partial AHI
        in the override band still requires at least 120 diagnostic minutes and
        at least 180 remaining minutes."

        Design: Difficulty/boundary_precision_check/split_minutes_exactly_120_qualifies
        """
        ws = _split_in_progress()

        decided = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=120, partial_ahi_observed=25.0,
            remaining_minutes_available=180,
            override_reason="documented clinical rationale")
        study = validate_success(decided)
        assert study["split_outcome"] == "CONVERT_TO_TITRATION"
        assert study["split_diagnostic_minutes"] == 120
        assert study["split_partial_ahi"] == 25.0

    def test_minutes_119_rejected(self, api):
        """PRD: "The diagnostic portion must have accumulated at least 120
        minutes; fewer minutes are rejected with
        `ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET`."

        Design: Corner/validations/split_minutes_119_rejected
        """
        ws = _split_in_progress()

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=119, partial_ahi_observed=45.0,
            remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET, 422)

        assert get_study(ws["study"]["id"])["split_outcome"] is None

    def test_remaining_179_rejected(self, api):
        """PRD: "Finally, at least 180 minutes must remain available for
        titration; fewer remaining minutes are rejected with
        `ERR_SPLIT_INSUFFICIENT_REMAINING`."

        Design: Corner/validations/split_remaining_179_rejected
        """
        ws = _split_in_progress()

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=120, partial_ahi_observed=40.0,
            remaining_minutes_available=179)
        validate_error(resp, ApiErrorId.ERR_SPLIT_INSUFFICIENT_REMAINING, 422)

        assert get_study(ws["study"]["id"])["split_outcome"] is None

    def test_central_predominance_rejected(self, api):
        """PRD: "An intended outcome of `CONVERT_TO_TITRATION` runs the full
        eligibility gate, and the gate evaluates safety before thresholds. A
        `central_predominance_flag` of true excludes split-night titration
        outright (`ERR_SPLIT_CENTRAL_PREDOMINANCE`)."

        Design: Corner/validations/split_central_predominance_rejected
        """
        ws = _split_in_progress()

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=130, partial_ahi_observed=45.0,
            central_predominance_flag=True, remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_SPLIT_CENTRAL_PREDOMINANCE, 422)

        assert get_study(ws["study"]["id"])["split_outcome"] is None


class TestSplitStateGateBeatsSafety:
    def test_state_error_wins_on_scheduled_study(self, api):
        """PRD: "For a `SPLIT_NIGHT` study, the technologist records the
        protocol branch exactly once, while the study is `IN_PROGRESS`."
        PRD: "Every request is evaluated against a fixed pipeline of checks,
        and a request fails at the first check it violates." — the state
        preconditions (stage 7, including `ERR_STUDY_NOT_IN_PROGRESS`) run
        before the clinical safety checks (stage 8, including
        `ERR_SPLIT_CENTRAL_PREDOMINANCE`).

        Design: Difficulty/priority_pair_validation_conflict/split_state_beats_safety
        """
        ws = setup_study_scheduled(study_type="SPLIT_NIGHT")
        assert ws["study"]["status"] == "SCHEDULED"

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=130, partial_ahi_observed=45.0,
            central_predominance_flag=True, remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_IN_PROGRESS, 409)

        study = get_study(ws["study"]["id"])
        assert study["split_outcome"] is None
        assert study["status"] == "SCHEDULED"

    def test_state_error_wins_after_technical_failure(self, api):
        """PRD: "For a `SPLIT_NIGHT` study, the technologist records the
        protocol branch exactly once, while the study is `IN_PROGRESS`."
        PRD: "Every request is evaluated against a fixed pipeline of checks,
        and a request fails at the first check it violates." — a study that
        left `IN_PROGRESS` via technical failure hits the same state
        precondition, still ahead of the central-predominance safety check.

        Design: Difficulty/priority_pair_validation_conflict/split_state_beats_safety
        """
        ws = _split_in_progress()
        failed = validate_success(api.technical_failure_study(
            ws["study"]["id"],
            make_sleep_technologist_headers(ws["technologist"]["id"])))
        assert failed["status"] == "TECHNICAL_FAILURE"

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=130, partial_ahi_observed=45.0,
            central_predominance_flag=True, remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_IN_PROGRESS, 409)

        assert get_study(ws["study"]["id"])["split_outcome"] is None


class TestSplitApplicabilityAndOneShot:
    def test_split_decision_on_psg_rejected(self, api):
        """PRD: "Recording it for any other study type is rejected with
        `ERR_SPLIT_NOT_APPLICABLE`"

        Design: Corner/errors/split_decision_on_psg_rejected
        """
        ws = setup_study_in_progress(study_type="PSG_DIAGNOSTIC")

        resp = _split_payload(
            api, ws["study"]["id"], ws["technologist"]["id"],
            diagnostic_minutes_observed=130, partial_ahi_observed=45.0,
            remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_SPLIT_NOT_APPLICABLE, 409)

    def test_split_second_decision_rejected(self, api):
        """PRD: "a second attempt once `split_outcome` is set is rejected with
        `ERR_SPLIT_ALREADY_DECIDED`."

        Design: Corner/errors/split_second_decision_rejected
        """
        ws = _split_in_progress()
        study_id, tech_id = ws["study"]["id"], ws["technologist"]["id"]
        first = _split_payload(
            api, study_id, tech_id,
            diagnostic_minutes_observed=120, partial_ahi_observed=40.0,
            remaining_minutes_available=180)
        assert validate_success(first)["split_outcome"] == \
            "CONVERT_TO_TITRATION"

        resp = _split_payload(
            api, study_id, tech_id,
            diagnostic_minutes_observed=130, partial_ahi_observed=45.0,
            remaining_minutes_available=200)
        validate_error(resp, ApiErrorId.ERR_SPLIT_ALREADY_DECIDED, 409)

        study = get_study(study_id)
        assert study["split_outcome"] == "CONVERT_TO_TITRATION", (
            "The one-shot decision stands")
        assert study["split_diagnostic_minutes"] == 120


class TestCompletionAfterSplit:
    def test_converted_split_requires_titration_fields(self, api):
        """PRD: "A `TITRATION_PAP` study — or a `SPLIT_NIGHT` study whose
        `split_outcome` is `CONVERT_TO_TITRATION` — must additionally supply
        `titration_final_pressure_cm`, the ending PAP pressure in cm H2O,
        together with `leak_95th_l_min`, the 95th-percentile mask leak in
        L/min; omitting either is rejected with `ERR_INVALID_REQUEST`."
        PRD: "Completion stamps `acquisition_completed_at` from the logical
        clock — null until this moment — moves the study to `SCORING_QUEUED`,
        and fulfills the order (`SCHEDULED` → `FULFILLED`)."

        Design: Corner/endpoints/converted_split_requires_titration_fields_at_completion
        """
        ws = _split_in_progress()
        study_id, tech_id = ws["study"]["id"], ws["technologist"]["id"]
        record_split_decision(
            study_id, tech_id,
            diagnostic_minutes_observed=120, partial_ahi_observed=40.0,
            remaining_minutes_available=180)

        resp = api.complete_acquisition(
            study_id, {"total_recording_time_minutes": 400},
            make_sleep_technologist_headers(tech_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        assert get_study(study_id)["status"] == "IN_PROGRESS", (
            "The rejected completion leaves the study in progress")

        completed = validate_success(api.complete_acquisition(
            study_id,
            {"total_recording_time_minutes": 400,
             "titration_final_pressure_cm": 8.0, "leak_95th_l_min": 12.0},
            make_sleep_technologist_headers(tech_id)))
        assert completed["status"] == "SCORING_QUEUED"
        assert completed["acquisition_completed_at"] == DEFAULT_CLOCK_STAMP
        assert get_order(ws["order"]["id"])["status"] == "FULFILLED", (
            "Completing the acquisition fulfills the parent order")

    def test_continue_records_outcome_and_skips_titration_fields(self, api):
        """PRD: "An intended outcome of `CONTINUE_DIAGNOSTIC` records the
        branch with no eligibility gate — the four threshold inputs are still
        stored."

        Design: Corner/endpoints/split_continue_records_outcome_and_skips_titration_fields
        """
        ws = _split_in_progress()
        study_id, tech_id = ws["study"]["id"], ws["technologist"]["id"]

        # These inputs would fail the CONVERT gate (AHI 12.0, 100 remaining);
        # CONTINUE_DIAGNOSTIC records the branch without running the gate.
        decided = record_split_decision(
            study_id, tech_id, intended_outcome="CONTINUE_DIAGNOSTIC",
            diagnostic_minutes_observed=150, partial_ahi_observed=12.0,
            remaining_minutes_available=100)
        assert decided["split_outcome"] == "CONTINUE_DIAGNOSTIC"
        assert decided["split_partial_ahi"] == 12.0
        assert decided["split_diagnostic_minutes"] == 150

        completed = validate_success(api.complete_acquisition(
            study_id, {"total_recording_time_minutes": 420},
            make_sleep_technologist_headers(tech_id)))
        assert completed["status"] == "SCORING_QUEUED"
        assert completed.get("titration_final_pressure_cm") is None, (
            "Titration fields are required only after CONVERT_TO_TITRATION")

    def test_split_completion_without_decision_rejected(self, api):
        """PRD: "Completing the acquisition requires the study to be
        `IN_PROGRESS` (`ERR_STUDY_NOT_IN_PROGRESS`) and, for a `SPLIT_NIGHT`
        study, requires the split decision to be recorded first
        (`ERR_SPLIT_DECISION_REQUIRED`)."

        Design: Corner/errors/split_completion_without_decision_rejected
        """
        ws = _split_in_progress()

        resp = api.complete_acquisition(
            ws["study"]["id"], {"total_recording_time_minutes": 400},
            make_sleep_technologist_headers(ws["technologist"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SPLIT_DECISION_REQUIRED, 409)

        study = get_study(ws["study"]["id"])
        assert study["status"] == "IN_PROGRESS"
        assert study["acquisition_completed_at"] is None
