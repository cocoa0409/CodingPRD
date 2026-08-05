"""Judgment, LockoutOrder and SealingRequest routes."""

from flask import g, request

import envelope
import services
import store
from common import (authorize, check_case_ownership, get_body, lookup, owns_case,
                    pagination_params, paginate, require_dt, require_enum,
                    require_str)
from errors import ApiError

JUDGMENT_READ_ROLES = {"Clerk", "Landlord", "Tenant", "Judge", "Sheriff"}
LOCKOUT_READ_ROLES = {"Clerk", "Landlord", "Tenant", "Judge", "Sheriff"}
SEALING_READ_ROLES = {"Clerk", "Tenant", "Judge"}

JUDGMENT_TYPES = {"POSSESSION", "DISMISSAL", "DIVERSION"}
JUDGMENT_STATUSES = {"ENTERED", "STAYED", "VACATED", "SATISFIED"}
LOCKOUT_STATUSES = {"REQUESTED", "SCHEDULED", "EXECUTED", "CANCELLED"}
SEALING_BASES = {"DISMISSAL", "DIVERSION", "TIME_ELAPSED"}
SEALING_STATUSES = {"REQUESTED", "GRANTED", "DENIED"}


def register(app):
    # --------------------------------------------------------------- judgments
    @app.route("/judgments", methods=["POST"])
    def create_judgment():
        authorize({"Judge"})
        body = get_body()
        case_id = require_str(body, "case_id")
        judgment_type = require_enum(body, "judgment_type", JUDGMENT_TYPES)
        case = lookup("cases", case_id)
        # state legality
        if judgment_type == "POSSESSION":
            if case["status"] not in {"IN_LITIGATION", "DEFAULTED"}:
                raise ApiError("ERR_INVALID_STATE", "Possession judgment requires IN_LITIGATION or DEFAULTED")
        elif judgment_type == "DISMISSAL":
            if case["status"] != "IN_LITIGATION":
                raise ApiError("ERR_INVALID_STATE", "Dismissal requires IN_LITIGATION")
        else:  # DIVERSION
            if case["status"] != "IN_LITIGATION":
                raise ApiError("ERR_INVALID_STATE", "Diversion judgment requires IN_LITIGATION")
        # SoD: judge must not have mediated (HELD/AGREEMENT) this case
        for ms in store.db["mediation_sessions"].values():
            if (ms["case_id"] == case_id and ms["status"] in {"HELD", "AGREEMENT"}
                    and ms["mediator_user_id"] == g.uid):
                raise ApiError("ERR_SOD_VIOLATION", "Judge mediated this case")

        j = services.new_entity("judgments", versioned=True)
        j["case_id"] = case_id
        j["judgment_type"] = judgment_type
        j["stay_until"] = None
        j["entered_by_user_id"] = g.uid
        j["status"] = "ENTERED"
        if judgment_type == "POSSESSION":
            j["money_amount_cents"] = services.final_net_arrears(case) + store.JUDGMENT_FILING_FEE_CENTS
            case["status"] = "JUDGMENT_ENTERED"
            case["outcome"] = "JUDGMENT_FOR_LANDLORD"
            services.touch(case)
        elif judgment_type == "DISMISSAL":
            j["money_amount_cents"] = 0
            case["status"] = "DISMISSED"
            case["outcome"] = "DISMISSED"
            case["closed_at"] = store.now()
            services.touch(case)
        else:  # DIVERSION
            j["money_amount_cents"] = 0
            case["status"] = "IN_DIVERSION"
            services.touch(case)
        return envelope.created(j)

    @app.route("/judgments/<judgment_id>", methods=["GET"])
    def get_judgment(judgment_id):
        authorize(JUDGMENT_READ_ROLES)
        j = lookup("judgments", judgment_id)
        check_case_ownership(store.db["cases"].get(j["case_id"], {}))
        return envelope.success(j)

    @app.route("/judgments", methods=["GET"])
    def list_judgments():
        authorize(JUDGMENT_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for j in store.db["judgments"].values():
            case = store.db["cases"].get(j["case_id"])
            if case is not None and not owns_case(case):
                continue
            if args.get("case_id") and j["case_id"] != args.get("case_id"):
                continue
            if args.get("status") and j["status"] != args.get("status"):
                continue
            items.append(j)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/judgments/<judgment_id>/transition", methods=["POST"])
    def transition_judgment(judgment_id):
        authorize({"Judge"})
        j = lookup("judgments", judgment_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in JUDGMENT_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        cur = j["status"]
        case = store.db["cases"].get(j["case_id"])
        if to == "STAYED":
            if cur != "ENTERED":
                raise ApiError("ERR_INVALID_STATE", "Judgment not ENTERED")
            stay_until = require_dt(body, "stay_until")
            if stay_until <= store.now():
                raise ApiError("ERR_INVALID_INTERVAL", "stay_until must be in the future")
            j["stay_until"] = stay_until
            j["status"] = "STAYED"
            services.touch(j)
        elif to == "ENTERED":
            if cur != "STAYED":
                raise ApiError("ERR_INVALID_STATE", "Judgment not STAYED")
            j["stay_until"] = None
            j["status"] = "ENTERED"
            services.touch(j)
        elif to == "VACATED":
            if cur not in {"ENTERED", "STAYED"}:
                raise ApiError("ERR_INVALID_STATE", "Judgment not ENTERED/STAYED")
            j["status"] = "VACATED"
            services.touch(j)
            if case is not None:
                services.dismiss_via_vacatur(case)
        elif to == "SATISFIED":
            if cur != "ENTERED":
                raise ApiError("ERR_INVALID_STATE", "Judgment not ENTERED")
            if j["judgment_type"] != "POSSESSION":
                raise ApiError("ERR_INVALID_STATE", "Only a possession judgment may be satisfied")
            j["status"] = "SATISFIED"
            services.touch(j)
        return envelope.success(j)

    # ----------------------------------------------------------- lockout orders
    @app.route("/lockout-orders", methods=["POST"])
    def create_lockout():
        authorize({"Landlord", "Clerk"})
        body = get_body()
        case_id = require_str(body, "case_id")
        judgment_id = require_str(body, "judgment_id")
        case = lookup("cases", case_id)
        judgment = lookup("judgments", judgment_id)
        check_case_ownership(case)
        if judgment["judgment_type"] != "POSSESSION" or judgment["status"] not in {"ENTERED", "STAYED"}:
            raise ApiError("ERR_NO_POSSESSION_JUDGMENT", "Requires a possession judgment in ENTERED/STAYED")
        lo = services.new_entity("lockout_orders", versioned=True)
        lo["case_id"] = case_id
        lo["judgment_id"] = judgment_id
        lo["officer_id"] = None
        lo["scheduled_at"] = None
        lo["executed_at"] = None
        lo["status"] = "REQUESTED"
        return envelope.created(lo)

    @app.route("/lockout-orders/<lockout_id>", methods=["GET"])
    def get_lockout(lockout_id):
        authorize(LOCKOUT_READ_ROLES)
        lo = lookup("lockout_orders", lockout_id)
        check_case_ownership(store.db["cases"].get(lo["case_id"], {}))
        return envelope.success(lo)

    @app.route("/lockout-orders", methods=["GET"])
    def list_lockouts():
        authorize(LOCKOUT_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for lo in store.db["lockout_orders"].values():
            case = store.db["cases"].get(lo["case_id"])
            if case is not None and not owns_case(case):
                continue
            if args.get("case_id") and lo["case_id"] != args.get("case_id"):
                continue
            if args.get("judgment_id") and lo["judgment_id"] != args.get("judgment_id"):
                continue
            if args.get("officer_id") and lo.get("officer_id") != args.get("officer_id"):
                continue
            if args.get("status") and lo["status"] != args.get("status"):
                continue
            items.append(lo)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/lockout-orders/<lockout_id>/transition", methods=["POST"])
    def transition_lockout(lockout_id):
        authorize({"Sheriff", "Clerk"})
        lo = lookup("lockout_orders", lockout_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in LOCKOUT_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        judgment = store.db["judgments"].get(lo["judgment_id"])
        case = store.db["cases"].get(lo["case_id"])

        if to == "SCHEDULED":
            if g.role != "Sheriff":
                raise ApiError("ERR_UNAUTHORIZED", "Only a sheriff may schedule a lockout")
            officer_id = require_str(body, "officer_id")
            scheduled_at = require_dt(body, "scheduled_at")
            lookup("officers", officer_id)
            if lo["status"] != "REQUESTED":
                raise ApiError("ERR_INVALID_STATE", "Lockout not REQUESTED")
            if judgment is None or judgment["judgment_type"] != "POSSESSION" \
                    or judgment["status"] not in {"ENTERED", "STAYED"}:
                raise ApiError("ERR_NO_POSSESSION_JUDGMENT", "Requires possession judgment in ENTERED/STAYED")
            if judgment["status"] == "STAYED" and judgment["stay_until"] is not None \
                    and scheduled_at < judgment["stay_until"]:
                raise ApiError("ERR_LOCKOUT_STAY_ACTIVE", "Scheduled inside an active stay")
            # officer buffer: no other SCHEDULED lockout within 48h
            for other in store.db["lockout_orders"].values():
                if (other["id"] != lo["id"] and other["status"] == "SCHEDULED"
                        and other.get("officer_id") == officer_id
                        and other.get("scheduled_at") is not None):
                    delta = abs((scheduled_at - other["scheduled_at"]).total_seconds())
                    if delta < store.LOCKOUT_BUFFER_HOURS * 3600:
                        raise ApiError("ERR_OFFICER_UNAVAILABLE", "Officer has a nearby scheduled lockout")
            lo["officer_id"] = officer_id
            lo["scheduled_at"] = scheduled_at
            lo["status"] = "SCHEDULED"
            services.touch(lo)
            if case is not None and case["status"] == "JUDGMENT_ENTERED":
                case["status"] = "ENFORCEMENT"
                services.touch(case)
        elif to == "EXECUTED":
            if g.role != "Sheriff":
                raise ApiError("ERR_UNAUTHORIZED", "Only a sheriff may execute a lockout")
            if lo["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "Lockout not SCHEDULED")
            if judgment is None or judgment["status"] != "ENTERED":
                raise ApiError("ERR_NO_POSSESSION_JUDGMENT", "Judgment must be ENTERED to execute")
            if store.now() < lo["scheduled_at"]:
                raise ApiError("ERR_LOCKOUT_NOT_DUE", "Lockout not yet due")
            lo["executed_at"] = store.now()
            lo["status"] = "EXECUTED"
            services.touch(lo)
            if case is not None and case["status"] == "ENFORCEMENT":
                case["status"] = "CLOSED_ENFORCED"
                case["outcome"] = "ENFORCED"
                case["closed_at"] = store.now()
                services.touch(case)
        elif to == "CANCELLED":
            if lo["status"] not in {"REQUESTED", "SCHEDULED"}:
                raise ApiError("ERR_INVALID_STATE", "Lockout not REQUESTED/SCHEDULED")
            lo["status"] = "CANCELLED"
            services.touch(lo)
        else:
            raise ApiError("ERR_INVALID_STATE", "Illegal lockout transition to %s" % to)
        return envelope.success(lo)

    # -------------------------------------------------------- sealing requests
    @app.route("/sealing-requests", methods=["POST"])
    def create_sealing():
        authorize({"Tenant"})
        body = get_body()
        case_id = require_str(body, "case_id")
        basis = require_enum(body, "basis", SEALING_BASES)
        case = lookup("cases", case_id)
        check_case_ownership(case)
        eligible = (case["status"] in {"DISMISSED", "DIVERSION_SATISFIED", "CLOSED_ENFORCED"}
                    and case["closed_at"] is not None
                    and store.now() >= case["closed_at"] + store.days(store.SEALING_WAIT_DAYS))
        if not eligible:
            raise ApiError("ERR_SEALING_INELIGIBLE", "Case is not eligible for sealing")
        sr = services.new_entity("sealing_requests", versioned=True)
        sr["case_id"] = case_id
        sr["basis"] = basis
        sr["decided_by_user_id"] = None
        sr["status"] = "REQUESTED"
        return envelope.created(sr)

    @app.route("/sealing-requests/<sealing_id>", methods=["GET"])
    def get_sealing(sealing_id):
        authorize(SEALING_READ_ROLES)
        sr = lookup("sealing_requests", sealing_id)
        check_case_ownership(store.db["cases"].get(sr["case_id"], {}))
        return envelope.success(sr)

    @app.route("/sealing-requests", methods=["GET"])
    def list_sealing():
        authorize(SEALING_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for sr in store.db["sealing_requests"].values():
            case = store.db["cases"].get(sr["case_id"])
            if case is not None and not owns_case(case):
                continue
            if args.get("case_id") and sr["case_id"] != args.get("case_id"):
                continue
            if args.get("status") and sr["status"] != args.get("status"):
                continue
            items.append(sr)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/sealing-requests/<sealing_id>/transition", methods=["POST"])
    def transition_sealing(sealing_id):
        authorize({"Judge"})
        sr = lookup("sealing_requests", sealing_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in SEALING_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        case = store.db["cases"].get(sr["case_id"])
        if to == "GRANTED":
            if sr["status"] != "REQUESTED":
                raise ApiError("ERR_INVALID_STATE", "Sealing request not REQUESTED")
            sr["decided_by_user_id"] = g.uid
            sr["status"] = "GRANTED"
            services.touch(sr)
            if case is not None:
                case["sealed"] = True
                services.touch(case)
        elif to == "DENIED":
            if sr["status"] != "REQUESTED":
                raise ApiError("ERR_INVALID_STATE", "Sealing request not REQUESTED")
            sr["decided_by_user_id"] = g.uid
            sr["status"] = "DENIED"
            services.touch(sr)
        else:
            raise ApiError("ERR_INVALID_STATE", "Illegal sealing transition to %s" % to)
        return envelope.success(sr)
