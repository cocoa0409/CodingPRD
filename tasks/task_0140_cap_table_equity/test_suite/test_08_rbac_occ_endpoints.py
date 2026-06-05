"""RBAC enforcement, optimistic-concurrency (OCC) version checks, Form 3921
generation/filtering, and immediate-consistency reads.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    build_user_headers,
    TEST_USERS,
    make_stakeholder_headers,
    make_board_approver_headers,
    create_cap_table,
    create_security_class,
    create_shareholder,
    create_effective_valuation,
    create_option_pool,
    create_grant,
    create_active_grant,
    create_outstanding_note,
    create_safe_note,
    setup_settled_exercise,
    issue_shares,
    set_clock,
    api_client,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ============================================================================
# Corner/rbac/stakeholder_cannot_approve_grant_forbidden
# ============================================================================

def test_stakeholder_cannot_approve_grant(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    PRD §4: grant approval is authorized for BoardApprover only. A Stakeholder
    calling approve → ERR_FORBIDDEN.

    Design: Corner/rbac/stakeholder_cannot_approve_grant_forbidden
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@rb.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=10_000)
    grant = create_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                         share_count=1000, strike_price_cents=100,
                         grant_date="2025-01-01T00:00:00Z")
    resp = api.approve_option_grant(grant["id"], make_stakeholder_headers(sh["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ============================================================================
# Corner/rbac/auditor_cannot_create_cap_table_forbidden
# ============================================================================

def test_auditor_cannot_create_cap_table(api):
    """PRD §2.1: "An `Auditor` is a read-only compliance reviewer." PRD §4:
    `POST /cap-tables` is authorized for Administrator only; "When the headers are
    well-formed but the declared role is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_create_cap_table_forbidden
    """
    resp = api.create_cap_table({"company_name": "Nope", "authorized_shares": 100}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ============================================================================
# Corner/rbac/missing_headers_returns_unauthenticated
# ============================================================================

def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Request with an unknown role → ERR_UNAUTHENTICATED, before authorization.

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    bad_headers = {"X-User-ID": "x", "X-User-Role": "Nobody", "Content-Type": "application/json"}
    resp = api.list_cap_tables(bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ============================================================================
# Corner/cross_cutting_complexity_layers/occ_pool_refresh_stale_version
# ============================================================================

def test_pool_refresh_with_stale_version_rejected(api):
    """PRD §2.6: "Refreshing an option pool requires `expected_pool_version` to
    match the pool's current `version`. A grant approval that exhausts the pool
    bumps its version, so a refresh carrying a stale value would top up against an
    outdated `available_shares` figure and is rejected."

    Observe pool v0, approve a grant that exhausts it (version bumps), refresh
    with stale v0 → ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_pool_refresh_stale_version
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@op.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=1000)
    pool_v0 = pool["version"]
    create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                        share_count=1000, strike_price_cents=100,
                        grant_date="2025-01-01T00:00:00Z")
    resp = api.refresh_option_pool(
        pool["id"], {"expected_pool_version": pool_v0, "refresh_increment_shares": 5000}, APPROVER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ============================================================================
# Corner/cross_cutting_complexity_layers/occ_note_convert_stale_version
# ============================================================================

def test_note_convert_with_stale_version_rejected(api):
    """PRD §2.6: "Converting a SAFE/note requires `expected_note_version` to match
    the note's current `version`. A revise or execute on the same note
    legitimately bumps its version, so a converter carrying a stale value is
    operating on outdated conversion terms and is rejected."

    Observe note version after submit, revise (version bumps), resubmit+execute,
    convert with the stale pre-revise version → ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_note_convert_stale_version
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    pref = create_security_class(ct["id"], name="Series A", class_type="PREFERRED",
                                 original_issue_price_cents=1000,
                                 liquidation_pref_multiple=1.0, participating=False)
    ang = create_shareholder(ct["id"], legal_name="Angel", holder_type="INVESTOR", email="a@on.com")
    note = create_safe_note(ct["id"], ang["id"], instrument_type="SAFE",
                            principal_cents=1_000_000, valuation_cap_cents=0, discount_pct=0.20)
    get_success_data(api.submit_terms_safe_note(note["id"], ADMIN))
    note_stale = get_success_data(api.get_safe_note(note["id"], APPROVER))
    stale_version = note_stale["version"]
    get_success_data(api.revise_safe_note(note["id"], ADMIN))
    get_success_data(api.submit_terms_safe_note(note["id"], ADMIN))
    get_success_data(api.execute_safe_note(note["id"], APPROVER))
    resp = api.convert_safe_note(
        note["id"], {"target_class_id": pref["id"], "expected_note_version": stale_version}, APPROVER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ============================================================================
# Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_mutation
# ============================================================================

def test_captable_version_increments_by_one_per_mutation(api):
    """PRD §2.4: "`version` (an integer that starts at 1 on creation and
    increments by one on every mutation)." PRD §3.1: "Each of these three
    transitions increments the cap table's `version`."

    Fresh table v==1; lock → 2; unlock → 3.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_mutation
    """
    ct = validate_success(api.create_cap_table(
        {"company_name": "VerCo", "authorized_shares": 1_000_000}, ADMIN), 201)
    assert ct["version"] == 1, f"expected v1, got {ct['version']}"
    locked = validate_success(api.lock_cap_table(
        ct["id"], {"expected_cap_table_version": ct["version"]}, APPROVER), 200)
    assert locked["version"] == 2, f"expected v2 after lock, got {locked['version']}"
    unlocked = validate_success(api.unlock_cap_table(
        ct["id"], {"expected_cap_table_version": locked["version"]}, APPROVER), 200)
    assert unlocked["version"] == 3, f"expected v3 after unlock, got {unlocked['version']}"


# ============================================================================
# Corner/endpoints/form_3921_generated_for_settled_us_taxpayer_exercise
# ============================================================================

def test_form_3921_generated_for_settled_exercise(api):
    """PRD §3.9: "The form is an immutable record derived from the exercise's
    grant and valuation: it captures the owning `cap_table_id`, the `exercise_id`,
    the reported `shareholder_id`, the `tax_year` ..., the `exercise_fmv_cents`
    (the per-share fair-market value from the grant's valuation), the
    `strike_price_cents` copied from the grant, and the `shares_transferred` the
    exercise minted."

    Settled exercise of 1000, valuation fmv 100, grant strike 200 (409A-compliant:
    PRD §3.6 requires strike >= the grant valuation's fmv), US taxpayer →
    201 Form3921 with shares_transferred 1000, exercise_fmv_cents 100 (copied from
    the grant's valuation), strike_price_cents 200 (copied from the grant). The two
    values are kept distinct so the copy of each source field is independently checked.

    Design: Corner/endpoints/form_3921_generated_for_settled_us_taxpayer_exercise
    """
    env = setup_settled_exercise(share_count=1000, fmv_per_share_cents=100,
                                 strike_price_cents=200, clock="2026-06-01T00:00:00Z")
    data = validate_success(api.generate_form_3921(env["exercise"]["id"], ADMIN), 201)
    assert data["shares_transferred"] == 1000, f"got {data['shares_transferred']}"
    assert data["exercise_fmv_cents"] == 100, f"got {data['exercise_fmv_cents']}"
    assert data["strike_price_cents"] == 200, f"got {data['strike_price_cents']}"


# ============================================================================
# Corner/endpoints/form_3921_filtered_list_by_exercise
# ============================================================================

def test_form_3921_filtered_list_by_exercise(api):
    """PRD §3.9: "Form 3921 records can be listed and filtered by `cap_table_id`,
    `exercise_id`, or `shareholder_id`."

    Generate one Form3921, then GET /forms-3921?exercise_id={id} → one row whose
    exercise_id matches.

    Design: Corner/endpoints/form_3921_filtered_list_by_exercise
    """
    env = setup_settled_exercise(share_count=1000, fmv_per_share_cents=100,
                                 strike_price_cents=100, clock="2026-06-01T00:00:00Z")
    get_success_data(api.generate_form_3921(env["exercise"]["id"], ADMIN))
    resp = api.list_forms_3921(AUDITOR, params={"exercise_id": env["exercise"]["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 form, got {len(data)}"
    assert data[0]["exercise_id"] == env["exercise"]["id"], (
        f"row exercise_id mismatch: {data[0]['exercise_id']}"
    )


# ============================================================================
# Corner/consistency_model/immediate_consistency_issued_shares_in_same_response
# ============================================================================

def test_issued_shares_immediately_reflected_after_issuance(api):
    """PRD §2.8: "`issued_shares` is defined as the sum of `shares_outstanding`
    across every security class on the cap table, and it is recomputed on every
    issuance, every exercise settlement or reversal, and every note conversion."
    PRD §2.4: "Fetching a cap table recomputes its `issued_shares` and
    `fully_diluted_shares` before returning."

    Issue 250 shares, then GET the cap table → issued_shares == 250 immediately.

    Design: Corner/consistency_model/immediate_consistency_issued_shares_in_same_response
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Fnd", holder_type="FOUNDER", email="f@im.com")
    issue_shares(ct["id"], common["id"], sh["id"], 250, price_paid_cents=0)
    data = validate_success(api.get_cap_table(ct["id"], ADMIN), 200)
    assert data["issued_shares"] == 250, f"expected 250 immediately, got {data['issued_shares']}"
