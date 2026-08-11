"""Loaner issue, return, the inspection chain and the delivery cascade."""
from test_helpers import (
    ApiErrorId, ADMIN,
    api_client, approve_claim, assess_item, bench_intake, build_config, complete_work,
    create_claim, create_deli_slicer_spec, create_invoice, create_loaner_unit,
    deliver_request, find_draft_invoice, issue_invoice, issue_loaner,
    make_technician_headers, read_bench_day, read_item, read_loaner_issue,
    read_loaner_unit, return_loaner, route_to_bench, route_to_van, set_clock,
    stage_request, start_work, validate_success, validate_error, work_and_deliver,
    assert_loaner_issue, assert_loaner_unit, assert_loaner_unit_conservation,
    assert_same_instant,
)


def test_loaner_unit_for_an_ineligible_class_is_refused():
    """PRD 3.8: "A loaner unit is added to the rotation pool for a specific
    `item_class_spec_id` at a `grade` of `STANDARD` or `PREMIUM`, with a `cycle_ceiling` of at
    least one defaulting to 12; the referenced spec must have `loaner_eligible` true, or the
    creation is `ERR_LOANER_NOT_ELIGIBLE`."
    PRD 2.6 rung 29: "The referenced `ItemClassSpec` has `loaner_eligible` true. Otherwise
    `ERR_LOANER_NOT_ELIGIBLE` (422). Applies to loaner-unit creation and to loaner issue;
    pre-empts rungs 30–57."

    Design: Corner/validations/loaner_unit_for_an_ineligible_class_is_refused
    """
    spec = create_deli_slicer_spec()
    response = api_client.create_loaner_unit(
        {"item_class_spec_id": spec["id"], "grade": "STANDARD", "cycle_ceiling": 5}, ADMIN)
    validate_error(response, ApiErrorId.ERR_LOANER_NOT_ELIGIBLE.value, 422)


def test_loaner_issue_against_an_empty_pool_is_refused():
    """PRD 3.8: "An empty candidate pool is `ERR_LOANER_STOCK_EXHAUSTED`."
    PRD 2.6 rung 51: "The loaner candidate pool described in §3.8 is not empty. Otherwise
    `ERR_LOANER_STOCK_EXHAUSTED` (409). Applies to loaner issue; pre-empts rungs 52–57."

    Design: Corner/validations/loaner_issue_with_an_empty_pool_is_refused
    """
    world = build_config(with_van=False, with_bench=False)
    request, _items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")], submit=False)

    response = api_client.create_loaner_issue(
        {"service_request_id": request["id"],
         "item_class_spec_id": world["specs"]["CHEF_KNIFE"]["id"],
         "requested_grade": "PREMIUM"},
        make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_LOANER_STOCK_EXHAUSTED.value, 409)


def test_selector_substitutes_a_premium_unit_when_no_standard_is_in_stock():
    """PRD 3.8: "Candidates are ranked first by whether their grade exactly equals
    `requested_grade`, exact matches ahead of substitutes; then by grade rank ascending, so the
    cheapest acceptable substitute is used before a dearer one; then by `cycle_count`
    ascending, which is the rotation rule proper and puts the least-worn unit into service
    first; and finally by `created_at` ascending."
    PRD 3.8: "The chosen unit moves `IN_STOCK → ISSUED`; the issue record is born `OPEN`,
    records `loaner_unit_id`, stamps `issued_at` from the logical clock, derives `due_at` as
    `issued_at` plus 14 days, and sets `substituted` true exactly when the issued unit's grade
    differs from `requested_grade`."

    Design: Corner/calculations/loaner_selector_substitutes_premium_when_standard_is_out_of_stock
    """
    world = build_config(with_van=False, with_bench=False)
    premium = create_loaner_unit(world["specs"]["CHEF_KNIFE"]["id"], grade="PREMIUM",
                                cycle_ceiling=5)
    request, _items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")], submit=False)

    issue = validate_success(api_client.create_loaner_issue(
        {"service_request_id": request["id"],
         "item_class_spec_id": world["specs"]["CHEF_KNIFE"]["id"],
         "requested_grade": "STANDARD"},
        make_technician_headers(world["tech"]["id"])), 201)
    assert_loaner_issue(issue)
    assert issue["loaner_unit_id"] == premium["id"]
    assert issue["substituted"] is True
    assert issue["requested_grade"] == "STANDARD"
    assert_same_instant(issue["issued_at"], "2026-05-01T00:00:00Z", "issued_at")
    assert_same_instant(issue["due_at"], "2026-05-15T00:00:00Z", "due_at")
    assert read_loaner_unit(premium["id"])["status"] == "ISSUED"


def _issued_loaner_world(cycle_ceiling=5):
    world = build_config(with_bench=False)
    unit = create_loaner_unit(world["specs"]["CHEF_KNIFE"]["id"], grade="STANDARD",
                              cycle_ceiling=cycle_ceiling)
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    route_to_van(world, request["id"])
    issue = issue_loaner(request["id"], world["specs"]["CHEF_KNIFE"]["id"], world["tech"]["id"])
    return world, request, items, unit, issue


def test_late_customer_return_is_capped_at_the_maximum_late_fee():
    """PRD 3.8: "Under the **customer-late** variant, the grace end is `due_at` plus 24
    hours; the overdue seconds are the return instant minus the grace end, floored at zero; the
    late days are those overdue seconds divided by 86400 and rounded *up* to a whole number —
    this is the one ceiling in the system, and any part of a day counts as a whole day; and
    `late_fee_cents` is the lesser of a 2500-cent cap and the late days multiplied by 250 cents
    per day."
    PRD 3.8: "When the computed fee is greater than zero, a late-fee line is appended to the
    account's draft invoice, creating that draft invoice when none exists."
    PRD 3.10: "Taxability is fixed per kind and is not negotiable per line: `SERVICE`,
    `SUBSCRIPTION_FEE`, `PRORATION_CREDIT` and `WARRANTY_CREDIT` lines are taxable; `PART` and
    `LATE_FEE` lines are not."

    Design: Corner/calculations/loaner_late_fee_reaches_the_cap_for_a_customer_delay
    """
    world, _request, _items, unit, issue = _issued_loaner_world()
    set_clock("2026-06-01T00:00:00Z")

    returned = return_loaner(issue["id"], world["tech"]["id"], damage_reported=False)
    assert_same_instant(returned["due_at"], "2026-05-15T00:00:00Z", "due_at")
    assert returned["delay_attribution"] == "CUSTOMER"
    assert returned["late_fee_cents"] == 2500

    reread_unit = read_loaner_unit(unit["id"])
    assert reread_unit["status"] == "IN_STOCK"
    assert reread_unit["cycle_count"] == 1

    invoice = find_draft_invoice(world["account"]["id"])
    assert invoice["nontaxable_subtotal_cents"] == 2500
    assert invoice["taxable_subtotal_cents"] == 0
    assert invoice["tax_cents"] == 0
    assert invoice["total_cents"] == 2500


def test_late_fee_is_waived_when_the_delay_is_the_shops_own_rework():
    """PRD 3.8: "Attribution is `SERVICE` when the issue's service request carries a non-null
    `origin_warranty_claim_id`, or when any item of that request has `service_status`
    `REWORK_QUEUED` at the moment of return; otherwise it is `CUSTOMER`."
    PRD 3.8: "Under the **service-delay** variant the `late_fee_cents` is 0 no matter how far
    past the deadline the return is, because the shop owns a delay it caused by having the
    customer's blade back in for rework."

    Design: Corner/calculations/loaner_late_fee_waived_when_the_delay_is_the_shops_own_rework
    """
    world = build_config(second_technician=True)
    unit = create_loaner_unit(world["specs"]["CHEF_KNIFE"]["id"], grade="STANDARD",
                              cycle_ceiling=5)
    request, items = stage_request(world, [("CHEF_KNIFE", "CHIP_REPAIR")])
    route_to_bench(world, request["id"])
    work_and_deliver(world, request["id"], [items[0]["id"]], ["CHIP_REPAIR"])
    invoice = create_invoice(world["account"]["id"], service_request_id=request["id"])
    issue_invoice(invoice["id"])
    claim = create_claim(items[0]["id"], world["account"]["id"], reason="Chip returned")
    approve_claim(claim["id"], world["tech_b"]["id"])
    issue = issue_loaner(request["id"], world["specs"]["CHEF_KNIFE"]["id"],
                         world["tech_b"]["id"])
    set_clock("2026-06-01T00:00:00Z")

    returned = return_loaner(issue["id"], world["tech_b"]["id"], damage_reported=False)
    assert read_item(items[0]["id"])["service_status"] == "REWORK_QUEUED"
    assert returned["delay_attribution"] == "SERVICE"
    assert returned["late_fee_cents"] == 0

    reread_unit = read_loaner_unit(unit["id"])
    assert reread_unit["status"] == "IN_STOCK"
    assert reread_unit["cycle_count"] == 1


def test_returned_unit_re_enters_stock_and_can_be_issued_a_second_time():
    """PRD 3.8: "Otherwise the unit moves `INSPECTION → IN_STOCK` and rejoins the rotation
    with its higher `cycle_count`, which under the selector's ranking sends it to the back of
    the queue."
    PRD 3.8: "Eligible units are those that are `IN_STOCK`, belong to the requested spec, and
    whose grade rank is at least the requested grade's rank, where `STANDARD` ranks 1 and
    `PREMIUM` ranks 2 — so a premium unit may stand in for a standard request, but never the
    other way round."

    Design: Difficulty/non_linear_state_machine/loaner_unit_issue_inspection_stock_reentry_cycle
    """
    world, request, _items, unit, first_issue = _issued_loaner_world()
    return_loaner(first_issue["id"], world["tech"]["id"], damage_reported=False)

    second_issue = issue_loaner(request["id"], world["specs"]["CHEF_KNIFE"]["id"],
                                world["tech"]["id"])
    assert second_issue["status"] == "OPEN"
    assert second_issue["loaner_unit_id"] == read_loaner_issue(
        first_issue["id"])["loaner_unit_id"]

    reread_unit = read_loaner_unit(unit["id"])
    assert_loaner_unit(reread_unit)
    assert reread_unit["status"] == "ISSUED"
    assert reread_unit["cycle_count"] == 1
    assert reread_unit["damage_reported"] is False


def test_first_loan_closes_with_no_late_fee_and_customer_attribution():
    """PRD 3.8: "Either way the issue moves `OPEN → RETURNED`, `returned_at` is stamped from
    the logical clock, `delay_attribution` and `late_fee_cents` are computed, and the unit
    moves `ISSUED → INSPECTION`, recording `damage_reported` from the return."
    PRD 3.8: "A return at or before the grace end yields zero late days and therefore no fee."

    Design: Difficulty/non_linear_state_machine/loaner_unit_issue_inspection_stock_reentry_cycle
    """
    world, _request, _items, _unit, first_issue = _issued_loaner_world()

    returned = return_loaner(first_issue["id"], world["tech"]["id"], damage_reported=False)
    assert returned["status"] == "RETURNED"
    assert returned["late_fee_cents"] == 0
    assert returned["delay_attribution"] == "CUSTOMER"
    assert_same_instant(returned["returned_at"], "2026-05-01T00:00:00Z", "returned_at")


def _loaner_ready_for_delivery(cycle_ceiling=1):
    world = build_config()
    unit = create_loaner_unit(world["specs"]["CHEF_KNIFE"]["id"], grade="STANDARD",
                              cycle_ceiling=cycle_ceiling)
    request, items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    route_to_van(world, request["id"])
    issue = issue_loaner(request["id"], world["specs"]["CHEF_KNIFE"]["id"], world["tech"]["id"])
    bench_intake(request["id"], world["bench"]["id"], world["tech"]["id"])
    assess_item(items[0]["id"], "ROUTINE_HONE", world["tech"]["id"])
    start_work(items[0]["id"], world["tech"]["id"])
    complete_work(items[0]["id"], world["tech"]["id"])
    return world, request, items, unit, issue


def test_delivery_closes_the_open_loaner_and_retires_the_unit_at_its_ceiling():
    """PRD 3.8: "Delivery of a van-route or rework request runs four linked steps: the
    finished items move to `DELIVERED` on both axes and `delivered_at` is stamped; that
    stamping closes the request's open loaner issue, moving it `OPEN → RETURNED`; that closure
    moves the loaner unit `ISSUED → INSPECTION` and computes the late fee; and the inspection
    resolves the unit to `RETIRED` or back to `IN_STOCK`."
    PRD 3.8: "If the incremented `cycle_count` has reached or passed `cycle_ceiling`, or
    `damage_reported` is true, the unit moves `INSPECTION → RETIRED`, which is terminal and
    removes it from the loanable pool — an effect that can push a later issue onto the
    substitute-grade branch of the selector, or all the way to `ERR_LOANER_STOCK_EXHAUSTED`."

    Design: Difficulty/transitive_cascade/delivery_closes_loaner_and_retires_unit_depth_four_cascade
    """
    world, request, _items, unit, issue = _loaner_ready_for_delivery(cycle_ceiling=1)

    deliver_request(request["id"], world["tech"]["id"])

    reread_issue = read_loaner_issue(issue["id"])
    assert reread_issue["status"] == "RETURNED"
    assert reread_issue["late_fee_cents"] == 0
    assert reread_issue["delay_attribution"] == "CUSTOMER"

    reread_unit = read_loaner_unit(unit["id"])
    assert reread_unit["status"] == "RETIRED"
    assert reread_unit["cycle_count"] == 1


def test_delivery_delivers_the_item_on_both_axes_and_frees_the_bench_day():
    """PRD 3.8: "On success the request moves `IN_SERVICE → COMPLETED` and `completed_at` is
    stamped from the logical clock, and every item still at `DONE` moves `DONE → DELIVERED` on
    the work axis. In every case the items' minutes are released from the bench day's
    `booked_minutes`."
    PRD 3.8: "For a `VAN_ROUTE` or `REWORK` request, each such item's `custody_location` moves
    `BENCH → DELIVERED` and its `delivered_at` is stamped."

    Design: Difficulty/transitive_cascade/delivery_closes_loaner_and_retires_unit_depth_four_cascade
    """
    world, request, items, _unit, _issue = _loaner_ready_for_delivery(cycle_ceiling=1)

    delivered = deliver_request(request["id"], world["tech"]["id"])
    assert delivered["status"] == "COMPLETED"

    item = read_item(items[0]["id"])
    assert item["service_status"] == "DELIVERED"
    assert item["custody_location"] == "DELIVERED"
    assert read_bench_day(world["bench"]["id"])["booked_minutes"] == 0


def _two_unit_pool():
    world = build_config(with_bench=False)
    unit_one = create_loaner_unit(world["specs"]["CHEF_KNIFE"]["id"], grade="STANDARD",
                                  cycle_ceiling=5)
    unit_two = create_loaner_unit(world["specs"]["CHEF_KNIFE"]["id"], grade="STANDARD",
                                  cycle_ceiling=5)
    request, _items = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    route_to_van(world, request["id"])
    issue = issue_loaner(request["id"], world["specs"]["CHEF_KNIFE"]["id"], world["tech"]["id"])
    return world, unit_one, unit_two, issue


def test_loaner_pool_is_conserved_across_an_issue_and_an_undamaged_return():
    """PRD 2.10: "For every class spec and grade, the count of `LoanerUnit` rows in
    `IN_STOCK` plus those in `ISSUED` plus those in `INSPECTION` plus those in `RETIRED` equals
    the total number of units ever created for that spec and grade; and the number of units in
    `ISSUED` equals the number of `LoanerIssue` rows in `OPEN`. Issuing a loaner and then
    returning it undamaged, with the unit still short of its cycle ceiling, must return the
    in-stock count to its pre-issue value."

    Design: Difficulty/compensating_invariant/loaner_stock_conservation_across_issue_then_return
    """
    world, unit_one, unit_two, issue = _two_unit_pool()

    return_loaner(issue["id"], world["tech"]["id"], damage_reported=False)

    first = read_loaner_unit(unit_one["id"])
    second = read_loaner_unit(unit_two["id"])
    assert first["status"] == "IN_STOCK"
    assert second["status"] == "IN_STOCK"
    assert first["cycle_count"] == 1
    assert second["cycle_count"] == 0
    assert_loaner_unit_conservation([first, second], 2)


def test_returned_issue_records_no_late_fee_and_no_grade_substitution():
    """PRD 3.8: "A return at or before the grace end yields zero late days and therefore no
    fee."
    PRD 3.8: "The chosen unit moves `IN_STOCK → ISSUED`; the issue record is born `OPEN`,
    records `loaner_unit_id`, stamps `issued_at` from the logical clock, derives `due_at` as
    `issued_at` plus 14 days, and sets `substituted` true exactly when the issued unit's grade
    differs from `requested_grade`."

    Design: Difficulty/compensating_invariant/loaner_stock_conservation_across_issue_then_return
    """
    world, _unit_one, _unit_two, issue = _two_unit_pool()

    returned = return_loaner(issue["id"], world["tech"]["id"], damage_reported=False)
    assert returned["status"] == "RETURNED"
    assert returned["late_fee_cents"] == 0
    assert returned["substituted"] is False
