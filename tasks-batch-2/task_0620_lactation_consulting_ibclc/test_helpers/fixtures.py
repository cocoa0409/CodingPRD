"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through several API
calls to reach a testable state (e.g. a COMPLETED consult takes practice ->
consultant -> client -> set-clock -> consult -> feeding-assessment -> start ->
complete). These helpers encapsulate those chains so tests focus on assertions.

All helpers use get_success_data() (lenient validator) internally so setup
failures surface as clear "setup failed" errors rather than confusing
assertion failures. Consultant calls are ownership-gated, so they thread the
real Consultant.id via make_consultant_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_practice_payload,
    create_sliding_scale_tier_payload,
    create_service_package_payload,
    create_consultant_payload,
    create_client_payload,
    create_consult_payload,
    create_feeding_assessment_payload,
    create_follow_up_plan_payload,
    create_weighted_feed_payload,
    create_superbill_payload,
    create_dme_qualification_payload,
    create_pediatrician_referral_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_consultant_headers, make_client_headers

ADMIN = TEST_USERS["practice_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ─── Tier 1: Primitive creators ──────────────────────────────────────────────

def create_practice(aca_preventive_enabled=None, name="Bay Lactation"):
    """Create a practice. Pass aca_preventive_enabled to override the default."""
    overrides = {"name": name}
    if aca_preventive_enabled is not None:
        overrides["aca_preventive_enabled"] = aca_preventive_enabled
    return get_success_data(api_client.create_practice(
        create_practice_payload(**overrides), ADMIN))


def set_clock(practice_id, to_iso8601):
    """Advance a practice's logical clock to the given instant."""
    return get_success_data(api_client.set_clock(
        set_clock_payload(practice_id, to_iso8601), ADMIN))


def create_consultant(practice_id, **overrides):
    return get_success_data(api_client.create_consultant(
        create_consultant_payload(practice_id, **overrides), ADMIN))


def create_client(practice_id, **overrides):
    return get_success_data(api_client.create_client(
        create_client_payload(practice_id, **overrides), FRONT_DESK))


def create_tier(practice_id, name, income_ceiling_cents, discount_pct):
    return get_success_data(api_client.create_sliding_scale_tier(
        create_sliding_scale_tier_payload(
            practice_id, name, income_ceiling_cents, discount_pct), ADMIN))


def create_package(practice_id, name, included_visits, price_cents):
    return get_success_data(api_client.create_service_package(
        create_service_package_payload(
            practice_id, name, included_visits, price_cents), ADMIN))


def create_consult(practice_id, client_id, consultant_id,
                   scheduled_start_utc, scheduled_end_utc,
                   consult_type="TELEHEALTH", pay_method="SELF_PAY"):
    return get_success_data(api_client.create_consult(
        create_consult_payload(
            practice_id, client_id, consultant_id,
            scheduled_start_utc, scheduled_end_utc,
            consult_type=consult_type, pay_method=pay_method), FRONT_DESK))


# ─── Tier 2: Practice setup helpers ──────────────────────────────────────────

def setup_practice_with_consultant_and_client(aca_preventive_enabled=None,
                                              clock_utc=None,
                                              client_overrides=None,
                                              consultant_overrides=None):
    """Practice + one consultant + one ACTIVE client, clock optionally advanced.

    Returns dict: {practice, consultant, client}.
    """
    practice = create_practice(aca_preventive_enabled=aca_preventive_enabled)
    consultant = create_consultant(practice["id"], **(consultant_overrides or {}))
    client = create_client(practice["id"], **(client_overrides or {}))
    if clock_utc is not None:
        set_clock(practice["id"], clock_utc)
    return {"practice": practice, "consultant": consultant, "client": client}


# ─── Tier 3: Consult lifecycle shortcuts ─────────────────────────────────────

def record_feeding_assessment(consult_id, consultant_id, **overrides):
    """Record a feeding assessment (ownership-gated on the Consultant)."""
    return get_success_data(api_client.create_feeding_assessment(
        create_feeding_assessment_payload(consult_id, **overrides),
        make_consultant_headers(consultant_id)))


def start_consult(consult_id, consultant_id):
    return get_success_data(api_client.start_consult(
        consult_id, make_consultant_headers(consultant_id)))


def complete_consult(consult_id, consultant_id):
    return get_success_data(api_client.complete_consult(
        consult_id, make_consultant_headers(consultant_id)))


def create_completed_consult(practice=None, aca_preventive_enabled=None,
                             clock_utc="2026-06-10T15:00:00Z",
                             start_utc="2026-06-10T15:00:00Z",
                             end_utc="2026-06-10T16:00:00Z",
                             consult_type="TELEHEALTH", pay_method="SELF_PAY",
                             client_overrides=None):
    """Walk practice -> consultant -> client -> clock -> consult -> assessment
    -> start -> complete and return a fully COMPLETED consult.

    Returns dict: {practice, consultant, client, consult}.
    """
    ctx = setup_practice_with_consultant_and_client(
        aca_preventive_enabled=aca_preventive_enabled,
        clock_utc=clock_utc,
        client_overrides=client_overrides,
    )
    consult = create_consult(
        ctx["practice"]["id"], ctx["client"]["id"], ctx["consultant"]["id"],
        start_utc, end_utc, consult_type=consult_type, pay_method=pay_method)
    record_feeding_assessment(consult["id"], ctx["consultant"]["id"])
    start_consult(consult["id"], ctx["consultant"]["id"])
    consult = complete_consult(consult["id"], ctx["consultant"]["id"])
    ctx["consult"] = consult
    return ctx


def create_in_progress_consult(clock_utc="2026-06-10T15:00:00Z",
                               start_utc="2026-06-10T15:00:00Z",
                               end_utc="2026-06-10T16:00:00Z"):
    """Walk to an IN_PROGRESS consult (started, not completed).

    Returns dict: {practice, consultant, client, consult}.
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc=clock_utc)
    consult = create_consult(
        ctx["practice"]["id"], ctx["client"]["id"], ctx["consultant"]["id"],
        start_utc, end_utc)
    record_feeding_assessment(consult["id"], ctx["consultant"]["id"])
    consult = start_consult(consult["id"], ctx["consultant"]["id"])
    ctx["consult"] = consult
    return ctx


# ─── Tier 4: Follow-up plans & superbills ────────────────────────────────────

def open_follow_up_plan(consult_id, consultant_id, target_daily_transfer_grams):
    return get_success_data(api_client.create_follow_up_plan(
        create_follow_up_plan_payload(consult_id, target_daily_transfer_grams),
        make_consultant_headers(consultant_id)))


def add_weighted_feed(plan_id, consultant_id, pre_feed_weight_grams,
                      post_feed_weight_grams):
    return get_success_data(api_client.create_weighted_feed(
        create_weighted_feed_payload(plan_id, pre_feed_weight_grams,
                                     post_feed_weight_grams),
        make_consultant_headers(consultant_id)))


def close_follow_up_plan(plan_id, consultant_id):
    return get_success_data(api_client.close_follow_up_plan(
        plan_id, make_consultant_headers(consultant_id)))


def create_open_follow_up_plan(target_daily_transfer_grams=100):
    """COMPLETED consult + an OPEN follow-up plan against it.

    Returns dict: {practice, consultant, client, consult, plan}.
    """
    ctx = create_completed_consult()
    plan = open_follow_up_plan(
        ctx["consult"]["id"], ctx["consultant"]["id"], target_daily_transfer_grams)
    ctx["plan"] = plan
    return ctx


def draft_superbill(consult_id, billed_amount_cents, allowed_amount_cents, **overrides):
    return get_success_data(api_client.create_superbill(
        create_superbill_payload(consult_id, billed_amount_cents,
                                 allowed_amount_cents, **overrides), BILLING))


def submit_superbill(superbill_id):
    return get_success_data(api_client.submit_superbill(superbill_id, BILLING))


def adjudicate_superbill(superbill_id, outcome):
    return get_success_data(api_client.adjudicate_superbill(
        superbill_id, {"outcome": outcome}, BILLING))


def create_submitted_superbill(billed_amount_cents=25000, allowed_amount_cents=15000,
                               is_aca_preventive=True, deductible_remaining_cents=None,
                               coinsurance_pct=None):
    """COMPLETED consult -> DRAFT superbill -> SUBMITTED superbill.

    Returns dict: {practice, consultant, client, consult, superbill}.
    """
    ctx = create_completed_consult()
    overrides = {"is_aca_preventive": is_aca_preventive}
    if deductible_remaining_cents is not None:
        overrides["deductible_remaining_cents"] = deductible_remaining_cents
    if coinsurance_pct is not None:
        overrides["coinsurance_pct"] = coinsurance_pct
    sb = draft_superbill(ctx["consult"]["id"], billed_amount_cents,
                         allowed_amount_cents, **overrides)
    sb = submit_superbill(sb["id"])
    ctx["superbill"] = sb
    return ctx


def create_paid_superbill(billed_amount_cents=25000, allowed_amount_cents=15000,
                          is_aca_preventive=True, deductible_remaining_cents=None,
                          coinsurance_pct=None):
    """COMPLETED consult -> SUBMITTED -> PAID superbill (ledger increased).

    Returns dict: {practice, consultant, client, consult, superbill}.
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=billed_amount_cents,
        allowed_amount_cents=allowed_amount_cents,
        is_aca_preventive=is_aca_preventive,
        deductible_remaining_cents=deductible_remaining_cents,
        coinsurance_pct=coinsurance_pct)
    ctx["superbill"] = adjudicate_superbill(ctx["superbill"]["id"], "PAID")
    return ctx


def get_client(client_id):
    """Re-read a client to capture its current computed fields / version."""
    return get_success_data(api_client.get_client(client_id, BILLING))


# ─── Tier 5: DME & referrals ─────────────────────────────────────────────────

def request_dme(consult_id, pump_type, as_billing=True):
    headers = BILLING
    return get_success_data(api_client.create_dme_qualification(
        create_dme_qualification_payload(consult_id, pump_type), headers))


def create_pending_dme(pump_type="STANDARD_ELECTRIC",
                       infant_dob="2026-06-01T00:00:00Z",
                       consult_clock="2026-06-20T15:00:00Z",
                       request_clock="2026-07-01T00:00:00Z"):
    """COMPLETED consult (IN_HOME), then advance clock and request a PENDING DME.

    The consult is created/completed at consult_clock; the clock is then moved to
    request_clock so requested_utc is stamped there (driving the window rule).

    Returns dict: {practice, consultant, client, consult, dme}.
    """
    ctx = create_completed_consult(
        clock_utc=consult_clock,
        start_utc=consult_clock,
        end_utc="2026-06-20T16:00:00Z",
        consult_type="IN_HOME",
        client_overrides={"infant_dob": infant_dob})
    set_clock(ctx["practice"]["id"], request_clock)
    dme = request_dme(ctx["consult"]["id"], pump_type)
    ctx["dme"] = dme
    return ctx


def create_referral(consult_id, consultant_id, reason="WEIGHT_CONCERN",
                    pediatrician_name="Dr Lee"):
    return get_success_data(api_client.create_pediatrician_referral(
        create_pediatrician_referral_payload(consult_id, reason=reason,
                                             pediatrician_name=pediatrician_name),
        make_consultant_headers(consultant_id)))


# ─── Tier 6: No-show / suspension cascade staging ────────────────────────────

def no_show_consult(consult_id):
    return get_success_data(api_client.no_show_consult(consult_id, FRONT_DESK))


def cancel_consult(consult_id):
    return get_success_data(api_client.cancel_consult(consult_id, FRONT_DESK))


def setup_client_with_two_strikes(clock_utc="2026-06-10T10:00:00Z"):
    """A client with exactly 2 no-show strikes (still ACTIVE).

    Creates two short SELF_PAY consults in the past relative to the clock and
    no-shows them. Returns dict: {practice, consultant, client}.
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc=clock_utc)
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    c1 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T09:00:00Z", "2026-06-10T09:15:00Z")
    no_show_consult(c1["id"])
    c2 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T09:15:00Z", "2026-06-10T09:30:00Z")
    no_show_consult(c2["id"])
    return ctx


def setup_suspended_client(clock_utc="2026-06-10T10:00:00Z"):
    """A SUSPENDED client (3 no-show strikes). Returns {practice, consultant, client}."""
    ctx = setup_client_with_two_strikes(clock_utc=clock_utc)
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    c3 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T09:30:00Z", "2026-06-10T09:45:00Z")
    no_show_consult(c3["id"])
    return ctx
