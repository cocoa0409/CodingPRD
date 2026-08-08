"""Inquiries, needs assessments, and benefit guidances."""
from flask import Blueprint, request

import store
import calc
import services as svc
import validate as V
import envelope as E
import constants as C
from rbac import guard, deny_ownership
from errors import ApiError
from serialize import dump
from protected import PROTECTED

bp = Blueprint("inq", __name__)


# ===========================================================================
# Inquiries
# ===========================================================================
@bp.post("/inquiries")
def create_inquiry():
    uid, role = guard(["PlatformAdmin", "Advisor", "Family"])
    body = V.get_body()
    V.reject_protected(body, {"family_id", "origin", "region_code", "requested_care_level",
                              "target_move_in_date", "declared_budget_monthly_cents", "notes"},
                       PROTECTED["inquiry"])
    family_id = V.req_str(body, "family_id")
    origin = V.req_enum(body, "origin", C.ORIGINS)
    region_code = V.req_str(body, "region_code")
    care_level = V.req_enum(body, "requested_care_level", C.CARE_LEVELS)
    move_in = V.req_date(body, "target_move_in_date")
    budget = V.req_int(body, "declared_budget_monthly_cents", 1)
    notes = V.opt_str(body, "notes")
    family = V.lookup("families", family_id, "ERR_FAMILY_NOT_FOUND")
    if role == "Family" and uid != family_id:
        deny_ownership()
    today = store.now_date()
    if move_in < today:
        raise ApiError("ERR_MOVE_IN_DATE_INVALID", "target_move_in_date is in the past.")
    days_to_move = (move_in - today).days
    score = calc.inquiry_priority_score(care_level, days_to_move, budget)
    row = svc.new_row("inquiries", {
        "family_id": family_id, "assigned_advisor_id": None, "origin": origin,
        "region_code": region_code, "requested_care_level": care_level,
        "target_move_in_date": move_in.isoformat(),
        "declared_budget_monthly_cents": budget, "priority_score": score,
        "status": "NEW", "match_count": 0, "hold_reason": None,
        "close_reason_code": None, "notes": notes,
    })
    return E.created(dump(row))


@bp.get("/inquiries/<inquiry_id>")
def get_inquiry(inquiry_id):
    guard(C.ALL_ROLES)
    i = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    return E.ok(dump(i))


@bp.get("/inquiries")
def list_inquiries():
    guard(C.ALL_ROLES)
    rows = list(store.DB["inquiries"].values())
    for key in ("family_id", "assigned_advisor_id", "status", "region_code"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


def _own_inquiry_advisor(inquiry, uid, role):
    if role == "Advisor" and inquiry["assigned_advisor_id"] != uid:
        deny_ownership()


@bp.post("/inquiries/<inquiry_id>/assign")
def assign_inquiry(inquiry_id):
    guard(["PlatformAdmin"])
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"advisor_id"}, {"id"})
    advisor_id = V.opt_str(body, "advisor_id")
    explicit = None
    if advisor_id is not None:
        explicit = V.lookup("advisors", advisor_id, "ERR_ADVISOR_NOT_FOUND")
    if inquiry["status"] != "NEW":
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry is not NEW.")
    if explicit is None:
        candidates = []
        for a in store.DB["advisors"].values():
            svc.recompute_advisor_fields(a)
            if (a["status"] == "ACTIVE" and a["region_code"] == inquiry["region_code"]
                    and a["active_caseload_count"] < a["caseload_capacity"]):
                candidates.append(a)
        if not candidates:
            raise ApiError("ERR_NO_ELIGIBLE_ADVISOR", "No eligible advisor available.")
        candidates.sort(key=lambda a: (a["weighted_load_index"],
                                       a["active_caseload_count"], a["created_at"]))
        chosen = candidates[0]
    else:
        chosen = explicit
        if chosen["status"] != "ACTIVE" or chosen["region_code"] != inquiry["region_code"]:
            raise ApiError("ERR_ADVISOR_NOT_ELIGIBLE", "Advisor not eligible.")
        svc.recompute_advisor_fields(chosen)
        if chosen["active_caseload_count"] >= chosen["caseload_capacity"]:
            raise ApiError("ERR_ADVISOR_CASELOAD_FULL", "Advisor caseload is full.")
    inquiry["assigned_advisor_id"] = chosen["id"]
    inquiry["status"] = "ASSIGNED"
    svc.new_row("assignments", {
        "advisor_id": chosen["id"], "inquiry_id": inquiry["id"],
        "assigned_at": store.now_iso(), "released_at": None,
        "release_reason": None, "status": "ACTIVE",
    })
    svc.recompute_advisor_fields(chosen)
    svc.touch(chosen)
    svc.touch(inquiry)
    return E.ok(dump(inquiry))


@bp.post("/inquiries/<inquiry_id>/reassign")
def reassign_inquiry(inquiry_id):
    guard(["PlatformAdmin"])
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"to_advisor_id"}, {"id"})
    to_advisor_id = V.req_str(body, "to_advisor_id")
    target = V.lookup("advisors", to_advisor_id, "ERR_ADVISOR_NOT_FOUND")
    if inquiry["status"] not in ("ASSIGNED", "ASSESSED", "MATCHING", "TOURING", "ON_HOLD"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry cannot be reassigned in its state.")
    if to_advisor_id == inquiry["assigned_advisor_id"]:
        raise ApiError("ERR_VALIDATION", "to_advisor_id must differ from the current advisor.")
    if target["status"] != "ACTIVE" or target["region_code"] != inquiry["region_code"]:
        raise ApiError("ERR_ADVISOR_NOT_ELIGIBLE", "Target advisor not eligible.")
    svc.recompute_advisor_fields(target)
    if target["active_caseload_count"] >= target["caseload_capacity"]:
        raise ApiError("ERR_ADVISOR_CASELOAD_FULL", "Target advisor caseload is full.")
    prev = svc.active_assignment_for_inquiry(inquiry["id"])
    if prev is not None:
        prev["status"] = "REASSIGNED"
        prev["released_at"] = store.now_iso()
        prev["release_reason"] = "REASSIGNED"
        svc.touch(prev)
        losing = store.DB["advisors"].get(prev["advisor_id"])
        if losing is not None:
            svc.recompute_advisor_fields(losing)
            svc.touch(losing)
    svc.new_row("assignments", {
        "advisor_id": target["id"], "inquiry_id": inquiry["id"],
        "assigned_at": store.now_iso(), "released_at": None,
        "release_reason": None, "status": "ACTIVE",
    })
    svc.recompute_advisor_fields(target)
    svc.touch(target)
    inquiry["assigned_advisor_id"] = to_advisor_id
    svc.touch(inquiry)
    return E.ok(dump(inquiry))


@bp.post("/inquiries/<inquiry_id>/hold")
def hold_inquiry(inquiry_id):
    uid, role = guard(["Advisor", "PlatformAdmin"])
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"reason"}, PROTECTED["inquiry"])
    reason = V.req_str(body, "reason")
    _own_inquiry_advisor(inquiry, uid, role)
    if inquiry["status"] not in ("MATCHING", "TOURING"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry cannot be held in its state.")
    from_touring = inquiry["status"] == "TOURING"
    inquiry["hold_reason"] = reason
    inquiry["status"] = "ON_HOLD"
    if from_touring:
        for match in svc.matches_of_inquiry(inquiry["id"]):
            for tour in svc.scheduled_tours_of_match(match["id"]):
                tour["status"] = "CANCELLED"
                tour["cancel_reason_code"] = "INQUIRY_ON_HOLD"
                svc.touch(tour)
                if match["status"] == "TOUR_SCHEDULED":
                    match["status"] = "SHORTLISTED"
                    svc.touch(match)
    svc.touch(inquiry)
    return E.ok(dump(inquiry))


@bp.post("/inquiries/<inquiry_id>/resume")
def resume_inquiry(inquiry_id):
    uid, role = guard(["Advisor", "PlatformAdmin"])
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    V.get_body()
    _own_inquiry_advisor(inquiry, uid, role)
    if inquiry["status"] != "ON_HOLD":
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry is not on hold.")
    inquiry["hold_reason"] = None
    inquiry["status"] = "MATCHING"
    svc.touch(inquiry)
    return E.ok(dump(inquiry))


@bp.post("/inquiries/<inquiry_id>/close")
def close_inquiry(inquiry_id):
    uid, role = guard(["Advisor", "PlatformAdmin"])
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"reason_code"}, PROTECTED["inquiry"])
    reason_code = V.req_str(body, "reason_code")
    _own_inquiry_advisor(inquiry, uid, role)
    if inquiry["status"] not in ("ASSIGNED", "ASSESSED", "MATCHING", "TOURING", "ON_HOLD"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry cannot be closed in its state.")
    for p in store.DB["placements"].values():
        if (p["inquiry_id"] == inquiry["id"]
                and p["residency_status"] in ("PENDING_MOVE_IN", "MOVED_IN", "RESIDENT_CONFIRMED")):
            raise ApiError("ERR_PLACEMENT_EXISTS",
                           "Inquiry has an active placement and cannot be closed.")
    inquiry["close_reason_code"] = reason_code
    inquiry["status"] = "CLOSED_LOST"
    for match in svc.matches_of_inquiry(inquiry["id"]):
        if match["status"] in ("PROPOSED", "SHORTLISTED", "TOUR_SCHEDULED", "TOURED"):
            svc.withdraw_match(match, inquiry)
    svc.release_active_caseload(inquiry, "CLOSED_LOST")
    svc.touch(inquiry)
    return E.ok(dump(inquiry))


# ===========================================================================
# Needs assessments
# ===========================================================================
def _recompute_assessment_ceiling(assessment):
    g = svc.issued_guidance_for_assessment(assessment["id"])
    offset = g["estimated_monthly_benefit_cents"] if g else 0
    assessment["benefit_offset_cents"] = offset
    assessment["affordability_ceiling_cents"] = calc.affordability_ceiling(
        assessment["budget_monthly_cents"], offset)


@bp.post("/assessments")
def create_assessment():
    uid, role = guard(["Advisor"])
    body = V.get_body()
    V.reject_protected(body, {"inquiry_id", "adl_score", "cognitive_score", "mobility_score",
                              "budget_monthly_cents", "gross_monthly_income_cents",
                              "va_eligible", "marital_status"}, PROTECTED["assessment"])
    inquiry_id = V.req_str(body, "inquiry_id")
    adl = V.req_int(body, "adl_score", 0, 10)
    cog = V.req_int(body, "cognitive_score", 0, 10)
    mob = V.req_int(body, "mobility_score", 0, 10)
    budget = V.req_int(body, "budget_monthly_cents", 1)
    gross = V.req_int(body, "gross_monthly_income_cents", 0)
    va_eligible = V.req_bool(body, "va_eligible")
    marital = V.req_enum(body, "marital_status", C.MARITAL)
    V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    if svc.assessment_for_inquiry(inquiry_id) is not None:
        raise ApiError("ERR_VALIDATION", "An assessment already exists for this inquiry.")
    rec = calc.recommended_care_level(adl, cog, mob)
    row = svc.new_row("assessments", {
        "inquiry_id": inquiry_id, "author_advisor_id": uid,
        "adl_score": adl, "cognitive_score": cog, "mobility_score": mob,
        "budget_monthly_cents": budget, "gross_monthly_income_cents": gross,
        "va_eligible": va_eligible, "marital_status": marital,
        "recommended_care_level": rec, "benefit_offset_cents": 0,
        "affordability_ceiling_cents": 0, "status": "DRAFT",
        "revision_note": None, "revision_count": 0,
    })
    return E.created(dump(row))


@bp.get("/assessments/<assessment_id>")
def get_assessment(assessment_id):
    guard(C.ALL_ROLES)
    a = V.lookup("assessments", assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    return E.ok(dump(a))


@bp.get("/assessments")
def list_assessments():
    guard(C.ALL_ROLES)
    rows = list(store.DB["assessments"].values())
    for key in ("inquiry_id", "author_advisor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.patch("/assessments/<assessment_id>")
def patch_assessment(assessment_id):
    uid, role = guard(["Advisor"])
    a = V.lookup("assessments", assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"adl_score", "cognitive_score", "mobility_score",
                              "budget_monthly_cents", "gross_monthly_income_cents",
                              "va_eligible", "marital_status"}, PROTECTED["assessment"])
    adl = V.opt_int(body, "adl_score", 0, 10)
    cog = V.opt_int(body, "cognitive_score", 0, 10)
    mob = V.opt_int(body, "mobility_score", 0, 10)
    budget = V.opt_int(body, "budget_monthly_cents", 1)
    gross = V.opt_int(body, "gross_monthly_income_cents", 0)
    va_eligible = V.opt_bool(body, "va_eligible")
    marital = V.opt_enum(body, "marital_status", C.MARITAL)
    if uid != a["author_advisor_id"]:
        deny_ownership()
    if a["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE", "Assessment is not editable.")
    if adl is not V._MISSING:
        a["adl_score"] = adl
    if cog is not V._MISSING:
        a["cognitive_score"] = cog
    if mob is not V._MISSING:
        a["mobility_score"] = mob
    if budget is not V._MISSING:
        a["budget_monthly_cents"] = budget
    if gross is not V._MISSING:
        a["gross_monthly_income_cents"] = gross
    if va_eligible is not V._MISSING:
        a["va_eligible"] = va_eligible
    if marital is not V._MISSING:
        a["marital_status"] = marital
    a["recommended_care_level"] = calc.recommended_care_level(
        a["adl_score"], a["cognitive_score"], a["mobility_score"])
    if a["status"] == "REVISION_REQUESTED":
        a["status"] = "DRAFT"
        a["revision_note"] = None
    svc.touch(a)
    return E.ok(dump(a))


@bp.post("/assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    uid, role = guard(["Advisor"])
    a = V.lookup("assessments", assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    V.get_body()
    if uid != a["author_advisor_id"]:
        deny_ownership()
    if a["status"] != "DRAFT":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE", "Assessment is not in DRAFT.")
    a["status"] = "SUBMITTED"
    svc.touch(a)
    return E.ok(dump(a))


@bp.post("/assessments/<assessment_id>/review")
def review_assessment(assessment_id):
    uid, role = guard(["Advisor", "PlatformAdmin"])
    a = V.lookup("assessments", assessment_id, "ERR_ASSESSMENT_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"decision", "revision_note"}, PROTECTED["assessment"])
    decision = V.req_enum(body, "decision", C.REVIEW_DECISIONS)
    revision_note = V.opt_str(body, "revision_note")
    if role == "Advisor" and uid == a["author_advisor_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "A reviewer may not review their own assessment.")
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE", "Assessment is not SUBMITTED.")
    if decision == "APPROVE":
        a["status"] = "APPROVED"
        _recompute_assessment_ceiling(a)
        inquiry = store.DB["inquiries"].get(a["inquiry_id"])
        if inquiry is not None and inquiry["status"] == "ASSIGNED":
            inquiry["status"] = "ASSESSED"
            svc.touch(inquiry)
    else:
        a["status"] = "REVISION_REQUESTED"
        a["revision_note"] = revision_note
        a["revision_count"] = a["revision_count"] + 1
    svc.touch(a)
    return E.ok(dump(a))


# ===========================================================================
# Benefit guidances
# ===========================================================================
@bp.post("/benefit-guidances")
def create_guidance():
    uid, role = guard(["BenefitsCounselor"])
    body = V.get_body()
    V.reject_protected(body, {"inquiry_id", "benefit_type", "expected_assessment_version"},
                       PROTECTED["guidance"])
    inquiry_id = V.req_str(body, "inquiry_id")
    benefit_type = V.req_enum(body, "benefit_type", C.BENEFIT_TYPES)
    expected_version = V.req_int(body, "expected_assessment_version")
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    # VA certification (priority 7)
    advisor = store.DB["advisors"].get(uid)
    if advisor is None or not advisor.get("is_va_certified"):
        raise ApiError("ERR_ADVISOR_NOT_VA_CERTIFIED", "Acting advisor is not VA-certified.")
    # Segregation of duties (priority 9)
    if uid == inquiry["assigned_advisor_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The counselor may not be the inquiry's assigned advisor.")
    assessment = svc.assessment_for_inquiry(inquiry_id)
    if assessment is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND", "Inquiry has no needs assessment.")
    # OCC (priority 11)
    if expected_version != assessment["version"]:
        raise ApiError("ERR_STALE_VERSION", "Assessment version is stale.")
    # Assessment approved + inquiry status (priority 13)
    if assessment["status"] != "APPROVED":
        raise ApiError("ERR_ASSESSMENT_NOT_APPROVED", "Assessment is not approved.")
    if inquiry["status"] not in ("ASSESSED", "MATCHING", "TOURING", "ON_HOLD"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry state does not permit guidance.")
    # VA eligibility (priority 15)
    if not assessment["va_eligible"]:
        raise ApiError("ERR_GUIDANCE_NOT_ELIGIBLE", "Assessment is not VA-eligible.")
    ume, countable, benefit = calc.va_benefit_estimate(
        assessment["budget_monthly_cents"], assessment["gross_monthly_income_cents"],
        assessment["marital_status"], benefit_type)
    # Level 1: supersede prior issued guidance
    prior = svc.issued_guidance_for_assessment(assessment["id"])
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        svc.touch(prior)
    row = svc.new_row("guidances", {
        "inquiry_id": inquiry_id, "assessment_id": assessment["id"],
        "counselor_advisor_id": uid, "benefit_type": benefit_type,
        "unreimbursed_medical_cents": ume, "countable_income_cents": countable,
        "estimated_monthly_benefit_cents": benefit, "status": "ISSUED",
    })
    # Level 2: recompute assessment offset + ceiling; bump version
    _recompute_assessment_ceiling(assessment)
    svc.touch(assessment)
    # Level 3: recompute fit for PROPOSED / SHORTLISTED matches
    for match in svc.matches_of_inquiry(inquiry_id):
        if match["status"] in ("PROPOSED", "SHORTLISTED"):
            svc.recompute_match_fit(match)
    return E.created(dump(row))


@bp.get("/benefit-guidances/<guidance_id>")
def get_guidance(guidance_id):
    guard(C.ALL_ROLES)
    g = V.lookup("guidances", guidance_id, "ERR_GUIDANCE_NOT_FOUND")
    return E.ok(dump(g))


@bp.get("/benefit-guidances")
def list_guidances():
    guard(C.ALL_ROLES)
    rows = list(store.DB["guidances"].values())
    for key in ("inquiry_id", "assessment_id", "counselor_advisor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)
