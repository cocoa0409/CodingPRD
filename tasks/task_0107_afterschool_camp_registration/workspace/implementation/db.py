"""In-memory data store."""

import itertools
import threading
import uuid

from clock import clock


# Global write lock — serializes mutating operations across threads to
# preserve PRD's first-writer-wins invariants on capacity counters,
# Child.medical_authorization_status, ScholarshipAward.consumed_credit_cents,
# and SessionDay.weather_status. Re-entrant so cascade chains can nest.
write_lock = threading.RLock()

# In-flight intent tracker for confirm-vs-revoke race detection
# (PRD §3.2). Each in-flight CONFIRM and revoke-MEDICAL registers
# itself in this tracker BEFORE acquiring the global write lock.
# Inside the lock, each operation can observe whether a peer of the
# other type is/was in flight on the same child during this operation's
# lifespan. The race-LOSER is the operation whose request_entry_seq
# is greater (entered the system later) when both operations overlap;
# it rejects with ERR_AUTHORIZATION_NOT_ACTIVE.
_intent_lock = threading.Lock()
_inflight_confirm = {}  # child_id -> set[seq]
_inflight_med_revoke = {}  # child_id -> set[seq]
# Per-child "race resolution" markers — when a winner commits while a
# peer is still in flight, the winner stamps a marker the loser sees
# when it later acquires the lock.
_race_loser_seqs = {}  # child_id -> set[seq]  (these seqs MUST reject)
_intent_seq = itertools.count(1)


def next_request_seq():
    return next(_intent_seq)


def register_confirm_intent(child_id, seq):
    with _intent_lock:
        _inflight_confirm.setdefault(child_id, set()).add(seq)


def unregister_confirm_intent(child_id, seq):
    with _intent_lock:
        s = _inflight_confirm.get(child_id)
        if s is not None:
            s.discard(seq)
            if not s:
                _inflight_confirm.pop(child_id, None)


def register_med_revoke_intent(child_id, seq):
    with _intent_lock:
        _inflight_med_revoke.setdefault(child_id, set()).add(seq)


def unregister_med_revoke_intent(child_id, seq):
    with _intent_lock:
        s = _inflight_med_revoke.get(child_id)
        if s is not None:
            s.discard(seq)
            if not s:
                _inflight_med_revoke.pop(child_id, None)


def detect_race_and_mark_losers(child_id, my_op, my_seq):
    """If a peer of the opposite op-type is currently in flight on this
    child, this operation is the race-winner and the peer(s) are marked
    as losers. If THIS operation was previously marked as a loser (by
    an earlier-running peer), return True so the caller can reject."""
    with _intent_lock:
        if my_seq in _race_loser_seqs.get(child_id, set()):
            # An earlier-running peer marked me as the loser.
            _race_loser_seqs[child_id].discard(my_seq)
            if not _race_loser_seqs[child_id]:
                _race_loser_seqs.pop(child_id, None)
            return True  # I am the loser — reject.
        # Are there peer-operations of the OPPOSITE type in flight?
        peer_table = (
            _inflight_med_revoke if my_op == "confirm" else _inflight_confirm
        )
        peers = peer_table.get(child_id, set())
        if peers:
            # I am the race-winner. Mark every peer as the race-loser.
            _race_loser_seqs.setdefault(child_id, set()).update(peers)
        return False  # I am the winner (or no contention). Proceed.


def new_id():
    return str(uuid.uuid4())


def now_iso_virtual():
    return clock.now_iso()


class DataStore:
    def __init__(self):
        self.families = {}            # id -> Family dict
        self.guardians = {}           # id -> Guardian dict
        self.children = {}            # id -> Child dict
        self.emergency_contacts = {}  # id -> EmergencyContact dict
        self.authorizations = {}      # id -> Authorization dict
        self.sessions = {}            # id -> Session dict
        self.enrollments = {}         # id -> Enrollment dict
        self.scholarships = {}        # id -> ScholarshipAward dict
        self.session_days = {}        # id -> SessionDay dict

        # Family email uniqueness across non-archived families
        self.family_emails = {}  # lower-cased email -> family_id

    def reset(self):
        self.__init__()
        clock.reset()


def init_common_fields(record):
    """Set id/created_at/updated_at/version on a new record (common_fields=true)."""
    ts = now_iso_virtual()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def init_lean_fields(record):
    """Set id/created_at only — for entities without updated_at/version (Authorization, SessionDay)."""
    ts = now_iso_virtual()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    return record


def touch(record):
    """Bump updated_at and version on a mutation."""
    record["updated_at"] = now_iso_virtual()
    record["version"] = record.get("version", 1) + 1
    return record


# Singleton
db = DataStore()
