"""ShoppableServiceList: create with entry-composition policing, certify
(ordered thresholds), publish (version pinning + auto-archive), and the
consumer display tool computed from PINNED records (PRD 3.5, 2.7)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ANCILLARY_INCLUSION_VIOLATION,
    ERR_BUNDLED_ITEM_NOT_ANCILLARY,
    ERR_CROSS_FACILITY_REFERENCE,
    ERR_DISPLAY_DISABLED,
    ERR_ENTRY_NOT_SHOPPABLE,
    ERR_ENTRY_RECORD_MISSING,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ITEM_RETIRED,
    ERR_LIST_NOT_CERTIFIED,
    ERR_LIST_NOT_DRAFT,
    ERR_LIST_NOT_PUBLISHED,
    ERR_MANDATED_COUNT_BELOW_MINIMUM,
    ERR_NO_PUBLISHED_CYCLE,
    ERR_SERVICE_ITEM_NOT_FOUND,
    ERR_SHOPPABLE_COUNT_BELOW_MINIMUM,
    ERR_SHOPPABLE_LIST_NOT_FOUND,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_list,
    require_string,
    sort_created,
)

bp = Blueprint("lists", __name__)


def get_list_or_404(lid: str) -> dict:
    lst = db.shoppable_service_lists.get(lid)
    if lst is None:
        raise_err(ERR_SHOPPABLE_LIST_NOT_FOUND, "Shoppable service list not found")
    return lst


def _validate_entries(facility_id: str, entries: list) -> list:
    """Entry composition policing at creation (PRD 3.5). Returns the
    normalized entry array. Validation follows the PRD 2.9 ladder:
    shape -> existence (P3) -> state (P4) -> structural (P6) -> referential (P7)."""
    normalized = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, f"entries[{idx}] must be an object")
        if "service_item_id" not in entry or not isinstance(entry["service_item_id"], str) or entry["service_item_id"] == "":
            raise_err(ERR_INVALID_REQUEST, f"entries[{idx}].service_item_id is required")
        if "display_name" not in entry or not isinstance(entry["display_name"], str):
            raise_err(ERR_INVALID_REQUEST, f"entries[{idx}].display_name is required")
        bundled = entry.get("bundled_ancillary_item_ids", [])
        if bundled is None:
            bundled = []
        if not isinstance(bundled, list) or any(not isinstance(b, str) for b in bundled):
            raise_err(ERR_INVALID_REQUEST, f"entries[{idx}].bundled_ancillary_item_ids must be an array of ids")
        include_cond = entry.get("include_conditional_ancillaries")
        if not isinstance(include_cond, bool):
            raise_err(ERR_INVALID_REQUEST, f"entries[{idx}].include_conditional_ancillaries must be a boolean")
        display_order = entry.get("display_order")
        if isinstance(display_order, bool) or not isinstance(display_order, int):
            raise_err(ERR_INVALID_REQUEST, f"entries[{idx}].display_order must be an integer")
        normalized.append({
            "service_item_id": entry["service_item_id"],
            "display_name": entry["display_name"],
            "bundled_ancillary_item_ids": bundled,
            "include_conditional_ancillaries": include_cond,
            "display_order": display_order,
        })

    # Existence (P3): every referenced item, entries in order, bundles after.
    for entry in normalized:
        if entry["service_item_id"] not in db.service_items:
            raise_err(ERR_SERVICE_ITEM_NOT_FOUND, "Entry service item not found")
        for anc_id in entry["bundled_ancillary_item_ids"]:
            if anc_id not in db.service_items:
                raise_err(ERR_SERVICE_ITEM_NOT_FOUND, "Bundled ancillary item not found")

    # State (P4): entry items must not be RETIRED.
    for entry in normalized:
        if db.service_items[entry["service_item_id"]]["status"] == "RETIRED":
            raise_err(ERR_ITEM_RETIRED, "Entry references a RETIRED service item")

    # Structural (P6): entry class, then bundled class, then inclusion mode
    # (the class check precedes the inclusion-mode check).
    for entry in normalized:
        item = db.service_items[entry["service_item_id"]]
        if item["service_class"] != "SHOPPABLE":
            raise_err(ERR_ENTRY_NOT_SHOPPABLE, "Entry item must have service_class SHOPPABLE")
        for anc_id in entry["bundled_ancillary_item_ids"]:
            anc = db.service_items[anc_id]
            if anc["service_class"] != "ANCILLARY":
                raise_err(ERR_BUNDLED_ITEM_NOT_ANCILLARY, "Bundled item must have service_class ANCILLARY")
            if anc["ancillary_inclusion"] == "SEPARATELY_PRICED":
                raise_err(ERR_ANCILLARY_INCLUSION_VIOLATION, "SEPARATELY_PRICED ancillaries can never be bundled")

    # Referential (P7): every entry's item must belong to the list's facility.
    for entry in normalized:
        if db.service_items[entry["service_item_id"]]["facility_id"] != facility_id:
            raise_err(ERR_CROSS_FACILITY_REFERENCE, "Entry item belongs to a different facility")

    return normalized


@bp.post("/transparency/shoppable-service-lists")
@require_roles("TransparencyOfficer")
def create_list(_user_id: str, _role: str):
    body = get_json_body()
    facility_id = require_string(body, "facility_id")
    title = require_string(body, "title")
    entries_raw = require_list(body, "entries")

    # Existence (P3).
    if facility_id not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")

    entries = _validate_entries(facility_id, entries_raw)

    entry_count = len(entries)
    mandated_count = sum(
        1 for e in entries
        if db.service_items[e["service_item_id"]].get("cms_shoppable_mandated") is True
    )

    lst = db.stamp_new({
        "facility_id": facility_id,
        "title": title,
        "entries": entries,
        "entry_count": entry_count,
        "mandated_entry_count": mandated_count,
        "pinned_records": [],
        "status": "DRAFT",
    })
    db.shoppable_service_lists[lst["id"]] = lst
    return success_object(db.public(lst), 201)


@bp.get("/transparency/facilities/<fid>/shoppable-service-lists")
@require_roles(*ALL_ROLES)
def list_facility_lists(fid: str, _user_id: str, _role: str):
    if fid not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    limit, offset = parse_pagination()
    items = [l for l in db.shoppable_service_lists.values() if l["facility_id"] == fid]
    items = apply_filters(items, ["status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(l) for l in page], limit, offset, total)


@bp.post("/transparency/shoppable-service-lists/<lid>/certify")
@require_roles("TransparencyOfficer")
def certify_list(lid: str, _user_id: str, _role: str):
    lst = get_list_or_404(lid)
    # State (P4).
    if lst["status"] != "DRAFT":
        raise_err(ERR_LIST_NOT_DRAFT, "Only a DRAFT list can be certified")
    fac = db.facilities.get(lst["facility_id"])
    # Fiscal (P9) in pinned order: total-count check FIRST (>= inclusive),
    # mandated-count check SECOND.
    if lst["entry_count"] < fac["shoppable_min_entries"]:
        raise_err(ERR_SHOPPABLE_COUNT_BELOW_MINIMUM, "entry_count below facility shoppable_min_entries")
    if lst["mandated_entry_count"] < fac["mandated_min_entries"]:
        raise_err(ERR_MANDATED_COUNT_BELOW_MINIMUM, "mandated_entry_count below facility mandated_min_entries")
    lst["status"] = "CERTIFIED"
    db.bump(lst)
    return success_object(db.public(lst), 200)


def _latest_published_cycle(facility_id: str):
    matches = [c for c in db.publication_cycles.values()
               if c["facility_id"] == facility_id and c["status"] == "PUBLISHED"]
    # Latest period_start, tie-break created_at ASC (insertion order).
    matches.sort(key=lambda c: (-db.parse_dt(c["period_start"]).timestamp(), c["created_at"], c["_seq"]))
    return matches[0] if matches else None


@bp.post("/transparency/shoppable-service-lists/<lid>/publish")
@require_roles("TransparencyOfficer")
def publish_list(lid: str, _user_id: str, _role: str):
    lst = get_list_or_404(lid)
    # State (P4).
    if lst["status"] != "CERTIFIED":
        raise_err(ERR_LIST_NOT_CERTIFIED, "Only a CERTIFIED list can be published")

    # Cross-entity fiscal gates: a PUBLISHED cycle must exist, and every entry
    # item must have a PUBLISHED charge record in the latest PUBLISHED cycle.
    cycle = _latest_published_cycle(lst["facility_id"])
    if cycle is None:
        raise_err(ERR_NO_PUBLISHED_CYCLE, "Facility has no PUBLISHED publication cycle")

    pinned = []
    for entry in lst["entries"]:
        candidates = [
            r for r in db.standard_charge_records.values()
            if r["facility_id"] == lst["facility_id"]
            and r["service_item_id"] == entry["service_item_id"]
            and r["status"] == "PUBLISHED"
            and r["publication_cycle_id"] == cycle["id"]
        ]
        if not candidates:
            raise_err(ERR_ENTRY_RECORD_MISSING, "An entry item lacks a PUBLISHED charge record in the latest PUBLISHED cycle")
        candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
        rec = candidates[-1]
        pinned.append({
            "service_item_id": entry["service_item_id"],
            "charge_record_id": rec["id"],
            "record_version": rec["version"],
        })

    # Auto-archive the prior PUBLISHED list of the same facility.
    for other in db.shoppable_service_lists.values():
        if (
            other["id"] != lid
            and other["facility_id"] == lst["facility_id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "ARCHIVED"
            db.bump(other)

    lst["pinned_records"] = pinned
    lst["status"] = "PUBLISHED"
    db.bump(lst)
    return success_object(db.public(lst), 200)


@bp.get("/transparency/shoppable-service-lists/<lid>/display")
@require_roles(*ALL_ROLES)
def display_list(lid: str, _user_id: str, _role: str):
    lst = get_list_or_404(lid)
    # State (P4), then the feature-flag safety gate (P5).
    if lst["status"] != "PUBLISHED":
        raise_err(ERR_LIST_NOT_PUBLISHED, "Display is served only for a PUBLISHED list")
    fac = db.facilities.get(lst["facility_id"])
    if fac is not None and fac.get("shoppable_display_enabled") is False:
        raise_err(ERR_DISPLAY_DISABLED, "Consumer display is disabled for this facility")

    pinned_by_item = {p["service_item_id"]: p for p in lst.get("pinned_records", [])}
    rows = []
    stale_any = False
    for entry in lst["entries"]:
        pin = pinned_by_item.get(entry["service_item_id"])
        rec = db.standard_charge_records.get(pin["charge_record_id"]) if pin else None
        # Package price computed at read time from the PINNED record's stored
        # snapshot values — never from any live record (PRD 3.5).
        if rec is not None:
            candidates = [rec["gross_charge_cents"], rec["discounted_cash_cents"]]
            if rec.get("derived_disclosure_cents") is not None:
                candidates.append(rec["derived_disclosure_cents"])
            base_cents = min(candidates)
            stale = (rec["version"] != pin["record_version"]) or (rec["status"] == "SUPERSEDED")
        else:
            base_cents = 0
            stale = True
        stale_any = stale_any or stale

        # Bundle: per-item floor FIRST, then summation; never re-rounded (2.7).
        bundle_sum = 0
        for anc_id in entry.get("bundled_ancillary_item_ids", []):
            anc = db.service_items.get(anc_id)
            if anc is None:
                continue
            mode = anc.get("ancillary_inclusion")
            contributes = (
                mode == "ALWAYS_BUNDLED"
                or (mode == "CONDITIONALLY_INCLUDED" and entry.get("include_conditional_ancillaries") is True)
            )
            if contributes:
                # floor(gross * 0.90) via exact integer math: (gross*9)//10.
                bundle_sum += (anc["gross_charge_cents"] * 9) // 10

        rows.append({
            "service_item_id": entry["service_item_id"],
            "display_name": entry["display_name"],
            "display_order": entry["display_order"],
            "bundled_ancillary_item_ids": entry.get("bundled_ancillary_item_ids", []),
            "include_conditional_ancillaries": entry.get("include_conditional_ancillaries", False),
            "charge_record_id": pin["charge_record_id"] if pin else None,
            "record_version": pin["record_version"] if pin else None,
            "base_cents": base_cents,
            "bundle_cents": bundle_sum,
            "package_price_cents": base_cents + bundle_sum,
            "stale": stale,
        })

    return success_object({
        "list_id": lst["id"],
        "entries": rows,
        "stale_any": stale_any,
    }, 200)
