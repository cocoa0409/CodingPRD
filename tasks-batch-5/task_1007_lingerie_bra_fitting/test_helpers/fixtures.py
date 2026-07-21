"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (empty database, logical clock at 2026-07-01)
before every test, so each fixture builds all of its preconditions from scratch
using only PRD-declared endpoints. Setup calls use get_success_data() (the lenient
validator) so any setup failure surfaces as a clear error, not a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_loyalty_adjustment_payload,
    create_fitter_payload,
    create_room_payload,
    create_appointment_payload,
    create_fit_payload,
    create_product_payload,
    create_sku_payload,
    create_order_payload,
    create_order_line_payload,
    create_exchange_payload,
    create_insurance_claim_payload,
    adjudicate_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_fitter_headers,
)

_SM = TEST_USERS["store_manager_headers"]
_BC = TEST_USERS["billing_clerk_headers"]


# ─── Primitive builders ───────────────────────────────────────────────────
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), _SM))


def new_customer(points: int = 0, **overrides) -> dict:
    """Create a customer; when points != 0, credit them via a loyalty adjustment
    and return the refreshed customer (so loyalty_points / loyalty_tier are current)."""
    cust = get_success_data(api_client.create_customer(create_customer_payload(**overrides), _SM))
    if points:
        api_client.create_loyalty_adjustment(
            cust["id"], create_loyalty_adjustment_payload(points, "PROMOTION"), _SM
        )
        cust = get_success_data(api_client.get_customer(cust["id"], _SM))
    return cust


def new_fitter(post_surgical_certified: bool = False, is_active: bool = True, **overrides) -> dict:
    payload = create_fitter_payload(
        post_surgical_certified=post_surgical_certified, is_active=is_active, **overrides
    )
    return get_success_data(api_client.create_fitter(payload, _SM))


def new_room(capacity: int = 5, is_private: bool = False, is_active: bool = True, **overrides) -> dict:
    payload = create_room_payload(
        capacity=capacity, is_private=is_private, is_active=is_active, **overrides
    )
    return get_success_data(api_client.create_room(payload, _SM))


def new_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_payload(**overrides), _SM))


def new_sku(product_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_sku(create_sku_payload(product_id, **overrides), _SM))


def get_sku(sku_id: str) -> dict:
    return get_success_data(api_client.get_sku(sku_id, _SM))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, _SM))


def get_line(line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(line_id, _SM))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, _SM))


# ─── Tier 1: Appointment state progression ────────────────────────────────
def setup_booked_appointment(
    fitting_type: str = "STANDARD",
    post_surgical_certified: bool = False,
    is_private: bool = False,
    capacity: int = 5,
    scheduled_start: str = "2026-07-02T10:00:00Z",
    **appt_overrides,
) -> dict:
    """A freshly booked (REQUESTED) appointment plus its customer, fitter and room."""
    cust = new_customer()
    fitter = new_fitter(post_surgical_certified=post_surgical_certified)
    room = new_room(capacity=capacity, is_private=is_private)
    appt = get_success_data(
        api_client.create_appointment(
            create_appointment_payload(
                cust["id"], fitter["id"], room["id"],
                fitting_type=fitting_type, scheduled_start=scheduled_start, **appt_overrides,
            ),
            make_customer_headers(cust["id"]),
        )
    )
    return {"customer": cust, "fitter": fitter, "room": room, "appointment": appt}


def setup_confirmed_appointment(**kwargs) -> dict:
    """A CONFIRMED appointment (booked, then confirmed by the assigned fitter)."""
    ctx = setup_booked_appointment(**kwargs)
    confirmed = get_success_data(
        api_client.confirm_appointment(
            ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"])
        )
    )
    ctx["appointment"] = confirmed
    return ctx


def setup_checked_in_appointment(**kwargs) -> dict:
    """A CHECKED_IN appointment; also records the current version (post check-in)."""
    ctx = setup_confirmed_appointment(**kwargs)
    checked_in = get_success_data(
        api_client.checkin_appointment(
            ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"])
        )
    )
    ctx["appointment"] = checked_in
    ctx["version"] = checked_in["version"]
    return ctx


def submit_fit(ctx: dict, underbust_cm, bust_cm, fit_preference: str = "STANDARD") -> dict:
    """Submit a fit against a CHECKED_IN appointment using its recorded version."""
    payload = create_fit_payload(
        underbust_cm, bust_cm, ctx["version"], fit_preference=fit_preference
    )
    fitted = get_success_data(
        api_client.fit_appointment(
            ctx["appointment"]["id"], payload, make_fitter_headers(ctx["fitter"]["id"])
        )
    )
    ctx["appointment"] = fitted
    ctx["version"] = fitted["version"]
    return fitted


# ─── Tier 2: Order construction ───────────────────────────────────────────
def setup_order_with_line(
    category: str = "EVERYDAY_BRA",
    base_price_cents: int = 4000,
    hygiene_class=None,
    initial_stock: int = 5,
    quantity: int = 1,
    band_size: int = 34,
    cup_size: str = "C",
    is_active_sku: bool = True,
    order_type=None,
    is_gift: bool = False,
    points: int = 0,
    **_,
) -> dict:
    """A DRAFT order carrying one ACTIVE line, plus its customer/product/SKU."""
    cust = new_customer(points=points)
    prod_kwargs = {"category": category, "base_price_cents": base_price_cents}
    if hygiene_class is not None:
        prod_kwargs["hygiene_class"] = hygiene_class
    prod = new_product(**prod_kwargs)
    sku = new_sku(
        prod["id"], band_size=band_size, cup_size=cup_size,
        initial_stock=initial_stock, is_active=is_active_sku,
    )
    order_kwargs = {}
    if order_type is not None:
        order_kwargs["order_type"] = order_type
    if is_gift:
        order_kwargs["is_gift"] = True
    order = get_success_data(
        api_client.create_order(
            create_order_payload(cust["id"], **order_kwargs), make_customer_headers(cust["id"])
        )
    )
    line = get_success_data(
        api_client.add_order_line(
            order["id"], create_order_line_payload(sku["id"], quantity),
            make_customer_headers(cust["id"]),
        )
    )
    return {"customer": cust, "product": prod, "sku": sku, "order": order, "line": line}


def _place(ctx: dict) -> dict:
    ctx["order"] = get_success_data(
        api_client.place_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
    )
    return ctx


def _pay(ctx: dict) -> dict:
    ctx["order"] = get_success_data(api_client.pay_order(ctx["order"]["id"], _BC))
    return ctx


def _fulfill(ctx: dict) -> dict:
    ctx["order"] = get_success_data(api_client.fulfill_order(ctx["order"]["id"], _SM))
    return ctx


def setup_placed_order(**kwargs) -> dict:
    return _place(setup_order_with_line(**kwargs))


def setup_paid_order(**kwargs) -> dict:
    return _pay(_place(setup_order_with_line(**kwargs)))


def setup_fulfilled_line(**kwargs) -> dict:
    """A single-line order carried all the way through FULFILLED; `line` is refreshed."""
    ctx = _fulfill(_pay(_place(setup_order_with_line(**kwargs))))
    ctx["line"] = get_line(ctx["line"]["id"])
    return ctx


# ─── Tier 3: Multi-line orders for loyalty / discount arithmetic ──────────
def setup_gold_multiline_placed_order(unit_price_cents: int = 525, n_lines: int = 2) -> dict:
    """A GOLD customer (5000 pts) with `n_lines` ACTIVE lines of gross `unit_price_cents`
    on a placed (unpaid) order. Each SKU is a non-extended size so price == base price."""
    cust = new_customer(points=5000)
    prod = new_product(category="EVERYDAY_BRA", base_price_cents=unit_price_cents)
    order = get_success_data(
        api_client.create_order(create_order_payload(cust["id"]), make_customer_headers(cust["id"]))
    )
    skus, lines = [], []
    for i in range(n_lines):
        sku = new_sku(prod["id"], band_size=34 + 2 * i, cup_size="C", initial_stock=5)
        skus.append(sku)
        line = get_success_data(
            api_client.add_order_line(
                order["id"], create_order_line_payload(sku["id"], 1),
                make_customer_headers(cust["id"]),
            )
        )
        lines.append(line)
    order = get_success_data(
        api_client.place_order(order["id"], make_customer_headers(cust["id"]))
    )
    return {"customer": cust, "product": prod, "order": order, "skus": skus, "lines": lines}


# ─── Tier 4: Mastectomy / insurance setup ─────────────────────────────────
def setup_paid_mastectomy_order(base_price_cents: int = 20000, quantity: int = 1, points: int = 0) -> dict:
    """A PAID order containing a single MASTECTOMY_BRA line (band 34 / cup C, not
    extended, so line gross == base_price_cents * quantity)."""
    return setup_paid_order(
        category="MASTECTOMY_BRA",
        base_price_cents=base_price_cents,
        hygiene_class="INTIMATE_NON_RETURNABLE",
        initial_stock=5,
        quantity=quantity,
        points=points,
    )


def submit_claim(ctx: dict) -> dict:
    claim = get_success_data(
        api_client.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), _BC)
    )
    ctx["claim"] = claim
    return claim


def adjudicate(ctx: dict, decision: str, adjudicated_amount_cents=None) -> dict:
    claim = get_success_data(
        api_client.adjudicate_claim(
            ctx["claim"]["id"], adjudicate_payload(decision, adjudicated_amount_cents), _BC
        )
    )
    ctx["claim"] = claim
    return claim


# ─── Tier 5: Exchange / reminder helpers ──────────────────────────────────
def request_exchange(ctx: dict, item_condition: str = "SEALED") -> dict:
    """Request an exchange against the context's fulfilled line."""
    exch = get_success_data(
        api_client.create_exchange(
            create_exchange_payload(ctx["order"]["id"], ctx["line"]["id"], item_condition),
            make_customer_headers(ctx["customer"]["id"]),
        )
    )
    return exch


def get_reminder_for_line(line_id: str) -> dict:
    """Return the (single) reminder seeded for a fulfilled bra line."""
    data, _meta = _list_reminders(order_line_id=line_id)
    assert data, f"Setup expected a reminder for line {line_id}"
    return data[0]


def _list_reminders(**params):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_reminders(_SM, params=params))
