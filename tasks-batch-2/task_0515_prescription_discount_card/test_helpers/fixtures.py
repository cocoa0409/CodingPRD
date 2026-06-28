"""Composite setup helpers for multi-step test prerequisites.

The database is reset before every test, so every fixture builds its state from
scratch using only PRD-declared endpoints. Setup calls use get_success_data()
(lenient validator) so a setup failure produces a clear "Setup failed" error.

Identity threading: Member is entity-backed, so every ownership-gated call uses
make_member_headers(member_id) — never the shared TEST_USERS["member_headers"]
constant — to avoid the ownership-rejection cascade.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_drug_payload, create_pharmacy_payload, create_price_quote_payload,
    create_member_payload, create_comparison_payload, create_discount_card_payload,
    create_claim_payload, create_copay_card_payload, create_copay_link_payload,
    create_gold_membership_payload, create_mail_order_payload,
)
from .test_users import TEST_USERS, make_member_headers
from .constants import TEST_CLOCK_UTC

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
OPERATOR = TEST_USERS["pharmacy_operator_headers"]
SPONSOR = TEST_USERS["copay_sponsor_headers"]


# ─── Primitive builders ──────────────────────────────────────────────────────

def set_clock(to_iso8601=TEST_CLOCK_UTC):
    """Advance the server logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_drug(**overrides):
    """Create a Drug (PlatformAdmin). Returns the drug entity."""
    return get_success_data(api_client.create_drug(create_drug_payload(**overrides), ADMIN))


def create_pharmacy(**overrides):
    """Create an ACTIVE Pharmacy (PlatformAdmin)."""
    return get_success_data(
        api_client.create_pharmacy(create_pharmacy_payload(**overrides), ADMIN))


def create_quote(drug_id, pharmacy_id, **overrides):
    """Publish a PriceQuote (PlatformAdmin)."""
    return get_success_data(api_client.create_price_quote(
        create_price_quote_payload(drug_id, pharmacy_id, **overrides), ADMIN))


def create_member(**overrides):
    """Register a Member (public)."""
    return get_success_data(api_client.create_member(create_member_payload(**overrides), ANON))


def create_active_gold_member(member=None, **member_overrides):
    """Create a Member with a PAID gold membership whose access is ACTIVE.

    Returns (member, membership). After record-payment the membership's
    access_status is ACTIVE and Member.active_gold_membership_id is set, so the
    member is treated as Gold by the selector and the coupon credential rule.
    """
    if member is None:
        member = create_member(**member_overrides)
    headers = make_member_headers(member["id"])
    gm = get_success_data(api_client.create_gold_membership(
        create_gold_membership_payload(member["id"]), headers))
    # record-payment returns the updated membership (billing PAID, access ACTIVE);
    # capture it so callers see the post-payment state, not the stale PENDING one.
    gm = get_success_data(api_client.record_gold_payment(gm["id"], ADMIN))
    # Re-read the member so callers see the reconciled active_gold_membership_id.
    member = get_success_data(api_client.get_member(member["id"], headers))
    return member, gm


# ─── Tier 1/2: search-session backbone ────────────────────────────────────────

def setup_resolved_comparison(member=None, drug=None, pharmacy=None,
                              quote_overrides=None, comparison_overrides=None,
                              member_overrides=None, drug_overrides=None,
                              pharmacy_overrides=None, set_clock_first=True):
    """Walk clock -> drug -> pharmacy -> quote -> member -> comparison -> run.

    Returns a dict with keys: member, drug, pharmacy, quote, comparison.
    The comparison is RESOLVED (one eligible CA quote). Pass member= to reuse a
    pre-built (possibly Gold) member so the basis follows that member's access.
    """
    if set_clock_first:
        set_clock()
    if drug is None:
        drug = create_drug(**(drug_overrides or {}))
    if pharmacy is None:
        pharmacy = create_pharmacy(**(pharmacy_overrides or {}))
    quote = create_quote(drug["id"], pharmacy["id"], **(quote_overrides or {}))
    if member is None:
        member = create_member(**(member_overrides or {}))
    headers = make_member_headers(member["id"])
    comparison = get_success_data(api_client.create_comparison(
        create_comparison_payload(member["id"], drug["id"], **(comparison_overrides or {})),
        headers))
    comparison = get_success_data(api_client.run_comparison(
        comparison["id"], {"member_id": member["id"]}, headers))
    return {
        "member": member, "drug": drug, "pharmacy": pharmacy,
        "quote": quote, "comparison": comparison,
    }


def setup_discount_card(member=None, gold=False, **kwargs):
    """Backbone through to an ISSUED DiscountCard.

    If gold=True, the member is first made an ACTIVE Gold member so the card's
    pricing_basis resolves to GOLD. Returns a dict extending
    setup_resolved_comparison with key: card (and membership when gold).
    """
    membership = None
    if member is None and gold:
        member, membership = create_active_gold_member(
            **{k: v for k, v in (kwargs.get("member_overrides") or {}).items()})
        kwargs = {k: v for k, v in kwargs.items() if k != "member_overrides"}
    ctx = setup_resolved_comparison(member=member, **kwargs)
    headers = make_member_headers(ctx["member"]["id"])
    card = get_success_data(api_client.create_discount_card(
        create_discount_card_payload(ctx["member"]["id"], ctx["comparison"]["id"]), headers))
    ctx["card"] = card
    ctx["membership"] = membership
    return ctx


# ─── Tier 3: claim lifecycle shortcuts ────────────────────────────────────────

def setup_submitted_claim(quantity=2, gold=False, **kwargs):
    """Backbone through a SUBMITTED Claim. Returns ctx + key: claim."""
    ctx = setup_discount_card(gold=gold, **kwargs)
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(ctx["card"]["id"], ctx["pharmacy"]["id"], quantity=quantity),
        OPERATOR))
    ctx["claim"] = claim
    return ctx


def setup_adjudicated_claim(quantity=2, gold=False, **kwargs):
    """Backbone through an ADJUDICATED Claim. Returns ctx + keys: claim, claim_version.

    claim_version is the Claim.version observed AFTER adjudication (the value a
    fresh reverse must supply under OCC, PRD §2.6).
    """
    ctx = setup_submitted_claim(quantity=quantity, gold=gold, **kwargs)
    claim = get_success_data(api_client.adjudicate_claim(ctx["claim"]["id"], OPERATOR))
    ctx["claim"] = claim
    ctx["claim_version"] = claim["version"]
    return ctx


def create_copay_card(drug_id, **overrides):
    """Publish an ACTIVE CopayCard (CopayCardSponsor)."""
    return get_success_data(api_client.create_copay_card(
        create_copay_card_payload(drug_id, **overrides), SPONSOR))


def link_copay_card(copay_card_id, member_id, claim_id):
    """Member links a copay card to a SUBMITTED claim. Returns the LINKED link."""
    return get_success_data(api_client.create_copay_link(
        create_copay_link_payload(copay_card_id, member_id, claim_id),
        make_member_headers(member_id)))


def setup_submitted_claim_with_copay_link(quantity=2, max_benefit_cents=50000,
                                          per_fill_cap_cents=4000, **kwargs):
    """SUBMITTED claim with an ACTIVE CopayCard LINKED to it.

    Returns ctx + keys: claim, copay_card, copay_link. The copay card is scoped
    to the same drug as the claim's card so linkage passes the drug-match guard.
    """
    ctx = setup_submitted_claim(quantity=quantity, **kwargs)
    copay_card = create_copay_card(
        ctx["drug"]["id"],
        max_benefit_cents=max_benefit_cents, per_fill_cap_cents=per_fill_cap_cents)
    link = link_copay_card(copay_card["id"], ctx["member"]["id"], ctx["claim"]["id"])
    ctx["copay_card"] = copay_card
    ctx["copay_link"] = link
    return ctx


def setup_adjudicated_claim_with_copay(quantity=2, max_benefit_cents=3000,
                                       per_fill_cap_cents=8000, **kwargs):
    """ADJUDICATED claim that drew a copay offset. Returns ctx + claim_version.

    Defaults (remaining 3000 binds) drive the copay card to EXHAUSTED so the
    reverse-compensation path can be exercised.
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=quantity, max_benefit_cents=max_benefit_cents,
        per_fill_cap_cents=per_fill_cap_cents, **kwargs)
    claim = get_success_data(api_client.adjudicate_claim(ctx["claim"]["id"], OPERATOR))
    ctx["claim"] = claim
    ctx["claim_version"] = claim["version"]
    return ctx


# ─── Tier 2: mail-order ───────────────────────────────────────────────────────

def setup_placed_mail_order(quantity=2, ship_to_state="CA", pharmacy_overrides=None,
                            **kwargs):
    """Backbone through a PLACED MailOrderFulfillment at a mail-order pharmacy.

    Returns ctx + key: mail_order. The pharmacy is created with is_mail_order=True.
    """
    pharmacy_overrides = dict(pharmacy_overrides or {})
    pharmacy_overrides.setdefault("is_mail_order", True)
    pharmacy_overrides.setdefault("name", "PH Mail")
    pharmacy_overrides.setdefault("chain_code", "MAIL")
    pharmacy_overrides.setdefault("dispense_fee_cents", 150)
    ctx = setup_discount_card(pharmacy_overrides=pharmacy_overrides, **kwargs)
    headers = make_member_headers(ctx["member"]["id"])
    mo = get_success_data(api_client.create_mail_order(
        create_mail_order_payload(ctx["card"]["id"], ctx["pharmacy"]["id"],
                                  ctx["member"]["id"], quantity=quantity,
                                  ship_to_state=ship_to_state),
        headers))
    ctx["mail_order"] = mo
    return ctx


def setup_telehealth_referral(reason="PRICE_TOO_HIGH", **kwargs):
    """Backbone through a REQUESTED TelehealthReferral from a RESOLVED comparison."""
    ctx = setup_resolved_comparison(**kwargs)
    headers = make_member_headers(ctx["member"]["id"])
    from .factories import create_telehealth_referral_payload
    ref = get_success_data(api_client.create_telehealth_referral(
        create_telehealth_referral_payload(ctx["member"]["id"], ctx["comparison"]["id"],
                                            reason=reason),
        headers))
    ctx["referral"] = ref
    return ctx
