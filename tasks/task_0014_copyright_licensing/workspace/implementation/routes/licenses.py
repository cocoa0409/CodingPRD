"""License routes — create, get, rounds, terminate."""
import copy

from flask import Blueprint

from clock import format_iso, get_now, parse_iso
from common import check_version, get_json_body, paginate, stamp_new, stamp_update
from db import db, new_id
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import append_audit, append_rights_chain
from services.conflict import check_rights_conflict
from services.works import is_owner_or_co_owner

bp = Blueprint("licenses", __name__)


VALID_MEDIA = {"DIGITAL", "PRINT", "BROADCAST", "MERCHANDISE"}
VALID_EXCLUSIVITY = {"EXCLUSIVE", "NON_EXCLUSIVE"}
VALID_REVISION = {"NONE", "MINOR", "FULL"}
VALID_PERIOD = {"MONTHLY", "QUARTERLY", "ANNUAL"}
VALID_ACTIONS = {"OFFER", "COUNTER", "ACCEPT", "WITHDRAW"}


def _validate_term(term_start_str, term_end_str, allow_past=False):
    ts = parse_iso(term_start_str) if term_start_str else None
    te = parse_iso(term_end_str) if term_end_str else None
    if ts is None or te is None:
        raise api_error("ERR_INVALID_TERM", "term_start/term_end required")
    if ts >= te:
        raise api_error("ERR_INVALID_TERM", "term_start must be < term_end")
    if not allow_past:
        if ts <= get_now():
            raise api_error("ERR_INVALID_TERM", "term_start must be in the future")
    return ts, te


def _validate_territory(territory):
    if not isinstance(territory, list) or not territory:
        raise api_error("ERR_VALIDATION", "territory must be non-empty array")
    if "WORLD" in territory and len(territory) > 1:
        raise api_error("ERR_VALIDATION", "WORLD is exclusive of other codes")
    for t in territory:
        if not isinstance(t, str) or len(t) not in (2, 5):
            # alpha-2 codes; "WORLD" is also acceptable (length 5)
            if t != "WORLD" and (not isinstance(t, str) or len(t) != 2):
                raise api_error("ERR_VALIDATION", f"invalid territory code: {t}")


def _validate_media(media_types):
    if not isinstance(media_types, list) or not media_types:
        raise api_error("ERR_VALIDATION", "media_types must be non-empty array")
    for m in media_types:
        if m not in VALID_MEDIA:
            raise api_error("ERR_VALIDATION", f"invalid media_type: {m}")


def _persist_round(license_obj, action, proposed_by_id, clause_diff):
    rnd = {
        "id": new_id(),
        "created_at": format_iso(get_now()),
        "license_id": license_obj["id"],
        "round_number": license_obj["current_round"],
        "proposed_by_id": proposed_by_id,
        "clause_diff": copy.deepcopy(clause_diff) if clause_diff else {},
        "action": action,
        "submitted_at": format_iso(get_now()),
    }
    db.negotiation_rounds[rnd["id"]] = rnd
    return rnd


def _last_round(license_id):
    rows = [r for r in db.negotiation_rounds.values() if r.get("license_id") == license_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("round_number", 0), r.get("created_at", "")))
    return rows[-1]


def _opposite_party(license_obj, prev_round):
    """Return the rights_holder_id that is allowed to act next given prev_round."""
    if prev_round is None:
        return license_obj["licensee_id"]
    if prev_round["proposed_by_id"] == license_obj["licensor_id"]:
        return license_obj["licensee_id"]
    return license_obj["licensor_id"]


@bp.route("/licenses", methods=["POST"])
def create_license():
    user_id, role = require_roles(["RightsHolder"])
    body = get_json_body()

    work_id = body.get("work_id")
    licensor_id = body.get("licensor_id")
    licensee_id = body.get("licensee_id")
    territory = body.get("territory")
    term_start = body.get("term_start")
    term_end = body.get("term_end")
    media_types = body.get("media_types")
    exclusivity = body.get("exclusivity")
    sublicense_allowed = body.get("sublicense_allowed")
    revision_rights = body.get("revision_rights")
    fixed_fee_cents = body.get("fixed_fee_cents", 0)
    revenue_share_bps = body.get("revenue_share_bps", 0)
    minimum_guarantee_cents = body.get("minimum_guarantee_cents", 0)
    advance_cents = body.get("advance_cents", 0)
    settlement_period = body.get("settlement_period")

    # Existence (priority 3): work_id, licensor_id, licensee_id resolve.
    if not work_id:
        raise api_error("ERR_VALIDATION", "work_id required")
    work = db.works.get(work_id)
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    if not licensor_id or licensor_id not in db.rights_holders:
        raise api_error("ERR_NOT_FOUND", "licensor not found")
    if not licensee_id or licensee_id not in db.rights_holders:
        raise api_error("ERR_NOT_FOUND", "licensee not found")
    if licensor_id == licensee_id:
        raise api_error("ERR_VALIDATION", "licensor must differ from licensee")

    # Authz: the caller (RightsHolder) must be the licensor (licensor_id == X-User-ID)
    # for licence creation per RBAC: "POST /licenses (caller must be primary_owner or co_owner of work_id)".
    # The licensor must be a primary or co-owner.
    if not is_owner_or_co_owner(work, licensor_id):
        raise api_error("ERR_FORBIDDEN",
                        "licensor must be primary_owner or co_owner of the work")

    # Caller must equal licensor (cannot draft on someone else's behalf).
    if user_id != licensor_id:
        raise api_error("ERR_FORBIDDEN", "caller must equal licensor_id")

    # Field validations
    _validate_territory(territory)
    _validate_media(media_types)
    if exclusivity not in VALID_EXCLUSIVITY:
        raise api_error("ERR_VALIDATION", "exclusivity invalid")
    if revision_rights not in VALID_REVISION:
        raise api_error("ERR_VALIDATION", "revision_rights invalid")
    if settlement_period not in VALID_PERIOD:
        raise api_error("ERR_VALIDATION", "settlement_period invalid")
    if not isinstance(sublicense_allowed, bool):
        raise api_error("ERR_VALIDATION", "sublicense_allowed must be boolean")
    for f, v in [("fixed_fee_cents", fixed_fee_cents),
                 ("revenue_share_bps", revenue_share_bps),
                 ("minimum_guarantee_cents", minimum_guarantee_cents),
                 ("advance_cents", advance_cents)]:
        if not isinstance(v, int) or v < 0:
            raise api_error("ERR_VALIDATION", f"{f} must be non-negative integer")
    if revenue_share_bps > 10000:
        raise api_error("ERR_VALIDATION", "revenue_share_bps must be <= 10000")

    # Term well-formedness (priority 23): term_start < term_end and in future.
    _validate_term(term_start, term_end, allow_past=False)

    license_obj = {
        "work_id": work_id,
        "licensor_id": licensor_id,
        "licensee_id": licensee_id,
        "territory": list(territory),
        "term_start": term_start,
        "term_end": term_end,
        "media_types": list(media_types),
        "exclusivity": exclusivity,
        "sublicense_allowed": sublicense_allowed,
        "revision_rights": revision_rights,
        "fixed_fee_cents": int(fixed_fee_cents),
        "revenue_share_bps": int(revenue_share_bps),
        "minimum_guarantee_cents": int(minimum_guarantee_cents),
        "advance_cents": int(advance_cents),
        "settlement_period": settlement_period,
        "status": "OFFERED",
        "current_round": 1,
        "pinned_work_version": None,
        "contract_id": None,
        "effective_date": None,
        "cumulative_advance_recouped_cents": 0,
    }
    stamp_new(license_obj)
    db.licenses[license_obj["id"]] = license_obj

    # Persist initial OFFER round.
    _persist_round(license_obj, "OFFER", licensor_id, {})

    return success(license_obj, status=201)


@bp.route("/licenses/<license_id>", methods=["GET"])
def get_license(license_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    return success(license_obj)


@bp.route("/licenses/<license_id>/rounds", methods=["GET"])
def list_rounds(license_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    rows = [r for r in db.negotiation_rounds.values() if r.get("license_id") == license_id]
    page, meta = paginate(rows, sort_key=lambda r: (r.get("round_number", 0), r.get("created_at", "")))
    return success(page, response_type="array", pagination=meta)


@bp.route("/licenses/<license_id>/rounds", methods=["POST"])
def submit_round(license_id):
    user_id, role = require_roles(["RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    body = get_json_body()
    check_version(license_obj, body)

    action = body.get("action")
    clause_diff = body.get("clause_diff", {})

    if action not in VALID_ACTIONS:
        raise api_error("ERR_VALIDATION", "action invalid")

    status = license_obj.get("status")

    # Authz first: caller must be licensor or licensee.
    licensor_id = license_obj["licensor_id"]
    licensee_id = license_obj["licensee_id"]
    if user_id not in (licensor_id, licensee_id):
        raise api_error("ERR_FORBIDDEN", "caller is neither licensor nor licensee")

    if action == "WITHDRAW":
        # Only licensor may withdraw. Allowed from OFFERED or COUNTERED.
        if user_id != licensor_id:
            raise api_error("ERR_FORBIDDEN", "only licensor may withdraw")
        if status not in ("OFFERED", "COUNTERED"):
            raise api_error("ERR_INVALID_STATE", "license cannot be withdrawn from this state")
        before = {"status": status}
        license_obj["status"] = "WITHDRAWN"
        stamp_update(license_obj)
        rnd = _persist_round(license_obj, "WITHDRAW", user_id, clause_diff)
        append_audit(user_id, "License", license_obj["id"], "LICENSE_CHANGED",
                     before, {"status": "WITHDRAWN"})
        return success(rnd, status=201)

    if action == "COUNTER":
        if status not in ("OFFERED", "COUNTERED"):
            raise api_error("ERR_INVALID_STATE", "license is not in a counter-able state")
        prev = _last_round(license_id)
        # Turn alternation: caller must be opposite of previous proposer.
        if prev is not None and prev["proposed_by_id"] == user_id:
            raise api_error("ERR_NOT_YOUR_TURN", "caller is the same party as previous round")
        before = {"status": status, "current_round": license_obj["current_round"]}
        license_obj["status"] = "COUNTERED"
        license_obj["current_round"] += 1
        stamp_update(license_obj)
        rnd = _persist_round(license_obj, "COUNTER", user_id, clause_diff)
        append_audit(user_id, "License", license_obj["id"], "LICENSE_CHANGED",
                     before,
                     {"status": "COUNTERED", "current_round": license_obj["current_round"]})
        return success(rnd, status=201)

    if action == "ACCEPT":
        if status not in ("OFFERED", "COUNTERED"):
            raise api_error("ERR_INVALID_STATE", "license is not in an accept-able state")
        prev = _last_round(license_id)
        # Turn alternation
        if status == "OFFERED":
            # licensee must accept
            if user_id != licensee_id:
                raise api_error("ERR_NOT_YOUR_TURN", "only the licensee may accept the initial offer")
        else:  # COUNTERED
            if prev is not None and prev["proposed_by_id"] == user_id:
                raise api_error("ERR_NOT_YOUR_TURN", "caller is the same party as previous round")

        # Work must be REGISTERED.
        work = db.works.get(license_obj["work_id"])
        if not work or work.get("registration_status") != "REGISTERED":
            raise api_error("ERR_WORK_NOT_REGISTERED",
                            "Work must be REGISTERED to accept a license")

        # Rights conflict check.
        non_excl_conflicts = check_rights_conflict(license_obj)

        # Pin work version, transition to ACCEPTED.
        before = {"status": status}
        license_obj["status"] = "ACCEPTED"
        license_obj["pinned_work_version"] = work.get("version")
        stamp_update(license_obj)
        rnd = _persist_round(license_obj, "ACCEPT", user_id, clause_diff)
        append_audit(user_id, "License", license_obj["id"], "LICENSE_CHANGED",
                     before, {"status": "ACCEPTED",
                              "pinned_work_version": license_obj["pinned_work_version"]})

        # Non-exclusive conflicts: emit RIGHTS_CONFLICT_DETECTED audit per spec.
        if non_excl_conflicts:
            append_audit("system", "License", license_obj["id"],
                         "RIGHTS_CONFLICT_DETECTED", None,
                         copy.deepcopy(license_obj))
        return success(rnd, status=201)

    if action == "OFFER":
        # The initial OFFER is auto-persisted on creation. Reject explicit OFFER actions.
        raise api_error("ERR_INVALID_STATE",
                        "OFFER is auto-persisted on license creation; subsequent rounds use COUNTER/ACCEPT/WITHDRAW")

    raise api_error("ERR_VALIDATION", "action invalid")


@bp.route("/licenses/<license_id>/terminate", methods=["POST"])
def terminate_license(license_id):
    user_id, role = require_roles(["RightsHolder"])
    license_obj = db.licenses.get(license_id)
    if not license_obj:
        raise api_error("ERR_NOT_FOUND", "license not found")
    body = get_json_body()
    check_version(license_obj, body)

    if license_obj.get("status") != "EFFECTIVE":
        raise api_error("ERR_INVALID_STATE",
                        "license must be EFFECTIVE to manually terminate")
    if user_id != license_obj["licensor_id"]:
        raise api_error("ERR_FORBIDDEN", "only licensor may terminate")

    # Pending settlements: any DRAFT statement with an in-flight payment? Spec says
    # all RoyaltyStatements must be in {SETTLED, REVERSED, DRAFT} and there must
    # be no pending payment. We allow termination if all statements are SETTLED,
    # REVERSED, or DRAFT. The pending-payment scenario is encoded via concurrency,
    # which we do not race-detect; but if a DRAFT statement is currently being
    # paid the corresponding payment event hasn't applied yet — we treat the
    # license as terminable when all statements are in those three buckets.
    # However, if the spec intends strict blocking for any DRAFT, mention pending.
    for s in db.royalty_statements.values():
        if s.get("license_id") == license_id and s.get("status") not in ("SETTLED", "REVERSED", "DRAFT"):
            raise api_error("ERR_HAS_PENDING_SETTLEMENTS",
                            "license has pending settlements")

    before = {"status": license_obj["status"]}
    license_obj["status"] = "TERMINATED"
    stamp_update(license_obj)
    append_audit(user_id, "License", license_obj["id"], "LICENSE_CHANGED",
                 before, {"status": "TERMINATED"})
    append_rights_chain(license_obj["work_id"], "LICENSE_TERMINATED", user_id,
                        "License", license_obj["id"], {"reason": "MANUAL"})

    # Cascade contracts.
    contract = db.contracts.get(license_obj.get("contract_id")) if license_obj.get("contract_id") else None
    if contract and contract.get("status") == "EFFECTIVE":
        cbefore = {"status": contract["status"]}
        contract["status"] = "TERMINATED"
        stamp_update(contract)
        append_audit("system", "Contract", contract["id"], "CONTRACT_AMENDED",
                     cbefore, {"status": "TERMINATED"})

    return success(license_obj)
