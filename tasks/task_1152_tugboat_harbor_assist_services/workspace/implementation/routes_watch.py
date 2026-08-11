"""Watch rotations: log, list, get."""
from flask import Blueprint, request

from db import store, new_id, stamp_new
from errors import ApiError
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_dt, half_open_overlap,
    parse_pagination, page_slice,
)
from calc import ser_watch, REQUIRED_REST_SECONDS, REST_WINDOW

bp = Blueprint('watch_rotations', __name__)

DAY_SECONDS = 24 * 3600


@bp.route('/api/watch-rotations', methods=['POST'])
def create_watch():
    uid, role = authenticate()
    require_roles(role, ('TugCaptain',))
    body = json_body()
    c = Check()
    # The assignment must load to evaluate TugCaptain ownership (stage 3).
    raw_asg = body.get('tug_assignment_id')
    asg = None
    if raw_asg is None or not isinstance(raw_asg, str):
        c.bad_request = True
    else:
        asg = store.tug_assignments.get(raw_asg)
        if asg is None:
            not_found('tug assignment')
    if asg is not None and asg['tug_id'] != uid:
        raise ApiError('ERR_ASSIGNMENT_NOT_OWNED', 403,
                       'TugCaptain may only log watches on their own tug')
    raw_crew = body.get('crew_member_id')
    crew = None
    if raw_crew is None or not isinstance(raw_crew, str):
        c.bad_request = True
    else:
        crew = store.crew_members.get(raw_crew)
        if crew is None:
            not_found('crew member')
    # From-state (stage 7): assignment must be CONFIRMED or ACTIVE.
    if asg is not None and asg['status'] not in ('CONFIRMED', 'ACTIVE'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot log a watch on an assignment in state {asg['status']}")
    ws = get_dt(body, 'watch_start', c)
    we = get_dt(body, 'watch_end', c)
    if ws is not None and we is not None and crew is not None:
        # Temporal (15): no half-open overlap with the member's other watches.
        for w in store.watch_rotations.values():
            if (w['crew_member_id'] == crew['id']
                    and half_open_overlap(ws, we, w['watch_start'], w['watch_end'])):
                raise ApiError('ERR_WATCH_OVERLAP', 409,
                               'Watch overlaps an existing watch of this crew member')
        # Constraint (23): crew rest >= 600 minutes in the prior 24h.
        window_start = ws - REST_WINDOW
        worked_seconds = 0.0
        existing = sorted(
            (w for w in store.watch_rotations.values()
             if w['crew_member_id'] == crew['id']),
            key=lambda w: (w['watch_start'], w['_seq']),
        )
        for w in existing:
            lo = max(w['watch_start'], window_start)
            hi = min(w['watch_end'], ws)
            if hi > lo:
                worked_seconds += (hi - lo).total_seconds()
        if DAY_SECONDS - worked_seconds < REQUIRED_REST_SECONDS:
            raise ApiError('ERR_CREW_REST_VIOLATION', 422,
                           'Crew member rest in the prior 24h is below 600 minutes')
    if ws is not None and we is not None and we <= ws:
        c.bad_request = True
    c.raise_deferred()
    rec = {
        'id': new_id(), 'tug_assignment_id': raw_asg, 'crew_member_id': raw_crew,
        'watch_start': ws, 'watch_end': we,
    }
    stamp_new(rec)
    store.watch_rotations[rec['id']] = rec
    return ok_object(ser_watch(rec), 201)


@bp.route('/api/watch-rotations', methods=['GET'])
def list_watches():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    asg_id = request.args.get('tug_assignment_id')
    crew_id = request.args.get('crew_member_id')
    c.raise_deferred()
    recs = [w for w in store.watch_rotations.values()
            if (asg_id is None or w['tug_assignment_id'] == asg_id)
            and (crew_id is None or w['crew_member_id'] == crew_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_watch(w) for w in page], limit, offset, total)


@bp.route('/api/watch-rotations/<wid>', methods=['GET'])
def get_watch(wid):
    authenticate()
    w = store.watch_rotations.get(wid)
    if w is None:
        not_found('watch rotation')
    return ok_object(ser_watch(w))
