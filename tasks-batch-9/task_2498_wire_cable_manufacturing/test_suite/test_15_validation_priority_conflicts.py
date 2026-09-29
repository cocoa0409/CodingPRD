"""Requests that break two rules at once, where only the ladder decides the answer.

A shipment is staged against an order whose pricing is frozen *and* onto an
account whose limit the reel deposit alone destroys: the pricing hold answers,
and lifting it reveals the credit rule that was masked all along. A lot is
released by the very engineer who tested it *and* is a hundredth of a mil
under-walled: the dimensional gate answers, because a 403 does not automatically
win — only the declared position does.
"""

from test_helpers import (
    BILLING,
    CLERK,
    ENGINEER,
    QE_RELEASER,
    QE_RELEASER_USER_ID,
    QE_TESTER,
    QE_TESTER_USER_ID,
    advance_lot_to_extruded,
    assert_lot_dimensions,
    assert_money,
    create_lot,
    create_reel,
    create_shipment_payload,
    current_order_version,
    get_success_data,
    load_reel_payload,
    read_customer,
    read_lot,
    read_order,
    read_reel,
    record_inline_tests,
    release_lot,
    setup_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

TINY_LIMIT_ACCOUNT = {"credit_limit_usd": 100.00}
HELD_ORDER = {"order_number": "SO-CNF", "ordered_kft": 5.000}
UNDER_WALLED_ORDER = {"order_number": "SO-SOD", "ordered_kft": 5.000}
# A 28 mil nominal wall at 90 percent requires 25.20 mils, so 25.19 misses by a
# hundredth while 100 x 25.19 / 29.0 is 86.86 and clears concentricity.
TOLERANCES = {"min_wall_pct": 90, "concentricity_min_pct": 85}
UNDER_WALLED_EXTRUSION = {
    "measured_min_wall_mils": 25.19, "measured_max_wall_mils": 29.0,
}
SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}


def _held_and_overdrawn(api):
    """An order frozen by a formulation suspension, on an account whose limit the
    reel deposit alone destroys.

    Returns ``(world, lot, reel)``.
    """
    world = setup_baseline(
        api, customer_overrides=TINY_LIMIT_ACCOUNT, order_overrides=HELD_ORDER
    )
    get_success_data(api.price_lock_customer_order(world["order"]["id"], BILLING))

    lot = create_lot(api, world, lot_code="LOT-CNF", planned_length_ft=5000)
    advance_lot_to_extruded(api, lot["id"])
    record_inline_tests(api, lot["id"])
    release_lot(api, lot["id"], 5000)
    reel = create_reel(api, reel_serial="R-CNF")
    reel = get_success_data(
        api.load_reel(reel["id"], load_reel_payload(lot["id"], 5000), CLERK)
    )

    get_success_data(
        api.suspend_compound(
            world["insulation"]["id"], ENGINEER,
            {"suspension_reason": "filler lot out of spec"},
        )
    )
    return world, read_lot(api, lot["id"]), reel


def _stage(api, world, lot, reel):
    return api.create_shipment(
        create_shipment_payload(
            world["order"]["id"], lot["id"], reel["id"], 5000,
            current_order_version(api, world["order"]["id"]), ship_date="2026-08-05",
        ),
        CLERK,
    )


def _under_walled_lot(api, lot_code="LOT-SOD", **lot_overrides):
    """A lot at `TESTED` whose wall is a hundredth of a mil short, with every test
    row operated by the same engineer who will try to release it."""
    world = setup_baseline(
        api, product_overrides=TOLERANCES, order_overrides=UNDER_WALLED_ORDER
    )
    lot = create_lot(api, world, lot_code=lot_code, planned_length_ft=5000,
                     **lot_overrides)
    advance_lot_to_extruded(
        api, lot["id"], extrusion_overrides=UNDER_WALLED_EXTRUSION
    )
    record_inline_tests(api, lot["id"], tester_headers=QE_TESTER)
    return world, read_lot(api, lot["id"])


def test_a_pricing_hold_answers_before_the_credit_limit_does(api):
    """Both rules are genuinely violated by the same staging request, and the
    answer is the 409 from the earlier rung rather than the 402 from the later
    one.

    PRD 2.11: "Checks are evaluated in the following order, and the first failure
    ends the request with no persisted effect whatsoever:"

    PRD 3.8: "An order whose pricing dimension currently reads `HELD` — because its
    formulation or its listing file was suspended — cannot be shipped at all, and
    the attempt is refused with `ERR_ORDER_PRICING_HELD`."

    PRD 3.8: "Finally credit is checked: the shipping account's `status` must be
    `ACTIVE`, and its `credit_exposure_usd` plus the reel's `deposit_usd` must not
    exceed its `credit_limit_usd`."

    Design: Difficulty/priority_pair_validation_conflict/shipment_order_held_beats_credit_limit
    """
    world, lot, reel = _held_and_overdrawn(api)

    order = read_order(api, world["order"]["id"])
    assert order["pricing_status"] == "HELD", "the earlier rule is live"
    assert order["hold_reason"] == "COMPOUND_SUSPENDED"
    account = read_customer(api, world["customer"]["id"])
    assert_money(account["credit_limit_usd"], 100.00, "a deliberately tiny limit")
    assert_money(account["credit_exposure_usd"], 0.00, "nothing owed yet")
    assert_money(reel["deposit_usd"], 450.00, "the deposit alone breaks the limit")
    assert_lot_dimensions(lot, "PACKAGED", "CONFORMING")

    validate_error(_stage(api, world, lot, reel), "ERR_ORDER_PRICING_HELD", 409)


def test_the_masked_credit_rule_left_no_trace_of_its_own(api):
    """Because the ladder stopped at the pricing hold, none of the later rungs ran
    and nothing at all was written: no shipment row, no deposit charged, no
    length shipped.

    PRD 2.11: "Checks are evaluated in the following order, and the first failure
    ends the request with no persisted effect whatsoever:"

    PRD 3.8: "The holding account's `deposit_charged_total_usd` and
    `reel_deposit_balance_usd` are each increased by the reel's `deposit_usd`, after
    which `credit_exposure_usd` is recomputed and the account's standing
    re-evaluated."

    PRD 3.8: "Shipments may be listed and narrowed by `order_id`, by `lot_id`, by
    `reel_id` and by `status`."

    Design: Difficulty/priority_pair_validation_conflict/shipment_order_held_beats_credit_limit
    """
    world, lot, reel = _held_and_overdrawn(api)
    validate_error(_stage(api, world, lot, reel), "ERR_ORDER_PRICING_HELD", 409)

    rows, meta = validate_paginated(
        api.list_shipments(CLERK, {"order_id": world["order"]["id"]})
    )
    assert meta["total_count"] == 0, "the refused staging created no shipment"
    assert rows == []

    assert read_reel(api, reel["id"])["status"] == "LOADED", (
        "the reel never advanced to SHIPPED"
    )
    assert read_order(api, world["order"]["id"])["shipped_kft"] == 0.000
    account = read_customer(api, world["customer"]["id"])
    assert_money(account["reel_deposit_balance_usd"], 0.00, "no deposit was charged")
    assert_money(account["deposit_charged_total_usd"], 0.00, "none ever has been")
    assert account["status"] == "ACTIVE", "and the account's standing never moved"
    assert read_lot(api, lot["id"])["process_state"] == "PACKAGED"


def test_lifting_the_hold_reveals_the_credit_rule_it_was_masking(api):
    """Resolving the formulation problem and confirming the price returns the order
    to `LOCKED`, and the byte-identical staging request now answers 402 — the
    later rung was masked, not absent.

    PRD 3.5: "The same action also lifts an order sitting at `HELD` back to `LOCKED`
    once the blocking formulation or listing problem has been resolved, clearing
    `hold_reason` back to null as it does so."

    PRD 3.8: "An account already on `CREDIT_HOLD`, or one that the new deposit would
    push past its limit, is refused with `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP 402."

    PRD 2.11: "Credit — `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/shipment_order_held_beats_credit_limit
    """
    world, lot, reel = _held_and_overdrawn(api)
    validate_error(_stage(api, world, lot, reel), "ERR_ORDER_PRICING_HELD", 409)

    get_success_data(api.qualify_compound(world["insulation"]["id"], ENGINEER))
    get_success_data(api.release_catalog_product(world["product"]["id"], ENGINEER))
    unfrozen = get_success_data(
        api.price_lock_customer_order(world["order"]["id"], BILLING)
    )
    assert unfrozen["pricing_status"] == "LOCKED"
    assert unfrozen["hold_reason"] is None

    validate_error(_stage(api, world, lot, reel), "ERR_CREDIT_LIMIT_EXCEEDED", 402)

    account = read_customer(api, world["customer"]["id"])
    assert_money(account["credit_exposure_usd"], 0.00, "0.00 plus 450.00 over 100.00")
    assert read_reel(api, reel["id"])["status"] == "LOADED", (
        "the second refusal is as inert as the first"
    )


def test_the_dimensional_gate_answers_before_segregation_of_duties(api):
    """The releasing engineer is on both test rows and the wall is a hundredth of a
    mil short, and the answer is the 422 from the dimensional gate rather than
    the 403 an auth-shaped rule might be expected to win with.

    PRD 2.11: "First, at lot release the marking check precedes the dimensional
    check, the dimensional check precedes the test-completeness check, test
    completeness precedes the failed-test check, the failed-test check precedes
    segregation of duties, and the listing file's active-status requirement is
    evaluated last of all — so a lot that is simultaneously mis-marked and
    under-walled reports `ERR_MARKING_MISMATCH`, and a lot that is under-walled and
    released by its own tester reports `ERR_DIMENSIONAL_NONCONFORMANCE`."

    PRD 3.7: "The **dimensional** gate requires both that `concentricity_pct` be at
    least the SKU's `concentricity_min_pct` and that `measured_min_wall_mils` be at
    least the required minimum wall, which is the SKU's `insulation_thickness_mils`
    multiplied by its `min_wall_pct` and divided by one hundred, rounded half up to
    two decimals; either comparison failing produces
    `ERR_DIMENSIONAL_NONCONFORMANCE`, and both comparisons are inclusive, so a lot
    exactly at the limit conforms."

    PRD 3.7: "The **segregation-of-duties** gate requires the releasing `X-User-ID`
    to differ from every `operator_user_id` recorded on the lot's test rows; a
    quality engineer who ran any of the tests may not sign off the lot, and the
    attempt is refused with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    Design: Difficulty/priority_pair_validation_conflict/lot_release_dimensional_nonconformance_beats_segregation_of_duties
    """
    _, lot = _under_walled_lot(api)

    assert lot["concentricity_pct"] == 86.86, (
        "one hundred times 25.19 divided by 29.0, which clears the 85 minimum, so "
        "extrusion legitimately passed"
    )
    assert lot["measured_min_wall_mils"] == 25.19, "a hundredth under the 25.20 needed"
    assert_lot_dimensions(lot, "TESTED", "PENDING")

    rows, _ = validate_paginated(api.list_cable_tests(lot["id"], ENGINEER))
    assert len(rows) == 2
    assert {row["operator_user_id"] for row in rows} == {QE_TESTER_USER_ID}, (
        "the engineer about to sign the lot off ran every test on it"
    )

    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_TESTER),
        "ERR_DIMENSIONAL_NONCONFORMANCE", 422,
    )


def test_the_refused_release_signed_nothing_and_certified_no_length(api):
    """The lot is exactly where the tests left it: the failing rung ended the
    request before any of the release's own effects were applied.

    PRD 2.11: "Checks are evaluated in the following order, and the first failure
    ends the request with no persisted effect whatsoever:"

    PRD 3.7: "A lot that clears all six has `released_by_user_id` set from
    `X-User-ID` and `packaged_length_ft` set from the payload, and its quality
    dimension moves `PENDING` → `CONFORMING` while its process dimension
    deliberately stays at `TESTED` — packaging has been authorised, not performed."

    Design: Difficulty/priority_pair_validation_conflict/lot_release_dimensional_nonconformance_beats_segregation_of_duties
    """
    _, lot = _under_walled_lot(api)
    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_TESTER),
        "ERR_DIMENSIONAL_NONCONFORMANCE", 422,
    )

    refused = read_lot(api, lot["id"])
    assert_lot_dimensions(refused, "TESTED", "PENDING")
    assert refused["packaged_length_ft"] == 0, "no length was certified"
    assert refused["released_by_user_id"] is None, "and nobody signed the lot off"
    assert refused["version"] == lot["version"], "the refusal was not a mutation"


def test_a_clean_releaser_hits_the_same_dimensional_wall(api):
    """Handing the release to an engineer who tested nothing removes the later
    violation entirely and changes the answer not at all, while a sibling lot
    whose wall is legal shows the 403 that was underneath all along.

    PRD 2.11: "Dimensional conformance at release —
    `ERR_DIMENSIONAL_NONCONFORMANCE`."

    PRD 2.11: "Segregation of duties at release — `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.7: "The **segregation-of-duties** gate requires the releasing `X-User-ID`
    to differ from every `operator_user_id` recorded on the lot's test rows; a
    quality engineer who ran any of the tests may not sign off the lot, and the
    attempt is refused with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    Design: Difficulty/priority_pair_validation_conflict/lot_release_dimensional_nonconformance_beats_segregation_of_duties
    """
    world, under_walled = _under_walled_lot(api)

    validate_error(
        api.release_production_lot(
            under_walled["id"], {"packaged_length_ft": 5000}, QE_RELEASER
        ),
        "ERR_DIMENSIONAL_NONCONFORMANCE", 422,
    )

    legal = create_lot(
        api, world, lot_code="LOT-SOD-OK", planned_length_ft=5000, **SECOND_LINE_WINDOW
    )
    advance_lot_to_extruded(
        api, legal["id"],
        extrusion_overrides={"measured_min_wall_mils": 25.20,
                             "measured_max_wall_mils": 29.0},
    )
    record_inline_tests(api, legal["id"], tester_headers=QE_TESTER)

    validate_error(
        api.release_production_lot(legal["id"], {"packaged_length_ft": 5000}, QE_TESTER),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )

    released = validate_success(
        api.release_production_lot(
            legal["id"], {"packaged_length_ft": 5000}, QE_RELEASER
        ),
        200,
    )
    assert released["quality_state"] == "CONFORMING", (
        "a wall exactly on the 25.20 minimum conforms"
    )
    assert released["released_by_user_id"] == QE_RELEASER_USER_ID
