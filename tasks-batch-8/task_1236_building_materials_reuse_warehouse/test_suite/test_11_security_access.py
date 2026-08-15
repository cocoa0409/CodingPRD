"""Authentication, role authorization, entity-backed ownership, and the fixed
validation cascade order (PRD §2.1, §2.8, §2.10, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line,
    create_account,
    create_category,
    create_donor,
    create_offer,
    create_placed_item,
    create_sale,
    create_zone,
    finalize_sale,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_contractor_headers,
    make_donor_headers,
    make_intake_staff_headers,
)

INTAKE = TEST_USERS["intake_staff_headers"]
CASHIER = TEST_USERS["cashier_headers"]
ADMIN = TEST_USERS["warehouse_admin_headers"]


# ---------------------------------------------------------------------------
# Corner: errors / unauthenticated_request_rejected
# ---------------------------------------------------------------------------

def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the operational
    capacity in which they act. A request missing either header, or naming a role
    the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/unauthenticated_request_rejected
    """
    response = api.list_donors(headers=None)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner: validations / existence_beats_state_on_unknown_offer_accept
# ---------------------------------------------------------------------------

def test_accept_unknown_offer_returns_not_found(api):
    """PRD §2.8: "Requests are validated left to right. When a path carries
    resource identifiers, the system confirms each identifier exists before
    evaluating anything further along, and the first missing identifier produces
    that resource's own not-found error"
    PRD §2.10: "4. **Path existence** — path identifiers resolve, validated left
    to right, else the matching `ERR_{RESOURCE}_NOT_FOUND`." precedes "7.
    **State**".

    Design: Corner/validations/existence_beats_state_on_unknown_offer_accept
    """
    response = api.accept_offer(NON_EXISTENT_UUID, INTAKE)
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner: validations / role_denial_beats_not_found
# ---------------------------------------------------------------------------

def test_role_denial_beats_not_found(api):
    """PRD §2.10: "2. **Role authorization** — the acting role is listed in the
    endpoint's authorized roles, else `ERR_FORBIDDEN_ROLE`." precedes "4. **Path
    existence** — path identifiers resolve, validated left to right, else the
    matching `ERR_{RESOURCE}_NOT_FOUND`."
    PRD §2.1: "A request whose role is not listed among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/role_denial_beats_not_found
    """
    # Cashier is not among the offer-accept roles (PRD §4); even with a
    # non-existent offer id the role check must fire first.
    response = api.accept_offer(NON_EXISTENT_UUID, CASHIER)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Corner: rbac / donor_cannot_create_categories
# ---------------------------------------------------------------------------

def test_donor_cannot_create_categories(api):
    """PRD §2.1: "A request whose role is not listed among the roles authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: `POST /reuse/categories` is authorized for "StoreManager,
    WarehouseAdmin" only.

    Design: Corner/rbac/donor_cannot_create_categories
    """
    donor = create_donor(full_name="D RBAC")
    response = api.create_category(
        {
            "code": "NOPE", "display_name": "Nope", "pricing_model": "PER_UNIT",
            "base_rate_cents": 100, "hazmat_risk_flag": False,
            "markdown_after_days": 30, "markdown_step_pct": 0.20,
            "markdown_interval_days": 15, "max_markdown_steps": 2,
            "floor_price_pct": 0.40, "target_turn_days": 45,
        },
        make_donor_headers(donor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Corner: rbac / contractor_cannot_void_sale
# ---------------------------------------------------------------------------

def test_contractor_cannot_void_sale(api):
    """PRD §3.9: "A finalized sale can be voided by a `StoreManager` or
    `WarehouseAdmin` with a recorded `void_reason`; voiding from any state other
    than `FINALIZED` fails with `ERR_SALE_NOT_FINALIZED`."
    PRD §2.1: "A request whose role is not listed among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_void_sale
    """
    category = create_category(code="RBCAT", display_name="RB Cat",
                               base_rate_cents=50000)
    account = create_account(company_name="Ctor RB", contact_email="rb@x.com")
    zone = create_zone(code="ZRB", display_name="Zone RB", capacity=5)
    item = create_placed_item(category["id"], zone["id"], 50000,
                              description_text="rb item")
    contractor = make_contractor_headers(account["id"])
    sale = validate_success(api.create_sale(
        {"sale_channel": "CONTRACTOR_ACCOUNT", "contractor_id": account["id"]},
        contractor), expected_status=201)
    add_line(sale["id"], item["id"], headers=contractor)
    sale = validate_success(api.finalize_sale(sale["id"], {}, contractor))
    assert sale["status"] == "FINALIZED"

    response = api.void_sale(sale["id"], {"void_reason": "contractor attempt"}, contractor)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    sale = get_success_data(api.get_sale(sale["id"], CASHIER))
    assert sale["status"] == "FINALIZED", "rejected void leaves the sale FINALIZED"


# ---------------------------------------------------------------------------
# Corner: rbac / donor_read_other_offer_forbidden
# ---------------------------------------------------------------------------

def test_donor_read_other_offer_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the
    acting `Donor`; ownership checks on any resource that references a `Donor` —
    donation offers and tax receipts — compare the resource's `donor_id`
    foreign-key field to `X-User-ID`, and a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/donor_read_other_offer_forbidden
    """
    donor_a = create_donor(full_name="D A")
    donor_b = create_donor(full_name="D B")
    category = create_category(code="OWCAT", display_name="Own Cat")
    offer_b = create_offer(donor_b["id"], category["id"], description_text="b's offer")
    response = api.get_donation_offer(offer_b["id"], make_donor_headers(donor_a["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Corner: rbac / receipt_issuer_is_receiver_sod_rejected
# ---------------------------------------------------------------------------

def test_receipt_issuer_is_receiver_sod_rejected(api):
    """PRD §3.3: "Issuance is a second, deliberate act by an `IntakeStaff`
    operator, and the warehouse keeps the two hands apart: the operator issuing
    the receipt must not be the one who received the goods, so an `X-User-ID`
    equal to the receipt's `received_by_user_id` is refused with
    `ERR_RECEIPT_ISSUER_IS_RECEIVER`."
    PRD §3.3: "issuance stamps `issued_by_user_id` and `issued_at` from the acting
    operator and the logical clock."

    Design: Corner/rbac/receipt_issuer_is_receiver_sod_rejected
    """
    from test_helpers import add_offer_item, create_received_offer, draft_receipt

    category = create_category(code="SODCAT", display_name="SoD Cat",
                               base_rate_cents=30000)
    donor = create_donor(full_name="D SoD")
    offer = create_received_offer(donor["id"], category["id"],
                                  receiver_id="staff-sod-r", description_text="sod")
    add_offer_item(offer["id"], category["id"], 30000, estimated_weight_lbs=2)
    receipt = draft_receipt(offer["id"])

    response = api.issue_receipt(receipt["id"], {}, make_intake_staff_headers("staff-sod-r"))
    validate_error(response, ApiErrorId.ERR_RECEIPT_ISSUER_IS_RECEIVER)

    issued = validate_success(api.issue_receipt(
        receipt["id"], {}, make_intake_staff_headers("staff-sod-i")))
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == "staff-sod-i"
