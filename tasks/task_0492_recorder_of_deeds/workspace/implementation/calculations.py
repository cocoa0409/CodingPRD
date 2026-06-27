"""Calculation rules (PRD §3.3, §3.4, §3.8; SCAFFOLD calculations table).

All money is integer cents. Percentage charges (transfer tax, records-management
surcharge) are rounded HALF UP to whole cents independently, then integer-summed
with the recording fee (PRD §2.7 pinned round-then-sum order)."""
from decimal import Decimal

from helpers import round_half_up

# --- recording_fee constants (PRD §3.3) ---
BASE_FIRST_PAGE_CENTS = 2500
ADDL_PAGE_CENTS = 500
INDEX_SURCHARGE_CENTS = 200
FREE_PARTY_ENTRIES = 4
DOCTYPE_SURCHARGE_CENTS = {
    "DEED": 1000,
    "MORTGAGE": 1500,
    "LIEN": 800,
    "UCC": 500,
    "PLAT": 3000,
    "OTHER": 0,
}

# --- transfer_tax / records-management constants (PRD §3.3) ---
TAX_RATE_BPS = 55          # 0.55%
RMS_BPS = 13               # 0.13% records-management surcharge
EXEMPT_THRESHOLD_CENTS = 10000  # consideration <= $100.00 is exempt (boundary: <=)

# --- examination margin (PRD §3.3) ---
MIN_TOP_MARGIN_INCHES = 3.0  # boundary: >= (exactly 3.0 passes)

# --- copy/search fee (PRD §3.8) ---
CERTIFIED_COPY_FEE_CENTS = 1500
NAME_SEARCH_FEE_CENTS = 800

# --- lien / UCC (PRD §3.7) ---
LIEN_LAPSE_YEARS = 5
CONTINUATION_WINDOW_DAYS = 180
TAX_LIEN_GRACE_DAYS = 30


def recording_fee_cents(verified_page_count, doc_type, party_entry_count):
    """page_fee + index_fee + doctype_fee, all integer cents, no rounding
    (PRD §3.3 recording fee)."""
    page_fee = BASE_FIRST_PAGE_CENTS + ADDL_PAGE_CENTS * max(0, verified_page_count - 1)
    index_fee = INDEX_SURCHARGE_CENTS * max(0, party_entry_count - FREE_PARTY_ENTRIES)
    doctype_fee = DOCTYPE_SURCHARGE_CENTS[doc_type]
    return page_fee + index_fee + doctype_fee


def transfer_tax_cents(consideration_cents):
    """0 if consideration <= exempt threshold, else round_half_up(consideration *
    55bps / 10000) (PRD §3.3 transfer tax)."""
    if consideration_cents <= EXEMPT_THRESHOLD_CENTS:
        return 0
    return round_half_up(Decimal(consideration_cents) * Decimal(TAX_RATE_BPS) / Decimal(10000))


def records_mgmt_cents(consideration_cents):
    """0 if consideration <= exempt threshold, else round_half_up(consideration *
    13bps / 10000) (PRD §3.3 records-management surcharge)."""
    if consideration_cents <= EXEMPT_THRESHOLD_CENTS:
        return 0
    return round_half_up(Decimal(consideration_cents) * Decimal(RMS_BPS) / Decimal(10000))


def assessment_components(verified_page_count, doc_type, party_entry_count,
                          verified_consideration_cents):
    """Compute the three component fees and the total with the pinned
    round-then-sum order (PRD §2.7, §3.3)."""
    rec_fee = recording_fee_cents(verified_page_count, doc_type, party_entry_count)
    tax = transfer_tax_cents(verified_consideration_cents)
    rms = records_mgmt_cents(verified_consideration_cents)
    total = rec_fee + tax + rms
    return rec_fee, tax, rms, total


def copy_search_fee_cents(request_type):
    """Flat copy/search fee (PRD §3.8)."""
    if request_type == "CERTIFIED_COPY":
        return CERTIFIED_COPY_FEE_CENTS
    return NAME_SEARCH_FEE_CENTS
