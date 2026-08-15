"""Dose entry: clinical-safety checks, ordinal uniqueness, OCC, verify and void."""
from test_helpers import (
    ApiErrorId,
    add_manual_dose,
    add_verified_dose,
    api_client,
    assert_immunization_record,
    assert_student,
    create_immunization_record_payload,
    create_mmr_requirement,
    create_student,
    get_student,
    list_student_records,
    validate_error,
    validate_success,
    void_record_payload,
)


class TestDoseSafetyAndUniqueness:

    def test_min_age_violation_rejected(self, clerk_headers):
        """PRD section 3.3: "First, the `administered_date` must not fall before the
        student's `date_of_birth` plus the applicable requirement's `min_age_months`
        whole calendar months; a dose administered too early is rejected with
        `ERR_MIN_AGE_VIOLATION` (HTTP 422)."

        Design: Corner/calculations/min_age_violation_rejected
        """
        create_mmr_requirement(doses_required=1, min_age_months=12)
        student = create_student(
            "SCH-Z1", legal_name="Too Young", date_of_birth="2025-08-01T00:00:00Z"
        )
        # DOB 2025-08-01 + 12 whole calendar months = 2026-08-01; the dose below
        # (2026-07-15) precedes that boundary.
        resp = api_client.create_immunization_record(
            student["id"],
            create_immunization_record_payload(
                student["version"], administered_date="2026-07-15T00:00:00Z"
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MIN_AGE_VIOLATION)

    def test_duplicate_dose_rejected(self, clerk_headers):
        """PRD section 3.3: "Independently of timing, the dose ordinal must be
        unique: among records that are not `VOIDED`, no two records for the same
        student and vaccine may share a `dose_number`, and a colliding entry is
        rejected with `ERR_DUPLICATE_DOSE`."

        Design: Corner/calculations/duplicate_dose_rejected
        """
        create_mmr_requirement(doses_required=2, min_interval_days=28)
        student = create_student("SCH-Z2", legal_name="Dupe Dose")
        add_manual_dose(student["id"], student["version"],
                        administered_date="2026-08-05T00:00:00Z")
        refreshed = get_student(student["id"])
        # 2026-09-10 is 36 days after 2026-08-05 (>= 28), so only the duplicate
        # ordinal can reject this entry.
        resp = api_client.create_immunization_record(
            student["id"],
            create_immunization_record_payload(
                refreshed["version"],
                dose_number=1,
                administered_date="2026-09-10T00:00:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DOSE)

    def test_safety_masks_duplicate_on_interval_violation(self, clerk_headers):
        """PRD section 2.7: "When multiple checks could reject the same request, the
        system evaluates them in a fixed priority order and surfaces the first
        failure encountered."
        PRD section 2.7: "6. **Dose clinical safety** — evaluated only on manual
        dose entry, in this order: (6a) the administered date must not precede the
        minimum-age boundary for the applicable requirement, else
        `ERR_MIN_AGE_VIOLATION`; then (6b) the administered date must respect the
        minimum interval after the latest prior dose of the same vaccine, else
        `ERR_MIN_INTERVAL_VIOLATION`."
        PRD section 2.7: "8. **Uniqueness, segregation, and allowability** — in this
        order: (8a) no duplicate dose ordinal, else `ERR_DUPLICATE_DOSE`".

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_dose_entry
        """
        create_mmr_requirement(doses_required=2, min_interval_days=28)
        student = create_student("SCH-Z", legal_name="Sam Zee")
        add_verified_dose(student["id"], administered_date="2026-08-05T00:00:00Z")
        refreshed = get_student(student["id"])
        # 2026-08-20 is 15 days after 2026-08-05 (< 28) AND reuses dose_number 1:
        # the safety check (priority 6) must surface ahead of the uniqueness
        # check (priority 8).
        resp = api_client.create_immunization_record(
            student["id"],
            create_immunization_record_payload(
                refreshed["version"],
                dose_number=1,
                administered_date="2026-08-20T00:00:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MIN_INTERVAL_VIOLATION)

    def test_safety_masks_duplicate_on_min_age_violation(self, clerk_headers):
        """PRD section 2.7: "When multiple checks could reject the same request, the
        system evaluates them in a fixed priority order and surfaces the first
        failure encountered."
        PRD section 2.7: "6. **Dose clinical safety** — evaluated only on manual
        dose entry, in this order: (6a) the administered date must not precede the
        minimum-age boundary for the applicable requirement, else
        `ERR_MIN_AGE_VIOLATION`; then (6b) the administered date must respect the
        minimum interval after the latest prior dose of the same vaccine, else
        `ERR_MIN_INTERVAL_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_dose_entry
        """
        create_mmr_requirement(doses_required=2, min_interval_days=28,
                               min_age_months=12)
        student = create_student("SCH-Z", legal_name="Sam Zee",
                                 date_of_birth="2020-06-15T00:00:00Z")
        add_verified_dose(student["id"], administered_date="2026-08-05T00:00:00Z")
        refreshed = get_student(student["id"])
        # DOB 2020-06-15 + 12 months = 2021-06-15; 2021-06-01 precedes that
        # boundary AND reuses dose_number 1: check (6a) must surface first.
        resp = api_client.create_immunization_record(
            student["id"],
            create_immunization_record_payload(
                refreshed["version"],
                dose_number=1,
                administered_date="2021-06-01T00:00:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MIN_AGE_VIOLATION)


class TestDoseOccAndVoid:

    def test_occ_stale_student_version_on_dose_create(self, clerk_headers):
        """PRD section 2.6: "Recording a dose against a student requires the request
        to carry `expected_student_version`, holding the `version` of the Student
        the client last observed. Dose creation legitimately mutates the student —
        every creation recomputes the student's derived compliance fields and
        increments `version` — so if the supplied value does not equal the
        student's current `version`, the request is rejected with
        `ERR_STALE_STUDENT_VERSION` (HTTP 412): the client is writing against a
        superseded view of the student's record."

        Design: Corner/cross_cutting_layers/occ_stale_student_version_on_dose_create
        """
        create_mmr_requirement(doses_required=2, min_interval_days=28)
        student = create_student("SCH-OCC", legal_name="Occ Stu")
        stale_version = student["version"]
        add_manual_dose(student["id"], stale_version,
                        administered_date="2026-08-05T00:00:00Z")
        # The first creation advanced Student.version; replaying the captured
        # version must now be rejected.
        resp = api_client.create_immunization_record(
            student["id"],
            create_immunization_record_payload(
                stale_version, dose_number=2,
                administered_date="2026-09-10T00:00:00Z",
            ),
            clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_STUDENT_VERSION)
        records, meta = list_student_records(student["id"])
        assert meta["total_count"] == 1, "a rejected write must not create a record"

    def test_void_verified_dose_recomputes_deficiency(self, nurse_headers):
        """PRD section 3.3: "Voiding a previously verified record can cost the
        student their standing: if at least one applicable requirement is no longer
        satisfied after the void, a student in `ENROLLED_COMPLIANT` falls back to
        `ENROLLED_PROVISIONAL` when the current logical clock is at or before the
        student's `provisional_deadline`, and falls to `NON_COMPLIANT` when the
        clock is strictly past that deadline. In both cases
        `deficiency_vaccine_codes` is recomputed and the student's `version`
        incremented."

        Design: Corner/cross_cutting_layers/void_verified_dose_recomputes_deficiency
        """
        create_mmr_requirement(doses_required=1)
        student = create_student("SCH-VD", legal_name="Void Dose")
        record = add_verified_dose(student["id"],
                                   administered_date="2026-08-05T00:00:00Z")
        compliant = get_student(student["id"])
        assert compliant["status"] == "ENROLLED_COMPLIANT"
        assert compliant["deficiency_vaccine_codes"] == []

        resp = api_client.void_immunization_record(
            record["id"], void_record_payload(), nurse_headers
        )
        voided = validate_success(resp, 200)
        assert_immunization_record(voided)
        assert voided["status"] == "VOIDED"

        reverted = get_student(student["id"])
        assert_student(reverted)
        # Clock is still the startup default 2026-08-01, at or before the
        # provisional deadline 2026-08-31, so the student falls back to
        # ENROLLED_PROVISIONAL.
        assert reverted["status"] == "ENROLLED_PROVISIONAL"
        assert reverted["deficiency_vaccine_codes"] == ["MMR"]
        assert reverted["version"] > compliant["version"]
