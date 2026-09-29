"""Claim endpoints.  Two independent axes: handling_status and payment_status."""
from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import derive
import ops
import store
import sync
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing, require_open_posture
from store import clock_now, dec, money, touch

bp = Blueprint("claims", __name__)

ACCESS_STATUSES = ("ACCESSIBLE", "INACCESSIBLE", "RESTRICTED")
ENTRY_TYPES = ("INITIAL_CASE", "REVISION", "PAYMENT", "REVERSAL")


@bp.post("/claims")
def create_claim():
    begin()
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None

    payload = validate.body()
    policy_number = validate.req_string(payload, "policy_number")
    loss_state = validate.req_state(payload, "loss_state")
    loss_date = validate.req_datetime(payload, "loss_date_utc")
    reported_loss = validate.req_number(payload, "reported_loss_amount", minimum=0)
    coverage_lines = validate.req_coverage_lines(payload)
    access_status = validate.opt_enum(payload, "access_status", ACCESS_STATUSES,
                                     default="ACCESSIBLE")
    # Position 31 - (policy_number, loss_date_utc) uniqueness.
    for other in store.claims.values():
        if other["policy_number"] == policy_number \
                and other["loss_date_utc"] == loss_date:
            fail("ERR_DUPLICATE_CLAIM")

    rec = store.base_record()
    rec.update({
        "event_id": None if event is None else event["id"],
        "policy_number": policy_number,
        "loss_state": loss_state,
        "loss_date_utc": loss_date,
        "reported_at_utc": clock_now(),
        "reported_loss_amount": reported_loss,
        "coverage_lines": coverage_lines,
        "access_status": access_status,
        "handling_status": "INTAKE",
        "payment_status": "NONE",
        "severity_score": Decimal("0.00"),
        "triage_tier": None,
        "inspection_mode": None,
        "deadline_utc": None,
        "reopen_count": 0,
        "reopen_anchor_utc": None,
        "closing_examiner_user_id": None,
        "advance_issuing_examiner_user_id": None,
        "transfer_batch_id": None,
    })
    store.claims[rec["id"]] = rec
    if event is not None:
        touch(event)
    return created(derive.claim_out(rec))


@bp.get("/claims")
def list_claims():
    begin()
    rows = list(store.claims.values())
    for param, field in (("event_id", "event_id"),
                         ("transfer_batch_id", "transfer_batch_id"),
                         ("handling_status", "handling_status"),
                         ("payment_status", "payment_status"),
                         ("triage_tier", "triage_tier"),
                         ("loss_state", "loss_state")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.claim_out)


@bp.get("/claims/<claim_id>")
def read_claim(claim_id):
    begin()
    return ok(derive.claim_out(validate.claim(claim_id)))


@bp.post("/claims/<claim_id>/assign-cat-code")
def assign_cat_code(claim_id):
    begin()
    # Position 4 (event) precedes position 5 (claim).
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    rec = validate.claim(claim_id)
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")

    if rec["handling_status"] != "INTAKE":
        fail("ERR_CLAIM_NOT_IN_INTAKE")
    if event["status"] not in ("DECLARED", "SURGE_ACTIVE"):
        fail("ERR_EVENT_NOT_DECLARED")

    rec["event_id"] = event["id"]
    touch(rec)
    touch(event)
    return ok(derive.claim_out(rec))


@bp.post("/claims/<claim_id>/triage")
def triage_claim(claim_id):
    begin()
    rec = validate.claim(claim_id)
    if rec["handling_status"] != "INTAKE":
        fail("ERR_CLAIM_NOT_IN_INTAKE")
    if rec["event_id"] is None:
        fail("ERR_CLAIM_NOT_CAT_CODED")
    event = store.events.get(rec["event_id"])
    if event is None or event["status"] not in ("DECLARED", "SURGE_ACTIVE"):
        fail("ERR_EVENT_NOT_DECLARED")
    # Position 20.
    require_open_posture(event)

    score, tier = calc.severity_score(rec, event)
    rec["severity_score"] = score
    rec["triage_tier"] = tier
    rec["inspection_mode"] = calc.inspection_mode(rec)
    rec["handling_status"] = "TRIAGED"
    sync.recompute_deadline(rec)
    ops.append_entry(rec, "INITIAL_CASE", calc.initial_case_reserve(rec),
                     Decimal("0.00"), "Initial case reserve opened at triage")
    touch(rec)
    touch(event)
    return ok(derive.claim_out(rec))


@bp.post("/claims/<claim_id>/close")
def close_claim(claim_id):
    user_id, _role = begin()
    rec = validate.claim(claim_id)
    # Pair A: the state check outranks the moratorium check.
    if rec["handling_status"] != "INSPECTED":
        fail("ERR_CLAIM_NOT_INSPECTED")
    # Position 21.
    if derive.event_moratorium_active(rec["event_id"]):
        fail("ERR_MORATORIUM_ACTIVE")
    # Position 22 - segregation of duties.
    if rec["advance_issuing_examiner_user_id"] is not None \
            and rec["advance_issuing_examiner_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if rec["payment_status"] not in ("NONE", "SETTLED"):
        fail("ERR_ADVANCE_OUTSTANDING")
    open_jobs = [v for v in store.vendor_assignments.values()
                 if v["claim_id"] == rec["id"]
                 and v["status"] in ("DISPATCHED", "ACCEPTED")]
    if open_jobs:
        fail("ERR_VENDOR_JOB_OPEN")

    rec["handling_status"] = "CLOSED"
    rec["closing_examiner_user_id"] = user_id
    touch(rec)
    event = store.events.get(rec["event_id"])
    if event is not None:
        touch(event)
    return ok(derive.claim_out(rec))


@bp.post("/claims/<claim_id>/reopen")
def reopen_claim(claim_id):
    begin()
    rec = validate.claim(claim_id)
    if rec["handling_status"] != "CLOSED":
        fail("ERR_CLAIM_NOT_CLOSED")
    event = store.events.get(rec["event_id"])
    if event is not None and event["status"] == "CLOSED":
        fail("ERR_EVENT_CLOSED")
    # Position 34.
    if rec["reopen_count"] >= calc.MAX_REOPENS:
        fail("ERR_REOPEN_LIMIT_REACHED")

    rec["handling_status"] = "REOPENED"
    rec["reopen_count"] += 1
    rec["closing_examiner_user_id"] = None
    rec["reopen_anchor_utc"] = clock_now()
    if event is not None:
        score, tier = calc.severity_score(rec, event)
        rec["severity_score"] = score
        rec["triage_tier"] = tier
    rec["inspection_mode"] = calc.inspection_mode(rec)
    sync.recompute_deadline(rec)
    touch(rec)
    if event is not None:
        touch(event)
    return ok(derive.claim_out(rec))


@bp.post("/claims/<claim_id>/reserve-entries")
def create_reserve_entry(claim_id):
    begin()
    rec = validate.claim(claim_id)
    payload = validate.body()
    expected = validate.req_int(payload, "expected_claim_version")
    entry_type = validate.req_enum(payload, "entry_type", ("REVISION", "PAYMENT"))
    delta_case = validate.req_number(payload, "delta_case_reserve")
    delta_paid = validate.req_number(payload, "delta_paid")
    settles = validate.opt_bool(payload, "settles_claim", False)
    memo = payload.get("memo")
    if memo is not None and not isinstance(memo, str):
        fail("ERR_VALIDATION", "memo must be a string.")
    # Position 18 - optimistic concurrency on the claim's version.
    if expected != rec["version"]:
        fail("ERR_STALE_CLAIM_VERSION")

    event = store.events.get(rec["event_id"])
    settling = entry_type == "PAYMENT" and settles
    if settling:
        # The settling entry requires a completed inspection.
        if rec["handling_status"] != "INSPECTED":
            fail("ERR_CLAIM_NOT_INSPECTED")
    # Position 20.
    require_open_posture(event)
    # Position 41 - the case reserve may never go negative.
    current = derive.claim_case_reserve(rec["id"])
    if settling:
        applied_case = money(-current)
    else:
        applied_case = money(delta_case)
    if money(current + applied_case) < money(0):
        fail("ERR_RESERVE_WOULD_GO_NEGATIVE")

    entry = ops.append_entry(rec, entry_type, applied_case, money(delta_paid),
                             memo if memo is not None
                             else "Manual %s entry" % entry_type.lower())
    if entry_type == "PAYMENT":
        if settles:
            rec["payment_status"] = "SETTLED"
        elif rec["payment_status"] in ("NONE", "ADVANCE_ISSUED"):
            rec["payment_status"] = "PARTIAL_PAID"
    touch(rec)
    if event is not None:
        touch(event)
    return created(derive.reserve_entry_out(entry))
