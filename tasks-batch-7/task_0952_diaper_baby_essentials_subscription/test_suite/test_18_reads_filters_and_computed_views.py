"""Filtered list reads, the computed projections, and the append-only log reads."""

from test_helpers import (
    TEST_USERS,
    assert_same_instant,
    cycle_lines,
    list_credits_of,
    list_referrals,
    list_substitution_events,
    make_account_holder_headers,
    make_child,
    make_plan,
    make_sku,
    make_subscription,
    read_cycle,
    register_and_verify_account,
    set_clock,
    setup_allocated_cycle,
    setup_household,
    unique_code,
    unique_email,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate,
    allocate_cycle,
    charge_cycle,
    deliver_cycle,
    dispatch_cycle,
    generate_cycle,
    lock_cycle,
    make_registry,
    make_registry_item,
    pay_gift,
    reserve_gift,
    setup_open_registry,
    setup_registry_parties,
)

OPS = TEST_USERS["ops_admin_headers"]


def test_the_pipeline_r_reads_walk_the_whole_foreign_key_graph(api):
    """PRD §2.3: "Filter parameters named in section 4 combine conjunctively — supplying two
    filters narrows the result to rows matching both."
    PRD §3.5: "Cycle lines are readable individually and listable, filterable by `cycle_id`, by
    `sku_id` and by `status`."
    PRD §3.2: "Children are listable, filterable by `account_id` and by `stage`, and readable
    by the household, by a `RegistryOwner`, and by support and operations staff."

    Design: Corner/endpoints/corner_filtered_reads_walk_the_pipeline_r_fk_graph
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="graph")
    headers = ctx["headers"]

    children, children_meta = validate_paginated(
        api.list_children(headers, {"account_id": ctx["account_id"]})
    )
    subscriptions, sub_meta = validate_paginated(
        api.list_subscriptions(headers, {"account_id": ctx["account_id"]})
    )
    cycles, cycle_meta = validate_paginated(
        api.list_cycles(headers, {"subscription_id": ctx["subscription"]["id"]})
    )
    lines, line_meta = validate_paginated(
        api.list_cycle_lines(headers, {"cycle_id": cycle["id"]})
    )

    assert children[0]["id"] == ctx["child"]["id"]
    assert subscriptions[0]["id"] == ctx["subscription"]["id"]
    assert cycles[0]["id"] == cycle["id"]

    line = validate_success(api.get_cycle_line(lines[0]["id"], headers))
    assert line["sku_id"] == ctx["sku"]["id"]

    for meta in (children_meta, sub_meta, cycle_meta, line_meta):
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


def test_the_cadence_projection_and_pricing_preview_mutate_nothing(api):
    """PRD §3.4: "a forward-looking cadence read reports the current `cadence_interval_days`,
    the current `anchor_date`, the projected `next_window_start`, `next_window_end` and
    `next_cutoff_at`, and an `override_active` boolean saying whether a manual override is
    presently pinned."
    PRD §3.7: "A pricing preview read returns this whole breakdown without mutating anything:
    `subtotal_cents`, `shipping_cents`, `gift_credit_applied_cents`,
    `referral_credit_applied_cents`, `loyalty_redemption_applied_cents`,
    `loyalty_points_redeemed`, `promo_discount_cents`, `total_due_cents` and
    `points_earn_base_cents`."

    Design: Corner/endpoints/corner_cadence_projection_and_pricing_preview_computed_reads
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="proj")
    version_before = read_cycle(api, cycle["id"])["version"]

    projection = validate_success(
        api.get_cadence_projection(ctx["subscription"]["id"], ctx["headers"])
    )
    assert projection["cadence_interval_days"] == 20
    assert_same_instant(
        projection["next_window_start"], "2026-06-28T00:00:00Z", "next_window_start"
    )
    assert_same_instant(
        projection["next_cutoff_at"], "2026-06-26T00:00:00Z", "next_cutoff_at"
    )
    assert projection["override_active"] is False

    preview = validate_success(api.get_pricing_preview(cycle["id"], ctx["headers"]))
    assert preview["total_due_cents"] == 2999
    assert preview["points_earn_base_cents"] == 2400

    assert read_cycle(api, cycle["id"])["version"] == version_before, (
        "a computed read never mutates the cycle"
    )


def test_the_registry_summary_reports_the_fulfilment_progress(api):
    """PRD §3.9: "A summary read reports `item_count`, `requested_units`, `fulfilled_units`,
    `completion_pct` and `inflight_gift_count` for the registry as a whole."
    PRD §3.9: "A registry's `completion_pct` is the sum of `fulfilled_quantity` across all of
    its items divided by the sum of `requested_quantity` across all of its items, with no
    status filter on either sum, rounded half up to four decimal places; when nothing is
    requested at all the value is 0. It is recomputed whenever items are added, changed or
    removed and whenever gift activity moves a fulfilled quantity."

    Design: Corner/endpoints/corner_registry_summary_computed_read
    """
    parties, registry, item = setup_open_registry(api, requested_quantity=3)
    gift = reserve_gift(api, parties, item, 2)
    pay_gift(api, parties, gift["id"])

    summary = validate_success(
        api.get_registry_summary(registry["id"], parties["owner_headers"])
    )
    assert summary["item_count"] == 1
    assert summary["requested_units"] == 3
    assert summary["fulfilled_units"] == 2
    assert summary["completion_pct"] == 0.6667

    shopper_view = validate_success(
        api.get_registry(registry["id"], parties["purchaser_headers"])
    )
    assert shopper_view["completion_pct"] == 0.6667


def test_the_registry_gift_and_item_reads_all_resolve(api):
    """PRD §3.9: "The owner may rename a registry by supplying a new `title`."
    PRD §3.9: "Gift orders are readable and listable, filterable by `registry_item_id`,
    `purchaser_account_id` and `status`."
    PRD §3.9: "The reservation is persisted with `status` `PENDING_PAYMENT`, `paid_cents` 0,
    `claim_mode` null, `paid_at` null and `claimed_at` null, and the registry item's `version`
    is advanced."

    Design: Corner/endpoints/corner_registry_and_gift_and_item_reads
    """
    parties, registry, item = setup_open_registry(api, requested_quantity=2)
    version_before = registry["version"]
    gift = reserve_gift(api, parties, item, 1)

    renamed = validate_success(
        api.update_registry(registry["id"], {"title": "New Title"}, parties["owner_headers"])
    )
    assert renamed["title"] == "New Title"
    assert renamed["version"] > version_before

    registries, _ = validate_paginated(
        api.list_registries(parties["owner_headers"], {"owner_account_id": parties["owner_id"]})
    )
    assert registries[0]["id"] == registry["id"]

    items, _ = validate_paginated(
        api.list_registry_items(parties["owner_headers"], {"registry_id": registry["id"]})
    )
    assert items[0]["id"] == item["id"]

    gifts, _ = validate_paginated(
        api.list_gift_orders(parties["purchaser_headers"], {"registry_item_id": item["id"]})
    )
    assert gifts[0]["id"] == gift["id"]

    read_back = validate_success(
        api.get_gift_order(gift["id"], parties["purchaser_headers"])
    )
    assert read_back["status"] == "PENDING_PAYMENT"
    assert read_back["paid_cents"] == 0


def test_the_append_only_logs_are_readable_and_filterable(api):
    """PRD §3.2: "Flags are listable by `child_id` and by `severity`, and either role may
    delete one."
    PRD §3.5: "Skip records are readable individually and listable, filterable by
    `subscription_id`, `cycle_id` and `status`."
    PRD §3.4: "Pause records are readable individually and listable, filterable by
    `subscription_id` and by `status`."
    PRD §3.4: "`consumed_days` is what the budget actually counts, and it is computed per
    record: an `ENDED` record consumes the inclusive number of days from its `start_date` to its
    `actual_end_date`; an `ACTIVE` record consumes the inclusive number of days from its
    `start_date` to today; a `SCHEDULED` or `CANCELLED` record consumes nothing."

    Design: Corner/endpoints/corner_substitution_and_allergen_and_pause_and_skip_reads
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = make_plan(api)
    make_sku(api, code=unique_code("S2-A"), name="Stage 2 A",
             pack_price_cents=1200, pack_size_units=60,
             allergen_tags=["FRAGRANCE"])
    sku_b = make_sku(api, code=unique_code("S2-B"), name="Stage 2 B",
                     pack_price_cents=1500, pack_size_units=80, allergen_tags=[])
    account = register_and_verify_account(
        api, email=unique_email("logs"), payment_method_on_file=True
    )
    headers = make_account_holder_headers(account["id"])
    child = make_child(api, account)
    flag = validate_success(
        api.create_allergen_flag(
            child["id"],
            {"allergen_tag": "FRAGRANCE", "severity": "SEVERE", "note": "Rash after wipes"},
            headers,
        ),
        201,
    )
    subscription = make_subscription(api, account, plan, child)
    subscription = activate(api, account["id"], subscription["id"])
    cycle = generate_cycle(api, subscription["id"])
    allocate_cycle(api, cycle["id"])
    line = cycle_lines(api, cycle["id"])[0]
    assert line["sku_id"] == sku_b["id"], (
        "the allergen screen excluded the fragranced SKU at allocation time"
    )
    assert not list_substitution_events(api, line["id"])

    validate_success(api.skip_cycle(cycle["id"], headers))
    pause = validate_success(
        api.create_pause(
            subscription["id"], {"start_date": "2026-08-01", "end_date": "2026-08-05"}, headers
        ),
        201,
    )

    flags, _ = validate_paginated(api.list_allergen_flags(headers, {"child_id": child["id"]}))
    assert flags[0]["id"] == flag["id"]
    assert validate_success(api.get_allergen_flag(flag["id"], headers))["note"] == "Rash after wipes"

    skips, _ = validate_paginated(
        api.list_skip_records(headers, {"subscription_id": subscription["id"]})
    )
    assert skips[0]["status"] == "APPLIED"

    pauses, _ = validate_paginated(
        api.list_pause_records(headers, {"subscription_id": subscription["id"]})
    )
    assert pauses[0]["id"] == pause["id"]
    read_pause = validate_success(api.get_pause_record(pause["id"], headers))
    assert read_pause["status"] == "SCHEDULED"
    assert read_pause["consumed_days"] == 0


def test_the_points_credit_and_referral_reads_all_resolve(api):
    """PRD §3.11: "Referrals are readable and listable, filterable by `referrer_account_id`,
    `referee_account_id`, `vesting_cycle_id` and `status`."
    PRD §3.7: "Credits are readable individually and listable, filterable by `account_id`,
    `source_gift_order_id`, `source_referral_id`, `credit_type` and `status`."
    PRD §3.11: "Entries are readable and listable, filterable by `loyalty_account_id`,
    `cycle_id` and `entry_type`."
    PRD §3.8: "its multiplier is 1.00 for `BRONZE`, 1.25 for `SILVER` and 1.50 for `GOLD`."

    Design: Corner/endpoints/corner_points_ledger_and_credit_and_referral_reads
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    plan = make_plan(api)
    make_sku(api, code=unique_code("S2-STD"))
    referrer = register_and_verify_account(api, email=unique_email("readA"))
    referee = register_and_verify_account(
        api,
        email=unique_email("readB"),
        payment_method_on_file=True,
        referred_by_code=referrer["referral_code"],
    )
    child = make_child(api, referee, name="Kai", birth_date="2026-02-01")
    subscription = make_subscription(api, referee, plan, child)
    subscription = activate(api, referee["id"], subscription["id"])

    cycle = generate_cycle(api, subscription["id"])
    allocate_cycle(api, cycle["id"])
    set_clock(api, "2026-06-08T00:00:00Z")
    lock_cycle(api, cycle["id"])
    charge_cycle(api, cycle["id"])
    dispatch_cycle(api, cycle["id"])
    deliver_cycle(api, cycle["id"])

    referrals = list_referrals(api, referee_account_id=referee["id"])
    assert len(referrals) == 1
    referral = validate_success(api.get_referral(referrals[0]["id"], OPS))
    assert referral["status"] == "VESTED"
    assert referral["credit_cents"] == 1500
    assert referral["vesting_cycle_id"] == cycle["id"]

    credits = list_credits_of(api, referrer["id"], source_referral_id=referral["id"])
    assert len(credits) == 1
    credit = validate_success(
        api.get_credit(credits[0]["id"], make_account_holder_headers(referrer["id"]))
    )
    assert credit["issued_cents"] == 1500
    assert credit["credit_type"] == "REFERRAL"

    entries, _ = validate_paginated(
        api.list_points_ledger_entries(
            OPS, {"loyalty_account_id": referee["loyalty_account_id"], "entry_type": "EARN"}
        )
    )
    assert len(entries) == 1
    entry = validate_success(api.get_points_ledger_entry(entries[0]["id"], OPS))
    assert entry["delta_points"] == 24
    assert float(entry["tier_multiplier_applied"]) == 1.00

    _events, meta = validate_paginated(
        api.list_substitution_events(OPS, {"cycle_line_id": cycle["id"]})
    )
    assert meta["total_count"] == 0
