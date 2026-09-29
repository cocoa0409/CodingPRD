"""Composite setup helpers.

Every test starts against an empty database, so every precondition has to be
built out of PRD-declared endpoints.  These helpers assemble the chains that
more than one test needs.  They use ``get_success_data``, which accepts any 2xx
and raises a readable AssertionError naming the failing setup step.

Nothing here asserts business outcomes -- assertions belong in the tests.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import api_client
from .test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    CONTROLLER_HEADERS,
    distributor_rep_headers,
    sommelier_headers,
)

# --- Logical clock ------------------------------------------------------


def set_clock(to_iso8601, headers=None):
    """Move the logical clock. The endpoint answers 204 with no body."""
    response = api_client.set_clock(to_iso8601, headers or BEVERAGE_DIRECTOR_HEADERS)
    assert response.status_code == 204, (
        "clock set expected 204, got %s: %s" % (response.status_code, response.text))
    return response


# --- Reference data ----------------------------------------------------


def create_venue(**overrides):
    payload = f.venue_payload(**overrides)
    return get_success_data(api_client.create_venue(payload, BEVERAGE_DIRECTOR_HEADERS))


def create_wine(**overrides):
    payload = f.wine_payload(**overrides)
    return get_success_data(api_client.create_wine(payload, BEVERAGE_DIRECTOR_HEADERS))


def create_bin(venue, **overrides):
    venue_id = _id(venue)
    payload = f.cellar_bin_payload(**overrides)
    return get_success_data(
        api_client.create_cellar_bin(venue_id, payload, sommelier_headers(venue_id)))


def create_distributor(**overrides):
    payload = f.distributor_payload(**overrides)
    return get_success_data(
        api_client.create_distributor(payload, BEVERAGE_DIRECTOR_HEADERS))


def review_distributor(distributor, decision="CLEARED", **overrides):
    payload = f.compliance_review_payload(decision, **overrides)
    return get_success_data(
        api_client.create_compliance_review(_id(distributor), payload,
                                            COMPLIANCE_OFFICER_HEADERS))


def create_cleared_distributor(**overrides):
    """A distributor whose compliance_state has been moved to CLEARED."""
    distributor = create_distributor(**overrides)
    return review_distributor(distributor, "CLEARED")


# --- Inventory ---------------------------------------------------------


def create_lot(venue, wine, bin_=None, **overrides):
    """An InventoryLot posted directly by the venue's sommelier."""
    venue_id = _id(venue)
    if bin_ is None:
        bin_ = create_bin(venue_id)
    payload = f.inventory_lot_payload(venue_id, _id(wine), _id(bin_), **overrides)
    return get_success_data(
        api_client.create_inventory_lot(payload, sommelier_headers(venue_id)))


# --- Allocation --------------------------------------------------------


def create_offer(distributor, wine, **overrides):
    distributor_id = _id(distributor)
    payload = f.allocation_offer_payload(distributor_id, _id(wine), **overrides)
    return get_success_data(
        api_client.create_allocation_offer(payload,
                                           distributor_rep_headers(distributor_id)))


def setup_cleared_offer(wine=None, **overrides):
    """A CLEARED distributor plus an OPEN offer on a wine."""
    distributor = create_cleared_distributor()
    wine = wine or create_wine()
    offer = create_offer(distributor, wine, **overrides)
    return {"distributor": distributor, "wine": wine, "offer": offer}


def current_version(getter, entity_id):
    """Re-read an entity and return its current optimistic-concurrency version."""
    return get_success_data(getter(entity_id, BEVERAGE_DIRECTOR_HEADERS))["version"]


def file_claim(offer, venue, requested_bottles, expected_offer_version=None,
               **overrides):
    """File a claim, reading the offer's live version for the OCC guard."""
    offer_id = _id(offer)
    venue_id = _id(venue)
    if expected_offer_version is None:
        expected_offer_version = current_version(
            api_client.get_allocation_offer, offer_id)
    payload = f.allocation_claim_payload(venue_id, requested_bottles,
                                         expected_offer_version, **overrides)
    return get_success_data(
        api_client.create_allocation_claim(offer_id, payload,
                                          sommelier_headers(venue_id)))


def allocate(offer):
    return get_success_data(
        api_client.allocate_offer(_id(offer), BEVERAGE_DIRECTOR_HEADERS))


def receive_claim(claim, venue, bin_, received_at="2026-08-01T00:00:00Z"):
    venue_id = _id(venue)
    payload = f.receive_claim_payload(_id(bin_), received_at)
    return get_success_data(
        api_client.receive_claim(_id(claim), payload, sommelier_headers(venue_id)))


# --- Wine lists --------------------------------------------------------


def create_wine_list(venue, **overrides):
    venue_id = _id(venue)
    payload = f.wine_list_payload(**overrides)
    return get_success_data(
        api_client.create_wine_list(venue_id, payload, sommelier_headers(venue_id)))


def create_draft_version(wine_list, venue, **overrides):
    venue_id = _id(venue)
    payload = f.list_version_payload(**overrides)
    return get_success_data(
        api_client.create_list_version(_id(wine_list), payload,
                                       sommelier_headers(venue_id)))


def setup_draft_version(venue):
    """A WineList plus a DRAFT ListVersion for the given venue."""
    wine_list = create_wine_list(venue)
    version = create_draft_version(wine_list, venue)
    return {"wine_list": wine_list, "version": version}


def add_entry(version, wine, venue, sort_rank=1, **overrides):
    """Add a ListEntry, reading the version's live version for the OCC guard."""
    venue_id = _id(venue)
    version_id = _id(version)
    expected = overrides.pop("expected_list_version_version", None)
    if expected is None:
        expected = current_version(api_client.get_list_version, version_id)
    payload = f.list_entry_payload(_id(wine), expected, sort_rank, **overrides)
    return get_success_data(
        api_client.create_list_entry(version_id, payload,
                                     sommelier_headers(venue_id)))


def submit_version(version, venue):
    venue_id = _id(venue)
    return get_success_data(
        api_client.submit_list_version(_id(version), sommelier_headers(venue_id)))


def publish_version(version, venue):
    """Submit as the venue's sommelier then publish as the director, so the
    publisher's X-User-ID differs from the recorded submitter."""
    submit_version(version, venue)
    return get_success_data(
        api_client.publish_list_version(_id(version), BEVERAGE_DIRECTOR_HEADERS))


def _id(entity):
    """Accept either an entity dict or a bare id string."""
    if isinstance(entity, dict):
        return str(entity["id"])
    return str(entity)


# --- Published by-the-glass programme ----------------------------------


def setup_published_entry(venue=None, wine=None, by_the_glass=True,
                          pour_size_ml=125, bottles_received=6,
                          unit_cost_cents=None, received_at="2026-08-01T00:00:00Z",
                          entry_overrides=None, bin_overrides=None):
    """Venue + wine + bin + lot + wine list + PUBLISHED version + entry.

    Returns a dict of every object created, so a caller can reach any link of
    the chain.  The lot's ``unit_cost_cents`` defaults to the wine's
    ``reference_cost_cents`` unless overridden.
    """
    venue = venue or create_venue()
    wine = wine or create_wine()
    bin_ = create_bin(venue, **(bin_overrides or {}))
    lot = create_lot(venue, wine, bin_,
                     bottles_received=bottles_received,
                     unit_cost_cents=(unit_cost_cents
                                      if unit_cost_cents is not None
                                      else wine["reference_cost_cents"]),
                     received_at=received_at)
    wine_list = create_wine_list(venue)
    version = create_draft_version(wine_list, venue)
    overrides = dict(entry_overrides or {})
    if by_the_glass:
        overrides.setdefault("by_the_glass", True)
        overrides.setdefault("pour_size_ml", pour_size_ml)
    entry = add_entry(version, wine, venue, **overrides)
    published = publish_version(version, venue)
    return {
        "venue": venue,
        "wine": wine,
        "bin": bin_,
        "lot": lot,
        "wine_list": wine_list,
        "version": published,
        "entry": entry,
    }


def open_slot(venue, entry, lot, slot_index=1, preservation_method="ARGON",
              **overrides):
    venue_id = _id(venue)
    payload = f.btg_slot_payload(venue_id, _id(entry), _id(lot), slot_index,
                                 preservation_method, **overrides)
    return get_success_data(
        api_client.create_btg_slot(payload, sommelier_headers(venue_id)))


def close_slot(slot, venue, pours_sold, staff_education_pours=None):
    venue_id = _id(venue)
    overrides = {}
    if staff_education_pours is not None:
        overrides["staff_education_pours"] = staff_education_pours
    payload = f.close_slot_payload(pours_sold, **overrides)
    return get_success_data(
        api_client.close_btg_slot(_id(slot), payload, sommelier_headers(venue_id)))


# --- Spoilage write-offs -----------------------------------------------


def submit_write_off(venue, lot, bottles=1, reason_code="CORKED", **overrides):
    """Submitted by the venue's sommelier, so a Controller may approve it."""
    venue_id = _id(venue)
    payload = f.write_off_payload(venue_id, _id(lot), bottles, reason_code,
                                  **overrides)
    return get_success_data(
        api_client.create_spoilage_write_off(payload, sommelier_headers(venue_id)))


def approve_write_off(write_off):
    return get_success_data(
        api_client.approve_write_off(_id(write_off), CONTROLLER_HEADERS))


def reverse_write_off(write_off, note="Bottle recovered from the cellar."):
    return get_success_data(
        api_client.reverse_write_off(_id(write_off), f.note_payload(note),
                                     CONTROLLER_HEADERS))


# --- Wine dinner events ------------------------------------------------


def create_event(venue, version, pour_plan, **overrides):
    venue_id = _id(venue)
    payload = f.wine_dinner_event_payload(venue_id, _id(version), pour_plan,
                                          **overrides)
    return get_success_data(
        api_client.create_wine_dinner_event(payload, sommelier_headers(venue_id)))


def price_event(event, venue):
    venue_id = _id(venue)
    return get_success_data(
        api_client.price_event(_id(event), sommelier_headers(venue_id)))


def confirm_event(event):
    return get_success_data(
        api_client.confirm_event(_id(event), BEVERAGE_DIRECTOR_HEADERS))


def settle_event(event):
    return get_success_data(
        api_client.settle_event(_id(event), CONTROLLER_HEADERS))


def void_event_settlement(event, note="Settlement posted against the wrong period."):
    return get_success_data(
        api_client.void_event_settlement(_id(event), f.note_payload(note),
                                         CONTROLLER_HEADERS))


# --- Cost governance ---------------------------------------------------


def run_pour_cost(venue, period_start, period_end):
    """Run the venue's pour-cost variance and return the updated venue."""
    payload = f.pour_cost_run_payload(period_start, period_end)
    return get_success_data(
        api_client.create_pour_cost_run(_id(venue), payload,
                                        BEVERAGE_DIRECTOR_HEADERS))


def pour_cost_report(venue, period_start, period_end):
    return get_success_data(
        api_client.get_pour_cost_report(
            _id(venue), BEVERAGE_DIRECTOR_HEADERS,
            params={"period_start": period_start, "period_end": period_end}))


def open_investigations(venue):
    """Every VarianceInvestigation the venue currently has, newest last."""
    response = api_client.list_variance_investigations(
        CONTROLLER_HEADERS, params={"venue_id": _id(venue), "limit": 100})
    data, _meta = validate_paginated(response)
    # PRD 2.3: list results are ordered by `created_at` ascending and
    # "Records are never ordered by `id`" — keep the server's order.
    return data


def escalate_investigation(investigation, note="Gap unexplained after review."):
    return get_success_data(
        api_client.escalate_investigation(_id(investigation), f.note_payload(note),
                                          CONTROLLER_HEADERS))


def resolve_investigation(investigation, resolution="EXPLAINED",
                          resolution_note="Reviewed with the team."):
    payload = f.resolve_investigation_payload(resolution, resolution_note)
    return get_success_data(
        api_client.resolve_investigation(_id(investigation), payload,
                                         CONTROLLER_HEADERS))


def get_venue(venue):
    return get_success_data(
        api_client.get_venue(_id(venue), BEVERAGE_DIRECTOR_HEADERS))


def force_frozen_venue(venue=None, period_start="2026-09-01T00:00:00Z",
                       period_end="2026-09-02T00:00:00Z"):
    """Drive a venue's program_posture to FROZEN through the declared path.

    Sells one glass and pours five staff-education glasses out of the same
    bottle, so the ledger carries a full bottle of cost against a single
    glass of revenue.  The actual pour cost then sits far above the
    theoretical, the run opens an investigation, and the investigation is
    escalated -- which the PRD says necessarily freezes the venue.

    Returns the venue as it stands after the freeze.
    """
    venue = venue or create_venue()
    chain = setup_published_entry(venue=venue, pour_size_ml=100)
    set_clock("2026-09-01T12:00:00Z")
    slot = open_slot(venue, chain["entry"], chain["lot"])
    close_slot(slot, venue, pours_sold=1, staff_education_pours=5)
    run_pour_cost(venue, period_start, period_end)
    investigations = open_investigations(venue)
    assert investigations, (
        "expected the pour-cost run to open a variance investigation")
    active = [row for row in investigations if row["state"] == "OPEN"]
    if active:
        escalate_investigation(active[-1])
    updated = get_venue(venue)
    assert updated["program_posture"] == "FROZEN", (
        "setup expected a FROZEN venue, got %r" % (updated["program_posture"],))
    updated["_chain"] = chain
    return updated
