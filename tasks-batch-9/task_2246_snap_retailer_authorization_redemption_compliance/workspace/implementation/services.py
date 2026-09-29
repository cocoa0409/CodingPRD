"""Cascade and derivation services shared by the route modules."""
import calc
from core import commit, db, mark, now, ordered

__all__ = ["commit"]


# ---------------------------------------------------------------------------
# Generic mutation helper: records the row as dirty so it receives exactly one
# version bump for the whole request (§2.5).
# ---------------------------------------------------------------------------
def update_row(row, changes):
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        mark(row)
    return changed


# ---------------------------------------------------------------------------
# Depot / terminal conservation
# ---------------------------------------------------------------------------
def sync_depot(depot):
    if depot is None:
        return
    update_row(depot, calc.depot_counters(depot))


def sync_depot_of(terminal):
    sync_depot(db.equipment_depots.get(terminal["depot_id"]))


def set_terminal_status(terminal, status):
    update_row(terminal, {"status": status})
    sync_depot_of(terminal)


def resync_terminal(terminal):
    """Derive a terminal's status from its remaining open commitments."""
    if terminal["status"] == "RETIRED":
        return
    statuses = [d["status"] for d in db.terminal_deployments.values()
                if d["terminal_id"] == terminal["id"]
                and d["status"] in calc.OPEN_DEPLOYMENT_STATUSES]
    if "RECALL_PENDING" in statuses:
        target = "PENDING_RETURN"
    elif "ACTIVE" in statuses:
        target = "DEPLOYED"
    elif "RESERVED" in statuses:
        target = "RESERVED"
    else:
        target = "IN_STOCK"
    set_terminal_status(terminal, target)


def refresh_active_terminal_count(store):
    count = sum(1 for d in db.terminal_deployments.values()
                if d["store_id"] == store["id"] and d["status"] == "ACTIVE")
    update_row(store, {"active_terminal_count": count})


def close_deployment(deployment, target, close_reason_code=None,
                     set_closed_at=True):
    changes = {"status": target}
    if close_reason_code is not None:
        changes["close_reason_code"] = close_reason_code
    if set_closed_at:
        changes["closed_at"] = now()
    update_row(deployment, changes)
    terminal = db.ebt_terminals.get(deployment["terminal_id"])
    if terminal is not None:
        resync_terminal(terminal)
    store = db.stores.get(deployment["store_id"])
    if store is not None:
        refresh_active_terminal_count(store)


def release_reserved_deployments(store, close_reason_code=None):
    """Cascade used by application denial, store withdrawal and investigation
    opening: every RESERVED commitment of the store becomes RELEASED."""
    rows = ordered([d for d in db.terminal_deployments.values()
                    if d["store_id"] == store["id"] and d["status"] == "RESERVED"])
    for deployment in rows:
        close_deployment(deployment, "RELEASED", close_reason_code)
    return rows


def release_open_deployments_for_withdrawal(store):
    """Store withdrawal releases both ACTIVE and RESERVED commitments."""
    rows = ordered([d for d in db.terminal_deployments.values()
                    if d["store_id"] == store["id"]
                    and d["status"] in ("ACTIVE", "RESERVED")])
    for deployment in rows:
        close_deployment(deployment, "RELEASED")
    return rows


def recall_active_deployments(store, close_reason_code):
    rows = ordered([d for d in db.terminal_deployments.values()
                    if d["store_id"] == store["id"] and d["status"] == "ACTIVE"])
    for deployment in rows:
        update_row(deployment, {"status": "RECALL_PENDING",
                                "close_reason_code": close_reason_code})
        terminal = db.ebt_terminals.get(deployment["terminal_id"])
        if terminal is not None:
            resync_terminal(terminal)
    refresh_active_terminal_count(store)
    return rows


# ---------------------------------------------------------------------------
# Owner rollup
# ---------------------------------------------------------------------------
def rederive_case_balance(case):
    """Case version bumps are owned by the endpoint, so write in place."""
    case["cmp_outstanding_cents"] = calc.case_outstanding(case["id"])


def rederive_owner(owner_id):
    owner = db.owners.get(owner_id)
    if owner is None:
        return
    update_row(owner, calc.owner_rollup(owner_id))


def rederive_owner_of_store(store):
    if store is not None:
        rederive_owner(store["owner_id"])


# ---------------------------------------------------------------------------
# Redemption period aggregates
# ---------------------------------------------------------------------------
def refresh_period(period):
    values = calc.period_metrics(period)
    update_row(period, values)
    return values


def refresh_open_periods(store_id):
    for period in db.redemption_periods.values():
        if period["store_id"] == store_id and period["status"] == "OPEN":
            refresh_period(period)


def covering_period(txn):
    """The store's period whose half-open window contains the txn instant."""
    candidates = [p for p in db.redemption_periods.values()
                  if p["store_id"] == txn["store_id"]
                  and p["period_start"] <= txn["created_at"] < p["period_end"]]
    if not candidates:
        return None
    return ordered(candidates)[0]


def refresh_store_flag_level(store):
    update_row(store, {"redemption_flag_level": calc.store_flag_level(store["id"])})


# ---------------------------------------------------------------------------
# Inspector committed minutes
# ---------------------------------------------------------------------------
def refresh_inspector_minutes(inspector):
    if inspector is None:
        return
    update_row(inspector, {
        "committed_minutes": calc.inspector_committed_minutes(inspector["id"]),
    })


def refresh_inspector_minutes_by_id(inspector_id):
    refresh_inspector_minutes(db.inspectors.get(inspector_id))


# ---------------------------------------------------------------------------
# Application helpers
# ---------------------------------------------------------------------------
NON_TERMINAL_APPLICATION_STATUSES = (
    "DRAFT", "SUBMITTED", "PENDING_VISIT", "PENDING_DOCUMENTS", "UNDER_REVIEW")


def store_of_application(application):
    return db.stores.get(application["store_id"])


def application_of_store(store_id, statuses):
    rows = [a for a in db.applications.values()
            if a["store_id"] == store_id and a["status"] in statuses]
    if not rows:
        return None
    return ordered(rows)[-1]


def run_desk_assessment(application):
    qualifying, perishable, passes = calc.criterion_a(
        application.get("reported_inventory_lines"), "DESK_VARIETY_FIRST")
    return {
        "desk_qualifying_categories": qualifying,
        "desk_perishable_categories": perishable,
        "desk_criterion_pass": passes,
    }


def consume_deficiency_cycle(application, hold_reason_code,
                             verified_pass=None):
    """PENDING_VISIT -> PENDING_DOCUMENTS while cycles remain, else DENIED."""
    cycles = application.get("deficiency_cycle_count") or 0
    if cycles < 2:
        changes = {
            "status": "PENDING_DOCUMENTS",
            "deficiency_cycle_count": cycles + 1,
            "hold_reason_code": hold_reason_code,
        }
        if verified_pass is not None:
            changes["verified_criterion_pass"] = verified_pass
        update_row(application, changes)
    else:
        changes = {
            "status": "DENIED",
            "deficiency_cycle_count": 3,
            "decision_reason_code": "DEFICIENCY_CYCLES_EXHAUSTED",
            "decided_at": now(),
        }
        if verified_pass is not None:
            changes["verified_criterion_pass"] = verified_pass
        update_row(application, changes)
        store = store_of_application(application)
        if store is not None:
            release_reserved_deployments(store)


# ---------------------------------------------------------------------------
# Investigation opening cascade (§3.8)
# ---------------------------------------------------------------------------
def open_investigation_cascade(store):
    if store is None:
        return
    if store.get("sanction_status") in ("NONE", "SANCTION_REVERSED"):
        update_row(store, {"sanction_status": "UNDER_INVESTIGATION"})
    release_reserved_deployments(store)
    for application in ordered(list(db.applications.values())):
        if application["store_id"] != store["id"]:
            continue
        if application["status"] != "UNDER_REVIEW":
            continue
        update_row(application, {
            "status": "PENDING_DOCUMENTS",
            "hold_reason_code": "INVESTIGATION_HOLD",
            "deficiency_cycle_count": (application.get("deficiency_cycle_count") or 0) + 1,
        })


def store_has_live_investigation(store_id, exclude_id=None):
    for inv in db.investigations.values():
        if inv["store_id"] != store_id:
            continue
        if inv["id"] == exclude_id:
            continue
        if inv["status"] in ("OPEN", "EVIDENCE_REVIEW"):
            return True
    return False


# ---------------------------------------------------------------------------
# Sanction-case / election helpers
# ---------------------------------------------------------------------------
def case_elections(case_id):
    return ordered([e for e in db.cmp_elections.values()
                    if e["sanction_case_id"] == case_id])


def elected_election(case_id):
    for election in case_elections(case_id):
        if election["status"] == "ELECTED":
            return election
    return None


def approved_election(case_id):
    for election in case_elections(case_id):
        if election["status"] == "APPROVED":
            return election
    return None


def abate_outstanding(case):
    balance = calc.case_outstanding(case["id"])
    if balance > 0:
        calc.append_ledger_entry(case, "CMP_ABATEMENT", -balance,
                                 "REVIEW_REVERSAL")
    rederive_case_balance(case)
    store = db.stores.get(case["store_id"])
    rederive_owner_of_store(store)


CMP_FIGURE_FIELDS = ("cmp_basis_variant", "cmp_basis_period_ids",
                     "avg_monthly_redemption_cents", "monthly_penalty_cents",
                     "cmp_amount_cents", "cmp_capped")
