"""Mission completion cascades, tiered billing variants, the grower credit
ledger, and spray compliance records (PRD sections 3.5, 2.9, and 2.7)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    approve_claim,
    assert_spray_record,
    complete,
    create_claim,
    create_mission_completed,
    get_grower,
    get_mission,
    get_field,
    open_claim_review,
    pay_claim,
    setup_ops,
    validate_success,
)


def _invoice(grower_id, period_start="2026-06-01", period_end="2026-06-30"):
    resp = api_client.run_invoice(
        grower_id, {"period_start": period_start, "period_end": period_end},
        ADMIN)
    return validate_success(resp, expected_status=200)


class TestProvisionalVsFinalBilling:

    def test_invoice_final_applies_tier_discount_provision_differs(self):
        """PRD section 3.5: "The `FINAL` variant, settled at the monthly
        invoice run, prices only the first 200 overage acres of a mission at
        the full overage rate; every overage acre beyond 200 is billed at a
        discounted per-acre rate equal to the overage rate multiplied by 0.80,
        that discounted rate itself rounded half-up to a whole cent."
        PRD section 3.5: "The `PROVISIONAL` variant, quoted to the grower
        immediately at completion, prices all overage acres at the plan's
        straight `overage_rate_cents_per_acre`."

        Design: Difficulty/dual_variant_calc/mission_billing_provisional_vs_final_overage
        """
        ctx = setup_ops(plan_overrides={
            "included_acres_per_year": 100,
            "overage_rate_cents_per_acre": 500,
            "spray_allowed": True,
        }, field_overrides={
            # PRD section 3.3: acres_planned may not exceed legal_acres.
            "legal_acres": 400,
        })
        # Single mission of 350 flown acres with 100 included: 250 overage.
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=350, acres_flown=350)
        assert mission["status"] == "COMPLETED"
        invoice = _invoice(ctx["grower"]["id"])
        # PROVISIONAL: 250 * 500 = 125000
        assert invoice["provisional_total_cents"] == 125000, \
            f"provisional must price all 250 overage acres at 500, got " \
            f"{invoice['provisional_total_cents']}"
        # FINAL: 200*500 + 50*round(500*0.80) = 100000 + 20000 = 120000
        assert invoice["invoice_cents"] == 120000, \
            f"final must discount 50 acres beyond the 200-acre tier, got " \
            f"{invoice['invoice_cents']}"
        assert invoice["invoice_cents"] != invoice["provisional_total_cents"]

    def test_invoice_debits_credit_balance_by_final_amount(self):
        """PRD section 3.5: "Settlement debits the grower's
        `credit_balance_cents` by the invoice amount — there is no floor
        check, and the balance is permitted to go negative — and advances the
        grower's `version` by one."

        Design: Difficulty/dual_variant_calc/mission_billing_provisional_vs_final_overage
        """
        ctx = setup_ops(plan_overrides={
            "included_acres_per_year": 100,
            "overage_rate_cents_per_acre": 500,
        }, field_overrides={
            # PRD section 3.3: acres_planned may not exceed legal_acres.
            "legal_acres": 400,
        })
        create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=350, acres_flown=350)
        before = get_grower(ctx["grower"]["id"])
        assert before["credit_balance_cents"] == 0
        invoice = _invoice(ctx["grower"]["id"])
        after = get_grower(ctx["grower"]["id"])
        assert after["credit_balance_cents"] == 0 - invoice["invoice_cents"], \
            f"balance must be debited by invoice_cents, got " \
            f"{after['credit_balance_cents']}"
        assert after["credit_balance_cents"] == -120000
        assert after["version"] == before["version"] + 1, \
            "invoice run must advance the grower version by one"


class TestTieredOverageStraddle:

    def test_invoice_straddles_included_boundary_and_tier_cap(self):
        """PRD section 3.5: "Both start from the grower's year-to-date
        billable acreage as it stood immediately before this mission's acres
        were added, measured within the current subscription year — from
        `subscription_started_on` inclusive to the next anniversary
        exclusive."
        PRD section 3.5: "The `FINAL` variant, settled at the monthly invoice
        run, prices only the first 200 overage acres of a mission at the full
        overage rate; every overage acre beyond 200 is billed at a discounted
        per-acre rate equal to the overage rate multiplied by 0.80, that
        discounted rate itself rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/mission_billing_tiered_overage_straddle
        """
        ctx = setup_ops(
            plan_overrides={"included_acres_per_year": 100,
                            "overage_rate_cents_per_acre": 500},
            field_overrides={"legal_acres": 2000})
        # M1: 80 acres, prior ytd 0 -> fully inside the included allowance.
        create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z",
            acres_planned=80, acres_flown=80)
        # M2: 250 acres with prior ytd 80 -> 20 included, 230 overage;
        # overage straddles the 200-acre tier-1 cap.
        create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-03T08:00:00Z", end="2026-06-03T10:00:00Z",
            launch_time="2026-06-03T08:30:00Z",
            acres_planned=250, acres_flown=250)
        invoice = _invoice(ctx["grower"]["id"])
        # FINAL per line: M1 -> 0; M2 -> 200*500 + 30*400 = 112000.
        assert invoice["invoice_cents"] == 112000, \
            f"expected FINAL total 112000, got {invoice['invoice_cents']}"
        assert len(invoice["line_items"]) == 2, \
            f"expected one line per COMPLETED mission, got {invoice['line_items']}"

    def test_invoice_straddle_provisional_total_uses_flat_rate(self):
        """PRD section 3.5: "The `PROVISIONAL` variant, quoted to the grower
        immediately at completion, prices all overage acres at the plan's
        straight `overage_rate_cents_per_acre`."
        PRD section 3.5: "Under both variants each mission line is rounded
        half-up to integer cents before any summation across lines, so the
        sum of `FINAL` line amounts for an identical mission set can
        legitimately differ from the sum of `PROVISIONAL` amounts."

        Design: Difficulty/combinatorial_formula/mission_billing_tiered_overage_straddle
        """
        ctx = setup_ops(
            plan_overrides={"included_acres_per_year": 100,
                            "overage_rate_cents_per_acre": 500},
            field_overrides={"legal_acres": 2000})
        create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z",
            acres_planned=80, acres_flown=80)
        create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-03T08:00:00Z", end="2026-06-03T10:00:00Z",
            launch_time="2026-06-03T08:30:00Z",
            acres_planned=250, acres_flown=250)
        invoice = _invoice(ctx["grower"]["id"])
        # PROVISIONAL per line: M1 -> 0; M2 -> 230*500 = 115000.
        assert invoice["provisional_total_cents"] == 115000, \
            f"expected PROVISIONAL total 115000, got " \
            f"{invoice['provisional_total_cents']}"
        grower = get_grower(ctx["grower"]["id"])
        # Settlement debits the FINAL amount, not the provisional estimate.
        assert grower["credit_balance_cents"] == -112000
        assert grower["acres_included_ytd"] == 330


class TestCreditLedgerInvariant:

    def test_payout_then_invoice_conserves_balance(self):
        """PRD section 3.8: "Payment is the payout: an `APPROVED` claim —
        anything else is `ERR_CLAIM_NOT_APPROVED` — moves to `PAID`, the
        grower's `credit_balance_cents` is credited by the approved amount,
        and the grower's `version` increments."
        PRD section 3.5: "Settlement debits the grower's
        `credit_balance_cents` by the invoice amount — there is no floor
        check, and the balance is permitted to go negative".

        Design: Difficulty/compensating_invariant/grower_credit_balance_payout_vs_invoice_invariant
        """
        ctx = setup_ops(
            plan_overrides={"included_acres_per_year": 0,
                            "overage_rate_cents_per_acre": 500},
            grower_overrides={"liability_coverage_cents": 100_000_000},
            field_overrides={"legal_acres": 200})
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=100, acres_flown=100)
        claim = create_claim(ctx["grower"]["id"], mission["id"], 75000)
        open_claim_review(claim["id"])
        approve_claim(claim["id"], 75000)
        pay_claim(claim["id"])
        invoice = _invoice(ctx["grower"]["id"])
        # FINAL for 100 overage acres at 500: 50000 (all within tier 1).
        assert invoice["invoice_cents"] == 50000
        grower = get_grower(ctx["grower"]["id"])
        assert grower["credit_balance_cents"] == 0 + 75000 - 50000, \
            f"ledger must equal payout minus invoice, got " \
            f"{grower['credit_balance_cents']}"

    def test_invoice_then_payout_conserves_balance(self):
        """PRD section 3.5: "Settlement debits the grower's
        `credit_balance_cents` by the invoice amount — there is no floor
        check, and the balance is permitted to go negative".
        PRD section 3.8: "Payment is the payout: an `APPROVED` claim —
        anything else is `ERR_CLAIM_NOT_APPROVED` — moves to `PAID`, the
        grower's `credit_balance_cents` is credited by the approved amount,
        and the grower's `version` increments."

        Design: Difficulty/compensating_invariant/grower_credit_balance_payout_vs_invoice_invariant
        """
        ctx = setup_ops(
            plan_overrides={"included_acres_per_year": 0,
                            "overage_rate_cents_per_acre": 500},
            grower_overrides={"liability_coverage_cents": 100_000_000},
            field_overrides={"legal_acres": 200})
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=100, acres_flown=100)
        claim = create_claim(ctx["grower"]["id"], mission["id"], 75000)
        open_claim_review(claim["id"])
        approve_claim(claim["id"], 75000)
        # Invoice first: balance goes negative; payout then restores it.
        invoice = _invoice(ctx["grower"]["id"])
        assert invoice["invoice_cents"] == 50000
        mid = get_grower(ctx["grower"]["id"])
        assert mid["credit_balance_cents"] == -50000
        pay_claim(claim["id"])
        grower = get_grower(ctx["grower"]["id"])
        assert grower["credit_balance_cents"] == -50000 + 75000, \
            f"ledger must be conserved across invoice-then-payout, got " \
            f"{grower['credit_balance_cents']}"


class TestCompletionCascadeConsistency:

    def test_complete_immediately_updates_grower_acres_and_field_surveyed(self):
        """PRD section 3.5: "The mission moves to `COMPLETED`; the field's
        `surveyed_acres` is rewritten with the mission's actual `acres_flown`;
        the grower's `acres_included_ytd` grows by those same acres; and the
        versions of the mission, the field, and the grower all increment
        together."

        Design: Corner/consistency_model/complete_immediately_updates_grower_acres_and_field_surveyed
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=50, acres_flown=42)
        assert mission["status"] == "COMPLETED"
        grower = get_grower(ctx["grower"]["id"])
        field = get_field(ctx["field"]["id"])
        assert grower["acres_included_ytd"] == 42, \
            f"grower ytd must grow by acres_flown, got {grower['acres_included_ytd']}"
        assert field["surveyed_acres"] == 42, \
            f"surveyed_acres must be rewritten to acres_flown, got {field['surveyed_acres']}"

    def test_complete_cascades_mission_grower_and_field(self):
        """PRD section 3.5: "The mission moves to `COMPLETED`; the field's
        `surveyed_acres` is rewritten with the mission's actual `acres_flown`;
        the grower's `acres_included_ytd` grows by those same acres; and the
        versions of the mission, the field, and the grower all increment
        together."

        Design: Difficulty/transitive_cascade/mission_complete_cascades_depth3
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=100, acres_flown=100)
        after_m = get_mission(mission["id"])
        after_g = get_grower(ctx["grower"]["id"])
        after_f = get_field(ctx["field"]["id"])
        assert after_m["status"] == "COMPLETED"
        assert after_f["surveyed_acres"] == 100
        assert after_g["acres_included_ytd"] == 100
        # The grower version increments with the completion cascade.
        assert after_g["version"] == ctx["grower"]["version"] + 1


class TestSprayComplianceRecord:

    def test_spray_mission_complete_creates_immutable_record(self):
        """PRD section 3.5: "When the completed mission was a spray operation,
        completion additionally writes a `SprayMissionRecord` — one record,
        one-to-one with the mission — snapshotting the pilot's
        `applicator_license_no`, the `chemical_product_label` applied, and the
        `gallons_dispensed` at completion time".
        PRD section 3.5: "Pesticide compliance makes this record immutable:
        `record_locked` is always true, the record carries no `updated_at` or
        `version`, and it is retrievable as an array holding zero or one
        entry depending on whether the mission dispensed."

        Design: Corner/endpoints/spray_mission_complete_creates_immutable_record
        """
        ctx = setup_ops(
            plan_overrides={"spray_allowed": True},
            pilot_overrides={
                "applicator_license_no": "APP-9",
                "applicator_license_expires_on": "2027-01-01",
            })
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            mission_type="SPRAY", chemical_product_label="EPA-XYZ",
            acres_planned=20, acres_flown=20, gallons=12.5)
        resp = api_client.get_spray_record(mission["id"], ADMIN)
        records = validate_success(resp, expected_status=200)
        assert isinstance(records, list) and len(records) == 1, \
            f"expected exactly one spray record, got {records}"
        record = records[0]
        assert_spray_record(record)
        assert record["applicator_license_no"] == "APP-9"
        assert record["chemical_product_label"] == "EPA-XYZ"
        assert record["gallons_dispensed"] == 12.5
        assert record["record_locked"] is True
