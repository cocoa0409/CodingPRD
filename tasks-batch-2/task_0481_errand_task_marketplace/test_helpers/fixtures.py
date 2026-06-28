"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: after creating an entity_backed Client/Tasker, ownership-gated
calls use make_client_headers(id) / make_tasker_headers(id) with the real entity id,
never a shared constant (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_category_payload, create_fixed_category_payload, create_tasker_payload,
    create_client_payload, create_skill_payload, create_window_payload,
    create_booking_payload, create_claim_payload, create_complete_payload,
    create_cancel_payload, create_series_payload, create_review_payload,
    create_incident_payload,
)
from .test_users import (
    TEST_USERS, make_client_headers, make_tasker_headers,
    dispatcher_headers, trust_safety_headers,
)
from .constants import CLOCK_BASE


DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(to_iso8601, headers=None):
    """Set the logical clock. PRD §2.4."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or DISP))


# ─── Tier 1/2: Catalog primitives ──────────────────────────────────────────

def create_category(**overrides):
    """Create an ACTIVE HOURLY category. Returns category dict."""
    return get_success_data(api_client.create_category(
        create_category_payload(**overrides), DISP))


def create_fixed_category(**overrides):
    """Create an ACTIVE FIXED category. Returns category dict."""
    return get_success_data(api_client.create_category(
        create_fixed_category_payload(**overrides), DISP))


def create_tasker(**overrides):
    """Register an ACTIVE tasker (trust_score=100, version=1). Returns tasker dict."""
    return get_success_data(api_client.create_tasker(
        create_tasker_payload(**overrides), DISP))


def create_client(**overrides):
    """Register a client. Returns client dict."""
    return get_success_data(api_client.create_client(
        create_client_payload(**overrides), DISP))


def create_window(tasker_id, window_start, window_end):
    """Create an OPEN availability window for a tasker. Returns window dict."""
    return get_success_data(api_client.create_window(
        create_window_payload(tasker_id, window_start, window_end), DISP))


def create_skill(tasker_id, category_id):
    """Declare a PENDING TaskerSkill. Returns skill dict."""
    return get_success_data(api_client.create_skill(
        create_skill_payload(tasker_id, category_id), DISP))


def vet_skill(skill_id):
    """Vet a PENDING skill to VETTED. Returns skill dict."""
    return get_success_data(api_client.vet_skill(skill_id, TSO))


def file_incident(tasker_id, severity="HIGH", **overrides):
    """File an OPEN TrustIncident. Returns incident dict."""
    return get_success_data(api_client.create_incident(
        create_incident_payload(tasker_id, severity=severity, **overrides), TSO))


# ─── Booking lifecycle shortcuts ───────────────────────────────────────────

def create_booking(client_id, category_id, scheduled_start, **overrides):
    """Create a DRAFT booking as the owning client. Returns booking dict."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(client_id, category_id, scheduled_start, **overrides),
        make_client_headers(client_id)))


def create_offered_booking(client_id, category_id, scheduled_start, **overrides):
    """Create + offer a booking (estimate pinned, scheduled_end computed).
    Returns the OFFERED booking dict."""
    bk = create_booking(client_id, category_id, scheduled_start, **overrides)
    return get_success_data(api_client.offer_booking(bk["id"], make_client_headers(client_id)))


def get_tasker_version(tasker_id):
    """Read the tasker's current version (for OCC claim/accept)."""
    return get_success_data(api_client.get_tasker(tasker_id, DISP))["version"]


def claim_booking(booking_id, tasker_id, client_id=None):
    """Claim an OFFERED booking onto a tasker using the tasker's current version.
    Returns the CLAIMED booking dict."""
    ver = get_tasker_version(tasker_id)
    return get_success_data(api_client.claim_booking(
        booking_id, create_claim_payload(tasker_id, ver), DISP))


def create_claimed_booking(client_id, category_id, tasker_id, scheduled_start, **overrides):
    """Create -> offer -> claim onto tasker. Returns the CLAIMED booking dict."""
    bk = create_offered_booking(client_id, category_id, scheduled_start, **overrides)
    return claim_booking(bk["id"], tasker_id, client_id)


def drive_to_in_progress(booking_id, tasker_id):
    """From CLAIMED: depart -> start. Returns the IN_PROGRESS booking dict."""
    th = make_tasker_headers(tasker_id)
    get_success_data(api_client.depart_booking(booking_id, th))
    return get_success_data(api_client.start_booking(booking_id, th))


def create_in_progress_booking(client_id, category_id, tasker_id, scheduled_start, **overrides):
    """create -> offer -> claim -> depart -> start. Returns IN_PROGRESS booking dict."""
    bk = create_claimed_booking(client_id, category_id, tasker_id, scheduled_start, **overrides)
    return drive_to_in_progress(bk["id"], tasker_id)


def complete_booking(booking_id, tasker_id, **complete_overrides):
    """Complete an IN_PROGRESS booking (creates Settlement). Returns COMPLETED booking dict."""
    return get_success_data(api_client.complete_booking(
        booking_id, create_complete_payload(**complete_overrides),
        make_tasker_headers(tasker_id)))


def create_completed_booking(client_id, category_id, tasker_id, scheduled_start,
                             complete_overrides=None, **overrides):
    """Full chain create -> ... -> complete. Returns COMPLETED booking dict."""
    bk = create_in_progress_booking(client_id, category_id, tasker_id, scheduled_start, **overrides)
    return complete_booking(bk["id"], tasker_id, **(complete_overrides or {}))


# ─── Composite scenarios ───────────────────────────────────────────────────

def setup_catalog(clock=CLOCK_BASE, category_overrides=None,
                  tasker_overrides=None, window=None):
    """Clock + HOURLY category + tasker + client (+ optional OPEN window).

    Returns dict with keys: category, tasker, client, window (or None).
    """
    set_clock(clock)
    category = create_category(**(category_overrides or {}))
    tasker = create_tasker(**(tasker_overrides or {}))
    client = create_client()
    win = None
    if window is not None:
        win = create_window(tasker["id"], window[0], window[1])
    return {"category": category, "tasker": tasker, "client": client, "window": win}


def suspend_tasker(tasker_id):
    """File two HIGH incidents -> trust_score 30 -> SUSPENDED. Returns the tasker dict (re-read)."""
    file_incident(tasker_id, severity="HIGH")
    file_incident(tasker_id, severity="HIGH")
    return get_success_data(api_client.get_tasker(tasker_id, DISP))


def restrict_tasker(tasker_id):
    """File one HIGH incident -> trust_score 65 -> RESTRICTED.
    Returns (tasker_dict, incident_id)."""
    inc = file_incident(tasker_id, severity="HIGH")
    return get_success_data(api_client.get_tasker(tasker_id, DISP)), inc["id"]


def setup_completed_and_reviewed(clock=CLOCK_BASE, rating_value=5,
                                 window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
                                 scheduled_start="2026-06-25T10:00:00Z"):
    """Clock + category + tasker + client + window + a COMPLETED booking that the
    client reviews. Returns dict: category, tasker, client, booking, review.
    """
    ctx = setup_catalog(clock=clock, window=window)
    bk = create_completed_booking(ctx["client"]["id"], ctx["category"]["id"],
                                  ctx["tasker"]["id"], scheduled_start)
    review = get_success_data(api_client.create_review(
        create_review_payload(bk["id"], rating_value),
        make_client_headers(ctx["client"]["id"])))
    return {"category": ctx["category"], "tasker": ctx["tasker"],
            "client": ctx["client"], "booking": bk, "review": review}


def setup_series(clock=CLOCK_BASE, occurrence_count=3, frequency="WEEKLY",
                 first_start="2026-07-01T10:00:00Z"):
    """Clock + category + tasker + client + a RecurringSeries.
    Returns dict: category, tasker, client, series.
    """
    set_clock(clock)
    category = create_category()
    tasker = create_tasker()
    client = create_client()
    series = get_success_data(api_client.create_series(
        create_series_payload(client["id"], category["id"], tasker["id"], first_start,
                              occurrence_count=occurrence_count, frequency=frequency),
        make_client_headers(client["id"])))
    return {"category": category, "tasker": tasker, "client": client, "series": series}
