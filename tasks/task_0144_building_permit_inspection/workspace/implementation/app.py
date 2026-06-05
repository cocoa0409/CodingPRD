"""Building Permit & Inspection API — Flask entry point.

In-memory only. No seeding at startup. Boots fast on every re-launch.
"""
import os
from datetime import timedelta

from flask import Flask, request

from errors import ApiError
from money import D, round2, money_out
from store import db, lock, new_id, fmt_ts, parse_ts
from response import ok_object, ok_array, error_response
import domain
import validation as V


app = Flask(__name__)
app.url_map.strict_slashes = False


# =====================================================================
# Record creation helpers
# =====================================================================
def _stamp_new(rec, versioned=True):
    now = db.clock.now()
    rec["_created_at"] = now
    rec["_seq"] = db.next_seq()
    if versioned:
        rec["_updated_at"] = now
        rec["version"] = 1
    return rec


def _bump(rec):
    rec["_updated_at"] = db.clock.now()
    rec["version"] = rec.get("version", 1) + 1


def append_event(permit_id, event_type, detail):
    ev = {
        "id": new_id(),
        "permit_id": permit_id,
        "event_type": event_type,
        "detail": detail,
    }
    _stamp_new(ev, versioned=False)
    db.permit_events[ev["id"]] = ev
    return ev


# =====================================================================
# Error handling
# =====================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_PERMIT_NOT_FOUND", "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_FORBIDDEN_ROLE", "Method not allowed.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))


# =====================================================================
# Health
# =====================================================================
@app.route("/", methods=["GET"])
def root():
    return ok_object({"service": "building-permit-inspection"})


# =====================================================================
# Jurisdictions
# =====================================================================
@app.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        body = V.get_json_body()
        name = V.require_str(body, "name")
        code_edition = V.require_str(body, "code_edition")
        valuation_rate = V.require_number(body, "valuation_fee_rate_per_1000", minimum=0)
        sqft_rate = V.require_number(body, "square_foot_rate", minimum=0)
        plan_pct = V.require_number(body, "plan_review_fee_pct", minimum=0)
        min_fee = V.require_number(body, "minimum_permit_fee", minimum=0)
        renewal_pct = V.opt_number(body, "renewal_fee_pct", 0.5, minimum=0)
        valid_days = V.opt_int(body, "permit_valid_days", 180, minimum=1)

        rec = {
            "id": new_id(),
            "name": name,
            "code_edition": code_edition,
            "valuation_fee_rate_per_1000": valuation_rate,
            "square_foot_rate": sqft_rate,
            "plan_review_fee_pct": plan_pct,
            "minimum_permit_fee": min_fee,
            "renewal_fee_pct": renewal_pct,
            "permit_valid_days": valid_days,
        }
        _stamp_new(rec)
        db.jurisdictions[rec["id"]] = rec
        return ok_object(domain.ser_jurisdiction(rec), 201)


@app.route("/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction(jid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant", "PlanReviewer", "Inspector"])
        rec = V.lookup("jurisdictions", jid)
        return ok_object(domain.ser_jurisdiction(rec))


# =====================================================================
# Contractors
# =====================================================================
@app.route("/contractors", methods=["POST"])
def create_contractor():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PermitClerk", "BuildingOfficial"])
        body = V.get_json_body()
        business_name = V.require_str(body, "business_name")
        license_number = V.require_str(body, "license_number")
        license_status = V.opt_enum(body, "license_status", ["ACTIVE", "SUSPENDED", "EXPIRED"], "ACTIVE")
        license_expiry = V.require_datetime(body, "license_expiry")
        bond_amount = V.require_number(body, "bond_amount", minimum=0)
        bond_status = V.opt_enum(body, "bond_status", ["VERIFIED", "UNVERIFIED", "REVOKED"], "UNVERIFIED")

        # uniqueness (priority 5)
        for c in db.contractors.values():
            if c["license_number"] == license_number:
                raise ApiError("ERR_DUPLICATE_LICENSE", "license_number already in use")

        rec = {
            "id": new_id(),
            "business_name": business_name,
            "license_number": license_number,
            "license_status": license_status,
            "license_expiry": license_expiry,
            "bond_amount": bond_amount,
            "bond_status": bond_status,
        }
        _stamp_new(rec)
        db.contractors[rec["id"]] = rec
        return ok_object(domain.ser_contractor(rec), 201)


@app.route("/contractors/<cid>", methods=["GET"])
def get_contractor(cid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PermitClerk", "BuildingOfficial", "Applicant"])
        rec = V.lookup("contractors", cid)
        return ok_object(domain.ser_contractor(rec))


@app.route("/contractors/<cid>", methods=["PATCH"])
def patch_contractor(cid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PermitClerk", "BuildingOfficial"])
        rec = V.lookup("contractors", cid)
        body = V.get_json_body()
        if "license_status" in body and body["license_status"] is not None:
            rec["license_status"] = V.require_enum(body, "license_status", ["ACTIVE", "SUSPENDED", "EXPIRED"])
        if "license_expiry" in body and body["license_expiry"] is not None:
            rec["license_expiry"] = V.require_datetime(body, "license_expiry")
        if "bond_amount" in body and body["bond_amount"] is not None:
            rec["bond_amount"] = V.require_number(body, "bond_amount", minimum=0)
        if "bond_status" in body and body["bond_status"] is not None:
            rec["bond_status"] = V.require_enum(body, "bond_status", ["VERIFIED", "UNVERIFIED", "REVOKED"])
        _bump(rec)
        return ok_object(domain.ser_contractor(rec))


# =====================================================================
# Inspectors / Plan Reviewers
# =====================================================================
@app.route("/inspectors", methods=["POST"])
def create_inspector():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        body = V.get_json_body()
        full_name = V.require_str(body, "full_name")
        badge_number = V.require_str(body, "badge_number")
        for i in db.inspectors.values():
            if i["badge_number"] == badge_number:
                raise ApiError("ERR_DUPLICATE_LICENSE", "badge_number already in use")
        rec = {"id": new_id(), "full_name": full_name, "badge_number": badge_number}
        _stamp_new(rec)
        db.inspectors[rec["id"]] = rec
        return ok_object(domain.ser_inspector(rec), 201)


@app.route("/inspectors/<iid>", methods=["GET"])
def get_inspector(iid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant", "Inspector"])
        rec = V.lookup("inspectors", iid, "ERR_INSPECTION_NOT_FOUND")
        return ok_object(domain.ser_inspector(rec))


@app.route("/plan-reviewers", methods=["POST"])
def create_plan_reviewer():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        body = V.get_json_body()
        full_name = V.require_str(body, "full_name")
        cert_number = V.require_str(body, "cert_number")
        for pr in db.plan_reviewers.values():
            if pr["cert_number"] == cert_number:
                raise ApiError("ERR_DUPLICATE_LICENSE", "cert_number already in use")
        rec = {"id": new_id(), "full_name": full_name, "cert_number": cert_number}
        _stamp_new(rec)
        db.plan_reviewers[rec["id"]] = rec
        return ok_object(domain.ser_plan_reviewer(rec), 201)


@app.route("/plan-reviewers/<pid>", methods=["GET"])
def get_plan_reviewer(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant", "PlanReviewer"])
        rec = V.lookup("plan_reviewers", pid, "ERR_REVIEW_NOT_FOUND")
        return ok_object(domain.ser_plan_reviewer(rec))


# =====================================================================
# Permits
# =====================================================================
@app.route("/permits", methods=["POST"])
def create_permit():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        body = V.get_json_body()
        # existence (priority 3): left-to-right jurisdiction then contractor
        jurisdiction_id = V.require_str(body, "jurisdiction_id")
        contractor_id = V.require_str(body, "contractor_id")
        V.lookup("jurisdictions", jurisdiction_id)
        V.lookup("contractors", contractor_id)
        # body shape (priority 4)
        work_class = V.require_enum(body, "work_class", ["NEW_CONSTRUCTION", "ADDITION", "ALTERATION", "REPAIR"])
        fee_method = V.require_enum(body, "fee_method", ["VALUATION", "SQUARE_FOOT"])
        declared_valuation = V.opt_number(body, "declared_valuation", 0, minimum=0)
        floor_area_sqft = V.opt_number(body, "floor_area_sqft", 0, minimum=0)

        rec = {
            "id": new_id(),
            "jurisdiction_id": jurisdiction_id,
            "contractor_id": contractor_id,
            "work_class": work_class,
            "fee_method": fee_method,
            "declared_valuation": declared_valuation,
            "floor_area_sqft": floor_area_sqft,
            "accrued_renewal_fees": round2(0),
            "status": "SUBMITTED",
            "work_status": "NOT_STARTED",
            "review_cycle": 0,
            "issued_at": None,
            "expires_at": None,
            "approving_reviewer_id": None,
        }
        _stamp_new(rec)
        domain.recompute_fees(rec)
        db.permits[rec["id"]] = rec
        append_event(rec["id"], "SUBMITTED", "Permit application submitted.")
        return ok_object(domain.ser_permit(rec), 201)


@app.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk", "BuildingOfficial", "PlanReviewer", "Inspector"])
        rec = V.lookup("permits", pid)
        return ok_object(domain.ser_permit(rec))


@app.route("/permits", methods=["GET"])
def list_permits():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk", "BuildingOfficial", "PlanReviewer", "Inspector"])
        limit, offset = V.get_pagination()
        contractor_id = request.args.get("contractor_id")
        jurisdiction_id = request.args.get("jurisdiction_id")
        approving_reviewer_id = request.args.get("approving_reviewer_id")
        status = request.args.get("status")
        rows = list(db.permits.values())
        if contractor_id is not None:
            rows = [r for r in rows if r["contractor_id"] == contractor_id]
        if jurisdiction_id is not None:
            rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
        if approving_reviewer_id is not None:
            rows = [r for r in rows if r.get("approving_reviewer_id") == approving_reviewer_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_permit(r) for r in page], limit, offset, total)


@app.route("/permits/<pid>/withdraw", methods=["POST"])
def withdraw_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        permit = V.lookup("permits", pid)
        if permit["status"] not in ("SUBMITTED", "UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE", "Cannot withdraw from status %s" % permit["status"])
        # complete any OPEN plan review
        for r in db.plan_reviews.values():
            if r["permit_id"] == pid and r["review_status"] == "OPEN":
                r["review_status"] = "COMPLETED"
                _bump(r)
        permit["status"] = "WITHDRAWN"
        _bump(permit)
        append_event(pid, "WITHDRAWN", "Permit withdrawn.")
        return ok_object(domain.ser_permit(permit))


@app.route("/permits/<pid>/resubmit", methods=["POST"])
def resubmit_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        permit = V.lookup("permits", pid)
        if permit["status"] != "CORRECTIONS_REQUIRED":
            raise ApiError("ERR_INVALID_STATE", "Resubmit requires CORRECTIONS_REQUIRED")
        if domain.compute_open_correction_count(pid) != 0:
            raise ApiError("ERR_OPEN_CORRECTIONS", "Open corrections remain")
        permit["review_cycle"] += 1
        review = {
            "id": new_id(),
            "permit_id": pid,
            "reviewer_id": None,
            "cycle_number": permit["review_cycle"],
            "decision": "PENDING",
            "review_status": "OPEN",
        }
        # reviewer_id is assigned when a reviewer opens — but resubmit opens a
        # fresh review without a named reviewer until decided? PRD says it opens
        # a fresh OPEN PlanReview. It does not name a reviewer in the resubmit
        # body, so reviewer_id stays unset until a decision; however decide
        # requires the actor to equal reviewer_id. Keep None; a later /reviews
        # open would conflict. Per PRD the resubmit itself opens the review.
        _stamp_new(review)
        db.plan_reviews[review["id"]] = review
        permit["status"] = "UNDER_REVIEW"
        _bump(permit)
        append_event(pid, "RESUBMITTED", "Permit resubmitted for review.")
        return ok_object(domain.ser_permit(permit))


@app.route("/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PermitClerk"])
        permit = V.lookup("permits", pid)
        body = V.get_json_body()
        # priority 4: required body field
        expected = V.require_int(body, "expected_permit_application_version")
        # priority 6: state
        if permit["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Issue requires APPROVED")
        # priority 7: OCC
        if expected != permit["version"]:
            raise ApiError("ERR_STALE_PERMIT_VERSION", "Permit version mismatch")
        # priority 10: contractor verified
        contractor = db.contractors[permit["contractor_id"]]
        if domain.compute_verification_status(contractor) != "VERIFIED":
            raise ApiError("ERR_CONTRACTOR_UNVERIFIED", "Contractor not verified")
        # priority 17: balance due
        if domain.compute_balance_due(permit) != round2(0):
            raise ApiError("ERR_BALANCE_DUE", "Balance due must be zero")

        now = db.clock.now()
        jur = db.jurisdictions[permit["jurisdiction_id"]]
        permit["issued_at"] = now
        permit["expires_at"] = now + timedelta(days=jur["permit_valid_days"])
        permit["status"] = "ISSUED"
        permit["work_status"] = "ACTIVE"
        _bump(permit)
        append_event(pid, "ISSUED", "Permit issued.")
        return ok_object(domain.ser_permit(permit))


@app.route("/permits/<pid>/renew", methods=["POST"])
def renew_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PermitClerk"])
        permit = V.lookup("permits", pid)
        body = V.get_json_body()
        expected = V.require_int(body, "expected_permit_application_version")
        if permit["status"] != "EXPIRED":
            raise ApiError("ERR_INVALID_STATE", "Renew requires EXPIRED")
        if expected != permit["version"]:
            raise ApiError("ERR_STALE_PERMIT_VERSION", "Permit version mismatch")
        contractor = db.contractors[permit["contractor_id"]]
        if domain.compute_verification_status(contractor) != "VERIFIED":
            raise ApiError("ERR_CONTRACTOR_UNVERIFIED", "Contractor not verified")

        jur = db.jurisdictions[permit["jurisdiction_id"]]
        renewal_fee = round2(D(permit["total_permit_fee"]) * D(jur["renewal_fee_pct"]))
        permit["accrued_renewal_fees"] = round2(D(permit.get("accrued_renewal_fees", 0)) + renewal_fee)
        now = db.clock.now()
        permit["issued_at"] = now
        permit["expires_at"] = now + timedelta(days=jur["permit_valid_days"])
        permit["status"] = "ISSUED"
        permit["work_status"] = "ACTIVE"
        _bump(permit)
        append_event(pid, "RENEWED", "Permit renewed.")
        return ok_object(domain.ser_permit(permit))


@app.route("/permits/<pid>/expire", methods=["POST"])
def expire_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        permit = V.lookup("permits", pid)
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Expire requires ISSUED")
        now = db.clock.now()
        if permit["expires_at"] is None or now < permit["expires_at"]:
            raise ApiError("ERR_INVALID_STATE", "Clock has not reached expires_at")
        # no ISSUED CofO may exist
        for c in db.certificates.values():
            if c["permit_id"] == pid and c["co_status"] == "ISSUED":
                raise ApiError("ERR_INVALID_STATE", "An issued certificate exists")

        permit["work_status"] = "STOPPED"
        permit["status"] = "EXPIRED"
        _cancel_scheduled_inspections(pid)
        _bump(permit)
        append_event(pid, "EXPIRED", "Permit expired.")
        return ok_object(domain.ser_permit(permit))


@app.route("/permits/<pid>/finalize", methods=["POST"])
def finalize_permit(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        permit = V.lookup("permits", pid)
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Finalize requires ISSUED")
        # priority 11: work stopped gate
        if permit["work_status"] == "STOPPED":
            raise ApiError("ERR_WORK_STOPPED", "Active stop-work order blocks finalize")
        # priority 17: balance due (PRD §2.6 lists balance-due before certificate-present)
        if domain.compute_balance_due(permit) != round2(0):
            raise ApiError("ERR_BALANCE_DUE", "Balance due must be zero")
        # priority 18: certificate present
        has_co = any(c["permit_id"] == pid and c["co_status"] == "ISSUED" for c in db.certificates.values())
        if not has_co:
            raise ApiError("ERR_NO_CERTIFICATE", "An issued certificate of occupancy is required")

        permit["status"] = "FINALED"
        _bump(permit)
        append_event(pid, "ISSUED", "Permit finalized (closeout).")
        return ok_object(domain.ser_permit(permit))


# =====================================================================
# Fee payments
# =====================================================================
@app.route("/permits/<pid>/payments", methods=["POST"])
def create_payment(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        permit = V.lookup("permits", pid)
        body = V.get_json_body()
        amount = V.require_number(body, "amount", gt=0)
        payment_status = V.opt_enum(body, "payment_status", ["CLEARED", "VOID"], "CLEARED")
        rec = {
            "id": new_id(),
            "permit_id": pid,
            "amount": round2(amount),
            "payment_status": payment_status,
        }
        _stamp_new(rec, versioned=False)
        db.fee_payments[rec["id"]] = rec
        # recompute is implicit in serializer; bump permit as a mutation
        _bump(permit)
        return ok_object(domain.ser_fee_payment(rec), 201)


@app.route("/payments/<pmid>", methods=["GET"])
def get_payment(pmid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk", "BuildingOfficial"])
        rec = db.fee_payments.get(pmid)
        if rec is None:
            raise ApiError("ERR_PERMIT_NOT_FOUND", "Payment not found")
        return ok_object(domain.ser_fee_payment(rec))


@app.route("/payments", methods=["GET"])
def list_payments():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk", "BuildingOfficial"])
        limit, offset = V.get_pagination()
        permit_id = request.args.get("permit_id")
        rows = list(db.fee_payments.values())
        if permit_id is not None:
            rows = [r for r in rows if r["permit_id"] == permit_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_fee_payment(r) for r in page], limit, offset, total)


# =====================================================================
# Plan reviews
# =====================================================================
@app.route("/permits/<pid>/reviews", methods=["POST"])
def open_review(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer"])
        permit = V.lookup("permits", pid)
        body = V.get_json_body()
        reviewer_id = V.require_str(body, "reviewer_id")
        V.lookup("plan_reviewers", reviewer_id, "ERR_REVIEW_NOT_FOUND")
        # priority 6: state — permit SUBMITTED and no OPEN review exists
        if permit["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Opening a review requires SUBMITTED")
        for r in db.plan_reviews.values():
            if r["permit_id"] == pid and r["review_status"] == "OPEN":
                raise ApiError("ERR_INVALID_STATE", "An OPEN review already exists")

        review = {
            "id": new_id(),
            "permit_id": pid,
            "reviewer_id": reviewer_id,
            "cycle_number": permit["review_cycle"],
            "decision": "PENDING",
            "review_status": "OPEN",
        }
        _stamp_new(review)
        db.plan_reviews[review["id"]] = review
        permit["status"] = "UNDER_REVIEW"
        _bump(permit)
        append_event(pid, "REVIEW_OPENED", "Plan review opened.")
        return ok_object(domain.ser_plan_review(review), 201)


@app.route("/reviews/<rid>", methods=["GET"])
def get_review(rid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer", "PermitClerk", "BuildingOfficial", "Applicant"])
        rec = V.lookup("plan_reviews", rid)
        return ok_object(domain.ser_plan_review(rec))


@app.route("/reviews", methods=["GET"])
def list_reviews():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer", "PermitClerk", "BuildingOfficial", "Applicant"])
        limit, offset = V.get_pagination()
        permit_id = request.args.get("permit_id")
        reviewer_id = request.args.get("reviewer_id")
        rows = list(db.plan_reviews.values())
        if permit_id is not None:
            rows = [r for r in rows if r["permit_id"] == permit_id]
        if reviewer_id is not None:
            rows = [r for r in rows if r["reviewer_id"] == reviewer_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_plan_review(r) for r in page], limit, offset, total)


@app.route("/reviews/<rid>/decide", methods=["POST"])
def decide_review(rid):
    with lock:
        uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer"])
        review = V.lookup("plan_reviews", rid)
        body = V.get_json_body()
        decision = V.require_enum(body, "decision", ["APPROVED", "CORRECTIONS"])
        permit = db.permits.get(review["permit_id"])
        # priority 6: state — review OPEN and permit UNDER_REVIEW
        if review["review_status"] != "OPEN" or permit["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Review not decidable in current state")
        # priority 8: assigned-reviewer ownership
        if review["reviewer_id"] != uid:
            raise ApiError("ERR_NOT_ASSIGNED_REVIEWER", "Acting reviewer is not assigned")

        if decision == "APPROVED":
            # priority 12: open corrections gate
            if domain.compute_open_correction_count(permit["id"]) != 0:
                raise ApiError("ERR_OPEN_CORRECTIONS", "Open corrections remain")
            review["decision"] = "APPROVED"
            review["review_status"] = "COMPLETED"
            _bump(review)
            permit["status"] = "APPROVED"
            permit["approving_reviewer_id"] = review["reviewer_id"]
            _bump(permit)
            append_event(permit["id"], "APPROVED", "Plan review approved.")
        else:  # CORRECTIONS
            # priority 12: requires at least one OPEN correction on this review
            has_open = any(
                cn["plan_review_id"] == rid and cn["item_status"] == "OPEN"
                for cn in db.correction_notices.values()
            )
            if not has_open:
                raise ApiError("ERR_OPEN_CORRECTIONS", "A corrections decision needs an open notice")
            review["decision"] = "CORRECTIONS"
            review["review_status"] = "COMPLETED"
            _bump(review)
            permit["status"] = "CORRECTIONS_REQUIRED"
            _bump(permit)
            append_event(permit["id"], "CORRECTIONS_REQUIRED", "Corrections required.")
        return ok_object(domain.ser_plan_review(review))


# =====================================================================
# Correction notices
# =====================================================================
@app.route("/reviews/<rid>/correction-notices", methods=["POST"])
def create_correction_notice(rid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer"])
        review = V.lookup("plan_reviews", rid)
        body = V.get_json_body()
        code_section = V.require_str(body, "code_section")
        description = V.require_str(body, "description")
        # priority 6: parent review must be OPEN
        if review["review_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Parent review must be OPEN")

        permit = db.permits.get(review["permit_id"])
        rec = {
            "id": new_id(),
            "plan_review_id": rid,
            "permit_id": review["permit_id"],
            "code_section": code_section,
            "description": description,
            "item_status": "OPEN",
        }
        _stamp_new(rec)
        db.correction_notices[rec["id"]] = rec
        if permit is not None:
            _bump(permit)
        return ok_object(domain.ser_correction_notice(rec), 201)


@app.route("/correction-notices/<cnid>", methods=["GET"])
def get_correction_notice(cnid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer", "PermitClerk", "BuildingOfficial", "Applicant"])
        rec = V.lookup("correction_notices", cnid)
        return ok_object(domain.ser_correction_notice(rec))


@app.route("/correction-notices", methods=["GET"])
def list_correction_notices():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["PlanReviewer", "PermitClerk", "BuildingOfficial", "Applicant"])
        limit, offset = V.get_pagination()
        plan_review_id = request.args.get("plan_review_id")
        permit_id = request.args.get("permit_id")
        rows = list(db.correction_notices.values())
        if plan_review_id is not None:
            rows = [r for r in rows if r["plan_review_id"] == plan_review_id]
        if permit_id is not None:
            rows = [r for r in rows if r["permit_id"] == permit_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_correction_notice(r) for r in page], limit, offset, total)


@app.route("/correction-notices/<cnid>/resolve", methods=["POST"])
def resolve_correction_notice(cnid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        rec = V.lookup("correction_notices", cnid)
        permit = db.permits.get(rec["permit_id"])
        # priority 6: notice OPEN and parent permit CORRECTIONS_REQUIRED
        if rec["item_status"] != "OPEN" or (permit is not None and permit["status"] != "CORRECTIONS_REQUIRED"):
            raise ApiError("ERR_INVALID_STATE", "Notice not resolvable in current state")
        rec["item_status"] = "RESOLVED"
        _bump(rec)
        if permit is not None:
            _bump(permit)
        return ok_object(domain.ser_correction_notice(rec))


# =====================================================================
# Inspection slots
# =====================================================================
@app.route("/inspection-slots", methods=["POST"])
def create_slot():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "Inspector"])
        body = V.get_json_body()
        inspector_id = V.require_str(body, "inspector_id")
        # PRD §2.5 enumerates which referenced identifiers receive an existence
        # check; inspector_id is NOT among them and there is no
        # ERR_INSPECTOR_NOT_FOUND. The slot simply records the inspector_id it
        # belongs to (PRD §3.7), so no existence lookup is performed here.
        window_start = V.require_datetime(body, "window_start")
        window_end = V.require_datetime(body, "window_end")
        if parse_ts(window_end) <= parse_ts(window_start):
            raise ApiError("ERR_INVALID_REQUEST", "window_end must be after window_start")
        max_inspections = V.opt_int(body, "max_inspections", 1, minimum=1)
        rec = {
            "id": new_id(),
            "inspector_id": inspector_id,
            "window_start": window_start,
            "window_end": window_end,
            "max_inspections": max_inspections,
        }
        _stamp_new(rec)
        db.inspection_slots[rec["id"]] = rec
        return ok_object(domain.ser_slot(rec), 201)


@app.route("/inspection-slots/<sid>", methods=["GET"])
def get_slot(sid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "Inspector", "Applicant", "PermitClerk"])
        rec = V.lookup("inspection_slots", sid)
        return ok_object(domain.ser_slot(rec))


@app.route("/inspection-slots", methods=["GET"])
def list_slots():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "Inspector", "Applicant", "PermitClerk"])
        limit, offset = V.get_pagination()
        inspector_id = request.args.get("inspector_id")
        rows = list(db.inspection_slots.values())
        if inspector_id is not None:
            rows = [r for r in rows if r["inspector_id"] == inspector_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_slot(r) for r in page], limit, offset, total)


# =====================================================================
# Inspections
# =====================================================================
@app.route("/permits/<pid>/inspections", methods=["POST"])
def schedule_inspection(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        permit = V.lookup("permits", pid)
        body = V.get_json_body()
        # existence (priority 3): slot referenced in body
        slot_id = V.require_str(body, "slot_id")
        slot = V.lookup("inspection_slots", slot_id)
        # body shape (priority 4)
        inspection_type = V.require_enum(body, "inspection_type", ["ROUGH", "FINAL"])
        scheduled_start = V.require_datetime(body, "scheduled_start")
        scheduled_end = V.require_datetime(body, "scheduled_end")
        ss = parse_ts(scheduled_start)
        se = parse_ts(scheduled_end)
        if se <= ss:
            raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be after scheduled_start")

        # priority 6: parent permit must be ISSUED
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Permit must be ISSUED to schedule")

        # priority 13: FINAL requires a PASSED ROUGH
        if inspection_type == "FINAL":
            has_rough_pass = any(
                i["permit_id"] == pid and i["inspection_type"] == "ROUGH" and i["inspection_status"] == "PASSED"
                for i in db.inspections.values()
            )
            if not has_rough_pass:
                raise ApiError("ERR_ROUGH_NOT_PASSED", "A passed ROUGH inspection is required")

        # priority 14: interval within slot window
        ws = parse_ts(slot["window_start"])
        we = parse_ts(slot["window_end"])
        if not (ss >= ws and se <= we):
            raise ApiError("ERR_OUTSIDE_SLOT_WINDOW", "Interval not within slot window")

        # priority 15: inspector double-booking (half-open overlap)
        inspector_id = slot["inspector_id"]
        for i in db.inspections.values():
            if i["inspector_id"] != inspector_id:
                continue
            if i["inspection_status"] not in ("SCHEDULED", "PASSED", "FAILED"):
                continue
            os = parse_ts(i["scheduled_start"])
            oe = parse_ts(i["scheduled_end"])
            if ss < oe and os < se:  # genuine overlap on half-open intervals
                raise ApiError("ERR_INSPECTOR_DOUBLE_BOOKED", "Inspector overlap")

        # priority 16: slot capacity
        if domain.compute_booked_count(slot_id) >= slot["max_inspections"]:
            raise ApiError("ERR_SLOT_CAPACITY_FULL", "Slot is full")

        rec = {
            "id": new_id(),
            "permit_id": pid,
            "slot_id": slot_id,
            "inspector_id": inspector_id,
            "inspection_type": inspection_type,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "inspection_status": "SCHEDULED",
        }
        _stamp_new(rec)
        db.inspections[rec["id"]] = rec
        append_event(pid, "INSPECTION_SCHEDULED", "Inspection scheduled (%s)." % inspection_type)
        return ok_object(domain.ser_inspection(rec), 201)


@app.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk", "BuildingOfficial", "Inspector"])
        rec = V.lookup("inspections", iid)
        return ok_object(domain.ser_inspection(rec))


@app.route("/inspections", methods=["GET"])
def list_inspections():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk", "BuildingOfficial", "Inspector"])
        limit, offset = V.get_pagination()
        permit_id = request.args.get("permit_id")
        slot_id = request.args.get("slot_id")
        inspector_id = request.args.get("inspector_id")
        rows = list(db.inspections.values())
        if permit_id is not None:
            rows = [r for r in rows if r["permit_id"] == permit_id]
        if slot_id is not None:
            rows = [r for r in rows if r["slot_id"] == slot_id]
        if inspector_id is not None:
            rows = [r for r in rows if r["inspector_id"] == inspector_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_inspection(r) for r in page], limit, offset, total)


@app.route("/inspections/<iid>/result", methods=["POST"])
def inspection_result(iid):
    with lock:
        uid, role = V.authenticate()
        V.authorize(role, ["Inspector"])
        insp = V.lookup("inspections", iid)
        body = V.get_json_body()
        outcome = V.require_enum(body, "outcome", ["PASS", "FAIL"])
        permit = db.permits.get(insp["permit_id"])
        # priority 6: state — inspection SCHEDULED and permit ISSUED
        if insp["inspection_status"] != "SCHEDULED" or permit["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Result not recordable in current state")

        if outcome == "PASS" and insp["inspection_type"] == "FINAL":
            # priority 9: segregation of duties (before work-stopped per §2.6 order)
            if uid == permit.get("approving_reviewer_id"):
                raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Plan approver may not field-sign FINAL")

        # priority 11: work stopped gate
        if permit["work_status"] == "STOPPED":
            raise ApiError("ERR_WORK_STOPPED", "Active stop-work order blocks result entry")

        if outcome == "PASS" and insp["inspection_type"] == "FINAL":
            # priority 13: rough must be passed
            has_rough_pass = any(
                i["permit_id"] == insp["permit_id"]
                and i["inspection_type"] == "ROUGH"
                and i["inspection_status"] == "PASSED"
                for i in db.inspections.values()
            )
            if not has_rough_pass:
                raise ApiError("ERR_ROUGH_NOT_PASSED", "A passed ROUGH inspection is required")

        if outcome == "PASS":
            insp["inspection_status"] = "PASSED"
            _bump(insp)
            append_event(insp["permit_id"], "INSPECTION_PASSED", "Inspection passed.")
            if insp["inspection_type"] == "FINAL":
                co = {
                    "id": new_id(),
                    "permit_id": insp["permit_id"],
                    "final_inspection_id": insp["id"],
                    "co_type": "FINAL",
                    "co_status": "ISSUED",
                }
                _stamp_new(co)
                db.certificates[co["id"]] = co
                append_event(insp["permit_id"], "CO_ISSUED", "Certificate of occupancy issued.")
        else:  # FAIL
            insp["inspection_status"] = "FAILED"
            _bump(insp)
            append_event(insp["permit_id"], "INSPECTION_FAILED", "Inspection failed.")
        return ok_object(domain.ser_inspection(insp))


@app.route("/inspections/<iid>/cancel", methods=["POST"])
def cancel_inspection(iid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["Applicant", "PermitClerk"])
        insp = V.lookup("inspections", iid)
        if insp["inspection_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED inspection can be cancelled")
        insp["inspection_status"] = "CANCELLED"
        _bump(insp)
        return ok_object(domain.ser_inspection(insp))


def _cancel_scheduled_inspections(pid):
    for i in db.inspections.values():
        if i["permit_id"] == pid and i["inspection_status"] == "SCHEDULED":
            i["inspection_status"] = "CANCELLED"
            _bump(i)


# =====================================================================
# Stop-work orders
# =====================================================================
@app.route("/permits/<pid>/stop-work-orders", methods=["POST"])
def create_swo(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        permit = V.lookup("permits", pid)
        body = V.get_json_body()
        reason = V.require_str(body, "reason")
        # priority 6: permit ISSUED and work_status ACTIVE
        if permit["status"] != "ISSUED" or permit["work_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Stop-work requires ISSUED + ACTIVE work")

        rec = {
            "id": new_id(),
            "permit_id": pid,
            "reason": reason,
            "order_status": "ACTIVE",
        }
        _stamp_new(rec)
        db.stop_work_orders[rec["id"]] = rec
        permit["work_status"] = "STOPPED"
        # cascade: cancel SCHEDULED inspections (free capacity)
        _cancel_scheduled_inspections(pid)
        # cascade: revoke any ISSUED CofO
        for c in db.certificates.values():
            if c["permit_id"] == pid and c["co_status"] == "ISSUED":
                c["co_status"] = "REVOKED"
                _bump(c)
                append_event(pid, "CO_REVOKED", "Certificate revoked by stop-work.")
        _bump(permit)
        append_event(pid, "STOP_WORK_ISSUED", "Stop-work order issued.")
        return ok_object(domain.ser_swo(rec), 201)


@app.route("/stop-work-orders/<sid>", methods=["GET"])
def get_swo(sid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant"])
        rec = V.lookup("stop_work_orders", sid)
        return ok_object(domain.ser_swo(rec))


@app.route("/stop-work-orders", methods=["GET"])
def list_swo():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant"])
        limit, offset = V.get_pagination()
        permit_id = request.args.get("permit_id")
        rows = list(db.stop_work_orders.values())
        if permit_id is not None:
            rows = [r for r in rows if r["permit_id"] == permit_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_swo(r) for r in page], limit, offset, total)


@app.route("/stop-work-orders/<sid>/lift", methods=["POST"])
def lift_swo(sid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        rec = V.lookup("stop_work_orders", sid)
        if rec["order_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE order can be lifted")
        rec["order_status"] = "LIFTED"
        _bump(rec)
        permit = db.permits.get(rec["permit_id"])
        # restore work_status if no other ACTIVE SWO remains
        if permit is not None:
            others_active = any(
                s["permit_id"] == rec["permit_id"] and s["order_status"] == "ACTIVE" and s["id"] != sid
                for s in db.stop_work_orders.values()
            )
            if not others_active:
                permit["work_status"] = "ACTIVE"
                _bump(permit)
        append_event(rec["permit_id"], "STOP_WORK_LIFTED", "Stop-work order lifted.")
        return ok_object(domain.ser_swo(rec))


# =====================================================================
# Certificates of occupancy
# =====================================================================
@app.route("/certificates/<cid>", methods=["GET"])
def get_certificate(cid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant"])
        rec = V.lookup("certificates", cid)
        return ok_object(domain.ser_certificate(rec))


@app.route("/certificates", methods=["GET"])
def list_certificates():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant"])
        limit, offset = V.get_pagination()
        permit_id = request.args.get("permit_id")
        final_inspection_id = request.args.get("final_inspection_id")
        rows = list(db.certificates.values())
        if permit_id is not None:
            rows = [r for r in rows if r["permit_id"] == permit_id]
        if final_inspection_id is not None:
            rows = [r for r in rows if r["final_inspection_id"] == final_inspection_id]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_certificate(r) for r in page], limit, offset, total)


@app.route("/certificates/<cid>/revoke", methods=["POST"])
def revoke_certificate(cid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        rec = V.lookup("certificates", cid)
        if rec["co_status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Only an ISSUED certificate can be revoked")
        rec["co_status"] = "REVOKED"
        _bump(rec)
        append_event(rec["permit_id"], "CO_REVOKED", "Certificate revoked.")
        return ok_object(domain.ser_certificate(rec))


# =====================================================================
# Permit events
# =====================================================================
@app.route("/permits/<pid>/events", methods=["GET"])
def list_events(pid):
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial", "PermitClerk", "Applicant", "PlanReviewer", "Inspector"])
        V.lookup("permits", pid)
        limit, offset = V.get_pagination()
        rows = [e for e in db.permit_events.values() if e["permit_id"] == pid]
        rows = V.sort_by_creation(rows)
        page, total = V.paginate(rows, limit, offset)
        return ok_array([domain.ser_permit_event(r) for r in page], limit, offset, total)


# =====================================================================
# Test-driving clock
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        body = V.get_json_body()
        to_iso = V.require_datetime(body, "to_iso8601")
        db.clock.set_to(parse_ts(to_iso))
        return ok_object({})


@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    with lock:
        _uid, role = V.authenticate()
        V.authorize(role, ["BuildingOfficial"])
        body = V.get_json_body()
        days = body.get("days", None)
        if not isinstance(days, (int, float)) or isinstance(days, bool):
            raise ApiError("ERR_INVALID_REQUEST", "days must be a number")
        db.clock.advance_days(days)
        return ok_object({})


# =====================================================================
# Main
# =====================================================================
def _run():
    import socket
    import time

    port = int(os.environ.get("PORT", "10000"))
    # Defensive bind: the just-killed previous server may briefly still hold
    # the port. Retry a short loop rather than crashing.
    deadline = time.time() + 30
    last_err = None
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.close()
            break
        except OSError as exc:
            last_err = exc
            s.close()
            time.sleep(0.25)
    else:
        raise SystemExit("Port %d not bindable: %s" % (port, last_err))

    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    _run()
