"""In-memory data store, logical clock and serialisation helpers.

The store starts EMPTY on every boot. No entity is ever seeded, preloaded or
hardcoded here; every row is created by a client through a declared endpoint.
"""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    d = dt.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def jsonable(value):
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items()
                    if not str(k).startswith("_"))
    return value


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.providers = {}
        self.exam_forms = {}
        self.testing_sites = {}
        self.candidates = {}
        self.proctors = {}
        self.batches = {}
        self.codes = {}
        self.accommodations = {}
        self.sessions = {}
        self.score_reports = {}
        self.incidents = {}
        self.certificates = {}
        self.registrations = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self._code_seq = 0
        self._cert_seq = 0
        self._touched = set()

    # -- per-request bookkeeping ------------------------------------------
    def begin_request(self):
        """version increments exactly once per entity per request (PRD 2.4)."""
        self._touched = set()

    # -- sequencing -------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_code_value(self):
        self._code_seq += 1
        return "FMC-%08d" % self._code_seq

    def next_certificate_number(self):
        self._cert_seq += 1
        return "CERT-%08d" % self._cert_seq

    # -- record helpers ---------------------------------------------------
    def base(self):
        identifier = str(uuid.uuid4())
        self._touched.add(identifier)
        return {
            "id": identifier,
            "created_at": self.clock,
            "updated_at": self.clock,
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, record):
        if record["id"] in self._touched:
            record["updated_at"] = self.clock
            return record
        self._touched.add(record["id"])
        record["updated_at"] = self.clock
        record["version"] = record["version"] + 1
        return record

    # -- ordering ---------------------------------------------------------
    def ordered(self, rows):
        return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


store = Store()


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def now_wall():
    return datetime.now(UTC)
