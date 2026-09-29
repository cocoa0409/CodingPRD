"""Cascades, conserved-quantity maintenance and derived-state recomputation."""

import db
from services import calc
from store import new_row, touch
from timeutil import add_days, day_span, fmt_iso


# --- speaker calendar -------------------------------------------------------

def create_hold(speaker, kind, start_raw, start_dt, end_raw, end_dt,
                engagement_id=None, reason=None):
    span = day_span(start_dt, end_dt)
    hold = new_row({
        "speaker_id": speaker["id"],
        "engagement_id": engagement_id,
        "kind": kind,
        "hold_start_utc": start_raw,
        "hold_end_utc": end_raw,
        "day_span": span,
        "status": "ACTIVE",
        "reason": reason,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.holds[hold["id"]] = hold
    speaker["held_days_count"] = speaker["held_days_count"] + span
    touch(speaker)
    return hold


def active_holds_for_speaker(speaker_id):
    return [h for h in db.holds.values()
            if h["speaker_id"] == speaker_id and h["status"] == "ACTIVE"]


def engagement_hold(engagement_id):
    for hold in db.holds.values():
        if (hold["kind"] == "ENGAGEMENT"
                and hold["engagement_id"] == engagement_id
                and hold["status"] == "ACTIVE"):
            return hold
    return None


def leave_calendar(engagement, new_status):
    """ACTIVE -> CONSUMED (delivery) or ACTIVE -> RELEASED (cancellation)."""
    hold = engagement_hold(engagement["id"])
    if hold is None:
        return None
    hold["status"] = new_status
    touch(hold)
    speaker = db.speakers[engagement["speaker_id"]]
    speaker["held_days_count"] = speaker["held_days_count"] - hold["day_span"]
    touch(speaker)
    return hold


# --- exclusivity grants -----------------------------------------------------

def sweep_expired_grants(now):
    """Lazy expiry sweep: ACTIVE grants whose window has closed become EXPIRED."""
    for grant in db.grants.values():
        if grant["status"] == "ACTIVE" and grant["_to_dt"] <= now:
            grant["status"] = "EXPIRED"
            touch(grant)


def expire_grants_of_engagement(engagement_id):
    for grant in db.grants.values():
        if grant["source_engagement_id"] == engagement_id and grant["status"] == "ACTIVE":
            grant["status"] = "EXPIRED"
            touch(grant)


def create_grant(engagement, contract, client):
    """Half-open window [event_end_utc, event_end_utc + exclusivity_days)."""
    effective_from = engagement["_event_end_dt"]
    effective_to = add_days(effective_from, contract["exclusivity_days"])
    grant = new_row({
        "source_engagement_id": engagement["id"],
        "speaker_id": engagement["speaker_id"],
        "beneficiary_client_id": client["id"],
        "industry_code": client["industry_code"],
        "effective_from_utc": engagement["event_end_utc"],
        "effective_to_utc": fmt_iso(effective_to),
        "status": "ACTIVE",
        "_from_dt": effective_from,
        "_to_dt": effective_to,
    })
    db.grants[grant["id"]] = grant
    return grant


def exclusivity_conflict(engagement, client):
    """Half-open window [effective_from_utc, effective_to_utc)."""
    event_start = engagement["_event_start_dt"]
    for grant in db.grants.values():
        if grant["status"] != "ACTIVE":
            continue
        if grant["speaker_id"] != engagement["speaker_id"]:
            continue
        if grant["industry_code"] != client["industry_code"]:
            continue
        if grant["beneficiary_client_id"] == client["id"]:
            continue
        if grant["_from_dt"] <= event_start < grant["_to_dt"]:
            return grant
    return None


# --- proposal / option bookkeeping ------------------------------------------

def options_of(proposal_id):
    return [o for o in db.options.values() if o["proposal_id"] == proposal_id]


def recount_options(proposal):
    live = [o for o in options_of(proposal["id"]) if o["status"] in ("OFFERED", "SELECTED")]
    proposal["options_count"] = len(live)
    return proposal["options_count"]


# --- invoices / remittances -------------------------------------------------

def issue_invoice(engagement, kind, now):
    if kind == "ENGAGEMENT_FEE":
        fee_line = engagement["quoted_fee_cents"]
        recording_line = engagement["recording_fee_cents"]
    else:
        fee_line = engagement["retention_net_cents"] or 0
        recording_line = 0
    travel_line = engagement["travel_reimbursable_cents"]
    surcharge = calc.invoice_surcharge(fee_line, recording_line, travel_line)
    amount_due = fee_line + recording_line + travel_line + surcharge
    client = db.clients[db.inquiries[engagement["inquiry_id"]]["client_id"]]
    invoice = new_row({
        "engagement_id": engagement["id"],
        "client_id": client["id"],
        "kind": kind,
        "fee_line_cents": fee_line,
        "recording_line_cents": recording_line,
        "travel_line_cents": travel_line,
        "surcharge_cents": surcharge,
        "amount_due_cents": amount_due,
        "amount_paid_cents": 0,
        "status": "ISSUED",
        "issued_at_utc": fmt_iso(now),
    })
    db.invoices[invoice["id"]] = invoice
    client["outstanding_balance_cents"] = client["outstanding_balance_cents"] + amount_due
    touch(client)
    return invoice


def create_remittance(engagement, gross_fee_cents, commission_cents, travel_passthrough_cents):
    net = gross_fee_cents - commission_cents + travel_passthrough_cents
    remittance = new_row({
        "engagement_id": engagement["id"],
        "speaker_id": engagement["speaker_id"],
        "gross_fee_cents": gross_fee_cents,
        "commission_cents": commission_cents,
        "travel_passthrough_cents": travel_passthrough_cents,
        "net_payable_cents": net,
        "status": "PENDING",
        "paid_at_utc": None,
    })
    db.remittances[remittance["id"]] = remittance
    speaker = db.speakers[engagement["speaker_id"]]
    speaker["pending_remittance_cents"] = speaker["pending_remittance_cents"] + net
    touch(speaker)
    return remittance


def remittance_of_engagement(engagement_id, statuses=None):
    for remittance in db.remittances.values():
        if remittance["engagement_id"] != engagement_id:
            continue
        if statuses is None or remittance["status"] in statuses:
            return remittance
    return None


# --- contracts --------------------------------------------------------------

def contracts_of(engagement_id):
    return [c for c in db.contracts.values() if c["engagement_id"] == engagement_id]


def executed_contract(engagement_id):
    for contract in contracts_of(engagement_id):
        if contract["status"] == "EXECUTED":
            return contract
    return None


def void_unexecuted_contracts(engagement_id):
    for contract in contracts_of(engagement_id):
        if contract["status"] in ("DRAFT", "SENT", "PARTIALLY_SIGNED"):
            contract["status"] = "VOID"
            touch(contract)


# --- speaker performance and tiering ---------------------------------------

def feedback_candidates(speaker_id):
    """Every Feedback reachable from this speaker's engagements, newest first.

    Ordered by Feedback.created_at DESC, then engagement.event_start_utc DESC.
    """
    rows = []
    for feedback in db.feedbacks.values():
        engagement = db.engagements.get(feedback["engagement_id"])
        if engagement is None or engagement["speaker_id"] != speaker_id:
            continue
        rows.append((feedback, engagement))
    rows.sort(
        key=lambda pair: (pair[0]["_created_ts"], pair[1]["_event_start_dt"], pair[0]["_seq"]),
        reverse=True,
    )
    return [pair[0] for pair in rows]


def recompute_speaker_scores(speaker):
    composites = [f["composite_score"] for f in feedback_candidates(speaker["id"])]
    rolling = calc.rolling_score(composites)
    lifetime = calc.lifetime_score(composites)
    speaker["rolling_score"] = float(rolling) if rolling is not None else None
    speaker["lifetime_score"] = float(lifetime) if lifetime is not None else None
    touch(speaker)


def apply_roster_tier(speaker):
    tier = calc.roster_tier(speaker["engagements_delivered_count"], speaker["rolling_score"])
    speaker["roster_tier"] = tier
    speaker["default_commission_pct"] = float(calc.TIER_COMMISSION_PCT[tier])
    touch(speaker)
    return tier


# --- inquiry cascades -------------------------------------------------------

def block_qualified_inquiries(client_id):
    for inquiry in db.inquiries.values():
        if inquiry["client_id"] == client_id and inquiry["status"] == "QUALIFIED":
            inquiry["status"] = "BLOCKED"
            touch(inquiry)


def unblock_inquiries(client_id):
    for inquiry in db.inquiries.values():
        if inquiry["client_id"] == client_id and inquiry["status"] == "BLOCKED":
            inquiry["status"] = "QUALIFIED"
            touch(inquiry)
