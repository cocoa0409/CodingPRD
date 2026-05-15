"""Discharge application routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..clock import now_iso_ms
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..services import loans as loan_svc
from ..services import payments as payment_svc
from ..services.borrowers import recompute_aggregates
from ..store import bump_version, common_fields_create, get_store
from ._helpers import (
    check_version_or_conflict,
    created,
    get_borrower_or_404,
    get_json_body,
    list_ok,
    ok,
)


VALID_PROGRAMS = {"PSLF", "VETERAN_TPD"}


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/discharge-applications", methods=["POST"])
    @require_auth("Borrower", "ServicerAdmin")
    def create_discharge(borrower_id):
        get_borrower_or_404(borrower_id)
        body = get_json_body(allow_empty=False)
        program = body.get("program")
        if program not in VALID_PROGRAMS:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid program: {program}")
        app_doc = {
            **common_fields_create(),
            "borrower_id": borrower_id,
            "program": program,
            "status": "SUBMITTED",
            "approved_loan_ids": [],
            "discharged_principal_cents": 0,
            "discharged_interest_cents": 0,
            "reviewed_by": None,
        }
        get_store().discharge_applications[app_doc["id"]] = app_doc
        return created(app_doc)

    @app.route("/borrowers/<borrower_id>/discharge-applications", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "ServicerCertifier", "ServicerApprover")
    def list_discharge(borrower_id):
        get_borrower_or_404(borrower_id)
        limit, offset = parse_limit_offset()
        status = parse_optional_str("status")
        program = parse_optional_str("program")
        items = [
            a for a in get_store().discharge_applications.values()
            if a.get("borrower_id") == borrower_id
        ]
        if status:
            items = [a for a in items if a["status"] == status]
        if program:
            items = [a for a in items if a["program"] == program]
        items.sort(key=lambda a: a["created_at"])
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(items),
            "has_more": offset + limit < len(items),
        }
        return list_ok(items[offset : offset + limit], page)

    @app.route("/borrowers/<borrower_id>/discharge-applications/<application_id>", methods=["PATCH"])
    @require_auth("ServicerCertifier", "ServicerApprover")
    def patch_discharge(borrower_id, application_id):
        b = get_borrower_or_404(borrower_id)
        app_doc = get_store().discharge_applications.get(application_id)
        if not app_doc or app_doc["borrower_id"] != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Application {application_id} not found.")
        body = get_json_body(allow_empty=False)
        check_version_or_conflict(app_doc, body)
        target = body.get("status")
        user_id, role = current_actor()
        cur = app_doc["status"]

        # Per PRD §3.9: SUBMITTED is the Certifier's state ("From SUBMITTED, a
        # ServicerCertifier may move the application to UNDER_REVIEW or
        # directly reject it"); UNDER_REVIEW is the Approver's state ("from
        # UNDER_REVIEW, a ServicerApprover is the only role permitted to
        # approve or reject"); APPROVED and REJECTED are terminal — no role
        # is permitted to transition the application further.
        #
        # Per PRD §2.8, role-permission (ERR_FORBIDDEN) is checked BEFORE
        # state-machine eligibility (ERR_INVALID_STATE). When the current
        # state has a defined permitted role and the caller's role differs
        # from it, the failure is FORBIDDEN. When the current state is
        # terminal — and therefore has no permitted role at all — the
        # failure is a state-machine error (INVALID_STATE), because no
        # role authorization for this transition is defined to compare
        # against.
        _STATE_PERMITTED_ROLE = {
            "SUBMITTED": "ServicerCertifier",
            "UNDER_REVIEW": "ServicerApprover",
        }
        permitted = _STATE_PERMITTED_ROLE.get(cur)
        if permitted is None:
            # Terminal state (APPROVED, REJECTED) — no role permitted.
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Application in {cur}; no further transitions permitted.",
            )
        if role != permitted:
            raise ApiError(
                "ERR_FORBIDDEN",
                f"Only {permitted} may transition from {cur}.",
            )
        # ServicerCertifier transitions: SUBMITTED -> UNDER_REVIEW or REJECTED
        if role == "ServicerCertifier":
            if cur != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "Only SUBMITTED can be transitioned by certifier.")
            if target == "UNDER_REVIEW":
                if app_doc["program"] == "PSLF":
                    # require at least one APPROVED EmploymentCertification
                    approved = [
                        c for c in get_store().employment_certifications.values()
                        if c.get("borrower_id") == borrower_id and c.get("status") == "APPROVED"
                    ]
                    if not approved:
                        raise ApiError(
                            "ERR_PSLF_NO_EMPLOYMENT_EVIDENCE",
                            "PSLF requires at least one APPROVED employment certification.",
                        )
                app_doc["status"] = "UNDER_REVIEW"
                app_doc["reviewed_by"] = user_id
                bump_version(app_doc)
                return ok(app_doc)
            if target == "REJECTED":
                app_doc["status"] = "REJECTED"
                app_doc["reviewed_by"] = user_id
                bump_version(app_doc)
                return ok(app_doc)
            raise ApiError("ERR_FORBIDDEN", "Certifier may only set UNDER_REVIEW or REJECTED from SUBMITTED.")

        # ServicerApprover transitions: UNDER_REVIEW -> APPROVED or REJECTED
        if role == "ServicerApprover":
            if cur != "UNDER_REVIEW":
                raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW can be approved/rejected.")
            if target == "REJECTED":
                app_doc["status"] = "REJECTED"
                app_doc["reviewed_by"] = user_id
                bump_version(app_doc)
                return ok(app_doc)
            if target != "APPROVED":
                raise ApiError("ERR_FORBIDDEN", "Approver may only APPROVE or REJECT from UNDER_REVIEW.")
            # APPROVED logic
            approved_loan_ids = body.get("approved_loan_ids") or []
            if not isinstance(approved_loan_ids, list) or not approved_loan_ids:
                raise ApiError("ERR_INVALID_INPUT", "approved_loan_ids must be a non-empty list.")
            # Validate loans
            loans = []
            for lid in approved_loan_ids:
                loan = get_store().loans.get(lid)
                if not loan or loan.get("borrower_id") != borrower_id:
                    raise ApiError("ERR_LOAN_NOT_FOUND", f"Loan {lid} not found.")
                loans.append(loan)
            # State precondition: REPAYMENT, DELINQUENT, FORBEARANCE
            for l in loans:
                if l["status"] not in ("REPAYMENT", "DELINQUENT", "FORBEARANCE"):
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        f"Loan {l['id']} is in {l['status']}; cannot be discharged.",
                    )
            # Segregation of duties for PSLF (only relevant if PSLF? PRD §2.9
            # says: approver must not equal certifier on any APPROVED
            # EmploymentCertification for this borrower. Applies generically.)
            cert_reviewers = {
                c.get("reviewed_by")
                for c in get_store().employment_certifications.values()
                if c.get("borrower_id") == borrower_id and c.get("status") == "APPROVED"
            }
            if user_id in cert_reviewers:
                raise ApiError(
                    "ERR_SOD_VIOLATION",
                    "Approver may not also have certified the supporting evidence.",
                )
            # VETERAN_TPD vs PSLF eligibility checks
            if app_doc["program"] == "VETERAN_TPD":
                if b.get("veteran_status") != "TPD_VETERAN":
                    raise ApiError("ERR_VETERAN_INELIGIBLE", "Borrower is not TPD_VETERAN.")
            else:  # PSLF
                # Recount qualifying counts first
                payment_svc.recount_pslf_for_borrower(borrower_id)
                for l in loans:
                    if int(l.get("qualifying_pslf_payment_count", 0)) < 120:
                        raise ApiError(
                            "ERR_PSLF_INSUFFICIENT_PAYMENTS",
                            f"Loan {l['id']} has insufficient PSLF qualifying payments.",
                        )
            # Apply discharge
            discharged_principal = sum(int(l["principal_balance_cents"]) for l in loans)
            discharged_interest = sum(int(l["accrued_interest_cents"]) for l in loans)
            for l in loans:
                l["principal_balance_cents"] = 0
                l["accrued_interest_cents"] = 0
                loan_svc.set_status(l, "DISCHARGED")
            app_doc["status"] = "APPROVED"
            app_doc["approved_loan_ids"] = list(approved_loan_ids)
            app_doc["discharged_principal_cents"] = discharged_principal
            app_doc["discharged_interest_cents"] = discharged_interest
            app_doc["reviewed_by"] = user_id
            bump_version(app_doc)
            recompute_aggregates(b)
            return ok(app_doc)

        raise ApiError("ERR_FORBIDDEN", "Role not permitted to PATCH discharge applications.")
