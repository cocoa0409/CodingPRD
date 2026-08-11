"""Storage economics, the billing-cycle close and mid-cycle plan changes."""

from test_helpers import (
    CMRA_OPERATOR,
    PLATFORM_ADMIN,
    make_box_holder_headers,
    assert_billing_cycle,
    assert_storage_day_partition,
    assert_usage_ledger_entry,
    activate_box,
    box_version,
    create_box,
    create_plan_tier,
    log_and_match_letter,
    open_billing_cycle,
    plan_change_payload,
    read_mail_item,
    read_scan_job_list,
    request_scan,
    set_clock,
    setup_releasable_box,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The free storage window
# ==========================================================================
def _setup_letter_on_a_five_day_window(box_number, legal_name, holder_email):
    ctx = setup_releasable_box(
        box_number,
        legal_name,
        holder_email=holder_email,
        plan_overrides={"name": "Plus Five Day Storage", "included_storage_days": 5},
    )
    item = log_and_match_letter(ctx)
    ctx["item_id"] = item["id"]
    return ctx


def test_a_piece_at_exactly_the_included_storage_days_is_still_free(api):
    """PRD §3.12: "`free_storage_days_used` is the smaller of total custody days and the
    tier's `included_storage_days`, and `billable_storage_days` is total custody days
    less `free_storage_days_used`."
    PRD §3.12: "The storage axis leaves `FREE_WINDOW` for `ACCRUING` only when four
    conditions hold together: the piece is still in `FREE_WINDOW`; its `handling_status`
    is `RECEIVED`, `AWAITING_CLEARANCE` or `HELD` — never `PENDING_DISPOSITION`, which is
    precisely the suspension described in §3.7; its total custody days is **strictly
    greater than** the tier's `included_storage_days`, so a piece sitting at exactly the
    included figure is still free; and its `item_class` is not `SOP`."

    Five whole custody days sits exactly ON the still-free edge.

    Design: Difficulty/boundary_precision_check/storage_free_window_exact_day_boundary
    """
    ctx = _setup_letter_on_a_five_day_window("N-1401", "Uma Store", "uma@example.com")

    set_clock("2026-05-06T00:00:00Z")

    piece = read_mail_item(ctx["item_id"])
    assert piece["storage_status"] == "FREE_WINDOW"
    assert piece["free_storage_days_used"] == 5
    assert piece["billable_storage_days"] == 0
    assert piece["billing_status"] == "UNBILLED"
    assert_storage_day_partition(piece, 5)


def test_one_day_past_the_included_window_starts_the_accrual(api):
    """PRD §3.12: "The transition appends a usage-ledger entry of `unit_type`
    `STORAGE_DAY` into the mailbox's `OPEN` billing cycle, increments that cycle's
    `storage_days_consumed`, moves the piece's `billing_status` `UNBILLED → METERED` if
    it was still unbilled, and bumps `MailItem.version` by one."
    PRD §3.12: "Thereafter the accrual repeats once per additional whole day: the
    quantity metered on any occasion is the piece's `billable_storage_days` now less its
    `billable_storage_days` at the previous metering, and the money is that difference
    multiplied by the tier's `overage_storage_day_cents`."

    Six whole custody days sits one day ABOVE the still-free edge.

    Design: Difficulty/boundary_precision_check/storage_free_window_exact_day_boundary
    """
    ctx = _setup_letter_on_a_five_day_window("N-1401", "Uma Store", "uma@example.com")

    set_clock("2026-05-06T00:00:00Z")
    set_clock("2026-05-07T00:00:00Z")

    piece = read_mail_item(ctx["item_id"])
    assert piece["storage_status"] == "ACCRUING"
    assert piece["free_storage_days_used"] == 5
    assert piece["billable_storage_days"] == 1
    assert piece["billing_status"] == "METERED"
    assert_storage_day_partition(piece, 6)

    cycle = open_billing_cycle(ctx["box_id"])
    assert cycle["storage_days_consumed"] == 1
    entries, meta = validate_paginated(
        api.list_cycle_usage_entries(
            cycle["id"], CMRA_OPERATOR, params={"unit_type": "STORAGE_DAY"}
        )
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert entry["tranche"] == "OVERAGE"
    assert entry["quantity"] == 1
    assert entry["unit_rate_cents"] == 30
    assert entry["amount_cents"] == 30


def test_storage_usage_is_discoverable_from_the_piece_itself(api):
    """PRD §3.4: "The usage-ledger entries attributable to one piece may also be listed,
    filtered by `unit_type`."
    PRD §3.12: "Total custody days is the elapsed time between `received_at` and that end
    of custody, divided by 86,400 seconds with any remainder discarded — whole days only,
    always rounded down."

    Design: Corner/endpoints/usage_entries_are_discoverable_from_the_mail_item
    """
    ctx = setup_releasable_box(
        "Z-4003",
        "Sal Ledger",
        holder_email="sal@example.com",
        home_address_line="1 Ledger Ln",
        plan_overrides={"included_storage_days": 5},
    )
    item = log_and_match_letter(ctx)

    set_clock("2026-05-09T00:00:00Z")

    entries, meta = validate_paginated(
        api.list_mail_item_usage_entries(
            item["id"], CMRA_OPERATOR, params={"unit_type": "STORAGE_DAY"}
        )
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert_usage_ledger_entry(entry)
    assert entry["unit_type"] == "STORAGE_DAY"
    assert entry["tranche"] == "OVERAGE"
    assert entry["quantity"] == 3
    assert entry["unit_rate_cents"] == 30
    assert entry["amount_cents"] == 90
    assert entry["source_event"] == "STORAGE_ACCRUAL"

    piece = read_mail_item(item["id"])
    assert piece["free_storage_days_used"] == 5
    assert piece["billable_storage_days"] == 3
    assert_storage_day_partition(piece, 8)


# ==========================================================================
# The monthly charge and the loyalty tier
# ==========================================================================
def _setup_cycle_ready_to_close_with_scan_overage(api):
    ctx = setup_releasable_box(
        "D-401",
        "Gil Loyal",
        holder_email="gil@example.com",
        plan_overrides={
            "tier_code": "ENTERPRISE",
            "name": "Grand",
            "rank": 4,
            "monthly_fee_cents": 38000,
            "included_scan_pages": 0,
        },
        home_address_line="44 Pine Rd",
    )
    item = log_and_match_letter(ctx, interior_scan_consent=True)
    request_scan(ctx, item["id"], "INTERIOR", 100)
    for job in read_scan_job_list(item["id"]):
        validate_success(api.start_scan_job(job["id"], CMRA_OPERATOR))
        validate_success(api.complete_scan_job(job["id"], CMRA_OPERATOR))
    set_clock("2026-05-31T00:00:00Z")
    return ctx


def test_the_loyalty_percentage_is_keyed_on_the_pre_discount_subtotal(api):
    """PRD §3.12: "The loyalty percentage is then selected **from that subtotal**: 10
    percent when the subtotal is greater than or equal to 40,000 cents, otherwise 5
    percent when it is greater than or equal to 15,000 cents, otherwise zero."
    PRD §3.12: "`loyalty_discount_cents` is the subtotal multiplied by that percentage,
    rounded half up to whole cents."
    PRD §3.12: "`total_charge_cents` is the subtotal less `loyalty_discount_cents`."
    PRD §2.6: "The discount percentage is selected by comparing the subtotal computed
    before any discount, and the discount is then subtracted."

    The subtotal of 40,500 sits above the inclusive 40,000-cent edge of the 10 percent
    tier; re-keying on the post-discount total would demote it.

    Design: Difficulty/combinatorial_formula/loyalty_tier_keyed_on_pre_discount_subtotal
    """
    ctx = _setup_cycle_ready_to_close_with_scan_overage(api)

    closed = validate_success(api.close_billing_cycle(ctx["box_id"], PLATFORM_ADMIN))
    assert_billing_cycle(closed)
    assert closed["loyalty_discount_cents"] == 4050
    assert closed["total_charge_cents"] == 36450


def test_the_closing_cycle_freezes_its_base_fee_and_overage_total(api):
    """PRD §3.12: "First `OPEN → CLOSING`, which freezes `plan_tier_id_at_close` with the
    mailbox's `plan_tier_id` as of that moment and `base_fee_cents` with that tier's
    `monthly_fee_cents`, and runs the metering and monthly-charge calculations."
    PRD §3.12: "The subtotal is `base_fee_cents` plus `overage_total_cents` plus
    `proration_charge_cents` less `proration_credit_cents`, where `overage_total_cents`
    is the sum of `amount_cents` over this cycle's usage-ledger entries whose `tranche`
    is `OVERAGE`."

    Design: Difficulty/combinatorial_formula/loyalty_tier_keyed_on_pre_discount_subtotal
    """
    ctx = _setup_cycle_ready_to_close_with_scan_overage(api)

    closed = validate_success(api.close_billing_cycle(ctx["box_id"], PLATFORM_ADMIN))
    assert closed["base_fee_cents"] == 38000
    assert closed["overage_total_cents"] == 2500
    assert closed["scan_pages_consumed"] == 100
    assert closed["status"] == "CLOSED"


# ==========================================================================
# Mid-cycle plan change
# ==========================================================================
def _setup_two_boxes_on_two_tiers():
    basic = create_plan_tier(
        tier_code="BASIC",
        name="Basic",
        rank=1,
        monthly_fee_cents=3000,
        included_recipients=2,
        included_scan_pages=20,
        included_forwards=1,
    )
    plus = create_plan_tier(
        tier_code="PLUS", name="Plus", rank=2, monthly_fee_cents=6100
    )
    upgrader = create_box(
        "B-201", basic["id"], holder_name="Up Grader", holder_email="up@example.com"
    )
    activate_box(upgrader["id"])
    downgrader = create_box(
        "B-202", plus["id"], holder_name="Down Grader", holder_email="down@example.com"
    )
    activate_box(downgrader["id"])
    set_clock("2026-05-20T00:00:00Z")
    return {
        "basic_id": basic["id"],
        "plus_id": plus["id"],
        "upgrader_id": upgrader["id"],
        "downgrader_id": downgrader["id"],
    }


def test_an_upgrade_takes_effect_at_once_and_books_both_proration_amounts(api):
    """PRD §3.12: "When the new tier's `rank` is **strictly greater** than the old
    tier's — an upgrade — `proration_credit_cents` is the old tier's `monthly_fee_cents`
    multiplied by days remaining, divided by 30, rounded half up exactly once, and
    `proration_charge_cents` is the same computation on the new tier's
    `monthly_fee_cents`; `plan_tier_id` is set to the new tier immediately and
    `pending_plan_tier_id` is set to null."
    PRD §2.6: "Deriving a rounded daily rate first and multiplying it by the remaining
    days is a different and incorrect answer: a 6,100-cent tier with 11 days remaining
    yields 2237 cents under the pinned order and 2233 cents under the rounded-daily-rate
    order."

    Design: Difficulty/dual_variant_calc/plan_change_upgrade_vs_downgrade_proration
    """
    ids = _setup_two_boxes_on_two_tiers()
    box_id = ids["upgrader_id"]
    holder = make_box_holder_headers(box_id)

    updated = validate_success(
        api.change_plan(
            box_id, plan_change_payload(ids["plus_id"], box_version(box_id)), holder
        )
    )
    assert updated["plan_tier_id"] == ids["plus_id"]
    assert updated["pending_plan_tier_id"] is None

    cycle = open_billing_cycle(box_id)
    assert cycle["proration_credit_cents"] == 1100
    assert cycle["proration_charge_cents"] == 2237


def test_a_downgrade_is_deferred_and_books_no_proration(api):
    """PRD §3.12: "When the new tier's `rank` is **strictly lower** — a downgrade — both
    proration amounts are zero, `plan_tier_id` is left exactly as it was, and
    `pending_plan_tier_id` is set to the new tier so that the change lands at the next
    close."
    PRD §3.12: "An identical request body therefore produces two entirely different
    outcomes depending only on the rank comparison."

    Design: Difficulty/dual_variant_calc/plan_change_upgrade_vs_downgrade_proration
    """
    ids = _setup_two_boxes_on_two_tiers()
    box_id = ids["downgrader_id"]
    holder = make_box_holder_headers(box_id)

    updated = validate_success(
        api.change_plan(
            box_id, plan_change_payload(ids["basic_id"], box_version(box_id)), holder
        )
    )
    assert updated["plan_tier_id"] == ids["plus_id"]
    assert updated["pending_plan_tier_id"] == ids["basic_id"]

    cycle = open_billing_cycle(box_id)
    assert cycle["proration_credit_cents"] == 0
    assert cycle["proration_charge_cents"] == 0
