"""Payment recording: box classification matrix, withholding at posting,
per-payment rounding order, and the payment-creation validation gates."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    SPEC,
    ApiErrorId,
    assert_payment,
    create_matched_vendor,
    create_mismatched_vendor,
    create_payment,
    create_tax_year,
    create_vendor,
    get_vendor,
    make_tax_transmitter_headers,
    record_match,
    submit_w9,
    validate_error,
    validate_paginated,
    validate_success,
)


def _post_payment(api, vendor_id, **overrides):
    payload = {
        "vendor_id": vendor_id,
        "source_system": "AP_ERP",
        "payment_type": "SERVICE",
        "amount_cents": 70000,
        "payment_date": "2025-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return api.create_payment(payload, CLERK)


class TestBoxClassificationMatrix:
    def test_box_mapping_service_matrix_and_attorney_pierce(self, api):
        """PRD §3.4: "`ATTORNEY_FEE` payments are always reportable to `NEC_1` — the
        corporate exemption does not apply — and `MEDICAL_HEALTH` payments are always
        reportable to `MISC_6`, likewise exempt from the corporate exemption."
        PRD §3.4: "For the remaining types the corporate exemption applies: a
        `SERVICE` payment maps to `NEC_1` unless the vendor is corporate-exempt
        (then `NONE`)..."

        Design: Difficulty/combinatorial_formula/box_mapping_classification_matrix
        """
        create_tax_year()
        ind, _ = create_matched_vendor(legal_name="Ind", tin="111111111")
        corp, _ = create_matched_vendor(
            legal_name="Corp", tin="222222222", tin_type="EIN",
            entity_classification="C_CORP",
        )

        ind_svc = validate_success(
            _post_payment(api, ind["id"], payment_type="SERVICE"), 201
        )
        assert_payment(ind_svc)
        assert ind_svc["reportable_box"] == "NEC_1"
        assert ind_svc["is_reportable"] is True

        corp_svc = validate_success(
            _post_payment(api, corp["id"], payment_type="SERVICE"), 201
        )
        assert corp_svc["reportable_box"] == "NONE"
        assert corp_svc["is_reportable"] is False

        # The corporate exemption does not apply to attorney fees.
        corp_atty = validate_success(
            _post_payment(
                api, corp["id"], payment_type="ATTORNEY_FEE", amount_cents=30000,
                payment_date="2025-06-02T00:00:00Z",
            ),
            201,
        )
        assert corp_atty["reportable_box"] == "NEC_1"
        assert corp_atty["is_reportable"] is True

    def test_box_mapping_medical_rent_and_never_reportable_types(self, api):
        """PRD §3.4: "Payments of type `GOODS` or `REIMBURSEMENT` are never
        reportable and map to `NONE`."
        PRD §3.4: "`RENT` maps to `MISC_1`, `ROYALTY` to `MISC_2`, and `PRIZE_AWARD`
        to `MISC_3`, each unless the vendor is corporate-exempt."
        PRD §3.4: "`MEDICAL_HEALTH` payments are always reportable to `MISC_6`,
        likewise exempt from the corporate exemption."

        Design: Difficulty/combinatorial_formula/box_mapping_classification_matrix
        """
        create_tax_year()
        llcs, _ = create_matched_vendor(
            legal_name="Llcs", tin="333333333", tin_type="EIN",
            entity_classification="LLC_S",
        )
        ind, _ = create_matched_vendor(legal_name="Ind", tin="444444444")

        # Corporate-exempt classification does not shield medical payments.
        llcs_med = validate_success(
            _post_payment(api, llcs["id"], payment_type="MEDICAL_HEALTH", amount_cents=50000),
            201,
        )
        assert llcs_med["reportable_box"] == "MISC_6"
        assert llcs_med["is_reportable"] is True

        ind_rent = validate_success(
            _post_payment(api, ind["id"], payment_type="RENT", amount_cents=20000),
            201,
        )
        assert ind_rent["reportable_box"] == "MISC_1"
        assert ind_rent["is_reportable"] is True

        goods = validate_success(
            _post_payment(api, ind["id"], payment_type="GOODS", amount_cents=20000),
            201,
        )
        assert goods["reportable_box"] == "NONE"
        assert goods["is_reportable"] is False

        reimbursement = validate_success(
            _post_payment(api, ind["id"], payment_type="REIMBURSEMENT", amount_cents=20000),
            201,
        )
        assert reimbursement["reportable_box"] == "NONE"
        assert reimbursement["is_reportable"] is False


class TestWithholdingAtPosting:
    def test_withholding_per_payment_rounding_order_discriminates(self, api):
        """PRD §2.6: "One rounding order is pinned and non-negotiable: backup
        withholding is rounded per payment first, and ledger balances and remittance
        totals are sums of those per-payment rounded values. The alternative order —
        summing gross payments, multiplying, and rounding once — is forbidden for the
        ledger because it diverges from per-payment rounding by up to one cent per
        payment."
        PRD §3.4: "When the vendor's `backup_withholding_flag` is true at posting,
        the payment's `withheld_cents` is the gross `amount_cents` multiplied by the
        covering tax year's `backup_withholding_rate_bps`, divided by ten thousand,
        and rounded half-up to whole cents..."

        Design: Difficulty/combinatorial_formula/withholding_per_payment_rounding_order
        """
        create_tax_year()
        vendor, _ = create_mismatched_vendor(
            legal_name="Round Test", tin="444444444", tin_type="EIN",
            entity_classification="PARTNERSHIP", reason_code="IRS_CODE_2",
        )

        p1 = validate_success(
            _post_payment(api, vendor["id"], amount_cents=1015,
                          payment_date="2025-03-01T00:00:00Z", source_system="MANUAL"),
            201,
        )
        p2 = validate_success(
            _post_payment(api, vendor["id"], amount_cents=1040,
                          payment_date="2025-03-02T00:00:00Z", source_system="MANUAL"),
            201,
        )
        # round_half_up(1015 * 0.24) = round_half_up(243.6) = 244
        assert p1["withheld_cents"] == 244
        # round_half_up(1040 * 0.24) = round_half_up(249.6) = 250
        assert p2["withheld_cents"] == 250
        # Per-payment-then-sum: 244 + 250 = 494. The forbidden aggregate order
        # would give round_half_up(2055 * 0.24) = 493.
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 494

    def test_withholding_per_payment_rounding_order_three_payments(self, api):
        """PRD §2.6: "One rounding order is pinned and non-negotiable: backup
        withholding is rounded per payment first, and ledger balances and remittance
        totals are sums of those per-payment rounded values."
        PRD §2.10: "A vendor's `withholding_balance_cents` is always the signed sum
        of that vendor's entries whose status is `UNREMITTED`; nothing else
        contributes."

        Design: Difficulty/combinatorial_formula/withholding_per_payment_rounding_order
        """
        create_tax_year()
        vendor, _ = create_mismatched_vendor(legal_name="Round3", tin="454545454")

        amounts = [1015, 1040, 100]
        expected_each = [244, 250, 24]
        for i, (amount, expected) in enumerate(zip(amounts, expected_each)):
            payment = validate_success(
                _post_payment(api, vendor["id"], amount_cents=amount,
                              payment_date=f"2025-03-0{i + 1}T00:00:00Z"),
                201,
            )
            assert payment["withheld_cents"] == expected
        # Per-payment sum 244 + 250 + 24 = 518; aggregate rounding of
        # (1015 + 1040 + 100) * 0.24 = 517.2 would give 517.
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 518

    def test_withholding_zero_when_flag_off(self, api):
        """PRD §3.4: "when the flag is false, `withheld_cents` is zero. Whenever
        `withheld_cents` is greater than zero, posting also creates a
        `DEBIT_WITHHELD` ledger entry in `UNREMITTED` status..."

        Design: Corner/calculations/c_withholding_zero_when_flag_off
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Zero V", tin="159159159")
        payment = validate_success(_post_payment(api, vendor["id"], amount_cents=100000), 201)
        assert payment["withheld_cents"] == 0

        entries, meta = validate_paginated(
            api.list_withholding_entries(SPEC, params={"vendor_id": vendor["id"]})
        )
        assert meta["total_count"] == 0
        assert entries == []

    def test_rate_threshold_flag_reset_on_match(self, api):
        """PRD §3.3: "A `MATCHED` result completes the vendor's identity record: the
        vendor's `tin`, `tin_type`, and `legal_name` are overwritten with
        `submitted_tin`, `submitted_tin_type`, and `submitted_legal_name`, the
        vendor's `tin_match_status` becomes `MATCHED`, and the
        `backup_withholding_flag` is recomputed — true only if the vendor's
        `b_notice_stage` is `SECOND`."
        PRD §3.4: "When the vendor's `backup_withholding_flag` is true at posting,
        the payment's `withheld_cents` is the gross `amount_cents` multiplied by the
        covering tax year's `backup_withholding_rate_bps`, divided by ten thousand,
        and rounded half-up to whole cents — per the pinned per-payment rounding
        order of §2.6; when the flag is false, `withheld_cents` is zero."

        Design: Corner/cross_cutting_layers/c_rate_threshold_flag_reset_on_match
        """
        create_tax_year()
        vendor, _w1 = create_mismatched_vendor(
            legal_name="Flag V", tin="888000888", reason_code="IRS_CODE_1"
        )
        during = validate_success(_post_payment(api, vendor["id"], amount_cents=100000), 201)
        assert during["withheld_cents"] == 24000

        w2 = submit_w9(vendor["id"], submitted_tin="888000888", submitted_tin_type="SSN",
                       signature_name="F2")
        record_match(w2["id"], "MATCHED")

        after = validate_success(
            _post_payment(api, vendor["id"], amount_cents=50000,
                          payment_date="2025-06-02T00:00:00Z"),
            201,
        )
        assert after["withheld_cents"] == 0

        final = get_vendor(vendor["id"])
        assert final["backup_withholding_flag"] is False
        # Prior accrual is not retroactively refunded.
        assert final["withholding_balance_cents"] == 24000

    def test_immediate_visibility_after_payment(self, api):
        """PRD §3.4: "The payment's `tax_year` is computed as the calendar year of
        `payment_date`, and its withholding quarter is the payment month divided by
        three and rounded up to a whole number, yielding one through four."
        PRD §2.10: "A vendor's `withholding_balance_cents` is always the signed sum
        of that vendor's entries whose status is `UNREMITTED`; nothing else
        contributes."

        Design: Corner/consistency_model/c_immediate_visibility_after_payment
        """
        create_tax_year()
        vendor, _ = create_mismatched_vendor(
            legal_name="Imm C", tin="999000999", reason_code="IRS_CODE_4"
        )
        payment = validate_success(_post_payment(api, vendor["id"], amount_cents=100000), 201)
        # The creation response already carries the computed fields.
        assert payment["tax_year"] == 2025
        assert payment["reportable_box"] == "NEC_1"
        assert payment["withheld_cents"] == 24000
        # The very next read reflects the new balance — no reconciliation lag.
        assert get_vendor(vendor["id"])["withholding_balance_cents"] == 24000


class TestPaymentGates:
    def test_payment_w9_gate_returns_409(self, api):
        """PRD §3.4: "Posting is guarded by the vendor's compliance posture: the
        vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), its `tin_match_status`
        must be `MATCHED` or `MISMATCHED` (`ERR_W9_NOT_ON_FILE`)..."

        Design: Corner/validations/c_payment_w9_gate_returns_409
        """
        create_tax_year()
        vendor = create_vendor(legal_name="Gate V")
        resp = _post_payment(api, vendor["id"], amount_cents=1000)
        validate_error(resp, ApiErrorId.ERR_W9_NOT_ON_FILE, 409)

    def test_payment_no_tax_year_returns_422(self, api):
        """PRD §3.4: "the `payment_date` must fall inside an existing tax year's
        half-open period (`ERR_NO_TAX_YEAR`), and that year must still be `OPEN`
        (`ERR_TAX_YEAR_CLOSED`)."

        Design: Corner/validations/c_payment_no_tax_year_returns_422
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="NoYear V", tin="159753486")
        resp = _post_payment(
            api, vendor["id"], amount_cents=1000, payment_date="2024-06-01T00:00:00Z"
        )
        validate_error(resp, ApiErrorId.ERR_NO_TAX_YEAR, 422)

    def test_payment_zero_amount_returns_422(self, api):
        """PRD §3.4: "A missing or non-positive `amount_cents` draws
        `ERR_INVALID_AMOUNT`."

        Design: Corner/validations/c_payment_zero_amount_returns_422
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="ZeroAmt V", tin="357951456")
        resp = _post_payment(api, vendor["id"], amount_cents=0)
        validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT, 422)

    def test_payment_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.7: "Malformed bodies, unknown fields, invalid enum members, missing
        required fields, and bad date ranges are rejected with `ERR_INVALID_REQUEST`
        wherever they arise in the ladder."
        PRD §3.4: "Four source systems — `AP_ERP`, `CORP_CARD`, `MANUAL`, and
        `FIELD_OFFICE` — feed the same ledger..."

        Design: Corner/entities/c_payment_invalid_enum_returns_invalid_request
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Enum V", tin="123123123")
        resp = _post_payment(api, vendor["id"], amount_cents=1000, source_system="BITCOIN")
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_payment_unknown_field_returns_invalid_request(self, api):
        """PRD §2.7: "Malformed bodies, unknown fields, invalid enum members, missing
        required fields, and bad date ranges are rejected with `ERR_INVALID_REQUEST`
        wherever they arise in the ladder."

        Design: Corner/entities/c_payment_unknown_field_returns_invalid_request
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Strict V", tin="321321321")
        resp = _post_payment(api, vendor["id"], amount_cents=1000, legacy_ref="OLD-77")
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_wrong_role_payment_returns_forbidden(self, api):
        """PRD §2.1: "Access to every endpoint is restricted by role, and an attempt
        to perform an action outside the caller's designated role is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/validations/c_wrong_role_payment_returns_forbidden
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Role V", tin="852741963")
        payload = {
            "vendor_id": vendor["id"],
            "source_system": "AP_ERP",
            "payment_type": "SERVICE",
            "amount_cents": 1000,
            "payment_date": "2025-06-01T00:00:00Z",
        }
        resp = api.create_payment(payload, make_tax_transmitter_headers("xmtr-9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestPaymentTemporalPrecedence:
    def test_payment_temporal_beats_fiscal_closed_year_negative_amount(self, api):
        """PRD §2.7: "Every request walks an ordered ladder of checks, and a failure
        at any rung short-circuits the ladder — the caller always receives the
        earliest applicable rejection, never a later one that an earlier failure
        would have masked."
        PRD §2.7: "8. **Temporal rules.** Payment dates must fall inside an existing,
        open tax-year period, and copy delivery must precede the year's copy deadline
        (`ERR_NO_TAX_YEAR`, `ERR_TAX_YEAR_CLOSED`, `ERR_COPY_DEADLINE_PASSED`)."
        PRD §2.7: "11. **Fiscal rules.** Payment amounts must be positive, and a
        remittance must cover a non-empty, positive-sum entry set
        (`ERR_INVALID_AMOUNT`, `ERR_NOTHING_TO_REMIT`)."

        Design: Difficulty/priority_pair_validation_conflict/payment_temporal_beats_fiscal
        """
        year = create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Tempo V", tin="343434343")
        close = api.close_tax_year(year["id"], ADMIN)
        validate_success(close, 200)

        # Both rung 8 (closed year) and rung 11 (negative amount) are violated;
        # the temporal error must win.
        resp = _post_payment(api, vendor["id"], amount_cents=-100)
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED, 409)

    def test_payment_temporal_beats_fiscal_uncovered_year_negative_amount(self, api):
        """PRD §2.7: "Every request walks an ordered ladder of checks, and a failure
        at any rung short-circuits the ladder — the caller always receives the
        earliest applicable rejection, never a later one that an earlier failure
        would have masked."
        PRD §3.4: "the `payment_date` must fall inside an existing tax year's
        half-open period (`ERR_NO_TAX_YEAR`), and that year must still be `OPEN`
        (`ERR_TAX_YEAR_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/payment_temporal_beats_fiscal
        """
        create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Tempo2 V", tin="343434343")
        # No tax year covers 2024 (rung 8) AND the amount is negative (rung 11).
        resp = _post_payment(
            api, vendor["id"], amount_cents=-100, payment_date="2024-06-01T00:00:00Z"
        )
        validate_error(resp, ApiErrorId.ERR_NO_TAX_YEAR, 422)
