"""Optimistic concurrency control on quoting (PRD §2.6, §3.3)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_fixture, create_order, add_line, order_version,
)

SM = TEST_USERS["sm_headers"]


def test_stale_expected_version_quote_rejected(api):
    """PRD §2.6: "The server compares `expected_order_version` against the target order's
    current `version`. If they match, the quote proceeds; if the order's `version` has
    advanced since the client last observed it — because another writer added a line or
    re-quoted the order in the meantime — then `expected_order_version` is stale and the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_quote_rejected
    """
    fx = create_fixture(api, sku_base="F-OCC", base_price_cents=5000, base_wattage=40)
    o = create_order(api, customer_name="OCC")
    add_line(api, o["id"], fx["id"], quantity=1)
    ov = order_version(api, o["id"])
    validate_success(api.quote_order(o["id"], {"expected_order_version": ov}, SM), 200)  # bumps version
    resp = api.quote_order(o["id"], {"expected_order_version": ov}, SM)  # stale token
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_correct_version_quote_succeeds_and_bumps_version(api):
    """PRD §3.3: "Both forms require the order to currently be in the state they act on and
    both require the concurrency token described earlier: the request carries
    `expected_order_version`, which must equal the order's current `version`, failing which
    the quote is rejected with `ERR_STALE_VERSION`. A successful quote increments the order's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_quote_succeeds_and_bumps
    """
    fx = create_fixture(api, sku_base="F-OCC2", base_price_cents=5000, base_wattage=40)
    o = create_order(api, customer_name="OCC2")
    add_line(api, o["id"], fx["id"], quantity=1)
    ov = order_version(api, o["id"])
    quoted = validate_success(api.quote_order(o["id"], {"expected_order_version": ov}, SM), 200)
    assert quoted["fulfillment_status"] == "QUOTED"
    assert quoted["version"] == ov + 1
