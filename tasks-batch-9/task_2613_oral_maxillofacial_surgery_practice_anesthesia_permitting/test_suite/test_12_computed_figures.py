"""Computed figures: inspection scoring, benefit routing and allocation at
creation, imaging retention and dose flags, distinct drill coverage, the block
minute ledger, and the LOCAL_ONLY fixed point of the confirmation gate."""
import pytest

from test_helpers import (
    ADMIN,
    BENEFITS,
    SCHEDULER,
    apply_permit,
    assert_block_ledger_conserved,
    assert_determination,
    assert_imaging_study,
    assert_inspection,
    assert_money_identity,
    assert_permit,
    assert_surgical_case,
    create_block,
    create_case,
    create_determination_payload,
    create_evaluation_payload,
    create_imaging_study_payload,
    create_patient,
    create_practice,
    create_staff,
    day_of_verification_payload,
    fetch_block,
    fetch_case,
    fetch_permit,
    fetch_practice,
    hold_case_on_block,
    log_drill,
    make_anesthesia_coordinator_headers,
    make_surgeon_headers,
    parse_iso,
    record_inspection_result,
    schedule_inspection,
    service_line,
    set_clock,
    validate_paginated,
    validate_success,
)


def test_calc_inspection_score_of_exactly_seventy_passes(api):
    """PRD: "The score starts at 100; each minor deficiency costs 2 points, each
    major deficiency costs 7 points, and each critical deficiency costs 25 points."
    PRD: "Otherwise, if `inspection_score` is at or above 70 the inspection is
    `PASSED`; because that comparison is inclusive, a score of exactly 70 passes."
    PRD: "A `FAILED_CORRECTABLE` result on a permit in `INSPECTION_PENDING` sends
    it back to `APPLIED` with `last_enforcement_reason` `DEFICIENCY_SCORE`, the
    privilege recomputed to `UNPERMITTED`, and the permit's `version` incremented;
    this is the revision cycle, and the applicant may schedule a fresh inspection
    from `APPLIED` again."
    PRD: "A `PASSED` result on a permit in `INSPECTION_PENDING` whose ratio is
    below 0.75 instead lands on `PROBATION`"

    Five major deficiencies score 65 and fail correctably; one minor plus four
    majors score exactly 70 and pass. No drill has ever been logged, so the
    passing inspection still lands the permit on probation.

    Design: Corner/calculations/inspection_score_of_exactly_seventy_passes
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = create_practice(name="Score OMS", state_code="OH", recovery_bay_count=2)
    permit = apply_permit(practice["id"], "MINIMAL_SEDATION", "2026-09-01T00:00:00Z")

    first = schedule_inspection(permit["id"], "2026-09-02T09:00:00Z")
    assert fetch_permit(permit["id"])["status"] == "INSPECTION_PENDING"
    set_clock("2026-09-02T10:00:00Z")
    failed = record_inspection_result(first["id"], minor=0, major=5, critical=0)

    assert_inspection(failed)
    assert failed["inspection_score"] == 65, (
        f"100 less five major deficiencies at 7 points is 65, got {failed['inspection_score']}"
    )
    assert failed["status"] == "FAILED_CORRECTABLE", (
        f"a score of 65 is below the 70 floor, got {failed['status']}"
    )
    reverted = fetch_permit(permit["id"])
    assert reverted["status"] == "APPLIED", (
        f"a correctable failure returns the permit to APPLIED, got {reverted['status']}"
    )
    assert reverted["last_enforcement_reason"] == "DEFICIENCY_SCORE"
    assert fetch_practice(practice["id"])["sedation_privilege_state"] == "UNPERMITTED"

    second = schedule_inspection(permit["id"], "2026-09-10T09:00:00Z")
    set_clock("2026-09-10T10:00:00Z")
    passed = record_inspection_result(second["id"], minor=1, major=4, critical=0)

    assert passed["inspection_score"] == 70, (
        "100 less one minor at 2 points and four majors at 7 points is exactly 70, "
        f"got {passed['inspection_score']}"
    )
    assert passed["status"] == "PASSED", (
        f"a score of exactly 70 passes because the comparison is inclusive, got {passed['status']}"
    )

    final = fetch_permit(permit["id"])
    assert_permit(final)
    assert final["drill_compliance_ratio"] == pytest.approx(0.00, abs=0.01), (
        "no drill has ever been logged, so the ratio is 0.00"
    )
    assert final["status"] == "PROBATION", (
        "a passing inspection with a lapsed drill ratio lands on PROBATION rather "
        f"than ACTIVE, got {final['status']}"
    )
    assert final["last_enforcement_reason"] == "DRILL_LAPSE"
    assert final["probation_count"] == 1
    assert fetch_practice(practice["id"])["sedation_privilege_state"] == "RESTRICTED"


def test_calc_dental_only_patient_route_prices_at_creation(api):
    """PRD: "When both `medical_plan_active` and `dental_plan_active` are true the
    `route` is `SPLIT`; when only `medical_plan_active` is true it is
    `MEDICAL_PRIMARY`; when only `dental_plan_active` is true it is
    `DENTAL_PRIMARY`; and when neither is true it is `SELF_PAY`."
    PRD: "Opening a determination stamps `status` `DRAFT` and `submission_count` 0,
    sets `dental_annual_remaining_snapshot_cents` from the patient's current
    `dental_annual_remaining_cents`, and immediately computes `route`,
    `primary_payer`, and the full allocation, so the specialist can see the split
    before committing to it."
    PRD: "On the pure `DENTAL_PRIMARY` route `medical_allowed_cents` stays 0."
    PRD: "`patient_responsibility_cents` is then the case's `total_charge_cents`
    less `medical_allowed_cents` less `dental_allowed_cents`."
    PRD: "An `APPROVED` outcome is terminal and settles the annual maximum: the
    patient's `dental_annual_remaining_cents` is reduced by `dental_allowed_cents`,
    never below 0, and the patient's `version` increments."

    Design: Corner/calculations/dental_only_patient_route_prices_at_creation
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Route OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(
        practice["id"], full_name="Pat Dental", dental_plan_active=True
    )
    case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-20T13:00:00Z", "2026-09-20T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="IMPLANT",
        total_charge_cents=90000,
    )

    payload = create_determination_payload(
        case["id"], [service_line("D6010", 90000, "DENTAL")]
    )
    data = validate_success(api.create_determination(payload, BENEFITS), 201)

    assert_determination(data)
    assert data["route"] == "DENTAL_PRIMARY", (
        f"only the dental plan is active, so the route is DENTAL_PRIMARY, got {data['route']}"
    )
    assert data["primary_payer"] == "DENTAL"
    assert data["status"] == "DRAFT"
    assert data["submission_count"] == 0
    assert data["dental_annual_remaining_snapshot_cents"] == 150000, (
        "the snapshot pins the patient's default annual remainder at creation, got "
        f"{data['dental_annual_remaining_snapshot_cents']}"
    )
    assert data["dental_allowed_cents"] == 45000, (
        f"fifty percent of the 90000 line is 45000, got {data['dental_allowed_cents']}"
    )
    assert data["medical_allowed_cents"] == 0, (
        f"no medical plan is active, got {data['medical_allowed_cents']}"
    )
    assert data["patient_responsibility_cents"] == 45000
    assert_money_identity(data, 90000)

    fresh_patient = validate_success(api.get_patient(patient["id"], ADMIN))
    assert fresh_patient["dental_annual_remaining_cents"] == 150000, (
        "only an approved payer response draws down the annual maximum, got "
        f"{fresh_patient['dental_annual_remaining_cents']}"
    )


def test_calc_self_pay_route_allows_nothing_to_either_plan(api):
    """PRD: "When both `medical_plan_active` and `dental_plan_active` are true the
    `route` is `SPLIT`; when only `medical_plan_active` is true it is
    `MEDICAL_PRIMARY`; when only `dental_plan_active` is true it is
    `DENTAL_PRIMARY`; and when neither is true it is `SELF_PAY`."
    PRD: "On `MEDICAL_PRIMARY` the `primary_payer` is `MEDICAL`, on
    `DENTAL_PRIMARY` it is `DENTAL`, and on `SELF_PAY` it is null."
    PRD: "On the `SELF_PAY` route both `medical_allowed_cents` and
    `dental_allowed_cents` are 0 and the patient owes everything."

    A PATHOLOGY case would be medical-first, but the procedure category only
    breaks the tie on the split route, so an uninsured patient still self-pays.

    Design: Corner/calculations/self_pay_route_allows_nothing_to_either_plan
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="SelfPay OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Cash")
    case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-20T13:00:00Z", "2026-09-20T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="PATHOLOGY",
        total_charge_cents=80000,
    )

    payload = create_determination_payload(
        case["id"], [service_line("41899", 80000, "MEDICAL")]
    )
    data = validate_success(api.create_determination(payload, BENEFITS), 201)

    assert_determination(data)
    assert data["route"] == "SELF_PAY", (
        f"neither coverage flag is set, so the route is SELF_PAY, got {data['route']}"
    )
    assert data["primary_payer"] is None, (
        f"SELF_PAY is the only route whose primary_payer is null, got {data['primary_payer']}"
    )
    assert data["medical_allowed_cents"] == 0
    assert data["dental_allowed_cents"] == 0
    assert data["patient_responsibility_cents"] == 80000, (
        f"the patient owes the whole charge, got {data['patient_responsibility_cents']}"
    )
    assert_money_identity(data, 80000)


def test_calc_minor_patient_retention_runs_to_majority_plus_seven(api):
    """PRD: "First determine the patient's age in whole years from `date_of_birth`
    to `acquired_at`."
    PRD: "The acquisition floor is `acquired_at` plus seven years."
    PRD: "For a patient who was already 18 or older at acquisition,
    `retention_until` is that acquisition floor."
    PRD: "For a patient who was under 18 at acquisition, compute a second date —
    the patient's eighteenth birthday, being `date_of_birth` plus eighteen years,
    plus a further seven years — and `retention_until` is whichever of the two
    dates is later."
    PRD: "Retention is computed once at registration and never recomputed, which is
    why the logical clock is irrelevant to it: the obligation is anchored to
    acquisition, not to the moment of upload."

    Design: Corner/calculations/minor_patient_retention_runs_to_majority_plus_seven
    """
    # The logical clock boots at 2026-08-01T00:00:00Z (PRD 2.5) and is monotonic,
    # so the session clock must sit at or after that instant. Every assertion below
    # is anchored to `acquired_at`, which stays at or before the clock.
    set_clock("2026-08-05T10:00:00Z")
    practice = create_practice(name="Imaging OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    surgeon_headers = make_surgeon_headers(surgeon["id"])
    adult = create_patient(
        practice["id"], full_name="Adult Ann", date_of_birth="1980-03-15T00:00:00Z"
    )
    minor = create_patient(
        practice["id"], full_name="Minor Milo", date_of_birth="2016-03-15T00:00:00Z",
        asa_class=1, airway_class=1, weight_kg=35,
    )

    adult_study = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                adult["id"], modality="PANORAMIC",
                justification_code="THIRD_MOLAR_ASSESSMENT",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=40.0,
            ),
            surgeon_headers,
        ),
        201,
    )
    minor_study = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                minor["id"], modality="PANORAMIC",
                justification_code="THIRD_MOLAR_ASSESSMENT",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=40.0,
            ),
            surgeon_headers,
        ),
        201,
    )

    assert_imaging_study(adult_study)
    assert_imaging_study(minor_study)
    assert parse_iso(adult_study["retention_until"]) == parse_iso("2033-06-01T09:00:00Z"), (
        "an adult study is kept for the seven-year acquisition floor, got "
        f"{adult_study['retention_until']}"
    )
    assert parse_iso(minor_study["retention_until"]) == parse_iso("2041-03-15T00:00:00Z"), (
        "the ten-year-old's majority date plus seven years is later than the "
        f"acquisition floor and wins, got {minor_study['retention_until']}"
    )
    assert adult_study["dose_flag"] == "WITHIN_PROTOCOL"
    assert minor_study["dose_flag"] == "WITHIN_PROTOCOL"
    assert "version" not in adult_study and "version" not in minor_study, (
        "an imaging study is write-once and exposes no version"
    )

    set_clock("2030-01-01T00:00:00Z")
    reread_adult = validate_success(api.get_imaging_study(adult_study["id"], ADMIN))
    reread_minor = validate_success(api.get_imaging_study(minor_study["id"], ADMIN))
    assert parse_iso(reread_adult["retention_until"]) == parse_iso("2033-06-01T09:00:00Z"), (
        "retention is anchored to acquisition and never recomputed"
    )
    assert parse_iso(reread_minor["retention_until"]) == parse_iso("2041-03-15T00:00:00Z"), (
        "retention is anchored to acquisition and never recomputed"
    )


def test_calc_dose_exactly_at_the_reference_level_stays_within_protocol(api):
    """PRD: "Dose is judged against a per-modality reference level: 100.0 for
    `PANORAMIC`, 60.0 for `CEPHALOMETRIC`, 250.0 for `CBCT_SMALL_FOV`, and 900.0
    for `CBCT_LARGE_FOV`, all in the same units as `dose_mgy_cm2`."
    PRD: "`dose_flag` is `ABOVE_REFERENCE_LEVEL` when the recorded dose is strictly
    greater than its modality's reference level, and `WITHIN_PROTOCOL` otherwise;
    because the comparison is strict, a dose exactly at the reference level is
    `WITHIN_PROTOCOL`."
    PRD: "Exceeding the reference level does not block the study — the record
    exists precisely so that protocol drift is visible."

    Design: Corner/calculations/dose_exactly_at_the_reference_level_stays_within_protocol
    """
    # The logical clock boots at 2026-08-01T00:00:00Z (PRD 2.5) and is monotonic,
    # so the session clock must sit at or after that instant. Every assertion below
    # is anchored to `acquired_at`, which stays at or before the clock.
    set_clock("2026-08-05T10:00:00Z")
    practice = create_practice(name="Dose OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    surgeon_headers = make_surgeon_headers(surgeon["id"])
    patient = create_patient(practice["id"], full_name="Pat Dose")

    at_level = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"], modality="CBCT_SMALL_FOV",
                justification_code="IMPLANT_PLANNING",
                acquired_at="2026-06-01T09:00:00Z", dose_mgy_cm2=250.0,
            ),
            surgeon_headers,
        ),
        201,
    )
    above_level = validate_success(
        api.create_imaging_study(
            create_imaging_study_payload(
                patient["id"], modality="CBCT_SMALL_FOV",
                justification_code="IMPLANT_PLANNING",
                acquired_at="2026-06-02T09:00:00Z", dose_mgy_cm2=250.1,
            ),
            surgeon_headers,
        ),
        201,
    )

    assert at_level["dose_flag"] == "WITHIN_PROTOCOL", (
        f"250.0 is not strictly greater than 250.0, got {at_level['dose_flag']}"
    )
    assert above_level["dose_flag"] == "ABOVE_REFERENCE_LEVEL", (
        f"250.1 exceeds the 250.0 reference level, got {above_level['dose_flag']}"
    )

    flagged, meta = validate_paginated(
        api.list_imaging_studies(
            ADMIN,
            params={"patient_id": patient["id"], "dose_flag": "ABOVE_REFERENCE_LEVEL"},
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one of the two studies is above the reference level, got {meta['total_count']}"
    )
    assert [row["id"] for row in flagged] == [above_level["id"]]


def test_calc_drill_ratio_ignores_deficient_duplicate_stale_and_foreign_drills(api):
    """PRD: "A `MODERATE_SEDATION` permit requires those two plus `LARYNGOSPASM`
    and `CARDIAC_ARREST` — four scenarios."
    PRD: "A drill qualifies when it belongs to that practice, its
    `deficiency_noted` is false, its `conducted_at` falls strictly later than the
    instant exactly 365 days before the logical clock and at or before the logical
    clock itself, and its `drill_type` is a member of the required set."
    PRD: "Count the distinct drill types among the qualifying drills — a type
    rehearsed five times counts once, and a type outside the required set counts not
    at all — divide that count by the number of types in the required set, and round
    the quotient half-up to two decimal places."
    PRD: "The practice is drill-compliant when the ratio is at or above 0.75;
    because the comparison is inclusive, a ratio of exactly 0.75 passes."
    PRD: "Logging any drill recomputes the open permit's `drill_compliance_ratio`
    and increments that permit's `version`."

    Six drills are logged; a duplicate, a deficient rehearsal, one outside the
    365-day window and one of an unrequired type all drop out, leaving two of the
    four required types covered.

    Design: Corner/calculations/drill_ratio_ignores_deficient_duplicate_stale_and_foreign_drills
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = create_practice(name="Drill OMS", state_code="OH", recovery_bay_count=2)
    monitor = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Mo Monitor", monitoring_certified=True
    )
    nurse = create_staff(practice["id"], "RECOVERY_NURSE", "Rhea Nurse")
    participants = [monitor["id"], nurse["id"]]
    permit = apply_permit(practice["id"], "MODERATE_SEDATION", "2026-08-01T00:00:00Z")

    log_drill(practice["id"], "AIRWAY_OBSTRUCTION", "2026-06-01T09:00:00Z", participants)
    log_drill(practice["id"], "AIRWAY_OBSTRUCTION", "2026-07-01T09:00:00Z", participants)
    log_drill(
        practice["id"], "LARYNGOSPASM", "2026-06-15T09:00:00Z", participants,
        deficiency_noted=True,
    )
    log_drill(practice["id"], "CARDIAC_ARREST", "2025-08-01T09:00:00Z", participants)
    log_drill(
        practice["id"], "MALIGNANT_HYPERTHERMIA", "2026-08-01T09:00:00Z", participants
    )
    log_drill(
        practice["id"], "LOCAL_ANESTHETIC_TOXICITY", "2026-08-15T09:00:00Z", participants
    )

    _, drill_meta = validate_paginated(
        api.list_drills(ADMIN, params={"practice_id": practice["id"]})
    )
    assert drill_meta["total_count"] == 6, (
        f"all six rehearsals are stored regardless of coverage, got {drill_meta['total_count']}"
    )

    summary = validate_success(api.get_compliance_summary(practice["id"], ADMIN))
    assert len(summary["required_drill_types"]) == 4, (
        f"MODERATE_SEDATION requires four scenarios, got {summary['required_drill_types']}"
    )
    assert set(summary["covered_drill_types"]) == {
        "AIRWAY_OBSTRUCTION", "LOCAL_ANESTHETIC_TOXICITY"
    }, (
        "only the clean, in-window, required types count as covered, got "
        f"{summary['covered_drill_types']}"
    )
    assert summary["drill_compliance_ratio"] == pytest.approx(0.50, abs=0.01), (
        f"two of four distinct required types is 0.50, got {summary['drill_compliance_ratio']}"
    )
    assert summary["drill_compliant"] is False, (
        "0.50 sits below the 0.75 floor, so the practice is not drill-compliant"
    )

    fresh_permit = fetch_permit(permit["id"])
    assert_permit(fresh_permit)
    assert fresh_permit["drill_compliance_ratio"] == pytest.approx(0.50, abs=0.01), (
        f"logging a drill recomputes the permit's ratio, got {fresh_permit['drill_compliance_ratio']}"
    )


def test_calc_block_committed_minutes_count_only_attached_cases(api):
    """PRD: "Thereafter `committed_minutes` is always the sum of `duration_minutes`
    over the surgical cases attached to this block whose `scheduling_status` is one
    of the four committing states — `BLOCK_HELD`, `CONFIRMED`, `IN_RECOVERY`, or
    `COMPLETED`."
    PRD: "Cases in `DRAFT` or `CANCELLED` contribute nothing, which is why
    cancelling a case returns its minutes to `open_minutes` rather than to
    `released_minutes`."
    PRD: "`utilization_pct` is one hundred multiplied by `committed_minutes`,
    divided by `block_duration_minutes`, rounded half-up to two decimal places."
    PRD: "A successful hold persists `block_id` on the case, advances
    `scheduling_status` from `DRAFT` to `BLOCK_HELD`, adds the case's
    `duration_minutes` to the block's `committed_minutes`, recomputes the block's
    `open_minutes` and `utilization_pct`, and increments the block's `version`"

    Two held cases of 60 and 30 minutes commit 90 of the block's 240 minutes; a
    third 120-minute case that never held the block contributes nothing.

    Design: Corner/calculations/block_committed_minutes_count_only_attached_cases
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = create_practice(name="Utilization OMS", state_code="OH", recovery_bay_count=2)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    patient = create_patient(practice["id"], full_name="Pat Util")
    block = create_block(
        practice["id"], surgeon["id"], "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z",
        room_code="OR-1", release_deadline_hours=48,
    )

    def _local_case(start, end, charge):
        return create_case(
            practice["id"], patient["id"], surgeon["id"], start, end,
            planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
            total_charge_cents=charge,
        )

    case_a = _local_case("2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z", 50000)
    case_b = _local_case("2026-09-14T14:30:00Z", "2026-09-14T15:00:00Z", 30000)
    case_c = _local_case("2026-09-14T15:30:00Z", "2026-09-14T17:30:00Z", 70000)

    assert block["block_duration_minutes"] == 240
    assert block["committed_minutes"] == 0
    assert block["open_minutes"] == 240
    assert block["utilization_pct"] == pytest.approx(0.00, abs=0.01)
    baseline_version = block["version"]

    hold_case_on_block(case_a["id"], block["id"])
    after_a = fetch_block(block["id"])
    assert after_a["committed_minutes"] == 60
    assert after_a["open_minutes"] == 180
    assert after_a["utilization_pct"] == pytest.approx(25.00, abs=0.01), (
        f"one hundred times 60 over 240 is 25.00, got {after_a['utilization_pct']}"
    )
    assert after_a["version"] == baseline_version + 1, (
        "a hold increments the block's version"
    )
    assert_block_ledger_conserved(after_a)

    hold_case_on_block(case_b["id"], block["id"])
    after_b = fetch_block(block["id"])
    assert after_b["committed_minutes"] == 90, (
        f"60 and 30 minutes of held cases sum to 90, got {after_b['committed_minutes']}"
    )
    assert after_b["open_minutes"] == 150
    assert after_b["utilization_pct"] == pytest.approx(37.50, abs=0.01), (
        f"one hundred times 90 over 240 rounds half-up to 37.50, got {after_b['utilization_pct']}"
    )
    assert after_b["released_minutes"] == 0
    assert_block_ledger_conserved(after_b)

    untouched = fetch_case(case_c["id"])
    assert_surgical_case(untouched)
    assert untouched["scheduling_status"] == "DRAFT"
    assert untouched["block_id"] is None, (
        "a case that never held the block carries no block_id"
    )
    assert untouched["duration_minutes"] == 120
    assert after_b["committed_minutes"] == 90, (
        "the draft case's 120 minutes are absent from the aggregate"
    )


def test_calc_local_only_case_confirms_with_no_monitor_and_no_permit(api):
    """PRD: "For a `LOCAL_ONLY` case nothing is required: no monitor, no
    certification, no surgeon ACLS card, and no recovery nurse."
    PRD: "A `LOCAL_ONLY` case is admitted under every privilege state, including
    `UNPERMITTED` and `SUSPENDED`, because no sedation is being delivered."
    PRD: "First fasting: for any case whose `planned_anesthesia_level` is above
    `LOCAL_ONLY`, `npo_solids_minutes` must be at least 480 — eight hours without
    solids — and `npo_clears_minutes` at least 120, two hours without clear liquids;
    a shortfall in either is `ERR_FASTING_REQUIREMENT_UNMET` (HTTP 409)."
    PRD: "Then escort: again for any level above `LOCAL_ONLY`, `escort_confirmed`
    must be true and `escort_name` must be non-empty, since a sedated patient may
    not be discharged without a responsible adult; otherwise the answer is
    `ERR_ESCORT_REQUIRED` (HTTP 409)."
    PRD: "`recovery_minutes_required` follows the anesthesia level: zero minutes for
    `LOCAL_ONLY`, 20 for `MINIMAL_SEDATION`, 45 for `MODERATE_SEDATION`, and 90 for
    `DEEP_SEDATION_GENERAL`; this figure is what makes a case occupy a recovery bay."

    The office holds no permit at all, has no recovery nurse, assigns no monitor and
    its surgeon has never been ACLS certified, yet the local-anesthesia case clears
    and confirms — and the clinical gates skip a short fast and a missing escort.

    Design: Corner/calculations/local_only_case_confirms_with_no_monitor_and_no_permit
    """
    set_clock("2026-09-14T07:00:00Z")
    practice = create_practice(name="Local OMS", state_code="OH", recovery_bay_count=1)
    surgeon = create_staff(practice["id"], "SURGEON", "Dr Alma Reyes")
    author = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Nia Author", monitoring_certified=False
    )
    verifier = create_staff(
        practice["id"], "ANESTHESIA_MONITOR", "Val Verifier", monitoring_certified=False
    )
    patient = create_patient(practice["id"], full_name="Pat Local")
    block = create_block(
        practice["id"], surgeon["id"], "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z",
        room_code="OR-1", release_deadline_hours=48,
    )
    case = create_case(
        practice["id"], patient["id"], surgeon["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z",
        planned_anesthesia_level="LOCAL_ONLY", procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    assert case["monitor_staff_id"] is None, (
        "a LOCAL_ONLY case may be drafted with no dedicated monitor"
    )
    assert case["recovery_minutes_required"] == 0

    evaluation = validate_success(
        api.create_evaluation(
            case["id"],
            create_evaluation_payload(
                author["id"], case["version"],
                asa_class_recorded=2, airway_class_recorded=2, comorbidity_count=0,
            ),
            make_anesthesia_coordinator_headers(author["id"]),
        ),
        201,
    )
    validate_success(
        api.sign_evaluation(
            evaluation["id"], {}, make_anesthesia_coordinator_headers(author["id"])
        )
    )
    verified = validate_success(
        api.verify_evaluation(
            evaluation["id"],
            day_of_verification_payload(
                "CLEAR", "2026-09-14T06:00:00Z", "2026-09-14T06:30:00Z",
                escort_confirmed=False,
            ),
            make_anesthesia_coordinator_headers(verifier["id"]),
        )
    )

    assert verified["status"] == "VERIFIED", (
        "the clinical gates are scoped to levels above LOCAL_ONLY, so a short fast "
        f"and a missing escort do not block this verification, got {verified['status']}"
    )
    assert verified["npo_solids_minutes"] == 60, (
        f"the last solid meal was one hour before verification, got {verified['npo_solids_minutes']}"
    )
    assert verified["npo_clears_minutes"] == 30
    assert verified["escort_confirmed"] is False
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"

    hold_case_on_block(case["id"], block["id"])
    held_block = fetch_block(block["id"])
    confirmed = validate_success(
        api.confirm_case(
            case["id"], {"expected_block_version": held_block["version"]}, SCHEDULER
        )
    )

    assert_surgical_case(confirmed)
    assert confirmed["scheduling_status"] == "CONFIRMED", (
        "a LOCAL_ONLY case confirms with no monitor, no ACLS card, no recovery nurse "
        f"and no permit on file, got {confirmed['scheduling_status']}"
    )
    assert confirmed["monitor_staff_id"] is None
    assert confirmed["recovery_minutes_required"] == 0, (
        "a LOCAL_ONLY case occupies none of the single recovery bay"
    )
    assert fetch_practice(practice["id"])["sedation_privilege_state"] == "UNPERMITTED", (
        "no permit was ever applied for, so the practice stays UNPERMITTED"
    )
