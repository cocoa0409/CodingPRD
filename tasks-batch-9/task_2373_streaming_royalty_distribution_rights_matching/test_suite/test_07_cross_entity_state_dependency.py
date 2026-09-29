"""Gates that live on a sibling or remote entity rather than on the addressed one.

Three areas are exercised: calculating a royalty pool while an unrelated usage
batch of the same period is still open, issuing a statement whose emptiness is
decided by the approval state of a rights registration, and opening an audit
engagement bounded by the audited statement's issue time and by the number of
statement lines that statement carries.
"""

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    append_line,
    assert_pool_value_conservation,
    assert_statement_totals,
    audit_engagement_payload,
    create_batch,
    create_effective_schedule,
    create_engagement,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    create_statement,
    data_production_payload,
    findings_payload,
    make_rights_holder_user_headers,
    period_version,
    produce_audit_data,
    seal_and_match_batch,
    seal_batch,
    set_clock,
    setup_all_matched_pool_finalized,
    setup_canonical_statement_issued,
    statement_lines,
    statement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["royalty_admin_headers"]
MATCHER = TEST_USERS["fuzzy_matcher_headers"]


# ─────────────────────────────────────────────────────
# Composite setups
# ─────────────────────────────────────────────────────

def _setup_pool_with_one_open_sibling_batch(api):
    """One period holding two GB/INDIVIDUAL batches — batch A sealed and matched
    by exact ISRC, batch B still OPEN — plus a DRAFT GB/INDIVIDUAL pool.

    The pool references neither batch, and nothing about the pool itself is
    defective; only the still-open sibling keeps the period out of
    ``USAGE_SEALED``.
    """
    fixture = {"schedule": create_effective_schedule(api)}
    fixture["period"] = create_period(api)
    fixture["recording"] = create_recording(api)
    period_id = fixture["period"]["id"]

    fixture["batch_a"] = create_batch(api, period_id, source_label="UK client feed")
    fixture["line_a"] = append_line(
        api,
        fixture["batch_a"]["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=300000,
    )
    # Batch B is opened while the period is still OPEN. Matching batch A first
    # would leave it the period's only batch, which per PRD §3.3 flips the
    # period OPEN -> USAGE_SEALED and makes opening batch B illegal (§3.2).
    fixture["batch_b"] = create_batch(api, period_id, source_label="IE client feed")
    fixture["line_b"] = append_line(
        api,
        fixture["batch_b"]["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=150000,
    )

    fixture["batch_a_after_match"] = seal_and_match_batch(api, fixture["batch_a"]["id"])

    fixture["pool"] = create_pool(
        api,
        period_id,
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    return fixture


def _finish_sibling_batch(api, fixture):
    """Seal and match batch B, which is what bubbles the period up."""
    seal_batch(api, fixture["batch_b"]["id"])
    fixture["batch_b_after_match"] = validate_success(
        api.match_usage_batch(fixture["batch_b"]["id"], MATCHER), 200
    )
    return fixture


def _setup_finalized_pool_and_unclaimed_publisher(api):
    """The all-matched GB/INDIVIDUAL fixture — two exact-ISRC lines, the label's
    MASTER claim approved, the pool FINALIZED — plus a publisher that holds no
    registration of any kind."""
    fixture = setup_all_matched_pool_finalized(api)
    fixture["publisher"] = create_publisher(
        api, legal_name="Tidewater Songs", territory="GB", rate_bps=800
    )
    return fixture


def _setup_engagement_at_audit_window_bound(api):
    """The canonical two-line issued statement, with the clock moved to exactly
    180 days after ``issued_at`` and one engagement opened there."""
    fixture = setup_canonical_statement_issued(api)
    set_clock(api, "2027-01-28T00:00:00Z")
    fixture["engagement"] = create_engagement(
        api, fixture["label"]["id"], fixture["statement"]["id"]
    )
    return fixture


# ─────────────────────────────────────────────────────
# pool_calculate_gated_by_sibling_batch_state
# ─────────────────────────────────────────────────────

class TestPoolCalculateGatedBySiblingBatchState:

    def test_calculate_refused_while_an_unrelated_sibling_batch_is_open(self, api):
        """Calculating a flawless DRAFT pool is refused with ERR_INVALID_PERIOD_STATE while a sibling usage batch of the same period is still OPEN.

        PRD: "In the first two cases the parent period's `status` must be `USAGE_SEALED` or `REOPENED`; in the third it must be `REOPENED`."

        Design: Difficulty/cross_entity_state_dependency/pool_calculate_gated_by_sibling_batch_state
        """
        fixture = _setup_pool_with_one_open_sibling_batch(api)

        assert fixture["batch_a_after_match"]["status"] == "MATCHED"
        assert fixture["batch_b"]["status"] == "OPEN"
        assert fixture["pool"]["status"] == "DRAFT"

        period_before = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN), 200
        )
        assert period_before["status"] == "OPEN"

        response = api.calculate_pool(fixture["pool"]["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_PERIOD_STATE.value, 409)

        pool_after = validate_success(api.get_pool(fixture["pool"]["id"], ADMIN), 200)
        assert pool_after["status"] == "DRAFT"
        assert pool_after["applied_rate_schedule_id"] is None
        assert pool_after["distributable_cents"] == 0

    def test_matching_the_sibling_batch_bubbles_the_period_to_usage_sealed(self, api):
        """Sealing and matching the last outstanding batch flips the period from OPEN to USAGE_SEALED with no call ever addressing the period.

        PRD: "It fires when the period owns at least one usage batch and every batch of the period has a `status` of either `MATCHED` or `PARTIALLY_MATCHED`; the last batch to finish matching is the one that flips the period."

        Design: Difficulty/cross_entity_state_dependency/pool_calculate_gated_by_sibling_batch_state
        """
        fixture = _setup_pool_with_one_open_sibling_batch(api)

        period_before = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN), 200
        )
        assert period_before["status"] == "OPEN"

        _finish_sibling_batch(api, fixture)
        assert fixture["batch_b_after_match"]["status"] == "MATCHED"

        period_after = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN), 200
        )
        assert period_after["status"] == "USAGE_SEALED"
        assert period_after["version"] > period_before["version"]

    def test_identical_calculate_succeeds_once_the_sibling_batch_is_matched(self, api):
        """The identical calculate call that was refused now sizes the pool over both batches, reaching total_play_count 450000 and distributable_cents 999999.

        PRD: "`distributable_cents` is the largest of three quantities: the lesser of `revenue_share_pool_cents` and three times `minimum_pool_cents`; `minimum_pool_cents` itself; and `statutory_floor_cents`."

        Design: Difficulty/cross_entity_state_dependency/pool_calculate_gated_by_sibling_batch_state
        """
        fixture = _setup_pool_with_one_open_sibling_batch(api)

        blocked = api.calculate_pool(fixture["pool"]["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_INVALID_PERIOD_STATE.value, 409)

        _finish_sibling_batch(api, fixture)

        pool = validate_success(api.calculate_pool(fixture["pool"]["id"], ADMIN), 200)
        assert pool["status"] == "CALCULATED"
        assert pool["total_play_count"] == 450000
        assert pool["revenue_share_pool_cents"] == 999999
        assert pool["minimum_pool_cents"] == 500000
        assert pool["statutory_floor_cents"] == 45000
        assert pool["distributable_cents"] == 999999
        assert pool["allocation_basis"] == "REVENUE_SHARE"
        assert pool["applied_rate_schedule_id"] == fixture["schedule"]["id"]

    def test_attribution_after_the_sibling_batch_is_matched(self, api):
        """Attribution rounded down spreads 999999 cents as 666666 and 333333 over the two batches' lines, leaving rounding_residual_cents 0.

        PRD: "Every other line receives `distributable_cents` multiplied by its own `play_count`, divided by `denominator_play_count`, rounded **down** to a whole cent."

        Design: Difficulty/cross_entity_state_dependency/pool_calculate_gated_by_sibling_batch_state
        """
        fixture = _setup_pool_with_one_open_sibling_batch(api)

        blocked = api.calculate_pool(fixture["pool"]["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_INVALID_PERIOD_STATE.value, 409)

        _finish_sibling_batch(api, fixture)
        pool = validate_success(api.calculate_pool(fixture["pool"]["id"], ADMIN), 200)

        assert pool["denominator_basis"] == "ALL_USAGE"
        assert pool["denominator_play_count"] == 450000

        line_a = validate_success(api.get_usage_line(fixture["line_a"]["id"], ADMIN), 200)
        line_b = validate_success(api.get_usage_line(fixture["line_b"]["id"], ADMIN), 200)
        assert line_a["attributed_revenue_cents"] == 666666
        assert line_b["attributed_revenue_cents"] == 333333

        assert pool["matched_attributed_cents"] == 999999
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert_pool_value_conservation(pool)


# ─────────────────────────────────────────────────────
# statement_issue_gated_by_registration_approval_elsewhere
# ─────────────────────────────────────────────────────

class TestStatementIssueGatedByRegistrationApprovalElsewhere:

    def test_statement_for_a_holder_without_an_approved_claim_is_created_empty(self, api):
        """A statement addressed to a holder that owns no APPROVED registration is created successfully as a DRAFT with line_count 0 and gross_cents 0.

        PRD: "A registration participates when its `status` is `APPROVED`, when its `territory_set` intersects the usage line's `territory_code` — with `WORLD` acting as the wildcard of §2.7 — when its `payee_holder_id` equals the statement's `rights_holder_id`, when the period's `usage_end` falls inside its half-open interval, meaning `effective_from` is on or before `usage_end` and `effective_to` is strictly after `usage_end`, and when it points at the right work for the right it claims."

        Design: Difficulty/cross_entity_state_dependency/statement_issue_gated_by_registration_approval_elsewhere
        """
        fixture = _setup_finalized_pool_and_unclaimed_publisher(api)
        period_id = fixture["period"]["id"]

        registrations, meta = validate_paginated(
            api.list_rights_registrations(
                ADMIN, params={"payee_holder_id": fixture["publisher"]["id"]}
            )
        )
        assert registrations == []
        assert meta["total_count"] == 0

        response = api.create_statement(
            statement_payload(
                fixture["publisher"]["id"], period_id, period_version(api, period_id)
            ),
            ADMIN,
        )
        statement = validate_success(response, 201)
        assert statement["status"] == "DRAFT"
        assert statement["issued_at"] is None
        assert statement["line_count"] == 0
        assert statement["gross_cents"] == 0
        assert statement["admin_fee_cents"] == 0
        assert statement["net_payable_cents"] == 0

    def test_issuing_the_empty_statement_is_refused(self, api):
        """Issuing the publisher's zero-line statement is refused with ERR_NO_STATEMENT_LINES, the statement stays DRAFT and no cent reaches the publisher's balance.

        PRD: "A statement that assembled to no lines at all cannot be issued and is refused with `ERR_NO_STATEMENT_LINES`; a statement that is not `DRAFT` is refused with `ERR_INVALID_STATEMENT_STATE`."

        Design: Difficulty/cross_entity_state_dependency/statement_issue_gated_by_registration_approval_elsewhere
        """
        fixture = _setup_finalized_pool_and_unclaimed_publisher(api)
        publisher_id = fixture["publisher"]["id"]

        statement = create_statement(api, publisher_id, fixture["period"]["id"])
        assert statement["line_count"] == 0

        response = api.issue_statement(statement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_NO_STATEMENT_LINES.value, 422)

        after = validate_success(api.get_statement(statement["id"], ADMIN), 200)
        assert after["status"] == "DRAFT"
        assert after["issued_at"] is None

        publisher = validate_success(api.get_rights_holder(publisher_id, ADMIN), 200)
        assert publisher["receivable_balance_cents"] == 0
        assert publisher["issued_statement_count"] == 0

    def test_statement_for_the_holder_with_the_approved_claim_issues(self, api):
        """Over the very same period and pool, the label's statement carries one line of 750000 gross, 60000 admin fee and 690000 net, and issues onto the label's balance.

        PRD: "Issuing moves the statement `DRAFT → ISSUED`, stamps `issued_at` from the logical clock, raises the payee's `receivable_balance_cents` by exactly `net_payable_cents`, increments the payee's `issued_statement_count` by 1, and increments the statement's `version`."

        Design: Difficulty/cross_entity_state_dependency/statement_issue_gated_by_registration_approval_elsewhere
        """
        fixture = _setup_finalized_pool_and_unclaimed_publisher(api)
        period_id = fixture["period"]["id"]
        label_id = fixture["label"]["id"]

        empty_statement = create_statement(api, fixture["publisher"]["id"], period_id)
        validate_error(
            api.issue_statement(empty_statement["id"], ADMIN),
            ApiErrorId.ERR_NO_STATEMENT_LINES.value,
            422,
        )

        statement = create_statement(api, label_id, period_id)
        assert statement["line_count"] == 1
        assert statement["gross_cents"] == 750000
        assert statement["admin_fee_cents"] == 60000
        assert statement["net_payable_cents"] == 690000

        lines = statement_lines(api, statement["id"])
        assert_statement_totals(statement, lines)
        assert lines[0]["line_type"] == "USAGE"
        assert lines[0]["right_type"] == "MASTER"
        assert lines[0]["routing"] == "DIRECT"
        assert lines[0]["payee_holder_id"] == label_id
        assert lines[0]["gross_cents"] == 750000
        assert lines[0]["admin_fee_cents"] == 60000
        assert lines[0]["net_cents"] == 690000

        issued = validate_success(api.issue_statement(statement["id"], ADMIN), 200)
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] is not None
        assert issued["net_payable_cents"] == 690000

        label = validate_success(api.get_rights_holder(label_id, ADMIN), 200)
        assert label["receivable_balance_cents"] == 690000
        assert label["issued_statement_count"] == 1

    def test_no_residual_line_rescues_the_publishers_statement(self, api):
        """The pool's residual payee is the label and its rounding residual is 0, so the publisher's statement receives no RESIDUAL line either.

        PRD: "When the pool's `residual_payee_holder_id` equals this statement's `rights_holder_id` and the pool's `rounding_residual_cents` is not zero, the statement also carries a residual line: `line_type` `RESIDUAL`, `work_id` null, `right_type` null, `routing` null, `play_count` 0, `share_bps` 10,000, `gross_cents` equal to the pool's `rounding_residual_cents`, `admin_fee_cents` 0, and `net_cents` equal to that same residual."

        Design: Difficulty/cross_entity_state_dependency/statement_issue_gated_by_registration_approval_elsewhere
        """
        fixture = _setup_finalized_pool_and_unclaimed_publisher(api)

        pool = validate_success(api.get_pool(fixture["pool"]["id"], ADMIN), 200)
        assert pool["status"] == "FINALIZED"
        assert pool["residual_payee_holder_id"] == fixture["label"]["id"]
        assert pool["rounding_residual_cents"] == 0

        statement = create_statement(
            api, fixture["publisher"]["id"], fixture["period"]["id"]
        )
        lines, meta = validate_paginated(
            api.list_statement_lines(ADMIN, params={"statement_id": statement["id"]})
        )
        assert lines == []
        assert meta["total_count"] == 0
        assert statement["line_count"] == 0


# ─────────────────────────────────────────────────────
# audit_engagement_gated_by_statement_issue_time_and_line_count
# ─────────────────────────────────────────────────────

class TestAuditEngagementGatedByStatementIssueTimeAndLineCount:

    def test_engagement_one_second_past_the_audit_window_is_refused(self, api):
        """One second past 180 days after the audited statement's issued_at, opening an engagement is refused with ERR_AUDIT_WINDOW_EXPIRED and nothing is created.

        PRD: "An `AuditEngagement` may be opened only while the current instant is at or before 180 days after the audited statement's `issued_at`."

        Design: Difficulty/cross_entity_state_dependency/audit_engagement_gated_by_statement_issue_time_and_line_count
        """
        fixture = setup_canonical_statement_issued(api)
        statement = fixture["statement"]
        assert statement["status"] == "ISSUED"
        assert statement["issued_at"].startswith("2026-08-01T00:00:00")

        set_clock(api, "2027-01-28T00:00:01Z")

        response = api.create_audit_engagement(
            audit_engagement_payload(fixture["label"]["id"], statement["id"]),
            make_rights_holder_user_headers(fixture["label"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_AUDIT_WINDOW_EXPIRED.value, 422)

        engagements, meta = validate_paginated(
            api.list_audit_engagements(ADMIN, params={"statement_id": statement["id"]})
        )
        assert engagements == []
        assert meta["total_count"] == 0

    def test_engagement_exactly_at_the_audit_window_bound_is_created(self, api):
        """Exactly at the inclusive bound the engagement is created, freezing required_line_count 2 from the audited statement and a production deadline 30 days out.

        PRD: "On creation the service freezes `required_line_count` from the number of statement lines the audited statement carries at that moment — frozen thereafter, so lines added later do not move the target — computes `production_deadline_at` as `created_at` advanced by 30 days, and sets `produced_line_count` to 0, `production_status` to `PENDING` and `finding_status` to `NONE`."

        Design: Difficulty/cross_entity_state_dependency/audit_engagement_gated_by_statement_issue_time_and_line_count
        """
        fixture = setup_canonical_statement_issued(api)
        assert len(fixture["statement_lines"]) == 2

        set_clock(api, "2027-01-28T00:00:00Z")

        response = api.create_audit_engagement(
            audit_engagement_payload(
                fixture["label"]["id"], fixture["statement"]["id"]
            ),
            make_rights_holder_user_headers(fixture["label"]["id"]),
        )
        engagement = validate_success(response, 201)
        assert engagement["required_line_count"] == 2
        assert engagement["produced_line_count"] == 0
        assert engagement["production_status"] == "PENDING"
        assert engagement["finding_status"] == "NONE"
        assert engagement["production_deadline_at"].startswith("2027-02-27T00:00:00")

    def test_findings_with_a_partial_production_are_refused(self, api):
        """With one of the audited statement's two lines produced the engagement is PARTIAL, and asserting a finding is refused with ERR_DATA_PRODUCTION_INCOMPLETE.

        PRD: "The engagement's `finding_status` must be `NONE`, or the request is refused with `ERR_INVALID_ENGAGEMENT_STATE`, and its `production_status` must be `COMPLETE` — a `PENDING` or `PARTIAL` production is not enough, and asserting against one is refused with `ERR_DATA_PRODUCTION_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/audit_engagement_gated_by_statement_issue_time_and_line_count
        """
        fixture = _setup_engagement_at_audit_window_bound(api)
        engagement_id = fixture["engagement"]["id"]
        label_id = fixture["label"]["id"]

        partial = produce_audit_data(
            api, engagement_id, [fixture["statement_lines"][0]["id"]]
        )
        assert partial["produced_line_count"] == 1
        assert partial["production_status"] == "PARTIAL"
        assert partial["finding_status"] == "NONE"

        response = api.record_audit_findings(
            engagement_id,
            findings_payload(5000),
            make_rights_holder_user_headers(label_id),
        )
        validate_error(response, ApiErrorId.ERR_DATA_PRODUCTION_INCOMPLETE.value, 422)

        after = validate_success(api.get_audit_engagement(engagement_id, ADMIN), 200)
        assert after["finding_status"] == "NONE"
        assert after["production_status"] == "PARTIAL"
        assert after["asserted_underpayment_cents"] == 0

    def test_findings_succeed_once_every_statement_line_is_produced(self, api):
        """Once the second line is produced the engagement is COMPLETE and the identical findings call succeeds, moving finding_status to ASSERTED.

        PRD: "A successful assertion stores the amount and the note, stamps `findings_recorded_by_user_id` with the caller's `X-User-ID`, and moves `finding_status` `NONE → ASSERTED` while leaving `production_status` exactly where it was."

        Design: Difficulty/cross_entity_state_dependency/audit_engagement_gated_by_statement_issue_time_and_line_count
        """
        fixture = _setup_engagement_at_audit_window_bound(api)
        engagement_id = fixture["engagement"]["id"]
        label_id = fixture["label"]["id"]

        produce_audit_data(api, engagement_id, [fixture["statement_lines"][0]["id"]])
        blocked = api.record_audit_findings(
            engagement_id,
            findings_payload(5000),
            make_rights_holder_user_headers(label_id),
        )
        validate_error(blocked, ApiErrorId.ERR_DATA_PRODUCTION_INCOMPLETE.value, 422)

        complete = validate_success(
            api.produce_audit_data(
                engagement_id,
                data_production_payload([fixture["statement_lines"][1]["id"]]),
                ADMIN,
            ),
            200,
        )
        assert complete["produced_line_count"] == 2
        assert complete["production_status"] == "COMPLETE"
        assert complete["finding_status"] == "NONE"

        response = api.record_audit_findings(
            engagement_id,
            findings_payload(5000),
            make_rights_holder_user_headers(label_id),
        )
        asserted = validate_success(response, 200)
        assert asserted["finding_status"] == "ASSERTED"
        assert asserted["production_status"] == "COMPLETE"
        assert asserted["asserted_underpayment_cents"] == 5000
