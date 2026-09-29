"""Licensees, surety bonds, the ledger, payments and the computed reads."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT,
                        LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("licensees", __name__, url_prefix="/mft")


@bp.post("/licensees")
def register_licensee():
    middleware.require(LICENSING_OFFICER)
    body = shape.body()
    legal_name = shape.req_str(body, "legal_name", 1, 120)
    fein = shape.req_pattern(body, "fein", shape.FEIN_RE)
    license_type = shape.req_enum(body, "license_type", calc.LICENSE_TYPES)
    mailing_state = shape.req_pattern(body, "mailing_state", shape.STATE_RE)
    gross_net_election = shape.opt_enum(body, "gross_net_election",
                                       calc.GROSS_NET_ELECTIONS, "NET")
    retail_channel = shape.opt_enum(body, "retail_channel",
                                    calc.RETAIL_CHANNELS, "NOT_APPLICABLE")
    parent_id = shape.opt_id(body, "parent_licensee_id")

    parent = helpers.body_licensee(parent_id) if parent_id else None

    for existing in db.licensees.values():
        if existing["fein"] == fein:
            raise ApiError("ERR_DUPLICATE_FEIN")

    if parent is not None:
        if (parent["license_type"] != "SUPPLIER"
                or parent["status"] != "ACTIVE"
                or parent["parent_licensee_id"] is not None):
            raise ApiError("ERR_INVALID_PARENT_LICENSEE")

    row = db.base_row()
    row.update({
        "legal_name": legal_name,
        "fein": fein,
        "license_type": license_type,
        "mailing_state": mailing_state,
        "status": "PENDING_BOND",
        "parent_licensee_id": parent_id,
        "gross_net_election": gross_net_election,
        "retail_channel": retail_channel,
    })
    db.licensees[row["id"]] = row
    return response.object_response(derive.licensee_json(row), 201)


@bp.get("/licensees/<licensee_id>")
def read_licensee(licensee_id):
    user_id, role = middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER,
                                       TAX_SUPERVISOR, AUDIT_MANAGER,
                                       FIELD_INSPECTOR, LICENSEE_AGENT)
    row = helpers.maybe("licensee", licensee_id)
    if row is not None:
        middleware.scope_guard(user_id, role, row["id"])
    row = helpers.find("licensee", licensee_id)
    return response.object_response(derive.licensee_json(row))


@bp.get("/licensees")
def list_licensees():
    # The licensee list is closed to LicenseeAgent entirely (PRD section 4).
    middleware.require(*middleware.ALL_STAFF)
    rows = db.ordered(db.licensees)
    rows = helpers.filter_by(rows, {
        "license_type": "license_type",
        "status": "status",
        "parent_licensee_id": "parent_licensee_id",
    })
    return response.list_response(rows, derive.licensee_json)


@bp.post("/licensees/<licensee_id>/activate")
def activate_licensee(licensee_id):
    middleware.require(LICENSING_OFFICER)
    row = helpers.ensure("licensee", helpers.maybe("licensee", licensee_id))
    if row["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")
    if row["status"] not in ("PENDING_BOND", "SUSPENDED"):
        raise ApiError("ERR_LICENSEE_STATE_INVALID")
    if derive.dyed_violation_count(row["id"]) >= calc.DYED_SUSPENSION_THRESHOLD:
        raise ApiError("ERR_DYED_VIOLATION_HOLD")
    # Evaluated with the suspension multiplier still in force.
    if derive.bond_position(row)["bond_deficiency_cents"] > 0:
        raise ApiError("ERR_BOND_DEFICIENCY_BLOCKS_ACTIVATION")

    row["status"] = "ACTIVE"
    db.touch(row)
    # The bond requirement is now recomputed with the multiplier back at 1.0.
    cascade.release_holds(row["id"], "BOND_DEFICIENCY")
    return response.object_response(derive.licensee_json(row))


@bp.post("/licensees/<licensee_id>/suspend")
def suspend_licensee(licensee_id):
    middleware.require(LICENSING_OFFICER, TAX_SUPERVISOR)
    peeked = helpers.maybe("licensee", licensee_id)
    body = shape.body()
    shape.req_str(body, "reason")
    row = helpers.ensure("licensee", peeked)
    if row["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSEE_STATE_INVALID")

    row["status"] = "SUSPENDED"
    db.touch(row)
    # The requirement now doubles; a resulting deficiency freezes claims.
    cascade.apply_bond_deficiency_hold(row)
    return response.object_response(derive.licensee_json(row))


@bp.post("/licensees/<licensee_id>/revoke")
def revoke_licensee(licensee_id):
    middleware.require(LICENSING_OFFICER)
    peeked = helpers.maybe("licensee", licensee_id)
    body = shape.body()
    shape.req_str(body, "reason")
    row = helpers.ensure("licensee", peeked)
    if row["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_STATE_INVALID")

    row["status"] = "REVOKED"
    db.touch(row)
    for bond in db.ordered(db.bonds):
        if bond["licensee_id"] == row["id"] and bond["status"] == "ACTIVE":
            bond["status"] = "FORFEITED"
            bond["release_reason"] = "LICENSE_REVOKED"
            db.touch(bond)
    for cert in db.ordered(db.certificates):
        if (cert["purchaser_licensee_id"] == row["id"]
                and cert["status"] == "ACTIVE"):
            cert["status"] = "REVOKED"
            db.touch(cert)
    for claim in db.ordered(db.refund_claims):
        if (claim["licensee_id"] == row["id"]
                and claim["status"] in ("SUBMITTED", "REVIEWED", "HELD")):
            claim["status"] = "DENIED"
            claim["allowable_gallons"] = calc.ZERO
            claim["refund_amount_cents"] = 0
            db.touch(claim)
    return response.object_response(derive.licensee_json(row))


@bp.post("/licensees/<licensee_id>/bonds")
def post_bond(licensee_id):
    middleware.require(LICENSING_OFFICER)
    peeked = helpers.maybe("licensee", licensee_id)
    body = shape.body()
    amount_cents = shape.req_int(body, "amount_cents",
                                minimum=calc.BOND_MIN_INSTRUMENT_CENTS)
    surety_name = shape.req_str(body, "surety_name")
    effective_date = shape.req_date(body, "effective_date")
    expected_version = shape.req_int(body, "expected_licensee_version")
    row = helpers.ensure("licensee", peeked)

    if expected_version != row["version"]:
        raise ApiError("ERR_STALE_LICENSEE_VERSION")
    if row["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")
    if effective_date > db.now().date():
        raise ApiError("ERR_DATE_RANGE_INVALID")

    bond = db.base_row()
    bond.update({
        "licensee_id": row["id"],
        "amount_cents": amount_cents,
        "surety_name": surety_name,
        "effective_date": effective_date,
        "status": "ACTIVE",
        "release_reason": None,
    })
    # Create-with-supersede: every older active instrument is released.
    for older in db.ordered(db.bonds):
        if older["licensee_id"] == row["id"] and older["status"] == "ACTIVE":
            older["status"] = "RELEASED"
            older["release_reason"] = "SUPERSEDED_BY_NEW_BOND"
            db.touch(older)
    db.bonds[bond["id"]] = bond
    db.touch(row)
    return response.object_response(derive.bond_json(bond), 201)


@bp.get("/licensees/<licensee_id>/bonds")
def list_bonds(licensee_id):
    user_id, role = middleware.require(LICENSING_OFFICER, TAX_SUPERVISOR,
                                       AUDIT_MANAGER, LICENSEE_AGENT)
    peeked = helpers.peek("licensee", licensee_id, user_id, role)
    response.pagination()
    row = helpers.ensure("licensee", peeked)
    rows = [b for b in db.ordered(db.bonds) if b["licensee_id"] == row["id"]]
    rows = helpers.filter_by(rows, {"status": "status"})
    return response.list_response(rows, derive.bond_json)


@bp.post("/bonds/<bond_id>/release")
def release_bond(bond_id):
    middleware.require(LICENSING_OFFICER)
    bond = helpers.find("bond", bond_id)
    if bond["status"] != "ACTIVE":
        raise ApiError("ERR_BOND_NOT_ACTIVE")
    licensee = db.licensees.get(bond["licensee_id"])
    if licensee is not None and licensee["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")
    if licensee is not None and licensee["status"] == "ACTIVE":
        position = derive.bond_position(licensee)
        remaining = position["posted_bond_cents"] - int(bond["amount_cents"])
        if remaining < position["required_bond_cents"]:
            raise ApiError("ERR_BOND_RELEASE_WOULD_CREATE_DEFICIENCY")

    bond["status"] = "RELEASED"
    bond["release_reason"] = "OPERATOR_RELEASE"
    db.touch(bond)
    if licensee is not None:
        db.touch(licensee)
    return response.object_response(derive.bond_json(bond))


@bp.get("/licensees/<licensee_id>/bond-status")
def bond_status(licensee_id):
    user_id, role = middleware.require(LICENSING_OFFICER, TAX_SUPERVISOR,
                                       AUDIT_MANAGER, LICENSEE_AGENT)
    row = helpers.ensure("licensee",
                         helpers.peek("licensee", licensee_id, user_id, role))
    return response.object_response(derive.bond_position(row))


@bp.get("/licensees/<licensee_id>/risk-profile")
def risk_profile(licensee_id):
    middleware.require(AUDIT_MANAGER, TAX_SUPERVISOR, RETURNS_EXAMINER)
    row = helpers.find("licensee", licensee_id)
    inputs = derive.risk_inputs(row["id"])
    variance, frequency = calc.risk_scores(
        inputs["unreported_gallons_total"], inputs["open_discrepancy_count"],
        inputs["late_filing_count"], inputs["dyed_violation_count"])
    return response.object_response({
        "risk_score_variance_weighted": variance,
        "risk_score_frequency_weighted": frequency,
        "unreported_gallons_total": derive.num(inputs["unreported_gallons_total"]),
        "open_discrepancy_count": inputs["open_discrepancy_count"],
        "late_filing_count": inputs["late_filing_count"],
        "dyed_violation_count": inputs["dyed_violation_count"],
        "audit_selection_threshold": calc.AUDIT_SELECTION_THRESHOLD,
    })


@bp.get("/licensees/<licensee_id>/ledger-entries")
def list_ledger_entries(licensee_id):
    user_id, role = middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER,
                                       TAX_SUPERVISOR, AUDIT_MANAGER,
                                       LICENSEE_AGENT)
    peeked = helpers.peek("licensee", licensee_id, user_id, role)
    response.pagination()
    row = helpers.ensure("licensee", peeked)
    rows = [e for e in db.ordered(db.ledger_entries)
            if e["licensee_id"] == row["id"]]
    rows = helpers.filter_by(rows, {"entry_type": "entry_type"})
    return response.list_response(rows, derive.ledger_entry_json)


@bp.post("/licensees/<licensee_id>/payments")
def record_payment(licensee_id):
    middleware.require(TAX_SUPERVISOR)
    peeked = helpers.maybe("licensee", licensee_id)
    body = shape.body()
    amount_cents = shape.req_int(body, "amount_cents", minimum=1)
    effective_date = shape.req_date(body, "effective_date")
    memo = shape.opt_str(body, "memo")
    row = helpers.ensure("licensee", peeked)

    if amount_cents > derive.balance_cents(row["id"]):
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    entry = cascade.post_ledger(row["id"], "PAYMENT", -amount_cents, "Payment",
                                None, memo, effective_date)
    db.touch(row)
    return response.object_response(derive.ledger_entry_json(entry), 201)
