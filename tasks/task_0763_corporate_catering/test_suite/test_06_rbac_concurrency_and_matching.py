"""Access control (authentication, role denial, segregation of duties), optimistic
concurrency on the shared inventory pool, the suspended-site gate, cross-entity invoice
matching, invoice variance tolerance, and session-slot uniqueness
(PRD §2.1, §2.5, §2.7, §2.8, §3.2, §3.6, §3.7).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_session, setup_catering_order, setup_matched_invoice,
    create_site, create_vendor, create_cycle, add_item, create_venue, create_invoice,
    stock_site, get_site_version, get_site,
    create_purchase_order_payload, create_service_session_payload, create_catering_order_payload,
    create_badge_transaction_payload,
    make_coordinator_headers, make_approver_headers,
)

ADMIN = TEST_USERS["site_admin_headers"]
MANAGER = TEST_USERS["cafeteria_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

WRAP = {"name": "Wrap", "category": "ENTREE", "price_cents": 350, "standard_recipe_cost_cents": 120}


# ─── Difficulty: cross_entity_state_dependency — invoice match needs RECEIVED PO ──
def _invoice_on_po(api, po_stage):
    site = create_site()
    vendor = create_vendor()
    po = validate_success(api.create_purchase_order(create_purchase_order_payload(
        vendor["id"], site["id"], [{"ingredient": "FLOUR", "qty": 10, "unit_cost_cents": 200}]), MANAGER), 201)
    if po_stage == "ISSUED":
        validate_success(api.issue_purchase_order(po["id"], MANAGER), 200)
    invoice = create_invoice(vendor["id"], po["id"], 2000)
    return invoice


def test_match_invoice_against_issued_po_rejected(api):
    """PRD §3.7: "Matching advances it from `RECEIVED` to `MATCHED` and requires that the
    referenced purchase order be in the `RECEIVED` state (otherwise `ERR_PO_NOT_RECEIVED`)."

    Design: Difficulty/cross_entity_state_dependency/invoice_match_requires_po_received
    """
    invoice = _invoice_on_po(api, "ISSUED")
    res = api.match_vendor_invoice(invoice["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_PO_NOT_RECEIVED.value, expected_status=409)
    assert validate_success(api.get_vendor_invoice(invoice["id"], FINANCE), 200)["status"] == "RECEIVED"


def test_match_invoice_against_draft_po_rejected(api):
    """PRD §3.7: "Matching advances it from `RECEIVED` to `MATCHED` and requires that the
    referenced purchase order be in the `RECEIVED` state (otherwise `ERR_PO_NOT_RECEIVED`)."

    Design: Difficulty/cross_entity_state_dependency/invoice_match_requires_po_received
    """
    invoice = _invoice_on_po(api, "DRAFT")
    res = api.match_vendor_invoice(invoice["id"], FINANCE)
    validate_error(res, ApiErrorId.ERR_PO_NOT_RECEIVED.value, expected_status=409)


# ─── Corner: validations — variance tolerance & session-slot uniqueness ─────
def test_invoice_variance_too_large_on_approve(api):
    """PRD §3.7: "A `resolution` of `APPROVE` advances the invoice from `MATCHED` to
    `APPROVED`, but only when the absolute value of `matched_variance_cents` is within the
    match tolerance of 500 cents; a larger absolute variance is rejected with
    `ERR_VARIANCE_TOO_LARGE`."

    Design: Corner/validations/invoice_variance_too_large_on_approve
    """
    ctx = setup_matched_invoice(3000, line=("FLOUR", 10, 200))  # variance 1000
    assert ctx["invoice"]["matched_variance_cents"] == 1000
    res = api.resolve_vendor_invoice(ctx["invoice"]["id"], {"resolution": "APPROVE"}, FINANCE)
    validate_error(res, ApiErrorId.ERR_VARIANCE_TOO_LARGE.value, expected_status=409)


def test_duplicate_session_slot_rejected(api):
    """PRD §3.2: "A site may hold only one session per combination of site, date, and meal
    period; a duplicate is rejected with `ERR_DUPLICATE_SESSION_SLOT`."

    Design: Corner/validations/duplicate_session_slot_rejected
    """
    site = create_site()
    cycle = create_cycle(site["id"])
    validate_success(api.create_service_session(create_service_session_payload(
        site["id"], cycle["id"], service_date="2026-03-02", meal_period="LUNCH",
        window_start="2026-03-02T11:00:00Z", window_end="2026-03-02T12:00:00Z"), MANAGER), 201)
    res = api.create_service_session(create_service_session_payload(
        site["id"], cycle["id"], service_date="2026-03-02", meal_period="LUNCH",
        window_start="2026-03-02T13:00:00Z", window_end="2026-03-02T14:00:00Z"), MANAGER)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SESSION_SLOT.value, expected_status=409)


# ─── Corner: rbac ───────────────────────────────────────────────────────────
def test_cafeteria_manager_cannot_create_badge_transaction(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." (POST /api/badge-transactions is authorized for Diner only, §4.)

    Design: Corner/rbac/cafeteria_manager_cannot_create_badge_transaction
    """
    ctx = setup_session(stage="IN_SERVICE", items=[WRAP])
    res = api.create_badge_transaction(create_badge_transaction_payload(
        ctx["employee"]["id"], ctx["session"]["id"],
        [{"menu_item_id": ctx["items"][0]["id"], "qty": 1}]), MANAGER)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_coordinator_cannot_review_order_role_denied(api):
    """PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." (POST /api/catering-orders/{id}/review is authorized for CateringApprover
    only, §4; the role check precedes the segregation-of-duties content check per §2.8.)

    Design: Corner/rbac/coordinator_cannot_review_own_order_role_denied
    """
    ctx = setup_catering_order(target="SUBMITTED", coordinator_id="coord-1")
    res = api.review_catering_order(ctx["order"]["id"], {"decision": "APPROVE"},
                                    make_coordinator_headers("coord-1"))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_segregation_of_duties_same_user_reviews_rejected(api):
    """PRD §3.6: "the approver's `X-User-ID` must not equal the order's `coordinator_id`, or
    the review is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_same_user_reviews_returns_error
    """
    ctx = setup_catering_order(target="SUBMITTED", coordinator_id="shared-1")
    res = api.review_catering_order(ctx["order"]["id"], {"decision": "APPROVE"},
                                    make_approver_headers("shared-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409)
    reread = validate_success(api.get_catering_order(ctx["order"]["id"], FINANCE), 200)
    assert reread["status"] == "SUBMITTED"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    site = create_site()
    res = api.get_client_site(site["id"], {})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# ─── Corner: cross_cutting — optimistic concurrency & suspended gate ────────
def test_confirm_with_correct_site_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "A confirm request must include `expected_client_site_version`, carrying the
    `version` of the target order's `ClientSite` as the caller last observed it."
    PRD §2.5: "confirming or fulfilling a catering order ... each increment the owning
    `ClientSite`'s `version` by 1."

    Design: Corner/cross_cutting/occ_correct_site_version_confirm_succeeds
    """
    ctx = setup_catering_order(target="APPROVED", stock=("KIT", 10, 100))
    version = get_site_version(ctx["site"]["id"])
    confirmed = validate_success(api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 2}]}, FINANCE), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert get_site(ctx["site"]["id"])["version"] == version + 1


def test_confirm_with_stale_site_version_returns_412(api):
    """PRD §2.7: "If `expected_client_site_version` does not equal the site's current
    `version` — because some other inventory-mutating write (a purchase-order receipt, a
    session close, or another catering confirmation) has advanced the site version since the
    caller last read it — the confirmation is rejected with `ERR_STALE_SITE_VERSION`
    (HTTP 412) and no inventory is reserved."

    Design: Corner/cross_cutting/occ_stale_site_version_on_confirm_returns_412
    """
    site = create_site()
    cycle = create_cycle(site["id"])
    wrap = add_item(cycle["id"], **WRAP)
    venue = create_venue(site["id"])
    stock_site(site["id"], "KIT", 20, 100)
    coord = make_coordinator_headers("coord-1")
    appr = make_approver_headers("appr-1")
    lines = [{"menu_item_id": wrap["id"], "qty": 1}]

    order_a = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], lines,
        event_start="2026-03-10T10:00:00Z", event_end="2026-03-10T11:00:00Z"), coord), 201)
    validate_success(api.submit_catering_order(order_a["id"], coord), 200)
    validate_success(api.review_catering_order(order_a["id"], {"decision": "APPROVE"}, appr), 200)

    order_b = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], lines,
        event_start="2026-03-10T12:00:00Z", event_end="2026-03-10T13:00:00Z"), coord), 201)
    validate_success(api.submit_catering_order(order_b["id"], coord), 200)
    validate_success(api.review_catering_order(order_b["id"], {"decision": "APPROVE"}, appr), 200)

    stale_version = get_site_version(site["id"])
    # Confirming A draws down the shared pool and advances the site version.
    validate_success(api.confirm_catering_order(
        order_a["id"], {"expected_client_site_version": stale_version,
                        "reserved_ingredients": [{"ingredient": "KIT", "qty": 2}]}, FINANCE), 200)
    # B still carries the pre-A version -> stale.
    res = api.confirm_catering_order(
        order_b["id"], {"expected_client_site_version": stale_version,
                        "reserved_ingredients": [{"ingredient": "KIT", "qty": 2}]}, FINANCE)
    validate_error(res, ApiErrorId.ERR_STALE_SITE_VERSION.value, expected_status=412)


def test_confirm_on_suspended_site_rejected(api):
    """PRD §3.6: "Confirmation requires, in order, that the site be `ACTIVE` (otherwise
    `ERR_SITE_SUSPENDED`)."

    Design: Corner/cross_cutting/site_suspended_blocks_confirm
    """
    ctx = setup_catering_order(target="APPROVED", stock=("KIT", 10, 100))
    validate_success(api.suspend_client_site(ctx["site"]["id"], ADMIN), 200)
    version = get_site_version(ctx["site"]["id"])
    res = api.confirm_catering_order(
        ctx["order"]["id"], {"expected_client_site_version": version,
                             "reserved_ingredients": [{"ingredient": "KIT", "qty": 2}]}, FINANCE)
    validate_error(res, ApiErrorId.ERR_SITE_SUSPENDED.value, expected_status=409)
