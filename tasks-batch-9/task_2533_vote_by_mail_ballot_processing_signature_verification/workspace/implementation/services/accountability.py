"""Ballot accountability and the conservation invariants (PRD 2.11)."""
import db
import lookups


def figures(election_rec):
    packets = lookups.packets_of_election(election_rec)
    packet_ids = {p["id"] for p in packets}
    envelopes = [
        e for e in db.return_envelopes.values() if e["ballot_packet_id"] in packet_ids
    ]
    env_ids = {e["id"] for e in envelopes}
    notices = [
        n for n in db.cure_notices.values() if n["return_envelope_id"] in env_ids
    ]

    packets_mailed = sum(
        1 for p in packets if p["status"] in ("MAILED", "RETURNED", "UNDELIVERABLE")
    )
    returned = sum(1 for p in packets if p["status"] == "RETURNED")
    outstanding = sum(1 for p in packets if p["status"] == "MAILED")
    undeliverable = sum(1 for p in packets if p["status"] == "UNDELIVERABLE")
    delta = packets_mailed - (returned + outstanding + undeliverable)

    countable = sum(
        1 for e in envelopes
        if e["signature_status"] == "ACCEPTED"
        and e["custody_status"] in ("SEPARATED", "COUNTED")
        and e["challenge_status"] != "SUSTAINED"
    )
    attributable = sum(
        1 for e in envelopes
        if e["custody_status"] in ("SEALED", "SEPARATED", "COUNTED")
        and e["signature_status"] != "REJECTED"
    )
    rejected = sum(1 for e in envelopes if e["signature_status"] == "REJECTED")
    open_cures = sum(
        1 for n in notices if n["status"] in ("ISSUED", "UNDER_EVIDENCE_REVIEW")
    )
    return {
        "packets_mailed_count": packets_mailed,
        "returned_packet_count": returned,
        "outstanding_packet_count": outstanding,
        "undeliverable_packet_count": undeliverable,
        "envelopes_received_count": len(envelopes),
        "countable_envelope_count": countable,
        "attributable_ballot_count": attributable,
        "rejected_envelope_count": rejected,
        "open_cure_count": open_cures,
        "accountability_delta": delta,
        "reconciliation_status": "IN_BALANCE" if delta == 0 else "OUT_OF_BALANCE",
    }


ELECTION_KEYS = (
    "packets_mailed_count",
    "outstanding_packet_count",
    "undeliverable_packet_count",
    "envelopes_received_count",
    "countable_envelope_count",
    "attributable_ballot_count",
    "rejected_envelope_count",
    "open_cure_count",
    "reconciliation_status",
)


def recompute(election_rec):
    """Write the live accountability picture onto the election.

    The record is only touched when a figure actually changed, so a read that
    changes nothing never bumps the election's version.
    """
    if election_rec is None:
        return None
    computed = figures(election_rec)
    changed = False
    for key in ELECTION_KEYS:
        if election_rec.get(key) != computed[key]:
            election_rec[key] = computed[key]
            changed = True
    if changed:
        db.touch(election_rec)
    return election_rec


def postage_totals(election_rec):
    """postage_committed_cents / postage_actual_cents by definition (PRD 2.11)."""
    batches = [
        b for b in db.mailing_batches.values()
        if b["election_id"] == election_rec["id"]
    ]
    committed = sum(
        b["estimated_postage_cents"] or 0
        for b in batches
        if b["status"] in ("SEALED", "DISPATCHED")
    )
    actual = sum(
        b["actual_postage_cents"] or 0
        for b in batches
        if b["status"] == "DISPATCHED"
    )
    return committed, actual


def accountability_read(election_rec):
    recompute(election_rec)
    computed = figures(election_rec)
    return {
        "election_id": election_rec["id"],
        "packets_mailed_count": computed["packets_mailed_count"],
        "returned_packet_count": computed["returned_packet_count"],
        "outstanding_packet_count": computed["outstanding_packet_count"],
        "undeliverable_packet_count": computed["undeliverable_packet_count"],
        "envelopes_received_count": computed["envelopes_received_count"],
        "countable_envelope_count": computed["countable_envelope_count"],
        "attributable_ballot_count": computed["attributable_ballot_count"],
        "rejected_envelope_count": computed["rejected_envelope_count"],
        "provisional_referral_count": election_rec["provisional_referral_count"],
        "open_cure_count": computed["open_cure_count"],
        "accountability_delta": computed["accountability_delta"],
        "reconciliation_status": computed["reconciliation_status"],
        "postage_committed_cents": election_rec["postage_committed_cents"],
        "postage_actual_cents": election_rec["postage_actual_cents"],
    }


BATCH_PACKET_STATUSES = ("QUEUED", "MAILED", "RETURNED", "UNDELIVERABLE")


def recompute_batch(batch):
    """MailingBatch.packet_count counts QUEUED|MAILED|RETURNED|UNDELIVERABLE."""
    if batch is None:
        return None
    count = sum(
        1 for p in db.ballot_packets.values()
        if p["mailing_batch_id"] == batch["id"] and p["status"] in BATCH_PACKET_STATUSES
    )
    if batch["packet_count"] != count:
        batch["packet_count"] = count
        db.touch(batch)
    return batch
