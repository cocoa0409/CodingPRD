"""Package resolution and the oversize / overstay / forwarding fee math.

Covers difficulty instances for the dual-variant overstay, the combinatorial
oversize and invoice-balance formulas, the overstay grace boundary, and the
package fork-join; plus corner instances for the oversize cap, forwarding flat
rates, and the pickup-code mismatch.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_facility_operator_headers,
    setup_active_agreement, setup_notified_package, setup_agreement_with_forwarding,
    receive_package, receive_and_notify_package, create_mail_item, advance_clock,
    get_open_invoice, find_ledger_entries, create_locker,
)

OP = make_facility_operator_headers()


def _ledger(api, agr_id):
    inv = get_open_invoice(agr_id)
    body = api.list_ledger_entries(inv["id"], OP).json()
    return inv, body["data"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / overstay_provisional_diverges_from_final_on_package
# ---------------------------------------------------------------------------
def test_overstay_provisional_diverges_from_final_on_package(api):
    """PRD §3.5: "The provisional overstay is computed at notification and again on
    every clock advance, using the facility's live current_utc as the reference; it
    is written to overstay_fee_cents so a reader can see the running exposure, but it
    is not posted to the ledger and may grow as the clock advances. The final
    overstay is computed at the terminal transition — pickup, forward, or
    abandonment — using the package's resolved_at as the reference; this frozen
    figure is the amount actually posted as the OVERSTAY charge to the invoice."

    Design: Difficulty/dual_variant_calc/overstay_provisional_diverges_from_final_on_package
    """
    # MEDIUM locker; notified 2026-06-01; daily rate 300 (MEDIUM); grace 2 days.
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=3, autopay_enabled=False, locker_size="MEDIUM",
                               pkg_size="MEDIUM", longest_dim_cm=40, weight_g=3000, name="F1")
    fac_id = s["facility"]["id"]
    pkg_id = s["package"]["id"]
    code = s["package"]["pickup_code"]

    # Clock day 4 -> stored 4 -> overstay_days max(0,4-2)=2 -> 2*300 = 600 provisional.
    advance_clock(fac_id, "2026-06-05T00:00:00.000Z")
    prov = validate_success(api.get_package(pkg_id, OP))
    assert prov["overstay_fee_cents"] == 600, "provisional overstay at day 4 is 600c"

    # Clock day 7 -> pickup -> final overstay days max(0,7-2)=5 -> 5*300 = 1500.
    advance_clock(fac_id, "2026-06-08T00:00:00.000Z")
    v2 = validate_success(api.get_package(pkg_id, OP))["version"]
    final = validate_success(api.pickup_package(
        pkg_id, {"pickup_code": code, "expected_package_version": v2}, OP))
    assert final["overstay_fee_cents"] == 1500, "final overstay at day 7 is 1500c"
    assert final["overstay_fee_cents"] != 600, "final diverges from the day-4 provisional"


def test_provisional_overstay_grows_as_clock_advances(api):
    """PRD §3.5: "it is written to overstay_fee_cents so a reader can see the running
    exposure, but it is not posted to the ledger and may grow as the clock advances."

    Design: Difficulty/dual_variant_calc/overstay_provisional_diverges_from_final_on_package
    """
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", locker_size="MEDIUM",
                               pkg_size="MEDIUM", longest_dim_cm=40, weight_g=3000, name="F1b")
    fac_id = s["facility"]["id"]
    pkg_id = s["package"]["id"]
    advance_clock(fac_id, "2026-06-05T00:00:00.000Z")  # stored 4 -> 600
    assert validate_success(api.get_package(pkg_id, OP))["overstay_fee_cents"] == 600
    advance_clock(fac_id, "2026-06-07T00:00:00.000Z")  # stored 6 -> 4*300 = 1200
    assert validate_success(api.get_package(pkg_id, OP))["overstay_fee_cents"] == 1200


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / oversize_fee_nonlinear_three_input_tiered
# ---------------------------------------------------------------------------
def test_oversize_fee_nonlinear_three_input_tiered(api):
    """PRD §3.5: "To price the overage, the system measures how far the parcel's
    longest_dim_cm exceeds its tier's dimension cap and divides that excess by a 10 cm
    bucket, rounding up to a whole number of buckets, with no negative buckets when
    the parcel is within the cap. It does the same for weight, dividing the amount by
    which weight_g exceeds the tier's weight cap by a 1,000 g bucket and rounding up,
    again floored at zero buckets. Each dimension bucket costs 150 cents and each
    weight bucket costs 80 cents; the raw fee is the dimension-bucket count times 150
    plus the weight-bucket count times 80."

    Design: Difficulty/combinatorial_formula/oversize_fee_nonlinear_three_input_tiered
    """
    # MEDIUM caps: dim 50, weight 5000. dim 72 -> ceil(22/10)=3 buckets; weight 6200
    # -> ceil(1200/1000)=2 buckets. fee = 3*150 + 2*80 = 610.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F3")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "FEDEX", "size_tier": "MEDIUM", "longest_dim_cm": 72, "weight_g": 6200}, OP)
    data = validate_success(resp, expected_status=201)
    assert data["oversize_fee_cents"] == 610, "3 dim buckets (450) + 2 weight buckets (160) = 610"


def test_oversize_fee_dimension_only_overage(api):
    """PRD §3.5: "To price the overage, the system measures how far the parcel's
    longest_dim_cm exceeds its tier's dimension cap and divides that excess by a 10 cm
    bucket, rounding up to a whole number of buckets, with no negative buckets when
    the parcel is within the cap."
    PRD §3.5: "Each dimension bucket costs 150 cents and each weight bucket costs 80
    cents; the raw fee is the dimension-bucket count times 150 plus the weight-bucket
    count times 80."

    Design: Difficulty/combinatorial_formula/oversize_fee_nonlinear_three_input_tiered
    """
    # MEDIUM caps dim 50 / weight 5000. dim 61 -> ceil(11/10)=2 dim buckets; weight
    # 4000 within cap -> 0 weight buckets. fee = 2*150 + 0 = 300.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="MEDIUM", name="F3b")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "FEDEX", "size_tier": "MEDIUM", "longest_dim_cm": 61, "weight_g": 4000}, OP)
    data = validate_success(resp, expected_status=201)
    assert data["oversize_fee_cents"] == 300, "2 dim buckets (300) + 0 weight buckets = 300"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / invoice_balance_round_per_line_then_sum
# ---------------------------------------------------------------------------
def test_invoice_balance_round_per_line_then_sum(api):
    """PRD §3.6: "Because every ledger and payment amount is already an integer-cent
    line item, the invoice sums those integers directly and never re-rounds a running
    subtotal."
    PRD §3.4: "the finalized overstay charge (if greater than zero) and the pinned
    oversize charge (if greater than zero) are posted to the agreement's invoice as
    CHARGE ledger entries with reasons OVERSTAY and OVERSIZE, raising the balance,"

    Design: Difficulty/combinatorial_formula/invoice_balance_round_per_line_then_sum
    """
    # RENTAL 3000*3 = 9000, OVERSIZE 610, OVERSTAY (day 7, MEDIUM) 1500 -> total 11110.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=3,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="F4")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    pkg = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                     longest_dim_cm=72, weight_g=6200)
    advance_clock(fac_id, "2026-06-08T00:00:00.000Z")
    v = validate_success(api.get_package(pkg["id"], OP))["version"]
    validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": v}, OP))

    inv = get_open_invoice(agr_id)
    inv = validate_success(api.get_invoice(inv["id"], OP))
    assert inv["charges_total_cents"] == 11110, "charges = 9000 RENTAL + 610 OVERSIZE + 1500 OVERSTAY"


def test_invoice_balance_equals_summed_line_items(api):
    """PRD §3.6: "The balance_cents is charges_total_cents minus credits_total_cents
    minus payments_total_cents, and it may go negative, representing an overpayment
    credit. Because every ledger and payment amount is already an integer-cent line
    item, the invoice sums those integers directly and never re-rounds a running
    subtotal."

    Design: Difficulty/combinatorial_formula/invoice_balance_round_per_line_then_sum
    """
    # Same 9000+610+1500 = 11110 charges, autopay OFF, no payments -> balance 11110.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=3,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="F4b")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    pkg = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                     longest_dim_cm=72, weight_g=6200)
    advance_clock(fac_id, "2026-06-08T00:00:00.000Z")
    v = validate_success(api.get_package(pkg["id"], OP))["version"]
    validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": v}, OP))
    inv = get_open_invoice(agr_id)
    inv = validate_success(api.get_invoice(inv["id"], OP))
    assert inv["balance_cents"] == 11110, "balance = charges - credits - payments = 11110 - 0 - 0"
    assert inv["balance_cents"] == (
        inv["charges_total_cents"] - inv["credits_total_cents"] - inv["payments_total_cents"]
    ), "balance is the direct difference of the summed integer-cent totals"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / overstay_grace_boundary_zero_at_grace_day
# ---------------------------------------------------------------------------
def test_overstay_zero_at_exactly_grace_day(api):
    """PRD §3.5: "From that, the chargeable overstay days are the stored days minus
    the grace of 2 days, floored at zero — which means a fee begins to accrue only
    once the parcel has been stored for at least 3 calendar days (the grace of 2
    plus 1)."

    Design: Difficulty/boundary_precision_check/overstay_grace_boundary_zero_at_grace_day
    """
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", locker_size="MEDIUM",
                               pkg_size="MEDIUM", longest_dim_cm=40, weight_g=3000, name="F11")
    fac_id = s["facility"]["id"]
    pkg_id = s["package"]["id"]
    code = s["package"]["pickup_code"]
    # Stored exactly 2 calendar days == GRACE_DAYS -> overstay 0.
    advance_clock(fac_id, "2026-06-03T00:00:00.000Z")
    v = validate_success(api.get_package(pkg_id, OP))["version"]
    final = validate_success(api.pickup_package(
        pkg_id, {"pickup_code": code, "expected_package_version": v}, OP))
    assert final["overstay_fee_cents"] == 0, "overstay is 0 at exactly stored_days == grace (2)"


def test_overstay_charges_one_day_just_past_grace(api):
    """PRD §3.5: "a fee begins to accrue only once the parcel has been stored for at
    least 3 calendar days (the grace of 2 plus 1). The daily rate depends on the
    assigned locker's size_tier: 200 cents per day for SMALL, 300 for MEDIUM, 500 for
    LARGE, and 800 for XL."

    Design: Difficulty/boundary_precision_check/overstay_grace_boundary_zero_at_grace_day
    """
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", locker_size="MEDIUM",
                               pkg_size="MEDIUM", longest_dim_cm=40, weight_g=3000, name="F11b")
    fac_id = s["facility"]["id"]
    pkg_id = s["package"]["id"]
    code = s["package"]["pickup_code"]
    # Stored 3 calendar days -> overstay_days max(0,3-2)=1 -> 1*300 = 300.
    advance_clock(fac_id, "2026-06-04T00:00:00.000Z")
    v = validate_success(api.get_package(pkg_id, OP))["version"]
    final = validate_success(api.pickup_package(
        pkg_id, {"pickup_code": code, "expected_package_version": v}, OP))
    assert final["overstay_fee_cents"] == 300, "one chargeable day at MEDIUM rate is 300c"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / package_fork_join_divergent_branches
# ---------------------------------------------------------------------------
def test_package_fork_join_divergent_branches(api):
    """PRD §3.4: "An operator notifies the recipient that a parcel is ready, moving
    RECEIVED → NOTIFIED"
    PRD §3.4: "Forwarding moves NOTIFIED → FORWARDED: it finalizes the overstay fee
    against resolved_at, stamps resolved_at, posts the OVERSTAY and OVERSIZE charges
    as on pickup, and additionally posts a FORWARDING charge of 1,200 cents for
    forwarding the parcel itself; autopay then captures if enabled, and the locker is
    released."

    Design: Difficulty/non_linear_state_machine/package_fork_join_divergent_branches
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="F6")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    # second locker so both packages get a slot
    create_locker(fac_id, label="L2", size_tier="MEDIUM")

    pkg_a = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                       longest_dim_cm=40, weight_g=3000)
    pkg_b = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                       longest_dim_cm=40, weight_g=3000)
    v_a = validate_success(api.get_package(pkg_a["id"], OP))["version"]

    picked = validate_success(api.pickup_package(
        pkg_a["id"], {"pickup_code": pkg_a["pickup_code"], "expected_package_version": v_a}, OP))
    forwarded = validate_success(api.forward_package(pkg_b["id"], {"destination_address": "1 Main St"}, OP))
    assert picked["status"] == "PICKED_UP", "branch A reaches PICKED_UP"
    assert forwarded["status"] == "FORWARDED", "branch B reaches FORWARDED"

    inv, entries = _ledger(api, agr_id)
    forwarding = find_ledger_entries(entries, reason="FORWARDING")
    assert len(forwarding) == 1, "only the FORWARDED branch posts a FORWARDING charge"
    assert forwarding[0]["amount_cents"] == 1200, "package FORWARDING charge is 1200c"


def test_pickup_branch_posts_no_forwarding_charge(api):
    """PRD §3.4: "As a depth-three cascade, the finalized overstay charge (if greater
    than zero) and the pinned oversize charge (if greater than zero) are posted to the
    agreement's invoice as CHARGE ledger entries with reasons OVERSTAY and OVERSIZE,
    raising the balance, after which the autopay cascade captures payment if autopay
    is enabled."

    Design: Difficulty/non_linear_state_machine/package_fork_join_divergent_branches
    """
    # A same-day in-tier pickup posts NO ledger charges (overstay 0, oversize 0),
    # and crucially no FORWARDING charge — distinguishing it from the FORWARDED branch.
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=1, autopay_enabled=False, with_locker=True,
                               locker_size="MEDIUM", name="F6b")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    pkg = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                     longest_dim_cm=40, weight_g=3000)
    v = validate_success(api.get_package(pkg["id"], OP))["version"]
    picked = validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": v}, OP))
    assert picked["status"] == "PICKED_UP"
    _, entries = _ledger(api, agr_id)
    assert find_ledger_entries(entries, reason="FORWARDING") == [], \
        "the PICKED_UP branch posts no FORWARDING charge"


# ---------------------------------------------------------------------------
# Corner: calculations / oversize_fee_cap_applied
# ---------------------------------------------------------------------------
def test_oversize_fee_cap_applied(api):
    """PRD §3.5: "That raw fee is then capped: the final oversize_fee_cents is the
    smaller of the raw fee and the cap of 2,000 cents, with the cap applied last
    after the buckets are summed."

    Design: Corner/calculations/oversize_fee_cap_applied
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=True, locker_size="LARGE", name="Depot")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "FEDEX", "size_tier": "LARGE", "longest_dim_cm": 300, "weight_g": 100000}, OP)
    data = validate_success(resp, expected_status=201)
    assert data["oversize_fee_cents"] == 2000, "raw fee clamps to the 2000c cap"


# ---------------------------------------------------------------------------
# Corner: calculations / forwarding_fee_scan_vs_forward_flat_rates
# ---------------------------------------------------------------------------
def test_forwarding_fee_scan_vs_forward_flat_rates(api):
    """PRD §3.7: "The service fee is pinned into fee_cents at creation: a forward
    costs 600 cents and a scan costs 150 cents."

    Design: Corner/calculations/forwarding_fee_scan_vs_forward_flat_rates
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=False, name="Depot")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    mi1 = create_mail_item(fac_id, agr_id)
    mi2 = create_mail_item(fac_id, agr_id)

    scan = validate_success(api.create_forwarding_request({"mail_item_id": mi1["id"], "kind": "SCAN"}, OP),
                            expected_status=201)
    fwd = validate_success(api.create_forwarding_request(
        {"mail_item_id": mi2["id"], "kind": "FORWARD", "destination_address": "5 Oak Ave"}, OP),
        expected_status=201)
    assert scan["fee_cents"] == 150, "SCAN fee is 150c"
    assert fwd["fee_cents"] == 600, "FORWARD fee is 600c"


# ---------------------------------------------------------------------------
# Corner: errors / pickup_wrong_code_on_notified_returns_mismatch
# ---------------------------------------------------------------------------
def test_pickup_wrong_code_on_notified_returns_mismatch(api):
    """PRD §3.4: "the supplied pickup_code must equal the package's stored
    pickup_code (else ERR_PICKUP_CODE_MISMATCH); and the owning agreement must be
    ACTIVE or SUSPENDED."

    Design: Corner/errors/pickup_wrong_code_on_notified_returns_mismatch
    """
    s = setup_notified_package(clock="2026-06-01T00:00:00.000Z", locker_size="MEDIUM",
                               pkg_size="MEDIUM", longest_dim_cm=40, weight_g=3000, name="Depot")
    pkg_id = s["package"]["id"]
    v = validate_success(api.get_package(pkg_id, OP))["version"]
    resp = api.pickup_package(pkg_id, {"pickup_code": "999999", "expected_package_version": v}, OP)
    validate_error(resp, ApiErrorId.ERR_PICKUP_CODE_MISMATCH.value)
    after = validate_success(api.get_package(pkg_id, OP))
    assert after["status"] == "NOTIFIED", "package stays NOTIFIED after a code mismatch"
