"""AgencyBinding service."""

from db import store
from errors import raise_err
from clock import clock
from util import (
    get_str, get_enum, get_number, parse_iso8601, COUNTRY_RE,
)

AGENCY_KINDS = {"PUBLISHER", "LABEL", "CMO"}


def serialize(b: dict) -> dict:
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "rights_holder_id": b["rights_holder_id"],
        "agency_kind": b["agency_kind"],
        "agency_name": b["agency_name"],
        "territory": b["territory"],
        "commission_percent": float(b["commission_percent"]),
        "effective_from": b["effective_from"],
        "effective_until": b.get("effective_until"),
        "status": b["status"],
    }


def _validate_territory(t: str):
    if t == "WW":
        return
    if not (len(t) == 2 and t.isupper() and t.isalpha()):
        raise_err("ERR_VALIDATION", "territory must be 2 uppercase letters or 'WW'")


def create_agency_binding(body: dict) -> dict:
    rights_holder_id = get_str(body, "rights_holder_id")
    agency_kind = get_enum(body, "agency_kind", AGENCY_KINDS)
    agency_name = get_str(body, "agency_name", min_len=1, max_len=200)
    territory = get_str(body, "territory", min_len=2, max_len=2)
    _validate_territory(territory)
    commission_percent = get_number(body, "commission_percent", lo=0.0, hi=50.0)
    effective_from_str = get_str(body, "effective_from")
    effective_from = parse_iso8601(effective_from_str)
    effective_until_str = body.get("effective_until")
    effective_until = parse_iso8601(effective_until_str) if effective_until_str else None

    with store.lock:
        if rights_holder_id not in store.rights_holders:
            raise_err("ERR_NOT_FOUND", "RightsHolder not found")

        # Temporal validation
        if effective_until is not None and effective_from >= effective_until:
            raise_err("ERR_AGENCY_BINDING_OVERLAP", "effective_from must be < effective_until")

        # Overlap check on (rights_holder_id, agency_kind, territory)
        for existing in store.agency_bindings.values():
            if (existing["rights_holder_id"] == rights_holder_id and
                    existing["agency_kind"] == agency_kind and
                    existing["territory"] == territory and
                    existing["status"] == "ACTIVE"):
                e_from = parse_iso8601(existing["effective_from"])
                e_until = parse_iso8601(existing["effective_until"]) if existing.get("effective_until") else None
                # Two intervals [a, b) and [c, d) (with b or d possibly None for open-ended).
                a, b = e_from, e_until
                c, d = effective_from, effective_until
                overlap = _intervals_overlap(a, b, c, d)
                if overlap:
                    raise_err("ERR_AGENCY_BINDING_OVERLAP", "Overlap with existing ACTIVE binding")
                # Successor check (validation #20): successor must start at or after predecessor's effective_until.
                # If existing ends at b and proposed starts at c < b: overlap (already caught). If c >= b, ok.
                # The "no buffer" rule is satisfied by allowing c == b.

        row = store.common_fields()
        row.update({
            "rights_holder_id": rights_holder_id,
            "agency_kind": agency_kind,
            "agency_name": agency_name,
            "territory": territory,
            "commission_percent": float(commission_percent),
            "effective_from": effective_from_str_normalized(effective_from_str, effective_from),
            "effective_until": effective_until_str_normalized(effective_until_str, effective_until) if effective_until else None,
            "status": "ACTIVE",
        })
        store.agency_bindings[row["id"]] = row
    return serialize(row)


def effective_from_str_normalized(s: str, dt) -> str:
    # keep the raw string supplied by the user (it has already been validated as ISO 8601)
    return s


def effective_until_str_normalized(s, dt) -> str:
    return s


def _intervals_overlap(a, b, c, d):
    """[a, b) overlaps [c, d). None means open-ended."""
    a_end = b if b is not None else None
    c_end = d if d is not None else None
    # Open-ended intervals: treat None as infinity.
    if a_end is None and c_end is None:
        return True  # both infinite, surely overlap
    if a_end is None:
        # [a, inf) overlaps [c, d) iff a < d
        return a < c_end
    if c_end is None:
        return c < a_end
    return a < c_end and c < a_end


def terminate_agency_binding(binding_id: str, body: dict) -> dict:
    with store.lock:
        b = store.agency_bindings.get(binding_id)
        if not b:
            raise_err("ERR_NOT_FOUND", "AgencyBinding not found")
        # OCC
        if isinstance(body, dict) and "version" in body and body["version"] is not None:
            if body["version"] != b["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        b["status"] = "TERMINATED"
        store.touch(b)
        return serialize(b)


def get_active_binding_for_share(binding_id: str, holder_id: str, region: str):
    """Return binding row only if applicable for a share belonging to holder_id targeting pool region."""
    if not binding_id:
        return None
    b = store.agency_bindings.get(binding_id)
    if not b:
        return None
    if b["rights_holder_id"] != holder_id:
        return None
    if b["status"] != "ACTIVE":
        return None
    if b["territory"] != "WW" and b["territory"] != region:
        return None
    return b


def binding_active_at(binding: dict, when) -> bool:
    """Check the binding is active at the given UTC datetime."""
    if binding["status"] != "ACTIVE":
        return False
    e_from = parse_iso8601(binding["effective_from"])
    e_until = parse_iso8601(binding["effective_until"]) if binding.get("effective_until") else None
    if when < e_from:
        return False
    if e_until is not None and when >= e_until:
        return False
    return True
