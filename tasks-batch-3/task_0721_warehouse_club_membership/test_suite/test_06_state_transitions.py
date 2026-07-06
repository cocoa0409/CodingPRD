"""Corner-queue state-machine valid/invalid transitions."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_basic_plan, create_product,
    create_active_membership, create_pending_membership, set_clock,
    get_membership, get_membership_version,
    create_finalized_transaction, ApiErrorId,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]
MEMBER = TEST_USERS["member_headers"]


def test_signup_payment_activates_membership(api):
    """PRD §3.2: "A SUCCEEDED payment with purpose SIGNUP against a membership in
    PENDING_PAYMENT drives the system activation that moves it to ACTIVE: the server sets
    term_start_utc to the current clock instant and term_end_utc to 365 days later, records
    a FeeEvent of kind SIGNUP for the plan's annual fee against that term."

    Design: Corner/state_machines/signup_payment_activates_membership
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_pending_membership(plan["id"], primary_member_name="Act Mem")
    res = api.create_payment({"membership_id": m["id"], "purpose": "SIGNUP",
                              "outcome": "SUCCEEDED"}, make_member_headers(m["id"]))
    validate_success(res, 201)
    assert get_membership(m["id"])["status"] == "ACTIVE"
    fees = api.list_fee_events(make_member_headers(m["id"]),
                               params={"membership_id": m["id"], "kind": "SIGNUP"}).json()["data"]
    signup = [f for f in fees if f["kind"] == "SIGNUP"]
    assert signup[0]["amount_cents"] == 6000


def test_transaction_starts_open_with_zero_totals(api):
    """PRD §3.5: "The transaction starts in OPEN status with zeroed totals and tracks its
    owning membership_id and computed gross_cents, instant_savings_cents, rebate_cents,
    net_cents, reward_accrued_cents, and finalized_at_utc."

    Design: Corner/state_machines/transaction_starts_open
    """
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="Open Mem")
    res = api.create_transaction({"membership_id": m["id"]}, CLERK)
    data = validate_success(res, 201)
    assert data["status"] == "OPEN"
    assert data["gross_cents"] == 0
    assert data["net_cents"] == 0


def test_void_open_transaction_no_ledger(api):
    """PRD §3.6: "A RegisterClerk may instead void an OPEN transaction, moving it from OPEN
    to VOIDED. A void writes no ledger entries because the transaction was never
    finalized."

    Design: Corner/state_machines/void_open_transaction_no_ledger
    """
    plan = create_basic_plan()
    product = create_product("P-VOID")
    m = create_active_membership(plan["id"], primary_member_name="Void Mem")
    txn = get_success_data(api.create_transaction({"membership_id": m["id"]}, CLERK))
    get_success_data(api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK))
    res = api.void_transaction(txn["id"], CLERK)
    data = validate_success(res, 200)
    assert data["status"] == "VOIDED"
    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"source_transaction_id": txn["id"]}).json()["data"]
    assert len(ledger) == 0


def test_revoke_active_household_card(api):
    """PRD §3.4: "A card may be revoked explicitly by the member while it is ACTIVE, moving
    it from ACTIVE to REVOKED and recomputing the membership's household_card_count."

    Design: Corner/state_machines/revoke_active_household_card
    """
    plan = create_basic_plan(max_household_cards=1)
    m = create_active_membership(plan["id"], primary_member_name="Rev Mem")
    hdr = make_member_headers(m["id"])
    card = get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"}, hdr))
    res = api.revoke_household_card(card["id"], hdr)
    data = validate_success(res, 200)
    assert data["status"] == "REVOKED"
    assert get_membership(m["id"])["household_card_count"] == 0


def test_auto_renew_keeps_active_across_boundary(api):
    """PRD §3.3: "If auto_renew is true and a SUCCEEDED RENEWAL payment exists for the new
    term, the membership stays ACTIVE across the boundary with the same side effects as a
    manual renewal."

    Design: Corner/state_machines/auto_renew_keeps_active_across_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="AutoR Mem", auto_renew=True)
    hdr = make_member_headers(m["id"])
    get_success_data(api.create_payment({"membership_id": m["id"], "purpose": "RENEWAL",
                                         "outcome": "SUCCEEDED"}, hdr))
    set_clock("2027-04-01T00:00:00Z")
    assert get_membership(m["id"])["status"] == "ACTIVE"


def test_lapse_expired_cascade_revokes_cards(api):
    """PRD §3.3: "If auto_renew is false, the membership lapses: it moves from ACTIVE to
    EXPIRED, a RewardLedgerEntry of type EXPIRY zeroes the term's unredeemed reward,
    reward_accrued_cents is recomputed to 0, and every household card still in ACTIVE status
    cascades to REVOKED."

    Design: Corner/state_machines/lapse_expired_cascade_revokes_cards
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="Lapse Mem", auto_renew=False)
    hdr = make_member_headers(m["id"])
    card = get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"}, hdr))
    set_clock("2027-04-01T00:00:00Z")
    assert get_membership(m["id"])["status"] == "EXPIRED"
    assert get_success_data(api.get_household_card(card["id"], hdr))["status"] == "REVOKED"
    assert get_membership(m["id"])["reward_accrued_cents"] == 0


# --- Invalid transitions ---
def test_renew_non_active_membership_rejected(api):
    """PRD §3.3: "Renewing a membership that is not ACTIVE is rejected with
    ERR_MEMBERSHIP_NOT_ACTIVE."

    Design: Corner/state_machines/renew_non_active_membership_rejected
    """
    plan = create_basic_plan()
    m = create_pending_membership(plan["id"], primary_member_name="Pend Mem")
    ver = get_success_data(api.get_membership(m["id"], make_member_headers(m["id"])))["version"]
    res = api.renew_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


def test_add_line_to_finalized_transaction_rejected(api):
    """PRD §3.5: "Adding a line is permitted only while the transaction is OPEN (otherwise
    ERR_TRANSACTION_NOT_OPEN)."

    Design: Corner/state_machines/add_line_to_finalized_transaction_rejected
    """
    plan = create_basic_plan()
    product = create_product("P-FINLINE")
    m = create_active_membership(plan["id"], primary_member_name="FinLine Mem")
    txn, line = create_finalized_transaction(m["id"], product["id"], 1)
    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_TRANSACTION_NOT_OPEN)


def test_void_finalized_transaction_rejected(api):
    """PRD §3.6: "Voiding a non-OPEN transaction is rejected with ERR_TRANSACTION_NOT_OPEN."

    Design: Corner/state_machines/void_finalized_transaction_rejected
    """
    plan = create_basic_plan()
    product = create_product("P-FINVOID")
    m = create_active_membership(plan["id"], primary_member_name="FinVoid Mem")
    txn, line = create_finalized_transaction(m["id"], product["id"], 1)
    res = api.void_transaction(txn["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_TRANSACTION_NOT_OPEN)


def test_revoke_already_revoked_card_rejected(api):
    """PRD §3.4: "revoking a card that is not ACTIVE is rejected with ERR_CARD_NOT_ACTIVE."

    Design: Corner/state_machines/revoke_already_revoked_card_rejected
    """
    plan = create_basic_plan(max_household_cards=1)
    m = create_active_membership(plan["id"], primary_member_name="RevTerm Mem")
    hdr = make_member_headers(m["id"])
    card = get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"}, hdr))
    get_success_data(api.revoke_household_card(card["id"], hdr))
    res = api.revoke_household_card(card["id"], hdr)
    validate_error(res, ApiErrorId.ERR_CARD_NOT_ACTIVE)


def test_signup_payment_on_active_membership_purpose_mismatch(api):
    """PRD §3.2: "A SIGNUP payment on a membership that is not in PENDING_PAYMENT, or a
    RENEWAL payment on a membership that is neither EXPIRED nor ACTIVE, is rejected with
    ERR_PAYMENT_PURPOSE_MISMATCH (HTTP 409)."

    Design: Corner/state_machines/signup_payment_on_active_membership_purpose_mismatch
    """
    plan = create_basic_plan()
    m = create_active_membership(plan["id"], primary_member_name="PMis Mem")
    res = api.create_payment({"membership_id": m["id"], "purpose": "SIGNUP",
                              "outcome": "SUCCEEDED"}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_PAYMENT_PURPOSE_MISMATCH)
