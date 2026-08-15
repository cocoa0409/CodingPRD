"""Master-data and envelope claims: customers, sheet stock, audit, pagination."""
from test_helpers import (
    CLERK,
    MGR,
    ApiErrorId,
    assert_customer,
    create_customer,
    create_customer_payload,
    create_grade,
    create_sheet_stock_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_customer_creation_defaults(api):
    """PRD §3.1: "A new customer starts with `status` ACTIVE and a
    `scrap_credit_balance_cents` of zero."

    Design: Corner/entities/customer_creation_defaults_and_required_fields
    """
    resp = api.create_customer(
        create_customer_payload(company_name="Acme", email="a@x.com",
                                credit_limit_cents=500000),
        MGR,
    )
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["status"] == "ACTIVE"
    assert data["scrap_credit_balance_cents"] == 0
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def test_customer_create_missing_required_field_returns_400(api):
    """PRD §2.9: "whether the body is well-formed, meaning required fields
    present, types matching, and no unknown fields (`ERR_INVALID_REQUEST`,
    HTTP 400)."

    Design: Corner/entities/customer_create_missing_required_field_returns_400
    """
    resp = api.create_customer({"company_name": "NoCredit"}, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, _meta = validate_paginated(api.list_customers(MGR))
    assert all(r["company_name"] != "NoCredit" for r in rows), (
        "rejected create must not persist a Customer row"
    )


def test_sheet_stock_kind_system_assigned(api):
    """PRD §3.2: "The system classifies `kind` automatically: a sheet measuring
    exactly 1200 by 2400 millimeters is a FULL_SHEET, and anything else is
    recorded as a REMNANT — a usable offcut retained in inventory."

    Design: Corner/entities/sheet_stock_kind_system_assigned
    """
    grade = create_grade()

    full = validate_success(
        api.create_sheet_stock(create_sheet_stock_payload(grade["id"]), CLERK),
        201,
    )
    remnant = validate_success(
        api.create_sheet_stock(
            create_sheet_stock_payload(grade["id"], width_mm=600, height_mm=900),
            CLERK,
        ),
        201,
    )
    assert full["kind"] == "FULL_SHEET"
    assert remnant["kind"] == "REMNANT"
    assert full["status"] == "AVAILABLE"
    assert remnant["status"] == "AVAILABLE"


def test_entity_not_found_returns_404(api):
    """PRD §2.8: "the server resolves identifiers strictly left to right and
    rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does
    not exist, before examining later segments, the request body, or any
    business rule."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_customer("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_audit_event_immutable_no_version(api):
    """PRD §2.5: "An inspection report and an audit event each carry only `id`
    and `created_at`; both `updated_at` and `version` are absent from them,
    since neither resource is ever modified after creation."

    Design: Corner/entities/audit_event_immutable_no_version
    """
    create_customer(company_name="Aud", email="aud@x.com", credit_limit_cents=1000)

    rows, meta = validate_paginated(api.list_audit_events(MGR))
    assert meta["total_count"] >= 1, "a mutation must append an audit event"
    for row in rows:
        assert is_valid_uuid(row["id"])
        assert is_iso8601_timestamp(row["created_at"])
        assert "version" not in row, "audit events carry no version field"
        assert "updated_at" not in row, "audit events carry no updated_at field"
        assert row["entity_type"] and row["event_type"]
        assert row["actor_role"] and row["actor_id"]


def test_pagination_envelope_on_list(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the envelope's `meta` object."

    Design: Corner/entities/pagination_envelope_on_list
    """
    for i in range(12):
        create_customer(company_name=f"P{i + 1:02d}", email=f"p{i + 1:02d}@x.com",
                        credit_limit_cents=1000)

    page1, meta1 = validate_paginated(api.list_customers(MGR, params={"limit": 10, "offset": 0}))
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert len(page1) == 10

    page2, meta2 = validate_paginated(api.list_customers(MGR, params={"limit": 10, "offset": 10}))
    assert meta2["has_more"] is False
    assert len(page2) == 2

    default_rows, default_meta = validate_paginated(api.list_customers(MGR))
    assert default_meta["limit"] == 10, "default limit is 10 when omitted"
    assert len(default_rows) == 10
    assert default_meta["total_count"] == 12
