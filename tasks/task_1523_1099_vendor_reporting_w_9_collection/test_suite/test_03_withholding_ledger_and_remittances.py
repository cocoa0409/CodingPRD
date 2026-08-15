"""The withholding ledger: immutable entries, reversal pairs, payment-void
cascade, remittance lifecycle, segregation of duties, and accrual/statutory
divergence."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    SPEC,
    ApiErrorId,
    assert_remittance,
    assert_withholding_entry,
    assert_withholding_ledger_conservation,
    create_draft_remittance,
    create_matched_vendor,
    create_mismatched_vendor,
    create_payment,
    create_tax_year,
    create_validated_return,
    generate_returns,
    get_single_return,
    get_vendor,
    list_withholding_entries,
    make_tax_specialist_headers,
    make_tax_transmitter_headers,
    setup_withheld_payment,
    submit_remittance,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLedgerShape:
    def test_withholding_entry_immutable_shape(self, api):
        """PRD §2.5: "Withholding ledger entries are the deliberate exception: a
        `WithholdingEntry` is an immutable ledger row that carries only `id` and
        `created_at`. Both `updated_at` and `version` are absent from withholding
        entries."
        PRD §3.4: "Whenever `withheld_cents` is greater than zero, posting also
        creates a `DEBIT_WITHHELD` ledger entry in `UNREMITTED` status carrying the
        payment's `vendor_id`, `payment_id`, `tax_year`, and `quarter`..."

        Design: Corner/entities/c_withholding_entry_immutable_shape
        """
        _year, vendor, payment = setup_withheld_payment(amount_cents=100000)
        entries, meta = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_withholding_entry(entry)
        assert entry["amount_cents"] == 24000
        assert entry["entry_type"] == "DEBIT_WITHHELD"
        assert entry["status"] == "UNREMITTED"
        assert entry["payment_id"] == payment["id"]
        assert entry["tax_year"] == 2025
        assert entry["quarter"] == 1


class TestPaymentVoidCascade:
    def test_payment_void_reverses_withholding_and_recomputes(self, api):
        """PRD §3.4: "A successful void moves the payment to `VOIDED` and cascades:
        if its `withheld_cents` was greater than zero, the original `DEBIT_WITHHELD`
        entry becomes `REVERSED` and a compensating `REVERSAL` entry of negative
        `withheld_cents` is created already `REVERSED`, the pair netting to zero and
        leaving the unremitted pool atomically; the vendor's
        `withholding_balance_cents` is recomputed; every `DRAFT` remittance for the
        payment's year-quarter recomputes..."
        PRD §3.5: "the recomputed `amount_cents` must be greater than zero at submit
        time (`ERR_NOTHING_TO_REMIT` covers a draft whose entries have drained
        away)."

        Design: Difficulty/transitive_cascade/payment_void_reverses_withholding_and_recomputes
        """
        _year, vendor, payment = setup_withheld_payment(amount_cents=100000)
        remittance = create_draft_remittance(tax_year=2025, quarter=1, creator_id="spec-1")
        assert remittance["amount_cents"] == 24000

        voided = validate_success(api.void_payment(payment["id"], CLERK), 200)
        assert voided["status"] == "VOIDED"

        reversals, meta = validate_paginated(
            api.list_withholding_entries(
                SPEC, params={"vendor_id": vendor["id"], "entry_type": "REVERSAL"}
            )
        )
        assert meta["total_count"] == 1
        reversal = reversals[0]
        assert reversal["amount_cents"] == -24000
        assert reversal["status"] == "REVERSED"

        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 0

        rem_after = validate_success(api.get_remittance(remittance["id"], SPEC), 200)
        assert rem_after["amount_cents"] == 0

        submit = api.submit_remittance(remittance["id"], make_tax_transmitter_headers("xmtr-1"))
        validate_error(submit, ApiErrorId.ERR_NOTHING_TO_REMIT, 409)

    def test_payment_void_reverts_validated_return_to_draft(self, api):
        """PRD §3.4: "the vendor's `DRAFT` and `VALIDATED` returns for the payment's
        tax year recompute their box amounts on the final basis, with `VALIDATED`
        returns reverting to `DRAFT`."

        Design: Difficulty/transitive_cascade/payment_void_reverses_withholding_and_recomputes
        """
        create_tax_year()
        # tin supplied at onboarding keeps the vendor validatable after its W-9
        # comes back MISMATCHED (validate requires a non-null tin).
        vendor, payment, tax_return = create_validated_return(
            mismatched=True, tin="999999999", amount_cents=100000,
        )
        assert tax_return["federal_status"] == "VALIDATED"
        assert tax_return["box_amounts"]["box_1_cents"] == 100000
        assert tax_return["box_amounts"]["box_4_cents"] == 24000

        validate_success(api.void_payment(payment["id"], CLERK), 200)

        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert after["federal_status"] == "DRAFT"
        # Final-basis recompute over the surviving POSTED set (now empty).
        assert after["box_amounts"]["box_1_cents"] == 0
        assert after["box_amounts"]["box_4_cents"] == 0
        assert after["amount_basis"] == "FINAL"


class TestLedgerConservation:
    def test_withholding_ledger_conservation_across_void_and_remit(self, api):
        """PRD §2.10: "A vendor's `withholding_balance_cents` is always the signed
        sum of that vendor's entries whose status is `UNREMITTED`; nothing else
        contributes."
        PRD §2.10: "When a remittance is submitted, the entries it sweeps are
        stamped with its id in `remittance_id` and move to `REMITTED`, permanently
        exiting the pool."

        Design: Difficulty/compensating_invariant/withholding_ledger_conservation_across_void_and_remit
        """
        create_tax_year()
        vendor, _w9 = create_mismatched_vendor(legal_name="Cons V", tin="909090909")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-02-10T00:00:00Z")
        p2 = create_payment(vendor["id"], amount_cents=50000, payment_date="2025-02-20T00:00:00Z")
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 36000

        validate_success(api.void_payment(p2["id"], CLERK), 200)
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 24000

        entries, meta = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 3
        by_key = sorted((e["entry_type"], e["amount_cents"], e["status"]) for e in entries)
        assert by_key == [
            ("DEBIT_WITHHELD", 12000, "REVERSED"),
            ("DEBIT_WITHHELD", 24000, "UNREMITTED"),
            ("REVERSAL", -12000, "REVERSED"),
        ]
        assert_withholding_ledger_conservation(get_vendor(vendor["id"]), entries)

        remittance = create_draft_remittance(tax_year=2025, quarter=1, creator_id="spec-1")
        # Only the surviving UNREMITTED debit feeds the draft.
        assert remittance["amount_cents"] == 24000

        submit_remittance(remittance["id"], submitter_id="xmtr-1")
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 0

        entries_after, _ = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        remitted_signed = sum(
            e["amount_cents"] for e in entries_after if e["status"] == "REMITTED"
        )
        signed_total = sum(e["amount_cents"] for e in entries_after)
        # Money conservation: balance + remitted == signed total over all rows.
        assert 0 + remitted_signed == signed_total == 24000
        assert_withholding_ledger_conservation(get_vendor(vendor["id"]), entries_after)

    def test_withholding_ledger_conservation_across_manual_reversal(self, api):
        """PRD §3.5: "The reversal creates a compensating `REVERSAL` entry of
        negative `amount_cents` whose `reverses_entry_id` names the original, both
        rows resting in `REVERSED`; the vendor's `withholding_balance_cents` is
        recomputed, draft remittances recompute..."

        Design: Difficulty/compensating_invariant/withholding_ledger_conservation_across_void_and_remit
        """
        create_tax_year()
        vendor, _w9 = create_mismatched_vendor(legal_name="Cons2 V", tin="909090909")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-02-10T00:00:00Z")
        create_payment(vendor["id"], amount_cents=50000, payment_date="2025-02-20T00:00:00Z")
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 36000

        entries, _ = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        small = [e for e in entries if e["amount_cents"] == 12000][0]
        reversed_entry = validate_success(
            api.reverse_withholding_entry(small["id"], ADMIN), 200
        )
        assert reversed_entry["status"] == "REVERSED"

        all_entries, meta = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 3
        reversal = [e for e in all_entries if e["entry_type"] == "REVERSAL"][0]
        assert reversal["amount_cents"] == -12000
        assert reversal["reverses_entry_id"] == small["id"]
        assert reversal["status"] == "REVERSED"

        vendor_after = get_vendor(vendor["id"])
        assert vendor_after["withholding_balance_cents"] == 24000
        assert_withholding_ledger_conservation(vendor_after, all_entries)


class TestEntryReversalRules:
    def test_reverse_remitted_entry_returns_409(self, api):
        """PRD §3.5: "a `TaxAdmin` may reverse an entry manually, but only a
        `DEBIT_WITHHELD` entry may be reversed — reversing a `REVERSAL` entry is
        rejected with `ERR_INVALID_STATE_TRANSITION` — and only while it is
        `UNREMITTED` (a `REMITTED` entry draws `ERR_ENTRY_ALREADY_REMITTED`; an
        already-`REVERSED` entry draws `ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/validations/c_reverse_remitted_entry_returns_409
        """
        _year, vendor, _payment = setup_withheld_payment(amount_cents=100000)
        remittance = create_draft_remittance(tax_year=2025, quarter=1, creator_id="spec-1")
        submit_remittance(remittance["id"], submitter_id="xmtr-1")

        entries, meta = validate_paginated(
            api.list_withholding_entries(
                ADMIN, params={"vendor_id": vendor["id"], "entry_type": "DEBIT_WITHHELD"}
            )
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert entry["status"] == "REMITTED"

        resp = api.reverse_withholding_entry(entry["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ENTRY_ALREADY_REMITTED, 409)

        after = validate_success(api.get_withholding_entry(entry["id"], ADMIN), 200)
        assert after["status"] == "REMITTED"


class TestRemittanceLifecycle:
    def test_remittance_empty_set_boundary(self, api):
        """PRD §3.5: "Drafting is rejected with `ERR_NOTHING_TO_REMIT` when the
        matching entry set is empty or sums to zero or less."

        Design: Difficulty/boundary_precision_check/remittance_empty_set_boundary
        """
        create_tax_year()
        resp = api.create_remittance(
            {"tax_year": 2025, "quarter": 1}, make_tax_specialist_headers("spec-1")
        )
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_REMIT, 409)

    def test_remittance_zero_sum_set_boundary(self, api):
        """PRD §3.5: "Drafting is rejected with `ERR_NOTHING_TO_REMIT` when the
        matching entry set is empty or sums to zero or less."

        Design: Difficulty/boundary_precision_check/remittance_empty_set_boundary
        """
        _year, vendor, _payment = setup_withheld_payment(amount_cents=100000)
        entries, _ = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        # Reverse the only debit: the UNREMITTED pool for (2025, Q1) is now empty.
        validate_success(api.reverse_withholding_entry(entries[0]["id"], ADMIN), 200)

        resp = api.create_remittance(
            {"tax_year": 2025, "quarter": 1}, make_tax_specialist_headers("spec-1")
        )
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_REMIT, 409)

    def test_remittance_reject_reopen_cycle(self, api):
        """PRD §3.5: "A `REJECTED` outcome un-sweeps the entries: they return to
        `UNREMITTED`, their `remittance_id` is cleared, and each vendor's balance is
        recomputed."
        PRD §3.5: "A `TaxSpecialist` may reopen a `REJECTED` remittance, returning it
        to `DRAFT` and recomputing `amount_cents` from the current `UNREMITTED`
        entries."
        PRD §3.5: "An `ACKNOWLEDGED` outcome moves the remittance to its terminal
        `ACKNOWLEDGED` state."

        Design: Corner/state_machines/c_remittance_reject_reopen_cycle
        """
        _year, vendor, _payment = setup_withheld_payment(amount_cents=100000)
        remittance = create_draft_remittance(tax_year=2025, quarter=1, creator_id="spec-1")
        submit_remittance(remittance["id"], submitter_id="xmtr-1")

        rejected = validate_success(
            api.record_remittance_outcome(remittance["id"], {"outcome": "REJECTED"}, IRS), 200
        )
        assert rejected["status"] == "REJECTED"

        entries, _ = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert entries[0]["status"] == "UNREMITTED"
        assert entries[0].get("remittance_id") is None

        reopened = validate_success(api.reopen_remittance(remittance["id"], SPEC), 200)
        assert reopened["status"] == "DRAFT"
        # Recomputed from the current UNREMITTED entries.
        assert reopened["amount_cents"] == 24000

        resubmitted = submit_remittance(remittance["id"], submitter_id="xmtr-1")
        assert resubmitted["status"] == "SUBMITTED"
        acked = validate_success(
            api.record_remittance_outcome(remittance["id"], {"outcome": "ACKNOWLEDGED"}, IRS),
            200,
        )
        assert acked["status"] == "ACKNOWLEDGED"
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 0

    def test_sod_remittance_creator_cannot_submit(self, api):
        """PRD §2.11: "The `TaxTransmitter` who submits a remittance must not be the
        `TaxSpecialist` whose id was recorded as `created_by_user_id` when the draft
        was created... Any of these collisions is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/c_sod_remittance_creator_cannot_submit
        """
        _year, vendor, _payment = setup_withheld_payment(amount_cents=100000)
        remittance = create_draft_remittance(tax_year=2025, quarter=1, creator_id="spec-9")

        # Correct role, but the same user id that created the draft.
        resp = api.submit_remittance(remittance["id"], make_tax_transmitter_headers("spec-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        after = validate_success(api.get_remittance(remittance["id"], SPEC), 200)
        assert after["status"] == "DRAFT"
        entries, _ = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert all(e["status"] == "UNREMITTED" for e in entries)

    def test_derived_remittance_amount_reconciles_on_new_payment(self, api):
        """PRD §3.5: "The draft's `amount_cents` is computed on the accrual basis —
        the signed sum of all `UNREMITTED` entries matching that year-quarter — and
        is recomputed on every entry mutation while the remittance remains `DRAFT`."

        Design: Corner/cross_cutting_layers/c_derived_remittance_amount_reconciles_on_new_payment
        """
        _year, vendor, _payment = setup_withheld_payment(amount_cents=100000)
        remittance = create_draft_remittance(tax_year=2025, quarter=1, creator_id="spec-1")
        assert remittance["amount_cents"] == 24000

        # Another Q1 payment (withheld 12000) mutates the entry set.
        create_payment(vendor["id"], amount_cents=50000, payment_date="2025-03-15T00:00:00Z",
                       source_system="MANUAL")

        after = validate_success(api.get_remittance(remittance["id"], SPEC), 200)
        assert after["amount_cents"] == 36000


class TestRemittanceReconciliationBases:
    def test_remittance_accrual_vs_statutory_divergence_at_submit(self, api):
        """PRD §3.5: "A successful submit sweeps every `UNREMITTED` entry for the
        year-quarter into `REMITTED`, stamps each with the remittance's id in
        `remittance_id`, recomputes each affected vendor's balance, locks
        `amount_cents`, and computes and freezes `statutory_expected_cents` — the
        statutory comparison figure, which multiplies the sum of gross `amount_cents`
        over the year-quarter's `POSTED` payments whose `withheld_cents` is greater
        than zero by the year's rate in basis points divided by ten thousand,
        rounding half-up once over the aggregate."
        PRD §3.5: "The two bases legitimately diverge: the accrual figure sums
        per-payment rounded values while the statutory figure rounds once, so the API
        exposes both and never rejects on their difference."

        Design: Difficulty/dual_variant_calc/remittance_accrual_vs_statutory_divergence
        """
        create_tax_year()
        vendor, _w9 = create_mismatched_vendor(legal_name="Baker LLC", tin="123456789")
        create_payment(vendor["id"], amount_cents=1015, payment_date="2025-04-10T00:00:00Z")
        create_payment(vendor["id"], amount_cents=1040, payment_date="2025-05-10T00:00:00Z")

        remittance = create_draft_remittance(tax_year=2025, quarter=2, creator_id="spec-1")
        submitted = validate_success(
            api.submit_remittance(remittance["id"], make_tax_transmitter_headers("xmtr-1")),
            200,
        )
        assert_remittance(submitted)
        # Accrual: round_half_up(1015*.24) + round_half_up(1040*.24) = 244 + 250 = 494.
        assert submitted["amount_cents"] == 494
        # Statutory: round_half_up((1015 + 1040) * 0.24) = round_half_up(493.2) = 493.
        assert submitted["statutory_expected_cents"] == 493
        assert submitted["status"] == "SUBMITTED"

        after = validate_success(api.get_remittance(remittance["id"], SPEC), 200)
        assert after["amount_cents"] == 494
        assert after["statutory_expected_cents"] == 493

    def test_remittance_accrual_basis_at_draft_time(self, api):
        """PRD §3.5: "The draft's `amount_cents` is computed on the accrual basis —
        the signed sum of all `UNREMITTED` entries matching that year-quarter — and
        is recomputed on every entry mutation while the remittance remains `DRAFT`."

        Design: Difficulty/dual_variant_calc/remittance_accrual_vs_statutory_divergence
        """
        create_tax_year()
        vendor, _w9 = create_mismatched_vendor(legal_name="Baker2 LLC", tin="123456789")
        create_payment(vendor["id"], amount_cents=1015, payment_date="2025-04-10T00:00:00Z")
        create_payment(vendor["id"], amount_cents=1040, payment_date="2025-05-10T00:00:00Z")

        remittance = create_draft_remittance(tax_year=2025, quarter=2, creator_id="spec-1")
        assert remittance["status"] == "DRAFT"
        # Draft amount is the accrual-basis signed sum of the UNREMITTED pool.
        assert remittance["amount_cents"] == 494
        assert remittance["created_by_user_id"] == "spec-1"
