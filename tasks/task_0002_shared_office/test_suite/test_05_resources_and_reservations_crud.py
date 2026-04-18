"""Resource and Reservation CRUD tests.

Covers PRD §3.2 (resource registration) and §3.3 (reservation creation into
PENDING).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_reservation,
    assert_resource,
    create_member,
    create_reservation_payload,
    create_resource,
    create_resource_payload,
    create_tenant,
    make_tenant_member_headers,
    setup_tenant_member_badge,
    validate_error,
    validate_success,
)


def test_create_workstation_resource(api, admin_headers):
    """PRD §3.2: "A `PlatformAdmin` registers each bookable space as a `Resource`.
    Every resource carries a `kind` enumeration of `WORKSTATION`, `MEETING_ROOM`, or
    `EVENT_AREA`, a short `code` that must be unique across all resources (for
    example, `WS-12`, `MR-3`, `EVT-A`), a `capacity` that is at least 1, and three
    per-`kind` rate fields — `hourly_rate_cents`, `daily_rate_cents`, and
    `block_rate_cents` — each of which defaults to 0 when the `kind` in question
    does not use it."

    Claim: POST /resources with kind=WORKSTATION returns a resource in status
    AVAILABLE and carries the specified code.
    """
    res = api.create_resource(
        create_resource_payload(kind="WORKSTATION", code="WS-T1"), admin_headers
    )
    resource = validate_success(res, expected_status=201)
    assert_resource(resource)
    assert resource["kind"] == "WORKSTATION"
    assert resource["code"] == "WS-T1"
    assert resource["status"] == "AVAILABLE"


def test_duplicate_resource_code_rejected(api, admin_headers):
    """PRD §3.2: "a short `code` that must be unique across all resources."

    Claim: a second resource with the same code must be rejected.
    """
    create_resource(kind="WORKSTATION", code="WS-UNIQUE-1")
    res = api.create_resource(
        create_resource_payload(kind="WORKSTATION", code="WS-UNIQUE-1"), admin_headers
    )
    assert res.status_code >= 400 and res.status_code < 500, (
        "Duplicate resource code must be rejected per PRD §3.2 uniqueness"
    )


def test_create_reservation_enters_pending(api, admin_headers):
    """PRD §3.3: "A reservation that passes all of these enters `PENDING`."

    Claim: successful POST /reservations → 201 with status=PENDING.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge(billing_plan="HOURLY")
    resource = create_resource(kind="WORKSTATION")
    advance_clock_to("2026-07-01T08:00:00.000Z")
    headers = make_tenant_member_headers(member["id"])
    payload = create_reservation_payload(
        tenant["id"], member["id"], resource["id"],
        "2026-07-01T09:00:00.000Z", "2026-07-01T10:00:00.000Z",
    )
    res = api.create_reservation(payload, headers)
    reservation = validate_success(res, expected_status=201)
    assert_reservation(reservation)
    assert reservation["status"] == "PENDING"
    assert reservation["tenant_id"] == tenant["id"]
    assert reservation["member_id"] == member["id"]
    assert reservation["resource_id"] == resource["id"]


def test_tenant_mismatch_when_member_belongs_to_other_tenant(api, admin_headers):
    """PRD §3.3: "The request is evaluated first for the cross-tenant referential
    rule: the `member_id` must belong to a `Member` whose `tenant_id` equals the
    `tenant_id` in the payload, otherwise `ERR_TENANT_MISMATCH` is returned."

    Claim: member_id's tenant != payload tenant_id → ERR_TENANT_MISMATCH (422).
    """
    tenant_a, _lease_a, member_a, _badge_a = setup_tenant_member_badge()
    tenant_b = create_tenant()
    resource = create_resource(kind="WORKSTATION")
    advance_clock_to("2026-07-01T08:00:00.000Z")
    headers = make_tenant_member_headers(member_a["id"])
    payload = create_reservation_payload(
        tenant_b["id"], member_a["id"], resource["id"],
        "2026-07-01T09:00:00.000Z", "2026-07-01T10:00:00.000Z",
    )
    res = api.create_reservation(payload, headers)
    validate_error(res, "ERR_TENANT_MISMATCH", expected_status=422)


def test_reservation_with_nonexistent_resource(api, admin_headers):
    """PRD §2.7: "Body-level foreign keys — `tenant_id`, `member_id`, `resource_id`,
    `host_member_id`, `bill_id` — are also resolved; if any one of them references
    a row that does not exist, the response is `ERR_REFERENCED_ENTITY_MISSING`."

    Claim: resource_id pointing to non-existent row → ERR_REFERENCED_ENTITY_MISSING.
    """
    tenant, _lease, member, _badge = setup_tenant_member_badge()
    advance_clock_to("2026-07-01T08:00:00.000Z")
    headers = make_tenant_member_headers(member["id"])
    payload = create_reservation_payload(
        tenant["id"], member["id"], "00000000-0000-4000-8000-000000000000",
        "2026-07-01T09:00:00.000Z", "2026-07-01T10:00:00.000Z",
    )
    res = api.create_reservation(payload, headers)
    validate_error(res, "ERR_REFERENCED_ENTITY_MISSING", expected_status=404)
