"""Party registry creation, tract creation, and 404 handling (PRD §2.8, §3.1)."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_buyer,
    assert_forester,
    assert_tract,
    create_buyer_payload,
    create_forester_payload,
    create_landowner_payload,
    create_tract_payload,
    make_forester_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_party_registry_entities(api):
    """PRD §3.1: "Registering a timber buyer records the mill's `company_name`
    and its timber-buyer `license_no`, and optionally accepts a `prior_defaults`
    count that seeds the buyer's contract-default history — it starts at 0 when
    not supplied".

    Design: Corner/entities/create_party_registry_entities
    """
    forester = validate_success(
        api.create_forester(create_forester_payload(license_no="F-100"), ADMIN), 201
    )
    buyer = validate_success(
        api.create_buyer(create_buyer_payload(license_no="B-100"), ADMIN), 201
    )
    assert_forester(forester)
    assert_buyer(buyer)
    assert forester["license_no"] == "F-100"
    assert buyer["prior_defaults"] == 0


def test_create_tract_happy_and_defaults(api):
    """PRD §3.1: "Every tract begins life with `status` `OPEN`, and its
    `conservation_enrollment_start` and `conservation_enrollment_end` remain
    null unless a carbon valuation is later accepted against it."

    Design: Corner/entities/create_tract_happy_and_defaults
    """
    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    landowner = get_success_data(api.create_landowner(create_landowner_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])
    resp = api.create_tract(
        create_tract_payload(landowner_id=landowner["id"], forester_id=forester["id"]),
        fh,
    )
    tract = validate_success(resp, 201)
    assert_tract(tract)
    assert tract["status"] == "OPEN"
    assert tract["version"] == 1
    assert tract["conservation_enrollment_start"] is None


def test_create_tract_missing_required_field_returns_invalid_request(api):
    """PRD §2.7: "Request schema: required fields are present, types are valid,
    enum values fall in their declared sets, dates are well-formed, amounts
    declared non-negative are non-negative, and unknown fields are rejected
    (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/create_tract_missing_required_field_returns_invalid_request
    """
    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])
    resp = api.create_tract(
        {
            "name": "Tract A",
            "county": "Covington",
            "total_acres": 100,
            "forester_id": forester["id"],
        },
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_stand_extra_field_rejected(api):
    """PRD §2.7: "unknown fields are rejected (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/create_stand_extra_field_rejected
    """
    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    landowner = get_success_data(api.create_landowner(create_landowner_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])
    tract = get_success_data(api.create_tract(
        create_tract_payload(landowner_id=landowner["id"], forester_id=forester["id"]),
        fh,
    ))
    resp = api.create_stand(
        {
            "tract_id": tract["id"],
            "name": "Stand 1",
            "acres": 50,
            "primary_species": "PINE",
            "bogus_field": 1,
        },
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_sale_not_found_returns_404(api):
    """PRD §2.8: "Each resource type has its own not-found error, so a caller
    can tell exactly which reference failed: ... `ERR_SALE_NOT_FOUND` for a sale".

    Design: Corner/entities/get_sale_not_found_returns_404
    """
    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])
    resp = api.get_sale(NON_EXISTENT_UUID, fh)
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_FOUND)


def test_create_tract_with_bad_party_reference_returns_party_not_found(api):
    """PRD §2.8: "`ERR_PARTY_NOT_FOUND` for any of the four registry parties
    (forester, landowner, buyer, contractor)".

    Design: Corner/entities/create_tract_with_bad_party_reference_returns_party_not_found
    """
    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])
    resp = api.create_tract(
        create_tract_payload(landowner_id=NON_EXISTENT_UUID, forester_id=forester["id"]),
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_PARTY_NOT_FOUND)


def test_resource_not_found_family_returns_per_entity_404(api):
    """PRD §2.8: "Each resource type has its own not-found error, so a caller
    can tell exactly which reference failed: `ERR_PARTY_NOT_FOUND` for any of
    the four registry parties ..., `ERR_TRACT_NOT_FOUND` for a tract,
    `ERR_STAND_NOT_FOUND` for a stand, ... and `ERR_VALUATION_NOT_FOUND` for a
    carbon valuation. All carry HTTP 404."

    Design: Corner/validations/resource_not_found_family_returns_per_entity_404
    """
    forester = get_success_data(api.create_forester(create_forester_payload(), ADMIN))
    fh = make_forester_headers(forester["id"])

    cases = [
        ("tract", lambda: api.get_tract(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_TRACT_NOT_FOUND),
        ("stand", lambda: api.get_stand(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_STAND_NOT_FOUND),
        ("cruise", lambda: api.get_cruise(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_CRUISE_NOT_FOUND),
        ("prescription", lambda: api.get_prescription(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_PRESCRIPTION_NOT_FOUND),
        ("sale", lambda: api.get_sale(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_SALE_NOT_FOUND),
        ("bid", lambda: api.get_bid(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_BID_NOT_FOUND),
        ("contract", lambda: api.get_contract(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        ("bond", lambda: api.get_bond(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_BOND_NOT_FOUND),
        ("settlement", lambda: api.get_settlement(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
        ("inspection", lambda: api.get_inspection(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        ("obligation", lambda: api.get_obligation(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_OBLIGATION_NOT_FOUND),
        ("survey", lambda: api.get_survey(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_SURVEY_NOT_FOUND),
        ("valuation", lambda: api.get_carbon_valuation(NON_EXISTENT_UUID, fh), ApiErrorId.ERR_VALUATION_NOT_FOUND),
    ]
    for name, fn, expected_err in cases:
        resp = fn()
        validate_error(resp, expected_err), f"{name} should yield {expected_err}"
