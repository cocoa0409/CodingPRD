"""Disclosures, roster entries, inventorship disputes."""
from flask import Blueprint, request

from store import db, create_record, touch, now
from util import (ApiError, require, get_body, check_schema, v_nonempty_str,
                  v_str, v_enum, v_dt, v_int, v_int_range, v_shares,
                  ok_object, ok_list, paginate)
from serializers import ser_disclosure, ser_entry, ser_dispute
from services import SHARE_TOTAL_BP

bp = Blueprint("disclosures", __name__)

RATING_ENUM = ("HIGH", "MEDIUM", "LOW")


def _get_disclosure_or_404(disclosure_id):
    disc = db.disclosures.get(disclosure_id)
    if disc is None:
        raise ApiError("ERR_DISCLOSURE_NOT_FOUND", 404, "Disclosure id does not exist")
    return disc


def _get_entry_or_404(entry_id):
    entry = db.entries.get(entry_id)
    if entry is None:
        raise ApiError("ERR_DISCLOSURE_ENTRY_NOT_FOUND", 404, "DisclosureInventor entry id does not exist")
    return entry


def _get_dispute_or_404(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "InventorshipDispute id does not exist")
    return dispute


def _roster(disclosure_id):
    return [e for e in db.entries.values() if e["disclosure_id"] == disclosure_id]


# ---------------------------------------------------------------------------
# Disclosures
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosures", methods=["POST"])
def create_disclosure():
    uid, _ = require("Inventor")
    if uid not in db.inventors:
        raise ApiError("ERR_INVENTOR_NOT_FOUND", 404, "Inventor id does not exist")
    data = check_schema(get_body(), {
        "title": (True, v_nonempty_str),
        "description": (True, v_str),
        "funding_source": (True, v_enum("FEDERAL", "NON_FEDERAL", "MIXED")),
        "federal_agency": (False, v_str),
        "grant_number": (False, v_str),
        "public_disclosure_date": (False, v_dt),
    })
    if data["funding_source"] in ("FEDERAL", "MIXED"):
        if "federal_agency" not in data or "grant_number" not in data:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "federal_agency and grant_number are required for FEDERAL or MIXED funding")
        federal_agency = data["federal_agency"]
        grant_number = data["grant_number"]
    else:
        federal_agency = None
        grant_number = None
    disc = create_record(db.disclosures, {
        "title": data["title"],
        "description": data["description"],
        "funding_source": data["funding_source"],
        "federal_agency": federal_agency,
        "grant_number": grant_number,
        "public_disclosure_date": data.get("public_disclosure_date"),
        "submitter_inventor_id": uid,
        "status": "INVENTORSHIP_REVIEW",
        "patentability_rating": None,
        "market_rating": None,
        "unreimbursed_cost_cents": 0,
        "written_off_cost_cents": 0,
        "cost_writeoff_review_required": False,
    })
    return ok_object(ser_disclosure(disc), status=201)


@bp.route("/tlo/disclosures", methods=["GET"])
def list_disclosures():
    require()
    records = list(db.disclosures.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        records = [d for d in records if d["status"] == status_filter]
    funding_filter = request.args.get("funding_source")
    if funding_filter is not None:
        records = [d for d in records if d["funding_source"] == funding_filter]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_disclosure(d) for d in page], limit, offset, total)


@bp.route("/tlo/disclosures/<disclosureId>", methods=["GET"])
def get_disclosure(disclosureId):
    require()
    return ok_object(ser_disclosure(_get_disclosure_or_404(disclosureId)))


# ---------------------------------------------------------------------------
# Roster entries
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosures/<disclosureId>/inventors", methods=["POST"])
def add_roster_entry(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "inventor_id": (True, v_nonempty_str),
        "share_bp": (True, v_int_range(1, 10000)),
    })
    if data["inventor_id"] not in db.inventors:
        raise ApiError("ERR_INVENTOR_NOT_FOUND", 404, "Inventor id does not exist")
    if disc["status"] != "INVENTORSHIP_REVIEW":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Roster additions require disclosure status INVENTORSHIP_REVIEW")
    for e in _roster(disc["id"]):
        if e["inventor_id"] == data["inventor_id"]:
            raise ApiError("ERR_DUPLICATE_INVENTOR", 422,
                           "Inventor already on this disclosure's roster")
    entry = create_record(db.entries, {
        "disclosure_id": disc["id"],
        "inventor_id": data["inventor_id"],
        "share_bp": data["share_bp"],
        "confirmation_status": "PENDING",
        "confirmed_at": None,
    })
    touch(disc)
    return ok_object(ser_entry(entry), status=201)


@bp.route("/tlo/disclosures/<disclosureId>/inventors", methods=["GET"])
def list_roster_entries(disclosureId):
    require()
    disc = _get_disclosure_or_404(disclosureId)
    page, limit, offset, total = paginate(_roster(disc["id"]))
    return ok_list([ser_entry(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Disclosure workflow actions
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosures/<disclosureId>/inventorship/finalize", methods=["POST"])
def finalize_inventorship(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "expected_disclosure_version": (True, v_int),
    })
    # PRD §2.8 names the dispute-cycle scenario: a raised dispute advances the
    # disclosure version and moves it to INVENTORSHIP_DISPUTED, and the PRD
    # explicitly says "the finalize is rejected with ERR_STALE_VERSION" in
    # that case. The OCC check therefore runs before the state check.
    if data["expected_disclosure_version"] != disc["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_disclosure_version does not match the disclosure's current version")
    roster = _roster(disc["id"])
    if (disc["status"] != "INVENTORSHIP_REVIEW" or not roster
            or any(e["confirmation_status"] != "CONFIRMED" for e in roster)):
        raise ApiError("ERR_INVENTORSHIP_NOT_FINALIZABLE", 409,
                       "Finalize requires INVENTORSHIP_REVIEW with >=1 entries, all CONFIRMED")
    if sum(e["share_bp"] for e in roster) != SHARE_TOTAL_BP:
        raise ApiError("ERR_SHARE_SUM_INVALID", 409,
                       "Share vector does not sum to exactly 10000 basis points")
    disc["status"] = "INVENTORSHIP_CONFIRMED"
    touch(disc)
    return ok_object(ser_disclosure(disc))


@bp.route("/tlo/disclosures/<disclosureId>/assessment", methods=["POST"])
def record_assessment(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "patentability_rating": (True, v_enum(*RATING_ENUM)),
        "market_rating": (True, v_enum(*RATING_ENUM)),
        "assessment_notes": (False, v_str),
    })
    if disc["status"] != "INVENTORSHIP_CONFIRMED":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Assessment requires disclosure status INVENTORSHIP_CONFIRMED")
    disc["patentability_rating"] = data["patentability_rating"]
    disc["market_rating"] = data["market_rating"]
    disc["status"] = "UNDER_ASSESSMENT"
    touch(disc)
    return ok_object(ser_disclosure(disc))


@bp.route("/tlo/disclosures/<disclosureId>/decision", methods=["POST"])
def record_decision(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "decision": (True, v_enum("PURSUE_PATENT", "WAIVE_TO_INVENTORS", "SHELF")),
        "rationale": (False, v_str),
    })
    if disc["status"] != "UNDER_ASSESSMENT":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Decision requires disclosure status UNDER_ASSESSMENT")
    if data["decision"] == "PURSUE_PATENT":
        if (disc["patentability_rating"] not in ("HIGH", "MEDIUM")
                or disc["market_rating"] not in ("HIGH", "MEDIUM")):
            raise ApiError("ERR_ASSESSMENT_GATE_FAILED", 409,
                           "PURSUE_PATENT requires both ratings in {HIGH, MEDIUM}")
        disc["status"] = "PATENT_PURSUED"
    elif data["decision"] == "WAIVE_TO_INVENTORS":
        disc["status"] = "WAIVED_TO_INVENTORS"
    else:
        disc["status"] = "SHELVED"
    touch(disc)
    return ok_object(ser_disclosure(disc))


@bp.route("/tlo/disclosures/<disclosureId>/cost-review/clear", methods=["POST"])
def clear_cost_review(disclosureId):
    require("TechTransferOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    check_schema(get_body(), {})
    if not disc["cost_writeoff_review_required"]:
        raise ApiError("ERR_COST_REVIEW_NOT_REQUIRED", 409,
                       "cost_writeoff_review_required is false")
    disc["cost_writeoff_review_required"] = False
    db.writeoff_cleared.add(disc["id"])
    touch(disc)
    return ok_object(ser_disclosure(disc))


# ---------------------------------------------------------------------------
# Roster entry top-level actions
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosure-entries/<entryId>", methods=["GET"])
def get_entry(entryId):
    require()
    return ok_object(ser_entry(_get_entry_or_404(entryId)))


@bp.route("/tlo/disclosure-entries/<entryId>/confirm", methods=["POST"])
def confirm_entry(entryId):
    uid, _ = require("Inventor")
    entry = _get_entry_or_404(entryId)
    if uid != entry["inventor_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "An inventor may only confirm their own roster entry")
    check_schema(get_body(), {})
    if entry["confirmation_status"] != "PENDING":
        raise ApiError("ERR_ENTRY_NOT_CONFIRMABLE", 409,
                       "Confirm requires entry confirmation_status PENDING")
    disc = db.disclosures[entry["disclosure_id"]]
    if disc["status"] != "INVENTORSHIP_REVIEW":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Confirm requires disclosure status INVENTORSHIP_REVIEW")
    entry["confirmation_status"] = "CONFIRMED"
    entry["confirmed_at"] = now()
    touch(entry)
    return ok_object(ser_entry(entry))


@bp.route("/tlo/disclosure-entries/<entryId>/dispute", methods=["POST"])
def dispute_entry(entryId):
    uid, _ = require("Inventor")
    entry = _get_entry_or_404(entryId)
    disc = db.disclosures[entry["disclosure_id"]]
    if not any(e["inventor_id"] == uid for e in _roster(disc["id"])):
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only an inventor on this disclosure's roster may raise a dispute")
    data = check_schema(get_body(), {"reason": (True, v_str)})
    if entry["confirmation_status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_ENTRY_NOT_DISPUTABLE", 409,
                       "Dispute requires entry confirmation_status PENDING or CONFIRMED")
    if disc["status"] not in ("INVENTORSHIP_REVIEW", "INVENTORSHIP_DISPUTED"):
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "Dispute requires the disclosure to be in inventorship review")
    entry["confirmation_status"] = "DISPUTED"
    entry["confirmed_at"] = None
    touch(entry)
    dispute = create_record(db.disputes, {
        "disclosure_id": disc["id"],
        "entry_id": entry["id"],
        "raised_by_inventor_id": uid,
        "reason": data["reason"],
        "status": "OPEN",
        "resolution_notes": None,
    })
    disc["status"] = "INVENTORSHIP_DISPUTED"
    touch(disc)
    return ok_object(ser_dispute(dispute), status=201)


@bp.route("/tlo/disclosure-entries/<entryId>/disputes", methods=["GET"])
def list_entry_disputes(entryId):
    require()
    entry = _get_entry_or_404(entryId)
    records = [d for d in db.disputes.values() if d["entry_id"] == entry["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_dispute(d) for d in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Inventorship disputes
# ---------------------------------------------------------------------------

@bp.route("/tlo/inventorship-disputes", methods=["GET"])
def list_disputes():
    require()
    records = list(db.disputes.values())
    disc_filter = request.args.get("disclosure_id")
    if disc_filter is not None:
        records = [d for d in records if d["disclosure_id"] == disc_filter]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_dispute(d) for d in page], limit, offset, total)


@bp.route("/tlo/inventorship-disputes/<disputeId>", methods=["GET"])
def get_dispute(disputeId):
    require()
    return ok_object(ser_dispute(_get_dispute_or_404(disputeId)))


@bp.route("/tlo/inventorship-disputes/<disputeId>/resolve", methods=["POST"])
def resolve_dispute(disputeId):
    require("TechTransferOfficer")
    dispute = _get_dispute_or_404(disputeId)
    data = check_schema(get_body(), {
        "resolution_notes": (True, v_str),
        "adjusted_shares": (True, v_shares),
    })
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_NOT_OPEN", 409, "Resolve requires dispute status OPEN")
    disc = db.disclosures[dispute["disclosure_id"]]
    roster = _roster(disc["id"])
    roster_ids = [e["id"] for e in roster]
    vector_ids = [s["entry_id"] for s in data["adjusted_shares"]]
    if (len(vector_ids) != len(roster_ids)
            or len(set(vector_ids)) != len(vector_ids)
            or set(vector_ids) != set(roster_ids)
            or sum(s["share_bp"] for s in data["adjusted_shares"]) != SHARE_TOTAL_BP):
        raise ApiError("ERR_SHARE_SUM_INVALID", 409,
                       "adjusted_shares must name every roster entry exactly once and sum to 10000")
    share_by_id = {s["entry_id"]: s["share_bp"] for s in data["adjusted_shares"]}
    for e in roster:
        e["share_bp"] = share_by_id[e["id"]]
        e["confirmation_status"] = "PENDING"
        e["confirmed_at"] = None
        touch(e)
    dispute["status"] = "RESOLVED"
    dispute["resolution_notes"] = data["resolution_notes"]
    touch(dispute)
    disc["status"] = "INVENTORSHIP_REVIEW"
    touch(disc)
    return ok_object(ser_dispute(dispute))
