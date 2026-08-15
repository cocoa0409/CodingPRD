"""Approval, deemed approval, and effective-date resolution (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    draft_response,
    get_success_data,
    raise_objection,
    set_clock,
    setup_approved_filing,
    setup_draft_filing,
    setup_submitted_filing,
    submit_response,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_prior_approval_effective_date_includes_lead_time(api):
    """PRD §3.5: "Under `PRIOR_APPROVAL`, the `actual_effective_date` is the
    later of the `proposed_effective_date` and the approval date plus
    `min_effective_lead_days` — the lead time can push effectiveness past the
    proposal."

    Design: Difficulty/dual_variant_calc/effective_date_prior_approval_vs_file_and_use
    """
    scenario = setup_approved_filing(approve_at="2026-09-01T00:00:00Z")
    filing = scenario["filing"]
    assert filing["status"] == "APPROVED"
    # max(2026-10-01, 2026-09-01 + 45d = 2026-10-16) = 2026-10-16
    assert filing["actual_effective_date"] == "2026-10-16"


def test_file_and_use_effective_date_keeps_proposal(api):
    """PRD §3.5: "Under `FILE_AND_USE` and `USE_AND_FILE`, the
    `actual_effective_date` is exactly the `proposed_effective_date`,
    regardless of when approval arrives."

    Design: Difficulty/dual_variant_calc/effective_date_prior_approval_vs_file_and_use
    """
    scenario = setup_approved_filing(
        state_code="NV",
        approve_at="2026-09-01T00:00:00Z",
        profile_overrides={"filing_method": "FILE_AND_USE", "deemer_days": 0},
    )
    filing = scenario["filing"]
    assert filing["status"] == "APPROVED"
    assert filing["actual_effective_date"] == "2026-10-01"


def test_approve_succeeds_with_zero_open_objections(api):
    """PRD §3.5: "A `StateRegulator` approves a `SUBMITTED` filing only when
    the objection ledger is clean: `open_objection_count` must be zero, meaning
    every objection is `RESOLVED` or `WITHDRAWN`, and an approval attempted
    with open objections is rejected with `ERR_OPEN_OBJECTIONS` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/approve_with_zero_open_objections
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    first = raise_objection(filing_id, "Q1: trend support.")
    second = raise_objection(filing_id, "Q2: expense load.")
    get_success_data(api.withdraw_objection(first["id"], fx.REGULATOR))
    get_success_data(api.withdraw_objection(second["id"], fx.REGULATOR))

    before = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert before["status"] == "SUBMITTED"
    assert before["open_objection_count"] == 0

    set_clock("2026-09-01T00:00:00Z")
    approved = validate_success(api.approve_filing(filing_id, fx.REGULATOR), 200)
    assert approved["status"] == "APPROVED"
    assert approved["actual_effective_date"] == "2026-10-16"


def test_approve_succeeds_after_objection_resolved(api):
    """PRD §3.5: "A `StateRegulator` approves a `SUBMITTED` filing only when
    the objection ledger is clean: `open_objection_count` must be zero, meaning
    every objection is `RESOLVED` or `WITHDRAWN`".

    Design: Difficulty/boundary_precision_check/approve_with_zero_open_objections
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    objection = raise_objection(filing_id, "Trend support?")
    response = draft_response(objection["id"], objection["version"], "See exhibit A.")
    submit_response(response["id"])
    get_success_data(api.resolve_objection(objection["id"], fx.REGULATOR))

    before = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert before["open_objection_count"] == 0

    set_clock("2026-09-01T00:00:00Z")
    approved = validate_success(api.approve_filing(filing_id, fx.REGULATOR), 200)
    assert approved["status"] == "APPROVED"


def test_approve_blocked_by_response_submitted_objection(api):
    """PRD §3.4: "An objection in `RESPONSE_SUBMITTED` therefore does not hold
    the filing in `UNDER_OBJECTION`; yet note the deliberate asymmetry that
    `RESPONSE_SUBMITTED` still counts toward `open_objection_count`, so the
    filing cannot be approved until every objection is fully `RESOLVED` or
    `WITHDRAWN` (§3.5)."
    PRD §3.5: "an approval attempted with open objections is rejected with
    `ERR_OPEN_OBJECTIONS` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_response_submitted_objection
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Trend support?")
    set_clock("2026-08-15T00:00:00Z")
    response = draft_response(objection["id"], objection["version"], "See exhibit A.")
    submit_response(response["id"])

    # Filing bubbled back to SUBMITTED, yet the count still blocks approval.
    before = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert before["status"] == "SUBMITTED"
    assert before["open_objection_count"] == 1

    res = api.approve_filing(filing_id, fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_OPEN_OBJECTIONS)
    after = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert after["status"] == "SUBMITTED"


def test_approve_blocked_with_one_resolved_one_submitted(api):
    """PRD §3.5: "an approval attempted with open objections is rejected with
    `ERR_OPEN_OBJECTIONS` (HTTP 409)."
    PRD §3.4: "yet note the deliberate asymmetry that `RESPONSE_SUBMITTED`
    still counts toward `open_objection_count`, so the filing cannot be
    approved until every objection is fully `RESOLVED` or `WITHDRAWN`".

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_response_submitted_objection
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    resolved_one = raise_objection(filing_id, "Q1")
    resp1 = draft_response(resolved_one["id"], resolved_one["version"], "A1")
    submit_response(resp1["id"])
    get_success_data(api.resolve_objection(resolved_one["id"], fx.REGULATOR))

    open_one = raise_objection(filing_id, "Q2")
    resp2 = draft_response(open_one["id"], open_one["version"], "A2")
    submit_response(resp2["id"])

    before = get_success_data(api.get_filing(filing_id, fx.REGULATOR))
    assert before["open_objection_count"] == 1

    res = api.approve_filing(filing_id, fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_OPEN_OBJECTIONS)


def test_deemed_approval_fires_at_deemer_date(api):
    """PRD §3.5: "During each clock sweep, a `SUBMITTED` filing whose
    `deemer_date` has been reached — the rule fires at 00:00:00Z of that date,
    so reaching the deemer date itself is enough — becomes `DEEMED_APPROVED`".
    PRD §3.5: "A deemed approval stamps `approved_at` as 00:00:00Z of the
    deemer date, resolves `actual_effective_date` with that deemed approval
    time standing in for the approval instant".

    Design: Corner/state_machines/deemed_approval_fires_at_deemer_date
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]
    assert scenario["filing"]["deemer_date"] == "2026-09-30"  # 08-01 + 60d

    set_clock("2026-09-29T00:00:00Z")
    before = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert before["status"] == "SUBMITTED"

    set_clock("2026-09-30T00:00:00Z")
    after = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert after["status"] == "DEEMED_APPROVED"
    assert_instant_equals(after["approved_at"], "2026-09-30T00:00:00Z")
    # max(2026-10-01, 2026-09-30 + 45d = 2026-11-14)
    assert after["actual_effective_date"] == "2026-11-14"


def test_deemer_tolls_while_objection_open(api):
    """PRD §3.5: "becomes `DEEMED_APPROVED`, but only while no objection of the
    filing is non-terminal: the deemer tolls for as long as any objection sits
    in `RAISED`, `RESPONSE_DRAFTED`, `RESPONSE_SUBMITTED`, `OVERDUE`, or
    `REOPENED`."
    PRD §3.5: "A deemed approval stamps `approved_at` as 00:00:00Z of the
    deemer date".

    Design: Corner/state_machines/deemed_approval_tolls_while_objection_open
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-10T12:00:00Z")
    objection = raise_objection(filing_id, "Provide ratemaking exhibits.")

    # Past the 2026-09-30 deemer with the objection unanswered: still tolled.
    set_clock("2026-10-05T00:00:00Z")
    overdue = get_success_data(api.get_objection(objection["id"], fx.OFFICER))
    assert overdue["status"] == "OVERDUE"
    assert overdue["late_breach"] is True
    tolled = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert tolled["status"] == "UNDER_OBJECTION"

    get_success_data(api.withdraw_objection(objection["id"], fx.REGULATOR))
    set_clock("2026-10-06T00:00:00Z")
    final = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert final["status"] == "DEEMED_APPROVED"
    # approved_at is pinned to the deemer date, not the fire date.
    assert_instant_equals(final["approved_at"], "2026-09-30T00:00:00Z")


def test_deemed_approved_filing_marks_effective(api):
    """PRD §3.5: "From `APPROVED` or `DEEMED_APPROVED`, the filing may be
    marked effective once the current date has reached the
    `actual_effective_date`".

    Design: Corner/state_machines/deemed_approved_filing_marks_effective
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    set_clock("2026-09-30T00:00:00Z")
    deemed = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert deemed["status"] == "DEEMED_APPROVED"
    assert deemed["actual_effective_date"] == "2026-11-14"

    set_clock("2026-11-14T00:00:00Z")
    effective = validate_success(api.mark_filing_effective(filing_id, fx.OFFICER), 200)
    assert effective["status"] == "EFFECTIVE"
    assert effective["actual_effective_date"] == "2026-11-14"


def test_use_and_file_effectiveness_precedes_approval(api):
    """PRD §3.5: "Use-and-file states permit a shortcut: a filing whose profile
    uses `USE_AND_FILE` may be marked effective directly from `SUBMITTED` —
    against any other filing method the attempt draws `ERR_INVALID_STATE` —
    once the current date has reached the `proposed_effective_date`, with the
    same ratebook overlap check; the `actual_effective_date` is then simply the
    `proposed_effective_date`".

    Design: Corner/state_machines/use_and_file_effectiveness_precedes_approval
    """
    scenario = setup_submitted_filing(
        state_code="OR",
        proposed_effective_date="2026-08-20",
        profile_overrides={"filing_method": "USE_AND_FILE", "deemer_days": 0},
    )
    filing_id = scenario["filing"]["id"]

    set_clock("2026-08-20T00:00:00Z")
    effective = validate_success(api.mark_filing_effective(filing_id, fx.OFFICER), 200)
    assert effective["status"] == "EFFECTIVE"
    assert effective["actual_effective_date"] == "2026-08-20"
    assert effective["approved_at"] is None


def test_prior_approval_mark_effective_blocked_from_submitted(api):
    """PRD §3.5: "a filing whose profile uses `USE_AND_FILE` may be marked
    effective directly from `SUBMITTED` — against any other filing method the
    attempt draws `ERR_INVALID_STATE`".

    Design: Corner/state_machines/prior_approval_mark_effective_blocked_from_submitted
    """
    # Proposed 2026-09-20 satisfies the 45-day lead from 2026-08-01.
    scenario = setup_submitted_filing(proposed_effective_date="2026-09-20")
    filing_id = scenario["filing"]["id"]

    # Past the proposal but before the 2026-09-30 deemer: still SUBMITTED.
    set_clock("2026-09-25T00:00:00Z")
    res = api.mark_filing_effective(filing_id, fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert after["status"] == "SUBMITTED"


def test_mark_effective_before_actual_date_rejected(api):
    """PRD §3.5: "From `APPROVED` or `DEEMED_APPROVED`, the filing may be
    marked effective once the current date has reached the
    `actual_effective_date` — attempting it earlier is rejected with
    `ERR_EFFECTIVE_DATE_NOT_REACHED` (HTTP 409)".

    Design: Corner/validations/mark_effective_before_actual_date_rejected
    """
    scenario = setup_approved_filing(approve_at="2026-09-01T00:00:00Z")
    assert scenario["filing"]["actual_effective_date"] == "2026-10-16"

    set_clock("2026-10-10T00:00:00Z")
    res = api.mark_filing_effective(scenario["filing"]["id"], fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_EFFECTIVE_DATE_NOT_REACHED)
    after = get_success_data(api.get_filing(scenario["filing"]["id"], fx.OFFICER))
    assert after["status"] == "APPROVED"


def test_approve_draft_filing_rejected(api):
    """PRD §3.5: "A `StateRegulator` approves a `SUBMITTED` filing only when
    the objection ledger is clean".
    PRD §2.8: "sixth, whether the target resource is in a state from which the
    requested transition exists, rejected otherwise as `ERR_INVALID_STATE`
    (HTTP 409)".

    Design: Corner/state_machines/approve_draft_filing_returns_invalid_state
    """
    scenario = setup_draft_filing()
    res = api.approve_filing(scenario["filing"]["id"], fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_filing(scenario["filing"]["id"], fx.REGULATOR))
    assert after["status"] == "DRAFT"
    assert after["approved_at"] is None
