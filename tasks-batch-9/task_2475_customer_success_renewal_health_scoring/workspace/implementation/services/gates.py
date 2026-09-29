"""The shared precondition gates of the validation ladder."""
from errors import ApiError


def require_not_frozen(account):
    """Ladder rule 13."""
    if account['coverage_posture'] == 'FROZEN':
        raise ApiError('ERR_COVERAGE_POSTURE_FROZEN',
                       'The account coverage posture is FROZEN.')


def require_open(account):
    """Ladder rule 14 — the strictly stronger gate."""
    if account['coverage_posture'] != 'OPEN':
        raise ApiError('ERR_COVERAGE_POSTURE_RESTRICTED',
                       'The account coverage posture must be OPEN; it is %s.'
                       % account['coverage_posture'])


def require_health_tier(account, allowed):
    """Ladder rule 18."""
    if account['health_tier'] not in allowed:
        raise ApiError('ERR_HEALTH_TIER_INELIGIBLE',
                       'The account health tier %s is not one of %s.'
                       % (account['health_tier'], ', '.join(allowed)))


def invalid_transition(message):
    """Ladder rule 12 and the unnumbered per-edge preconditions that share its
    error code."""
    return ApiError('ERR_INVALID_STATE_TRANSITION', message)
