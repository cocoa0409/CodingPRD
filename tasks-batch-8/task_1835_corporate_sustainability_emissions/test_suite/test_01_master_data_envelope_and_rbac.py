"""Master data creation defaults, response envelope, and top-level RBAC/auth."""
from test_helpers import (
    ANONYMOUS_HEADERS, ApiErrorId, NON_EXISTENT_UUID, assert_emission_target,
    assert_site, assert_supplier_engagement, create_emission_factor_payload,
    create_site_payload, create_target_payload, get_cycle, is_valid_uuid,
    make_collecting_cycle, make_cycle, make_engagement, validate_error,
    validate_success,
)


def test_site_creation_defaults_and_envelope(api, manager_headers):
    """PRD §3.1: "New sites enter `ACTIVE` status." PRD §2.2: "The
    `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`." and "The `response_type` is either \"object\"
    for a single resource or \"array\" for a list of resources." PRD §2.4:
    "The `version` is a system-managed integer that increments by exactly one
    on every mutation of the resource."

    Design: Corner/entities/site_creation_defaults_and_envelope
    """
    resp = api.create_site(
        create_site_payload(name="Alpha", country_code="US", grid_region_code="CA"),
        manager_headers,
    )
    assert resp.status_code == 201, f"create must return 201, got {resp.status_code}"
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    data = body["data"]
    assert_site(data)
    assert data["status"] == "ACTIVE", "new sites enter ACTIVE status"
    assert data["version"] == 1, "version is system-managed and starts at 1"

    fetched = validate_success(api.get_site(data["id"], manager_headers))
    assert fetched["name"] == "Alpha"
    assert fetched["country_code"] == "US"
    assert fetched["grid_region_code"] == "CA"


def test_site_create_ignores_client_supplied_system_fields(api, manager_headers):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
    `created_at` timestamp is ISO 8601 UTC with three fractional digits, fixed
    at creation. The `updated_at` timestamp follows the same format and
    refreshes on every modification. The `version` is a system-managed integer
    that increments by exactly one on every mutation of the resource."

    Design: Corner/entities/site_create_system_fields_input_ignored
    """
    resp = api.create_site(
        {
            "id": "client-chosen-id",
            "created_at": "1999-01-01T00:00:00Z",
            "version": 42,
            "name": "Beta",
            "country_code": "US",
            "grid_region_code": "TX",
        },
        manager_headers,
    )
    data = validate_success(resp, 201)
    assert_site(data)
    assert data["id"] != "client-chosen-id", "id is server-minted, not caller-set"
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1, "version is system-managed, not caller-set"
    assert data["created_at"] != "1999-01-01T00:00:00Z", (
        "created_at is fixed at creation by the server, not caller-set"
    )


def test_site_get_not_found_returns_404(api, manager_headers):
    """PRD §2.10: "Existence — every path identifier and every body-supplied
    foreign key (`cycle_id`, `site_id`, `factor_id`, `activity_record_id`,
    `supersedes_evidence_id`) resolves to an existing resource:
    `ERR_NOT_FOUND`."

    Design: Corner/entities/site_get_not_found_returns_404
    """
    resp = api.get_site(NON_EXISTENT_UUID, manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_site_create_missing_required_name_returns_invalid_request(api, manager_headers):
    """PRD §2.10: "Request shape — required fields present, types and enum
    members valid, `quantity` greater than zero, `spend_usd` not negative,
    datetimes in ISO 8601, and `reason` or `assurance_statement` non-empty
    where required: `ERR_INVALID_REQUEST`, on all write endpoints."

    Design: Corner/entities/site_create_missing_required_name_returns_invalid_request
    """
    resp = api.create_site(
        {"country_code": "US", "grid_region_code": "CA"}, manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_steward_cannot_create_emission_factor(api, steward_headers):
    """PRD §2.1: "When the role is valid but not permitted for the endpoint —
    or not permitted for the specific workflow step being attempted — the
    request is rejected with `ERR_UNAUTHORIZED`." PRD §4: POST
    `/sustainability/emission-factors` is authorized for
    SustainabilityManager only.

    Design: Corner/roles/steward_cannot_create_emission_factor
    """
    resp = api.create_emission_factor(create_emission_factor_payload(), steward_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_site_create_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside this list, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/roles/site_create_missing_auth_returns_unauthenticated
    """
    resp = api.create_site(
        create_site_payload(name="Gamma", grid_region_code="WA"), ANONYMOUS_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_engagement_creation_defaults_round_one(api, analyst_headers):
    """PRD §3.5: "The engagement starts `INVITED` at `round` 1, with
    `supplier_tco2e` and `responded_at` null until the first response."

    Design: Corner/entities/engagement_creation_defaults_round_one
    """
    cycle = make_collecting_cycle()
    engagement = make_engagement(cycle["id"], contact_user_id="supplier-1")
    assert_supplier_engagement(engagement)
    assert engagement["status"] == "INVITED"
    assert engagement["round"] == 1, "a new engagement starts at round 1"
    assert engagement.get("supplier_tco2e") is None
    assert engagement.get("responded_at") is None


def test_target_creation_defaults_provisional(api, manager_headers):
    """PRD §3.8: "New targets start in `DRAFT` with `baseline_source`
    `PROVISIONAL`, `trajectory_status` `NOT_EVALUATED`, and both
    `baseline_shift_pct` and `baseline_shift_significant` null."

    Design: Corner/entities/target_creation_defaults_provisional
    """
    resp = api.create_target(create_target_payload(), manager_headers)
    data = validate_success(resp, 201)
    assert_emission_target(data)
    assert data["status"] == "DRAFT"
    assert data["baseline_source"] == "PROVISIONAL"
    assert data["trajectory_status"] == "NOT_EVALUATED"
    assert data.get("baseline_shift_pct") is None
    assert data.get("baseline_shift_significant") is None


def test_cycle_transition_invalid_enum_returns_invalid_request(api, manager_headers):
    """PRD §2.10: "Request shape — required fields present, types and enum
    members valid, `quantity` greater than zero, `spend_usd` not negative,
    datetimes in ISO 8601, and `reason` or `assurance_statement` non-empty
    where required: `ERR_INVALID_REQUEST`, on all write endpoints."

    Design: Corner/entities/cycle_transition_invalid_enum_returns_invalid_request
    """
    cycle = make_cycle()
    resp = api.transition_cycle(cycle["id"], {"to_state": "EXPLODED"}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert get_cycle(cycle["id"])["status"] == "DRAFT", (
        "a rejected transition must not mutate the cycle"
    )
