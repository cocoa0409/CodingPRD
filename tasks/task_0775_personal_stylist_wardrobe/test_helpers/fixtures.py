"""Composite setup helpers.

Each test runs against a freshly restarted server (empty DB), so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup calls
use ``get_success_data`` (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than an assertion deep inside a test.

Identity threading: Client and Stylist are entity_backed; any ownership-gated call
uses ``make_client_headers(client_id)`` / ``make_stylist_headers(stylist_id)`` with the
real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_stylist_payload, register_client_payload, create_assessment_payload,
    create_engagement_payload, create_session_payload, complete_session_payload,
    create_item_payload, create_lookbook_payload, add_outfit_payload,
    create_subscription_payload, create_referral_payload, signup_referral_payload,
    wallet_adjustment_payload, clock_payload, unique_email,
)
from .test_users import make_admin_headers, make_anonymous_headers, make_client_headers, make_stylist_headers


# ─────────────────────────── Primitive builders ───────────────────────────
def set_clock(api, iso: str):
    """Advance the server logical clock."""
    return get_success_data(api.set_clock(clock_payload(iso), make_admin_headers()))


def create_stylist(api, commission_pct=0.30, tier="SENIOR", full_name="Test Stylist"):
    return get_success_data(api.create_stylist(
        create_stylist_payload(full_name=full_name, email=unique_email("sty"),
                               commission_pct=commission_pct, tier=tier),
        make_admin_headers(),
    ))


def register_client(api, full_name="Test Client", email=None):
    return get_success_data(api.register_client(
        register_client_payload(full_name=full_name, email=email or unique_email("cl")),
        make_anonymous_headers(),
    ))


def credit_wallet(api, client_id, amount_cents):
    return get_success_data(api.adjust_wallet(
        client_id, wallet_adjustment_payload(amount_cents=amount_cents), make_admin_headers()))


def create_draft_assessment(api, client_id):
    return get_success_data(api.create_assessment(
        client_id, create_assessment_payload(), make_client_headers(client_id)))


def create_completed_assessment(api, client_id, stylist_id):
    a = create_draft_assessment(api, client_id)
    get_success_data(api.complete_assessment(a["id"], make_stylist_headers(stylist_id)))
    return a


def create_active_engagement(api, client_id, stylist_id, mode="HOURLY",
                             block_rate_cents=3000, package_blocks=None,
                             package_price_cents=None):
    """Create + activate an engagement. Returns the activated engagement (carries version)."""
    eng = get_success_data(api.create_engagement(
        create_engagement_payload(client_id, stylist_id, mode, block_rate_cents,
                                  package_blocks, package_price_cents),
        make_client_headers(client_id),
    ))
    return get_success_data(api.activate_engagement(eng["id"], make_client_headers(client_id)))


def schedule_session(api, engagement_id, client_id, expected_version,
                     session_type="CLOSET_AUDIT", modality="IN_PERSON",
                     scheduled_start="2026-04-01T10:00:00Z",
                     scheduled_end="2026-04-01T11:30:00Z"):
    return get_success_data(api.create_session(
        engagement_id,
        create_session_payload(scheduled_start, scheduled_end, expected_version,
                               session_type=session_type, modality=modality),
        make_client_headers(client_id),
    ))


def confirm_session(api, session_id, stylist_id):
    return get_success_data(api.confirm_session(session_id, make_stylist_headers(stylist_id)))


def complete_session(api, session_id, stylist_id, actual_minutes):
    return get_success_data(api.complete_session(
        session_id, complete_session_payload(actual_minutes), make_stylist_headers(stylist_id)))


# ─────────────────────────── Composite: sessions ───────────────────────────
def setup_confirmed_session(api, *, mode="HOURLY", block_rate_cents=3000,
                            package_blocks=None, package_price_cents=None,
                            commission_pct=0.30, tier="SENIOR",
                            session_type="CLOSET_AUDIT", modality="IN_PERSON",
                            scheduled_start="2026-04-01T10:00:00Z",
                            scheduled_end="2026-04-01T11:30:00Z"):
    """Stylist + client + COMPLETED assessment + ACTIVE engagement + one CONFIRMED session.

    Returns dict: stylist, client, assessment, engagement, session.
    """
    sty = create_stylist(api, commission_pct=commission_pct, tier=tier)
    cl = register_client(api)
    assessment = create_completed_assessment(api, cl["id"], sty["id"])
    eng = create_active_engagement(api, cl["id"], sty["id"], mode, block_rate_cents,
                                   package_blocks, package_price_cents)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            session_type=session_type, modality=modality,
                            scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    sess = confirm_session(api, sess["id"], sty["id"])
    return {"stylist": sty, "client": cl, "assessment": assessment,
            "engagement": eng, "session": sess}


def setup_scheduled_session(api, *, mode="HOURLY", block_rate_cents=3000,
                            package_blocks=None, package_price_cents=None,
                            commission_pct=0.30, assessment="draft",
                            session_type="CLOSET_AUDIT", modality="IN_PERSON",
                            scheduled_start="2026-04-01T10:00:00Z",
                            scheduled_end="2026-04-01T11:30:00Z"):
    """Stylist + client + ACTIVE engagement + one SCHEDULED (not confirmed) session.

    ``assessment`` controls the client's StyleAssessment: "draft" (created but not
    completed), "completed", or None (no assessment). Returns dict as above.
    """
    sty = create_stylist(api, commission_pct=commission_pct)
    cl = register_client(api)
    assessment_obj = None
    if assessment == "draft":
        assessment_obj = create_draft_assessment(api, cl["id"])
    elif assessment == "completed":
        assessment_obj = create_completed_assessment(api, cl["id"], sty["id"])
    eng = create_active_engagement(api, cl["id"], sty["id"], mode, block_rate_cents,
                                   package_blocks, package_price_cents)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            session_type=session_type, modality=modality,
                            scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    return {"stylist": sty, "client": cl, "assessment": assessment_obj,
            "engagement": eng, "session": sess}


def setup_completed_session(api, *, mode="HOURLY", block_rate_cents=3000,
                            package_blocks=None, package_price_cents=None,
                            commission_pct=0.30, actual_minutes=90,
                            session_type="CLOSET_AUDIT", modality="IN_PERSON",
                            scheduled_start="2026-04-01T10:00:00Z",
                            scheduled_end="2026-04-01T11:30:00Z"):
    """setup_confirmed_session then COMPLETE the session. Returns dict incl. completed session."""
    ctx = setup_confirmed_session(api, mode=mode, block_rate_cents=block_rate_cents,
                                  package_blocks=package_blocks,
                                  package_price_cents=package_price_cents,
                                  commission_pct=commission_pct, session_type=session_type,
                                  modality=modality, scheduled_start=scheduled_start,
                                  scheduled_end=scheduled_end)
    ctx["session"] = complete_session(api, ctx["session"]["id"], ctx["stylist"]["id"], actual_minutes)
    return ctx


# ─────────────────────────── Composite: shopping / purchases ───────────────────────────
def setup_shopping_session_with_item(api, *, commission_pct=0.40, retail_cost_cents=8000,
                                     block_rate_cents=3000):
    """CONFIRMED SHOPPING session with exactly one PURCHASED item. Returns dict with
    stylist, client, engagement, session, item."""
    ctx = setup_confirmed_session(api, commission_pct=commission_pct,
                                  block_rate_cents=block_rate_cents, session_type="SHOPPING",
                                  scheduled_start="2026-04-02T10:00:00Z",
                                  scheduled_end="2026-04-02T11:30:00Z")
    item = get_success_data(api.create_item(
        ctx["session"]["id"], create_item_payload(retail_cost_cents=retail_cost_cents),
        make_stylist_headers(ctx["stylist"]["id"])))
    ctx["item"] = item
    return ctx


# ─────────────────────────── Composite: lookbooks ───────────────────────────
def setup_lookbook(api, *, num_outfits=1, deliver=False):
    """ACTIVE HOURLY engagement + a lookbook with ``num_outfits`` outfits (optionally
    DELIVERED). Returns dict with stylist, client, engagement, lookbook."""
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY")
    lb = get_success_data(api.create_lookbook(
        eng["id"], create_lookbook_payload(), make_stylist_headers(sty["id"])))
    for i in range(num_outfits):
        lb = get_success_data(api.add_outfit(
            lb["id"], add_outfit_payload(name=f"Look {i + 1}"), make_stylist_headers(sty["id"])))
    if deliver:
        lb = get_success_data(api.deliver_lookbook(lb["id"], make_stylist_headers(sty["id"])))
    return {"stylist": sty, "client": cl, "engagement": eng, "lookbook": lb}


# ─────────────────────────── Composite: invoices ───────────────────────────
def setup_issued_invoice_from_session(api, *, actual_minutes=90, block_rate_cents=3000,
                                      wallet_credit=0):
    """Full lifecycle to an ISSUED invoice on a single COMPLETED session. Returns dict
    with stylist, client, engagement, session, invoice."""
    sty = create_stylist(api)
    cl = register_client(api)
    if wallet_credit:
        credit_wallet(api, cl["id"], wallet_credit)
    create_completed_assessment(api, cl["id"], sty["id"])
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY",
                                   block_rate_cents=block_rate_cents)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            scheduled_start="2026-04-03T10:00:00Z",
                            scheduled_end="2026-04-03T11:30:00Z")
    sess = confirm_session(api, sess["id"], sty["id"])
    sess = complete_session(api, sess["id"], sty["id"], actual_minutes)
    inv = get_success_data(api.create_invoice(eng["id"], make_admin_headers()))
    return {"stylist": sty, "client": cl, "engagement": eng, "session": sess, "invoice": inv}


# ─────────────────────────── Composite: subscriptions ───────────────────────────
def setup_pending_subscription(api, *, tier="SILVER", monthly_fee_cents=5000, wallet_credit=0):
    """Client (with optional wallet credit) + a PENDING subscription. Returns dict with
    client, subscription."""
    cl = register_client(api)
    if wallet_credit:
        credit_wallet(api, cl["id"], wallet_credit)
    sub = get_success_data(api.create_subscription(
        cl["id"], create_subscription_payload(tier=tier, monthly_fee_cents=monthly_fee_cents),
        make_client_headers(cl["id"])))
    return {"client": cl, "subscription": sub}


def setup_active_subscription(api, *, tier="SILVER", monthly_fee_cents=5000, wallet_credit=None):
    """PENDING subscription then ACTIVATED (wallet is seeded to cover the fee unless
    ``wallet_credit`` overrides)."""
    if wallet_credit is None:
        wallet_credit = monthly_fee_cents
    ctx = setup_pending_subscription(api, tier=tier, monthly_fee_cents=monthly_fee_cents,
                                     wallet_credit=wallet_credit)
    ctx["subscription"] = get_success_data(
        api.activate_subscription(ctx["subscription"]["id"], make_admin_headers()))
    return ctx


# ─────────────────────────── Composite: referrals ───────────────────────────
def setup_signed_up_referral(api, *, clock_iso="2026-03-15T00:00:00Z"):
    """Referrer + referee clients; referral created (estimated 5000) and SIGNED_UP.
    Returns dict with referrer, referee, referral (and the referral's estimated credit)."""
    if clock_iso:
        set_clock(api, clock_iso)
    referrer = register_client(api)
    referee = register_client(api)
    refl = get_success_data(api.create_referral(
        create_referral_payload(referrer_client_id=referrer["id"], referee_email=referee["email"]),
        make_client_headers(referrer["id"])))
    refl = get_success_data(api.signup_referral(
        refl["id"], signup_referral_payload(referee_client_id=referee["id"]), make_admin_headers()))
    return {"referrer": referrer, "referee": referee, "referral": refl}


def setup_signed_up_referral_with_issued_invoice(api, *, clock_iso="2026-03-15T00:00:00Z",
                                                 actual_minutes=90, block_rate_cents=3000):
    """A SIGNED_UP referral whose referee has an ISSUED invoice (single COMPLETED session)
    and no prior PAID invoice. Paying that invoice fires the qualification cascade.

    Returns dict with referrer, referee, referral, stylist, engagement, session, invoice.
    """
    ctx = setup_signed_up_referral(api, clock_iso=clock_iso)
    referee = ctx["referee"]
    sty = create_stylist(api, commission_pct=0.40)
    create_completed_assessment(api, referee["id"], sty["id"])
    eng = create_active_engagement(api, referee["id"], sty["id"], mode="HOURLY",
                                   block_rate_cents=block_rate_cents)
    sess = schedule_session(api, eng["id"], referee["id"], eng["version"],
                            scheduled_start="2026-04-01T10:00:00Z",
                            scheduled_end="2026-04-01T11:30:00Z")
    sess = confirm_session(api, sess["id"], sty["id"])
    sess = complete_session(api, sess["id"], sty["id"], actual_minutes)
    inv = get_success_data(api.create_invoice(eng["id"], make_admin_headers()))
    ctx.update({"stylist": sty, "engagement": eng, "session": sess, "invoice": inv})
    return ctx
