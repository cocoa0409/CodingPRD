"""Three off-by-one boundaries where the PRD says the comparison is strictly greater-than.

Each test pairs the value that lands exactly on the limit with the value one notch past it,
so neither an inclusive comparison nor a truncating division can pass both halves.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_COST_VARIANCE_EXCEEDED, ERR_PROSPECT_FRAUD_BLOCKED
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_money_group,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    ADVERSE_ACTION_NONE,
    ADVERSE_ACTION_RENT_TO_INCOME,
    APP_CONDITIONAL_APPROVED,
    APP_DENIED,
    CLOCK_AUG_01,
    FRAUD_VARIANT_POST,
    IDENTITY_VERIFIED,
    OCC_RESERVED,
    SLOT_AVAILABLE,
    SLOT_BOOKED,
    WO_PENDING_DISPATCH,
)


def test_a_score_of_exactly_the_block_threshold_may_still_book(api):
    """6000 books; 6002 is refused. The gate is strictly greater-than.

    PRD SS3.6: "A third prospect, verified with a document score of 6000, liveness true, a
    verified income of 157500, credit `D`, no evictions, a device reputation of 3000 and 400 km,
    has factors identity 4000, income 7500, history 5000 and device 9000, weighing out to
    14000000 plus 22500000 plus 10000000 plus 13500000 and giving exactly 6000 basis points --
    landing exactly on the threshold, which is allowed."  PRD SS3.7: booking "requires ... its
    `fraud_risk_score_bps` to be at or below the market's `fraud_block_threshold_bps`, a
    strictly greater score being refused with `ERR_PROSPECT_FRAUD_BLOCKED`."

    Design: Difficulty/boundary_precision_check/fraud_score_exactly_at_block_threshold_allows_booking
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    first_slot = x.available_slot(
        api,
        home["id"],
        starts_at="2026-09-10T15:00:00Z",
        ends_at="2026-09-10T15:30:00Z",
    )
    second_slot = x.available_slot(
        api,
        home["id"],
        starts_at="2026-09-10T16:00:00Z",
        ends_at="2026-09-10T16:30:00Z",
    )
    on_threshold = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p3a@example.com",
            "full_name": "Priya ThreeA",
            "phone": "+1-404-555-0131",
            "declared_monthly_income_cents": 157500,
            "credit_tier": "D",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 6000,
            "verified_monthly_income_cents": 157500,
            "device_reputation_bps": 3000,
            "ip_geo_distance_km": 400,
        },
    )
    over_threshold = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p3b@example.com",
            "full_name": "Peter ThreeB",
            "phone": "+1-404-555-0132",
            "declared_monthly_income_cents": 157000,
            "credit_tier": "D",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 6000,
            "verified_monthly_income_cents": 157000,
            "device_reputation_bps": 3000,
            "ip_geo_distance_km": 400,
        },
    )
    assert_fields(
        on_threshold.verified,
        fraud_risk_score_bps=6000,
        identity_status=IDENTITY_VERIFIED,
        fraud_score_variant=FRAUD_VARIANT_POST,
    )
    assert_fields(
        over_threshold.verified,
        fraud_risk_score_bps=6002,
        identity_status=IDENTITY_VERIFIED,
    )

    booked = ok(
        api.book_showing_slot(
            first_slot["id"],
            f.book_slot_payload(on_threshold.prospect_id),
            on_threshold.headers,
        )
    )
    assert_fields(booked, status=SLOT_BOOKED, prospect_id=on_threshold.prospect_id)

    failed(
        api.book_showing_slot(
            second_slot["id"],
            f.book_slot_payload(over_threshold.prospect_id),
            over_threshold.headers,
        ),
        ERR_PROSPECT_FRAUD_BLOCKED,
    )

    untouched = ok(api.get_showing_slot(second_slot["id"], x.AGENT))
    assert_fields(untouched, status=SLOT_AVAILABLE)
    assert_absent_or_empty(untouched, "prospect_id")
    assert_fields(ok(api.get_home(home["id"], x.ANALYST)), booked_showing_count=1)


def test_a_variance_of_exactly_the_tolerance_is_accepted_and_one_cent_more_is_not(api):
    """321408 rounds to 1000 and stands; 321409 rounds to 1001 and is refused.

    PRD SS3.3: "`variance_bps` is then the quoted cost less that benchmark, multiplied by 10,000,
    divided by the benchmark and rounded half up".  PRD SS3.3: "A quote whose `variance_bps` is
    **strictly greater** than the market's `cost_variance_tolerance_bps` is refused with
    `ERR_COST_VARIANCE_EXCEEDED`; a variance landing exactly on the tolerance is accepted.
    Continuing the interior-paint example whose benchmark was 292176, a quote of 300000 gives
    268 basis points and is accepted against a tolerance of 1000".

    Design: Difficulty/boundary_precision_check/work_order_variance_exactly_at_tolerance_accepted
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])

    accepted = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                quoted_cost_cents=321408,
            ),
            x.OPS,
        )
    )
    assert_money_group(accepted, benchmark_total_cents=292176, quoted_cost_cents=321408)
    assert_fields(accepted, variance_bps=1000, status=WO_PENDING_DISPATCH, crew_days=9)

    failed(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                quoted_cost_cents=321409,
            ),
            x.OPS,
        ),
        ERR_COST_VARIANCE_EXCEEDED,
    )

    rows, _meta = page(api.list_work_orders(x.OPS, {"home_id": home["id"]}))
    assert [row["id"] for row in rows] == [accepted["id"]]


def test_a_rent_to_income_ratio_exactly_at_the_ceiling_is_conditionally_approved(api):
    """537500 of income screens through at exactly 4000; 537000 gives 4004 and is denied.

    PRD SS3.8: "On the boundary, a verified income of 537500 gives a ratio of exactly 4000, which
    does not fire clause 3 and so lands in clause 5 as `CONDITIONAL_APPROVED`, whereas a verified
    income of 537000 gives 4004 and is `DENIED` for `RENT_TO_INCOME`."  PRD SS3.8 clause 3:
    "Otherwise, if `rent_to_income_bps` is **strictly greater** than the market's
    `rent_to_income_max_bps`, it is `DENIED` with `adverse_action_reason` `RENT_TO_INCOME`. A
    ratio landing exactly on the ceiling does not fire this clause and falls through."  PRD SS3.8
    on the two side-effect sets: "On `DENIED`, `security_deposit_cents`, `pet_deposit_cents`,
    `total_move_in_deposit_cents` and `risk_multiplier_bps` are all set to 0 and the **home is
    not touched at all**", while an approval builds the stack and cascades "the home's
    `occupancy_status` `VACANT` -> `RESERVED`".

    Design: Difficulty/boundary_precision_check/rent_to_income_exactly_at_market_ceiling_conditionally_approved
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    over_ceiling = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p6a@example.com",
            "full_name": "Pia SixA",
            "phone": "+1-404-555-0161",
            "declared_monthly_income_cents": 600000,
        },
        verification_overrides={"verified_monthly_income_cents": 537000},
    )
    on_ceiling = x.verified_prospect(
        api,
        market["id"],
        prospect_overrides={
            "email": "p6b@example.com",
            "full_name": "Pablo SixB",
            "phone": "+1-404-555-0162",
            "declared_monthly_income_cents": 600000,
        },
        verification_overrides={"verified_monthly_income_cents": 537500},
    )
    assert_fields(over_ceiling.verified, fraud_risk_score_bps=1203)
    assert_fields(on_ceiling.verified, fraud_risk_score_bps=1200)
    app_a = get_success_data(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"], over_ceiling.prospect_id, pet_count=0, pet_breeds=[]
            ),
            over_ceiling.headers,
        )
    )
    app_b = get_success_data(
        api.create_rental_application(
            f.rental_application_payload(
                home["id"], on_ceiling.prospect_id, pet_count=0, pet_breeds=[]
            ),
            on_ceiling.headers,
        )
    )

    denied = ok(api.screen_rental_application(app_a["id"], {}, x.AGENT))
    approved = ok(api.screen_rental_application(app_b["id"], {}, x.AGENT))

    assert_fields(
        denied,
        rent_to_income_bps=4004,
        status=APP_DENIED,
        adverse_action_reason=ADVERSE_ACTION_RENT_TO_INCOME,
        risk_multiplier_bps=0,
    )
    assert_money_group(denied, total_move_in_deposit_cents=0)
    assert_fields(
        approved,
        rent_to_income_bps=4000,
        status=APP_CONDITIONAL_APPROVED,
        adverse_action_reason=ADVERSE_ACTION_NONE,
        risk_multiplier_bps=15000,
    )
    assert_money_group(
        approved,
        security_deposit_cents=322500,
        pet_deposit_cents=0,
        total_move_in_deposit_cents=322500,
    )
    assert_fields(ok(api.get_home(home["id"], x.ANALYST)), occupancy_status=OCC_RESERVED)
