"""Document draft endpoints (drafting, review, signoff, lock)."""

import re

import clock
import db
import errors
import helpers
import response
import serializers
from flask import Blueprint
from middleware import auth_required, get_actor, acting_lawyer
from services import audit


bp = Blueprint("document_drafts", __name__)


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


def _next_version_number(case_id, template_id):
    return 1 + sum(
        1 for d in db.document_drafts.values()
        if d["case_id"] == case_id and d["template_id"] == template_id
    )


def _render_body(template, case, overrides):
    """Substitute {{variable}} placeholders.

    Auto-fillable variables sourced from Case and from Party rows on the case.
    Variables referenced in `overrides` win when the override key matches the
    bare variable name.
    """
    body_text = template["body_template"]

    # Build context. Standard auto-fills:
    parties = [p for p in db.parties.values() if p["case_id"] == case["id"]]
    plaintiff_names = ", ".join(
        p["full_name"] for p in parties if p["party_role"] == "PLAINTIFF"
    )
    defendant_names = ", ".join(
        p["full_name"] for p in parties if p["party_role"] == "DEFENDANT"
    )
    context = {
        "case_number": case["case_number"],
        "case_title": case["title"],
        "case_type": case["case_type"],
        "claim_amount_cents": case["claim_amount_cents"],
        "plaintiff_name": plaintiff_names,
        "defendant_name": defendant_names,
    }
    if overrides:
        for k, v in overrides.items():
            context[k] = v

    def _sub(m):
        key = m.group(1).strip()
        if key in context:
            return str(context[key])
        return m.group(0)

    return re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", _sub, body_text)


@bp.route("/document-drafts", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def create_draft():
    body = helpers.get_json_body()
    case_id = helpers.require_str(body, "case_id")
    template_id = helpers.require_str(body, "template_id")
    drafter_lawyer_id = helpers.require_str(body, "drafter_lawyer_id")
    overrides = body.get("variable_overrides") or {}
    if not isinstance(overrides, dict):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "variable_overrides must be an object.")

    case = db.cases.get(case_id)
    if case is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Case {case_id} not found.")
    template = db.document_templates.get(template_id)
    if template is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Template {template_id} not found.")
    drafter = db.lawyers.get(drafter_lawyer_id)
    if drafter is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Lawyer {drafter_lawyer_id} not found.")

    _ensure_not_archived(case)

    if case["posture"] == "FROZEN":
        errors.raise_error(errors.ERR_CASE_POSTURE_FROZEN, "Case is FROZEN; cannot create new drafts.")

    if template["case_type"] != case["case_type"]:
        errors.raise_error(
            errors.ERR_TEMPLATE_CASE_TYPE_MISMATCH,
            "Template case_type does not match Case.case_type.",
        )

    # Identity-verification check: any Party referenced inside variable_overrides
    # by id_document_number/full_name through an explicit "party:<id>" override
    # must be verified.
    for k, v in overrides.items():
        if isinstance(v, str) and v.startswith("party:"):
            party_id = v[len("party:"):]
            party = db.parties.get(party_id)
            if party is None:
                errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Party {party_id} not found.")
            if not party["identity_verified"]:
                errors.raise_error(
                    errors.ERR_PARTY_NOT_VERIFIED,
                    "Party referenced in variable_overrides must be identity-verified.",
                )

    rendered = _render_body(template, case, overrides)
    did = db.new_id()
    common = helpers.common_create()
    draft = {
        "id": did,
        "case_id": case_id,
        "template_id": template_id,
        "template_version_pinned": template["version"],
        "version_number": _next_version_number(case_id, template_id),
        "rendered_body": rendered,
        "variable_overrides": dict(overrides),
        "drafter_lawyer_id": drafter_lawyer_id,
        "senior_reviewer_lawyer_id": None,
        "partner_signoff_lawyer_id": None,
        "signed_off_at": None,
        "status": "DRAFTING",
        **common,
    }
    db.document_drafts[did] = draft
    audit.append(
        subject_type="DOCUMENT_DRAFT",
        subject_id=did,
        action="DRAFT_CREATED",
        payload_snapshot={"version_number": draft["version_number"]},
    )
    return response.created(serializers.draft_dict(draft))


def _load_draft(did):
    draft = db.document_drafts.get(did)
    if draft is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DocumentDraft {did} not found.")
    case = db.cases.get(draft["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    if draft["status"] == "LOCKED":
        errors.raise_error(errors.ERR_DRAFT_LOCKED, "Draft is LOCKED.")
    return draft


@bp.route("/document-drafts/<did>/submit-for-review", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def submit_for_review(did):
    draft = _load_draft(did)
    body = helpers.get_json_body()
    helpers.check_occ(draft, body.get("version"))

    if draft["status"] != "DRAFTING":
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft must be in DRAFTING.")

    case = db.cases.get(draft["case_id"])
    if case is None or case["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Parent case must be ACTIVE.")

    if not draft.get("rendered_body"):
        errors.raise_error(errors.ERR_INVALID_STATE, "rendered_body must be non-empty.")

    draft["status"] = "IN_REVIEW"
    helpers.bump(draft)
    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=did, action="REVIEW_SUBMITTED",
    )
    return response.ok(serializers.draft_dict(draft))


def _check_reviewer(draft, *, require_partner=False):
    """Apply segregation-of-duties (priority 9) and reviewer-rank (priority 18)
    in their fixed priority order.
    """
    user_id, user_role = get_actor()
    # Priority 9: drafter cannot act on their own draft for any reviewer-side op.
    if user_id == draft["drafter_lawyer_id"]:
        errors.raise_error(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Drafter cannot perform reviewer/signoff actions on their own draft.",
        )

    lw = acting_lawyer()
    if lw is None:
        errors.raise_error(
            errors.ERR_REVIEWER_RANK_INSUFFICIENT,
            "Acting principal must be a Lawyer.",
        )

    if require_partner:
        if lw["role"] != "PARTNER":
            errors.raise_error(
                errors.ERR_REVIEWER_RANK_INSUFFICIENT,
                "Partner-signoff requires Lawyer.role=PARTNER.",
            )
    else:
        if lw["role"] not in {"SENIOR", "PARTNER"}:
            errors.raise_error(
                errors.ERR_REVIEWER_RANK_INSUFFICIENT,
                "Senior-pass / request-revisions requires Lawyer.role in {SENIOR, PARTNER}.",
            )
    return lw


@bp.route("/document-drafts/<did>/senior-pass", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def senior_pass(did):
    draft = _load_draft(did)
    body = helpers.get_json_body()
    helpers.check_occ(draft, body.get("version"))

    if draft["status"] != "IN_REVIEW":
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft must be IN_REVIEW for senior-pass.")
    lw = _check_reviewer(draft)

    draft["senior_reviewer_lawyer_id"] = lw["id"]
    draft["status"] = "DRAFTING"
    helpers.bump(draft)
    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=did, action="SENIOR_PASSED",
    )
    return response.ok(serializers.draft_dict(draft))


@bp.route("/document-drafts/<did>/request-revisions", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def request_revisions(did):
    draft = _load_draft(did)
    body = helpers.get_json_body()
    helpers.check_occ(draft, body.get("version"))

    if draft["status"] != "IN_REVIEW":
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft must be IN_REVIEW to request revisions.")
    _check_reviewer(draft)

    draft["status"] = "REVISING"
    draft["version_number"] = draft["version_number"] + 1
    helpers.bump(draft)
    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=did, action="REVIEW_REJECTED",
    )
    return response.ok(serializers.draft_dict(draft))


@bp.route("/document-drafts/<did>/resume-drafting", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def resume_drafting(did):
    draft = _load_draft(did)
    body = helpers.get_json_body()
    helpers.check_occ(draft, body.get("version"))

    if draft["status"] != "REVISING":
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft must be REVISING to resume drafting.")
    user_id, _ = get_actor()
    if user_id != draft["drafter_lawyer_id"]:
        errors.raise_error(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Only the original drafter may resume drafting.",
        )

    draft["status"] = "DRAFTING"
    helpers.bump(draft)
    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=did, action="REVISION_RESUMED",
    )
    return response.ok(serializers.draft_dict(draft))


@bp.route("/document-drafts/<did>/partner-signoff", methods=["POST"])
@auth_required("PartnerLawyer")
def partner_signoff(did):
    draft = _load_draft(did)
    body = helpers.get_json_body()
    helpers.check_occ(draft, body.get("version"))

    if draft["status"] != "IN_REVIEW":
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft must be IN_REVIEW for partner-signoff.")

    lw = _check_reviewer(draft, require_partner=True)

    if not draft.get("senior_reviewer_lawyer_id"):
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "senior_reviewer_lawyer_id must be set before partner-signoff.",
        )

    draft["partner_signoff_lawyer_id"] = lw["id"]
    draft["signed_off_at"] = clock.now()
    draft["status"] = "SIGNED_OFF"
    helpers.bump(draft)
    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=did, action="SIGNED_OFF",
    )
    return response.ok(serializers.draft_dict(draft))


@bp.route("/document-drafts/<did>/lock", methods=["POST"])
@auth_required("PartnerLawyer")
def lock_draft(did):
    draft = _load_draft(did)
    body = helpers.get_json_body()
    helpers.check_occ(draft, body.get("version"))

    if draft["status"] != "SIGNED_OFF":
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft must be SIGNED_OFF to lock.")

    user_id, _ = get_actor()
    if user_id == draft["drafter_lawyer_id"]:
        errors.raise_error(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Drafter cannot lock their own draft.",
        )

    if draft.get("template_version_pinned") is None:
        errors.raise_error(errors.ERR_INVALID_STATE, "Draft template_version_pinned missing.")

    draft["status"] = "LOCKED"
    helpers.bump(draft)
    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=did, action="LOCKED",
    )
    return response.ok(serializers.draft_dict(draft))


@bp.route("/document-drafts/<did>", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def read_draft(did):
    draft = db.document_drafts.get(did)
    if draft is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"DocumentDraft {did} not found.")
    return response.ok(serializers.draft_dict(draft))
