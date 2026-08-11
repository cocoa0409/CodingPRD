"""Routes: DefaultCase, NoteholderDirection, DirectionEndorsement (PRD 3.5)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES, uid, check_noteholder_owns
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_SEGREGATION_OF_DUTIES,
                    ERR_CURE_DEADLINE_PASSED, ERR_DIRECTION_LAPSED,
                    ERR_DUPLICATE_CONSTRAINT, ERR_NO_ELIGIBLE_POSITION,
                    ERR_THRESHOLD_NOT_MET, ERR_STALE_VERSION,
                    ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now, now_iso, mutate, touch
from validate import req_str, opt_str, req_enum, req_datetime, parse_datetime, is_int
from domain import (recompute_active_default_count, cascade_indenture_defaulted,
                    maybe_resume_indenture, cascade_accelerate,
                    cascade_rescind_acceleration, eligible_principal,
                    holder_aggregate_principal, recompute_direction_aggregates,
                    refresh_direction_effectiveness)

bp = Blueprint("defaults", __name__)

CASE_TERMINAL = ("CURED", "WAIVED")


# ---------------------------------------------------------------------------
# DefaultCase
# ---------------------------------------------------------------------------

@bp.route("/default-cases", methods=["POST"])
@require_roles("TrustOfficer")
def create_case():
    body = get_body()
    with LOCK:
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        req_str(body, "indenture_id")
        dtype = req_enum(body, "default_type",
                         ["PAYMENT", "COVENANT_BREACH", "CROSS_DEFAULT",
                          "BANKRUPTCY", "SINKING_FUND_MISS"])
        cure_deadline = req_datetime(body, "cure_deadline")
        source_ref = opt_str(body, "source_ref")
        e = new_entity("default_cases")
        e.update({
            "indenture_id": indenture_id,
            "default_type": dtype,
            "source_ref": source_ref,
            "declared_at": now_iso(),
            "cure_deadline": cure_deadline,
            "status": "ALLEGED",
            "declared_by_user_id": uid(),
            "confirmed_by_user_id": None,
        })
        recompute_active_default_count(ind)
    return ok(public(e), 201)


@bp.route("/default-cases", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cases():
    return list_response(DB["default_cases"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
    })


@bp.route("/default-cases/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_case(cid):
    e = DB["default_cases"].get(cid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "DefaultCase not found")
    return ok(public(e))


@bp.route("/default-cases/<cid>/confirm", methods=["POST"])
@require_roles("TrustManager")
def confirm_case(cid):
    with LOCK:
        case = DB["default_cases"].get(cid)
        if case is None:
            raise_err(ERR_NOT_FOUND, "DefaultCase not found")
        if case["status"] in CASE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "DefaultCase is terminal (%s)" % case["status"])
        if case["status"] != "ALLEGED":
            raise_err(ERR_INVALID_STATE, "Only an ALLEGED case can be confirmed")
        # Rule 6: segregation of duties (confirmer != declarer).
        if uid() == case["declared_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "Confirmer must differ from the declaring officer")
        mutate(case, status="CONFIRMED", confirmed_by_user_id=uid())
        ind = DB["indentures"].get(case["indenture_id"])
        if ind is not None:
            recompute_active_default_count(ind)
            cascade_indenture_defaulted(ind)
    return ok(public(case))


@bp.route("/default-cases/<cid>/cure", methods=["POST"])
@require_roles("TrustManager")
def cure_case(cid):
    with LOCK:
        case = DB["default_cases"].get(cid)
        if case is None:
            raise_err(ERR_NOT_FOUND, "DefaultCase not found")
        if case["status"] in CASE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "DefaultCase is terminal (%s)" % case["status"])
        if case["status"] != "CONFIRMED":
            raise_err(ERR_INVALID_STATE, "Only a CONFIRMED case can be cured")
        # Rule 15: logical clock <= cure_deadline; equality cures.
        deadline = parse_datetime(case["cure_deadline"])
        if deadline is not None and now() > deadline:
            raise_err(ERR_CURE_DEADLINE_PASSED,
                      "The cure deadline has passed")
        mutate(case, status="CURED")
        ind = DB["indentures"].get(case["indenture_id"])
        if ind is not None:
            maybe_resume_indenture(ind)
    return ok(public(case))


# ---------------------------------------------------------------------------
# NoteholderDirection
# ---------------------------------------------------------------------------

@bp.route("/directions", methods=["POST"])
@require_roles("TrustOfficer")
def create_direction():
    body = get_body()
    with LOCK:
        case_id = body.get("default_case_id")
        case = DB["default_cases"].get(case_id) if isinstance(case_id, str) else None
        if case is None:
            raise_err(ERR_NOT_FOUND, "DefaultCase not found")
        # Rule 5: case must be CONFIRMED or ACCELERATED.
        if case["status"] in CASE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "DefaultCase is terminal (%s)" % case["status"])
        if case["status"] not in ("CONFIRMED", "ACCELERATED"):
            raise_err(ERR_INVALID_STATE,
                      "Directions open only on CONFIRMED or ACCELERATED cases")
        # OCC: expected_default_case_version must match the case's version.
        expected = body.get("expected_default_case_version")
        if is_int(expected) and expected != case["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_default_case_version is stale")
        # Shape (rule 26).
        req_str(body, "default_case_id")
        itype = req_enum(body, "instruction_type",
                         ["ACCELERATE", "RESCIND_ACCELERATION", "WAIVE_DEFAULT"])
        expires = req_datetime(body, "expires_at")
        if not is_int(body.get("expected_default_case_version")):
            raise_err(ERR_INVALID_REQUEST,
                      "expected_default_case_version is required")
        # Supersede CIRCULATING siblings on the same case.
        for d in DB["directions"].values():
            if d["default_case_id"] == case["id"] and d["status"] == "CIRCULATING":
                mutate(d, status="SUPERSEDED")
        touch(case)  # creation advances the parent case version
        ind = DB["indentures"].get(case["indenture_id"])
        eligible = eligible_principal(case["indenture_id"])
        if itype == "RESCIND_ACCELERATION":
            rule_text = ("EFFECTIVE when supporting_principal_cents * 2 > "
                         "eligible_principal_cents (> 50% of eligible, strict)")
        else:
            rule_text = ("EFFECTIVE when supporting_principal_cents * 4 >= "
                         "eligible_principal_cents (>= 25% of eligible, inclusive)")
        e = new_entity("directions")
        e.update({
            "default_case_id": case_id,
            "instruction_type": itype,
            "expires_at": expires,
            "eligible_principal_cents": eligible,
            "supporting_principal_cents": 0,
            "threshold_rule": rule_text,
            "status": "CIRCULATING",
        })
    return ok(public(e), 201)


@bp.route("/directions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_directions():
    return list_response(DB["directions"].values(), {
        "default_case_id": request.args.get("default_case_id"),
        "status": request.args.get("status"),
    })


@bp.route("/directions/<did>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_direction(did):
    e = DB["directions"].get(did)
    if e is None:
        raise_err(ERR_NOT_FOUND, "NoteholderDirection not found")
    return ok(public(e))


@bp.route("/directions/<did>/endorsements", methods=["POST"])
@require_roles("Noteholder")
def endorse_direction(did):
    body = get_body()
    with LOCK:
        # Rule 3: Noteholder acts only on its own account.
        account_id = body.get("noteholder_account_id")
        if account_id is not None:
            check_noteholder_owns(account_id)
        # Rule 4: path id, then payload reference.
        direction = DB["directions"].get(did)
        if direction is None:
            raise_err(ERR_NOT_FOUND, "NoteholderDirection not found")
        acc = DB["noteholder_accounts"].get(account_id) if isinstance(account_id, str) else None
        if acc is None:
            raise_err(ERR_NOT_FOUND, "NoteholderAccount not found")
        # Rule 9: at most one ACTIVE endorsement per (direction, account).
        for en in DB["direction_endorsements"].values():
            if (en["direction_id"] == did
                    and en["noteholder_account_id"] == account_id
                    and en["status"] == "ACTIVE"):
                raise_err(ERR_DUPLICATE_CONSTRAINT,
                          "An ACTIVE endorsement already exists for this account")
        # Rule 16: circulation window.
        exp = parse_datetime(direction["expires_at"])
        if (direction["status"] not in ("CIRCULATING", "EFFECTIVE")
                or (exp is not None and now() >= exp)):
            raise_err(ERR_DIRECTION_LAPSED,
                      "Direction is not circulating or has lapsed")
        # Rule 23: holder-of-record eligibility.
        case = DB["default_cases"].get(direction["default_case_id"])
        aggregate = holder_aggregate_principal(case["indenture_id"], account_id)
        if aggregate <= 0:
            raise_err(ERR_NO_ELIGIBLE_POSITION,
                      "Endorser holds no eligible principal")
        # Rule 26: shape.
        req_str(body, "noteholder_account_id")
        e = new_entity("direction_endorsements")
        e.update({
            "direction_id": did,
            "noteholder_account_id": account_id,
            "endorsed_principal_cents": aggregate,
            "status": "ACTIVE",
        })
        recompute_direction_aggregates(direction)
        refresh_direction_effectiveness(direction)
    return ok(public(e), 201)


@bp.route("/direction-endorsements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_endorsements():
    return list_response(DB["direction_endorsements"].values(), {
        "direction_id": request.args.get("direction_id"),
        "noteholder_account_id": request.args.get("noteholder_account_id"),
        "status": request.args.get("status"),
    })


@bp.route("/direction-endorsements/<eid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_endorsement(eid):
    e = DB["direction_endorsements"].get(eid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "DirectionEndorsement not found")
    return ok(public(e))


@bp.route("/direction-endorsements/<eid>/withdraw", methods=["POST"])
@require_roles("Noteholder")
def withdraw_endorsement(eid):
    with LOCK:
        en = DB["direction_endorsements"].get(eid)
        if en is None:
            raise_err(ERR_NOT_FOUND, "DirectionEndorsement not found")
        # Rule 3: only the endorsing holder may withdraw.
        check_noteholder_owns(en["noteholder_account_id"])
        # Rule 5: endorsement ACTIVE; direction still circulating.
        if en["status"] == "WITHDRAWN":
            raise_err(ERR_ALREADY_TERMINAL, "Endorsement is already WITHDRAWN")
        direction = DB["directions"].get(en["direction_id"])
        if direction is None or direction["status"] not in ("CIRCULATING", "EFFECTIVE"):
            raise_err(ERR_INVALID_STATE,
                      "Direction is no longer circulating")
        mutate(en, status="WITHDRAWN")
        recompute_direction_aggregates(direction)
        refresh_direction_effectiveness(direction)
    return ok(public(en))


@bp.route("/directions/<did>/execute", methods=["POST"])
@require_roles("TrustManager")
def execute_direction(did):
    with LOCK:
        direction = DB["directions"].get(did)
        if direction is None:
            raise_err(ERR_NOT_FOUND, "NoteholderDirection not found")
        # Rule 25: direction must be EFFECTIVE at execution.
        if direction["status"] != "EFFECTIVE":
            raise_err(ERR_THRESHOLD_NOT_MET,
                      "Direction is not EFFECTIVE")
        case = DB["default_cases"].get(direction["default_case_id"])
        if case is None:
            raise_err(ERR_NOT_FOUND, "DefaultCase not found")
        itype = direction["instruction_type"]
        # Rule 5: the case state must admit the instruction.
        required = {"ACCELERATE": "CONFIRMED", "WAIVE_DEFAULT": "CONFIRMED",
                    "RESCIND_ACCELERATION": "ACCELERATED"}[itype]
        if case["status"] in CASE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "DefaultCase is terminal (%s)" % case["status"])
        if case["status"] != required:
            raise_err(ERR_INVALID_STATE,
                      "DefaultCase state %s does not admit %s"
                      % (case["status"], itype))
        ind = DB["indentures"].get(case["indenture_id"])
        if itype == "ACCELERATE":
            mutate(case, status="ACCELERATED")
            if ind is not None:
                recompute_active_default_count(ind)
                cascade_accelerate(ind)
        elif itype == "WAIVE_DEFAULT":
            mutate(case, status="WAIVED")
            if ind is not None:
                maybe_resume_indenture(ind)
        else:  # RESCIND_ACCELERATION
            mutate(case, status="CONFIRMED")
            if ind is not None:
                recompute_active_default_count(ind)
                cascade_rescind_acceleration(ind)
        mutate(direction, status="EXECUTED")
    return ok(public(direction))
