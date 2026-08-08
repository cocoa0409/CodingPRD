"""Relocation: per-diem reimbursement rounding, placement precedence, buffered overlap.

Queue A: combinatorial_formula, priority_pair_validation_conflict, resource_temporal_overlap.
Queue B: validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_case, setup_relocation_unit, create_placement,
    create_relocation_placement_payload, TEST_USERS,
)

CM = TEST_USERS["case_manager_headers"]


# ─── combinatorial_formula / relocation_reimbursement_round_per_day_then_sum ─
def test_reimbursement_rounds_per_day_then_multiplies_nights(api):
    """PRD §3.8: "This raw daily amount is rounded half up to whole cents to produce the
    per-day amount, and only then is the per-day amount multiplied by the number of
    nights to give `reimbursement_cents`. The rounding is applied to the per-day figure
    before the multiplication, not to the full product."

    Design: Difficulty/combinatorial_formula/relocation_reimbursement_round_per_day_then_sum
    """
    ctx = setup_case(income_tier="LOW", bll=25.0)
    unit = setup_relocation_unit()
    placement = create_placement(ctx["case_id"], unit["id"], "2026-06-01", "2026-06-30",
                                 occupant_count=3)
    ended = validate_success(api_client.end_relocation_placement(
        placement["id"], {"actual_end_date": "2026-06-06"}, CM), 200)
    # per_day = round_half_up((12000 + 3500*3) * 1.075) = round_half_up(24187.5) = 24188
    # reimbursement = 24188 * 5 nights = 120940
    assert ended["reimbursement_cents"] == 120940


def test_placement_end_records_status_and_actual_end_date(api):
    """PRD §3.8: "Ending sets `status` to `ENDED`, records `actual_end_date`, and
    computes `reimbursement_cents`."

    Design: Difficulty/combinatorial_formula/relocation_reimbursement_round_per_day_then_sum
    """
    ctx = setup_case(income_tier="LOW", bll=25.0)
    unit = setup_relocation_unit()
    placement = create_placement(ctx["case_id"], unit["id"], "2026-06-01", "2026-06-30",
                                 occupant_count=3)
    ended = validate_success(api_client.end_relocation_placement(
        placement["id"], {"actual_end_date": "2026-06-06"}, CM), 200)
    assert ended["status"] == "ENDED"
    assert ended["actual_end_date"] == "2026-06-06"
    assert ended["reimbursement_cents"] == 120940


# ─── priority_pair_validation_conflict / referential_beats_temporal_on_relocation ─
def test_terminal_case_placement_returns_case_not_active(api):
    """PRD §2.8: "on relocation placement a **case-not-active** failure
    (`ERR_CASE_NOT_ACTIVE`, priority 12) takes precedence over a **temporal-overlap**
    failure (`ERR_RELOCATION_OVERLAP`, priority 14): when both would fail, the
    case-not-active error wins."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_relocation
    """
    ctx_a = setup_case(income_tier="LOW", bll=22.0)
    ctx_b = setup_case(income_tier="LOW", bll=22.0)
    unit = setup_relocation_unit()
    create_placement(ctx_a["case_id"], unit["id"], "2026-06-01", "2026-06-10", occupant_count=2)
    validate_success(api_client.withdraw_case(ctx_b["case_id"], CM), 200)
    res = api_client.create_relocation_placement(
        create_relocation_placement_payload(ctx_b["case_id"], unit["id"],
                                             start_date="2026-06-05", end_date="2026-06-08",
                                             occupant_count=2), CM)
    validate_error(res, "ERR_CASE_NOT_ACTIVE")


def test_case_not_active_reported_instead_of_overlap(api):
    """PRD §3.8: "When both the case-not-active and the overlap checks would fail, the
    case-not-active error is reported first (see §2.8)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_relocation
    """
    ctx_a = setup_case(income_tier="LOW", bll=22.0)
    ctx_b = setup_case(income_tier="LOW", bll=22.0)
    unit = setup_relocation_unit()
    create_placement(ctx_a["case_id"], unit["id"], "2026-06-01", "2026-06-10", occupant_count=2)
    validate_success(api_client.withdraw_case(ctx_b["case_id"], CM), 200)
    res = api_client.create_relocation_placement(
        create_relocation_placement_payload(ctx_b["case_id"], unit["id"],
                                             start_date="2026-06-05", end_date="2026-06-08",
                                             occupant_count=2), CM)
    error = validate_error(res, "ERR_CASE_NOT_ACTIVE")
    assert error["error_id"] != "ERR_RELOCATION_OVERLAP"


# ─── resource_temporal_overlap / relocation_unit_buffered_closed_overlap ─
def test_placement_within_cleaning_buffer_rejected(api):
    """PRD §3.8: "the placement is rejected with `ERR_RELOCATION_OVERLAP` (HTTP 409) if
    the unit has any other `ACTIVE` placement whose closed interval falls within a
    cleaning buffer of 3 days of this one — concretely, a conflict exists when the new
    stay's `start_date` is on or before the existing stay's `end_date` plus 3 days and
    the new stay's `end_date` is on or after the existing stay's `start_date` minus 3
    days."

    Design: Difficulty/resource_temporal_overlap/relocation_unit_buffered_closed_overlap
    """
    ctx = setup_case(income_tier="LOW", bll=22.0)
    unit = setup_relocation_unit()
    create_placement(ctx["case_id"], unit["id"], "2026-06-01", "2026-06-05", occupant_count=2)
    res = api_client.create_relocation_placement(
        create_relocation_placement_payload(ctx["case_id"], unit["id"],
                                             start_date="2026-06-07", end_date="2026-06-10",
                                             occupant_count=2), CM)
    validate_error(res, "ERR_RELOCATION_OVERLAP")


def test_placement_beyond_cleaning_buffer_accepted(api):
    """PRD §3.8: "a conflict exists when the new stay's `start_date` is on or before the
    existing stay's `end_date` plus 3 days and the new stay's `end_date` is on or after
    the existing stay's `start_date` minus 3 days."

    Design: Difficulty/resource_temporal_overlap/relocation_unit_buffered_closed_overlap
    """
    ctx = setup_case(income_tier="LOW", bll=22.0)
    unit = setup_relocation_unit()
    create_placement(ctx["case_id"], unit["id"], "2026-06-01", "2026-06-05", occupant_count=2)
    placement = validate_success(api_client.create_relocation_placement(
        create_relocation_placement_payload(ctx["case_id"], unit["id"],
                                             start_date="2026-06-20", end_date="2026-06-25",
                                             occupant_count=2), CM), 201)
    assert placement["status"] == "ACTIVE"


# ─── Corner: validations / placement_on_offline_unit_returns_unit_unavailable ─
def test_placement_on_offline_unit_returns_unit_unavailable(api):
    """PRD §3.8: "The chosen unit's `status` must be `AVAILABLE`, else
    `ERR_UNIT_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/placement_on_offline_unit_returns_unit_unavailable
    """
    ctx = setup_case(income_tier="LOW", bll=22.0)
    unit = setup_relocation_unit(status="OFFLINE", bedroom_count=1)
    res = api_client.create_relocation_placement(
        create_relocation_placement_payload(ctx["case_id"], unit["id"],
                                             start_date="2026-06-01", end_date="2026-06-05",
                                             occupant_count=2), CM)
    validate_error(res, "ERR_UNIT_UNAVAILABLE")
