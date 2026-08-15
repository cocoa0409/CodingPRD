"""Entity creation defaults, not-found handling, pagination envelope, FK reads."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_customer,
    assert_equipment_item,
    assert_layout,
    create_customer_payload,
    create_equipment_item_payload,
    create_layout_payload,
    create_project_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
KD = TEST_USERS["kitchen_designer_headers"]


def test_customer_create_returns_defaults(api, platform_admin_headers):
    """PRD §3.1: "The new customer starts with `status` of `ACTIVE`, an
    `outstanding_exposure_cents` of 0, and the usual common fields."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/customer_create_returns_defaults
    """
    res = api.create_customer(
        create_customer_payload(
            legal_name="Default Cust",
            contact_email="d@x.test",
            credit_limit_cents=1_000_000,
        ),
        platform_admin_headers,
    )
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    assert customer["outstanding_exposure_cents"] == 0
    assert is_valid_uuid(customer["id"])
    assert "-" in customer["id"] and not customer["id"].startswith("cus_")


def test_project_create_retainage_pct_default(api):
    """PRD §3.1: "The PM may also set `retainage_pct`, the fraction of the
    eventual contract value withheld until punch-list closure; when omitted it
    defaults to 0.10, and in all cases it must be greater than 0 and at most
    0.20."

    Design: Corner/entities/project_create_retainage_pct_default
    """
    customer = get_success_data(api.create_customer(create_customer_payload(), ADMIN))

    p1 = validate_success(
        api.create_project(
            create_project_payload(customer["id"], project_name="NoPct"), PM
        ),
        201,
    )
    assert p1["retainage_pct"] == pytest.approx(0.10)

    p2 = validate_success(
        api.create_project(
            create_project_payload(
                customer["id"], project_name="WithPct", retainage_pct=0.15
            ),
            PM,
        ),
        201,
    )
    assert p2["retainage_pct"] == pytest.approx(0.15)


def test_project_get_not_found(api, project_manager_headers):
    """PRD §2.7: "A failure at any segment returns the not-found error for that
    segment's resource type" and lists `ERR_PROJECT_NOT_FOUND` among those
    resource errors, "each with HTTP 404."

    Design: Corner/entities/project_get_not_found
    """
    res = api.get_project(NON_EXISTENT_UUID, project_manager_headers)
    validate_error(res, "ERR_PROJECT_NOT_FOUND", expected_status=404)


def test_customer_list_pagination_envelope(api, platform_admin_headers):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`,
    and `has_more` inside `meta`." and "`limit` defaults to 10".

    Design: Corner/entities/customer_list_pagination_envelope
    """
    for i in range(3):
        get_success_data(
            api.create_customer(
                create_customer_payload(legal_name=f"C{i+1}"), platform_admin_headers
            )
        )

    data, meta = validate_paginated(api.list_customers(platform_admin_headers))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(data) == 3


def test_layout_hood_required_default_false(api):
    """PRD §3.2: "an optional `hood_required` flag declaring whether the design
    calls for a Type-I hood; the flag defaults to false."

    Design: Corner/entities/layout_hood_required_default_false
    """
    customer = get_success_data(api.create_customer(create_customer_payload(), ADMIN))
    project = get_success_data(
        api.create_project(create_project_payload(customer["id"]), PM)
    )
    layout = validate_success(
        api.create_layout(
            project["id"],
            create_layout_payload(layout_label="Rev-A", drawing_ref="DWG-HD"),
            KD,
        ),
        201,
    )
    assert_layout(layout)
    assert layout["hood_required"] is False


def test_fk_equipment_item_layout_id_reverse_reachable(api):
    """PRD §3.2: "each row carries both its parent `layout_id` and a
    denormalized `project_id` so the project-wide filtered list can answer
    \"all fryers across all revisions\" without walking layouts."

    Design: Corner/entities/fk_equipment_item_layout_id_reverse_reachable
    """
    customer = get_success_data(api.create_customer(create_customer_payload(), ADMIN))
    project = get_success_data(
        api.create_project(create_project_payload(customer["id"]), PM)
    )
    layout = get_success_data(
        api.create_layout(project["id"], create_layout_payload(), KD)
    )
    get_success_data(
        api.create_equipment_item(
            project["id"],
            layout["id"],
            create_equipment_item_payload(
                model_no="A", quantity=1, unit_price_cents=100, lead_time_days=1
            ),
            KD,
        )
    )
    get_success_data(
        api.create_equipment_item(
            project["id"],
            layout["id"],
            create_equipment_item_payload(
                model_no="B", quantity=1, unit_price_cents=200, lead_time_days=1
            ),
            KD,
        )
    )

    data, meta = validate_paginated(
        api.list_equipment_items_on_layout(project["id"], layout["id"], KD)
    )
    assert meta["total_count"] == 2
    for item in data:
        assert_equipment_item(item)
        assert item["layout_id"] == layout["id"]
        assert item["project_id"] == project["id"]
