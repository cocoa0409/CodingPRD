"""Entity existence lookups that raise the correct not-found error (PRD §2.8)."""
import db
from errors import err


def get_sponsor(sid):
    rec = db.sponsors.get(sid)
    if rec is None:
        raise err("ERR_SPONSOR_NOT_FOUND", "Sponsor %s not found." % sid)
    return rec


def get_program(pid):
    rec = db.programs.get(pid)
    if rec is None:
        raise err("ERR_PROGRAM_NOT_FOUND", "Program %s not found." % pid)
    return rec


def get_wage_step(wid):
    rec = db.wage_steps.get(wid)
    if rec is None:
        raise err("ERR_WAGE_STEP_NOT_FOUND", "Wage step %s not found." % wid)
    return rec


def get_milestone(mid):
    rec = db.milestones.get(mid)
    if rec is None:
        raise err("ERR_MILESTONE_NOT_FOUND", "Milestone %s not found." % mid)
    return rec


def get_journeyworker(jid):
    rec = db.journeyworkers.get(jid)
    if rec is None:
        raise err("ERR_JOURNEYWORKER_NOT_FOUND", "Journeyworker %s not found." % jid)
    return rec


def get_apprentice(aid):
    rec = db.apprentices.get(aid)
    if rec is None:
        raise err("ERR_APPRENTICE_NOT_FOUND", "Apprentice %s not found." % aid)
    return rec


def get_agreement(aid):
    rec = db.agreements.get(aid)
    if rec is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", "Agreement %s not found." % aid)
    return rec


def get_ojt_entry(oid):
    rec = db.ojt_entries.get(oid)
    if rec is None:
        raise err("ERR_OJT_ENTRY_NOT_FOUND", "OJT entry %s not found." % oid)
    return rec


def get_rti_record(rid):
    rec = db.rti_records.get(rid)
    if rec is None:
        raise err("ERR_RTI_RECORD_NOT_FOUND", "RTI record %s not found." % rid)
    return rec


def get_attainment(aid):
    rec = db.milestone_attainments.get(aid)
    if rec is None:
        raise err("ERR_ATTAINMENT_NOT_FOUND", "Milestone attainment %s not found." % aid)
    return rec


def get_certificate(cid):
    rec = db.certificates.get(cid)
    if rec is None:
        raise err("ERR_CERTIFICATE_NOT_FOUND", "Completion certificate %s not found." % cid)
    return rec


def get_eeo_report(rid):
    rec = db.eeo_reports.get(rid)
    if rec is None:
        raise err("ERR_EEO_REPORT_NOT_FOUND", "EEO report %s not found." % rid)
    return rec
