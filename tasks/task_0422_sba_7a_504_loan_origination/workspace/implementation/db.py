"""In-memory data store.

Per PRD §2.4 every resource carries system-managed fields: `id` (server-minted
UUID, no type prefix), `created_at`, `updated_at` (ISO 8601 UTC, three fractional
digits), and `version` (integer beginning at its initial value at creation,
incrementing by one on every mutation).

NOTHING is seeded here. The store starts empty on every boot; tests build all
state through the declared API surface.
"""
import datetime
import threading
import uuid

# A global lock guards every mutation so cascades stay atomic and consistent
# under the test harness's request flow.
LOCK = threading.RLock()

# One dict per entity type, keyed by id.
lenders = {}
borrowers = {}
applications = {}
proceeds = {}
collateral = {}
form_packages = {}
credit_memos = {}
disbursements = {}
guaranty_sales = {}
servicing_reports = {}
liquidations = {}
guaranty_purchases = {}

ALL = {
    "Lender": lenders,
    "Borrower": borrowers,
    "Application": applications,
    "ProceedsLineItem": proceeds,
    "CollateralItem": collateral,
    "FormPackage": form_packages,
    "CreditMemo": credit_memos,
    "Disbursement": disbursements,
    "GuarantySale": guaranty_sales,
    "ServicingReport": servicing_reports,
    "LiquidationEvent": liquidations,
    "GuarantyPurchase": guaranty_purchases,
}


def new_id():
    # UUID with no type prefix.
    return str(uuid.uuid4())


def now_ts():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# A monotonically increasing sequence so created_at ordering is stable even when
# two creates land in the same millisecond. Used only as a tiebreaker for the
# default created_at-ascending sort (PRD §2.3).
_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def init_record(fields):
    """Stamp the four system-managed common fields onto a new record."""
    ts = now_ts()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = _next_seq()
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version (PRD §2.4)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1
