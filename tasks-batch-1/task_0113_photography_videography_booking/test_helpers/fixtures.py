"""Composite setup helpers for the Photography & Videography Booking API.

Each test runs against a freshly-rebooted, empty database, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.

Identity threading: Client and Photographer are entity-backed (PRD §2.1). Every
ownership-gated call uses make_client_headers(client_id) /
make_photographer_headers(lead_photographer_id) with the real entity id — never the
shared TEST_USERS fallback. The owning Photographer for a ShootSchedule/Gallery is
the booking's lead_photographer_id.

Naming reflects the PRD engagement stages:
  participants/catalogue -> booking (DRAFT) -> contract sign -> schedule ->
  confirm (CONFIRMED) -> deposit settle (DEPOSIT_PAID) -> shoot complete (SHOT) ->
  gallery upload (PROOFING) -> finalize (DELIVERED) -> close (CLOSED).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_client_headers, make_photographer_headers, make_admin_headers,
)
from .factories import (
    create_client_payload,
    create_photographer_payload,
    create_session_package_payload,
    create_booking_payload,
    create_payment_payload,
    create_contract_payload,
    create_shoot_schedule_payload,
    upload_gallery_payload,
    second_shooter_assignment_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Test clock
# ---------------------------------------------------------------------------
def set_clock(iso8601: str, headers=ADMIN):
    """Set the server's logical UTC clock for deterministic temporal tests (PRD §3.8)."""
    return get_success_data(api_client.set_clock(iso8601, headers))


def _list(response):
    """Return (data_list, meta) from a paginated list response."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 0: participants and the session catalogue
# ---------------------------------------------------------------------------
def create_client(**overrides):
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def create_photographer(hourly_rate_cents=7000, **overrides):
    payload = create_photographer_payload(hourly_rate_cents=hourly_rate_cents, **overrides)
    return get_success_data(api_client.create_photographer(payload, ADMIN))


def create_package(**overrides):
    """Create a SessionPackage. Override base_fee_cents, deposit_pct,
    included_shoot_hours, overage_hourly_rate_cents, included_edited_images,
    requires_model_release, active, etc."""
    return get_success_data(
        api_client.create_session_package(create_session_package_payload(**overrides), ADMIN)
    )


def create_booking(client_id, package_id, lead_photographer_id, requested_shoot_hours=2):
    """Create a DRAFT booking as the owning Client."""
    payload = create_booking_payload(
        client_id, package_id, lead_photographer_id, requested_shoot_hours=requested_shoot_hours
    )
    return get_success_data(
        api_client.create_booking(payload, make_client_headers(client_id))
    )


# ---------------------------------------------------------------------------
# Tier 1: a fresh participant set + DRAFT booking
# ---------------------------------------------------------------------------
def setup_draft_booking(
    base_fee_cents=100000,
    deposit_pct=0.30,
    included_shoot_hours=2,
    overage_hourly_rate_cents=12000,
    included_edited_images=30,
    requires_model_release=False,
    active=True,
    session_type="PORTRAIT",
    tier="BASIC",
    requested_shoot_hours=2,
    lead_hourly_rate_cents=7000,
):
    """Client + Photographer + active SessionPackage + DRAFT booking.

    Returns dict(client, photographer, package, booking). The booking is created
    by the owning Client; later ownership-gated calls thread the client id.
    """
    client = create_client()
    photographer = create_photographer(hourly_rate_cents=lead_hourly_rate_cents)
    package = create_package(
        session_type=session_type, tier=tier,
        base_fee_cents=base_fee_cents, deposit_pct=deposit_pct,
        included_shoot_hours=included_shoot_hours,
        overage_hourly_rate_cents=overage_hourly_rate_cents,
        included_edited_images=included_edited_images,
        requires_model_release=requires_model_release, active=active,
    )
    booking = create_booking(
        client["id"], package["id"], photographer["id"],
        requested_shoot_hours=requested_shoot_hours,
    )
    return {
        "client": client,
        "photographer": photographer,
        "package": package,
        "booking": booking,
    }


# ---------------------------------------------------------------------------
# Tier 1b: contract lifecycle + schedule (the pre-confirm preconditions)
# ---------------------------------------------------------------------------
def create_signed_contract(booking_id, client_id, includes_model_release=False):
    """Draft -> send -> sign a contract for a booking. Returns the SIGNED contract.

    Contract create/send are StudioAdmin; sign is the owning Client."""
    overrides = {}
    if includes_model_release:
        overrides["includes_model_release"] = True
    contract = get_success_data(
        api_client.create_contract(create_contract_payload(booking_id, **overrides), ADMIN)
    )
    get_success_data(api_client.send_contract(contract["id"], ADMIN))
    contract = get_success_data(
        api_client.sign_contract(contract["id"], make_client_headers(client_id))
    )
    return contract


def create_sent_contract(booking_id, includes_model_release=False):
    """Draft -> send a contract (left in SENT, not signed). Returns the SENT contract."""
    overrides = {}
    if includes_model_release:
        overrides["includes_model_release"] = True
    contract = get_success_data(
        api_client.create_contract(create_contract_payload(booking_id, **overrides), ADMIN)
    )
    contract = get_success_data(api_client.send_contract(contract["id"], ADMIN))
    return contract


def create_schedule(booking_id, start_utc, end_utc, headers=ADMIN):
    """Schedule a shoot window (SCHEDULED). StudioAdmin or Photographer may create."""
    payload = create_shoot_schedule_payload(booking_id, start_utc, end_utc)
    return get_success_data(api_client.create_shoot_schedule(payload, headers))


# ---------------------------------------------------------------------------
# Tier 2: confirmed booking (DRAFT -> CONFIRMED)
# ---------------------------------------------------------------------------
def setup_confirmed_booking(
    start_utc="2026-07-20T10:00:00Z",
    end_utc="2026-07-20T12:00:00Z",
    includes_model_release=None,
    **package_kwargs
):
    """Build a DRAFT booking, sign its contract, schedule the shoot, and confirm it.

    Returns dict(client, photographer, package, booking, contract, schedule) where
    booking is the CONFIRMED booking (with pinned deposit_due_cents). If
    includes_model_release is None it defaults to the package's requires_model_release
    so confirm passes the model-release gate.

    package_kwargs are forwarded to setup_draft_booking (base_fee_cents, deposit_pct,
    requested_shoot_hours, requires_model_release, etc.).
    """
    base = setup_draft_booking(**package_kwargs)
    client, photographer = base["client"], base["photographer"]
    booking, package = base["booking"], base["package"]

    if includes_model_release is None:
        includes_model_release = package["requires_model_release"]

    contract = create_signed_contract(
        booking["id"], client["id"], includes_model_release=includes_model_release
    )
    schedule = create_schedule(booking["id"], start_utc, end_utc)
    booking = get_success_data(
        api_client.confirm_booking(booking["id"], make_client_headers(client["id"]))
    )
    return {
        "client": client,
        "photographer": photographer,
        "package": package,
        "booking": booking,
        "contract": contract,
        "schedule": schedule,
    }


# ---------------------------------------------------------------------------
# Tier 3: deposit-paid (UNPAID -> DEPOSIT_PAID)
# ---------------------------------------------------------------------------
def settle_deposit(booking_id, deposit_due_cents):
    """Create + settle a DEPOSIT payment equal to the pinned deposit_due_cents."""
    payment = get_success_data(
        api_client.create_payment(
            create_payment_payload(booking_id, "DEPOSIT", deposit_due_cents), ADMIN
        )
    )
    return get_success_data(api_client.settle_payment(payment["id"], ADMIN))


def setup_deposit_paid_booking(
    start_utc="2026-07-20T10:00:00Z",
    end_utc="2026-07-20T12:00:00Z",
    **package_kwargs
):
    """CONFIRMED booking advanced to DEPOSIT_PAID by settling the deposit.

    Returns the same dict as setup_confirmed_booking, with booking re-fetched after
    settlement (payment_status == DEPOSIT_PAID)."""
    ctx = setup_confirmed_booking(start_utc=start_utc, end_utc=end_utc, **package_kwargs)
    settle_deposit(ctx["booking"]["id"], ctx["booking"]["deposit_due_cents"])
    ctx["booking"] = get_success_data(
        api_client.get_booking(ctx["booking"]["id"], ADMIN)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: shot booking (CONFIRMED+DEPOSIT_PAID -> SHOT) and gallery in PROOFING
# ---------------------------------------------------------------------------
def setup_shot_booking(
    start_utc="2026-07-20T10:00:00Z",
    end_utc="2026-07-20T12:00:00Z",
    complete_clock="2026-07-20T12:30:00Z",
    **package_kwargs
):
    """DEPOSIT_PAID booking with its shoot completed (workflow_status == SHOT).

    Advances the clock past end_utc, then completes the shoot as the lead photographer.
    Returns the setup dict with booking re-fetched (SHOT) and schedule COMPLETED.
    """
    ctx = setup_deposit_paid_booking(start_utc=start_utc, end_utc=end_utc, **package_kwargs)
    photographer = ctx["photographer"]
    set_clock(complete_clock)
    schedule = get_success_data(
        api_client.complete_shoot_schedule(
            ctx["schedule"]["id"], make_photographer_headers(photographer["id"])
        )
    )
    ctx["schedule"] = schedule
    ctx["booking"] = get_success_data(api_client.get_booking(ctx["booking"]["id"], ADMIN))
    return ctx


def create_gallery_in_proofing(booking_id, lead_photographer_id, delivered_image_count=30):
    """Create a Gallery for a SHOT booking and upload images -> PROOFING.
    Gallery create + upload are by the lead Photographer (owner)."""
    headers = make_photographer_headers(lead_photographer_id)
    gallery = get_success_data(
        api_client.create_gallery({"booking_id": booking_id}, headers)
    )
    gallery = get_success_data(
        api_client.upload_gallery(
            gallery["id"], upload_gallery_payload(delivered_image_count), headers
        )
    )
    return gallery


def setup_proofing_gallery(
    delivered_image_count=30,
    included_edited_images=30,
    start_utc="2026-07-20T10:00:00Z",
    end_utc="2026-07-20T12:00:00Z",
    complete_clock="2026-07-20T12:30:00Z",
    **package_kwargs
):
    """SHOT booking with a Gallery in PROOFING (uploaded delivered_image_count images).

    Returns the setup dict plus a "gallery" key.
    """
    ctx = setup_shot_booking(
        start_utc=start_utc, end_utc=end_utc, complete_clock=complete_clock,
        included_edited_images=included_edited_images, **package_kwargs
    )
    gallery = create_gallery_in_proofing(
        ctx["booking"]["id"], ctx["photographer"]["id"],
        delivered_image_count=delivered_image_count,
    )
    ctx["gallery"] = gallery
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: second-shooter assignment helpers
# ---------------------------------------------------------------------------
def assign_second_shooter(schedule_id, photographer_id, expected_version):
    """Assign a second shooter with the current schedule version (OCC). StudioAdmin."""
    payload = second_shooter_assignment_payload(photographer_id, expected_version)
    return get_success_data(
        api_client.create_second_shooter_assignment(schedule_id, payload, ADMIN)
    )


def fresh_version(get_callable, entity_id):
    """Re-read an entity and return its current version (helper for OCC tests)."""
    data = get_success_data(get_callable(entity_id, ADMIN))
    return data["version"]
