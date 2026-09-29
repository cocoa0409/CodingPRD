"""Authentication, role gating and ownership resolution (PRD section 2.1)."""

from flask import request

import db
import response
from errors import ApiError, fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ADVERTISER = "Advertiser"
ROLE_PUBLISHER = "Publisher"
ROLE_CLASSIFICATION_ANALYST = "ClassificationAnalyst"
ROLE_DISPUTE_OFFICER = "DisputeOfficer"
ROLE_ACCREDITATION_AUDITOR = "AccreditationAuditor"
ROLE_MEASUREMENT_OPERATOR = "MeasurementOperator"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_ADVERTISER,
    ROLE_PUBLISHER,
    ROLE_CLASSIFICATION_ANALYST,
    ROLE_DISPUTE_OFFICER,
    ROLE_ACCREDITATION_AUDITOR,
    ROLE_MEASUREMENT_OPERATOR,
)

# Roles whose identity is entity backed: X-User-ID is mandatory for them.
ENTITY_BACKED_ROLES = (ROLE_ADVERTISER, ROLE_PUBLISHER)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self):
        return self.role == ROLE_PLATFORM_ADMIN

    @property
    def is_advertiser(self):
        return self.role == ROLE_ADVERTISER

    @property
    def is_publisher(self):
        return self.role == ROLE_PUBLISHER


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def authenticate():
    """Priority 1 -- authentication."""
    role = _header(USER_ROLE_HEADER)
    user_id = _header(USER_ID_HEADER)
    if role is None or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role in ENTITY_BACKED_ROLES and user_id is None:
        fail("ERR_UNAUTHENTICATED")
    return Caller(user_id, role)


def require(*allowed_roles):
    """Priority 1 then priority 2 -- authentication then role authorisation."""
    caller = authenticate()
    if allowed_roles and caller.role not in allowed_roles:
        fail("ERR_UNAUTHORIZED_ROLE")
    return caller


def clock_caller():
    """The logical-clock endpoint is exempt from the general auth chain but
    still demands X-User-Role naming PlatformAdmin (PRD section 2.1)."""
    role = _header(USER_ROLE_HEADER)
    if role is None or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role != ROLE_PLATFORM_ADMIN:
        fail("ERR_UNAUTHORIZED_ROLE")
    return Caller(_header(USER_ID_HEADER), role)


# --------------------------------------------------------------------------- #
# ownership (priority 3)                                                      #
# --------------------------------------------------------------------------- #
def own_advertiser(caller, advertiser_id):
    """A resource that resolves to an advertiser."""
    if caller.is_advertiser and advertiser_id is not None and advertiser_id != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def own_publisher(caller, publisher_id):
    """A resource that resolves to a publisher."""
    if caller.is_publisher and publisher_id is not None and publisher_id != caller.user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def own_campaign(caller, campaign):
    if campaign is not None:
        own_advertiser(caller, campaign.get("advertiser_id"))


def own_page(caller, page):
    if page is not None:
        own_publisher(caller, page.get("publisher_id"))


# --------------------------------------------------------------------------- #
# request bodies and query parameters                                         #
# --------------------------------------------------------------------------- #
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return default
    raw = raw.strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if str(value) != raw and not (raw.startswith("+") and str(value) == raw[1:]):
        # tolerate leading zeros / plus sign but reject float-ish input
        try:
            int(raw, 10)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s may not exceed %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param(
        "limit",
        response.PAGINATION_LIMIT_DEFAULT,
        response.PAGINATION_LIMIT_MIN,
        response.PAGINATION_LIMIT_MAX,
    )
    offset = _int_param("offset", response.PAGINATION_OFFSET_DEFAULT, 0, None)
    return limit, offset


def query(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw if raw else None


def query_bool(name):
    raw = query(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return "__unmatchable__"
