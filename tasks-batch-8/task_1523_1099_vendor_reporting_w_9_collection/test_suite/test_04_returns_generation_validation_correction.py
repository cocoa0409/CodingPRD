"""Return generation (thresholds, idempotency, provisional snapshots),
validation gates, and the correction lifecycle."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    SPEC,
    ApiErrorId,
    assert_tax_return,
    create_accepted_return,
    create_matched_vendor,
    create_mismatched_vendor,
    create_payment,
    create_tax_year,
    create_validated_return,
    generate_returns,
    get_single_return,
    get_vendor,
    list_returns,
    make_tax_specialist_headers,
    record_match,
    submit_w9,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGenerationThresholds:
    def test_nec_threshold_exact_600_boundary(self, api):
        """PRD §3.6: "An NEC return exists for the vendor-year exactly when the
        `NEC_1` total is at least the year's `nec_reportable_threshold_cents`..."
        PRD §3.1: "`nec_reportable_threshold_cents` defaults to 60000 (six hundred
        dollars)..."

        Design: Difficulty/boundary_precision_check/nec_threshold_exact_600
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Edge V", tin="454545454")
        create_payment(vendor["id"], amount_cents=40000, payment_date="2025-03-01T00:00:00Z")
        create_payment(vendor["id"], amount_cents=19999, payment_date="2025-03-02T00:00:00Z")

        first = generate_returns(2025)
        # 59999 < 60000: below the inclusive boundary.
        assert first["generated_count"] == 0

        create_payment(vendor["id"], amount_cents=1, payment_date="2025-03-03T00:00:00Z",
                       source_system="MANUAL")
        second = generate_returns(2025)
        # 60000 >= 60000: the boundary is inclusive.
        assert second["generated_count"] == 1

        tax_return = get_single_return(vendor["id"], tax_year=2025)
        assert tax_return["box_amounts"]["box_1_cents"] == 60000

    def test_nec_threshold_below_and_at_with_fresh_vendors(self, api):
        """PRD §3.6: "An NEC return exists for the vendor-year exactly when the
        `NEC_1` total is at least the year's `nec_reportable_threshold_cents`; a MISC
        return exists exactly when the sum of the `MISC_1`, `MISC_2`, `MISC_3`, and
        `MISC_6` totals is at least the year's `misc_reportable_threshold_cents`."

        Design: Difficulty/boundary_precision_check/nec_threshold_exact_600
        """
        create_tax_year()
        below, _ = create_matched_vendor(legal_name="Below V", tin="464646464")
        create_payment(below["id"], amount_cents=59999, payment_date="2025-03-01T00:00:00Z")
        exact, _ = create_matched_vendor(legal_name="Exact V", tin="474747474")
        create_payment(exact["id"], amount_cents=60000, payment_date="2025-03-01T00:00:00Z")

        result = generate_returns(2025)
        # Exactly one vendor-year crosses the inclusive threshold.
        assert result["generated_count"] == 1

        below_rows, below_meta = validate_paginated(
            api.list_returns(SPEC, params={"vendor_id": below["id"]})
        )
        exact_rows, exact_meta = validate_paginated(
            api.list_returns(SPEC, params={"vendor_id": exact["id"]})
        )
        assert below_meta["total_count"] == 0
        assert exact_meta["total_count"] == 1
        assert exact_rows[0]["box_amounts"]["box_1_cents"] == 60000

    def test_misc_threshold_uses_box_sum(self, api):
        """PRD §3.6: "a MISC return exists exactly when the sum of the `MISC_1`,
        `MISC_2`, `MISC_3`, and `MISC_6` totals is at least the year's
        `misc_reportable_threshold_cents`."
        PRD §3.6: "the `MISC_1`, `MISC_2`, `MISC_3`, and `MISC_6` totals populate
        `box_1_cents`, `box_2_cents`, `box_3_cents`, and `box_6_cents` of a MISC form
        respectively."

        Design: Corner/calculations/c_misc_threshold_uses_box_sum
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(
            legal_name="Misc V", tin="753753753", tin_type="EIN",
            entity_classification="PARTNERSHIP",
        )
        create_payment(vendor["id"], amount_cents=30000, payment_date="2025-06-01T00:00:00Z",
                       payment_type="RENT")
        create_payment(vendor["id"], amount_cents=30000, payment_date="2025-06-02T00:00:00Z",
                       payment_type="ROYALTY")

        result = generate_returns(2025)
        assert result["generated_count"] == 1

        tax_return = get_single_return(vendor["id"], tax_year=2025)
        # Each box alone is below 60000; the MISC threshold applies to the sum.
        assert tax_return["form_type"] == "MISC"
        assert tax_return["box_amounts"]["box_1_cents"] == 30000
        assert tax_return["box_amounts"]["box_2_cents"] == 30000


class TestGenerationAggregation:
    def test_return_box4_aggregates_withheld(self, api):
        """PRD §3.6: "For each such vendor the system aggregates box sums over the
        vendor's `POSTED`, reportable payments for the year, grouped by
        `reportable_box`, and computes `box_4_cents` as the sum of `withheld_cents`
        over the same `POSTED` in-year payment set, regardless of reportability."

        Design: Corner/calculations/c_return_box4_aggregates_withheld
        """
        create_tax_year()
        vendor, _ = create_mismatched_vendor(
            legal_name="Box4 V", tin="357357357", reason_code="IRS_CODE_2"
        )
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")
        create_payment(vendor["id"], amount_cents=50000, payment_date="2025-06-02T00:00:00Z")

        generate_returns(2025)
        tax_return = get_single_return(vendor["id"], tax_year=2025)
        assert_tax_return(tax_return)
        assert tax_return["box_amounts"]["box_1_cents"] == 150000
        # Gross reportable is not reduced by withholding; box 4 carries 24000 + 12000.
        assert tax_return["box_amounts"]["box_4_cents"] == 36000

    def test_aggregation_across_source_systems(self, api):
        """PRD §3.4: "Four source systems — `AP_ERP`, `CORP_CARD`, `MANUAL`, and
        `FIELD_OFFICE` — feed the same ledger, and payments from all four aggregate
        onto a single vendor-year return."
        PRD §3.6: "For each such vendor the system aggregates box sums over the
        vendor's `POSTED`, reportable payments for the year, grouped by
        `reportable_box`..."

        Design: Corner/calculations/c_aggregation_across_source_systems
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Agg V", tin="951951951")
        create_payment(vendor["id"], amount_cents=30000, payment_date="2025-06-01T00:00:00Z",
                       source_system="AP_ERP")
        create_payment(vendor["id"], amount_cents=20000, payment_date="2025-06-02T00:00:00Z",
                       source_system="CORP_CARD")
        create_payment(vendor["id"], amount_cents=10000, payment_date="2025-06-03T00:00:00Z",
                       source_system="MANUAL")
        create_payment(vendor["id"], amount_cents=5000, payment_date="2025-06-04T00:00:00Z",
                       source_system="FIELD_OFFICE")
        doomed = create_payment(vendor["id"], amount_cents=7000,
                                payment_date="2025-06-05T00:00:00Z", source_system="MANUAL")
        validate_success(api.void_payment(doomed["id"], CLERK), 200)

        generate_returns(2025)
        tax_return = get_single_return(vendor["id"], tax_year=2025)
        # 30000 + 20000 + 10000 + 5000 = 65000; the VOIDED 7000 is excluded.
        assert tax_return["box_amounts"]["box_1_cents"] == 65000

    def test_generate_idempotent_skip(self, api):
        """PRD §3.6: "Generation is idempotent per key: when a vendor-year-form
        combination already has a non-terminal return (`DRAFT`, `VALIDATED`,
        `TRANSMITTED`, or `ACCEPTED`), that combination is skipped and counted. The
        response reports `generated_count`, the `generated_return_ids` array, and
        `skipped_count`."

        Design: Corner/endpoints/c_generate_idempotent_skip
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Idem V", tin="333000333")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")

        first = generate_returns(2025)
        assert first["generated_count"] == 1
        assert len(first["generated_return_ids"]) == 1

        second = generate_returns(2025)
        assert second["generated_count"] == 0
        assert second["skipped_count"] == 1

        rows, meta = validate_paginated(
            api.list_returns(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 1


class TestProvisionalVsFinal:
    def test_return_box_provisional_vs_final_on_late_payment(self, api):
        """PRD §3.6: "Generation captures a provisional snapshot: the aggregation
        runs over the payments that exist at the moment of the call, and the result
        is frozen into both `provisional_box_amounts` and `box_amounts` with
        `amount_basis` set to `PROVISIONAL`. The provisional snapshot is never
        overwritten afterward."
        PRD §3.7: "Each member return moves from `VALIDATED` to `TRANSMITTED`, has
        its `transmittal_id` set, and is recomputed to the final basis with
        `amount_basis` becoming `FINAL`..."

        Design: Difficulty/dual_variant_calc/return_box_provisional_vs_final_on_late_payment
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Able Contracting", tin="123456789")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-03-10T00:00:00Z")
        generate_returns(2025)
        tax_return = get_single_return(vendor["id"], tax_year=2025)
        assert tax_return["amount_basis"] == "PROVISIONAL"
        assert tax_return["box_amounts"]["box_1_cents"] == 100000
        assert tax_return["provisional_box_amounts"]["box_1_cents"] == 100000

        # A late-recorded payment dated in-year, created AFTER generation.
        create_payment(vendor["id"], amount_cents=25000, payment_date="2025-11-20T00:00:00Z",
                       source_system="CORP_CARD")

        validate_success(api.validate_return(tax_return["id"], SPEC), 200)
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        validate_success(
            api.seal_transmittal(transmittal["id"], make_tax_specialist_headers("spec-1")),
            200,
        )

        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        # FINAL recompute includes the late payment; the provisional snapshot is frozen.
        assert after["provisional_box_amounts"]["box_1_cents"] == 100000
        assert after["box_amounts"]["box_1_cents"] == 125000
        assert after["amount_basis"] == "FINAL"
        assert after["federal_status"] == "TRANSMITTED"

    def test_late_payment_does_not_rewrite_provisional_draft(self, api):
        """PRD §3.6: "Generation captures a provisional snapshot: the aggregation
        runs over the payments that exist at the moment of the call, and the result
        is frozen into both `provisional_box_amounts` and `box_amounts` with
        `amount_basis` set to `PROVISIONAL`. The provisional snapshot is never
        overwritten afterward. A final-basis aggregation — over all of the vendor's
        `POSTED` in-year payments, including payments recorded after generation but
        dated in-year — overwrites `box_amounts` and sets `amount_basis` to `FINAL`;
        this happens at transmittal seal and on every invalidation event (payment
        void or withholding reversal on the same vendor-year, a merge re-parent, or
        an `entity_classification` change)."

        Design: Difficulty/dual_variant_calc/return_box_provisional_vs_final_on_late_payment
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Able2 Contracting", tin="123456789")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-03-10T00:00:00Z")
        generate_returns(2025)
        tax_return = get_single_return(vendor["id"], tax_year=2025)

        # A late payment is neither a seal nor an invalidation event.
        create_payment(vendor["id"], amount_cents=25000, payment_date="2025-11-20T00:00:00Z",
                       source_system="CORP_CARD")

        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert after["federal_status"] == "DRAFT"
        assert after["amount_basis"] == "PROVISIONAL"
        assert after["box_amounts"]["box_1_cents"] == 100000
        assert after["provisional_box_amounts"]["box_1_cents"] == 100000


class TestReturnLifecycle:
    def test_return_initial_state_draft_pending_copy(self, api):
        """PRD §3.6: "Generation captures a provisional snapshot: the aggregation
        runs over the payments that exist at the moment of the call, and the result
        is frozen into both `provisional_box_amounts` and `box_amounts` with
        `amount_basis` set to `PROVISIONAL`."
        PRD §3.7: "Recipient copy delivery runs on a parallel status dimension,
        `recipient_copy_status`, which starts at `PENDING` and moves independently of
        the federal lifecycle."

        Design: Corner/state_machines/c_return_initial_state_draft_pending_copy
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Init V", tin="654654654")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")
        generate_returns(2025)

        tax_return = get_single_return(vendor["id"], tax_year=2025)
        assert_tax_return(tax_return)
        assert tax_return["federal_status"] == "DRAFT"
        assert tax_return["recipient_copy_status"] == "PENDING"
        assert tax_return["amount_basis"] == "PROVISIONAL"
        assert tax_return["is_correction"] is False
        assert tax_return["version"] == 1

    def test_validate_twice_returns_409(self, api):
        """PRD §3.6: "Validation requires the return to be `DRAFT` (otherwise
        `ERR_INVALID_STATE_TRANSITION`)..."

        Design: Corner/state_machines/c_validate_twice_returns_409
        """
        create_tax_year()
        _vendor, _payment, tax_return = create_validated_return(
            legal_name="Twice V", tin="789789789"
        )
        assert tax_return["federal_status"] == "VALIDATED"

        resp = api.validate_return(tax_return["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert after["federal_status"] == "VALIDATED"

    def test_deactivate_blocked_with_open_return(self, api):
        """PRD §3.2: "Deactivation requires the vendor's `withholding_balance_cents`
        to be exactly zero and no `DRAFT` or `VALIDATED` return to exist for the
        vendor; either condition blocks the action with
        `ERR_VENDOR_HAS_OPEN_OBLIGATIONS`."

        Design: Corner/state_machines/c_deactivate_blocked_with_open_return
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Deact V", tin="852852852")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")
        generate_returns(2025)

        resp = api.deactivate_vendor(vendor["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_VENDOR_HAS_OPEN_OBLIGATIONS, 409)
        assert get_vendor(vendor["id"])["status"] == "ACTIVE"


class TestValidateW9Gate:
    def test_validate_blocked_while_rematch_pending_then_succeeds(self, api):
        """PRD §3.3: "While a vendor sits in `PENDING_MATCH`, return validation is
        blocked with `ERR_W9_NOT_ON_FILE`; returns already `VALIDATED` when a
        re-submission lands are unaffected and simply wait for the new result."
        PRD §3.6: "Validation requires the return to be `DRAFT` (otherwise
        `ERR_INVALID_STATE_TRANSITION`), the vendor's `tin_match_status` to be
        `MATCHED` or `MISMATCHED` with a non-null `tin` (otherwise
        `ERR_W9_NOT_ON_FILE` — so a vendor sitting in `PENDING_MATCH` cannot be
        validated)..."

        Design: Difficulty/cross_entity_state_dependency/validate_blocked_while_rematch_pending
        """
        create_tax_year()
        vendor, _w1 = create_matched_vendor(legal_name="ReV", tin="898989898")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")
        generate_returns(2025)
        tax_return = get_single_return(vendor["id"], tax_year=2025)

        # Re-submission moves the vendor back to PENDING_MATCH.
        w2 = submit_w9(vendor["id"], submitted_tin="898989898", submitted_tin_type="SSN",
                       signature_name="R2")
        assert get_vendor(vendor["id"])["tin_match_status"] == "PENDING_MATCH"

        blocked = api.validate_return(tax_return["id"], SPEC)
        validate_error(blocked, ApiErrorId.ERR_W9_NOT_ON_FILE, 409)

        record_match(w2["id"], "MATCHED")
        ok = validate_success(api.validate_return(tax_return["id"], SPEC), 200)
        assert ok["federal_status"] == "VALIDATED"

    def test_validated_return_unaffected_by_rematch_and_payment_gated(self, api):
        """PRD §3.3: "While a vendor sits in `PENDING_MATCH`, return validation is
        blocked with `ERR_W9_NOT_ON_FILE`; returns already `VALIDATED` when a
        re-submission lands are unaffected and simply wait for the new result."
        PRD §3.4: "Posting is guarded by the vendor's compliance posture: the vendor
        must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), its `tin_match_status` must be
        `MATCHED` or `MISMATCHED` (`ERR_W9_NOT_ON_FILE`)..."

        Design: Difficulty/cross_entity_state_dependency/validate_blocked_while_rematch_pending
        """
        create_tax_year()
        vendor, _payment, tax_return = create_validated_return(
            legal_name="ReV2", tin="898989898"
        )
        assert tax_return["federal_status"] == "VALIDATED"

        submit_w9(vendor["id"], submitted_tin="898989898", submitted_tin_type="SSN",
                  signature_name="R2")
        assert get_vendor(vendor["id"])["tin_match_status"] == "PENDING_MATCH"

        # The already-VALIDATED return simply waits.
        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert after["federal_status"] == "VALIDATED"

        # But new payments are gated while the match is pending.
        resp = api.create_payment(
            {
                "vendor_id": vendor["id"],
                "source_system": "AP_ERP",
                "payment_type": "SERVICE",
                "amount_cents": 1000,
                "payment_date": "2025-06-02T00:00:00Z",
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_W9_NOT_ON_FILE, 409)


class TestCorrections:
    def test_correct_on_draft_returns_409(self, api):
        """PRD §3.6: "A `TaxSpecialist` creates a correction against an original
        whose `federal_status` is `ACCEPTED`; correcting anything else, or correcting
        while another non-terminal correction of the same original exists, is
        rejected with `ERR_RETURN_NOT_CORRECTABLE`."

        Design: Corner/validations/c_correct_on_draft_returns_409
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="CorrDraft V", tin="456123789")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-06-01T00:00:00Z")
        generate_returns(2025)
        tax_return = get_single_return(vendor["id"], tax_year=2025)
        assert tax_return["federal_status"] == "DRAFT"

        # Fresh version — OCC passes, so the domain rule is what fires.
        resp = api.correct_return(
            tax_return["id"], {"expected_return_version": tax_return["version"]}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_CORRECTABLE, 409)

    def test_occ_return_correct_stale(self, api):
        """PRD §2.8: "Creating a correction against an accepted return likewise
        requires `expected_return_version`, the client-side copy of the original
        return's `version`; if another writer has advanced that version since the
        client last read it, the correction is rejected with `ERR_STALE_VERSION`
        (HTTP 412), because the client may be acting on a view that predates a
        competing correction draft."

        Design: Corner/cross_cutting_layers/c_occ_return_correct_stale
        """
        create_tax_year()
        _vendor, _payment, tax_return, _t = create_accepted_return(
            legal_name="OccR V", tin="666000666"
        )
        assert tax_return["federal_status"] == "ACCEPTED"
        current_version = tax_return["version"]

        resp = api.correct_return(
            tax_return["id"], {"expected_return_version": current_version - 1}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        # No correction was created for this original.
        rows, meta = validate_paginated(
            api.list_returns(SPEC, params={"corrects_return_id": tax_return["id"]})
        )
        assert meta["total_count"] == 0
