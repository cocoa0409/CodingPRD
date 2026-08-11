"""Members and their preference profile (PRD 3.2)."""
from flask import Blueprint, g, request

import authz
import constants as C
import guards
import lookup
import store
import validate as V
from errors import ApiError
from routes.common import created, ok

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "full_name", "email")                                # rung 4
    full_name = V.string_field(body["full_name"], "full_name", 1, 120)   # rung 6
    email = V.string_field(body["email"], "email", 1)
    if "@" not in email:
        raise ApiError("ERR_VALIDATION", "Field 'email' must contain '@'.")
    allergies = body.get("allergy_exclusions")
    allergies = [] if allergies is None else \
        V.string_array_field(allergies, "allergy_exclusions")
    dislikes = body.get("dislikes")
    dislikes = [] if dislikes is None else V.string_array_field(dislikes, "dislikes")
    never = body.get("never_substitute")
    never = False if never is None else V.bool_field(never, "never_substitute")
    guards.unique("Member", lambda m: m["email"] == email)               # rung 53

    rec = store.create("Member", {
        "full_name": full_name, "email": email,
        "allergy_exclusions": allergies, "dislikes": dislikes,
        "never_substitute": never, "season_no_show_count": 0,
        "standing": "GOOD", "credit_balance_cents": 0,
    })
    return created(rec)


@bp.get("/members/<mid>")
def read_member(mid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER, C.ROLE_HUB)
    member = lookup.member(mid)                                          # rung 9
    authz.own_member(member["id"])                                       # rung 22
    return ok(member)


@bp.patch("/members/<mid>/preferences")
def update_preferences(mid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER)
    body = V.body_of(request)
    # Every input on this endpoint is optional, so rung 4 has nothing to assert.
    allergies = body.get("allergy_exclusions")
    if allergies is not None:
        allergies = V.string_array_field(allergies, "allergy_exclusions")  # rung 6
    dislikes = body.get("dislikes")
    if dislikes is not None:
        dislikes = V.string_array_field(dislikes, "dislikes")
    never = body.get("never_substitute")
    if never is not None:
        never = V.bool_field(never, "never_substitute")
    standing_reset = body.get("standing_reset")
    if standing_reset is not None:
        standing_reset = V.bool_field(standing_reset, "standing_reset")

    member = lookup.member(mid)                                          # rung 9
    authz.own_member(member["id"])                                       # rung 22
    # rung 24 carve-out: "the member preference update".

    # Adjudication of friction 8: standing_reset sent by a Member is refused
    # with ERR_UNAUTHORIZED, not silently ignored.  Rung 4's ignore rule speaks
    # about UNKNOWN fields, and standing_reset is a declared input of this
    # endpoint; PRD 4's own endpoint table calls it "administrator-only", and
    # ERR_UNAUTHORIZED is the only code in the catalogue that expresses a role
    # restriction.  Only an actual attempt to use the instrument (true) is
    # refused, so a Member may still send standing_reset false alongside a
    # legitimate preference edit.
    if standing_reset and g.role != C.ROLE_ADMIN:
        raise ApiError("ERR_UNAUTHORIZED",
                       "standing_reset is an administrator's instrument.")

    if allergies is not None:
        member["allergy_exclusions"] = allergies
    if dislikes is not None:
        member["dislikes"] = dislikes
    if never is not None:
        member["never_substitute"] = never
    if standing_reset:
        member["season_no_show_count"] = 0
        member["standing"] = "GOOD"
        # PRD 3.2: "Subscriptions that were paused because of a restriction are
        # not automatically resumed by the reset."
    store.touch(member)
    return ok(member)
