"""Shared row construction, path resolution and list helpers for the route modules."""

from db import clock_iso, db, mark_fresh, new_id, public_list
from errors import ApiError
from response import ok_list
from validation import pagination

# --------------------------------------------------------------------------
# row construction
# --------------------------------------------------------------------------

def insert(collection, fields, audited=True):
    """Create a row with the audit triple (or, for events, id + created_at only)."""
    row = {"id": new_id()}
    row.update(fields)
    now = clock_iso()
    row["created_at"] = now
    if audited:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row["id"]] = row
    mark_fresh(row)
    return row


# --------------------------------------------------------------------------
# path / foreign-key resolution
# --------------------------------------------------------------------------

def _resolve(collection, row_id, error_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_staff(staff_id):
    return _resolve("staff_members", staff_id, "ERR_STAFF_MEMBER_NOT_FOUND")


def get_client(client_id):
    return _resolve("clients", client_id, "ERR_CLIENT_NOT_FOUND")


def get_call(call_id):
    return _resolve("hotline_calls", call_id, "ERR_HOTLINE_CALL_NOT_FOUND")


def get_assessment(assessment_id):
    return _resolve("risk_assessments", assessment_id, "ERR_RISK_ASSESSMENT_NOT_FOUND")


def get_plan(plan_id):
    return _resolve("safety_plans", plan_id, "ERR_SAFETY_PLAN_NOT_FOUND")


def get_component(plan, component_id):
    component = db.plan_components.get(component_id)
    if component is None or component["safety_plan_id"] != plan["id"]:
        raise ApiError("ERR_PLAN_COMPONENT_NOT_FOUND")
    return component


def get_shelter(shelter_id):
    return _resolve("shelters", shelter_id, "ERR_SHELTER_NOT_FOUND")


def get_unit(unit_id):
    return _resolve("shelter_units", unit_id, "ERR_SHELTER_UNIT_NOT_FOUND")


def get_screening(request_id):
    return _resolve("screening_requests", request_id, "ERR_SCREENING_REQUEST_NOT_FOUND")


def get_admission(admission_id):
    return _resolve("shelter_admissions", admission_id, "ERR_SHELTER_ADMISSION_NOT_FOUND")


def get_case(case_id):
    return _resolve("protective_order_cases", case_id, "ERR_PROTECTIVE_ORDER_CASE_NOT_FOUND")


def get_partner(partner_id):
    return _resolve("landlord_partners", partner_id, "ERR_LANDLORD_PARTNER_NOT_FOUND")


def get_referral(referral_id):
    return _resolve("housing_referrals", referral_id, "ERR_HOUSING_REFERRAL_NOT_FOUND")


def get_disclosure(event_id):
    return _resolve("disclosure_events", event_id, "ERR_DISCLOSURE_EVENT_NOT_FOUND")


# --------------------------------------------------------------------------
# list helpers
# --------------------------------------------------------------------------

def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def filtered(collection, filters, extra=None):
    """Conjunctive equality filtering; None filter values are ignored."""
    out = []
    for row in getattr(db, collection).values():
        if extra is not None and not extra(row):
            continue
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def list_page(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(public_list(page), limit, offset, total)
