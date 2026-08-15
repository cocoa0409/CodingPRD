"""Scrap dispositions, liability payout tier variants, the four-hop exposure
cascade, and claim lifecycle settlement (PRD §3.1, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_liability_claim,
    assign_order,
    create_customer,
    create_load,
    create_work_order,
    decide_case,
    get_customer,
    get_open_case_for_order,
    get_work_order,
    make_customer_headers,
    record_inspection,
    run_load_to_completed,
    setup_failed_order,
    setup_scrapped_order,
    setup_shop,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]
QE2 = TEST_USERS["quality_engineer_2"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / liability_payout_standard_vs_extended_tier
# ---------------------------------------------------------------------------

def test_liability_payout_standard_vs_extended_tier(api):
    """PRD §3.8: "The payout depends on the customer's elected tier. Under
    `STANDARD`, `payout_cents` is the lesser of the order's
    `declared_value_cents` and three times its `processing_charge_cents`.
    Under `EXTENDED`, the material is valued by weight: first extend 85 cents
    per pound across the lot's `received_weight_lb`, round that extension
    half-up to whole cents, and only then apply the cap — `payout_cents` is
    the lesser of `declared_value_cents` and the rounded extension."

    Design: Difficulty/dual_variant_calc/liability_payout_standard_vs_extended_tier
    """
    # One furnace, one recipe, one load: two orders with identical economics
    # (declared 1000000, charge 100000, weight 1000 lb) differing only in the
    # customer's liability tier.
    shop = setup_shop(furnace_overrides={
        "max_load_weight_lb": 5000,
        "quench_media_supported": ["OIL", "WATER"],
    })
    cust_std = create_customer(name="Std Co", liability_tier="STANDARD")
    cust_ext = create_customer(name="Ext Co", liability_tier="EXTENDED")
    order_std = create_work_order(
        cust_std["id"], shop["recipe"]["id"], part_quantity=10,
        received_weight_lb=1000, declared_value_cents=1000000,
        processing_charge_cents=100000,
    )
    order_ext = create_work_order(
        cust_ext["id"], shop["recipe"]["id"], part_quantity=10,
        received_weight_lb=1000, declared_value_cents=1000000,
        processing_charge_cents=100000,
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order_std["id"])
    assign_order(load["id"], order_ext["id"])
    run_load_to_completed(
        load["id"],
        readings=[{"recorded_at": "2026-08-02T10:00:00Z", "temp_f": 1650}],
    )

    for order in (order_std, order_ext):
        test = record_inspection(order["id"], readings=[50, 50])
        assert test["result"] == "FAIL"
        case = get_open_case_for_order(order["id"])
        decide_case(case["id"], "SCRAP")

    claims_std = validate_success(
        api.list_liability_claims(CSR, params={"work_order_id": order_std["id"]}),
        200,
    )
    claims_ext = validate_success(
        api.list_liability_claims(CSR, params={"work_order_id": order_ext["id"]}),
        200,
    )
    assert len(claims_std) == 1 and len(claims_ext) == 1
    payout_std = claims_std[0]["payout_cents"]
    payout_ext = claims_ext[0]["payout_cents"]
    assert payout_std == 300000, (
        f"STANDARD: min(1000000, 3 x 100000) = 300000, got {payout_std}"
    )
    assert payout_ext == 85000, (
        f"EXTENDED: min(1000000, round_half_up(85 x 1000)) = 85000, got "
        f"{payout_ext}"
    )
    assert payout_std != payout_ext, (
        "identical lot economics must pay differently purely by tier variant"
    )


def test_liability_payout_cap_and_extension_rounding(api):
    """PRD §3.8: "The payout depends on the customer's elected tier. Under
    `STANDARD`, `payout_cents` is the lesser of the order's
    `declared_value_cents` and three times its `processing_charge_cents`.
    Under `EXTENDED`, the material is valued by weight: first extend 85 cents
    per pound across the lot's `received_weight_lb`, round that extension
    half-up to whole cents, and only then apply the cap — `payout_cents` is
    the lesser of `declared_value_cents` and the rounded extension."
    PRD §2.6: "Money is integer cents everywhere: quoted and final surcharges,
    energy surcharges, liability payouts, and exposure totals are whole-cent
    integers, and every rounding step called out in this document uses the
    round-half-up method."

    Design: Difficulty/dual_variant_calc/liability_payout_standard_vs_extended_tier
    """
    # EXTENDED with a fractional per-pound extension: 85 x 10.005 = 850.425
    # rounds half-up to 850 whole cents before the (non-binding) cap.
    ext = setup_scrapped_order(
        customer_overrides={"name": "Ext Co", "liability_tier": "EXTENDED"},
        recipe_overrides={"alloy_code": "4140"},
        order_overrides={
            "received_weight_lb": 10.005,
            "declared_value_cents": 100000,
            "processing_charge_cents": 100000,
        },
    )
    assert ext["claim"]["payout_cents"] == 850, (
        f"round_half_up(850.425) = 850 before the cap, got "
        f"{ext['claim']['payout_cents']}"
    )

    # STANDARD capped by the declared value: min(250000, 3 x 100000).
    std = setup_scrapped_order(
        customer_overrides={"name": "Std Co", "liability_tier": "STANDARD"},
        recipe_overrides={"alloy_code": "8620"},
        furnace_overrides={"furnace_code": "F-2"},
        order_overrides={
            "declared_value_cents": 250000,
            "processing_charge_cents": 100000,
        },
    )
    assert std["claim"]["payout_cents"] == 250000, (
        f"declared value caps the 3x-charge variant, got "
        f"{std['claim']['payout_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / scrap_disposition_four_hop_cascade
# ---------------------------------------------------------------------------

def test_scrap_disposition_four_hop_cascade(api):
    """PRD §3.7: "`SCRAP` moves the order from `PROCESSED` to `SCRAPPED` and
    opens a `PENDING` LiabilityClaim whose `payout_cents` follows §3.8, adding
    that payout to the customer's `outstanding_liability_exposure_cents`."
    PRD §3.8: "Liability claims exist only because a disposition decided
    `SCRAP`; each is created in `PENDING` with `work_order_id` and
    `customer_id` copied from the scrapped order."
    PRD §3.8: "Under `STANDARD`, `payout_cents` is the lesser of the order's
    `declared_value_cents` and three times its `processing_charge_cents`."

    Design: Difficulty/transitive_cascade/scrap_disposition_four_hop_cascade
    """
    bundle = setup_failed_order(
        customer_overrides={"name": "Cascade Co", "liability_tier": "STANDARD"},
        order_overrides={
            "declared_value_cents": 1000000,
            "processing_charge_cents": 100000,
        },
    )
    customer = bundle["shop"]["customer"]
    assert get_customer(customer["id"])["outstanding_liability_exposure_cents"] == 0

    # Hop 1: the decide closes the case.
    decided = decide_case(bundle["case"]["id"], "SCRAP")
    assert decided["status"] == "DECIDED"

    # Hop 2: the order is scrapped.
    order = get_work_order(bundle["order"]["id"])
    assert order["processing_status"] == "SCRAPPED"

    # Hop 3: a PENDING liability claim appears with the tier payout.
    claims = validate_success(
        api.list_liability_claims(
            CSR, params={"work_order_id": bundle["order"]["id"]}
        ),
        200,
    )
    assert len(claims) == 1
    claim = claims[0]
    assert_liability_claim(claim)
    assert claim["status"] == "PENDING"
    assert claim["payout_cents"] == 300000
    assert claim["work_order_id"] == bundle["order"]["id"]
    assert claim["customer_id"] == customer["id"]

    # Hop 4: the customer's exposure absorbs the payout.
    exposure = get_customer(customer["id"])["outstanding_liability_exposure_cents"]
    assert exposure == 300000, f"exposure must rise by the payout, got {exposure}"


def test_scrap_then_reject_releases_exposure(api):
    """PRD §3.8: "Alternatively, a `CustomerServiceRep` may reject a `PENDING`
    claim (`ERR_CLAIM_NOT_PENDING`), moving it to `REJECTED` and likewise
    releasing `payout_cents` from the exposure total. `PAID` and `REJECTED`
    are terminal."
    PRD §3.1: "Each account also carries
    `outstanding_liability_exposure_cents`, a computed figure that starts at
    0: the sum of `payout_cents` over that customer's claims in `PENDING` or
    `ACCEPTED` status, recomputed whenever a claim is created, paid, or
    rejected."

    Design: Difficulty/transitive_cascade/scrap_disposition_four_hop_cascade
    """
    bundle = setup_scrapped_order(
        customer_overrides={"name": "Rej Co", "liability_tier": "STANDARD"},
        order_overrides={
            "declared_value_cents": 1000000,
            "processing_charge_cents": 100000,
        },
    )
    customer_id = bundle["customer"]["id"]
    claim = bundle["claim"]
    assert claim["status"] == "PENDING"
    assert get_customer(customer_id)["outstanding_liability_exposure_cents"] == 300000

    rejected = validate_success(api.reject_liability_claim(claim["id"], CSR), 200)
    assert rejected["status"] == "REJECTED"
    assert get_customer(customer_id)["outstanding_liability_exposure_cents"] == 0, (
        "rejecting the claim must release its payout from the exposure"
    )
    assert get_work_order(bundle["order"]["id"])["processing_status"] == "SCRAPPED"


# ---------------------------------------------------------------------------
# Corner: state_machines / claim_lifecycle_state_guards
# ---------------------------------------------------------------------------

def test_claim_lifecycle_state_guards(api):
    """PRD §3.8: "From `PENDING`, a claim can be accepted by the customer it
    belongs to — ownership is enforced by comparing `X-User-ID` to the
    claim's `customer_id` (`ERR_OWNERSHIP_MISMATCH`), and a claim no longer
    `PENDING` rejects acceptance with `ERR_CLAIM_NOT_PENDING` (HTTP 409) —
    moving it to `ACCEPTED`. A `CustomerServiceRep` then settles an `ACCEPTED`
    claim by paying it (any other status fails with `ERR_CLAIM_NOT_ACCEPTED`,
    HTTP 409), moving it to `PAID` and subtracting `payout_cents` from the
    customer's `outstanding_liability_exposure_cents`. Alternatively, a
    `CustomerServiceRep` may reject a `PENDING` claim
    (`ERR_CLAIM_NOT_PENDING`), moving it to `REJECTED` and likewise releasing
    `payout_cents` from the exposure total. `PAID` and `REJECTED` are
    terminal."

    Design: Corner/state_machines/claim_lifecycle_state_guards
    """
    bundle = setup_scrapped_order(
        customer_overrides={"name": "Claim Co", "liability_tier": "STANDARD"}
    )
    customer_id = bundle["customer"]["id"]
    claim = bundle["claim"]
    owner_headers = make_customer_headers(customer_id)

    # Pay while PENDING: must accept first.
    res = api.pay_liability_claim(claim["id"], CSR)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_ACCEPTED.value)

    # Owner accepts: PENDING -> ACCEPTED.
    accepted = validate_success(
        api.accept_liability_claim(claim["id"], owner_headers), 200
    )
    assert accepted["status"] == "ACCEPTED"

    # Double accept rejected — the claim is no longer PENDING.
    res = api.accept_liability_claim(claim["id"], owner_headers)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_PENDING.value)

    # Pay the ACCEPTED claim.
    paid = validate_success(api.pay_liability_claim(claim["id"], CSR), 200)
    assert paid["status"] == "PAID"

    # PAID is terminal: reject after pay is rejected.
    res = api.reject_liability_claim(claim["id"], CSR)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_PENDING.value)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / claim_pay_restores_customer_exposure
# ---------------------------------------------------------------------------

def test_claim_pay_restores_customer_exposure(api):
    """PRD §3.8: "A `CustomerServiceRep` then settles an `ACCEPTED` claim by
    paying it (any other status fails with `ERR_CLAIM_NOT_ACCEPTED`,
    HTTP 409), moving it to `PAID` and subtracting `payout_cents` from the
    customer's `outstanding_liability_exposure_cents`."
    PRD §3.1: "Each account also carries
    `outstanding_liability_exposure_cents`, a computed figure that starts at
    0: the sum of `payout_cents` over that customer's claims in `PENDING` or
    `ACCEPTED` status, recomputed whenever a claim is created, paid, or
    rejected."

    Design: Difficulty/compensating_invariant/claim_pay_restores_customer_exposure
    """
    bundle = setup_scrapped_order(
        customer_overrides={"name": "Expo Co", "liability_tier": "STANDARD"},
        order_overrides={
            "declared_value_cents": 1000000,
            "processing_charge_cents": 100000,
        },
    )
    customer_id = bundle["customer"]["id"]
    claim = bundle["claim"]
    assert get_customer(customer_id)["outstanding_liability_exposure_cents"] == 300000

    # Accept holds the exposure: ACCEPTED claims still count.
    validate_success(
        api.accept_liability_claim(
            claim["id"], make_customer_headers(customer_id)
        ),
        200,
    )
    assert get_customer(customer_id)["outstanding_liability_exposure_cents"] == 300000

    # Pay compensates the exposure back to zero.
    paid = validate_success(api.pay_liability_claim(claim["id"], CSR), 200)
    assert paid["status"] == "PAID"
    exposure = get_customer(customer_id)["outstanding_liability_exposure_cents"]
    assert exposure == 0, (
        f"pay must release the payout from exposure exactly, got {exposure}"
    )


def test_claim_reject_restores_customer_exposure(api):
    """PRD §3.8: "Alternatively, a `CustomerServiceRep` may reject a `PENDING`
    claim (`ERR_CLAIM_NOT_PENDING`), moving it to `REJECTED` and likewise
    releasing `payout_cents` from the exposure total. `PAID` and `REJECTED`
    are terminal."
    PRD §3.1: "Each account also carries
    `outstanding_liability_exposure_cents`, a computed figure that starts at
    0: the sum of `payout_cents` over that customer's claims in `PENDING` or
    `ACCEPTED` status, recomputed whenever a claim is created, paid, or
    rejected."

    Design: Difficulty/compensating_invariant/claim_pay_restores_customer_exposure
    """
    bundle = setup_scrapped_order(
        customer_overrides={"name": "Expo2 Co", "liability_tier": "STANDARD"},
        order_overrides={
            "declared_value_cents": 1000000,
            "processing_charge_cents": 100000,
        },
    )
    customer_id = bundle["customer"]["id"]
    claim = bundle["claim"]
    assert get_customer(customer_id)["outstanding_liability_exposure_cents"] == 300000

    rejected = validate_success(api.reject_liability_claim(claim["id"], CSR), 200)
    assert rejected["status"] == "REJECTED"
    assert get_customer(customer_id)["outstanding_liability_exposure_cents"] == 0

    # REJECTED is terminal: accept is no longer possible.
    res = api.accept_liability_claim(
        claim["id"], make_customer_headers(customer_id)
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_PENDING.value)
