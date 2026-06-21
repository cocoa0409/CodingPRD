"""Existence lookups — raise ERR_NOT_FOUND when missing (PRD §2.5)."""
from db import db
from errors import err


def get_client(cid):
    c = db.clients.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Client not found")
    return c


def get_linguist(lid):
    l = db.linguists.get(lid)
    if l is None:
        raise err("ERR_NOT_FOUND", "Linguist not found")
    return l


def get_rate_card(rid):
    r = db.rate_cards.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "RateCard not found")
    return r


def get_project(pid):
    p = db.projects.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    return p


def get_job(jid):
    j = db.jobs.get(jid)
    if j is None:
        raise err("ERR_NOT_FOUND", "ProjectJob not found")
    return j


def get_assignment(aid):
    a = db.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "Assignment not found")
    return a


def get_qa_report(qid):
    q = db.qa_reports.get(qid)
    if q is None:
        raise err("ERR_NOT_FOUND", "QAReport not found")
    return q


def get_invoice(iid):
    i = db.invoices.get(iid)
    if i is None:
        raise err("ERR_NOT_FOUND", "Invoice not found")
    return i


def jobs_of_project(pid):
    return [j for j in db.jobs.values() if j["project_id"] == pid]


def assignments_of_job(jid):
    return [a for a in db.assignments.values() if a["job_id"] == jid]


def active_translator_assignment(jid):
    """The job's non-terminal TRANSLATOR assignment, if any."""
    terminal = {"DELIVERED", "DECLINED", "SUPERSEDED", "CANCELLED"}
    for a in db.assignments.values():
        if a["job_id"] == jid and a["role"] == "TRANSLATOR" and a["status"] not in terminal:
            return a
    return None


def active_reviewer_assignment(jid):
    terminal = {"DELIVERED", "DECLINED", "SUPERSEDED", "CANCELLED"}
    for a in db.assignments.values():
        if a["job_id"] == jid and a["role"] == "REVIEWER" and a["status"] not in terminal:
            return a
    return None


def invoices_of_project(pid):
    return [i for i in db.invoices.values() if i["project_id"] == pid]
