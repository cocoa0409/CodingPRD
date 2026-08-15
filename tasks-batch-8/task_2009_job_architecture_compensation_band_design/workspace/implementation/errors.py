"""Error classes and error ID constants per scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error IDs (from SCAFFOLD.yaml / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                      # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                    # 400
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"                          # 400
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_PROGRAM_STATE_FORBIDS = "ERR_PROGRAM_STATE_FORBIDS"        # 409
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"  # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"                  # 409
ERR_FLSA_SALARY_BASIS_VIOLATION = "ERR_FLSA_SALARY_BASIS_VIOLATION"  # 422
ERR_FLSA_TESTS_INCOMPLETE = "ERR_FLSA_TESTS_INCOMPLETE"        # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"              # 403
ERR_DUPLICATE_BAND = "ERR_DUPLICATE_BAND"                      # 409
ERR_DUPLICATE_POLICY = "ERR_DUPLICATE_POLICY"                  # 409
ERR_BAND_OVERLAP_EXCEEDS_POLICY = "ERR_BAND_OVERLAP_EXCEEDS_POLICY"  # 422
ERR_PROGRESSION_BELOW_POLICY = "ERR_PROGRESSION_BELOW_POLICY"  # 422
ERR_NO_MARKET_DATA = "ERR_NO_MARKET_DATA"                      # 422
ERR_GEO_CYCLE = "ERR_GEO_CYCLE"                                # 422
ERR_PROFILE_IN_USE = "ERR_PROFILE_IN_USE"                      # 409
ERR_REFRESH_WINDOW_CONFLICT = "ERR_REFRESH_WINDOW_CONFLICT"    # 409
ERR_REFRESH_NOT_DUE = "ERR_REFRESH_NOT_DUE"                    # 409
ERR_REVERSE_WINDOW_EXPIRED = "ERR_REVERSE_WINDOW_EXPIRED"      # 422
ERR_CUT_TOO_CLOSE = "ERR_CUT_TOO_CLOSE"                        # 422
ERR_EXCEPTION_ROLLING_CAP = "ERR_EXCEPTION_ROLLING_CAP"        # 422
ERR_EXCEPTION_CAP_EXCEEDED = "ERR_EXCEPTION_CAP_EXCEEDED"      # 422
ERR_DEPARTMENT_POOL_EXHAUSTED = "ERR_DEPARTMENT_POOL_EXHAUSTED"  # 422
ERR_BUDGET_IMPACT_EXCEEDS = "ERR_BUDGET_IMPACT_EXCEEDS"        # 422
ERR_REFERENCED_ENTITY_STATE = "ERR_REFERENCED_ENTITY_STATE"    # 422


def unauthenticated(msg="missing or unknown X-User-Role / missing X-User-ID"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden_role(msg="role not listed for the endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, msg, 403)


def invalid_request(msg="request body shape violation"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_enum(msg="enum field carries an undeclared member"):
    return ApiError(ERR_INVALID_ENUM, msg, 400)


def not_found(msg="path id or body FK reference does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def stale_version(msg="expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def program_state_forbids(msg="CompProgram posture does not permit the operation"):
    return ApiError(ERR_PROGRAM_STATE_FORBIDS, msg, 409)


def invalid_state_transition(msg="trigger not declared for the entity's current state"):
    return ApiError(ERR_INVALID_STATE_TRANSITION, msg, 409)


def already_terminal(msg="entity sits in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, msg, 409)


def flsa_salary_basis_violation(msg="FLSA salary-basis floor violated"):
    return ApiError(ERR_FLSA_SALARY_BASIS_VIOLATION, msg, 422)


def flsa_tests_incomplete(msg="flsa_classification == PENDING"):
    return ApiError(ERR_FLSA_TESTS_INCOMPLETE, msg, 409)


def segregation_of_duties(msg="approver cannot be the submitter"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, msg, 403)


def ownership_mismatch(msg="employee's department_id does not equal X-User-ID"):
    return ApiError(ERR_OWNERSHIP_MISMATCH, msg, 403)


def duplicate_band(msg="non-SUPERSEDED band already exists for (program, family, level, geo)"):
    return ApiError(ERR_DUPLICATE_BAND, msg, 409)


def duplicate_policy(msg="progression policy already exists for (family, from_level, to_level)"):
    return ApiError(ERR_DUPLICATE_POLICY, msg, 409)


def band_overlap_exceeds_policy(msg="unrounded overlap vs adjacent-lower band exceeds policy max"):
    return ApiError(ERR_BAND_OVERLAP_EXCEEDS_POLICY, msg, 422)


def progression_below_policy(msg="unrounded midpoint progression below policy min"):
    return ApiError(ERR_PROGRESSION_BELOW_POLICY, msg, 422)


def no_market_data(msg="pricing candidate set empty for the chosen variant"):
    return ApiError(ERR_NO_MARKET_DATA, msg, 422)


def geo_cycle(msg="geo zone parent chain forms a cycle"):
    return ApiError(ERR_GEO_CYCLE, msg, 422)


def profile_in_use(msg="retire attempted while ACTIVE employees reference the profile"):
    return ApiError(ERR_PROFILE_IN_USE, msg, 409)


def refresh_window_conflict(msg="planned window overlaps a non-terminal cycle of the same program"):
    return ApiError(ERR_REFRESH_WINDOW_CONFLICT, msg, 409)


def refresh_not_due(msg="apply attempted before effective_date"):
    return ApiError(ERR_REFRESH_NOT_DUE, msg, 409)


def reverse_window_expired(msg="reverse/rescind attempted after anchor + 30 days"):
    return ApiError(ERR_REVERSE_WINDOW_EXPIRED, msg, 422)


def cut_too_close(msg="market cut within 30 days of another cut for the same (job_profile_id, geo_zone_id)"):
    return ApiError(ERR_CUT_TOO_CLOSE, msg, 422)


def exception_rolling_cap(msg="employee already has 2 in-flight-or-approved exception requests in the trailing 365 days"):
    return ApiError(ERR_EXCEPTION_ROLLING_CAP, msg, 422)


def exception_cap_exceeded(msg="requested_salary_cents exceeds exception cap"):
    return ApiError(ERR_EXCEPTION_CAP_EXCEEDED, msg, 422)


def department_pool_exhausted(msg="positive adjustment exceeds department pool headroom"):
    return ApiError(ERR_DEPARTMENT_POOL_EXHAUSTED, msg, 422)


def budget_impact_exceeds(msg="refresh budget_impact_cents exceeds program refresh_budget_cents"):
    return ApiError(ERR_BUDGET_IMPACT_EXCEEDS, msg, 422)


def referenced_entity_state(msg="referenced entity in wrong state"):
    return ApiError(ERR_REFERENCED_ENTITY_STATE, msg, 422)
