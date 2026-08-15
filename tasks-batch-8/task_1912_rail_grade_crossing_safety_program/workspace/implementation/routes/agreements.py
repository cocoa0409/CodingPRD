"""Closure / consolidation negotiation endpoints (PRD §3.5)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_COUNTER_TURN,
    ERR_CROSSING_NOT_ACTIVE,
    ERR_CROSSING_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INCENTIVE_CAP_EXCEEDED,
    ERR_INCENTIVE_REGRESSION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LOCALITY_MISMATCH,
    ERR_LOCALITY_NOT_FOUND,
    ERR_NEGOTIATION_ROUND_LIMIT,
    ERR_SELF_ACCEPT_FORBIDDEN,
    ERR_SELF_CONSOLIDATION,
)
from helpers import (
    body_or_empty,
    get_or_404,
    paginate,
    query_filter,
    reject_unknown,
    req_enum,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import calcs

bp = Blueprint("closure_agreements", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

CLOSURE_TYPES = ("CLOSURE", "CONSOLIDATION")
AGREEMENT_STATUSES = (
    "DRAFT",
    "PROPOSED",
    "COUNTERED",
    "DOT_ACCEPTED",
    "LOCALITY_RATIFIED",
    "EXECUTED",
    "REJECTED",
    "WITHDRAWN",
)

CREATE_FIELDS = ("crossing_id", "locality_id", "closure_type", "consolidation_target_crossing_id")


def serialize_agreement(a):
    return {
        "id": a["id"],
        "crossing_id": a["crossing_id"],
        "locality_id": a["locality_id"],
        "closure_type": a["closure_type"],
        "consolidation_target_crossing_id": a["consolidation_target_crossing_id"],
        "computed_incentive_cents": a["computed_incentive_cents"],
        "current_offer_cents": a["current_offer_cents"],
        "negotiation_round": a["negotiation_round"],
        "created_by_party": a["created_by_party"],
        "created_by_user_id": a["created_by_user_id"],
        "last_offer_by_party": a["last_offer_by_party"],
        "last_offer_by_user_id": a["last_offer_by_user_id"],
        "dot_accepted_by_user_id": a["dot_accepted_by_user_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _party_of(role):
    return "DOT" if role == "RailSafetyOfficer" else "LOCALITY"


def _check_creator_party(agreement, role, user_id):
    """Propose/withdraw: the acting side must be the side that created the
    agreement (DOT -> RailSafetyOfficer; LOCALITY -> owning LocalAuthority)."""
    if agreement["created_by_party"] == "DOT":
        if role != "RailSafetyOfficer":
            raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                           "Only a RailSafetyOfficer may perform this action on a DOT-created agreement")
    else:
        if role != "LocalAuthority" or user_id != agreement["locality_id"]:
            raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                           "Only the owning LocalAuthority may perform this action on a locality-created agreement")


@bp.post("/closure-agreements")
def create_agreement():
    user_id, role = auth(["RailSafetyOfficer", "LocalAuthority"])
    body = body_or_empty()

    # Priority 2: a LocalAuthority may only open a negotiation for itself.
    if role == "LocalAuthority" and body.get("locality_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "A LocalAuthority may only create agreements for its own locality")

    # Priority 3: body FKs left-to-right.
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    locality_id = body.get("locality_id")
    if isinstance(locality_id, str) and locality_id and locality_id not in store.localities:
        raise ApiError(ERR_LOCALITY_NOT_FOUND, 404, f"Locality {locality_id} does not exist")
    target_id = body.get("consolidation_target_crossing_id")
    if isinstance(target_id, str) and target_id and target_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {target_id} does not exist")

    # Priority 4: the crossing under closure (and any consolidation target)
    # must be ACTIVE.
    crossing = store.crossings.get(crossing_id) if isinstance(crossing_id, str) else None
    if crossing is not None and crossing["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Crossing {crossing_id} is not ACTIVE (current: {crossing['status']})")
    target = store.crossings.get(target_id) if isinstance(target_id, str) and target_id else None
    if body.get("closure_type") == "CONSOLIDATION" and target is not None and target["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Consolidation target crossing {target_id} is not ACTIVE")

    # Priority 7: request shape and business constraints.
    reject_unknown(body, CREATE_FIELDS)
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    locality_id = req_str(body, "locality_id")
    if locality_id not in store.localities:
        raise ApiError(ERR_LOCALITY_NOT_FOUND, 404, f"Locality {locality_id} does not exist")
    closure_type = req_enum(body, "closure_type", CLOSURE_TYPES)
    if target_id is not None and not isinstance(target_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'consolidation_target_crossing_id' must be a string")
    if closure_type == "CONSOLIDATION" and not target_id:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "consolidation_target_crossing_id is required for CONSOLIDATION")
    if closure_type == "CLOSURE" and target_id:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "consolidation_target_crossing_id must be absent for CLOSURE")
    if closure_type == "CONSOLIDATION" and target_id == crossing_id:
        raise ApiError(ERR_SELF_CONSOLIDATION, 422,
                       "consolidation_target_crossing_id must differ from crossing_id")

    crossing = store.crossings[crossing_id]
    computed = calcs.closure_incentive(closure_type, crossing["exposure_index"])
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "locality_id": locality_id,
        "closure_type": closure_type,
        "consolidation_target_crossing_id": target_id if closure_type == "CONSOLIDATION" else None,
        "computed_incentive_cents": computed,
        "current_offer_cents": computed,
        "negotiation_round": 0,
        "created_by_party": _party_of(role),
        "created_by_user_id": user_id,
        "last_offer_by_party": None,
        "last_offer_by_user_id": None,
        "dot_accepted_by_user_id": None,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.agreements[rec["id"]] = rec
    return ok(serialize_agreement(rec), 201)


@bp.get("/closure-agreements")
def list_agreements():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    locality_f = query_filter("locality_id")
    target_f = query_filter("consolidation_target_crossing_id")
    status_f = query_filter("status")
    items = []
    for a in store.agreements.values():
        if crossing_f is not None and a["crossing_id"] != crossing_f:
            continue
        if locality_f is not None and a["locality_id"] != locality_f:
            continue
        if target_f is not None and a["consolidation_target_crossing_id"] != target_f:
            continue
        if status_f is not None and a["status"] != status_f:
            continue
        items.append(a)
    items = sorted(items, key=lambda a: a["created_at"])
    page, meta = paginate([serialize_agreement(a) for a in items])
    return ok_list(page, meta)


@bp.get("/closure-agreements/<agreement_id>")
def get_agreement(agreement_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.agreements, agreement_id, ERR_AGREEMENT_NOT_FOUND,
                     f"Closure agreement {agreement_id} does not exist")
    return ok(serialize_agreement(rec))


@bp.post("/closure-agreements/<agreement_id>/transition")
def transition_agreement(agreement_id):
    user_id, role = auth(["ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority"])
    body = body_or_empty()
    to_status = body.get("to_status")

    # Fixed per-target role admission (priority 2) where it is not party-dependent.
    if to_status == "DOT_ACCEPTED" and role != "RailSafetyOfficer":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Only a RailSafetyOfficer may accept for the DOT")
    if to_status in ("LOCALITY_RATIFIED", "REJECTED") and role != "LocalAuthority":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Only a LocalAuthority may perform this action")
    if to_status == "EXECUTED" and role != "ProgramAdministrator":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Only a ProgramAdministrator may execute an agreement")

    rec = get_or_404(store.agreements, agreement_id, ERR_AGREEMENT_NOT_FOUND,
                     f"Closure agreement {agreement_id} does not exist")
    reject_unknown(body, ("to_status",))
    if not isinstance(to_status, str) or to_status not in AGREEMENT_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(AGREEMENT_STATUSES)}")

    if to_status == "PROPOSED":
        _check_creator_party(rec, role, user_id)
        if rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot propose from {rec['status']}")
        rec["status"] = "PROPOSED"
        rec["negotiation_round"] = 1
        rec["current_offer_cents"] = rec["computed_incentive_cents"]
        rec["last_offer_by_party"] = rec["created_by_party"]
        rec["last_offer_by_user_id"] = user_id
    elif to_status == "DOT_ACCEPTED":
        if rec["status"] not in ("PROPOSED", "COUNTERED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to DOT_ACCEPTED from {rec['status']}")
        # Segregation of duties: the officer who tabled the current DOT offer
        # may not be the one who accepts it.
        if rec["last_offer_by_party"] == "DOT" and user_id == rec["last_offer_by_user_id"]:
            raise ApiError(ERR_SELF_ACCEPT_FORBIDDEN, 403,
                           "The officer who tabled the current DOT offer may not accept it")
        rec["status"] = "DOT_ACCEPTED"
        rec["dot_accepted_by_user_id"] = user_id
    elif to_status == "LOCALITY_RATIFIED":
        if rec["status"] != "DOT_ACCEPTED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to LOCALITY_RATIFIED from {rec['status']}")
        if user_id != rec["locality_id"]:
            raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                           "Only the agreement's locality may ratify it")
        rec["status"] = "LOCALITY_RATIFIED"
    elif to_status == "EXECUTED":
        if rec["status"] != "LOCALITY_RATIFIED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot execute from {rec['status']}")
        rec["status"] = "EXECUTED"
        crossing = store.crossings.get(rec["crossing_id"])
        if crossing is not None and crossing["status"] == "ACTIVE":
            crossing["status"] = "CLOSURE_PENDING"
            crossing["version"] += 1
            crossing["updated_at"] = now_iso()
    elif to_status == "REJECTED":
        if rec["status"] not in ("PROPOSED", "COUNTERED", "DOT_ACCEPTED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot reject from {rec['status']}")
        if user_id != rec["locality_id"]:
            raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                           "Only the agreement's locality may reject it")
        rec["status"] = "REJECTED"
    elif to_status == "WITHDRAWN":
        _check_creator_party(rec, role, user_id)
        if rec["status"] not in ("DRAFT", "PROPOSED", "COUNTERED", "DOT_ACCEPTED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot withdraw from {rec['status']}")
        rec["status"] = "WITHDRAWN"
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_agreement(rec))


@bp.post("/closure-agreements/<agreement_id>/counter")
def counter_agreement(agreement_id):
    user_id, role = auth(["RailSafetyOfficer", "LocalAuthority"])
    rec = get_or_404(store.agreements, agreement_id, ERR_AGREEMENT_NOT_FOUND,
                     f"Closure agreement {agreement_id} does not exist")
    body = body_or_empty()

    # Priority 4: the negotiation must be live.
    if rec["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot counter from {rec['status']}")

    # Priority 7: turn alternation and locality ownership, then the round cap.
    actor_party = _party_of(role)
    if actor_party == rec["last_offer_by_party"]:
        raise ApiError(ERR_COUNTER_TURN, 403,
                       "The party that tabled the current offer may not counter it")
    if role == "LocalAuthority" and user_id != rec["locality_id"]:
        raise ApiError(ERR_LOCALITY_MISMATCH, 403,
                       "Only the agreement's locality may counter for the locality")
    if rec["negotiation_round"] >= calcs.MAX_NEGOTIATION_ROUNDS:
        raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT, 409,
                       f"The negotiation round cap of {calcs.MAX_NEGOTIATION_ROUNDS} has been reached")

    reject_unknown(body, ("proposed_incentive_cents",))
    proposed = body.get("proposed_incentive_cents")
    if not isinstance(proposed, int) or isinstance(proposed, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'proposed_incentive_cents' is required and must be an integer")

    # Priority 10: counter direction and cap rules.
    if actor_party == "LOCALITY":
        if proposed <= rec["current_offer_cents"]:
            raise ApiError(ERR_INCENTIVE_REGRESSION, 422,
                           "A locality counter must raise the current offer")
        if proposed > calcs.MAX_INCENTIVE_CAP_CENTS:
            raise ApiError(ERR_INCENTIVE_CAP_EXCEEDED, 422,
                           f"A locality counter may not exceed {calcs.MAX_INCENTIVE_CAP_CENTS} cents")
    else:
        if proposed >= rec["current_offer_cents"]:
            raise ApiError(ERR_INCENTIVE_REGRESSION, 422,
                           "A DOT counter must lower the current offer")
        if proposed < rec["computed_incentive_cents"]:
            raise ApiError(ERR_INCENTIVE_REGRESSION, 422,
                           "A DOT counter may not go below the computed minimum incentive")

    rec["current_offer_cents"] = proposed
    rec["negotiation_round"] += 1
    rec["last_offer_by_party"] = actor_party
    rec["last_offer_by_user_id"] = user_id
    rec["status"] = "COUNTERED" if rec["status"] == "PROPOSED" else "PROPOSED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_agreement(rec))
