"""Public-skate admissions: capacity boundary, rental-skate inventory, the
scheduled-slot precondition, the fiscal guard, refund money-conservation, and
reverse-reachable listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_rink, create_slot, create_published_slot, publish_slot, create_skater,
    create_funded_skater, admit, setup_public_slot,
)

RM = TEST_USERS["rink_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/public_skate_capacity_strict_boundary
# ---------------------------------------------------------------------------
def test_admissions_below_capacity_succeed(api):
    """PRD §3.2: "An admission is allowed only while `admitted_count` is strictly
    less than `public_skate_capacity`; when the count has reached capacity, a
    further admission is rejected with `ERR_CAPACITY_FULL`."

    Design: Difficulty/boundary_precision_check/public_skate_capacity_strict_boundary
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=2,
                              public_skate_fee_cents=0, rental_skate_count=5)
    slot_id = setup["slot"]["id"]
    s1 = create_skater(api, "cap1@x.com")
    s2 = create_skater(api, "cap2@x.com")
    a1 = validate_success(api.create_admission(slot_id, {"skater_id": s1["id"]}, FD), 201)
    a2 = validate_success(api.create_admission(slot_id, {"skater_id": s2["id"]}, FD), 201)
    assert a1["status"] == "ADMITTED" and a2["status"] == "ADMITTED"
    slot = validate_success(api.get_ice_slot(slot_id, RM))
    assert slot["admitted_count"] == 2, f"expected 2 admitted, got {slot['admitted_count']}"


def test_admission_at_capacity_rejected(api):
    """PRD §3.2: "An admission is allowed only while `admitted_count` is strictly
    less than `public_skate_capacity`; when the count has reached capacity, a
    further admission is rejected with `ERR_CAPACITY_FULL`."

    Design: Difficulty/boundary_precision_check/public_skate_capacity_strict_boundary
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=2,
                              public_skate_fee_cents=0, rental_skate_count=5)
    slot_id = setup["slot"]["id"]
    for i in range(2):
        sk = create_skater(api, f"full{i}@x.com")
        validate_success(api.create_admission(slot_id, {"skater_id": sk["id"]}, FD), 201)
    third = create_skater(api, "third@x.com")
    validate_error(api.create_admission(slot_id, {"skater_id": third["id"]}, FD),
                   ApiErrorId.ERR_CAPACITY_FULL.value)
    slot = validate_success(api.get_ice_slot(slot_id, RM))
    assert slot["admitted_count"] == 2, f"count must stay 2, got {slot['admitted_count']}"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/admission_requires_scheduled_public_slot
# ---------------------------------------------------------------------------
def test_admission_on_draft_slot_rejected(api):
    """PRD §3.2: "The target slot must be a `PUBLIC_SKATE` slot in `SCHEDULED`
    status — any other purpose or status yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/admission_requires_scheduled_public_slot
    """
    setup = setup_public_slot(api, published=False, public_skate_capacity=5,
                              public_skate_fee_cents=0)
    sk = create_skater(api, "draftadm@x.com")
    validate_error(api.create_admission(setup["slot"]["id"], {"skater_id": sk["id"]}, FD),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_admission_succeeds_after_slot_published(api):
    """PRD §3.2: "The target slot must be a `PUBLIC_SKATE` slot in `SCHEDULED`
    status — any other purpose or status yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/admission_requires_scheduled_public_slot
    """
    setup = setup_public_slot(api, published=False, public_skate_capacity=5,
                              public_skate_fee_cents=0)
    sk = create_skater(api, "okadm@x.com")
    publish_slot(api, setup["slot"]["id"])
    data = validate_success(
        api.create_admission(setup["slot"]["id"], {"skater_id": sk["id"]}, FD), 201)
    assert data["status"] == "ADMITTED", f"expected ADMITTED, got {data['status']}"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/money_conserved_across_admission_and_refund
# ---------------------------------------------------------------------------
def test_refund_credits_wallet_and_resets_capture(api):
    """PRD §3.2: "Refunding credits the admission's `captured_cents` back to the
    skater's wallet, sets `refunded_cents` to that amount, zeroes `captured_cents`,
    decrements the slot's admitted count, restores the rental skate if one was
    issued, and moves the admission to `REFUNDED`."

    Design: Difficulty/compensating_invariant/money_conserved_across_admission_and_refund
    """
    rink = create_rink(api, public_skate_capacity=2, public_skate_fee_cents=1500,
                       rental_skate_count=1)
    slot = create_published_slot(api, rink["id"], "PUBLIC_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    sk = create_funded_skater(api, "money@x.com", 5000)
    adm = validate_success(
        api.create_admission(slot["id"], {"skater_id": sk["id"], "rental_skate": True}, FD),
        201)
    data = validate_success(api.refund_admission(adm["id"], FD))
    assert data["status"] == "REFUNDED"
    assert data["captured_cents"] == 0, f"captured must zero, got {data['captured_cents']}"
    assert data["refunded_cents"] == 1500, (
        f"refunded_cents must equal fee 1500, got {data['refunded_cents']}")
    skater = validate_success(api.get_skater(sk["id"], RM))
    assert skater["wallet_credit_cents"] == 5000, (
        f"wallet must be restored to 5000, got {skater['wallet_credit_cents']}")


def test_money_conserved_wallet_plus_captured_constant(api):
    """PRD §2.7: "Whenever an operation would charge more than the wallet holds ...
    the request is rejected with `ERR_INSUFFICIENT_FUNDS` and no money moves."
    PRD §3.2: "the rink's `public_skate_fee_cents` is deducted from the skater's
    wallet and recorded as the admission's `captured_cents`".

    Design: Difficulty/compensating_invariant/money_conserved_across_admission_and_refund
    """
    rink = create_rink(api, public_skate_capacity=2, public_skate_fee_cents=1500,
                       rental_skate_count=1)
    slot = create_published_slot(api, rink["id"], "PUBLIC_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    sk = create_funded_skater(api, "cons@x.com", 5000)
    # After admission: wallet 3500 + captured 1500 == 5000.
    adm = validate_success(
        api.create_admission(slot["id"], {"skater_id": sk["id"], "rental_skate": True}, FD),
        201)
    skater = validate_success(api.get_skater(sk["id"], RM))
    assert skater["wallet_credit_cents"] + adm["captured_cents"] == 5000, (
        "money not conserved after admission")
    # After refund: wallet 5000 + captured 0 == 5000.
    refunded = validate_success(api.refund_admission(adm["id"], FD))
    skater = validate_success(api.get_skater(sk["id"], RM))
    assert skater["wallet_credit_cents"] + refunded["captured_cents"] == 5000, (
        "money not conserved after refund")


# ---------------------------------------------------------------------------
# Corner/calculations/rental_skate_inventory_exhausted
# ---------------------------------------------------------------------------
def test_second_rental_admission_exhausts_inventory(api):
    """PRD §3.2: "A rental admission is allowed only when `available_rental_skates`
    is at least 1; if no pairs are free, the admission is rejected with
    `ERR_NO_RENTAL_SKATES`."

    Design: Corner/calculations/rental_skate_inventory_exhausted
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=5,
                              public_skate_fee_cents=0, rental_skate_count=1)
    slot_id = setup["slot"]["id"]
    s1 = create_skater(api, "rent1@x.com")
    s2 = create_skater(api, "rent2@x.com")
    validate_success(
        api.create_admission(slot_id, {"skater_id": s1["id"], "rental_skate": True}, FD),
        201)
    rink = validate_success(api.get_rink(setup["rink"]["id"], RM))
    assert rink["available_rental_skates"] == 0, (
        f"expected 0 free skates, got {rink['available_rental_skates']}")
    validate_error(
        api.create_admission(slot_id, {"skater_id": s2["id"], "rental_skate": True}, FD),
        ApiErrorId.ERR_NO_RENTAL_SKATES.value)


# ---------------------------------------------------------------------------
# Corner/validations/admission_insufficient_funds_returns_402
# ---------------------------------------------------------------------------
def test_admission_with_zero_wallet_rejected(api):
    """PRD §2.7: "Whenever an operation would charge more than the wallet holds —
    an admission fee, a locker fee, a tuition monthly fee, or a slot-booking quote
    — the request is rejected with `ERR_INSUFFICIENT_FUNDS` and no money moves."

    Design: Corner/validations/admission_insufficient_funds_returns_402
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=5,
                              public_skate_fee_cents=1500)
    sk = create_skater(api, "broke@x.com")
    validate_error(
        api.create_admission(setup["slot"]["id"], {"skater_id": sk["id"]}, FD),
        ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ---------------------------------------------------------------------------
# Corner/endpoints/admissions_reverse_reachable_by_slot
# ---------------------------------------------------------------------------
def test_list_admissions_filtered_by_ice_slot(api):
    """PRD §4 (endpoint table): "GET /admissions | List admissions (filter by
    ice_slot_id, skater_id, status)".
    PRD §3.2: "the admission is created in `ADMITTED` status".

    Design: Corner/endpoints/admissions_reverse_reachable_by_slot
    """
    setup = setup_public_slot(api, published=True, public_skate_capacity=5,
                              public_skate_fee_cents=0, rental_skate_count=2)
    slot_id = setup["slot"]["id"]
    s1 = create_skater(api, "la1@x.com")
    s2 = create_skater(api, "la2@x.com")
    admit(api, slot_id, s1["id"])
    admit(api, slot_id, s2["id"])
    data, meta = validate_paginated(api.list_admissions(RM, params={"ice_slot_id": slot_id}))
    assert len(data) == 2, f"expected 2 admissions for the slot, got {len(data)}"
    assert all(item["ice_slot_id"] == slot_id for item in data), (
        "every listed admission must reference the queried slot")
