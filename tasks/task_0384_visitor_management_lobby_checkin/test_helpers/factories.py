"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
  - Site: name, badge_total required; timezone optional (defaults UTC).
  - Floor: site_id, label, capacity required.
  - Host: site_id, full_name, email required; department optional (defaults FACILITIES).
  - WatchlistEntry: site_id, match_type, match_value_normalized required;
    severity optional (defaults REVIEW), active optional (defaults true).
  - MeetingRoom: floor_id, name, seats required.
  - ParkingSpace: site_id, bay_label required.
  - Visit: site_id, host_id, floor_id, visitor_full_name, visitor_company,
    scheduled_start, scheduled_end required; room_id, parking_space_id,
    contractor_pass_id, id_scanned optional (id_scanned defaults false).
  - Agreement: visit_id, document_kind, document_version required.
  - ContractorPass: host_id, contractor_name, contractor_company,
    access_valid_from, access_valid_until required.
  - DeliveryLog: host_id, carrier, parcel_fees_cents required.
  - EvacuationEvent: floor_id, triggered_reason required.
"""

DEFAULT_START = "2026-06-16T09:00:00Z"
DEFAULT_END = "2026-06-16T11:00:00Z"


def create_site_payload(**overrides) -> dict:
    defaults = {"name": "HQ", "badge_total": 5}
    defaults.update(overrides)
    return defaults


def create_floor_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "label": "L3", "capacity": 5}
    defaults.update(overrides)
    return defaults


def create_host_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "full_name": "Dana Host", "email": "dana@x.com"}
    defaults.update(overrides)
    return defaults


def create_watchlist_entry_payload(site_id, match_type, match_value_normalized, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "match_type": match_type,
        "match_value_normalized": match_value_normalized,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_room_payload(floor_id, **overrides) -> dict:
    defaults = {"floor_id": floor_id, "name": "Room 1", "seats": 6}
    defaults.update(overrides)
    return defaults


def create_parking_space_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "bay_label": "P12"}
    defaults.update(overrides)
    return defaults


def create_visit_payload(site_id, host_id, floor_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "host_id": host_id,
        "floor_id": floor_id,
        "visitor_full_name": "Test Visitor",
        "visitor_company": "TestCo",
        "scheduled_start": DEFAULT_START,
        "scheduled_end": DEFAULT_END,
        "id_scanned": True,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(visit_id, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
        "document_kind": "NDA",
        "document_version": "NDA-v3",
    }
    defaults.update(overrides)
    return defaults


def create_contractor_pass_payload(host_id, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "contractor_name": "Pat Builder",
        "contractor_company": "BuildCo",
        "access_valid_from": "2026-06-01T00:00:00Z",
        "access_valid_until": "2026-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(host_id, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "carrier": "FEDEX",
        "parcel_fees_cents": [100],
    }
    defaults.update(overrides)
    return defaults


def create_evacuation_event_payload(floor_id, **overrides) -> dict:
    defaults = {"floor_id": floor_id, "triggered_reason": "FIRE_DRILL"}
    defaults.update(overrides)
    return defaults
