"""Probate Court & Estate Administration API — Flask, in-memory."""
import os

from flask import Flask, request

import calc
from db import store, new_id, now_iso_from, parse_iso
from errors import APIError, err
from middleware import authenticate, authorize
from response import success, error_response

app = Flask(__name__)


# ----------------------------------------------------------------------------
# Common helpers
# ----------------------------------------------------------------------------
def clock_iso():
    return now_iso_from(store.clock)


def base_fields():
    ts = clock_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    entity["updated_at"] = clock_iso()
    entity["version"] += 1


def bump_estate(estate):
    estate["updated_at"] = clock_iso()
    estate["version"] += 1


def get_json():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_MISSING_FIELD", "Request body must be a JSON object")
    return body


def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_MISSING_FIELD", f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_MISSING_FIELD", f"Field {field} must be a non-empty string")
    return v


def require_positive_int(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise err("ERR_MISSING_FIELD", f"Field {field} must be a positive integer")
    return v


def require_non_negative_int(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise err("ERR_MISSING_FIELD", f"Field {field} must be a non-negative integer")
    return v


def require_bool(body, field):
    v = require_present(body, field)
    if not isinstance(v, bool):
        raise err("ERR_MISSING_FIELD", f"Field {field} must be a boolean")
    return v


def require_enum(body, field, members):
    v = require_str(body, field)
    if v not in members:
        raise err("ERR_MISSING_FIELD", f"Field {field} must be one of {sorted(members)}")
    return v


def require_datetime(body, field):
    v = require_present(body, field)
    try:
        return parse_iso(v)
    except Exception:
        raise err("ERR_MISSING_FIELD", f"Field {field} must be a valid ISO 8601 datetime")


def find(collection_name, entity_id):
    ent = store.collection(collection_name).get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent


def get_estate(estate_id):
    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_NOT_FOUND", "Estate not found")
    return est


def check_estate_version(body, estate):
    """OCC: expected_estate_version must match estate.version."""
    expected = body.get("expected_estate_version")
    if expected is None:
        raise err("ERR_MISSING_FIELD", "Missing required field: expected_estate_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_MISSING_FIELD", "expected_estate_version must be an integer")
    if expected != estate["version"]:
        raise err("ERR_STALE_VERSION", "expected_estate_version does not match Estate.version")


# ----------------------------------------------------------------------------
# Pagination / listing
# ----------------------------------------------------------------------------
def paginate(items):
    # sort by created_at ascending (stable). created_at ties broken by insertion.
    items = sorted(items, key=lambda e: (e["created_at"],))
    total = len(items)
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    # limit default 10, min 1, max 100
    if limit is None:
        lim = 10
    else:
        try:
            lim = int(limit)
        except Exception:
            raise err("ERR_MISSING_FIELD", "limit must be an integer")
        if lim < 1:
            lim = 1
        if lim > 100:
            lim = 100
    if offset is None:
        off = 0
    else:
        try:
            off = int(offset)
        except Exception:
            raise err("ERR_MISSING_FIELD", "offset must be an integer")
        if off < 0:
            off = 0
    page = items[off:off + lim]
    pagination = {
        "limit": lim,
        "offset": off,
        "total_count": total,
        "has_more": off + lim < total,
    }
    return page, pagination


def list_filtered(collection_name, filters):
    items = list(store.collection(collection_name).values())
    for key in filters:
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if str(e.get(key)) == val]
    page, pagination = paginate(items)
    return success(page, response_type="array", status=200, pagination=pagination)


# ----------------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------------
@app.errorhandler(APIError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, APIError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_MISSING_FIELD", str(e)), 400


# ============================================================================
# Clock
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    body = get_json()
    dt = require_datetime(body, "to_iso8601")
    store.clock = dt
    return success({}, response_type="object", status=200)


# ============================================================================
# Estate
# ============================================================================
@app.route("/estates", methods=["POST"])
def create_estate():
    _, role = authenticate()
    authorize(role, {"Clerk"})
    body = get_json()
    decedent_name = require_str(body, "decedent_name")
    dod = require_datetime(body, "date_of_death")
    county_code = require_str(body, "county_code")
    estate_type = require_enum(body, "estate_type", {"TESTATE", "INTESTATE"})
    gross = require_positive_int(body, "gross_estate_value_cents")
    # date_of_death must be <= current logical clock
    if dod > store.clock:
        raise err("ERR_MISSING_FIELD", "date_of_death must not be after the current clock")

    est = base_fields()
    est.update({
        "decedent_name": decedent_name,
        "date_of_death": body["date_of_death"],
        "county_code": county_code,
        "estate_type": estate_type,
        "gross_estate_value_cents": gross,
        "status": "DRAFT",
        "supervision_level": calc.supervision_level(gross),
        "claim_period_opened_at": None,
        "claim_bar_date": None,
        "inventory_total_cents": 0,
        "marshaled_cash_cents": 0,
        "allowed_claims_total_cents": 0,
        "residue_cents": 0,
    })
    store.estates[est["id"]] = est
    return success(est, status=201)


@app.route("/estates/<eid>", methods=["GET"])
def get_estate_ep(eid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    est = find("estates", eid)
    calc.sync_estate_derived(est)
    return success(est)


@app.route("/estates", methods=["GET"])
def list_estates():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    for est in store.estates.values():
        calc.sync_estate_derived(est)
    return list_filtered("estates", ["county_code", "status"])


# ============================================================================
# Petition
# ============================================================================
@app.route("/petitions", methods=["POST"])
def create_petition():
    _, role = authenticate()
    authorize(role, {"Clerk"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    petitioner_name = require_str(body, "petitioner_name")
    will_lodged = require_bool(body, "will_lodged")
    nominated = require_str(body, "nominated_representative_name")
    # will_date required iff will_lodged true, else must be omitted
    will_date = None
    if will_lodged:
        require_datetime(body, "will_date")
        will_date = body["will_date"]
    else:
        if "will_date" in body and body["will_date"] is not None:
            raise err("ERR_MISSING_FIELD", "will_date must be omitted when will_lodged is false")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")

    pet = base_fields()
    pet.update({
        "estate_id": estate_id,
        "petitioner_name": petitioner_name,
        "will_lodged": will_lodged,
        "will_date": will_date,
        "nominated_representative_name": nominated,
        "status": "PENDING",
        "denial_reason": None,
    })
    store.petitions[pet["id"]] = pet
    return success(pet, status=201)


@app.route("/petitions/<pid>", methods=["GET"])
def get_petition(pid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("petitions", pid))


@app.route("/petitions", methods=["GET"])
def list_petitions():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("petitions", ["estate_id", "status"])


@app.route("/petitions/<pid>/grant", methods=["POST"])
def grant_petition(pid):
    uid, role = authenticate()
    authorize(role, {"ProbateJudge"})
    pet = find("petitions", pid)
    est = get_estate(pet["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if pet["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Petition not PENDING")
    if est["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Estate not DRAFT")
    if est["estate_type"] == "TESTATE" and not pet["will_lodged"]:
        raise err("ERR_WILL_NOT_LODGED", "TESTATE estate requires a lodged will")
    # side effects
    pet["status"] = "GRANTED"
    touch(pet)
    est["status"] = "OPEN"
    est["claim_period_opened_at"] = clock_iso()
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(pet)


@app.route("/petitions/<pid>/deny", methods=["POST"])
def deny_petition(pid):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    pet = find("petitions", pid)
    est = get_estate(pet["estate_id"])
    body = get_json()
    denial_reason = require_str(body, "denial_reason")
    check_estate_version(body, est)
    if pet["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Petition not PENDING")
    if est["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Estate not DRAFT")
    pet["status"] = "DENIED"
    pet["denial_reason"] = denial_reason
    touch(pet)
    bump_estate(est)
    return success(pet)


# ============================================================================
# PersonalRepresentative
# ============================================================================
@app.route("/representatives", methods=["POST"])
def create_representative():
    _, role = authenticate()
    authorize(role, {"Clerk"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    petition_id = require_str(body, "petition_id")
    full_name = require_str(body, "full_name")
    rep_uid = require_str(body, "representative_user_id")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")
    pet = store.petitions.get(petition_id)
    if pet is None or pet["estate_id"] != estate_id:
        raise err("ERR_INVALID_REFERENCE", "petition_id does not resolve under this estate")

    level = calc.supervision_level(est["gross_estate_value_cents"])
    rep = base_fields()
    rep.update({
        "estate_id": estate_id,
        "petition_id": petition_id,
        "full_name": full_name,
        "representative_user_id": rep_uid,
        "bond_required": calc.bond_required_flag(level),
        "bond_id": None,
        "status": "NOMINATED",
        "letters_issued_at": None,
    })
    store.representatives[rep["id"]] = rep
    return success(rep, status=201)


@app.route("/representatives/<rid>", methods=["GET"])
def get_representative(rid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("representatives", rid))


@app.route("/representatives", methods=["GET"])
def list_representatives():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("representatives", ["estate_id", "petition_id", "bond_id", "status"])


@app.route("/representatives/<rid>/appoint", methods=["POST"])
def appoint_representative(rid):
    uid, role = authenticate()
    authorize(role, {"ProbateJudge"})
    rep = find("representatives", rid)
    est = get_estate(rep["estate_id"])
    body = get_json()
    # Segregation of duties (priority 3, before state checks)
    if uid == rep["representative_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Judge may not appoint self as representative")
    check_estate_version(body, est)
    if rep["status"] != "NOMINATED":
        raise err("ERR_INVALID_STATE", "Representative not NOMINATED")
    # cross-entity state gate: petition GRANTED
    pet = store.petitions.get(rep["petition_id"])
    if pet is None or pet["status"] != "GRANTED":
        raise err("ERR_CROSS_ENTITY_STATE", "Petition not GRANTED")
    approved_bond = None
    if rep["bond_required"]:
        for b in store.bonds.values():
            if b["estate_id"] == rep["estate_id"] and b["representative_id"] == rid and b["status"] == "APPROVED":
                approved_bond = b
                break
        if approved_bond is None:
            raise err("ERR_BOND_NOT_APPROVED", "Required bond is not APPROVED")
    rep["status"] = "APPOINTED"
    rep["letters_issued_at"] = clock_iso()
    rep["bond_id"] = approved_bond["id"] if approved_bond else None
    touch(rep)
    bump_estate(est)
    return success(rep)


def _rep_simple_transition(rid, from_states, to_state, forfeit_bond=False,
                           exonerate_bond=False, require_closed=False):
    uid, role = authenticate()
    authorize(role, {"ProbateJudge"})
    rep = find("representatives", rid)
    est = get_estate(rep["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if rep["status"] not in from_states:
        raise err("ERR_INVALID_STATE", f"Representative not in {from_states}")
    if require_closed and est["status"] != "CLOSED":
        raise err("ERR_CROSS_ENTITY_STATE", "Estate not CLOSED")
    rep["status"] = to_state
    if (forfeit_bond or exonerate_bond) and rep.get("bond_id"):
        bond = store.bonds.get(rep["bond_id"])
        if bond is not None:
            bond["status"] = "FORFEITED" if forfeit_bond else "EXONERATED"
            touch(bond)
    touch(rep)
    bump_estate(est)
    return success(rep)


@app.route("/representatives/<rid>/suspend", methods=["POST"])
def suspend_representative(rid):
    return _rep_simple_transition(rid, {"APPOINTED"}, "SUSPENDED")


@app.route("/representatives/<rid>/reinstate", methods=["POST"])
def reinstate_representative(rid):
    return _rep_simple_transition(rid, {"SUSPENDED"}, "APPOINTED")


@app.route("/representatives/<rid>/remove", methods=["POST"])
def remove_representative(rid):
    return _rep_simple_transition(rid, {"APPOINTED", "SUSPENDED"}, "REMOVED", forfeit_bond=True)


@app.route("/representatives/<rid>/discharge", methods=["POST"])
def discharge_representative(rid):
    return _rep_simple_transition(rid, {"APPOINTED"}, "DISCHARGED", exonerate_bond=True,
                                  require_closed=True)


# ============================================================================
# Bond
# ============================================================================
@app.route("/bonds", methods=["POST"])
def create_bond():
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative", "Clerk"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    representative_id = require_str(body, "representative_id")
    surety_name = require_str(body, "surety_name")
    penal = require_non_negative_int(body, "penal_amount_cents")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")
    rep = store.representatives.get(representative_id)
    if rep is None or rep["estate_id"] != estate_id:
        raise err("ERR_INVALID_REFERENCE", "representative_id does not resolve under this estate")

    level = calc.supervision_level(est["gross_estate_value_cents"])
    bond = base_fields()
    bond.update({
        "estate_id": estate_id,
        "representative_id": representative_id,
        "surety_name": surety_name,
        "penal_amount_cents": penal,
        "required_amount_cents": calc.bond_required_amount(est["gross_estate_value_cents"], level),
        "status": "FILED",
    })
    store.bonds[bond["id"]] = bond
    return success(bond, status=201)


@app.route("/bonds/<bid>", methods=["GET"])
def get_bond(bid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("bonds", bid))


@app.route("/bonds", methods=["GET"])
def list_bonds():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("bonds", ["estate_id", "representative_id", "status"])


@app.route("/bonds/<bid>/approve", methods=["POST"])
def approve_bond(bid):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    bond = find("bonds", bid)
    est = get_estate(bond["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if bond["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Bond not FILED")
    if bond["penal_amount_cents"] < bond["required_amount_cents"]:
        raise err("ERR_BOND_INSUFFICIENT", "penal_amount_cents below required_amount_cents")
    bond["status"] = "APPROVED"
    touch(bond)
    bump_estate(est)
    return success(bond)


# ============================================================================
# Beneficiary
# ============================================================================
@app.route("/beneficiaries", methods=["POST"])
def create_beneficiary():
    _, role = authenticate()
    authorize(role, {"Clerk", "PersonalRepresentative"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    full_name = require_str(body, "full_name")
    relationship = require_enum(body, "relationship",
                                {"SPOUSE", "CHILD", "HEIR", "DEVISEE", "CREDITOR_RESIDUAL"})
    share_bps = require_positive_int(body, "share_bps")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")

    ben = base_fields()
    ben.update({
        "estate_id": estate_id,
        "full_name": full_name,
        "relationship": relationship,
        "share_bps": share_bps,
        "distributed_cents": 0,
    })
    store.beneficiaries[ben["id"]] = ben
    return success(ben, status=201)


@app.route("/beneficiaries/<bid>", methods=["GET"])
def get_beneficiary(bid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("beneficiaries", bid))


@app.route("/beneficiaries", methods=["GET"])
def list_beneficiaries():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("beneficiaries", ["estate_id"])


# ============================================================================
# CreditorClaim
# ============================================================================
@app.route("/claims", methods=["POST"])
def create_claim():
    _, role = authenticate()
    authorize(role, {"Clerk", "PersonalRepresentative"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    creditor_name = require_str(body, "creditor_name")
    claim_class = require_enum(body, "claim_class",
                               {"SECURED", "FUNERAL", "ADMIN", "TAX", "GENERAL"})
    claimed = require_positive_int(body, "claimed_amount_cents")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")

    claim = base_fields()
    claim.update({
        "estate_id": estate_id,
        "creditor_name": creditor_name,
        "claim_class": claim_class,
        "claimed_amount_cents": claimed,
        "allowed_amount_cents": None,
        "filed_at": clock_iso(),
        "paid_amount_cents": None,
        "status": "FILED",
    })
    store.claims[claim["id"]] = claim
    return success(claim, status=201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("claims", cid))


@app.route("/claims", methods=["GET"])
def list_claims():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("claims", ["estate_id", "claim_class", "status"])


def _acting_pr_owns(uid, estate_id):
    """Return True if an APPOINTED representative on this estate has this user id."""
    for rep in store.representatives.values():
        if (rep["estate_id"] == estate_id and rep["status"] == "APPOINTED"
                and rep["representative_user_id"] == uid):
            return True
    return False


@app.route("/claims/<cid>/allow", methods=["POST"])
def allow_claim(cid):
    uid, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    claim = find("claims", cid)
    est = get_estate(claim["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim not FILED")
    if est["status"] not in ("OPEN", "INVENTORIED", "ACCOUNTING"):
        raise err("ERR_INVALID_STATE", "Estate not in an allow-eligible state")
    # cross-entity: PR appointed and owns estate
    if not _acting_pr_owns(uid, est["id"]):
        raise err("ERR_CROSS_ENTITY_STATE", "Acting PR not APPOINTED on this estate")
    # late claim -> auto-bar branch
    bar = calc.claim_bar_date(parse_iso(est["claim_period_opened_at"]))
    filed = parse_iso(claim["filed_at"])
    if filed > bar:
        claim["status"] = "BARRED"
        touch(claim)
        bump_estate(est)
        raise err("ERR_CLAIM_PERIOD_CLOSED", "Claim filed after the bar date; barred")
    # in-period: validate allowed_amount
    allowed = require_present(body, "allowed_amount_cents")
    if isinstance(allowed, bool) or not isinstance(allowed, int):
        raise err("ERR_MISSING_FIELD", "allowed_amount_cents must be an integer")
    if not (0 < allowed <= claim["claimed_amount_cents"]):
        raise err("ERR_ALLOWED_AMOUNT_INVALID", "allowed_amount_cents out of range")
    claim["allowed_amount_cents"] = allowed
    claim["status"] = "ALLOWED"
    touch(claim)
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(claim)


@app.route("/claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    uid, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    claim = find("claims", cid)
    est = get_estate(claim["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim not FILED")
    if not _acting_pr_owns(uid, est["id"]):
        raise err("ERR_CROSS_ENTITY_STATE", "Acting PR not APPOINTED on this estate")
    claim["status"] = "REJECTED"
    touch(claim)
    bump_estate(est)
    return success(claim)


@app.route("/claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    uid, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    claim = find("claims", cid)
    est = get_estate(claim["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if claim["status"] != "ALLOWED":
        raise err("ERR_INVALID_STATE", "Claim not ALLOWED")
    if est["status"] != "ACCOUNTING":
        raise err("ERR_INVALID_STATE", "Estate not ACCOUNTING")
    # priority waterfall: this claim must be lowest-ordered ALLOWED-not-PAID claim
    def order_key(c):
        return (calc.CLAIM_RANK[c["claim_class"]], c["created_at"])
    allowed_not_paid = [c for c in store.claims.values()
                        if c["estate_id"] == est["id"] and c["status"] == "ALLOWED"]
    allowed_not_paid.sort(key=order_key)
    if allowed_not_paid and allowed_not_paid[0]["id"] != claim["id"]:
        raise err("ERR_CLAIM_PRIORITY_VIOLATION",
                  "A strictly-higher-priority ALLOWED claim is still unpaid")
    pool = est["marshaled_cash_cents"]
    if pool <= 0:
        raise err("ERR_INSUFFICIENT_MARSHALED_FUNDS", "No marshaled cash available")
    allocation = min(claim["allowed_amount_cents"], pool)
    claim["paid_amount_cents"] = allocation
    claim["status"] = "PAID"
    est["marshaled_cash_cents"] = pool - allocation
    touch(claim)
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(claim)


# ============================================================================
# Asset
# ============================================================================
@app.route("/assets", methods=["POST"])
def create_asset():
    _, role = authenticate()
    authorize(role, {"Clerk", "PersonalRepresentative"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    description = require_str(body, "description")
    asset_class = require_enum(body, "asset_class",
                               {"REAL_PROPERTY", "CASH", "SECURITY", "PERSONAL_PROPERTY"})
    declared = require_positive_int(body, "declared_value_cents")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")

    asset = base_fields()
    asset.update({
        "estate_id": estate_id,
        "description": description,
        "asset_class": asset_class,
        "declared_value_cents": declared,
        "appraised_value_cents": None,
        "liquidation_proceeds_cents": None,
        "status": "LISTED",
    })
    store.assets[asset["id"]] = asset
    return success(asset, status=201)


@app.route("/assets/<aid>", methods=["GET"])
def get_asset(aid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("assets", aid))


@app.route("/assets", methods=["GET"])
def list_assets():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("assets", ["estate_id", "asset_class", "status"])


@app.route("/assets/<aid>/appraise", methods=["POST"])
def appraise_asset(aid):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    asset = find("assets", aid)
    est = get_estate(asset["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if asset["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Asset not LISTED")
    if est["status"] not in ("OPEN", "INVENTORIED"):
        raise err("ERR_INVALID_STATE", "Estate not in an appraise-eligible state")
    appraised = require_positive_int(body, "appraised_value_cents")
    asset["appraised_value_cents"] = appraised
    asset["status"] = "APPRAISED"
    touch(asset)
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(asset)


@app.route("/assets/<aid>/marshal", methods=["POST"])
def marshal_asset(aid):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    asset = find("assets", aid)
    est = get_estate(asset["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if asset["status"] != "APPRAISED":
        raise err("ERR_INVALID_STATE", "Asset not APPRAISED")
    if est["status"] not in ("INVENTORIED", "ACCOUNTING"):
        raise err("ERR_INVALID_STATE", "Estate not in a marshal-eligible state")
    asset["status"] = "MARSHALED"
    if asset["asset_class"] == "CASH":
        est["marshaled_cash_cents"] += asset["appraised_value_cents"]
    touch(asset)
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(asset)


@app.route("/assets/<aid>/liquidate", methods=["POST"])
def liquidate_asset(aid):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    asset = find("assets", aid)
    est = get_estate(asset["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if asset["status"] != "MARSHALED":
        raise err("ERR_INVALID_STATE", "Asset not MARSHALED")
    if est["status"] != "ACCOUNTING":
        raise err("ERR_INVALID_STATE", "Estate not ACCOUNTING")
    if asset["asset_class"] != "CASH":
        proceeds = require_positive_int(body, "liquidation_proceeds_cents")
    else:
        # for CASH, proceeds optional; if supplied must be positive int
        if "liquidation_proceeds_cents" in body and body["liquidation_proceeds_cents"] is not None:
            proceeds = require_positive_int(body, "liquidation_proceeds_cents")
        else:
            proceeds = asset["appraised_value_cents"]
    asset["liquidation_proceeds_cents"] = proceeds
    asset["status"] = "LIQUIDATED"
    est["marshaled_cash_cents"] += proceeds
    touch(asset)
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(asset)


@app.route("/assets/<aid>/distribute-in-kind", methods=["POST"])
def distribute_in_kind(aid):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    asset = find("assets", aid)
    est = get_estate(asset["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if asset["status"] != "MARSHALED":
        raise err("ERR_INVALID_STATE", "Asset not MARSHALED")
    if est["status"] != "DISTRIBUTING":
        raise err("ERR_INVALID_STATE", "Estate not DISTRIBUTING")
    asset["status"] = "DISTRIBUTED"
    touch(asset)
    bump_estate(est)
    return success(asset)


# ============================================================================
# Distribution
# ============================================================================
@app.route("/distributions", methods=["POST"])
def create_distribution():
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    beneficiary_id = require_str(body, "beneficiary_id")
    proposed = require_positive_int(body, "proposed_amount_cents")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")
    ben = store.beneficiaries.get(beneficiary_id)
    if ben is None or ben["estate_id"] != estate_id:
        raise err("ERR_INVALID_REFERENCE", "beneficiary_id does not resolve under this estate")

    dist = base_fields()
    dist.update({
        "estate_id": estate_id,
        "beneficiary_id": beneficiary_id,
        "proposed_amount_cents": proposed,
        "receipt_reference": None,
        "status": "PROPOSED",
    })
    store.distributions[dist["id"]] = dist
    return success(dist, status=201)


@app.route("/distributions/<did>", methods=["GET"])
def get_distribution(did):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("distributions", did))


@app.route("/distributions", methods=["GET"])
def list_distributions():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("distributions", ["estate_id", "beneficiary_id", "status"])


@app.route("/distributions/<did>/approve", methods=["POST"])
def approve_distribution(did):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    dist = find("distributions", did)
    est = get_estate(dist["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if dist["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Distribution not PROPOSED")
    if est["status"] != "DISTRIBUTING":
        raise err("ERR_INVALID_STATE", "Estate not DISTRIBUTING")
    # all allowed claims paid: allowed_claims_total == sum of PAID claims' paid_amount
    calc.sync_estate_derived(est)
    paid_total = sum(c.get("paid_amount_cents", 0) or 0
                     for c in store.claims.values()
                     if c["estate_id"] == est["id"] and c["status"] == "PAID")
    if est["allowed_claims_total_cents"] != paid_total:
        raise err("ERR_CLAIMS_UNPAID", "Some allowed claims are not yet paid")
    if dist["proposed_amount_cents"] > est["residue_cents"]:
        raise err("ERR_DISTRIBUTION_EXCEEDS_RESIDUE", "proposed amount exceeds residue")
    dist["status"] = "APPROVED"
    touch(dist)
    bump_estate(est)
    return success(dist)


@app.route("/distributions/<did>/pay", methods=["POST"])
def pay_distribution(did):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    dist = find("distributions", did)
    est = get_estate(dist["estate_id"])
    body = get_json()
    receipt = require_str(body, "receipt_reference")
    check_estate_version(body, est)
    if dist["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Distribution not APPROVED")
    if est["marshaled_cash_cents"] < dist["proposed_amount_cents"]:
        raise err("ERR_INSUFFICIENT_MARSHALED_FUNDS", "Insufficient marshaled cash")
    dist["receipt_reference"] = receipt
    dist["status"] = "PAID"
    est["marshaled_cash_cents"] -= dist["proposed_amount_cents"]
    # recompute beneficiary distributed
    ben = store.beneficiaries.get(dist["beneficiary_id"])
    if ben is not None:
        ben["distributed_cents"] = calc.recompute_beneficiary_distributed(ben["id"], est["id"])
        touch(ben)
    touch(dist)
    calc.sync_estate_derived(est)
    bump_estate(est)
    return success(dist)


@app.route("/distributions/<did>/return", methods=["POST"])
def return_distribution(did):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    dist = find("distributions", did)
    est = get_estate(dist["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if dist["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Distribution not APPROVED")
    dist["status"] = "RETURNED"
    touch(dist)
    bump_estate(est)
    return success(dist)


# ============================================================================
# AccountingReport
# ============================================================================
@app.route("/accountings", methods=["POST"])
def create_accounting():
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    report_type = require_enum(body, "report_type", {"INVENTORY", "INTERIM", "FINAL"})

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")

    rep = base_fields()
    rep.update({
        "estate_id": estate_id,
        "report_type": report_type,
        "snapshot_inventory_cents": None,
        "snapshot_allowed_claims_cents": None,
        "snapshot_distributed_cents": None,
        "balances": None,
        "status": "DRAFT",
    })
    store.accountings[rep["id"]] = rep
    return success(rep, status=201)


@app.route("/accountings/<aid>", methods=["GET"])
def get_accounting(aid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("accountings", aid))


@app.route("/accountings", methods=["GET"])
def list_accountings():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("accountings", ["estate_id", "report_type", "status"])


@app.route("/accountings/<aid>/file", methods=["POST"])
def file_accounting(aid):
    _, role = authenticate()
    authorize(role, {"PersonalRepresentative"})
    rep = find("accountings", aid)
    est = get_estate(rep["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if rep["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Report not DRAFT")
    rt = rep["report_type"]
    need = {"INVENTORY": "OPEN", "INTERIM": "INVENTORIED", "FINAL": "ACCOUNTING"}[rt]
    if est["status"] != need:
        raise err("ERR_INVALID_STATE", f"Estate must be {need} to file a {rt} report")
    if rt == "FINAL":
        # every ALLOWED claim already PAID
        for c in store.claims.values():
            if c["estate_id"] == est["id"] and c["status"] == "ALLOWED":
                raise err("ERR_CLAIMS_UNPAID", "Some allowed claims are not yet paid")
    calc.sync_estate_derived(est)
    rep["snapshot_inventory_cents"] = est["inventory_total_cents"]
    rep["snapshot_allowed_claims_cents"] = est["allowed_claims_total_cents"]
    rep["snapshot_distributed_cents"] = sum(
        d["proposed_amount_cents"] for d in store.distributions.values()
        if d["estate_id"] == est["id"] and d["status"] == "PAID")
    rep["balances"] = calc.accounting_balance(est["id"], est["marshaled_cash_cents"])
    rep["status"] = "FILED"
    touch(rep)
    if rt == "FINAL":
        est["status"] = "DISTRIBUTING"
    bump_estate(est)
    return success(rep)


@app.route("/accountings/<aid>/approve", methods=["POST"])
def approve_accounting(aid):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    rep = find("accountings", aid)
    est = get_estate(rep["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if rep["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Report not FILED")
    # recompute balance fresh
    fresh_balance = calc.accounting_balance(est["id"], est["marshaled_cash_cents"])
    rep["balances"] = fresh_balance
    if not fresh_balance:
        raise err("ERR_ACCOUNTING_UNBALANCED", "Accounting does not balance")
    rep["status"] = "APPROVED"
    rt = rep["report_type"]
    if rt == "INVENTORY" and est["status"] == "OPEN":
        est["status"] = "INVENTORIED"
    elif rt == "INTERIM" and est["status"] == "INVENTORIED":
        est["status"] = "ACCOUNTING"
    elif rt == "FINAL" and est["status"] == "DISTRIBUTING":
        est["status"] = "CLOSED"
    touch(rep)
    bump_estate(est)
    return success(rep)


@app.route("/accountings/<aid>/reject", methods=["POST"])
def reject_accounting(aid):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    rep = find("accountings", aid)
    est = get_estate(rep["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if rep["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Report not FILED")
    rep["status"] = "REJECTED"
    touch(rep)
    bump_estate(est)
    return success(rep)


# ============================================================================
# Hearing
# ============================================================================
@app.route("/hearings", methods=["POST"])
def create_hearing():
    _, role = authenticate()
    authorize(role, {"Clerk"})
    body = get_json()
    estate_id = require_str(body, "estate_id")
    hearing_type = require_enum(body, "hearing_type", {"PETITION", "ACCOUNTING", "REMOVAL"})
    courtroom_code = require_str(body, "courtroom_code")
    judge_user_id = require_str(body, "judge_user_id")
    start_at = require_datetime(body, "start_at")
    end_at = require_datetime(body, "end_at")
    if end_at <= start_at:
        raise err("ERR_MISSING_FIELD", "end_at must be strictly after start_at")

    est = store.estates.get(estate_id)
    if est is None:
        raise err("ERR_INVALID_REFERENCE", "estate_id does not resolve")

    # courtroom overlap: half-open, no buffer
    for h in store.hearings.values():
        if h["status"] == "SCHEDULED" and h["courtroom_code"] == courtroom_code:
            e_start = parse_iso(h["start_at"])
            e_end = parse_iso(h["end_at"])
            if start_at < e_end and e_start < end_at:
                raise err("ERR_COURTROOM_CONFLICT", "Courtroom interval overlap")
    # judge calendar overlap: closed interval + 30-min buffer
    from datetime import timedelta
    recess = timedelta(minutes=calc.JUDGE_RECESS_MINUTES)
    n_start = start_at - recess
    n_end = end_at + recess
    for h in store.hearings.values():
        if h["status"] == "SCHEDULED" and h["judge_user_id"] == judge_user_id:
            e_start = parse_iso(h["start_at"])
            e_end = parse_iso(h["end_at"])
            if n_start <= e_end and e_start <= n_end:
                raise err("ERR_JUDGE_CALENDAR_CONFLICT", "Judge calendar overlap")

    hearing = base_fields()
    hearing.update({
        "estate_id": estate_id,
        "hearing_type": hearing_type,
        "courtroom_code": courtroom_code,
        "judge_user_id": judge_user_id,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "status": "SCHEDULED",
    })
    store.hearings[hearing["id"]] = hearing
    return success(hearing, status=201)


@app.route("/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return success(find("hearings", hid))


@app.route("/hearings", methods=["GET"])
def list_hearings():
    _, role = authenticate()
    authorize(role, {"Clerk", "ProbateJudge", "PersonalRepresentative"})
    return list_filtered("hearings", ["estate_id", "courtroom_code", "judge_user_id", "status"])


@app.route("/hearings/<hid>/hold", methods=["POST"])
def hold_hearing(hid):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    hearing = find("hearings", hid)
    est = get_estate(hearing["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if hearing["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Hearing not SCHEDULED")
    if store.clock < parse_iso(hearing["start_at"]):
        raise err("ERR_INVALID_STATE", "Hearing start time not reached")
    hearing["status"] = "HELD"
    touch(hearing)
    bump_estate(est)
    return success(hearing)


@app.route("/hearings/<hid>/vacate", methods=["POST"])
def vacate_hearing(hid):
    _, role = authenticate()
    authorize(role, {"ProbateJudge"})
    hearing = find("hearings", hid)
    est = get_estate(hearing["estate_id"])
    body = get_json()
    check_estate_version(body, est)
    if hearing["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Hearing not SCHEDULED")
    hearing["status"] = "VACATED"
    touch(hearing)
    bump_estate(est)
    return success(hearing)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
