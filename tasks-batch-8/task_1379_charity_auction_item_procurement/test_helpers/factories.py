"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import STANDARD_EVENT_CONFIG

_counter = itertools.count(1)


def _n():
    return next(_counter)


def create_gala_event_payload(**overrides) -> dict:
    defaults = dict(STANDARD_EVENT_CONFIG)
    defaults["name"] = f"Gala {_n()}"
    # Deep-copy the tiers so per-test overrides never mutate the module default.
    defaults["bid_increment_tiers"] = [dict(t) for t in
                                       STANDARD_EVENT_CONFIG[
                                           "bid_increment_tiers"]]
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Donor {n}",
        "email": f"donor{n}@example.org",
        "donor_type": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_bidder_payload(gala_event_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "gala_event_id": gala_event_id,
        "full_name": f"Bidder {n}",
        "email": f"bidder{n}@example.org",
        "paddle_no": n,
        "payment_method_on_file": True,
    }
    defaults.update(overrides)
    return defaults


def create_solicitation_payload(donor_id, gala_event_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "donor_id": donor_id,
        "gala_event_id": gala_event_id,
        "ask_description": f"Ask {n}",
        "ask_estimate_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def revise_solicitation_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "ask_description": f"Revised ask {n}",
        "ask_estimate_cents": 35000,
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(solicitation_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "solicitation_id": solicitation_id,
        "title": f"Item {n}",
        "description": f"Description {n}",
        "kind": "PHYSICAL",
    }
    defaults.update(overrides)
    return defaults


def submit_valuation_payload(fmv_cents, expected_item_version,
                             **overrides) -> dict:
    defaults = {
        "fmv_cents": fmv_cents,
        "fmv_source": "APPRAISAL",
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(**overrides) -> dict:
    defaults = {
        "starts_at": "2027-08-05T00:00:00Z",
        "ends_at": "2027-08-12T00:00:00Z",
        "label": "owner use",
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(gala_event_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "gala_event_id": gala_event_id,
        "title": f"Bundle {n}",
    }
    defaults.update(overrides)
    return defaults


def place_bid_payload(amount_cents, expected_bundle_version) -> dict:
    return {
        "amount_cents": amount_cents,
        "expected_bundle_version": expected_bundle_version,
    }


def create_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def redeem_certificate_payload(scheduled_start="2027-01-10T00:00:00Z",
                               scheduled_end="2027-01-12T00:00:00Z") -> dict:
    return {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
