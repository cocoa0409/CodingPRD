"""Payload factories — one per entity, input fields only.

Only fields the PRD marks as client input appear here. Server/computed fields
(status, loyalty_tier, copies_available, estimated_total_cents, payouts, ...)
are never sent.
"""
import itertools

_counter = itertools.count(1)


def _unique_email(prefix: str = "cust") -> str:
    return f"{prefix}-{next(_counter)}@example.com"


# ---- Customer ----
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(amount_cents: int, reason: str = "ADJUSTMENT",
                                     **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


# ---- ComicSeries ----
def create_comic_series_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Series",
        "publisher": "Test Publisher",
    }
    defaults.update(overrides)
    return defaults


# ---- ComicIssue ----
def create_comic_issue_payload(series_id: str, **overrides) -> dict:
    defaults = {
        "series_id": series_id,
        "issue_number": "1",
        "cover_price_cents": 400,
        "on_sale_date": "2026-04-01T00:00:00Z",
        "order_cutoff_date": "2026-03-15T00:00:00Z",
        "copies_ordered": 5,
    }
    defaults.update(overrides)
    return defaults


# ---- PullSubscription ----
def create_pull_subscription_payload(customer_id: str, series_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "series_id": series_id,
    }
    defaults.update(overrides)
    return defaults


# ---- Reservation ----
def create_reservation_payload(customer_id: str, issue_id: str,
                               expected_comic_issue_version: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "issue_id": issue_id,
        "expected_comic_issue_version": expected_comic_issue_version,
    }
    defaults.update(overrides)
    return defaults


# ---- PreOrder ----
def create_pre_order_payload(customer_id: str, issue_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "issue_id": issue_id,
    }
    defaults.update(overrides)
    return defaults


# ---- BackIssue ----
def create_back_issue_payload(series_id: str, **overrides) -> dict:
    defaults = {
        "series_id": series_id,
        "issue_number": "1",
        "condition": "RAW",
        "price_cents": 500,
    }
    defaults.update(overrides)
    return defaults


# ---- GradingSubmission ----
def create_grading_submission_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "description": "Amazing Spider-Man #300",
        "declared_value_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


# ---- Event ----
def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Signing",
        "store_location": "LOC1",
        "starts_at": "2026-05-01T10:00:00Z",
        "ends_at": "2026-05-01T12:00:00Z",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


# ---- EventRegistration ----
def create_event_registration_payload(customer_id: str, event_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "event_id": event_id,
    }
    defaults.update(overrides)
    return defaults


# ---- Consignment ----
def create_consignment_payload(consignor_id: str, **overrides) -> dict:
    defaults = {
        "consignor_id": consignor_id,
        "description": "Consigned item",
        "asking_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


# ---- Checkout ----
def create_checkout_payload(customer_id: str, line_items, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults
