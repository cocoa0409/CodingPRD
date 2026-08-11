"""The shop sweep: counter-bill expiry followed by deemed BRC acceptance."""
from test_helpers import (
    TEST_USERS, api_client, counter_item, file_counter_bill,
    scenario_submitted_brc, set_clock, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]


def test_sweep_deemed_acceptance_and_counter_expiry():
    """PRD §2.4: "The sweep applies counter-bill expiry first — any
    counter-bill still `OPEN` or `REBUTTED` once the logical clock has passed
    the disputed card's dispute window plus an additional grace of the shop's
    `counter_window_days` moves to `EXPIRED` — and then applies deemed
    acceptance: any Billing Repair Card still `SUBMITTED` whose dispute window
    has passed with no `OPEN` or `REBUTTED` counter-bill moves to `ACCEPTED`,
    posting party balances exactly as a manual acceptance would."
    PRD §2.4: "When the last active counter on a disputed card expires, the
    card returns from `DISPUTED` to `SUBMITTED` and is then eligible for deemed
    acceptance within the same sweep."

    Design: Corner/cross_cutting_layers/sweep_deemed_acceptance_and_counter_expiry
    """
    ctx = scenario_submitted_brc(actual_hours=1.5)  # BRC 13500 submitted at base clock
    cb = file_counter_bill(ctx, [counter_item(ctx["brc_lines"][0]["id"], 1000,
                                              "left hanging")])
    assert cb["status"] == "OPEN"

    # Submitted 2026-05-01T08:00:00Z -> dispute window ends 2026-05-31T08:00Z;
    # a further 30-day grace for counters ends 2026-06-30T08:00Z.
    set_clock("2026-07-01T10:00:01Z")
    validate_success(api_client.sweep_shop(ctx["shop"]["id"], ADMIN))

    cb_now = validate_success(api_client.get_counter_bill(cb["id"], ADMIN))
    assert cb_now["status"] == "EXPIRED", "OPEN past dispute window plus grace expires"

    brc_now = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc_now["status"] == "ACCEPTED", "deemed acceptance once no active counters remain"

    owner = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner["outstanding_balance_cents"] == 13500, (
        "deemed acceptance posts the same net balance as a manual acceptance; "
        "the expired counter grants no credit")
