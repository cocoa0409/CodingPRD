"""Sublet agreements (PRD §3.7) and alteration agreements (PRD §3.8)."""
from flask import request

import domain as D
from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_NOT_RESOURCE_OWNER,
    ERR_TEMPORAL_CONFLICT,
    ERR_CROSS_ENTITY_VIOLATION,
    ERR_SUBLET_POLICY_VIOLATION,
    ERR_ALTERATION_SAFETY_VIOLATION,
)
from middleware import ctx, require_role, ALL_ROLES
from response import ok
from util import get_body, req_str, req_int, req_bool, req_dt, add_years
from routes.core import bp, list_response

READ_ALL = list(ALL_ROLES)


def _check_owner(resource, uid):
    if uid != resource["shareholder_id"]:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Caller is not the owning shareholder", 403)


def _get_shareholder_or_422(cid, sh_id):
    sh = STORE["shareholders"].get(sh_id)
    if sh is None or sh["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced shareholder does not exist", 422)
    return sh


def _get_unit_or_422(cid, unit_id):
    unit = STORE["units"].get(unit_id)
    if unit is None or unit["cooperative_id"] != cid:
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Referenced unit does not exist", 422)
    return unit


# ---------------------------------------------------------------------------
# Sublet agreements
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/sublet-agreements")
def create_sublet(cid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    body = get_body()
    unit_id = req_str(body, "unit_id")
    shareholder_id = req_str(body, "shareholder_id")
    subtenant_name = req_str(body, "subtenant_name")
    start = req_dt(body, "sublet_start_date")
    end = req_dt(body, "sublet_end_date")
    if uid != shareholder_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "X-User-ID must equal shareholder_id", 403)
    _get_unit_or_422(cid, unit_id)
    _get_shareholder_or_422(cid, shareholder_id)
    s = D.make(
        "sublet_agreements", coop,
        cooperative_id=cid,
        unit_id=unit_id,
        shareholder_id=shareholder_id,
        subtenant_name=subtenant_name,
        sublet_start_date=start,
        sublet_end_date=end,
        monthly_sublet_fee_cents=None,
        sublet_status="DRAFT",
    )
    return ok(D.ser(s), 201)


@bp.get("/cooperatives/<cid>/sublet-agreements")
def list_sublets(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("sublet_agreements", cid, [
        ("unit_id", request.args.get("unit_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("sublet_status", request.args.get("sublet_status"), False),
    ])


@bp.get("/cooperatives/<cid>/sublet-agreements/<sid>")
def get_sublet(cid, sid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    s = D.get_scoped("sublet_agreements", sid, cid, "SubletAgreement")
    return ok(D.ser(s))


@bp.post("/cooperatives/<cid>/sublet-agreements/<sid>/submit")
def submit_sublet(cid, sid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    s = D.get_scoped("sublet_agreements", sid, cid, "SubletAgreement")
    _check_owner(s, uid)
    if s["sublet_status"] in ("COMPLETED", "REJECTED", "TERMINATED_EARLY"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Sublet is in terminal state", 409)
    if s["sublet_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Sublet is not DRAFT", 409)
    sh = STORE["shareholders"].get(s["shareholder_id"])
    if sh is None or sh["standing"] != "GOOD_STANDING":
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Shareholder is not in GOOD_STANDING", 422)
    if s["sublet_start_date"] >= s["sublet_end_date"]:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "sublet_start_date must be before sublet_end_date", 422)
    overlap = any(
        o for o in STORE["sublet_agreements"].values()
        if o["cooperative_id"] == cid
        and o["unit_id"] == s["unit_id"]
        and o["id"] != s["id"]
        and o["sublet_status"] in ("SUBMITTED", "APPROVED", "ACTIVE")
        and D.windows_overlap(o["sublet_start_date"], o["sublet_end_date"],
                              s["sublet_start_date"], s["sublet_end_date"])
    )
    if overlap:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "Sublet window overlaps another sublet", 422)
    unit = STORE["units"].get(s["unit_id"])
    if unit is not None and unit["occupancy_status"] == "SUBLET":
        raise ApiError(ERR_SUBLET_POLICY_VIOLATION, "Unit is already sublet", 422)
    if s["sublet_end_date"] > add_years(s["sublet_start_date"], coop["sublet_policy_years_max"]):
        raise ApiError(
            ERR_SUBLET_POLICY_VIOLATION,
            "Sublet exceeds the %d-year maximum" % coop["sublet_policy_years_max"],
            422,
        )
    if unit is not None and unit["last_sublet_end_date"] is not None:
        earliest = add_years(unit["last_sublet_end_date"], coop["sublet_policy_gap_years"])
        if s["sublet_start_date"] < earliest:
            raise ApiError(
                ERR_SUBLET_POLICY_VIOLATION,
                "Owner-occupancy gap of %d year(s) not honored" % coop["sublet_policy_gap_years"],
                422,
            )
    s["sublet_status"] = "SUBMITTED"
    D.touch(s, coop)
    return ok(D.ser(s))


@bp.post("/cooperatives/<cid>/sublet-agreements/<sid>/reject")
def reject_sublet(cid, sid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    s = D.get_scoped("sublet_agreements", sid, cid, "SubletAgreement")
    if s["sublet_status"] in ("COMPLETED", "REJECTED", "TERMINATED_EARLY"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Sublet is in terminal state", 409)
    if s["sublet_status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, "Only SUBMITTED or APPROVED sublets can be rejected", 409)
    s["sublet_status"] = "REJECTED"
    D.touch(s, coop)
    return ok(D.ser(s))


@bp.post("/cooperatives/<cid>/sublet-agreements/<sid>/terminate-early")
def terminate_sublet(cid, sid):
    uid, role = ctx()
    require_role(role, ["BoardOfficer"])
    coop = D.get_coop(cid)
    s = D.get_scoped("sublet_agreements", sid, cid, "SubletAgreement")
    if s["sublet_status"] in ("COMPLETED", "REJECTED", "TERMINATED_EARLY"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Sublet is in terminal state", 409)
    if s["sublet_status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, "Only APPROVED or ACTIVE sublets can be terminated", 409)
    now = coop["current_utc"]
    s["sublet_status"] = "TERMINATED_EARLY"
    D.touch(s, coop)
    unit = STORE["units"].get(s["unit_id"])
    if unit is not None:
        unit["occupancy_status"] = "OWNER_OCCUPIED"
        unit["last_sublet_end_date"] = now
        D.touch(unit, coop)
    return ok(D.ser(s))


# ---------------------------------------------------------------------------
# Alteration agreements
# ---------------------------------------------------------------------------

@bp.post("/cooperatives/<cid>/alteration-agreements")
def create_alteration(cid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    body = get_body()
    unit_id = req_str(body, "unit_id")
    shareholder_id = req_str(body, "shareholder_id")
    scope = req_str(body, "scope_description")
    contractor = req_str(body, "contractor_name")
    insurance = req_int(body, "contractor_insurance_cents")
    window_start = req_dt(body, "work_window_start")
    window_end = req_dt(body, "work_window_end")
    bid = req_int(body, "contractor_bid_cents")
    wet = req_bool(body, "involves_wet_over_dry")
    if uid != shareholder_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "X-User-ID must equal shareholder_id", 403)
    _get_unit_or_422(cid, unit_id)
    _get_shareholder_or_422(cid, shareholder_id)
    a = D.make(
        "alteration_agreements", coop,
        cooperative_id=cid,
        unit_id=unit_id,
        shareholder_id=shareholder_id,
        scope_description=scope,
        contractor_name=contractor,
        contractor_insurance_cents=insurance,
        work_window_start=window_start,
        work_window_end=window_end,
        security_deposit_cents=None,
        contractor_bid_cents=bid,
        involves_wet_over_dry=wet,
        alteration_status="DRAFT",
    )
    return ok(D.ser(a), 201)


@bp.get("/cooperatives/<cid>/alteration-agreements")
def list_alterations(cid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    return list_response("alteration_agreements", cid, [
        ("unit_id", request.args.get("unit_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("alteration_status", request.args.get("alteration_status"), False),
    ])


@bp.get("/cooperatives/<cid>/alteration-agreements/<aid>")
def get_alteration(cid, aid):
    uid, role = ctx()
    require_role(role, READ_ALL)
    D.get_coop(cid)
    a = D.get_scoped("alteration_agreements", aid, cid, "AlterationAgreement")
    return ok(D.ser(a))


@bp.post("/cooperatives/<cid>/alteration-agreements/<aid>/submit")
def submit_alteration(cid, aid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    a = D.get_scoped("alteration_agreements", aid, cid, "AlterationAgreement")
    _check_owner(a, uid)
    if a["alteration_status"] in ("COMPLETED", "REJECTED", "ABANDONED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Alteration is in terminal state", 409)
    if a["alteration_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Alteration is not DRAFT", 409)
    # Alteration safety (priority 6) precedes cross-entity checks (priority 7).
    if a["contractor_insurance_cents"] < D.ALTERATION_MIN_INSURANCE_CENTS:
        raise ApiError(
            ERR_ALTERATION_SAFETY_VIOLATION,
            "Contractor insurance below the $1M minimum",
            422,
        )
    sh = STORE["shareholders"].get(a["shareholder_id"])
    if sh is None or sh["standing"] != "GOOD_STANDING":
        raise ApiError(ERR_CROSS_ENTITY_VIOLATION, "Shareholder is not in GOOD_STANDING", 422)
    if a["work_window_start"] >= a["work_window_end"]:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "work_window_start must be before work_window_end", 422)
    overlap = any(
        o for o in STORE["alteration_agreements"].values()
        if o["cooperative_id"] == cid
        and o["unit_id"] == a["unit_id"]
        and o["id"] != a["id"]
        and o["alteration_status"] in ("APPROVED", "IN_PROGRESS")
        and D.windows_overlap(o["work_window_start"], o["work_window_end"],
                              a["work_window_start"], a["work_window_end"])
    )
    if overlap:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "Work window overlaps another alteration", 422)
    # Refundable deposit: max(ceil(5% of bid), $5k).
    five_pct = (a["contractor_bid_cents"] * 5 + 99) // 100
    a["security_deposit_cents"] = max(five_pct, D.ALTERATION_MIN_DEPOSIT_CENTS)
    a["alteration_status"] = "SUBMITTED"
    D.touch(a, coop)
    return ok(D.ser(a))


@bp.post("/cooperatives/<cid>/alteration-agreements/<aid>/start-work")
def start_work(cid, aid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    a = D.get_scoped("alteration_agreements", aid, cid, "AlterationAgreement")
    _check_owner(a, uid)
    if a["alteration_status"] in ("COMPLETED", "REJECTED", "ABANDONED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Alteration is in terminal state", 409)
    if a["alteration_status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Alteration is not APPROVED", 409)
    now = coop["current_utc"]
    if now < a["work_window_start"] or now >= a["work_window_end"]:
        raise ApiError(ERR_TEMPORAL_CONFLICT, "Outside the permitted work window", 422)
    a["alteration_status"] = "IN_PROGRESS"
    D.touch(a, coop)
    return ok(D.ser(a))


@bp.post("/cooperatives/<cid>/alteration-agreements/<aid>/complete")
def complete_alteration(cid, aid):
    uid, role = ctx()
    require_role(role, ["Shareholder"])
    coop = D.get_coop(cid)
    a = D.get_scoped("alteration_agreements", aid, cid, "AlterationAgreement")
    _check_owner(a, uid)
    if a["alteration_status"] in ("COMPLETED", "REJECTED", "ABANDONED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Alteration is in terminal state", 409)
    if a["alteration_status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Alteration is not IN_PROGRESS", 409)
    a["alteration_status"] = "COMPLETED"
    D.touch(a, coop)
    return ok(D.ser(a))


@bp.post("/cooperatives/<cid>/alteration-agreements/<aid>/abandon")
def abandon_alteration(cid, aid):
    uid, role = ctx()
    require_role(role, ["Shareholder", "BoardOfficer"])
    coop = D.get_coop(cid)
    a = D.get_scoped("alteration_agreements", aid, cid, "AlterationAgreement")
    if role == "Shareholder":
        _check_owner(a, uid)
    if a["alteration_status"] in ("COMPLETED", "REJECTED", "ABANDONED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Alteration is in terminal state", 409)
    if a["alteration_status"] not in ("APPROVED", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE, "Only APPROVED or IN_PROGRESS alterations can be abandoned", 409)
    a["alteration_status"] = "ABANDONED"
    D.touch(a, coop)
    return ok(D.ser(a))
