"""Reusable rungs of the ordered validation ladder (rungs 7 through 50)."""

from datetime import timedelta

import db
from errors import ApiError
from services import derive, enums


# --------------------------------------------- rung 7: move actionability (409)
def require_move_state(move, allowed):
    if move["lifecycle_status"] not in allowed:
        raise ApiError(
            "ERR_MOVE_NOT_ACTIONABLE",
            "Move lifecycle_status %s does not permit this operation."
            % move["lifecycle_status"],
        )


def require_move_live(move):
    require_move_state(move, enums.OPEN_LIFECYCLE)


def require_not_locked(move):
    """A COMPLETED move locks itself and every child against further mutation."""
    if move["lifecycle_status"] == "COMPLETED":
        raise ApiError(
            "ERR_MOVE_NOT_ACTIONABLE",
            "The move is COMPLETED and locked against further mutation.",
        )


# ------------------------------------------------- rung 8: order state (409)
def require_order_state(order, allowed, message=None):
    if order["provision_status"] not in allowed:
        raise ApiError(
            "ERR_ORDER_NOT_SCHEDULABLE",
            message
            or "Order provision_status %s does not permit this operation."
            % order["provision_status"],
        )


def require_credit_state(order, allowed, message=None, error_id="ERR_ORDER_NOT_SCHEDULABLE"):
    if order["credit_status"] not in allowed:
        raise ApiError(
            error_id,
            message
            or "Order credit_status %s does not permit this operation."
            % order["credit_status"],
        )


# ------------------------------------------------ rung 9: filing state (409)
def require_filing_state(order_status, allowed, message=None):
    if order_status not in allowed:
        raise ApiError(
            "ERR_FILING_NOT_SUBMITTABLE",
            message or "Filing status %s does not permit this operation." % order_status,
        )


# --------------------------------------------- rung 10: placement state (409)
def require_placement_state(placement, allowed):
    if placement["placement_status"] not in allowed:
        raise ApiError(
            "ERR_PLACEMENT_NOT_CONVERTIBLE",
            "Placement status %s does not permit this operation."
            % placement["placement_status"],
        )


# ------------------------------------------------- rungs 14/15: concurrency
def check_move_version(move, expected):
    if expected is not None and expected != move["version"]:
        raise ApiError(
            "ERR_STALE_MOVE_VERSION",
            "expected_move_version %s does not match the stored version %s."
            % (expected, move["version"]),
        )


def check_resident_version(resident, expected):
    if expected is not None and expected != resident["version"]:
        raise ApiError(
            "ERR_STALE_RESIDENT_VERSION",
            "expected_resident_version %s does not match the stored version %s."
            % (expected, resident["version"]),
        )


# ------------------------------------------------------ rungs 16/17: identity
def require_identity_verified(move):
    latest = derive.latest_verification(move["id"])
    if move.get("verified_at") is None or latest is None or latest["status"] != "PASSED":
        raise ApiError(
            "ERR_IDENTITY_NOT_VERIFIED",
            "The move has no passed identity verification.",
        )


def require_identity_current(move):
    limit = derive.identity_valid_until(move)
    if limit is None or db.now() > limit:
        raise ApiError(
            "ERR_IDENTITY_VERIFICATION_EXPIRED",
            "The identity verification is outside its %d-day validity window."
            % enums.IDENTITY_VALIDITY_DAYS,
        )


def require_attempts_available(move):
    if move["identity_attempt_count"] >= enums.MAX_IDENTITY_ATTEMPTS:
        raise ApiError(
            "ERR_VERIFICATION_ATTEMPTS_EXHAUSTED",
            "All %d identity verification attempts have been consumed."
            % enums.MAX_IDENTITY_ATTEMPTS,
        )


# -------------------------------------------------------- rungs 20/21/22
def require_consent(move, scope):
    if not derive.has_consent(move, scope):
        raise ApiError(
            "ERR_CONSENT_MISSING",
            "No GRANTED %s consent covers this move." % scope,
        )


def require_gate_open(move):
    if move["consent_gate"] != "OPEN":
        raise ApiError(
            "ERR_CONSENT_REVOKED",
            "The move's consent gate is BLOCKED.",
        )


def require_no_marketing_opt_out(resident):
    if resident["marketing_opt_out"]:
        raise ApiError(
            "ERR_MARKETING_OPT_OUT",
            "The resident has opted out of partner marketing.",
        )


# --------------------------------------------------- rungs 25/26/27
def require_provider_active(provider):
    if provider["provider_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_INACTIVE", "The utility provider is INACTIVE.")


def require_feed_active(feed_source):
    if feed_source["feed_status"] != "ACTIVE":
        raise ApiError("ERR_FEED_SUSPENDED", "The feed source is SUSPENDED.")


def require_duplicate_resolved(move):
    if move["duplicate_flag"] == "SUSPECTED":
        raise ApiError(
            "ERR_DUPLICATE_MOVE_UNRESOLVED",
            "The move carries an unresolved SUSPECTED duplicate flag.",
        )


# --------------------------------------------------------- rung 29: move date
def require_move_date_in_range(move_date):
    today = db.clock_date()
    if move_date < today - timedelta(days=enums.MOVE_DATE_PAST_DAYS):
        raise ApiError(
            "ERR_MOVE_DATE_OUT_OF_RANGE",
            "move_date is more than %d days in the past." % enums.MOVE_DATE_PAST_DAYS,
        )
    if move_date > today + timedelta(days=enums.MOVE_DATE_FUTURE_DAYS):
        raise ApiError(
            "ERR_MOVE_DATE_OUT_OF_RANGE",
            "move_date is more than %d days in the future."
            % enums.MOVE_DATE_FUTURE_DAYS,
        )


# --------------------------------------------------- rung 38: completion date
def require_move_date_reached(move):
    if db.clock_date() < db.parse_date(move["move_date"]):
        raise ApiError(
            "ERR_MOVE_DATE_NOT_REACHED",
            "The logical clock has not reached the move_date yet.",
        )
