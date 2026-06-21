"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading:
  * Couple writes use `make_couple_headers(couple_user_id)` so the
    X-User-ID matches the wedding's `couple_user_id` ownership check (PRD §2.1).
  * GuestSelf writes use `make_guest_self_headers(guest_id, invitation_token)`
    so X-User-ID matches Guest.id and X-Invitation-Token matches
    Guest.invitation_token (PRD §2.1).

Setup helpers use `get_success_data` from the framework so a failed setup
surfaces as a clear "setup failed" error rather than a misleading assertion
failure deep inside a test.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_wedding_payload,
    create_meal_option_payload,
    create_table_payload,
    create_guest_payload,
    create_plus_one_payload,
    create_seating_assignment_payload,
    create_registry_item_payload,
    create_purchase_payload,
    guest_rsvp_payload,
)
from .test_users import (
    TEST_USERS,
    make_couple_headers,
    make_platform_admin_headers,
    make_platform_integration_headers,
)


# ─── Internal helpers for date math ───────────────────────────────────────

def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp ending in 'Z' to a tz-aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _format_iso(dt: datetime) -> str:
    """Format a tz-aware datetime as an ISO 8601 UTC timestamp ending in 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_ceremony_and_deadline(clock_iso: str) -> Tuple[str, str]:
    """Compute reasonable ceremony_at and rsvp_deadline_at relative to a clock.

    PRD §3.1 requires ceremony_at > current_utc and current_utc < rsvp_deadline_at
    < ceremony_at for `open-rsvp` to succeed. We default to:
      - ceremony_at = clock + 150 days (~5 months)
      - rsvp_deadline_at = clock + 120 days (~4 months)
    so any bootstrap that sets a clock anchors valid future ceremony/deadline
    relative to that clock.
    """
    base = _parse_iso(clock_iso)
    ceremony = base + timedelta(days=150)
    deadline = base + timedelta(days=120)
    return _format_iso(ceremony), _format_iso(deadline)


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> None:
    """Set the server clock used for ceremony_at / rsvp_deadline_at /
    sent_at checks (PRD §2.10)."""
    api_client.set_clock(to_iso8601, make_platform_admin_headers())


# ─── Tier 1: Wedding-only state progression ────────────────────────────────

def create_wedding(
    couple_user_id: str = "couple-1",
    title: str = "Test Wedding",
    ceremony_at: str = "2027-06-01T18:00:00Z",
    rsvp_deadline_at: str = "2027-05-15T23:59:59Z",
    **overrides,
) -> dict:
    """Create a Wedding in DRAFT (PRD §3.1)."""
    payload = create_wedding_payload(
        couple_user_id=couple_user_id,
        title=title,
        ceremony_at=ceremony_at,
        rsvp_deadline_at=rsvp_deadline_at,
        **overrides,
    )
    return get_success_data(api_client.create_wedding(
        payload, make_couple_headers(couple_user_id),
    ))


def create_adult_meal_option(
    wedding: dict,
    code: str = "ADULT",
    label: str = "Adult plate",
    max_servings: int = 10,
    **overrides,
) -> dict:
    """Create one adult MealOption (is_kids=false) for a Wedding."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_meal_option_payload(
        code=code, label=label, max_servings=max_servings,
        is_kids=False, **overrides,
    )
    return get_success_data(api_client.create_meal_option(
        wedding["id"], payload, headers,
    ))


def create_kids_meal_option(
    wedding: dict,
    code: str = "KIDS",
    label: str = "Kids pasta",
    max_servings: int = 10,
    **overrides,
) -> dict:
    """Create one kids MealOption (is_kids=true) for a Wedding."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_meal_option_payload(
        code=code, label=label, max_servings=max_servings,
        is_kids=True, **overrides,
    )
    return get_success_data(api_client.create_meal_option(
        wedding["id"], payload, headers,
    ))


def add_table(
    wedding: dict,
    table_number: int = 1,
    capacity: int = 4,
    kids_only: bool = False,
) -> dict:
    """Add one Table to a Wedding."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_table_payload(
        table_number=table_number, capacity=capacity, kids_only=kids_only,
    )
    return get_success_data(api_client.create_table(
        wedding["id"], payload, headers,
    ))


def add_guest(
    wedding: dict,
    full_name: str,
    email: str,
    is_child: bool = False,
    plus_one_allowed: bool = False,
) -> dict:
    """Add one Guest to a Wedding."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_guest_payload(
        full_name=full_name, email=email,
        is_child=is_child, plus_one_allowed=plus_one_allowed,
    )
    return get_success_data(api_client.create_guest(
        wedding["id"], payload, headers,
    ))


def open_rsvp(wedding: dict) -> dict:
    """Transition wedding DRAFT -> RSVP_OPEN (PRD §3.1)."""
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.open_rsvp(wedding["id"], headers))


def close_rsvp(wedding: dict) -> dict:
    """Transition wedding RSVP_OPEN -> RSVP_CLOSED (PRD §3.1)."""
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.close_rsvp(wedding["id"], headers))


def archive_wedding(wedding: dict) -> dict:
    """Transition wedding SEATED -> ARCHIVED (PRD §3.1)."""
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.archive_wedding(wedding["id"], headers))


def guest_rsvp_attending(
    wedding: dict,
    guest_id: str,
    meal_option_id: str,
) -> dict:
    """Guest RSVPs ATTENDING with a meal selection (Couple-driven)."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = guest_rsvp_payload(attending=True, meal_option_id=meal_option_id)
    return get_success_data(api_client.guest_rsvp(guest_id, payload, headers))


def guest_rsvp_decline(wedding: dict, guest_id: str) -> dict:
    """Guest RSVPs DECLINED (Couple-driven)."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = guest_rsvp_payload(attending=False)
    return get_success_data(api_client.guest_rsvp(guest_id, payload, headers))


def revoke_guest_rsvp(wedding: dict, guest_id: str) -> dict:
    """Revert Guest -> INVITED (Couple-only, RSVP_OPEN window)."""
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.revoke_guest_rsvp(guest_id, headers))


def add_plus_one(
    wedding: dict,
    guest_id: str,
    full_name: str = "Test Partner",
    is_child: bool = False,
    meal_option_id: Optional[str] = None,
) -> dict:
    """Couple adds a PlusOne under a Guest with plus_one_allowed=true."""
    headers = make_couple_headers(wedding["couple_user_id"])
    overrides = {}
    if meal_option_id is not None:
        overrides["meal_option_id"] = meal_option_id
    payload = create_plus_one_payload(
        full_name=full_name, is_child=is_child, **overrides,
    )
    return get_success_data(api_client.create_plus_one(
        guest_id, payload, headers,
    ))


def manual_seat_guest(wedding: dict, table_id: str, guest_id: str) -> dict:
    """Manually create a SeatingAssignment row for a Guest."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_seating_assignment_payload(
        wedding_id=wedding["id"], table_id=table_id,
        assignee_type="GUEST", assignee_id=guest_id,
    )
    return get_success_data(api_client.create_seating_assignment(payload, headers))


def manual_seat_plus_one(wedding: dict, table_id: str, plus_one_id: str) -> dict:
    """Manually create a SeatingAssignment row for a PlusOne."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_seating_assignment_payload(
        wedding_id=wedding["id"], table_id=table_id,
        assignee_type="PLUS_ONE", assignee_id=plus_one_id,
    )
    return get_success_data(api_client.create_seating_assignment(payload, headers))


def finalize_seating(wedding: dict, expected_version: int) -> dict:
    """Finalize seating with OCC."""
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.finalize_seating(
        wedding["id"], expected_version, headers,
    ))


def add_registry_item(
    wedding: dict,
    sku: str = "SKU-1",
    title: str = "Gift",
    target_quantity: int = 2,
    unit_price_cents: int = 1000,
) -> dict:
    """Couple adds a RegistryItem to the Wedding."""
    headers = make_couple_headers(wedding["couple_user_id"])
    payload = create_registry_item_payload(
        sku=sku, title=title,
        target_quantity=target_quantity, unit_price_cents=unit_price_cents,
    )
    return get_success_data(api_client.create_registry_item(
        wedding["id"], payload, headers,
    ))


def ingest_purchase(
    registry_item_id: str,
    platform_code: str = "STORE_A",
    external_purchase_id: str = "ext-1",
    purchaser_name: str = "Buyer",
    quantity: int = 1,
    occurred_at: str = "2027-01-02T10:00:00Z",
) -> dict:
    """PlatformIntegration ingests a purchase."""
    headers = make_platform_integration_headers()
    payload = create_purchase_payload(
        platform_code=platform_code,
        external_purchase_id=external_purchase_id,
        purchaser_name=purchaser_name,
        quantity=quantity,
        occurred_at=occurred_at,
    )
    return get_success_data(api_client.create_purchase(
        registry_item_id, payload, headers,
    ))


def get_thank_you_note_for_purchase(wedding: dict, purchase_id: str) -> Optional[dict]:
    """Look up the auto-created ThankYouNote for a CONFIRMED Purchase.
    Returns None if no note exists (purchase is PENDING_REVIEW or was cancelled).
    """
    headers = make_couple_headers(wedding["couple_user_id"])
    res = api_client.list_thank_you_notes(headers, params={"purchase_id": purchase_id})
    data = get_success_data(res)
    # `data` may be a list or a dict with a list payload; handle both.
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        items = data.get("items") or data.get("data") or []
        if isinstance(items, list) and items:
            return items[0]
    return None


def get_wedding(wedding: dict) -> dict:
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.get_wedding(wedding["id"], headers))


def get_registry_item(wedding: dict, registry_item_id: str) -> dict:
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.get_registry_item(registry_item_id, headers))


def get_guest(wedding: dict, guest_id: str) -> dict:
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.get_guest(guest_id, headers))


def get_plus_one(wedding: dict, plus_one_id: str) -> dict:
    headers = make_couple_headers(wedding["couple_user_id"])
    return get_success_data(api_client.get_plus_one(plus_one_id, headers))


def list_seating_assignments_for_wedding(wedding: dict) -> list:
    headers = make_couple_headers(wedding["couple_user_id"])
    res = api_client.list_seating_assignments(headers, params={"wedding_id": wedding["id"]})
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


# ─── Tier 2: Wedding bootstraps (common chain prefixes) ────────────────────

def bootstrap_wedding_in_draft(
    couple_user_id: str = "couple-draft",
    clock_iso: str = "2027-01-01T00:00:00Z",
    ceremony_at: Optional[str] = None,
    rsvp_deadline_at: Optional[str] = None,
    title: str = "Draft Wedding",
) -> dict:
    """Set clock then create a DRAFT Wedding. Returns the wedding.

    ceremony_at / rsvp_deadline_at default to safely-after-clock_iso values so
    PRD §3.1's open-rsvp preconditions (ceremony_at > current_utc and
    current_utc < rsvp_deadline_at < ceremony_at) hold for arbitrary clock_iso.
    """
    if ceremony_at is None or rsvp_deadline_at is None:
        default_ceremony, default_deadline = _default_ceremony_and_deadline(clock_iso)
        if ceremony_at is None:
            ceremony_at = default_ceremony
        if rsvp_deadline_at is None:
            rsvp_deadline_at = default_deadline
    set_clock(clock_iso)
    return create_wedding(
        couple_user_id=couple_user_id, title=title,
        ceremony_at=ceremony_at, rsvp_deadline_at=rsvp_deadline_at,
    )


def bootstrap_wedding_in_rsvp_open(
    couple_user_id: str = "couple-open",
    clock_iso: str = "2027-01-01T00:00:00Z",
    ceremony_at: Optional[str] = None,
    rsvp_deadline_at: Optional[str] = None,
    title: str = "Open Wedding",
    adult_meal_max_servings: int = 10,
) -> Tuple[dict, dict]:
    """Bootstrap a Wedding all the way to RSVP_OPEN with one adult MealOption.
    Returns (wedding_after_open, adult_meal_option).
    """
    wedding = bootstrap_wedding_in_draft(
        couple_user_id=couple_user_id, clock_iso=clock_iso,
        ceremony_at=ceremony_at, rsvp_deadline_at=rsvp_deadline_at,
        title=title,
    )
    adult_meal = create_adult_meal_option(
        wedding, max_servings=adult_meal_max_servings,
    )
    wedding = open_rsvp(wedding)
    return wedding, adult_meal


def bootstrap_wedding_with_open_registry(
    couple_user_id: str = "couple-reg",
    clock_iso: str = "2027-01-01T00:00:00Z",
    target_quantity: int = 2,
    sku: str = "SKU-REG",
    title: str = "Reg Wedding",
    ceremony_at: Optional[str] = None,
    rsvp_deadline_at: Optional[str] = None,
) -> Tuple[dict, dict]:
    """Bootstrap a Wedding to RSVP_OPEN and add one RegistryItem.
    Returns (wedding, registry_item).
    """
    wedding, _ = bootstrap_wedding_in_rsvp_open(
        couple_user_id=couple_user_id, clock_iso=clock_iso, title=title,
        ceremony_at=ceremony_at, rsvp_deadline_at=rsvp_deadline_at,
    )
    item = add_registry_item(
        wedding, sku=sku, title="Gift Item",
        target_quantity=target_quantity, unit_price_cents=1000,
    )
    return wedding, item


# ─── Tier 3: Lifecycle shortcuts ──────────────────────────────────────────

def bootstrap_seated_wedding(
    couple_user_id: str = "couple-seated",
    clock_iso: str = "2027-01-01T00:00:00Z",
    ceremony_at: Optional[str] = None,
    rsvp_deadline_at: Optional[str] = None,
) -> Tuple[dict, dict, dict, dict, dict]:
    """Bootstrap a Wedding all the way through SEATED with one attending Guest
    seated at one Table. Returns (wedding, adult_meal, table, guest, assignment).
    """
    wedding, adult_meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id=couple_user_id, clock_iso=clock_iso,
        ceremony_at=ceremony_at, rsvp_deadline_at=rsvp_deadline_at,
    )
    table = add_table(wedding, table_number=1, capacity=2, kids_only=False)
    guest = add_guest(
        wedding, full_name="Seat Me", email="seated@example.com",
        is_child=False, plus_one_allowed=False,
    )
    guest = guest_rsvp_attending(wedding, guest["id"], adult_meal["id"])
    wedding = close_rsvp(wedding)
    assignment = manual_seat_guest(wedding, table["id"], guest["id"])
    fresh = get_wedding(wedding)
    wedding = finalize_seating(wedding, fresh["version"])
    return wedding, adult_meal, table, guest, assignment


def bootstrap_archived_wedding(
    couple_user_id: str = "couple-arch",
    clock_iso_before: str = "2027-01-01T00:00:00Z",
    clock_iso_after_ceremony: str = "2027-06-02T00:00:00Z",
    ceremony_at: Optional[str] = None,
    rsvp_deadline_at: Optional[str] = None,
) -> dict:
    """Bootstrap a Wedding all the way through ARCHIVED. Returns the archived
    wedding (status == ARCHIVED).
    """
    wedding, _adult_meal, _table, _guest, _asg = bootstrap_seated_wedding(
        couple_user_id=couple_user_id, clock_iso=clock_iso_before,
        ceremony_at=ceremony_at, rsvp_deadline_at=rsvp_deadline_at,
    )
    set_clock(clock_iso_after_ceremony)
    return archive_wedding(wedding)


def bootstrap_confirmed_purchase(
    couple_user_id: str = "couple-conf",
    clock_iso: str = "2027-01-01T00:00:00Z",
    target_quantity: int = 1,
    quantity: int = 1,
) -> Tuple[dict, dict, dict, dict]:
    """Bootstrap a Wedding + RegistryItem + one CONFIRMED Purchase + its
    auto-created PENDING ThankYouNote.
    Returns (wedding, registry_item, purchase, thank_you_note).
    """
    wedding, item = bootstrap_wedding_with_open_registry(
        couple_user_id=couple_user_id, clock_iso=clock_iso,
        target_quantity=target_quantity,
    )
    purchase = ingest_purchase(
        item["id"], platform_code="STORE_A", external_purchase_id="conf-1",
        purchaser_name="Confirmed Buyer", quantity=quantity,
        occurred_at="2027-01-02T10:00:00Z",
    )
    note = get_thank_you_note_for_purchase(wedding, purchase["id"])
    return wedding, item, purchase, note
