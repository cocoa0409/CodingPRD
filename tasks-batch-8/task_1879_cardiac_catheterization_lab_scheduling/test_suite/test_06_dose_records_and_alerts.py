"""Dose recording: per-record rounding, contrast ceiling, void compensation,
and the latching radiation alert."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_contrast_record,
    add_radiation_record,
    assert_dose_record,
    complete_case,
    create_cardiologist,
    post_case,
    setup_in_progress_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]


class TestRadiationRounding:
    def test_radiation_record_total_rounded_per_record(self, api):
        """PRD §3.6: "Each radiation entry first computes its own
        `record_total_mgy`: the `fluoroscopy_mgy` and `cine_mgy` components added
        together, then rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/radiation_report_round_per_record_then_sum
        """
        workspace = setup_in_progress_workspace()
        case = workspace["case"]
        rec1 = add_radiation_record(case["id"], 1.005, 0)
        rec2 = add_radiation_record(case["id"], 1.005, 0)
        assert_dose_record(rec1)
        assert rec1["record_total_mgy"] == pytest.approx(1.01, abs=1e-6), \
            "round_half_up(1.005 + 0, 2) per record"
        assert rec2["record_total_mgy"] == pytest.approx(1.01, abs=1e-6)

    def test_cumulative_radiation_sums_rounded_records(self, api):
        """PRD §3.6: "Rounding must happen per record, before summing; summing the
        raw components and rounding once at the end is forbidden, because the
        orders genuinely diverge — two entries each recording 1.005 mGy of
        fluoroscopy and no cine yield 2.02 mGy under the pinned order (1.01 plus
        1.01) but 2.01 mGy under the forbidden one."

        Design: Difficulty/combinatorial_formula/radiation_report_round_per_record_then_sum
        """
        workspace = setup_in_progress_workspace()
        case = workspace["case"]
        add_radiation_record(case["id"], 1.005, 0)
        add_radiation_record(case["id"], 1.005, 0)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["cumulative_radiation_mgy"] == pytest.approx(2.02, abs=1e-6), \
            "per-record rounding then sum; the forbidden order would give 2.01"
        assert current["radiation_alert"] is False, "2.02 < 5000.0"


class TestContrastCeiling:
    def test_contrast_projection_exactly_at_limit_allowed(self, api):
        """PRD §3.6: "The projected total — the case's current
        `cumulative_contrast_ml` plus the new entry's `contrast_ml` — may not
        exceed the ceiling: a projection strictly above the limit is rejected with
        `ERR_CONTRAST_LIMIT_EXCEEDED`, while a projection landing exactly on the
        limit is allowed."
        PRD §3.2: "A 60 kg patient with a creatinine of 1.5 mg/dL receives a
        ceiling of 200.0 mL"

        Design: Difficulty/boundary_precision_check/contrast_exactly_at_limit_allowed_above_rejected
        """
        workspace = setup_in_progress_workspace(weight_kg=60, serum_creatinine=1.5)
        case = workspace["case"]
        assert case["contrast_limit_ml"] == pytest.approx(200.0, abs=1e-6)
        rec1 = add_contrast_record(case["id"], 150)
        assert_dose_record(rec1)
        rec2 = add_contrast_record(case["id"], 50.0)
        assert rec2["status"] == "ACTIVE", "projection 200.0 == limit: allowed"
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["cumulative_contrast_ml"] == pytest.approx(200.0, abs=1e-6)

    def test_contrast_projection_above_limit_rejected(self, api):
        """PRD §3.6: "a projection strictly above the limit is rejected with
        `ERR_CONTRAST_LIMIT_EXCEEDED`, while a projection landing exactly on the
        limit is allowed."
        PRD §3.6: "Accepted entries raise `cumulative_contrast_ml`, the running sum
        over the case's `ACTIVE` contrast entries."

        Design: Difficulty/boundary_precision_check/contrast_exactly_at_limit_allowed_above_rejected
        """
        workspace = setup_in_progress_workspace(weight_kg=60, serum_creatinine=1.5)
        case = workspace["case"]
        add_contrast_record(case["id"], 150)
        add_contrast_record(case["id"], 50.0)  # cumulative exactly 200.0
        resp = api.create_dose_record(
            case["id"], {"record_type": "CONTRAST", "contrast_ml": 0.1},
            TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_CONTRAST_LIMIT_EXCEEDED,
                       expected_status=422)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["cumulative_contrast_ml"] == pytest.approx(200.0, abs=1e-6), \
            "the rejected entry is not persisted"


class TestContrastBudgetConservation:
    def test_contrast_add_consumes_budget(self, api):
        """PRD §3.6: "Accepted entries raise `cumulative_contrast_ml`, the running
        sum over the case's `ACTIVE` contrast entries."
        PRD §3.2: "At posting time the server computes the patient's contrast
        ceiling and stores it as `contrast_limit_ml`."

        Design: Difficulty/compensating_invariant/dose_add_void_pair_conserves_contrast_budget
        """
        workspace = setup_in_progress_workspace(weight_kg=60, serum_creatinine=1.5)
        case = workspace["case"]
        add_contrast_record(case["id"], 70)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["cumulative_contrast_ml"] == pytest.approx(70.0, abs=1e-6)
        assert current["contrast_limit_ml"] == pytest.approx(200.0, abs=1e-6)
        # Budget accounting: 70.0 consumed + 130.0 remaining == 200.0 ceiling.

    def test_contrast_void_restores_budget(self, api):
        """PRD §3.6: "The entry moves `ACTIVE` → `VOIDED`, and both cumulative
        totals are recomputed over the remaining `ACTIVE` entries."
        PRD §3.2: "At posting time the server computes the patient's contrast
        ceiling and stores it as `contrast_limit_ml`."

        Design: Difficulty/compensating_invariant/dose_add_void_pair_conserves_contrast_budget
        """
        workspace = setup_in_progress_workspace(weight_kg=60, serum_creatinine=1.5)
        case = workspace["case"]
        record = add_contrast_record(case["id"], 70)
        voided = validate_success(api.void_dose_record(record["id"], TECHNOLOGIST))
        assert voided["status"] == "VOIDED"
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["cumulative_contrast_ml"] == pytest.approx(0.0, abs=1e-6), \
            "the compensating void fully restores the budget"
        assert current["contrast_limit_ml"] == pytest.approx(200.0, abs=1e-6), \
            "the ceiling is fixed at posting and unchanged by the pair"


class TestDoseRecordStateGates:
    def test_dose_record_on_posted_case_returns_invalid_state(self, api):
        """PRD §3.6: "While a case is `IN_PROGRESS`, a `CathLabTechnologist`
        records dose entries against it; adding an entry in any other case state
        is refused with `ERR_CASE_INVALID_STATE`."

        Design: Corner/state_machines/dose_record_on_posted_case_returns_invalid_state
        """
        physician = create_cardiologist()
        case = post_case(physician["id"])
        assert case["status"] == "POSTED"
        resp = api.create_dose_record(
            case["id"], {"record_type": "CONTRAST", "contrast_ml": 10},
            TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        _, meta = validate_paginated(
            api.list_case_dose_records(case["id"], TECHNOLOGIST))
        assert meta["total_count"] == 0

    def test_double_void_dose_record_returns_already_voided(self, api):
        """PRD §3.6: "It requires the parent case `IN_PROGRESS` — otherwise
        `ERR_CASE_INVALID_STATE` — and the entry still `ACTIVE`; voiding an
        already-`VOIDED` record is refused with
        `ERR_DOSE_RECORD_ALREADY_VOIDED`."

        Design: Corner/state_machines/double_void_dose_record_returns_already_voided
        """
        workspace = setup_in_progress_workspace()
        record = add_radiation_record(workspace["case"]["id"], 10, 5)
        validate_success(api.void_dose_record(record["id"], TECHNOLOGIST))
        resp = api.void_dose_record(record["id"], TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_DOSE_RECORD_ALREADY_VOIDED,
                       expected_status=409)
        records, _ = validate_paginated(
            api.list_case_dose_records(workspace["case"]["id"], TECHNOLOGIST))
        assert records[0]["status"] == "VOIDED"

    def test_void_dose_record_after_case_completed_returns_invalid_state(self, api):
        """PRD §3.6: "It requires the parent case `IN_PROGRESS` — otherwise
        `ERR_CASE_INVALID_STATE` — and the entry still `ACTIVE`; voiding an
        already-`VOIDED` record is refused with
        `ERR_DOSE_RECORD_ALREADY_VOIDED`."

        Design: Corner/state_machines/void_dose_record_after_case_completed_returns_invalid_state
        """
        workspace = setup_in_progress_workspace()
        case = workspace["case"]
        record = add_contrast_record(case["id"], 50)
        complete_case(case["id"], workspace["physician"]["id"])
        resp = api.void_dose_record(record["id"], TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        records, _ = validate_paginated(
            api.list_case_dose_records(case["id"], TECHNOLOGIST))
        assert records[0]["status"] == "ACTIVE"
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["cumulative_contrast_ml"] == pytest.approx(50.0, abs=1e-6)


class TestRadiationAlertLatch:
    def test_radiation_alert_latches_at_threshold_and_survives_void(self, api):
        """PRD §3.6: "When the cumulative figure reaches 5,000.0 mGy — equality
        triggers — the case's `radiation_alert` flag is set true, and it latches:
        once raised, it never clears automatically."
        PRD §3.6: "Even if the recomputed radiation total drops back below
        5,000.0 mGy, a latched `radiation_alert` stays set."

        Design: Corner/cross_cutting_complexity_layers/radiation_alert_latches_at_threshold_and_survives_void
        """
        workspace = setup_in_progress_workspace()
        case = workspace["case"]
        add_radiation_record(case["id"], 2500, 0)
        rec2 = add_radiation_record(case["id"], 2500, 0)
        at_threshold = validate_success(api.get_case(case["id"], SCHEDULER))
        assert at_threshold["cumulative_radiation_mgy"] == pytest.approx(
            5000.0, abs=1e-6)
        assert at_threshold["radiation_alert"] is True, \
            "equality triggers the alert"

        validate_success(api.void_dose_record(rec2["id"], TECHNOLOGIST))
        after_void = validate_success(api.get_case(case["id"], SCHEDULER))
        assert after_void["cumulative_radiation_mgy"] == pytest.approx(
            2500.0, abs=1e-6)
        assert after_void["radiation_alert"] is True, \
            "the latched alert survives the compensating void"
