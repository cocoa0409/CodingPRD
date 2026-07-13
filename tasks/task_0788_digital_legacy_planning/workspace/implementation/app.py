"""Digital-Legacy & End-of-Life Planning API (task_0788).

Flask app with in-memory storage. Boots empty on every launch.
"""
import os
import math
from datetime import timedelta

from flask import Flask, request

import store
import domain as d
from errors import ApiError
from helpers import (
    begin, check_scope, get_body, ok, ok_list, err_response,
    req_str, opt_str, req_enum, opt_enum, req_int, opt_int, opt_number,
    req_dt, req_enum_array, get_pagination, sort_created,
)

app = Flask(__name__)


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_VALIDATION", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_VALIDATION", f"Unexpected error: {e}", 400)


# =============================================================================
# Generic list helper
# =============================================================================
def scoped_records(records, ctx):
    role, uid = ctx
    if role == "Owner":
        return [r for r in records if r.get("plan_id") == uid]
    if role == "Deputy":
        dep = store.DEPUTIES.get(uid)
        if not dep:
            return []
        return [r for r in records if r.get("plan_id") == dep["plan_id"]]
    return list(records)


def finalize_list(records, serializer):
    limit, offset = get_pagination()
    records = sort_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def deputy_can_read_item(deputy_uid, item):
    dep = store.DEPUTIES.get(deputy_uid)
    if not dep:
        return False
    if item["status"] != "RELEASED":
        return False
    if item["kind"] not in dep["access_scope"]:
        return False
    for r in store.RELEASE_REQUESTS.values():
        if (r["requested_by_deputy_id"] == deputy_uid
                and r["status"] == "GRANTED"
                and r["plan_id"] == item["plan_id"]
                and item["kind"] in r["scope_kinds"]):
            return True
    return False


# =============================================================================
# Plan
# =============================================================================
@app.route("/legacy/plans", methods=["POST"])
def create_plan():
    ctx = begin({"Owner", "PlatformAdmin"})
    body = get_body()
    owner_full_name = req_str(body, "owner_full_name")
    owner_email = req_str(body, "owner_email")
    rec = store.base_record()
    rec.update({
        "owner_full_name": owner_full_name,
        "owner_email": owner_email,
        "life_status": "ACTIVE",
        "life_evidence_ref": None,
    })
    store.PLANS[rec["id"]] = rec
    return ok(d.serialize_plan(rec), 201)


@app.route("/legacy/plans/<plan_id>", methods=["GET"])
def get_plan_ep(plan_id):
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])
    return ok(d.serialize_plan(plan), 200)


@app.route("/legacy/plans/<plan_id>/completeness", methods=["GET"])
def plan_completeness_ep(plan_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])
    return ok(d.serialize_plan(plan), 200)


@app.route("/legacy/plans/<plan_id>/life-status", methods=["POST"])
def plan_life_status_ep(plan_id):
    ctx = begin({"PlatformAdmin"})
    body = get_body()
    new_status = req_str(body, "new_status")
    evidence_ref = req_str(body, "evidence_ref")
    plan = d.get_plan(plan_id)

    allowed = {
        "ACTIVE": {"INCAPACITATED", "DECEASED"},
        "INCAPACITATED": {"DECEASED"},
        "DECEASED": set(),
    }
    if new_status not in allowed.get(plan["life_status"], set()):
        raise ApiError("ERR_INVALID_LIFE_EVENT", "Illegal life-status transition")

    plan["life_status"] = new_status
    plan["life_evidence_ref"] = evidence_ref
    store.touch(plan)

    if new_status == "DECEASED":
        for r in store.REVIEW_REMINDERS.values():
            if r["plan_id"] == plan_id and r["status"] in ("SCHEDULED", "DUE", "OVERDUE"):
                r["status"] = "DISMISSED"
                store.touch(r)
    return ok(d.serialize_plan(plan), 200)


# =============================================================================
# VaultItem
# =============================================================================
@app.route("/legacy/vault-items", methods=["POST"])
def create_vault_item():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    kind = req_enum(body, "kind", d.VAULT_KINDS)
    category = req_str(body, "category")
    title = req_str(body, "title")
    secret_ref = req_str(body, "secret_ref")
    sensitivity = opt_enum(body, "sensitivity", d.SENSITIVITY, "MEDIUM")
    gross = opt_int(body, "gross_value_cents", None, min_value=0)
    liability = opt_int(body, "liability_cents", 0, min_value=0)
    dist = opt_enum(body, "distribution_basis", d.DISTRIBUTION_BASIS, "NET")

    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])

    if kind == "ASSET":
        net = None
        if gross is not None:
            net = max(gross - (liability or 0), 0)
    else:
        net = None

    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "kind": kind,
        "category": category,
        "title": title,
        "secret_ref": secret_ref,
        "sensitivity": sensitivity,
        "gross_value_cents": gross,
        "liability_cents": liability,
        "distribution_basis": dist,
        "net_value_cents": net,
        "status": "DRAFT",
    })
    store.VAULT_ITEMS[rec["id"]] = rec
    return ok(d.serialize_vault_item(rec), 201)


@app.route("/legacy/vault-items", methods=["GET"])
def list_vault_items():
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    role, uid = ctx
    records = scoped_records(list(store.VAULT_ITEMS.values()), ctx)

    plan_id = request.args.get("plan_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if kind:
        records = [r for r in records if r["kind"] == kind]
    if status:
        records = [r for r in records if r["status"] == status]
    else:
        records = [r for r in records if r["status"] != "ARCHIVED"]

    if role == "Deputy":
        records = [r for r in records if deputy_can_read_item(uid, r)]

    return finalize_list(records, d.serialize_vault_item)


@app.route("/legacy/vault-items/<item_id>", methods=["GET"])
def get_vault_item_ep(item_id):
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    role, uid = ctx
    item = d.get_vault_item(item_id)
    check_scope(ctx, item["plan_id"])
    if role == "Deputy" and not deputy_can_read_item(uid, item):
        raise ApiError("ERR_ACCESS_NOT_RELEASED", "Vault item is not released to this deputy")
    return ok(d.serialize_vault_item(item), 200)


@app.route("/legacy/vault-items/<item_id>/seal", methods=["POST"])
def seal_vault_item(item_id):
    ctx = begin({"Owner"})
    item = d.get_vault_item(item_id)
    check_scope(ctx, item["plan_id"])
    if item["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Item cannot be sealed from its current state")
    if item["kind"] == "ASSET":
        if item["gross_value_cents"] is None:
            raise ApiError("ERR_VALIDATION", "gross_value_cents is required to seal an ASSET")
        linked = [
            b for b in store.BENEFICIARIES.values()
            if b["asset_vault_item_id"] == item_id and b["status"] == "NOMINATED"
        ]
        total = sum(float(b["allocation_pct"]) for b in linked)
        if linked and total > 100:
            raise ApiError("ERR_ALLOCATION_EXCEEDS_100", "Beneficiary allocation exceeds 100%")
    item["status"] = "SEALED"
    store.touch(item)
    return ok(d.serialize_vault_item(item), 200)


@app.route("/legacy/vault-items/<item_id>/recall", methods=["POST"])
def recall_vault_item(item_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    item = d.get_vault_item(item_id)
    check_scope(ctx, item["plan_id"])
    if item["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Only a RELEASED item can be recalled")
    item["status"] = "SEALED"
    store.touch(item)
    if item["kind"] == "ASSET":
        for b in store.BENEFICIARIES.values():
            if b["asset_vault_item_id"] == item_id and b["status"] == "VESTED":
                b["status"] = "NOMINATED"
                b["allocated_value_cents"] = 0
                store.touch(b)
    return ok(d.serialize_vault_item(item), 200)


@app.route("/legacy/vault-items/<item_id>/archive", methods=["POST"])
def archive_vault_item(item_id):
    ctx = begin({"Owner"})
    item = d.get_vault_item(item_id)
    check_scope(ctx, item["plan_id"])
    if item["status"] not in ("DRAFT", "SEALED"):
        raise ApiError("ERR_INVALID_STATE", "Item cannot be archived from its current state")
    item["status"] = "ARCHIVED"
    store.touch(item)
    return ok(d.serialize_vault_item(item), 200)


# =============================================================================
# Deputy
# =============================================================================
@app.route("/legacy/deputies", methods=["POST"])
def create_deputy():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    deputy_role = req_enum(body, "deputy_role", d.DEPUTY_ROLES)
    access_scope = req_enum_array(body, "access_scope", d.VAULT_KINDS)
    release_trigger = req_enum(body, "release_trigger", d.RELEASE_TRIGGERS)
    start_at = req_dt(body, "authority_start_at")
    end_at = req_dt(body, "authority_end_at")
    consumes_seat = body.get("consumes_seat", True)
    if not isinstance(consumes_seat, bool):
        raise ApiError("ERR_VALIDATION", "consumes_seat must be a boolean")

    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])

    # Term overlap (priority 10)
    buffer = timedelta(days=7)
    for other in store.DEPUTIES.values():
        if (other["plan_id"] == plan_id
                and other["deputy_role"] == deputy_role
                and other["status"] != "REVOKED"):
            s2, e2 = other["authority_start_at"], other["authority_end_at"]
            gap_ok = (start_at > e2 + buffer) or (s2 > end_at + buffer)
            if not gap_ok:
                raise ApiError("ERR_DEPUTY_TERM_OVERLAP", "Deputy term overlaps an existing term")

    # Seat capacity (priority 11)
    if consumes_seat:
        used, limit, _ = d.seat_accounting(plan_id)
        if used >= limit:
            raise ApiError("ERR_SEAT_LIMIT_REACHED", "No seats available")

    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "full_name": full_name,
        "email": email,
        "deputy_role": deputy_role,
        "access_scope": access_scope,
        "release_trigger": release_trigger,
        "authority_start_at": start_at,
        "authority_end_at": end_at,
        "consumes_seat": consumes_seat,
        "status": "INVITED",
    })
    store.DEPUTIES[rec["id"]] = rec
    return ok(d.serialize_deputy(rec), 201)


@app.route("/legacy/deputies", methods=["GET"])
def list_deputies():
    ctx = begin({"Owner", "PlatformAdmin"})
    records = scoped_records(list(store.DEPUTIES.values()), ctx)
    plan_id = request.args.get("plan_id")
    deputy_role = request.args.get("deputy_role")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if deputy_role:
        records = [r for r in records if r["deputy_role"] == deputy_role]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_deputy)


@app.route("/legacy/deputies/<deputy_id>", methods=["GET"])
def get_deputy_ep(deputy_id):
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    dep = d.get_deputy(deputy_id)
    check_scope(ctx, dep["plan_id"])
    return ok(d.serialize_deputy(dep), 200)


@app.route("/legacy/deputies/<deputy_id>/accept", methods=["POST"])
def accept_deputy(deputy_id):
    ctx = begin({"Deputy"})
    dep = d.get_deputy(deputy_id)
    check_scope(ctx, dep["plan_id"])
    if dep["status"] != "INVITED":
        raise ApiError("ERR_INVALID_STATE", "Deputy cannot accept from its current state")
    dep["status"] = "ACCEPTED"
    store.touch(dep)
    return ok(d.serialize_deputy(dep), 200)


@app.route("/legacy/deputies/<deputy_id>/revoke", methods=["POST"])
def revoke_deputy(deputy_id):
    ctx = begin({"Owner"})
    dep = d.get_deputy(deputy_id)
    check_scope(ctx, dep["plan_id"])
    if dep["status"] not in ("INVITED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE", "Deputy cannot be revoked from its current state")
    dep["status"] = "REVOKED"
    store.touch(dep)
    # Cascade: PENDING/VERIFIED release requests by this deputy -> DENIED
    for r in store.RELEASE_REQUESTS.values():
        if (r["requested_by_deputy_id"] == deputy_id
                and r["status"] in ("PENDING", "VERIFIED")):
            r["status"] = "DENIED"
            store.touch(r)
    return ok(d.serialize_deputy(dep), 200)


# =============================================================================
# Beneficiary
# =============================================================================
@app.route("/legacy/beneficiaries", methods=["POST"])
def create_beneficiary():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    full_name = req_str(body, "full_name")
    relationship = req_str(body, "relationship")
    contact_email = opt_str(body, "contact_email", None)
    allocation_pct = opt_number(body, "allocation_pct", 0, min_value=0, max_value=100)
    parent_id = opt_str(body, "parent_beneficiary_id", None)
    asset_id = opt_str(body, "asset_vault_item_id", None)

    plan = d.get_plan(plan_id)
    parent = d.get_beneficiary(parent_id) if parent_id else None
    asset = d.get_vault_item(asset_id) if asset_id else None

    check_scope(ctx, plan["id"])

    if parent and parent["plan_id"] != plan_id:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE", "parent_beneficiary_id belongs to a different plan")
    if asset and asset["plan_id"] != plan_id:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE", "asset_vault_item_id belongs to a different plan")

    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "parent_beneficiary_id": parent_id,
        "asset_vault_item_id": asset_id,
        "full_name": full_name,
        "relationship": relationship,
        "contact_email": contact_email,
        "allocation_pct": allocation_pct,
        "allocated_value_cents": 0,
        "status": "NOMINATED",
    })
    store.BENEFICIARIES[rec["id"]] = rec
    return ok(d.serialize_beneficiary(rec), 201)


@app.route("/legacy/beneficiaries", methods=["GET"])
def list_beneficiaries():
    ctx = begin({"Owner", "PlatformAdmin"})
    records = scoped_records(list(store.BENEFICIARIES.values()), ctx)
    plan_id = request.args.get("plan_id")
    parent_id = request.args.get("parent_beneficiary_id")
    asset_id = request.args.get("asset_vault_item_id")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if parent_id:
        records = [r for r in records if r["parent_beneficiary_id"] == parent_id]
    if asset_id:
        records = [r for r in records if r["asset_vault_item_id"] == asset_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_beneficiary)


@app.route("/legacy/beneficiaries/<beneficiary_id>", methods=["GET"])
def get_beneficiary_ep(beneficiary_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    b = d.get_beneficiary(beneficiary_id)
    check_scope(ctx, b["plan_id"])
    return ok(d.serialize_beneficiary(b), 200)


@app.route("/legacy/beneficiaries/<beneficiary_id>/remove", methods=["POST"])
def remove_beneficiary(beneficiary_id):
    ctx = begin({"Owner"})
    b = d.get_beneficiary(beneficiary_id)
    check_scope(ctx, b["plan_id"])
    if b["status"] != "NOMINATED":
        raise ApiError("ERR_INVALID_STATE", "Beneficiary cannot be removed from its current state")
    b["status"] = "REMOVED"
    store.touch(b)
    return ok(d.serialize_beneficiary(b), 200)


# =============================================================================
# Directive
# =============================================================================
@app.route("/legacy/directives", methods=["POST"])
def create_directive():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    directive_type = req_enum(body, "directive_type", d.DIRECTIVE_TYPES)
    content = req_str(body, "content")
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])
    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "directive_type": directive_type,
        "content": content,
        "version_number": 1,
        "status": "DRAFT",
    })
    store.DIRECTIVES[rec["id"]] = rec
    return ok(d.serialize_directive(rec), 201)


@app.route("/legacy/directives", methods=["GET"])
def list_directives():
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    records = scoped_records(list(store.DIRECTIVES.values()), ctx)
    plan_id = request.args.get("plan_id")
    directive_type = request.args.get("directive_type")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if directive_type:
        records = [r for r in records if r["directive_type"] == directive_type]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_directive)


@app.route("/legacy/directives/<directive_id>", methods=["GET"])
def get_directive_ep(directive_id):
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    dr = d.get_directive(directive_id)
    check_scope(ctx, dr["plan_id"])
    return ok(d.serialize_directive(dr), 200)


@app.route("/legacy/directives/<directive_id>/activate", methods=["POST"])
def activate_directive(directive_id):
    ctx = begin({"Owner"})
    body = get_body()
    expected = req_int(body, "expected_plan_version")
    dr = d.get_directive(directive_id)
    check_scope(ctx, dr["plan_id"])
    if dr["status"] not in ("DRAFT", "UNDER_REVISION"):
        raise ApiError("ERR_INVALID_STATE", "Directive cannot be activated from its current state")
    plan = d.get_plan(dr["plan_id"])
    if plan["life_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Cannot activate a directive unless the plan is ACTIVE")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_plan_version does not match the plan version")

    # Supersede any other ACTIVE directive of the same type
    for other in store.DIRECTIVES.values():
        if (other["id"] != dr["id"]
                and other["plan_id"] == dr["plan_id"]
                and other["directive_type"] == dr["directive_type"]
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            store.touch(other)

    dr["status"] = "ACTIVE"
    store.touch(dr)
    store.touch(plan)  # increments Plan.version
    return ok(d.serialize_directive(dr), 200)


@app.route("/legacy/directives/<directive_id>/revise", methods=["POST"])
def revise_directive(directive_id):
    ctx = begin({"Owner"})
    dr = d.get_directive(directive_id)
    check_scope(ctx, dr["plan_id"])
    if dr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE directive can be revised")
    dr["status"] = "UNDER_REVISION"
    dr["version_number"] += 1
    store.touch(dr)
    return ok(d.serialize_directive(dr), 200)


@app.route("/legacy/directives/<directive_id>/revoke", methods=["POST"])
def revoke_directive(directive_id):
    ctx = begin({"Owner"})
    dr = d.get_directive(directive_id)
    check_scope(ctx, dr["plan_id"])
    if dr["status"] not in ("DRAFT", "ACTIVE", "UNDER_REVISION"):
        raise ApiError("ERR_INVALID_STATE", "Directive cannot be revoked from its current state")
    dr["status"] = "REVOKED"
    store.touch(dr)
    return ok(d.serialize_directive(dr), 200)


# =============================================================================
# ReleaseRequest
# =============================================================================
@app.route("/legacy/release-requests", methods=["POST"])
def create_release_request():
    ctx = begin({"Deputy"})
    role, uid = ctx
    body = get_body()
    plan_id = req_str(body, "plan_id")
    trigger_type = req_enum(body, "trigger_type", d.RR_TRIGGERS)
    scope_kinds = req_enum_array(body, "scope_kinds", d.VAULT_KINDS)
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])  # deputy must serve this plan
    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "requested_by_deputy_id": uid,
        "trigger_type": trigger_type,
        "scope_kinds": scope_kinds,
        "required_approvals": 0,
        "approval_count": 0,
        "approver_deputy_ids": [],
        "expires_at": None,
        "status": "PENDING",
    })
    store.RELEASE_REQUESTS[rec["id"]] = rec
    return ok(d.serialize_release_request(rec), 201)


@app.route("/legacy/release-requests", methods=["GET"])
def list_release_requests():
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    records = scoped_records(list(store.RELEASE_REQUESTS.values()), ctx)
    plan_id = request.args.get("plan_id")
    req_by = request.args.get("requested_by_deputy_id")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if req_by:
        records = [r for r in records if r["requested_by_deputy_id"] == req_by]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_release_request)


@app.route("/legacy/release-requests/<release_request_id>", methods=["GET"])
def get_release_request_ep(release_request_id):
    ctx = begin({"Owner", "PlatformAdmin", "Deputy"})
    r = d.get_release_request(release_request_id)
    check_scope(ctx, r["plan_id"])
    return ok(d.serialize_release_request(r), 200)


@app.route("/legacy/release-requests/<release_request_id>/verify", methods=["POST"])
def verify_release_request(release_request_id):
    ctx = begin({"PlatformAdmin"})
    r = d.get_release_request(release_request_id)
    if r["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING request can be verified")
    plan = store.PLANS.get(r["plan_id"])
    life = plan["life_status"] if plan else "ACTIVE"
    ok_trigger = (
        (r["trigger_type"] == "ON_DEATH" and life == "DECEASED")
        or (r["trigger_type"] == "ON_INCAPACITY" and life in ("INCAPACITATED", "DECEASED"))
    )
    if not ok_trigger:
        raise ApiError("ERR_RELEASE_NOT_TRIGGERED", "Plan life status does not satisfy the trigger")

    accepted = d.accepted_deputy_count(r["plan_id"])
    required = max(1, math.ceil(accepted * float(d.QUORUM_FRACTION)))
    r["required_approvals"] = required
    r["expires_at"] = store.now() + timedelta(days=14)
    r["status"] = "VERIFIED"
    store.touch(r)
    return ok(d.serialize_release_request(r), 200)


@app.route("/legacy/release-requests/<release_request_id>/approve", methods=["POST"])
def approve_release_request(release_request_id):
    ctx = begin({"Deputy"})
    role, uid = ctx
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    opt_str(body, "note", None)
    r = d.get_release_request(release_request_id)
    check_scope(ctx, r["plan_id"])
    if r["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", "Only a VERIFIED request can be voted on")
    if uid in r["approver_deputy_ids"]:
        raise ApiError("ERR_DUPLICATE_APPROVAL", "Deputy has already voted on this request")

    r["approver_deputy_ids"].append(uid)
    if decision == "APPROVE":
        r["approval_count"] += 1
        if r["approval_count"] >= r["required_approvals"]:
            r["status"] = "APPROVED"
    else:  # REJECT vetoes
        r["status"] = "DENIED"
    store.touch(r)
    return ok(d.serialize_release_request(r), 200)


@app.route("/legacy/release-requests/<release_request_id>/deny", methods=["POST"])
def deny_release_request(release_request_id):
    ctx = begin({"PlatformAdmin"})
    r = d.get_release_request(release_request_id)
    if r["status"] not in ("PENDING", "VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", "Request cannot be denied from its current state")
    r["status"] = "DENIED"
    store.touch(r)
    return ok(d.serialize_release_request(r), 200)


@app.route("/legacy/release-requests/<release_request_id>/grant", methods=["POST"])
def grant_release_request(release_request_id):
    ctx = begin({"PlatformAdmin"})
    r = d.get_release_request(release_request_id)

    if r["status"] == "VERIFIED":
        raise ApiError("ERR_QUORUM_NOT_MET", "Quorum has not been met for this request")
    if r["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED request can be granted")

    sealed_in_scope = [
        v for v in store.VAULT_ITEMS.values()
        if v["plan_id"] == r["plan_id"]
        and v["status"] == "SEALED"
        and v["kind"] in r["scope_kinds"]
    ]
    if not sealed_in_scope:
        raise ApiError("ERR_NOTHING_TO_RELEASE", "No sealed in-scope vault items to release")

    sub = d.plan_subscription(r["plan_id"])
    if sub and sub["status"] == "PAST_DUE":
        raise ApiError("ERR_SUBSCRIPTION_PAST_DUE", "Subscription is past due")

    r["status"] = "GRANTED"
    store.touch(r)
    # Cascade link 1: release sealed in-scope items; link 2: vest asset beneficiaries
    for v in sorted(sealed_in_scope, key=lambda x: (x["created_at"], x["_seq"])):
        v["status"] = "RELEASED"
        store.touch(v)
        if v["kind"] == "ASSET":
            d.beneficiary_allocation(v)
    return ok(d.serialize_release_request(r), 200)


# =============================================================================
# Subscription
# =============================================================================
@app.route("/legacy/subscriptions", methods=["POST"])
def create_subscription():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    tier = req_enum(body, "tier", d.SUB_TIERS)
    refund_policy = opt_enum(body, "refund_policy", d.REFUND_POLICIES, "IMMEDIATE_PRORATA")
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])
    start = store.now()
    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "tier": tier,
        "refund_policy": refund_policy,
        "seat_limit": d.SEAT_LIMITS[tier],
        "monthly_fee_cents": d.MONTHLY_FEES[tier],
        "period_start": start,
        "period_end": start + timedelta(days=30),
        "last_refund_cents": 0,
        "status": "TRIALING",
    })
    store.SUBSCRIPTIONS[rec["id"]] = rec
    return ok(d.serialize_subscription(rec), 201)


@app.route("/legacy/subscriptions", methods=["GET"])
def list_subscriptions():
    ctx = begin({"Owner", "PlatformAdmin"})
    records = scoped_records(list(store.SUBSCRIPTIONS.values()), ctx)
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_subscription)


@app.route("/legacy/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription_ep(subscription_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    s = d.get_subscription(subscription_id)
    check_scope(ctx, s["plan_id"])
    return ok(d.serialize_subscription(s), 200)


@app.route("/legacy/subscriptions/<subscription_id>/cancel", methods=["POST"])
def cancel_subscription(subscription_id):
    ctx = begin({"Owner"})
    s = d.get_subscription(subscription_id)
    check_scope(ctx, s["plan_id"])
    if s["status"] not in ("TRIALING", "ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE", "Subscription cannot be canceled from its current state")
    refund = d.subscription_refund(s)
    s["last_refund_cents"] = refund
    s["status"] = "CANCELED"
    store.touch(s)
    # Cascade: ACTIVE shares -> REVOKED
    for sh in store.SHARES.values():
        if sh["plan_id"] == s["plan_id"] and sh["status"] == "ACTIVE":
            sh["status"] = "REVOKED"
            store.touch(sh)
    return ok(d.serialize_subscription(s), 200)


@app.route("/legacy/subscriptions/<subscription_id>/record-payment", methods=["POST"])
def record_payment(subscription_id):
    ctx = begin({"PlatformAdmin"})
    body = get_body()
    outcome = req_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    s = d.get_subscription(subscription_id)
    if s["status"] == "CANCELED":
        raise ApiError("ERR_INVALID_STATE", "Subscription is canceled")

    if outcome == "SUCCEEDED":
        clock = store.now()
        new_start = s["period_end"] if s["period_end"] > clock else clock
        s["period_start"] = new_start
        s["period_end"] = new_start + timedelta(days=30)
        s["status"] = "ACTIVE"
        store.touch(s)
    else:  # FAILED
        if s["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE subscription can move to PAST_DUE")
        s["status"] = "PAST_DUE"
        store.touch(s)
    return ok(d.serialize_subscription(s), 200)


# =============================================================================
# Share
# =============================================================================
@app.route("/legacy/shares", methods=["POST"])
def create_share():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    scope = req_enum(body, "scope", d.SHARE_SCOPES)
    shared_with_email = req_str(body, "shared_with_email")
    effective_at = req_dt(body, "effective_at")
    expires_at = req_dt(body, "expires_at")
    vault_item_id = opt_str(body, "vault_item_id", None)
    if scope == "ITEM" and not vault_item_id:
        raise ApiError("ERR_VALIDATION", "vault_item_id is required when scope is ITEM")

    plan = d.get_plan(plan_id)
    item = d.get_vault_item(vault_item_id) if vault_item_id else None
    check_scope(ctx, plan["id"])

    if item and item["plan_id"] != plan_id:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE", "vault_item_id belongs to a different plan")

    # Window overlap (priority 10)
    for other in store.SHARES.values():
        if (other["plan_id"] == plan_id
                and other["status"] == "ACTIVE"
                and other["vault_item_id"] == vault_item_id
                and other["shared_with_email"] == shared_with_email):
            if effective_at < other["expires_at"] and other["effective_at"] < expires_at:
                raise ApiError("ERR_SHARE_WINDOW_OVERLAP", "Share window overlaps an existing active share")

    # Paid subscription required
    sub = d.plan_subscription(plan_id)
    if not sub or sub["tier"] == "FREE" or sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_REQUIRED", "External sharing requires an active paid subscription")

    # Seat capacity
    used, limit, _ = d.seat_accounting(plan_id)
    if used >= limit:
        raise ApiError("ERR_SEAT_LIMIT_REACHED", "No seats available")

    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "vault_item_id": vault_item_id,
        "shared_with_email": shared_with_email,
        "scope": scope,
        "effective_at": effective_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
    })
    store.SHARES[rec["id"]] = rec
    return ok(d.serialize_share(rec), 201)


@app.route("/legacy/shares", methods=["GET"])
def list_shares():
    ctx = begin({"Owner", "PlatformAdmin"})
    records = scoped_records(list(store.SHARES.values()), ctx)
    plan_id = request.args.get("plan_id")
    vault_item_id = request.args.get("vault_item_id")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if vault_item_id:
        records = [r for r in records if r["vault_item_id"] == vault_item_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_share)


@app.route("/legacy/shares/<share_id>", methods=["GET"])
def get_share_ep(share_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    s = d.get_share(share_id)
    check_scope(ctx, s["plan_id"])
    return ok(d.serialize_share(s), 200)


@app.route("/legacy/shares/<share_id>/revoke", methods=["POST"])
def revoke_share(share_id):
    ctx = begin({"Owner"})
    s = d.get_share(share_id)
    check_scope(ctx, s["plan_id"])
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE share can be revoked")
    s["status"] = "REVOKED"
    store.touch(s)
    return ok(d.serialize_share(s), 200)


# =============================================================================
# Integration
# =============================================================================
@app.route("/legacy/integrations", methods=["POST"])
def create_integration():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    provider_type = req_enum(body, "provider_type", d.PROVIDER_TYPES)
    provider_name = req_str(body, "provider_name")
    external_ref = req_str(body, "external_ref")
    coverage_cents = opt_int(body, "coverage_cents", 0, min_value=0)
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])
    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "provider_type": provider_type,
        "provider_name": provider_name,
        "external_ref": external_ref,
        "coverage_cents": coverage_cents,
        "last_synced_at": None,
        "sync_status": "LINKED",
    })
    store.INTEGRATIONS[rec["id"]] = rec
    return ok(d.serialize_integration(rec), 201)


@app.route("/legacy/integrations", methods=["GET"])
def list_integrations():
    ctx = begin({"Owner", "PlatformAdmin"})
    records = scoped_records(list(store.INTEGRATIONS.values()), ctx)
    plan_id = request.args.get("plan_id")
    provider_type = request.args.get("provider_type")
    sync_status = request.args.get("sync_status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if provider_type:
        records = [r for r in records if r["provider_type"] == provider_type]
    if sync_status:
        records = [r for r in records if r["sync_status"] == sync_status]
    return finalize_list(records, d.serialize_integration)


@app.route("/legacy/integrations/<integration_id>", methods=["GET"])
def get_integration_ep(integration_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    i = d.get_integration(integration_id)
    check_scope(ctx, i["plan_id"])
    return ok(d.serialize_integration(i), 200)


@app.route("/legacy/integrations/<integration_id>/sync", methods=["POST"])
def sync_integration(integration_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    i = d.get_integration(integration_id)
    check_scope(ctx, i["plan_id"])
    if i["sync_status"] != "LINKED":
        raise ApiError("ERR_INVALID_STATE", "Integration cannot be synced from its current state")
    # LINKED -> SYNCING -> LINKED within the same request
    i["last_synced_at"] = store.now()
    i["sync_status"] = "LINKED"
    store.touch(i)
    return ok(d.serialize_integration(i), 200)


# =============================================================================
# ReviewReminder
# =============================================================================
@app.route("/legacy/review-reminders", methods=["POST"])
def create_reminder():
    ctx = begin({"Owner"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    subject_kind = req_enum(body, "subject_kind", d.SUBJECT_KINDS)
    interval_days = opt_int(body, "interval_days", 180, min_value=1)
    last_reviewed_at = req_dt(body, "last_reviewed_at")
    plan = d.get_plan(plan_id)
    check_scope(ctx, plan["id"])
    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "subject_kind": subject_kind,
        "interval_days": interval_days,
        "last_reviewed_at": last_reviewed_at,
        "due_at": last_reviewed_at + timedelta(days=interval_days),
        "status": "SCHEDULED",
    })
    store.REVIEW_REMINDERS[rec["id"]] = rec
    return ok(d.serialize_reminder(rec), 201)


@app.route("/legacy/review-reminders", methods=["GET"])
def list_reminders():
    ctx = begin({"Owner", "PlatformAdmin"})
    records = scoped_records(list(store.REVIEW_REMINDERS.values()), ctx)
    plan_id = request.args.get("plan_id")
    subject_kind = request.args.get("subject_kind")
    status = request.args.get("status")
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if subject_kind:
        records = [r for r in records if r["subject_kind"] == subject_kind]
    if status:
        records = [r for r in records if r["status"] == status]
    return finalize_list(records, d.serialize_reminder)


@app.route("/legacy/review-reminders/<reminder_id>", methods=["GET"])
def get_reminder_ep(reminder_id):
    ctx = begin({"Owner", "PlatformAdmin"})
    r = d.get_reminder(reminder_id)
    check_scope(ctx, r["plan_id"])
    return ok(d.serialize_reminder(r), 200)


@app.route("/legacy/review-reminders/<reminder_id>/complete", methods=["POST"])
def complete_reminder(reminder_id):
    ctx = begin({"Owner"})
    r = d.get_reminder(reminder_id)
    check_scope(ctx, r["plan_id"])
    if r["status"] not in ("SCHEDULED", "DUE", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", "Reminder cannot be completed from its current state")
    clock = store.now()
    r["status"] = "COMPLETED"
    r["last_reviewed_at"] = clock
    r["due_at"] = clock + timedelta(days=r["interval_days"])
    store.touch(r)
    return ok(d.serialize_reminder(r), 200)


# =============================================================================
# Ops / clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_ep():
    ctx = begin({"PlatformAdmin"})
    body = get_body()
    dt = req_dt(body, "to_iso8601")
    store.set_clock(dt)
    return ok({}, 200)


@app.route("/_ops/run-review-sweep", methods=["POST"])
def run_review_sweep():
    ctx = begin({"PlatformAdmin"})
    body = get_body()
    plan_id = req_str(body, "plan_id")
    plan = d.get_plan(plan_id)
    clock = store.now()
    grace = timedelta(days=d.GRACE_DAYS)

    # Review reminders reclassification
    for r in store.REVIEW_REMINDERS.values():
        if r["plan_id"] != plan_id or r["status"] not in ("SCHEDULED", "DUE", "OVERDUE"):
            continue
        due = r["due_at"]
        if clock < due:
            new = "SCHEDULED"
        elif clock < due + grace:
            new = "DUE"
        else:
            new = "OVERDUE"
        if new != r["status"]:
            r["status"] = new
            store.touch(r)

    # Active shares past expiry -> EXPIRED
    for sh in store.SHARES.values():
        if sh["plan_id"] == plan_id and sh["status"] == "ACTIVE" and clock >= sh["expires_at"]:
            sh["status"] = "EXPIRED"
            store.touch(sh)

    # Open release requests past expiry -> EXPIRED
    for rr in store.RELEASE_REQUESTS.values():
        if (rr["plan_id"] == plan_id and rr["status"] in ("PENDING", "VERIFIED")
                and rr["expires_at"] is not None and clock >= rr["expires_at"]):
            rr["status"] = "EXPIRED"
            store.touch(rr)

    return ok(d.serialize_plan(plan), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
