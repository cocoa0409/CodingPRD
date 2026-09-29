"""In-memory data store.

Nothing is ever seeded here: every store starts empty on every boot and is only
populated through the declared API surface.
"""

import itertools
import uuid

from flask import g

import clock

projects = {}
geologic_models = {}
legacy_wellbores = {}
pore_space_tracts = {}
injection_well_permits = {}
monitoring_plans = {}
monitoring_methods = {}
financial_instruments = {}
injection_periods = {}
tax_credit_claims = {}
remediation_orders = {}

ALL_STORES = (
    projects,
    geologic_models,
    legacy_wellbores,
    pore_space_tracts,
    injection_well_permits,
    monitoring_plans,
    monitoring_methods,
    financial_instruments,
    injection_periods,
    tax_credit_claims,
    remediation_orders,
)

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_fields(with_version=True):
    stamp = clock.now_iso()
    row = {"id": new_id(), "created_at": stamp}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Bump a row's concurrency field once per request (PRD Section 2.8)."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = clock.now_iso()


def ordered(rows):
    """Default list ordering: created_at ascending, stable by insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def models_of(project_id):
    return ordered([m for m in geologic_models.values() if m["project_id"] == project_id])


def wellbores_of(project_id):
    return ordered([w for w in legacy_wellbores.values() if w["project_id"] == project_id])


def tracts_of(project_id):
    return ordered([t for t in pore_space_tracts.values() if t["project_id"] == project_id])


def permits_of(project_id):
    return ordered([p for p in injection_well_permits.values() if p["project_id"] == project_id])


def plans_of(project_id):
    return ordered([p for p in monitoring_plans.values() if p["project_id"] == project_id])


def methods_of(plan_id):
    return ordered([m for m in monitoring_methods.values() if m["monitoring_plan_id"] == plan_id])


def instruments_of(project_id):
    return ordered([i for i in financial_instruments.values() if i["project_id"] == project_id])


def periods_of_permit(permit_id):
    return ordered([r for r in injection_periods.values() if r["permit_id"] == permit_id])


def periods_of_project(project_id):
    permit_ids = {p["id"] for p in injection_well_permits.values() if p["project_id"] == project_id}
    return ordered([r for r in injection_periods.values() if r["permit_id"] in permit_ids])


def claims_of(project_id):
    return ordered([c for c in tax_credit_claims.values() if c["project_id"] == project_id])


def orders_of(project_id):
    return ordered([o for o in remediation_orders.values() if o["project_id"] == project_id])


def project_of_model(model):
    return projects.get(model["project_id"])


def project_of_permit(permit):
    return projects.get(permit["project_id"])


def project_of_plan(plan):
    return projects.get(plan["project_id"])


def project_of_method(method):
    plan = monitoring_plans.get(method["monitoring_plan_id"])
    return projects.get(plan["project_id"]) if plan else None


def project_of_period(record):
    permit = injection_well_permits.get(record["permit_id"])
    return projects.get(permit["project_id"]) if permit else None


def reset():
    for store in ALL_STORES:
        store.clear()
    clock.reset()
