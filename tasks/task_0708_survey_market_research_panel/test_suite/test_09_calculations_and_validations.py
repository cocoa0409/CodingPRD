"""Calculation results and single-failure validation rejections.

Corner queue (B): sections calculations and validations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_study, create_quota_cell, create_panelist, create_consent,
    create_fielding_study_with_cell, setup_panelist_with_consent,
    create_screening_participation, setup_qualified_participation,
    setup_started_participation, create_facility,
    create_focus_group_payload, create_focus_group_booking_payload,
    create_data_delivery_payload, submit_payload, get_panelist_version,
    make_panelist_headers,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


# ----------------------- calculations -----------------------
def test_payout_cash_cents_computed_from_points(api):
    """PRD §3.7: "At request time the server computes cash_cents as
    points_requested times the conversion rate of 2 cents per point."

    Design: Corner/calculations/payout_cash_cents_computed_from_points
    """
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_CC2")
    pid = panelist["id"]
    ph = make_panelist_headers(pid)
    v0 = get_panelist_version(pid)
    data = validate_success(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "CASH", "points_requested": 150,
         "expected_panelist_version": v0}, ph), expected_status=201)
    assert data["cash_cents"] == 300, \
        f"cash_cents should be 150*2=300, got {data['cash_cents']}"


def test_build_delivery_snapshots_included_completes(api):
    """PRD §3.9: "On build, the system snapshots included_completes_n as the count
    of the study's participations whose quality_status is PASS and whose
    completion_status is COMPLETED at build time."

    Design: Corner/calculations/build_delivery_snapshots_included_completes
    """
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_SNP")
    assert participation["quality_status"] == "PASS"
    delivery = get_success_data(api.create_data_delivery(
        create_data_delivery_payload(study["id"], report_format="CSV"), RM))
    validate_success(api.close_study(study["id"], RM))

    built = validate_success(api.build_data_delivery(delivery["id"], RM))
    assert built["status"] == "READY"
    assert built["included_completes_n"] == 1, \
        f"one PASS+COMPLETED participation should snapshot to 1, got {built['included_completes_n']}"


# ----------------------- validations -----------------------
def test_duplicate_segment_key_in_study_returns_conflict(api):
    """PRD §3.1: "The segment_key must be unique within a single study's quota
    cells; attempting to add a second cell with a segment label already in use for
    that study is rejected with ERR_DUPLICATE_SEGMENT (HTTP 409)."

    Design: Corner/validations/duplicate_segment_key_in_study_returns_conflict
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    create_quota_cell(study["id"], segment_key="DUP", target_n=2)
    validate_error(api.create_quota_cell(study["id"], {"segment_key": "DUP", "target_n": 3}, RM),
                   ApiErrorId.ERR_DUPLICATE_SEGMENT.value)


def test_launch_without_quota_cells_returns_no_quota_cells(api):
    """PRD §3.1: "a launch attempted with no quota cells (total target below 1) is
    rejected with ERR_NO_QUOTA_CELLS (HTTP 409)."

    Design: Corner/validations/launch_without_quota_cells_returns_no_quota_cells
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    validate_error(api.launch_study(study["id"], RM), ApiErrorId.ERR_NO_QUOTA_CELLS.value)


def test_launch_empty_irb_returns_irb_required(api):
    """PRD §3.1: "A launch attempted with an empty IRB protocol is rejected with
    ERR_IRB_PROTOCOL_REQUIRED (HTTP 422)".

    Design: Corner/validations/launch_empty_irb_returns_irb_required
    """
    study = get_success_data(api.create_study(
        {"title": "EI", "irb_protocol_number": "", "estimated_minutes": 10,
         "base_incentive_points": 50, "screener_min_age": 0}, RM))
    create_quota_cell(study["id"], segment_key="SEG_EI", target_n=2)
    validate_error(api.launch_study(study["id"], RM), ApiErrorId.ERR_IRB_PROTOCOL_REQUIRED.value)


def test_payout_below_minimum_returns_below_minimum(api):
    """PRD §3.7: "The request must redeem at least the minimum payout of 100
    points; a smaller request is rejected with ERR_PAYOUT_BELOW_MINIMUM
    (HTTP 422)."

    Design: Corner/validations/payout_below_minimum_returns_below_minimum
    """
    panelist = create_panelist(segment_key="SEG_BM")
    v0 = get_panelist_version(panelist["id"])
    ph = make_panelist_headers(panelist["id"])
    validate_error(api.create_payout_request(
        {"panelist_id": panelist["id"], "payout_method": "CASH", "points_requested": 1,
         "expected_panelist_version": v0}, ph), ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM.value)


def test_focus_group_seats_exceed_capacity_returns_error(api):
    """PRD §3.8: "The offered seats must not exceed the facility's capacity, or
    scheduling is rejected with ERR_SEATS_EXCEED_CAPACITY (HTTP 422)."

    Design: Corner/validations/focus_group_seats_exceed_capacity_returns_error
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    facility = create_facility(capacity=3)
    validate_error(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-05-02T10:00:00Z",
                                   ends_at="2026-05-02T11:00:00Z", seats=5), FC),
        ApiErrorId.ERR_SEATS_EXCEED_CAPACITY.value)


def test_booking_when_session_full_returns_session_full(api):
    """PRD §3.8: "the session must still have room — booking is blocked once
    booked_n is greater than or equal to the offered seats, in which case it is
    rejected with ERR_SESSION_FULL (HTTP 409)."

    Design: Corner/validations/booking_when_session_full_returns_session_full
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    facility = create_facility(capacity=5)
    fg = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-05-03T10:00:00Z",
                                   ends_at="2026-05-03T11:00:00Z", seats=1), FC))
    pA = create_panelist(email="sf1@x.com", segment_key="SEG_SF")
    pB = create_panelist(email="sf2@x.com", segment_key="SEG_SF")
    get_success_data(api.create_focus_group_booking(
        create_focus_group_booking_payload(fg["id"], pA["id"], fg["version"]), FC))
    fg_fresh = validate_success(api.get_focus_group(fg["id"], FC))

    validate_error(api.create_focus_group_booking(
        create_focus_group_booking_payload(fg["id"], pB["id"], fg_fresh["version"]), FC),
        ApiErrorId.ERR_SESSION_FULL.value)


def test_submit_missing_fields_returns_submit_fields_missing(api):
    """PRD §3.3: "The submit body must supply completion_seconds (how long the
    panelist took) and straightline_run ... if either is absent the submit is
    rejected with ERR_SUBMIT_FIELDS_MISSING (HTTP 422)."

    Design: Corner/validations/submit_missing_fields_returns_submit_fields_missing
    """
    study, cell, panelist, participation = setup_started_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_SM")
    ph = make_panelist_headers(panelist["id"])
    # straightline_run omitted.
    validate_error(api.submit_participation(participation["id"], {"completion_seconds": 600}, ph),
                   ApiErrorId.ERR_SUBMIT_FIELDS_MISSING.value)


def test_rescreen_over_limit_returns_rescreen_limit_rejected(api):
    """PRD §3.2: "the participation has not exhausted its rescreen budget — its
    rescreen_count must be strictly below the maximum of three rescreens, or the
    request is rejected with ERR_RESCREEN_LIMIT (HTTP 422)."

    Design: Corner/validations/rescreen_over_limit_returns_rescreen_limit_rejected
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_RL")
    panelist = create_panelist(segment_key="SEG_RL")
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])
    # Loop screen-OUT / rescreen until rescreen_count reaches the max of 3.
    for _ in range(3):
        get_success_data(api.screen_participation(part["id"], "OUT", FC))
        rescreened = get_success_data(api.rescreen_participation(part["id"], FC))
    assert rescreened["rescreen_count"] == 3, \
        f"rescreen_count should be 3 after three loops, got {rescreened['rescreen_count']}"

    # Now at the limit: screen OUT once more then the next rescreen is rejected.
    get_success_data(api.screen_participation(part["id"], "OUT", FC))
    validate_error(api.rescreen_participation(part["id"], FC), ApiErrorId.ERR_RESCREEN_LIMIT.value)
