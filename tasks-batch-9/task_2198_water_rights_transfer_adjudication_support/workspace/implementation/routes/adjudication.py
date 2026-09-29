"""Basin adjudication: decree dockets and the claims filed into them."""
from flask import Blueprint

import calc
import clock
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("adjudication", __name__)

PHASES = (
    "OPEN_FOR_CLAIMS",
    "EXAMINATION",
    "OBJECTION_PERIOD",
    "DECREE_ENTERED",
    "CLOSED",
)
TARGET_PHASES = ("EXAMINATION", "OBJECTION_PERIOD", "DECREE_ENTERED", "CLOSED")
PHASE_CHAIN = {
    "OPEN_FOR_CLAIMS": "EXAMINATION",
    "EXAMINATION": "OBJECTION_PERIOD",
    "OBJECTION_PERIOD": "DECREE_ENTERED",
    "DECREE_ENTERED": "CLOSED",
}
FILING_STATUSES = ("FILED", "EXAMINED", "OBJECTED", "DECREED")
VERIFICATION_STATUSES = ("UNVERIFIED", "FIELD_VERIFIED", "DISPUTED")
VERIFICATION_OUTCOMES = ("FIELD_VERIFIED", "DISPUTED")
ZERO2 = calc.D("0.00")


# ---------------------------------------------------------------------------
# Decree dockets
# ---------------------------------------------------------------------------

@bp.route("/decree-dockets", methods=["POST"])
def create_docket():
    middleware.authenticate((middleware.ROLE_ADJUDICATOR,))

    body = validate.get_body()
    basin_code = validate.req_str(body, "basin_code", 1, 24)
    docket_number = validate.req_str(body, "docket_number", 1, 40)
    deadline_raw, _deadline = validate.req_date(body, "claim_filing_deadline")

    for existing in db.decree_dockets.values():
        if existing["docket_number"] == docket_number:
            raise ApiError(
                "ERR_DUPLICATE_DOCKET_NUMBER",
                "A decree docket numbered '%s' already exists." % docket_number,
            )

    row = db.base_row()
    row.update({
        "basin_code": basin_code,
        "docket_number": docket_number,
        "claim_filing_deadline": deadline_raw,
        "phase": "OPEN_FOR_CLAIMS",
        "claim_count": 0,
        "decreed_claim_count": 0,
        "total_decreed_af": ZERO2,
    })
    db.decree_dockets[row["id"]] = row
    return response.object_response(serialize.decree_docket(row), 201)


@bp.route("/decree-dockets/<did>", methods=["GET"])
def get_docket(did):
    middleware.authenticate(middleware.ALL_ROLES)
    docket = common.get_docket(did)
    return response.object_response(serialize.decree_docket(docket))


@bp.route("/decree-dockets/<did>/advance-phase", methods=["POST"])
def advance_phase(did):
    middleware.authenticate((middleware.ROLE_ADJUDICATOR,))
    docket = common.get_docket(did)

    body = validate.get_body()
    target = validate.req_enum(body, "target_phase", TARGET_PHASES)

    current = docket["phase"]
    if PHASE_CHAIN.get(current) != target:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A docket in phase %s cannot advance to %s." % (current, target),
        )

    if target == "EXAMINATION":
        deadline = clock.parse_date(docket["claim_filing_deadline"])
        if clock.now() < deadline:
            raise ApiError(
                "ERR_WINDOW_STILL_OPEN",
                "Claim filing remains open until %s."
                % docket["claim_filing_deadline"],
            )

    claims = derive.claims_for_docket(docket["id"])
    if target == "EXAMINATION":
        if len(claims) < 1:
            raise ApiError(
                "ERR_DOCKET_CHILDREN_NOT_READY",
                "At least one claim must be on file before examination.",
            )
    elif target == "OBJECTION_PERIOD":
        if any(c["filing_status"] == "FILED" for c in claims):
            raise ApiError(
                "ERR_DOCKET_CHILDREN_NOT_READY",
                "Every claim must be examined before the objection period opens.",
            )
    elif target == "DECREE_ENTERED":
        if any(c["filing_status"] != "DECREED" for c in claims):
            raise ApiError(
                "ERR_DOCKET_CHILDREN_NOT_READY",
                "Every claim must be DECREED before the decree is entered.",
            )

    docket["phase"] = target
    derive.recompute_docket(docket)
    db.touch(docket)
    return response.object_response(serialize.decree_docket(docket))


# ---------------------------------------------------------------------------
# Adjudication claims
# ---------------------------------------------------------------------------

def _require_phase(docket, phase):
    if docket["phase"] != phase:
        raise ApiError(
            "ERR_DOCKET_PHASE_INVALID",
            "The docket is in phase %s; %s is required." % (docket["phase"], phase),
        )


def _refresh_docket(docket):
    derive.recompute_docket(docket)
    db.touch(docket)


@bp.route("/adjudication-claims", methods=["POST"])
def create_claim():
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR)
    )

    body = validate.get_body()
    common.owner_precheck(
        caller, body, "water_right_id", db.water_rights, common.right_owner
    )

    docket_id = validate.req_str(body, "decree_docket_id")
    right_id = validate.req_str(body, "water_right_id")
    priority_raw, priority_dt = validate.req_date(body, "claimed_priority_date")
    claimed_af = validate.req_decimal(body, "claimed_af", gt=0)

    docket = common.get_docket(docket_id)
    right = common.get_right(right_id)

    for existing in derive.claims_for_docket(docket["id"]):
        if existing["water_right_id"] == right["id"]:
            raise ApiError(
                "ERR_DUPLICATE_CLAIM",
                "This water right already has a claim on the docket.",
            )

    _require_phase(docket, "OPEN_FOR_CLAIMS")

    deadline = clock.parse_date(docket["claim_filing_deadline"])
    if clock.now() >= deadline:
        raise ApiError(
            "ERR_CLAIM_FILING_CLOSED",
            "The claim filing window closed on %s." % docket["claim_filing_deadline"],
        )

    row = db.base_row()
    row.update({
        "decree_docket_id": docket["id"],
        "water_right_id": right["id"],
        "claimed_priority_date": priority_raw,
        "claimed_af": calc.q2(claimed_af),
        "filing_status": "FILED",
        "verification_status": "UNVERIFIED",
        "examiner_recommended_af": None,
        "decreed_af": None,
        "objection_count": 0,
        "priority_rank": None,
    })
    db.adjudication_claims[row["id"]] = row
    _refresh_docket(docket)
    return response.object_response(serialize.adjudication_claim(row), 201)


@bp.route("/adjudication-claims", methods=["GET"])
def list_claims():
    middleware.authenticate(middleware.ALL_ROLES)
    limit, offset = validate.pagination()
    docket_id = validate.query_str("decree_docket_id")
    right_id = validate.query_str("water_right_id")
    filing_status = validate.query_enum("filing_status", FILING_STATUSES)
    verification_status = validate.query_enum(
        "verification_status", VERIFICATION_STATUSES
    )

    rows = []
    for row in db.adjudication_claims.values():
        if docket_id is not None and row["decree_docket_id"] != docket_id:
            continue
        if right_id is not None and row["water_right_id"] != right_id:
            continue
        if filing_status is not None and row["filing_status"] != filing_status:
            continue
        if (
            verification_status is not None
            and row["verification_status"] != verification_status
        ):
            continue
        rows.append(row)
    rows = common.sort_by(rows, lambda r: r["claimed_priority_date"])
    return common.emit(rows, serialize.adjudication_claim, limit, offset)


@bp.route("/adjudication-claims/<cid>", methods=["GET"])
def get_claim(cid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    claim = common.get_claim(cid)
    middleware.require_owner(caller, common.claim_owner(claim))
    return response.object_response(serialize.adjudication_claim(claim))


@bp.route("/adjudication-claims/<cid>/examine", methods=["POST"])
def examine_claim(cid):
    middleware.authenticate((middleware.ROLE_ADJUDICATOR,))
    claim = common.get_claim(cid)

    body = validate.get_body()
    recommended = validate.req_decimal(body, "examiner_recommended_af", gt=0)
    validate.req_str(body, "examination_note", min_len=1, max_len=500)

    if claim["filing_status"] != "FILED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a FILED claim may be examined (filing_status is %s)."
            % claim["filing_status"],
        )

    docket = db.decree_dockets.get(claim["decree_docket_id"])
    if docket is not None:
        _require_phase(docket, "EXAMINATION")

    recommended = calc.q2(recommended)
    if recommended > calc.q2(claim["claimed_af"]):
        raise ApiError(
            "ERR_RECOMMENDATION_EXCEEDS_CLAIM",
            "examiner_recommended_af %s exceeds claimed_af %s."
            % (recommended, claim["claimed_af"]),
        )

    claim["examiner_recommended_af"] = recommended
    claim["filing_status"] = "EXAMINED"
    db.touch(claim)
    return response.object_response(serialize.adjudication_claim(claim))


@bp.route("/adjudication-claims/<cid>/verify", methods=["POST"])
def verify_claim(cid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    claim = common.get_claim(cid)

    body = validate.get_body()
    outcome = validate.req_enum(body, "verification_outcome", VERIFICATION_OUTCOMES)
    validate.req_str(body, "field_note", min_len=1, max_len=500)

    current = claim["verification_status"]
    allowed = (
        (current == "UNVERIFIED" and outcome in ("FIELD_VERIFIED", "DISPUTED"))
        or (current == "DISPUTED" and outcome == "FIELD_VERIFIED")
    )
    if not allowed:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A claim in verification_status %s cannot move to %s."
            % (current, outcome),
        )

    if outcome == "FIELD_VERIFIED":
        records = derive.use_records_for_right(claim["water_right_id"])
        if not any(
            r["verification_source"] in calc.ADMISSIBLE_SOURCES for r in records
        ):
            raise ApiError(
                "ERR_NO_VERIFIED_USE_EVIDENCE",
                "The claim's water right has no metered or imagery-backed use "
                "evidence.",
            )

    claim["verification_status"] = outcome
    db.touch(claim)
    return response.object_response(serialize.adjudication_claim(claim))


@bp.route("/adjudication-claims/<cid>/object", methods=["POST"])
def object_claim(cid):
    caller = middleware.authenticate(
        (middleware.ROLE_CLAIMANT, middleware.ROLE_ADJUDICATOR)
    )
    claim = common.get_claim(cid)

    body = validate.get_body()
    validate.req_str(body, "objection_basis", min_len=1, max_len=240)
    validate.req_str(body, "objection_note", min_len=1, max_len=240)

    if claim["filing_status"] not in ("EXAMINED", "OBJECTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A claim in filing_status %s cannot be objected to."
            % claim["filing_status"],
        )

    docket = db.decree_dockets.get(claim["decree_docket_id"])
    if docket is not None:
        _require_phase(docket, "OBJECTION_PERIOD")

    owner_id = common.claim_owner(claim)
    if owner_id is not None and caller.user_id == owner_id:
        raise ApiError(
            "ERR_SELF_OBJECTION_FORBIDDEN",
            "A claimant may not object to its own claim.",
        )

    claim["filing_status"] = "OBJECTED"
    claim["objection_count"] = claim["objection_count"] + 1
    db.touch(claim)
    return response.object_response(serialize.adjudication_claim(claim))


@bp.route("/adjudication-claims/<cid>/decree", methods=["POST"])
def decree_claim(cid):
    middleware.authenticate((middleware.ROLE_ADJUDICATOR,))
    claim = common.get_claim(cid)

    body = validate.get_body()
    validate.req_str(body, "decree_note", min_len=1, max_len=500)

    if claim["filing_status"] not in ("EXAMINED", "OBJECTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A claim in filing_status %s cannot be decreed."
            % claim["filing_status"],
        )

    docket = db.decree_dockets.get(claim["decree_docket_id"])
    if docket is not None:
        _require_phase(docket, "OBJECTION_PERIOD")

    if claim["verification_status"] != "FIELD_VERIFIED":
        raise ApiError(
            "ERR_CLAIM_NOT_VERIFIED",
            "The claim must be FIELD_VERIFIED before it can be decreed.",
        )

    right = db.water_rights.get(claim["water_right_id"])
    right_priority = (
        clock.parse_date(right["priority_date"]) if right is not None else None
    )
    claim["decreed_af"] = calc.decreed_volume(
        claim["claimed_af"],
        claim["examiner_recommended_af"],
        claim["objection_count"],
        clock.parse_date(claim["claimed_priority_date"]),
        right_priority,
    )
    claim["filing_status"] = "DECREED"
    db.touch(claim)

    if docket is not None:
        previous = {
            c["id"]: c["priority_rank"] for c in derive.claims_for_docket(docket["id"])
        }
        derive.reassign_priority_ranks(docket["id"])
        for other in derive.claims_for_docket(docket["id"]):
            if other["id"] == claim["id"]:
                continue
            if previous.get(other["id"]) != other["priority_rank"]:
                db.touch(other)
        derive.recompute_docket(docket)
        if (
            docket["phase"] == "OBJECTION_PERIOD"
            and docket["claim_count"] > 0
            and docket["decreed_claim_count"] == docket["claim_count"]
        ):
            docket["phase"] = "DECREE_ENTERED"
        db.touch(docket)
    return response.object_response(serialize.adjudication_claim(claim))
