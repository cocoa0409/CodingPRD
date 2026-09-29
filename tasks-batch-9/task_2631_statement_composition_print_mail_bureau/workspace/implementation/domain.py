"""Shared lookups, ledger helpers and roll-up recomputation."""
import calc
from core import DB, ceil_div, fail, half_up, minutes_between, now, touch


# --------------------------------------------------------------------------- lookups
def find(store, row_id, error_id):
    row = store.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "referenced resource %s was not found" % row_id)
    return row


def client_or_404(row_id):
    return find(DB.clients, row_id, "ERR_CLIENT_NOT_FOUND")


def template_or_404(row_id):
    return find(DB.templates, row_id, "ERR_TEMPLATE_NOT_FOUND")


def file_or_404(row_id):
    return find(DB.files, row_id, "ERR_DATA_FILE_NOT_FOUND")


def record_or_404(row_id):
    return find(DB.records, row_id, "ERR_RECORD_NOT_FOUND")


def job_or_404(row_id):
    return find(DB.jobs, row_id, "ERR_JOB_NOT_FOUND")


def piece_or_404(row_id):
    return find(DB.pieces, row_id, "ERR_MAIL_PIECE_NOT_FOUND")


def line_or_404(row_id):
    return find(DB.lines, row_id, "ERR_PRESS_LINE_NOT_FOUND")


def run_or_404(row_id):
    return find(DB.runs, row_id, "ERR_PRINT_RUN_NOT_FOUND")


def facility_or_404(row_id):
    return find(DB.facilities, row_id, "ERR_ENTRY_FACILITY_NOT_FOUND")


def batch_or_404(row_id):
    return find(DB.batches, row_id, "ERR_PRESORT_BATCH_NOT_FOUND")


def return_or_404(row_id):
    return find(DB.returns, row_id, "ERR_RETURN_NOT_FOUND")


def enrollment_or_404(row_id):
    return find(DB.enrollments, row_id, "ERR_ENROLLMENT_NOT_FOUND")


def drsite_or_404(row_id):
    return find(DB.drsites, row_id, "ERR_DR_SITE_NOT_FOUND")


# --------------------------------------------------------------------------- collections
def records_of_file(file_id):
    return [r for r in DB.records.values() if r["data_file_id"] == file_id]


def records_in_order(file_id):
    return sorted(records_of_file(file_id), key=lambda r: (r["sequence_no"], r["_seq"]))


def pieces_of_job(job_id):
    return [p for p in DB.pieces.values() if p["composition_job_id"] == job_id]


def pieces_in_order(job_id):
    return sorted(pieces_of_job(job_id), key=lambda p: (p["piece_seq"], p["created_at"], p["_seq"]))


def pieces_of_batch(batch_id):
    return [p for p in DB.pieces.values() if p["presort_batch_id"] == batch_id]


def batches_of_job(job_id):
    return [b for b in DB.batches.values() if b["composition_job_id"] == job_id]


def enrollments_of_client(client_id):
    return [e for e in DB.enrollments.values() if e["client_id"] == client_id]


def scans_of_piece(piece_id):
    return [s for s in DB.scans.values() if s["mail_piece_id"] == piece_id]


def returns_of_piece(piece_id):
    return [r for r in DB.returns.values() if r["mail_piece_id"] == piece_id]


def insert_by_code():
    return dict((row["insert_code"], row) for row in DB.inserts.values())


def the_drsite():
    for row in DB.drsites.values():
        return row
    return None


def client_of_job(job):
    return DB.clients.get(job["client_id"])


def client_of_return(ret):
    piece = DB.pieces.get(ret["mail_piece_id"])
    if piece is None:
        return None
    job = DB.jobs.get(piece["composition_job_id"])
    if job is None:
        return None
    return DB.clients.get(job["client_id"])


# --------------------------------------------------------------------------- mutation helper
def apply_changes(row, changes):
    """Assign only the fields that actually change; bump version once when any did."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


# --------------------------------------------------------------------------- reprint chain
def piece_depth(piece):
    depth = 0
    seen = set()
    cursor = piece
    while cursor is not None and cursor.get("reprint_of_piece_id"):
        if cursor["id"] in seen:
            break
        seen.add(cursor["id"])
        depth += 1
        cursor = DB.pieces.get(cursor["reprint_of_piece_id"])
    return depth


def job_chain_depth(job_id):
    depths = [piece_depth(p) for p in pieces_of_job(job_id)]
    return max(depths) if depths else 0


# --------------------------------------------------------------------------- roll-ups
PRINTABLE_EXCLUDED = ("SUPPRESSED", "VOID")


def printable_pieces(job_id):
    return [p for p in pieces_of_job(job_id) if p["piece_status"] not in PRINTABLE_EXCLUDED]


def accountable_pieces(job_id):
    return [p for p in pieces_of_job(job_id) if p["piece_status"] != "VOID"]


def recompute_piece_counters(job):
    pieces = pieces_of_job(job["id"])
    job["accountable_piece_count"] = len([p for p in pieces if p["piece_status"] != "VOID"])
    job["print_piece_count"] = len([p for p in pieces if p["piece_status"] not in PRINTABLE_EXCLUDED])
    job["electronic_piece_count"] = len([p for p in pieces if p["piece_status"] == "SUPPRESSED"])
    job["void_piece_count"] = len([p for p in pieces if p["piece_status"] == "VOID"])
    job["reprint_piece_count"] = len([p for p in pieces if p.get("reprint_of_piece_id")])
    job["print_sheet_count"] = sum(
        p["sheet_count"] for p in pieces if p["piece_status"] not in PRINTABLE_EXCLUDED
    )
    job["reprint_chain_depth"] = job_chain_depth(job["id"])


def recompute_print_sheet_count(job):
    job["print_sheet_count"] = sum(
        p["sheet_count"] for p in pieces_of_job(job["id"])
        if p["piece_status"] not in PRINTABLE_EXCLUDED
    )


def recompute_batch(batch, bump=True):
    pieces = [p for p in pieces_of_batch(batch["id"]) if p["piece_status"] != "VOID"]
    batch["piece_count"] = len(pieces)
    batch["tray_count"] = ceil_div(len(pieces), calc.TRAY_CAPACITY_PIECES)
    batch["reserved_insert_sheets"] = sum(p["insert_sheet_count"] for p in pieces)
    if bump:
        touch(batch)


def release_line_sheets(line, sheets):
    line["committed_sheet_count"] = line["committed_sheet_count"] - sheets
    line["utilization_bp"] = calc.utilization_bp(line)
    touch(line)


def commit_line_sheets(line, sheets):
    line["committed_sheet_count"] = line["committed_sheet_count"] + sheets
    line["utilization_bp"] = calc.utilization_bp(line)
    touch(line)


def credit_hold_minutes(job):
    """Fold the current integrity hold into sla_hold_minutes and clear the marker."""
    held_since = job.get("integrity_held_since")
    if held_since is not None:
        elapsed = minutes_between(held_since, now())
        if elapsed < 0:
            elapsed = 0
        job["sla_hold_minutes"] = job.get("sla_hold_minutes", 0) + half_up(elapsed)
        job["integrity_held_since"] = None
