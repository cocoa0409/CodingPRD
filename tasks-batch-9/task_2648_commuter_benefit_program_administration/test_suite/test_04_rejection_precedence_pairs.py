"""Rejection precedence: which code comes back when one request breaks two rules.

Each pair below is exercised twice.  The isolation test violates only the
later-evaluated rule and proves that rule really does fire on its own; the paired
test then leaves that violation in place, adds the earlier-evaluated violation,
and demands the earlier code -- because the service walks a single fixed ladder
and never masks an earlier check with a later one.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import PROGRAM_ADMIN, factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_ELECTION_WINDOW_NOT_OPEN,
    ERR_EMPTY_ORDER_BATCH,
    ERR_EXCLUSION_LIMIT_EXCEEDED,
    ERR_MEDIA_REGION_INELIGIBLE,
    ERR_ORDER_CUTOFF_PASSED,
    ERR_ORDINANCE_MANDATE_UNMET,
)
from test_helpers.constants import (
    ORDINANCE_EMPLOYEE_THRESHOLD,
    REGION_AUS,
    REGION_NYC,
    REGION_SFO,
)
from test_helpers.test_users import (
    make_compliance_reviewer_headers,
    make_order_desk_headers,
)

# --- Pair 1: a 15000-cent pre-tax request against a 10000-cent shared limit -----
OVERAGE_PRETAX_CENTS = 15000
AUSTIN_GROUP_LIMIT_CENTS = 10000

# --- Pair 2: a parking-only San Francisco employer and an out-of-region medium --
PARKING_PRETAX_CENTS = 12000

# --- Pair 3: the batch seal window ---------------------------------------------
FLEET_CUTOFF_AT = "2026-08-10T00:00:00Z"
PAST_CUTOFF_INSTANT = "2026-08-15T00:00:00Z"
SEALING_DESK_ID = "desk-sealer"


# =============================================================================
# Pair 1 -- election window posture outranks the pre-tax overage rejection
# =============================================================================
def _build_overage_scenario(api):
    """An ACTIVE Austin program whose shared transit limit and category sub-limit
    are both 10000 cents, under a `REJECT_OVERAGE` spill policy.

    A 15000-cent pre-tax request against this program therefore spills 5000 cents,
    which the spill policy refuses outright.  The region is not an ordinance
    jurisdiction and no assessment is run, so the employer stays `UNASSESSED` and
    nothing else can interfere with the two checks under test.
    """
    base = fx.make_program_with_participant(
        api,
        region_code=REGION_AUS,
        employer_overrides={
            "legal_name": "Austin Ride Share Benefits",
            "transit_group_limit_cents": AUSTIN_GROUP_LIMIT_CENTS,
            "parking_group_limit_cents": AUSTIN_GROUP_LIMIT_CENTS,
            "pretax_ratio_cap_pct": 100,
            "spill_policy": "REJECT_OVERAGE",
            "program_cap_cents": 5000000,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": AUSTIN_GROUP_LIMIT_CENTS,
            "pretax_allowed": True,
            "posttax_allowed": True,
        },
        window_overrides={
            "benefit_month": "2026-08",
            "opens_at": "2026-07-01T00:00:00Z",
            "cutoff_at": "2026-08-20T00:00:00Z",
        },
    )
    base["election_body"] = f.election_payload(
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        fx.current_account_version(api, base["account"]["id"]),
        pretax_amount_cents=OVERAGE_PRETAX_CENTS,
        posttax_amount_cents=0,
    )
    return base


def test_01_pretax_overage_alone_is_refused_by_the_rejecting_spill_policy(api):
    """PRD 3.4: "Under `REJECT_OVERAGE`, an overage is not tolerated at all:
    whenever the spill would be greater than zero, the election create or amendment
    is refused with `ERR_EXCLUSION_LIMIT_EXCEEDED` (HTTP 422), and the employee must
    lower their pre-tax request until the spill would be exactly zero."

    Design: Difficulty/priority_pair_validation_conflict/window_locked_state_46_outranks_exclusion_limit_fiscal_80
    """
    scenario = _build_overage_scenario(api)
    window = fx.read_window(api, scenario["window"]["id"])
    assert window["status"] == "OPEN", "only the fiscal rule may be violated here"

    validate_error(
        api.create_election(scenario["election_body"], PROGRAM_ADMIN),
        ERR_EXCLUSION_LIMIT_EXCEEDED,
    )

    elections, meta = validate_paginated(
        api.list_elections(PROGRAM_ADMIN, {"employee_id": scenario["employee"]["id"]})
    )
    assert meta["total_count"] == 0 and elections == [], (
        "a refused election must leave no row behind"
    )


def test_02_locked_window_outranks_the_pretax_overage_on_the_same_body(api):
    """PRD 2.7: "The service therefore evaluates checks in a single fixed ladder,
    returning the first failure it encounters and never masking an earlier check
    with a later one."
    PRD 2.7: "10. Election window posture: creating an election requires the
    window's `status` to be exactly `OPEN`; amending one requires the window's
    `status` to be either `OPEN` or `LOCKED`."
    PRD 2.7: "32. Pre-tax overage under a rejecting spill policy —
    `ERR_EXCLUSION_LIMIT_EXCEEDED` (HTTP 422), on `POST /benefits/elections` and
    `PATCH /benefits/elections/{election_id}`."

    Design: Difficulty/priority_pair_validation_conflict/window_locked_state_46_outranks_exclusion_limit_fiscal_80
    """
    scenario = _build_overage_scenario(api)

    # The identical body is genuinely over the exclusion limit while the window is OPEN.
    validate_error(
        api.create_election(scenario["election_body"], PROGRAM_ADMIN),
        ERR_EXCLUSION_LIMIT_EXCEEDED,
    )

    locked = validate_success(
        api.lock_election_window(scenario["window"]["id"], PROGRAM_ADMIN)
    )
    assert locked["status"] == "LOCKED"

    # Same body, same overage -- but now the window posture check fires first.
    validate_error(
        api.create_election(scenario["election_body"], PROGRAM_ADMIN),
        ERR_ELECTION_WINDOW_NOT_OPEN,
    )

    window = fx.read_window(api, scenario["window"]["id"])
    assert window["election_count"] == 0
    account = fx.read_account(api, scenario["account"]["id"])
    assert account["version"] == scenario["election_body"]["expected_account_version"], (
        "a rejected create must not advance the benefit account version"
    )
    elections, meta = validate_paginated(
        api.list_elections(PROGRAM_ADMIN, {"employee_id": scenario["employee"]["id"]})
    )
    assert meta["total_count"] == 0 and elections == []


# =============================================================================
# Pair 2 -- ordinance posture outranks media region eligibility
# =============================================================================
def _build_parking_only_sfo_scenario(api):
    """An ACTIVE San Francisco employer whose only benefit category is PARKING, a
    roster that hits the ordinance headcount threshold exactly, and a parking
    medium published for the wrong region.

    Because the sole category is PARKING, the employer has no qualifying pre-tax
    transit offering at all; because the medium's region is New York while the
    employee reports in San Francisco, an election naming it is also regionally
    ineligible.  No assessment has run yet, so the ordinance verdict is not yet
    written onto the employer.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {
                "category_type": "PARKING",
                "monthly_exclusion_limit_cents": 30000,
                "pretax_allowed": True,
                "posttax_allowed": True,
            }
        ],
        legal_name="Golden Gate Parking Only",
        region_code=REGION_SFO,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    roster = fx.make_roster(
        api,
        employer["id"],
        ORDINANCE_EMPLOYEE_THRESHOLD,
        work_region_code=REGION_SFO,
        hire_date="2026-01-05T00:00:00Z",
        prefix="SFO",
    )
    media = fx.make_transit_media(
        api,
        "desk-catalog",
        sku="NYC-PARK-A",
        media_type="DEBIT_CARD",
        region_code=REGION_NYC,
        eligible_category_type="PARKING",
        unit_price_cents=PARKING_PRETAX_CENTS,
        requires_physical_fulfillment=False,
    )
    account = fx.make_benefit_account(
        api, roster[0]["id"], category["id"], PROGRAM_ADMIN
    )
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )
    election_body = f.election_payload(
        roster[0]["id"],
        window["id"],
        category["id"],
        account["version"],
        pretax_amount_cents=PARKING_PRETAX_CENTS,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )
    return {
        "employer": employer,
        "category": category,
        "roster": roster,
        "employee": roster[0],
        "media": media,
        "account": account,
        "window": window,
        "election_body": election_body,
    }


def test_03_out_of_region_medium_alone_is_refused_as_regionally_ineligible(api):
    """PRD 3.3: "the product's `eligible_category_type` must equal the elected
    category's `category_type` and the product's `region_code` must equal the
    electing employee's `work_region_code`, with `ERR_MEDIA_REGION_INELIGIBLE`
    otherwise"

    Design: Difficulty/priority_pair_validation_conflict/ordinance_safety_52_outranks_media_region_referential_60
    """
    scenario = _build_parking_only_sfo_scenario(api)
    employer = fx.read_employer(api, scenario["employer"]["id"])
    assert employer["ordinance_mandate_status"] == "UNASSESSED", (
        "an employer that has never been assessed is not blocked, so only the "
        "media eligibility rule may be violated here"
    )
    assert scenario["media"]["region_code"] == REGION_NYC
    assert scenario["employee"]["work_region_code"] == REGION_SFO

    validate_error(
        api.create_election(scenario["election_body"], PROGRAM_ADMIN),
        ERR_MEDIA_REGION_INELIGIBLE,
    )

    window = fx.read_window(api, scenario["window"]["id"])
    assert window["election_count"] == 0


def test_04_noncompliant_ordinance_posture_outranks_media_region_ineligibility(api):
    """PRD 2.7: "Because checks 15 through 17 precede checks 18 through 23, an
    employer found deficient under its local ordinance surfaces as
    `ERR_ORDINANCE_MANDATE_UNMET` even when the election also names a retired
    category or a discontinued media product"
    PRD 3.9: "an employer whose `ordinance_mandate_status` is
    `MANDATED_NONCOMPLIANT` may not take on new elections or amend existing ones
    until the deficiency is cured"
    PRD 3.9: "If the qualifying count is zero, the assessment records
    `mandate_status` `MANDATED_NONCOMPLIANT` with `finding`
    `DEFICIENT_NO_QUALIFYING_TRANSIT_OFFERING`."

    Design: Difficulty/priority_pair_validation_conflict/ordinance_safety_52_outranks_media_region_referential_60
    """
    scenario = _build_parking_only_sfo_scenario(api)

    # The identical body really is regionally ineligible before the assessment runs.
    validate_error(
        api.create_election(scenario["election_body"], PROGRAM_ADMIN),
        ERR_MEDIA_REGION_INELIGIBLE,
    )

    assessment = get_success_data(
        api.create_compliance_assessment(
            scenario["employer"]["id"],
            f.compliance_assessment_payload(assessment_month="2026-08"),
            make_compliance_reviewer_headers("reviewer-okafor"),
        )
    )
    assert assessment["covered_employee_count"] == ORDINANCE_EMPLOYEE_THRESHOLD
    assert assessment["qualifying_transit_offering_count"] == 0
    assert assessment["mandate_status"] == "MANDATED_NONCOMPLIANT"
    assert assessment["finding"] == "DEFICIENT_NO_QUALIFYING_TRANSIT_OFFERING"

    employer = fx.read_employer(api, scenario["employer"]["id"])
    assert employer["ordinance_mandate_status"] == "MANDATED_NONCOMPLIANT", (
        "the verdict is written back onto the employer"
    )

    # Same body, same ineligible medium -- the ordinance guard now answers first.
    validate_error(
        api.create_election(scenario["election_body"], PROGRAM_ADMIN),
        ERR_ORDINANCE_MANDATE_UNMET,
    )

    window = fx.read_window(api, scenario["window"]["id"])
    assert window["election_count"] == 0


# =============================================================================
# Pair 3 -- the order cutoff outranks the non-empty batch constraint
# =============================================================================
def _build_empty_batch_scenario(api):
    """An ACTIVE Austin program with an OPEN 2026-08 window whose cutoff falls on
    2026-08-10, and one procurement batch for that window carrying no lines at all.

    The logical clock still sits at its default instant, which is strictly before
    the cutoff, so at first only the emptiness of the batch can be objected to.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        legal_name="Austin Fleet Passes",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    window = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at=FLEET_CUTOFF_AT,
    )
    batch = fx.make_open_batch(api, window["id"], REGION_AUS, SEALING_DESK_ID)
    return {
        "employer": employer,
        "category": built["categories"][0],
        "window": window,
        "batch": batch,
    }


def _assert_batch_never_sealed(api, batch_id):
    batch = fx.read_batch(api, batch_id)
    assert batch["status"] == "OPEN", "a refused seal must leave the batch OPEN"
    assert batch["sealed_by_user_id"] is None
    assert batch["sealed_at"] is None
    assert batch["line_count"] == 0
    return batch


def test_05_empty_batch_alone_cannot_be_sealed_while_inside_the_cutoff(api):
    """PRD 3.5: "Sealing requires the batch to be `OPEN`, the current logical clock
    instant to fall strictly before the governing window's `cutoff_at`, and at least
    one media line in the batch to be `PENDING` — an empty batch cannot be sealed
    and is refused with `ERR_EMPTY_ORDER_BATCH`."

    Design: Difficulty/priority_pair_validation_conflict/order_cutoff_temporal_66_outranks_empty_batch_constraint_74
    """
    scenario = _build_empty_batch_scenario(api)
    assert scenario["batch"]["line_count"] == 0
    assert scenario["window"]["cutoff_at"].startswith("2026-08-10"), (
        "the clock's default instant must sit strictly before this cutoff"
    )

    validate_error(
        api.seal_order_batch(
            scenario["batch"]["id"], make_order_desk_headers(SEALING_DESK_ID)
        ),
        ERR_EMPTY_ORDER_BATCH,
    )
    _assert_batch_never_sealed(api, scenario["batch"]["id"])


def test_06_cutoff_passed_outranks_the_empty_batch_refusal_on_the_same_seal(api):
    """PRD 2.7: "The service therefore evaluates checks in a single fixed ladder,
    returning the first failure it encounters and never masking an earlier check
    with a later one."
    PRD 2.7: "23. Order cutoff — `ERR_ORDER_CUTOFF_PASSED` (HTTP 422), on four
    operations: `POST /benefits/elections`, `PATCH /benefits/elections/{election_id}`,
    `POST /benefits/media-orders` and `POST /benefits/order-batches/{batch_id}/seal`."
    PRD 2.7: "28. Non-empty batch — `ERR_EMPTY_ORDER_BATCH` (HTTP 422), on
    `POST /benefits/order-batches/{batch_id}/seal`."

    Design: Difficulty/priority_pair_validation_conflict/order_cutoff_temporal_66_outranks_empty_batch_constraint_74
    """
    scenario = _build_empty_batch_scenario(api)
    desk = make_order_desk_headers(SEALING_DESK_ID)

    # Inside the cutoff, the same empty batch is refused for emptiness alone.
    validate_error(api.seal_order_batch(scenario["batch"]["id"], desk), ERR_EMPTY_ORDER_BATCH)

    # Nothing about the batch changes; only the logical clock moves past the cutoff.
    fx.set_clock(api, PAST_CUTOFF_INSTANT)

    validate_error(api.seal_order_batch(scenario["batch"]["id"], desk), ERR_ORDER_CUTOFF_PASSED)
    _assert_batch_never_sealed(api, scenario["batch"]["id"])
