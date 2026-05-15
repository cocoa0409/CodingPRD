"""Installment plan routes."""
from __future__ import annotations

from flask import Flask

from ..audit import emit_sync_event, write_audit, write_payment_event
from ..auth import current_actor, require_auth
from ..calculations import MIN_CREDIT_SCORE, TERM_APR_TABLE, compute_installment_schedule
from ..clock import now_dt
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.validation import require_keys, require_str
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


def register(app: Flask) -> None:
    # --- POST /aesthetics/installments ---
    @app.route("/aesthetics/installments", methods=["POST"])
    @require_auth("FinanceOfficer", "Consultant")
    def create_installment():
        body = get_json_body()
        require_keys(body, ["treatment_plan_id", "downpayment_cents", "term_months", "finance_partner_id"])
        with LOCK:
            plan = get_store().treatment_plans.get(body["treatment_plan_id"])
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "plan must be APPROVED")
            term = body["term_months"]
            if not isinstance(term, int) or isinstance(term, bool) or term not in TERM_APR_TABLE:
                raise ApiError("ERR_INVALID_INSTALLMENT_TERM", "term_months invalid")
            dp = body["downpayment_cents"]
            if not isinstance(dp, int) or isinstance(dp, bool) or dp < 0:
                raise ApiError("ERR_DOWNPAYMENT_OUT_OF_RANGE", "downpayment_cents out of range")
            final_total = plan.get("final_total_cents") or 0
            if dp > final_total:
                raise ApiError("ERR_DOWNPAYMENT_OUT_OF_RANGE", "downpayment > final_total")
            if plan["id"] in get_store().installment_by_plan:
                raise ApiError("ERR_INSTALLMENT_ALREADY_EXISTS", "installment plan already exists")
            inst = common_fields_create()
            inst.update({
                "treatment_plan_id": plan["id"],
                "principal_cents": final_total - dp,
                "downpayment_cents": dp,
                "term_months": term,
                "apr_bps": None,
                "finance_partner_id": require_str(body["finance_partner_id"], "finance_partner_id"),
                "schedule": [],
                "paid_amount_cents": 0,
                "status": "PENDING_KYC",
                "default_strike_count": 0,
            })
            get_store().installment_plans[inst["id"]] = inst
            get_store().installment_by_plan[plan["id"]] = inst["id"]
        return created(inst)

    # --- POST /aesthetics/installments/{id}/activate ---
    @app.route("/aesthetics/installments/<iid>/activate", methods=["POST"])
    @require_auth("FinanceOfficer")
    def activate(iid: str):
        with LOCK:
            inst = get_store().installment_plans.get(iid)
            if not inst:
                raise ApiError("ERR_NOT_FOUND", "Installment plan not found")
            if inst["status"] != "PENDING_KYC":
                raise ApiError("ERR_INVALID_STATE", "must be PENDING_KYC")
            plan = get_store().treatment_plans.get(inst["treatment_plan_id"])
            if not plan or plan["status"] != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "plan must be APPROVED")
            cust = get_store().customers.get(plan["customer_id"])
            if not cust:
                raise ApiError("ERR_NOT_FOUND", "Customer not found")
            if cust["kyc_status"] != "VERIFIED":
                raise ApiError("ERR_KYC_OR_CREDIT_FAIL", "KYC not verified")
            min_credit = MIN_CREDIT_SCORE[inst["term_months"]]
            if cust["credit_score"] is None or int(cust["credit_score"]) < min_credit:
                raise ApiError("ERR_KYC_OR_CREDIT_FAIL", "credit below threshold")
            apr_bps, schedule = compute_installment_schedule(inst["principal_cents"], inst["term_months"], now_dt())
            inst["apr_bps"] = apr_bps
            inst["schedule"] = schedule
            inst["status"] = "ACTIVE"
            bump_version(inst)
            emit_sync_event("FINANCE_PARTNER", "PLAN_ACTIVATED", {"installment_plan_id": iid})
            write_audit("INSTALLMENT_ACTIVATED", "InstallmentPlan", iid)
        return ok(inst)

    # --- POST /aesthetics/installments/{id}/payments ---
    @app.route("/aesthetics/installments/<iid>/payments", methods=["POST"])
    @require_auth("Customer", "FinanceOfficer")
    def payment(iid: str):
        body = get_json_body()
        require_keys(body, ["amount_cents", "external_ref"])
        user_id, role = current_actor()
        with LOCK:
            inst = get_store().installment_plans.get(iid)
            if not inst:
                raise ApiError("ERR_NOT_FOUND", "Installment plan not found")
            if inst["status"] not in ("ACTIVE", "IN_DEFAULT"):
                raise ApiError("ERR_INVALID_STATE", f"cannot pay in {inst['status']}")
            plan = get_store().treatment_plans.get(inst["treatment_plan_id"])
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if role == "Customer" and plan["customer_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Customer can only pay own plan")
            amt = body["amount_cents"]
            if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
                raise ApiError("ERR_PAYMENT_AMOUNT_INVALID", "amount must be > 0")
            # Remaining unpaid balance
            remaining = sum(int(e["total_cents"]) for e in inst["schedule"] if e["status"] != "PAID")
            if amt > remaining:
                raise ApiError("ERR_PAYMENT_AMOUNT_INVALID", "exceeds remaining balance")
            # Mark schedule entries in order
            spent = amt
            overdue_pending: list[int] = []
            if inst["status"] == "IN_DEFAULT":
                now = now_dt()
                from ..clock import parse_iso
                for e in inst["schedule"]:
                    if e["status"] == "PENDING":
                        due = parse_iso(e["due_date"])
                        from datetime import timedelta
                        if now > due + timedelta(days=7):
                            overdue_pending.append(e["index"])
            for e in inst["schedule"]:
                if e["status"] == "PAID":
                    continue
                if spent >= int(e["total_cents"]):
                    spent -= int(e["total_cents"])
                    e["status"] = "PAID"
                else:
                    break
            inst["paid_amount_cents"] = sum(int(e["total_cents"]) for e in inst["schedule"] if e["status"] == "PAID")
            # Check if recovered from IN_DEFAULT
            if inst["status"] == "IN_DEFAULT":
                if all(inst["schedule"][i - 1]["status"] == "PAID" for i in overdue_pending):
                    inst["status"] = "ACTIVE"
            # Check if fully paid
            if all(e["status"] == "PAID" for e in inst["schedule"]):
                inst["status"] = "COMPLETED"
                emit_sync_event("FINANCE_PARTNER", "PLAN_SETTLED", {"installment_plan_id": iid})
            bump_version(inst)
            write_payment_event(iid, "INSTALLMENT_PAID", amt, body.get("external_ref"))
            emit_sync_event("PAYMENT", "INSTALLMENT_PAID", {"installment_plan_id": iid, "amount_cents": amt})
        return ok(inst)

    # --- POST /aesthetics/installments/{id}/refund-medical-event ---
    @app.route("/aesthetics/installments/<iid>/refund-medical-event", methods=["POST"])
    @require_auth("FinanceOfficer")
    def refund_medical_event(iid: str):
        body = get_json_body()
        require_keys(body, ["adverse_event_id"])
        with LOCK:
            inst = get_store().installment_plans.get(iid)
            if not inst:
                raise ApiError("ERR_NOT_FOUND", "Installment plan not found")
            if inst["status"] != "ACTIVE":
                raise ApiError("ERR_INVALID_STATE", "must be ACTIVE")
            ae = get_store().adverse_events.get(body["adverse_event_id"])
            if not ae:
                raise ApiError("ERR_NOT_FOUND", "AdverseEvent not found")
            if ae["severity"] != "SEVERE":
                raise ApiError("ERR_INVALID_STATE", "Refund requires SEVERE AE")
            inst["status"] = "REFUNDED"
            for e in inst["schedule"]:
                if e["status"] == "PENDING":
                    e["status"] = "CANCELLED"
            bump_version(inst)
            write_payment_event(iid, "REFUND", int(inst["paid_amount_cents"]))
            emit_sync_event("FINANCE_PARTNER", "REFUND_INITIATED", {"installment_plan_id": iid})
            write_audit("INSTALLMENT_REFUNDED", "InstallmentPlan", iid)
        return ok(inst)

    # --- GET /aesthetics/installments/{id} ---
    @app.route("/aesthetics/installments/<iid>", methods=["GET"])
    @require_auth("FinanceOfficer", "Customer", "Consultant")
    def fetch_installment(iid: str):
        inst = get_store().installment_plans.get(iid)
        if not inst:
            raise ApiError("ERR_NOT_FOUND", "Installment plan not found")
        user_id, role = current_actor()
        if role == "Customer":
            plan = get_store().treatment_plans.get(inst["treatment_plan_id"])
            if not plan or plan["customer_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Customer can only access own installments")
        return ok(inst)

    # --- GET /aesthetics/installments ---
    @app.route("/aesthetics/installments", methods=["GET"])
    @require_auth("FinanceOfficer", "Consultant")
    def list_installments():
        limit, offset = parse_limit_offset()
        tpid = parse_optional_str("treatment_plan_id")
        st = parse_optional_str("status")
        items = list(get_store().installment_plans.values())
        if tpid:
            items = [i for i in items if i["treatment_plan_id"] == tpid]
        if st:
            items = [i for i in items if i["status"] == st]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
