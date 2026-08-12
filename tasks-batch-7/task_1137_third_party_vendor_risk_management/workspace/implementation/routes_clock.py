"""Logical-clock test-driving endpoints (PRD §2.8)."""
from core import (app, auth, contracts, cycles, engagements, err, fmt_rt,
                  get_body, mutate, now, ok, parse_dt, recompute_vendor,
                  set_clock, vendors)

CLOCK_READERS = ('PlatformAdmin', 'RiskOfficer', 'ComplianceDirector',
                 'VendorRelationshipManager', 'InternalAuditor',
                 'BusinessUnitOwner')


@app.route('/tprm/_clock/set_current_utc', methods=['POST'])
@auth('PlatformAdmin')
def set_current_utc():
    body = get_body()
    target = parse_dt(body.get('to_iso8601'))
    if target is None:
        err('ERR_INVALID_REQUEST', 400,
            'to_iso8601 is required and must be an ISO 8601 datetime.')
    set_clock(target)
    t = now()
    # Monitoring-cycle OVERDUE promotion (due_at strictly earlier than now).
    affected = set()
    for c in cycles.values():
        if c['status'] in ('SCHEDULED', 'IN_PROGRESS') and c['due_at'] < t:
            mutate(c, status='OVERDUE')
            affected.add(c['vendor_id'])
    # Contract EXPIRED promotion (engagement no longer ACTIVE).
    for c in contracts.values():
        if c['status'] == 'EXECUTED' and c['expiry_date'] <= t:
            e = engagements.get(c['engagement_id'])
            if e is not None and e['lifecycle_status'] in (
                    'EXITING', 'EXITED', 'TERMINATED_FOR_CAUSE'):
                mutate(c, status='EXPIRED')
    for vid in affected:
        recompute_vendor(vendors[vid])
    return ok({'new_current_utc': fmt_rt(t)})


@app.route('/tprm/_clock/current_utc', methods=['GET'])
@auth(*CLOCK_READERS)
def get_current_utc():
    return ok({'current_utc': fmt_rt(now())})
