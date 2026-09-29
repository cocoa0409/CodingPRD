"""The unremitted ledger, the posture thresholds and the three guarded creates."""

from test_helpers import (
    ApiErrorId,
    add_line,
    agency_version,
    assert_money_equal,
    assert_posture,
    assert_remittance_status,
    assert_total_count,
    create_policy_file,
    create_policy_file_payload,
    create_state_program,
    create_statement,
    create_statement_payload,
    issue_policy,
    onboard_agency,
    read_agency,
    reconcile_statement,
    reopen_statement,
    request_letter,
    request_letter_payload,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OFFICER


class TestUnremittedLedgerInputSet:
    """The ledger sums the issued files only, never the whole book of orders."""

    def test_pending_and_referred_files_stay_out_of_the_unremitted_ledger(
        self, api, env
    ):
        """700,000 issued against 500,000 pending and 900,000 referred gives 700,000.

        PRD: "`unremitted_premium_cents` is the sum of `gross_premium_cents` across the
        agency's policy files whose `issuance_status` is `ISSUED` or `LATE_ISSUED` and whose
        `remittance_status` is `UNREPORTED`, `REPORTED` or `DISPUTED`; settling a statement
        removes its reported policies from that set, and reopening the settled statement
        puts them back, returning the ledger to its exact pre-settlement value."

        Design: Corner/calculations/input_set_filtering_unremitted_ledger_counts_only_issued_files
        """
        to_be_issued = create_policy_file(
            api,
            env,
            closing_date="2026-07-10",
            liability_amount_cents=40_000_000,
            gross_premium_cents=700_000,
        )
        left_pending = create_policy_file(
            api,
            env,
            closing_date="2026-07-10",
            liability_amount_cents=40_000_000,
            gross_premium_cents=500_000,
        )
        referred = create_policy_file(
            api,
            env,
            closing_date="2026-07-10",
            liability_amount_cents=40_000_000,
            gross_premium_cents=900_000,
            complex_title_flag=True,
        )
        assert left_pending["issuance_status"] == "PENDING", (
            f"the second file must wait at PENDING, got {left_pending['issuance_status']}"
        )
        assert referred["issuance_status"] == "PENDING_REFERRAL", (
            "the complex-title file must be routed to counsel, got "
            f"{referred['issuance_status']}"
        )

        issued = issue_policy(api, env, to_be_issued["id"], policy_number="POL-621")

        assert issued["issuance_status"] == "ISSUED", (
            f"the first file must reach ISSUED, got {issued['issuance_status']}"
        )
        assert_remittance_status(issued, "UNREPORTED")
        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["unremitted_premium_cents"],
            700_000,
            "unremitted_premium_cents (the issued file alone)",
        )
        assert agency["unremitted_premium_cents"] != 2_100_000, (
            "2,100,000 is the sum of all three files, which is not the ledger's input "
            f"set, but the agency reads {agency['unremitted_premium_cents']}"
        )
        assert_posture(agency, "OPEN")


class TestUnremittedToleranceBoundary:
    """The tolerance clause is strict, so equality does not restrict."""

    def test_exactly_fifty_million_stays_open_and_one_more_cent_restricts(self, api):
        """50,000,000 unremitted is `OPEN`; 50,100,000 propagates to `RESTRICTED`.

        PRD: "Otherwise, the posture is `RESTRICTED` when any one of six conditions holds:
        `appointment_status` is `PENDING_REVIEW`; `financial_review_status` is anything
        other than `ACCEPTED`; `escrow_standing` is `WATCH`; `open_critical_finding_count`
        is at least 1; `unreported_policy_count` is at least 3; or
        `unremitted_premium_cents` is strictly greater than five hundred thousand dollars,
        that is, greater than 50,000,000 cents."

        Design: Corner/calculations/constraint_propagation_unremitted_tolerance_boundary_flips_posture_to_restricted
        """
        program = create_state_program(
            api, counsel_referral_threshold_cents=600_000_000
        )
        env = onboard_agency(
            api,
            state_program=program,
            agency_overrides={"underwriting_authority_limit_cents": 500_000_000},
        )
        first = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=400_000_000,
            gross_premium_cents=25_000_000,
        )
        second = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=400_000_000,
            gross_premium_cents=25_000_000,
        )
        assert first["issuance_status"] == "PENDING", (
            "400,000,000 is inside both the authority limit and the referral threshold, "
            f"so the file must land on PENDING, got {first['issuance_status']}"
        )
        issue_policy(api, env, first["id"], policy_number="POL-671")

        issue_policy(api, env, second["id"], policy_number="POL-672")

        at_boundary = read_agency(api, env.agency_id)
        assert_money_equal(
            at_boundary["unremitted_premium_cents"],
            50_000_000,
            "unremitted_premium_cents at the tolerance",
        )
        assert_posture(at_boundary, "OPEN")

        third = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=20_000_000,
            gross_premium_cents=100_000,
        )
        issue_policy(api, env, third["id"], policy_number="POL-673")

        over = read_agency(api, env.agency_id)
        assert_money_equal(
            over["unremitted_premium_cents"],
            50_100_000,
            "unremitted_premium_cents one rung above the tolerance",
        )
        assert_posture(over, "RESTRICTED")
        assert over["escrow_standing"] == "COMPLIANT", (
            f"the standing must be untouched, got {over['escrow_standing']}"
        )
        assert over["open_critical_finding_count"] == 0, (
            "no finding exists, got " f"{over['open_critical_finding_count']}"
        )
        assert over["appointment_status"] == "APPOINTED", (
            f"the appointment must be untouched, got {over['appointment_status']}"
        )
        assert over["financial_review_status"] == "ACCEPTED", (
            "the financial review must be untouched, got "
            f"{over['financial_review_status']}"
        )


class TestOptimisticConcurrencyOnTheGuardedCreates:
    """Each of the three guarded creates refuses a version it did not just read."""

    def test_a_letter_request_carrying_a_superseded_version_is_refused(self, api, env):
        """An intervening policy-file creation invalidates the observed version.

        PRD: "A `POST /closing-protection-letters` request must carry
        `expected_agency_version` matching the target agency's current `version`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_letter_request_rejects_a_stale_agency_version_returns_412
        """
        observed = agency_version(api, env.agency_id)
        create_policy_file(api, env, expected_agency_version=observed)
        fresh = agency_version(api, env.agency_id)
        assert fresh == observed + 1, (
            "the policy-file creation is the single intervening versioned write, so the "
            f"version must read {observed + 1}, got {fresh}"
        )

        stale = api.request_letter(
            request_letter_payload(
                env.agency_id,
                env.state_program_id,
                observed,
                transaction_ref="TXN-9201",
            ),
            env.principal,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_AGENCY_VERSION.value, 412)
        _rows, empty_meta = validate_paginated(
            api.list_letters(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(empty_meta, 0)

        accepted = validate_success(
            api.request_letter(
                request_letter_payload(
                    env.agency_id,
                    env.state_program_id,
                    fresh,
                    transaction_ref="TXN-9201",
                ),
                env.principal,
            ),
            201,
        )

        assert accepted["status"] == "REQUESTED", (
            f"the retried request must land on REQUESTED, got {accepted['status']}"
        )
        assert agency_version(api, env.agency_id) == fresh + 1, (
            "the accepted letter request is itself a versioned write, so the version "
            f"must read {fresh + 1}, got {agency_version(api, env.agency_id)}"
        )

    def test_a_policy_file_creation_carrying_a_superseded_version_is_refused(
        self, api, env
    ):
        """An intervening letter request invalidates the routing profile.

        PRD: "A `POST /policy-files` request must likewise carry
        `expected_agency_version` matching the agency's current `version`, and a mismatch is
        rejected with `ERR_STALE_AGENCY_VERSION` (HTTP 412), because the referral routing
        stamped onto the new file is derived from `underwriting_authority_limit_cents` at
        that version."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_policy_file_create_rejects_a_stale_agency_version_returns_412
        """
        observed = agency_version(api, env.agency_id)
        request_letter(api, env, expected_agency_version=observed)
        fresh = agency_version(api, env.agency_id)
        assert fresh == observed + 1, (
            "the letter request is the single intervening versioned write, so the version "
            f"must read {observed + 1}, got {fresh}"
        )
        payload = create_policy_file_payload(
            env.agency_id,
            env.state_program_id,
            observed,
            order_number="ORD-9211",
            closing_date="2026-07-10",
            liability_amount_cents=40_000_000,
            gross_premium_cents=33_333,
        )

        stale = api.create_policy_file(payload, env.principal)

        validate_error(stale, ApiErrorId.ERR_STALE_AGENCY_VERSION.value, 412)
        _rows, empty_meta = validate_paginated(
            api.list_policy_files(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(empty_meta, 0)

        accepted = validate_success(
            api.create_policy_file({**payload, "expected_agency_version": fresh}, env.principal),
            201,
        )

        assert accepted["issuance_status"] == "PENDING", (
            f"the retried creation must land on PENDING, got {accepted['issuance_status']}"
        )
        assert_money_equal(
            accepted["approved_liability_cents"],
            40_000_000,
            "approved_liability_cents on an unreferred file",
        )

    def test_a_statement_creation_carrying_a_superseded_version_is_refused(
        self, api, env
    ):
        """An intervening issuance invalidates the observed remittance baseline.

        PRD: "A `POST /remittance-statements` request must also carry
        `expected_agency_version` matching the agency's current `version`, and a mismatch is
        rejected with `ERR_STALE_AGENCY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_statement_create_rejects_a_stale_agency_version_returns_412
        """
        policy_file = create_policy_file(api, env)
        observed = agency_version(api, env.agency_id)

        issue_policy(api, env, policy_file["id"], policy_number="POL-9221")

        fresh = agency_version(api, env.agency_id)
        assert fresh == observed + 1, (
            "the issuance is the write the stale request had not seen, so the version "
            f"must read {observed + 1}, got {fresh}"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["unremitted_premium_cents"], 33_333, "unremitted_premium_cents"
        )

        stale = api.create_statement(
            create_statement_payload(
                env.agency_id, "2026-07-01", "2026-07-31", observed
            ),
            env.principal,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_AGENCY_VERSION.value, 412)
        _rows, empty_meta = validate_paginated(
            api.list_statements(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(empty_meta, 0)

        accepted = validate_success(
            api.create_statement(
                create_statement_payload(
                    env.agency_id, "2026-07-01", "2026-07-31", fresh
                ),
                env.principal,
            ),
            201,
        )

        assert accepted["status"] == "DRAFT", (
            f"the retried statement must open in DRAFT, got {accepted['status']}"
        )


class TestUnreportedPolicyThreshold:
    """The unreported-count gate is recomputed at every reconciliation.

    It is a live comparison rather than a latch.
    """

    def test_the_third_unreported_policy_restricts_and_reporting_it_releases(
        self, api, env
    ):
        """Three unreported policies restrict the agency; two put it back at `OPEN`.

        PRD: "The agency's `unreported_policy_count` is then mirrored from this statement,
        the agency's `oversight_posture` is recomputed — three or more unreported policies
        is one of the restrict conditions — and `Agency.version` is incremented by 1."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_triggers_third_unreported_policy_restricts_the_agency
        """
        files = []
        for index in range(4):
            policy_file = create_policy_file(
                api,
                env,
                closing_date="2026-07-20",
                liability_amount_cents=20_000_000,
                gross_premium_cents=100_000,
            )
            issue_policy(api, env, policy_file["id"], policy_number=f"POL-70{index}")
            files.append(policy_file)
        before = read_agency(api, env.agency_id)
        assert_money_equal(
            before["unremitted_premium_cents"], 400_000, "unremitted_premium_cents"
        )
        assert_posture(before, "OPEN")
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        add_line(api, env, statement["id"], files[0]["id"], 100_000)
        submit_statement(api, env, statement["id"])

        restricting = reconcile_statement(api, statement["id"])

        assert_money_equal(
            restricting["expected_gross_premium_cents"],
            400_000,
            "expected_gross_premium_cents",
        )
        assert restricting["unreported_policy_count"] == 3, (
            "three of the four July policies carry no line, got "
            f"{restricting['unreported_policy_count']}"
        )
        assert_money_equal(
            restricting["late_fee_cents"],
            30_000,
            "late_fee_cents (one tenth of 300,000 with no filing fee)",
        )
        restricted = read_agency(api, env.agency_id)
        assert restricted["unreported_policy_count"] == 3, (
            "the count is mirrored onto the agency, got "
            f"{restricted['unreported_policy_count']}"
        )
        assert_posture(restricted, "RESTRICTED")

        reopen_statement(
            api, statement["id"], reopen_reason="Two closings were omitted"
        )
        add_line(api, env, statement["id"], files[1]["id"], 100_000)
        submit_statement(api, env, statement["id"])

        releasing = reconcile_statement(api, statement["id"])

        assert releasing["unreported_policy_count"] == 2, (
            "one more reported policy leaves two unreported, got "
            f"{releasing['unreported_policy_count']}"
        )
        assert_money_equal(
            releasing["late_fee_cents"], 20_000, "late_fee_cents on the second pass"
        )
        released = read_agency(api, env.agency_id)
        assert released["unreported_policy_count"] == 2, (
            "the mirrored count must fall with the statement, got "
            f"{released['unreported_policy_count']}"
        )
        assert_posture(released, "OPEN")
        assert_remittance_status(
            validate_success(api.get_policy_file(files[0]["id"], OFFICER)), "REPORTED"
        )
        assert_remittance_status(
            validate_success(api.get_policy_file(files[2]["id"], OFFICER)), "UNREPORTED"
        )
