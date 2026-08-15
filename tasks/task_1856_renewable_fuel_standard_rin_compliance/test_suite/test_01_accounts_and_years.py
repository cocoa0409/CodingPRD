"""Account, obligation-year, lot, and blending-record surface claims (PRD §3.1, §3.2)."""
import pytest

from test_helpers import (
    CM,
    NON_EXISTENT_UUID,
    OPS,
    ApiErrorId,
    assert_compliance_account,
    create_account,
    create_account_payload,
    create_account_and_year,
    create_generated_lot,
    create_obligation_year_payload,
    create_rin_lot_payload,
    create_trade,
    create_vendor,
    get_success_data,
    make_trader_headers,
    separate_lot,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestAccountCreateAndGet:
    def test_account_create_returns_system_fields(self, api):
        """PRD §3.1: "The account opens with `escrow_reserved_cents` and `spent_cents` both at zero"
        PRD §2.4: "Every primary resource carries a standard set of system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that increments by one on every mutation of the resource"

        Design: Corner/entities/account_create_and_get_roundtrip
        """
        payload = create_account_payload(
            company_name="Acme Refining", epa_registration_id="EPA-RT-1",
        )
        resp = api.create_compliance_account(payload, OPS)
        data = validate_success(resp, expected_status=201)
        assert_compliance_account(data)
        assert data["escrow_reserved_cents"] == 0
        assert data["spent_cents"] == 0
        assert data["version"] == 1
        assert data["created_at"] is not None

    def test_account_get_roundtrip_returns_stored_fields(self, api):
        """PRD §3.1: "An `OpsAdmin` registers each obligated party with its legal `company_name` and its EPA-issued `epa_registration_id`"

        Design: Corner/entities/account_create_and_get_roundtrip
        """
        acct = create_account(
            company_name="Acme Refining", epa_registration_id="EPA-RT-1",
        )
        resp = api.get_compliance_account(acct["id"], CM)
        data = validate_success(resp)
        assert data["company_name"] == "Acme Refining"
        assert data["epa_registration_id"] == "EPA-RT-1"
        assert data["escrow_reserved_cents"] == 0
        assert data["spent_cents"] == 0


class TestAccountNaturalKey:
    def test_duplicate_epa_registration_rejected(self, api):
        """PRD §3.1: "its EPA-issued `epa_registration_id`, which must be unique across accounts — a duplicate registration is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/account_duplicate_epa_registration_rejected
        """
        create_account(
            company_name="Acme Refining", epa_registration_id="EPA-DUP-1",
        )
        resp = api.create_compliance_account(
            {"company_name": "Other Refining", "epa_registration_id": "EPA-DUP-1"},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestYearCreationValidation:
    def test_missing_required_standard_rejected(self, api):
        """PRD §2.8: "Only then is the request body examined for shape: required fields present, enum values valid, quantities positive, the EPA standard percentages monotonically ordered, the quarter-end-date rule honored, and window bounds well formed — violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/year_create_missing_required_field
        """
        acct = create_account(epa_registration_id="EPA-REQ-1")
        payload = {
            "account_id": acct["id"],
            "year": 2026,
            "projected_volume_gal": 1000,
            "std_cellulosic_pct": 10.0,
            "std_biomass_diesel_pct": 20.0,
            "std_advanced_pct": 30.0,
        }
        resp = api.create_obligation_year(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_standards_must_be_monotonically_nondecreasing(self, api):
        """PRD §3.1: "The percentages must be non-negative and monotonically non-decreasing in that order — cellulosic may equal but never exceed biomass-based diesel, biomass-based diesel may equal but never exceed advanced, and advanced may equal but never exceed total — and a malformed set is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/year_standards_must_be_nondecreasing
        """
        acct = create_account(epa_registration_id="EPA-REQ-2")
        payload = create_obligation_year_payload(
            account_id=acct["id"], std_biomass_diesel_pct=30.0,
            std_advanced_pct=25.0,
        )
        resp = api.create_obligation_year(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLotInitialState:
    def test_new_generated_lot_active_with_all_rins_attached(self, api):
        """PRD §3.2: "At creation all of those RINs remain attached to physical gallons: `attached_qty` equals `rin_qty`, `separated_qty` is zero, and `available_qty` equals `rin_qty`, while `pending_retired_qty`, `retired_qty`, `invalidated_qty`, and `expired_qty` all start at zero."
        PRD §3.2: "Each lot fixes its `retention_until` at creation per §2.9 and opens in `ACTIVE` status."

        Design: Corner/state_machines/lot_initial_state_active
        """
        acct = create_account(epa_registration_id="EPA-SM-1")
        lot = create_generated_lot(acct["id"], d_code="D6", gallon_qty=50)
        assert lot["status"] == "ACTIVE"
        assert lot["attached_qty"] == 50
        assert lot["separated_qty"] == 0
        assert lot["available_qty"] == 50


class TestLotValidation:
    def test_invalid_d_code_enum_rejected(self, api):
        """PRD §3.2: "a `d_code` of `D3` (cellulosic), `D4` (biomass-based diesel), `D5` (advanced), or `D6` (conventional renewable)"
        PRD §2.8: "Only then is the request body examined for shape: required fields present, enum values valid, quantities positive, the EPA standard percentages monotonically ordered, the quarter-end-date rule honored, and window bounds well formed — violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/lot_create_invalid_d_code_enum
        """
        acct = create_account(epa_registration_id="EPA-REQ-3")
        payload = create_rin_lot_payload(account_id=acct["id"], d_code="D9")
        resp = api.create_rin_lot(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_lot_not_found(self, api):
        """PRD §2.8: "Next, path identifiers are resolved strictly left to right, and the first identifier that does not name an existing resource yields `ERR_NOT_FOUND`."

        Design: Corner/entities/lot_get_not_found
        """
        resp = api.get_rin_lot(NON_EXISTENT_UUID, CM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLotListing:
    def test_list_filter_by_account_and_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints paginate through two query parameters: `limit`, the maximum number of items returned, defaults to 10 and accepts values from a minimum of 1 to a maximum of 100; `offset`, the number of items skipped, defaults to 0."
        PRD §3.2: "Lots may be listed with optional `account_id`, `vendor_id`, or `trade_id` filters"

        Design: Corner/entities/rin_lots_list_filter_and_pagination
        """
        acct_a = create_account(epa_registration_id="EPA-LST-1")
        acct_b = create_account(epa_registration_id="EPA-LST-2")
        create_generated_lot(acct_a["id"], d_code="D6", gallon_qty=10)
        create_generated_lot(
            acct_b["id"], d_code="D4", gallon_qty=20, equivalence_value=1.5,
        )
        resp = api.list_rin_lots(CM, params={"account_id": acct_a["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert all(lot["account_id"] == acct_a["id"] for lot in data)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestBlendingRecordImmutability:
    def test_blending_record_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "One deliberate exception exists: the BlendingRecord is an immutable event log and carries only `id` and `created_at` — `updated_at` and `version` are absent because a blending record, once written, never changes."

        Design: Corner/entities/blending_record_immutable_event
        """
        acct = create_account(epa_registration_id="EPA-IMM-1")
        lot = create_generated_lot(acct["id"], gallon_qty=10)
        br = separate_lot(lot["id"], 4)
        resp = api.get_blending_record(br["id"], CM)
        data = validate_success(resp)
        assert "version" not in data
        assert "updated_at" not in data
        assert data["blended_gallons"] == 4
        assert data["rin_lot_id"] == lot["id"]

    def test_blending_record_retention_is_created_at_plus_1825_days(self, api):
        """PRD §2.9: "each carries a `retention_until` timestamp fixed at creation as its `created_at` plus 1825 days — a five-year retention expressed as a fixed day count so that leap years are absorbed."
        PRD §3.2: "Each blending writes an immutable BlendingRecord that copies the `account_id` from the separated lot, takes the `rin_lot_id` from the request path, stamps `blended_at` from the logical clock, and fixes its own `retention_until`."

        Design: Corner/entities/blending_record_immutable_event
        """
        from datetime import datetime, timedelta, timezone

        acct = create_account(epa_registration_id="EPA-IMM-9")
        lot = create_generated_lot(acct["id"], gallon_qty=10)
        br = separate_lot(lot["id"], 4)
        resp = api.get_blending_record(br["id"], CM)
        data = validate_success(resp)
        created = datetime.fromisoformat(
            data["created_at"].replace("Z", "+00:00"),
        )
        retention = datetime.fromisoformat(
            data["retention_until"].replace("Z", "+00:00"),
        )
        assert retention - created == timedelta(days=1825)


class TestComputedFields:
    def test_rin_qty_computed_per_lot_rounding(self, api):
        """PRD §2.5: "When a lot is generated, its RIN quantity is the wet-gallon volume multiplied by its equivalence value, rounded half-up to zero decimal places — and that rounding is applied per lot at the moment of generation."

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        acct = create_account(epa_registration_id="EPA-CMP-1")
        lot = create_generated_lot(
            acct["id"], d_code="D4", gallon_qty=101, equivalence_value=1.5,
        )
        assert lot["rin_qty"] == 152

    def test_trade_total_price_is_exact_integer_product(self, api):
        """PRD §3.3: "The trade's `total_price_cents` is the exact integer product of quantity and unit price"

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        acct = create_account(epa_registration_id="EPA-CMP-2")
        ven = create_vendor(acct["id"])
        trd = create_trade(acct["id"], ven["id"], rin_qty=12, price_per_rin_cents=137)
        assert trd["total_price_cents"] == 1644


class TestBodyForeignKeys:
    def test_trade_with_missing_vendor_is_reference_error(self, api):
        """PRD §3.3: "The vendor must exist and belong to the trade's account (`ERR_REFERENCE_NOT_FOUND` otherwise)."
        PRD §2.8: "Referential integrity of body foreign keys follows: a referenced account, vendor, obligation year, state program, or RIN lot that does not exist — or sibling references that belong to different accounts, such as a trade whose vendor belongs to another desk — yields `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/entities/body_fk_reference_must_exist
        """
        acct = create_account(epa_registration_id="EPA-FK-1")
        payload = {
            "account_id": acct["id"],
            "vendor_id": NON_EXISTENT_UUID,
            "d_code": "D6",
            "vintage_year": 2026,
            "rin_qty": 10,
            "price_per_rin_cents": 100,
        }
        resp = api.create_rin_trade(payload, make_trader_headers("tr-1"))
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)
