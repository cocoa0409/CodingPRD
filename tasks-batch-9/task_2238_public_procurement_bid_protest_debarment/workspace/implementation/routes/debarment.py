"""Suspension, debarment and reinstatement (PRD §3.9)."""

from flask import Blueprint, g

import calc
import serializers
import services
import store
import validation as v
from errors import ApiError
from util import add_days, add_months, months_between

bp = Blueprint("debarment", __name__)

CAUSE_CODES = (
    "FRAUD", "BID_RIGGING", "REPEATED_NONPERFORMANCE", "FALSE_CERTIFICATION",
    "SAFETY_VIOLATION", "ADMINISTRATIVE_DEFAULT",
)
MITIGATING_CODES = ("SELF_DISCLOSURE", "RESTITUTION_PAID", "COMPLIANCE_PROGRAM", "COOPERATION")
EVIDENCE_CODES = (
    "RESTITUTION_COMPLETE", "MANAGEMENT_REPLACED", "COMPLIANCE_AUDIT_PASSED",
    "TRAINING_COMPLETED",
)
LIVE_PROCEEDING_STATUSES = ("NOTICE_ISSUED", "RESPONSE_RECEIVED", "HEARING_HELD")


def _occupancy_end(proceeding):
    if proceeding["status"] == "DEBARRED":
        return proceeding["debarment_end_utc"]
    if proceeding["status"] == "DISMISSED":
        return proceeding["decided_at_utc"]
    return add_days(
        proceeding["notice_issued_at_utc"], calc.LIVE_PROCEEDING_OCCUPANCY_DAYS
    )


# --------------------------------------------------------------------------- #
# proceedings
# --------------------------------------------------------------------------- #

@bp.post("/procurement/debarment-proceedings")
@v.endpoint(["DebarmentAuthority"])
def open_proceeding():
    data = v.body()
    vendor_id = v.req_str(data, "vendor_id")
    cause_code = v.req_enum(data, "cause_code", CAUSE_CODES)
    aggravating = v.code_array(
        data, "aggravating_factor_codes", CAUSE_CODES, required=True, non_empty=True
    )
    mitigating = v.code_array(data, "mitigating_factor_codes", MITIGATING_CODES)
    source_protest_id = v.opt_str(data, "source_protest_id")
    interim_suspension = v.opt_bool(data, "interim_suspension", False)

    v.distinct(aggravating, "aggravating_factor_codes")
    v.distinct(mitigating, "mitigating_factor_codes")

    vendor = services.must("vendors", vendor_id)
    source_protest = None
    if source_protest_id is not None:
        source_protest = services.must("protests", source_protest_id)

    severity = calc.interim_severity(aggravating)
    if interim_suspension and severity < calc.INTERIM_THRESHOLD:
        raise ApiError("ERR_INTERIM_SUSPENSION_THRESHOLD_NOT_MET")

    notice_instant = store.now()
    for other in services.proceedings_of_vendor(vendor):
        end = _occupancy_end(other)
        if end is None:
            continue
        if other["notice_issued_at_utc"] <= notice_instant <= end:
            raise ApiError("ERR_ACTIVE_PROCEEDING_EXISTS")

    if vendor["eligibility_status"] == "DEBARRED":
        raise ApiError("ERR_VENDOR_ALREADY_DEBARRED")

    proceeding = store.insert("proceedings", store.row("proceedings", {
        "vendor_id": vendor["id"],
        "source_protest_id": source_protest["id"] if source_protest else None,
        "cause_code": cause_code,
        "aggravating_factor_codes": list(aggravating),
        "mitigating_factor_codes": list(mitigating),
        "notice_issued_at_utc": notice_instant,
        "response_deadline_utc": calc.response_deadline_from(notice_instant),
        "status": "NOTICE_ISSUED",
        "interim_status": "NONE",
        "aggravating_total_points": calc.aggravating_total(aggravating),
        "mitigating_credit_points": 0,
        "severity_score": severity,
        "debarment_period_months": 0,
        "debarment_start_utc": None,
        "debarment_end_utc": None,
        "strikes_applied": 0,
        "response_narrative": None,
        "decided_at_utc": None,
    }))

    if interim_suspension:
        proceeding["interim_status"] = "INTERIM_SUSPENDED"
        proceeding["strikes_applied"] = 1
        services.suspend_vendor(vendor, proceeding)

    return ("obj", proceeding, serializers.proceeding, 201)


@bp.get("/procurement/debarment-proceedings/<proceeding_id>")
@v.endpoint(v.ALL_ROLES)
def read_proceeding(proceeding_id):
    return ("obj", services.must("proceedings", proceeding_id),
            serializers.proceeding, 200)


@bp.get("/procurement/debarment-proceedings")
@v.endpoint(v.ALL_ROLES)
def list_proceedings():
    limit, offset = v.pagination()
    filters = {
        "vendor_id": v.query("vendor_id"),
        "source_protest_id": v.query("source_protest_id"),
        "status": v.query("status"),
        "interim_status": v.query("interim_status"),
    }
    rows = [r for r in store.ordered(store.values("proceedings")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.proceeding, limit, offset, total)


@bp.post("/procurement/debarment-proceedings/<proceeding_id>/response")
@v.endpoint(["Vendor"])
def file_response(proceeding_id):
    data = v.body()
    narrative = v.req_str(data, "response_narrative")
    mitigating = v.code_array(data, "mitigating_factor_codes", MITIGATING_CODES)
    v.distinct(mitigating, "mitigating_factor_codes")

    proceeding = services.must("proceedings", proceeding_id)

    if g.user_id != proceeding["vendor_id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")
    if proceeding["status"] != "NOTICE_ISSUED":
        raise ApiError("ERR_INVALID_PROCEEDING_STATE")
    if store.now() > proceeding["response_deadline_utc"]:
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED")

    merged = list(proceeding["mitigating_factor_codes"])
    for code in mitigating:
        if code not in merged:
            merged.append(code)
    v.set_field(proceeding, "mitigating_factor_codes", merged)
    v.set_field(proceeding, "response_narrative", narrative)
    v.set_field(proceeding, "status", "RESPONSE_RECEIVED")
    v.touch(proceeding)
    return ("obj", proceeding, serializers.proceeding, 200)


@bp.post("/procurement/debarment-proceedings/<proceeding_id>/hearing")
@v.endpoint(["DebarmentAuthority"])
def hold_hearing(proceeding_id):
    data = v.body()
    v.req_str(data, "hearing_summary")

    proceeding = services.must("proceedings", proceeding_id)
    if proceeding["status"] not in ("NOTICE_ISSUED", "RESPONSE_RECEIVED"):
        raise ApiError("ERR_INVALID_PROCEEDING_STATE")
    if proceeding["status"] == "NOTICE_ISSUED":
        if not store.now() > proceeding["response_deadline_utc"]:
            raise ApiError("ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED")

    v.set_field(proceeding, "status", "HEARING_HELD")
    v.touch(proceeding)
    return ("obj", proceeding, serializers.proceeding, 200)


@bp.post("/procurement/debarment-proceedings/<proceeding_id>/decision")
@v.endpoint(["DebarmentAuthority"])
def decide_proceeding(proceeding_id):
    data = v.body()
    outcome = v.req_enum(data, "outcome", ("DEBARRED", "DISMISSED"))
    v.req_str(data, "rationale")

    proceeding = services.must("proceedings", proceeding_id)
    vendor = services.must("vendors", proceeding["vendor_id"])

    if proceeding["status"] != "HEARING_HELD":
        raise ApiError("ERR_INVALID_PROCEEDING_STATE")

    if outcome == "DEBARRED":
        prior_strikes = vendor["debarment_strike_count"] - proceeding["strikes_applied"]
        severity, credit, _agg = calc.final_severity(
            proceeding["aggravating_factor_codes"],
            proceeding["mitigating_factor_codes"],
            max(0, prior_strikes),
        )
        months = calc.debarment_period_months(severity)
        if months == 0:
            raise ApiError("ERR_SEVERITY_BELOW_DEBARMENT_FLOOR")

        start = store.now()
        v.set_field(proceeding, "severity_score", severity)
        v.set_field(proceeding, "mitigating_credit_points", credit)
        v.set_field(proceeding, "debarment_period_months", months)
        v.set_field(proceeding, "debarment_start_utc", start)
        v.set_field(proceeding, "debarment_end_utc", add_months(start, months))
        v.set_field(proceeding, "decided_at_utc", start)
        v.set_field(proceeding, "strikes_applied", 1)
        if proceeding["interim_status"] == "INTERIM_SUSPENDED":
            v.set_field(proceeding, "interim_status", "INTERIM_LIFTED")
        v.set_field(proceeding, "status", "DEBARRED")
        v.touch(proceeding)
        services.debar_vendor(vendor, proceeding)
    else:
        v.set_field(proceeding, "decided_at_utc", store.now())
        v.set_field(proceeding, "status", "DISMISSED")
        v.touch(proceeding)
        if proceeding["interim_status"] == "INTERIM_SUSPENDED":
            v.set_field(proceeding, "strikes_applied", 0)
            v.set_field(proceeding, "interim_status", "INTERIM_LIFTED")
            services.restore_vendor(vendor, ("BLOCKED_SUSPENDED",))

    return ("obj", proceeding, serializers.proceeding, 200)


# --------------------------------------------------------------------------- #
# reinstatement petitions
# --------------------------------------------------------------------------- #

@bp.post("/procurement/debarment-proceedings/<proceeding_id>/reinstatement-petitions")
@v.endpoint(["Vendor"])
def file_petition(proceeding_id):
    data = v.body()
    evidence = v.code_array(
        data, "remediation_evidence_codes", EVIDENCE_CODES, required=True, non_empty=True
    )
    narrative = v.req_str(data, "narrative")
    expected_version = v.req_int(data, "expected_proceeding_version")
    v.distinct(evidence, "remediation_evidence_codes")

    proceeding = services.must("proceedings", proceeding_id)
    vendor = services.must("vendors", proceeding["vendor_id"])

    if g.user_id != proceeding["vendor_id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")
    if expected_version != proceeding["version"]:
        raise ApiError("ERR_STALE_PROCEEDING_VERSION")
    if proceeding["status"] != "DEBARRED":
        raise ApiError("ERR_INVALID_PROCEEDING_STATE")

    earliest = calc.earliest_petition_instant(
        proceeding["debarment_start_utc"], proceeding["debarment_period_months"]
    )
    if store.now() < earliest:
        raise ApiError("ERR_PETITION_PREMATURE")

    if any(p["status"] == "FILED" for p in services.petitions_of(proceeding)):
        raise ApiError("ERR_PETITION_ALREADY_PENDING")

    filed_at = store.now()
    petition = store.insert("petitions", store.row("petitions", {
        "proceeding_id": proceeding["id"],
        "remediation_evidence_codes": list(evidence),
        "narrative": narrative,
        "filed_at_utc": filed_at,
        "status": "FILED",
        "months_served_at_filing": months_between(proceeding["debarment_start_utc"], filed_at),
        "decided_at_utc": None,
        "decision_rationale": None,
    }))
    v.touch(proceeding)
    return ("obj", petition, serializers.petition, 201)


@bp.get("/procurement/debarment-proceedings/<proceeding_id>/reinstatement-petitions")
@v.endpoint(v.ALL_ROLES)
def list_petitions(proceeding_id):
    limit, offset = v.pagination()
    proceeding = services.must("proceedings", proceeding_id)
    status = v.query("status")
    rows = [
        p for p in services.petitions_of(proceeding)
        if status is None or p["status"] == status
    ]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.petition, limit, offset, total)


@bp.get("/procurement/reinstatement-petitions/<petition_id>")
@v.endpoint(v.ALL_ROLES)
def read_petition(petition_id):
    return ("obj", services.must("petitions", petition_id), serializers.petition, 200)


@bp.post("/procurement/reinstatement-petitions/<petition_id>/decision")
@v.endpoint(["DebarmentAuthority"])
def decide_petition(petition_id):
    data = v.body()
    outcome = v.req_enum(data, "outcome", ("GRANTED", "DENIED"))
    rationale = v.req_str(data, "decision_rationale")

    petition = services.must("petitions", petition_id)
    proceeding = services.must("proceedings", petition["proceeding_id"])
    vendor = services.must("vendors", proceeding["vendor_id"])

    if proceeding["status"] != "DEBARRED":
        raise ApiError("ERR_INVALID_PROCEEDING_STATE")
    if petition["status"] != "FILED":
        raise ApiError("ERR_INVALID_PETITION_STATE")

    v.set_field(petition, "status", outcome)
    v.set_field(petition, "decided_at_utc", store.now())
    v.set_field(petition, "decision_rationale", rationale)
    v.touch(petition)

    if outcome == "GRANTED":
        v.set_field(proceeding, "strikes_applied", 0)
        services.restore_vendor(vendor, ("BLOCKED_DEBARRED",))

    return ("obj", petition, serializers.petition, 200)
