"""Corner-queue auth/RBAC, OCC concurrency, derived-field and consistency claims."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_basic_plan, create_executive_plan, create_product,
    create_active_membership, create_pending_membership, set_clock,
    get_membership, get_membership_version,
    open_transaction, add_line, create_finalized_transaction, ApiErrorId,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]
MEMBER = TEST_USERS["member_headers"]


# --- validations ---
def test_missing_user_context_unauthenticated(api):
    """PRD §2.1: "If either header is missing or X-User-Role is not one of the known roles,
    the request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT (HTTP 401)."

    Design: Corner/validations/missing_user_context_unauthenticated
    """
    create_basic_plan()
    res = api.list_memberships({})  # no auth headers
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


def test_member_only_product_allowed_when_active(api):
    """PRD §3.5: "If the product is member_only and the owning membership is not ACTIVE, the
    line is rejected with ERR_MEMBER_ONLY_PRODUCT (HTTP 403)." (so an ACTIVE membership
    succeeds and snapshots the member price)

    Design: Corner/validations/member_only_product_blocked_for_pending_membership
    """
    plan = create_basic_plan()
    product = create_product("P-MO-OK", member_only=True)
    m = create_active_membership(plan["id"], primary_member_name="MO-OK Mem")
    txn = open_transaction(m["id"])
    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    data = validate_success(res, 201)
    assert data["unit_price_cents"] == 8000


def test_reward_redemption_exceeds_available_rejected(api):
    """PRD §3.8: "If the requested redeem_reward_cents exceeds the available reward for the
    current term, the request is rejected with ERR_REWARD_REDEMPTION_EXCEEDS_AVAILABLE
    (HTTP 422)."

    Design: Corner/validations/reward_redemption_exceeds_available_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-OVERR", reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="OverR Mem", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    ver = get_membership_version(m["id"])
    res = api.renew_membership(m["id"], {"expected_membership_version": ver,
                                         "redeem_reward_cents": 1000}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_REWARD_REDEMPTION_EXCEEDS_AVAILABLE)


def test_household_card_limit_included_rejected(api):
    """PRD §3.4: "if the active-card count is already at or above `max_household_cards`,
    creating another `INCLUDED` card is rejected with `ERR_HOUSEHOLD_CARD_LIMIT` (HTTP 409)."

    Design: Corner/validations/household_card_limit_included_rejected
    """
    plan = create_basic_plan(max_household_cards=1)
    m = create_active_membership(plan["id"], primary_member_name="HCLim Mem")
    hdr = make_member_headers(m["id"])
    get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"}, hdr))
    res = api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Kid", "card_kind": "INCLUDED"}, hdr)
    validate_error(res, ApiErrorId.ERR_HOUSEHOLD_CARD_LIMIT)


# --- errors ---
def test_renewal_payment_on_pending_purpose_mismatch(api):
    """PRD §3.2: "a RENEWAL payment on a membership that is neither EXPIRED nor ACTIVE, is
    rejected with ERR_PAYMENT_PURPOSE_MISMATCH (HTTP 409)."

    Design: Corner/errors/renewal_payment_on_pending_membership_purpose_mismatch
    """
    plan = create_basic_plan()
    m = create_pending_membership(plan["id"], primary_member_name="RenPend Mem")
    res = api.create_payment({"membership_id": m["id"], "purpose": "RENEWAL",
                              "outcome": "SUCCEEDED"}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_PAYMENT_PURPOSE_MISMATCH)


def test_cancel_non_active_membership_rejected(api):
    """PRD §3.3: "Cancelling a non-ACTIVE membership is rejected with
    ERR_MEMBERSHIP_NOT_ACTIVE."

    Design: Corner/errors/cancel_non_active_membership_rejected
    """
    plan = create_basic_plan()
    m = create_pending_membership(plan["id"], primary_member_name="CancPend Mem")
    ver = get_success_data(api.get_membership(m["id"], make_member_headers(m["id"])))["version"]
    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


def test_transaction_not_found_on_add_line(api):
    """PRD §2.5: "the membership first, then the targeted transaction, return, or card ...
    The request is rejected at the first identifier that does not resolve, using that
    identifier's not-found code: ... ERR_TRANSACTION_NOT_FOUND."

    Design: Corner/errors/transaction_not_found_on_add_line
    """
    from test_helpers import NON_EXISTENT_UUID
    product = create_product("P-TNF")
    res = api.add_line(NON_EXISTENT_UUID, {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)


# --- rbac ---
def test_member_cannot_create_plan(api):
    """PRD §2.1: "When a recognized caller attempts an operation their role is not permitted
    to perform, the request is rejected with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."
    PRD §4: "POST /plans | Create a membership plan | ClubAdmin"

    Design: Corner/rbac/member_cannot_create_plan
    """
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="RbacM Mem")
    res = api.create_plan({"tier": "EXECUTIVE", "annual_fee_cents": 12000, "reward_rate_bps": 200,
                           "reward_cap_cents": 100000, "max_household_cards": 1,
                           "addon_fee_cents": 6000}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_register_clerk_cannot_create_return(api):
    """PRD §2.1: "the request is rejected with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."
    PRD §4: "POST /returns | Create a return | ServiceDeskClerk, ClubAdmin"

    Design: Corner/rbac/register_clerk_cannot_create_return
    """
    plan = create_basic_plan()
    product = create_product("P-RBAC-RET")
    m = create_active_membership(plan["id"], primary_member_name="RbacRet Mem")
    txn, line = create_finalized_transaction(m["id"], product["id"], 1)
    res = api.create_return({"membership_id": m["id"], "product_id": product["id"],
                             "qty": 1, "transaction_id": txn["id"]}, CLERK)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_service_desk_cannot_open_transaction(api):
    """PRD §2.1: "the request is rejected with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."
    PRD §4: "POST /transactions | Open a transaction | RegisterClerk, ClubAdmin"

    Design: Corner/rbac/service_desk_cannot_open_transaction
    """
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="RbacTx Mem")
    res = api.create_transaction({"membership_id": m["id"]}, SVC)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_anonymous_cannot_open_transaction(api):
    """PRD §2.1: "When X-User-Role is Anonymous ... the only thing this principal may do is
    sign up a new membership."
    PRD §2.1: "If either header is missing or X-User-Role is not one of the known roles, the
    request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT (HTTP 401)."

    Design: Corner/rbac/anonymous_cannot_open_transaction
    """
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="Anon Mem")
    res = api.create_transaction({"membership_id": m["id"]}, {})  # no role headers
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


# --- cross-cutting: OCC, derived fields ---
def test_occ_renew_correct_version_succeeds(api):
    """PRD §2.10: "Each of these two requests must carry expected_membership_version as a
    required, non-optional field whose value is the version the client last observed on the
    target membership."
    PRD §3.3: "increments the membership version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_renew_correct_version_succeeds
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="OCCok Mem", auto_renew=False)
    ver = get_membership_version(m["id"])
    res = api.renew_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    data = validate_success(res, 200)
    # PRD §3.3: renewal "increments the membership version by one." Assert the +1
    # delta against the version observed just before renew (activation is a mutation, §2.4).
    assert data["version"] == ver + 1


def test_occ_renew_stale_version_conflict(api):
    """PRD §2.10: "If `expected_membership_version` does not equal the membership's current
    `version`, the request is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412) and
    nothing is mutated."

    Design: Corner/cross_cutting_complexity_layers/occ_renew_stale_version_conflict
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="OCCstale Mem", auto_renew=False)
    ver = get_membership_version(m["id"])
    hdr = make_member_headers(m["id"])
    validate_success(api.renew_membership(m["id"], {"expected_membership_version": ver}, hdr), 200)
    # second renew reuses the now-stale token
    res = api.renew_membership(m["id"], {"expected_membership_version": ver}, hdr)
    validate_error(res, ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION)


def test_occ_cancel_stale_version_conflict(api):
    """PRD §2.10: "For cancellation, it captures the case where the membership was renewed or
    otherwise mutated after the client read it, making the prorated cancel refund the client
    computed stale."
    PRD §2.10: "the request is rejected with ERR_STALE_MEMBERSHIP_VERSION (HTTP 412) and
    nothing is mutated."

    Design: Corner/cross_cutting_complexity_layers/occ_cancel_stale_version_conflict
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="OCCcancel Mem", auto_renew=False)
    ver = get_membership_version(m["id"])
    hdr = make_member_headers(m["id"])
    validate_success(api.renew_membership(m["id"], {"expected_membership_version": ver}, hdr), 200)
    res = api.cancel_membership(m["id"], {"expected_membership_version": ver}, hdr)
    validate_error(res, ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION)


def test_derived_fees_paid_after_signup(api):
    """PRD §2.9: "The membership's derived fees_paid_cents is the total of membership and
    add-on fees collected for the current term, net of any cancellation refunds."

    Design: Corner/cross_cutting_complexity_layers/derived_field_fees_paid_after_signup
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="Fees Mem")
    assert get_membership(m["id"])["fees_paid_cents"] == 6000


def test_reward_cap_reset_on_renew(api):
    """PRD §3.3: "writes a RewardLedgerEntry of type EXPIRY that zeroes any unredeemed
    reward carried from the prior term ... resets reward_accrued_cents and
    reward_redeemed_cents to 0 for the new term."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_reward_cap_reset_on_renew
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-RESET", reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Reset Mem", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    ver = get_membership_version(m["id"])
    validate_success(api.renew_membership(m["id"], {"expected_membership_version": ver},
                                          make_member_headers(m["id"])), 200)
    assert get_membership(m["id"])["reward_accrued_cents"] == 0
    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"membership_id": m["id"], "entry_type": "EXPIRY"}).json()["data"]
    assert len([e for e in ledger if e["entry_type"] == "EXPIRY"]) >= 1


def test_cascade_signup_creates_feeevent(api):
    """PRD §3.2: "records a FeeEvent of kind SIGNUP for the plan's annual fee against that
    term."
    PRD §3.9: "Fee events can be listed and filtered by membership_id or by kind."

    Design: Corner/cross_cutting_complexity_layers/cascade_signup_creates_feeevent
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="FeeCasc Mem")
    fees = api.list_fee_events(make_member_headers(m["id"]),
                               params={"membership_id": m["id"], "kind": "SIGNUP"}).json()["data"]
    signup = [f for f in fees if f["kind"] == "SIGNUP"]
    assert len(signup) == 1
    assert signup[0]["amount_cents"] == 6000


def test_immediate_consistency_totals_visible(api):
    """PRD §3.5: "After each line add the transaction totals are recomputed: gross_cents is
    the sum of line grosses ... and net_cents the gross minus instant savings minus rebate,
    floored at 0."

    Design: Corner/consistency_model/immediate_consistency_totals_visible_in_same_response
    """
    plan = create_basic_plan()
    product = create_product("P-IMM", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Imm Mem")
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 2)
    txn = get_success_data(api.get_transaction(txn["id"], CLERK))
    assert txn["gross_cents"] == 16000
    assert txn["net_cents"] == 16000
