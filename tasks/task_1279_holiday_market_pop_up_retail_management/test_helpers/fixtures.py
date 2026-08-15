"""
Composite setup helpers for multi-step test prerequisites.

The interesting claims in this PRD require the system to be in a specific
state that takes 5-15 API calls to reach (market -> vendor -> application ->
jury scores -> decide -> booth -> assignment -> activate -> open -> POS).
These helpers encapsulate those chains. All helpers use get_success_data()
(lenient validator) so setup failures produce clear errors, and every vendor
or juror call threads the correct identity headers.

Clock management: the server's logical clock starts at 2026-08-01T00:00:00Z
(PRD §1). Helpers set the clock explicitly so application windows, open
windows, and run_ops expiry checks are deterministic.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SETUP_CLOCK, OPEN_CLOCK
from .factories import (
    create_market_payload, create_vendor_payload, create_application_payload,
    create_booth_payload, create_assignment_payload, create_permit_payload,
    create_hookup_payload, create_pos_device_payload, create_settlement_payload,
    create_load_slot_payload, create_weather_event_payload,
    create_renewal_offer_payload,
)
from .test_users import TEST_USERS, make_vendor_headers, make_juror_headers

OPERATOR = TEST_USERS["market_operator_headers"]
JURY_CHAIR = TEST_USERS["jury_chair_headers"]
UTILITY = TEST_USERS["utility_crew_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Drive the server's logical clock to the given instant (PRD §1)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, OPERATOR))


def create_market(market_overrides=None, clock: str = SETUP_CLOCK):
    """Set the logical clock, then create a Market (starts in SETUP)."""
    if clock:
        set_clock(clock)
    res = api_client.create_market(create_market_payload(**(market_overrides or {})), OPERATOR)
    return get_success_data(res)


def create_vendor_entity(**overrides):
    res = api_client.create_vendor(create_vendor_payload(**overrides), OPERATOR)
    return get_success_data(res)


def create_booth_entity(market_id: str, **overrides):
    res = api_client.create_booth(market_id, create_booth_payload(**overrides), OPERATOR)
    return get_success_data(res)


def get_market(market_id: str):
    return get_success_data(api_client.get_market(market_id, OPERATOR))


def get_vendor(vendor_id: str):
    return get_success_data(api_client.get_vendor(vendor_id, OPERATOR))


def get_application(market_id: str, application_id: str):
    return get_success_data(api_client.get_application(market_id, application_id, JURY_CHAIR))


def get_assignment(market_id: str, assignment_id: str):
    return get_success_data(api_client.get_assignment(market_id, assignment_id, OPERATOR))


def get_booth(market_id: str, booth_id: str):
    return get_success_data(api_client.get_booth(market_id, booth_id, OPERATOR))


def get_pos_device(market_id: str, pos_device_id: str):
    return get_success_data(api_client.get_pos_device(market_id, pos_device_id, OPERATOR))


def get_settlement(market_id: str, settlement_id: str):
    return get_success_data(api_client.get_settlement(market_id, settlement_id, OPERATOR))


def get_load_slot(market_id: str, load_slot_id: str):
    return get_success_data(api_client.get_load_slot(market_id, load_slot_id, OPERATOR))


def get_permit(market_id: str, permit_id: str):
    return get_success_data(api_client.get_permit(market_id, permit_id, OPERATOR))


def get_hookup(market_id: str, hookup_id: str):
    return get_success_data(api_client.get_hookup(market_id, hookup_id, OPERATOR))


def run_ops(market_id: str):
    """Invoke the ops checkpoint once (PRD §3.9)."""
    return get_success_data(api_client.run_ops(market_id, OPERATOR))


# ---------------------------------------------------------------------------
# Tier 1: Application state progression (DRAFT -> SUBMITTED -> UNDER_JURY -> decided)
# ---------------------------------------------------------------------------

def create_draft_application(market_id: str, vendor_id: str, **app_overrides):
    payload = create_application_payload(vendor_id, **app_overrides)
    res = api_client.create_application(market_id, payload, make_vendor_headers(vendor_id))
    return get_success_data(res)


def submit_application(market_id: str, application_id: str, vendor_id: str):
    res = api_client.submit_application(market_id, application_id,
                                        make_vendor_headers(vendor_id))
    return get_success_data(res)


def score_application(market_id: str, application_id: str, score: int, juror_id: str):
    res = api_client.score_application(market_id, application_id,
                                       {"score_0_100": score},
                                       make_juror_headers(juror_id))
    return get_success_data(res)


def score_application_n(market_id: str, application_id: str, scores,
                        juror_prefix: str = None):
    """Apply len(scores) scores from DISTINCT jurors (a juror may score an
    application only once, PRD §3.3). Returns the latest application state."""
    prefix = juror_prefix or f"juror-{uuid.uuid4().hex[:6]}"
    app = None
    for i, s in enumerate(scores):
        app = score_application(market_id, application_id, s, f"{prefix}-{i}")
    return app


def decide_application(market_id: str, application_id: str, decision: str = "ACCEPTED"):
    """Decide with the application's CURRENT version (OCC, PRD §2.7).
    Returns the raw response so callers can assert success or failure."""
    app = get_application(market_id, application_id)
    payload = {"decision": decision, "expected_application_version": app["version"]}
    return api_client.decide_application(market_id, application_id, payload, JURY_CHAIR)


def create_submitted_application(market_id: str, vendor_id: str, **app_overrides):
    """DRAFT -> SUBMITTED. Market must be SETUP and clock inside the
    application window (PRD §3.2)."""
    app = create_draft_application(market_id, vendor_id, **app_overrides)
    return submit_application(market_id, app["id"], vendor_id)


def create_under_jury_application(market_id: str, vendor_id: str, scores=(80, 80, 80),
                                  juror_prefix: str = None, **app_overrides):
    """SUBMITTED -> UNDER_JURY with the given scores applied."""
    app = create_submitted_application(market_id, vendor_id, **app_overrides)
    return score_application_n(market_id, app["id"], scores, juror_prefix)


def create_accepted_application(market_id: str, vendor_id: str, scores=(80, 80, 80),
                                juror_prefix: str = None, **app_overrides):
    """Full jury path ending in ACCEPTED (PRD §3.3)."""
    app = create_under_jury_application(market_id, vendor_id, scores,
                                        juror_prefix, **app_overrides)
    return get_success_data(decide_application(market_id, app["id"], "ACCEPTED"))


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy — market + vendor + accepted application + booth
# ---------------------------------------------------------------------------

def setup_accepted_application(market_overrides=None, vendor_overrides=None,
                               app_overrides=None, booth_overrides=None,
                               scores=(80, 80, 80), clock: str = SETUP_CLOCK,
                               include_booth: bool = True):
    """Market (SETUP) + Vendor + application decided ACCEPTED (+ one Booth).
    Returns dict(market, vendor, application, booth)."""
    market = create_market(market_overrides, clock=clock)
    vendor = create_vendor_entity(**(vendor_overrides or {}))
    app = create_accepted_application(market["id"], vendor["id"], scores=scores,
                                      **(app_overrides or {}))
    booth = (create_booth_entity(market["id"], **(booth_overrides or {}))
             if include_booth else None)
    return {"market": market, "vendor": vendor, "application": app, "booth": booth}


# ---------------------------------------------------------------------------
# Tier 3: Assignment lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_assignment_for(market_id: str, booth_id: str, application_id: str):
    """Create a BoothAssignment (starts PENDING_PAYMENT, PRD §3.4)."""
    res = api_client.create_assignment(
        market_id, create_assignment_payload(booth_id, application_id), OPERATOR)
    return get_success_data(res)


def activate_assignment(market_id: str, assignment_id: str):
    """PENDING_PAYMENT -> ACTIVE. Returns the activated assignment."""
    return get_success_data(api_client.activate_assignment(market_id, assignment_id, OPERATOR))


def setup_active_assignment(market_overrides=None, vendor_overrides=None,
                            app_overrides=None, booth_overrides=None,
                            scores=(80, 80, 80), clock: str = SETUP_CLOCK):
    """setup_accepted_application + assignment created and ACTIVE.
    Returns dict(market, vendor, application, booth, assignment)."""
    ctx = setup_accepted_application(market_overrides, vendor_overrides, app_overrides,
                                     booth_overrides, scores, clock)
    asg = create_assignment_for(ctx["market"]["id"], ctx["booth"]["id"],
                                ctx["application"]["id"])
    ctx["assignment"] = activate_assignment(ctx["market"]["id"], asg["id"])
    return ctx


def open_market(market_id: str, clock: str = OPEN_CLOCK):
    """Advance the clock, then open the market with its CURRENT version
    (OCC, PRD §2.7/§3.8). Returns the raw response."""
    set_clock(clock)
    market = get_market(market_id)
    return api_client.open_market(
        market_id, {"expected_market_version": market["version"]}, OPERATOR)


def setup_open_market(market_overrides=None, vendor_overrides=None,
                      app_overrides=None, booth_overrides=None,
                      scores=(80, 80, 80), clock: str = SETUP_CLOCK,
                      open_clock: str = OPEN_CLOCK):
    """Active assignment + market opened to OPEN posture (PRD §3.8 requires at
    least one ACTIVE booth assignment). Returns ctx with refreshed market."""
    ctx = setup_active_assignment(market_overrides, vendor_overrides, app_overrides,
                                  booth_overrides, scores, clock)
    ctx["market"] = get_success_data(open_market(ctx["market"]["id"], clock=open_clock))
    return ctx


def setup_active_pos_device(device_code: str = None, open_clock: str = OPEN_CLOCK,
                            **setup_kwargs):
    """Open market + ACTIVE assignment + ACTIVE PosDevice (PRD §3.6).
    PosDevice activation requires assignment ACTIVE, shared_pos_enabled true,
    and posture OPEN."""
    ctx = setup_open_market(**setup_kwargs)
    payload = create_pos_device_payload(ctx["assignment"]["id"])
    if device_code:
        payload["device_code"] = device_code
    device = get_success_data(api_client.create_pos_device(ctx["market"]["id"], payload,
                                                           OPERATOR))
    ctx["pos_device"] = get_success_data(
        api_client.activate_pos_device(ctx["market"]["id"], device["id"], OPERATOR))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: Settlement accumulation / vendor metrics
# ---------------------------------------------------------------------------

def create_settlement(market_id: str, vendor_id: str, assignment_id: str,
                      business_date: str, gross_card_cents: int,
                      gross_cash_cents: int = 0, refund_cents: int = 0):
    """Create a DRAFT settlement (pos_fee_cents / net_payable_cents computed
    at creation, PRD §3.6)."""
    payload = create_settlement_payload(assignment_id, business_date,
                                        gross_card_cents, gross_cash_cents,
                                        refund_cents=refund_cents)
    res = api_client.create_settlement(market_id, payload, make_vendor_headers(vendor_id))
    return get_success_data(res)


def submit_settlement(market_id: str, settlement_id: str, vendor_id: str):
    return get_success_data(api_client.submit_settlement(market_id, settlement_id,
                                                         make_vendor_headers(vendor_id)))


def reconcile_settlement(market_id: str, settlement_id: str):
    return get_success_data(api_client.reconcile_settlement(market_id, settlement_id,
                                                            FINANCE))


def setup_submitted_settlement(business_date: str = "2026-12-05",
                               gross_card_cents: int = 10000,
                               gross_cash_cents: int = 0,
                               refund_cents: int = 0, **setup_kwargs):
    """Open market + ACTIVE assignment + one SUBMITTED settlement.
    Returns ctx with settlement."""
    ctx = setup_open_market(**setup_kwargs)
    st = create_settlement(ctx["market"]["id"], ctx["vendor"]["id"],
                           ctx["assignment"]["id"], business_date,
                           gross_card_cents, gross_cash_cents, refund_cents)
    ctx["settlement"] = submit_settlement(ctx["market"]["id"], st["id"],
                                          ctx["vendor"]["id"])
    return ctx


def setup_reconciled_settlement(**kwargs):
    """setup_submitted_settlement + FinanceOfficer reconcile (recomputes the
    vendor's renewal_score, PRD §3.6/§3.10)."""
    ctx = setup_submitted_settlement(**kwargs)
    ctx["settlement"] = reconcile_settlement(ctx["market"]["id"], ctx["settlement"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: Permits, hookups, load slots, weather, renewal offers
# ---------------------------------------------------------------------------

def create_permit_for(market_id: str, assignment_id: str,
                      permit_type: str = "TEMP_STRUCTURE", **overrides):
    payload = create_permit_payload(assignment_id, permit_type, **overrides)
    return get_success_data(api_client.create_permit(market_id, payload, OPERATOR))


def create_installed_hookup(market_id: str, booth_id: str,
                            hookup_type: str = "PROPANE"):
    """REQUESTED -> INSTALLED (requires market SETUP, PRD §3.5)."""
    hookup = get_success_data(api_client.create_hookup(
        market_id, create_hookup_payload(booth_id, hookup_type), UTILITY))
    return get_success_data(api_client.install_hookup(market_id, hookup["id"], UTILITY))


def create_load_slot_for(market_id: str, assignment_id: str, **overrides):
    payload = create_load_slot_payload(assignment_id, **overrides)
    return get_success_data(api_client.create_load_slot(market_id, payload, OPERATOR))


def create_weather_event(market_id: str, **overrides):
    payload = create_weather_event_payload(**overrides)
    return get_success_data(api_client.create_weather_event(market_id, payload, OPERATOR))


def create_renewal_offer_for(market_id: str, vendor_id: str, prior_assignment_id: str,
                             offered_booth_id: str, **overrides):
    payload = create_renewal_offer_payload(vendor_id, prior_assignment_id,
                                           offered_booth_id, **overrides)
    return get_success_data(api_client.create_renewal_offer(market_id, payload, OPERATOR))
