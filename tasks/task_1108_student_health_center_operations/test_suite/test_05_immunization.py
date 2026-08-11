"""Immunization claims: dose temporal rules, record uniqueness, exemption
lockout, the grace-window posture derivation, and dose-recording OCC
(PRD §2.8, §3.1, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_immunization_record,
    create_appointment_payload,
    create_immunization_record_payload,
    exempt_record_payload,
    get_student,
    make_immunization_record,
    make_provider,
    make_requirement,
    make_student,
    record_dose_payload,
    set_clock,
    validate_error,
    validate_success,
)


def test_immunization_record_dose_error_matrix(api, nurse_headers,
                                               clinician_headers):
    """PRD §3.3: "except for the very first dose, which is unconstrained — it
    must fall at least `min_interval_days` after the previous recorded dose
    (`ERR_DOSE_INTERVAL_VIOLATION`)".
    PRD §3.3: "it may not lie in the future relative to the current logical date
    (`ERR_DOSE_DATE_IN_FUTURE`)".
    PRD §3.3: "At most one non-terminal record may exist for a given
    student–requirement pair; attempting to open a second while the first is
    neither `IN_COMPLIANCE` nor `EXEMPTED` is rejected with
    `ERR_DUPLICATE_IMMUNIZATION_RECORD`."
    PRD §3.3: "a dose against an `IN_COMPLIANCE` or `EXEMPTED` record is
    rejected with `ERR_RECORD_NOT_DOSEABLE`."

    Design: Corner/state_machines/immunization_record_dose_error_matrix
    """
    set_clock("2026-05-01T00:00:00Z")
    requirement = make_requirement(
        vaccine_code="MMR", required_doses=2, min_interval_days=28,
        deadline_date="2026-08-01", grace_period_days=0,
    )
    student = make_student("S27", "Dose Errors")
    record = make_immunization_record(student["id"], requirement["id"])
    assert_immunization_record(record)
    assert record["status"] == "PENDING"

    # First dose (unconstrained by the interval rule).
    after_first = validate_success(
        api.record_dose(
            record["id"],
            record_dose_payload("2026-04-01", record["version"]),
            nurse_headers,
        ),
        200,
    )
    assert after_first["doses_received"] == 1
    assert after_first["version"] == record["version"] + 1

    # 2026-04-20 < 2026-04-01 + 28 days (= 2026-04-29): interval violation.
    res1 = api.record_dose(
        record["id"],
        record_dose_payload("2026-04-20", after_first["version"]),
        nurse_headers,
    )
    validate_error(res1, ApiErrorId.ERR_DOSE_INTERVAL_VIOLATION, expected_status=422)

    # 2026-05-02 > current logical date 2026-05-01: future dose.
    res2 = api.record_dose(
        record["id"],
        record_dose_payload("2026-05-02", after_first["version"]),
        nurse_headers,
    )
    validate_error(res2, ApiErrorId.ERR_DOSE_DATE_IN_FUTURE, expected_status=422)

    # Second non-terminal record for the same (student, requirement).
    res3 = api.create_immunization_record(
        create_immunization_record_payload(student["id"], requirement["id"]),
        nurse_headers,
    )
    validate_error(res3, ApiErrorId.ERR_DUPLICATE_IMMUNIZATION_RECORD,
                   expected_status=409)

    # Exempt the record; terminal records reject further doses.
    exempted = validate_success(
        api.exempt_immunization_record(
            record["id"], exempt_record_payload("medical contraindication"),
            clinician_headers,
        ),
        200,
    )
    assert exempted["status"] == "EXEMPTED"
    assert exempted["exemption_reason"] == "medical contraindication"

    res4 = api.record_dose(
        record["id"],
        record_dose_payload("2026-05-01", exempted["version"]),
        nurse_headers,
    )
    validate_error(res4, ApiErrorId.ERR_RECORD_NOT_DOSEABLE, expected_status=409)


def test_posture_grace_window_provisional_hold(api, front_desk_headers):
    """PRD §3.1: "The posture is `REGISTRATION_HOLD` whenever either an
    immunization hold or a financial hold is present; it is `PROVISIONAL_HOLD`
    when no registration-level hold exists but at least one record is in grace;
    otherwise it is `CLEAR`."
    PRD §3.1: "a grace-period student shows neither (a provisional hold
    contributes no entry to the set)".
    PRD §3.4: "a `PROVISIONAL_HOLD` does not block elective booking".

    Design: Corner/calculations/posture_grace_window_provisional_hold
    """
    set_clock("2026-05-01T00:00:00Z")
    requirement = make_requirement(
        vaccine_code="MMR", required_doses=2, min_interval_days=28,
        deadline_date="2026-05-10", grace_period_days=5,
    )
    student = make_student("S40", "Grace Test")
    record = make_immunization_record(student["id"], requirement["id"])
    provider = make_provider("Dr P")

    # 2026-05-10 < 2026-05-12 <= 2026-05-15 (deadline + grace): record in GRACE.
    set_clock("2026-05-12T00:00:00Z")

    record_after = validate_success(
        api.get_immunization_record(record["id"], front_desk_headers), 200
    )
    assert record_after["status"] == "GRACE"

    student_after = get_student(student["id"])
    assert student_after["compliance_posture"] == "PROVISIONAL_HOLD"
    assert student_after["active_hold_types"] == [], (
        "a provisional hold contributes no entry to active_hold_types"
    )

    # Elective booking remains allowed under PROVISIONAL_HOLD.
    appt = validate_success(
        api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "SPORTS_PHYSICAL",
                "2026-05-13T10:00:00Z", "2026-05-13T10:30:00Z",
            ),
            front_desk_headers,
        ),
        201,
    )
    assert appt["status"] == "BOOKED"


def test_occ_stale_record_version_on_dose_entry(api, nurse_headers):
    """PRD §2.8: "a dose-recording request must carry `expected_record_version`,
    the caller's last-observed `version` of the immunization record. If the
    record's current `version` no longer matches — because another dose was
    recorded against it since the caller last read it — the request is rejected
    with `ERR_STALE_RECORD_VERSION` (HTTP 412)".
    PRD §3.3: "When the incremented count reaches the requirement's
    `required_doses`, the record transitions to `IN_COMPLIANCE`".

    Design: Corner/cross_cutting_layers/occ_stale_record_version_on_dose_entry
    """
    set_clock("2026-05-01T00:00:00Z")
    requirement = make_requirement(
        vaccine_code="MMR", required_doses=2, min_interval_days=28,
        deadline_date="2026-08-01", grace_period_days=0,
    )
    student = make_student("S71", "Occ Rec")
    record = make_immunization_record(student["id"], requirement["id"])
    stale_version = record["version"]

    after_first = validate_success(
        api.record_dose(
            record["id"],
            record_dose_payload("2026-04-01", stale_version),
            nurse_headers,
        ),
        200,
    )
    assert after_first["doses_received"] == 1
    assert after_first["version"] == stale_version + 1

    # The stale version is rejected even though the dose date itself is valid
    # (2026-05-01 satisfies the 28-day interval from 2026-04-01 and is not in
    # the future).
    res = api.record_dose(
        record["id"],
        record_dose_payload("2026-05-01", stale_version),
        nurse_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_RECORD_VERSION, expected_status=412)

    # Retrying with the fresh version succeeds and completes the requirement.
    completed = validate_success(
        api.record_dose(
            record["id"],
            record_dose_payload("2026-05-01", after_first["version"]),
            nurse_headers,
        ),
        200,
    )
    assert completed["doses_received"] == 2
    assert completed["status"] == "IN_COMPLIANCE"
    assert completed["dose_dates"] == ["2026-04-01", "2026-05-01"]
