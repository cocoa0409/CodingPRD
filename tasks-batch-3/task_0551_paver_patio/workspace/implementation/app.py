"""Hardscape Outdoor Living API — Flask entrypoint.

All state lives in the in-memory store (store.db). Nothing is seeded at startup;
every entity is created by clients through the endpoints below.
"""

import os
import uuid
from datetime import timedelta

from flask import Flask, request, jsonify

from store import db, iso_millis
from util import (
    ApiError, authorize, check_owner, find, get_body, ok, build_meta,
    base_record, touch, serialize, list_response,
    v_str, v_bool, v_int, v_num, v_enum, v_date, v_list, parse_iso, D, rhu,
)
from calc import project_valuation, material_order_pallets, deposit_cap

app = Flask(__name__)

CATEGORIES = {'PAVER', 'WALL_BLOCK', 'FIRE_PIT', 'OUTDOOR_KITCHEN'}
UNITS = {'SQFT', 'FACE_SQFT', 'EACH', 'LINEAR_FT'}
PHASE_TYPES = {'EXCAVATION', 'BASE_PREP', 'PAVER_SET', 'WALL_BUILD', 'FEATURE_INSTALL', 'FINAL_GRADE'}


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        'meta': build_meta(),
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }
    return jsonify(body), e.http_status


@app.get('/')
def root():
    return jsonify({'status': 'ok'}), 200


# ===========================================================================
# Logical clock (PRD 2.9)
# ===========================================================================
@app.post('/_clock/set_current_utc')
def clock_set():
    authorize({'PlatformAdmin'})
    b = get_body()
    raw = b.get('to_iso8601')
    if raw is None or not isinstance(raw, str):
        raise ApiError('ERR_INVALID_REQUEST', 422, 'to_iso8601 required')
    try:
        dt = parse_iso(raw)
    except Exception:
        raise ApiError('ERR_INVALID_REQUEST', 422, 'to_iso8601 is not a valid ISO 8601 instant')
    db.clock_dt = dt
    db.clock_raw = raw
    return ok({'current_utc': raw}, 'object', 200)


# ===========================================================================
# Customer (PRD 3.1)
# ===========================================================================
@app.post('/customers')
def create_customer():
    authorize({'DesignConsultant', 'PlatformAdmin'})
    b = get_body()
    full_name = v_str(b, 'full_name')
    email = v_str(b, 'email')
    phone = v_str(b, 'phone', required=False)
    billing = v_str(b, 'billing_address', required=False)
    for c in db.customers.values():
        if c['email'] == email:
            raise ApiError('ERR_INVALID_REQUEST', 422, 'email must be unique')
    rec = base_record('customer', {
        'full_name': full_name, 'email': email,
        'phone': phone, 'billing_address': billing,
    })
    db.customers[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


# ===========================================================================
# Product (PRD 3.1)
# ===========================================================================
@app.post('/products')
def create_product():
    authorize({'PlatformAdmin'})
    b = get_body()
    sku = v_str(b, 'sku')
    name = v_str(b, 'name')
    category = v_enum(b, 'category', CATEGORIES)
    unit = v_enum(b, 'unit', UNITS)
    unit_price = v_int(b, 'unit_price_cents', minimum=0)
    waste = v_num(b, 'waste_factor', required=False, default=0, minimum=0, lt=1)
    coverage = v_num(b, 'coverage_per_pallet_sqft', required=False, default=0, minimum=0)
    for p in db.products.values():
        if p['sku'] == sku:
            raise ApiError('ERR_INVALID_REQUEST', 422, 'sku must be unique')
    rec = base_record('product', {
        'sku': sku, 'name': name, 'category': category, 'unit': unit,
        'unit_price_cents': unit_price, 'waste_factor': waste,
        'coverage_per_pallet_sqft': coverage,
        'is_feature': category in ('FIRE_PIT', 'OUTDOOR_KITCHEN'),
    })
    db.products[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/products/<pid>')
def get_product(pid):
    authorize({'PlatformAdmin', 'DesignConsultant', 'ProjectManager'})
    rec = find(db.products, pid, 'ERR_PRODUCT_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/products/<pid>/line-items')
def product_line_items(pid):
    authorize({'PlatformAdmin', 'DesignConsultant'})
    find(db.products, pid, 'ERR_PRODUCT_NOT_FOUND')
    return list_response(db.line_items.values(), lambda r: r['product_id'] == pid)


@app.get('/products/<pid>/change-orders')
def product_change_orders(pid):
    authorize({'PlatformAdmin', 'ProjectManager'})
    find(db.products, pid, 'ERR_PRODUCT_NOT_FOUND')
    return list_response(db.change_orders.values(), lambda r: r['add_product_id'] == pid)


# ===========================================================================
# Crew (PRD 3.1)
# ===========================================================================
@app.post('/crews')
def create_crew():
    authorize({'PlatformAdmin'})
    b = get_body()
    name = v_str(b, 'name')
    region = v_str(b, 'region_code')
    rec = base_record('crew', {'name': name, 'region_code': region})
    db.crews[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/crews/<cid>')
def get_crew(cid):
    authorize({'PlatformAdmin', 'ProjectManager'})
    rec = find(db.crews, cid, 'ERR_CREW_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/crews/<cid>/work-phases')
def crew_work_phases(cid):
    authorize({'PlatformAdmin', 'ProjectManager'})
    find(db.crews, cid, 'ERR_CREW_NOT_FOUND')
    return list_response(db.work_phases.values(), lambda r: r['crew_id'] == cid)


# ===========================================================================
# Project (PRD 3.2 - 3.9)
# ===========================================================================
@app.post('/projects')
def create_project():
    authorize({'DesignConsultant', 'PlatformAdmin'})
    b = get_body()
    customer_id = v_str(b, 'customer_id')
    site_address = v_str(b, 'site_address')
    region = v_str(b, 'region_code')
    in_hoa = v_bool(b, 'in_hoa', required=False, default=False)
    find(db.customers, customer_id, 'ERR_CUSTOMER_NOT_FOUND')
    rec = base_record('project', {
        'customer_id': customer_id, 'site_address': site_address,
        'region_code': region, 'in_hoa': in_hoa, 'status': 'DRAFT',
        'permit_required': False, 'hoa_required': False,
        'estimated_total_cents': 0, 'prompt_pay_discount_cents': 0,
        'contract_value_cents': 0, 'amount_paid_cents': 0, 'balance_due_cents': 0,
        'final_billed_total_cents': 0,
        'warranty_start_date': None, 'warranty_end_date': None,
    })
    db.projects[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/projects')
def list_projects():
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin', 'Client'})
    cust = request.args.get('customer_id')
    return list_response(db.projects.values(), lambda r: cust is None or r['customer_id'] == cust)


@app.get('/projects/<pid>')
def get_project(pid):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.post('/projects/<pid>/generate-estimate')
def generate_estimate(pid):
    authorize({'DesignConsultant'})
    project = find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    if project['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Project is not DRAFT')
    if not any(dr['project_id'] == pid and dr['status'] == 'APPROVED'
               for dr in db.design_revisions.values()):
        raise ApiError('ERR_DESIGN_NOT_APPROVED', 409, 'No approved design revision')
    measurements = [m for m in db.site_measurements.values() if m['project_id'] == pid]
    if not measurements:
        raise ApiError('ERR_NO_MEASUREMENT', 409, 'No site measurement')
    if not any(l['project_id'] == pid for l in db.line_items.values()):
        raise ApiError('ERR_NO_LINE_ITEMS', 409, 'No line items')

    # Permit determination happens as part of generate-estimate; the estimate
    # total must reflect the permit fee, so set permit_required first (PRD 3.3).
    project['permit_required'] = any(D(m['wall_height_in']) >= 48 for m in measurements)
    project['hoa_required'] = project['in_hoa']
    total, prompt = project_valuation(project, 'estimate')
    project['estimated_total_cents'] = total
    project['prompt_pay_discount_cents'] = prompt
    project['contract_value_cents'] = total
    project['balance_due_cents'] = total - project['amount_paid_cents']
    project['status'] = 'QUOTED'
    touch(project)
    return ok(serialize(project), 'object', 200)


@app.post('/projects/<pid>/submit-approvals')
def submit_approvals(pid):
    authorize({'ProjectManager'})
    project = find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    if project['status'] != 'QUOTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Project is not QUOTED')
    if project['permit_required']:
        permit = base_record('permit', {
            'project_id': pid, 'permit_number': None, 'fee_cents': 35000,
            'correction_notes': None, 'status': 'PREPARING',
        })
        db.permits[permit['id']] = permit
    if project['hoa_required']:
        hoa = base_record('hoa_submission', {
            'project_id': pid, 'decision_notes': None, 'conditions': None,
            'status': 'DRAFT',
        })
        db.hoa_submissions[hoa['id']] = hoa
    project['status'] = 'PENDING_APPROVALS'
    touch(project)
    return ok(serialize(project), 'object', 200)


@app.post('/projects/<pid>/sign-contract')
def sign_contract(pid):
    uid, _ = authorize({'Client'})
    project = find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    check_owner(project, uid)
    if project['status'] != 'PENDING_APPROVALS':
        raise ApiError('ERR_INVALID_STATE', 409, 'Project is not PENDING_APPROVALS')
    if not any(dw['project_id'] == pid and dw['draw_type'] == 'DEPOSIT' and dw['status'] == 'PAID'
               for dw in db.draws.values()):
        raise ApiError('ERR_DEPOSIT_NOT_PAID', 409, 'Deposit draw is not PAID')
    if project['hoa_required']:
        if not any(h['project_id'] == pid and h['status'] == 'APPROVED'
                   for h in db.hoa_submissions.values()):
            raise ApiError('ERR_HOA_NOT_APPROVED', 409, 'HOA submission is not APPROVED')
    for line in db.line_items.values():
        if line['project_id'] == pid:
            product = db.products[line['product_id']]
            line['pinned_unit_price_cents'] = product['unit_price_cents']
            touch(line)
    project['contract_value_cents'] = project['estimated_total_cents']
    project['balance_due_cents'] = project['contract_value_cents'] - project['amount_paid_cents']
    project['status'] = 'CONTRACTED'
    touch(project)
    return ok(serialize(project), 'object', 200)


@app.post('/projects/<pid>/start-production')
def start_production(pid):
    authorize({'ProjectManager'})
    project = find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    if project['status'] != 'CONTRACTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Project is not CONTRACTED')
    if not any(mo['project_id'] == pid and mo['status'] == 'DELIVERED'
               for mo in db.material_orders.values()):
        raise ApiError('ERR_MATERIAL_NOT_DELIVERED', 409, 'No delivered material order')
    if not any(wp['project_id'] == pid and wp['status'] == 'SCHEDULED'
               for wp in db.work_phases.values()):
        raise ApiError('ERR_INVALID_STATE', 409, 'No scheduled work phase')
    project['status'] = 'IN_PRODUCTION'
    touch(project)
    return ok(serialize(project), 'object', 200)


@app.post('/projects/<pid>/cancel')
def cancel_project(pid):
    authorize({'ProjectManager'})
    project = find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    if project['status'] in ('COMPLETED', 'CANCELLED'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Project is terminal')
    if project['status'] in ('CONTRACTED', 'IN_PRODUCTION'):
        for mo in db.material_orders.values():
            if mo['project_id'] == pid and mo['status'] in ('DRAFT', 'PLACED'):
                mo['status'] = 'CANCELLED'
                touch(mo)
        for wp in db.work_phases.values():
            if wp['project_id'] == pid and wp['status'] in ('PLANNED', 'SCHEDULED', 'IN_PROGRESS', 'BLOCKED'):
                wp['status'] = 'CANCELLED'
                touch(wp)
        for dw in db.draws.values():
            if dw['project_id'] == pid and dw['status'] == 'PENDING':
                dw['status'] = 'VOID'
                touch(dw)
    project['status'] = 'CANCELLED'
    touch(project)
    return ok(serialize(project), 'object', 200)


# ===========================================================================
# DesignRevision (PRD 3.2)
# ===========================================================================
@app.post('/design-revisions')
def create_design_revision():
    authorize({'DesignConsultant'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    notes = v_str(b, 'notes', required=False)
    find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    rec = base_record('design_revision', {
        'project_id': project_id, 'revision_round': 1, 'render_url': None,
        'notes': notes, 'status': 'DRAFTING',
    })
    db.design_revisions[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/design-revisions/<did>')
def get_design_revision(did):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.design_revisions, did, 'ERR_DESIGN_REVISION_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/design-revisions')
def list_design_revisions(pid):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.design_revisions.values(), lambda r: r['project_id'] == pid)


@app.post('/design-revisions/<did>/render')
def design_render(did):
    authorize({'DesignConsultant'})
    rec = find(db.design_revisions, did, 'ERR_DESIGN_REVISION_NOT_FOUND')
    if rec['status'] != 'DRAFTING':
        raise ApiError('ERR_INVALID_STATE', 409, 'Revision is not DRAFTING')
    rec['render_url'] = 'https://renders.hardscape.example/%s/round-%d.glb' % (did, rec['revision_round'])
    rec['status'] = 'RENDERED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/design-revisions/<did>/submit-review')
def design_submit_review(did):
    authorize({'DesignConsultant'})
    rec = find(db.design_revisions, did, 'ERR_DESIGN_REVISION_NOT_FOUND')
    if rec['status'] != 'RENDERED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Revision is not RENDERED')
    rec['status'] = 'IN_REVIEW'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/design-revisions/<did>/approve')
def design_approve(did):
    uid, _ = authorize({'Client'})
    rec = find(db.design_revisions, did, 'ERR_DESIGN_REVISION_NOT_FOUND')
    project = db.projects[rec['project_id']]
    check_owner(project, uid)
    if rec['status'] != 'IN_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409, 'Revision is not IN_REVIEW')
    rec['status'] = 'APPROVED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/design-revisions/<did>/request-revision')
def design_request_revision(did):
    uid, _ = authorize({'Client'})
    rec = find(db.design_revisions, did, 'ERR_DESIGN_REVISION_NOT_FOUND')
    project = db.projects[rec['project_id']]
    check_owner(project, uid)
    if rec['status'] != 'IN_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409, 'Revision is not IN_REVIEW')
    rec['status'] = 'REVISION_REQUESTED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/design-revisions/<did>/revise')
def design_revise(did):
    authorize({'DesignConsultant'})
    rec = find(db.design_revisions, did, 'ERR_DESIGN_REVISION_NOT_FOUND')
    if rec['status'] != 'REVISION_REQUESTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Revision is not REVISION_REQUESTED')
    rec['revision_round'] += 1
    rec['render_url'] = None
    rec['status'] = 'DRAFTING'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


# ===========================================================================
# SiteMeasurement (PRD 3.2)
# ===========================================================================
@app.post('/site-measurements')
def create_site_measurement():
    authorize({'DesignConsultant'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    zone_label = v_str(b, 'zone_label')
    measured_sqft = v_num(b, 'measured_sqft', minimum=0)
    wall_height = v_num(b, 'wall_height_in', required=False, default=0, minimum=0)
    find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    rec = base_record('site_measurement', {
        'project_id': project_id, 'zone_label': zone_label,
        'measured_sqft': measured_sqft, 'wall_height_in': wall_height,
    })
    db.site_measurements[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/site-measurements/<sid>')
def get_site_measurement(sid):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin'})
    rec = find(db.site_measurements, sid, 'ERR_SITE_MEASUREMENT_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/site-measurements')
def list_site_measurements(pid):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.site_measurements.values(), lambda r: r['project_id'] == pid)


# ===========================================================================
# LineItem (PRD 3.2)
# ===========================================================================
@app.post('/line-items')
def create_line_item():
    authorize({'DesignConsultant'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    product_id = v_str(b, 'product_id')
    measured_quantity = v_num(b, 'measured_quantity', positive=True)
    find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    product = find(db.products, product_id, 'ERR_PRODUCT_NOT_FOUND')
    rec = base_record('line_item', {
        'project_id': project_id, 'product_id': product_id,
        'category': product['category'], 'measured_quantity': measured_quantity,
        'pinned_unit_price_cents': None, 'installed_quantity': None,
        'origin': 'ORIGINAL',
    })
    db.line_items[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/line-items/<lid>')
def get_line_item(lid):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.line_items, lid, 'ERR_LINE_ITEM_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/line-items')
def list_line_items(pid):
    authorize({'DesignConsultant', 'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.line_items.values(), lambda r: r['project_id'] == pid)


# ===========================================================================
# Permit (PRD 3.4)
# ===========================================================================
@app.get('/permits/<pid>')
def get_permit(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.permits, pid, 'ERR_PERMIT_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/permits')
def list_permits(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.permits.values(), lambda r: r['project_id'] == pid)


@app.post('/permits/<pid>/submit')
def permit_submit(pid):
    authorize({'ProjectManager'})
    rec = find(db.permits, pid, 'ERR_PERMIT_NOT_FOUND')
    if rec['status'] != 'PREPARING':
        raise ApiError('ERR_INVALID_STATE', 409, 'Permit is not PREPARING')
    rec['status'] = 'SUBMITTED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/permits/<pid>/approve')
def permit_approve(pid):
    authorize({'PlatformAdmin'})
    rec = find(db.permits, pid, 'ERR_PERMIT_NOT_FOUND')
    if rec['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Permit is not SUBMITTED')
    rec['permit_number'] = 'PMT-' + uuid.uuid4().hex[:10].upper()
    rec['status'] = 'APPROVED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/permits/<pid>/deny')
def permit_deny(pid):
    authorize({'PlatformAdmin'})
    b = get_body()
    correction_notes = v_str(b, 'correction_notes', required=False)
    rec = find(db.permits, pid, 'ERR_PERMIT_NOT_FOUND')
    if rec['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Permit is not SUBMITTED')
    rec['correction_notes'] = correction_notes
    rec['status'] = 'DENIED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


# ===========================================================================
# HoaSubmission (PRD 3.4)
# ===========================================================================
@app.get('/hoa-submissions/<hid>')
def get_hoa(hid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.hoa_submissions, hid, 'ERR_HOA_SUBMISSION_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/hoa-submissions')
def list_hoa(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.hoa_submissions.values(), lambda r: r['project_id'] == pid)


@app.post('/hoa-submissions/<hid>/submit')
def hoa_submit(hid):
    authorize({'ProjectManager'})
    rec = find(db.hoa_submissions, hid, 'ERR_HOA_SUBMISSION_NOT_FOUND')
    if rec['status'] not in ('DRAFT', 'CONDITIONAL'):
        raise ApiError('ERR_INVALID_STATE', 409, 'HOA submission not in DRAFT/CONDITIONAL')
    rec['status'] = 'SUBMITTED'
    touch(rec)
    return ok(serialize(rec), 'object', 200)


@app.post('/hoa-submissions/<hid>/decide')
def hoa_decide(hid):
    authorize({'PlatformAdmin'})
    b = get_body()
    outcome = v_enum(b, 'outcome', {'APPROVED', 'CONDITIONAL', 'REJECTED'})
    decision_notes = v_str(b, 'decision_notes', required=False)
    conditions = v_str(b, 'conditions', required=False)
    rec = find(db.hoa_submissions, hid, 'ERR_HOA_SUBMISSION_NOT_FOUND')
    if rec['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'HOA submission is not SUBMITTED')
    rec['decision_notes'] = decision_notes
    if outcome == 'CONDITIONAL':
        rec['conditions'] = conditions
    rec['status'] = outcome
    touch(rec)
    return ok(serialize(rec), 'object', 200)


# ===========================================================================
# ChangeOrder (PRD 3.8)
# ===========================================================================
@app.post('/change-orders')
def create_change_order():
    authorize({'ProjectManager'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    description = v_str(b, 'description', required=False)
    add_product_id = v_str(b, 'add_product_id')
    add_qty = v_num(b, 'add_measured_quantity', positive=True)
    add_wall = v_num(b, 'add_wall_height_in', required=False, default=0, minimum=0)
    expected = v_int(b, 'expected_project_version')
    project = find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    find(db.products, add_product_id, 'ERR_PRODUCT_NOT_FOUND')
    if expected != project['version']:
        raise ApiError('ERR_STALE_VERSION', 412, 'expected_project_version is stale')
    rec = base_record('change_order', {
        'project_id': project_id, 'description': description,
        'add_product_id': add_product_id, 'add_measured_quantity': add_qty,
        'add_wall_height_in': add_wall, 'expected_project_version': expected,
        'pricing_method': 'RECOMPUTE', 'price_delta_cents': 0, 'status': 'PROPOSED',
    })
    db.change_orders[rec['id']] = rec
    touch(project)  # ledger touch (PRD 2.4 / 3.8)
    return ok(serialize(rec), 'object', 201)


@app.get('/change-orders/<cid>')
def get_change_order(cid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.change_orders, cid, 'ERR_CHANGE_ORDER_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/change-orders')
def list_change_orders(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.change_orders.values(), lambda r: r['project_id'] == pid)


@app.post('/change-orders/<cid>/approve')
def change_order_approve(cid):
    authorize({'ProjectManager'})
    co = find(db.change_orders, cid, 'ERR_CHANGE_ORDER_NOT_FOUND')
    if co['status'] != 'PROPOSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Change order is not PROPOSED')
    project = db.projects[co['project_id']]
    if project['status'] not in ('CONTRACTED', 'IN_PRODUCTION'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Project not CONTRACTED/IN_PRODUCTION')

    product = db.products[co['add_product_id']]
    permit_required_before = project['permit_required']
    old_value = project['contract_value_cents']

    # Create the added line (origin CHANGE_ORDER, price pinned immediately).
    new_line = base_record('line_item', {
        'project_id': project['id'], 'product_id': product['id'],
        'category': product['category'], 'measured_quantity': co['add_measured_quantity'],
        'pinned_unit_price_cents': product['unit_price_cents'],
        'installed_quantity': None, 'origin': 'CHANGE_ORDER',
    })
    db.line_items[new_line['id']] = new_line

    # RECOMPUTE: whole-project estimate over the enlarged line set.
    new_value, _ = project_valuation(project, 'estimate')
    co['price_delta_cents'] = new_value - old_value
    project['contract_value_cents'] = new_value
    project['balance_due_cents'] = project['contract_value_cents'] - project['amount_paid_cents']
    co['status'] = 'APPROVED'
    touch(co)
    touch(project)  # recompute ledger touch (+1)

    # Permit revert cascade (depth-3): ChangeOrder -> Project -> WorkPhase -> Crew.
    if D(co['add_wall_height_in']) >= 48 and not permit_required_before:
        project['permit_required'] = True
        if not any(p['project_id'] == project['id'] for p in db.permits.values()):
            permit = base_record('permit', {
                'project_id': project['id'], 'permit_number': None, 'fee_cents': 35000,
                'correction_notes': None, 'status': 'PREPARING',
            })
            db.permits[permit['id']] = permit
        project['status'] = 'PENDING_APPROVALS'
        for wp in db.work_phases.values():
            if wp['project_id'] == project['id'] and wp['status'] in ('SCHEDULED', 'IN_PROGRESS'):
                wp['status'] = 'BLOCKED'  # releases crew (booking count recomputed)
                touch(wp)
        touch(project)  # revert ledger touch (+1)

    return ok(serialize(co), 'object', 200)


@app.post('/change-orders/<cid>/reject')
def change_order_reject(cid):
    authorize({'ProjectManager'})
    co = find(db.change_orders, cid, 'ERR_CHANGE_ORDER_NOT_FOUND')
    if co['status'] != 'PROPOSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Change order is not PROPOSED')
    project = db.projects[co['project_id']]
    co['status'] = 'REJECTED'
    touch(co)
    touch(project)  # ledger touch even though no dollar changed (PRD 2.4 / 3.8)
    return ok(serialize(co), 'object', 200)


# ===========================================================================
# MaterialOrder (PRD 3.6)
# ===========================================================================
@app.post('/material-orders')
def create_material_order():
    authorize({'ProjectManager'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    requested_delivery_date = v_date(b, 'requested_delivery_date')
    line_item_ids = v_list(b, 'line_item_ids')
    supplier_ref = v_str(b, 'supplier_ref', required=False)
    project = find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    if len(line_item_ids) == 0:
        raise ApiError('ERR_NO_ORDERABLE_ITEMS', 422, 'line_item_ids is empty')
    for lid in line_item_ids:
        line = db.line_items.get(lid)
        if line is None or line['project_id'] != project_id:
            raise ApiError('ERR_LINE_ITEM_NOT_FOUND', 404, 'line_item not found in project')
    rec = base_record('material_order', {
        'project_id': project_id, 'region_code': project['region_code'],
        'requested_delivery_date': requested_delivery_date,
        'line_item_ids': list(line_item_ids), 'total_pallets': 0,
        'total_sqft_ordered': 0, 'supplier_ref': supplier_ref, 'status': 'DRAFT',
    })
    db.material_orders[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/material-orders/<mid>')
def get_material_order(mid):
    authorize({'ProjectManager', 'PlatformAdmin'})
    rec = find(db.material_orders, mid, 'ERR_MATERIAL_ORDER_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/material-orders')
def list_material_orders(pid):
    authorize({'ProjectManager', 'PlatformAdmin'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.material_orders.values(), lambda r: r['project_id'] == pid)


@app.post('/material-orders/<mid>/place')
def material_order_place(mid):
    authorize({'ProjectManager'})
    order = find(db.material_orders, mid, 'ERR_MATERIAL_ORDER_NOT_FOUND')
    if order['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Material order is not DRAFT')
    project = db.projects[order['project_id']]
    if project['status'] not in ('CONTRACTED', 'IN_PRODUCTION'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Project not CONTRACTED/IN_PRODUCTION')
    occupied = sum(
        1 for mo in db.material_orders.values()
        if mo['id'] != mid and mo['status'] in ('PLACED', 'DELIVERED')
        and mo['region_code'] == order['region_code']
        and mo['requested_delivery_date'] == order['requested_delivery_date']
    )
    if occupied >= 2:
        raise ApiError('ERR_DELIVERY_SLOT_FULL', 409, 'Delivery slot is full')
    total_pallets, total_sqft = material_order_pallets(order)
    order['total_pallets'] = total_pallets
    order['total_sqft_ordered'] = total_sqft
    order['status'] = 'PLACED'
    touch(order)
    return ok(serialize(order), 'object', 200)


@app.post('/material-orders/<mid>/confirm-delivery')
def material_order_confirm(mid):
    authorize({'ProjectManager'})
    order = find(db.material_orders, mid, 'ERR_MATERIAL_ORDER_NOT_FOUND')
    if order['status'] != 'PLACED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Material order is not PLACED')
    order['status'] = 'DELIVERED'
    touch(order)
    return ok(serialize(order), 'object', 200)


# ===========================================================================
# WorkPhase (PRD 3.7)
# ===========================================================================
def _permit_gate(project, phase_type):
    if phase_type == 'WALL_BUILD' and project['permit_required']:
        if not any(p['project_id'] == project['id'] and p['status'] == 'APPROVED'
                   for p in db.permits.values()):
            raise ApiError('ERR_PERMIT_NOT_APPROVED', 409, 'Permit is not APPROVED')


@app.post('/work-phases')
def create_work_phase():
    authorize({'ProjectManager'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    phase_type = v_enum(b, 'phase_type', PHASE_TYPES)
    covered = v_list(b, 'covered_line_item_ids', required=False, default=[])
    sequence_index = v_int(b, 'sequence_index', required=False, default=0)
    is_final = v_bool(b, 'is_final', required=False, default=False)
    find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    for lid in covered:
        line = db.line_items.get(lid)
        if line is None or line['project_id'] != project_id:
            raise ApiError('ERR_LINE_ITEM_NOT_FOUND', 404, 'covered line_item not found in project')
    rec = base_record('work_phase', {
        'project_id': project_id, 'crew_id': None, 'phase_type': phase_type,
        'requires_permit': False, 'covered_line_item_ids': list(covered),
        'sequence_index': sequence_index, 'is_final': is_final,
        'start_date': None, 'end_date': None, 'status': 'PLANNED',
    })
    db.work_phases[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/work-phases/<wid>')
def get_work_phase(wid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.work_phases, wid, 'ERR_WORK_PHASE_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/work-phases')
def list_work_phases(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.work_phases.values(), lambda r: r['project_id'] == pid)


@app.post('/work-phases/<wid>/schedule')
def work_phase_schedule(wid):
    authorize({'ProjectManager'})
    b = get_body()
    crew_id = v_str(b, 'crew_id')
    start_date = v_date(b, 'start_date')
    end_date = v_date(b, 'end_date')
    phase = find(db.work_phases, wid, 'ERR_WORK_PHASE_NOT_FOUND')
    project = db.projects[phase['project_id']]
    if phase['status'] != 'PLANNED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Work phase is not PLANNED')
    if project['status'] not in ('CONTRACTED', 'IN_PRODUCTION'):
        raise ApiError('ERR_INVALID_STATE', 409, 'Project not CONTRACTED/IN_PRODUCTION')
    find(db.crews, crew_id, 'ERR_CREW_NOT_FOUND')
    _permit_gate(project, phase['phase_type'])
    if end_date < start_date:
        raise ApiError('ERR_INVALID_DATE_RANGE', 422, 'end_date before start_date')
    for other in db.work_phases.values():
        if other['id'] == wid:
            continue
        if other['crew_id'] == crew_id and other['status'] in ('SCHEDULED', 'IN_PROGRESS'):
            if other['start_date'] and other['end_date'] \
                    and start_date <= other['end_date'] and other['start_date'] <= end_date:
                raise ApiError('ERR_CREW_DOUBLE_BOOKED', 409, 'Crew is double-booked')
    phase['crew_id'] = crew_id
    phase['start_date'] = start_date
    phase['end_date'] = end_date
    phase['requires_permit'] = (phase['phase_type'] == 'WALL_BUILD' and project['permit_required'])
    phase['status'] = 'SCHEDULED'
    touch(phase)
    return ok(serialize(phase), 'object', 200)


@app.post('/work-phases/<wid>/start')
def work_phase_start(wid):
    authorize({'ProjectManager'})
    phase = find(db.work_phases, wid, 'ERR_WORK_PHASE_NOT_FOUND')
    project = db.projects[phase['project_id']]
    if phase['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Work phase is not SCHEDULED')
    if project['status'] != 'IN_PRODUCTION':
        raise ApiError('ERR_INVALID_STATE', 409, 'Project is not IN_PRODUCTION')
    _permit_gate(project, phase['phase_type'])
    phase['status'] = 'IN_PROGRESS'
    touch(phase)
    return ok(serialize(phase), 'object', 200)


@app.post('/work-phases/<wid>/complete')
def work_phase_complete(wid):
    authorize({'ProjectManager'})
    b = get_body()
    installed = b.get('installed_quantities')
    if installed is None:
        installed = {}
    if not isinstance(installed, dict):
        raise ApiError('ERR_INVALID_REQUEST', 422, 'installed_quantities must be an object')
    phase = find(db.work_phases, wid, 'ERR_WORK_PHASE_NOT_FOUND')
    if phase['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409, 'Work phase is not IN_PROGRESS')
    project = db.projects[phase['project_id']]

    for lid in phase['covered_line_item_ids']:
        if lid in installed:
            line = db.line_items.get(lid)
            if line is not None:
                line['installed_quantity'] = installed[lid]
                touch(line)
    phase['status'] = 'COMPLETED'  # leaving IN_PROGRESS releases the crew booking
    touch(phase)

    if phase['is_final'] and project['status'] == 'IN_PRODUCTION':
        _complete_project(project)

    return ok(serialize(phase), 'object', 200)


def _complete_project(project):
    total, _ = project_valuation(project, 'as_built')
    project['final_billed_total_cents'] = total
    retention = base_record('draw', {
        'project_id': project['id'], 'work_phase_id': None,
        'draw_type': 'RETENTION_RELEASE',
        'amount_cents': rhu(D(project['contract_value_cents']) * D('0.05')),
        'expected_project_version': None, 'status': 'PENDING',
    })
    db.draws[retention['id']] = retention
    start = db.clock_dt
    end = start + timedelta(days=365)
    project['warranty_start_date'] = iso_millis(start)
    project['warranty_end_date'] = iso_millis(end)
    project['_warranty_end_dt'] = end
    project['status'] = 'COMPLETED'
    touch(project)


# ===========================================================================
# ProgressDraw (PRD 3.7)
# ===========================================================================
@app.post('/draws')
def create_draw():
    authorize({'ProjectManager'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    draw_type = v_enum(b, 'draw_type', {'DEPOSIT', 'PROGRESS'})
    amount = v_int(b, 'amount_cents', positive=True)
    work_phase_id = v_str(b, 'work_phase_id', required=False)
    expected = v_int(b, 'expected_project_version')
    project = find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    if work_phase_id is not None:
        wp = find(db.work_phases, work_phase_id, 'ERR_WORK_PHASE_NOT_FOUND')
        if wp['project_id'] != project_id:
            raise ApiError('ERR_WORK_PHASE_NOT_FOUND', 404, 'work_phase not in project')
    # Fiscal limits (tier 10) before OCC (tier 11).
    if draw_type == 'DEPOSIT':
        if amount > deposit_cap(project):
            raise ApiError('ERR_DEPOSIT_EXCEEDS_CAP', 422, 'Deposit exceeds cap')
    else:  # PROGRESS
        if amount > project['balance_due_cents']:
            raise ApiError('ERR_DRAW_EXCEEDS_BALANCE', 422, 'Progress draw exceeds balance due')
    if expected != project['version']:
        raise ApiError('ERR_STALE_VERSION', 412, 'expected_project_version is stale')
    rec = base_record('draw', {
        'project_id': project_id, 'work_phase_id': work_phase_id,
        'draw_type': draw_type, 'amount_cents': amount,
        'expected_project_version': expected, 'status': 'PENDING',
    })
    db.draws[rec['id']] = rec
    touch(project)  # ledger touch (PRD 2.4)
    return ok(serialize(rec), 'object', 201)


@app.get('/draws/<did>')
def get_draw(did):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.draws, did, 'ERR_DRAW_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/draws')
def list_draws(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.draws.values(), lambda r: r['project_id'] == pid)


@app.get('/work-phases/<wid>/draws')
def list_work_phase_draws(wid):
    authorize({'ProjectManager', 'PlatformAdmin'})
    find(db.work_phases, wid, 'ERR_WORK_PHASE_NOT_FOUND')
    return list_response(db.draws.values(), lambda r: r['work_phase_id'] == wid)


@app.post('/draws/<did>/record-payment')
def draw_record_payment(did):
    authorize({'ProjectManager'})
    draw = find(db.draws, did, 'ERR_DRAW_NOT_FOUND')
    if draw['status'] != 'PENDING':
        raise ApiError('ERR_INVALID_STATE', 409, 'Draw is not PENDING')
    project = db.projects[draw['project_id']]
    draw['status'] = 'PAID'
    touch(draw)
    project['amount_paid_cents'] += draw['amount_cents']
    project['balance_due_cents'] = project['contract_value_cents'] - project['amount_paid_cents']
    touch(project)
    return ok(serialize(draw), 'object', 200)


@app.post('/draws/<did>/refund')
def draw_refund(did):
    authorize({'ProjectManager'})
    draw = find(db.draws, did, 'ERR_DRAW_NOT_FOUND')
    if draw['status'] != 'PAID':
        raise ApiError('ERR_INVALID_STATE', 409, 'Draw is not PAID')
    project = db.projects[draw['project_id']]
    draw['status'] = 'REFUNDED'
    touch(draw)
    project['amount_paid_cents'] -= draw['amount_cents']
    project['balance_due_cents'] = project['contract_value_cents'] - project['amount_paid_cents']
    touch(project)
    return ok(serialize(draw), 'object', 200)


# ===========================================================================
# WarrantyClaim (PRD 3.9)
# ===========================================================================
@app.post('/warranty-claims')
def create_warranty_claim():
    uid, _ = authorize({'Client'})
    b = get_body()
    project_id = v_str(b, 'project_id')
    claim_category = v_enum(b, 'claim_category', {'WORKMANSHIP', 'MATERIAL', 'SETTLEMENT'})
    description = v_str(b, 'description', required=False)
    project = find(db.projects, project_id, 'ERR_PROJECT_NOT_FOUND')
    check_owner(project, uid)
    if project['status'] != 'COMPLETED':
        raise ApiError('ERR_NOT_COMPLETED', 409, 'Project is not COMPLETED')
    if project.get('_warranty_end_dt') is not None and db.clock_dt > project['_warranty_end_dt']:
        raise ApiError('ERR_WARRANTY_WINDOW_CLOSED', 409, 'Warranty window is closed')
    rec = base_record('warranty_claim', {
        'project_id': project_id, 'claim_category': claim_category,
        'description': description, 'filed_at': iso_millis(db.clock_dt), 'status': 'FILED',
    })
    db.warranty_claims[rec['id']] = rec
    return ok(serialize(rec), 'object', 201)


@app.get('/warranty-claims/<wid>')
def get_warranty_claim(wid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    rec = find(db.warranty_claims, wid, 'ERR_WARRANTY_CLAIM_NOT_FOUND')
    return ok(serialize(rec), 'object', 200)


@app.get('/projects/<pid>/warranty-claims')
def list_warranty_claims(pid):
    authorize({'ProjectManager', 'PlatformAdmin', 'Client'})
    find(db.projects, pid, 'ERR_PROJECT_NOT_FOUND')
    return list_response(db.warranty_claims.values(), lambda r: r['project_id'] == pid)


@app.post('/warranty-claims/<wid>/decide')
def warranty_claim_decide(wid):
    authorize({'PlatformAdmin'})
    b = get_body()
    outcome = v_enum(b, 'outcome', {'APPROVED', 'DENIED'})
    v_str(b, 'resolution_notes', required=False)  # accepted, not persisted
    rec = find(db.warranty_claims, wid, 'ERR_WARRANTY_CLAIM_NOT_FOUND')
    if rec['status'] != 'FILED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Warranty claim is not FILED')
    rec['status'] = outcome
    touch(rec)
    return ok(serialize(rec), 'object', 200)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
