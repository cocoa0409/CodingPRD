"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this marketplace require the system to be walked
through 5-15 API calls (register a family + caregiver, clear a background check,
open a posting, offer + confirm a booking, drive sessions through clock-in /
clock-out, sweep payouts) before the behaviour under test is even reachable.
These helpers encapsulate those preambles.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: Family and Caregiver are entity_backed roles, so ownership-
gated calls thread the actual entity id through make_family_headers(id) /
make_caregiver_headers(id) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_family_payload, create_caregiver_payload, create_background_check_payload,
    create_job_posting_payload, create_booking_payload, create_backup_request_payload,
    create_payout_payload, create_review_payload,
)
from .test_users import (
    TEST_USERS, make_admin_headers, make_family_headers, make_caregiver_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 0: Clock control ────────────────────────────────────────────────
def set_clock(iso8601):
    """Pin the deterministic system clock to a given instant (admin-only)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 1: Primitive entity creation ────────────────────────────────────
def create_family(wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
                  email="fam@x.com", display_name="Fam"):
    """Register a family. Returns the Family resource."""
    payload = create_family_payload(
        display_name=display_name, email=email, num_children=num_children,
        required_tier=required_tier, wallet_balance_cents=wallet_balance_cents,
    )
    return get_success_data(api_client.create_family(payload, ADMIN))


def create_caregiver(hourly_rate_floor_cents=1500, email="cg@x.com", full_name="Cg"):
    """Register a caregiver. Returns the Caregiver resource (OFFLINE, NONE tier)."""
    payload = create_caregiver_payload(
        full_name=full_name, email=email, hourly_rate_floor_cents=hourly_rate_floor_cents,
    )
    return get_success_data(api_client.create_caregiver(payload, ADMIN))


def set_caregiver_available(caregiver_id):
    """Move a caregiver to AVAILABLE (ownership-gated → caregiver headers)."""
    return get_success_data(api_client.set_availability(
        caregiver_id, {"availability_status": "AVAILABLE"},
        make_caregiver_headers(caregiver_id)))


def clear_background_check(caregiver_id, tier="BASIC"):
    """Initiate → start → adjudicate CLEAR a background check at `tier`.
    Leaves the caregiver verification_status=CLEAR, background_check_tier>=tier."""
    bc = get_success_data(api_client.create_background_check(
        create_background_check_payload(caregiver_id, requested_tier=tier), ADMIN))
    api_client.start_background_check(bc["id"], ADMIN)
    get_success_data(api_client.adjudicate_background_check(
        bc["id"], {"decision": "CLEAR"}, ADMIN))
    return bc


def create_cleared_available_caregiver(tier="BASIC", hourly_rate_floor_cents=1500,
                                       email="cg@x.com", full_name="Cg"):
    """Register a caregiver, make AVAILABLE, and clear a `tier` background check.
    Returns the up-to-date Caregiver resource."""
    cg = create_caregiver(hourly_rate_floor_cents=hourly_rate_floor_cents,
                          email=email, full_name=full_name)
    set_caregiver_available(cg["id"])
    clear_background_check(cg["id"], tier=tier)
    return get_success_data(api_client.get_caregiver(cg["id"], ADMIN))


def create_open_posting(family_id, care_type="ONE_TIME", family_pay_rate_cents=2000,
                        required_tier="BASIC", title="Posting"):
    """Create an OPEN job posting owned by `family_id` (ownership-gated)."""
    payload = create_job_posting_payload(
        family_id, title=title, care_type=care_type,
        family_pay_rate_cents=family_pay_rate_cents, required_tier=required_tier)
    return get_success_data(api_client.create_job_posting(
        payload, make_family_headers(family_id)))


# ─── Tier 2: Booking offer (OFFERED) ──────────────────────────────────────
def offer_booking(family_id, caregiver_id, job_posting_id, agreed_rate_cents=2000,
                  scheduled_start="2026-03-20T08:00:00Z", scheduled_end="2026-03-20T12:00:00Z",
                  recurrence_count=1, is_holiday=None):
    """Family extends a booking offer. Returns the OFFERED Booking resource."""
    payload = create_booking_payload(
        family_id, caregiver_id, job_posting_id,
        agreed_rate_cents=agreed_rate_cents,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        recurrence_count=recurrence_count)
    if is_holiday is not None:
        payload["is_holiday"] = is_holiday
    return get_success_data(api_client.create_booking(
        payload, make_family_headers(family_id)))


def confirm_booking(booking_id, caregiver_id):
    """Caregiver confirms a standing offer (ownership-gated)."""
    return get_success_data(api_client.confirm_booking(
        booking_id, make_caregiver_headers(caregiver_id)))


def first_session(booking_id):
    """Return the first BookingSession of a booking (admin read)."""
    data, _meta = _list(api_client.list_sessions(ADMIN, params={"booking_id": booking_id}))
    assert data, f"no sessions found for booking {booking_id}"
    return data[0]


def sessions_for(booking_id, status=None):
    """List all sessions of a booking, optionally filtered by status (admin read)."""
    params = {"booking_id": booking_id}
    if status is not None:
        params["status"] = status
    data, _meta = _list(api_client.list_sessions(ADMIN, params=params))
    return data


def _list(response):
    """Lenient unwrap of a list response into (data, meta)."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 3: Confirmed booking with a single clocked-out session ───────────
def setup_confirmed_one_time_booking(
        *, wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
        family_pay_rate_cents=2000, agreed_rate_cents=2000, caregiver_tier="BASIC",
        scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
        is_holiday=False, confirm_clock="2026-03-01T00:00:00Z",
        email_suffix="x"):
    """Walk a family + cleared caregiver + OPEN posting to a CONFIRMED one-time
    booking with exactly one SCHEDULED session.

    Returns dict(family, caregiver, posting, booking, session).
    """
    set_clock(confirm_clock)
    fam = create_family(wallet_balance_cents=wallet_balance_cents, num_children=num_children,
                        required_tier=required_tier, email=f"fam-{email_suffix}@x.com")
    cg = create_cleared_available_caregiver(
        tier=caregiver_tier, email=f"cg-{email_suffix}@x.com")
    posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                  family_pay_rate_cents=family_pay_rate_cents,
                                  required_tier=required_tier)
    booking = offer_booking(fam["id"], cg["id"], posting["id"],
                            agreed_rate_cents=agreed_rate_cents,
                            scheduled_start=scheduled_start, scheduled_end=scheduled_end,
                            recurrence_count=1, is_holiday=is_holiday)
    booking = confirm_booking(booking["id"], cg["id"])
    session = first_session(booking["id"])
    return {"family": fam, "caregiver": cg, "posting": posting,
            "booking": booking, "session": session}


def complete_session(session, caregiver_id, *, clock_in, clock_out):
    """Clock a SCHEDULED session in at `clock_in` and out at `clock_out`.
    Returns the COMPLETED BookingSession."""
    set_clock(clock_in)
    get_success_data(api_client.clock_in(session["id"], make_caregiver_headers(caregiver_id)))
    set_clock(clock_out)
    return get_success_data(api_client.clock_out(
        session["id"], make_caregiver_headers(caregiver_id)))


def setup_completed_one_time_session(
        *, wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
        agreed_rate_cents=2000, family_pay_rate_cents=2000, caregiver_tier="BASIC",
        scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
        clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z",
        is_holiday=False, email_suffix="c"):
    """Full chain from registration through a COMPLETED session (clocked in then
    out). Returns dict(family, caregiver, posting, booking, session)
    where session is the COMPLETED session with gross_pay_cents populated."""
    ctx = setup_confirmed_one_time_booking(
        wallet_balance_cents=wallet_balance_cents, num_children=num_children,
        required_tier=required_tier, family_pay_rate_cents=family_pay_rate_cents,
        agreed_rate_cents=agreed_rate_cents, caregiver_tier=caregiver_tier,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        is_holiday=is_holiday, email_suffix=email_suffix)
    completed = complete_session(ctx["session"], ctx["caregiver"]["id"],
                                 clock_in=clock_in, clock_out=clock_out)
    ctx["session"] = completed
    return ctx


# ─── Tier 4: Payout sweeps ────────────────────────────────────────────────
def create_payout(caregiver_id, family_id, session_ids):
    """Sweep COMPLETED sessions into a PENDING payout (admin-only)."""
    return get_success_data(api_client.create_payout(
        create_payout_payload(caregiver_id, family_id, session_ids), ADMIN))


def setup_paid_payout(
        *, num_children=2, agreed_rate_cents=2000,
        scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
        clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z",
        is_holiday=False, family_pay_rate_cents=2000, required_tier="BASIC",
        caregiver_tier="BASIC", wallet_balance_cents=100000, email_suffix="p"):
    """A completed session swept into a payout that is then PAID.
    Returns dict(family, caregiver, posting, booking, session, payout)."""
    ctx = setup_completed_one_time_session(
        wallet_balance_cents=wallet_balance_cents, num_children=num_children,
        required_tier=required_tier, agreed_rate_cents=agreed_rate_cents,
        family_pay_rate_cents=family_pay_rate_cents, caregiver_tier=caregiver_tier,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        clock_in=clock_in, clock_out=clock_out, is_holiday=is_holiday,
        email_suffix=email_suffix)
    payout = create_payout(ctx["caregiver"]["id"], ctx["family"]["id"],
                           [ctx["session"]["id"]])
    payout = get_success_data(api_client.pay_payout(payout["id"], ADMIN))
    ctx["payout"] = payout
    return ctx


# ─── Tier 5: Reviews / reputation ─────────────────────────────────────────
def submit_review(booking_id, family_id, caregiver_id, rating_value):
    """Family submits a review on a COMPLETED booking (ownership-gated)."""
    return get_success_data(api_client.create_review(
        create_review_payload(booking_id, family_id, caregiver_id, rating_value=rating_value),
        make_family_headers(family_id)))


def publish_review(review_id):
    """Platform publishes a PENDING_MODERATION review (admin-only)."""
    return get_success_data(api_client.moderate_review(
        review_id, {"decision": "PUBLISH"}, ADMIN))


# ─── Tier 6: Backup requests ──────────────────────────────────────────────
def open_backup_request(family_id, needed_start="2026-03-05T08:00:00Z",
                        needed_end="2026-03-05T12:00:00Z", required_tier="BASIC",
                        max_rate_cents=3000):
    """Family opens an OPEN BackupCareRequest (ownership-gated). Returns resource."""
    return get_success_data(api_client.create_backup_request(
        create_backup_request_payload(
            family_id, needed_start=needed_start, needed_end=needed_end,
            required_tier=required_tier, max_rate_cents=max_rate_cents),
        make_family_headers(family_id)))
