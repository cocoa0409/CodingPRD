"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating a Customer that will act as a Customer/B2BBuyer owner,
ownership-gated calls in the same chain use make_customer_headers(cust_id) /
make_b2b_buyer_headers(cust_id) with the real Customer.id — never the shared constant.

Every helper builds its preconditions from scratch (the server DB is empty before each test).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload, create_state_rule_payload, create_campaign_payload,
    create_customer_payload, create_card_payload, activate_card_payload,
    reload_card_payload, create_hold_payload, create_redemption_payload,
    settle_redemption_payload, create_bulk_order_payload, create_replacement_payload,
    approve_replacement_payload, create_refund_payload, create_dormancy_waiver_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_b2b_buyer_headers

_ADMIN = TEST_USERS["program_admin_headers"]
_STORE = TEST_USERS["store_associate_headers"]
_FRAUD = TEST_USERS["fraud_analyst_headers"]


# ─── Tier 0: Primitives ───────────────────────────────────────────────────

def create_program(**overrides):
    """Create a Program. Returns the program dict."""
    res = api_client.create_program(create_program_payload(**overrides), _ADMIN)
    return get_success_data(res)


def create_customer(is_corporate=False, email="cust@x.com", **overrides):
    """Register a Customer. Returns the customer dict."""
    payload = create_customer_payload(email=email, **overrides)
    if is_corporate:
        payload["is_corporate"] = True
    res = api_client.create_customer(payload, _ADMIN)
    return get_success_data(res)


def issue_card(program_id, form_factor="DIGITAL", state_code="FL", owner_customer_id=None):
    """Issue an INACTIVE card. Returns the card dict."""
    kwargs = {}
    if owner_customer_id is not None:
        kwargs["owner_customer_id"] = owner_customer_id
    res = api_client.create_card(
        create_card_payload(program_id, form_factor=form_factor,
                            state_code=state_code, **kwargs),
        _STORE)
    return get_success_data(res)


def set_clock(to_iso8601):
    """Advance the test-driving clock. Returns the raw response."""
    return api_client.set_clock(to_iso8601, _ADMIN)


# ─── Tier 1: State Progression — card to ACTIVE with a known balance ───────

def create_active_card(program_id, settled_cents, state_code="FL", form_factor="DIGITAL",
                       owner_customer_id=None):
    """Issue a card and activate it with an initial LOAD of `settled_cents`.
    Returns the activated card dict (lifecycle_status == ACTIVE)."""
    card = issue_card(program_id, form_factor=form_factor, state_code=state_code,
                      owner_customer_id=owner_customer_id)
    res = api_client.activate_card(card["id"], activate_card_payload(settled_cents), _STORE)
    return get_success_data(res)


def setup_program_and_active_card(settled_cents, reload_min_cents=500,
                                  reload_max_balance_cents=100000, hold_ttl_seconds=900,
                                  state_code="FL", form_factor="DIGITAL",
                                  owner_customer_id=None):
    """Program (with given config) + one ACTIVE card at `settled_cents`.
    Returns (program, card)."""
    program = create_program(reload_min_cents=reload_min_cents,
                             reload_max_balance_cents=reload_max_balance_cents,
                             hold_ttl_seconds=hold_ttl_seconds)
    card = create_active_card(program["id"], settled_cents,
                              state_code=state_code, form_factor=form_factor,
                              owner_customer_id=owner_customer_id)
    return program, card


def place_hold(card_id, amount_cents):
    """Place an ACTIVE authorization hold on a card. Returns the hold dict."""
    res = api_client.create_hold(create_hold_payload(card_id, amount_cents), _STORE)
    return get_success_data(res)


def setup_card_with_hold(settled_cents, hold_cents, hold_ttl_seconds=900):
    """Program + ACTIVE card at `settled_cents` + one ACTIVE hold of `hold_cents`.
    Returns (program, card, hold)."""
    program, card = setup_program_and_active_card(
        settled_cents, hold_ttl_seconds=hold_ttl_seconds)
    hold = place_hold(card["id"], hold_cents)
    return program, card, hold


# ─── Tier 1b: Risk dimension progression ───────────────────────────────────

def flag_card(card_id):
    """Drive CLEAR → FLAGGED. Returns the card dict."""
    return get_success_data(api_client.flag_card(card_id, _FRAUD))


def freeze_card(card_id):
    """Drive FLAGGED → FROZEN_RISK. Returns the card dict."""
    return get_success_data(api_client.freeze_card(card_id, _FRAUD))


def setup_frozen_card(settled_cents):
    """Program + ACTIVE card flagged then frozen (risk_status FROZEN_RISK).
    Returns (program, card)."""
    program, card = setup_program_and_active_card(settled_cents)
    flag_card(card["id"])
    freeze_card(card["id"])
    return program, card


def setup_flagged_card(settled_cents):
    """Program + ACTIVE FLAGGED card. Returns (program, card)."""
    program, card = setup_program_and_active_card(settled_cents)
    flag_card(card["id"])
    return program, card


# ─── Tier 2: Multi-card split-tender scenarios ─────────────────────────────

def setup_three_cards(balances=(3000, 1500, 4000), reload_max_balance_cents=100000):
    """Program + three ACTIVE cards with the given balances (A, B, C).
    Returns (program, [card_a, card_b, card_c])."""
    program = create_program(reload_min_cents=500,
                             reload_max_balance_cents=reload_max_balance_cents)
    cards = [create_active_card(program["id"], bal) for bal in balances]
    return program, cards


def draft_redemption(program_id, requested_amount_cents, card_id_order, customer_id=None,
                     headers=None):
    """Draft a DRAFT redemption. Returns the redemption dict."""
    payload = create_redemption_payload(program_id, requested_amount_cents, card_id_order)
    if customer_id is not None:
        payload["customer_id"] = customer_id
    return get_success_data(
        api_client.create_redemption(payload, headers or _STORE))


def setup_draft_redemption_over_cards(requested_amount_cents, balances, order_index,
                                      reload_max_balance_cents=100000):
    """Program + N ACTIVE cards + a DRAFT redemption over `order_index` (a list of indices
    into the created cards defining card_id_order). Returns (program, cards, redemption)."""
    program, cards = setup_three_cards(tuple(balances),
                                       reload_max_balance_cents=reload_max_balance_cents)
    order = [cards[i]["id"] for i in order_index]
    redemption = draft_redemption(program["id"], requested_amount_cents, order)
    return program, cards, redemption


def settle_redemption(redemption_id, expected_version, headers=None):
    """Settle a DRAFT redemption. Returns the raw response (caller inspects status)."""
    return api_client.settle_redemption(
        redemption_id, settle_redemption_payload(expected_version), headers or _STORE)


def setup_settled_redemption(balances=(3000, 1500), requested_amount_cents=4500,
                             with_customer=True):
    """Program + customer + ACTIVE cards owned by the customer + a SETTLED redemption
    that draws them down per the waterfall. Returns
    (program, customer, cards, redemption_after_settle)."""
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    customer = create_customer(email="cust@x.com") if with_customer else None
    cards = []
    for bal in balances:
        owner = customer["id"] if customer else None
        cards.append(create_active_card(program["id"], bal, owner_customer_id=owner))
    order = [c["id"] for c in cards]
    cust_id = customer["id"] if customer else None
    redemption = draft_redemption(program["id"], requested_amount_cents, order,
                                  customer_id=cust_id)
    settled = get_success_data(
        api_client.settle_redemption(
            redemption["id"], settle_redemption_payload(redemption["version"]), _STORE))
    return program, customer, cards, settled


# ─── Tier 3: Replacement lifecycle ─────────────────────────────────────────

def open_replacement(old_card_id, reason="FRAUD", headers=None):
    """Open an OPEN ReplacementRequest. Returns the replacement dict."""
    return get_success_data(
        api_client.create_replacement(
            create_replacement_payload(old_card_id, reason), headers or _FRAUD))


def setup_open_replacement(settled_cents=3000, reason="FRAUD", owner_customer_id=None,
                           form_factor="PHYSICAL"):
    """Program + ACTIVE card (at `settled_cents`, version captured) + an OPEN replacement.
    Returns (program, card, replacement)."""
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    card = create_active_card(program["id"], settled_cents, form_factor=form_factor,
                              owner_customer_id=owner_customer_id)
    replacement = open_replacement(card["id"], reason=reason)
    return program, card, replacement


def approve_replacement(replacement_id, expected_old_card_version, headers=None):
    """Approve a replacement. Returns the raw response (caller inspects status/data)."""
    return api_client.approve_replacement(
        replacement_id, approve_replacement_payload(expected_old_card_version),
        headers or _FRAUD)


def setup_approved_replacement(settled_cents=3000, reason="LOST"):
    """Program + ACTIVE card → OPEN replacement → APPROVED (old card VOIDED, new card minted).
    Returns (program, old_card, replacement_after_approve)."""
    program, card, replacement = setup_open_replacement(settled_cents, reason=reason)
    approved = get_success_data(
        api_client.approve_replacement(
            replacement["id"], approve_replacement_payload(card["version"]), _FRAUD))
    return program, card, approved


# ─── Tier 4: Refund lifecycle ──────────────────────────────────────────────

def open_refund(card_id, requested_refund_cents, redemption_id=None, headers=None):
    """Open a PENDING RefundRequest. Returns the refund dict."""
    return get_success_data(
        api_client.create_refund(
            create_refund_payload(card_id, requested_refund_cents,
                                  redemption_id=redemption_id),
            headers or _ADMIN))


def setup_pending_refund_on_owned_card(settled_cents=5000, refund_cents=1000):
    """Program + customer + ACTIVE owned card + a PENDING refund opened by the customer.
    Returns (program, customer, card, refund). The refund is opened with the entity-backed
    customer headers so ownership passes."""
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    customer = create_customer(email="cust@x.com")
    card = create_active_card(program["id"], settled_cents,
                              owner_customer_id=customer["id"])
    refund = get_success_data(
        api_client.create_refund(
            create_refund_payload(card["id"], refund_cents),
            make_customer_headers(customer["id"])))
    return program, customer, card, refund


def setup_full_refund_on_settled_redemption(balances=(3000, 1500),
                                            requested_amount_cents=4500):
    """Program + customer + two cards + a SETTLED redemption + a PENDING full-amount refund
    on card A referencing that redemption. Returns
    (program, customer, cards, settled_redemption, refund)."""
    program, customer, cards, settled = setup_settled_redemption(
        balances=balances, requested_amount_cents=requested_amount_cents)
    refund = open_refund(cards[0]["id"], requested_amount_cents,
                         redemption_id=settled["id"])
    return program, customer, cards, settled, refund


# ─── Tier 5: Bulk order lifecycle ──────────────────────────────────────────

def setup_quoted_bulk_order(card_count, face_value_cents, b2b_discount_pct=0.035,
                            is_corporate=True):
    """Program + buyer Customer + a QUOTED BulkOrder. The quote is placed with the
    entity-backed buyer headers. Returns (program, buyer, bulk_order)."""
    program = create_program(b2b_discount_pct=b2b_discount_pct)
    buyer = create_customer(is_corporate=is_corporate, email="corp@x.com",
                            full_name="Corp Co")
    bulk_order = get_success_data(
        api_client.create_bulk_order(
            create_bulk_order_payload(program["id"], buyer["id"],
                                      card_count, face_value_cents),
            make_b2b_buyer_headers(buyer["id"])))
    return program, buyer, bulk_order


def setup_confirmed_bulk_order(card_count, face_value_cents, b2b_discount_pct=0.035):
    """Program + corporate buyer + a CONFIRMED BulkOrder (net_invoice_cents pinned).
    Returns (program, buyer, bulk_order_after_confirm)."""
    program, buyer, bulk_order = setup_quoted_bulk_order(
        card_count, face_value_cents, b2b_discount_pct=b2b_discount_pct)
    confirmed = get_success_data(
        api_client.confirm_bulk_order(bulk_order["id"], make_b2b_buyer_headers(buyer["id"])))
    return program, buyer, confirmed


# ─── Tier 6: Dormancy / breakage / escheat (clock-driven) ──────────────────

def setup_card_for_dormancy(state_rule_kwargs, activate_at_iso, assess_at_iso,
                            settled_cents=4000, state_code="FL"):
    """Program + a StateRule (per state_rule_kwargs) + a card activated at `activate_at_iso`
    with `settled_cents`, then the clock advanced to `assess_at_iso`. The card is NOT yet
    assessed. Returns (program, state_rule, card)."""
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    state_rule = get_success_data(
        api_client.create_state_rule(
            create_state_rule_payload(program["id"], state_code=state_code,
                                      **state_rule_kwargs),
            _ADMIN))
    set_clock(activate_at_iso)
    card = create_active_card(program["id"], settled_cents, state_code=state_code)
    set_clock(assess_at_iso)
    return program, state_rule, card


def setup_two_jurisdiction_cards_for_breakage(activate_at_iso, assess_at_iso,
                                              settled_cents=4000, escheat_rate=0.60):
    """Program + FL(RECOGNIZE) + CA(ESCHEAT rate) StateRules + one FL card and one CA card,
    both activated at `activate_at_iso` with `settled_cents`, clock advanced to
    `assess_at_iso`. Neither card is assessed yet.
    Returns (program, card_fl, card_ca)."""
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    get_success_data(api_client.create_state_rule(
        create_state_rule_payload(program["id"], state_code="FL",
                                  expiration_allowed=True, dormancy_fee_allowed=False,
                                  breakage_policy="RECOGNIZE"),
        _ADMIN))
    get_success_data(api_client.create_state_rule(
        create_state_rule_payload(program["id"], state_code="CA",
                                  expiration_allowed=True, dormancy_fee_allowed=False,
                                  breakage_policy="ESCHEAT", escheat_rate=escheat_rate),
        _ADMIN))
    set_clock(activate_at_iso)
    card_fl = create_active_card(program["id"], settled_cents, state_code="FL")
    card_ca = create_active_card(program["id"], settled_cents, state_code="CA")
    set_clock(assess_at_iso)
    return program, card_fl, card_ca


# ─── Tier 7: Campaigns ─────────────────────────────────────────────────────

def create_campaign(program_id, window_start, window_end, name="Winter", bonus_pct=0.10):
    """Create a SCHEDULED campaign. Returns the campaign dict."""
    return get_success_data(
        api_client.create_campaign(
            create_campaign_payload(program_id, window_start, window_end,
                                    name=name, bonus_pct=bonus_pct),
            _ADMIN))


def setup_active_campaign_and_card(settled_cents, window_start, window_end, sync_at_iso,
                                   bonus_pct=0.10):
    """Program + a campaign synced ACTIVE (clock at sync_at_iso inside the window) +
    an ACTIVE card at `settled_cents`. Returns (program, campaign, card)."""
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    campaign = create_campaign(program["id"], window_start, window_end, bonus_pct=bonus_pct)
    set_clock(sync_at_iso)
    campaign = get_success_data(api_client.sync_campaign_status(campaign["id"], _ADMIN))
    card = create_active_card(program["id"], settled_cents)
    return program, campaign, card


def setup_dormancy_waiver(card_id, window_start, window_end):
    """Create an ACTIVE DormancyWaiver. Returns the waiver dict."""
    return get_success_data(
        api_client.create_dormancy_waiver(
            create_dormancy_waiver_payload(card_id, window_start, window_end), _ADMIN))
