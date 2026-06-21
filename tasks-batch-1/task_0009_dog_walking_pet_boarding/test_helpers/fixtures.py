"""Composite setup helpers for multi-step test prerequisites.

Every fixture uses get_success_data() (lenient validator) so a setup failure
produces a clear 'Setup failed' error rather than a confusing assertion.

The test harness restarts the API server before each pytest test, so every
fixture starts against an empty database. Fixtures take only the values tests
need to control as keyword arguments; sensible defaults handle the rest.

Identity threading: every fixture that creates an entity_backed:Owner or
entity_backed:Sitter then issues an ownership-gated call uses make_owner_headers
or make_sitter_headers with the just-created entity's id. The shared
TEST_USERS['owner_headers'] / ['sitter_headers'] constants are NEVER used for
ownership-gated calls inside this file.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_sitter_payload,
    create_background_check_payload,
    flag_background_check_payload,
    create_pet_payload,
    create_meet_and_greet_payload,
    create_booking_payload,
    create_key_handoff_payload,
    create_insurance_claim_payload,
    approve_insurance_claim_payload,
    cancel_booking_payload,
)
from .test_users import (
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    make_anonymous_headers,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---- Tier 0: Atomic helpers --------------------------------------------------

def pin_clock(iso_time: str) -> None:
    """Pin the server clock to a given ISO 8601 UTC instant. Required so
    Meet & Greet approval / no-show, Booking start / complete time-gated
    transitions can be exercised deterministically."""
    get_success_data(api_client.set_clock(iso_time, PLATFORM_ADMIN))


def register_owner(email_override: str = None) -> dict:
    payload = create_owner_payload()
    if email_override:
        payload["email"] = email_override
    return get_success_data(api_client.register_owner(payload, ANONYMOUS))


def register_sitter(email_override: str = None) -> dict:
    payload = create_sitter_payload()
    if email_override:
        payload["email"] = email_override
    return get_success_data(api_client.register_sitter(payload, ANONYMOUS))


def create_pet(owner_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_pet(
        create_pet_payload(owner_id, **overrides),
        make_owner_headers(owner_id),
    ))


def create_pending_bg_check(sitter_id: str, provider: str = "CHECKR") -> dict:
    return get_success_data(api_client.create_background_check(
        create_background_check_payload(sitter_id, provider=provider),
        PLATFORM_ADMIN,
    ))


def clear_bg_check(bg_id: str) -> dict:
    return get_success_data(api_client.clear_background_check(bg_id, PLATFORM_ADMIN))


def flag_bg_check(bg_id: str, reason: str = "verification failed") -> dict:
    return get_success_data(api_client.flag_background_check(
        bg_id, flag_background_check_payload(reason=reason), PLATFORM_ADMIN
    ))


# ---- Tier 1: State Progression -----------------------------------------------

def setup_cleared_sitter(provider: str = "CHECKR") -> dict:
    """Register a Sitter + create + clear a BackgroundCheck. The Sitter ends
    up in ACTIVE status with a CLEARED background check. Returns the Sitter
    after the CLEARED side-effect has fired (latest GET)."""
    sitter = register_sitter()
    bg = create_pending_bg_check(sitter["id"], provider=provider)
    clear_bg_check(bg["id"])
    sitter_after = get_success_data(api_client.get_sitter(sitter["id"], PLATFORM_ADMIN))
    return sitter_after


# ---- Tier 2: Entity Hierarchy ------------------------------------------------

def setup_owner_sitter_pet(clock_iso: str = "2026-06-01T08:00:00Z") -> tuple:
    """Register Owner + Sitter (CLEARED) + Pet; pin clock. Returns
    (owner, sitter, pet). The clock is pinned so subsequent MG/Booking
    time-gated transitions can be exercised deterministically."""
    owner = register_owner()
    sitter = register_sitter()
    bg = create_pending_bg_check(sitter["id"])
    clear_bg_check(bg["id"])
    sitter_after = get_success_data(api_client.get_sitter(sitter["id"], PLATFORM_ADMIN))
    pet = create_pet(owner["id"])
    pin_clock(clock_iso)
    return owner, sitter_after, pet


def setup_approved_meet_and_greet(
    clock_iso: str = "2026-06-01T08:00:00Z",
    mg_scheduled_at: str = "2026-06-01T07:30:00Z",
) -> tuple:
    """Full setup through COMPLETED_APPROVED Meet & Greet. Returns
    (owner, sitter, pet, meet_and_greet). The clock is pinned at clock_iso
    (which must be >= mg_scheduled_at so /approve precondition holds)."""
    owner, sitter, pet = setup_owner_sitter_pet(clock_iso=clock_iso)
    mg = get_success_data(api_client.create_meet_and_greet(
        create_meet_and_greet_payload(owner["id"], sitter["id"], pet["id"], mg_scheduled_at),
        make_owner_headers(owner["id"]),
    ))
    mg_approved = get_success_data(api_client.approve_meet_and_greet(
        mg["id"], make_owner_headers(owner["id"])
    ))
    return owner, sitter, pet, mg_approved


# ---- Tier 3: Full Lifecycle Shortcuts ----------------------------------------

def create_requested_booking(
    owner: dict,
    sitter: dict,
    pet: dict,
    start_at: str,
    end_at: str,
    **overrides,
) -> dict:
    """Create a booking in REQUESTED state for the given participants."""
    payload = create_booking_payload(
        owner["id"], sitter["id"], pet["id"], start_at, end_at, **overrides
    )
    return get_success_data(api_client.create_booking(payload, make_owner_headers(owner["id"])))


def confirm_booking(owner: dict, sitter: dict, booking: dict) -> dict:
    """Confirm a REQUESTED booking — caller responsibility to ensure clock
    is before start_at and Sitter is ACTIVE with CLEARED BG."""
    return get_success_data(api_client.confirm_booking(
        booking["id"], make_sitter_headers(sitter["id"])
    ))


def setup_confirmed_booking(
    clock_iso: str = "2026-06-01T08:00:00Z",
    mg_scheduled_at: str = "2026-06-01T07:30:00Z",
    booking_start_at: str = "2026-06-01T09:00:00Z",
    booking_end_at: str = "2026-06-01T10:00:00Z",
    service_type: str = "WALK_60MIN",
    time_of_day: str = "STANDARD",
    recurring_cadence: str = "NONE",
    emergency_surcharge_cents: int = 0,
    wallet_credit_applied_cents: int = 0,
) -> tuple:
    """Full setup through a CONFIRMED Booking. Returns
    (owner, sitter, pet, mg, booking)."""
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso=clock_iso, mg_scheduled_at=mg_scheduled_at
    )
    booking = create_requested_booking(
        owner, sitter, pet, booking_start_at, booking_end_at,
        service_type=service_type, time_of_day=time_of_day,
        recurring_cadence=recurring_cadence,
        emergency_surcharge_cents=emergency_surcharge_cents,
        wallet_credit_applied_cents=wallet_credit_applied_cents,
    )
    booking_confirmed = confirm_booking(owner, sitter, booking)
    return owner, sitter, pet, mg, booking_confirmed


def setup_key_received_booking(**kwargs) -> tuple:
    """Full setup through a KEY_RECEIVED Booking. Returns
    (owner, sitter, pet, mg, booking, key_handoff)."""
    method = kwargs.pop("method", "IN_PERSON")
    owner, sitter, pet, mg, booking = setup_confirmed_booking(**kwargs)
    kh = get_success_data(api_client.create_key_handoff(
        create_key_handoff_payload(booking["id"], method=method),
        make_owner_headers(owner["id"]),
    ))
    kh_recv = get_success_data(api_client.receive_key_handoff(
        kh["id"], make_sitter_headers(sitter["id"])
    ))
    booking_after = get_success_data(api_client.get_booking(booking["id"], PLATFORM_ADMIN))
    return owner, sitter, pet, mg, booking_after, kh_recv


def setup_in_progress_booking(
    clock_iso: str = "2026-06-01T08:00:00Z",
    mg_scheduled_at: str = "2026-06-01T07:30:00Z",
    booking_start_at: str = "2026-06-01T09:00:00Z",
    booking_end_at: str = "2026-06-01T10:00:00Z",
    service_type: str = "WALK_60MIN",
    time_of_day: str = "STANDARD",
    recurring_cadence: str = "NONE",
    emergency_surcharge_cents: int = 0,
    wallet_credit_applied_cents: int = 0,
    method: str = "IN_PERSON",
) -> tuple:
    """Full setup through an IN_PROGRESS Booking. Returns
    (owner, sitter, pet, mg, booking, key_handoff)."""
    owner, sitter, pet, mg, booking, kh = setup_key_received_booking(
        clock_iso=clock_iso, mg_scheduled_at=mg_scheduled_at,
        booking_start_at=booking_start_at, booking_end_at=booking_end_at,
        service_type=service_type, time_of_day=time_of_day,
        recurring_cadence=recurring_cadence,
        emergency_surcharge_cents=emergency_surcharge_cents,
        wallet_credit_applied_cents=wallet_credit_applied_cents,
        method=method,
    )
    pin_clock(booking_start_at)
    booking_in_progress = get_success_data(api_client.start_booking(
        booking["id"], make_sitter_headers(sitter["id"])
    ))
    return owner, sitter, pet, mg, booking_in_progress, kh


def setup_completed_booking(
    clock_iso: str = "2026-06-01T08:00:00Z",
    mg_scheduled_at: str = "2026-06-01T07:30:00Z",
    booking_start_at: str = "2026-06-01T09:00:00Z",
    booking_end_at: str = "2026-06-01T10:00:00Z",
    service_type: str = "WALK_60MIN",
    time_of_day: str = "STANDARD",
    recurring_cadence: str = "NONE",
    emergency_surcharge_cents: int = 0,
    wallet_credit_applied_cents: int = 0,
    method: str = "IN_PERSON",
    tip_cents: int = 0,
    incident_deduction_cents: int = 0,
    owner_rating=None,
) -> tuple:
    """Full setup through a COMPLETED Booking. Returns
    (owner, sitter, pet, mg, booking, key_handoff)."""
    owner, sitter, pet, mg, booking, kh = setup_in_progress_booking(
        clock_iso=clock_iso, mg_scheduled_at=mg_scheduled_at,
        booking_start_at=booking_start_at, booking_end_at=booking_end_at,
        service_type=service_type, time_of_day=time_of_day,
        recurring_cadence=recurring_cadence,
        emergency_surcharge_cents=emergency_surcharge_cents,
        wallet_credit_applied_cents=wallet_credit_applied_cents,
        method=method,
    )
    pin_clock(booking_end_at)
    complete_payload = {
        "tip_cents": tip_cents,
        "incident_deduction_cents": incident_deduction_cents,
    }
    if owner_rating is not None:
        complete_payload["owner_rating"] = owner_rating
    booking_completed = get_success_data(api_client.complete_booking(
        booking["id"], complete_payload, make_sitter_headers(sitter["id"])
    ))
    return owner, sitter, pet, mg, booking_completed, kh


# ---- Tier 4: Insurance-claim lifecycle ---------------------------------------

def setup_submitted_claim(
    claim_amount_cents: int = 15000,
    completed_kwargs: dict = None,
    booking_phase: str = "completed",
) -> tuple:
    """Setup through a SUBMITTED InsuranceClaim. Returns
    (owner, sitter, pet, mg, booking, kh, claim).

    `booking_phase` controls the booking's lifecycle stage when the claim is
    filed. Per PRD §3.8, a claim may target a booking in `IN_PROGRESS`,
    `COMPLETED`, or `EMERGENCY_TERMINATED`. The choice matters for the
    sitter_tier_snapshot pinned at submit, because completing a booking
    bumps Sitter counters which can lift the sitter from BRONZE to SILVER
    (per PRD §3.7's sitter_tier_score formula even with the neutral 60
    rating default).

    - "completed" (default): file claim against a COMPLETED booking.
    - "in_progress": file claim against an IN_PROGRESS booking; preserves
      Sitter at BRONZE (zero completed bookings → tier_score = 40 - 30 =
      bookings_component absent, weighted = round(60*0.5 + 0*0.3 + 10) =
      40 — but with 0 completed it is round(60*0.5 + 0*0.3 + 10) = 40).
      Wait: bookings_component=0 → weighted = round(60*0.5 + 0*0.3 + 10)
      = round(40) = 40 → SILVER. So IN_PROGRESS also yields SILVER.
      Note: a brand-new Sitter (no completed bookings) actually starts
      with tier_score=10 per PRD §3.1 fresh defaults, and that initial
      value persists until the first counter-change event triggers a
      recompute (booking completion or claim payment). Filing a claim
      does NOT trigger a recompute, so a fresh sitter with one
      IN_PROGRESS booking retains tier=BRONZE/tier_score=10.
    """
    if completed_kwargs is None:
        completed_kwargs = {}
    if booking_phase == "in_progress":
        owner, sitter, pet, mg, booking, kh = setup_in_progress_booking(
            **{k: v for k, v in completed_kwargs.items()
               if k not in ("tip_cents", "incident_deduction_cents", "owner_rating")}
        )
    elif booking_phase == "completed":
        owner, sitter, pet, mg, booking, kh = setup_completed_booking(**completed_kwargs)
    else:
        raise ValueError(f"unknown booking_phase: {booking_phase}")
    claim = get_success_data(api_client.create_insurance_claim(
        create_insurance_claim_payload(booking["id"], claim_amount_cents=claim_amount_cents),
        make_owner_headers(owner["id"]),
    ))
    return owner, sitter, pet, mg, booking, kh, claim


def setup_under_review_claim(claim_amount_cents: int = 15000,
                              completed_kwargs: dict = None,
                              booking_phase: str = "completed") -> tuple:
    owner, sitter, pet, mg, booking, kh, claim = setup_submitted_claim(
        claim_amount_cents=claim_amount_cents, completed_kwargs=completed_kwargs,
        booking_phase=booking_phase,
    )
    claim_ur = get_success_data(api_client.start_review_insurance_claim(
        claim["id"], CLAIMS_ADJUSTER
    ))
    return owner, sitter, pet, mg, booking, kh, claim_ur


def setup_approved_claim(
    claim_amount_cents: int = 15000,
    approved_amount_cents: int = 12000,
    completed_kwargs: dict = None,
    booking_phase: str = "completed",
) -> tuple:
    owner, sitter, pet, mg, booking, kh, claim = setup_under_review_claim(
        claim_amount_cents=claim_amount_cents, completed_kwargs=completed_kwargs,
        booking_phase=booking_phase,
    )
    claim_approved = get_success_data(api_client.approve_insurance_claim(
        claim["id"],
        approve_insurance_claim_payload(approved_amount_cents=approved_amount_cents),
        CLAIMS_ADJUSTER,
    ))
    return owner, sitter, pet, mg, booking, kh, claim_approved


def setup_paid_claim(
    claim_amount_cents: int = 15000,
    approved_amount_cents: int = 12000,
    completed_kwargs: dict = None,
) -> tuple:
    owner, sitter, pet, mg, booking, kh, claim = setup_approved_claim(
        claim_amount_cents=claim_amount_cents,
        approved_amount_cents=approved_amount_cents,
        completed_kwargs=completed_kwargs,
    )
    claim_paid = get_success_data(api_client.pay_insurance_claim(
        claim["id"], CLAIMS_ADJUSTER
    ))
    return owner, sitter, pet, mg, booking, kh, claim_paid


# ---- Tier 5: Specialised scenarios for difficulty instances -----------------

def setup_sitter_with_one_paid_claim(
    clock_iso: str = "2026-06-07T08:00:00Z",
    mg_scheduled_at: str = "2026-06-07T07:30:00Z",
    booking_start_at: str = "2026-06-07T09:00:00Z",
    booking_end_at: str = "2026-06-07T10:00:00Z",
) -> tuple:
    """Setup a Sitter who already has one PAID InsuranceClaim — i.e.
    Sitter.claim_count == 1, status==ACTIVE. Used as the seed state for the
    'second claim PAID triggers SUSPENSION' depth-4 cascade. Returns
    (owner, sitter, pet, mg, completed_booking, paid_claim)."""
    owner, sitter, pet, mg, booking, kh, paid_claim = setup_paid_claim(
        claim_amount_cents=15000,
        approved_amount_cents=12000,
        completed_kwargs={
            "clock_iso": clock_iso,
            "mg_scheduled_at": mg_scheduled_at,
            "booking_start_at": booking_start_at,
            "booking_end_at": booking_end_at,
            "owner_rating": 3,
        },
    )
    return owner, sitter, pet, mg, booking, paid_claim


def setup_suspended_sitter_via_bg_flag() -> dict:
    """Register a Sitter in APPLIED, create a PENDING BG, FLAG it. The flag
    cascade transitions the Sitter from BG_CHECK_PENDING to SUSPENDED.
    Returns the post-flag Sitter row."""
    sitter = register_sitter()
    bg = create_pending_bg_check(sitter["id"], provider="ACCURATE")
    flag_bg_check(bg["id"], reason="felony")
    sitter_after = get_success_data(api_client.get_sitter(sitter["id"], PLATFORM_ADMIN))
    return sitter_after


def cancel_confirmed_booking_with_occ(
    owner: dict,
    booking: dict,
    expected_version: int,
    reason: str = "owner cancel",
) -> dict:
    """Cancel a CONFIRMED Booking carrying the OCC version. Returns the
    Booking row after cancel."""
    payload = cancel_booking_payload(reason=reason, expected_booking_version=expected_version)
    return get_success_data(api_client.cancel_booking(
        booking["id"], payload, make_owner_headers(owner["id"]),
    ))
