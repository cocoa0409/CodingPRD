"""Whole-endpoint round trips: paging, acknowledgement, ledger reach, closes."""

from test_helpers import (
    LINES_FOUR_1500,
    MONDAY_NOON,
    TEST_USERS,
    ApiErrorId,
    acknowledge_export,
    activate_rule,
    api_client,
    assert_expense_export,
    confirm_order,
    create_group,
    create_program,
    deliver_order,
    draft_order,
    draft_rule,
    final_close,
    generate_export,
    grace_close,
    order_line,
    place_order,
    place_order_raw,
    raise_claim,
    read_claim_refund_entries,
    read_employee,
    read_group,
    read_imputed_records,
    read_order,
    read_order_refund_entries,
    read_period,
    read_program,
    resolve_claim,
    resolve_claim_payload,
    settle_claim,
    setup_confirmed_order,
    setup_delivered_order,
    setup_resolved_claim,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLATFORM = TEST_USERS["platform_admin_headers"]
_PROGRAM = TEST_USERS["program_admin_headers"]
_DRAFTER = TEST_USERS["controller_drafter_headers"]
_APPROVER = TEST_USERS["controller_approver_headers"]
_RESOLVER = TEST_USERS["controller_resolver_headers"]


def _deliver(order, ns):
    return deliver_order(confirm_order(order, ns.restaurant), ns.restaurant)


def test_a_program_round_trips_through_create_read_patch_and_group_paging():
    """Two selectors are edited, three stay at their defaults, groups page 2-then-1.

    PRD §3.1: "`max_delivery_radius_km` is the program-wide radius ceiling in
    kilometres, measured from the delivery dock; it is optional, defaults to 8.0,
    and must be greater than 0 and at most 50.0."

    PRD §3.1: "`forecast_basis` selects the forecasting variant and defaults to
    `COMMITMENT`, the alternative being `RUN_RATE`."

    PRD §2.12: "Editing a program's policy selectors mutates the program row —
    bumping its `version` by 1 and refreshing `updated_at` — and recomputes nothing.
    No historical order, imputed record, or export is re-derived."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the number of items
    matching the filters before pagination is applied and `has_more` indicates
    whether items remain beyond the current page."

    Design: Corner/endpoints/program_create_read_patch_and_paginated_group_listing_round_trip
    """
    program = create_program()

    before = read_program(program["id"])
    assert before["max_delivery_radius_km"] == 8.0
    assert before["taxable_benefit_method"] == "DE_MINIMIS_EXCLUSION"
    assert before["rollover_policy"] == "CAPPED_PCT"
    assert before["rollover_cap_pct"] == 0.25
    assert before["forecast_basis"] == "COMMITMENT"
    assert before["program_spent_cents"] == 0
    assert before["program_reserved_cents"] == 0
    assert before["mtd_employer_captured_cents"] == 0
    assert before["version"] == 1

    patched = validate_success(
        api_client.patch_meal_program(
            program["id"],
            {"forecast_basis": "RUN_RATE", "max_delivery_radius_km": 12.0},
            _PLATFORM,
        )
    )
    assert patched["forecast_basis"] == "RUN_RATE"
    assert patched["max_delivery_radius_km"] == 12.0

    after = read_program(program["id"])
    assert after["forecast_basis"] == "RUN_RATE"
    assert after["max_delivery_radius_km"] == 12.0
    assert after["version"] == 2, "the edit bumps the program version by exactly 1"
    assert after["taxable_benefit_method"] == "DE_MINIMIS_EXCLUSION", (
        "an unmentioned selector keeps its default"
    )
    assert after["rollover_policy"] == "CAPPED_PCT"
    assert after["rollover_cap_pct"] == 0.25

    create_group(program["id"], name="Engineering", headcount_planned=3)
    interns = create_group(program["id"], name="Interns", headcount_planned=2)
    create_group(program["id"], name="Sales", headcount_planned=4)

    first_page, first_meta = validate_paginated(
        api_client.list_employee_groups(
            program["id"], _PROGRAM, params={"limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_employee_groups(
            program["id"], _PROGRAM, params={"limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    read_interns = read_group(interns["id"])
    assert read_interns["name"] == "Interns"
    assert read_interns["headcount_planned"] == 2
    assert read_interns["version"] == 1
    assert read_interns["active_rule_count"] == 0


def test_acknowledging_an_export_is_one_shot_and_a_failed_one_never_qualifies():
    """July is empty and lands in FAILED; August is acknowledged exactly once.

    PRD §3.9: "An empty bucket is not a zero-valued success: when `receipt_count`
    is 0 the export is created with status `FAILED` instead of `GENERATED`."

    PRD §3.9: "Downstream acceptance is recorded by acknowledging a `GENERATED`
    export, which moves it `GENERATED → ACKNOWLEDGED`, increments its `version` by 1,
    and makes it immutable. `ACKNOWLEDGED` and `FAILED` are both terminal, so a
    failed export can never be acknowledged and reports `ERR_INVALID_STATE`. Exports
    may be listed and filtered by `tax_month` and by `status`."

    Design: Corner/endpoints/expense_export_acknowledge_is_a_one_shot_action_and_a_failed_export_cannot_be_acknowledged
    """
    ns = setup_delivered_order()
    assert ns.order["employer_covered_cents"] == 1787
    assert ns.order["admin_fee_cents"] == 89
    assert ns.order["taxable_cents"] == 0

    failed = generate_export(ns.program["id"], tax_month="2026-07")
    assert_expense_export(failed)
    assert failed["status"] == "FAILED"
    assert failed["receipt_count"] == 0
    assert failed["employer_gross_cents"] == 0
    assert failed["net_of_refunds_cents"] == 0

    validate_error(
        api_client.acknowledge_expense_export(failed["id"], _DRAFTER),
        ApiErrorId.ERR_INVALID_STATE,
    )

    generated = generate_export(ns.program["id"], tax_month="2026-08")
    assert generated["status"] == "GENERATED"
    assert generated["receipt_count"] == 1
    assert generated["employer_gross_cents"] == 1787
    assert generated["employer_refund_cents"] == 0
    assert generated["net_of_refunds_cents"] == 1787
    assert generated["admin_fee_total_cents"] == 89
    assert generated["imputed_total_cents"] == 0
    assert generated["version"] == 1

    acknowledged = acknowledge_export(generated["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["version"] == 2

    validate_error(
        api_client.acknowledge_expense_export(generated["id"], _DRAFTER),
        ApiErrorId.ERR_INVALID_STATE,
    )

    rows, meta = validate_paginated(
        api_client.list_expense_exports(
            ns.program["id"], _DRAFTER, params={"status": "FAILED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == failed["id"]


def test_a_settled_claim_writes_rows_reachable_from_the_order_and_the_claim():
    """The whole 6,974-cent total is credited back as 2,500 plus 4,474.

    PRD §3.8: "Under `PROPORTIONAL`, the credit is split by the original charge
    ratio: `employee_refund_cents` is `approved_cents` multiplied by
    `employee_card_cents` and divided by `gross_total_cents`, rounded half-up to a
    whole cent, and `employer_credit_cents` is `approved_cents` minus that figure."

    PRD §3.8: "Settlement appends one or two `RefundLedgerEntry` rows with `reason`
    of `CLAIM_SETTLEMENT` and `credit_claim_id` naming the claim: an
    `EMPLOYER_CREDIT` entry for `employer_credit_cents` and an
    `EMPLOYEE_CARD_REFUND` entry for `employee_refund_cents`, each written only when
    its amount is greater than 0."

    PRD §3.8: "The ledger entries written against an order, and those written by a
    particular claim's settlement, are both readable and may be filtered by
    `direction` and by `reason`."

    PRD §3.8: "When that cumulative refund equals `gross_total_cents` exactly, the
    order moves to `REFUNDED` — from `CAPTURED` directly if this is the first
    settlement, or from `PARTIALLY_REFUNDED` if earlier ones came first — and
    `net_charged_cents` becomes 0."

    Design: Corner/endpoints/settled_refund_entries_are_reachable_from_both_the_order_and_the_claim
    """
    ns = setup_resolved_claim(
        routing_basis="PROPORTIONAL",
        claim_overrides={"claim_type": "NEVER_DELIVERED", "claimed_cents": 6974},
        order_overrides={"lines": LINES_FOUR_1500},
    )
    assert ns.order["covered_base_cents"] == 6974
    assert ns.order["employer_covered_cents"] == 2500
    assert ns.order["employee_card_cents"] == 4474
    assert ns.order["gross_total_cents"] == 6974

    assert ns.claim["status"] == "ROUTED_PROPORTIONAL"
    assert ns.claim["approved_cents"] == 6974
    assert ns.claim["employer_credit_cents"] == 2500
    assert ns.claim["employee_refund_cents"] == 4474

    settled = settle_claim(ns.claim)
    assert settled["status"] == "SETTLED"

    order = read_order(ns.order["id"])
    assert order["settlement_status"] == "REFUNDED"
    assert order["net_charged_cents"] == 0

    from_order = read_order_refund_entries(order["id"])
    assert len(from_order) == 2
    for entry in from_order:
        assert entry["credit_claim_id"] == ns.claim["id"]
        assert entry["reason"] == "CLAIM_SETTLEMENT"
        assert entry["order_id"] == order["id"]

    from_claim = read_claim_refund_entries(ns.claim["id"])
    assert len(from_claim) == 2
    assert sorted(e["id"] for e in from_claim) == sorted(e["id"] for e in from_order), (
        "both endpoints expose the same two immutable rows"
    )

    employer_side = read_order_refund_entries(
        order["id"], direction="EMPLOYER_CREDIT"
    )
    assert len(employer_side) == 1
    assert employer_side[0]["amount_cents"] == 2500

    employee_side = read_order_refund_entries(
        order["id"], direction="EMPLOYEE_CARD_REFUND"
    )
    assert len(employee_side) == 1
    assert employee_side[0]["amount_cents"] == 4474

    assert employer_side[0]["amount_cents"] + employee_side[0]["amount_cents"] == 6974


def test_the_close_mode_decides_whether_the_period_pauses_or_carves_its_rollover():
    """GRACE moves no cents; FINAL splits 48,213 into 12,500 and 35,713.

    PRD §3.9: "Mode `GRACE` moves the period `OPEN → GRACE`, increments its
    `version` by 1, and does exactly one thing: it stops new placements while
    leaving in-flight `PLACED` and `CONFIRMED` orders free to be confirmed and
    delivered."

    PRD §3.9: "Under `CAPPED_PCT`, the cap is `allocated_cents` multiplied by
    `rollover_cap_pct`, rounded half-up to a whole cent, and `rollover_out_cents` is
    the smaller of the unused amount and that cap."

    PRD §3.9: "`forfeited_cents` is then the unused amount minus
    `rollover_out_cents`, and `available_cents` is driven to 0, which restores the
    partition identity of §2.7 exactly."

    PRD §3.9: "A final close also increments the period's `version` by 1,
    recomputes the program's `program_reserved_cents`, and cascades to payroll: every
    `ImputedIncomeRecord` belonging to that period's employee whose `tax_month`
    equals the period's `period_month` and whose status is `ACCRUING` moves
    `ACCRUING → LOCKED`."

    Design: Corner/endpoints/close_mode_decides_whether_the_period_pauses_or_computes_its_rollover
    """
    ns = setup_delivered_order()
    assert ns.program["rollover_policy"] == "CAPPED_PCT"
    assert ns.program["rollover_cap_pct"] == 0.25

    paused = grace_close(ns.period["id"])
    assert paused["status"] == "GRACE"
    assert paused["rollover_out_cents"] == 0
    assert paused["forfeited_cents"] == 0

    after_grace = read_period(ns.period["id"])
    assert after_grace["spent_cents"] == 1787
    assert after_grace["reserved_cents"] == 0
    assert after_grace["available_cents"] == 48213, "GRACE carves nothing"

    validate_error(
        api_client.close_benefit_period(
            ns.period["id"], {"mode": "GRACE"}, _PROGRAM
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    closed = final_close(ns.period["id"])
    assert closed["status"] == "CLOSED"
    assert closed["rollover_out_cents"] == 12500, "25 percent of the 50,000 allocation"
    assert closed["forfeited_cents"] == 35713
    assert closed["available_cents"] == 0
    assert closed["rollover_out_cents"] + closed["forfeited_cents"] == 48213

    records = [
        record
        for record in read_imputed_records(ns.employee["id"])
        if record["tax_month"] == "2026-08"
    ]
    assert len(records) == 1
    assert records[0]["status"] == "LOCKED", "the final close cascaded into payroll"


def test_the_deliver_response_and_the_reads_taken_right_after_it_already_agree():
    """No retry is needed: the capture and every rollup are visible at once.

    PRD §3.7: "On success, `delivered_at` is stamped with the logical clock,
    `net_charged_cents` is set to `gross_total_cents`, and `employer_net_cents` is set
    to `employer_covered_cents`."

    PRD §3.7: "If the employee has no `ImputedIncomeRecord` for that `tax_month`,
    delivery creates one lazily, in status `ACCRUING`, with its `employee_id` and
    `tax_month` set and its `method` pinned from the program's
    `taxable_benefit_method` as it reads at that moment."

    PRD §3.7: "Finally the program rollups `program_spent_cents`,
    `program_reserved_cents`, and `mtd_employer_captured_cents` are all recomputed."

    Design: Corner/consistency_model/a_single_deliver_response_and_the_immediate_follow_up_reads_already_agree
    """
    ns = setup_confirmed_order()
    assert ns.order["fulfillment_status"] == "CONFIRMED"
    assert read_period(ns.period["id"])["reserved_cents"] == 1787

    delivered = deliver_order(ns.order, ns.restaurant)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["settlement_status"] == "CAPTURED"
    assert delivered["employer_net_cents"] == 1787
    assert delivered["net_charged_cents"] == 1787
    assert delivered["admin_fee_cents"] == 89

    period = read_period(ns.period["id"])
    assert period["reserved_cents"] == 0
    assert period["spent_cents"] == 1787
    assert period["available_cents"] == 48213

    program = read_program(ns.program["id"])
    assert program["program_spent_cents"] == 1787
    assert program["program_reserved_cents"] == 0
    assert program["mtd_employer_captured_cents"] == 1787

    records = read_imputed_records(ns.employee["id"])
    assert len(records) == 1, "the monthly bucket was created by this very delivery"
    assert records[0]["tax_month"] == "2026-08"
    assert records[0]["status"] == "ACCRUING"
    assert records[0]["gross_employer_paid_cents"] == 1787
    assert records[0]["taxable_cents"] == 0

    employee = read_employee(ns.employee["id"])
    assert employee["ytd_imputed_cents"] == 0
    assert employee["tax_treatment_flag"] == "NONE"


def test_each_of_the_three_version_gates_refuses_its_stale_read_then_accepts():
    """Period, order and group each answer 412 once, then take the fresh value.

    PRD §2.8: "If that value does not equal the period's current `version` at
    evaluation time, the placement is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP
    412). A successful placement increments the period's `version` by 1, so a client
    that read `available_cents` earlier and did not re-read it is refused rather than
    allowed to reserve budget against a balance that has since moved."

    PRD §2.8: "A `POST /credit-claims/{id}/resolve` request must carry
    `expected_order_version` holding the client's last observed `version` of the
    `Order` the claim addresses. A mismatch is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412). Delivery, cancellation, claim resolution,
    and claim settlement each increment the order's `version` by 1, so a routing
    split computed from a superseded employer/employee ratio can never be
    committed."

    PRD §2.8: "A `POST /budget-rules/{id}/activate` request must carry
    `expected_employee_group_version` holding the client's last observed `version` of
    the owning `EmployeeGroup`. A mismatch is rejected with
    `ERR_STALE_EMPLOYEE_GROUP_VERSION` (HTTP 412). A successful activation increments
    the group's `version` by 1, which is what preserves the
    at-most-one-active-rule-per-group invariant: a second activation issued against
    the pre-activation version is refused."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_their_stale_version_and_bump_exactly_one_on_success
    """
    ns = setup_scenario(rule_overrides={"daily_meal_limit": 3})
    assert read_group(ns.group["id"])["version"] == 2, "activation already moved it once"

    first_draft = draft_order(
        ns.employee, ns.period, ns.restaurant, ns.location,
        requested_delivery_at=MONDAY_NOON,
    )
    second_draft = draft_order(
        ns.employee, ns.period, ns.restaurant, ns.location,
        requested_delivery_at="2026-08-03T13:00:00Z",
    )

    first = place_order(first_draft, ns.employee, expected_version=1)
    order_version_read_too_early = first["version"]

    validate_error(
        place_order_raw(second_draft, ns.employee, expected_version=1),
        ApiErrorId.ERR_STALE_PERIOD_VERSION,
    )
    stale_view = read_period(ns.period["id"])
    assert stale_view["version"] == 2, "the refusal bumped nothing"
    assert stale_view["reserved_cents"] == 1787

    place_order(second_draft, ns.employee, expected_version=stale_view["version"])
    both_placed = read_period(ns.period["id"])
    assert both_placed["version"] == 3
    assert both_placed["reserved_cents"] == 3574
    assert both_placed["available_cents"] == 46426

    _deliver(first, ns)
    claim = raise_claim(
        first, ns.employee, claim_type="MISSING_ITEM", line_index=0, claimed_cents=1088
    )

    validate_error(
        api_client.resolve_credit_claim(
            claim["id"],
            resolve_claim_payload(order_version_read_too_early, approved_cents=1088),
            _RESOLVER,
        ),
        ApiErrorId.ERR_STALE_ORDER_VERSION,
    )
    assert read_order(first["id"])["settlement_status"] == "CAPTURED", (
        "the refused resolution moved no money"
    )

    resolved = resolve_claim(
        claim,
        first["id"],
        expected_order_version=read_order(first["id"])["version"],
        approved_cents=1088,
    )
    assert resolved["status"] == "ROUTED_EMPLOYEE_FIRST"
    assert resolved["employer_credit_cents"] == 1088
    assert resolved["employee_refund_cents"] == 0

    second_rule = draft_rule(ns.group["id"], monthly_allocation_cents=60000)
    validate_error(
        api_client.activate_budget_rule(
            second_rule["id"], {"expected_employee_group_version": 1}, _APPROVER
        ),
        ApiErrorId.ERR_STALE_EMPLOYEE_GROUP_VERSION,
    )
    assert read_group(ns.group["id"])["version"] == 2

    activated = activate_rule(
        second_rule["id"], ns.group["id"], expected_employee_group_version=2
    )
    assert activated["status"] == "ACTIVE"
    assert read_group(ns.group["id"])["version"] == 3

    rules, _meta = validate_paginated(
        api_client.list_budget_rules(ns.group["id"], _DRAFTER)
    )
    by_id = {rule["id"]: rule["status"] for rule in rules}
    assert by_id[ns.rule["id"]] == "SUPERSEDED"
    assert by_id[second_rule["id"]] == "ACTIVE"


def test_the_administration_rate_steps_down_only_after_100000_is_captured():
    """The order that lands exactly on 100,000 still pays five percent.

    PRD §3.5: "Its rate is selected from the program's
    `mtd_employer_captured_cents` *as it stands before this order's own employer share
    is added*: a month-to-date captured figure of at least 500,000 cents — five
    thousand dollars — prices at 3 percent, at least 100,000 cents but below 500,000
    prices at 4 percent, and below 100,000 cents prices at 5 percent."

    PRD §3.5: "Because the tier is read before the order's own contribution lands,
    the very order that crosses a tier boundary is still priced at the old, higher
    tier."

    PRD §2.7: "`mtd_employer_captured_cents` is the employer-covered cents captured
    by deliveries falling in the logical clock's current calendar month, and it is
    the tier input to the administration fee."

    PRD §3.7: "The employee's `ytd_imputed_cents` is then re-derived as the sum of
    `taxable_cents` across all of that employee's imputed-income records, and
    `tax_treatment_flag` is re-derived from it: the flag reads `W2_IMPUTED` once
    `ytd_imputed_cents` reaches the reporting threshold of 1,000 cents — ten dollars
    — and reads `NONE` below that."

    Design: Corner/cross_cutting_complexity_layers/admin_fee_rate_steps_down_once_month_to_date_capture_reaches_exactly_100000
    """
    ns = setup_scenario(
        group_overrides={"name": "Executives", "headcount_planned": 2},
        rule_overrides={
            "per_meal_cap_cents": 200000,
            "daily_meal_limit": 5,
            "monthly_allocation_cents": 500000,
        },
        employee_overrides={"full_name": "Cleo Noether", "email": "cleo@acme.test"},
    )

    banquet = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at=MONDAY_NOON,
            lines=[order_line("Board Banquet", 91609, 1)],
        ),
        ns.employee,
    )
    assert banquet["subtotal_cents"] == 91609
    assert banquet["tax_cents"] == 8016
    assert banquet["delivery_fee_cents"] == 0
    assert banquet["service_fee_cents"] == 375
    assert banquet["covered_base_cents"] == 100000
    assert banquet["employer_covered_cents"] == 100000
    assert banquet["employee_card_cents"] == 0
    assert banquet["admin_fee_cents"] == 5000, "5 percent, since MTD capture was 0"

    _deliver(banquet, ns)
    assert read_program(ns.program["id"])["mtd_employer_captured_cents"] == 100000

    lunch = place_order(
        draft_order(
            ns.employee,
            ns.period,
            ns.restaurant,
            ns.location,
            requested_delivery_at="2026-08-03T13:00:00Z",
        ),
        ns.employee,
    )
    assert lunch["employer_covered_cents"] == 1787
    assert lunch["admin_fee_cents"] == 71, "4 percent now; the 5 percent tier gave 89"

    _deliver(lunch, ns)

    employee = read_employee(ns.employee["id"])
    assert employee["ytd_imputed_cents"] == 98000, "98,000 above the floor, then 0"
    assert employee["tax_treatment_flag"] == "W2_IMPUTED"

    records = read_imputed_records(ns.employee["id"])
    assert len(records) == 1
    assert records[0]["method"] == "DE_MINIMIS_EXCLUSION"
    assert records[0]["gross_employer_paid_cents"] == 101787
    assert records[0]["taxable_cents"] == 98000
    assert records[0]["status"] == "ACCRUING"
