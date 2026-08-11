"""Response envelope shape and list pagination."""
from test_helpers import (
    validate_paginated, get_success_data, is_iso8601_timestamp,
    ApiErrorId,
    create_device_model_payload, create_device_unit_payload,
    create_client,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def test_list_pagination_limit_offset_and_meta(api):
    """PRD §2.3: "`limit` caps the number of returned items; it defaults to 10,
    with a minimum of 1 and a maximum of 100. `offset` skips that many items from
    the front of the result set and defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/ep_list_pagination_defaults_and_params
    """
    m = get_success_data(api.create_device_model(create_device_model_payload(
        name="Magna 5x", category="MAGNIFIER", list_price_cents=25000), ADMIN))
    for sn in ("SN-PG1", "SN-PG2", "SN-PG3"):
        get_success_data(api.create_device_unit(create_device_unit_payload(
            m["id"], serial_no=sn, condition="NEW"), ADMIN))
    page1, meta1 = validate_paginated(api.list_device_units(
        ADMIN, params={"device_model_id": m["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    page2, meta2 = validate_paginated(api.list_device_units(
        ADMIN, params={"device_model_id": m["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_success_and_error_envelope_shapes(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/ep_response_envelope_shape
    """
    c = create_client(full_name="Envelope")
    import json
    ok = api.get_client(c["id"], INTAKE)
    body = json.loads(ok.content.decode())
    assert ok.status_code == 200
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == c["id"]

    err = api.get_client("123e4567-e89b-42d3-a456-426614174000", INTAKE)
    ebody = json.loads(err.content.decode())
    assert err.status_code == 404
    assert ebody["response_type"] == "error"
    assert ebody["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
    assert isinstance(ebody["data"]["message"], str) and ebody["data"]["message"]
