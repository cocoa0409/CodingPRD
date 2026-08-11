"""Custody of finished goods: the hold, the release, quarantine and clearance."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_money,
    assert_same_instant,
    build_active_account,
    build_held_lot,
    build_released_lot,
    make_qa_manager_headers,
    open_shipment,
    read_lot,
    read_shipment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
QA = TEST_USERS["qa_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def test_a_quarantined_lot_may_be_cleared_back_to_its_pre_quarantine_status(api):
    """PRD 3.7: "The status held immediately before is recorded in
    `pre_quarantine_status`, whose only non-null members are `HELD` and `RELEASED`."
    PRD 3.7: "A clearance restores `status` to whatever `pre_quarantine_status` holds,
    increments `quarantine_clearance_count`, and runs the three-hop re-allocation
    cascade: allocations reversed specifically for `LOT_QUARANTINED` whose
    `reallocation_attempt_count` is strictly below 2 return to `ALLOCATED` with that
    counter incremented and the lot's `reserved_units` raised again, and each
    re-instated allocation takes its `charge_amount` back out of the subscription's
    `credit_balance`."

    Design: Difficulty/non_linear_state_machine/finished_lot_quarantine_reentry_loop_is_capped_at_one_clearance
    """
    built = build_released_lot(
        api, run_code="PR-6", vessel_code="FV-6", batch_code="B-6001", culture_label="Mother F"
    )
    lot_id = built["lot"]["id"]

    quarantined = validate_success(
        api.quarantine_finished_lot(lot_id, {"reason": "Off-flavour complaint"}, COMPLIANCE)
    )
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["pre_quarantine_status"] == "RELEASED"

    cleared = validate_success(api.clear_quarantine_finished_lot(lot_id, COMPLIANCE))
    assert cleared["status"] == "RELEASED"
    assert cleared["quarantine_clearance_count"] == 1


def test_a_second_clearance_is_refused_and_the_lot_stays_quarantined(api):
    """PRD 3.7: "**Clearance** is the way back, and it is capped. A lot may be cleared
    out of quarantine **at most once**: `quarantine_clearance_count` must be strictly
    below 1, and a second attempt answers `ERR_QUARANTINE_CLEARANCE_CAP` — after that
    the only remaining exit is a recall."

    Design: Difficulty/non_linear_state_machine/finished_lot_quarantine_reentry_loop_is_capped_at_one_clearance
    """
    built = build_released_lot(
        api, run_code="PR-6", vessel_code="FV-6", batch_code="B-6001", culture_label="Mother F"
    )
    lot_id = built["lot"]["id"]
    validate_success(
        api.quarantine_finished_lot(lot_id, {"reason": "Off-flavour complaint"}, COMPLIANCE)
    )
    validate_success(api.clear_quarantine_finished_lot(lot_id, COMPLIANCE))
    validate_success(
        api.quarantine_finished_lot(lot_id, {"reason": "Second complaint"}, COMPLIANCE)
    )

    response = api.clear_quarantine_finished_lot(lot_id, COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_QUARANTINE_CLEARANCE_CAP.value, 422)

    after = read_lot(api, lot_id)
    assert after["status"] == "QUARANTINED"
    assert after["quarantine_clearance_count"] == 1
    assert after["pre_quarantine_status"] == "RELEASED"


def test_the_hold_window_the_segregation_test_and_the_credit_gate_in_that_order(api):
    """PRD 3.7: "The clock must have reached `packaged_at` plus 48 hours — the exact
    48-hour instant is already releasable, and anything strictly earlier is
    `ERR_LOT_HOLD_PERIOD` — and the `QaManager` performing the release must not be the
    same person, by `X-User-ID`, who opened the packaging run that produced the lot."
    PRD 3.7: "That second test answers `ERR_SEGREGATION_OF_DUTIES`, and because it
    depends on stored state it is evaluated *after* the hold-window test, not with the
    role check: a release that is both too early and self-approved answers
    `ERR_LOT_HOLD_PERIOD`."
    PRD 3.7: "A successful release moves `HELD → RELEASED` and stamps
    `released_by_user_id` and `released_at`."
    PRD 3.9: "Step five: the confirmation is refused when that exposure is **strictly
    greater** than the account's `credit_limit`; an exposure exactly equal to the
    limit is accepted."

    Design: Corner/errors/hold_window_then_segregation_then_credit_limit_on_the_release_and_sell_path
    """
    built = build_held_lot(
        api, run_code="PR-39", vessel_code="FV-39", batch_code="B-39001",
        culture_label="Mother AH", run_creator_user_id="op-1",
    )
    lot_id = built["lot"]["id"]
    account = build_active_account(
        api, account_name="Small Limit Co", credit_limit=100.0, credit_terms_days=30,
        alcoholic_license_on_file=False,
    )

    # Both too early and self-approved: the hold window has to answer first.
    too_early = api.release_finished_lot(lot_id, make_qa_manager_headers("op-1"))
    validate_error(too_early, ApiErrorId.ERR_LOT_HOLD_PERIOD.value, 422)
    assert too_early.json()["data"]["error_id"] != "ERR_SEGREGATION_OF_DUTIES"

    set_clock(api, "2026-05-12T00:00:00.000Z")
    self_release = api.release_finished_lot(lot_id, make_qa_manager_headers("op-1"))
    validate_error(self_release, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    released = validate_success(
        api.release_finished_lot(lot_id, make_qa_manager_headers("qa-1"))
    )
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "qa-1"
    assert_same_instant(released["packaged_at"], "2026-05-10T00:00:00.000Z", "packaged_at")

    shipment = open_shipment(api, account["id"])
    add_line(api, shipment["id"], lot_id, 30, 5.00)
    refused = api.confirm_shipment(shipment["id"], SALES)
    validate_error(refused, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 402)

    after_shipment = read_shipment(api, shipment["id"])
    assert after_shipment["status"] == "DRAFT"
    assert_money(after_shipment["subtotal"], 150.00, "subtotal of the refused shipment")
    assert read_lot(api, lot_id)["reserved_units"] == 30, (
        "reservation happens at line-add time, so the refused confirm keeps it"
    )


def test_the_finished_lot_list_carries_the_declared_pagination_envelope(api):
    """PRD 2.3: "When `limit` is omitted it defaults to 10; the smallest accepted
    value is 1 and the largest is 100. When `offset` is omitted it defaults to 0, and
    the smallest accepted value is 0."
    PRD 2.3: "The `meta` block of a list response carries `limit` (the effective page
    size), `offset` (the effective starting index), `total_count` (the number of
    records matching the filter before pagination is applied) and `has_more` (true
    when records remain beyond this page)."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/entities/finished_lot_list_returns_the_declared_pagination_envelope
    """
    response = api.list_finished_lots(SALES)
    rows, meta = validate_paginated(response)

    body = response.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert rows == []
