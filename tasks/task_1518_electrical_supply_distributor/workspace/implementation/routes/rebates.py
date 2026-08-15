"""RebateProgram and RebateClaim endpoints (PRD §3.9)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from db import clock_date, new_record, sort_key, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_REBATE_PROGRAM_NOT_FOUND,
    ERR_REBATE_CLAIM_NOT_FOUND,
    ERR_REBATE_PERIOD_OVERLAP,
    ERR_REBATE_CLAIM_NOT_DRAFT,
    ERR_REBATE_CLAIM_NOT_SUBMITTED,
    ERR_REBATE_PERIOD_NOT_ENDED,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_rebate_claim, ser_rebate_program
from util import (
    get_json_body,
    is_int,
    paginate,
    parse_date,
    require_date,
    require_string,
    to_decimal,
)

bp = Blueprint("rebates", __name__, url_prefix="/distributor")

_CENT = Decimal("1")


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


def _qualifying_lines(program: dict) -> list:
    """Release lines qualifying for the program: release INVOICED with
    invoiced_on inside the closed period and an exact manufacturer match."""
    out = []
    for release in db.releases.values():
        if release["status"] != "INVOICED":
            continue
        invoiced_on = release["invoiced_on"]
        if invoiced_on is None:
            continue
        if not (program["period_start"] <= invoiced_on <= program["period_end"]):
            continue
        for line in db.release_lines.values():
            if line["release_id"] != release["id"] or line["billed_amount_cents"] is None:
                continue
            item = db.catalog_items[line["catalog_item_id"]]
            if item["manufacturer_name"] == program["manufacturer_name"]:
                out.append(line)
    return out


def _achieved_pct(program: dict, qualifying_base_cents: int) -> Decimal:
    """Last tier (ascending threshold) with threshold <= base; else 0."""
    pct = Decimal(0)
    for tier in program["tiers"]:
        if tier["threshold_cents"] <= qualifying_base_cents:
            pct = tier["rebate_pct"]
    return pct


# ---------------------------------------------------------------------------
# RebateProgram
# ---------------------------------------------------------------------------


@bp.post("/rebate-programs")
@require_roles("RebateClerk")
@atomic
def create_rebate_program():
    body = get_json_body()
    manufacturer_name = require_string(body, "manufacturer_name")
    period_start = require_date(body, "period_start")
    period_end = require_date(body, "period_end")
    raw_tiers = body.get("tiers")
    if not isinstance(raw_tiers, list):
        raise_err(ERR_INVALID_REQUEST, "tiers must be an array of {threshold_cents, rebate_pct}")
    tiers = []
    for entry in raw_tiers:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "each tier must be an object with threshold_cents and rebate_pct")
        threshold = entry.get("threshold_cents")
        if not is_int(threshold) or threshold < 0:
            raise_err(ERR_INVALID_REQUEST, "tier threshold_cents must be a non-negative integer")
        pct = to_decimal(entry.get("rebate_pct"))
        if pct is None or pct < 0:
            raise_err(ERR_INVALID_REQUEST, "tier rebate_pct must be a non-negative number")
        tiers.append({"threshold_cents": threshold, "rebate_pct": pct})
    if parse_date(period_end) < parse_date(period_start):
        raise_err(ERR_INVALID_REQUEST, "period_end must be >= period_start")

    # Closed-interval overlap per manufacturer; shared boundary dates conflict.
    for other in db.rebate_programs.values():
        if other["manufacturer_name"] != manufacturer_name:
            continue
        if period_start <= other["period_end"] and other["period_start"] <= period_end:
            raise_err(ERR_REBATE_PERIOD_OVERLAP, "Same-manufacturer program period overlaps an existing program")

    tiers.sort(key=lambda t: t["threshold_cents"])
    program = new_record(
        {
            "manufacturer_name": manufacturer_name,
            "period_start": period_start,
            "period_end": period_end,
            "tiers": tiers,
        }
    )
    db.rebate_programs[program["id"]] = program
    return success_object(ser_rebate_program(program), 201)


@bp.get("/rebate-programs")
@require_roles(*ROLES)
def list_rebate_programs():
    manufacturer = _query_arg("manufacturer_name")
    items = sorted(db.rebate_programs.values(), key=sort_key)
    if manufacturer is not None:
        items = [p for p in items if p["manufacturer_name"] == manufacturer]
    page, limit, offset, total = paginate(items)
    return success_list([ser_rebate_program(p) for p in page], limit, offset, total)


@bp.get("/rebate-programs/<program_id>")
@require_roles(*ROLES)
def get_rebate_program(program_id: str):
    program = db.rebate_programs.get(program_id)
    if program is None:
        raise_err(ERR_REBATE_PROGRAM_NOT_FOUND, "No rebate program with the given id")
    return success_object(ser_rebate_program(program))


# ---------------------------------------------------------------------------
# RebateClaim
# ---------------------------------------------------------------------------


@bp.post("/rebate-claims")
@require_roles("RebateClerk")
@atomic
def create_rebate_claim():
    body = get_json_body()
    rebate_program_id = require_string(body, "rebate_program_id")
    program = db.rebate_programs.get(rebate_program_id)
    if program is None:
        raise_err(ERR_REBATE_PROGRAM_NOT_FOUND, "No rebate program with the given id")

    # Provisional accrual: one rounding applied to the SUM (PRD §3.9).
    lines = _qualifying_lines(program)
    base = sum(l["billed_amount_cents"] for l in lines)
    pct = _achieved_pct(program, base)
    provisional = int((Decimal(base) * pct).quantize(_CENT, rounding=ROUND_HALF_UP))

    claim = new_record(
        {
            "rebate_program_id": rebate_program_id,
            "status": "DRAFT",
            "provisional_amount_cents": provisional,
            "qualifying_base_cents": None,
            "tier_pct_applied": None,
            "final_amount_cents": None,
        }
    )
    db.rebate_claims[claim["id"]] = claim
    return success_object(ser_rebate_claim(claim), 201)


@bp.get("/rebate-claims")
@require_roles(*ROLES)
def list_rebate_claims():
    rebate_program_id = _query_arg("rebate_program_id")
    status = _query_arg("status")
    items = sorted(db.rebate_claims.values(), key=sort_key)
    if rebate_program_id is not None:
        items = [c for c in items if c["rebate_program_id"] == rebate_program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_rebate_claim(c) for c in page], limit, offset, total)


@bp.get("/rebate-claims/<claim_id>")
@require_roles(*ROLES)
def get_rebate_claim(claim_id: str):
    claim = db.rebate_claims.get(claim_id)
    if claim is None:
        raise_err(ERR_REBATE_CLAIM_NOT_FOUND, "No rebate claim with the given id")
    return success_object(ser_rebate_claim(claim))


@bp.post("/rebate-claims/<claim_id>/submit")
@require_roles("RebateClerk")
@atomic
def submit_rebate_claim(claim_id: str):
    claim = db.rebate_claims.get(claim_id)
    if claim is None:
        raise_err(ERR_REBATE_CLAIM_NOT_FOUND, "No rebate claim with the given id")
    if claim["status"] != "DRAFT":
        raise_err(ERR_REBATE_CLAIM_NOT_DRAFT, "Submit requires the claim in DRAFT")
    program = db.rebate_programs[claim["rebate_program_id"]]
    if clock_date() <= parse_date(program["period_end"]):
        raise_err(ERR_REBATE_PERIOD_NOT_ENDED, "Claim submit requires the logical clock date to be after the program period_end")

    # Final variant: round half-up PER LINE, then sum (pinned order).
    lines = _qualifying_lines(program)
    base = sum(l["billed_amount_cents"] for l in lines)
    pct = _achieved_pct(program, base)
    final = sum(
        int((Decimal(l["billed_amount_cents"]) * pct).quantize(_CENT, rounding=ROUND_HALF_UP))
        for l in lines
    )
    claim["qualifying_base_cents"] = base
    claim["tier_pct_applied"] = pct
    claim["final_amount_cents"] = final
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success_object(ser_rebate_claim(claim))


@bp.post("/rebate-claims/<claim_id>/decide")
@require_roles("BranchManager")
@atomic
def decide_rebate_claim(claim_id: str):
    body = get_json_body()
    decision = require_string(body, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_err(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    claim = db.rebate_claims.get(claim_id)
    if claim is None:
        raise_err(ERR_REBATE_CLAIM_NOT_FOUND, "No rebate claim with the given id")
    if claim["status"] != "SUBMITTED":
        raise_err(ERR_REBATE_CLAIM_NOT_SUBMITTED, "Decide requires the claim in SUBMITTED")
    claim["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(claim)
    return success_object(ser_rebate_claim(claim))
