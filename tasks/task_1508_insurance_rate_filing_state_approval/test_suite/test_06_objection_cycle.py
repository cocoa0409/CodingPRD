"""The objection cycle: SLA clock, reopen loop, overdue sweep, OCC (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    draft_response,
    find_calendar_entry,
    get_success_data,
    raise_objection,
    set_clock,
    setup_submitted_filing,
    submit_response,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_reopen_restarts_sla_and_drags_filing_back(api):
    """PRD §3.4: "Reopening — allowed repeatedly, making the objection
    lifecycle cyclic — moves a `RESPONSE_SUBMITTED` objection to `REOPENED`,
    increments `reopen_count` by one, restarts the service clock by recomputing
    `due_at` as the reopen time plus `objection_response_sla_days`, opens a
    fresh `PENDING` `OBJECTION_RESPONSE_DUE` entry, and pulls the filing back
    to `UNDER_OBJECTION` with `open_objection_count` recomputed."

    Design: Difficulty/non_linear_state_machine/objection_reopen_revision_cycle
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Justify the trend factor.")
    assert_instant_equals(objection["due_at"], "2026-09-09T12:00:00Z")

    set_clock("2026-08-15T00:00:00Z")
    response = draft_response(objection["id"], objection["version"], "Trend support attached.")
    submit_response(response["id"])

    set_clock("2026-08-20T00:00:00Z")
    reopened = validate_success(api.reopen_objection(objection["id"], fx.REGULATOR), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    # Fresh SLA: 2026-08-20T00:00:00Z + 30 days = 2026-09-19T00:00:00Z.
    assert_instant_equals(reopened["due_at"], "2026-09-19T00:00:00Z")

    filing = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert filing["status"] == "UNDER_OBJECTION"
    assert filing["open_objection_count"] == 1


def test_objection_cycle_resolves_and_filing_bubbles_up(api):
    """PRD §3.4: "Resolving a `RESPONSE_SUBMITTED` objection moves it to the
    terminal state `RESOLVED` with `resolved_at` stamped."
    PRD §3.4: "A filing returns from `UNDER_OBJECTION` to `SUBMITTED` —
    bubbling up automatically — as soon as none of its objections remains in
    `RAISED`, `RESPONSE_DRAFTED`, `OVERDUE`, or `REOPENED`."

    Design: Difficulty/non_linear_state_machine/objection_reopen_revision_cycle
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Justify the trend factor.")
    set_clock("2026-08-15T00:00:00Z")
    response = draft_response(objection["id"], objection["version"], "Trend support attached.")
    submit_response(response["id"])

    set_clock("2026-08-20T00:00:00Z")
    validate_success(api.reopen_objection(objection["id"], fx.REGULATOR), 200)
    current = get_success_data(api.get_objection(objection["id"], fx.REGULATOR))
    response2 = draft_response(
        objection["id"], current["version"], "Additional exhibits attached."
    )
    submit_response(response2["id"])
    resolved = validate_success(
        api.resolve_objection(objection["id"], fx.REGULATOR), 200
    )
    assert resolved["status"] == "RESOLVED"

    filing = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert filing["status"] == "SUBMITTED"
    assert filing["open_objection_count"] == 0


def test_response_submitted_at_deadline_is_on_time(api):
    """PRD §3.4: "Timeliness is judged at the deadline with equality counting
    as on time: a response submitted at or before `due_at` resolves the
    `OBJECTION_RESPONSE_DUE` calendar entry to `MET`, while a response
    submitted after `due_at` sets the objection's `late_breach` to true."

    Design: Difficulty/boundary_precision_check/objection_response_deadline_inclusive
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Provide territorial exhibits.")
    response = draft_response(objection["id"], objection["version"], "Exhibits attached.")

    # Clock at exactly the deadline: equality is on time.
    set_clock("2026-09-09T12:00:00Z")
    submitted = submit_response(response["id"])
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-09-09T12:00:00Z")

    after = get_success_data(api.get_objection(objection["id"], fx.OFFICER))
    assert after["status"] == "RESPONSE_SUBMITTED"
    assert after["late_breach"] is False

    entry = find_calendar_entry(
        objection_id=objection["id"], entry_type="OBJECTION_RESPONSE_DUE"
    )
    assert entry["status"] == "MET"


def test_response_submitted_after_deadline_breaches(api):
    """PRD §3.4: "Timeliness is judged at the deadline with equality counting
    as on time: a response submitted at or before `due_at` resolves the
    `OBJECTION_RESPONSE_DUE` calendar entry to `MET`, while a response
    submitted after `due_at` sets the objection's `late_breach` to true."
    PRD §3.4: "Meanwhile the clock sweep watches silence: an objection still in
    `RAISED` or `RESPONSE_DRAFTED` when the logical clock passes `due_at`
    becomes `OVERDUE`, its `late_breach` is set true, and its calendar entry
    becomes `MISSED`."

    Design: Difficulty/boundary_precision_check/objection_response_deadline_inclusive
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Provide territorial exhibits.")
    draft_response(objection["id"], objection["version"], "Exhibits attached.")

    # One second past the deadline: the sweep flips the objection to OVERDUE.
    set_clock("2026-09-09T12:00:01Z")
    overdue = get_success_data(api.get_objection(objection["id"], fx.OFFICER))
    assert overdue["status"] == "OVERDUE"
    assert overdue["late_breach"] is True

    redraft = draft_response(objection["id"], overdue["version"], "Final exhibits.")
    submit_response(redraft["id"])
    after = get_success_data(api.get_objection(objection["id"], fx.OFFICER))
    assert after["status"] == "RESPONSE_SUBMITTED"
    assert after["late_breach"] is True


def test_resolved_objection_rejects_reopen(api):
    """PRD §3.4: "Resolving a `RESPONSE_SUBMITTED` objection moves it to the
    terminal state `RESOLVED` with `resolved_at` stamped."
    PRD §3.4: "Reopening — allowed repeatedly, making the objection lifecycle
    cyclic — moves a `RESPONSE_SUBMITTED` objection to `REOPENED`".

    Design: Corner/state_machines/resolved_objection_terminal_lockdown
    """
    scenario = setup_submitted_filing()
    objection = raise_objection(scenario["filing"]["id"], "Trend support?")
    response = draft_response(objection["id"], objection["version"], "See exhibit A.")
    submit_response(response["id"])
    resolved = validate_success(
        api.resolve_objection(objection["id"], fx.REGULATOR), 200
    )
    assert resolved["status"] == "RESOLVED"

    res = api.reopen_objection(objection["id"], fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_objection(objection["id"], fx.REGULATOR))
    assert after["status"] == "RESOLVED"


def test_overdue_objection_late_response_cycle(api):
    """PRD §3.4: "Meanwhile the clock sweep watches silence: an objection still
    in `RAISED` or `RESPONSE_DRAFTED` when the logical clock passes `due_at`
    becomes `OVERDUE`, its `late_breach` is set true, and its calendar entry
    becomes `MISSED`."
    PRD §3.4: "An objection that went `OVERDUE` before being answered keeps its
    `late_breach` flag true — lateness, once incurred, is permanent."

    Design: Corner/state_machines/overdue_objection_late_response_cycle
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Expense exhibit?")
    set_clock("2026-08-15T00:00:00Z")
    first = draft_response(objection["id"], objection["version"], "Draft in progress.")

    set_clock("2026-09-10T00:00:00Z")
    overdue = get_success_data(api.get_objection(objection["id"], fx.ANALYST))
    assert overdue["status"] == "OVERDUE"
    assert overdue["late_breach"] is True
    entry = find_calendar_entry(
        objection_id=objection["id"], entry_type="OBJECTION_RESPONSE_DUE"
    )
    assert entry["status"] == "MISSED"

    # Re-drafting from OVERDUE supersedes the stale draft.
    second = draft_response(
        objection["id"], overdue["version"], "Final answer with exhibits."
    )
    first_after = get_success_data(api.get_response(first["id"], fx.ANALYST))
    assert first_after["status"] == "SUPERSEDED"

    submitted = submit_response(second["id"])
    assert submitted["status"] == "SUBMITTED"
    final = get_success_data(api.get_objection(objection["id"], fx.OFFICER))
    assert final["status"] == "RESPONSE_SUBMITTED"
    assert final["late_breach"] is True

    # A resolved entry never reopens.
    entry_after = find_calendar_entry(
        objection_id=objection["id"], entry_type="OBJECTION_RESPONSE_DUE"
    )
    assert entry_after["status"] == "MISSED"


def test_response_draft_occ_and_supersession(api):
    """PRD §2.7: "Drafting an objection response requires
    `expected_objection_version`, carrying the version of the parent Objection
    the client last observed. If the objection's current `version` has advanced
    since that observation — for example because another analyst has already
    drafted a response, which supersedes the prior draft position — the draft
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "each draft creates an ObjectionResponse in `DRAFT` status,
    records the analyst as `drafted_by_user_id`, supersedes any prior `DRAFT`
    response on the same objection (that response moves to `SUPERSEDED`), moves
    the objection itself to `RESPONSE_DRAFTED`, and increments the objection's
    `version` by one."

    Design: Corner/cross_cutting_layers/occ_response_draft_stale_then_fresh_supersedes
    """
    scenario = setup_submitted_filing()
    objection = raise_objection(scenario["filing"]["id"], "Trend support?")
    stale_version = objection["version"]

    first = draft_response(objection["id"], stale_version, "Draft one.")
    assert first["status"] == "DRAFT"

    # The first draft bumped the objection's version: replaying is stale.
    res = api.draft_response(
        objection["id"],
        {"response_text": "Draft two (stale).", "expected_objection_version": stale_version},
        fx.ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    current = get_success_data(api.get_objection(objection["id"], fx.ANALYST))
    assert current["version"] == stale_version + 1

    second = validate_success(
        api.draft_response(
            objection["id"],
            {
                "response_text": "Draft two (fresh).",
                "expected_objection_version": current["version"],
            },
            fx.ANALYST,
        ),
        201,
    )
    assert second["status"] == "DRAFT"

    first_after = get_success_data(api.get_response(first["id"], fx.ANALYST))
    assert first_after["status"] == "SUPERSEDED"


def test_open_objection_count_reconciles(api):
    """PRD §3.4: "The first objection against a `SUBMITTED` filing moves that
    filing to `UNDER_OBJECTION`, and each objection event recomputes the
    filing's `open_objection_count` — the count of its objections in `RAISED`,
    `RESPONSE_DRAFTED`, `RESPONSE_SUBMITTED`, `OVERDUE`, or `REOPENED`."

    Design: Corner/cross_cutting_layers/derived_open_objection_count_reconciled
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]
    assert scenario["filing"]["open_objection_count"] == 0

    first = raise_objection(filing_id, "Q1")
    second = raise_objection(filing_id, "Q2")
    mid = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert mid["open_objection_count"] == 2
    assert mid["status"] == "UNDER_OBJECTION"

    get_success_data(api.withdraw_objection(first["id"], fx.REGULATOR))
    get_success_data(api.withdraw_objection(second["id"], fx.REGULATOR))
    final = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert final["open_objection_count"] == 0
    assert final["status"] == "SUBMITTED"
