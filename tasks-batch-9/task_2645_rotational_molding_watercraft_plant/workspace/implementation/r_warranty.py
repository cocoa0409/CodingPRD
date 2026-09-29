"""WarrantyClaim routes: two independent axes on one row and the conserved
two-bucket reserve ledger.

`claim_status` is the adjudication axis (SUBMITTED -> UNDER_REVIEW ->
APPROVED / DENIED, plus the UNDER_REVIEW -> SUBMITTED revert, the
APPROVED -> VOIDED reversal and the customer's WITHDRAWN escape hatch).
`storage_review_status` is the storage-guidance axis (NOT_STARTED ->
GUIDANCE_VERIFIED / GUIDANCE_VIOLATED -> WAIVED).  Deciding the storage axis
never moves the adjudication axis; approve and deny only *read* it.

Every check is registered on the shared ordered pipeline at the ladder
priority the scaffold declares, so the two parallel-axis guards resolve in the
declared order: 43 (ERR_CLAIM_INVALID_STATE) always precedes 46, 47 and 55,
and the OCC rung 84 is evaluated last of all.
"""
from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, touch
from errors import fail
from schema import add_schema, body_json, coerce, enum_filter, str_filter

bp = Blueprint("warranty", __name__)

CLAIM_READ = ("PlantAdmin", "WarrantyAgent", "Customer")

CLAIM_CREATE = {
    "claim_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "finished_unit_id": {"type": "string", "required": True},
    "customer_id": {"type": "string", "required": True},
    "claim_type": {"type": "enum", "required": True, "values": rt.CLAIM_TYPES},
    "reported_deformation_mm": {"type": "dec", "places": 2, "min": 0,
                                "default": "0.00"},
    "storage_description": {"type": "string", "required": False,
                            "min_len": 10, "max_len": 500},
}


@bp.route("/warranty-claims", methods=["POST"])
def create_claim():
    ctx = auth.authenticate(("WarrantyAgent", "Customer"))
    body = body_json()
    checks = Checks()
    holder = {}

    def own_customer():
        # A Customer may only open a claim in its own name.  Evaluated at the
        # customer-scope rung, i.e. before the body ids are resolved.
        if ctx.role != "Customer":
            return
        supplied = body.get("customer_id")
        if isinstance(supplied, str) and supplied != ctx.user_id:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION",
                 "A customer may only claim under its own customer_id.")

    def resolve():
        # PRD.md section 2.8, WarrantyClaim: "`finished_unit_id` (required, must
        # resolve or `ERR_FINISHED_UNIT_NOT_FOUND`); `customer_id` (required,
        # must resolve or `ERR_CUSTOMER_NOT_FOUND` ...)" — both references carry
        # an entity-specific not-found code, so neither collapses onto
        # ERR_RESOURCE_NOT_FOUND.
        holder["unit"] = rt.find("finished_units", body.get("finished_unit_id"))
        holder["customer"] = rt.find("customers", body.get("customer_id"))

    def deformation():
        if body.get("claim_type") != "HULL_DEFORMATION":
            return
        values = coerce(body, CLAIM_CREATE)
        if values["reported_deformation_mm"] < calc.DEFORMATION_THRESHOLD_MM:
            fail("ERR_DEFORMATION_BELOW_THRESHOLD",
                 "A HULL_DEFORMATION claim needs at least %s mm of deviation."
                 % calc.DEFORMATION_THRESHOLD_MM)

    def customer_active():
        if holder["customer"]["status"] != "ACTIVE":
            fail("ERR_CUSTOMER_NOT_ACTIVE", "The claimant is not ACTIVE.")

    def delivered():
        if holder["unit"]["logistics_status"] != "DELIVERED":
            fail("ERR_UNIT_NOT_DELIVERED",
                 "A hull in logistics_status %s carries no warranty."
                 % holder["unit"]["logistics_status"])

    checks.add(6, own_customer)
    checks.add(16, resolve)
    add_schema(checks, body, CLAIM_CREATE)
    checks.add(26, lambda: rt.unique_code("warranty_claims", "claim_code",
                                          body.get("claim_code")))
    checks.add(27, deformation)
    checks.add(60, customer_active)
    checks.add(61, delivered)
    checks.run()

    values = coerce(body, CLAIM_CREATE)
    row = {
        "claim_code": values["claim_code"],
        "finished_unit_id": holder["unit"]["id"],
        "customer_id": holder["customer"]["id"],
        "claim_type": values["claim_type"],
        "reported_deformation_mm": values["reported_deformation_mm"],
        "storage_description": values["storage_description"],
        "claim_status": "SUBMITTED",
        "storage_review_status": "NOT_STARTED",
        "months_in_service": None,
        "payout_basis": None,
        "pre_fee_gross_cents": None,
        "storage_deduction_cents": None,
        "admin_fee_cents": None,
        "net_payout_cents": None,
        "denial_reason": None,
    }
    core.insert("warranty_claims", row)
    return rt.one("warranty_claims", row, 201)


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    ctx = auth.authenticate(CLAIM_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("warranty_claims")
        rows = rt.filter_eq(rows, "finished_unit_id", str_filter("finished_unit_id"))
        rows = rt.filter_eq(rows, "customer_id", str_filter("customer_id"))
        rows = rt.filter_eq(rows, "claim_type",
                            enum_filter("claim_type", rt.CLAIM_TYPES))
        rows = rt.filter_eq(rows, "claim_status",
                            enum_filter("claim_status", rt.CLAIM_STATUSES))
        rows = rt.filter_eq(rows, "storage_review_status",
                            enum_filter("storage_review_status",
                                        rt.STORAGE_REVIEW_STATUSES))
        rows = rt.filter_eq(rows, "denial_reason",
                            enum_filter("denial_reason", rt.DENIAL_REASONS))
        # A Customer sees only its own claims; this narrows the page, it is not
        # a rejection, so it is applied after the declared filters.
        items[0] = auth.scope_claim_list(ctx, rows)

    checks.add(21, collect)
    checks.run()
    return rt.many("warranty_claims", items[0])


@bp.route("/warranty-claims/<warranty_claim_id>", methods=["GET"])
def read_claim(warranty_claim_id):
    ctx = auth.authenticate(CLAIM_READ)
    checks = Checks()
    holder = {}
    checks.add(6, lambda: auth.scope_claim(
        ctx, S.warranty_claims.get(warranty_claim_id)))
    checks.add(10, lambda: holder.update(
        row=rt.find("warranty_claims", warranty_claim_id)))
    checks.run()
    return rt.one("warranty_claims", holder["row"])


# --------------------------------------------------------------------------
# Shared prologue for every claim edge.  Rung 43 is the adjudication-axis
# guard and is registered here so it always precedes the storage-axis guards
# at 46, 47 and 55 and the OCC rung at 84.
# --------------------------------------------------------------------------
def _claim_action(warranty_claim_id, spec, roles, allowed_statuses):
    ctx = auth.authenticate(roles)
    body = body_json()
    checks = Checks()
    holder = {}

    def resolve():
        claim = holder["row"]
        holder["unit"] = S.finished_units.get(claim["finished_unit_id"])
        holder["customer"] = S.customers.get(claim["customer_id"])
        holder["model"] = (S.product_models.get(holder["unit"]["product_model_id"])
                           if holder["unit"] else None)

    def claim_state():
        if holder["row"]["claim_status"] not in allowed_statuses:
            fail("ERR_CLAIM_INVALID_STATE",
                 "Claim claim_status is %s." % holder["row"]["claim_status"])

    checks.add(10, lambda: holder.update(
        row=rt.find("warranty_claims", warranty_claim_id)))
    checks.add(10.5, resolve)
    add_schema(checks, body, spec)
    checks.add(43, claim_state)
    return ctx, holder, body, checks


@bp.route("/warranty-claims/<warranty_claim_id>/start-review", methods=["POST"])
def start_review(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, {}, ("WarrantyAgent",), ("SUBMITTED",))

    def customer_active():
        if holder["customer"] is None or holder["customer"]["status"] != "ACTIVE":
            fail("ERR_CUSTOMER_NOT_ACTIVE", "The claimant is not ACTIVE.")

    checks.add(60, customer_active)
    checks.run()
    claim, unit = holder["row"], holder["unit"]
    claim["claim_status"] = "UNDER_REVIEW"
    # Frozen here and re-aged only by a return-to-queue / start-review round trip.
    claim["months_in_service"] = calc.months_in_service(
        unit["delivered_at"] if unit else None, core.now())
    touch(claim)
    return rt.one("warranty_claims", claim)


STORAGE_OUTCOMES = ("VERIFIED", "VIOLATED")
STORAGE_REVIEW_SPEC = {
    "outcome": {"type": "enum", "required": True, "values": STORAGE_OUTCOMES},
    "storage_description": {"type": "string", "required": True,
                            "min_len": 10, "max_len": 500},
}
WAIVE_SPEC = {"waiver_note": {"type": "string", "required": True,
                              "min_len": 1, "max_len": 500}}
APPROVE_SPEC = {"expected_product_model_version": {"type": "int", "required": True,
                                                   "min": 1}}
DENY_SPEC = {"denial_reason": {"type": "enum", "required": True,
                               "values": rt.DENIAL_REASONS}}
RETURN_SPEC = {"return_note": {"type": "string", "required": True,
                               "min_len": 1, "max_len": 500}}
VOID_SPEC = {"void_reason": {"type": "string", "required": True,
                             "min_len": 1, "max_len": 500}}
WITHDRAW_SPEC = {"withdraw_reason": {"type": "string", "required": True,
                                     "min_len": 1, "max_len": 500}}


@bp.route("/warranty-claims/<warranty_claim_id>/storage-review", methods=["POST"])
def storage_review(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, STORAGE_REVIEW_SPEC, ("WarrantyAgent",),
        ("UNDER_REVIEW",))

    def not_decided():
        if holder["row"]["storage_review_status"] != "NOT_STARTED":
            fail("ERR_STORAGE_REVIEW_ALREADY_DONE",
                 "The storage axis already reads %s."
                 % holder["row"]["storage_review_status"])

    def acknowledged():
        # Only a VERIFIED outcome needs the acknowledgement; a VIOLATED finding
        # is exactly what an unacknowledged customer earns.
        if body.get("outcome") != "VERIFIED":
            return
        customer, unit = holder["customer"], holder["unit"]
        ack = customer["storage_guidance_acknowledged_at"] if customer else None
        if ack is None:
            fail("ERR_STORAGE_GUIDANCE_NOT_ACKNOWLEDGED",
                 "The claimant never acknowledged the storage guidance.")
        delivered_at = unit["delivered_at"] if unit else None
        if delivered_at is None or ack > delivered_at:
            fail("ERR_STORAGE_GUIDANCE_NOT_ACKNOWLEDGED",
                 "The guidance must have been acknowledged at or before delivery.")

    checks.add(46, not_decided)
    checks.add(56, acknowledged)
    checks.run()
    claim = holder["row"]
    claim["storage_review_status"] = ("GUIDANCE_VERIFIED"
                                     if body["outcome"] == "VERIFIED"
                                     else "GUIDANCE_VIOLATED")
    claim["storage_description"] = body["storage_description"]
    # The adjudication axis is deliberately untouched: the claim stays UNDER_REVIEW.
    touch(claim)
    return rt.one("warranty_claims", claim)


@bp.route("/warranty-claims/<warranty_claim_id>/waive-storage-finding",
          methods=["POST"])
def waive_storage_finding(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, WAIVE_SPEC, ("PlantAdmin",), ("UNDER_REVIEW",))

    def waivable():
        if holder["row"]["storage_review_status"] != "GUIDANCE_VIOLATED":
            fail("ERR_STORAGE_FINDING_NOT_WAIVABLE",
                 "Only a GUIDANCE_VIOLATED finding may be waived; this one is %s."
                 % holder["row"]["storage_review_status"])

    checks.add(47, waivable)
    checks.run()
    claim = holder["row"]
    claim["waiver_note"] = body["waiver_note"]
    # A waiver unblocks approval but never restores full value: the 35.00 pct
    # storage deduction still applies to a claim approved from WAIVED.
    claim["storage_review_status"] = "WAIVED"
    touch(claim)
    return rt.one("warranty_claims", claim)


@bp.route("/warranty-claims/<warranty_claim_id>/approve", methods=["POST"])
def approve_claim(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, APPROVE_SPEC, ("WarrantyAgent",), ("UNDER_REVIEW",))

    def storage_permissive():
        if holder["row"]["storage_review_status"] not in ("GUIDANCE_VERIFIED",
                                                         "WAIVED"):
            fail("ERR_STORAGE_REVIEW_INCOMPLETE",
                 "The storage axis reads %s; approval needs GUIDANCE_VERIFIED "
                 "or WAIVED." % holder["row"]["storage_review_status"])

    def customer_active():
        if holder["customer"] is None or holder["customer"]["status"] != "ACTIVE":
            fail("ERR_CUSTOMER_NOT_ACTIVE", "The claimant is not ACTIVE.")

    def delivered():
        unit = holder["unit"]
        if unit is None or unit["logistics_status"] != "DELIVERED":
            fail("ERR_UNIT_NOT_DELIVERED",
                 "The claimed hull is not DELIVERED, so it has no warranty clock.")

    def in_term():
        months = holder["row"]["months_in_service"] or 0
        if months > calc.WARRANTY_TERM_MONTHS:
            fail("ERR_WARRANTY_TERM_EXPIRED",
                 "The hull is %d months old; the term is %d months."
                 % (months, calc.WARRANTY_TERM_MONTHS))

    def reserve_covers():
        # Pricing runs here so the gate reads the same integers that will be
        # written; nothing is persisted until every rung has passed.
        payout = calc.warranty_payout(holder["model"], holder["row"])
        holder["payout"] = payout
        if payout["net_payout_cents"] > holder["model"]["warranty_reserve_cents"]:
            fail("ERR_WARRANTY_RESERVE_EXHAUSTED",
                 "net_payout_cents %d exceeds the reserve of %d."
                 % (payout["net_payout_cents"],
                    holder["model"]["warranty_reserve_cents"]))

    def occ():
        if body["expected_product_model_version"] != holder["model"]["version"]:
            fail("ERR_STALE_PRODUCT_MODEL_VERSION",
                 "expected_product_model_version does not match the stored version.")

    checks.add(55, storage_permissive)
    checks.add(60, customer_active)
    checks.add(61, delivered)
    checks.add(64, in_term)
    checks.add(76, reserve_covers)
    checks.add(84, occ)
    checks.run()

    claim, model = holder["row"], holder["model"]
    payout = holder["payout"]
    claim["payout_basis"] = payout["payout_basis"]
    claim["pre_fee_gross_cents"] = payout["pre_fee_gross_cents"]
    claim["storage_deduction_cents"] = payout["storage_deduction_cents"]
    claim["admin_fee_cents"] = payout["admin_fee_cents"]
    claim["net_payout_cents"] = payout["net_payout_cents"]
    claim["claim_status"] = "APPROVED"
    touch(claim)
    # The conserved two-bucket ledger: reserve down, paid up, by the identical
    # already-rounded integer.  The assertion inside guards the invariant.
    svc.reserve_draw(model, payout["net_payout_cents"])
    return rt.one("warranty_claims", claim)


@bp.route("/warranty-claims/<warranty_claim_id>/deny", methods=["POST"])
def deny_claim(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, DENY_SPEC, ("WarrantyAgent",), ("UNDER_REVIEW",))

    def storage_decided():
        if holder["row"]["storage_review_status"] == "NOT_STARTED":
            fail("ERR_STORAGE_REVIEW_INCOMPLETE",
                 "A claim cannot be denied before its storage axis is decided.")

    checks.add(55, storage_decided)
    checks.run()
    claim = holder["row"]
    # A storage violation forces the reason regardless of what was asked for.
    if claim["storage_review_status"] == "GUIDANCE_VIOLATED":
        claim["denial_reason"] = "STORAGE_GUIDANCE_VIOLATED"
    else:
        claim["denial_reason"] = body["denial_reason"]
    # Denial produces an explicit zero record, not nulls, and no reserve moves.
    claim["payout_basis"] = None
    claim["pre_fee_gross_cents"] = 0
    claim["storage_deduction_cents"] = 0
    claim["admin_fee_cents"] = 0
    claim["net_payout_cents"] = 0
    claim["claim_status"] = "DENIED"
    touch(claim)
    return rt.one("warranty_claims", claim)


@bp.route("/warranty-claims/<warranty_claim_id>/return-to-queue", methods=["POST"])
def return_to_queue(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, RETURN_SPEC, ("WarrantyAgent",), ("UNDER_REVIEW",))
    checks.run()
    claim = holder["row"]
    claim["return_note"] = body["return_note"]
    # Both axes reset inside one request, so the row's version advances once.
    claim["claim_status"] = "SUBMITTED"
    claim["storage_review_status"] = "NOT_STARTED"
    claim["months_in_service"] = None
    claim["storage_description"] = None
    touch(claim)
    return rt.one("warranty_claims", claim)


@bp.route("/warranty-claims/<warranty_claim_id>/void", methods=["POST"])
def void_claim(warranty_claim_id):
    ctx, holder, body, checks = _claim_action(
        warranty_claim_id, VOID_SPEC, ("PlantAdmin",), ("APPROVED",))
    checks.run()
    claim, model = holder["row"], holder["model"]
    claim["void_reason"] = body["void_reason"]
    claim["denial_reason"] = "APPROVAL_VOIDED"
    claim["claim_status"] = "VOIDED"
    # The money fields are retained as the audit record and are NOT zeroed.
    touch(claim)
    # The only path in the system that raises a reserve: the exact reversal.
    svc.reserve_restore(model, claim["net_payout_cents"] or 0)
    return rt.one("warranty_claims", claim)


@bp.route("/warranty-claims/<warranty_claim_id>/withdraw", methods=["POST"])
def withdraw_claim(warranty_claim_id):
    ctx = auth.authenticate(("Customer",))
    body = body_json()
    checks = Checks()
    holder = {}

    def claim_state():
        if holder["row"]["claim_status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            fail("ERR_CLAIM_INVALID_STATE",
                 "Claim claim_status is %s." % holder["row"]["claim_status"])

    checks.add(6, lambda: auth.scope_claim(
        ctx, S.warranty_claims.get(warranty_claim_id)))
    checks.add(10, lambda: holder.update(
        row=rt.find("warranty_claims", warranty_claim_id)))
    add_schema(checks, body, WITHDRAW_SPEC)
    checks.add(43, claim_state)
    checks.run()
    claim = holder["row"]
    claim["withdraw_reason"] = body["withdraw_reason"]
    claim["claim_status"] = "WITHDRAWN"
    touch(claim)
    return rt.one("warranty_claims", claim)
