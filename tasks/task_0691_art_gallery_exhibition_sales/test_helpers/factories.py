"""Payload factories — one per resource, input fields only.

Each factory supplies PRD-consistent defaults for required fields with a natural
default and accepts **overrides so a test can control just the values it cares
about. Optional fields (those the PRD marks with a default) are omitted unless
the caller passes them, so default-behavior tests can observe the server default.
"""

DEFAULTS = {
    "GALLERY_NAME": "Test Gallery",
    "HOME_STATE": "CA",
    "OUT_OF_STATE": "NY",
    "SALES_TAX_RATE_BPS": 875,
    "DEFAULT_SPLIT_BPS": 5000,
    "ARTIST_NAME": "Test Artist",
    "ARTWORK_TITLE": "Test Work",
    "LIST_PRICE_CENTS": 400_000,
    "INSURED_VALUE_CENTS": 400_000,
    "EXHIBITION_TITLE": "Test Show",
    "WALL_CAPACITY": 3,
    "OPENS_UTC": "2026-04-10T00:00:00Z",
    "CLOSES_UTC": "2026-05-10T00:00:00Z",
    "BUYER_NAME": "Test Buyer",
    "GROSS_AMOUNT_CENTS": 400_000,
    "BORROWER_NAME": "Test Borrower",
    "LESSEE_NAME": "Test Lessee",
    "MONTHLY_RATE_CENTS": 50_000,
    "TERM_MONTHS": 12,
    "GUEST_NAME": "Test Guest",
}


# ─── Gallery ─────────────────────────────────────────────────────────────────
def create_gallery_payload(**overrides) -> dict:
    """Required: name, home_state_code, sales_tax_rate_bps.
    Optional (server-defaulted): resale_exempt_threshold_cents (0),
    default_consignment_split_bps (5000)."""
    payload = {
        "name": DEFAULTS["GALLERY_NAME"],
        "home_state_code": DEFAULTS["HOME_STATE"],
        "sales_tax_rate_bps": DEFAULTS["SALES_TAX_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


# ─── Artist ──────────────────────────────────────────────────────────────────
def create_artist_payload(gallery_id, **overrides) -> dict:
    """Required: gallery_id, full_name. Optional: split_override_bps."""
    payload = {
        "gallery_id": gallery_id,
        "full_name": DEFAULTS["ARTIST_NAME"],
    }
    payload.update(overrides)
    return payload


# ─── Artwork ─────────────────────────────────────────────────────────────────
def create_artwork_payload(gallery_id, artist_id, **overrides) -> dict:
    """Required: gallery_id, artist_id, title, list_price_cents, insured_value_cents."""
    payload = {
        "gallery_id": gallery_id,
        "artist_id": artist_id,
        "title": DEFAULTS["ARTWORK_TITLE"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "insured_value_cents": DEFAULTS["INSURED_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def provenance_payload(event="Acquired by collector", **overrides) -> dict:
    """Required: event."""
    payload = {"event": event}
    payload.update(overrides)
    return payload


# ─── Exhibition ──────────────────────────────────────────────────────────────
def create_exhibition_payload(gallery_id, **overrides) -> dict:
    """Required: gallery_id, title, wall_capacity, opens_utc, closes_utc."""
    payload = {
        "gallery_id": gallery_id,
        "title": DEFAULTS["EXHIBITION_TITLE"],
        "wall_capacity": DEFAULTS["WALL_CAPACITY"],
        "opens_utc": DEFAULTS["OPENS_UTC"],
        "closes_utc": DEFAULTS["CLOSES_UTC"],
    }
    payload.update(overrides)
    return payload


def wall_slot_payload(artwork_id, position_index, expected_exhibition_version,
                      wall_label="N-1", **overrides) -> dict:
    """Required: artwork_id, wall_label, position_index, expected_exhibition_version."""
    payload = {
        "artwork_id": artwork_id,
        "wall_label": wall_label,
        "position_index": position_index,
        "expected_exhibition_version": expected_exhibition_version,
    }
    payload.update(overrides)
    return payload


# ─── Sale ────────────────────────────────────────────────────────────────────
def create_sale_payload(gallery_id, artwork_id, **overrides) -> dict:
    """Required: gallery_id, artwork_id, buyer_name, buyer_state_code,
    gross_amount_cents. Optional (server-defaulted): exhibition_id,
    discount_bps (0), shipping_cents (0)."""
    payload = {
        "gallery_id": gallery_id,
        "artwork_id": artwork_id,
        "buyer_name": DEFAULTS["BUYER_NAME"],
        "buyer_state_code": DEFAULTS["OUT_OF_STATE"],
        "gross_amount_cents": DEFAULTS["GROSS_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, expected_sale_version, **overrides) -> dict:
    """Required: amount_cents, expected_sale_version."""
    payload = {
        "amount_cents": amount_cents,
        "expected_sale_version": expected_sale_version,
    }
    payload.update(overrides)
    return payload


# ─── PaymentPlan ─────────────────────────────────────────────────────────────
def create_payment_plan_payload(sale_id, installment_count=3, cadence_days=30,
                                first_due_utc="2026-05-01T00:00:00Z", **overrides) -> dict:
    """Required: sale_id, installment_count, cadence_days, first_due_utc."""
    payload = {
        "sale_id": sale_id,
        "installment_count": installment_count,
        "cadence_days": cadence_days,
        "first_due_utc": first_due_utc,
    }
    payload.update(overrides)
    return payload


# ─── LeaseAgreement ──────────────────────────────────────────────────────────
def create_lease_payload(artwork_id, starts_utc="2026-04-01T00:00:00Z", **overrides) -> dict:
    """Required: artwork_id, lessee_name, monthly_rate_cents, term_months,
    starts_utc. Optional (server-defaulted): purchase_credit_bps (0)."""
    payload = {
        "artwork_id": artwork_id,
        "lessee_name": DEFAULTS["LESSEE_NAME"],
        "monthly_rate_cents": DEFAULTS["MONTHLY_RATE_CENTS"],
        "term_months": DEFAULTS["TERM_MONTHS"],
        "starts_utc": starts_utc,
    }
    payload.update(overrides)
    return payload


# ─── OpeningEvent ────────────────────────────────────────────────────────────
def create_opening_event_payload(exhibition_id, capacity=10,
                                 starts_utc="2026-05-01T18:00:00Z",
                                 rsvp_deadline_utc="2026-04-30T00:00:00Z",
                                 **overrides) -> dict:
    """Required: exhibition_id, capacity, starts_utc, rsvp_deadline_utc."""
    payload = {
        "exhibition_id": exhibition_id,
        "capacity": capacity,
        "starts_utc": starts_utc,
        "rsvp_deadline_utc": rsvp_deadline_utc,
    }
    payload.update(overrides)
    return payload


def create_rsvp_payload(opening_event_id, guest_name=None, **overrides) -> dict:
    """Required: opening_event_id, guest_name. Optional (server-defaulted):
    party_size (1)."""
    payload = {
        "opening_event_id": opening_event_id,
        "guest_name": guest_name or DEFAULTS["GUEST_NAME"],
    }
    payload.update(overrides)
    return payload


# ─── Loan ────────────────────────────────────────────────────────────────────
def create_loan_payload(artwork_id, coverage_value_cents,
                        out_utc="2026-04-05T00:00:00Z",
                        due_utc="2026-05-05T00:00:00Z", **overrides) -> dict:
    """Required: artwork_id, borrower_name, coverage_value_cents, out_utc, due_utc."""
    payload = {
        "artwork_id": artwork_id,
        "borrower_name": DEFAULTS["BORROWER_NAME"],
        "coverage_value_cents": coverage_value_cents,
        "out_utc": out_utc,
        "due_utc": due_utc,
    }
    payload.update(overrides)
    return payload


# ─── Payout ──────────────────────────────────────────────────────────────────
def create_payout_payload(artist_id, requested_cents, **overrides) -> dict:
    """Required: artist_id, requested_cents."""
    payload = {
        "artist_id": artist_id,
        "requested_cents": requested_cents,
    }
    payload.update(overrides)
    return payload


# ─── Clock ───────────────────────────────────────────────────────────────────
def set_clock_payload(to_iso8601, **overrides) -> dict:
    """Required: to_iso8601."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
