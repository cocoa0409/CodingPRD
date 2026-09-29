"""Personnel, QualificationCredit and RadiologistAuditCycle endpoints."""

from flask import Blueprint, g, request

import services as svc
from common import (
    ALL_ROLES, DB, ROLE_COORDINATOR, ROLE_QA, body_dict, endpoint, fail,
    filter_rows, new_entity, ok_entity, ok_list, ok_object, sort_rows, touch,
    v_dt, v_enum, v_int, v_num, v_str,
)

bp = Blueprint("personnel", __name__)

CREDIT_TYPES = ("CATEGORY_1_CE", "READ_VOLUME")
MODALITIES = ("DM_2D", "DBT_3D")
VARIANTS = ("PPV1_SCREENING", "PPV3_BIOPSY_ALL")


def _person_or_404(personnel_id):
    person = DB.get("personnel", personnel_id)
    if person is None:
        fail("ERR_PERSONNEL_NOT_FOUND", "personnel %s does not exist" % personnel_id)
    return person


def _cycle_or_404(cycle_id):
    cycle = DB.get("cycle", cycle_id)
    if cycle is None:
        fail("ERR_AUDIT_CYCLE_NOT_FOUND", "audit cycle %s does not exist" % cycle_id)
    return cycle


@bp.route("/personnel/<personnel_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def personnel_read(personnel_id):
    return ok_entity(_person_or_404(personnel_id))


# ---------------------------------------------------------------------------
# QualificationCredit
# ---------------------------------------------------------------------------
@bp.route("/personnel/<personnel_id>/credits", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def credit_create(personnel_id):
    _person_or_404(personnel_id)
    body = body_dict()
    credit_type = v_enum(body, "credit_type", CREDIT_TYPES, True)
    awarded_on = v_dt(body, "awarded_on", True)
    ce_hours = v_num(body, "ce_hours", False, default=None)
    exam_count = v_int(body, "exam_count", False, default=None)
    modality = v_enum(body, "modality", MODALITIES, False, default=None)
    source_note = v_str(body, "source_note", False, default=None)

    if credit_type == "CATEGORY_1_CE":
        if ce_hours is None:
            fail("ERR_INVALID_REQUEST", "ce_hours is required for CATEGORY_1_CE")
        if exam_count is not None:
            fail("ERR_INVALID_REQUEST", "exam_count may only accompany READ_VOLUME")
    else:
        if exam_count is None:
            fail("ERR_INVALID_REQUEST", "exam_count is required for READ_VOLUME")
        if ce_hours is not None:
            fail("ERR_INVALID_REQUEST", "ce_hours may only accompany CATEGORY_1_CE")
    if ce_hours is not None and ce_hours <= 0:
        fail("ERR_INVALID_REQUEST", "ce_hours must be greater than 0")
    if exam_count is not None and exam_count <= 0:
        fail("ERR_INVALID_REQUEST", "exam_count must be greater than 0")

    if awarded_on > DB.clock:
        fail("ERR_FUTURE_TIMESTAMP", "awarded_on may not be in the future")

    credit = new_entity("credit", {
        "personnel_id": personnel_id,
        "credit_type": credit_type,
        "ce_hours": ce_hours,
        "exam_count": exam_count,
        "modality": modality,
        "awarded_on": awarded_on,
        "source_note": source_note,
    })
    return ok_entity(credit, 201)


@bp.route("/personnel/<personnel_id>/credits", methods=["GET"])
@endpoint(ALL_ROLES)
def credits_list(personnel_id):
    _person_or_404(personnel_id)
    rows = [c for c in DB.all("credit") if c["personnel_id"] == personnel_id]
    rows = filter_rows(rows, {"credit_type": "credit_type"})
    return ok_list(sort_rows(rows))


@bp.route("/personnel/<personnel_id>/qualification-reviews", methods=["POST"])
@endpoint([ROLE_COORDINATOR])
def qualification_review(personnel_id):
    person = _person_or_404(personnel_id)
    body_dict()
    facility = DB.get("facility", person["facility_id"])
    policy = svc.home_policy(facility) if facility else None
    if policy is None:
        fail("ERR_STATE_POLICY_NOT_FOUND",
             "the facility's home state policy no longer exists")
    svc.evaluate_ce(person, policy)
    svc.recompute_posture(facility)
    return ok_entity(person)


# ---------------------------------------------------------------------------
# RadiologistAuditCycle
# ---------------------------------------------------------------------------
@bp.route("/personnel/<personnel_id>/audit-cycles", methods=["POST"])
@endpoint([ROLE_QA])
def audit_cycle_create(personnel_id):
    person = _person_or_404(personnel_id)
    body = body_dict()
    period_start = v_dt(body, "period_start", True)
    period_end = v_dt(body, "period_end", True)
    window_days = v_int(body, "followup_window_days", False, 30, 730, default=365)
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly after period_start")

    if person["role_type"] != "INTERPRETING_PHYSICIAN":
        fail("ERR_NOT_AN_INTERPRETING_PHYSICIAN",
             "audit cycles may only be opened for interpreting physicians")

    for peer in DB.all("cycle"):
        if peer["radiologist_id"] != personnel_id:
            continue
        if peer["status"] == "OPEN":
            fail("ERR_AUDIT_CYCLE_OVERLAP",
                 "this radiologist already has an OPEN audit cycle")
        if peer["period_start"] < period_end and period_start < peer["period_end"]:
            fail("ERR_AUDIT_CYCLE_OVERLAP",
                 "the requested period overlaps an existing audit cycle")

    cycle = new_entity("cycle", {
        "radiologist_id": personnel_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "variant_at_close": None,
        "followup_window_days": window_days,
        "screening_exam_count": None,
        "recall_count": None,
        "biopsy_count": None,
        "cancer_count": None,
        "excluded_exam_count": None,
        "recall_rate_pct": None,
        "ppv_pct": None,
        "abnormal_interpretation_flag": None,
        "locked_at": None,
    })
    return ok_entity(cycle, 201)


@bp.route("/personnel/<personnel_id>/audit-cycles", methods=["GET"])
@endpoint(ALL_ROLES)
def audit_cycles_list(personnel_id):
    _person_or_404(personnel_id)
    rows = [c for c in DB.all("cycle") if c["radiologist_id"] == personnel_id]
    rows = filter_rows(rows, {"status": "status"})
    return ok_list(sort_rows(rows))


@bp.route("/audit-cycles/<cycle_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def audit_cycle_read(cycle_id):
    return ok_entity(_cycle_or_404(cycle_id))


@bp.route("/audit-cycles/<cycle_id>/metrics", methods=["GET"])
@endpoint(ALL_ROLES)
def audit_cycle_metrics(cycle_id):
    cycle = _cycle_or_404(cycle_id)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "PPV1_SCREENING"
    if variant not in VARIANTS:
        fail("ERR_INVALID_REQUEST", "variant must be one of %s" % ", ".join(VARIANTS))
    return ok_object(svc.audit_metrics(cycle, variant))


@bp.route("/audit-cycles/<cycle_id>/close", methods=["POST"])
@endpoint([ROLE_QA])
def audit_cycle_close(cycle_id):
    cycle = _cycle_or_404(cycle_id)
    if cycle["radiologist_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the audited radiologist may not close their own cycle")
    body = body_dict()
    variant = v_enum(body, "variant", VARIANTS, True)

    if cycle["status"] not in ("OPEN", "AMENDED"):
        fail("ERR_AUDIT_CYCLE_NOT_CLOSABLE",
             "audit cycle in status %s cannot be closed" % cycle["status"])
    if cycle["status"] == "OPEN" and DB.clock < cycle["period_end"]:
        fail("ERR_AUDIT_PERIOD_NOT_ELAPSED",
             "the audit period has not elapsed yet")

    metrics = svc.audit_metrics(cycle, variant)
    for key in ("screening_exam_count", "recall_count", "biopsy_count",
                "cancer_count", "excluded_exam_count", "recall_rate_pct",
                "ppv_pct", "abnormal_interpretation_flag"):
        cycle[key] = metrics[key]
    cycle["variant_at_close"] = variant
    cycle["status"] = "LOCKED"
    cycle["locked_at"] = DB.clock
    touch(cycle)
    return ok_entity(cycle)
