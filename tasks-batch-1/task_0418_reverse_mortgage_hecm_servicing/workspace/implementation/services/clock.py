"""Simulated clock + occupancy-delinquency sweep (§3.1, §3.6)."""
from datetime import date

import db


def clock_date(lender):
    """Date portion (datetime.date) of a lender's clock_utc (ISO 8601)."""
    return iso_to_date(lender["clock_utc"])


def iso_to_date(iso):
    # iso like 2025-05-24T10:30:00.123Z -> 2025-05-24
    datepart = iso.split("T")[0]
    y, m, d = datepart.split("-")
    return date(int(y), int(m), int(d))


def parse_ymd(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def run_occupancy_sweep(lender):
    """Any PENDING OccupancyCertification on a loan in this lender's portfolio
    whose due_date < new clock date -> DELINQUENT; cascade CURRENT ->
    DELINQUENT_OCCUPANCY on the loan's servicing axis.

    Per PRD §3.1, the clock-setting operation "does not change resource versions
    other than the lender's own", so the sweep flips status WITHOUT bumping
    version / updated_at on the certification or the loan."""
    cur = clock_date(lender)
    lender_loan_ids = {lid for lid, ln in db.loans.items() if ln["lender_id"] == lender["id"]}
    for cert in db.occupancy_certifications.values():
        if cert["loan_id"] not in lender_loan_ids:
            continue
        if cert["status"] != "PENDING":
            continue
        if parse_ymd(cert["due_date"]) < cur:
            cert["status"] = "DELINQUENT"
            loan = db.loans.get(cert["loan_id"])
            if loan is not None and loan["servicing_status"] == "CURRENT":
                loan["servicing_status"] = "DELINQUENT_OCCUPANCY"
