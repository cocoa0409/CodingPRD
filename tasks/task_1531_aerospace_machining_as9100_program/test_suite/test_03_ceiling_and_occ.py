"""Agreement funds conservation, optimistic concurrency, price pinning (PRD §2.7, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_purchase_order,
    create_active_lta,
    create_purchase_order,
    get_lta,
    get_purchase_order,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / lta_ceiling_conservation
# ---------------------------------------------------------------------------

def test_po_create_debits_lta_ceiling(api):
    """PRD §3.2: "Every purchase order debits the agreement's funds:
    `remaining_ceiling_cents` is reduced by the order's `total_cents`, and an
    order whose total would drive the remainder negative is rejected with
    `ERR_LTA_CEILING_EXCEEDED` (402)."

    Design: Difficulty/compensating_invariant/lta_ceiling_conservation
    """
    lta = create_active_lta(
        ceiling_cents=100000000,
        pricing_tiers=[
            {"min_qty": 1, "unit_price_cents": 5000},
            {"min_qty": 100, "unit_price_cents": 4500},
        ],
        escalation_pct_per_year=0.0,
    )
    po = create_purchase_order(lta["id"], quantity=100)
    assert po["total_cents"] == 450000, f"100 x 4500 = 450000, got {po['total_cents']}"
    lta_after = get_lta(lta["id"])
    assert lta_after["remaining_ceiling_cents"] == 100000000 - 450000, (
        f"ceiling must be debited by the PO total, got "
        f"{lta_after['remaining_ceiling_cents']}"
    )


def test_po_cancel_restores_lta_ceiling(api):
    """PRD §3.2: "The cancellation cascade then restores consistency: every
    work order of the order still in `PLANNED` or `RELEASED` is cancelled, each
    first returning its `quantity` to the order's `unreleased_quantity`; the
    order's `total_cents` is added back to the agreement's
    `remaining_ceiling_cents`; and the agreement's `version` increments by
    one."

    Design: Difficulty/compensating_invariant/lta_ceiling_conservation
    """
    lta = create_active_lta(
        ceiling_cents=100000000,
        pricing_tiers=[
            {"min_qty": 1, "unit_price_cents": 5000},
            {"min_qty": 100, "unit_price_cents": 4500},
        ],
        escalation_pct_per_year=0.0,
    )
    po = create_purchase_order(lta["id"], quantity=100)
    assert get_lta(lta["id"])["remaining_ceiling_cents"] == 100000000 - 450000
    cancelled = validate_success(
        api_client.cancel_purchase_order(po["id"], CM), expected_status=200
    )
    assert cancelled["status"] == "CANCELLED"
    lta_after = get_lta(lta["id"])
    assert lta_after["remaining_ceiling_cents"] == 100000000, (
        f"cancelling the PO must restore the ceiling exactly, got "
        f"{lta_after['remaining_ceiling_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / occ_po_create_stale_version
# ---------------------------------------------------------------------------

def test_occ_po_create_stale_version(api):
    """PRD §2.7: "Two write operations on the commercial record are guarded by
    optimistic concurrency: creating a purchase order against an agreement, and
    amending an agreement's commercial terms. Both requests must carry
    `expected_lta_version`, a non-optional input field holding the agreement
    `version` the client last observed. If the value does not match the
    agreement's current `version` — because another write has advanced the
    agreement since the client last read it — the request is rejected with
    `ERR_STALE_LTA_VERSION` (HTTP 412), preventing the client from building on
    commercial terms it has not observed."

    Design: Corner/cross_cutting_layers/occ_po_create_stale_version
    """
    lta = create_active_lta(escalation_pct_per_year=0.0)
    stale_version = lta["version"]
    # First create succeeds and advances the agreement version.
    po1 = create_purchase_order(
        lta["id"], expected_lta_version=stale_version, quantity=1
    )
    assert_purchase_order(po1)
    assert get_lta(lta["id"])["version"] != stale_version
    # Second create still carrying the pre-write version is rejected.
    resp = api_client.create_purchase_order(
        {
            "lta_id": lta["id"],
            "po_number": "PO-OCC-2",
            "part_number": "P-OCC",
            "part_revision": "A",
            "quantity": 1,
            "flowdown_clauses": ["AS9100D_QMS"],
            "requires_special_process": False,
            "delivery_year": 2026,
            "expected_lta_version": stale_version,
        },
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LTA_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / occ_amend_stale_version
# ---------------------------------------------------------------------------

def test_occ_amend_stale_version(api):
    """PRD §2.7: "Two write operations on the commercial record are guarded by
    optimistic concurrency: creating a purchase order against an agreement, and
    amending an agreement's commercial terms."
    PRD §3.1: "Amendment leaves the agreement's state unchanged, attempts to
    amend in any other state are rejected with `ERR_INVALID_STATE`, and the
    amendment is OCC-guarded per §2.7: a stale `expected_lta_version` yields
    `ERR_STALE_LTA_VERSION` (412). Every amendment increments the agreement's
    `version` by one."

    Design: Corner/cross_cutting_layers/occ_amend_stale_version
    """
    lta = create_active_lta(escalation_pct_per_year=0.0)
    stale_version = lta["version"]
    amended = validate_success(
        api_client.amend_lta(
            lta["id"],
            {
                "expected_lta_version": stale_version,
                "pricing_tiers": [{"min_qty": 1, "unit_price_cents": 4800}],
            },
            CM,
        ),
        expected_status=200,
    )
    assert amended["version"] == stale_version + 1, (
        f"a successful amendment increments version by one, got "
        f"{amended['version']} (was {stale_version})"
    )
    resp = api_client.amend_lta(
        lta["id"],
        {"expected_lta_version": stale_version, "ceiling_cents": 90000000},
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LTA_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / po_price_pinned_after_lta_amend
# ---------------------------------------------------------------------------

def test_po_price_pinned_after_lta_amend(api):
    """PRD §3.1: "Crucially, amendment never reprices existing purchase orders:
    their pricing stays pinned to the agreement version recorded on each order
    as `lta_version_pinned`."
    PRD §3.2: "The agreement version observed at creation is recorded as
    `lta_version_pinned`, and later amendments never reprice the order — two
    orders for identical quantities placed before and after an amendment can
    legitimately carry different unit prices."

    Design: Corner/cross_cutting_layers/po_price_pinned_after_lta_amend
    """
    lta = create_active_lta(
        pricing_tiers=[
            {"min_qty": 1, "unit_price_cents": 5000},
            {"min_qty": 100, "unit_price_cents": 4500},
        ],
        escalation_pct_per_year=0.0,
    )
    po1 = create_purchase_order(lta["id"], quantity=10)
    assert po1["unit_price_cents"] == 5000

    amended = validate_success(
        api_client.amend_lta(
            lta["id"],
            {
                "expected_lta_version": get_lta(lta["id"])["version"],
                "pricing_tiers": [
                    {"min_qty": 1, "unit_price_cents": 4500},
                    {"min_qty": 100, "unit_price_cents": 4000},
                ],
            },
            CM,
        ),
        expected_status=200,
    )
    po2 = create_purchase_order(
        lta["id"], expected_lta_version=amended["version"], quantity=10
    )
    assert po2["unit_price_cents"] == 4500, (
        f"a new PO prices against the amended table (4500), got "
        f"{po2['unit_price_cents']}"
    )
    po1_after = get_purchase_order(po1["id"])
    assert po1_after["unit_price_cents"] == 5000, (
        f"the pre-amendment PO keeps its pinned price 5000, got "
        f"{po1_after['unit_price_cents']}"
    )
    assert po1_after["lta_version_pinned"] != po2["lta_version_pinned"], (
        "the two POs must be pinned to different agreement versions"
    )
