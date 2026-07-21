"""Entity serializers producing the exact response field sets."""
from core import db
import calc


def _full(rec, keys):
    out = {"id": rec["id"]}
    for k in keys:
        out[k] = rec.get(k)
    out["created_at"] = rec["created_at"]
    out["updated_at"] = rec["updated_at"]
    out["version"] = rec["version"]
    return out


def _append(rec, keys):
    out = {"id": rec["id"]}
    for k in keys:
        out[k] = rec.get(k)
    out["created_at"] = rec["created_at"]
    return out


def property_out(r):
    return _full(r, ["landlord_name", "unit_label", "full_rent_cents", "rent_due_day",
                     "remittance_account_ref", "integration_status", "status"])


def renter_out(r):
    return _full(r, ["property_id", "email", "full_name", "portion_rent_cents",
                     "status", "risk_band", "approved_limit_cents", "autopay_enabled"])


def application_out(r):
    return _full(r, ["renter_id", "reported_monthly_income_cents", "requested_split_count",
                     "prior_delinquency_count", "status", "risk_score", "risk_band",
                     "approved_limit_cents", "decision_reason"])


def cycle_out(r):
    return _full(r, ["renter_id", "property_id", "cycle_month", "cycle_start_date",
                     "mode", "split_count", "deferred_amount_cents", "planned_defer_days",
                     "full_rent_cents", "portion_cents", "fee_provisional_cents",
                     "fee_final_cents", "repaid_amount_cents", "net_remitted_cents",
                     "outstanding_cents", "status"])


def cycle_summary_out(r):
    out = cycle_out(r)
    principal = r["portion_cents"] - r["repaid_amount_cents"]
    case = _latest_case_for_cycle(r["id"])
    accrued = case["accrued_late_fee_cents"] if case else 0
    out["reinstatement_amount_cents"] = principal + accrued
    out["settlement_amount_cents"] = principal + calc.SETTLEMENT_ADMIN_FEE_CENTS
    return out


def installment_out(r):
    return _full(r, ["cycle_id", "sequence_no", "due_date", "amount_cents", "kind",
                     "attempt_count", "paid_at", "status"])


def remittance_out(r):
    return _full(r, ["cycle_id", "property_id", "amount_cents", "sent_at", "status"])


def mandate_out(r):
    return _full(r, ["renter_id", "method_ref", "status"])


def _latest_case_for_cycle(cycle_id):
    cases = [c for c in db.delinquency_cases.values() if c["cycle_id"] == cycle_id]
    if not cases:
        return None
    return sorted(cases, key=lambda c: c["_seq"])[-1]


def case_out(r):
    out = _full(r, ["cycle_id", "renter_id", "recovery_round", "accrued_late_fee_cents",
                    "principal_outstanding_cents", "promise_date", "opened_at",
                    "last_recovery_agent_id", "status"])
    cycle = db.billing_cycles.get(r["cycle_id"])
    if cycle is not None:
        principal = cycle["portion_cents"] - cycle["repaid_amount_cents"]
    else:
        principal = r["principal_outstanding_cents"]
    out["principal_outstanding_cents"] = principal
    out["reinstatement_amount_cents"] = principal + r["accrued_late_fee_cents"]
    out["settlement_amount_cents"] = principal + calc.SETTLEMENT_ADMIN_FEE_CENTS
    return out


def recovery_action_out(r):
    return _append(r, ["case_id", "action_type", "agent_id", "promise_date", "note"])


def reminder_out(r):
    return _append(r, ["renter_id", "cycle_id", "kind", "channel", "sent_at"])


def ledger_out(r):
    return _append(r, ["cycle_id", "entry_type", "amount_cents", "memo"])
