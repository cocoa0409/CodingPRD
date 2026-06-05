"""MDS assessment endpoints: schedule, fetch, list, start, complete, reopen,
submit, correct (PRD §3.4)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from clock import parse_iso, to_utc_date
from gate import gate
from services import calc, lookups


ASSESSMENT_TYPES = {"ADMISSION_5DAY", "INTERIM_IPA", "DISCHARGE"}


def _target_day(assessment_type):
    # Computed stay-day the assessment is anchored to (PRD §3.4): day 5 for the
    # 5-day. INTERIM_IPA / DISCHARGE are not anchored to a fixed schedule day.
    if assessment_type == "ADMISSION_5DAY":
        return 5
    return None


def _stay_day_index(admit_at_iso, ard_iso):
    """1-based stay-day index of an ARD relative to admit (PRD §3.4/§3.9)."""
    admit_d = to_utc_date(parse_iso(admit_at_iso))
    ard_d = to_utc_date(parse_iso(ard_iso))
    return (ard_d - admit_d).days + 1


def _ard_in_window(assessment, admission):
    """Return True iff assessment_reference_date falls in the type's ARD window
    (PRD §3.4)."""
    atype = assessment["assessment_type"]
    ard = assessment["assessment_reference_date"]
    if atype == "ADMISSION_5DAY":
        # stay-days 1..8 inclusive (admit day == day 1).
        idx = _stay_day_index(admission["admit_at"], ard)
        return 1 <= idx <= 8
    if atype == "INTERIM_IPA":
        # any day after the 5-day ARD (i.e., stay-day index > 5).
        idx = _stay_day_index(admission["admit_at"], ard)
        return idx > 5
    if atype == "DISCHARGE":
        # [discharge_planned_at - 2d, discharge_planned_at + 14d]. The
        # discharge-planned moment is when the admission entered
        # DISCHARGE_PLANNED; absent an explicit field, use updated_at at the
        # time of planning. We approximate the planned moment with the
        # admission's discharge_at if set, else its updated_at.
        anchor_iso = admission.get("discharge_at") or admission.get("updated_at")
        if anchor_iso is None:
            return False
        anchor_d = to_utc_date(parse_iso(anchor_iso))
        ard_d = to_utc_date(parse_iso(ard))
        delta = (ard_d - anchor_d).days
        return -2 <= delta <= 14
    return False


def _ard_window_bounds(assessment, admission):
    """Return the inclusive [start_date, end_date] ARD window for conflict
    detection (PRD §3.4). Windows are inclusive-closed."""
    atype = assessment["assessment_type"]
    admit_d = to_utc_date(parse_iso(admission["admit_at"]))
    if atype == "ADMISSION_5DAY":
        # stay-days 1..8 -> admit_d .. admit_d+7
        return admit_d, admit_d + _days(7)
    if atype == "INTERIM_IPA":
        # any day after day 5: open-ended; bound it at the assessment's own ARD
        # so that two INTERIM_IPA windows conflict only by sharing the same ARD
        # date region. Use a point window on the ARD date.
        ard_d = to_utc_date(parse_iso(assessment["assessment_reference_date"]))
        return ard_d, ard_d
    if atype == "DISCHARGE":
        anchor_iso = admission.get("discharge_at") or admission.get("updated_at")
        anchor_d = to_utc_date(parse_iso(anchor_iso)) if anchor_iso else admit_d
        return anchor_d - _days(2), anchor_d + _days(14)
    ard_d = to_utc_date(parse_iso(assessment["assessment_reference_date"]))
    return ard_d, ard_d


def _days(n):
    import datetime
    return datetime.timedelta(days=n)


def register(app):
    @app.route("/snf/admissions/<aid>/assessments", methods=["POST"])
    def schedule_assessment(aid):
        gate(["MdsCoordinator"])
        adm = lookups.get_admission(aid)
        body = V.get_body()
        atype = V.as_enum(V.require(body, "assessment_type"), "assessment_type", ASSESSMENT_TYPES)
        ard = V.require(body, "assessment_reference_date")
        V.as_datetime(ard, "assessment_reference_date")
        pt = V.as_int(V.require(body, "pt_function_score"), "pt_function_score", minimum=0, maximum=24)
        slp = V.as_int(V.require(body, "slp_components_count"), "slp_components_count", minimum=0, maximum=3)
        nta = V.as_int(V.require(body, "nta_comorbidity_points"), "nta_comorbidity_points", minimum=0, maximum=20)
        obj = {
            "admission_id": aid,
            "assessment_type": atype,
            "target_day": _target_day(atype),
            "assessment_reference_date": ard,
            "corrects_assessment_id": None,
            "pt_function_score": pt,
            "slp_components_count": slp,
            "nta_comorbidity_points": nta,
            "pt_ot_case_mix_group": None,
            "slp_case_mix_group": None,
            "nta_case_mix_group": None,
            "status": "SCHEDULED",
        }
        db.stamp_create(obj)
        db.assessments[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/admissions/<aid>/assessments", methods=["GET"])
    def list_admission_assessments(aid):
        gate(["MdsCoordinator", "BillingAnalyst"])
        lookups.get_admission(aid)
        limit, offset = V.pagination(request.args)
        rows = lookups.assessments_for_admission(aid)
        atype = request.args.get("assessment_type")
        if atype is not None:
            rows = [r for r in rows if r["assessment_type"] == atype]
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/assessments/<asid>", methods=["GET"])
    def get_assessment(asid):
        gate(["MdsCoordinator", "BillingAnalyst"])
        obj = lookups.get_assessment(asid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/assessments", methods=["GET"])
    def list_assessments():
        gate(["MdsCoordinator", "BillingAnalyst"])
        limit, offset = V.pagination(request.args)
        rows = list(db.assessments.values())
        for key in ("corrects_assessment_id", "admission_id", "status"):
            val = request.args.get(key)
            if val is not None:
                rows = [r for r in rows if r.get(key) == val]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/assessments/<asid>/start", methods=["POST"])
    def start_assessment(asid):
        gate(["MdsCoordinator"])
        obj = lookups.get_assessment(asid)
        if obj["status"] != "SCHEDULED":
            raise errors.err(errors.ERR_INVALID_STATE, "assessment is not SCHEDULED")
        adm = db.admissions.get(obj["admission_id"])
        # Parent admission must be ACTIVE/NON_COVERED/DISCHARGE_PLANNED (PRD §3.4).
        if adm is None or adm["status"] not in ("ACTIVE", "NON_COVERED", "DISCHARGE_PLANNED"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "parent admission is not in a startable state")
        # Temporal guard 1: ARD window (priority 9).
        if not _ard_in_window(obj, adm):
            raise errors.err(errors.ERR_ARD_OUT_OF_WINDOW,
                             "assessment_reference_date is outside the type's ARD window")
        # Temporal guard 2: window conflict with another non-superseded
        # assessment of the same type (priority 11). Windows inclusive-closed;
        # adjacency at a boundary IS a conflict.
        my_start, my_end = _ard_window_bounds(obj, adm)
        for other in lookups.assessments_for_admission(adm["id"]):
            if other["id"] == obj["id"]:
                continue
            # A correction supersedes its target on submission; it must be
            # startable while the target is still SUBMITTED, so the target it
            # directly corrects is not a conflicting "other" (PRD §3.4).
            if obj.get("corrects_assessment_id") == other["id"]:
                continue
            if other["assessment_type"] != obj["assessment_type"]:
                continue
            if other["status"] == "SUPERSEDED":
                continue
            o_start, o_end = _ard_window_bounds(other, adm)
            # Inclusive overlap including touching endpoints.
            if my_start <= o_end and o_start <= my_end:
                raise errors.err(errors.ERR_ASSESSMENT_WINDOW_CONFLICT,
                                 "ARD window conflicts with another assessment of the same type")
        obj["status"] = "IN_PROGRESS"
        db.touch(obj)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/assessments/<asid>/complete", methods=["POST"])
    def complete_assessment(asid):
        gate(["MdsCoordinator"])
        obj = lookups.get_assessment(asid)
        if obj["status"] != "IN_PROGRESS":
            raise errors.err(errors.ERR_INVALID_STATE, "assessment is not IN_PROGRESS")
        # All three clinical inputs must be present.
        for f in ("pt_function_score", "slp_components_count", "nta_comorbidity_points"):
            if obj.get(f) is None:
                raise errors.err(errors.ERR_INVALID_REQUEST, "missing %s" % f)
        pt_ot, slp, nta = calc.classify(obj)
        obj["pt_ot_case_mix_group"] = pt_ot
        obj["slp_case_mix_group"] = slp
        obj["nta_case_mix_group"] = nta
        obj["status"] = "COMPLETED"
        db.touch(obj)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/assessments/<asid>/reopen", methods=["POST"])
    def reopen_assessment(asid):
        gate(["MdsCoordinator"])
        obj = lookups.get_assessment(asid)
        if obj["status"] != "COMPLETED":
            raise errors.err(errors.ERR_INVALID_STATE, "assessment is not COMPLETED")
        # Blocked if any driven claim is FINALIZED/SUBMITTED/PAID (priority 19).
        for c in lookups.claims_for_assessment(obj["id"]):
            if c["status"] in ("FINALIZED", "SUBMITTED", "PAID"):
                raise errors.err(errors.ERR_ASSESSMENT_LOCKED_BY_CLAIM,
                                 "assessment is locked by a downstream claim")
        obj["pt_ot_case_mix_group"] = None
        obj["slp_case_mix_group"] = None
        obj["nta_case_mix_group"] = None
        obj["status"] = "IN_PROGRESS"
        db.touch(obj)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/assessments/<asid>/submit", methods=["POST"])
    def submit_assessment(asid):
        gate(["MdsCoordinator"])
        obj = lookups.get_assessment(asid)
        if obj["status"] != "COMPLETED":
            raise errors.err(errors.ERR_INVALID_STATE, "assessment is not COMPLETED")
        obj["status"] = "SUBMITTED"
        db.touch(obj)
        # If a correction, the corrected original is superseded at submission.
        if obj.get("corrects_assessment_id"):
            corrected = db.assessments.get(obj["corrects_assessment_id"])
            if corrected is not None:
                corrected["status"] = "SUPERSEDED"
                db.touch(corrected)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/assessments/<asid>/correct", methods=["POST"])
    def correct_assessment(asid):
        gate(["MdsCoordinator"])
        target = lookups.get_assessment(asid)
        body = V.get_body()
        atype = V.as_enum(V.require(body, "assessment_type"), "assessment_type", ASSESSMENT_TYPES)
        ard = V.require(body, "assessment_reference_date")
        V.as_datetime(ard, "assessment_reference_date")
        pt = V.as_int(V.require(body, "pt_function_score"), "pt_function_score", minimum=0, maximum=24)
        slp = V.as_int(V.require(body, "slp_components_count"), "slp_components_count", minimum=0, maximum=3)
        nta = V.as_int(V.require(body, "nta_comorbidity_points"), "nta_comorbidity_points", minimum=0, maximum=20)
        expected_version = V.as_int(V.require(body, "expected_assessment_version"),
                                    "expected_assessment_version")
        # State (priority 21): the corrected target must be SUBMITTED.
        if target["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "target assessment is not SUBMITTED")
        # OCC (priority 20): expected_assessment_version must match (PRD §2.6).
        if expected_version != target.get("version"):
            raise errors.err(errors.ERR_STALE_VERSION,
                             "expected_assessment_version does not match target version")
        obj = {
            "admission_id": target["admission_id"],
            "assessment_type": atype,
            "target_day": _target_day(atype),
            "assessment_reference_date": ard,
            "corrects_assessment_id": target["id"],
            "pt_function_score": pt,
            "slp_components_count": slp,
            "nta_comorbidity_points": nta,
            "pt_ot_case_mix_group": None,
            "slp_case_mix_group": None,
            "nta_case_mix_group": None,
            "status": "SCHEDULED",
        }
        db.stamp_create(obj)
        db.assessments[obj["id"]] = obj
        # Increment the corrected assessment's version by one (PRD §3.4).
        db.touch(target)
        return response.success(serialize.public(obj), 201)
