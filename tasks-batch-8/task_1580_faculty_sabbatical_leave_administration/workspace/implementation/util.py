"""Shared helpers: dates, decimals, envelope, errors, auth, pagination."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalog (id -> http status)
# ---------------------------------------------------------------------------
ERR = {
    'ERR_MISSING_OR_INVALID_USER_CONTEXT': 400,
    'ERR_INVALID_REQUEST': 400,
    'ERR_INVALID_PAGINATION': 400,
    'ERR_FORBIDDEN_ROLE': 403,
    'ERR_NOT_RESOURCE_OWNER': 403,
    'ERR_CHAIR_DEPARTMENT_MISMATCH': 403,
    'ERR_REVIEWER_CONFLICT': 403,
    'ERR_SEGREGATION_OF_DUTIES': 403,
    'ERR_DEPARTMENT_NOT_FOUND': 404,
    'ERR_FACULTY_NOT_FOUND': 404,
    'ERR_CYCLE_NOT_FOUND': 404,
    'ERR_APPLICATION_NOT_FOUND': 404,
    'ERR_REVIEW_NOT_FOUND': 404,
    'ERR_COVERAGE_PLAN_NOT_FOUND': 404,
    'ERR_GRANT_NOT_FOUND': 404,
    'ERR_FELLOWSHIP_NOT_FOUND': 404,
    'ERR_OBLIGATION_NOT_FOUND': 404,
    'ERR_REPAYMENT_NOT_FOUND': 404,
    'ERR_REPORT_NOT_FOUND': 404,
    'ERR_STALE_VERSION': 412,
    'ERR_INVALID_CYCLE_STATE': 409,
    'ERR_CYCLE_NOT_OPEN': 409,
    'ERR_CYCLE_NOT_CLOSED': 409,
    'ERR_CYCLE_NOT_ALLOCATED': 409,
    'ERR_INVALID_APPLICATION_STATE': 409,
    'ERR_SABBATICAL_REQUIRES_ALLOCATION': 409,
    'ERR_INVALID_FACULTY_STATE': 409,
    'ERR_INVALID_REVIEW_STATE': 409,
    'ERR_INVALID_PLAN_STATE': 409,
    'ERR_INVALID_GRANT_STATE': 409,
    'ERR_INVALID_FELLOWSHIP_STATE': 409,
    'ERR_INVALID_REPAYMENT_STATE': 409,
    'ERR_INVALID_REPORT_STATE': 409,
    'ERR_OVERDUE_REPORT_BLOCKS': 409,
    'ERR_DEFAULTED_REPAYMENT_BLOCKS': 409,
    'ERR_DUPLICATE_ACTIVE_APPLICATION': 409,
    'ERR_DUPLICATE_REVIEW': 409,
    'ERR_INSUFFICIENT_SERVICE_MONTHS': 422,
    'ERR_INVALID_DURATION_SALARY_COMBO': 422,
    'ERR_INVALID_DATE_RANGE': 422,
    'ERR_LEAVE_WINDOW_OVERLAP': 409,
    'ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT': 422,
    'ERR_GRANT_START_NOT_REACHED': 409,
    'ERR_DEPARTMENT_LEAVE_CAPACITY': 409,
    'ERR_INSUFFICIENT_SABBATICAL_CREDITS': 402,
    'ERR_DEPARTMENT_FROZEN': 409,
    'ERR_INSUFFICIENT_COVERAGE_BUDGET': 402,
    'ERR_PAYMENT_EXCEEDS_OUTSTANDING': 422,
    'ERR_POOL_BELOW_COMMITMENTS': 422,
}

MESSAGES = {
    'ERR_MISSING_OR_INVALID_USER_CONTEXT': 'X-User-ID and X-User-Role headers are required and the role must be a declared role.',
    'ERR_INVALID_REQUEST': 'The request payload is missing required fields or contains invalid values.',
    'ERR_INVALID_PAGINATION': 'Pagination parameters are out of bounds (limit must be 1..100, offset must be >= 0).',
    'ERR_FORBIDDEN_ROLE': 'The caller role is not authorized for this endpoint.',
    'ERR_NOT_RESOURCE_OWNER': 'The caller does not own the target resource.',
    'ERR_CHAIR_DEPARTMENT_MISMATCH': 'The acting chair does not chair the department of this coverage plan.',
    'ERR_REVIEWER_CONFLICT': 'The reviewer is the applicant or belongs to the applicant\'s department.',
    'ERR_SEGREGATION_OF_DUTIES': 'The coverage plan creator may not be the applicant.',
    'ERR_DEPARTMENT_NOT_FOUND': 'Department id does not exist.',
    'ERR_FACULTY_NOT_FOUND': 'FacultyMember id does not exist.',
    'ERR_CYCLE_NOT_FOUND': 'LeaveCycle id does not exist.',
    'ERR_APPLICATION_NOT_FOUND': 'LeaveApplication id does not exist.',
    'ERR_REVIEW_NOT_FOUND': 'CommitteeReview id does not exist.',
    'ERR_COVERAGE_PLAN_NOT_FOUND': 'CoveragePlan id does not exist.',
    'ERR_GRANT_NOT_FOUND': 'LeaveGrant id does not exist.',
    'ERR_FELLOWSHIP_NOT_FOUND': 'ExternalFellowship id does not exist.',
    'ERR_OBLIGATION_NOT_FOUND': 'ServiceObligation id does not exist.',
    'ERR_REPAYMENT_NOT_FOUND': 'RepaymentObligation id does not exist.',
    'ERR_REPORT_NOT_FOUND': 'AccomplishmentReport id does not exist.',
    'ERR_STALE_VERSION': 'The expected version does not match the resource\'s current version.',
    'ERR_INVALID_CYCLE_STATE': 'The cycle transition is invalid for the current cycle status.',
    'ERR_CYCLE_NOT_OPEN': 'Application submission requires the cycle to be OPEN.',
    'ERR_CYCLE_NOT_CLOSED': 'Allocation requires the cycle to be CLOSED.',
    'ERR_CYCLE_NOT_ALLOCATED': 'Finalization requires the cycle to be ALLOCATED.',
    'ERR_INVALID_APPLICATION_STATE': 'The application transition is invalid for the current application status.',
    'ERR_SABBATICAL_REQUIRES_ALLOCATION': 'Sabbatical applications are decided only by the allocation run.',
    'ERR_INVALID_FACULTY_STATE': 'The faculty member status is incompatible with this operation.',
    'ERR_INVALID_REVIEW_STATE': 'Review submission requires the review to be DRAFT.',
    'ERR_INVALID_PLAN_STATE': 'The coverage plan transition is invalid for the current plan status.',
    'ERR_INVALID_GRANT_STATE': 'The grant transition is invalid for the current grant status.',
    'ERR_INVALID_FELLOWSHIP_STATE': 'The fellowship transition is invalid for the current fellowship status.',
    'ERR_INVALID_REPAYMENT_STATE': 'The repayment obligation is in a terminal state.',
    'ERR_INVALID_REPORT_STATE': 'The report transition is invalid for the current report status.',
    'ERR_OVERDUE_REPORT_BLOCKS': 'The faculty member has an OVERDUE accomplishment report.',
    'ERR_DEFAULTED_REPAYMENT_BLOCKS': 'The faculty member has a DEFAULTED repayment obligation.',
    'ERR_DUPLICATE_ACTIVE_APPLICATION': 'The faculty member already has another in-flight application.',
    'ERR_DUPLICATE_REVIEW': 'The reviewer already has a review for this application.',
    'ERR_INSUFFICIENT_SERVICE_MONTHS': 'Sabbatical submission requires at least 72 certified service months.',
    'ERR_INVALID_DURATION_SALARY_COMBO': 'The (duration, salary percentage) combination is not an allowed tier.',
    'ERR_INVALID_DATE_RANGE': 'The window is misaligned, inverted, or the supplied date falls outside it.',
    'ERR_LEAVE_WINDOW_OVERLAP': 'The window overlaps an ACTIVE grant of the same faculty member.',
    'ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT': 'The fellowship window overlaps less than half of the leave window.',
    'ERR_GRANT_START_NOT_REACHED': 'The grant start date has not been reached.',
    'ERR_DEPARTMENT_LEAVE_CAPACITY': 'The department already has the maximum number of simultaneous active leaves.',
    'ERR_INSUFFICIENT_SABBATICAL_CREDITS': 'The credit balance is below 36 credits per requested semester.',
    'ERR_DEPARTMENT_FROZEN': 'The department posture is FROZEN.',
    'ERR_INSUFFICIENT_COVERAGE_BUDGET': 'The department available amount is below the plan provisional cost.',
    'ERR_PAYMENT_EXCEEDS_OUTSTANDING': 'The payment amount exceeds the outstanding balance.',
    'ERR_POOL_BELOW_COMMITMENTS': 'The replacement pool may not be set below reserved plus spent amounts.',
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http = ERR[error_id]
        self.message = message or MESSAGES[error_id]
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return 'req_' + secrets.token_hex(12)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(dt.microsecond // 1000)


def month_of(dt):
    return '{:04d}-{:02d}'.format(dt.year, dt.month)


def prev_month_str(wm):
    y, m = int(wm[:4]), int(wm[5:7])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return '{:04d}-{:02d}'.format(y, m)


def month_index(wm):
    return int(wm[:4]) * 12 + int(wm[5:7])


def month_str_from_index(idx):
    y = (idx - 1) // 12
    m = (idx - 1) % 12 + 1
    return '{:04d}-{:02d}'.format(y, m)


def first_day_of_month(wm):
    return datetime(int(wm[:4]), int(wm[5:7]), 1, tzinfo=UTC)


def days_in_month(y, m):
    if m == 12:
        nxt = datetime(y + 1, 1, 1)
    else:
        nxt = datetime(y, m + 1, 1)
    return (nxt - datetime(y, m, 1)).days


def add_months(dt, n):
    total = (dt.month - 1) + n
    y = dt.year + total // 12
    m = total % 12 + 1
    d = min(dt.day, days_in_month(y, m))
    return dt.replace(year=y, month=m, day=d)


def whole_months_between(start, end):
    """Whole calendar months between two instants (anniversary method, floored)."""
    if end <= start:
        return 0
    m = (end.year - start.year) * 12 + (end.month - start.month)
    while m > 0 and add_months(start, m) > end:
        m -= 1
    return m


def windows_overlap(s1, e1, s2, e2):
    """Half-open interval overlap: adjacency (end == start) is not overlap."""
    return s1 < e2 and s2 < e1


def overlap_seconds(s1, e1, s2, e2):
    lo, hi = max(s1, s2), min(e1, e2)
    if hi <= lo:
        return 0.0
    return (hi - lo).total_seconds()


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
CENT = Decimal('0.01')


def D(value):
    return Decimal(str(value))


def q2(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_positive_money(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    if d.is_nan() or d.is_infinite() or d <= 0:
        return None
    return d


def parse_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def money_out(d):
    if d is None:
        return None
    return float(d)


# ---------------------------------------------------------------------------
# Envelope + pagination
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    meta = {
        'api_request_id': new_request_id(),
        'api_request_timestamp': iso(datetime.now(UTC)),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, code=200, pagination=None, response_type='object'):
    body = {'meta': _meta(pagination), 'response_type': response_type, 'data': data}
    return jsonify(body), code


def err_body(error_id, message, http):
    body = {'meta': _meta(), 'response_type': 'error',
            'data': {'error_id': error_id, 'message': message}}
    return jsonify(body), http


def pagination_params():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        fail('ERR_INVALID_PAGINATION')
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        fail('ERR_INVALID_PAGINATION')
    if limit < 1 or limit > 100 or offset < 0:
        fail('ERR_INVALID_PAGINATION')
    return limit, offset


def paginate(sorted_items):
    limit, offset = pagination_params()
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return page, meta


def sort_items(items):
    return sorted(items, key=lambda r: (r['created_at'], r['_seq']))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
ROLES = {'Faculty', 'CommitteeMember', 'DepartmentChair', 'ProvostOffice', 'LeaveAdministrator'}
ALL_ROLES = ROLES


def auth_context():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        fail('ERR_MISSING_OR_INVALID_USER_CONTEXT')
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        fail('ERR_FORBIDDEN_ROLE')


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail('ERR_INVALID_REQUEST', 'Request body must be a JSON object.')
    return data


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        fail('ERR_INVALID_REQUEST', 'Field "{}" is required and must be a non-empty string.'.format(field))
    return v


def optional_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        fail('ERR_INVALID_REQUEST', 'Field "{}" must be a string.'.format(field))
    return v
