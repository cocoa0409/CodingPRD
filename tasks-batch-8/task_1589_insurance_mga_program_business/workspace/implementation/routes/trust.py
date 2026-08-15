"""Premium trust accounting: carrier remittances and ledger reads
(PRD sections 2.8, 3.5)."""
from flask import Blueprint, request

import serialize
from db import STORE
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_TRUST_FLOOR_BREACH,
    ERR_NOTHING_TO_REMIT, ERR_REMITTANCE_MISMATCH,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services import trust
from validation import get_body, req_int, opt_str

bp = Blueprint("trust", __name__)

# Remittances and loss evaluations share this state gate.
REMITTABLE_STATUSES = ("ACTIVE", "RUN_OFF", "SUSPENDED")


@bp.post("/mga/programs/<programId>/remittances")
def create_remittance(programId):
    require_roles("MGAFinance")
    program = get_or_404(STORE.programs, programId, "Program")
    body = get_body()
    declared_amount_cents = req_int(body, "declared_amount_cents")
    memo = opt_str(body, "memo")
    require_program_not_terminal(program)
    if program["status"] not in REMITTABLE_STATUSES:
        raise_err(ERR_INVALID_STATE, "Remittances require program status ACTIVE, RUN_OFF or SUSPENDED.")
    # Fiduciary-safety check first: the declared remittance may not push the
    # trust balance below the program's floor.
    if program["trust_balance_cents"] - declared_amount_cents < program["min_trust_balance_cents"]:
        raise_err(ERR_TRUST_FLOOR_BREACH, "Remittance would push the trust balance below min_trust_balance_cents.")
    basis, remittance = trust.compute_remittance(program)
    if basis == 0:
        raise_err(ERR_NOTHING_TO_REMIT, "There is no unremitted-collections basis.")
    if declared_amount_cents != remittance:
        raise_err(
            ERR_REMITTANCE_MISMATCH,
            "declared_amount_cents %d != computed remittance %d." % (declared_amount_cents, remittance),
        )
    entry = trust.post_entry(
        program, "CARRIER_REMITTANCE", -remittance, basis_cents=basis, memo=memo
    )
    return success_object(serialize.ledger_entry(entry), status=201)


@bp.get("/mga/programs/<programId>/trust-ledger")
def list_program_trust_ledger(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [e for e in STORE.trust_ledger.values() if e["program_id"] == programId],
        entry_type=request.args.get("entry_type"),
    )
    return render_list(items, serialize.ledger_entry)


@bp.get("/mga/trust-ledger-entries/<entryId>")
def get_ledger_entry(entryId):
    require_roles(*ALL_ROLES)
    e = get_or_404(STORE.trust_ledger, entryId, "TrustLedgerEntry")
    return success_object(serialize.ledger_entry(e))


@bp.get("/mga/trust-ledger-entries")
def list_ledger_entries():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.trust_ledger.values()),
        program_id=request.args.get("program_id"),
        policy_id=request.args.get("policy_id"),
        claim_id=request.args.get("claim_id"),
        entry_type=request.args.get("entry_type"),
    )
    return render_list(items, serialize.ledger_entry)
