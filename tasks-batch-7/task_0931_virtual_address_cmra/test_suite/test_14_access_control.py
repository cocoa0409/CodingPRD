"""Authentication, role authorization and the two entity-backed identities."""

from test_helpers import (
    CMRA_OPERATOR,
    ApiErrorId,
    activate_box,
    add_recipient,
    box_version,
    create_box,
    create_plan_tier,
    file_id_document,
    log_and_match_letter,
    make_box_holder_headers,
    make_notary_headers,
    make_recipient_headers,
    plan_change_payload,
    setup_releasable_box,
    validate_error,
    validate_success,
)


def test_a_request_with_no_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request — without exception, including reads — must carry two
    headers: `X-User-ID` and `X-User-Role`. If either header is absent, or if
    `X-User-Role` carries a string that is not one of the six role names below, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "Test material sometimes refers to this situation as an "Anonymous"
    caller; there is no such role, and any request that would be described that way lands
    on `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    create_plan_tier()

    response = api.get("/boxes", headers={})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_a_box_holder_may_not_act_on_another_mailbox(api):
    """PRD §2.1: "When `X-User-Role` is `BoxHolder`, `X-User-ID` is the `id` of the
    acting mailbox. Ownership checks compare the mailbox the request targets — directly
    through a `/boxes/{id}/…` path, or indirectly through the `box_id` of the resource
    named in the path — to `X-User-ID`. A mismatch is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.9 rung 8: "A `BoxHolder`'s `X-User-ID` equals the mailbox the request targets,
    directly or through the target resource's `box_id`; a `Recipient`'s `X-User-ID`
    equals the target piece's `matched_recipient_id`. Otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/validations/box_holder_cannot_act_on_another_boxes_resources
    """
    plus = create_plan_tier()
    business = create_plan_tier(
        tier_code="BUSINESS",
        name="Business",
        rank=3,
        monthly_fee_cents=9000,
        included_recipients=6,
        included_scan_pages=100,
        included_forwards=4,
        overage_scan_page_cents=20,
        overage_forward_cents=800,
        overage_storage_day_cents=25,
        overage_recipient_cents=400,
    )
    box_a = create_box("Z-3001", plus["id"], holder_name="Box A", holder_email="a@example.com")
    activate_box(box_a["id"])
    box_b = create_box("Z-3002", plus["id"], holder_name="Box B", holder_email="b@example.com")
    activate_box(box_b["id"])

    response = api.change_plan(
        box_b["id"],
        plan_change_payload(business["id"], box_version(box_b["id"])),
        make_box_holder_headers(box_a["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    unchanged = validate_success(api.get_box(box_b["id"], CMRA_OPERATOR))
    assert unchanged["plan_tier_id"] == plus["id"]
    assert unchanged["pending_plan_tier_id"] is None


def test_a_notary_may_not_accept_a_form(api):
    """PRD §2.1: "A `Notary` is a commissioned notary who witnesses the Form 1583
    signature and holds no other authority whatsoever."
    PRD §2.9 rung 2: "The acting role appears in the endpoint's permitted-role list.
    Otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Corner/rbac/notary_cannot_perform_compliance_officer_operations
    """
    ctx = setup_releasable_box(
        "Z-6001", "Yul Role", holder_email="yul@example.com", accept_form=False
    )

    response = api.accept_form(ctx["form_id"], make_notary_headers("not-2"))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    form = validate_success(api.get_form_1583(ctx["form_id"], CMRA_OPERATOR))
    assert form["status"] == "NOTARIZED"


def test_a_box_holder_may_not_verify_an_identification_document(api):
    """PRD §2.1: "A `CmraOperator` is counter staff at the facility: it opens mailboxes,
    manages the roster and identification documents, logs and matches inbound mail, runs
    the scanning line, executes dispositions, handles checks and finalizes
    cancellations."
    PRD §2.9 rung 2: "The acting role appears in the endpoint's permitted-role list.
    Otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Corner/rbac/box_holder_cannot_verify_identification_documents
    """
    plan = create_plan_tier()
    box = create_box("Z-6002", plan["id"], holder_name="Zia Holder", holder_email="zia@example.com")
    activate_box(box["id"])
    member = add_recipient(box["id"], "Zia Holder")
    document = file_id_document(member["id"], "ADDRESS", "LEASE", "2027-03-31")

    response = api.verify_id_document(document["id"], make_box_holder_headers(box["id"]))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    documents = validate_success(api.list_id_documents(member["id"], CMRA_OPERATOR))
    assert documents[0]["status"] == "PENDING_REVIEW"
    assert documents[0]["verified_at"] is None


def test_a_roster_member_may_read_only_its_own_pieces(api):
    """PRD §2.1: "When `X-User-Role` is `Recipient`, `X-User-ID` is the `id` of the
    acting roster member. A `Recipient` may read only pieces whose
    `matched_recipient_id` equals its own id; anything else is `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD §3.4: "A successful match sets `matched_recipient_id`, which is never
    subsequently cleared, and bumps `MailItem.version` by one."

    Design: Corner/rbac/recipient_role_may_only_read_its_own_pieces
    """
    ctx = setup_releasable_box("Z-6003", "Abe Own", holder_email="abe@example.com")
    other = add_recipient(ctx["box_id"], "Bea Other")
    item = log_and_match_letter(ctx)

    own = validate_success(
        api.get_mail_item(item["id"], make_recipient_headers(ctx["recipient_id"]))
    )
    assert own["matched_recipient_id"] == ctx["recipient_id"]

    foreign = api.get_mail_item(
        item["id"], make_recipient_headers(other["id"])
    )
    validate_error(foreign, ApiErrorId.ERR_UNAUTHORIZED.value)
