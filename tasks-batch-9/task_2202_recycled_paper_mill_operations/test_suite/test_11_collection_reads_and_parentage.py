"""Reading the collections: page windows, the collection-specific 404 codes, the fields
a receipt derives for itself, and parentage as part of a row's identity.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, is_valid_uuid, is_iso8601_timestamp, TEST_USERS,
    declare_fiber_grade, declare_tl_140, publish_quote, register_supplier,
    register_machine, create_confirmed_po, record_receipt, setup_available_lot,
    setup_approved_batch, queue_batch, schedule_run, furnish_line, sublot,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
OPERATOR = TEST_USERS["operator_headers"]

OCC_11 = {"grade_code": "OCC_11", "index_symbol": "PPI_OCC",
          "max_contamination_pct": 3.00, "max_moisture_pct": 12.00,
          "nominal_yield_pct": 88.00, "deink_required": False, "rank_order": 1}


def _three_declared_grades():
    declare_fiber_grade(grade_code="MIX_54", index_symbol="PPI_SOP",
                        max_contamination_pct=8.00, max_moisture_pct=14.00,
                        nominal_yield_pct=78.00, rank_order=9)
    declare_fiber_grade(downgrade_target_grade_code="MIX_54", **OCC_11)
    declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                        max_contamination_pct=1.50, max_moisture_pct=10.00,
                        nominal_yield_pct=72.00, deink_required=True, rank_order=2)


def _confirmed_occ_order():
    declare_fiber_grade(**OCC_11)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             index_basis="CURRENT_MONTH", priced_for_month="2026-08",
                             negotiated_delta_per_ton=5.00)
    return supplier, po


def test_a_two_row_page_reports_the_whole_collection_in_its_total_count():
    """PRD §2.3: "Unless a specific endpoint narrative says otherwise, list results are
    sorted by `created_at` in ascending order — oldest first — so that a paged sweep over
    a collection is stable."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside `meta`, where `total_count` is the total number of rows matching
    the request's filters before pagination is applied and `has_more` is true when rows
    remain beyond the current page."

    Design: Corner/entities/list_fiber_grades_paginates_with_total_count_and_has_more
    """
    _three_declared_grades()

    first = api_client.list_fiber_grades(PLANNER, {"limit": 2, "offset": 0})
    validate_success(first)
    body = first.json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 2
    assert body["meta"]["total_count"] == 3
    assert body["meta"]["limit"] == 2
    assert body["meta"]["offset"] == 0
    assert body["meta"]["has_more"] is True

    second = api_client.list_fiber_grades(PLANNER, {"limit": 2, "offset": 2}).json()
    assert len(second["data"]) == 1
    assert second["meta"]["total_count"] == 3
    assert second["meta"]["has_more"] is False


def test_a_limit_one_above_the_ceiling_is_refused_rather_than_clamped():
    """PRD §2.3: "All list endpoints accept two query parameters, `limit` and `offset`.
    The `limit` parameter defaults to 10 when omitted, has a minimum accepted value of 1
    and a maximum accepted value of 100. The `offset` parameter defaults to 0 and must be
    a non-negative integer. A `limit` outside the range of 1 through 100 inclusive, or an
    `offset` that is negative or not an integer, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/list_fiber_grades_rejects_limit_above_max
    """
    declare_fiber_grade(**OCC_11)

    response = api_client.list_fiber_grades(BUYER, {"limit": 101, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    allowed = api_client.list_fiber_grades(BUYER, {"limit": 100, "offset": 0})
    validate_success(allowed)
    assert allowed.json()["meta"]["total_count"] == 1


def test_an_unknown_pulp_batch_id_answers_with_the_pulp_batch_code_not_a_shape_error():
    """PRD §2.7: "The existence codes are specific to the addressed collection:
    `ERR_SUPPLIER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_RECEIPT_NOT_FOUND`, `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_PULP_BATCH_NOT_FOUND`,
    `ERR_MACHINE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_GRADE_CHANGE_NOT_FOUND`,
    `ERR_ROLL_SET_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, and
    `ERR_STEAM_ALLOCATION_NOT_FOUND` each cover a path id of the corresponding kind,
    while `ERR_ENV_RECORD_NOT_FOUND` (HTTP 404) covers an effluent reading, sludge
    manifest, or reject stream id in the path."

    Design: Corner/entities/get_pulp_batch_with_unknown_id_returns_pulp_batch_not_found
    """
    declare_tl_140()
    bundle = setup_available_lot()
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 20.000)])

    response = api_client.get_pulp_batch(NON_EXISTENT_UUID, OPERATOR)
    validate_error(response, ApiErrorId.ERR_PULP_BATCH_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"

    validate_success(api_client.get_pulp_batch(batch["id"], OPERATOR))


def test_a_dry_single_sublot_truck_takes_no_deduction_at_all():
    """PRD §3.2: "Working through the sublots in ascending `sublot_no` order, each
    sublot's **wet tonnage** is its `gross_tons` minus its `tare_tons`, rounded half up
    to three decimal places."
    PRD §3.2: "Its **moisture excess** is its `moisture_pct` minus the grade's moisture
    ceiling, floored at zero so a dry sublot is never credited."
    PRD §3.2: "The receipt's `moisture_deduction_tons` is the sum of the per-sublot
    deductions, rounded to three decimal places, and its `net_tons` is the sum of the
    per-sublot **already-rounded** dry tonnages, rounded half up to two decimal places."
    PRD §3.2: "Two weighted averages come out of the same pass and both use the
    **pre-deduction wet tonnages** as weights, never the dry tonnages."

    Design: Corner/entities/receipt_creation_computes_net_tons_and_weighted_sample_fields
    """
    _, po = _confirmed_occ_order()

    receipt = record_receipt(po["id"], [sublot(1, 30.000, 8.000, 10.00, 2.00)],
                             truck_reference="TRK-0001")

    assert receipt["net_tons"] == pytest.approx(22.00, abs=1e-6)
    assert receipt["moisture_deduction_tons"] == pytest.approx(0.000, abs=1e-6)
    assert receipt["weighted_moisture_pct"] == pytest.approx(10.00, abs=1e-6)
    assert receipt["weighted_contamination_pct"] == pytest.approx(2.00, abs=1e-6)
    assert receipt["status"] == "SAMPLED"


def test_a_receipt_takes_its_party_and_grade_from_the_order_and_its_sampler_from_the_header():
    """PRD §3.2: "The receipt is created in `SAMPLED`, denormalises the parent order's
    `supplier_id` and contracted grade into `supplier_id` and `declared_grade_code`, and
    records the acting operator's identifier as `sampled_by_user_id`."
    PRD §3.2: "All three record the acting identifier as `dispositioned_by_user_id`."

    Design: Corner/entities/receipt_creation_stamps_system_fields_from_parent_and_header
    """
    supplier, po = _confirmed_occ_order()

    response = api_client.create_receipt(
        po["id"],
        {"truck_reference": "TRK-0002",
         "sublots": [sublot(1, 25.000, 7.000, 9.00, 1.50)]},
        SAMPLER)
    receipt = validate_success(response, 201)

    assert receipt["purchase_order_id"] == po["id"]
    assert receipt["supplier_id"] == supplier["id"]
    assert receipt["declared_grade_code"] == "OCC_11"
    assert receipt["sampled_by_user_id"] == SAMPLER["X-User-ID"]
    assert receipt["dispositioned_by_user_id"] is None
    assert receipt["accepted_grade_code"] is None
    assert receipt["truck_reference"] == "TRK-0002"
    assert is_valid_uuid(receipt["id"])
    assert is_iso8601_timestamp(receipt["created_at"])


def test_a_real_run_addressed_under_the_wrong_machine_simply_does_not_exist():
    """PRD §2.7: "Path parameters are resolved strictly left to right, and the first
    segment that fails to resolve determines the error."
    PRD §2.7: "A run id that exists but belongs to a different machine than the one named
    in the path is likewise `ERR_RUN_NOT_FOUND` (HTTP 404) — parentage is part of
    identity, not a filter."

    Design: Corner/entities/run_addressed_under_the_wrong_parent_machine_returns_run_not_found
    """
    pm1 = register_machine(name="PM1", wire_width_mm=5600, max_tons_per_hour=20.00,
                           changeover_buffer_minutes=30, steam_tph_per_ton=2.500)
    pm2 = register_machine(name="PM2", wire_width_mm=4200, max_tons_per_hour=14.00,
                           changeover_buffer_minutes=20, steam_tph_per_ton=2.100)
    bundle = setup_approved_batch()
    run = schedule_run(pm1["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z", pulp_draw_tons=15.000)

    response = api_client.start_run(pm2["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_RUN_NOT_FOUND.value, 404)

    unchanged = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert unchanged["run_status"] == "SCHEDULED"
    assert unchanged["machine_id"] == pm1["id"]


def test_a_furnish_line_naming_no_lot_at_all_stops_the_charge():
    """PRD §2.7: "Identifiers arriving in the request *body* rather than the path have
    their own codes: an unresolvable `fiber_grade_code`, `target_product_code` or
    `product_code` yields `ERR_GRADE_CODE_NOT_FOUND`; an unresolvable `supplier_id` or
    `customer_id` yields `ERR_PARTY_NOT_FOUND`; an unresolvable `pulp_batch_id` or a
    furnish line whose `inventory_lot_id` does not resolve yields
    `ERR_FURNISH_REFERENCE_NOT_FOUND`; an unresolvable `run_id`, `from_run_id`,
    `to_run_id` or `order_id`, or one that resolves to a row of the wrong type, yields
    `ERR_LINK_TARGET_NOT_FOUND`; and an entry of `reject_stream_ids` that does not
    resolve — or that resolves to a compensating reversal row — yields
    `ERR_REJECT_STREAM_REFERENCE_INVALID` (HTTP 404)."

    Design: Corner/entities/pulp_batch_furnish_line_pointing_at_unknown_lot_is_rejected
    """
    declare_tl_140()

    response = api_client.create_pulp_batch(
        {"pulper_line": "OCC_LINE", "target_product_code": "TL_140",
         "furnish_lines": [furnish_line(NON_EXISTENT_UUID, 20.000)]},
        OPERATOR)
    validate_error(response, ApiErrorId.ERR_FURNISH_REFERENCE_NOT_FOUND.value, 404)

    assert api_client.list_pulp_batches(OPERATOR).json()["meta"]["total_count"] == 0
