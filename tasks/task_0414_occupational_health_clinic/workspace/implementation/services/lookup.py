"""Path-resource existence lookups (priority 3). Each raises the resource-specific
not-found error from PRD §2.5 / §5.
"""

import errors
from db import db
from errors import err


def get_employer(employer_id):
    e = db.employers.get(employer_id)
    if e is None:
        raise err(errors.ERR_EMPLOYER_NOT_FOUND, "Employer not found")
    return e


def get_protocol(protocol_id):
    p = db.protocols.get(protocol_id)
    if p is None:
        raise err(errors.ERR_PROTOCOL_NOT_FOUND, "Protocol not found")
    return p


def get_worker(worker_id):
    w = db.workers.get(worker_id)
    if w is None:
        raise err(errors.ERR_WORKER_NOT_FOUND, "Worker not found")
    return w


def get_encounter(encounter_id):
    e = db.encounters.get(encounter_id)
    if e is None:
        raise err(errors.ERR_ENCOUNTER_NOT_FOUND, "Encounter not found")
    return e


def get_drug_screen(ds_id):
    d = db.drug_screens.get(ds_id)
    if d is None:
        raise err(errors.ERR_DRUG_SCREEN_NOT_FOUND, "Drug screen not found")
    return d


def get_injury_case(ic_id):
    c = db.injury_cases.get(ic_id)
    if c is None:
        raise err(errors.ERR_INJURY_CASE_NOT_FOUND, "Injury case not found")
    return c


def get_surveillance_exam(ex_id):
    x = db.surveillance_exams.get(ex_id)
    if x is None:
        raise err(errors.ERR_SURVEILLANCE_EXAM_NOT_FOUND, "Surveillance exam not found")
    return x


def get_work_status(ws_id):
    w = db.work_statuses.get(ws_id)
    if w is None:
        raise err(errors.ERR_WORK_STATUS_NOT_FOUND, "Work status not found")
    return w


def get_clearance(cl_id):
    c = db.clearances.get(cl_id)
    if c is None:
        raise err(errors.ERR_CLEARANCE_NOT_FOUND, "Clearance not found")
    return c


def get_invoice(inv_id):
    i = db.invoices.get(inv_id)
    if i is None:
        raise err(errors.ERR_INVOICE_NOT_FOUND, "Invoice not found")
    return i


def get_custody_event(ce_id):
    c = db.custody_events.get(ce_id)
    if c is None:
        # No dedicated custody-not-found error in the catalogue; treat as a
        # drug-screen-scoped resource per §2.5 patterns. The PRD only lists
        # not-found errors for the named resources; custody events are read via
        # the drug-screen they belong to. Use ERR_DRUG_SCREEN_NOT_FOUND is wrong;
        # there is genuinely no custody not-found id, so 404 with a generic id.
        raise err(("ERR_CUSTODY_EVENT_NOT_FOUND", 404), "Custody event not found")
    return c
