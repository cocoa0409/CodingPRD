"""Buffered closed-interval build windows, and the rejected actions that leave the set.

PRD §3.5: "only a gap of 31 days or more is accepted."
"""

from test_helpers import (
    ENGINEER_HEADERS,
    ERR_FIELD_ACTION_WINDOW_CONFLICT,
    create_family,
    create_field_action,
    create_period,
    create_remedy_option,
    decide_field_action,
    factories,
    read_field_action,
    select_remedy,
    submit_field_action,
    success_data,
    validate_error,
    validate_paginated,
)


def _build_world(api):
    """FAM-S owns a DRAFT window in Q1 2025 and a REJECTED window in August 2025."""
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-S",
        name="Steam Oven Platform",
        launch_date="2024-06-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=22000,
        reserve_cap_cents=60000000,
    )
    draft = create_field_action(
        api,
        family["id"],
        action_code="FA-S-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=1200,
        regulatory_notice_filed=False,
    )
    rejected = create_field_action(
        api,
        family["id"],
        action_code="FA-S-90",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-08-01",
        affected_build_end_date="2025-08-31",
        affected_unit_count=900,
        regulatory_notice_filed=False,
    )
    option = create_remedy_option(
        api,
        rejected["id"],
        option_code="OPT-S90",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=2000,
        labor_hours_centi=90,
        admin_cost_cents=300,
        expected_take_rate_bps=6000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, rejected["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, rejected["id"])
    decided = decide_field_action(api, rejected["id"], "REJECTED")
    assert decided["approval_state"] == "REJECTED"

    return {"family": family, "draft": draft, "rejected": rejected}


def _open_window(api, family_id, action_code, start, end, units):
    payload = factories.field_action_payload(
        family_id,
        action_code=action_code,
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date=start,
        affected_build_end_date=end,
        affected_unit_count=units,
        regulatory_notice_filed=False,
    )
    return api.create_field_action_raw(ENGINEER_HEADERS, payload)


def test_a_window_opening_exactly_thirty_days_later_is_still_inside_the_buffer(api):
    """Day 30 conflicts because the buffered comparison is inclusive at both ends.

    PRD §3.5: "a conflict exists when the new window's start date falls on or before the
    existing window's end date advanced by 30 days, and simultaneously the existing
    window's start date retreated by 30 days falls on or before the new window's end
    date. Adjacency is therefore illegal here ... and so is any gap of 30 days or fewer
    between the two windows." 2025-03-31 advanced by 30 days is 2025-04-30 exactly.

    Design: Difficulty/resource_temporal_overlap/closed_build_windows_need_a_thirty_day_buffer_and_ignore_rejected_actions
    """
    world = _build_world(api)

    response = _open_window(
        api, world["family"]["id"], "FA-S-02", "2025-04-30", "2025-06-30", 700
    )
    validate_error(response, ERR_FIELD_ACTION_WINDOW_CONFLICT, expected_status=409)


def test_a_window_opening_one_day_later_clears_the_buffer(api):
    """Day 31 is the first accepted start.

    PRD §3.5: "only a gap of 31 days or more is accepted." Starting on 2025-05-01 puts
    31 days between the new window and the existing 2025-03-31 end, and PRD §3.5 gives
    the resulting row's state: "A new action starts with `approval_state` of `DRAFT`".

    Design: Difficulty/resource_temporal_overlap/closed_build_windows_need_a_thirty_day_buffer_and_ignore_rejected_actions
    """
    world = _build_world(api)

    response = _open_window(
        api, world["family"]["id"], "FA-S-03", "2025-05-01", "2025-06-30", 700
    )
    action = success_data(response, expected_status=201)
    assert action["approval_state"] == "DRAFT"
    assert action["affected_build_start_date"] == "2025-05-01"


def test_a_rejected_action_leaves_the_conflict_input_set_entirely(api):
    """A window straight through a rejected campaign is accepted.

    PRD §3.5: "It must not intersect the window of any existing field action on the same
    family whose `approval_state` is `DRAFT`, `SUBMITTED` or `APPROVED` ... Field actions
    whose `approval_state` is `REJECTED` are excluded from the check entirely, so a
    rejected campaign does not block its own replacement." PRD §3.5 also confirms the
    rejected row surrendered its accrual: "It advances the action to `REJECTED`, records
    the controller's identifier as `decided_by_user_id`, and forces
    `specific_accrual_cents` back to 0."

    Design: Difficulty/resource_temporal_overlap/closed_build_windows_need_a_thirty_day_buffer_and_ignore_rejected_actions
    """
    world = _build_world(api)
    _open_window(api, world["family"]["id"], "FA-S-03", "2025-05-01", "2025-06-30", 700)

    response = _open_window(
        api, world["family"]["id"], "FA-S-91", "2025-08-10", "2025-09-10", 400
    )
    replacement = success_data(response, expected_status=201)
    assert replacement["approval_state"] == "DRAFT"

    blocked = read_field_action(api, world["rejected"]["id"])
    assert blocked["approval_state"] == "REJECTED"
    assert blocked["specific_accrual_cents"] == 0

    _, meta = validate_paginated(
        api.list_field_actions(ENGINEER_HEADERS, family_id=world["family"]["id"])
    )
    assert meta["total_count"] == 4
