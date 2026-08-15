"""Activity records and the landing-fee charge: the five-hundred-kilogram
remainder boundary, the signature-status rate pick, and request validation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    adopt_rates_for_year,
    assert_activity_record,
    create_activity_record_payload,
    create_airline,
    set_clock,
    setup_open_year,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import add_activity

FINANCE = TEST_USERS["finance_headers"]

# Pool geometry shared by the charge tests: airfield requirement 100_000_000
# cents over a 100_000 kg forecast derives a signatory fee of 1_000_000 cents
# per 1_000 kg and a non-signatory fee of 1_250_000 cents per 1_000 kg.
CHARGE_POOL = dict(
    airfield_opex_cents=100000000,
    terminal_opex_cents=0,
    nonairline_airfield_revenue_cents=0,
    nonairline_terminal_revenue_cents=0,
    terminal_total_space_sqft=100000,
    forecast_landed_weight_kg=100000,
    prior_year_surplus_cents=0,
)
SIGNATORY_RATE = 1000000
NON_SIGNATORY_RATE = 1250000


def _setup_adopted_year(api, label, iata):
    ws = setup_open_year(label, **CHARGE_POOL)
    airline = create_airline(iata, legal_name=f"{iata} Air")
    adopt_rates_for_year(ws)
    return ws, airline


class TestChargeUnitsAndRatePick:
    def test_remainder_below_500_rounds_down_at_500_rounds_up(self, api):
        """PRD §3.3: "The landed weight is broken into whole units of one
        thousand kilograms; a remainder of at least five hundred kilograms is
        rounded up as one additional full unit, while a smaller remainder is
        discarded — so a record landing exactly 1,499 kilograms bills a single
        unit, a record at exactly 1,500 kilograms bills two, and a remainder
        sitting exactly on the five-hundred-kilogram boundary always rounds
        up."
        PRD §3.3: "The per-unit rate is the adopted schedule's signatory fee
        when `signature_status_at_activity` is `SIGNATORY` and the
        non-signatory fee otherwise."

        Design: Difficulty/combinatorial_formula/landing_fee_charge_non_linear_threshold_and_tier
        """
        ws, airline = _setup_adopted_year(api, "FY_NL", "NL")

        rec_1499 = add_activity(ws["fy"]["id"], airline["id"], 1499,
                                activity_date="2026-09-05T00:00:00Z")
        assert_activity_record(rec_1499)
        assert rec_1499["billed_landing_fee_cents"] == 1 * SIGNATORY_RATE, (
            "1,499 kg bills a single unit; the 499 kg remainder is discarded")

        rec_1500 = add_activity(ws["fy"]["id"], airline["id"], 1500,
                                activity_date="2026-09-06T00:00:00Z")
        assert rec_1500["billed_landing_fee_cents"] == 2 * SIGNATORY_RATE, (
            "1,500 kg bills two units; the 500 kg remainder rounds up")

    def test_non_signatory_snapshot_picks_marked_up_rate(self, api):
        """PRD §3.3: "The snapshot, not the carrier's present standing, drives
        the rate pick."
        PRD §3.3: "The per-unit rate is the adopted schedule's signatory fee
        when `signature_status_at_activity` is `SIGNATORY` and the
        non-signatory fee otherwise. The resulting `billed_landing_fee_cents`
        is the number of charge units multiplied by that per-unit rate, in
        whole cents."

        Design: Difficulty/combinatorial_formula/landing_fee_charge_non_linear_threshold_and_tier
        """
        ws, airline = _setup_adopted_year(api, "FY_NL2", "NS")

        record = add_activity(ws["fy"]["id"], airline["id"], 1500,
                              signature_status_at_activity="NON_SIGNATORY",
                              activity_date="2026-09-07T00:00:00Z")
        assert record["billed_landing_fee_cents"] == 2 * NON_SIGNATORY_RATE, (
            "Two charge units at the non-signatory fee")


class TestRemainderBoundary:
    def test_1499kg_bills_one_unit(self, api):
        """PRD §3.3: "The landed weight is broken into whole units of one
        thousand kilograms; a remainder of at least five hundred kilograms is
        rounded up as one additional full unit, while a smaller remainder is
        discarded — so a record landing exactly 1,499 kilograms bills a single
        unit, a record at exactly 1,500 kilograms bills two, and a remainder
        sitting exactly on the five-hundred-kilogram boundary always rounds
        up."

        Design: Difficulty/boundary_precision_check/landing_fee_500kg_remainder_boundary
        """
        ws, airline = _setup_adopted_year(api, "FY_BND1", "BN")

        record = add_activity(ws["fy"]["id"], airline["id"], 1499,
                              signature_status_at_activity="NON_SIGNATORY",
                              activity_date="2026-09-05T00:00:00Z")
        assert record["billed_landing_fee_cents"] == NON_SIGNATORY_RATE

    def test_1500kg_bills_two_units(self, api):
        """PRD §3.3: "a remainder sitting exactly on the five-hundred-kilogram
        boundary always rounds up."
        PRD §3.3: "The resulting `billed_landing_fee_cents` is the number of
        charge units multiplied by that per-unit rate, in whole cents."

        Design: Difficulty/boundary_precision_check/landing_fee_500kg_remainder_boundary
        """
        ws, airline = _setup_adopted_year(api, "FY_BND2", "BT")

        record = add_activity(ws["fy"]["id"], airline["id"], 1500,
                              signature_status_at_activity="NON_SIGNATORY",
                              activity_date="2026-09-06T00:00:00Z")
        assert record["billed_landing_fee_cents"] == 2 * NON_SIGNATORY_RATE


class TestActivityRecordValidation:
    def test_missing_airline_id_rejected(self, api):
        """PRD §2.8: "Field shape follows: a missing required field, a
        wrong-typed value, or an enum value outside its declared set yields
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "`AirportFinance` records each landing as an
        **ActivityRecord** beneath the fiscal year, providing the `airline_id`,
        the `activity_date`, the `landed_weight_kg`"

        Design: Corner/entities/activity_record_required_fields
        """
        ws = setup_open_year("FY_REQ")

        payload = create_activity_record_payload(NON_EXISTENT_UUID)
        del payload["airline_id"]
        resp = api.create_activity_record(ws["fy"]["id"], payload, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_body_airline_reference_must_exist(self, api):
        """PRD §2.9: "Existence inside the request body is a separate, later
        check: a body that names a carrier, fiscal year, capital project, or
        settlement that does not exist is rejected with `ERR_FK_NOT_FOUND`, and
        only after path validation has already succeeded."

        Design: Corner/validations/fk_not_found_body_reference
        """
        ws = setup_open_year("FY_FK")

        payload = create_activity_record_payload(NON_EXISTENT_UUID)
        resp = api.create_activity_record(ws["fy"]["id"], payload, FINANCE)
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)

        data, meta = validate_paginated(
            api.list_activity_records(ws["fy"]["id"], FINANCE))
        assert meta["total_count"] == 0, "No activity may be persisted"
