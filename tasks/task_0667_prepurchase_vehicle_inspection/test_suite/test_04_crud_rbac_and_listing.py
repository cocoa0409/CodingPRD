"""Resource creation defaults, type constraints, immutability, listing,
pagination, RBAC, and authentication.

Queue B (Corner): entities, errors, endpoints, rbac sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_fee_schedule, create_account, create_vehicle, create_inspector,
    create_draft_order, create_report_for, create_dispatched_order,
    offer_assignment, create_recall, add_photo,
    create_account_payload, create_order_payload,
    make_account_holder_headers, make_inspector_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]


# ===========================================================================
# Queue B — entities section
# ===========================================================================
def test_create_account_returns_201_with_defaults(api):
    """PRD §3.1: "A new account begins with `status` of `ACTIVE` and an
    `outstanding_balance_cents` of 0." "The optional `net_terms_days` defaults to
    0" and "An account also carries an optional `rush_discount_pct`, defaulting to
    0".

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    res = api.create_account(
        {"account_type": "INDIVIDUAL", "legal_name": "Solo Buyer", "email": "solo@x.test"}, OPS)
    acct = validate_success(res, 201)
    assert acct["status"] == "ACTIVE"
    assert acct["outstanding_balance_cents"] == 0
    assert acct["net_terms_days"] == 0
    assert acct["rush_discount_pct"] == 0


def test_get_inspection_order_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)
    before any business rule runs."

    Design: Corner/entities/get_inspection_order_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, OPS)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_order_missing_fee_schedule_id_rejected(api):
    """PRD §2.9: "request-body well-formedness - required fields present, enum
    members valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_order_missing_required_field
    """
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2020, make="Honda", model="Civic")
    res = api.create_order({
        "account_id": acct["id"], "vehicle_id": veh["id"],
        "location_lat": 34.0, "location_lng": -118.0, "rush_tier": "NONE",
    }, make_account_holder_headers(acct["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_order_defaults_rush_none_workflow_draft_payment_unpaid(api):
    """PRD §3.2: "an optional `rush_tier` (defaulting to `NONE`, otherwise
    `EXPRESS` or `SAME_DAY`)". "A new order starts with `workflow_status` of
    `DRAFT` and `payment_status` of `UNPAID`." PRD §2.4: "`version` is an integer
    that begins at 1".

    Design: Corner/entities/order_default_rush_tier_none_and_payment_unpaid
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2005, make="Honda", model="Civic")
    res = api.create_order({
        "account_id": acct["id"], "vehicle_id": veh["id"], "fee_schedule_id": fs["id"],
        "location_lat": 34.0, "location_lng": -118.0,
    }, make_account_holder_headers(acct["id"]))
    order = validate_success(res, 201)
    assert order["rush_tier"] == "NONE"
    assert order["workflow_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["version"] == 1


def test_order_estimated_fee_is_server_computed(api):
    """PRD §3.2: "the subtotal is the sum of three components: the base, which is
    the schedule's `base_fee_cents`; the VIN-history add-on ... and the dispatch
    charge ... (this dispatch charge is zero at creation, since miles are not yet
    known...)."

    Design: Corner/entities/order_estimated_fee_computed_input_ignored
    """
    fs = create_fee_schedule(tier_code="STANDARD", base_fee_cents=15000,
                             vin_history_fee_cents=3000, per_mile_dispatch_cents=100)
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2008, make="Subaru", model="Impreza")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    # STANDARD base 15000, no vin, no dispatch yet, NONE rush -> 15000
    assert order["estimated_fee_cents"] == 15000


def test_invalid_account_type_enum_rejected(api):
    """PRD §3.1: "An account is created with an `account_type` of `DEALER`,
    `AUCTION`, or `INDIVIDUAL`".

    Design: Corner/entities/invalid_account_type_enum_rejected
    """
    res = api.create_account(
        {"account_type": "GOVERNMENT", "legal_name": "Bad", "email": "bad@x.test"}, OPS)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_report_points_failed_exceeds_total_rejected(api):
    """PRD §3.5: "the `points_failed` count of checkpoints that failed (which must
    be between 0 and `points_total` inclusive, a malformed request otherwise)".

    Design: Corner/entities/report_points_failed_exceeds_total_rejected
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2015, make="Jeep", model="GrandCherokee")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)

    res = api.create_report({
        "order_id": order["id"], "assignment_id": asg["id"],
        "odometer_reading": 30000, "points_total": 10, "points_failed": 12, "road_test_done": True,
    }, make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_vehicle_has_no_version_field(api):
    """PRD §2.4: "Three entities are immutable lightweight records and therefore
    carry only `id` and `created_at`, with no `updated_at` and no `version` field
    at all: `Vehicle`, `ReportPhoto`, and `VinHistoryRecord`. The implementer
    must not emit `updated_at` or `version` on these three."

    Design: Corner/entities/vehicle_immutable_no_version_field
    """
    res = api.create_vehicle(
        {"vin": "5FNYF18568B011111", "year": 2008, "make": "Honda", "model": "Pilot"}, OPS)
    veh = validate_success(res, 201)
    assert "version" not in veh
    assert "updated_at" not in veh
    assert "created_at" in veh


def test_list_orders_for_account_with_pagination_meta(api):
    """PRD §2.3: "The `meta` object of a list response includes `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_orders_for_account_filtered_list_fk
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL")
    veh1 = create_vehicle(year=1994, make="Chevy", model="Cavalier")
    veh2 = create_vehicle(year=1994, make="Chevy", model="Cavalier")
    create_draft_order(acct, veh1, fs, rush_tier="NONE")
    create_draft_order(acct, veh2, fs, rush_tier="NONE")

    data, meta = validate_paginated(
        api.list_account_orders(acct["id"], make_account_holder_headers(acct["id"])))
    assert meta["total_count"] == 2
    assert len(data) == 2
    assert meta["has_more"] is False


# ===========================================================================
# Queue B — errors section
# ===========================================================================
def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100." "A `limit` or
    `offset` outside its allowed bounds is rejected with `ERR_PAGINATION_INVALID`
    (HTTP 422)."

    Design: Corner/errors/pagination_limit_out_of_bounds
    """
    res = api.list_recalls(OPS, params={"limit": 500})
    validate_error(res, "ERR_PAGINATION_INVALID")


# ===========================================================================
# Queue B — endpoints section
# ===========================================================================
def test_recall_lookup_filtered_by_year_make_model(api):
    """PRD §3.6: "Recall lookup lists records filtered by `year`, `make`, and
    `model`."

    Design: Corner/endpoints/recall_lookup_filtered_list
    """
    create_recall(2018, "Toyota", "Corolla", campaign_id="RC-M", severity="HIGH")
    create_recall(2019, "Honda", "Civic", campaign_id="RC-N", severity="LOW")

    data, meta = validate_paginated(
        api.list_recalls(OPS, params={"year": 2018, "make": "Toyota", "model": "Corolla"}))
    assert len(data) == 1
    assert data[0]["campaign_id"] == "RC-M"


def test_list_report_photos_by_report_id(api):
    """PRD §2.8: "List endpoints support reverse lookup by foreign key: ...
    photos by `report_id`".

    Design: Corner/endpoints/list_report_photos_reverse_reachability
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2012, make="Cadillac", model="CTS")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, points_total=100, points_failed=5, road_test_done=True)
    add_photo(report, insp["id"], caption="front", is_critical=False, url="http://x/a.jpg")
    add_photo(report, insp["id"], caption="rust", is_critical=True, url="http://x/b.jpg")

    data, meta = validate_paginated(
        api.list_report_photos(make_inspector_headers(insp["id"]), params={"report_id": report["id"]}))
    assert len(data) == 2


# ===========================================================================
# Queue B — rbac section
# ===========================================================================
def test_inspector_cannot_create_order(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." (POST /inspection-orders is AccountHolder.)

    Design: Corner/rbac/inspector_cannot_create_order
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2017, make="Chevy", model="Malibu")
    insp = create_inspector(certified_tiers=["STANDARD"])

    res = api.create_order(
        create_order_payload(acct["id"], veh["id"], fs["id"], rush_tier="NONE"),
        make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_account_holder_cannot_resolve_dispute(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." (Resolving a dispute is an OpsAdmin op.)

    Design: Corner/rbac/accountholder_cannot_resolve_dispute
    """
    from test_helpers import setup_delivered_order, setup_dispute
    ctx = setup_delivered_order(
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        pay=True,
    )
    dispute = setup_dispute("MISSED_DEFECT", 5000, ctx["account"]["id"],
                            ctx["delivered_order"], ctx["report"], start_review=True)

    res = api.resolve_dispute(dispute["id"], make_account_holder_headers(ctx["account"]["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_user_id_header_unauthenticated(api):
    """PRD §2.1: "Every request must carry two authentication headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring
    the role under which the request is made. If either header is missing, ...
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_user_id_header
    """
    headers = {"X-User-Role": "OpsAdmin", "Content-Type": "application/json"}
    res = api.create_account(
        {"account_type": "INDIVIDUAL", "legal_name": "No Auth", "email": "na@x.test"}, headers)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_inspector_cannot_accept_peer_assignment(api):
    """PRD §2.1: "An `Inspector` may only accept or decline assignments offered to
    itself". "Ownership violations - for example, ... an `Inspector` accepting a
    peer's offered assignment - are rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/non_owner_inspector_cannot_accept_others_assignment
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL")
    veh = create_vehicle(year=2017, make="Chevy", model="Malibu")
    insp_a = create_inspector(certified_tiers=["STANDARD"], full_name="Insp A")
    insp_b = create_inspector(certified_tiers=["STANDARD"], full_name="Insp B")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg = offer_assignment(order, insp_a)

    res = api.accept_assignment(asg["id"], make_inspector_headers(insp_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")
