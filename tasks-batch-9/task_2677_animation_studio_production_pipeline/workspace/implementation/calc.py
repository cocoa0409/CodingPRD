"""Derived values: earned value, budget position, partner quality, render cost and
admission, asset reuse credit, plus every entity serializer.

All money is an integer count of cents; every non-integer intermediate is rounded
with ROUND_HALF_UP.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from store import by_created, created_key, db, iso, now, touch

# ------------------------------------------------------------------- constants
LABOR_RATE_CENTS_PER_HOUR = Decimal('9000')

STAGES = ('LAYOUT', 'ANIMATION', 'EFFECTS', 'LIGHTING', 'COMP')
STAGE_WEIGHT_PCT = {
    'LAYOUT': Decimal('0.10'),
    'ANIMATION': Decimal('0.40'),
    'EFFECTS': Decimal('0.15'),
    'LIGHTING': Decimal('0.15'),
    'COMP': Decimal('0.20'),
}

TIER_WEIGHT = {
    'TIER1': Decimal('1.0'),
    'TIER2': Decimal('1.5'),
    'TIER3': Decimal('2.0'),
}
NEUTRAL_DEFAULT = Decimal('50.00')
ROLLING_WINDOW_DAYS = 90

PRIORITY_MULTIPLIER = {
    'LOW': Decimal('0.80'),
    'NORMAL': Decimal('1.00'),
    'HIGH': Decimal('1.35'),
    'CRITICAL': Decimal('1.75'),
}
HEADROOM_PCT = {
    'LOW': Decimal('0.20'),
    'NORMAL': Decimal('0.10'),
    'HIGH': Decimal('0.00'),
    'CRITICAL': Decimal('0.00'),
}
PRIORITIES = ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')

OVERHEAD_TIER_1_CEILING_CENTS = 5000000
OVERHEAD_TIER_2_CEILING_CENTS = 20000000
OVERHEAD_RATE_TIER_1 = Decimal('0.15')
OVERHEAD_RATE_TIER_2 = Decimal('0.12')
OVERHEAD_RATE_TIER_3 = Decimal('0.10')

RETAKE_ESCALATION_THRESHOLD = 3

REUSE_DISCOUNT_PCT = {
    1: Decimal('0.40'),
    2: Decimal('0.25'),
}
REUSE_DISCOUNT_PCT_DEPTH_3_PLUS = Decimal('0.10')
MAX_CHAIN_DEPTH = 8

SECURITY_LEVELS = ('NONE', 'TIER1', 'TIER2', 'TIER3')
COLOR_SPACES = ('ACEScg', 'LogC', 'Rec709', 'sRGB')
GATE_TYPES = ('SCRIPT', 'STORYBOARD', 'ANIMATIC', 'DESIGN')
PHASES = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE', 'DELIVERY', 'WRAPPED')
BUILD_CHAIN = ('BRIEFED', 'MODELING', 'RIGGING', 'SURFACING', 'PUBLISHED')


# ------------------------------------------------------------ decimal helpers
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def rh_int(value):
    return int(round_half_up(value, 0))


def f2(value):
    if value is None:
        return None
    return float(round_half_up(value, 2))


def f4(value):
    if value is None:
        return None
    return float(round_half_up(value, 4))


def num(value):
    """Serialize a stored Decimal as a JSON number preserving its scale."""
    if value is None:
        return None
    return float(value)


def ceil_int(value):
    return int(D(value).quantize(Decimal('1'), rounding=ROUND_CEILING))


def ratio4(numerator, denominator):
    if denominator == 0:
        return None
    return round_half_up(D(numerator) / D(denominator), 4)


def whole_days(later, earlier):
    delta = (later - earlier).total_seconds()
    if delta < 0:
        return -int((-delta) // 86400) - (1 if (-delta) % 86400 else 0)
    return int(delta // 86400)


# ------------------------------------------------------------- graph helpers
def shot_tasks(shot):
    rows = [t for t in db.tasks.values() if t['shot_id'] == shot['id']]
    rows.sort(key=lambda t: t['stage_order'])
    return rows


def production_shots(production):
    return [s for s in db.shots.values() if s['production_id'] == production['id']]


def production_of(row):
    return db.productions.get(row.get('production_id'))


def shot_of_task(task):
    return db.shots.get(task['shot_id'])


def production_of_task(task):
    shot = shot_of_task(task)
    if shot is None:
        return None
    return db.productions.get(shot['production_id'])


def pool_jobs(pool_id, status=None):
    rows = [j for j in db.jobs.values() if j['render_pool_id'] == pool_id]
    if status is not None:
        rows = [j for j in rows if j['status'] == status]
    return rows


def task_jobs(task_id):
    return [j for j in db.jobs.values() if j['shot_stage_task_id'] == task_id]


# ------------------------------------------------------------ shot earned value
def shot_bcws_cents(shot):
    """Schedule-driven planned value; reads the logical clock on every call."""
    span = (shot['planned_finish_at'] - shot['planned_start_at']).total_seconds()
    if span <= 0:
        return 0
    elapsed = (now() - shot['planned_start_at']).total_seconds()
    fraction = D(elapsed) / D(span)
    if fraction < 0:
        fraction = Decimal('0')
    if fraction > 1:
        fraction = Decimal('1')
    return rh_int(D(shot['budget_cents']) * fraction)


def shot_logged_hours(tasks):
    total = Decimal('0')
    for task in tasks:
        total += D(task['actual_hours'])
    return total


def shot_labor_cost_cents(tasks):
    return rh_int(shot_logged_hours(tasks) * LABOR_RATE_CENTS_PER_HOUR)


def shot_bcwp_stage_weight(shot, tasks):
    weight = Decimal('0')
    for task in tasks:
        if task['status'] == 'APPROVED':
            weight += STAGE_WEIGHT_PCT[task['stage']]
    return rh_int(D(shot['budget_cents']) * weight)


def shot_bcwp_hours_progress(shot, tasks):
    actual = Decimal('0')
    budgeted = Decimal('0')
    for task in tasks:
        actual += D(task['actual_hours'])
        budgeted += D(task['budgeted_hours'])
    if budgeted == 0:
        fraction = Decimal('0')
    else:
        fraction = actual / budgeted
    if fraction < 0:
        fraction = Decimal('0')
    if fraction > 1:
        fraction = Decimal('1')
    return rh_int(D(shot['budget_cents']) * fraction)


def shot_render_committed_cents(tasks):
    total = 0
    ids = set(t['id'] for t in tasks)
    for job in db.jobs.values():
        if job['shot_stage_task_id'] in ids and job['status'] == 'RESERVED':
            total += job['estimated_cost_cents'] or 0
    return total


def shot_render_actual_cents(tasks):
    total = 0
    ids = set(t['id'] for t in tasks)
    for job in db.jobs.values():
        if job['shot_stage_task_id'] in ids and job['status'] in ('COMPLETED', 'FAILED'):
            total += job['final_cost_cents'] or 0
    return total


def derive_shot_status(shot, tasks, production):
    if production is not None and production['phase'] == 'PRE_PRODUCTION':
        return 'BLOCKED_PREPROD'
    if tasks and all(t['status'] == 'APPROVED' for t in tasks):
        return 'COMPLETE'
    if any(t['status'] != 'NOT_STARTED' for t in tasks):
        return 'IN_PRODUCTION'
    return 'READY'


def derive_current_stage(tasks):
    for task in sorted(tasks, key=lambda t: t['stage_order']):
        if task['status'] != 'APPROVED':
            return task['stage']
    return None


def recompute_shot(shot, production=None):
    """Reconcile every stored derived field of a shot. Clock-driven values
    (bcws_cents, spi) are not stored: they are derived on every read."""
    if production is None:
        production = db.productions.get(shot['production_id'])
    tasks = shot_tasks(shot)
    new = {
        'labor_cost_cents': shot_labor_cost_cents(tasks),
        'render_cost_committed_cents': shot_render_committed_cents(tasks),
        'render_cost_actual_cents': shot_render_actual_cents(tasks),
        'bcwp_cents': shot_bcwp_stage_weight(shot, tasks),
        'retake_count': sum(t['revision_count'] for t in tasks),
        'escalation_flag': any(t['escalated'] for t in tasks),
        'status': derive_shot_status(shot, tasks, production),
        'current_stage': derive_current_stage(tasks),
    }
    new['acwp_cents'] = new['labor_cost_cents'] + new['render_cost_actual_cents']
    new['cpi'] = ratio4(new['bcwp_cents'], new['acwp_cents'])
    changed = False
    for key, value in new.items():
        if shot.get(key) != value:
            shot[key] = value
            changed = True
    if changed:
        touch(shot)
    return changed


# --------------------------------------------------- production budget position
def overhead_rate_for(direct_cents):
    if direct_cents < OVERHEAD_TIER_1_CEILING_CENTS:
        return OVERHEAD_RATE_TIER_1
    if direct_cents < OVERHEAD_TIER_2_CEILING_CENTS:
        return OVERHEAD_RATE_TIER_2
    return OVERHEAD_RATE_TIER_3


def spend_ceiling_cents(production):
    return rh_int(D(production['budget_cents']) * (Decimal('1') + D(production['contingency_pct'])))


def production_package_fees(production):
    total = 0
    for pkg in db.packages.values():
        if pkg['production_id'] != production['id']:
            continue
        if pkg['status'] in ('IN_PROGRESS', 'DELIVERED', 'QC_PASSED', 'QC_FAILED'):
            total += pkg['fee_committed_cents']
    return total


def production_labor_cents(shots):
    """Per-task rounding, then summed (deliberately different from the shot-level
    figure, which rounds the summed hours once)."""
    total = 0
    for shot in shots:
        for task in shot_tasks(shot):
            total += rh_int(D(task['actual_hours']) * LABOR_RATE_CENTS_PER_HOUR)
    return total


def budget_position(production, extra_package_fee_cents=0):
    """Steps one through three of PRD 2.8. Returns the four figures."""
    shots = production_shots(production)
    render_actual = sum(s['render_cost_actual_cents'] for s in shots)
    direct = (production_package_fees(production) + extra_package_fee_cents
              + production_labor_cents(shots) + render_actual)
    overhead = rh_int(D(direct) * overhead_rate_for(direct))
    total = direct + overhead
    ceiling = spend_ceiling_cents(production)
    return {
        'direct_committed_cents': direct,
        'overhead_fee_cents': overhead,
        'total_committed_cents': total,
        'available_cents': ceiling - total,
    }


def recompute_production(production):
    shots = production_shots(production)
    new = {
        'shot_count': len(shots),
        'completed_shot_count': sum(1 for s in shots if s['status'] == 'COMPLETE'),
        'at_risk_shot_count': sum(1 for s in shots if s['escalation_flag']),
        'total_retake_count': sum(s['retake_count'] for s in shots),
        'render_committed_cents': sum(s['render_cost_committed_cents'] for s in shots),
        'render_actual_cents': sum(s['render_cost_actual_cents'] for s in shots),
        'bcwp_cents': sum(s['bcwp_cents'] for s in shots),
        'acwp_cents': sum(s['acwp_cents'] for s in shots),
    }
    new['cpi'] = ratio4(new['bcwp_cents'], new['acwp_cents'])
    new.update(budget_position(production))
    changed = False
    for key, value in new.items():
        if production.get(key) != value:
            production[key] = value
            changed = True
    if changed:
        touch(production)
    return changed


def production_bcws_cents(production):
    return sum(shot_bcws_cents(s) for s in production_shots(production))


def reconcile_shot(shot):
    """Recompute a shot and then the production above it."""
    production = db.productions.get(shot['production_id'])
    recompute_shot(shot, production)
    if production is not None:
        recompute_production(production)


def reconcile_shots(shots):
    seen = set()
    productions = []
    for shot in shots:
        if shot['id'] in seen:
            continue
        seen.add(shot['id'])
        production = db.productions.get(shot['production_id'])
        recompute_shot(shot, production)
        if production is not None and production['id'] not in [p['id'] for p in productions]:
            productions.append(production)
    for production in productions:
        recompute_production(production)


# ------------------------------------------------------------- partner quality
def partner_packages(partner_id):
    return [p for p in db.packages.values() if p['partner_id'] == partner_id]


def rolling_decay(age_days):
    if age_days <= 30:
        return Decimal('1.00')
    if age_days <= 60:
        return Decimal('0.75')
    if age_days <= ROLLING_WINDOW_DAYS:
        return Decimal('0.50')
    return None


def partner_quality_score(partner, variant='ROLLING_90D'):
    numerator = Decimal('0')
    denominator = Decimal('0')
    clock = now()
    for pkg in partner_packages(partner['id']):
        if pkg['status'] not in ('QC_PASSED', 'QC_FAILED'):
            continue
        if pkg['qc_decided_at'] is None:
            continue
        weight = TIER_WEIGHT[pkg['security_tier']]
        if variant == 'ROLLING_90D':
            decay = rolling_decay(whole_days(clock, pkg['qc_decided_at']))
            if decay is None:
                continue
            weight = weight * decay
        numerator += D(pkg['qc_score']) * weight
        denominator += weight
    if denominator == 0:
        return NEUTRAL_DEFAULT
    return round_half_up(numerator / denominator, 2)


def partner_qc_decided_count(partner):
    total = 0
    for pkg in partner_packages(partner['id']):
        if pkg['qc_decided_at'] is not None:
            total += 1
    return total


# ------------------------------------------------------------------ render cost
def cost_per_frame_cents(pool, requested_cores, seconds_per_frame, priority):
    core_seconds_per_frame = D(requested_cores) * D(seconds_per_frame)
    raw = (D(pool['cost_per_core_hour_cents']) * core_seconds_per_frame / D(3600)
           * PRIORITY_MULTIPLIER[priority])
    return rh_int(raw)


def committed_core_hours(requested_cores, window_start, window_end):
    hours = D((window_end - window_start).total_seconds()) / D(3600)
    return round_half_up(D(requested_cores) * hours, 2)


def usable_ceiling(pool, priority):
    headroom = ceil_int(D(pool['total_cores']) * HEADROOM_PCT[priority])
    return pool['total_cores'] - headroom


def intersects(job, window_start, window_end):
    return job['window_start'] < window_end and job['window_end'] > window_start


def peak_usage(jobs, window_start, window_end):
    overlapping = [j for j in jobs if intersects(j, window_start, window_end)]
    if not overlapping:
        return 0
    instants = [window_start]
    for job in overlapping:
        if job['window_start'] >= window_start:
            instants.append(job['window_start'])
    peak = 0
    for instant in instants:
        used = 0
        for job in overlapping:
            if job['window_start'] <= instant < job['window_end']:
                used += job['requested_cores']
        if used > peak:
            peak = used
    return peak


def plan_admission(pool, priority, requested_cores, window_start, window_end):
    """All-or-nothing admission. Returns (admitted, victims) without mutating
    anything: the victims are only committed when the whole admission succeeds."""
    ceiling = usable_ceiling(pool, priority)
    reserved = pool_jobs(pool['id'], 'RESERVED')
    peak = peak_usage(reserved, window_start, window_end)
    if requested_cores <= ceiling - peak:
        return True, []
    if priority != 'CRITICAL':
        return False, []
    eligible = [j for j in reserved
                if j['priority'] in ('LOW', 'NORMAL')
                and intersects(j, window_start, window_end)]
    eligible.sort(key=lambda j: (0 if j['priority'] == 'LOW' else 1,
                                 -j['requested_cores'],
                                 created_key(j)))
    victims = []
    victim_ids = set()
    for job in eligible:
        victims.append(job)
        victim_ids.add(job['id'])
        remaining = [j for j in reserved if j['id'] not in victim_ids]
        peak = peak_usage(remaining, window_start, window_end)
        if requested_cores <= ceiling - peak:
            return True, victims
    return False, []


def recompute_pool(pool):
    reserved = pool_jobs(pool['id'], 'RESERVED')
    total = Decimal('0')
    for job in reserved:
        total += D(job['committed_core_hours'])
    new_hours = round_half_up(total, 2)
    new_count = len(reserved)
    if pool['committed_core_hours'] != new_hours or pool['reserved_job_count'] != new_count:
        pool['committed_core_hours'] = new_hours
        pool['reserved_job_count'] = new_count
    return new_hours, new_count


# ------------------------------------------------------------- asset reuse credit
def walk_chain(start_source_id, seed_visited=None):
    """Walk derived_from_asset_id upward from start_source_id.

    Returns (depth, error) where error is None, 'CYCLE' or 'TOO_LONG'.
    depth counts the edges from the owning asset up to the chain root.
    """
    visited = set(seed_visited or ())
    depth = 0
    current = start_source_id
    while current is not None:
        if current in visited:
            return depth, 'CYCLE'
        visited.add(current)
        depth += 1
        row = db.assets.get(current)
        if row is None:
            return depth, None
        current = row.get('derived_from_asset_id')
        if depth > MAX_CHAIN_DEPTH + 1:
            break
    if depth > MAX_CHAIN_DEPTH:
        return depth, 'TOO_LONG'
    return depth, None


def chain_ancestors(asset):
    """Ancestor rows of an asset, nearest first."""
    rows = []
    seen = {asset['id']}
    current = asset.get('derived_from_asset_id')
    while current is not None and current not in seen:
        seen.add(current)
        row = db.assets.get(current)
        if row is None:
            break
        rows.append(row)
        current = row.get('derived_from_asset_id')
    return rows


def asset_reuse_depth(asset):
    return len(chain_ancestors(asset))


def recompute_asset_credit(asset):
    """reuse_depth, reuse_discount_pct and effective_complexity_points from the
    asset's current chain and reuse_source_stale flag."""
    ancestors = chain_ancestors(asset)
    depth = len(ancestors)
    if depth == 0:
        pct = Decimal('0.00')
    elif ancestors[0]['library_status'] != 'LIBRARY_APPROVED':
        pct = Decimal('0.00')
    elif asset['reuse_source_stale']:
        pct = Decimal('0.00')
    elif depth in REUSE_DISCOUNT_PCT:
        pct = REUSE_DISCOUNT_PCT[depth]
    else:
        pct = REUSE_DISCOUNT_PCT_DEPTH_3_PLUS
    effective = round_half_up(D(asset['base_complexity_points']) * (Decimal('1') - pct), 2)
    changed = False
    if asset.get('reuse_depth') != depth:
        asset['reuse_depth'] = depth
        changed = True
    if asset.get('reuse_discount_pct') != pct:
        asset['reuse_discount_pct'] = pct
        changed = True
    if asset.get('effective_complexity_points') != effective:
        asset['effective_complexity_points'] = effective
        changed = True
    return changed


def asset_credit_view(asset):
    """The reuse credit as read: the chain is walked on every read rather than
    cached, so an ancestor's library approval is visible to a descendant without
    any write to the descendant's row."""
    ancestors = chain_ancestors(asset)
    depth = len(ancestors)
    if depth == 0:
        pct = Decimal('0.00')
    elif ancestors[0]['library_status'] != 'LIBRARY_APPROVED':
        pct = Decimal('0.00')
    elif asset['reuse_source_stale']:
        pct = Decimal('0.00')
    elif depth in REUSE_DISCOUNT_PCT:
        pct = REUSE_DISCOUNT_PCT[depth]
    else:
        pct = REUSE_DISCOUNT_PCT_DEPTH_3_PLUS
    effective = round_half_up(D(asset['base_complexity_points']) * (Decimal('1') - pct), 2)
    return depth, pct, effective


def chain_contains(asset, ancestor_id):
    return any(a['id'] == ancestor_id for a in chain_ancestors(asset))


def chain_descendants(asset):
    """Every asset whose derived_from chain contains this asset, oldest first."""
    rows = [a for a in db.assets.values()
            if a['id'] != asset['id'] and chain_contains(a, asset['id'])]
    return by_created(rows)


def chain_stale(asset):
    return any(a['library_status'] == 'LIBRARY_DEPRECATED' for a in chain_ancestors(asset))


# ------------------------------------------------------- deliverable versioning
def deliverable_group(production_id, deliverable_type, shot_id):
    return [d for d in db.deliverables.values()
            if d['production_id'] == production_id
            and d['deliverable_type'] == deliverable_type
            and d['shot_id'] == shot_id]


def version_label(index):
    text = str(index)
    if len(text) < 2:
        text = text.rjust(2, '0')
    return 'v' + text


# ----------------------------------------------------------------- room helpers
def calibration_status(room):
    if room['last_calibrated_at'] is None:
        return 'UNCALIBRATED'
    age_days = whole_days(now(), room['last_calibrated_at'])
    if age_days > room['calibration_valid_days']:
        return 'EXPIRED'
    return 'CALIBRATED'


def session_notes(session):
    return by_created([n for n in db.notes.values()
                       if n['review_session_id'] == session['id']])


def recompute_note_count(session):
    count = len(session_notes(session))
    if session['note_count'] != count:
        session['note_count'] = count
        return True
    return False


# ------------------------------------------------------------------ serializers
def _common(row):
    return {
        'id': row['id'],
        'created_at': iso(row['created_at']),
        'updated_at': iso(row['updated_at']),
        'version': row['version'],
    }


def production_out(production):
    out = _common(production)
    bcws = production_bcws_cents(production)
    out.update({
        'title': production['title'],
        'production_code': production['production_code'],
        'format': production['format'],
        'phase': production['phase'],
        'budget_cents': production['budget_cents'],
        'contingency_pct': num(production['contingency_pct']),
        'render_allowance_cents': production['render_allowance_cents'],
        'master_color_space': production['master_color_space'],
        'approved_color_spaces': list(production['approved_color_spaces']),
        'gate_types': list(production['gate_types']),
        'shot_count': production['shot_count'],
        'completed_shot_count': production['completed_shot_count'],
        'at_risk_shot_count': production['at_risk_shot_count'],
        'total_retake_count': production['total_retake_count'],
        'direct_committed_cents': production['direct_committed_cents'],
        'overhead_fee_cents': production['overhead_fee_cents'],
        'total_committed_cents': production['total_committed_cents'],
        'available_cents': production['available_cents'],
        'render_committed_cents': production['render_committed_cents'],
        'render_actual_cents': production['render_actual_cents'],
        'bcwp_cents': production['bcwp_cents'],
        'bcws_cents': bcws,
        'acwp_cents': production['acwp_cents'],
        'cpi': num(production['cpi']),
        'spi': num(ratio4(production['bcwp_cents'], bcws)),
    })
    return out


def gate_out(gate):
    out = _common(gate)
    out.update({
        'production_id': gate['production_id'],
        'gate_type': gate['gate_type'],
        'sequence_index': gate['sequence_index'],
        'status': gate['status'],
        'revision_count': gate['revision_count'],
        'package_url': gate['package_url'],
        'submitted_by_user_id': gate['submitted_by_user_id'],
        'decided_by_user_id': gate['decided_by_user_id'],
        'decided_at': iso(gate['decided_at']),
    })
    return out


def asset_out(asset):
    out = _common(asset)
    depth, pct, effective = asset_credit_view(asset)
    out.update({
        'production_id': asset['production_id'],
        'derived_from_asset_id': asset['derived_from_asset_id'],
        'asset_code': asset['asset_code'],
        'asset_type': asset['asset_type'],
        'build_status': asset['build_status'],
        'library_status': asset['library_status'],
        'base_complexity_points': num(asset['base_complexity_points']),
        'reuse_depth': depth,
        'reuse_discount_pct': num(pct),
        'effective_complexity_points': num(effective),
        'reuse_source_stale': asset['reuse_source_stale'],
        'library_submitted_by_user_id': asset['library_submitted_by_user_id'],
        'library_decided_by_user_id': asset['library_decided_by_user_id'],
    })
    return out


def shot_out(shot):
    out = _common(shot)
    bcws = shot_bcws_cents(shot)
    out.update({
        'production_id': shot['production_id'],
        'shot_code': shot['shot_code'],
        'sequence_code': shot['sequence_code'],
        'frame_count': shot['frame_count'],
        'difficulty_factor': num(shot['difficulty_factor']),
        'budget_cents': shot['budget_cents'],
        'planned_start_at': iso(shot['planned_start_at']),
        'planned_finish_at': iso(shot['planned_finish_at']),
        'status': shot['status'],
        'current_stage': shot['current_stage'],
        'retake_count': shot['retake_count'],
        'escalation_flag': shot['escalation_flag'],
        'labor_cost_cents': shot['labor_cost_cents'],
        'render_cost_committed_cents': shot['render_cost_committed_cents'],
        'render_cost_actual_cents': shot['render_cost_actual_cents'],
        'bcwp_cents': shot['bcwp_cents'],
        'bcws_cents': bcws,
        'acwp_cents': shot['acwp_cents'],
        'cpi': num(shot['cpi']),
        'spi': num(ratio4(shot['bcwp_cents'], bcws)),
    })
    return out


def task_out(task):
    out = _common(task)
    out.update({
        'shot_id': task['shot_id'],
        'outsource_package_id': task['outsource_package_id'],
        'stage': task['stage'],
        'stage_order': task['stage_order'],
        'stage_weight_pct': num(task['stage_weight_pct']),
        'status': task['status'],
        'budgeted_hours': num(task['budgeted_hours']),
        'actual_hours': num(task['actual_hours']),
        'revision_count': task['revision_count'],
        'escalated': task['escalated'],
        'assigned_artist_user_id': task['assigned_artist_user_id'],
        'submitted_by_user_id': task['submitted_by_user_id'],
        'reviewed_by_user_id': task['reviewed_by_user_id'],
        'submitted_at': iso(task['submitted_at']),
        'approved_at': iso(task['approved_at']),
    })
    return out


def room_out(room):
    out = _common(room)
    out.update({
        'name': room['name'],
        'seat_capacity': room['seat_capacity'],
        'turnover_buffer_minutes': room['turnover_buffer_minutes'],
        'room_color_space': room['room_color_space'],
        'calibration_valid_days': room['calibration_valid_days'],
        'last_calibrated_at': iso(room['last_calibrated_at']),
        'calibration_status': calibration_status(room),
    })
    return out


def session_out(session):
    out = _common(session)
    out.update({
        'production_id': session['production_id'],
        'screening_room_id': session['screening_room_id'],
        'session_type': session['session_type'],
        'window_start': iso(session['window_start']),
        'window_end': iso(session['window_end']),
        'attendee_count': session['attendee_count'],
        'status': session['status'],
        'opened_at': iso(session['opened_at']),
        'closed_at': iso(session['closed_at']),
        'note_count': session['note_count'],
        'retake_issued_count': session['retake_issued_count'],
    })
    return out


def note_out(note):
    out = _common(note)
    out.update({
        'review_session_id': note['review_session_id'],
        'shot_stage_task_id': note['shot_stage_task_id'],
        'severity': note['severity'],
        'note_text': note['note_text'],
        'status': note['status'],
        'raised_by_user_id': note['raised_by_user_id'],
        'resolved_by_user_id': note['resolved_by_user_id'],
    })
    return out


def pool_out(pool):
    out = _common(pool)
    out.update({
        'name': pool['name'],
        'total_cores': pool['total_cores'],
        'cost_per_core_hour_cents': pool['cost_per_core_hour_cents'],
        'committed_core_hours': num(pool['committed_core_hours']),
        'reserved_job_count': pool['reserved_job_count'],
    })
    return out


def job_out(job):
    out = _common(job)
    out.update({
        'render_pool_id': job['render_pool_id'],
        'shot_stage_task_id': job['shot_stage_task_id'],
        'priority': job['priority'],
        'requested_cores': job['requested_cores'],
        'window_start': iso(job['window_start']),
        'window_end': iso(job['window_end']),
        'frame_count': job['frame_count'],
        'seconds_per_frame': num(job['seconds_per_frame']),
        'actual_seconds_per_frame': num(job['actual_seconds_per_frame']),
        'frames_completed': job['frames_completed'],
        'status': job['status'],
        'cost_per_frame_cents': job['cost_per_frame_cents'],
        'estimated_cost_cents': job['estimated_cost_cents'],
        'final_cost_cents': job['final_cost_cents'],
        'committed_core_hours': num(job['committed_core_hours']),
        'preempted_by_render_job_id': job['preempted_by_render_job_id'],
    })
    return out


def partner_out(partner):
    out = _common(partner)
    out.update({
        'legal_name': partner['legal_name'],
        'security_certification_level': partner['security_certification_level'],
        'mfa_enforced': partner['mfa_enforced'],
        'watermark_required': partner['watermark_required'],
        'status': partner['status'],
        'quality_score_rolling': num(partner_quality_score(partner, 'ROLLING_90D')),
        'quality_score_lifetime': num(partner_quality_score(partner, 'LIFETIME')),
        'qc_decided_package_count': partner['qc_decided_package_count'],
    })
    return out


def package_out(package):
    out = _common(package)
    out.update({
        'production_id': package['production_id'],
        'partner_id': package['partner_id'],
        'package_code': package['package_code'],
        'security_tier': package['security_tier'],
        'quality_min_score': num(package['quality_min_score']),
        'fee_cents': package['fee_cents'],
        'fee_committed_cents': package['fee_committed_cents'],
        'stage_task_ids': list(package['stage_task_ids']),
        'status': package['status'],
        'watermark_applied': package['watermark_applied'],
        'delivery_count': package['delivery_count'],
        'qc_score': package['qc_score'],
        'qc_decided_at': iso(package['qc_decided_at']),
    })
    return out


def deliverable_out(deliverable):
    out = _common(deliverable)
    out.update({
        'production_id': deliverable['production_id'],
        'shot_id': deliverable['shot_id'],
        'deliverable_type': deliverable['deliverable_type'],
        'color_space': deliverable['color_space'],
        'resolution': deliverable['resolution'],
        'frame_rate': num(deliverable['frame_rate']),
        'bit_depth': deliverable['bit_depth'],
        'version_index': deliverable['version_index'],
        'version_label': deliverable['version_label'],
        'status': deliverable['status'],
        'qc_note': deliverable['qc_note'],
        'delivered_at': iso(deliverable['delivered_at']),
    })
    return out
