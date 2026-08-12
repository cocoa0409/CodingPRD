"""Rehearsal slots: buffered stage overlap, attendance credit, terminal guards."""
from test_helpers import (
    ApiErrorId,
    get_contract,
    make_accepted_contract,
    make_contract,
    make_performer,
    make_season,
    make_slot,
    set_clock,
    setup_shortfall_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, DIRECTOR
from test_helpers.test_users import make_performer_headers


def test_rehearsal_attend_bubbles_contract_to_rehearsing(api, any_headers):
    """PRD §3.2: "An `ATTENDED` outcome sets the slot's `hours_credit` to its
    duration in hours — the difference between `end_time` and `start_time` — adds
    that credit to the contract's `completed_rehearsal_hours`, and, if the contract
    was still `ACCEPTED`, moves it automatically to `REHEARSING`."

    Design: Corner/state_machines/rehearsal_attend_bubbles_contract_to_rehearsing
    """
    season = make_season(name="Bubble Revel")
    performer, contract = make_accepted_contract(
        season["id"], performer_name="Axel the Bold",
        offered_day_rate_cents=20000, guaranteed_days=2,
        weather_pay_pct=0.5, required_rehearsal_hours=4,
    )
    slot = make_slot(contract["id"], "MAIN",
                     "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z")

    attended = validate_success(
        api.record_attendance(slot["id"], {"outcome": "ATTENDED"}, DIRECTOR), 200
    )
    assert attended["hours_credit"] == 2.0

    contract_after = validate_success(api.get_cast_contract(contract["id"], ANY), 200)
    assert contract_after["status"] == "REHEARSING"
    assert contract_after["completed_rehearsal_hours"] == 2.0


def test_rehearsal_slot_terminal_guards(api):
    """PRD §3.2: "The contract must be `ACCEPTED` or `REHEARSING`, else
    `ERR_CONTRACT_NOT_REHEARSABLE`."
    PRD §3.2: "Attendance recording by the director takes an `outcome` against a
    `SCHEDULED` slot (else `ERR_SLOT_NOT_RECORDABLE`)."
    PRD §3.2: "A slot may instead be cancelled outright while `SCHEDULED` (else
    `ERR_SLOT_NOT_CANCELLABLE`), moving it to `CANCELLED`"

    Design: Corner/errors/rehearsal_slot_terminal_guards
    """
    season = make_season(name="SlotGuard Revel")
    p1 = make_performer(stage_name="Otto", act_type="COMEDY", base_day_rate_cents=9000)
    c1 = make_contract(season["id"], p1["id"], offered_day_rate_cents=9000,
                       guaranteed_days=1, required_rehearsal_hours=2)
    validate_success(api.offer_contract(c1["id"], {}, DIRECTOR), 200)  # OFFERED only

    performer2, c2 = make_accepted_contract(
        season["id"], performer_name="Petra",
        offered_day_rate_cents=9500, guaranteed_days=1, required_rehearsal_hours=2,
    )
    slot = make_slot(c2["id"], "MAIN", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
    validate_success(
        api.record_attendance(slot["id"], {"outcome": "ATTENDED"}, DIRECTOR), 200
    )

    res = api.create_rehearsal_slot(
        {
            "contract_id": c1["id"], "stage_name": "MAIN",
            "start_time": "2026-05-11T09:00:00Z", "end_time": "2026-05-11T10:00:00Z",
        },
        DIRECTOR,
    )
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_REHEARSABLE, expected_status=409)

    res = api.record_attendance(slot["id"], {"outcome": "ATTENDED"}, DIRECTOR)
    validate_error(res, ApiErrorId.ERR_SLOT_NOT_RECORDABLE, expected_status=409)

    res = api.cancel_slot(slot["id"], DIRECTOR)
    validate_error(res, ApiErrorId.ERR_SLOT_NOT_CANCELLABLE, expected_status=409)


def test_rehearsal_overlap_inside_turnover_buffer_rejected(api):
    """PRD §3.2: "Each slot is treated as occupying its stage from its start until
    fifteen minutes after its end — a trailing turnover buffer — and a new slot
    whose own start-to-fifteen-minutes-after-end window intersects the occupancy
    window of an existing `SCHEDULED` or `ATTENDED` slot on the same stage is
    rejected with `ERR_REHEARSAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rehearsal_stage_buffered_overlap
    """
    season = make_season(name="Stage Revel", volunteer_min_hours=0)
    performer, contract = make_accepted_contract(
        season["id"], performer_name="The Fire Sisters",
        offered_day_rate_cents=15000, guaranteed_days=2,
        weather_pay_pct=0.5, required_rehearsal_hours=6,
    )
    # 09:00-10:00 occupies the stage over [09:00, 10:15).
    make_slot(contract["id"], "MAIN", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")

    # Starting 10 minutes after the previous end is still inside the buffer.
    res = api.create_rehearsal_slot(
        {
            "contract_id": contract["id"], "stage_name": "MAIN",
            "start_time": "2026-05-10T10:10:00Z", "end_time": "2026-05-10T11:00:00Z",
        },
        DIRECTOR,
    )
    validate_error(res, ApiErrorId.ERR_REHEARSAL_OVERLAP, expected_status=409)


def test_rehearsal_slot_at_buffer_boundary_accepted(api):
    """PRD §3.2: "Each slot is treated as occupying its stage from its start until
    fifteen minutes after its end — a trailing turnover buffer" — under the
    half-open interval rule of §2.5: "an interval includes its start and excludes
    its end, so one residency or shift may begin at the exact instant another ends
    without conflict."

    Design: Difficulty/resource_temporal_overlap/rehearsal_stage_buffered_overlap
    """
    season = make_season(name="Stage Revel", volunteer_min_hours=0)
    performer, contract = make_accepted_contract(
        season["id"], performer_name="The Fire Sisters",
        offered_day_rate_cents=15000, guaranteed_days=2,
        weather_pay_pct=0.5, required_rehearsal_hours=6,
    )
    make_slot(contract["id"], "MAIN", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")

    # Starting exactly at end + 15 minutes touches the half-open boundary only.
    slot2 = validate_success(
        api.create_rehearsal_slot(
            {
                "contract_id": contract["id"], "stage_name": "MAIN",
                "start_time": "2026-05-10T10:15:00Z", "end_time": "2026-05-10T11:15:00Z",
            },
            DIRECTOR,
        ),
        201,
    )
    assert slot2["status"] == "SCHEDULED"


def test_rehearsal_shortfall_penalty_in_final_payout(api, operator_headers, any_headers):
    """PRD §3.2: "the final payout is the greater of `accrued_payout_cents` and
    `guaranteed_days` times `offered_day_rate_cents`, minus a rehearsal-shortfall
    penalty. The shortfall is the amount by which `required_rehearsal_hours` exceeds
    `completed_rehearsal_hours`, treated as zero when the requirement was met; each
    short hour costs 5,000 cents, with the penalty rounded half up to whole cents
    once, and the resulting `final_payout_cents` is floored at zero so a settlement
    can never go negative."
    PRD §3.2: "When a faire day completes, every contract of the season in
    `PERFORMING` at that moment adds its full `offered_day_rate_cents` to
    `accrued_payout_cents`."

    Design: Corner/calculations/rehearsal_shortfall_penalty_in_final_payout
    """
    ctx = setup_shortfall_scenario()
    contract = validate_success(api.get_cast_contract(ctx["contract_id"], ANY), 200)
    assert contract["status"] == "COMPLETED"
    # The COMPLETED day accrued nothing: the contract (2.0 of 4 required hours)
    # never reached PERFORMING. One weather-cancelled day paid round(20000*0.5).
    assert contract["accrued_payout_cents"] == 10000
    # Final: max(10000, 2 * 20000) - (4 - 2) * 5000 = 40000 - 10000 = 30000.
    assert contract["final_payout_cents"] == 30000
