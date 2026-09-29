"""Auth, payload well-formedness, lookups and scope checks.

Every helper here corresponds to one band of the ordered gauntlet in PRD 2.9;
routes call them strictly in band order.
"""
from flask import request

from errors import fail
from store import db
from util import DATE_RE, INSTANT_RE, parse_date, parse_instant

ROLES = ("Merchant", "Consumer", "ProgramUnderwriter", "RiskAnalyst",
         "ServicingAgent", "ProgramAdmin")
TRADE_TYPES = ("ROOFING", "HVAC", "SOLAR", "WINDOWS", "GENERAL_REMODEL")
PROMOTION_TYPES = ("DEFERRED_INTEREST", "ZERO_INTEREST_EQUAL_PAY", "REDUCED_APR",
                   "STANDARD_REVOLVING")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


class Ctx(object):
    def __init__(self, role, user_id, body):
        self.role = role
        self.user_id = user_id
        self.body = body


# =============================================================================
# Band 1 + 2 — authentication and role authorisation (PRD 2.1)
# =============================================================================
def authorize(permitted_roles):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "A valid X-User-Role header is required.")
    user_id = request.headers.get("X-User-ID")
    if request.method != "GET":
        if user_id is None or user_id.strip() == "":
            fail("ERR_UNAUTHENTICATED", "A non-empty X-User-ID header is required.")
    if role not in permitted_roles:
        fail("ERR_ROLE_NOT_PERMITTED",
             "Role %s may not call this endpoint." % role)
    return Ctx(role, user_id, None)


# =============================================================================
# Band 3 — payload well-formedness (PRD 2.9 #3)
# =============================================================================
def read_body(ctx, required=True):
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        body = {}
    else:
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        if body is None:
            body = {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    _check_amount_fields(body)
    ctx.body = body
    return body


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_amount_fields(body):
    """Every *_cents / *_bps field must be a whole number that is not negative."""
    for key, value in body.items():
        if key.endswith("_cents") or key.endswith("_bps"):
            if value is None:
                continue
            if not _is_int(value) or value < 0:
                fail("ERR_INVALID_REQUEST",
                     "Field %s must be a non-negative whole number." % key)


def req_present(body, name):
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    return body[name]


def req_str(body, name, allow_empty=False):
    value = req_present(body, name)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    if not allow_empty and value == "":
        fail("ERR_INVALID_REQUEST", "Field %s must not be empty." % name)
    return value


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        fail("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    return body[name]


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field %s must be one of %s." %
             (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    value = req_str(body, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field %s must be one of %s." %
             (name, ", ".join(allowed)))
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = req_present(body, name)
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "Field %s must be a whole number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field %s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field %s must be at most %d." % (name, maximum))
    return value


def req_money(body, name, positive=False):
    value = req_int(body, name, minimum=0)
    if positive and value <= 0:
        fail("ERR_INVALID_REQUEST", "Field %s must be greater than zero." % name)
    return value


def opt_money(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum=0)


def req_bool(body, name):
    value = req_present(body, name)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        fail("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return body[name]


def req_date(body, name):
    value = req_str(body, name)
    if not DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field %s must be an ISO date (YYYY-MM-DD)." % name)
    try:
        parse_date(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field %s is not a valid calendar date." % name)
    return value


def req_instant(body, name):
    value = req_str(body, name)
    if not INSTANT_RE.match(value):
        fail("ERR_INVALID_REQUEST",
             "Field %s must be an ISO 8601 UTC instant ending in Z." % name)
    try:
        return parse_instant(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field %s is not a valid instant." % name)


def req_enum_array(body, name, allowed):
    value = req_present(body, name)
    if not isinstance(value, list) or not value:
        fail("ERR_INVALID_REQUEST", "Field %s must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST",
                 "Field %s may only contain %s." % (name, ", ".join(allowed)))
    return list(value)


# =============================================================================
# Pagination (PRD 2.3)
# =============================================================================
def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def filter_arg(name, allowed=None):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s filter must be one of %s." %
             (name, ", ".join(allowed)))
    return value


def bool_filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s filter must be true or false." % name)


# =============================================================================
# Band 5 + 6 — identifier resolution (PRD 2.7). Containment counts as
# non-resolution: a child of another parent raises the child's not-found code.
# =============================================================================
def get_merchant(merchant_id):
    rec = db.merchants.get(merchant_id)
    if rec is None:
        fail("ERR_MERCHANT_NOT_FOUND", "Merchant %s does not exist." % merchant_id)
    return rec


def get_license(merchant_id, license_id):
    rec = db.licenses.get(license_id)
    if rec is None or rec["merchant_id"] != merchant_id:
        fail("ERR_LICENSE_NOT_FOUND", "License %s does not exist." % license_id)
    return rec


def get_enrollment(enrollment_id):
    rec = db.enrollments.get(enrollment_id)
    if rec is None:
        fail("ERR_ENROLLMENT_NOT_FOUND",
             "Promotion enrollment %s does not exist." % enrollment_id)
    return rec


def get_consumer(consumer_id):
    rec = db.consumers.get(consumer_id)
    if rec is None:
        fail("ERR_CONSUMER_NOT_FOUND", "Consumer %s does not exist." % consumer_id)
    return rec


def get_plan(plan_id):
    rec = db.promotion_plans.get(plan_id)
    if rec is None:
        fail("ERR_PROMOTION_PLAN_NOT_FOUND",
             "Promotion plan %s does not exist." % plan_id)
    return rec


def get_application(application_id):
    rec = db.applications.get(application_id)
    if rec is None:
        fail("ERR_APPLICATION_NOT_FOUND",
             "Credit application %s does not exist." % application_id)
    return rec


def get_loan_account(account_id):
    rec = db.loan_accounts.get(account_id)
    if rec is None:
        fail("ERR_LOAN_ACCOUNT_NOT_FOUND",
             "Loan account %s does not exist." % account_id)
    return rec


def get_project(project_id):
    rec = db.projects.get(project_id)
    if rec is None:
        fail("ERR_PROJECT_NOT_FOUND", "Project %s does not exist." % project_id)
    return rec


def get_milestone(project_id, milestone_id):
    rec = db.milestones.get(milestone_id)
    if rec is None or rec["project_id"] != project_id:
        fail("ERR_MILESTONE_NOT_FOUND", "Milestone %s does not exist." % milestone_id)
    return rec


def get_milestone_by_id(milestone_id):
    rec = db.milestones.get(milestone_id)
    if rec is None:
        fail("ERR_MILESTONE_NOT_FOUND", "Milestone %s does not exist." % milestone_id)
    return rec


def get_draw(draw_id):
    rec = db.draws.get(draw_id)
    if rec is None:
        fail("ERR_DRAW_NOT_FOUND", "Funding draw %s does not exist." % draw_id)
    return rec


def get_dispute(case_id):
    rec = db.disputes.get(case_id)
    if rec is None:
        fail("ERR_DISPUTE_NOT_FOUND", "Dispute case %s does not exist." % case_id)
    return rec


def get_alert(merchant_id, alert_id):
    rec = db.alerts.get(alert_id)
    if rec is None or rec["merchant_id"] != merchant_id:
        fail("ERR_ALERT_NOT_FOUND", "Fraud alert %s does not exist." % alert_id)
    return rec


def get_trade_rule(trade_type):
    from calc import trade_rule_for
    rule = trade_rule_for(trade_type)
    if rule is None:
        fail("ERR_TRADE_RULE_NOT_FOUND",
             "No trade rule is registered for %s." % trade_type)
    return rule


# =============================================================================
# Band 7 + 8 + 9 — entity-backed identity and ownership scope (PRD 2.1)
# =============================================================================
def resolve_identity(ctx, permitted_roles):
    if ctx.role == "Merchant" and "Merchant" in permitted_roles:
        if ctx.user_id is None or ctx.user_id not in db.merchants:
            fail("ERR_IDENTITY_UNKNOWN",
                 "X-User-ID does not resolve to a merchant.")
    if ctx.role == "Consumer" and "Consumer" in permitted_roles:
        if ctx.user_id is None or ctx.user_id not in db.consumers:
            fail("ERR_IDENTITY_UNKNOWN",
                 "X-User-ID does not resolve to a consumer.")


def merchant_scope(ctx, merchant_id):
    if ctx.role == "Merchant" and ctx.user_id != merchant_id:
        fail("ERR_MERCHANT_SCOPE_VIOLATION",
             "This merchant may only act inside its own book.")


def consumer_scope(ctx, consumer_id):
    if ctx.role == "Consumer" and ctx.user_id != consumer_id:
        fail("ERR_CONSUMER_SCOPE_VIOLATION",
             "This consumer may only act inside its own book.")
