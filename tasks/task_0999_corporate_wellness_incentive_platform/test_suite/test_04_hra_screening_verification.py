"""Health assessment scoring, biometric screenings, verification axis (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_employee,
    create_enrollment,
    accept_enrollment,
    create_screening,
    result_screening,
    set_clock,
    setup_active_enrollment,
    setup_cohort,
    setup_verified_enrollment,
    submit_hra,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


def employee_headers(ctx_or_employee):
    """Ownership-gated Employee headers for a fixture context or employee dict."""
    from test_helpers import make_employee_headers

    employee = ctx_or_employee.get("employee", ctx_or_employee)
    return make_employee_headers(employee["id"])


class TestHighRiskHraCascade:
    """Difficulty instance: HRA scoring -> verification flip -> auto referral -> count."""

    def test_high_hra_scores_and_verifies(self, api):
        """PRD §3.4: "The computed `risk_score` is the plain sum of the ten answers,
        and the `risk_band` follows fixed cut lines: `LOW` when the score is below
        30, `MODERATE` when it is at least 30 but below 60, and `HIGH` when it is
        60 or more."
        PRD §3.3: "Creating a member's first HealthAssessment moves `PENDING →
        VERIFIED` automatically."

        Design: Difficulty/transitive_cascade/hra_high_risk_transitive_cascade
        """
        ctx = setup_active_enrollment()
        hra = validate_success(
            api.create_hra(
                {"enrollment_id": ctx["enrollment"]["id"], "answers": [7] * 10},
                employee_headers(ctx),
            ),
            201,
        )
        assert hra["risk_score"] == 70
        assert hra["risk_band"] == "HIGH"

        after = validate_success(api.get_enrollment(ctx["enrollment"]["id"], BA), 200)
        assert after["verification_status"] == "VERIFIED"

    def test_high_hra_auto_creates_referral(self, api):
        """PRD §3.4: "a `HIGH` band additionally auto-creates a CoachingReferral with
        `reason` set to `HIGH_RISK`, `source` set to `AUTO_RISK`, and status
        `REFERRED`, incrementing the enrollment's `auto_referral_count` by one."

        Design: Difficulty/transitive_cascade/hra_high_risk_transitive_cascade
        """
        ctx = setup_active_enrollment()
        submit_hra(ctx["enrollment"]["id"], ctx["employee"]["id"], answers=[7] * 10)

        referrals, meta = validate_paginated(
            api.list_enrollment_coaching_referrals(ctx["enrollment"]["id"], BA)
        )
        assert meta["total_count"] == 1
        referral = referrals[0]
        assert referral["source"] == "AUTO_RISK"
        assert referral["reason"] == "HIGH_RISK"
        assert referral["status"] == "REFERRED"

        after = validate_success(api.get_enrollment(ctx["enrollment"]["id"], BA), 200)
        assert after["auto_referral_count"] == 1


class TestHraRiskBandBoundaries:
    def test_hra_risk_band_lower_boundaries(self, api):
        """PRD §3.4: "the `risk_band` follows fixed cut lines: `LOW` when the score
        is below 30, `MODERATE` when it is at least 30 but below 60, and `HIGH`
        when it is 60 or more."
        PRD §3.4: "a `HIGH` band additionally auto-creates a CoachingReferral with
        `reason` set to `HIGH_RISK`, `source` set to `AUTO_RISK`, and status
        `REFERRED`, incrementing the enrollment's `auto_referral_count` by one."

        Design: Corner/calculations/hra_risk_band_lower_boundaries
        """
        ctx = setup_cohort(2)
        enr_1, enr_2 = ctx["enrollments"]
        emp_1, emp_2 = ctx["employees"]

        hra_1 = submit_hra(enr_1["id"], emp_1["id"], answers=[3] * 10)
        assert hra_1["risk_score"] == 30
        assert hra_1["risk_band"] == "MODERATE"
        after_1 = validate_success(api.get_enrollment(enr_1["id"], BA), 200)
        assert after_1["auto_referral_count"] == 0, "MODERATE creates no auto-referral"

        hra_2 = submit_hra(enr_2["id"], emp_2["id"], answers=[6] * 10)
        assert hra_2["risk_score"] == 60
        assert hra_2["risk_band"] == "HIGH"
        after_2 = validate_success(api.get_enrollment(enr_2["id"], BA), 200)
        assert after_2["auto_referral_count"] == 1, "HIGH auto-creates one referral"


class TestHraDuplicate:
    def test_hra_duplicate_rejected(self, api):
        """PRD §3.4: "no prior assessment may exist for the enrollment (otherwise
        `ERR_HRA_ALREADY_COMPLETED`)..."

        Design: Corner/errors/hra_duplicate_rejected
        """
        ctx = setup_active_enrollment()
        submit_hra(ctx["enrollment"]["id"], ctx["employee"]["id"], answers=[2] * 10)

        res = api.create_hra(
            {"enrollment_id": ctx["enrollment"]["id"], "answers": [1] * 10},
            employee_headers(ctx),
        )
        validate_error(res, ApiErrorId.ERR_HRA_ALREADY_COMPLETED, expected_status=409)

        _data, meta = validate_paginated(
            api.list_enrollment_hras(ctx["enrollment"]["id"], BA)
        )
        assert meta["total_count"] == 1, "the first HRA remains the only one"


class TestBiometricTargets:
    def test_biometric_targets_strict_less_than(self, api):
        """PRD §3.4: "From these the system computes `targets_met`, a count from zero
        to four of the strict targets achieved — `bmi` strictly below 30.0,
        `systolic_bp` strictly below 140, `total_cholesterol` strictly below 200,
        and `glucose` strictly below 100 — and drives the verification axis: a
        result meeting at most one target flags the enrollment, moving
        `verification_status` from `VERIFIED` to `FLAGGED`..."

        Design: Corner/calculations/biometric_targets_strict_less_than
        """
        ctx = setup_verified_enrollment(answers=[2] * 10)
        screening = create_screening(ctx["enrollment"]["id"], ctx["employee"]["id"])

        resulted = validate_success(
            api.result_biometric_screening(
                screening["id"],
                {"bmi": 30.0, "systolic_bp": 140, "total_cholesterol": 200, "glucose": 100},
                BA,
            ),
            200,
        )
        assert resulted["targets_met"] == 0, (
            "measurements exactly AT their thresholds meet zero targets (strict <)"
        )
        assert resulted["status"] == "RESULTED"

        after = validate_success(api.get_enrollment(ctx["enrollment"]["id"], BA), 200)
        assert after["verification_status"] == "FLAGGED"


class TestScreeningWindows:
    def test_screening_slot_outside_plan_year_rejected(self, api):
        """PRD §3.4: "the slot sits inside the plan year, `slot_start` on or after
        `plan_year_start` and `slot_end` on or before `plan_year_end` (otherwise
        `ERR_SLOT_OUTSIDE_WINDOW`)."

        Design: Corner/validations/screening_slot_outside_plan_year_rejected
        """
        ctx = setup_active_enrollment()
        res = api.create_biometric_screening(
            {
                "enrollment_id": ctx["enrollment"]["id"],
                "clinic_location": "HQ",
                "slot_start": "2027-03-01T10:00:00Z",
                "slot_end": "2027-03-01T10:30:00Z",
            },
            employee_headers(ctx),
        )
        validate_error(res, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW, expected_status=422)

    def test_screening_no_show_on_clock_sweep(self, api):
        """PRD §2.5: "Every BiometricScreening still `SCHEDULED` whose `slot_end` is
        strictly earlier than the new current instant transitions to `NO_SHOW`."
        PRD §3.4: "A screening whose slot passes without results is swept to
        `NO_SHOW` when the logical clock advances strictly past its `slot_end`..."

        Design: Corner/state_machines/screening_no_show_on_clock_sweep
        """
        ctx = setup_active_enrollment()
        screening = create_screening(ctx["enrollment"]["id"], ctx["employee"]["id"])
        assert screening["status"] == "SCHEDULED"

        set_clock("2026-05-02T00:00:00Z")

        screenings, _meta = validate_paginated(
            api.list_enrollment_biometric_screenings(ctx["enrollment"]["id"], BA)
        )
        by_id = {s["id"]: s for s in screenings}
        assert by_id[screening["id"]]["status"] == "NO_SHOW"


class TestKioskCapacity:
    """Difficulty instance: aggregate capacity pool per clinic_location; overlaps
    allowed below kiosk_capacity, rejected at it; adjacency never counts."""

    def test_third_overlapping_screening_rejected(self, api):
        """PRD §3.4: "the number of other `SCHEDULED` screenings at the same
        `clinic_location` whose slots strictly overlap the new one must stay below
        the employer's `kiosk_capacity`, otherwise `ERR_KIOSK_CAPACITY_EXCEEDED`..."

        Design: Difficulty/resource_temporal_overlap/kiosk_slot_aggregate_capacity
        """
        ctx = setup_cohort(3)
        enr_1, enr_2, enr_3 = ctx["enrollments"]
        emp_1, emp_2, emp_3 = ctx["employees"]

        first = create_screening(
            enr_1["id"], emp_1["id"],
            slot_start="2026-04-20T10:00:00Z", slot_end="2026-04-20T10:30:00Z",
        )
        assert first["status"] == "SCHEDULED"
        second = create_screening(
            enr_2["id"], emp_2["id"],
            slot_start="2026-04-20T10:15:00Z", slot_end="2026-04-20T10:45:00Z",
        )
        assert second["status"] == "SCHEDULED", (
            "second overlapping appointment allowed: overlapping count 1 < capacity 2"
        )

        res = api.create_biometric_screening(
            {
                "enrollment_id": enr_3["id"],
                "clinic_location": "HQ",
                "slot_start": "2026-04-20T10:20:00Z",
                "slot_end": "2026-04-20T10:50:00Z",
            },
            employee_headers(emp_3),
        )
        validate_error(res, ApiErrorId.ERR_KIOSK_CAPACITY_EXCEEDED, expected_status=409)

    def test_adjacent_slot_beyond_capacity_allowed(self, api):
        """PRD §3.4: "the number of other `SCHEDULED` screenings at the same
        `clinic_location` whose slots strictly overlap the new one must stay below
        the employer's `kiosk_capacity`, otherwise `ERR_KIOSK_CAPACITY_EXCEEDED`,
        where strict overlap means the new slot starts before the other's end and
        ends after the other's start, so back-to-back adjacency never counts as
        overlap..."

        Design: Difficulty/resource_temporal_overlap/kiosk_slot_aggregate_capacity
        """
        ctx = setup_cohort(3)
        enr_1, enr_2, enr_3 = ctx["enrollments"]
        emp_1, emp_2, emp_3 = ctx["employees"]

        create_screening(
            enr_1["id"], emp_1["id"],
            slot_start="2026-04-20T10:00:00Z", slot_end="2026-04-20T11:00:00Z",
        )
        create_screening(
            enr_2["id"], emp_2["id"],
            slot_start="2026-04-20T10:00:00Z", slot_end="2026-04-20T11:00:00Z",
        )
        # Two identical slots are already at capacity (2); a strictly adjacent
        # third slot overlaps neither and must be accepted.
        third = validate_success(
            api.create_biometric_screening(
                {
                    "enrollment_id": enr_3["id"],
                    "clinic_location": "HQ",
                    "slot_start": "2026-04-20T11:00:00Z",
                    "slot_end": "2026-04-20T12:00:00Z",
                },
                employee_headers(emp_3),
            ),
            201,
        )
        assert third["status"] == "SCHEDULED"
