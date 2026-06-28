"""Cremation pricing, invoice totals, and clinic statement balances.

Covers the dual-variant and combinatorial calculation difficulty instances plus the
calculation corner instances. Every charge/total is computed by the server at firing
or invoice time; tests assert the literal cents the PRD pricing rules determine.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    setup_private_case_invoiced, setup_communal_batch_fired,
    setup_private_case_cremated, setup_private_case_received,
    setup_received_case_with_cooler, stage_load_fire_private,
    create_clinic, create_owner, create_retort, create_case,
    drive_case_to_received, store_case, get_case_version,
    set_clock, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _charge(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))["cremation_charge_cents"]


# =========================================================================== #
# dual_variant_calc
# =========================================================================== #
def test_private_flat_vs_communal_allocated_charge_diverge(api):
    """PRD §3.9: "For a `PRIVATE` batch — which holds the single member — the charge is
    the flat tier rate for that pet's weight tier plus the expedite surcharge if the
    case is expedited: 12000 cents for `SMALL`, 18000 for `MEDIUM`, 26000 for `LARGE`,
    and 38000 for `XLARGE`, with an additional 5000 cents added when the `expedited`
    flag is true."
    PRD §3.9: "For a `COMMUNAL` batch, a fixed pooled firing cost of 30000 cents is
    recorded as the batch's `communal_firing_total_cents` and then allocated across all
    member cases (those not cancelled) in proportion to body weight."

    Design: Difficulty/dual_variant_calc/dual_calc_case_private_vs_communal_charge
    """
    # PRIVATE MEDIUM (50 lbs), not expedited -> flat 18000.
    priv = setup_private_case_cremated(clock="2026-03-01T00:00:00Z", weight_lbs=50,
                                       bill_to="OWNER")
    assert _charge(priv["case"]["id"]) == 18000

    # COMMUNAL 3/4/20 -> weight-proportional shares of 30000, last absorbs remainder.
    com = setup_communal_batch_fired("2026-03-01T12:00:00Z", [3, 4, 20])
    com1, com2, com3 = com["case_ids"]
    assert _charge(com1) == 3333
    assert _charge(com2) == 4444
    assert _charge(com3) == 22223
    assert _charge(com1) + _charge(com2) + _charge(com3) == 30000


def test_clinic_statement_accrual_exceeds_completion(api):
    """PRD §3.14: "Under the `ACCRUAL` basis a case's charge is recognized once the body
    has been received, so the sum includes every clinic-account case whose custody status
    is `RECEIVED`, `IN_COOLER`, `STAGED`, `CREMATED`, `READY_FOR_RETURN`, or `RETURNED`."
    PRD §3.14: "Under the `COMPLETION` basis recognition waits for cremation, so the sum
    includes only clinic-account cases whose custody status is `CREMATED`,
    `READY_FOR_RETURN`, or `RETURNED`."

    Design: Difficulty/dual_variant_calc/dual_calc_clinic_statement_accrual_vs_completion
    """
    set_clock("2026-04-01T00:00:00Z")
    clinic = create_clinic()
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()

    # Case A: clinic-billed PRIVATE MEDIUM (50 lbs -> 18000), fired AND completed.
    caseA = create_case(owner["id"], clinic_id=clinic["id"], service_type="PRIVATE",
                        weight_lbs=50, bill_to="CLINIC_ACCOUNT", pickup_kind="CLINIC")
    drive_case_to_received(caseA["id"])
    batchA = stage_load_fire_private(caseA["id"], retort["id"],
                                     "2026-04-01T08:00:00Z", "2026-04-01T10:00:00Z")
    get_success_data(api_client.complete_batch(batchA, OPERATOR))

    # Case B: clinic-billed PRIVATE 20 lbs SMALL (12000), fired but NOT completed (STAGED).
    caseB = create_case(owner["id"], clinic_id=clinic["id"], service_type="PRIVATE",
                        weight_lbs=20, bill_to="CLINIC_ACCOUNT", pickup_kind="CLINIC")
    drive_case_to_received(caseB["id"])
    stage_load_fire_private(caseB["id"], retort["id"],
                            "2026-04-01T12:00:00Z", "2026-04-01T14:00:00Z")

    accrual = validate_success(
        api_client.get_clinic_statement(clinic["id"], ADMIN, params={"basis": "ACCRUAL"}))
    completion = validate_success(
        api_client.get_clinic_statement(clinic["id"], ADMIN, params={"basis": "COMPLETION"}))

    assert accrual["balance_cents"] == 30000, "accrual recognizes STAGED B (12000) + completed A (18000)"
    assert completion["balance_cents"] == 18000, "completion recognizes only cremated A"
    assert accrual["balance_cents"] != completion["balance_cents"]


# =========================================================================== #
# combinatorial_formula
# =========================================================================== #
def test_private_charge_large_tier_plus_expedite_surcharge(api):
    """PRD §3.9: "a case weighing 25 pounds or less is `SMALL`; from 26 through 75 pounds
    inclusive it is `MEDIUM`; from 76 through 150 pounds inclusive it is `LARGE`; and
    above 150 pounds it is `XLARGE`."
    PRD §3.9: "26000 for `LARGE`, and 38000 for `XLARGE`, with an additional 5000 cents
    added when the `expedited` flag is true."

    Design: Difficulty/combinatorial_formula/combinatorial_private_charge_tier_plus_surcharge
    """
    ctx = setup_private_case_cremated(clock="2026-03-05T00:00:00Z", weight_lbs=120,
                                      expedited=True, bill_to="OWNER")
    case = get_success_data(api_client.get_case(ctx["case"]["id"], ADMIN))
    assert case["weight_tier"] == "LARGE"
    assert case["cremation_charge_cents"] == 31000, "26000 LARGE + 5000 expedite"


def test_communal_rounding_order_last_member_absorbs_remainder(api):
    """PRD §3.9: "that raw share is rounded half up to a whole cent, and this per-case
    rounding happens before any summation. Because rounding each share independently may
    leave the sum of shares off the pooled total by a few cents in either direction, the
    remainder — the pooled total minus the sum of the rounded shares — is added to the
    share of the last member when members are ordered by their creation timestamp
    ascending."

    Design: Difficulty/combinatorial_formula/combinatorial_communal_rounding_order_remainder
    """
    ctx = setup_communal_batch_fired("2026-03-06T00:00:00Z", [3, 4, 20])
    k1, k2, k3 = ctx["case_ids"]
    assert _charge(k1) == 3333
    assert _charge(k2) == 4444
    assert _charge(k3) == 22223, "last by created_at absorbs the +1 remainder"


def test_invoice_subtotal_then_mid_fee_tier_then_total(api):
    """PRD §3.10: "It computes the invoice's `subtotal_cents`, `handling_fee_cents`, and
    `total_cents` in that pinned order. The subtotal is the case's
    `cremation_charge_cents` plus the sum of `unit_price_cents` over the case's keepsake
    orders that are not cancelled plus the sum of `price_cents` over the case's memorial
    add-ons that are not cancelled."
    PRD §3.10: "1500 cents when the subtotal is from 20000 through 50000 cents inclusive"

    Design: Difficulty/combinatorial_formula/combinatorial_invoice_subtotal_then_fee_tier
    """
    # PRIVATE MEDIUM expedited -> 18000 + 5000 = 23000 charge; PAW_PRINT 4500 + URN 8000.
    set_clock("2026-03-07T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=50,
                       expedited=True, bill_to="OWNER", pickup_kind="HOME")
    get_success_data(api_client.create_keepsake(case["id"], "PAW_PRINT", OPERATOR))
    get_success_data(api_client.create_keepsake(case["id"], "URN", OPERATOR))
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-03-07T08:00:00Z", "2026-03-07T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    version = get_case_version(case["id"])

    invoice = validate_success(api_client.create_invoice(case["id"], version, ADMIN), 201)
    assert invoice["subtotal_cents"] == 35500, "23000 + 4500 + 8000"
    assert invoice["handling_fee_cents"] == 1500, "35500 in 20000..50000 mid tier"
    assert invoice["total_cents"] == 37000


# =========================================================================== #
# Corner: calculations
# =========================================================================== #
def test_invoice_fee_tier_subtotal_boundary_20000(api):
    """PRD §3.10: "2500 cents when the subtotal is below 20000 cents, 1500 cents when the
    subtotal is from 20000 through 50000 cents inclusive, and 0 cents when the subtotal is
    above 50000 cents."

    Design: Corner/calculations/calc_invoice_fee_tier_boundary_20000
    """
    # PRIVATE SMALL (20 lbs -> 12000) + URN 8000 = 20000 subtotal (lower edge of mid tier).
    set_clock("2026-05-07T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=20,
                       bill_to="OWNER", pickup_kind="HOME", species="CAT")
    get_success_data(api_client.create_keepsake(case["id"], "URN", OPERATOR))
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-05-07T08:00:00Z", "2026-05-07T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    version = get_case_version(case["id"])

    invoice = validate_success(api_client.create_invoice(case["id"], version, ADMIN), 201)
    assert invoice["subtotal_cents"] == 20000
    assert invoice["handling_fee_cents"] == 1500, "20000 is inclusive lower edge of mid tier"
    assert invoice["total_cents"] == 21500


def test_invoice_clinic_account_waives_handling_fee(api):
    """PRD §3.10: "The handling fee depends on who is billed: for a `CLINIC_ACCOUNT`
    invoice the handling fee is waived at 0."
    PRD §3.10: "The total is the subtotal plus the handling fee; for a clinic-account
    invoice, where the fee is 0, the total therefore equals the subtotal."

    Design: Corner/calculations/calc_invoice_clinic_account_waives_fee
    """
    set_clock("2026-05-08T00:00:00Z")
    clinic = create_clinic()
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], clinic_id=clinic["id"], service_type="PRIVATE",
                       weight_lbs=50, bill_to="CLINIC_ACCOUNT", pickup_kind="CLINIC")
    get_success_data(api_client.create_keepsake(case["id"], "URN", OPERATOR))
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-05-08T08:00:00Z", "2026-05-08T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    version = get_case_version(case["id"])

    invoice = validate_success(api_client.create_invoice(case["id"], version, ADMIN), 201)
    assert invoice["subtotal_cents"] == 26000, "18000 charge + 8000 URN"
    assert invoice["handling_fee_cents"] == 0
    assert invoice["total_cents"] == 26000


def test_invoice_excludes_cancelled_keepsake(api):
    """PRD §3.10: "The subtotal is the case's `cremation_charge_cents` plus the sum of
    `unit_price_cents` over the case's keepsake orders that are not cancelled plus the sum
    of `price_cents` over the case's memorial add-ons that are not cancelled."

    Design: Corner/calculations/calc_invoice_excludes_cancelled_keepsake
    """
    set_clock("2026-05-09T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=50,
                       bill_to="OWNER", pickup_kind="HOME")
    get_success_data(api_client.create_keepsake(case["id"], "PAW_PRINT", OPERATOR))
    urn = get_success_data(api_client.create_keepsake(case["id"], "URN", OPERATOR))
    get_success_data(api_client.patch_keepsake(urn["id"], "CANCELLED", OPERATOR))
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-05-09T08:00:00Z", "2026-05-09T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    version = get_case_version(case["id"])

    invoice = validate_success(api_client.create_invoice(case["id"], version, ADMIN), 201)
    assert invoice["subtotal_cents"] == 22500, "18000 charge + 4500 PAW_PRINT only"
    assert invoice["handling_fee_cents"] == 1500
    assert invoice["total_cents"] == 24000


def test_cooler_occupancy_after_single_store(api):
    """PRD §3.1: "Available capacity is the total capacity minus the occupied count,
    floored at zero. A cooler's status is `FULL` when its occupied count is at least its
    total capacity, and `AVAILABLE` otherwise"
    PRD §3.4: "A successful store sets the case's `cooler_id` to the target cooler,
    increments that cooler's `occupied_count` by one, recomputes the cooler's
    `available_capacity` and `status`"

    Design: Corner/calculations/calc_cooler_occupancy_after_store
    """
    ctx = setup_received_case_with_cooler(clock="2026-05-10T00:00:00Z", capacity=3)
    store_case(ctx["case"]["id"], ctx["cooler"]["id"])
    cooler = get_success_data(api_client.get_cooler(ctx["cooler"]["id"], ADMIN))
    assert cooler["occupied_count"] == 1
    assert cooler["available_capacity"] == 2
    assert cooler["status"] == "AVAILABLE"


def test_weight_tier_boundary_25_small_26_medium(api):
    """PRD §3.9: "The boundaries are inclusive on the upper edge, so a 25-pound pet is
    `SMALL` while a 26-pound pet is `MEDIUM`."

    Design: Corner/entities/entity_case_weight_tier_boundary_25_vs_26
    """
    owner = create_owner()
    c25 = create_case(owner["id"], weight_lbs=25, species="CAT", service_type="PRIVATE",
                      bill_to="OWNER", pickup_kind="HOME")
    c26 = create_case(owner["id"], weight_lbs=26, species="DOG", service_type="PRIVATE",
                      bill_to="OWNER", pickup_kind="HOME")
    assert get_success_data(api_client.get_case(c25["id"], ADMIN))["weight_tier"] == "SMALL"
    assert get_success_data(api_client.get_case(c26["id"], ADMIN))["weight_tier"] == "MEDIUM"
