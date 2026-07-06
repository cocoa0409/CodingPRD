"""Examination / correspondence cycle and deposit acceptance state rules.

Covers Difficulty queue instance application_correspondence_cycle and the deposit
idempotency corner instance.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty — application_correspondence_cycle
# ==========================================================================
def test_two_correspondence_rounds_return_to_examination(api, rightsholder_headers, examiner_headers):
    """PRD §3.3: "An Examiner may open a correspondence request, moving the
    application from UNDER_EXAMINATION to CORRESPONDENCE; this requires an
    issue_code and a message, sets correspondence_open to true ... and increments
    correspondence_rounds by 1. The applicant then responds ... which moves the
    application from CORRESPONDENCE back to UNDER_EXAMINATION and clears
    correspondence_open to false. Because the examiner may open correspondence
    again after each response, correspondence_rounds accumulates one per cycle."

    Design: Difficulty/non_linear_state_machine/application_correspondence_cycle
    """
    _work, app = fx.setup_application_under_examination()
    aid = app["id"]
    fx.get_success_data(api.issue_correspondence(aid, fac.issue_correspondence_payload(), examiner_headers))
    fx.get_success_data(api.respond_correspondence(aid, fac.respond_correspondence_payload(), rightsholder_headers))
    fx.get_success_data(
        api.issue_correspondence(aid, fac.issue_correspondence_payload(issue_code="OTHER", message="again"), examiner_headers)
    )
    final = validate_success(
        api.respond_correspondence(aid, fac.respond_correspondence_payload(message="answered"), rightsholder_headers), 200
    )
    assert final["status"] == "UNDER_EXAMINATION"
    assert final["correspondence_rounds"] == 2
    assert final["correspondence_open"] is False


def test_single_correspondence_round_increments_counter(api, examiner_headers):
    """PRD §3.3: "An Examiner may open a correspondence request, moving the
    application from UNDER_EXAMINATION to CORRESPONDENCE; this requires an
    issue_code and a message, sets correspondence_open to true, sets the
    correspondence_deadline to the clock time plus CORRESPONDENCE_DAYS days, and
    increments correspondence_rounds by 1."

    Design: Difficulty/non_linear_state_machine/application_correspondence_cycle
    """
    _work, app = fx.setup_application_under_examination()
    opened = validate_success(
        api.issue_correspondence(app["id"], fac.issue_correspondence_payload(), examiner_headers), 200
    )
    assert opened["status"] == "CORRESPONDENCE"
    assert opened["correspondence_open"] is True
    assert opened["correspondence_rounds"] == 1


# ==========================================================================
# Corner — deposit idempotency (accept twice)
# ==========================================================================
def test_accept_already_accepted_deposit_rejected(api, rightsholder_headers, examiner_headers):
    """PRD §3.2: "Both accept and reject require the deposit to still be SUBMITTED,
    otherwise ERR_INVALID_STATE."

    Design: Corner/state_machines/deposit_accept_twice_returns_invalid_state
    """
    work = fx.create_work()
    app = fx.create_application(work["id"])
    dep = fx.get_success_data(api.create_deposit(fac.create_deposit_payload(app["id"]), rightsholder_headers))
    fx.get_success_data(api.accept_deposit(dep["id"], examiner_headers))
    resp = api.accept_deposit(dep["id"], examiner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
