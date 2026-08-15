"""Routes: matters — intake, lifecycle transitions, summary."""
from flask import request

import calc
from db import new_common, next_matter_number, parse_dt, store, touch
from errors import (
    ERR_FIELD_CONSTRAINT,
    ERR_HOLD_COMPLIANCE_BLOCK,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_ENGAGEMENT,
    ERR_NOT_FOUND,
    ERR_NOT_MATTER_OWNER,
    ERR_NO_APPROVED_BUDGET,
    ERR_OPEN_LIMITATION_EXPOSURE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENCE_STATE_INVALID,
    ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT,
    raise_err,
)
from middleware import READ_SET_CFO, apply_filters, auth, get_body, paginate
from response import ok_list, ok_object
from serializers import serialize
from validation import check_constraints_11, check_shape_23, reject_extra_fields

LC = ("LitigationCounsel",)
DGC = ("DeputyGeneralCounsel",)
LOA = ("LegalOperationsAnalyst",)

MATTER_TYPES = ("COMMERCIAL", "EMPLOYMENT", "IP", "REGULATORY", "PRODUCT_LIABILITY", "CLASS_ACTION")
RESOLUTION_TYPES_DIRECT = ("JUDGMENT", "DISMISSAL", "SUMMARY_JUDGMENT")

CREATE_SPEC = {
    "title": {"type": "str", "required": True},
    "matter_type": {"type": "enum", "enum": MATTER_TYPES, "required": True},
    "adverse_party": {"type": "str", "required": True},
    "jurisdiction": {"type": "str", "required": True},
    "filing_date": {"type": "datetime", "required": True},
    "owning_counsel_id": {"type": "str", "required": True},
    "exposure_low_cents": {"type": "int", "min": 0},
    "exposure_high_cents": {"type": "int", "min": 0},
    "probability_of_loss_pct": {"type": "int", "min": 0, "max": 100},
}

PATCH_SPEC = {
    "title": {"type": "str"},
    "exposure_low_cents": {"type": "int", "min": 0},
    "exposure_high_cents": {"type": "int", "min": 0},
    "probability_of_loss_pct": {"type": "int", "min": 0, "max": 100},
    "owning_counsel_id": {"type": "str"},
}


def get_matter(mid):
    rec = store.matters.get(mid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Matter %s does not exist." % mid)
    return rec


def _require_owner(uid, matter):
    if uid != matter["owning_counsel_id"]:
        raise_err(ERR_NOT_MATTER_OWNER, "Only the owning counsel may perform this operation.")


def register(app):

    @app.post("/litigation/matters")
    def create_matter():
        auth(LC)
        body = get_body()
        # (4) body FK existence
        owner_id = body.get("owning_counsel_id") if isinstance(body, dict) else None
        owner = None
        if isinstance(owner_id, str) and owner_id != "":
            owner = store.staff_users.get(owner_id)
            if owner is None:
                raise_err(ERR_REFERENCE_NOT_FOUND, "owning_counsel_id does not name a staff user.")
        # (11) scalar constraints
        check_constraints_11(body, CREATE_SPEC)
        if isinstance(body, dict):
            low = body.get("exposure_low_cents")
            high = body.get("exposure_high_cents")
            if (
                isinstance(low, int) and not isinstance(low, bool)
                and isinstance(high, int) and not isinstance(high, bool)
                and high < low
            ):
                raise_err(ERR_FIELD_CONSTRAINT, "exposure_high_cents must be >= exposure_low_cents.")
        # (16) a deactivated staff member may not own new matters
        if owner is not None and not owner.get("is_active", True):
            raise_err(ERR_REFERENCE_STATE_INVALID, "A deactivated staff member may not own new matters.")
        # (23) request shape
        check_shape_23(body, CREATE_SPEC)
        rec = new_common(
            {
                "matter_number": next_matter_number(),
                "title": body["title"],
                "matter_type": body["matter_type"],
                "adverse_party": body["adverse_party"],
                "jurisdiction": body["jurisdiction"],
                "filing_date": parse_dt(body["filing_date"]),
                "status": "INTAKE",
                "exposure_low_cents": body.get("exposure_low_cents"),
                "exposure_high_cents": body.get("exposure_high_cents"),
                "probability_of_loss_pct": body.get("probability_of_loss_pct"),
                "exposure_tier": None,
                "reserve_amount_cents": None,
                "accrued_to_date_cents": 0,
                "posture": None,
                "resolution_type": None,
                "resolved_at": None,
                "owning_counsel_id": body["owning_counsel_id"],
                "close_checklist_ack": False,
            }
        )
        store.matters[rec["id"]] = rec
        calc.recompute_matter_derived(rec, tier_changed=True)
        return ok_object(serialize("matter", rec), 201)

    @app.get("/litigation/matters")
    def list_matters():
        auth(READ_SET_CFO)
        records = apply_filters(
            store.matters.values(),
            [
                ("status", request.args.get("status")),
                ("exposure_tier", request.args.get("exposure_tier")),
                ("matter_type", request.args.get("matter_type")),
                ("owning_counsel_id", request.args.get("owning_counsel_id")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("matter", r) for r in page], limit, offset, total)

    @app.get("/litigation/matters/<mid>")
    def get_one_matter(mid):
        auth(READ_SET_CFO)
        return ok_object(serialize("matter", get_matter(mid)))

    @app.patch("/litigation/matters/<mid>")
    def patch_matter(mid):
        auth(LC)
        matter = get_matter(mid)
        body = get_body()
        # (5) updates allowed only while INTAKE or ASSESSMENT
        if matter["status"] not in ("INTAKE", "ASSESSMENT"):
            raise_err(ERR_INVALID_STATE, "Matter intake fields are frozen past ASSESSMENT.")
        # (4) body FK existence
        owner_id = body.get("owning_counsel_id") if isinstance(body, dict) else None
        if isinstance(owner_id, str) and owner_id != "":
            if owner_id not in store.staff_users:
                raise_err(ERR_REFERENCE_NOT_FOUND, "owning_counsel_id does not name a staff user.")
        # (11) scalar constraints on present fields, cross-field on merged values
        check_constraints_11(body, PATCH_SPEC)
        if isinstance(body, dict):
            low = body.get("exposure_low_cents", matter["exposure_low_cents"])
            high = body.get("exposure_high_cents", matter["exposure_high_cents"])
            if (
                isinstance(low, int) and not isinstance(low, bool)
                and isinstance(high, int) and not isinstance(high, bool)
                and high < low
            ):
                raise_err(ERR_FIELD_CONSTRAINT, "exposure_high_cents must be >= exposure_low_cents.")
        # (23) request shape
        check_shape_23(body, PATCH_SPEC)
        for field in ("title", "exposure_low_cents", "exposure_high_cents",
                      "probability_of_loss_pct", "owning_counsel_id"):
            if field in body:
                matter[field] = body[field]
        calc.recompute_matter_derived(matter, tier_changed=True)
        touch(matter)
        return ok_object(serialize("matter", matter))

    @app.post("/litigation/matters/<mid>/submit-assessment")
    def submit_assessment(mid):
        uid, _ = auth(LC)
        matter = get_matter(mid)
        body = get_body()
        if matter["status"] != "INTAKE":
            raise_err(ERR_INVALID_STATE, "Only an INTAKE matter may be submitted for assessment.")
        _require_owner(uid, matter)
        # (11) the exposure triplet must be set with high >= low
        low = matter["exposure_low_cents"]
        high = matter["exposure_high_cents"]
        prob = matter["probability_of_loss_pct"]
        if low is None or high is None or prob is None:
            raise_err(ERR_FIELD_CONSTRAINT, "The exposure triplet must be set before assessment.")
        if high < low:
            raise_err(ERR_FIELD_CONSTRAINT, "exposure_high_cents must be >= exposure_low_cents.")
        reject_extra_fields(body, ())
        matter["status"] = "ASSESSMENT"
        calc.recompute_matter_derived(matter, tier_changed=True)
        touch(matter)
        return ok_object(serialize("matter", matter))

    @app.post("/litigation/matters/<mid>/advance-to-staffing")
    def advance_to_staffing(mid):
        uid, _ = auth(LC)
        matter = get_matter(mid)
        body = get_body()
        if matter["status"] != "ASSESSMENT":
            raise_err(ERR_INVALID_STATE, "Only an ASSESSMENT matter may advance to staffing.")
        _require_owner(uid, matter)
        if not any(d["matter_id"] == mid for d in store.deadlines.values()):
            raise_err(ERR_INVALID_STATE, "At least one deadline must exist before staffing.")
        reject_extra_fields(body, ())
        matter["status"] = "STAFFING"
        matter["posture"] = calc.compute_posture(matter)
        touch(matter)
        return ok_object(serialize("matter", matter))

    @app.post("/litigation/matters/<mid>/activate")
    def activate_matter(mid):
        uid, _ = auth(LC)
        matter = get_matter(mid)
        body = get_body()
        if matter["status"] not in ("STAFFING", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "Only a STAFFING or REOPENED matter may activate.")
        _require_owner(uid, matter)
        if matter["status"] == "STAFFING":
            # (21) an APPROVED budget is required on the STAFFING path
            if calc.approved_budget_of(mid) is None:
                raise_err(ERR_NO_APPROVED_BUDGET, "An APPROVED budget is required to activate.")
            # (25) at least one ACTIVE engagement
            if not any(
                e["matter_id"] == mid and e["status"] == "ACTIVE"
                for e in store.engagements.values()
            ):
                raise_err(ERR_NO_ACTIVE_ENGAGEMENT, "At least one ACTIVE engagement is required.")
        else:
            # REOPENED path: ACTIVE or SUSPENDED engagement suffices
            if not any(
                e["matter_id"] == mid and e["status"] in ("ACTIVE", "SUSPENDED")
                for e in store.engagements.values()
            ):
                raise_err(ERR_NO_ACTIVE_ENGAGEMENT, "At least one ACTIVE or SUSPENDED engagement is required.")
        reject_extra_fields(body, ())
        matter["status"] = "ACTIVE"
        matter["posture"] = calc.compute_posture(matter)
        touch(matter)
        return ok_object(serialize("matter", matter))

    @app.post("/litigation/matters/<mid>/resolve")
    def resolve_matter(mid):
        uid, _ = auth(LC)
        matter = get_matter(mid)
        body = get_body()
        if matter["status"] not in ("ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "Only an ACTIVE or REOPENED matter may be resolved.")
        _require_owner(uid, matter)
        # (11) SETTLEMENT resolution flows only via the settlement pipeline
        rt = body.get("resolution_type") if isinstance(body, dict) else None
        if isinstance(rt, str) and rt not in RESOLUTION_TYPES_DIRECT:
            raise_err(
                ERR_FIELD_CONSTRAINT,
                "resolution_type must be one of JUDGMENT, DISMISSAL, SUMMARY_JUDGMENT.",
            )
        # (23) request shape
        check_shape_23(body, {"resolution_type": {"type": "str", "required": True}})
        # (26) open limitation exposure must be vacated first
        for d in store.deadlines.values():
            if (
                d["matter_id"] == mid
                and d["deadline_type"] == "LIMITATION_EXPIRY"
                and d["status"] == "SCHEDULED"
            ):
                raise_err(
                    ERR_OPEN_LIMITATION_EXPOSURE,
                    "A SCHEDULED LIMITATION_EXPIRY deadline blocks resolution.",
                )
        calc.matter_resolution_cascade(matter, body["resolution_type"], vacate_deadlines=True)
        return ok_object(serialize("matter", matter))

    @app.post("/litigation/matters/<mid>/reopen")
    def reopen_matter(mid):
        auth(DGC)
        matter = get_matter(mid)
        body = get_body()
        if matter["status"] != "RESOLVED":
            raise_err(ERR_INVALID_STATE, "Only a RESOLVED matter may be reopened.")
        # (23) reopen_reason must be a non-empty string
        check_shape_23(body, {"reopen_reason": {"type": "str", "required": True}})
        # (28) a confirmed disbursed payment makes reopening impossible
        for p in store.payments.values():
            if (
                p["matter_id"] == mid
                and p["status"] == "DISBURSED"
                and p["payment_status"] == "CONFIRMED"
            ):
                raise_err(
                    ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT,
                    "A confirmed disbursed payment blocks reopening.",
                )
        matter["status"] = "REOPENED"
        matter["resolved_at"] = None
        matter["reserve_amount_cents"] = calc.compute_reserve(matter)
        matter["posture"] = calc.compute_posture(matter)
        touch(matter)
        return ok_object(serialize("matter", matter))

    @app.post("/litigation/matters/<mid>/close")
    def close_matter(mid):
        auth(LOA)
        matter = get_matter(mid)
        body = get_body()
        if matter["status"] not in ("INTAKE", "RESOLVED"):
            raise_err(ERR_INVALID_STATE, "Only an INTAKE or RESOLVED matter may be closed.")
        # (8) hold-compliance pins
        if matter["status"] == "INTAKE":
            if (
                any(e["matter_id"] == mid for e in store.engagements.values())
                or any(h["matter_id"] == mid for h in store.holds.values())
                or any(w["matter_id"] == mid for w in store.work_orders.values())
                or any(s["matter_id"] == mid for s in store.settlements.values())
                or any(p["matter_id"] == mid for p in store.payments.values())
            ):
                raise_err(
                    ERR_HOLD_COMPLIANCE_BLOCK,
                    "An INTAKE matter with child records cannot be closed.",
                )
        else:
            if any(h["matter_id"] == mid and h["status"] != "RELEASED" for h in store.holds.values()):
                raise_err(ERR_HOLD_COMPLIANCE_BLOCK, "All holds must be RELEASED before closure.")
            if any(
                w["matter_id"] == mid and w["status"] not in ("COMPLETED", "CANCELLED")
                for w in store.work_orders.values()
            ):
                raise_err(ERR_HOLD_COMPLIANCE_BLOCK, "All work orders must be terminal before closure.")
            if any(
                p["matter_id"] == mid and p["status"] not in ("DISBURSED", "REJECTED", "CANCELLED")
                for p in store.payments.values()
            ):
                raise_err(ERR_HOLD_COMPLIANCE_BLOCK, "All payment requests must be terminal before closure.")
        # (23) close_checklist_ack must be present and true
        check_shape_23(body, {"close_checklist_ack": {"type": "bool", "required": True}})
        if body["close_checklist_ack"] is not True:
            raise_err(ERR_INVALID_REQUEST, "close_checklist_ack must be true.")
        matter["close_checklist_ack"] = True
        matter["status"] = "CLOSED"
        matter["posture"] = calc.compute_posture(matter)
        touch(matter)
        return ok_object(serialize("matter", matter))

    @app.get("/litigation/matters/<mid>/summary")
    def matter_summary(mid):
        auth(READ_SET_CFO)
        matter = get_matter(mid)
        budget = calc.approved_budget_of(mid)
        open_deadline_count = sum(
            1 for d in store.deadlines.values()
            if d["matter_id"] == mid and d["status"] == "SCHEDULED"
        )
        active_hold_count = sum(
            1 for h in store.holds.values()
            if h["matter_id"] == mid and h["status"] in ("DRAFT", "ISSUED", "ACKNOWLEDGED")
        )
        committed_estimate = sum(
            w["estimated_cost_cents"] for w in store.work_orders.values()
            if w["matter_id"] == mid and w["status"] in ("AUTHORIZED", "IN_PROGRESS")
        )
        return ok_object(
            {
                "matter_id": mid,
                "reserve_amount_cents": matter["reserve_amount_cents"],
                "accrued_to_date_cents": matter["accrued_to_date_cents"],
                "utilization_pct": budget["utilization_pct"] if budget is not None else 0,
                "open_deadline_count": open_deadline_count,
                "active_hold_count": active_hold_count,
                "committed_vendor_estimate_cents": committed_estimate,
            }
        )
