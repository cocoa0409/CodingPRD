"""The biometric collection point inventory and lifecycle."""

from flask import Blueprint

import constants as K
import derive
import serialize
from authz import actor, require_role
from calc import refresh_destruction_due_at
from common import READ_ROLES_ALL, respond, respond_list
from errors import fail
from ops import (
    accommodations_for_asset,
    consents_for_asset,
    published_in_scope_policy,
    require_notice_coverage,
)
from store import db, new_record, touch
from validate import (
    body,
    find_asset,
    find_jurisdiction,
    find_program,
    find_vendor,
    opt_datetime,
    opt_str,
    query_enum,
    query_str,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("assets", __name__)


def _vendor_of(asset):
    if asset.get("vendor_id") is None:
        return None
    return db.vendors.get(asset["vendor_id"])


def _executed_contract_meeting_floor(vendor_id):
    for contract in db.contracts.values():
        if contract["vendor_id"] != vendor_id or contract["status"] != "EXECUTED":
            continue
        if contract["compliance_score"] >= K.CONTRACT_SCORE_FLOOR:
            return contract
    return None


@bp.post("/biometric-assets")
def create_asset():
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    data = body()
    program_id = req_str(data, "program_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    system_category = req_enum(data, "system_category", K.SYSTEM_CATEGORIES)
    modality = req_enum(data, "modality", K.MODALITIES)
    subject_class = req_enum(data, "subject_class", K.SUBJECT_CLASSES)
    template_storage_location = req_str(data, "template_storage_location")
    declared_retention_days = req_int(data, "declared_retention_days", minimum=1)
    retention_basis = req_enum(data, "retention_basis", K.RETENTION_BASES)
    vendor_id = opt_str(data, "vendor_id")

    program = find_program(program_id)
    find_jurisdiction(jurisdiction_id)
    if vendor_id is not None:
        find_vendor(vendor_id)

    rec = new_record()
    rec.update(
        {
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "vendor_id": vendor_id,
            "pinned_policy_id": None,
            "system_category": system_category,
            "modality": modality,
            "subject_class": subject_class,
            "template_storage_location": template_storage_location,
            "declared_retention_days": declared_retention_days,
            "retention_basis": retention_basis,
            "status": "DISCOVERED",
            "collection_started_at": None,
            "purpose_satisfied_at": None,
            "destruction_due_at": None,
            "templates_destroyed_at": None,
            "enrolled_subject_count": 0,
            "consent_gap_count": 0,
        }
    )
    db.assets[rec["id"]] = rec
    touch(program)
    return respond(serialize.asset, rec, 201)


@bp.patch("/biometric-assets/<asset_id>")
def patch_asset(asset_id):
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    data = body()

    updates = {}
    if "purpose_satisfied_at" in data:
        if data["purpose_satisfied_at"] is None:
            updates["purpose_satisfied_at"] = None
        else:
            updates["purpose_satisfied_at"] = opt_datetime(data, "purpose_satisfied_at")
    if "declared_retention_days" in data:
        updates["declared_retention_days"] = req_int(data, "declared_retention_days", minimum=1)
    if "retention_basis" in data:
        updates["retention_basis"] = req_enum(data, "retention_basis", K.RETENTION_BASES)
    if "template_storage_location" in data:
        updates["template_storage_location"] = req_str(data, "template_storage_location")

    asset = find_asset(asset_id)
    if asset["status"] == "DECOMMISSIONED":
        fail("ERR_INVALID_TRANSITION", "A decommissioned collection point can no longer be edited.")

    asset.update(updates)
    if asset["pinned_policy_id"] is not None and asset["collection_started_at"] is not None:
        refresh_destruction_due_at(asset)
    touch(asset)
    return respond(serialize.asset, asset)


@bp.post("/biometric-assets/<asset_id>/transitions")
def asset_transition(asset_id):
    _, role = actor()
    require_role(role, ("PrivacyOfficer",))
    raw = body()
    to_status = req_enum(raw, "to_status", K.ASSET_STATUSES)

    asset = find_asset(asset_id)
    current = asset["status"]

    edges = {
        ("DISCOVERED", "CLASSIFIED"),
        ("CLASSIFIED", "ACTIVE"),
        ("ACTIVE", "GATED"),
        ("GATED", "ACTIVE"),
        ("GATED", "DECOMMISSIONED"),
        ("CLASSIFIED", "DECOMMISSIONED"),
    }
    if (current, to_status) not in edges:
        fail(
            "ERR_INVALID_TRANSITION",
            "A collection point cannot move from %s to %s." % (current, to_status),
        )

    derive.refresh_all()
    program = db.programs.get(asset["program_id"])
    vendor = _vendor_of(asset)

    if to_status == "CLASSIFIED":
        if vendor is not None:
            analysable = any(
                c["vendor_id"] == vendor["id"] and c["status"] in ("APPROVED", "EXECUTED")
                for c in db.contracts.values()
            )
            if not analysable:
                fail(
                    "ERR_VENDOR_CONTRACT_NONCOMPLIANT",
                    "The operating vendor has no approved or executed contract.",
                )
        asset["status"] = "CLASSIFIED"
        touch(asset)

    elif to_status == "ACTIVE" and current == "CLASSIFIED":
        # step 9
        if program is not None and program["posture"] in ("RESTRICTED", "FROZEN"):
            fail(
                "ERR_PROGRAM_POSTURE_BLOCKED",
                "The program posture is %s; activation is blocked." % program["posture"],
            )
        # step 10
        policy = published_in_scope_policy(asset["program_id"], asset["jurisdiction_id"])
        if policy is None:
            fail(
                "ERR_POLICY_NOT_PUBLISHED",
                "No published policy covers this collection point's jurisdiction.",
            )
        juris = find_jurisdiction(asset["jurisdiction_id"])
        require_notice_coverage(juris, asset["subject_class"])
        if vendor is not None and int(vendor["risk_score"]) > K.VENDOR_RISK_GATE:
            fail(
                "ERR_VENDOR_RISK_TOO_HIGH",
                "The operating vendor's risk score exceeds the gate of %s." % K.VENDOR_RISK_GATE,
            )
        # step 12
        if vendor is not None and _executed_contract_meeting_floor(vendor["id"]) is None:
            fail(
                "ERR_CONTRACT_SCORE_BELOW_FLOOR",
                "The operating vendor has no executed contract meeting the score floor.",
            )

        asset["pinned_policy_id"] = policy["id"]
        if asset["collection_started_at"] is None:
            asset["collection_started_at"] = db.clock
        refresh_destruction_due_at(asset)
        asset["status"] = "ACTIVE"
        touch(asset)

    elif to_status == "ACTIVE":  # GATED -> ACTIVE revival
        # step 9
        if program is not None and program["posture"] == "FROZEN":
            fail("ERR_PROGRAM_POSTURE_BLOCKED", "The program is FROZEN; revival is blocked.")
        # step 12
        if vendor is not None and _executed_contract_meeting_floor(vendor["id"]) is None:
            fail(
                "ERR_CONTRACT_SCORE_BELOW_FLOOR",
                "The operating vendor has no executed contract meeting the score floor.",
            )
        # step 13
        if int(asset["consent_gap_count"] or 0) > 0:
            fail(
                "ERR_CONSENT_GAP_OPEN",
                "This collection point still carries unresolved consent records.",
            )
        refresh_destruction_due_at(asset)
        asset["status"] = "ACTIVE"
        touch(asset)

    elif to_status == "GATED":
        asset["status"] = "GATED"
        touch(asset)

    elif current == "CLASSIFIED":  # CLASSIFIED -> DECOMMISSIONED
        if any(c["asset_id"] == asset_id for c in db.consents.values()):
            fail(
                "ERR_INVALID_TRANSITION",
                "A classified collection point with consent records cannot be decommissioned.",
            )
        asset["status"] = "DECOMMISSIONED"
        touch(asset)

    else:  # GATED -> DECOMMISSIONED, full teardown
        asset["templates_destroyed_at"] = db.clock
        for consent in consents_for_asset(
            asset_id, ("SOLICITED", "GRANTED", "RESOLICIT_REQUIRED")
        ):
            consent["status"] = "EXPIRED"
            touch(consent)
        for accommodation in accommodations_for_asset(
            asset_id, ("REQUESTED", "PROVISIONED", "ACTIVE")
        ):
            accommodation["status"] = "ENDED"
            touch(accommodation)
        asset["status"] = "DECOMMISSIONED"
        touch(asset)

    return respond(serialize.asset, asset)


@bp.get("/biometric-assets/<asset_id>")
def read_asset(asset_id):
    _, role = actor()
    require_role(role, READ_ROLES_ALL)
    asset = find_asset(asset_id)
    return respond(serialize.asset, asset)


@bp.get("/biometric-assets")
def list_assets():
    _, role = actor()
    require_role(role, READ_ROLES_ALL)
    program_id = query_str("program_id")
    jurisdiction_id = query_str("jurisdiction_id")
    vendor_id = query_str("vendor_id")
    pinned_policy_id = query_str("pinned_policy_id")
    status = query_enum("status", K.ASSET_STATUSES)
    rows = list(db.assets.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    if pinned_policy_id is not None:
        rows = [r for r in rows if r["pinned_policy_id"] == pinned_policy_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, serialize.asset)
