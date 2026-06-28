"""Composite setup helpers.

Most interesting claims require the system to be in a specific multi-step state
before the behavior under test can be exercised. These helpers encapsulate those
setup sequences so test bodies focus on assertions, not plumbing.

The test harness restarts the API server (and clears the database) before every
individual test, so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient) so a setup
failure surfaces as a clear "Setup failed" rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import TEST_USERS

ADMIN = TEST_USERS["gallery_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
SALES = TEST_USERS["sales_associate_headers"]


# ─── Tier 0: primitives ──────────────────────────────────────────────────────
def create_gallery(**overrides) -> dict:
    """Create a gallery (GalleryAdmin)."""
    resp = api_client.create_gallery(f.create_gallery_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_artist(gallery_id, **overrides) -> dict:
    """Register an ACTIVE artist under a gallery (GalleryAdmin)."""
    resp = api_client.create_artist(f.create_artist_payload(gallery_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_artwork(gallery_id, artist_id, **overrides) -> dict:
    """Consign a CONSIGNED artwork (GalleryAdmin)."""
    resp = api_client.create_artwork(
        f.create_artwork_payload(gallery_id, artist_id, **overrides), ADMIN)
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (GalleryAdmin)."""
    resp = api_client.set_clock(f.set_clock_payload(to_iso8601), ADMIN)
    return get_success_data(resp)


# ─── Tier 1: gallery + artist + artwork ──────────────────────────────────────
def setup_gallery_artist_artwork(gallery_overrides=None, artist_overrides=None,
                                 artwork_overrides=None):
    """Active gallery + ACTIVE artist + one CONSIGNED artwork.

    Returns (gallery, artist, artwork). The single most common base scenario.
    """
    gallery = create_gallery(**(gallery_overrides or {}))
    artist = create_artist(gallery["id"], **(artist_overrides or {}))
    artwork = create_artwork(gallery["id"], artist["id"], **(artwork_overrides or {}))
    return gallery, artist, artwork


# ─── Tier 2: exhibitions and the wall map ────────────────────────────────────
def create_exhibition(gallery_id, **overrides) -> dict:
    """Schedule a PLANNED exhibition (GalleryAdmin)."""
    resp = api_client.create_exhibition(
        f.create_exhibition_payload(gallery_id, **overrides), ADMIN)
    return get_success_data(resp)


def place_wall_slot(exhibition_id, artwork_id, position_index,
                    expected_exhibition_version, wall_label="N-1") -> dict:
    """Place an artwork on the wall map (Registrar)."""
    resp = api_client.place_wall_slot(
        exhibition_id,
        f.wall_slot_payload(artwork_id, position_index, expected_exhibition_version,
                            wall_label=wall_label),
        REGISTRAR)
    return get_success_data(resp)


def setup_exhibition_with_placed_artwork(wall_capacity=2, **gallery_overrides):
    """PLANNED exhibition with one PLACED wall slot for a fresh artwork.

    Returns (gallery, artist, artwork, exhibition, wall_slot).
    """
    gallery, artist, artwork = setup_gallery_artist_artwork(
        gallery_overrides=gallery_overrides or None)
    exhibition = create_exhibition(gallery["id"], wall_capacity=wall_capacity)
    wall_slot = place_wall_slot(
        exhibition["id"], artwork["id"], 0, exhibition["version"], wall_label="N-1")
    return gallery, artist, artwork, exhibition, wall_slot


# ─── Tier 3: sale lifecycle shortcuts ────────────────────────────────────────
def create_sale(gallery_id, artwork_id, **overrides) -> dict:
    """Open a RESERVED sale against an artwork (SalesAssociate)."""
    resp = api_client.create_sale(
        f.create_sale_payload(gallery_id, artwork_id, **overrides), SALES)
    return get_success_data(resp)


def setup_reserved_sale(sale_overrides=None, gallery_overrides=None,
                        artist_overrides=None, artwork_overrides=None):
    """Gallery + artist + artwork + a RESERVED sale.

    Returns (gallery, artist, artwork, sale).
    """
    gallery, artist, artwork = setup_gallery_artist_artwork(
        gallery_overrides=gallery_overrides, artist_overrides=artist_overrides,
        artwork_overrides=artwork_overrides)
    sale = create_sale(gallery["id"], artwork["id"], **(sale_overrides or {}))
    return gallery, artist, artwork, sale


def setup_invoiced_sale(sale_overrides=None, gallery_overrides=None,
                        artist_overrides=None, artwork_overrides=None):
    """A sale walked through to INVOICED.

    Returns (gallery, artist, artwork, sale) where `sale` is the post-invoice
    resource (so sale["version"] is the value to feed expected_sale_version).
    """
    gallery, artist, artwork, sale = setup_reserved_sale(
        sale_overrides=sale_overrides, gallery_overrides=gallery_overrides,
        artist_overrides=artist_overrides, artwork_overrides=artwork_overrides)
    invoiced = get_success_data(api_client.invoice_sale(sale["id"], SALES))
    return gallery, artist, artwork, invoiced


def setup_paid_in_full_sale(sale_overrides=None, gallery_overrides=None,
                            artist_overrides=None, artwork_overrides=None):
    """A sale invoiced and paid in full (amount_collected == buyer_total), ready
    to settle. Returns (gallery, artist, artwork, sale) where `sale` is the
    post-payment resource.
    """
    gallery, artist, artwork, invoiced = setup_invoiced_sale(
        sale_overrides=sale_overrides, gallery_overrides=gallery_overrides,
        artist_overrides=artist_overrides, artwork_overrides=artwork_overrides)
    paid = get_success_data(api_client.post_payment(
        invoiced["id"],
        f.payment_payload(invoiced["buyer_total_cents"], invoiced["version"]),
        SALES))
    return gallery, artist, artwork, paid


def setup_settled_sale(sale_overrides=None, gallery_overrides=None,
                       artist_overrides=None, artwork_overrides=None):
    """A sale walked all the way to SETTLED (artwork SOLD, artist ledger accrued).

    Returns (gallery, artist, artwork, sale) where `sale` is the settled resource.
    """
    gallery, artist, artwork, paid = setup_paid_in_full_sale(
        sale_overrides=sale_overrides, gallery_overrides=gallery_overrides,
        artist_overrides=artist_overrides, artwork_overrides=artwork_overrides)
    settled = get_success_data(api_client.settle_sale(paid["id"], SALES))
    return gallery, artist, artwork, settled


# ─── Tier 4: artist with an accrued payable balance ──────────────────────────
def setup_artist_with_payable(accrued_gross=400_000):
    """Artist with a single SETTLED tax-exempt sale, leaving a payable balance.

    With a NY (out-of-state) buyer the sale is tax-exempt, so net == gross and
    the final artist share at the default 50% split is accrued. Returns
    (gallery, artist, artwork, sale).
    """
    return setup_settled_sale(sale_overrides={
        "buyer_state_code": "NY", "gross_amount_cents": accrued_gross})


def complete_payout(payout_id) -> dict:
    resp = api_client.complete_payout(payout_id, ADMIN)
    return get_success_data(resp)


def create_payout(artist_id, requested_cents) -> dict:
    resp = api_client.create_payout(
        f.create_payout_payload(artist_id, requested_cents), ADMIN)
    return get_success_data(resp)


# ─── Tier 5: loans ───────────────────────────────────────────────────────────
def create_loan(artwork_id, coverage_value_cents, out_utc, due_utc,
                borrower_name="Borrower") -> dict:
    resp = api_client.create_loan(
        f.create_loan_payload(artwork_id, coverage_value_cents,
                              out_utc=out_utc, due_utc=due_utc,
                              borrower_name=borrower_name),
        REGISTRAR)
    return get_success_data(resp)


def setup_returned_loan(out_utc="2026-04-05T00:00:00Z",
                        due_utc="2026-05-05T00:00:00Z", insured_value=200_000):
    """Artwork with one RETURNED loan in its history (artwork back to CONSIGNED).

    Returns (gallery, artist, artwork, loan).
    """
    gallery, artist, artwork = setup_gallery_artist_artwork(
        artwork_overrides={"insured_value_cents": insured_value})
    loan = create_loan(artwork["id"], insured_value, out_utc, due_utc)
    get_success_data(api_client.return_loan(loan["id"], REGISTRAR))
    return gallery, artist, artwork, loan


# ─── Tier 6: leases ──────────────────────────────────────────────────────────
def create_lease(artwork_id, starts_utc="2026-04-01T00:00:00Z", **overrides) -> dict:
    resp = api_client.create_lease(
        f.create_lease_payload(artwork_id, starts_utc=starts_utc, **overrides), SALES)
    return get_success_data(resp)


def setup_active_lease(starts_utc="2026-04-01T00:00:00Z", list_price=1_000_000,
                       monthly_rate=50_000, term_months=12, purchase_credit_bps=2000):
    """ACTIVE lease against an artwork now ON_LOAN.

    Returns (gallery, artist, artwork, lease).
    """
    gallery, artist, artwork = setup_gallery_artist_artwork(
        artwork_overrides={"list_price_cents": list_price,
                           "insured_value_cents": list_price})
    lease = create_lease(artwork["id"], starts_utc=starts_utc,
                         monthly_rate_cents=monthly_rate, term_months=term_months,
                         purchase_credit_bps=purchase_credit_bps)
    return gallery, artist, artwork, lease


# ─── Tier 7: opening events and RSVPs ────────────────────────────────────────
def create_opening_event(exhibition_id, capacity=10, **overrides) -> dict:
    resp = api_client.create_opening_event(
        f.create_opening_event_payload(exhibition_id, capacity=capacity, **overrides),
        ADMIN)
    return get_success_data(resp)


def create_rsvp(opening_event_id, guest_name, party_size=None) -> dict:
    overrides = {}
    if party_size is not None:
        overrides["party_size"] = party_size
    resp = api_client.create_rsvp(
        f.create_rsvp_payload(opening_event_id, guest_name=guest_name, **overrides),
        SALES)
    return get_success_data(resp)


def setup_event_with_rsvp(capacity=10, party_size=2, guest_name="Guest"):
    """Exhibition + SCHEDULED opening event holding one CONFIRMED RSVP.

    Returns (gallery, exhibition, event, rsvp). Uses an exhibition run window
    that starts after the default clock so the RSVP deadline is in the future.
    """
    gallery = create_gallery()
    exhibition = create_exhibition(
        gallery["id"], wall_capacity=3,
        opens_utc="2026-05-01T00:00:00Z", closes_utc="2026-06-01T00:00:00Z")
    event = create_opening_event(
        exhibition["id"], capacity=capacity,
        starts_utc="2026-05-01T18:00:00Z", rsvp_deadline_utc="2026-04-30T00:00:00Z")
    rsvp = create_rsvp(event["id"], guest_name, party_size=party_size)
    return gallery, exhibition, event, rsvp


# ─── Tier 8: payment plans ───────────────────────────────────────────────────
def create_payment_plan(sale_id, installment_count=3, cadence_days=30,
                        first_due_utc="2026-05-01T00:00:00Z") -> dict:
    resp = api_client.create_payment_plan(
        f.create_payment_plan_payload(sale_id, installment_count=installment_count,
                                      cadence_days=cadence_days,
                                      first_due_utc=first_due_utc),
        SALES)
    return get_success_data(resp)


def setup_invoiced_sale_with_plan(gross=1_000_000, installment_count=3,
                                  cadence_days=30,
                                  first_due_utc="2026-05-01T00:00:00Z"):
    """An INVOICED, tax-exempt (NY buyer) sale with an ACTIVE payment plan.

    Returns (gallery, artist, artwork, sale, plan). `sale` is the post-invoice
    resource (sale["version"] is current for the next payment).
    """
    gallery, artist, artwork, invoiced = setup_invoiced_sale(
        sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": gross})
    plan = create_payment_plan(invoiced["id"], installment_count=installment_count,
                               cadence_days=cadence_days, first_due_utc=first_due_utc)
    return gallery, artist, artwork, invoiced, plan
