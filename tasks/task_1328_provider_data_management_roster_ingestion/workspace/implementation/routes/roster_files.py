"""RosterFile endpoints (PRD §3.2, §3.4)."""

import hashlib
import json
import re

from flask import Blueprint, request

from db import DB, CLOCK
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import (
    ERR_SOURCE_NOT_ACTIVE, ERR_DUPLICATE_FILE, ERR_ROW_COUNT_MISMATCH,
    ERR_SOD_SAME_USER, ERR_STALE_VERSION, ERR_UNRESOLVED_ROW_CONFLICTS,
    ERR_NO_REPLACEMENT_FILE,
)
from middleware import require_roles, json_body, optional_json_body
from response import success_object, paginate
from services.common import new_common, touch, require_string, require_int
from services.identity import resolve_row
from services.attributes import apply_effective_dating
from services.quality import run_quality_scoring

bp = Blueprint("roster_files", __name__)

_NPI_RE = re.compile(r"^\d{10}$")
_TIN_RE = re.compile(r"^\d{9}$")


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _public_row(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _rows_of(file_id):
    rows = [r for r in DB.roster_rows.values() if r["roster_file_id"] == file_id]
    rows.sort(key=lambda r: r["row_index"])
    return rows


def _get_file(fid):
    f = DB.roster_files.get(fid)
    if f is None:
        raise not_found()
    return f


@bp.route("/pdm/roster-files", methods=["POST"])
def create_file():
    _role, user_id = require_roles("IntakeOperator")
    body = json_body()
    roster_source_id = require_string(body, "roster_source_id")
    external_file_ref = require_string(body, "external_file_ref")
    declared_row_count = require_int(body, "declared_row_count", minimum=0)
    checksum = require_string(body, "checksum")

    src = DB.roster_sources.get(roster_source_id)
    if src is None:
        raise not_found("roster_source_id does not exist")
    # Source must be ACTIVE — evaluated before the duplicate-file check.
    if src["status"] != "ACTIVE":
        raise ApiError(ERR_SOURCE_NOT_ACTIVE, 409, "RosterSource is not ACTIVE")
    for f in DB.roster_files.values():
        if f["roster_source_id"] != roster_source_id:
            continue
        if f["external_file_ref"] == external_file_ref or f["checksum"] == checksum:
            raise ApiError(ERR_DUPLICATE_FILE, 409,
                           "external_file_ref or checksum already registered for this source")

    rec = {
        **new_common(),
        "roster_source_id": roster_source_id,
        "external_file_ref": external_file_ref,
        "declared_row_count": declared_row_count,
        "received_at": CLOCK.now_iso(),
        "status": "RECEIVED",
        "parsed_row_count": 0,
        "rejected_row_count": 0,
        "committed_row_count": 0,
        "checksum": checksum,
        "_registrant_user_id": user_id,
        "_committer_user_id": None,
        "_payload_rows": body.get("payload_rows"),
    }
    DB.roster_files[rec["id"]] = rec
    return success_object(_public(rec), status=201)


@bp.route("/pdm/roster-files", methods=["GET"])
def list_files():
    require_roles("DataSteward", "IntakeOperator")
    items = list(DB.roster_files.values())
    src = request.args.get("roster_source_id")
    status = request.args.get("status")
    if src is not None:
        items = [f for f in items if f["roster_source_id"] == src]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginate([_public(f) for f in items], request.args)


@bp.route("/pdm/roster-files/<fid>", methods=["GET"])
def get_file(fid):
    require_roles("DataSteward", "IntakeOperator")
    return success_object(_public(_get_file(fid)))


# ---------------------------------------------------------------------------
# Pipeline transitions
# ---------------------------------------------------------------------------

@bp.route("/pdm/roster-files/<fid>/parse", methods=["POST"])
def parse_file(fid):
    require_roles("IntakeOperator")
    f = _get_file(fid)
    if f["status"] != "RECEIVED":
        raise invalid_state()
    src = DB.roster_sources.get(f["roster_source_id"])
    if src is None or src["status"] != "ACTIVE":
        raise ApiError(ERR_SOURCE_NOT_ACTIVE, 409, "RosterSource is not ACTIVE")

    payload_rows = f.get("_payload_rows")
    if payload_rows is not None:
        materialized = len(payload_rows)
    else:
        materialized = f["declared_row_count"]
    if materialized != f["declared_row_count"]:
        f["status"] = "REJECTED"
        touch(f)
        raise ApiError(ERR_ROW_COUNT_MISMATCH, 422,
                       "declared_row_count differs from materialized rows at parse")

    for i in range(materialized):
        if payload_rows is not None:
            raw = payload_rows[i]
            if not isinstance(raw, str):
                raw = json.dumps(raw)
        else:
            raw = f"row_{i}"
        row = {
            **new_common(),
            "roster_file_id": fid,
            "row_index": i,
            "raw_payload": raw,
            "normalized_payload": None,
            "npi": "",
            "tin": "",
            "location_key": "",
            "status": "PENDING",
            "reject_reason": None,
            "resolved_provider_id": None,
            "effective_date": None,
        }
        DB.roster_rows[row["id"]] = row
    f["parsed_row_count"] = materialized
    f["status"] = "PARSED"
    touch(f)
    return success_object(_public(f))


def _normalize_digits(value):
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def _normalize_row(row):
    """Format-specific normalization: coerce the raw row into canonical JSON
    with npi/tin/location_key/effective_date extracted."""
    raw = row["raw_payload"]
    payload = None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        npi = _normalize_digits(payload.get("npi"))
        tin = _normalize_digits(payload.get("tin"))
        loc = payload.get("location_key")
        if not loc:
            addr = payload.get("address") or {}
            parts = [
                str(payload.get("street1") or addr.get("street1") or ""),
                str(payload.get("city") or addr.get("city") or ""),
                str(payload.get("state") or addr.get("state") or ""),
                str(payload.get("zip") or addr.get("zip") or ""),
            ]
            joined = "|".join(p.strip().lower() for p in parts)
            loc = hashlib.sha256(joined.encode()).hexdigest()[:16] if joined.strip("|") else ""
        effective_date = payload.get("effective_date")
        if effective_date is None:
            effective_date = CLOCK.today()
        normalized = dict(payload)
        normalized["npi"] = npi
        normalized["tin"] = tin
        normalized["location_key"] = loc
        normalized["effective_date"] = effective_date
        return normalized, npi, tin, loc, effective_date
    # Non-JSON raw text: treat the whole line as unparseable identity legs.
    npi = _normalize_digits(raw)
    npi = npi if _NPI_RE.match(npi) else ""
    normalized = {"raw": raw, "npi": npi, "tin": "", "location_key": "",
                  "effective_date": CLOCK.today()}
    return normalized, npi, "", "", CLOCK.today()


@bp.route("/pdm/roster-files/<fid>/normalize", methods=["POST"])
def normalize_file(fid):
    require_roles("IntakeOperator")
    f = _get_file(fid)
    if f["status"] != "PARSED":
        raise invalid_state()
    rows = _rows_of(fid)
    for row in rows:
        if row["status"] != "PENDING":
            continue
        normalized, npi, tin, loc, eff = _normalize_row(row)
        row["normalized_payload"] = normalized
        row["npi"] = npi
        row["tin"] = tin
        row["location_key"] = loc
        row["effective_date"] = eff
        if not _NPI_RE.match(npi or ""):
            row["status"] = "REJECTED"
            row["reject_reason"] = "MALFORMED_NPI"
        elif not _TIN_RE.match(tin or ""):
            row["status"] = "REJECTED"
            row["reject_reason"] = "MALFORMED_TIN"
        elif not loc:
            row["status"] = "REJECTED"
            row["reject_reason"] = "MISSING_LOCATION"
        touch(row)
    # Duplicate-in-file detection on the surviving PENDING rows.
    seen = {}
    for row in rows:
        if row["status"] != "PENDING":
            continue
        triple = (row["npi"], row["tin"], row["location_key"])
        if triple in seen:
            row["status"] = "REJECTED"
            row["reject_reason"] = "DUPLICATE_IN_FILE"
            touch(row)
        else:
            seen[triple] = row["row_index"]
    f["rejected_row_count"] = sum(1 for r in rows if r["status"] == "REJECTED")
    f["status"] = "NORMALIZED"
    touch(f)
    return success_object(_public(f))


@bp.route("/pdm/roster-files/<fid>/validate", methods=["POST"])
def validate_file(fid):
    require_roles("IntakeOperator")
    f = _get_file(fid)
    if f["status"] != "NORMALIZED":
        raise invalid_state()
    src = DB.roster_sources.get(f["roster_source_id"])
    for row in _rows_of(fid):
        if row["status"] == "REJECTED":
            continue
        resolve_row(row, src)
    f["status"] = "VALIDATED"
    touch(f)
    return success_object(_public(f))


def _row_attributes(row):
    """Extract the attribute payload of a row: list of (group, key, value)."""
    payload = row.get("normalized_payload") or {}
    attrs = payload.get("attributes")
    out = []
    if isinstance(attrs, dict):
        for group, kv in attrs.items():
            if isinstance(kv, dict):
                for k, v in kv.items():
                    out.append((group, k, str(v)))
    elif isinstance(attrs, list):
        for item in attrs:
            if isinstance(item, dict):
                out.append((
                    item.get("attribute_group"),
                    item.get("attribute_key"),
                    str(item.get("attribute_value")),
                ))
    return [(g, k, v) for g, k, v in out if g and k]


@bp.route("/pdm/roster-files/<fid>/commit", methods=["POST"])
def commit_file(fid):
    _role, user_id = require_roles("IntakeOperator")
    f = _get_file(fid)
    # State legality first.
    if f["status"] != "VALIDATED":
        raise invalid_state()
    # Segregation of duties: registrant may not commit.
    if f.get("_registrant_user_id") is not None and user_id == f.get("_registrant_user_id"):
        raise ApiError(ERR_SOD_SAME_USER, 403,
                       "Commit attempted by the same user who registered the file")
    # OCC.
    body = optional_json_body()
    expected = body.get("expected_roster_file_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_roster_file_version is required")
    if expected != f["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_roster_file_version does not match the file's current version")
    # No PENDING or CONFLICT rows may remain.
    rows = _rows_of(fid)
    if any(r["status"] in ("PENDING", "CONFLICT") for r in rows):
        raise ApiError(ERR_UNRESOLVED_ROW_CONFLICTS, 409,
                       "Commit blocked: one or more rows unresolved")

    f["_committer_user_id"] = user_id
    touched_providers = set()
    src = DB.roster_sources.get(f["roster_source_id"])

    for row in rows:
        if row["status"] == "REJECTED":
            continue
        if row["status"] == "NEW_PROVIDER":
            provider = {
                **new_common(),
                "npi": row["npi"],
                "tin": row["tin"],
                "location_key": row["location_key"],
                "lifecycle_status": "ACTIVE",
                "merged_into_provider_id": None,
                "current_quality_score": 0,
                "staleness_flag": False,
                "last_roster_file_id": None,
            }
            DB.providers[provider["id"]] = provider
            pid = provider["id"]
        else:  # MATCHED
            pid = row["resolved_provider_id"]
            provider = DB.providers.get(pid)
            if provider is None:
                continue
            # Alias creation per the winning link kind.
            link_kind = row.get("_winning_link_kind")
            if link_kind in ("AUTO_FUZZY", "MANUAL", "AUTO_EXACT"):
                alias = {
                    **new_common(),
                    "provider_id": pid,
                    "alias_npi": row["npi"],
                    "alias_tin": row["tin"],
                    "alias_location_key": row["location_key"],
                    "match_confidence": row.get("_winning_match_score", 100),
                    "link_kind": link_kind,
                    "status": "ACTIVE",
                }
                DB.provider_aliases[alias["id"]] = alias
        # Upsert the row's attribute payload.
        for group, key, value in _row_attributes(row):
            attr = {
                **new_common(),
                "provider_id": pid,
                "attribute_group": group,
                "attribute_key": key,
                "attribute_value": value,
                "effective_date": row.get("effective_date") or CLOCK.today(),
                "term_date": None,
                "roster_source_id": f["roster_source_id"],
                "roster_row_id": row["id"],
                "supersedes_attribute_id": None,
                "status": "PENDING",
            }
            DB.provider_attributes[attr["id"]] = attr
            apply_effective_dating(pid, attr)
        touched_providers.add(pid)

    for pid in touched_providers:
        provider = DB.providers[pid]
        provider["last_roster_file_id"] = fid
        touch(provider)
        run_quality_scoring(pid, roster_file_id=fid)

    f["committed_row_count"] = sum(
        1 for r in rows if r["status"] in ("MATCHED", "NEW_PROVIDER")
    )
    f["rejected_row_count"] = sum(1 for r in rows if r["status"] == "REJECTED")
    f["status"] = "COMMITTED"
    touch(f)
    return success_object(_public(f))


@bp.route("/pdm/roster-files/<fid>/reject", methods=["POST"])
def reject_file(fid):
    require_roles("IntakeOperator")
    f = _get_file(fid)
    if f["status"] not in ("RECEIVED", "PARSED", "NORMALIZED", "VALIDATED"):
        raise invalid_state()
    prior = f["status"]
    if prior == "PARSED":
        for row in _rows_of(fid):
            if row["status"] == "PENDING":
                row["status"] = "REJECTED"
                if not row.get("reject_reason"):
                    row["reject_reason"] = "MALFORMED_NPI"
                touch(row)
    elif prior in ("NORMALIZED", "VALIDATED"):
        for row in _rows_of(fid):
            if row["status"] not in ("MATCHED", "NEW_PROVIDER", "REJECTED"):
                row["status"] = "REJECTED"
                touch(row)
    f["rejected_row_count"] = sum(
        1 for r in _rows_of(fid) if r["status"] == "REJECTED"
    )
    f["status"] = "REJECTED"
    touch(f)
    return success_object(_public(f))


@bp.route("/pdm/roster-files/<fid>/supersede", methods=["POST"])
def supersede_file(fid):
    require_roles("DataSteward")
    f = _get_file(fid)
    if f["status"] != "COMMITTED":
        raise invalid_state()
    replacement = any(
        other["roster_source_id"] == f["roster_source_id"]
        and other["id"] != fid
        and other["status"] in ("VALIDATED", "COMMITTED")
        for other in DB.roster_files.values()
    )
    if not replacement:
        raise ApiError(ERR_NO_REPLACEMENT_FILE, 409,
                       "Supersede requires a replacement file in VALIDATED or COMMITTED")
    f["status"] = "SUPERSEDED"
    touch(f)
    return success_object(_public(f))


@bp.route("/pdm/roster-files/<fid>/roster-rows", methods=["GET"])
def list_file_rows(fid):
    require_roles("DataSteward", "IntakeOperator")
    _get_file(fid)
    items = _rows_of(fid)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([_public_row(r) for r in items], request.args)
