"""All API routes for the Public Adjuster & Claim Advocacy API (prefix /v1).

Every endpoint, field, error and side effect traces to PRD.md / SCAFFOLD.yaml.
Validation order within each handler follows PRD 2.10 with the claim-file
precondition order taken from the operation-specific narrative in PRD 3.3
(contract -> policy -> license -> loss-period).
"""

from datetime import timedelta

from flask import Blueprint, request, g

from store import db, new_id
from common import (
    ApiError, ok, authenticate, require_role, touch, stamp_new, public,
    get_body, require_fields, as_int, as_number, as_enum, as_str,
    parse_iso, fmt_ts, paginate,
)
import domain

bp = Blueprint("api", __name__)

POLICY_TYPES = {"HO3", "HO5", "COMMERCIAL", "FLOOD"}
PERIL_TYPES = {"WIND", "WATER", "FIRE", "HAIL", "THEFT"}
PAYMENT_TYPES = {"INITIAL", "SUPPLEMENT", "APPRAISAL_AWARD"}
DISPUTE_TYPES = {"FEE", "SERVICE", "LICENSING"}
RAISED_BY = {"CLIENT", "CARRIER"}
DECISIONS = {"APPROVE", "DENY"}

READ_ROLES = ("FirmPrincipal", "PublicAdjuster", "Client", "Carrier")

RESCISSION_WINDOW_DAYS = 3
SUPPLEMENT_WINDOW_DAYS = 365
TRAVEL_BUFFER_MINUTES = 60


def fetch(collection, ident):
    ent = collection.get(ident)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return ent


def filtered_list(collection, filters):
    """Apply exact-match query filters (only when the arg is present)."""
    items = list(collection.values())
    for arg, field in filters.items():
        if arg in request.args:
            val = request.args[arg]
            items = [e for e in items if str(e.get(field)) == val]
    return items


# =========================================================================
# Logical clock
# =========================================================================

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_role("FirmPrincipal", "System", "PublicAdjuster", "Carrier")
    body = get_body()
    require_fields(body, "to_iso8601")
    try:
        dt = parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant")
    db.set_clock(dt)
    return ok({}, 200)


# =========================================================================
# Adjuster
# =========================================================================

@bp.route("/adjusters", methods=["POST"])
def create_adjuster():
    authenticate()
    require_role("FirmPrincipal")
    body = get_body()
    require_fields(body, "full_name", "firm_name", "email")
    ent = {
        "id": new_id(),
        "full_name": as_str(body, "full_name"),
        "firm_name": as_str(body, "firm_name"),
        "email": as_str(body, "email"),
        "status": "ACTIVE",
    }
    stamp_new(ent)
    db.adjusters[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/adjusters/<ident>", methods=["GET"])
def get_adjuster(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.adjusters, ident)), 200)


# =========================================================================
# License
# =========================================================================

@bp.route("/licenses", methods=["POST"])
def create_license():
    authenticate()
    require_role("FirmPrincipal")
    body = get_body()
    # existence (priority 3)
    if body.get("adjuster_id") is not None:
        fetch(db.adjusters, body["adjuster_id"])
    # field validation
    require_fields(body, "adjuster_id", "state_code", "license_number",
                   "effective_date", "expiry_date")
    adjuster_id = as_str(body, "adjuster_id")
    state_code = as_str(body, "state_code")
    license_number = as_str(body, "license_number")
    try:
        eff = parse_iso(body["effective_date"])
        exp = parse_iso(body["expiry_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "effective_date/expiry_date must be ISO 8601")
    # period-overlap constraint (priority 8)
    for lic in db.licenses.values():
        if lic["adjuster_id"] != adjuster_id or lic["state_code"] != state_code:
            continue
        if lic["status"] == "REVOKED":
            continue
        o_eff = parse_iso(lic["effective_date"])
        o_exp = parse_iso(lic["expiry_date"])
        if eff <= o_exp and o_eff <= exp:
            raise ApiError("ERR_LICENSE_PERIOD_OVERLAP",
                           "License interval overlaps an existing credential")
    ent = {
        "id": new_id(),
        "adjuster_id": adjuster_id,
        "state_code": state_code,
        "license_number": license_number,
        "effective_date": body["effective_date"],
        "expiry_date": body["expiry_date"],
        "status": "ACTIVE",
    }
    stamp_new(ent)
    db.licenses[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/licenses/<ident>", methods=["GET"])
def get_license(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.licenses, ident)), 200)


@bp.route("/licenses", methods=["GET"])
def list_licenses():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.licenses, {
        "adjuster_id": "adjuster_id", "state_code": "state_code", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


def _license_transition(ident, allowed_from, to):
    authenticate()
    require_role("FirmPrincipal")
    lic = fetch(db.licenses, ident)
    if lic["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", "License not in a valid state for this action")
    lic["status"] = to
    touch(lic)
    return ok(public(lic), 200)


@bp.route("/licenses/<ident>/suspend", methods=["POST"])
def suspend_license(ident):
    return _license_transition(ident, {"ACTIVE"}, "SUSPENDED")


@bp.route("/licenses/<ident>/reinstate", methods=["POST"])
def reinstate_license(ident):
    return _license_transition(ident, {"SUSPENDED"}, "ACTIVE")


@bp.route("/licenses/<ident>/revoke", methods=["POST"])
def revoke_license(ident):
    return _license_transition(ident, {"ACTIVE", "SUSPENDED"}, "REVOKED")


# =========================================================================
# Client
# =========================================================================

@bp.route("/clients", methods=["POST"])
def create_client():
    authenticate()
    require_role("FirmPrincipal", "PublicAdjuster")
    body = get_body()
    require_fields(body, "full_name", "email", "mailing_state")
    ent = {
        "id": new_id(),
        "full_name": as_str(body, "full_name"),
        "email": as_str(body, "email"),
        "mailing_state": as_str(body, "mailing_state"),
        "status": "ACTIVE",
    }
    stamp_new(ent)
    db.clients[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/clients/<ident>", methods=["GET"])
def get_client(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.clients, ident)), 200)


# =========================================================================
# Policy
# =========================================================================

@bp.route("/policies", methods=["POST"])
def create_policy():
    authenticate()
    require_role("FirmPrincipal", "PublicAdjuster")
    body = get_body()
    if body.get("client_id") is not None:
        fetch(db.clients, body["client_id"])
    require_fields(body, "client_id", "carrier_name", "policy_number", "policy_type",
                   "coverage_limit_cents", "deductible_cents", "effective_date", "expiry_date")
    client_id = as_str(body, "client_id")
    carrier_name = as_str(body, "carrier_name")
    policy_number = as_str(body, "policy_number")
    policy_type = as_enum(body, "policy_type", POLICY_TYPES)
    coverage = as_int(body, "coverage_limit_cents", positive=True)
    deductible = as_int(body, "deductible_cents", non_negative=True)
    try:
        parse_iso(body["effective_date"])
        parse_iso(body["expiry_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "effective_date/expiry_date must be ISO 8601")
    ent = {
        "id": new_id(),
        "client_id": client_id,
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "policy_type": policy_type,
        "coverage_limit_cents": coverage,
        "deductible_cents": deductible,
        "effective_date": body["effective_date"],
        "expiry_date": body["expiry_date"],
        "status": "ACTIVE",
        "committed_cents": 0,
        "remaining_limit_cents": coverage,
        "forward_exposure_cents": 0,
    }
    stamp_new(ent)
    db.policies[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/policies/<ident>", methods=["GET"])
def get_policy(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.policies, ident)), 200)


@bp.route("/policies", methods=["GET"])
def list_policies():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.policies, {"client_id": "client_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


def _policy_transition(ident, to):
    authenticate()
    require_role("FirmPrincipal", "Carrier")
    pol = fetch(db.policies, ident)
    if pol["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Policy not ACTIVE")
    pol["status"] = to
    touch(pol)
    return ok(public(pol), 200)


@bp.route("/policies/<ident>/lapse", methods=["POST"])
def lapse_policy(ident):
    return _policy_transition(ident, "LAPSED")


@bp.route("/policies/<ident>/cancel", methods=["POST"])
def cancel_policy(ident):
    return _policy_transition(ident, "CANCELLED")


# =========================================================================
# Contract
# =========================================================================

@bp.route("/contracts", methods=["POST"])
def create_contract():
    authenticate()
    require_role("FirmPrincipal")
    body = get_body()
    if body.get("client_id") is not None:
        fetch(db.clients, body["client_id"])
    if body.get("adjuster_id") is not None:
        fetch(db.adjusters, body["adjuster_id"])
    require_fields(body, "client_id", "adjuster_id", "loss_state_code",
                   "fee_pct", "statutory_cap_pct")
    client_id = as_str(body, "client_id")
    adjuster_id = as_str(body, "adjuster_id")
    loss_state_code = as_str(body, "loss_state_code")
    fee_pct = as_number(body, "fee_pct", non_negative=True)
    cap_pct = as_number(body, "statutory_cap_pct", non_negative=True)
    prior_advance = 0
    if body.get("prior_advance_cents") is not None:
        prior_advance = as_int(body, "prior_advance_cents", non_negative=True)
    # statutory fee cap (priority 8): equality accepted
    if fee_pct > cap_pct:
        raise ApiError("ERR_FEE_EXCEEDS_STATUTORY_CAP",
                       "fee_pct exceeds statutory_cap_pct")
    ent = {
        "id": new_id(),
        "client_id": client_id,
        "adjuster_id": adjuster_id,
        "loss_state_code": loss_state_code,
        "fee_pct": fee_pct,
        "statutory_cap_pct": cap_pct,
        "prior_advance_cents": prior_advance,
        "advance_recouped_cents": 0,
        "signed_at": None,
        "rescission_deadline_at": None,
        "status": "DRAFT",
    }
    stamp_new(ent)
    db.contracts[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/contracts/<ident>", methods=["GET"])
def get_contract(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.contracts, ident)), 200)


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.contracts, {
        "client_id": "client_id", "adjuster_id": "adjuster_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/contracts/<ident>/sign", methods=["POST"])
def sign_contract(ident):
    authenticate()
    require_role("Client")
    contract = fetch(db.contracts, ident)
    # ownership (priority 2): only the named client may sign
    if g.user_id != contract["client_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the named client may sign this contract")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Contract not in DRAFT")
    contract["status"] = "SIGNED"
    contract["signed_at"] = fmt_ts(db.now())
    deadline = db.now() + timedelta(days=RESCISSION_WINDOW_DAYS)
    contract["rescission_deadline_at"] = fmt_ts(deadline)
    touch(contract)
    return ok(public(contract), 200)


@bp.route("/contracts/<ident>/activate", methods=["POST"])
def activate_contract(ident):
    authenticate()
    require_role("FirmPrincipal")
    contract = fetch(db.contracts, ident)
    if contract["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE", "Contract not in SIGNED")
    if not domain.license_currently_valid(contract["adjuster_id"], contract["loss_state_code"]):
        raise ApiError("ERR_LICENSE_NOT_VALID",
                       "Adjuster lacks a valid license in the loss state")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(public(contract), 200)


@bp.route("/contracts/<ident>/rescind", methods=["POST"])
def rescind_contract(ident):
    authenticate()
    require_role("Client", "FirmPrincipal")
    contract = fetch(db.contracts, ident)
    # Client may only rescind their own contract (entity-backed ownership).
    if g.role == "Client" and g.user_id != contract["client_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the named client may rescind this contract")
    if contract["status"] not in ("SIGNED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", "Contract not in SIGNED or ACTIVE")
    deadline = parse_iso(contract["rescission_deadline_at"])
    if db.now() > deadline:
        raise ApiError("ERR_RESCISSION_WINDOW_CLOSED", "Rescission window has closed")
    contract["status"] = "RESCINDED"
    touch(contract)
    domain.rescind_cascade(contract)
    return ok(public(contract), 200)


@bp.route("/contracts/<ident>/cancel", methods=["POST"])
def cancel_contract(ident):
    authenticate()
    require_role("FirmPrincipal")
    contract = fetch(db.contracts, ident)
    if contract["status"] == "DRAFT":
        contract["status"] = "CANCELLED"
        touch(contract)
        return ok(public(contract), 200)
    if contract["status"] == "SIGNED":
        for claim in db.claims.values():
            if claim["contract_id"] == contract["id"] and claim["status"] not in ("PAID", "WITHDRAWN"):
                raise ApiError("ERR_INVALID_STATE",
                               "A non-terminal claim exists on this contract")
        contract["status"] = "CANCELLED"
        touch(contract)
        return ok(public(contract), 200)
    raise ApiError("ERR_INVALID_STATE", "Contract cannot be cancelled from its current state")


# =========================================================================
# Claim
# =========================================================================

@bp.route("/claims", methods=["POST"])
def create_claim():
    authenticate()
    require_role("PublicAdjuster")
    body = get_body()
    if body.get("policy_id") is not None:
        fetch(db.policies, body["policy_id"])
    if body.get("contract_id") is not None:
        fetch(db.contracts, body["contract_id"])
    require_fields(body, "policy_id", "contract_id", "date_of_loss", "loss_state_code",
                   "peril_type", "pa_rcv_estimate_cents", "depreciation_pct")
    policy_id = as_str(body, "policy_id")
    contract_id = as_str(body, "contract_id")
    loss_state_code = as_str(body, "loss_state_code")
    peril_type = as_enum(body, "peril_type", PERIL_TYPES)
    rcv = as_int(body, "pa_rcv_estimate_cents", positive=True)
    dep = as_number(body, "depreciation_pct", non_negative=True)
    try:
        parse_iso(body["date_of_loss"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "date_of_loss must be ISO 8601")
    ent = {
        "id": new_id(),
        "policy_id": policy_id,
        "contract_id": contract_id,
        "date_of_loss": body["date_of_loss"],
        "loss_state_code": loss_state_code,
        "peril_type": peril_type,
        "pa_rcv_estimate_cents": rcv,
        "depreciation_pct": dep,
        "pa_acv_estimate_cents": None,
        "carrier_offer_cents": 0,
        "pa_counter_cents": 0,
        "negotiation_round": 0,
        "inspection_start": None,
        "inspection_end": None,
        "settlement_amount_cents": 0,
        "settled_at": None,
        "amount_recovered_cents": 0,
        "provisional_fee_cents": 0,
        "final_fee_cents": 0,
        "accepted_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(ent)
    db.claims[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/claims/<ident>", methods=["GET"])
def get_claim(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.claims, ident)), 200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.claims, {
        "policy_id": "policy_id", "contract_id": "contract_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/claims/<ident>/file", methods=["POST"])
def file_claim(ident):
    authenticate()
    require_role("PublicAdjuster")
    claim = fetch(db.claims, ident)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Claim not in DRAFT")
    contract = db.contracts.get(claim["contract_id"])
    policy = db.policies.get(claim["policy_id"])
    # PRD 3.3 precondition order: contract -> policy -> license -> loss-period
    if not contract or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "Referenced contract is not ACTIVE")
    if not policy or policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "Referenced policy is not ACTIVE")
    if not domain.license_currently_valid(contract["adjuster_id"], claim["loss_state_code"]):
        raise ApiError("ERR_LICENSE_NOT_VALID",
                       "Adjuster lacks a valid license in the loss state")
    dol = parse_iso(claim["date_of_loss"])
    if not (parse_iso(policy["effective_date"]) <= dol <= parse_iso(policy["expiry_date"])):
        raise ApiError("ERR_LOSS_OUTSIDE_POLICY_PERIOD",
                       "date_of_loss falls outside the policy period")
    from decimal import Decimal
    from common import round_half_up
    multiplier = Decimal("1") - Decimal(str(claim["depreciation_pct"]))
    claim["pa_acv_estimate_cents"] = round_half_up(
        claim["pa_rcv_estimate_cents"], multiplier)
    claim["status"] = "FILED"
    touch(claim)
    domain.recompute_policy_exposure(policy)
    return ok(public(claim), 200)


@bp.route("/claims/<ident>/schedule-inspection", methods=["POST"])
def schedule_inspection(ident):
    authenticate()
    require_role("PublicAdjuster")
    claim = fetch(db.claims, ident)
    body = get_body()
    require_fields(body, "inspection_start", "inspection_end")
    try:
        new_start = parse_iso(body["inspection_start"])
        new_end = parse_iso(body["inspection_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "inspection_start/end must be ISO 8601")
    contract = db.contracts.get(claim["contract_id"])
    adjuster_id = contract["adjuster_id"] if contract else None
    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for other in db.claims.values():
        if other["id"] == claim["id"]:
            continue
        if other.get("inspection_start") is None or other.get("inspection_end") is None:
            continue
        o_contract = db.contracts.get(other["contract_id"])
        o_adjuster = o_contract["adjuster_id"] if o_contract else None
        if o_adjuster != adjuster_id:
            continue
        o_start = parse_iso(other["inspection_start"])
        o_end = parse_iso(other["inspection_end"])
        # Non-conflict when the windows are at least the buffer apart (inclusive).
        separated = (o_end + buffer <= new_start) or (new_end + buffer <= o_start)
        if not separated:
            raise ApiError("ERR_INSPECTION_OVERLAP",
                           "Inspection window is too close to another for this adjuster")
    claim["inspection_start"] = body["inspection_start"]
    claim["inspection_end"] = body["inspection_end"]
    touch(claim)
    return ok(public(claim), 200)


@bp.route("/claims/<ident>/record-offer", methods=["POST"])
def record_offer(ident):
    authenticate()
    require_role("Carrier")
    claim = fetch(db.claims, ident)
    if claim["status"] not in ("FILED", "NEGOTIATING"):
        raise ApiError("ERR_INVALID_STATE", "Claim not open to a carrier offer")
    body = get_body()
    require_fields(body, "offer_cents")
    offer = as_int(body, "offer_cents", positive=True)
    claim["carrier_offer_cents"] = offer
    claim["negotiation_round"] += 1
    claim["status"] = "OFFER_RECEIVED"
    touch(claim)
    return ok(public(claim), 200)


@bp.route("/claims/<ident>/counter", methods=["POST"])
def counter_offer(ident):
    authenticate()
    require_role("PublicAdjuster")
    claim = fetch(db.claims, ident)
    if claim["status"] != "OFFER_RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Claim not in OFFER_RECEIVED")
    body = get_body()
    require_fields(body, "counter_cents")
    counter = as_int(body, "counter_cents", positive=True)
    claim["pa_counter_cents"] = counter
    claim["negotiation_round"] += 1
    claim["status"] = "NEGOTIATING"
    touch(claim)
    return ok(public(claim), 200)


@bp.route("/claims/<ident>/accept-settlement", methods=["POST"])
def accept_settlement(ident):
    authenticate()
    require_role("PublicAdjuster")
    claim = fetch(db.claims, ident)
    if claim["status"] != "OFFER_RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Claim not in OFFER_RECEIVED")
    contract = db.contracts.get(claim["contract_id"])
    policy = db.policies.get(claim["policy_id"])
    domain.apply_settlement(claim, contract, policy, claim["carrier_offer_cents"], g.user_id)
    return ok(public(claim), 200)


@bp.route("/claims/<ident>/withdraw", methods=["POST"])
def withdraw_claim(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    claim = fetch(db.claims, ident)
    if claim["status"] not in ("FILED", "NEGOTIATING", "OFFER_RECEIVED"):
        raise ApiError("ERR_INVALID_STATE", "Claim cannot be withdrawn from its current state")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    policy = db.policies.get(claim["policy_id"])
    if policy:
        domain.recompute_policy_exposure(policy)
    return ok(public(claim), 200)


# =========================================================================
# Supplement
# =========================================================================

@bp.route("/supplements", methods=["POST"])
def create_supplement():
    authenticate()
    require_role("PublicAdjuster")
    body = get_body()
    claim = None
    if body.get("claim_id") is not None:
        claim = fetch(db.claims, body["claim_id"])
    if claim is not None:
        # state (priority 4): claim must be SETTLED or PAID
        if claim["status"] not in ("SETTLED", "PAID"):
            raise ApiError("ERR_INVALID_STATE", "Claim has not settled")
        # OCC (priority 11)
        ecv = body.get("expected_claim_version")
        if isinstance(ecv, int) and not isinstance(ecv, bool):
            if ecv != claim["version"]:
                raise ApiError("ERR_STALE_CLAIM_VERSION",
                               "expected_claim_version does not match current claim version")
    # field validation (priority 12)
    require_fields(body, "claim_id", "expected_claim_version", "amount_cents", "reason")
    as_int(body, "expected_claim_version", non_negative=True)
    amount = as_int(body, "amount_cents", positive=True)
    reason = as_str(body, "reason")
    ent = {
        "id": new_id(),
        "claim_id": claim["id"],
        "amount_cents": amount,
        "reason": reason,
        "submitted_at": None,
        "status": "DRAFT",
    }
    stamp_new(ent)
    db.supplements[ent["id"]] = ent
    # creating the supplement increments the claim's version by 1
    touch(claim)
    return ok(public(ent), 201)


@bp.route("/supplements/<ident>", methods=["GET"])
def get_supplement(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.supplements, ident)), 200)


@bp.route("/supplements", methods=["GET"])
def list_supplements():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.supplements, {"claim_id": "claim_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/supplements/<ident>/submit", methods=["POST"])
def submit_supplement(ident):
    authenticate()
    require_role("PublicAdjuster")
    supp = fetch(db.supplements, ident)
    if supp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Supplement not in DRAFT")
    claim = db.claims.get(supp["claim_id"])
    settled_at = parse_iso(claim["settled_at"])
    if db.now() > settled_at + timedelta(days=SUPPLEMENT_WINDOW_DAYS):
        raise ApiError("ERR_SUPPLEMENT_WINDOW_CLOSED", "Supplement window has closed")
    supp["status"] = "SUBMITTED"
    supp["submitted_at"] = fmt_ts(db.now())
    touch(supp)
    return ok(public(supp), 200)


@bp.route("/supplements/<ident>/decide", methods=["POST"])
def decide_supplement(ident):
    authenticate()
    require_role("FirmPrincipal")
    supp = fetch(db.supplements, ident)
    if supp["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Supplement not in SUBMITTED")
    body = get_body()
    require_fields(body, "decision")
    decision = as_enum(body, "decision", DECISIONS)
    claim = db.claims.get(supp["claim_id"])
    policy = db.policies.get(claim["policy_id"])
    if decision == "APPROVE":
        # fiscal capacity (priority 10)
        if supp["amount_cents"] > policy["remaining_limit_cents"]:
            raise ApiError("ERR_POLICY_LIMIT_EXCEEDED",
                           "Supplement amount exceeds policy remaining limit")
        supp["status"] = "APPROVED"
        touch(supp)
        claim["settlement_amount_cents"] += supp["amount_cents"]
        touch(claim)
        domain.recompute_policy_exposure(policy)
    else:
        supp["status"] = "DENIED"
        touch(supp)
    return ok(public(supp), 200)


# =========================================================================
# Appraisal
# =========================================================================

@bp.route("/appraisals", methods=["POST"])
def create_appraisal():
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    body = get_body()
    claim = None
    if body.get("claim_id") is not None:
        claim = fetch(db.claims, body["claim_id"])
    if claim is not None:
        if claim["status"] not in ("OFFER_RECEIVED", "NEGOTIATING"):
            raise ApiError("ERR_INVALID_STATE",
                           "Appraisal may only be invoked with a carrier offer on record")
    require_fields(body, "claim_id")
    ent = {
        "id": new_id(),
        "claim_id": claim["id"],
        "pa_appraiser_name": None,
        "carrier_appraiser_name": None,
        "umpire_name": None,
        "pa_appraiser_amount_cents": 0,
        "carrier_appraiser_amount_cents": 0,
        "award_cents": 0,
        "status": "INVOKED",
    }
    stamp_new(ent)
    db.appraisals[ent["id"]] = ent
    claim["status"] = "IN_APPRAISAL"
    touch(claim)
    return ok(public(ent), 201)


@bp.route("/appraisals/<ident>", methods=["GET"])
def get_appraisal(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.appraisals, ident)), 200)


@bp.route("/appraisals", methods=["GET"])
def list_appraisals():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.appraisals, {"claim_id": "claim_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/appraisals/<ident>/name-appraisers", methods=["POST"])
def name_appraisers(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    appraisal = fetch(db.appraisals, ident)
    if appraisal["status"] != "INVOKED":
        raise ApiError("ERR_INVALID_STATE", "Appraisal not in INVOKED")
    body = get_body()
    require_fields(body, "pa_appraiser_name", "pa_appraiser_amount_cents",
                   "carrier_appraiser_name", "carrier_appraiser_amount_cents")
    pa_name = as_str(body, "pa_appraiser_name")
    carrier_name = as_str(body, "carrier_appraiser_name")
    pa_amt = as_int(body, "pa_appraiser_amount_cents", non_negative=True)
    carrier_amt = as_int(body, "carrier_appraiser_amount_cents", non_negative=True)
    if pa_name == carrier_name:
        raise ApiError("ERR_APPRAISER_CONFLICT", "Appraisers must be distinct people")
    appraisal["pa_appraiser_name"] = pa_name
    appraisal["carrier_appraiser_name"] = carrier_name
    appraisal["pa_appraiser_amount_cents"] = pa_amt
    appraisal["carrier_appraiser_amount_cents"] = carrier_amt
    appraisal["status"] = "APPRAISERS_NAMED"
    touch(appraisal)
    return ok(public(appraisal), 200)


@bp.route("/appraisals/<ident>/select-umpire", methods=["POST"])
def select_umpire(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    appraisal = fetch(db.appraisals, ident)
    if appraisal["status"] != "APPRAISERS_NAMED":
        raise ApiError("ERR_INVALID_STATE", "Appraisal not in APPRAISERS_NAMED")
    body = get_body()
    require_fields(body, "umpire_name")
    umpire_name = as_str(body, "umpire_name")
    if appraisal["pa_appraiser_amount_cents"] == appraisal["carrier_appraiser_amount_cents"]:
        raise ApiError("ERR_UMPIRE_NOT_NEEDED", "Appraiser valuations agree; no umpire needed")
    if umpire_name in (appraisal["pa_appraiser_name"], appraisal["carrier_appraiser_name"]):
        raise ApiError("ERR_APPRAISER_CONFLICT", "Umpire must differ from both appraisers")
    appraisal["umpire_name"] = umpire_name
    appraisal["status"] = "UMPIRE_SELECTED"
    touch(appraisal)
    return ok(public(appraisal), 200)


@bp.route("/appraisals/<ident>/render-award", methods=["POST"])
def render_award(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal", "System")
    appraisal = fetch(db.appraisals, ident)
    body = get_body()
    status = appraisal["status"]
    pa_amt = appraisal["pa_appraiser_amount_cents"]
    carrier_amt = appraisal["carrier_appraiser_amount_cents"]
    if status == "APPRAISERS_NAMED":
        # agree branch
        if pa_amt != carrier_amt:
            raise ApiError("ERR_UMPIRE_REQUIRED",
                           "Appraiser valuations differ; an umpire is required")
        award = pa_amt
    elif status == "UMPIRE_SELECTED":
        # umpire branch
        require_fields(body, "award_cents")
        award = as_int(body, "award_cents", non_negative=True)
        lo, hi = min(pa_amt, carrier_amt), max(pa_amt, carrier_amt)
        if not (lo <= award <= hi):
            raise ApiError("ERR_AWARD_OUT_OF_RANGE",
                           "Award must lie within the appraiser range")
    else:
        raise ApiError("ERR_INVALID_STATE", "Appraisal not ready for an award")
    appraisal["award_cents"] = award
    appraisal["status"] = "AWARDED"
    touch(appraisal)
    # cascade parent claim IN_APPRAISAL -> SETTLED
    claim = db.claims.get(appraisal["claim_id"])
    contract = db.contracts.get(claim["contract_id"])
    policy = db.policies.get(claim["policy_id"])
    domain.apply_settlement(claim, contract, policy, award, g.user_id)
    return ok(public(appraisal), 200)


@bp.route("/appraisals/<ident>/cancel", methods=["POST"])
def cancel_appraisal(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    appraisal = fetch(db.appraisals, ident)
    if appraisal["status"] != "INVOKED":
        raise ApiError("ERR_INVALID_STATE", "Only an INVOKED appraisal may be cancelled")
    appraisal["status"] = "CANCELLED"
    touch(appraisal)
    claim = db.claims.get(appraisal["claim_id"])
    if claim and claim["status"] == "IN_APPRAISAL":
        claim["status"] = "NEGOTIATING"
        touch(claim)
    return ok(public(appraisal), 200)


# =========================================================================
# Payment
# =========================================================================

@bp.route("/payments", methods=["POST"])
def create_payment():
    authenticate()
    require_role("Carrier")
    body = get_body()
    if body.get("claim_id") is not None:
        fetch(db.claims, body["claim_id"])
    require_fields(body, "claim_id", "amount_cents", "payment_type")
    claim_id = as_str(body, "claim_id")
    amount = as_int(body, "amount_cents", positive=True)
    payment_type = as_enum(body, "payment_type", PAYMENT_TYPES)
    ent = {
        "id": new_id(),
        "claim_id": claim_id,
        "amount_cents": amount,
        "payment_type": payment_type,
        "received_at": fmt_ts(db.now()),
        "status": "RECEIVED",
    }
    stamp_new(ent)
    db.payments[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/payments/<ident>", methods=["GET"])
def get_payment(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.payments, ident)), 200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.payments, {"claim_id": "claim_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/payments/<ident>/clear", methods=["POST"])
def clear_payment(ident):
    authenticate()
    require_role("Carrier")
    payment = fetch(db.payments, ident)
    if payment["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Payment not in RECEIVED")
    claim = db.claims.get(payment["claim_id"])
    if not claim or claim["status"] not in ("SETTLED", "PAID"):
        raise ApiError("ERR_CLAIM_NOT_SETTLED", "Claim is not SETTLED or PAID")
    contract = db.contracts.get(claim["contract_id"])
    policy = db.policies.get(claim["policy_id"])
    payment["status"] = "CLEARED"
    payment["received_at"] = fmt_ts(db.now())
    touch(payment)
    claim["amount_recovered_cents"] += payment["amount_cents"]
    domain.create_disbursement(claim, payment, contract)
    domain.recompute_final_fee(claim, contract)
    if claim["amount_recovered_cents"] >= claim["settlement_amount_cents"] and claim["status"] == "SETTLED":
        claim["status"] = "PAID"
        if contract and contract["status"] == "ACTIVE":
            contract["status"] = "COMPLETED"
            touch(contract)
    touch(claim)
    if policy:
        domain.recompute_policy_exposure(policy)
    return ok(public(payment), 200)


@bp.route("/payments/<ident>/reverse", methods=["POST"])
def reverse_payment(ident):
    authenticate()
    require_role("Carrier", "FirmPrincipal")
    payment = fetch(db.payments, ident)
    if payment["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", "Payment not in CLEARED")
    disb = None
    for d in db.disbursements.values():
        if d["payment_id"] == payment["id"]:
            disb = d
            break
    if disb is not None and disb["status"] == "RELEASED":
        raise ApiError("ERR_DISBURSEMENT_RELEASED",
                       "Payment cannot be reversed after its disbursement is released")
    payment["status"] = "REVERSED"
    touch(payment)
    claim = db.claims.get(payment["claim_id"])
    contract = db.contracts.get(claim["contract_id"]) if claim else None
    if claim:
        claim["amount_recovered_cents"] -= payment["amount_cents"]
        domain.recompute_final_fee(claim, contract)
        touch(claim)
    if disb is not None and disb["status"] in ("PENDING", "HELD"):
        disb["status"] = "VOIDED"
        touch(disb)
    if claim:
        policy = db.policies.get(claim["policy_id"])
        if policy:
            domain.recompute_policy_exposure(policy)
    return ok(public(payment), 200)


# =========================================================================
# Disbursement
# =========================================================================

@bp.route("/disbursements/<ident>", methods=["GET"])
def get_disbursement(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.disbursements, ident)), 200)


@bp.route("/disbursements", methods=["GET"])
def list_disbursements():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.disbursements, {
        "claim_id": "claim_id", "payment_id": "payment_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/disbursements/<ident>/release", methods=["POST"])
def release_disbursement(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    disb = fetch(db.disbursements, ident)
    if disb["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Disbursement not in PENDING")
    claim = db.claims.get(disb["claim_id"])
    # segregation of duties (priority 9)
    if claim and g.user_id == claim.get("accepted_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Releaser must differ from the settlement acceptor")
    # no open dispute
    for disp in db.disputes.values():
        if disp["claim_id"] == disb["claim_id"] and disp["status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError("ERR_OPEN_DISPUTE_BLOCKS_RELEASE",
                           "An open dispute blocks disbursement release")
    disb["status"] = "RELEASED"
    disb["released_at"] = fmt_ts(db.now())
    touch(disb)
    contract = db.contracts.get(claim["contract_id"]) if claim else None
    if contract:
        contract["advance_recouped_cents"] += disb["advance_recoup_cents"]
        touch(contract)
    return ok(public(disb), 200)


@bp.route("/disbursements/<ident>/hold", methods=["POST"])
def hold_disbursement(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    disb = fetch(db.disbursements, ident)
    if disb["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Disbursement not in PENDING")
    disb["status"] = "HELD"
    touch(disb)
    return ok(public(disb), 200)


@bp.route("/disbursements/<ident>/resume", methods=["POST"])
def resume_disbursement(ident):
    authenticate()
    require_role("PublicAdjuster", "FirmPrincipal")
    disb = fetch(db.disbursements, ident)
    if disb["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", "Disbursement not in HELD")
    disb["status"] = "PENDING"
    touch(disb)
    return ok(public(disb), 200)


# =========================================================================
# Dispute
# =========================================================================

@bp.route("/disputes", methods=["POST"])
def create_dispute():
    authenticate()
    require_role("Client", "Carrier", "FirmPrincipal")
    body = get_body()
    if body.get("claim_id") is not None:
        fetch(db.claims, body["claim_id"])
    require_fields(body, "claim_id", "dispute_type", "raised_by", "description")
    claim_id = as_str(body, "claim_id")
    dispute_type = as_enum(body, "dispute_type", DISPUTE_TYPES)
    raised_by = as_enum(body, "raised_by", RAISED_BY)
    description = as_str(body, "description")
    ent = {
        "id": new_id(),
        "claim_id": claim_id,
        "dispute_type": dispute_type,
        "raised_by": raised_by,
        "description": description,
        "resolution": None,
        "status": "OPEN",
    }
    stamp_new(ent)
    db.disputes[ent["id"]] = ent
    return ok(public(ent), 201)


@bp.route("/disputes/<ident>", methods=["GET"])
def get_dispute(ident):
    authenticate()
    require_role(*READ_ROLES)
    return ok(public(fetch(db.disputes, ident)), 200)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    authenticate()
    require_role(*READ_ROLES)
    items = filtered_list(db.disputes, {"claim_id": "claim_id", "status": "status"})
    data, pg = paginate(items)
    return ok(data, 200, pagination=pg)


@bp.route("/disputes/<ident>/review", methods=["POST"])
def review_dispute(ident):
    authenticate()
    require_role("FirmPrincipal")
    disp = fetch(db.disputes, ident)
    if disp["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Dispute not in OPEN")
    disp["status"] = "UNDER_REVIEW"
    touch(disp)
    return ok(public(disp), 200)


@bp.route("/disputes/<ident>/resolve", methods=["POST"])
def resolve_dispute(ident):
    authenticate()
    require_role("FirmPrincipal")
    disp = fetch(db.disputes, ident)
    if disp["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Dispute not in UNDER_REVIEW")
    body = get_body()
    require_fields(body, "resolution")
    resolution = as_str(body, "resolution")
    disp["status"] = "RESOLVED"
    disp["resolution"] = resolution
    touch(disp)
    return ok(public(disp), 200)


@bp.route("/disputes/<ident>/withdraw", methods=["POST"])
def withdraw_dispute(ident):
    authenticate()
    require_role("Client", "Carrier")
    disp = fetch(db.disputes, ident)
    if disp["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", "Dispute cannot be withdrawn from its current state")
    disp["status"] = "WITHDRAWN"
    touch(disp)
    return ok(public(disp), 200)
