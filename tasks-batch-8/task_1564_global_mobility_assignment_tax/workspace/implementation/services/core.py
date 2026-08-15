"""Entity lifecycle helpers and cross-aggregate cascade services (PRD §2.9)."""
from db import db
from util import new_id, now_ts


def new_record(collection, fields):
    rec = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": None,  # set below so created_at == updated_at at birth
        "version": 1,
    }
    rec.update(fields)
    rec["updated_at"] = rec["created_at"]
    db[collection][rec["id"]] = rec
    return rec


def touch(rec, bump_version=True):
    rec["updated_at"] = now_ts()
    if bump_version:
        rec["version"] += 1


def assignment_of(rec):
    return db["assignments"].get(rec["assignment_id"])


def program_of_assignment(asg):
    return db["programs"].get(asg["program_id"])


def policy_of_assignment(asg):
    return db["allowance_policies"].get(asg["policy_id"])


def employee_of_assignment(asg):
    return db["employees"].get(asg["employee_id"])


def open_split_of(assignment_id):
    """The PayrollSplit for the assignment in a non-terminal state (at most one)."""
    for sp in db["payroll_splits"].values():
        if sp["assignment_id"] == assignment_id and sp["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"):
            return sp
    return None


def issued_certificate_of(assignment_id):
    for c in db["certificates_of_coverage"].values():
        if c["assignment_id"] == assignment_id and c["status"] == "ISSUED":
            return c
    return None


def current_projection_of(assignment_id):
    for p in db["cost_projections"].values():
        if p["assignment_id"] == assignment_id and p["status"] == "CURRENT":
            return p
    return None


# ---------------------------------------------------------------------------
# Ledger cascades
# ---------------------------------------------------------------------------

def create_chargeback_entry(asg, entry_type, amount_cents, source_record_id=None,
                            source_settlement_id=None):
    """Chargeback entries exist only as cascade products (PRD §3.9)."""
    return new_record("chargeback_entries", {
        "assignment_id": asg["id"],
        "business_unit": asg["host_business_unit"],
        "entry_type": entry_type,
        "source_record_id": source_record_id,
        "source_settlement_id": source_settlement_id,
        "amount_cents": amount_cents,
        "status": "ACCRUED",
    })


def rerun_overrun_posture_check(asg):
    """PRD §3.6: after every mutation of Assignment.ytd_chargeback_cents.

    Strictly-greater comparison evaluated as an exact rational, no rounding:
    OVERRUN iff ytd_chargeback_cents * 100
                > monthly_cost_cents * posted_months * threshold_pct.
    """
    proj = current_projection_of(asg["id"])
    if proj is None:
        new_posture = "NORMAL"
    else:
        posted_months = sum(
            1 for r in db["shadow_payroll_records"].values()
            if r["assignment_id"] == asg["id"] and r["status"] == "POSTED"
        )
        if posted_months == 0:
            new_posture = "NORMAL"
        else:
            program = program_of_assignment(asg)
            lhs = asg["ytd_chargeback_cents"] * 100
            rhs = (proj["monthly_cost_cents"] * posted_months
                   * program["cost_overrun_threshold_pct"])
            new_posture = "OVERRUN" if lhs > rhs else "NORMAL"
    if asg["cost_posture"] != new_posture:
        asg["cost_posture"] = new_posture
        touch(asg, bump_version=False)


def recompute_draft_record(rec):
    """Recompute a DRAFT ShadowPayrollRecord's money fields from current inputs
    (PRD §3.3: recomputed while in DRAFT whenever an underlying input changes)."""
    from services.calculations import compute_record_fields

    asg = assignment_of(rec)
    split = open_split_of(rec["assignment_id"])
    policy = policy_of_assignment(asg)
    employee = employee_of_assignment(asg)
    fields = compute_record_fields(
        total_gross_cents=rec["total_gross_cents"],
        per_diem_days=rec["per_diem_days"],
        housing_receipts_cents=rec["housing_receipts_cents"],
        home_payroll_pct=split["home_payroll_pct"],
        coc_exempt=split["coc_exempt"],
        per_diem_daily_cents=policy["per_diem_daily_cents"],
        cola_pct=policy["cola_pct"],
        housing_monthly_cap_cents=policy["housing_monthly_cap_cents"],
        family_size=employee["family_size"],
    )
    rec.update(fields)
    touch(rec)


def expire_certificate(cert):
    """CoC expiry cascade (PRD §3.5): ISSUED -> EXPIRED, flip coc_exempt off and
    recompute employer_socsec_cents on every DRAFT record of the assignment."""
    cert["status"] = "EXPIRED"
    touch(cert)
    # Cascade hop 1: the split's exemption flag flips off.
    split = open_split_of(cert["assignment_id"])
    if split is not None and split["coc_exempt"]:
        split["coc_exempt"] = False
        touch(split)
    # Cascade hop 2: DRAFT records recompute; POSTED records stay frozen.
    for rec in db["shadow_payroll_records"].values():
        if rec["assignment_id"] == cert["assignment_id"] and rec["status"] == "DRAFT":
            recompute_draft_record(rec)


def sweep_certificate_expiry():
    """Run on every logical-clock set: coverage end is inclusive, so a
    certificate expires only once the clock date is strictly after valid_until."""
    from util import CLOCK, parse_date

    today = CLOCK.today()
    for cert in list(db["certificates_of_coverage"].values()):
        if cert["status"] != "ISSUED" or not cert.get("valid_until"):
            continue
        if today > parse_date(cert["valid_until"]):
            expire_certificate(cert)
