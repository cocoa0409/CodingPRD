"""The standing-route subscription, its cadence series and the allowance ledger."""
from test_helpers import (
    ApiErrorId, ADMIN,
    api_client, build_config, create_account, create_invoice, create_plan_tier,
    create_subscription, list_allowance_entries, make_account_owner_headers, read_account,
    read_invoice, read_item, read_request, read_subscription, route_to_bench, set_clock,
    stage_request,
    validate_error, validate_success, void_invoice, work_and_deliver,
    assert_allowance_ledger_balances, assert_subscription,
)


def _account_with_subscription(cadence="MONTHLY", anchor_date="2026-06-01", **tier_kwargs):
    tier = create_plan_tier(**tier_kwargs)
    account = create_account()
    subscription = create_subscription(account["id"], tier["id"], cadence=cadence,
                                       anchor_date=anchor_date)
    return account, tier, subscription


def test_resuming_an_active_subscription_is_an_invalid_transition():
    """PRD 3.2: "**Resuming.** A resume moves the subscription `PAUSED → ACTIVE`, is
    available only from `PAUSED`, and additionally requires the owning account to be `ACTIVE`."
    PRD 3.2: "The **cycle allowance** is the plan tier's `included_items_per_cycle` multiplied
    by the cadence's allowance multiplier, which is 4 for `WEEKLY`, 2 for `BIWEEKLY` and 1 for
    `MONTHLY`; the product is an exact integer and needs no rounding."

    Design: Corner/state_machines/resuming_an_active_subscription_returns_invalid_state
    """
    account, _tier, subscription = _account_with_subscription()

    response = api_client.resume_subscription(
        subscription["id"], make_account_owner_headers(account["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reread = read_subscription(subscription["id"])
    assert_subscription(reread)
    assert reread["status"] == "ACTIVE"
    assert reread["anchor_date"] == "2026-06-01"
    assert reread["next_service_date"] == "2026-06-01"
    assert reread["allowance_remaining"] == 2
    assert reread["effective_monthly_fee_cents"] == 12000
    assert reread["included_items_this_cycle"] == 2


def test_skip_advances_the_next_service_date_by_exactly_one_interval():
    """PRD 3.2: "It advances `next_service_date` by exactly one cadence interval, increments
    `skip_count_this_cycle` by one, and reaches out into the route: every `SCHEDULED` stop
    belonging to this account whose run date equals the skipped service date moves `SCHEDULED →
    SKIPPED`, and each such stop's service request returns `SCHEDULED → SUBMITTED`, releasing
    its minutes back to the run."
    PRD 3.2: "The next standing visit is derived from the anchor and the interval, where the
    interval is 7 days for `WEEKLY`, 14 for `BIWEEKLY` and 28 for `MONTHLY`."

    Design: Corner/state_machines/subscription_skip_advances_next_service_date_by_one_interval
    """
    account, _tier, subscription = _account_with_subscription()
    assert subscription["next_service_date"] == "2026-06-01"

    skipped = validate_success(api_client.skip_subscription(
        subscription["id"], make_account_owner_headers(account["id"])))
    assert skipped["next_service_date"] == "2026-06-29"
    assert skipped["skip_count_this_cycle"] == 1
    assert skipped["status"] == "ACTIVE"
    assert skipped["cycle_index"] == 1


def test_advance_cycle_expires_the_unused_allowance_and_regrants_it():
    """PRD 3.2: "Because allowance rollover is disabled in this system, the closing act is
    destructive: an `EXPIRED` ledger entry is appended for whatever `allowance_remaining` still
    stands, with a `reason` naming the cycle end, skipped when that figure is zero. Then
    `cycle_index` increments by one and `cycle_start_date` is set to the previous
    `cycle_end_date`, `next_service_date` is recomputed under the anchored variant, a `GRANTED`
    entry for `included_items_this_cycle` is appended with a `reason` naming the cycle opening
    — skipped when that figure is zero — `allowance_remaining` is set to
    `included_items_this_cycle`, and `skip_count_this_cycle` resets to 0."
    PRD 3.2: "The derived `cycle_end_date` is always the `cycle_start_date` plus 30 days and
    is the *exclusive* upper bound of the cycle — a clock sitting exactly on `cycle_end_date`
    is already outside the cycle."

    Design: Corner/state_machines/advance_cycle_expires_unused_allowance_and_regrants_it
    """
    _account, _tier, subscription = _account_with_subscription(anchor_date="2026-05-01")
    set_clock("2026-05-31T00:00:00Z")

    advanced = validate_success(
        api_client.advance_subscription_cycle(subscription["id"], ADMIN))
    assert advanced["cycle_index"] == 2
    assert advanced["cycle_start_date"] == "2026-05-31"
    assert advanced["cycle_end_date"] == "2026-06-30"
    assert advanced["allowance_remaining"] == 2
    assert advanced["skip_count_this_cycle"] == 0
    assert advanced["next_service_date"] == "2026-06-26"

    entries = list_allowance_entries(subscription["id"])
    assert len(entries) == 3, f"expected three ledger rows, got {len(entries)}"
    assert [entry["kind"] for entry in entries] == ["GRANTED", "EXPIRED", "GRANTED"]


def test_resume_reanchors_the_series_a_full_interval_out():
    """PRD 3.2: "Under the **re-anchored** variant — used on resume from pause and on a
    cadence change, both of which first reset `anchor_date` to the logical clock's date —
    `next_service_date` is the candidate for the smallest whole multiple of at least *one*, so
    the series always lands a full interval out even though the freshly reset anchor would
    itself have qualified under the anchored variant."
    PRD 3.2: "It re-anchors `anchor_date` to the logical clock's date, increments `cycle_index`
    by one and sets `cycle_start_date` to that same date, appends a `GRANTED` ledger entry for
    `included_items_this_cycle` with a `reason` naming the resume — again skipped when that
    number is zero — sets `allowance_remaining` to `included_items_this_cycle`, resets
    `skip_count_this_cycle` to 0, computes `next_service_date` under the re-anchored variant,
    and clears `paused_at` back to null."

    Design: Corner/calculations/resume_reanchors_next_service_date_one_full_interval_out
    """
    account, _tier, subscription = _account_with_subscription(cadence="WEEKLY",
                                                              anchor_date="2026-05-01")
    owner = make_account_owner_headers(account["id"])
    assert subscription["next_service_date"] == "2026-05-01"
    validate_success(api_client.pause_subscription(subscription["id"], owner))

    resumed = validate_success(api_client.resume_subscription(subscription["id"], owner))
    assert resumed["status"] == "ACTIVE"
    assert resumed["anchor_date"] == "2026-05-01"
    assert resumed["next_service_date"] == "2026-05-08"
    assert resumed["cycle_index"] == 2
    assert resumed["cycle_start_date"] == "2026-05-01"
    assert resumed["allowance_remaining"] == 8
    assert resumed["paused_at"] is None


def test_second_live_subscription_for_one_account_is_refused():
    """PRD 3.2: "It succeeds only if the account is `ACTIVE`, the account has no other
    subscription in `ACTIVE` or `PAUSED` — a second live one is
    `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION` — and the requested cadence is a member of the plan
    tier's `allowed_cadences`."
    PRD 2.6 rung 44: "The account has no other subscription whose `status` is `ACTIVE` or
    `PAUSED`. Otherwise `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION` (409). Applies to subscription
    creation; pre-empts rungs 45–57."

    Design: Corner/validations/second_live_subscription_for_one_account_is_refused
    """
    account, tier, subscription = _account_with_subscription()

    response = api_client.create_subscription(
        {"account_id": account["id"], "plan_tier_id": tier["id"], "cadence": "WEEKLY",
         "anchor_date": "2026-06-01"}, make_account_owner_headers(account["id"]))
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_SUBSCRIPTION.value, 409)
    assert read_subscription(subscription["id"])["cadence"] == "MONTHLY"


def test_cancelled_subscription_cannot_back_a_new_request():
    """PRD 3.3: "When a `subscription_id` is supplied it must not name a `CANCELLED`
    subscription; that is `ERR_SUBSCRIPTION_NOT_ACTIVE`."
    PRD 3.2: "From `ACTIVE`, an `EXPIRED` ledger entry is appended for the standing
    `allowance_remaining` with a `reason` naming the cancellation — skipped when it is already
    zero — then `allowance_remaining` is set to 0 and `next_service_date` to null."

    Design: Corner/validations/cancelled_subscription_cannot_back_a_new_request
    """
    account, _tier, subscription = _account_with_subscription()
    owner = make_account_owner_headers(account["id"])
    validate_success(api_client.cancel_subscription(subscription["id"], owner))

    response = api_client.create_service_request(
        {"account_id": account["id"], "channel": "VAN_ROUTE", "requested_date": "2026-05-01",
         "subscription_id": subscription["id"]}, owner)
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, 409)

    reread = read_subscription(subscription["id"])
    assert reread["status"] == "CANCELLED"
    assert reread["allowance_remaining"] == 0
    assert reread["next_service_date"] is None


def test_skip_and_cadence_change_are_both_refused_inside_the_48_hour_window():
    """PRD 3.2: "**Skipping.** A customer may skip the next standing visit while the
    subscription is `ACTIVE`, provided `next_service_date` is not null and the logical clock is
    at least 48 hours before midnight UTC at the start of that date; exactly 48 hours before
    passes, and anything later is `ERR_SKIP_WINDOW_CLOSED`."
    PRD 3.2: "requires the logical clock to be at least 48 hours before midnight UTC at the
    start of the current `next_service_date` — a late change is `ERR_CADENCE_CHANGE_TOO_LATE`"
    PRD 3.2: "Note that the skip window and the cadence-change window use the same 48-hour
    rule against the same date but report different codes, because they are different rungs."

    Design: Corner/validations/skip_and_cadence_change_are_both_refused_inside_the_window
    """
    account, _tier, subscription = _account_with_subscription(anchor_date="2026-05-02")
    owner = make_account_owner_headers(account["id"])

    validate_error(api_client.skip_subscription(subscription["id"], owner),
                   ApiErrorId.ERR_SKIP_WINDOW_CLOSED.value, 409)
    validate_error(api_client.change_subscription_cadence(
        subscription["id"],
        {"cadence": "WEEKLY", "expected_subscription_version": subscription["version"]}, owner),
        ApiErrorId.ERR_CADENCE_CHANGE_TOO_LATE.value, 409)

    reread = read_subscription(subscription["id"])
    assert reread["next_service_date"] == "2026-05-02"
    assert reread["cadence"] == "MONTHLY"
    assert reread["skip_count_this_cycle"] == 0


def test_second_cadence_change_carrying_the_original_version_is_stale():
    """PRD 2.7: "Changing a subscription's cadence requires `expected_subscription_version`,
    carrying the caller's last observed `version` of the target `Subscription`. A mismatch is
    rejected with `ERR_STALE_VERSION` (HTTP 412). A later cadence change legitimately supersedes
    an earlier one, so nothing about the state forbids it; the version check pins the allowance
    and fee the caller believed they were re-anchoring from."
    PRD 3.2: "The **effective monthly fee** is the plan tier's `monthly_fee_cents` multiplied
    by the cadence's fee multiplier and then rounded half up to a whole number of cents; the
    multiplier is 1.75 for `WEEKLY`, 1.25 for `BIWEEKLY` and 1.00 for `MONTHLY`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_the_second_cadence_change
    """
    account, _tier, subscription = _account_with_subscription()
    owner = make_account_owner_headers(account["id"])
    original_version = subscription["version"]
    first = validate_success(api_client.change_subscription_cadence(
        subscription["id"],
        {"cadence": "WEEKLY", "expected_subscription_version": original_version}, owner))
    assert first["cadence"] == "WEEKLY"

    response = api_client.change_subscription_cadence(
        subscription["id"],
        {"cadence": "BIWEEKLY", "expected_subscription_version": original_version}, owner)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    reread = read_subscription(subscription["id"])
    assert reread["cadence"] == "WEEKLY"
    assert reread["effective_monthly_fee_cents"] == 21000
    assert reread["included_items_this_cycle"] == 8
    assert reread["allowance_remaining"] == 8


def _subscription_visit_invoiced():
    """A delivered subscriber visit whose DRAFT invoice consumed one allowance unit."""
    world = build_config()
    tier = create_plan_tier(included_items_per_cycle=2)
    subscription = create_subscription(world["account"]["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")],
                                   subscription_id=subscription["id"])
    route_to_bench(world, request["id"])
    work_and_deliver(world, request["id"], [items[0]["id"]], ["ROUTINE_HONE"])
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    return world, subscription, request, items[0], invoice


def test_voiding_an_invoice_restores_the_allowance_it_consumed():
    """PRD 3.10: "Voiding returns every covered service request `INVOICED → UNBILLED` and
    writes an allowance ledger entry of kind `RESTORED` for each unit the invoice had consumed,
    raising the subscription's `allowance_remaining` back by that count."
    PRD 2.10: "Creating an invoice and then voiding it writes restoring entries that return
    `allowance_remaining` to its pre-invoice value."

    Design: Difficulty/compensating_invariant/allowance_ledger_balances_after_consume_then_void
    """
    _world, subscription, request, item, invoice = _subscription_visit_invoiced()
    assert read_subscription(subscription["id"])["allowance_remaining"] == 1

    voided = void_invoice(invoice["id"])
    assert voided["status"] == "VOID"
    assert read_subscription(subscription["id"])["allowance_remaining"] == 2
    assert read_request(request["id"])["billing_status"] == "UNBILLED"
    assert read_item(item["id"])["allowance_applied"] is False


def test_void_leaves_a_balanced_allowance_ledger_and_no_outstanding_money():
    """PRD 2.10: "For each subscription and each `cycle_index`, the sum of `quantity` over
    `GRANTED` entries, minus the sum over `CONSUMED` entries, minus the sum over `EXPIRED`
    entries, plus the sum over `RESTORED` entries, equals that subscription's
    `allowance_remaining`, evaluated over the current cycle."
    PRD 3.10: "when it was still `DRAFT`, no balance movement is needed because a draft never
    contributed."

    Design: Difficulty/compensating_invariant/allowance_ledger_balances_after_consume_then_void
    """
    world, subscription, _request, _item, invoice = _subscription_visit_invoiced()

    void_invoice(invoice["id"])

    entries = list_allowance_entries(subscription["id"])
    assert len(entries) == 3, f"expected GRANTED, CONSUMED and RESTORED rows, got {entries}"
    assert sorted(entry["kind"] for entry in entries) == ["CONSUMED", "GRANTED", "RESTORED"]
    reread = read_subscription(subscription["id"])
    assert_allowance_ledger_balances(entries, reread["allowance_remaining"],
                                     reread["cycle_index"])
    assert read_invoice(invoice["id"])["status"] == "VOID"
    assert read_account(world["account"]["id"])["outstanding_balance_cents"] == 0
