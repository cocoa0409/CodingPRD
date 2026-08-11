"""Composite setup helpers for the chair-massage workflow tests.

Every helper builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints. Setup calls use the lenient validator so a
failure surfaces as a clear setup error naming the failing step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_booking_payload,
    create_corporate_account_payload,
    create_region_payload,
    create_satisfaction_survey_payload,
    create_slot_claim_payload,
    create_therapist_license_payload,
    create_therapist_payload,
    create_waiver_payload,
    create_wellness_program_payload,
)
from .test_users import (
    TEST_USERS,
    make_organizer_headers,
    make_therapist_headers,
)

EVENT_DAY_CLOCK = "2026-06-10T09:00:00Z"
DEFAULT_EVENT_DATE = "2026-06-10"


def admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-entity creators
# ---------------------------------------------------------------------------

def create_region(**overrides) -> dict:
    resp = api_client.create_region(create_region_payload(**overrides), admin_headers())
    return get_success_data(resp)


def create_corporate_account(region_id: str, **overrides) -> dict:
    payload = create_corporate_account_payload(region_id=region_id, **overrides)
    resp = api_client.create_corporate_account(payload, admin_headers())
    return get_success_data(resp)


def create_therapist(home_region_id: str, **overrides) -> dict:
    payload = create_therapist_payload(home_region_id=home_region_id, **overrides)
    resp = api_client.create_therapist(payload, admin_headers())
    return get_success_data(resp)


def create_therapist_license(therapist_id: str, region_id: str, **overrides) -> dict:
    payload = create_therapist_license_payload(
        therapist_id=therapist_id, region_id=region_id, **overrides,
    )
    resp = api_client.create_therapist_license(payload, admin_headers())
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(to_iso8601, admin_headers()))


# ---------------------------------------------------------------------------
# Tier 2: base bundle (region + account + therapist [+ license])
# ---------------------------------------------------------------------------

def setup_region_account_therapist(
    region_overrides: dict = None,
    account_overrides: dict = None,
    therapist_overrides: dict = None,
    license_overrides: dict = None,
    with_license: bool = True,
) -> dict:
    """Region + corporate account + therapist (licensed in the region).

    Returns a context dict with the entities and the identity-bound headers:
    ``organizer`` is bound to the account id, ``therapist_headers`` to the
    therapist id (ownership-gated calls must use these, per PRD §2.1).
    """
    region = create_region(**(region_overrides or {}))
    account = create_corporate_account(region["id"], **(account_overrides or {}))
    therapist = create_therapist(region["id"], **(therapist_overrides or {}))
    license_ = None
    if with_license:
        license_ = create_therapist_license(
            therapist["id"], region["id"], **(license_overrides or {}),
        )
    return {
        "region": region,
        "account": account,
        "therapist": therapist,
        "license": license_,
        "admin": admin_headers(),
        "organizer": make_organizer_headers(account["id"]),
        "therapist_headers": make_therapist_headers(therapist["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 1: booking state progression
# ---------------------------------------------------------------------------

def create_event_booking(ctx: dict, **overrides) -> dict:
    payload = create_booking_payload(
        **{
            "corporate_account_id": ctx["account"]["id"],
            "region_id": ctx["region"]["id"],
            **overrides,
        }
    )
    resp = api_client.create_booking(payload, ctx["organizer"])
    return get_success_data(resp)


def get_booking(ctx: dict, booking_id: str) -> dict:
    return get_success_data(api_client.get_booking(booking_id, ctx["organizer"]))


def get_chair(ctx: dict, chair_id: str) -> dict:
    return get_success_data(api_client.get_chair_slot(chair_id, ctx["organizer"]))


def get_slot_claim(ctx: dict, claim_id: str) -> dict:
    return get_success_data(api_client.get_slot_claim(claim_id, ctx["organizer"]))


def list_booking_chairs(ctx: dict, booking_id: str) -> list:
    return get_success_data(
        api_client.list_booking_chair_slots(booking_id, ctx["organizer"])
    )


def open_booking(ctx: dict, booking_id: str):
    """DRAFT -> SCHEDULING. Returns (booking, chairs)."""
    booking = get_success_data(api_client.open_scheduling(booking_id, ctx["organizer"]))
    chairs = list_booking_chairs(ctx, booking_id)
    return booking, chairs


def assign_therapist(ctx: dict, chair_id: str, therapist_id: str) -> dict:
    resp = api_client.assign_chair_slot(
        chair_id, {"therapist_id": therapist_id}, ctx["organizer"],
    )
    return get_success_data(resp)


def confirm_booking(ctx: dict, booking_id: str) -> dict:
    """SCHEDULING -> CONFIRMED, fetching a fresh version for the OCC field."""
    version = get_booking(ctx, booking_id)["version"]
    resp = api_client.confirm_booking(
        booking_id, {"expected_booking_version": version}, ctx["organizer"],
    )
    return get_success_data(resp)


def start_service(ctx: dict, booking_id: str) -> dict:
    return get_success_data(api_client.start_service(booking_id, ctx["organizer"]))


def complete_booking(ctx: dict, booking_id: str) -> dict:
    return get_success_data(api_client.complete_booking(booking_id, ctx["organizer"]))


# ---------------------------------------------------------------------------
# Tier 3: day-of-event lifecycle and the sign-up sheet
# ---------------------------------------------------------------------------

def drive_booking_in_progress(
    ctx: dict,
    booking_id: str,
    chairs: list,
    event_day_clock: str = EVENT_DAY_CLOCK,
) -> dict:
    """CONFIRMED -> IN_PROGRESS: confirm, advance the logical clock to the
    event date, depart + arrive every assigned chair, then start service."""
    confirm_booking(ctx, booking_id)
    set_clock(event_day_clock)
    for chair in chairs:
        th = make_therapist_headers(chair["therapist_id"])
        get_success_data(api_client.depart_chair_slot(chair["id"], th))
        get_success_data(api_client.arrive_chair_slot(chair["id"], th))
    return start_service(ctx, booking_id)


def add_claim(ctx: dict, chair_id: str, name: str, email: str) -> dict:
    """Create a sign-up-sheet claim, fetching the chair's fresh version first."""
    version = get_chair(ctx, chair_id)["version"]
    payload = create_slot_claim_payload(
        recipient_name=name,
        recipient_email=email,
        expected_chair_slot_version=version,
    )
    resp = api_client.create_slot_claim(chair_id, payload, ctx["organizer"])
    return get_success_data(resp)


def sign_waiver_for_claim(ctx: dict, claim_id: str, booking_id: str, email: str) -> dict:
    payload = create_waiver_payload(booking_id=booking_id, signer_email=email)
    resp = api_client.sign_waiver(claim_id, payload, ctx["organizer"])
    return get_success_data(resp)


def check_in_claim(ctx: dict, claim_id: str) -> dict:
    return get_success_data(api_client.check_in_slot_claim(claim_id, ctx["organizer"]))


def cancel_claim(ctx: dict, claim_id: str) -> dict:
    return get_success_data(api_client.cancel_slot_claim(claim_id, ctx["organizer"]))


def complete_claim(ctx: dict, claim_id: str, therapist_id: str = None) -> dict:
    headers = (
        make_therapist_headers(therapist_id)
        if therapist_id
        else ctx["therapist_headers"]
    )
    return get_success_data(api_client.complete_slot_claim(claim_id, headers))


def submit_survey(ctx: dict, claim_id: str, rating: int, **overrides) -> dict:
    payload = create_satisfaction_survey_payload(rating=rating, **overrides)
    resp = api_client.submit_satisfaction_survey(claim_id, payload, ctx["organizer"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3b: full-pipeline bundles
# ---------------------------------------------------------------------------

def setup_scheduling_booking(
    num_chairs: int = 1,
    assign: bool = True,
    booking_overrides: dict = None,
    **bundle_kwargs,
) -> dict:
    """Base bundle + an EVENT booking in SCHEDULING with ``num_chairs`` chairs,
    each ASSIGNED to the bundle therapist when ``assign`` is true."""
    ctx = setup_region_account_therapist(**bundle_kwargs)
    overrides = {"chair_count": num_chairs}
    overrides.update(booking_overrides or {})
    booking = create_event_booking(ctx, **overrides)
    booking, chairs = open_booking(ctx, booking["id"])
    if assign:
        for chair in chairs:
            assign_therapist(ctx, chair["id"], ctx["therapist"]["id"])
        chairs = list_booking_chairs(ctx, booking["id"])
    ctx.update({"booking": booking, "chairs": chairs})
    return ctx


def setup_in_progress_booking(
    num_claims: int = 0,
    claims_completed: int = 0,
    claims_checked_in: int = 0,
    sign_waivers: bool = True,
    event_day_clock: str = EVENT_DAY_CLOCK,
    booking_overrides: dict = None,
    **bundle_kwargs,
) -> dict:
    """Full pipeline: booking driven to IN_PROGRESS on its event date with
    ``num_claims`` claims on chair 0; the first ``claims_checked_in`` are
    checked in and the first ``claims_completed`` are completed (completion
    implies check-in). All claims get waivers unless ``sign_waivers`` is false.
    """
    if booking_overrides is None and num_claims > 4:
        # Default window (60) x slot (15) seats 4; widen when more are needed.
        booking_overrides = {"window_duration_minutes": 15 * (num_claims + 1)}
    ctx = setup_scheduling_booking(booking_overrides=booking_overrides, **bundle_kwargs)
    booking = ctx["booking"]
    chair = ctx["chairs"][0]
    drive_booking_in_progress(ctx, booking["id"], ctx["chairs"], event_day_clock)
    n_checked = max(claims_checked_in, claims_completed)
    claims = []
    for i in range(num_claims):
        claim = add_claim(ctx, chair["id"], f"Recipient {i}", f"r{i}@example.test")
        if sign_waivers:
            sign_waiver_for_claim(ctx, claim["id"], booking["id"], claim["recipient_email"])
        claims.append(claim)
    for i in range(n_checked):
        check_in_claim(ctx, claims[i]["id"])
    for i in range(claims_completed):
        complete_claim(ctx, claims[i]["id"])
    ctx["booking"] = get_booking(ctx, booking["id"])
    ctx["claims"] = claims
    return ctx


def setup_completed_booking(
    num_claims_completed: int = 0,
    booking_overrides: dict = None,
    **bundle_kwargs,
) -> dict:
    """Full pipeline to a COMPLETED booking whose claims (if any) are all
    COMPLETED: waiver + check-in + complete per claim, then booking complete."""
    ctx = setup_in_progress_booking(
        num_claims=num_claims_completed,
        claims_completed=num_claims_completed,
        booking_overrides=booking_overrides,
        **bundle_kwargs,
    )
    complete_booking(ctx, ctx["booking"]["id"])
    ctx["booking"] = get_booking(ctx, ctx["booking"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: invoices and account balances
# ---------------------------------------------------------------------------

def create_invoice(ctx: dict, booking_id: str, pricing_variant: str) -> dict:
    resp = api_client.create_booking_invoice(
        booking_id, {"pricing_variant": pricing_variant}, ctx["admin"],
    )
    return get_success_data(resp)


def get_invoice(ctx: dict, invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ctx["admin"]))


def get_account(ctx: dict) -> dict:
    return get_success_data(
        api_client.get_corporate_account(ctx["account"]["id"], ctx["admin"])
    )


def setup_completed_booking_with_invoice(
    num_claims_completed: int = 0,
    pricing_variant: str = "FINAL",
    booking_overrides: dict = None,
    **bundle_kwargs,
) -> dict:
    """COMPLETED booking + a DRAFT invoice of the requested pricing variant."""
    ctx = setup_completed_booking(
        num_claims_completed=num_claims_completed,
        booking_overrides=booking_overrides,
        **bundle_kwargs,
    )
    invoice = create_invoice(ctx, ctx["booking"]["id"], pricing_variant)
    ctx["invoice"] = invoice
    return ctx


def setup_issued_invoice(
    num_claims_completed: int = 0,
    booking_overrides: dict = None,
    **bundle_kwargs,
) -> dict:
    """COMPLETED booking + FINAL invoice issued (booking INVOICED)."""
    ctx = setup_completed_booking_with_invoice(
        num_claims_completed=num_claims_completed,
        pricing_variant="FINAL",
        booking_overrides=booking_overrides,
        **bundle_kwargs,
    )
    get_success_data(api_client.issue_invoice(ctx["invoice"]["id"], ctx["admin"]))
    ctx["invoice"] = get_invoice(ctx, ctx["invoice"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Wellness programs
# ---------------------------------------------------------------------------

def create_wellness_program(ctx: dict, **overrides) -> dict:
    payload = create_wellness_program_payload(
        corporate_account_id=ctx["account"]["id"], **overrides,
    )
    resp = api_client.create_wellness_program(payload, ctx["organizer"])
    return get_success_data(resp)


def get_wellness_program(ctx: dict, program_id: str) -> dict:
    return get_success_data(api_client.get_wellness_program(program_id, ctx["admin"]))
