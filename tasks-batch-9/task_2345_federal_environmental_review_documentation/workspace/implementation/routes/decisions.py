"""Decisions, mitigation obligations, objections and record certification."""

from flask import Blueprint, g

import db
import response
import validation as v
from errors import ApiError, fail
from middleware import endpoint
from routes.helpers import body_ref, list_response, of_action, office_of, path_row
from services import calc, cascade, record, rollups

bp = Blueprint("decisions", __name__)

DECISION_TYPES = ("CE_DETERMINATION", "FONSI", "MITIGATED_FONSI", "RECORD_OF_DECISION")

CLASSIFICATION_FOR_DECISION = {
    "CE_DETERMINATION": ("CATEGORICAL_EXCLUSION",),
    "FONSI": ("ENVIRONMENTAL_ASSESSMENT",),
    "MITIGATED_FONSI": ("ENVIRONMENTAL_ASSESSMENT",),
    "RECORD_OF_DECISION": ("ENVIRONMENTAL_IMPACT_STATEMENT",),
}

DECISION_SPEC = {
    "action_id": {"required": True, "check": v.c_str(1)},
    "selected_alternative_id": {"required": True, "check": v.c_str(1)},
    "decision_type": {"required": True, "check": v.c_enum(DECISION_TYPES)},
}

MITIGATION_SPEC = {
    "source_analysis_id": {"required": True, "check": v.c_str(1)},
    "measure_text": {"required": True, "check": v.c_str(1)},
    "cost_estimate_cents": {"required": True, "check": v.c_int(lo=0)},
    "monitoring_years": {"check": v.c_int(lo=0, hi=20), "default": 0},
    "annual_monitoring_cost_cents": {"check": v.c_int(lo=0), "default": 0},
    "reduction_points": {"check": v.c_num(lo=0, hi=20), "default": 0.0},
    "expected_decision_version": {"required": True, "check": v.c_int(lo=0)},
}

OBJECTION_SPEC = {
    "objector_name": {"required": True, "check": v.c_str(1)},
    "objector_type": {
        "required": True,
        "check": v.c_enum(("COMMENTER", "AGENCY", "TRIBE", "OTHER")),
    },
    "basis_issue_area": {"required": True, "check": v.c_enum(v.RESOURCE_AREAS)},
    "standing_basis": {
        "required": True,
        "check": v.c_enum(("SUBSTANTIVE_COMMENT", "AGENCY_CONSULTATION", "NONE")),
    },
}

DECISION_READ_ROLES = [
    "NepaCoordinator",
    "ReviewingOfficial",
    "DecidingOfficial",
    "ObjectionReviewingOfficer",
]
MITIGATION_READ_ROLES = ["NepaCoordinator", "ReviewingOfficial", "DecidingOfficial"]
OBJECTION_READ_ROLES = [
    "NepaCoordinator",
    "ReviewingOfficial",
    "ObjectionReviewingOfficer",
    "PublicCommenter",
]


def commitments_of(decision_id):
    return [c for c in db.rows("mitigations") if c["decision_id"] == decision_id]


# --------------------------------------------------------------- decisions


@endpoint(bp, "/decisions", ["POST"], ["NepaCoordinator"])
def create_decision():
    body = v.parse_body(DECISION_SPEC)
    action = body_ref("actions", body["action_id"], "action_id")
    alternative = body_ref(
        "alternatives", body["selected_alternative_id"], "selected_alternative_id"
    )

    if alternative["screening_status"] == "STALE":
        fail("ERR_ALTERNATIVE_STALE", "the selected alternative is STALE")
    if action["classification"] not in CLASSIFICATION_FOR_DECISION[body["decision_type"]]:
        fail("ERR_REFERENCE_MISMATCH", "decision_type does not match the action's classification")
    if alternative["action_id"] != action["id"]:
        fail("ERR_REFERENCE_MISMATCH", "the selected alternative belongs to a different action")
    if alternative["screening_status"] != "SCREENED_IN":
        fail("ERR_REFERENCE_MISMATCH", "the selected alternative is not SCREENED_IN")

    row = db.new_row(
        "decisions",
        {
            "action_id": action["id"],
            "selected_alternative_id": alternative["id"],
            "decision_type": body["decision_type"],
            "prepared_by_user_id": g.user_id,
            "signed_by_user_id": None,
            "signed_at": None,
            "committed_obligation_cents": 0,
            "base_obligation_cents": 0,
            "credit_points": 0.0,
            "contingency_fee_cents": 0,
            "binding_obligation_cents": 0,
            "mitigated_max_score": 0.0,
            "objection_window_opens_at": None,
            "objection_window_closes_at": None,
            "objection_count": 0,
            "status": "DRAFT",
        },
    )
    return response.created(db.public(row))


@endpoint(bp, "/decisions/<decision_id>", ["GET"], DECISION_READ_ROLES + ["PublicCommenter"])
def get_decision(decision_id):
    decision = path_row("decisions", decision_id, "decision document")
    return response.ok(db.public(decision))


@endpoint(bp, "/decisions", ["GET"], DECISION_READ_ROLES)
def list_decisions():
    return list_response(
        db.rows("decisions"), "action_id", "selected_alternative_id", "status", "decision_type"
    )


# ------------------------------------------------------ mitigation commitments


@endpoint(bp, "/decisions/<decision_id>/mitigations", ["POST"], ["NepaCoordinator"])
def create_mitigation(decision_id):
    body = v.parse_body(MITIGATION_SPEC)
    decision = path_row("decisions", decision_id, "decision document")
    analysis = body_ref("analyses", body["source_analysis_id"], "source_analysis_id")
    action = db.find("actions", decision["action_id"])
    office = office_of(action)

    if decision["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "commitments may only be attached to a DRAFT decision")
    if body["expected_decision_version"] != decision["version"]:
        fail("ERR_STALE_DECISION_VERSION", "expected_decision_version does not match the decision")
    if analysis["action_id"] != action["id"]:
        fail("ERR_REFERENCE_MISMATCH", "the source analysis belongs to a different action")
    if analysis["status"] != "FINAL":
        fail("ERR_REFERENCE_MISMATCH", "the source analysis is not FINAL")

    fields = {
        "decision_id": decision["id"],
        "source_analysis_id": analysis["id"],
        "measure_text": body["measure_text"],
        "cost_estimate_cents": body["cost_estimate_cents"],
        "monitoring_years": body["monitoring_years"],
        "annual_monitoring_cost_cents": body["annual_monitoring_cost_cents"],
        "reduction_points": body["reduction_points"],
    }
    fields["lifecycle_obligation_cents"] = calc.lifecycle_obligation_cents(fields, office)
    fields["monitoring_status"] = "NOT_REQUIRED"
    fields["status"] = "PROPOSED"
    row = db.new_row("mitigations", fields)
    db.touch(decision)
    return response.created(db.public(row))


@endpoint(bp, "/mitigations/<mitigation_id>", ["GET"], MITIGATION_READ_ROLES)
def get_mitigation(mitigation_id):
    commitment = path_row("mitigations", mitigation_id, "mitigation commitment")
    return response.ok(db.public(commitment))


@endpoint(bp, "/mitigations", ["GET"], MITIGATION_READ_ROLES)
def list_mitigations():
    return list_response(
        db.rows("mitigations"), "decision_id", "source_analysis_id", "monitoring_status", "status"
    )


# ----------------------------------------------------------------- signature


@endpoint(bp, "/decisions/<decision_id>/sign", ["POST"], ["DecidingOfficial"])
def sign_decision(decision_id):
    v.no_body()
    decision = path_row("decisions", decision_id, "decision document")
    action = db.find("actions", decision["action_id"])
    office = office_of(action)

    if g.user_id == decision["prepared_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the signer may not be the principal who prepared the draft",
            403,
        )
    if decision["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT decision may be signed")
    if action["review_stage"] != "COMMENT_CLOSED":
        fail("ERR_INVALID_STATE", "the action's review_stage must be COMMENT_CLOSED")

    if decision["decision_type"] != "CE_DETERMINATION":
        finals = [
            d for d in of_action("documents", action["id"]) if d["publication_status"] == "FINAL"
        ]
        if not finals:
            fail("ERR_FINAL_DOCUMENT_REQUIRED", "the action has no FINAL NEPA document")

    commitments = commitments_of(decision["id"])
    becoming_binding = [c for c in commitments if c["status"] == "PROPOSED"]
    binding = becoming_binding + [c for c in commitments if c["status"] == "BINDING"]

    if decision["decision_type"] == "MITIGATED_FONSI" and not binding:
        fail(
            "ERR_MITIGATED_FONSI_WITHOUT_COMMITMENT",
            "a MITIGATED_FONSI requires at least one binding mitigation commitment",
        )

    fiscals = calc.decision_fiscals(binding, office, action["max_unmitigated_score"])
    projected = int(office["binding_obligation_cents"]) + fiscals["binding_obligation_cents"]
    if projected > int(office["max_binding_obligation_cents"]):
        fail(
            "ERR_OBLIGATION_CAP_EXCEEDED",
            "the signature would push the office ledger past its ceiling",
        )

    for commitment in becoming_binding:
        commitment["status"] = "BINDING"
        commitment["monitoring_status"] = (
            "SCHEDULED" if commitment["monitoring_years"] > 0 else "NOT_REQUIRED"
        )
        db.touch(commitment)

    now = db.logical_now()
    decision.update(fiscals)
    decision["signed_by_user_id"] = g.user_id
    decision["signed_at"] = db.iso(now)
    decision["objection_window_opens_at"] = db.iso(now)
    decision["objection_window_closes_at"] = db.iso(
        db.add_days(now, office["objection_window_days"])
    )
    decision["status"] = "SIGNED"
    db.touch(decision)

    office["binding_obligation_cents"] = projected
    db.touch(office)

    action["review_stage"] = "DECIDED"
    db.touch(action)
    record.add_entry(
        action,
        "DECISION_SIGNED",
        "DecisionDocument",
        decision["id"],
        "Decision signed as %s" % decision["decision_type"],
    )
    return response.ok(db.public(decision))


@endpoint(bp, "/decisions/<decision_id>/certify-record", ["POST"], ["ReviewingOfficial"])
def certify_record(decision_id):
    v.no_body()
    decision = path_row("decisions", decision_id, "decision document")
    action = db.find("actions", decision["action_id"])

    if action["record_certified_at"] is not None:
        fail("ERR_RECORD_ALREADY_CERTIFIED", "the administrative record is already certified")
    if action["review_stage"] != "DECIDED":
        fail("ERR_INVALID_STATE", "the action's review_stage must be DECIDED")
    if decision["status"] != "SIGNED":
        fail("ERR_INVALID_STATE", "only a SIGNED decision's record may be certified")

    now = db.logical_now()
    if now < db.parse_dt(decision["objection_window_closes_at"]):
        fail("ERR_TEMPORAL_CONFLICT", "the objection window has not closed")
    for objection in db.rows("objections"):
        if objection["decision_id"] == decision["id"] and objection["status"] == "FILED":
            fail("ERR_OBJECTIONS_PENDING", "an objection is still pending resolution")

    action["record_certified_at"] = db.iso(now)
    action["review_stage"] = "RECORD_CERTIFIED"
    db.touch(action)
    record.add_entry(
        action,
        "RECORD_CERTIFIED",
        "ProposedAction",
        action["id"],
        "Administrative record certified",
    )
    return response.ok(db.public(action))


# ---------------------------------------------------------------- objections


@endpoint(bp, "/decisions/<decision_id>/objections", ["POST"], ["PublicCommenter", "AgencyLiaison"])
def file_objection(decision_id):
    body = v.parse_body(OBJECTION_SPEC)
    decision = path_row("decisions", decision_id, "decision document")
    action = db.find("actions", decision["action_id"])

    if decision["status"] != "SIGNED":
        fail("ERR_INVALID_STATE", "objections may only be filed against a SIGNED decision")
    if body["standing_basis"] == "NONE":
        fail(
            "ERR_OBJECTION_STANDING_MISSING",
            "the objector did not participate during the comment period",
        )

    now = db.logical_now()
    opens = db.parse_dt(decision["objection_window_opens_at"])
    closes = db.parse_dt(decision["objection_window_closes_at"])
    if now < opens or not now < closes:
        fail("ERR_OBJECTION_WINDOW_CLOSED", "the objection window is not open")

    row = db.new_row(
        "objections",
        {
            "decision_id": decision["id"],
            "objector_name": body["objector_name"],
            "objector_type": body["objector_type"],
            "basis_issue_area": body["basis_issue_area"],
            "standing_basis": body["standing_basis"],
            "resolution_note": None,
            "status": "FILED",
        },
    )
    rollups.refresh_decision_objection_count(decision)
    record.add_entry(
        action,
        "OBJECTION_FILED",
        "Objection",
        row["id"],
        "Administrative objection filed by %s" % body["objector_name"],
    )
    return response.created(db.public(row))


@endpoint(bp, "/decisions/<decision_id>/objections", ["GET"], DECISION_READ_ROLES + [
    "PublicCommenter"
])
def list_decision_objections(decision_id):
    path_row("decisions", decision_id, "decision document")
    items = [o for o in db.rows("objections") if o["decision_id"] == decision_id]
    return list_response(items, "status")


@endpoint(bp, "/objections/<objection_id>", ["GET"], OBJECTION_READ_ROLES)
def get_objection(objection_id):
    objection = path_row("objections", objection_id, "objection")
    return response.ok(db.public(objection))


@endpoint(bp, "/objections/<objection_id>/resolve", ["POST"], ["ObjectionReviewingOfficer"])
def resolve_objection(objection_id):
    body = v.parse_body(
        {
            "disposition": {"required": True, "check": v.c_enum(("DENIED", "REMANDED"))},
            "resolution_note": {"required": True, "check": v.c_str(1)},
        }
    )
    objection = path_row("objections", objection_id, "objection")
    decision = db.find("decisions", objection["decision_id"])
    action = db.find("actions", decision["action_id"])
    office = office_of(action)

    if g.user_id == decision["signed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the resolver may not be the official who signed the decision",
            403,
        )
    if objection["status"] != "FILED":
        fail("ERR_INVALID_STATE", "only a FILED objection may be resolved")

    if body["disposition"] == "REMANDED":
        if decision["status"] != "SIGNED":
            fail("ERR_INVALID_STATE", "only a SIGNED decision may be remanded")
        if action["record_certified_at"] is not None:
            fail(
                "ERR_RECORD_ALREADY_CERTIFIED",
                "the administrative record has already been certified",
            )

    objection["resolution_note"] = body["resolution_note"]
    objection["status"] = body["disposition"]
    db.touch(objection)
    record.add_entry(
        action,
        "OBJECTION_RESOLVED",
        "Objection",
        objection["id"],
        "Objection resolved as %s" % body["disposition"],
    )

    if body["disposition"] == "REMANDED":
        cascade.vacate_decision(decision, action, office)
    return response.ok(db.public(objection))
