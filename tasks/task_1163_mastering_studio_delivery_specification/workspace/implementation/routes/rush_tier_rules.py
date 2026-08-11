from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import (
    auth, require_roles, body, req_field, as_int, as_enum, pagination_args,
)
from response import success, success_list

bp = Blueprint('rush_tier_rules', __name__)

TIERS = ('STANDARD', 'EXPRESS', 'RUSH', 'EMERGENCY')


@bp.post('/studio/rush-tier-rules')
def create_rule():
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    data = body()
    tier = as_enum(req_field(data, 'tier'), 'tier', TIERS)
    multiplier_bp = as_int(req_field(data, 'multiplier_bp'), 'multiplier_bp')
    sla_hours = as_int(req_field(data, 'sla_hours'), 'sla_hours')
    if sla_hours <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'sla_hours must be > 0')
    surcharge = as_int(req_field(data, 'surcharge_breach_cents'), 'surcharge_breach_cents')
    included = as_int(req_field(data, 'included_revision_rounds'), 'included_revision_rounds')
    per_round = as_int(req_field(data, 'per_round_cents'), 'per_round_cents')
    for r in db.rush_tier_rules.values():
        if r['tier'] == tier:
            raise ApiError(ERR_INVALID_REQUEST, 409, 'tier already registered')
    rec = db.new_record()
    rec.update({
        'tier': tier,
        'multiplier_bp': multiplier_bp,
        'sla_hours': sla_hours,
        'surcharge_breach_cents': surcharge,
        'included_revision_rounds': included,
        'per_round_cents': per_round,
    })
    db.rush_tier_rules[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/rush-tier-rules')
def list_rules():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    limit, offset = pagination_args()
    tier = request.args.get('tier')
    items = list(db.rush_tier_rules.values())
    if tier is not None:
        items = [r for r in items if r['tier'] == tier]
    items.sort(key=lambda r: r['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)
