"""Payload factories — one per entity, input fields only (PRD Section 3/4)."""

# Reference convention ("InkExpo 2026"): 4 selling days 2026-10-15..18,
# renewal opens 2026-08-05, public window 2026-08-12..2026-08-25,
# early-bird deadline 2026-08-20, tax 8.75% (875 bp), permits required.
CONVENTION_DEFAULTS = {
    "name": "InkExpo 2026",
    "starts_at": "2026-10-15T09:00:00Z",
    "ends_at": "2026-10-18T18:00:00Z",
    "renewal_open_at": "2026-08-05T00:00:00Z",
    "application_open_at": "2026-08-12T00:00:00Z",
    "application_close_at": "2026-08-25T00:00:00Z",
    "early_bird_deadline": "2026-08-20T00:00:00Z",
    "tax_permit_required": True,
    "sales_tax_rate_bp": 875,
}

DEFAULT_QUOTAS = [
    {"category": "ARTIST_ALLEY", "max_accepted": 2, "max_waitlisted": 2},
    {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1},
]

DEFAULT_DOCK_DOORS = [{"door_code": "D1"}, {"door_code": "D2"}]


def _with_overrides(defaults, overrides):
    payload = dict(defaults)
    payload.update(overrides)
    return payload


def create_convention_payload(
    category_quotas=None, dock_doors=None, **overrides
) -> dict:
    payload = _with_overrides(CONVENTION_DEFAULTS, overrides)
    payload["category_quotas"] = (
        list(category_quotas) if category_quotas is not None else list(DEFAULT_QUOTAS)
    )
    payload["dock_doors"] = (
        list(dock_doors) if dock_doors is not None else list(DEFAULT_DOCK_DOORS)
    )
    return payload


def create_space_unit_payload(convention_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "space_code": "A-101",
        "block": "A",
        "unit_number": 101,
        "hall": "MAIN",
        "kind": "BOOTH_10X10",
        "base_price_cents": 100000,
    }
    return _with_overrides(defaults, overrides)


def create_exhibitor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Dealer One LLC",
        "category": "DEALER",
    }
    return _with_overrides(defaults, overrides)


def create_application_payload(convention_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "category": "DEALER",
        "channel": "OPEN",
        "requested_space_kinds": ["BOOTH_10X10"],
        "requested_space_count": 1,
        "estimated_daily_sales_cents": 33333,
    }
    return _with_overrides(defaults, overrides)


def create_jury_score_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "originality": 80,
        "craft": 90,
        "category_fit": 70,
        "professionalism": 60,
    }
    return _with_overrides(defaults, overrides)


def create_placement_payload(application_id, space_unit_id) -> dict:
    return {"application_id": application_id, "space_unit_id": space_unit_id}


def create_neighbor_request_payload(convention_id, target_exhibitor_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "target_exhibitor_id": target_exhibitor_id,
        "kind": "ADJACENT_TO",
    }
    return _with_overrides(defaults, overrides)


def create_staff_member_payload(convention_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "full_name": "Staff One",
    }
    return _with_overrides(defaults, overrides)


def create_load_slot_payload(convention_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "direction": "INBOUND",
        "starts_at": "2026-10-14T08:00:00Z",
        "ends_at": "2026-10-14T12:00:00Z",
        "pallet_capacity": 10,
    }
    return _with_overrides(defaults, overrides)


def create_freight_booking_payload(
    application_id, load_slot_id, dock_door_id, **overrides
) -> dict:
    defaults = {
        "application_id": application_id,
        "load_slot_id": load_slot_id,
        "dock_door_id": dock_door_id,
        "door_starts_at": "2026-10-14T08:00:00Z",
        "door_ends_at": "2026-10-14T09:00:00Z",
        "pallet_count": 2,
    }
    return _with_overrides(defaults, overrides)


def create_issue_ticket_payload(convention_id, exhibitor_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "exhibitor_id": exhibitor_id,
        "category": "CONDUCT",
        "severity": "CRITICAL",
        "description": "Policy incident at booth",
    }
    return _with_overrides(defaults, overrides)


def create_sales_report_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "lines": [
            {"sale_date": "2026-10-15", "gross_cents": 33333},
            {"sale_date": "2026-10-16", "gross_cents": 33333},
            {"sale_date": "2026-10-17", "gross_cents": 33333},
        ],
    }
    return _with_overrides(defaults, overrides)


def submit_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": "ST-4432",
        "permit_expires_at": "2027-01-01T00:00:00Z",
    }
    return _with_overrides(defaults, overrides)
