"""Payload factories.

Each builder returns a minimal-but-valid request body for one endpoint and
lets the caller override any field with a keyword argument.  Passing
``field=None`` explicitly sends JSON null; omitting the field omits the key.
"""
import itertools

from .constants import WINE_CATEGORIES

_counter = itertools.count(1)


def unique_suffix():
    """A short monotonically increasing token for unique codes and names."""
    return "%04d" % next(_counter)


def _merge(base, overrides):
    """Overlay ``overrides`` onto ``base``; a value of ``_OMIT`` drops the key."""
    out = dict(base)
    for key, value in overrides.items():
        if value is OMIT:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class _Omit:
    def __repr__(self):
        return "<OMIT>"


OMIT = _Omit()


def cogs_targets(pct=30.0, **per_category):
    """A complete ``cogs_target_pct_by_category`` object.

    All six WINE_CATEGORIES keys are always present, defaulting to ``pct``.
    """
    targets = {category: pct for category in WINE_CATEGORIES}
    targets.update(per_category)
    return targets


def venue_payload(**overrides):
    suffix = unique_suffix()
    base = {
        "name": "Cellar House %s" % suffix,
        "venue_code": "VN%s" % suffix,
        "cogs_target_pct_by_category": cogs_targets(),
    }
    return _merge(base, overrides)


def cellar_bin_payload(**overrides):
    base = {
        "bin_code": "BIN%s" % unique_suffix(),
        "zone": "CELLAR",
        "capacity_bottles": 48,
    }
    return _merge(base, overrides)


def distributor_payload(**overrides):
    suffix = unique_suffix()
    base = {
        "name": "Meridian Selections %s" % suffix,
        "license_number": "LIC-%s" % suffix,
    }
    return _merge(base, overrides)


def compliance_review_payload(decision="CLEARED", **overrides):
    base = {"decision": decision}
    return _merge(base, overrides)


def wine_payload(**overrides):
    suffix = unique_suffix()
    base = {
        "producer": "Domaine %s" % suffix,
        "cuvee": "Cuvee %s" % suffix,
        "vintage_year": 2019,
        "category": "RED",
        "reference_cost_cents": 4000,
    }
    return _merge(base, overrides)


def allocation_offer_payload(distributor_id, wine_id, **overrides):
    base = {
        "distributor_id": str(distributor_id),
        "wine_id": str(wine_id),
        "offered_bottles": 12,
        "unit_cost_cents": 4000,
        "response_deadline": "2026-12-01T00:00:00Z",
    }
    return _merge(base, overrides)


def allocation_claim_payload(venue_id, requested_bottles, expected_offer_version,
                             **overrides):
    base = {
        "venue_id": str(venue_id),
        "requested_bottles": requested_bottles,
        "expected_offer_version": expected_offer_version,
    }
    return _merge(base, overrides)


def receive_claim_payload(bin_id, received_at, **overrides):
    base = {"bin_id": str(bin_id), "received_at": received_at}
    return _merge(base, overrides)


def inventory_lot_payload(venue_id, wine_id, bin_id, **overrides):
    base = {
        "venue_id": str(venue_id),
        "wine_id": str(wine_id),
        "bin_id": str(bin_id),
        "bottles_received": 6,
        "unit_cost_cents": 4000,
        "received_at": "2026-08-01T00:00:00Z",
    }
    return _merge(base, overrides)


def wine_list_payload(**overrides):
    base = {"name": "Main List %s" % unique_suffix()}
    return _merge(base, overrides)


def list_version_payload(**overrides):
    base = {}
    return _merge(base, overrides)


def list_entry_payload(wine_id, expected_list_version_version, sort_rank=1,
                       **overrides):
    base = {
        "wine_id": str(wine_id),
        "sort_rank": sort_rank,
        "expected_list_version_version": expected_list_version_version,
    }
    return _merge(base, overrides)


def btg_slot_payload(venue_id, list_entry_id, lot_id, slot_index=1,
                     preservation_method="ARGON", **overrides):
    base = {
        "venue_id": str(venue_id),
        "list_entry_id": str(list_entry_id),
        "lot_id": str(lot_id),
        "slot_index": slot_index,
        "preservation_method": preservation_method,
    }
    return _merge(base, overrides)


def close_slot_payload(pours_sold, **overrides):
    base = {"pours_sold": pours_sold}
    return _merge(base, overrides)


def write_off_payload(venue_id, lot_id, bottles=1, reason_code="CORKED",
                      **overrides):
    base = {
        "venue_id": str(venue_id),
        "lot_id": str(lot_id),
        "bottles": bottles,
        "reason_code": reason_code,
        "narrative": "Bottle failed at service.",
    }
    return _merge(base, overrides)


def note_payload(note="Recorded for audit.", **overrides):
    base = {"note": note}
    return _merge(base, overrides)


def pour_plan_line(list_entry_id, pours_per_seat=1):
    return {"list_entry_id": str(list_entry_id), "pours_per_seat": pours_per_seat}


def wine_dinner_event_payload(venue_id, list_version_id, pour_plan,
                              **overrides):
    base = {
        "venue_id": str(venue_id),
        "list_version_id": str(list_version_id),
        "name": "Wine Dinner %s" % unique_suffix(),
        "starts_at": "2026-09-10T18:00:00Z",
        "ends_at": "2026-09-10T22:00:00Z",
        "seat_count": 40,
        "pour_plan": pour_plan,
    }
    return _merge(base, overrides)


def pour_cost_run_payload(period_start, period_end, **overrides):
    base = {"period_start": period_start, "period_end": period_end}
    return _merge(base, overrides)


def resolve_investigation_payload(resolution="EXPLAINED",
                                  resolution_note="Reviewed with the team.",
                                  **overrides):
    base = {"resolution": resolution, "resolution_note": resolution_note}
    return _merge(base, overrides)


def corkage_payload(byo_bottle_count=1, bottles_purchased_from_list=0,
                    party_size=4, byo_categories=None, **overrides):
    base = {
        "byo_bottle_count": byo_bottle_count,
        "bottles_purchased_from_list": bottles_purchased_from_list,
        "party_size": party_size,
        "byo_categories": list(byo_categories or ["RED"]),
    }
    return _merge(base, overrides)
