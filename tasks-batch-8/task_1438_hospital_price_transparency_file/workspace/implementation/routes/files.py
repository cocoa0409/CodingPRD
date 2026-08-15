"""MachineReadableFile: OCC-guarded generation (seal), cycle-scoped list, and
repeatable schema validation on the parallel generation/validation dimensions."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CYCLE_NOT_FOUND,
    ERR_CYCLE_NOT_FROZEN,
    ERR_FILE_NOT_FOUND,
    ERR_FILE_NOT_SEALED,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import DEID_MIN_PAYERS, payer_count_for_item
from util import (
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_created,
)

bp = Blueprint("files", __name__)

FILE_FORMATS = {"JSON", "CSV"}


def get_file_or_404(fid: str) -> dict:
    f = db.machine_readable_files.get(fid)
    if f is None:
        raise_err(ERR_FILE_NOT_FOUND, "Machine-readable file not found")
    return f


@bp.post("/transparency/machine-readable-files")
@require_roles("TransparencyOfficer")
def generate_file(_user_id: str, _role: str):
    body = get_json_body()
    cycle_id = require_string(body, "publication_cycle_id")
    file_format_raw = require_string(body, "file_format")
    expected_version = require_int(body, "expected_publication_cycle_version")

    # Existence (P3).
    cycle = db.publication_cycles.get(cycle_id)
    if cycle is None:
        raise_err(ERR_CYCLE_NOT_FOUND, "Publication cycle not found")

    # Enum membership after FK existence.
    if file_format_raw not in FILE_FORMATS:
        raise_err(ERR_INVALID_REQUEST, "file_format must be JSON or CSV")

    # OCC (scaffold concurrency rule occ-cycle-file-generate).
    if expected_version != cycle["version"]:
        raise_err(ERR_STALE_VERSION, "PublicationCycle version is stale")

    # State (P4): generation is defined only against a FROZEN cycle.
    if cycle["status"] != "FROZEN":
        raise_err(ERR_CYCLE_NOT_FROZEN, "Files may only be generated for a FROZEN cycle")

    # Snapshot rollup at generation time: VALIDATED records ordered by the
    # item's billing code ASC, tie-break record created_at ASC.
    validated = [r for r in db.standard_charge_records.values()
                 if r["publication_cycle_id"] == cycle_id and r["status"] == "VALIDATED"]

    def _rec_sort_key(r):
        item = db.service_items.get(r["service_item_id"])
        code = item["code"] if item else ""
        return (code, r["created_at"], r["_seq"])

    validated.sort(key=_rec_sort_key)
    record_count = len(validated)
    summary_total = sum(r["discounted_cash_cents"] for r in validated)

    # Regeneration supersedes the prior SEALED file of the same cycle.
    for f in db.machine_readable_files.values():
        if f["publication_cycle_id"] == cycle_id and f["generation_status"] == "SEALED":
            f["generation_status"] = "SUPERSEDED"
            db.bump(f)

    mrf = db.stamp_new({
        "publication_cycle_id": cycle_id,
        "file_format": file_format_raw,
        "generation_status": "SEALED",
        "validation_status": "UNVALIDATED",
        "record_count": record_count,
        "summary_total_discounted_cents": summary_total,
        "validation_errors": [],
    })
    db.machine_readable_files[mrf["id"]] = mrf
    db.bump(cycle)
    return success_object(db.public(mrf), 201)


@bp.get("/transparency/publication-cycles/<cid>/machine-readable-files")
@require_roles(*ALL_ROLES)
def list_cycle_files(cid: str, _user_id: str, _role: str):
    if cid not in db.publication_cycles:
        raise_err(ERR_CYCLE_NOT_FOUND, "Publication cycle not found")
    limit, offset = parse_pagination()
    items = [f for f in db.machine_readable_files.values() if f["publication_cycle_id"] == cid]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(f) for f in page], limit, offset, total)


@bp.post("/transparency/machine-readable-files/<fid>/validate")
@require_roles("TransparencyOfficer")
def validate_file(fid: str, _user_id: str, _role: str):
    mrf = get_file_or_404(fid)

    # Schema validation is defined only on the SEALED generation state
    # (the validation dimension itself loops UNVALIDATED <-> VALID/INVALID).
    if mrf["generation_status"] != "SEALED":
        raise_err(ERR_FILE_NOT_SEALED, "Only a SEALED file can be validated")

    cycle = db.publication_cycles.get(mrf["publication_cycle_id"])
    fac = db.facilities.get(cycle["facility_id"]) if cycle else None
    min_records = fac["min_records_per_cycle"] if fac else 1

    # Rules evaluate LIVE state at validate time, not generation time.
    violations: list[tuple[str, dict | None]] = []
    if mrf["record_count"] < min_records:
        violations.append(("MIN_RECORDS_BELOW_FLOOR", None))

    validated_recs = [r for r in db.standard_charge_records.values()
                      if r["publication_cycle_id"] == mrf["publication_cycle_id"]
                      and r["status"] == "VALIDATED"]
    for rec in validated_recs:
        item = db.service_items.get(rec["service_item_id"])
        if item is not None and item["status"] == "RETIRED":
            violations.append(("RETIRED_ITEM_PRESENT", rec))
        # De-identification: an ACTIVE AGGREGATE_ONLY contract with an ACTIVE
        # rate on the item demands the >=3 distinct-payer floor.
        has_aggregate = False
        for r in db.payer_negotiated_rates.values():
            if r["service_item_id"] != rec["service_item_id"] or r["status"] != "ACTIVE":
                continue
            c = db.payer_contracts.get(r["contract_id"])
            if (
                c is not None
                and c["status"] == "ACTIVE"
                and c["facility_id"] == rec["facility_id"]
                and c["confidentiality_clause"] == "AGGREGATE_ONLY"
            ):
                has_aggregate = True
                break
        if has_aggregate and payer_count_for_item(rec["facility_id"], rec["service_item_id"]) < DEID_MIN_PAYERS:
            violations.append(("DEIDENTIFICATION_VIOLATION", rec))

    # Deterministic order: violation code ASC, then record created_at ASC.
    def _vio_key(v):
        code, rec = v
        return (code, rec["created_at"] if rec else "", rec["_seq"] if rec else 0)

    violations.sort(key=_vio_key)
    codes = [f"{code}:{rec['id']}" if rec is not None else code for code, rec in violations]

    mrf["validation_status"] = "VALID" if not codes else "INVALID"
    mrf["validation_errors"] = codes
    db.bump(mrf)
    if cycle is not None:
        db.bump(cycle)
    return success_object(db.public(mrf), 200)
