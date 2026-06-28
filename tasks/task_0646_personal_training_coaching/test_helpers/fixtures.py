"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through several API calls
to reach a testable state (e.g. an ACTIVE SESSION_PACK engagement takes
set-clock -> trainer -> client -> submit-intake -> assess -> engagement ->
session-pack). These helpers encapsulate those chains so tests focus on
assertions.

All helpers use get_success_data() (lenient validator) internally so setup
failures surface as clear errors rather than confusing assertion failures.
Trainer and Client calls are ownership-gated, so they thread the real
Trainer.id / Client.id via make_trainer_headers() / make_client_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_trainer_payload,
    create_client_payload,
    create_engagement_payload,
    create_session_pack_payload,
    create_booking_payload,
    create_program_assignment_payload,
    create_macro_plan_payload,
    create_check_in_payload,
    create_habit_log_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_trainer_headers, make_client_headers

ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ─── Tier 0: Logical clock ───────────────────────────────────────────────────

def set_clock(to_iso8601):
    """Advance the server logical clock to the given instant (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ─── Tier 1: Primitive creators ──────────────────────────────────────────────

def create_trainer(**overrides):
    """Register a trainer (PlatformAdmin). Returns the Trainer dict."""
    return get_success_data(api_client.create_trainer(
        create_trainer_payload(**overrides), ADMIN))


def create_client(trainer_id, **overrides):
    """Create a DRAFT client owned by trainer_id (ownership-gated on Trainer)."""
    return get_success_data(api_client.create_client(
        create_client_payload(trainer_id, **overrides),
        make_trainer_headers(trainer_id)))


def submit_intake(client_id):
    return get_success_data(api_client.submit_intake(
        client_id, make_client_headers(client_id)))


def assess_client(trainer_id, client_id):
    return get_success_data(api_client.assess_client(
        client_id, make_trainer_headers(trainer_id)))


# ─── Tier 2: Assessed client ─────────────────────────────────────────────────

def create_assessed_client(trainer_id, **client_overrides):
    """Create a client and walk it DRAFT -> SUBMITTED -> ASSESSED.

    Returns the ASSESSED Client dict (carries the post-assess version).
    """
    client = create_client(trainer_id, **client_overrides)
    submit_intake(client["id"])
    return assess_client(trainer_id, client["id"])


def setup_trainer_and_assessed_client(clock_utc=DEFAULT_CLOCK, client_overrides=None):
    """Clock + trainer + one ASSESSED client.

    Returns dict: {trainer, client} where client is the post-assess record.
    """
    if clock_utc is not None:
        set_clock(clock_utc)
    trainer = create_trainer()
    client = create_assessed_client(trainer["id"], **(client_overrides or {}))
    return {"trainer": trainer, "client": client}


# ─── Tier 3: Engagement creators ─────────────────────────────────────────────

def create_engagement(trainer_id, client_id, expected_client_version,
                      billing_model="SESSION_PACK", **overrides):
    """Create an engagement for an ASSESSED client (ownership-gated on Trainer)."""
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(client_id, expected_client_version,
                                  billing_model=billing_model, **overrides),
        make_trainer_headers(trainer_id)))


def setup_session_pack_engagement(clock_utc=DEFAULT_CLOCK, client_overrides=None):
    """Clock + trainer + ASSESSED client + ACTIVE SESSION_PACK engagement.

    Returns dict: {trainer, client, engagement}.
    """
    ctx = setup_trainer_and_assessed_client(clock_utc=clock_utc,
                                            client_overrides=client_overrides)
    engagement = create_engagement(
        ctx["trainer"]["id"], ctx["client"]["id"], ctx["client"]["version"],
        billing_model="SESSION_PACK")
    return {"trainer": ctx["trainer"], "client": ctx["client"], "engagement": engagement}


def setup_subscription_engagement(clock_utc=DEFAULT_CLOCK, monthly_fee_cents=6000,
                                  cycle_start_utc=None, client_overrides=None):
    """Clock + trainer + ASSESSED client + ACTIVE ONLINE_SUBSCRIPTION engagement.

    cycle_start_utc defaults to clock_utc. Returns {trainer, client, engagement}.
    """
    ctx = setup_trainer_and_assessed_client(clock_utc=clock_utc,
                                            client_overrides=client_overrides)
    engagement = create_engagement(
        ctx["trainer"]["id"], ctx["client"]["id"], ctx["client"]["version"],
        billing_model="ONLINE_SUBSCRIPTION",
        monthly_fee_cents=monthly_fee_cents,
        cycle_start_utc=cycle_start_utc or clock_utc)
    return {"trainer": ctx["trainer"], "client": ctx["client"], "engagement": engagement}


# ─── Tier 4: Session packs and bookings ──────────────────────────────────────

def create_pack(trainer_id, engagement_id, total_sessions=5, price_cents=50000):
    """Purchase a SessionPack (ownership-gated on Trainer). Returns pack dict."""
    return get_success_data(api_client.create_session_pack(
        engagement_id,
        create_session_pack_payload(total_sessions=total_sessions, price_cents=price_cents),
        make_trainer_headers(trainer_id)))


def get_pack(trainer_id, pack_id):
    return get_success_data(api_client.get_session_pack(
        pack_id, make_trainer_headers(trainer_id)))


def setup_pack_engagement(clock_utc=DEFAULT_CLOCK, total_sessions=5, price_cents=50000,
                          client_overrides=None):
    """Clock + trainer + ASSESSED client + ACTIVE SESSION_PACK engagement + one pack.

    Returns dict: {trainer, client, engagement, pack}.
    """
    ctx = setup_session_pack_engagement(clock_utc=clock_utc, client_overrides=client_overrides)
    pack = create_pack(ctx["trainer"]["id"], ctx["engagement"]["id"],
                       total_sessions=total_sessions, price_cents=price_cents)
    return {**ctx, "pack": pack}


def book_pack_session(trainer_id, engagement_id, pack_id, expected_version,
                      start_utc, end_utc, as_client_id=None):
    """Create a SESSION_PACK booking. Acts as the Trainer unless as_client_id given."""
    headers = (make_client_headers(as_client_id) if as_client_id
               else make_trainer_headers(trainer_id))
    return get_success_data(api_client.create_booking(
        create_booking_payload(engagement_id, start_utc, end_utc,
                               session_pack_id=pack_id,
                               expected_session_pack_version=expected_version),
        headers))


def book_subscription_session(trainer_id, engagement_id, start_utc, end_utc,
                              as_client_id=None):
    """Create an ONLINE_SUBSCRIPTION booking (no pack). Trainer unless as_client_id."""
    headers = (make_client_headers(as_client_id) if as_client_id
               else make_trainer_headers(trainer_id))
    return get_success_data(api_client.create_booking(
        create_booking_payload(engagement_id, start_utc, end_utc), headers))


# ─── Tier 5: Programs, check-ins, macro plans ────────────────────────────────

def create_program(trainer_id, engagement_id, planned_workouts_per_week=4,
                   habit_checks_target=10, title="Phase 1"):
    return get_success_data(api_client.create_program_assignment(
        create_program_assignment_payload(
            engagement_id, title=title,
            planned_workouts_per_week=planned_workouts_per_week,
            habit_checks_target=habit_checks_target),
        make_trainer_headers(trainer_id)))


def publish_program(trainer_id, program_id):
    return get_success_data(api_client.publish_program(
        program_id, make_trainer_headers(trainer_id)))


def create_published_program(trainer_id, engagement_id, planned_workouts_per_week=4,
                             habit_checks_target=10):
    """Create and publish a program. Returns the PUBLISHED program dict."""
    program = create_program(trainer_id, engagement_id,
                             planned_workouts_per_week=planned_workouts_per_week,
                             habit_checks_target=habit_checks_target)
    return publish_program(trainer_id, program["id"])


def log_habit(client_id, engagement_id, program_id, kind, logged_at):
    return get_success_data(api_client.create_habit_log(
        create_habit_log_payload(engagement_id, program_id, kind, logged_at),
        make_client_headers(client_id)))


def submit_check_in(client_id, engagement_id, measured_at, weight_kg,
                    window_start_utc, window_end_utc, **overrides):
    return get_success_data(api_client.create_check_in(
        engagement_id,
        create_check_in_payload(measured_at, weight_kg, window_start_utc,
                                window_end_utc, **overrides),
        make_client_headers(client_id)))


def assess_check_in(trainer_id, check_in_id):
    return get_success_data(api_client.assess_check_in(
        check_in_id, make_trainer_headers(trainer_id)))


def setup_client_with_assessed_weight(clock_utc=DEFAULT_CLOCK, billing_model="ONLINE_SUBSCRIPTION",
                                      weight_kg=80, measured_at="2026-06-01T08:00:00Z",
                                      window_start_utc="2026-05-25T00:00:00Z",
                                      window_end_utc="2026-06-01T00:00:00Z",
                                      client_overrides=None, monthly_fee_cents=6000):
    """Engagement + one ASSESSED check-in so the client has a latest_weight_kg.

    Returns dict: {trainer, client, engagement, check_in}.
    """
    if billing_model == "SESSION_PACK":
        ctx = setup_session_pack_engagement(clock_utc=clock_utc, client_overrides=client_overrides)
    else:
        ctx = setup_subscription_engagement(clock_utc=clock_utc, monthly_fee_cents=monthly_fee_cents,
                                            client_overrides=client_overrides)
    check_in = submit_check_in(ctx["client"]["id"], ctx["engagement"]["id"],
                               measured_at, weight_kg, window_start_utc, window_end_utc)
    assess_check_in(ctx["trainer"]["id"], check_in["id"])
    return {**ctx, "check_in": check_in}


def create_macro_plan(trainer_id, engagement_id, goal="FAT_LOSS", activity_level="MODERATE"):
    return get_success_data(api_client.create_macro_plan(
        engagement_id, create_macro_plan_payload(goal=goal, activity_level=activity_level),
        make_trainer_headers(trainer_id)))


def setup_provisional_macro_plan(clock_utc=DEFAULT_CLOCK, weight_kg=80,
                                 goal="FAT_LOSS", activity_level="MODERATE",
                                 client_overrides=None):
    """Subscription engagement + ASSESSED check-in + PROVISIONAL macro plan.

    Returns dict: {trainer, client, engagement, check_in, macro_plan}.
    """
    ctx = setup_client_with_assessed_weight(
        clock_utc=clock_utc, billing_model="ONLINE_SUBSCRIPTION",
        weight_kg=weight_kg, client_overrides=client_overrides)
    macro_plan = create_macro_plan(ctx["trainer"]["id"], ctx["engagement"]["id"],
                                   goal=goal, activity_level=activity_level)
    return {**ctx, "macro_plan": macro_plan}
