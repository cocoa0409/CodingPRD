"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only `source: input` fields appear here; computed
and system fields are never sent.
"""
import itertools

# Per-process counter so generated emails / labels stay unique within a test.
_counter = itertools.count(1)


def _uid() -> int:
    return next(_counter)


def create_owner_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "full_name": f"Rider {n}",
        "email": f"rider{n}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_stall_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "label": f"Stall-{n}",
        "kind": "STALL",
        "capacity": 1,
        "daily_rate_cents": 4500,
    }
    defaults.update(overrides)
    return defaults


def create_pasture_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "label": f"Pasture-{n}",
        "kind": "PASTURE",
        "capacity": 1,
        "daily_rate_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_horse_payload(owner_id: str, **overrides) -> dict:
    n = _uid()
    defaults = {
        "owner_id": owner_id,
        "name": f"Horse-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_boarding_agreement_payload(horse_id: str, stall_id: str, start_date: str,
                                      **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "stall_id": stall_id,
        "start_date": start_date,
    }
    defaults.update(overrides)
    return defaults


def create_lesson_payload(horse_id: str, starts_at: str, ends_at: str,
                          lesson_fee_cents: int = 8000,
                          instructor_name: str = "Pat", **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "instructor_name": instructor_name,
        "lesson_fee_cents": lesson_fee_cents,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(horse_id: str, scheduled_at: str,
                                 visit_type: str = "FARRIER",
                                 duration_minutes: int = 60,
                                 fee_cents: int = 12000, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "visit_type": visit_type,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "fee_cents": fee_cents,
    }
    defaults.update(overrides)
    return defaults


def create_show_entry_payload(horse_id: str, event_date: str,
                              event_name: str = "County Show",
                              entry_fee_cents: int = 5000, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "event_name": event_name,
        "event_date": event_date,
        "entry_fee_cents": entry_fee_cents,
    }
    defaults.update(overrides)
    return defaults


def create_turnout_payload(horse_id: str, pasture_id: str, window_start: str,
                           window_end: str, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "pasture_id": pasture_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(owner_id: str, period_label: str = "2026-06",
                           **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "period_label": period_label,
    }
    defaults.update(overrides)
    return defaults
