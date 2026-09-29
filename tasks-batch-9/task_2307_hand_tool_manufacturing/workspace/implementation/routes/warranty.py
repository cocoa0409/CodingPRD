"""WarrantyProgram, Claimant, WarrantyClaim and ClaimLine endpoints (PRD §3.7, §3.8)."""

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import ensure_unique_code, listing
from serialize import claim_line_out, claim_out, claimant_out, program_out
from store import base_row, store, touch, with_common
from validate import (auth, claimant_identity, filter_arg, get_body, lookup, req_enum, req_int,
                     req_str, require_present, resolve_ref)

warranty_bp = Blueprint("warranty", __name__)

WA = ["WarrantyAdministrator", "PlatformAdmin"]


# --------------------------------------------------------------------------- #
# WarrantyProgram
# --------------------------------------------------------------------------- #
@warranty_bp.post("/toolworks/warranty-programs")
def create_program():
    auth(*WA)
    body = get_body()
    program_code = req_str(body, "program_code")
    reserve_funded_cents = req_int(body, "reserve_funded_cents", 0)
    fraud_score_threshold = req_int(body, "fraud_score_threshold", 1, 100)
    ensure_unique_code(store.programs, "program_code", program_code)

    row = with_common(base_row(
        program_code=program_code,
        reserve_funded_cents=reserve_funded_cents,
        fraud_score_threshold=fraud_score_threshold,
        reserve_balance_cents=reserve_funded_cents,
        open_hold_count=0,
    ))
    store.programs[row["id"]] = row
    return ok(program_out(row), 201)


@warranty_bp.get("/toolworks/warranty-programs")
def list_programs():
    auth("WarrantyAdministrator", "ChannelManager", "PlatformAdmin")
    items, limit, offset, total = listing(list(store.programs.values()), program_out)
    return ok_list(items, limit, offset, total)


@warranty_bp.get("/toolworks/warranty-programs/<id>")
def get_program(id):
    auth("WarrantyAdministrator", "ChannelManager", "PlatformAdmin")
    row = lookup(store.programs, id, "ERR_WARRANTY_PROGRAM_NOT_FOUND")
    return ok(program_out(row))


# --------------------------------------------------------------------------- #
# Claimant
# --------------------------------------------------------------------------- #
@warranty_bp.post("/toolworks/claimants")
def create_claimant():
    auth(*WA)
    body = get_body()
    email = req_str(body, "email")
    claimant_type = req_enum(body, "claimant_type", calc.CLAIMANT_TYPES)
    ensure_unique_code(store.claimants, "email", email)

    row = with_common(base_row(
        email=email,
        claimant_type=claimant_type,
        status="ACTIVE",
        fraud_risk_score_intake=0,
        fraud_risk_score_adjudication=0,
        lifetime_claim_count=0,
    ))
    store.claimants[row["id"]] = row
    return ok(claimant_out(row), 201)


@warranty_bp.get("/toolworks/claimants")
def list_claimants():
    auth(*WA)
    filters = {"status": filter_arg("status"), "claimant_type": filter_arg("claimant_type")}
    items, limit, offset, total = listing(list(store.claimants.values()), claimant_out, filters)
    return ok_list(items, limit, offset, total)


@warranty_bp.get("/toolworks/claimants/<id>")
def get_claimant(id):
    auth("WarrantyAdministrator", "Claimant", "PlatformAdmin")
    row = lookup(store.claimants, id, "ERR_CLAIMANT_NOT_FOUND")
    return ok(claimant_out(row))


@warranty_bp.post("/toolworks/claimants/<id>/block")
def block_claimant(id):
    auth(*WA)
    row = lookup(store.claimants, id, "ERR_CLAIMANT_NOT_FOUND")
    body = get_body()
    req_str(body, "block_reason")

    if row["status"] != "ACTIVE":
        raise ApiError("ERR_CLAIMANT_STATE_INVALID")

    row["status"] = "BLOCKED"
    touch(row)
    return ok(claimant_out(row))


# --------------------------------------------------------------------------- #
# WarrantyClaim
# --------------------------------------------------------------------------- #
@warranty_bp.post("/toolworks/warranty-claims")
def create_claim():
    role, user_id = auth("Claimant", "WarrantyAdministrator", "PlatformAdmin")
    body = get_body()

    if role == "Claimant":
        claimant_identity(role, user_id)
        quoted = body.get("claimant_id")
        if isinstance(quoted, str) and quoted != user_id:
            raise ApiError("ERR_CLAIMANT_MISMATCH")

    sku = resolve_ref(body, "sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")
    claimant = resolve_ref(body, "claimant_id", store.claimants, "ERR_CLAIMANT_NOT_FOUND")
    program = resolve_ref(body, "program_id", store.programs, "ERR_WARRANTY_PROGRAM_NOT_FOUND")

    require_present(claimant, "claimant_id")
    require_present(sku, "sku_id")
    require_present(program, "program_id")
    serial_code = req_str(body, "serial_code")
    claim_reason = req_enum(body, "claim_reason", calc.CLAIM_REASONS)

    if claimant["status"] == "BLOCKED":
        raise ApiError("ERR_CLAIMANT_BLOCKED")

    if sku["warranty_tier"] == "NONE":
        raise ApiError("ERR_WARRANTY_TIER_NOT_COVERED")

    for existing in svc.claimant_claims(claimant["id"]):
        if (existing["sku_id"] == sku["id"] and existing["serial_code"] == serial_code
                and existing["status"] in ("SUBMITTED", "FRAUD_HOLD", "APPROVED")):
            raise ApiError("ERR_DUPLICATE_OPEN_CLAIM")

    score = svc.intake_fraud_score(claimant, serial_code)
    held = score >= program["fraud_score_threshold"]

    row = with_common(base_row(
        claimant_id=claimant["id"],
        sku_id=sku["id"],
        program_id=program["id"],
        serial_code=serial_code,
        claim_reason=claim_reason,
        status="FRAUD_HOLD" if held else "SUBMITTED",
        fraud_score_at_intake=score,
        reserve_charge_cents=0,
        replacement_unit_count=0,
        line_count=0,
        hold_reason="INTAKE_FRAUD_SCORE" if held else None,
        held_by_user_id=None,
        fraud_cleared=False,
        denial_code=None,
        shipment_ref=None,
        revocation_reason=None,
    ))
    store.claims[row["id"]] = row

    claimant["fraud_risk_score_intake"] = score
    svc.refresh_lifetime_count(claimant)
    touch(claimant)

    if held:
        svc.recompute_reserve(program)
        touch(program)

    return ok(claim_out(row), 201)


@warranty_bp.get("/toolworks/warranty-claims")
def list_claims():
    auth("WarrantyAdministrator", "BrandProtectionAnalyst", "ChannelManager", "PlatformAdmin")
    filters = {
        "claimant_id": filter_arg("claimant_id"),
        "sku_id": filter_arg("sku_id"),
        "program_id": filter_arg("program_id"),
        "status": filter_arg("status"),
    }
    items, limit, offset, total = listing(list(store.claims.values()), claim_out, filters)
    return ok_list(items, limit, offset, total)


@warranty_bp.get("/toolworks/warranty-claims/<id>")
def get_claim(id):
    role, user_id = auth("WarrantyAdministrator", "Claimant", "BrandProtectionAnalyst",
                         "PlatformAdmin")
    claimant_identity(role, user_id)
    row = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    if role == "Claimant" and row["claimant_id"] != user_id:
        raise ApiError("ERR_CLAIMANT_MISMATCH")
    return ok(claim_out(row))


@warranty_bp.post("/toolworks/warranty-claims/<id>/lines")
def add_claim_line(id):
    role, user_id = auth("Claimant", "WarrantyAdministrator", "PlatformAdmin")
    claimant_identity(role, user_id)
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    if role == "Claimant" and claim["claimant_id"] != user_id:
        raise ApiError("ERR_CLAIMANT_MISMATCH")

    body = get_body()
    component_code = req_str(body, "component_code")
    component_list_price_cents = req_int(body, "component_list_price_cents", 1)
    quantity = req_int(body, "quantity", 1)

    if claim["status"] not in ("SUBMITTED", "FRAUD_HOLD"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    sku = store.skus[claim["sku_id"]]
    row = base_row(
        claim_id=claim["id"],
        component_code=component_code,
        component_list_price_cents=component_list_price_cents,
        quantity=quantity,
        line_reserve_cents=calc.line_reserve_cents(component_list_price_cents, quantity, sku),
    )
    store.claim_lines[row["id"]] = row

    svc.recompute_claim_rollups(claim)
    touch(claim)
    return ok(claim_line_out(row), 201)


@warranty_bp.get("/toolworks/warranty-claims/<id>/lines")
def list_claim_lines(id):
    auth("WarrantyAdministrator", "Claimant", "PlatformAdmin")
    lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    rows = [l for l in store.claim_lines.values() if l["claim_id"] == id]
    items, limit, offset, total = listing(rows, claim_line_out)
    return ok_list(items, limit, offset, total)


@warranty_bp.post("/toolworks/warranty-claims/<id>/hold")
def hold_claim(id):
    role, user_id = auth("WarrantyAdministrator", "BrandProtectionAnalyst", "PlatformAdmin")
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    hold_reason = req_str(body, "hold_reason")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "FRAUD_HOLD"
    claim["hold_reason"] = hold_reason
    claim["held_by_user_id"] = user_id
    touch(claim)

    program = store.programs[claim["program_id"]]
    svc.recompute_reserve(program)
    touch(program)

    claimant = store.claimants[claim["claimant_id"]]
    svc.refresh_adjudication(claimant)
    return ok(claim_out(claim))


@warranty_bp.post("/toolworks/warranty-claims/<id>/clear-hold")
def clear_hold(id):
    role, user_id = auth(*WA)
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    req_str(body, "clearance_note")

    if claim["status"] != "FRAUD_HOLD":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if claim["held_by_user_id"] is not None and claim["held_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["status"] = "SUBMITTED"
    claim["fraud_cleared"] = True
    claim["hold_reason"] = None
    touch(claim)

    program = store.programs[claim["program_id"]]
    svc.recompute_reserve(program)
    touch(program)

    claimant = store.claimants[claim["claimant_id"]]
    svc.refresh_adjudication(claimant)
    return ok(claim_out(claim))


@warranty_bp.post("/toolworks/warranty-claims/<id>/approve")
def approve_claim(id):
    role, user_id = auth(*WA)
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    expected_program_version = req_int(body, "expected_program_version")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    program = store.programs[claim["program_id"]]
    if expected_program_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")

    sku = store.skus[claim["sku_id"]]
    if sku["warranty_posture"] != "OPEN":
        raise ApiError("ERR_SKU_WARRANTY_RESTRICTED")

    svc.recompute_claim_rollups(claim)

    if sku["units_on_hand"] < claim["replacement_unit_count"]:
        raise ApiError("ERR_REPLACEMENT_STOCK_INSUFFICIENT")
    if program["reserve_balance_cents"] < claim["reserve_charge_cents"]:
        raise ApiError("ERR_RESERVE_INSUFFICIENT")

    claimant = store.claimants[claim["claimant_id"]]
    if not claim["fraud_cleared"]:
        if claimant["fraud_risk_score_adjudication"] >= program["fraud_score_threshold"]:
            raise ApiError("ERR_FRAUD_SCORE_TOO_HIGH")

    if claim["line_count"] < 1:
        raise ApiError("ERR_CLAIM_HAS_NO_LINES")

    if claim["held_by_user_id"] is not None and claim["held_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["status"] = "APPROVED"
    touch(claim)

    svc.recompute_units(sku)
    touch(sku)

    svc.recompute_reserve(program)
    touch(program)

    svc.refresh_adjudication(claimant)
    return ok(claim_out(claim))


@warranty_bp.post("/toolworks/warranty-claims/<id>/deny")
def deny_claim(id):
    auth(*WA)
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    denial_code = req_str(body, "denial_code")

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "DENIED"
    claim["denial_code"] = denial_code
    touch(claim)

    claimant = store.claimants[claim["claimant_id"]]
    svc.refresh_adjudication(claimant)
    return ok(claim_out(claim))


@warranty_bp.post("/toolworks/warranty-claims/<id>/deny-fraud")
def deny_claim_fraud(id):
    auth("WarrantyAdministrator", "BrandProtectionAnalyst", "PlatformAdmin")
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    denial_code = req_str(body, "denial_code")

    if claim["status"] != "FRAUD_HOLD":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "DENIED_FRAUD"
    claim["denial_code"] = denial_code
    touch(claim)

    program = store.programs[claim["program_id"]]
    svc.recompute_reserve(program)
    touch(program)

    claimant = store.claimants[claim["claimant_id"]]
    svc.refresh_adjudication(claimant)
    return ok(claim_out(claim))


@warranty_bp.post("/toolworks/warranty-claims/<id>/fulfill")
def fulfill_claim(id):
    auth(*WA)
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    shipment_ref = req_str(body, "shipment_ref")

    if claim["status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "FULFILLED"
    claim["shipment_ref"] = shipment_ref
    touch(claim)

    sku = store.skus[claim["sku_id"]]
    svc.recompute_units(sku)
    touch(sku)
    return ok(claim_out(claim))


@warranty_bp.post("/toolworks/warranty-claims/<id>/revoke")
def revoke_claim(id):
    auth("WarrantyAdministrator", "BrandProtectionAnalyst", "PlatformAdmin")
    claim = lookup(store.claims, id, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    revocation_reason = req_str(body, "revocation_reason")

    if claim["status"] not in ("APPROVED", "FULFILLED"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "REVOKED"
    claim["revocation_reason"] = revocation_reason
    touch(claim)

    sku = store.skus[claim["sku_id"]]
    svc.recompute_units(sku)
    touch(sku)

    program = store.programs[claim["program_id"]]
    svc.recompute_reserve(program)
    touch(program)

    claimant = store.claimants[claim["claimant_id"]]
    svc.refresh_adjudication(claimant)
    return ok(claim_out(claim))
