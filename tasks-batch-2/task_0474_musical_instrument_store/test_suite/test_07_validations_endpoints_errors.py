"""Breadth tests over body-FK / fiscal validations, action endpoints, sub-resource
reads, and error conditions (pagination range, luthier assignment gate).
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    make_customer_headers, make_luthier_headers,
    create_customer,
    create_reserved_unit, setup_rto_with_n_paid_months, setup_ticket_in_progress,
    read_agreement,
    ApiErrorId,
    create_agreement_payload, buyout_payload, reserve_unit_payload, rent_payment_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Corner / validations
# ===========================================================================
def test_payoff_mismatch_rejects_wrong_amount(api):
    """PRD §3.4: "the submitted amount_cents must equal the agreement's current
    payoff_quote_cents to the cent; any other amount is rejected with
    ERR_PAYOFF_MISMATCH."

    Design: Corner/validations/payoff_mismatch_rejects_wrong_amount
    """
    customer, agreement, unit = setup_rto_with_n_paid_months(
        num_months=3, list_price_cents=120000, monthly_rent_cents=10000, equity_rate_pct=0.50,
    )
    cust_headers = make_customer_headers(customer["id"])
    av = read_agreement(agreement["id"], customer["id"])["version"]
    # payoff quote is 110000; pay 100000 instead
    resp = api.buyout_agreement(agreement["id"], buyout_payload(100000, av), cust_headers)
    validate_error(resp, ApiErrorId.ERR_PAYOFF_MISMATCH.value)
    after = read_agreement(agreement["id"], customer["id"])
    assert after["status"] == "ACTIVE"


def test_reservation_mismatch_wrong_customer_on_agreement(api):
    """PRD §3.2: "The reserved unit must be held for this same customer — the unit's
    reserved_for_customer_id must equal the payload customer_id — otherwise the
    create is rejected with ERR_RESERVATION_MISMATCH."

    Design: Corner/validations/reservation_mismatch_wrong_customer_on_agreement
    """
    c1 = create_customer()
    c2 = create_customer()
    reserved, _ = create_reserved_unit(c1["id"])
    # open an agreement for c2 on a unit reserved for c1
    resp = api.create_agreement(
        create_agreement_payload(c2["id"], reserved["id"], plan="RENTAL"), SA
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_MISMATCH.value)
    unit_after = validate_success(api.get_unit(reserved["id"], SA), 200)
    assert unit_after["status"] == "RESERVED"


# ===========================================================================
# Corner / endpoints
# ===========================================================================
def test_release_reserved_unit_returns_to_available(api):
    """PRD §3.1: "Releasing a reservation returns a `RESERVED` unit to `AVAILABLE`,
    clears `reserved_for_customer_id`, and increments the unit's `version` by 1."

    Design: Corner/endpoints/release_reserved_unit_returns_to_available
    """
    customer = create_customer()
    reserved, _ = create_reserved_unit(customer["id"])
    released = validate_success(api.release_unit(reserved["id"], SA), 200)
    assert released["status"] == "AVAILABLE"


def test_list_payments_filtered_by_agreement_sub_resource(api):
    """PRD §3.2: "Posting appends a `PaymentRecord` whose `kind` is `RENT`, whose
    `status` is `POSTED`, whose `amount_cents` the system sets, and whose
    `billing_cycle_index` records the covered cycle"
    PRD §3.2: "The chronological payment log on an agreement can be listed."

    Design: Corner/endpoints/list_payments_filtered_by_agreement_sub_resource
    """
    customer, agreement, unit = setup_rto_with_n_paid_months(
        num_months=1, list_price_cents=120000, monthly_rent_cents=10000, equity_rate_pct=0.50,
    )
    data, _meta = validate_paginated(api.list_agreement_payments(agreement["id"], SA))
    rents = [r for r in data if r["kind"] == "RENT"]
    assert len(rents) == 1


# ===========================================================================
# Corner / errors
# ===========================================================================
def test_pagination_limit_out_of_range_returns_validation(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum
    of 100."
    PRD §2.3: "A `limit` or `offset` outside its accepted range is rejected with
    `ERR_VALIDATION`."

    Design: Corner/errors/pagination_limit_out_of_range_returns_validation
    """
    resp = api.list_units(SA, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_ticket_action_by_unassigned_luthier_returns_not_assigned(api):
    """PRD §3.6: "only the luthier whose identifier matches the ticket's
    assigned_luthier_id may act on it; a different luthier attempting to work the
    ticket is rejected with ERR_TICKET_NOT_ASSIGNED."

    Design: Corner/errors/ticket_action_by_unassigned_luthier_returns_not_assigned
    """
    ticket = setup_ticket_in_progress(luthier_id="luthier-1")
    resp = api.await_parts_ticket(ticket["id"], make_luthier_headers("luthier-2"))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_ASSIGNED.value)
    after = validate_success(api.get_ticket(ticket["id"], make_luthier_headers("luthier-1")), 200)
    assert after["status"] == "IN_PROGRESS"
