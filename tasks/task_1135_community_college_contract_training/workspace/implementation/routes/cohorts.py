"""Cohort and Participant endpoints."""

from flask import Blueprint, request

import db
from db import now, stamp_new, store, touch
from errors import fail
from middleware import check_employer_scope, require_roles
from response import ok, ok_list, serialize
from services import lifecycle, lookups
from util import body_json, fmt_dt, pagination_args, req_enum, req_int, req_str, require_dt

bp = Blueprint("cohorts", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)

DELIVERY_MODES = ("ON_SITE", "ON_CAMPUS")


def _paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = pagination_args()
    page = items[offset : offset + limit]
    return ok_list([serialize(r) for r in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------

@bp.route("/ct/training-agreements/<aid>/cohorts", methods=["POST"])
def create_cohort(aid):
    require_roles("WorkforceCoordinator")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    body = body_json()
    delivery_mode = req_enum(body, "delivery_mode", DELIVERY_MODES)
    min_enrollment = req_int(body, "min_enrollment", min_value=1)
    start_date = fmt_dt(require_dt(body.get("start_date"), "start_date"))
    end_date = fmt_dt(require_dt(body.get("end_date"), "end_date"))
    venue_id = body.get("venue_id")
    if venue_id is not None:
        if not isinstance(venue_id, str) or not venue_id:
            fail("ERR_INVALID_REQUEST", "Field 'venue_id' must be a string")
        if venue_id not in store["venues"]:
            fail("ERR_INVALID_REQUEST", f"venue_id {venue_id} does not exist")

    if agreement["contract_status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_AGREEMENT_TERMINAL", f"Agreement is {agreement['contract_status']}")
    if agreement["contract_status"] not in ("QUOTED", "NEGOTIATING", "SIGNED", "IN_DELIVERY"):
        fail(
            "ERR_INVALID_STATE",
            f"Cannot create a cohort under an agreement in {agreement['contract_status']}",
        )
    if delivery_mode != agreement["delivery_mode"]:
        fail("ERR_DELIVERY_MODE_MISMATCH", "Cohort delivery_mode differs from the agreement's")
    if len(lookups.cohorts_of_agreement(aid)) >= agreement["max_cohorts"]:
        fail("ERR_INVALID_REQUEST", "The agreement's max_cohorts ceiling has been reached")

    rec = stamp_new(
        {
            "id": db.new_id(),
            "agreement_id": aid,
            "venue_id": venue_id,
            "delivery_mode": delivery_mode,
            "min_enrollment": min_enrollment,
            "start_date": start_date,
            "end_date": end_date,
            "enrolled_count": 0,
            "completer_count": 0,
            "delivery_status": "SCHEDULED",
            "billing_status": "UNBILLED",
            "_credentialed_at": None,
        }
    )
    store["cohorts"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/cohorts/<cid>", methods=["GET"])
def get_cohort(cid):
    uid, role = require_roles(*READ_ROLES)
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    check_employer_scope(uid, role, lookups.employer_id_of_cohort(cohort))
    return ok(serialize(cohort))


@bp.route("/ct/cohorts", methods=["GET"])
def list_cohorts():
    uid, role = require_roles(*READ_ROLES)
    items = list(store["cohorts"].values())
    if role == "EmployerContact":
        items = [c for c in items if lookups.employer_id_of_cohort(c) == uid]
    f_venue = request.args.get("venue_id")
    f_agreement = request.args.get("agreement_id")
    f_status = request.args.get("delivery_status")
    if f_venue is not None:
        items = [c for c in items if c.get("venue_id") == f_venue]
    if f_agreement is not None:
        items = [c for c in items if c["agreement_id"] == f_agreement]
    if f_status is not None:
        items = [c for c in items if c["delivery_status"] == f_status]
    return _paginate(items)


@bp.route("/ct/cohorts/<cid>/launch", methods=["POST"])
def launch_cohort(cid):
    require_roles("WorkforceCoordinator")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    if cohort["delivery_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Cannot launch a cohort in {cohort['delivery_status']}")
    agreement = store["agreements"][cohort["agreement_id"]]
    if agreement["contract_status"] not in ("SIGNED", "IN_DELIVERY"):
        fail("ERR_AGREEMENT_NOT_SIGNED", "The agreement is not SIGNED or IN_DELIVERY")
    if cohort["enrolled_count"] < cohort["min_enrollment"]:
        fail(
            "ERR_BELOW_MIN_ENROLLMENT",
            f"enrolled_count {cohort['enrolled_count']} is below min_enrollment {cohort['min_enrollment']}",
        )
    sessions = lookups.sessions_of_cohort(cid)
    for session in sessions:
        if session["status"] != "PLANNED":
            continue
        confirmed = [
            a
            for a in lookups.assignments_of_session(session["id"])
            if a["status"] == "CONFIRMED"
        ]
        if not confirmed:
            fail(
                "ERR_CREDENTIAL_MISMATCH",
                f"PLANNED session {session['id']} lacks a CONFIRMED instructor assignment",
            )
    venue_ids = {c for c in [cohort.get("venue_id")] if c}
    venue_ids |= {s["venue_id"] for s in sessions if s.get("venue_id")}
    for venue_id in venue_ids:
        venue = store["venues"].get(venue_id)
        if venue is not None and venue["kind"] == "CAMPUS_LAB" and venue["capacity"] < cohort["enrolled_count"]:
            fail(
                "ERR_VENUE_CAPACITY_EXCEEDED",
                f"Venue {venue_id} capacity {venue['capacity']} is below enrolled_count {cohort['enrolled_count']}",
            )
    cohort["delivery_status"] = "LAUNCHED"
    touch(cohort)
    if agreement["contract_status"] == "SIGNED":
        agreement["contract_status"] = "IN_DELIVERY"
        touch(agreement)
    return ok(serialize(cohort))


@bp.route("/ct/cohorts/<cid>/cancel", methods=["POST"])
def cancel_cohort(cid):
    require_roles("WorkforceCoordinator", "CollegeAdmin")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    if cohort["delivery_status"] not in ("SCHEDULED", "LAUNCHED"):
        fail("ERR_INVALID_STATE", f"Cannot cancel a cohort in {cohort['delivery_status']}")
    lifecycle.cancel_cohort_cascade(cohort)
    return ok(serialize(cohort))


@bp.route("/ct/cohorts/<cid>/issue_credentials", methods=["POST"])
def issue_credentials(cid):
    require_roles("CredentialOfficer")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    if cohort["delivery_status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", f"Cannot issue credentials for a cohort in {cohort['delivery_status']}")
    if cohort["completer_count"] < 1:
        fail("ERR_NO_COMPLETERS", "The cohort has no completers")
    date_part = cohort["start_date"].replace("-", "")[:8]
    for participant in lookups.participants_of_cohort(cid):
        if participant["completion_status"] == "COMPLETED":
            participant["credential_code"] = (
                f"CTC-{date_part}-{participant['external_employee_ref']}"
            )
            touch(participant)
    cohort["delivery_status"] = "CREDENTIALED"
    cohort["_credentialed_at"] = fmt_dt(now())
    touch(cohort)
    return ok(serialize(cohort))


@bp.route("/ct/cohorts/<cid>/sessions", methods=["GET"])
def list_cohort_sessions(cid):
    uid, role = require_roles(*READ_ROLES)
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    check_employer_scope(uid, role, lookups.employer_id_of_cohort(cohort))
    return _paginate(lookups.sessions_of_cohort(cid))


@bp.route("/ct/cohorts/<cid>/participants", methods=["GET"])
def list_cohort_participants(cid):
    uid, role = require_roles(*READ_ROLES)
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    check_employer_scope(uid, role, lookups.employer_id_of_cohort(cohort))
    return _paginate(lookups.participants_of_cohort(cid))


@bp.route("/ct/cohorts/<cid>/invoices", methods=["GET"])
def list_cohort_invoices(cid):
    uid, role = require_roles(*READ_ROLES)
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    check_employer_scope(uid, role, lookups.employer_id_of_cohort(cohort))
    return _paginate(lookups.invoices_of_cohort(cid))


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

@bp.route("/ct/cohorts/<cid>/participants", methods=["POST"])
def create_participant(cid):
    require_roles("WorkforceCoordinator")
    cohort = lookups.get_or_404("cohorts", cid, "Cohort")
    body = body_json()
    ref = req_str(body, "external_employee_ref")
    full_name = req_str(body, "full_name")
    if cohort["delivery_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", f"Cannot enroll participants on a cohort in {cohort['delivery_status']}")
    for existing in lookups.participants_of_cohort(cid):
        if (
            existing["external_employee_ref"] == ref
            and existing["completion_status"] == "ENROLLED"
        ):
            fail("ERR_DUPLICATE_PARTICIPANT", f"external_employee_ref '{ref}' is already enrolled")
    rec = stamp_new(
        {
            "id": db.new_id(),
            "cohort_id": cid,
            "external_employee_ref": ref,
            "full_name": full_name,
            "attended_hours": 0,
            "attendance_pct": 0,
            "completion_status": "ENROLLED",
            "credential_code": None,
        }
    )
    store["participants"][rec["id"]] = rec
    cohort["enrolled_count"] += 1
    touch(cohort)
    return ok(serialize(rec), 201)


@bp.route("/ct/participants/<pid>", methods=["GET"])
def get_participant(pid):
    uid, role = require_roles(*READ_ROLES)
    participant = lookups.get_or_404("participants", pid, "Participant")
    check_employer_scope(uid, role, lookups.employer_id_of_participant(participant))
    return ok(serialize(participant))


@bp.route("/ct/participants/<pid>/drop", methods=["POST"])
def drop_participant(pid):
    require_roles("WorkforceCoordinator")
    participant = lookups.get_or_404("participants", pid, "Participant")
    if participant["completion_status"] != "ENROLLED":
        fail("ERR_INVALID_STATE", f"Cannot drop a participant in {participant['completion_status']}")
    participant["completion_status"] = "DROPPED"
    touch(participant)
    cohort = store["cohorts"].get(participant["cohort_id"])
    if cohort is not None:
        cohort["enrolled_count"] = sum(
            1
            for p in lookups.participants_of_cohort(cohort["id"])
            if p["completion_status"] == "ENROLLED"
        )
        touch(cohort)
    return ok(serialize(participant))
