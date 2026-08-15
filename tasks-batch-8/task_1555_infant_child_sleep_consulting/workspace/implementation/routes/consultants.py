from flask import Blueprint

from auth import user_context, require_role
from db import store, base_fields, register
from domain import ser_consultant
from envelope import ok
from errors import ApiError
from validators import body, req_str, req_int

bp = Blueprint('consultants', __name__)


@bp.post('/consultants')
def create_consultant():
    _, role = user_context()
    require_role(role, 'PracticeAdmin')
    data = body()
    full_name = req_str(data, 'full_name')
    certification_no = req_str(data, 'certification_no')
    max_active_cases = req_int(data, 'max_active_cases', min_v=1)
    c = base_fields()
    c.update({
        'full_name': full_name,
        'certification_no': certification_no,
        'max_active_cases': max_active_cases,
    })
    register(store.consultants, c)
    return ok(ser_consultant(c), status=201)


@bp.get('/consultants/<consultantId>')
def get_consultant(consultantId):
    _, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    c = store.consultants.get(consultantId)
    if c is None:
        raise ApiError('ERR_CONSULTANT_NOT_FOUND', 404, 'Consultant not found')
    return ok(ser_consultant(c))
