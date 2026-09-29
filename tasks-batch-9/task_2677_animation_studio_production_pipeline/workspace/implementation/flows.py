"""Lookup helpers, phase gating and the state transitions shared by several
endpoints (retake entry, stage approval, package recall)."""
from calc import (RETAKE_ESCALATION_THRESHOLD, reconcile_shots, recompute_production,
                  shot_of_task)
from helpers import ApiError
from store import db, now, touch

_NOT_FOUND = {
    'productions': 'ERR_PRODUCTION_NOT_FOUND',
    'gates': 'ERR_GATE_NOT_FOUND',
    'assets': 'ERR_ASSET_NOT_FOUND',
    'shots': 'ERR_SHOT_NOT_FOUND',
    'tasks': 'ERR_TASK_NOT_FOUND',
    'rooms': 'ERR_ROOM_NOT_FOUND',
    'sessions': 'ERR_SESSION_NOT_FOUND',
    'notes': 'ERR_NOTE_NOT_FOUND',
    'pools': 'ERR_POOL_NOT_FOUND',
    'jobs': 'ERR_RENDER_JOB_NOT_FOUND',
    'partners': 'ERR_PARTNER_NOT_FOUND',
    'packages': 'ERR_PACKAGE_NOT_FOUND',
    'deliverables': 'ERR_DELIVERABLE_NOT_FOUND',
}


def _lookup(collection, row_id):
    table = getattr(db, collection)
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(_NOT_FOUND[collection], 404, '%s not found' % collection[:-1])
    return table[row_id]


def get_production(row_id):
    return _lookup('productions', row_id)


def get_gate(row_id):
    return _lookup('gates', row_id)


def get_asset(row_id):
    return _lookup('assets', row_id)


def get_shot(row_id):
    return _lookup('shots', row_id)


def get_task(row_id):
    return _lookup('tasks', row_id)


def get_room(row_id):
    return _lookup('rooms', row_id)


def get_session(row_id):
    return _lookup('sessions', row_id)


def get_note(row_id):
    return _lookup('notes', row_id)


def get_pool(row_id):
    return _lookup('pools', row_id)


def get_job(row_id):
    return _lookup('jobs', row_id)


def get_partner(row_id):
    return _lookup('partners', row_id)


def get_package(row_id):
    return _lookup('packages', row_id)


def get_deliverable(row_id):
    return _lookup('deliverables', row_id)


# -------------------------------------------------------------- phase gating
def require_phase(production, allowed):
    if production is None:
        return
    if production['phase'] not in allowed:
        raise ApiError('ERR_PRODUCTION_PHASE_INVALID', 409,
                       'production phase %s does not permit this operation'
                       % production['phase'])


# ------------------------------------------------------- shared task transitions
def enter_retake(task):
    """Every entry into RETAKE, from whatever source, runs the same arithmetic."""
    task['status'] = 'RETAKE'
    task['approved_at'] = None
    task['revision_count'] += 1
    if task['revision_count'] >= RETAKE_ESCALATION_THRESHOLD:
        task['escalated'] = True
    touch(task)


def approve_task(task, user_id):
    task['status'] = 'APPROVED'
    task['approved_at'] = now()
    task['reviewed_by_user_id'] = user_id
    touch(task)


def package_tasks(package):
    """Scoped stage tasks of a package, in the declared scope order."""
    rows = []
    for task_id in package['stage_task_ids']:
        row = db.tasks.get(task_id)
        if row is not None:
            rows.append(row)
    return rows


def tasks_linked_to(package_id):
    return [t for t in db.tasks.values() if t['outsource_package_id'] == package_id]


def reconcile_tasks(tasks):
    """Recompute every shot the given tasks belong to, and their productions."""
    shots = []
    for task in tasks:
        shot = shot_of_task(task)
        if shot is not None:
            shots.append(shot)
    reconcile_shots(shots)


def reconcile_production(production):
    if production is not None:
        recompute_production(production)


def fk_lookup(body, key, getter):
    """Resolve a body foreign key (check 4) before the schema check (check 5).

    A field that is absent or not a non-empty string is left to the schema step,
    which reports ERR_VALIDATION; a present identifier that does not resolve
    raises the matching 404.
    """
    if not isinstance(body, dict):
        return None
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return getter(value)
