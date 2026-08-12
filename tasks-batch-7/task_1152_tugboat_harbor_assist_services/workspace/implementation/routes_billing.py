"""Billing: invoices (finalize/void) and damage claims (review/settle)."""
from flask import Blueprint, request

from db import store, new_id, stamp_new, touch
from errors import ApiError
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_str, get_int, get_enum, get_occ,
    parse_pagination, check_enum_filter, page_slice,
)
from calc import (
    ser_invoice, ser_claim, compute_invoice_lines, claim_economics,
    recompute_vessel_outstanding,
)

bp = Blueprint('billing', __name__)

INVOICE_STATUSES = {'PROVISIONAL', 'FINALIZED', 'VOID'}
INVOICE_TERMINAL = {'FINALIZED', 'VOID'}
CLAIM_STATUSES = {'FILED', 'UNDER_REVIEW', 'ACCEPTED', 'DENIED', 'SETTLED'}
CLAIM_TERMINAL = {'SETTLED', 'DENIED'}
REVIEW_ACTIONS = {'START_REVIEW', 'REQUEST_INFO', 'ACCEPT', 'DENY'}


def _load_invoice(iid):
    inv = store.invoices.get(iid)
    if inv is None:
        not_found('invoice')
    return inv


def _load_claim(cid):
    cl = store.damage_claims.get(cid)
    if cl is None:
        not_found('damage claim')
    return cl


# ------------------------------------------------------------------ invoices

@bp.route('/api/invoices', methods=['GET'])
def list_invoices():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', INVOICE_STATUSES, c)
    job_id = request.args.get('job_order_id')
    c.raise_deferred()
    recs = [i for i in store.invoices.values()
            if (status is None or i['status'] == status)
            and (job_id is None or i['job_order_id'] == job_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.route('/api/invoices/<iid>', methods=['GET'])
def get_invoice(iid):
    authenticate()
    return ok_object(ser_invoice(_load_invoice(iid)))


@bp.route('/api/invoices/<iid>/finalize', methods=['POST'])
def finalize_invoice(iid):
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    inv = _load_invoice(iid)
    body = json_body()
    c = Check()
    get_occ(body, 'expected_invoice_version', inv['version'], c)
    if inv['status'] in INVOICE_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Invoice is in terminal state {inv['status']}")
    # inv['status'] == 'PROVISIONAL' here; the owning job must be COMPLETED.
    job = store.job_orders[inv['job_order_id']]
    if job['status'] != 'COMPLETED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot finalize while the job is in state {job['status']}")
    c.raise_deferred()
    lines = compute_invoice_lines(job, 'ACTUAL')
    inv.update(lines)
    inv['status'] = 'FINALIZED'
    touch(inv)
    job['status'] = 'INVOICED'
    touch(job)
    recompute_vessel_outstanding(job['vessel_id'])
    return ok_object(ser_invoice(inv))


@bp.route('/api/invoices/<iid>/void', methods=['POST'])
def void_invoice(iid):
    _, role = authenticate()
    require_roles(role, ('PortAdmin',))
    inv = _load_invoice(iid)
    if inv['status'] == 'VOID':
        raise ApiError('ERR_ALREADY_TERMINAL', 409, 'Invoice is already VOID')
    body = json_body()
    c = Check()
    get_str(body, 'void_reason', c, required=False)  # accepted, not stored
    c.raise_deferred()
    inv['status'] = 'VOID'
    touch(inv)
    job = store.job_orders[inv['job_order_id']]
    recompute_vessel_outstanding(job['vessel_id'])
    return ok_object(ser_invoice(inv))


# ------------------------------------------------------------------ claims

@bp.route('/api/damage-claims', methods=['POST'])
def create_claim():
    uid, role = authenticate()
    require_roles(role, ('VesselAgent',))
    body = json_body()
    c = Check()
    # Ownership (stage 3): the claim's vessel_id must equal X-User-ID.
    raw_vessel = body.get('vessel_id')
    if raw_vessel is None or not isinstance(raw_vessel, str):
        c.bad_request = True
    elif raw_vessel != uid:
        raise ApiError('ERR_JOB_NOT_OWNED', 403,
                       'VesselAgent may only file claims for their own vessel')
    # Existence (stage 4), left to right: incident_id, then vessel_id.
    raw_incident = body.get('incident_id')
    incident = None
    if raw_incident is None or not isinstance(raw_incident, str):
        c.bad_request = True
    else:
        incident = store.incidents.get(raw_incident)
        if incident is None:
            not_found('incident')
    if isinstance(raw_vessel, str) and raw_vessel not in store.vessels:
        not_found('vessel')
    # Business constraints: one claim per incident (24) before resolved (25).
    if incident is not None:
        for cl in store.damage_claims.values():
            if cl['incident_id'] == incident['id']:
                raise ApiError('ERR_CLAIM_ALREADY_FILED', 409,
                               'A damage claim already exists for this incident')
        if incident['status'] == 'RESOLVED':
            raise ApiError('ERR_INCIDENT_ALREADY_RESOLVED', 409,
                           'Cannot file a claim against a RESOLVED incident')
    claimed = get_int(body, 'claimed_amount_cents', c, lo=0, lo_exclusive=True)
    c.raise_deferred()
    variant, cap, deductible, payout = claim_economics(incident, claimed)
    rec = {
        'id': new_id(), 'incident_id': raw_incident, 'vessel_id': raw_vessel,
        'claimed_amount_cents': claimed, 'liability_variant': variant,
        'liability_cap_cents': cap, 'deductible_cents': deductible,
        'payout_cents': payout, 'reviewer_notes': None, 'status': 'FILED',
    }
    stamp_new(rec)
    store.damage_claims[rec['id']] = rec
    # Filing against a REPORTED incident escalates it to UNDER_INVESTIGATION.
    if incident['status'] == 'REPORTED':
        incident['status'] = 'UNDER_INVESTIGATION'
        touch(incident)
    return ok_object(ser_claim(rec), 201)


@bp.route('/api/damage-claims', methods=['GET'])
def list_claims():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', CLAIM_STATUSES, c)
    incident_id = request.args.get('incident_id')
    vessel_id = request.args.get('vessel_id')
    c.raise_deferred()
    recs = [cl for cl in store.damage_claims.values()
            if (status is None or cl['status'] == status)
            and (incident_id is None or cl['incident_id'] == incident_id)
            and (vessel_id is None or cl['vessel_id'] == vessel_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_claim(cl) for cl in page], limit, offset, total)


@bp.route('/api/damage-claims/<cid>', methods=['GET'])
def get_claim(cid):
    authenticate()
    return ok_object(ser_claim(_load_claim(cid)))


@bp.route('/api/damage-claims/<cid>/review', methods=['POST'])
def review_claim(cid):
    _, role = authenticate()
    require_roles(role, ('ClaimsAdjuster',))
    cl = _load_claim(cid)
    body = json_body()
    c = Check()
    action = get_enum(body, 'action', REVIEW_ACTIONS, c)
    notes = get_str(body, 'reviewer_notes', c, required=False)
    if cl['status'] in CLAIM_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Claim is in terminal state {cl['status']}")
    transitions = {
        'START_REVIEW': ('FILED', 'UNDER_REVIEW'),
        'REQUEST_INFO': ('UNDER_REVIEW', 'FILED'),
        'ACCEPT': ('UNDER_REVIEW', 'ACCEPTED'),
        'DENY': ('UNDER_REVIEW', 'DENIED'),
    }
    if action is not None:
        from_state, to_state = transitions[action]
        if cl['status'] != from_state:
            raise ApiError('ERR_INVALID_STATE', 409,
                           f"Action {action} requires state {from_state}, "
                           f"but the claim is {cl['status']}")
        if notes is not None:
            cl['reviewer_notes'] = notes
        cl['status'] = to_state
        touch(cl)
    c.raise_deferred()
    return ok_object(ser_claim(cl))


@bp.route('/api/damage-claims/<cid>/settle', methods=['POST'])
def settle_claim(cid):
    _, role = authenticate()
    require_roles(role, ('ClaimsAdjuster',))
    cl = _load_claim(cid)
    if cl['status'] in CLAIM_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Claim is in terminal state {cl['status']}")
    if cl['status'] != 'ACCEPTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot settle a claim in state {cl['status']}")
    cl['status'] = 'SETTLED'
    touch(cl)
    recompute_vessel_outstanding(cl['vessel_id'])
    return ok_object(ser_claim(cl))
