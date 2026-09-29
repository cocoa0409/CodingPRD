"""Prospect registration and the five parallel prospect dimensions
(PRD 3.1, 3.2, 3.3, 3.4)."""

from flask import Blueprint

import auth
import constants as K
import derive
import logic
import respond
import validate
from db import db
from errors import ApiError

bp = Blueprint("prospects", __name__)

ALL_ROLES = list(K.ROLES)


@bp.post("/prospects")
def create_prospect():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    draft_cycle_id = validate.string(data, "draft_cycle_id")
    full_name = validate.string(data, "full_name")
    position_group = validate.enum(data, "position_group", K.POSITION_GROUPS)
    school_code = validate.string(data, "school_code")
    seasons_played = validate.integer(data, "seasons_played", minimum=0, maximum=6)
    scouting_grade = validate.number(data, "scouting_grade", minimum=0, maximum=100)
    scarcity_rank = validate.integer(
        data, "position_group_scarcity_rank", minimum=1
    )

    cycle = logic.fk_lookup(db.draft_cycles, draft_cycle_id, "draft cycle")
    logic.require_unfrozen(cycle)

    rec = db.insert(
        db.prospects,
        "Prospect",
        {
            "draft_cycle_id": cycle["id"],
            "full_name": full_name,
            "position_group": position_group,
            "school_code": school_code,
            "seasons_played": seasons_played,
            "scouting_grade": scouting_grade,
            "position_group_scarcity_rank": scarcity_rank,
            "declaration_status": "UNDECLARED",
            "declared_at": None,
            "late_declaration_waived": False,
            "early_entry_waived": False,
            "eligibility_status": "UNREVIEWED",
            "invitation_status": "NOT_INVITED",
            "consent_status": "NONE",
            "consent_scope": None,
            "consent_expires_at": None,
            "medical_clearance_status": "PENDING",
            "drafted_pick_overall_number": 0,
            "signing_status": "UNSIGNED",
        },
    )
    return respond.created(rec)


@bp.get("/prospects/<prospect_id>")
def get_prospect(prospect_id):
    auth.begin(ALL_ROLES)
    return respond.one(logic.path_lookup(db.prospects, prospect_id))


# --------------------------------------------------------------------------
# declaration dimension
# --------------------------------------------------------------------------
@bp.post("/prospects/<prospect_id>/declaration")
def declaration(prospect_id):
    user_id, role = auth.begin(["ProspectAgent"])
    data = validate.body()
    action = validate.enum(data, "action", ("DECLARE", "WITHDRAW"))
    prospect = logic.path_lookup(db.prospects, prospect_id)
    logic.own_prospect(role, user_id, prospect["id"])
    cycle = derive.prospect_cycle(prospect)

    if action == "DECLARE":
        logic.require_phase(cycle, ("DECLARATION_OPEN",))
    else:
        logic.require_phase(cycle, ("DECLARATION_OPEN", "COMBINE_WEEK"))
    logic.require_unfrozen(cycle)

    if action == "WITHDRAW":
        if prospect["declaration_status"] != "DECLARED":
            raise logic.invalid_transition(
                "Only a DECLARED prospect may withdraw a declaration."
            )
        if prospect["signing_status"] != "UNSIGNED":
            raise logic.invalid_transition(
                "A prospect with a contract in flight may not withdraw."
            )
        prospect["declaration_status"] = "WITHDRAWN"
        prospect["eligibility_status"] = "INELIGIBLE"
        logic.cancel_scheduled_bookings(prospect["id"])
        return respond.ok(prospect)

    # DECLARE
    if not prospect["late_declaration_waived"]:
        if db.now > cycle["declaration_deadline_at"]:
            raise ApiError(
                "ERR_DECLARATION_DEADLINE_PASSED",
                "The declaration deadline for this cycle has passed.",
            )
    if prospect["declaration_status"] != "UNDECLARED":
        raise ApiError(
            "ERR_ALREADY_DECLARED", "This prospect has already left UNDECLARED."
        )
    prospect["declaration_status"] = "DECLARED"
    prospect["declared_at"] = db.now
    return respond.ok(prospect)


# --------------------------------------------------------------------------
# eligibility dimension
# --------------------------------------------------------------------------
@bp.post("/prospects/<prospect_id>/eligibility-determination")
def eligibility_determination(prospect_id):
    auth.begin(["EligibilityCommittee"])
    data = validate.body()
    action = validate.enum(
        data, "action", ("DECLARE_ELIGIBLE", "DECLARE_INELIGIBLE")
    )
    prospect = logic.path_lookup(db.prospects, prospect_id)
    cycle = derive.prospect_cycle(prospect)
    logic.require_unfrozen(cycle)

    current = prospect["eligibility_status"]
    if action == "DECLARE_ELIGIBLE":
        if current != "UNREVIEWED":
            raise logic.invalid_transition(
                "Only an UNREVIEWED prospect may be declared eligible."
            )
        if prospect["declaration_status"] != "DECLARED":
            raise logic.invalid_transition(
                "The prospect has not declared for the draft."
            )
        if (
            prospect["seasons_played"] < K.ELIGIBILITY_MIN_SEASONS
            and not prospect["early_entry_waived"]
        ):
            raise logic.invalid_transition(
                "The prospect has not completed three amateur seasons."
            )
        prospect["eligibility_status"] = "ELIGIBLE"
        return respond.ok(prospect)

    # DECLARE_INELIGIBLE
    if current == "UNREVIEWED":
        if prospect["declaration_status"] not in ("DECLARED", "WITHDRAWN"):
            raise logic.invalid_transition(
                "An UNDECLARED prospect may not be ruled ineligible."
            )
        prospect["eligibility_status"] = "INELIGIBLE"
        if prospect["invitation_status"] in ("INVITED", "ACCEPTED"):
            prospect["invitation_status"] = "WITHDRAWN"
        logic.cancel_scheduled_bookings(prospect["id"])
        return respond.ok(prospect)
    if current == "ELIGIBLE":
        if prospect["drafted_pick_overall_number"] != 0:
            raise logic.invalid_transition(
                "A selected prospect may not be ruled ineligible."
            )
        prospect["eligibility_status"] = "INELIGIBLE"
        if prospect["invitation_status"] in ("INVITED", "ACCEPTED"):
            prospect["invitation_status"] = "WITHDRAWN"
        return respond.ok(prospect)
    raise logic.invalid_transition("INELIGIBLE is terminal on this dimension.")


# --------------------------------------------------------------------------
# invitation dimension
# --------------------------------------------------------------------------
INVITATION_ROLES = {
    "INVITE": ("LeagueDraftAdmin",),
    "WITHDRAW": ("LeagueDraftAdmin",),
    "ACCEPT": ("ProspectAgent",),
    "DECLINE": ("ProspectAgent",),
}


@bp.post("/prospects/<prospect_id>/combine-invitation")
def combine_invitation(prospect_id):
    user_id, role = auth.actor()
    auth.require(role, ["LeagueDraftAdmin", "ProspectAgent"])
    auth.require_action_role(role, validate.peek("action"), INVITATION_ROLES)

    data = validate.body()
    action = validate.enum(
        data, "action", ("INVITE", "ACCEPT", "DECLINE", "WITHDRAW")
    )
    prospect = logic.path_lookup(db.prospects, prospect_id)
    logic.own_prospect(role, user_id, prospect["id"])
    cycle = derive.prospect_cycle(prospect)

    if action in ("INVITE", "ACCEPT"):
        logic.require_phase(cycle, ("DECLARATION_OPEN", "COMBINE_WEEK"))
    logic.require_unfrozen(cycle)

    current = prospect["invitation_status"]
    if action == "INVITE":
        if current != "NOT_INVITED":
            raise logic.invalid_transition(
                "Only a NOT_INVITED prospect may be invited."
            )
        if prospect["eligibility_status"] == "INELIGIBLE":
            raise logic.invalid_transition("An INELIGIBLE prospect may not be invited.")
        if prospect["declaration_status"] != "DECLARED":
            raise logic.invalid_transition(
                "Only a DECLARED prospect may be invited."
            )
        prospect["invitation_status"] = "INVITED"
    elif action == "ACCEPT":
        if current != "INVITED":
            raise logic.invalid_transition("Only an INVITED invitation may be accepted.")
        prospect["invitation_status"] = "ACCEPTED"
    elif action == "DECLINE":
        if current != "INVITED":
            raise logic.invalid_transition("Only an INVITED invitation may be declined.")
        prospect["invitation_status"] = "DECLINED"
        prospect["medical_clearance_status"] = "UNVERIFIED"
    else:  # WITHDRAW
        if current != "ACCEPTED":
            raise logic.invalid_transition(
                "Only an ACCEPTED invitation may be withdrawn."
            )
        prospect["invitation_status"] = "WITHDRAWN"
        logic.cancel_scheduled_bookings(prospect["id"])
        prospect["medical_clearance_status"] = "UNVERIFIED"
    return respond.ok(prospect)


# --------------------------------------------------------------------------
# consent dimension
# --------------------------------------------------------------------------
@bp.post("/prospects/<prospect_id>/consent")
def consent(prospect_id):
    user_id, role = auth.begin(["ProspectAgent"])
    data = validate.body()
    action = validate.enum(data, "action", ("GRANT", "REVOKE"))
    scope = None
    expires_at = None
    if action == "GRANT":
        scope = validate.enum(data, "scope", K.CONSENT_SCOPES)
        expires_at = validate.instant(data, "consent_expires_at")

    prospect = logic.path_lookup(db.prospects, prospect_id)
    logic.own_prospect(role, user_id, prospect["id"])
    cycle = derive.prospect_cycle(prospect)
    logic.require_unfrozen(cycle)

    current = prospect["consent_status"]
    if action == "GRANT":
        if current == "GRANTED":
            raise logic.invalid_transition("Consent is already GRANTED.")
        if current == "NONE" and prospect["declaration_status"] != "DECLARED":
            raise logic.invalid_transition(
                "The prospect has not declared for the draft."
            )
        if expires_at <= db.now:
            raise logic.invalid_transition(
                "consent_expires_at must fall strictly after the current instant."
            )
        prospect["consent_status"] = "GRANTED"
        prospect["consent_scope"] = scope
        prospect["consent_expires_at"] = expires_at
        return respond.ok(prospect)

    if current != "GRANTED":
        raise logic.invalid_transition("Only GRANTED consent may be revoked.")
    logic.revoke_consent(prospect)
    return respond.ok(prospect)


# --------------------------------------------------------------------------
# eligibility waivers filed against a prospect
# --------------------------------------------------------------------------
@bp.post("/prospects/<prospect_id>/eligibility-waivers")
def create_waiver(prospect_id):
    user_id, role = auth.begin(["ProspectAgent"])
    data = validate.body()
    waiver_type = validate.enum(data, "waiver_type", K.WAIVER_TYPES)
    rationale = validate.string(data, "rationale")
    prospect = logic.path_lookup(db.prospects, prospect_id)
    logic.own_prospect(role, user_id, prospect["id"])
    logic.require_unfrozen(derive.prospect_cycle(prospect))

    rec = db.insert(
        db.eligibility_waivers,
        "EligibilityWaiver",
        {
            "prospect_id": prospect["id"],
            "waiver_type": waiver_type,
            "rationale": rationale,
            "status": "SUBMITTED",
            "info_request_count": 0,
            "submitted_by_user_id": user_id,
            "opened_by_user_id": None,
            "decided_by_user_id": None,
            "decision_note": None,
            "decided_at": None,
        },
    )
    return respond.created(rec)


@bp.get("/prospects/<prospect_id>/eligibility-waivers")
def list_waivers(prospect_id):
    auth.begin(["LeagueDraftAdmin", "EligibilityCommittee", "ProspectAgent"])
    limit, offset = validate.pagination()
    status = validate.query_enum("status", K.WAIVER_STATUSES)
    waiver_type = validate.query_enum("waiver_type", K.WAIVER_TYPES)
    prospect = logic.path_lookup(db.prospects, prospect_id)
    rows = [
        w
        for w in db.eligibility_waivers.values()
        if w["prospect_id"] == prospect["id"]
    ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if waiver_type is not None:
        rows = [r for r in rows if r["waiver_type"] == waiver_type]
    return respond.listing(logic.by_created(rows), limit, offset)
