"""Rung 4 existence resolution plus the derived read-model helpers."""

from decimal import Decimal

import calc
from errors import ApiError
from store import ZERO2, by_created, clock, db, latest, parse_iso

NOT_FOUND = {
    "utility_programs": "ERR_UTILITY_PROGRAM_NOT_FOUND",
    "technicians": "ERR_TECHNICIAN_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
    "duct_systems": "ERR_DUCT_SYSTEM_NOT_FOUND",
    "leakage_tests": "ERR_LEAKAGE_TEST_NOT_FOUND",
    "seal_jobs": "ERR_SEAL_JOB_NOT_FOUND",
    "verification_reports": "ERR_VERIFICATION_REPORT_NOT_FOUND",
    "rebate_claims": "ERR_REBATE_CLAIM_NOT_FOUND",
    "comfort_complaints": "ERR_COMFORT_COMPLAINT_NOT_FOUND",
}


def get_or_404(collection, row_id):
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[collection], "%s does not exist." % row_id)
    return row


def program_or_404(row_id):
    return get_or_404("utility_programs", row_id)


def technician_or_404(row_id):
    return get_or_404("technicians", row_id)


def project_or_404(row_id):
    return get_or_404("projects", row_id)


def duct_system_or_404(row_id):
    return get_or_404("duct_systems", row_id)


def leakage_test_or_404(row_id):
    return get_or_404("leakage_tests", row_id)


def seal_job_or_404(row_id):
    return get_or_404("seal_jobs", row_id)


def report_or_404(row_id):
    return get_or_404("verification_reports", row_id)


def claim_or_404(row_id):
    return get_or_404("rebate_claims", row_id)


def complaint_or_404(row_id):
    return get_or_404("comfort_complaints", row_id)


# --------------------------------------------------------------------------
# collection navigation
# --------------------------------------------------------------------------
def duct_systems_of_project(project_id):
    return by_created([d for d in db.rows("duct_systems") if d["project_id"] == project_id])


def leakage_tests_of_system(duct_system_id):
    return by_created([t for t in db.rows("leakage_tests")
                       if t["duct_system_id"] == duct_system_id])


def seal_jobs_of_system(duct_system_id):
    return by_created([j for j in db.rows("seal_jobs")
                       if j["duct_system_id"] == duct_system_id])


def seal_jobs_of_project(project_id):
    ids = set(d["id"] for d in duct_systems_of_project(project_id))
    return by_created([j for j in db.rows("seal_jobs") if j["duct_system_id"] in ids])


def samples_of_job(seal_job_id):
    rows = [s for s in db.rows("leakage_samples") if s["seal_job_id"] == seal_job_id]
    return sorted(rows, key=lambda s: (s["sample_seq"], s["_seq"]))


def combustion_tests_of_project(project_id):
    return by_created([c for c in db.rows("combustion_tests") if c["project_id"] == project_id])


def reports_of_job(seal_job_id):
    return by_created([r for r in db.rows("verification_reports")
                       if r["seal_job_id"] == seal_job_id])


def claims_of_report(report_id):
    return by_created([c for c in db.rows("rebate_claims")
                       if c["verification_report_id"] == report_id])


def claims_of_program(program_id):
    return by_created([c for c in db.rows("rebate_claims")
                       if c["utility_program_id"] == program_id])


def readings_of_complaint(complaint_id):
    rows = [r for r in db.rows("airflow_readings") if r["comfort_complaint_id"] == complaint_id]
    return sorted(rows, key=lambda r: (r["reading_seq"], r["_seq"]))


def complaints_of_project(project_id):
    return by_created([c for c in db.rows("comfort_complaints")
                       if c["project_id"] == project_id])


def retest_children(seal_job_id):
    return [j for j in db.rows("seal_jobs") if j.get("retest_of_job_id") == seal_job_id]


def project_of_system(duct_system):
    return db.projects.get(duct_system["project_id"])


def project_of_job(seal_job):
    system = db.duct_systems.get(seal_job["duct_system_id"])
    if system is None:
        return None
    return project_of_system(system)


def program_of_project(project):
    pid = project.get("utility_program_id")
    if not pid:
        return None
    return db.utility_programs.get(pid)


# --------------------------------------------------------------------------
# derived values
# --------------------------------------------------------------------------
def program_ledger(program):
    """committed / paid / remaining, derived from the program's claims
    (PRD section 2.11)."""
    committed = 0
    paid = 0
    for claim in claims_of_program(program["id"]):
        payable = int(claim.get("payable_cents") or 0)
        if claim["status"] in ("SUBMITTED", "APPROVED"):
            committed += payable
        elif claim["status"] == "PAID":
            paid += payable
    remaining = int(program["annual_budget_cents"]) - committed - paid
    return committed, paid, remaining


def remaining_budget(program):
    return program_ledger(program)[2]


def open_seal_job_count(technician_id):
    return len([j for j in db.rows("seal_jobs")
                if j["technician_id"] == technician_id
                and j["status"] in calc.SEAL_JOB_OPEN])


def active_seal_job_id(duct_system_id):
    """The newest run on the system whose status is SCHEDULED, MASKING,
    INJECTING or PAUSED (SCAFFOLD section 1.1 computed pointer)."""
    best = None
    for job in db.rows("seal_jobs"):
        if job["duct_system_id"] != duct_system_id:
            continue
        if job["status"] not in calc.SEAL_JOB_OPEN:
            continue
        if best is None or job["_seq"] > best["_seq"]:
            best = job
    return best["id"] if best else None


def duct_system_counts(project_id):
    systems = duct_systems_of_project(project_id)
    total = len(systems)
    eligible = len([s for s in systems if s["eligibility_status"] == "ELIGIBLE"])
    return total, eligible


def latest_accepted_pre_test(duct_system_id):
    rows = [t for t in leakage_tests_of_system(duct_system_id)
            if t["phase"] == "PRE" and t["status"] == "ACCEPTED"]
    return latest(rows)


def latest_accepted_post_test(duct_system_id):
    rows = [t for t in leakage_tests_of_system(duct_system_id)
            if t["phase"] == "POST" and t["status"] == "ACCEPTED"]
    return latest(rows)


def warranty_status(seal_job):
    """Derived on every read, in the pinned precedence of PRD section 3.9."""
    if seal_job.get("warranty_registered_at") is None:
        return "NOT_REGISTERED"
    if seal_job.get("warranty_suspended"):
        return "SUSPENDED"
    due = seal_job.get("retest_due_at")
    if due is not None and clock() > due:
        for child in retest_children(seal_job["id"]):
            if child["status"] in ("VERIFIED", "RETEST_CLOSED"):
                return "REGISTERED"
        return "LAPSED"
    return "REGISTERED"


def governing_readings(complaint_id):
    """The greatest reading_seq per distinct room_label."""
    best = {}
    for reading in readings_of_complaint(complaint_id):
        room = reading["room_label"]
        current = best.get(room)
        if current is None or reading["reading_seq"] > current["reading_seq"]:
            best[room] = reading
    return best


def balanced_room_count(complaint_id):
    governing = governing_readings(complaint_id)
    return len([r for r in governing.values() if r["within_tolerance"]])


def distinct_room_count(complaint_id):
    return len(governing_readings(complaint_id))


def combustion_coverage(project, phase):
    """Returns (ok_count, has_fail) over the project's combustion tests of ``phase``."""
    ok_count = 0
    has_fail = False
    for test in combustion_tests_of_project(project["id"]):
        if test["phase"] != phase:
            continue
        if test["verdict"] == "FAIL":
            has_fail = True
        elif test["verdict"] in ("PASS", "MARGINAL"):
            ok_count += 1
    return ok_count, has_fail
