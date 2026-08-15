"""Damage chargebacks: waiver dual variant, per-claim rounding order, and
the charge/waive compensating invariant."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_damage_claim_payload,
    create_customer, create_equipment_class, create_equipment_unit,
    create_contract, add_line, activate_contract, set_clock, deliver_line,
    setup_draft_contract_with_line, setup_active_rental, setup_charged_damage_claim,
    off_rent, create_claim, assess_claim, charge_claim, dispute_claim,
    resolve_claim, get_contract, get_invoice,
    make_customer_headers,
    assert_damage_claim, assert_invoice,
)


def _two_delivered_lines_waiver_contract():
    """Waiver-elected ACTIVE contract with two lines on two units, both
    delivered 2026-08-05T09:00:00Z and called off rent 2026-08-06T09:00:00Z
    (one billable day each at 10000). Returns (ctx, line1, line2)."""
    set_clock("2026-08-01T09:00:00Z")
    customer = create_customer("Delta Framing", "ap@delta.example")
    cls = create_equipment_class(
        class_code="CTLG", max_working_height_ft=30, daily_rate_cents=10000,
        weekly_rate_cents=70000, monthly_rate_cents=200000,
        replacement_value_cents=2_000_000)
    u1 = create_equipment_unit(cls["id"], "CTLG-001")
    u2 = create_equipment_unit(cls["id"], "CTLG-002")
    contract = create_contract(customer["id"], "77 Commerce Dr",
                               damage_waiver_elected=True)
    l1 = add_line(contract["id"], u1["id"], "2026-08-05", "2026-08-06", 25)
    l2 = add_line(contract["id"], u2["id"], "2026-08-05", "2026-08-06", 25)
    activate_contract(contract["id"])
    deliver_line(contract["id"], l1["id"], "drv-1", "2026-08-05T08:00:00Z",
                 "2026-08-05T10:00:00Z", deliver_at="2026-08-05T09:00:00Z")
    deliver_line(contract["id"], l2["id"], "drv-2", "2026-08-05T08:00:00Z",
                 "2026-08-05T10:00:00Z", deliver_at="2026-08-05T09:00:00Z")
    set_clock("2026-08-06T09:00:00Z")
    off_rent(l1["id"])
    off_rent(l2["id"])
    ctx = {"customer": customer, "equipment_class": cls, "contract": contract}
    return ctx, l1, l2


class TestWaiverDualVariant:
    def test_identical_claims_diverge_by_waiver_election(self, api):
        """PRD §3.8: "for a `DAMAGE` claim on a contract that elected the
        damage waiver, customer liability is ten percent of
        `repair_estimate_cents`, rounded half-up to whole cents at charge time
        and stored as that rounded integer; for a `DAMAGE` claim without the
        waiver, the chargeback is the full `repair_estimate_cents`".

        Design: Difficulty/dual_variant_calc/damage_waiver_vs_standard_chargeback
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Ironworks LLC", "ar@ironworks.example")
        cls = create_equipment_class(
            class_code="BOOM45", max_working_height_ft=51, min_rental_days=4,
            daily_rate_cents=20000, weekly_rate_cents=80000,
            monthly_rate_cents=240000, replacement_value_cents=4_000_000)
        u1 = create_equipment_unit(cls["id"], "BOOM45-001", "ANSI A92.20")
        u2 = create_equipment_unit(cls["id"], "BOOM45-002", "ANSI A92.20")

        ctxs = {}
        for key, waiver, unit, addr in (
                ("a", True, u1, "10 Oak Ave"), ("b", False, u2, "20 Pine Rd")):
            contract = create_contract(customer["id"], addr,
                                       damage_waiver_elected=waiver)
            line = add_line(contract["id"], unit["id"], "2026-08-05",
                            "2026-08-20", 40)
            activate_contract(contract["id"])
            deliver_line(contract["id"], line["id"],
                         "drv-1" if key == "a" else "drv-2",
                         "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z",
                         deliver_at="2026-08-05T09:00:00Z")
            ctxs[key] = (contract, line)

        chargebacks = {}
        for key, reporter in (("a", customer["id"]), ("b", None)):
            contract, line = ctxs[key]
            claim = create_claim(line["id"], "DAMAGE", "bent guardrail",
                                 reporter_customer_id=reporter)
            assess_claim(claim["id"], 50_000)
            charged = charge_claim(claim["id"])
            assert_damage_claim(charged)
            chargebacks[key] = charged["chargeback_cents"]

        assert chargebacks["a"] == 5000, "waiver: round_half_up(0.10 * 50000)"
        assert chargebacks["b"] == 50000, "standard: full estimate"
        assert chargebacks["b"] - chargebacks["a"] == 45000, (
            "identical inputs diverge only through damage_waiver_elected")
        assert get_contract(ctxs["a"][0]["id"])["damage_subtotal_cents"] == 5000
        assert get_contract(ctxs["b"][0]["id"])["damage_subtotal_cents"] == 50000

    def test_waiver_chargeback_rounds_half_up_per_claim(self, api):
        """PRD §3.8: "customer liability is ten percent of
        `repair_estimate_cents`, rounded half-up to whole cents at charge time
        and stored as that rounded integer". PRD §2.6: "Where a computation
        can produce a fractional cent, the result is rounded half-up to the
        nearest whole cent."

        Design: Difficulty/dual_variant_calc/damage_waiver_vs_standard_chargeback
        """
        ctx = setup_charged_damage_claim(repair_estimate_cents=50_005,
                                         damage_waiver_elected=True)
        # round_half_up(0.10 * 50005) = round_half_up(5000.5) = 5001.
        assert ctx["claim"]["chargeback_cents"] == 5001
        assert get_contract(ctx["contract"]["id"])["damage_subtotal_cents"] == 5001


class TestPerClaimRoundingThenSum:
    def test_per_claim_rounding_then_sum_damage_subtotal(self, api):
        """PRD §2.6: "Rounding is pinned to the component level: the damage
        chargeback is rounded per claim at charge time, the labor charge is
        rounded per trip at completion, the recovery credit is rounded per
        claim at recovery, and each rounded integer is stored." and
        "Invoice-level aggregates then sum those stored integer components and
        are never re-rounded — summing raw unrounded percentages and rounding
        once at the aggregate level is explicitly not the rule."

        Design: Difficulty/combinatorial_formula/per_claim_rounding_then_sum
        """
        ctx, l1, l2 = _two_delivered_lines_waiver_contract()
        chargebacks = []
        for line in (l1, l2):
            claim = create_claim(line["id"], "DAMAGE", "deck bent")
            assess_claim(claim["id"], 33_335)
            charged = charge_claim(claim["id"])
            chargebacks.append(charged["chargeback_cents"])

        # round_half_up(0.10 * 33335) = round_half_up(3333.5) = 3334 per claim.
        assert chargebacks == [3334, 3334]
        invoice = get_invoice(ctx["contract"]["id"])
        # Per-claim rounding then sum; sum-then-round would yield 6667.
        assert invoice["damage_subtotal_cents"] == 6668

    def test_invoice_total_sums_stored_integer_components(self, api):
        """PRD §3.9: "Its body carries the `contract_id`, the contract's
        `status`, and four integer-cent figures: `rental_subtotal_cents`
        aggregated from the lines per §3.4, `logistics_subtotal_cents`
        aggregated from completed trips per §3.5, `damage_subtotal_cents`
        aggregated from claims per §3.8, and `invoice_total_cents` as the sum
        of the three subtotals."

        Design: Difficulty/combinatorial_formula/per_claim_rounding_then_sum
        """
        ctx, l1, l2 = _two_delivered_lines_waiver_contract()
        for line in (l1, l2):
            claim = create_claim(line["id"], "DAMAGE", "deck bent")
            assess_claim(claim["id"], 33_335)
            charge_claim(claim["id"])

        invoice = get_invoice(ctx["contract"]["id"])
        assert_invoice(invoice)
        assert invoice["rental_subtotal_cents"] == 20000, "2 lines x 1 day x 10000"
        assert invoice["logistics_subtotal_cents"] == 30000, "2 trips x 15000"
        assert invoice["damage_subtotal_cents"] == 6668
        assert invoice["invoice_total_cents"] == 56668


class TestChargeWaiveConservation:
    def test_charge_then_waive_restores_damage_subtotal(self, api):
        """PRD §3.8: "the contract's `damage_subtotal_cents` — the sum of
        `chargeback_cents` over the contract's claims in `CHARGED` status,
        minus the sum of `recovery_credit_cents` over those same claims,
        treating a missing credit as zero — is recomputed" and "Waiving moves
        the claim from `DISPUTED` to `WAIVED`, the compensating action of the
        charge: the chargeback is removed from the contract's
        `damage_subtotal_cents`".

        Design: Difficulty/compensating_invariant/charge_then_waive_damage_subtotal_conserved
        """
        ctx = setup_active_rental(damage_waiver_elected=True)
        contract_id = ctx["contract"]["id"]
        assert get_contract(contract_id)["damage_subtotal_cents"] == 0

        claim = create_claim(ctx["line"]["id"], "DAMAGE", "battery tray cracked")
        assess_claim(claim["id"], 50_000)
        charged = charge_claim(claim["id"])
        assert charged["chargeback_cents"] == 5000, "waiver: 10% of 50000"
        assert get_contract(contract_id)["damage_subtotal_cents"] == 5000

        dispute_claim(claim["id"], ctx["customer"]["id"])
        resolve_claim(claim["id"], "WAIVE")
        assert get_contract(contract_id)["damage_subtotal_cents"] == 0, (
            "compensating action restores the pre-charge value, no drift")

    def test_repeated_charge_waive_rounds_conserve_subtotal(self, api):
        """PRD §3.8: "`CHARGED` → `DISPUTED` → `CHARGED` cycle may repeat" for
        disputes, and waiving is "the compensating action of the charge: the
        chargeback is removed from the contract's `damage_subtotal_cents`" —
        so a second independent claim charged and waived returns the subtotal
        to zero again.

        Design: Difficulty/compensating_invariant/charge_then_waive_damage_subtotal_conserved
        """
        ctx = setup_active_rental(damage_waiver_elected=True)
        contract_id = ctx["contract"]["id"]

        for estimate, expected in ((50_000, 5000), (80_000, 8000)):
            claim = create_claim(ctx["line"]["id"], "DAMAGE", "repeat damage")
            assess_claim(claim["id"], estimate)
            charged = charge_claim(claim["id"])
            assert charged["chargeback_cents"] == expected
            assert get_contract(contract_id)["damage_subtotal_cents"] == expected
            dispute_claim(claim["id"], ctx["customer"]["id"])
            resolve_claim(claim["id"], "WAIVE")
            assert get_contract(contract_id)["damage_subtotal_cents"] == 0


class TestClaimStateGate:
    def test_claim_on_reserved_line_rejected(self, api,
                                             rental_coordinator_headers):
        """PRD §3.8: "The line must be `OUT_ON_RENT`, `OFF_RENT`, or
        `RETURNED` — a claim against a line still `RESERVED` or already
        `CANCELLED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/validations/claim_on_reserved_line_rejected
        """
        ctx = setup_draft_contract_with_line()
        res = api.create_damage_claim(
            create_damage_claim_payload(ctx["line"]["id"], "DAMAGE",
                                        "damaged before delivery"),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
