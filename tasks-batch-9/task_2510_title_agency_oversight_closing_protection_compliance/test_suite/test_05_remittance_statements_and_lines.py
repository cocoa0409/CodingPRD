"""Remittance statements: period intervals, line linkage and the per-line premium split."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line,
    agency_version,
    assert_money_equal,
    assert_split_conserves,
    assert_statement_status,
    assert_total_count,
    create_policy_file,
    create_statement,
    factories,
    ids_of,
    issue_policy,
    onboard_agency,
    read_agency,
    statement_lines,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OFFICER


class TestRemittancePeriodIntervals:
    """Periods are closed date intervals over the agency's reporting calendar."""

    def test_a_period_sharing_one_endpoint_day_is_an_overlap(self, api, env):
        """June 30 belongs to the June statement, so a period reusing it is refused.

        PRD: "Two closed intervals overlap when the new `period_start` is on or before
        the existing `period_end` and the existing `period_start` is on or before the new
        `period_end`; an overlap is refused with `ERR_REMITTANCE_PERIOD_OVERLAP` (HTTP
        409)."

        Design: Difficulty/resource_temporal_overlap/remittance_period_overlap_rejected_while_next_day_adjacency_is_accepted
        """
        create_statement(api, env, "2026-06-01", "2026-06-30")
        version_before = agency_version(api, env.agency_id)

        response = api.create_statement(
            factories.create_statement_payload(
                env.agency_id, "2026-06-30", "2026-07-31", version_before
            ),
            env.principal,
        )

        validate_error(response, ApiErrorId.ERR_REMITTANCE_PERIOD_OVERLAP.value, 409)
        assert agency_version(api, env.agency_id) == version_before, (
            "the rejected create must leave the agency version at "
            f"{version_before}, got {agency_version(api, env.agency_id)}"
        )

    def test_a_period_starting_the_next_day_is_accepted(self, api, env):
        """Adjacency is not overlap, so July 1 opens cleanly behind a June 30 close.

        PRD: "A period that begins exactly one day after an existing period ends is
        therefore accepted."

        Design: Difficulty/resource_temporal_overlap/remittance_period_overlap_rejected_while_next_day_adjacency_is_accepted
        """
        create_statement(api, env, "2026-06-01", "2026-06-30")
        rejected = api.create_statement(
            factories.create_statement_payload(
                env.agency_id, "2026-06-30", "2026-07-31", agency_version(api, env.agency_id)
            ),
            env.principal,
        )
        validate_error(rejected, ApiErrorId.ERR_REMITTANCE_PERIOD_OVERLAP.value, 409)

        july = create_statement(api, env, "2026-07-01", "2026-07-31")

        assert july["period_start"] == "2026-07-01", (
            f"the accepted period must start 2026-07-01, got {july['period_start']}"
        )
        assert_statement_status(july, "DRAFT")
        _rows, meta = validate_paginated(
            api.list_statements(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(meta, 2)


class TestPremiumSplitRoundingOrder:
    """Each line rounds first; the statement sums the already-rounded legs."""

    def test_each_line_rounds_before_the_statement_sums(self, api, env):
        """Three lines of 33,333 at 0.80 give 26,666 and 6,667 apiece.

        PRD: "The line's `agency_retention_cents` is the reported premium multiplied by
        that state program's `premium_split_agency_pct`, rounded half up to a whole cent;
        the line's `underwriter_share_cents` is then the reported premium minus that
        retention."

        Design: Difficulty/combinatorial_formula/premium_split_rounds_each_line_then_sums
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        lines = []
        for closing_date in ("2026-07-05", "2026-07-10", "2026-07-20"):
            policy_file = create_policy_file(
                api, env, closing_date=closing_date, gross_premium_cents=33_333
            )
            issue_policy(api, env, policy_file["id"])
            lines.append(
                add_line(api, env, statement["id"], policy_file["id"], 33_333)
            )

        for index, line in enumerate(lines, start=1):
            assert_money_equal(
                line["agency_retention_cents"],
                26_666,
                f"line {index} agency_retention_cents",
            )
            assert_money_equal(
                line["underwriter_share_cents"],
                6_667,
                f"line {index} underwriter_share_cents",
            )
            assert_split_conserves(
                33_333,
                line["agency_retention_cents"],
                line["underwriter_share_cents"],
                f"line {index}",
            )

        totals = validate_success(api.get_statement(statement["id"], OFFICER))
        assert_money_equal(
            totals["reported_gross_premium_cents"],
            99_999,
            "statement reported_gross_premium_cents",
        )
        assert_money_equal(
            totals["agency_retention_cents"], 79_998, "statement agency_retention_cents"
        )
        assert_money_equal(
            totals["underwriter_share_cents"],
            20_001,
            "statement underwriter_share_cents",
        )

    def test_submission_refreshes_the_totals_in_the_rounded_order(self, api, env):
        """The submitted statement carries 20,001, not the 20,000 of the wrong order.

        PRD: "Statement totals are then sums of the already-rounded line values, per the
        order-of-operations rule in Section 2.5: the statement's
        `reported_gross_premium_cents` is the sum of the line reported premiums, its
        `agency_retention_cents` is the sum of the line retentions, and its
        `underwriter_share_cents` is the sum of the line underwriter shares."

        Design: Difficulty/combinatorial_formula/premium_split_rounds_each_line_then_sums
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        for closing_date in ("2026-07-05", "2026-07-10", "2026-07-20"):
            policy_file = create_policy_file(
                api, env, closing_date=closing_date, gross_premium_cents=33_333
            )
            issue_policy(api, env, policy_file["id"])
            add_line(api, env, statement["id"], policy_file["id"], 33_333)

        submitted = submit_statement(api, env, statement["id"])

        assert_statement_status(submitted, "SUBMITTED")
        assert_money_equal(
            submitted["reported_gross_premium_cents"],
            99_999,
            "reported_gross_premium_cents",
        )
        assert_money_equal(
            submitted["agency_retention_cents"], 79_998, "agency_retention_cents"
        )
        assert_money_equal(
            submitted["underwriter_share_cents"], 20_001, "underwriter_share_cents"
        )
        assert submitted["submitted_at"] is not None, (
            "submission stamps submitted_at with the clock instant, but it is null"
        )

    def test_an_exact_half_cent_rounds_half_up(self, api, state_program):
        """12,012 at 0.875 is exactly 10,510.5 and must land on 10,511.

        PRD: "A single-line illustration of the half-up direction: a reported premium of
        12,012 cents at a retention fraction of 0.875 gives the exact product 10,510.5,
        which becomes 10,511 cents of retention — banker's rounding would give 10,510 —
        leaving 1,501 cents of underwriter share."

        Design: Corner/calculations/precision_line_split_rounds_half_up_not_to_even
        """
        program = validate_success(
            api.create_state_program(
                factories.create_state_program_payload(premium_split_agency_pct=0.875),
                OFFICER,
            ),
            201,
        )
        env = onboard_agency(api, state_program=program)
        policy_file = create_policy_file(
            api, env, closing_date="2026-07-15", gross_premium_cents=12_012
        )
        issue_policy(api, env, policy_file["id"])
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")

        line = add_line(api, env, statement["id"], policy_file["id"], 12_012)

        assert_money_equal(
            line["agency_retention_cents"], 10_511, "agency_retention_cents"
        )
        assert_money_equal(
            line["underwriter_share_cents"], 1_501, "underwriter_share_cents"
        )
        assert_split_conserves(
            12_012,
            line["agency_retention_cents"],
            line["underwriter_share_cents"],
            "half-cent line",
        )
        assert line["premium_mismatch"] is False, (
            "the reported figure equals the policy's gross_premium_cents, so "
            f"premium_mismatch must be false, got {line['premium_mismatch']!r}"
        )


class TestLineReferentialRules:
    """The three referential rules that guard a line, and the path that precedes them."""

    def test_line_under_an_unknown_statement_reports_the_path_segment(self, api):
        """Path resolution runs before any body reference is looked at.

        PRD: "Path parameters are resolved strictly left to right, and each segment
        produces its own not-found error before anything to its right is examined"

        Design: Corner/entities/parent_relationships_line_under_unknown_statement_returns_404
        """
        response = api.create_line(
            NON_EXISTENT_UUID,
            factories.create_line_payload(
                "11111111-1111-4111-8111-111111111111", 33_333
            ),
            {
                "X-User-ID": "11111111-1111-4111-8111-111111111111",
                "X-User-Role": "AgencyPrincipal",
                "Content-Type": "application/json",
            },
        )

        validate_error(
            response, ApiErrorId.ERR_REMITTANCE_STATEMENT_NOT_FOUND.value, 404
        )
        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_POLICY_FILE_NOT_FOUND.value, (
            "the unresolvable path segment outranks the unresolvable body reference, "
            f"but the response carried {body['data']['error_id']}"
        )

    def test_line_requires_an_issued_policy_and_then_succeeds(self, api, env):
        """The identical POST is refused while the file is `PENDING` and accepted after.

        PRD: "The referenced policy must belong to the same agency as the statement and
        must have an `issuance_status` of `ISSUED` or `LATE_ISSUED`, else
        `ERR_LINE_POLICY_NOT_ISSUED` (HTTP 422) — a pending, declined or voided file
        cannot be remitted, and neither can another agency's file."

        Design: Corner/validations/cross_entity_validation_line_requires_issued_policy_then_succeeds
        """
        policy_file = create_policy_file(
            api, env, closing_date="2026-07-20", gross_premium_cents=33_333
        )
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")

        refused = api.create_line(
            statement["id"],
            factories.create_line_payload(policy_file["id"], 33_333),
            env.principal,
        )
        validate_error(refused, ApiErrorId.ERR_LINE_POLICY_NOT_ISSUED.value, 422)
        _rows, empty_meta = validate_paginated(
            api.list_lines(statement["id"], OFFICER)
        )
        assert_total_count(empty_meta, 0)

        issue_policy(api, env, policy_file["id"], policy_number="POL-741")

        line = add_line(api, env, statement["id"], policy_file["id"], 33_333)

        assert_money_equal(
            line["agency_retention_cents"], 26_666, "agency_retention_cents"
        )
        assert_money_equal(
            line["underwriter_share_cents"], 6_667, "underwriter_share_cents"
        )
        after = validate_success(api.get_statement(statement["id"], OFFICER))
        assert_money_equal(
            after["reported_gross_premium_cents"],
            33_333,
            "statement reported_gross_premium_cents",
        )

    def test_line_requires_the_policy_to_close_inside_the_period(self, api, env):
        """A June closing cannot be reported on the July statement.

        PRD: "The policy's `closing_date` must fall inside the statement's period,
        inclusive of both bounds, else `ERR_POLICY_NOT_IN_PERIOD` (HTTP 422)."

        Design: Corner/endpoints/cross_reference_link_line_requires_the_policy_to_close_inside_the_period_returns_422
        """
        june = create_policy_file(
            api, env, closing_date="2026-06-25", gross_premium_cents=500_000
        )
        june_issued = issue_policy(api, env, june["id"])
        assert june_issued["issuance_status"] == "LATE_ISSUED", (
            "2026-06-25 is 37 elapsed days from the clock, so the file must be "
            f"LATE_ISSUED, got {june_issued['issuance_status']}"
        )
        july = create_policy_file(
            api, env, closing_date="2026-07-10", gross_premium_cents=600_000
        )
        july_issued = issue_policy(api, env, july["id"])
        assert july_issued["issuance_status"] == "ISSUED", (
            f"the July file must be ISSUED, got {july_issued['issuance_status']}"
        )
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")

        refused = api.create_line(
            statement["id"],
            factories.create_line_payload(june["id"], 500_000),
            env.principal,
        )
        validate_error(refused, ApiErrorId.ERR_POLICY_NOT_IN_PERIOD.value, 422)

        line = add_line(api, env, statement["id"], july["id"], 600_000)
        assert line["policy_file_id"] == july["id"], (
            f"the line must link the July policy, got {line['policy_file_id']}"
        )

        _july_rows, july_meta = validate_paginated(
            api.list_policy_remittance_lines(july["id"], OFFICER)
        )
        assert_total_count(july_meta, 1)
        _june_rows, june_meta = validate_paginated(
            api.list_policy_remittance_lines(june["id"], OFFICER)
        )
        assert_total_count(june_meta, 0)

    def test_submitting_a_statement_with_no_lines_is_refused(self, api, env):
        """`DRAFT` to `SUBMITTED` exists, so only its own precondition can block it.

        PRD: "It requires at least one line — an empty statement is refused with
        `ERR_STATEMENT_HAS_NO_LINES` (HTTP 409) — and it requires that the agency's
        `appointment_status` not be `TERMINATED`, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/precondition_enforcement_submit_statement_without_lines_returns_409
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        assert_statement_status(statement, "DRAFT")

        response = api.transition_statement(
            statement["id"],
            factories.statement_state_payload("SUBMITTED"),
            env.principal,
        )

        validate_error(response, ApiErrorId.ERR_STATEMENT_HAS_NO_LINES.value, 409)

        after = validate_success(api.get_statement(statement["id"], OFFICER))
        assert_statement_status(after, "DRAFT")
        assert after["submitted_at"] is None, (
            f"submitted_at must still be null, got {after['submitted_at']!r}"
        )
        _rows, meta = validate_paginated(api.list_lines(statement["id"], OFFICER))
        assert_total_count(meta, 0)


class TestPremiumMismatchFlag:
    """`premium_mismatch` is derived per line and is a list filter."""

    def test_line_list_filters_on_the_premium_mismatch_flag(self, api, env):
        """Two lines, one under-reported, and the filter returns exactly that one.

        PRD: "Each line also carries `premium_mismatch`, which is true exactly when the
        line's `reported_gross_premium_cents` differs from the referenced policy's
        `gross_premium_cents` and false otherwise."

        Design: Corner/endpoints/computed_read_line_list_filters_on_the_premium_mismatch_flag
        """
        matching_policy = create_policy_file(
            api, env, closing_date="2026-07-10", gross_premium_cents=33_333
        )
        issue_policy(api, env, matching_policy["id"])
        short_policy = create_policy_file(
            api, env, closing_date="2026-07-11", gross_premium_cents=50_000
        )
        issue_policy(api, env, short_policy["id"])
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")

        matching_line = add_line(
            api, env, statement["id"], matching_policy["id"], 33_333
        )
        short_line = add_line(api, env, statement["id"], short_policy["id"], 20_000)

        assert matching_line["premium_mismatch"] is False, (
            "33,333 reported against a 33,333 policy is no mismatch, got "
            f"{matching_line['premium_mismatch']!r}"
        )
        assert short_line["premium_mismatch"] is True, (
            "20,000 reported against a 50,000 policy is a mismatch, got "
            f"{short_line['premium_mismatch']!r}"
        )

        flagged, flagged_meta = validate_paginated(
            api.list_lines(statement["id"], OFFICER, params={"premium_mismatch": True})
        )
        assert_total_count(flagged_meta, 1)
        assert ids_of(flagged) == [short_line["id"]], (
            f"the filter must return only the under-reported line, got {ids_of(flagged)}"
        )

        unfiltered = statement_lines(api, statement["id"])
        assert len(unfiltered) == 2, (
            f"the unfiltered list still shows both lines, got {len(unfiltered)}"
        )
        totals = validate_success(api.get_statement(statement["id"], OFFICER))
        assert_money_equal(
            totals["reported_gross_premium_cents"],
            53_333,
            "statement reported_gross_premium_cents",
        )
        assert_money_equal(
            totals["agency_retention_cents"], 42_666, "statement agency_retention_cents"
        )
        assert_money_equal(
            totals["underwriter_share_cents"],
            10_667,
            "statement underwriter_share_cents",
        )
        assert read_agency(api, env.agency_id)["unremitted_premium_cents"] == 83_333, (
            "both issued policies are still unremitted, so the ledger must read 83,333"
        )
