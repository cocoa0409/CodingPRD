"""Warranty: the delivered-lab-order gate, the remake liability, the supersede
semantics, and the lab-order-version guard on filing."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_warranty_claim,
    create_warranty_claim_payload,
    deliver_lab_order,
    drive_lab_order_to_shipped,
    file_warranty_claim,
    read_lab_order,
    read_warranty_claim,
    set_clock,
    setup_confirmed_order,
    setup_delivered_lab_order,
    setup_delivered_order_with_open_warranty_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import LAB, STORE

# A 6,000c M160 blank, no coatings, no prism, power 2.00 → lens_upcharge_cents 6,000.
M160_ORDER = {
    "frame": {"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
    "material": {"code": "M160", "base_price_cents": 6000, "material_index": 1.60},
    "prescription": {
        "od_sphere": -2.00,
        "od_cylinder": 0.00,
        "os_sphere": -2.00,
        "os_cylinder": 0.00,
        "pd_mm": 62.0,
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# The WarrantyClaim ↔ LabOrder cross-entity state dependency
# ═════════════════════════════════════════════════════════════════════════════

def test_filing_against_a_shipped_but_undelivered_lab_order_is_refused(api):
    """PRD §3.9: "The target lab order's `status` must be `DELIVERED`, with a non-null
    `delivered_at` — glasses still in the lab cannot break — and any other status is refused
    with `ERR_LAB_ORDER_NOT_DELIVERED`."

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_depends_on_lab_order_delivered_state
    """
    scenario = setup_confirmed_order(**M160_ORDER)
    shipped = drive_lab_order_to_shipped(scenario["lab_order"]["id"])
    assert shipped["status"] == "SHIPPED"

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            shipped["id"],
            scenario["customer"]["id"],
            "CUSTOMER_DAMAGE",
            shipped["version"],  # a current version, so the OCC guard passes
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LAB_ORDER_NOT_DELIVERED.value)

    _rows, meta = validate_paginated(
        api.list_warranty_claims(STORE, params={"lab_order_id": shipped["id"]})
    )
    assert meta["total_count"] == 0


def test_handover_unlocks_the_warranty_filing_and_freezes_the_liability(api):
    """PRD §3.7: "It stamps `delivered_at` with the logical clock at that instant, which is the
    anchor for the entire warranty window, and it advances the parent order's
    `fulfillment_status` from `READY_FOR_PICKUP` or from `SHIPPED` to `DELIVERED`."
    PRD §3.9: "`CUSTOMER_DAMAGE` carries the same half-of-the-lens-upcharge share, floored to
    whole cents, **plus** a flat fifteen-dollar — 1,500-cent — reshipping fee, with no grace
    period of any kind; a pair damaged the day after handover is charged exactly as much as one
    damaged eleven months later."

    The same POST flips from refused to accepted purely because the StoreAssociate handed the
    glasses over. The charge is floor(6,000 * 0.5) + 1,500 == 4,500.

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_depends_on_lab_order_delivered_state
    """
    scenario = setup_confirmed_order(**M160_ORDER)
    shipped = drive_lab_order_to_shipped(scenario["lab_order"]["id"])

    refused = api.create_warranty_claim(
        create_warranty_claim_payload(
            shipped["id"], scenario["customer"]["id"], "CUSTOMER_DAMAGE", shipped["version"]
        ),
        scenario["headers"],
    )
    validate_error(refused, ApiErrorId.ERR_LAB_ORDER_NOT_DELIVERED.value)

    delivered = deliver_lab_order(shipped["id"])
    assert delivered["status"] == "DELIVERED"
    # The clock was never moved, so it still reads its 2026-05-01T00:00:00Z default.
    assert_same_instant(delivered["delivered_at"], "2026-05-01T00:00:00Z", "delivered_at")

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            delivered["id"],
            scenario["customer"]["id"],
            "CUSTOMER_DAMAGE",
            delivered["version"],
        ),
        scenario["headers"],
    )
    claim = validate_success(resp, 201)

    assert_warranty_claim(claim)
    assert claim["status"] == "OPEN"
    assert claim["customer_charge_cents"] == 4500
    assert claim["remake_lab_order_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# The remake liability branches
# ═════════════════════════════════════════════════════════════════════════════

def test_an_rx_change_at_exactly_thirty_days_is_still_free(api):
    """PRD §3.9: "An `RX_CHANGE` is free during a thirty-day grace period: when the count of
    whole days since delivery is thirty or fewer the charge is zero, and beyond thirty days the
    customer pays half of the parent order's frozen `lens_upcharge_cents`, floored to whole
    cents."
    PRD §3.9: "And the filing must fall inside the warranty window: the system counts the whole
    days elapsed from the lab order's `delivered_at` to the current logical clock by dividing
    the elapsed time by one day and rounding **down**, and refuses the filing with
    `ERR_WARRANTY_EXPIRED` when that count is **greater than** 365."

    The grace period boundary is inclusive: exactly thirty days still costs nothing.

    Design: Corner/calculations/rx_change_remake_is_free_inside_the_thirty_day_grace
    """
    scenario = setup_delivered_lab_order(**M160_ORDER)
    lab_id = scenario["lab_order"]["id"]

    set_clock("2026-05-31T00:00:00Z")  # exactly 30 days after the 2026-05-01 delivery
    lab = read_lab_order(lab_id)

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            lab_id, scenario["customer"]["id"], "RX_CHANGE", lab["version"]
        ),
        scenario["headers"],
    )
    claim = validate_success(resp, 201)

    assert claim["customer_charge_cents"] == 0
    assert claim["status"] == "OPEN"
    assert claim["reason"] == "RX_CHANGE"


def test_approving_a_manufacturer_defect_mints_a_free_remake_lab_order(api):
    """PRD §3.9: "A `MANUFACTURER_DEFECT` costs the customer nothing at all — the charge is
    zero."
    PRD §3.9: "`APPROVED` advances it `OPEN → APPROVED` and mints a brand-new lab order against
    the same `order_id`: that replacement enters `QUEUED` with `remake_count` back at zero and
    `is_remake` set to true, and its `id` is written to the warranty claim's
    `remake_lab_order_id`."

    Design: Corner/state_machines/warranty_approval_mints_a_remake_lab_order
    """
    scenario = setup_delivered_order_with_open_warranty_claim(reason="MANUFACTURER_DEFECT")
    warranty = scenario["warranty_claim"]
    assert warranty["customer_charge_cents"] == 0

    resp = api.decide_warranty_claim(warranty["id"], {"decision": "APPROVED"}, STORE)
    decided = validate_success(resp, 200)

    assert decided["status"] == "APPROVED"
    assert decided["customer_charge_cents"] == 0
    remake_id = decided["remake_lab_order_id"]
    assert remake_id is not None

    remake = read_lab_order(remake_id)
    assert remake["status"] == "QUEUED"
    assert remake["is_remake"] is True
    assert remake["remake_count"] == 0
    assert remake["order_id"] == scenario["order"]["id"]

    _rows, meta = validate_paginated(
        api.list_lab_orders(LAB, params={"order_id": scenario["order"]["id"]})
    )
    assert meta["total_count"] == 2, "the original and the remake"


def test_filing_a_warranty_claim_after_366_days_is_refused(api):
    """PRD §3.9: "And the filing must fall inside the warranty window: the system counts the
    whole days elapsed from the lab order's `delivered_at` to the current logical clock by
    dividing the elapsed time by one day and rounding **down**, and refuses the filing with
    `ERR_WARRANTY_EXPIRED` when that count is **greater than** 365. A filing at exactly 365 days
    is inside the window and is accepted; a filing at 366 days is not."

    Design: Corner/errors/warranty_filed_after_the_365_day_window_returns_warranty_expired
    """
    scenario = setup_delivered_lab_order(
        frame=M160_ORDER["frame"],
        material=M160_ORDER["material"],
        prescription=dict(
            M160_ORDER["prescription"],
            issued_at="2026-04-01T00:00:00Z",
            expires_at="2028-04-01T00:00:00Z",
        ),
    )
    lab = scenario["lab_order"]

    set_clock("2027-05-02T00:00:00Z")  # 366 days after the 2026-05-01 delivery

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            lab["id"], scenario["customer"]["id"], "CUSTOMER_DAMAGE", lab["version"]
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)

    _rows, meta = validate_paginated(
        api.list_warranty_claims(STORE, params={"lab_order_id": lab["id"]})
    )
    assert meta["total_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# The lab-order-version guard and the supersede semantics
# ═════════════════════════════════════════════════════════════════════════════

def test_re_filing_a_warranty_claim_with_a_spent_lab_order_version_is_rejected(api):
    """PRD §2.7: "Filing a warranty claim — `POST /optical/warranty-claims` — requires a
    non-optional `expected_lab_order_version` field in the request body, carrying the `version`
    of the target `LabOrder` as the client last observed it. If that value does not equal the
    lab order's current `version`, the request is rejected with `ERR_STALE_LAB_ORDER_VERSION`
    (HTTP 412)."
    PRD §3.9: "`CUSTOMER_DAMAGE` carries the same half-of-the-lens-upcharge share, floored to
    whole cents, **plus** a flat fifteen-dollar — 1,500-cent — reshipping fee, with no grace
    period of any kind; a pair damaged the day after handover is charged exactly as much as one
    damaged eleven months later."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lab_order_version_on_warranty_create_returns_412
    """
    scenario = setup_delivered_lab_order(**M160_ORDER)
    lab = scenario["lab_order"]
    delivered_version = lab["version"]

    first = file_warranty_claim(
        lab["id"], scenario["customer"]["id"], "CUSTOMER_DAMAGE", delivered_version
    )
    assert first["customer_charge_cents"] == 4500

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            lab["id"],
            scenario["customer"]["id"],
            "RX_CHANGE",
            delivered_version,  # the filing above already advanced the lab order
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LAB_ORDER_VERSION.value)

    assert read_warranty_claim(first["id"])["status"] == "OPEN"
    assert read_lab_order(lab["id"])["active_warranty_claim_id"] == first["id"]

    _rows, meta = validate_paginated(
        api.list_warranty_claims(STORE, params={"lab_order_id": lab["id"]})
    )
    assert meta["total_count"] == 1


def test_a_fresh_lab_order_version_supersedes_the_open_warranty_claim(api):
    """PRD §3.9: "Like an insurance claim, a warranty claim **supersedes**. Any existing `OPEN`
    claim on the same lab order transitions `OPEN → SUPERSEDED`, its `version` increments, and
    the lab order's `active_warranty_claim_id` is repointed at the new claim — which also
    increments the lab order's `version`, which is why a second filing needs a fresh
    `expected_lab_order_version`."
    PRD §3.9: "A `MANUFACTURER_DEFECT` costs the customer nothing at all — the charge is zero."

    Design: Corner/cross_cutting_complexity_layers/fresh_lab_order_version_supersedes_the_open_warranty_claim
    """
    scenario = setup_delivered_lab_order(**M160_ORDER)
    lab = scenario["lab_order"]

    first = file_warranty_claim(
        lab["id"], scenario["customer"]["id"], "CUSTOMER_DAMAGE", lab["version"]
    )

    refreshed = read_lab_order(lab["id"])  # re-read the version the filing advanced

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            lab["id"],
            scenario["customer"]["id"],
            "MANUFACTURER_DEFECT",
            refreshed["version"],
        ),
        scenario["headers"],
    )
    second = validate_success(resp, 201)

    assert read_warranty_claim(first["id"])["status"] == "SUPERSEDED"
    assert second["status"] == "OPEN"
    assert second["customer_charge_cents"] == 0
    assert read_lab_order(lab["id"])["active_warranty_claim_id"] == second["id"]

    _rows, meta = validate_paginated(
        api.list_warranty_claims(STORE, params={"lab_order_id": lab["id"]})
    )
    assert meta["total_count"] == 2
