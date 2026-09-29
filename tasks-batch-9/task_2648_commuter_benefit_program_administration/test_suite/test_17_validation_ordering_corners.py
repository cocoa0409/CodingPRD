"""Validation ordering, boundary instants and aggregate-limit corners.

Every test here pins a single refusal or acceptance produced by the fixed
rejection ladder of the election and media-order surfaces: which allocation
halves a category permits, where the half-open ordering window actually ends,
how two categories sharing one limit group consume a single employer headroom,
how the mid-month change flag gates the counter that lives behind it, and which
of two simultaneously violated checks the ladder surfaces first.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import (
    ERR_ALLOCATION_TYPE_NOT_ALLOWED,
    ERR_BENEFIT_CATEGORY_RETIRED,
    ERR_CHANGE_LIMIT_EXCEEDED,
    ERR_EXCLUSION_LIMIT_EXCEEDED,
    ERR_MEDIA_REGION_INELIGIBLE,
    ERR_MID_MONTH_CHANGE_NOT_ALLOWED,
    ERR_ORDER_CUTOFF_PASSED,
)
from test_helpers.test_users import PROGRAM_ADMIN, make_order_desk_headers

WINDOW_CUTOFF_AT = "2026-08-20T00:00:00Z"
ONE_SECOND_BEFORE_CUTOFF = "2026-08-19T23:59:59Z"
COVERAGE_START_AT = "2026-08-01T00:00:00Z"
COVERAGE_END_AT = "2026-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Composite preconditions used by more than one test in this module.
# ---------------------------------------------------------------------------
def _posttax_only_program(api, legal_name):
    """An ACTIVE program whose only category forbids the pre-tax half."""
    return fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={"legal_name": legal_name, "program_cap_cents": 5000000},
        category_overrides={
            "category_type": "PARKING",
            "monthly_exclusion_limit_cents": 30000,
            "pretax_allowed": False,
            "posttax_allowed": True,
        },
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
    )


def _order_ready_program(api):
    """A PENDING election awaiting media plus an OPEN batch, no line filed yet."""
    built = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={"legal_name": "Cutoff Instant Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        window_overrides={
            "benefit_month": "2026-08",
            "opens_at": "2026-07-01T00:00:00Z",
            "cutoff_at": WINDOW_CUTOFF_AT,
        },
    )
    media = fixtures.make_transit_media(
        api,
        sku="AUS-CI",
        media_type="PAPER_PASS",
        region_code=constants.REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=4000,
    )
    election = fixtures.make_election(
        api,
        built["employee"]["id"],
        built["window"]["id"],
        built["category"]["id"],
        built["account"]["id"],
        pretax_amount_cents=4000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )
    batch = fixtures.make_open_batch(
        api, built["window"]["id"], constants.REGION_AUS, "desk-build"
    )
    built["media"] = media
    built["election"] = election
    built["batch"] = batch
    return built


def _shared_group_program(api):
    """Two categories in one limit group, the first already holding 20000 cents."""
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "VANPOOL", "monthly_exclusion_limit_cents": 30000},
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000},
        ],
        legal_name="Shared Group Co",
        region_code=constants.REGION_AUS,
        transit_group_limit_cents=31500,
        parking_group_limit_cents=31500,
        program_cap_cents=5000000,
        pretax_ratio_cap_pct=100,
        spill_policy="REJECT_OVERAGE",
    )
    employer = built["employer"]
    vanpool_category, transit_category = built["categories"]
    employee = fixtures.make_employee(
        api, employer["id"], PROGRAM_ADMIN, work_region_code=constants.REGION_AUS
    )
    vanpool_account = fixtures.make_benefit_account(
        api, employee["id"], vanpool_category["id"]
    )
    transit_account = fixtures.make_benefit_account(
        api, employee["id"], transit_category["id"]
    )
    window = fixtures.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        cutoff_at=WINDOW_CUTOFF_AT,
    )
    vanpool_election = fixtures.make_election(
        api,
        employee["id"],
        window["id"],
        vanpool_category["id"],
        vanpool_account["id"],
        pretax_amount_cents=20000,
        posttax_amount_cents=0,
    )
    return {
        "employer": employer,
        "vanpool_category": vanpool_category,
        "transit_category": transit_category,
        "employee": employee,
        "vanpool_account": vanpool_account,
        "transit_account": transit_account,
        "window": window,
        "vanpool_election": vanpool_election,
    }


def _mid_month_program(api):
    """Two adjacent LOCKED windows over one account: window A permits a mid-month
    change and window B forbids it, so both gates are reachable from one setup."""
    fixtures.set_clock(api, "2026-07-15T00:00:00Z")
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        legal_name="Mid Month Co",
        region_code=constants.REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
        pretax_ratio_cap_pct=100,
    )
    employer = built["employer"]
    category = built["categories"][0]
    employee = fixtures.make_employee(
        api, employer["id"], PROGRAM_ADMIN, work_region_code=constants.REGION_AUS
    )
    account = fixtures.make_benefit_account(api, employee["id"], category["id"])

    window_a = fixtures.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-07",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-01T00:00:00Z",
        mid_month_change_allowed=True,
    )
    election_a = fixtures.make_election(
        api,
        employee["id"],
        window_a["id"],
        category["id"],
        account["id"],
        pretax_amount_cents=5000,
        posttax_amount_cents=0,
    )
    validate_success(api.lock_election_window(window_a["id"], PROGRAM_ADMIN))

    window_b = fixtures.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        cutoff_at="2026-09-01T00:00:00Z",
        mid_month_change_allowed=False,
    )
    election_b = fixtures.make_election(
        api,
        employee["id"],
        window_b["id"],
        category["id"],
        account["id"],
        pretax_amount_cents=6000,
        posttax_amount_cents=0,
    )
    validate_success(api.lock_election_window(window_b["id"], PROGRAM_ADMIN))

    return {
        "employer": employer,
        "category": category,
        "employee": employee,
        "account": account,
        "window_a": window_a,
        "window_b": window_b,
        "election_a": election_a,
        "election_b": election_b,
    }


def _sfo_medium(api):
    """A catalogue product whose region is wrong for every employee below."""
    return fixtures.make_transit_media(
        api,
        sku="SFO-XR",
        media_type="PAPER_PASS",
        region_code=constants.REGION_SFO,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=4000,
    )

# ---------------------------------------------------------------------------
# The allocation halves a category permits
# ---------------------------------------------------------------------------
def test_01_pretax_request_on_a_posttax_only_category_is_refused(api):
    """A positive pre-tax half is refused when the category forbids pre-tax money.

    Nothing else about the request is wrong: the category is ACTIVE, the window
    OPEN, the account present and the amount far under every ceiling.

    PRD: "The allocation halves must be permitted by the category: a positive `pretax_amount_cents` requires the category's `pretax_allowed` to be true, and a positive `posttax_amount_cents` requires its `posttax_allowed` to be true, with `ERR_ALLOCATION_TYPE_NOT_ALLOWED` otherwise."

    Design: Corner/validations/pretax_request_against_posttax_only_category_is_rejected
    """
    built = _posttax_only_program(api, "Post Tax Only Co")
    employee, account = built["employee"], built["account"]
    assert built["category"]["pretax_allowed"] is False
    assert built["category"]["posttax_allowed"] is True
    assert built["window"]["status"] == "OPEN"

    response = api.create_election(
        factories.election_payload(
            employee["id"],
            built["window"]["id"],
            built["category"]["id"],
            account["version"],
            pretax_amount_cents=5000,
            posttax_amount_cents=0,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ERR_ALLOCATION_TYPE_NOT_ALLOWED, expected_status=422)

    elections, meta = validate_paginated(
        api.list_elections(PROGRAM_ADMIN, {"employee_id": employee["id"]})
    )
    assert elections == []
    assert meta["total_count"] == 0

    after = fixtures.read_account(api, account["id"])
    assertions.assert_unchanged(account, after, "contributed_cents")


def test_02_posttax_only_request_on_the_same_category_is_accepted(api):
    """The satisfaction side of the same clause: with the pre-tax half at zero the
    `pretax_allowed` requirement is vacuous, so the identical configuration accepts
    the create and reports a split with nothing excluded and nothing spilled.

    PRD: "The allocation halves must be permitted by the category: a positive `pretax_amount_cents` requires the category's `pretax_allowed` to be true, and a positive `posttax_amount_cents` requires its `posttax_allowed` to be true, with `ERR_ALLOCATION_TYPE_NOT_ALLOWED` otherwise."

    PRD: "A successful create runs the pre-tax exclusion split of §3.4 under its elected basis, writing `total_amount_cents`, `excluded_amount_cents`, `posttax_spill_cents` and `posttax_effective_cents` and setting `exclusion_basis` to `ELECTED_BASIS`."

    PRD: "The create also advances the resolved benefit account's `version` by 1 and recomputes both the window's `election_count` and the category's `active_election_count`."

    Design: Corner/validations/posttax_only_request_on_the_same_category_succeeds
    """
    built = _posttax_only_program(api, "Post Tax Pass Co")
    employee, account = built["employee"], built["account"]

    election = validate_success(
        api.create_election(
            factories.election_payload(
                employee["id"],
                built["window"]["id"],
                built["category"]["id"],
                account["version"],
                pretax_amount_cents=0,
                posttax_amount_cents=5000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assertions.assert_exclusion_split(
        election,
        excluded_amount_cents=0,
        posttax_spill_cents=0,
        total_amount_cents=5000,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 5000
    assertions.assert_election_axes(election, "PENDING", "NOT_REQUIRED")
    assert election["benefit_account_id"] == account["id"]
    assert election["change_count"] == 0

    after = fixtures.read_account(api, account["id"])
    assert after["version"] == account["version"] + 1
    assert after["version"] == 2


# ---------------------------------------------------------------------------
# The half-open ordering interval ends AT the cutoff instant
# ---------------------------------------------------------------------------
def test_03_media_order_at_exactly_the_window_cutoff_instant_is_refused(api):
    """With the logical clock standing on the cutoff instant itself the line create
    is already too late: the comparison is strict, so equality fails.

    PRD: "the current logical clock instant must fall strictly before the governing window's `cutoff_at`, otherwise `ERR_ORDER_CUTOFF_PASSED`"

    PRD: "the current logical clock instant must fall strictly before the window's `cutoff_at`, since the occupation interval is half-open and the cutoff instant itself is already past; at or after the cutoff the create is refused with `ERR_ORDER_CUTOFF_PASSED`"

    Design: Corner/validations/media_order_at_exactly_the_cutoff_instant_is_already_past
    """
    built = _order_ready_program(api)
    election, media, batch = built["election"], built["media"], built["batch"]
    assert built["window"]["cutoff_at"] == WINDOW_CUTOFF_AT
    assertions.assert_election_axes(election, "PENDING", "AWAITING_ORDER")

    fixtures.set_clock(api, WINDOW_CUTOFF_AT)
    response = api.create_media_order(
        factories.media_order_payload(
            election["id"],
            media["id"],
            batch["id"],
            election["version"],
            quantity=1,
            coverage_start_at=COVERAGE_START_AT,
            coverage_end_at=COVERAGE_END_AT,
        ),
        make_order_desk_headers("desk-build"),
    )
    validate_error(response, ERR_ORDER_CUTOFF_PASSED, expected_status=422)

    assertions.assert_election_axes(
        fixtures.read_election(api, election["id"]), "PENDING", "AWAITING_ORDER"
    )
    assert fixtures.read_batch(api, batch["id"])["line_count"] == 0


def test_04_media_order_one_second_before_the_cutoff_instant_is_accepted(api):
    """One second earlier the identical body is inside the half-open interval, so the
    line opens PENDING with the catalogue price snapshotted and the parent election
    moves off AWAITING_ORDER.

    PRD: "the current logical clock instant must fall strictly before the governing window's `cutoff_at`, otherwise `ERR_ORDER_CUTOFF_PASSED`"

    PRD: "A successful line create opens the row in `status` `PENDING` with `unit_price_cents_snapshot` copied from the catalogue product's current `unit_price_cents`"

    PRD: "Creating a media line for an election that was waiting therefore advances the election `AWAITING_ORDER → ORDERED`, provided `entitled_media_units` is greater than zero and at least one of the election's media orders is not `CANCELLED`."

    PRD: "Computed rollup counters are recomputed as part of the same request rather than lazily: `enrolled_employee_count` on an employer, `active_election_count` on a benefit category, `election_count` on an election window, `ledger_entry_count` on a benefit account and `line_count` on a procurement batch are all correct at the moment the response is emitted."

    Design: Corner/validations/media_order_at_exactly_the_cutoff_instant_is_already_past
    """
    built = _order_ready_program(api)
    election, media, batch = built["election"], built["media"], built["batch"]
    assert media["unit_price_cents"] == 4000

    fixtures.set_clock(api, ONE_SECOND_BEFORE_CUTOFF)
    order = validate_success(
        api.create_media_order(
            factories.media_order_payload(
                election["id"],
                media["id"],
                batch["id"],
                election["version"],
                quantity=1,
                coverage_start_at=COVERAGE_START_AT,
                coverage_end_at=COVERAGE_END_AT,
            ),
            make_order_desk_headers("desk-build"),
        ),
        expected_status=201,
    )

    assert order["status"] == "PENDING"
    assert order["unit_price_cents_snapshot"] == 4000
    assert order["order_batch_id"] == batch["id"]
    assert fixtures.read_batch(api, batch["id"])["line_count"] == 1
    assertions.assert_election_axes(
        fixtures.read_election(api, election["id"]), "PENDING", "ORDERED"
    )


# ---------------------------------------------------------------------------
# One limit group, two categories: individually legal, collectively over
# ---------------------------------------------------------------------------
def test_05_second_transit_category_over_the_shared_group_limit_is_refused(api):
    """20000 on VANPOOL and 15000 on TRANSIT_PASS each sit under the 30000 category
    cap, but both map to the TRANSIT group whose employer limit is 31500, leaving
    11500 of headroom; under REJECT_OVERAGE the 3500-cent spill is fatal.

    PRD: "The elected category's `limit_group` — `TRANSIT` for a `TRANSIT_PASS` or `VANPOOL` category, `PARKING` for a `PARKING` category — selects the employer's group limit: `transit_group_limit_cents` for the transit group, `parking_group_limit_cents` for the parking group."

    PRD: "The group headroom is then the group limit minus that prior consumption, floored at zero"

    PRD: "`excluded_amount_cents` is then the smallest of those four values: the requested `pretax_amount_cents`, the group headroom, the category cap, and the ratio cap."

    PRD: "Under `REJECT_OVERAGE`, an overage is not tolerated at all: whenever the spill would be greater than zero, the election create or amendment is refused with `ERR_EXCLUSION_LIMIT_EXCEEDED` (HTTP 422), and the employee must lower their pre-tax request until the spill would be exactly zero."

    Design: Corner/validations/two_categories_each_under_cap_together_exceed_the_shared_transit_group_limit
    """
    built = _shared_group_program(api)
    assert built["employer"]["transit_group_limit_cents"] == 31500
    assert built["employer"]["spill_policy"] == "REJECT_OVERAGE"
    assert built["vanpool_category"]["limit_group"] == "TRANSIT"
    assert built["transit_category"]["limit_group"] == "TRANSIT"
    assertions.assert_exclusion_split(
        built["vanpool_election"],
        excluded_amount_cents=20000,
        posttax_spill_cents=0,
        total_amount_cents=20000,
    )

    response = api.create_election(
        factories.election_payload(
            built["employee"]["id"],
            built["window"]["id"],
            built["transit_category"]["id"],
            built["transit_account"]["version"],
            pretax_amount_cents=15000,
            posttax_amount_cents=0,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ERR_EXCLUSION_LIMIT_EXCEEDED, expected_status=422)

    sibling = fixtures.read_election(api, built["vanpool_election"]["id"])
    assert sibling["excluded_amount_cents"] == 20000
    assertions.assert_unchanged(built["vanpool_election"], sibling)


def test_06_second_transit_category_at_exactly_the_group_headroom_is_accepted(api):
    """Lowering the same request to precisely the 11500 cents of remaining group
    headroom makes the spill exactly zero, which REJECT_OVERAGE tolerates.

    PRD: "The group headroom is then the group limit minus that prior consumption, floored at zero"

    PRD: "`excluded_amount_cents` is then the smallest of those four values: the requested `pretax_amount_cents`, the group headroom, the category cap, and the ratio cap."

    PRD: "Whatever pre-tax the employee asked for beyond that becomes the overage: `posttax_spill_cents` is the requested `pretax_amount_cents` minus `excluded_amount_cents`."

    PRD: "Under `REJECT_OVERAGE`, an overage is not tolerated at all: whenever the spill would be greater than zero, the election create or amendment is refused with `ERR_EXCLUSION_LIMIT_EXCEEDED` (HTTP 422), and the employee must lower their pre-tax request until the spill would be exactly zero."

    Design: Corner/validations/two_categories_each_under_cap_together_exceed_the_shared_transit_group_limit
    """
    built = _shared_group_program(api)

    election = validate_success(
        api.create_election(
            factories.election_payload(
                built["employee"]["id"],
                built["window"]["id"],
                built["transit_category"]["id"],
                built["transit_account"]["version"],
                pretax_amount_cents=11500,
                posttax_amount_cents=0,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assertions.assert_exclusion_split(
        election,
        excluded_amount_cents=11500,
        posttax_spill_cents=0,
        total_amount_cents=11500,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 0
    assert election["benefit_account_id"] == built["transit_account"]["id"]
    assertions.assert_election_axes(election, "PENDING", "NOT_REQUIRED")


# ---------------------------------------------------------------------------
# The mid-month flag gate runs before the single-change counter
# ---------------------------------------------------------------------------
def test_07_amendment_against_a_locked_window_that_forbids_mid_month_changes_is_refused(api):
    """Window B forbids mid-month changes, so its election's first amendment dies on
    the flag gate and never reaches the counter it would otherwise have satisfied.

    PRD: "Against a `LOCKED` window it is gated twice, and in this order: first the window's `mid_month_change_allowed` flag must be true, otherwise `ERR_MID_MONTH_CHANGE_NOT_ALLOWED`; and only if that flag gate passes is the count checked — the election's `change_count` must be strictly below the single-change allowance of one, so an election that has already absorbed one mid-month change is refused with `ERR_CHANGE_LIMIT_EXCEEDED`."

    PRD: "because check 26 precedes check 27, an amendment against a locked window that forbids mid-month changes surfaces as `ERR_MID_MONTH_CHANGE_NOT_ALLOWED` and never as `ERR_CHANGE_LIMIT_EXCEEDED`"

    Design: Corner/validations/mid_month_change_flag_gates_the_amendment_and_the_single_change_limit_follows
    """
    built = _mid_month_program(api)
    assert built["window_a"]["mid_month_change_allowed"] is True
    assert built["window_b"]["mid_month_change_allowed"] is False
    assert fixtures.read_window(api, built["window_b"]["id"])["status"] == "LOCKED"

    before = fixtures.read_election(api, built["election_b"]["id"])
    assert before["change_count"] == 0
    assertions.assert_election_axes(before, "FUNDED", "NOT_REQUIRED")

    response = api.patch_election(
        built["election_b"]["id"], {"pretax_amount_cents": 4000}, PROGRAM_ADMIN
    )
    validate_error(response, ERR_MID_MONTH_CHANGE_NOT_ALLOWED, expected_status=422)

    after = fixtures.read_election(api, built["election_b"]["id"])
    assert after["pretax_amount_cents"] == 6000
    assert after["change_count"] == 0
    assertions.assert_unchanged(
        before,
        after,
        "pretax_amount_cents",
        "change_count",
        "excluded_amount_cents",
        "total_amount_cents",
    )


def test_08_single_mid_month_change_is_allowed_and_the_second_is_refused(api):
    """Window A permits mid-month changes, so the counter behind the flag becomes
    reachable: exactly one amendment lands, moves the funded money as a signed
    delta, and the second amendment is refused on the allowance of one.

    PRD: "Against a `LOCKED` window it is gated twice, and in this order: first the window's `mid_month_change_allowed` flag must be true, otherwise `ERR_MID_MONTH_CHANGE_NOT_ALLOWED`; and only if that flag gate passes is the count checked — the election's `change_count` must be strictly below the single-change allowance of one, so an election that has already absorbed one mid-month change is refused with `ERR_CHANGE_LIMIT_EXCEEDED`."

    PRD: "Every successful amendment re-runs the exclusion split under the elected basis, increments `change_count` by 1, re-derives `fulfillment_status` from the election's media orders, and advances `Election.version` by 1."

    PRD: "the service computes the new `total_amount_cents` minus the old `total_amount_cents` and, unless that delta is exactly zero, appends one ledger entry with `entry_type` `CONTRIBUTION_ADJUSTMENT` and `amount_cents` equal to that signed delta, with `source_entity` `Election` and `source_id` the election's identifier."

    PRD: "A third, order-sensitive identity governs the log itself: each entry's `balance_after_cents` equals the running signed total of all entries for that account up to and including itself, taken in ascending `created_at` order."

    PRD: "A funded amendment also recomputes the employer's `total_pretax_committed_cents` and advances `Employer.version` by 1."

    Design: Corner/validations/mid_month_change_flag_gates_the_amendment_and_the_single_change_limit_follows
    """
    built = _mid_month_program(api)
    election_a_id = built["election_a"]["id"]

    amended = validate_success(
        api.patch_election(election_a_id, {"pretax_amount_cents": 4000}, PROGRAM_ADMIN)
    )
    assert amended["change_count"] == 1
    assertions.assert_exclusion_split(
        amended,
        excluded_amount_cents=4000,
        posttax_spill_cents=0,
        total_amount_cents=4000,
        exclusion_basis="ELECTED_BASIS",
    )
    assertions.assert_election_axes(amended, "FUNDED", "NOT_REQUIRED")

    refused = api.patch_election(
        election_a_id, {"pretax_amount_cents": 3000}, PROGRAM_ADMIN
    )
    validate_error(refused, ERR_CHANGE_LIMIT_EXCEEDED, expected_status=422)

    settled = fixtures.read_election(api, election_a_id)
    assert settled["pretax_amount_cents"] == 4000
    assert settled["change_count"] == 1
    assertions.assert_unchanged(amended, settled, "pretax_amount_cents", "change_count")

    account = fixtures.read_account(api, built["account"]["id"])
    assert account["contributed_cents"] == 10000
    assert account["available_balance_cents"] == 10000
    assert account["ledger_entry_count"] == 3
    assertions.assert_account_conservation(account)

    entries = fixtures.read_ledger(api, built["account"]["id"])
    assertions.assert_ledger_sequence(
        entries,
        [
            ("CONTRIBUTION", 5000, 5000),
            ("CONTRIBUTION", 6000, 11000),
            ("CONTRIBUTION_ADJUSTMENT", -1000, 10000),
        ],
    )
    assert entries[2]["source_entity"] == "Election"
    assert entries[2]["source_id"] == election_a_id
    assertions.assert_ledger_matches_account(account, entries)

    employer = fixtures.read_employer(api, built["employer"]["id"])
    assert employer["total_pretax_committed_cents"] == 10000
    assert employer["program_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# The retirement check resolves the row the media-eligibility check reads
# ---------------------------------------------------------------------------
def test_09_retired_category_outranks_the_ineligible_media_region(api):
    """One request violates both checks at once — a RETIRED category and a medium
    from the wrong region — and the ladder must surface the earlier one, because the
    media comparison reads the very category row the earlier check validates.

    PRD: "The service therefore evaluates checks in a single fixed ladder, returning the first failure it encounters and never masking an earlier check with a later one."

    PRD: "18. Category retirement — `ERR_BENEFIT_CATEGORY_RETIRED` (HTTP 422), on `POST /benefits/elections` and `POST /benefits/benefit-accounts`."

    PRD: "19. Media eligibility and region — `ERR_MEDIA_REGION_INELIGIBLE` (HTTP 422), on `POST /benefits/elections` and `POST /benefits/media-orders`."

    PRD: "Retiring a category moves it `ACTIVE → RETIRED`, which is terminal, and deliberately touches nothing else — existing elections continue exactly as they were, and only *new* elections and *new* benefit accounts are refused, with `ERR_BENEFIT_CATEGORY_RETIRED`."

    Design: Corner/validations/retired_category_check_runs_before_the_media_region_check_that_depends_on_it
    """
    media = _sfo_medium(api)
    assert media["region_code"] == constants.REGION_SFO

    built = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={"legal_name": "Retired Cat Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
    )
    assert built["employee"]["work_region_code"] == constants.REGION_AUS

    retired = validate_success(
        api.retire_benefit_category(built["category"]["id"], PROGRAM_ADMIN)
    )
    assert retired["status"] == "RETIRED"

    error = validate_error(
        api.create_election(
            factories.election_payload(
                built["employee"]["id"],
                built["window"]["id"],
                built["category"]["id"],
                built["account"]["version"],
                pretax_amount_cents=4000,
                posttax_amount_cents=0,
                transit_media_id=media["id"],
                media_quantity=1,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_BENEFIT_CATEGORY_RETIRED,
        expected_status=422,
    )
    assert error["error_id"] != ERR_MEDIA_REGION_INELIGIBLE


def test_10_active_category_with_the_same_wrong_region_medium_surfaces_the_region_error(api):
    """The control that proves the later check really was violated: the identical
    out-of-region medium against an ACTIVE category returns the media-region error.

    PRD: "19. Media eligibility and region — `ERR_MEDIA_REGION_INELIGIBLE` (HTTP 422), on `POST /benefits/elections` and `POST /benefits/media-orders`."

    PRD: "must be regionally and categorically eligible: the product's `eligible_category_type` must equal the elected category's `category_type` and the product's `region_code` must equal the electing employee's `work_region_code`, with `ERR_MEDIA_REGION_INELIGIBLE` otherwise."

    Design: Corner/validations/retired_category_check_runs_before_the_media_region_check_that_depends_on_it
    """
    media = _sfo_medium(api)

    built = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={"legal_name": "Active Cat Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
    )
    assert built["category"]["status"] == "ACTIVE"
    assert media["eligible_category_type"] == built["category"]["category_type"]
    assert media["region_code"] != built["employee"]["work_region_code"]

    validate_error(
        api.create_election(
            factories.election_payload(
                built["employee"]["id"],
                built["window"]["id"],
                built["category"]["id"],
                built["account"]["version"],
                pretax_amount_cents=4000,
                posttax_amount_cents=0,
                transit_media_id=media["id"],
                media_quantity=1,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_MEDIA_REGION_INELIGIBLE,
        expected_status=422,
    )
