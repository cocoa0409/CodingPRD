"""Customer onboarding and machine registration: creation shape, required
fields, enum and uniqueness rules, 404s, and list pagination defaults."""

import test_helpers as fx
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    PM,
    ApiErrorId,
    create_customer_payload,
    create_machine_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_customer_creation_and_retrieval(api):
    """PRD §3.1: "A `PlatformAdmin` onboards a customer by creating a Customer record with a company `name`, a `credit_limit_cents` ceiling — the maximum approved quote total the customer may commit to, which must be at least zero — and an optional free-form `region` label."
    PRD §2.4: "Every resource in the system — Customer, Machine, Assessment, RebuildProject, Part, ProjectPartLine, ReverseEngineeringJob, DowntimeWindow, ShipmentStage, AcceptanceTest, TrainingRecord, WarrantyClaim, and TradeInOffer — carries a standard set of system-managed properties"
    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/customer_creation_and_retrieval
    """
    res = api.create_customer(
        create_customer_payload(name="Acme Corp", credit_limit_cents=500_000_000), ADMIN
    )
    assert res.json()["response_type"] == "object"
    customer = validate_success(res, 201)
    fx.assert_customer(customer)
    assert is_valid_uuid(customer["id"])

    got = validate_success(api.get_customer(customer["id"], ADMIN), 200)
    assert got["name"] == "Acme Corp"
    assert got["credit_limit_cents"] == 500_000_000
    assert got["id"] == customer["id"]


def test_machine_creation_missing_required_serial_number_rejected(api):
    """PRD §3.1: "Registration records the owning `customer_id`, the OEM `serial_number` (unique across all machines; a duplicate submission is rejected with `ERR_INVALID_REQUEST`), the `machine_type` — one of `LATHE`, `MILL`, or `GRINDER` — the `year_of_manufacture` (a four-digit year between 1950 and 2026 inclusive, later feeding the age term of residual valuation), the as-found `control_generation` (`LEGACY` or `MODERN`), and the recorded `spindle_hours` (at least zero)."
    PRD §2.8: "Required fields are present, enum members are valid, and numeric ranges are respected — a `quantity` greater than zero, micron readings at least zero, exactly five acceptance samples; duplicate submissions of unique fields such as `serial_number` or `part_number` also fail here; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/machine_creation_missing_required_serial_number_rejected
    """
    customer = fx.create_customer()
    payload = create_machine_payload(customer["id"])
    del payload["serial_number"]
    res = api.create_machine(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_machine_creation_invalid_enum_rejected(api):
    """PRD §3.1: "the `machine_type` — one of `LATHE`, `MILL`, or `GRINDER`"
    PRD §2.8: "Required fields are present, enum members are valid, and numeric ranges are respected — a `quantity` greater than zero, micron readings at least zero, exactly five acceptance samples; duplicate submissions of unique fields such as `serial_number` or `part_number` also fail here; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/machine_creation_invalid_enum_rejected
    """
    customer = fx.create_customer()
    payload = create_machine_payload(customer["id"], machine_type="DRILL")
    res = api.create_machine(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_machine_duplicate_serial_number_rejected(api):
    """PRD §3.1: "Registration records the owning `customer_id`, the OEM `serial_number` (unique across all machines; a duplicate submission is rejected with `ERR_INVALID_REQUEST`), the `machine_type` — one of `LATHE`, `MILL`, or `GRINDER` — the `year_of_manufacture` (a four-digit year between 1950 and 2026 inclusive, later feeding the age term of residual valuation), the as-found `control_generation` (`LEGACY` or `MODERN`), and the recorded `spindle_hours` (at least zero)."

    Design: Corner/entities/machine_duplicate_serial_number_rejected
    """
    customer = fx.create_customer()
    first = create_machine_payload(customer["id"], serial_number="SN-DUP-1")
    validate_success(api.create_machine(first, ADMIN), 201)

    dupe = create_machine_payload(
        customer["id"], serial_number="SN-DUP-1", machine_type="MILL",
        year_of_manufacture=2020, control_generation="MODERN", spindle_hours=500,
    )
    res = api.create_machine(dupe, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_machine_get_nonexistent_returns_not_found(api):
    """PRD §2.8: "Path identifiers exist, validated left to right, and body-referenced identifiers (`part_id`, `window_id`, `offer_id`) exist; otherwise `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/machine_get_nonexistent_returns_not_found
    """
    res = api.get_machine(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_machines_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100."
    PRD §2.3: "The `offset` parameter states how many items to skip and defaults to 0."
    PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope."
    PRD §3.1: "Machines can be listed with an optional `customer_id` filter, alongside the standard `limit` and `offset` parameters."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/machines_list_pagination_defaults
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])

    res = api.list_machines(PM, params={"customer_id": customer["id"]})
    assert res.json()["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert data[0]["id"] == machine["id"]
