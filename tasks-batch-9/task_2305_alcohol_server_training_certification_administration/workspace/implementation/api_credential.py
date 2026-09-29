"""Certificates and the state-registry submission loop."""

from flask import Blueprint

import domain
import envelope
import store as st
import validate as v
from auth import authenticate, ALCOHOL_SERVER, EMPLOYER_ADMIN, PROGRAM_ADMIN, \
    STATE_REGULATOR
from calcs import registry_penalty
from errors import fail, invalid
from store import apply_changes, create_row, store

bp = Blueprint("credential", __name__)

READ_CERTIFICATE_ROLES = (PROGRAM_ADMIN, STATE_REGULATOR, EMPLOYER_ADMIN, ALCOHOL_SERVER)
TRANSMITTABLE_REGISTRY_STATES = ("PENDING_SUBMISSION", "RESUBMIT_REQUIRED")


def paged(items):
    limit, offset = v.pagination()
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.get("/certificates/<certificate_id>")
def read_certificate(certificate_id):
    authenticate(READ_CERTIFICATE_ROLES)
    return envelope.ok_row(v.must_exist("certificates", certificate_id))


@bp.get("/certificates")
def list_certificates():
    authenticate(READ_CERTIFICATE_ROLES)
    filters = {
        "alcohol_server_id": v.q_str("alcohol_server_id"),
        "enrollment_id": v.q_str("enrollment_id"),
        "state_jurisdiction_id": v.q_str("state_jurisdiction_id"),
        "renews_certificate_id": v.q_str("renews_certificate_id"),
        "validity_state": v.q_enum("validity_state", v.VALIDITY_STATES),
        "registry_state": v.q_enum("registry_state", v.REGISTRY_STATES),
    }

    def keep(row):
        for key, wanted in filters.items():
            if wanted is not None and row[key] != wanted:
                return False
        return True

    return paged([r for r in st.rows("certificates") if keep(r)])


@bp.post("/certificates/<certificate_id>/registry-submissions")
def transmit_certificate(certificate_id):
    authenticate((PROGRAM_ADMIN,))
    body = v.body()
    batch_reference = v.opt_str(body, "batch_reference", 1, None)
    certificate = v.must_exist("certificates", certificate_id)
    if (certificate["registry_state"] not in TRANSMITTABLE_REGISTRY_STATES
            or certificate["validity_state"] == "SUPERSEDED"):          # priority 15
        fail("ERR_CERTIFICATE_INVALID_STATE",
             "A certificate in %s / %s cannot be transmitted."
             % (certificate["validity_state"], certificate["registry_state"]))

    jurisdiction = st.get("state_jurisdictions", certificate["state_jurisdiction_id"])
    attempt_number = len(domain.submissions_of_certificate(certificate["id"])) + 1
    transmitted_at = store.clock
    late_days, penalty = registry_penalty(
        transmitted_at,
        certificate["registry_due_at"],
        attempt_number,
        jurisdiction["registry_late_fee_cents_per_day"],
    )
    submission = create_row("registry_submissions", {
        "certificate_id": certificate["id"],
        "batch_reference": batch_reference,
        "submission_state": "TRANSMITTED",
        "attempt_number": attempt_number,
        "transmitted_at": transmitted_at,
        "due_at": certificate["registry_due_at"],
        "late_days": late_days,
        "penalty_fee_cents": penalty,
        "rejection_code": "NONE",
        "acknowledged_at": None,
    })
    apply_changes(certificate, {"registry_state": "SUBMITTED"})
    return envelope.ok_row(submission, 201)


@bp.post("/registry-submissions/<submission_id>/acknowledge")
def acknowledge_submission(submission_id):
    authenticate((STATE_REGULATOR,))
    body = v.body()
    result = v.req_enum(body, "result", v.ACK_RESULTS)
    rejection_code = v.opt_enum(body, "rejection_code", v.REJECTION_CODES)
    if result == "REJECTED" and (rejection_code is None or rejection_code == "NONE"):
        invalid("Field 'rejection_code' is required and must not be NONE.")
    submission = v.must_exist("registry_submissions", submission_id)
    if submission["submission_state"] != "TRANSMITTED":                 # priority 16
        fail("ERR_SUBMISSION_INVALID_STATE",
             "Only a TRANSMITTED submission may be acknowledged; this one is '%s'."
             % submission["submission_state"])
    certificate = st.get("certificates", submission["certificate_id"])
    if result == "ACCEPTED":
        domain.acknowledge_accepted(submission, certificate)
    else:
        domain.acknowledge_rejected(submission, certificate, rejection_code)
    return envelope.ok_row(submission)


@bp.get("/certificates/<certificate_id>/registry-submissions")
def list_submissions(certificate_id):
    authenticate((PROGRAM_ADMIN, STATE_REGULATOR))
    limit, offset = v.pagination()
    certificate = v.must_exist("certificates", certificate_id)
    items = domain.submissions_of_certificate(certificate["id"])
    page, total = envelope.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)
