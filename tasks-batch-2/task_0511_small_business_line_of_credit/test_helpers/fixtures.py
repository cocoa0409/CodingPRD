"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific state reached only after a long
chain of API calls (merchant -> bank feed -> application -> submit -> approve -> credit-line ->
draws -> remittances -> NSF chain -> default -> charge-off). These helpers encapsulate those
chains so tests focus on assertions.

All helpers use get_success_data() (lenient) internally so a setup failure surfaces as a clear
"Setup step failed" rather than a confusing assertion failure.

Identity threading: roles are opaque (PRD §2.1), but the server *records* X-User-ID as an audit
anchor for segregation-of-duties (submitted_by_user_id, defaulted_by_user_id). These helpers
therefore pass explicit X-User-IDs (uw_1 submits, uw_2 approves, co_default declares default,
co_chargeoff charges off) so SoD-sensitive sequences succeed.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_merchant_payload,
    create_bank_feed_payload,
    create_application_payload,
    submit_application_payload,
    create_credit_line_payload,
    create_draw_payload,
    create_remittance_payload,
    settle_remittance_payload,
    declare_default_payload,
    charge_off_payload,
)
from .test_users import (
    make_underwriter_headers,
    make_servicer_headers,
    make_credit_officer_headers,
)

# Standard operator identities used across fixtures (PRD §2.1 audit anchors).
UW1 = make_underwriter_headers("uw_1")
UW2 = make_underwriter_headers("uw_2")
SV1 = make_servicer_headers("sv_1")
CO1 = make_credit_officer_headers("co_1")
CO_DEFAULT = make_credit_officer_headers("co_default")
CO_CHARGEOFF = make_credit_officer_headers("co_chargeoff")


# ─── primitives ───────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, SV1))


def create_merchant(**overrides):
    return get_success_data(api_client.create_merchant(create_merchant_payload(**overrides)))


def create_bank_feed(merchant_id: str, **overrides):
    return get_success_data(
        api_client.create_bank_feed(merchant_id, create_bank_feed_payload(**overrides), UW1)
    )


# ─── Tier 1/2: application lifecycle ──────────────────────────────────
def create_draft_application(merchant_overrides=None, feed_overrides=None, app_overrides=None):
    """Merchant + FRESH feed + DRAFT application. Returns (merchant, feed, application)."""
    merchant = create_merchant(**(merchant_overrides or {}))
    feed = create_bank_feed(merchant["id"], **(feed_overrides or {}))
    app = get_success_data(
        api_client.create_application(
            create_application_payload(merchant["id"], feed["id"], **(app_overrides or {})),
            UW1,
        )
    )
    return merchant, feed, app


def create_submitted_application(
    merchant_overrides=None, feed_overrides=None, app_overrides=None
):
    """DRAFT application submitted by uw_1 (risk_score computed). Returns (merchant, feed, app)."""
    merchant, feed, app = create_draft_application(
        merchant_overrides, feed_overrides, app_overrides
    )
    app = get_success_data(
        api_client.submit_application(app["id"], UW1, submit_application_payload())
    )
    return merchant, feed, app


def create_approved_application(
    merchant_overrides=None, feed_overrides=None, app_overrides=None
):
    """Submitted-then-approved application (uw_1 submits, uw_2 approves). Returns (m, feed, app)."""
    merchant, feed, app = create_submitted_application(
        merchant_overrides, feed_overrides, app_overrides
    )
    app = get_success_data(api_client.approve_application(app["id"], UW2))
    return merchant, feed, app


# ─── Tier 1/3: credit line activation ─────────────────────────────────
def create_active_credit_line(
    cadence="DAILY",
    merchant_overrides=None,
    feed_overrides=None,
    app_overrides=None,
):
    """Full origination to an ACTIVE CreditLine. Returns (merchant, feed, application, line)."""
    merchant, feed, app = create_approved_application(
        merchant_overrides, feed_overrides, app_overrides
    )
    line = get_success_data(
        api_client.create_credit_line(create_credit_line_payload(app["id"], remittance_cadence=cadence), CO1)
    )
    return merchant, feed, app, line


def get_line(line_id):
    return get_success_data(api_client.get_credit_line(line_id, CO1))


# ─── draws ─────────────────────────────────────────────────────────────
def take_draw(line_id, principal_cents):
    return get_success_data(
        api_client.create_draw(line_id, create_draw_payload(principal_cents), SV1)
    )


def create_active_line_with_draw(
    principal_cents, cadence="DAILY", feed_overrides=None
):
    """ACTIVE line with one OUTSTANDING draw. Returns (line, draw)."""
    _, _, _, line = create_active_credit_line(cadence=cadence, feed_overrides=feed_overrides)
    draw = take_draw(line["id"], principal_cents)
    return line, draw


# ─── remittances ───────────────────────────────────────────────────────
def schedule_remittance(line_id, scheduled_for):
    return get_success_data(
        api_client.create_remittance(line_id, create_remittance_payload(scheduled_for), SV1)
    )


def settle_remittance(remittance_id, outcome):
    return get_success_data(
        api_client.settle_remittance(remittance_id, settle_remittance_payload(outcome), SV1)
    )


# ─── Tier 4: NSF chain → DELINQUENT / nsf_strike_count targeting ──────
def drive_line_to_strikes(
    line_id,
    first_scheduled_for,
    first_clock,
    num_nsf,
    retry_gap_days=2,
):
    """
    Settle an NSF chain `num_nsf` times so the line accrues `num_nsf` strikes.

    Schedules a first remittance at `first_scheduled_for`, then for each NSF settle advances the
    logical clock to the remittance's scheduled_for and settles NSF. Each NSF (while attempt_count
    < NSF_MAX_RETRIES) spawns a retry two days later via next_retry_remittance_id (PRD §3.5); the
    helper follows that pointer for the next settle.

    `first_clock` is set BEFORE scheduling so the schedule is in the future. Returns the LAST
    settled remittance dict (whose next_retry_remittance_id, if any, points at the still-SCHEDULED
    retry).
    """
    set_clock(first_clock)
    remit = schedule_remittance(line_id, first_scheduled_for)
    last = None
    current = remit
    for i in range(num_nsf):
        set_clock(current["scheduled_for"])
        last = settle_remittance(current["id"], "NSF")
        next_id = last.get("next_retry_remittance_id")
        if next_id:
            current = get_success_data(api_client.get_remittance(next_id, SV1))
    return last


def setup_delinquent_line(
    principal_cents=200_000,
    cadence="DAILY",
    first_scheduled_for="2026-05-15T00:00:00Z",
    first_clock="2026-05-13T00:00:00Z",
):
    """
    ACTIVE line with one OUTSTANDING draw driven to DELINQUENT via 3 NSF strikes
    (NSF_DELINQUENCY_THRESHOLD). A SCHEDULED retry remittance remains pending.
    Returns (line, draw, last_settled_remittance).
    """
    set_clock(first_clock)
    line, draw = create_active_line_with_draw(
        principal_cents, cadence=cadence, feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
    )
    last = drive_line_to_strikes(line["id"], first_scheduled_for, first_clock, num_nsf=3)
    return line, draw, last


def setup_line_at_default_threshold(
    principal_cents=200_000,
    cadence="DAILY",
    first_scheduled_for="2026-05-15T00:00:00Z",
    first_clock="2026-05-13T00:00:00Z",
):
    """
    Line driven to nsf_strike_count == 5 (NSF_DEFAULT_THRESHOLD) via a single NSF retry chain;
    still DELINQUENT (not yet declared). Returns (line, draw, last_settled_remittance).
    """
    set_clock(first_clock)
    line, draw = create_active_line_with_draw(
        principal_cents, cadence=cadence, feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
    )
    last = drive_line_to_strikes(line["id"], first_scheduled_for, first_clock, num_nsf=5)
    return line, draw, last


def setup_defaulted_line(
    principal_cents=200_000,
    declared_by=CO_DEFAULT,
):
    """
    DEFAULTED line: driven to 5 strikes then declare-default (default declared by `declared_by`,
    co_default by convention). Returns (line, draw, line_after_default).
    """
    line, draw, _ = setup_line_at_default_threshold(principal_cents=principal_cents)
    ver = get_line(line["id"])["version"]
    line_after = get_success_data(
        api_client.declare_default(line["id"], declare_default_payload(ver), declared_by)
    )
    return line, draw, line_after


def setup_charged_off_line(principal_cents=200_000):
    """
    CHARGED_OFF line: default declared by co_default, charge-off by co_chargeoff (SoD-compliant).
    Returns (line, draw, line_after_chargeoff).
    """
    line, draw, line_after_default = setup_defaulted_line(principal_cents=principal_cents)
    ver = line_after_default["version"]
    line_after = get_success_data(
        api_client.charge_off(line["id"], charge_off_payload(ver), CO_CHARGEOFF)
    )
    return line, draw, line_after
