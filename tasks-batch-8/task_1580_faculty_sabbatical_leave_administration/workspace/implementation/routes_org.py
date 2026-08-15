"""Routes: logical clock, departments, faculty members, accrual engine."""
from decimal import Decimal

from flask import request

from db import CLOCK, SEQ, STORE, clock_now, touch
from flask_app import app
from services import (add_ledger_entry, breach_obligation, cancel_scheduled_grant,
                      curtail_grant, department_mutated, faculty_balances,
                      ser_department, ser_faculty, ser_ledger_entry,
                      sweep_overdue_and_defaults)
from util import (auth_context, body_json, fail, first_day_of_month, iso,
                  month_index, month_of, month_str_from_index, new_id, ok,
                  optional_string, paginate, parse_dt, parse_int,
                  parse_positive_money, prev_month_str, require_role,
                  require_string, sort_items)

ADMIN = {'LeaveAdministrator'}
RANKS = {'ASSISTANT_PROFESSOR', 'ASSOCIATE_PROFESSOR', 'FULL_PROFESSOR'}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    uid, role = auth_context()  # tier 1: headers present and role declared
    body = body_json()
    target = parse_dt(body.get('to_iso8601'))  # tier 2: request shape
    if target is None:
        fail('ERR_INVALID_REQUEST', 'to_iso8601 is required and must be a valid ISO-8601 timestamp.')
    require_role(role, ADMIN)  # tier 3: role membership
    CLOCK['now'] = target
    sweep_overdue_and_defaults()
    return ok({'current_utc': iso(target)})


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
@app.route('/departments', methods=['POST'])
def create_department():
    auth_context()
    body = body_json()
    name = require_string(body, 'name')
    pool = parse_positive_money(body.get('replacement_pool'))
    if pool is None:
        fail('ERR_INVALID_REQUEST', 'replacement_pool is required and must be a positive number.')
    chair = body.get('chair_faculty_id')
    if chair is not None and not isinstance(chair, str):
        fail('ERR_INVALID_REQUEST', 'chair_faculty_id must be a string when provided.')
    role = auth_context()[1]
    require_role(role, ADMIN)
    if chair is not None and chair not in STORE['faculty']:
        fail('ERR_FACULTY_NOT_FOUND')
    now = clock_now()
    dept = {
        'id': new_id(), '_seq': next(SEQ),
        'name': name, 'chair_faculty_id': chair,
        'replacement_pool': pool,
        'reserved_amount': Decimal('0'), 'spent_amount': Decimal('0'),
        'posture': 'OPEN',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['departments'][dept['id']] = dept
    return ok(ser_department(dept), 201)


@app.route('/departments', methods=['GET'])
def list_departments():
    auth_context()
    items = sort_items(STORE['departments'].values())
    chair = request.args.get('chair_faculty_id')
    if chair is not None:
        items = [d for d in items if d['chair_faculty_id'] == chair]
    page, meta = paginate(items)
    return ok([ser_department(d) for d in page], 200, pagination=meta, response_type='array')


@app.route('/departments/<did>', methods=['GET'])
def get_department(did):
    auth_context()
    dept = STORE['departments'].get(did)
    if dept is None:
        fail('ERR_DEPARTMENT_NOT_FOUND')
    return ok(ser_department(dept))


@app.route('/departments/<did>', methods=['PATCH'])
def patch_department(did):
    auth_context()
    body = body_json()
    name = body.get('name')
    if name is not None and (not isinstance(name, str) or not name):
        fail('ERR_INVALID_REQUEST', 'name must be a non-empty string.')
    pool = None
    if 'replacement_pool' in body:
        pool = parse_positive_money(body.get('replacement_pool'))
        if pool is None:
            fail('ERR_INVALID_REQUEST', 'replacement_pool must be a positive number.')
    chair_marker = object()
    chair = body.get('chair_faculty_id', chair_marker)
    if chair is not chair_marker and chair is not None and not isinstance(chair, str):
        fail('ERR_INVALID_REQUEST', 'chair_faculty_id must be a string or null.')
    role = auth_context()[1]
    require_role(role, ADMIN)
    dept = STORE['departments'].get(did)  # tier 4: existence, left to right
    if dept is None:
        fail('ERR_DEPARTMENT_NOT_FOUND')
    if chair is not chair_marker and chair is not None and chair not in STORE['faculty']:
        fail('ERR_FACULTY_NOT_FOUND')
    if pool is not None and pool < dept['reserved_amount'] + dept['spent_amount']:
        fail('ERR_POOL_BELOW_COMMITMENTS')
    if name is not None:
        dept['name'] = name
    if chair is not chair_marker:
        dept['chair_faculty_id'] = chair
    if pool is not None:
        dept['replacement_pool'] = pool
    department_mutated(dept)  # recompute posture + version increment
    return ok(ser_department(dept))


# ---------------------------------------------------------------------------
# Faculty members
# ---------------------------------------------------------------------------
@app.route('/faculty-members', methods=['POST'])
def create_faculty():
    auth_context()
    body = body_json()
    employee_number = require_string(body, 'employee_number')
    full_name = require_string(body, 'full_name')
    department_id = body.get('department_id')
    if not isinstance(department_id, str) or not department_id:
        fail('ERR_INVALID_REQUEST', 'department_id is required.')
    rank = body.get('academic_rank')
    if rank not in RANKS:
        fail('ERR_INVALID_REQUEST', 'academic_rank must be one of ASSISTANT_PROFESSOR, ASSOCIATE_PROFESSOR, FULL_PROFESSOR.')
    hire_date = parse_dt(body.get('hire_date'))
    if hire_date is None:
        fail('ERR_INVALID_REQUEST', 'hire_date is required and must be a valid ISO-8601 timestamp.')
    salary = parse_positive_money(body.get('annual_base_salary'))
    if salary is None:
        fail('ERR_INVALID_REQUEST', 'annual_base_salary is required and must be a positive number.')
    role = auth_context()[1]
    require_role(role, ADMIN)
    if department_id not in STORE['departments']:
        fail('ERR_DEPARTMENT_NOT_FOUND')
    for f in STORE['faculty'].values():
        if f['employee_number'] == employee_number:
            fail('ERR_INVALID_REQUEST', 'employee_number must be unique.')
    now = clock_now()
    fac = {
        'id': new_id(), '_seq': next(SEQ),
        'employee_number': employee_number, 'full_name': full_name,
        'department_id': department_id, 'academic_rank': rank,
        'hire_date': hire_date, 'annual_base_salary': salary,
        'status': 'ACTIVE',
        'last_accrued_month': prev_month_str(month_of(hire_date)),
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['faculty'][fac['id']] = fac
    return ok(ser_faculty(fac), 201)


@app.route('/faculty-members', methods=['GET'])
def list_faculty():
    auth_context()
    items = sort_items(STORE['faculty'].values())
    dept = request.args.get('department_id')
    if dept is not None:
        items = [f for f in items if f['department_id'] == dept]
    status = request.args.get('status')
    if status is not None:
        items = [f for f in items if f['status'] == status]
    page, meta = paginate(items)
    return ok([ser_faculty(f) for f in page], 200, pagination=meta, response_type='array')


@app.route('/faculty-members/<fid>', methods=['GET'])
def get_faculty(fid):
    auth_context()
    fac = STORE['faculty'].get(fid)
    if fac is None:
        fail('ERR_FACULTY_NOT_FOUND')
    return ok(ser_faculty(fac))


@app.route('/faculty-members/<fid>/separate', methods=['POST'])
def separate_faculty(fid):
    auth_context()
    body = body_json()
    sep_date = parse_dt(body.get('separation_date'))
    if sep_date is None:
        fail('ERR_INVALID_REQUEST', 'separation_date is required and must be a valid ISO-8601 timestamp.')
    role = auth_context()[1]
    require_role(role, ADMIN)
    fac = STORE['faculty'].get(fid)
    if fac is None:
        fail('ERR_FACULTY_NOT_FOUND')
    if fac['status'] == 'SEPARATED':
        fail('ERR_INVALID_FACULTY_STATE')

    if fac['status'] == 'ON_LEAVE':
        # The ACTIVE grant is curtailed at the separation date; the fresh
        # obligation is immediately breached (amount_owed == base_amount).
        active = sort_items([g for g in STORE['grants'].values()
                             if g['faculty_id'] == fid and g['status'] == 'ACTIVE'])
        new_obligations = []
        for g in active:
            ob = curtail_grant(g, sep_date)
            if ob is not None:
                new_obligations.append(ob)
        for ob in new_obligations:
            breach_obligation(ob)
        earlier = sort_items([o for o in STORE['obligations'].values()
                              if o['faculty_id'] == fid and o['status'] == 'IN_PROGRESS'])
        for ob in earlier:
            breach_obligation(ob)
    else:
        # ACTIVE: every SCHEDULED grant is cancelled with the full unwind.
        scheduled = sort_items([g for g in STORE['grants'].values()
                                if g['faculty_id'] == fid and g['status'] == 'SCHEDULED'])
        for g in scheduled:
            cancel_scheduled_grant(g)
        in_progress = sort_items([o for o in STORE['obligations'].values()
                                  if o['faculty_id'] == fid and o['status'] == 'IN_PROGRESS'])
        for ob in in_progress:
            breach_obligation(ob)

    fac['status'] = 'SEPARATED'
    touch(fac)
    return ok(ser_faculty(fac))


@app.route('/faculty-members/<fid>/eligibility', methods=['GET'])
def faculty_eligibility(fid):
    auth_context()
    raw = request.args.get('proposed_start_date')
    start = parse_dt(raw) if raw is not None else None
    if start is None:
        fail('ERR_INVALID_REQUEST', 'proposed_start_date query parameter is required and must be a valid ISO-8601 timestamp.')
    fac = STORE['faculty'].get(fid)
    if fac is None:
        fail('ERR_FACULTY_NOT_FOUND')
    credit, lifetime = faculty_balances(fid)
    start_prev = prev_month_str(month_of(start))
    extra = month_index(start_prev) - month_index(fac['last_accrued_month'])
    provisional = lifetime + max(0, extra)
    return ok({
        'certified_service_months': lifetime,
        'provisional_service_months': provisional,
        'credit_balance': credit,
        'eligible_certified': lifetime >= 72,
        'eligible_provisional': provisional >= 72,
    })


@app.route('/faculty-members/<fid>/accrual-ledger-entries', methods=['GET'])
def faculty_ledger(fid):
    auth_context()
    fac = STORE['faculty'].get(fid)
    if fac is None:
        fail('ERR_FACULTY_NOT_FOUND')
    items = sort_items([e for e in STORE['ledger'] if e['faculty_id'] == fid])
    page, meta = paginate(items)
    return ok([ser_ledger_entry(e) for e in page], 200, pagination=meta, response_type='array')


# ---------------------------------------------------------------------------
# Accrual engine
# ---------------------------------------------------------------------------
@app.route('/accrual-runs', methods=['POST'])
def accrual_run():
    auth_context()
    body_json()  # no payload fields; tolerate empty body
    role = auth_context()[1]
    require_role(role, ADMIN)
    now = clock_now()
    through = prev_month_str(month_of(now))
    through_idx = month_index(through)

    earn_created = 0
    processed = 0
    for fac in sort_items(STORE['faculty'].values()):
        processed += 1
        last_idx = month_index(fac['last_accrued_month'])
        if through_idx <= last_idx:
            continue
        blocked = any(r['faculty_id'] == fac['id'] and r['status'] == 'OVERDUE'
                      for r in STORE['reports'].values())
        separated = fac['status'] == 'SEPARATED'
        covering = [g for g in STORE['grants'].values()
                    if g['faculty_id'] == fac['id']
                    and g['status'] in ('ACTIVE', 'COMPLETED', 'CURTAILED')]
        idx = last_idx
        while idx < through_idx:
            idx += 1
            wm = month_str_from_index(idx)
            first_day = first_day_of_month(wm)
            covered = any(g['start_date'] <= first_day < g['end_date'] for g in covering)
            if not covered and not blocked and not separated:
                add_ledger_entry(fac['id'], 'EARN', 1, month=wm)
                earn_created += 1
        fac['last_accrued_month'] = through
        touch(fac)

    obligation_months = 0
    for ob in sort_items(STORE['obligations'].values()):
        if ob['status'] != 'IN_PROGRESS':
            continue
        fac = STORE['faculty'].get(ob['faculty_id'])
        last_idx = month_index(ob['last_credited_month'])
        changed = False
        if through_idx > last_idx:
            months = through_idx - last_idx
            if fac is not None and fac['status'] == 'ACTIVE':
                ob['fulfilled_months'] += months
                obligation_months += months
            # months while ON_LEAVE / SEPARATED are skipped permanently;
            # the watermark advances regardless.
            ob['last_credited_month'] = through
            changed = True
        if ob['fulfilled_months'] >= ob['required_months']:
            ob['status'] = 'FULFILLED'
            changed = True
        if changed:
            touch(ob)

    return ok({
        'earn_entries_created': earn_created,
        'obligation_months_credited': obligation_months,
        'faculty_processed': processed,
    })


@app.route('/accrual-ledger-entries', methods=['POST'])
def create_ledger_entry():
    auth_context()
    body = body_json()
    faculty_id = body.get('faculty_id')
    if not isinstance(faculty_id, str) or not faculty_id:
        fail('ERR_INVALID_REQUEST', 'faculty_id is required.')
    entry_type = body.get('entry_type')
    if entry_type != 'ADJUST':
        fail('ERR_INVALID_REQUEST', 'entry_type must be ADJUST.')
    delta = parse_int(body.get('credits_delta'))
    if delta is None:
        fail('ERR_INVALID_REQUEST', 'credits_delta is required and must be an integer.')
    affects = body.get('affects_lifetime', False)
    if not isinstance(affects, bool):
        fail('ERR_INVALID_REQUEST', 'affects_lifetime must be a boolean.')
    note = optional_string(body, 'note')
    role = auth_context()[1]
    require_role(role, ADMIN)
    if faculty_id not in STORE['faculty']:
        fail('ERR_FACULTY_NOT_FOUND')
    entry = add_ledger_entry(faculty_id, 'ADJUST', delta,
                             month=None, affects_lifetime=affects, note=note)
    return ok(ser_ledger_entry(entry), 201)
