from datetime import datetime, timezone
from flask import Blueprint, request
from middleware.auth import require_auth
from models.database import db, Assignment, Rider
from services.rider_service import recompute_acceptance_rate, recompute_bonus_tier
from services.dispatch_service import dispatch_order, get_rejected_rider_ids
from utils.clock import clock
from utils.response import success_response, err

bp = Blueprint('clock', __name__)


def sweep_expired_offers():
    now = clock.now()
    offered = Assignment.query.filter_by(status='OFFERED').all()
    for a in offered:
        offered_dt = datetime.strptime(a.offered_at, '%Y-%m-%dT%H:%M:%S.%fZ')
        offered_dt = offered_dt.replace(tzinfo=timezone.utc)
        elapsed = (now - offered_dt).total_seconds()
        if elapsed >= 60:
            a.status = 'REJECTED'
            rider = Rider.query.get(a.rider_id)
            if rider:
                recompute_acceptance_rate(rider)
                recompute_bonus_tier(rider)
                rider.touch()
            from models.database import Order
            order = Order.query.get(a.order_id)
            if order:
                exclude_ids = get_rejected_rider_ids(order.id)
                dispatch_order(order, exclude_rider_ids=exclude_ids)


@bp.route('/api/_clock/advance', methods=['POST'])
@require_auth({'PlatformAdmin'})
def advance_clock():
    data = request.get_json(silent=True) or {}
    seconds = data.get('seconds', 0)
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return err('ERR_VALIDATION', 'Invalid seconds value.')
    clock.advance(seconds)
    sweep_expired_offers()
    db.session.commit()
    return success_response({'new_time': clock.format(clock.now())})
