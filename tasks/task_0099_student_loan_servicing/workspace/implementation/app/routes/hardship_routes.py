"""Hardship request routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..clock import days_between, now_dt, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..services import loans as loan_svc
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


VALID_KINDS = {
    "DEFERMENT_IN_SCHOOL",
    "DEFERMENT_UNEMPLOYMENT",
    "DEFERMENT_ECONOMIC_HARDSHIP",
    "DEFERMENT_MILITARY",
    "FORBEARANCE_GENERAL",
    "FORBEARANCE_MANDATORY",
}


def _validate_loans(borrower_id: str, ids: list[str]) -> list[dict]:
    if not isinstance(ids, list) or not ids:
        raise ApiError("ERR_INVALID_INPUT", "applied_loan_ids required.")
    store = get_store()
    out = []
    for lid in ids:
        loan = store.loans.get(lid)
        if not loan or loan.get("borrower_id") != borrower_id:
            raise ApiError("ERR_LOAN_NOT_FOUND", f"Loan {lid} not found.")
        out.append(loan)
    return out


def _cumulative_forbearance_days(borrower_id: str) -> int:
    total = 0
    for r in get_store().hardship_requests.values():
        if (
            r.get("borrower_id") == borrower_id
            and r.get("kind") == "FORBEARANCE_GENERAL"
            and r.get("status") == "APPROVED"
        ):
            try:
                rf = parse_iso(r["requested_from"])
                rt = parse_iso(r["requested_to"])
            except Exception:
                continue
            total += max(0, days_between(rt, rf))
    return total


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/hardship-requests", methods=["POST"])
    @require_auth("Borrower", "ServicerAdmin")
    def create_hardship(borrower_id):
        b = get_borrower_or_404(borrower_id)
        body = get_json_body(allow_empty=False)
        kind = body.get("kind")
        if kind not in VALID_KINDS:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid kind: {kind}")
        rf = body.get("requested_from")
        rt = body.get("requested_to")
        if not rf or not rt:
            raise ApiError("ERR_INVALID_INPUT", "requested_from and requested_to required.")
        try:
            rf_dt = parse_iso(rf)
            rt_dt = parse_iso(rt)
        except Exception:
            raise ApiError("ERR_BAD_DATE_WINDOW", "Invalid date format.")
        if rt_dt <= rf_dt:
            raise ApiError("ERR_BAD_DATE_WINDOW", "requested_to must be after requested_from.")
        if rf_dt < now_dt():
            raise ApiError("ERR_BAD_DATE_WINDOW", "requested_from must not be in the past.")
        ids = body.get("applied_loan_ids") or []
        _validate_loans(borrower_id, ids)
        req = {
            **common_fields_create(),
            "borrower_id": borrower_id,
            "kind": kind,
            "requested_from": rf,
            "requested_to": rt,
            "applied_loan_ids": list(ids),
            "cumulative_forbearance_days_at_request": _cumulative_forbearance_days(borrower_id),
            "status": "SUBMITTED",
            "rejection_reason": None,
            "reviewed_by": None,
        }
        get_store().hardship_requests[req["id"]] = req
        return created(req)

    @app.route("/borrowers/<borrower_id>/hardship-requests", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "ServicerCertifier")
    def list_hardship(borrower_id):
        get_borrower_or_404(borrower_id)
        limit, offset = parse_limit_offset()
        status = parse_optional_str("status")
        kind = parse_optional_str("kind")
        items = [
            r for r in get_store().hardship_requests.values()
            if r.get("borrower_id") == borrower_id
        ]
        if status:
            items = [r for r in items if r["status"] == status]
        if kind:
            items = [r for r in items if r["kind"] == kind]
        items.sort(key=lambda r: r["created_at"])
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(items),
            "has_more": offset + limit < len(items),
        }
        return list_ok(items[offset : offset + limit], page)

    @app.route("/borrowers/<borrower_id>/hardship-requests/<request_id>", methods=["PATCH"])
    @require_auth("ServicerCertifier")
    def patch_hardship(borrower_id, request_id):
        b = get_borrower_or_404(borrower_id)
        req = get_store().hardship_requests.get(request_id)
        if not req or req.get("borrower_id") != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"HardshipRequest {request_id} not found.")
        body = get_json_body(allow_empty=False)
        check_version_or_conflict(req, body)
        if req["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "HardshipRequest is not in SUBMITTED.")
        target = body.get("status")
        if target not in ("APPROVED", "REJECTED"):
            raise ApiError("ERR_INVALID_INPUT", f"Invalid target status: {target}")
        user_id, _ = current_actor()
        if target == "REJECTED":
            req["status"] = "REJECTED"
            req["rejection_reason"] = body.get("rejection_reason") or ""
            req["reviewed_by"] = user_id
            bump_version(req)
            return ok(req)

        # APPROVED: check preconditions
        loans = [get_store().loans[l] for l in req["applied_loan_ids"] if l in get_store().loans]
        # No DEFAULT
        for l in loans:
            if l["status"] == "DEFAULT":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    f"Loan {l['id']} is in DEFAULT; cannot apply hardship.",
                )
        # DEFERMENT_IN_SCHOOL + DIRECT_PLUS -> ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL
        if req["kind"] == "DEFERMENT_IN_SCHOOL":
            for l in loans:
                if l["loan_type"] == "DIRECT_PLUS":
                    raise ApiError(
                        "ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL",
                        "DEFERMENT_IN_SCHOOL not allowed on DIRECT_PLUS.",
                    )
        # FORBEARANCE_GENERAL cumulative cap 1095 days
        if req["kind"] == "FORBEARANCE_GENERAL":
            try:
                rf_dt = parse_iso(req["requested_from"])
                rt_dt = parse_iso(req["requested_to"])
            except Exception:
                raise ApiError("ERR_BAD_DATE_WINDOW", "Invalid stored window.")
            window_days = max(0, days_between(rt_dt, rf_dt))
            existing = _cumulative_forbearance_days(borrower_id)
            if existing + window_days > 1095:
                raise ApiError(
                    "ERR_FORBEARANCE_CAP_EXCEEDED",
                    "Lifetime FORBEARANCE_GENERAL cap exceeded.",
                )

        # Apply transitions to each loan
        is_deferment = req["kind"].startswith("DEFERMENT_")
        target_status = "DEFERMENT" if is_deferment else "FORBEARANCE"
        for l in loans:
            current = l["status"]
            if current == "REPAYMENT":
                loan_svc.set_status(l, target_status)
            elif current == "DELINQUENT" and not is_deferment:
                l["days_past_due"] = 0
                loan_svc.set_status(l, "FORBEARANCE")
            elif current == "GRACE" and is_deferment:
                # in-school deferment from grace -> deferment
                loan_svc.set_status(l, "DEFERMENT")
            # else leave loan alone (no transition); approval still proceeds

        req["status"] = "APPROVED"
        req["reviewed_by"] = user_id
        bump_version(req)
        recompute_aggregates(b)
        return ok(req)

    @app.route("/borrowers/<borrower_id>/hardship-requests/<request_id>", methods=["DELETE"])
    @require_auth("Borrower")
    def cancel_hardship(borrower_id, request_id):
        get_borrower_or_404(borrower_id)
        req = get_store().hardship_requests.get(request_id)
        if not req or req.get("borrower_id") != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"HardshipRequest {request_id} not found.")
        if req["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only SUBMITTED requests can be cancelled.")
        req["status"] = "CANCELLED"
        bump_version(req)
        return ok(req)
