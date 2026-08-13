"""Agent debit ledger (PRD §3.8). Append-only entries; running balance."""

import db
from services.common import new_id, stamp_append_only


def post_entry(agent, entry_type, amount_cents, deal_id=None, settlement_id=None,
               reason=None):
    """Append a ledger entry and move the agent's debit balance. Positive
    amounts increase the balance; negative amounts decrease it."""
    agent["debit_balance_cents"] = agent.get("debit_balance_cents", 0) + amount_cents
    entry = {
        "id": new_id(),
        "agent_id": agent["id"],
        "deal_id": deal_id,
        "settlement_id": settlement_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "resulting_balance_cents": agent["debit_balance_cents"],
        "reason": reason,
    }
    stamp_append_only(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry
