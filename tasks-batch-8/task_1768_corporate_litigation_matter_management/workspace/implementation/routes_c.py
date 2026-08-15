"""Routes: engagements, budgets, accrual entries."""
import re

from flask import request

import calc
from db import fmt_ts, new_common, new_id, next_seq, store, touch, wall_now
from errors import (
    ERR_BUDGET_EXCEEDED,
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_DUPLICATE,
    ERR_ENGAGEMENT_LETTER_REQUIRED,
    ERR_FIELD_CONSTRAINT,
    ERR_INVALID_STATE,
    ERR_MATTER_POSTURE_FROZEN,
    ERR_NOT_FOUND,
    ERR_RATE_CAP_EXCEEDED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENCE_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_MATTER_VERSION,
    raise_err,
)
from middleware import READ_SET, apply_filters, auth, get_body, paginate
from response import ok_list, ok_object
from routes_b import get_matter
from serializers import serialize
from validation import check_constraints_11, check_shape_23, reject_extra_fields

LC = ("LitigationCounsel",)
DGC = ("DeputyGeneralCounsel",)
FBP = ("FinanceBusinessPartner",)

ROLE_TYPES = ("LEAD_COUNSEL", "CO_COUNSEL", "LOCAL_COUNSEL", "SPECIALIST")
FEE_ARRANGEMENTS = ("HOURLY", "FLAT_FEE", "CONTINGENCY", "HYBRID")
ENTRY_KINDS = ("ACCRUAL", "INVOICE", "ADJUSTMENT")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

ENGAGEMENT_CREATE_SPEC = {
    "firm_id": {"type": "str", "required": True},
    "role_type": {"type": "enum", "enum": ROLE_TYPES, "required": True},
    "fee_arrangement": {"type": "enum", "enum": FEE_ARRANGEMENTS, "required": True},
    "proposed_rate_cents": {"type": "int", "positive": True},
    "contingency_pct": {"type": "int", "min": 1, "max": 40},
    "engagement_letter_executed": {"type": "bool"},
    "supersedes_engagement_id": {"type": "str"},
}

BUDGET_CREATE_SPEC = {
    "fiscal_year": {"type": "int", "required": True},
    "lifecycle_budget_cents": {"type": "int", "required": True, "positive": True},
    "fy_budget_cents": {"type": "int", "required": True, "positive": True},
    "expected_matter_version": {"type": "int", "required": True},
    "prior_version_id": {"type": "str"},
}

ACCRUAL_CREATE_SPEC = {
    "engagement_id": {"type": "str", "required": True},
    "period": {"type": "str", "required": True},
    "entry_kind": {"type": "enum", "enum": ENTRY_KINDS, "required": True},
    "amount_cents": {"type": "int", "required": True},
    "reverses_entry_id": {"type": "str"},
}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_engagement(eid):
    rec = store.engagements.get(eid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Engagement %s does not exist." % eid)
    return rec


def get_budget(bid):
    rec = store.budgets.get(bid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Budget %s does not exist." % bid)
    return rec


def get_accrual(aid):
    rec = store.accruals.get(aid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Accrual entry %s does not exist." % aid)
    return rec


def register(app):

    # ------------------------------------------------------------ engagements
    @app.post("/litigation/matters/<mid>/engagements")
    def create_engagement(mid):
        auth(LC)
        matter = get_matter(mid)
        body = get_body()
        # (4) body FK existence
        firm = None
        if isinstance(body, dict):
            firm_id = body.get("firm_id")
            if isinstance(firm_id, str) and firm_id != "":
                firm = store.firms.get(firm_id)
                if firm is None:
                    raise_err(ERR_REFERENCE_NOT_FOUND, "firm_id does not name a counsel firm.")
            sup_id = body.get("supersedes_engagement_id")
            if isinstance(sup_id, str) and sup_id != "" and sup_id not in store.engagements:
                raise_err(ERR_REFERENCE_NOT_FOUND, "supersedes_engagement_id does not name an engagement.")
        # (11) scalar constraints
        check_constraints_11(body, ENGAGEMENT_CREATE_SPEC)
        # (15) supersedes target must belong to the same matter
        if firm is not None and isinstance(body, dict):
            sup_id = body.get("supersedes_engagement_id")
            if isinstance(sup_id, str) and sup_id in store.engagements:
                if store.engagements[sup_id]["matter_id"] != mid:
                    raise_err(
                        ERR_CROSS_REFERENCE_MISMATCH,
                        "supersedes_engagement_id must name an engagement of the same matter.",
                    )
        # (17) rate cap for HOURLY/HYBRID
        if firm is not None and isinstance(body, dict):
            rate = body.get("proposed_rate_cents")
            if body.get("fee_arrangement") in ("HOURLY", "HYBRID") and _is_int(rate):
                if rate > firm["blended_rate_cap_cents"]:
                    raise_err(ERR_RATE_CAP_EXCEEDED, "proposed_rate_cents exceeds the firm blended rate cap.")
        # (23) request shape with conditional requirements
        def _need_rate(b):
            return b.get("fee_arrangement") in ("HOURLY", "HYBRID")

        def _need_contingency(b):
            return b.get("fee_arrangement") in ("CONTINGENCY", "HYBRID")

        check_shape_23(
            body,
            ENGAGEMENT_CREATE_SPEC,
            conditional_required={
                "proposed_rate_cents": _need_rate,
                "contingency_pct": _need_contingency,
            },
        )
        rec = new_common(
            {
                "matter_id": mid,
                "firm_id": body["firm_id"],
                "role_type": body["role_type"],
                "status": "PROPOSED",
                "fee_arrangement": body["fee_arrangement"],
                "proposed_rate_cents": body.get("proposed_rate_cents"),
                "contingency_pct": body.get("contingency_pct"),
                "approved_by_user_id": None,
                "engagement_letter_executed": body.get("engagement_letter_executed", False),
                "supersedes_engagement_id": body.get("supersedes_engagement_id"),
            }
        )
        store.engagements[rec["id"]] = rec
        return ok_object(serialize("engagement", rec), 201)

    @app.get("/litigation/matters/<mid>/engagements")
    def list_matter_engagements(mid):
        auth(READ_SET)
        get_matter(mid)
        records = apply_filters(
            [e for e in store.engagements.values() if e["matter_id"] == mid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("engagement", r) for r in page], limit, offset, total)

    @app.get("/litigation/engagements")
    def list_engagements():
        auth(READ_SET)
        records = apply_filters(
            store.engagements.values(),
            [
                ("firm_id", request.args.get("firm_id")),
                ("matter_id", request.args.get("matter_id")),
                ("approved_by_user_id", request.args.get("approved_by_user_id")),
                ("supersedes_engagement_id", request.args.get("supersedes_engagement_id")),
                ("status", request.args.get("status")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("engagement", r) for r in page], limit, offset, total)

    @app.get("/litigation/engagements/<eid>")
    def get_one_engagement(eid):
        auth(READ_SET)
        return ok_object(serialize("engagement", get_engagement(eid)))

    @app.patch("/litigation/engagements/<eid>")
    def patch_engagement(eid):
        auth(LC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] not in ("PROPOSED", "APPROVED"):
            raise_err(ERR_INVALID_STATE, "The engagement letter may be updated only while PROPOSED or APPROVED.")
        check_shape_23(body, {"engagement_letter_executed": {"type": "bool"}})
        if "engagement_letter_executed" in body:
            eng["engagement_letter_executed"] = body["engagement_letter_executed"]
        touch(eng)
        return ok_object(serialize("engagement", eng))

    @app.post("/litigation/engagements/<eid>/approve")
    def approve_engagement(eid):
        uid, _ = auth(DGC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] != "PROPOSED":
            raise_err(ERR_INVALID_STATE, "Only a PROPOSED engagement may be approved.")
        matter = store.matters.get(eng["matter_id"])
        if matter is None or matter["status"] not in ("STAFFING", "ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter must be in STAFFING, ACTIVE or REOPENED.")
        # (7) segregation of duties for LEAD_COUNSEL proposals
        if eng["role_type"] == "LEAD_COUNSEL" and uid == matter["owning_counsel_id"]:
            raise_err(
                ERR_SEGREGATION_OF_DUTIES,
                "The owning counsel may not approve a LEAD_COUNSEL engagement.",
            )
        # (16) firm panel and conflict state
        firm = store.firms.get(eng["firm_id"])
        if firm is None or firm["panel_status"] != "APPROVED":
            raise_err(ERR_REFERENCE_STATE_INVALID, "The firm must be panel-APPROVED.")
        if firm["conflict_check_status"] not in ("CLEARED", "WAIVED"):
            raise_err(ERR_REFERENCE_STATE_INVALID, "The firm conflicts must be CLEARED or WAIVED.")
        # (17) rate cap
        if eng["fee_arrangement"] in ("HOURLY", "HYBRID"):
            rate = eng.get("proposed_rate_cents")
            if rate is not None and rate > firm["blended_rate_cap_cents"]:
                raise_err(ERR_RATE_CAP_EXCEEDED, "proposed_rate_cents exceeds the firm blended rate cap.")
        reject_extra_fields(body, ())
        eng["status"] = "APPROVED"
        eng["approved_by_user_id"] = uid
        touch(eng)
        sup_id = eng.get("supersedes_engagement_id")
        if sup_id:
            prior = store.engagements.get(sup_id)
            if prior is not None and prior["status"] in ("ACTIVE", "SUSPENDED"):
                prior["status"] = "TERMINATED"
                touch(prior)
        return ok_object(serialize("engagement", eng))

    @app.post("/litigation/engagements/<eid>/reject")
    def reject_engagement(eid):
        auth(DGC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] != "PROPOSED":
            raise_err(ERR_INVALID_STATE, "Only a PROPOSED engagement may be rejected.")
        reject_extra_fields(body, ())
        eng["status"] = "REJECTED"
        touch(eng)
        return ok_object(serialize("engagement", eng))

    @app.post("/litigation/engagements/<eid>/activate")
    def activate_engagement(eid):
        auth(LC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] != "APPROVED":
            raise_err(ERR_INVALID_STATE, "Only an APPROVED engagement may be activated.")
        matter = store.matters.get(eng["matter_id"])
        if matter is None or matter["status"] not in ("STAFFING", "ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter must be in STAFFING, ACTIVE or REOPENED.")
        # (24) the engagement letter must be executed
        if not eng.get("engagement_letter_executed", False):
            raise_err(ERR_ENGAGEMENT_LETTER_REQUIRED, "The engagement letter must be executed first.")
        reject_extra_fields(body, ())
        eng["status"] = "ACTIVE"
        touch(eng)
        return ok_object(serialize("engagement", eng))

    @app.post("/litigation/engagements/<eid>/suspend")
    def suspend_engagement(eid):
        auth(LC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "Only an ACTIVE engagement may be suspended.")
        reject_extra_fields(body, ())
        eng["status"] = "SUSPENDED"
        touch(eng)
        return ok_object(serialize("engagement", eng))

    @app.post("/litigation/engagements/<eid>/reinstate")
    def reinstate_engagement(eid):
        auth(LC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] != "SUSPENDED":
            raise_err(ERR_INVALID_STATE, "Only a SUSPENDED engagement may be reinstated.")
        matter = store.matters.get(eng["matter_id"])
        if matter is None or matter["status"] not in ("ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "Cannot reinstate while the matter is not ACTIVE or REOPENED.")
        reject_extra_fields(body, ())
        eng["status"] = "ACTIVE"
        touch(eng)
        return ok_object(serialize("engagement", eng))

    @app.post("/litigation/engagements/<eid>/terminate")
    def terminate_engagement(eid):
        auth(DGC)
        eng = get_engagement(eid)
        body = get_body()
        if eng["status"] not in ("ACTIVE", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "Only an ACTIVE or SUSPENDED engagement may be terminated.")
        reject_extra_fields(body, ())
        eng["status"] = "TERMINATED"
        touch(eng)
        return ok_object(serialize("engagement", eng))

    # ---------------------------------------------------------------- budgets
    @app.post("/litigation/matters/<mid>/budgets")
    def create_budget(mid):
        auth(LC)
        matter = get_matter(mid)
        body = get_body()
        # (4) body FK existence
        if isinstance(body, dict):
            prior_id = body.get("prior_version_id")
            if isinstance(prior_id, str) and prior_id != "" and prior_id not in store.budgets:
                raise_err(ERR_REFERENCE_NOT_FOUND, "prior_version_id does not name a budget.")
        # (11) scalar + cross-field constraints
        check_constraints_11(body, BUDGET_CREATE_SPEC)
        if isinstance(body, dict):
            lifecycle = body.get("lifecycle_budget_cents")
            fy = body.get("fy_budget_cents")
            if _is_int(lifecycle) and _is_int(fy) and fy > lifecycle:
                raise_err(ERR_FIELD_CONSTRAINT, "fy_budget_cents must not exceed lifecycle_budget_cents.")
        # (15) prior version must belong to the same matter
        if isinstance(body, dict):
            prior_id = body.get("prior_version_id")
            if isinstance(prior_id, str) and prior_id in store.budgets:
                if store.budgets[prior_id]["matter_id"] != mid:
                    raise_err(
                        ERR_CROSS_REFERENCE_MISMATCH,
                        "prior_version_id must name a budget of the same matter.",
                    )
        # (22) optimistic concurrency on the matter version
        if isinstance(body, dict):
            expected = body.get("expected_matter_version")
            if _is_int(expected) and expected != matter["version"]:
                raise_err(ERR_STALE_MATTER_VERSION, "expected_matter_version does not match the matter version.")
        # (23) request shape
        check_shape_23(body, BUDGET_CREATE_SPEC)
        rec = new_common(
            {
                "matter_id": mid,
                "fiscal_year": body["fiscal_year"],
                "lifecycle_budget_cents": body["lifecycle_budget_cents"],
                "fy_budget_cents": body["fy_budget_cents"],
                "status": "DRAFT",
                "submitted_by_user_id": None,
                "approved_by_user_id": None,
                "utilization_pct": 0,
                "prior_version_id": body.get("prior_version_id"),
            }
        )
        store.budgets[rec["id"]] = rec
        touch(matter)
        return ok_object(serialize("budget", rec), 201)

    @app.get("/litigation/matters/<mid>/budgets")
    def list_matter_budgets(mid):
        auth(READ_SET)
        get_matter(mid)
        records = apply_filters(
            [b for b in store.budgets.values() if b["matter_id"] == mid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("budget", r) for r in page], limit, offset, total)

    @app.get("/litigation/budgets")
    def list_budgets():
        auth(READ_SET)
        records = apply_filters(
            store.budgets.values(),
            [
                ("matter_id", request.args.get("matter_id")),
                ("submitted_by_user_id", request.args.get("submitted_by_user_id")),
                ("approved_by_user_id", request.args.get("approved_by_user_id")),
                ("prior_version_id", request.args.get("prior_version_id")),
                ("status", request.args.get("status")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("budget", r) for r in page], limit, offset, total)

    @app.get("/litigation/budgets/<bid>")
    def get_one_budget(bid):
        auth(READ_SET)
        return ok_object(serialize("budget", get_budget(bid)))

    @app.post("/litigation/budgets/<bid>/submit")
    def submit_budget(bid):
        uid, _ = auth(LC)
        budget = get_budget(bid)
        body = get_body()
        if budget["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT budget may be submitted.")
        matter = store.matters.get(budget["matter_id"])
        if matter is None or matter["status"] not in ("ASSESSMENT", "STAFFING", "ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter must be in ASSESSMENT, STAFFING, ACTIVE or REOPENED.")
        reject_extra_fields(body, ())
        budget["status"] = "SUBMITTED"
        budget["submitted_by_user_id"] = uid
        touch(budget)
        return ok_object(serialize("budget", budget))

    @app.post("/litigation/budgets/<bid>/approve")
    def approve_budget(bid):
        uid, _ = auth(FBP)
        budget = get_budget(bid)
        body = get_body()
        if budget["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED budget may be approved.")
        # (7) segregation of duties
        if uid == budget["submitted_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES, "The budget submitter may not approve it.")
        matter = store.matters.get(budget["matter_id"])
        # (20) fiscal gates: unique-active invariant. The budget named by
        # prior_version_id is about to be superseded by this approval and so
        # does not count against the invariant.
        prior_id = budget.get("prior_version_id")
        for other in store.budgets.values():
            if (
                other["matter_id"] == budget["matter_id"]
                and other["id"] != budget["id"]
                and other["id"] != prior_id
                and other["status"] == "APPROVED"
            ):
                raise_err(ERR_BUDGET_EXCEEDED, "Another budget for this matter is already APPROVED.")
        accrued = matter["accrued_to_date_cents"] if matter is not None else 0
        if budget["fy_budget_cents"] < accrued:
            raise_err(ERR_BUDGET_EXCEEDED, "fy_budget_cents is below already-posted accruals.")
        reject_extra_fields(body, ())
        budget["status"] = "APPROVED"
        budget["approved_by_user_id"] = uid
        if matter is not None:
            budget["utilization_pct"] = calc.compute_utilization_pct(
                matter["accrued_to_date_cents"], budget["fy_budget_cents"]
            )
        touch(budget)
        prior_id = budget.get("prior_version_id")
        if prior_id:
            prior = store.budgets.get(prior_id)
            if prior is not None and prior["status"] == "APPROVED":
                prior["status"] = "SUPERSEDED"
                touch(prior)
        if matter is not None:
            calc.recompute_posture_bump(matter)
        return ok_object(serialize("budget", budget))

    @app.post("/litigation/budgets/<bid>/reject")
    def reject_budget(bid):
        auth(FBP)
        budget = get_budget(bid)
        body = get_body()
        if budget["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED budget may be rejected.")
        reject_extra_fields(body, ())
        budget["status"] = "REJECTED"
        touch(budget)
        return ok_object(serialize("budget", budget))

    # ------------------------------------------------------------ accruals
    @app.post("/litigation/matters/<mid>/accrual-entries")
    def create_accrual(mid):
        auth(LC)
        get_matter(mid)
        body = get_body()
        # (4) body FK existence
        if isinstance(body, dict):
            eng_id = body.get("engagement_id")
            if isinstance(eng_id, str) and eng_id != "" and eng_id not in store.engagements:
                raise_err(ERR_REFERENCE_NOT_FOUND, "engagement_id does not name an engagement.")
            rev_id = body.get("reverses_entry_id")
            if isinstance(rev_id, str) and rev_id != "" and rev_id not in store.accruals:
                raise_err(ERR_REFERENCE_NOT_FOUND, "reverses_entry_id does not name an accrual entry.")
        # (11) scalar constraints: enum, sign by kind, period format
        check_constraints_11(body, ACCRUAL_CREATE_SPEC)
        if isinstance(body, dict):
            kind = body.get("entry_kind")
            amount = body.get("amount_cents")
            if kind in ("ACCRUAL", "INVOICE") and _is_int(amount) and amount <= 0:
                raise_err(ERR_FIELD_CONSTRAINT, "ACCRUAL and INVOICE amounts must be positive.")
            if kind == "ADJUSTMENT" and _is_int(amount) and amount >= 0:
                raise_err(ERR_FIELD_CONSTRAINT, "ADJUSTMENT amounts must be negative.")
            period = body.get("period")
            if isinstance(period, str) and period != "" and not PERIOD_RE.match(period):
                raise_err(ERR_FIELD_CONSTRAINT, "period must be in YYYY-MM form.")
        # (23) request shape; reverses_entry_id is required for ADJUSTMENT
        check_shape_23(
            body,
            ACCRUAL_CREATE_SPEC,
            conditional_required={
                "reverses_entry_id": lambda b: b.get("entry_kind") == "ADJUSTMENT",
            },
        )
        rec = {
            "id": new_id(),
            "created_at": fmt_ts(wall_now()),
            "_seq": next_seq(),
            "matter_id": mid,
            "engagement_id": body["engagement_id"],
            "period": body["period"],
            "entry_kind": body["entry_kind"],
            "amount_cents": body["amount_cents"],
            "status": "DRAFT",
            "submitted_at": None,
            "reverses_entry_id": body.get("reverses_entry_id"),
        }
        store.accruals[rec["id"]] = rec
        return ok_object(serialize("accrual", rec), 201)

    @app.get("/litigation/matters/<mid>/accrual-entries")
    def list_matter_accruals(mid):
        auth(READ_SET)
        get_matter(mid)
        records = apply_filters(
            [a for a in store.accruals.values() if a["matter_id"] == mid],
            [
                ("status", request.args.get("status")),
                ("entry_kind", request.args.get("entry_kind")),
                ("period", request.args.get("period")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("accrual", r) for r in page], limit, offset, total)

    @app.get("/litigation/engagements/<eid>/accrual-entries")
    def list_engagement_accruals(eid):
        auth(READ_SET)
        get_engagement(eid)
        records = [a for a in store.accruals.values() if a["engagement_id"] == eid]
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("accrual", r) for r in page], limit, offset, total)

    @app.get("/litigation/accrual-entries")
    def list_accruals():
        auth(READ_SET)
        records = apply_filters(
            store.accruals.values(),
            [
                ("matter_id", request.args.get("matter_id")),
                ("engagement_id", request.args.get("engagement_id")),
                ("reverses_entry_id", request.args.get("reverses_entry_id")),
                ("status", request.args.get("status")),
                ("entry_kind", request.args.get("entry_kind")),
                ("period", request.args.get("period")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("accrual", r) for r in page], limit, offset, total)

    @app.get("/litigation/accrual-entries/<aid>")
    def get_one_accrual(aid):
        auth(READ_SET)
        return ok_object(serialize("accrual", get_accrual(aid)))

    @app.post("/litigation/accrual-entries/<aid>/submit")
    def submit_accrual(aid):
        auth(LC)
        entry = get_accrual(aid)
        body = get_body()
        if entry["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT entry may be submitted.")
        matter = store.matters.get(entry["matter_id"])
        if matter is None or matter["status"] not in ("STAFFING", "ACTIVE", "REOPENED", "SETTLEMENT_PENDING"):
            raise_err(ERR_INVALID_STATE, "The linked matter is not in a submittable state.")
        eng = store.engagements.get(entry["engagement_id"])
        if eng is None or eng["status"] not in ("ACTIVE", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "The linked engagement must be ACTIVE or SUSPENDED.")
        # (9) posture gate
        if matter["posture"] == "FROZEN":
            raise_err(ERR_MATTER_POSTURE_FROZEN, "The matter posture is FROZEN.")
        reject_extra_fields(body, ())
        entry["status"] = "SUBMITTED"
        entry["submitted_at"] = store.clock
        return ok_object(serialize("accrual", entry))

    @app.post("/litigation/accrual-entries/<aid>/post")
    def post_accrual(aid):
        auth(FBP)
        entry = get_accrual(aid)
        body = get_body()
        if entry["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED entry may be posted.")
        if entry["entry_kind"] in ("ACCRUAL", "INVOICE"):
            # (12) one POSTED entry per (engagement_id, period, entry_kind)
            for other in store.accruals.values():
                if (
                    other["id"] != entry["id"]
                    and other["engagement_id"] == entry["engagement_id"]
                    and other["period"] == entry["period"]
                    and other["entry_kind"] == entry["entry_kind"]
                    and other["status"] == "POSTED"
                ):
                    raise_err(ERR_DUPLICATE, "A POSTED entry already exists for this engagement, period and kind.")
        else:
            # ADJUSTMENT: magnitude gate (11) then reversed-entry state (16)
            reversed_entry = store.accruals.get(entry.get("reverses_entry_id") or "")
            if reversed_entry is not None and abs(entry["amount_cents"]) > reversed_entry["amount_cents"]:
                raise_err(ERR_FIELD_CONSTRAINT, "The adjustment amount exceeds the reversed entry amount.")
            if reversed_entry is None or reversed_entry["status"] != "POSTED":
                raise_err(ERR_REFERENCE_STATE_INVALID, "reverses_entry_id must reference a POSTED entry.")
        reject_extra_fields(body, ())
        entry["status"] = "POSTED"
        if entry["entry_kind"] == "ADJUSTMENT":
            reversed_entry = store.accruals[entry["reverses_entry_id"]]
            reversed_entry["status"] = "VOID"
        matter = store.matters.get(entry["matter_id"])
        if matter is not None:
            calc.ledger_sync(matter)
        return ok_object(serialize("accrual", entry))

    @app.post("/litigation/accrual-entries/<aid>/void")
    def void_accrual(aid):
        auth(FBP)
        entry = get_accrual(aid)
        body = get_body()
        if entry["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED entry may be voided.")
        reject_extra_fields(body, ())
        entry["status"] = "VOID"
        return ok_object(serialize("accrual", entry))
