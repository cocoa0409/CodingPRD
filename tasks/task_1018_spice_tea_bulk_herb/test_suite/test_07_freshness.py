"""Lot freshness: inclusive best_by expiry at pack and on read."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_confirmed_order, clock_set, new_product, new_lot,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PROD = TEST_USERS["production_headers"]
CATALOG = TEST_USERS["catalog_headers"]


# ---- boundary_precision_check / freshness_expiry_inclusive_at_pack ----

def _confirmed_lot_expiring_at(api, best_by="2026-08-01T00:00:00Z"):
    ctx = setup_confirmed_order(
        api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5,
        requested_grams=50, allergen_ack=True, lot_grams=100,
        lot_best_by=best_by, clock="2026-06-15T00:00:00Z",
    )
    clock_set(api, best_by)  # clock now exactly at best_by
    return ctx


def test_pack_rejected_when_clock_equals_best_by(api):
    """PRD §2.7: "Comparing the current clock to a lot's `best_by`: if the clock is at or
    after `best_by` (the boundary is inclusive), the lot is `EXPIRED`."
    PRD §3.7: "If the FEFO-selected lot turns out to be expired, packing is rejected with
    `ERR_LOT_EXPIRED`."

    Design: Difficulty/boundary_precision_check/freshness_expiry_inclusive_at_pack
    """
    ctx = _confirmed_lot_expiring_at(api)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 58, "tare_grams": 8}]
    resp = api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD)
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED.value)


def test_lot_reads_expired_exactly_at_best_by(api):
    """PRD §2.7: "Expiry dominates — a lot whose clock has reached `best_by` reads
    `EXPIRED` even if grams remain and even if it was previously drawn to zero."

    Design: Difficulty/boundary_precision_check/freshness_expiry_inclusive_at_pack
    """
    ctx = _confirmed_lot_expiring_at(api)
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    assert lot["status"] == "EXPIRED", lot["status"]


# ---- Corner / calculations / lot_expired_status_on_read ----

def test_lot_past_best_by_reads_expired(api):
    """PRD §2.7: "A lot's freshness is derived, never stored as an input. Comparing the
    current clock to a lot's `best_by`: if the clock is at or after `best_by` (the boundary
    is inclusive), the lot is `EXPIRED`; otherwise, if its remaining `grams_on_hand` is
    zero, it is `DEPLETED`; otherwise it is `AVAILABLE`."

    Design: Corner/calculations/corner_lot_expired_status_on_read
    """
    clock_set(api, "2026-09-01T00:00:00Z")
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    lot = new_lot(api, cham["id"], lot_code="OLD", grams_received=100,
                  received_at="2026-05-01T00:00:00Z", best_by="2026-08-01T00:00:00Z")
    read = validate_success(api.get_inventory_lot(lot["id"], CATALOG))
    assert read["status"] == "EXPIRED", read["status"]
