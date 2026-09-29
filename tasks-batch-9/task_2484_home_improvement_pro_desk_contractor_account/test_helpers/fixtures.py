"""Composite setup helpers.

Every test starts against an empty database, so every precondition here is built
from published endpoints only. Setup calls use the lenient success reader so a
broken precondition surfaces as a setup failure rather than a confusing
assertion mismatch.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BASELINE_VOLUME_FOR_TIER,
    LIST_PRICE_CENTS,
    SKU_MORTAR_BAG,
    SKU_SHINGLE_BUNDLE,
    SKU_TRIM_PACK,
    TEST_DEFAULTS,
)
from .factories import (
    counter_offer_line_price,
    create_credit_line_payload,
    create_delivery_appointment_payload,
    create_delivery_truck_payload,
    create_job_quote_payload,
    create_order_line_payload,
    create_pro_account_payload,
    create_pro_order_payload,
    create_quote_line_payload,
    create_return_request_payload,
    create_store_payload,
    create_store_stock_payload,
    create_tax_exempt_certificate_payload,
    create_will_call_staging_payload,
    return_line,
)
from .test_users import (
    CREDIT_MANAGER,
    PLATFORM_ADMIN,
    PRO_DESK_ASSOCIATE,
    STORE_OPERATIONS,
    TAX_COMPLIANCE_OFFICER,
    make_contractor_admin_headers,
)


# =========================================================================== #
# Tier 0 — single-call primitives                                             #
# =========================================================================== #


def set_clock(to_iso8601: str) -> str:
    """Move the logical clock and return the new reading."""
    data = get_success_data(api_client.set_current_utc(to_iso8601, PLATFORM_ADMIN))
    return data["current_utc"]


def create_store(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_store(create_store_payload(**overrides), PLATFORM_ADMIN)
    )


def create_store_stock(
    store_id: str, sku: str = SKU_SHINGLE_BUNDLE, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_store_stock(
            create_store_stock_payload(store_id, sku, **overrides), PLATFORM_ADMIN
        )
    )


def create_delivery_truck(store_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_delivery_truck(
            create_delivery_truck_payload(store_id, **overrides), STORE_OPERATIONS
        )
    )


def create_pro_account(home_store_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pro_account(
            create_pro_account_payload(home_store_id, **overrides), PLATFORM_ADMIN
        )
    )


def create_credit_line(pro_account_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_credit_line(
            create_credit_line_payload(pro_account_id, **overrides), CREDIT_MANAGER
        )
    )


def read_pro_account(pro_account_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_pro_account(
            pro_account_id, make_contractor_admin_headers(pro_account_id)
        )
    )


def read_pro_order(pro_order_id: str, account_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_pro_order(pro_order_id, make_contractor_admin_headers(account_id))
    )


def read_credit_line(credit_line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_credit_line(credit_line_id, CREDIT_MANAGER))


def read_store_stock(store_stock_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_store_stock(store_stock_id, STORE_OPERATIONS)
    )


def file_tax_exempt_certificate(
    pro_account_id: str, **overrides
) -> Dict[str, Any]:
    """File a resale certificate, reading the account version the filing pins on."""
    account = read_pro_account(pro_account_id)
    payload = create_tax_exempt_certificate_payload(
        pro_account_id, account["version"], **overrides
    )
    return get_success_data(
        api_client.create_tax_exempt_certificate(
            payload, make_contractor_admin_headers(pro_account_id)
        )
    )


def verify_tax_exempt_certificate(certificate_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_tax_exempt_certificate(
            certificate_id, TAX_COMPLIANCE_OFFICER
        )
    )


# =========================================================================== #
# Tier 1 — provisioned environment                                            #
# =========================================================================== #


DEFAULT_SKU_STOCK = (
    (SKU_SHINGLE_BUNDLE, 600),
    (SKU_MORTAR_BAG, 500),
    (SKU_TRIM_PACK, 400),
)


def setup_store_with_stock(
    skus: Optional[List[Tuple[str, int]]] = None, **store_overrides
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Register one store and stock it. Returns (store, {sku: stock_row})."""
    store = create_store(**store_overrides)
    rows: Dict[str, Dict[str, Any]] = {}
    for sku, on_hand in list(skus or DEFAULT_SKU_STOCK):
        rows[sku] = create_store_stock(
            store["id"],
            sku,
            on_hand_units=on_hand,
            list_unit_price_cents=LIST_PRICE_CENTS[sku],
        )
    return store, rows


def setup_account_at_tier(
    home_store_id: str, tier_code: str = "MEMBER", **account_overrides
) -> Dict[str, Any]:
    """Create an account whose trailing volume places it in the named tier."""
    overrides = {"baseline_volume_cents": BASELINE_VOLUME_FOR_TIER[tier_code]}
    overrides.update(account_overrides)
    return create_pro_account(home_store_id, **overrides)


def setup_pro_desk(
    tier_code: str = "MEMBER",
    skus: Optional[List[Tuple[str, int]]] = None,
    store_overrides: Optional[Dict[str, Any]] = None,
    account_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The common baseline: one stocked store plus one pro account.

    Returns a dict with keys ``store``, ``stocks``, ``account`` and
    ``admin_headers`` (the account's own ContractorAdmin headers).
    """
    store, stocks = setup_store_with_stock(skus, **(store_overrides or {}))
    account = setup_account_at_tier(store["id"], tier_code, **(account_overrides or {}))
    return {
        "store": store,
        "stocks": stocks,
        "account": account,
        "admin_headers": make_contractor_admin_headers(account["id"]),
    }


# =========================================================================== #
# Tier 2 — orders and their lines                                             #
# =========================================================================== #


def create_draft_order(
    account_id: str,
    fulfillment_store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    **order_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a DRAFT order plus its lines. Returns (order, order_lines)."""
    headers = make_contractor_admin_headers(account_id)
    order = get_success_data(
        api_client.create_pro_order(
            create_pro_order_payload(account_id, fulfillment_store_id, **order_overrides),
            headers,
        )
    )
    order_lines = []
    for sku, qty_units in list(lines or []):
        order_lines.append(
            get_success_data(
                api_client.create_order_line(
                    order["id"], create_order_line_payload(sku, qty_units), headers
                )
            )
        )
    return order, order_lines


def submit_order(order_id: str, account_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_pro_order(order_id, make_contractor_admin_headers(account_id))
    )


def reserve_order(order_id: str) -> List[Dict[str, Any]]:
    """Run the sourcing waterfall. Returns the reservations it booked."""
    return get_success_data(api_client.reserve_pro_order(order_id, PRO_DESK_ASSOCIATE))


def allocate_reservations(reservations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        get_success_data(
            api_client.allocate_reservation(reservation["id"], STORE_OPERATIONS)
        )
        for reservation in reservations
    ]


def setup_submitted_order(
    account_id: str,
    store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    **order_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """DRAFT order with lines, then submitted. Returns (submitted order, lines)."""
    order, order_lines = create_draft_order(
        account_id, store_id, lines or [(SKU_SHINGLE_BUNDLE, 10)], **order_overrides
    )
    submitted = submit_order(order["id"], account_id)
    return submitted, order_lines


def setup_reserved_order(
    account_id: str,
    store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    **order_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Submitted then reserved. Returns (order, order_lines, reservations)."""
    order, order_lines = setup_submitted_order(
        account_id, store_id, lines, **order_overrides
    )
    reservations = reserve_order(order["id"])
    order = read_pro_order(order["id"], account_id)
    return order, order_lines, reservations


# =========================================================================== #
# Tier 3 — full fulfillment lifecycles                                        #
# =========================================================================== #


def stage_and_pick_up(
    order_id: str,
    store_id: str,
    stage_start: str = "2026-08-01T08:00:00Z",
    stage_hours: int = 6,
    picked_up_by: str = "Crew A",
) -> Dict[str, Any]:
    """Book a bay, stage it and hand the material over. Returns the staging."""
    staging = get_success_data(
        api_client.create_will_call_staging(
            create_will_call_staging_payload(
                order_id, store_id, stage_start=stage_start, stage_hours=stage_hours
            ),
            STORE_OPERATIONS,
        )
    )
    get_success_data(
        api_client.stage_will_call_staging(staging["id"], STORE_OPERATIONS)
    )
    return get_success_data(
        api_client.pick_up_will_call_staging(
            staging["id"], picked_up_by, STORE_OPERATIONS
        )
    )


def setup_fulfilled_will_call_order(
    account_id: str,
    store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    stage_start: str = "2026-08-01T08:00:00Z",
    stage_hours: int = 6,
    **order_overrides,
) -> Dict[str, Any]:
    """Walk a will-call order all the way to FULFILLED.

    Returns a dict with ``order``, ``order_lines``, ``reservations`` and
    ``staging``.
    """
    order_overrides.setdefault("delivery_mode", "WILL_CALL")
    order, order_lines, reservations = setup_reserved_order(
        account_id, store_id, lines, **order_overrides
    )
    allocate_reservations(reservations)
    staging = stage_and_pick_up(
        order["id"], store_id, stage_start=stage_start, stage_hours=stage_hours
    )
    return {
        "order": read_pro_order(order["id"], account_id),
        "order_lines": order_lines,
        "reservations": reservations,
        "staging": staging,
    }


def deliver_order(
    order_id: str,
    truck_id: str,
    window_start: str = "2026-08-05T09:00:00Z",
    window_end: str = "2026-08-05T11:00:00Z",
    jobsite_access_type: str = "CURBSIDE",
) -> Dict[str, Any]:
    """Book, confirm and complete a delivery appointment. Returns the appointment."""
    appointment = get_success_data(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                order_id,
                truck_id,
                window_start=window_start,
                window_end=window_end,
                jobsite_access_type=jobsite_access_type,
            ),
            STORE_OPERATIONS,
        )
    )
    get_success_data(
        api_client.confirm_delivery_appointment(appointment["id"], STORE_OPERATIONS)
    )
    return get_success_data(
        api_client.complete_delivery_appointment(appointment["id"], STORE_OPERATIONS)
    )


def setup_fulfilled_delivery_order(
    account_id: str,
    store_id: str,
    truck_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    window_start: str = "2026-08-05T09:00:00Z",
    window_end: str = "2026-08-05T11:00:00Z",
    jobsite_access_type: str = "CURBSIDE",
    **order_overrides,
) -> Dict[str, Any]:
    """Walk a delivery order all the way to FULFILLED."""
    order_overrides.setdefault("delivery_mode", "DELIVERY")
    order, order_lines, reservations = setup_reserved_order(
        account_id, store_id, lines, **order_overrides
    )
    appointment = deliver_order(
        order["id"],
        truck_id,
        window_start=window_start,
        window_end=window_end,
        jobsite_access_type=jobsite_access_type,
    )
    return {
        "order": read_pro_order(order["id"], account_id),
        "order_lines": order_lines,
        "reservations": reservations,
        "appointment": appointment,
    }


def invoice_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.invoice_pro_order(order_id, CREDIT_MANAGER))


def pay_order(order_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.pay_pro_order(order_id, amount_cents, CREDIT_MANAGER)
    )


def setup_invoiced_will_call_order(
    account_id: str,
    store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    stage_start: str = "2026-08-01T08:00:00Z",
    stage_hours: int = 6,
    **order_overrides,
) -> Dict[str, Any]:
    """Fulfil a will-call credit order and invoice it. Returns the fulfilment dict."""
    order_overrides.setdefault("payment_method", "CREDIT_LINE")
    bundle = setup_fulfilled_will_call_order(
        account_id,
        store_id,
        lines,
        stage_start=stage_start,
        stage_hours=stage_hours,
        **order_overrides,
    )
    bundle["order"] = invoice_order(bundle["order"]["id"])
    return bundle


# =========================================================================== #
# Tier 4 — quote negotiation                                                  #
# =========================================================================== #


def create_draft_quote(
    account_id: str,
    store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    **quote_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a DRAFT quote plus its lines. Returns (quote, quote_lines)."""
    headers = make_contractor_admin_headers(account_id)
    quote = get_success_data(
        api_client.create_job_quote(
            create_job_quote_payload(account_id, store_id, **quote_overrides), headers
        )
    )
    quote_lines = []
    for sku, qty_units in list(lines or [(SKU_SHINGLE_BUNDLE, 8)]):
        quote_lines.append(
            get_success_data(
                api_client.create_quote_line(
                    quote["id"], create_quote_line_payload(sku, qty_units), headers
                )
            )
        )
    return quote, quote_lines


def submit_quote(quote_id: str, account_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_job_quote(quote_id, make_contractor_admin_headers(account_id))
    )


def counter_offer(
    quote_id: str,
    quote_lines: List[Dict[str, Any]],
    negotiated_unit_price_cents: int,
    term_days: int,
    expected_job_quote_version: int,
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """Write one negotiation round priced uniformly across every line."""
    line_prices = [
        counter_offer_line_price(line["id"], negotiated_unit_price_cents)
        for line in quote_lines
    ]
    return get_success_data(
        api_client.counter_offer_job_quote(
            quote_id,
            line_prices,
            term_days,
            expected_job_quote_version,
            headers or PRO_DESK_ASSOCIATE,
        )
    )


def setup_accepted_quote(
    account_id: str,
    store_id: str,
    lines: Optional[List[Tuple[str, int]]] = None,
    negotiated_unit_price_cents: int = 1_500,
    term_days: int = 45,
    **quote_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create, submit, counter, approve and accept a quote.

    Returns (accepted quote, quote_lines).
    """
    quote_overrides.setdefault("requested_term_days", term_days)
    quote, quote_lines = create_draft_quote(
        account_id, store_id, lines, **quote_overrides
    )
    submitted = submit_quote(quote["id"], account_id)
    counter_offer(
        quote["id"],
        quote_lines,
        negotiated_unit_price_cents,
        term_days,
        submitted["version"],
    )
    get_success_data(api_client.approve_job_quote(quote["id"], CREDIT_MANAGER))
    accepted = get_success_data(
        api_client.accept_job_quote(
            quote["id"], make_contractor_admin_headers(account_id)
        )
    )
    refreshed_lines = [
        get_success_data(
            api_client.get_quote_line(
                line["id"], make_contractor_admin_headers(account_id)
            )
        )
        for line in quote_lines
    ]
    return accepted, refreshed_lines


# =========================================================================== #
# Tier 5 — returns, rebates and terminal states                               #
# =========================================================================== #


def request_return(
    order_id: str,
    account_id: str,
    lines: List[Tuple[str, int]],
    reason_code: str = "OVER_ORDERED",
) -> Dict[str, Any]:
    payload = create_return_request_payload(
        order_id,
        [return_line(order_line_id, qty) for order_line_id, qty in lines],
        reason_code=reason_code,
    )
    return get_success_data(
        api_client.create_return_request(
            payload, make_contractor_admin_headers(account_id)
        )
    )


def approve_return(return_request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_return_request(return_request_id, PRO_DESK_ASSOCIATE)
    )


def credit_return(return_request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.credit_return_request(return_request_id, CREDIT_MANAGER)
    )


def setup_credited_return(
    order_id: str,
    account_id: str,
    lines: List[Tuple[str, int]],
    reason_code: str = "OVER_ORDERED",
) -> Dict[str, Any]:
    """Request, approve and credit a return in one go."""
    request = request_return(order_id, account_id, lines, reason_code)
    approve_return(request["id"])
    return credit_return(request["id"])


def list_rebate_accruals(account_id: str, payout_status: Optional[str] = None) -> List[dict]:
    params: Dict[str, Any] = {"pro_account_id": account_id}
    if payout_status is not None:
        params["payout_status"] = payout_status
    return get_success_data(
        api_client.list_rebate_accruals(CREDIT_MANAGER, params=params)
    )


def freeze_credit_line(credit_line_id: str, reason_code: str = "MANUAL_REVIEW") -> Dict[str, Any]:
    return get_success_data(
        api_client.freeze_credit_line(credit_line_id, reason_code, CREDIT_MANAGER)
    )


def setup_account_with_credit_line(
    tier_code: str = "GOLD",
    limit_cents: int = 100_000_000,
    terms_days: int = 30,
    skus: Optional[List[Tuple[str, int]]] = None,
    store_overrides: Optional[Dict[str, Any]] = None,
    account_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Stocked store + account at a tier + an open credit line.

    Returns the ``setup_pro_desk`` dict extended with ``credit_line``.
    """
    scenario = setup_pro_desk(
        tier_code=tier_code,
        skus=skus,
        store_overrides=store_overrides,
        account_overrides=account_overrides,
    )
    scenario["credit_line"] = create_credit_line(
        scenario["account"]["id"], limit_cents=limit_cents, terms_days=terms_days
    )
    return scenario
