"""Endpoint-level edge behaviour: the logical-clock setter, audit data production
and the supersede-overlapping flag on ownership claims."""

from datetime import datetime

from test_helpers import (
    CANONICAL_SCHEDULE,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    append_line,
    calculate_pool,
    create_batch,
    create_effective_schedule,
    create_engagement,
    create_holder,
    create_label,
    create_period,
    create_pool,
    create_recording,
    create_statement,
    data_production_payload,
    file_and_approve_registration,
    file_registration,
    finalize_pool,
    issue_statement,
    review_registration,
    seal_and_match_batch,
    set_clock,
    statement_lines,
    validate_error,
    validate_success,
)

STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"
MOVED_CLOCK_UTC = "2026-09-15T12:00:00Z"
SECOND_PERIOD_LABEL = "2026-07"
SECOND_PERIOD_USAGE_START = "2026-07-01"
SECOND_PERIOD_USAGE_END = "2026-07-31"
SECOND_PERIOD_CLAIM_WINDOW_CLOSES_AT = "2026-09-29T00:00:00Z"

UNKNOWN_STATEMENT_LINE_ID = "11111111-1111-4111-8111-111111111122"

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]


def _assert_instant_equals(actual: str, expected: str, label: str) -> None:
    """Compare two ISO 8601 UTC instants regardless of fractional-digit spelling."""
    parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    parsed_expected = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert parsed_actual == parsed_expected, (
        f"{label}: expected instant {expected}, got {actual}"
    )


def _setup_two_tier_audit_engagement(api):
    """One holder, two EFFECTIVE GB schedules (INDIVIDUAL and FAMILY), one sealed
    and matched batch carrying a 450000-play INDIVIDUAL line and a 100000-play
    FAMILY line, both pools finalized, the holder's two-line statement ISSUED and
    an audit engagement opened over it with nothing produced yet."""
    label = create_label(api)

    individual_schedule = dict(CANONICAL_SCHEDULE)
    individual_schedule["proceeding_ref"] = "CRB-2026-IND"
    create_effective_schedule(api, **individual_schedule)

    family_schedule = dict(CANONICAL_SCHEDULE)
    family_schedule["proceeding_ref"] = "CRB-2026-FAM"
    family_schedule["subscription_tier"] = "FAMILY"
    create_effective_schedule(api, **family_schedule)

    period = create_period(api)
    recording = create_recording(api)

    batch = create_batch(api, period["id"])
    append_line(
        api,
        batch["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=450000,
    )
    append_line(
        api,
        batch["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="FAMILY",
        play_count=100000,
    )
    seal_and_match_batch(api, batch["id"])

    file_and_approve_registration(
        api,
        recording["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )

    individual_pool = create_pool(
        api,
        period["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    calculate_pool(api, individual_pool["id"])
    family_pool = create_pool(
        api,
        period["id"],
        territory_code="GB",
        subscription_tier="FAMILY",
        subscriber_count=400,
        gross_revenue_cents=200000,
    )
    calculate_pool(api, family_pool["id"])
    finalize_pool(api, individual_pool["id"])
    finalize_pool(api, family_pool["id"])

    statement = create_statement(api, label["id"], period["id"])
    issue_statement(api, statement["id"])

    individual_lines = statement_lines(
        api, statement["id"], pool_id=individual_pool["id"]
    )
    family_lines = statement_lines(api, statement["id"], pool_id=family_pool["id"])
    assert len(individual_lines) == 1, "the INDIVIDUAL pool funds exactly one line"
    assert len(family_lines) == 1, "the FAMILY pool funds exactly one line"

    engagement = create_engagement(api, label["id"], statement["id"])

    return {
        "label": label,
        "period": period,
        "statement": statement,
        "individual_line": individual_lines[0],
        "family_line": family_lines[0],
        "engagement": engagement,
    }


def _setup_approved_gb_master_claim(api):
    """A label and a rival distributor, one recording carrying no usage at all,
    and the label's MASTER GB 10000 bps claim APPROVED."""
    label = create_label(api)
    distributor = create_holder(
        api,
        legal_name="Harborline Distribution",
        holder_type="DISTRIBUTOR",
        home_territory_code="GB",
        direct_deal_rate_bps=800,
    )
    recording = create_recording(api)
    incumbent = file_and_approve_registration(
        api,
        recording["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["GB"],
    )
    return {
        "label": label,
        "distributor": distributor,
        "recording": recording,
        "incumbent": incumbent,
    }


def _setup_reviewed_supersede_claim(api, work_id, claimant_id):
    """File a MASTER GB claim carrying supersede_overlapping, take it into review
    and return the raw approve response."""
    registration = file_registration(
        api,
        work_id,
        claimant_id,
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["GB"],
        supersede_overlapping=True,
    )
    review_registration(api, registration["id"])
    return registration, api.approve_rights_registration(
        registration["id"], REVIEWER_HEADERS
    )


# ─────────────────────────────────────────────────────
# The logical clock
# ─────────────────────────────────────────────────────

def test_period_created_before_any_clock_call_carries_the_startup_instant(api):
    """A record created before any caller sets the clock is stamped with the startup instant 2026-08-01T00:00:00Z rather than host wall-clock time.

    PRD: "Before any caller has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time."

    Design: Corner/endpoints/clock_endpoint_pins_created_at_and_moves_time_forward
    """
    period = create_period(api)

    _assert_instant_equals(period["created_at"], STARTUP_CLOCK_UTC, "created_at")


def test_period_created_after_the_clock_moves_takes_the_new_instant(api):
    """Moving the logical clock forward makes the next record's created_at read from the new instant.

    PRD: "Everything the specification calls the current instant is read from this clock, including the `issued_at` stamped on a statement and the `promulgated_at` stamped on a rate schedule."

    Design: Corner/endpoints/clock_endpoint_pins_created_at_and_moves_time_forward
    """
    create_period(api)

    validate_success(set_clock(api, MOVED_CLOCK_UTC), 200)

    second_period = create_period(
        api,
        label=SECOND_PERIOD_LABEL,
        usage_start=SECOND_PERIOD_USAGE_START,
        usage_end=SECOND_PERIOD_USAGE_END,
    )

    _assert_instant_equals(second_period["created_at"], MOVED_CLOCK_UTC, "created_at")


def test_claim_window_is_derived_from_usage_end_and_not_from_the_clock(api):
    """Each period's claim_window_closes_at is its own usage_end at midnight advanced by 60 days, whatever the clock reads when the period is opened.

    PRD: "An `AccountingPeriod` computes `claim_window_closes_at` as its `usage_end` taken at midnight UTC — that is, at `00:00:00.000Z` on that date — advanced by 60 days; the bound is inclusive, so the current instant exactly equal to `claim_window_closes_at` still counts as open."

    Design: Corner/endpoints/clock_endpoint_pins_created_at_and_moves_time_forward
    """
    first_period = create_period(api)
    _assert_instant_equals(
        first_period["claim_window_closes_at"],
        TEST_DEFAULTS["PERIOD_CLAIM_WINDOW_CLOSES_AT"],
        "first claim_window_closes_at",
    )

    set_clock(api, MOVED_CLOCK_UTC)

    second_period = create_period(
        api,
        label=SECOND_PERIOD_LABEL,
        usage_start=SECOND_PERIOD_USAGE_START,
        usage_end=SECOND_PERIOD_USAGE_END,
    )
    _assert_instant_equals(
        second_period["claim_window_closes_at"],
        SECOND_PERIOD_CLAIM_WINDOW_CLOSES_AT,
        "second claim_window_closes_at",
    )


def test_setting_the_clock_does_not_rewrite_already_stored_timestamps(api):
    """A stored created_at keeps recording the moment its record came into existence after the clock has been moved on.

    PRD: "Every resource also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits, recording the moment the record came into existence."

    Design: Corner/endpoints/clock_endpoint_pins_created_at_and_moves_time_forward
    """
    period = create_period(api)

    set_clock(api, MOVED_CLOCK_UTC)

    reread = validate_success(api.get_period(period["id"], ADMIN_HEADERS), 200)
    assert reread["created_at"] == period["created_at"]
    assert reread["claim_window_closes_at"] == period["claim_window_closes_at"]
    _assert_instant_equals(reread["created_at"], STARTUP_CLOCK_UTC, "created_at")


# ─────────────────────────────────────────────────────
# Audit data production
# ─────────────────────────────────────────────────────

def test_data_production_counts_distinct_statement_lines_only(api):
    """produced_line_count advances by the number of distinct lines produced, so a repeated identifier inside one call and an already-produced identifier in a later call are each counted once.

    PRD: "`produced_line_count` is then recomputed as the count of **distinct** line identifiers accepted across every production call on this engagement, so re-submitting a line already produced does not advance the count."

    Design: Corner/endpoints/data_production_deduplicates_ids_and_is_all_or_nothing
    """
    fixture = _setup_two_tier_audit_engagement(api)
    engagement = fixture["engagement"]
    individual_line_id = fixture["individual_line"]["id"]
    family_line_id = fixture["family_line"]["id"]

    assert engagement["required_line_count"] == 2
    assert engagement["produced_line_count"] == 0
    assert engagement["production_status"] == "PENDING"

    first = validate_success(
        api.produce_audit_data(
            engagement["id"],
            data_production_payload([individual_line_id, individual_line_id]),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert first["produced_line_count"] == 1
    assert first["production_status"] == "PARTIAL"

    second = validate_success(
        api.produce_audit_data(
            engagement["id"],
            data_production_payload([individual_line_id, family_line_id]),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert second["produced_line_count"] == 2
    assert second["production_status"] == "COMPLETE"


def test_production_naming_one_unknown_line_records_nothing_at_all(api):
    """A production batch carrying one unknown statement line identifier is rejected outright and the valid identifier travelling in the same body is not recorded.

    PRD: "Every identifier supplied must belong to the audited statement: an identifier that does not exist at all is refused with `ERR_STATEMENT_LINE_NOT_FOUND`, and an identifier that resolves to a line of some other statement is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/data_production_deduplicates_ids_and_is_all_or_nothing
    """
    fixture = _setup_two_tier_audit_engagement(api)
    engagement = fixture["engagement"]
    individual_line_id = fixture["individual_line"]["id"]
    family_line_id = fixture["family_line"]["id"]

    accepted = validate_success(
        api.produce_audit_data(
            engagement["id"],
            data_production_payload([individual_line_id, individual_line_id]),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert accepted["produced_line_count"] == 1
    assert accepted["production_status"] == "PARTIAL"

    validate_error(
        api.produce_audit_data(
            engagement["id"],
            data_production_payload([family_line_id, UNKNOWN_STATEMENT_LINE_ID]),
            ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_STATEMENT_LINE_NOT_FOUND.value,
        404,
    )

    unchanged = validate_success(
        api.get_audit_engagement(engagement["id"], ADMIN_HEADERS), 200
    )
    assert unchanged["produced_line_count"] == 1
    assert unchanged["production_status"] == "PARTIAL"


# ─────────────────────────────────────────────────────
# The supersede-overlapping flag
# ─────────────────────────────────────────────────────

def test_supersede_overlapping_clears_the_same_claimants_incumbent_row(api):
    """A holder re-filing over its own approved share with supersede_overlapping set moves that incumbent row to SUPERSEDED before the share ceiling is tested, so the re-filing approves cleanly.

    PRD: "If the registration was filed with `supersede_overlapping` set to true, then before the share ceiling of §3.4 is tested, every `APPROVED` registration sharing the same work, the same `right_type` and the same `claimant_id`, whose `territory_set` intersects this one's and whose half-open interval overlaps this one's, is moved `APPROVED → SUPERSEDED`."

    Design: Corner/endpoints/supersede_overlapping_flag_is_scoped_to_the_same_claimant
    """
    fixture = _setup_approved_gb_master_claim(api)
    work_id = fixture["recording"]["id"]
    incumbent_id = fixture["incumbent"]["id"]
    assert fixture["incumbent"]["status"] == "APPROVED"

    refiling, approve_response = _setup_reviewed_supersede_claim(
        api, work_id, fixture["label"]["id"]
    )
    approved = validate_success(approve_response, 200)
    assert refiling["supersede_overlapping"] is True
    assert approved["status"] == "APPROVED"

    incumbent = validate_success(
        api.get_rights_registration(incumbent_id, ANALYST_HEADERS), 200
    )
    assert incumbent["status"] == "SUPERSEDED"

    still_approved = validate_success(
        api.list_rights_registrations(
            ANALYST_HEADERS, params={"work_id": work_id, "status": "APPROVED"}
        ),
        200,
    )
    assert len(still_approved) == 1
    assert still_approved[0]["id"] == refiling["id"]

    work = validate_success(api.get_work(work_id, ANALYST_HEADERS), 200)
    assert work["rights_state"] == "REGISTERED"


def test_supersede_overlapping_does_not_clear_a_rival_claimants_row(api):
    """A rival claimant setting supersede_overlapping cannot displace another holder's approved share, so its approval trips the per-territory share ceiling instead.

    PRD: "If any territory's total exceeds 10,000 basis points, the approval is refused with `ERR_SHARE_OVERSUBSCRIBED`; a total of exactly 10,000 is accepted and a total of 10,001 is not."

    Design: Corner/endpoints/supersede_overlapping_flag_is_scoped_to_the_same_claimant
    """
    fixture = _setup_approved_gb_master_claim(api)
    work_id = fixture["recording"]["id"]

    refiling, approve_response = _setup_reviewed_supersede_claim(
        api, work_id, fixture["label"]["id"]
    )
    validate_success(approve_response, 200)

    rival, rival_approve_response = _setup_reviewed_supersede_claim(
        api, work_id, fixture["distributor"]["id"]
    )
    validate_error(
        rival_approve_response,
        ApiErrorId.ERR_SHARE_OVERSUBSCRIBED.value,
        409,
    )

    rival_after = validate_success(
        api.get_rights_registration(rival["id"], ANALYST_HEADERS), 200
    )
    assert rival_after["status"] == "UNDER_REVIEW"

    still_approved = validate_success(
        api.list_rights_registrations(
            ANALYST_HEADERS, params={"work_id": work_id, "status": "APPROVED"}
        ),
        200,
    )
    assert len(still_approved) == 1
    assert still_approved[0]["id"] == refiling["id"]

    work = validate_success(api.get_work(work_id, ANALYST_HEADERS), 200)
    assert work["rights_state"] == "REGISTERED"
