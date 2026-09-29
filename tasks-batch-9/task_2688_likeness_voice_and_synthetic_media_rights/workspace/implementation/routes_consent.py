"""Consent grants: drafting, countersignature, suspension and revocation."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import calc
import guards
import services
from core import (
    ALL_ROLES, authorize, body_json, collection, db, fail, invalid, new_id, now,
    public, respond, touch, want_dt, want_enum, want_enum_list, want_bool,
    want_code_list, want_int, want_pct, want_str,
)

bp = Blueprint("consent", __name__)

GRANTOR_KINDS = ("TALENT", "ESTATE")
EXCLUSIVITY = ("EXCLUSIVE", "NON_EXCLUSIVE")
SUSPENSION_REASONS = ("DEATH_PENDING_ESTATE", "COMPLIANCE_HOLD")
TERMINAL_GRANT_STATUSES = ("REVOKED", "EXPIRED")


def _overlaps_half_open(a_from, a_until, b_from, b_until):
    return a_from < b_until and b_from < a_until


@bp.post("/consent-grants")
def draft_consent_grant():
    authorize("RightsAdministrator")
    body = body_json()

    talent_id = want_str(body, "talent_id", 1, None)
    grantor_kind = want_enum(body, "grantor_kind", GRANTOR_KINDS)
    permitted_media_types = want_enum_list(body, "permitted_media_types",
                                           calc.MEDIA_TYPES, 5)
    permitted_use_notes = want_str(body, "permitted_use_notes", 1, 500)
    territory_codes = want_code_list(body, "territory_codes", 20)
    exclusivity = want_enum(body, "exclusivity", EXCLUSIVITY)
    effective_from = want_dt(body, "effective_from")
    effective_until = want_dt(body, "effective_until")
    initial_creation_fee_cents = want_int(body, "initial_creation_fee_cents", 0)
    per_use_base_fee_cents = want_int(body, "per_use_base_fee_cents", 0)
    expected_talent_version = want_int(body, "expected_talent_version", 0)
    estate_authority_id = want_str(body, "estate_authority_id", 1, None,
                                   required=False, default=None)
    talent_share_pct = want_pct(body, "talent_share_pct", 0, 1, True, False,
                                required=False, default=Decimal("0.75"))
    agency_share_pct = want_pct(body, "agency_share_pct", 0, 1, False, True,
                                required=False, default=Decimal("0.20"))
    approval_required = want_bool(body, "approval_required", required=False, default=True)
    revocable = want_bool(body, "revocable", required=False, default=True)
    if talent_share_pct + agency_share_pct > Decimal("1"):
        invalid("talent_share_pct and agency_share_pct may not exceed 1 together")
    if grantor_kind == "ESTATE" and not estate_authority_id:
        invalid("estate_authority_id is required when grantor_kind is ESTATE")
    if grantor_kind == "TALENT" and estate_authority_id:
        invalid("estate_authority_id must be null when grantor_kind is TALENT")

    talent = guards.need_talent(talent_id)
    if estate_authority_id:
        guards.need_estate_authority(estate_authority_id)

    profile = guards.need_profile(talent["domicile_state_code"])

    union_snapshot = talent["union_code"] if talent["union_code"] != "NONE" else None
    governing_media = calc.governing_media_type(permitted_media_types)
    union_row = None
    if union_snapshot:
        union_row = calc.select_union_row(union_snapshot, governing_media, effective_from)
        if union_row is None:
            fail("ERR_UNION_SCHEDULE_MISSING",
                 "no union minimum row for %s / %s" % (union_snapshot, governing_media))

    if expected_talent_version != int(talent["version"]):
        fail("ERR_TALENT_VERSION_STALE",
             "expected_talent_version %s does not match the talent's current version %s"
             % (expected_talent_version, talent["version"]))

    guards.block_frozen(talent)
    guards.need_verified_estate(talent)
    guards.need_postmortem_registration(talent, profile)
    guards.need_live_postmortem_term(talent)

    if effective_until <= effective_from:
        fail("ERR_CONSENT_TERM_INVALID",
             "effective_until must be strictly after effective_from")
    if effective_until - effective_from < timedelta(days=calc.MIN_CONSENT_TERM_DAYS):
        fail("ERR_CONSENT_TERM_INVALID",
             "a consent term must span at least %d days" % calc.MIN_CONSENT_TERM_DAYS)

    for other in db.consent_grants.values():
        if other["talent_id"] != talent["id"]:
            continue
        if other["status"] in TERMINAL_GRANT_STATUSES:
            continue
        if not _overlaps_half_open(effective_from, effective_until,
                                   other["effective_from"], other["effective_until"]):
            continue
        if not set(permitted_media_types).intersection(set(other["permitted_media_types"])):
            continue
        if not set(territory_codes).intersection(set(other["territory_codes"])):
            continue
        if exclusivity == "EXCLUSIVE" or other["exclusivity"] == "EXCLUSIVE":
            fail("ERR_EXCLUSIVITY_WINDOW_CONFLICT",
                 "this term conflicts with an existing exclusive grant")

    if union_row is not None:
        floor = Decimal(int(union_row["minimum_per_use_cents"]))
        if Decimal(per_use_base_fee_cents) < calc.UNION_FLOOR_RATIO * floor:
            fail("ERR_COMPENSATION_BELOW_STATUTORY_FLOOR",
                 "per_use_base_fee_cents must be at least half the union per-use floor")

    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "talent_id": talent["id"],
        "estate_authority_id": estate_authority_id,
        "grantor_kind": grantor_kind,
        "permitted_media_types": permitted_media_types,
        "permitted_use_notes": permitted_use_notes,
        "territory_codes": territory_codes,
        "exclusivity": exclusivity,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "effective_end_actual": None,
        "initial_creation_fee_cents": initial_creation_fee_cents,
        "per_use_base_fee_cents": per_use_base_fee_cents,
        "talent_share_pct": talent_share_pct,
        "agency_share_pct": agency_share_pct,
        "administrator_share_pct": Decimal("1") - talent_share_pct - agency_share_pct,
        "approval_required": approval_required,
        "revocable": revocable,
        "union_code_snapshot": union_snapshot,
        "status": "PENDING_COUNTERSIGN",
        "suspension_reason": None,
        "drafted_by_user_id": g.user_id,
        "countersigned_at": None,
        "initial_compensation_cents": 0,
        "union_topup_cents": 0,
        "total_compensation_cents": 0,
        "_seq": db.next_seq(),
    }
    db.consent_grants[row["id"]] = row
    touch(talent)
    return respond(public(row), 201)


@bp.get("/consent-grants/<row_id>")
def read_consent_grant(row_id):
    authorize(*ALL_ROLES)
    return respond(public(guards.need_grant(row_id)))


@bp.get("/consent-grants")
def list_consent_grants():
    authorize(*ALL_ROLES)
    return collection(db.consent_grants.values(), {
        "talent_id": "talent_id",
        "estate_authority_id": "estate_authority_id",
        "status": "status",
        "exclusivity": "exclusivity",
    })


@bp.post("/consent-grants/<row_id>/countersign")
def countersign(row_id):
    authorize("TalentRepresentative", "EstateRepresentative")
    body_json()
    grant = guards.need_grant(row_id)
    talent = db.talents[grant["talent_id"]]
    profile = calc.profile_for(talent["domicile_state_code"])

    floor = guards.need_union_initial_floor(grant)
    guards.countersign_ownership(grant, talent, g.role, g.user_id)
    if grant["status"] != "PENDING_COUNTERSIGN":
        fail("ERR_INVALID_CONSENT_STATE",
             "only a PENDING_COUNTERSIGN grant may be countersigned")
    guards.block_frozen(talent)
    guards.need_verified_estate(talent)
    guards.need_postmortem_registration(talent, profile)

    scaled, initial, topup = calc.initial_creation_compensation(grant, floor)
    grant["status"] = "ACTIVE"
    grant["countersigned_at"] = now()
    grant["initial_compensation_cents"] = initial
    grant["union_topup_cents"] = topup
    services.append_entry(grant, "INITIAL_CREATION", scaled,
                          memo="Initial digital replica creation payment")
    if topup > 0:
        services.append_entry(grant, "UNION_TOPUP", topup,
                              memo="Union minimum top-up for the initial creation payment")
    services.recompute_grant_total(grant)
    touch(grant)
    services.recompute_talent(talent)
    touch(talent)
    return respond(public(grant))


@bp.post("/consent-grants/<row_id>/suspension")
def suspension(row_id):
    authorize("RightsAdministrator")
    body = body_json()
    action = want_enum(body, "action", ("SUSPEND", "REINSTATE"))
    reason = want_enum(body, "suspension_reason", SUSPENSION_REASONS,
                       required=False, default=None)
    grant = guards.need_grant(row_id)
    talent = db.talents[grant["talent_id"]]

    if action == "SUSPEND":
        if grant["status"] != "ACTIVE":
            fail("ERR_INVALID_CONSENT_STATE", "only an ACTIVE grant may be suspended")
        grant["status"] = "SUSPENDED"
        grant["suspension_reason"] = reason or "COMPLIANCE_HOLD"
        touch(grant)
        services.recompute_talent(talent)
        touch(talent)
        return respond(public(grant))

    if grant["status"] != "SUSPENDED":
        fail("ERR_INVALID_CONSENT_STATE", "only a SUSPENDED grant may be reinstated")
    prior_reason = grant["suspension_reason"]
    if prior_reason == "DEATH_PENDING_ESTATE":
        authority = services.verified_authority(talent["id"])
        if authority is None:
            fail("ERR_ESTATE_AUTHORITY_UNVERIFIED",
                 "a VERIFIED estate authority is required before reinstatement")
        profile = calc.profile_for(talent["domicile_state_code"])
        if profile is not None and profile["postmortem_requires_registration"] \
                and not authority.get("registration_number"):
            fail("ERR_POSTMORTEM_REGISTRATION_MISSING",
                 "this state requires a post-mortem rights registration number")
        expiry = talent.get("postmortem_rights_until")
        if expiry is None or now() > expiry:
            fail("ERR_POSTMORTEM_RIGHTS_EXPIRED",
                 "the post-mortem term has lapsed")
    grant["status"] = "ACTIVE"
    grant["suspension_reason"] = None
    touch(grant)
    services.release_estate_pending(talent, grant)
    touch(talent)
    return respond(public(grant))


@bp.post("/consent-grants/<row_id>/revoke")
def revoke(row_id):
    authorize("TalentRepresentative", "EstateRepresentative")
    body = body_json()
    want_str(body, "revocation_note", 1, None)
    grant = guards.need_grant(row_id)
    talent = db.talents[grant["talent_id"]]
    guards.revoke_ownership(grant, g.role, g.user_id)
    if grant["status"] not in ("PENDING_COUNTERSIGN", "ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_CONSENT_STATE", "this grant is already in a terminal status")
    if not grant["revocable"]:
        fail("ERR_CONSENT_NOT_REVOCABLE", "this grant is not revocable")

    started_from = grant["status"]
    grant["status"] = "REVOKED"
    grant["effective_end_actual"] = now()
    grant["suspension_reason"] = None
    touch(grant)
    if started_from == "PENDING_COUNTERSIGN":
        services.recompute_talent(talent)
    else:
        services.revoke_cascade(grant, talent)
    services.recompute_grant_total(grant)
    touch(talent)
    return respond(public(grant))
