"""ComplianceFiling and RECRetirement endpoints (PRD §3.9)."""

from flask import Blueprint, g, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_REFERENCED_NOT_FOUND,
                    ERR_REFERENTIAL_STATE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_UNIQUENESS_CONFLICT, ERR_ZERO_REC_CLAIM)
from serializers import ser_filing, ser_rec
from services import get_or_404, rps_attainment
from store import STORE
from util import as_enum, as_int, as_number, as_str, get_body

bp = Blueprint("filings", __name__)

FILING_TYPES = {"RPS_ANNUAL", "ERRA_FORECAST", "PSD"}
FILING_READERS = ("ComplianceOfficer", "BoardDirector", "UtilityLiaison")
ATTACHABLE = ("DRAFT", "PREPARED", "REVIEWED")


def _present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


@bp.post("/cca/compliance-filings")
@require_roles("ComplianceOfficer")
def create_filing():
    body = get_body(request)
    ftype = as_enum(_present(body, "filing_type"), "filing_type", FILING_TYPES)
    year = as_int(_present(body, "compliance_year"), "compliance_year")
    rec = STORE.new_record()
    rec.update({
        "filing_type": ftype,
        "compliance_year": year,
        "rps_actual_pct": None,
        "rps_shortfall_mwh": None,
        "status": "DRAFT",
        "prepared_by": None,
        "reviewed_by": None,
        "revision_count": 0,
    })
    STORE.filings[rec["id"]] = rec
    return ok_object(ser_filing(rec), status=201)


@bp.get("/cca/compliance-filings")
@require_roles(*FILING_READERS)
def list_filings():
    items = list(STORE.filings.values())
    ft = request.args.get("filing_type")
    if ft is not None:
        items = [f for f in items if f["filing_type"] == ft]
    st = request.args.get("status")
    if st is not None:
        items = [f for f in items if f["status"] == st]
    cy = request.args.get("compliance_year")
    if cy is not None:
        try:
            cy_i = int(cy)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "compliance_year filter must be an integer")
        items = [f for f in items if f["compliance_year"] == cy_i]
    items.sort(key=lambda f: (f["_created_dt"], f["_seq"]))
    return paginate(items, ser_filing)


@bp.get("/cca/compliance-filings/<fid>")
@require_roles(*FILING_READERS)
def get_filing(fid):
    return ok_object(ser_filing(get_or_404(STORE.filings, fid, "ComplianceFiling")))


@bp.get("/cca/compliance-filings/<fid>/rec-retirements")
@require_roles("ComplianceOfficer", "BoardDirector")
def filing_recs(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    items = [r for r in STORE.recs.values() if r["compliance_filing_id"] == filing["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    return paginate(items, ser_rec)


@bp.post("/cca/compliance-filings/<fid>/prepare")
@require_roles("ComplianceOfficer")
def prepare_filing(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be prepared")
    if filing["filing_type"] == "RPS_ANNUAL":
        has_rec = any(r["compliance_filing_id"] == filing["id"]
                      for r in STORE.recs.values())
        if not has_rec:
            raise ApiError(ERR_ZERO_REC_CLAIM, 422,
                           "RPS_ANNUAL filing prepare requires at least one REC retirement")
        pct, shortfall = rps_attainment(filing, STORE.authority())
        filing["rps_actual_pct"] = pct
        filing["rps_shortfall_mwh"] = shortfall
    filing["prepared_by"] = g.user_id
    filing["status"] = "PREPARED"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


@bp.post("/cca/compliance-filings/<fid>/review")
@require_roles("ComplianceOfficer")
def review_filing(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "PREPARED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be reviewed")
    if g.user_id == filing["prepared_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The reviewing officer must differ from the preparing officer")
    filing["reviewed_by"] = g.user_id
    filing["status"] = "REVIEWED"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


@bp.post("/cca/compliance-filings/<fid>/file")
@require_roles("BoardDirector")
def file_filing(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "REVIEWED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be filed")
    filing["status"] = "FILED"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


@bp.post("/cca/compliance-filings/<fid>/cpuc-accept")
@require_roles("UtilityLiaison")
def cpuc_accept(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be accepted")
    filing["status"] = "ACCEPTED_BY_CPUC"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


@bp.post("/cca/compliance-filings/<fid>/cpuc-reject")
@require_roles("UtilityLiaison")
def cpuc_reject(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be rejected")
    filing["status"] = "REJECTED_BY_CPUC"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


@bp.post("/cca/compliance-filings/<fid>/revise")
@require_roles("ComplianceOfficer")
def revise_filing(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "REJECTED_BY_CPUC":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be revised")
    filing["revision_count"] += 1
    filing["prepared_by"] = None
    filing["reviewed_by"] = None
    filing["status"] = "DRAFT"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


@bp.post("/cca/compliance-filings/<fid>/withdraw")
@require_roles("ComplianceOfficer")
def withdraw_filing(fid):
    filing = get_or_404(STORE.filings, fid, "ComplianceFiling")
    if filing["status"] == "ACCEPTED_BY_CPUC":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "ComplianceFiling is ACCEPTED_BY_CPUC (terminal)")
    if filing["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"ComplianceFiling in status {filing['status']} cannot be withdrawn")
    filing["status"] = "WITHDRAWN"
    STORE.touch(filing)
    return ok_object(ser_filing(filing))


# --- REC retirements ----------------------------------------------------------

@bp.post("/cca/rec-retirements")
@require_roles("ComplianceOfficer")
def create_rec():
    body = get_body(request)
    filing_id = body.get("compliance_filing_id")
    if filing_id is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field 'compliance_filing_id'")
    filing = STORE.filings.get(filing_id)
    if filing is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                       f"ComplianceFiling '{filing_id}' not found")
    contract_id = body.get("supply_contract_id")
    if contract_id is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field 'supply_contract_id'")
    contract = STORE.contracts.get(contract_id)
    if contract is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404,
                       f"SupplyContract '{contract_id}' not found")
    # Uniqueness (priority 11) before referential state (priority 12).
    serial = body.get("retirement_serial")
    if isinstance(serial, str):
        for r in STORE.recs.values():
            if r["retirement_serial"] == serial:
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               f"retirement_serial '{serial}' already exists")
    serial = as_str(_present(body, "retirement_serial"), "retirement_serial")
    if filing["filing_type"] != "RPS_ANNUAL":
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       "REC retirements attach only to RPS_ANNUAL filings")
    if filing["status"] not in ATTACHABLE:
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       f"Filing in status {filing['status']} no longer accepts REC retirements")
    if contract["contract_type"] not in ("PPA", "REC_ONLY"):
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       "REC retirements must reference a PPA or REC_ONLY contract")
    mwh = as_number(_present(body, "retired_mwh"), "retired_mwh")
    if float(mwh) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "retired_mwh must be > 0")
    rec = STORE.new_record(with_version=False)
    rec.update({
        "compliance_filing_id": filing["id"],
        "supply_contract_id": contract["id"],
        "retired_mwh": mwh,
        "retirement_serial": serial,
        "retired_on": STORE.now_iso(),
    })
    STORE.recs[rec["id"]] = rec
    return ok_object(ser_rec(rec), status=201)


@bp.get("/cca/rec-retirements")
@require_roles("ComplianceOfficer", "BoardDirector")
def list_recs():
    items = list(STORE.recs.values())
    fid = request.args.get("compliance_filing_id")
    if fid is not None:
        items = [r for r in items if r["compliance_filing_id"] == fid]
    cid = request.args.get("supply_contract_id")
    if cid is not None:
        items = [r for r in items if r["supply_contract_id"] == cid]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    return paginate(items, ser_rec)
