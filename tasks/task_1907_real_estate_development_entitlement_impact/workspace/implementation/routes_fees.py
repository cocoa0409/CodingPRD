"""Routes: conditions of approval, impact fee assessments, payments, deferral,
development agreements, referendum petitions, appeals, permit sequences."""

from decimal import Decimal

from flask import request

import store
from store import CLOCK, touch
from auth import authenticate, authorize, require_owner
from envelope import success, paginate
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_APPLICATION_NOT_APPROVED, ERR_TEMPORAL_WINDOW_VIOLATION,
    ERR_REFERENDUM_WINDOW_CLOSED, ERR_APPEAL_WINDOW_CLOSED,
    ERR_INSUFFICIENT_SIGNATURES, ERR_PERMIT_ALREADY_ISSUED,
    ERR_PAYMENT_EXCEEDS_BALANCE, ERR_NOT_FOUND,
)
from validate import (
    body_or_empty, require_fields, reject_version_fields, req_str, req_enum,
    req_int, req_datetime, req_number,
)
import domain
from domain import get_or_404, D

ALL_ROLES = ("PlatformAdmin", "Applicant", "StaffReviewer", "DecisionAuthority")


def _json():
    return request.get_json(silent=True)


def _app_or_404(appId):
    return get_or_404("applications", appId, "EntitlementApplication")


def _owning_project(app_rec):
    return domain.project_for(app_rec) if app_rec else None


def register_fee_routes(app):

    # --- conditions of approval ----------------------------------------------
    @app.post("/entitlement/applications/<appId>/conditions")
    def create_condition(appId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["condition_text", "category", "required_before"])
        text = req_str(body, "condition_text")
        category = req_enum(body, "category",
                            ("FEE", "IMPROVEMENT", "DESIGN", "ENVIRONMENTAL"))
        required_before = req_enum(body, "required_before",
                                   ("PERMIT_ISSUANCE", "CERTIFICATE_OF_OCCUPANCY",
                                    "FINAL_INSPECTION"))
        if app_rec["status"] != "APPROVED":
            raise ApiError(ERR_APPLICATION_NOT_APPROVED,
                           "Conditions are added at or after approval", 409)
        # A PERMIT_ISSUANCE condition created after a permit already issued is
        # BREACHED on arrival (the milestone passed without satisfaction).
        breached = False
        if required_before == "PERMIT_ISSUANCE":
            breached = any(
                s for s in store.all_records("permit_sequences")
                if s.get("application_id") == appId and s["status"] == "ISSUED")
        rec = store.new_record("conditions")
        rec.update({
            "application_id": appId,
            "condition_text": text,
            "category": category,
            "required_before": required_before,
            "satisfied_at": None,
            "status": "BREACHED" if breached else "PENDING",
        })
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/conditions")
    def list_conditions(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [c for c in store.all_records("conditions")
                if c.get("application_id") == appId]
        for param in ("status", "required_before"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/conditions/<conditionId>")
    def get_condition(conditionId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("conditions", conditionId,
                                  "ConditionOfApproval"), 200)

    @app.get("/entitlement/conditions")
    def filter_conditions():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("conditions")
        for param in ("application_id", "status", "required_before"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/conditions/<conditionId>/satisfy")
    def satisfy_condition(conditionId):
        p = authenticate()
        authorize(p, ("Applicant",))
        reject_version_fields(body_or_empty(_json()))
        cond = get_or_404("conditions", conditionId, "ConditionOfApproval")
        if cond["status"] in ("SATISFIED", "WAIVED", "BREACHED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Condition is in a terminal state", 409)
        app_rec = store.get("applications", cond.get("application_id"))
        if app_rec is None or app_rec["status"] != "APPROVED":
            raise ApiError(ERR_APPLICATION_NOT_APPROVED,
                           "A condition can be satisfied only while the parent "
                           "application stands APPROVED", 409)
        project = _owning_project(app_rec)
        if project is not None:
            require_owner(p, project)
        cond["status"] = "SATISFIED"
        cond["satisfied_at"] = store.fmt_dt(CLOCK.now())
        touch(cond)
        return success(cond, 200)

    @app.post("/entitlement/conditions/<conditionId>/waive")
    def waive_condition(conditionId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        reject_version_fields(body_or_empty(_json()))
        cond = get_or_404("conditions", conditionId, "ConditionOfApproval")
        if cond["status"] in ("SATISFIED", "WAIVED", "BREACHED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Condition is in a terminal state", 409)
        cond["status"] = "WAIVED"
        touch(cond)
        return success(cond, 200)

    # --- assessments / payments ------------------------------------------------
    @app.get("/entitlement/applications/<appId>/assessments")
    def list_assessments(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [a for a in store.all_records("assessments")
                if a.get("application_id") == appId]
        for param in ("variant", "status"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/assessments/<assessmentId>")
    def get_assessment(assessmentId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("assessments", assessmentId,
                                  "ImpactFeeAssessment"), 200)

    @app.get("/entitlement/assessments")
    def filter_assessments():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("assessments")
        for param in ("application_id", "fee_schedule_id", "variant",
                      "status"):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(param) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/assessments/<assessmentId>/payments")
    def create_payment(assessmentId):
        p = authenticate()
        authorize(p, ("Applicant",))
        assessment = get_or_404("assessments", assessmentId,
                                "ImpactFeeAssessment")
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["amount", "paid_at"])
        amount_raw = req_number(body, "amount")
        amount = D(amount_raw)
        if amount <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "amount must be > 0", 400)
        paid_at = req_datetime(body, "paid_at")

        if assessment["status"] == "REFUNDED":
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Assessment is REFUNDED; no further payments", 409)
        app_rec = store.get("applications", assessment.get("application_id"))
        project = _owning_project(app_rec)
        if project is not None:
            require_owner(p, project)

        domain.recompute_outstanding(assessment)
        outstanding = D(assessment["outstanding_balance"])
        if assessment["status"] == "PAID" or amount > outstanding:
            raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE,
                           "Payment amount exceeds the outstanding balance",
                           402)

        late_fee = domain.compute_late_fee(amount, paid_at,
                                           assessment.get("due_date"))
        rec = store.new_record("payments")
        rec.update({
            "assessment_id": assessmentId,
            "amount": domain.r2(amount),
            "paid_at": store.fmt_dt(paid_at),
            "late_fee": late_fee,
            "applied_amount": domain.r2(amount),
            "refunded": False,
        })

        paid_total = domain.paid_in_total(assessment)
        net = D(assessment["net_total"])
        domain.recompute_outstanding(assessment)
        if paid_total >= net:
            assessment["status"] = "PAID"
        elif assessment["status"] == "OPEN":
            assessment["status"] = "PARTIALLY_PAID"
        # DEFERRED stays DEFERRED until the balance reaches zero, then PAID.
        touch(assessment)
        return success(rec, 201)

    @app.get("/entitlement/assessments/<assessmentId>/payments")
    def list_payments(assessmentId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        get_or_404("assessments", assessmentId, "ImpactFeeAssessment")
        recs = [pay for pay in store.all_records("payments")
                if pay.get("assessment_id") == assessmentId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/payments/<paymentId>")
    def get_payment(paymentId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("payments", paymentId, "FeePayment"), 200)

    @app.get("/entitlement/payments")
    def filter_payments():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("payments")
        v = request.args.get("assessment_id")
        if v is not None:
            recs = [r for r in recs if r.get("assessment_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/assessments/<assessmentId>/defer")
    def defer_assessment(assessmentId):
        p = authenticate()
        authorize(p, ("Applicant",))
        reject_version_fields(body_or_empty(_json()))
        assessment = get_or_404("assessments", assessmentId,
                                "ImpactFeeAssessment")
        if assessment["status"] == "REFUNDED":
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Assessment is REFUNDED; no further transitions",
                           409)
        # Fixed order (PRD 3.7): permit check FIRST, then the variant check.
        app_id = assessment.get("application_id")
        issued = [s for s in store.all_records("permit_sequences")
                  if s.get("application_id") == app_id
                  and s["status"] == "ISSUED"]
        if issued:
            raise ApiError(ERR_PERMIT_ALREADY_ISSUED,
                           "Cannot defer fees: a permit has already been "
                           "issued", 409)
        if assessment.get("variant") != "FINAL":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a FINAL assessment can be deferred", 409)
        app_rec = store.get("applications", app_id)
        project = _owning_project(app_rec)
        if project is not None:
            require_owner(p, project)
        assessment["status"] = "DEFERRED"
        # Due date moves to the certificate-of-occupancy milestone (no concrete
        # date exists for that milestone; payments are not late while deferred).
        assessment["due_date"] = None
        domain.recompute_outstanding(assessment)
        touch(assessment)
        return success(assessment, 200)

    # --- development agreements --------------------------------------------------
    @app.post("/entitlement/applications/<appId>/development-agreements")
    def create_da(appId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["agreement_number", "adoption_date",
                              "vesting_term_years", "registered_voters"])
        number = req_str(body, "agreement_number")
        adoption = req_datetime(body, "adoption_date")
        years = req_int(body, "vesting_term_years")
        voters = req_int(body, "registered_voters")
        if years < 1 or years > 15:
            raise ApiError(ERR_INVALID_REQUEST,
                           "vesting_term_years must be between 1 and 15", 400)
        if voters <= 0:
            raise ApiError(ERR_INVALID_REQUEST,
                           "registered_voters must be > 0", 400)
        if app_rec["status"] != "APPROVED":
            raise ApiError(ERR_APPLICATION_NOT_APPROVED,
                           "A development agreement is drafted on an approved "
                           "application", 409)
        from datetime import timedelta
        rec = store.new_record("development_agreements")
        rec.update({
            "application_id": appId,
            "agreement_number": number,
            "adoption_date": store.fmt_dt(adoption),
            "vesting_term_years": years,
            "registered_voters": voters,
            "vesting_expires_at": store.fmt_dt(domain.add_years(adoption,
                                                                years)),
            "referendum_deadline": store.fmt_dt(
                adoption + timedelta(days=domain.REFERENDUM_WINDOW_DAYS)),
            "vesting_status": None,
            "status": "DRAFT",
        })
        return success(rec, 201)

    @app.get("/entitlement/development-agreements/<daId>")
    def get_da(daId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("development_agreements", daId,
                                  "DevelopmentAgreement"), 200)

    @app.get("/entitlement/applications/<appId>/development-agreements")
    def list_das(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [d for d in store.all_records("development_agreements")
                if d.get("application_id") == appId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/development-agreements")
    def filter_das():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("development_agreements")
        v = request.args.get("application_id")
        if v is not None:
            recs = [r for r in recs if r.get("application_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/development-agreements/<daId>/adopt")
    def adopt_da(daId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        reject_version_fields(body_or_empty(_json()))
        da = get_or_404("development_agreements", daId, "DevelopmentAgreement")
        if da["status"] in ("EFFECTIVE", "REPEALED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "DevelopmentAgreement is in a terminal state", 409)
        if da["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a DRAFT development agreement can be "
                           "adopted", 409)
        app_rec = store.get("applications", da.get("application_id"))
        if app_rec is None or app_rec["status"] != "APPROVED":
            raise ApiError(ERR_APPLICATION_NOT_APPROVED,
                           "Parent application must be APPROVED", 409)
        da["status"] = "ADOPTED"
        da["vesting_status"] = "PENDING_REFERENDUM"
        touch(da)
        return success(da, 200)

    @app.post("/entitlement/development-agreements/<daId>/finalize-vesting")
    def finalize_vesting(daId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        reject_version_fields(body_or_empty(_json()))
        da = get_or_404("development_agreements", daId, "DevelopmentAgreement")
        if da["status"] in ("EFFECTIVE", "REPEALED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "DevelopmentAgreement is in a terminal state", 409)
        if da["status"] != "ADOPTED":
            raise ApiError(ERR_INVALID_STATE,
                           "Only an ADOPTED development agreement can "
                           "finalize vesting", 409)
        qualified = any(
            pet for pet in store.all_records("petitions")
            if pet.get("development_agreement_id") == daId
            and pet["status"] == "CERTIFIED_QUALIFIED")
        if qualified:
            raise ApiError(ERR_INVALID_STATE,
                           "A CERTIFIED_QUALIFIED petition blocks vesting",
                           409)
        if CLOCK.now() < store.parse_dt(da["referendum_deadline"]):
            raise ApiError(ERR_TEMPORAL_WINDOW_VIOLATION,
                           "The referendum window has not yet lapsed", 422)
        da["status"] = "EFFECTIVE"
        da["vesting_status"] = "VESTED"
        touch(da)
        return success(da, 200)

    # --- referendum petitions ------------------------------------------------------
    @app.post("/entitlement/development-agreements/<daId>/referendum-petitions")
    def file_petition(daId):
        p = authenticate()
        authorize(p, ("Applicant", "PlatformAdmin"))
        da = get_or_404("development_agreements", daId, "DevelopmentAgreement")
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["filed_at", "valid_signature_count"])
        filed_at = req_datetime(body, "filed_at")
        valid = req_int(body, "valid_signature_count")
        if valid < 0:
            raise ApiError(ERR_INVALID_REQUEST,
                           "valid_signature_count must be >= 0", 400)
        if da["status"] != "ADOPTED":
            raise ApiError(ERR_INVALID_STATE,
                           "Petitions may be filed only while the referendum "
                           "window is open (agreement ADOPTED)", 409)
        if filed_at >= store.parse_dt(da["referendum_deadline"]):
            raise ApiError(ERR_REFERENDUM_WINDOW_CLOSED,
                           "Petition filed_at is on or after the "
                           "referendum_deadline", 422)
        required = domain.referendum_required_signatures(
            da["registered_voters"])
        rec = store.new_record("petitions")
        rec.update({
            "development_agreement_id": daId,
            "filed_at": store.fmt_dt(filed_at),
            "valid_signature_count": valid,
            "required_signature_count": required,
            "qualifies": valid >= required,
            "status": "FILED",
        })
        return success(rec, 201)

    @app.get("/entitlement/development-agreements/<daId>/referendum-petitions")
    def list_petitions(daId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        get_or_404("development_agreements", daId, "DevelopmentAgreement")
        recs = [pet for pet in store.all_records("petitions")
                if pet.get("development_agreement_id") == daId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/referendum-petitions/<petitionId>")
    def get_petition(petitionId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("petitions", petitionId,
                                  "ReferendumPetition"), 200)

    @app.get("/entitlement/referendum-petitions")
    def filter_petitions():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("petitions")
        v = request.args.get("development_agreement_id")
        if v is not None:
            recs = [r for r in recs if r.get("development_agreement_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/referendum-petitions/<petitionId>/certify")
    def certify_petition(petitionId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        reject_version_fields(body_or_empty(_json()))
        pet = get_or_404("petitions", petitionId, "ReferendumPetition")
        if pet["status"] in ("CERTIFIED_QUALIFIED", "CERTIFIED_INSUFFICIENT",
                             "REJECTED_UNTIMELY"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Petition is in a terminal state", 409)
        da = store.get("development_agreements",
                       pet.get("development_agreement_id"))
        deadline = store.parse_dt(da["referendum_deadline"]) if da else None
        filed_at = store.parse_dt(pet["filed_at"])
        if deadline is not None and filed_at >= deadline:
            pet["status"] = "REJECTED_UNTIMELY"
            touch(pet)
            return success(pet, 200)
        if pet["valid_signature_count"] >= pet["required_signature_count"]:
            pet["status"] = "CERTIFIED_QUALIFIED"
            touch(pet)
            if da is not None and da["status"] == "ADOPTED":
                da["status"] = "REPEALED"
                da["vesting_status"] = "INVALIDATED"
                touch(da)
            return success(pet, 200)
        # Timely but short: the petition is disposed CERTIFIED_INSUFFICIENT
        # and the shortfall is reported as ERR_INSUFFICIENT_SIGNATURES.
        pet["status"] = "CERTIFIED_INSUFFICIENT"
        touch(pet)
        raise ApiError(ERR_INSUFFICIENT_SIGNATURES,
                       "valid_signature_count is below "
                       "required_signature_count; petition disposed as "
                       "CERTIFIED_INSUFFICIENT", 422)

    # --- appeals ---------------------------------------------------------------------
    @app.post("/entitlement/applications/<appId>/appeals")
    def file_appeal(appId):
        p = authenticate()
        authorize(p, ("Applicant", "PlatformAdmin"))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["appellant_name", "filed_at", "grounds"])
        appellant = req_str(body, "appellant_name")
        filed_at = req_datetime(body, "filed_at")
        grounds = req_str(body, "grounds")
        decision = domain.latest_decision_for(appId)
        if decision is None:
            raise ApiError(ERR_INVALID_STATE,
                           "No rendered decision exists for this application",
                           409)
        if decision["status"] != "RENDERED":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a RENDERED decision can be appealed", 409)
        if filed_at >= store.parse_dt(decision["appeal_deadline"]):
            raise ApiError(ERR_APPEAL_WINDOW_CLOSED,
                           "Appeal filed_at is on or after the "
                           "appeal_deadline", 422)
        rec = store.new_record("appeals")
        rec.update({
            "application_id": appId,
            "appellant_name": appellant,
            "filed_at": store.fmt_dt(filed_at),
            "grounds": grounds,
            "status": "FILED",
        })
        decision["status"] = "STAYED_ON_APPEAL"
        touch(decision)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/appeals")
    def list_appeals(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [a for a in store.all_records("appeals")
                if a.get("application_id") == appId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/appeals/<appealId>")
    def get_appeal(appealId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("appeals", appealId, "Appeal"), 200)

    @app.get("/entitlement/appeals")
    def filter_appeals():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("appeals")
        v = request.args.get("application_id")
        if v is not None:
            recs = [r for r in recs if r.get("application_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/appeals/<appealId>/resolve")
    def resolve_appeal(appealId):
        p = authenticate()
        authorize(p, ("DecisionAuthority",))
        appeal = get_or_404("appeals", appealId, "Appeal")
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["ruling"])
        ruling = req_enum(body, "ruling", ("UPHELD", "REVERSED", "DISMISS"))
        if appeal["status"] in ("UPHELD", "REVERSED", "DISMISSED_UNTIMELY"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Appeal is in a terminal state", 409)
        decision = domain.latest_decision_for(appeal["application_id"])
        if ruling == "UPHELD":
            appeal["status"] = "UPHELD"
            if decision is not None and decision["status"] == "STAYED_ON_APPEAL":
                decision["status"] = "FINAL"
                touch(decision)
        elif ruling == "REVERSED":
            appeal["status"] = "REVERSED"
            if decision is not None and decision["status"] == "STAYED_ON_APPEAL":
                decision["status"] = "REVERSED_ON_APPEAL"
                touch(decision)
            app_rec = store.get("applications", appeal["application_id"])
            if app_rec is not None:
                app_rec["status"] = "DECISION_PENDING"
                touch(app_rec)
        else:  # DISMISS
            appeal["status"] = "DISMISSED_UNTIMELY"
            if decision is not None and decision["status"] == "STAYED_ON_APPEAL":
                decision["status"] = "FINAL"
                touch(decision)
        touch(appeal)
        return success(appeal, 200)

    # --- permit sequences --------------------------------------------------------------
    @app.post("/entitlement/applications/<appId>/permit-sequences")
    def request_permit(appId):
        p = authenticate()
        authorize(p, ("Applicant",))
        app_rec = _app_or_404(appId)
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["permit_type"])
        permit_type = req_enum(body, "permit_type",
                               ("GRADING", "BUILDING", "UTILITY", "OCCUPANCY"))
        project = _owning_project(app_rec)
        if project is not None:
            require_owner(p, project)
        rec = store.new_record("permit_sequences")
        rec.update({
            "application_id": appId,
            "permit_type": permit_type,
            "sequence_rank": domain.SEQUENCE_RANKS[permit_type],
            "requested_at": store.fmt_dt(CLOCK.now()),
            "issued_at": None,
            "status": "REQUESTED",
        })
        # A request whose issuance preconditions already fail is recorded as
        # BLOCKED (terminal) instead of REQUESTED (PRD 3.9).
        if domain.issuance_blockers(rec):
            rec["status"] = "BLOCKED"
            touch(rec)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>/permit-sequences")
    def list_permits(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        _app_or_404(appId)
        recs = [s for s in store.all_records("permit_sequences")
                if s.get("application_id") == appId]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.get("/entitlement/permit-sequences/<seqId>")
    def get_permit(seqId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("permit_sequences", seqId,
                                  "PermitSequence"), 200)

    @app.get("/entitlement/permit-sequences")
    def filter_permits():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("permit_sequences")
        v = request.args.get("application_id")
        if v is not None:
            recs = [r for r in recs if r.get("application_id") == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/permit-sequences/<seqId>/issue")
    def issue_permit(seqId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        seq = get_or_404("permit_sequences", seqId, "PermitSequence")
        if seq["status"] in ("ISSUED", "BLOCKED"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "PermitSequence is in a terminal state", 409)
        blockers = domain.issuance_blockers(seq)
        if blockers:
            error_id, message, status = blockers[0]
            raise ApiError(error_id, message, status)
        seq["status"] = "ISSUED"
        seq["issued_at"] = store.fmt_dt(CLOCK.now())
        touch(seq)
        return success(seq, 200)
