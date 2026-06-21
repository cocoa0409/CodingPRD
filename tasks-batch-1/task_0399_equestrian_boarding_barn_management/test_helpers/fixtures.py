"""Composite setup helpers for multi-step test prerequisites.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Helpers use the
lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Identity threading: the Owner role is entity-backed, so every ownership-gated
Owner call (creating/signing a waiver, etc.) uses make_owner_headers(owner_id)
with the real Owner.id rather than the shared TEST_USERS["owner_headers"].
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_stall_payload,
    create_pasture_payload,
    create_horse_payload,
    create_boarding_agreement_payload,
    create_lesson_payload,
    create_service_visit_payload,
    create_show_entry_payload,
    create_turnout_payload,
    create_invoice_payload,
)
from .test_users import TEST_USERS, make_owner_headers

BM = TEST_USERS["barn_manager_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]
PROVIDER = TEST_USERS["service_provider_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the logical clock. Returns the response data (may be empty)."""
    return get_success_data(api_client.set_clock(to_iso8601, BM))


# ---------------------------------------------------------------------------
# Tier 1: base aggregates
# ---------------------------------------------------------------------------
def create_owner(**overrides):
    """Create an owner. Returns the owner dict."""
    return get_success_data(api_client.create_owner(create_owner_payload(**overrides), BM))


def adjust_deposit(owner_id: str, amount_cents: int):
    """Adjust an owner's held deposit. Returns the owner dict."""
    return get_success_data(
        api_client.adjust_deposit(owner_id, {"amount_cents": amount_cents}, BM)
    )


def create_signed_waiver(owner_id: str):
    """Create a PENDING waiver for the owner and sign it (PENDING -> SIGNED).
    Returns the signed waiver dict."""
    own_headers = make_owner_headers(owner_id)
    waiver = get_success_data(api_client.create_waiver(owner_id, own_headers))
    return get_success_data(
        api_client.sign_waiver(owner_id, waiver["id"], own_headers)
    )


def create_pending_waiver(owner_id: str):
    """Create a PENDING (unsigned) waiver. Returns the waiver dict."""
    own_headers = make_owner_headers(owner_id)
    return get_success_data(api_client.create_waiver(owner_id, own_headers))


def create_owner_with_signed_waiver(**owner_overrides):
    """Create an owner and give it a SIGNED waiver. Returns (owner, waiver)."""
    owner = create_owner(**owner_overrides)
    waiver = create_signed_waiver(owner["id"])
    return owner, waiver


def create_stall(**overrides):
    """Create a STALL (capacity 1 by default). Returns the stall dict."""
    return get_success_data(api_client.create_stall(create_stall_payload(**overrides), BM))


def create_pasture(capacity: int = 1, **overrides):
    """Create a PASTURE with the given capacity. Returns the stall dict."""
    return get_success_data(
        api_client.create_stall(create_pasture_payload(capacity=capacity, **overrides), BM)
    )


def create_horse(owner_id: str, **overrides):
    """Create a horse for an owner. Returns the horse dict."""
    return get_success_data(
        api_client.create_horse(create_horse_payload(owner_id, **overrides), BM)
    )


# ---------------------------------------------------------------------------
# Tier 2: boarding agreements
# ---------------------------------------------------------------------------
def create_draft_agreement(horse_id: str, stall_id: str,
                           start_date: str = "2026-06-01T00:00:00.000Z"):
    """Create a DRAFT boarding agreement. Returns the agreement dict."""
    return get_success_data(
        api_client.create_boarding_agreement(
            create_boarding_agreement_payload(horse_id, stall_id, start_date), BM
        )
    )


def transition_agreement(agreement_id: str, target_status: str):
    """Drive an agreement transition. Returns the agreement dict."""
    return get_success_data(
        api_client.transition_boarding_agreement(
            agreement_id, {"target_status": target_status}, BM
        )
    )


def create_active_boarding(daily_rate_cents: int = 4500,
                           start_date: str = "2026-06-01T00:00:00.000Z",
                           clock: str = "2026-06-01T00:00:00.000Z",
                           stall_capacity: int = 1):
    """Owner with SIGNED waiver + STALL + horse + ACTIVE agreement.

    Sets the clock first, creates everything, and activates the agreement.
    Returns dict(owner, waiver, stall, horse, agreement).
    """
    set_clock(clock)
    owner, waiver = create_owner_with_signed_waiver()
    stall = create_stall(capacity=stall_capacity, daily_rate_cents=daily_rate_cents)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"], start_date=start_date)
    agreement = transition_agreement(agreement["id"], "ACTIVE")
    return {
        "owner": owner,
        "waiver": waiver,
        "stall": stall,
        "horse": horse,
        "agreement": agreement,
    }


def create_ended_boarding(daily_rate_cents: int = 4500,
                          start_date: str = "2026-06-01T00:00:00.000Z",
                          activate_clock: str = "2026-06-01T00:00:00.000Z",
                          end_clock: str = "2026-06-11T00:00:00.000Z"):
    """Owner with SIGNED waiver + STALL + horse + agreement walked to ENDED.

    With the default dates this gives a 10-occupied-day, no-suspension agreement
    whose final_charge_cents == daily_rate_cents * 10.
    Returns dict(owner, waiver, stall, horse, agreement).
    """
    ctx = create_active_boarding(
        daily_rate_cents=daily_rate_cents, start_date=start_date, clock=activate_clock
    )
    set_clock(end_clock)
    ctx["agreement"] = transition_agreement(ctx["agreement"]["id"], "ENDED")
    return ctx


def get_owner(owner_id: str):
    """GET an owner (recomputes provisional_standing_score). Returns owner dict."""
    return get_success_data(api_client.get_owner(owner_id, BM))


# ---------------------------------------------------------------------------
# Tier 3: invoice lifecycle
# ---------------------------------------------------------------------------
def open_invoice(owner_id: str, period_label: str = "2026-06"):
    """Open a draft invoice for the owner. Returns the invoice dict."""
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(owner_id, period_label), BM)
    )


def finalize_invoice(invoice_id: str, owner_id: str):
    """Finalize an OPEN invoice using the owner's current version.

    Reads the owner first to capture the fresh version, then finalizes.
    Returns the finalized invoice dict.
    """
    owner = get_owner(owner_id)
    return get_success_data(
        api_client.transition_invoice(
            invoice_id,
            {"target_status": "FINALIZED", "expected_owner_version": owner["version"]},
            BM,
        )
    )


def setup_open_invoice_for_ended_boarding(daily_rate_cents: int = 4500):
    """One ENDED 10-day boarding (final = daily*10) + an OPEN invoice.

    Returns dict(owner, waiver, stall, horse, agreement, invoice).
    """
    ctx = create_ended_boarding(daily_rate_cents=daily_rate_cents)
    ctx["invoice"] = open_invoice(ctx["owner"]["id"])
    return ctx


def setup_finalized_invoice_for_ended_boarding(daily_rate_cents: int = 4500):
    """One ENDED 10-day boarding + a FINALIZED invoice (amount_due = daily*10
    when no deposit). Returns dict(owner, waiver, stall, horse, agreement, invoice).
    """
    ctx = setup_open_invoice_for_ended_boarding(daily_rate_cents=daily_rate_cents)
    ctx["invoice"] = finalize_invoice(ctx["invoice"]["id"], ctx["owner"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: lessons / visits / shows / turnouts
# ---------------------------------------------------------------------------
def create_lesson(horse_id: str, starts_at: str, ends_at: str,
                  lesson_fee_cents: int = 8000):
    """Schedule a lesson. Returns the lesson dict."""
    return get_success_data(
        api_client.create_lesson(
            create_lesson_payload(horse_id, starts_at, ends_at,
                                  lesson_fee_cents=lesson_fee_cents),
            BM,
        )
    )


def complete_lesson(lesson_id: str):
    """Instructor completes a lesson. Returns the lesson dict."""
    return get_success_data(
        api_client.transition_lesson(lesson_id, {"target_status": "COMPLETED"}, INSTRUCTOR)
    )


def no_show_lesson(lesson_id: str):
    """Instructor marks a lesson NO_SHOW. Returns the lesson dict."""
    return get_success_data(
        api_client.transition_lesson(lesson_id, {"target_status": "NO_SHOW"}, INSTRUCTOR)
    )


def create_service_visit(horse_id: str, scheduled_at: str,
                         visit_type: str = "FARRIER",
                         duration_minutes: int = 60, fee_cents: int = 12000):
    """Request a service visit. Returns the visit dict."""
    return get_success_data(
        api_client.create_service_visit(
            create_service_visit_payload(
                horse_id, scheduled_at, visit_type=visit_type,
                duration_minutes=duration_minutes, fee_cents=fee_cents,
            ),
            BM,
        )
    )


def schedule_service_visit(visit_id: str):
    """BarnManager schedules a requested visit. Returns the visit dict."""
    return get_success_data(
        api_client.transition_service_visit(visit_id, {"target_status": "SCHEDULED"}, BM)
    )


def complete_service_visit(visit_id: str):
    """ServiceProvider completes a scheduled visit. Returns the visit dict."""
    return get_success_data(
        api_client.transition_service_visit(visit_id, {"target_status": "COMPLETED"}, PROVIDER)
    )


def create_show_entry(horse_id: str, event_date: str = "2026-07-01T00:00:00.000Z",
                      entry_fee_cents: int = 5000, event_name: str = "County Show"):
    """Submit a show entry. Returns the entry dict."""
    return get_success_data(
        api_client.create_show_entry(
            create_show_entry_payload(horse_id, event_date,
                                      event_name=event_name,
                                      entry_fee_cents=entry_fee_cents),
            BM,
        )
    )


def confirm_show_entry(entry_id: str):
    """BarnManager confirms a submitted entry. Returns the entry dict."""
    return get_success_data(
        api_client.transition_show_entry(entry_id, {"target_status": "CONFIRMED"}, BM)
    )


def create_turnout(horse_id: str, pasture_id: str, window_start: str, window_end: str):
    """Book a turnout. Returns the turnout dict."""
    return get_success_data(
        api_client.create_turnout(
            create_turnout_payload(horse_id, pasture_id, window_start, window_end), BM
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: owner-standing accumulation
# ---------------------------------------------------------------------------
def setup_delinquent_owner_with_suspended_agreement():
    """Reach an owner whose committed standing_score == 80 (DELINQUENT) holding a
    SUSPENDED second agreement, ready for a reinstatement attempt.

    Drives exactly the difficulty-recipe chain:
      - daily_rate 8500 stall; agreement ACTIVE 06-01 -> ENDED 06-11
        (final 85000) -> one OPEN invoice finalized -> committed balance 85000
        -> base = floor(85000/10000)*10 = 80; penalty = 1 unpaid * 20 capped to
        score min(100, 80+20)=... but balance cap is 60, so base=min(60,80)=60,
        penalty=min(40,20)=20, score=80.
      - a SECOND agreement on the same stall (after the first ended, occupied 0)
        is activated then suspended.
    Returns dict(owner, stall, horse, first_agreement, invoice, second_agreement).
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _waiver = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=8500)
    horse = create_horse(owner["id"])
    a1 = create_draft_agreement(horse["id"], stall["id"])
    a1 = transition_agreement(a1["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    a1 = transition_agreement(a1["id"], "ENDED")
    invoice = open_invoice(owner["id"])
    invoice = finalize_invoice(invoice["id"], owner["id"])
    # Second agreement on the now-free stall, activated then suspended.
    a2 = create_draft_agreement(horse["id"], stall["id"],
                                start_date="2026-06-12T00:00:00.000Z")
    a2 = transition_agreement(a2["id"], "ACTIVE")
    a2 = transition_agreement(a2["id"], "SUSPENDED")
    return {
        "owner": owner,
        "stall": stall,
        "horse": horse,
        "first_agreement": a1,
        "invoice": invoice,
        "second_agreement": a2,
    }
