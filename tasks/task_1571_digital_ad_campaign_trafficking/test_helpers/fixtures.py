"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.
Every helper builds preconditions from scratch via PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_insertion_order_payload,
    create_line_item_payload,
    create_creative_payload,
    create_delivery_snapshot_payload,
    create_impression_event_payload,
    create_verification_report_payload,
    create_make_good_payload,
    create_reconciliation_payload,
    create_wrap_report_payload,
)
from .constants import TEST_DEFAULTS, CLOCK_STARTUP_DEFAULT
from .test_users import TEST_USERS, make_analyst_headers, make_billing_headers

AD_TAG = TEST_DEFAULTS["AD_TAG"]


# ─── Tier 1: single-entity creation / clock ───────────

def set_clock(to_iso8601=CLOCK_STARTUP_DEFAULT):
    """Drive the server logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, TEST_USERS["ad_ops_headers"]))


def create_io(**overrides):
    """Create an insertion order in DRAFT. Returns the IO dict."""
    return get_success_data(api_client.create_insertion_order(
        create_insertion_order_payload(**overrides), TEST_USERS["ad_ops_headers"]))


def create_line_item(io_id, **overrides):
    """Create a line item in DRAFT under an existing IO. Returns the line item."""
    return get_success_data(api_client.create_line_item(
        create_line_item_payload(io_id, **overrides), TEST_USERS["trafficker_headers"]))


def create_creative(line_item_id, **overrides):
    """Upload a creative (lands UPLOADED). Returns the creative."""
    return get_success_data(api_client.create_creative(
        create_creative_payload(line_item_id, **overrides),
        TEST_USERS["trafficker_headers"]))


def transition_io(io_id, action):
    return get_success_data(api_client.transition_insertion_order(
        io_id, {"action": action}, TEST_USERS["ad_ops_headers"]))


def transition_line_item(li_id, action):
    return get_success_data(api_client.transition_line_item(
        li_id, {"action": action}, TEST_USERS["trafficker_headers"]))


def transition_creative(cr_id, action, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_creative(
        cr_id, payload, TEST_USERS["trafficker_headers"]))


# ─── Tier 2: creative QA/tagging chain ────────────────

def walk_creative_to_tagged(creative_id, ad_tag=AD_TAG):
    """SUBMIT_QA → PASS_QA → TAG. Returns the TAGGED creative."""
    transition_creative(creative_id, "SUBMIT_QA")
    transition_creative(creative_id, "PASS_QA")
    return transition_creative(creative_id, "TAG", ad_tag=ad_tag)


# ─── Tier 3: line-item progression composites ─────────

def setup_draft_line_item(io_overrides=None, li_overrides=None):
    """DRAFT IO + DRAFT line item. Returns {"io": io, "line_item": li}."""
    io = create_io(**(io_overrides or {}))
    li = create_line_item(io["id"], **(li_overrides or {}))
    return {"io": io, "line_item": li}


def setup_trafficked_line_item(clock=CLOCK_STARTUP_DEFAULT, io_overrides=None,
                               li_overrides=None):
    """APPROVED IO + TRAFFICKED line item with one TAGGED creative.

    Returns {"io": io, "line_item": li, "creative": cr}.
    """
    set_clock(clock)
    io = create_io(**(io_overrides or {}))
    li = create_line_item(io["id"], **(li_overrides or {}))
    transition_io(io["id"], "APPROVE")
    cr = create_creative(li["id"])
    walk_creative_to_tagged(cr["id"])
    li = transition_line_item(li["id"], "TRAFFIC")
    return {"io": io, "line_item": li, "creative": cr}


def setup_live_line_item(clock=CLOCK_STARTUP_DEFAULT, io_overrides=None,
                         li_overrides=None, activate_io=False):
    """APPROVED IO + LIVE line item whose TAGGED creative flipped to LIVE.

    Returns {"io": io, "line_item": li, "creative": cr} with post-launch state.
    """
    ctx = setup_trafficked_line_item(clock=clock, io_overrides=io_overrides,
                                     li_overrides=li_overrides)
    li = transition_line_item(ctx["line_item"]["id"], "LAUNCH")
    if activate_io:
        transition_io(ctx["io"]["id"], "ACTIVATE")
    cr = get_success_data(api_client.get_creative(
        ctx["creative"]["id"], TEST_USERS["trafficker_headers"]))
    return {"io": ctx["io"], "line_item": li, "creative": cr}


def add_tagged_creative(line_item_id, name="CR2", ad_tag="<script>t2</script>"):
    """Upload a creative and walk it to TAGGED under an existing line item."""
    cr = create_creative(line_item_id, name=name)
    return walk_creative_to_tagged(cr["id"], ad_tag=ad_tag)


# ─── Tier 4: delivery / events / verification / make-goods ──────────────

def post_snapshot(line_item_id, snapshot_date, impressions, clicks):
    """POST a delivery snapshot. Returns the POSTED snapshot."""
    return get_success_data(api_client.create_delivery_snapshot(
        create_delivery_snapshot_payload(line_item_id, snapshot_date, impressions,
                                         clicks),
        TEST_USERS["trafficker_headers"]))


def void_snapshot(snapshot_id):
    return get_success_data(api_client.transition_delivery_snapshot(
        snapshot_id, {"action": "VOID"}, TEST_USERS["trafficker_headers"]))


def get_line_item(line_item_id):
    return get_success_data(api_client.get_line_item(
        line_item_id, TEST_USERS["trafficker_headers"]))


def get_io(io_id):
    return get_success_data(api_client.get_insertion_order(
        io_id, TEST_USERS["ad_ops_headers"]))


def get_creative(creative_id):
    return get_success_data(api_client.get_creative(
        creative_id, TEST_USERS["trafficker_headers"]))


def post_impression_event(line_item_id, user_key, occurred_at=None):
    overrides = {}
    if occurred_at is not None:
        overrides["occurred_at"] = occurred_at
    return api_client.create_impression_event(
        create_impression_event_payload(line_item_id, user_key, **overrides),
        TEST_USERS["trafficker_headers"])


def file_verification_report(line_item_id, user_id="va-1", **overrides):
    """File a verification report as a VerificationAnalyst. Returns the report."""
    return get_success_data(api_client.create_verification_report(
        create_verification_report_payload(line_item_id, **overrides),
        make_analyst_headers(user_id)))


def propose_make_good(report_id, user_id="va-1", **overrides):
    """Propose a make-good as a VerificationAnalyst. Returns the make-good."""
    return get_success_data(api_client.create_make_good(
        create_make_good_payload(report_id, **overrides),
        make_analyst_headers(user_id)))


def decide_make_good(make_good_id, action, user_id="bm-2"):
    """APPROVE / REJECT / APPLY / REVERSE as a BillingManager."""
    return get_success_data(api_client.transition_make_good(
        make_good_id, {"action": action}, make_billing_headers(user_id)))


def setup_breach_report(line_item_id, user_id="va-1", measured=100000,
                        viewable=80000, ivt=5000, vendor="IAS",
                        period_start="2026-08-01", period_end="2026-08-07"):
    """File an IVT-breach report against a LIVE line item (fires the fraud
    cascade). Returns the BREACH report."""
    return file_verification_report(
        line_item_id, user_id=user_id, vendor=vendor, period_start=period_start,
        period_end=period_end, measured_impressions=measured,
        viewable_impressions=viewable, ivt_impressions=ivt)


# ─── Tier 5: reconciliation / completion / wrap composites ───────────────

def create_reconciliation(line_item_id, period_start="2026-08-01",
                          period_end="2026-08-10", third_party_impressions=0,
                          user_id="bm-1"):
    """Open a reconciliation as a BillingManager. Returns the OPEN record."""
    return get_success_data(api_client.create_reconciliation(
        create_reconciliation_payload(
            line_item_id, period_start=period_start, period_end=period_end,
            third_party_impressions=third_party_impressions),
        make_billing_headers(user_id)))


def transition_reconciliation(rec_id, action, user_id="bm-1"):
    return get_success_data(api_client.transition_reconciliation(
        rec_id, {"action": action}, make_billing_headers(user_id)))


def create_and_reconcile(line_item_id, period_start="2026-08-01",
                         period_end="2026-08-10", third_party_impressions=0,
                         reconciler="bm-1"):
    """Open + RECONCILE. Returns the RECONCILED record."""
    rec = create_reconciliation(line_item_id, period_start, period_end,
                                third_party_impressions, user_id=reconciler)
    return transition_reconciliation(rec["id"], "RECONCILE", user_id=reconciler)


def create_and_lock_reconciliation(line_item_id, period_start="2026-08-01",
                                   period_end="2026-08-10",
                                   third_party_impressions=0,
                                   reconciler="bm-1", locker="bm-2"):
    """Open + RECONCILE + LOCK with segregated operators. Returns LOCKED record."""
    rec = create_and_reconcile(line_item_id, period_start, period_end,
                               third_party_impressions, reconciler=reconciler)
    return transition_reconciliation(rec["id"], "LOCK", user_id=locker)


def complete_line_item(line_item_id):
    """Manual COMPLETE (caller must have moved the clock past end_date)."""
    return transition_line_item(line_item_id, "COMPLETE")


def complete_io(io_id):
    """Manual IO COMPLETE (requires all line items terminal + past flight_end)."""
    return transition_io(io_id, "COMPLETE")


def create_wrap_report(io_id, attribution_model="LINEAR_CLICKS",
                       total_conversions=10, user_id="bm-1"):
    return get_success_data(api_client.create_wrap_report(
        create_wrap_report_payload(io_id, attribution_model=attribution_model,
                                   total_conversions=total_conversions),
        make_billing_headers(user_id)))
