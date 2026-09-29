"""Print vendors, print jobs and ballot lot custody."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import guards
import serial
import store
import util
import validate
from errors import fail

bp = Blueprint("print", __name__)


def _write_invoice(job, basis):
    figures = calc.invoice(job, basis)
    job["invoice_basis"] = figures["invoice_basis"]
    job["invoice_subtotal_cents"] = figures["invoice_subtotal_cents"]
    job["delivered_quantity"] = figures["delivered_quantity"]
    job["freight_cents"] = figures["freight_cents"]
    job["defect_credit_cents"] = figures["defect_credit_cents"]
    job["invoice_total_cents"] = figures["invoice_total_cents"]


# ---------------------------------------------------------------------------
# Print vendors
# ---------------------------------------------------------------------------

@bp.post("/print-vendors")
def create_vendor():
    auth.require(auth.ELECTIONS_DIRECTOR)
    body = validate.body()
    name = validate.req_str(body, "name")
    press_line_count = validate.req_int(body, "press_line_count", minimum=1)
    certified_secure = validate.req_bool(body, "certified_secure")
    status = validate.opt_enum(body, "status", ("ACTIVE", "SUSPENDED"), "ACTIVE")
    row = store.insert("print_vendors", {
        "name": name,
        "press_line_count": press_line_count,
        "certified_secure": certified_secure,
        "status": status,
        "quality_defect_rate_bp": 0,
        "active_job_count": 0,
    })
    return envelope.created(serial.vendor(row))


@bp.get("/print-vendors/<vendor_id>")
def read_vendor(vendor_id):
    auth.require_any()
    row = guards.find("print_vendors", vendor_id)
    return envelope.ok(serial.vendor(row))


# ---------------------------------------------------------------------------
# Print jobs
# ---------------------------------------------------------------------------

@bp.post("/print-jobs")
def create_job():
    auth.require(auth.BALLOT_COORDINATOR)
    body = validate.body()
    vendor_id = validate.req_str(body, "vendor_id")
    style_id = validate.req_str(body, "style_id")
    quantity_ordered = validate.req_int(body, "quantity_ordered", minimum=1)
    unit_cost = validate.req_int(body, "unit_cost_cents_per_thousand", minimum=1)
    window_start = validate.req_ts(body, "press_window_start")
    window_end = validate.req_ts(body, "press_window_end")
    expected_version = validate.req_int(body, "expected_ballot_style_version")
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST", "press_window_end must be strictly after press_window_start.")
    vendor = store.get("print_vendors", vendor_id)
    if vendor is None:
        fail("ERR_PRINT_VENDOR_NOT_FOUND", "Print vendor does not exist.")
    style = store.get("ballot_styles", style_id)
    if style is None:
        fail("ERR_BALLOT_STYLE_NOT_FOUND", "Ballot style does not exist.")
    election = store.election_of_style(style)
    if expected_version != style["version"]:
        fail("ERR_STALE_BALLOT_STYLE_VERSION",
             "Ballot style version %s is stale." % expected_version)
    guards.require_phase(election, ("CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    if style["status"] not in ("APPROVED", "LOCKED"):
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit a print order." % style["status"])
    if vendor["status"] != "ACTIVE" or not vendor["certified_secure"]:
        fail("ERR_VENDOR_NOT_SECURE",
             "Vendor is not an active certified secure facility.")
    overlaps = 0
    for other in store.jobs_of_vendor(vendor_id):
        if other["status"] not in derive.ACTIVE_JOB_STATUSES:
            continue
        other_start = util.parse_ts(other["press_window_start"])
        other_end = util.parse_ts(other["press_window_end"])
        if window_start < other_end and other_start < window_end:
            overlaps += 1
    if overlaps >= vendor["press_line_count"]:
        fail("ERR_PRESS_CAPACITY_EXCEEDED",
             "Vendor has %d of %d press lines committed across this window."
             % (overlaps, vendor["press_line_count"]))
    requirement = sum((p["required_ballot_quantity"] or 0)
                      for p in store.precincts_of(election["id"])
                      if p["assigned_style_id"] == style_id)
    if quantity_ordered < requirement:
        fail("ERR_QUANTITY_BELOW_REQUIREMENT",
             "Ordered quantity %d is below the requirement of %d."
             % (quantity_ordered, requirement))
    row = store.insert("print_jobs", {
        "election_id": election["id"],
        "vendor_id": vendor_id,
        "style_id": style_id,
        "quantity_ordered": quantity_ordered,
        "unit_cost_cents_per_thousand": unit_cost,
        "press_window_start": util.fmt_ts(window_start),
        "press_window_end": util.fmt_ts(window_end),
        "style_version_at_creation": style["version"],
        "status": "PROOF_PENDING",
        "approved_by_user_id": None,
        "sample_size": 0,
        "defect_count": 0,
        "defect_rate_bp": 0,
        "inspection_count": 0,
        "delivered_quantity": 0,
        "invoice_basis": None,
        "invoice_subtotal_cents": 0,
        "defect_credit_cents": 0,
        "freight_cents": 0,
        "invoice_total_cents": 0,
    })
    derive.recompute_vendor_active_jobs(vendor)
    return envelope.created(serial.job(row))


@bp.get("/print-jobs/<job_id>")
def read_job(job_id):
    auth.require_any()
    row = guards.find("print_jobs", job_id)
    return envelope.ok(serial.job(row))


@bp.get("/print-jobs")
def list_jobs():
    auth.require_any()
    limit, offset = validate.pagination()
    election_id = validate.query_str("election_id")
    vendor_id = validate.query_str("vendor_id")
    style_id = validate.query_str("style_id")
    status = validate.query_enum("status", ("PROOF_PENDING", "PRINTING", "QC_HOLD",
                                           "QC_PASSED", "DELIVERED", "REJECTED"))
    rows = store.all_rows("print_jobs")
    if election_id:
        rows = [r for r in rows if r["election_id"] == election_id]
    if vendor_id:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    if style_id:
        rows = [r for r in rows if r["style_id"] == style_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=store.order_key)
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.job(r) for r in page], limit, offset, total)


@bp.post("/print-jobs/<job_id>/approve-proof")
def approve_proof(job_id):
    role, user = auth.require(auth.ELECTIONS_DIRECTOR)
    job = guards.find("print_jobs", job_id)
    election = store.get("elections", job["election_id"])
    style = store.get("ballot_styles", job["style_id"])
    if job["status"] != "PROOF_PENDING":
        fail("ERR_JOB_STATE_INVALID",
             "Print job state %s does not permit proof approval." % job["status"])
    guards.require_phase(election, ("CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    if style is None or style["status"] not in ("APPROVED", "LOCKED"):
        fail("ERR_STYLE_STATE_INVALID", "Ballot style is no longer approved.")
    vendor = store.get("print_vendors", job["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE" or not vendor["certified_secure"]:
        fail("ERR_VENDOR_NOT_SECURE",
             "Vendor is not an active certified secure facility.")
    if style["version"] != job["style_version_at_creation"]:
        fail("ERR_PROOF_VERSION_STALE",
             "The proof was pinned to ballot style version %s."
             % job["style_version_at_creation"])
    job["status"] = "PRINTING"
    job["approved_by_user_id"] = user
    _write_invoice(job, "ESTIMATE")
    store.touch(job)
    derive.recompute_vendor_active_jobs(vendor)
    derive.recompute_committed_print(election)
    return envelope.ok(serial.job(job))


@bp.post("/print-jobs/<job_id>/inspect")
def inspect_job(job_id):
    auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    sample_size = validate.req_int(body, "sample_size", minimum=1)
    defect_count = validate.req_int(body, "defect_count", minimum=0)
    if defect_count > sample_size:
        fail("ERR_INVALID_REQUEST", "defect_count may not exceed sample_size.")
    job = guards.find("print_jobs", job_id)
    if job["status"] not in ("PRINTING", "QC_HOLD"):
        fail("ERR_JOB_STATE_INVALID",
             "Print job state %s does not permit inspection." % job["status"])
    job["inspection_count"] = (job["inspection_count"] or 0) + 1
    job["sample_size"] = (job["sample_size"] or 0) + sample_size
    job["defect_count"] = (job["defect_count"] or 0) + defect_count
    job["defect_rate_bp"] = util.round_half_up(job["defect_count"] * 10000,
                                               job["sample_size"])
    job["status"] = ("QC_HOLD" if job["defect_rate_bp"] >= calc.QC_HOLD_THRESHOLD_BP
                     else "QC_PASSED")
    store.touch(job)
    derive.recompute_vendor_defect_rate(store.get("print_vendors", job["vendor_id"]))
    return envelope.ok(serial.job(job))


@bp.post("/print-jobs/<job_id>/deliver")
def deliver_job(job_id):
    role, user = auth.require(auth.PRINT_VENDOR_REP)
    body = validate.body()
    raw_lots = body.get("lots")
    if not isinstance(raw_lots, list) or not raw_lots:
        fail("ERR_INVALID_REQUEST", "Field 'lots' must be a non-empty array.")
    manifest = []
    codes = []
    for entry in raw_lots:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each manifest line must be an object.")
        lot_code = validate.req_str(entry, "lot_code")
        quantity_shipped = validate.req_int(entry, "quantity_shipped", minimum=1)
        seal_number = validate.req_str(entry, "seal_number")
        if lot_code in codes:
            fail("ERR_INVALID_REQUEST",
                 "Manifest repeats lot_code '%s'." % lot_code)
        codes.append(lot_code)
        manifest.append({"lot_code": lot_code, "quantity_shipped": quantity_shipped,
                         "seal_number": seal_number})
    job = guards.find("print_jobs", job_id)
    if user is None or user != job["vendor_id"]:
        fail("ERR_UNAUTHORIZED", "This print job belongs to another vendor.")
    if job["status"] != "QC_PASSED":
        fail("ERR_JOB_STATE_INVALID",
             "Print job state %s does not permit delivery." % job["status"])
    seen_seals = []
    for line in manifest:
        seal = line["seal_number"]
        if seal in seen_seals or derive.seal_in_use(job["election_id"], seal):
            fail("ERR_SEAL_NUMBER_DUPLICATE",
                 "Seal number '%s' is already in use in this election." % seal)
        seen_seals.append(seal)
    for line in manifest:
        lot = store.insert("ballot_lots", {
            "election_id": job["election_id"],
            "print_job_id": job["id"],
            "precinct_id": None,
            "lot_code": line["lot_code"],
            "quantity_shipped": line["quantity_shipped"],
            "seal_number": line["seal_number"],
            "custody_state": "IN_TRANSIT",
            "quantity_received": 0,
            "issued_quantity": 0,
            "voted_quantity": 0,
            "spoiled_quantity": 0,
            "unused_quantity": 0,
            "returned_unused_quantity": 0,
            "accounted_quantity": 0,
            "lot_variance": 0,
            "issued_by_user_id": None,
        })
        derive.append_custody(job["election_id"], "BALLOT_LOT", lot["id"],
                              "TRANSFER_OUT", None, "IN_TRANSIT",
                              lot["seal_number"], role, user)
    job["status"] = "DELIVERED"
    _write_invoice(job, "FINAL")
    store.touch(job)
    election = store.get("elections", job["election_id"])
    derive.recompute_vendor_active_jobs(store.get("print_vendors", job["vendor_id"]))
    derive.recompute_committed_print(election)
    derive.recompute_open_seals(election)
    return envelope.ok(serial.job(job))


# ---------------------------------------------------------------------------
# Ballot lots
# ---------------------------------------------------------------------------

@bp.get("/ballot-lots/<lot_id>")
def read_lot(lot_id):
    auth.require_any()
    row = guards.find("ballot_lots", lot_id)
    return envelope.ok(serial.lot(row))


@bp.get("/ballot-lots")
def list_lots():
    auth.require_any()
    limit, offset = validate.pagination()
    election_id = validate.query_str("election_id")
    print_job_id = validate.query_str("print_job_id")
    precinct_id = validate.query_str("precinct_id")
    custody_state = validate.query_enum("custody_state", ("IN_TRANSIT", "RECEIVED",
                                                          "ISSUED", "RETURNED", "VOIDED"))
    rows = store.all_rows("ballot_lots")
    if election_id:
        rows = [r for r in rows if r["election_id"] == election_id]
    if print_job_id:
        rows = [r for r in rows if r["print_job_id"] == print_job_id]
    if precinct_id:
        rows = [r for r in rows if r["precinct_id"] == precinct_id]
    if custody_state:
        rows = [r for r in rows if r["custody_state"] == custody_state]
    rows.sort(key=lambda r: (r["lot_code"], r["created_at"], r["_seq"]))
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.lot(r) for r in page], limit, offset, total)


@bp.post("/ballot-lots/<lot_id>/receive")
def receive_lot(lot_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    seal_number = validate.req_str(body, "seal_number")
    quantity_received = validate.req_int(body, "quantity_received", minimum=1)
    lot = guards.find("ballot_lots", lot_id)
    election = store.get("elections", lot["election_id"])
    guards.require_phase(election, ("STYLES_LOCKED", "DEPLOYED"))
    if lot["custody_state"] != "IN_TRANSIT":
        fail("ERR_LOT_STATE_INVALID",
             "Ballot lot state %s does not permit receipt." % lot["custody_state"])
    if seal_number != lot["seal_number"]:
        fail("ERR_SEAL_MISMATCH", "The presented seal is not the seal that was shipped.")
    lot["custody_state"] = "RECEIVED"
    lot["quantity_received"] = quantity_received
    lot["unused_quantity"] = quantity_received
    store.touch(lot)
    derive.append_custody(lot["election_id"], "BALLOT_LOT", lot["id"], "RECEIPT",
                          "IN_TRANSIT", "RECEIVED", lot["seal_number"], role, user)
    derive.recompute_election_totals(election, skip_issued=True)
    return envelope.ok(serial.lot(lot))


@bp.post("/ballot-lots/<lot_id>/issue")
def issue_lot(lot_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    precinct_id = validate.req_str(body, "precinct_id")
    issue_quantity = validate.req_int(body, "issue_quantity", minimum=1)
    lot = guards.find("ballot_lots", lot_id)
    election = store.get("elections", lot["election_id"])
    precinct = store.get("precincts", precinct_id)
    if precinct is None or precinct["election_id"] != lot["election_id"]:
        fail("ERR_PRECINCT_NOT_FOUND", "Precinct does not exist.")
    guards.require_phase(election, ("STYLES_LOCKED", "DEPLOYED"))
    if lot["custody_state"] != "RECEIVED":
        fail("ERR_LOT_STATE_INVALID",
             "Ballot lot state %s does not permit issue." % lot["custody_state"])
    job = store.get("print_jobs", lot["print_job_id"])
    lot_style_id = job["style_id"] if job is not None else None
    if precinct["assigned_style_id"] != lot_style_id:
        fail("ERR_LOT_NOT_FOR_PRECINCT",
             "This lot was printed for another ballot style.")
    if issue_quantity > (lot["quantity_received"] or 0):
        fail("ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT",
             "Issue quantity %d exceeds the %d ballots received."
             % (issue_quantity, lot["quantity_received"] or 0))
    lot["custody_state"] = "ISSUED"
    lot["precinct_id"] = precinct_id
    lot["issued_quantity"] = issue_quantity
    lot["unused_quantity"] = (lot["quantity_received"] or 0) - issue_quantity
    lot["issued_by_user_id"] = user
    store.touch(lot)
    derive.append_custody(lot["election_id"], "BALLOT_LOT", lot["id"], "ISSUE",
                          "RECEIVED", "ISSUED", lot["seal_number"], role, user)
    derive.recompute_precinct(precinct)
    derive.recompute_election_totals(election)
    derive.recompute_readiness(election)
    return envelope.ok(serial.lot(lot))


@bp.post("/ballot-lots/<lot_id>/recall")
def recall_lot(lot_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    validate.opt_str(body, "recall_reason")
    lot = guards.find("ballot_lots", lot_id)
    election = store.get("elections", lot["election_id"])
    guards.require_phase(election, ("STYLES_LOCKED", "DEPLOYED"))
    if lot["custody_state"] != "ISSUED":
        fail("ERR_LOT_STATE_INVALID",
             "Ballot lot state %s does not permit recall." % lot["custody_state"])
    precinct = store.get("precincts", lot["precinct_id"])
    lot["custody_state"] = "RECEIVED"
    lot["issued_quantity"] = 0
    lot["unused_quantity"] = lot["quantity_received"] or 0
    lot["precinct_id"] = None
    lot["issued_by_user_id"] = None
    store.touch(lot)
    derive.append_custody(lot["election_id"], "BALLOT_LOT", lot["id"], "RECALL",
                          "ISSUED", "RECEIVED", lot["seal_number"], role, user)
    if precinct is not None:
        derive.recompute_precinct(precinct)
    derive.recompute_election_totals(election)
    derive.recompute_readiness(election)
    return envelope.ok(serial.lot(lot))


@bp.post("/ballot-lots/<lot_id>/return-counts")
def return_counts(lot_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    voted_quantity = validate.req_int(body, "voted_quantity", minimum=0)
    spoiled_quantity = validate.req_int(body, "spoiled_quantity", minimum=0)
    returned_unused_quantity = validate.req_int(body, "returned_unused_quantity", minimum=0)
    lot = guards.find("ballot_lots", lot_id)
    election = store.get("elections", lot["election_id"])
    guards.require_phase(election, ("DEPLOYED", "POLLS_CLOSED"))
    if lot["custody_state"] != "ISSUED":
        fail("ERR_LOT_STATE_INVALID",
             "Ballot lot state %s does not permit return accounting." % lot["custody_state"])
    accounted = voted_quantity + spoiled_quantity + returned_unused_quantity
    if accounted > (lot["quantity_received"] or 0):
        fail("ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT",
             "Accounted %d exceeds the %d ballots received."
             % (accounted, lot["quantity_received"] or 0))
    lot["custody_state"] = "RETURNED"
    lot["voted_quantity"] = voted_quantity
    lot["spoiled_quantity"] = spoiled_quantity
    lot["returned_unused_quantity"] = returned_unused_quantity
    lot["accounted_quantity"] = accounted
    lot["lot_variance"] = (lot["issued_quantity"] or 0) - accounted
    store.touch(lot)
    derive.append_custody(lot["election_id"], "BALLOT_LOT", lot["id"], "RETURN",
                          "ISSUED", "RETURNED", lot["seal_number"], role, user)
    derive.recompute_election_totals(election)
    return envelope.ok(serial.lot(lot))
