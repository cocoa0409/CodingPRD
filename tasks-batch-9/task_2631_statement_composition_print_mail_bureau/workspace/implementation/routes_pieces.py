"""Mail pieces, scan events, reprints, undeliverable returns and presort batches."""
from flask import Blueprint

import calc
import domain
from core import (
    ALL_ROLES, DB, ROLE_INTEGRITY_AUDITOR, ROLE_POSTAGE_CONTROLLER, acting_user, append_row,
    base_row, fail, filter_bool, filter_value, json_body, now, opt_str, paginate, pagination,
    req_dt, req_enum, req_int, req_str, require_auth, respond, respond_list, serialize,
    sorted_rows, touch,
)

bp = Blueprint("pieces", __name__)

_NEXT_STATUS = {"PRINT": "PRINTED", "INSERT": "INSERTED", "INDUCT": "INDUCTED"}
_FROM_STATUS = {"PRINT": "COMPOSED", "INSERT": "PRINTED", "INDUCT": "INSERTED"}


# --------------------------------------------------------------------------- mail pieces
@bp.route("/bureau/mail-pieces/<piece_id>", methods=["GET"])
def piece_read(piece_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.piece_or_404(piece_id)), 200)


@bp.route("/bureau/mail-pieces", methods=["GET"])
def piece_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    job_id = filter_value("composition_job_id")
    record_id = filter_value("statement_record_id")
    batch_id = filter_value("presort_batch_id")
    reprint_of = filter_value("reprint_of_piece_id")
    piece_status = filter_value("piece_status", calc.PIECE_STATUSES)
    integrity_status = filter_value("integrity_status", calc.PIECE_INTEGRITY_STATUSES)
    presort_bucket = filter_value("presort_bucket", calc.PRESORT_BUCKETS)
    rows = list(DB.pieces.values())
    if job_id is not None:
        rows = [r for r in rows if r["composition_job_id"] == job_id]
    if record_id is not None:
        rows = [r for r in rows if r["statement_record_id"] == record_id]
    if batch_id is not None:
        rows = [r for r in rows if r["presort_batch_id"] == batch_id]
    if reprint_of is not None:
        rows = [r for r in rows if r["reprint_of_piece_id"] == reprint_of]
    if piece_status is not None:
        rows = [r for r in rows if r["piece_status"] == piece_status]
    if integrity_status is not None:
        rows = [r for r in rows if r["integrity_status"] == integrity_status]
    if presort_bucket is not None:
        rows = [r for r in rows if r["presort_bucket"] == presort_bucket]
    rows = sorted_rows(rows, lambda r: (r["piece_seq"], r["created_at"]))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/mail-pieces/<piece_id>/scan-events", methods=["GET"])
def piece_scan_events(piece_id):
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    stage = filter_value("stage", calc.SCAN_STAGES)
    accepted = filter_bool("accepted")
    domain.piece_or_404(piece_id)
    rows = domain.scans_of_piece(piece_id)
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    if accepted is not None:
        rows = [r for r in rows if r["accepted"] == accepted]
    rows = sorted_rows(rows, lambda r: (r["scanned_at"], r["created_at"]))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/mail-pieces/<piece_id>/undeliverable-returns", methods=["GET"])
def piece_returns(piece_id):
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    disposition = filter_value("disposition", calc.RETURN_DISPOSITIONS)
    domain.piece_or_404(piece_id)
    rows = domain.returns_of_piece(piece_id)
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    rows = sorted_rows(rows, lambda r: (r["created_at"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


# --------------------------------------------------------------------------- barcode scans
@bp.route("/bureau/mail-pieces/<piece_id>/scans", methods=["POST"])
def piece_scan(piece_id):
    require_auth((ROLE_INTEGRITY_AUDITOR,))
    body = json_body()
    stage = req_enum(body, "stage", calc.SCAN_STAGES)
    scanned_barcode = req_str(body, "scanned_barcode")
    device_code = req_str(body, "device_code")
    piece = domain.piece_or_404(piece_id)
    job = DB.jobs.get(piece["composition_job_id"])
    if job is None or job["status"] not in ("PRINTING", "PRINTED", "INTEGRITY_HELD"):
        fail("ERR_JOB_INVALID_STATE", "scans require a job in PRINTING, PRINTED or INTEGRITY_HELD")
    if piece["piece_status"] in ("SUPPRESSED", "VOID"):
        fail("ERR_PIECE_NOT_SCANNABLE", "a SUPPRESSED or VOID piece cannot be scanned")

    accepted = False
    reason = "NONE"
    if scanned_barcode != piece["imb_barcode"]:
        reason = "UNKNOWN_BARCODE"
    elif [s for s in domain.scans_of_piece(piece_id) if s["stage"] == stage and s["accepted"]]:
        reason = "DUPLICATE_STAGE"
    elif piece["piece_status"] != _FROM_STATUS[stage]:
        reason = "OUT_OF_SEQUENCE"
    else:
        accepted = True

    event = append_row()
    event.update({
        "mail_piece_id": piece_id,
        "stage": stage,
        "scanned_barcode": scanned_barcode,
        "device_code": device_code,
        "accepted": accepted,
        "rejection_reason": reason,
        "scanned_at": now(),
    })
    DB.scans[event["id"]] = event

    if accepted:
        piece["piece_status"] = _NEXT_STATUS[stage]
        piece["last_scan_stage"] = stage
        piece["accepted_scan_count"] = piece["accepted_scan_count"] + 1
        if stage == "INDUCT" and piece["integrity_status"] == "UNVERIFIED":
            piece["integrity_status"] = "SCAN_MATCHED"
        touch(piece)
    elif reason == "DUPLICATE_STAGE":
        piece["integrity_status"] = "DUPLICATE_SCAN"
        touch(piece)
    return respond(serialize(event), 201)


# --------------------------------------------------------------------------- reprints
@bp.route("/bureau/mail-pieces/<piece_id>/reprints", methods=["POST"])
def piece_reprint(piece_id):
    require_auth((ROLE_INTEGRITY_AUDITOR,))
    body = json_body()
    expected_version = req_int(body, "expected_composition_job_version")
    opt_str(body, "reprint_reason")
    piece = domain.piece_or_404(piece_id)
    job = DB.jobs.get(piece["composition_job_id"])
    if job is None or job["status"] != "INTEGRITY_HELD":
        fail("ERR_JOB_INVALID_STATE", "a reprint requires an INTEGRITY_HELD job")
    if (piece["integrity_status"] not in ("SCAN_MISSING", "DUPLICATE_SCAN")
            or piece["piece_status"] == "VOID"):
        fail("ERR_PIECE_NOT_REPRINT_ELIGIBLE", "the piece is not reprint-eligible")
    if expected_version != job["version"]:
        fail("ERR_STALE_COMPOSITION_JOB_VERSION", "expected_composition_job_version is stale")

    inserts = domain.insert_by_code()
    codes = list(piece["insert_codes"] or [])
    for code in codes:
        stock = inserts.get(code)
        if stock is None:
            continue
        if stock["on_hand_count"] + 1 < 1:
            fail("ERR_INSERT_STOCK_INSUFFICIENT", "insert %s cannot cover the replacement" % code)

    piece["piece_status"] = "VOID"
    touch(piece)

    replacement = base_row()
    replacement.update({
        "composition_job_id": piece["composition_job_id"],
        "statement_record_id": piece["statement_record_id"],
        "presort_batch_id": piece["presort_batch_id"],
        "reprint_of_piece_id": piece["id"],
        "imb_barcode": "%s-R%d" % (piece["imb_barcode"], domain.piece_depth(piece) + 1),
        "piece_seq": piece["piece_seq"],
        "sheet_count": piece["sheet_count"],
        "insert_sheet_count": piece["insert_sheet_count"],
        "color_page_count": piece["color_page_count"],
        "insert_codes": list(codes),
        "billable": False,
        "mail_class": piece["mail_class"],
        "presort_bucket": piece["presort_bucket"],
        "piece_status": "COMPOSED",
        "integrity_status": "UNVERIFIED",
        "last_scan_stage": "NONE",
        "accepted_scan_count": 0,
        "undeliverable_flag": False,
    })
    DB.pieces[replacement["id"]] = replacement

    for code in codes:
        stock = inserts.get(code)
        if stock is None:
            continue
        stock["on_hand_count"] = stock["on_hand_count"] + 1
        stock["reserved_count"] = stock["reserved_count"] - 1
        stock["on_hand_count"] = stock["on_hand_count"] - 1
        stock["reserved_count"] = stock["reserved_count"] + 1
        touch(stock)

    domain.recompute_piece_counters(job)
    job["matched_piece_count"] = 0
    job["missing_scan_count"] = 0
    job["duplicate_scan_count"] = 0
    domain.credit_hold_minutes(job)
    batch = DB.batches.get(piece["presort_batch_id"]) if piece["presort_batch_id"] else None
    if batch is not None:
        domain.recompute_batch(batch)
    job["integrity_status"] = "PENDING"
    job["status"] = "PRINTED"
    touch(job)
    return respond(serialize(replacement), 201)


# --------------------------------------------------------------------------- undeliverable returns
@bp.route("/bureau/undeliverable-returns", methods=["POST"])
def return_create():
    require_auth((ROLE_INTEGRITY_AUDITOR,))
    body = json_body()
    mail_piece_id = req_str(body, "mail_piece_id")
    reason_code = req_enum(body, "reason_code", calc.RETURN_REASON_CODES)
    piece = domain.piece_or_404(mail_piece_id)
    if domain.returns_of_piece(mail_piece_id):
        fail("ERR_RETURN_DUPLICATE", "an undeliverable return already exists for this piece")
    if piece["piece_status"] in ("SUPPRESSED", "VOID"):
        fail("ERR_PIECE_NOT_SCANNABLE", "a SUPPRESSED or VOID piece cannot be returned")
    row = base_row()
    row.update({
        "mail_piece_id": mail_piece_id,
        "reason_code": reason_code,
        "corrected_address_line1": None,
        "corrected_postal_code": None,
        "disposition": "SCANNED",
        "returned_at": now(),
        "classified_at": None,
        "feedback_sent_at": None,
        "feedback_batch_seq": None,
    })
    DB.returns[row["id"]] = row
    return respond(serialize(row), 201)


@bp.route("/bureau/undeliverable-returns/<return_id>", methods=["GET"])
def return_read(return_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.return_or_404(return_id)), 200)


@bp.route("/bureau/undeliverable-returns/<return_id>/classify", methods=["POST"])
def return_classify(return_id):
    require_auth((ROLE_INTEGRITY_AUDITOR,))
    body = json_body()
    corrected_line1 = opt_str(body, "corrected_address_line1")
    corrected_postal = opt_str(body, "corrected_postal_code")
    row = domain.return_or_404(return_id)
    if row["disposition"] != "SCANNED":
        fail("ERR_RETURN_INVALID_STATE", "only a SCANNED return may be classified")
    address_branch = (
        corrected_line1 is not None
        and corrected_postal is not None
        and row["reason_code"] != "DECEASED"
    )
    piece = DB.pieces.get(row["mail_piece_id"])
    record = DB.records.get(piece["statement_record_id"]) if piece is not None else None
    client = domain.client_of_return(row)
    row["classified_at"] = now()
    if address_branch:
        row["disposition"] = "ADDRESS_UPDATED"
        row["corrected_address_line1"] = corrected_line1
        row["corrected_postal_code"] = corrected_postal
    else:
        row["disposition"] = "UNRESOLVED"
        row["corrected_address_line1"] = None
        row["corrected_postal_code"] = None
    touch(row)
    if record is not None:
        if address_branch:
            record["address_line1"] = corrected_line1
            record["postal_code"] = corrected_postal
            record["hygiene_status"] = "CORRECTED"
        else:
            record["hygiene_status"] = "STALE"
        record["address_update_pending"] = True
        touch(record)
    if piece is not None:
        piece["undeliverable_flag"] = True
        touch(piece)
    if client is not None:
        client["pending_address_feedback_count"] = client["pending_address_feedback_count"] + 1
        touch(client)
    return respond(serialize(row), 200)


# --------------------------------------------------------------------------- presort batches
@bp.route("/bureau/presort-batches/<batch_id>", methods=["GET"])
def batch_read(batch_id):
    require_auth(ALL_ROLES)
    return respond(serialize(domain.batch_or_404(batch_id)), 200)


@bp.route("/bureau/presort-batches", methods=["GET"])
def batch_list():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    job_id = filter_value("composition_job_id")
    facility_id = filter_value("entry_facility_id")
    status = filter_value("status", calc.BATCH_STATUSES)
    bucket = filter_value("presort_bucket", calc.BATCH_BUCKETS)
    rows = list(DB.batches.values())
    if job_id is not None:
        rows = [r for r in rows if r["composition_job_id"] == job_id]
    if facility_id is not None:
        rows = [r for r in rows if r["entry_facility_id"] == facility_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if bucket is not None:
        rows = [r for r in rows if r["presort_bucket"] == bucket]
    rows = sorted_rows(rows, lambda r: (r["created_at"],))
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.route("/bureau/presort-batches/<batch_id>/seal", methods=["POST"])
def batch_seal(batch_id):
    user_id, _role = require_auth((ROLE_POSTAGE_CONTROLLER,))
    body = json_body()
    expected_client_version = req_int(body, "expected_client_version")
    batch = domain.batch_or_404(batch_id)
    job = DB.jobs.get(batch["composition_job_id"])
    if job is None or job["status"] != "VERIFIED":
        fail("ERR_JOB_INVALID_STATE", "sealing requires a VERIFIED job")
    if batch["status"] != "OPEN":
        fail("ERR_BATCH_NOT_OPEN", "only an OPEN batch may be sealed")
    client = DB.clients.get(job["client_id"])
    if client is None or expected_client_version != client["version"]:
        fail("ERR_STALE_CLIENT_VERSION", "expected_client_version is stale")
    estimated = 0
    for piece in domain.pieces_of_batch(batch_id):
        if piece["piece_status"] == "VOID":
            continue
        estimated += calc.piece_gross_postage(
            batch["mail_class"], batch["presort_bucket"], piece["sheet_count"]
        )
    if client["postage_escrow_available_cents"] < estimated:
        fail("ERR_POSTAGE_ESCROW_INSUFFICIENT", "the client's postage escrow cannot cover the estimate")
    batch["status"] = "SEALED"
    batch["estimated_postage_cents"] = estimated
    batch["sealed_by_user_id"] = user_id
    touch(batch)
    client["postage_committed_cents"] = client["postage_committed_cents"] + estimated
    client["postage_escrow_available_cents"] = client["postage_escrow_available_cents"] - estimated
    touch(client)
    return respond(serialize(batch), 200)


@bp.route("/bureau/presort-batches/<batch_id>/unseal", methods=["POST"])
def batch_unseal(batch_id):
    require_auth((ROLE_POSTAGE_CONTROLLER,))
    json_body()
    batch = domain.batch_or_404(batch_id)
    if batch["status"] != "SEALED":
        fail("ERR_BATCH_NOT_SEALED", "only a SEALED batch may be unsealed")
    released = batch["estimated_postage_cents"] or 0
    batch["status"] = "OPEN"
    batch["estimated_postage_cents"] = None
    batch["sealed_by_user_id"] = None
    touch(batch)
    job = DB.jobs.get(batch["composition_job_id"])
    client = DB.clients.get(job["client_id"]) if job is not None else None
    if client is not None:
        client["postage_committed_cents"] = client["postage_committed_cents"] - released
        client["postage_escrow_available_cents"] = client["postage_escrow_available_cents"] + released
        touch(client)
    return respond(serialize(batch), 200)


@bp.route("/bureau/presort-batches/<batch_id>/manifest", methods=["POST"])
def batch_manifest(batch_id):
    user_id, _role = require_auth((ROLE_POSTAGE_CONTROLLER,))
    body = json_body()
    facility_id = req_str(body, "entry_facility_id")
    window_start = req_dt(body, "induction_window_start")
    window_end = req_dt(body, "induction_window_end")
    batch = domain.batch_or_404(batch_id)
    facility = domain.facility_or_404(facility_id)
    if batch["status"] != "SEALED":
        fail("ERR_BATCH_NOT_SEALED", "only a SEALED batch may be manifested")
    if facility["status"] != "OPEN":
        fail("ERR_ENTRY_FACILITY_CLOSED", "the named entry facility is CLOSED")
    if user_id == batch.get("sealed_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES", "the sealing controller may not manifest the batch")
    if window_start >= window_end:
        fail("ERR_INVALID_INDUCTION_WINDOW", "induction_window_start must precede induction_window_end")
    span_minutes = (window_end - window_start).total_seconds() / 60.0
    if span_minutes > 1440:
        fail("ERR_INVALID_INDUCTION_WINDOW", "the induction window may not exceed 1440 minutes")
    committed = 0
    for other in DB.batches.values():
        if other["id"] == batch_id:
            continue
        if other["status"] != "MANIFESTED" or other["entry_facility_id"] != facility_id:
            continue
        if other["induction_window_start"] is None or other["induction_window_end"] is None:
            continue
        if window_start < other["induction_window_end"] and other["induction_window_start"] < window_end:
            committed += other["tray_count"]
    if committed + batch["tray_count"] > facility["tray_capacity_per_window"]:
        fail("ERR_INDUCTION_CAPACITY_EXCEEDED", "aggregate induction tray capacity would be exceeded")

    discount_bp = (
        facility["discount_bp_first_class"] if batch["mail_class"] == "FIRST_CLASS"
        else facility["discount_bp_marketing"]
    )
    manifested = 0
    for piece in domain.pieces_of_batch(batch_id):
        if piece["piece_status"] != "INDUCTED":
            continue
        gross = calc.piece_gross_postage(
            batch["mail_class"], batch["presort_bucket"], piece["sheet_count"]
        )
        manifested += calc.piece_net_postage(gross, discount_bp)
    variance = manifested - (batch["estimated_postage_cents"] or 0)
    job = DB.jobs.get(batch["composition_job_id"])
    client = DB.clients.get(job["client_id"]) if job is not None else None
    if client is not None and variance > 0 and variance > client["postage_escrow_available_cents"]:
        fail("ERR_POSTAGE_ESCROW_INSUFFICIENT", "the remaining escrow cannot cover the postage variance")

    batch["status"] = "MANIFESTED"
    batch["entry_facility_id"] = facility_id
    batch["induction_window_start"] = window_start
    batch["induction_window_end"] = window_end
    batch["manifested_postage_cents"] = manifested
    batch["postage_variance_cents"] = variance
    batch["manifested_by_user_id"] = user_id
    touch(batch)

    facility["committed_tray_count"] = facility["committed_tray_count"] + batch["tray_count"]
    touch(facility)

    if client is not None:
        client["postage_committed_cents"] = client["postage_committed_cents"] + variance
        client["postage_escrow_available_cents"] = client["postage_escrow_available_cents"] - variance
        touch(client)

    if job is not None:
        siblings = domain.batches_of_job(job["id"])
        if siblings and all(b["status"] == "MANIFESTED" for b in siblings):
            job["status"] = "MANIFESTED"
            touch(job)
            consumed = {}
            for piece in domain.pieces_of_job(job["id"]):
                if piece["piece_status"] in ("SUPPRESSED", "VOID"):
                    continue
                for code in piece["insert_codes"] or []:
                    consumed[code] = consumed.get(code, 0) + 1
            stocks = domain.insert_by_code()
            for code in sorted(consumed):
                stock = stocks.get(code)
                if stock is None:
                    continue
                stock["reserved_count"] = stock["reserved_count"] - consumed[code]
                stock["consumed_count"] = stock["consumed_count"] + consumed[code]
                touch(stock)
    return respond(serialize(batch), 200)
