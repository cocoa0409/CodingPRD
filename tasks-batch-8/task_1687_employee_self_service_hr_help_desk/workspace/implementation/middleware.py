"""Auth: X-User-ID / X-User-Role extraction, entity-backed identity binding."""
from flask import request

import db
from errors import ApiError

ROLES = (
    'Employee', 'HelpDeskAgent', 'SpecialistAgent', 'SensitiveCaseManager',
    'KnowledgeManager', 'HRDataSteward', 'WorkforcePlanner', 'HRServicesAdmin',
)
AGENT_ROLES = ('HelpDeskAgent', 'SpecialistAgent', 'SensitiveCaseManager')


class Ctx:
    def __init__(self, user_id, role, agent=None):
        self.user_id = user_id
        self.role = role
        self.agent = agent  # Agent row for agent roles, else None


def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not isinstance(uid, str) or not role or not isinstance(role, str):
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'X-User-ID and X-User-Role headers are required')
    if role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'undeclared role')
    if role == 'Employee':
        if uid not in db.employees:
            raise ApiError('ERR_UNAUTHENTICATED', 401,
                           'X-User-ID references no Employee row')
        return Ctx(uid, role)
    if role in AGENT_ROLES:
        agent = db.agents.get(uid)
        if agent is None:
            raise ApiError('ERR_UNAUTHENTICATED', 401,
                           'X-User-ID references no Agent row')
        return Ctx(uid, role, agent=agent)
    # Opaque roles: identifier not tied to any persisted entity.
    return Ctx(uid, role)


def require_roles(ctx, *roles):
    if ctx.role not in roles:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'caller role is not authorized for this endpoint')


def caller_sensitive_cleared(ctx):
    """True when the caller is an entity-backed agent holding SENSITIVE clearance."""
    return ctx.agent is not None and ctx.agent.get('clearance') == 'SENSITIVE'


def require_sensitive_write(ctx, ticket):
    """Any write/action on a sensitive ticket requires caller agent clearance
    SENSITIVE. Opaque roles (e.g. HRServicesAdmin) hold no agent clearance and
    are exempt; agent-role callers must hold SENSITIVE."""
    if ticket.get('sensitive') and ctx.role in AGENT_ROLES \
            and not caller_sensitive_cleared(ctx):
        raise ApiError('ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED', 403,
                       'sensitive ticket requires SENSITIVE clearance')
