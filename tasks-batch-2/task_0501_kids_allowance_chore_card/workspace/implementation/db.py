"""In-memory data store. All state lives in module-level dicts keyed by id and
is wiped on every fresh process boot. No seeding at startup."""
import uuid

from clock import Clock, iso, parse_date

# One dict per entity type, keyed by id.
families = {}
child_accounts = {}
jars = {}
chores = {}
chore_completions = {}
debit_cards = {}
card_controls = {}
transactions = {}
allowance_schedules = {}
allowance_runs = {}
interest_match_configs = {}
interest_accruals = {}
investment_accounts = {}
investment_orders = {}
spend_alerts = {}

clock = Clock()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return iso(clock.current())


def base_fields(common=True):
    """System-managed common fields (PRD §2.4). SpendAlert passes common=False:
    it carries only id and created_at, no updated_at and no version."""
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 0
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1


def compute_is_teen(child):
    """True once (clock_now - birthdate) >= 13 years (PRD §3.2). Computed by
    calendar comparison so a child born exactly 13 years before clock_now reads
    True (corner: born 2013-06-26, clock 2026-06-26 -> True)."""
    bd = parse_date(child.get("birthdate"))
    if bd is None:
        return False
    now = clock.current()
    years = now.year - bd.year
    if (now.month, now.day) < (bd.month, bd.day):
        years -= 1
    return years >= 13
