"""Composite setup helpers for the Tattoo & Piercing Studio API.

These encapsulate the multi-step preambles that most interesting test claims
require — registering an artist/chair/client, verifying the client, holding an
appointment, paying the deposit, signing the waiver, confirming, and (often)
completing the session. Tests import these by name and focus on assertions.

All setup calls use get_success_data() (the lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion deep in a test.

IDENTITY THREADING: after a fixture creates an entity-backed Artist or Client,
every ownership-gated call uses make_artist_headers(artist_id) /
make_client_headers(client_id) with the real entity id — never the shared
TEST_USERS fallback.

The server database is reset before every test (the runner relaunches the
server via start.sh), so each fixture builds its world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_artist_headers, make_client_headers,
)
from . import factories


MANAGER = TEST_USERS["manager_headers"]
# Anonymous self-signup carries no auth identity (PRD §2.1).
ANON = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Clock control (PRD §2.8 test-driving)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the server's logical UTC clock. Returns the reported current_utc."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------
def create_artist(**overrides) -> dict:
    """Register an artist (StudioManager-exclusive). Returns the Artist dict."""
    return get_success_data(
        api_client.create_artist(factories.create_artist_payload(**overrides), MANAGER)
    )


def create_chair(**overrides) -> dict:
    """Add a chair. Returns the Chair dict (with version)."""
    return get_success_data(
        api_client.create_chair(factories.create_chair_payload(**overrides), MANAGER)
    )


def create_client(**overrides) -> dict:
    """Self-register a client (Anonymous). Returns the Client dict (UNVERIFIED)."""
    return get_success_data(
        api_client.create_client(factories.create_client_payload(**overrides), ANON)
    )


def create_verified_client(**overrides) -> dict:
    """Self-register a client, submit ID, and have the manager approve it.
    Returns the VERIFIED Client dict. Requires the clock to already be set if
    the test cares about the age computation (defaults to DOB 1990-01-01,
    comfortably over 18)."""
    client = create_client(**overrides)
    cid = client["id"]
    ch = make_client_headers(cid)
    get_success_data(
        api_client.submit_id_verification(cid, factories.id_verification_payload(), ch)
    )
    return get_success_data(api_client.approve_id_verification(cid, MANAGER))


def create_flash_design(artist_id: str, **overrides) -> dict:
    """Artist publishes a flash design. Returns the FlashDesign dict."""
    ah = make_artist_headers(artist_id)
    return get_success_data(
        api_client.create_flash_design(
            factories.create_flash_design_payload(artist_id, **overrides), ah
        )
    )


def current_chair_version(chair_id: str) -> int:
    """Re-read a chair's current version (it bumps on each hold)."""
    return get_success_data(api_client.get_chair(chair_id, MANAGER))["version"]


# ---------------------------------------------------------------------------
# Tier 2: held appointment (the core booking preamble)
# ---------------------------------------------------------------------------
def hold_appointment(artist_id: str, client_id: str, chair_id: str,
                     chair_version: int, **overrides) -> dict:
    """Create an appointment HOLD as the owning client. Returns the Appointment
    dict (status HELD, with required_deposit_cents and version)."""
    ch = make_client_headers(client_id)
    payload = factories.create_appointment_payload(
        artist_id, client_id, chair_id, chair_version, **overrides
    )
    return get_success_data(api_client.create_appointment(payload, ch))


def pay_deposit(appointment_id: str, client_id: str, amount_cents: int,
                expected_version: int) -> dict:
    """Pay one deposit toward an appointment. Returns the Deposit dict."""
    ch = make_client_headers(client_id)
    return get_success_data(
        api_client.pay_deposit(
            appointment_id, factories.deposit_payload(amount_cents, expected_version), ch
        )
    )


def record_waiver(appointment_id: str, client_id: str, **overrides) -> dict:
    """Record a valid (aftercare-acknowledged) consent waiver. Returns the
    ConsentWaiver dict."""
    ch = make_client_headers(client_id)
    return get_success_data(
        api_client.record_waiver(
            appointment_id, factories.waiver_payload(client_id, **overrides), ch
        )
    )


def setup_confirmed_appointment(
    *,
    clock="2026-06-01T12:00:00Z",
    hourly_rate_cents=18000,
    estimated_minutes=180,
    deposit_cents=10800,
    start_at="2026-06-10T10:00:00Z",
    end_at="2026-06-10T13:00:00Z",
    cleanup_buffer_minutes=30,
    pricing_mode="HOURLY",
    flash_design_id=None,
    piece_price_cents=None,
    aftercare_acknowledged=True,
    commission_pct=0.70,
):
    """Full preamble through a CONFIRMED HOURLY (or PIECE) appointment.

    Steps: set clock -> create artist -> create chair -> create+verify client
    -> hold appointment -> pay deposit -> record waiver -> confirm.

    Returns a dict with keys: artist, chair, client, appointment (the confirmed
    appointment as returned by /confirm), deposit, appointment_id, artist_id,
    client_id, chair_id, deposit_id, flash_design_id.
    """
    set_clock(clock)
    artist = create_artist(
        hourly_rate_cents=hourly_rate_cents, commission_pct=commission_pct
    )
    chair = create_chair(cleanup_buffer_minutes=cleanup_buffer_minutes)
    client = create_verified_client()

    hold_overrides = {
        "pricing_mode": pricing_mode,
        "estimated_minutes": estimated_minutes,
        "start_at": start_at,
        "end_at": end_at,
    }
    if pricing_mode == "HOURLY":
        hold_overrides["hourly_rate_cents"] = hourly_rate_cents
    else:  # PIECE
        hold_overrides["flash_design_id"] = flash_design_id
        hold_overrides["piece_price_cents"] = piece_price_cents
        hold_overrides.pop("hourly_rate_cents", None)

    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"], **hold_overrides
    )
    deposit = pay_deposit(appt["id"], client["id"], deposit_cents, appt["version"])
    record_waiver(appt["id"], client["id"], aftercare_acknowledged=aftercare_acknowledged)
    confirmed = get_success_data(
        api_client.confirm_appointment(appt["id"], make_client_headers(client["id"]))
    )
    return {
        "artist": artist,
        "chair": chair,
        "client": client,
        "appointment": confirmed,
        "deposit": deposit,
        "appointment_id": appt["id"],
        "artist_id": artist["id"],
        "client_id": client["id"],
        "chair_id": chair["id"],
        "deposit_id": deposit["id"],
        "flash_design_id": flash_design_id,
    }


def setup_confirmed_flash_appointment(
    *,
    clock="2026-06-01T12:00:00Z",
    piece_price_cents=55000,
    deposit_cents=11000,
    estimated_minutes=120,
    start_at="2026-06-15T10:00:00Z",
    end_at="2026-06-15T12:00:00Z",
    aftercare_acknowledged=True,
):
    """A CONFIRMED PIECE appointment booked on a freshly-published flash design.
    The flash is RESERVED at confirmation. Returns the same shape as
    setup_confirmed_appointment plus the flash design under flash_design_id."""
    set_clock(clock)
    artist = create_artist(hourly_rate_cents=17000)
    flash = create_flash_design(
        artist["id"], piece_price_cents=piece_price_cents,
        estimated_minutes=estimated_minutes,
    )
    chair = create_chair()
    client = create_verified_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        pricing_mode="PIECE", flash_design_id=flash["id"],
        piece_price_cents=piece_price_cents, estimated_minutes=estimated_minutes,
        start_at=start_at, end_at=end_at,
    )
    deposit = pay_deposit(appt["id"], client["id"], deposit_cents, appt["version"])
    record_waiver(appt["id"], client["id"], aftercare_acknowledged=aftercare_acknowledged)
    confirmed = get_success_data(
        api_client.confirm_appointment(appt["id"], make_client_headers(client["id"]))
    )
    return {
        "artist": artist,
        "flash": flash,
        "chair": chair,
        "client": client,
        "appointment": confirmed,
        "deposit": deposit,
        "appointment_id": appt["id"],
        "artist_id": artist["id"],
        "client_id": client["id"],
        "chair_id": chair["id"],
        "deposit_id": deposit["id"],
        "flash_design_id": flash["id"],
    }


# ---------------------------------------------------------------------------
# Tier 3: completed appointment (lifecycle shortcut)
# ---------------------------------------------------------------------------
def setup_completed_appointment(
    *,
    clock="2026-06-01T12:00:00Z",
    complete_clock=None,
    actual_minutes=200,
    **confirm_kwargs,
):
    """Full lifecycle through COMPLETED for an HOURLY appointment.

    Builds a confirmed appointment, optionally advances the clock to
    complete_clock, then completes it as the owning artist with actual_minutes.
    Returns the same dict as setup_confirmed_appointment but 'appointment' is
    the COMPLETED appointment (with gross_cents / balance_due_cents)."""
    ctx = setup_confirmed_appointment(clock=clock, **confirm_kwargs)
    if complete_clock is not None:
        set_clock(complete_clock)
    completed = get_success_data(
        api_client.complete_appointment(
            ctx["appointment_id"], {"actual_minutes": actual_minutes},
            make_artist_headers(ctx["artist_id"]),
        )
    )
    ctx["appointment"] = completed
    return ctx


def setup_completed_flash_appointment(*, clock="2026-06-01T12:00:00Z",
                                      complete_clock=None, **flash_kwargs):
    """Full lifecycle through COMPLETED for a PIECE/flash appointment (no
    actual_minutes needed). Returns the flash-appointment context with
    'appointment' as the COMPLETED appointment."""
    ctx = setup_confirmed_flash_appointment(clock=clock, **flash_kwargs)
    if complete_clock is not None:
        set_clock(complete_clock)
    completed = get_success_data(
        api_client.complete_appointment(
            ctx["appointment_id"], {}, make_artist_headers(ctx["artist_id"]),
        )
    )
    ctx["appointment"] = completed
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: held-but-not-yet-confirmed appointment (compliance-gate tests)
# ---------------------------------------------------------------------------
def setup_held_appointment(
    *,
    clock="2026-06-01T12:00:00Z",
    verify_client=True,
    hourly_rate_cents=18000,
    estimated_minutes=180,
    start_at="2026-06-10T10:00:00Z",
    end_at="2026-06-10T13:00:00Z",
):
    """A HELD HOURLY appointment with no deposit and no waiver yet. The client
    is VERIFIED by default; pass verify_client=False to leave it UNVERIFIED.
    Returns the same context shape (appointment is HELD)."""
    set_clock(clock)
    artist = create_artist(hourly_rate_cents=hourly_rate_cents)
    chair = create_chair()
    client = create_verified_client() if verify_client else create_client()
    appt = hold_appointment(
        artist["id"], client["id"], chair["id"], chair["version"],
        hourly_rate_cents=hourly_rate_cents, estimated_minutes=estimated_minutes,
        start_at=start_at, end_at=end_at,
    )
    return {
        "artist": artist,
        "chair": chair,
        "client": client,
        "appointment": appt,
        "appointment_id": appt["id"],
        "artist_id": artist["id"],
        "client_id": client["id"],
        "chair_id": chair["id"],
        "appointment_version": appt["version"],
        "required_deposit_cents": appt["required_deposit_cents"],
    }


# ---------------------------------------------------------------------------
# Tier 5: custom-request pipeline
# ---------------------------------------------------------------------------
def create_pending_custom_request(*, artist_overrides=None, client_overrides=None,
                                  **request_overrides):
    """Create an artist, a client, and a PENDING custom request from the client
    to the artist. Returns (artist, client, request) dicts."""
    artist = create_artist(**(artist_overrides or {}))
    client = create_client(**(client_overrides or {}))
    request = get_success_data(
        api_client.create_custom_request(
            factories.create_custom_request_payload(
                artist["id"], client["id"], **request_overrides
            ),
            make_client_headers(client["id"]),
        )
    )
    return artist, client, request


def create_approved_custom_request(*, quoted_price_cents=60000, estimated_minutes=180):
    """Create a custom request, quote it, and have the client approve it.
    Returns (artist, client, request) with request in APPROVED."""
    artist, client, request = create_pending_custom_request()
    get_success_data(
        api_client.quote_custom_request(
            request["id"],
            factories.quote_payload(
                quoted_price_cents=quoted_price_cents, estimated_minutes=estimated_minutes
            ),
            make_artist_headers(artist["id"]),
        )
    )
    approved = get_success_data(
        api_client.approve_custom_request(request["id"], make_client_headers(client["id"]))
    )
    return artist, client, approved


# ---------------------------------------------------------------------------
# Tier 6: touch-up on a completed parent
# ---------------------------------------------------------------------------
def setup_requested_touchup(
    *,
    clock="2026-06-01T12:00:00Z",
    complete_clock="2026-06-10T14:00:00Z",
    request_clock=None,
    aftercare_acknowledged=True,
):
    """A COMPLETED HOURLY appointment with one REQUESTED touch-up.

    If request_clock is supplied the clock is advanced before requesting (drives
    the touch-up free-window fee). Returns the completed-appointment context plus
    'touchup' and 'touchup_id'."""
    ctx = setup_completed_appointment(
        clock=clock, complete_clock=complete_clock,
        aftercare_acknowledged=aftercare_acknowledged,
    )
    if request_clock is not None:
        set_clock(request_clock)
    touchup = get_success_data(
        api_client.request_touchup(
            ctx["appointment_id"], make_client_headers(ctx["client_id"])
        )
    )
    ctx["touchup"] = touchup
    ctx["touchup_id"] = touchup["id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 7: portfolio item on a completed parent
# ---------------------------------------------------------------------------
def setup_draft_portfolio_item(*, clock="2026-06-01T12:00:00Z",
                               complete_clock="2026-06-10T14:00:00Z"):
    """A COMPLETED HOURLY appointment with one DRAFT portfolio item created by
    the artist. Returns the completed context plus 'portfolio_item' and
    'portfolio_item_id'."""
    ctx = setup_completed_appointment(clock=clock, complete_clock=complete_clock)
    item = get_success_data(
        api_client.create_portfolio_item(
            factories.create_portfolio_item_payload(
                ctx["artist_id"], ctx["appointment_id"]
            ),
            make_artist_headers(ctx["artist_id"]),
        )
    )
    ctx["portfolio_item"] = item
    ctx["portfolio_item_id"] = item["id"]
    return ctx


def setup_draft_portfolio_item_on_confirmed():
    """A CONFIRMED (NOT completed) HOURLY appointment with a DRAFT portfolio
    item. Used to test that publishing requires a COMPLETED parent; the portfolio
    item is created directly on the confirmed appointment."""
    ctx = setup_confirmed_appointment()
    item = get_success_data(
        api_client.create_portfolio_item(
            factories.create_portfolio_item_payload(
                ctx["artist_id"], ctx["appointment_id"]
            ),
            make_artist_headers(ctx["artist_id"]),
        )
    )
    ctx["portfolio_item"] = item
    ctx["portfolio_item_id"] = item["id"]
    return ctx
