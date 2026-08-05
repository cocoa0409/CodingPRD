"""Referral steerage, navigation SLAs and loop closure (PRD 3.7)."""

from core import calc, constants, payload, serializers, store
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule

_AUTO_AUTHORIZED_TIERS = ("CENTER_OF_EXCELLENCE", "PREFERRED")


def _site_of_visit(visit):
    if visit is None:
        return None
    return store.get("site", visit.get("site_id"))


def _validate_create(ctx):
    payload.require_id(ctx.body, "participant_id")
    payload.require_id(ctx.body, "visit_id")
    payload.require_string(ctx.body, "specialty")
    tier = payload.require_present(ctx.body, "steerage_tier")
    urgency = payload.require_present(ctx.body, "urgency")
    if not isinstance(tier, str):
        raise ApiError("ERR_VALIDATION", "Field 'steerage_tier' must be a string.")
    if not isinstance(urgency, str):
        raise ApiError("ERR_VALIDATION", "Field 'urgency' must be a string.")


def _create(ctx):
    body = ctx.body
    visit = ctx.entity("visit_id")
    site = _site_of_visit(visit)
    due = calc.referral_sla_due_at(body["urgency"], store.now_dt(), site or {})
    tier = body["steerage_tier"]
    row = store.insert(
        "referral",
        {
            "participant_id": body["participant_id"],
            "visit_id": body["visit_id"],
            "redirected_from_referral_id": None,
            "specialty": body["specialty"],
            "steerage_tier": tier,
            "urgency": body["urgency"],
            "sla_due_at": due,
            # CENTER_OF_EXCELLENCE and PREFERRED need no prior authorization.
            "status": "AUTHORIZED" if tier in _AUTO_AUTHORIZED_TIERS else "SUBMITTED",
            "raised_by_provider_id": ctx.user_id,
            "authorized_by_provider_id": None,
            "escalated_at": None,
            "loop_closed_at": None,
            "consult_note_reference": None,
        },
    )
    return ObjectResult(serializers.dump("referral", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("referral"),
        {
            "participant_id": ctx.args.get("participant_id"),
            "visit_id": ctx.args.get("visit_id"),
            "redirected_from_referral_id": ctx.args.get("redirected_from_referral_id"),
            "raised_by_provider_id": ctx.args.get("raised_by_provider_id"),
            "status": ctx.args.get("status"),
            "urgency": ctx.args.get("urgency"),
        },
    )
    return paginate(ctx, "referral", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("referral", ctx.entity("referral_id")), 200)


# ---------------------------------------------------------------- authorize --

def _state_authorize(ctx):
    if ctx.entity("referral_id")["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")


def _segregation_of_duties(ctx):
    referral = ctx.entity("referral_id")
    if ctx.user_id == referral.get("raised_by_provider_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def _authorize(ctx):
    referral = ctx.entity("referral_id")
    referral["status"] = "AUTHORIZED"
    referral["authorized_by_provider_id"] = ctx.user_id
    return ObjectResult(serializers.dump("referral", referral), 200)


# ------------------------------------------------------------------ decline --

def _state_decline(ctx):
    if ctx.entity("referral_id")["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")


def _decline(ctx):
    referral = ctx.entity("referral_id")
    referral["status"] = "DECLINED"
    return ObjectResult(serializers.dump("referral", referral), 200)


# ----------------------------------------------------------------- redirect --

def _validate_redirect(ctx):
    payload.require_string(ctx.body, "specialty")
    tier = payload.require_present(ctx.body, "steerage_tier")
    urgency = payload.require_present(ctx.body, "urgency")
    if not isinstance(tier, str):
        raise ApiError("ERR_VALIDATION", "Field 'steerage_tier' must be a string.")
    if not isinstance(urgency, str):
        raise ApiError("ERR_VALIDATION", "Field 'urgency' must be a string.")


def _state_redirect(ctx):
    if ctx.entity("referral_id")["status"] != "DECLINED":
        raise ApiError("ERR_INVALID_STATE")


def _redirect(ctx):
    predecessor = ctx.entity("referral_id")
    predecessor["status"] = "REDIRECTED"
    visit = store.get("visit", predecessor["visit_id"])
    site = _site_of_visit(visit)
    due = calc.referral_sla_due_at(ctx.body["urgency"], store.now_dt(), site or {})
    successor = store.insert(
        "referral",
        {
            "participant_id": predecessor["participant_id"],
            "visit_id": predecessor["visit_id"],
            "redirected_from_referral_id": predecessor["id"],
            "specialty": ctx.body["specialty"],
            "steerage_tier": ctx.body["steerage_tier"],
            "urgency": ctx.body["urgency"],
            "sla_due_at": due,
            # A redirect successor starts at SUBMITTED whatever its tier: the
            # auto-authorization of original creation does not apply here.
            "status": "SUBMITTED",
            # Copied unchanged, so segregation of duties survives the chain.
            "raised_by_provider_id": predecessor["raised_by_provider_id"],
            "authorized_by_provider_id": None,
            "escalated_at": None,
            "loop_closed_at": None,
            "consult_note_reference": None,
        },
    )
    return ObjectResult(serializers.dump("referral", successor), 201)


# --------------------------------------------------------------- close loop --

def _validate_close(ctx):
    payload.require_string(ctx.body, "consult_note_reference")


def _state_close(ctx):
    if ctx.entity("referral_id")["status"] not in ("AUTHORIZED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE")


def _close_loop(ctx):
    referral = ctx.entity("referral_id")
    referral["status"] = "CLOSED_LOOP"
    referral["consult_note_reference"] = ctx.body["consult_note_reference"]
    referral["loop_closed_at"] = store.now_iso()
    # escalated_at is preserved on the ESCALATED -> CLOSED_LOOP leg.
    return ObjectResult(serializers.dump("referral", referral), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
]

_referral_owner_scope = scope_rule(
    participant_of=lambda ctx: ctx.entity("referral_id")["participant_id"]
)

SPECS = [
    Spec(
        method="POST",
        path="/referrals",
        roles=[constants.ROLE_CLINICIAN, constants.ROLE_CARE_NAVIGATOR],
        handler=_create,
        status=201,
        body_fks=[
            ("participant_id", "participant", True),
            ("visit_id", "visit", True),
        ],
        payload=_validate_create,
        enums=[("steerage_tier", "steerage_tier"), ("urgency", "urgency")],
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/referrals",
        roles=_READ_ROLES,
        handler=_list,
        walled=True,
    ),
    Spec(
        method="GET",
        path="/referrals/{referral_id}",
        roles=_READ_ROLES,
        handler=_read,
        walled=True,
        path_ids=[("referral_id", "referral")],
        scope=_referral_owner_scope,
    ),
    Spec(
        method="POST",
        path="/referrals/{referral_id}/authorize",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_authorize,
        path_ids=[("referral_id", "referral")],
        checks={10: _state_authorize, 22: _segregation_of_duties},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/referrals/{referral_id}/decline",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_decline,
        path_ids=[("referral_id", "referral")],
        checks={10: _state_decline},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/referrals/{referral_id}/redirect",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_redirect,
        status=201,
        path_ids=[("referral_id", "referral")],
        payload=_validate_redirect,
        enums=[("steerage_tier", "steerage_tier"), ("urgency", "urgency")],
        checks={10: _state_redirect},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/referrals/{referral_id}/close-loop",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_close_loop,
        path_ids=[("referral_id", "referral")],
        payload=_validate_close,
        checks={10: _state_close},
        is_write=True,
    ),
]
