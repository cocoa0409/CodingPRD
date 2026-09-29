"""Requests that break two rules at once. The catalogue's priority order decides which
error the caller is told about, and a control call proves the loser is reachable alone.
"""

from test_helpers import (
    ApiErrorId,
    MODERATE_FACTORS,
    api_client,
    approve_screening,
    assert_bed_ledger_invariant,
    decide_disclosure,
    get_success_data,
    read_client,
    read_unit,
    reserve_bed,
    seed_client,
    seed_client_with_assessed_call,
    seed_disclosure_event,
    seed_legal_advocate,
    seed_privacy_officer,
    seed_screening_request,
    seed_sealed_client_via_compromise,
    seed_shelter_scene,
    unit_version,
    validate_error,
    validate_paginated,
    waitlist_screening,
)

TWO_ADULTS = {"household_size": 2, "minor_children_count": 0, "hmis_disclosure_consent": "DENIED"}
SUBPOENA_KEYS = ["client_code", "legal_name"]
LAPSED_ROI = {"roi_signed_on": "2026-07-01", "roi_expires_on": "2026-07-31"}


def _full_two_bed_unit():
    """Both beds of a STANDARD two-bed unit are reserved; one waitlisted and one approved
    request are left over, both decided while the facility was still OPEN."""
    scene = seed_shelter_scene(
        shelter_overrides={
            "name": "Elm House",
            "nightly_rate_cents": 8000,
            "weekend_surcharge_cents": 2000,
            "child_supplement_cents": 1000,
        },
        unit_overrides={"unit_label": "B1", "unit_type": "STANDARD", "bed_capacity": 2},
    )
    requests = []
    for code, name in (("C-9001", "Alina Ford"), ("C-9002", "Mira Osei"), ("C-9003", "Tess Baird")):
        client, call, _ra = seed_client_with_assessed_call(
            scene.advocate,
            client_overrides=dict(TWO_ADULTS, client_code=code, legal_name=name),
            assessment_overrides=dict(MODERATE_FACTORS),
        )
        requests.append(
            seed_screening_request(
                scene.advocate,
                client["id"],
                call["id"],
                scene.shelter["id"],
                requested_entry_date="2026-08-07",
            )
        )
    first, waitlisted, spare = requests
    approve_screening(scene.manager, first["id"], scene.advocate.id)
    waitlisted = waitlist_screening(scene.manager, waitlisted["id"], scene.advocate.id)
    spare = approve_screening(scene.manager, spare["id"], scene.advocate.id)
    admission = get_success_data(
        reserve_bed(
            scene, first["id"], entry_date="2026-08-07", planned_exit_date="2026-08-12"
        )
    )
    return scene, waitlisted, spare, admission


def test_waitlisted_request_reports_the_state_error_ahead_of_the_capacity_error():
    """The screening's own status is checked before the beds it is asking for.

    PRD: "The named screening request must be in status `APPROVED`, or the create is
    `ERR_SCREENING_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_stay_window_capacity_on_admission_create
    """
    scene, waitlisted, _spare, admission = _full_two_bed_unit()
    version_before = unit_version(scene.manager, scene.unit["id"])

    response = reserve_bed(
        scene,
        waitlisted["id"],
        entry_date="2026-08-07",
        planned_exit_date="2026-08-12",
        expected_shelter_unit_version=version_before,
    )

    body = validate_error(response, ApiErrorId.ERR_SCREENING_NOT_APPROVED.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED.value
    assert (
        get_success_data(
            api_client.get_screening_request(waitlisted["id"], scene.manager.headers)
        )["status"]
        == "WAITLISTED"
    )
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 2
    assert unit["available_beds"] == 0
    assert unit["version"] == version_before
    assert_bed_ledger_invariant(unit)
    rows, _meta = validate_paginated(
        api_client.list_shelter_admissions(
            scene.manager.headers, params={"limit": 100, "offset": 0}
        )
    )
    assert [row["id"] for row in rows] == [admission["id"]]


def test_approved_request_against_a_full_window_reports_the_capacity_error():
    """With the state precondition satisfied the fiscal rule is the only one left to break.

    PRD: "Over the half-open day window running from `entry_date` up to but excluding
    `planned_exit_date`, the server sums the `household_size` of every admission already on
    that unit whose `occupancy_status` is `RESERVED` or `CHECKED_IN` and whose own half-open
    window overlaps the requested one, adds the requesting `household_size`, and refuses the
    placement with `ERR_UNIT_CAPACITY_EXCEEDED` if the total exceeds the unit's
    `bed_capacity`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_stay_window_capacity_on_admission_create
    """
    scene, _waitlisted, spare, admission = _full_two_bed_unit()
    version_before = unit_version(scene.manager, scene.unit["id"])
    assert spare["status"] == "APPROVED"

    response = reserve_bed(
        scene,
        spare["id"],
        entry_date="2026-08-07",
        planned_exit_date="2026-08-12",
        expected_shelter_unit_version=version_before,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED.value, 409)
    assert read_unit(scene.manager, scene.unit["id"])["version"] == version_before
    rows, _meta = validate_paginated(
        api_client.list_shelter_admissions(
            scene.manager.headers, params={"limit": 100, "offset": 0}
        )
    )
    assert [row["id"] for row in rows] == [admission["id"]]


def _two_subpoenas_on_lapsed_releases():
    """One sealed survivor and one unsealed survivor, each with a lapsed court subpoena."""
    officer = seed_privacy_officer("Cyn Park", max_caseload=5)
    legal = seed_legal_advocate("Iris Vale", max_caseload=12)
    scene, sealed_client, _admission = seed_sealed_client_via_compromise(
        client_overrides={
            "client_code": "C-9101",
            "legal_name": "Alina Ford",
            "household_size": 1,
            "minor_children_count": 0,
            "hmis_disclosure_consent": "DENIED",
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        compromise_source="COURT_FILING",
    )
    sealed_event = seed_disclosure_event(
        officer,
        sealed_client["id"],
        legal.id,
        "COURT_SUBPOENA",
        SUBPOENA_KEYS,
        requester_org="District Attorney, Family Violence Unit",
        **LAPSED_ROI,
    )
    normal_client = seed_client(
        scene.advocate,
        client_code="C-9102",
        legal_name="Mira Osei",
        household_size=1,
        minor_children_count=0,
        hmis_disclosure_consent="DENIED",
    )
    normal_event = seed_disclosure_event(
        officer,
        normal_client["id"],
        legal.id,
        "COURT_SUBPOENA",
        SUBPOENA_KEYS,
        requester_org="District Attorney, Family Violence Unit",
        **LAPSED_ROI,
    )
    assert read_client(sealed_client["id"])["confidentiality_posture"] == "SEALED"
    assert read_client(normal_client["id"])["confidentiality_posture"] == "NORMAL"
    return officer, sealed_event, normal_event


def test_sealed_record_reports_the_confidentiality_hold_ahead_of_the_lapsed_release():
    """The seal is announced first, even though the paperwork has also expired.

    PRD: "First, the survivor's `confidentiality_posture` must not be `SEALED`: a sealed
    record releases nothing at all, and the refusal is `ERR_CONFIDENTIALITY_HOLD`,
    deliberately evaluated ahead of every paperwork check so that the caller learns about
    the seal rather than about a missing signature."

    Design: Difficulty/priority_pair_validation_conflict/safety_hold_outranks_expired_roi_on_disclosure_decide
    """
    officer, sealed_event, _normal_event = _two_subpoenas_on_lapsed_releases()

    response = decide_disclosure(officer, sealed_event["id"], "RELEASE")

    body = validate_error(response, ApiErrorId.ERR_CONFIDENTIALITY_HOLD.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_ROI_EXPIRED.value
    unchanged = get_success_data(
        api_client.get_disclosure_event(sealed_event["id"], officer.headers)
    )
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["released_field_keys"] == []
    assert unchanged["decided_at"] is None


def test_unsealed_record_with_the_same_lapsed_release_reports_the_roi_error():
    """Remove the seal and the paperwork gate becomes the visible refusal.

    PRD: "Third, a `PARTNER_AGENCY` or `COURT_SUBPOENA` release requires `roi_expires_on`
    to be present and to fall on or after the logical clock reading taken as a UTC calendar
    date; a missing or lapsed release of information is `ERR_ROI_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_hold_outranks_expired_roi_on_disclosure_decide
    """
    officer, _sealed_event, normal_event = _two_subpoenas_on_lapsed_releases()

    response = decide_disclosure(officer, normal_event["id"], "RELEASE")

    validate_error(response, ApiErrorId.ERR_ROI_EXPIRED.value, 409)
    unchanged = get_success_data(
        api_client.get_disclosure_event(normal_event["id"], officer.headers)
    )
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["decided_at"] is None
    assert unchanged["released_field_keys"] == []
