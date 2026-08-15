"""Change-request apply/void, batch validation/execution/rollback, clock sweep."""
from datetime import timedelta

from errors import ApiError
from store import db
from services import (
    GOV_ATTR, MAX_RETRY, SENSITIVE, audit, bump, compute_priority, creates_cycle,
    derive_row_status, dq_screen, emit_event, is_salary_field, live_rows, make_row,
    open_exception, parse_gov_value, place_row, position_depth, resolve_salary,
    row_covers, subtree_height, valid_salary_literal,
)
from util import clock_date


# ------------------------------------------------------------ change requests
def apply_change_request(cr, actor, via_sweep=False):
    """Full §3.4 application gate (validation tiers 6-10) plus effects.

    via_sweep: clock-driven auto-application of position-targeted requests;
    the sweep fires exactly when clock >= effective_date, so the
    "effective_date on/after clock" gate (aimed at manual early applies)
    is skipped.
    """
    field = db.data_fields.get(cr["target_field_id"])
    if cr["status"] != "APPROVED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409,
                       "Change request is not APPROVED")
    worker = None
    if cr["target_worker_id"]:
        worker = db.workers.get(cr["target_worker_id"])
        if worker is None or worker["status"] != "ACTIVE":
            raise ApiError("ERR_WORKER_NOT_ACTIVE", 409, "Worker is not ACTIVE")
    if field is None or field["status"] != "ACTIVE":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409, "Data field is not ACTIVE")
    # tier 8: CRITICAL data-quality rules
    critical, warnings = dq_screen(field, cr["new_value"])
    if critical:
        raise ApiError("ERR_DQ_CRITICAL_VIOLATION", 422,
                       "An ACTIVE CRITICAL data-quality rule rejects the value")
    # tier 9: correction-mode policy
    row = None
    if cr["correction_mode"] == "CORRECT_HISTORY":
        if field["history_policy"] == "APPEND_ONLY":
            raise ApiError("ERR_CORRECTION_MODE_NOT_ALLOWED", 422,
                           "APPEND_ONLY field forbids CORRECT_HISTORY")
        if not cr["target_row_id"]:
            raise ApiError("ERR_CORRECTION_MODE_NOT_ALLOWED", 422,
                           "CORRECT_HISTORY requires target_row_id")
        row = db.assignments.get(cr["target_row_id"])
        if row is None:
            raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404,
                           "target_row_id does not exist")
    position = db.positions.get(cr["target_position_id"]) if cr["target_position_id"] else None
    # tier 9: hierarchy checks
    if cr["target_type"] == "POSITION_HIERARCHY":
        np = db.positions.get(str(cr["new_value"]))
        if np is None or np["status"] != "ACTIVE":
            raise ApiError("ERR_POSITION_NOT_ACTIVE", 409,
                           "New parent position does not exist or is not ACTIVE")
        if creates_cycle(position, np):
            raise ApiError("ERR_HIERARCHY_CYCLE", 409,
                           "Hierarchy change would create a cycle")
        if position_depth(np) + subtree_height(position["id"]) > 10:
            raise ApiError("ERR_HIERARCHY_DEPTH_EXCEEDED", 422,
                           "Resulting reporting chain deeper than 10 levels")
    # tier 10: temporal windows
    cdate = clock_date()
    if cr["target_worker_id"] and cr["correction_mode"] == "NEW_RECORD":
        D = cr["effective_date"]
        if D is None or D < cdate - timedelta(days=730) or D > cdate + timedelta(days=365):
            raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_WINDOW", 422,
                           "effective_date outside [clock-730d, clock+365d]")
    if cr["target_position_id"]:
        D = cr["effective_date"]
        if D is None or D > cdate + timedelta(days=365) or (
                not via_sweep and D < cdate):
            raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_WINDOW", 422,
                           "Position change effective_date must be on/after clock date")
    # ---- effects ----
    sensitive = field["sensitivity"] in SENSITIVE
    if cr["target_worker_id"]:
        if cr["correction_mode"] == "CORRECT_HISTORY":
            attr = GOV_ATTR[field["field_key"]]
            old = row[attr]
            cr["prior_value"] = None if old is None else str(old)
            row[attr] = parse_gov_value(field, cr["new_value"])
            bump(row)
            audit(actor, "CORRECT", worker_id=worker["id"], field_id=field["id"],
                  change_request_id=cr["id"], old_value=cr["prior_value"],
                  new_value=cr["new_value"])
            if cr["propagate_correction"]:
                for ch in field["downstream_channels"]:
                    emit_event("CORRECTION_PROPAGATED", ch, worker["id"],
                               change_request_id=cr["id"])
        else:
            D = cr["effective_date"]
            baseline, new_end, truncated, trunc_old_end = place_row(worker, D)
            attr = GOV_ATTR[field["field_key"]]
            attrs = {k: baseline[k] for k in
                     ("position_id", "salary_cents", "pay_grade", "location_code")}
            old_val = attrs[attr]
            attrs[attr] = parse_gov_value(field, cr["new_value"])
            new_row = make_row(worker["id"], cr["id"], attrs["position_id"],
                               attrs["salary_cents"], attrs["pay_grade"],
                               attrs["location_code"], D, new_end)
            cr["prior_row_end"] = trunc_old_end
            cr["_truncated_row_id"] = truncated["id"] if truncated else None
            cr["_inserted_row_id"] = new_row["id"]
            if sensitive:
                audit(actor, "APPLY", worker_id=worker["id"], field_id=field["id"],
                      change_request_id=cr["id"],
                      old_value=None if old_val is None else str(old_val),
                      new_value=cr["new_value"])
            for ch in field["downstream_channels"]:
                emit_event("CHANGE_APPLIED", ch, worker["id"],
                           change_request_id=cr["id"])
            bump(worker)
    else:
        if cr["target_type"] == "POSITION_HIERARCHY":
            old = position["parent_position_id"]
            cr["prior_value"] = old
            position["parent_position_id"] = str(cr["new_value"])
        elif field["field_key"] == "position.parent_position_id":
            old = position["parent_position_id"]
            cr["prior_value"] = old
            position["parent_position_id"] = str(cr["new_value"])
        else:
            attr = "title" if field["field_key"] == "position.title" else "department"
            old = position[attr]
            cr["prior_value"] = old
            position[attr] = cr["new_value"]
        bump(position)
        if sensitive:
            audit(actor, "APPLY", field_id=field["id"], change_request_id=cr["id"],
                  old_value=old, new_value=cr["new_value"])
        # position changes are internal: no integration events
    cr["status"] = "APPLIED"
    bump(cr)
    for r in warnings:
        open_exception(rule_id=r["id"], change_request_id=cr["id"], batch_id=None,
                       integration_event_id=None,
                       worker_id=worker["id"] if worker else None,
                       field_id=field["id"], observed_value=cr["new_value"])
    return cr


def void_change_request(cr, actor):
    if cr["status"] != "APPLIED":
        raise ApiError("ERR_REQUEST_INVALID_STATE", 409,
                       "Only an APPLIED change request can be voided")
    for other in db.change_requests.values():
        if other["id"] == cr["id"] or other["status"] != "APPLIED":
            continue
        same_target = (other["target_field_id"] == cr["target_field_id"] and
                       other["target_worker_id"] == cr["target_worker_id"] and
                       other["target_position_id"] == cr["target_position_id"])
        if same_target and (other["created_at"], other["_seq"]) > (cr["created_at"], cr["_seq"]):
            raise ApiError("ERR_REQUEST_INVALID_STATE", 409,
                           "A later APPLIED change exists for the same target and field")
    field = db.data_fields.get(cr["target_field_id"])
    if cr["target_worker_id"]:
        worker = db.workers.get(cr["target_worker_id"])
        if cr["correction_mode"] == "CORRECT_HISTORY":
            row = db.assignments.get(cr["target_row_id"])
            if row is not None and field is not None:
                attr = GOV_ATTR[field["field_key"]]
                pv = cr["prior_value"]
                row[attr] = (parse_gov_value(field, pv) if pv is not None else None)
                bump(row)
        else:
            ins = db.assignments.get(cr.get("_inserted_row_id") or "")
            if ins is not None and ins["row_status"] != "VOIDED":
                ins["row_status"] = "VOIDED"
                bump(ins)
            tr = db.assignments.get(cr.get("_truncated_row_id") or "")
            if tr is not None:
                tr["effective_end_date"] = cr["prior_row_end"]
                bump(tr)
        if worker is not None:
            bump(worker)
        wid = worker["id"] if worker else None
    else:
        position = db.positions.get(cr["target_position_id"])
        if position is not None and field is not None:
            if cr["target_type"] == "POSITION_HIERARCHY" or field["field_key"] == "position.parent_position_id":
                position["parent_position_id"] = cr["prior_value"]
            else:
                attr = "title" if field["field_key"] == "position.title" else "department"
                position[attr] = cr["prior_value"]
            bump(position)
        wid = None
    audit(actor, "VOID", worker_id=wid,
          field_id=field["id"] if field else None, change_request_id=cr["id"],
          old_value=cr["new_value"], new_value=cr["prior_value"])
    channels = []
    for e in db.events.values():
        if e["change_request_id"] == cr["id"] and e["event_type"] in (
                "CHANGE_APPLIED", "CORRECTION_PROPAGATED"):
            if e["channel"] not in channels:
                channels.append(e["channel"])
    for ch in channels:
        emit_event("REVERSAL", ch, wid, change_request_id=cr["id"])
    cr["status"] = "VOIDED"
    bump(cr)
    return cr


# ------------------------------------------------------------------- batches
def _prior_row_for(worker_id, D, rows):
    covering = None
    earlier = []
    for r in rows:
        if r["worker_id"] != worker_id or r["row_status"] == "VOIDED":
            continue
        if row_covers(r, D):
            covering = r
        elif r["effective_start_date"] < D:
            earlier.append(r)
    if covering is not None:
        return covering
    if earlier:
        earlier.sort(key=lambda r: (r["effective_start_date"], r["_seq"]))
        return earlier[-1]
    return None


def validate_line(line, dq_rows=None):
    """Per-line validation in tier order; returns error_id or None."""
    worker = db.workers.get(line["target_worker_id"])
    if worker is None:
        return "ERR_WORKER_NOT_FOUND"
    if worker["status"] != "ACTIVE":
        return "ERR_WORKER_NOT_ACTIVE"
    field = db.data_fields.get(line["target_field_id"])
    if field is None:
        return "ERR_DATA_FIELD_NOT_FOUND"
    if field["status"] != "ACTIVE":
        return "ERR_FIELD_NOT_ACTIVE"
    D = line["effective_date"]
    rows = live_rows(worker["id"])
    prior_row = _prior_row_for(worker["id"], D, dq_rows if dq_rows is not None else rows)
    if is_salary_field(field):
        value_str = (str(resolve_salary(line["new_value"], prior_row["salary_cents"]))
                     if prior_row is not None else line["new_value"])
    else:
        value_str = line["new_value"]
    critical, _ = dq_screen(field, value_str)
    if critical:
        return "ERR_DQ_CRITICAL_VIOLATION"
    if field["sensitivity"] == "RESTRICTED":
        return "ERR_RESTRICTED_FIELD_IN_BATCH"
    for r in rows:
        if r["effective_start_date"] == D:
            return "ERR_EFFECTIVE_PERIOD_OVERLAP"
    if prior_row is None:
        return "ERR_INVALID_REQUEST"
    cdate = clock_date()
    if D < cdate - timedelta(days=730) or D > cdate + timedelta(days=365):
        return "ERR_EFFECTIVE_DATE_OUT_OF_WINDOW"
    return None


def execute_batch(batch, actor):
    """Sequential line re-validation + application in line_index ASC order."""
    lines = [l for l in db.batch_lines.values() if l["batch_id"] == batch["id"]]
    lines.sort(key=lambda l: (l["line_index"], l["created_at"], l["_seq"]))
    # Pre-execution row snapshot for prior-salary resolution (§3.5).
    pre_rows = [dict(r) for r in db.assignments.values()]
    for line in lines:
        if line["status"] != "VALIDATED":
            continue
        err = validate_line(line, dq_rows=pre_rows)
        if err is not None:
            line["status"] = "FAILED"
            line["error_id"] = err
            bump(line)
            continue
        worker = db.workers[line["target_worker_id"]]
        field = db.data_fields[line["target_field_id"]]
        D = line["effective_date"]
        baseline, new_end, truncated, trunc_old_end = place_row(worker, D)
        attrs = {k: baseline[k] for k in
                 ("position_id", "salary_cents", "pay_grade", "location_code")}
        pre_row = _prior_row_for(worker["id"], D, pre_rows)
        prior_salary = pre_row["salary_cents"] if pre_row is not None else baseline["salary_cents"]
        old_val = attrs[GOV_ATTR[field["field_key"]]]
        if is_salary_field(field):
            new_salary = resolve_salary(line["new_value"], prior_salary)
            attrs["salary_cents"] = new_salary
            line["resolved_delta_cents"] = new_salary - prior_salary
            applied_value_str = str(new_salary)
        else:
            attrs[GOV_ATTR[field["field_key"]]] = parse_gov_value(field, line["new_value"])
            line["resolved_delta_cents"] = None
            applied_value_str = line["new_value"]
        new_row = make_row(worker["id"], None, attrs["position_id"],
                           attrs["salary_cents"], attrs["pay_grade"],
                           attrs["location_code"], D, new_end)
        line["_inserted_row_id"] = new_row["id"]
        line["_truncated_row_id"] = truncated["id"] if truncated else None
        line["_truncated_old_end"] = trunc_old_end
        line["_prior_value"] = None if old_val is None else str(old_val)
        line["_channels"] = list(field["downstream_channels"])
        if field["sensitivity"] in SENSITIVE:
            audit(actor, "BATCH_APPLY", worker_id=worker["id"], field_id=field["id"],
                  batch_id=batch["id"],
                  old_value=None if old_val is None else str(old_val),
                  new_value=applied_value_str)
        for ch in field["downstream_channels"]:
            emit_event("CHANGE_APPLIED", ch, worker["id"], batch_id=batch["id"])
        _, warnings = dq_screen(field, applied_value_str)
        for r in warnings:
            open_exception(rule_id=r["id"], change_request_id=None,
                           batch_id=batch["id"], integration_event_id=None,
                           worker_id=worker["id"], field_id=field["id"],
                           observed_value=line["new_value"])
        bump(worker)
        line["status"] = "APPLIED"
        line["error_id"] = None
        bump(line)
    any_failed = any(l["status"] == "FAILED" for l in lines)
    batch["status"] = "COMPLETED_WITH_ERRORS" if any_failed else "COMPLETED"
    bump(batch)
    return batch


def rollback_batch(batch, actor):
    lines = [l for l in db.batch_lines.values() if l["batch_id"] == batch["id"]]
    applied = [l for l in lines if l["status"] == "APPLIED"]
    applied.sort(key=lambda l: (l["line_index"], l["created_at"], l["_seq"]), reverse=True)
    # Original batch events still QUEUED -> CANCELLED (before emitting reversals).
    for e in db.events.values():
        if e["batch_id"] == batch["id"] and e["status"] == "QUEUED" and \
                e["event_type"] in ("CHANGE_APPLIED", "CORRECTION_PROPAGATED"):
            e["status"] = "CANCELLED"
            bump(e)
    for line in applied:
        ins = db.assignments.get(line.get("_inserted_row_id") or "")
        if ins is not None and ins["row_status"] != "VOIDED":
            ins["row_status"] = "VOIDED"
            bump(ins)
        tr = db.assignments.get(line.get("_truncated_row_id") or "")
        if tr is not None:
            tr["effective_end_date"] = line.get("_truncated_old_end")
            bump(tr)
        audit(actor, "BATCH_VOID", worker_id=line["target_worker_id"],
              field_id=line["target_field_id"], batch_id=batch["id"],
              old_value=line["new_value"], new_value=line.get("_prior_value"))
        for ch in line.get("_channels", []):
            emit_event("REVERSAL", ch, line["target_worker_id"], batch_id=batch["id"])
        worker = db.workers.get(line["target_worker_id"])
        if worker is not None:
            bump(worker)
        line["status"] = "ROLLED_BACK"
        bump(line)
    batch["status"] = "ROLLED_BACK"
    bump(batch)
    return batch


# ---------------------------------------------------------------- clock sweep
def sweep():
    """Re-evaluate every time-driven rule after a logical-clock advance (§2.5)."""
    cdate = clock_date()
    # assignment row_status derivation
    for r in db.assignments.values():
        if r["row_status"] == "VOIDED":
            continue
        new = derive_row_status(r["effective_start_date"], r["effective_end_date"], cdate)
        if new != r["row_status"]:
            r["row_status"] = new
            bump(r)
    # grants: APPROVED->PROVISIONED inside window; APPROVED/PROVISIONED->EXPIRED past it
    for g in db.grants.values():
        if g["status"] == "APPROVED":
            if cdate > g["valid_until"]:
                g["status"] = "EXPIRED"
                bump(g)
            elif g["valid_from"] <= cdate:
                g["status"] = "PROVISIONED"
                bump(g)
        elif g["status"] == "PROVISIONED":
            if cdate > g["valid_until"]:
                g["status"] = "EXPIRED"
                bump(g)
    # waived exceptions reopen once the waiver lapses
    for x in db.exceptions.values():
        if x["status"] == "WAIVED" and x["waiver_expiry_date"] is not None \
                and cdate > x["waiver_expiry_date"]:
            x["status"] = "OPEN"
            x["waiver_expiry_date"] = None
            bump(x)
    # approved position-targeted change requests apply at effective_date
    crs = sorted(db.change_requests.values(), key=lambda c: (c["created_at"], c["_seq"]))
    for cr in crs:
        if cr["status"] == "APPROVED" and cr["target_position_id"] and \
                cr["effective_date"] is not None and cr["effective_date"] <= cdate:
            try:
                apply_change_request(cr, "system", via_sweep=True)
            except ApiError:
                pass
    # scheduled batches auto-execute
    for b in sorted(db.batches.values(), key=lambda b: (b["created_at"], b["_seq"])):
        if b["status"] == "SCHEDULED" and b["scheduled_effective_date"] is not None \
                and b["scheduled_effective_date"] <= cdate:
            execute_batch(b, "system")
    # exception priority scores recomputed (age grows with the clock)
    for x in db.exceptions.values():
        s = compute_priority(x)
        if s != x["priority_score"]:
            x["priority_score"] = s
            bump(x)


# ------------------------------------------------------------ event lifecycle
def dispatch_event(ev, outcome):
    if ev["status"] != "QUEUED":
        raise ApiError("ERR_EVENT_INVALID_STATE", 409, "Dispatch requires QUEUED")
    if outcome == "ACKNOWLEDGED":
        ev["status"] = "ACKNOWLEDGED"
    else:  # FAILED
        ev["retry_count"] += 1
        if ev["retry_count"] >= MAX_RETRY:
            ev["status"] = "DEAD_LETTERED"
            open_exception(rule_id=None, change_request_id=ev["change_request_id"],
                           batch_id=ev["batch_id"], integration_event_id=ev["id"],
                           worker_id=ev["worker_id"], field_id=None,
                           observed_value=None)
        else:
            ev["status"] = "FAILED"
    bump(ev)
    return ev
