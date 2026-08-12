"""Payload factories — one per entity, input fields only (PRD section 3)."""
import itertools

DEFAULTS = {
    "BASE_PRICE_PER_LOT_CENTS": 5000000,
    "ANNUAL_ESCALATION_PCT": 6.0,
    "PENALTY_PER_LOT_PER_DAY_CENTS": 1000,
    "EARNEST_MONEY_CENTS": 1000000,
    "INTEREST_RATE_ANNUAL_PCT": 5.0,
}

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_community_payload(**overrides) -> dict:
    defaults = {
        "community_name": f"Community {_seq()}",
        "total_planned_units": 100,
    }
    defaults.update(overrides)
    return defaults


def activate_payload(**overrides) -> dict:
    defaults = {"declarant_director_names": ["D1", "D2", "D3", "D4", "D5"]}
    defaults.update(overrides)
    return defaults


def create_phase_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "phase_name": f"Phase {_seq()}",
        "sequence_no": 1,
        "planned_lot_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_amenity_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "amenity_type": "CLUBHOUSE",
        "hard_deadline_date": "2027-12-31T00:00:00Z",
        "budgeted_cost_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_builder_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "legal_name": f"Builder {_seq()}",
        "credit_tier": "A",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "builder_id": None,
        "phase_id": None,
        "base_price_per_lot_cents": DEFAULTS["BASE_PRICE_PER_LOT_CENTS"],
        "annual_escalation_pct": DEFAULTS["ANNUAL_ESCALATION_PCT"],
        "penalty_per_lot_per_day_cents": DEFAULTS["PENALTY_PER_LOT_PER_DAY_CENTS"],
        "earnest_money_cents": DEFAULTS["EARNEST_MONEY_CENTS"],
        "total_lots_committed": 1,
    }
    defaults.update(overrides)
    return defaults


def create_tranche_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "tranche_no": 1,
        "due_date": "2026-06-30T00:00:00Z",
        "lot_count_due": 1,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "phase_id": None,
        "parcel_number": f"PARCEL-{_seq()}",
    }
    defaults.update(overrides)
    return defaults


def create_closing_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "lot_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "fiscal_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    defaults = {
        "budget_id": None,
        "category": "MANAGEMENT",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_rate_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "budget_id": None,
        "fiscal_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_district_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "district_name": f"District {_seq()}",
        "interest_rate_annual_pct": DEFAULTS["INTEREST_RATE_ANNUAL_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_advance_payload(**overrides) -> dict:
    defaults = {
        "district_id": None,
        "amount_cents": 1000000,
        "advance_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_levy_payload(**overrides) -> dict:
    defaults = {
        "district_id": None,
        "levy_year": 2026,
        "amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "district_id": None,
        "amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "lot_id": None,
        "project_type": "NEW_CONSTRUCTION",
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "lot_id": None,
        "violation_type": "SETBACK",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "title": f"Event {_seq()}",
        "venue": "SALES_CENTER",
        "start_at": "2026-05-20T10:00:00Z",
        "end_at": "2026-05-20T12:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_rsvp_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,
        "resident_id": None,
        "party_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "agent_name": f"Agent {_seq()}",
        "visitor_name": f"Visitor {_seq()}",
        "start_at": "2026-05-02T10:00:00Z",
        "end_at": "2026-05-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "community_id": None,
        "full_name": f"Resident {n}",
        "email": f"resident{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {
        "community_id": None,
        "notice_type": "GENERAL_MEETING",
        "subject": f"Notice {_seq()}",
        "body": "body",
        "send_at": "2026-05-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
