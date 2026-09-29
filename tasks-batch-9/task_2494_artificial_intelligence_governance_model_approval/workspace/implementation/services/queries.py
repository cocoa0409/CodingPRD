"""Collection lookups, ordered created_at ASC (PRD 2.2 default list ordering)."""
import constants
import db


def gates_of(use_case_id):
    return db.ordered(
        [g for g in db.review_gates.values() if g["use_case_id"] == use_case_id]
    )


def live_gates_of(use_case_id):
    return [g for g in gates_of(use_case_id) if g["status"] != "VOIDED"]


def evaluations_of(use_case_id):
    return db.ordered(
        [e for e in db.test_evaluations.values() if e["use_case_id"] == use_case_id]
    )


def evaluations_of_binding(binding_id):
    return db.ordered(
        [e for e in db.test_evaluations.values() if e["model_binding_id"] == binding_id]
    )


def designs_of(use_case_id):
    return db.ordered(
        [d for d in db.oversight_designs.values() if d["use_case_id"] == use_case_id]
    )


def notices_of(use_case_id):
    return db.ordered(
        [n for n in db.disclosure_notices.values() if n["use_case_id"] == use_case_id]
    )


def bindings_of(use_case_id):
    return db.ordered(
        [b for b in db.model_bindings.values() if b["use_case_id"] == use_case_id]
    )


def pinned_binding_of(use_case_id):
    pinned = [b for b in bindings_of(use_case_id) if b["status"] == "PINNED"]
    return pinned[-1] if pinned else None


def bindings_of_asset(asset_id):
    return db.ordered(
        [b for b in db.model_bindings.values() if b["model_asset_id"] == asset_id]
    )


def assessments_of(asset_id):
    return db.ordered(
        [a for a in db.vendor_assessments.values() if a["model_asset_id"] == asset_id]
    )


def accepted_assessments_of(asset_id):
    return [a for a in assessments_of(asset_id) if a["status"] == "ACCEPTED"]


def incidents_of(use_case_id):
    return db.ordered(
        [i for i in db.monitoring_incidents.values() if i["use_case_id"] == use_case_id]
    )


def shadows_of_asset(asset_id):
    return db.ordered(
        [s for s in db.shadow_deployments.values() if s["model_asset_id"] == asset_id]
    )


def ledger_of(use_case_id):
    return db.ordered(
        [e for e in db.ledger_entries.values() if e["use_case_id"] == use_case_id]
    )


def passed_eval_types(use_case_id):
    return {e["eval_type"] for e in evaluations_of(use_case_id) if e["status"] == "PASSED"}


def cleared_gate_count(use_case_id):
    return sum(1 for g in gates_of(use_case_id) if g["status"] == "CLEARED")


def passed_eval_count(use_case_id):
    return sum(1 for e in evaluations_of(use_case_id) if e["status"] == "PASSED")


def effective_tier(use_case):
    if use_case.get("final_risk_tier") is not None:
        return use_case["final_risk_tier"]
    return use_case.get("risk_tier")


def inventory_use_cases():
    return [
        u for u in db.all_of(db.use_cases) if u["status"] in constants.INVENTORY_STATUSES
    ]
