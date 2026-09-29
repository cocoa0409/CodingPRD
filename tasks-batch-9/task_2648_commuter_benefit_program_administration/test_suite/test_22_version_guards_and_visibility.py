"""Concurrency-token guards, category allocation permissions and derived-field visibility.

Two creates in this service carry an optimistic-concurrency token naming the
version the client last observed on the row the create is about to displace, and
a stale token is refused before anything is written.  The same module covers the
category flags that decide which halves of an allocation are accepted, and the
promise that a rollup or cascade-derived value is already correct in the very
response that caused it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_ALLOCATION_TYPE_NOT_ALLOWED,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_STALE_ELECTION_VERSION,
)
from test_helpers.assertions import (
    assert_account_conservation,
    assert_election_axes,
    assert_exclusion_split,
    assert_ledger_matches_account,
    assert_ledger_sequence,
)
from test_helpers.constants import REGION_AUS
from test_helpers.test_users import PROGRAM_ADMIN, make_order_desk_headers


# =============================================================================
# The election create's account-version token.
# =============================================================================
def test_01_replaying_a_consumed_account_version_on_an_election_create_is_refused(api):
    """PRD §2.11: "Creating an election requires a non-optional `expected_account_version`
    field in the request body, carrying the `version` the client last observed on the
    `BenefitAccount` resolved from the election's `employee_id` and `benefit_category_id`."
    PRD §2.11: "If that value does not equal the account's current `version`, the create is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD §3.3: "The create also advances the resolved benefit account's `version` by 1 and
    recomputes both the window's `election_count` and the category's
    `active_election_count`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_account_version_on_election_create_is_rejected
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    stale_version = fixtures.current_account_version(api, program["account"]["id"])

    first = validate_success(
        api.create_election(
            f.election_payload(
                program["employee"]["id"],
                program["window"]["id"],
                program["category"]["id"],
                stale_version,
                pretax_amount_cents=5000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert fixtures.current_account_version(api, program["account"]["id"]) == (
        stale_version + 1
    ), "the accepted create consumed the version the retry is about to replay"

    validate_error(
        api.create_election(
            f.election_payload(
                program["employee"]["id"],
                program["window"]["id"],
                program["category"]["id"],
                stale_version,
                pretax_amount_cents=7000,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_STALE_ACCOUNT_VERSION,
    )

    account = fixtures.read_account(api, program["account"]["id"])
    assert account["version"] == stale_version + 1, "the refused create wrote nothing"
    rows, meta = validate_paginated(api.list_elections(PROGRAM_ADMIN))
    assert meta["total_count"] == 1, "the refused create must not have persisted a row"
    assert rows[0]["id"] == first["id"]
    assert rows[0]["funding_status"] == "PENDING"
    assert rows[0]["superseded_election_id"] is None


def test_02_refiling_at_the_observed_account_version_supersedes_the_prior_election(api):
    """PRD §2.11: "If that value does not equal the account's current `version`, the create
    is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD §3.3: "When a prior election exists for that exact triple whose `funding_status` is
    `PENDING` or `HELD`, the create sets the new row's `superseded_election_id` to the prior
    election's identifier and drives the prior election down: the prior `funding_status`
    becomes `CANCELLED`, its `excluded_amount_cents`, `posttax_spill_cents`,
    `posttax_effective_cents` and `total_amount_cents` are all zeroed, its
    `fulfillment_status` becomes `CANCELLED`, every media order of the prior election whose
    `status` is `PENDING` or `SUBMITTED` is moved to `CANCELLED`, and the prior
    `Election.version` advances by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_account_version_on_election_create_is_rejected
    """
    program = fixtures.make_program_with_participant(api, region_code=REGION_AUS)
    first_version = fixtures.current_account_version(api, program["account"]["id"])

    first = validate_success(
        api.create_election(
            f.election_payload(
                program["employee"]["id"],
                program["window"]["id"],
                program["category"]["id"],
                first_version,
                pretax_amount_cents=5000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_election(
            f.election_payload(
                program["employee"]["id"],
                program["window"]["id"],
                program["category"]["id"],
                first_version,
                pretax_amount_cents=7000,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_STALE_ACCOUNT_VERSION,
    )

    refreshed_version = fixtures.current_account_version(api, program["account"]["id"])
    second = validate_success(
        api.create_election(
            f.election_payload(
                program["employee"]["id"],
                program["window"]["id"],
                program["category"]["id"],
                refreshed_version,
                pretax_amount_cents=7000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert second["superseded_election_id"] == first["id"]
    assert_election_axes(second, "PENDING", "NOT_REQUIRED")
    assert_exclusion_split(
        second,
        excluded_amount_cents=7000,
        posttax_spill_cents=0,
        total_amount_cents=7000,
        exclusion_basis="ELECTED_BASIS",
    )

    displaced = fixtures.read_election(api, first["id"])
    assert_election_axes(displaced, "CANCELLED", "CANCELLED")
    assert displaced["excluded_amount_cents"] == 0
    assert displaced["posttax_spill_cents"] == 0
    assert displaced["posttax_effective_cents"] == 0
    assert displaced["total_amount_cents"] == 0
    assert displaced["version"] == first["version"] + 1

    account = fixtures.read_account(api, program["account"]["id"])
    assert account["version"] == refreshed_version + 1, (
        "only the two accepted creates advanced the account version"
    )


# =============================================================================
# The media-order create's election-version token.
# =============================================================================
def test_03_replaying_a_consumed_election_version_on_a_media_order_create_is_refused(api):
    """PRD §2.11: "Creating a media order requires a non-optional
    `expected_election_version` field in the request body, carrying the `version` the client
    last observed on the `Election` named by `election_id`."
    PRD §2.11: "If that value does not equal the election's current `version`, the create is
    rejected with `ERR_STALE_ELECTION_VERSION` (HTTP 412)."
    PRD §3.5: "The create then re-derives the parent election's `fulfillment_status` and
    advances `Election.version` by 1 — which is exactly why the create carries
    `expected_election_version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_election_version_on_media_order_create_is_rejected
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=6000,
        unit_price_cents=6000,
        stop_after="ordered",
    )
    stale_version = chain["election"]["version"]
    assert fixtures.current_election_version(api, chain["election"]["id"]) == (
        stale_version + 1
    ), "the accepted line create consumed the version the retry is about to replay"

    validate_error(
        api.create_media_order(
            f.media_order_payload(
                chain["election"]["id"],
                chain["media"]["id"],
                chain["batch"]["id"],
                stale_version,
                quantity=1,
            ),
            make_order_desk_headers("desk-retry"),
        ),
        ERR_STALE_ELECTION_VERSION,
    )

    rows, meta = validate_paginated(
        api.list_media_orders(
            make_order_desk_headers("desk-audit"),
            {"election_id": chain["election"]["id"]},
        )
    )
    assert meta["total_count"] == 1, "the refused create must not have persisted a line"
    assert rows[0]["id"] == chain["order"]["id"]
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["superseded_media_order_id"] is None
    assert fixtures.read_batch(api, chain["batch"]["id"])["status"] == "OPEN"


def test_04_refiling_at_the_observed_election_version_supersedes_the_pending_line(api):
    """PRD §2.11: "If that value does not equal the election's current `version`, the create
    is rejected with `ERR_STALE_ELECTION_VERSION` (HTTP 412)."
    PRD §3.5: "Like elections, media lines supersede rather than stack: when a `PENDING`
    line already exists for the same `election_id` and `transit_media_id` pair, that older
    line is moved to `CANCELLED`, the new row's `superseded_media_order_id` is set to the
    older line's identifier, and `MediaOrder.version` advances by 1 on the cancelled row."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_election_version_on_media_order_create_is_rejected
    """
    chain = fixtures.make_procurement_chain(
        api,
        region_code=REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=6000,
        unit_price_cents=6000,
        stop_after="ordered",
    )
    stale_version = chain["election"]["version"]

    validate_error(
        api.create_media_order(
            f.media_order_payload(
                chain["election"]["id"],
                chain["media"]["id"],
                chain["batch"]["id"],
                stale_version,
                quantity=1,
            ),
            make_order_desk_headers("desk-retry"),
        ),
        ERR_STALE_ELECTION_VERSION,
    )

    refreshed_version = fixtures.current_election_version(api, chain["election"]["id"])
    replacement = validate_success(
        api.create_media_order(
            f.media_order_payload(
                chain["election"]["id"],
                chain["media"]["id"],
                chain["batch"]["id"],
                refreshed_version,
                quantity=1,
            ),
            make_order_desk_headers("desk-retry"),
        ),
        expected_status=201,
    )
    assert replacement["status"] == "PENDING"
    assert replacement["superseded_media_order_id"] == chain["order"]["id"]
    assert replacement["unit_price_cents_snapshot"] == 6000

    displaced = fixtures.read_media_order(api, chain["order"]["id"])
    assert displaced["status"] == "CANCELLED"
    assert displaced["version"] == chain["order"]["version"] + 1
    assert fixtures.current_election_version(api, chain["election"]["id"]) == (
        refreshed_version + 1
    ), "only the two accepted line creates advanced the election version"


# =============================================================================
# Which halves of an allocation a category will accept.
# =============================================================================
def _program_with_pretax_only_and_defaulted_categories(api):
    """One employer carrying a pre-tax-only category beside a defaulted one.

    The transit category is declared with `posttax_allowed` false; the parking
    category omits both flags and takes their documented defaults.  The single
    employee holds one benefit account per category.
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {
                "category_type": "TRANSIT_PASS",
                "monthly_exclusion_limit_cents": 30000,
                "pretax_allowed": True,
                "posttax_allowed": False,
            },
            {"category_type": "PARKING", "monthly_exclusion_limit_cents": 30000},
        ],
        legal_name="Allocation Flags Co",
        region_code=REGION_AUS,
    )
    employer = built["employer"]
    pretax_only, defaulted = built["categories"][0], built["categories"][1]
    employee = fixtures.make_employee(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        external_ref="AUS-FLAG-1",
        work_region_code=REGION_AUS,
    )
    return {
        "employer": employer,
        "pretax_only": pretax_only,
        "defaulted": defaulted,
        "employee": employee,
        "pretax_only_account": fixtures.make_benefit_account(
            api, employee["id"], pretax_only["id"], PROGRAM_ADMIN
        ),
        "defaulted_account": fixtures.make_benefit_account(
            api, employee["id"], defaulted["id"], PROGRAM_ADMIN
        ),
        "window": fixtures.make_open_window(api, employer["id"], PROGRAM_ADMIN),
    }


def test_05_a_posttax_half_against_a_pretax_only_category_is_refused(api):
    """PRD §3.3: "The allocation halves must be permitted by the category: a positive
    `pretax_amount_cents` requires the category's `pretax_allowed` to be true, and a
    positive `posttax_amount_cents` requires its `posttax_allowed` to be true, with
    `ERR_ALLOCATION_TYPE_NOT_ALLOWED` otherwise."
    PRD §3.1: "Two booleans control which halves of an allocation the category will accept:
    `pretax_allowed` and `posttax_allowed`, both defaulting to true."

    Design: Corner/cross_cutting_complexity_layers/pretax_only_category_flag_blocks_posttax_while_the_default_allows_it
    """
    setup = _program_with_pretax_only_and_defaulted_categories(api)
    assert setup["pretax_only"]["pretax_allowed"] is True
    assert setup["pretax_only"]["posttax_allowed"] is False
    assert setup["defaulted"]["pretax_allowed"] is True
    assert setup["defaulted"]["posttax_allowed"] is True

    account_version = fixtures.current_account_version(
        api, setup["pretax_only_account"]["id"]
    )
    validate_error(
        api.create_election(
            f.election_payload(
                setup["employee"]["id"],
                setup["window"]["id"],
                setup["pretax_only"]["id"],
                account_version,
                pretax_amount_cents=4000,
                posttax_amount_cents=1000,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_ALLOCATION_TYPE_NOT_ALLOWED,
    )

    _rows, meta = validate_paginated(api.list_elections(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "the refused create must not have persisted a row"
    assert (
        fixtures.current_account_version(api, setup["pretax_only_account"]["id"])
        == account_version
    ), "the refused create wrote nothing"


def test_06_the_same_posttax_half_is_accepted_by_the_defaulted_category(api):
    """PRD §3.1: "Two booleans control which halves of an allocation the category will
    accept: `pretax_allowed` and `posttax_allowed`, both defaulting to true."
    PRD §3.4: "Under `SPILL_TO_POSTTAX` the overage is simply reclassified, and
    `posttax_effective_cents` becomes the requested `posttax_amount_cents` plus
    `posttax_spill_cents`, so the employee's total deduction is unchanged and only its tax
    treatment shifts."

    Design: Corner/cross_cutting_complexity_layers/pretax_only_category_flag_blocks_posttax_while_the_default_allows_it
    """
    setup = _program_with_pretax_only_and_defaulted_categories(api)
    account_version = fixtures.current_account_version(
        api, setup["defaulted_account"]["id"]
    )

    election = validate_success(
        api.create_election(
            f.election_payload(
                setup["employee"]["id"],
                setup["window"]["id"],
                setup["defaulted"]["id"],
                account_version,
                pretax_amount_cents=4000,
                posttax_amount_cents=1000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert election["benefit_account_id"] == setup["defaulted_account"]["id"]
    assert_exclusion_split(
        election,
        excluded_amount_cents=4000,
        posttax_spill_cents=0,
        total_amount_cents=5000,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 1000
    assert_election_axes(election, "PENDING", "NOT_REQUIRED")


def test_07_a_pure_pretax_election_is_accepted_by_the_pretax_only_category(api):
    """PRD §3.3: "The allocation halves must be permitted by the category: a positive
    `pretax_amount_cents` requires the category's `pretax_allowed` to be true, and a
    positive `posttax_amount_cents` requires its `posttax_allowed` to be true, with
    `ERR_ALLOCATION_TYPE_NOT_ALLOWED` otherwise."
    PRD §3.4: "`excluded_amount_cents` is then the smallest of those four values: the
    requested `pretax_amount_cents`, the group headroom, the category cap, and the ratio
    cap."

    Design: Corner/cross_cutting_complexity_layers/pretax_only_category_flag_blocks_posttax_while_the_default_allows_it
    """
    setup = _program_with_pretax_only_and_defaulted_categories(api)
    account_version = fixtures.current_account_version(
        api, setup["pretax_only_account"]["id"]
    )

    election = validate_success(
        api.create_election(
            f.election_payload(
                setup["employee"]["id"],
                setup["window"]["id"],
                setup["pretax_only"]["id"],
                account_version,
                pretax_amount_cents=4000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert election["benefit_account_id"] == setup["pretax_only_account"]["id"]
    assert_exclusion_split(
        election,
        excluded_amount_cents=4000,
        posttax_spill_cents=0,
        total_amount_cents=4000,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 0


# =============================================================================
# Derived values are already correct in the response that caused them.
# =============================================================================
def test_08_an_election_create_returns_its_own_split_and_the_rollups_it_moved(api):
    """PRD §2.12: "Computed rollup counters are recomputed as part of the same request
    rather than lazily: `enrolled_employee_count` on an employer, `active_election_count` on
    a benefit category, `election_count` on an election window, `ledger_entry_count` on a
    benefit account and `line_count` on a procurement batch are all correct at the moment
    the response is emitted."
    PRD §3.3: "A successful create runs the pre-tax exclusion split of §3.4 under its
    elected basis, writing `total_amount_cents`, `excluded_amount_cents`,
    `posttax_spill_cents` and `posttax_effective_cents` and setting `exclusion_basis` to
    `ELECTED_BASIS`."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    program = fixtures.make_program_with_participant(
        api,
        region_code=REGION_AUS,
        account_overrides={"opening_rollover_cents": 2000},
    )
    account_version = fixtures.current_account_version(api, program["account"]["id"])

    election = validate_success(
        api.create_election(
            f.election_payload(
                program["employee"]["id"],
                program["window"]["id"],
                program["category"]["id"],
                account_version,
                pretax_amount_cents=5000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert_exclusion_split(
        election,
        excluded_amount_cents=5000,
        posttax_spill_cents=0,
        total_amount_cents=5000,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 0
    assert_election_axes(election, "PENDING", "NOT_REQUIRED")

    window = fixtures.read_window(api, program["window"]["id"])
    assert window["election_count"] == 1
    category = validate_success(
        api.get_benefit_category(program["category"]["id"], PROGRAM_ADMIN)
    )
    assert category["active_election_count"] == 1
    account = fixtures.read_account(api, program["account"]["id"])
    assert account["version"] == account_version + 1
    assert account["contributed_cents"] == 0, "no money moves until the window locks"
    assert account["available_balance_cents"] == 2000
    assert_account_conservation(account)


def test_09_the_lock_response_carries_the_state_and_counter_it_recomputed(api):
    """PRD §3.2: "Structurally, it advances the window `OPEN → LOCKED`, stamps `locked_at`
    with the current logical clock instant, recomputes `election_count`, and then sets off a
    chain that re-prices and funds every pending election in the window, credits each
    election's benefit account, and finally re-tests the employer's aggregate commitment
    against its program cap."
    PRD §3.4: "One ledger entry is appended to that election's benefit account with
    `entry_type` `CONTRIBUTION`, a positive `amount_cents` equal to the election's
    `total_amount_cents`, `source_entity` `Election` and `source_id` the election's
    identifier; the account's `contributed_cents` increases by that same
    `total_amount_cents`, `available_balance_cents` is recomputed against the conservation
    identities, `ledger_entry_count` is incremented, and `BenefitAccount.version` advances
    by 1."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
    """
    program = fixtures.make_program_with_participant(
        api,
        region_code=REGION_AUS,
        account_overrides={"opening_rollover_cents": 2000},
    )
    election = fixtures.make_election(
        api,
        program["employee"]["id"],
        program["window"]["id"],
        program["category"]["id"],
        program["account"]["id"],
        pretax_amount_cents=5000,
    )

    locked = validate_success(
        api.lock_election_window(program["window"]["id"], PROGRAM_ADMIN)
    )
    assert locked["status"] == "LOCKED"
    assert locked["locked_at"] is not None
    assert locked["election_count"] == 1, (
        "the counter the lock recomputed is already correct in the lock response"
    )
    assert locked["version"] == program["window"]["version"] + 1

    funded = fixtures.read_election(api, election["id"])
    assert_election_axes(funded, "FUNDED", "NOT_REQUIRED")
    assert_exclusion_split(
        funded,
        excluded_amount_cents=5000,
        posttax_spill_cents=0,
        total_amount_cents=5000,
        exclusion_basis="FUNDED_BASIS",
    )

    account = fixtures.read_account(api, program["account"]["id"])
    assert account["contributed_cents"] == 5000
    assert account["spent_cents"] == 0
    assert account["available_balance_cents"] == 7000
    assert account["ledger_entry_count"] == 2
    assert_account_conservation(account)

    entries = fixtures.read_ledger(api, program["account"]["id"])
    assert_ledger_sequence(entries, [("ROLLOVER_IN", 2000, 2000), ("CONTRIBUTION", 5000, 7000)])
    assert_ledger_matches_account(account, entries)
    contribution = entries[1]
    assert contribution["source_entity"] == "Election"
    assert contribution["source_id"] == election["id"]

    employer = fixtures.read_employer(api, program["employer"]["id"])
    assert employer["total_pretax_committed_cents"] == 5000
    assert employer["program_status"] == "ACTIVE"
