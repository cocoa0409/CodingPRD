"""Seasonal lottery: deterministic draw ranking, draw-timing precondition,
claim state gate, and the duplicate-entry rule."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_boater,
    create_vessel,
    setup_open_round,
    enter_lottery,
    create_lottery_entry_payload,
)

HARBOR = TEST_USERS["harbormaster_headers"]


def test_draw_ranks_resident_ahead_of_earlier_nonresident(api):
    """PRD §3.6: "The draw considers only `ENTERED` entries whose vessel is
    `REGISTERED` at the moment of the draw, ranks them by lowest `priority_tier`
    and then by lowest `draw_number`, and awards berths as a waterfall: with K
    equal to the number of ids in `berth_ids`, the first K ranked entries move
    from `ENTERED` to `WON`, the i-th winner receiving the i-th berth id as its
    `awarded_berth_id`; all remaining eligible entries and any entry whose vessel
    was not `REGISTERED` move from `ENTERED` to the terminal `LOST` state."

    Design: Corner/calculations/lottery_draw_resident_priority_over_entry_order
    """
    s = setup_open_round(api, "2026-04-05T00:00:00Z")
    round_id, berth_id = s["round"]["id"], s["berth"]["id"]
    boater_n = create_boater(api, full_name="NonRes First", email="nf@example.com",
                             residency_status="NON_RESIDENT")
    vessel_n = create_vessel(api, boater_n["id"], length_ft=30)
    entry_n = enter_lottery(api, round_id, boater_n["id"], vessel_n["id"])
    boater_r = create_boater(api, full_name="Res Second", email="rs@example.com",
                             residency_status="RESIDENT")
    vessel_r = create_vessel(api, boater_r["id"], length_ft=30)
    entry_r = enter_lottery(api, round_id, boater_r["id"], vessel_r["id"])
    set_clock(api, "2026-04-11T00:00:00Z")
    validate_success(api.draw_round(round_id, HARBOR))
    won = get_success_data(api.get_lottery_entry(entry_r["id"], HARBOR))
    lost = get_success_data(api.get_lottery_entry(entry_n["id"], HARBOR))
    assert won["status"] == "WON"
    assert won["awarded_berth_id"] == berth_id
    assert lost["status"] == "LOST"


def test_draw_before_close_date_rejected(api):
    """PRD §3.6: "A harbormaster draws the round once the clock is strictly after
    the `entry_close_date`; a premature draw is rejected with
    `ERR_ROUND_NOT_CLOSED_FOR_DRAW` (HTTP 409)"

    Design: Corner/state_machines/draw_before_close_date_returns_not_closed
    """
    s = setup_open_round(api, "2026-04-05T00:00:00Z")  # clock within entry window
    validate_error(
        api.draw_round(s["round"]["id"], HARBOR),
        ApiErrorId.ERR_ROUND_NOT_CLOSED_FOR_DRAW,
    )
    assert get_success_data(api.get_lottery_round(s["round"]["id"], HARBOR))["status"] == "OPEN"


def test_claim_entry_still_entered_rejected(api):
    """PRD §3.6: "a claim on an entry not in `WON` status with `ERR_ENTRY_NOT_WON`
    (HTTP 409)"

    Design: Corner/state_machines/claim_entry_not_won_returns_invalid
    """
    s = setup_open_round(api, "2026-04-05T00:00:00Z")
    boater = create_boater(api, full_name="Ent E", email="ent@example.com")
    vessel = create_vessel(api, boater["id"], length_ft=30)
    entry = enter_lottery(api, s["round"]["id"], boater["id"], vessel["id"])
    validate_error(api.claim_entry(entry["id"], HARBOR), ApiErrorId.ERR_ENTRY_NOT_WON)
    assert get_success_data(api.get_lottery_entry(entry["id"], HARBOR))["status"] == "ENTERED"


def test_duplicate_entry_same_boater_vessel_rejected(api):
    """PRD §3.6: "The same boater-and-vessel pair may not enter the same round
    twice; a duplicate is rejected with `ERR_DUPLICATE_LOTTERY_ENTRY` (HTTP 409)."

    Design: Corner/validations/duplicate_lottery_entry_returns_conflict
    """
    s = setup_open_round(api, "2026-04-05T00:00:00Z")
    boater = create_boater(api, full_name="Dup D", email="dup@example.com")
    vessel = create_vessel(api, boater["id"], length_ft=30)
    enter_lottery(api, s["round"]["id"], boater["id"], vessel["id"])
    validate_error(
        api.create_lottery_entry(
            create_lottery_entry_payload(s["round"]["id"], boater["id"], vessel["id"]), HARBOR
        ),
        ApiErrorId.ERR_DUPLICATE_LOTTERY_ENTRY,
    )
