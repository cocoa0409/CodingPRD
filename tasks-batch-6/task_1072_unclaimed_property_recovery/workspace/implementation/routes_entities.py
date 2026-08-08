"""Reference data (holders, property-types, state-accounts, owners, firms),
ledger reads, and the logical clock."""
import re
from flask import request

from store import STORE, new_id, parse_iso
from common import (
    ApiError, ok, ok_list, require_roles, get_json, require_str, require_int,
    require_enum, require_bool, require_number, stamp_new, serialize,
    serialize_list, paginate,
)
import lookups

HOLDER_TYPES = {"BANK", "INSURER", "UTILITY", "BROKER", "OTHER"}
DORMANCY_BASES = {"LAST_ACTIVITY", "ISSUANCE"}

_STATE_RE = re.compile(r"^[A-Z]{2}$")
_SSN_RE = re.compile(r"^[0-9]{4}$")


def require_state_code(body, name):
    v = require_str(body, name)
    if not _STATE_RE.match(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be two uppercase letters.")
    return v


def register(app):
    # ---------------- Holder ----------------
    @app.post("/holders")
    @require_roles("StateAdmin")
    def create_holder():
        body = get_json()
        legal_name = require_str(body, "legal_name")
        incorporation_state = require_state_code(body, "incorporation_state")
        holder_type = require_enum(body, "holder_type", HOLDER_TYPES)
        ent = {
            "id": new_id(),
            "legal_name": legal_name,
            "incorporation_state": incorporation_state,
            "holder_type": holder_type,
            "status": "ACTIVE",
            "audit_hold": False,
            "assessed_penalty_cents": 0,
        }
        stamp_new(ent)
        STORE.holders[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/holders/<hid>")
    @require_roles("StateAdmin", "Holder", "StateExaminer", "StateApprover")
    def get_holder(hid):
        return ok(serialize(lookups.holder(hid)))

    # ---------------- PropertyType ----------------
    @app.post("/property-types")
    @require_roles("StateAdmin")
    def create_property_type():
        body = get_json()
        code = require_str(body, "code")
        name = require_str(body, "name")
        dormancy_period_years = require_int(body, "dormancy_period_years", min_val=1)
        dormancy_basis = require_enum(body, "dormancy_basis", DORMANCY_BASES)
        interest_bearing = require_bool(body, "interest_bearing")
        due_diligence_required = require_bool(body, "due_diligence_required")
        due_diligence_min_days = require_int(body, "due_diligence_min_days", min_val=0)
        ent = {
            "id": new_id(),
            "code": code,
            "name": name,
            "dormancy_period_years": dormancy_period_years,
            "dormancy_basis": dormancy_basis,
            "interest_bearing": interest_bearing,
            "due_diligence_required": due_diligence_required,
            "due_diligence_min_days": due_diligence_min_days,
        }
        stamp_new(ent, full=False)
        STORE.property_types[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/property-types/<pid>")
    @require_roles("StateAdmin", "Holder", "StateExaminer", "StateApprover")
    def get_property_type(pid):
        return ok(serialize(lookups.property_type(pid)))

    # ---------------- StateAccount ----------------
    @app.post("/state-accounts")
    @require_roles("StateAdmin")
    def create_state_account():
        body = get_json()
        state_code = require_state_code(body, "state_code")
        ent = {
            "id": new_id(),
            "state_code": state_code,
            "custody_balance_cents": 0,
        }
        stamp_new(ent)
        STORE.state_accounts[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/state-accounts/<sid>")
    @require_roles("StateAdmin", "StateExaminer", "StateApprover")
    def get_state_account(sid):
        return ok(serialize(lookups.state_account(sid)))

    # ---------------- Owner ----------------
    @app.post("/owners")
    @require_roles("StateAdmin")
    def create_owner():
        body = get_json()
        full_name = require_str(body, "full_name")
        ssn_last4 = require_str(body, "ssn_last4")
        if not _SSN_RE.match(ssn_last4):
            raise ApiError("ERR_INVALID_REQUEST", 400, "ssn_last4 must be exactly 4 digits.")
        address_state = require_state_code(body, "address_state")
        email = require_str(body, "email")
        ent = {
            "id": new_id(),
            "full_name": full_name,
            "ssn_last4": ssn_last4,
            "address_state": address_state,
            "email": email,
            "id_verified": False,
        }
        stamp_new(ent)
        STORE.owners[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/owners/<oid>")
    @require_roles("StateAdmin", "Owner", "StateExaminer", "StateApprover")
    def get_owner(oid):
        return ok(serialize(lookups.owner(oid)))

    # ---------------- RecoveryFirm ----------------
    @app.post("/recovery-firms")
    @require_roles("StateAdmin")
    def create_recovery_firm():
        body = get_json()
        legal_name = require_str(body, "legal_name")
        registered_state = require_state_code(body, "registered_state")
        license_number = require_str(body, "license_number")
        max_fee_pct = require_number(body, "max_fee_pct")
        if not (0 < max_fee_pct <= 1):
            raise ApiError("ERR_INVALID_REQUEST", 400, "max_fee_pct must satisfy 0 < x <= 1.")
        ent = {
            "id": new_id(),
            "legal_name": legal_name,
            "registered_state": registered_state,
            "license_number": license_number,
            "max_fee_pct": max_fee_pct,
        }
        stamp_new(ent)
        STORE.recovery_firms[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/recovery-firms/<fid>")
    @require_roles("StateAdmin", "RecoveryAgent", "StateExaminer", "StateApprover")
    def get_recovery_firm(fid):
        return ok(serialize(lookups.recovery_firm(fid)))

    # ---------------- LedgerEntry ----------------
    @app.get("/ledger-entries/<lid>")
    @require_roles("StateAdmin", "StateExaminer", "StateApprover")
    def get_ledger_entry(lid):
        return ok(serialize(lookups.ledger_entry(lid)))

    @app.get("/ledger-entries")
    @require_roles("StateAdmin", "StateExaminer", "StateApprover")
    def list_ledger_entries():
        items = list(STORE.ledger.values())
        for key in ("state_account_id", "property_id", "ref_claim_id", "ref_report_id"):
            val = request.args.get(key)
            if val is not None:
                items = [e for e in items if e.get(key) == val]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize(e) for e in page], limit, offset, total)

    # ---------------- Logical clock ----------------
    @app.post("/_clock/set_current_utc")
    @require_roles("StateAdmin")
    def set_clock():
        body = get_json()
        to_iso8601 = require_str(body, "to_iso8601")
        dt = parse_iso(to_iso8601)
        if dt is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO 8601 instant.")
        STORE.clock = dt
        return ok({}, 200)
