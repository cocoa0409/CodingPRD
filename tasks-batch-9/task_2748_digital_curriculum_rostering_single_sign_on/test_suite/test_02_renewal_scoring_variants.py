"""
The two renewal-scoring bases of a vendor licence, and the inclusive floor
between renewing and renegotiating.

The renewal conversation is served by one computed read that carries a basis. The
decision of record ignores accounts that have gone quiet and measures engagement
against every seat the district pays for; the provisional basis offered to an
in-flight pilot forgives staleness and measures engagement against the seats that
actually have working identities. Identical stored rows therefore produce two
different scores and two different recommendations, while the invoice underneath
does not move. The recommendation tiers themselves are inclusive floors, so a
score that lands exactly on seventy renews.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import assert_integer_cents
from test_helpers.types import (
    GradeBand,
    IdentityStatus,
    OveragePolicy,
    RenewalBasis,
    RenewalRecommendation,
    SeatStatus,
)

USAGE_DATE = "2026-08-01"
ENGAGED_MINUTES = 120
LICENCE_SEATS = 5
LIST_PRICE_CENTS = 1000
COMMITTED_CENTS = 4000


def _ratio(value):
    """Renewal ratios are exposed unrounded, so compare them as real numbers."""
    return pytest.approx(value, abs=1e-9)


def _summary(api, vendor_app_id, **params):
    """Read the renewal summary as the data-governance authority."""
    response = api.get_renewal_summary(
        vendor_app_id, users.DATA_GOVERNANCE_OFFICER, **params
    )
    return validate_success(response, 200)


def _stale_usage_world(api):
    """
    A five-seat elementary licence with four seats taken: three identities have
    passwords, two of those logged two hours each on 1 August, and the clock then
    stands forty days later on 10 September.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
        min_password_length=8,
        password_requires_mixed_case=True,
        password_max_age_days=180,
        password_lockout_threshold=5,
        temp_password_ttl_hours=72,
    )
    term = fx.create_active_term(api)
    students = [
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2001", first_name="Alex", last_name="Nakamura",
            date_of_birth="2016-05-04",
        ),
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2002", first_name="Priya", last_name="Rao",
            date_of_birth="2016-07-11",
        ),
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2003", first_name="Liam", last_name="Osei",
            date_of_birth="2016-09-23",
        ),
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2004", first_name="Nora", last_name="Iqbal",
            date_of_birth="2016-11-02",
        ),
    ]
    licence = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=LICENCE_SEATS,
        price_per_seat_cents=LIST_PRICE_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="MathBlast",
        vendor_code="MBX",
        overage_policy=OveragePolicy.BLOCK,
    )
    fx.activate_license(api, licence["id"])
    allocation = fx.allocation_for_school(api, licence["id"], school["id"])

    accounts = [
        fx.provision_account(
            api, allocation["id"], vendor_app_id=licence["id"],
            student_id=student["id"],
        )
        for student in students
    ]
    for account in accounts[:3]:
        fx.set_account_password(api, account["id"])
    for account in accounts[:2]:
        fx.record_usage(
            api, account["id"], USAGE_DATE, ENGAGED_MINUTES,
            session_count=4, failed_logins=0,
        )

    fx.set_clock(api, "2026-09-10T00:00:00Z")
    return {
        "licence_id": licence["id"],
        "accounts": accounts,
    }


def test_final_basis_writes_off_stale_usage_and_recommends_renegotiating(api):
    """Forty days of silence wipes out the licence's engagement on the basis of record.

    Under the final basis "the recency test requires the account's
    `last_activity_date` to be no earlier than 30 days before the clock date, so
    stale accounts stop counting as engaged, and the engagement denominator is
    the consumed count". With four consumed seats out of five and nothing
    engaged, utilization contributes 0.40 while engagement and cost efficiency
    contribute nothing, "the final basis scores 40.00 and recommends
    `RENEGOTIATE`".

    Design: Difficulty/dual_variant_calc/renewal_score_final_vs_provisional_on_vendor_app
    """
    world = _stale_usage_world(api)

    summary = _summary(api, world["licence_id"])

    assert summary["basis"] == RenewalBasis.FINAL
    assert summary["consumed_seats"] == 4
    assert summary["provisioned_seats"] == 3
    assert summary["engaged_seats"] == 0
    assert float(summary["utilization"]) == _ratio(0.8)
    assert float(summary["engagement"]) == _ratio(0.0)
    assert summary["cost_per_engaged_cents"] is None
    assert float(summary["cost_efficiency"]) == _ratio(0.0)
    assert float(summary["renewal_score"]) == 40.00
    assert summary["renewal_recommendation"] == RenewalRecommendation.RENEGOTIATE


def test_provisional_basis_forgives_stale_usage_and_recommends_renewing(api):
    """The same rows, scored for an in-flight pilot, argue for renewal.

    "Under the provisional basis the recency test always passes, so lifetime
    minutes count whenever they were logged, and the engagement denominator is
    the provisioned count, excluding seats that are merely `RESERVED`" — so two
    engaged accounts over three provisioned ones, with a cost per engaged seat of
    2000 cents against the 1500-cent target, give "0.40 plus 0.30 times
    two-thirds plus 0.20 times 0.75, which is 0.75, or 75.00, and recommends
    `RENEW`".

    Design: Difficulty/dual_variant_calc/renewal_score_final_vs_provisional_on_vendor_app
    """
    world = _stale_usage_world(api)

    summary = _summary(api, world["licence_id"], basis=RenewalBasis.PROVISIONAL)

    assert summary["basis"] == RenewalBasis.PROVISIONAL
    assert summary["consumed_seats"] == 4
    assert summary["provisioned_seats"] == 3
    assert summary["engaged_seats"] == 2
    assert float(summary["utilization"]) == _ratio(0.8)
    assert float(summary["engagement"]) == _ratio(2 / 3)
    assert summary["cost_per_engaged_cents"] == 2000
    assert_integer_cents(summary["cost_per_engaged_cents"], "cost_per_engaged_cents")
    assert float(summary["cost_efficiency"]) == _ratio(0.75)
    assert float(summary["renewal_score"]) == 75.00
    assert summary["renewal_recommendation"] == RenewalRecommendation.RENEW


def test_the_invoice_projection_is_the_same_under_both_bases(api):
    """The negotiating scores differ but the money the district owes does not.

    The invoice projection starts from "the license's `committed_charge_cents`,
    already net of refunds" — 4000 cents for four full-price seats — which sits
    "below" every discount tier, so the fee is "the larger of a 25000-cent floor
    and the net seat charge multiplied by 0.03 rounded up" and the total is "the
    net seat charge plus the platform fee minus the shelfware credit". Nothing in
    those seven steps reads the basis.

    Design: Difficulty/dual_variant_calc/renewal_score_final_vs_provisional_on_vendor_app
    """
    world = _stale_usage_world(api)

    final = _summary(api, world["licence_id"])
    provisional = _summary(
        api, world["licence_id"], basis=RenewalBasis.PROVISIONAL
    )

    licence = fx.read_vendor_app(api, world["licence_id"])
    assert licence["committed_charge_cents"] == COMMITTED_CENTS

    for summary in (final, provisional):
        assert summary["gross_seat_cents"] == 4000
        assert float(summary["discount_rate"]) == _ratio(0.0)
        assert summary["discount_cents"] == 0
        assert summary["net_seat_cents"] == 4000
        assert summary["platform_fee_cents"] == 25000
        assert summary["shelfware_credit_cents"] == 0
        assert summary["invoice_total_cents"] == 29000
        assert_integer_cents(summary["invoice_total_cents"], "invoice_total_cents")


def test_the_unprovisioned_account_still_holds_its_reserved_seat(api):
    """The student whose password was never set is still costing the district a seat.

    Creation puts an account at "`seat_status` of `RESERVED` on the seat axis and
    `identity_status` of `PENDING_PROVISION` on the identity axis", and
    "`PROVISIONED` is never reached by creation; only a later password set gets
    there" — which is why the consumed count of four exceeds the provisioned
    count of three.

    Design: Difficulty/dual_variant_calc/renewal_score_final_vs_provisional_on_vendor_app
    """
    world = _stale_usage_world(api)

    fourth = fx.read_account(api, world["accounts"][3]["id"])

    assert fourth["identity_status"] == IdentityStatus.PENDING_PROVISION
    assert fourth["seat_status"] == SeatStatus.RESERVED
    assert fourth["active_minutes_total"] == 0
    assert fourth["last_activity_date"] is None


def _fresh_usage_world(api):
    """
    A five-seat elementary licence with four seats taken and every identity given
    a password, on a clock that stays at 1 August so no usage can go stale.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    term = fx.create_active_term(api)
    students = [
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2001", first_name="Alex", last_name="Nakamura",
            date_of_birth="2016-05-04",
        ),
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2002", first_name="Priya", last_name="Raman",
            date_of_birth="2016-07-11",
        ),
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2003", first_name="Lena", last_name="Sorensen",
            date_of_birth="2016-09-19",
        ),
        fx.create_student(
            api, school["id"], grade_level=4,
            sis_student_id="STU-2004", first_name="Mateo", last_name="Vargas",
            date_of_birth="2016-11-23",
        ),
    ]
    licence = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=LICENCE_SEATS,
        price_per_seat_cents=LIST_PRICE_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="MathBlast",
        vendor_code="MBX",
        overage_policy=OveragePolicy.BLOCK,
    )
    fx.activate_license(api, licence["id"])
    allocation = fx.allocation_for_school(api, licence["id"], school["id"])

    accounts = [
        fx.provision_account(
            api, allocation["id"], vendor_app_id=licence["id"],
            student_id=student["id"],
        )
        for student in students
    ]
    for account in accounts:
        fx.set_account_password(api, account["id"])

    return {
        "licence_id": licence["id"],
        "accounts": accounts,
    }


def _post_two_hours(api, account):
    """Post exactly the engagement floor of two hours for one account."""
    return fx.record_usage(
        api, account["id"], USAGE_DATE, ENGAGED_MINUTES,
        session_count=3, failed_logins=0,
    )


def test_one_engaged_seat_of_four_falls_short_of_the_renew_floor(api):
    """A single genuinely used seat out of four leaves the licence a renegotiation.

    With one engaged account the engagement term is one over the four consumed
    seats and the cost per engaged seat is the whole 4000 cents committed,
    against which "cost efficiency is the smaller of 1 and the ratio of a
    1500-cent target to that cost per engaged seat" — 0.375. The PRD works this
    exact case: "Drop either engaged account below 120 minutes and engagement
    falls to 0.25 while cost efficiency falls to 0.375, giving 0.55 and a score of
    55.00, which is `RENEGOTIATE`."

    Design: Difficulty/boundary_precision_check/renewal_score_exactly_at_renew_floor
    """
    world = _fresh_usage_world(api)
    _post_two_hours(api, world["accounts"][0])

    summary = _summary(api, world["licence_id"])

    assert summary["basis"] == RenewalBasis.FINAL
    assert summary["consumed_seats"] == 4
    assert summary["provisioned_seats"] == 4
    assert summary["engaged_seats"] == 1
    assert float(summary["utilization"]) == _ratio(0.8)
    assert float(summary["engagement"]) == _ratio(0.25)
    assert summary["cost_per_engaged_cents"] == 4000
    assert float(summary["cost_efficiency"]) == _ratio(0.375)
    assert float(summary["renewal_score"]) == 55.00
    assert summary["renewal_recommendation"] == RenewalRecommendation.RENEGOTIATE


def test_a_score_landing_exactly_on_seventy_still_renews(api):
    """Two engaged seats put the licence precisely on the renewal floor, which renews.

    "A license with `total_seats` of 5 and `price_per_seat_cents` of 1000, with 4
    seats consumed, `committed_charge_cents` of 4000 and 2 engaged accounts, has a
    utilization of 0.8 contributing 0.40, an engagement of 2 divided by 4
    contributing 0.15, and a cost per engaged seat of 2000 cents giving a cost
    efficiency of 0.75 and contributing 0.15 — a weighted sum of 0.70 and a
    `renewal_score` of exactly 70.00, which lands on `RENEW`." The tiers use
    inclusive floors: "`RENEW` at a score of 70 or above ... Both comparisons are
    'at least', never 'greater than'."

    Design: Difficulty/boundary_precision_check/renewal_score_exactly_at_renew_floor
    """
    world = _fresh_usage_world(api)
    _post_two_hours(api, world["accounts"][0])
    _post_two_hours(api, world["accounts"][1])

    summary = _summary(api, world["licence_id"])

    assert summary["consumed_seats"] == 4
    assert summary["provisioned_seats"] == 4
    assert summary["engaged_seats"] == 2
    assert float(summary["engagement"]) == _ratio(0.5)
    assert summary["cost_per_engaged_cents"] == 2000
    assert float(summary["cost_efficiency"]) == _ratio(0.75)
    assert float(summary["renewal_score"]) == 70.00
    assert summary["renewal_recommendation"] == RenewalRecommendation.RENEW


def test_exactly_two_hours_of_classroom_use_counts_as_engaged(api):
    """Two hours on the nose is engagement; an untouched account is not.

    The engaged population is the accounts that are "`PROVISIONED`, have an
    `active_minutes_total` of at least 120 minutes — two hours of real classroom
    use — and satisfy the variant's recency test", and every usage report grows
    that total by "the reported `active_minutes`". Two accounts therefore sit
    exactly on the inclusive floor while the two that never reported sit at zero.

    Design: Difficulty/boundary_precision_check/renewal_score_exactly_at_renew_floor
    """
    world = _fresh_usage_world(api)
    _post_two_hours(api, world["accounts"][0])
    _post_two_hours(api, world["accounts"][1])

    reported = [
        fx.read_account(api, account["id"]) for account in world["accounts"]
    ]

    assert reported[0]["active_minutes_total"] == 120
    assert reported[1]["active_minutes_total"] == 120
    assert reported[2]["active_minutes_total"] == 0
    assert reported[3]["active_minutes_total"] == 0
    assert reported[0]["last_activity_date"] == USAGE_DATE
    assert reported[1]["last_activity_date"] == USAGE_DATE


def test_telemetry_rescores_the_licence_without_touching_the_money(api):
    """The boundary score is stored on the licence, and usage never bills anything.

    Both "`renewal_score` and `renewal_recommendation` are also stored on the
    license and are recomputed whenever ... a usage report arrives", so the second
    report leaves the licence itself sitting on 70.00 and `RENEW`. The committed
    charge, frozen at each seat's provisioning rate, is untouched by telemetry:
    the report only moves minutes, sessions, the activity date and the seat axis.

    Design: Difficulty/boundary_precision_check/renewal_score_exactly_at_renew_floor
    """
    world = _fresh_usage_world(api)
    _post_two_hours(api, world["accounts"][0])
    committed_before = fx.read_vendor_app(api, world["licence_id"])[
        "committed_charge_cents"
    ]
    _post_two_hours(api, world["accounts"][1])

    licence = fx.read_vendor_app(api, world["licence_id"])

    assert float(licence["renewal_score"]) == 70.00
    assert licence["renewal_recommendation"] == RenewalRecommendation.RENEW
    assert committed_before == COMMITTED_CENTS
    assert licence["committed_charge_cents"] == COMMITTED_CENTS
    assert licence["consumed_seats"] == 4
