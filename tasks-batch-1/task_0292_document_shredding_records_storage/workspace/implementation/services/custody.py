"""Custody chain + the destruction certificate/invoice cascade (PRD §3.4-§3.6)."""
from db import db, stamp_create, touch
from services.calculations import destruction_charge


def append_custody_event(order, subject_type, subject_id, event_type, actor_id):
    """Append one immutable CustodyEvent (id + created_at only).

    sequence_no is 1-based monotonic within the order's chain.
    """
    # Next sequence number within this order's chain.
    existing = [e for e in db.custody_events.values() if e["order_id"] == order["id"]]
    seq_no = len(existing) + 1
    ev = {
        "order_id": order["id"],
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "sequence_no": seq_no,
        "actor_id": actor_id,
    }
    stamp_create(ev, with_version=False)  # only id + created_at
    db.custody_events[ev["id"]] = ev
    return ev


def serviced_containers(order):
    """Container dicts named in the order's container_ids, in listed order."""
    out = []
    for cid in order.get("container_ids") or []:
        c = db.containers.get(cid)
        if c is not None:
            out.append(c)
    return out


def next_certificate_no(account_id):
    """Server-minted serial, monotonic per account, ordered by issuance created_at."""
    count = sum(1 for c in db.certificates.values() if c["account_id"] == account_id)
    return "CERT-%d" % (count + 1)


def run_destruction_cascade(order, witnessed_by):
    """Three-hop cascade (PRD §3.6): finalize order -> issue certificate -> issue invoice.

    The caller has already set order.billed_weight_kg and recomputed order_charge_cents
    (hop 1 finalization happens before this for the plant branch at receive-at-plant;
    for on-site it happens at the shred step). Here we issue the certificate and invoice.
    Returns (certificate, invoice).
    """
    # Hop 2: auto-issue DestructionCertificate.
    cert = {
        "order_id": order["id"],
        "account_id": order["account_id"],
        "certificate_no": next_certificate_no(order["account_id"]),
        "destroyed_weight_kg": order["billed_weight_kg"],
        "witnessed_by": witnessed_by,
        "status": "ISSUED",
    }
    stamp_create(cert)
    db.certificates[cert["id"]] = cert

    # Hop 3: certificate issuance creates DestructionInvoice.
    inv = {
        "order_id": order["id"],
        "account_id": order["account_id"],
        "certificate_id": cert["id"],
        "line_cents": order["order_charge_cents"],
        "status": "ISSUED",
    }
    stamp_create(inv)
    db.destruction_invoices[inv["id"]] = inv

    return cert, inv


def finalize_order_charge(order, net_weight_kg, rate_card):
    """Hop 1 finalization: set billed_weight_kg to actual net, recompute charge (final)."""
    order["billed_weight_kg"] = net_weight_kg
    order["order_charge_cents"] = destruction_charge(order, rate_card)
