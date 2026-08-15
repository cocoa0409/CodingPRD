"""Flask application instance, error handlers, auth, pagination, lookups.

Kept import-cycle-free: route modules import from web (never from app).
"""
from flask import Flask, request

from store import DB
from util import ApiError, error_response, success_list

PREFIX = "/youth-ministry"
ALL_ROLES = ["ProgramDirector", "TripLeader", "Treasurer", "ScholarshipReviewer", "Guardian", "Chaperone"]

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected server error", 400))


@app.before_request
def _begin():
    DB.begin_request()


# ---------------------------------------------------------------------------
# Auth (validation priority 1 and 3)
# ---------------------------------------------------------------------------

def caller():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID and X-User-Role headers are required and role must be a declared role name",
                       400)
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN", "Role is not authorized for this endpoint", 403)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0", 400)
    return limit, offset


def paginate(items, serializer):
    limit, offset = pagination_params()
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers with 404s
# ---------------------------------------------------------------------------

def get_program(pid):
    p = DB.programs.get(pid)
    if p is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "Program not found", 404)
    return p


def get_trip(tid):
    t = DB.trips.get(tid)
    if t is None:
        raise ApiError("ERR_TRIP_NOT_FOUND", "Trip not found", 404)
    return t


def get_participant(pid):
    p = DB.participants.get(pid)
    if p is None:
        raise ApiError("ERR_PARTICIPANT_NOT_FOUND", "Participant not found", 404)
    return p


def get_registration(rid):
    r = DB.registrations.get(rid)
    if r is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND", "Registration not found", 404)
    return r


def get_consent_form(fid):
    f = DB.consent_forms.get(fid)
    if f is None:
        raise ApiError("ERR_CONSENT_FORM_NOT_FOUND", "Consent form not found", 404)
    return f


def get_account(aid):
    a = DB.fundraising_accounts.get(aid)
    if a is None:
        raise ApiError("ERR_FUNDRAISING_ACCOUNT_NOT_FOUND", "Fundraising account not found", 404)
    return a


def get_donation(did):
    d = DB.donations.get(did)
    if d is None:
        raise ApiError("ERR_DONATION_NOT_FOUND", "Donation not found", 404)
    return d


def get_payment(pid):
    p = DB.payments.get(pid)
    if p is None:
        raise ApiError("ERR_PAYMENT_NOT_FOUND", "Payment not found", 404)
    return p


def get_application(aid):
    a = DB.scholarship_applications.get(aid)
    if a is None:
        raise ApiError("ERR_SCHOLARSHIP_APPLICATION_NOT_FOUND", "Scholarship application not found", 404)
    return a


def get_chaperone(cid):
    c = DB.chaperones.get(cid)
    if c is None:
        raise ApiError("ERR_CHAPERONE_NOT_FOUND", "Chaperone not found", 404)
    return c


def get_check(cid):
    c = DB.background_checks.get(cid)
    if c is None:
        raise ApiError("ERR_BACKGROUND_CHECK_NOT_FOUND", "Background check not found", 404)
    return c


def get_assignment(aid):
    a = DB.chaperone_assignments.get(aid)
    if a is None:
        raise ApiError("ERR_CHAPERONE_ASSIGNMENT_NOT_FOUND", "Chaperone assignment not found", 404)
    return a


def get_lodging(lid):
    r = DB.lodging_reservations.get(lid)
    if r is None:
        raise ApiError("ERR_LODGING_RESERVATION_NOT_FOUND", "Lodging reservation not found", 404)
    return r


def guardian_owns_or_403(uid, role, guardian_user_id):
    if role == "Guardian" and guardian_user_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Guardian may act only on own resources", 403)
