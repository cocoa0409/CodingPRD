"""Producer onboarding: creation defaults, listing pagination, lookup errors."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_producer,
    create_producer_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PC = TEST_USERS["plant_controller_headers"]


def test_producer_creation_returns_system_defaults(api):
    """PRD §3.1: "On creation the producer starts with `status` set to `ACTIVE`
    (the full lifecycle is `ACTIVE`, `SUSPENDED`, or `TERMINATED`), `quality_flag`
    set to `STANDARD`, `rolling_rejection_count_30d` at 0, and `version` at 1."

    Design: Corner/entities/producer_creation_returns_system_fields
    """
    set_clock()
    res = api.create_producer(
        create_producer_payload(
            producer_code="PX1", farm_name="Farm X1", base_hauling_rate_cents_per_cwt=150
        ),
        PC,
    )
    producer = validate_success(res, 201)
    assert_producer(producer)
    assert producer["version"] == 1, f"version must start at 1, got {producer['version']}"
    assert producer["quality_flag"] == "STANDARD"
    assert producer["rolling_rejection_count_30d"] == 0
    assert producer["status"] == "ACTIVE"
    assert producer["producer_code"] == "PX1"
    assert producer["farm_name"] == "Farm X1"
    assert producer["base_hauling_rate_cents_per_cwt"] == 150


def test_producer_list_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "List responses always populate `meta.limit`, `meta.offset`,
    `meta.total_count`, and `meta.has_more`." PRD §2.3: "`limit` defaults to 10,
    must be at least 1, and may not exceed 100. `offset` defaults to 0 and must
    be non-negative."

    Design: Corner/entities/producer_list_pagination
    """
    set_clock()
    for i in range(12):
        get_success_data(
            api.create_producer(
                create_producer_payload(producer_code=f"PL{i + 1}", farm_name=f"F{i + 1}"),
                PC,
            )
        )

    data, meta = validate_paginated(api.list_producers(PC, params={"limit": 10, "offset": 0}))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert len(data) == 10

    data2, meta2 = validate_paginated(api.list_producers(PC, params={"limit": 10, "offset": 10}))
    assert meta2["offset"] == 10
    assert len(data2) == 2
    assert meta2["has_more"] is False


def test_producer_not_found_returns_404(api):
    """PRD §2.5: "If any segment fails to resolve to an existing resource, the
    request is rejected with `ERR_NOT_FOUND` and no further segments are evaluated."

    Design: Corner/entities/producer_not_found_returns_404
    """
    set_clock()
    res = api.get_producer(NON_EXISTENT_UUID, PC)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_producer_code_required(api):
    """PRD §3.1: "A `PlantController` registers a new producer by submitting the
    producer's FMMO-issued `producer_code`, the display `farm_name`, and the
    negotiated `base_hauling_rate_cents_per_cwt`." PRD §2.10: "finally any
    field-shape or enum-violation check (→ `ERR_INVALID_INPUT`)."

    Design: Corner/entities/producer_code_required_field
    """
    set_clock()
    payload = create_producer_payload(farm_name="NoCode", base_hauling_rate_cents_per_cwt=100)
    del payload["producer_code"]
    res = api.create_producer(payload, PC)
    validate_error(res, ApiErrorId.ERR_INVALID_INPUT)
