"""Payload factories — one per creatable entity, input fields only (PRD §3, §4)."""


def create_session_payload(**overrides) -> dict:
    """PictureDaySession create body (PRD §3.1)."""
    defaults = {
        "school_name": "Test Elementary",
        "scheduled_date": "2026-05-01T00:00:00Z",
        "gallery_closes_at": "2026-12-31T00:00:00Z",
        "retouch_budget_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(session_id, **overrides) -> dict:
    """Student roster row (PRD §3.1)."""
    defaults = {
        "picture_day_session_id": session_id,
        "full_name": "Test Student",
        "grade": "5",
        "homeroom": "R-204",
        "guardian_user_id": "guardian-1",
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(session_id, **overrides) -> dict:
    """PackageItem catalog entry (PRD §3.1)."""
    defaults = {
        "picture_day_session_id": session_id,
        "sku": "BASIC-1",
        "name": "Basic Package",
        "tier": "BASIC",
        "base_price_cents": 2499,
    }
    defaults.update(overrides)
    return defaults


def create_backdrop_payload(session_id, **overrides) -> dict:
    """Backdrop resource (PRD §3.1)."""
    defaults = {
        "picture_day_session_id": session_id,
        "label": "Blue Marble",
    }
    defaults.update(overrides)
    return defaults


def create_photographer_payload(session_id, **overrides) -> dict:
    """Photographer resource (PRD §3.1)."""
    defaults = {
        "picture_day_session_id": session_id,
        "full_name": "Test Photographer",
    }
    defaults.update(overrides)
    return defaults


def create_capture_slot_payload(session_id, backdrop_id, photographer_id, **overrides) -> dict:
    """CaptureSlot booking (PRD §3.2)."""
    defaults = {
        "picture_day_session_id": session_id,
        "backdrop_id": backdrop_id,
        "photographer_id": photographer_id,
        "homeroom": "R-204",
        "start_minute": 600,
        "end_minute": 660,
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(session_id, **overrides) -> dict:
    """Photo capture slate (PRD §3.3)."""
    defaults = {
        "picture_day_session_id": session_id,
        "candidate_name": "Test Student",
        "candidate_grade": "5",
        "candidate_homeroom": "R-204",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(session_id, student_id, **overrides) -> dict:
    """PhotoOrder create body (PRD §3.6)."""
    defaults = {
        "picture_day_session_id": session_id,
        "student_id": student_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(order_id, package_item_id, quantity=1, **overrides) -> dict:
    """OrderLine create body (PRD §3.6)."""
    defaults = {
        "photo_order_id": order_id,
        "package_item_id": package_item_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_retouch_order_payload(photo_id, kind="RETOUCH", **overrides) -> dict:
    """RetouchOrder create body (PRD §3.5)."""
    defaults = {
        "photo_id": photo_id,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id, **overrides) -> dict:
    """Shipment create body (PRD §3.8)."""
    defaults = {
        "photo_order_id": order_id,
        "carrier": "USPS",
        "distribution_method": "HOME_DELIVERY",
        "tracking_code": "TRK-001",
    }
    defaults.update(overrides)
    return defaults
