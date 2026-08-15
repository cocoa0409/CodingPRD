"""In-memory data store. Fresh on every process boot (per-test-server isolation)."""

COLLECTIONS = [
    "exam_cycles",
    "courses",
    "teachers",
    "teacher_authorizations",
    "students",
    "fee_reduction_applications",
    "registrations",
    "exam_orders",
    "exam_sessions",
    "proctor_assignments",
    "irregularity_reports",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence; lists sort by it (creation order, ascending).
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
