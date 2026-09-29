"""Refusal behaviour: authentication of the vendor-backed identity, the family of
per-resource 404s, and the state guards on shipment confirmation, scorecard
publication, integration-test evaluation and offer activation.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    add_blackout,
    create_active_vendor,
    create_draft_item,
    create_draft_vendor,
    create_integration_test_payload,
    create_seeded_scorecard,
    evaluate_integration_test_payload,
    get_success_data,
    make_vendor_ops_analyst_headers,
    make_vendor_user_headers,
    publish_scorecard,
    refresh_item,
    refresh_line,
    refresh_vendor,
    reset_clock,
    set_clock,
    setup_transmitted_line,
    setup_vendor_with_active_offer,
    ship_confirm_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["vendor_ops_analyst_headers"]
MM = TEST_USERS["merchandise_manager_headers"]
CARE = TEST_USERS["care_agent_headers"]


def _row_by_id(rows, row_id):
    """The one row of a list response carrying this id."""
    matches = [row for row in rows if row["id"] == row_id]
    assert matches, f"expected a row with id {row_id} in {rows}"
    return matches[0]


def test_vendor_user_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is absent or holds any string outside that set of five, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401); the same error is returned when the role is `VendorUser` but `X-User-ID` is absent."

    The offer being read genuinely exists and belongs to an active vendor, so the
    only possible objection is the missing vendor identity header. The refusal is
    401 rather than an authorization or scoping error.

    Design: Corner/errors/corner_vendor_user_without_an_x_user_id_header_is_unauthenticated
    """
    state = setup_vendor_with_active_offer(api, suffix="E1")

    headers = {"X-User-Role": "VendorUser", "Content-Type": "application/json"}
    response = api.get_item(state["item_id"], headers)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_unknown_order_id_returns_order_not_found(api):
    """PRD §2.6: "An order identifier in the path resolves to an existing order. Otherwise `ERR_ORDER_NOT_FOUND`. Applies to the single-order read, the promise read and order transmission."

    A well-formed identifier that names no order gets the order-specific 404.

    Design: Corner/errors/corner_unknown_order_id_returns_order_not_found
    """
    reset_clock(api)

    response = api.get_order(NON_EXISTENT_UUID, CARE)

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_unknown_order_line_id_returns_line_not_found(api):
    """PRD §2.6: "A `line_id` in the path or body resolves to an existing order line. Otherwise `ERR_LINE_NOT_FOUND`. Applies to every endpoint beneath `/dropship/order-lines/...` and to the `line_id` supplied when a return is opened."

    An order line carries its own 404, distinct from the order's.

    Design: Corner/errors/corner_unknown_order_line_id_returns_line_not_found
    """
    reset_clock(api)

    response = api.get_order_line(NON_EXISTENT_UUID, ADMIN)

    validate_error(response, ApiErrorId.ERR_LINE_NOT_FOUND.value)


def test_unknown_return_id_returns_return_not_found(api):
    """PRD §2.6: "A return identifier in the path resolves to an existing return authorization. Otherwise `ERR_RETURN_NOT_FOUND`. Applies to the single-return read and to authorization, receipt and rejection."

    The dedicated return 404 fires on the plain read path too.

    Design: Corner/errors/corner_unknown_return_id_returns_return_not_found
    """
    reset_clock(api)

    response = api.get_return(NON_EXISTENT_UUID, CARE)

    validate_error(response, ApiErrorId.ERR_RETURN_NOT_FOUND.value)


def test_unknown_scorecard_id_returns_scorecard_not_found(api):
    """PRD §2.6: "A scorecard identifier in the path resolves to an existing scorecard. Otherwise `ERR_SCORECARD_NOT_FOUND`. Applies to scorecard publication."

    The publish request carries a real and current vendor version, so the
    optimistic-concurrency gate would be satisfied; existence of the scorecard is
    checked first and answers 404 while the vendor row stays untouched.

    Design: Corner/errors/corner_unknown_scorecard_id_returns_scorecard_not_found
    """
    reset_clock(api)
    vendor = create_draft_vendor(api, suffix="E5")
    assert vendor["version"] == 1

    response = api.publish_scorecard(NON_EXISTENT_UUID, vendor["version"], ADMIN)

    validate_error(response, ApiErrorId.ERR_SCORECARD_NOT_FOUND.value)
    assert refresh_vendor(api, vendor["id"])["version"] == 1


def test_unknown_integration_test_id_returns_integration_test_not_found(api):
    """PRD §2.6: "A test identifier in the path resolves to an existing integration test run. Otherwise `ERR_INTEGRATION_TEST_NOT_FOUND`. Applies to test evaluation."

    The evaluation path addresses the test run directly, so an unknown id gets the
    integration-test 404 rather than a vendor one.

    Design: Corner/errors/corner_unknown_integration_test_id_returns_integration_test_not_found
    """
    reset_clock(api)

    response = api.evaluate_integration_test(
        NON_EXISTENT_UUID,
        evaluate_integration_test_payload("PASS"),
        make_vendor_ops_analyst_headers("ops-evaluator-E6"),
    )

    validate_error(response, ApiErrorId.ERR_INTEGRATION_TEST_NOT_FOUND.value)


def test_unknown_blackout_id_under_a_real_vendor_returns_blackout_not_found(api):
    """PRD §2.6: "The `blackout_id` in the path resolves to an existing blackout window whose `vendor_id` equals the vendor named in the path. Otherwise `ERR_BLACKOUT_NOT_FOUND`. Applies to blackout cancellation."

    The nested cancellation path carries two identifiers. With a real vendor and an
    unknown window the answer is the blackout 404, and cancelling the window that
    does exist afterwards still works and moves it to CANCELLED.

    Design: Corner/errors/corner_unknown_blackout_id_under_a_real_vendor_returns_blackout_not_found
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="E7")
    blackout = add_blackout(
        api,
        vendor["id"],
        start_date="2026-08-20",
        end_date="2026-08-21",
        reason="PEAK_FREEZE",
        reopen_buffer_days=0,
    )

    missing = api.cancel_blackout(vendor["id"], NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_BLACKOUT_NOT_FOUND.value)

    cancelled = validate_success(api.cancel_blackout(vendor["id"], blackout["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"

    rows, meta = validate_paginated(
        api.list_blackouts(vendor["id"], ADMIN, params={"status": "ACTIVE"})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_ship_confirm_before_acknowledgment_returns_line_invalid_state(api):
    """PRD §3.6: "A `TRANSMITTED` line must be acknowledged first; skipping the acknowledgment is refused with `ERR_LINE_INVALID_STATE`."

    A vendor shipping straight off transmission is refused, no shipment record is
    written and the vendor's settlement ledger stays at zero.

    Design: Corner/errors/corner_ship_confirm_before_acknowledgment_returns_line_invalid_state
    """
    state = setup_transmitted_line(api, quantity=1, order_ref="ORD-E8", suffix="E8")

    response = api.ship_confirm_line(
        state["line_id"],
        ship_confirm_payload(1, tracking_number="1Z-LS-001"),
        make_vendor_user_headers(state["vendor_id"]),
    )

    validate_error(response, ApiErrorId.ERR_LINE_INVALID_STATE.value)
    assert refresh_line(api, state["line_id"])["status"] == "TRANSMITTED"
    shipments, _ = validate_paginated(
        api.list_shipment_confirmations(state["line_id"], ADMIN)
    )
    assert shipments == []
    assert refresh_vendor(api, state["vendor_id"])["settlement_balance_cents"] == 0


def test_publishing_an_already_published_scorecard_returns_scorecard_invalid_state(api):
    """PRD §3.9: "Publication is a `PlatformAdmin`-only step and requires the scorecard to be in `status` `DRAFT`; publishing an already-published scorecard is refused with `ERR_SCORECARD_INVALID_STATE`."

    The second publish supplies the vendor version re-read after the first publish
    bumped it, so the concurrency gate is satisfied and only the scorecard's own
    status can explain the refusal. Nothing the first publish wrote moves again.

    Design: Corner/errors/corner_publishing_an_already_published_scorecard_returns_scorecard_invalid_state
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="E9")
    set_clock(api, "2026-10-01T00:00:00Z")
    scorecard = create_seeded_scorecard(
        api,
        vendor["id"],
        20.0,
        9500,
        300,
        400,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )

    published = publish_scorecard(api, scorecard["id"], vendor["id"])
    assert published["status"] == "PUBLISHED"
    assert published["composite_score"] == 95.8
    assert published["tier"] == "PLATINUM"
    after_first = refresh_vendor(api, vendor["id"])
    assert after_first["performance_tier"] == "PLATINUM"
    assert after_first["promise_padding_days"] == 0

    response = api.publish_scorecard(scorecard["id"], after_first["version"], ADMIN)
    validate_error(response, ApiErrorId.ERR_SCORECARD_INVALID_STATE.value)

    rows, _ = validate_paginated(api.list_scorecards(vendor["id"], ADMIN))
    assert _row_by_id(rows, scorecard["id"])["status"] == "PUBLISHED"
    untouched = refresh_vendor(api, vendor["id"])
    assert untouched["version"] == after_first["version"]
    assert untouched["performance_tier"] == "PLATINUM"
    assert untouched["promise_padding_days"] == 0


def test_evaluating_the_same_integration_test_twice_returns_invalid_state(api):
    """PRD §2.6: "The test run's `status` is `PENDING` and its `round_number` equals the vendor's current `integration_round`. Otherwise `ERR_INTEGRATION_TEST_INVALID_STATE` (HTTP 409). Applies to test evaluation."

    The second evaluation comes from a third, different operator identity, so the
    segregation-of-duties comparison passes and the only remaining objection is
    that the run has already left PENDING.

    Design: Corner/errors/corner_evaluating_the_same_integration_test_twice_returns_integration_test_invalid_state
    """
    reset_clock(api)
    vendor = create_draft_vendor(api, suffix="E10")
    get_success_data(api.begin_integration(vendor["id"], OPS))
    run = get_success_data(
        api.record_integration_test(
            vendor["id"],
            create_integration_test_payload("CATALOG"),
            make_vendor_ops_analyst_headers("ops-recorder-E10"),
        )
    )
    get_success_data(
        api.evaluate_integration_test(
            run["id"],
            evaluate_integration_test_payload("PASS"),
            make_vendor_ops_analyst_headers("ops-evaluator-E10"),
        )
    )

    response = api.evaluate_integration_test(
        run["id"],
        evaluate_integration_test_payload(
            "FAIL", reported_error_count=3, defect_notes="Second adjudication attempt"
        ),
        make_vendor_ops_analyst_headers("ops-auditor-E10"),
    )

    validate_error(response, ApiErrorId.ERR_INTEGRATION_TEST_INVALID_STATE.value)
    rows, _ = validate_paginated(api.list_integration_tests(vendor["id"], ADMIN))
    assert _row_by_id(rows, run["id"])["status"] == "PASSED"
    assert refresh_vendor(api, vendor["id"])["onboarding_status"] == "INTEGRATION_TESTING"


def test_activating_an_offer_with_no_matching_ship_method_coverage_is_rejected(api):
    """PRD §2.6: "The vendor has at least one serviceability rule with `status` `ACTIVE`; for offer activation that rule must additionally match the offer's `ship_method`. Otherwise `ERR_NO_SERVICEABILITY_COVERAGE` (HTTP 422). Applies to vendor activation and offer activation."

    The vendor's single coverage row serves US-WEST by GROUND, so a GROUND offer
    activates while an otherwise identical TWO_DAY offer is refused and stays in
    DRAFT at version 1 with no availability.

    Design: Corner/errors/corner_activating_an_offer_with_no_matching_ship_method_coverage_is_rejected
    """
    reset_clock(api)
    vendor = create_active_vendor(
        api, suffix="E11", rules=[{"zone_code": "US-WEST", "ship_method": "GROUND"}]
    )
    ground_offer = create_draft_item(
        api, vendor["id"], sku="SKU-COVER-G", ship_method="GROUND"
    )
    two_day_offer = create_draft_item(
        api, vendor["id"], sku="SKU-COVER-X", ship_method="TWO_DAY"
    )

    activated = validate_success(api.activate_item(ground_offer["id"], MM))
    assert activated["status"] == "ACTIVE"

    response = api.activate_item(two_day_offer["id"], MM)
    validate_error(response, ApiErrorId.ERR_NO_SERVICEABILITY_COVERAGE.value)

    refused = refresh_item(api, two_day_offer["id"])
    assert refused["status"] == "DRAFT"
    assert refused["version"] == 1
    assert refused["available_units"] == 0
