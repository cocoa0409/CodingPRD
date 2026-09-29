"""Education providers, instructors, completions, advertising names, the clock."""
from datetime import timedelta

from flask import Blueprint

import cascades
import computed
import envelope
import serialize
import shape
import store
from authz import guard
from errors import fail

bp = Blueprint("education", __name__)


# ----------------------------------------------------------------- providers
@bp.post("/commission/education-providers")
def register_provider():
    guard(["LicensingAnalyst"])
    data = shape.body()
    name = shape.req_str(data, "name")
    admin_user_id = shape.opt_str(data, "admin_user_id")
    row = store.insert("education_provider", {
        "name": name,
        "admin_user_id": admin_user_id,
        "status": "PENDING",
        "approved_at": None,
        "approval_expires_at": None,
    })
    return envelope.created(serialize.education_provider(row))


@bp.post("/commission/education-providers/<pid>/approval")
def approve_provider(pid):
    guard(["LicensingAnalyst"])
    data = shape.body()
    years = shape.opt_int(data, "approval_years", computed.DEFAULT_APPROVAL_YEARS,
                          minimum=1)

    provider = computed.must("education_provider", pid)
    if provider["status"] not in ("PENDING", "PROBATION"):
        fail("ERR_INVALID_STATE",
             "Only a PENDING or PROBATION provider may be approved.")
    if provider["status"] == "PROBATION":
        if computed.suspended_instructor_count(provider["id"]) != 0:
            fail("ERR_INVALID_STATE",
                 "The provider still carries suspended instructors.")
        if computed.invalidated_credit_hours(provider["id"]) >= computed.PROVIDER_SUSPEND_HOURS:
            fail("ERR_INVALID_STATE",
                 "The provider carries %d or more invalidated credit hours."
                 % computed.PROVIDER_SUSPEND_HOURS)

    moment = store.now()
    provider["status"] = "APPROVED"
    provider["approved_at"] = store.fmt_dt(moment)
    provider["approval_expires_at"] = store.fmt_dt(
        moment + timedelta(seconds=years * 365 * 86400))
    store.touch(provider)
    return envelope.ok(serialize.education_provider(provider))


# --------------------------------------------------------------- instructors
@bp.post("/commission/education-providers/<pid>/instructors")
def enrol_instructor(pid):
    user_id, role = guard(["ProviderAdmin", "LicensingAnalyst"])
    data = shape.body()
    full_name = shape.req_str(data, "full_name")
    credential_type = shape.req_enum(data, "credential_type", computed.CREDENTIAL_TYPES)
    licensee_id = shape.opt_id(data, "licensee_id")

    provider = computed.must("education_provider", pid)
    if licensee_id is not None:
        computed.must("licensee", licensee_id)
    if role == "ProviderAdmin" and provider.get("admin_user_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "This provider is not administered by the acting user.")
    if provider["status"] != "APPROVED":
        fail("ERR_PROVIDER_NOT_APPROVED",
             "Only an APPROVED provider may enrol instructors.")

    row = store.insert("instructor", {
        "education_provider_id": provider["id"],
        "licensee_id": licensee_id,
        "full_name": full_name,
        "credential_type": credential_type,
        "status": "PENDING",
        "approved_at": None,
        "suspended_reason": None,
    })
    return envelope.created(serialize.instructor(row))


@bp.post("/commission/instructors/<iid>/approval")
def approve_instructor(iid):
    guard(["LicensingAnalyst"])
    data = shape.body()
    shape.opt_str(data, "approval_note")

    instructor = computed.must("instructor", iid)
    if instructor["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING instructor may be approved.")
    provider = store.get("education_provider", instructor["education_provider_id"])
    if provider is None or provider["status"] != "APPROVED":
        fail("ERR_PROVIDER_NOT_APPROVED",
             "Only an APPROVED provider may approve instructors.")
    if instructor["credential_type"] == "LICENSED_BROKER":
        backing = store.get("licensee", instructor.get("licensee_id"))
        if (backing is None or backing["person_type"] != "BROKER"
                or backing["license_status"] != "ACTIVE"):
            fail("ERR_INVALID_STATE",
                 "A LICENSED_BROKER instructor needs an ACTIVE broker licence.")

    instructor["status"] = "APPROVED"
    instructor["approved_at"] = store.fmt_dt(store.now())
    store.touch(instructor)
    return envelope.ok(serialize.instructor(instructor))


# ---------------------------------------------------------- course completions
@bp.post("/commission/course-completions")
def record_completion():
    user_id, role = guard(["ProviderAdmin", "LicensingAnalyst"])
    data = shape.body()
    licensee_id = shape.req_id(data, "licensee_id")
    instructor_id = shape.req_id(data, "instructor_id")
    provider_id = shape.req_id(data, "education_provider_id")
    course_type = shape.req_enum(data, "course_type", computed.COURSE_TYPES)
    credit_hours = shape.req_int(data, "credit_hours", minimum=1, maximum=12)
    completed_on = shape.req_date(data, "completed_on")

    student = computed.must("licensee", licensee_id)
    instructor = computed.must("instructor", instructor_id)
    provider = computed.must("education_provider", provider_id)

    if role == "ProviderAdmin" and provider.get("admin_user_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "This provider is not administered by the acting user.")
    if instructor["education_provider_id"] != provider["id"]:
        fail("ERR_INSTRUCTOR_PROVIDER_MISMATCH",
             "The instructor does not belong to the named provider.")
    if provider["status"] not in ("APPROVED", "PROBATION"):
        fail("ERR_PROVIDER_NOT_APPROVED",
             "Only an APPROVED or PROBATION provider may report completions.")
    if instructor["status"] != "APPROVED":
        fail("ERR_INSTRUCTOR_NOT_APPROVED",
             "Only an APPROVED instructor may be named on a completion.")

    row = store.insert("course_completion", {
        "licensee_id": student["id"],
        "instructor_id": instructor["id"],
        "education_provider_id": provider["id"],
        "course_type": course_type,
        "credit_hours": credit_hours,
        "completed_on": store.fmt_date(completed_on),
        "credit_status": "VALID",
        "invalidated_at": None,
    }, audited=False)
    if course_type == "PRELICENSE":
        student["prelicense_hours"] = student.get("prelicense_hours", 0) + credit_hours
        store.touch(student)
    return envelope.created(serialize.course_completion(row))


# -------------------------------------------------------- advertising names
def _team_lead_check(kind, lead, brokerage_id):
    if kind == "TEAM":
        if (lead is None or lead["license_status"] != "ACTIVE"
                or lead.get("sponsoring_brokerage_id") != brokerage_id):
            fail("ERR_TEAM_LEAD_NOT_AFFILIATED",
                 "The team lead must be an ACTIVE licensee of this brokerage.")
    elif lead is not None:
        fail("ERR_TEAM_LEAD_NOT_AFFILIATED",
             "team_lead_licensee_id must be null for a DBA or BRANCH name.")


@bp.post("/commission/advertising-names")
def submit_name():
    guard(["Broker", "LicensingAnalyst"])
    data = shape.body()
    brokerage_id = shape.req_id(data, "brokerage_id")
    kind = shape.req_enum(data, "kind", computed.AD_KINDS)
    name_text = shape.req_str(data, "name_text")
    lead_id = shape.opt_id(data, "team_lead_licensee_id")

    brokerage = computed.must("brokerage", brokerage_id)
    lead = None
    if lead_id is not None:
        lead = computed.must("licensee", lead_id)

    _team_lead_check(kind, lead, brokerage["id"])
    normalized = computed.normalize_name(name_text)
    if computed.name_taken(normalized):
        fail("ERR_ADVERTISING_NAME_TAKEN",
             "That normalized name is already held by a live registration.")

    row = store.insert("advertising_name", {
        "brokerage_id": brokerage["id"],
        "team_lead_licensee_id": lead_id,
        "kind": kind,
        "name_text": name_text,
        "normalized_name": normalized,
        "prohibited_term_hits": computed.prohibited_term_hits(normalized),
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "rejection_reason": None,
    })
    return envelope.created(serialize.advertising_name(row))


@bp.post("/commission/advertising-names/<nid>/review")
def review_name(nid):
    user_id, _ = guard(["LicensingAnalyst"])
    data = shape.body()
    decision = shape.req_enum(data, "decision", {"APPROVE", "REJECT", "REVOKE"})
    rejection_reason = shape.opt_enum(data, "rejection_reason",
                                      computed.REJECTION_REASONS)

    row = computed.must("advertising_name", nid)
    if decision == "REVOKE":
        if row["status"] != "APPROVED":
            fail("ERR_INVALID_STATE", "Only an APPROVED name may be revoked.")
        row["status"] = "REVOKED"
        row["reviewed_by_user_id"] = user_id
        row["rejection_reason"] = rejection_reason
        store.touch(row)
        return envelope.ok(serialize.advertising_name(row))

    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED name may be reviewed.")

    if decision == "REJECT":
        row["status"] = "REJECTED"
        row["reviewed_by_user_id"] = user_id
        row["rejection_reason"] = rejection_reason
        store.touch(row)
        return envelope.ok(serialize.advertising_name(row))

    posture = computed.posture_of(row["brokerage_id"])
    if posture in ("RESTRICTED", "FROZEN"):
        fail("ERR_BROKERAGE_POSTURE_BLOCKED",
             "The owning brokerage's supervision posture is %s." % posture)
    normalized = row["normalized_name"]
    if computed.prohibited_term_hits(normalized) > 0:
        fail("ERR_PROHIBITED_ADVERTISING_TERM",
             "The name contains a prohibited term.")
    if row["kind"] == "TEAM" and computed.team_word_hits(normalized) > 0:
        fail("ERR_TEAM_NAME_IMPLIES_BROKERAGE",
             "A team name may not imply an independent firm.")
    lead = store.get("licensee", row.get("team_lead_licensee_id"))
    _team_lead_check(row["kind"], lead, row["brokerage_id"])
    if computed.name_taken(normalized, exclude_id=row["id"]):
        fail("ERR_ADVERTISING_NAME_TAKEN",
             "That normalized name is already held by another live registration.")

    row["status"] = "APPROVED"
    row["reviewed_by_user_id"] = user_id
    store.touch(row)
    return envelope.ok(serialize.advertising_name(row))


# ------------------------------------------------------------------- the clock
@bp.post("/commission/_clock/set_current_utc")
def set_clock():
    guard(["LicensingAnalyst", "TrustAuditor", "CommissionCounsel",
           "HearingPanelChair", "RecoveryFundTrustee"])
    data = shape.body()
    moment = shape.req_dt(data, "to_iso8601")
    store.set_clock(moment)
    return envelope.ok({"current_utc": store.fmt_dt(store.now())})
