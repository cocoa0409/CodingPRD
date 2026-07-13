"""Screening panel: screen creation and the three independent axes (Newborn Screening PRD)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_satisfactory_specimen,
    create_screen_on_satisfactory,
    create_hospital_and_infant,
    create_specimen,
    receive_specimen,
    point_of_care_hearing_payload,
    point_of_care_cchd_payload,
    TEST_USERS,
    make_birth_facility_user_headers,
)

LAB = TEST_USERS["lab_technician_headers"]


# ─── Corner: opening a screen immediately moves specimen to IN_TESTING ─
def test_screen_create_moves_specimen_in_testing_immediately(api):
    """PRD §3.4: "opening it links the screen to the specimen and moves the specimen from
    `SATISFACTORY` to `IN_TESTING`."

    Design: Corner/consistency_model/screen_create_moves_specimen_in_testing_immediately
    """
    _facility, _infant, specimen = create_satisfactory_specimen()
    validate_success(api.create_screen({"specimen_id": specimen["id"]}, LAB), 201)
    reloaded = get_success_data(api.get_specimen(specimen["id"], LAB))
    assert reloaded["status"] == "IN_TESTING"


# ─── Corner: CCHD RETEST at lower reading 94 ──────────────────────────
def test_cchd_retest_at_94_lower(api):
    """PRD §3.4: "In every other case — a lower reading from 90 through 94, or a lower
    reading of at least 95 with a difference greater than 3 — the interpretation is
    `RETEST`."

    Design: Corner/calculations/cchd_retest_at_94_lower_saturation
    """
    facility, _infant, _specimen, screen = create_screen_on_satisfactory()
    hdr = make_birth_facility_user_headers(facility["id"])
    updated = validate_success(
        api.report_point_of_care(screen["id"], point_of_care_cchd_payload(94, 96), hdr), 200
    )
    assert updated["cchd_status"] == "RETEST"


# ─── Difficulty: CCHD PASS at the exact >=95 boundary ─────────────────
def test_cchd_pass_at_exactly_95_both_limbs(api):
    """PRD §3.4: "Otherwise, if the lower reading is at least 95 and the difference is at
    most 3, the interpretation is `PASS`."
    PRD §3.4: "exactly 95 is eligible for a pass."

    Design: Difficulty/boundary_precision_check/cchd_pass_at_exactly_95_saturation
    """
    facility, _infant, _specimen, screen = create_screen_on_satisfactory()
    hdr = make_birth_facility_user_headers(facility["id"])
    updated = validate_success(
        api.report_point_of_care(screen["id"], point_of_care_cchd_payload(95, 95), hdr), 200
    )
    assert updated["cchd_status"] == "PASS"


def test_cchd_pass_at_95_with_difference_exactly_three(api):
    """PRD §3.4: "Otherwise, if the lower reading is at least 95 and the difference is at
    most 3, the interpretation is `PASS`."

    Design: Difficulty/boundary_precision_check/cchd_pass_at_exactly_95_saturation
    """
    facility, _infant, _specimen, screen = create_screen_on_satisfactory()
    hdr = make_birth_facility_user_headers(facility["id"])
    # lower reading 95, difference exactly 3 → still PASS
    updated = validate_success(
        api.report_point_of_care(screen["id"], point_of_care_cchd_payload(95, 98), hdr), 200
    )
    assert updated["cchd_status"] == "PASS"


# ─── Difficulty: three axes evolve independently on one screen ────────
def test_hearing_refer_leaves_metabolic_pending(api):
    """PRD §3.4: "A `REFER` moves it from `NOT_DONE` to `REFER` and sets `overall_disposition`
    to `FLAGGED`; in addition, if no follow-up case is currently open for this screen, a
    `SHORT_TERM` `FollowUpCase` is opened in `OPEN` state with `critical_flag_count` of zero
    and `opened_at_clock` at the current clock, the infant's `open_case_count` is
    incremented, `followup_status` becomes `ACTIVE`, and an INITIAL priority score is
    computed — but the specimen is not moved out of `IN_TESTING` and the metabolic axis
    stays `PENDING`."

    Design: Difficulty/non_linear_state_machine/screen_three_axes_evolve_independently
    """
    facility, _infant, _specimen, screen = create_screen_on_satisfactory()
    hdr = make_birth_facility_user_headers(facility["id"])
    updated = validate_success(
        api.report_point_of_care(screen["id"], point_of_care_hearing_payload("REFER"), hdr), 200
    )
    assert updated["hearing_status"] == "REFER"
    assert updated["metabolic_status"] == "PENDING"
    assert updated["cchd_status"] == "NOT_DONE"


def test_three_axes_move_independently_hearing_refer_cchd_pass_metabolic_pending(api):
    """PRD §3.4: "A screen carries three independent status axes that evolve on the same
    record: a metabolic axis (`metabolic_status`, starting `PENDING`), a hearing axis
    (`hearing_status`, starting `NOT_DONE`), and a critical-congenital-heart-disease axis
    (`cchd_status`, starting `NOT_DONE`)."

    Design: Difficulty/non_linear_state_machine/screen_three_axes_evolve_independently
    """
    facility, _infant, _specimen, screen = create_screen_on_satisfactory()
    hdr = make_birth_facility_user_headers(facility["id"])
    api.report_point_of_care(screen["id"], point_of_care_hearing_payload("REFER"), hdr)
    updated = validate_success(
        api.report_point_of_care(screen["id"], point_of_care_cchd_payload(98, 97), hdr), 200
    )
    assert updated["hearing_status"] == "REFER"
    assert updated["cchd_status"] == "PASS"
    assert updated["metabolic_status"] == "PENDING"


# ─── Difficulty: screen create blocked by an UNSATISFACTORY specimen ──
def test_screen_create_on_unsatisfactory_specimen_rejected(api):
    """PRD §3.4: "The screen may be opened only when the specimen is in `SATISFACTORY` state,
    else the create is rejected with `ERR_SPECIMEN_NOT_SATISFACTORY`; opening it links the
    screen to the specimen and moves the specimen from `SATISFACTORY` to `IN_TESTING`."

    Design: Difficulty/cross_entity_state_dependency/screen_create_blocked_by_unsatisfactory_specimen
    """
    facility, infant = create_hospital_and_infant()
    specimen = create_specimen(facility, infant)
    receive_specimen(specimen, blood_spot_count=2)  # UNSATISFACTORY
    res = api.create_screen({"specimen_id": specimen["id"]}, LAB)
    validate_error(res, "ERR_SPECIMEN_NOT_SATISFACTORY", expected_status=409)


def test_screen_create_rejected_leaves_specimen_unsatisfactory(api):
    """PRD §3.4: "The screen may be opened only when the specimen is in `SATISFACTORY` state,
    else the create is rejected with `ERR_SPECIMEN_NOT_SATISFACTORY`; opening it links the
    screen to the specimen and moves the specimen from `SATISFACTORY` to `IN_TESTING`."

    Design: Difficulty/cross_entity_state_dependency/screen_create_blocked_by_unsatisfactory_specimen
    """
    facility, infant = create_hospital_and_infant()
    specimen = create_specimen(facility, infant)
    receive_specimen(specimen, blood_spot_count=2)  # UNSATISFACTORY
    api.create_screen({"specimen_id": specimen["id"]}, LAB)
    reloaded = get_success_data(api.get_specimen(specimen["id"], LAB))
    assert reloaded["status"] == "UNSATISFACTORY"
    screens = get_success_data(api.list_screens(LAB, params={"specimen_id": specimen["id"]}))
    assert len(screens) == 0
