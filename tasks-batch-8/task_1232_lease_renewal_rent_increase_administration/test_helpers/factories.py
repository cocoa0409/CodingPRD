"""Payload factories — input fields only (PRD §3)."""
import itertools

from .constants import CA_OAK, STD_RENT_CENTS, STD_TERM_MONTHS, STD_TERM_START

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_policy_payload(**overrides) -> dict:
    """RentCapPolicy create payload; defaults to the shared CA-OAK fixture."""
    defaults = dict(CA_OAK)
    defaults["jurisdiction_code"] = f"CA-OAK-{next(_counter)}"
    defaults.update(overrides)
    return defaults


def ca_oak_policy_payload() -> dict:
    """The literal CA-OAK policy (fixed jurisdiction_code) for tests that do
    not create more than one policy."""
    return dict(CA_OAK)


def create_property_payload(rent_cap_policy_id: str, **overrides) -> dict:
    defaults = {
        "name": _uniq("Court"),
        "rent_cap_policy_id": rent_cap_policy_id,
        "min_term_months": 12,
        "max_term_months": 12,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "unit_number": _uniq("U"),
        "bedrooms": 1,
        "current_market_rent_cents": 210000,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {"full_name": f"Res Ident {n}", "email": f"res.ident{n}@x.com"}
    defaults.update(overrides)
    return defaults


def create_lease_payload(unit_id: str, resident_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "resident_id": resident_id,
        "term_start_date": STD_TERM_START,
        "term_months": STD_TERM_MONTHS,
        "monthly_rent_cents": STD_RENT_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(expected_lease_version: int, **overrides) -> dict:
    """Offer create payload; OCC version is required (PRD §2.7)."""
    defaults = {"expected_lease_version": expected_lease_version}
    defaults.update(overrides)
    return defaults


def respond_accept_payload() -> dict:
    return {"response_type": "ACCEPT"}


def respond_decline_payload() -> dict:
    return {"response_type": "DECLINE"}


def respond_counter_payload(counter_rent_cents: int, **overrides) -> dict:
    defaults = {"response_type": "COUNTER", "counter_rent_cents": counter_rent_cents}
    defaults.update(overrides)
    return defaults


def create_concession_payload(requested_rent_cents: int, **overrides) -> dict:
    defaults = {"requested_rent_cents": requested_rent_cents}
    defaults.update(overrides)
    return defaults


def create_notice_payload(cause_type: str, effective_date: str, **overrides) -> dict:
    defaults = {"cause_type": cause_type, "effective_date": effective_date}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
