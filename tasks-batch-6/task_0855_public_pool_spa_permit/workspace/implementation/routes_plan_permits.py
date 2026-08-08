"""Plan reviews and permits."""

from flask import g

import constants as C
import domain
from auth import authenticate, authorize, own_or_403, require_action_role
from clock import LOGICAL_CLOCK, add_days
from errors import ApiError
from helpers import facility_or_404, get_or_404, matches, paged_list
from response import object_response
from serializers import permit_json, plan_review_json
from store import DB, base_record, ordered, touch
from validation import (bad, json_body, opt_bool, opt_string, qs, req_date,
                        req_enum, req_int, req_string)

PLAN_REVIEW_ACTIONS = ("START_REVIEW", "REQUEST_CORRECTIONS", "APPROVE", "DISAPPROVE")
PERMIT_ACTIONS = ("SUBMIT", "START_REVIEW", "ISSUE", "DENY", "SUSPEND", "REINSTATE",
                  "REVOKE", "EXPIRE")
PERMIT_ACTION_ROLES = {
    "SUBMIT": ("Operator",),
    "START_REVIEW": ("HealthAuthorityAdmin",),
    "ISSUE": ("HealthAuthorityAdmin",),
    "DENY": ("HealthAuthorityAdmin",),
    "SUSPEND": ("HealthAuthorityAdmin",),
    "REINSTATE": ("HealthAuthorityAdmin",),
    "REVOKE": ("HealthAuthorityAdmin",),
    "EXPIRE": ("HealthAuthorityAdmin",),
}


def _invalid_plan_state():
    raise ApiError("ERR_INVALID_PLAN_REVIEW_STATE",
                   "The plan review is not in a state that permits this action.")


def _invalid_permit_state():
    raise ApiError("ERR_INVALID_PERMIT_STATE",
                   "The permit is not in a state that permits this action.")


def register(app):

    # ------------------------------------------------------------------
    # plan reviews
    # ------------------------------------------------------------------
    def _new_plan_review(facility, project_type, drawing_reference,
                         supersedes_id=None, revision_round=0):
        rec = base_record()
        rec.update({
            "facility_id": facility["id"],
            "supersedes_plan_review_id": supersedes_id,
            "project_type": project_type,
            "drawing_reference": drawing_reference,
            "revision_round": revision_round,
            "status": "SUBMITTED",
            "submitted_on": LOGICAL_CLOCK.today(),
            "reviewer_user_id": None,
            "decided_at": None,
            "decided_by_user_id": None,
            "correction_notes": None,
        })
        DB.plan_reviews[rec["id"]] = rec
        domain.post_ledger_entry(facility["operator_id"], "PLAN_REVIEW_FEE",
                                 C.PLAN_REVIEW_FEE_CENTS, permit_id=None)
        return rec

    @app.route("/plan-reviews", methods=["POST"])
    def create_plan_review():
        authenticate()
        authorize("Operator")
        body = json_body()
        facility_id = req_string(body, "facility_id")
        project_type = req_enum(body, "project_type", C.PROJECT_TYPES)
        drawing_reference = opt_string(body, "drawing_reference")
        facility = facility_or_404(facility_id)
        own_or_403(facility["operator_id"])
        rec = _new_plan_review(facility, project_type, drawing_reference)
        return object_response(plan_review_json(rec), 201)

    @app.route("/plan-reviews/<review_id>/revisions", methods=["POST"])
    def create_plan_revision(review_id):
        authenticate()
        authorize("Operator")
        review = get_or_404(DB.plan_reviews, review_id, "ERR_PLAN_REVIEW_NOT_FOUND")
        body = json_body()
        expected_version = req_int(body, "expected_plan_review_version")
        drawing_reference = opt_string(body, "drawing_reference")
        facility = DB.facilities.get(review["facility_id"])
        own_or_403(facility["operator_id"] if facility else None)

        if expected_version != review["version"]:
            raise ApiError("ERR_STALE_PLAN_REVIEW_VERSION",
                           "The plan review version has moved on.")
        if review["status"] != "CORRECTIONS_REQUIRED":
            _invalid_plan_state()
        if review["revision_round"] + 1 > C.PLAN_REVIEW_MAX_REVISION_ROUNDS:
            raise ApiError("ERR_PLAN_REVIEW_ROUNDS_EXHAUSTED",
                           "The plan review has exhausted its correction rounds.")

        review["status"] = "SUPERSEDED"
        touch(review)
        rec = _new_plan_review(facility, review["project_type"], drawing_reference,
                               supersedes_id=review["id"],
                               revision_round=review["revision_round"] + 1)
        return object_response(plan_review_json(rec), 201)

    @app.route("/plan-reviews/<review_id>", methods=["GET"])
    def read_plan_review(review_id):
        authenticate()
        authorize("Operator", "PlanReviewer", "HealthAuthorityAdmin")
        rec = get_or_404(DB.plan_reviews, review_id, "ERR_PLAN_REVIEW_NOT_FOUND")
        return object_response(plan_review_json(rec))

    @app.route("/plan-reviews", methods=["GET"])
    def list_plan_reviews():
        authenticate()
        authorize("Operator", "PlanReviewer", "HealthAuthorityAdmin")
        f_facility = qs("facility_id")
        f_supersedes = qs("supersedes_plan_review_id")
        f_status = qs("status")
        rows = [r for r in DB.plan_reviews.values()
                if matches(r["facility_id"], f_facility)
                and matches(r["supersedes_plan_review_id"], f_supersedes)
                and matches(r["status"], f_status)]
        return paged_list(rows, plan_review_json)

    @app.route("/plan-reviews/<review_id>/transition", methods=["POST"])
    def transition_plan_review(review_id):
        authenticate()
        authorize("PlanReviewer")
        review = get_or_404(DB.plan_reviews, review_id, "ERR_PLAN_REVIEW_NOT_FOUND")
        body = json_body()
        action = req_enum(body, "action", PLAN_REVIEW_ACTIONS)
        correction_notes = opt_string(body, "correction_notes")

        if action == "START_REVIEW":
            if review["status"] != "SUBMITTED":
                _invalid_plan_state()
            review["status"] = "UNDER_REVIEW"
            review["reviewer_user_id"] = g.user_id
        elif action == "REQUEST_CORRECTIONS":
            if review["status"] != "UNDER_REVIEW":
                _invalid_plan_state()
            if review["revision_round"] >= C.PLAN_REVIEW_MAX_REVISION_ROUNDS:
                raise ApiError("ERR_PLAN_REVIEW_ROUNDS_EXHAUSTED",
                               "The plan review has exhausted its correction rounds.")
            review["status"] = "CORRECTIONS_REQUIRED"
            review["correction_notes"] = correction_notes
        elif action == "APPROVE":
            if review["status"] != "UNDER_REVIEW":
                _invalid_plan_state()
            review["status"] = "APPROVED"
            review["decided_at"] = LOGICAL_CLOCK.now()
            review["decided_by_user_id"] = g.user_id
            review["correction_notes"] = None
        else:  # DISAPPROVE
            if review["status"] != "UNDER_REVIEW":
                _invalid_plan_state()
            review["status"] = "DISAPPROVED"
            review["decided_at"] = LOGICAL_CLOCK.now()
            review["decided_by_user_id"] = g.user_id
            for permit in ordered(list(DB.permits.values())):
                if permit["plan_review_id"] != review["id"]:
                    continue
                if permit["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
                    permit["status"] = "DENIED"
                    touch(permit)
        touch(review)
        return object_response(plan_review_json(review))

    # ------------------------------------------------------------------
    # permits
    # ------------------------------------------------------------------
    @app.route("/permits", methods=["POST"])
    def create_permit():
        authenticate()
        authorize("Operator")
        body = json_body()
        facility_id = req_string(body, "facility_id")
        permit_type = req_enum(body, "permit_type", C.PERMIT_TYPES)
        term_start_date = req_date(body, "term_start_date")
        plan_review_id = opt_string(body, "plan_review_id")

        facility = facility_or_404(facility_id)
        review = None
        if plan_review_id is not None:
            review = get_or_404(DB.plan_reviews, plan_review_id,
                                "ERR_PLAN_REVIEW_NOT_FOUND")
            if review["facility_id"] != facility["id"]:
                raise ApiError("ERR_PLAN_REVIEW_FACILITY_MISMATCH",
                               "The plan review belongs to a different facility.")
        own_or_403(facility["operator_id"])

        if permit_type == "SEASONAL":
            if (not facility["is_seasonal"]
                    or facility["season_start_date"] is None
                    or facility["season_end_date"] is None):
                raise ApiError("ERR_SEASON_TERM_TOO_LONG",
                               "A seasonal permit requires a seasonal facility.")
            season_days = (facility["season_end_date"]
                           - facility["season_start_date"]).days + 1
            if season_days > C.SEASONAL_PERMIT_MAX_TERM_DAYS:
                raise ApiError("ERR_SEASON_TERM_TOO_LONG",
                               "The declared season exceeds the seasonal maximum.")
            term_end_date = facility["season_end_date"]
        else:
            term_end_date = add_days(term_start_date, C.ANNUAL_PERMIT_TERM_DAYS - 1)
        term_days = (term_end_date - term_start_date).days + 1

        for other in DB.permits.values():
            if other["facility_id"] != facility["id"]:
                continue
            if other["status"] not in ("SUBMITTED", "UNDER_REVIEW", "ISSUED"):
                continue
            if (term_start_date <= other["term_end_date"]
                    and other["term_start_date"] <= term_end_date):
                raise ApiError("ERR_PERMIT_TERM_OVERLAP",
                               "Another permit already covers part of this term.")

        if term_start_date > add_days(LOGICAL_CLOCK.today(),
                                      C.PERMIT_RENEWAL_WINDOW_DAYS):
            raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN",
                           "The renewal window for this term is not open yet.")

        if facility["requires_plan_review"] and plan_review_id is None:
            raise ApiError("ERR_PLAN_REVIEW_NOT_APPROVED",
                           "This facility requires an approved plan review.")

        applied_on = LOGICAL_CLOCK.today()
        rec = base_record()
        rec.update({
            "facility_id": facility["id"],
            "plan_review_id": plan_review_id,
            "permit_type": permit_type,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
            "term_days": term_days,
            "applied_on": applied_on,
            "is_late_application": applied_on > term_start_date,
            "assessed_fee_cents": 0,
            "fee_variant": None,
            "classification_at_issue": None,
            "status": "DRAFT",
            "issued_at": None,
            "issued_by_user_id": None,
            "suspension_reason": None,
            "refunded": False,
        })
        DB.permits[rec["id"]] = rec
        return object_response(permit_json(rec), 201)

    @app.route("/permits/<permit_id>", methods=["GET"])
    def read_permit(permit_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        rec = get_or_404(DB.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
        return object_response(permit_json(rec))

    @app.route("/permits", methods=["GET"])
    def list_permits():
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        f_facility = qs("facility_id")
        f_review = qs("plan_review_id")
        f_status = qs("status")
        f_type = qs("permit_type")
        rows = [p for p in DB.permits.values()
                if matches(p["facility_id"], f_facility)
                and matches(p["plan_review_id"], f_review)
                and matches(p["status"], f_status)
                and matches(p["permit_type"], f_type)]
        return paged_list(rows, permit_json)

    @app.route("/permits/<permit_id>/transition", methods=["POST"])
    def transition_permit(permit_id):
        authenticate()
        authorize("Operator", "HealthAuthorityAdmin")
        permit = get_or_404(DB.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
        body = json_body()
        action = req_enum(body, "action", PERMIT_ACTIONS)
        opt_string(body, "reason")
        refund_eligible = opt_bool(body, "refund_eligible", default=False)
        require_action_role(action, PERMIT_ACTION_ROLES)

        facility = DB.facilities.get(permit["facility_id"])
        own_or_403(facility["operator_id"] if facility else None)

        if action == "SUBMIT":
            if permit["status"] != "DRAFT":
                _invalid_permit_state()
            permit["status"] = "SUBMITTED"
        elif action == "START_REVIEW":
            if permit["status"] != "SUBMITTED":
                _invalid_permit_state()
            permit["status"] = "UNDER_REVIEW"
        elif action == "DENY":
            if permit["status"] != "UNDER_REVIEW":
                _invalid_permit_state()
            permit["status"] = "DENIED"
        elif action == "ISSUE":
            _issue_permit(permit, facility)
        elif action == "SUSPEND":
            if permit["status"] != "ISSUED":
                _invalid_permit_state()
            permit["status"] = "SUSPENDED"
            permit["suspension_reason"] = "ADMINISTRATIVE"
            domain.bump_facility(facility)
        elif action == "REINSTATE":
            if permit["status"] != "SUSPENDED":
                _invalid_permit_state()
            if domain.has_blocking_closure(facility["id"]):
                _invalid_permit_state()
            if domain.qualifying_open_violations(facility["id"],
                                                 ("IMMINENT_HEALTH_HAZARD",)):
                raise ApiError("ERR_OPEN_CRITICAL_VIOLATIONS",
                               "An open imminent-hazard violation blocks reinstatement.")
            permit["status"] = "ISSUED"
            permit["suspension_reason"] = None
            domain.bump_facility(facility)
        elif action == "REVOKE":
            if permit["status"] not in ("ISSUED", "SUSPENDED"):
                _invalid_permit_state()
            if refund_eligible:
                cutoff = add_days(permit["term_start_date"], C.PERMIT_REFUND_WINDOW_DAYS)
                if permit["refunded"] or LOGICAL_CLOCK.today() > cutoff:
                    raise ApiError("ERR_REFUND_NOT_ELIGIBLE",
                                   "This permit is not eligible for a refund.")
            permit["status"] = "REVOKED"
            if refund_eligible:
                charged = sum(e["amount_cents"] for e in DB.ledger_entries.values()
                              if e["permit_id"] == permit["id"]
                              and e["entry_type"] in ("PERMIT_FEE", "LATE_PENALTY"))
                domain.post_ledger_entry(facility["operator_id"], "REFUND", -charged,
                                         permit_id=permit["id"])
                permit["refunded"] = True
            domain.bump_facility(facility)
        else:  # EXPIRE
            if permit["status"] not in ("ISSUED", "SUSPENDED"):
                _invalid_permit_state()
            if LOGICAL_CLOCK.today() <= permit["term_end_date"]:
                _invalid_permit_state()
            permit["status"] = "EXPIRED"
            domain.bump_facility(facility)

        touch(permit)
        return object_response(permit_json(permit))

    def _issue_permit(permit, facility):
        if permit["status"] != "UNDER_REVIEW":
            _invalid_permit_state()
        review = (DB.plan_reviews.get(permit["plan_review_id"])
                  if permit["plan_review_id"] else None)
        if review is not None and review["decided_by_user_id"] is not None \
                and g.user_id == review["decided_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The issuing officer decided the referenced plan review.")
        if LOGICAL_CLOCK.today() >= domain.VGB_ENFORCEMENT_DATE:
            if domain.vgb_compliance_status(facility) != "COMPLIANT":
                raise ApiError("ERR_VGB_NONCOMPLIANT",
                               "The facility is not VGB drain-safety compliant.")
        if domain.qualifying_open_violations(
                facility["id"], ("CRITICAL", "IMMINENT_HEALTH_HAZARD")):
            raise ApiError("ERR_OPEN_CRITICAL_VIOLATIONS",
                           "The facility carries open critical violations.")
        if facility["requires_plan_review"]:
            if review is None or review["status"] != "APPROVED":
                raise ApiError("ERR_PLAN_REVIEW_NOT_APPROVED",
                               "The referenced plan review is not approved.")
        operator_id = facility["operator_id"]
        if domain.fee_balance_cents(operator_id) != 0:
            raise ApiError("ERR_OUTSTANDING_FEES",
                           "The operator has an outstanding fee balance.")

        fee_variant, subtotal_cents, penalty_cents = domain.assess_permit_fee(
            permit, facility)
        permit["fee_variant"] = fee_variant
        permit["assessed_fee_cents"] = subtotal_cents + penalty_cents
        permit["classification_at_issue"] = facility["facility_class"]
        permit["status"] = "ISSUED"
        permit["issued_at"] = LOGICAL_CLOCK.now()
        permit["issued_by_user_id"] = g.user_id
        domain.post_ledger_entry(operator_id, "PERMIT_FEE", subtotal_cents,
                                 permit_id=permit["id"])
        if permit["is_late_application"]:
            domain.post_ledger_entry(operator_id, "LATE_PENALTY", penalty_cents,
                                     permit_id=permit["id"])
        domain.bump_facility(facility)
