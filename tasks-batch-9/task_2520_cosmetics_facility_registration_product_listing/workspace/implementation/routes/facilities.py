"""Facility registration, renewals, ownership changes, ledger and inspections."""

from datetime import timedelta

from flask import Blueprint

import access
import calc
import domain
import envelope
import schema
import store
from access import Checks, Ctx
from errors import ApiError

bp = Blueprint("facilities", __name__)


# --------------------------------------------------------------- facilities
@bp.post("/cosmetics/facilities")
def create_facility():
    auth = access.authorize("FacilityRegistrant")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()

    def validate():
        payload = body if body is not None else {}
        ctx.name = schema.string_field(payload, "facility_name", max_len=200)
        ctx.owner = schema.string_field(payload, "owner_operator_name", max_len=200)
        ctx.ftype = schema.enum_field(payload, "facility_type", domain.FACILITY_TYPES)
        ctx.country = schema.country_code_field(payload, "country_code")
        ctx.state = schema.string_field(payload, "state_or_province", max_len=64)

    checks.add(access.R_INVALID, validate)
    checks.run()

    facility = store.insert("facilities", {
        "facility_name": ctx.name,
        "owner_operator_name": ctx.owner,
        "facility_type": ctx.ftype,
        "country_code": ctx.country,
        "state_or_province": ctx.state,
        "facility_fei": None,
        "registration_status": "DRAFT",
        "compliance_posture": "OPEN",
        "registration_cycle_count": 0,
        "current_period_start": None,
        "current_period_end": None,
        "renewal_window_open_date": None,
        "grace_end_date": None,
        "gmp_readiness_score": None,
        "last_inspection_outcome": None,
    })
    return envelope.created(domain.facility_json(facility))


@bp.get("/cosmetics/facilities/<fid>")
def get_facility(fid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))
    checks.run()
    return envelope.ok(domain.facility_json(ctx.facility))


@bp.get("/cosmetics/facilities")
def list_facilities():
    access.authorize("RegulatoryReviewer", "EnforcementOfficer", "SystemOperator")
    from flask import request
    records = store.all_of("facilities")
    status = request.args.get("registration_status")
    if status:
        records = [r for r in records if r["registration_status"] == status]
    posture = request.args.get("compliance_posture")
    if posture:
        records = [r for r in records if r["compliance_posture"] == posture]
    return envelope.paginate(store.by_created(records), domain.facility_json)


@bp.post("/cosmetics/facilities/<fid>/submit-registration")
def submit_registration(fid):
    auth = access.authorize("FacilityRegistrant")
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))

    def state():
        facility = ctx.facility
        access.state_error(facility["registration_status"] == "DRAFT", "ERR_INVALID_FACILITY_STATE")
        for field in ("facility_name", "owner_operator_name", "facility_type",
                      "country_code", "state_or_province"):
            if not facility.get(field) or not str(facility[field]).strip():
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % field)

    checks.add(access.R_STATE_FACILITY, state)
    checks.run()

    facility = ctx.facility
    facility["registration_status"] = "PENDING_REVIEW"
    store.touch(facility)
    return envelope.ok(domain.facility_json(facility))


@bp.post("/cosmetics/facilities/<fid>/registration-decision")
def registration_decision(fid):
    auth = access.authorize("RegulatoryReviewer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))

    def validate():
        payload = body if body is not None else {}
        ctx.decision = schema.enum_field(payload, "decision", ("APPROVE", "REJECT"))
        ctx.note = schema.string_field(payload, "decision_note", required=False, max_len=1000, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_FACILITY, lambda: access.state_error(
        ctx.facility["registration_status"] == "PENDING_REVIEW", "ERR_INVALID_FACILITY_STATE"))
    checks.run()

    facility = ctx.facility
    if ctx.decision == "REJECT":
        facility["registration_status"] = "REJECTED"
        store.touch(facility)
        domain.ledger_append(facility["id"], "STATE_TRANSITION", "Facility", facility["id"],
                             "registration rejected")
        return envelope.ok(domain.facility_json(facility))

    facility["registration_status"] = "REGISTERED"
    approved = len([f for f in store.all_of("facilities") if f["facility_fei"]])
    facility["facility_fei"] = "FEI-%06d" % (approved + 1)
    domain.create_period(facility, "INITIAL", store.today(), 1)
    facility["registration_cycle_count"] += 1
    domain.recompute_posture(facility)
    store.touch(facility)
    domain.ledger_append(facility["id"], "STATE_TRANSITION", "Facility", facility["id"],
                         "registration approved")
    return envelope.ok(domain.facility_json(facility))


@bp.post("/cosmetics/facilities/<fid>/renewals")
def file_renewal(fid):
    auth = access.authorize("FacilityRegistrant")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))

    def validate():
        payload = body if body is not None else {}
        ctx.kind = schema.enum_field(payload, "renewal_kind", ("STANDARD", "ABBREVIATED"))

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_FACILITY, lambda: access.state_error(
        ctx.facility["registration_status"] in ("REGISTERED", "RENEWAL_DUE", "LAPSED"),
        "ERR_INVALID_FACILITY_STATE"))

    def renewal_window():
        open_date = ctx.facility["renewal_window_open_date"]
        access.state_error(open_date is not None and store.today() >= open_date,
                           "ERR_RENEWAL_WINDOW_NOT_OPEN")

    checks.add(access.R_RENEWAL_WINDOW, renewal_window)

    def grace():
        grace_end = ctx.facility["grace_end_date"]
        access.state_error(grace_end is not None and store.today() <= grace_end,
                           "ERR_GRACE_PERIOD_EXPIRED")

    checks.add(access.R_GRACE, grace)
    checks.add(access.R_ABBREVIATED, lambda: access.state_error(
        ctx.kind != "ABBREVIATED" or domain.abbreviated_renewal_eligible(ctx.facility),
        "ERR_ABBREVIATED_RENEWAL_NOT_ELIGIBLE"))
    checks.run()

    facility = ctx.facility
    was_lapsed = facility["registration_status"] == "LAPSED"
    predecessor = domain.active_period(facility) or domain.latest_period(facility)
    domain.expire_active_period(facility)
    prior_end = predecessor["period_end"] if predecessor else facility["current_period_end"]
    prior_index = predecessor["sequence_index"] if predecessor else 0
    period_kind = "RENEWAL" if store.today() <= prior_end else "LATE_RENEWAL"
    period = domain.create_period(facility, period_kind, prior_end + timedelta(days=1), prior_index + 1)
    facility["registration_cycle_count"] += 1
    facility["registration_status"] = "REGISTERED"
    changed, before, after, escalated = domain.recompute_posture(facility)
    store.touch(facility)

    if was_lapsed:
        restored = domain.restore_after_late_renewal(facility)
        domain.ledger_append(
            facility["id"], "POSTURE_CHANGE", "Facility", facility["id"],
            "Compliance posture recomputed after a late renewal inside the grace window.",
            posture_before=before, posture_after=after,
        )
        for listing in restored:
            domain.ledger_append(
                facility["id"], "STATE_TRANSITION", "ProductListing", listing["id"],
                "Listing restored after the establishment renewed inside the grace window.",
            )
    else:
        domain.ledger_append(facility["id"], "STATE_TRANSITION", "Facility", facility["id"],
                             "renewal accepted")
    return envelope.created(domain.period_json(period))


@bp.get("/cosmetics/facilities/<fid>/registration-periods")
def list_periods(fid):
    auth = access.authorize("FacilityRegistrant", "RegulatoryReviewer", "EnforcementOfficer",
                            "SystemOperator")
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))
    checks.run()
    from flask import request
    records = sorted(domain.periods_of_facility(fid), key=lambda p: p["sequence_index"])
    # PRD §3.1: "the listing may be narrowed with a `status` filter."
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    return envelope.paginate(records, domain.period_json)


# ---------------------------------------------------------- ownership changes
@bp.post("/cosmetics/facilities/<fid>/ownership-changes")
def file_ownership_change(fid):
    auth = access.authorize("FacilityRegistrant")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))

    def validate():
        payload = body if body is not None else {}
        ctx.new_owner = schema.string_field(payload, "new_owner_operator_name", max_len=200)
        ctx.effective = schema.day_field(payload, "change_effective_date")
        ctx.expected = schema.int_field(payload, "expected_facility_version", minimum=0)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STALE_FACILITY, lambda: access.state_error(
        ctx.expected == ctx.facility["version"], "ERR_STALE_FACILITY_VERSION"))
    checks.run()

    facility = ctx.facility
    for filing in store.by_created(domain.ownership_changes_of_facility(facility["id"])):
        if filing["status"] == "FILED":
            filing["status"] = "SUPERSEDED"
            store.touch(filing)

    filed_at = store.now()
    deadline = store.end_of_day(ctx.effective + timedelta(days=domain.OWNERSHIP_FILING_DEADLINE_DAYS))
    filing = store.insert("ownership_changes", {
        "facility_id": facility["id"],
        "new_owner_operator_name": ctx.new_owner,
        "change_effective_date": ctx.effective,
        "filed_at": filed_at,
        "filing_deadline_at": deadline,
        "is_late_filing": filed_at > deadline,
        "status": "FILED",
        "decision_note": None,
        "decided_by_user_id": None,
    })
    store.touch(facility)
    return envelope.created(domain.ownership_change_json(filing))


@bp.get("/cosmetics/facilities/<fid>/ownership-changes")
def list_ownership_changes(fid):
    auth = access.authorize("FacilityRegistrant", "RegulatoryReviewer", "SystemOperator")
    from flask import request
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))
    checks.run()
    records = domain.ownership_changes_of_facility(fid)
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    return envelope.paginate(store.by_created_desc(records), domain.ownership_change_json)


@bp.post("/cosmetics/ownership-changes/<oid>/decision")
def decide_ownership_change(oid):
    auth = access.authorize("RegulatoryReviewer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_OWNERSHIP_CHANGE,
               lambda: ctx.set("filing", access.need_ownership_change(oid)))

    def validate():
        payload = body if body is not None else {}
        ctx.decision = schema.enum_field(payload, "decision", ("ACCEPT", "REJECT"))
        ctx.note = schema.string_field(payload, "decision_note", required=False, max_len=1000, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_OWNERSHIP, lambda: access.state_error(
        ctx.filing["status"] == "FILED", "ERR_INVALID_OWNERSHIP_CHANGE_STATE"))
    checks.run()

    filing = ctx.filing
    facility = store.get("facilities", filing["facility_id"])
    filing["decision_note"] = ctx.note
    filing["decided_by_user_id"] = auth.user_id
    filing["status"] = "ACCEPTED" if ctx.decision == "ACCEPT" else "REJECTED"
    store.touch(filing)
    if ctx.decision == "ACCEPT":
        facility["owner_operator_name"] = filing["new_owner_operator_name"]
        store.touch(facility)
        domain.ledger_append(facility["id"], "OWNERSHIP_CHANGE", "OwnershipChangeUpdate",
                             filing["id"], "Ownership change accepted.")
    return envelope.ok(domain.ownership_change_json(filing))


@bp.get("/cosmetics/facilities/<fid>/ledger-entries")
def list_ledger(fid):
    auth = access.authorize("FacilityRegistrant", "RegulatoryReviewer", "EnforcementOfficer",
                            "SystemOperator")
    from flask import request
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))
    checks.run()
    records = domain.ledger_of_facility(fid)
    entry_type = request.args.get("entry_type")
    if entry_type:
        records = [r for r in records if r["entry_type"] == entry_type]
    subject_entity = request.args.get("subject_entity")
    if subject_entity:
        records = [r for r in records if r["subject_entity"] == subject_entity]
    records = sorted(records, key=lambda r: r["sequence_no"])
    return envelope.paginate(records, domain.ledger_json)


# --------------------------------------------------------------- inspections
@bp.post("/cosmetics/facilities/<fid>/inspections")
def schedule_inspection(fid):
    access.authorize("RegulatoryReviewer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))

    def validate():
        payload = body if body is not None else {}
        ctx.itype = schema.enum_field(payload, "inspection_type", domain.INSPECTION_TYPES)
        ctx.start = schema.day_field(payload, "window_start")
        ctx.end = schema.day_field(payload, "window_end")

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_WINDOW_BOUNDS, lambda: access.state_error(
        ctx.start < ctx.end, "ERR_INVALID_WINDOW_BOUNDS"))
    checks.add(access.R_NOT_REGISTERED, lambda: access.state_error(
        ctx.facility["registration_status"] in domain.ADMISSIBLE_REGISTERED,
        "ERR_FACILITY_NOT_REGISTERED"))

    def containment():
        facility = ctx.facility
        start = facility["current_period_start"]
        end = facility["current_period_end"]
        inside = (
            start is not None and end is not None
            and ctx.start >= start
            and (ctx.end - timedelta(days=1)) <= end
        )
        access.state_error(inside, "ERR_INSPECTION_OUTSIDE_REGISTRATION_PERIOD")

    checks.add(access.R_INSPECTION_PERIOD, containment)

    def open_engagements():
        return [
            e for e in domain.inspections_of_facility(fid)
            if e["status"] not in domain.INSPECTION_TERMINAL_STATUSES
        ]

    def buffer_rule():
        for other in open_engagements():
            if other["inspection_type"] != ctx.itype:
                continue
            before_gap = (other["window_start"] - ctx.end).days
            after_gap = (ctx.start - other["window_end"]).days
            if before_gap >= 7 or after_gap >= 7:
                continue
            raise ApiError("ERR_INSPECTION_TYPE_BUFFER_VIOLATION")

    checks.add(access.R_BUFFER, buffer_rule)

    def overlap_rule():
        for other in open_engagements():
            if ctx.start < other["window_end"] and other["window_start"] < ctx.end:
                raise ApiError("ERR_INSPECTION_WINDOW_OVERLAP")

    checks.add(access.R_OVERLAP, overlap_rule)
    checks.run()

    engagement = store.insert("inspections", {
        "facility_id": fid,
        "inspection_type": ctx.itype,
        "window_start": ctx.start,
        "window_end": ctx.end,
        "status": "SCHEDULED",
        "observation_count": 0,
        "category_subscores": None,
        "readiness_score": None,
        "outcome_class": None,
        "response_due_at": None,
        "response_submitted_at": None,
        "response_summary": None,
    })
    return envelope.created(domain.inspection_json(engagement))


@bp.get("/cosmetics/facilities/<fid>/inspections")
def list_inspections(fid):
    auth = access.authorize("FacilityRegistrant", "RegulatoryReviewer", "EnforcementOfficer",
                            "SystemOperator")
    from flask import request
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=ctx.facility["id"]))
    checks.run()
    records = domain.inspections_of_facility(fid)
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    itype = request.args.get("inspection_type")
    if itype:
        records = [r for r in records if r["inspection_type"] == itype]
    records = sorted(records, key=lambda r: (r["window_start"], r["_seq"]))
    return envelope.paginate(records, domain.inspection_json)


@bp.post("/cosmetics/facilities/<fid>/inspections/<inspection_id>/observations")
def issue_observations(fid, inspection_id):
    access.authorize("RegulatoryReviewer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_INSPECTION,
               lambda: ctx.set("engagement", access.need_inspection(inspection_id, fid)))

    def validate():
        payload = body if body is not None else {}
        items = schema.object_list_field(payload, "observations")
        for item in items:
            schema.enum_field(item, "category", calc.OBSERVATION_CATEGORIES)
            schema.enum_field(item, "severity", tuple(calc.SEVERITY_WEIGHT.keys()))
        ctx.observations = items

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_INSPECTION, lambda: access.state_error(
        ctx.engagement["status"] == "SCHEDULED", "ERR_INVALID_INSPECTION_STATE"))
    checks.run()

    engagement = ctx.engagement
    facility = ctx.facility
    score, subscores = calc.gmp_readiness(ctx.observations)
    engagement["observation_count"] = len(ctx.observations)
    engagement["category_subscores"] = subscores
    engagement["readiness_score"] = score
    facility["gmp_readiness_score"] = score
    if score >= domain.GMP_NAI_THRESHOLD:
        engagement["status"] = "CLOSED_NAI"
        engagement["outcome_class"] = "NAI"
        engagement["response_due_at"] = None
        facility["last_inspection_outcome"] = "NAI"
        store.touch(engagement)
        store.touch(facility)
        domain.ledger_append(facility["id"], "INSPECTION_OUTCOME", "InspectionEngagement",
                             engagement["id"], "Inspection engagement closed as NAI.")
    else:
        engagement["status"] = "OBSERVATIONS_ISSUED"
        engagement["outcome_class"] = "PENDING_RESPONSE"
        engagement["response_due_at"] = store.end_of_day(
            store.today() + timedelta(days=domain.RESPONSE_WINDOW_DAYS))
        store.touch(engagement)
        store.touch(facility)
    return envelope.ok(domain.inspection_json(engagement))


@bp.post("/cosmetics/facilities/<fid>/inspections/<inspection_id>/response")
def submit_inspection_response(fid, inspection_id):
    auth = access.authorize("FacilityRegistrant")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_FACILITY, lambda: ctx.set("facility", access.need_facility(fid)))
    checks.add(access.R_INSPECTION,
               lambda: ctx.set("engagement", access.need_inspection(inspection_id, fid)))
    checks.add(access.R_OWNER, lambda: access.check_owner(auth, facility_id=fid))

    def validate():
        payload = body if body is not None else {}
        ctx.summary = schema.string_field(payload, "response_summary", max_len=2000)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_INSPECTION, lambda: access.state_error(
        ctx.engagement["status"] == "OBSERVATIONS_ISSUED", "ERR_INVALID_INSPECTION_STATE"))
    checks.add(access.R_RESPONSE_WINDOW, lambda: access.state_error(
        ctx.engagement["response_due_at"] is not None
        and store.now() <= ctx.engagement["response_due_at"],
        "ERR_INSPECTION_RESPONSE_WINDOW_CLOSED"))
    checks.run()

    engagement = ctx.engagement
    engagement["status"] = "RESPONSE_SUBMITTED"
    engagement["response_submitted_at"] = store.now()
    engagement["response_summary"] = ctx.summary
    store.touch(engagement)
    return envelope.ok(domain.inspection_json(engagement))
