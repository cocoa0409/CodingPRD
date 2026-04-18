from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, Rider
from services.rider_service import create_rider, has_active_assignments
from utils.response import success_response, err

bp = Blueprint('riders', __name__)


@bp.route('/api/riders', methods=['POST'])
@require_auth({'PlatformAdmin'})
def register_rider():
    data = request.get_json(silent=True) or {}
    if 'name' not in data or not data['name']:
        return err('ERR_VALIDATION', 'Name is required.')
    if 'phone' not in data or not data['phone']:
        return err('ERR_VALIDATION', 'Phone is required.')
    existing = Rider.query.filter_by(phone=data['phone']).first()
    if existing:
        return err('ERR_VALIDATION', 'Phone must be unique.')
    r = create_rider(data)
    db.session.commit()
    return success_response(r.to_dict(), 201)


@bp.route('/api/riders/<id>', methods=['GET'])
@require_auth({'PlatformAdmin', 'Rider', 'CustomerService'})
def get_rider(id):
    r = Rider.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Rider not found.')
    if g.user_role == 'Rider' and g.user_id != r.id:
        return err('ERR_FORBIDDEN', 'Not your rider profile.')
    return success_response(r.to_dict())


@bp.route('/api/riders/<id>/go-online', methods=['POST'])
@require_auth({'Rider'})
def go_online(id):
    r = Rider.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Rider not found.')
    if g.user_id != r.id:
        return err('ERR_FORBIDDEN', 'Not your rider profile.')
    if r.status != 'OFFLINE':
        return err('ERR_INVALID_STATE', 'Rider must be OFFLINE to go online.')
    r.status = 'AVAILABLE'
    r.touch()
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/riders/<id>/go-offline', methods=['POST'])
@require_auth({'Rider'})
def go_offline(id):
    r = Rider.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Rider not found.')
    if g.user_id != r.id:
        return err('ERR_FORBIDDEN', 'Not your rider profile.')
    if r.status != 'AVAILABLE':
        return err('ERR_INVALID_STATE', 'Rider must be AVAILABLE to go offline.')
    if has_active_assignments(r.id):
        return err('ERR_INVALID_STATE', 'Cannot go offline with active assignments.')
    r.status = 'OFFLINE'
    r.touch()
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/riders/<id>/suspend', methods=['POST'])
@require_auth({'PlatformAdmin'})
def suspend_rider(id):
    r = Rider.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Rider not found.')
    if r.status != 'AVAILABLE':
        return err('ERR_INVALID_STATE', 'Rider must be AVAILABLE to be suspended.')
    if r.on_time_rate >= 0.70 and r.acceptance_rate >= 0.50:
        return err('ERR_SUSPEND_CRITERIA_NOT_MET', 'Rider metrics do not meet suspension thresholds.')
    r.status = 'SUSPENDED'
    r.touch()
    db.session.commit()
    return success_response(r.to_dict())
