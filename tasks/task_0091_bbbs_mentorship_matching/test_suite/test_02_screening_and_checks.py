"""Background screening, adjudication tolerances, and validity expiry.

Queue-B calculations/validations/cross-cutting translations on the screening axis.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

COORD = fx.COORD
SCREENER = fx.SCREENER
SPECIALIST = fx.SPECIALIST


def test_dmv_check_clears_at_adverse_tolerance(api):
    """PRD §3.1: "a `DMV` screen may be cleared if its `adverse_findings` is at
    most 1." PRD §3.1: "On a successful clear the screen moves `PENDING →
    CLEARED`".

    Design: Corner/calculations/background_check_dmv_adverse_tolerance_clears
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Dmv")
    api.submit_screening(vol["id"], SCREENER)
    # submit-screening cascades CRIMINAL, DMV, CHILD_ABUSE_REGISTRY in that order;
    # the DMV screen is the second created.
    _crim, dmv, _car = fx.screen_check_ids(vol["id"])
    resp = api.adjudicate_check(dmv, f.adjudicate_payload("CLEAR", 1), SCREENER)
    data = validate_success(resp, 200)
    assert data["status"] == "CLEARED", "DMV tolerates adverse_findings == 1"


def test_criminal_check_blocked_by_adverse_finding(api):
    """PRD §3.1: "a `CRIMINAL` or a `CHILD_ABUSE_REGISTRY` screen may be cleared
    only if its `adverse_findings` is exactly 0 ... If the supplied count exceeds
    the applicable tolerance, the clear is rejected with
    `ERR_ADVERSE_FINDING_BLOCKS_CLEAR` (HTTP 409) and the screen stays `PENDING`."

    Design: Corner/validations/adverse_finding_blocks_clear_on_criminal
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Af")
    api.submit_screening(vol["id"], SCREENER)
    crim, _dmv, _car = fx.screen_check_ids(vol["id"])
    resp = api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 1), SCREENER)
    validate_error(resp, ApiErrorId.ERR_ADVERSE_FINDING_BLOCKS_CLEAR.value, 409)
    # Screen stays PENDING.
    check = validate_success(api.get_background_check(crim, SCREENER), 200)
    assert check["status"] == "PENDING"


def test_clock_sweep_expires_background_check_and_clears_pointer(api):
    """PRD §3.1: "its `valid_until` is set to the adjudication instant plus
    twenty-four calendar months."
    PRD §3.2: "Any `CLEARED` screen whose `valid_until` is now at or before the
    current instant is moved `CLEARED → EXPIRED`; when an expiring screen is the
    one a volunteer's `cleared_check_id` points at, that pointer is cleared."

    Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_background_check
    """
    fx.set_clock(fx.REF_CLOCK)  # 2026-01-01
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Exp")
    crim, _dmv, _car = fx.submit_and_clear_screening(vol["id"])
    # Advance past valid_until (24 months after 2026-01-01 is 2028-01-01).
    fx.set_clock("2028-02-01T00:00:00Z")
    check = validate_success(api.get_background_check(crim, SCREENER), 200)
    assert check["status"] == "EXPIRED"
    volunteer = validate_success(api.get_volunteer(vol["id"], SPECIALIST), 200)
    assert volunteer["cleared_check_id"] is None
