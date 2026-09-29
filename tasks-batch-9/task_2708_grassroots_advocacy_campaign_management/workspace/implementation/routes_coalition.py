"""CoalitionPartner and PartnerEndorsement endpoints (PRD 3.3, 3.4)."""

from flask import Blueprint

import calc
import cascades
import gates
import serializers as S
from common import (
    R_COMPLIANCE,
    R_DIRECTOR,
    R_PARTNER,
    R_STRATEGIST,
    by_created,
    check_shape,
    db,
    err,
    f_bool,
    f_enum,
    f_int,
    f_str,
    get_body,
    must,
    must_fk,
    new_row,
    ok,
    ok_list,
    pagination,
    q_str,
    require_role,
    touch,
)

bp = Blueprint("coalition", __name__)

TIERS = ("ANCHOR", "CORE", "ALLY")


@bp.post("/advocacy/coalition-partners")
def create_partner():
    require_role(R_DIRECTOR)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    check_shape(
        body, required=("campaign_id", "org_name", "tier", "branding_asset_ref")
    )
    org_name = f_str(body, "org_name", max_len=160)
    tier = f_enum(body, "tier", TIERS)
    branding = f_str(body, "branding_asset_ref", max_len=120)
    gates.gate_campaign_active(campaign)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "org_name": org_name,
            "tier": tier,
            "branding_asset_ref": branding,
            "share_weight": calc.SHARE_WEIGHT[tier],
            "committed_cents": 0,
            "status": "ACTIVE",
            "active_endorsement_count": 0,
        }
    )
    db.partners[row["id"]] = row
    calc.refresh_cost_share(campaign)
    calc.refresh_variant_quorums(campaign["id"])
    return ok(S.partner_out(row), 201)


@bp.get("/advocacy/coalition-partners/<partner_id>")
def get_partner(partner_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    row = must("partner", partner_id)
    return ok(S.partner_out(row))


@bp.get("/advocacy/coalition-partners")
def list_partners():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    limit, offset = pagination()
    campaign_id = q_str("campaign_id")
    tier = q_str("tier")
    status = q_str("status")
    rows = by_created(list(db.partners.values()))
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([S.partner_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/coalition-partners/<partner_id>/withdraw")
def withdraw_partner(partner_id):
    require_role(R_DIRECTOR, R_PARTNER)
    partner = must("partner", partner_id)
    campaign = db.campaigns[partner["campaign_id"]]
    body = get_body()
    check_shape(body, required=("withdraw_reason",))
    f_str(body, "withdraw_reason", max_len=400)
    gates.gate_owner_partner(partner["id"])
    gates.gate_campaign_active(campaign)
    gates.gate_state(partner["status"], ("ACTIVE",))
    partner["status"] = "WITHDRAWN"
    partner["committed_cents"] = 0
    touch(partner)
    calc.refresh_cost_share(campaign)
    # hop 1: revoke this partner's ACTIVE endorsements
    affected = []
    for endorsement in calc.endorsements_of_partner(partner["id"]):
        if endorsement["status"] != "ACTIVE":
            continue
        endorsement["status"] = "REVOKED"
        endorsement["revoked_reason"] = "PARTNER_WITHDRAWN"
        touch(endorsement)
        affected.append(endorsement["message_variant_id"])
    calc.refresh_partner_endorsement_count(partner)
    # hop 2: endorsement_count and quorum on the affected variants
    calc.refresh_variant_quorums(campaign["id"])
    for variant_id in affected:
        variant = db.variants.get(variant_id)
        if variant is None:
            continue
        calc.refresh_variant_endorsement_count(variant)
    # hop 3 + hop 4: quorum-driven demotion, then its scheduled waves
    for variant in calc.variants_of(campaign["id"]):
        cascades.enforce_quorum(variant)
    # hop 5: blocked count and posture
    calc.cascade(campaign)
    return ok(S.partner_out(partner))


# ---------------------------------------------------------------------------
# Partner endorsements
# ---------------------------------------------------------------------------


@bp.post("/advocacy/partner-endorsements")
def create_endorsement():
    require_role(R_PARTNER, R_DIRECTOR)
    body = get_body()
    partner = must_fk("partner", body, "partner_id")
    variant = must_fk("variant", body, "message_variant_id")
    check_shape(
        body,
        required=(
            "partner_id",
            "message_variant_id",
            "discipline_pledge",
            "talking_points_ack",
            "expected_variant_version",
        ),
    )
    f_bool(body, "discipline_pledge", must_be=True)
    f_bool(body, "talking_points_ack", must_be=True)
    expected = f_int(body, "expected_variant_version", minimum=0)
    gates.gate_owner_partner(partner["id"])
    gates.gate_variant_version(variant, expected)
    campaign = db.campaigns[partner["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    for existing in calc.endorsements_of_variant(variant["id"]):
        if existing["partner_id"] == partner["id"] and existing["status"] == "ACTIVE":
            err(
                "ERR_DUPLICATE_ENDORSEMENT",
                "this partner already holds an ACTIVE endorsement of that variant",
            )
    if partner["status"] != "ACTIVE":
        err("ERR_PARTNER_WITHDRAWN", "the coalition partner has withdrawn")
    if partner["campaign_id"] != variant["campaign_id"]:
        err("ERR_CAMPAIGN_MISMATCH", "partner and variant belong to different campaigns")
    row = new_row()
    row.update(
        {
            "partner_id": partner["id"],
            "message_variant_id": variant["id"],
            "discipline_pledge": True,
            "talking_points_ack": True,
            "endorsed_variant_version": int(variant["version"]),
            "status": "ACTIVE",
            "revoked_reason": None,
        }
    )
    db.endorsements[row["id"]] = row
    calc.refresh_partner_endorsement_count(partner)
    calc.refresh_variant_endorsement_count(variant)
    quorum = calc.quorum_for(campaign["id"])
    if variant["required_endorsement_quorum"] != quorum:
        variant["required_endorsement_quorum"] = quorum
        touch(variant)
    return ok(S.endorsement_out(row), 201)


@bp.get("/advocacy/partner-endorsements/<endorsement_id>")
def get_endorsement(endorsement_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    row = must("endorsement", endorsement_id)
    return ok(S.endorsement_out(row))


@bp.get("/advocacy/partner-endorsements")
def list_endorsements():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    limit, offset = pagination()
    partner_id = q_str("partner_id")
    variant_id = q_str("message_variant_id")
    status = q_str("status")
    rows = by_created(list(db.endorsements.values()))
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    if variant_id is not None:
        rows = [r for r in rows if r["message_variant_id"] == variant_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([S.endorsement_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/partner-endorsements/<endorsement_id>/revoke")
def revoke_endorsement(endorsement_id):
    require_role(R_PARTNER, R_DIRECTOR)
    endorsement = must("endorsement", endorsement_id)
    partner = db.partners[endorsement["partner_id"]]
    campaign = db.campaigns[partner["campaign_id"]]
    body = get_body()
    check_shape(body, required=("revoked_reason",))
    reason = f_str(body, "revoked_reason", max_len=400)
    gates.gate_owner_partner(endorsement["partner_id"])
    gates.gate_campaign_active(campaign)
    gates.gate_state(endorsement["status"], ("ACTIVE",))
    if partner["status"] != "ACTIVE":
        err("ERR_PARTNER_WITHDRAWN", "the coalition partner has withdrawn")
    cascades.revoke_endorsement_row(endorsement, reason)
    calc.cascade(campaign)
    return ok(S.endorsement_out(endorsement))
