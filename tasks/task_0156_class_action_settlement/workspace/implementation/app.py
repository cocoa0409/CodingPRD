"""Class Action Settlement Administration API — Flask entry point.

Single-module implementation: all routes, state machines, calculations and
validations live here, backed by the in-memory store in db.py. Storage is
in-memory only; every process restart wipes all state.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request

import db
import errors as E
from errors import ApiError, err
from response import success, error

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
TAX_REPORTING_THRESHOLD_CENTS = 60000
BACKUP_WITHHOLDING_BPS = 2400
BPS_DENOMINATOR = 10000

ROLES = {
    "SettlementAdmin",
    "FundController",
    "ClaimsReviewer",
    "ClaimsAdministrator",
    "Claimant",
    "Court",
}

ENUM_SETS = {
    "distribution_method": {"PRO_RATA", "TIERED"},
    "claimant_tier": {"TIER_A", "TIER_B"},
    "channel": {"EMAIL", "MAIL", "PUBLICATION"},
    "delivery_status": {"DELIVERED", "BOUNCED", "RETURNED"},
    "reason_code": {"MISSING_PROOF", "SIGNATURE_MISSING", "IDENTITY_UNVERIFIED", "DUPLICATE_SUSPECTED"},
    "form_type": {"1099_MISC", "1099_NEC"},
    "ruling": {"SUSTAINED", "OVERRULED"},
}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    # Unknown route -> treat as path-resource-not-found family.
    return error("ERR_SETTLEMENT_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error("ERR_SETTLEMENT_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return error("ERR_INTERNAL", "Internal server error: %s" % e, 500)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    """Validate X-User-ID + X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or not isinstance(user_id, str) or not isinstance(role, str):
        raise err(E.ERR_UNAUTHENTICATED, "Missing or unparseable authentication headers.")
    if role not in ROLES:
        raise err(E.ERR_UNAUTHENTICATED, "Unknown role.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(E.ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation." % role)


# ---------------------------------------------------------------------------
# Request-body helpers and validation
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def require_fields(data, fields):
    """priority 20: ERR_MISSING_REQUIRED_FIELD."""
    for f in fields:
        if f not in data or data[f] is None:
            raise err(E.ERR_MISSING_REQUIRED_FIELD, "Missing required field: %s" % f)


def check_enum(data, field):
    """priority 21: ERR_INVALID_ENUM (only when the field is present)."""
    if field in data and data[field] is not None:
        if data[field] not in ENUM_SETS[field]:
            raise err(E.ERR_INVALID_ENUM, "Invalid value for %s: %r" % (field, data[field]))


def as_int(value):
    if isinstance(value, bool):
        raise err(E.ERR_MISSING_REQUIRED_FIELD, "Expected an integer.")
    if isinstance(value, int):
        return value
    raise err(E.ERR_MISSING_REQUIRED_FIELD, "Expected an integer.")


def parse_dt(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err(E.ERR_MISSING_REQUIRED_FIELD, "Expected an ISO 8601 datetime string.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(E.ERR_MISSING_REQUIRED_FIELD, "Unparseable datetime: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    """items: already-sorted list of serialized rows. Returns (page, meta)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(rows):
    """Sort entity dicts by creation order (created_at ASC, stable by _seq)."""
    return sorted(rows, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Entity construction helpers
# ---------------------------------------------------------------------------
def base_full():
    """Common system fields for a full (versioned) entity."""
    ts = db.iso_now_ms()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def base_lean():
    """Common system fields for a lean audit row (NoticeRecord, LedgerEntry)."""
    return {
        "id": db.new_id(),
        "created_at": db.iso_now_ms(),
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Bump updated_at + version on a mutation the state machine declares."""
    entity["updated_at"] = db.iso_now_ms()
    entity["version"] = entity["version"] + 1


# ---------------------------------------------------------------------------
# Serializers — strip internal-only fields (_seq, validating_reviewer_id, etc.)
# ---------------------------------------------------------------------------
_INTERNAL = {"_seq"}
_SETTLEMENT_INTERNAL = {"_seq"}
_CLAIM_INTERNAL = {"_seq", "validating_reviewer_id"}


def ser(entity, internal=None):
    drop = internal if internal is not None else _INTERNAL
    return {k: v for k, v in entity.items() if k not in drop}


def ser_settlement(s):
    return ser(s, _SETTLEMENT_INTERNAL)


def ser_claim(c):
    return ser(c, _CLAIM_INTERNAL)


# ---------------------------------------------------------------------------
# Lookup helpers (existence; raises ERR_SETTLEMENT_NOT_FOUND for path ids)
# ---------------------------------------------------------------------------
def get_path(collection, _id):
    row = collection.get(_id)
    if row is None:
        raise err(E.ERR_SETTLEMENT_NOT_FOUND, "Resource not found: %s" % _id)
    return row


def get_fk(collection, _id):
    """Body FK existence — raises ERR_REFERENCED_ENTITY_NOT_FOUND."""
    row = collection.get(_id)
    if row is None:
        raise err(E.ERR_REFERENCED_ENTITY_NOT_FOUND, "Referenced entity not found: %s" % _id)
    return row


# ---------------------------------------------------------------------------
# Cross-entity / derived helpers
# ---------------------------------------------------------------------------
NON_REJECTED_LIVE = {"SUBMITTED", "DEFICIENT", "CURED", "VALIDATED", "PAID"}


def member_claims(member_id):
    return [c for c in db.claims.values() if c["class_member_id"] == member_id]


def member_has_non_rejected_claim(member_id):
    return any(c["status"] != "REJECTED" for c in member_claims(member_id))


def member_has_live_claim(member_id):
    return any(c["status"] in NON_REJECTED_LIVE for c in member_claims(member_id))


def effective_optout_exists(member_id):
    return any(
        o["class_member_id"] == member_id and o["status"] == "EFFECTIVE"
        for o in db.opt_outs.values()
    )


def recompute_open_deficiency_count(claim):
    n = sum(
        1 for d in db.deficiencies.values()
        if d["claim_id"] == claim["id"] and d["status"] == "OPEN"
    )
    claim["open_deficiency_count"] = n
    return n


def maybe_promote_member_on_claim(member):
    """On first claim creation: NOTIFIED -> PARTICIPATING (if no effective opt-out)."""
    if member["status"] == "NOTIFIED" and not effective_optout_exists(member["id"]):
        member["status"] = "PARTICIPATING"
        touch(member)


def maybe_demote_member_after_rejection(member_id):
    """If a PARTICIPATING member has no remaining live (non-REJECTED) claim, fall back to NOTIFIED."""
    member = db.class_members.get(member_id)
    if member is None:
        return
    if member["status"] == "PARTICIPATING" and not member_has_live_claim(member_id):
        member["status"] = "NOTIFIED"
        touch(member)


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------
def append_ledger(settlement_id, entry_type, amount_cents, reference_id):
    row = base_lean()
    row.update({
        "settlement_id": settlement_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reference_id": reference_id,
    })
    db.ledger_entries[row["id"]] = row
    return row


def ledger_balance(settlement_id):
    return sum(
        e["amount_cents"] for e in db.ledger_entries.values()
        if e["settlement_id"] == settlement_id
    )


# ===========================================================================
# SETTLEMENT
# ===========================================================================
@app.route("/settlements", methods=["POST"])
def create_settlement():
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    data = body()
    check_enum(data, "distribution_method")
    require_fields(data, [
        "case_caption", "gross_fund_cents", "attorney_fee_cents",
        "admin_cost_cents", "distribution_method",
        "claim_filing_deadline", "objection_deadline",
    ])
    gross = as_int(data["gross_fund_cents"])
    fee = as_int(data["attorney_fee_cents"])
    admin = as_int(data["admin_cost_cents"])
    tier_a = as_int(data["tier_a_amount_cents"]) if data.get("tier_a_amount_cents") is not None else 0
    tier_b = as_int(data["tier_b_amount_cents"]) if data.get("tier_b_amount_cents") is not None else 0
    floor = as_int(data["cy_pres_floor_cents"]) if data.get("cy_pres_floor_cents") is not None else 0
    # parse deadlines (stored as ISO strings, also kept parsed internally)
    cfd = parse_dt(data["claim_filing_deadline"])
    objd = parse_dt(data["objection_deadline"])

    s = base_full()
    s.update({
        "case_caption": data["case_caption"],
        "gross_fund_cents": gross,
        "attorney_fee_cents": fee,
        "admin_cost_cents": admin,
        "distribution_method": data["distribution_method"],
        "tier_a_amount_cents": tier_a,
        "tier_b_amount_cents": tier_b,
        "claim_filing_deadline": data["claim_filing_deadline"],
        "objection_deadline": data["objection_deadline"],
        "cy_pres_floor_cents": floor,
        "status": "DRAFT",
        "net_distributable_cents": gross - fee - admin,
        "allocated_cents": 0,
        "residual_cents": 0,
        "_claim_filing_deadline_dt": cfd,
        "_objection_deadline_dt": objd,
    })
    db.settlements[s["id"]] = s
    return success(ser_settlement(s), 201)


def _public_settlement(s):
    # exclude internal parsed-dt cache fields
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    return out


@app.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin", "FundController", "ClaimsReviewer", "ClaimsAdministrator", "Court"])
    s = get_path(db.settlements, sid)
    return success(_public_settlement(s), 200)


@app.route("/settlements", methods=["GET"])
def list_settlements():
    _uid, role = auth()
    require_role(role, ["SettlementAdmin", "FundController", "ClaimsReviewer", "ClaimsAdministrator", "Court"])
    status = request.args.get("status")
    rows = list(db.settlements.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = paginate([_public_settlement(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/settlements/<sid>/open-notice", methods=["POST"])
def open_notice(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    s = get_path(db.settlements, sid)
    if s["status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Settlement is not in DRAFT.")
    # precondition: cy pres coherent — an APPROVED designation exists OR floor==0
    approved_exists = any(
        d["settlement_id"] == sid and d["status"] == "APPROVED"
        for d in db.cy_pres_designations.values()
    )
    if not (approved_exists or s["cy_pres_floor_cents"] == 0):
        raise err(E.ERR_INVALID_STATE, "Cy pres floor set without an approved designation.")
    s["status"] = "NOTICE_OPEN"
    append_ledger(sid, "FUND_OPEN", s["gross_fund_cents"], sid)
    append_ledger(sid, "FEE_DEBIT", -s["attorney_fee_cents"], sid)
    append_ledger(sid, "ADMIN_DEBIT", -s["admin_cost_cents"], sid)
    touch(s)
    return success(_public_settlement(s), 200)


@app.route("/settlements/<sid>/open-claims", methods=["POST"])
def open_claims(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    s = get_path(db.settlements, sid)
    if s["status"] != "NOTICE_OPEN":
        raise err(E.ERR_INVALID_STATE, "Settlement is not in NOTICE_OPEN.")
    has_member = any(m["settlement_id"] == sid for m in db.class_members.values())
    if not has_member:
        raise err(E.ERR_INVALID_STATE, "No class member exists under this settlement.")
    s["status"] = "CLAIMS_OPEN"
    touch(s)
    return success(_public_settlement(s), 200)


@app.route("/settlements/<sid>/close-claims", methods=["POST"])
def close_claims(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    s = get_path(db.settlements, sid)
    if s["status"] != "CLAIMS_OPEN":
        raise err(E.ERR_INVALID_STATE, "Settlement is not in CLAIMS_OPEN.")
    if db.now() < s["_claim_filing_deadline_dt"]:
        raise err(E.ERR_INVALID_STATE, "Clock has not reached the claim filing deadline.")
    s["status"] = "CLAIMS_CLOSED"
    # Sweep: every OPEN deficiency whose cure_deadline <= now -> EXPIRED, then
    # its claim -> REJECTED via the rejection cascade.
    now = db.now()
    claims_to_reject = set()
    for d in db.deficiencies.values():
        if d["status"] == "OPEN" and d["_cure_deadline_dt"] <= now:
            claims_to_reject.add(d["claim_id"])
    for cid in claims_to_reject:
        claim = db.claims.get(cid)
        if claim is None:
            continue
        if claim["status"] in {"SUBMITTED", "DEFICIENT", "CURED"}:
            _reject_claim_internal(claim)
    touch(s)
    return success(_public_settlement(s), 200)


@app.route("/settlements/<sid>/begin-distribution", methods=["POST"])
def begin_distribution(sid):
    _uid, role = auth()
    require_role(role, ["FundController"])
    s = get_path(db.settlements, sid)
    if s["status"] != "CLAIMS_CLOSED":
        raise err(E.ERR_INVALID_STATE, "Settlement is not in CLAIMS_CLOSED.")
    has_validated = any(
        c["settlement_id"] == sid and c["status"] == "VALIDATED"
        for c in db.claims.values()
    )
    if not has_validated:
        raise err(E.ERR_INVALID_STATE, "No VALIDATED claim exists to distribute.")
    s["status"] = "DISTRIBUTING"
    touch(s)
    return success(_public_settlement(s), 200)


@app.route("/settlements/<sid>/reconcile", methods=["POST"])
def reconcile(sid):
    _uid, role = auth()
    require_role(role, ["FundController"])
    s = get_path(db.settlements, sid)
    data = body()
    require_fields(data, ["expected_settlement_version"])
    # state
    if s["status"] != "DISTRIBUTING":
        raise err(E.ERR_INVALID_STATE, "Settlement is not in DISTRIBUTING.")
    # no batch left COMPUTED
    any_computed = any(
        b["settlement_id"] == sid and b["status"] == "COMPUTED"
        for b in db.distribution_batches.values()
    )
    if any_computed:
        raise err(E.ERR_INVALID_STATE, "A distribution batch is still COMPUTED.")
    residual = s["net_distributable_cents"] - s["allocated_cents"]
    sweep = (residual > 0 and residual < s["cy_pres_floor_cents"])
    # cy pres shares balance precondition (only matters when sweep runs)
    approved = [
        d for d in db.cy_pres_designations.values()
        if d["settlement_id"] == sid and d["status"] == "APPROVED"
    ]
    if sweep:
        if sum(d["share_bps"] for d in approved) != BPS_DENOMINATOR:
            raise err(E.ERR_CY_PRES_SHARES_UNBALANCED, "Approved cy pres shares do not sum to 10000.")
    # OCC (priority 18) — evaluated after the business checks above per §2.12 ordering
    expected = data["expected_settlement_version"]
    if expected != s["version"]:
        raise err(E.ERR_STALE_SETTLEMENT_VERSION, "Stale settlement version.")

    if sweep:
        funded = cy_pres_sweep(residual, approved)
        for d in approved:
            amt = funded[d["id"]]
            d["funded_cents"] = amt
            d["status"] = "FUNDED"
            touch(d)
            append_ledger(sid, "CY_PRES_DEBIT", -amt, d["id"])
        s["residual_cents"] = 0
    else:
        # residual <= 0 (zero) or >= floor: record the standing residual as-is.
        s["residual_cents"] = residual if residual > 0 else 0
    s["status"] = "RECONCILED"
    touch(s)
    return success(_public_settlement(s), 200)


@app.route("/settlements/<sid>/close", methods=["POST"])
def close_settlement(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    s = get_path(db.settlements, sid)
    if s["status"] != "RECONCILED":
        raise err(E.ERR_INVALID_STATE, "Settlement is not in RECONCILED.")
    if ledger_balance(sid) != 0:
        raise err(E.ERR_INVALID_STATE, "Ledger does not balance to zero.")
    s["status"] = "CLOSED"
    touch(s)
    return success(_public_settlement(s), 200)


@app.route("/settlements/<sid>/ledger-balance", methods=["GET"])
def get_ledger_balance(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin", "FundController"])
    s = get_path(db.settlements, sid)
    out = {
        "balance_cents": ledger_balance(sid),
        "net_distributable_cents": s["net_distributable_cents"],
        "allocated_cents": s["allocated_cents"],
        "residual_cents": s["residual_cents"],
    }
    return success(out, 200)


@app.route("/settlements/<sid>/ledger-entries", methods=["GET"])
def list_ledger_entries(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin", "FundController"])
    get_path(db.settlements, sid)
    entry_type = request.args.get("entry_type")
    rows = [e for e in db.ledger_entries.values() if e["settlement_id"] == sid]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


# ===========================================================================
# CLASS MEMBER + NOTICE
# ===========================================================================
@app.route("/settlements/<sid>/class-members", methods=["POST"])
def create_class_member(sid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator"])
    s = get_path(db.settlements, sid)
    data = body()
    check_enum(data, "claimant_tier")
    require_fields(data, ["full_name", "email"])
    email = data["email"]
    # unique email within settlement (priority 19)
    for m in db.class_members.values():
        if m["settlement_id"] == sid and m["email"] == email:
            raise err(E.ERR_DUPLICATE_MEMBER_EMAIL, "Email already registered in this settlement.")
    m = base_full()
    m.update({
        "settlement_id": sid,
        "full_name": data["full_name"],
        "email": email,
        "claimant_tier": data.get("claimant_tier") or "TIER_B",
        "tin_on_file": bool(data["tin_on_file"]) if data.get("tin_on_file") is not None else False,
        "status": "NOTIFIED",
        "notice_count": 0,
    })
    _ = s
    db.class_members[m["id"]] = m
    return success(ser(m), 201)


@app.route("/class-members/<mid>", methods=["GET"])
def get_class_member(mid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "ClaimsReviewer", "FundController", "Claimant"])
    m = get_path(db.class_members, mid)
    return success(ser(m), 200)


@app.route("/class-members", methods=["GET"])
def list_class_members():
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "ClaimsReviewer", "FundController"])
    settlement_id = request.args.get("settlement_id")
    status = request.args.get("status")
    rows = list(db.class_members.values())
    if settlement_id is not None:
        rows = [r for r in rows if r["settlement_id"] == settlement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/class-members/<mid>/notices", methods=["POST"])
def create_notice(mid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator"])
    m = get_path(db.class_members, mid)
    data = body()
    check_enum(data, "channel")
    check_enum(data, "delivery_status")
    require_fields(data, ["channel", "delivery_status"])
    n = base_lean()
    n.update({
        "class_member_id": mid,
        "channel": data["channel"],
        "delivery_status": data["delivery_status"],
    })
    db.notice_records[n["id"]] = n
    m["notice_count"] = m["notice_count"] + 1
    touch(m)
    return success(ser(n), 201)


@app.route("/class-members/<mid>/notices", methods=["GET"])
def list_notices(mid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "ClaimsReviewer"])
    get_path(db.class_members, mid)
    rows = [n for n in db.notice_records.values() if n["class_member_id"] == mid]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


# ===========================================================================
# CLAIM + DEFICIENCY
# ===========================================================================
def _create_claim(settlement_id, class_member_id, claimed_loss_cents, supersedes_claim_id):
    """Shared claim-creation logic. Assumes auth/role already checked.
    Validates per the priority order, builds the claim, promotes the member.
    """
    # priority 4: body FK existence
    settlement = get_fk(db.settlements, settlement_id)
    member = get_fk(db.class_members, class_member_id)
    if supersedes_claim_id is not None:
        get_fk(db.claims, supersedes_claim_id)
    # priority 5: member belongs to the named settlement
    if member["settlement_id"] != settlement_id:
        raise err(E.ERR_MEMBER_SETTLEMENT_MISMATCH, "Member does not belong to the named settlement.")
    # priority 7: settlement posture must be CLAIMS_OPEN
    if settlement["status"] != "CLAIMS_OPEN":
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not accepting claims.")
    # priority 8: claim window — strictly before claim_filing_deadline
    if db.now() >= settlement["_claim_filing_deadline_dt"]:
        raise err(E.ERR_CLAIM_WINDOW_CLOSED, "Claim filing window is closed.")
    # priority 12: excluded member cannot file
    if member["status"] == "EXCLUDED":
        raise err(E.ERR_MEMBER_EXCLUDED, "Excluded member cannot file a claim.")
    # priority 14: refile validity
    if supersedes_claim_id is not None:
        prior = db.claims[supersedes_claim_id]
        if prior["status"] != "REJECTED" or prior["class_member_id"] != class_member_id:
            raise err(E.ERR_INVALID_SUPERSEDE, "Superseded claim must be a REJECTED claim of the same member.")
        # the superseded claim cannot already be superseded
        if any(c["supersedes_claim_id"] == supersedes_claim_id for c in db.claims.values()):
            raise err(E.ERR_INVALID_SUPERSEDE, "That claim has already been superseded.")

    claimed = as_int(claimed_loss_cents)
    c = base_full()
    c.update({
        "settlement_id": settlement_id,
        "class_member_id": class_member_id,
        "supersedes_claim_id": supersedes_claim_id,
        "claimed_loss_cents": claimed,
        "recognized_loss_cents": 0,
        "status": "SUBMITTED",
        "open_deficiency_count": 0,
        "paid_amount_cents": 0,
        "validating_reviewer_id": None,
    })
    db.claims[c["id"]] = c
    maybe_promote_member_on_claim(member)
    return c


@app.route("/claims", methods=["POST"])
def create_claim():
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "Claimant"])
    data = body()
    require_fields(data, ["settlement_id", "class_member_id", "claimed_loss_cents"])
    c = _create_claim(
        data["settlement_id"], data["class_member_id"],
        data["claimed_loss_cents"], data.get("supersedes_claim_id"),
    )
    return success(ser_claim(c), 201)


@app.route("/class-members/<mid>/file-claim", methods=["POST"])
def file_claim_self(mid):
    uid, role = auth()
    require_role(role, ["Claimant"])
    # path member must exist (ERR_SETTLEMENT_NOT_FOUND)
    member = get_path(db.class_members, mid)
    # Claimant identity is entity-backed: X-User-ID must be the acting member.
    if uid != mid:
        raise err(E.ERR_FORBIDDEN_ROLE, "Claimant may only file for themselves.")
    _ = member
    data = body()
    require_fields(data, ["settlement_id", "claimed_loss_cents"])
    c = _create_claim(
        data["settlement_id"], mid,
        data["claimed_loss_cents"], data.get("supersedes_claim_id"),
    )
    return success(ser_claim(c), 201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    _uid, role = auth()
    require_role(role, ["ClaimsReviewer", "ClaimsAdministrator", "FundController", "Claimant"])
    c = get_path(db.claims, cid)
    return success(ser_claim(c), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    _uid, role = auth()
    require_role(role, ["ClaimsReviewer", "ClaimsAdministrator", "FundController"])
    rows = list(db.claims.values())
    for field in ("settlement_id", "class_member_id", "supersedes_claim_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser_claim(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/claims/<cid>/validate", methods=["POST"])
def validate_claim(cid):
    uid, role = auth()
    require_role(role, ["ClaimsReviewer"])
    c = get_path(db.claims, cid)
    data = body()
    require_fields(data, ["recognized_loss_cents"])
    # priority 6: state legality
    if c["status"] not in {"SUBMITTED", "CURED"}:
        raise err(E.ERR_INVALID_STATE, "Claim is not in a validatable state.")
    # owning settlement posture: CLAIMS_OPEN or CLAIMS_CLOSED
    settlement = db.settlements.get(c["settlement_id"])
    if settlement is None or settlement["status"] not in {"CLAIMS_OPEN", "CLAIMS_CLOSED"}:
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not in a validatable posture.")
    # priority 13: recognized <= claimed
    recognized = as_int(data["recognized_loss_cents"])
    if recognized > c["claimed_loss_cents"]:
        raise err(E.ERR_RECOGNIZED_EXCEEDS_CLAIMED, "recognized_loss_cents exceeds claimed_loss_cents.")
    # priority 22: deficiency blocks validation
    if c["open_deficiency_count"] != 0:
        raise err(E.ERR_VALIDATION_BLOCKED_BY_DEFICIENCY, "Open deficiency blocks validation.")
    c["recognized_loss_cents"] = recognized
    c["status"] = "VALIDATED"
    c["validating_reviewer_id"] = uid
    touch(c)
    return success(ser_claim(c), 200)


def _reject_claim_internal(c):
    """Drive a claim to REJECTED: expire OPEN deficiencies, reset count, demote member."""
    c["status"] = "REJECTED"
    for d in db.deficiencies.values():
        if d["claim_id"] == c["id"] and d["status"] == "OPEN":
            d["status"] = "EXPIRED"
            touch(d)
    c["open_deficiency_count"] = 0
    touch(c)
    maybe_demote_member_after_rejection(c["class_member_id"])


@app.route("/claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    _uid, role = auth()
    require_role(role, ["ClaimsReviewer"])
    c = get_path(db.claims, cid)
    if c["status"] not in {"SUBMITTED", "DEFICIENT", "CURED"}:
        raise err(E.ERR_INVALID_STATE, "Claim cannot be rejected from its current state.")
    _reject_claim_internal(c)
    return success(ser_claim(c), 200)


@app.route("/claims/<cid>/cure", methods=["POST"])
def cure_claim(cid):
    _uid, role = auth()
    require_role(role, ["Claimant", "ClaimsAdministrator"])
    c = get_path(db.claims, cid)
    if c["status"] != "DEFICIENT":
        raise err(E.ERR_INVALID_STATE, "Claim is not DEFICIENT.")
    now = db.now()
    open_defs = [
        d for d in db.deficiencies.values()
        if d["claim_id"] == cid and d["status"] == "OPEN"
    ]
    # priority 10: every OPEN deficiency cure_deadline strictly after the clock
    for d in open_defs:
        if now >= d["_cure_deadline_dt"]:
            raise err(E.ERR_CURE_WINDOW_CLOSED, "A deficiency cure window has closed.")
    for d in open_defs:
        d["status"] = "CURED"
        touch(d)
    c["open_deficiency_count"] = 0
    c["status"] = "CURED"
    touch(c)
    return success(ser_claim(c), 200)


@app.route("/claims/<cid>/deficiencies", methods=["POST"])
def raise_deficiency(cid):
    _uid, role = auth()
    require_role(role, ["ClaimsReviewer"])
    c = get_path(db.claims, cid)
    data = body()
    check_enum(data, "reason_code")
    require_fields(data, ["reason_code", "cure_deadline"])
    if c["status"] not in {"SUBMITTED", "CURED"}:
        raise err(E.ERR_INVALID_STATE, "Deficiency may only be raised on a SUBMITTED or CURED claim.")
    cure_dt = parse_dt(data["cure_deadline"])
    d = base_full()
    d.update({
        "claim_id": cid,
        "reason_code": data["reason_code"],
        "cure_deadline": data["cure_deadline"],
        "status": "OPEN",
        "_cure_deadline_dt": cure_dt,
    })
    db.deficiencies[d["id"]] = d
    c["open_deficiency_count"] = c["open_deficiency_count"] + 1
    c["status"] = "DEFICIENT"
    touch(c)
    return success(_ser_deficiency(d), 201)


def _ser_deficiency(d):
    return {k: v for k, v in d.items() if not k.startswith("_") and k != "_seq"}


@app.route("/claims/<cid>/deficiencies", methods=["GET"])
def list_deficiencies(cid):
    _uid, role = auth()
    require_role(role, ["ClaimsReviewer", "ClaimsAdministrator", "Claimant"])
    get_path(db.claims, cid)
    status = request.args.get("status")
    rows = [d for d in db.deficiencies.values() if d["claim_id"] == cid]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = paginate([_ser_deficiency(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/deficiencies/<did>", methods=["GET"])
def get_deficiency(did):
    _uid, role = auth()
    require_role(role, ["ClaimsReviewer", "ClaimsAdministrator", "Claimant"])
    d = get_path(db.deficiencies, did)
    return success(_ser_deficiency(d), 200)


# ===========================================================================
# OPT-OUT + OBJECTION
# ===========================================================================
@app.route("/opt-outs", methods=["POST"])
def create_optout():
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "Claimant"])
    data = body()
    require_fields(data, ["settlement_id", "class_member_id"])
    settlement = get_fk(db.settlements, data["settlement_id"])
    member = get_fk(db.class_members, data["class_member_id"])
    # priority 5: membership
    if member["settlement_id"] != data["settlement_id"]:
        raise err(E.ERR_MEMBER_SETTLEMENT_MISMATCH, "Member does not belong to the named settlement.")
    # priority 7: posture NOTICE_OPEN or CLAIMS_OPEN
    if settlement["status"] not in {"NOTICE_OPEN", "CLAIMS_OPEN"}:
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not accepting opt-outs.")
    # priority 9: objection/opt-out window — strictly before objection_deadline
    if db.now() >= settlement["_objection_deadline_dt"]:
        raise err(E.ERR_OBJECTION_WINDOW_CLOSED, "Opt-out window is closed.")
    o = base_full()
    o.update({
        "settlement_id": data["settlement_id"],
        "class_member_id": data["class_member_id"],
        "status": "REQUESTED",
    })
    db.opt_outs[o["id"]] = o
    return success(ser(o), 201)


@app.route("/opt-outs/<oid>", methods=["GET"])
def get_optout(oid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "Claimant", "FundController"])
    o = get_path(db.opt_outs, oid)
    return success(ser(o), 200)


@app.route("/opt-outs", methods=["GET"])
def list_optouts():
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "FundController"])
    rows = list(db.opt_outs.values())
    for field in ("settlement_id", "class_member_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/opt-outs/<oid>/finalize", methods=["POST"])
def finalize_optout(oid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator"])
    o = get_path(db.opt_outs, oid)
    if o["status"] != "REQUESTED":
        raise err(E.ERR_INVALID_STATE, "Opt-out is not REQUESTED.")
    settlement = db.settlements.get(o["settlement_id"])
    if settlement is None or settlement["status"] not in {"NOTICE_OPEN", "CLAIMS_OPEN"}:
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement posture does not permit finalize.")
    # priority 11: member must have no non-REJECTED claim
    if member_has_non_rejected_claim(o["class_member_id"]):
        raise err(E.ERR_MEMBER_HAS_CLAIM, "Member holds a non-REJECTED claim.")
    o["status"] = "EFFECTIVE"
    touch(o)
    member = db.class_members.get(o["class_member_id"])
    if member is not None:
        member["status"] = "EXCLUDED"
        touch(member)
    return success(ser(o), 200)


@app.route("/opt-outs/<oid>/revoke", methods=["POST"])
def revoke_optout(oid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator"])
    o = get_path(db.opt_outs, oid)
    if o["status"] != "EFFECTIVE":
        raise err(E.ERR_INVALID_STATE, "Opt-out is not EFFECTIVE.")
    settlement = db.settlements.get(o["settlement_id"])
    if settlement is None or settlement["status"] not in {"NOTICE_OPEN", "CLAIMS_OPEN"}:
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement posture does not permit revoke.")
    o["status"] = "REVOKED"
    touch(o)
    member = db.class_members.get(o["class_member_id"])
    if member is not None:
        member["status"] = "NOTIFIED"
        touch(member)
    return success(ser(o), 200)


@app.route("/objections", methods=["POST"])
def create_objection():
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "Claimant"])
    data = body()
    require_fields(data, ["settlement_id", "class_member_id", "grounds"])
    settlement = get_fk(db.settlements, data["settlement_id"])
    member = get_fk(db.class_members, data["class_member_id"])
    if member["settlement_id"] != data["settlement_id"]:
        raise err(E.ERR_MEMBER_SETTLEMENT_MISMATCH, "Member does not belong to the named settlement.")
    # posture: objection requires the window still open -> NOTICE_OPEN or CLAIMS_OPEN
    if settlement["status"] not in {"NOTICE_OPEN", "CLAIMS_OPEN"}:
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not accepting objections.")
    if db.now() >= settlement["_objection_deadline_dt"]:
        raise err(E.ERR_OBJECTION_WINDOW_CLOSED, "Objection window is closed.")
    o = base_full()
    o.update({
        "settlement_id": data["settlement_id"],
        "class_member_id": data["class_member_id"],
        "grounds": data["grounds"],
        "status": "FILED",
    })
    db.objections[o["id"]] = o
    return success(ser(o), 201)


@app.route("/objections/<oid>", methods=["GET"])
def get_objection(oid):
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "Claimant", "Court", "FundController"])
    o = get_path(db.objections, oid)
    return success(ser(o), 200)


@app.route("/objections", methods=["GET"])
def list_objections():
    _uid, role = auth()
    require_role(role, ["ClaimsAdministrator", "Court", "FundController"])
    rows = list(db.objections.values())
    for field in ("settlement_id", "class_member_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/objections/<oid>/rule", methods=["POST"])
def rule_objection(oid):
    _uid, role = auth()
    require_role(role, ["Court"])
    o = get_path(db.objections, oid)
    data = body()
    check_enum(data, "ruling")
    require_fields(data, ["ruling"])
    if o["status"] != "FILED":
        raise err(E.ERR_INVALID_STATE, "Objection is not FILED.")
    o["status"] = data["ruling"]  # SUSTAINED or OVERRULED (enum-validated)
    touch(o)
    return success(ser(o), 200)


@app.route("/objections/<oid>/withdraw", methods=["POST"])
def withdraw_objection(oid):
    uid, role = auth()
    require_role(role, ["Claimant"])
    o = get_path(db.objections, oid)
    if o["status"] != "FILED":
        raise err(E.ERR_INVALID_STATE, "Objection is not FILED.")
    # only the objecting member (by X-User-ID) may withdraw
    if o["class_member_id"] != uid:
        raise err(E.ERR_FORBIDDEN_ROLE, "Only the objecting member may withdraw.")
    o["status"] = "WITHDRAWN"
    touch(o)
    return success(ser(o), 200)


# ===========================================================================
# DISTRIBUTION BATCH + PAYMENT + TAX FORM
# ===========================================================================
@app.route("/distribution-batches", methods=["POST"])
def create_batch():
    _uid, role = auth()
    require_role(role, ["FundController"])
    data = body()
    require_fields(data, ["settlement_id", "sequence_no"])
    settlement = get_fk(db.settlements, data["settlement_id"])
    if settlement["status"] != "DISTRIBUTING":
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not DISTRIBUTING.")
    b = base_full()
    b.update({
        "settlement_id": data["settlement_id"],
        "sequence_no": as_int(data["sequence_no"]),
        "status": "DRAFT",
        "planned_total_cents": 0,
        "posted_total_cents": 0,
        "residual_after_cents": 0,
    })
    db.distribution_batches[b["id"]] = b
    return success(ser(b), 201)


@app.route("/distribution-batches/<bid>", methods=["GET"])
def get_batch(bid):
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin"])
    b = get_path(db.distribution_batches, bid)
    return success(ser(b), 200)


@app.route("/distribution-batches", methods=["GET"])
def list_batches():
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin"])
    rows = list(db.distribution_batches.values())
    for field in ("settlement_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


def eligible_claims(settlement_id):
    """VALIDATED, paid_amount_cents==0, owning member PARTICIPATING; created_at ASC."""
    rows = []
    for c in db.claims.values():
        if c["settlement_id"] != settlement_id:
            continue
        if c["status"] != "VALIDATED" or c["paid_amount_cents"] != 0:
            continue
        m = db.class_members.get(c["class_member_id"])
        if m is None or m["status"] != "PARTICIPATING":
            continue
        rows.append(c)
    return sorted(rows, key=lambda r: r["_seq"])


def distribution_allocation(settlement, eligible):
    """Returns {claim_id: gross} per the calculation in scaffold §1.3."""
    gross = {}
    remaining = settlement["net_distributable_cents"] - settlement["allocated_cents"]
    if settlement["distribution_method"] == "PRO_RATA":
        total = sum(c["recognized_loss_cents"] for c in eligible)
        # exact weighted share via integer floor; largest-remainder for leftover.
        floors = {}
        fracs = {}  # numerator of fractional part: (remaining*loss) mod total
        for c in eligible:
            num = remaining * c["recognized_loss_cents"]
            floors[c["id"]] = num // total
            fracs[c["id"]] = num % total
        leftover = remaining - sum(floors.values())
        for cid in floors:
            gross[cid] = floors[cid]
        # leftover cents one each: fractional part DESC, ties by created_at ASC.
        order = sorted(
            eligible,
            key=lambda c: (-fracs[c["id"]], c["_seq"]),
        )
        i = 0
        while leftover > 0 and i < len(order):
            gross[order[i]["id"]] += 1
            leftover -= 1
            i += 1
    else:  # TIERED
        for c in sorted(eligible, key=lambda r: (r["_seq"], r["id"])):
            m = db.class_members.get(c["class_member_id"])
            tier = m["claimant_tier"] if m else "TIER_B"
            tier_amt = settlement["tier_a_amount_cents"] if tier == "TIER_A" else settlement["tier_b_amount_cents"]
            gross[c["id"]] = tier_amt
    return gross


def cy_pres_sweep(residual, approved):
    """Returns {designation_id: funded} per scaffold §1.3 cy_pres_sweep."""
    recipients = sorted(approved, key=lambda r: r["_seq"])
    floors = {}
    fracs = {}
    for r in recipients:
        num = residual * r["share_bps"]
        floors[r["id"]] = num // BPS_DENOMINATOR
        fracs[r["id"]] = num % BPS_DENOMINATOR
    leftover = residual - sum(floors.values())
    funded = dict(floors)
    order = sorted(recipients, key=lambda r: (-fracs[r["id"]], r["_seq"]))
    i = 0
    while leftover > 0 and i < len(order):
        funded[order[i]["id"]] += 1
        leftover -= 1
        i += 1
    return funded


@app.route("/distribution-batches/<bid>/compute", methods=["POST"])
def compute_batch(bid):
    _uid, role = auth()
    require_role(role, ["FundController"])
    b = get_path(db.distribution_batches, bid)
    if b["status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Batch is not DRAFT.")
    settlement = db.settlements.get(b["settlement_id"])
    if settlement is None or settlement["status"] != "DISTRIBUTING":
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not DISTRIBUTING.")
    eligible = eligible_claims(b["settlement_id"])
    gross_map = distribution_allocation(settlement, eligible)
    planned_total = 0
    for c in eligible:
        g = gross_map[c["id"]]
        m = db.class_members.get(c["class_member_id"])
        tin = m["tin_on_file"] if m else False
        if (not tin) and g >= TAX_REPORTING_THRESHOLD_CENTS:
            withholding = (g * BACKUP_WITHHOLDING_BPS) // BPS_DENOMINATOR
        else:
            withholding = 0
        amount = g - withholding
        p = base_full()
        p.update({
            "distribution_batch_id": bid,
            "claim_id": c["id"],
            "gross_amount_cents": g,
            "withholding_cents": withholding,
            "amount_cents": amount,
            "status": "PLANNED",
        })
        db.payments[p["id"]] = p
        planned_total += amount
    b["planned_total_cents"] = planned_total
    b["status"] = "COMPUTED"
    touch(b)
    return success(ser(b), 200)


def batch_payments(bid):
    return [p for p in db.payments.values() if p["distribution_batch_id"] == bid]


@app.route("/distribution-batches/<bid>/post", methods=["POST"])
def post_batch(bid):
    uid, role = auth()
    require_role(role, ["FundController"])
    b = get_path(db.distribution_batches, bid)
    data = body()
    require_fields(data, ["expected_settlement_version"])
    if b["status"] != "COMPUTED":
        raise err(E.ERR_INVALID_STATE, "Batch is not COMPUTED.")
    settlement = db.settlements.get(b["settlement_id"])
    if settlement is None:
        raise err(E.ERR_SETTLEMENT_NOT_FOUND, "Settlement not found.")
    payments = batch_payments(bid)
    # priority 15: segregation of duties — posting FC != reviewer who validated any claim
    for p in payments:
        claim = db.claims.get(p["claim_id"])
        if claim is not None and claim.get("validating_reviewer_id") == uid:
            raise err(E.ERR_SEGREGATION_OF_DUTIES, "Posting controller validated a claim in this batch.")
    # priority 18: OCC
    if data["expected_settlement_version"] != settlement["version"]:
        raise err(E.ERR_STALE_SETTLEMENT_VERSION, "Stale settlement version.")
    # priority 17: fund capacity
    headroom = settlement["net_distributable_cents"] - settlement["allocated_cents"]
    if b["planned_total_cents"] > headroom:
        raise err(E.ERR_FUND_EXCEEDED, "Batch planned total exceeds remaining fund headroom.")

    # commit
    for p in payments:
        p["status"] = "COMMITTED"
        touch(p)
        claim = db.claims.get(p["claim_id"])
        if claim is not None:
            claim["paid_amount_cents"] = p["amount_cents"]
            claim["status"] = "PAID"
            touch(claim)
        append_ledger(b["settlement_id"], "PAYMENT_DEBIT", -p["amount_cents"], p["id"])
        # tax forms for qualifying payments
        m = db.class_members.get(claim["class_member_id"]) if claim is not None else None
        tin = m["tin_on_file"] if m else False
        if (not tin) and p["gross_amount_cents"] >= TAX_REPORTING_THRESHOLD_CENTS:
            t = base_full()
            t.update({
                "payment_id": p["id"],
                "class_member_id": claim["class_member_id"] if claim else None,
                "form_type": "1099_MISC",
                "reportable_cents": p["gross_amount_cents"],
                "withheld_cents": p["withholding_cents"],
                "status": "ISSUED",
            })
            db.tax_forms[t["id"]] = t
    posted_total = sum(p["amount_cents"] for p in payments)
    settlement["allocated_cents"] = settlement["allocated_cents"] + posted_total
    b["posted_total_cents"] = b["planned_total_cents"]
    b["residual_after_cents"] = settlement["net_distributable_cents"] - settlement["allocated_cents"]
    b["status"] = "POSTED"
    touch(b)
    touch(settlement)
    return success(ser(b), 200)


@app.route("/distribution-batches/<bid>/void", methods=["POST"])
def void_batch(bid):
    _uid, role = auth()
    require_role(role, ["FundController"])
    b = get_path(db.distribution_batches, bid)
    if b["status"] != "COMPUTED":
        raise err(E.ERR_INVALID_STATE, "Batch is not COMPUTED.")
    for p in batch_payments(bid):
        if p["status"] == "PLANNED":
            p["status"] = "CANCELLED"
            touch(p)
    b["status"] = "VOID"
    touch(b)
    return success(ser(b), 200)


@app.route("/distribution-batches/<bid>/reverse", methods=["POST"])
def reverse_batch(bid):
    _uid, role = auth()
    require_role(role, ["FundController"])
    b = get_path(db.distribution_batches, bid)
    if b["status"] != "POSTED":
        raise err(E.ERR_INVALID_STATE, "Batch is not POSTED.")
    settlement = db.settlements.get(b["settlement_id"])
    if settlement is None or settlement["status"] != "DISTRIBUTING":
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement is not DISTRIBUTING.")
    payments = batch_payments(bid)
    # precondition: no TaxForm referencing a payment in this batch is VOIDED
    payment_ids = {p["id"] for p in payments}
    for t in db.tax_forms.values():
        if t["payment_id"] in payment_ids and t["status"] == "VOIDED":
            raise err(E.ERR_INVALID_STATE, "A tax form in this batch is already voided.")
    for p in payments:
        if p["status"] == "COMMITTED":
            p["status"] = "REVERSED"
            touch(p)
            claim = db.claims.get(p["claim_id"])
            if claim is not None and claim["status"] == "PAID":
                claim["status"] = "VALIDATED"
                claim["paid_amount_cents"] = 0
                touch(claim)
            append_ledger(b["settlement_id"], "PAYMENT_REVERSAL_CREDIT", p["amount_cents"], p["id"])
    settlement["allocated_cents"] = settlement["allocated_cents"] - b["posted_total_cents"]
    for t in db.tax_forms.values():
        if t["payment_id"] in payment_ids and t["status"] in {"ISSUED", "CORRECTED"}:
            t["status"] = "VOIDED"
            touch(t)
    b["status"] = "REVERSED"
    touch(b)
    touch(settlement)
    return success(ser(b), 200)


@app.route("/distribution-batches/<bid>/payments", methods=["GET"])
def list_batch_payments(bid):
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin"])
    get_path(db.distribution_batches, bid)
    status = request.args.get("status")
    rows = [p for p in db.payments.values() if p["distribution_batch_id"] == bid]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin", "ClaimsReviewer"])
    p = get_path(db.payments, pid)
    return success(ser(p), 200)


@app.route("/payments", methods=["GET"])
def list_payments():
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin", "ClaimsReviewer"])
    rows = list(db.payments.values())
    for field in ("claim_id", "distribution_batch_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/tax-forms/<tid>", methods=["GET"])
def get_tax_form(tid):
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin"])
    t = get_path(db.tax_forms, tid)
    return success(ser(t), 200)


@app.route("/tax-forms", methods=["GET"])
def list_tax_forms():
    _uid, role = auth()
    require_role(role, ["FundController", "SettlementAdmin"])
    rows = list(db.tax_forms.values())
    for field in ("payment_id", "class_member_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/tax-forms/<tid>/correct", methods=["POST"])
def correct_tax_form(tid):
    _uid, role = auth()
    require_role(role, ["FundController"])
    t = get_path(db.tax_forms, tid)
    if t["status"] != "ISSUED":
        raise err(E.ERR_INVALID_STATE, "Tax form is not ISSUED.")
    p = db.payments.get(t["payment_id"])
    if p is None or p["status"] != "COMMITTED":
        raise err(E.ERR_INVALID_STATE, "Referenced payment is not COMMITTED.")
    t["reportable_cents"] = p["gross_amount_cents"]
    t["withheld_cents"] = p["withholding_cents"]
    t["status"] = "CORRECTED"
    touch(t)
    return success(ser(t), 200)


# ===========================================================================
# CY PRES DESIGNATION
# ===========================================================================
@app.route("/settlements/<sid>/cy-pres-designations", methods=["POST"])
def create_cy_pres(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    s = get_path(db.settlements, sid)
    data = body()
    require_fields(data, ["recipient_name", "share_bps"])
    share = as_int(data["share_bps"])
    _ = s
    d = base_full()
    d.update({
        "settlement_id": sid,
        "recipient_name": data["recipient_name"],
        "share_bps": share,
        "status": "PROPOSED",
        "funded_cents": 0,
    })
    db.cy_pres_designations[d["id"]] = d
    return success(ser(d), 201)


@app.route("/cy-pres-designations/<did>", methods=["GET"])
def get_cy_pres(did):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin", "FundController", "Court"])
    d = get_path(db.cy_pres_designations, did)
    return success(ser(d), 200)


@app.route("/settlements/<sid>/cy-pres-designations", methods=["GET"])
def list_cy_pres(sid):
    _uid, role = auth()
    require_role(role, ["SettlementAdmin", "FundController", "Court"])
    get_path(db.settlements, sid)
    status = request.args.get("status")
    rows = [d for d in db.cy_pres_designations.values() if d["settlement_id"] == sid]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = paginate([ser(r) for r in rows])
    return success(page, 200, pagination=meta)


@app.route("/cy-pres-designations/<did>/approve", methods=["POST"])
def approve_cy_pres(did):
    _uid, role = auth()
    require_role(role, ["Court"])
    d = get_path(db.cy_pres_designations, did)
    if d["status"] != "PROPOSED":
        raise err(E.ERR_INVALID_STATE, "Designation is not PROPOSED.")
    settlement = db.settlements.get(d["settlement_id"])
    allowed = {"DRAFT", "NOTICE_OPEN", "CLAIMS_OPEN", "CLAIMS_CLOSED", "DISTRIBUTING"}
    if settlement is None or settlement["status"] not in allowed:
        raise err(E.ERR_SETTLEMENT_POSTURE_INVALID, "Settlement posture does not permit approval.")
    d["status"] = "APPROVED"
    touch(d)
    return success(ser(d), 200)


@app.route("/cy-pres-designations/<did>/revoke", methods=["POST"])
def revoke_cy_pres(did):
    _uid, role = auth()
    require_role(role, ["Court"])
    d = get_path(db.cy_pres_designations, did)
    if d["status"] != "PROPOSED":
        raise err(E.ERR_INVALID_STATE, "Designation is not PROPOSED.")
    d["status"] = "REVOKED"
    touch(d)
    return success(ser(d), 200)


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = auth()
    require_role(role, ["SettlementAdmin"])
    data = body()
    require_fields(data, ["to_iso8601"])
    dt = parse_dt(data["to_iso8601"])
    db.set_clock(dt)
    return success({"current_utc": db.iso_now_ms()}, 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
