"""In-memory data store. Wiped on every process start; no seeding, no persistence."""
import threading
import uuid
from datetime import datetime, timezone

# Each entity collection is a dict keyed by id.
function_rooms = {}
hotel_room_blocks = {}
events = {}
bookings = {}            # FunctionRoomBooking
menu_lines = {}
service_lines = {}
room_block_links = {}
payment_schedule_items = {}
payments = {}

# A monotonic counter used to order records deterministically by creation
# (created_at carries the wall clock at three-digit ms precision, which is too
# coarse to break ties between same-millisecond inserts; this sequence keeps
# created_at-ascending list ordering stable per the PRD §2.3 sort).
_seq_counter = 0
_lock = threading.Lock()

# Server logical clock (PRD §2.9). Startup default is exactly 2026-01-01T00:00:00Z.
clock_utc = "2026-01-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock ISO 8601 UTC with three fractional digits — used for
    created_at/updated_at system timestamps (NOT the logical clock)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    global _seq_counter
    with _lock:
        _seq_counter += 1
        return _seq_counter
