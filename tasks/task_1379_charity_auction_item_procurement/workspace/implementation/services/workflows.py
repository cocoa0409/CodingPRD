"""Shared domain workflows: cascades, bubble-ups, sweeps, acknowledgment tracking
(scaffold section 1.2 state machines; PRD 2.10, 3.3, 3.6-3.9)."""

import uuid
from datetime import timedelta

import clock
import errors
import middleware as mw
from db import stores
from services import calc


# ------------------------------------------------------------------ lookups

def event_of_gala(gala_event_id):
    return stores["gala_events"][gala_event_id]


def member_items(bundle):
    items = [i for i in stores["items"].values() if i["bundle_id"] == bundle["id"]]
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def active_bid(bundle_id):
    for b in stores["bids"].values():
        if b["bundle_id"] == bundle_id and b["status"] == "ACTIVE":
            return b
    return None


def certificate_of(invoice_id):
    for c in stores["certificates"].values():
        if c["invoice_id"] == invoice_id:
            return c
    return None


def invoice_amount_paid(invoice_id):
    """amount_paid_cents = sum(SUCCEEDED) - sum(REFUNDED); a refunded payment was
    previously succeeded, so the conserved-ledger value equals the SUCCEEDED sum
    (a full refund recomputes to zero, PRD 3.7)."""
    return sum(
        p["amount_cents"]
        for p in stores["payments"].values()
        if p["invoice_id"] == invoice_id and p["status"] == "SUCCEEDED"
    )


# ------------------------------------------------------------------ serializers

def serialize_bundle(bundle):
    """While DRAFT, min_bid_cents shows the PREVIEW variant computed on the fly
    from the current (unfrozen) bundle_fmv_cents (PRD 3.4)."""
    out = mw.serialize(bundle)
    if bundle["status"] == "DRAFT":
        event = stores["gala_events"].get(bundle["gala_event_id"])
        if event is not None:
            out["min_bid_cents"] = calc.minimum_bid_cents(bundle["bundle_fmv_cents"], event)
    return out


def serialize_invoice(invoice):
    out = mw.serialize(invoice)
    out["amount_paid_cents"] = invoice_amount_paid(invoice["id"])
    return out


# ------------------------------------------------------------------ solicitations

def check_cooldown(donor_id, event, exclude_id=None):
    """Half-open window [last_sent_at, last_sent_at + cooldown_days) against any
    OTHER solicitation of the same (donor, event); a solicitation may always
    re-send itself (PRD 3.2)."""
    now = clock.now()
    window = timedelta(days=event["solicitation_cooldown_days"])
    for s in stores["solicitations"].values():
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["donor_id"] != donor_id or s["gala_event_id"] != event["id"]:
            continue
        last = s["last_sent_at"]
        if last is not None and last <= now < last + window:
            raise errors.err_solicitation_cooldown(
                "Donor has a solicitation whose last_sent_at is within the cooldown window"
            )


# ------------------------------------------------------------------ acknowledgments

def latest_active_ack(item_id):
    acks = [
        a for a in stores["acknowledgments"].values()
        if a["item_id"] == item_id and a["status"] != "VOIDED"
    ]
    if not acks:
        return None
    return sorted(acks, key=lambda r: (r["created_at"], r["_seq"]))[-1]


def create_ack(item):
    rec = mw.new_record()
    rec.update({
        "donor_id": item["donor_id"],
        "gala_event_id": item["gala_event_id"],
        "item_id": item["id"],
        "kind": "DONATION_RECEIPT",
        "fmv_cents": item["current_fmv_cents"],
        "disclosure_tier": item["disclosure_tier"],
        "status": "PENDING",
        "issued_at": None,
    })
    stores["acknowledgments"][rec["id"]] = rec
    return rec


# ------------------------------------------------------------------ dispositions

def create_disposition(item):
    rec = mw.new_record()
    rec.update({
        "item_id": item["id"],
        "gala_event_id": item["gala_event_id"],
        "donor_id": item["donor_id"],
        "decision": None,
        "target_gala_event_id": None,
        "status": "PROPOSED",
    })
    stores["dispositions"][rec["id"]] = rec
    return rec


def _latest_disposition_executed(item_id):
    disps = [d for d in stores["dispositions"].values() if d["item_id"] == item_id]
    if not disps:
        return False
    latest = sorted(disps, key=lambda r: (r["created_at"], r["_seq"]))[-1]
    return latest["status"] == "EXECUTED"


def execute_disposition(disp):
    """Donor accepted: run the decided path on the item, then bubble the bundle
    up to DISPOSITIONED when every member item's latest disposition is EXECUTED."""
    item = stores["items"][disp["item_id"]]
    old_bundle_id = item["bundle_id"]
    decision = disp["decision"]
    if decision == "RETURN_TO_DONOR":
        item["status"] = "RETURNED_TO_DONOR"
        mw.touch(item)
        ack = latest_active_ack(item["id"])
        if ack is not None:
            ack["status"] = "VOIDED"
            mw.touch(ack)
    elif decision == "ROLLOVER":
        item["gala_event_id"] = disp["target_gala_event_id"]
        item["bundle_id"] = None
        item["status"] = "VALUED"
        mw.touch(item)
        ack = latest_active_ack(item["id"])
        if ack is not None:
            ack["status"] = "VOIDED"
            mw.touch(ack)
        create_ack(item)
    elif decision == "DISCARD":
        item["status"] = "DISCARDED"
        mw.touch(item)
        # Acknowledgment unchanged: the gift completed; remains issuable.
    if old_bundle_id:
        bundle = stores["bundles"].get(old_bundle_id)
        if bundle is not None and bundle["status"] == "UNSOLD":
            members = member_items(bundle)
            if all(_latest_disposition_executed(i["id"]) for i in members):
                bundle["status"] = "DISPOSITIONED"
                mw.touch(bundle)


# ------------------------------------------------------------------ valuations

def recompute_bundle_fmv(bundle):
    bundle["bundle_fmv_cents"] = sum(
        (i["current_fmv_cents"] or 0) for i in member_items(bundle)
    )
    mw.touch(bundle)


def apply_valuation_approval(valuation, approver_id):
    """Item fmv/tier update; RECEIVED -> VALUED on first approval; acknowledgment
    create/refresh/void+recreate; DRAFT bundle FMV recompute (PRD 3.3)."""
    item = stores["items"][valuation["item_id"]]
    valuation["status"] = "APPROVED"
    valuation["decided_by_user_id"] = approver_id
    mw.touch(valuation)

    item["current_fmv_cents"] = valuation["fmv_cents"]
    item["disclosure_tier"] = calc.disclosure_tier(valuation["fmv_cents"])
    if item["status"] == "RECEIVED":
        item["status"] = "VALUED"
        mw.touch(item)
        create_ack(item)
    else:
        mw.touch(item)
        ack = latest_active_ack(item["id"])
        if ack is not None:
            if ack["status"] == "PENDING":
                # AS_OF_ISSUE: PENDING acknowledgment tracks re-valuations.
                ack["fmv_cents"] = item["current_fmv_cents"]
                ack["disclosure_tier"] = item["disclosure_tier"]
                mw.touch(ack)
            elif ack["status"] == "ISSUED":
                ack["status"] = "VOIDED"
                mw.touch(ack)
                create_ack(item)
        if item["status"] == "BUNDLED" and item["bundle_id"]:
            bundle = stores["bundles"].get(item["bundle_id"])
            if bundle is not None and bundle["status"] == "DRAFT":
                recompute_bundle_fmv(bundle)


# ------------------------------------------------------------------ close cascade

def new_certificate(invoice):
    rec = mw.new_record()
    while True:
        code = "CERT-" + uuid.uuid4().hex[:8].upper()
        if all(c["certificate_code"] != code for c in stores["certificates"].values()):
            break
    rec.update({
        "invoice_id": invoice["id"],
        "certificate_code": code,
        "status": "PENDING_ISSUE",
        "issued_at": None,
        "valid_from": None,
        "expires_at": None,
        "grace_end_at": None,
        "redeemed_at": None,
        "scheduled_start": None,
        "scheduled_end": None,
    })
    stores["certificates"][rec["id"]] = rec
    return rec


def close_cascade(event):
    """BIDDING_OPEN -> BIDDING_CLOSED: settle every PUBLISHED bundle in
    published_at ASC order (tie-break created_at ASC) (PRD 3.6)."""
    published = [
        b for b in stores["bundles"].values()
        if b["gala_event_id"] == event["id"] and b["status"] == "PUBLISHED"
    ]
    published.sort(key=lambda r: (r["published_at"], r["created_at"], r["_seq"]))
    for bundle in published:
        bid = active_bid(bundle["id"])
        members = member_items(bundle)
        if bid is not None:
            bundle["status"] = "SOLD"
            mw.touch(bundle)
            bid["status"] = "WINNER"
            mw.touch(bid)
            winning = bid["amount_cents"]
            fmv = bundle["bundle_fmv_cents"]
            revenue, contribution = calc.split_portions(winning, fmv)
            prorata = calc.prorata_contribution(
                winning, fmv, [i["current_fmv_cents"] for i in members]
            )
            inv = mw.new_record()
            inv.update({
                "gala_event_id": bundle["gala_event_id"],
                "bundle_id": bundle["id"],
                "bidder_id": bid["bidder_id"],
                "winning_bid_cents": winning,
                "pinned_bundle_fmv_cents": fmv,
                "revenue_portion_cents": revenue,
                "contribution_portion_cents": contribution,
                "contribution_prorata_cents": prorata,
                "payment_status": "UNPAID",
                "fulfillment_status": "PENDING",
            })
            stores["invoices"][inv["id"]] = inv
            has_experience = False
            for item in members:
                item["status"] = "SOLD"
                mw.touch(item)
                if item["kind"] == "EXPERIENCE":
                    has_experience = True
            if has_experience:
                new_certificate(inv)
        else:
            bundle["status"] = "UNSOLD"
            mw.touch(bundle)
            for item in members:
                item["status"] = "UNSOLD"
                mw.touch(item)
                create_disposition(item)


# ------------------------------------------------------------------ payments

def issue_certificate(invoice):
    """Certificate PENDING_ISSUE -> ISSUED with the validity window (PRD 3.8)."""
    cert = certificate_of(invoice["id"])
    if cert is None or cert["status"] != "PENDING_ISSUE":
        return
    event = stores["gala_events"][invoice["gala_event_id"]]
    now = clock.now()
    expires = calc.add_months(now, event["cert_validity_months"])
    cert["status"] = "ISSUED"
    cert["issued_at"] = now
    cert["valid_from"] = now
    cert["expires_at"] = expires
    cert["grace_end_at"] = expires + timedelta(days=event["cert_grace_days"])
    mw.touch(cert)


def paid_cascade(invoice):
    """UNPAID/PARTIALLY_PAID -> PAID; fulfillment PENDING -> READY; certificate issued."""
    invoice["payment_status"] = "PAID"
    if invoice["fulfillment_status"] == "PENDING":
        invoice["fulfillment_status"] = "READY"
    mw.touch(invoice)
    issue_certificate(invoice)


def settle_bundle_bubble(invoice):
    """Bubble-up: invoice fulfilled/expired moves its SOLD bundle to SETTLED."""
    bundle = stores["bundles"].get(invoice["bundle_id"])
    if bundle is not None and bundle["status"] == "SOLD":
        bundle["status"] = "SETTLED"
        mw.touch(bundle)


def _unsold_compensation(invoice):
    """Shared unwind for refund / write-off (PRD 3.7): certificate voided,
    fulfillment voided, WINNER bid voided, bundle and member items re-opened to
    UNSOLD with one PROPOSED disposition per member item."""
    cert = certificate_of(invoice["id"])
    if cert is not None and cert["status"] in ("PENDING_ISSUE", "ISSUED"):
        cert["status"] = "VOIDED"
        mw.touch(cert)
    if invoice["fulfillment_status"] in ("PENDING", "READY"):
        invoice["fulfillment_status"] = "VOIDED"
    mw.touch(invoice)
    bundle = stores["bundles"].get(invoice["bundle_id"])
    if bundle is not None:
        for b in stores["bids"].values():
            if b["bundle_id"] == bundle["id"] and b["status"] == "WINNER":
                b["status"] = "VOID"
                mw.touch(b)
        if bundle["status"] == "SOLD":
            bundle["status"] = "UNSOLD"
            mw.touch(bundle)
            for item in member_items(bundle):
                if item["status"] == "SOLD":
                    item["status"] = "UNSOLD"
                    mw.touch(item)
                create_disposition(item)


def refund_cascade(invoice):
    for p in stores["payments"].values():
        if p["invoice_id"] == invoice["id"] and p["status"] == "SUCCEEDED":
            p["status"] = "REFUNDED"
            mw.touch(p)
    invoice["payment_status"] = "REFUNDED"
    _unsold_compensation(invoice)


def writeoff_cascade(invoice):
    invoice["payment_status"] = "WRITTEN_OFF"
    _unsold_compensation(invoice)


# ------------------------------------------------------------------ clock sweep

def expiry_sweep():
    """On clock set: ISSUED certificates with expires_at STRICTLY before the new
    instant expire (closed bound: equality survives) (PRD 2.5, 3.8)."""
    now = clock.now()
    for cert in list(stores["certificates"].values()):
        if cert["status"] == "ISSUED" and cert["expires_at"] < now:
            cert["status"] = "EXPIRED"
            mw.touch(cert)
            invoice = stores["invoices"].get(cert["invoice_id"])
            if invoice is not None and invoice["fulfillment_status"] == "READY":
                invoice["fulfillment_status"] = "EXPIRED"
                mw.touch(invoice)
                settle_bundle_bubble(invoice)
