"""The premium tax ledger: TaxFilingLine emission and the policy tax dimension."""

import store
from calc import filing
from store import db, touch


def emit_line(policy, state_program_id, line_type, taxable_premium_cents,
              tax_cents, stamping_fee_cents, source_endorsement_id=None,
              source_cancellation_id=None):
    """Create one OPEN tax filing line. The period_key is derived from the
    logical clock at the moment of creation, formatted per the state's
    filing_frequency, and is never revisited afterwards."""
    program = db.get("state_programs", state_program_id)
    period_key = filing.period_key_for(program) if program else None
    return db.insert("tax_filing_lines", {
        "policy_id": policy["id"],
        "state_program_id": state_program_id,
        "filing_batch_id": None,
        "source_endorsement_id": source_endorsement_id,
        "source_cancellation_id": source_cancellation_id,
        "line_type": line_type,
        "period_key": period_key,
        "taxable_premium_cents": int(taxable_premium_cents),
        "tax_cents": int(tax_cents),
        "stamping_fee_cents": int(stamping_fee_cents),
        "status": "OPEN",
    })


def program_id_for_state(state_code):
    program = store.state_program_by_code(state_code)
    return program["id"] if program else None


def advance_to_adjusted(policy, has_delta):
    """CALCULATED -> ADJUSTED fires for any non-UNCALCULATED tax dimension.
    REMITTED -> ADJUSTED closes the cycle only when the adjusting event
    produces a non-zero tax or stamping fee delta."""
    status = policy.get("tax_status")
    if status == "UNCALCULATED":
        return False
    if status == "REMITTED" and not has_delta:
        return False
    policy["tax_status"] = "ADJUSTED"
    return True


def _policies_of(lines):
    seen = []
    for line in lines:
        pid = line.get("policy_id")
        if pid not in seen:
            seen.append(pid)
    return seen


def advance_policies_after_filing(lines):
    """A policy reaches FILED once all of its lines are FILED, VOIDED or
    REMITTED."""
    for policy_id in _policies_of(lines):
        policy = db.get("policies", policy_id)
        if policy is None:
            continue
        if policy.get("tax_status") not in ("CALCULATED", "ADJUSTED"):
            continue
        rows = store.lines_of_policy(policy_id)
        if rows and all(r.get("status") in ("FILED", "VOIDED", "REMITTED")
                        for r in rows):
            policy["tax_status"] = "FILED"
            touch(policy)


def advance_policies_after_remittance(lines):
    """A policy reaches REMITTED once all of its lines are REMITTED or VOIDED."""
    for policy_id in _policies_of(lines):
        policy = db.get("policies", policy_id)
        if policy is None:
            continue
        if policy.get("tax_status") != "FILED":
            continue
        rows = store.lines_of_policy(policy_id)
        if rows and all(r.get("status") in ("REMITTED", "VOIDED") for r in rows):
            policy["tax_status"] = "REMITTED"
            touch(policy)
