"""Dispute filing, deadline arithmetic, priority score, and filing guards.

Translates queue A (Difficulty) dual_variant_calc and combinatorial_formula plus
queue B (Corner) dispute/priority instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    make_bureau_headers, make_furnisher_headers, make_consumer_headers,
    create_tradeline_payload,
    setup_consumer_furnisher_file, setup_file_with_tradeline,
    setup_frozen_file_with_tradeline, setup_corrected_tradeline,
    setup_deleted_tradeline, setup_filed_dispute,
    set_clock, get_file_version, create_tradeline, file_dispute,
)

BUREAU = make_bureau_headers()


def _v(cfile_id):
    return validate_success(api_client.get_credit_file(cfile_id, BUREAU))["version"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — deadline CALENDAR vs EXPEDITED
# ---------------------------------------------------------------------------

def test_deadline_calendar_30_days(api):
    """PRD §3.4: "Under CALENDAR mode, the deadline is the filing instant plus 30
    calendar days, with weekends counted normally; this is the standard FCRA
    reinvestigation window."

    Design: Difficulty/dual_variant_calc/investigation_deadline_calendar_vs_expedited
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="REVOLVING", balance_cents=120000,
                          date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                          reported_delinquency_date="2020-03-01T00:00:00.000Z")
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="INACCURATE_BALANCE", clock_mode="CALENDAR")
    assert dispute["deadline_at"] == "2026-02-04T00:00:00.000Z", (
        f"Expected 2026-02-04T00:00:00.000Z, got {dispute['deadline_at']}"
    )


def test_deadline_expedited_diverges_from_calendar(api):
    """PRD §3.4: "Under EXPEDITED mode ... the deadline is the filing instant
    advanced by 15 business days: starting from the filing date, the system steps
    forward one calendar day at a time, counting only days that fall on Monday
    through Friday and skipping every Saturday and Sunday, until 15 such weekdays
    have been added, while preserving the time-of-day component of the filing instant."

    Design: Difficulty/dual_variant_calc/investigation_deadline_calendar_vs_expedited
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl_cal = create_tradeline(cfile["id"], furnisher["id"], balance_cents=120000,
                              date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                              reported_delinquency_date="2020-03-01T00:00:00.000Z")
    d_cal = file_dispute(consumer["id"], cfile["id"], tl_cal["id"], get_file_version(cfile["id"]),
                         dispute_reason="INACCURATE_BALANCE", clock_mode="CALENDAR")
    tl_exp = create_tradeline(cfile["id"], furnisher["id"], account_type="INSTALLMENT", balance_cents=80000,
                              date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                              reported_delinquency_date="2020-03-01T00:00:00.000Z")
    d_exp = file_dispute(consumer["id"], cfile["id"], tl_exp["id"], get_file_version(cfile["id"]),
                         dispute_reason="NOT_MINE", clock_mode="EXPEDITED")
    assert d_exp["deadline_at"] == "2026-01-26T00:00:00.000Z", (
        f"Expected 2026-01-26T00:00:00.000Z, got {d_exp['deadline_at']}"
    )
    assert d_cal["deadline_at"] != d_exp["deadline_at"]


def test_deadline_expedited_business_day_rounding_order(api):
    """PRD §3.4: "Under EXPEDITED mode ... the deadline is the filing instant
    advanced by 15 business days: starting from the filing date, the system steps
    forward one calendar day at a time, counting only days that fall on Monday
    through Friday and skipping every Saturday and Sunday, until 15 such weekdays
    have been added, while preserving the time-of-day component of the filing instant."

    Design: Difficulty/combinatorial_formula/deadline_business_day_rounding_order
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-09T09:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="INSTALLMENT", balance_cents=30000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="EXPEDITED")
    assert dispute["deadline_at"] == "2026-01-30T09:00:00.000Z", (
        f"Expected 2026-01-30T09:00:00.000Z, got {dispute['deadline_at']}"
    )
    # The skip-order (count only the post-increment weekday) is load-bearing: a naive
    # add-15-calendar-days would land on 2026-01-24, which the rule must NOT produce.
    assert dispute["deadline_at"] != "2026-01-24T09:00:00.000Z"


def test_deadline_expedited_from_monday_filing(api):
    """PRD §3.4: "Under EXPEDITED mode ... the deadline is the filing instant advanced
    by 15 business days: starting from the filing date, the system steps forward one
    calendar day at a time, counting only days that fall on Monday through Friday and
    skipping every Saturday and Sunday, until 15 such weekdays have been added, while
    preserving the time-of-day component of the filing instant."

    Design: Difficulty/combinatorial_formula/deadline_business_day_rounding_order
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    # Monday 2026-01-05: 15 business days forward (skipping weekends) -> 2026-01-26.
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="INSTALLMENT", balance_cents=30000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="NOT_MINE", clock_mode="EXPEDITED")
    assert dispute["deadline_at"] == "2026-01-26T00:00:00.000Z", (
        f"Expected 2026-01-26T00:00:00.000Z, got {dispute['deadline_at']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — reage vs purge derivations on a tradeline
# ---------------------------------------------------------------------------

def test_purge_due_at_anchored_to_dofd_unchanged_by_reage(api):
    """PRD §3.2: "The purge instant is anchored to the date of first delinquency
    alone and never to the reported delinquency date, so re-aging an account can
    never push its purge date outward."

    Design: Difficulty/dual_variant_calc/reage_violation_vs_purge_window_on_tradeline
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file(set_clock_anchor=False, bureau_code="EXPERIAN")
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="COLLECTION", balance_cents=50000,
                          date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                          reported_delinquency_date="2020-03-01T00:00:00.000Z")
    assert tl["purge_due_at"] == "2027-08-27T00:00:00.000Z", (
        f"Expected 2027-08-27T00:00:00.000Z, got {tl['purge_due_at']}"
    )
    after = validate_success(
        api.reage_tradeline(tl["id"], {"reported_delinquency_date": "2022-06-01T00:00:00.000Z"},
                           make_furnisher_headers(furnisher["id"]))
    )
    assert after["purge_due_at"] == "2027-08-27T00:00:00.000Z", (
        f"Purge instant must be unchanged after re-age, got {after['purge_due_at']}"
    )


def test_reage_violation_flips_true_after_forward_reage(api):
    """PRD §3.2: "reage_violation, a boolean that is true exactly when the reported
    delinquency date lies strictly after the date of first delinquency, and false
    when the two dates are equal or when the reported date is earlier — equality is
    legal and is not a violation."

    Design: Difficulty/dual_variant_calc/reage_violation_vs_purge_window_on_tradeline
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file(set_clock_anchor=False, bureau_code="EXPERIAN")
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="COLLECTION", balance_cents=50000,
                          date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                          reported_delinquency_date="2020-03-01T00:00:00.000Z")
    assert tl["reage_violation"] is False
    after = validate_success(
        api.reage_tradeline(tl["id"], {"reported_delinquency_date": "2022-06-01T00:00:00.000Z"},
                           make_furnisher_headers(furnisher["id"]))
    )
    assert after["reage_violation"] is True


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — priority score nonlinear
# ---------------------------------------------------------------------------

def test_priority_score_illegal_reage_balance_cap(api):
    """PRD §3.4: "The score begins from a reason weight determined by the
    dispute_reason: 50 for IDENTITY_THEFT, 40 for ILLEGAL_REAGE, 35 for NOT_MINE,
    20 for INACCURATE_BALANCE, and 15 for PAID_IN_FULL. To this is added a re-age
    bonus of 25 points when the linked tradeline's reage_violation flag is true, and
    0 when it is false. A balance factor is then added, equal to the tradeline's
    balance_cents divided by 50000 using integer floor division — one point per 500
    dollars of reported balance — but capped so that the balance factor never
    exceeds 20."

    Design: Difficulty/combinatorial_formula/priority_score_nonlinear_multi_input
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="REVOLVING", balance_cents=750000,
                          date_of_first_delinquency="2019-01-01T00:00:00.000Z",
                          reported_delinquency_date="2019-01-01T00:00:00.000Z")
    validate_success(
        api.reage_tradeline(tl["id"], {"reported_delinquency_date": "2021-05-01T00:00:00.000Z"},
                           make_furnisher_headers(furnisher["id"]))
    )
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="ILLEGAL_REAGE")
    assert dispute["priority_score"] == 80, f"Expected 80, got {dispute['priority_score']}"


def test_priority_score_identity_theft_below_balance_cap(api):
    """PRD §3.4: "The score begins from a reason weight determined by the
    dispute_reason: 50 for IDENTITY_THEFT, 40 for ILLEGAL_REAGE, 35 for NOT_MINE,
    20 for INACCURATE_BALANCE, and 15 for PAID_IN_FULL. To this is added a re-age
    bonus of 25 points when the linked tradeline's reage_violation flag is true, and
    0 when it is false. A balance factor is then added, equal to the tradeline's
    balance_cents divided by 50000 using integer floor division — one point per 500
    dollars of reported balance — but capped so that the balance factor never
    exceeds 20."

    Design: Difficulty/combinatorial_formula/priority_score_nonlinear_multi_input
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    # IDENTITY_THEFT(50) + no reage(0) + floor(250000/50000)=5 (below cap) - 0 = 55.
    tl = create_tradeline(cfile["id"], furnisher["id"], account_type="REVOLVING", balance_cents=250000)
    assert tl["reage_violation"] is False
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="IDENTITY_THEFT")
    assert dispute["priority_score"] == 55, f"Expected 55, got {dispute['priority_score']}"


# ---------------------------------------------------------------------------
# Corner: calculations — priority clamp to zero, reage equal-date legal
# ---------------------------------------------------------------------------

def test_priority_score_clamped_to_zero_after_two_reopens(api):
    """PRD §3.4: "A reopen penalty is then subtracted, equal to 10 points for each
    prior reopen cycle, that is, 10 multiplied by the dispute's reopen_count. The
    resulting raw total is then clamped into the range 0 through 100: any value below
    0 becomes 0 and any value above 100 becomes 100."

    Design: Corner/calculations/priority_score_clamped_to_zero_high_reopen
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=0)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="PAID_IN_FULL")
    ch = make_consumer_headers(consumer["id"])
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    validate_success(api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU), 201)
    validate_success(api.reopen_dispute(dispute["id"], ch))
    validate_success(api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU), 201)
    reopened = validate_success(api.reopen_dispute(dispute["id"], ch))
    assert reopened["reopen_count"] == 2, f"Expected reopen_count 2, got {reopened['reopen_count']}"
    assert reopened["priority_score"] == 0, f"Expected 0, got {reopened['priority_score']}"


def test_reage_to_equal_dofd_is_legal(api):
    """PRD §3.2: "reage_violation, a boolean that is true exactly when the reported
    delinquency date lies strictly after the date of first delinquency, and false
    when the two dates are equal or when the reported date is earlier — equality is
    legal and is not a violation."

    Design: Corner/calculations/reage_violation_equal_dates_is_legal
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file(set_clock_anchor=False)
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=10000,
                          date_of_first_delinquency="2020-03-01T00:00:00.000Z",
                          reported_delinquency_date="2022-03-01T00:00:00.000Z")
    assert tl["reage_violation"] is True
    after = validate_success(
        api.reage_tradeline(tl["id"], {"reported_delinquency_date": "2020-03-01T00:00:00.000Z"},
                           make_furnisher_headers(furnisher["id"]))
    )
    assert after["reage_violation"] is False


# ---------------------------------------------------------------------------
# Corner: state_machines — initial state, redispute, duplicate, deletable
# ---------------------------------------------------------------------------

def test_new_dispute_starts_filed_reopen_zero(api):
    """PRD §3.3: "A newly filed dispute enters status FILED, its filed_at is stamped
    with the current server clock, its reopen_count begins at 0, and its
    outcome_reason begins null."

    Design: Corner/state_machines/dispute_initial_state_is_filed
    """
    consumer, furnisher, cfile, tl, dispute = setup_filed_dispute()
    assert dispute["status"] == "FILED"
    assert dispute["reopen_count"] == 0


def test_redispute_corrected_tradeline_returns_to_disputed(api):
    """PRD §3.3: "the disputed tradeline transitions from REPORTING, CORRECTED, or
    VERIFIED to DISPUTED"
    PRD §3.3: "The target tradeline must be in a disputable status — REPORTING,
    CORRECTED, or VERIFIED — or the request is rejected with ERR_TRADELINE_NOT_DISPUTABLE"

    Design: Corner/state_machines/redispute_corrected_tradeline_reporting_to_disputed
    """
    consumer, furnisher, cfile, tl, _dispute = setup_corrected_tradeline()
    assert tl["status"] == "CORRECTED"
    v = get_file_version(cfile["id"])
    new_dispute = validate_success(
        api.create_dispute(
            {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "PAID_IN_FULL",
             "clock_mode": "CALENDAR", "expected_credit_file_version": v},
            make_consumer_headers(consumer["id"])),
        201,
    )
    assert new_dispute["status"] == "FILED"
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    assert tl_after["status"] == "DISPUTED"


def test_dispute_on_deleted_tradeline_not_disputable(api):
    """PRD §3.3: "The target tradeline must be in a disputable status — REPORTING,
    CORRECTED, or VERIFIED — or the request is rejected with
    ERR_TRADELINE_NOT_DISPUTABLE (for instance, a tradeline already DISPUTED or
    already DELETED cannot be disputed afresh)."

    Design: Corner/state_machines/tradeline_not_disputable_when_deleted
    """
    consumer, furnisher, cfile, tl, _dispute = setup_deleted_tradeline()
    assert tl["status"] == "DELETED"
    v = get_file_version(cfile["id"])
    resp = api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "INACCURATE_BALANCE",
         "clock_mode": "CALENDAR", "expected_credit_file_version": v},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRADELINE_NOT_DISPUTABLE.value)


# ---------------------------------------------------------------------------
# Difficulty + Corner: filing guards (frozen / locked / overlap / stale)
# ---------------------------------------------------------------------------

def test_dispute_create_blocked_by_frozen_file(api):
    """PRD §3.3: "The parent credit file must not be FROZEN; filing against a frozen
    file is rejected with ERR_FILE_FROZEN."

    Design: Difficulty/cross_entity_state_dependency/dispute_create_blocked_by_frozen_file
    """
    consumer, furnisher, cfile, tl = setup_frozen_file_with_tradeline()
    v = get_file_version(cfile["id"])
    resp = api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "NOT_MINE",
         "clock_mode": "CALENDAR", "expected_credit_file_version": v},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FILE_FROZEN.value)


def test_frozen_file_rejection_leaves_tradeline_reporting(api):
    """PRD §3.3: "The parent credit file must not be FROZEN; filing against a frozen
    file is rejected with ERR_FILE_FROZEN."
    PRD §3.3: "the disputed tradeline transitions from REPORTING, CORRECTED, or
    VERIFIED to DISPUTED"

    Design: Difficulty/cross_entity_state_dependency/dispute_create_blocked_by_frozen_file
    """
    consumer, furnisher, cfile, tl = setup_frozen_file_with_tradeline()
    v = get_file_version(cfile["id"])
    api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "NOT_MINE",
         "clock_mode": "CALENDAR", "expected_credit_file_version": v},
        make_consumer_headers(consumer["id"]),
    )
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    assert tl_after["status"] == "REPORTING", "tradeline must remain REPORTING when dispute is blocked"


def test_locked_file_allows_dispute_creation(api):
    """PRD §3.7: "The freeze_type is either LOCK — a consumer-toggled convenience
    posture — or FREEZE, the stronger statutory protection that blocks new tradeline
    pulls and dispute creation."
    PRD §3.7: "A FROZEN posture blocks both new dispute creation and opening an
    investigation, as enforced by the ERR_FILE_FROZEN checks elsewhere."

    Design: Corner/state_machines/locked_file_allows_dispute_creation
    """
    consumer, furnisher, cfile, tl = setup_file_with_tradeline()
    v = get_file_version(cfile["id"])
    validate_success(
        api.create_security_freeze(
            {"credit_file_id": cfile["id"], "freeze_type": "LOCK",
             "effective_at": "2026-01-05T00:00:00.000Z", "expected_credit_file_version": v},
            make_consumer_headers(consumer["id"])),
        201,
    )
    v2 = get_file_version(cfile["id"])
    dispute = validate_success(
        api.create_dispute(
            {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "NOT_MINE",
             "clock_mode": "CALENDAR", "expected_credit_file_version": v2},
            make_consumer_headers(consumer["id"])),
        201,
    )
    assert dispute["status"] == "FILED"


def test_overlapping_same_reason_dispute_rejected(api):
    """PRD §3.3: "The new dispute is rejected with ERR_OVERLAPPING_INVESTIGATION if,
    on the same credit file, there exists any other non-terminal dispute (status
    FILED, INVESTIGATING, REVERIFYING, or REOPENED) that carries the same
    dispute_reason and whose window overlaps the new one."

    Design: Difficulty/resource_temporal_overlap/dispute_investigation_window_overlap_same_reason
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl_a = create_tradeline(cfile["id"], furnisher["id"], balance_cents=50000)
    tl_b = create_tradeline(cfile["id"], furnisher["id"], account_type="INSTALLMENT", balance_cents=60000)
    file_dispute(consumer["id"], cfile["id"], tl_a["id"], get_file_version(cfile["id"]),
                 dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    v = get_file_version(cfile["id"])
    resp = api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": tl_b["id"], "dispute_reason": "NOT_MINE",
         "clock_mode": "CALENDAR", "expected_credit_file_version": v},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OVERLAPPING_INVESTIGATION.value)


def test_overlapping_check_scoped_per_reason_different_reason_succeeds(api):
    """PRD §3.3: "The new dispute is rejected with ERR_OVERLAPPING_INVESTIGATION if,
    on the same credit file, there exists any other non-terminal dispute ... that
    carries the same dispute_reason and whose window overlaps the new one. ... This
    aggregate check is scoped per credit file and per dispute reason"

    Design: Difficulty/resource_temporal_overlap/dispute_investigation_window_overlap_same_reason
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl_a = create_tradeline(cfile["id"], furnisher["id"], balance_cents=50000)
    tl_b = create_tradeline(cfile["id"], furnisher["id"], account_type="INSTALLMENT", balance_cents=60000)
    file_dispute(consumer["id"], cfile["id"], tl_a["id"], get_file_version(cfile["id"]),
                 dispute_reason="NOT_MINE", clock_mode="CALENDAR")
    v = get_file_version(cfile["id"])
    # Same overlapping window, but a DIFFERENT dispute_reason -> not rejected.
    dispute_b = validate_success(
        api.create_dispute(
            {"credit_file_id": cfile["id"], "tradeline_id": tl_b["id"], "dispute_reason": "INACCURATE_BALANCE",
             "clock_mode": "CALENDAR", "expected_credit_file_version": v},
            make_consumer_headers(consumer["id"])),
        201,
    )
    assert dispute_b["status"] == "FILED"


def test_dispute_create_stale_version_rejected(api):
    """PRD §2.8: "when a consumer files a dispute against a credit file, the request
    must carry expected_credit_file_version matching the file's current version; if a
    concurrently placed freeze or a prior dispute's resolution cascade has bumped the
    file's version ... since the consumer last read it, the dispute creation is
    rejected with ERR_STALE_FILE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/dispute_create_stale_version_rejected
    """
    consumer, furnisher, cfile, tl = setup_file_with_tradeline()
    stale_v = get_file_version(cfile["id"])
    # A LOCK bumps the file version after the client captured stale_v.
    validate_success(
        api.create_security_freeze(
            {"credit_file_id": cfile["id"], "freeze_type": "LOCK",
             "effective_at": "2026-01-05T00:00:00.000Z", "expected_credit_file_version": stale_v},
            make_consumer_headers(consumer["id"])),
        201,
    )
    resp = api.create_dispute(
        {"credit_file_id": cfile["id"], "tradeline_id": tl["id"], "dispute_reason": "NOT_MINE",
         "clock_mode": "CALENDAR", "expected_credit_file_version": stale_v},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FILE_VERSION.value)


def test_deadline_breach_blocks_open_investigation(api):
    """PRD §3.4: "Opening requires that the dispute currently be FILED, that the
    parent file not be FROZEN (otherwise ERR_FILE_FROZEN), and that the server clock
    be at or before the dispute's deadline (otherwise the deadline has been breached
    and ERR_DEADLINE_BREACHED applies)."

    Design: Corner/state_machines/deadline_breach_blocks_open_investigation
    """
    consumer, furnisher, cfile, tl, dispute = setup_filed_dispute()
    # SET (not advance) the clock past the deadline so no sweep runs.
    api.clock_set("2026-02-10T00:00:00.000Z", BUREAU)
    resp = api.open_investigation(dispute["id"], BUREAU)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_BREACHED.value)
