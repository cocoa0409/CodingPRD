"""In-memory data store, IDs, sequencing."""

import uuid
import threading


_LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.programs = {}                  # id -> Program dict
        self.recruiting_calendars = {}      # id -> RecruitingCalendar dict
        self.athletes = {}                  # id -> Athlete dict
        self.eligibility_records = {}       # id -> EligibilityRecord dict
        self.scholarship_slots = {}         # id -> ScholarshipSlot dict
        self.recruiting_contacts = {}       # id -> RecruitingContact dict
        self.nil_deals = {}                 # id -> NILDeal dict
        self.transfer_portal_entries = {}   # id -> TransferPortalEntry dict
        self.compliance_violations = {}     # id -> ComplianceViolation dict
        # Tracking: violation -> athlete it suspended, and list of deal ids it suspended
        self.violation_athlete_suspensions = {}  # violation_id -> {athlete_id, suspended_deal_ids:[...], prev_amateur_status, prev_status}
        # Substantiated timestamp for appeal-window checks and auto-expire
        self.substantiated_at = {}          # violation_id -> datetime
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


STORE = Store()


def lock():
    return _LOCK


def gen_id() -> str:
    return str(uuid.uuid4())


def gen_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]
