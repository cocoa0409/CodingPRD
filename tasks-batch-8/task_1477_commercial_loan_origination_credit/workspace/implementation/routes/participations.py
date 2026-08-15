"""Participations: propose, commit (fee share), release (compensating return)."""
from flask import Blueprint

import serialize
from db import STORE, new_entity, touch
from errors import (
    raise_err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_COMMITMENT_NOT_ACCEPTED,
    ERR_PARTICIPATION_OVERALLOCATION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure
from services.fees import participation_fee_share_cents
from validation import get_body, req_str, req_int

bp = Blueprint("participations", __name__)

PARTICIPATION_APP_STAGES = {"COMMITMENT", "DOCUMENTATION", "CLOSING", "FUNDED"}
LETTER_OPEN_STATES = {"ISSUED", "ACCEPTED", "FUNDED"}


@bp.post("/credit/participations")
def create_participation():
    require_roles("RelationshipManager")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    participant_bank_name = req_str(body, "participant_bank_name")
    allocated = req_int(body, "allocated_amount_cents")
    if allocated <= 0:
        raise_err(ERR_VALIDATION, "Field 'allocated_amount_cents' must be strictly greater than zero.")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")

    app = STORE.loan_applications[app_id]
    letter = exposure.letter_for_app(app_id)
    if app['status'] not in PARTICIPATION_APP_STAGES or letter is None or letter['status'] not in LETTER_OPEN_STATES:
        raise_err(ERR_COMMITMENT_NOT_ACCEPTED,
                  "Participation requires the application past TERM_SHEET_NEGOTIATION with a letter ISSUED, ACCEPTED, or FUNDED.")
    # Priority 33: allocation may not exceed current unallocated headroom.
    if allocated > exposure.bank_hold_amount_cents(app_id):
        raise_err(ERR_PARTICIPATION_OVERALLOCATION,
                  "allocated_amount_cents exceeds the current unallocated commitment headroom.")

    participation = new_entity()
    participation.update({
        'loan_application_id': app_id,
        'participant_bank_name': participant_bank_name,
        'allocated_amount_cents': allocated,
        'fee_share_cents': None,
        'status': 'PROPOSED',
    })
    STORE.participations[participation['id']] = participation
    return success_object(serialize.participation(participation), status=201)


@bp.get("/credit/loan-applications/<aid>/participations")
def application_participations(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    return render_list(exposure.participations_of_app(aid), serialize.participation)


@bp.post("/credit/participations/<pid>/commit")
def commit_participation(pid):
    require_roles("RelationshipManager")
    participation = get_or_404(STORE.participations, pid, "Participation")
    get_body(required=False)
    if participation['status'] != 'PROPOSED':
        raise_err(ERR_INVALID_STATE, "Participation status is %s; commit requires PROPOSED." % participation['status'])
    letter = exposure.letter_for_app(participation['loan_application_id'])
    if letter is None or letter['status'] not in LETTER_OPEN_STATES:
        raise_err(ERR_COMMITMENT_NOT_ACCEPTED,
                  "Commitment letter must be ISSUED, ACCEPTED, or FUNDED to commit a participation.")
    # Per-share round-half-up allocation; the bank remainder absorbs rounding.
    participation['fee_share_cents'] = participation_fee_share_cents(letter, participation['allocated_amount_cents'])
    participation['status'] = 'COMMITTED'
    touch(participation)
    return success_object(serialize.participation(participation))


@bp.post("/credit/participations/<pid>/release")
def release_participation(pid):
    require_roles("RelationshipManager")
    participation = get_or_404(STORE.participations, pid, "Participation")
    get_body(required=False)
    if participation['status'] not in ('PROPOSED', 'COMMITTED'):
        raise_err(ERR_INVALID_STATE, "Participation status is %s; release requires PROPOSED or COMMITTED." % participation['status'])
    # Compensating return: allocation and (if committed) fee share return to the
    # bank hold; the derived hold fields pick this up automatically.
    participation['status'] = 'RELEASED'
    participation['fee_share_cents'] = None
    touch(participation)
    return success_object(serialize.participation(participation))
