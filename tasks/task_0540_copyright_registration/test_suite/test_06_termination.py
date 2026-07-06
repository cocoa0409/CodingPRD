"""Statutory termination window boundaries and the termination cascade.

Covers Difficulty queue instance termination_window_earliest_boundary and the
termination-before-window / termination-cascade corner instances.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty — termination_window_earliest_boundary
# ==========================================================================
def test_effective_date_at_window_earliest_accepted(api, examiner_headers):
    """PRD §3.7: "the window_earliest_date is the grant_date plus 35 years" and
    effectuation "is only permitted when the requested effective_date falls on or
    after window_earliest_date and on or before window_latest_date."

    Design: Difficulty/boundary_precision_check/termination_window_earliest_boundary
    """
    # grant 1990-06-01 -> window_earliest = 2025-06-01; effective_date == earliest.
    _work, lic, term = fx.setup_license_for_termination(
        grant_date="1990-06-01T00:00:00Z", effective_date="2025-06-01T00:00:00Z",
    )
    effectuated = validate_success(api.effectuate_termination(term["id"], examiner_headers), 200)
    assert effectuated["status"] == "EFFECTIVE"
    assert fx.get_license(lic["id"])["status"] == "TERMINATED"


def test_effective_date_at_window_latest_accepted(api, examiner_headers):
    """PRD §3.7: "the window_latest_date is that earliest date plus a further 5
    years. These bounds are calendar-year arithmetic and both ends are inclusive."
    (effectuation permitted "on or before window_latest_date")

    Design: Difficulty/boundary_precision_check/termination_window_earliest_boundary
    """
    # grant 1990-06-01 -> earliest 2025-06-01, latest 2030-06-01; effective_date == latest.
    _work, lic, term = fx.setup_license_for_termination(
        grant_date="1990-06-01T00:00:00Z", effective_date="2030-06-01T00:00:00Z",
    )
    effectuated = validate_success(api.effectuate_termination(term["id"], examiner_headers), 200)
    assert effectuated["status"] == "EFFECTIVE"
    assert fx.get_license(lic["id"])["status"] == "TERMINATED"


# ==========================================================================
# Corner — termination before window earliest
# ==========================================================================
def test_effective_date_before_window_earliest_rejected(api, examiner_headers):
    """PRD §3.7: "an effective date outside that inclusive window is rejected with
    ERR_TERMINATION_WINDOW."

    Design: Corner/calculations/termination_before_window_earliest_returns_window_error
    """
    # grant 1990-06-01 -> earliest 2025-06-01; effective_date one day before.
    _work, _lic, term = fx.setup_license_for_termination(
        grant_date="1990-06-01T00:00:00Z", effective_date="2025-05-31T00:00:00Z",
    )
    validate_error(api.effectuate_termination(term["id"], examiner_headers), ApiErrorId.ERR_TERMINATION_WINDOW)


# ==========================================================================
# Corner — termination cascade reverses posted statements
# ==========================================================================
def test_termination_cascade_reverses_posted_and_zeroes_escrow(api, rightsholder_headers, examiner_headers):
    """PRD §3.7: "the parent license is moved to TERMINATED (link A ...); every
    royalty statement under that license which is POSTED is moved to REVERSED
    (link B, because the license terminated); and the license's escrow_balance_cents
    is driven to zero (link C, because those statements were reversed)."

    Design: Corner/state_machines/termination_cascade_reverses_posted_statements
    """
    _work, lic, term = fx.setup_license_for_termination(effective_date="2026-06-01T00:00:00Z")
    rs = fx.create_draft_statement(lic["id"])
    fx.post_statement(rs["id"])
    assert fx.get_license(lic["id"])["escrow_balance_cents"] > 0
    validate_success(api.effectuate_termination(term["id"], examiner_headers), 200)
    assert fx.get_license(lic["id"])["status"] == "TERMINATED"
    assert fx.get_royalty_statement(rs["id"])["status"] == "REVERSED"
    assert fx.get_license(lic["id"])["escrow_balance_cents"] == 0
