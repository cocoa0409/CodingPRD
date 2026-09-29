"""Entity lookups (ladder rungs 4 and 5) and small navigation helpers."""

from db import db, rows
from errors import fail

NOT_FOUND = {
    "filing_seasons": "ERR_FILING_SEASON_NOT_FOUND",
    "controlled_groups": "ERR_CONTROLLED_GROUP_NOT_FOUND",
    "group_members": "ERR_GROUP_MEMBER_NOT_FOUND",
    "employees": "ERR_EMPLOYEE_NOT_FOUND",
    "furnishing_consents": "ERR_CONSENT_NOT_FOUND",
    "forms_1095c": "ERR_FORM_NOT_FOUND",
    "transmittals": "ERR_TRANSMITTAL_NOT_FOUND",
    "transmittal_errors": "ERR_TRANSMITTAL_ERROR_NOT_FOUND",
    "penalty_notices": "ERR_PENALTY_NOTICE_NOT_FOUND",
    # the seven append-only ledger families
    "monthly_headcounts": "ERR_RECORD_NOT_FOUND",
    "measurement_cycles": "ERR_RECORD_NOT_FOUND",
    "hours_records": "ERR_RECORD_NOT_FOUND",
    "employment_events": "ERR_RECORD_NOT_FOUND",
    "coverage_offers": "ERR_RECORD_NOT_FOUND",
    "monthly_coverage_lines": "ERR_RECORD_NOT_FOUND",
    "penalty_evidence": "ERR_RECORD_NOT_FOUND",
}


def find(table, identifier):
    if not isinstance(identifier, str):
        fail(NOT_FOUND[table])
    record = db.table(table).get(identifier)
    if record is None:
        fail(NOT_FOUND[table])
    return record


def get(table, identifier):
    if not isinstance(identifier, str):
        return None
    return db.table(table).get(identifier)


# --------------------------------------------------------------------------- #
# navigation
# --------------------------------------------------------------------------- #
def group_of_member(member):
    return get("controlled_groups", member["controlled_group_id"])


def season_of_group(group):
    return get("filing_seasons", group["filing_season_id"])


def member_of_employee(employee):
    return get("group_members", employee["group_member_id"])


def group_of_employee(employee):
    member = member_of_employee(employee)
    return group_of_member(member) if member else None


def season_of_employee(employee):
    group = group_of_employee(employee)
    return season_of_group(group) if group else None


def season_of_member(member):
    group = group_of_member(member)
    return season_of_group(group) if group else None


def members_of_group(group, active_only=False):
    out = [m for m in rows("group_members") if m["controlled_group_id"] == group["id"]]
    if active_only:
        out = [m for m in out if m["member_status"] == "ACTIVE"]
    return out


def employees_of_group(group):
    ids = set(m["id"] for m in members_of_group(group))
    return [e for e in rows("employees") if e["group_member_id"] in ids]


def forms_of_employee(employee):
    return [f for f in rows("forms_1095c") if f["employee_id"] == employee["id"]]


def lines_of_form(form):
    out = [l for l in rows("monthly_coverage_lines") if l["form_1095c_id"] == form["id"]]
    out.sort(key=lambda l: l["month"])
    return out


def offers_of_employee(employee):
    return [o for o in rows("coverage_offers") if o["employee_id"] == employee["id"]]


def hours_of_employee(employee):
    return [h for h in rows("hours_records") if h["employee_id"] == employee["id"]]


def headcounts_of_member(member, count_year=None):
    out = [h for h in rows("monthly_headcounts") if h["group_member_id"] == member["id"]]
    if count_year is not None:
        out = [h for h in out if h["count_year"] == count_year]
    return out


def transmittals_of_member(member):
    return [t for t in rows("transmittals") if t["group_member_id"] == member["id"]]


def forms_of_transmittal(transmittal):
    return [f for f in rows("forms_1095c") if f["transmittal_id"] == transmittal["id"]]


def errors_of_transmittal(transmittal):
    return [e for e in rows("transmittal_errors") if e["transmittal_id"] == transmittal["id"]]


def evidence_of_notice(notice):
    return [e for e in rows("penalty_evidence") if e["penalty_notice_id"] == notice["id"]]


def consent_of_employee(employee_id):
    for c in rows("furnishing_consents"):
        if c["employee_id"] == employee_id:
            return c
    return None


VOIDED = "VOIDED"


def is_live(form):
    return form["furnishing_status"] != VOIDED and form["filing_status"] != VOIDED


def live_form(employee):
    """The employee's non-VOIDED statement (the most recent one when several)."""
    candidates = [f for f in forms_of_employee(employee) if is_live(f)]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f["_seq"])


def group_of_form(form):
    employee = get("employees", form["employee_id"])
    return group_of_employee(employee) if employee else None
