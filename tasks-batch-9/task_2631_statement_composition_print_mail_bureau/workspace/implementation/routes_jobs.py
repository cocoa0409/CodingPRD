"""Composition jobs: compose, presort, schedule, reconcile, close; and print runs."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
from core import (
    ALL_ROLES, DB, ROLE_BUREAU_ADMIN, ROLE_COMPOSITION_OPERATOR, ROLE_INTEGRITY_AUDITOR,
    ROLE_POSTAGE_CONTROLLER, ROLE_PRODUCTION_SCHEDULER, acting_user, base_row, ceil_div, fail,
    filter_value,
    json_body, now, opt_bool, opt_str, paginate, pagination, req_dt, req_enum, req_int,
    req_str, require_auth, respond, respond_list, serialize, sorted_rows, touch,
)
from routes_ref import template_insert_codes

bp = Blueprint("jobs", __name__)


# --------------------------------------------------------------------------- composition
@bp.route("/bureau/composition-jobs", methods=["POST"])
def job_compose():
    user_id, _role = require_auth((ROLE_COMPOSITION_OPERATOR,))
    body = json_body()
    data_file_id = req_str(body, "data_file_id")
    template_id = req_str(body, "template_id")
    rush_requested = opt_bool(body, "rush_requested", False)
    data_file = domain.file_or_404(data_file_id)
    template = domain.template_or_404(template_id)
    if template["client_id"] != data_file["client_id"]:
        fail("ERR_CLIENT_MISMATCH", "the template does not belong to the data file's client")
    client = domain.client_or_404(data_file["client_id"])
    if client["status"] == "SUSPENDED":
        fail("ERR_CLIENT_SUSPENDED", "client is SUSPENDED and may not compose jobs")
    if data_file["status"] != "ACCEPTED":
        fail("ERR_FILE_INVALID_STATE", "composition requires an ACCEPTED data file")
    if template["status"] != "ACTIVE":
        fail("ERR_TEMPLATE_NOT_ACTIVE", "composition requires an ACTIVE template version")

    known = domain.insert_by_code()
    clock = now()
    codes = template_insert_codes(template)
    unknown = [code for code in codes if code not in known]
    for code in codes:
        stock = known.get(code)
        if stock is None:
            continue
        if (stock["status"] != "ACTIVE"
                or stock["effective_from"] > clock
                or (stock["effective_to"] is not None and clock >= stock["effective_to"])):
            fail("ERR_INSERT_NOT_EFFECTIVE", "insert %s is not effective at the composition instant" % code)
    if unknown:
        fail("ERR_INSERT_CODE_UNKNOWN", "insert code %s does not exist" % unknown[0])

    records = domain.records_in_order(data_file_id)
    enrollments = {}
    for row in domain.enrollments_of_client(client["id"]):
        enrollments[row["account_ref"]] = row

    job = base_row()
    job.update({
        "client_id": client["id"],
        "data_file_id": data_file_id,
        "template_id": template_id,
        "composed_by_user_id": user_id,
        "composition_epoch": client["paperless_sync_epoch"],
        "rush_requested": rush_requested,
        "status": "COMPOSED",
        "integrity_status": "PENDING",
    })

    pieces = []
    for record in records:
        confidence = calc.hygiene_confidence(record)
        hygiene_status = calc.hygiene_disposition(confidence)
        enrollment = enrollments.get(record["account_ref"])
        suppressed = (
            enrollment is not None
            and enrollment["status"] == "ENROLLED"
            and enrollment.get("enrolled_epoch") is not None
            and enrollment["enrolled_epoch"] <= job["composition_epoch"]
        )
        built = calc.compose_sheets(template, record, known)
        domain.apply_changes(record, {
            "hygiene_confidence": confidence,
            "hygiene_status": hygiene_status,
            "delivery_channel": "ELECTRONIC" if suppressed else "PRINT",
            "computed_sheet_count": built["sheet_count"],
            "computed_insert_codes": list(built["insert_codes"]),
        })
        piece = base_row()
        piece.update({
            "composition_job_id": job["id"],
            "statement_record_id": record["id"],
            "presort_batch_id": None,
            "reprint_of_piece_id": None,
            "imb_barcode": calc.mint_barcode(
                client["client_code"], data_file["received_at"], record["sequence_no"]
            ),
            "piece_seq": record["sequence_no"],
            "sheet_count": built["sheet_count"],
            "insert_sheet_count": built["insert_sheet_count"],
            "color_page_count": built["color_page_count"],
            "insert_codes": list(built["insert_codes"]),
            "billable": True,
            "mail_class": "NONE_ELECTRONIC" if suppressed else template["mail_class_preference"],
            "presort_bucket": "PENDING",
            "piece_status": "SUPPRESSED" if suppressed else "COMPOSED",
            "integrity_status": "UNVERIFIED",
            "last_scan_stage": "NONE",
            "accepted_scan_count": 0,
            "undeliverable_flag": False,
        })
        pieces.append(piece)

    needed = {}
    for piece in pieces:
        if piece["piece_status"] == "SUPPRESSED":
            continue
        for code in piece["insert_codes"]:
            needed[code] = needed.get(code, 0) + 1
    for code in sorted(needed):
        stock = known.get(code)
        if stock is None or stock["on_hand_count"] < needed[code]:
            fail("ERR_INSERT_STOCK_INSUFFICIENT", "insert %s cannot cover %d copies" % (code, needed[code]))
    for code in sorted(needed):
        stock = known[code]
        stock["on_hand_count"] = stock["on_hand_count"] - needed[code]
        stock["reserved_count"] = stock["reserved_count"] + needed[code]
        touch(stock)

    for piece in pieces:
        DB.pieces[piece["id"]] = piece

    billable = [p for p in pieces if p["billable"]]
    printable = [p for p in pieces if p["piece_status"] not in ("SUPPRESSED", "VOID")]
    job.update({
        "expected_piece_count": len(records),
        "accountable_piece_count": len([p for p in pieces if p["piece_status"] != "VOID"]),
        "print_piece_count": len(printable),
        "electronic_piece_count": len([p for p in pieces if p["piece_status"] == "SUPPRESSED"]),
        "void_piece_count": 0,
        "reprint_piece_count": 0,
        "matched_piece_count": 0,
        "missing_scan_count": 0,
        "duplicate_scan_count": 0,
        "reprint_chain_depth": 0,
        "total_sheet_count": sum(p["sheet_count"] for p in billable),
        "print_sheet_count": sum(p["sheet_count"] for p in printable),
        "insert_sheet_total": sum(p["insert_sheet_count"] for p in billable),
        "color_page_count": sum(p["color_page_count"] for p in billable),
        "sla_due_at": data_file["accepted_at"] + timedelta(hours=client["sla_turnaround_hours"]),
        "sla_completed_at": None,
        "sla_hold_minutes": 0,
        "integrity_held_since": None,
        "projected_completion_at": None,
        "projected_penalty_cents": None,
        "assessed_penalty_cents": None,
        "composition_charge_cents": None,
        "insert_charge_cents": None,
        "pre_discount_subtotal_cents": None,
        "volume_discount_cents": None,
        "expedite_fee_cents": None,
        "billing_total_cents": None,
    })
    DB.jobs[job["id"]] = job

    data_file["status"] = "CONSUMED"
    touch(data_file)
    return respond(serialize(job), 201)


@bp.route("/bureau/composition-jobs/<job_id>", methods=["GET"])
def job_read(job_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.job_or_404(job_id)), 200)


@bp.route("/bureau/composition-jobs", methods=["GET"])
def job_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    client_id = filter_value("client_id")
    data_file_id = filter_value("data_file_id")
    template_id = filter_value("template_id")
    status = filter_value("status", calc.JOB_STATUSES)
    integrity_status = filter_value("integrity_status", calc.JOB_INTEGRITY_STATUSES)
    rows = list(DB.jobs.values())
    if client_id is not None:
        rows = [r for r in rows if r["client_id"] == client_id]
    if data_file_id is not None:
        rows = [r for r in rows if r["data_file_id"] == data_file_id]
    if template_id is not None:
        rows = [r for r in rows if r["template_id"] == template_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if integrity_status is not None:
        rows = [r for r in rows if r["integrity_status"] == integrity_status]
    rows = sorted_rows(rows, lambda r: (r["created_at"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/composition-jobs/<job_id>/integrity-summary", methods=["GET"])
def job_integrity_summary(job_id):
    require_auth((
        ROLE_BUREAU_ADMIN, ROLE_COMPOSITION_OPERATOR, ROLE_PRODUCTION_SCHEDULER,
        ROLE_POSTAGE_CONTROLLER, ROLE_INTEGRITY_AUDITOR,
    ))
    return respond(serialize(domain.job_or_404(job_id)), 200)


# --------------------------------------------------------------------------- presort
def _bucket_pass(residue, keyfunc, minimum, bucket, assigned):
    groups = {}
    for piece in residue:
        groups.setdefault(keyfunc(piece), []).append(piece)
    remaining = []
    for key in sorted(groups.keys()):
        group = groups[key]
        if len(group) >= minimum:
            for piece in group:
                assigned[piece["id"]] = bucket
        else:
            remaining.extend(group)
    return sorted(remaining, key=lambda p: (p["piece_seq"], p["_seq"]))


@bp.route("/bureau/composition-jobs/<job_id>/presort", methods=["POST"])
def job_presort(job_id):
    require_auth((ROLE_COMPOSITION_OPERATOR,))
    json_body()
    job = domain.job_or_404(job_id)
    if job["status"] != "COMPOSED":
        fail("ERR_JOB_INVALID_STATE", "presort requires a COMPOSED job")
    pieces = domain.pieces_in_order(job_id)
    if not [p for p in pieces if p["piece_status"] == "COMPOSED"]:
        fail("ERR_JOB_INVALID_STATE", "the job carries no COMPOSED pieces to sort")
    candidates = [p for p in pieces if p["piece_status"] not in ("SUPPRESSED", "VOID")]

    assigned = {}
    residue = []
    for piece in candidates:
        record = DB.records.get(piece["statement_record_id"])
        hygiene = record["hygiene_status"] if record else "PENDING"
        if hygiene in ("UNDELIVERABLE_AS_ADDRESSED", "STALE") or piece["sheet_count"] > calc.MAX_MACHINABLE_SHEETS:
            assigned[piece["id"]] = "NONMACHINABLE"
        else:
            residue.append(piece)

    def postal(piece):
        record = DB.records.get(piece["statement_record_id"])
        return (record["postal_code"] or "") if record else ""

    residue = _bucket_pass(residue, lambda p: postal(p), calc.MIN_FIVE_DIGIT_PIECES, "FIVE_DIGIT", assigned)
    residue = _bucket_pass(residue, lambda p: postal(p)[:3], calc.MIN_THREE_DIGIT_PIECES, "THREE_DIGIT", assigned)
    residue = _bucket_pass(residue, lambda p: postal(p)[:1], calc.MIN_AADC_PIECES, "AADC", assigned)
    for piece in residue:
        assigned[piece["id"]] = "MIXED_AADC"

    for mail_class in calc.MAIL_CLASS_CREATION_ORDER:
        for bucket in calc.BUCKET_CREATION_ORDER:
            members = [
                p for p in candidates
                if p["mail_class"] == mail_class and assigned.get(p["id"]) == bucket
            ]
            if not members:
                continue
            batch = base_row()
            batch.update({
                "composition_job_id": job_id,
                "entry_facility_id": None,
                "mail_class": mail_class,
                "presort_bucket": bucket,
                "piece_count": len([p for p in members if p["piece_status"] != "VOID"]),
                "tray_count": 0,
                "reserved_insert_sheets": sum(
                    p["insert_sheet_count"] for p in members if p["piece_status"] != "VOID"
                ),
                "estimated_postage_cents": None,
                "manifested_postage_cents": None,
                "postage_variance_cents": None,
                "induction_window_start": None,
                "induction_window_end": None,
                "status": "OPEN",
                "sealed_by_user_id": None,
                "manifested_by_user_id": None,
            })
            batch["tray_count"] = ceil_div(batch["piece_count"], calc.TRAY_CAPACITY_PIECES)
            DB.batches[batch["id"]] = batch
            for piece in members:
                domain.apply_changes(piece, {
                    "presort_bucket": bucket,
                    "presort_batch_id": batch["id"],
                })

    job["status"] = "PRESORTED"
    touch(job)
    return respond(serialize(job), 200)


# --------------------------------------------------------------------------- scheduling
@bp.route("/bureau/composition-jobs/<job_id>/schedule", methods=["POST"])
def job_schedule(job_id):
    require_auth((ROLE_PRODUCTION_SCHEDULER,))
    body = json_body()
    window_start = req_dt(body, "window_start")
    press_line_id = opt_str(body, "press_line_id")
    job = domain.job_or_404(job_id)
    named = domain.line_or_404(press_line_id) if press_line_id is not None else None
    if job["status"] != "PRESORTED":
        fail("ERR_JOB_INVALID_STATE", "scheduling requires a PRESORTED job")
    if named is not None and named["status"] != "AVAILABLE":
        fail("ERR_PRESS_LINE_UNAVAILABLE", "the named press line is in MAINTENANCE")
    client = domain.client_of_job(job)
    if client is not None and client["dr_readiness_required"]:
        site = domain.the_drsite()
        readiness = calc.dr_readiness(site)[0] if site is not None else None
        if readiness != "READY":
            fail("ERR_DR_SITE_NOT_READY", "the disaster-recovery site does not read READY")
    if window_start < now():
        fail("ERR_WINDOW_IN_PAST", "window_start is earlier than the current logical clock")

    template = DB.templates.get(job["template_id"])
    required = calc.press_requirements(job, template or {})
    planned = job["print_sheet_count"]

    if named is not None:
        run_minutes = calc.run_minutes_for(planned, named["sheets_per_hour"])
        window_end = window_start + timedelta(minutes=run_minutes)
        if not required.issubset(set(named["capabilities"])):
            fail("ERR_PRESS_LINE_CAPABILITY_MISMATCH", "the named press line lacks a required capability")
        if calc.window_conflicts(named, window_start, window_end):
            fail("ERR_PRESS_WINDOW_CONFLICT", "the requested window conflicts with existing work")
        if named["committed_sheet_count"] + planned > named["daily_sheet_capacity"]:
            fail("ERR_PRESS_CAPACITY_EXCEEDED", "the named press line has insufficient sheet headroom")
        line = named
        selection_mode = "EXPLICIT"
    else:
        candidates = []
        for candidate in DB.lines.values():
            if candidate["status"] != "AVAILABLE":
                continue
            if not required.issubset(set(candidate["capabilities"])):
                continue
            if candidate["daily_sheet_capacity"] - candidate["committed_sheet_count"] < planned:
                continue
            minutes = calc.run_minutes_for(planned, candidate["sheets_per_hour"])
            end = window_start + timedelta(minutes=minutes)
            if calc.window_conflicts(candidate, window_start, end):
                continue
            candidates.append((candidate, minutes, end))
        if not candidates:
            fail("ERR_NO_ELIGIBLE_PRESS_LINE", "no press line survives every eligibility predicate")
        ranked = sorted(
            candidates,
            key=lambda item: (
                -calc.line_score(item[0], required),
                -item[0]["sheets_per_hour"],
                item[0]["line_code"],
            ),
        )
        line, run_minutes, window_end = ranked[0]
        selection_mode = "SELECTED"

    run = base_row()
    run.update({
        "composition_job_id": job_id,
        "press_line_id": line["id"],
        "window_start": window_start,
        "window_end": window_end,
        "planned_sheet_count": planned,
        "run_minutes": run_minutes,
        "selection_score": calc.line_score(line, required),
        "selection_mode": selection_mode,
        "status": "PLANNED",
        "started_at": None,
        "completed_at": None,
        "printed_piece_count": 0,
        "abort_reason": "NONE",
    })
    DB.runs[run["id"]] = run

    domain.commit_line_sheets(line, planned)

    job["status"] = "SCHEDULED"
    job["projected_completion_at"] = window_end + timedelta(minutes=calc.FULFILMENT_LAG_MINUTES)
    job["projected_penalty_cents"] = calc.projected_penalty(client, job, job["projected_completion_at"])
    touch(job)
    return respond(serialize(run), 201)


# --------------------------------------------------------------------------- integrity reconciliation
@bp.route("/bureau/composition-jobs/<job_id>/reconcile-integrity", methods=["POST"])
def job_reconcile(job_id):
    require_auth((ROLE_INTEGRITY_AUDITOR,))
    json_body()
    job = domain.job_or_404(job_id)
    if job["status"] != "PRINTED":
        fail("ERR_JOB_INVALID_STATE", "reconciliation requires a PRINTED job")
    pieces = domain.pieces_in_order(job_id)
    accountable = [p for p in pieces if p["piece_status"] != "VOID"]
    printable = [p for p in pieces if p["piece_status"] not in ("SUPPRESSED", "VOID")]
    job["accountable_piece_count"] = len(accountable)
    job["print_piece_count"] = len(printable)
    for piece in printable:
        if piece["integrity_status"] == "SCAN_MATCHED":
            domain.apply_changes(piece, {"integrity_status": "RECONCILED"})
        elif piece["integrity_status"] == "UNVERIFIED":
            domain.apply_changes(piece, {"integrity_status": "SCAN_MISSING"})
    job["matched_piece_count"] = len([p for p in printable if p["integrity_status"] == "RECONCILED"])
    job["missing_scan_count"] = len([p for p in printable if p["integrity_status"] == "SCAN_MISSING"])
    job["duplicate_scan_count"] = len([p for p in printable if p["integrity_status"] == "DUPLICATE_SCAN"])
    job["reprint_chain_depth"] = domain.job_chain_depth(job_id)
    if (job["missing_scan_count"] == 0 and job["duplicate_scan_count"] == 0
            and job["matched_piece_count"] == job["print_piece_count"]):
        job["integrity_status"] = "MATCHED"
        job["status"] = "VERIFIED"
    else:
        job["integrity_status"] = "BREACHED"
        job["integrity_held_since"] = now()
        job["status"] = "INTEGRITY_HELD"
    touch(job)
    return respond(serialize(job), 200)


# --------------------------------------------------------------------------- commercial closure
@bp.route("/bureau/composition-jobs/<job_id>/close", methods=["POST"])
def job_close(job_id):
    require_auth((ROLE_BUREAU_ADMIN,))
    json_body()
    job = domain.job_or_404(job_id)
    if job["status"] != "MANIFESTED":
        fail("ERR_JOB_INVALID_STATE", "closure requires a MANIFESTED job")
    if acting_user() == job.get("composed_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES", "the composing operator may not close the job")
    client = domain.client_of_job(job)
    job["sla_completed_at"] = now()
    job["assessed_penalty_cents"] = calc.assessed_penalty(client, job, job["sla_completed_at"])
    figures = calc.billing_figures(job)
    for key in (
        "composition_charge_cents", "insert_charge_cents", "pre_discount_subtotal_cents",
        "volume_discount_cents", "expedite_fee_cents", "billing_total_cents",
    ):
        job[key] = figures[key]
    job["status"] = "CLOSED"
    touch(job)
    return respond(serialize(job), 200)


# --------------------------------------------------------------------------- print runs
@bp.route("/bureau/print-runs/<run_id>", methods=["GET"])
def run_read(run_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.run_or_404(run_id)), 200)


@bp.route("/bureau/print-runs", methods=["GET"])
def run_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    job_id = filter_value("composition_job_id")
    line_id = filter_value("press_line_id")
    status = filter_value("status", calc.RUN_STATUSES)
    rows = list(DB.runs.values())
    if job_id is not None:
        rows = [r for r in rows if r["composition_job_id"] == job_id]
    if line_id is not None:
        rows = [r for r in rows if r["press_line_id"] == line_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows, lambda r: (r["window_start"], r["created_at"]))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/print-runs/<run_id>/start", methods=["POST"])
def run_start(run_id):
    require_auth((ROLE_PRODUCTION_SCHEDULER,))
    json_body()
    run = domain.run_or_404(run_id)
    if run["status"] != "PLANNED":
        fail("ERR_RUN_INVALID_STATE", "only a PLANNED run may be started")
    line = DB.lines.get(run["press_line_id"])
    if line is None or line["status"] != "AVAILABLE":
        fail("ERR_PRESS_LINE_UNAVAILABLE", "the press line is not AVAILABLE")
    run["status"] = "RUNNING"
    run["started_at"] = now()
    touch(run)
    job = DB.jobs.get(run["composition_job_id"])
    if job is not None:
        job["status"] = "PRINTING"
        touch(job)
    return respond(serialize(run), 200)


@bp.route("/bureau/print-runs/<run_id>/complete", methods=["POST"])
def run_complete(run_id):
    require_auth((ROLE_PRODUCTION_SCHEDULER,))
    json_body()
    run = domain.run_or_404(run_id)
    if run["status"] != "RUNNING":
        fail("ERR_RUN_INVALID_STATE", "only a RUNNING run may be completed")
    job = DB.jobs.get(run["composition_job_id"])
    run["status"] = "COMPLETED"
    run["completed_at"] = now()
    run["printed_piece_count"] = len([
        p for p in domain.pieces_of_job(run["composition_job_id"])
        if p["piece_status"] in ("PRINTED", "INSERTED", "INDUCTED")
    ])
    touch(run)
    line = DB.lines.get(run["press_line_id"])
    if line is not None:
        domain.release_line_sheets(line, run["planned_sheet_count"])
    if job is not None:
        job["status"] = "PRINTED"
        touch(job)
    return respond(serialize(run), 200)


@bp.route("/bureau/print-runs/<run_id>/abort", methods=["POST"])
def run_abort(run_id):
    require_auth((ROLE_PRODUCTION_SCHEDULER,))
    body = json_body()
    abort_reason = req_enum(body, "abort_reason", calc.ABORT_REASONS)
    run = domain.run_or_404(run_id)
    if run["status"] != "RUNNING":
        fail("ERR_RUN_INVALID_STATE", "only a RUNNING run may be aborted")
    run["status"] = "ABORTED"
    run["completed_at"] = now()
    run["abort_reason"] = abort_reason
    touch(run)
    line = DB.lines.get(run["press_line_id"])
    if line is not None:
        domain.release_line_sheets(line, run["planned_sheet_count"])
    job = DB.jobs.get(run["composition_job_id"])
    if job is not None:
        for piece in domain.pieces_in_order(job["id"]):
            if piece["piece_status"] == "PRINTED" and piece["last_scan_stage"] == "PRINT":
                domain.apply_changes(piece, {
                    "piece_status": "COMPOSED",
                    "integrity_status": "UNVERIFIED",
                    "accepted_scan_count": 0,
                    "last_scan_stage": "NONE",
                })
        domain.recompute_print_sheet_count(job)
        job["projected_completion_at"] = None
        job["projected_penalty_cents"] = 0
        job["status"] = "PRESORTED"
        touch(job)
    return respond(serialize(run), 200)
