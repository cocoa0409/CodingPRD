"""Record construction, common-field management, serialization, and lookups.

Common system-managed fields (PRD §2.4):
  id, created_at, updated_at, version  — carried by every entity EXCEPT NiceClass
  (an immutable reference record carrying only id + created_at).

A "mutation" (state advance or derived-field recompute, including server-initiated
sweeps/cascades) refreshes updated_at and increments version by one.
"""

from db import db, new_id
from errors import raise_api


# ----- Common fields --------------------------------------------------------

def _now_iso():
    return db.current_utc_iso()


def make_record(extra: dict, common: bool = True) -> dict:
    rec = {"id": new_id()}
    now = _now_iso()
    rec["created_at"] = now
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    rec.update(extra)
    return rec


def touch(rec: dict):
    """Mark a mutation: refresh updated_at and bump version by one.

    No-op on NiceClass (which has neither field)."""
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = _now_iso()


# ----- Lookups --------------------------------------------------------------

def get_or_404(table: dict, rid, what: str = "resource"):
    if rid is None or rid not in table:
        raise_api("ERR_NOT_FOUND", f"{what} not found")
    return table[rid]


# ----- Serialization --------------------------------------------------------

def _distinct_class_count(application_id: str) -> int:
    classes = {
        gs["nice_class_id"]
        for gs in db.goods_services.values()
        if gs["application_id"] == application_id
    }
    return len(classes)


def ser_applicant(rec: dict) -> dict:
    open_count = sum(
        1
        for a in db.applications.values()
        if a["applicant_id"] == rec["id"]
        and a["status"] not in ("REGISTERED", "ABANDONED")
    )
    return {
        "id": rec["id"],
        "legal_name": rec["legal_name"],
        "entity_type": rec["entity_type"],
        "country_code": rec["country_code"],
        "is_foreign_domiciled": rec["country_code"] != "US",
        "open_application_count": open_count,
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_attorney(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "bar_number": rec["bar_number"],
        "bar_state": rec["bar_state"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_nice_class(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "class_number": rec["class_number"],
        "title": rec["title"],
        "is_service_class": 35 <= rec["class_number"] <= 45,
        "created_at": rec["created_at"],
    }


def ser_application(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "applicant_id": rec["applicant_id"],
        "attorney_id": rec.get("attorney_id"),
        "mark_text": rec["mark_text"],
        "filing_basis": rec["filing_basis"],
        "filing_tier": rec["filing_tier"],
        "status": rec["status"],
        "class_count": _distinct_class_count(rec["id"]),
        "filing_fee_cents": rec["filing_fee_cents"],
        "office_action_round": rec["office_action_round"],
        "filed_at": rec.get("filed_at"),
        "published_at": rec.get("published_at"),
        "notice_of_allowance_at": rec.get("notice_of_allowance_at"),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_goods_services(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "application_id": rec["application_id"],
        "nice_class_id": rec["nice_class_id"],
        "description": rec["description"],
        "pre_approved": rec["pre_approved"],
        "use_status": rec["use_status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_office_action(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "application_id": rec["application_id"],
        "round_number": rec["round_number"],
        "is_final": rec["is_final"],
        "ground": rec["ground"],
        "issued_at": rec["issued_at"],
        "response_deadline": rec["response_deadline"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_office_action_response(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "office_action_id": rec["office_action_id"],
        "argument_text": rec["argument_text"],
        "amends_identification": rec["amends_identification"],
        "submitted_at": rec["submitted_at"],
        "days_late": rec["days_late"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_statement_of_use(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "application_id": rec["application_id"],
        "specimen_url": rec["specimen_url"],
        "first_use_date": rec["first_use_date"],
        "extension_number": rec["extension_number"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_ttab(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "proceeding_type": rec["proceeding_type"],
        "target_application_id": rec.get("target_application_id"),
        "target_registration_id": rec.get("target_registration_id"),
        "petitioner_applicant_id": rec["petitioner_applicant_id"],
        "claim_status": rec["claim_status"],
        "defense_status": rec["defense_status"],
        "filed_at": rec["filed_at"],
        "answer_deadline": rec["answer_deadline"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_registration(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "application_id": rec["application_id"],
        "registration_number": rec["registration_number"],
        "registered_at": rec["registered_at"],
        "status": rec["status"],
        "maintenance_cycle": rec["maintenance_cycle"],
        "next_maintenance_due_at": rec.get("next_maintenance_due_at"),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_maintenance_filing(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "registration_id": rec["registration_id"],
        "filing_type": rec["filing_type"],
        "filed_at": rec["filed_at"],
        "in_grace_period": rec["in_grace_period"],
        "fee_cents": rec["fee_cents"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_madrid(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "basic_application_id": rec["basic_application_id"],
        "designated_countries": list(rec["designated_countries"]),
        "status": rec["status"],
        "dependency_end_at": rec["dependency_end_at"],
        "fee_cents": rec["fee_cents"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_docket_deadline(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "subject_type": rec["subject_type"],
        "subject_id": rec["subject_id"],
        "application_id": rec.get("application_id"),
        "due_at": rec["due_at"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


# ----- Docket deadline helpers ---------------------------------------------

def create_docket_deadline(subject_type, subject_id, due_at, application_id=None):
    rec = make_record({
        "subject_type": subject_type,
        "subject_id": subject_id,
        "application_id": application_id,
        "due_at": due_at,
        "status": "PENDING",
    })
    db.docket_deadlines[rec["id"]] = rec
    return rec


def find_docket_deadlines(subject_type, subject_id, status=None):
    out = []
    for d in db.docket_deadlines.values():
        if d["subject_type"] == subject_type and d["subject_id"] == subject_id:
            if status is None or d["status"] == status:
                out.append(d)
    return out


def set_docket_status(subject_type, subject_id, new_status, only_pending=True):
    """Set the docket deadline(s) for a subject to new_status. Each affected row
    is a mutation (touch). Returns the number updated."""
    n = 0
    for d in find_docket_deadlines(subject_type, subject_id):
        if only_pending and d["status"] != "PENDING":
            continue
        d["status"] = new_status
        touch(d)
        n += 1
    return n
