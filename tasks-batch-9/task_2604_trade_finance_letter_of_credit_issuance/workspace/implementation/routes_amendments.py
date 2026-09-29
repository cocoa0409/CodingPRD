"""Amendment drafting, issuance and beneficiary consent (PRD 3.5)."""

from flask import Blueprint

import calc
import ledger
import validate as v
from db import clock_date, clock_date_str, clock_instant, db, new_row, public, touch
from errors import bail
from middleware import (
    BENEFICIARY_USER,
    TRADE_FINANCE_OFFICER,
    must_find,
    pending,
    raise_pending,
    require,
    segregation,
)
from response import created, ok
from routes_credits import (
    INCOTERMS,
    ISSUED_STATUSES,
    guard_credit_state,
    incoterm_document_check,
    screen_credit_parties,
)

bp = Blueprint("amendments", __name__)

CONSENT_DECISIONS = ("ACCEPT", "REJECT")


def _validate_change_set_values(change_set):
    """Shape of each amendable value (band 3). Unknown keys are left alone --
    they are adjudicated later as ERR_EMPTY_CHANGE_SET (band 7)."""
    if "amount_cents" in change_set:
        v.req_int(change_set, "amount_cents", minimum=100000)
    if "tolerance_pct" in change_set:
        v.req_int(change_set, "tolerance_pct", minimum=0, maximum=10)
    if "presentation_period_days" in change_set:
        v.req_int(change_set, "presentation_period_days", minimum=1, maximum=30)
    if "expiry_date" in change_set:
        v.req_date(change_set, "expiry_date")
    if "latest_shipment_date" in change_set:
        v.req_date(change_set, "latest_shipment_date")
    if "incoterm" in change_set:
        v.req_enum(change_set, "incoterm", INCOTERMS)
    if "incoterm_place" in change_set:
        v.req_str(change_set, "incoterm_place", 1, 120)
    if "partial_shipment_allowed" in change_set:
        v.req_bool(change_set, "partial_shipment_allowed")
    if "transhipment_allowed" in change_set:
        v.req_bool(change_set, "transhipment_allowed")


def _merged(credit, change_set, key):
    if key in change_set:
        return change_set[key]
    return credit.get(key)


def _shipment_coherent(credit, change_set):
    """latest_shipment_date <= expiry_date, and expiry_date > issue_date."""
    shipment = calc.parse_date(_merged(credit, change_set, "latest_shipment_date"))
    expiry = calc.parse_date(_merged(credit, change_set, "expiry_date"))
    if shipment is not None and expiry is not None and shipment > expiry:
        return False
    issue = calc.parse_date(credit.get("issue_date"))
    if issue is not None and expiry is not None and expiry <= issue:
        return False
    return True


def _amended_incoterm_documents(credit, change_set):
    """Re-run the incoterm/insurance pairing against the amended incoterm."""
    if "incoterm" not in change_set:
        return
    probe = dict(credit)
    probe["incoterm"] = change_set["incoterm"]
    incoterm_document_check(probe)


# --------------------------------------------------------------------------
# POST /credits/{id}/amendments
# --------------------------------------------------------------------------

@bp.post("/credits/<credit_id>/amendments")
def draft_amendment(credit_id):
    principal = require(TRADE_FINANCE_OFFICER)
    data = v.body()
    change_set = v.req_object(data, "change_set", min_keys=1, max_keys=5)
    reason = v.req_str(data, "reason", 1, 500)
    expected_version = v.req_int(data, "expected_credit_version", minimum=1)
    _validate_change_set_values(change_set)
    credit = must_find("credits", credit_id)

    # band 4 -- state, then optimistic concurrency
    guard_credit_state(credit, ISSUED_STATUSES, "ERR_CREDIT_NOT_ISSUED")
    if int(credit["version"]) != expected_version:
        bail("ERR_STALE_CREDIT_VERSION")

    # band 6 -- temporal
    if not _shipment_coherent(credit, change_set):
        bail("ERR_SHIPMENT_AFTER_EXPIRY")

    # band 7 -- structural: unknown keys and no-op-only change sets
    for key in change_set:
        if key not in calc.AMENDABLE_KEYS:
            bail("ERR_EMPTY_CHANGE_SET")
    effective = calc.effective_change_set(change_set, credit)
    if not effective:
        bail("ERR_EMPTY_CHANGE_SET")

    facility = db.facilities.get(credit["facility_id"])
    exposure = calc.credit_allocation_exposure(
        credit, facility, "committed_issuance", overrides=effective)
    delta = exposure["committed_allocation_cents"] - int(credit["committed_allocation_cents"] or 0)

    seq = len(ledger.amendments_of_credit(credit_id)) + 1
    ledger.supersede_draft_amendments(credit_id)

    row = new_row(
        credit_id=credit_id,
        seq=seq,
        change_set=dict(change_set),
        reason=reason,
        requires_beneficiary_consent=calc.requires_beneficiary_consent(effective, credit),
        status="DRAFT",
        consent_window_start=None,
        consent_deadline_date=None,
        window_end_effective=None,
        resolved_at=None,
        amendment_fee_cents=0,
        exposure_delta_cents=delta,
        drafted_by_user_id=principal.user_id,
        issued_by_user_id=None,
    )
    db.amendments[row["id"]] = row

    # drafting an amendment is itself a write on the credit
    touch(credit)
    return created(public(row))


# --------------------------------------------------------------------------
# POST /amendments/{id}/issue
# --------------------------------------------------------------------------

@bp.post("/amendments/<amendment_id>/issue")
def issue_amendment(amendment_id):
    principal = require(TRADE_FINANCE_OFFICER)
    amendment, deferred = pending("amendments", amendment_id)
    if amendment is not None:
        segregation(principal, amendment.get("drafted_by_user_id"))

    data = v.body()
    v.opt_str(data, "issue_note", 0, 500)
    raise_pending(deferred)

    # band 4
    if amendment["status"] != "DRAFT":
        bail("ERR_AMENDMENT_NOT_DRAFT")
    credit = db.credits.get(amendment["credit_id"])
    if credit is None:
        bail("ERR_CREDIT_NOT_FOUND")
    guard_credit_state(credit, ISSUED_STATUSES, "ERR_CREDIT_NOT_ISSUED")

    # band 5
    scored, _fields = screen_credit_parties(credit)
    if scored["result"] == "BLOCKED":
        bail("ERR_SANCTIONS_BLOCK")

    change_set = amendment["change_set"]
    effective = calc.effective_change_set(change_set, credit)

    # band 6
    if not _shipment_coherent(credit, change_set):
        bail("ERR_SHIPMENT_AFTER_EXPIRY")

    # band 7 -- window overlap (closed intervals + symmetric cooling-off buffer)
    start = clock_date()
    siblings = ledger.amendments_of_credit(credit["id"])
    if calc.amendment_window_conflict(siblings, amendment_id, start):
        bail("ERR_AMENDMENT_WINDOW_CONFLICT")
    _amended_incoterm_documents(credit, change_set)

    facility = db.facilities.get(credit["facility_id"])
    exposure = calc.credit_allocation_exposure(
        credit, facility, "committed_issuance", overrides=effective)
    delta = exposure["committed_allocation_cents"] - int(credit["committed_allocation_cents"] or 0)
    fee = calc.amendment_recharge_fee(
        delta,
        exposure["gross_exposure_cents"],
        _merged(credit, effective, "expiry_date"),
        start,
    )

    deadline = calc.add_days(start, calc.AMENDMENT_CONSENT_DAYS)
    amendment["issued_by_user_id"] = principal.user_id
    amendment["consent_window_start"] = start.isoformat()
    amendment["consent_deadline_date"] = deadline.isoformat()
    amendment["window_end_effective"] = deadline.isoformat()
    amendment["requires_beneficiary_consent"] = calc.requires_beneficiary_consent(effective, credit)
    amendment["exposure_delta_cents"] = delta
    amendment["amendment_fee_cents"] = fee
    amendment["status"] = "ISSUED"

    if amendment["requires_beneficiary_consent"]:
        amendment["status"] = "PENDING_CONSENT"
        credit["status"] = "AMENDMENT_PENDING"
        touch(credit)
    else:
        # the window closed the instant it opened
        amendment["status"] = "ACCEPTED"
        amendment["window_end_effective"] = clock_date_str()
        amendment["resolved_at"] = clock_instant()
        ledger.accept_amendment_effects(amendment, credit, facility)

    touch(amendment)
    return ok(public(amendment))


# --------------------------------------------------------------------------
# POST /amendments/{id}/consent
# --------------------------------------------------------------------------

@bp.post("/amendments/<amendment_id>/consent")
def consent_amendment(amendment_id):
    principal = require(BENEFICIARY_USER)
    amendment, deferred = pending("amendments", amendment_id)
    if amendment is not None:
        parent = db.credits.get(amendment["credit_id"])
        if parent is None or parent["beneficiary_id"] != principal.user_id:
            bail("ERR_PRINCIPAL_NOT_PARTY")

    data = v.body()
    decision = v.req_enum(data, "decision", CONSENT_DECISIONS)
    v.opt_str(data, "note", 0, 500)
    raise_pending(deferred)

    # band 4 -- own state, then the parent credit's state
    if amendment["status"] != "PENDING_CONSENT":
        bail("ERR_AMENDMENT_NOT_PENDING_CONSENT")
    credit = db.credits.get(amendment["credit_id"])
    guard_credit_state(credit, ISSUED_STATUSES, "ERR_CREDIT_NOT_ISSUED")

    # band 6 -- inclusive closed consent window
    deadline = calc.parse_date(amendment.get("consent_deadline_date"))
    if deadline is None or clock_date() > deadline:
        bail("ERR_CONSENT_WINDOW_CLOSED")

    facility = db.facilities.get(credit["facility_id"])

    if decision == "REJECT":
        amendment["status"] = "REJECTED"
        amendment["amendment_fee_cents"] = 0
        amendment["resolved_at"] = clock_instant()
        amendment["window_end_effective"] = clock_date_str()
        touch(amendment)
        credit["status"] = "ISSUED"
        touch(credit)
        return ok(public(amendment))

    # ACCEPT -- band 9 fiscal headroom on the re-cut allocation, checked last
    effective = calc.effective_change_set(amendment["change_set"], credit)
    exposure = calc.credit_allocation_exposure(
        credit, facility, "committed_issuance", overrides=effective)
    prior = ledger.open_allocation_of_credit(credit["id"])
    retained = int(prior["charge_cents"]) if prior is not None else 0
    new_charge = retained + int(amendment["amendment_fee_cents"])
    if facility is not None:
        others = 0
        for row in ledger.facility_allocations(facility["id"]):
            if row["status"] != "OPEN":
                continue
            if prior is not None and row["id"] == prior["id"]:
                continue
            others += int(row["allocated_cents"]) + int(row["charge_cents"])
        headroom = int(facility["limit_cents"]) - others
        if exposure["committed_allocation_cents"] + new_charge > headroom:
            bail("ERR_FACILITY_LIMIT_EXCEEDED")

    amendment["status"] = "ACCEPTED"
    amendment["resolved_at"] = clock_instant()
    amendment["window_end_effective"] = clock_date_str()
    touch(amendment)
    credit["status"] = "ISSUED"
    ledger.accept_amendment_effects(amendment, credit, facility)
    return ok(public(amendment))
