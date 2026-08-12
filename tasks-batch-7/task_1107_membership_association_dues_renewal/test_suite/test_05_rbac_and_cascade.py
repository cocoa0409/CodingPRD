"""RBAC denials, expel cascade, response envelope.

Covers Queue A difficulty instances: none directly (all are in earlier files).

Covers Queue B corner instances:
- rbac/member_cannot_publish_schedule_returns_forbidden
- rbac/member_cannot_expel_other_member_returns_forbidden
- rbac/dues_administrator_cannot_refund_returns_forbidden
- cross_cutting_complexity_layers/cascading_side_effects_member_expel_cascade
- endpoints/response_envelope_success_shape
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_category,
    create_chapter,
    create_cycle_policy,
    create_published_schedule,
    create_draft_schedule,
    create_member,
    get_initial_invoice,
    settle_invoice,
    verify_member,
    advance_clock_and_run,
    get_pending_renewal_invoice,
    make_member_headers,
    list_benefits,
    get_directory_listing,
    get_auto_renew_auth,
    TEST_USERS,
)

DUES_ADMIN = TEST_USERS["dues_admin_headers"]
MEMBERSHIP_ADMIN = TEST_USERS["membership_admin_headers"]


# =====================================================================
# Queue B — rbac/member_cannot_publish_schedule_returns_forbidden
# =====================================================================

def test_member_cannot_publish_schedule_returns_forbidden(api):
    """PRD §2.1: "Once the role is authenticated, the request is checked against the
    role-permission matrix in §4; any action outside the caller's authorized set is
    rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4: POST /api/dues-schedules/{id}/publish is authorized for DuesAdministrator
    only.

    Design: Corner/rbac/member_cannot_publish_schedule_returns_forbidden
    """
    cat = create_category(code="PROF", name="P")
    s = create_draft_schedule(cat["id"])
    # Member role (shared fallback headers fine — no ownership gating on this endpoint)
    resp = api_client.publish_dues_schedule(s["id"], TEST_USERS["member_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# =====================================================================
# Queue B — rbac/member_cannot_expel_other_member_returns_forbidden
# =====================================================================

def test_member_cannot_expel_other_member_returns_forbidden(api):
    """PRD §4: POST /api/members/{id}/expel is authorized for MembershipAdministrator
    only.
    PRD §2.1: "any action outside the caller's authorized set is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/member_cannot_expel_other_member_returns_forbidden
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    create_published_schedule(cat["id"],
                               effective_from="2026-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    ma = create_member(cat["id"], ch["id"], pol["id"], email="a@x.com")
    mb = create_member(cat["id"], ch["id"], pol["id"], email="b@x.com")
    # Member A attempts to expel Member B
    resp = api_client.expel_member(mb["id"], make_member_headers(ma["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# =====================================================================
# Queue B — rbac/dues_administrator_cannot_refund_returns_forbidden
# =====================================================================

def test_dues_administrator_cannot_refund_returns_forbidden(api):
    """PRD §4: POST /api/dues-invoices/{id}/refund is authorized for
    MembershipAdministrator only.
    PRD §2.1: "any action outside the caller's authorized set is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/dues_administrator_cannot_refund_returns_forbidden
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    create_published_schedule(cat["id"],
                               effective_from="2026-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv = get_initial_invoice(m["id"], mh)
    settle_invoice(inv["id"], mh)
    resp = api_client.refund_invoice(inv["id"], DUES_ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# =====================================================================
# Queue B — cross_cutting_complexity_layers/cascading_side_effects_member_expel_cascade
# =====================================================================

def test_expel_cascades_to_all_children(api):
    """PRD §3.7: "Expulsion applies the same cascade as resignation: auto-renew
    revoked, entitlements revoked, directory hidden as HIDDEN_OPT_OUT, open invoices
    written off, member version incremented."
    PRD §3.7 (resignation cascade): "Resignation revokes the AutoRenewAuthorization
    (status REVOKED, revoked_at stamped), transitions every BenefitEntitlement to
    REVOKED, sets the DirectoryListing visibility_state to HIDDEN_OPT_OUT, writes off
    every open DuesInvoice — those in PENDING or FAILED_RETRYABLE transition to
    WRITTEN_OFF in payment_status and COVERAGE_ENDED in fulfillment_status while
    remaining readable for audit — and increments the member's version."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_member_expel_cascade
    """
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    create_published_schedule(cat["id"],
                               effective_from="2026-01-01T00:00:00Z",
                               annual_amount_cents=120000, chapter_share_bps=2000,
                               increase_notice_days=60)
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv0 = get_initial_invoice(m["id"], mh)
    settle_invoice(inv0["id"], mh)
    verify_member(m["id"])
    enroll_resp = api_client.enroll_auto_renew(
        m["id"], {"payment_method_token": "tok_v"}, mh
    )
    validate_success(enroll_resp, expected_status=201)
    # Force renewal invoice issuance
    advance_clock_and_run("2027-04-25T00:00:00Z")
    inv_r = get_pending_renewal_invoice(m["id"])
    # Expel
    expel_resp = api_client.expel_member(m["id"], MEMBERSHIP_ADMIN)
    validate_success(expel_resp, expected_status=200)
    m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
    assert m_after["status"] == "EXPELLED"
    ar_list = get_auto_renew_auth(m["id"], MEMBERSHIP_ADMIN)
    assert isinstance(ar_list, list) and len(ar_list) == 1
    assert ar_list[0]["status"] == "REVOKED"
    benefits = list_benefits(m["id"], MEMBERSHIP_ADMIN)
    for b in benefits:
        assert b["status"] == "REVOKED", (
            f"BenefitEntitlement must be REVOKED after expel; got {b['status']}"
        )
    listings = get_directory_listing(m["id"], MEMBERSHIP_ADMIN)
    assert isinstance(listings, list) and len(listings) == 1
    assert listings[0]["visibility_state"] == "HIDDEN_OPT_OUT"
    inv_r_after = get_success_data(api_client.get_dues_invoice(inv_r["id"], MEMBERSHIP_ADMIN))
    assert inv_r_after["payment_status"] == "WRITTEN_OFF"


# =====================================================================
# Queue B — endpoints/response_envelope_success_shape
# =====================================================================

def test_response_envelope_success_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format in their JSON body" with keys meta.api_request_id,
    meta.api_request_timestamp, response_type, data. "The api_request_id is a
    server-generated unique identifier for the request that starts with req_."
    "The response_type is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/endpoints/response_envelope_success_shape
    """
    cat = create_category(code="PROF", name="P")
    resp = api_client.get_membership_category(cat["id"], DUES_ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert "meta" in body and "response_type" in body and "data" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "object"
    assert body["data"]["id"] == cat["id"]
