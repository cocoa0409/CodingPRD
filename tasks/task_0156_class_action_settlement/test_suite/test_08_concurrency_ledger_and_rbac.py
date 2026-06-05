"""Cross-cutting layers: optimistic concurrency on the fund, ledger
reverse-reachability and conservation, void-with-no-ledger-impact, immediate
consistency, plus ownership (objection withdraw) and RBAC isolation.

Queue B (Corner): cross_cutting_complexity_layers, consistency_model, errors,
rbac sections.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    fixtures,
    ApiErrorId,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_claimant_headers, make_fund_controller_headers

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
REVIEWER = fixtures.REVIEWER
CONTROLLER = fixtures.CONTROLLER
COURT = fixtures.COURT


# ─── occ_correct_version_post_succeeds ───────────────────────────────────────
def test_occ_correct_version_post_succeeds():
    """PRD §2.9: "A request to post a distribution batch must carry `expected_settlement_version` carrying the client's last observed `version` of the owning settlement. If that value does not equal the settlement's current `version`, the post is rejected with `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_post_succeeds
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA", gross_fund_cents=50000,
        members=[{"email": "m@x.com", "full_name": "M", "claimed_loss_cents": 50000, "recognized_loss_cents": 50000}],
    )
    s_id = ctx["settlement"]["id"]
    version_before = fixtures.get_settlement_version(s_id)
    result = get_success_data(api_client.post_batch(
        ctx["batch"]["id"], version_before, make_fund_controller_headers("controller-1")))
    assert result["status"] == "POSTED"
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["allocated_cents"] == 50000
    assert settlement["version"] == version_before + 1


# ─── occ_stale_version_reconcile_returns_412 ─────────────────────────────────
def test_occ_stale_version_reconcile_returns_412():
    """PRD §2.9: "a request to reconcile a settlement must carry `expected_settlement_version` matching the settlement's current `version`; a mismatch is rejected with the same `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_reconcile_returns_412
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA", gross_fund_cents=50000,
        members=[{"email": "m@x.com", "full_name": "M", "claimed_loss_cents": 50000, "recognized_loss_cents": 50000}],
    )
    s_id = ctx["settlement"]["id"]
    stale_version = fixtures.get_settlement_version(s_id)
    # Post bumps the settlement version, leaving `stale_version` behind.
    get_success_data(api_client.post_batch(
        ctx["batch"]["id"], stale_version, make_fund_controller_headers("controller-1")))
    resp = api_client.reconcile(s_id, stale_version, CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_STALE_SETTLEMENT_VERSION.value)
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["status"] == "DISTRIBUTING"


# ─── ledger_entries_reverse_reachable_after_post ─────────────────────────────
def test_ledger_entries_reverse_reachable_and_balanced_after_post():
    """PRD §2.7: "the ledger accumulates: the gross fund as a positive `FUND_OPEN` entry; the attorney fee and the administration cost as negative `FEE_DEBIT` and `ADMIN_DEBIT` entries; one negative `PAYMENT_DEBIT` per committed payment"

    Design: Corner/cross_cutting_complexity_layers/ledger_entries_reverse_reachable_after_post
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    entries, _ = validate_paginated(api_client.list_ledger_entries(s_id, CONTROLLER))
    types = {e["entry_type"] for e in entries}
    assert {"FUND_OPEN", "FEE_DEBIT", "ADMIN_DEBIT", "PAYMENT_DEBIT"}.issubset(types)
    assert sum(e["amount_cents"] for e in entries) == 0


# ─── cascade_void_does_not_touch_ledger ──────────────────────────────────────
def test_void_does_not_touch_ledger():
    """PRD §3.6: "Voiding is the divergent sibling of posting: it cancels every planned payment in the batch (each `PLANNED` payment becomes `CANCELLED`), sets the batch to the terminal `VOID`, and increments the batch's version — with no ledger impact, no claim transition, and no tax forms."

    Design: Corner/cross_cutting_complexity_layers/cascade_void_does_not_touch_ledger
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA", gross_fund_cents=50000,
        members=[{"email": "m@x.com", "full_name": "M", "claimed_loss_cents": 50000, "recognized_loss_cents": 50000}],
    )
    s_id = ctx["settlement"]["id"]
    result = get_success_data(api_client.void_batch(ctx["batch"]["id"], CONTROLLER))
    assert result["status"] == "VOID"
    bal = get_success_data(api_client.get_ledger_balance(s_id, CONTROLLER))
    assert bal["balance_cents"] == 50000  # only FUND_OPEN, no PAYMENT_DEBIT
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["allocated_cents"] == 0


# ─── post_reflects_all_cascades_in_same_response_immediate ───────────────────
def test_post_response_reflects_posted_total_and_residual_immediately():
    """PRD §3.6: "increases the settlement's `allocated_cents` by the posted total and sets the batch's `posted_total_cents` to its `planned_total_cents`; sets the batch's `residual_after_cents` to the net distributable amount minus the now-updated allocated amount"

    Design: Corner/consistency_model/post_reflects_all_cascades_in_same_response_immediate
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA", gross_fund_cents=50000,
        members=[{"email": "m@x.com", "full_name": "M", "claimed_loss_cents": 50000, "recognized_loss_cents": 50000}],
    )
    s_id = ctx["settlement"]["id"]
    version = fixtures.get_settlement_version(s_id)
    posted = get_success_data(api_client.post_batch(
        ctx["batch"]["id"], version, make_fund_controller_headers("controller-1")))
    assert posted["posted_total_cents"] == 50000
    assert posted["residual_after_cents"] == 0


# ─── objection_withdraw_by_non_owner_forbidden ───────────────────────────────
def test_objection_withdraw_by_non_owner_forbidden():
    """PRD §2.1: "a `Claimant` may only withdraw an objection they themselves filed: the acting claimant's `X-User-ID` must equal the objecting member referenced by the objection."
    PRD §3.5: "only the member who filed the objection (matched by `X-User-ID`) may withdraw it."

    Design: Corner/errors/objection_withdraw_by_non_owner_forbidden
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-03-01T00:00:00Z", objection_deadline="2026-02-01T00:00:00Z",
        cy_pres_floor_cents=0, case_caption="In re Owner")
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    m1 = fixtures.register_member(s_id, full_name="M1", email="m1@x.com", tin_on_file=True)
    m2 = fixtures.register_member(s_id, full_name="M2", email="m2@x.com", tin_on_file=True)
    objection = get_success_data(api_client.create_objection(
        {"settlement_id": s_id, "class_member_id": m1["id"], "grounds": "x"}, ADMINISTRATOR))

    resp = api_client.withdraw_objection(objection["id"], make_claimant_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    refreshed = get_success_data(api_client.get_objection(objection["id"], ADMINISTRATOR))
    assert refreshed["status"] == "FILED"


# ─── rbac: claims_reviewer_cannot_create_settlement ──────────────────────────
def test_claims_reviewer_cannot_create_settlement():
    """PRD §2.1: "When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/claims_reviewer_cannot_create_settlement
    """
    resp = api_client.create_settlement({
        "case_caption": "In re NoPerm",
        "gross_fund_cents": 100000,
        "attorney_fee_cents": 0,
        "admin_cost_cents": 0,
        "distribution_method": "PRO_RATA",
        "claim_filing_deadline": "2026-02-01T00:00:00Z",
        "objection_deadline": "2026-01-20T00:00:00Z",
    }, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac: missing_headers_returns_unauthenticated ───────────────────────────
def test_missing_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing or carrying an unparseable value for either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api_client.list_settlements({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── rbac: peer_role_isolation_controller_cannot_validate_claim ──────────────
def test_peer_role_isolation_controller_cannot_validate_claim():
    """PRD §2.1: "When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/peer_role_isolation_controller_cannot_validate_claim
    """
    settlement, member, claim = fixtures.setup_submitted_claim(claimed_loss_cents=5000)
    resp = api_client.validate_claim(claim["id"], 5000, CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    refreshed = get_success_data(api_client.get_claim(claim["id"], REVIEWER))
    assert refreshed["status"] == "SUBMITTED"
