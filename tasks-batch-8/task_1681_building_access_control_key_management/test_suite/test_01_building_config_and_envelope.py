"""Building configuration defaults, response envelope, pagination, run-ops summary,
and baseline auth/existence behavior."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_building,
    create_building,
    create_person,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]
DESK = TEST_USERS["front_desk_headers"]


def test_building_create_applies_config_defaults(api):
    """PRD §3.1: "Every omitted field takes a default: `audit_retention_days`
    defaults to 90 (the days an access event stays unarchived before run-ops
    archives it), `alert_escalation_minutes` defaults to 30 (how long a
    propped-door alert may sit unacknowledged before escalation),
    `vendor_badge_pool_max` defaults to 10 (the maximum number of concurrently
    live vendor temporary credentials building-wide),
    `default_propped_threshold_seconds` defaults to 120, `base_fee_cents`
    defaults to 15000, `per_door_fee_cents` to 7500, `per_key_reissue_fee_cents`
    to 2500, and `emergency_surcharge_pct` to 20 (the percent surcharge on the
    door portion when a rekey campaign finishes outside business hours)."
    PRD §3.1: "A building also carries `ops_run_index`, a system counter that
    starts at 0 and increments once per run-ops checkpoint."

    Design: Corner/entities/building_create_applies_config_defaults
    """
    building = create_building("Defaults Hall")
    data = validate_success(api.get_building(building["id"], ADMIN))
    assert_building(data)
    assert data["audit_retention_days"] == 90
    assert data["alert_escalation_minutes"] == 30
    assert data["vendor_badge_pool_max"] == 10
    assert data["default_propped_threshold_seconds"] == 120
    assert data["base_fee_cents"] == 15000
    assert data["per_door_fee_cents"] == 7500
    assert data["per_key_reissue_fee_cents"] == 2500
    assert data["emergency_surcharge_pct"] == 20
    assert data["business_open_utc"] == "08:00"
    assert data["business_close_utc"] == "18:00"
    assert data["ops_run_index"] == 0
    assert data["version"] == 1


def test_response_envelope_shape_for_success_and_error(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/response_envelope_shape_for_success_and_error
    """
    building = create_building("Envelope House")
    ok_resp = api.get_building(building["id"], ADMIN)
    ok_body = ok_resp.json()
    assert ok_resp.status_code == 200
    assert ok_body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in ok_body["meta"]
    assert ok_body["response_type"] == "object"
    assert ok_body["data"]["id"] == building["id"]

    err_resp = api.get_building(NON_EXISTENT_UUID, ADMIN)
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


def test_run_ops_summary_and_index_increment(api):
    """PRD §3.6: "The checkpoint response reports the new `ops_run_index` plus
    four counts: `vendor_credentials_expired`, `propped_alerts_created`,
    `alerts_escalated`, and `events_archived`."
    PRD §3.1: "A building also carries `ops_run_index`, a system counter that
    starts at 0 and increments once per run-ops checkpoint."

    Design: Corner/endpoints/run_ops_summary_and_index_increment
    """
    building = create_building("Ops House")
    first = validate_success(api.run_ops(building["id"], OFFICER))
    assert first["ops_run_index"] == 1
    assert first["vendor_credentials_expired"] == 0
    assert first["propped_alerts_created"] == 0
    assert first["alerts_escalated"] == 0
    assert first["events_archived"] == 0
    second = validate_success(api.run_ops(building["id"], OFFICER))
    assert second["ops_run_index"] == 2


def test_person_list_pagination_limit_offset(api):
    """PRD §2.3: "`limit` sets the maximum number of rows returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
    rows skipped and defaults to 0. The `meta` object of every list response
    includes `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "Every list endpoint returns rows ordered by `created_at`
    ascending, with the entity's per-building monotone minting counter `seq`
    ascending as the tie-break (for `RekeyCampaign` the campaign-scoped counter
    is named `rekey_seq`; `AccessEvent` uses its building-scoped `seq`)."

    Design: Corner/endpoints/person_list_pagination_limit_offset
    """
    building = create_building("Page House")
    for i in range(1, 13):
        create_person(building["id"], f"P-{i:02d}", "STAFF")

    page1, meta1 = validate_paginated(
        api.list_persons(DESK, params={"building_id": building["id"]})
    )
    assert len(page1) == 10, f"default limit 10 expected, got {len(page1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert page1[0]["full_name"] == "P-01"

    page2, meta2 = validate_paginated(
        api.list_persons(DESK, params={"building_id": building["id"], "limit": 10, "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
    assert page2[0]["full_name"] == "P-11"
    assert page2[1]["full_name"] == "P-12"


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request with a missing header, an unrecognized role, or —
    for entity-backed roles — an id that does not resolve to a persisted
    `Person` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/missing_auth_header_returns_unauthenticated
    """
    building = create_building("Auth House")
    resp = api.get_building(building["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_door_get_nonexistent_not_found(api):
    """PRD §2.9: "Existence of path identifiers and body-supplied foreign keys
    follows, validated left-to-right along the URL path (`ERR_NOT_FOUND`)."

    Design: Corner/entities/door_get_nonexistent_not_found
    """
    create_building("Ghost House")
    resp = api.get_door(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
