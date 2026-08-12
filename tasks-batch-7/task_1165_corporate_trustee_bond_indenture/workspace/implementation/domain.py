"""Derived-field recomputation, cross-entity cascades, and the logical-clock
sweep (PRD 2.5, 2.10 and the state-machine side effects of section 3)."""
from datetime import timedelta

from store import DB, now, now_iso, new_entity, mutate, touch


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def tranches_of(indenture_id):
    return [t for t in DB["tranches"].values() if t["indenture_id"] == indenture_id]


def positions_of_tranche(tranche_id):
    return [p for p in DB["positions"].values() if p["tranche_id"] == tranche_id]


def positions_of_indenture(indenture_id):
    ids = {t["id"] for t in tranches_of(indenture_id)}
    return [p for p in DB["positions"].values() if p["tranche_id"] in ids]


def runs_of_indenture(indenture_id):
    ids = {t["id"] for t in tranches_of(indenture_id)}
    return [r for r in DB["payment_runs"].values() if r["tranche_id"] in ids]


def records_of_run(run_id):
    return [r for r in DB["distribution_records"].values()
            if r["payment_run_id"] == run_id]


def cases_of_indenture(indenture_id):
    return [c for c in DB["default_cases"].values()
            if c["indenture_id"] == indenture_id]


def obligations_of(indenture_id):
    return [o for o in DB["covenant_obligations"].values()
            if o["indenture_id"] == indenture_id]


# ---------------------------------------------------------------------------
# Derived-field recomputation (PRD 2.10)
# ---------------------------------------------------------------------------

def recompute_tranche_outstanding(tranche):
    """original minus reductions from executed, non-reversed redemption runs."""
    reductions = 0
    for run in DB["payment_runs"].values():
        if (run["tranche_id"] == tranche["id"]
                and run["payment_type"] != "INTEREST"
                and run["distribution_status"] == "DISTRIBUTED"):
            reductions += sum(r["allocated_cents"] for r in records_of_run(run["id"]))
    mutate(tranche, outstanding_principal_cents=tranche["original_principal_cents"] - reductions)


def recompute_indenture_outstanding(indenture):
    total = sum(t["outstanding_principal_cents"]
                for t in tranches_of(indenture["id"]))
    mutate(indenture, outstanding_principal_cents=total)


def recompute_posture(indenture):
    obs = obligations_of(indenture["id"])
    if any(o["status"] == "BREACHED" for o in obs):
        posture = "BREACH"
    elif any(o["status"] == "LATE" for o in obs):
        posture = "GRACE"
    else:
        posture = "CURRENT"
    mutate(indenture, covenant_posture=posture)


def recompute_active_default_count(indenture):
    n = sum(1 for c in cases_of_indenture(indenture["id"])
            if c["status"] in ("CONFIRMED", "ACCELERATED"))
    mutate(indenture, active_default_count=n)


def recompute_account_totals(account):
    pos_ids = [p["id"] for p in DB["positions"].values()
               if p["noteholder_account_id"] == account["id"]]
    unpaid = received = 0
    for rec in DB["distribution_records"].values():
        if rec["position_id"] in pos_ids:
            if rec["status"] == "HELD":
                unpaid += rec["allocated_cents"]
            elif rec["status"] == "PAID":
                received += rec["allocated_cents"]
    mutate(account, total_unpaid_cents=unpaid, total_received_cents=received)


def recompute_all_account_totals():
    for acc in DB["noteholder_accounts"].values():
        recompute_account_totals(acc)


def eligible_principal(indenture_id):
    """Sum of principal over ACTIVE positions of tranches in ACTIVE/ACCELERATED."""
    total = 0
    for t in tranches_of(indenture_id):
        if t["status"] in ("ACTIVE", "ACCELERATED"):
            for p in positions_of_tranche(t["id"]):
                if p["status"] == "ACTIVE":
                    total += p["principal_amount_cents"]
    return total


def holder_aggregate_principal(indenture_id, account_id):
    """Holder's aggregate principal over ACTIVE positions of the indenture's
    ACTIVE/ACCELERATED tranches."""
    total = 0
    for t in tranches_of(indenture_id):
        if t["status"] in ("ACTIVE", "ACCELERATED"):
            for p in positions_of_tranche(t["id"]):
                if (p["status"] == "ACTIVE"
                        and p["noteholder_account_id"] == account_id):
                    total += p["principal_amount_cents"]
    return total


def recompute_direction_aggregates(direction):
    case = DB["default_cases"].get(direction["default_case_id"])
    if case is None:
        return
    eligible = eligible_principal(case["indenture_id"])
    supporting = sum(e["endorsed_principal_cents"]
                     for e in DB["direction_endorsements"].values()
                     if e["direction_id"] == direction["id"]
                     and e["status"] == "ACTIVE")
    mutate(direction, eligible_principal_cents=eligible,
           supporting_principal_cents=supporting)


def refresh_direction_effectiveness(direction):
    """Flip CIRCULATING <-> EFFECTIVE per the quorum tally."""
    from calc import quorum_effective
    met = quorum_effective(direction["instruction_type"],
                           direction["supporting_principal_cents"],
                           direction["eligible_principal_cents"])
    if met and direction["status"] == "CIRCULATING":
        mutate(direction, status="EFFECTIVE")
    elif not met and direction["status"] == "EFFECTIVE":
        mutate(direction, status="CIRCULATING")


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_indenture_defaulted(indenture):
    """Indenture ACTIVE -> DEFAULTED with the full suspension cascade."""
    if indenture["status"] == "ACTIVE":
        mutate(indenture, status="DEFAULTED")
    for run in runs_of_indenture(indenture["id"]):
        if run["distribution_status"] == "SCHEDULED":
            mutate(run, distribution_status="SUSPENDED")
        elif run["distribution_status"] == "DISTRIBUTED":
            for rec in records_of_run(run["id"]):
                if rec["status"] == "PENDING":
                    mutate(rec, status="HELD")
    recompute_all_account_totals()


def maybe_resume_indenture(indenture):
    """DEFAULTED -> ACTIVE when the last active default clears (resume cascade)."""
    recompute_active_default_count(indenture)
    if indenture["active_default_count"] == 0 and indenture["status"] == "DEFAULTED":
        mutate(indenture, status="ACTIVE")
        for run in runs_of_indenture(indenture["id"]):
            if run["distribution_status"] == "SUSPENDED":
                mutate(run, distribution_status="SCHEDULED")
            elif run["distribution_status"] == "DISTRIBUTED":
                for rec in records_of_run(run["id"]):
                    if rec["status"] == "HELD":
                        mutate(rec, status="PENDING")
        recompute_all_account_totals()


def cascade_accelerate(indenture):
    """Indenture DEFAULTED -> ACCELERATED; ACTIVE tranches -> ACCELERATED."""
    if indenture["status"] == "DEFAULTED":
        mutate(indenture, status="ACCELERATED")
    for t in tranches_of(indenture["id"]):
        if t["status"] == "ACTIVE":
            mutate(t, status="ACCELERATED")


def cascade_rescind_acceleration(indenture):
    """Indenture ACCELERATED -> DEFAULTED; ACCELERATED tranches -> ACTIVE."""
    if indenture["status"] == "ACCELERATED":
        mutate(indenture, status="DEFAULTED")
    for t in tranches_of(indenture["id"]):
        if t["status"] == "ACCELERATED":
            mutate(t, status="ACTIVE")


def bubble_up_satisfaction(indenture):
    """ACTIVE -> SATISFIED when every tranche is terminal (REDEEMED/MATURED)."""
    if indenture["status"] != "ACTIVE":
        return
    trs = tranches_of(indenture["id"])
    if trs and all(t["status"] in ("REDEEMED", "MATURED") for t in trs):
        mutate(indenture, status="SATISFIED")


def obligation_roll_forward(obligation):
    """Cyclic machine: status returns to OPEN, next_due_date advances by one
    frequency interval."""
    from validate import add_months, parse_date_strict
    months = {"QUARTERLY": 3, "SEMI_ANNUAL": 6, "ANNUAL": 12}[obligation["frequency"]]
    nd = parse_date_strict(obligation["next_due_date"])
    if nd is not None:
        obligation["next_due_date"] = add_months(nd, months).isoformat()
    if obligation["status"] in ("OPEN", "LATE", "BREACHED"):
        mutate(obligation, status="OPEN")
    else:
        touch(obligation)


def cure_linked_alleged_case(indenture, obligation):
    """Certificate ACCEPT while BREACHED: linked ALLEGED default -> CURED."""
    for c in cases_of_indenture(indenture["id"]):
        if c.get("source_ref") == obligation["id"] and c["status"] == "ALLEGED":
            mutate(c, status="CURED")
    maybe_resume_indenture(indenture)


def waive_linked_alleged_case(indenture, obligation):
    """Consent waiver cascade: linked ALLEGED default -> WAIVED."""
    for c in cases_of_indenture(indenture["id"]):
        if c.get("source_ref") == obligation["id"] and c["status"] == "ALLEGED":
            mutate(c, status="WAIVED")
    recompute_active_default_count(indenture)


# ---------------------------------------------------------------------------
# Logical-clock sweep (PRD 2.5)
# ---------------------------------------------------------------------------

def sweep():
    """Deterministic sweep run on every clock set: covenant delinquency ladder
    with breach case auto-creation, direction lapsing, distribution settlement."""
    today = now().date()
    # 1. Covenant obligations: OPEN -> LATE -> BREACHED (both rungs may fire
    #    in a single sweep when the clock jumps past both thresholds).
    touched_indentures = set()
    for ob in list(DB["covenant_obligations"].values()):
        from validate import parse_date_strict
        nd = parse_date_strict(ob["next_due_date"])
        if nd is None:
            continue
        if ob["status"] == "OPEN" and today > nd:
            mutate(ob, status="LATE")
            touched_indentures.add(ob["indenture_id"])
        if ob["status"] == "LATE" and today > nd + timedelta(days=ob["grace_period_days"]):
            mutate(ob, status="BREACHED")
            touched_indentures.add(ob["indenture_id"])
            from store import fmt_ts
            case = new_entity("default_cases")
            case.update({
                "indenture_id": ob["indenture_id"],
                "default_type": "COVENANT_BREACH",
                "source_ref": ob["id"],
                "declared_at": now_iso(),
                "cure_deadline": fmt_ts(now() + timedelta(days=30)),
                "status": "ALLEGED",
                "declared_by_user_id": None,
                "confirmed_by_user_id": None,
            })
    for ind_id in touched_indentures:
        ind = DB["indentures"].get(ind_id)
        if ind is not None:
            recompute_posture(ind)
            recompute_active_default_count(ind)
    # 2. Noteholder directions whose circulation deadline has passed lapse.
    for d in list(DB["directions"].values()):
        if d["status"] in ("CIRCULATING", "EFFECTIVE"):
            from validate import parse_datetime
            exp = parse_datetime(d["expires_at"])
            if exp is not None and now() > exp:
                mutate(d, status="LAPSED")
    # 3. Settlement: PENDING records of DISTRIBUTED runs due at/before today
    #    move to PAID — skipped while the indenture is DEFAULTED/ACCELERATED.
    from validate import parse_date_strict as pd_
    for run in list(DB["payment_runs"].values()):
        if run["distribution_status"] != "DISTRIBUTED":
            continue
        spd = pd_(run["scheduled_payment_date"])
        if spd is None or today < spd:
            continue
        tranche = DB["tranches"].get(run["tranche_id"])
        if tranche is None:
            continue
        ind = DB["indentures"].get(tranche["indenture_id"])
        if ind is None or ind["status"] in ("DEFAULTED", "ACCELERATED"):
            continue
        settled = False
        for rec in records_of_run(run["id"]):
            if rec["status"] == "PENDING":
                mutate(rec, status="PAID", paid_at=now_iso())
                settled = True
        if settled:
            recompute_all_account_totals()
