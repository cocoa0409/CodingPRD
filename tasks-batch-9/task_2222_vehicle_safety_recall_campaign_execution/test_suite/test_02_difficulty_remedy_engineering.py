"""
Remedy engineering: the independence of the two campaign dimensions, and the
closed-window conflict rule that governs labor operation codes.
"""

from test_helpers import (
    ApiErrorId,
    CampaignStatus,
    RemedyStatus,
    assert_labor_operation,
    factories as f,
    fixtures as fx,
    get_success_data,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import SAFETY_ENGINEER_1, SAFETY_ENGINEER_2_ID

STOCK_UNIT = {"sale_status": "IN_DEALER_STOCK", "owner_name": "Stock Unit"}


def _interim_then_released(api):
    """
    A campaign carried FILED -> INTERIM_NOTIFIED by a stop-sale advisory, then
    given a released remedy by a second engineer.
    """
    return fx.campaign_with_remedy(
        api,
        vehicles=[STOCK_UNIT],
        interim_advisory={"stop_sale": True, "do_not_drive": True},
    )


def test_remedy_release_advances_only_the_remedy_dimension(api):
    """
    Releasing the remedy out of INTERIM_ONLY moves `remedy_status` to
    REMEDY_RELEASED and leaves `campaign_status` at INTERIM_NOTIFIED, spending
    exactly one version increment.

    PRD §2.5: "A recall campaign carries two lifecycle dimensions on one record,
    and they advance independently."

    PRD §3.4: "A release stamps `remedy_released_at` from the logical clock and
    `remedy_released_by_user_id` from the caller's `X-User-ID` — refreshing both
    on a re-release — and increments the campaign's `version` by 1."

    Design: Difficulty/non_linear_state_machine/campaign_parallel_status_and_remedy_dimensions_advance_independently
    """
    state = _interim_then_released(api)
    campaign = state["campaign"]

    assert campaign["remedy_status"] == RemedyStatus.REMEDY_RELEASED
    assert campaign["campaign_status"] == CampaignStatus.INTERIM_NOTIFIED, (
        "releasing a remedy is not an administrative advance"
    )
    assert campaign["version"] == state["campaign_version_before_release"] + 1
    assert campaign["remedy_released_by_user_id"] == SAFETY_ENGINEER_2_ID
    assert campaign["remedy_revision_count"] == 0


def test_remedy_release_lifts_the_stop_sale_hold_but_not_the_do_not_drive_flag(api):
    """
    The release clears `stop_sale_flag` and the build record's `stop_sale_hold`
    while the do-not-drive advisory raised by the same interim notice survives.

    PRD §3.4: "It also lifts the sales freeze: `stop_sale_flag` is set to false
    and every vehicle in the campaign's population carrying `stop_sale_hold` has
    that hold cleared."

    PRD §3.4: "`do_not_drive_flag` is deliberately left untouched."

    Design: Difficulty/non_linear_state_machine/campaign_parallel_status_and_remedy_dimensions_advance_independently
    """
    state = _interim_then_released(api)
    campaign = state["campaign"]

    assert campaign["stop_sale_flag"] is False
    assert campaign["do_not_drive_flag"] is True

    vehicle = get_success_data(api.get_vehicle(state["vehicle_id"], SAFETY_ENGINEER_1))
    assert vehicle["stop_sale_hold"] is False
    assert vehicle["sale_status"] == "IN_DEALER_STOCK"


def test_labor_operation_starting_on_a_siblings_end_date_is_refused(api):
    """
    A second labor operation with the same code whose `effective_from` equals the
    existing operation's `effective_to` intersects it, because the window is
    closed at both ends.

    PRD §3.5: "Two labor operations sharing the same campaign and the same
    `labor_op_code` may not have intersecting closed windows, and because both
    ends are inclusive, windows that merely touch — where the existing
    operation's `effective_to` equals the new one's `effective_from` — *do*
    intersect and are rejected with `ERR_LABOR_OP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/labor_operation_closed_window_rejects_touching_endpoint
    """
    state = fx.draft_campaign(api)
    campaign_id = state["campaign_id"]
    lop_a = fx.add_labor_operation(api, campaign_id)

    response = api.create_labor_operation(
        campaign_id,
        f.labor_operation_payload(
            flat_hours=1.20, effective_from="2027-12-31", effective_to="2028-12-31"
        ),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.LABOR_OP_WINDOW_CONFLICT, 409)

    ops, _ = read_list(
        api.list_labor_operations(campaign_id, SAFETY_ENGINEER_1, {"labor_op_code": "R101-01"}),
        expected_total=1,
    )
    assert ops[0]["id"] == lop_a["id"]
    assert ops[0]["effective_to"] == "2027-12-31"
    assert ops[0]["flat_hours"] == 1.10


def test_labor_operation_starting_the_day_after_a_sibling_ends_is_accepted(api):
    """
    Moving the new operation's `effective_from` one day past the existing
    operation's `effective_to` removes the intersection, so both codes coexist
    and the first keeps its published hours.

    PRD §3.5: "**The labor-operation window is closed at both ends**: a date
    qualifies when it is on or after `effective_from` and on or before
    `effective_to`."

    PRD §3.5: "Labor-operation listings accept a `labor_op_code` filter and an
    `effective_on` date filter that returns only codes whose closed window
    contains that date."

    Design: Difficulty/resource_temporal_overlap/labor_operation_closed_window_rejects_touching_endpoint
    """
    state = fx.draft_campaign(api)
    campaign_id = state["campaign_id"]
    lop_a = fx.add_labor_operation(api, campaign_id)

    response = api.create_labor_operation(
        campaign_id,
        f.labor_operation_payload(
            flat_hours=1.20, effective_from="2028-01-01", effective_to="2028-12-31"
        ),
        SAFETY_ENGINEER_1,
    )
    lop_b = validate_success(response, 201)
    assert_labor_operation(lop_b)
    assert lop_b["effective_from"] == "2028-01-01"
    assert lop_b["flat_hours"] == 1.20
    assert lop_b["claim_count"] == 0

    ops, _ = read_list(
        api.list_labor_operations(campaign_id, SAFETY_ENGINEER_1, {"labor_op_code": "R101-01"}),
        expected_total=2,
    )
    stored_a = next(o for o in ops if o["id"] == lop_a["id"])
    assert stored_a["effective_to"] == "2027-12-31"
    assert stored_a["flat_hours"] == 1.10
