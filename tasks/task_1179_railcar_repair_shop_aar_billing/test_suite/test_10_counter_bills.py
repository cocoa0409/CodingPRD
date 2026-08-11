"""Counter-bill windows, single-active-counter rule, and the rebut/revise loop."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, counter_item, file_counter_bill,
    make_car_owner_rep_headers, scenario_submitted_brc, set_clock,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]


def test_counter_bill_window_closed_after_dispute_window():
    """PRD §3.8: "Either responsible party may file a counter-bill against a
    card in `SUBMITTED` or `DISPUTED`, provided the filing lands within the
    dispute window — a filing after `dispute_window_ends_at` is rejected with
    `ERR_COUNTER_BILL_WINDOW_CLOSED`".
    PRD §3.7: "computes `dispute_window_ends_at` as `submitted_at` plus the
    shop's `counter_window_days`".

    Design: Corner/validations/counter_bill_window_closed_after_dispute_window
    """
    ctx = scenario_submitted_brc(actual_hours=1.5)  # submitted while clock reads base time
    # The BRC was submitted at 2026-05-01T08:00:00Z; the 30-day dispute window
    # ends 2026-05-31T08:00:00Z. Advance one second past the following day.
    set_clock("2026-06-01T10:00:01Z")
    resp = api_client.create_counter_bill(
        ctx["brc"]["id"],
        {"items": [counter_item(ctx["brc_lines"][0]["id"], 1000, "too late")]},
        make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_COUNTER_BILL_WINDOW_CLOSED, expected_status=409)
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "SUBMITTED", "rejected filing leaves the card SUBMITTED"


def test_second_counter_bill_while_open_rejected():
    """PRD §3.8: "no other counter-bill on the card is `OPEN` or `REBUTTED`,
    else `ERR_COUNTER_BILL_ACTIVE`."

    Design: Corner/errors/second_counter_bill_while_open_rejected
    """
    ctx = scenario_submitted_brc(actual_hours=1.5)
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])
    bl_id = ctx["brc_lines"][0]["id"]
    cb1 = file_counter_bill(ctx, [counter_item(bl_id, 1000, "first")])
    assert cb1["status"] == "OPEN"
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "DISPUTED"

    resp = api_client.create_counter_bill(
        ctx["brc"]["id"],
        {"items": [counter_item(bl_id, 500, "second while open")]}, owner)
    validate_error(resp, ApiErrorId.ERR_COUNTER_BILL_ACTIVE, expected_status=409)

    cb1_now = validate_success(api_client.get_counter_bill(cb1["id"], ADMIN))
    assert cb1_now["status"] == "OPEN", "first counter-bill is untouched"
    brc_now = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc_now["status"] == "DISPUTED", "card stays disputed while a counter is active"


def test_counter_bill_rebut_revise_cycle():
    """PRD §3.8: "Rebutting instead moves an `OPEN` counter to `REBUTTED` with
    an optional `rebuttal_note`. The filer — and only the filer, matched by
    `filed_by_id` — may then revise a `REBUTTED` counter back to `OPEN` with a
    replacement `items` list, provided the dispute window is still open;
    revision recomputes `total_countered_cents` and re-runs both ceiling
    checks."

    Design: Corner/errors/counter_bill_rebut_revise_cycle
    """
    ctx = scenario_submitted_brc(actual_hours=1.5)  # final 13500
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])
    bl_id = ctx["brc_lines"][0]["id"]
    cb = file_counter_bill(ctx, [counter_item(bl_id, 1000, "first pass")])
    assert cb["total_countered_cents"] == 1000

    rebutted = validate_success(api_client.rebut_counter_bill(
        cb["id"], {"rebuttal_note": "hours documented"}, BILLING))
    assert rebutted["status"] == "REBUTTED"

    revised = validate_success(api_client.revise_counter_bill(
        cb["id"], {"items": [counter_item(bl_id, 1200, "revised upward with evidence")]},
        owner))
    assert revised["status"] == "OPEN", "revise returns the counter to OPEN"
    assert revised["total_countered_cents"] == 1200, "items replaced and total recomputed"
