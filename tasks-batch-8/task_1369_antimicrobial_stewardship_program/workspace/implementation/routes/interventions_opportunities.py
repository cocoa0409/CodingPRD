"""Routes: audit interventions (negotiation cycle) and conversion opportunities."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    err_adjudicator_conflict,
    err_conversion_not_eligible,
    err_deescalation_not_eligible,
    err_intervention_not_appealable,
    err_intervention_not_appealed,
    err_intervention_not_draft,
    err_intervention_not_pending,
    err_intervention_overdue,
    err_no_oral_form,
    err_no_supporting_culture,
    err_not_audit_owner,
    err_not_found,
    err_not_prescriber,
    err_opportunity_not_detected,
    err_order_not_auditable,
    err_order_not_iv,
    err_invalid_request,
)
from middleware import ALL_ROLES, auth_context, require_role
from response import success_object
from services import core
from services.core import CLASS_BREADTH_RANK, UNKNOWN_CLASS_RANK
from services.listing import list_response
from services.serializers import serialize
from util import (
    body_json,
    new_id,
    parse_iso,
    require_enum,
    require_fields,
    require_string,
    to_number,
)

bp = Blueprint("interventions_opportunities", __name__)

INTERVENTION_TYPES = {"DOSE_OPTIMIZATION", "DEESCALATION", "IV_TO_PO", "DURATION_REDUCTION", "STOP"}
RESPONSES = {"ACCEPTED", "REJECTED"}
VERDICTS = {"UPHOLD", "OVERTURN"}
OPPORTUNITY_KINDS = {"IV_TO_PO", "DEESCALATION"}


def get_intervention_or_404(iid):
    itv = db.audit_interventions.get(iid)
    if itv is None:
        raise err_not_found("AuditIntervention not found")
    return itv


def get_opportunity_or_404(oid):
    opp = db.conversion_opportunities.get(oid)
    if opp is None:
        raise err_not_found("ConversionOpportunity not found")
    return opp


def _require_active_practitioner(pid):
    prac = db.practitioners.get(pid)
    if prac is None:
        raise err_not_found("Practitioner not found")
    if not prac.get("is_active", True):
        from errors import err_practitioner_inactive

        raise err_practitioner_inactive()
    return prac


# --- Audit interventions ---------------------------------------------------------


@bp.route("/stewardship/audit-interventions", methods=["POST"])
def create_intervention():
    _, role = auth_context()
    require_role(role, {"IDPharmacist"})
    payload = body_json()
    require_fields(
        payload, ["antibiotic_order_id", "auditor_id", "intervention_type", "recommendation_text"]
    )
    text = require_string(payload, "recommendation_text", min_len=20)
    itype = require_enum(payload, "intervention_type", INTERVENTION_TYPES)
    order = db.antibiotic_orders.get(payload["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    auditor = _require_active_practitioner(payload["auditor_id"])
    hospital = db.hospitals.get(order["_hospital_id"])
    itv = {
        "id": new_id(),
        "antibiotic_order_id": order["id"],
        "auditor_id": auditor["id"],
        "intervention_type": itype,
        "recommendation_text": text,
        "recommendation_status": "DOCUMENTED",
        "responded_by_id": None,
        "appeal_adjudicator_id": None,
        "due_at": core.clock_plus(hospital, hours=24),
        "_hospital_id": order["_hospital_id"],
    }
    core.stamp_new(itv)
    db.audit_interventions[itv["id"]] = itv
    return success_object(serialize(itv), status=201)


@bp.route("/stewardship/audit-interventions/<iid>", methods=["GET"])
def get_intervention(iid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_intervention_or_404(iid)))


@bp.route("/stewardship/audit-interventions", methods=["GET"])
def list_interventions():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.audit_interventions.values(),
        [
            "antibiotic_order_id",
            "auditor_id",
            "responded_by_id",
            "appeal_adjudicator_id",
            "recommendation_status",
        ],
    )


@bp.route("/stewardship/audit-interventions/<iid>/issue", methods=["POST"])
def issue_intervention(iid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist"})
    itv = get_intervention_or_404(iid)
    if itv["recommendation_status"] != "DOCUMENTED":
        raise err_intervention_not_draft()
    order = db.antibiotic_orders.get(itv["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    if order["therapy_status"] not in ("ACTIVE", "REVIEW_REQUIRED"):
        raise err_order_not_auditable()
    hospital = db.hospitals.get(order["_hospital_id"])
    itv["recommendation_status"] = "RECOMMENDED"
    itv["due_at"] = core.clock_plus(hospital, hours=24)
    core.touch(itv)
    if order["therapy_status"] == "ACTIVE":
        order["therapy_status"] = "REVIEW_REQUIRED"
        core.touch(order)
    return success_object(serialize(itv))


@bp.route("/stewardship/audit-interventions/<iid>/respond", methods=["POST"])
def respond_intervention(iid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician"})
    itv = get_intervention_or_404(iid)
    payload = body_json()
    require_fields(payload, ["response", "responder_id"])
    response = payload["response"]
    if response not in RESPONSES:
        raise err_invalid_request("response must be ACCEPTED or REJECTED")
    _require_active_practitioner(payload["responder_id"])
    if itv["recommendation_status"] != "RECOMMENDED":
        raise err_intervention_not_pending()
    order = db.antibiotic_orders.get(itv["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    if payload["responder_id"] != order["prescriber_id"]:
        raise err_not_prescriber()
    hospital = db.hospitals.get(order["_hospital_id"])
    if itv.get("due_at") and core.hospital_clock(hospital) > parse_iso(itv["due_at"]):
        raise err_intervention_overdue()
    itv["responded_by_id"] = payload["responder_id"]
    if response == "REJECTED":
        itv["recommendation_status"] = "REJECTED"
        core.touch(itv)
        return success_object(serialize(itv))
    # ACCEPTED — order transition per intervention_type (PRD 3.3).
    itv["recommendation_status"] = "ACCEPTED"
    core.touch(itv)
    itype = itv["intervention_type"]
    if itype == "STOP":
        order["therapy_status"] = "DISCONTINUED"
        order["stopped_at"] = core.clock_iso(hospital)
        core.recompute_order_dot(order)
        core.touch(order)
    elif itype == "IV_TO_PO":
        order["therapy_status"] = "CONVERTED"
        order["route"] = "PO"
        core.touch(order)
    elif itype == "DEESCALATION":
        order["therapy_status"] = "DEESCALATED"
        # Swap to the suggested drug carried through the linked conversion
        # opportunity (latest DETECTED/ACCEPTED de-escalation for this order).
        linked = [
            o
            for o in db.conversion_opportunities.values()
            if o["antibiotic_order_id"] == order["id"] and o["opportunity_kind"] == "DEESCALATION"
        ]
        linked.sort(key=lambda o: (o["created_at"], o["id"]))
        if linked and linked[-1].get("suggested_antimicrobial_id"):
            order["antimicrobial_id"] = linked[-1]["suggested_antimicrobial_id"]
        core.touch(order)
    else:
        # DOSE_OPTIMIZATION / DURATION_REDUCTION: return to ACTIVE.
        if order["therapy_status"] == "REVIEW_REQUIRED":
            order["therapy_status"] = "ACTIVE"
            core.touch(order)
    return success_object(serialize(itv))


@bp.route("/stewardship/audit-interventions/<iid>/appeal", methods=["POST"])
def appeal_intervention(iid):
    _, role = auth_context()
    require_role(role, {"IDPharmacist"})
    itv = get_intervention_or_404(iid)
    payload = body_json()
    require_fields(payload, ["appealer_id"])
    _require_active_practitioner(payload["appealer_id"])
    if itv["recommendation_status"] != "REJECTED":
        raise err_intervention_not_appealable()
    if payload["appealer_id"] != itv["auditor_id"]:
        raise err_not_audit_owner()
    itv["recommendation_status"] = "APPEALED"
    core.touch(itv)
    return success_object(serialize(itv))


@bp.route("/stewardship/audit-interventions/<iid>/adjudicate", methods=["POST"])
def adjudicate_intervention(iid):
    _, role = auth_context()
    require_role(role, {"StewardshipDirector"})
    itv = get_intervention_or_404(iid)
    payload = body_json()
    require_fields(payload, ["verdict", "adjudicator_id"])
    verdict = payload["verdict"]
    if verdict not in VERDICTS:
        raise err_invalid_request("verdict must be UPHOLD or OVERTURN")
    _require_active_practitioner(payload["adjudicator_id"])
    if itv["recommendation_status"] != "APPEALED":
        raise err_intervention_not_appealed()
    if payload["adjudicator_id"] in (itv["auditor_id"], itv.get("responded_by_id")):
        raise err_adjudicator_conflict()
    itv["appeal_adjudicator_id"] = payload["adjudicator_id"]
    order = db.antibiotic_orders.get(itv["antibiotic_order_id"])
    hospital = db.hospitals.get(itv["_hospital_id"])
    if verdict == "UPHOLD":
        itv["recommendation_status"] = "RECOMMENDED"
        itv["due_at"] = core.clock_plus(hospital, hours=24)
        core.touch(itv)
    else:
        itv["recommendation_status"] = "REJECTED_FINAL"
        core.touch(itv)
        if order is not None:
            prescriber = db.practitioners.get(order["prescriber_id"])
            if prescriber is not None:
                prescriber["unresolved_noncompliance_count"] = (
                    prescriber.get("unresolved_noncompliance_count", 0) + 1
                )
                core.recompute_standing(prescriber)
                core.touch(prescriber)
    return success_object(serialize(itv))


# --- Conversion opportunities --------------------------------------------------------


def _newest_final_culture(patient_id):
    finals = [
        c
        for c in db.culture_reports.values()
        if c["patient_case_id"] == patient_id and c["status"] == "FINAL" and c.get("resulted_at")
    ]
    if not finals:
        return None

    def key(c):
        return (parse_iso(c["resulted_at"]), parse_iso(c["collected_at"]), c["created_at"])

    finals.sort(key=key)
    return finals[-1]


def _culture_has_s_for(culture_id, antimicrobial_id):
    for row in db.susceptibility_results.values():
        if (
            row["culture_report_id"] == culture_id
            and row["antimicrobial_id"] == antimicrobial_id
            and row["interpretation"] == "S"
        ):
            return True
    return False


def _any_final_culture_supports(patient_id, antimicrobial_id):
    for c in db.culture_reports.values():
        if c["patient_case_id"] != patient_id or c["status"] != "FINAL":
            continue
        if _culture_has_s_for(c["id"], antimicrobial_id):
            return True
    return False


@bp.route("/stewardship/conversion-opportunities/detect", methods=["POST"])
def detect_opportunity():
    _, role = auth_context()
    require_role(role, {"IDPharmacist", "StewardshipDirector"})
    payload = body_json()
    require_fields(payload, ["antibiotic_order_id", "opportunity_kind"])
    kind = require_enum(payload, "opportunity_kind", OPPORTUNITY_KINDS)
    order = db.antibiotic_orders.get(payload["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    suggested = None
    if payload.get("suggested_antimicrobial_id") is not None:
        suggested = db.antimicrobials.get(payload["suggested_antimicrobial_id"])
        if suggested is None:
            raise err_not_found("Antimicrobial not found")
    hospital = db.hospitals.get(order["_hospital_id"])
    patient = db.patient_cases.get(order["patient_case_id"])
    drug = db.antimicrobials.get(order["antimicrobial_id"])

    if kind == "IV_TO_PO":
        min_hours = hospital["iv_to_po_min_iv_hours"]
        iv_hours = order["cumulative_iv_hours"]
        gates_ok = (
            order["route"] == "IV"
            and drug is not None
            and drug["has_po_form"]
            and iv_hours >= min_hours
            and patient is not None
            and patient["has_enteral_access"]
            and (not patient["is_immunocompromised"] or iv_hours >= 2 * min_hours)
        )
        if not gates_ok:
            raise err_conversion_not_eligible()
        hemodynamic_term = Decimal(40)
        renal_term = Decimal(min(patient["renal_function_crcl"], 90))
        over_blocks = (iv_hours - min_hours) // 24
        duration_term = Decimal(max(0, 30 - 5 * over_blocks))
        score = core.round2(hemodynamic_term + Decimal("0.4") * renal_term + duration_term)
        if score < core.CONVERSION_MIN_SCORE:
            raise err_conversion_not_eligible()
        score_out = to_number(score)
    else:
        if suggested is None:
            raise err_invalid_request("suggested_antimicrobial_id is required for DEESCALATION")
        culture = _newest_final_culture(order["patient_case_id"])
        dot_now = order["dot_calendar"]  # snapshot as of clock, before any side effects
        gates_ok = (
            culture is not None
            and _culture_has_s_for(culture["id"], suggested["id"])
            and drug is not None
            and CLASS_BREADTH_RANK.get(
                suggested["drug_class"], UNKNOWN_CLASS_RANK
            )
            < CLASS_BREADTH_RANK.get(drug["drug_class"], UNKNOWN_CLASS_RANK)
            and order["indication"] in ("EMPIRIC", "CULTURE_DIRECTED")
        )
        if not gates_ok:
            raise err_deescalation_not_eligible()
        rank_current = CLASS_BREADTH_RANK.get(drug["drug_class"], UNKNOWN_CLASS_RANK)
        rank_suggested = CLASS_BREADTH_RANK.get(suggested["drug_class"], UNKNOWN_CLASS_RANK)
        score = 50
        if culture["is_first_isolate"]:
            score += 25
        if dot_now >= hospital["dot_review_threshold"]:
            score += 15
        if patient is not None and patient["is_immunocompromised"]:
            score -= 20
        score += 10 * (rank_current - rank_suggested)
        if score < core.DEESCALATION_MIN_SCORE:
            raise err_deescalation_not_eligible()
        score_out = int(score)

    opp = {
        "id": new_id(),
        "antibiotic_order_id": order["id"],
        "opportunity_kind": kind,
        "eligibility_score": score_out,
        "detected_at": core.clock_iso(hospital),
        "suggested_antimicrobial_id": suggested["id"] if suggested is not None else None,
        "status": "DETECTED",
        "_hospital_id": order["_hospital_id"],
    }
    core.stamp_new(opp)
    db.conversion_opportunities[opp["id"]] = opp
    return success_object(serialize(opp), status=201)


@bp.route("/stewardship/conversion-opportunities/<oid>", methods=["GET"])
def get_opportunity(oid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_opportunity_or_404(oid)))


@bp.route("/stewardship/conversion-opportunities", methods=["GET"])
def list_opportunities():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return list_response(
        db.conversion_opportunities.values(),
        ["antibiotic_order_id", "opportunity_kind", "suggested_antimicrobial_id", "status"],
    )


@bp.route("/stewardship/conversion-opportunities/<oid>/accept", methods=["POST"])
def accept_opportunity(oid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician"})
    opp = get_opportunity_or_404(oid)
    payload = body_json()
    require_fields(payload, ["accepter_id"])
    _require_active_practitioner(payload["accepter_id"])
    if opp["status"] != "DETECTED":
        raise err_opportunity_not_detected()
    order = db.antibiotic_orders.get(opp["antibiotic_order_id"])
    if order is None:
        raise err_not_found("AntibioticOrder not found")
    drug = db.antimicrobials.get(order["antimicrobial_id"])
    if opp["opportunity_kind"] == "IV_TO_PO":
        if order["route"] != "IV":
            raise err_order_not_iv()
        if drug is None or not drug["has_po_form"]:
            raise err_no_oral_form()
        order["route"] = "PO"
        order["therapy_status"] = "CONVERTED"
    else:
        if not _any_final_culture_supports(order["patient_case_id"], opp["suggested_antimicrobial_id"]):
            raise err_no_supporting_culture()
        order["antimicrobial_id"] = opp["suggested_antimicrobial_id"]
        order["therapy_status"] = "DEESCALATED"
    opp["status"] = "ACCEPTED"
    core.touch(opp)
    core.touch(order)
    return success_object(serialize(opp))


@bp.route("/stewardship/conversion-opportunities/<oid>/decline", methods=["POST"])
def decline_opportunity(oid):
    _, role = auth_context()
    require_role(role, {"AttendingPhysician"})
    opp = get_opportunity_or_404(oid)
    payload = body_json()
    require_fields(payload, ["decliner_id"])
    _require_active_practitioner(payload["decliner_id"])
    if opp["status"] != "DETECTED":
        raise err_opportunity_not_detected()
    opp["status"] = "DECLINED"
    core.touch(opp)
    return success_object(serialize(opp))
