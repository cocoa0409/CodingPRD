"""Casualty intake: creation defaults, schema validation, list pagination."""
from test_helpers import (
    ApiErrorId,
    assert_casualty,
    create_casualty_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    report_casualty,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_casualty_creation_defaults_and_system_fields(api, salvage_master_headers):
    """PRD 3.1: "A new casualty opens with `lifecycle_status` set to `REPORTED`
    and `env_posture` set to `ENV_CLEAR`."
    PRD 2.5: "The `id` is a server-minted UUID with no type prefix. The
    `created_at` timestamp records creation as an ISO 8601 UTC value with three
    fractional digits. The `updated_at` timestamp refreshes on every mutation of
    the resource, including system-driven mutations caused by cascades."

    Design: Corner/entities/casualty_creation_defaults_and_system_fields
    """
    res = api.create_casualty(
        create_casualty_payload(
            vessel_name="MV Tern",
            casualty_type="GROUNDING",
            declared_salved_value_cents=100_000_000,
            position="40N 10W",
        ),
        salvage_master_headers,
    )
    casualty = validate_success(res, 201)
    assert_casualty(casualty)
    assert casualty["lifecycle_status"] == "REPORTED"
    assert casualty["env_posture"] == "ENV_CLEAR"
    assert casualty["version"] == 1, "version starts at 1 on creation"
    assert is_valid_uuid(casualty["id"])
    assert is_iso8601_timestamp(casualty["created_at"])
    assert is_iso8601_timestamp(casualty["updated_at"])


def test_casualty_missing_required_field_rejected(api, salvage_master_headers):
    """PRD 2.7: "First, at priority 0, request schema validation: all required
    fields present, enum values valid, numeric amounts and quantities positive
    where required ... Any failure here yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/casualty_missing_required_field_rejected
    """
    payload = {
        "vessel_name": "MV Tern",
        "casualty_type": "GROUNDING",
        "position": "40N 10W",
    }
    res = api.create_casualty(payload, salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_casualty_invalid_enum_rejected(api, salvage_master_headers):
    """PRD 3.1: "the `casualty_type` — one of `GROUNDING`, `COLLISION`, `FIRE`,
    or `SUNK`"
    PRD 2.7: "First, at priority 0, request schema validation: all required
    fields present, enum values valid ... Any failure here yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/casualty_invalid_enum_rejected
    """
    payload = create_casualty_payload(casualty_type="ORBITAL")
    res = api.create_casualty(payload, salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_casualties_list_pagination_defaults(
    api, salvage_master_headers, contracts_officer_headers
):
    """PRD 2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum
    of 100. The `offset` parameter sets the number of items skipped and defaults
    to 0. Every list response sorts its resources by creation timestamp
    (`created_at`) in ascending order, and every list response includes the
    fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object
    of the envelope."

    Design: Corner/entities/casualties_list_pagination_defaults
    """
    get_success_data(
        api.create_casualty(
            create_casualty_payload(
                vessel_name="MV Tern",
                casualty_type="GROUNDING",
                declared_salved_value_cents=100_000_000,
                position="40N 10W",
            ),
            salvage_master_headers,
        )
    )
    data, meta = validate_paginated(api.list_casualties(contracts_officer_headers))
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0, "default offset is 0"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
    assert_casualty(data[0])
