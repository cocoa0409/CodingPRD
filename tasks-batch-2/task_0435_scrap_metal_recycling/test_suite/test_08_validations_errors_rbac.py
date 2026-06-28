"""Validation violations, error-catalogue triggers, RBAC denials.

Corner queue: validations + errors + rbac section instances.
"""
from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_weighed_ticket,
    create_released_ticket,
    WM, PC, YM, CO,
)
from test_helpers.test_users import TEST_USERS
from prd_bench_local_runner.testing import build_user_headers


# ---- validations ----
def test_weigh_out_tare_ge_gross_rejected(api):
    """PRD §3.3: "The `tare_weight_lb` must be at least 0 and strictly less than the
    ticket's `gross_weight_lb` — the empty vehicle must weigh less than the loaded
    one — or the request is rejected with `ERR_INVALID_WEIGHT` (HTTP 422)."

    tare 1500 == gross 1500 is not strictly less.

    Design: Corner/validations/weigh_out_tare_ge_gross_rejected
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Tare Co", id_type="STATE_ID", id_number="SID-TR")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "SHRED_STEEL", 100)
    resp = api.weigh_out(ticket["id"], {"tare_weight_lb": 1500}, WM)
    validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT.value)


def test_line_item_grade_not_active_rejected(api):
    """PRD §3.3: "Adding a line resolves `grade_code` against the price book: it must
    match a `CommodityPrice` whose `status` is `ACTIVE`, otherwise the line is
    rejected with `ERR_GRADE_NOT_ACTIVE` (HTTP 409)."

    A grade that was never published has no ACTIVE price row.

    Design: Corner/validations/line_item_superseded_grade_rejected
    """
    seller = register_seller(legal_name="NoGrade Co", id_type="STATE_ID", id_number="SID-NG")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    resp = api.add_line_item(ticket["id"], {"grade_code": "UNKNOWN_GRADE", "weight_lb": 100}, WM)
    validate_error(resp, ApiErrorId.ERR_GRADE_NOT_ACTIVE.value)


def test_release_mixed_category_container_rejected(api):
    """PRD §3.4: "The container's `category` must match the category of *every* line
    item on the ticket — a mixed-category ticket, or one whose grades do not all
    match the container, cannot be loaded, and the release is rejected with
    `ERR_CATEGORY_MISMATCH` (HTTP 409)."

    A NON_FERROUS (CU) ticket released into a FERROUS container mismatches.

    Design: Corner/validations/release_mixed_category_container_rejected
    """
    built = create_weighed_ticket(grade_code="CU_BARE_BRIGHT", category="NON_FERROUS",
                                  spot=375, mill=410, weight_lb=100)
    ferrous_container = stage_container("FERROUS", capacity_lb=5000)
    resp = api.release_ticket(built["ticket"]["id"], {"container_id": ferrous_container["id"]}, WM)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH.value)


def test_tin_required_for_1099_cash_settle_rejected(api):
    """PRD §3.5: "if the `method` is `CASH` and adding this payout would bring
    `ytd_cash_paid_cents` to at least 60000 cents, the seller must already have a
    non-null `tin` on file; if not, the settle is rejected with
    `ERR_TIN_REQUIRED_FOR_1099` (HTTP 422) and no funds are disbursed."

    A 60000c CASH payout for a TIN-less seller is rejected on settle.

    Design: Corner/validations/tin_required_for_1099_cash_settle_rejected
    """
    publish_price("BRASS", "NON_FERROUS", spot=100, mill=110)
    seller = register_seller(legal_name="NoTIN Co", id_type="STATE_ID", id_number="SID-NT")
    built = create_released_ticket(
        grade_code="BRASS", category="NON_FERROUS", spot=100, mill=110,
        weight_lb=600, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    resp = api.settle_payout(payout["id"], PC)
    validate_error(resp, ApiErrorId.ERR_TIN_REQUIRED_FOR_1099.value)
    after = validate_success(api.get_payout(payout["id"], PC))
    assert after["status"] == "PENDING", f"payout must stay PENDING, got {after['status']}"


def test_duplicate_payout_for_ticket_rejected(api):
    """PRD §3.5: "There must be no existing payout for the ticket — exactly one
    payout per ticket, and a second attempt is rejected with `ERR_DUPLICATE_PAYOUT`
    (HTTP 409)."

    Design: Corner/validations/duplicate_payout_for_ticket_rejected
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Dup Co", id_type="STATE_ID", id_number="SID-DUP")
    built = create_released_ticket(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=100, capacity_lb=5000, seller_id=seller["id"],
    )
    validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CHECK"}, PC), 201
    )
    resp = api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYOUT.value)


# ---- errors ----
def test_error_invalid_request_negative_weight(api):
    """PRD §3.3: "Each line names a `grade_code` and a `weight_lb` (the pounds of
    that grade, which must be greater than 0)."
    PRD §5: "ERR_INVALID_REQUEST | 422".

    weight_lb of 0 is out of range.

    Design: Corner/errors/error_invalid_request_negative_weight
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Neg Co", id_type="STATE_ID", id_number="SID-NEG")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    resp = api.add_line_item(ticket["id"], {"grade_code": "SHRED_STEEL", "weight_lb": 0}, WM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---- rbac ----
def test_payoutclerk_cannot_open_ticket(api):
    """PRD §2.1: "If the headers are well-formed and the role is recognized but that
    role is not permitted to perform the requested operation, the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST /yard/tickets | Open a DRAFT scale ticket at inbound weigh |
    WeighMaster".

    A PayoutClerk is not authorized to open tickets.

    Design: Corner/rbac/payoutclerk_cannot_open_ticket
    """
    seller = register_seller(legal_name="Rbac Co", id_type="STATE_ID", id_number="SID-RB")
    resp = api.create_ticket({"seller_id": seller["id"], "gross_weight_lb": 100}, PC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_weighmaster_cannot_publish_price(api):
    """PRD §2.1: "If the headers are well-formed and the role is recognized but that
    role is not permitted to perform the requested operation, the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.2: "A `YardManager` publishes a price by supplying a `grade_code`".

    A WeighMaster is not authorized to publish prices.

    Design: Corner/rbac/weighmaster_cannot_publish_price
    """
    resp = api.create_commodity_price(
        {"grade_code": "X", "category": "FERROUS",
         "spot_price_cents_per_lb": 10, "mill_price_cents_per_lb": 12}, WM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    An unknown role header is rejected before anything else.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    ghost = build_user_headers("ghost-1", "Ghost")
    resp = api.create_seller(
        {"legal_name": "NoAuth", "id_type": "STATE_ID", "id_number": "SID-NA"}, ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
