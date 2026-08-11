"""Business logic: calculations (SCAFFOLD §1.3), serializers, cascade helpers."""

from datetime import date, datetime, timedelta

from db import create_entity, now_iso, store, strip_internal, touch
from errors import err_validation

# Pinned source-type order for largest-remainder ties and transfer row copies.
SOURCE_ORDER = ["AFTER_TAX", "EMPLOYER_PRETAX", "PRE_TAX", "ROTH"]
SOURCE_TYPES = set(SOURCE_ORDER)

PLAN_TYPES = {"PLAN_401K", "PLAN_403B", "PLAN_457B", "IRA"}
EMPLOYMENT_STATUSES = {"ACTIVE", "SEPARATED", "RETIRED", "DISABLED"}
MARITAL_STATUSES = {"SINGLE", "MARRIED", "WIDOWED", "DIVORCED"}
CASE_TYPES = {
    "DIRECT_ROLLOVER_OUT",
    "INDIRECT_ROLLOVER_OUT",
    "PLAN_TRANSFER",
    "IN_PLAN_ROTH_CONVERSION",
    "ROLLOVER_IN",
}
DOC_TYPES = {
    "SPOUSAL_CONSENT",
    "SEPARATION_VERIFICATION",
    "DISABILITY_PROOF",
    "IDENTITY_PROOF",
    "RECEIVING_PLAN_ACCEPTANCE",
    "SOURCE_PLAN_STATEMENT",
}
# Deterministic required-document creation order (PRD §3.4).
DOC_RULE_ORDER = [
    "SPOUSAL_CONSENT",
    "SEPARATION_VERIFICATION",
    "DISABILITY_PROOF",
    "IDENTITY_PROOF",
    "RECEIVING_PLAN_ACCEPTANCE",
    "SOURCE_PLAN_STATEMENT",
]
VERIF_DIRECTIONS = {"OUTBOUND", "INBOUND"}
VERIF_METHODS = {"PLAN_LETTER", "IRS_FORM_LOOKUP", "THIRD_PARTY_REGISTRY"}
DISB_METHODS = {"CHECK", "ACH", "WIRE", "INTERNAL_BOOK_ENTRY"}

AGE_THRESHOLD_MONTHS = 714  # 59.5 years exactly
WITHHOLDING_NUM = 20  # 20% mandatory federal withholding on indirect rollovers
WINDOW_DAYS = 60

# Non-terminal case statuses that a plan freeze suspends (PRD §3.1 link 1).
SUSPENDABLE_STATUSES = {
    "DRAFT",
    "DOCS_PENDING",
    "ELIGIBILITY_REVIEW",
    "ELIGIBLE",
    "DISBURSED",
    "AWAITING_REDEPOSIT",
    "ACCEPTANCE_PENDING",
}
TERMINAL_CASE_STATUSES = {"COMPLETED", "INCOMPLETE", "DENIED", "CANCELLED"}


# ---------------------------------------------------------------- dates ----
def parse_date(s):
    """Strict YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def req_date(data, field):
    d = parse_date(data.get(field))
    if d is None:
        raise err_validation("Field %s must be an ISO date YYYY-MM-DD" % field)
    return d


def parse_iso8601(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    from datetime import timezone

    return dt.astimezone(timezone.utc)


def add_days(d, n):
    return d + timedelta(days=n)


# ------------------------------------------------------------ participants --
def age_months_on(dob, on):
    """Complete calendar months between dob and on (PRD §3.2)."""
    m = (on.year - dob.year) * 12 + (on.month - dob.month)
    if on.day < dob.day:
        m -= 1
    return m


def age_years_2dp(age_months):
    """trunc(age_months / 12, 2 decimal places)."""
    return (age_months * 100 // 12) / 100


# --------------------------------------------------------------- accounts ---
def msb_rows_of(account_id):
    rows = [r for r in store.msb.values() if r["account_id"] == account_id]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def vested_of_row(row):
    """floor(balance_cents * vested_pct / 100) per row (PRD §2.7 floor-then-sum)."""
    return (row["balance_cents"] * row["vested_pct"]) // 100


def account_total(account_id):
    return sum(r["balance_cents"] for r in msb_rows_of(account_id))


def account_vested(account_id):
    return sum(vested_of_row(r) for r in msb_rows_of(account_id))


def account_basis(account_id):
    return sum(r["basis_cents"] for r in msb_rows_of(account_id))


def maybe_close_account(acct):
    """Auto-CLOSE when total balance reaches 0 on terminal transitions (PRD §3.2)."""
    if acct is not None and acct["status"] == "ACTIVE" and account_total(acct["id"]) == 0:
        acct["status"] = "CLOSED"
        touch(acct)


def find_or_create_source_row(account_id, source_type):
    for r in msb_rows_of(account_id):
        if r["source_type"] == source_type:
            return r
    return create_entity(
        store.msb,
        {
            "account_id": account_id,
            "source_type": source_type,
            "balance_cents": 0,
            "basis_cents": 0,
            "vested_pct": 100,
        },
    )


# ------------------------------------------------------------ calculations ---
def round_half_up_div(a, b):
    """round_half_up(a / b) for non-negative integers; a half rounds away from zero."""
    if b == 0:
        return 0
    return (2 * a + b) // (2 * b)


def source_allocation(rows, gross):
    """Waterfall allocation (SCAFFOLD §1.3 source_allocation).

    rows: eligible MoneySourceBalance dicts (balance > 0, type-filtered by caller).
    Returns {row_id: {"amount": cents, "basis": cents}} for rows with amount > 0.
    """
    if gross <= 0 or not rows:
        return {}
    vested = {r["id"]: vested_of_row(r) for r in rows}
    total_vested = sum(vested.values())
    if total_vested <= 0:
        return {}
    # Exact rational shares; floor first, then largest-remainder distribution.
    floors = {}
    fracs = {}
    for r in rows:
        num = gross * vested[r["id"]]
        floors[r["id"]] = num // total_vested
        fracs[r["id"]] = num - floors[r["id"]] * total_vested  # remainder of the division
    remainder = gross - sum(floors.values())
    order = sorted(rows, key=lambda r: (-fracs[r["id"]], SOURCE_ORDER.index(r["source_type"])))
    i = 0
    while remainder > 0 and i < len(order):
        floors[order[i]["id"]] += 1
        remainder -= 1
        i += 1
    out = {}
    for r in rows:
        amt = floors[r["id"]]
        if amt <= 0:
            continue
        basis = round_half_up_div(amt * r["basis_cents"], r["balance_cents"]) if r["balance_cents"] > 0 else 0
        out[r["id"]] = {"amount": amt, "basis": basis}
    return out


def indirect_withholding(taxable_cents):
    """round_half_up(taxable * 0.20), integer cents."""
    return (taxable_cents * 2 + 5) // 10


def eligibility_event(plan, participant, on_date):
    """eligibility_determination (SCAFFOLD §1.3). Branch priority pinned top-down."""
    if plan is not None and plan["status"] == "TERMINATED":
        return "PLAN_TERMINATION"
    if participant["employment_status"] in ("SEPARATED", "RETIRED"):
        return "SEPARATION"
    if participant["employment_status"] == "DISABLED":
        return "DISABILITY"
    dob = parse_date(participant["date_of_birth"])
    if dob is not None and age_months_on(dob, on_date) >= AGE_THRESHOLD_MONTHS:
        return "AGE_59_HALF"
    return "NONE"


# ------------------------------------------------------------------ cases ---
def case_owner_participant_id(case):
    """Owning participant: source account's owner, else receiving account's (ROLLOVER_IN)."""
    if case.get("source_account_id"):
        acct = store.accounts.get(case["source_account_id"])
        return acct["participant_id"] if acct else None
    if case.get("receiving_account_id"):
        acct = store.accounts.get(case["receiving_account_id"])
        return acct["participant_id"] if acct else None
    return None


def case_source_account(case):
    return store.accounts.get(case["source_account_id"]) if case.get("source_account_id") else None


def case_receiving_account(case):
    return store.accounts.get(case["receiving_account_id"]) if case.get("receiving_account_id") else None


def credited_total(case_id):
    """Sum of CREDITED redeposit amounts only (SCAFFOLD §1.3 redeposit_completion)."""
    return sum(
        r["amount_cents"]
        for r in store.redeposits.values()
        if r.get("rollover_case_id") == case_id and r["status"] == "CREDITED"
    )


def non_cancelled_disbursement(case_id):
    for d in store.disbursements.values():
        if d["rollover_case_id"] == case_id and d["status"] != "CANCELLED":
            return d
    return None


def docs_of_case(case_id):
    rows = [d for d in store.documents.values() if d["rollover_case_id"] == case_id]
    rows.sort(key=lambda d: d["_seq"])
    return rows


def has_verified_verification(case_id, direction):
    return any(
        v["rollover_case_id"] == case_id and v["direction"] == direction and v["status"] == "VERIFIED"
        for v in store.verifications.values()
    )


def active_loans_of_account(account_id):
    return [l for l in store.loans.values() if l["account_id"] == account_id and l["status"] == "ACTIVE"]


def update_5498(participant_id, account_id, tax_year, contribution_cents):
    """Create or update the single DRAFT 5498 per (participant_id, tax_year)."""
    draft = None
    for f in store.taxforms.values():
        if (
            f["form_type"] == "FORM_5498"
            and f["participant_id"] == participant_id
            and f["tax_year"] == tax_year
            and f["status"] == "DRAFT"
        ):
            draft = f
            break
    fmv = account_total(account_id)
    if draft is None:
        create_entity(
            store.taxforms,
            {
                "form_type": "FORM_5498",
                "tax_year": tax_year,
                "participant_id": participant_id,
                "rollover_case_id": None,
                "loan_id": None,
                "gross_distribution_cents": None,
                "taxable_amount_cents": None,
                "federal_withholding_cents": None,
                "distribution_code": None,
                "rollover_contribution_cents": contribution_cents,
                "fair_market_value_cents": fmv,
                "status": "DRAFT",
                "supersedes_id": None,
                "revision": 0,
            },
        )
    else:
        draft["rollover_contribution_cents"] = (draft["rollover_contribution_cents"] or 0) + contribution_cents
        draft["fair_market_value_cents"] = fmv
        touch(draft)


def draft_1099(case_id, loan_id, participant_id, tax_year, gross, withholding, taxable, code):
    return create_entity(
        store.taxforms,
        {
            "form_type": "FORM_1099_R",
            "tax_year": tax_year,
            "participant_id": participant_id,
            "rollover_case_id": case_id,
            "loan_id": loan_id,
            "gross_distribution_cents": gross,
            "taxable_amount_cents": taxable,
            "federal_withholding_cents": withholding,
            "distribution_code": code,
            "rollover_contribution_cents": None,
            "fair_market_value_cents": None,
            "status": "DRAFT",
            "supersedes_id": None,
            "revision": 0,
        },
    )


def supersede_form(old, new_amounts):
    """Correction chain (PRD §3.10): old -> SUPERSEDED; new ISSUED at revision+1."""
    old["status"] = "SUPERSEDED"
    touch(old)  # superseded row's version increments by 1
    fields = {
        "form_type": old["form_type"],
        "tax_year": old["tax_year"],
        "participant_id": old["participant_id"],
        "rollover_case_id": old.get("rollover_case_id"),
        "loan_id": old.get("loan_id"),
        "gross_distribution_cents": old.get("gross_distribution_cents"),
        "taxable_amount_cents": old.get("taxable_amount_cents"),
        "federal_withholding_cents": old.get("federal_withholding_cents"),
        "distribution_code": old.get("distribution_code"),
        "rollover_contribution_cents": old.get("rollover_contribution_cents"),
        "fair_market_value_cents": old.get("fair_market_value_cents"),
        "status": "ISSUED",
        "supersedes_id": old["id"],
        "revision": old["revision"] + 1,
    }
    for k, v in new_amounts.items():
        if v is not None:
            fields[k] = v
    return create_entity(store.taxforms, fields)


def recompute_indirect_1099_corrected(case):
    """Corrected variant: taxable = taxable_cents - min(credited_total, taxable_cents).

    DRAFT forms are rewritten in place; ISSUED forms get an auto-correction revision.
    """
    credited = credited_total(case["id"])
    taxable_cents = case.get("taxable_cents") or 0
    corrected = taxable_cents - min(credited, taxable_cents)
    for f in list(store.taxforms.values()):
        if (
            f["form_type"] == "FORM_1099_R"
            and f.get("rollover_case_id") == case["id"]
            and f["status"] in ("DRAFT", "ISSUED")
        ):
            if f["status"] == "DRAFT":
                f["taxable_amount_cents"] = corrected
                touch(f)
            else:
                supersede_form(f, {"taxable_amount_cents": corrected})


def skip_scheduled_notices(case_id):
    count = 0
    for n in store.notices.values():
        if n["rollover_case_id"] == case_id and n["status"] == "SCHEDULED":
            n["status"] = "SKIPPED"
            touch(n)
            count += 1
    return count


def complete_indirect_case(case):
    """AWAITING_REDEPOSIT -> COMPLETED with notice + 1099-R cascades (PRD §3.9)."""
    case["status"] = "COMPLETED"
    touch(case)
    skip_scheduled_notices(case["id"])
    recompute_indirect_1099_corrected(case)
    maybe_close_account(case_source_account(case))


def restore_disbursement(disb):
    """cancel_disbursement invariant: source balances return exactly to pre-issue
    values — every row credited back its issue-time allocation and basis share,
    plus any forfeited unvested employer remainder (PRD §3.7, SCAFFOLD §1.2)."""
    case = store.cases.get(disb["rollover_case_id"])
    if case is None:
        return
    acct = case_source_account(case)
    if acct is None:
        return
    alloc = disb.get("_alloc") or {}
    forfeit = disb.get("_forfeit") or {}
    for row in msb_rows_of(acct["id"]):
        a = alloc.get(row["id"])
        if a:
            row["balance_cents"] += a["amount"]
            row["basis_cents"] += a["basis"]
            touch(row)
        f = forfeit.get(row["id"])
        if f:
            row["balance_cents"] += f["amount"]
            row["basis_cents"] += f["basis"]
            touch(row)
    if forfeit:
        case["forfeiture_cents"] = 0
        touch(case)
    touch(acct)


# ------------------------------------------------------------- serializers ---
def serialize_plan(p):
    return strip_internal(p)


def serialize_freeze_window(w):
    return strip_internal(w)


def serialize_participant(p):
    out = strip_internal(p)
    dob = parse_date(p["date_of_birth"])
    if dob is not None:
        months = age_months_on(dob, clock_date_safe())
    else:
        months = 0
    out["age_months"] = months
    out["current_age_years"] = age_years_2dp(months)
    return out


def clock_date_safe():
    from db import clock_date

    return clock_date()


def serialize_account(a):
    out = strip_internal(a)
    out["total_balance_cents"] = account_total(a["id"])
    out["vested_balance_cents"] = account_vested(a["id"])
    out["basis_cents"] = account_basis(a["id"])
    return out


def serialize_msb(r):
    return strip_internal(r)


def serialize_loan(l):
    return strip_internal(l)


def serialize_case(c):
    out = strip_internal(c)
    out["credited_total_cents"] = credited_total(c["id"])
    return out


def serialize_document(d):
    return strip_internal(d)


def serialize_verification(v):
    return strip_internal(v)


def serialize_disbursement(d):
    return strip_internal(d)


def serialize_redeposit(r):
    return strip_internal(r)


def serialize_notice(n):
    return strip_internal(n)


def serialize_taxform(f):
    return strip_internal(f)
