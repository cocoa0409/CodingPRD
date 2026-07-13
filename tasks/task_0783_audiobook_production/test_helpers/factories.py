"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """Generate a process-unique email so onboarding never collides."""
    return f"{prefix}-{next(_counter)}@example.com"


def create_author_payload(**overrides) -> dict:
    payload = {"name": "Test Author", "email": unique_email("author")}
    payload.update(overrides)
    return payload


def create_narrator_payload(**overrides) -> dict:
    payload = {
        "name": "Test Narrator",
        "email": unique_email("narrator"),
        "hourly_rate_cents": 20000,
    }
    payload.update(overrides)
    return payload


def create_title_payload(**overrides) -> dict:
    payload = {
        "title_name": "Test Title",
        "isbn": "978-0000000000",
        "exclusivity": "NON_EXCLUSIVE",
        "territory": "WORLD",
        "list_price_cents": 2000,
    }
    payload.update(overrides)
    return payload


def create_audition_payload(title_id, **overrides) -> dict:
    payload = {"title_id": title_id, "sample_url": "http://sample/audition"}
    payload.update(overrides)
    return payload


def create_contract_payload(title_id, narrator_id, expected_title_version, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "narrator_id": narrator_id,
        "deal_type": "ROYALTY_SHARE",
        "royalty_share_pct": 0.30,
        "expected_title_version": expected_title_version,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(title_id, start_date, end_date, **overrides) -> dict:
    payload = {"title_id": title_id, "start_date": start_date, "end_date": end_date}
    payload.update(overrides)
    return payload


def create_milestone_payload(contract_id, milestone_type="FULL", **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "milestone_type": milestone_type,
        "audio_url": "http://audio/deliverable",
    }
    if milestone_type == "FULL":
        payload["finished_hours"] = 6.0
    payload.update(overrides)
    return payload


def create_qc_review_payload(outcome="PASS", **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "FAIL":
        payload["notes"] = "Revision required"
    payload.update(overrides)
    return payload


def create_channel_payload(**overrides) -> dict:
    payload = {
        "name": "Test Channel",
        "supported_territories": ["US"],
        "retailer_cut_pct": 0.40,
    }
    payload.update(overrides)
    return payload


def create_listing_payload(title_id, channel_id, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "channel_id": channel_id,
        "territory": "US",
        "effective_from": "2026-03-01",
        "effective_until": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def create_sales_event_payload(listing_id, units_sold, unit_price_cents, occurred_at, **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "units_sold": units_sold,
        "unit_price_cents": unit_price_cents,
        "occurred_at": occurred_at,
    }
    payload.update(overrides)
    return payload


def create_statement_payload(title_id, period_start, period_end, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload
