"""Error catalogue (PRD section 5 / scaffold 1.6) and the carrying exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = CATALOG[error_id][0]
        self.message = message or CATALOG[error_id][1]


CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (
        400, "X-User-ID or X-User-Role header is missing or empty."),
    "ERR_FORBIDDEN_FOR_ROLE": (
        403, "The caller's role is not permitted for this endpoint."),
    "ERR_NOT_FOUND": (
        404, "A referenced resource does not exist."),
    "ERR_INVALID_REQUEST": (
        400, "The request payload is malformed, missing a required field, "
             "or carries an invalid enum or out-of-range value."),
    "ERR_DEPOSIT_SEGMENT_REQUIRED": (
        422, "category=DEPOSIT requires deposit_segment."),
    "ERR_ASSUMPTION_PARAMS_MISMATCH": (
        422, "params keys do not exactly match the assumption set's domain schema."),
    "ERR_OBSERVED_VALUE_INVALID": (
        422, "observed_value_pct must lie within [0, 100]."),
    "ERR_STALE_VERSION": (
        412, "expected_book_version does not match the book's current version."),
    "ERR_INVALID_STATE_TRANSITION": (
        409, "The requested transition is not legal from the resource's current state."),
    "ERR_BOOK_NOT_ACTIVE": (
        409, "Simulation run creation requires the book to be ACTIVE."),
    "ERR_BOOK_ACTIVATION_INCOMPLETE": (
        409, "Activation requires at least one ACTIVE asset and one ACTIVE "
             "liability position."),
    "ERR_SEGREGATION_OF_DUTIES": (
        409, "Segregation of duties forbids this action."),
    "ERR_ASSUMPTION_NOT_APPROVED": (
        409, "A pinned assumption set is not APPROVED."),
    "ERR_ASSUMPTION_UNDER_REVIEW": (
        409, "A pinned assumption set has an OPEN BREACH backtest review."),
    "ERR_SCENARIO_NOT_ACTIVE": (
        409, "The referenced scenario is not ACTIVE."),
    "ERR_LIMIT_SCOPE_CONFLICT": (
        409, "An ACTIVE policy limit already exists for the same "
             "(book, metric, applies_to_kinds) scope."),
    "ERR_REPORT_PERIOD_CONFLICT": (
        409, "A non-terminal ALCO report already exists for this book and period."),
    "ERR_OPEN_BREACHES_REMAIN": (
        409, "The report period still has open breaches."),
    "ERR_REGULATORY_COVERAGE_INCOMPLETE": (
        409, "The period lacks a PUBLISHED run for at least one regulatory preset."),
    "ERR_POSITION_RETIRED": (
        409, "The hedged position is RETIRED."),
    "ERR_POSITION_HAS_ACTIVE_HEDGE": (
        409, "A PROPOSED, DESIGNATED, or ACTIVE hedge references this position."),
    "ERR_HEDGE_WINDOW_OVERLAP": (
        409, "The designation window overlaps another DESIGNATED/ACTIVE hedge "
             "on the same position."),
    "ERR_DESIGNATION_WINDOW_PAST": (
        409, "start_month is before the current logical month."),
    "ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE": (
        409, "notional_cents exceeds the hedged position's balance_cents."),
    "ERR_HEDGE_NOT_ACTIVATABLE": (
        409, "The hedge cannot be activated before its designation start_month."),
    "ERR_BACKTEST_WINDOW_NOT_ELAPSED": (
        409, "The observation window has not fully elapsed relative to the "
             "logical clock."),
    "ERR_BACKTEST_WINDOW_OVERLAP": (
        409, "The review window overlaps or abuts an existing review window on "
             "the same assumption set (a gap of at least one month is required)."),
    "ERR_BACKTEST_CLOSURE_REQUIRES_REVISION": (
        409, "CLOSED_REVISED requires a newer APPROVED assumption set in the "
             "same book and domain."),
}
