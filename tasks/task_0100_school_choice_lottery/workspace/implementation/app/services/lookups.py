"""Lookup helpers — raise ERR_NOT_FOUND / ERR_FK_NOT_FOUND as appropriate."""
from ..errors import APIError
from ..store import get_store


def get_district_or_404(district_id: str) -> dict:
    rec = get_store().districts.get(district_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"district {district_id} not found")
    return rec


def get_school_or_404(school_id: str) -> dict:
    rec = get_store().schools.get(school_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"school {school_id} not found")
    return rec


def get_program_or_404(program_id: str) -> dict:
    rec = get_store().programs.get(program_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"program {program_id} not found")
    return rec


def get_family_or_404(family_id: str) -> dict:
    rec = get_store().families.get(family_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"family {family_id} not found")
    return rec


def get_student_or_404(student_id: str) -> dict:
    rec = get_store().students.get(student_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"student {student_id} not found")
    return rec


def get_application_or_404(application_id: str) -> dict:
    rec = get_store().applications.get(application_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"application {application_id} not found")
    return rec


def get_transfer_request_or_404(tr_id: str) -> dict:
    rec = get_store().transfer_requests.get(tr_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"transfer request {tr_id} not found")
    return rec


def get_lottery_run_or_404(lr_id: str) -> dict:
    rec = get_store().lottery_runs.get(lr_id)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"lottery run {lr_id} not found")
    return rec


# ---- FK helpers (return ERR_FK_NOT_FOUND on miss) ----

def fk_district(district_id: str) -> dict:
    rec = get_store().districts.get(district_id)
    if rec is None:
        raise APIError("ERR_FK_NOT_FOUND", f"district_id {district_id} does not exist")
    return rec


def fk_school(school_id: str) -> dict:
    rec = get_store().schools.get(school_id)
    if rec is None:
        raise APIError("ERR_FK_NOT_FOUND", f"school_id {school_id} does not exist")
    return rec


def fk_program(program_id: str) -> dict:
    rec = get_store().programs.get(program_id)
    if rec is None:
        raise APIError("ERR_FK_NOT_FOUND", f"program_id {program_id} does not exist")
    return rec


def fk_family(family_id: str) -> dict:
    rec = get_store().families.get(family_id)
    if rec is None:
        raise APIError("ERR_FK_NOT_FOUND", f"family_id {family_id} does not exist")
    return rec


def fk_student(student_id: str) -> dict:
    rec = get_store().students.get(student_id)
    if rec is None:
        raise APIError("ERR_FK_NOT_FOUND", f"student_id {student_id} does not exist")
    return rec


def fk_application(application_id: str) -> dict:
    rec = get_store().applications.get(application_id)
    if rec is None:
        raise APIError("ERR_FK_NOT_FOUND", f"application_id {application_id} does not exist")
    return rec
