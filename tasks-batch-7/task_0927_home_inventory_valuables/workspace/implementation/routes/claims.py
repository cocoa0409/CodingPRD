"""Post-loss claim support (PRD 3.7)."""

import calc
import cascades
import derive
import serializers
import store
from constants import (
    ADJUDICATION_DECISIONS,
    CLAIM_MIN_EVIDENCE_TIER_RANK,
    DEDUCTIBLE_MODES,
    DENIAL_REASONS,
    EVIDENCE_RANK,
    MAX_APPEALS_PER_LINE,
    PERILS,
    SETTLEMENT_BASES,
)
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one
from timeutil import clock

TERMINAL_CLAIM_STATES = ("SETTLED", "DENIED", "WITHDRAWN")


def _claim(ctx):
    return ctx.row("claim_id")


def _claim_household(ctx):
    return _claim(ctx)["household_id"]


def _line(ctx):
    return ctx.row("claim_line_id")


def _line_claim(ctx):
    return store.claims.get(_line(ctx)["claim_id"])


def _line_household(ctx):
    claim = _line_claim(ctx)
    return claim["household_id"] if claim else None


def _claim_lines(claim_id):
    return [l for l in store.all_of(store.claim_lines) if l["claim_id"] == claim_id]


# ----------------------------------------------------------- opening a claim
def _open_rung14(ctx):
    package = store.packages[ctx.body["package_id"]]
    if package["status"] not in ("GENERATED", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE")
    if package["policy_id"] != ctx.body["policy_id"]:
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/claims",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={
        "household_id": ("string", True),
        "package_id": ("string", True),
        "policy_id": ("string", True),
        "loss_date": ("datetime", True),
        "peril": ("string", True),
        "settlement_basis": ("string", True),
        "affected_room_ids": ("array", True),
        "deductible_mode": ("string", False),
    },
    enums={
        "peril": PERILS,
        "settlement_basis": SETTLEMENT_BASES,
        "deductible_mode": DEDUCTIBLE_MODES,
    },
    fks=("household_id", "package_id", "policy_id", "affected_room_ids"),
    household=lambda ctx: ctx.body.get("household_id"),
    rungs={14: _open_rung14},
)
def open_claim(ctx):
    household_id = ctx.body["household_id"]
    affected = list(ctx.body["affected_room_ids"])
    claim = store.new_row(
        store.claims,
        household_id=household_id,
        package_id=ctx.body["package_id"],
        policy_id=ctx.body["policy_id"],
        peril=ctx.body["peril"],
        settlement_basis=ctx.body["settlement_basis"],
        deductible_mode=ctx.body.get("deductible_mode") or "PRO_RATA",
        affected_room_ids=affected,
        status="OPEN",
        frozen_item_count=0,
        line_count=0,
        approved_line_count=0,
        denied_line_count=0,
        blocked_line_count=0,
        total_settlement_cents=0,
    )
    derive.keep_raw(claim, "loss_date", ctx.body["loss_date"])
    derive.stamp(claim, "submitted_at", None)

    frozen = []
    for item in store.all_of(store.items):
        if item["household_id"] != household_id or item["lifecycle_state"] != "CATALOGED":
            continue
        if item["room_id"] not in affected:
            continue
        item["lifecycle_state"] = "FROZEN"
        item["frozen_by_claim_id"] = claim["id"]
        store.touch(item)
        frozen.append(item)
    claim["frozen_item_count"] = len(frozen)

    household = store.households.get(household_id)
    if household is not None:
        derive.recompute_household(household, bump=True)
        store.touch(household)

    frozen_ids = {i["id"] for i in frozen}
    for plan in store.all_of(store.estate_plans):
        if plan["household_id"] != household_id or plan["status"] != "PROPOSED":
            continue
        blocked = [
            a
            for a in derive.plan_allocations(plan["id"])
            if a["item_id"] in frozen_ids
        ]
        if not blocked:
            continue
        plan["status"] = "DRAFT"
        plan["balance_spread_pct"] = None
        plan["balanced"] = False
        store.touch(plan)
        for alloc in blocked:
            if not alloc["blocked"]:
                alloc["blocked"] = True
                store.touch(alloc)
        derive.recompute_plan(plan, bump=False)
    return one(serializers.claim(claim), 201)


@endpoint(
    "GET",
    "/vault/claims/{claim_id}",
    roles=["Homeowner", "ClaimsAdjuster", "InsuranceAgent", "PlatformAdmin"],
    scope_household=_claim_household,
)
def read_claim(ctx):
    return one(serializers.claim(_claim(ctx)))


@endpoint(
    "GET",
    "/vault/claims",
    roles=["Homeowner", "ClaimsAdjuster", "InsuranceAgent", "PlatformAdmin"],
)
def list_claims(ctx):
    return list_response(
        store.all_of(store.claims),
        ctx.args,
        serializers.claim,
        {
            "household_id": field("household_id"),
            "package_id": field("package_id"),
            "policy_id": field("policy_id"),
            "status": field("status"),
        },
    )


# ------------------------------------------------------------- claim lines
def _line_item(ctx):
    return store.items.get(ctx.body.get("item_id"))


def _lines_rung20(ctx):
    item = _line_item(ctx)
    if EVIDENCE_RANK[item["evidence_tier"]] < CLAIM_MIN_EVIDENCE_TIER_RANK:
        raise ApiError("ERR_EVIDENCE_TIER_INSUFFICIENT")


def _lines_rung21(ctx):
    if _line_item(ctx)["valuation_state"] == "APPRAISAL_REQUIRED":
        raise ApiError("ERR_APPRAISAL_REQUIRED")


def _lines_rung24(ctx):
    item = _line_item(ctx)
    quantity = ctx.body["claimed_quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ApiError("ERR_INVALID_QUANTITY")
    if quantity < 1 or quantity > item["quantity"]:
        raise ApiError("ERR_INVALID_QUANTITY")


def _lines_rung29(ctx):
    claim = _claim(ctx)
    for line in store.claim_lines.values():
        if line["claim_id"] == claim["id"] and line["item_id"] == ctx.body["item_id"]:
            raise ApiError("ERR_DUPLICATE_CLAIM_LINE")


@endpoint(
    "POST",
    "/vault/claims/{claim_id}/lines",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={"item_id": ("string", True), "claimed_quantity": ("integer", True)},
    fks=("item_id",),
    household=_claim_household,
    scope_household=_claim_household,
    rungs={20: _lines_rung20, 21: _lines_rung21, 24: _lines_rung24, 29: _lines_rung29},
)
def create_claim_line(ctx):
    claim = _claim(ctx)
    item = _line_item(ctx)
    line = store.new_row(
        store.claim_lines,
        claim_id=claim["id"],
        item_id=item["id"],
        claimed_quantity=ctx.body["claimed_quantity"],
        status="PENDING",
        gross_value_cents=0,
        capped_value_cents=0,
        deductible_share_cents=0,
        net_settlement_cents=0,
        appeal_count=0,
        settlement_hold=False,
        basis_downgraded=False,
        denial_reason=None,
    )
    line["_basis_at_create"] = item["effective_value_basis"]
    derive.recompute_claim_counts(claim, bump=True)
    store.touch(claim)
    return one(serializers.claim_line(line), 201)


@endpoint(
    "GET",
    "/vault/claim-lines/{claim_line_id}",
    roles=["Homeowner", "ClaimsAdjuster", "PlatformAdmin"],
    scope_household=_line_household,
)
def read_claim_line(ctx):
    return one(serializers.claim_line(_line(ctx)))


@endpoint("GET", "/vault/claim-lines", roles=["Homeowner", "ClaimsAdjuster", "PlatformAdmin"])
def list_claim_lines(ctx):
    return list_response(
        store.all_of(store.claim_lines),
        ctx.args,
        serializers.claim_line,
        {
            "claim_id": field("claim_id"),
            "item_id": field("item_id"),
            "status": field("status"),
        },
    )


# --------------------------------------------------------------- submission
def _submit_rung13(ctx):
    if _claim(ctx)["status"] in TERMINAL_CLAIM_STATES:
        raise ApiError("ERR_ALREADY_TERMINAL")


def _submit_rung14(ctx):
    claim = _claim(ctx)
    if claim["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if claim["line_count"] < 1:
        raise ApiError("ERR_INVALID_STATE")
    package = store.packages.get(claim["package_id"])
    if package is None or package["status"] not in ("GENERATED", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/claims/{claim_id}/submit",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    household=_claim_household,
    scope_household=_claim_household,
    rungs={13: _submit_rung13, 14: _submit_rung14},
)
def submit_claim(ctx):
    claim = _claim(ctx)
    lines = _claim_lines(claim["id"])
    policy = store.policies.get(claim["policy_id"])
    items_by_id = {l["item_id"]: store.items.get(l["item_id"]) for l in lines}
    # Pinned evaluation order: all of step 1, then all of step 2, then step 3.
    for line in lines:
        line["gross_value_cents"] = calc.claim_gross_value(claim, line, items_by_id[line["item_id"]])
    calc.apply_capping(claim, lines, items_by_id)
    calc.allocate_deductible(claim, policy, lines)
    calc.finish_net(lines)
    for line in lines:
        store.touch(line)
    claim["status"] = "SUBMITTED"
    derive.stamp(claim, "submitted_at", clock.now)
    claim["total_settlement_cents"] = sum(
        l["net_settlement_cents"] for l in lines if l["status"] == "APPROVED"
    )
    store.touch(claim)
    return one(serializers.claim(claim))


# ------------------------------------------------------------ adjudication
def _adjudicate_rung13(ctx):
    if _line(ctx)["status"] == "APPROVED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _adjudicate_rung14(ctx):
    line = _line(ctx)
    claim = _line_claim(ctx)
    if line["status"] not in ("PENDING", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE")
    if ctx.body["decision"] == "APPROVE":
        if line["settlement_hold"]:
            raise ApiError("ERR_INVALID_STATE")
        if line["status"] == "PENDING" and (
            claim is None or claim["status"] not in ("SUBMITTED", "UNDER_REVIEW")
        ):
            raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/claim-lines/{claim_line_id}/adjudicate",
    roles=["ClaimsAdjuster"],
    mutating=True,
    body={"decision": ("string", True), "denial_reason": ("string", False)},
    enums={"decision": ADJUDICATION_DECISIONS, "denial_reason": DENIAL_REASONS},
    household=_line_household,
    rungs={13: _adjudicate_rung13, 14: _adjudicate_rung14},
)
def adjudicate_line(ctx):
    line = _line(ctx)
    claim = _line_claim(ctx)
    if ctx.body["decision"] == "APPROVE":
        line["status"] = "APPROVED"
    else:
        line["status"] = "DENIED"
        line["denial_reason"] = ctx.body.get("denial_reason")
        line["net_settlement_cents"] = 0
    store.touch(line)
    if claim is not None:
        if claim["status"] == "SUBMITTED":
            claim["status"] = "UNDER_REVIEW"
        derive.recompute_claim_counts(claim, bump=True)
        store.touch(claim)
        if claim["status"] == "SUPPLEMENT_REQUESTED":
            remaining = [l for l in _claim_lines(claim["id"]) if l["status"] == "APPEALED"]
            if not remaining:
                claim["status"] = "UNDER_REVIEW"
        cascades.maybe_auto_deny(claim)
    return one(serializers.claim_line(line))


# ------------------------------------------------------------------ appeal
def _appeal_rung13(ctx):
    if _line(ctx)["status"] == "APPROVED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _appeal_rung14(ctx):
    line = _line(ctx)
    claim = _line_claim(ctx)
    if line["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE")
    if claim is None or claim["status"] not in ("UNDER_REVIEW", "SUPPLEMENT_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")


def _appeal_rung30(ctx):
    if _line(ctx)["appeal_count"] >= MAX_APPEALS_PER_LINE:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED")


@endpoint(
    "POST",
    "/vault/claim-lines/{claim_line_id}/appeal",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={"appeal_note": ("string", False)},
    household=_line_household,
    scope_household=_line_household,
    rungs={13: _appeal_rung13, 14: _appeal_rung14, 30: _appeal_rung30},
)
def appeal_line(ctx):
    line = _line(ctx)
    claim = _line_claim(ctx)
    line["status"] = "APPEALED"
    line["appeal_count"] += 1
    line["denial_reason"] = None
    store.touch(line)
    if claim is not None:
        if claim["status"] == "UNDER_REVIEW":
            claim["status"] = "SUPPLEMENT_REQUESTED"
        derive.recompute_claim_counts(claim, bump=True)
        store.touch(claim)
    return one(serializers.claim_line(line))


# ---------------------------------------------------------------- settlement
def _settle_rung13(ctx):
    if _claim(ctx)["status"] in TERMINAL_CLAIM_STATES:
        raise ApiError("ERR_ALREADY_TERMINAL")


def _settle_rung14(ctx):
    claim = _claim(ctx)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    for line in _claim_lines(claim["id"]):
        if line["status"] in ("PENDING", "APPEALED"):
            raise ApiError("ERR_INVALID_STATE")
    if claim["blocked_line_count"] != 0:
        raise ApiError("ERR_INVALID_STATE")
    if claim["approved_line_count"] < 1:
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/claims/{claim_id}/settle",
    roles=["ClaimsAdjuster"],
    mutating=True,
    household=_claim_household,
    rungs={13: _settle_rung13, 14: _settle_rung14},
)
def settle_claim(ctx):
    claim = _claim(ctx)
    policy = store.policies.get(claim["policy_id"])
    approved = [l for l in _claim_lines(claim["id"]) if l["status"] == "APPROVED"]
    calc.allocate_deductible(claim, policy, approved)
    calc.finish_net(approved)
    claim["total_settlement_cents"] = sum(l["net_settlement_cents"] for l in approved)
    claim["status"] = "SETTLED"
    store.touch(claim)
    derive.unfreeze_items_of_claim(claim, bump=True)
    household = store.households.get(claim["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
        store.touch(household)
    return one(serializers.claim(claim))


# ---------------------------------------------------------------- withdrawal
def _withdraw_rung13(ctx):
    if _claim(ctx)["status"] in TERMINAL_CLAIM_STATES:
        raise ApiError("ERR_ALREADY_TERMINAL")


def _withdraw_rung14(ctx):
    if _claim(ctx)["status"] not in ("OPEN", "SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/claims/{claim_id}/withdraw",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={"withdraw_reason": ("string", False)},
    household=_claim_household,
    scope_household=_claim_household,
    rungs={13: _withdraw_rung13, 14: _withdraw_rung14},
)
def withdraw_claim(ctx):
    claim = _claim(ctx)
    claim["status"] = "WITHDRAWN"
    store.touch(claim)
    derive.unfreeze_items_of_claim(claim, bump=True)
    derive.void_grants(derive.grants_scoped_to_claim(claim["id"]), "SCOPE_DELETED")
    household = store.households.get(claim["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
        store.touch(household)
    return one(serializers.claim(claim))
