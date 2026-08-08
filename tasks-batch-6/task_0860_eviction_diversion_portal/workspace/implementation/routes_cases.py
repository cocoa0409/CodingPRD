"""Case and Answer routes."""

from flask import g, request

import envelope
import services
import store
from common import (authorize, check_case_ownership, get_body, lookup, owns_case,
                    optional_int, pagination_params, paginate, require_enum,
                    require_int, require_str)
from errors import ApiError

ALL_ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge", "ProgramAdmin", "Sheriff"}
CASE_READ_ROLES = ALL_ROLES
ANSWER_ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge"}

FILING_TYPES = {"NONPAYMENT", "HOLDOVER", "NUISANCE"}
CASE_STATUSES = {
    "FILED", "SERVED", "ANSWERED", "DEFAULTED", "IN_DIVERSION", "IN_LITIGATION",
    "JUDGMENT_ENTERED", "ENFORCEMENT", "CLOSED_ENFORCED", "DIVERSION_SATISFIED",
    "DISMISSED",
}
DEFENSE_TYPES = {"WARRANTY_OF_HABITABILITY", "IMPROPER_SERVICE", "RENT_PAID",
                 "RETALIATION", "DISCRIMINATION"}


def _truthy(v):
    return str(v).lower() in ("1", "true", "yes")


def register(app):
    # ------------------------------------------------------------------ cases
    @app.route("/cases", methods=["POST"])
    def create_case():
        authorize({"Landlord", "Clerk"})
        body = get_body()
        court_id = require_str(body, "court_id")
        landlord_id = require_str(body, "landlord_id")
        tenant_id = require_str(body, "tenant_id")
        filing_type = require_enum(body, "filing_type", FILING_TYPES)
        claimed = optional_int(body, "claimed_arrears_cents", default=0, minimum=0)
        # existence left-to-right
        lookup("courts", court_id)
        lookup("landlords", landlord_id)
        lookup("tenants", tenant_id)
        # ownership (entity-backed Landlord)
        if g.role == "Landlord" and landlord_id != g.uid:
            raise ApiError("ERR_UNAUTHORIZED", "Landlord may only file their own cases")

        case = services.new_entity("cases", versioned=True)
        case["court_id"] = court_id
        case["landlord_id"] = landlord_id
        case["tenant_id"] = tenant_id
        case["filing_type"] = filing_type
        case["claimed_arrears_cents"] = claimed
        case["net_arrears_cents"] = claimed
        case["answer_due_at"] = case["created_at"] + store.days(store.ANSWER_WINDOW_DAYS)
        case["served_at"] = None
        case["status"] = "FILED"
        case["outcome"] = "PENDING"
        case["closed_at"] = None
        case["sealed"] = False
        return envelope.created(case)

    @app.route("/cases/<case_id>", methods=["GET"])
    def get_case(case_id):
        authorize(CASE_READ_ROLES)
        case = lookup("cases", case_id)
        check_case_ownership(case)
        services.refresh_case(case)
        return envelope.success(case)

    @app.route("/cases", methods=["GET"])
    def list_cases():
        authorize(CASE_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        include_sealed = _truthy(args.get("include_sealed")) if args.get("include_sealed") is not None else False
        items = []
        for c in store.db["cases"].values():
            if not owns_case(c):
                continue
            if args.get("court_id") and c["court_id"] != args.get("court_id"):
                continue
            if args.get("landlord_id") and c["landlord_id"] != args.get("landlord_id"):
                continue
            if args.get("tenant_id") and c["tenant_id"] != args.get("tenant_id"):
                continue
            if args.get("status") and c["status"] != args.get("status"):
                continue
            if c["sealed"] and not include_sealed:
                continue
            services.refresh_case(c)
            items.append(c)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/cases/<case_id>/transition", methods=["POST"])
    def transition_case(case_id):
        authorize({"Clerk"})
        case = lookup("cases", case_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in CASE_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        cur = case["status"]
        if to == "SERVED":
            if cur != "FILED":
                raise ApiError("ERR_INVALID_STATE", "Case not in FILED")
            case["status"] = "SERVED"
            case["served_at"] = store.now()
            services.touch(case)
        elif to == "DEFAULTED":
            if cur not in {"SERVED", "ANSWERED"}:
                raise ApiError("ERR_INVALID_STATE", "Case not in SERVED")
            if store.now() < case["answer_due_at"]:
                raise ApiError("ERR_ANSWER_WINDOW_OPEN", "Answer window still open")
            has_answer = any(a["case_id"] == case["id"] for a in store.db["answers"].values())
            if has_answer:
                raise ApiError("ERR_ALREADY_ANSWERED", "An answer already exists")
            case["status"] = "DEFAULTED"
            services.touch(case)
        elif to == "IN_LITIGATION":
            if cur not in {"ANSWERED", "IN_DIVERSION"}:
                raise ApiError("ERR_INVALID_STATE", "Case cannot move to IN_LITIGATION from %s" % cur)
            case["status"] = "IN_LITIGATION"
            services.touch(case)
        else:
            raise ApiError("ERR_INVALID_STATE", "Clerk cannot drive transition to %s" % to)
        services.refresh_case(case)
        return envelope.success(case)

    # ---------------------------------------------------------------- answers
    @app.route("/answers", methods=["POST"])
    def create_answer():
        authorize({"Tenant"})
        body = get_body()
        case_id = require_str(body, "case_id")
        defenses = body.get("defenses")
        if not isinstance(defenses, list):
            raise ApiError("ERR_VALIDATION", "defenses must be an array")
        for d in defenses:
            if d not in DEFENSE_TYPES:
                raise ApiError("ERR_VALIDATION", "Invalid defense: %s" % d)
        rent_withheld = optional_int(body, "rent_withheld_cents", default=0, minimum=0)
        case = lookup("cases", case_id)
        check_case_ownership(case)
        if case["status"] == "DEFAULTED":
            raise ApiError("ERR_ANSWER_WINDOW_CLOSED", "Case has already defaulted")
        if case["status"] != "SERVED":
            raise ApiError("ERR_INVALID_STATE", "Case must be SERVED to answer")

        ans = services.new_entity("answers", versioned=False)
        ans["case_id"] = case_id
        ans["defenses"] = defenses
        ans["rent_withheld_cents"] = rent_withheld
        ans["is_late"] = ans["created_at"] > case["answer_due_at"]
        # side-effect: case SERVED -> ANSWERED
        case["status"] = "ANSWERED"
        services.touch(case)
        return envelope.created(ans)

    @app.route("/answers/<answer_id>", methods=["GET"])
    def get_answer(answer_id):
        authorize(ANSWER_ROLES)
        ans = lookup("answers", answer_id)
        case = store.db["cases"].get(ans["case_id"])
        if case is not None:
            check_case_ownership(case)
        return envelope.success(ans)

    @app.route("/answers", methods=["GET"])
    def list_answers():
        authorize(ANSWER_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for a in store.db["answers"].values():
            case = store.db["cases"].get(a["case_id"])
            if case is not None and not owns_case(case):
                continue
            if args.get("case_id") and a["case_id"] != args.get("case_id"):
                continue
            items.append(a)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)
