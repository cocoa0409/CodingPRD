"""Action and computed-read endpoints of the OMS anesthesia-permitting API.

Roster CRUD, the referral acknowledgement link, the regulator-notification
self-loop, the practice compliance projection, probation remediation, and the
periodic compliance sweep.
"""
from test_helpers import (
    ADMIN,
    BENEFITS,
    INVENTORY,
    SCHEDULER,
    ApiErrorId,
    api_client as api,
    assert_block_ledger_conserved,
    assert_block_time,
    assert_common_fields,
    assert_staff_member,
    make_quality_reviewer_headers,
    make_surgeon_headers,
    parse_iso,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_action_staff_member_create_read_and_filtered_list():
    """Roster rows are created, read back and filtered by practice and role.

    PRD: "Each `StaffMember` is created against a `practice_id` with a
    `full_name` of 1 to 120 characters and a `role_type` drawn from `SURGEON`,
    `ANESTHESIA_MONITOR`, `RECOVERY_NURSE`, and `INVENTORY_TECH`."

    PRD: "Two credential fields ride along: `monitoring_certified`, a boolean
    defaulting to false that records whether the member holds the
    anesthesia-assistant monitoring certificate, and `acls_expires_on`, the ISO
    8601 UTC expiry instant of the member's ACLS or PALS card, where a null
    means the member has never been certified at all."

    PRD: "Staff may be listed with `practice_id` and `role_type` filters, which
    is how an operator answers the question the staffing matrix asks about
    recovery nurses."

    Design: Corner/endpoints/staff_member_create_read_and_filtered_list
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Roster OMS", "state_code": "OH", "recovery_bay_count": 2}, ADMIN
        ),
        201,
    )
    prac_id = practice["id"]

    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
                "acls_expires_on": "2027-06-30T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    monitor = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Mo Monitor",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    nurse = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Ren Nurse",
                "role_type": "RECOVERY_NURSE",
            },
            ADMIN,
        ),
        201,
    )

    for row in (surgeon, monitor, nurse):
        assert_staff_member(row)
        assert_common_fields(row)
        assert row["version"] == 1, "a freshly created staff member starts at version 1"
        assert row["practice_id"] == prac_id

    assert parse_iso(surgeon["acls_expires_on"]) == parse_iso("2027-06-30T00:00:00Z")
    assert surgeon["monitoring_certified"] is False, (
        "monitoring_certified defaults to false when it is not supplied"
    )
    assert nurse["monitoring_certified"] is False
    assert nurse["acls_expires_on"] is None, (
        "a null acls_expires_on means the member has never been certified"
    )

    read_back = validate_success(api.get_staff_member(monitor["id"], SCHEDULER))
    assert read_back["full_name"] == "Mo Monitor"
    assert read_back["role_type"] == "ANESTHESIA_MONITOR"
    assert read_back["monitoring_certified"] is True

    monitors, monitor_meta = validate_paginated(
        api.list_staff_members(
            SCHEDULER, {"practice_id": prac_id, "role_type": "ANESTHESIA_MONITOR"}
        )
    )
    assert monitor_meta["total_count"] == 1
    assert [row["id"] for row in monitors] == [monitor["id"]]

    everyone, all_meta = validate_paginated(
        api.list_staff_members(SCHEDULER, {"practice_id": prac_id})
    )
    assert all_meta["total_count"] == 3
    assert {row["id"] for row in everyone} == {
        surgeon["id"], monitor["id"], nurse["id"]
    }


def test_action_regulator_notification_flips_the_flag_without_moving_the_status():
    """The board notification is a self-loop: the flag flips, the status stays.

    PRD: "Recording it sets `regulator_notified` to true and increments the
    event's `version`, and it deliberately does **not** advance `status`."

    PRD: "`reporting_deadline_at` is `occurred_at` plus 24 hours for a
    `SENTINEL` event, plus 72 hours for a `SEVERE` one, plus 7 days for a
    `MODERATE` one, and plus 30 days for a `MINOR` one."

    PRD: "`open_adverse_event_count` is the number of adverse events filed
    against cases of this practice whose own `status` is anything other than
    `CLOSED`."

    Design: Corner/endpoints/regulator_notification_flips_the_flag_without_moving_the_status
    """
    set_clock("2026-09-14T15:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Notify OMS", "state_code": "OH", "recovery_bay_count": 2}, ADMIN
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Notify",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "TRAUMA",
                "planned_start": "2026-09-14T13:00:00Z",
                "planned_end": "2026-09-14T14:00:00Z",
                "total_charge_cents": 50000,
            },
            SCHEDULER,
        ),
        201,
    )
    event = validate_success(
        api.create_adverse_event(
            {
                "case_id": case["id"],
                "event_type": "AIRWAY_OBSTRUCTION",
                "severity": "SEVERE",
                "occurred_at": "2026-09-14T14:30:00Z",
                "narrative": "Transient desaturation requiring airway support.",
            },
            make_surgeon_headers(surgeon["id"]),
        ),
        201,
    )
    event_version = event["version"]

    assert event["regulator_notified"] is False
    assert event["status"] == "REPORTED"
    assert parse_iso(event["reporting_deadline_at"]) == parse_iso(
        "2026-09-17T14:30:00Z"
    ), "a SEVERE event is due 72 hours after it occurred"
    assert event["late_report"] is False

    set_clock("2026-09-14T16:00:00Z")
    notified = validate_success(
        api.record_regulator_notification(
            event["id"],
            {
                "notified_at": "2026-09-14T16:00:00Z",
                "notification_reference": "OH-DENT-2026-0914-01",
            },
            make_quality_reviewer_headers(surgeon["id"]),
        )
    )
    assert notified["regulator_notified"] is True
    assert notified["status"] == "REPORTED", (
        "the notification track never advances the review status"
    )
    assert notified["version"] > event_version
    assert notified["reviewer_staff_id"] is None, (
        "the notification track needs no reviewer"
    )

    practice_after = validate_success(api.get_practice(prac_id, ADMIN))
    assert practice_after["open_adverse_event_count"] == 1, (
        "notification is not closure, so the event is still open"
    )


def test_action_referral_acknowledgement_links_the_referring_provider():
    """Acknowledgement moves PENDING to ACKNOWLEDGED and refuses NOT_REQUIRED.

    PRD: "A `SchedulingCoordinator` records the referring dentist's or
    orthodontist's sign-off on the coordinated plan by supplying
    `acknowledged_by_npi`, which advances `referral_coordination_status` from
    `PENDING` to `ACKNOWLEDGED`."

    PRD: "Attempting the same acknowledgement on a case whose
    `referral_coordination_status` is `NOT_REQUIRED` is rejected with
    `ERR_INVALID_STATE_TRANSITION` (HTTP 409), as is a repeat acknowledgement of
    a case already `ACKNOWLEDGED`."

    PRD: "`referral_coordination_status` starts at `PENDING` when the
    `procedure_category` is `THIRD_MOLAR` or `ORTHOGNATHIC` **and** a
    `referring_provider_npi` was supplied, and at `NOT_REQUIRED` in every other
    combination — a `TRAUMA` case with a referring NPI, or a `THIRD_MOLAR` case
    without one, are both `NOT_REQUIRED`."

    Design: Corner/endpoints/referral_acknowledgement_links_the_referring_provider
    """
    set_clock("2026-09-11T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Referral OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Referral",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    linked_case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "ORTHOGNATHIC",
                "planned_start": "2026-09-21T13:00:00Z",
                "planned_end": "2026-09-21T14:30:00Z",
                "total_charge_cents": 120000,
                "referring_provider_npi": "1447382910",
            },
            SCHEDULER,
        ),
        201,
    )
    solo_case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-22T13:00:00Z",
                "planned_end": "2026-09-22T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    assert linked_case["referral_coordination_status"] == "PENDING"
    assert solo_case["referral_coordination_status"] == "NOT_REQUIRED"

    acknowledged = validate_success(
        api.record_referral_coordination(
            linked_case["id"], {"acknowledged_by_npi": "1447382910"}, SCHEDULER
        )
    )
    assert acknowledged["referral_coordination_status"] == "ACKNOWLEDGED"
    assert acknowledged["version"] > linked_case["version"]

    validate_error(
        api.record_referral_coordination(
            solo_case["id"], {"acknowledged_by_npi": "1447382910"}, SCHEDULER
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    cases, _meta = validate_paginated(
        api.list_surgical_cases(SCHEDULER, {"practice_id": prac_id})
    )
    by_id = {row["id"]: row for row in cases}
    assert by_id[linked_case["id"]]["scheduling_status"] == "DRAFT"
    assert by_id[solo_case["id"]]["scheduling_status"] == "DRAFT"
    assert by_id[linked_case["id"]]["referral_coordination_status"] == "ACKNOWLEDGED"
    assert by_id[solo_case["id"]]["referral_coordination_status"] == "NOT_REQUIRED"


def test_action_compliance_summary_derives_permit_drill_and_consignment_figures():
    """The summary projects permit, drill and consignment aggregates at once.

    PRD: "It answers with the practice's own `practice_id` and current
    `sedation_privilege_state`; the `open_permit_id`, `permit_status`, and
    `permit_level` of the practice's open permit; the `required_drill_types`
    that permit level demands alongside the `covered_drill_types` actually
    satisfied inside the trailing window; the `drill_compliance_ratio` and the
    boolean `drill_compliant` derived from it; the `open_adverse_event_count`;
    and both `consignment_committed_cents` and `consignment_credit_limit_cents`
    so the remaining consignment headroom is visible at a glance."

    PRD: "Reading this view recomputes the drill ratio against the current
    logical clock but persists nothing — it is a pure projection, and a practice
    whose drills have silently aged out of the window will show a lapsed ratio
    here before any enforcement action has been taken against it."

    PRD: "`consignment_credit_cents` is twenty percent of `line_subtotal_cents`,
    rounded half-up to whole cents, when the lot's `is_consignment` is true, and
    0 when it is false."

    Design: Corner/endpoints/compliance_summary_derives_permit_drill_and_consignment_figures
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Summary OMS", "state_code": "OH", "recovery_bay_count": 2}, ADMIN
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    monitor = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Mo Monitor",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    permit = validate_success(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "MINIMAL_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    for drill_type, conducted_at in (
        ("AIRWAY_OBSTRUCTION", "2026-08-20T09:00:00Z"),
        ("LOCAL_ANESTHETIC_TOXICITY", "2026-08-21T09:00:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": [monitor["id"], surgeon["id"]],
                },
                ADMIN,
            ),
            201,
        )
    inspection = validate_success(
        api.create_inspection(
            {"permit_id": permit["id"], "scheduled_for": "2026-09-02T09:00:00Z"}, ADMIN
        ),
        201,
    )
    set_clock("2026-09-02T10:00:00Z")
    validate_success(
        api.record_inspection_result(
            inspection["id"],
            {
                "minor_deficiency_count": 0,
                "major_deficiency_count": 0,
                "critical_deficiency_count": 0,
            },
            ADMIN,
        )
    )
    patient = validate_success(
        api.create_patient(
            {
                "practice_id": prac_id,
                "full_name": "Pat Summary",
                "date_of_birth": "1980-03-15T00:00:00Z",
                "asa_class": 2,
                "airway_class": 2,
                "weight_kg": 80,
            },
            SCHEDULER,
        ),
        201,
    )
    case = validate_success(
        api.create_surgical_case(
            {
                "practice_id": prac_id,
                "patient_id": patient["id"],
                "primary_surgeon_id": surgeon["id"],
                "planned_anesthesia_level": "LOCAL_ONLY",
                "procedure_category": "IMPLANT",
                "planned_start": "2026-09-20T13:00:00Z",
                "planned_end": "2026-09-20T14:00:00Z",
                "total_charge_cents": 90000,
            },
            SCHEDULER,
        ),
        201,
    )
    lot = validate_success(
        api.create_implant_lot(
            {
                "practice_id": prac_id,
                "manufacturer_code": "NOBEL",
                "catalog_reference": "NB-4310",
                "diameter_mm": 4.3,
                "length_mm": 10.0,
                "unit_cost_cents": 30000,
                "quantity_on_hand": 5,
                "expiry_date": "2027-01-31T00:00:00Z",
                "is_consignment": True,
            },
            INVENTORY,
        ),
        201,
    )
    reservation = validate_success(
        api.create_reservation(
            {
                "case_id": case["id"],
                "lot_id": lot["id"],
                "quantity": 2,
                "expected_lot_version": lot["version"],
            },
            INVENTORY,
        ),
        201,
    )

    summary = validate_success(api.get_compliance_summary(prac_id, BENEFITS))
    assert summary["practice_id"] == prac_id
    assert summary["sedation_privilege_state"] == "PERMITTED"
    assert summary["open_permit_id"] == permit["id"]
    assert summary["permit_status"] == "ACTIVE"
    assert summary["permit_level"] == "MINIMAL_SEDATION"
    assert set(summary["required_drill_types"]) == {
        "AIRWAY_OBSTRUCTION",
        "LOCAL_ANESTHETIC_TOXICITY",
    }
    assert set(summary["covered_drill_types"]) == set(summary["required_drill_types"])
    assert float(summary["drill_compliance_ratio"]) == 1.00
    assert summary["drill_compliant"] is True
    assert summary["consignment_committed_cents"] == 48000, (
        "60000 subtotal less the 12000 consignment credit"
    )
    assert summary["consignment_credit_limit_cents"] == 500000
    assert summary["open_adverse_event_count"] == 0

    reservation_read = validate_success(api.get_reservation(reservation["id"], INVENTORY))
    assert reservation_read["line_subtotal_cents"] == 60000
    assert reservation_read["consignment_credit_cents"] == 12000
    assert reservation_read["consignment_liability_cents"] == 48000
    practice_read = validate_success(api.get_practice(prac_id, ADMIN))
    assert practice_read["consignment_committed_cents"] == 48000

    permit_before = validate_success(api.get_permit(permit["id"], ADMIN))
    again = validate_success(api.get_compliance_summary(prac_id, BENEFITS))
    assert again == summary, "a pure projection returns identical figures on re-read"
    permit_after = validate_success(api.get_permit(permit["id"], ADMIN))
    practice_after = validate_success(api.get_practice(prac_id, ADMIN))
    assert permit_after["version"] == permit_before["version"], (
        "reading the projection persists nothing"
    )
    assert practice_after["version"] == practice_read["version"]


def test_action_remediation_is_allowed_only_from_probation_with_drills_restored():
    """One attestation call refused for lapse, accepted once drills are current,
    then refused again because the permit is no longer on probation.

    PRD: "A `PASSED` result on a permit in `INSPECTION_PENDING` whose ratio is
    below 0.75 instead lands on `PROBATION`: `issued_at` and `expires_at` are
    stamped exactly as on the `ACTIVE` branch — the permit really was issued —
    but `last_enforcement_reason` becomes `DRILL_LAPSE`, `probation_count`
    increases by 1, `remediation_deadline_at` is set to the logical clock plus 30
    days, `sedation_privilege_state` becomes `RESTRICTED`, and the narrow cascade
    runs: every case of that practice whose `planned_anesthesia_level` is
    `DEEP_SEDATION_GENERAL` and whose `clearance_status` is `CLEARED` moves to
    `clearance_status` `DEFERRED`."

    PRD: "Third, the `drill_compliance_ratio`, recomputed at that instant, must
    be at or above 0.75; a still-lapsed practice is refused with
    `ERR_DRILL_COMPLIANCE_LAPSED` (HTTP 409)."

    PRD: "A successful attestation returns the permit to `ACTIVE`, clears both
    `remediation_deadline_at` and `last_enforcement_reason` to null, restores
    `sedation_privilege_state` from `RESTRICTED` to `PERMITTED` — which reopens
    `DEEP_SEDATION_GENERAL` scheduling — and increments the practice's
    `version`."

    PRD: "First, the permit's `status` must actually be `PROBATION`; anything
    else is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/remediation_is_allowed_only_from_probation_with_drills_restored
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Remediate OMS", "state_code": "OH", "recovery_bay_count": 2},
            ADMIN,
        ),
        201,
    )
    prac_id = practice["id"]
    monitor = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Mo Monitor",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    nurse = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Rhea Nurse",
                "role_type": "RECOVERY_NURSE",
            },
            ADMIN,
        ),
        201,
    )
    permit = validate_success(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "MODERATE_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    participants = [monitor["id"], nurse["id"]]
    for drill_type, conducted_at in (
        ("AIRWAY_OBSTRUCTION", "2026-08-20T09:00:00Z"),
        ("LARYNGOSPASM", "2026-08-21T09:00:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": participants,
                },
                ADMIN,
            ),
            201,
        )
    inspection = validate_success(
        api.create_inspection(
            {"permit_id": permit["id"], "scheduled_for": "2026-09-02T09:00:00Z"}, ADMIN
        ),
        201,
    )
    set_clock("2026-09-02T10:00:00Z")
    result = validate_success(
        api.record_inspection_result(
            inspection["id"],
            {
                "minor_deficiency_count": 0,
                "major_deficiency_count": 0,
                "critical_deficiency_count": 0,
            },
            ADMIN,
        )
    )
    assert result["inspection_score"] == 100
    assert result["status"] == "PASSED"

    on_probation = validate_success(api.get_permit(permit["id"], ADMIN))
    assert on_probation["status"] == "PROBATION"
    assert on_probation["last_enforcement_reason"] == "DRILL_LAPSE"
    assert on_probation["probation_count"] == 1
    assert parse_iso(on_probation["remediation_deadline_at"]) == parse_iso(
        "2026-10-02T10:00:00Z"
    ), "the remediation window is the logical clock plus 30 days"
    assert float(on_probation["drill_compliance_ratio"]) == 0.50
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["sedation_privilege_state"]
        == "RESTRICTED"
    )

    validate_error(
        api.remediate_permit(
            permit["id"], {"attestation_note": "Deficiencies corrected."}, ADMIN
        ),
        ApiErrorId.ERR_DRILL_COMPLIANCE_LAPSED.value,
    )

    set_clock("2026-09-03T10:00:00Z")
    for drill_type, conducted_at in (
        ("LOCAL_ANESTHETIC_TOXICITY", "2026-09-03T08:00:00Z"),
        ("CARDIAC_ARREST", "2026-09-03T09:00:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": participants,
                },
                ADMIN,
            ),
            201,
        )
    restored = validate_success(api.get_permit(permit["id"], ADMIN))
    assert float(restored["drill_compliance_ratio"]) == 1.00
    assert restored["status"] == "PROBATION", (
        "logging drills fixes the ratio but does not itself reinstate the permit"
    )

    reinstated = validate_success(
        api.remediate_permit(
            permit["id"], {"attestation_note": "All four drills now current."}, ADMIN
        )
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["remediation_deadline_at"] is None
    assert reinstated["last_enforcement_reason"] is None
    assert reinstated["probation_count"] == 1, (
        "probation_count is permanent history and is never decremented"
    )
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["sedation_privilege_state"]
        == "PERMITTED"
    )

    validate_error(
        api.remediate_permit(
            permit["id"], {"attestation_note": "Filed twice by mistake."}, ADMIN
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )


def test_action_compliance_sweep_expires_a_permit_and_releases_an_idle_block():
    """One sweep expires the elapsed permit and gives back the idle block.

    PRD: "In the expiry pass, any permit — whether `ACTIVE` or on `PROBATION` —
    whose `expires_at` is at or before the logical clock moves to the terminal
    `EXPIRED` with `last_enforcement_reason` `PERMIT_EXPIRY` and the practice's
    `sedation_privilege_state` recomputed to `UNPERMITTED`."

    PRD: "Permits are handled in two passes, and the order between them is
    significant: every permit is tested for expiry **first**, and only permits
    still `ACTIVE` after that pass are re-checked for drill compliance, so an
    expired permit is never also counted as newly on probation."

    PRD: "When `committed_minutes` is zero the block moves to `RELEASED`, with
    `released_minutes` set to the full `block_duration_minutes` and
    `open_minutes` set to 0."

    PRD: "The sweep answers with `swept_at` recording the logical clock it ran
    at, the counts `permits_expired` and `permits_suspended` alongside the
    corresponding `permits_expired_ids` and `permits_suspended_ids` arrays, the
    counts `blocks_released` and `blocks_partially_released`, and finally
    `cases_cancelled` and `reservations_released` summarising the collateral
    effects of the cascades."

    Design: Corner/endpoints/compliance_sweep_expires_a_permit_and_releases_an_idle_block
    """
    set_clock("2026-09-01T10:00:00Z")
    practice = validate_success(
        api.create_practice(
            {"name": "Sweep OMS", "state_code": "OH", "recovery_bay_count": 2}, ADMIN
        ),
        201,
    )
    prac_id = practice["id"]
    surgeon = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Dr Alma Reyes",
                "role_type": "SURGEON",
            },
            ADMIN,
        ),
        201,
    )
    monitor = validate_success(
        api.create_staff_member(
            {
                "practice_id": prac_id,
                "full_name": "Mo Monitor",
                "role_type": "ANESTHESIA_MONITOR",
                "monitoring_certified": True,
            },
            ADMIN,
        ),
        201,
    )
    permit = validate_success(
        api.create_permit(
            {
                "practice_id": prac_id,
                "permit_level": "MINIMAL_SEDATION",
                "applied_on": "2026-08-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    for drill_type, conducted_at in (
        ("AIRWAY_OBSTRUCTION", "2026-08-20T09:00:00Z"),
        ("LOCAL_ANESTHETIC_TOXICITY", "2026-08-21T09:00:00Z"),
    ):
        validate_success(
            api.create_drill(
                {
                    "practice_id": prac_id,
                    "drill_type": drill_type,
                    "conducted_at": conducted_at,
                    "participant_staff_ids": [monitor["id"], surgeon["id"]],
                },
                ADMIN,
            ),
            201,
        )
    inspection = validate_success(
        api.create_inspection(
            {"permit_id": permit["id"], "scheduled_for": "2026-09-02T09:00:00Z"}, ADMIN
        ),
        201,
    )
    set_clock("2026-09-02T10:00:00Z")
    validate_success(
        api.record_inspection_result(
            inspection["id"],
            {
                "minor_deficiency_count": 0,
                "major_deficiency_count": 0,
                "critical_deficiency_count": 0,
            },
            ADMIN,
        )
    )
    block = validate_success(
        api.create_block_time(
            {
                "practice_id": prac_id,
                "surgeon_id": surgeon["id"],
                "room_code": "OR-1",
                "block_start": "2028-09-10T13:00:00Z",
                "block_end": "2028-09-10T17:00:00Z",
                "release_deadline_hours": 48,
            },
            SCHEDULER,
        ),
        201,
    )
    set_clock("2028-09-09T10:00:00Z")

    before_permit = validate_success(api.get_permit(permit["id"], ADMIN))
    assert before_permit["status"] == "ACTIVE"
    assert parse_iso(before_permit["expires_at"]) == parse_iso("2028-09-02T10:00:00Z")
    before_block = validate_success(api.get_block_time(block["id"], SCHEDULER))
    assert_block_time(before_block)
    assert before_block["status"] == "RESERVED"
    assert before_block["open_minutes"] == 240
    assert float(before_block["utilization_pct"]) == 0.00

    swept = validate_success(
        api.run_compliance_sweep({"practice_id": prac_id}, ADMIN)
    )
    assert parse_iso(swept["swept_at"]) == parse_iso("2028-09-09T10:00:00Z")
    assert swept["permits_expired"] == 1
    assert swept["permits_expired_ids"] == [permit["id"]]
    assert swept["permits_suspended"] == 0
    assert swept["blocks_released"] == 1
    assert swept["blocks_partially_released"] == 0
    assert swept["cases_cancelled"] == 0
    assert swept["reservations_released"] == 0

    after_permit = validate_success(api.get_permit(permit["id"], ADMIN))
    assert after_permit["status"] == "EXPIRED"
    assert after_permit["last_enforcement_reason"] == "PERMIT_EXPIRY", (
        "expiry is evaluated before the drill recompute, so the reason is not a lapse"
    )
    assert after_permit["probation_count"] == 0, (
        "an expired permit is never also counted as newly on probation"
    )
    assert (
        validate_success(api.get_practice(prac_id, ADMIN))["sedation_privilege_state"]
        == "UNPERMITTED"
    )

    after_block = validate_success(api.get_block_time(block["id"], SCHEDULER))
    assert after_block["status"] == "RELEASED"
    assert after_block["released_minutes"] == 240
    assert after_block["open_minutes"] == 0
    assert after_block["committed_minutes"] == 0
    assert_block_ledger_conserved(after_block)

    again = validate_success(api.run_compliance_sweep({"practice_id": prac_id}, ADMIN))
    for counter in (
        "permits_expired",
        "permits_suspended",
        "blocks_released",
        "blocks_partially_released",
        "cases_cancelled",
        "reservations_released",
    ):
        assert again[counter] == 0, (
            f"a second sweep at the same clock must report {counter} as 0"
        )
