"""AuditCampaign endpoints (PRD §3.8, §3.9)."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list

bp = Blueprint("audit_campaigns", __name__)

AU = "Auditor"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


@bp.route("/tenants/<tid>/audit_campaigns", methods=["POST"])
def create_campaign(tid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "name": body.get("name"),
        "population_state_filter": body.get("population_state_filter") or [],
        "sampling_method": body.get("sampling_method"),
        "target_confidence_pct": body.get("target_confidence_pct"),
        "floor_sample_size": body.get("floor_sample_size"),
        "planned_sample_size": None,
        "opened_by_user_id": None,
        "closed_by_user_id": None,
        "status": "DRAFT",
    })
    db.stores["audit_campaigns"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/audit_campaigns/<cid>", methods=["GET"])
def get_campaign(tid, cid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/open", methods=["POST"])
def open_campaign(tid, cid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT campaign can be opened", 409)
    # Configuration coherence; an incoherent configuration is rejected as an
    # invalid transition (PRD §3.8).
    method = campaign["sampling_method"]
    if method not in ("STATISTICAL", "FIXED_FLOOR"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Unsupported sampling_method", 409)
    if method == "STATISTICAL" and campaign["target_confidence_pct"] not in (90, 95, 99):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "STATISTICAL campaigns require target_confidence_pct of 90, 95, or 99", 409)
    if method == "FIXED_FLOOR" and not (
        isinstance(campaign["floor_sample_size"], int) and campaign["floor_sample_size"] >= 1
    ):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "FIXED_FLOOR campaigns require floor_sample_size >= 1", 409)
    campaign["opened_by_user_id"] = domain_actor_id()
    campaign["status"] = "SAMPLING"
    population = domain.sampling_population(tenant, campaign)
    campaign["planned_sample_size"] = domain.compute_planned_sample_size(len(population), campaign)
    bump(campaign)
    domain.recompute_audit_posture(tenant)
    bump(tenant)
    return ok(db.pub(campaign))


def domain_actor_id():
    from flask import g
    return g.user_id


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/sample", methods=["POST"])
def sample_campaign(tid, cid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    if campaign["status"] != "SAMPLING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a SAMPLING campaign can draw its sample", 409)
    population = domain.sampling_population(tenant, campaign)
    domain.create_samples_for_campaign(campaign, tenant, population)
    campaign["status"] = "FIELDWORK"
    bump(campaign)
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/samples", methods=["GET"])
def list_samples(tid, cid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    items = [s for s in db.stores["audit_samples"].values() if s["campaign_id"] == campaign["id"]]
    outcome = request.args.get("outcome")
    if outcome is not None:
        items = [s for s in items if s["outcome"] == outcome]
    items.sort(key=lambda s: s["_seq"])
    return ok_list([db.pub(s) for s in items])


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/resample", methods=["POST"])
def resample_campaign(tid, cid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    if campaign["status"] != "REMEDIATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a REMEDIATION campaign can be resampled", 409)
    # At least one RemediationAction in RESOLVED status.
    sample_ids = {
        s["id"] for s in db.stores["audit_samples"].values() if s["campaign_id"] == campaign["id"]
    }
    has_resolved = any(
        a["sample_id"] in sample_ids and a["status"] == "RESOLVED"
        for a in db.stores["remediation_actions"].values()
    )
    if not has_resolved:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Resampling requires at least one RESOLVED remediation action",
            409,
        )
    # Fresh samples for the previously failed certificates.
    failed_certs = sorted(
        {
            s["certificate_id"]
            for s in db.stores["audit_samples"].values()
            if s["campaign_id"] == campaign["id"] and s["outcome"] == "FAILED"
        },
        key=lambda cert_id: (
            db.stores["certificates"][cert_id]["_seq"]
            if cert_id in db.stores["certificates"]
            else 0
        ),
    )
    certs = [db.stores["certificates"][c] for c in failed_certs if c in db.stores["certificates"]]
    saved_plan = campaign["planned_sample_size"]
    campaign["planned_sample_size"] = len(certs)
    domain.create_samples_for_campaign(campaign, tenant, certs)
    campaign["planned_sample_size"] = saved_plan
    campaign["status"] = "FIELDWORK"
    bump(campaign)
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/begin_defense_assembly", methods=["POST"])
def begin_defense_assembly(tid, cid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    if campaign["status"] != "REMEDIATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a REMEDIATION campaign can enter defense assembly", 409)
    # Priority 20: every FAILED sample must have a RESOLVED remediation.
    actions = list(db.stores["remediation_actions"].values())
    for s in db.stores["audit_samples"].values():
        if s["campaign_id"] != campaign["id"] or s["outcome"] != "FAILED":
            continue
        if not any(a["sample_id"] == s["id"] and a["status"] == "RESOLVED" for a in actions):
            raise ApiError(
                "ERR_UNREMEDIATED_FAILURES",
                "Campaign has FAILED samples lacking a RESOLVED remediation action",
                409,
            )
    campaign["status"] = "DEFENSE_ASSEMBLY"
    bump(campaign)
    domain.recompute_audit_posture(tenant)
    bump(tenant)
    # The defense packet is one-to-one with its campaign; create it in DRAFT.
    existing = [
        p for p in db.stores["defense_packets"].values() if p["campaign_id"] == campaign["id"]
    ]
    if not existing:
        packet = db.make_record({
            "tenant_id": tenant["id"],
            "campaign_id": campaign["id"],
            "included_certificate_ids": [],
            "missing_certificate_ids": [],
            "completeness_score_pct": 0,
            "assembled_by_user_id": None,
            "status": "DRAFT",
        })
        db.stores["defense_packets"][packet["id"]] = packet
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/close", methods=["POST"])
def close_campaign(tid, cid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    if campaign["status"] != "DEFENSE_ASSEMBLY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DEFENSE_ASSEMBLY campaign can be closed", 409)
    packets = [
        p for p in db.stores["defense_packets"].values() if p["campaign_id"] == campaign["id"]
    ]
    if not packets or packets[0]["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Campaign cannot close before its defense packet is DELIVERED",
            409,
        )
    # Priority 8: closer must differ from opener.
    if domain_actor_id() == campaign["opened_by_user_id"]:
        raise ApiError(
            "ERR_SOD_CLOSER_IS_OPENER",
            "The auditor closing the campaign must differ from the one who opened it",
            409,
        )
    campaign["closed_by_user_id"] = domain_actor_id()
    campaign["status"] = "CLOSED"
    bump(campaign)
    domain.recompute_audit_posture(tenant)
    bump(tenant)
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/audit_campaigns/<cid>/cancel", methods=["POST"])
def cancel_campaign(tid, cid):
    require_role(AU)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("audit_campaigns", cid, tenant["id"])
    if campaign["status"] not in ("DRAFT", "SAMPLING"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a DRAFT or SAMPLING campaign can be cancelled",
            409,
        )
    was_sampling = campaign["status"] == "SAMPLING"
    campaign["status"] = "CANCELLED"
    bump(campaign)
    if was_sampling:
        # Cancelling from SAMPLING returns the tenant's posture to CLEAR.
        domain.recompute_audit_posture(tenant)
        bump(tenant)
    return ok(db.pub(campaign))
