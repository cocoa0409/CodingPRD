"""Routes: logical clock, staff users, counsel firms."""
from flask import request

from calc import run_sweeps
from db import fmt_iso, new_common, parse_dt, store, touch
from errors import (
    ERR_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERENCE_STATE_INVALID,
    raise_err,
)
from middleware import (
    READ_SET,
    READ_SET_CFO,
    apply_filters,
    auth,
    get_body,
    paginate,
    parse_bool_filter,
)
from response import ok_list, ok_object
from serializers import serialize
from validation import check_constraints_11, check_shape_23, reject_extra_fields

LOA = ("LegalOperationsAnalyst",)
GC = ("GeneralCounsel",)

JOB_FAMILIES = ("LEGAL", "FINANCE", "OPERATIONS", "EXECUTIVE")
CONFLICT_RESULTS = ("CLEARED", "WAIVED", "FLAGGED")


def _get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Resource %s does not exist." % rid)
    return rec


def register(app):

    # ---------------------------------------------------------- logical clock
    @app.post("/litigation/_clock/set_current_utc")
    def set_clock():
        auth(LOA)
        body = get_body()
        target = parse_dt(body.get("to_iso8601")) if isinstance(body, dict) else None
        check_shape_23(body, {"to_iso8601": {"type": "datetime", "required": True}})
        store.clock = target
        run_sweeps()
        return ok_object({"current_utc": fmt_iso(store.clock)})

    # ------------------------------------------------------------ staff users
    @app.post("/litigation/staff-users")
    def create_staff_user():
        auth(LOA)
        body = get_body()
        spec = {
            "full_name": {"type": "str", "required": True},
            "email": {"type": "str", "required": True},
            "job_family": {"type": "enum", "enum": JOB_FAMILIES, "required": True},
            "is_active": {"type": "bool"},
        }
        check_constraints_11(body, spec)
        if isinstance(body, dict) and isinstance(body.get("email"), str):
            for u in store.staff_users.values():
                if u["email"] == body["email"]:
                    raise_err(ERR_DUPLICATE, "A staff user with this email already exists.")
        check_shape_23(body, spec)
        rec = new_common(
            {
                "full_name": body["full_name"],
                "email": body["email"],
                "job_family": body["job_family"],
                "is_active": body.get("is_active", True),
            }
        )
        store.staff_users[rec["id"]] = rec
        return ok_object(serialize("staff_user", rec), 201)

    @app.get("/litigation/staff-users")
    def list_staff_users():
        auth(READ_SET_CFO)
        records = apply_filters(
            store.staff_users.values(),
            [
                ("email", request.args.get("email")),
                ("job_family", request.args.get("job_family")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("staff_user", r) for r in page], limit, offset, total)

    @app.get("/litigation/staff-users/<rid>")
    def get_staff_user(rid):
        auth(READ_SET_CFO)
        rec = _get_or_404(store.staff_users, rid)
        return ok_object(serialize("staff_user", rec))

    @app.get("/litigation/staff-users/<rid>/custodianships")
    def list_custodianships(rid):
        auth(("LitigationCounsel", "DeputyGeneralCounsel", "GeneralCounsel", "LegalOperationsAnalyst"))
        _get_or_404(store.staff_users, rid)
        records = [c for c in store.custodians.values() if c["staff_user_id"] == rid]
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("custodian", r) for r in page], limit, offset, total)

    # ----------------------------------------------------------- counsel firms
    @app.post("/litigation/counsel-firms")
    def create_firm():
        auth(LOA)
        body = get_body()
        spec = {
            "firm_name": {"type": "str", "required": True},
            "blended_rate_cap_cents": {"type": "int", "required": True, "positive": True},
            "is_active": {"type": "bool"},
        }
        check_constraints_11(body, spec)
        check_shape_23(body, spec)
        rec = new_common(
            {
                "firm_name": body["firm_name"],
                "panel_status": "PENDING",
                "conflict_check_status": "UNCHECKED",
                "blended_rate_cap_cents": body["blended_rate_cap_cents"],
                "is_active": body.get("is_active", True),
            }
        )
        store.firms[rec["id"]] = rec
        return ok_object(serialize("firm", rec), 201)

    @app.get("/litigation/counsel-firms")
    def list_firms():
        auth(READ_SET)
        records = apply_filters(
            store.firms.values(),
            [
                ("panel_status", request.args.get("panel_status")),
                ("is_active", parse_bool_filter(request.args.get("is_active"))),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("firm", r) for r in page], limit, offset, total)

    @app.get("/litigation/counsel-firms/<rid>")
    def get_firm(rid):
        auth(READ_SET)
        rec = _get_or_404(store.firms, rid)
        return ok_object(serialize("firm", rec))

    @app.post("/litigation/counsel-firms/<rid>/conflict-check")
    def firm_conflict_check(rid):
        auth(LOA)
        firm = _get_or_404(store.firms, rid)
        body = get_body()
        spec = {"result": {"type": "enum", "enum": CONFLICT_RESULTS, "required": True}}
        check_constraints_11(body, spec)
        check_shape_23(body, spec)
        firm["conflict_check_status"] = body["result"]
        touch(firm)
        return ok_object(serialize("firm", firm))

    @app.post("/litigation/counsel-firms/<rid>/approve-panel")
    def firm_approve_panel(rid):
        auth(GC)
        firm = _get_or_404(store.firms, rid)
        body = get_body()
        if firm["panel_status"] != "PENDING":
            raise_err(ERR_INVALID_STATE, "Only a PENDING firm may be approved onto the panel.")
        if firm["conflict_check_status"] not in ("CLEARED", "WAIVED"):
            raise_err(
                ERR_REFERENCE_STATE_INVALID,
                "Conflict screening must be CLEARED or WAIVED before panel approval.",
            )
        reject_extra_fields(body, ())
        firm["panel_status"] = "APPROVED"
        touch(firm)
        return ok_object(serialize("firm", firm))

    @app.post("/litigation/counsel-firms/<rid>/suspend")
    def firm_suspend(rid):
        auth(GC)
        firm = _get_or_404(store.firms, rid)
        body = get_body()
        if firm["panel_status"] != "APPROVED":
            raise_err(ERR_INVALID_STATE, "Only an APPROVED firm may be suspended.")
        reject_extra_fields(body, ())
        firm["panel_status"] = "SUSPENDED"
        touch(firm)
        for e in store.engagements.values():
            if e["firm_id"] == firm["id"] and e["status"] == "ACTIVE":
                e["status"] = "SUSPENDED"
                touch(e)
        return ok_object(serialize("firm", firm))

    @app.post("/litigation/counsel-firms/<rid>/reinstate")
    def firm_reinstate(rid):
        auth(GC)
        firm = _get_or_404(store.firms, rid)
        body = get_body()
        if firm["panel_status"] != "SUSPENDED":
            raise_err(ERR_INVALID_STATE, "Only a SUSPENDED firm may be reinstated.")
        reject_extra_fields(body, ())
        firm["panel_status"] = "APPROVED"
        touch(firm)
        return ok_object(serialize("firm", firm))

    @app.post("/litigation/counsel-firms/<rid>/terminate")
    def firm_terminate(rid):
        auth(GC)
        firm = _get_or_404(store.firms, rid)
        body = get_body()
        if firm["panel_status"] not in ("APPROVED", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "Only an APPROVED or SUSPENDED firm may be terminated.")
        for e in store.engagements.values():
            if e["firm_id"] == firm["id"] and e["status"] in ("ACTIVE", "APPROVED"):
                raise_err(
                    ERR_REFERENCE_STATE_INVALID,
                    "Firm has engagements in ACTIVE or APPROVED status; terminate them first.",
                )
        reject_extra_fields(body, ())
        firm["panel_status"] = "TERMINATED"
        touch(firm)
        return ok_object(serialize("firm", firm))

    @app.get("/litigation/counsel-firms/<rid>/engagements")
    def firm_engagements(rid):
        auth(READ_SET)
        _get_or_404(store.firms, rid)
        records = [e for e in store.engagements.values() if e["firm_id"] == rid]
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("engagement", r) for r in page], limit, offset, total)
