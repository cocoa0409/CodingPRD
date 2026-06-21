"""Payload factories — one per entity, input fields only.

HTS chapter cheat-sheet (first two digits of hts_code select the duty rate):
  61/62 apparel  -> 1650 bps    e.g. 6109100012, 6203420000
  84/85 machinery-> 250 bps     e.g. 8501100000
  other  general -> 500 bps     e.g. 9403600080 (ch94), 2106909998 (ch21, FDA goods)
"""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_importer_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Imports",
        "ior_number": _uniq("IOR"),
        "owner_user_id": "imp-user-1",
    }
    defaults.update(overrides)
    return defaults


def create_bond_payload(importer_id: str, **overrides) -> dict:
    defaults = {
        "importer_id": importer_id,
        "bond_type": "CONTINUOUS",
        "limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_isf_payload(importer_id: str, **overrides) -> dict:
    defaults = {
        "importer_id": importer_id,
        "bill_of_lading": _uniq("BOL"),
        "vessel_eta": "2026-06-10T00:00:00Z",
        "data_element_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(importer_id: str, bond_id: str, **overrides) -> dict:
    defaults = {
        "importer_id": importer_id,
        "bond_id": bond_id,
        "entry_type": "CONSUMPTION_01",
        "country_of_origin": "CN",
        "entry_date": "2026-06-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "hts_code": "9403600080",  # ch94, general 500 bps
        "customs_value_cents": 1_000_000,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pga_review_payload(entry_id: str, agency: str = "FDA", **overrides) -> dict:
    defaults = {"entry_id": entry_id, "agency": agency}
    defaults.update(overrides)
    return defaults


def create_exam_slot_payload(entry_id: str, **overrides) -> dict:
    defaults = {
        "station_code": "CES_LAX",
        "entry_id": entry_id,
        "window_start": "2026-06-06T10:00:00Z",
        "window_end": "2026-06-06T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(importer_id: str, **overrides) -> dict:
    defaults = {"importer_id": importer_id, "period_month": "2026-06"}
    defaults.update(overrides)
    return defaults


def create_psc_payload(
    entry_id: str, expected_entry_version: int, **overrides
) -> dict:
    defaults = {
        "entry_id": entry_id,
        "filing_kind": "PSC",
        "corrected_value_delta_cents": 200_000,
        "expected_entry_version": expected_entry_version,
    }
    defaults.update(overrides)
    return defaults
