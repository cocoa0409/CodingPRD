"""Assets and their source candidates."""
from flask import Blueprint, request

from core import (ROLE_ARCHIVE_RESEARCHER, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL,
                  ROLE_PRODUCTION_ADMIN, body, by_seq, created, db, fail, guard, invalid, new_row,
                  ok, ok_list, opt_int, opt_str, pagination, public, req_enum, req_int, req_str,
                  touch)
from domain import (bump_asset, candidates_of_asset, get_archive, get_asset, get_production,
                    recompute_production)

bp = Blueprint("assets", __name__)

ASSET_TYPES = ("ARCHIVAL_FOOTAGE", "MUSIC")
USAGE_PURPOSES = ("CRITICAL_COMMENTARY", "ILLUSTRATIVE_BACKGROUND")
AVAILABILITY_STATUSES = ("AVAILABLE", "ELEMENT_MISSING", "RIGHTS_UNCLEAR", "WITHDRAWN")
CLEARANCE_OPEN_STATUSES = ("DEVELOPMENT", "CLEARANCE")


@bp.post("/productions/<pid>/assets")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_PRODUCTION_ADMIN)
def create_asset(pid):
    production = get_production(pid)
    data = body()

    asset_type = req_enum(data, "asset_type", ASSET_TYPES)
    title = req_str(data, "title")
    tc_in = req_int(data, "timecode_in_seconds", minimum=0)
    tc_out = req_int(data, "timecode_out_seconds", minimum=0)
    usage_purpose = req_enum(data, "usage_purpose", USAGE_PURPOSES)
    if tc_out <= tc_in:
        invalid("timecode_out_seconds must exceed timecode_in_seconds.")
    depiction_key = opt_str(data, "depiction_subject_key")
    pd_reference = opt_str(data, "pd_attestation_reference")

    if production["status"] not in CLEARANCE_OPEN_STATUSES:
        fail("ERR_PRODUCTION_NOT_IN_CLEARANCE",
             "A %s production accepts no new assets." % production["status"])

    row = new_row()
    row.update({
        "production_id": pid,
        "asset_type": asset_type,
        "title": title,
        "timecode_in_seconds": tc_in,
        "timecode_out_seconds": tc_out,
        "duration_seconds": tc_out - tc_in,
        "usage_purpose": usage_purpose,
        "depiction_subject_key": depiction_key,
        "pd_attestation_reference": pd_reference,
        "selected_source_candidate_id": None,
        "rights_basis": "PUBLIC_DOMAIN" if pd_reference is not None else "UNDETERMINED",
        "licensing_status": "CLEARED" if pd_reference is not None else "UNCLEARED",
        "depiction_status": "PENDING" if depiction_key is not None else "NOT_REQUIRED",
        "lapse_count": 0,
    })
    db.assets[row["id"]] = row

    recompute_production(production)
    touch(production)
    return created(public(row))


@bp.get("/assets/<aid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_ARCHIVE_RESEARCHER,
       ROLE_LEGAL_COUNSEL)
def read_asset(aid):
    return ok(public(get_asset(aid)))


@bp.get("/assets")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_ARCHIVE_RESEARCHER,
       ROLE_LEGAL_COUNSEL)
def list_assets():
    limit, offset = pagination()
    rows = by_seq(list(db.assets.values()))
    for key in ("production_id", "selected_source_candidate_id", "asset_type",
                "licensing_status", "depiction_status", "rights_basis"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/assets/<aid>/source-candidates")
@guard(ROLE_ARCHIVE_RESEARCHER)
def create_candidate(aid):
    asset = get_asset(aid)
    data = body()

    archive_id = data.get("archive_id")
    if not isinstance(archive_id, str) or not archive_id.strip():
        invalid("Field 'archive_id' is required and must be a non-empty string.")
    get_archive(archive_id)

    row = new_row()
    row.update({
        "asset_id": aid,
        "archive_id": archive_id,
        "availability_status": req_enum(data, "availability_status", AVAILABILITY_STATUSES),
        "quoted_rate_per_30s_cents": opt_int(data, "quoted_rate_per_30s_cents", 0, minimum=0),
        "provenance_confidence": opt_int(data, "provenance_confidence", 0, minimum=0,
                                         maximum=100),
        "selection_status": "NOT_SELECTED",
    })
    db.source_candidates[row["id"]] = row
    return created(public(row))


@bp.get("/assets/<aid>/source-candidates")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def list_candidates(aid):
    get_asset(aid)
    limit, offset = pagination()
    rows = candidates_of_asset(aid)
    for key in ("availability_status", "selection_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/assets/<aid>/select-source")
@guard(ROLE_ARCHIVE_RESEARCHER, ROLE_CLEARANCE_SUPERVISOR)
def select_source(aid):
    asset = get_asset(aid)
    data = body()
    candidate_id = req_str(data, "source_candidate_id")

    candidates = candidates_of_asset(aid)
    chosen = None
    for candidate in candidates:
        if candidate["id"] == candidate_id:
            chosen = candidate
            break
    if chosen is None:
        fail("ERR_SOURCE_CANDIDATE_NOT_FOUND",
             "No source candidate %s on this asset." % candidate_id)

    if not any(c["availability_status"] == "AVAILABLE" for c in candidates):
        fail("ERR_NO_AVAILABLE_SOURCE",
             "The asset has no source candidate in AVAILABLE.")
    if chosen["availability_status"] != "AVAILABLE":
        fail("ERR_NO_AVAILABLE_SOURCE",
             "Only an AVAILABLE candidate may be selected.")

    for candidate in candidates:
        if candidate["id"] != chosen["id"] and candidate["selection_status"] == "SELECTED":
            candidate["selection_status"] = "REJECTED"
            touch(candidate)
    if chosen["selection_status"] != "SELECTED":
        chosen["selection_status"] = "SELECTED"
        touch(chosen)

    asset["selected_source_candidate_id"] = chosen["id"]
    bump_asset(asset)
    return ok(public(asset))
