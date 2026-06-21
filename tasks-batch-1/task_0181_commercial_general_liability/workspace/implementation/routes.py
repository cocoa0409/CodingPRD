"""All API routes (PRD §4). Flat topology: every entity a top-level collection."""
from flask import request

from db import db
import errors
from errors import err
from common import (
    get_user_context, require_roles, attach_common, touch, parse_dt,
    parse_pagination, sorted_by_created, get_body,
)
from response import object_response, array_response
import serialize as S
import engine


# ===========================================================================
# Lookup helpers
# ===========================================================================
def _get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


def _resolve_fk(coll, rid, insurer_id):
    """Resolve a body FK within the same insurer. Raise ERR_REFERENCE_NOT_FOUND
    if missing or cross-insurer."""
    rec = coll.get(rid)
    if rec is None:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "Referenced resource not found")
    if insurer_id is not None and rec.get("insurer_id") not in (None, insurer_id):
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "Referenced resource crosses insurer boundary")
    return rec


def _policy_insurer_id(policy):
    return policy["insurer_id"]


def _claim_policy(claim):
    return db.policies.get(claim["policy_id"])


def _audit_policy(audit):
    return db.policies.get(audit["policy_id"])


# ===========================================================================
# CertificateHolder ownership filter (PRD §2.1)
# ===========================================================================
def _holder_can_read(role, user_id, record):
    """For an entity-backed CertificateHolder, a resource that references a
    certificate holder is readable only when its certificate_holder_id matches.
    Resources without a certificate_holder_id are not gated here.
    """
    if role != "CertificateHolder":
        return True
    if "certificate_holder_id" in record:
        return record.get("certificate_holder_id") == user_id
    return True


# ===========================================================================
# Generic list responder
# ===========================================================================
def _list_response(records, role=None, user_id=None):
    if role == "CertificateHolder":
        records = [r for r in records if _holder_can_read(role, user_id, r)]
    records = sorted_by_created(records)
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return page, limit, offset, total


def register(app):

    # =======================================================================
    # Insurer
    # =======================================================================
    @app.route("/insurers", methods=["POST"])
    def create_insurer():
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin"})
        body = get_body()
        rec = {
            "name": body.get("name"),
            "naic_code": body.get("naic_code"),
            "current_date": "2026-01-01T00:00:00.000Z",
            "audit_waiver_threshold_cents": body.get("audit_waiver_threshold_cents", 50000),
        }
        if rec["audit_waiver_threshold_cents"] is None:
            rec["audit_waiver_threshold_cents"] = 50000
        attach_common(rec)
        db.insurers[rec["id"]] = rec
        return object_response(S.ser_insurer(rec), 201)

    @app.route("/insurers/<insurer_id>", methods=["GET"])
    def get_insurer(insurer_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster",
                             "PremiumAuditor", "CertificateHolder"})
        rec = _get_or_404(db.insurers, insurer_id)
        return object_response(S.ser_insurer(rec), 200)

    @app.route("/insurers/<insurer_id>/clock", methods=["POST"])
    def advance_clock(insurer_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin"})
        insurer = _get_or_404(db.insurers, insurer_id)
        body = get_body()
        target_raw = body.get("to_iso8601")
        target = parse_dt(target_raw)
        current = parse_dt(insurer["current_date"])
        if target is None or target < current:
            raise err(errors.ERR_CLOCK_NOT_MONOTONIC,
                      "Clock cannot move backward")
        insurer["current_date"] = target_raw
        touch(insurer)
        # Cascade: expire IN_FORCE policies whose expiration_date <= new current_date.
        for policy in db.policies.values():
            if policy["insurer_id"] != insurer_id:
                continue
            if policy["status"] != "IN_FORCE":
                continue
            exp = parse_dt(policy["expiration_date"])
            if target >= exp:
                policy["status"] = "EXPIRED"
                touch(policy)
                # Cascade ISSUED COIs -> EXPIRED.
                for coi in db.certificates.values():
                    if coi["policy_id"] == policy["id"] and coi["status"] == "ISSUED":
                        coi["status"] = "EXPIRED"
                        touch(coi)
        return object_response(S.ser_insurer(insurer), 200)

    # =======================================================================
    # Insured
    # =======================================================================
    @app.route("/insureds", methods=["POST"])
    def create_insured():
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter"})
        body = get_body()
        insurer = _resolve_fk(db.insurers, body.get("insurer_id"), None)
        fein = body.get("fein")
        for ins in db.insureds.values():
            if ins["insurer_id"] == insurer["id"] and ins["fein"] == fein:
                raise err(errors.ERR_DUPLICATE_FEIN, "fein already used within insurer")
        rec = {
            "insurer_id": insurer["id"],
            "legal_name": body.get("legal_name"),
            "fein": fein,
            "primary_basis": body.get("primary_basis"),
        }
        attach_common(rec)
        db.insureds[rec["id"]] = rec
        return object_response(S.ser_insured(rec), 201)

    @app.route("/insureds/<insured_id>", methods=["GET"])
    def get_insured(insured_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        rec = _get_or_404(db.insureds, insured_id)
        return object_response(S.ser_insured(rec), 200)

    @app.route("/insureds", methods=["GET"])
    def list_insureds():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        recs = list(db.insureds.values())
        insurer_id = request.args.get("insurer_id")
        if insurer_id is not None:
            recs = [r for r in recs if r["insurer_id"] == insurer_id]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_insured(r) for r in page], limit, offset, total)

    # =======================================================================
    # CertificateHolder
    # =======================================================================
    @app.route("/certificate-holders", methods=["POST"])
    def create_holder():
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter"})
        body = get_body()
        insurer = _resolve_fk(db.insurers, body.get("insurer_id"), None)
        rec = {
            "insurer_id": insurer["id"],
            "holder_name": body.get("holder_name"),
            "address": body.get("address"),
        }
        attach_common(rec)
        db.certificate_holders[rec["id"]] = rec
        return object_response(S.ser_holder(rec), 201)

    @app.route("/certificate-holders/<holder_id>", methods=["GET"])
    def get_holder(holder_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster",
                             "PremiumAuditor", "CertificateHolder"})
        rec = _get_or_404(db.certificate_holders, holder_id)
        return object_response(S.ser_holder(rec), 200)

    @app.route("/certificate-holders", methods=["GET"])
    def list_holders():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "PremiumAuditor"})
        recs = list(db.certificate_holders.values())
        insurer_id = request.args.get("insurer_id")
        if insurer_id is not None:
            recs = [r for r in recs if r["insurer_id"] == insurer_id]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_holder(r) for r in page], limit, offset, total)

    # =======================================================================
    # Policy
    # =======================================================================
    @app.route("/policies", methods=["POST"])
    def create_policy():
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        body = get_body()
        insurer = _resolve_fk(db.insurers, body.get("insurer_id"), None)
        insured = _resolve_fk(db.insureds, body.get("insured_id"), insurer["id"])
        policy_number = body.get("policy_number")
        for p in db.policies.values():
            if p["insurer_id"] == insurer["id"] and p["policy_number"] == policy_number:
                raise err(errors.ERR_DUPLICATE_POLICY_NUMBER,
                          "policy_number already used within insurer")
        rec = {
            "insurer_id": insurer["id"],
            "insured_id": insured["id"],
            "policy_number": policy_number,
            "coverage_trigger": body.get("coverage_trigger"),
            "retroactive_date": body.get("retroactive_date"),
            "effective_date": body.get("effective_date"),
            "expiration_date": body.get("expiration_date"),
            "each_occurrence_limit_cents": body.get("each_occurrence_limit_cents"),
            "general_aggregate_limit_cents": body.get("general_aggregate_limit_cents"),
            "products_aggregate_limit_cents": body.get("products_aggregate_limit_cents"),
            "premium_basis": body.get("premium_basis"),
            "rate_per_unit_cents": body.get("rate_per_unit_cents"),
            "minimum_premium_cents": body.get("minimum_premium_cents"),
            "estimated_exposure_units": body.get("estimated_exposure_units"),
            "estimated_premium_cents": None,
            "audited_premium_cents": None,
            "general_aggregate_remaining_cents": None,
            "products_aggregate_remaining_cents": None,
            "posture": None,
            "status": "DRAFT",
        }
        attach_common(rec)
        db.policies[rec["id"]] = rec
        return object_response(S.ser_policy(rec), 201)

    @app.route("/policies/<policy_id>", methods=["GET"])
    def get_policy(policy_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster",
                             "PremiumAuditor", "CertificateHolder"})
        rec = _get_or_404(db.policies, policy_id)
        return object_response(S.ser_policy(rec), 200)

    @app.route("/policies", methods=["GET"])
    def list_policies():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        recs = list(db.policies.values())
        insurer_id = request.args.get("insurer_id")
        insured_id = request.args.get("insured_id")
        status = request.args.get("status")
        if insurer_id is not None:
            recs = [r for r in recs if r["insurer_id"] == insurer_id]
        if insured_id is not None:
            recs = [r for r in recs if r["insured_id"] == insured_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_policy(r) for r in page], limit, offset, total)

    @app.route("/policies/<policy_id>/bind", methods=["POST"])
    def bind_policy(policy_id):
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        policy = _get_or_404(db.policies, policy_id)
        if policy["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Policy is not in DRAFT")
        # Structural preconditions (PRD §3.2), in the stated order.
        trigger = policy["coverage_trigger"]
        retro = policy["retroactive_date"]
        eff = parse_dt(policy["effective_date"])
        exp = parse_dt(policy["expiration_date"])
        if trigger == "CLAIMS_MADE":
            if retro is None or parse_dt(retro) > eff:
                raise err(errors.ERR_RETRO_DATE_REQUIRED,
                          "CLAIMS_MADE requires retroactive_date <= effective_date")
        elif trigger == "OCCURRENCE":
            if retro is not None:
                raise err(errors.ERR_RETRO_DATE_NOT_ALLOWED,
                          "OCCURRENCE policy must have null retroactive_date")
        if not (eff < exp):
            raise err(errors.ERR_INVALID_POLICY_PERIOD,
                      "effective_date must be strictly before expiration_date")
        if policy["products_aggregate_limit_cents"] > policy["general_aggregate_limit_cents"]:
            raise err(errors.ERR_AGGREGATE_LIMIT_INVALID,
                      "products aggregate cannot exceed general aggregate")
        # Side effects.
        policy["estimated_premium_cents"] = engine.rate_premium(
            policy["estimated_exposure_units"],
            policy["rate_per_unit_cents"],
            policy["minimum_premium_cents"],
        )
        policy["general_aggregate_remaining_cents"] = policy["general_aggregate_limit_cents"]
        policy["products_aggregate_remaining_cents"] = policy["products_aggregate_limit_cents"]
        policy["posture"] = "HEALTHY"
        policy["status"] = "BOUND"
        touch(policy)
        return object_response(S.ser_policy(policy), 200)

    @app.route("/policies/<policy_id>/activate", methods=["POST"])
    def activate_policy(policy_id):
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        policy = _get_or_404(db.policies, policy_id)
        if policy["status"] != "BOUND":
            raise err(errors.ERR_INVALID_STATE, "Policy is not BOUND")
        insurer = db.insurers[policy["insurer_id"]]
        current = parse_dt(insurer["current_date"])
        eff = parse_dt(policy["effective_date"])
        if current < eff:
            raise err(errors.ERR_POLICY_NOT_YET_EFFECTIVE,
                      "current_date has not reached effective_date")
        policy["status"] = "IN_FORCE"
        touch(policy)
        return object_response(S.ser_policy(policy), 200)

    @app.route("/policies/<policy_id>/cancel", methods=["POST"])
    def cancel_policy(policy_id):
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        policy = _get_or_404(db.policies, policy_id)
        status = policy["status"]
        if status not in ("BOUND", "IN_FORCE"):
            raise err(errors.ERR_INVALID_STATE, "Policy cannot be cancelled from this state")
        if status == "IN_FORCE":
            live = {"OPEN", "RESERVED", "PAID", "REOPENED"}
            for c in db.claims.values():
                if c["policy_id"] == policy_id and c["status"] in live:
                    raise err(errors.ERR_OPEN_CLAIMS_BLOCK_CANCEL,
                              "Open claims block cancellation")
            # Cascade: VOID ACTIVE endorsements, REVOKE ISSUED COIs.
            for endo in db.endorsements.values():
                if endo["policy_id"] == policy_id and endo["status"] == "ACTIVE":
                    endo["status"] = "VOID"
                    touch(endo)
            for coi in db.certificates.values():
                if coi["policy_id"] == policy_id and coi["status"] == "ISSUED":
                    coi["status"] = "REVOKED"
                    touch(coi)
        policy["status"] = "CANCELLED"
        touch(policy)
        return object_response(S.ser_policy(policy), 200)

    # =======================================================================
    # Additional Insured Endorsement
    # =======================================================================
    _FORM_SCOPE = {
        "CG2010": "ONGOING_OPS",
        "CG2037": "COMPLETED_OPS",
        "CG2010_2037": "BOTH",
    }

    @app.route("/endorsements", methods=["POST"])
    def create_endorsement():
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        body = get_body()
        policy = _resolve_fk(db.policies, body.get("policy_id"), None)
        insurer_id = policy["insurer_id"]
        holder = _resolve_fk(db.certificate_holders, body.get("certificate_holder_id"), insurer_id)
        form_number = body.get("form_number")
        scope = _FORM_SCOPE.get(form_number)
        ai_eff_raw = body.get("ai_effective_date")
        ai_eff = parse_dt(ai_eff_raw)
        eff = parse_dt(policy["effective_date"])
        exp = parse_dt(policy["expiration_date"])
        if ai_eff is None or ai_eff < eff or ai_eff >= exp:
            raise err(errors.ERR_AI_DATE_OUTSIDE_PERIOD,
                      "ai_effective_date must be within the policy period")
        rec = {
            "policy_id": policy["id"],
            "certificate_holder_id": holder["id"],
            "form_number": form_number,
            "scope": scope,
            "ai_effective_date": ai_eff_raw,
            "status": "ACTIVE",
        }
        attach_common(rec)
        db.endorsements[rec["id"]] = rec
        # Cascade: supersede any prior ACTIVE endorsement for same holder on this policy.
        for other in db.endorsements.values():
            if other["id"] == rec["id"]:
                continue
            if (other["policy_id"] == policy["id"]
                    and other["certificate_holder_id"] == holder["id"]
                    and other["status"] == "ACTIVE"):
                other["status"] = "SUPERSEDED"
                touch(other)
                for coi in db.certificates.values():
                    if coi["additional_insured_endorsement_id"] == other["id"] and coi["status"] == "ISSUED":
                        coi["status"] = "REVOKED"
                        touch(coi)
        return object_response(S.ser_endorsement(rec), 201)

    @app.route("/endorsements/<endorsement_id>", methods=["GET"])
    def get_endorsement(endorsement_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "CertificateHolder",
                             "ClaimsAdjuster", "PremiumAuditor"})
        rec = _get_or_404(db.endorsements, endorsement_id)
        return object_response(S.ser_endorsement(rec), 200)

    @app.route("/endorsements", methods=["GET"])
    def list_endorsements():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "CertificateHolder",
                             "ClaimsAdjuster", "PremiumAuditor"})
        recs = list(db.endorsements.values())
        policy_id = request.args.get("policy_id")
        holder_id = request.args.get("certificate_holder_id")
        status = request.args.get("status")
        if policy_id is not None:
            recs = [r for r in recs if r["policy_id"] == policy_id]
        if holder_id is not None:
            recs = [r for r in recs if r["certificate_holder_id"] == holder_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_endorsement(r) for r in page], limit, offset, total)

    @app.route("/endorsements/<endorsement_id>/void", methods=["POST"])
    def void_endorsement(endorsement_id):
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        endo = _get_or_404(db.endorsements, endorsement_id)
        if endo["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Endorsement is not ACTIVE")
        endo["status"] = "VOID"
        touch(endo)
        for coi in db.certificates.values():
            if coi["additional_insured_endorsement_id"] == endo["id"] and coi["status"] == "ISSUED":
                coi["status"] = "REVOKED"
                touch(coi)
        return object_response(S.ser_endorsement(endo), 200)

    # =======================================================================
    # Certificate of Insurance
    # =======================================================================
    @app.route("/certificates", methods=["POST"])
    def create_certificate():
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        body = get_body()
        policy = _resolve_fk(db.policies, body.get("policy_id"), None)
        insurer_id = policy["insurer_id"]
        holder = _resolve_fk(db.certificate_holders, body.get("certificate_holder_id"), insurer_id)
        endo_id = body.get("additional_insured_endorsement_id")
        if endo_id is not None:
            _resolve_fk(db.endorsements, endo_id, insurer_id)
        names_ai = body.get("names_as_additional_insured", False)
        if names_ai is None:
            names_ai = False
        rec = {
            "policy_id": policy["id"],
            "certificate_holder_id": holder["id"],
            "additional_insured_endorsement_id": endo_id,
            "names_as_additional_insured": bool(names_ai),
            "issue_date": None,
            "snapshot_each_occurrence_cents": None,
            "snapshot_general_aggregate_remaining_cents": None,
            "status": "DRAFT",
        }
        attach_common(rec)
        db.certificates[rec["id"]] = rec
        return object_response(S.ser_certificate(rec), 201)

    @app.route("/certificates/<certificate_id>", methods=["GET"])
    def get_certificate(certificate_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "CertificateHolder",
                             "ClaimsAdjuster", "PremiumAuditor"})
        rec = _get_or_404(db.certificates, certificate_id)
        return object_response(S.ser_certificate(rec), 200)

    @app.route("/certificates", methods=["GET"])
    def list_certificates():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "CertificateHolder",
                             "ClaimsAdjuster", "PremiumAuditor"})
        recs = list(db.certificates.values())
        policy_id = request.args.get("policy_id")
        holder_id = request.args.get("certificate_holder_id")
        endo_id = request.args.get("additional_insured_endorsement_id")
        status = request.args.get("status")
        if policy_id is not None:
            recs = [r for r in recs if r["policy_id"] == policy_id]
        if holder_id is not None:
            recs = [r for r in recs if r["certificate_holder_id"] == holder_id]
        if endo_id is not None:
            recs = [r for r in recs if r["additional_insured_endorsement_id"] == endo_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_certificate(r) for r in page], limit, offset, total)

    @app.route("/certificates/<certificate_id>/issue", methods=["POST"])
    def issue_certificate(certificate_id):
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        coi = _get_or_404(db.certificates, certificate_id)
        if coi["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Certificate is not DRAFT")
        policy = db.policies[coi["policy_id"]]
        if policy["status"] != "IN_FORCE":
            raise err(errors.ERR_POLICY_NOT_IN_FORCE, "Policy is not IN_FORCE")
        if policy["posture"] == "EXHAUSTED":
            raise err(errors.ERR_POLICY_EXHAUSTED, "Policy posture is EXHAUSTED")
        if coi["names_as_additional_insured"]:
            endo_id = coi["additional_insured_endorsement_id"]
            endo = db.endorsements.get(endo_id) if endo_id is not None else None
            if (endo is None or endo["status"] != "ACTIVE"
                    or endo["certificate_holder_id"] != coi["certificate_holder_id"]):
                raise err(errors.ERR_AI_ENDORSEMENT_MISSING,
                          "No ACTIVE matching endorsement backs the AI assertion")
        coi["issue_date"] = db.insurers[policy["insurer_id"]]["current_date"]
        coi["snapshot_each_occurrence_cents"] = policy["each_occurrence_limit_cents"]
        coi["snapshot_general_aggregate_remaining_cents"] = policy["general_aggregate_remaining_cents"]
        coi["status"] = "ISSUED"
        touch(coi)
        return object_response(S.ser_certificate(coi), 200)

    @app.route("/certificates/<certificate_id>/revoke", methods=["POST"])
    def revoke_certificate(certificate_id):
        _, role = get_user_context()
        require_roles(role, {"Underwriter"})
        coi = _get_or_404(db.certificates, certificate_id)
        if coi["status"] != "ISSUED":
            raise err(errors.ERR_INVALID_STATE, "Certificate is not ISSUED")
        coi["status"] = "REVOKED"
        touch(coi)
        return object_response(S.ser_certificate(coi), 200)

    # =======================================================================
    # Claim
    # =======================================================================
    @app.route("/claims", methods=["POST"])
    def create_claim():
        _, role = get_user_context()
        require_roles(role, {"ClaimsAdjuster"})
        body = get_body()
        policy = _resolve_fk(db.policies, body.get("policy_id"), None)
        loss_type = body.get("loss_type")
        bucket = "PRODUCTS" if loss_type == "PRODUCTS_COMPLETED_OPS" else "GENERAL"
        rec = {
            "policy_id": policy["id"],
            "claimant_name": body.get("claimant_name"),
            "loss_type": loss_type,
            "occurrence_date": body.get("occurrence_date"),
            "reported_date": body.get("reported_date"),
            "aggregate_bucket": bucket,
            "incurred_cents": 0,
            "recognized_incurred_cents": 0,
            "status": "OPEN",
        }
        attach_common(rec)
        db.claims[rec["id"]] = rec
        return object_response(S.ser_claim(rec), 201)

    @app.route("/claims/<claim_id>", methods=["GET"])
    def get_claim(claim_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        rec = _get_or_404(db.claims, claim_id)
        return object_response(S.ser_claim(rec), 200)

    @app.route("/claims", methods=["GET"])
    def list_claims():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        recs = list(db.claims.values())
        policy_id = request.args.get("policy_id")
        loss_type = request.args.get("loss_type")
        status = request.args.get("status")
        if policy_id is not None:
            recs = [r for r in recs if r["policy_id"] == policy_id]
        if loss_type is not None:
            recs = [r for r in recs if r["loss_type"] == loss_type]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_claim(r) for r in page], limit, offset, total)

    @app.route("/claims/<claim_id>/transactions", methods=["POST"])
    def post_transaction(claim_id):
        _, role = get_user_context()
        require_roles(role, {"ClaimsAdjuster"})
        claim = _get_or_404(db.claims, claim_id)
        policy = _claim_policy(claim)
        body = get_body()
        txn_type = body.get("txn_type")
        amount = body.get("amount_cents")
        expected_version = body.get("expected_policy_version")
        status = claim["status"]

        # --- State gate (priority 5): is the transition legal from this state? ---
        valid_types = {"RESERVE_SET", "PAYMENT", "RECOVERY", "RESERVE_RELEASE"}
        is_opening = txn_type == "RESERVE_SET" and status in ("OPEN", "REOPENED")
        if status in ("OPEN", "REOPENED"):
            # Only the opening RESERVE_SET is allowed from OPEN/REOPENED.
            if txn_type != "RESERVE_SET":
                raise err(errors.ERR_INVALID_STATE,
                          "Only RESERVE_SET may open a claim")
        elif status == "RESERVED":
            if txn_type not in ("RESERVE_SET", "RESERVE_RELEASE", "RECOVERY", "PAYMENT"):
                raise err(errors.ERR_INVALID_STATE, "Invalid transaction for RESERVED claim")
        elif status == "PAID":
            if txn_type not in ("PAYMENT", "RESERVE_SET", "RESERVE_RELEASE", "RECOVERY"):
                raise err(errors.ERR_INVALID_STATE, "Invalid transaction for PAID claim")
        else:
            # CLOSED / DENIED cannot take transactions.
            raise err(errors.ERR_INVALID_STATE, "Claim cannot accept transactions in its current state")

        # --- Coverage trigger test (priority 8): only on the opening RESERVE_SET. ---
        if is_opening:
            if policy["status"] != "IN_FORCE":
                raise err(errors.ERR_POLICY_NOT_IN_FORCE, "Policy is not IN_FORCE")
            _coverage_test(policy, claim)

        # --- Amount validation (priority 9). ---
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise err(errors.ERR_INVALID_AMOUNT, "amount_cents must be a positive integer")

        # --- Release/recovery overrun (priority 10). ---
        if txn_type == "RESERVE_RELEASE":
            if amount > engine.compute_open_reserve(claim_id):
                raise err(errors.ERR_RELEASE_EXCEEDS_RESERVE,
                          "RESERVE_RELEASE exceeds open reserve")
        elif txn_type == "RECOVERY":
            cum_payments = sum(t["amount_cents"] for t in engine.claim_transactions(claim_id)
                               if t["txn_type"] == "PAYMENT")
            if amount > cum_payments:
                raise err(errors.ERR_RELEASE_EXCEEDS_RESERVE,
                          "RECOVERY exceeds cumulative payments")
        elif txn_type not in valid_types:
            raise err(errors.ERR_INVALID_STATE, "Unknown txn_type")

        # --- OCC (priority 15, last): required on every txn except the opening RESERVE_SET. ---
        if not is_opening:
            if expected_version != policy["version"]:
                raise err(errors.ERR_STALE_POLICY_VERSION,
                          "expected_policy_version does not match policy version")

        # --- Commit: append transaction, advance claim state, cascade. ---
        seq = 1 + max((t["posted_sequence"] for t in engine.claim_transactions(claim_id)), default=0)
        txn = {
            "claim_id": claim_id,
            "txn_type": txn_type,
            "amount_cents": amount,
            "posted_sequence": seq,
            "memo": body.get("memo"),
        }
        attach_common(txn, with_version=False)
        db.claim_transactions[txn["id"]] = txn

        # Advance claim state.
        if txn_type == "RESERVE_SET" and status in ("OPEN", "REOPENED"):
            claim["status"] = "RESERVED"
        elif txn_type == "PAYMENT" and status == "RESERVED":
            claim["status"] = "PAID"
        # else: state unchanged (RESERVED stays RESERVED, PAID stays PAID).

        engine.recompute_claim_and_cascade(claim, policy, bump_policy_version=True)
        return object_response(S.ser_transaction(txn), 201)

    @app.route("/claim-transactions/<transaction_id>", methods=["GET"])
    def get_transaction(transaction_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        rec = _get_or_404(db.claim_transactions, transaction_id)
        return object_response(S.ser_transaction(rec), 200)

    @app.route("/claim-transactions", methods=["GET"])
    def list_transactions():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        recs = list(db.claim_transactions.values())
        claim_id = request.args.get("claim_id")
        txn_type = request.args.get("txn_type")
        if claim_id is not None:
            recs = [r for r in recs if r["claim_id"] == claim_id]
        if txn_type is not None:
            recs = [r for r in recs if r["txn_type"] == txn_type]
        # Posted order: by created order (which equals posted_sequence within a claim).
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_transaction(r) for r in page], limit, offset, total)

    @app.route("/claims/<claim_id>/close", methods=["POST"])
    def close_claim(claim_id):
        _, role = get_user_context()
        require_roles(role, {"ClaimsAdjuster"})
        claim = _get_or_404(db.claims, claim_id)
        if claim["status"] not in ("RESERVED", "PAID"):
            raise err(errors.ERR_INVALID_STATE, "Claim cannot be closed from this state")
        # Net open reserve must be zero.
        reserve_set = sum(t["amount_cents"] for t in engine.claim_transactions(claim_id)
                          if t["txn_type"] == "RESERVE_SET")
        reserve_release = sum(t["amount_cents"] for t in engine.claim_transactions(claim_id)
                              if t["txn_type"] == "RESERVE_RELEASE")
        if (reserve_set - reserve_release) != 0:
            raise err(errors.ERR_OPEN_RESERVE_REMAINS, "Open reserve remains")
        claim["status"] = "CLOSED"
        policy = _claim_policy(claim)
        # incurred recompute + cascade (released room may return); policy version bumps.
        engine.recompute_claim_and_cascade(claim, policy, bump_policy_version=True)
        return object_response(S.ser_claim(claim), 200)

    @app.route("/claims/<claim_id>/deny", methods=["POST"])
    def deny_claim(claim_id):
        _, role = get_user_context()
        require_roles(role, {"ClaimsAdjuster"})
        claim = _get_or_404(db.claims, claim_id)
        # Deny is attempted from OPEN / RESERVED / PAID; CLOSED/DENIED/REOPENED
        # are not deniable (state gate). A PAID claim is then rejected by the
        # no-payment rule (PRD §3.7).
        if claim["status"] not in ("OPEN", "RESERVED", "PAID"):
            raise err(errors.ERR_INVALID_STATE, "Claim cannot be denied from this state")
        has_payment = any(t["txn_type"] == "PAYMENT"
                          for t in engine.claim_transactions(claim_id))
        if has_payment:
            raise err(errors.ERR_PAID_CLAIM_CANNOT_DENY, "Paid claim cannot be denied")
        claim["status"] = "DENIED"
        claim["recognized_incurred_cents"] = 0
        touch(claim)
        policy = _claim_policy(claim)
        # DENIED claim contributes 0 to erosion; recompute aggregates + posture; bump policy.
        engine.recompute_aggregates_and_posture(policy)
        touch(policy)
        return object_response(S.ser_claim(claim), 200)

    @app.route("/claims/<claim_id>/reopen", methods=["POST"])
    def reopen_claim(claim_id):
        _, role = get_user_context()
        require_roles(role, {"ClaimsAdjuster"})
        claim = _get_or_404(db.claims, claim_id)
        if claim["status"] != "CLOSED":
            raise err(errors.ERR_INVALID_STATE, "Only a CLOSED claim can be reopened")
        policy = _claim_policy(claim)
        if policy["status"] != "IN_FORCE":
            raise err(errors.ERR_POLICY_NOT_IN_FORCE, "Policy is not IN_FORCE")
        claim["status"] = "REOPENED"
        touch(claim)
        touch(policy)
        return object_response(S.ser_claim(claim), 200)

    # =======================================================================
    # Premium Audit
    # =======================================================================
    @app.route("/audits", methods=["POST"])
    def create_audit():
        _, role = get_user_context()
        require_roles(role, {"PremiumAuditor", "InsurerAdmin"})
        body = get_body()
        policy = _resolve_fk(db.policies, body.get("policy_id"), None)
        audit_basis = body.get("audit_basis")
        if audit_basis != policy["premium_basis"]:
            raise err(errors.ERR_AUDIT_BASIS_MISMATCH,
                      "audit_basis must equal policy premium_basis")
        rec = {
            "policy_id": policy["id"],
            "audit_basis": audit_basis,
            "audited_exposure_units": 0,
            "computed_audited_premium_cents": None,
            "net_adjustment_cents": None,
            "revision_round": 0,
            "status": "SCHEDULED",
        }
        attach_common(rec)
        db.audits[rec["id"]] = rec
        return object_response(S.ser_audit(rec), 201)

    @app.route("/audits/<audit_id>", methods=["GET"])
    def get_audit(audit_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "PremiumAuditor"})
        rec = _get_or_404(db.audits, audit_id)
        return object_response(S.ser_audit(rec), 200)

    @app.route("/audits", methods=["GET"])
    def list_audits():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "PremiumAuditor"})
        recs = list(db.audits.values())
        policy_id = request.args.get("policy_id")
        status = request.args.get("status")
        if policy_id is not None:
            recs = [r for r in recs if r["policy_id"] == policy_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_audit(r) for r in page], limit, offset, total)

    @app.route("/audits/<audit_id>/start", methods=["POST"])
    def start_audit(audit_id):
        _, role = get_user_context()
        require_roles(role, {"PremiumAuditor"})
        audit = _get_or_404(db.audits, audit_id)
        if audit["status"] != "SCHEDULED":
            raise err(errors.ERR_INVALID_STATE, "Audit is not SCHEDULED")
        policy = _audit_policy(audit)
        if policy["status"] != "EXPIRED":
            raise err(errors.ERR_POLICY_NOT_AUDITABLE, "Policy is not EXPIRED")
        audit["status"] = "IN_PROGRESS"
        touch(audit)
        return object_response(S.ser_audit(audit), 200)

    @app.route("/audits/<audit_id>/exposure-records", methods=["POST"])
    def create_exposure(audit_id):
        _, role = get_user_context()
        require_roles(role, {"PremiumAuditor"})
        audit = _get_or_404(db.audits, audit_id)
        if audit["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "Audit is not IN_PROGRESS")
        body = get_body()
        rec = {
            "premium_audit_id": audit["id"],
            "class_code": body.get("class_code"),
            "basis_amount_units": body.get("basis_amount_units"),
        }
        attach_common(rec)
        db.exposure_records[rec["id"]] = rec
        # Recompute audited_exposure_units (order-independent sum).
        audit["audited_exposure_units"] = sum(
            e["basis_amount_units"] for e in db.exposure_records.values()
            if e["premium_audit_id"] == audit["id"]
        )
        touch(audit)
        return object_response(S.ser_exposure(rec), 201)

    @app.route("/exposure-records/<exposure_record_id>", methods=["GET"])
    def get_exposure(exposure_record_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "PremiumAuditor"})
        rec = _get_or_404(db.exposure_records, exposure_record_id)
        return object_response(S.ser_exposure(rec), 200)

    @app.route("/exposure-records", methods=["GET"])
    def list_exposure():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "PremiumAuditor"})
        recs = list(db.exposure_records.values())
        audit_id = request.args.get("premium_audit_id")
        class_code = request.args.get("class_code")
        if audit_id is not None:
            recs = [r for r in recs if r["premium_audit_id"] == audit_id]
        if class_code is not None:
            recs = [r for r in recs if r["class_code"] == class_code]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_exposure(r) for r in page], limit, offset, total)

    @app.route("/audits/<audit_id>/complete", methods=["POST"])
    def complete_audit(audit_id):
        _, role = get_user_context()
        require_roles(role, {"PremiumAuditor"})
        audit = _get_or_404(db.audits, audit_id)
        if audit["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "Audit is not IN_PROGRESS")
        records = [e for e in db.exposure_records.values()
                   if e["premium_audit_id"] == audit["id"]]
        if len(records) == 0:
            raise err(errors.ERR_NO_EXPOSURE_RECORDS, "No exposure records on this audit")
        policy = _audit_policy(audit)
        units = sum(e["basis_amount_units"] for e in records)
        audit["audited_exposure_units"] = units
        computed = engine.rate_premium(units, policy["rate_per_unit_cents"],
                                       policy["minimum_premium_cents"])
        audit["computed_audited_premium_cents"] = computed
        audit["net_adjustment_cents"] = computed - policy["estimated_premium_cents"]
        audit["status"] = "COMPLETED"
        touch(audit)
        return object_response(S.ser_audit(audit), 200)

    @app.route("/audits/<audit_id>/dispute", methods=["POST"])
    def dispute_audit(audit_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin"})
        audit = _get_or_404(db.audits, audit_id)
        if audit["status"] != "COMPLETED":
            raise err(errors.ERR_INVALID_STATE, "Audit is not COMPLETED")
        audit["status"] = "DISPUTED"
        touch(audit)
        return object_response(S.ser_audit(audit), 200)

    @app.route("/audits/<audit_id>/reopen", methods=["POST"])
    def reopen_audit(audit_id):
        _, role = get_user_context()
        require_roles(role, {"PremiumAuditor"})
        audit = _get_or_404(db.audits, audit_id)
        if audit["status"] != "DISPUTED":
            raise err(errors.ERR_INVALID_STATE, "Audit is not DISPUTED")
        audit["status"] = "IN_PROGRESS"
        audit["revision_round"] = audit["revision_round"] + 1
        audit["computed_audited_premium_cents"] = None
        audit["net_adjustment_cents"] = None
        touch(audit)
        return object_response(S.ser_audit(audit), 200)

    @app.route("/audits/<audit_id>/finalize", methods=["POST"])
    def finalize_audit(audit_id):
        _, role = get_user_context()
        require_roles(role, {"PremiumAuditor"})
        audit = _get_or_404(db.audits, audit_id)
        if audit["status"] != "COMPLETED":
            raise err(errors.ERR_INVALID_STATE, "Audit is not COMPLETED")
        policy = _audit_policy(audit)
        insurer = db.insurers[policy["insurer_id"]]
        threshold = insurer["audit_waiver_threshold_cents"]
        net = audit["net_adjustment_cents"]
        body = get_body()
        expected_version = body.get("expected_policy_version")

        if abs(net) <= threshold:
            # WAIVED branch: estimate stands; no policy version bump in scaffold.
            audit["status"] = "WAIVED"
            touch(audit)
            policy["audited_premium_cents"] = policy["estimated_premium_cents"]
            policy["status"] = "AUDIT_CLOSED"
            touch(policy)
        else:
            # FINALIZED branch: OCC check, then write computed premium; bump policy.
            if expected_version != policy["version"]:
                raise err(errors.ERR_STALE_POLICY_VERSION,
                          "expected_policy_version does not match policy version")
            audit["status"] = "FINALIZED"
            touch(audit)
            policy["audited_premium_cents"] = audit["computed_audited_premium_cents"]
            policy["status"] = "AUDIT_CLOSED"
            touch(policy)
        return object_response(S.ser_audit(audit), 200)

    # =======================================================================
    # Loss Run
    # =======================================================================
    @app.route("/policies/<policy_id>/loss-runs", methods=["POST"])
    def generate_loss_run(policy_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster", "PremiumAuditor"})
        policy = _get_or_404(db.policies, policy_id)
        insurer = db.insurers[policy["insurer_id"]]
        cutoff_raw = insurer["current_date"]
        cutoff = parse_dt(cutoff_raw)
        included = []
        for c in db.claims.values():
            if c["policy_id"] != policy_id:
                continue
            if parse_dt(c["reported_date"]) <= cutoff:
                included.append(c)
        total_incurred = sum(c["incurred_cents"] for c in included)
        general_incurred = sum(c["incurred_cents"] for c in included
                               if c["aggregate_bucket"] == "GENERAL")
        products_incurred = sum(c["incurred_cents"] for c in included
                                if c["aggregate_bucket"] == "PRODUCTS")
        claim_count = len(included)
        open_count = sum(1 for c in included if c["status"] not in ("CLOSED", "DENIED"))
        rec = {
            "policy_id": policy_id,
            "as_of_date": cutoff_raw,
            "total_incurred_cents": total_incurred,
            "general_incurred_cents": general_incurred,
            "products_incurred_cents": products_incurred,
            "claim_count": claim_count,
            "open_claim_count": open_count,
        }
        attach_common(rec)
        db.loss_runs[rec["id"]] = rec
        return object_response(S.ser_loss_run(rec), 201)

    @app.route("/loss-runs/<loss_run_id>", methods=["GET"])
    def get_loss_run(loss_run_id):
        _, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster",
                             "PremiumAuditor", "CertificateHolder"})
        rec = _get_or_404(db.loss_runs, loss_run_id)
        return object_response(S.ser_loss_run(rec), 200)

    @app.route("/loss-runs", methods=["GET"])
    def list_loss_runs():
        user_id, role = get_user_context()
        require_roles(role, {"InsurerAdmin", "Underwriter", "ClaimsAdjuster",
                             "PremiumAuditor", "CertificateHolder"})
        recs = list(db.loss_runs.values())
        policy_id = request.args.get("policy_id")
        if policy_id is not None:
            recs = [r for r in recs if r["policy_id"] == policy_id]
        page, limit, offset, total = _list_response(recs, role, user_id)
        return array_response([S.ser_loss_run(r) for r in page], limit, offset, total)


# ===========================================================================
# Coverage trigger test (PRD §3.5, calc coverage_test)
# ===========================================================================
def _coverage_test(policy, claim):
    eff = parse_dt(policy["effective_date"])
    exp = parse_dt(policy["expiration_date"])
    occ = parse_dt(claim["occurrence_date"])
    if policy["coverage_trigger"] == "OCCURRENCE":
        if not (occ >= eff and occ < exp):
            raise err(errors.ERR_OCCURRENCE_OUTSIDE_PERIOD,
                      "occurrence_date outside policy period")
    else:  # CLAIMS_MADE
        retro = parse_dt(policy["retroactive_date"])
        if not (occ >= retro):
            raise err(errors.ERR_CLAIM_BEFORE_RETRO_DATE,
                      "occurrence_date before retroactive_date")
        rep = parse_dt(claim["reported_date"])
        if not (rep >= eff and rep < exp):
            raise err(errors.ERR_OCCURRENCE_OUTSIDE_PERIOD,
                      "reported_date outside policy period")
