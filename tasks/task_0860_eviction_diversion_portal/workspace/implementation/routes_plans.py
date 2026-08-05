"""PaymentPlan and Installment routes."""

from flask import g, request

import envelope
import services
import store
from common import (authorize, check_case_ownership, get_body, lookup, owns_case,
                    pagination_params, paginate, require_dt, require_enum,
                    require_int, require_str)
from errors import ApiError

PLAN_READ_ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge"}
INSTALLMENT_READ_ROLES = {"Clerk", "Landlord", "Tenant", "Judge"}
PARTY = {"LANDLORD", "TENANT"}
DECISIONS = {"ACCEPT", "COUNTER", "REJECT"}


def _counterparty(party):
    return "TENANT" if party == "LANDLORD" else "LANDLORD"


def _acting_party():
    return "LANDLORD" if g.role == "Landlord" else "TENANT"


def register(app):
    # ---------------------------------------------------------- payment plans
    @app.route("/payment-plans", methods=["POST"])
    def create_plan():
        authorize({"Landlord", "Tenant"})
        body = get_body()
        case_id = require_str(body, "case_id")
        proposed_by = require_enum(body, "proposed_by", PARTY)
        total = require_int(body, "total_cents", minimum=1)
        count = require_int(body, "installment_count", minimum=1)
        first_due = require_dt(body, "first_due_date")
        expected_version = require_int(body, "expected_case_version")
        case = lookup("cases", case_id)
        check_case_ownership(case)
        if expected_version != case["version"]:
            raise ApiError("ERR_STALE_VERSION", "Case version has advanced")
        plan = services.new_entity("payment_plans", versioned=True)
        plan["case_id"] = case_id
        plan["proposed_by"] = proposed_by
        plan["total_cents"] = total
        plan["installment_count"] = count
        plan["first_due_date"] = first_due
        plan["current_proposer"] = _counterparty(proposed_by)
        plan["status"] = "PROPOSED"
        services.touch(case)  # OCC: case.version += 1
        return envelope.created(plan)

    @app.route("/payment-plans/<plan_id>", methods=["GET"])
    def get_plan(plan_id):
        authorize(PLAN_READ_ROLES)
        plan = lookup("payment_plans", plan_id)
        check_case_ownership(store.db["cases"].get(plan["case_id"], {}))
        return envelope.success(plan)

    @app.route("/payment-plans", methods=["GET"])
    def list_plans():
        authorize(PLAN_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for p in store.db["payment_plans"].values():
            case = store.db["cases"].get(p["case_id"])
            if case is not None and not owns_case(case):
                continue
            if args.get("case_id") and p["case_id"] != args.get("case_id"):
                continue
            if args.get("status") and p["status"] != args.get("status"):
                continue
            items.append(p)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/payment-plans/<plan_id>/respond", methods=["POST"])
    def respond_plan(plan_id):
        authorize({"Landlord", "Tenant"})
        plan = lookup("payment_plans", plan_id)
        body = get_body()
        decision = require_enum(body, "decision", DECISIONS)
        case = store.db["cases"].get(plan["case_id"])
        if case is not None:
            check_case_ownership(case)
        if plan["status"] not in {"PROPOSED", "COUNTERED"}:
            raise ApiError("ERR_INVALID_STATE", "Plan is not open for a response")
        if _acting_party() != plan["current_proposer"]:
            raise ApiError("ERR_WRONG_PARTY_TURN", "It is not this party's turn")

        if decision == "COUNTER":
            new_total = require_int(body, "new_total_cents", minimum=1)
            new_count = require_int(body, "new_installment_count", minimum=1)
            plan["total_cents"] = new_total
            plan["installment_count"] = new_count
            plan["current_proposer"] = _counterparty(plan["current_proposer"])
            plan["status"] = "COUNTERED" if plan["status"] == "PROPOSED" else "PROPOSED"
            services.touch(plan)
        elif decision == "REJECT":
            plan["status"] = "REJECTED"
            plan["current_proposer"] = None
            services.touch(plan)
        elif decision == "ACCEPT":
            arrears = services.final_net_arrears(case) if case else 0
            if plan["total_cents"] < arrears:
                raise ApiError("ERR_PLAN_INSUFFICIENT", "Plan total does not cover arrears")
            plan["current_proposer"] = None
            plan["status"] = "ACCEPTED"
            services.touch(plan)
            services.generate_installments(plan)
            if case is not None and case["status"] in {"ANSWERED", "IN_LITIGATION"}:
                case["status"] = "IN_DIVERSION"
                services.touch(case)
        return envelope.success(plan)

    # ----------------------------------------------------------- installments
    @app.route("/installments/<installment_id>", methods=["GET"])
    def get_installment(installment_id):
        authorize(INSTALLMENT_READ_ROLES)
        inst = lookup("installments", installment_id)
        case = services.case_of("installments", inst)
        if case is not None:
            check_case_ownership(case)
        return envelope.success(inst)

    @app.route("/installments", methods=["GET"])
    def list_installments():
        authorize(INSTALLMENT_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for inst in store.db["installments"].values():
            case = services.case_of("installments", inst)
            if case is not None and not owns_case(case):
                continue
            if args.get("payment_plan_id") and inst["payment_plan_id"] != args.get("payment_plan_id"):
                continue
            if args.get("status") and inst["status"] != args.get("status"):
                continue
            items.append(inst)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/installments/<installment_id>/transition", methods=["POST"])
    def transition_installment(installment_id):
        authorize({"Tenant", "Clerk"})
        inst = lookup("installments", installment_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in {"PAID", "MISSED", "DUE"}:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        plan = store.db["payment_plans"].get(inst["payment_plan_id"])
        case = services.case_of("installments", inst)

        if to == "PAID":
            if g.role != "Tenant":
                raise ApiError("ERR_UNAUTHORIZED", "Only the tenant may pay an installment")
            if case is not None:
                check_case_ownership(case)
            if inst["status"] != "DUE":
                raise ApiError("ERR_INVALID_STATE", "Installment not DUE")
            if plan is None or plan["status"] != "ACCEPTED":
                raise ApiError("ERR_INVALID_STATE", "Parent plan is not ACCEPTED")
            inst["status"] = "PAID"
            inst["paid_at"] = store.now()
            services.touch(inst)
            # bubble-up: all installments PAID -> plan COMPLETED -> case satisfied
            siblings = [i for i in store.db["installments"].values()
                        if i["payment_plan_id"] == plan["id"]]
            if all(i["status"] == "PAID" for i in siblings):
                plan["status"] = "COMPLETED"
                services.touch(plan)
                if case is not None and case["status"] == "IN_DIVERSION":
                    services.satisfy_diversion(case)
        elif to == "MISSED":
            if g.role != "Clerk":
                raise ApiError("ERR_UNAUTHORIZED", "Only a clerk may mark an installment missed")
            if inst["status"] != "DUE":
                raise ApiError("ERR_INVALID_STATE", "Installment not DUE")
            if plan is None or plan["status"] != "ACCEPTED":
                raise ApiError("ERR_INVALID_STATE", "Parent plan is not ACCEPTED")
            if store.now() <= inst["due_date"]:
                raise ApiError("ERR_INSTALLMENT_NOT_DUE", "Installment due date has not passed")
            inst["status"] = "MISSED"
            services.touch(inst)
            plan["status"] = "DEFAULTED"
            services.touch(plan)
            if case is not None and case["status"] == "IN_DIVERSION":
                case["status"] = "IN_LITIGATION"
                services.touch(case)
        else:
            raise ApiError("ERR_INVALID_STATE", "Illegal installment transition to %s" % to)
        return envelope.success(inst)
