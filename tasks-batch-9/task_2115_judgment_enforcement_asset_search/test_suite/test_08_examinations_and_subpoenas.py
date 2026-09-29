"""Compelling disclosure: examinations, their subpoena axis and the continuance cycle."""

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_debtor_examination,
    assert_sweep_summary_shape,
    issue_subpoena,
    issue_subpoena_payload,
    locate_debtor,
    make_case_manager_headers,
    read_examination,
    schedule_examination,
    setup_judgment,
    setup_scheduled_examination,
    setup_served_examination,
    validate_error,
    validate_success,
)

CM = make_case_manager_headers()


# ==========================================================================
# The two dimensions advance separately on one row
# ==========================================================================
def test_serving_the_order_disposes_of_both_dimensions_at_once(api):
    """PRD §3.4: "A new examination begins with `status` of `SCHEDULED`,
    `subpoena_status` of `NOT_ISSUED`, `continuance_count` of 0, and
    `subpoena_service_deadline_on` set to the calendar date of `scheduled_at` less
    10 days."
    PRD §3.4: "Service stamps `served_on`, and if the subpoena is sitting in
    `ISSUED` it moves `ISSUED → SERVED` on the same call, so one act of service
    disposes of both dimensions."
    PRD §2.10: "Debtor examinations carry a second dimension in the same way: the
    appearance order runs on `status`, while the duces-tecum subpoena runs
    independently on `subpoena_status`."

    Design: Difficulty/non_linear_state_machine/debtor_examination_scheduled_served_scheduled_continuance_cycle
    """
    ctx = setup_scheduled_examination(
        scheduled_at="2026-09-01T15:00:00Z",
        court_case_number="CV-2026-0302",
        filing_costs_cents=0,
    )
    assert ctx["examination"]["subpoena_service_deadline_on"] == "2026-08-22"

    issue_subpoena(
        ctx["examination"]["id"],
        recipient_type="EMPLOYER",
        recipient_name="Atlantic Freight Co",
    )

    served = validate_success(
        api.serve_examination(ctx["examination"]["id"], "2026-08-01", CM)
    )
    assert_debtor_examination(served)
    assert served["status"] == "SERVED"
    assert served["subpoena_status"] == "SERVED"


def test_a_continuance_returns_the_order_to_scheduled_without_moving_the_subpoena(api):
    """PRD §3.4: "It moves the examination `SERVED → SCHEDULED`, replaces
    `scheduled_at` with `new_scheduled_at`, increments `continuance_count` by one,
    clears `served_on`, and recomputes `subpoena_service_deadline_on` as the
    calendar date of the new `scheduled_at` less 10 days."
    PRD §3.4: "An examination may therefore cycle `SCHEDULED → SERVED →
    SCHEDULED` at most twice before it must resolve."

    Design: Difficulty/non_linear_state_machine/debtor_examination_scheduled_served_scheduled_continuance_cycle
    """
    ctx = setup_scheduled_examination(
        scheduled_at="2026-09-01T15:00:00Z",
        court_case_number="CV-2026-0306",
        filing_costs_cents=0,
    )
    issue_subpoena(
        ctx["examination"]["id"],
        recipient_type="EMPLOYER",
        recipient_name="Atlantic Freight Co",
    )
    validate_success(api.serve_examination(ctx["examination"]["id"], "2026-08-01", CM))

    continued = validate_success(
        api.record_examination_outcome(
            ctx["examination"]["id"],
            {"outcome": "CONTINUED", "new_scheduled_at": "2026-10-15T15:00:00Z"},
            CM,
        )
    )
    assert continued["status"] == "SCHEDULED"
    assert continued["continuance_count"] == 1
    assert continued["subpoena_service_deadline_on"] == "2026-10-05"

    stored = read_examination(ctx["examination"]["id"])
    assert stored["scheduled_at"].startswith("2026-10-15T15:00:00")
    assert stored.get("served_on") is None
    assert stored["subpoena_status"] == "SERVED"


# ==========================================================================
# Service depends on the debtor being locatable
# ==========================================================================
def test_serving_an_unlocated_debtor_is_refused(api):
    """PRD §3.4: "The judgment must be `ACTIVE`, the debtor's `locate_status` must
    be `LOCATED` — one cannot serve someone nobody can find, and attempting it is
    `ERR_DEBTOR_NOT_LOCATED` — and `served_on` must fall on or after the date 30
    days before the current clock date and on or before the current clock date
    itself, with anything outside that span rejected as `ERR_INVALID_REQUEST`."
    PRD §3.1: "Four investigative counters are server-owned: a freshly registered
    debtor has `locate_status` of `UNLOCATED`, a `skip_trace_count` of 0, a
    `no_show_count` of 0, and no `last_skip_trace_on` at all until the first trace
    runs."

    Design: Difficulty/cross_entity_state_dependency/exam_service_requires_located_debtor
    """
    ctx = setup_judgment(court_case_number="CV-2026-0705", filing_costs_cents=0)
    assert ctx["debtor"]["locate_status"] == "UNLOCATED"
    examination = schedule_examination(
        ctx["judgment"]["id"], scheduled_at="2026-09-01T15:00:00Z"
    )

    validate_error(
        api.serve_examination(examination["id"], "2026-08-01", CM),
        ApiErrorId.ERR_DEBTOR_NOT_LOCATED.value,
        409,
    )
    assert read_examination(examination["id"])["status"] == "SCHEDULED"


def test_a_completed_trace_unlocks_service_of_the_appearance_order(api):
    """PRD §3.3: "A trace with `located` true sets the debtor's `locate_status` to
    `LOCATED`."
    PRD §3.4: "Serving the appearance order moves the examination `SCHEDULED →
    SERVED` and takes `served_on`, the calendar date of service."

    Design: Difficulty/cross_entity_state_dependency/exam_service_requires_located_debtor
    """
    ctx = setup_judgment(court_case_number="CV-2026-0706", filing_costs_cents=0)
    examination = schedule_examination(
        ctx["judgment"]["id"], scheduled_at="2026-09-01T15:00:00Z"
    )
    validate_error(
        api.serve_examination(examination["id"], "2026-08-01", CM),
        ApiErrorId.ERR_DEBTOR_NOT_LOCATED.value,
        409,
    )

    traced = locate_debtor(ctx["debtor"]["id"], "inv-1", hits_count=4)
    assert traced["locate_status"] == "LOCATED"
    assert traced["skip_trace_count"] == 1

    served = validate_success(
        api.serve_examination(examination["id"], "2026-08-01", CM)
    )
    assert served["status"] == "SERVED"
    assert served["served_on"] == "2026-08-01"


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_recording_an_outcome_on_an_unserved_examination_is_refused(api):
    """PRD §3.4: "`HELD` moves it `SERVED → HELD` and stamps
    `outcome_recorded_on`; the debtor appeared and the matter is finished."
    PRD §2.8: "The target resource sits in one of the states from which the
    requested transition is legal — otherwise `ERR_INVALID_STATE` and HTTP 409.
    This applies to every state-transition endpoint."

    Design: Corner/state_machines/record_outcome_on_an_unserved_examination_rejected_as_invalid_state
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-2013", interest_rate_bps=0, filing_costs_cents=0
    )
    examination = schedule_examination(
        ctx["judgment"]["id"], scheduled_at="2026-09-01T15:00:00Z"
    )

    validate_error(
        api.record_examination_outcome(examination["id"], {"outcome": "HELD"}, CM),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )
    stored = read_examination(examination["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored.get("outcome_recorded_on") is None


def test_a_third_continuance_hits_the_continuance_ceiling(api):
    """PRD §3.4: "`CONTINUED` is the cyclic branch: it requires a
    `new_scheduled_at` in the payload, requires `continuance_count` to be strictly
    less than the ceiling of 2 continuances (a third attempt draws
    `ERR_CONTINUANCE_LIMIT`), and requires `new_scheduled_at` to satisfy the same
    120-day separation against every other live examination on the debtor."

    Design: Corner/state_machines/third_continuance_rejected_by_continuance_limit
    """
    ctx = setup_served_examination(
        scheduled_at="2026-09-01T15:00:00Z",
        court_case_number="CV-2026-2014",
        interest_rate_bps=0,
        filing_costs_cents=0,
    )
    examination_id = ctx["examination"]["id"]

    first = validate_success(
        api.record_examination_outcome(
            examination_id,
            {"outcome": "CONTINUED", "new_scheduled_at": "2026-10-15T15:00:00Z"},
            CM,
        )
    )
    assert first["continuance_count"] == 1
    validate_success(api.serve_examination(examination_id, "2026-08-01", CM))

    second = validate_success(
        api.record_examination_outcome(
            examination_id,
            {"outcome": "CONTINUED", "new_scheduled_at": "2026-12-01T15:00:00Z"},
            CM,
        )
    )
    assert second["continuance_count"] == 2
    validate_success(api.serve_examination(examination_id, "2026-08-01", CM))

    validate_error(
        api.record_examination_outcome(
            examination_id,
            {"outcome": "CONTINUED", "new_scheduled_at": "2027-01-15T15:00:00Z"},
            CM,
        ),
        ApiErrorId.ERR_CONTINUANCE_LIMIT.value,
        409,
    )

    stored = read_examination(examination_id)
    assert stored["continuance_count"] == 2
    assert stored["scheduled_at"].startswith("2026-12-01T15:00:00")
    assert stored["status"] == "SERVED"


def test_issuing_a_subpoena_after_its_lead_deadline_is_refused(api):
    """PRD §3.4: "Issuing a duces-tecum subpoena requires the examination's own
    status dimension to still be `SCHEDULED` and the current clock date to fall on
    or before `subpoena_service_deadline_on`; issuing later is refused with
    `ERR_SUBPOENA_DEADLINE_PASSED`."

    Design: Corner/validations/subpoena_issued_after_the_lead_deadline_returns_deadline_passed
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4005", interest_rate_bps=0, filing_costs_cents=0
    )
    examination = schedule_examination(
        ctx["judgment"]["id"], scheduled_at="2026-09-01T15:00:00Z"
    )
    assert examination["subpoena_service_deadline_on"] == "2026-08-22"

    advance_clock("2026-08-23T00:00:00Z")

    validate_error(
        api.issue_subpoena(
            examination["id"],
            issue_subpoena_payload(
                recipient_type="THIRD_PARTY_BANK", recipient_name="First Pacific Bank"
            ),
            CM,
        ),
        ApiErrorId.ERR_SUBPOENA_DEADLINE_PASSED.value,
        422,
    )
    assert read_examination(examination["id"])["subpoena_status"] == "NOT_ISSUED"


def test_the_sweep_expires_the_subpoena_without_touching_the_appearance_order(api):
    """PRD §2.5: "**Step 4 — lapsed subpoenas.** Every subpoena in `ISSUED` on an
    examination whose own status dimension is still `SCHEDULED`, and whose
    `subpoena_service_deadline_on` falls strictly before the new clock date,
    becomes `EXPIRED`."
    PRD §3.4: "If the examination is never served and the clock passes the
    deadline while the examination's status dimension is still `SCHEDULED`, the
    sweep moves the subpoena `ISSUED → EXPIRED`, which is terminal on that axis."
    PRD §3.4: "Issuance moves `subpoena_status` `NOT_ISSUED → ISSUED` and stamps
    those two values onto the examination row as `subpoena_recipient_type` and
    `subpoena_recipient_name` respectively."

    Design: Corner/state_machines/clock_sweep_expires_issued_subpoena_without_touching_examination_status
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-2010", interest_rate_bps=0, filing_costs_cents=0
    )
    examination = schedule_examination(
        ctx["judgment"]["id"], scheduled_at="2026-09-01T15:00:00Z"
    )
    assert examination["subpoena_service_deadline_on"] == "2026-08-22"

    issued = issue_subpoena(
        examination["id"],
        recipient_type="EMPLOYER",
        recipient_name="Atlantic Freight Co",
    )
    assert issued["subpoena_status"] == "ISSUED"
    assert issued["subpoena_recipient_type"] == "EMPLOYER"

    summary = advance_clock("2026-08-23T00:00:00Z")
    assert_sweep_summary_shape(summary)
    assert summary["expired_subpoena_count"] == 1

    stored = read_examination(examination["id"])
    assert stored["subpoena_status"] == "EXPIRED"
    assert stored["status"] == "SCHEDULED"
