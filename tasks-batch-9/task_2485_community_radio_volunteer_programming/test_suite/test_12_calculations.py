"""Derived numbers, read back at the exact figures the PRD publishes.

Seniority is assembled from four terms with a cap on one of them; a copy screen
sums flag weights and routes on two thresholds; and a penalty price is doubled or
not doubled depending on which side of a half-open hour window the conduct fell.
Each case pins the number itself rather than a range, because a formula that lands
one point out is a different formula.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import (
    DIRECTOR_HEADERS,
    OFFICER_ONE,
    OFFICER_TWO,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
FLIGHT_START = "2026-08-05T00:00:00Z"
FLIGHT_END = "2026-09-05T00:00:00Z"
EPISODE_START = "2026-08-03T09:00:00Z"
SAFE_HARBOUR_START_HOUR = "2026-07-30T06:00:00Z"
SAFE_HARBOUR_END_HOUR = "2026-07-30T22:00:00Z"


def _reviewed_spot(copy_text, underwriter_name):
    """One spot carried from draft through submission to the officer's ruling, so
    the risk score is computed by the review rather than supplied."""
    fixtures.set_clock(CLOCK)
    spot = fixtures.create_spot(
        underwriter_name=underwriter_name,
        spot_class="UNDERWRITING",
        copy_text=copy_text,
        flight_start=FLIGHT_START,
        flight_end=FLIGHT_END,
    )
    fixtures.submit_spot(spot["id"])
    return api_client.review_underwriting_spot(
        spot["id"], factories.review_spot_payload(), make_compliance_officer_headers(OFFICER_ONE)
    )


def _show_with_a_confirmed_hour_and_a_scheduled_airing():
    """One approved music show holding a confirmed Monday 09:00 hour with one
    airing still to come, which is what a restriction has to take away."""
    base = fixtures.station()
    chain = fixtures.episode_chain(
        base["host_id"],
        base["members"],
        title="Delta Blues Hour",
        requested_daypart="MIDDAY",
        duration_minutes=60,
        day_of_week=1,
        start_minute=540,
        scheduled_start_utc=EPISODE_START,
        air_status=None,
        confirm=True,
        publish=False,
    )
    assert fixtures.read_slot(chain["slot_id"])["status"] == "CONFIRMED"
    assert fixtures.read_episode(chain["episode_id"])["air_status"] == "SCHEDULED"
    return chain


def _file_indecency(chain, occurred_at, complainant_note):
    return validate_success(
        api_client.create_compliance_incident(
            factories.create_incident_payload(
                "INDECENCY",
                "MAJOR",
                occurred_at,
                complainant_note=complainant_note,
                program_id=chain["program_id"],
                episode_id=chain["episode_id"],
            ),
            make_compliance_officer_headers(OFFICER_ONE),
        ),
        201,
    )


class TestSeniorityScore:
    def test_a_clean_record_scores_the_published_fifty_four_points(self):
        """Twenty-four months of service and three live certifications make 54.00.

        The score is "a **service term** equal to `continuous_service_months`,
        capped at 60 months", plus "a **certification term** equal to 10 points for
        each live certification", plus a performance term that "When that set is
        empty ... is `0.00`", minus "a **strike term** equal to 15 points for each
        disciplinary strike". "A volunteer with all three core certifications,
        twenty-four whole months of service, no strikes and no hosted shows
        therefore scores exactly `54.00`".

        Design: Corner/calculations/seniority_score_weights_service_and_certifications_on_a_clean_record
        """
        fixtures.set_clock(CLOCK)
        host = fixtures.create_certified_host(seniority_start_date="2024-08-01")

        data = validate_success(
            api_client.get_volunteer(host["id"], DIRECTOR_HEADERS), 200
        )
        assert data["continuous_service_months"] == 24
        assert data["current_certification_count"] == 3
        assert data["strike_count"] == 0
        assertions.assert_two_decimals_equal(data["seniority_score"], 54.00, "seniority_score")
        assert data["status"] == "CERTIFIED"
        assert data["needs_core_renewal"] is False

    def test_the_service_term_stops_at_the_sixty_month_cap(self):
        """Ninety-one months of service earn sixty months of credit and no more.

        The service term is "capped at 60 months — five years of service is as much
        credit as long service can earn, and further months add nothing", and the
        certification term is "10 multiplied by `current_certification_count`". A
        veteran with one live certification therefore reads `70.00`, not the figure
        an uncapped term would give.

        Design: Corner/calculations/seniority_score_service_term_stops_at_the_sixty_month_cap
        """
        fixtures.set_clock(CLOCK)
        gus = fixtures.create_volunteer(
            legal_name="Gus Amado",
            email="gus@krcr.example",
            role_track="ENGINEER",
            seniority_start_date="2019-01-01",
        )
        fixtures.add_certification(gus["id"], "BOARD_OPERATION", 84)

        data = validate_success(api_client.get_volunteer(gus["id"], DIRECTOR_HEADERS), 200)
        assert data["continuous_service_months"] == 91
        assert data["current_certification_count"] == 1
        assertions.assert_two_decimals_equal(data["seniority_score"], 70.00, "seniority_score")
        assert data["status"] == "IN_TRAINING"
        assert data["needs_core_renewal"] is True


class TestUnderwritingRiskScore:
    def test_two_flags_sum_past_the_reject_threshold(self):
        """A call to action and a stated price add up to seventy-five points.

        "`CALL_TO_ACTION` contributes 40 points when the normalized copy contains
        any of the phrases "call now" ..." and "`PRICE_INFO` contributes 35 points
        when the copy states a price: either it contains a currency amount, meaning
        a dollar sign immediately followed by a digit". `MISSING_SPONSOR_ID` fires
        only "when the normalized copy does **not** contain the spot's
        `underwriter_name`", and this copy names it. `compliance_flags` records "the
        names of exactly the flags that matched, sorted in ascending alphabetical
        order". "A score of at least 60 moves the spot `UNDER_REVIEW → REJECTED`;
        `approved_copy_text` stays null and `public_file_status` stays
        `NOT_REQUIRED`", and "the officer's `X-User-ID` is stored in
        `reviewed_by_user_id`".

        Design: Corner/calculations/underwriting_risk_score_sums_two_flag_weights_and_rejects_the_copy
        """
        response = _reviewed_spot(
            "Call now and visit Ada's Autos on Fifth Street, tires from $99.",
            "Ada's Autos",
        )
        data = validate_success(response, 200)

        assert data["noncommercial_risk_score"] == 75
        assert data["compliance_flags"] == ["CALL_TO_ACTION", "PRICE_INFO"]
        assert data["status"] == "REJECTED"
        assert data["approved_copy_text"] is None
        assert data["public_file_status"] == "NOT_REQUIRED"
        assert data["reviewed_by_user_id"] == OFFICER_ONE
        assertions.assert_underwriting_spot(data)

    def test_a_single_flag_below_the_edit_threshold_still_approves(self):
        """Ten points is a flag on the record but not a bar to approval.

        "`MISSING_SPONSOR_ID` contributes 10 points when the normalized copy does
        **not** contain the spot's `underwriter_name` normalized by the identical
        rule". "A `noncommercial_risk_score` below 25 moves the spot `UNDER_REVIEW →
        APPROVED` with the `copy_text` accepted as-is", and "Spots of class
        `UNDERWRITING` and `PSA` incur no obligation and keep `public_file_status`
        `NOT_REQUIRED`."

        Design: Corner/calculations/underwriting_risk_score_below_the_edit_threshold_approves_a_flagged_copy
        """
        response = _reviewed_spot(
            "Fresh sourdough is baked daily on Fifth Street.", "Bluebird Bakery"
        )
        data = validate_success(response, 200)

        assert data["noncommercial_risk_score"] == 10
        assert data["compliance_flags"] == ["MISSING_SPONSOR_ID"]
        assert data["status"] == "APPROVED"
        assert data["public_file_status"] == "NOT_REQUIRED"
        assert data["reviewed_by_user_id"] == OFFICER_ONE
        assertions.assert_underwriting_spot(data)


class TestSafeHarbourMultiplier:
    def test_conduct_at_exactly_six_in_the_morning_is_doubled(self):
        """The window opens inclusively, so a major indecency costs ten points.

        The flag "is true when — and only when — the `category` is `INDECENCY` and
        the station-local hour of `occurred_at` falls in the window from 06:00 up to
        but not including 22:00 ... conduct at exactly `06:00` is inside it. When
        `safe_harbor_violation` is true the base points are **doubled**", the
        `INDECENCY` base being "5 at `MAJOR`". Ten points reaches `RESTRICTED`, which
        begins "at 6 points or more", and that fires the cascade: "every occupation
        of that show in `TENTATIVE` or `CONFIRMED` moves to `PREEMPTED` — with
        `preempted_by_program_id` left null ... and every airing of that show whose
        `air_status` is `SCHEDULED` moves to `CANCELLED`."

        Design: Corner/calculations/incident_penalty_points_double_at_the_safe_harbour_start_hour
        """
        chain = _show_with_a_confirmed_hour_and_a_scheduled_airing()

        filed = _file_indecency(
            chain, SAFE_HARBOUR_START_HOUR, "Unbleeped word during the 06:00 hour."
        )
        assert filed["safe_harbor_violation"] is True
        assert filed["penalty_points"] == 10

        ruled = validate_success(
            api_client.adjudicate_compliance_incident(
                filed["id"],
                factories.adjudicate_incident_payload(finding="SUBSTANTIATED"),
                make_compliance_officer_headers(OFFICER_TWO),
            ),
            200,
        )
        assert ruled["status"] == "SUBSTANTIATED"

        program = fixtures.read_program(chain["program_id"])
        assert program["compliance_penalty_points"] == 10
        assert program["compliance_standing"] == "RESTRICTED"

        slot = fixtures.read_slot(chain["slot_id"])
        assert slot["status"] == "PREEMPTED"
        assert slot["preempted_by_program_id"] is None

        assert fixtures.read_episode(chain["episode_id"])["air_status"] == "CANCELLED"

    def test_conduct_at_exactly_ten_at_night_is_not_doubled(self):
        """The window closes exclusively, so the identical conduct costs five.

        "That window is half-open at the top: conduct at 21:59 is inside the window
        and conduct at exactly 22:00 is outside it." Five points lands the show on
        `WATCH`, which runs "from 1 through 5 points", and "`WATCH` is a warning
        state only: a show on `WATCH` keeps airing, keeps its occupations and can
        still be given new airings".

        Design: Corner/calculations/incident_penalty_points_are_not_doubled_at_the_safe_harbour_end_hour
        """
        chain = _show_with_a_confirmed_hour_and_a_scheduled_airing()

        filed = _file_indecency(
            chain, SAFE_HARBOUR_END_HOUR, "Unbleeped word at the top of the 22:00 hour."
        )
        assert filed["safe_harbor_violation"] is False
        assert filed["penalty_points"] == 5

        validate_success(
            api_client.adjudicate_compliance_incident(
                filed["id"],
                factories.adjudicate_incident_payload(finding="SUBSTANTIATED"),
                make_compliance_officer_headers(OFFICER_TWO),
            ),
            200,
        )

        program = fixtures.read_program(chain["program_id"])
        assert program["compliance_penalty_points"] == 5
        assert program["compliance_standing"] == "WATCH"

        assert fixtures.read_slot(chain["slot_id"])["status"] == "CONFIRMED"
        assert fixtures.read_episode(chain["episode_id"])["air_status"] == "SCHEDULED"
