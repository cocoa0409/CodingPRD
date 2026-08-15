"""Entity-creation, default, retrieval, and pagination corner tests (PRD §2, §3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, ADMIN, INSPECTOR, NON_EXISTENT_UUID,
    create_landlord, create_voucher_family, create_payment_standard,
    create_landlord_payload, create_payment_standard_payload,
    setup_priced_unit, setup_active_scenario,
    create_draft_contract,
    assert_landlord, assert_hap_payment,
    list_hap_payments,
    make_landlord_headers,
)


class TestLandlordCreation:
    def test_create_returns_201_and_stored_fields(self, api):
        """PRD §3.1: "An admin supplies the `legal_name` and `tax_id`; `tax_id`
        is unique across all landlord records, so a duplicate tax ID is rejected
        at create time. The new landlord record starts in `ACTIVE` status."
        PRD §4: "Creating a new resource returns HTTP 201"

        Design: Corner/entities/landlord_create_returns_201_and_stored_fields
        """
        resp = api.create_landlord(
            create_landlord_payload(legal_name="Corner L1", tax_id="CT1"), ADMIN
        )
        data = validate_success(resp, expected_status=201)
        assert_landlord(data)
        assert data["version"] == 1, (
            f"version starts at 1 on creation (PRD §2.4), got {data['version']}"
        )
        assert data["status"] == "ACTIVE"
        assert data["legal_name"] == "Corner L1"
        assert data["tax_id"] == "CT1"

    def test_create_stores_tax_id_and_active_status(self, api):
        """PRD §3.1: "An admin supplies the `legal_name` and `tax_id`; `tax_id`
        is unique across all landlord records, so a duplicate tax ID is rejected
        at create time. The new landlord record starts in `ACTIVE` status."

        Design: Corner/entities/landlord_create_returns_201_and_stored_fields
        """
        resp = api.create_landlord(
            create_landlord_payload(legal_name="Corner L1b", tax_id="CT1b"), ADMIN
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        fetched = get_success_data(api.get_landlord(data["id"], ADMIN))
        assert fetched["legal_name"] == "Corner L1b"
        assert fetched["tax_id"] == "CT1b"


class TestLandlordGetNotFound:
    def test_get_nonexistent_landlord_returns_not_found(self, api):
        """PRD §2.5: "then existence of every path-parameter and
        body-referenced resource, validated left-to-right as the identifiers
        appear in the URL and then the payload (`ERR_NOT_FOUND`)"

        Design: Corner/entities/landlord_get_not_found
        """
        resp = api.get_landlord(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPaymentStandardDefaults:
    def test_omitted_effective_to_stored_null(self, api):
        """PRD §3.2: "Each row is effective from `effective_from` (an ISO
        `YYYY-MM-DD` date, inclusive) through `effective_to` (also inclusive); a
        null `effective_to` means the row is open-ended."

        Design: Corner/entities/payment_standard_effective_to_default_null
        """
        resp = api.create_payment_standard(
            create_payment_standard_payload(
                zip_code="90210", bedroom_count=3, amount_cents=250_000,
                effective_from="2026-01-01",
            ),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert "effective_to" in data, "effective_to key must be present on the row"
        assert data["effective_to"] is None, (
            f"omitted effective_to must be stored null (open-ended), got "
            f"{data['effective_to']!r}"
        )


class TestHapPaymentShape:
    def test_hap_payment_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "The `HAPPayment` entity is the exception: it carries only
        `id` and `created_at`. Both `updated_at` and `version` are absent on
        `HAPPayment` rows, and no endpoint exposes or requires a payment
        `version`."

        Design: Corner/entities/hap_payment_immutable_common_fields_false
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90300", family_code="CF2",
        )
        payments = list_hap_payments(contract["id"])
        assert payments, "activation must schedule exactly one HAPPayment row"
        for row in payments:
            assert_hap_payment(row)


class TestUnitDelistInvalidState:
    def test_delist_under_contract_unit_rejected(self, api):
        """PRD §3.1: "delisting is owner-only and is only defined while the unit
        is `LISTED`, so attempting it against an `UNDER_CONTRACT` or
        `SUSPENDED_ABATEMENT` unit is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/unit_delist_from_under_contract_rejected
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90301", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="CF3",
        )
        contract = create_draft_contract(unit, family, landlord)
        # The unit flipped LISTED -> UNDER_CONTRACT on contract creation.
        resp = api.delist_unit(unit["id"], make_landlord_headers(landlord["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestVoucherFamilyInitialState:
    def test_new_family_starts_searching(self, api):
        """PRD §3.1: "The family's `status` begins at `SEARCHING` and remains
        there until a contract activates."

        Design: Corner/state_machines/voucher_family_initial_state_searching
        """
        resp = api.create_voucher_family(
            {
                "family_code": "CF5",
                "voucher_bedroom_size": 2,
                "annual_income_cents": 1_000_000,
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SEARCHING", (
            f"a new voucher family begins SEARCHING, got {data['status']}"
        )


class TestListLandlordsPagination:
    def test_pagination_envelope_fields(self, api):
        """PRD §2.3: "List responses return rows sorted by `created_at`
        ascending, and the `meta` envelope includes `limit`, `offset`,
        `total_count`, and `has_more` so a client can page deterministically
        through a stable result set."

        Design: Corner/endpoints/list_landlords_pagination_envelope
        """
        create_landlord(legal_name="PL1", tax_id="PT1")
        create_landlord(legal_name="PL2", tax_id="PT2")
        resp = api.list_landlords(ADMIN, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert len(data) == 1, f"limit=1 must return exactly one row, got {len(data)}"
        assert meta["total_count"] == 2, (
            f"two landlords exist, expected total_count 2, got {meta['total_count']}"
        )
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestContractGetByInspector:
    def test_inspector_can_get_contract(self, api):
        """PRD §4: the `GET /hcv/contracts/{id}` row lists authorized roles
        `HousingAuthorityAdmin`, `Landlord`, `Inspector`.
        PRD §2.1: "`Inspector` — an HQS inspector. Like the admin, this role's
        `X-User-ID` is an opaque operator identifier not tied to any persisted
        entity."

        Design: Corner/endpoints/contract_get_by_inspector_allowed
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90309", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="CF12",
        )
        contract = create_draft_contract(unit, family, landlord)
        resp = api.get_contract(contract["id"], INSPECTOR)
        data = validate_success(resp)
        assert data["id"] == contract["id"]
        assert data["status"] == "DRAFT"
