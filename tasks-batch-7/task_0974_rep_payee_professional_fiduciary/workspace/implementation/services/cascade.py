"""Cascade operations: client lifecycle, freeze, misuse, clock-driven."""

from datetime import datetime, timezone, timedelta

from db import store
from services.derived import recompute_client_rollups, recompute_bond_rollups


def freeze_account(account_id, now_iso):
    """Freeze an OPEN account. Rejects its pending disbursements."""
    acct = store.accounts.get(account_id)
    if not acct or acct["status"] != "OPEN":
        return
    acct["status"] = "FROZEN"
    acct["updated_at"] = now_iso
    acct["version"] += 1
    # freeze cascade: reject pending disbursements on this account
    for d in store.disbursements.values():
        if d["account_id"] != account_id:
            continue
        if d["status"] in ("REQUESTED", "PENDING_CONSERVATOR", "APPROVED"):
            d["status"] = "REJECTED"
            d["updated_at"] = now_iso
            d["version"] += 1


def unfreeze_account(account_id, now_iso):
    acct = store.accounts.get(account_id)
    if not acct or acct["status"] != "FROZEN":
        return
    acct["status"] = "OPEN"
    acct["updated_at"] = now_iso
    acct["version"] += 1


def cascade_client_suspend(client_id, now_iso):
    """Freeze every OPEN account of the client (cascades into disbursement rejects)."""
    for acct in list(store.accounts.values()):
        if acct["client_id"] == client_id and acct["status"] == "OPEN":
            freeze_account(acct["id"], now_iso)
    recompute_client_rollups(client_id)
    recompute_bond_rollups()


def cascade_client_terminate(client_id, now_iso):
    """Freeze accounts, terminate entitlements, supersede plans, lapse spend-downs."""
    for acct in list(store.accounts.values()):
        if acct["client_id"] == client_id and acct["status"] == "OPEN":
            freeze_account(acct["id"], now_iso)
    for ent in store.entitlements.values():
        if ent["client_id"] == client_id and ent["status"] in ("PENDING_VERIFICATION", "VERIFIED"):
            ent["status"] = "TERMINATED"
            ent["updated_at"] = now_iso
            ent["version"] += 1
    for p in store.budget_plans.values():
        if p["client_id"] == client_id and p["status"] in ("DRAFT", "PROPOSED", "APPROVED"):
            p["status"] = "SUPERSEDED"
            p["superseded_by_plan_id"] = None
            p["updated_at"] = now_iso
            p["version"] += 1
    for sp in store.spend_down_plans.values():
        if sp["client_id"] == client_id and sp["status"] in ("DRAFT", "ACTIVE"):
            sp["status"] = "LAPSED"
            sp["updated_at"] = now_iso
            sp["version"] += 1
    recompute_client_rollups(client_id)
    recompute_bond_rollups()


def cascade_misuse_confirmed(client_id, now_iso):
    """Audit misuse cascade: client ACTIVE -> SUSPENDED; accounts OPEN -> FROZEN; pending -> REJECTED."""
    c = store.clients.get(client_id)
    if not c:
        return
    if c["status"] == "ACTIVE":
        c["status"] = "SUSPENDED"
        c["updated_at"] = now_iso
        c["version"] += 1
        cascade_client_suspend(client_id, now_iso)
    else:
        # If not ACTIVE, the client stays as-is (the cascade is defined for ACTIVE)
        pass


def advance_clock(to_dt):
    """Set logical clock and evaluate time-driven transitions.

    - CourtOrder PETITIONED/GRANTED -> EXPIRED when clock date > expiry_date
    - SuretyBond ACTIVE -> LAPSED when clock date >= coverage_end_date
      OR premium_paid_through_date < clock date
    """
    store.clock = to_dt
    clock_date = to_dt.date()
    now_iso = _iso(to_dt)

    for o in store.court_orders.values():
        if o["status"] in ("PETITIONED", "GRANTED"):
            exp = o.get("expiry_date")
            if exp and clock_date > exp:
                o["status"] = "EXPIRED"
                o["updated_at"] = now_iso
                o["version"] += 1

    for b in store.bonds.values():
        if b["status"] == "ACTIVE":
            lapse = False
            if clock_date >= b["coverage_end_date"]:
                lapse = True
            if b["premium_paid_through_date"] < clock_date:
                lapse = True
            if lapse:
                b["status"] = "LAPSED"
                b["updated_at"] = now_iso
                b["version"] += 1


def _iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now_iso():
    return _iso(store.clock)


def clock_date():
    return store.clock.date()


def clock_month_str():
    d = store.clock.date()
    return f"{d.year:04d}-{d.month:02d}"
