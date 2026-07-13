"""Domain lookups, calculations, and serialization."""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import store
from errors import ApiError

# --- Enum vocabularies --------------------------------------------------------
VAULT_KINDS = {"ACCOUNT", "ASSET", "DOCUMENT"}
SENSITIVITY = {"LOW", "MEDIUM", "HIGH"}
DISTRIBUTION_BASIS = {"NET", "GROSS"}
DEPUTY_ROLES = {"EXECUTOR", "HEALTHCARE_PROXY", "GUARDIAN", "VIEWER"}
RELEASE_TRIGGERS = {"ON_DEATH", "ON_INCAPACITY", "IMMEDIATE"}
DIRECTIVE_TYPES = {"MEDICAL", "FUNERAL", "DNR", "ORGAN_DONATION"}
RR_TRIGGERS = {"ON_DEATH", "ON_INCAPACITY"}
SUB_TIERS = {"FREE", "PLUS", "FAMILY"}
REFUND_POLICIES = {"IMMEDIATE_PRORATA", "FORFEIT"}
SHARE_SCOPES = {"ITEM", "PLAN"}
PROVIDER_TYPES = {"WILL_REGISTRY", "LIFE_INSURANCE"}
SUBJECT_KINDS = {"VAULT", "DIRECTIVE", "BENEFICIARY", "SUBSCRIPTION"}
LIFE_STATUSES = {"ACTIVE", "INCAPACITATED", "DECEASED"}

SEAT_LIMITS = {"FREE": 1, "PLUS": 5, "FAMILY": 10}
MONTHLY_FEES = {"FREE": 0, "PLUS": 1200, "FAMILY": 2400}

TARGET_ITEMS = 5
TARGET_DIRECTIVES = 2
TARGET_BENEFICIARIES = 3
QUORUM_FRACTION = Decimal("0.5")
GRACE_DAYS = 30


# --- Not-found lookups --------------------------------------------------------
def get_plan(plan_id):
    p = store.PLANS.get(plan_id)
    if not p:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Plan not found")
    return p


def get_vault_item(item_id):
    v = store.VAULT_ITEMS.get(item_id)
    if not v:
        raise ApiError("ERR_VAULT_ITEM_NOT_FOUND", "Vault item not found")
    return v


def get_deputy(deputy_id):
    d = store.DEPUTIES.get(deputy_id)
    if not d:
        raise ApiError("ERR_DEPUTY_NOT_FOUND", "Deputy not found")
    return d


def get_beneficiary(bid):
    b = store.BENEFICIARIES.get(bid)
    if not b:
        raise ApiError("ERR_NOT_FOUND", "Beneficiary not found")
    return b


def get_directive(did):
    d = store.DIRECTIVES.get(did)
    if not d:
        raise ApiError("ERR_DIRECTIVE_NOT_FOUND", "Directive not found")
    return d


def get_release_request(rid):
    r = store.RELEASE_REQUESTS.get(rid)
    if not r:
        raise ApiError("ERR_RELEASE_REQUEST_NOT_FOUND", "Release request not found")
    return r


def get_subscription(sid):
    s = store.SUBSCRIPTIONS.get(sid)
    if not s:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found")
    return s


def get_share(sid):
    s = store.SHARES.get(sid)
    if not s:
        raise ApiError("ERR_SHARE_NOT_FOUND", "Share not found")
    return s


def get_integration(iid):
    i = store.INTEGRATIONS.get(iid)
    if not i:
        raise ApiError("ERR_NOT_FOUND", "Integration not found")
    return i


def get_reminder(rid):
    r = store.REVIEW_REMINDERS.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", "Review reminder not found")
    return r


# --- Aggregation helpers ------------------------------------------------------
def plan_subscription(plan_id):
    subs = [s for s in store.SUBSCRIPTIONS.values() if s["plan_id"] == plan_id]
    if not subs:
        return None
    return max(subs, key=lambda s: s["_seq"])


def seat_limit_for(plan_id):
    sub = plan_subscription(plan_id)
    if not sub:
        return 0
    return SEAT_LIMITS.get(sub["tier"], 0)


def seats_used_for(plan_id):
    dep = sum(
        1
        for d in store.DEPUTIES.values()
        if d["plan_id"] == plan_id
        and d["status"] in ("INVITED", "ACCEPTED")
        and d["consumes_seat"]
    )
    sh = sum(
        1
        for s in store.SHARES.values()
        if s["plan_id"] == plan_id and s["status"] == "ACTIVE"
    )
    return dep + sh


def seat_accounting(plan_id):
    limit = seat_limit_for(plan_id)
    used = seats_used_for(plan_id)
    return used, limit, max(limit - used, 0)


def accepted_deputy_count(plan_id):
    return sum(
        1
        for d in store.DEPUTIES.values()
        if d["plan_id"] == plan_id and d["status"] == "ACCEPTED"
    )


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def completeness_pct(plan_id):
    sealed = sum(
        1
        for v in store.VAULT_ITEMS.values()
        if v["plan_id"] == plan_id and v["status"] in ("SEALED", "RELEASED")
    )
    active_dir = sum(
        1
        for d in store.DIRECTIVES.values()
        if d["plan_id"] == plan_id and d["status"] == "ACTIVE"
    )
    accepted_dep = accepted_deputy_count(plan_id)
    ben = sum(
        1
        for b in store.BENEFICIARIES.values()
        if b["plan_id"] == plan_id and b["status"] in ("NOMINATED", "VESTED")
    )

    sub = plan_subscription(plan_id)
    tier = sub["tier"] if sub else None
    if tier == "FAMILY":
        w_vault, w_dir, w_dep, w_ben = 30, 20, 20, 30
    else:
        w_vault, w_dir, w_dep, w_ben = 40, 20, 20, 20

    vs = min(Decimal(sealed) / Decimal(TARGET_ITEMS), Decimal(1))
    ds = min(Decimal(active_dir) / Decimal(TARGET_DIRECTIVES), Decimal(1))
    ps = Decimal(1) if accepted_dep >= 1 else Decimal(0)
    bs = min(Decimal(ben) / Decimal(TARGET_BENEFICIARIES), Decimal(1))

    raw = (Decimal(w_vault) * vs + Decimal(w_dir) * ds
           + Decimal(w_dep) * ps + Decimal(w_ben) * bs)
    return round_half_up(raw)


def _floor_dec(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def beneficiary_allocation(item):
    """Vest linked NOMINATED beneficiaries of a released ASSET item."""
    if item["kind"] != "ASSET":
        return
    basis = item["net_value_cents"] if item["distribution_basis"] == "NET" else item["gross_value_cents"]
    if basis is None:
        basis = 0
    basis = int(basis)

    bens = [
        b
        for b in store.BENEFICIARIES.values()
        if b["asset_vault_item_id"] == item["id"] and b["status"] == "NOMINATED"
    ]
    bens = sorted(bens, key=lambda b: (b["created_at"], b["_seq"]))
    if not bens:
        return

    floors = []
    sum_pct = Decimal(0)
    for b in bens:
        pct = Decimal(str(b["allocation_pct"]))
        sum_pct += pct
        raw_b = Decimal(basis) * (pct / Decimal(100))
        floors.append(_floor_dec(raw_b))

    pool = _floor_dec(Decimal(basis) * (sum_pct / Decimal(100)))
    remainder = pool - sum(floors)
    if remainder < 0:
        remainder = 0

    for idx, b in enumerate(bens):
        extra = 1 if idx < remainder else 0
        b["allocated_value_cents"] = floors[idx] + extra
        b["status"] = "VESTED"
        store.touch(b)


def subscription_refund(sub):
    if sub["refund_policy"] == "FORFEIT":
        return 0
    period_end = sub["period_end"]
    clock = store.now()
    delta_days = (period_end - clock).total_seconds() / 86400.0
    remaining = max(0, math.floor(delta_days))
    fee = sub["monthly_fee_cents"]
    return round_half_up(Decimal(fee * remaining) / Decimal(30))


# --- Serialization ------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": store.fmt_dt(rec["created_at"]),
        "updated_at": store.fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_plan(p):
    used, limit, available = seat_accounting(p["id"])
    out = _common(p)
    out.update({
        "owner_full_name": p["owner_full_name"],
        "owner_email": p["owner_email"],
        "life_status": p["life_status"],
        "life_evidence_ref": p["life_evidence_ref"],
        "completeness_pct": completeness_pct(p["id"]),
        "seats_used": used,
        "seats_available": available,
    })
    return out


def serialize_vault_item(v):
    out = _common(v)
    out.update({
        "plan_id": v["plan_id"],
        "kind": v["kind"],
        "category": v["category"],
        "title": v["title"],
        "secret_ref": v["secret_ref"],
        "sensitivity": v["sensitivity"],
        "gross_value_cents": v["gross_value_cents"],
        "liability_cents": v["liability_cents"],
        "distribution_basis": v["distribution_basis"],
        "net_value_cents": v["net_value_cents"],
        "status": v["status"],
    })
    return out


def serialize_deputy(d):
    out = _common(d)
    out.update({
        "plan_id": d["plan_id"],
        "full_name": d["full_name"],
        "email": d["email"],
        "deputy_role": d["deputy_role"],
        "access_scope": d["access_scope"],
        "release_trigger": d["release_trigger"],
        "authority_start_at": store.fmt_dt(d["authority_start_at"]),
        "authority_end_at": store.fmt_dt(d["authority_end_at"]),
        "consumes_seat": d["consumes_seat"],
        "status": d["status"],
    })
    return out


def serialize_beneficiary(b):
    out = _common(b)
    out.update({
        "plan_id": b["plan_id"],
        "parent_beneficiary_id": b["parent_beneficiary_id"],
        "asset_vault_item_id": b["asset_vault_item_id"],
        "full_name": b["full_name"],
        "relationship": b["relationship"],
        "contact_email": b["contact_email"],
        "allocation_pct": b["allocation_pct"],
        "allocated_value_cents": b["allocated_value_cents"],
        "status": b["status"],
    })
    return out


def serialize_directive(d):
    out = _common(d)
    out.update({
        "plan_id": d["plan_id"],
        "directive_type": d["directive_type"],
        "content": d["content"],
        "version_number": d["version_number"],
        "status": d["status"],
    })
    return out


def serialize_release_request(r):
    out = _common(r)
    out.update({
        "plan_id": r["plan_id"],
        "requested_by_deputy_id": r["requested_by_deputy_id"],
        "trigger_type": r["trigger_type"],
        "scope_kinds": r["scope_kinds"],
        "required_approvals": r["required_approvals"],
        "approval_count": r["approval_count"],
        "approver_deputy_ids": r["approver_deputy_ids"],
        "expires_at": store.fmt_dt(r["expires_at"]),
        "status": r["status"],
    })
    return out


def serialize_subscription(s):
    out = _common(s)
    out.update({
        "plan_id": s["plan_id"],
        "tier": s["tier"],
        "refund_policy": s["refund_policy"],
        "seat_limit": s["seat_limit"],
        "monthly_fee_cents": s["monthly_fee_cents"],
        "period_start": store.fmt_dt(s["period_start"]),
        "period_end": store.fmt_dt(s["period_end"]),
        "last_refund_cents": s["last_refund_cents"],
        "status": s["status"],
    })
    return out


def serialize_share(s):
    out = _common(s)
    out.update({
        "plan_id": s["plan_id"],
        "vault_item_id": s["vault_item_id"],
        "shared_with_email": s["shared_with_email"],
        "scope": s["scope"],
        "effective_at": store.fmt_dt(s["effective_at"]),
        "expires_at": store.fmt_dt(s["expires_at"]),
        "status": s["status"],
    })
    return out


def serialize_integration(i):
    out = _common(i)
    out.update({
        "plan_id": i["plan_id"],
        "provider_type": i["provider_type"],
        "provider_name": i["provider_name"],
        "external_ref": i["external_ref"],
        "coverage_cents": i["coverage_cents"],
        "last_synced_at": store.fmt_dt(i["last_synced_at"]),
        "sync_status": i["sync_status"],
    })
    return out


def serialize_reminder(r):
    out = _common(r)
    out.update({
        "plan_id": r["plan_id"],
        "subject_kind": r["subject_kind"],
        "interval_days": r["interval_days"],
        "last_reviewed_at": store.fmt_dt(r["last_reviewed_at"]),
        "due_at": store.fmt_dt(r["due_at"]),
        "status": r["status"],
    })
    return out
