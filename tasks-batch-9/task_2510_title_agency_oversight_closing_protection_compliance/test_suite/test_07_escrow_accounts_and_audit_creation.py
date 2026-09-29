"""Escrow trust accounts, balance snapshots, audit opening and the variance variants."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_common_fields,
    assert_contains_id,
    assert_excludes_id,
    assert_money_equal,
    assert_total_count,
    create_agency,
    create_audit,
    create_escrow_account,
    create_escrow_account_payload,
    create_escrow_audit_payload,
    ids_of,
    make_agency_principal_headers,
    post_snapshot,
    submit_audit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, OFFICER

STRICT_SNAPSHOT = {
    "book_balance_cents": 10_000_000,
    "bank_balance_cents": 10_120_000,
    "outstanding_items_cents": 100_000,
    "trial_balance_cents": 10_015_000,
    "unidentified_funds_cents": 0,
    "aged_unidentified_over_90_cents": 0,
    "snapshot_as_of": "2026-07-31",
}


class TestEscrowAccountRegistration:
    """An account is registered, read back and listed; nothing else may touch it."""

    def test_new_account_opens_with_zeroed_balances(self, api, env):
        """Only three inputs are supplied, so every balance defaults to 0.

        PRD: "A new account opens with `status` `OPEN`, every balance at 0 and
        `snapshot_as_of` null."

        Design: Corner/entities/defaults_new_escrow_account_opens_with_zeroed_balances
        """
        created = validate_success(
            api.create_escrow_account(
                create_escrow_account_payload(
                    env.agency_id, bank_name="First Trust Bank", account_ref="ESCROW-1"
                ),
                env.principal,
            ),
            201,
        )

        assert_common_fields(created, "escrow account")
        assert created["status"] == "OPEN", (
            f"a new account must open in OPEN, got {created['status']}"
        )
        assert created["snapshot_as_of"] is None, (
            f"snapshot_as_of must start null, got {created['snapshot_as_of']!r}"
        )
        for field in (
            "book_balance_cents",
            "bank_balance_cents",
            "outstanding_items_cents",
            "trial_balance_cents",
            "unidentified_funds_cents",
            "aged_unidentified_over_90_cents",
            "adjusted_bank_balance_cents",
        ):
            assert_money_equal(created[field], 0, field)
        assert created["version"] == 1, (
            f"a new account must be at version 1, got {created['version']}"
        )
        assert created["agency_id"] == env.agency_id, (
            f"the account must belong to the registering agency, got {created['agency_id']}"
        )

    def test_adjusted_bank_balance_is_derived_from_the_snapshot(self, api, env):
        """A bank balance of 10,120,000 less 100,000 outstanding stores 10,020,000.

        PRD: "Posting a snapshot derives `adjusted_bank_balance_cents` as
        `bank_balance_cents` minus `outstanding_items_cents` and persists it on the
        account."

        Design: Corner/entities/computed_fields_adjusted_bank_balance_derived_from_snapshot
        """
        account = create_escrow_account(api, env)
        assert_money_equal(
            account["adjusted_bank_balance_cents"], 0, "adjusted_bank_balance_cents"
        )

        snapshotted = post_snapshot(
            api, env, account["id"], **{**STRICT_SNAPSHOT, "unidentified_funds_cents": 25_000}
        )

        assert_money_equal(
            snapshotted["adjusted_bank_balance_cents"],
            10_020_000,
            "adjusted_bank_balance_cents",
        )
        assert snapshotted["snapshot_as_of"] == "2026-07-31", (
            f"snapshot_as_of must be persisted, got {snapshotted['snapshot_as_of']!r}"
        )
        assert_money_equal(
            snapshotted["trial_balance_cents"], 10_015_000, "trial_balance_cents"
        )
        assert_money_equal(
            snapshotted["unidentified_funds_cents"], 25_000, "unidentified_funds_cents"
        )
        assert snapshotted["status"] == "OPEN", (
            "recording a snapshot does not change the account status, got "
            f"{snapshotted['status']}"
        )

    def test_accounts_are_created_read_and_listed_by_agency(self, api, env):
        """Two accounts for one agency, read individually and filtered away from a third.

        PRD: "An escrow trust account is the agency's own record, registered by the
        `AgencyPrincipal` with the `agency_id`, the depository `bank_name` and a masked
        `account_ref`."

        Design: Corner/endpoints/standard_crud_escrow_account_create_read_and_filtered_list
        """
        other_agency = create_agency(api)
        other_account = validate_success(
            api.create_escrow_account(
                create_escrow_account_payload(
                    other_agency["id"], bank_name="Second State Bank", account_ref="ESCROW-B1"
                ),
                make_agency_principal_headers(other_agency["id"]),
            ),
            201,
        )

        first = validate_success(
            api.create_escrow_account(
                create_escrow_account_payload(
                    env.agency_id, bank_name="First Trust Bank", account_ref="ESCROW-A1"
                ),
                env.principal,
            ),
            201,
        )
        second = validate_success(
            api.create_escrow_account(
                create_escrow_account_payload(
                    env.agency_id, bank_name="First Trust Bank", account_ref="ESCROW-A2"
                ),
                env.principal,
            ),
            201,
        )

        assert first["id"] != second["id"], "the two accounts must be distinct rows"
        assert first["status"] == "OPEN" and second["status"] == "OPEN", (
            "both new accounts must be OPEN, got "
            f"{first['status']} and {second['status']}"
        )

        read_back = validate_success(api.get_escrow_account(second["id"], AUDITOR))
        assert read_back["account_ref"] == "ESCROW-A2", (
            f"the read must return ESCROW-A2, got {read_back['account_ref']!r}"
        )
        assert read_back["agency_id"] == env.agency_id, (
            f"the read row must belong to the agency, got {read_back['agency_id']}"
        )

        rows, meta = validate_paginated(
            api.list_escrow_accounts(AUDITOR, params={"agency_id": env.agency_id})
        )
        assert_total_count(meta, 2)
        assert_contains_id(rows, first["id"], "the filtered account list")
        assert_contains_id(rows, second["id"], "the filtered account list")
        assert_excludes_id(rows, other_account["id"], "the filtered account list")

        _all_rows, all_meta = validate_paginated(api.list_escrow_accounts(AUDITOR))
        assert_total_count(all_meta, 3)


class TestAuditOpening:
    """Opening an audit stamps the SoD anchor and nothing is computed yet."""

    def test_a_new_audit_starts_in_draft(self, api, escrow_env):
        """The opener's identifier is recorded and every derived figure is still empty.

        PRD: "The new audit opens in `DRAFT` with `conducted_by_user_id` set to the
        opening actor's `X-User-ID` — the SoD-1 anchor — with `risk_tier` `LOW`, with
        `open_finding_count` and `critical_finding_count` at 0, with `variance_method`,
        `submitted_at`, `closed_at` and `closed_by_user_id` null, and with
        `reconciliation_variance_cents` and `unidentified_funds_reviewed_cents` at 0."

        Design: Corner/state_machines/initial_state_new_escrow_audit_starts_in_draft
        """
        env, account = escrow_env

        created = validate_success(
            api.create_escrow_audit(
                create_escrow_audit_payload(
                    env.agency_id, account["id"], audit_type="SURPRISE"
                ),
                AUDITOR,
            ),
            201,
        )

        assert created["status"] == "DRAFT", (
            f"a new audit must open in DRAFT, got {created['status']}"
        )
        assert created["conducted_by_user_id"] == "auditor-1", (
            "conducted_by_user_id must hold the opening actor's identifier, got "
            f"{created['conducted_by_user_id']!r}"
        )
        assert created["closed_by_user_id"] is None, (
            f"closed_by_user_id must start null, got {created['closed_by_user_id']!r}"
        )
        assert created["variance_method"] is None, (
            f"variance_method must start null, got {created['variance_method']!r}"
        )
        assert_money_equal(
            created["reconciliation_variance_cents"], 0, "reconciliation_variance_cents"
        )
        assert created["risk_tier"] == "LOW", (
            f"risk_tier must default to LOW, got {created['risk_tier']}"
        )
        assert created["open_finding_count"] == 0, (
            f"open_finding_count must start at 0, got {created['open_finding_count']}"
        )
        assert created["critical_finding_count"] == 0, (
            "critical_finding_count must start at 0, got "
            f"{created['critical_finding_count']}"
        )
        assert created["submitted_at"] is None, (
            f"submitted_at must start null, got {created['submitted_at']!r}"
        )

    def test_unknown_audit_id_is_a_resource_specific_not_found(self, api):
        """A well-formed but unknown identifier is a 404, not a 400 or an empty object.

        PRD: "Path parameters are resolved strictly left to right, and each segment
        produces its own not-found error before anything to its right is examined"

        Design: Corner/entities/not_found_get_escrow_audit_with_unknown_uuid_returns_404
        """
        response = api.get_escrow_audit(NON_EXISTENT_UUID, AUDITOR)

        validate_error(response, ApiErrorId.ERR_ESCROW_AUDIT_NOT_FOUND.value, 404)
        body = response.json()
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            f"the error must carry a non-empty message, got {body['data']['message']!r}"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "the error envelope must still carry an api_request_id, got "
            f"{body['meta']['api_request_id']!r}"
        )

    def test_scheduled_audits_need_exactly_ninety_days_of_spacing(self, api, escrow_env):
        """89 days is refused and 90 days is accepted on the same account.

        PRD: "Scheduled audits must be spaced: the absolute gap between the new
        `as_of_date` and the `as_of_date` of every existing `SCHEDULED` audit of the same
        account must be at least ninety days, with a gap of exactly ninety days accepted,
        and a tighter gap refused with `ERR_AUDIT_SPACING_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/scheduled_audit_ninety_day_spacing_boundary_and_surprise_capacity
        """
        env, account = escrow_env
        create_audit(api, env, account["id"], as_of_date="2026-05-03")

        too_close = api.create_escrow_audit(
            create_escrow_audit_payload(
                env.agency_id,
                account["id"],
                audit_type="SCHEDULED",
                as_of_date="2026-07-31",
            ),
            AUDITOR,
        )
        validate_error(too_close, ApiErrorId.ERR_AUDIT_SPACING_VIOLATION.value, 409)

        on_the_boundary = validate_success(
            api.create_escrow_audit(
                create_escrow_audit_payload(
                    env.agency_id,
                    account["id"],
                    audit_type="SCHEDULED",
                    as_of_date="2026-08-01",
                ),
                AUDITOR,
            ),
            201,
        )

        assert on_the_boundary["audit_type"] == "SCHEDULED", (
            f"the accepted audit must be SCHEDULED, got {on_the_boundary['audit_type']}"
        )
        assert on_the_boundary["as_of_date"] == "2026-08-01", (
            "2026-05-03 to 2026-08-01 is exactly 90 days, got "
            f"{on_the_boundary['as_of_date']}"
        )
        _rows, meta = validate_paginated(
            api.list_escrow_audits(
                AUDITOR, params={"escrow_account_id": account["id"]}
            )
        )
        assert_total_count(meta, 2)

    def test_surprise_audits_ignore_spacing_but_are_capped_at_one(self, api, escrow_env):
        """A surprise audit shares the scheduled date, and a second one is refused.

        PRD: "Surprise audits are instead exclusive: no other `SURPRISE` audit of the
        same account may be sitting in a non-terminal `status` — that is, in `DRAFT`,
        `SUBMITTED`, `UNDER_REVIEW` or `REMEDIATION_REQUIRED` — else
        `ERR_SURPRISE_AUDIT_IN_PROGRESS` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/scheduled_audit_ninety_day_spacing_boundary_and_surprise_capacity
        """
        env, account = escrow_env
        create_audit(api, env, account["id"], as_of_date="2026-05-03")
        scheduled = create_audit(api, env, account["id"], as_of_date="2026-08-01")

        surprise = validate_success(
            api.create_escrow_audit(
                create_escrow_audit_payload(
                    env.agency_id,
                    account["id"],
                    audit_type="SURPRISE",
                    as_of_date="2026-08-01",
                ),
                AUDITOR,
            ),
            201,
        )
        assert surprise["as_of_date"] == scheduled["as_of_date"], (
            "the surprise audit shares the scheduled audit's as_of_date, got "
            f"{surprise['as_of_date']} against {scheduled['as_of_date']}"
        )
        assert surprise["status"] == "DRAFT", (
            f"the surprise audit sits in DRAFT, got {surprise['status']}"
        )

        second_surprise = api.create_escrow_audit(
            create_escrow_audit_payload(
                env.agency_id,
                account["id"],
                audit_type="SURPRISE",
                as_of_date="2026-08-01",
            ),
            AUDITOR,
        )

        validate_error(
            second_surprise, ApiErrorId.ERR_SURPRISE_AUDIT_IN_PROGRESS.value, 409
        )
        rows, meta = validate_paginated(
            api.list_escrow_audits(
                AUDITOR, params={"escrow_account_id": account["id"]}
            )
        )
        assert_total_count(meta, 3)
        assert surprise["id"] in ids_of(rows), (
            f"the accepted surprise audit must be listed, got {ids_of(rows)}"
        )


class TestVarianceVariants:
    """The same balances yield two different variances, chosen by `audit_type`."""

    def test_surprise_audit_reports_the_largest_of_three_legs(self, api, env):
        """Byte-identical balances give 20,000 under the strict three-way variant.

        PRD: "A `SURPRISE` audit uses `STRICT_THREE_WAY`:
        `reconciliation_variance_cents` is the largest of three absolute differences —
        the adjusted bank balance against the book balance, the adjusted bank balance
        against the trial balance, and the book balance against the trial balance — so a
        book-to-trial break is caught even when the bank leg happens to agree with the
        trial balance."

        Design: Difficulty/dual_variant_calc/escrow_variance_strict_three_way_versus_bank_to_trial
        """
        first_account = create_escrow_account(api, env)
        second_account = create_escrow_account(api, env)
        for account in (first_account, second_account):
            snapshot = post_snapshot(api, env, account["id"], **STRICT_SNAPSHOT)
            assert_money_equal(
                snapshot["adjusted_bank_balance_cents"],
                10_020_000,
                "adjusted_bank_balance_cents",
            )
        surprise = create_audit(
            api, env, first_account["id"], audit_type="SURPRISE"
        )
        create_audit(api, env, second_account["id"], audit_type="SCHEDULED")

        submitted = submit_audit(api, surprise["id"])

        assert submitted["variance_method"] == "STRICT_THREE_WAY", (
            "a SURPRISE audit persists the strict variant name, got "
            f"{submitted['variance_method']!r}"
        )
        assert_money_equal(
            submitted["reconciliation_variance_cents"],
            20_000,
            "reconciliation_variance_cents under STRICT_THREE_WAY",
        )
        assert submitted["open_finding_count"] == 0, (
            "20,000 is inside the 100,000 tolerance, so no finding is raised, got "
            f"{submitted['open_finding_count']}"
        )
        _rows, meta = validate_paginated(
            api.list_findings(surprise["id"], AUDITOR)
        )
        assert_total_count(meta, 0)

    def test_scheduled_audit_reports_only_the_bank_to_trial_leg(self, api, env):
        """The same balances give 5,000, and the 15,000 book-to-trial break goes unseen.

        PRD: "A `SCHEDULED` audit uses `BANK_TO_TRIAL`:
        `reconciliation_variance_cents` is the single absolute difference between the
        adjusted bank balance and the trial balance, and a book-to-trial break invisible
        in that one pair goes unreported."

        Design: Difficulty/dual_variant_calc/escrow_variance_strict_three_way_versus_bank_to_trial
        """
        first_account = create_escrow_account(api, env)
        second_account = create_escrow_account(api, env)
        for account in (first_account, second_account):
            post_snapshot(api, env, account["id"], **STRICT_SNAPSHOT)
        surprise = create_audit(api, env, first_account["id"], audit_type="SURPRISE")
        scheduled = create_audit(api, env, second_account["id"], audit_type="SCHEDULED")

        strict = submit_audit(api, surprise["id"])
        bank_to_trial = submit_audit(api, scheduled["id"])

        assert bank_to_trial["variance_method"] == "BANK_TO_TRIAL", (
            "a SCHEDULED audit persists the bank-to-trial variant name, got "
            f"{bank_to_trial['variance_method']!r}"
        )
        assert_money_equal(
            bank_to_trial["reconciliation_variance_cents"],
            5_000,
            "reconciliation_variance_cents under BANK_TO_TRIAL",
        )
        assert (
            bank_to_trial["reconciliation_variance_cents"]
            < strict["reconciliation_variance_cents"]
        ), (
            "the scheduled variant must report less than the strict variant on identical "
            f"balances, got {bank_to_trial['reconciliation_variance_cents']} against "
            f"{strict['reconciliation_variance_cents']}"
        )
        assert bank_to_trial["open_finding_count"] == 0, (
            "5,000 is inside the 100,000 tolerance, so no finding is raised, got "
            f"{bank_to_trial['open_finding_count']}"
        )
        _rows, meta = validate_paginated(
            api.list_findings(scheduled["id"], AUDITOR)
        )
        assert_total_count(meta, 0)
