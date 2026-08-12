"""Cross-entity lookup helpers."""

from db import store
from errors import fail


def get_or_404(collection, rid, label=None):
    rec = store[collection].get(rid)
    if rec is None:
        fail("ERR_NOT_FOUND", f"{label or collection[:-1].capitalize()} {rid} does not exist")
    return rec


def employer_exists(rid):
    return rid in store["employers"]


def agreement_of_cohort(cohort):
    return store["agreements"].get(cohort["agreement_id"])


def cohort_of_session(session):
    return store["cohorts"].get(session["cohort_id"])


def cohort_of_participant(participant):
    return store["cohorts"].get(participant["cohort_id"])


def cohort_of_invoice(invoice):
    return store["cohorts"].get(invoice["cohort_id"])


def cohort_of_application(application):
    return store["cohorts"].get(application["cohort_id"])


def agreement_of_invoice(invoice):
    return store["agreements"].get(invoice["agreement_id"])


def employer_id_of_agreement(agreement):
    return agreement["employer_id"] if agreement else None


def employer_id_of_cohort(cohort):
    agr = agreement_of_cohort(cohort)
    return agr["employer_id"] if agr else None


def employer_id_of_session(session):
    cohort = cohort_of_session(session)
    return employer_id_of_cohort(cohort) if cohort else None


def employer_id_of_participant(participant):
    cohort = cohort_of_participant(participant)
    return employer_id_of_cohort(cohort) if cohort else None


def employer_id_of_invoice(invoice):
    agr = agreement_of_invoice(invoice)
    return agr["employer_id"] if agr else None


def employer_id_of_application(application):
    cohort = cohort_of_application(application)
    return employer_id_of_cohort(cohort) if cohort else None


def employer_id_of_report(report):
    agr = store["agreements"].get(report["agreement_id"])
    return agr["employer_id"] if agr else None


def cohorts_of_agreement(agreement_id):
    return [c for c in store["cohorts"].values() if c["agreement_id"] == agreement_id]


def sessions_of_cohort(cohort_id):
    return [s for s in store["sessions"].values() if s["cohort_id"] == cohort_id]


def participants_of_cohort(cohort_id):
    return [p for p in store["participants"].values() if p["cohort_id"] == cohort_id]


def assignments_of_session(session_id):
    return [a for a in store["assignments"].values() if a["session_id"] == session_id]


def applications_of_cohort(cohort_id):
    return [a for a in store["applications"].values() if a["cohort_id"] == cohort_id]


def invoices_of_cohort(cohort_id):
    return [i for i in store["invoices"].values() if i["cohort_id"] == cohort_id]


def reports_of_agreement(agreement_id):
    return [r for r in store["reports"].values() if r["agreement_id"] == agreement_id]


def assessments_of_employer(employer_id):
    return [a for a in store["assessments"].values() if a["employer_id"] == employer_id]


def agreements_of_employer(employer_id):
    return [a for a in store["agreements"].values() if a["employer_id"] == employer_id]
