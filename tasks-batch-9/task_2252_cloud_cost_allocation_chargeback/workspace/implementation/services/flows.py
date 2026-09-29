"""Multi-entity workflows and cascades."""
from decimal import Decimal

from db import (
    base_fields,
    db,
    fmt_dt,
    now,
    ordered,
    touch,
)
from errors import fail
from services import derived
from services.calc import (
    BUDGET_PRESSURE_PCT,
    D,
    DISCOUNT_RATE,
    HOURS_PER_PERIOD,
    KIND_RANK,
    SPIKE_DELTA_MIN_CENTS,
    SPIKE_RATIO_MIN,
    distribute,
    remediation_verdict,
    rhu,
    rhu_cents,
    routed_queue_for,
    severity_band,
    severity_components,
    task_metrics,
)


# ==========================================================================
# allocation runs
# ==========================================================================
def in_scope_records(run):
    scope = None
    if run.get("scope_business_unit_id"):
        scope = derived.subtree_ids(run["scope_business_unit_id"])
    result = []
    for record in ordered(list(db.cost_records.values())):
        if record["allocation_state"] not in ("UNALLOCATED", "DISPUTED_HOLD"):
            continue
        if record["_billing_period_start_dt"] < run["_period_start_dt"]:
            continue
        if record["_billing_period_end_dt"] > run["_period_end_dt"]:
            continue
        if scope is not None and record["business_unit_id"] not in scope:
            continue
        result.append(record)
    return result


def _participant_basis(bu, pool):
    basis = pool.get("proportional_basis") or "SPEND"
    if basis == "HEADCOUNT":
        return D(bu["headcount"])
    if basis == "REVENUE":
        return D(bu["revenue_cents"])
    return D(bu["direct_spend_cents"])


def _new_line(run, bu_id, line_kind, method_applied, allocated_cents, **extra):
    line = base_fields(with_version=False)
    line.update(
        {
            "allocation_run_id": run["id"],
            "business_unit_id": bu_id,
            "shared_cost_pool_id": extra.get("shared_cost_pool_id"),
            "line_kind": line_kind,
            "method_applied": method_applied,
            "allocated_cents": allocated_cents,
            "basis_value": extra.get("basis_value", 0.00),
            "rounding_remainder_cents": extra.get("rounding_remainder_cents", 0),
            "memo": extra.get("memo"),
            "_cost_record_ids": extra.get("cost_record_ids", []),
        }
    )
    db.allocation_lines[line["id"]] = line
    return line


def manual_adjustment_line(run, bu_id, allocated_cents, memo):
    """Append a MANUAL_ADJUSTMENT line and refresh line_count (PRD 3.5)."""
    line = _new_line(run, bu_id, "MANUAL_ADJUSTMENT", "MANUAL", allocated_cents, memo=memo)
    run["line_count"] = len(derived.run_lines(run["id"]))
    touch(run)
    return line


def compute_run(run, variant):
    """Destructive rebuild of the run's line set (PRD 3.5)."""
    pools = derived.run_pools(run["id"])

    # ladder rung 24: ERR_NO_ELIGIBLE_PARTICIPANTS for every pool before any basis check
    plans = []
    for pool in pools:
        derived.pool_sync(pool, bump=False)
        eligible = []
        for bu_id in pool["participant_business_unit_ids"]:
            bu = db.business_units.get(bu_id)
            if bu is not None and bu["status"] == "ACTIVE":
                eligible.append(bu)
        if not eligible:
            fail(
                "ERR_NO_ELIGIBLE_PARTICIPANTS",
                "Shared cost pool %s has no ACTIVE participant business unit." % pool["id"],
            )
        plans.append((pool, ordered(eligible)))

    for pool, eligible in plans:
        if pool["methodology"] == "PROPORTIONAL":
            total = sum(_participant_basis(bu, pool) for bu in eligible)
            if total == 0:
                fail(
                    "ERR_PROPORTIONAL_BASIS_ZERO",
                    "Proportional basis total for pool %s is zero." % pool["id"],
                )

    scope = in_scope_records(run)

    # destructive: every existing line of the run is deleted, adjustments included
    for line_id in [l["id"] for l in derived.run_lines(run["id"])]:
        del db.allocation_lines[line_id]

    method = "LIST_BASIS" if variant == "PROVISIONAL" else "EFFECTIVE_BASIS"
    basis_field = "list_cost_cents" if variant == "PROVISIONAL" else "effective_cost_cents"

    direct = [r for r in scope if r["shared_cost_pool_id"] is None and r["business_unit_id"]]
    groups = {}
    for record in direct:
        groups.setdefault(record["business_unit_id"], []).append(record)
    bus = ordered([db.business_units[b] for b in groups if b in db.business_units])
    for bu in bus:
        records = groups[bu["id"]]
        _new_line(
            run,
            bu["id"],
            "DIRECT",
            method,
            sum(r[basis_field] for r in records),
            cost_record_ids=[r["id"] for r in records],
        )

    for pool, eligible in plans:
        pooled = pool["pooled_cost_cents"]
        record_ids = [r["id"] for r in derived.pool_records(pool["id"])]
        if pool["methodology"] == "PROPORTIONAL":
            bases = [_participant_basis(bu, pool) for bu in eligible]
            total = sum(bases)
            exact = [D(pooled) * basis / total for basis in bases]
            method_applied = "PROPORTIONAL"
        else:
            bases = [Decimal(0) for _ in eligible]
            exact = [D(pooled) / D(len(eligible)) for _ in eligible]
            method_applied = "EVEN_SPLIT"
        allocations, flags = distribute(pooled, exact)
        for index, bu in enumerate(eligible):
            _new_line(
                run,
                bu["id"],
                "SHARED",
                method_applied,
                allocations[index],
                shared_cost_pool_id=pool["id"],
                basis_value=float(rhu(bases[index], 2)),
                rounding_remainder_cents=flags[index],
                cost_record_ids=list(record_ids),
            )

    lines = derived.run_lines(run["id"])
    run["variant_applied"] = variant
    run["scoped_effective_cost_cents"] = sum(r["effective_cost_cents"] for r in scope)
    run["total_allocated_cents"] = sum(
        l["allocated_cents"] for l in lines if l["line_kind"] in ("DIRECT", "SHARED")
    )
    run["line_count"] = len(lines)
    run["status"] = "COMPUTED_PROVISIONAL" if variant == "PROVISIONAL" else "COMPUTED_FINAL"
    touch(run)
    return run


def publish_run(run, actor_id):
    run["status"] = "PUBLISHED"
    run["published_by_user_id"] = actor_id

    lines = derived.run_lines(run["id"])
    record_ids = []
    for line in lines:
        if line["line_kind"] not in ("DIRECT", "SHARED"):
            continue
        for rid in line.get("_cost_record_ids", []):
            if rid not in record_ids:
                record_ids.append(rid)
    for rid in record_ids:
        record = db.cost_records.get(rid)
        if record is None:
            continue
        record["allocation_state"] = "ALLOCATED"
        record["allocated_by_run_id"] = run["id"]
        touch(record)

    affected = []
    for line in lines:
        if line["business_unit_id"] not in affected:
            affected.append(line["business_unit_id"])

    if run["mode"] == "CHARGEBACK":
        for bu in ordered([db.business_units[b] for b in affected if b in db.business_units]):
            invoice = base_fields()
            invoice.update(
                {
                    "allocation_run_id": run["id"],
                    "business_unit_id": bu["id"],
                    "settlement_status": "UNBILLED",
                    "dispute_status": "NONE",
                    "gross_amount_cents": derived.bu_line_total(run["id"], bu["id"]),
                    "credited_amount_cents": 0,
                    "paid_amount_cents": 0,
                    "net_due_cents": 0,
                    "dispute_window_ends_at": None,
                    "issued_at": None,
                    "_payments": [],
                    "_write_off_memo": None,
                    "_issued_at_dt": None,
                    "_dispute_window_ends_at_dt": None,
                }
            )
            invoice["net_due_cents"] = invoice["gross_amount_cents"]
            db.chargeback_invoices[invoice["id"]] = invoice

    touch(run)
    for bu_id in affected:
        derived.bu_sync_id(bu_id)
    return run


def reopen_run(run):
    run["status"] = "REOPENED"
    run["reopen_count"] = run["reopen_count"] + 1

    affected = []
    for line in derived.run_lines(run["id"]):
        if line["business_unit_id"] not in affected:
            affected.append(line["business_unit_id"])

    for record in list(db.cost_records.values()):
        if record["allocated_by_run_id"] == run["id"]:
            record["allocation_state"] = "UNALLOCATED"
            record["allocated_by_run_id"] = None
            touch(record)

    for invoice in derived.run_invoices(run["id"]):
        if invoice["business_unit_id"] not in affected:
            affected.append(invoice["business_unit_id"])
        if invoice["settlement_status"] in ("UNBILLED", "ISSUED", "PARTIALLY_CREDITED"):
            invoice["settlement_status"] = "VOIDED"
            invoice["net_due_cents"] = 0
            touch(invoice)

    for line_id in [l["id"] for l in derived.run_lines(run["id"])]:
        del db.allocation_lines[line_id]
    run["total_allocated_cents"] = 0
    run["line_count"] = 0
    touch(run)

    for bu_id in affected:
        derived.bu_sync_id(bu_id)
    return run


# ==========================================================================
# commitments
# ==========================================================================
def apply_commitment_waterfall(commitment):
    capacity = commitment["hourly_commit_cents"] * HOURS_PER_PERIOD
    commitment["committed_capacity_cents"] = capacity

    if commitment["commitment_type"] == "RESERVED_INSTANCE":
        coverable = [commitment["covered_resource_kind"]]
    else:
        coverable = ["COMPUTE", "DATABASE"]

    candidates = [
        r
        for r in db.cost_records.values()
        if r["allocation_state"] == "UNALLOCATED"
        and r["applied_commitment_id"] is None
        and r["resource_kind"] in coverable
        and r["_billing_period_start_dt"] >= commitment["_term_start_dt"]
        and r["_billing_period_end_dt"] <= commitment["_term_end_dt"]
    ]
    candidates.sort(
        key=lambda r: (
            KIND_RANK.get(r["resource_kind"], 99),
            r["_billing_period_start_dt"],
            r["created_at"],
            r["_seq"],
        )
    )

    remaining = capacity
    total_discount = 0
    affected_bus = []
    rate = DISCOUNT_RATE[commitment["commitment_type"]]
    for record in candidates:
        if record["list_cost_cents"] <= remaining:
            discount = rhu_cents(D(record["list_cost_cents"]) * rate)
            record["effective_cost_cents"] = record["list_cost_cents"] - discount
            record["applied_commitment_id"] = commitment["id"]
            touch(record)
            total_discount += discount
            remaining -= record["list_cost_cents"]
            if record["business_unit_id"] and record["business_unit_id"] not in affected_bus:
                affected_bus.append(record["business_unit_id"])

    commitment["_in_scope_list_total"] = sum(r["list_cost_cents"] for r in candidates)
    commitment["total_discount_cents"] = total_discount
    commitment["status"] = "ACTIVE"
    values = derived.commitment_values(commitment)
    commitment.update(values)
    touch(commitment)

    for bu_id in affected_bus:
        derived.bu_sync_id(bu_id)
    return commitment


# ==========================================================================
# cloud resource / remediation cascades
# ==========================================================================
def terminate_resource(resource):
    resource["lifecycle_state"] = "TERMINATED"
    resource["monthly_run_rate_cents"] = 0
    touch(resource)

    commitments = []
    for record in list(db.cost_records.values()):
        if record["cloud_resource_id"] != resource["id"]:
            continue
        if record["allocation_state"] not in ("UNALLOCATED", "ALLOCATED"):
            continue
        record["allocation_state"] = "REVERSED"
        touch(record)
        if record["applied_commitment_id"] and record["applied_commitment_id"] not in commitments:
            commitments.append(record["applied_commitment_id"])

    for commitment_id in commitments:
        derived.commitment_sync(db.commitments.get(commitment_id))

    request = db.provisioning_requests.get(resource["provisioning_request_id"])
    if request is not None and request["status"] == "PROVISIONED":
        request["status"] = "TERMINATED"
        touch(request)

    derived.bu_sync_id(resource["business_unit_id"])
    return resource


def execute_task(task, status):
    task["status"] = status
    task["realized_savings_cents"] = task["projected_savings_cents"]
    resource = db.cloud_resources.get(task["cloud_resource_id"])
    touch(task)
    if resource is None:
        return task
    if task["kind"] == "RIGHTSIZE":
        if resource["lifecycle_state"] == "RIGHTSIZE_PENDING":
            resource["lifecycle_state"] = "RESIZED"
        resource["monthly_run_rate_cents"] = max(
            0, resource["monthly_run_rate_cents"] - task["realized_savings_cents"]
        )
        touch(resource)
        derived.bu_sync_id(resource["business_unit_id"])
    else:
        if resource["lifecycle_state"] != "TERMINATED":
            terminate_resource(resource)
    return task


def cancel_task(task):
    task["status"] = "CANCELLED"
    touch(task)
    resource = db.cloud_resources.get(task["cloud_resource_id"])
    if resource is None:
        return task
    if resource["lifecycle_state"] in ("FLAGGED_IDLE", "RIGHTSIZE_PENDING"):
        if not derived.has_open_task(resource["id"], exclude_id=task["id"]):
            resource["lifecycle_state"] = "ACTIVE"
            touch(resource)
    return task


def new_task(resource, kind, metrics):
    task = base_fields()
    task.update(
        {
            "cloud_resource_id": resource["id"],
            "kind": kind,
            "status": "PROPOSED",
            "observed_utilization_pct": metrics["observed_utilization_pct"],
            "waste_score": metrics["waste_score"],
            "projected_savings_cents": metrics["projected_savings_cents"],
            "realized_savings_cents": 0,
            "auto_remediation_eligible": metrics["auto_remediation_eligible"],
            "remediation_window_starts_at": None,
            "remediation_window_ends_at": None,
            "_window_start_dt": None,
            "_window_end_dt": None,
            "snooze_count": 0,
        }
    )
    db.remediation_tasks[task["id"]] = task
    return task


def idle_detection_scan(business_unit_id=None):
    candidates = [r for r in db.cloud_resources.values() if r["lifecycle_state"] == "ACTIVE"]
    if business_unit_id is not None:
        candidates = [r for r in candidates if r["business_unit_id"] == business_unit_id]
    candidates.sort(key=lambda r: (-r["monthly_run_rate_cents"], r["created_at"], r["_seq"]))

    created = []
    for resource in candidates:
        if derived.has_open_task(resource["id"]):
            continue
        kind, _savings = remediation_verdict(
            resource["utilization_pct"], resource["monthly_run_rate_cents"]
        )
        if kind is None:
            continue
        metrics = task_metrics(resource, kind)
        task = new_task(resource, kind, metrics)
        resource["lifecycle_state"] = (
            "FLAGGED_IDLE" if kind == "IDLE_TERMINATE" else "RIGHTSIZE_PENDING"
        )
        touch(resource)
        created.append(task)
    return created


def remediation_sweep():
    touched = []
    clock = now()
    for task in ordered(list(db.remediation_tasks.values())):
        if task["status"] == "APPROVED":
            execute_task(task, "EXECUTED")
            touched.append(task)
        elif task["status"] == "OWNER_NOTIFIED":
            window_end = task.get("_window_end_dt")
            if window_end is not None and clock > window_end:
                if task["auto_remediation_eligible"]:
                    execute_task(task, "AUTO_EXECUTED")
                else:
                    cancel_task(task)
                touched.append(task)
    return touched


# ==========================================================================
# disputes / cost record holds
# ==========================================================================
def hold_invoice_records(invoice):
    for rid in derived.invoice_record_ids(invoice):
        record = db.cost_records.get(rid)
        if record is None:
            continue
        if record["allocation_state"] == "ALLOCATED":
            record["allocation_state"] = "DISPUTED_HOLD"
            touch(record)


def release_invoice_records(invoice):
    for rid in derived.invoice_record_ids(invoice):
        record = db.cost_records.get(rid)
        if record is None:
            continue
        if record["allocation_state"] == "DISPUTED_HOLD":
            record["allocation_state"] = "ALLOCATED"
            touch(record)


# ==========================================================================
# anomaly detection
# ==========================================================================
def anomaly_scan(business_unit_id=None):
    units = [bu for bu in ordered(list(db.business_units.values())) if bu["status"] == "ACTIVE"]
    if business_unit_id is not None:
        units = [bu for bu in units if bu["id"] == business_unit_id]

    alerts = []
    for bu in units:
        records = [
            r
            for r in db.cost_records.values()
            if r["business_unit_id"] == bu["id"] and r["allocation_state"] != "REVERSED"
        ]
        records.sort(
            key=lambda r: (r["_billing_period_start_dt"], r["created_at"], r["_seq"]),
            reverse=True,
        )
        if len(records) < 4:
            continue
        observed = records[0]["effective_cost_cents"]
        baseline_exact = D(
            records[1]["effective_cost_cents"]
            + records[2]["effective_cost_cents"]
            + records[3]["effective_cost_cents"]
        ) / D(3)
        baseline = int(baseline_exact.to_integral_value(rounding="ROUND_FLOOR"))
        if baseline == 0:
            continue
        delta = observed - baseline
        ratio = rhu(D(observed) / D(baseline), 4)
        if not (ratio >= SPIKE_RATIO_MIN and delta >= SPIKE_DELTA_MIN_CENTS):
            continue

        budget_component = Decimal(0)
        instant = records[0]["_billing_period_start_dt"]
        breached = derived.covering_budget(bu["id"], instant, statuses=("BREACHED",))
        if breached is not None:
            budget_component = Decimal(20)
        else:
            budget = derived.covering_budget(
                bu["id"], instant, statuses=("DRAFT", "ACTIVE")
            )
            if budget is not None and budget["amount_cents"]:
                pressure = D(budget["actual_spend_cents"]) / D(budget["amount_cents"]) * 100
                if pressure >= BUDGET_PRESSURE_PCT:
                    budget_component = Decimal(12)

        score = severity_components(ratio, delta, budget_component)
        severity = severity_band(score)
        alert = base_fields()
        alert.update(
            {
                "business_unit_id": bu["id"],
                "root_cause_cloud_resource_id": None,
                "detected_at": fmt_dt(now()),
                "baseline_cents": baseline,
                "observed_cents": observed,
                "delta_cents": delta,
                "spike_ratio": float(ratio),
                "severity_score": float(score),
                "severity": severity,
                "routed_queue": routed_queue_for(severity),
                "status": "ROUTED",
                "root_cause_kind": None,
                "acknowledged_by_user_id": None,
            }
        )
        db.anomaly_alerts[alert["id"]] = alert
        alerts.append(alert)
    return alerts
