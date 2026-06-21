"""Whole-animal shares: the cyclic OPEN<->FULLY_CLAIMED state machine, the
quarter-unit over-commit gate, the conserve-on-cancel invariant, the single-claim
calculation, and the break-down side effect.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_animal_share,
    create_customer,
    create_cut_type,
    claim_share,
    setup_share_with_claims,
    make_customer_headers,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine / animal_share_cyclic_open_fullyclaimed_open
# ===========================================================================
def test_share_cycles_back_to_open_on_cancel(api):
    """PRD §3.7: "If the share had been `FULLY_CLAIMED` and the cancel drops
    `claimed_fraction_x4` below 4, the share bubbles `FULLY_CLAIMED → OPEN`; this
    revert is cyclic".

    Two HALF claims -> x4=4 FULLY_CLAIMED; cancel one HALF -> x4=2, share OPEN.

    Design: Difficulty/non_linear_state_machine/animal_share_cyclic_open_fullyclaimed_open
    """
    built = setup_share_with_claims(carcass_weight_g=100000, deposit_cents=8000,
                                    claims=["HALF", "HALF"])
    share = built["share"]
    assert share["share_status"] == "FULLY_CLAIMED"
    assert share["claimed_fraction_x4"] == 4

    claim2 = built["claims"][1]
    owner2 = built["customers"][1]
    get_success_data(api.cancel_share_claim(claim2["id"], make_customer_headers(owner2["id"])))

    share_after = get_success_data(api.get_animal_share(share["id"], MGR))
    assert share_after["share_status"] == "OPEN"
    assert share_after["claimed_fraction_x4"] == 2


def test_share_remaining_recomputed_after_cancel(api):
    """PRD §3.7: "decrements the share's `claimed_fraction_x4` by the claim's
    quarter units, and recomputes `remaining_carcass_g`."
    PRD §3.7: "`remaining_carcass_g` is recomputed as the `carcass_weight_g` times
    the quantity four-minus-`claimed_fraction_x4`, divided by 4, floored to whole
    grams."

    After cancelling one HALF (x4 4->2): remaining = floor(100000*2/4) = 50000.

    Design: Difficulty/non_linear_state_machine/animal_share_cyclic_open_fullyclaimed_open
    """
    built = setup_share_with_claims(carcass_weight_g=100000, deposit_cents=8000,
                                    claims=["HALF", "HALF"])
    share = built["share"]
    claim2 = built["claims"][1]
    owner2 = built["customers"][1]
    get_success_data(api.cancel_share_claim(claim2["id"], make_customer_headers(owner2["id"])))
    share_after = get_success_data(api.get_animal_share(share["id"], MGR))
    assert share_after["remaining_carcass_g"] == 50000, (
        f"expected 50000, got {share_after['remaining_carcass_g']}"
    )


# ===========================================================================
# Difficulty: resource_temporal_overlap / animal_share_fraction_capacity_overlap
# ===========================================================================
def test_share_overcommit_rejected_above_four_quarters(api):
    """PRD §3.7: "the current `claimed_fraction_x4` plus the requested units must
    be less than or equal to 4 (a whole animal is 4 quarter-units). A claim that
    would push the total above 4 quarter-units is rejected with
    `ERR_SHARE_OVERCOMMITTED` (HTTP 409)."

    x4 at 3 (QUARTER + HALF), a further HALF (2) would reach 5 -> rejected.

    Design: Difficulty/resource_temporal_overlap/animal_share_fraction_capacity_overlap
    """
    built = setup_share_with_claims(carcass_weight_g=80000, deposit_cents=6000,
                                    claims=["QUARTER", "HALF"])
    share = built["share"]
    assert share["claimed_fraction_x4"] == 3
    over = create_customer(full_name="Hugo Overflow", phone="555-0014")
    resp = api.create_share_claim(
        {"animal_share_id": share["id"], "customer_id": over["id"], "fraction": "HALF"},
        make_customer_headers(over["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHARE_OVERCOMMITTED.value)


def test_share_quarter_fits_exactly_to_four_quarters(api):
    """PRD §3.7: "A claim is admitted only if it does not over-commit the carcass:
    the current `claimed_fraction_x4` plus the requested units must be less than or
    equal to 4".
    PRD §3.7: "When a claim brings `claimed_fraction_x4` to exactly 4, the share
    bubbles `OPEN → FULLY_CLAIMED` and its `remaining_carcass_g` becomes 0."

    x4 at 3, a QUARTER (1) reaches exactly 4 -> admitted, share FULLY_CLAIMED.

    Design: Difficulty/resource_temporal_overlap/animal_share_fraction_capacity_overlap
    """
    built = setup_share_with_claims(carcass_weight_g=80000, deposit_cents=6000,
                                    claims=["QUARTER", "HALF"])
    share = built["share"]
    last = create_customer(full_name="Quincy Final", phone="555-0015")
    claim = validate_success(
        api.create_share_claim(
            {"animal_share_id": share["id"], "customer_id": last["id"], "fraction": "QUARTER"},
            make_customer_headers(last["id"]),
        ),
        expected_status=201,
    )
    assert claim["claim_status"] == "ACTIVE"
    share_after = get_success_data(api.get_animal_share(share["id"], MGR))
    assert share_after["claimed_fraction_x4"] == 4
    assert share_after["share_status"] == "FULLY_CLAIMED"
    assert share_after["remaining_carcass_g"] == 0


# ===========================================================================
# Difficulty: compensating_invariant / share_claim_cancel_conserves_carcass_grams_and_deposit
# ===========================================================================
def test_cancel_conserves_carcass_grams(api):
    """PRD §3.7: "Cancellation conserves carcass grams by exactly reversing a
    claim."
    PRD §3.7: "decrements the share's `claimed_fraction_x4` by the claim's quarter
    units, and recomputes `remaining_carcass_g`."

    Forward HALF claim then cancel -> remaining_carcass_g back to 100000, x4 == 0.

    Design: Difficulty/compensating_invariant/share_claim_cancel_conserves_carcass_grams_and_deposit
    """
    share = create_animal_share(carcass_weight_g=100000, deposit_cents=8000)
    cust = create_customer(full_name="Cara Conserve", phone="555-0015")
    claim = claim_share(share["id"], cust["id"], "HALF")
    get_success_data(api.cancel_share_claim(claim["id"], make_customer_headers(cust["id"])))

    share_after = get_success_data(api.get_animal_share(share["id"], MGR))
    assert share_after["remaining_carcass_g"] == 100000, (
        f"carcass grams must be conserved at 100000, got {share_after['remaining_carcass_g']}"
    )
    assert share_after["claimed_fraction_x4"] == 0


def test_cancel_refunds_deposit_to_store_credit(api):
    """PRD §3.7: "On cancel the server refunds the claim's `deposit_paid_cents` to
    the customer's `store_credit_cents`".
    PRD §3.7: "the claim's `deposit_paid_cents` is the share's `deposit_cents`
    multiplied by 1 for a `QUARTER` or by 2 for a `HALF`."

    HALF claim charges 2*8000=16000c; cancel refunds 16000c to store credit.

    Design: Difficulty/compensating_invariant/share_claim_cancel_conserves_carcass_grams_and_deposit
    """
    share = create_animal_share(carcass_weight_g=100000, deposit_cents=8000)
    cust = create_customer(full_name="Cara Conserve", phone="555-0016")
    claim = claim_share(share["id"], cust["id"], "HALF")
    assert claim["deposit_paid_cents"] == 16000
    get_success_data(api.cancel_share_claim(claim["id"], make_customer_headers(cust["id"])))

    cust_after = get_success_data(api.get_customer(cust["id"], MGR))
    assert cust_after["store_credit_cents"] == 16000, (
        f"refund of 16000 to store credit expected, got {cust_after['store_credit_cents']}"
    )


# ===========================================================================
# Corner: calculations / share_remaining_after_single_quarter_claim
# ===========================================================================
def test_single_quarter_claim_remaining_and_deposit(api):
    """PRD §3.7: "the claim's `deposit_paid_cents` is the share's `deposit_cents`
    multiplied by 1 for a `QUARTER`".
    PRD §3.7: "`remaining_carcass_g` is recomputed as the `carcass_weight_g` times
    the quantity four-minus-`claimed_fraction_x4`, divided by 4, floored to whole
    grams."

    QUARTER on 100000g, deposit 8000: deposit_paid 8000, x4 1, remaining
    floor(100000*3/4)=75000.

    Design: Corner/calculations/share_remaining_after_single_quarter_claim
    """
    share = create_animal_share(carcass_weight_g=100000, deposit_cents=8000)
    cust = create_customer(full_name="Quincy Quarter", phone="555-1006")
    claim = claim_share(share["id"], cust["id"], "QUARTER")
    assert claim["deposit_paid_cents"] == 8000
    share_after = get_success_data(api.get_animal_share(share["id"], MGR))
    assert share_after["claimed_fraction_x4"] == 1
    assert share_after["remaining_carcass_g"] == 75000


# ===========================================================================
# Corner: endpoints / break_down_share_spawns_lots_with_source
# ===========================================================================
def test_break_down_spawns_lots_with_source_share(api):
    """PRD §3.7: "a `Butcher` breaks it down, advancing `FULLY_CLAIMED →
    BROKEN_DOWN`; the break-down supplies a `lots` payload, and the server spawns
    the described `InventoryLot` rows with each new lot's `source_share_id` set to
    this share."

    Design: Corner/endpoints/break_down_share_spawns_lots_with_source
    """
    built = setup_share_with_claims(carcass_weight_g=100000, deposit_cents=8000,
                                    claims=["HALF", "HALF"])
    share = built["share"]
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    broken = validate_success(
        api.break_down_share(
            share["id"], {"lots": [{"cut_type_id": cut["id"], "received_weight_g": 4000}]},
            BUTCHER,
        )
    )
    assert broken["share_status"] == "BROKEN_DOWN"

    listed = api.list_inventory_lots(BUTCHER, params={"source_share_id": share["id"]})
    rows = listed.json()["data"]
    assert len(rows) >= 1, "expected at least one spawned lot for the share"
    assert rows[0]["source_share_id"] == share["id"]
