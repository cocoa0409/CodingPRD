"""Initial postures and refused re-transitions on the setup side of the program.

The concern of this module is the state machinery that surrounds an election
before any media moves: the two independent axes an election is born with, the
terminal retirement of a benefit category, the once-only publication of an
election window, the refusal to seal a procurement batch that carries no lines,
and the roster rollup that employer activation is required to recompute.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import PROGRAM_ADMIN, constants, factories, fixtures
from test_helpers import make_order_desk_headers
from test_helpers.api_errors import (
    ERR_ALREADY_TERMINAL,
    ERR_EMPTY_ORDER_BATCH,
    ERR_INVALID_STATE_TRANSITION,
)


def test_01_election_filed_without_media_opens_pending_and_not_required(api):
    """PRD §3.3: "The new row opens with `funding_status` `PENDING` and `change_count` at zero."
    PRD §3.3: "Its `fulfillment_status` is derived immediately: an election created with `media_quantity` of zero, or with the field omitted altogether, opens in `NOT_REQUIRED`, because no media will ever be needed for it; an election with a positive `media_quantity` opens in `AWAITING_ORDER`."
    PRD §3.3: "A successful create runs the pre-tax exclusion split of §3.4 under its elected basis, writing `total_amount_cents`, `excluded_amount_cents`, `posttax_spill_cents` and `posttax_effective_cents` and setting `exclusion_basis` to `ELECTED_BASIS`."

    Design: Corner/state_machines/election_created_without_media_starts_pending_and_not_required
    """
    base = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    account_version = fixtures.current_account_version(api, base["account"]["id"])

    created = validate_success(
        api.create_election(
            factories.election_payload(
                base["employee"]["id"],
                base["window"]["id"],
                base["category"]["id"],
                account_version,
                pretax_amount_cents=5000,
                posttax_amount_cents=0,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert created["funding_status"] == "PENDING", created["funding_status"]
    assert created["fulfillment_status"] == "NOT_REQUIRED", created["fulfillment_status"]
    assert created["entitled_media_units"] == 0, created["entitled_media_units"]
    assert created["exclusion_basis"] == "ELECTED_BASIS", created["exclusion_basis"]
    assert created["excluded_amount_cents"] == 5000, created["excluded_amount_cents"]
    assert created["posttax_spill_cents"] == 0, created["posttax_spill_cents"]
    assert created["total_amount_cents"] == 5000, created["total_amount_cents"]
    assert created["change_count"] == 0, created["change_count"]
    assert created["version"] == 1, created["version"]
    assert created["benefit_account_id"] == base["account"]["id"], (
        "the create must resolve the account of the employee and category pair"
    )

    reread = fixtures.read_election(api, created["id"])
    assert reread["funding_status"] == "PENDING"
    assert reread["fulfillment_status"] == "NOT_REQUIRED"


def test_02_zero_media_quantity_starts_not_required_while_positive_starts_awaiting_order(api):
    """PRD §3.3: "an election created with `media_quantity` of zero, or with the field omitted altogether, opens in `NOT_REQUIRED`, because no media will ever be needed for it; an election with a positive `media_quantity` opens in `AWAITING_ORDER`."

    Design: Corner/state_machines/election_created_without_media_starts_pending_and_not_required
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        region_code=constants.REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    window = fixtures.make_open_window(api, employer["id"], PROGRAM_ADMIN)

    zero_side = fixtures.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        external_ref="AUS-IS-ZERO",
        work_region_code=constants.REGION_AUS,
    )
    positive_side = fixtures.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        external_ref="AUS-IS-POS",
        work_region_code=constants.REGION_AUS,
    )

    zero_election = validate_success(
        api.create_election(
            factories.election_payload(
                zero_side["employee"]["id"],
                window["id"],
                category["id"],
                fixtures.current_account_version(api, zero_side["account"]["id"]),
                pretax_amount_cents=5000,
                posttax_amount_cents=0,
                media_quantity=0,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    positive_election = validate_success(
        api.create_election(
            factories.election_payload(
                positive_side["employee"]["id"],
                window["id"],
                category["id"],
                fixtures.current_account_version(api, positive_side["account"]["id"]),
                pretax_amount_cents=5000,
                posttax_amount_cents=0,
                media_quantity=2,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert zero_election["entitled_media_units"] == 0
    assert zero_election["fulfillment_status"] == "NOT_REQUIRED", (
        "an explicit media_quantity of zero opens the fulfillment axis in NOT_REQUIRED"
    )
    assert zero_election["funding_status"] == "PENDING"

    assert positive_election["entitled_media_units"] == 2
    assert positive_election["fulfillment_status"] == "AWAITING_ORDER", (
        "a positive media_quantity opens the fulfillment axis in AWAITING_ORDER"
    )
    assert positive_election["funding_status"] == "PENDING"


def test_03_retiring_a_category_moves_it_to_retired_and_touches_nothing_else(api):
    """PRD §3.1: "Retiring a category moves it `ACTIVE → RETIRED`, which is terminal, and deliberately touches nothing else — existing elections continue exactly as they were, and only *new* elections and *new* benefit accounts are refused, with `ERR_BENEFIT_CATEGORY_RETIRED`."
    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional-second digits refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/benefit_category_retire_moves_active_to_retired
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000},
            {"category_type": "PARKING", "monthly_exclusion_limit_cents": 30000},
        ],
        region_code=constants.REGION_CHI,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
    )
    employer = built["employer"]
    transit_category, parking_category = built["categories"]
    assert parking_category["status"] == "ACTIVE"
    assert parking_category["version"] == 1

    retired = validate_success(
        api.retire_benefit_category(parking_category["id"], PROGRAM_ADMIN)
    )

    assert retired["status"] == "RETIRED", retired["status"]
    assert retired["version"] == 2, (
        f"one mutation must advance version 1 -> 2, got {retired['version']}"
    )

    untouched = validate_success(
        api.get_benefit_category(transit_category["id"], PROGRAM_ADMIN)
    )
    assert untouched["status"] == "ACTIVE", "the sibling category must be left alone"
    assert untouched["version"] == 1, "the sibling category must not be mutated"

    employer_after = fixtures.read_employer(api, employer["id"])
    assert employer_after["program_status"] == "ACTIVE", (
        "retiring one category must not unwind the employer program"
    )


def test_04_retiring_an_already_retired_category_is_refused_and_writes_nothing(api):
    """PRD §2.7: "Terminality: the target row must not already sit in one of its entity's terminal states, otherwise `ERR_ALREADY_TERMINAL` (HTTP 409). Applies to every action endpoint on Employer, BenefitCategory, Employee, TransitMedia, ElectionWindow, Election, OrderBatch, MediaOrder, SubstantiationClaim and PayrollFile."
    PRD §3.1: "Retiring a category moves it `ACTIVE → RETIRED`, which is terminal, and deliberately touches nothing else — existing elections continue exactly as they were, and only *new* elections and *new* benefit accounts are refused, with `ERR_BENEFIT_CATEGORY_RETIRED`."

    Design: Corner/state_machines/retire_on_already_retired_category_returns_already_terminal
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000},
            {"category_type": "PARKING", "monthly_exclusion_limit_cents": 30000},
        ],
        region_code=constants.REGION_CHI,
    )
    parking_category = built["categories"][1]

    first = validate_success(
        api.retire_benefit_category(parking_category["id"], PROGRAM_ADMIN)
    )
    assert first["status"] == "RETIRED"
    assert first["version"] == 2

    second = api.retire_benefit_category(parking_category["id"], PROGRAM_ADMIN)
    assert second.status_code == 409, (
        f"a retire against a terminal category must be a 409 conflict, got {second.status_code}"
    )
    validate_error_is_one_of(
        second, [ERR_ALREADY_TERMINAL, ERR_INVALID_STATE_TRANSITION]
    )

    after = validate_success(
        api.get_benefit_category(parking_category["id"], PROGRAM_ADMIN)
    )
    assert after["status"] == "RETIRED", after["status"]
    assert after["version"] == 2, (
        f"the refused second retire must perform no write, version is {after['version']}"
    )


def test_05_publishing_an_already_open_window_a_second_time_is_refused(api):
    """PRD §3.2: "Publishing a window advances it `SCHEDULED → OPEN`, which is what makes it visible to electing employees. It requires the window to be `SCHEDULED` and the owning employer's `program_status` to be `ACTIVE`; a `DRAFT` or `SUSPENDED` program is refused with `ERR_EMPLOYER_PROGRAM_NOT_ACTIVE`."
    PRD §3.2: "an already-`CLOSED` window rejects further transitions with `ERR_ALREADY_TERMINAL`, and any action with no declared outgoing transition from the current state is rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/second_window_open_request_returns_invalid_state_transition
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        region_code=constants.REGION_SEA,
    )
    window = fixtures.make_scheduled_window(
        api, built["employer"]["id"], PROGRAM_ADMIN, benefit_month="2026-08"
    )
    assert window["status"] == "SCHEDULED"
    assert window["version"] == 1

    first = validate_success(api.open_election_window(window["id"], PROGRAM_ADMIN))
    assert first["status"] == "OPEN", first["status"]
    assert first["version"] == 2, first["version"]

    second = api.open_election_window(window["id"], PROGRAM_ADMIN)
    validate_error(second, ERR_INVALID_STATE_TRANSITION)

    after = fixtures.read_window(api, window["id"])
    assert after["status"] == "OPEN", after["status"]
    assert after["version"] == 2, (
        f"re-firing open must not be applied a second time, version is {after['version']}"
    )


def test_06_sealing_a_batch_that_holds_no_pending_lines_is_refused(api):
    """PRD §3.5: "Sealing requires the batch to be `OPEN`, the current logical clock instant to fall strictly before the governing window's `cutoff_at`, and at least one media line in the batch to be `PENDING` — an empty batch cannot be sealed and is refused with `ERR_EMPTY_ORDER_BATCH`."
    PRD §3.5: "A new batch opens in `status` `OPEN` with `line_count`, `subtotal_cents`, `discount_cents` and `total_cents` all zero and both `sealed_by_user_id` and `released_by_user_id` null, as well as `sealed_at`."

    Design: Corner/state_machines/order_batch_seal_with_zero_pending_lines_returns_empty_order_batch
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        region_code=constants.REGION_CHI,
    )
    window = fixtures.make_open_window(api, built["employer"]["id"], PROGRAM_ADMIN)
    batch = fixtures.make_open_batch(
        api, window["id"], constants.REGION_CHI, "desk-empty-seal"
    )
    assert batch["status"] == "OPEN"
    assert batch["line_count"] == 0
    assert batch["version"] == 1

    refused = api.seal_order_batch(
        batch["id"], make_order_desk_headers("desk-empty-seal")
    )
    validate_error(refused, ERR_EMPTY_ORDER_BATCH)

    after = fixtures.read_batch(api, batch["id"])
    assert after["status"] == "OPEN", (
        f"the batch must not leave OPEN, it is {after['status']}"
    )
    assert after["version"] == 1, (
        f"the refused seal must perform no write, version is {after['version']}"
    )
    assert after["line_count"] == 0, after["line_count"]
    assert after["subtotal_cents"] == 0, after["subtotal_cents"]
    assert after["discount_cents"] == 0, after["discount_cents"]
    assert after["total_cents"] == 0, after["total_cents"]
    assert after["sealed_by_user_id"] is None, (
        "a refused seal must not stamp the sealing operator"
    )
    assert after["sealed_at"] is None, "a refused seal must not stamp sealed_at"
    assert after["released_by_user_id"] is None, after["released_by_user_id"]


def test_07_activation_recomputes_the_enrolled_employee_count_from_the_active_roster(api):
    """PRD §3.1: "On success the employer's `program_status` becomes `ACTIVE`, `enrolled_employee_count` is recomputed as the number of that employer's employees whose `status` is `ACTIVE`, and `Employer.version` advances by 1."
    PRD §3.1: "A newly registered employer lands in `program_status` `DRAFT` with `ordinance_mandate_status` `UNASSESSED`, `total_pretax_committed_cents` and `enrolled_employee_count` both at zero, and `version` 1."

    Design: Corner/state_machines/employer_activate_recomputes_enrolled_employee_count_side_effect
    """
    employer = fixtures.make_draft_employer(
        api, PROGRAM_ADMIN, region_code=constants.REGION_NYC
    )
    assert employer["program_status"] == "DRAFT"
    assert employer["enrolled_employee_count"] == 0
    assert employer["version"] == 1

    validate_success(
        api.create_benefit_category(
            factories.benefit_category_payload(
                employer["id"],
                category_type="TRANSIT_PASS",
                monthly_exclusion_limit_cents=30000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    for external_ref in ("NYC-ROSTER-1", "NYC-ROSTER-2"):
        employee = fixtures.make_employee(
            api,
            employer["id"],
            PROGRAM_ADMIN,
            external_ref=external_ref,
            work_region_code=constants.REGION_NYC,
        )
        assert employee["status"] == "ACTIVE", employee["status"]

    before = fixtures.read_employer(api, employer["id"])
    assert before["program_status"] == "DRAFT", before["program_status"]

    activated = validate_success(api.activate_employer(employer["id"], PROGRAM_ADMIN))

    assert activated["program_status"] == "ACTIVE", activated["program_status"]
    assert activated["enrolled_employee_count"] == 2, (
        "the counter must be recomputed from the two ACTIVE employees, got "
        f"{activated['enrolled_employee_count']}"
    )
    assert activated["version"] == before["version"] + 1, (
        f"activation must advance version by exactly 1: {before['version']} -> "
        f"{activated['version']}"
    )
    assert activated["total_pretax_committed_cents"] == 0, (
        "activation moves no money"
    )
    assert activated["ordinance_mandate_status"] == "UNASSESSED", (
        "activation does not assess the local ordinance"
    )

    reread = fixtures.read_employer(api, employer["id"])
    assert reread["program_status"] == "ACTIVE", reread["program_status"]
    assert reread["enrolled_employee_count"] == 2, reread["enrolled_employee_count"]
    assert reread["version"] == activated["version"], reread["version"]
