"""Park, Lot, and Home creation — CRUD, uniqueness, ownership-pool counter."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_home,
    assert_lot,
    assert_park,
    create_home_payload,
    create_lot,
    create_lot_payload,
    create_park,
    create_park_payload,
    create_resident,
    get_park,
    make_park_manager_headers,
    random_vin,
    register_home,
    validate_error,
    validate_success,
)


# ===========================================================================
# Park creation — PRD §3.1
# ===========================================================================
class TestParkCreation:
    def test_create_park_returns_park_shape(self, api):
        """PRD §3.1: 'A freshly created park reports an
        ownership_pool_count of zero.'

        Claim: POST /parks returns the canonical Park shape with
        ownership_pool_count == 0.
        """
        resp = api.create_park(
            create_park_payload(state_code="CA", master_cpi_pct=2.00),
            TEST_USERS["park_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_park(data)
        assert data["ownership_pool_count"] == 0, (
            "PRD §3.1: 'A freshly created park reports an "
            "ownership_pool_count of zero.'"
        )

    @pytest.mark.parametrize("state_code", ["CA", "FL", "OR", "AZ", "TX"])
    def test_all_documented_state_codes_accepted(self, api, state_code):
        """PRD §2.9: 'Each Park declares the state in which it operates
        via the state_code field, which must be one of CA, FL, OR, AZ,
        or TX.'

        Claim: every documented state_code is accepted on POST /parks.
        """
        resp = api.create_park(
            create_park_payload(state_code=state_code),
            TEST_USERS["park_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["state_code"] == state_code


# ===========================================================================
# Lot creation — PRD §3.1
# ===========================================================================
class TestLotCreation:
    def test_new_lot_starts_park_owned(self, api):
        """PRD §3.1: 'A new lot begins life with its ownership_mode set
        to PARK_OWNED, a null home_id, and a null current_lease_id.'

        Claim: a freshly created lot reports ownership_mode=PARK_OWNED
        and null home_id / current_lease_id.
        """
        park = create_park()
        lot = create_lot(park["id"])
        assert_lot(lot)
        assert lot["ownership_mode"] == "PARK_OWNED"
        assert lot["home_id"] is None
        assert lot["current_lease_id"] is None

    def test_lot_creation_increments_ownership_pool_count(self, api):
        """PRD §3.1: 'the lot creation step also bumps the parent
        park's ownership_pool_count by one.'

        Claim: creating one lot increments Park.ownership_pool_count
        by exactly one.
        """
        park = create_park()
        assert park["ownership_pool_count"] == 0
        create_lot(park["id"])
        refreshed = get_park(park["id"])
        assert refreshed["ownership_pool_count"] == 1, (
            "PRD §3.1: 'the lot creation step also bumps the parent "
            "park's ownership_pool_count by one.'"
        )

    def test_duplicate_lot_number_within_park_rejected(self, api):
        """PRD §3.1: 'lot_number (a 1-to-16-character string that must
        be unique within its parent park — duplicates are rejected
        with ERR_DUPLICATE_LOT_NUMBER).'

        Claim: re-using a lot_number within the same Park →
        ERR_DUPLICATE_LOT_NUMBER.
        """
        park = create_park()
        create_lot(park["id"], lot_number="L01")
        resp = api.create_lot(
            park["id"],
            create_lot_payload("L01", base_rent_cents=200_000),
            make_park_manager_headers(park["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER.value)

    def test_same_lot_number_across_different_parks_allowed(self, api):
        """PRD §3.1: 'lot_number (a 1-to-16-character string that must
        be unique within its parent park — duplicates are rejected
        with ERR_DUPLICATE_LOT_NUMBER).'

        Claim: the same lot_number under a different Park is allowed
        (uniqueness is scoped to the parent park, not global).
        """
        park_a = create_park()
        park_b = create_park()
        create_lot(park_a["id"], lot_number="L01")
        lot_b = create_lot(park_b["id"], lot_number="L01")
        assert lot_b["lot_number"] == "L01"


# ===========================================================================
# Home registration — PRD §3.1
# ===========================================================================
class TestHomeRegistration:
    def test_home_on_park_owned_lot_has_null_owner(self, api):
        """PRD §3.1: 'A home registered on a PARK_OWNED lot has its
        owner_resident_id set to null — the park itself is the implied
        owner.'

        Claim: POST /parks/{id}/homes on a PARK_OWNED lot returns a
        Home with owner_resident_id == null.
        """
        park = create_park()
        lot = create_lot(park["id"])
        home = register_home(
            park_id=park["id"], lot_id=lot["id"],
            assessed_value_cents=4_000_000,
        )
        assert_home(home)
        assert home["owner_resident_id"] is None, (
            "PRD §3.1: 'A home registered on a PARK_OWNED lot has its "
            "owner_resident_id set to null.'"
        )
        assert home["lot_id"] == lot["id"]

    def test_duplicate_vin_rejected_globally(self, api):
        """PRD §3.1: 'vin (exactly 17 characters, uppercase letters A–Z
        and digits 0–9, globally unique — duplicates are rejected with
        ERR_DUPLICATE_VIN).'

        Claim: re-using a VIN anywhere in the system →
        ERR_DUPLICATE_VIN.
        """
        park_a = create_park()
        lot_a = create_lot(park_a["id"])
        vin = random_vin()
        register_home(park_id=park_a["id"], lot_id=lot_a["id"], vin=vin)
        park_b = create_park()
        lot_b = create_lot(park_b["id"])
        resp = api.create_home(
            park_b["id"],
            create_home_payload(lot_id=lot_b["id"], vin=vin,
                                assessed_value_cents=1_000_000),
            make_park_manager_headers(park_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN.value)

    def test_vin_must_be_exactly_17_chars(self, api):
        """PRD §3.1: 'vin (exactly 17 characters, uppercase letters A–Z
        and digits 0–9, globally unique — duplicates are rejected
        with ERR_DUPLICATE_VIN).'

        Claim: POST /homes returns a Home whose VIN has length 17
        (the only acceptable length).
        """
        park = create_park()
        lot = create_lot(park["id"])
        # Use a fresh 17-char VIN.
        home = register_home(park["id"], lot["id"])
        assert len(home["vin"]) == 17
