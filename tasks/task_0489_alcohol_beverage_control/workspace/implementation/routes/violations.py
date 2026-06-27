"""Violations + administrative actions: file/contest/sustain/dismiss, the
sustain cascade (action + fine + demerits + suspension threshold), and enforce."""
from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS
from db import db, new_id, common_fields, touch
from helpers import body, paginate, sort_created, out, out_list, get_or_404
import validate
from calculations import fine_cents, demerit_for
from cascades import expire_active_permits, revoke_active_permits
from response import ok, created, listed

bp = Blueprint("violations", __name__)

SEVERITIES = {"MINOR", "SERIOUS", "EGREGIOUS"}
ACTION_TYPES = {"FINE", "SUSPENSION", "REVOCATION"}


@bp.route("/violations", methods=["POST"])
def file_violation():
    caller = require_auth(["Investigator"])
    data = body()
    license_id = validate.require_str(data, "license_id")
    if license_id not in db.licenses:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")
    severity = validate.require_enum(data, "severity", SEVERITIES)

    ent = {
        "id": new_id(), "license_id": license_id,
        "investigator_user_id": caller.user_id, "severity": severity,
        "status": "ALLEGED", "action_id": None,
    }
    ent.update(common_fields())
    db.violations[ent["id"]] = ent
    return created(out(ent))


@bp.route("/violations/<id>", methods=["GET"])
def get_violation(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.violations, id)
    return ok(out(ent))


@bp.route("/violations/<id>/contest", methods=["POST"])
def contest_violation(id):
    require_auth(["Applicant"])
    v = get_or_404(db.violations, id)
    if v["status"] != "ALLEGED":
        raise errors.err(errors.ERR_INVALID_STATE, "Violation not ALLEGED")
    v["status"] = "CONTESTED"
    touch(v)
    return ok(out(v))


@bp.route("/violations/<id>/sustain", methods=["POST"])
def sustain_violation(id):
    caller = require_auth(["AdjudicationOfficer"])
    v = get_or_404(db.violations, id)
    if v["status"] not in ("ALLEGED", "CONTESTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Violation not ALLEGED/CONTESTED")
    # priority 5: segregation of duties
    if caller.user_id == v["investigator_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Adjudicator must differ from investigator")

    data = body()
    action_type = validate.require_enum(data, "action_type", ACTION_TYPES)
    suspension_days = validate.opt_int(data, "suspension_days", 0, minimum=0)

    lic = db.licenses.get(v["license_id"])
    prior_demerits = lic["demerit_points"] if lic is not None else 0

    # Create the administrative action; compute the fine from the prior snapshot.
    computed_fine = fine_cents(v["severity"], prior_demerits, action_type)
    action = {
        "id": new_id(), "violation_id": v["id"], "license_id": v["license_id"],
        "action_type": action_type, "fine_cents": computed_fine,
        "fine_paid_cents": 0, "suspension_days": suspension_days,
        "adjudicator_user_id": caller.user_id,
    }
    action.update(common_fields())
    db.administrative_actions[action["id"]] = action

    v["status"] = "SUSTAINED"
    v["action_id"] = action["id"]
    touch(v)

    if lic is not None:
        lic["demerit_points"] = lic["demerit_points"] + demerit_for(v["severity"])
        lic["outstanding_fine_cents"] = lic["outstanding_fine_cents"] + computed_fine
        # suspension_threshold: demerit_points >= 10 suspends ACTIVE/RENEWAL_DUE
        if lic["demerit_points"] >= 10 and lic["status"] in ("ACTIVE", "RENEWAL_DUE"):
            lic["status"] = "SUSPENDED"
            expire_active_permits(lic["id"])
        touch(lic)
    return ok(out(v))


@bp.route("/violations/<id>/dismiss", methods=["POST"])
def dismiss_violation(id):
    caller = require_auth(["AdjudicationOfficer"])
    v = get_or_404(db.violations, id)
    if v["status"] != "CONTESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Violation not CONTESTED")
    if caller.user_id == v["investigator_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Adjudicator must differ from investigator")
    v["status"] = "DISMISSED"
    touch(v)
    return ok(out(v))


# --- Administrative actions --------------------------------------------------
@bp.route("/administrative-actions/<id>", methods=["GET"])
def get_action(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.administrative_actions, id)
    return ok(out(ent))


@bp.route("/violations/<id>/administrative-actions", methods=["GET"])
def list_violation_actions(id):
    require_auth(ALL_READERS)
    get_or_404(db.violations, id)
    items = [a for a in db.administrative_actions.values() if a["violation_id"] == id]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/administrative-actions/<id>/enforce", methods=["POST"])
def enforce_action(id):
    require_auth(["AdjudicationOfficer"])
    action = get_or_404(db.administrative_actions, id)
    lic = db.licenses.get(action["license_id"])
    if lic is None:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")

    if action["action_type"] == "SUSPENSION":
        if lic["status"] not in ("ACTIVE", "RENEWAL_DUE"):
            raise errors.err(errors.ERR_INVALID_STATE, "License not ACTIVE/RENEWAL_DUE")
        lic["status"] = "SUSPENDED"
        expire_active_permits(lic["id"])
        touch(lic)
    elif action["action_type"] == "REVOCATION":
        if lic["status"] not in ("ACTIVE", "SUSPENDED", "RENEWAL_DUE"):
            raise errors.err(errors.ERR_INVALID_STATE, "License not in a revocable state")
        lic["status"] = "REVOKED"
        revoke_active_permits(lic["id"])
        touch(lic)
    else:  # FINE — nothing to enforce beyond the ledger sync at sustain time
        raise errors.err(errors.ERR_INVALID_STATE, "FINE action requires no enforcement")

    return ok(out(action))
