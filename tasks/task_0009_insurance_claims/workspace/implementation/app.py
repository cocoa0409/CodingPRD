"""Flask app for the insurance-claims API."""
import os
import re
from datetime import timedelta
from decimal import Decimal

from flask import Flask, g, request

from core import (
    ADMIN_TOKEN,
    AUTO_APPROVAL_THRESHOLD_CENTS,
    AUTO_FRAUD_GATE,
    FRAUD_HOLD_GATE,
    LOCK,
    ROLE_ADJUSTER,
    ROLE_CUSTOMER,
    ROLE_PAYOUT_OFFICER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVIEWER,
    ApiError,
    bump,
    db,
    err,
    error_response,
    get_json_body,
    get_or_404,
    iso_z,
    new_id,
    new_request_id,
    now_iso,
    ok,
    paginate,
    parse_auth,
    parse_iso,
    parse_pagination,
    require_admin_token,
    require_enum,
    require_field,
    require_int,
    require_roles,
    require_str,
    server_now,
    stamp_create,
    stamp_create_immutable,
)
from domain import (
    apply_repair_shop_decay_for_claim,
    compute_fraud_score,
    compute_gross_payout,
    compute_net_payout,
    estimate_lines_for_inv,
    get_active_investigation,
    get_appeal_for_claim,
    get_open_investigation,
    get_payout_for_claim,
    log_audit,
    mint_claim_number,
    primary_review_decision,
    projected_pattern_threshold_score,
    whole_days_between,
)


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------
@app.before_request
def _before():
    g.api_request_id = new_request_id()
    LOCK.acquire()


@app.teardown_request
def _teardown(_exc):
    try:
        LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _on_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _flask_404(_e):
    # Distinguish "endpoint does not exist" from "resource not found" — both 404,
    # but use the canonical error_id so clients get a stable code.
    return error_response(err("ERR_NOT_FOUND", "route not found"))


@app.errorhandler(405)
def _flask_405(_e):
    return error_response(err("ERR_FORBIDDEN", "method not allowed"))


@app.errorhandler(Exception)
def _flask_exc(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_VALIDATION_FAILED", str(e), http_status=400))


@app.get("/healthz")
def healthz():
    return ok({"status": "ok"})


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------
def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items):
    return [serialize(x) for x in items]


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
_POLICY_NUMBER_RE = re.compile(r"^[A-Z0-9]{8,24}$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _validate_policy_number(s: str):
    if not _POLICY_NUMBER_RE.match(s):
        raise err("ERR_VALIDATION_FAILED", "policy_number must be 8-24 uppercase alphanumeric")


def _ratio(value):
    try:
        v = Decimal(str(value))
    except Exception:
        raise err("ERR_VALIDATION_FAILED", "coinsurance_ratio must be numeric")
    if v < Decimal("0") or v > Decimal("1"):
        raise err("ERR_VALIDATION_FAILED", "coinsurance_ratio must be in [0,1]")
    # Quantize to 4 decimal places
    return float(v.quantize(Decimal("0.0001")))


def _require_unique(value, by_iter, label, error_id="ERR_VALIDATION_FAILED"):
    for x in by_iter:
        if x == value:
            raise err(error_id, f"duplicate {label}: {value}")


# ===========================================================================
# Policies
# ===========================================================================
@app.post("/policies")
def create_policy():
    require_roles(ROLE_PLATFORM_ADMIN)
    body = get_json_body()
    policy_number = require_str(body, "policy_number")
    _validate_policy_number(policy_number)
    insured_party_id = require_str(body, "insured_party_id")
    coverage_type = require_enum(body, "coverage_type", {"AUTO", "PROPERTY", "LIABILITY"})
    coverage_limit_cents = require_int(body, "coverage_limit_cents", ge=0)
    deductible_cents = require_int(body, "deductible_cents", ge=0)
    coinsurance_ratio = _ratio(require_field(body, "coinsurance_ratio"))
    effective_from_s = require_str(body, "effective_from")
    effective_to_s = require_str(body, "effective_to")
    eff_from = parse_iso(effective_from_s)
    eff_to = parse_iso(effective_to_s)
    if eff_to <= eff_from:
        raise err("ERR_VALIDATION_FAILED", "effective_to must be after effective_from")
    reporting_window_days = body.get("reporting_window_days", 30)
    if reporting_window_days is None:
        reporting_window_days = 30
    try:
        reporting_window_days = int(reporting_window_days)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION_FAILED", "reporting_window_days must be integer")
    if reporting_window_days < 1:
        raise err("ERR_VALIDATION_FAILED", "reporting_window_days must be >= 1")

    # Uniqueness on policy_number
    for p in db.policies.values():
        if p["policy_number"] == policy_number:
            raise err("ERR_VALIDATION_FAILED", "policy_number already exists")

    rec = stamp_create()
    rec.update(
        {
            "policy_number": policy_number,
            "insured_party_id": insured_party_id,
            "coverage_type": coverage_type,
            "coverage_limit_cents": coverage_limit_cents,
            "deductible_cents": deductible_cents,
            "coinsurance_ratio": coinsurance_ratio,
            "effective_from": iso_z(eff_from),
            "effective_to": iso_z(eff_to),
            "reporting_window_days": reporting_window_days,
            "status": "ACTIVE",
        }
    )
    db.policies[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/policies/<pid>")
def get_policy(pid):
    user_id, role = require_roles(
        ROLE_PLATFORM_ADMIN, ROLE_CUSTOMER, ROLE_ADJUSTER, ROLE_REVIEWER, ROLE_PAYOUT_OFFICER
    )
    rec = get_or_404(db.policies, pid, "Policy")
    if role == ROLE_CUSTOMER and rec["insured_party_id"] != user_id:
        raise err("ERR_FORBIDDEN", "not own policy")
    return ok(serialize(rec))


@app.patch("/policies/<pid>")
def patch_policy(pid):
    require_roles(ROLE_PLATFORM_ADMIN)
    rec = get_or_404(db.policies, pid, "Policy")
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(rec.get("version", 1)):
            raise err("ERR_VERSION_CONFLICT")
    changed = False
    if "status" in body and body["status"] is not None:
        st = body["status"]
        if st not in ("ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED"):
            raise err("ERR_VALIDATION_FAILED", "invalid status")
        if rec["status"] != st:
            rec["status"] = st
            changed = True
    if changed:
        bump(rec)
    return ok(serialize(rec))


# ===========================================================================
# Adjusters
# ===========================================================================
@app.post("/adjusters")
def create_adjuster():
    require_roles(ROLE_PLATFORM_ADMIN)
    body = get_json_body()
    full_name = require_str(body, "full_name")
    license_number = require_str(body, "license_number")
    specialty = require_enum(body, "specialty", {"AUTO", "PROPERTY", "LIABILITY"})
    for a in db.adjusters.values():
        if a["license_number"] == license_number:
            raise err("ERR_VALIDATION_FAILED", "license_number already exists")
    rec = stamp_create()
    rec.update(
        {
            "full_name": full_name,
            "license_number": license_number,
            "specialty": specialty,
            "status": "ACTIVE",
        }
    )
    db.adjusters[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/adjusters")
def list_adjusters():
    require_roles(ROLE_PLATFORM_ADMIN, ROLE_REVIEWER)
    limit, offset = parse_pagination()
    items = list(db.adjusters.values())
    status_f = request.args.get("status")
    spec_f = request.args.get("specialty")
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if spec_f is not None:
        items = [a for a in items if a["specialty"] == spec_f]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


@app.patch("/adjusters/<aid>")
def patch_adjuster(aid):
    require_roles(ROLE_PLATFORM_ADMIN)
    rec = get_or_404(db.adjusters, aid, "Adjuster")
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(rec.get("version", 1)):
            raise err("ERR_VERSION_CONFLICT")
    changed = False
    if "status" in body and body["status"] is not None:
        st = body["status"]
        if st not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_VALIDATION_FAILED", "invalid status")
        if rec["status"] != st:
            rec["status"] = st
            changed = True
    if changed:
        bump(rec)
    return ok(serialize(rec))


# ===========================================================================
# Repair shops
# ===========================================================================
@app.post("/repair-shops")
def create_repair_shop():
    require_roles(ROLE_PLATFORM_ADMIN)
    body = get_json_body()
    name = require_str(body, "name")
    tax_id = require_str(body, "tax_id")
    for s in db.repair_shops.values():
        if s["tax_id"] == tax_id:
            raise err("ERR_VALIDATION_FAILED", "tax_id already exists")
    rec = stamp_create()
    rec.update(
        {
            "name": name,
            "tax_id": tax_id,
            "trust_score": 1.00,
            "status": "ACTIVE",
        }
    )
    db.repair_shops[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/repair-shops/<sid>")
def get_repair_shop(sid):
    require_roles(ROLE_PLATFORM_ADMIN, ROLE_ADJUSTER, ROLE_REVIEWER)
    rec = get_or_404(db.repair_shops, sid, "RepairShop")
    projection = request.args.get("projection")
    if projection == "pattern_threshold":
        # PRD §3.5: pattern_threshold projection returns a what-if `trust_score`
        # (the smaller of the current trust_score and 0.20 when 3+ collusion
        # flags exist within the 90-day lookback). State is not mutated.
        view = serialize(rec)
        view["trust_score"] = projected_pattern_threshold_score(rec)
        view["projection"] = "pattern_threshold"
        return ok(view)
    return ok(serialize(rec))


@app.patch("/repair-shops/<sid>")
def patch_repair_shop(sid):
    require_roles(ROLE_PLATFORM_ADMIN)
    rec = get_or_404(db.repair_shops, sid, "RepairShop")
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(rec.get("version", 1)):
            raise err("ERR_VERSION_CONFLICT")
    # Admin override cannot raise trust_score (only canonical decay moves it).
    if "trust_score" in body and body["trust_score"] is not None:
        try:
            new_score = Decimal(str(body["trust_score"]))
        except Exception:
            raise err("ERR_VALIDATION_FAILED", "bad trust_score")
        if new_score > Decimal(str(rec["trust_score"])):
            raise err("ERR_VALIDATION_FAILED", "admin cannot raise trust_score")
    changed = False
    if "status" in body and body["status"] is not None:
        st = body["status"]
        if st not in ("ACTIVE", "BLACKLISTED"):
            raise err("ERR_VALIDATION_FAILED", "invalid status")
        if rec["status"] != st:
            rec["status"] = st
            changed = True
    if changed:
        bump(rec)
    return ok(serialize(rec))


# ===========================================================================
# Claims — intake & retrieval
# ===========================================================================
def _customer_owns_policy(user_id, policy):
    return policy["insured_party_id"] == user_id


def _customer_owns_claim(user_id, claim):
    return claim["claimant_id"] == user_id


@app.post("/claims")
def create_claim():
    user_id, role = require_roles(ROLE_CUSTOMER)
    body = get_json_body()
    policy_id = require_str(body, "policy_id")
    report_channel = require_enum(body, "report_channel", {"WEB", "MOBILE", "PHONE", "AGENT"})
    idempotency_key = require_str(body, "idempotency_key")
    loss_date_s = require_str(body, "loss_date")
    incident_description = require_str(body, "incident_description")
    claimed_amount_cents = require_int(body, "claimed_amount_cents", gt=0)
    salvage_value_cents = body.get("salvage_value_cents", 0)
    if salvage_value_cents is None:
        salvage_value_cents = 0
    try:
        salvage_value_cents = int(salvage_value_cents)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION_FAILED", "salvage_value_cents must be integer")
    if salvage_value_cents < 0:
        raise err("ERR_VALIDATION_FAILED", "salvage_value_cents must be >= 0")

    loss_date = parse_iso(loss_date_s)

    # Priority 5: policy must exist and be ACTIVE
    policy = db.policies.get(policy_id)
    if not policy:
        # Per PRD §2.6 the cascade puts the policy_inactive check at this slot;
        # a non-existent policy_id at intake is a domain-validity failure too.
        raise err("ERR_POLICY_INACTIVE", "policy not found or inactive")
    if not _customer_owns_policy(user_id, policy):
        raise err("ERR_FORBIDDEN", "policy not owned by claimant")
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_INACTIVE", f"policy.status={policy['status']}")

    # Priority 6: loss_date in [effective_from, effective_to)
    eff_from = parse_iso(policy["effective_from"])
    eff_to = parse_iso(policy["effective_to"])
    if loss_date < eff_from or loss_date >= eff_to:
        raise err("ERR_LOSS_OUTSIDE_POLICY_PERIOD")

    # Priority 7: reporting window
    reported_at = server_now()
    if (reported_at - loss_date).days > policy["reporting_window_days"]:
        raise err("ERR_REPORTING_WINDOW_EXCEEDED")

    # Priority 8: idempotency within last 24h
    horizon = reported_at - timedelta(hours=24)
    for c in db.claims.values():
        if c["claimant_id"] == user_id and c.get("idempotency_key") == idempotency_key:
            try:
                created = parse_iso(c["created_at"])
            except Exception:
                continue
            if created >= horizon:
                raise err(
                    "ERR_DUPLICATE_CLAIM_INTAKE",
                    f"duplicate intake; existing claim_id={c['id']}",
                )

    # Mint claim
    claim_number = mint_claim_number()
    rec = stamp_create()
    rec.update(
        {
            "claim_number": claim_number,
            "policy_id": policy_id,
            "claimant_id": user_id,
            "report_channel": report_channel,
            "idempotency_key": idempotency_key,
            "loss_date": iso_z(loss_date),
            "reported_at": iso_z(reported_at),
            "incident_description": incident_description,
            "claimed_amount_cents": claimed_amount_cents,
            "assessed_loss_cents": 0,
            "salvage_value_cents": salvage_value_cents,
            "subrogation_recovery_cents": 0,
            "status": "INTAKE",
            "review_path": None,
            "gross_payout_cents": None,
            "net_payout_cents": None,
            "denial_reason": None,
            "fraud_score": 0.00,
        }
    )
    db.claims[rec["id"]] = rec
    log_audit(
        rec["id"],
        actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=None, to_state="INTAKE",
        payload={"claim_number": claim_number, "report_channel": report_channel},
    )
    return ok(serialize(rec), http=201)


@app.get("/claims/<cid>")
def get_claim(cid):
    user_id, role = require_roles(
        ROLE_CUSTOMER, ROLE_ADJUSTER, ROLE_REVIEWER, ROLE_PAYOUT_OFFICER, ROLE_PLATFORM_ADMIN
    )
    rec = get_or_404(db.claims, cid, "Claim")
    if role == ROLE_CUSTOMER and not _customer_owns_claim(user_id, rec):
        raise err("ERR_FORBIDDEN", "not own claim")
    return ok(serialize(rec))


@app.get("/claims")
def list_claims():
    user_id, role = require_roles(
        ROLE_CUSTOMER, ROLE_ADJUSTER, ROLE_REVIEWER, ROLE_PAYOUT_OFFICER, ROLE_PLATFORM_ADMIN
    )
    limit, offset = parse_pagination()
    items = list(db.claims.values())
    status_f = request.args.get("status")
    claimant_f = request.args.get("claimant_id")
    policy_f = request.args.get("policy_id")
    if role == ROLE_CUSTOMER:
        items = [c for c in items if c["claimant_id"] == user_id]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    if claimant_f is not None:
        items = [c for c in items if c["claimant_id"] == claimant_f]
    if policy_f is not None:
        items = [c for c in items if c["policy_id"] == policy_f]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


@app.get("/claims/<cid>/estimate")
def get_estimate(cid):
    user_id, role = require_roles(
        ROLE_CUSTOMER, ROLE_ADJUSTER, ROLE_REVIEWER, ROLE_PLATFORM_ADMIN
    )
    claim = get_or_404(db.claims, cid, "Claim")
    if role == ROLE_CUSTOMER and not _customer_owns_claim(user_id, claim):
        raise err("ERR_FORBIDDEN", "not own claim")
    policy = db.policies.get(claim["policy_id"])
    if not policy:
        raise err("ERR_NOT_FOUND", "policy")
    gross = compute_gross_payout(claim["claimed_amount_cents"], policy)
    return ok(
        {
            "claim_id": claim["id"],
            "variant": "estimate_at_intake",
            "claimed_amount_cents": claim["claimed_amount_cents"],
            "deductible_cents": policy["deductible_cents"],
            "coinsurance_ratio": policy["coinsurance_ratio"],
            "coverage_limit_cents": policy["coverage_limit_cents"],
            "gross_payout_cents": gross,
        }
    )


# ===========================================================================
# Investigations
# ===========================================================================
@app.post("/claims/<cid>/investigations")
def open_investigation(cid):
    user_id, role = require_roles(ROLE_ADJUSTER)
    claim = get_or_404(db.claims, cid, "Claim")
    body = get_json_body()
    adjuster_id = require_str(body, "adjuster_id")

    # Concurrency guard: one Investigation in non-rejected state per claim.
    if get_active_investigation(cid):
        raise err("ERR_INVESTIGATION_ALREADY_OPEN")

    if claim["status"] != "INTAKE":
        # If an investigation already exists in a non-rejected state, surface the more
        # specific error code; otherwise fall back to invalid state.
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")

    # The acting adjuster must equal adjuster_id (role-identity check).
    if user_id != adjuster_id:
        raise err("ERR_FORBIDDEN", "adjuster identity mismatch")

    adjuster = db.adjusters.get(adjuster_id)
    if not adjuster:
        raise err("ERR_NOT_FOUND", "Adjuster")

    policy = db.policies.get(claim["policy_id"])
    if not policy:
        raise err("ERR_NOT_FOUND", "Policy")
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_INACTIVE", "policy not active")
    if adjuster["status"] != "ACTIVE":
        raise err("ERR_VALIDATION_FAILED", "adjuster not ACTIVE")
    if adjuster["specialty"] != policy["coverage_type"]:
        raise err("ERR_ADJUSTER_SPECIALTY_MISMATCH")

    # Time guards (defence-in-depth alongside intake checks).
    loss_date = parse_iso(claim["loss_date"])
    eff_from = parse_iso(policy["effective_from"])
    eff_to = parse_iso(policy["effective_to"])
    if loss_date < eff_from or loss_date >= eff_to:
        raise err("ERR_LOSS_OUTSIDE_POLICY_PERIOD")
    reported_at = parse_iso(claim["reported_at"])
    if (reported_at - loss_date).days > policy["reporting_window_days"]:
        raise err("ERR_REPORTING_WINDOW_EXCEEDED")

    inv = stamp_create()
    inv.update(
        {
            "claim_id": cid,
            "adjuster_id": adjuster_id,
            "photo_urls": [],
            "assessed_loss_cents": 0,
            "document_authenticity_passed": False,
            "status": "OPEN",
        }
    )
    db.investigations[inv["id"]] = inv

    prev = claim["status"]
    claim["status"] = "UNDER_INVESTIGATION"
    bump(claim)
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state="UNDER_INVESTIGATION",
        payload={"investigation_id": inv["id"], "adjuster_id": adjuster_id},
    )
    return ok(serialize(inv), http=201)


@app.patch("/claims/<cid>/investigations/<inv_id>")
def patch_investigation(cid, inv_id):
    user_id, role = require_roles(ROLE_ADJUSTER)
    claim = get_or_404(db.claims, cid, "Claim")
    inv = get_or_404(db.investigations, inv_id, "Investigation")
    if inv["claim_id"] != cid:
        raise err("ERR_NOT_FOUND", "Investigation")
    if user_id != inv["adjuster_id"]:
        raise err("ERR_FORBIDDEN", "not assigned adjuster")
    if inv["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", f"investigation.status={inv['status']}")

    body = get_json_body()
    changed = False
    if "photo_urls" in body and body["photo_urls"] is not None:
        urls = body["photo_urls"]
        if not isinstance(urls, list):
            raise err("ERR_VALIDATION_FAILED", "photo_urls must be array")
        for u in urls:
            if not isinstance(u, str) or not _URL_RE.match(u):
                raise err("ERR_VALIDATION_FAILED", "invalid photo url")
        inv["photo_urls"] = list(urls)
        changed = True
    if "document_authenticity_passed" in body and body["document_authenticity_passed"] is not None:
        v = body["document_authenticity_passed"]
        if not isinstance(v, bool):
            raise err("ERR_VALIDATION_FAILED", "document_authenticity_passed must be boolean")
        inv["document_authenticity_passed"] = v
        changed = True
    if "assessed_loss_cents" in body and body["assessed_loss_cents"] is not None:
        v = body["assessed_loss_cents"]
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_FAILED", "assessed_loss_cents must be integer")
        if iv < 0:
            raise err("ERR_VALIDATION_FAILED", "assessed_loss_cents must be >= 0")
        inv["assessed_loss_cents"] = iv
        changed = True
    if changed:
        bump(inv)
    return ok(serialize(inv))


@app.post("/claims/<cid>/investigations/<inv_id>/estimates")
def add_estimate(cid, inv_id):
    user_id, role = require_roles(ROLE_ADJUSTER)
    claim = get_or_404(db.claims, cid, "Claim")
    inv = get_or_404(db.investigations, inv_id, "Investigation")
    if inv["claim_id"] != cid:
        raise err("ERR_NOT_FOUND", "Investigation")
    if user_id != inv["adjuster_id"]:
        raise err("ERR_FORBIDDEN", "not assigned adjuster")
    if inv["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", f"investigation.status={inv['status']}")

    body = get_json_body()
    repair_shop_id = require_str(body, "repair_shop_id")
    description = require_str(body, "description")
    amount_cents = require_int(body, "amount_cents", gt=0)
    shop = db.repair_shops.get(repair_shop_id)
    if not shop:
        raise err("ERR_NOT_FOUND", "RepairShop")
    if shop["status"] == "BLACKLISTED":
        raise err("ERR_REPAIR_SHOP_BLACKLISTED")

    line = stamp_create_immutable()
    line.update(
        {
            "investigation_id": inv_id,
            "repair_shop_id": repair_shop_id,
            "description": description,
            "amount_cents": amount_cents,
        }
    )
    db.estimate_line_items[line["id"]] = line
    return ok(serialize(line), http=201)


@app.post("/claims/<cid>/investigations/<inv_id>/reject")
def reject_investigation(cid, inv_id):
    user_id, role = require_roles(ROLE_ADJUSTER)
    claim = get_or_404(db.claims, cid, "Claim")
    inv = get_or_404(db.investigations, inv_id, "Investigation")
    if inv["claim_id"] != cid:
        raise err("ERR_NOT_FOUND", "Investigation")
    if user_id != inv["adjuster_id"]:
        raise err("ERR_FORBIDDEN", "not assigned adjuster")
    if inv["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", f"investigation.status={inv['status']}")

    inv["status"] = "REJECTED"
    bump(inv)

    if claim["status"] == "UNDER_INVESTIGATION":
        prev = claim["status"]
        claim["status"] = "INTAKE"
        claim["review_path"] = None
        bump(claim)
        log_audit(
            cid, actor_id=user_id, actor_role=role,
            event_type="STATUS_CHANGE",
            from_state=prev, to_state="INTAKE",
            payload={"investigation_id": inv_id, "reason": "rejected"},
        )
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state="OPEN", to_state="REJECTED",
        payload={"resource": "Investigation", "investigation_id": inv_id},
    )
    return ok(serialize(inv))


# ===========================================================================
# Submit for review
# ===========================================================================
@app.post("/claims/<cid>/submit-for-review")
def submit_for_review(cid):
    user_id, role = require_roles(ROLE_ADJUSTER)
    claim = get_or_404(db.claims, cid, "Claim")
    if claim["status"] != "UNDER_INVESTIGATION":
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    inv = get_open_investigation(cid)
    if not inv:
        raise err("ERR_INVALID_STATE", "no OPEN investigation")
    if user_id != inv["adjuster_id"]:
        raise err("ERR_FORBIDDEN", "not assigned adjuster")

    # Priority-ordered preconditions per scaffold §1.4.
    # 9: anti-fraud is computed from existing flags; do that score first so it can fire.
    fraud_score = compute_fraud_score(cid)
    if fraud_score >= FRAUD_HOLD_GATE:
        # We must still write the score so callers can observe what's blocking;
        # but per PRD the transition itself is rejected before mutating state.
        raise err("ERR_FRAUD_HOLD", f"fraud_score={float(fraud_score)} >= 0.80")

    # 10: document authenticity
    if not inv.get("document_authenticity_passed"):
        raise err("ERR_DOCUMENT_AUTHENTICITY_FAILED")
    # 17: photos
    if not inv.get("photo_urls"):
        raise err("ERR_PHOTOS_REQUIRED")
    # 18: estimate
    if not estimate_lines_for_inv(inv["id"]):
        raise err("ERR_ESTIMATE_REQUIRED")

    policy = db.policies.get(claim["policy_id"])
    if not policy:
        raise err("ERR_NOT_FOUND", "Policy")

    # Compute gross_payout (15: must not exceed coverage_limit — calculation enforces; guard anyway).
    gross = compute_gross_payout(int(inv.get("assessed_loss_cents") or 0), policy)
    if gross > int(policy["coverage_limit_cents"]):
        raise err("ERR_COVERAGE_LIMIT_EXCEEDED")

    # All preconditions hold; commit side effects.
    inv["status"] = "COMPLETED"
    bump(inv)
    claim["assessed_loss_cents"] = int(inv.get("assessed_loss_cents") or 0)
    claim["gross_payout_cents"] = gross
    # net at_approval (subrogation = 0)
    claim["subrogation_recovery_cents"] = 0
    claim["net_payout_cents"] = compute_net_payout(claim)
    claim["fraud_score"] = float(fraud_score)

    # Repair-shop trust decay cascade
    apply_repair_shop_decay_for_claim(cid, actor_id=user_id, actor_role=role)

    # Review-path assignment
    if (
        int(claim["claimed_amount_cents"]) <= AUTO_APPROVAL_THRESHOLD_CENTS
        and Decimal(str(claim["fraud_score"])) < AUTO_FRAUD_GATE
    ):
        claim["review_path"] = "AUTO"
    else:
        claim["review_path"] = "MANUAL"

    prev = claim["status"]
    claim["status"] = "UNDER_REVIEW"
    bump(claim)

    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state="UNDER_REVIEW",
        payload={
            "review_path": claim["review_path"],
            "gross_payout_cents": gross,
            "net_payout_cents": claim["net_payout_cents"],
            "fraud_score": claim["fraud_score"],
        },
    )

    # AUTO path — record system primary review decision and approve.
    if claim["review_path"] == "AUTO":
        decision = stamp_create_immutable()
        decision.update(
            {
                "claim_id": cid,
                "reviewer_id": "system",
                "review_level": "PRIMARY",
                "outcome": "APPROVE",
                "rationale": "auto-approved by review-path rule",
                "decided_at": now_iso(),
            }
        )
        db.review_decisions[decision["id"]] = decision
        log_audit(
            cid, actor_id="system", actor_role=ROLE_REVIEWER,
            event_type="REVIEW_DECISION",
            payload={"outcome": "APPROVE", "review_level": "PRIMARY", "auto": True},
        )
        from_state = claim["status"]
        claim["status"] = "APPROVED"
        bump(claim)
        log_audit(
            cid, actor_id="system", actor_role=ROLE_REVIEWER,
            event_type="STATUS_CHANGE",
            from_state=from_state, to_state="APPROVED",
            payload={"auto": True},
        )

    return ok(serialize(claim))


# ===========================================================================
# Primary review decisions
# ===========================================================================
@app.post("/claims/<cid>/decisions")
def post_decision(cid):
    user_id, role = require_roles(ROLE_REVIEWER)
    claim = get_or_404(db.claims, cid, "Claim")
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"APPROVE", "DENY"})
    rationale = require_str(body, "rationale")

    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    if claim.get("review_path") != "MANUAL":
        # AUTO-path claims auto-approve at submit-for-review time; manual decisions
        # against them are nonsensical state-wise.
        raise err("ERR_INVALID_STATE", "manual decision not allowed on AUTO path")

    inv = get_active_investigation(cid)
    if inv and user_id == inv["adjuster_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "reviewer == adjuster")

    rec = stamp_create_immutable()
    rec.update(
        {
            "claim_id": cid,
            "reviewer_id": user_id,
            "review_level": "PRIMARY",
            "outcome": outcome,
            "rationale": rationale,
            "decided_at": now_iso(),
        }
    )
    db.review_decisions[rec["id"]] = rec
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="REVIEW_DECISION",
        payload={"outcome": outcome, "review_level": "PRIMARY"},
    )
    prev = claim["status"]
    if outcome == "APPROVE":
        claim["status"] = "APPROVED"
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = rationale
    bump(claim)
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state=claim["status"],
        payload={"outcome": outcome},
    )
    return ok(serialize(rec), http=201)


# ===========================================================================
# Payouts
# ===========================================================================
@app.post("/claims/<cid>/payouts")
def create_payout(cid):
    user_id, role = require_roles(ROLE_PAYOUT_OFFICER)
    claim = get_or_404(db.claims, cid, "Claim")
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    # Per PRD only PENDING/SETTLED payouts count toward uniqueness; a REVERSED
    # payout no longer blocks a new payout.
    existing = get_payout_for_claim(cid)
    if existing and existing["status"] != "REVERSED":
        raise err("ERR_PAYOUT_ALREADY_EXISTS")
    if int(claim.get("net_payout_cents") or 0) <= 0:
        raise err("ERR_INVALID_STATE", "net_payout_cents must be > 0")

    pay = stamp_create()
    pay.update(
        {
            "claim_id": cid,
            "amount_cents": int(claim["net_payout_cents"]),
            "bank_reference": None,
            "status": "PENDING",
            "settled_at": None,
        }
    )
    db.payouts[pay["id"]] = pay

    prev = claim["status"]
    claim["status"] = "PAID"
    bump(claim)
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="PAYOUT_EVENT",
        payload={"event": "payout_created", "payout_id": pay["id"], "amount_cents": pay["amount_cents"]},
    )
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state="PAID",
        payload={"payout_id": pay["id"]},
    )
    return ok(serialize(pay), http=201)


@app.get("/claims/<cid>/payouts")
def get_payout(cid):
    user_id, role = require_roles(
        ROLE_CUSTOMER, ROLE_PAYOUT_OFFICER, ROLE_REVIEWER, ROLE_PLATFORM_ADMIN
    )
    claim = get_or_404(db.claims, cid, "Claim")
    if role == ROLE_CUSTOMER and not _customer_owns_claim(user_id, claim):
        raise err("ERR_FORBIDDEN", "not own claim")
    pay = get_payout_for_claim(cid)
    if not pay:
        raise err("ERR_NOT_FOUND", "Payout")
    return ok(serialize(pay))


# ===========================================================================
# Subrogations
# ===========================================================================
@app.post("/claims/<cid>/subrogations")
def post_subrogation(cid):
    user_id, role = require_roles(ROLE_PAYOUT_OFFICER)
    claim = get_or_404(db.claims, cid, "Claim")
    # PRD §3.6: subrogation requires the underlying payout in SETTLED;
    # bank-settle cascades the claim PAID->CLOSED, so accept both PAID and
    # CLOSED here. APPROVED (after bank-fail) is rejected with ERR_INVALID_STATE.
    if claim["status"] not in ("PAID", "CLOSED"):
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    pay = get_payout_for_claim(cid)
    if not pay or pay["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "payout not SETTLED")
    body = get_json_body()
    amount = require_int(body, "amount_cents", gt=0)

    new_sub = int(claim.get("subrogation_recovery_cents") or 0) + amount
    salvage = int(claim.get("salvage_value_cents") or 0)
    gross = int(claim.get("gross_payout_cents") or 0)
    if salvage + new_sub > gross:
        raise err("ERR_NEGATIVE_NET_PAYOUT")

    claim["subrogation_recovery_cents"] = new_sub
    claim["net_payout_cents"] = compute_net_payout(claim)
    bump(claim)
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="PAYOUT_EVENT",
        payload={
            "event": "subrogation",
            "amount_cents": amount,
            "subrogation_recovery_cents": new_sub,
            "net_payout_cents": claim["net_payout_cents"],
        },
    )
    return ok(serialize(claim))


# ===========================================================================
# Appeals
# ===========================================================================
@app.post("/claims/<cid>/appeals")
def post_appeal(cid):
    user_id, role = require_roles(ROLE_CUSTOMER)
    claim = get_or_404(db.claims, cid, "Claim")
    if claim["status"] != "DENIED":
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    if not _customer_owns_claim(user_id, claim):
        raise err("ERR_FORBIDDEN", "not own claim")
    if get_appeal_for_claim(cid):
        raise err("ERR_APPEAL_ALREADY_EXISTS")

    body = get_json_body()
    grounds = require_str(body, "grounds")

    rec = stamp_create()
    rec.update(
        {
            "claim_id": cid,
            "requestor_id": user_id,
            "grounds": grounds,
            "secondary_reviewer_id": None,
            "status": "UNDER_RECONSIDERATION",  # auto-advance from SUBMITTED
            "final_decision_recorded_at": None,
        }
    )
    db.appeals[rec["id"]] = rec

    prev = claim["status"]
    claim["status"] = "APPEALED"
    bump(claim)
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="APPEAL_DECISION",
        payload={"event": "appeal_filed", "appeal_id": rec["id"]},
    )
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state="APPEALED",
        payload={"appeal_id": rec["id"]},
    )
    return ok(serialize(rec), http=201)


@app.delete("/claims/<cid>/appeals/<appeal_id>")
def delete_appeal(cid, appeal_id):
    user_id, role = require_roles(ROLE_CUSTOMER)
    claim = get_or_404(db.claims, cid, "Claim")
    appeal = get_or_404(db.appeals, appeal_id, "Appeal")
    if appeal["claim_id"] != cid:
        raise err("ERR_NOT_FOUND", "Appeal")
    if appeal["requestor_id"] != user_id:
        raise err("ERR_FORBIDDEN", "not appeal requestor")
    # Withdrawal allowed only while still in SUBMITTED. The system auto-advances on
    # creation, so per spec only the brief-window-pre-advance can be withdrawn.
    if appeal["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", f"appeal.status={appeal['status']}")
    appeal["status"] = "WITHDRAWN"
    bump(appeal)
    if claim["status"] == "APPEALED":
        prev = claim["status"]
        claim["status"] = "DENIED"
        bump(claim)
        log_audit(
            cid, actor_id=user_id, actor_role=role,
            event_type="STATUS_CHANGE",
            from_state=prev, to_state="DENIED",
            payload={"appeal_id": appeal_id, "reason": "withdrawn"},
        )
    return ok(serialize(appeal))


@app.post("/claims/<cid>/appeals/<appeal_id>/decisions")
def post_appeal_decision(cid, appeal_id):
    user_id, role = require_roles(ROLE_REVIEWER)
    claim = get_or_404(db.claims, cid, "Claim")
    appeal = get_or_404(db.appeals, appeal_id, "Appeal")
    if appeal["claim_id"] != cid:
        raise err("ERR_NOT_FOUND", "Appeal")
    if claim["status"] != "APPEALED":
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    if appeal["status"] != "UNDER_RECONSIDERATION":
        raise err("ERR_INVALID_STATE", f"appeal.status={appeal['status']}")

    body = get_json_body()
    outcome = require_enum(body, "outcome", {"OVERTURN", "UPHOLD"})
    rationale = require_str(body, "rationale")

    inv = get_active_investigation(cid)
    if inv and user_id == inv["adjuster_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "secondary reviewer == adjuster")
    primary = primary_review_decision(cid)
    if primary and user_id == primary["reviewer_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "secondary reviewer == primary reviewer")

    decision = stamp_create_immutable()
    decision.update(
        {
            "claim_id": cid,
            "reviewer_id": user_id,
            "review_level": "SECONDARY",
            "outcome": "APPROVE" if outcome == "OVERTURN" else "DENY",
            "rationale": rationale,
            "decided_at": now_iso(),
        }
    )
    db.review_decisions[decision["id"]] = decision

    appeal["secondary_reviewer_id"] = user_id
    appeal["final_decision_recorded_at"] = now_iso()
    if outcome == "OVERTURN":
        appeal["status"] = "OVERTURNED"
    else:
        appeal["status"] = "UPHELD_DENIAL"
    bump(appeal)

    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="APPEAL_DECISION",
        payload={"outcome": outcome, "appeal_id": appeal_id},
    )

    prev = claim["status"]
    if outcome == "OVERTURN":
        # Recompute payout figures on the latest data
        policy = db.policies.get(claim["policy_id"])
        if policy:
            claim["gross_payout_cents"] = compute_gross_payout(
                int(claim.get("assessed_loss_cents") or 0), policy
            )
            claim["net_payout_cents"] = compute_net_payout(claim)
        claim["status"] = "APPROVED"
        claim["denial_reason"] = None
    else:
        claim["status"] = "CLOSED"
    bump(claim)
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state=claim["status"],
        payload={"appeal_id": appeal_id, "outcome": outcome},
    )
    return ok(serialize(decision), http=201)


# ===========================================================================
# Fraud flags
# ===========================================================================
@app.post("/claims/<cid>/fraud-flags")
def post_fraud_flag(cid):
    user_id, role = require_roles(ROLE_PLATFORM_ADMIN)
    claim = get_or_404(db.claims, cid, "Claim")
    body = get_json_body()
    signal = require_enum(
        body, "signal",
        {"DUPLICATE_PATTERN", "REPAIR_SHOP_COLLUSION", "DOCUMENT_FORGERY", "RAPID_RESUBMISSION"},
    )
    severity_raw = require_field(body, "severity")
    try:
        sev = Decimal(str(severity_raw))
    except Exception:
        raise err("ERR_VALIDATION_FAILED", "severity must be numeric")
    if sev < Decimal(0) or sev > Decimal(1):
        raise err("ERR_VALIDATION_FAILED", "severity out of [0,1]")
    repair_shop_id = body.get("repair_shop_id")
    if signal == "REPAIR_SHOP_COLLUSION":
        if not repair_shop_id:
            raise err("ERR_VALIDATION_FAILED", "repair_shop_id required for collusion")
        if repair_shop_id not in db.repair_shops:
            raise err("ERR_NOT_FOUND", "RepairShop")
    rec = stamp_create_immutable()
    rec.update(
        {
            "claim_id": cid,
            "signal": signal,
            "severity": float(sev),
            "repair_shop_id": repair_shop_id if signal == "REPAIR_SHOP_COLLUSION" else None,
        }
    )
    db.fraud_flags[rec["id"]] = rec
    log_audit(
        cid, actor_id=user_id, actor_role=role,
        event_type="FRAUD_FLAG_ADDED",
        payload={
            "signal": signal,
            "severity": float(sev),
            "repair_shop_id": rec["repair_shop_id"],
        },
    )
    return ok(serialize(rec), http=201)


# ===========================================================================
# Audit log
# ===========================================================================
@app.get("/claims/<cid>/audit-log")
def get_audit_log(cid):
    require_roles(ROLE_REVIEWER, ROLE_PLATFORM_ADMIN)
    if cid not in db.claims:
        raise err("ERR_NOT_FOUND", "Claim")
    limit, offset = parse_pagination()
    items = [a for a in db.audit_log.values() if a["claim_id"] == cid]
    et = request.args.get("event_type")
    if et is not None:
        items = [a for a in items if a["event_type"] == et]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


# ===========================================================================
# Test-driving control endpoints
# ===========================================================================
@app.post("/_clock/advance")
def clock_advance():
    require_admin_token()
    body = get_json_body()
    target_s = require_str(body, "to_iso8601")
    target = parse_iso(target_s)
    cur = server_now()
    if target < cur:
        raise err("ERR_VALIDATION_FAILED", "clock cannot move backward")
    db.simulated_clock = target
    return ok({"clock": iso_z(target)})


@app.post("/_events/bank-settle")
def event_bank_settle():
    require_admin_token()
    body = get_json_body()
    payout_id = require_str(body, "payout_id")
    pay = db.payouts.get(payout_id)
    if not pay:
        raise err("ERR_NOT_FOUND", "Payout")
    if pay["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", f"payout.status={pay['status']}")
    claim = db.claims.get(pay["claim_id"])
    if not claim:
        raise err("ERR_NOT_FOUND", "Claim")
    if claim["status"] != "PAID":
        raise err("ERR_INVALID_STATE", f"claim.status={claim['status']}")
    pay["status"] = "SETTLED"
    pay["bank_reference"] = "BANKREF-" + new_id().split("-")[0].upper()
    pay["settled_at"] = now_iso()
    bump(pay)
    log_audit(
        claim["id"], actor_id="system", actor_role=ROLE_PLATFORM_ADMIN,
        event_type="PAYOUT_EVENT",
        payload={"event": "bank_settled", "payout_id": pay["id"], "bank_reference": pay["bank_reference"]},
    )
    prev = claim["status"]
    claim["status"] = "CLOSED"
    bump(claim)
    db.event_log.append({"type": "POLICY_CLAIM_CLOSED", "claim_id": claim["id"], "at": now_iso()})
    log_audit(
        claim["id"], actor_id="system", actor_role=ROLE_PLATFORM_ADMIN,
        event_type="STATUS_CHANGE",
        from_state=prev, to_state="CLOSED",
        payload={"reason": "bank_settled"},
    )
    return ok(serialize(pay))


@app.post("/_events/bank-fail")
def event_bank_fail():
    require_admin_token()
    body = get_json_body()
    payout_id = require_str(body, "payout_id")
    pay = db.payouts.get(payout_id)
    if not pay:
        raise err("ERR_NOT_FOUND", "Payout")
    if pay["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", f"payout.status={pay['status']}")
    claim = db.claims.get(pay["claim_id"])
    if not claim:
        raise err("ERR_NOT_FOUND", "Claim")
    pay["status"] = "REVERSED"
    bump(pay)
    log_audit(
        claim["id"], actor_id="system", actor_role=ROLE_PLATFORM_ADMIN,
        event_type="PAYOUT_EVENT",
        payload={"event": "bank_failed", "payout_id": pay["id"]},
    )
    if claim["status"] == "PAID":
        prev = claim["status"]
        # Compensating: gross/net unchanged; only the payout reverses.
        claim["status"] = "APPROVED"
        bump(claim)
        log_audit(
            claim["id"], actor_id="system", actor_role=ROLE_PLATFORM_ADMIN,
            event_type="STATUS_CHANGE",
            from_state=prev, to_state="APPROVED",
            payload={"reason": "bank_failed"},
        )
    return ok(serialize(pay))


# ===========================================================================
# Entrypoint
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
