"""Corner-design sections: endpoints, rbac.

Endpoint-level claims (list filters, sub-resource scoping) and role-based
denials — each rooted in a single PRD sentence.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    award_quote_payload,
    create_carrier,
    create_qualified_carrier,
    create_quote,
    create_shipper,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_smartway_audit_payload
from test_helpers import make_shipper_headers


# ─── Endpoints section ────────────────────────────────────────────


def test_list_loads_filter_by_carrier_id_scopes_to_that_carrier(api):
    """PRD §4 (endpoint table): `GET /freight/loads | List loads; supports
    filtering by quote_request_id, carrier_id, status.`
    PRD §2.1: "When `X-User-Role` is `Carrier`, `X-User-ID` is the `id`
    of the acting `Carrier` row; carrier-facing list and detail endpoints
    filter by `carrier_id == X-User-ID`, and the pickup/deliver/factoring
    endpoints require the targeted `Load` or `Invoice` to belong to that
    same carrier."

    The list endpoint must honor a `carrier_id` filter so the caller only
    sees rows belonging to that carrier.

    Design: Corner/endpoints/list_loads_filter_by_carrier_id
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    carrier_a = create_qualified_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )
    carrier_b = create_qualified_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )

    # Award two different quotes, one to each carrier.
    quote1 = create_quote(
        shipper["id"], lane_origin="10001", lane_destination="30303",
        distance_miles=400,
        pickup_window_start_utc="2026-06-10T08:00:00Z",
        pickup_window_end_utc="2026-06-10T18:00:00Z",
        requested_equipment="DRY_VAN",
    )
    load1 = get_success_data(api.award_quote(
        quote1["id"], award_quote_payload(carrier_a["id"], quote1["version"]),
        TEST_USERS["broker_ops_headers"],
    ))
    quote2 = create_quote(
        shipper["id"], lane_origin="10001", lane_destination="30303",
        distance_miles=400,
        pickup_window_start_utc="2026-06-20T08:00:00Z",
        pickup_window_end_utc="2026-06-20T18:00:00Z",
        requested_equipment="DRY_VAN",
    )
    load2 = get_success_data(api.award_quote(
        quote2["id"], award_quote_payload(carrier_b["id"], quote2["version"]),
        TEST_USERS["broker_ops_headers"],
    ))

    res = api.list_loads(TEST_USERS["broker_ops_headers"],
                         params={"carrier_id": carrier_a["id"]})
    data, _meta = validate_paginated(res)
    returned_carrier_ids = {row["carrier_id"] for row in data}
    returned_ids = {row["id"] for row in data}
    assert returned_carrier_ids == {carrier_a["id"]}, (
        f"Filter must isolate carrier_a's loads; got carrier_ids={returned_carrier_ids}"
    )
    assert load1["id"] in returned_ids
    assert load2["id"] not in returned_ids


def test_shipper_subresource_smartway_audits(api):
    """PRD §4 (endpoint table): `GET /freight/shippers/{id}/smartway-audits |
    List SmartWay audits for a single shipper.`
    PRD §2.7: "A request to list a shipper's quarterly audits under
    `/shippers/{id}/smartway-audits` first verifies the shipper exists —
    if not, `ERR_RESOURCE_NOT_FOUND` is returned for the shipper
    specifically, before any audit row is consulted."

    The sub-resource form scopes to a single shipper's audits.

    Design: Corner/endpoints/shipper_subresource_smartway_audits
    """
    set_clock("2026-05-01T00:00:00Z")  # 2026Q1 is past.
    shipper = create_shipper(credit_limit_cents=1_000_000)
    get_success_data(api.create_smartway_audit(
        create_smartway_audit_payload(shipper["id"], "2026Q1"),
        TEST_USERS["broker_ops_headers"],
    ))
    res = api.list_shipper_smartway_audits(
        shipper["id"], TEST_USERS["broker_ops_headers"],
    )
    data, _meta = validate_paginated(res)
    assert len(data) >= 1
    for row in data:
        assert row["shipper_id"] == shipper["id"]


# ─── RBAC section ─────────────────────────────────────────────────


def test_shipper_cannot_qualify_carrier(api):
    """PRD §2.1: "If the header pair is present but the declared role is
    not permitted to invoke the targeted endpoint, the request is rejected
    with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 (endpoint table): `POST /freight/carriers/{id}/qualify | Approve
    carrier qualification (PENDING → QUALIFIED). | BrokerOps`

    The qualify endpoint is restricted to BrokerOps; a Shipper caller is
    rejected with ERR_UNAUTHORIZED.

    Design: Corner/rbac/shipper_cannot_qualify_carrier
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    carrier = create_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )
    shipper_headers = make_shipper_headers(shipper["id"])
    res = api.qualify_carrier(carrier["id"], shipper_headers)
    validate_error(res, "ERR_UNAUTHORIZED")

    after = get_success_data(api_client.get_carrier(
        carrier["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert after["qualification_status"] == "PENDING"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers. `X-User-ID`
    identifies the acting principal and `X-User-Role` declares the
    operational capacity in which the principal is acting. If either
    header is missing or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_returns_unauthenticated
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.list_shippers(TEST_USERS["anonymous_headers"])
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_award_with_stale_quote_version_rejected(api):
    """PRD §2.6: "If, at the moment the server processes the award, the
    `QuoteRequest`'s current `version` differs from
    `expected_quote_request_version` — for example because a sibling
    broker has already withdrawn the quote, or because the server has
    auto-expired it, or because a fresh quote on the same lane has
    legitimately superseded the client's view — the award is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and no `Load` is created."

    Design: Corner/rbac/occ_stale_version_on_award_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    carrier = create_qualified_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )
    quote = create_quote(
        shipper["id"], lane_origin="10001", lane_destination="30303",
        distance_miles=400,
        pickup_window_start_utc="2026-06-15T08:00:00Z",
        pickup_window_end_utc="2026-06-15T18:00:00Z",
        requested_equipment="DRY_VAN",
    )
    # Send a stale version (current minus 1) — server must reject with 412.
    res = api.award_quote(
        quote["id"],
        award_quote_payload(carrier["id"], quote["version"] - 1),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_STALE_VERSION")

    quote_after = get_success_data(api_client.get_quote_request(
        quote["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert quote_after["status"] == "OPEN"
