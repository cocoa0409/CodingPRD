"""Employee and PerDiemRate creation, retrieval, and shape.

Covers PRD §3.12 (admin-only employees & rate rows), §2.4 (append-only
PerDiemRate and Receipt), and validation rules around manager_id.
"""
from __future__ import annotations

import uuid

import pytest

from test_helpers import (
    admin_headers as default_admin_headers,
    assert_append_only_fields,
    assert_employee,
    assert_per_diem_rate,
    create_employee_payload,
    create_per_diem_rate_payload,
    seed_default_boston_rate,
    seed_manager,
    validate_error,
    validate_success,
)


def test_create_employee_traveler_returns_traveler_shape(api, admin_headers):
    """PRD §3.12: "Employees are created by an `ADMIN` operator who
    supplies `full_name`, `email` ... `role` ... an optional `manager_id`
    (required for `TRAVELER`, must be null for `ADMIN`), `cost_center`,
    and `home_address_state`."
    """
    manager = seed_manager()
    payload = create_employee_payload(
        role="TRAVELER", manager_id=manager["id"],
    )
    res = api.create_employee(payload, admin_headers)
    body = validate_success(res, 201)
    assert_employee(body)
    assert body["role"] == "TRAVELER"
    assert body["manager_id"] == manager["id"]


def test_create_traveler_without_manager_id_is_rejected(api, admin_headers):
    """PRD §3.12: "an optional `manager_id` (required for `TRAVELER`,
    must be null for `ADMIN`)".

    A TRAVELER without manager_id is not faithful to PRD; the request
    must be rejected. The specific error_id is not pinned by PRD prose,
    so only a 4xx outcome is asserted.
    """
    payload = create_employee_payload(role="TRAVELER")
    # Force the field to be absent — the helper otherwise inserts None.
    payload.pop("manager_id", None)
    res = api.create_employee(payload, admin_headers)
    assert 400 <= res.status_code < 500, res.text


def test_create_admin_with_manager_id_is_rejected(api, admin_headers):
    """PRD §3.12: "must be null for `ADMIN`"."""
    payload = create_employee_payload(role="ADMIN", manager_id=str(uuid.uuid4()))
    # The helper would set manager_id to None for ADMIN — override with a value.
    payload["manager_id"] = str(uuid.uuid4())
    res = api.create_employee(payload, admin_headers)
    assert 400 <= res.status_code < 500, res.text


def test_employee_email_globally_unique_case_insensitive(api, admin_headers):
    """PRD §3.12: "`email` (globally unique, compared case-insensitively)"."""
    email = f"caseuser-{uuid.uuid4().hex[:6]}@example.com"
    res1 = api.create_employee(
        create_employee_payload(role="MANAGER", email=email),
        admin_headers,
    )
    validate_success(res1, 201)
    res2 = api.create_employee(
        create_employee_payload(role="MANAGER", email=email.upper()),
        admin_headers,
    )
    assert 400 <= res2.status_code < 500, res2.text


def test_create_per_diem_rate_returns_append_only_shape(api, admin_headers):
    """PRD §3.12: "Per-diem rate rows do not carry `updated_at` or
    `version` — they carry only `id` and `created_at`".
    """
    payload = create_per_diem_rate_payload(
        city=f"City-{uuid.uuid4().hex[:6]}",
    )
    res = api.create_per_diem_rate(payload, admin_headers)
    rate = validate_success(res, 201)
    assert_per_diem_rate(rate)
    assert_append_only_fields(rate)


def test_list_per_diem_rates_filterable_by_city(api, admin_headers):
    """PRD §4 list endpoint description: "List per-diem rates; filterable
    by `city`, `state`, `effective_on`"."""
    city_a = f"CityA-{uuid.uuid4().hex[:6]}"
    city_b = f"CityB-{uuid.uuid4().hex[:6]}"
    api.create_per_diem_rate(
        create_per_diem_rate_payload(city=city_a), admin_headers,
    )
    api.create_per_diem_rate(
        create_per_diem_rate_payload(city=city_b), admin_headers,
    )
    res = api.list_per_diem_rates(admin_headers, params={"city": city_a})
    body = res.json()
    assert res.status_code == 200, res.text
    assert "data" in body
    cities = {row["city"].lower() for row in body["data"]}
    assert city_a.lower() in cities
    assert city_b.lower() not in cities


def test_create_employee_requires_admin_role(api):
    """PRD §4 endpoint table: "POST /employees ... Authorized Role(s):
    ADMIN" + PRD §2.1 "an authenticated principal whose role is not on
    the endpoint's authorized list receives `ERR_INVALID_ROLE` as well."
    """
    from test_helpers import (
        make_finance_reviewer_headers, seed_finance_reviewer,
    )
    finance = seed_finance_reviewer()
    res = api.create_employee(
        create_employee_payload(role="MANAGER"),
        make_finance_reviewer_headers(finance["id"]),
    )
    validate_error(res, "ERR_INVALID_ROLE")
