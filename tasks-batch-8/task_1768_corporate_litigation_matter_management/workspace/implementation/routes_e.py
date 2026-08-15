"""Routes: settlement authority policies, settlement requests, payment requests, portfolio report."""
from flask import request

import calc
from db import new_common, parse_dt, store, touch
from errors import (
    ERR_BUDGET_EXCEEDED,
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_DUPLICATE,
    ERR_FIELD_CONSTRAINT,
    ERR_INVALID_STATE,
    ERR_MATTER_POSTURE_FROZEN,
    ERR_NOT_FOUND,
    ERR_NOT_MATTER_OWNER,
    ERR_NO_APPROVED_BUDGET,
    ERR_PAYMENT_RAIL_STATE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENCE_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SETTLEMENT_AUTHORITY,
    ERR_STALE_MATTER_VERSION,
    raise_err,
)
from middleware import READ_SET_CFO, apply_filters, auth, get_body, paginate, parse_bool_filter
from response import ok_list, ok_object
from routes_b import get_matter
from serializers import serialize
from validation import check_constraints_11, check_shape_23, reject_extra_fields

LC = ("LitigationCounsel",)
DGC = ("DeputyGeneralCounsel",)
GC = ("GeneralCounsel",)
FBP = ("FinanceBusinessPartner",)
SETTLEMENT_APPROVERS = ("DeputyGeneralCounsel", "GeneralCounsel", "ChiefFinancialOfficer", "BoardCommittee")
PORTFOLIO_ROLES = ("GeneralCounsel", "DeputyGeneralCounsel", "ChiefFinancialOfficer", "FinanceBusinessPartner")

TIERS = ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
APPROVER_ROLES = ("DeputyGeneralCounsel", "GeneralCounsel", "ChiefFinancialOfficer", "BoardCommittee")
SETTLEMENT_KINDS = ("PAY_OUT", "PAY_IN", "NON_MONETARY")
PAYMENT_KINDS = ("SETTLEMENT", "JUDGMENT", "COST_AWARD")

POLICY_CREATE_SPEC = {
    "tier": {"type": "enum", "enum": TIERS, "required": True},
    "approver_role": {"type": "enum", "enum": APPROVER_ROLES, "required": True},
    "max_single_amount_cents": {"type": "int", "required": True, "positive": True},
    "dual_approval_required_over_cents": {"type": "int", "required": True, "positive": True},
    "is_active": {"type": "bool"},
}

SETTLEMENT_CREATE_SPEC = {
    "proposed_amount_cents": {"type": "int", "required": True, "positive": True},
    "settlement_kind": {"type": "enum", "enum": SETTLEMENT_KINDS, "required": True},
    "terms_summary": {"type": "str", "required": True},
    "expires_at": {"type": "datetime", "required": True},
    "expected_matter_version": {"type": "int", "required": True},
}

PAYMENT_CREATE_SPEC = {
    "payment_kind": {"type": "enum", "enum": PAYMENT_KINDS, "required": True},
    "amount_cents": {"type": "int", "required": True, "positive": True},
    "payee_name": {"type": "str", "required": True},
    "settlement_request_id": {"type": "str"},
}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_settlement(sid):
    rec = store.settlements.get(sid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Settlement request %s does not exist." % sid)
    return rec


def get_payment(pid):
    rec = store.payments.get(pid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Payment request %s does not exist." % pid)
    return rec


def register(app):

    # ------------------------------------------------------- authority policy
    @app.post("/litigation/settlement-authority-policies")
    def create_policy():
        auth(GC)
        body = get_body()
        # (11) scalar + cross-field constraints
        check_constraints_11(body, POLICY_CREATE_SPEC)
        if isinstance(body, dict):
            single = body.get("max_single_amount_cents")
            dual = body.get("dual_approval_required_over_cents")
            if _is_int(single) and _is_int(dual) and dual < single:
                raise_err(
                    ERR_FIELD_CONSTRAINT,
                    "dual_approval_required_over_cents must be >= max_single_amount_cents.",
                )
        # (12) tier unique among active rows
        if isinstance(body, dict) and body.get("tier") in TIERS:
            new_active = body.get("is_active", True)
            if new_active is True or new_active is None:
                for p in store.policies.values():
                    if p["tier"] == body["tier"] and p.get("is_active", True):
                        raise_err(ERR_DUPLICATE, "An active policy row already exists for this tier.")
        check_shape_23(body, POLICY_CREATE_SPEC)
        rec = new_common(
            {
                "tier": body["tier"],
                "approver_role": body["approver_role"],
                "max_single_amount_cents": body["max_single_amount_cents"],
                "dual_approval_required_over_cents": body["dual_approval_required_over_cents"],
                "is_active": body.get("is_active", True),
            }
        )
        store.policies[rec["id"]] = rec
        return ok_object(serialize("policy", rec), 201)

    @app.get("/litigation/settlement-authority-policies")
    def list_policies():
        auth(READ_SET_CFO)
        records = apply_filters(
            store.policies.values(),
            [
                ("tier", request.args.get("tier")),
                ("is_active", parse_bool_filter(request.args.get("is_active"))),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("policy", r) for r in page], limit, offset, total)

    @app.get("/litigation/settlement-authority-policies/<pid>")
    def get_one_policy(pid):
        auth(READ_SET_CFO)
        rec = store.policies.get(pid)
        if rec is None:
            raise_err(ERR_NOT_FOUND, "Settlement authority policy %s does not exist." % pid)
        return ok_object(serialize("policy", rec))

    # -------------------------------------------------------- settlement flow
    @app.post("/litigation/matters/<mid>/settlement-requests")
    def create_settlement(mid):
        auth(LC)
        matter = get_matter(mid)
        body = get_body()
        # (11) scalar constraints
        check_constraints_11(body, SETTLEMENT_CREATE_SPEC)
        # (22) optimistic concurrency on the matter version
        if isinstance(body, dict):
            expected = body.get("expected_matter_version")
            if _is_int(expected) and expected != matter["version"]:
                raise_err(ERR_STALE_MATTER_VERSION, "expected_matter_version does not match the matter version.")
        # (23) request shape
        check_shape_23(body, SETTLEMENT_CREATE_SPEC)
        rec = new_common(
            {
                "matter_id": mid,
                "proposed_amount_cents": body["proposed_amount_cents"],
                "settlement_kind": body["settlement_kind"],
                "status": "DRAFT",
                "counter_amount_cents": None,
                "requested_by_user_id": None,
                "approved_by_user_ids": [],
                "_approved_roles": [],
                "authority_tier_at_submission": None,
                "terms_summary": body["terms_summary"],
                "expires_at": parse_dt(body["expires_at"]),
            }
        )
        store.settlements[rec["id"]] = rec
        touch(matter)
        return ok_object(serialize("settlement", rec), 201)

    @app.get("/litigation/matters/<mid>/settlement-requests")
    def list_matter_settlements(mid):
        auth(READ_SET_CFO)
        get_matter(mid)
        records = apply_filters(
            [s for s in store.settlements.values() if s["matter_id"] == mid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("settlement", r) for r in page], limit, offset, total)

    @app.get("/litigation/settlement-requests")
    def list_settlements():
        auth(READ_SET_CFO)
        records = apply_filters(
            store.settlements.values(),
            [
                ("matter_id", request.args.get("matter_id")),
                ("requested_by_user_id", request.args.get("requested_by_user_id")),
                ("status", request.args.get("status")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("settlement", r) for r in page], limit, offset, total)

    @app.get("/litigation/settlement-requests/<sid>")
    def get_one_settlement(sid):
        auth(READ_SET_CFO)
        return ok_object(serialize("settlement", get_settlement(sid)))

    @app.post("/litigation/settlement-requests/<sid>/submit")
    def submit_settlement(sid):
        uid, _ = auth(LC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT settlement request may be submitted.")
        matter = store.matters.get(sr["matter_id"])
        if matter is None or matter["status"] not in ("ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter must be ACTIVE or REOPENED.")
        # (6) owner-gated
        if uid != matter["owning_counsel_id"]:
            raise_err(ERR_NOT_MATTER_OWNER, "Only the owning counsel may submit a settlement request.")
        # (9) posture gate
        if matter["posture"] == "FROZEN":
            raise_err(ERR_MATTER_POSTURE_FROZEN, "The matter posture is FROZEN.")
        # (11) non-monetary settlements carry a nominal one-cent amount
        if sr["settlement_kind"] == "NON_MONETARY" and sr["proposed_amount_cents"] != 1:
            raise_err(ERR_FIELD_CONSTRAINT, "A NON_MONETARY settlement must carry proposed_amount_cents of exactly 1.")
        reject_extra_fields(body, ())
        sr["status"] = "SUBMITTED"
        sr["requested_by_user_id"] = uid
        sr["authority_tier_at_submission"] = matter["exposure_tier"]
        touch(sr)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/begin-review")
    def begin_review_settlement(sid):
        auth(DGC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED settlement request may enter review.")
        reject_extra_fields(body, ())
        sr["status"] = "UNDER_REVIEW"
        touch(sr)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/approve")
    def approve_settlement(sid):
        uid, role = auth(SETTLEMENT_APPROVERS)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "Only an UNDER_REVIEW settlement request may be approved.")
        # (7) segregation of duties: requester and prior approvers are turned away
        if uid == sr["requested_by_user_id"] or uid in sr["approved_by_user_ids"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES, "The requester or a prior approver may not approve.")
        # (19) settlement authority routing against the snapshot tier
        policy = calc.active_policy_for_tier(sr["authority_tier_at_submission"])
        if policy is None:
            raise_err(ERR_SETTLEMENT_AUTHORITY, "No active authority policy for the snapshot tier.")
        amount = sr["proposed_amount_cents"]
        if amount <= policy["max_single_amount_cents"]:
            required = 1
        elif amount <= policy["dual_approval_required_over_cents"]:
            required = 2
        else:
            raise_err(ERR_SETTLEMENT_AUTHORITY, "The amount exceeds even the dual-approval threshold.")
        prior_roles = sr.get("_approved_roles", [])
        if not sr["approved_by_user_ids"]:
            if role != policy["approver_role"]:
                raise_err(ERR_SETTLEMENT_AUTHORITY, "The first approval must come from the policy-designated role.")
        else:
            first_rank = calc.ROLE_RANK[prior_roles[0]]
            if calc.ROLE_RANK[role] <= first_rank:
                raise_err(ERR_SETTLEMENT_AUTHORITY, "The second approver must rank strictly above the first.")
        reject_extra_fields(body, ())
        sr["approved_by_user_ids"].append(uid)
        sr["_approved_roles"].append(role)
        if len(sr["approved_by_user_ids"]) >= required:
            sr["status"] = "APPROVED"
        touch(sr)
        if sr["status"] == "APPROVED":
            matter = store.matters.get(sr["matter_id"])
            if matter is not None:
                calc.matter_to_settlement_pending(matter)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/counter")
    def counter_settlement(sid):
        auth(DGC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "Only an UNDER_REVIEW settlement request may be countered.")
        # (11) the counter must be positive and differ from the ask
        counter = body.get("counter_amount_cents") if isinstance(body, dict) else None
        if _is_int(counter):
            if counter <= 0:
                raise_err(ERR_FIELD_CONSTRAINT, "counter_amount_cents must be positive.")
            if counter == sr["proposed_amount_cents"]:
                raise_err(ERR_FIELD_CONSTRAINT, "counter_amount_cents must differ from the current ask.")
        check_shape_23(body, {"counter_amount_cents": {"type": "int", "required": True}})
        sr["status"] = "COUNTERED"
        sr["counter_amount_cents"] = body["counter_amount_cents"]
        sr["approved_by_user_ids"] = []
        sr["_approved_roles"] = []
        touch(sr)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/accept-counter")
    def accept_counter_settlement(sid):
        uid, _ = auth(LC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] != "COUNTERED":
            raise_err(ERR_INVALID_STATE, "Only a COUNTERED settlement request may accept its counter.")
        # (6) only the requesting counsel may accept the counter
        if uid != sr["requested_by_user_id"]:
            raise_err(ERR_NOT_MATTER_OWNER, "Only the requesting counsel may accept the counter.")
        reject_extra_fields(body, ())
        sr["status"] = "UNDER_REVIEW"
        sr["proposed_amount_cents"] = sr["counter_amount_cents"]
        sr["counter_amount_cents"] = None
        matter = store.matters.get(sr["matter_id"])
        sr["authority_tier_at_submission"] = matter["exposure_tier"] if matter is not None else None
        touch(sr)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/reject")
    def reject_settlement(sid):
        auth(GC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] not in ("UNDER_REVIEW", "COUNTERED"):
            raise_err(ERR_INVALID_STATE, "Only an UNDER_REVIEW or COUNTERED settlement request may be rejected.")
        reject_extra_fields(body, ())
        sr["status"] = "REJECTED"
        sr["counter_amount_cents"] = None
        touch(sr)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/execute")
    def execute_settlement(sid):
        auth(GC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] != "APPROVED":
            raise_err(ERR_INVALID_STATE, "Only an APPROVED settlement request may be executed.")
        matter = store.matters.get(sr["matter_id"])
        if matter is None or matter["status"] != "SETTLEMENT_PENDING":
            raise_err(ERR_INVALID_STATE, "The linked matter must be SETTLEMENT_PENDING.")
        # (16) a FINANCE_APPROVED payment must be staged before execution
        staged = any(
            p["settlement_request_id"] == sid and p["status"] == "FINANCE_APPROVED"
            for p in store.payments.values()
        )
        if not staged:
            raise_err(ERR_REFERENCE_STATE_INVALID, "A FINANCE_APPROVED payment must be staged before execution.")
        reject_extra_fields(body, ())
        sr["status"] = "EXECUTED"
        touch(sr)
        calc.matter_resolution_cascade(matter, "SETTLEMENT", vacate_deadlines=False)
        return ok_object(serialize("settlement", sr))

    @app.post("/litigation/settlement-requests/<sid>/withdraw")
    def withdraw_settlement(sid):
        uid, _ = auth(LC)
        sr = get_settlement(sid)
        body = get_body()
        if sr["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "COUNTERED"):
            raise_err(ERR_INVALID_STATE, "This settlement request may not be withdrawn from its current state.")
        # (6) post-submission states may be withdrawn only by the requester
        if sr["status"] != "DRAFT" and uid != sr["requested_by_user_id"]:
            raise_err(ERR_NOT_MATTER_OWNER, "Only the requesting counsel may withdraw this request.")
        reject_extra_fields(body, ())
        sr["status"] = "WITHDRAWN"
        sr["counter_amount_cents"] = None
        touch(sr)
        return ok_object(serialize("settlement", sr))

    # ------------------------------------------------------------ payments
    @app.post("/litigation/matters/<mid>/payment-requests")
    def create_payment(mid):
        auth(LC)
        get_matter(mid)
        body = get_body()
        # (4) body FK existence
        settlement = None
        if isinstance(body, dict):
            sr_id = body.get("settlement_request_id")
            if isinstance(sr_id, str) and sr_id != "":
                settlement = store.settlements.get(sr_id)
                if settlement is None:
                    raise_err(ERR_REFERENCE_NOT_FOUND, "settlement_request_id does not name a settlement request.")
        # (11) scalar constraints
        check_constraints_11(body, PAYMENT_CREATE_SPEC)
        # (15) the settlement must belong to the same matter
        if settlement is not None and settlement["matter_id"] != mid:
            raise_err(ERR_CROSS_REFERENCE_MISMATCH, "settlement_request_id must name a settlement of the same matter.")
        # (23) request shape; settlement_request_id required for SETTLEMENT payments
        check_shape_23(
            body,
            PAYMENT_CREATE_SPEC,
            conditional_required={
                "settlement_request_id": lambda b: b.get("payment_kind") == "SETTLEMENT",
            },
        )
        rec = new_common(
            {
                "matter_id": mid,
                "settlement_request_id": body.get("settlement_request_id"),
                "payment_kind": body["payment_kind"],
                "amount_cents": body["amount_cents"],
                "payee_name": body["payee_name"],
                "status": "DRAFT",
                "payment_status": "NOT_SENT",
                "submitted_by_user_id": None,
                "approved_by_user_id": None,
                "disbursed_at": None,
            }
        )
        store.payments[rec["id"]] = rec
        return ok_object(serialize("payment", rec), 201)

    @app.get("/litigation/matters/<mid>/payment-requests")
    def list_matter_payments(mid):
        auth(READ_SET_CFO)
        get_matter(mid)
        records = apply_filters(
            [p for p in store.payments.values() if p["matter_id"] == mid],
            [
                ("status", request.args.get("status")),
                ("payment_kind", request.args.get("payment_kind")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("payment", r) for r in page], limit, offset, total)

    @app.get("/litigation/settlement-requests/<sid>/payment-requests")
    def list_settlement_payments(sid):
        auth(READ_SET_CFO)
        get_settlement(sid)
        records = [p for p in store.payments.values() if p["settlement_request_id"] == sid]
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("payment", r) for r in page], limit, offset, total)

    @app.get("/litigation/payment-requests")
    def list_payments():
        auth(READ_SET_CFO)
        records = apply_filters(
            store.payments.values(),
            [
                ("matter_id", request.args.get("matter_id")),
                ("settlement_request_id", request.args.get("settlement_request_id")),
                ("submitted_by_user_id", request.args.get("submitted_by_user_id")),
                ("approved_by_user_id", request.args.get("approved_by_user_id")),
                ("status", request.args.get("status")),
                ("payment_kind", request.args.get("payment_kind")),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("payment", r) for r in page], limit, offset, total)

    @app.get("/litigation/payment-requests/<pid>")
    def get_one_payment(pid):
        auth(READ_SET_CFO)
        return ok_object(serialize("payment", get_payment(pid)))

    @app.post("/litigation/payment-requests/<pid>/submit")
    def submit_payment(pid):
        uid, _ = auth(LC)
        pr = get_payment(pid)
        body = get_body()
        if pr["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT payment request may be submitted.")
        matter = store.matters.get(pr["matter_id"])
        if matter is None or matter["status"] not in ("SETTLEMENT_PENDING", "RESOLVED", "ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter is not in a payable state.")
        if pr["payment_kind"] == "JUDGMENT" and not (
            matter["status"] == "RESOLVED" and matter["resolution_type"] == "JUDGMENT"
        ):
            raise_err(ERR_INVALID_STATE, "A JUDGMENT payment requires the matter RESOLVED with resolution_type JUDGMENT.")
        # (11) a SETTLEMENT payment must equal the settlement's executed amount
        settlement = None
        if pr["payment_kind"] == "SETTLEMENT":
            settlement = store.settlements.get(pr.get("settlement_request_id") or "")
            if settlement is not None and pr["amount_cents"] != settlement["proposed_amount_cents"]:
                raise_err(ERR_FIELD_CONSTRAINT, "A SETTLEMENT payment must equal the settlement amount exactly.")
        # (16) the linked settlement must be APPROVED
        if pr["payment_kind"] == "SETTLEMENT":
            if settlement is None or settlement["status"] != "APPROVED":
                raise_err(ERR_REFERENCE_STATE_INVALID, "The linked settlement request must be APPROVED.")
        reject_extra_fields(body, ())
        pr["status"] = "SUBMITTED"
        pr["submitted_by_user_id"] = uid
        touch(pr)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/finance-approve")
    def finance_approve_payment(pid):
        uid, _ = auth(FBP)
        pr = get_payment(pid)
        body = get_body()
        if pr["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED payment request may be finance-approved.")
        # (7) segregation of duties
        if uid == pr["submitted_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES, "The payment submitter may not finance-approve it.")
        matter = store.matters.get(pr["matter_id"])
        budget = calc.approved_budget_of(pr["matter_id"])
        # (21) an APPROVED budget is required
        if budget is None:
            raise_err(ERR_NO_APPROVED_BUDGET, "No APPROVED budget exists for this matter.")
        # (20) the payment must fit within fiscal-year headroom
        accrued = matter["accrued_to_date_cents"] if matter is not None else 0
        if pr["amount_cents"] > budget["fy_budget_cents"] - accrued:
            raise_err(ERR_BUDGET_EXCEEDED, "The payment exceeds the remaining fiscal-year budget.")
        reject_extra_fields(body, ())
        pr["status"] = "FINANCE_APPROVED"
        pr["approved_by_user_id"] = uid
        touch(pr)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/disburse")
    def disburse_payment(pid):
        auth(FBP)
        pr = get_payment(pid)
        body = get_body()
        if pr["status"] != "FINANCE_APPROVED":
            raise_err(ERR_INVALID_STATE, "Only a FINANCE_APPROVED payment request may be disbursed.")
        # (29) the rail must still read NOT_SENT
        if pr["payment_status"] != "NOT_SENT":
            raise_err(ERR_PAYMENT_RAIL_STATE, "The payment rail is not NOT_SENT.")
        reject_extra_fields(body, ())
        pr["status"] = "DISBURSED"
        pr["payment_status"] = "SENT"
        pr["disbursed_at"] = store.clock
        touch(pr)
        matter = store.matters.get(pr["matter_id"])
        if matter is not None:
            calc.ledger_sync(matter)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/confirm-receipt")
    def confirm_receipt_payment(pid):
        auth(FBP)
        pr = get_payment(pid)
        body = get_body()
        # (29) rail SENT -> CONFIRMED
        if pr["payment_status"] != "SENT":
            raise_err(ERR_PAYMENT_RAIL_STATE, "Only a SENT payment may be confirmed.")
        reject_extra_fields(body, ())
        pr["payment_status"] = "CONFIRMED"
        touch(pr)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/mark-returned")
    def mark_returned_payment(pid):
        auth(FBP)
        pr = get_payment(pid)
        body = get_body()
        # (29) rail SENT -> RETURNED
        if pr["payment_status"] != "SENT":
            raise_err(ERR_PAYMENT_RAIL_STATE, "Only a SENT payment may be marked returned.")
        reject_extra_fields(body, ())
        pr["payment_status"] = "RETURNED"
        touch(pr)
        matter = store.matters.get(pr["matter_id"])
        if matter is not None:
            calc.ledger_sync(matter)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/redisburse")
    def redisburse_payment(pid):
        auth(FBP)
        pr = get_payment(pid)
        body = get_body()
        # (29) rail RETURNED -> SENT while the request remains DISBURSED
        if pr["payment_status"] != "RETURNED" or pr["status"] != "DISBURSED":
            raise_err(ERR_PAYMENT_RAIL_STATE, "Only a RETURNED payment of a DISBURSED request may be redisbursed.")
        reject_extra_fields(body, ())
        pr["payment_status"] = "SENT"
        touch(pr)
        matter = store.matters.get(pr["matter_id"])
        if matter is not None:
            calc.ledger_sync(matter)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/reject")
    def reject_payment(pid):
        auth(FBP)
        pr = get_payment(pid)
        body = get_body()
        if pr["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED payment request may be rejected.")
        reject_extra_fields(body, ())
        pr["status"] = "REJECTED"
        touch(pr)
        return ok_object(serialize("payment", pr))

    @app.post("/litigation/payment-requests/<pid>/cancel")
    def cancel_payment(pid):
        uid, _ = auth(LC)
        pr = get_payment(pid)
        body = get_body()
        if pr["status"] not in ("DRAFT", "SUBMITTED"):
            raise_err(ERR_INVALID_STATE, "Only a DRAFT or SUBMITTED payment request may be cancelled.")
        # (6) a submitted request may be cancelled only by its submitter
        if pr["status"] == "SUBMITTED" and uid != pr["submitted_by_user_id"]:
            raise_err(ERR_NOT_MATTER_OWNER, "Only the submitter may cancel this payment request.")
        reject_extra_fields(body, ())
        pr["status"] = "CANCELLED"
        touch(pr)
        return ok_object(serialize("payment", pr))

    # -------------------------------------------------------------- portfolio
    @app.get("/litigation/reports/portfolio")
    def portfolio_report():
        auth(PORTFOLIO_ROLES)
        matter_type = request.args.get("matter_type")
        tier_filter = request.args.get("exposure_tier")
        matters = [
            m for m in store.matters.values()
            if (matter_type is None or m["matter_type"] == matter_type)
            and (tier_filter is None or m["exposure_tier"] == tier_filter)
        ]
        cohorts = []
        for tier in TIERS:
            cohort = [m for m in matters if m["exposure_tier"] == tier]
            resolved = [m for m in cohort if m["status"] in ("RESOLVED", "CLOSED")]
            resolved_count = len(resolved)
            total_accrued = sum(m["accrued_to_date_cents"] for m in cohort)
            if cohort:
                midpoint_sum = sum(m["exposure_low_cents"] + m["exposure_high_cents"] for m in cohort)
                avg_exposure = midpoint_sum // (2 * len(cohort))
            else:
                avg_exposure = 0
            if resolved_count > 0:
                favorable = sum(
                    1 for m in resolved if m["resolution_type"] in ("DISMISSAL", "SUMMARY_JUDGMENT")
                )
                favorability = (100 * favorable) // resolved_count
            else:
                favorability = 0
            cohorts.append(
                {
                    "exposure_tier": tier,
                    "resolved_count": resolved_count,
                    "total_accrued_cents": total_accrued,
                    "avg_exposure_cents": avg_exposure,
                    "outcome_favorability_pct": favorability,
                }
            )
        open_exposure = 0
        for m in matters:
            if m["status"] in ("STAFFING", "ACTIVE", "REOPENED", "SETTLEMENT_PENDING"):
                high = m.get("exposure_high_cents")
                if high is not None:
                    open_exposure += high
        return ok_object(
            {
                "cohorts": cohorts,
                "open_exposure_cents": open_exposure,
                "total_matters": len(matters),
            }
        )
