"""Stage-3 existence resolution (PRD sections 2.5 and 2.11).

Where a request names several resources they are resolved in the entity order
institution, readiness submission, depositor record, deposit account, insurance
determination, receivership certificate, bidder, bid, branch reopening,
dividend round -- and the first one that does not resolve determines the 404.
"""

from db import db
from errors import ApiError


def _find(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def institution(identifier):
    return _find(db.institutions, identifier, "ERR_INSTITUTION_NOT_FOUND")


def submission(identifier):
    return _find(db.submissions, identifier, "ERR_SUBMISSION_NOT_FOUND")


def depositor(identifier):
    return _find(db.depositors, identifier, "ERR_DEPOSITOR_NOT_FOUND")


def account(identifier):
    return _find(db.accounts, identifier, "ERR_ACCOUNT_NOT_FOUND")


def determination(identifier):
    return _find(db.determinations, identifier, "ERR_DETERMINATION_NOT_FOUND")


def certificate(identifier):
    return _find(db.certificates, identifier, "ERR_CERTIFICATE_NOT_FOUND")


def bidder(identifier):
    return _find(db.bidders, identifier, "ERR_BIDDER_NOT_FOUND")


def bid(identifier):
    return _find(db.bids, identifier, "ERR_BID_NOT_FOUND")


def reopening(identifier):
    return _find(db.reopenings, identifier, "ERR_BRANCH_REOPENING_NOT_FOUND")


def distribution(identifier):
    return _find(db.distributions, identifier, "ERR_DISTRIBUTION_NOT_FOUND")


# --- collection scans -------------------------------------------------------


def accounts_of(institution_id):
    return [a for a in db.accounts.values() if a["institution_id"] == institution_id]


def depositors_of(institution_id):
    return [d for d in db.depositors.values() if d["institution_id"] == institution_id]


def submissions_of(institution_id):
    return [s for s in db.submissions.values() if s["institution_id"] == institution_id]


def interests_on_account(account_id, role=None):
    rows = [
        i for i in db.interests.values() if i["deposit_account_id"] == account_id
    ]
    if role is not None:
        rows = [i for i in rows if i["interest_role"] == role]
    return rows


def interests_of_depositor(depositor_id, role=None):
    rows = [
        i for i in db.interests.values() if i["depositor_record_id"] == depositor_id
    ]
    if role is not None:
        rows = [i for i in rows if i["interest_role"] == role]
    return rows


def determinations_of_depositor(depositor_id):
    return [
        d
        for d in db.determinations.values()
        if d["depositor_record_id"] == depositor_id
    ]


def certificates_of_institution(institution_id):
    return [
        c for c in db.certificates.values() if c["institution_id"] == institution_id
    ]


def certificates_of_determination(determination_id):
    return [
        c
        for c in db.certificates.values()
        if c["insurance_determination_id"] == determination_id
    ]


def bids_of_institution(institution_id):
    return [b for b in db.bids.values() if b["institution_id"] == institution_id]


def reopenings_of(institution_id):
    return [r for r in db.reopenings.values() if r["institution_id"] == institution_id]


def distributions_of(institution_id):
    return [
        d for d in db.distributions.values() if d["institution_id"] == institution_id
    ]


def institution_of_depositor(depositor_row):
    return db.institutions.get(depositor_row["institution_id"])
