"""In-memory data store. Starts empty on every boot. No seeding."""
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """ISO 8601 UTC with millisecond precision, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    """Pure in-memory dict store keyed by id."""

    def __init__(self):
        self.borrowers = {}              # id -> Borrower dict
        self.loans = {}                  # id -> Loan dict
        self.repayment_plans = {}        # id -> RepaymentPlan dict
        self.income_certifications = {}  # id -> IncomeCertification dict
        self.qualifying_employments = {} # id -> QualifyingEmployment dict
        self.payments = {}               # id -> Payment dict
        self.status_changes = {}         # id -> StatusChange dict
        self.discharge_applications = {} # id -> DischargeApplication dict
        # Server logical clock, ISO 8601 UTC string. Defaults to real wall clock.
        self.current_utc = utc_now_iso()


# Module-level singleton (per process). Re-created on every process boot.
store = Store()
