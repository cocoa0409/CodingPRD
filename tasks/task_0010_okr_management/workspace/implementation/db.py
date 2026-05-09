"""In-memory data store. Each entity is a dict keyed by id -> entity dict."""

from threading import RLock

# Master lock; coarse-grained — sufficient for benchmark
LOCK = RLock()

departments = {}      # id -> Department
users = {}            # id -> User
cycles = {}           # id -> OKRCycle
objectives = {}       # id -> Objective
key_results = {}      # id -> KeyResult
progress_updates = {} # id -> ProgressUpdate
alignment_links = {}  # id -> AlignmentLink
co_ownerships = {}    # id -> CoOwnership
review_scores = {}    # id -> ReviewScore
access_grants = {}    # id -> AccessGrant
audit_logs = {}       # id -> AuditLog
external_events = {}  # id -> ExternalEvent


def reset():
    for d in (departments, users, cycles, objectives, key_results,
              progress_updates, alignment_links, co_ownerships,
              review_scores, access_grants, audit_logs, external_events):
        d.clear()
