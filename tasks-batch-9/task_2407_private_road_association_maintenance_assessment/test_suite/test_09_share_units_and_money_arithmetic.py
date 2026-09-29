"""Share-unit derivation, the eight-step allocation arithmetic, the reserve
credit at levy, the competitive-bidding floor, and the standing projection."""
import pytest

from test_helpers import (
    api_client,
    make_clerk_headers,
    make_commissioner_headers,
    make_member_owner_headers,
    make_treasurer_headers,
    payment_payload,
    read_action,
    read_association,
    read_bid,
    read_charge,
    read_member,
    read_project,
    read_roll,
    set_clock,
    setup_annual_assessment,
    setup_association,
    setup_delinquent_charge,
    setup_assessment_roll,
    setup_member,
    setup_parcel,
    setup_project,
    setup_road_segment,
    submit_bid,
    subdivide,
    validate_error,
    validate_success,
)
from test_helpers import award_project as award
from test_helpers import list_roll_charges

CLERK = make_clerk_headers("clerk-1")

MAIN_SEGMENT = {
    "length_feet": 1600,
    "width_feet": 22,
    "max_grade_pct": 8,
    "surface_type": "GRAVEL",
    "turnout_count": 1,
    "turnaround_present": True,
    "bridge_present": False,
    "culvert_count": 2,
}

# The five usage classes, each on an identical 240 ft / 8 trip parcel.
FIVE_CLASSES = [
    ("DB140-P01", "RESIDENTIAL_YEAR_ROUND", 240.0),
    ("DB140-P02", "SEASONAL", 144.0),
    ("DB140-P03", "AGRICULTURAL", 192.0),
    ("DB140-P04", "COMMERCIAL", 420.0),
    ("DB140-P05", "UNDEVELOPED", 60.0),
]


class TestUsageClassDrivesFrontageUnitsOnly:
    """One multiplier table, applied on one of the two share units."""

    def test_each_usage_class_scales_the_frontage_units(self, api):
        """PRD §3.2: "The usage-class multiplier is 1.00 for
        `RESIDENTIAL_YEAR_ROUND`, 0.60 for `SEASONAL`, 0.80 for `AGRICULTURAL`,
        1.75 for `COMMERCIAL`, and 0.25 for `UNDEVELOPED`. `frontage_share_units`
        is the parcel's `frontage_feet` multiplied by the multiplier for its
        `usage_class`."

        Design: Corner/calculations/frontage_share_units_follow_usage_class_while_trip_units_ignore_it
        """
        association = setup_association(
            name="Five Classes Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(
            association["id"], name="Five Classes Main", **MAIN_SEGMENT
        )

        for deed_book_page, usage_class, expected_units in FIVE_CLASSES:
            parcel = setup_parcel(
                segment["id"],
                deed_book_page=deed_book_page,
                frontage_feet=240,
                usage_class=usage_class,
                trips_per_day=8,
                covenant_recorded=True,
            )
            assert parcel["usage_class"] == usage_class
            assert parcel["frontage_share_units"] == pytest.approx(
                expected_units, abs=0.0001
            ), f"{usage_class} on 240 ft must weigh {expected_units} frontage units"

    def test_trip_units_are_identical_across_all_five_classes(self, api):
        """PRD §3.2: "`trip_share_units` is the parcel's `trips_per_day`
        multiplied by twenty-five, plus its `frontage_feet` multiplied by two
        tenths. Note the deliberate asymmetry: the trip-generation unit applies no
        usage-class multiplier at all, which is the whole source of divergence
        between the two assessment methods."

        Design: Corner/calculations/frontage_share_units_follow_usage_class_while_trip_units_ignore_it
        """
        association = setup_association(
            name="Five Classes Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(
            association["id"], name="Five Classes Main", **MAIN_SEGMENT
        )

        parcels = [
            setup_parcel(
                segment["id"],
                deed_book_page=deed_book_page,
                frontage_feet=240,
                usage_class=usage_class,
                trips_per_day=8,
                covenant_recorded=True,
            )
            for deed_book_page, usage_class, _ in FIVE_CLASSES
        ]

        for parcel in parcels:
            assert parcel["trip_share_units"] == pytest.approx(248.0, abs=0.0001), (
                "eight trips at twenty-five plus 240 ft at two tenths is 248 units "
                "no matter what the usage class says"
            )
        frontage_units = {p["frontage_share_units"] for p in parcels}
        assert len(frontage_units) == 5, (
            "the same five parcels diverge completely on the frontage side"
        )


class TestAssessableSetExclusions:
    """Five parcels on the road, one parcel in the assessment."""

    def test_certification_assesses_only_the_active_covenanted_parcel(self, api):
        """PRD §3.4: "First the **assessable parcel set** is computed: every parcel
        whose `status` is `ACTIVE`, whose `covenant_recorded` is true, whose
        `road_segment_id` names a segment of the roll's association, and for which
        a member exists on that parcel whose `standing_status` is `GOOD_STANDING`,
        `DELINQUENT`, or `LIEN_FILED`. Parcels that are `SUBDIVIDED`, `WITHDRAWN`,
        or `PENDING_CONNECTION` are excluded, as are parcels whose member is still
        `PENDING_DEED_VERIFICATION`."

        Design: Corner/calculations/certification_excludes_subdivided_pending_and_uncovenanted_parcels
        """
        scenario = _split_rock()

        listed = validate_success(
            api_client.list_parcels(
                CLERK, params={"road_segment_id": scenario["segment"]["id"], "limit": 100}
            )
        )
        assert len(listed) == 5, "parent, two children, and two other lots are all on file"

        roll = validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))

        assert roll["status"] == "CERTIFIED"
        assert roll["total_share_units"] == pytest.approx(290.0, abs=0.0001), (
            "540 units sit on the segment but only the one assessable parcel counts"
        )
        assert roll["total_levied_cents"] == 1_600_000
        assert roll["unallocated_residual_cents"] == 2_400_000

    def test_only_the_assessable_parcel_receives_a_charge(self, api):
        """PRD §3.4: "The certification writes one charge per assessable parcel
        with `charge_type` `ANNUAL` and `status` `PENDING`, freezing that parcel's
        `share_units_snapshot` and computed `amount_cents` onto the charge, with
        `paid_cents` at zero, `balance_cents` equal to `amount_cents`, a null
        `due_date`, and a null `delinquent_since`."

        Design: Corner/calculations/certification_excludes_subdivided_pending_and_uncovenanted_parcels
        """
        scenario = _split_rock()
        validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))

        charges = list_roll_charges(scenario["roll"]["id"])

        assert len(charges) == 1
        charge = charges[0]
        assert charge["parcel_id"] == scenario["assessable_parcel"]["id"]
        assert charge["charge_type"] == "ANNUAL"
        assert charge["status"] == "PENDING"
        assert charge["share_units_snapshot"] == pytest.approx(290.0, abs=0.0001)
        assert charge["amount_cents"] == 1_600_000
        assert charge["balance_cents"] == 1_600_000
        assert charge["paid_cents"] == 0
        assert charge["due_date"] is None
        assert charge["delinquent_since"] is None

        billed = {c["parcel_id"] for c in charges}
        for excluded in scenario["excluded_parcel_ids"]:
            assert excluded not in billed


def _split_rock():
    """One assessable parcel, one subdivided parent with two pending children, and
    one parcel whose covenant was never recorded."""
    set_clock("2026-08-01T00:00:00Z")
    association = setup_association(
        name="Split Rock Road Association", reserve_target_cents=1_000_000
    )
    segment = setup_road_segment(association["id"], name="Split Rock Main", **MAIN_SEGMENT)

    assessable = setup_parcel(
        segment["id"],
        deed_book_page="DB141-P01",
        frontage_feet=290,
        usage_class="RESIDENTIAL_YEAR_ROUND",
        trips_per_day=6,
        covenant_recorded=True,
    )
    setup_member(assessable["id"], verified=True, deed_book_page="DB141-P01")

    to_split = setup_parcel(
        segment["id"],
        deed_book_page="DB141-P02",
        frontage_feet=100,
        usage_class="RESIDENTIAL_YEAR_ROUND",
        trips_per_day=2,
        covenant_recorded=True,
    )
    setup_member(to_split["id"], verified=True, deed_book_page="DB141-P02")
    split = subdivide(
        to_split["id"],
        [
            {"deed_book_page": "DB141-P02A", "frontage_feet": 60},
            {"deed_book_page": "DB141-P02B", "frontage_feet": 40},
        ],
    )

    uncovenanted = setup_parcel(
        segment["id"],
        deed_book_page="DB141-P03",
        frontage_feet=150,
        usage_class="RESIDENTIAL_YEAR_ROUND",
        trips_per_day=1,
        covenant_recorded=False,
    )

    roll = setup_assessment_roll(
        association["id"],
        fiscal_year=2026,
        fy_start_date="2026-01-01",
        fy_end_date="2026-12-31",
        budget_requirement_cents=4_000_000,
        method_variant="FRONTAGE_WEIGHTED",
    )
    return {
        "association": association,
        "segment": segment,
        "assessable_parcel": assessable,
        "roll": roll,
        "excluded_parcel_ids": [
            split["parent_parcel"]["id"],
            uncovenanted["id"],
            *[child["id"] for child in split["children"]],
        ],
    }


SINGLE_290 = [
    {
        "deed_book_page": "DB142-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]


class TestLevyCreditsFifteenPercent:
    """Fifteen percent of four million lands exactly on the adequate boundary."""

    def test_levy_credits_the_contribution_and_dates_the_charge(self, api):
        """PRD §3.4: "On levy, every `ANNUAL` charge of the roll whose `status` is
        `PENDING` moves `PENDING → OPEN` and is stamped with a `due_date` of the
        levy date plus forty-five days; `levied_at` is stamped with the current
        logical-clock instant and the roll's own `due_date` is set to the same date.
        The roll's `reserve_contribution_cents` is set to fifteen percent of
        `budget_requirement_cents`, rounded half up to whole cents, and that amount
        is credited to the association's `reserve_balance_cents`"

        Design: Corner/calculations/levy_credits_fifteen_percent_and_lands_on_the_inclusive_adequate_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=SINGLE_290,
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
            association_overrides={
                "name": "Ridge Hollow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Ridge Hollow Main"),
        )

        roll = scenario["roll"]
        assert roll["status"] == "LEVIED"
        assert roll["reserve_contribution_cents"] == 600_000
        assert roll["levied_at"].startswith("2026-08-01T00:00:00")
        assert roll["due_date"] == "2026-09-15"
        assert roll["version"] == 3, "create, certify, levy — three mutations"

        charges = list_roll_charges(roll["id"])
        assert len(charges) == 1
        assert charges[0]["status"] == "OPEN"
        assert charges[0]["due_date"] == "2026-09-15"
        assert charges[0]["amount_cents"] == 1_600_000

    def test_six_tenths_of_target_is_adequate_and_the_totals_do_not_move(self, api):
        """PRD §2.6: "the posture is `FULLY_FUNDED` when the balance is at least
        the target; otherwise it is `ADEQUATE` when the balance multiplied by one
        hundred is at least the target multiplied by sixty — so a balance of
        exactly sixty percent of target is `ADEQUATE` — and otherwise it is
        `UNDERFUNDED`."
        PRD §2.6: "`reserve_funding_ratio` is the balance divided by the target,
        rounded to four decimals for display."

        Design: Corner/calculations/levy_credits_fifteen_percent_and_lands_on_the_inclusive_adequate_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=SINGLE_290,
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
            association_overrides={
                "name": "Ridge Hollow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Ridge Hollow Main"),
        )

        association = read_association(scenario["association"]["id"])
        assert association["reserve_balance_cents"] == 600_000
        assert association["reserve_funding_ratio"] == pytest.approx(0.6, abs=0.0001)
        assert association["reserve_posture"] == "ADEQUATE", (
            "600000 * 100 equals 1000000 * 60, and the comparison is inclusive"
        )

        roll = read_roll(scenario["roll"]["id"])
        assert roll["total_levied_cents"] == 1_600_000, "the levy spreads no new money"
        assert roll["unallocated_residual_cents"] == 2_400_000


THREE_WAYS = [
    {
        "deed_book_page": "DB143-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
    {
        "deed_book_page": "DB143-P02",
        "frontage_feet": 240,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
    {
        "deed_book_page": "DB143-P03",
        "frontage_feet": 200,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
]


def _three_ways():
    set_clock("2026-08-01T00:00:00Z")
    return setup_annual_assessment(
        parcel_specs=THREE_WAYS,
        fiscal_year=2026,
        fy_start_date="2026-01-01",
        fy_end_date="2026-12-31",
        budget_requirement_cents=4_000_000,
        method_variant="FRONTAGE_WEIGHTED",
        certify=True,
        levy=False,
        association_overrides={
            "name": "Three Ways Road Association",
            "reserve_target_cents": 1_000_000,
        },
        segment_overrides=dict(MAIN_SEGMENT, name="Three Ways Main"),
    )


class TestPerParcelRoundingLeavesAResidual:
    """Three unclamped parcels, three half-up roundings, one cent left over."""

    def test_each_parcel_rounds_half_up_on_its_own(self, api):
        """PRD §3.4: "Seventh, each parcel's post-redistribution figure is rounded
        half up to whole cents to become that parcel's `amount_cents`; the rounding
        is per parcel and never applied to a subtotal."
        PRD §3.4: "Third, each parcel's raw pro-rata share is the roll's
        `budget_requirement_cents` multiplied by that parcel's share unit and
        divided by `total_share_units`, held as an exact rational with no rounding
        yet."

        Design: Corner/calculations/annual_allocation_rounds_each_parcel_then_sums_leaving_a_one_cent_residual
        """
        scenario = _three_ways()
        charges = list_roll_charges(scenario["roll"]["id"])
        by_parcel = {c["parcel_id"]: c for c in charges}

        expected = {
            scenario["parcels"][0]["id"]: 1_589_041,
            scenario["parcels"][1]["id"]: 1_315_068,
            scenario["parcels"][2]["id"]: 1_095_890,
        }
        assert len(charges) == 3
        for parcel_id, amount_cents in expected.items():
            assert by_parcel[parcel_id]["amount_cents"] == amount_cents
            assert by_parcel[parcel_id]["balance_cents"] == amount_cents

    def test_the_sum_of_the_rounded_amounts_leaves_one_cent_unallocated(self, api):
        """PRD §3.4: "Eighth, the roll's `total_levied_cents` is the sum of those
        rounded per-parcel amounts, and its `unallocated_residual_cents` is
        `budget_requirement_cents` minus `total_levied_cents`. That residual is
        recorded rather than spread, and it may legitimately be negative when the
        fifty-thousand-cent floor over-collected, just as it may be positive when
        the per-parcel cap absorbed budget."

        Design: Corner/calculations/annual_allocation_rounds_each_parcel_then_sums_leaving_a_one_cent_residual
        """
        scenario = _three_ways()
        roll = read_roll(scenario["roll"]["id"])
        charges = list_roll_charges(roll["id"])

        assert roll["total_share_units"] == pytest.approx(730.0, abs=0.0001)
        assert roll["total_levied_cents"] == 3_999_999
        assert roll["unallocated_residual_cents"] == 1
        assert sum(c["amount_cents"] for c in charges) == roll["total_levied_cents"]
        assert max(c["amount_cents"] for c in charges) < 1_600_000, (
            "no share reaches the forty-percent cap, so nothing clamps"
        )


class TestCompetitiveBiddingFloorIsInclusive:
    """One million cents needs three bids; 999,999 does not."""

    def test_a_million_cent_bid_with_two_candidates_is_refused_then_allowed(self, api):
        """PRD §3.7: "A competitive-bidding floor then applies: when the winning
        bid's `amount_cents` is at least one million cents, the project must carry
        at least three responsive candidates, and fewer than three is rejected with
        `ERR_INSUFFICIENT_BIDS`. The threshold is inclusive, so a bid of exactly
        one million cents already needs three responsive bids."

        Design: Corner/calculations/competitive_bid_threshold_is_inclusive_at_exactly_one_million_cents
        """
        _, segment = _copper_creek()
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )
        low = submit_bid(project, 1_000_000, contractor_user_id="c-1", contractor_name="Basin Grading LLC")
        mid = submit_bid(project, 1_200_000, contractor_user_id="c-2", contractor_name="Highline Roadworks")

        refused = api_client.award_project(
            project["id"], {"bid_id": low["id"]}, make_commissioner_headers("rc-2")
        )
        validate_error(refused, "ERR_INSUFFICIENT_BIDS", 409)

        held = read_project(project["id"])
        assert held["status"] == "BID_SOLICITATION"
        assert held["awarded_bid_id"] is None

        high = submit_bid(project, 1_500_000, contractor_user_id="c-3", contractor_name="Cascade Earthworks")
        awarded = award(project["id"], low["id"])

        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 1_000_000
        assert awarded["reserve_draw_cents"] == 0
        assert read_bid(low["id"])["status"] == "AWARDED"
        assert read_bid(mid["id"])["status"] == "REJECTED"
        assert read_bid(high["id"])["status"] == "REJECTED"

    def test_one_cent_below_the_floor_awards_on_a_single_bid(self, api):
        """PRD §3.7: "for the operating categories `GRADING`, `SNOW`, and `DUST` the
        draw is zero, because operating work is funded from the annual levy"
        PRD §3.7: "And the computed reserve draw must not exceed the association's
        `reserve_balance_cents`, an inclusive comparison that permits a draw equal
        to the whole balance and drives it to exactly zero; exceeding it is
        `ERR_INSUFFICIENT_RESERVE`."

        Design: Corner/calculations/competitive_bid_threshold_is_inclusive_at_exactly_one_million_cents
        """
        association, segment = _copper_creek()
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-20",
            window_end_date="2026-08-23",
        )
        only_bid = submit_bid(
            project, 999_999, contractor_user_id="c-1", contractor_name="Basin Grading LLC"
        )

        awarded = award(project["id"], only_bid["id"])

        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 999_999
        assert awarded["reserve_draw_cents"] == 0

        assert read_association(association["id"])["reserve_balance_cents"] == 0, (
            "a zero draw satisfies the reserve gate even on an empty reserve"
        )


def _copper_creek():
    set_clock("2026-08-01T00:00:00Z")
    association = setup_association(
        name="Copper Creek Road Association", reserve_target_cents=1_000_000
    )
    segment = setup_road_segment(association["id"], name="Copper Creek Main", **MAIN_SEGMENT)
    return association, segment


class TestStandingFlipsOnTheClearingPayment:
    """A partial payment changes nothing about standing; the last cent changes
    everything."""

    def _effectuated_notice(self):
        scenario = setup_delinquent_charge(
            parcel_specs=[
                {
                    "deed_book_page": "DB144-P01",
                    "frontage_feet": 290,
                    "usage_class": "RESIDENTIAL_YEAR_ROUND",
                    "trips_per_day": 6,
                }
            ],
            levy_clock="2026-08-01T00:00:00Z",
            remedy_clock="2026-10-15T00:00:00Z",
            action_type="NOTICE",
        )
        validate_success(
            api_client.effectuate_delinquency_action(
                scenario["action"]["id"], make_treasurer_headers("bt-2")
            )
        )
        scenario["member_headers"] = make_member_owner_headers(scenario["members"][0]["id"])
        return scenario

    def test_a_partial_payment_leaves_the_member_delinquent_and_warned(self, api):
        """PRD §3.6: "On success the payment is added to `paid_cents`,
        `balance_cents` is recomputed as `amount_cents` less `paid_cents`, and the
        charge moves to `PAID` only when `balance_cents` has reached exactly zero —
        a partial payment leaves the charge where it was."
        PRD §2.8: "if any charge of that member has `status` `DELINQUENT`, the
        standing becomes `DELINQUENT`; failing both, the standing becomes
        `GOOD_STANDING`."

        Design: Corner/calculations/member_standing_flips_only_when_the_last_delinquent_charge_clears
        """
        scenario = self._effectuated_notice()
        charge_id = scenario["charge"]["id"]

        validate_success(
            api_client.create_payment(
                charge_id, payment_payload(1_000_000), scenario["member_headers"]
            )
        )

        charge = read_charge(charge_id)
        assert charge["paid_cents"] == 1_000_000
        assert charge["balance_cents"] == 600_000
        assert charge["status"] == "DELINQUENT"
        assert charge["delinquent_since"] == "2026-10-15"

        member = read_member(scenario["members"][0]["id"])
        assert member["standing_status"] == "DELINQUENT"
        assert member["access_status"] == "WARNED"

        action = read_action(scenario["action"]["id"])
        assert action["status"] == "EFFECTIVE"
        assert action["lien_amount_cents"] == 0, "a NOTICE freezes no lien principal"

    def test_the_clearing_payment_releases_the_notice_and_restores_standing(self, api):
        """PRD §3.6: "Because the charge reached `PAID`, every delinquency action on
        that charge whose `status` is `EFFECTIVE` moves `EFFECTIVE → RELEASED` with
        `released_at` stamped and its `lien_amount_cents` reset to zero"
        PRD §3.6: "A member sitting in `WARNED` or `RESTRICTED` returns to
        `UNRESTRICTED` exactly when, after the mutation, no `EFFECTIVE` remedy
        remains for that member. `restricted_days_used` is not decremented by any
        of this."

        Design: Corner/calculations/member_standing_flips_only_when_the_last_delinquent_charge_clears
        """
        scenario = self._effectuated_notice()
        charge_id = scenario["charge"]["id"]
        validate_success(
            api_client.create_payment(
                charge_id, payment_payload(1_000_000), scenario["member_headers"]
            )
        )

        validate_success(
            api_client.create_payment(
                charge_id, payment_payload(600_000), scenario["member_headers"]
            )
        )

        charge = read_charge(charge_id)
        assert charge["paid_cents"] == 1_600_000
        assert charge["balance_cents"] == 0
        assert charge["status"] == "PAID"

        member = read_member(scenario["members"][0]["id"])
        assert member["standing_status"] == "GOOD_STANDING"
        assert member["access_status"] == "UNRESTRICTED"
        assert member["encumbered_principal_cents"] == 0
        assert member["restricted_days_used"] == 0

        action = read_action(scenario["action"]["id"])
        assert action["status"] == "RELEASED", (
            "released by the payment cascade, not by an explicit release call"
        )
        assert action["released_at"].startswith("2026-10-15T00:00:00")
        assert action["lien_amount_cents"] == 0
