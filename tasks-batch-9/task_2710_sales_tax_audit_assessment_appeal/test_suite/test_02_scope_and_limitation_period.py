"""Scoping an examination period and the limitation clock that hangs off it."""
from test_helpers import (
    ApiErrorId,
    api_client,
    base_expiry_for,
    draft_waiver,
    execute_waiver,
    open_second_audit_for_taxpayer,
    read_assessment,
    read_audit,
    scope_audit_payload,
    set_clock_date,
    setup_final_assessment,
    setup_scoped_audit,
    validate_error,
    validate_success,
    void_waiver,
)
from test_helpers import TEST_USERS

AUDITOR = TEST_USERS["field_auditor_headers"]

FIRST_SCOPE_START = "2026-01-01"
FIRST_SCOPE_END = "2026-06-30"
SHARED_DAY = "2026-06-30"
DAY_AFTER = "2026-07-01"
SECOND_SCOPE_END = "2026-12-31"
MINI_TAX_DEFICIENCY_CENTS = 4_762


def _closed_first_audit_and_a_fresh_second():
    """Take one audit to CLOSED, then convert the holder's next lead."""
    ctx = setup_final_assessment(tax_deficiency_cents=MINI_TAX_DEFICIENCY_CENTS)
    ctx["second_audit"] = open_second_audit_for_taxpayer(ctx)
    return ctx


def _scope_second(ctx, start, end):
    return api_client.scope_audit(
        ctx["second_audit"]["id"], scope_audit_payload(start, end, "DESK"), AUDITOR
    )


def test_a_closed_audit_still_defends_its_last_examined_day():
    """A second period sharing the first period's final day is refused.

    PRD 3.2: "A period is audited once and only once, so the proposed closed
    interval from `scope_period_start` through `scope_period_end` inclusive must
    not overlap the closed scope interval of any other audit of the same permit
    holder whose `status` is anything other than `ABANDONED` — `CLOSED` audits
    included."
    PRD 3.2: "Sharing even a single endpoint day is an overlap, and the attempt is
    rejected with `ERR_AUDIT_SCOPE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/audit_scope_overlap_on_a_single_shared_endpoint_day
    """
    ctx = _closed_first_audit_and_a_fresh_second()
    assert read_audit(ctx["audit"]["id"])["status"] == "CLOSED"
    assert read_assessment(ctx["assessment"]["id"])["status"] == "FINAL"

    response = _scope_second(ctx, SHARED_DAY, SECOND_SCOPE_END)
    validate_error(response, ApiErrorId.ERR_AUDIT_SCOPE_OVERLAP.value, 409)

    second = read_audit(ctx["second_audit"]["id"])
    assert second["status"] == "PLANNED"
    assert second["scope_period_start"] is None


def test_a_period_starting_the_day_after_is_adjacent_not_overlapping():
    """Starting on the day after the first period ends is accepted and fixes the base date.

    PRD 3.2: "Sharing even a single endpoint day is an overlap, and the attempt is
    rejected with `ERR_AUDIT_SCOPE_OVERLAP`."
    PRD 3.2: "On success the audit moves `PLANNED → SCOPED`, and its
    `base_statute_expiry_date` is set to `scope_period_end` advanced by 1,095
    calendar days — the three-year base limitation period — and fixed there
    permanently."

    Design: Difficulty/resource_temporal_overlap/audit_scope_overlap_on_a_single_shared_endpoint_day
    """
    ctx = _closed_first_audit_and_a_fresh_second()

    response = _scope_second(ctx, DAY_AFTER, SECOND_SCOPE_END)
    validate_success(response, 200)

    second = read_audit(ctx["second_audit"]["id"])
    assert second["status"] == "SCOPED"
    assert second["scope_period_start"] == DAY_AFTER
    assert second["base_statute_expiry_date"] == "2029-12-30"
    assert second["base_statute_expiry_date"] == base_expiry_for(SECOND_SCOPE_END)


SIGNING_DAY = "2026-07-15"
BASE_EXPIRY = "2029-06-29"
EXTENDED_TO = "2030-06-29"
WAIVER_DAYS = 365


def _audit_with_a_drafted_waiver():
    """Scoped audit whose base date is 2029-06-29, plus one unsigned waiver."""
    ctx = setup_scoped_audit(
        scope_period_start=FIRST_SCOPE_START, scope_period_end=FIRST_SCOPE_END
    )
    audit = read_audit(ctx["audit"]["id"])
    assert audit["base_statute_expiry_date"] == BASE_EXPIRY
    assert audit["statute_expiry_date"] == BASE_EXPIRY
    assert audit["waiver_days_added"] == 0
    assert audit["statute_status"] == "PROTECTED"
    ctx["clock_date"] = set_clock_date(SIGNING_DAY)
    ctx["waiver"] = draft_waiver(audit["id"], FIRST_SCOPE_END, EXTENDED_TO)
    return ctx


def test_signing_a_waiver_moves_the_live_date_off_the_base_date():
    """The executed waiver records the expiry it found and the days it contributed.

    PRD 3.2: "The waiver moves `DRAFTED → EXECUTED`, capturing `prior_expiry_date`
    as the audit's expiry at that moment and `days_added` as the whole number of
    days from that snapshot to `extended_to_date`."
    PRD 3.2: "The sum of all such contributions is stored on the audit as
    `waiver_days_added`."

    Design: Difficulty/compensating_invariant/waiver_void_returns_every_day_it_added
    """
    ctx = _audit_with_a_drafted_waiver()

    waiver = execute_waiver(ctx["waiver"]["id"], ctx["taxpayer"]["id"], SIGNING_DAY)

    assert waiver["status"] == "EXECUTED"
    assert waiver["prior_expiry_date"] == BASE_EXPIRY
    assert waiver["days_added"] == WAIVER_DAYS

    audit = read_audit(ctx["audit"]["id"])
    assert audit["statute_expiry_date"] == EXTENDED_TO
    assert audit["waiver_days_added"] == WAIVER_DAYS
    assert audit["base_statute_expiry_date"] == BASE_EXPIRY


def test_voiding_the_waiver_returns_the_date_to_the_base_day_exactly():
    """Every day the waiver added comes back, and the waiver leaves the replay set.

    PRD 3.2: "it sets the waiver's `days_added` back to 0 and re-runs the replay,
    so with no other executed waiver on file the audit returns exactly to its
    `base_statute_expiry_date` advanced only by `tolled_days`, and
    `waiver_days_added` returns to 0."
    PRD 3.2: "Otherwise it is `PROTECTED`."

    Design: Difficulty/compensating_invariant/waiver_void_returns_every_day_it_added
    """
    ctx = _audit_with_a_drafted_waiver()
    execute_waiver(ctx["waiver"]["id"], ctx["taxpayer"]["id"], SIGNING_DAY)

    voided = void_waiver(ctx["waiver"]["id"])

    assert voided["status"] == "VOIDED"
    assert voided["days_added"] == 0

    audit = read_audit(ctx["audit"]["id"])
    assert audit["statute_expiry_date"] == BASE_EXPIRY
    assert audit["waiver_days_added"] == 0
    assert audit["tolled_days"] == 0
    assert audit["statute_status"] == "PROTECTED"
