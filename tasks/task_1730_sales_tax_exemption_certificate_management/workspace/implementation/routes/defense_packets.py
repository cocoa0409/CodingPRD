"""AuditDefensePacket endpoints (PRD §3.9)."""

from flask import Blueprint, g

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import ok, ok_list

bp = Blueprint("defense_packets", __name__)

AU = "Auditor"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/defense_packet", methods=["GET"])
def get_packet(tid, cid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    packets = [p for p in db.stores["defense_packets"].values() if p["campaign_id"] == campaign["id"]]
    packets.sort(key=lambda p: p["_seq"])
    return ok_list([db.pub(p) for p in packets[:1]])


@bp.route("/tenants/<tid>/audit_defense_packets/<pid>/assemble", methods=["POST"])
def assemble_packet(tid, pid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    packet = domain.get_scoped("defense_packets", pid, tenant["id"])
    campaign = db.stores["audit_campaigns"].get(packet["campaign_id"])
    # Assembling requires the campaign to be in DEFENSE_ASSEMBLY.
    if not campaign or campaign["status"] != "DEFENSE_ASSEMBLY":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Packet can be assembled only while its campaign is in DEFENSE_ASSEMBLY",
            409,
        )
    if packet["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT packet can be assembled", 409)
    included, missing, score = domain.compute_packet_fields(campaign)
    packet["included_certificate_ids"] = included
    packet["missing_certificate_ids"] = missing
    packet["completeness_score_pct"] = score
    packet["assembled_by_user_id"] = g.user_id
    packet["status"] = "ASSEMBLED"
    bump(packet)
    return ok(db.pub(packet))


@bp.route("/tenants/<tid>/audit_defense_packets/<pid>/deliver", methods=["POST"])
def deliver_packet(tid, pid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    packet = domain.get_scoped("defense_packets", pid, tenant["id"])
    if packet["status"] != "ASSEMBLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an ASSEMBLED packet can be delivered", 409)
    # Priority 21: delivery demands a completeness score of exactly 100.
    if packet["completeness_score_pct"] != 100:
        raise ApiError("ERR_PACKET_INCOMPLETE", "Defense packet completeness_score_pct is below 100", 409)
    packet["status"] = "DELIVERED"
    bump(packet)
    return ok(db.pub(packet))
