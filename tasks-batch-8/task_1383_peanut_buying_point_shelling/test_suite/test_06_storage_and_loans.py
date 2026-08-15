"""Storage layered gates, loan pledges, collateral variants, foreclosure."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_warehouse,
    api_client,
    assert_loan_pledge,
    assert_storage_receipt,
    create_loan_pledge_payload,
    create_sheet,
    finalize_sheet,
    get_loan_pledge,
    get_load,
    get_storage_receipt,
    get_warehouse,
    get_buying_point,
    make_grower_headers,
    pledge_full_receipt,
    report_load,
    set_clock,
    setup_cleared_load,
    setup_settlement_foundation,
    setup_stored_load,
    store_load,
    validate_error,
    validate_success,
    weigh_load,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStorageGates:

    def test_store_untested_load_rejected(self):
        """PRD section 3.7: "The aflatoxin axis must be `PASSED` or
        `SEGREGATED` (`ERR_AFLATOXIN_NOT_CLEARED`)."

        Design: Corner/errors/store_untested_load_rejected
        """
        f = setup_settlement_foundation()
        load, _sheet = _graded_only(f)
        resp = api_client.create_storage_receipt(
            {"load_id": load["id"], "warehouse_id": f["warehouse"]["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_AFLATOXIN_NOT_CLEARED)
        assert get_load(load["id"])["status"] == "GRADED"
        resp = api_client.list_storage_receipts(
            ADMIN, params={"load_id": load["id"]})
        assert resp.json()["meta"]["total_count"] == 0

    def test_store_segregated_into_general_reports_safety_not_capacity(self):
        """PRD section 2.9 lists the fixed evaluation order and §2.9 places
        "Segregation of duties and compliance gates" (8) ahead of "Uniqueness
        and overlap constraints" including warehouse capacity (9): "When
        several checks could fire on the same request, the server evaluates
        them in a fixed order and reports the first failure".
        PRD section 3.7: "a `SEGREGATED` load requires a `SEGREGATED`
        compartment and a `PASSED` load requires a `GENERAL` compartment
        (`ERR_COMPARTMENT_SEGREGATION`)."

        Design: Difficulty/priority_pair_validation_conflict/store_safety_error_beats_capacity_error
        """
        f = setup_settlement_foundation()
        wh_s = add_warehouse(f["bp"]["id"], name="WH-S", compartment="SEGREGATED",
                             capacity_tons=24)
        # shrink WH-G so both compartments are too small for a 25t load
        wh_g = add_warehouse(f["bp"]["id"], name="WH-G2", compartment="GENERAL",
                             capacity_tons=24)
        load, _sheet, _cert = setup_cleared_load(
            f["grower"]["id"], result_ppb=18.5)  # SEGREGATE band
        assert get_load(load["id"])["aflatoxin_status"] == "SEGREGATED"

        # Dual failure on the GENERAL warehouse: compartment mismatch AND
        # capacity shortfall (free 24 < gross 25) -> safety error wins.
        resp = api_client.create_storage_receipt(
            {"load_id": load["id"], "warehouse_id": wh_g["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_COMPARTMENT_SEGREGATION)

    def test_store_segregated_into_segregated_reports_capacity(self):
        """PRD section 3.7: "And the warehouse's `free_tons` must be at least
        the load's `gross_tons` (`ERR_WAREHOUSE_CAPACITY`)."

        Design: Difficulty/priority_pair_validation_conflict/store_safety_error_beats_capacity_error
        """
        f = setup_settlement_foundation()
        wh_s = add_warehouse(f["bp"]["id"], name="WH-S", compartment="SEGREGATED",
                             capacity_tons=24)
        load, _sheet, _cert = setup_cleared_load(
            f["grower"]["id"], result_ppb=18.5)

        # Compartment clean, capacity still short -> capacity error fires.
        resp = api_client.create_storage_receipt(
            {"load_id": load["id"], "warehouse_id": wh_s["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_CAPACITY)

        assert get_load(load["id"])["status"] == "GRADED"
        resp = api_client.list_storage_receipts(
            ADMIN, params={"load_id": load["id"]})
        assert resp.json()["meta"]["total_count"] == 0


class TestImmediateConsistency:

    def test_immediate_consistency_read_after_write(self):
        """PRD section 3.7: "The receipt opens `OPEN` with `tons_initial` equal
        to the load's gross tonnage, a `segregated` snapshot that is true
        exactly when the load's aflatoxin axis was `SEGREGATED` at store time,
        and `stored_at` stamped from the logical clock; the warehouse's
        `stored_tons` increases by the gross tonnage, the buying point's
        posture recomputes, the load moves `GRADED` → `STORED`, and the load's
        `version` increments."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        f = setup_settlement_foundation()
        load, _sheet, _cert = setup_cleared_load(f["grower"]["id"])
        receipt = store_load(load["id"], f["warehouse"]["id"])

        assert_storage_receipt(receipt)
        assert receipt["status"] == "OPEN"
        assert receipt["tons_initial"] == 25.0
        assert receipt["tons_remaining"] == 25.0
        assert receipt["segregated"] is False
        assert receipt["stored_at"].startswith("2026-09-01T09:00:00")

        wh = get_warehouse(f["warehouse"]["id"])
        assert wh["stored_tons"] == 25
        assert wh["free_tons"] == 1975

        assert get_load(load["id"])["status"] == "STORED"
        assert get_buying_point(f["bp"]["id"])["intake_posture"] == "OPEN"


class TestLoanPledge:

    def test_pledge_amount_bounds(self):
        """PRD section 3.7: "the full-receipt pledge rule applies:
        `pledged_tons` must equal the receipt's `tons_remaining` — pledging
        less is rejected with `ERR_INVALID_REQUEST`, pledging more with
        `ERR_LOAN_UNDER_COLLATERALIZED`."

        Design: Corner/errors/pledge_amount_bounds
        """
        f = setup_settlement_foundation()
        load, _sheet, _cert, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        gid = f["grower"]["id"]

        resp = api_client.create_loan_pledge(
            create_loan_pledge_payload(grower_id=gid,
                                       storage_receipt_id=receipt["id"],
                                       pledged_tons=25.001),
            make_grower_headers(gid))
        validate_error(resp, ApiErrorId.ERR_LOAN_UNDER_COLLATERALIZED)

        resp = api_client.create_loan_pledge(
            create_loan_pledge_payload(grower_id=gid,
                                       storage_receipt_id=receipt["id"],
                                       pledged_tons=20.0),
            make_grower_headers(gid))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        pledge = pledge_full_receipt(gid, receipt["id"], pledged_tons=25.0)
        assert_loan_pledge(pledge)
        assert pledge["status"] == "ACTIVE"
        # all-quota principal: 25 x 35500
        assert pledge["principal_cents"] == 887500
        assert get_storage_receipt(receipt["id"])["status"] == "PLEDGED"

    def test_collateral_dual_variant_values_at_creation(self):
        """PRD section 3.7: "`collateral_value_standard_cents` values the quota
        portion at the quota purchase price and the additional portion at the
        additional purchase price, each product rounded half up to whole cents
        and summed. `collateral_value_conservative_cents` values all pledged
        tons at the additional-tier price."
        PRD section 3.7: "`principal_cents` is the quota portion times
        `loan_rate_quota_cents_per_ton`, rounded half up to whole cents, plus
        the additional portion times `loan_rate_additional_cents_per_ton`,
        rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/collateral_coverage_dual_variant_margin_flip
        """
        f = setup_settlement_foundation()
        load, _sheet, _cert, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        pledge = pledge_full_receipt(f["grower"]["id"], receipt["id"],
                                     pledged_tons=25.0)
        assert pledge["principal_cents"] == 887500  # 25 x 35500
        assert pledge["quota_part_tons"] == 25.0
        assert pledge["additional_part_tons"] == 0
        assert pledge["collateral_value_standard_cents"] == 1400000  # 25 x 56000
        assert pledge["collateral_value_conservative_cents"] == 1000000  # 25 x 40000
        assert pledge["accrued_interest_cents"] == 0
        # day 0: outstanding 887500; threshold 887500 x 1.10 = 976250 <= 1000000
        assert pledge["margin_status"] == "MARGIN_OK"

    def test_margin_flips_to_call_on_day_122(self):
        """PRD section 3.7: "Interest accrues on `outstanding_principal_cents`
        at two basis points per day — two ten-thousandths of principal per
        whole day elapsed from `pledged_at`, partial days discarded".
        PRD section 3.7: "`margin_status` is `MARGIN_OK` when the conservative
        value is at least 110 percent of the outstanding principal plus
        interest accrued to the current clock — the threshold is compared
        exactly, with no rounding — and `MARGIN_CALL` otherwise."

        Design: Difficulty/dual_variant_calc/collateral_coverage_dual_variant_margin_flip
        """
        f = setup_settlement_foundation()
        load, _sheet, _cert, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        pledge = pledge_full_receipt(f["grower"]["id"], receipt["id"],
                                     pledged_tons=25.0)

        set_clock("2026-12-31T09:00:00Z")  # day 121
        p121 = get_loan_pledge(pledge["id"])
        assert p121["accrued_interest_cents"] == 21478  # 177.5 x 121 = 21477.5 half-up
        assert p121["outstanding_principal_cents"] == 887500
        # threshold (887500 + 21478) x 1.10 = 999875.80 <= 1000000
        assert p121["margin_status"] == "MARGIN_OK"
        assert p121["collateral_value_standard_cents"] == 1400000

        set_clock("2027-01-01T09:00:00Z")  # day 122
        p122 = get_loan_pledge(pledge["id"])
        assert p122["accrued_interest_cents"] == 21655
        # threshold (887500 + 21655) x 1.10 = 1000070.50 > 1000000
        assert p122["margin_status"] == "MARGIN_CALL"
        assert p122["collateral_value_standard_cents"] == 1400000, \
            "standard variant still clears — the conservative variant decides the flag"

    def test_foreclose_maturity_boundary(self):
        """PRD section 3.7: "it requires the current logical clock to be
        strictly later than `maturity_date` (otherwise
        `ERR_FORECLOSE_NOT_MATURED`) and the outstanding principal plus accrued
        interest to be above zero (otherwise `ERR_INVALID_STATE`)."
        PRD section 3.7: "records `foreclosure_credit_cents` as the amount by
        which the standard collateral value exceeds the outstanding exposure
        (zero when it does not), moves the receipt `PLEDGED` → `FORFEITED`,
        zeroes the receipt's `tons_remaining`, reduces the warehouse's
        `stored_tons` by that tonnage, and recomputes the buying point's
        posture."

        Design: Corner/validations/foreclose_maturity_boundary
        """
        f = setup_settlement_foundation()
        load, _sheet, _cert, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        pledge = pledge_full_receipt(f["grower"]["id"], receipt["id"],
                                     pledged_tons=25.0)

        set_clock("2026-11-30T00:00:00Z")  # maturity-eve
        resp = api_client.foreclose_loan_pledge(pledge["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORECLOSE_NOT_MATURED)

        set_clock("2026-12-02T09:00:00Z")  # day 92, strictly past maturity
        foreclosed = validate_success(
            api_client.foreclose_loan_pledge(pledge["id"], ADMIN))
        assert foreclosed["status"] == "FORECLOSED"
        # outstanding = 887500 + round(887500 x 0.0002 x 92) = 887500 + 16330 = 903830
        # credit = 1400000 - 903830
        assert foreclosed["foreclosure_credit_cents"] == 496170

        receipt_after = get_storage_receipt(receipt["id"])
        assert receipt_after["status"] == "FORFEITED"
        assert receipt_after["tons_remaining"] == 0
        wh = get_warehouse(f["warehouse"]["id"])
        assert wh["stored_tons"] == 0
        assert wh["free_tons"] == 2000


def _graded_only(f):
    """Report + weigh + grade-finalize (no aflatoxin draw). Returns (load, sheet)."""
    load = report_load(f["grower"]["id"])
    weighed = weigh_load(load["id"], 25.0)
    sheet = create_sheet(load["id"], weighed["version"])
    finalize_sheet(sheet["id"])
    return get_load(load["id"]), sheet
