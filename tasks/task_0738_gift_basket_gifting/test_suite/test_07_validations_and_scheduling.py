"""Validation corners not already exercised by Difficulty-queue instances:
duplicate-email partial success, mixed accept/reject inventory partial success,
segregation-of-duties (budget and proof) in isolation, scheduled_send_date past,
hard-cap budget exceeded even under the approval threshold, and
ERR_EMPTY_RECIPIENT_LIST in isolation.

Plus complexity-layers: OCC stale-version (branding + order after PATCH),
clock-driven recurring-series generation, perishable-reservation auto-expiry,
and atomic rollback of a failed auto-approval continuation.

Plus one RBAC corner (missing auth headers, wrong role).

Notes on skips:
- Corner/roles/account_manager_cannot_act_on_a_different_accounts_order is
  SKIPPED under the PRD-first Core rule: PRD §2.1 states that ownership is
  compared against X-User-ID but does not uniquely name the error id fired on
  mismatch (ERR_FORBIDDEN_ROLE vs an existence-style error are both
  PRD-consistent readings).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, factories, fixtures,
)
from test_helpers.test_users import (
    TEST_USERS, make_account_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FIN = TEST_USERS["finance_approver_headers"]
PROOF = TEST_USERS["proof_approver_headers"]
WH = TEST_USERS["warehouse_ops_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_duplicate_recipient_email_within_same_import_batch_rejected(api):
    """PRD §3.4: "a row's email may not duplicate another ACCEPTED row's email
    within the same import batch or against the order's already-existing
    recipients — a collision is rejected with ERR_DUPLICATE_RECIPIENT_EMAIL
    (422) and only that row is dropped"

    Design: Corner/validations/duplicate_recipient_email_within_same_import_batch_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Sticker Basket", base_price_cents=1500))
    order = fixtures.create_order(
        api, account=base["account"], template_id=base["template"]["id"],
        occasion="CUSTOM")
    hdrs = make_account_manager_headers(base["account"]["id"])
    rows = validate_success(api.import_recipients(
        order["id"],
        {"rows": [
            factories.recipient_row(full_name="First Copy",
                                    email="dup@example.com", quantity=1),
            factories.recipient_row(full_name="Second Copy",
                                    email="dup@example.com", quantity=1),
            factories.recipient_row(full_name="Unrelated",
                                    email="unique@example.com", quantity=1),
        ]}, hdrs), 201)
    assert rows[0]["import_row_status"] == "ACCEPTED"
    assert rows[1]["import_row_status"] == "REJECTED"
    assert rows[2]["import_row_status"] == "ACCEPTED"


def test_import_batch_partial_success_mixed_accept_reject(api):
    """PRD §3.4: "each row is evaluated independently and is persisted as a
    Recipient whose import_row_status is either ACCEPTED or REJECTED — a
    rejected row never contributes to recipient counts, cost calculations, or
    any downstream cascade."
    PRD §3.4: "for every row that is ACCEPTED, the system creates the Recipient
    plus one InventoryReservation per SKU in the template's composition"

    Design: Corner/validations/import_batch_partial_success_mixed_accept_reject
    """
    account = fixtures.create_account(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000)
    sku = fixtures.create_sku(api, name="Limited Gadget", unit_cost_cents=400,
                              is_perishable=False, on_hand_qty=3)
    template = fixtures.create_template(
        api, name="Limited Basket", base_price_cents=2500,
        category="CORPORATE_WELCOME", sku_id=sku["id"])
    order = fixtures.create_order(
        api, account=account, template_id=template["id"], occasion="CUSTOM")
    hdrs = make_account_manager_headers(account["id"])
    rows = validate_success(api.import_recipients(
        order["id"],
        {"rows": [
            factories.recipient_row(full_name="First Two",
                                    email="first2@example.com", quantity=2),
            factories.recipient_row(full_name="Second Two",
                                    email="second2@example.com", quantity=2),
        ]}, hdrs), 201)
    # First row consumes 2 of 3 units → ACCEPTED; second needs 2 with only 1
    # remaining → REJECTED. Overall 201 because accepted_rows > 0.
    assert rows[0]["import_row_status"] == "ACCEPTED"
    assert rows[1]["import_row_status"] == "REJECTED"


def test_self_approval_forbidden_clean_single_failure(api):
    """PRD §2.8: "BudgetApproval.requested_by_user_id — populated from the
    requested_by_user_id supplied when the order was submitted for approval —
    must differ from the deciding FinanceApprover's submitted
    approver_user_id; a match is rejected with ERR_SELF_APPROVAL_FORBIDDEN
    (403)."

    Design: Corner/validations/self_approval_forbidden_clean_single_failure
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000,
        template_kwargs=dict(name="Diary Basket", base_price_cents=4000))
    p = fixtures.setup_pending_approval_order(
        api, base=base,
        rows=[factories.recipient_row(email="sa@example.com", quantity=2)],
        requested_by_user_id="emp-req-25")
    resp = api.budget_decision(
        p["order"]["id"],
        factories.budget_decision_payload(
            decision="APPROVE", approver_user_id="emp-req-25",
            station_id=base["station"]["id"],
            scheduled_date="2026-03-04T00:00:00Z"),
        FIN)
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value)


def test_self_proof_approval_forbidden_clean_single_failure(api):
    """PRD §2.8: "MessageProof.submitted_by_user_id — populated from the
    submitted_by_user_id supplied when the message was submitted for proof —
    must differ from the deciding ProofApprover's submitted decided_by_user_id;
    a match is rejected with ERR_SELF_PROOF_APPROVAL_FORBIDDEN (403)."

    Design: Corner/validations/self_proof_approval_forbidden_clean_single_failure
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Bookmark Basket", category="CLIENT_APPRECIATION",
                             base_price_cents=2000))
    _, rec = fixtures.setup_order_with_recipients(
        api, account=base["account"], template_id=base["template"]["id"],
        rows=[factories.recipient_row(email="sp@example.com", quantity=1)],
        occasion="THANK_YOU")
    proof = fixtures.submit_message_proof(
        api, account_id=base["account"]["id"], recipient_id=rec[0]["id"],
        message_text="Well done!", submitted_by_user_id="emp-msg-8")
    resp = api.decide_message_proof(
        proof["id"],
        factories.proof_decision_payload(
            decision="APPROVE", decided_by_user_id="emp-msg-8"),
        PROOF)
    validate_error(resp, ApiErrorId.ERR_SELF_PROOF_APPROVAL_FORBIDDEN.value)


def test_scheduled_send_date_in_the_past_rejected(api):
    """PRD §3.4: "If scheduled_send_date is supplied, it must be strictly later
    than the server's current logical time, or the request is rejected with
    ERR_SCHEDULED_SEND_IN_PAST (422)"

    Design: Corner/validations/scheduled_send_date_in_the_past_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Ornament Basket", category="HOLIDAY",
                             base_price_cents=3000))
    hdrs = make_account_manager_headers(base["account"]["id"])
    payload = factories.create_order_payload(
        template_id=base["template"]["id"], occasion="HOLIDAY",
        scheduled_send_date="2026-02-28T00:00:00Z",
        expected_corporate_account_version=base["account"]["version"])
    resp = api.create_order(base["account"]["id"], payload, hdrs)
    validate_error(resp, ApiErrorId.ERR_SCHEDULED_SEND_IN_PAST.value)


def test_budget_hard_cap_exceeded_even_when_under_approval_threshold(api):
    """PRD §3.4: "A separate, independent hard-cap flag notes whether
    ytd_spend_cents plus this total_cost_cents would exceed monthly_budget_cents;
    that flag is not enforced at submission time but is re-checked at the moment
    of approval (manual or automatic alike) as the ERR_BUDGET_EXCEEDED (402)
    check described above — meaning a request can auto-approve on the threshold
    check yet still be rejected on the hard-cap check if account spending has
    moved in between."

    Design: Corner/validations/budget_hard_cap_exceeded_even_when_under_approval_threshold
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=45_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Tumbler Basket", base_price_cents=4000))
    # Seed: 10 × 4000 = 40000 auto-approved (< 1000000 threshold, < 45000 hard cap).
    # Since requires_approval=false, this triggers the auto-approval continuation
    # which requires station_id/scheduled_date on the submit payload.
    seed_order, _ = fixtures.setup_order_with_recipients(
        api, account=base["account"], template_id=base["template"]["id"],
        rows=[factories.recipient_row(email="seed@example.com", quantity=10)],
        occasion="ONBOARDING")
    fixtures.submit_for_approval(
        api, account_id=base["account"]["id"], order_id=seed_order["id"],
        requested_by_user_id="emp-req-26",
        station_id=base["station"]["id"],
        scheduled_date="2026-03-04T00:00:00Z")
    # Refresh account version (bumped by the seed order create).
    account = fixtures.get_account(api, account_id=base["account"]["id"])
    base["account"] = account
    # New order: 2 × 4000 = 8000 (still under approval_threshold),
    # but ytd 40000 + 8000 = 48000 > monthly_budget 45000 → ERR_BUDGET_EXCEEDED.
    order = fixtures.create_order(
        api, account=account, template_id=base["template"]["id"],
        occasion="ONBOARDING")
    fixtures.import_recipients(
        api, account_id=account["id"], order_id=order["id"],
        rows=[factories.recipient_row(email="hc@example.com", quantity=2)])
    hdrs = make_account_manager_headers(account["id"])
    resp = api.submit_for_approval(
        order["id"],
        factories.submit_for_approval_payload(
            requested_by_user_id="emp-req-27",
            station_id=base["station"]["id"],
            scheduled_date="2026-03-04T00:00:00Z"),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)


def test_empty_recipient_list_clean_single_failure(api):
    """PRD §3.4: "It further requires at least one ACCEPTED recipient on the
    order, or ERR_EMPTY_RECIPIENT_LIST (422)"

    Design: Corner/validations/empty_recipient_list_clean_single_failure
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Notes Basket", base_price_cents=1500))
    order = fixtures.create_order(
        api, account=base["account"], template_id=base["template"]["id"],
        occasion="CUSTOM")
    hdrs = make_account_manager_headers(base["account"]["id"])
    resp = api.submit_for_approval(
        order["id"],
        factories.submit_for_approval_payload(requested_by_user_id="emp-req-28"),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_EMPTY_RECIPIENT_LIST.value)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting an X-User-Role
    value outside this set, is rejected with ERR_UNAUTHENTICATED (401) before
    any other processing occurs."

    Design: Corner/roles/missing_auth_headers_returns_401
    """
    resp = api.list_orders(ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_wrong_role_forbidden_from_exclusive_operation(api):
    """PRD §2.1: "A request from an authenticated but unpermitted role for the
    target operation is rejected with ERR_FORBIDDEN_ROLE (403)."

    Design: Corner/roles/wrong_role_forbidden_from_exclusive_operation
    """
    payload = factories.create_template_payload(
        name="Not Allowed", category="CUSTOM", base_price_cents=1000,
        is_perishable=False, components=[])
    resp = api.create_template(payload, WH)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_occ_stale_version_rejected_on_branding_profile_create(api):
    """PRD §2.5: "Creating a BrandingProfile (via the account's branding-profile
    creation endpoint) must carry expected_corporate_account_version, matching
    the target CorporateAccount's current version at the instant of the write.
    If another writer has advanced the account's version since the client last
    read it — for example, because a different branding profile was already
    created for the account since then — the create is rejected with
    ERR_STALE_VERSION (HTTP 412), preventing the client from building a profile
    against a view of the account it no longer accurately reflects."

    Design: Corner/complexity_layers/occ_stale_version_rejected_on_branding_profile_create
    """
    account = fixtures.create_account(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000)
    hdrs = make_account_manager_headers(account["id"])
    # First create succeeds and bumps version.
    validate_success(api.create_branding_profile(
        account["id"],
        factories.create_branding_profile_payload(
            name="First Kit", accent_color="#111111", card_stock="MATTE",
            expected_corporate_account_version=account["version"]),
        hdrs), 201)
    # Second create with the ORIGINAL (now stale) version is rejected.
    resp = api.create_branding_profile(
        account["id"],
        factories.create_branding_profile_payload(
            name="Second Kit", accent_color="#222222", card_stock="GLOSS",
            expected_corporate_account_version=account["version"]),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_stale_version_rejected_on_order_create_after_budget_patch(api):
    """PRD §2.5: "Creating a CorporateOrder (via the account's order creation
    endpoint) is guarded the identical way: the request body must carry
    expected_corporate_account_version matching the account's current version,
    and a mismatch is rejected with the same ERR_STALE_VERSION (HTTP 412)."
    PRD §2.5: "The scenario this protects against is a budget adjustment: if
    the account's monthly budget or approval threshold was just changed through
    the account's budget-update endpoint (which itself bumps
    CorporateAccount.version, per §2.4), an order-creation request holding a
    stale version number is proceeding against outdated affordability
    assumptions and is rejected rather than allowed to silently use the old
    policy."

    Design: Corner/complexity_layers/occ_stale_version_rejected_on_order_create_after_budget_patch
    """
    account = fixtures.create_account(
        api, monthly_budget_cents=500_000, approval_threshold_cents=500_000)
    sku = fixtures.create_sku(api, name="Occ Item", unit_cost_cents=200,
                              is_perishable=False, on_hand_qty=100)
    template = fixtures.create_template(
        api, name="Occ Basket", base_price_cents=2000, category="CUSTOM",
        sku_id=sku["id"])
    # PATCH bumps account version.
    validate_success(api.update_account_budget(
        account["id"], {"monthly_budget_cents": 600_000}, ADMIN))
    # Order create carrying the original (now stale) version is rejected.
    hdrs = make_account_manager_headers(account["id"])
    payload = factories.create_order_payload(
        template_id=template["id"], occasion="CUSTOM",
        expected_corporate_account_version=account["version"])
    resp = api.create_order(account["id"], payload, hdrs)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_recurring_series_auto_generates_order_when_clock_passes_next_run_date(api):
    """PRD §3.9: "Whenever the logical clock is advanced past a series's
    next_run_date while that series is still active, the system automatically
    clones the source order's template_id, branding_profile_id, and occasion
    into a brand-new CorporateOrder — starting DRAFT, with no recipients yet
    imported — under the same corporate account; it records that new order's
    id onto last_generated_order_id (a system-set cache, not itself a
    reverse-reachability foreign key) and advances next_run_date by another
    interval_days."

    Design: Corner/complexity_layers/recurring_series_auto_generates_order_when_clock_passes_next_run_date
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Recur Basket", base_price_cents=3000))
    source_order = fixtures.create_order(
        api, account=base["account"], template_id=base["template"]["id"],
        occasion="ONBOARDING")
    hdrs = make_account_manager_headers(base["account"]["id"])
    series = validate_success(api.create_recurring_series(
        base["account"]["id"],
        {"source_order_id": source_order["id"], "interval_days": 30},
        hdrs), 201)
    # Clock advance past next_run_date triggers generation.
    fixtures.set_clock(api, to_iso8601="2026-04-01T00:00:00Z")
    got = validate_success(api.get_recurring_series(series["id"], ADMIN))
    assert got["last_generated_order_id"] is not None, \
        "system-set last_generated_order_id must record the new order"
    assert got["last_generated_order_id"] != source_order["id"], \
        "the generated order is a NEW CorporateOrder, not the source"


def test_perishable_reservation_auto_expires_when_clock_passes_expires_at(api):
    """PRD §3.9: "The same clock-advance call also sweeps every reservation
    still RESERVED whose expires_at has now passed to EXPIRED"

    Design: Corner/complexity_layers/perishable_reservation_auto_expires_when_clock_passes_expires_at
    """
    account = fixtures.create_account(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000)
    sku = fixtures.create_sku(
        api, name="Fresh Berries", unit_cost_cents=250,
        is_perishable=True, shelf_life_days=2, on_hand_qty=50)
    template = fixtures.create_template(
        api, name="Berry Basket", category="CLIENT_APPRECIATION",
        base_price_cents=3500, is_perishable=True, shelf_life_days=2,
        sku_id=sku["id"])
    order, rec = fixtures.setup_order_with_recipients(
        api, account=account, template_id=template["id"],
        rows=[factories.recipient_row(email="exp@example.com", quantity=3)],
        occasion="THANK_YOU")
    reservation = fixtures.find_reservation_for_recipient(
        api, recipient_id=rec[0]["id"])
    # Reservation created at clock default 2026-03-01 + shelf 2 days → expires
    # 2026-03-03. Advance clock past that.
    fixtures.set_clock(api, to_iso8601="2026-03-04T00:00:00Z")
    got = validate_success(
        api.get_inventory_reservation(reservation["id"], WH))
    assert got["status"] == "EXPIRED"


class TestFailedAutoApprovalRollsBackAtomically:
    """A submit-for-approval whose requires_approval resolves to false but whose
    auto-approval continuation itself fails a precondition must leave the order
    in DRAFT with NO BudgetApproval row persisted."""

    def test_bogus_station_id_returns_fulfillment_ref_not_found(self, api):
        """PRD §3.4: "the named station_id must resolve to an existing
        AssemblyStation (ERR_FULFILLMENT_REF_NOT_FOUND, 404)"

        Design: Corner/consistency_model/failed_auto_approval_rolls_back_atomically_leaving_order_draft
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Small Basket", category="CUSTOM",
                                 base_price_cents=1000))
        order = fixtures.create_order(
            api, account=base["account"], template_id=base["template"]["id"],
            occasion="CUSTOM")
        fixtures.import_recipients(
            api, account_id=base["account"]["id"], order_id=order["id"],
            rows=[factories.recipient_row(email="atomic@example.com", quantity=1)])
        hdrs = make_account_manager_headers(base["account"]["id"])
        resp = api.submit_for_approval(
            order["id"],
            factories.submit_for_approval_payload(
                requested_by_user_id="emp-req-29",
                station_id="00000000-0000-4000-8000-000000000008",
                scheduled_date="2026-03-04T00:00:00Z"),
            hdrs)
        validate_error(resp, ApiErrorId.ERR_FULFILLMENT_REF_NOT_FOUND.value)

    def test_order_remains_draft_and_no_budget_approval_row(self, api):
        """PRD §3.4: "If any of these fail during the auto-fire, the entire
        submit-for-approval call fails as one atomic unit: the order is left
        exactly as it was, still DRAFT, and — critically — no BudgetApproval
        row is persisted at all, not even the PENDING one that a normal
        (non-auto-approving) submission would have created."

        Design: Corner/consistency_model/failed_auto_approval_rolls_back_atomically_leaving_order_draft
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Small Basket 2", category="CUSTOM",
                                 base_price_cents=1000))
        order = fixtures.create_order(
            api, account=base["account"], template_id=base["template"]["id"],
            occasion="CUSTOM")
        fixtures.import_recipients(
            api, account_id=base["account"]["id"], order_id=order["id"],
            rows=[factories.recipient_row(email="atomic2@example.com", quantity=1)])
        hdrs = make_account_manager_headers(base["account"]["id"])
        api.submit_for_approval(
            order["id"],
            factories.submit_for_approval_payload(
                requested_by_user_id="emp-req-29b",
                station_id="00000000-0000-4000-8000-000000000009",
                scheduled_date="2026-03-04T00:00:00Z"),
            hdrs)
        after = validate_success(api.get_order(order["id"], ADMIN))
        assert after["approval_status"] == "DRAFT"
        data, _ = validate_paginated(api.list_budget_approvals(order["id"], ADMIN))
        assert data == [], "no BudgetApproval row persisted by the failed attempt"
