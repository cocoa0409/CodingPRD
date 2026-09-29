"""Inter-agency discrepancy negotiation, adoption and arbitration."""

from flask import Blueprint

import calc
import cascade
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import append_only_record, base_record, db, sorted_rows, touch

bp = Blueprint("disc", __name__)

SUBJECT_TYPES = ["ROAD_NAME", "ADDRESS_RANGE", "BOUNDARY_CELL"]
CASE_STATUSES = ["OPEN", "PROPOSAL_PENDING", "COUNTERED", "ESCALATED", "CONCURRED",
                 "ADOPTED", "ARBITRATED"]
SIDES = ["OPENER", "COUNTERPARTY"]
PROPOSAL_STATUSES = ["PENDING", "COUNTERED", "ADOPTED", "VOIDED"]
NEGOTIATING = ("OPEN", "PROPOSAL_PENDING", "COUNTERED")


def _acting_side(case, user_id):
    if user_id == case["opened_by_agency_id"]:
        return "OPENER"
    if user_id == case["counterparty_agency_id"]:
        return "COUNTERPARTY"
    raise ApiError("ERR_AGENCY_IDENTITY_MISMATCH",
                   "Only the two parties to this case may act on it.")


@bp.post("/discrepancy-cases")
def create_case():
    user_id, _role = v.auth(["AgencyLiaison"])
    data = v.body()
    subject_type = v.req_enum(data, "subject_type", SUBJECT_TYPES)
    subject_kind = "cell" if subject_type == "BOUNDARY_CELL" else "road"
    subject = v.maybe_find(subject_kind, v.raw_ref(data, "subject_ref_id"))
    counterparty = v.maybe_find("agency", v.raw_ref(data, "counterparty_agency_id"))
    v.req_id(data, "subject_ref_id")
    v.req_id(data, "counterparty_agency_id")
    description = v.req_str(data, "description", 1, 500)

    opener = db.agencies.get(user_id)
    if opener is None:
        raise ApiError("ERR_AGENCY_IDENTITY_MISMATCH",
                       "The acting X-User-ID does not name a responding agency.")

    if counterparty["id"] == opener["id"]:
        raise ApiError("ERR_COUNTERPARTY_INVALID",
                       "An agency may not open a case against itself.")
    if counterparty["jurisdiction_id"] != subject["jurisdiction_id"]:
        raise ApiError("ERR_COUNTERPARTY_INVALID",
                       "The counterparty is chartered in another jurisdiction.")
    if opener["status"] != "ACTIVE" or counterparty["status"] != "ACTIVE":
        raise ApiError("ERR_AGENCY_NOT_ACTIVE",
                       "A suspended agency may not be a party to a new discrepancy case.")
    for row in db.cases.values():
        if row["subject_type"] != subject_type or row["subject_ref_id"] != subject["id"]:
            continue
        if row["status"] not in ("ADOPTED", "ARBITRATED"):
            raise ApiError("ERR_SUBJECT_CASE_ALREADY_OPEN",
                           "An unresolved case already exists on this subject.")

    row = base_record()
    row.update({
        "subject_type": subject_type,
        "subject_ref_id": subject["id"],
        "jurisdiction_id": subject["jurisdiction_id"],
        "opened_by_agency_id": opener["id"],
        "counterparty_agency_id": counterparty["id"],
        "description": description,
        "status": "OPEN",
        "concurred_by_side": None,
        "resolved_value": None,
        "escalated_at": None,
        "adopted_at": None,
    })
    db.cases[row["id"]] = row
    return created(ser.case(row))


@bp.get("/discrepancy-cases/<identifier>")
def get_case(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("case", identifier)
    return ok(ser.case(row))


@bp.get("/discrepancy-cases")
def list_cases():
    v.auth(v.ALL_ROLES)
    opened_by = v.q_str("opened_by_agency_id")
    if opened_by is not None:
        v.find("agency", opened_by)
    counterparty_id = v.q_str("counterparty_agency_id")
    if counterparty_id is not None:
        v.find("agency", counterparty_id)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    proposal_id = v.q_str("current_proposal_id")
    if proposal_id is not None:
        v.find("proposal", proposal_id)
    subject_type = v.q_enum("subject_type", SUBJECT_TYPES)
    subject_ref_id = v.q_str("subject_ref_id")
    status = v.q_enum("status", CASE_STATUSES)
    limit, offset = v.pagination()

    rows = sorted_rows(list(db.cases.values()))
    if opened_by is not None:
        rows = [r for r in rows if r["opened_by_agency_id"] == opened_by]
    if counterparty_id is not None:
        rows = [r for r in rows if r["counterparty_agency_id"] == counterparty_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if proposal_id is not None:
        rows = [r for r in rows
                if calc.case_current_proposal(r["id"]) is not None
                and calc.case_current_proposal(r["id"])["id"] == proposal_id]
    if subject_type is not None:
        rows = [r for r in rows if r["subject_type"] == subject_type]
    if subject_ref_id is not None:
        rows = [r for r in rows if r["subject_ref_id"] == subject_ref_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.case(r) for r in page], limit, offset, total)


@bp.post("/discrepancy-cases/<identifier>/proposals")
def file_proposal(identifier):
    user_id, _role = v.auth(["AgencyLiaison"])
    case = v.find("case", identifier)
    side = _acting_side(case, user_id)
    data = v.body()
    proposed_value = v.req_str(data, "proposed_value", 1, 120)
    expected = v.req_int(data, "expected_case_version")
    rationale = v.opt_str(data, "rationale", 0, 500)

    if case["status"] not in NEGOTIATING:
        raise ApiError("ERR_CASE_INVALID_STATE",
                       "A case whose status is %s accepts no further proposals."
                       % case["status"])
    if expected != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION",
                       "expected_case_version %d does not match the stored version %d."
                       % (expected, case["version"]))
    current = calc.case_current_proposal(case["id"])
    if current is not None and current["proposed_by_side"] == side:
        raise ApiError("ERR_SELF_CONCURRENCE",
                       "An agency may not counter its own pending proposal.")

    prior_rounds = calc.case_round_count(case["id"])
    row = append_only_record()
    row.update({
        "case_id": case["id"],
        "round_number": prior_rounds + 1,
        "proposed_by_side": side,
        "proposed_value": proposed_value,
        "rationale": rationale,
    })
    db.proposals[row["id"]] = row

    if prior_rounds >= calc.MAX_PROPOSAL_ROUNDS:
        case["status"] = "ESCALATED"
        case["escalated_at"] = db.now()
    elif case["status"] in ("OPEN", "COUNTERED"):
        case["status"] = "PROPOSAL_PENDING"
    else:
        case["status"] = "COUNTERED"
    touch(case)
    return created(ser.proposal(row))


@bp.get("/discrepancy-cases/<identifier>/proposals")
def list_proposals(identifier):
    v.auth(v.ALL_ROLES)
    case = v.find("case", identifier)
    side = v.q_enum("proposed_by_side", SIDES)
    status = v.q_enum("status", PROPOSAL_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows([p for p in db.proposals.values() if p["case_id"] == case["id"]])
    if side is not None:
        rows = [r for r in rows if r["proposed_by_side"] == side]
    if status is not None:
        rows = [r for r in rows if calc.proposal_status(r) == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.proposal(r) for r in page], limit, offset, total)


@bp.post("/discrepancy-cases/<identifier>/concur")
def concur(identifier):
    user_id, _role = v.auth(["AgencyLiaison"])
    case = v.find("case", identifier)
    side = _acting_side(case, user_id)
    data = v.body()
    proposal = v.maybe_find("proposal", v.raw_ref(data, "proposal_id"))
    v.req_id(data, "proposal_id")

    if case["status"] not in ("PROPOSAL_PENDING", "COUNTERED"):
        raise ApiError("ERR_CASE_INVALID_STATE",
                       "A case whose status is %s cannot be concurred with." % case["status"])
    current = calc.case_current_proposal(case["id"])
    if current is None or proposal["id"] != current["id"] \
            or calc.proposal_status(proposal) != "PENDING":
        raise ApiError("ERR_CASE_INVALID_STATE",
                       "Only the case's current PENDING proposal may be concurred with.")
    if current["proposed_by_side"] == side:
        raise ApiError("ERR_SELF_CONCURRENCE",
                       "An agency may not concur with its own proposal.")

    case["status"] = "CONCURRED"
    case["concurred_by_side"] = side
    touch(case)
    return ok(ser.case(case))


@bp.post("/discrepancy-cases/<identifier>/adopt")
def adopt(identifier):
    v.auth(["SystemAdmin"])
    case = v.find("case", identifier)
    if case["status"] != "CONCURRED":
        raise ApiError("ERR_CASE_INVALID_STATE",
                       "Only a CONCURRED case may be adopted; this one is %s." % case["status"])
    current = calc.case_current_proposal(case["id"])
    if current is None:
        raise ApiError("ERR_CASE_INVALID_STATE", "The case holds no proposal to adopt.")

    resolved_value = current["proposed_value"]
    case["resolved_value"] = resolved_value
    case["adopted_at"] = db.now()
    case["status"] = "ADOPTED"
    touch(case)
    cascade.resolution_cascade(case, resolved_value)
    return ok(ser.case(case))


@bp.post("/discrepancy-cases/<identifier>/arbitrate")
def arbitrate(identifier):
    v.auth(["SystemAdmin"])
    case = v.find("case", identifier)
    data = v.body()
    arbitration_value = v.req_str(data, "arbitration_value", 1, 120)
    v.opt_str(data, "rationale", 0, 500)
    if case["status"] != "ESCALATED":
        raise ApiError("ERR_CASE_INVALID_STATE",
                       "Only an ESCALATED case may be arbitrated; this one is %s."
                       % case["status"])

    case["resolved_value"] = arbitration_value
    case["adopted_at"] = db.now()
    case["status"] = "ARBITRATED"
    touch(case)
    cascade.resolution_cascade(case, arbitration_value)
    return ok(ser.case(case))
