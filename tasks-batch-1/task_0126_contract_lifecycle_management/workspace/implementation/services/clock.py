"""Logical clock advance + sweep (PRD §2.10, §3.6, §3.7, §3.9 / SCAFFOLD §1.2)."""

from datetime import timedelta

from common import bump, stamp_new
from db import db
from services.audit import append_audit
from services.contract_logic import current_version
from util import add_calendar_months, format_iso_millis, parse_iso8601


def _parse_stored_dt(value):
    if value is None:
        return None
    return parse_iso8601(value)


def advance_clock(to_iso8601):
    """Set the clock to `to_iso8601` and run the sweep over all contracts.

    Returns (now_iso, swept_contract_ids). A contract id appears in
    swept_contract_ids if the sweep mutated the contract or any of its children.
    """
    new_now = parse_iso8601(to_iso8601, field="to_iso8601")
    db.clock = new_now

    swept = set()

    # The sweep applies, in one pass per §3.9. We process contracts in a stable
    # order (creation order) for determinism.
    contracts = sorted(
        db.contracts.values(),
        key=lambda c: (c.get("created_at", ""), c.get("id", "")),
    )

    for contract in contracts:
        # 1) Renewal alerts SCHEDULED -> DUE where now >= trigger_date and the
        #    parent contract is ACTIVE (PRD §3.6, boundary inclusive).
        if contract.get("status") == "ACTIVE":
            for alert in _alerts_of(contract):
                if alert.get("status") == "SCHEDULED":
                    trigger = _parse_stored_dt(alert.get("trigger_date"))
                    if trigger is not None and new_now >= trigger:
                        alert["status"] = "DUE"
                        bump(alert)
                        swept.add(contract["id"])

        # 2) Obligations OPEN -> BREACHED where now > due_date and contract ACTIVE
        #    (PRD §3.6, strictly past).
        if contract.get("status") == "ACTIVE":
            for ob in _obligations_of(contract):
                if ob.get("status") == "OPEN":
                    due = _parse_stored_dt(ob.get("due_date"))
                    if due is not None and new_now > due:
                        ob["status"] = "BREACHED"
                        bump(ob)
                        append_audit(contract["id"], "OBLIGATION_BREACHED",
                                     actor_user_id=None,
                                     detail="Obligation breached past due date.")
                        swept.add(contract["id"])

        # 3) ACTIVE contracts: auto-renew on a DUE alert, else expire when the
        #    term has run out (PRD §3.7).
        if contract.get("status") == "ACTIVE":
            if contract.get("auto_renew") and _has_due_alert(contract):
                _system_renew(contract)
                swept.add(contract["id"])
            elif not contract.get("auto_renew"):
                expiry = _parse_stored_dt(contract.get("expiry_date"))
                if expiry is not None and new_now >= expiry:
                    _expire(contract)
                    swept.add(contract["id"])

    return format_iso_millis(new_now), sorted(swept)


# --- Child lookups -----------------------------------------------------------
def _alerts_of(contract):
    return [a for a in db.renewal_alerts.values()
            if a.get("contract_id") == contract.get("id")]


def _obligations_of(contract):
    return [o for o in db.obligations.values()
            if o.get("contract_id") == contract.get("id")]


def _has_due_alert(contract):
    return any(a.get("status") == "DUE" for a in _alerts_of(contract))


# --- System renew (auto-renew self-loop, PRD §3.7) ---------------------------
def _system_renew(contract):
    renew_contract(contract)


def renew_contract(contract):
    """Shared renewal logic for both manual renew and the auto-renew sweep
    (PRD §3.7). Caller must have verified preconditions for the manual path."""
    prior_expiry = _parse_stored_dt(contract.get("expiry_date"))

    contract["renewal_cycle_index"] = int(contract.get("renewal_cycle_index", 0)) + 1
    contract["effective_date"] = format_iso_millis(prior_expiry)
    new_expiry = add_calendar_months(prior_expiry, int(contract["term_months"]))
    contract["expiry_date"] = format_iso_millis(new_expiry)

    # The DUE alert -> RESOLVED(RENEWED).
    for alert in _alerts_of(contract):
        if alert.get("status") == "DUE":
            alert["status"] = "RESOLVED"
            alert["resolution"] = "RENEWED"
            bump(alert)

    # New SCHEDULED alert for the new expiry.
    _create_renewal_alert(contract, new_expiry)

    append_audit(contract["id"], "RENEWED", actor_user_id=None,
                 detail="Contract renewed; term extended.")
    bump(contract)


def _create_renewal_alert(contract, expiry_dt):
    org = db.organizations.get(contract.get("organization_id"))
    lead_days = int(org.get("auto_renew_lead_days")) if org else 30
    trigger = expiry_dt - timedelta(days=lead_days)
    alert = {
        "contract_id": contract["id"],
        "trigger_date": format_iso_millis(trigger),
        "resolution": None,
        "status": "SCHEDULED",
    }
    stamp_new(alert)
    db.renewal_alerts[alert["id"]] = alert
    return alert


# --- Expiry (PRD §3.7) -------------------------------------------------------
def _expire(contract):
    contract["status"] = "EXPIRED"

    for alert in _alerts_of(contract):
        if alert.get("status") in ("SCHEDULED", "DUE"):
            alert["status"] = "RESOLVED"
            alert["resolution"] = "LET_LAPSE"
            bump(alert)

    for ob in _obligations_of(contract):
        if ob.get("status") == "OPEN":
            ob["status"] = "WAIVED"
            bump(ob)

    bump(contract)
