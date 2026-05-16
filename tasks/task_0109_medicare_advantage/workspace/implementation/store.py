"""In-memory data store and clock."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.beneficiaries: dict = {}
        self.plans: dict = {}
        self.enrollment_periods: dict = {}
        self.enrollments: dict = {}
        self.late_enrollment_penalties: dict = {}
        self.medigap_policies: dict = {}
        self.drug_claims: dict = {}
        self.drug_phase_ledgers: dict = {}
        self.star_rating_snapshots: dict = {}
        # Index plan_code uniqueness
        self.plan_codes: set = set()
        # Index medicare_id uniqueness
        self.medicare_ids: set = set()
        # Logical clock. Default to real now() so that pre-clock-advance behavior is sane.
        self._clock: datetime = datetime.now(timezone.utc)

    @property
    def clock(self) -> datetime:
        return self._clock

    def set_clock(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._clock = dt.astimezone(timezone.utc)

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def now_iso(self) -> str:
        n = self._clock
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


store = Store()
