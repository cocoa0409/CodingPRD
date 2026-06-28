"""Composite setup helpers for multi-step iBuyer Home Offer test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading (PRD §2.1): the Seller role is entity-backed — X-User-ID is
the acting Seller's id, and ownership of a property/offer/transaction is checked
against the underlying Property.seller_id. Every ownership-gated Seller call
(accept, withdraw, schedule-close, cancel) therefore uses
make_seller_headers(<the real Seller.id>). PricingAnalyst and OperationsAdmin are
opaque operators; the shared TEST_USERS constants are fine for them.

The logical clock starts at 2026-01-01T00:00:00Z (PRD §2.7). Fixtures that need a
known issuance instant set the clock explicitly via set_clock(). The canonical
"standard" property uses comp_median_value=500000, market_trend_pct=0.02, so
avm_value == 510000.00.
"""
import datetime
import uuid
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_seller_payload,
    create_property_payload,
    issue_offer_payload,
    create_repair_line_item_payload,
    finalize_assessment_payload,
    schedule_close_payload,
    retrade_payload,
    create_resale_payload,
)
from .test_users import TEST_USERS, make_seller_headers
from .constants import INSPECTION_LEAD_DAYS

# Standard clock instant most setups run against (issuance at 2026-03-01).
STANDARD_CLOCK = "2026-03-01T00:00:00Z"
# Standard in-window close date (14 days out from STANDARD_CLOCK).
STANDARD_CLOSE_DATE = "2026-03-15T00:00:00Z"


def _iso(dt: datetime.datetime) -> str:
    """Serialize an aware UTC datetime as an ISO-8601 instant with a trailing Z."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _inspection_window_open(close_date_iso: str) -> str:
    """The instant the inspection window opens: close_date minus INSPECTION_LEAD_DAYS
    (PRD §3.6: "The inspection window opens 3 days before the close date, so starting
    the inspection requires that the logical clock has reached at least `close_date`
    minus 3 days")."""
    s = close_date_iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return _iso(dt - datetime.timedelta(days=INSPECTION_LEAD_DAYS))

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]


def _unique_email(prefix: str = "s") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


# --- Tier 0: Logical clock --------------------------------------------------

def set_clock(iso8601: str) -> None:
    """Advance the server's logical clock to an absolute UTC instant (OperationsAdmin).
    The clock endpoint is auth-exempt (PRD §2.7) but we pass admin headers anyway."""
    api_client.set_clock(iso8601, _ADMIN)


# --- Tier 1: Single-entity creation ----------------------------------------

def create_seller(**overrides) -> dict:
    """Register a Seller (homeowner). Email is randomized for uniqueness unless
    overridden."""
    overrides.setdefault("email", _unique_email())
    payload = create_seller_payload(**overrides)
    return get_success_data(api_client.create_seller(payload, _ADMIN))


def create_property(seller_id: str, **overrides) -> dict:
    """Register a property and compute its AVM (PricingAnalyst). Defaults to the
    standard comp_median_value=500000, market_trend_pct=0.02 (avm=510000)."""
    payload = create_property_payload(seller_id, **overrides)
    return get_success_data(api_client.create_property(payload, _ANALYST))


def issue_offer(property_id: str, **overrides) -> dict:
    """Issue the first offer for a property (PricingAnalyst). service_fee_pct
    defaults to 0.05."""
    payload = issue_offer_payload(**overrides)
    return get_success_data(api_client.issue_offer(property_id, payload, _ANALYST))


# --- Tier 2: Property under offer -------------------------------------------

def setup_property_under_offer(
    set_standard_clock: bool = True,
    property_overrides: dict = None,
    offer_overrides: dict = None,
):
    """Seller + standard property (avm=510000) + first issued offer.

    Returns (seller, prop, offer). The property is UNDER_OFFER with one ISSUED
    active offer. Sets the clock to STANDARD_CLOCK first unless disabled (some
    clock-default tests must leave the clock untouched).
    """
    if set_standard_clock:
        set_clock(STANDARD_CLOCK)
    seller = create_seller()
    prop = create_property(seller["id"], **(property_overrides or {}))
    offer = issue_offer(prop["id"], **(offer_overrides or {}))
    return seller, prop, offer


def reissue_offer(property_id: str, expected_property_version: int, **overrides) -> dict:
    """Re-issue an offer carrying the OCC version token (PricingAnalyst)."""
    payload = issue_offer_payload(
        expected_property_version=expected_property_version, **overrides
    )
    return get_success_data(api_client.issue_offer(property_id, payload, _ANALYST))


def get_property_version(property_id: str) -> int:
    return get_success_data(api_client.get_property(property_id, _ANALYST))["version"]


# --- Tier 3: Accepted offer -> transaction ----------------------------------

def accept_offer(offer_id: str, seller_id: str) -> dict:
    """Seller accepts the offer (ownership-gated). Returns the spawned Transaction."""
    return get_success_data(
        api_client.accept_offer(offer_id, {}, make_seller_headers(seller_id))
    )


def get_assessment_for_offer(offer_id: str) -> dict:
    """Fetch the (single) Assessment created on accept; returns the assessment dict."""
    data = get_success_data(api_client.get_offer_assessment(offer_id, _ADMIN))
    # GET /offers/{id}/assessment returns an array of length 0 or 1.
    assert isinstance(data, list) and len(data) >= 1, "expected one assessment"
    return data[0]


def setup_accepted_transaction(
    set_standard_clock: bool = True,
    property_overrides: dict = None,
    offer_overrides: dict = None,
):
    """Property under offer, then accepted -> Transaction(PENDING_ASSESSMENT) +
    Assessment(DRAFT).

    Returns (seller, prop, offer, txn, assessment).
    """
    seller, prop, offer = setup_property_under_offer(
        set_standard_clock=set_standard_clock,
        property_overrides=property_overrides,
        offer_overrides=offer_overrides,
    )
    txn = accept_offer(offer["id"], seller["id"])
    assessment = get_assessment_for_offer(offer["id"])
    return seller, prop, offer, txn, assessment


# --- Tier 4: Repair line items + finalized assessment -----------------------

# Canonical three-line repair set (round-per-line-then-sum -> 6634.57).
STANDARD_REPAIR_LINES = [
    ("ROOF", 1234.567),
    ("HVAC", 899.991),
    ("FOUNDATION", 4500.005),
]


def add_repair_line_items(assessment_id: str, lines):
    """Attach a list of (category, estimate_amount) repair line items (OperationsAdmin).
    Returns the list of created line-item dicts."""
    created = []
    for category, amount in lines:
        payload = create_repair_line_item_payload(category, amount)
        created.append(
            get_success_data(
                api_client.create_repair_line_item(assessment_id, payload, _ADMIN)
            )
        )
    return created


def finalize_assessment(
    assessment_id: str,
    roof_condition="GOOD",
    hvac_condition="GOOD",
    foundation_condition="GOOD",
) -> dict:
    """Finalize an assessment (OperationsAdmin); computes condition_score."""
    payload = finalize_assessment_payload(
        roof_condition=roof_condition,
        hvac_condition=hvac_condition,
        foundation_condition=foundation_condition,
    )
    return get_success_data(
        api_client.finalize_assessment(assessment_id, payload, _ADMIN)
    )


def setup_finalized_assessment(
    repair_lines=None,
    roof_condition="GOOD",
    hvac_condition="GOOD",
    foundation_condition="GOOD",
    property_overrides: dict = None,
    offer_overrides: dict = None,
):
    """Accepted transaction with optional repair line items, then assessment FINALIZED.

    Returns (seller, prop, offer, txn, assessment, line_items).
    """
    seller, prop, offer, txn, assessment = setup_accepted_transaction(
        property_overrides=property_overrides, offer_overrides=offer_overrides
    )
    line_items = []
    if repair_lines:
        line_items = add_repair_line_items(assessment["id"], repair_lines)
    finalized = finalize_assessment(
        assessment["id"],
        roof_condition=roof_condition,
        hvac_condition=hvac_condition,
        foundation_condition=foundation_condition,
    )
    return seller, prop, offer, txn, finalized, line_items


# --- Tier 5: Scheduled close ------------------------------------------------

def schedule_close(
    transaction_id: str,
    seller_id: str,
    close_date: str = STANDARD_CLOSE_DATE,
    leaseback_days: int = 0,
    final_concession: float = 0.0,
) -> dict:
    """Seller schedules the close (ownership-gated). Returns the SCHEDULED transaction."""
    payload = schedule_close_payload(
        close_date,
        leaseback_days=leaseback_days,
        final_concession=final_concession,
    )
    return get_success_data(
        api_client.schedule_close(
            transaction_id, payload, make_seller_headers(seller_id)
        )
    )


def setup_scheduled_transaction(
    repair_lines=None,
    leaseback_days: int = 0,
    final_concession: float = 0.0,
    close_date: str = STANDARD_CLOSE_DATE,
    roof_condition="GOOD",
    hvac_condition="GOOD",
    foundation_condition="GOOD",
    property_overrides: dict = None,
    offer_overrides: dict = None,
):
    """Full chain through SCHEDULED: accept -> [repairs] -> finalize -> schedule-close.

    Returns (seller, prop, offer, txn, assessment, line_items).
    """
    seller, prop, offer, txn, assessment, line_items = setup_finalized_assessment(
        repair_lines=repair_lines,
        roof_condition=roof_condition,
        hvac_condition=hvac_condition,
        foundation_condition=foundation_condition,
        property_overrides=property_overrides,
        offer_overrides=offer_overrides,
    )
    txn = schedule_close(
        txn["id"],
        seller["id"],
        close_date=close_date,
        leaseback_days=leaseback_days,
        final_concession=final_concession,
    )
    return seller, prop, offer, txn, assessment, line_items


# --- Tier 6: Inspection-phase transaction -----------------------------------

def start_inspection(transaction_id: str) -> dict:
    """Open the inspection window (OperationsAdmin). Returns INSPECTION transaction."""
    return get_success_data(
        api_client.start_inspection(transaction_id, {}, _ADMIN)
    )


def setup_inspection_transaction(
    repair_lines=None,
    leaseback_days: int = 0,
    final_concession: float = 0.0,
    close_date: str = STANDARD_CLOSE_DATE,
    roof_condition="GOOD",
    hvac_condition="GOOD",
    foundation_condition="GOOD",
    property_overrides: dict = None,
    offer_overrides: dict = None,
):
    """Full chain through INSPECTION (no re-trade yet).

    Returns (seller, prop, offer, txn, assessment, line_items).
    """
    seller, prop, offer, txn, assessment, line_items = setup_scheduled_transaction(
        repair_lines=repair_lines,
        leaseback_days=leaseback_days,
        final_concession=final_concession,
        close_date=close_date,
        roof_condition=roof_condition,
        hvac_condition=hvac_condition,
        foundation_condition=foundation_condition,
        property_overrides=property_overrides,
        offer_overrides=offer_overrides,
    )
    # The schedule-close window check has already passed at STANDARD_CLOCK; now advance
    # the logical clock to the instant the inspection window opens (close_date minus
    # INSPECTION_LEAD_DAYS) so start-inspection's lower-bound gate (PRD §3.6) is met.
    set_clock(_inspection_window_open(close_date))
    txn = start_inspection(txn["id"])
    return seller, prop, offer, txn, assessment, line_items


def apply_retrade(transaction_id: str, retrade_amount: float, **overrides) -> dict:
    """Apply an inspection re-trade (PricingAnalyst). Returns updated transaction."""
    payload = retrade_payload(retrade_amount, **overrides)
    return get_success_data(api_client.retrade(transaction_id, payload, _ANALYST))


def cancel_transaction(transaction_id: str, seller_id: str, **overrides) -> dict:
    """Seller cancels the transaction (ownership-gated). Returns CANCELLED transaction."""
    payload = dict(overrides)
    return get_success_data(
        api_client.cancel_transaction(
            transaction_id, payload, make_seller_headers(seller_id)
        )
    )


# --- Tier 7: Closed transaction + resale ------------------------------------

def close_transaction(transaction_id: str) -> dict:
    """Close the transaction (OperationsAdmin). Returns CLOSED transaction."""
    return get_success_data(
        api_client.close_transaction(transaction_id, {}, _ADMIN)
    )


def setup_closed_transaction(
    repair_lines=None,
    leaseback_days: int = 0,
    final_concession: float = 0.0,
    close_date: str = STANDARD_CLOSE_DATE,
    roof_condition="GOOD",
    hvac_condition="GOOD",
    foundation_condition="GOOD",
    property_overrides: dict = None,
    offer_overrides: dict = None,
):
    """Full happy path through CLOSED (no re-trade).

    Returns (seller, prop, offer, txn, assessment, line_items).
    """
    seller, prop, offer, txn, assessment, line_items = setup_inspection_transaction(
        repair_lines=repair_lines,
        leaseback_days=leaseback_days,
        final_concession=final_concession,
        close_date=close_date,
        roof_condition=roof_condition,
        hvac_condition=hvac_condition,
        foundation_condition=foundation_condition,
        property_overrides=property_overrides,
        offer_overrides=offer_overrides,
    )
    txn = close_transaction(txn["id"])
    return seller, prop, offer, txn, assessment, line_items


def list_resale(transaction_id: str, list_price: float = 560000, **overrides) -> dict:
    """List a CLOSED transaction's property for resale (PricingAnalyst)."""
    payload = create_resale_payload(transaction_id, list_price, **overrides)
    return get_success_data(api_client.create_resale(payload, _ANALYST))


def sell_resale(resale_id: str, sold_price: float) -> dict:
    """Record a resale sale (OperationsAdmin). Returns SOLD resale."""
    return get_success_data(
        api_client.sell_resale(resale_id, {"sold_price": sold_price}, _ADMIN)
    )
