"""Aggregate-chain resolution helpers shared by routes."""
from db import STORE
from errors import ApiError


def not_found(what="resource"):
    raise ApiError("ERR_NOT_FOUND", 404, f"{what} not found")


def get_landlord(lid):
    r = STORE.landlords.get(lid)
    if not r:
        not_found("landlord")
    return r


def get_unit(uid):
    r = STORE.units.get(uid)
    if not r:
        not_found("unit")
    return r


def get_tenancy(tid):
    r = STORE.tenancies.get(tid)
    if not r:
        not_found("tenancy")
    return r


def get_case(cid):
    r = STORE.cases.get(cid)
    if not r:
        not_found("case")
    return r


def get_notice(nid):
    r = STORE.notices.get(nid)
    if not r:
        not_found("notice")
    return r


def get_package(pid):
    r = STORE.packages.get(pid)
    if not r:
        not_found("filing package")
    return r


def get_hearing(hid):
    r = STORE.hearings.get(hid)
    if not r:
        not_found("hearing")
    return r


def get_answer(aid):
    r = STORE.answers.get(aid)
    if not r:
        not_found("answer")
    return r


def get_referral(rid):
    r = STORE.referrals.get(rid)
    if not r:
        not_found("referral")
    return r


def get_judgment(jid):
    r = STORE.judgments.get(jid)
    if not r:
        not_found("judgment")
    return r


def get_writ(wid):
    r = STORE.writs.get(wid)
    if not r:
        not_found("writ")
    return r


def get_storage_record(sid):
    r = STORE.storage_records.get(sid)
    if not r:
        not_found("storage record")
    return r


def get_collection_entry(eid):
    r = STORE.collection_entries.get(eid)
    if not r:
        not_found("collection entry")
    return r


def get_report(rid):
    r = STORE.reports.get(rid)
    if not r:
        not_found("rental history report")
    return r


def unit_of_case(case):
    tenancy = STORE.tenancies.get(case["tenancy_id"])
    return STORE.units.get(tenancy["unit_id"]) if tenancy else None


def jurisdiction_of_case(case):
    unit = unit_of_case(case)
    return unit["jurisdiction_code"] if unit else None


def accepted_package_for_case(case_id):
    for p in STORE.packages.values():
        if p["case_id"] == case_id and p["status"] == "ACCEPTED":
            return p
    return None


def judgment_for_case(case_id):
    for j in STORE.judgments.values():
        if j["case_id"] == case_id:
            return j
    return None
