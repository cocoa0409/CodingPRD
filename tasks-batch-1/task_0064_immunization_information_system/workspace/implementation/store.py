import uuid
from datetime import datetime, timezone


class Clock:
    """Server clock; can be overridden for test-driving via /_clock/set_current_utc."""
    def __init__(self):
        self._override = None  # datetime (UTC) or None

    def set_utc(self, dt):
        self._override = dt

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def today_date(self):
        return self.now().date()


class Store:
    def __init__(self):
        self.patients = {}
        self.providers = {}
        self.products = {}
        self.lots = {}
        self.immunizations = {}
        self.allergy_records = {}
        self.provider_reports = {}
        self.report_lines = {}          # line_id -> line dict (pending lines for reports)
        self.adverse_events = {}
        self.evaluations = {}
        self.certificates = {}
        self.recalls = {}
        self.clock = Clock()
        self._seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        # monotonic creation sequence as a stable tie-break for equal timestamps
        self._seq += 1
        return self._seq


def now_iso(clock):
    dt = clock.now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


STORE = Store()
