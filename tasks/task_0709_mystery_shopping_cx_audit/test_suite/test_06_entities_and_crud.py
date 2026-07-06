"""Entity creation, defaults, system-minted fields, validation of required fields
and enums, not-found resolution, the computed travel distance, and certification
attempt indexing.

Covers the corner entities section instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID, fixtures,
)
from test_helpers.test_users import (
    make_anonymous_headers,
    make_platform_admin_headers,
    make_qa_validator_headers,
    make_client_manager_headers,
)
from test_helpers import factories


# ---------------------------------------------------------------------------
# entities / create_shopper_minimal_required_fields_returns_201
# ---------------------------------------------------------------------------
def test_create_shopper_minimal_required_fields_returns_201(api):
    """PRD 3.1: "A newly registered shopper starts in REGISTERED status with a
    reliability_score of 100.0 and a certification_score of 0."

    Design: Corner/entities/create_shopper_minimal_required_fields_returns_201
    """
    payload = {"full_name": "Cor Shop", "email": "cor@x.test", "home_lat": 40.0, "home_lng": -74.0}
    data = validate_success(api.create_shopper(payload, make_anonymous_headers()), expected_status=201)
    assert data["status"] == "REGISTERED", f"expected REGISTERED, got {data['status']}"
    assert data["reliability_score"] == 100, f"expected 100, got {data['reliability_score']}"
    assert data["certification_score"] == 0, f"expected 0, got {data['certification_score']}"
    assert data["tax_id_on_file"] is False, f"expected tax_id_on_file false, got {data['tax_id_on_file']}"


# ---------------------------------------------------------------------------
# entities / create_shopper_missing_email_returns_invalid_request
# ---------------------------------------------------------------------------
def test_create_shopper_missing_email_returns_invalid_request(api):
    """PRD 3.1: "Shoppers also self-register publicly, providing their full_name
    (their legal name as the 1099 payee), a unique email, and a home position as
    home_lat and home_lng decimal-degree coordinates."
    PRD 5 error catalogue / 3 (generic malformed body): a missing required field is
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_shopper_missing_email_returns_invalid_request
    """
    payload = {"full_name": "No Email", "home_lat": 40.0, "home_lng": -74.0}
    resp = api.create_shopper(payload, make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# entities / get_shopper_nonexistent_returns_not_found
# ---------------------------------------------------------------------------
def test_get_shopper_nonexistent_returns_not_found(api):
    """PRD 2.4: "A request is rejected with ERR_NOT_FOUND for the first path segment
    whose identifier does not resolve to an existing resource, before any later
    segment or any body foreign key is examined."

    Design: Corner/entities/get_shopper_nonexistent_returns_not_found
    """
    resp = api.get_shopper(NON_EXISTENT_UUID, make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# entities / system_fields_minted_by_server_input_ignored
# ---------------------------------------------------------------------------
def test_registered_shopper_system_fields_minted_by_server(api):
    """PRD 3.1: "A newly registered shopper starts in REGISTERED status with a
    reliability_score of 100.0 and a certification_score of 0."

    The server forces these system-managed values; they are not client inputs.

    Design: Corner/entities/system_fields_minted_by_server_input_ignored
    """
    payload = {"full_name": "Ignore Me", "email": "ig@x.test", "home_lat": 40.0, "home_lng": -74.0}
    data = validate_success(api.create_shopper(payload, make_anonymous_headers()), expected_status=201)
    assert data["reliability_score"] == 100, f"expected 100, got {data['reliability_score']}"
    assert data["status"] == "REGISTERED", f"expected REGISTERED, got {data['status']}"


# ---------------------------------------------------------------------------
# entities / defaults_applied_tax_id_on_file_false
# ---------------------------------------------------------------------------
def test_tax_id_on_file_defaults_false_when_omitted(api):
    """PRD 3.1: "A shopper may optionally declare at registration whether a W-9 /
    TIN is already on file via tax_id_on_file; if omitted it is false."

    Design: Corner/entities/defaults_applied_tax_id_on_file_false
    """
    payload = {"full_name": "Def Shop", "email": "def@x.test", "home_lat": 40.0, "home_lng": -74.0}
    data = validate_success(api.create_shopper(payload, make_anonymous_headers()), expected_status=201)
    assert data["tax_id_on_file"] is False, f"expected tax_id_on_file false, got {data['tax_id_on_file']}"


# ---------------------------------------------------------------------------
# entities / location_invalid_scenario_family_enum_rejected
# ---------------------------------------------------------------------------
def test_location_invalid_scenario_family_enum_rejected(api):
    """PRD 3.3: "A Location is created under a client with a label, a site position
    given as lat and lng decimal degrees, and the scenario_family a shopper must be
    certified in to audit there -- RETAIL, DINING, or BANKING."
    PRD 5 / generic malformed body: an out-of-range enum is ERR_INVALID_REQUEST.

    Design: Corner/entities/location_invalid_scenario_family_enum_rejected
    """
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cm = make_client_manager_headers(client["id"])
    payload = {"label": "Bad", "lat": 40.0, "lng": -74.0, "scenario_family": "SPA"}
    resp = api.create_location(client["id"], payload, cm)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# entities / travel_distance_computed_input_ignored
# ---------------------------------------------------------------------------
def test_travel_distance_computed_via_haversine(api):
    """PRD 3.4: "This is the great-circle (haversine) distance from the shopper's
    home position to the location, using an Earth radius of 6371.0088 kilometers...
    The result is rounded half up to two decimal places and stored as
    travel_distance_km, where it pins all later mileage reimbursement."

    Design: Corner/entities/travel_distance_computed_input_ignored
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.5, loc_lng=-74.5,
        home_lat=40.0, home_lng=-74.0,
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    payload = factories.create_assignment_payload(
        cat["wave"]["id"], cat["shopper"]["id"], cat["location"]["id"],
        cat["script"]["id"], "2026-06-10T00:00:00Z",
    )
    asg = validate_success(api.create_assignment(payload, cm), expected_status=201)
    assert asg["travel_distance_km"] == 69.94, (
        f"travel_distance_km expected 69.94 (haversine 40.0/-74.0 -> 40.5/-74.5), "
        f"got {asg['travel_distance_km']}"
    )


# ---------------------------------------------------------------------------
# entities / certification_attempt_immutable_no_version_field
# ---------------------------------------------------------------------------
def test_first_certification_attempt_has_index_one_and_passed(api):
    """PRD 3.2: "Each attempt is stamped with the candidate's shopper_id and an
    attempt_index, the 1-based ordinal of this attempt among the shopper's attempts
    in that same scenario_family, ordered by creation time."
    PRD 3.2: "The attempt's outcome is computed: it is PASSED when the raw_score is
    at least 70, and FAILED otherwise."

    Design: Corner/entities/certification_attempt_immutable_no_version_field
    """
    shopper = fixtures.register_shopper(tax_id_on_file=False, home_lat=40.0, home_lng=-74.0)
    sid = shopper["id"]
    attempt = validate_success(
        api.create_certification_attempt(sid, {"raw_score": 90, "scenario_family": "RETAIL"},
                                         make_qa_validator_headers()),
        expected_status=201,
    )
    assert attempt["attempt_index"] == 1, f"first attempt index expected 1, got {attempt['attempt_index']}"
    assert attempt["outcome"] == "PASSED", f"outcome expected PASSED for 90, got {attempt['outcome']}"
    listed = validate_success(api.list_certification_attempts(sid, make_qa_validator_headers()))
    first = listed[0] if isinstance(listed, list) else listed
    assert first["attempt_index"] == 1
