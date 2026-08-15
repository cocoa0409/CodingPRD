"""Employer compliance posture (PRD 2.9) and shared lookups.

compliance_posture is recomputed fresh on every read and after every mutation
in the employer's subgraph; it is derived, never stored.
"""

from __future__ import annotations

import db


def pack_for_state(state_code: str) -> dict | None:
    for pack in db.state_rule_packs.values():
        if pack["state_code"] == state_code:
            return pack
    return None


def employer_workers(employer_id: str) -> list[dict]:
    return [w for w in db.workers.values() if w["employer_id"] == employer_id]


def employer_paychecks(employer_id: str) -> list[dict]:
    """Paychecks belonging to this employer (via parent pay run)."""
    run_ids = {r["id"] for r in db.pay_runs.values() if r["employer_id"] == employer_id}
    return [p for p in db.paychecks.values() if p["pay_run_id"] in run_ids]


def issued_paychecks(employer_id: str) -> list[dict]:
    return [p for p in employer_paychecks(employer_id) if p["status"] == "ISSUED"]


def policy_covers(employer_id: str, state_code: str, on_date: str) -> bool:
    """A BOUND or ACTIVE policy for the state whose closed coverage window
    includes on_date."""
    for pol in db.policies.values():
        if pol["employer_id"] != employer_id:
            continue
        if pol["state_code"] != state_code:
            continue
        if pol["status"] not in ("BOUND", "ACTIVE"):
            continue
        if pol["coverage_start"] <= on_date <= pol["coverage_end"]:
            return True
    return False


def compute_posture(employer: dict) -> str:
    today = db.clock_today()
    # RESTRICTED: any ACTIVE worker in a workers-comp-mandated state without a
    # BOUND|ACTIVE policy covering the logical-clock current date.
    for worker in employer_workers(employer["id"]):
        if worker["status"] != "ACTIVE":
            continue
        pack = pack_for_state(worker["work_state_code"])
        if pack is None or not pack["workers_comp_required"]:
            continue
        if not policy_covers(employer["id"], worker["work_state_code"], today):
            return "RESTRICTED"
    # ATTENTION: any late deposit or any REJECTED filing.
    for dep in db.deposits.values():
        if dep["employer_id"] == employer["id"] and dep.get("late_days", 0) > 0:
            return "ATTENTION"
    for filing in db.filings.values():
        if filing["employer_id"] == employer["id"] and filing["status"] == "REJECTED":
            return "ATTENTION"
    return "CLEAR"
