"""Yacht listing lifecycle, availability calendar blocks, operator standing,
ownership RBAC, OCC on the calendar, and list pagination."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_availability_block,
    assert_yacht,
    create_availability_block_payload,
    create_broker_payload,
    create_listed_yacht,
    create_manual_block,
    create_operator,
    create_qualified_client,
    create_request,
    create_yacht,
    make_client_headers,
    make_operator_headers,
    setup_listed_marketplace,
    setup_marketplace,
    setup_submitted_request,
    submit_request,
    TEST_USERS,
    api_client,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_yacht_list_delist_relist_cycle_and_version(api):
    """PRD section 3.2: "Listing the yacht moves it from `DRAFT` to `LISTED`
    (and a previously `DELISTED` yacht may be listed again by the same path)."
    PRD section 3.2: "Both listing and delisting increment the yacht's
    `version` by one."

    Design: Corner/state_machines/yacht_list_delist_relist_cycle_and_version
    """
    ctx = setup_marketplace()
    assert ctx.yacht["status"] == "DRAFT"
    v0 = ctx.yacht["version"]

    listed = validate_success(api.list_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert listed["status"] == "LISTED"
    assert listed["version"] == v0 + 1, "listing increments the yacht version by one"

    delisted = validate_success(api.delist_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert delisted["status"] == "DELISTED"
    assert delisted["version"] == v0 + 2, "delisting increments the yacht version by one"

    relisted = validate_success(api.list_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert_yacht(relisted)
    assert relisted["status"] == "LISTED", "a DELISTED yacht may be listed again"
    assert relisted["version"] == v0 + 3


def test_delist_blocked_by_live_request(api):
    """PRD section 3.2: "Delisting moves `LISTED` to `DELISTED` and is
    deliberately asymmetric: it requires ownership but not operator good
    standing, and it is blocked with `ERR_INVALID_STATE` only while the yacht
    is referenced by a live deal — any charter request in `SUBMITTED`,
    `OFFERED`, or `COUNTERED` (a `DRAFT` request does not block), or any
    agreement in `PENDING_SIGNATURES`, `SIGNED`, `IN_PREP`, or `UNDERWAY`."

    Design: Corner/state_machines/delist_blocked_by_live_request
    """
    ctx = setup_submitted_request()  # request is SUBMITTED -> live deal
    res = api.delist_yacht(ctx.yacht["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    yacht = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert yacht["status"] == "LISTED", "a blocked delist must leave the yacht LISTED"


def test_manual_charter_block_creation_rejected(api):
    """PRD section 3.2: "Creating one takes a `block_type` of `MAINTENANCE` or
    `OPERATOR_HOLD` — the third block type, `CHARTER`, is reserved for the
    system and a manual creation naming it is rejected as
    `ERR_INVALID_REQUEST`"

    Design: Corner/state_machines/manual_charter_block_creation_rejected
    """
    ctx = setup_marketplace()
    res = api.create_availability_block(
        ctx.yacht["id"],
        create_availability_block_payload(ctx.yacht["version"],
                                          block_type="CHARTER"),
        ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_yacht_availability_blocks(ctx.yacht["id"], ctx.op_headers))
    assert meta["total_count"] == 0 and data == [], (
        "a rejected block creation must persist nothing")


def test_charter_block_release_rejected_manual_block_ok(api):
    """PRD section 3.2: "Releasing a manual block is the owning operator's
    call and moves the block from `ACTIVE` to `RELEASED`, again incrementing
    the yacht's `version`. A `CHARTER` block refuses manual release with
    `ERR_INVALID_STATE` — it is released only by the cancellation cascade of
    section 3.9, the same cascade that fills its `charter_agreement_id` at
    creation."

    Design: Corner/state_machines/charter_block_release_rejected_manual_block_ok
    """
    ctx = setup_marketplace()
    manual_block = create_manual_block(
        ctx.yacht["id"], ctx.operator["id"], ctx.yacht["version"],
        start_date="2026-09-01", end_date="2026-09-05")
    listed = validate_success(api.list_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    v_listed = listed["version"]

    # Drive a request to acceptance so a system CHARTER block exists.
    request = create_request(ctx.client["id"], ctx.yacht["id"])
    request = submit_request(request["id"], ctx.client["id"])
    from test_helpers import accept_request, make_offer
    offered = make_offer(request["id"], ctx.central_agent["id"])
    agreement = accept_request(request["id"], ctx.client["id"], offered["version"])

    blocks, meta = validate_paginated(
        api.list_agreement_availability_blocks(agreement["id"], ctx.op_headers))
    assert len(blocks) == 1 and blocks[0]["block_type"] == "CHARTER"
    charter_block = blocks[0]

    res = api.release_availability_block(charter_block["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    released = validate_success(
        api.release_availability_block(manual_block["id"], ctx.op_headers), 200)
    assert released["status"] == "RELEASED"

    yacht = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert yacht["version"] == v_listed + 2, (
        "the accept created a CHARTER block (+1) and the manual release "
        "bumped the calendar version once more (+1); the rejected release "
        "bumped nothing")


def test_yacht_get_not_found_returns_404(api):
    """PRD section 2.9: "Where an endpoint path nests one resource under
    another (for example a yacht's availability blocks or an agreement's
    expenses), identifiers in the path are validated strictly left to right:
    the first identifier that does not resolve to an existing resource rejects
    the request with `ERR_NOT_FOUND` (HTTP 404), and body-level foreign keys
    such as `yacht_id`, `client_id`, `listing_central_agent_id`, and
    `retail_broker_id` are likewise checked for existence before business
    rules run."

    Design: Corner/entities/yacht_get_not_found_returns_404
    """
    res = api.get_yacht(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    body = res.json()
    assert "api_request_id" in body["meta"], (
        "the error envelope's meta carries api_request_id")
    assert "api_request_timestamp" in body["meta"]
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


def test_yacht_enum_type_constraint_rejected(api, platform_admin_headers):
    """PRD section 3.2: "the `pricing_mode` (`PRO_RATA` or `WEEKLY_PLUS_DAILY`)
    that selects the quote variant"
    PRD section 2.11: "Field-level constraints — required fields present,
    types and enum members valid, dates well-formed and ordered, amounts
    positive, manual block types restricted (`ERR_INVALID_REQUEST`), plus
    capacity (`ERR_CAPACITY_EXCEEDED`), duration (`ERR_CHARTER_DURATION_INVALID`),
    duplicate requests (`ERR_DUPLICATE_ACTIVE_REQUEST`), negotiation rounds
    (`ERR_NEGOTIATION_ROUND_LIMIT`), gratuity minimums
    (`ERR_GRATUITY_BELOW_MINIMUM`), and insurance coverage and window checks
    (`ERR_INSURANCE_COVERAGE_INSUFFICIENT`, `ERR_INSURANCE_WINDOW_INVALID`)."

    Design: Corner/entities/yacht_enum_type_constraint_rejected
    """
    operator = create_operator()
    central_agent = validate_success(
        api.create_broker(create_broker_payload(), ADMIN), 201)

    res = api.create_yacht(
        {"name": "Yacht X", "charter_type": "BAREBOAT", "home_port": "Athens",
         "capacity_berths": 8, "weekly_base_rate_cents": 700000,
         "min_charter_days": 3, "required_resume_class": "COASTAL",
         "security_deposit_cents": 500000, "pricing_mode": "DAILY",
         "listing_central_agent_id": central_agent["id"]},
        make_operator_headers(operator["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_yachts(ADMIN, params={"operator_id": operator["id"]}))
    assert meta["total_count"] == 0 and data == [], (
        "DAILY is not a declared pricing_mode member; nothing may persist")


def test_operator_suspended_gates_writes(api):
    """PRD section 3.1: "Suspending an operator flips it to `SUSPENDED`, and
    while suspended the operator is barred from four activities: listing a
    yacht, creating an availability block, having a charter request submitted
    against one of its yachts, and having an offer issued on such a request —
    each rejected with `ERR_OPERATOR_SUSPENDED`."

    Design: Corner/validations/operator_suspended_gates_writes
    """
    ctx = setup_listed_marketplace()
    request = create_request(ctx.client["id"], ctx.yacht["id"])
    v_listed = ctx.yacht["version"]

    suspended = validate_success(
        api.suspend_operator(ctx.operator["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"

    res = api.create_availability_block(
        ctx.yacht["id"],
        create_availability_block_payload(v_listed,
                                          start_date="2026-09-01",
                                          end_date="2026-09-05"),
        ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_OPERATOR_SUSPENDED, expected_status=422)

    res = api.submit_charter_request(request["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_OPERATOR_SUSPENDED, expected_status=422)

    reactivated = validate_success(
        api.reactivate_operator(ctx.operator["id"], ADMIN), 200)
    assert reactivated["status"] == "ACTIVE"

    submitted = validate_success(
        api.submit_charter_request(request["id"], ctx.cl_headers), 200)
    assert submitted["status"] == "SUBMITTED", (
        "reactivation returns the operator to ACTIVE and restores writes")


def test_forbidden_operator_ownership_returns_403(api, platform_admin_headers):
    """PRD section 2.1: "A well-authenticated caller who attempts an operation
    not open to their role, or who violates an ownership rule — an operator
    touching another operator's yacht, a non-party acting on a request or
    agreement, an offer issued by a broker who is not the listing central
    agent — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/forbidden_operator_ownership_returns_403
    """
    operator1 = create_operator(name="Op One", home_port="Athens")
    operator2 = create_operator(name="Op Two", home_port="Piraeus")
    central_agent = validate_success(
        api.create_broker(create_broker_payload(), ADMIN), 201)
    yacht = create_yacht(operator1["id"], central_agent["id"])

    res = api.create_availability_block(
        yacht["id"],
        create_availability_block_payload(yacht["version"],
                                          start_date="2026-09-01",
                                          end_date="2026-09-05"),
        make_operator_headers(operator2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    after = validate_success(api.get_yacht(yacht["id"], ADMIN), 200)
    assert after["version"] == yacht["version"], (
        "a forbidden block creation must not mutate the yacht")
    blocks, meta = validate_paginated(
        api.list_yacht_availability_blocks(yacht["id"], ADMIN))
    assert meta["total_count"] == 0


def test_occ_block_create_stale_yacht(api):
    """PRD section 2.10: "Third, creating a manual availability block on a
    yacht requires `expected_yacht_version` in the request body, carrying the
    yacht `version` the operator last observed. A mismatch with the yacht's
    current `version` — for example because an accepted charter has meanwhile
    system-created a charter block on that calendar — is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the operator must re-read the calendar
    before adding the block."

    Design: Corner/cross_cutting_complexity_layers/occ_block_create_stale_yacht
    """
    ctx = setup_marketplace()
    stale_version = ctx.yacht["version"]
    listed = validate_success(api.list_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert listed["version"] != stale_version

    res = api.create_availability_block(
        ctx.yacht["id"],
        create_availability_block_payload(stale_version,
                                          start_date="2026-09-01",
                                          end_date="2026-09-05"),
        ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # Re-read the calendar and resubmit against the current version.
    current = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    created = validate_success(
        api.create_availability_block(
            ctx.yacht["id"],
            create_availability_block_payload(current["version"],
                                              start_date="2026-09-01",
                                              end_date="2026-09-05"),
            ctx.op_headers),
        201)
    assert_availability_block(created)
    assert created["status"] == "ACTIVE"

    after = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    assert after["version"] == current["version"] + 1, (
        "a created block increments the yacht's version by one")


def test_overlapping_block_rejected_availability_conflict(api):
    """PRD section 2.7: "A true half-open overlap — the requested interval and
    an `ACTIVE` block on the same yacht share at least one day — is rejected
    with `ERR_AVAILABILITY_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/yacht_block_overlap_vs_buffer_adjacency
    """
    ctx = setup_marketplace()
    block = create_manual_block(ctx.yacht["id"], ctx.operator["id"],
                                ctx.yacht["version"])  # [2026-09-10, 2026-09-20)
    current = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)

    # [2026-09-15, 2026-09-25) shares the days 09-15..09-19 with the block.
    res = api.create_availability_block(
        ctx.yacht["id"],
        create_availability_block_payload(current["version"],
                                          block_type="OPERATOR_HOLD",
                                          start_date="2026-09-15",
                                          end_date="2026-09-25"),
        ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_AVAILABILITY_CONFLICT, expected_status=409)

    blocks, meta = validate_paginated(
        api.list_yacht_availability_blocks(ctx.yacht["id"], ctx.op_headers))
    assert meta["total_count"] == 1, "the rejected overlap must not persist"


def test_zero_gap_adjacency_violates_buffer_one_day_gap_passes(api):
    """PRD section 2.7: "Even without overlap, the yard needs one full
    turnaround day between bookings: if the requested interval is disjoint
    from an `ACTIVE` block but abuts it with a gap of zero days — less than
    the one-day turnaround buffer — the request is rejected with
    `ERR_TURNAROUND_BUFFER_VIOLATION` (HTTP 409). A gap of one day or more
    passes the buffer check."

    Design: Difficulty/resource_temporal_overlap/yacht_block_overlap_vs_buffer_adjacency
    """
    ctx = setup_marketplace()
    block = create_manual_block(ctx.yacht["id"], ctx.operator["id"],
                                ctx.yacht["version"])  # [2026-09-10, 2026-09-20)
    current = validate_success(api.get_yacht(ctx.yacht["id"], ctx.op_headers), 200)

    # Starts exactly at the block's exclusive end: gap 0 < buffer 1.
    res = api.create_availability_block(
        ctx.yacht["id"],
        create_availability_block_payload(current["version"],
                                          block_type="OPERATOR_HOLD",
                                          start_date="2026-09-20",
                                          end_date="2026-09-25"),
        ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_TURNAROUND_BUFFER_VIOLATION,
                   expected_status=409)

    # Gap of exactly one day (09-20 free) satisfies the buffer.
    created = validate_success(
        api.create_availability_block(
            ctx.yacht["id"],
            create_availability_block_payload(current["version"],
                                              block_type="OPERATOR_HOLD",
                                              start_date="2026-09-21",
                                              end_date="2026-09-25"),
            ctx.op_headers),
        201)
    assert created["status"] == "ACTIVE"


def test_list_pagination_defaults_and_limit_cap(api, platform_admin_headers):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned; it defaults to 10 when omitted and accepts values from a minimum
    of 1 to a maximum of 100. The `offset` parameter specifies how many items
    to skip and defaults to 0."
    PRD section 2.3: "The `meta` object of a list response carries the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a
    client can always tell how much of the collection remains unread."

    Design: Corner/endpoints/list_pagination_defaults_and_limit_cap
    """
    operator = create_operator()
    central_agent = validate_success(
        api.create_broker(create_broker_payload(), ADMIN), 201)
    for i in range(12):
        create_yacht(operator["id"], central_agent["id"],
                     name=f"Y{i + 1:02d}", capacity_berths=4,
                     weekly_base_rate_cents=100000, security_deposit_cents=100000)

    page1, meta1 = validate_paginated(
        api.list_yachts(ADMIN, params={"operator_id": operator["id"]}))
    assert meta1["limit"] == 10, "the default limit is 10 when omitted"
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_yachts(ADMIN, params={"operator_id": operator["id"],
                                       "offset": 10}))
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False

    res = api.list_yachts(ADMIN, params={"operator_id": operator["id"],
                                         "limit": 101})
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
