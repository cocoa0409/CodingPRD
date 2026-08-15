"""Item, Valuation, and BlackoutWindow routes (PRD 3.3, 3.4)."""

from flask import Blueprint, request

import errors
import middleware as mw
import response
from db import stores
from services import workflows as wf

bp = Blueprint("items", __name__)

PO = ["ProcurementOfficer"]
READ = mw.ALL_ROLES


# ------------------------------------------------------------------- items

@bp.post("/items")
def create_item():
    mw.require_auth(PO)
    body = mw.get_json_body()
    solicitation_id = mw.require_string(body, "solicitation_id")
    sol = mw.get_or_404("solicitations", solicitation_id)
    title = mw.require_string(body, "title")
    description = mw.require_string(body, "description")
    kind = mw.require_enum(body, "kind", {"PHYSICAL", "EXPERIENCE"})
    event = stores["gala_events"][sol["gala_event_id"]]
    if event["status"] not in ("SOLICITING", "CATALOGING"):
        raise errors.err_event_phase_forbidden("Item receipt requires event SOLICITING or CATALOGING")
    if sol["status"] != "PLEDGED":
        raise errors.err_solicitation_not_pledged()
    rec = mw.new_record()
    rec["solicitation_id"] = sol["id"]
    rec["donor_id"] = sol["donor_id"]
    rec["gala_event_id"] = sol["gala_event_id"]
    rec["bundle_id"] = None
    rec["title"] = title
    rec["description"] = description
    rec["kind"] = kind
    rec["status"] = "RECEIVED"
    rec["current_fmv_cents"] = None
    rec["disclosure_tier"] = None
    stores["items"][rec["id"]] = rec
    # Same transaction: the solicitation moves PLEDGED -> FULFILLED.
    sol["status"] = "FULFILLED"
    mw.touch(sol)
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/items/<rid>")
def get_item(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("items", rid)))


@bp.get("/items")
def list_items():
    mw.require_auth(READ)
    limit, offset = mw.parse_pagination()
    args = request.args
    items = list(stores["items"].values())
    for f in ("solicitation_id", "donor_id", "gala_event_id", "bundle_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [i for i in items if str(i.get(f)) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(i) for i in page], limit, offset, total)


# ------------------------------------------------------------------- valuations

@bp.post("/items/<rid>/valuations")
def submit_valuation(rid):
    user_id, _ = mw.require_auth(PO)
    item = mw.get_or_404("items", rid)
    body = mw.get_json_body()
    fmv_cents = mw.require_int(body, "fmv_cents")
    if fmv_cents < 1:
        raise errors.err_invalid_request("fmv_cents must be >= 1")
    fmv_source = mw.require_enum(body, "fmv_source", {"DONOR_DECLARED", "APPRAISAL", "COMPARABLE_SALE"})
    expected = mw.require_int(body, "expected_item_version")
    if expected != item["version"]:
        raise errors.err_stale_version()
    # Submission supersedes any still-SUBMITTED valuation of the same item.
    for v in stores["valuations"].values():
        if v["item_id"] == item["id"] and v["status"] == "SUBMITTED":
            v["status"] = "SUPERSEDED"
            mw.touch(v)
    rec = mw.new_record()
    rec["item_id"] = item["id"]
    rec["fmv_cents"] = fmv_cents
    rec["fmv_source"] = fmv_source
    rec["status"] = "SUBMITTED"
    rec["submitted_by_user_id"] = user_id
    rec["decided_by_user_id"] = None
    stores["valuations"][rec["id"]] = rec
    mw.touch(item)
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/items/<rid>/valuations")
def list_item_valuations(rid):
    mw.require_auth(READ)
    item = mw.get_or_404("items", rid)
    limit, offset = mw.parse_pagination()
    items = [v for v in stores["valuations"].values() if v["item_id"] == item["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(v) for v in page], limit, offset, total)


@bp.post("/valuations/<rid>/approve")
def approve_valuation(rid):
    user_id, _ = mw.require_auth(["ValuationApprover"])
    val = mw.get_or_404("valuations", rid)
    item = stores["items"][val["item_id"]]
    # Generic state check (priority 7): re-valuation blocked once the item is
    # terminally dispositioned.
    if item["status"] in ("RETURNED_TO_DONOR", "DISCARDED"):
        raise errors.err_invalid_state("Item is terminally dispositioned; re-valuation blocked")
    if val["status"] != "SUBMITTED":
        raise errors.err_valuation_already_decided()
    if user_id == val["submitted_by_user_id"]:
        raise errors.err_sod()
    wf.apply_valuation_approval(val, user_id)
    return response.success_object(mw.serialize(val))


@bp.post("/valuations/<rid>/reject")
def reject_valuation(rid):
    user_id, _ = mw.require_auth(["ValuationApprover"])
    val = mw.get_or_404("valuations", rid)
    if val["status"] != "SUBMITTED":
        raise errors.err_valuation_already_decided()
    if user_id == val["submitted_by_user_id"]:
        raise errors.err_sod()
    val["status"] = "REJECTED"
    val["decided_by_user_id"] = user_id
    mw.touch(val)
    return response.success_object(mw.serialize(val))


# ------------------------------------------------------------------- blackout windows

@bp.post("/items/<rid>/blackout-windows")
def create_blackout_window(rid):
    mw.require_auth(["CatalogManager"])
    item = mw.get_or_404("items", rid)
    body = mw.get_json_body()
    starts_at = mw.require_datetime(body, "starts_at")
    ends_at = mw.require_datetime(body, "ends_at")
    label = mw.optional_string(body, "label")
    if item["kind"] != "EXPERIENCE":
        raise errors.err_invalid_request("Blackout windows attach only to EXPERIENCE items")
    if not starts_at < ends_at:
        raise errors.err_invalid_request("ends_at must be strictly later than starts_at")
    rec = mw.new_record()
    rec["item_id"] = item["id"]
    rec["starts_at"] = starts_at
    rec["ends_at"] = ends_at
    rec["label"] = label
    stores["blackout_windows"][rec["id"]] = rec
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/items/<rid>/blackout-windows")
def list_blackout_windows(rid):
    mw.require_auth(READ)
    item = mw.get_or_404("items", rid)
    limit, offset = mw.parse_pagination()
    items = [w for w in stores["blackout_windows"].values() if w["item_id"] == item["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(w) for w in page], limit, offset, total)
