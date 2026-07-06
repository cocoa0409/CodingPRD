"""Screening cycle, quota boundary, and bulk-void cascades.

Difficulty queue (A): non_linear_state_machine (rescreen cycle),
boundary_precision_check (quota last-seat), transitive_cascade (study close,
panelist suspend).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_fielding_study_with_cell, setup_panelist_with_consent,
    create_screening_participation, create_panelist, create_consent,
    setup_screened_in_participation,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


def _accruals_for_participation(api, participation_id):
    resp = api.list_incentive_accruals(OPS, params={"participation_id": participation_id})
    data, _ = __import__("test_helpers").validate_paginated(resp)
    return data


def test_rescreen_cycles_screened_out_back_to_screening(api):
    """PRD §3.2: "The coordinator may **rescreen** it, cycling `SCREENED_OUT →
    SCREENING` to give it another pass." "A successful rescreen increments
    `rescreen_count` by one and re-reserves a seat on the cell."

    Design: Difficulty/non_linear_state_machine/participation_rescreen_cycle_screened_out_to_screening
    """
    study, cell = create_fielding_study_with_cell(target_n=1, segment_key="SEG_C")
    panelist = create_panelist(segment_key="SEG_C")
    create_consent(panelist["id"], study["id"])
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])
    # Screen OUT, releasing the seat.
    get_success_data(api.screen_participation(part["id"], "OUT", FC))

    rescreened = validate_success(api.rescreen_participation(part["id"], FC))
    assert rescreened["screening_status"] == "SCREENING", \
        f"rescreen loops back to SCREENING, got {rescreened['screening_status']}"
    assert rescreened["rescreen_count"] == 1, \
        f"rescreen_count should increment to 1, got {rescreened['rescreen_count']}"

    # The cyclic transition re-reserves the cell's only seat.
    cell_after = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_after["reserved_n"] == 1, f"reserved_n should be 1, got {cell_after['reserved_n']}"
    assert cell_after["available_n"] == 0, f"available_n should be 0, got {cell_after['available_n']}"


def test_quota_last_seat_consumed_then_full(api):
    """PRD §3.2: "the cell must still have a seat — `available_n` of at least 1 —
    or the screen is rejected with `ERR_QUOTA_CELL_FULL` (HTTP 409)."
    PRD §2.7: "`reserved_n` is the number of participations on this cell whose
    `screening_status` is `SCREENING` or `SCREENED_IN`".

    Design: Difficulty/boundary_precision_check/quota_last_seat_boundary_one_vs_zero
    """
    study, cell = create_fielding_study_with_cell(target_n=1, segment_key="SEG_LS")
    pnlA = create_panelist(segment_key="SEG_LS")
    pnlB = create_panelist(segment_key="SEG_LS")
    create_consent(pnlA["id"], study["id"])
    create_consent(pnlB["id"], study["id"])

    partA = create_screening_participation(study["id"], pnlA["id"], cell["id"])
    # First screen-in consumes the only seat at available_n == 1.
    get_success_data(api.screen_participation(partA["id"], "IN", FC))
    cell_mid = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_mid["reserved_n"] == 1, f"reserved_n should be 1, got {cell_mid['reserved_n']}"
    assert cell_mid["available_n"] == 0, f"available_n should be 0, got {cell_mid['available_n']}"

    # Second participation's screen-in finds available_n == 0 and is rejected.
    partB = create_screening_participation(study["id"], pnlB["id"], cell["id"])
    validate_error(api.screen_participation(partB["id"], "IN", FC),
                   ApiErrorId.ERR_QUOTA_CELL_FULL.value)
    partB_after = validate_success(api.get_participation(partB["id"], OPS))
    assert partB_after["screening_status"] == "SCREENING", \
        f"rejected screen leaves SCREENING, got {partB_after['screening_status']}"


def test_study_close_cascade_voids_releases_and_voids_accrual(api):
    """PRD §3.4: "When a `ResearchManager` closes a study (moving it `FIELDING →
    CLOSED`, or `PAUSED → CLOSED`), every participation on that study still in
    `SCREENING` or `SCREENED_IN` is forced to `VOIDED` — this is the study-closure
    cascade. Each such void releases that participation's reserved seat on its
    quota cell and flips its held provisional accrual to `VOID`."

    Design: Difficulty/transitive_cascade/study_close_cascade_void_release_voidaccrual
    """
    study, cell, panelist, participation = setup_screened_in_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_CC")

    closed = validate_success(api.close_study(study["id"], RM))
    assert closed["status"] == "CLOSED"

    # Link 1: participation voided.
    part_after = validate_success(api.get_participation(participation["id"], OPS))
    assert part_after["screening_status"] == "VOIDED", \
        f"close cascade must VOID the screened-in participation, got {part_after['screening_status']}"

    # Link 2: seat released.
    cell_after = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_after["reserved_n"] == 0, f"reserved_n should be 0, got {cell_after['reserved_n']}"
    assert cell_after["available_n"] == 2, f"available_n should be 2, got {cell_after['available_n']}"

    # Link 3: held provisional accrual voided -> no credit -> balance 0.
    accruals = _accruals_for_participation(api, participation["id"])
    prov = [a for a in accruals if a["accrual_kind"] == "PROVISIONAL"]
    assert len(prov) == 1, f"expected one PROVISIONAL accrual, got {len(prov)}"
    assert prov[0]["status"] == "VOID", \
        f"provisional accrual must be VOID after close, got {prov[0]['status']}"
    bal = validate_success(api.get_panelist(panelist["id"], OPS))["points_balance"]
    assert bal == 0, f"no points credited, balance should be 0, got {bal}"


def test_panelist_suspend_cascade_voids_and_releases(api):
    """PRD §3.4: "A `PanelOps` operator may suspend a panelist (`ACTIVE →
    SUSPENDED` or `AT_RISK → SUSPENDED`); a suspension is not terminal and forces
    every one of that panelist's participations still in `SCREENING` or
    `SCREENED_IN` to `VOIDED`, again releasing their seats and voiding their held
    accruals."

    Design: Difficulty/transitive_cascade/panelist_suspend_cascade_void_release
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_SC")
    panelist = create_panelist(segment_key="SEG_SC")
    # Participation left in SCREENING (no consent needed to create a participation).
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])
    cell_before = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_before["reserved_n"] == 1, f"seat reserved on create, got {cell_before['reserved_n']}"

    suspended = validate_success(api.suspend_panelist(panelist["id"], OPS))
    assert suspended["status"] == "SUSPENDED"

    # Link 1: the SCREENING participation is voided.
    part_after = validate_success(api.get_participation(part["id"], OPS))
    assert part_after["screening_status"] == "VOIDED", \
        f"suspend cascade must VOID the SCREENING participation, got {part_after['screening_status']}"

    # Link 2: seat released.
    cell_after = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_after["reserved_n"] == 0, f"reserved_n should be 0, got {cell_after['reserved_n']}"
    assert cell_after["available_n"] == 2, f"available_n should be 2, got {cell_after['available_n']}"
