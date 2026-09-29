"""Lookups, derived counters, effective filings and the NPA exhaust posture."""

from decimal import Decimal

from db import db, dec, days, now, r2, touch, by_created, by_created_desc
from errors import ApiError
from services import constants as C


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def _find(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    record = collection.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def get_carrier(carrier_id):
    return _find(db.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")


def get_npa(npa_id):
    return _find(db.npas, npa_id, "ERR_NPA_NOT_FOUND")


def get_rate_center(rate_center_id):
    return _find(db.rate_centers, rate_center_id, "ERR_RATE_CENTER_NOT_FOUND")


def get_block(block_id):
    return _find(db.blocks, block_id, "ERR_BLOCK_NOT_FOUND")


def get_request(request_id):
    return _find(db.allocation_requests, request_id, "ERR_ALLOCATION_REQUEST_NOT_FOUND")


def get_filing(filing_id):
    return _find(db.filings, filing_id, "ERR_FILING_NOT_FOUND")


def get_finding(finding_id):
    return _find(db.findings, finding_id, "ERR_AUDIT_FINDING_NOT_FOUND")


def get_order(order_id):
    return _find(db.orders, order_id, "ERR_RECLAMATION_ORDER_NOT_FOUND")


def get_plan(plan_id):
    return _find(db.relief_plans, plan_id, "ERR_RELIEF_PLAN_NOT_FOUND")


def get_port_request(port_request_id):
    return _find(db.port_requests, port_request_id, "ERR_PORT_REQUEST_NOT_FOUND")


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------

def blocks_of_rate_center(rate_center_id):
    return by_created(
        [b for b in db.blocks.values() if b["rate_center_id"] == rate_center_id]
    )


def blocks_of_npa(npa_id):
    return by_created([b for b in db.blocks.values() if b["npa_id"] == npa_id])


def rate_centers_of_npa(npa_id):
    return by_created([r for r in db.rate_centers.values() if r["npa_id"] == npa_id])


def blocks_of_carrier(carrier_id):
    return by_created(
        [b for b in db.blocks.values() if b.get("holder_carrier_id") == carrier_id]
    )


def routing_records_of_block(block_id):
    records = [r for r in db.routing_records.values() if r["number_block_id"] == block_id]
    return sorted(records, key=lambda r: (r["effective_at"], r["_seq"]))


def open_routing_record(block_id):
    """The block's single open published row, if any."""
    for record in reversed(routing_records_of_block(block_id)):
        if record["record_status"] == "PUBLISHED" and record["end_at"] is None:
            return record
    return None


# --------------------------------------------------------------------------
# derived counters (PRD 2.9)
# --------------------------------------------------------------------------

def carrier_blocks_held(carrier_id):
    return len(
        [
            b
            for b in db.blocks.values()
            if b.get("holder_carrier_id") == carrier_id
            and b["allocation_status"] in C.HELD_STATUSES
        ]
    )


def npa_available_count(npa_id):
    return len(
        [
            b
            for b in db.blocks.values()
            if b["npa_id"] == npa_id and b["allocation_status"] == "POOL_AVAILABLE"
        ]
    )


def npa_total_count(npa_id):
    return len([b for b in db.blocks.values() if b["npa_id"] == npa_id])


def rc_available_count(rate_center_id):
    return len(
        [
            b
            for b in db.blocks.values()
            if b["rate_center_id"] == rate_center_id
            and b["allocation_status"] == "POOL_AVAILABLE"
        ]
    )


def rc_assigned_count(rate_center_id):
    return len(
        [
            b
            for b in db.blocks.values()
            if b["rate_center_id"] == rate_center_id
            and b["allocation_status"] in C.HELD_STATUSES
        ]
    )


def rc_pending_request_count(rate_center_id):
    return len(
        [
            r
            for r in db.allocation_requests.values()
            if r["rate_center_id"] == rate_center_id
            and r["status"] in ("PENDING_REVIEW", "INFO_REQUESTED")
        ]
    )


def accepts_initial_requests(rate_center):
    if rate_center["jeopardy_flag"]:
        return False
    if rate_center["pooling_status"] == "TRANSITIONAL":
        return False
    return True


def is_pooling_eligible(block):
    return block["contaminated_count"] <= C.CONTAMINATION_MAX_FOR_POOLING


def comment_count(plan_id):
    return len([c for c in db.comments.values() if c["relief_plan_id"] == plan_id])


# --------------------------------------------------------------------------
# carrier eligibility (PRD 3.1)
# --------------------------------------------------------------------------

def eligibility_status(carrier):
    license_status = carrier["license_status"]
    readiness = carrier["facilities_readiness_status"]
    strikes = carrier["reclamation_strike_count"]
    probation_until = carrier["probation_until"]
    if license_status in ("SUSPENDED", "REVOKED"):
        return "SUSPENDED"
    if license_status == "GRANTED" and readiness == "VERIFIED":
        if strikes >= C.RECLAMATION_PROBATION_STRIKES or (
            probation_until is not None and probation_until > now()
        ):
            return "PROBATION"
        if strikes < C.RECLAMATION_PROBATION_STRIKES and (
            probation_until is None or probation_until <= now()
        ):
            return "ELIGIBLE"
    return "INELIGIBLE"


def license_expired(carrier):
    expires = carrier["license_expires_on"]
    return expires is None or expires <= now()


def on_probation(carrier):
    if eligibility_status(carrier) == "PROBATION":
        return True
    probation_until = carrier["probation_until"]
    return probation_until is not None and probation_until > now()


# --------------------------------------------------------------------------
# filings
# --------------------------------------------------------------------------

def filings_for(carrier_id, rate_center_id, statuses):
    return [
        f
        for f in db.filings.values()
        if f["carrier_id"] == carrier_id
        and f["rate_center_id"] == rate_center_id
        and f["status"] in statuses
    ]


def _submitted_key(filing):
    stamp = filing["submitted_at"]
    return (
        stamp is not None,
        stamp or filing["created_at"],
        filing["created_at"],
        filing["_seq"],
    )


def effective_filing(carrier_id, rate_center_id):
    """Newest SUBMITTED/ACCEPTED/REJECTED filing, submitted_at DESC then created_at DESC."""
    rows = filings_for(carrier_id, rate_center_id, C.FILING_EFFECTIVE_STATUSES)
    if not rows:
        return None
    rows.sort(key=_submitted_key)
    return rows[-1]


def sweep_effective_filing(carrier_id, rate_center_id):
    """Narrower definition used by the sweep: SUBMITTED or ACCEPTED only."""
    rows = filings_for(carrier_id, rate_center_id, ("SUBMITTED", "ACCEPTED"))
    if not rows:
        return None
    rows.sort(key=_submitted_key)
    return rows[-1]


def chronological_filings(carrier_id, rate_center_id):
    """SUBMITTED/ACCEPTED filings ordered submitted_at ASC then created_at ASC."""
    rows = filings_for(carrier_id, rate_center_id, ("SUBMITTED", "ACCEPTED"))
    rows.sort(key=_submitted_key)
    return rows


def effective_utilization(carrier_id, rate_center_id):
    """PRD 3.4: audited when present, else claimed, else 0.00."""
    filing = effective_filing(carrier_id, rate_center_id)
    if filing is None:
        return Decimal("0.00")
    if filing["audited_utilization_pct"] is not None:
        return dec(filing["audited_utilization_pct"])
    if filing["claimed_utilization_pct"] is None:
        return Decimal("0.00")
    return dec(filing["claimed_utilization_pct"])


def aggregate_utilization_pct(rate_center_id):
    """PRD 3.3: pooled over the effective filings of the holders."""
    holders = []
    for block in blocks_of_rate_center(rate_center_id):
        holder = block.get("holder_carrier_id")
        if holder and block["allocation_status"] in ("RESERVED", "ASSIGNED"):
            if holder not in holders:
                holders.append(holder)
    numerator = 0
    denominator = 0
    seen_any = False
    for holder in holders:
        filing = effective_filing(holder, rate_center_id)
        if filing is None:
            continue
        seen_any = True
        numerator += (
            filing["numbers_assigned"]
            + filing["numbers_intermediate"]
            + filing["numbers_reserved"]
        )
        denominator += (
            filing["blocks_held_at_period_end"] * C.NUMBERS_PER_BLOCK
            - filing["numbers_administrative"]
            - filing["numbers_aging"]
        )
    if not seen_any:
        # no holder has an effective filing; does anybody at all?
        for filing in db.filings.values():
            if (
                filing["rate_center_id"] == rate_center_id
                and filing["status"] in C.FILING_EFFECTIVE_STATUSES
            ):
                return 0.00
        return None
    if denominator <= 0:
        return 0.00
    return r2(dec(numerator) * Decimal(100) / dec(denominator))


# --------------------------------------------------------------------------
# NPA exhaust posture (PRD 3.2)
# --------------------------------------------------------------------------

def npa_exhaust_posture(npa):
    available = npa_available_count(npa["id"])
    if npa["status"] == "RETIRED":
        return "RETIRED"
    if npa["status"] == "RELIEF_PLANNED":
        return "RELIEF_PLANNED"
    if available == 0:
        return "EXHAUSTED"
    if available <= C.NPA_JEOPARDY_AVAILABLE_BLOCKS:
        return "JEOPARDY"
    if npa["status"] == "EXHAUSTED" and npa["jeopardy_declared_at"] is not None:
        return "JEOPARDY"
    return "ACTIVE"


def set_rate_center_jeopardy(npa_id, flag):
    for rate_center in rate_centers_of_npa(npa_id):
        if rate_center["jeopardy_flag"] != flag:
            rate_center["jeopardy_flag"] = flag
            touch(rate_center)


def apply_posture(npa, new_status):
    """Apply one posture edge with its bookkeeping.  Returns True when it moved."""
    old_status = npa["status"]
    if new_status == old_status:
        return False
    npa["status"] = new_status
    if new_status == "JEOPARDY":
        if old_status == "ACTIVE":
            npa["jeopardy_declared_at"] = now()
        set_rate_center_jeopardy(npa["id"], True)
    elif new_status == "EXHAUSTED":
        set_rate_center_jeopardy(npa["id"], True)
    elif new_status == "ACTIVE":
        npa["jeopardy_declared_at"] = None
        set_rate_center_jeopardy(npa["id"], False)
    touch(npa)
    return True


def recompute_npa_posture(npa):
    return apply_posture(npa, npa_exhaust_posture(npa))


def declare_jeopardy(npa):
    npa["status"] = "JEOPARDY"
    npa["jeopardy_declared_at"] = now()
    set_rate_center_jeopardy(npa["id"], True)
    touch(npa)


# --------------------------------------------------------------------------
# probation cascade (PRD 3.3 / 3.7)
# --------------------------------------------------------------------------

def push_pending_growth_requests_to_info(carrier_id):
    rows = [
        r
        for r in db.allocation_requests.values()
        if r["carrier_id"] == carrier_id
        and r["status"] == "PENDING_REVIEW"
        and r["request_type"] in ("GROWTH", "POOL_REPLENISH")
    ]
    for request in by_created(rows):
        request["status"] = "INFO_REQUESTED"
        request["info_request_count"] += 1
        touch(request)


def enter_probation(carrier, add_strike=False):
    if add_strike:
        carrier["reclamation_strike_count"] += 1
    carrier["probation_until"] = now() + days(C.PROBATION_DAYS)
    touch(carrier)
    push_pending_growth_requests_to_info(carrier["id"])
