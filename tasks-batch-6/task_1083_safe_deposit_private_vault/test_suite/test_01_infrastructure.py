"""Infrastructure, CRUD, listing, pagination, and RBAC (Corner queue B).

Covers entities / endpoints / rbac / consistency_model corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, ANON_HEADERS,
    make_renter_headers, assert_branch, assert_box,
)
from test_helpers import factories as F
from test_helpers import fixtures as X

ADMIN = TEST_USERS["vault_admin_headers"]
OFFICER = TEST_USERS["vault_officer_headers"]
ANY_HEADERS = ADMIN  # any authenticated role may read


def test_create_branch_returns_all_fields(api):
    """PRD §3.1: "A branch opens in `OPEN` status; a `CLOSED` branch blocks new
    boxes and appointments." PRD §4: "Operations that create a new resource
    return `201 Created`".

    Design: Corner/entities/branch_creation_returns_all_fields
    """
    resp = api.create_branch(F.create_branch_payload(viewing_room_capacity=3), ADMIN)
    data = validate_success(resp, 201)
    assert_branch(data)
    assert data["status"] == "OPEN"
    assert data["viewing_room_capacity"] == 3


def test_create_box_missing_box_number_rejected(api):
    """PRD §2.6: "required fields present, enums valid, numeric constraints
    satisfied (payment `amount_cents` greater than zero, `purity` in the
    half-open range greater than 0 and at most 1, and the precious-metal fields
    present when required), else `ERR_INVALID_REQUEST` (422)." PRD §3.1: "is
    placed in a branch by supplying its `branch_id`, its `box_type_id`, and a
    `box_number`".

    Design: Corner/entities/box_missing_required_field_rejected
    """
    branch = X.create_branch(api)
    box_type = X.create_box_type(api, size_class="SMALL", annual_rate_cents=12000)
    resp = api.create_box({"branch_id": branch["id"], "box_type_id": box_type["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_get_unknown_renter_returns_404(api):
    """PRD §2.6: "Path identifiers and body foreign keys are checked left to
    right, and the first identifier that resolves to nothing yields
    `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/renter_not_found_returns_404
    """
    resp = api.get_renter("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_rental_annual_rate_snapshotted_from_box_type(api):
    """PRD §3.3: "`annual_rate_cents` is snapshotted from the chosen box type so
    that later rate changes to the box type never disturb an existing lease."

    Design: Corner/entities/rental_annual_rate_snapshot_computed
    """
    branch = X.create_branch(api)
    box_type = X.create_box_type(api, size_class="LARGE", annual_rate_cents=48000)
    box = X.create_box(api, branch["id"], box_type["id"])
    renter = X.create_renter(api, verified=False)
    resp = api.create_rental(F.create_rental_payload(box["id"], renter["id"], plan_term_months=12), ADMIN)
    data = validate_success(resp, 201)
    assert data["annual_rate_cents"] == 48000
    assert data["status"] == "PENDING"


def test_rental_optional_terms_apply_defaults(api):
    """PRD §3.3: "optional terms: `plan_term_months` (the lease length in months,
    at least 1, defaulting to 12), `autopay_enabled` (default false),
    `autopay_source_ref` (a stored payment instrument, default null),
    `insurance_rider_enabled` (default false)".

    Design: Corner/entities/rental_defaults_applied
    """
    branch = X.create_branch(api)
    box_type = X.create_box_type(api, size_class="SMALL", annual_rate_cents=12000)
    box = X.create_box(api, branch["id"], box_type["id"])
    renter = X.create_renter(api, verified=False)
    resp = api.create_rental({"box_id": box["id"], "renter_id": renter["id"]}, ADMIN)
    data = validate_success(resp, 201)
    assert data["plan_term_months"] == 12
    assert data["autopay_enabled"] is False
    assert data["insurance_rider_enabled"] is False


def test_create_box_with_unknown_branch_rejected(api):
    """PRD §2.6: "every referenced resource exists. Path identifiers and body
    foreign keys are checked left to right, and the first identifier that
    resolves to nothing yields `ERR_NOT_FOUND` (404). A body foreign key is only
    checked after the path resource it belongs to is confirmed."

    Design: Corner/entities/box_bad_branch_fk_rejected
    """
    box_type = X.create_box_type(api, size_class="SMALL", annual_rate_cents=12000)
    resp = api.create_box(
        {"branch_id": "00000000-0000-4000-8000-000000000001",
         "box_type_id": box_type["id"], "box_number": "X-1"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_box_read_after_write_is_immediate(api):
    """PRD §3.1: "A new box starts `AVAILABLE`." PRD §2.4: "Every primary
    resource carries a server-minted `id` formatted as a UUID with no type
    prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional
    digits."

    Design: Corner/consistency_model/immediate_read_after_write
    """
    branch = X.create_branch(api)
    box_type = X.create_box_type(api, size_class="SMALL", annual_rate_cents=12000)
    box = X.create_box(api, branch["id"], box_type["id"], box_number="IM-1")
    resp = api.get_box(box["id"], ANY_HEADERS)
    data = validate_success(resp, 200)
    assert_box(data)
    assert data["box_number"] == "IM-1"
    assert data["status"] == "AVAILABLE"


def test_list_rentals_filter_by_status(api):
    """PRD §3.3: "Rentals may be listed and filtered by `box_id`, `renter_id`,
    and `status`."

    Design: Corner/endpoints/list_rentals_filter_by_status
    """
    branch = X.create_branch(api, viewing_room_capacity=4)
    box_type = X.create_box_type(api)
    box1 = X.create_box(api, branch["id"], box_type["id"])
    box2 = X.create_box(api, branch["id"], box_type["id"])
    renterA = X.create_renter(api)
    rentalA = X.create_rental(api, box1["id"], renterA["id"])
    rentalA = validate_success(api.activate_rental(rentalA["id"], ADMIN), 200)
    renterB = X.create_renter(api, verified=False)
    rentalB = X.create_rental(api, box2["id"], renterB["id"])

    resp = api.list_rentals(ANY_HEADERS, params={"status": "ACTIVE"})
    data, meta = validate_paginated(resp)
    ids = {r["id"] for r in data}
    assert rentalA["id"] in ids, "ACTIVE rental must appear"
    assert rentalB["id"] not in ids, "PENDING rental must be excluded by status filter"


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "A `limit` or `offset` outside its permitted range is rejected with
    `ERR_VALIDATION`."

    Design: Corner/endpoints/pagination_limit_out_of_range_rejected
    """
    resp = api.list_renters(ADMIN, params={"limit": 1000})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_renter_cannot_run_billing_cycle(api):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted
    for the target operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/renter_cannot_run_billing_cycle
    """
    renter = X.create_renter(api, verified=False)
    resp = api.run_billing_cycle(make_renter_headers(renter["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)


def test_officer_cannot_create_branch(api):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted
    for the target operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/officer_cannot_create_branch
    """
    resp = api.create_branch(F.create_branch_payload(), OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting a value the
    server cannot validate, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    resp = api.create_branch(F.create_branch_payload(), ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
