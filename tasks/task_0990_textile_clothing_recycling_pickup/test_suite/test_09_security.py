"""Authentication, role authorization, and entity-backed ownership checks."""
from test_helpers import (
    api_client, validate_error, validate_success, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_resident_headers, make_partner_manager_headers,
    make_sponsor_manager_headers, make_driver_headers,
    new_zone, new_resident, new_partner, new_fund, new_delivered_kit, new_pickup,
    route_pickup, collect_pickup, certify_ticket, run_selector, read_fund,
    ctx_collected, ctx_certified,
    create_pickup_payload, mark_collected_payload, certify_ticket_payload,
    topup_payload,
)

OP = TEST_USERS["zone_operator_headers"]
SENSOR = TEST_USERS["sensor_gateway_headers"]


def test_create_zone_missing_auth_headers(api):
    """PRD §2.1: "Every call to the API is authenticated by a pair of HTTP
    headers. The caller must supply `X-User-ID` to identify themselves and
    `X-User-Role` to declare their operational capacity. If either header is
    missing, or if `X-User-Role` is not one of the declared roles, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/create_zone_missing_auth_headers
    """
    resp = api_client.create_zone({"name": "Zone ER1"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_resident_cannot_read_other_resident_record(api):
    """PRD §2.1: "Four roles are entity-backed. When `X-User-Role` is `Resident`,
    `X-User-ID` is the `id` of the acting `Resident`; ownership checks compare a
    resource's `resident_id` foreign key (and, on pickup creation, the body's
    `resident_id`) to the supplied `X-User-ID`."
    PRD §2.1: "A second check then evaluates whether the declared role is on the
    endpoint's authorized list and whether the caller's entity binding matches the
    resource being acted on; failure here is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/errors/resident_cannot_read_other_resident_record
    """
    zone = new_zone("Zone ER3")
    ra = new_resident(zone["id"], "Val V", "val@x.com")
    rb = new_resident(zone["id"], "Wyn W", "wyn@x.com")

    resp = api_client.get_resident(ra["id"], make_resident_headers(rb["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_resident_cannot_certify_ticket(api):
    """PRD §2.1: "A second check then evaluates whether the declared role is on
    the endpoint's authorized list and whether the caller's entity binding matches
    the resource being acted on; failure here is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    Design: Corner/errors/resident_cannot_certify_ticket
    """
    ctx = ctx_collected(zone_name="Zone ER2", resident_name="Ute U", resident_email="ute@x.com")

    resp = api_client.certify_ticket(
        ctx["ticket"]["id"], certify_ticket_payload(certified_weight_kg=12.5, grade="RESALE"),
        make_resident_headers(ctx["resident"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    ticket = get_success_data(api_client.get_weight_ticket(ctx["ticket"]["id"], OP))
    assert ticket["status"] == "PROVISIONAL", "rejected certify must not mutate the ticket"


def test_partner_manager_cannot_accept_other_partners_assignment(api):
    """PRD §2.1: "When `X-User-Role` is `PartnerManager`, `X-User-ID` is the `id`
    of the acting `Partner`; an assignment's `partner_id` must equal it."

    Design: Corner/errors/partner_manager_cannot_accept_other_partners_assignment
    """
    p1 = new_partner("First Thrift", "THRIFT", ["RESALE"], 1000)
    p2 = new_partner("Second Thrift", "THRIFT", ["RESALE"], 1000)
    ctx = ctx_certified(zone_name="Zone ER4", resident_name="Xio X", resident_email="xio@x.com",
                        certified_weight_kg=12.5, grade="RESALE")
    a = run_selector(ctx["ticket"]["id"])
    assert a["partner_id"] == p1["id"], "setup sanity: earliest-created partner wins the tie"

    resp = api_client.accept_routing_assignment(a["id"], make_partner_manager_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    assignments, _ = validate_paginated(
        api_client.list_ticket_routing_assignments(ctx["ticket"]["id"], OP)
    )
    assert assignments[0]["status"] == "PENDING", "rejected accept must not mutate the assignment"


def test_sensor_gateway_cannot_create_pickup(api):
    """PRD §2.11: "The order is: (1) authentication of the headers, (2) role
    authorization and entity-backed ownership, (3) request well-formedness
    (required fields present, no undeclared fields, types and enum membership and
    numeric ranges valid)"
    PRD §2.1: "The system recognizes eight roles, spelled exactly as follows:
    `ZoneOperator`, `Resident`, `Driver`, `PartnerManager`, `Inspector`,
    `SponsorManager`, `CharityAdmin`, `SensorGateway`. No role is a superset of
    another; each owns a distinct slice of the resource graph."

    Design: Corner/rbac/sensor_gateway_cannot_create_pickup
    """
    zone = new_zone("Zone RB1")
    resident = new_resident(zone["id"], "Yus Y", "yus@x.com")

    resp = api_client.create_pickup_request({}, SENSOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_sponsor_manager_cannot_topup_other_fund(api):
    """PRD §2.1: "When `X-User-Role` is `SponsorManager`, `X-User-ID` is the `id`
    of the acting `SponsorFund`."

    Design: Corner/rbac/sponsor_manager_cannot_topup_other_fund
    """
    z1 = new_zone("Zone RB2a")
    z2 = new_zone("Zone RB2b")
    f1 = new_fund(z1["id"], 10000)
    f2 = new_fund(z2["id"], 20000, "GreenThread")

    resp = api_client.topup_fund(f2["id"], topup_payload(1000), make_sponsor_manager_headers(f1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert read_fund(f2["id"])["funded_total_cents"] == 20000, "rejected top-up must not mutate the fund"


def test_driver_cannot_collect_unassigned_pickup(api):
    """PRD §2.1: "There is one exception on the `Driver` role: for an
    already-routed pickup the assigned driver's id is significant, and
    mark-collected or mark-no-show require `X-User-ID` to equal the pickup's
    stored `driver_id`"

    Design: Corner/rbac/driver_cannot_collect_unassigned_pickup
    """
    zone = new_zone("Zone RB3")
    resident = new_resident(zone["id"], "Zoe Z", "zoe@x.com")
    new_delivered_kit(resident["id"], "BAG")
    pickup = new_pickup(resident["id"], bags_claimed=3)
    route_pickup(pickup["id"], "drv-1", "2026-05-10")

    resp = api_client.mark_collected(
        pickup["id"], mark_collected_payload(provisional_weight_kg=9.0),
        make_driver_headers("drv-2"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    pickup = get_success_data(api_client.get_pickup_request(pickup["id"], OP))
    assert pickup["status"] == "ROUTED", "rejected collection must not mutate the pickup"
    tickets, _ = validate_paginated(api_client.list_pickup_weight_tickets(pickup["id"], OP))
    assert tickets == [], "no ticket may be created by the rejected collection"
