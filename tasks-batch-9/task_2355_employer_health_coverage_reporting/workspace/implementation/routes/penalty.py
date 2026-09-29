"""Proposed-penalty notices, evidence, recomputation and allocation."""

from flask import Blueprint

import calc
import lookups as lk
import sync
from auth import require_roles
from db import clock_date, clock_iso, insert, rows, touch
from envelope import created, ok
from errors import fail
from guards import listing, single_read
from shapes import (
    body,
    date_field,
    enum_field,
    int_field,
    order_dates,
    string_field,
    to_date,
)

bp = Blueprint("penalty", __name__)

NOTICE_READ_ROLES = ("ComplianceOfficer", "Preparer", "FilingAgent")
EVIDENCE_TYPES = ("OFFER_PROOF", "FT_STATUS_DISPUTE", "MEC_OFFER_PROOF")
EVIDENCE_OPEN_STATES = ("RECEIVED", "EVIDENCE_GATHERING", "RECOMPUTED")
FILED_FOR_EVIDENCE = ("FILED_ACCEPTED", "FILED_WITH_ERRORS", "CORRECTION_DRAFTED")


def _month_array(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array of months." % name)
    out = []
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int) or entry < 1 or entry > 12:
            fail("ERR_INVALID_REQUEST", "%s entries must be integers 1..12." % name)
        out.append(entry)
    return out


def _employee_month_array(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array of objects." % name)
    out = []
    for entry in value:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "%s entries must be objects." % name)
        employee_id = string_field(entry, "employee_id")
        month = int_field(entry, "month", minimum=1, maximum=12)
        out.append({"employee_id": employee_id, "month": month})
    return out


# --------------------------------------------------------------------------- #
# PenaltyNotice
# --------------------------------------------------------------------------- #
@bp.post("/penalty-notices")
def create_notice():
    require_roles("ComplianceOfficer")
    data = body()
    controlled_group_id = string_field(data, "controlled_group_id")
    notice_number = string_field(data, "notice_number")
    notice_date = date_field(data, "notice_date")
    response_due_date = date_field(data, "response_due_date")
    proposed_amount_cents = int_field(data, "proposed_amount_cents", minimum=0)
    asserted_a_months = _month_array(data, "asserted_a_months")
    asserted_b_employee_months = _employee_month_array(data, "asserted_b_employee_months")
    order_dates(
        notice_date,
        response_due_date,
        True,
        "response_due_date must be strictly after notice_date.",
    )

    lk.find("controlled_groups", controlled_group_id)
    for entry in asserted_b_employee_months:
        lk.find("employees", entry["employee_id"])
    for existing in rows("penalty_notices"):
        if existing["notice_number"] == notice_number:
            fail("ERR_DUPLICATE_RESOURCE", "That notice number is already recorded.")

    record = insert(
        "penalty_notices",
        {
            "controlled_group_id": controlled_group_id,
            "notice_number": notice_number,
            "notice_date": notice_date,
            "response_due_date": response_due_date,
            "proposed_amount_cents": proposed_amount_cents,
            "asserted_a_months": asserted_a_months,
            "asserted_b_employee_months": asserted_b_employee_months,
            "status": "RECEIVED",
            "a_month_penalty_cents": None,
            "b_month_penalty_cents": None,
            "recalculated_amount_cents": None,
            "allocated_total_cents": 0,
            "unallocated_amount_cents": 0,
            "evidence_count": 0,
            "applied_evidence_count": 0,
            "abated_amount_cents": None,
            "determination": None,
            "recomputed_at": None,
            "last_evidence_user_id": None,
            "response_submitted_by_user_id": None,
            "response_submitted_at": None,
        },
    )
    return created(record)


@bp.get("/penalty-notices")
def list_notices():
    return listing(
        "penalty_notices",
        {"controlled_group_id": ("controlled_group_id", "str"), "status": ("status", "str")},
        NOTICE_READ_ROLES,
    )


@bp.get("/penalty-notices/<identifier>")
def read_notice(identifier):
    return single_read("penalty_notices", identifier, NOTICE_READ_ROLES)


def _require_window_open(notice):
    if clock_date() > to_date(notice["response_due_date"]):
        fail("ERR_NOTICE_RESPONSE_WINDOW_CLOSED", "The response window has closed.")


@bp.post("/penalty-notices/<notice_id>/evidence")
def create_evidence(notice_id):
    user_id, _role = require_roles("ComplianceOfficer")
    data = body()
    evidence_type = enum_field(data, "evidence_type", EVIDENCE_TYPES)
    month = int_field(data, "month", minimum=1, maximum=12)
    document_ref = string_field(data, "document_ref")
    needs_employee = evidence_type in ("FT_STATUS_DISPUTE", "OFFER_PROOF")
    employee_id = string_field(data, "employee_id", required=needs_employee)
    needs_codes = evidence_type == "OFFER_PROOF"
    asserted_line14_code = string_field(data, "asserted_line14_code", required=needs_codes)
    asserted_line16_code = string_field(data, "asserted_line16_code", required=needs_codes)

    notice = lk.find("penalty_notices", notice_id)
    group = lk.get("controlled_groups", notice["controlled_group_id"])
    employee = None
    if employee_id is not None:
        employee = lk.find("employees", employee_id)
        member_ids = set(m["id"] for m in lk.members_of_group(group)) if group else set()
        if employee["group_member_id"] not in member_ids:
            fail("ERR_SCOPE_MISMATCH", "That employee is outside the notice's controlled group.")

    if notice["status"] not in EVIDENCE_OPEN_STATES:
        fail("ERR_NOTICE_STATE_INVALID", "This notice no longer accepts evidence.")

    if evidence_type == "MEC_OFFER_PROOF":
        if month not in (notice["asserted_a_months"] or []):
            fail(
                "ERR_EVIDENCE_MONTH_NOT_ASSERTED",
                "The agency did not assert a section (a) failure for that month.",
            )
    else:
        pairs = set(
            (entry["employee_id"], entry["month"])
            for entry in (notice["asserted_b_employee_months"] or [])
        )
        if (employee_id, month) not in pairs:
            fail(
                "ERR_EVIDENCE_MONTH_NOT_ASSERTED",
                "The agency did not assert that employee-month.",
            )

    _require_window_open(notice)

    record = insert(
        "penalty_evidence",
        {
            "penalty_notice_id": notice["id"],
            "employee_id": employee_id,
            "evidence_type": evidence_type,
            "month": month,
            "asserted_line14_code": asserted_line14_code,
            "asserted_line16_code": asserted_line16_code,
            "document_ref": document_ref,
            "applied": False,
            "filed_by_user_id": user_id,
        },
    )

    was_recomputed = notice["status"] == "RECOMPUTED"
    sync.set_field(notice, "status", "EVIDENCE_GATHERING")
    sync.set_field(notice, "last_evidence_user_id", user_id)
    if was_recomputed and group is not None:
        sync.invalidate_recomputation(notice, group)
    touch(notice)
    return created(record)


@bp.post("/penalty-notices/<notice_id>/recompute")
def recompute_notice(notice_id):
    require_roles("ComplianceOfficer")
    body()
    notice = lk.find("penalty_notices", notice_id)
    group = lk.get("controlled_groups", notice["controlled_group_id"])
    season = lk.season_of_group(group) if group else None

    evidence = lk.evidence_of_notice(notice)
    if notice["status"] != "EVIDENCE_GATHERING" or len(evidence) < 1:
        fail("ERR_NOTICE_STATE_INVALID", "This notice is not ready to be recomputed.")

    for row in evidence:
        if row["evidence_type"] == "MEC_OFFER_PROOF" or not row.get("employee_id"):
            continue
        employee = lk.get("employees", row["employee_id"])
        forms = lk.forms_of_employee(employee) if employee else []
        if not any(f["filing_status"] in FILED_FOR_EVIDENCE for f in forms):
            fail(
                "ERR_EVIDENCE_FORM_NOT_FILED",
                "The statement this evidence disputes has not been filed.",
            )

    _require_window_open(notice)
    if season is None:
        fail("ERR_FILING_SEASON_NOT_FOUND", "No filing season governs this notice.")

    result = calc.recompute_penalty(notice, group, season)
    allocated = 0
    for member in result["active_members"]:
        sync.set_field(
            member, "allocated_exclusion_employees", result["exclusion_by_member"][member["id"]]
        )
        cents = result["cents_by_member"][member["id"]]
        sync.set_field(member, "allocated_penalty_cents", cents)
        allocated += cents

    sync.set_field(notice, "a_month_penalty_cents", result["a_month_penalty_cents"])
    sync.set_field(notice, "b_month_penalty_cents", result["b_month_penalty_cents"])
    sync.set_field(notice, "recalculated_amount_cents", result["recalculated_amount_cents"])
    sync.set_field(notice, "applied_evidence_count", result["applied_evidence_count"])
    sync.set_field(notice, "allocated_total_cents", allocated)
    sync.set_field(
        notice, "unallocated_amount_cents", result["recalculated_amount_cents"] - allocated
    )
    sync.set_field(notice, "recomputed_at", clock_iso())
    sync.set_field(notice, "status", "RECOMPUTED")
    touch(notice)
    return ok(notice)


@bp.post("/penalty-notices/<notice_id>/allocation/reset")
def reset_allocation(notice_id):
    require_roles("ComplianceOfficer")
    body()
    notice = lk.find("penalty_notices", notice_id)
    if notice["status"] != "RECOMPUTED":
        fail("ERR_NOTICE_NOT_RECOMPUTED", "Only a recomputed notice has an allocation.")
    if (notice.get("allocated_total_cents") or 0) <= 0:
        fail("ERR_NOTICE_NOT_RECOMPUTED", "There is nothing allocated to reset.")

    group = lk.get("controlled_groups", notice["controlled_group_id"])
    if group is not None:
        sync.zero_member_allocations(group)
    sync.set_field(notice, "allocated_total_cents", 0)
    sync.set_field(
        notice, "unallocated_amount_cents", notice.get("recalculated_amount_cents") or 0
    )
    touch(notice)
    return ok(notice)


@bp.post("/penalty-notices/<notice_id>/submit-response")
def submit_response(notice_id):
    user_id, _role = require_roles("ComplianceOfficer")
    body()
    notice = lk.find("penalty_notices", notice_id)
    if notice["status"] != "RECOMPUTED":
        fail("ERR_NOTICE_NOT_RECOMPUTED", "The notice must be recomputed before responding.")
    if user_id == notice.get("last_evidence_user_id"):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who last filed evidence may not submit the response.",
        )
    _require_window_open(notice)
    if notice.get("recalculated_amount_cents") is None or (
        notice.get("unallocated_amount_cents") or 0
    ) != 0:
        fail("ERR_ALLOCATION_NOT_SETTLED", "The allocation across members is not settled.")

    sync.set_field(notice, "status", "RESPONSE_SUBMITTED")
    sync.set_field(notice, "response_submitted_at", clock_iso())
    sync.set_field(notice, "response_submitted_by_user_id", user_id)
    touch(notice)
    return ok(notice)


@bp.post("/penalty-notices/<notice_id>/agency-determination")
def agency_determination(notice_id):
    require_roles("ComplianceOfficer")
    data = body()
    determination = enum_field(
        data, "determination", ("ABATED_FULL", "ABATED_PARTIAL", "SUSTAINED")
    )
    abated = int_field(data, "abated_amount_cents", minimum=0)

    notice = lk.find("penalty_notices", notice_id)
    if notice["status"] != "RESPONSE_SUBMITTED":
        fail("ERR_NOTICE_STATE_INVALID", "No response has been submitted for this notice.")

    proposed = notice["proposed_amount_cents"]
    if determination == "ABATED_FULL" and abated != proposed:
        fail("ERR_ABATEMENT_AMOUNT_INVALID", "A full abatement must equal the proposed amount.")
    if determination == "ABATED_PARTIAL" and not (0 < abated < proposed):
        fail(
            "ERR_ABATEMENT_AMOUNT_INVALID",
            "A partial abatement must be between 0 and the proposed amount.",
        )
    if determination == "SUSTAINED" and abated != 0:
        fail("ERR_ABATEMENT_AMOUNT_INVALID", "A sustained penalty abates nothing.")

    group = lk.get("controlled_groups", notice["controlled_group_id"])
    members = lk.members_of_group(group, active_only=True) if group else []

    sync.set_field(notice, "determination", determination)
    sync.set_field(notice, "abated_amount_cents", abated)
    sync.set_field(notice, "status", determination)

    if determination == "ABATED_FULL":
        for member in members:
            sync.set_field(member, "allocated_penalty_cents", 0)
        sync.set_field(notice, "allocated_total_cents", 0)
        sync.set_field(notice, "unallocated_amount_cents", 0)
    elif determination == "SUSTAINED":
        cents = calc.allocate_cents(proposed, members)
        total = 0
        for member in members:
            sync.set_field(member, "allocated_penalty_cents", cents[member["id"]])
            total += cents[member["id"]]
        sync.set_field(notice, "allocated_total_cents", total)
        sync.set_field(notice, "unallocated_amount_cents", 0)
    touch(notice)
    return ok(notice)


# --------------------------------------------------------------------------- #
# PenaltyEvidence
# --------------------------------------------------------------------------- #
@bp.get("/penalty-evidence")
def list_evidence():
    return listing(
        "penalty_evidence",
        {
            "penalty_notice_id": ("penalty_notice_id", "str"),
            "employee_id": ("employee_id", "str"),
            "evidence_type": ("evidence_type", "str"),
        },
        NOTICE_READ_ROLES,
    )


@bp.get("/penalty-evidence/<identifier>")
def read_evidence(identifier):
    return single_read("penalty_evidence", identifier, NOTICE_READ_ROLES)
