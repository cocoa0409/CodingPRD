"""Payload factories — one per entity, input fields only.

Each factory builds a body with sensible defaults and accepts **overrides for
any value a test needs to control. Only source:input fields appear here.
"""

DEFAULTS = {
    "VENUE_NAME": "Test Range",
    "BAY_COUNT": 2,
    "BAY_LABEL": "Bay 1",
    "MEMBER_NAME": "Test Member",
    "BASE_RATE_CENTS": 2500,
}


# ─── Venue ────────────────────────────────────────────────────────────────
def create_venue_payload(**overrides) -> dict:
    """name + bay_count required; the four settings are optional (have defaults)."""
    defaults = {
        "name": DEFAULTS["VENUE_NAME"],
        "bay_count": DEFAULTS["BAY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


# ─── Bay ──────────────────────────────────────────────────────────────────
def create_bay_payload(venue_id: str, **overrides) -> dict:
    """venue_id + label required; floor_level / has_target_tech optional."""
    defaults = {
        "venue_id": venue_id,
        "label": DEFAULTS["BAY_LABEL"],
    }
    defaults.update(overrides)
    return defaults


# ─── Member ───────────────────────────────────────────────────────────────
_member_email_seq = [0]


def _next_email() -> str:
    _member_email_seq[0] += 1
    return f"member{_member_email_seq[0]}@x.com"


def create_member_payload(**overrides) -> dict:
    """email + full_name required; tier optional (defaults to STANDARD)."""
    defaults = {
        "email": _next_email(),
        "full_name": DEFAULTS["MEMBER_NAME"],
    }
    defaults.update(overrides)
    return defaults


# ─── GameCard ─────────────────────────────────────────────────────────────
def create_game_card_payload(member_id: str, credits_total: int = 1, **overrides) -> dict:
    defaults = {"member_id": member_id, "credits_total": credits_total}
    defaults.update(overrides)
    return defaults


# ─── GiftCard ─────────────────────────────────────────────────────────────
def create_gift_card_payload(face_value_cents: int = 5000, **overrides) -> dict:
    defaults = {"face_value_cents": face_value_cents}
    defaults.update(overrides)
    return defaults


# ─── Reservation ──────────────────────────────────────────────────────────
def create_reservation_payload(venue_id: str, bay_id: str, member_id: str,
                               start_utc: str, end_utc: str, time_band: str,
                               **overrides) -> dict:
    """venue_id, bay_id, member_id, start_utc, end_utc, time_band required;
    day_type (WEEKDAY) and pay_source (CARD_ON_FILE) optional."""
    defaults = {
        "venue_id": venue_id,
        "bay_id": bay_id,
        "member_id": member_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "time_band": time_band,
    }
    defaults.update(overrides)
    return defaults


# ─── GameSession ──────────────────────────────────────────────────────────
def create_session_payload(bay_id: str, member_id: str, **overrides) -> dict:
    """bay_id + member_id required; reservation_id optional."""
    defaults = {"bay_id": bay_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


# ─── EventPackage ─────────────────────────────────────────────────────────
def create_event_package_payload(venue_id: str, organizer_member_id: str,
                                 headcount_estimate: int, per_head_package_cents: int,
                                 **overrides) -> dict:
    """venue_id, organizer_member_id, headcount_estimate, per_head_package_cents
    required; bay_block_cents (15000) and deposit_cents (0) optional."""
    defaults = {
        "venue_id": venue_id,
        "organizer_member_id": organizer_member_id,
        "headcount_estimate": headcount_estimate,
        "per_head_package_cents": per_head_package_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── FBTab ────────────────────────────────────────────────────────────────
def create_fb_tab_payload(**overrides) -> dict:
    """Either session_id or event_package_id supplied via overrides."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def fb_item_payload(name: str, unit_price_cents: int, qty: int = 1, **overrides) -> dict:
    defaults = {"name": name, "unit_price_cents": unit_price_cents, "qty": qty}
    defaults.update(overrides)
    return defaults


# ─── QueueTicket ──────────────────────────────────────────────────────────
def create_queue_ticket_payload(venue_id: str, member_id: str, **overrides) -> dict:
    """venue_id + member_id required; game_card_id and party_size optional."""
    defaults = {"venue_id": venue_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


# ─── Lesson ───────────────────────────────────────────────────────────────
def create_lesson_payload(venue_id: str, bay_id: str, member_id: str, kind: str,
                          start_utc: str, end_utc: str, **overrides) -> dict:
    """venue_id, bay_id, member_id, kind, start_utc, end_utc required;
    seats optional (defaults to 1)."""
    defaults = {
        "venue_id": venue_id,
        "bay_id": bay_id,
        "member_id": member_id,
        "kind": kind,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults
