"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: CardHolder calls are entity-backed by CardHolder and
MerchantUser calls are entity-backed by Merchant. Ownership-gated calls always
use make_cardholder_headers(holder["id"]) / make_merchantuser_headers(
merchant["id"]) built from the real entity ids — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CARD_EXPIRY
from .factories import (
    create_access_grant_payload,
    create_account_payload,
    create_adjustment_payload,
    create_card_holder_payload,
    create_card_payload,
    create_door_zone_payload,
    create_funding_payload,
    create_meal_plan_payload,
    create_merchant_payload,
    create_photo_payload,
    create_replacement_payload,
    create_settlement_payload,
    create_term_payload,
    create_transaction_payload,
)
from .test_users import (
    TEST_USERS,
    make_bursar_headers,
    make_cardholder_headers,
    make_fraud_analyst_headers,
    make_merchantuser_headers,
)

ADMIN = TEST_USERS["card_office_admin_headers"]
DINING = TEST_USERS["dining_manager_headers"]
BURSAR = TEST_USERS["bursar_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
SECURITY = TEST_USERS["security_officer_headers"]
POS = TEST_USERS["pos_headers"]
DOOR = TEST_USERS["door_controller_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Drive the logical clock (PRD: PlatformAdmin-only administrative set)."""
    get_success_data(api_client.set_clock(to_iso8601, PLATFORM))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_holder(**overrides):
    """Register a card holder. Returns the holder."""
    return get_success_data(
        api_client.create_card_holder(create_card_holder_payload(**overrides), ADMIN))


def issue_card(holder_id, expires_at=DEFAULT_CARD_EXPIRY):
    """Issue a card (born PENDING_PHOTO / NOT_SUBMITTED). Returns the card."""
    return get_success_data(
        api_client.issue_card(holder_id, create_card_payload(expires_at=expires_at),
                              ADMIN))


def submit_photo(card_id, holder_id, image_ref=None):
    """Submit a photo as the owning holder. Returns the PhotoSubmission."""
    payload = create_photo_payload()
    if image_ref is not None:
        payload["image_ref"] = image_ref
    return get_success_data(
        api_client.submit_card_photo(card_id, payload,
                                     make_cardholder_headers(holder_id)))


def review_photo(photo_id, decision="APPROVED", rejection_reason=None,
                 reviewer=None):
    """Review a photo as CardOfficeAdmin. Returns the reviewed submission."""
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.review_photo(photo_id, payload, reviewer or ADMIN))


def activate_card(card_id, allow_provisional=False):
    """Activate a PENDING_PHOTO card. Returns the activated card."""
    payload = {"allow_provisional": True} if allow_provisional else {}
    return get_success_data(api_client.activate_card(card_id, payload, ADMIN))


def create_term(**overrides):
    """Create a SCHEDULED term. Returns the term."""
    return get_success_data(
        api_client.create_term(create_term_payload(**overrides), DINING))


def create_plan(**overrides):
    """Create a DRAFT meal plan. Returns the plan."""
    return get_success_data(
        api_client.create_meal_plan(create_meal_plan_payload(**overrides), DINING))


def publish_plan(plan_id):
    return get_success_data(api_client.publish_meal_plan(plan_id, DINING))


def create_and_publish_plan(**overrides):
    plan = create_plan(**overrides)
    publish_plan(plan["id"])
    return plan


def open_term(term_id):
    return get_success_data(api_client.open_term(term_id, DINING))


def advance_term_week(term_id):
    return get_success_data(api_client.advance_term_week(term_id, DINING))


def close_term(term_id):
    return get_success_data(api_client.close_term(term_id, DINING))


def settle_term(term_id):
    return get_success_data(api_client.settle_term(term_id, DINING))


def enroll_holder(holder_id, plan_id, term_id):
    """Assign a plan. Returns the enrollment (ASSIGNED or ACTIVE)."""
    return get_success_data(
        api_client.create_enrollment(
            holder_id, {"plan_id": plan_id, "term_id": term_id}, DINING))


def open_account(holder_id, account_type="CAMPUS_CASH", term_id=None):
    """Open a declining-balance account as BursarOffice. Returns the account."""
    payload = create_account_payload(account_type=account_type)
    if term_id is not None:
        payload["term_id"] = term_id
    return get_success_data(api_client.create_account(holder_id, payload, BURSAR))


def fund_account(account_id, amount_cents, key=None, headers=None):
    """Fund an OPEN account. Returns the FUND LedgerEntry."""
    payload = create_funding_payload(amount_cents)
    if key is not None:
        payload["idempotency_key"] = key
    return get_success_data(
        api_client.fund_account(account_id, payload, headers or BURSAR))


def create_merchant(**overrides):
    """Onboard a merchant (born PENDING_CONTRACT). Returns the merchant."""
    return get_success_data(
        api_client.create_merchant(create_merchant_payload(**overrides), BURSAR))


def activate_merchant(merchant_id):
    return get_success_data(api_client.activate_merchant(merchant_id, BURSAR))


def create_active_merchant(**overrides):
    merchant = create_merchant(**overrides)
    activate_merchant(merchant["id"])
    return merchant


def create_zone(**overrides):
    """Create an ACTIVE door zone. Returns the zone."""
    return get_success_data(
        api_client.create_door_zone(create_door_zone_payload(**overrides), SECURITY))


def create_grant(card_id, zone_id, **overrides):
    """Grant door access for a card. Returns the ACTIVE grant."""
    return get_success_data(
        api_client.create_access_grant(
            card_id, create_access_grant_payload(zone_id, **overrides), SECURITY))


def create_settlement_draft(merchant_id, term_id, headers=None, **overrides):
    """Create a settlement DRAFT (as the owning MerchantUser by default)."""
    hdrs = headers or make_merchantuser_headers(merchant_id)
    return get_success_data(
        api_client.create_settlement(
            merchant_id, create_settlement_payload(term_id, **overrides), hdrs))


# ---------------------------------------------------------------------------
# Tier 2: composite entity chains
# ---------------------------------------------------------------------------

def create_verified_card(holder_id, expires_at=DEFAULT_CARD_EXPIRY):
    """Issue -> photo submit -> approve -> activate. Returns the ACTIVE card
    with photo APPROVED (is_provisional false)."""
    card = issue_card(holder_id, expires_at=expires_at)
    photo = submit_photo(card["id"], holder_id)
    review_photo(photo["id"], decision="APPROVED")
    return activate_card(card["id"])


def create_provisional_card(holder_id, expires_at=DEFAULT_CARD_EXPIRY):
    """Issue -> activate with allow_provisional. Returns the ACTIVE card with
    photo NOT_SUBMITTED (is_provisional true)."""
    card = issue_card(holder_id, expires_at=expires_at)
    return activate_card(card["id"], allow_provisional=True)


def create_holder_with_verified_card(**holder_overrides):
    """Returns (holder, ACTIVE photo-verified card)."""
    holder = create_holder(**holder_overrides)
    card = create_verified_card(holder["id"])
    return holder, card


def create_holder_with_provisional_card(**holder_overrides):
    """Returns (holder, ACTIVE provisional card)."""
    holder = create_holder(**holder_overrides)
    card = create_provisional_card(holder["id"])
    return holder, card


def open_term_with_plan(term_overrides=None, plan_overrides=None):
    """Create + publish a plan, create + open a term.
    Returns (term, plan)."""
    term = create_term(**(term_overrides or {}))
    plan = create_and_publish_plan(**(plan_overrides or {}))
    open_term(term["id"])
    return term, plan


def setup_open_enrollment(term_overrides=None, plan_overrides=None,
                          holder_overrides=None):
    """Open term + published plan + ACTIVE enrollment.
    Returns (holder, term, plan, enrollment)."""
    term, plan = open_term_with_plan(term_overrides, plan_overrides)
    holder = create_holder(**(holder_overrides or {}))
    enrollment = enroll_holder(holder["id"], plan["id"], term["id"])
    return holder, term, plan, enrollment


def setup_enrolled_holder_with_card(term_overrides=None, plan_overrides=None,
                                    holder_overrides=None):
    """Open term + plan + ACTIVE enrollment + verified ACTIVE card.
    Returns (holder, term, plan, enrollment, card)."""
    holder, term, plan, enrollment = setup_open_enrollment(
        term_overrides, plan_overrides, holder_overrides)
    card = create_verified_card(holder["id"])
    return holder, term, plan, enrollment, card


def setup_funded_campus_cash(holder=None, amount_cents=5000, **holder_overrides):
    """Holder + verified card + CAMPUS_CASH account funded with amount_cents.
    Returns (holder, card, account)."""
    if holder is None:
        holder, card = create_holder_with_verified_card(**holder_overrides)
    else:
        card = create_verified_card(holder["id"])
    account = open_account(holder["id"], "CAMPUS_CASH")
    fund_account(account["id"], amount_cents)
    return holder, card, account


# ---------------------------------------------------------------------------
# Tier 3: spending and disputes
# ---------------------------------------------------------------------------

def post_pos_transaction(card_id, tender_type, amount_cents, key=None):
    """Post an on-campus transaction as PointOfSale. Returns raw data."""
    payload = create_transaction_payload(card_id, tender_type, amount_cents)
    if key is not None:
        payload["idempotency_key"] = key
    return get_success_data(api_client.create_transaction(payload, POS))


def post_merchant_transaction(card_id, merchant_id, amount_cents, key=None,
                              tender_type="CAMPUS_CASH"):
    """Post an off-campus transaction as the owning MerchantUser."""
    payload = create_transaction_payload(card_id, tender_type, amount_cents,
                                         merchant_id=merchant_id)
    if key is not None:
        payload["idempotency_key"] = key
    return get_success_data(
        api_client.create_transaction(payload, make_merchantuser_headers(merchant_id)))


def file_dispute(transaction_id, holder_id, reason_code="AMOUNT_MISMATCH"):
    """File a dispute as the owning holder. Returns the OPENED dispute."""
    return get_success_data(
        api_client.create_dispute(transaction_id, {"reason_code": reason_code},
                                  make_cardholder_headers(holder_id)))


def grant_provisional_credit(dispute_id, analyst="fraud-1"):
    return get_success_data(
        api_client.grant_provisional_credit(dispute_id,
                                            make_fraud_analyst_headers(analyst)))


def resolve_dispute(dispute_id, outcome, note="resolved", analyst="fraud-1"):
    return get_success_data(
        api_client.resolve_dispute(dispute_id,
                                   {"outcome": outcome, "resolution_note": note},
                                   make_fraud_analyst_headers(analyst)))


def setup_disputed_purchase(amount_cents=1200, fund_cents=5000,
                            reason_code="AMOUNT_MISMATCH", tender="CAMPUS_CASH"):
    """Holder + verified card + funded account + one purchase + OPENED dispute.
    Returns (holder, card, account, transaction, dispute)."""
    holder, card, account = setup_funded_campus_cash(amount_cents=fund_cents)
    tx = post_pos_transaction(card["id"], tender, amount_cents)
    dispute = file_dispute(tx["id"], holder["id"], reason_code)
    return holder, card, account, tx, dispute


# ---------------------------------------------------------------------------
# Tier 3b: plan changes
# ---------------------------------------------------------------------------

def request_plan_change(enrollment, new_plan_id):
    """Submit a plan change as the owning holder at the enrollment's current
    version. Returns the SUBMITTED PlanChangeRequest."""
    fresh = get_success_data(api_client.get_enrollment(enrollment["id"], DINING))
    holder_id = enrollment["holder_id"]
    return get_success_data(
        api_client.create_change_request(
            enrollment["id"],
            {"new_plan_id": new_plan_id,
             "expected_enrollment_version": fresh["version"]},
            make_cardholder_headers(holder_id)))


# ---------------------------------------------------------------------------
# Tier 4: term closeout / refund chains
# ---------------------------------------------------------------------------

def setup_close_pending_dining_account(spends=(), dining_cents=10000,
                                       price_cents=90000, close_clock=None):
    """Open term + plan + enrollment (dining account auto-funded at
    activation) + optional DINING_DOLLARS purchases + term closed.
    Returns (holder, term, plan, enrollment, dining_account)."""
    term, plan = open_term_with_plan(
        None, {"dining_dollar_allocation_cents": dining_cents,
               "price_cents": price_cents})
    holder = create_holder()
    enrollment = enroll_holder(holder["id"], plan["id"], term["id"])
    if spends:
        card = create_verified_card(holder["id"])
        for amount in spends:
            post_pos_transaction(card["id"], "DINING_DOLLARS", amount)
    set_clock(close_clock or "2026-12-14T00:00:00Z")
    close_term(term["id"])
    from .api_client import api_client as _api
    accounts, _ = validate_paginated(
        _api.list_accounts(BURSAR, {"holder_id": holder["id"],
                                    "term_id": term["id"]}))
    return holder, term, plan, enrollment, accounts[0]


def request_refund(account_id, holder_id):
    """Create a refund request as the owning holder. Returns the request."""
    return get_success_data(
        api_client.create_refund_request(account_id,
                                         make_cardholder_headers(holder_id)))


# ---------------------------------------------------------------------------
# Tier 4b: merchant settlement chains
# ---------------------------------------------------------------------------

def setup_merchant_with_transactions(amounts, commission_bps=275,
                                     commission_mode="PER_TRANSACTION",
                                     tx_clock="2026-09-05T12:00:00Z",
                                     **merchant_overrides):
    """Term + ACTIVE merchant + funded verified card + one merchant
    transaction per amount. Returns (term, merchant, holder, card, account,
    transactions)."""
    term = create_term()
    merchant = create_active_merchant(commission_bps=commission_bps,
                                      commission_mode=commission_mode,
                                      **merchant_overrides)
    holder, card, account = setup_funded_campus_cash(amount_cents=10000)
    set_clock(tx_clock)
    transactions = [
        post_merchant_transaction(card["id"], merchant["id"], amount)
        for amount in amounts
    ]
    return term, merchant, holder, card, account, transactions


def submit_settlement_as_merchant(settlement_id, merchant_id):
    return get_success_data(
        api_client.submit_settlement(settlement_id,
                                     make_merchantuser_headers(merchant_id)))


def setup_submitted_settlement(amounts=(999,), commission_bps=275,
                               commission_mode="PER_TRANSACTION"):
    """Merchant with transactions swept into a SUBMITTED settlement.
    Returns (term, merchant, holder, card, account, transactions,
    settlement)."""
    term, merchant, holder, card, account, txs = \
        setup_merchant_with_transactions(
            amounts, commission_bps=commission_bps, commission_mode=commission_mode)
    settlement = create_settlement_draft(merchant["id"], term["id"])
    submitted = submit_settlement_as_merchant(settlement["id"], merchant["id"])
    return term, merchant, holder, card, account, txs, submitted


# ---------------------------------------------------------------------------
# Tier 5: replacement chains
# ---------------------------------------------------------------------------

def replace_card(card, reason, headers=None, **extra):
    """Replace a card at its current version. Returns the new card."""
    fresh = get_success_data(api_client.get_card(card["id"], ADMIN))
    payload = create_replacement_payload(reason, fresh["version"], **extra)
    return get_success_data(
        api_client.replace_card(card["id"], payload, headers or ADMIN))


def report_card_stolen(card_id, holder_id, police_report_number=None):
    payload = {}
    if police_report_number is not None:
        payload["police_report_number"] = police_report_number
    return get_success_data(
        api_client.report_card_stolen(card_id, payload,
                                      make_cardholder_headers(holder_id)))


def report_card_lost(card_id, holder_id):
    return get_success_data(
        api_client.report_card_lost(card_id, make_cardholder_headers(holder_id)))
