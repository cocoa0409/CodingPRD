"""The buyer's and the lab's side of the contract: who may judge a truck, how much a
supplier on probation may still commit to, and what pricing does with no published index.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_supplier_headers, declare_fiber_grade, publish_quote,
    register_supplier, create_draft_po, create_priced_po, create_confirmed_po,
    record_receipt, disposition, lots_of_receipt, sublot, set_clock, po_version,
)

BUYER = TEST_USERS["buyer_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]

OCC_11 = {"grade_code": "OCC_11", "index_symbol": "PPI_OCC",
          "max_contamination_pct": 3.00, "max_moisture_pct": 12.00,
          "nominal_yield_pct": 88.00, "deink_required": False, "rank_order": 1}
DIRTY_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 5.00)]


def _declared_market():
    declare_fiber_grade(**OCC_11)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    return register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)


def test_the_operator_who_sampled_the_truck_may_not_pass_judgement_on_it():
    """PRD §3.2: "All three branches require the receipt to be in `SAMPLED`, failing which the
    request is rejected with `ERR_RECEIPT_INVALID_STATE` (HTTP 409), and all three enforce
    segregation of duties: the acting `X-User-ID` must differ from the receipt's
    `sampled_by_user_id`, and an operator attempting to disposition the truck they sampled is
    rejected with `ERR_SOD_SAME_SAMPLER` (HTTP 409)."
    PRD §3.2: "**Accepting** is permitted only when `weighted_contamination_pct` is no greater
    than the declared grade's `max_contamination_pct` — the boundary is inclusive, so a truck
    exactly at the limit is clean enough — and only when the parent purchase order is in
    `CONFIRMED` or `PARTIALLY_RECEIVED`."
    PRD §3.2: "The supplier's `contamination_strike_count` is left untouched — a clean truck
    costs the supplier nothing."

    Design: Corner/validations/the_sampler_dispositioning_their_own_truck_is_stopped_before_the_grade_check
    """
    supplier = _declared_market()
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             negotiated_delta_per_ton=5.00)
    receipt = record_receipt(po["id"], DIRTY_TRUCK, truck_reference="TRK-0001",
                             sampler_headers=SAMPLER)

    response = api_client.disposition_receipt(
        receipt["id"], {"disposition": "ACCEPT"}, SAMPLER)
    validate_error(response, ApiErrorId.ERR_SOD_SAME_SAMPLER.value, 409)

    undecided = get_success_data(api_client.get_receipt(receipt["id"], SAMPLER))
    assert undecided["status"] == "SAMPLED"
    assert undecided["sampled_by_user_id"] == "ql_sample"
    assert undecided["dispositioned_by_user_id"] is None
    assert undecided["accepted_grade_code"] is None
    assert lots_of_receipt(receipt["id"]) == [], \
        "no lot may be minted by a refused acceptance"
    unblemished = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert unblemished["contamination_strike_count"] == 0
    assert unblemished["qualification_status"] == "QUALIFIED"


def test_a_supplier_on_probation_may_still_sign_for_exactly_five_hundred_tons():
    """PRD §3.1: "Taking an order `PRICED → CONFIRMED` requires the order to be in `PRICED`,
    requires the acting `X-User-ID` to equal the order's `supplier_id` (otherwise
    `ERR_NOT_RESOURCE_OWNER`), and requires the supplier to be commercially fit: either
    `qualification_status` reads `QUALIFIED`, or it reads `PROBATION` and `contracted_tons` is
    no greater than 500.00."
    PRD §3.1: "A supplier on probation attempting to confirm a contract above 500.00 tons is
    rejected with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 409)."
    PRD §3.2: "Four or more strikes makes the supplier `SUSPENDED`; two or three strikes makes
    it `PROBATION`; anything below two leaves it `QUALIFIED`."

    Design: Corner/validations/a_probation_supplier_may_still_confirm_exactly_five_hundred_tons
    """
    set_clock("2026-08-01T00:00:00Z")
    supplier = _declared_market()
    struck = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                                 negotiated_delta_per_ton=5.00)
    for reference, judge in (("TRK-0001", DISPOSER), ("TRK-0002", CERTIFIER)):
        receipt = record_receipt(struck["id"], DIRTY_TRUCK, truck_reference=reference,
                                 sampler_headers=SAMPLER)
        disposition(receipt["id"], "REJECT", headers=judge)
    on_probation = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert on_probation["qualification_status"] == "PROBATION"
    at_the_limit = create_priced_po(supplier["id"], "OCC_11", contracted_tons=500.00,
                                    negotiated_delta_per_ton=0.00)

    confirmed = validate_success(api_client.confirm_purchase_order(
        at_the_limit["id"], make_supplier_headers(supplier["id"])))

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["contracted_tons"] == pytest.approx(500.00, abs=1e-6)
    assert confirmed["quoted_unit_price_per_ton"] == pytest.approx(194.81, abs=1e-6), \
        "180.00 of index plus 12.50 of freight plus a 2.31 surcharge"
    posture = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert posture["contamination_strike_count"] == 2
    assert posture["qualification_status"] == "PROBATION"


def test_pricing_off_a_month_that_was_never_published_is_unprocessable():
    """PRD §3.1: "It is refused with `ERR_PURCHASE_ORDER_INVALID_STATE` unless the order is
    currently in `DRAFT`, refused with `ERR_SUPPLIER_SUSPENDED` when the counterparty's
    `qualification_status` is `SUSPENDED`, and refused with `ERR_INDEX_QUOTE_MISSING` (HTTP
    422) when no non-superseded quote exists for the resolved symbol and month."
    PRD §3.1: "The target month is the order's `priced_for_month` when `index_basis` is
    `CURRENT_MONTH`, and the calendar month immediately preceding `priced_for_month` when
    `index_basis` is `PRIOR_MONTH`."
    PRD §3.1: "The surviving quote's `published_price_per_ton` is the raw index price, and the
    resolved month is recorded as `index_quote_month_used`."

    Design: Corner/validations/prior_month_pricing_without_a_published_quote_is_unprocessable
    """
    supplier = _declared_market()
    po = create_draft_po(supplier["id"], "OCC_11", contracted_tons=100.00,
                         index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                         negotiated_delta_per_ton=0.00)
    version_before = po_version(po["id"])

    response = api_client.price_purchase_order(
        po["id"], {"expected_purchase_order_version": version_before}, BUYER)
    validate_error(response, ApiErrorId.ERR_INDEX_QUOTE_MISSING.value, 422)

    unpriced = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert unpriced["status"] == "DRAFT"
    assert unpriced["quoted_unit_price_per_ton"] is None
    assert unpriced["fuel_surcharge_per_ton"] is None
    assert unpriced["extended_contract_value"] is None
    assert unpriced["index_quote_month_used"] is None
    assert unpriced["version"] == version_before, \
        "2026-07 has no quote at all, so nothing was written"
