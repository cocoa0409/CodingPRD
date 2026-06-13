"""Cascade side-effects (PRD §2.5, §3.11; SCAFFOLD §1.2).

The void-and-release cascade fires when a case is cancelled:
  L1  Case CANCELLED -> Contract VOID (if a contract exists and is not VOID/SETTLED)
  L2  Contract VOID  -> for each POSTED PRINCIPAL/EARNINGS deposit, create a
                        compensating REFUND deposit of equal amount and mark the
                        original REFUNDED; each VERIFIED InsuranceAssignment -> RELEASED
  L3  Contract VOID  -> reserved Plot (RESERVED, reserved_case_id == case) released
  L4  Contract VOID  -> each SCHEDULED Event of the case -> CANCELLED

Every affected row independently bumps its own version + updated_at.
"""
import db


def _next_posted_seq():
    # reuse the global insertion counter for posted_at ordering
    return db._next_seq()


def void_contract(contract):
    """Apply links L2-L4 of the void-and-release cascade, then mark contract VOID."""
    contract_id = contract["id"]
    case = db.cases.get(contract["case_id"])

    # L2a: refund every POSTED PRINCIPAL/EARNINGS deposit so the conserved
    # corpus (PRD §2.8) returns to 0.
    #   trust_principal      = sum(POSTED PRINCIPAL) - sum(POSTED REFUND)
    #   credited_earnings    = sum(POSTED EARNINGS)
    # PRINCIPAL: keep the original POSTED and add an equal POSTED REFUND leg
    #            (the REFUND is the subtraction term, so +amount - amount = 0).
    # EARNINGS:  a REFUND leg only subtracts from principal, so instead drop the
    #            EARNINGS deposit out of the POSTED set (mark it REFUNDED) — that
    #            removes it from sum(POSTED EARNINGS), returning earnings to 0.
    for dep in list(db.trust_deposits.values()):
        if dep["contract_id"] != contract_id:
            continue
        if dep["status"] != "POSTED":
            continue
        if dep["kind"] == "PRINCIPAL":
            refund = {
                "id": db.new_id(),
                "contract_id": contract_id,
                "kind": "REFUND",
                "amount_cents": dep["amount_cents"],
                "status": "POSTED",
                "posted_at": db.now_iso(),
            }
            db.stamp_create(refund)
            refund["_posted_at_seq"] = _next_posted_seq()
            db.trust_deposits[refund["id"]] = refund
            db.touch(dep)  # affected by the void; stays POSTED for net-zero
        elif dep["kind"] == "EARNINGS":
            dep["status"] = "REFUNDED"
            db.touch(dep)

    # L2b: release every VERIFIED insurance assignment.
    for a in db.insurance_assignments.values():
        if a["contract_id"] == contract_id and a["status"] == "VERIFIED":
            a["status"] = "RELEASED"
            db.touch(a)

    # L3: release the plot reserved for this case.
    if case is not None:
        for p in db.plots.values():
            if p.get("reserved_case_id") == case["id"] and p["status"] == "RESERVED":
                p["status"] = "AVAILABLE"
                p["reserved_case_id"] = None
                p["locked_price_cents"] = None
                db.touch(p)

        # L4: cancel every SCHEDULED event of the case.
        for e in db.events.values():
            if e["case_id"] == case["id"] and e["status"] == "SCHEDULED":
                e["status"] = "CANCELLED"
                db.touch(e)

    # finally mark the contract VOID with its own version bump.
    contract["status"] = "VOID"
    db.touch(contract)


def cancel_case(case):
    """Head of the cascade: cancel the case, then void its contract if eligible."""
    case["arrangement_status"] = "CANCELLED"
    case["interment_status"] = "NOT_READY"
    db.touch(case)

    contract = None
    for c in db.contracts.values():
        if c["case_id"] == case["id"]:
            contract = c
            break
    if contract is not None and contract["status"] not in ("VOID", "SETTLED"):
        void_contract(contract)
