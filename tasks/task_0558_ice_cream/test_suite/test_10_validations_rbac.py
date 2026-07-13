"""Isolated business-rule violations, RBAC forbidden/unauthenticated, list & remove endpoints.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_flavor, make_size, make_batch, make_station, make_pre_order,
    open_drawer, open_order, add_line, get_order, get_batch, get_order_line,
    create_flavor_payload,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
LEAD = TEST_USERS["shift_lead_headers"]
SCOOP = TEST_USERS["scooper_headers"]
BAKER = TEST_USERS["baker_headers"]


# ─────────────── validations (corner) ───────────────

def test_insufficient_batch_volume_isolated(api):
    """PRD 3.3: "If the combined headroom across all candidate batches is less than
    the needed volume, the line is rejected with `ERR_INSUFFICIENT_BATCH_VOLUME`
    and nothing is reserved."

    Design: Corner/validations/insufficient_batch_volume_isolated
    """
    flavor = make_flavor(par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    make_batch(flavor["id"], initial_volume_ml=90)  # 90 ml headroom, DOUBLE needs 180
    drawer = open_drawer()
    order = open_order(drawer["id"])  # no loyalty attached -> only headroom can fail
    res = api.add_line(order["id"], {"size_option_id": size["id"], "flavor_id": flavor["id"]}, SCOOP)
    validate_error(res, "ERR_INSUFFICIENT_BATCH_VOLUME")


def test_insufficient_cash_tendered_on_pay(api):
    """PRD 3.4: "For a cash payment, the `tendered_cash_cents` must be at least the
    `total_cents`; a short tender is rejected with `ERR_INSUFFICIENT_CASH_TENDERED`."

    Design: Corner/validations/insufficient_cash_tendered_on_pay
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])  # total 381
    res = api.pay_order(order["id"], {"payment_method": "CASH", "tendered_cash_cents": 300}, SCOOP)
    validate_error(res, "ERR_INSUFFICIENT_CASH_TENDERED")


# ─────────────── rbac (corner) ───────────────

def test_baker_cannot_create_flavor_forbidden(api):
    """PRD 2.1: "A request that is authenticated but whose role is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN`."
    PRD 2.1: "a `Manager` owns catalog and configuration ... and a `Baker` owns
    production — batches, releases, waste, and the production transitions of cakes."

    Design: Corner/rbac/baker_cannot_create_flavor_forbidden
    """
    validate_error(api.create_flavor(create_flavor_payload(), BAKER), "ERR_FORBIDDEN")


def test_scooper_cannot_open_drawer_forbidden(api):
    """PRD 2.1: "A request that is authenticated but whose role is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN`."
    PRD 2.1: "a `ShiftLead` owns the cash drawer, voids, and refunds".

    Design: Corner/rbac/scooper_cannot_open_drawer_forbidden
    """
    validate_error(api.create_drawer({"opening_float_cents": 10000}, SCOOP), "ERR_FORBIDDEN")


def test_scooper_cannot_requote_forbidden(api):
    """PRD 2.1: "A request that is authenticated but whose role is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN`."
    PRD 3.6: "A `Manager` re-quotes it, replacing `quoted_price_cents` with a new
    value and incrementing the pre-order's `version` by one."

    Design: Corner/rbac/scooper_cannot_requote_forbidden
    """
    flavor = make_flavor(par_level_ml=300)
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"])
    res = api.requote_pre_order(
        po["id"], {"quoted_price_cents": 4500, "expected_preorder_version": po["version"]}, SCOOP)
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_auth_header_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or that carries an
    `X-User-Role` value outside these four, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    validate_error(api.list_flavors(headers={}), "ERR_UNAUTHENTICATED")


# ─────────────── endpoints (corner) ───────────────

def test_list_flavors_pagination_envelope(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum
    of 100."
    PRD 2.3: "List responses include the following fields in the `meta` object of
    the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_flavors_pagination_envelope
    """
    make_flavor(name="Vanilla")
    make_flavor(name="Chocolate", standard_cost_cents_per_ml=1.90)
    data, meta = validate_paginated(api.list_flavors(MGR, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_remove_line_recomputes_order_totals_immediate(api):
    """PRD 3.3: "A line may be removed from an open ticket, which moves it from
    `ACTIVE` to `REMOVED` and releases its reservation by lowering each affected
    batch's `reserved_volume_ml` ... Adding or removing a line recomputes the
    order's running totals."

    Design: Corner/endpoints/remove_line_recomputes_order_totals_immediate
    """
    flavor = make_flavor(par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch = make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])  # reserves 180
    validate_success(api.remove_line(order["id"], line["id"], SCOOP), 200)
    assert get_order_line(line["id"])["status"] == "REMOVED"
    assert get_order(order["id"])["subtotal_cents"] == 0
    assert get_batch(batch["id"])["reserved_volume_ml"] == 0
