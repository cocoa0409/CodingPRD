"""Vessels, liens, documentation records."""
from db import db, clock
from errors import err_duplicate, err_doc_mode, err_lien_instrument, err_invalid_state
from middleware import (get_caller, require_roles, get_json_body, require_fields,
                        check_enum, check_int, check_str, check_number)
from response import success_object, success_list
from services.common import (new_entity, touch, get_or_404, serialize_vessel,
                             serialize_lien, serialize_doc_record)
from flask import Blueprint
import re

bp = Blueprint("vessels", __name__)

US_STATES = {"FL", "CA", "WA", "NY", "TX", "RI", "MD", "NC", "SC", "MA", "GA", "NJ"}
DOC_MODES = {"USCG", "STATE"}
LIEN_INSTRUMENTS = {"PREFERRED_MORTGAGE", "UCC1", "MECHANIC"}
RECORD_KINDS = {"USCG_COD", "STATE_TITLE", "ABSTRACT"}
HIN_RE = re.compile(r"^[0-9A-Z]{12}$")
USCG_NO_RE = re.compile(r"^[0-9]{6,7}$")


def _hin_in_use(hin):
    return any(v["hin"] == hin for v in db.vessels.values())


def _check_doc_coherence(body, existing=None):
    """Vessel documentation coherence (priority 10). Merges body over existing."""
    merged = dict(existing) if existing else {}
    for k in ("documentation_mode", "uscg_official_no", "state_title_no"):
        if k in body:
            merged[k] = body[k]
    mode = merged.get("documentation_mode")
    uscg_no = merged.get("uscg_official_no")
    state_no = merged.get("state_title_no")
    if mode == "USCG":
        # uscg_official_no required; must not carry a state title number in its place
        if not uscg_no:
            raise err_doc_mode("uscg_official_no required when documentation_mode == USCG")
        if state_no:
            raise err_doc_mode("state_title_no forbidden when documentation_mode == USCG")
    elif mode == "STATE":
        if not state_no:
            raise err_doc_mode("state_title_no required when documentation_mode == STATE")
        if uscg_no:
            raise err_doc_mode("uscg_official_no forbidden when documentation_mode == STATE")


def _recompute_liens_status(vessel):
    open_liens = [l for l in db.liens.values()
                  if l["vessel_id"] == vessel["id"] and l["status"] in ("RECORDED", "PARTIALLY_SATISFIED")]
    vessel["liens_status"] = "ENCUMBERED" if open_liens else "CLEAN"


@bp.route("/yacht/vessels", methods=["POST"])
def create_vessel():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent"])
    body = get_json_body()
    require_fields(body, ["hin", "make", "model", "year_built", "length_overall_ft",
                          "documentation_mode", "current_location_state_code"])
    # Priority 9: uniqueness of HIN precedes documentation coherence
    check_str(body, "hin")
    if _hin_in_use(body["hin"]):
        raise err_duplicate(f"Vessel with hin {body['hin']} already exists")
    # Priority 10: documentation coherence
    check_enum(body, "documentation_mode", DOC_MODES)
    _check_doc_coherence(body)
    # Shape checks
    if not HIN_RE.match(body["hin"]):
        from errors import err_invalid_request
        raise err_invalid_request("hin must be exactly 12 uppercase alphanumerics")
    check_str(body, "make")
    check_str(body, "model")
    check_int(body, "year_built")
    if body["year_built"] > clock.now().year:
        from errors import err_invalid_request
        raise err_invalid_request("year_built may not be later than the current clock year")
    check_number(body, "length_overall_ft")
    check_enum(body, "current_location_state_code", US_STATES)
    if body.get("documentation_mode") == "USCG":
        check_str(body, "uscg_official_no")
        if not USCG_NO_RE.match(body["uscg_official_no"]):
            from errors import err_invalid_request
            raise err_invalid_request("uscg_official_no must be a 6-7 digit string")
    if body.get("state_title_no") is not None:
        check_str(body, "state_title_no", required=False)

    v = new_entity()
    v["hin"] = body["hin"]
    v["make"] = body["make"]
    v["model"] = body["model"]
    v["year_built"] = body["year_built"]
    v["length_overall_ft"] = body["length_overall_ft"]
    v["documentation_mode"] = body["documentation_mode"]
    v["uscg_official_no"] = body.get("uscg_official_no")
    v["state_title_no"] = body.get("state_title_no")
    v["current_location_state_code"] = body["current_location_state_code"]
    v["liens_status"] = "CLEAN"
    db.vessels[v["id"]] = v
    return success_object(serialize_vessel(v), 201)


@bp.route("/yacht/vessels/<vid>", methods=["GET"])
def get_vessel(vid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    v = get_or_404(db.vessels, vid, "Vessel")
    return success_object(serialize_vessel(v))


@bp.route("/yacht/vessels/<vid>", methods=["PUT"])
def update_vessel(vid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent"])
    v = get_or_404(db.vessels, vid, "Vessel")
    body = get_json_body()
    # Priority 10: documentation coherence on the merged record
    _check_doc_coherence(body, existing=v)
    if "make" in body:
        check_str(body, "make")
    if "model" in body:
        check_str(body, "model")
    if "current_location_state_code" in body:
        check_enum(body, "current_location_state_code", US_STATES)
    if "uscg_official_no" in body and body["uscg_official_no"] is not None:
        check_str(body, "uscg_official_no", required=False)
    if "state_title_no" in body and body["state_title_no"] is not None:
        check_str(body, "state_title_no", required=False)

    for k in ("make", "model", "current_location_state_code", "state_title_no", "uscg_official_no"):
        if k in body:
            v[k] = body[k]
    touch(v)
    return success_object(serialize_vessel(v))


@bp.route("/yacht/vessels/<vid>/liens", methods=["GET"])
def list_liens(vid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    v = get_or_404(db.vessels, vid, "Vessel")
    items = sorted([l for l in db.liens.values() if l["vessel_id"] == v["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_lien(l) for l in items], len(items) or 10, 0, len(items))


@bp.route("/yacht/vessels/<vid>/liens", methods=["POST"])
def create_lien(vid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent", "ClosingOfficer"])
    v = get_or_404(db.vessels, vid, "Vessel")
    body = get_json_body()
    require_fields(body, ["lienholder_name", "instrument_type", "amount_cents", "priority_rank"])
    # Priority 13: lien instrument coherence
    check_enum(body, "instrument_type", LIEN_INSTRUMENTS)
    if body["instrument_type"] == "PREFERRED_MORTGAGE" and v["documentation_mode"] != "USCG":
        raise err_lien_instrument()
    check_str(body, "lienholder_name")
    check_int(body, "amount_cents", min_v=0)
    check_int(body, "priority_rank", min_v=1)

    l = new_entity()
    l["vessel_id"] = v["id"]
    l["lienholder_name"] = body["lienholder_name"]
    l["instrument_type"] = body["instrument_type"]
    l["amount_cents"] = body["amount_cents"]
    l["payoff_amount_cents"] = 0
    l["priority_rank"] = body["priority_rank"]
    l["status"] = "RECORDED"
    db.liens[l["id"]] = l
    # Side effect: vessel flips to ENCUMBERED and bumps version
    v["liens_status"] = "ENCUMBERED"
    touch(v)
    return success_object(serialize_lien(l), 201)


@bp.route("/yacht/liens/<lid>/release", methods=["POST"])
def release_lien(lid):
    from errors import err_invalid_request
    caller = get_caller()
    require_roles(caller, ["ListingAgent", "ClosingOfficer"])
    l = get_or_404(db.liens, lid, "LienRecord")
    body = get_json_body()
    # State check (priority 5)
    if l["status"] != "RECORDED":
        raise err_invalid_state("Lien is not in RECORDED state")
    # Release evidence must be non-empty
    if not body.get("release_ref") or not isinstance(body.get("release_ref"), str):
        raise err_invalid_request("release_ref must be a non-empty string")
    l["status"] = "RELEASED"
    touch(l)
    v = db.vessels.get(l["vessel_id"])
    if v is not None:
        _recompute_liens_status(v)
    return success_object(serialize_lien(l))


@bp.route("/yacht/vessels/<vid>/documentation-records", methods=["GET"])
def list_doc_records(vid):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "ListingAgent", "SellingAgent",
                           "ClosingOfficer", "EscrowOfficer"])
    v = get_or_404(db.vessels, vid, "Vessel")
    items = sorted([d for d in db.doc_records.values() if d["vessel_id"] == v["id"]],
                   key=lambda x: x["created_at"])
    return success_list([serialize_doc_record(d) for d in items], len(items) or 10, 0, len(items))


@bp.route("/yacht/vessels/<vid>/documentation-records", methods=["POST"])
def create_doc_record(vid):
    caller = get_caller()
    require_roles(caller, ["ListingAgent", "ClosingOfficer"])
    v = get_or_404(db.vessels, vid, "Vessel")
    body = get_json_body()
    require_fields(body, ["record_kind", "instrument_no", "issue_date"])
    check_enum(body, "record_kind", RECORD_KINDS)
    check_str(body, "instrument_no")
    check_str(body, "issue_date")
    from db import parse_iso
    from errors import err_invalid_request
    try:
        parse_iso(body["issue_date"])
    except (ValueError, TypeError):
        raise err_invalid_request("issue_date must be an ISO-8601 datetime")

    # Filing a newer record of same kind supersedes the prior VALID one
    for d in db.doc_records.values():
        if d["vessel_id"] == v["id"] and d["record_kind"] == body["record_kind"] \
                and d["status"] == "VALID":
            d["status"] = "SUPERSEDED"
            touch(d)

    rec = new_entity()
    rec["vessel_id"] = v["id"]
    rec["record_kind"] = body["record_kind"]
    rec["instrument_no"] = body["instrument_no"]
    rec["issue_date"] = body["issue_date"]
    rec["status"] = "VALID"
    db.doc_records[rec["id"]] = rec
    return success_object(serialize_doc_record(rec), 201)
