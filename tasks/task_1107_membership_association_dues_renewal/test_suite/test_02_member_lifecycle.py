"""Member lifecycle: registration, verification, grace, lapse, reinstatement,
resignation, expulsion, OCC.

Covers Queue A difficulty instances:
- cross_entity_state_dependency/member_verify_gated_on_dues_invoice_settled
- non_linear_state_machine/member_cyclic_grace_active_lapsed_reinstated_cycle
- resource_temporal_overlap/membership_term_reinstatement_back_to_back

Covers Queue B corner instances:
- entities/member_computed_fields_ignore_client_input
- entities/member_get_nonexistent_returns_not_found
- entities/members_list_pagination_defaults
- state_machines/member_resign_from_already_resigned_returns_invalid_state
- cross_cutting_complexity_layers/occ_stale_member_version_on_resign_rejected
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_category,
    create_chapter,
    create_cycle_policy,
    create_published_schedule,
    create_member,
    get_initial_invoice,
    settle_invoice,
    verify_member,
    set_clock,
    advance_clock_and_run,
    run_renewal_cycle,
    get_pending_renewal_invoice,
    make_member_headers,
    TEST_USERS,
)

DUES_ADMIN = TEST_USERS["dues_admin_headers"]
MEMBERSHIP_ADMIN = TEST_USERS["membership_admin_headers"]


def _setup_reference():
    cat = create_category(code="PROF", name="P")
    ch = create_chapter(code="CH", name="C")
    pol = create_cycle_policy(code="POLICY", mode="ANNIVERSARY",
                               calendar_anchor_month=1, calendar_anchor_day=1,
                               proration_method="NONE")
    sched = create_published_schedule(cat["id"],
                                       effective_from="2026-01-01T00:00:00Z",
                                       annual_amount_cents=120000,
                                       chapter_share_bps=2000,
                                       increase_notice_days=60)
    return cat, ch, pol, sched


# =====================================================================
# Queue A — cross_entity_state_dependency/member_verify_gated_on_dues_invoice_settled
# =====================================================================

class TestVerifyGatedOnInvoiceSettled:
    def test_verify_before_settle_rejected_verification_blocked(self, api):
        """PRD §3.6: "If the initial invoice has not yet settled, the verification is
        rejected with ERR_VERIFICATION_BLOCKED."

        Design: Difficulty/cross_entity_state_dependency/member_verify_gated_on_dues_invoice_settled
        """
        cat, ch, pol, _ = _setup_reference()
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        resp = api_client.verify_member(m["id"], make_member_headers(m["id"]))
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_BLOCKED)

    def test_verify_after_settle_succeeds(self, api):
        """PRD §3.6: "The preconditions are that the member is currently in
        PENDING_VERIFICATION and that the initial DuesInvoice for the opening term
        has reached payment_status of SETTLED." "When verification succeeds, the
        member transitions from PENDING_VERIFICATION to ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/member_verify_gated_on_dues_invoice_settled
        """
        cat, ch, pol, _ = _setup_reference()
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv = get_initial_invoice(m["id"], mh)
        settle_invoice(inv["id"], mh)
        resp = api_client.verify_member(m["id"], mh)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ACTIVE"


# =====================================================================
# Queue B — entities/member_computed_fields_ignore_client_input
# =====================================================================

def test_member_create_initializes_system_fields(api):
    """PRD §3.3: "The Member row is created with status set to PENDING_VERIFICATION
    and version initialized to 1."
    PRD §3.10: "The member's lifetime_dues_paid_cents is not changed by these
    attributions — that accumulator counts settled dues invoices only." (So before
    any settle, the accumulator is zero.)

    Design: Corner/entities/member_computed_fields_ignore_client_input
    """
    cat, ch, pol, _ = _setup_reference()
    resp = api_client.create_member(
        {
            "email": "m@x.com",
            "full_name": "M",
            "category_id": cat["id"],
            "home_chapter_id": ch["id"],
            "cycle_policy_id": pol["id"],
            "joined_at": "2026-05-01T00:00:00Z",
        },
        make_member_headers("registrar"),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["version"] == 1
    assert data["lifetime_dues_paid_cents"] == 0


# =====================================================================
# Queue B — entities/member_get_nonexistent_returns_not_found
# =====================================================================

def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.5: "(3) existence of every path id and every referenced body id
    (member, invoice, schedule, chapter, category, cycle policy, and so on) —
    failures yield ERR_NOT_FOUND."

    Design: Corner/entities/member_get_nonexistent_returns_not_found
    """
    resp = api_client.get_member(NON_EXISTENT_UUID, MEMBERSHIP_ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# =====================================================================
# Queue B — entities/members_list_pagination_defaults
# =====================================================================

def test_list_members_pagination_envelope(api):
    """PRD §2.3: "If limit is omitted it defaults to 10, with a minimum of 1 and a
    maximum of 100. If offset is omitted it defaults to 0. ... Every paginated list
    response carries limit, offset, total_count, and has_more in its meta block."

    Design: Corner/entities/members_list_pagination_defaults
    """
    cat, ch, pol, _ = _setup_reference()
    create_member(cat["id"], ch["id"], pol["id"], email="m1@x.com")
    create_member(cat["id"], ch["id"], pol["id"], email="m2@x.com")
    resp = api_client.list_members(MEMBERSHIP_ADMIN)
    data_list, meta = validate_paginated(resp)
    assert isinstance(data_list, list)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert "total_count" in meta
    assert "has_more" in meta


# =====================================================================
# Queue A — non_linear_state_machine/member_cyclic_grace_active_lapsed_reinstated_cycle
# =====================================================================

class TestMemberGraceCycle:
    def test_grace_to_active_on_renewal_settle(self, api):
        """PRD §3.7: "When a payment attempt on a renewal invoice succeeds and settles
        the renewal invoice, the member transitions from GRACE back to ACTIVE."

        Design: Difficulty/non_linear_state_machine/member_cyclic_grace_active_lapsed_reinstated_cycle
        """
        cat, ch, pol, _ = _setup_reference()
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv0 = get_initial_invoice(m["id"], mh)
        settle_invoice(inv0["id"], mh)
        verify_member(m["id"])
        # Advance past current_period_end (2027-05-01) but within grace (30 days)
        advance_clock_and_run("2027-05-15T00:00:00Z")
        # Renewal invoice should have been issued by the sweep
        inv_r = get_pending_renewal_invoice(m["id"])
        settle_invoice(inv_r["id"], mh)
        m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after["status"] == "ACTIVE"

    def test_renewal_settle_opens_new_term_with_renewal_opened_by(self, api):
        """PRD §3.7: "A new MembershipTerm is opened for the new period with
        opened_by set to RENEWAL."

        Design: Difficulty/non_linear_state_machine/member_cyclic_grace_active_lapsed_reinstated_cycle
        """
        cat, ch, pol, _ = _setup_reference()
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv0 = get_initial_invoice(m["id"], mh)
        settle_invoice(inv0["id"], mh)
        verify_member(m["id"])
        advance_clock_and_run("2027-05-15T00:00:00Z")
        inv_r = get_pending_renewal_invoice(m["id"])
        settle_invoice(inv_r["id"], mh)
        terms = get_success_data(api_client.list_membership_terms(m["id"], MEMBERSHIP_ADMIN))
        renewal_terms = [t for t in terms if t.get("opened_by") == "RENEWAL"]
        assert len(renewal_terms) >= 1, (
            f"expected a RENEWAL MembershipTerm after grace-cycle renewal settle; terms={terms}"
        )


# =====================================================================
# Queue A — resource_temporal_overlap/membership_term_reinstatement_back_to_back
# =====================================================================

class TestReinstatementBackToBack:
    def _setup_lapsed_member_with_back_dues_settled(self):
        cat, ch, pol, _ = _setup_reference()
        m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
        mh = make_member_headers(m["id"])
        inv0 = get_initial_invoice(m["id"], mh)
        settle_invoice(inv0["id"], mh)
        verify_member(m["id"])
        # Past period_end (2027-05-01) + 30 grace days = past 2027-05-31 -> LAPSED
        advance_clock_and_run("2027-06-15T00:00:00Z")
        # File reinstatement request within window (90 days)
        set_clock("2027-07-01T00:00:00Z")
        req_resp = api_client.create_reinstatement_request(m["id"], mh)
        req = get_success_data(req_resp)
        back_inv_id = req["back_dues_invoice_id"]
        # Settle the back-dues invoice
        settle_invoice(back_inv_id, mh)
        return m, req, back_inv_id, mh

    def test_reinstatement_approve_moves_member_to_active(self, api):
        """PRD §3.7: "Approval transitions the request to APPROVED, opens a new
        MembershipTerm with opened_by set to REINSTATEMENT, moves the member from
        LAPSED through REINSTATED to ACTIVE in the same commit..."

        Design: Difficulty/resource_temporal_overlap/membership_term_reinstatement_back_to_back
        """
        m, req, back_inv_id, mh = self._setup_lapsed_member_with_back_dues_settled()
        approve_resp = api_client.approve_reinstatement_request(
            m["id"], req["id"], MEMBERSHIP_ADMIN
        )
        approved = validate_success(approve_resp, expected_status=200)
        assert approved["status"] == "APPROVED"
        m_after = get_success_data(api_client.get_member(m["id"], MEMBERSHIP_ADMIN))
        assert m_after["status"] == "ACTIVE"
        back_inv = get_success_data(api_client.get_dues_invoice(back_inv_id, MEMBERSHIP_ADMIN))
        assert back_inv["payment_status"] == "SETTLED"

    def test_reinstatement_opens_new_term_with_reinstatement_opened_by(self, api):
        """PRD §3.7: "Approval transitions the request to APPROVED, opens a new
        MembershipTerm with opened_by set to REINSTATEMENT..."

        Design: Difficulty/resource_temporal_overlap/membership_term_reinstatement_back_to_back
        """
        m, req, back_inv_id, mh = self._setup_lapsed_member_with_back_dues_settled()
        approve_resp = api_client.approve_reinstatement_request(
            m["id"], req["id"], MEMBERSHIP_ADMIN
        )
        validate_success(approve_resp, expected_status=200)
        terms = get_success_data(api_client.list_membership_terms(m["id"], MEMBERSHIP_ADMIN))
        reinstatement_terms = [t for t in terms if t.get("opened_by") == "REINSTATEMENT"]
        assert len(reinstatement_terms) >= 1, (
            f"expected a REINSTATEMENT MembershipTerm; terms={terms}"
        )


# =====================================================================
# Queue B — state_machines/member_resign_from_already_resigned_returns_invalid_state
# =====================================================================

def test_resign_already_resigned_returns_invalid_state(api):
    """PRD §3.7: "A member in ACTIVE or GRACE may resign by submitting
    expected_member_version." A RESIGNED member is outside {ACTIVE, GRACE}.
    PRD §2.5: "(6) target state permits the requested transition — failures yield
    ERR_INVALID_STATE."

    Design: Corner/state_machines/member_resign_from_already_resigned_returns_invalid_state
    """
    cat, ch, pol, _ = _setup_reference()
    m = create_member(cat["id"], ch["id"], pol["id"], email="m@x.com")
    mh = make_member_headers(m["id"])
    inv = get_initial_invoice(m["id"], mh)
    settle_invoice(inv["id"], mh)
    verify_member(m["id"])
    m_now = get_success_data(api_client.get_member(m["id"], mh))
    resign_resp = api_client.resign_member(
        m["id"], {"expected_member_version": m_now["version"]}, mh
    )
    validate_success(resign_resp, expected_status=200)
    m_after = get_success_data(api_client.get_member(m["id"], mh))
    resign_again = api_client.resign_member(
        m["id"], {"expected_member_version": m_after["version"]}, mh
    )
    validate_error(resign_again, ApiErrorId.ERR_INVALID_STATE)


# =====================================================================
# Queue B — cross_cutting_complexity_layers/occ_stale_member_version_on_resign_rejected
# =====================================================================

def test_resign_with_stale_member_version_rejected(api):
    """PRD §2.8: "If expected_member_version does not match the member's current
    version at the moment the write is attempted — for example, because a renewal
    settle cascade, a refund, or a benefit propagation has since advanced the
    version — the request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Member is created at version=1; settle+verify bumps version. Resigning with the
    stale version=1 must be rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_resign_rejected
    """
    cat, ch, pol, _ = _setup_reference()
    create_resp = api_client.create_member(
        {
            "email": "m@x.com", "full_name": "M",
            "category_id": cat["id"], "home_chapter_id": ch["id"],
            "cycle_policy_id": pol["id"], "joined_at": "2026-05-01T00:00:00Z",
        },
        make_member_headers("registrar"),
    )
    m = validate_success(create_resp, expected_status=201)
    v_init = m["version"]
    mh = make_member_headers(m["id"])
    inv = get_initial_invoice(m["id"], mh)
    settle_invoice(inv["id"], mh)
    verify_member(m["id"])
    resign_resp = api_client.resign_member(
        m["id"], {"expected_member_version": v_init}, mh
    )
    validate_error(resign_resp, ApiErrorId.ERR_STALE_VERSION)
