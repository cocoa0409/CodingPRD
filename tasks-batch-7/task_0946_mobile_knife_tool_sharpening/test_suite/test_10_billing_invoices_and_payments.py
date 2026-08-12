"""Invoices, the allowance plan, the tax rounding discipline and payments."""
from test_helpers import (
    ApiErrorId, CLERK,
    add_stop, api_client, arrive_stop, bench_intake, build_config, create_account,
    create_invoice, create_plan_tier, create_run, create_subscription, dispatch_run,
    find_draft_invoice, issue_invoice, list_invoice_lines,
    make_account_owner_headers, pickup, read_account, read_invoice, read_item, read_request,
    read_statement, read_subscription, route_to_bench, setup_cadence_upgrade_invoice,
    setup_delivered_van_visit, setup_paused_credit_invoice, stage_request, validate_error,
    validate_paginated, validate_success, void_invoice, work_and_deliver,
    assert_invoice, assert_invoice_line, assert_invoice_totals_consistent,
    assert_money_conservation, assert_payment,
)


def test_invoice_line_is_append_only_and_carries_no_version():
    """PRD 2.4: "Three entities are exceptions and carry only `id` and `created_at`, with no
    `updated_at` and no `version` at all: `InvoiceLine`, `Payment` and `AllowanceLedgerEntry`.
    These three are append-only ledger records — once written they are never modified, so a
    mutation counter would be meaningless on them."
    PRD 3.10: "Every line carries an `invoice_id`, a `source`, a human-readable `description`,
    a signed `amount_cents`, a `taxable` flag and a 1-based `sequence_index` recording its
    append order within the invoice."

    Design: Corner/entities/invoice_line_is_append_only_and_carries_no_version
    """
    _account, _subscription, invoice = setup_paused_credit_invoice()

    rows, _meta = validate_paginated(
        api_client.list_invoice_lines_of_invoice(invoice["id"], CLERK))
    assert len(rows) == 1, f"expected one proration line, got {len(rows)}"
    line = rows[0]
    assert_invoice_line(line)
    assert line["source"] == "PRORATION_CREDIT"
    assert line["amount_cents"] == -12000
    assert line["taxable"] is True
    assert line["sequence_index"] == 1
    assert "version" not in line

    reread = read_invoice(invoice["id"])
    assert reread["taxable_subtotal_cents"] == -12000
    assert reread["tax_cents"] == 0
    assert reread["total_cents"] == -12000


def test_tax_exempt_account_pays_no_tax_on_a_positive_invoice():
    """PRD 3.10: "`tax_cents` is 0 when the account is `tax_exempt`, and otherwise the greater
    of zero and `taxable_subtotal_cents`, multiplied by a service tax rate of 725 basis points
    and divided by 10000, rounded half up once"
    PRD 3.2: "Under the **cadence-change** variant, the line amount is the *difference* between
    the new effective monthly fee and the old one, multiplied by the same unused-days fraction
    over the same 30-day basis, again with a single half-up rounding of the whole product"

    Design: Corner/calculations/tax_exempt_account_pays_no_tax_on_a_positive_invoice
    """
    account, subscription, invoice = setup_cadence_upgrade_invoice(
        issue=False,
        account_kwargs={"name": "Civic Kitchens", "account_type": "COMMERCIAL",
                        "contact_email": "ops@civic.test", "tax_exempt": True})
    assert subscription["effective_monthly_fee_cents"] == 21000
    assert subscription["included_items_this_cycle"] == 8
    assert subscription["allowance_remaining"] == 8
    assert subscription["next_service_date"] == "2026-05-08"

    reread = read_invoice(invoice["id"])
    assert_invoice(reread)
    assert reread["taxable_subtotal_cents"] == 18300
    assert reread["tax_cents"] == 0
    assert reread["total_cents"] == 18300
    assert read_account(account["id"])["tax_exempt"] is True


def test_monthly_rollup_spends_the_allowance_across_the_whole_cycle():
    """PRD 3.10: "Under **monthly-rollup** billing the scope is every `COMPLETED`, `UNBILLED`
    service request of the account whose `completed_at` falls inside the invoice's
    `billing_period`, so the ranking is global across the whole cycle and the allowance lands
    on the dearest items of the period regardless of which visit produced them."
    PRD 3.10: "They are ranked by `final_gross_cents` descending with ties broken by
    `created_at` ascending, so the dearest item absorbs the allowance and the customer gets the
    most value out of it. K is the lesser of the number of candidate items and the
    subscription's `allowance_remaining`."
    PRD 3.10: "it carries exactly one subscription-fee line equal to the subscription's
    `effective_monthly_fee_cents` when the account has a subscription in `ACTIVE` or `PAUSED`."

    Design: Corner/calculations/monthly_rollup_spends_the_allowance_across_the_whole_cycle
    """
    world = build_config(specs=("CHEF_KNIFE", "SALON_SHEAR"), tech_certs=["SHEAR"],
                         account_kwargs={"billing_mode": "MONTHLY_ROLLUP"})
    tier = create_plan_tier(included_items_per_cycle=1)
    subscription = create_subscription(world["account"]["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    first, first_items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")],
                                       subscription_id=subscription["id"])
    second, second_items = stage_request(world, [("SALON_SHEAR", "ROUTINE_HONE")],
                                         subscription_id=subscription["id"])
    run = create_run(world["van"]["id"], world["tech"]["id"])
    stop_one = add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")
    stop_two = add_stop(run["id"], second["id"], sequence=2, arrival_window_start="10:00")
    dispatch_run(run["id"])
    for stop, request, items in ((stop_one, first, first_items),
                                 (stop_two, second, second_items)):
        arrive_stop(stop["id"], world["tech"]["id"])
        pickup(request["id"], world["tech"]["id"])
        bench_intake(request["id"], world["bench"]["id"], world["tech"]["id"])
        work_and_deliver(world, request["id"], [items[0]["id"]], ["ROUTINE_HONE"])

    invoice = create_invoice(world["account"]["id"], billing_period="2026-05")
    assert invoice["billing_mode"] == "MONTHLY_ROLLUP"
    assert invoice["taxable_subtotal_cents"] == 12765
    assert invoice["nontaxable_subtotal_cents"] == 0
    assert invoice["tax_cents"] == 925
    assert invoice["total_cents"] == 13690
    assert_invoice_totals_consistent(invoice)

    shear = read_item(second_items[0]["id"])
    chef = read_item(first_items[0]["id"])
    assert shear["allowance_applied"] is True
    assert shear["charged_service_cents"] == 0
    assert chef["allowance_applied"] is False
    assert chef["charged_service_cents"] == 765
    assert read_subscription(subscription["id"])["allowance_remaining"] == 0
    assert read_request(first["id"])["billing_status"] == "INVOICED"
    assert read_request(second["id"])["billing_status"] == "INVOICED"


def test_overpayment_is_refused_on_an_issued_invoice():
    """PRD 3.10: "The amount must be at least 1 and must not exceed the invoice's
    `amount_due_cents`, since the overpayment tolerance is 0 cents; an excess is
    `ERR_OVERPAYMENT`."
    PRD 2.6 rung 56: "The payment's `amount_cents` is at most the invoice's `amount_due_cents`
    plus an overpayment tolerance of 0 cents — which is to say, at most `amount_due_cents`
    exactly. Otherwise `ERR_OVERPAYMENT` (422)."

    Design: Corner/validations/overpayment_is_refused_on_an_issued_invoice
    """
    account, _subscription, invoice = setup_cadence_upgrade_invoice(issue=True)

    response = api_client.create_payment(
        invoice["id"],
        {"amount_cents": 19628, "method": "CARD",
         "expected_invoice_version": invoice["version"]},
        make_account_owner_headers(account["id"]))
    validate_error(response, ApiErrorId.ERR_OVERPAYMENT.value, 422)

    reread = read_invoice(invoice["id"])
    assert reread["amount_due_cents"] == 19627
    assert reread["amount_paid_cents"] == 0
    assert reread["status"] == "ISSUED"
    assert read_account(account["id"])["outstanding_balance_cents"] == 19627


def test_issued_credit_memo_cannot_be_paid():
    """PRD 3.10: "An invoice whose `amount_due_cents` has fallen below 1 — which is reachable
    on an issued credit memo whose credits outweigh its charges — is `ERR_INVOICE_NOT_PAYABLE`."
    PRD 2.6 rung 18: "The invoice's `status` is `ISSUED` or `PARTIALLY_PAID` and its
    `amount_due_cents` is at least 1. Otherwise `ERR_INVOICE_NOT_PAYABLE` (409)."

    Design: Corner/validations/credit_memo_cannot_be_paid
    """
    account, _subscription, draft = setup_paused_credit_invoice()
    invoice = issue_invoice(draft["id"])

    response = api_client.create_payment(
        invoice["id"],
        {"amount_cents": 100, "method": "CARD",
         "expected_invoice_version": invoice["version"]},
        make_account_owner_headers(account["id"]))
    validate_error(response, ApiErrorId.ERR_INVOICE_NOT_PAYABLE.value, 409)

    reread = read_invoice(invoice["id"])
    assert reread["status"] == "ISSUED"
    assert reread["taxable_subtotal_cents"] == -12000
    assert reread["tax_cents"] == 0
    assert reread["total_cents"] == -12000
    assert reread["amount_due_cents"] == -12000
    assert read_account(account["id"])["outstanding_balance_cents"] == -12000


def test_per_visit_account_billed_with_a_period_is_a_scope_mismatch():
    """PRD 3.10: "Under **per-visit** billing the body must supply `service_request_id` and
    must omit `billing_period`; the invoice covers exactly one `COMPLETED` service request and
    carries no subscription-fee line."
    PRD 2.6 rung 30: "A per-visit invoice supplies `service_request_id` and omits
    `billing_period`; a monthly-rollup invoice supplies `billing_period` and omits
    `service_request_id`. Otherwise `ERR_INVOICE_SCOPE_MISMATCH` (422)."

    Design: Corner/validations/per_visit_invoice_without_a_service_request_is_a_scope_mismatch
    """
    account = create_account(billing_mode="PER_VISIT")
    response = api_client.create_invoice(
        {"account_id": account["id"], "billing_period": "2026-05"}, CLERK)
    validate_error(response, ApiErrorId.ERR_INVOICE_SCOPE_MISMATCH.value, 422)


def test_rollup_invoice_with_nothing_to_bill_is_empty():
    """PRD 3.10: "An invoice that would be created with no lines at all is
    `ERR_EMPTY_INVOICE`."
    PRD 2.6 rung 55: "The invoice has at least one `InvoiceLine`. Otherwise
    `ERR_EMPTY_INVOICE` (409). Applies to invoice creation and to invoice issuing; pre-empts
    rungs 56–57."

    Design: Corner/validations/rollup_invoice_with_nothing_to_bill_is_empty
    """
    account = create_account(name="Quiet Cafe", zone_code="ZONE_E",
                             contact_email="ops@quiet.test", billing_mode="MONTHLY_ROLLUP")
    response = api_client.create_invoice(
        {"account_id": account["id"], "billing_period": "2026-05"}, CLERK)
    validate_error(response, ApiErrorId.ERR_EMPTY_INVOICE.value, 409)


def test_second_draft_invoice_for_one_account_is_refused():
    """PRD 3.10: "An account may hold only one invoice in `DRAFT` at a time — a second is
    `ERR_DUPLICATE_DRAFT_INVOICE` — and every request the new invoice would cover must be
    `UNBILLED`, or the creation is `ERR_DUPLICATE_INVOICE`."
    PRD 2.6 rung 47: "The account has no other invoice whose `status` is `DRAFT`. Otherwise
    `ERR_DUPLICATE_DRAFT_INVOICE` (409). Applies to invoice creation; pre-empts rungs 48–57."

    Design: Corner/validations/second_draft_invoice_for_one_account_is_refused
    """
    account, _subscription, _draft = setup_paused_credit_invoice(
        account_kwargs={"billing_mode": "MONTHLY_ROLLUP"})

    response = api_client.create_invoice(
        {"account_id": account["id"], "billing_period": "2026-05"}, CLERK)
    error = validate_error(response, ApiErrorId.ERR_DUPLICATE_DRAFT_INVOICE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_EMPTY_INVOICE.value


def test_invoicing_an_already_invoiced_visit_is_refused():
    """PRD 3.10: "An account may hold only one invoice in `DRAFT` at a time — a second is
    `ERR_DUPLICATE_DRAFT_INVOICE` — and every request the new invoice would cover must be
    `UNBILLED`, or the creation is `ERR_DUPLICATE_INVOICE`."
    PRD 2.6 rung 48: "Every service request the invoice would cover has `billing_status`
    `UNBILLED`. Otherwise `ERR_DUPLICATE_INVOICE` (409). Applies to invoice creation;
    pre-empts rungs 49–57."

    Design: Corner/validations/invoicing_an_already_invoiced_visit_is_refused
    """
    world, request, _items = setup_delivered_van_visit()
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    issue_invoice(invoice["id"])

    response = api_client.create_invoice(
        {"account_id": world["account"]["id"], "service_request_id": request["id"]}, CLERK)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_INVOICE.value, 409)

    reread = read_invoice(invoice["id"])
    assert reread["total_cents"] == 965
    assert reread["status"] == "ISSUED"
    assert read_request(request["id"])["billing_status"] == "INVOICED"


def test_account_statement_reports_the_money_and_allowance_position():
    """PRD 3.1: "A read-only statement pulls the account's money and allowance position
    together in one place: it reports the `account_id`, the live `outstanding_balance_cents`, a
    `draft_invoice_count` of that account's invoices currently in `DRAFT`, an
    `unbilled_request_count` of that account's service requests whose `billing_status` is
    `UNBILLED`, and the `allowance_remaining` of the account's subscription — zero when the
    account has none."

    Design: Corner/endpoints/account_statement_reports_the_computed_money_and_allowance_position
    """
    account, _subscription, _invoice = setup_cadence_upgrade_invoice(issue=True)

    statement = read_statement(account["id"])
    assert statement["account_id"] == account["id"]
    assert statement["outstanding_balance_cents"] == 19627
    assert statement["draft_invoice_count"] == 0
    assert statement["unbilled_request_count"] == 0
    assert statement["allowance_remaining"] == 8


def test_second_partial_payment_carrying_the_pre_payment_version_is_stale():
    """PRD 2.7: "Applying a payment to an invoice requires `expected_invoice_version`,
    carrying the payer's last observed `version` of the target `Invoice`. A mismatch with the
    invoice's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Partial
    payments legitimately stack, so a second sequential payment against the same `ISSUED` or
    `PARTIALLY_PAID` invoice would otherwise simply succeed; the version check is what pins the
    payer's view of `amount_due_cents`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_the_second_partial_payment
    """
    account, _subscription, invoice = setup_cadence_upgrade_invoice(issue=True)
    owner = make_account_owner_headers(account["id"])
    original_version = invoice["version"]
    first = validate_success(api_client.create_payment(
        invoice["id"],
        {"amount_cents": 1000, "method": "CARD",
         "expected_invoice_version": original_version}, owner), 201)
    assert_payment(first)

    response = api_client.create_payment(
        invoice["id"],
        {"amount_cents": 500, "method": "CARD",
         "expected_invoice_version": original_version}, owner)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    reread = read_invoice(invoice["id"])
    assert reread["status"] == "PARTIALLY_PAID"
    assert reread["amount_paid_cents"] == 1000
    assert reread["amount_due_cents"] == 18627
    assert first["resulting_invoice_status"] == "PARTIALLY_PAID"
    assert read_account(account["id"])["outstanding_balance_cents"] == 18627


def _rush_subscriber_visit_invoiced():
    """A RUSH subscriber visit carrying a 3200 shear and a 2025 re-tipped chef knife."""
    world = build_config(specs=("SALON_SHEAR", "CHEF_KNIFE"), tech_certs=["SHEAR"],
                         account_kwargs={"name": "Shear Bliss Salon", "account_type": "SALON",
                                         "contact_email": "front@shearbliss.test",
                                         "billing_mode": "PER_VISIT"})
    tier = create_plan_tier(included_items_per_cycle=1)
    subscription = create_subscription(world["account"]["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-06-01")
    request, items = stage_request(
        world, [("SALON_SHEAR", "ROUTINE_HONE"), ("CHEF_KNIFE", "RE_TIP")],
        subscription_id=subscription["id"], priority="RUSH")
    route_to_bench(world, request["id"])
    work_and_deliver(world, request["id"], [item["id"] for item in items],
                     ["ROUTINE_HONE", "RE_TIP"])
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    return world, subscription, items, invoice


def test_rush_floor_beats_twenty_percent_of_an_allowance_absorbed_base():
    """PRD 3.10: "*Step four.* If the service request's `priority` is `RUSH`, the surcharge is
    added to the base. The surcharge is the greater of 500 cents and 20 percent of the base
    rounded half up — so a rush on a cheap blade costs a flat 500 cents and a rush on an
    expensive one costs a fifth of its price. The surcharge is computed on the *post-allowance,
    post-discount* base, which means an item the allowance absorbed still costs 500 cents to
    rush, since 20 percent of zero is zero and the floor wins."
    PRD 3.10: "*Step three.* Each item's base amount is then determined by exactly one of three
    mutually exclusive branches. If `allowance_applied` is true, the base is 0. Otherwise, if
    the item's service request names a `subscription_id` whose subscription is in `ACTIVE`, the
    base is `final_gross_cents` multiplied by one minus the plan tier's `overage_discount_pct`,
    rounded half up to whole cents. Otherwise the base is `final_gross_cents` unchanged."

    Design: Difficulty/combinatorial_formula/rush_floor_over_overage_discounted_base_mode_a
    """
    _world, _subscription, items, _invoice = _rush_subscriber_visit_invoiced()

    shear = read_item(items[0]["id"])
    chef = read_item(items[1]["id"])
    assert shear["allowance_applied"] is True
    assert shear["charged_service_cents"] == 500
    assert shear["part_fee_cents"] == 0
    assert chef["allowance_applied"] is False
    assert chef["final_gross_cents"] == 2025
    assert chef["charged_service_cents"] == 2221
    assert chef["part_fee_cents"] == 400


def test_rush_invoice_totals_split_taxable_service_from_non_taxable_parts():
    """PRD 3.10: "Taxability is fixed per kind and is not negotiable per line: `SERVICE`,
    `SUBSCRIPTION_FEE`, `PRORATION_CREDIT` and `WARRANTY_CREDIT` lines are taxable; `PART` and
    `LATE_FEE` lines are not."
    PRD 3.10: "`total_cents` is `taxable_subtotal_cents` plus `nontaxable_subtotal_cents` plus
    `tax_cents`; and `amount_due_cents` is `total_cents` minus `amount_paid_cents`."
    PRD 3.10: "Each of the first K items gets `allowance_applied` true and one allowance ledger
    entry of kind `CONSUMED` with `quantity` 1, a `reason` naming the invoicing, and its
    `request_item_id`; `allowance_remaining` decreases by exactly K."

    Design: Difficulty/combinatorial_formula/rush_floor_over_overage_discounted_base_mode_a
    """
    _world, subscription, _items, invoice = _rush_subscriber_visit_invoiced()

    reread = read_invoice(invoice["id"])
    assert reread["taxable_subtotal_cents"] == 2721
    assert reread["nontaxable_subtotal_cents"] == 400
    assert reread["tax_cents"] == 197
    assert reread["total_cents"] == 3318
    assert_invoice_totals_consistent(reread)
    assert read_subscription(subscription["id"])["allowance_remaining"] == 0


def _two_chef_knife_visit_invoiced():
    """A non-subscriber visit with two 900-cent routine hones, invoiced but not issued."""
    world, request, items = setup_delivered_van_visit(
        items=(("CHEF_KNIFE", "ROUTINE_HONE"), ("CHEF_KNIFE", "ROUTINE_HONE")))
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    return world, request, items, invoice


def test_tax_is_rounded_once_over_the_aggregate_taxable_subtotal():
    """PRD 3.10: "The single-rounding discipline of §2.8 applies here in its strictest form:
    the tax is computed once over the aggregate taxable subtotal and rounded once, never per
    line and summed."
    PRD 2.8: "Invoice tax is computed once over the aggregate taxable subtotal and rounded
    once; rounding the tax of each taxable line and summing those roundings is explicitly *not*
    the contract and produces different cents on multi-line invoices."

    Design: Difficulty/combinatorial_formula/invoice_tax_aggregate_rounding_not_per_line_mode_b
    """
    _world, _request, _items, invoice = _two_chef_knife_visit_invoiced()

    reread = read_invoice(invoice["id"])
    assert reread["taxable_subtotal_cents"] == 1800
    assert reread["tax_cents"] == 131, (
        "tax must be one half-up rounding of 725 basis points over the whole taxable subtotal")


def test_aggregate_tax_flows_into_the_invoice_total_and_amount_due():
    """PRD 3.10: "`total_cents` is `taxable_subtotal_cents` plus `nontaxable_subtotal_cents`
    plus `tax_cents`; and `amount_due_cents` is `total_cents` minus `amount_paid_cents`."
    PRD 2.10: "An invoice's `amount_due_cents` equals its `total_cents` minus its
    `amount_paid_cents`; its `amount_paid_cents` equals the sum of `amount_cents` over the
    `Payment` rows against it"

    Design: Difficulty/combinatorial_formula/invoice_tax_aggregate_rounding_not_per_line_mode_b
    """
    _world, _request, _items, invoice = _two_chef_knife_visit_invoiced()

    reread = read_invoice(invoice["id"])
    assert reread["nontaxable_subtotal_cents"] == 0
    assert reread["total_cents"] == 1931
    assert reread["amount_due_cents"] == 1931
    assert_money_conservation(reread)
    lines = list_invoice_lines(invoice["id"])
    assert [line["source"] for line in lines] == ["SERVICE", "SERVICE"]


def test_full_payment_settles_the_billing_axis_without_moving_fulfilment():
    """PRD 3.10: "A payment exactly equal to the amount due moves the invoice `ISSUED → PAID`
    or `PARTIALLY_PAID → PAID`, drives `amount_due_cents` to 0, decrements
    `outstanding_balance_cents` accordingly, increments `version`, and moves every service
    request covered by that invoice on its billing axis `INVOICED → SETTLED`."
    PRD 2.9: "A `ServiceRequest` carries a **fulfilment axis** in `status`, moving through
    `DRAFT`, `SUBMITTED`, `SCHEDULED`, `IN_SERVICE`, `COMPLETED` and `CANCELLED`, and, entirely
    independently on the very same row, a **billing axis** in `billing_status`, moving through
    `UNBILLED`, `INVOICED`, `SETTLED` and `CREDITED`."

    Design: Difficulty/non_linear_state_machine/service_request_parallel_axes_move_independently
    """
    world, request, _items, draft = _two_chef_knife_visit_invoiced()
    invoice = issue_invoice(draft["id"])
    validate_success(api_client.create_payment(
        invoice["id"],
        {"amount_cents": 1931, "method": "CARD",
         "expected_invoice_version": invoice["version"]},
        make_account_owner_headers(world["account"]["id"])), 201)

    reread = read_request(request["id"])
    assert reread["status"] == "COMPLETED"
    assert reread["billing_status"] == "SETTLED"


def test_full_payment_clears_the_invoice_and_the_account_balance():
    """PRD 3.10: "**Issuing** an invoice moves it `DRAFT → ISSUED`, requires at least one
    line, freezes all computed totals, and increments the account's `outstanding_balance_cents`
    by `amount_due_cents`."
    PRD 3.10: "Each payment records `applied_at` from the logical clock and the
    `resulting_invoice_status` the invoice landed in."

    Design: Difficulty/non_linear_state_machine/service_request_parallel_axes_move_independently
    """
    world, _request, _items, draft = _two_chef_knife_visit_invoiced()
    invoice = issue_invoice(draft["id"])
    assert read_account(world["account"]["id"])["outstanding_balance_cents"] == 1931

    payment = validate_success(api_client.create_payment(
        invoice["id"],
        {"amount_cents": 1931, "method": "CARD",
         "expected_invoice_version": invoice["version"]},
        make_account_owner_headers(world["account"]["id"])), 201)
    assert_payment(payment)
    assert payment["resulting_invoice_status"] == "PAID"

    reread = read_invoice(invoice["id"])
    assert reread["status"] == "PAID"
    assert reread["amount_paid_cents"] == 1931
    assert reread["amount_due_cents"] == 0
    assert_money_conservation(reread)
    assert read_account(world["account"]["id"])["outstanding_balance_cents"] == 0


def _paused_subscriber_visit():
    """A delivered subscriber visit whose subscription was paused before invoicing."""
    world = build_config()
    tier = create_plan_tier(included_items_per_cycle=0)
    subscription = create_subscription(world["account"]["id"], tier["id"], cadence="MONTHLY",
                                       anchor_date="2026-05-01")
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")],
                                   subscription_id=subscription["id"])
    route_to_bench(world, request["id"])
    work_and_deliver(world, request["id"], [items[0]["id"]], ["ROUTINE_HONE"])
    validate_success(api_client.pause_subscription(
        subscription["id"], make_account_owner_headers(world["account"]["id"])))
    credit_invoice = find_draft_invoice(world["account"]["id"])
    void_invoice(credit_invoice["id"])
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    return world, subscription, items[0], credit_invoice, invoice


def test_overage_discount_is_withheld_while_the_subscription_is_paused():
    """PRD 3.10: "Otherwise, if the item's service request names a `subscription_id` whose
    subscription is in `ACTIVE`, the base is `final_gross_cents` multiplied by one minus the
    plan tier's `overage_discount_pct`, rounded half up to whole cents. Otherwise the base is
    `final_gross_cents` unchanged."
    PRD 3.10: "Note what the middle branch means in practice: the overage discount is what a
    subscriber gets on items *beyond* their allowance, and it is unavailable to a subscriber
    whose subscription is `PAUSED` or `CANCELLED`."

    Design: Difficulty/cross_entity_state_dependency/overage_discount_withheld_because_subscription_is_paused
    """
    _world, subscription, item, _credit_invoice, _invoice = _paused_subscriber_visit()

    assert read_subscription(subscription["id"])["status"] == "PAUSED"
    reread = read_item(item["id"])
    assert reread["allowance_applied"] is False
    assert reread["charged_service_cents"] == 900
    assert reread["charged_service_cents"] != 765


def test_paused_subscriber_visit_is_taxed_on_the_undiscounted_service_line():
    """PRD 3.10: "`tax_cents` is 0 when the account is `tax_exempt`, and otherwise the greater
    of zero and `taxable_subtotal_cents`, multiplied by a service tax rate of 725 basis points
    and divided by 10000, rounded half up once"
    PRD 3.10: "`DRAFT → VOID` is available unconditionally; `ISSUED → VOID` is available only
    when `amount_paid_cents` is exactly 0 — a partly paid invoice cannot be voided."

    Design: Difficulty/cross_entity_state_dependency/overage_discount_withheld_because_subscription_is_paused
    """
    _world, _subscription, _item, credit_invoice, invoice = _paused_subscriber_visit()

    reread = read_invoice(invoice["id"])
    assert reread["taxable_subtotal_cents"] == 900
    assert reread["tax_cents"] == 65
    assert reread["total_cents"] == 965
    assert_invoice_totals_consistent(reread)
    assert read_invoice(credit_invoice["id"])["status"] == "VOID"
