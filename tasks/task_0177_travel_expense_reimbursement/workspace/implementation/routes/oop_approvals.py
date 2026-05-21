"""Out-of-Policy approval chain endpoints."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_role, current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import (
    err_invalid_state,
    err_not_found,
    err_oop_duplicate_approver,
    err_oop_wrong_approver_role,
    err_reference_not_found,
    err_segregation_of_duties,
    err_validation,
)
from core.serializers import serialize_oop_approval
from core.store import store
from core.utils import lock, parse_iso
from services.per_diem_service import resolve_per_diem
from services.timestamps import stamp_create, stamp_update


bp = Blueprint("oop_approvals", __name__)


def _get_traveler_for_approval(app):
    line = store.expense_lines.get(app["expense_line_id"])
    if line is None:
        return None, None, None
    report = store.expense_reports.get(line["report_id"])
    if report is None:
        return line, None, None
    trip = store.trips.get(report["trip_id"])
    return line, report, trip


def _cascade_line_oop_status(line_id: str, new_status: str):
    """Apply policy_status cascade after a chain decision."""
    line = store.expense_lines.get(line_id)
    if line is None:
        return
    if new_status == "OOP_APPROVED":
        prior_reimb = int(line.get("amount_reimbursable_cents") or 0)
        line["policy_status"] = "OOP_APPROVED"
        new_reimb = int(line.get("amount_claimed_cents") or 0)
        line["amount_reimbursable_cents"] = new_reimb
        # Card delta
        delta = new_reimb - prior_reimb
        if line.get("virtual_card_id") and delta != 0:
            card = store.virtual_cards.get(line["virtual_card_id"])
            if card is not None:
                new_auth = int(card.get("authorized_amount_cents") or 0) + delta
                # Cap at credit limit if positive delta would breach? Per the
                # PRD this is a system-driven cascade, so we apply it directly.
                if new_auth < 0:
                    new_auth = 0
                card["authorized_amount_cents"] = new_auth
                stamp_update(card)
        stamp_update(line)
    elif new_status == "OOP_DENIED":
        line["policy_status"] = "OOP_DENIED"
        stamp_update(line)

    # Recompute report rollup
    report = store.expense_reports.get(line["report_id"])
    if report is not None:
        from services.line_service import rollup_report
        rollup_report(report)
        stamp_update(report)


@bp.post("/oop-approvals")
@require_roles("TRAVELER")
def create_oop():
    body = get_json_body()
    line_id = body.get("expense_line_id")
    justification = body.get("justification")

    if not line_id:
        raise err_validation("expense_line_id is required.")
    if not justification or not isinstance(justification, str):
        raise err_validation("justification is required.")
    if not (10 <= len(justification) <= 1000):
        raise err_validation("justification must be 10-1000 chars.")

    line = store.expense_lines.get(line_id)
    if line is None:
        raise err_reference_not_found(f"expense_line_id {line_id} not found.")

    report = store.expense_reports.get(line["report_id"])
    if report is None:
        raise err_reference_not_found("Parent report not found.")
    trip = store.trips.get(report["trip_id"])
    if trip is None:
        raise err_reference_not_found("Parent trip not found.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the traveler may request OOP approval.")

    if line.get("policy_status") != "OUT_OF_POLICY":
        raise err_invalid_state(
            f"Line policy_status is {line.get('policy_status')}, not OUT_OF_POLICY."
        )

    # Compute requires_final_escalation
    high_cost = False
    rate = resolve_per_diem(
        trip["destination_city"],
        trip["destination_state"],
        parse_iso(trip["start_date"]),
    )
    if rate is not None and rate.get("is_high_cost_locality"):
        high_cost = True
    requires_final = (int(line.get("amount_claimed_cents") or 0) > 100000) or high_cost

    with lock():
        rec = {
            "expense_line_id": line_id,
            "requester_employee_id": current_user_id(),
            "justification": justification,
            "chain_level": "AWAITING_L1",
            "l1_approver_id": None,
            "l2_approver_id": None,
            "final_approver_id": None,
            "requires_final_escalation": requires_final,
        }
        stamp_create(rec)
        store.oop_approvals[rec["id"]] = rec
    return success_response(serialize_oop_approval(rec), status=201)


@bp.get("/oop-approvals/<aid>")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "OOP_APPROVER", "ADMIN")
def get_oop(aid):
    app = store.oop_approvals.get(aid)
    if app is None:
        raise err_not_found(f"OutOfPolicyApproval {aid} not found.")
    return success_response(serialize_oop_approval(app))


@bp.post("/oop-approvals/<aid>/l1-approve")
@require_roles("MANAGER")
def l1_approve(aid):
    app = store.oop_approvals.get(aid)
    if app is None:
        raise err_not_found(f"OutOfPolicyApproval {aid} not found.")
    if app["chain_level"] != "AWAITING_L1":
        raise err_invalid_state(f"chain_level is {app['chain_level']}, not AWAITING_L1.")

    line, report, trip = _get_traveler_for_approval(app)
    if trip is None:
        raise err_reference_not_found("Cannot resolve trip for approval.")
    traveler = store.employees.get(trip["traveler_id"])
    if traveler is None:
        raise err_reference_not_found("Traveler not found.")

    if current_user_id() == trip["traveler_id"]:
        raise err_segregation_of_duties("Approver cannot be the traveler.")
    if current_user_id() != traveler.get("manager_id"):
        raise err_oop_wrong_approver_role("Acting manager must be the traveler's manager.")

    with lock():
        app["chain_level"] = "AWAITING_L2"
        app["l1_approver_id"] = current_user_id()
        stamp_update(app)
    return success_response(serialize_oop_approval(app))


@bp.post("/oop-approvals/<aid>/l2-approve")
@require_roles("FINANCE_REVIEWER")
def l2_approve(aid):
    app = store.oop_approvals.get(aid)
    if app is None:
        raise err_not_found(f"OutOfPolicyApproval {aid} not found.")
    if app["chain_level"] != "AWAITING_L2":
        raise err_invalid_state(f"chain_level is {app['chain_level']}, not AWAITING_L2.")

    line, report, trip = _get_traveler_for_approval(app)
    if trip is None:
        raise err_reference_not_found("Cannot resolve trip for approval.")

    if current_user_id() == trip["traveler_id"]:
        raise err_segregation_of_duties("Approver cannot be the traveler.")

    with lock():
        app["l2_approver_id"] = current_user_id()
        if app.get("requires_final_escalation"):
            app["chain_level"] = "AWAITING_FINAL"
        else:
            app["chain_level"] = "FINAL_APPROVED"
            _cascade_line_oop_status(app["expense_line_id"], "OOP_APPROVED")
        stamp_update(app)
    return success_response(serialize_oop_approval(app))


@bp.post("/oop-approvals/<aid>/final-approve")
@require_roles("OOP_APPROVER")
def final_approve(aid):
    app = store.oop_approvals.get(aid)
    if app is None:
        raise err_not_found(f"OutOfPolicyApproval {aid} not found.")
    if app["chain_level"] != "AWAITING_FINAL":
        raise err_invalid_state(f"chain_level is {app['chain_level']}, not AWAITING_FINAL.")

    line, report, trip = _get_traveler_for_approval(app)
    if trip is None:
        raise err_reference_not_found("Cannot resolve trip for approval.")

    if current_user_id() == trip["traveler_id"]:
        raise err_segregation_of_duties("Approver cannot be the traveler.")
    if app.get("l1_approver_id") == current_user_id():
        raise err_oop_duplicate_approver("Final approver must differ from L1 approver.")

    with lock():
        app["final_approver_id"] = current_user_id()
        app["chain_level"] = "FINAL_APPROVED"
        _cascade_line_oop_status(app["expense_line_id"], "OOP_APPROVED")
        stamp_update(app)
    return success_response(serialize_oop_approval(app))


@bp.post("/oop-approvals/<aid>/deny")
@require_roles("MANAGER", "FINANCE_REVIEWER", "OOP_APPROVER")
def deny_oop(aid):
    app = store.oop_approvals.get(aid)
    if app is None:
        raise err_not_found(f"OutOfPolicyApproval {aid} not found.")

    chain = app["chain_level"]
    role = current_role()
    if chain == "AWAITING_L1" and role != "MANAGER":
        raise err_oop_wrong_approver_role(f"Wrong role {role} for AWAITING_L1.")
    if chain == "AWAITING_L2" and role != "FINANCE_REVIEWER":
        raise err_oop_wrong_approver_role(f"Wrong role {role} for AWAITING_L2.")
    if chain == "AWAITING_FINAL" and role != "OOP_APPROVER":
        raise err_oop_wrong_approver_role(f"Wrong role {role} for AWAITING_FINAL.")
    if chain in {"FINAL_APPROVED", "DENIED"}:
        raise err_invalid_state(f"chain_level is {chain}; cannot deny.")

    with lock():
        app["chain_level"] = "DENIED"
        stamp_update(app)
        _cascade_line_oop_status(app["expense_line_id"], "OOP_DENIED")
    return success_response(serialize_oop_approval(app))
