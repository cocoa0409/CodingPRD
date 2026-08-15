"""Shared helpers: record creation, family-scope ownership resolution."""

import db
import errors


def make_record(store: dict, fields: dict) -> dict:
    now = db.fmt_ts(db.wall_now())
    rec = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    store[rec["id"]] = rec
    return rec


def get_or_404(store: dict, rid: str, label: str):
    rec = store.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, f"{label} not found: {rid}")
    return rec


def ref_or_404(store: dict, rid: str, label: str):
    rec = store.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, f"Referenced {label} not found: {rid}")
    return rec


def application_family_id(app) -> str:
    applicant = db.applicants.get(app["applicant_id"])
    return applicant["family_id"] if applicant else None


def contract_family_id(contract) -> str:
    app = db.applications.get(contract["application_id"])
    return application_family_id(app) if app else None


def aid_family_id(aid) -> str:
    app = db.applications.get(aid["application_id"])
    return application_family_id(app) if app else None


def evaluation_family_id(ev) -> str:
    app = db.applications.get(ev["application_id"])
    return application_family_id(app) if app else None


def reenrollment_family_id(offer) -> str:
    student = db.students.get(offer["student_id"])
    return student["family_id"] if student else None


def parent_scope_check(uid: str, role: str, family_id) -> None:
    """PRD layer 3: a Parent caller may only touch resources in their family."""
    if role != "Parent":
        return
    if family_id is None or family_id != uid:
        raise errors.err(errors.ERR_FAMILY_SCOPE_VIOLATION,
                         "Parent caller may only access resources within their family scope")


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
