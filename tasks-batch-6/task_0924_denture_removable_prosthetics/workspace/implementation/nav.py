"""Relationship navigation helpers over the in-memory store."""
from store import db, sorted_rows


# --- direct parent lookups ---------------------------------------------------
def case_of_arch(arch):
    return db.cases.get(arch["case_id"])


def arch_of(row):
    return db.arches.get(row.get("case_arch_id"))


def case_of_prosthesis(prosthesis):
    arch = db.arches.get(prosthesis["case_arch_id"])
    return db.cases.get(arch["case_id"]) if arch else None


def patient_of_case(case):
    return db.patients.get(case["patient_id"]) if case else None


def patient_of_arch(arch):
    return patient_of_case(case_of_arch(arch)) if arch else None


def patient_of_prosthesis(prosthesis):
    return patient_of_case(case_of_prosthesis(prosthesis)) if prosthesis else None


# --- child collections -------------------------------------------------------
def arches_of_case(case):
    return sorted_rows(
        [a for a in db.arches.values() if a["case_id"] == case["id"]]
    )


def non_abandoned_arches(case):
    return [a for a in arches_of_case(case) if a["arch_status"] != "ARCH_ABANDONED"]


def impressions_of_arch(arch):
    return sorted_rows(
        [r for r in db.impressions.values() if r["case_arch_id"] == arch["id"]]
    )


def tryins_of_arch(arch):
    return sorted_rows(
        [r for r in db.tryins.values() if r["case_arch_id"] == arch["id"]]
    )


def labcases_of_arch(arch):
    return sorted_rows(
        [r for r in db.labcases.values() if r["case_arch_id"] == arch["id"]]
    )


def labcases_of_case(case):
    ids = {a["id"] for a in arches_of_case(case)}
    return sorted_rows([r for r in db.labcases.values() if r["case_arch_id"] in ids])


def prostheses_of_arch(arch):
    return sorted_rows(
        [r for r in db.prostheses.values() if r["case_arch_id"] == arch["id"]]
    )


def latest_prosthesis_of_arch(arch):
    rows = prostheses_of_arch(arch)
    return rows[-1] if rows else None


def prostheses_of_case(case):
    ids = {a["id"] for a in arches_of_case(case)}
    return sorted_rows([r for r in db.prostheses.values() if r["case_arch_id"] in ids])


def prostheses_of_patient(patient_id):
    out = []
    for p in db.prostheses.values():
        arch = db.arches.get(p["case_arch_id"])
        if not arch:
            continue
        case = db.cases.get(arch["case_id"])
        if case and case["patient_id"] == patient_id:
            out.append(p)
    return sorted_rows(out)


def services_of_prosthesis(prosthesis):
    return sorted_rows(
        [r for r in db.services.values() if r["prosthesis_id"] == prosthesis["id"]]
    )


def services_of_case(case):
    ids = {p["id"] for p in prostheses_of_case(case)}
    return sorted_rows([r for r in db.services.values() if r["prosthesis_id"] in ids])


def warranty_claims_of_prosthesis(prosthesis):
    return sorted_rows(
        [
            r
            for r in db.warranty_claims.values()
            if r["prosthesis_id"] == prosthesis["id"]
        ]
    )


def warranty_claims_of_case(case):
    ids = {p["id"] for p in prostheses_of_case(case)}
    return sorted_rows(
        [r for r in db.warranty_claims.values() if r["prosthesis_id"] in ids]
    )


def remake_requests_of_arch(arch):
    return sorted_rows(
        [r for r in db.remake_requests.values() if r["case_arch_id"] == arch["id"]]
    )


def predeterminations_of_case(case):
    return sorted_rows(
        [r for r in db.predeterminations.values() if r["case_id"] == case["id"]]
    )


def claims_of_case(case):
    return sorted_rows([r for r in db.claims.values() if r["case_id"] == case["id"]])


def plans_of_case(case):
    return sorted_rows([r for r in db.plans.values() if r["case_id"] == case["id"]])


def plans_of_patient(patient_id):
    return sorted_rows(
        [r for r in db.plans.values() if r["patient_id"] == patient_id]
    )


def installments_of_plan(plan):
    rows = [r for r in db.installments.values() if r["payment_plan_id"] == plan["id"]]
    return sorted(rows, key=lambda r: r["sequence_number"])


def plan_of_installment(installment):
    return db.plans.get(installment["payment_plan_id"])


def coverages_of_patient(patient_id):
    return sorted_rows(
        [r for r in db.coverages.values() if r["patient_id"] == patient_id]
    )


def coverage_at_rank(patient_id, rank):
    rows = [
        r
        for r in db.coverages.values()
        if r["patient_id"] == patient_id and r["rank"] == rank
    ]
    return rows[0] if len(rows) == 1 else None
