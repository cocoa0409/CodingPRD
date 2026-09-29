"""FundingSource and FundingCommitment endpoints (PRD 3.1, 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

from db import base_row, db, touch
from errors import ApiError
from middleware import authenticate
from response import created, listing, ok, pagination
from services import cascade, lookup, serialize
from validation import Payload, body_fk, raw_body

bp = Blueprint("funding", __name__)

LEVELS = ("FEDERAL", "STATE", "LOCAL")
SOURCE_STATUSES = ("ACTIVE", "FULLY_OBLIGATED", "EXPIRED", "SUSPENDED")
COMMITMENT_STATUSES = ("RESERVED", "OBLIGATED", "DISBURSED", "LAPSED", "RELEASED")
READ_ROLES = ("ProgramAdmin", "AcquisitionOfficer")

SOURCE_FIELDS = (
    "program_id",
    "source_name",
    "level",
    "authorized_cents",
    "obligation_window_start",
    "obligation_window_end",
    "max_share_pct",
    "priority_order",
    "requires_match",
    "match_ratio",
    "fully_obligated_threshold_pct",
)


@bp.post("/funding-sources")
def create_source():
    authenticate(("ProgramAdmin",))
    body = raw_body()
    program = lookup.get_program(body_fk(body, "program_id"))
    payload = Payload(body, SOURCE_FIELDS)
    payload.string("program_id", min_len=1)
    source_name = payload.string("source_name", min_len=1, max_len=160)
    level = payload.enum("level", LEVELS)
    authorized = payload.integer("authorized_cents", minimum=1)
    window_start = payload.instant("obligation_window_start")
    window_end = payload.instant("obligation_window_end")
    max_share = payload.decimal("max_share_pct", exclusive_min=0, maximum=1)
    priority_order = payload.integer("priority_order", minimum=1)
    requires_match = payload.boolean("requires_match", required=False, default=False)
    match_ratio = payload.decimal(
        "match_ratio", required=False, default=Decimal(0), minimum=0
    )
    threshold = payload.decimal(
        "fully_obligated_threshold_pct",
        required=False,
        default=Decimal("0.95"),
        exclusive_min=0,
        maximum=1,
    )
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "obligation_window_end must be strictly after obligation_window_start",
        )
    if not requires_match and match_ratio != Decimal(0):
        raise ApiError(
            "ERR_INVALID_REQUEST", "match_ratio must be 0 when requires_match is false"
        )

    row = base_row()
    row.update(
        {
            "program_id": program["id"],
            "source_name": source_name,
            "level": level,
            "authorized_cents": authorized,
            "obligation_window_start": window_start,
            "obligation_window_end": window_end,
            "max_share_pct": max_share,
            "requires_match": requires_match,
            "match_ratio": match_ratio,
            "fully_obligated_threshold_pct": threshold,
            "priority_order": priority_order,
            "status": "ACTIVE",
            "suspension_reason": None,
        }
    )
    db.funding_sources[row["id"]] = row
    return created(serialize.funding_source(row))


@bp.get("/funding-sources/<source_id>")
def read_source(source_id):
    authenticate(READ_ROLES)
    return ok(serialize.funding_source(lookup.get_funding_source(source_id)))


@bp.get("/funding-sources")
def list_sources():
    authenticate(READ_ROLES)
    limit, offset = pagination(request.args)
    rows = list(db.funding_sources.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    level = request.args.get("level")
    if level is not None:
        if level not in LEVELS:
            raise ApiError("ERR_INVALID_REQUEST", "level filter is not valid")
        rows = [r for r in rows if r["level"] == level]
    status = request.args.get("status")
    if status is not None:
        if status not in SOURCE_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", "status filter is not valid")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["priority_order"], r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.funding_source)


@bp.post("/funding-sources/<source_id>/suspension")
def suspend_source(source_id):
    authenticate(("ProgramAdmin",))
    source = lookup.get_funding_source(source_id)
    payload = Payload(raw_body(), ("reason",))
    reason = payload.string("reason", min_len=1, max_len=500)

    if source["status"] not in ("ACTIVE", "FULLY_OBLIGATED"):
        raise ApiError(
            "ERR_INVALID_SOURCE_STATE",
            "only an ACTIVE or FULLY_OBLIGATED source can be suspended",
        )

    source["status"] = "SUSPENDED"
    source["suspension_reason"] = reason
    touch(source)
    cascade.lapse_reserved_on_source(source, cascade.LAPSE_SOURCE_SUSPENDED)
    return ok(serialize.funding_source(source))


@bp.get("/funding-commitments/<commitment_id>")
def read_commitment(commitment_id):
    authenticate(READ_ROLES)
    return ok(serialize.funding_commitment(lookup.get_commitment(commitment_id)))


@bp.get("/funding-commitments")
def list_commitments():
    authenticate(READ_ROLES)
    limit, offset = pagination(request.args)
    rows = list(db.funding_commitments.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    funding_source_id = request.args.get("funding_source_id")
    if funding_source_id is not None:
        rows = [r for r in rows if r["funding_source_id"] == funding_source_id]
    status = request.args.get("status")
    if status is not None:
        if status not in COMMITMENT_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", "status filter is not valid")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["sweep_order"], r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.funding_commitment)
