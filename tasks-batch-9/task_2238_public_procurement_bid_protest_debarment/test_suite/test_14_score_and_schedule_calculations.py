"""Composite responsibility scores, the moving bid due date, the apparent low
bidder, the debarred-list snapshot window and the officer's daily docket.

Every value asserted here is derived by a pinned procedure in the PRD, so each
test builds the exact inputs the procedure reads and pins the single result the
procedure must produce — together with the neighbouring value a plausible but
wrong reading of the procedure would have produced instead.
"""
from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    OFFICER_HEADERS,
    REVIEWER_HEADERS,
)

QUESTION_DEADLINE_CLOCK = "2026-08-20T00:00:00Z"
BID_DUE_CLOCK = "2026-08-27T00:00:00Z"


# --------------------------------------------------------------------------
# Private composition helpers. Each one drives the public API only.
# --------------------------------------------------------------------------
def _requirement(code: str, description: str) -> Dict[str, Any]:
    return {
        "requirement_code": code,
        "description": description,
        "materiality": "MATERIAL",
        "is_waivable": False,
    }


def _walk_to_bids_opened(solicitation_id: str) -> Dict[str, Any]:
    """Close the question period and publicly open the bids, at the two instants
    of the default procurement calendar."""
    fx.set_clock(QUESTION_DEADLINE_CLOCK)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_CLOCK)
    return fx.open_bids(solicitation_id)


def _review_responsibility(
    bid_id: str,
    financial_capacity_score: int,
    past_performance_score: int,
    integrity_score: int,
    determination: str,
    notes: str,
):
    """The raw responsibility-review response, so the caller can validate either
    a success or a rejection itself."""
    return api_client.create_responsibility_review(
        bid_id,
        fac.responsibility_review_payload(
            financial_capacity_score=financial_capacity_score,
            past_performance_score=past_performance_score,
            integrity_score=integrity_score,
            determination=determination,
            notes=notes,
        ),
        REVIEWER_HEADERS,
    )


def _suspended_bidder_on_a_high_value_solicitation() -> Dict[str, Any]:
    """A vendor whose bid is already on file and found RESPONSIVE on a
    600,000,000-cent procurement, and who has since been interim-suspended in a
    fraud proceeding so that it carries exactly one debarment strike. The bid was
    filed while the solicitation was still ISSUED, which is why the suspension
    fan-out never reached it."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Sandhurst Structures",
        tax_id="100000048",
        contact_email="v48@example.gov",
    )
    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-C16",
        title="Truss Bridge Superstructure Replacement",
        issuing_agency_code="DOT",
        estimated_value_cents=600000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[_requirement("REQ-WELD", "AWS certified welders")],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    bid = fx.submit_bid(solicitation_id, vendor["id"], total_price_cents=100000000)

    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="FRAUD",
        aggravating_factor_codes=["FRAUD"],
        mitigating_factor_codes=[],
        interim_suspension=True,
    )

    _walk_to_bids_opened(solicitation_id)
    fx.determine_responsiveness(
        bid["id"], headers=OFFICER_HEADERS, determination="RESPONSIVE", reason_codes=[]
    )

    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation_id,
        "bid_id": bid["id"],
        "proceeding_id": proceeding["id"],
    }


def _eligible_bidder_on_a_standard_solicitation(tax_id: str, number: str) -> Dict[str, Any]:
    """An ELIGIBLE vendor with no strikes whose single bid on a 10,000,000-cent
    procurement has been opened and found RESPONSIVE, so it is the apparent low
    bidder awaiting a responsibility review."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Tannery Row Electric",
        tax_id=tax_id,
        contact_email="v{}@example.gov".format(tax_id),
    )
    solicitation = fx.create_solicitation(
        solicitation_number=number,
        title="Traffic Signal Cabinet Retrofit",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[_requirement("REQ-IMSA", "IMSA level II technician")],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    bid = fx.submit_bid(solicitation_id, vendor["id"], total_price_cents=7500000)

    _walk_to_bids_opened(solicitation_id)
    fx.determine_responsiveness(
        bid["id"], headers=OFFICER_HEADERS, determination="RESPONSIVE", reason_codes=[]
    )

    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation_id,
        "bid_id": bid["id"],
    }


def _issued_solicitation_extended_by_five_days() -> str:
    """A live solicitation advertised for 2026-08-27 whose first addendum has
    already deferred the bid due date by five calendar days."""
    fx.reset_clock()
    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-C18",
        title="Guardrail End Treatment Upgrade",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[_requirement("REQ-MASH", "MASH tested terminal")],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    fx.add_addendum(
        solicitation["id"],
        summary="revised terminal detail sheet",
        extends_bid_due_by_days=5,
        acknowledgment_required=True,
        new_requirement_codes=[],
    )
    return solicitation["id"]


def _two_bids_opened_at_seven_and_nine_million() -> Dict[str, Any]:
    """One procurement whose public opening priced a 7,000,000-cent bid and a
    9,000,000-cent bid, each from its own vendor, the cheaper one filed first."""
    fx.reset_clock()
    vendor_a = fx.create_vendor(
        legal_name="Underhill Excavation",
        tax_id="100000050",
        contact_email="v50@example.gov",
    )
    vendor_b = fx.create_vendor(
        legal_name="Vantage Earthworks",
        tax_id="100000051",
        contact_email="v51@example.gov",
    )
    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-C19",
        title="Retention Basin Excavation",
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[_requirement("REQ-SPOIL", "spoil disposal site letter")],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])
    solicitation_id = solicitation["id"]

    bid_a = fx.submit_bid(solicitation_id, vendor_a["id"], total_price_cents=7000000)
    bid_b = fx.submit_bid(solicitation_id, vendor_b["id"], total_price_cents=9000000)

    solicitation = _walk_to_bids_opened(solicitation_id)

    return {
        "solicitation_id": solicitation_id,
        "solicitation": solicitation,
        "bid_a_id": bid_a["id"],
        "bid_b_id": bid_b["id"],
    }


def _twelve_month_debarment_ending_next_august() -> Dict[str, Any]:
    """A vendor debarred on 2026-08-16 for repeated nonperformance and an
    unabated safety citation, which is a severity of 35 and therefore the
    twelve-month tier."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name="Westerly Line Striping",
        tax_id="100000052",
        contact_email="v52@example.gov",
    )
    proceeding = fx.open_proceeding(
        vendor["id"],
        cause_code="REPEATED_NONPERFORMANCE",
        aggravating_factor_codes=["REPEATED_NONPERFORMANCE", "SAFETY_VIOLATION"],
        mitigating_factor_codes=[],
        interim_suspension=False,
    )
    fx.set_clock("2026-08-16T00:00:00Z")
    fx.hold_debarment_hearing(
        proceeding["id"],
        hearing_summary="no written response was filed within the response window",
    )
    proceeding = fx.decide_debarment(
        proceeding["id"],
        outcome="DEBARRED",
        rationale="three terminated contracts and an unabated safety citation",
    )
    return {
        "vendor_id": vendor["id"],
        "proceeding_id": proceeding["id"],
        "proceeding": proceeding,
    }


def _read_debarred_list(as_of_utc: str):
    return api_client.list_debarred_vendors(
        OFFICER_HEADERS, params={"as_of_utc": as_of_utc, "limit": 100, "offset": 0}
    )


def _protest_under_review(
    vendor_legal_name: str,
    tax_id: str,
    solicitation_number: str,
    title: str,
    requirement_code: str,
    requirement_description: str,
    question_text: str,
    narrative: str,
) -> Dict[str, Any]:
    """A prospective bidder who asked a written question and then protested the
    solicitation itself, with the agency report already filed so the protest is
    UNDER_REVIEW and a hearing may be put on the docket."""
    fx.reset_clock()
    vendor = fx.create_vendor(
        legal_name=vendor_legal_name,
        tax_id=tax_id,
        contact_email="v{}@example.gov".format(tax_id),
    )
    fx.fund_vendor(vendor["id"], 100000)

    solicitation = fx.create_solicitation(
        solicitation_number=solicitation_number,
        title=title,
        issuing_agency_code="DOT",
        estimated_value_cents=10000000,
        original_bid_due_utc=BID_DUE_CLOCK,
        original_question_deadline_utc=QUESTION_DEADLINE_CLOCK,
        mandatory_requirements=[
            _requirement(requirement_code, requirement_description)
        ],
    )
    solicitation = fx.issue_solicitation(solicitation["id"])

    fx.submit_question(solicitation["id"], vendor["id"], question_text=question_text)
    protest = fx.file_protest(
        solicitation["id"],
        vendor["id"],
        grounds_code="SOLICITATION_IMPROPRIETY",
        narrative=narrative,
    )
    fx.add_record_item(
        protest["id"], headers=OFFICER_HEADERS, item_type="AGENCY_REPORT"
    )

    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation["id"],
        "protest_id": protest["id"],
        "protest": protest,
    }


def _book_hearing(
    protest_id: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    room_code: str,
):
    return api_client.create_hearing(
        protest_id,
        fac.hearing_payload(
            HEARING_OFFICER_USER_ID,
            scheduled_start_utc=scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            room_code=room_code,
        ),
        HEARING_OFFICER_HEADERS,
    )


def _full_day_and_evening_dockets() -> Dict[str, Any]:
    """Two independent protests before the same hearing officer: the first
    already holds a hearing filling the whole of 2026-08-28, and the second has
    been refused an evening slot on that day for want of docket capacity."""
    matter_a = _protest_under_review(
        vendor_legal_name="Yarrowdale Milling",
        tax_id="100000053",
        solicitation_number="SOL-2238-C20",
        title="Cold In Place Recycling",
        requirement_code="REQ-CIR",
        requirement_description="cold in place recycling train",
        question_text="is a single-unit recycling train acceptable?",
        narrative="the train specification names one manufacturer",
    )
    matter_b = _protest_under_review(
        vendor_legal_name="Zephyr Bridge Coatings",
        tax_id="100000054",
        solicitation_number="SOL-2238-C21",
        title="Steel Girder Recoating",
        requirement_code="REQ-CONTAIN",
        requirement_description="class 1A containment",
        question_text="is full containment required over water?",
        narrative="the containment class is unattainable for this span",
    )

    hearing_a = validate_success(
        _book_hearing(
            matter_a["protest_id"],
            "2026-08-28T09:00:00Z",
            "2026-08-28T17:00:00Z",
            "ROOM-A",
        ),
        expected_status=201,
    )
    refusal = validate_error(
        _book_hearing(
            matter_b["protest_id"],
            "2026-08-28T18:00:00Z",
            "2026-08-28T19:00:00Z",
            "ROOM-B",
        ),
        ApiErrorId.ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED.value,
    )

    return {
        "matter_a": matter_a,
        "matter_b": matter_b,
        "hearing_a_id": hearing_a["id"],
        "refusal": refusal,
    }


# --------------------------------------------------------------------------
# The composite responsibility score
# --------------------------------------------------------------------------
class TestCompositeResponsibilityScore:
    def test_high_value_weights_and_one_strike_produce_the_composite(self):
        """Under the `HIGH_VALUE` profile, the emphasis shifts to the balance sheet: financial capacity carries five tenths, past performance three tenths, and integrity two tenths.

        An estimated value of 600,000,000 cents is above the high-value boundary,
        so 90 / 90 / 90 weights to 0.5*90 + 0.3*90 + 0.2*90 = 90.00 and the one
        strike the interim suspension attributed to the bidder subtracts seven
        points, leaving 83.00. The STANDARD profile, or the same weights with the
        strike ignored, would both have returned 90.00 instead.

        Design: Corner/calculations/corner_composite_score_high_value_profile_applies_the_strike_penalty
        """
        state = _suspended_bidder_on_a_high_value_solicitation()

        review = validate_success(
            _review_responsibility(
                state["bid_id"],
                financial_capacity_score=90,
                past_performance_score=90,
                integrity_score=90,
                determination="NONRESPONSIBLE",
                notes=(
                    "capacity is adequate but the vendor is under an active "
                    "integrity proceeding"
                ),
            ),
            expected_status=201,
        )

        assert review["weight_profile"] == "HIGH_VALUE"
        assert review["strike_penalty_points"] == pytest.approx(
            k.STRIKE_PENALTY_POINTS_PER_STRIKE, abs=0.01
        )
        assert review["composite_score"] == pytest.approx(83.00, abs=0.01)
        assert review["composite_score"] != pytest.approx(90.00, abs=0.01), (
            "the high-value weights and the strike penalty must both be applied"
        )
        assert review["determination"] == "NONRESPONSIBLE"

    def test_the_suspension_strike_is_counted_and_the_candidate_set_empties(self):
        """Because the ranking procedure excludes bids whose `responsibility_status` is `NONRESPONSIBLE`, the solicitation immediately recomputes `apparent_low_bid_id`, which now names the next-lowest eligible candidate or becomes null when none remains.

        The suspension that supplied the strike never touched the bid itself,
        because the solicitation was still open for bids when the notice issued;
        the bid therefore reaches the review as RESPONSIVE, and the adverse
        review is what empties the field.

        Design: Corner/calculations/corner_composite_score_high_value_profile_applies_the_strike_penalty
        """
        state = _suspended_bidder_on_a_high_value_solicitation()

        vendor = fx.read_vendor(state["vendor_id"])
        proceeding = fx.read_proceeding(state["proceeding_id"])
        assert vendor["eligibility_status"] == "SUSPENDED"
        assert vendor["debarment_strike_count"] == 1
        assert proceeding["strikes_applied"] == 1

        validate_success(
            _review_responsibility(
                state["bid_id"],
                financial_capacity_score=90,
                past_performance_score=90,
                integrity_score=90,
                determination="NONRESPONSIBLE",
                notes=(
                    "capacity is adequate but the vendor is under an active "
                    "integrity proceeding"
                ),
            ),
            expected_status=201,
        )

        bid = fx.read_bid(state["bid_id"])
        solicitation = fx.read_solicitation(state["solicitation_id"])

        assert bid["responsiveness_status"] == "RESPONSIVE"
        assert bid["responsibility_status"] == "NONRESPONSIBLE"
        assert solicitation["apparent_low_bid_id"] is None
        assert solicitation["status"] == "EVALUATION"

    def test_an_integrity_failure_caps_the_weighted_value_at_forty_nine(self):
        """If the reviewer's `integrity_score` is strictly below 40, the clamped value is further capped at 49 — which, being below the responsible threshold, makes a `RESPONSIBLE` determination arithmetically impossible for a bidder with an integrity failure no matter how strong its other factors.

        Scores of 80 / 85 / 38 weight to 0.3*80 + 0.4*85 + 0.3*38 = 69.40 under
        the STANDARD profile and carry no strike penalty, but the integrity score
        of 38 sits below the floor, so the recorded composite is 49.00 rather
        than the unclamped 69.40.

        Design: Corner/calculations/corner_composite_score_integrity_ceiling_clamps_the_weighted_value
        """
        state = _eligible_bidder_on_a_standard_solicitation("100000049", "SOL-2238-C17")

        review = validate_success(
            _review_responsibility(
                state["bid_id"],
                financial_capacity_score=80,
                past_performance_score=85,
                integrity_score=38,
                determination="NONRESPONSIBLE",
                notes="unresolved integrity findings",
            ),
            expected_status=201,
        )

        assert review["weight_profile"] == "STANDARD"
        assert review["strike_penalty_points"] == pytest.approx(0, abs=0.01)
        assert review["composite_score"] == pytest.approx(
            k.INTEGRITY_CEILING_SCORE, abs=0.01
        )
        assert review["composite_score"] != pytest.approx(69.40, abs=0.01), (
            "the weighted value must not pass through the integrity ceiling"
        )
        assert fx.read_bid(state["bid_id"])["responsibility_status"] == "NONRESPONSIBLE"

    def test_the_capped_score_cannot_support_a_responsible_determination(self):
        """For a `RESPONSIBLE` determination only, the bidding vendor's `eligibility_status` must be `ELIGIBLE`, else `ERR_VENDOR_NOT_ELIGIBLE`, and the computed `composite_score` must reach the responsible threshold of 60.00, else `ERR_RESPONSIBILITY_SCORE_BELOW_THRESHOLD` (HTTP 422).

        The same 80 / 85 / 38 factor scores are capped at 49.00 by the integrity
        ceiling, which is below the threshold, so the favourable determination is
        refused even though the bidder is eligible and the unclamped 69.40 would
        have cleared it.

        Design: Corner/calculations/corner_composite_score_integrity_ceiling_clamps_the_weighted_value
        """
        state = _eligible_bidder_on_a_standard_solicitation("100000149", "SOL-2238-C17B")

        error = validate_error(
            _review_responsibility(
                state["bid_id"],
                financial_capacity_score=80,
                past_performance_score=85,
                integrity_score=38,
                determination="RESPONSIBLE",
                notes="unresolved integrity findings",
            ),
            ApiErrorId.ERR_RESPONSIBILITY_SCORE_BELOW_THRESHOLD.value,
        )

        assert error["error_id"] == "ERR_RESPONSIBILITY_SCORE_BELOW_THRESHOLD"
        bid = fx.read_bid(state["bid_id"])
        assert bid["responsibility_status"] == "NOT_REVIEWED"
        assert fx.read_solicitation(state["solicitation_id"])["status"] == "EVALUATION"


# --------------------------------------------------------------------------
# The moving bid due date
# --------------------------------------------------------------------------
class TestEffectiveBidDueDate:
    def test_every_addendum_extension_is_summed_from_the_original_due_date(self):
        """The solicitation's `cumulative_extension_days` is recomputed as the sum of `extends_bid_due_by_days` over every addendum of that solicitation, with no status filter of any kind, evaluated in ascending sequence order; `addendum_count` is recomputed as the number of addendum rows on the solicitation; and `effective_bid_due_utc` is set to `original_bid_due_utc` plus that cumulative number of whole calendar days, preserving the original time of day.

        Five days and then three days accumulate to eight, so the bid due date
        moves from 2026-08-27 to 2026-09-04 while the originally advertised date
        is left untouched as the historical record.

        Design: Corner/calculations/corner_effective_bid_due_aggregates_every_addendum_extension
        """
        solicitation_id = _issued_solicitation_extended_by_five_days()

        addendum = validate_success(
            api_client.create_addendum(
                solicitation_id,
                fac.addendum_payload(
                    summary="clarified pay item units",
                    extends_bid_due_by_days=3,
                    acknowledgment_required=True,
                    new_requirement_codes=[],
                ),
                OFFICER_HEADERS,
            ),
            expected_status=201,
        )

        assert addendum["sequence_number"] == 2
        assert addendum["extends_bid_due_by_days"] == 3
        assert addendum["adds_material_requirement"] is False

        solicitation = fx.read_solicitation(solicitation_id)
        assert solicitation["addendum_count"] == 2
        assert solicitation["cumulative_extension_days"] == 8
        assert solicitation["effective_bid_due_utc"].startswith("2026-09-04T00:00:00")
        assert solicitation["original_bid_due_utc"].startswith("2026-08-27T00:00:00")
        assert solicitation["status"] == "ISSUED"

    def test_the_question_deadline_follows_the_new_bid_due_date_by_one_week(self):
        """If the solicitation is `ISSUED` and the addendum's `extends_bid_due_by_days` is strictly greater than zero, `question_deadline_utc` is recomputed as the new `effective_bid_due_utc` less one week.

        After the second extension the bid due date is 2026-09-04, so the
        question deadline is re-derived as 2026-08-28 and the intermediate
        2026-08-25 that followed the first addendum is superseded; the originally
        advertised deadline of 2026-08-20 is never mutated.

        Design: Corner/calculations/corner_effective_bid_due_aggregates_every_addendum_extension
        """
        solicitation_id = _issued_solicitation_extended_by_five_days()

        after_first = fx.read_solicitation(solicitation_id)
        assert after_first["question_deadline_utc"].startswith("2026-08-25T00:00:00")

        validate_success(
            api_client.create_addendum(
                solicitation_id,
                fac.addendum_payload(
                    summary="clarified pay item units",
                    extends_bid_due_by_days=3,
                    acknowledgment_required=True,
                    new_requirement_codes=[],
                ),
                OFFICER_HEADERS,
            ),
            expected_status=201,
        )

        solicitation = fx.read_solicitation(solicitation_id)
        assert solicitation["question_deadline_utc"].startswith("2026-08-28T00:00:00")
        assert solicitation["original_question_deadline_utc"].startswith(
            "2026-08-20T00:00:00"
        )
        assert solicitation["cumulative_extension_days"] == 8
        assert solicitation["effective_bid_due_utc"].startswith("2026-09-04T00:00:00")


# --------------------------------------------------------------------------
# The apparent low bidder
# --------------------------------------------------------------------------
class TestApparentLowBidderSelection:
    def test_the_public_opening_ranks_the_bids_at_their_as_read_prices(self):
        """Opening stamps `bids_opened_at_utc` from the logical clock, which becomes the trigger event for one flavour of protest timeliness, and prices every non-withdrawn bid under the **as-read variant** of the evaluated-price rule: each such bid's `evaluated_price_cents` is set to exactly its `total_price_cents`, and its `informality_loading_cents` is set to 0.

        The 7,000,000-cent bid and the 9,000,000-cent bid are priced exactly as
        read, so the cheaper of the two is the apparent low bidder the moment the
        bids are opened.

        Design: Corner/calculations/corner_apparent_low_bidder_excludes_a_nonresponsive_bid
        """
        state = _two_bids_opened_at_seven_and_nine_million()

        bid_a = fx.read_bid(state["bid_a_id"])
        bid_b = fx.read_bid(state["bid_b_id"])

        assert bid_a["evaluated_price_cents"] == 7000000
        assert bid_a["informality_loading_cents"] == 0
        assert bid_b["evaluated_price_cents"] == 9000000
        assert bid_b["informality_loading_cents"] == 0
        assert state["solicitation"]["apparent_low_bid_id"] == state["bid_a_id"]
        assert state["solicitation"]["status"] == "BIDS_OPENED"

    def test_a_nonresponsive_bid_leaves_the_candidate_set_without_being_repriced(self):
        """Withdrawn and nonresponsive bids are excluded permanently — they never re-enter the candidate set.

        Marking the cheaper 7,000,000-cent bid NONRESPONSIVE moves the apparent
        low bidder to the 9,000,000-cent bid, and the excluded row keeps its
        evaluated price of 7,000,000 cents, because the exclusion is by
        responsiveness status rather than by any re-pricing of the offer.

        Design: Corner/calculations/corner_apparent_low_bidder_excludes_a_nonresponsive_bid
        """
        state = _two_bids_opened_at_seven_and_nine_million()

        bid_a = validate_success(
            api_client.determine_responsiveness(
                state["bid_a_id"],
                fac.responsiveness_payload(
                    determination="NONRESPONSIVE",
                    reason_codes=["MATERIAL_REQUIREMENT_UNMET"],
                ),
                OFFICER_HEADERS,
            )
        )

        assert bid_a["responsiveness_status"] == "NONRESPONSIVE"
        assert bid_a["nonresponsive_reason_codes"] == ["MATERIAL_REQUIREMENT_UNMET"]
        assert bid_a["evaluated_price_cents"] == 7000000

        solicitation = fx.read_solicitation(state["solicitation_id"])
        assert solicitation["apparent_low_bid_id"] == state["bid_b_id"]
        assert solicitation["status"] == "EVALUATION"


# --------------------------------------------------------------------------
# The debarred-vendor list snapshot
# --------------------------------------------------------------------------
class TestDebarredVendorListSnapshot:
    def test_the_twelve_month_tier_fixes_the_debarment_end_instant(self):
        """The same convention gives `debarment_end_utc` as the start instant plus the full `debarment_period_months`.

        Repeated nonperformance and a safety violation aggregate to 35 points
        with no mitigation and no prior strike, which reads the twelve-month tier
        off the period table, so a debarment starting on 2026-08-16 ends on
        2027-08-16 at the same time of day.

        Design: Corner/calculations/corner_debarred_list_drops_a_debarment_whose_end_equals_as_of
        """
        state = _twelve_month_debarment_ending_next_august()
        proceeding = state["proceeding"]

        assert proceeding["severity_score"] == pytest.approx(35.00, abs=0.01)
        assert proceeding["mitigating_credit_points"] == pytest.approx(0, abs=0.01)
        assert proceeding["debarment_period_months"] == 12
        assert proceeding["debarment_start_utc"].startswith("2026-08-16T00:00:00")
        assert proceeding["debarment_end_utc"].startswith("2027-08-16T00:00:00")
        assert proceeding["status"] == "DEBARRED"

    def test_a_debarment_ending_exactly_at_the_as_of_instant_drops_off(self):
        """Within that status scope, a vendor appears only when its `active_debarment_id` is not null and the proceeding that identifier names either has a null `debarment_end_utc` or has a `debarment_end_utc` strictly greater than the as-of instant — a debarment whose end instant equals the as-of instant has expired and drops off the list.

        One second before the debarment ends the vendor is still on the public
        list; read at the end instant itself the list is empty, while the vendor
        row itself remains DEBARRED and still points at the proceeding, because
        the snapshot window is a reading of the list and not a reinstatement.

        Design: Corner/calculations/corner_debarred_list_drops_a_debarment_whose_end_equals_as_of
        """
        state = _twelve_month_debarment_ending_next_august()

        listed, listed_meta = validate_paginated(
            _read_debarred_list("2027-08-15T23:59:59Z")
        )
        assert [row["id"] for row in listed] == [state["vendor_id"]]
        assert listed_meta["total_count"] == 1

        expired, expired_meta = validate_paginated(
            _read_debarred_list("2027-08-16T00:00:00Z")
        )
        assert state["vendor_id"] not in [row["id"] for row in expired]
        assert expired_meta["total_count"] == 0
        assert expired_meta["has_more"] is False

        vendor = fx.read_vendor(state["vendor_id"])
        assert vendor["eligibility_status"] == "DEBARRED"
        assert vendor["active_debarment_id"] == state["proceeding_id"]


# --------------------------------------------------------------------------
# The hearing officer's daily docket
# --------------------------------------------------------------------------
class TestOfficerDailyDocketMinutes:
    def test_a_full_docket_refuses_a_further_booking_on_the_same_day(self):
        """The candidate's own window length in whole minutes is added to that sum, and if the total exceeds 480 minutes the request is refused with `ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED`.

        A hearing running from 09:00 to 17:00 on 2026-08-28 books the whole
        eight-hour allowance for that officer on that UTC day, so a further
        sixty-minute evening slot would total 540 minutes and is refused, leaving
        the second protest exactly where it was.

        Design: Corner/calculations/corner_docket_minutes_are_released_when_a_hearing_is_cancelled
        """
        state = _full_day_and_evening_dockets()

        assert state["refusal"]["error_id"] == "ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED"

        hearing_a = fx.read_hearing(state["hearing_a_id"])
        assert hearing_a["status"] == "SCHEDULED"

        protest_b = fx.read_protest(state["matter_b"]["protest_id"])
        assert protest_b["status"] == "UNDER_REVIEW"

    def test_cancelling_a_hearing_returns_its_minutes_to_the_docket(self):
        """Booked minutes are the sum, in whole minutes, of the window lengths of every other hearing sharing the candidate's `hearing_officer_user_id` whose `status` is `SCHEDULED` or `CONVENED` and whose `scheduled_start_utc` falls inside that day window; hearings in `CONCLUDED` or `CANCELLED` release their minutes and are not counted.

        Withdrawing the first protest cancels its eight-hour hearing, which takes
        all 480 of its minutes out of the officer's booked total for
        2026-08-28, so the identical evening booking that was refused a moment
        earlier now succeeds.

        Design: Corner/calculations/corner_docket_minutes_are_released_when_a_hearing_is_cancelled
        """
        state = _full_day_and_evening_dockets()

        fx.withdraw_protest(
            state["matter_a"]["protest_id"],
            state["matter_a"]["vendor_id"],
            withdrawal_reason="the agency answered the question by addendum",
        )
        assert fx.read_hearing(state["hearing_a_id"])["status"] == "CANCELLED"

        hearing_b = validate_success(
            _book_hearing(
                state["matter_b"]["protest_id"],
                "2026-08-28T18:00:00Z",
                "2026-08-28T19:00:00Z",
                "ROOM-B",
            ),
            expected_status=201,
        )

        assert hearing_b["status"] == "SCHEDULED"
        assert hearing_b["scheduled_start_utc"].startswith("2026-08-28T18:00:00")
        assert hearing_b["scheduled_end_utc"].startswith("2026-08-28T19:00:00")
        assert hearing_b["continuance_count"] == 0

        assert fx.read_protest(state["matter_b"]["protest_id"])["status"] == (
            "HEARING_SCHEDULED"
        )
        protest_a = fx.read_protest(state["matter_a"]["protest_id"])
        assert protest_a["status"] == "WITHDRAWN"
        assert protest_a["fee_refunded_cents"] == 35638
