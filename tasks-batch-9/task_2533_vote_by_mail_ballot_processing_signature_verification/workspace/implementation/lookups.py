"""Identifier resolution (PRD 2.6) and lineage walks."""
import db
from errors import ApiError


def _get(store, rec_id, error_id):
    if not isinstance(rec_id, str):
        raise ApiError(error_id)
    rec = store.get(rec_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def election(rec_id):
    return _get(db.elections, rec_id, "ERR_ELECTION_NOT_FOUND")


def voter(rec_id):
    return _get(db.voters, rec_id, "ERR_VOTER_NOT_FOUND")


def reviewer(rec_id):
    return _get(db.reviewers, rec_id, "ERR_REVIEWER_NOT_FOUND")


def envelope(rec_id):
    return _get(db.return_envelopes, rec_id, "ERR_ENVELOPE_NOT_FOUND")


def ballot_request(rec_id):
    return _get(db.ballot_requests, rec_id, "ERR_RECORD_NOT_FOUND")


def address_verification(rec_id):
    return _get(db.address_verifications, rec_id, "ERR_RECORD_NOT_FOUND")


def enrollment(rec_id):
    return _get(db.enrollments, rec_id, "ERR_RECORD_NOT_FOUND")


def mailing_batch(rec_id):
    return _get(db.mailing_batches, rec_id, "ERR_RECORD_NOT_FOUND")


def ballot_packet(rec_id):
    return _get(db.ballot_packets, rec_id, "ERR_RECORD_NOT_FOUND")


def signature_review(rec_id):
    return _get(db.signature_reviews, rec_id, "ERR_RECORD_NOT_FOUND")


def cure_notice(rec_id):
    return _get(db.cure_notices, rec_id, "ERR_RECORD_NOT_FOUND")


def cure_evidence(rec_id):
    return _get(db.cure_evidence, rec_id, "ERR_RECORD_NOT_FOUND")


def remake_record(rec_id):
    return _get(db.remake_records, rec_id, "ERR_RECORD_NOT_FOUND")


def observer_session(rec_id):
    return _get(db.observer_sessions, rec_id, "ERR_RECORD_NOT_FOUND")


def transparency_entry(rec_id):
    return _get(db.transparency_log, rec_id, "ERR_RECORD_NOT_FOUND")


# ---------------------------------------------------------------- lineage walks
def election_of_packet(packet):
    batch = db.mailing_batches.get(packet["mailing_batch_id"]) if packet else None
    if batch is None:
        return None
    return db.elections.get(batch["election_id"])


def election_of_envelope(env):
    if env is None:
        return None
    packet = db.ballot_packets.get(env["ballot_packet_id"])
    return election_of_packet(packet)


def election_of_notice(notice):
    if notice is None:
        return None
    return election_of_envelope(db.return_envelopes.get(notice["return_envelope_id"]))


def election_of_remake(record):
    if record is None:
        return None
    return election_of_envelope(db.return_envelopes.get(record["original_envelope_id"]))


def voter_of_envelope(env):
    if env is None:
        return None
    packet = db.ballot_packets.get(env["ballot_packet_id"])
    if packet is None:
        return None
    req = db.ballot_requests.get(packet["ballot_request_id"])
    if req is None:
        return None
    return db.voters.get(req["voter_id"])


def voter_of_packet(packet):
    if packet is None:
        return None
    req = db.ballot_requests.get(packet["ballot_request_id"])
    if req is None:
        return None
    return db.voters.get(req["voter_id"])


def packets_of_election(election_rec):
    batch_ids = {
        b["id"] for b in db.mailing_batches.values()
        if b["election_id"] == election_rec["id"]
    }
    return [p for p in db.ballot_packets.values() if p["mailing_batch_id"] in batch_ids]


def envelopes_of_election(election_rec):
    packet_ids = {p["id"] for p in packets_of_election(election_rec)}
    return [
        e for e in db.return_envelopes.values()
        if e["ballot_packet_id"] in packet_ids
    ]


def notices_of_election(election_rec):
    env_ids = {e["id"] for e in envelopes_of_election(election_rec)}
    return [n for n in db.cure_notices.values() if n["return_envelope_id"] in env_ids]


def active_enrollment_of_voter(voter_rec):
    rows = [
        e for e in db.enrollments.values()
        if e["voter_id"] == voter_rec["id"] and e["status"] == "ACTIVE"
    ]
    rows = db.ordered(rows)
    return rows[-1] if rows else None


def live_enrollment_of_voter(voter_rec):
    """Enrollment in ACTIVE or SUSPENDED, most recent first-created wins."""
    rows = [
        e for e in db.enrollments.values()
        if e["voter_id"] == voter_rec["id"] and e["status"] in ("ACTIVE", "SUSPENDED")
    ]
    rows = db.ordered(rows)
    return rows[-1] if rows else None
