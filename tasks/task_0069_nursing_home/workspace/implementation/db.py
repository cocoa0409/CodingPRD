"""In-memory data store with threading lock."""
import uuid
from threading import RLock


# A global lock used to serialize all mutations (gives us deterministic
# first-writer-wins for races). The Flask dev server is single-threaded by
# default with threaded=False in app.py, but use a lock defensively.
LOCK = RLock()


def new_id():
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        self.elders = {}                 # id -> Elder dict
        self.rooms = {}                  # id -> Room dict
        self.beds = {}                   # id -> Bed dict
        self.waitlist = {}               # id -> WaitlistEntry dict
        self.waitlist_offered_at = {}    # id -> datetime when entry moved to OFFERED
        self.care_assessments = {}       # id -> CareAssessment dict
        self.care_plans = {}             # id -> CarePlan dict
        self.care_plans_superseded_at = {}  # id -> datetime when plan became SUPERSEDED
        self.task_executions = {}        # id -> CareTaskExecution dict
        self.prescriptions = {}          # id -> Prescription dict
        self.prescription_schedules = {} # prescription_id -> [iso datetime str slots]
        self.administrations = {}        # id -> MedicationAdministration dict
        self.medication_errors = {}      # id -> MedicationErrorReport dict
        self.visit_reservations = {}     # id -> VisitReservation dict
        self.bills = {}                  # id -> Bill dict
        self.bill_external_payment_refs = {}  # external_payment_ref -> bill_id (for duplicate detection)
        self.audit_logs = {}             # id -> AuditLog dict
        self.external_events = {}        # id -> ExternalEvent dict
        self.external_event_index = {}   # (source, idempotency_key) -> event_id
        self.epidemic_config = None      # singleton dict
        # Pending prescription suspensions per elder (for on_leave/return cascade) we just iterate.


DB_INSTANCE = DB()


def get_db():
    return DB_INSTANCE


def reset_db():
    """Useful in tests / between runs."""
    global DB_INSTANCE
    DB_INSTANCE = DB()
