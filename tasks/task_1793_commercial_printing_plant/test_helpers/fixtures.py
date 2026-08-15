"""Composite setup helpers.

Each helper builds its preconditions from scratch via PRD-declared endpoints
(the server restarts with an empty database before every test). All helpers
use get_success_data() internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating a Customer, every ownership-gated call in
the same chain uses make_customer_headers(customer["id"]) — never the shared
TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DUE_DATE_ISO, RUN_START_ISO
from .factories import (
    approve_claim_payload,
    complete_press_run_payload,
    create_bindery_ticket_payload,
    create_claim_payload,
    create_customer_payload,
    create_estimate_payload,
    create_gang_run_payload,
    create_mail_drop_payload,
    create_po_payload,
    create_paper_stock_payload,
    create_press_payload,
    create_press_run_payload,
    create_proof_payload,
    gang_member_payload,
    receive_po_payload,
    signature_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_plant_manager_headers

_PM = TEST_USERS["plant_manager_headers"]
_EST = TEST_USERS["estimator_headers"]
_PRE = TEST_USERS["prepress_headers"]
_SCH = TEST_USERS["scheduler_headers"]
_PUR = TEST_USERS["purchasing_headers"]
_MAIL = TEST_USERS["mail_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base resources
# ---------------------------------------------------------------------------

def create_customer(name="Test Customer", credit_limit_cents=100000000, default_tolerance_pct=5):
    """Create a customer. Returns the Customer dict."""
    payload = create_customer_payload(
        name=name,
        credit_limit_cents=credit_limit_cents,
        default_tolerance_pct=default_tolerance_pct,
    )
    resp = api_client.create_customer(payload, _PM)
    cust = get_success_data(resp)
    assert cust.get("id"), f"Setup failed: create_customer -> {resp.text}"
    return cust


def create_stock(name="80G", cost_per_sheet_cents=9, grade="COATED",
                 reorder_threshold_sheets=0, reorder_quantity_sheets=20000):
    """Create a paper stock. Returns the PaperStock dict."""
    payload = create_paper_stock_payload(
        name=name,
        grade=grade,
        cost_per_sheet_cents=cost_per_sheet_cents,
        reorder_threshold_sheets=reorder_threshold_sheets,
        reorder_quantity_sheets=reorder_quantity_sheets,
    )
    resp = api_client.create_paper_stock(payload, _PUR)
    stock = get_success_data(resp)
    assert stock.get("id"), f"Setup failed: create_stock -> {resp.text}"
    return stock


def create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=5000,
                          reorder_threshold_sheets=0, reorder_quantity_sheets=20000,
                          grade="COATED"):
    """Stock + one PO fully received. Returns (stock, po)."""
    stock = create_stock(
        name=name,
        cost_per_sheet_cents=cost_per_sheet_cents,
        grade=grade,
        reorder_threshold_sheets=reorder_threshold_sheets,
        reorder_quantity_sheets=reorder_quantity_sheets,
    )
    po_resp = api_client.create_paper_purchase_order(
        create_po_payload(stock["id"], ordered_sheets=sheets,
                          cost_per_sheet_cents=cost_per_sheet_cents), _PUR)
    po = get_success_data(po_resp)
    assert po.get("id"), f"Setup failed: create PO -> {po_resp.text}"
    rcv = api_client.receive_paper_purchase_order(
        po["id"], receive_po_payload(sheets), _PUR)
    po = get_success_data(rcv)
    assert po.get("status") in ("RECEIVED", "PARTIALLY_RECEIVED"), (
        f"Setup failed: receive PO -> {rcv.text}"
    )
    return stock, po


def create_press(name="W1", press_type="WEB", status=None,
                 rated_impressions_per_hour=10000, make_ready_minutes_base=45,
                 washup_buffer_minutes=30):
    """Create a press. Returns the Press dict (carries version for OCC)."""
    payload = create_press_payload(
        name=name,
        press_type=press_type,
        rated_impressions_per_hour=rated_impressions_per_hour,
        make_ready_minutes_base=make_ready_minutes_base,
        washup_buffer_minutes=washup_buffer_minutes,
    )
    if status is not None:
        payload["status"] = status
    resp = api_client.create_press(payload, _PM)
    press = get_success_data(resp)
    assert press.get("id"), f"Setup failed: create_press -> {resp.text}"
    return press


# ---------------------------------------------------------------------------
# Tier 2: estimate -> job chains
# ---------------------------------------------------------------------------

def create_estimate(customer_id, signatures, quantity_ordered=1000,
                    fulfillment_type="SHIP", press_type="WEB",
                    binding_method="SADDLE_STITCH",
                    press_spoilage_pct=0, bindery_spoilage_pct=0,
                    finishing_options=None, included_proof_rounds=2,
                    quote_valid_days=30, due_date=DUE_DATE_ISO,
                    job_name="Test Job"):
    """Create a DRAFT estimate. Returns the Estimate dict."""
    payload = create_estimate_payload(
        customer_id,
        job_name=job_name,
        quantity_ordered=quantity_ordered,
        press_type=press_type,
        binding_method=binding_method,
        fulfillment_type=fulfillment_type,
        signatures=signatures,
        press_spoilage_pct=press_spoilage_pct,
        bindery_spoilage_pct=bindery_spoilage_pct,
        due_date=due_date,
        included_proof_rounds=included_proof_rounds,
        quote_valid_days=quote_valid_days,
    )
    if finishing_options is not None:
        payload["finishing_options"] = finishing_options
    resp = api_client.create_estimate(payload, _EST)
    est = get_success_data(resp)
    assert est.get("id"), f"Setup failed: create_estimate -> {resp.text}"
    return est


def quote_estimate(estimate_id):
    resp = api_client.quote_estimate(estimate_id, _EST)
    est = get_success_data(resp)
    assert est.get("status") == "QUOTED", f"Setup failed: quote -> {resp.text}"
    return est


def accept_estimate(estimate_id, customer_id):
    """Accept a QUOTED estimate as its owning customer. Returns the Job dict."""
    resp = api_client.accept_estimate(estimate_id, make_customer_headers(customer_id))
    job = get_success_data(resp)
    assert job.get("id"), f"Setup failed: accept -> {resp.text}"
    return job


def create_accepted_job(customer_id, signatures, **estimate_kwargs):
    """DRAFT -> QUOTED -> ACCEPTED. Returns (estimate, job)."""
    est = create_estimate(customer_id, signatures, **estimate_kwargs)
    quote_estimate(est["id"])
    job = accept_estimate(est["id"], customer_id)
    return est, job


def upload_proof(job_id, file_uri="s3://proofs/p.pdf"):
    resp = api_client.create_proof(create_proof_payload(job_id, file_uri=file_uri), _PRE)
    proof = get_success_data(resp)
    assert proof.get("id"), f"Setup failed: upload_proof -> {resp.text}"
    return proof


def approve_proof(proof_id, customer_id):
    resp = api_client.approve_proof(proof_id, make_customer_headers(customer_id))
    proof = get_success_data(resp)
    assert proof.get("status") == "APPROVED", f"Setup failed: approve_proof -> {resp.text}"
    return proof


def create_plated_job(customer_id, signatures, **estimate_kwargs):
    """Accepted job driven PREPRESS -> PROOF_REVIEW -> PLATED.
    Returns (estimate, job, proof)."""
    est, job = create_accepted_job(customer_id, signatures, **estimate_kwargs)
    proof = upload_proof(job["id"])
    approve_proof(proof["id"], customer_id)
    job = get_success_data(api_client.get_job(job["id"], _PM))
    assert job["production_status"] == "PLATED"
    return est, job, proof


# ---------------------------------------------------------------------------
# Tier 3: press scheduling and completion
# ---------------------------------------------------------------------------

def schedule_press_run(press, job_id=None, gang_run_id=None, run_quantity=1000,
                       scheduled_start=RUN_START_ISO):
    """Schedule a run; refreshes press OCC version from the supplied press dict.
    Returns the PressRun dict."""
    payload = create_press_run_payload(
        press["id"], press["version"],
        run_quantity=run_quantity, scheduled_start=scheduled_start,
    )
    if job_id is not None:
        payload["job_id"] = job_id
    if gang_run_id is not None:
        payload["gang_run_id"] = gang_run_id
    resp = api_client.create_press_run(payload, _SCH)
    run = get_success_data(resp)
    assert run.get("id"), f"Setup failed: schedule_press_run -> {resp.text}"
    return run


def complete_press_run(run_id, gross_impressions=1000, sheets_used=1000, waste_sheets=0):
    resp = api_client.complete_press_run(
        run_id,
        complete_press_run_payload(
            gross_impressions=gross_impressions,
            sheets_used=sheets_used,
            waste_sheets=waste_sheets,
        ),
        _SCH,
    )
    run = get_success_data(resp)
    assert run.get("status") == "COMPLETE", f"Setup failed: complete_press_run -> {resp.text}"
    return run


def refresh_press(press_id):
    return get_success_data(api_client.get_press(press_id, _SCH))


def create_job_in_bindery(customer_id, signatures, press=None, **estimate_kwargs):
    """PLATED job + scheduled + completed solo run -> BINDERY.
    Returns (est, job, run, press)."""
    est, job, _proof = create_plated_job(customer_id, signatures, **estimate_kwargs)
    if press is None:
        press = create_press()
    qty = estimate_kwargs.get("quantity_ordered", 1000)
    run = schedule_press_run(press, job_id=job["id"], run_quantity=qty)
    complete_press_run(run["id"], gross_impressions=qty, sheets_used=max(qty, 1), waste_sheets=0)
    job = get_success_data(api_client.get_job(job["id"], _PM))
    assert job["production_status"] == "BINDERY"
    return est, job, run, press


def complete_bindery_and_deliver(job_id, customer_id=None, delivered_quantity=None,
                                 operation="FOLD", pieces_completed=None):
    """Create one bindery ticket, complete it, then record delivery (SHIP jobs).
    Returns the FULFILLED job."""
    bt_resp = api_client.create_bindery_ticket(
        create_bindery_ticket_payload(job_id, operation=operation, sequence_no=1), _PM)
    bt = get_success_data(bt_resp)
    assert bt.get("id"), f"Setup failed: create bindery ticket -> {bt_resp.text}"
    cmp_resp = api_client.complete_bindery_ticket(
        bt["id"], {"pieces_completed": pieces_completed if pieces_completed is not None else 1000}, _PM)
    bt = get_success_data(cmp_resp)
    assert bt.get("status") == "COMPLETE", f"Setup failed: complete ticket -> {cmp_resp.text}"
    if delivered_quantity is not None:
        rd = api_client.record_delivery(job_id, {"delivered_quantity": delivered_quantity}, _PM)
        job = get_success_data(rd)
        assert job.get("production_status") == "FULFILLED", (
            f"Setup failed: record_delivery -> {rd.text}"
        )
        return job
    return get_success_data(api_client.get_job(job_id, _PM))


def create_fulfilled_ship_job(customer_id, signatures, delivered_quantity=None,
                              quantity_ordered=1000, **estimate_kwargs):
    """Full SHIP pipeline: accept -> plate -> run -> bindery -> delivery.
    Returns (est, job, press)."""
    est, job, run, press = create_job_in_bindery(
        customer_id, signatures, quantity_ordered=quantity_ordered, **estimate_kwargs)
    qty = quantity_ordered
    job = complete_bindery_and_deliver(
        job["id"], delivered_quantity=delivered_quantity if delivered_quantity is not None else qty,
        pieces_completed=delivered_quantity if delivered_quantity is not None else qty,
    )
    return est, job, press


def create_issued_invoice(customer_id, signatures, delivered_quantity=None,
                          quantity_ordered=1000, **estimate_kwargs):
    """Full SHIP pipeline + PRODUCTION invoice ISSUED.
    Returns (est, job, invoice, press)."""
    est, job, press = create_fulfilled_ship_job(
        customer_id, signatures,
        delivered_quantity=delivered_quantity, quantity_ordered=quantity_ordered,
        **estimate_kwargs)
    inv_resp = api_client.create_invoice({"job_id": job["id"]}, _PM)
    inv = get_success_data(inv_resp)
    assert inv.get("id"), f"Setup failed: create invoice -> {inv_resp.text}"
    inv = get_success_data(api_client.issue_invoice(inv["id"], _PM))
    assert inv["status"] == "ISSUED"
    return est, job, inv, press


# ---------------------------------------------------------------------------
# Tier 3b: MAIL pipeline
# ---------------------------------------------------------------------------

def create_mail_drop_for_job(job_id, zip_counts, drop_date="2026-08-25",
                             destination_entry="NONE", piece_weight_oz=2.0):
    payload = create_mail_drop_payload(
        job_id, zip_counts=zip_counts, drop_date=drop_date,
        destination_entry=destination_entry, piece_weight_oz=piece_weight_oz,
    )
    resp = api_client.create_mail_drop(payload, _MAIL)
    drop = get_success_data(resp)
    assert drop.get("id"), f"Setup failed: create_mail_drop -> {resp.text}"
    return drop


def fulfill_mail_job_via_drop(job_id, zip_counts, drop_date="2026-08-25"):
    """Plan -> presort -> drop. Returns the DROPPED MailDrop dict."""
    drop = create_mail_drop_for_job(job_id, zip_counts, drop_date=drop_date)
    drop = get_success_data(api_client.presort_mail_drop(drop["id"], _MAIL))
    assert drop["status"] == "PRESORTED"
    drop = get_success_data(api_client.drop_mail_drop(drop["id"], _MAIL))
    assert drop["status"] == "DROPPED"
    return drop


def create_fulfilled_mail_job(customer_id, signatures, zip_counts,
                              quantity_ordered=10002, **estimate_kwargs):
    """Full MAIL pipeline: accept -> plate -> run -> bindery -> drop.
    Returns (est, job, drop, press)."""
    estimate_kwargs.setdefault("fulfillment_type", "MAIL")
    est, job, run, press = create_job_in_bindery(
        customer_id, signatures, quantity_ordered=quantity_ordered, **estimate_kwargs)
    total_pieces = sum(z["pieces"] for z in zip_counts)
    complete_bindery_and_deliver(job["id"], delivered_quantity=None,
                                 pieces_completed=total_pieces)
    drop = fulfill_mail_job_via_drop(job["id"], zip_counts)
    job = get_success_data(api_client.get_job(job["id"], _PM))
    assert job["production_status"] == "FULFILLED"
    return est, job, drop, press


# ---------------------------------------------------------------------------
# Tier 4: claims
# ---------------------------------------------------------------------------

def file_claim(job_id, customer_id, defect_qty, claimed_defect="SHORTAGE"):
    resp = api_client.create_reprint_claim(
        create_claim_payload(job_id, claimed_defect=claimed_defect, defect_qty=defect_qty),
        make_customer_headers(customer_id),
    )
    claim = get_success_data(resp)
    assert claim.get("id"), f"Setup failed: file claim -> {resp.text}"
    return claim


def review_claim(claim_id, reviewer_user_id="pm-1"):
    resp = api_client.review_reprint_claim(
        claim_id, make_plant_manager_headers(reviewer_user_id))
    claim = get_success_data(resp)
    assert claim.get("status") == "UNDER_REVIEW", f"Setup failed: review claim -> {resp.text}"
    return claim


def create_reviewed_claim(job_id, customer_id, defect_qty, claimed_defect="SHORTAGE",
                          reviewer_user_id="pm-1"):
    """FILED -> UNDER_REVIEW. Returns the claim dict."""
    claim = file_claim(job_id, customer_id, defect_qty, claimed_defect)
    return review_claim(claim["id"], reviewer_user_id)


# ---------------------------------------------------------------------------
# Tier 4b: gang runs
# ---------------------------------------------------------------------------

def create_gang_run(paper_stock_id, press_type="WEB", anchor_due_date=DUE_DATE_ISO):
    resp = api_client.create_gang_run(
        create_gang_run_payload(paper_stock_id, press_type=press_type,
                                anchor_due_date=anchor_due_date),
        _SCH,
    )
    gang = get_success_data(resp)
    assert gang.get("id"), f"Setup failed: create gang -> {resp.text}"
    return gang


def add_gang_member(gang, job_id):
    """Add a member using the gang's current version (refreshed via the
    supplied gang dict's version). Returns (updated_gang, new_version)."""
    resp = api_client.add_gang_member(
        gang["id"], gang_member_payload(job_id, gang["version"]), _SCH)
    updated = get_success_data(resp)
    assert updated.get("id"), f"Setup failed: add gang member -> {resp.text}"
    return updated


def lock_gang(gang_id):
    resp = api_client.lock_gang_run(gang_id, _SCH)
    gang = get_success_data(resp)
    assert gang.get("status") == "LOCKED", f"Setup failed: lock gang -> {resp.text}"
    return gang


def create_gang_with_members(paper_stock_id, job_ids, press_type="WEB",
                             anchor_due_date=DUE_DATE_ISO):
    """Create gang and add the given PLATED jobs in order. Returns the gang."""
    gang = create_gang_run(paper_stock_id, press_type=press_type, anchor_due_date=anchor_due_date)
    for jid in job_ids:
        gang = add_gang_member(gang, jid)
    return gang


def create_locked_gang(paper_stock_id, job_ids, press_type="WEB",
                       anchor_due_date=DUE_DATE_ISO):
    """Gang with members, LOCKED. Returns the locked GangRun dict."""
    gang = create_gang_with_members(paper_stock_id, job_ids, press_type=press_type,
                                    anchor_due_date=anchor_due_date)
    return lock_gang(gang["id"])


# ---------------------------------------------------------------------------
# Standard spec shortcuts (the spec the design indices converge on)
# ---------------------------------------------------------------------------

def standard_signatures(stock_id):
    """Two identical 16-page up=2 signatures, MR 150000 each, rate 37250."""
    return [
        signature_payload(stock_id, name="A", pages=16, up_count=2,
                          make_ready_cents=150000, rate_per_thousand_cents=37250),
        signature_payload(stock_id, name="B", pages=16, up_count=2,
                          make_ready_cents=150000, rate_per_thousand_cents=37250),
    ]


def minimal_signature(stock_id, make_ready_cents=50000, rate_per_thousand_cents=30000,
                      up_count=1, pages=8):
    return [signature_payload(stock_id, name="A", pages=pages, up_count=up_count,
                              make_ready_cents=make_ready_cents,
                              rate_per_thousand_cents=rate_per_thousand_cents)]


def gang_pair_signatures(stock_id, make_ready_cents):
    """Single 16-page up=2 signature used by the gang-pair scenarios."""
    return [signature_payload(stock_id, name="S1", pages=16, up_count=2,
                              make_ready_cents=make_ready_cents,
                              rate_per_thousand_cents=37250)]
