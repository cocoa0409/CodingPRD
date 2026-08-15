"""Clock-driven scheduled evaluation (PRD 2.4): every time-based auto-transition."""
from db import clock, store, touch
from services.calculations import evaluate_cycle_satisfaction
from services.core import adjust_hold_count, adjust_restriction_count, create_hold


def run_sweep():
    """Evaluate every clock-driven auto-transition once per clock advancement.

    Returns the number of automatic state transitions applied (creations are not
    transitions; each entity state change counts once).
    """
    now = clock.current
    transitions = 0

    # Annual cycles: OPEN -> OVERDUE (strict: on the due date itself it stays OPEN),
    # auto-creating one ACTIVE hold per missing obligation and cascading suspension.
    for cyc in sorted(store.cycles.values(), key=lambda c: c["_seq"]):
        if cyc["status"] != "OPEN":
            continue
        emp = store.employees[cyc["employee_id"]]
        missing_tb = cyc["tb_completed_at"] is None and now > cyc["tb_due_date"]
        missing_fit = (
            emp["requires_respirator"]
            and cyc["fit_test_completed_at"] is None
            and cyc["fit_test_due_date"] is not None
            and now > cyc["fit_test_due_date"]
        )
        if not (missing_tb or missing_fit):
            continue
        cyc["status"] = "OVERDUE"
        touch(cyc)
        transitions += 1
        if missing_tb:
            _, tr = create_hold(emp["id"], "TB_OVERDUE", cycle_id=cyc["id"])
            if tr:
                transitions += 1
        if missing_fit:
            _, tr = create_hold(emp["id"], "FIT_TEST_OVERDUE", cycle_id=cyc["id"])
            if tr:
                transitions += 1

    # Satisfaction re-evaluation on clock set (late completion remains possible only
    # via completions calls; evaluation is pinned to run on clock set too).
    for cyc in sorted(store.cycles.values(), key=lambda c: c["_seq"]):
        if cyc["status"] in ("OPEN", "OVERDUE"):
            emp = store.employees[cyc["employee_id"]]
            before = cyc["status"]
            evaluate_cycle_satisfaction(cyc, emp)
            if cyc["status"] != before:
                transitions += 1

    # PEP regimens: RECOMMENDED -> WINDOW_EXPIRED when now > window_deadline (STRICT).
    for pep in sorted(store.pep_regimens.values(), key=lambda p: p["_seq"]):
        if pep["status"] == "RECOMMENDED" and now > pep["window_deadline"]:
            pep["status"] = "WINDOW_EXPIRED"
            touch(pep)
            transitions += 1

    # Serology follow-ups: SCHEDULED -> DUE at window_open (INCLUSIVE),
    # then DUE -> OVERDUE when now > window_close (STRICT).
    followups = sorted(store.followups.values(), key=lambda f: f["_seq"])
    for fu in followups:
        if fu["status"] == "SCHEDULED" and now >= fu["window_open"]:
            fu["status"] = "DUE"
            touch(fu)
            transitions += 1
    for fu in followups:
        if fu["status"] == "DUE" and now > fu["window_close"]:
            fu["status"] = "OVERDUE"
            touch(fu)
            transitions += 1

    # Contacts: auto-clear strictly past monitoring_end with no symptoms reported.
    for ct in sorted(store.contacts.values(), key=lambda c: c["_seq"]):
        if (ct["status"] == "MONITORING" and now > ct["monitoring_end"]
                and not ct["symptom_onset_reported"]):
            ct["status"] = "CLEARED"
            touch(ct)
            transitions += 1

    # Work restrictions: ACTIVE -> EXPIRED when now >= end_date (half-open interval
    # fully elapsed).
    for r in sorted(store.restrictions.values(), key=lambda r: r["_seq"]):
        if r["status"] == "ACTIVE" and r["end_date"] is not None and now >= r["end_date"]:
            r["status"] = "EXPIRED"
            touch(r)
            emp = store.employees[r["employee_id"]]
            adjust_restriction_count(emp, -1)
            transitions += 1

    return transitions
