"""Reusable lookup helpers across services and routes."""
import db


def effective_w4(employee_id, tax_year):
    """The currently-effective FILED W4Form for (employee_id, tax_year).

    Selection rule (PRD §3.3 / §3.4): most recent filed_at; tie-break created_at ASC.
    Returns None when no FILED W-4 exists for that pair.
    """
    candidates = [
        w for w in db.w4_forms.values()
        if w["employee_id"] == employee_id
        and w["tax_year"] == tax_year
        and w["status"] == "FILED"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda w: (w["filed_at"], w["created_at"]),
        reverse=False,
    )
    # Most recent filed_at; tie-break created_at ASC.
    # We want the LATEST filed_at — invert by sorting reverse on filed_at,
    # but ties resolved by EARLIEST created_at. Composite sort:
    candidates.sort(key=lambda w: w["created_at"])  # secondary ASC
    candidates.sort(key=lambda w: w["filed_at"], reverse=True)  # primary DESC stable
    return candidates[0]


def find_tax_rate_table(jurisdiction, tax_year, filing_status):
    """Find a TaxRateTable row. STATE:* and LOCAL:* always use SINGLE per scaffold."""
    for t in db.tax_rate_tables.values():
        if (
            t["jurisdiction"] == jurisdiction
            and t["tax_year"] == tax_year
            and t["filing_status"] == filing_status
        ):
            return t
    return None


def state_jurisdiction(work_state_code):
    return f"STATE:{work_state_code}"


def local_jurisdiction(locality_code):
    if not locality_code or locality_code == "NONE":
        return None
    return f"LOCAL:{locality_code}"


def period_month_of(pay_date_iso):
    """Year-month bucket key, first 7 chars of an ISO 8601 datetime string."""
    return pay_date_iso[:7]


def pay_date_year(pay_date_iso):
    return int(pay_date_iso[:4])


def employee_has_active_child_support(employee_id):
    """True if at least one ACTIVE CHILD_SUPPORT order exists for the employee."""
    for g in db.garnishment_orders.values():
        if (
            g["employee_id"] == employee_id
            and g["status"] == "ACTIVE"
            and g["order_type"] == "CHILD_SUPPORT"
        ):
            return True
    return False


def most_recent_paid_paycheck_for(employee_id):
    """Most recent PAID Paycheck for the employee, ordered by created_at DESC; None if none."""
    candidates = [
        p for p in db.paychecks.values()
        if p["employee_id"] == employee_id and p["status"] == "PAID"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p["created_at"], reverse=True)
    return candidates[0]


def remittance_jurisdictions_for(paycheck):
    """Yields (jurisdiction, tax_type, bucket_field) tuples for a paycheck's withholdings.

    FED_INCOME -> federal_withheld_cents
    FICA_EMPLOYEE -> ss + base medicare + additional medicare (combined)
    STATE_INCOME -> state_withheld_cents
    LOCAL_INCOME -> local_withheld_cents (only if locality)
    """
    employee = db.employees[paycheck["employee_id"]]
    work_state = employee["work_state_code"]
    locality = employee.get("locality_code") or "NONE"

    yield ("FEDERAL", "FED_INCOME", paycheck["fed_withheld_cents"])
    yield ("FEDERAL", "FICA_EMPLOYEE",
           paycheck["ss_withheld_cents"]
           + paycheck["medicare_withheld_cents"]
           + paycheck["addl_medicare_cents"])
    yield (state_jurisdiction(work_state), "STATE_INCOME", paycheck["state_withheld_cents"])
    if locality != "NONE":
        yield (local_jurisdiction(locality), "LOCAL_INCOME", paycheck["local_withheld_cents"])
