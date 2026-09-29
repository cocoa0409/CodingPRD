"""The two statutory deadline variants a hold computes from one anchor.

A hold freezes four instants at initiation. Two of them share an anchor and an
offset but run on different calendars, so the same 72-hour hold can lapse on a
Sunday afternoon while its court paperwork is not due until the Tuesday after a
holiday Monday.
"""

from test_helpers import (
    HoldStatus,
    STATUTORY_HOURS_EMERGENCY_72H,
    assert_hold,
    assert_millisecond_instant,
    create_hold,
    involuntary_case,
    read_hold,
    set_clock,
)

#: The anchor the PRD works through, chosen so the two variants disagree.
DIVERGENT_SIGNATURE = "2026-09-03T14:30:00Z"

#: An anchor whose raw 72-hour instant already sits inside a court window.
COINCIDENT_SIGNATURE = "2026-09-01T10:00:00Z"


def _hold_on(api, roster, mrn, legal_name, age_years, gender, signed_at):
    """Sign an evaluation at ``signed_at`` and file an emergency hold from it."""
    case = involuntary_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender,
        danger_to_self=True,
        signed_at_clock=signed_at,
    )
    hold = create_hold(
        api,
        roster.intake_headers,
        case["patient"]["id"],
        case["evaluation"]["id"],
    )
    return case, hold


class TestHoldDeadlineVariants:
    """One anchor, two calendars, two deadlines that routinely disagree."""

    def test_release_and_filing_deadlines_diverge_across_a_weekend_and_holiday(
        self, api, clock, roster
    ):
        """A Sunday lapse rolls to the Tuesday after a holiday Monday for filing.

        PRD 3.3: "The divergence between the two variants is the point: an anchor
        of `2026-09-03T14:30:00Z` on a 72-hour hold yields a
        `release_deadline_at` of `2026-09-06T14:30:00.000Z` — a Sunday — while
        the same inputs yield a `petition_filing_deadline_at` of
        `2026-09-08T09:00:00.000Z`, because Sunday rolls to Monday and Monday the
        7th is a recognized holiday."

        Design: Difficulty/dual_variant_calc/hold_deadline_calendar_vs_judicial_day_variants_diverge
        """
        set_clock(api, "2026-09-01T10:00:00Z")
        _, hold = _hold_on(
            api,
            roster,
            "MRN-2367-A",
            "Dana Whitlock",
            34,
            "FEMALE",
            DIVERGENT_SIGNATURE,
        )

        stored = read_hold(api, hold["id"])
        assert_hold(stored)
        assert stored["release_deadline_at"] == "2026-09-06T14:30:00.000Z"
        assert stored["petition_filing_deadline_at"] == "2026-09-08T09:00:00.000Z"
        assert stored["release_deadline_at"] != stored["petition_filing_deadline_at"]

    def test_both_deadlines_coincide_when_the_raw_instant_lands_in_a_court_window(
        self, api, clock, roster
    ):
        """No roll happens when the wall-clock instant is already a judicial one.

        PRD 3.3: "The roll is applied repeatedly: if the candidate's date is a
        Saturday, a Sunday or one of the recognized holidays, the candidate
        becomes the following day at `09:00:00.000Z` and the test restarts;
        otherwise, if the candidate's time of day is earlier than 09:00:00 it
        becomes that same date at `09:00:00.000Z` and the test restarts;
        otherwise, if its time of day is later than 16:00:00 it becomes the
        following day at `09:00:00.000Z` and the test restarts; when none of the
        three applies, that candidate is the filing deadline."

        Design: Difficulty/dual_variant_calc/hold_deadline_calendar_vs_judicial_day_variants_diverge
        """
        _, hold = _hold_on(
            api,
            roster,
            "MRN-2367-B",
            "Perry Vale",
            41,
            "MALE",
            COINCIDENT_SIGNATURE,
        )

        stored = read_hold(api, hold["id"])
        assert stored["release_deadline_at"] == "2026-09-04T10:00:00.000Z"
        assert stored["petition_filing_deadline_at"] == "2026-09-04T10:00:00.000Z"
        assert stored["release_deadline_at"] == stored["petition_filing_deadline_at"]

    def test_frozen_instants_anchor_on_the_evaluation_signature_not_the_hold_row(
        self, api, clock, roster
    ):
        """The anchor is the signature instant, and certification is anchor plus four hours.

        PRD 3.3: "`clock_started_at` is the statutory anchor and is emphatically
        *not* the hold row's own creation timestamp: for an `EMERGENCY_72H` hold
        it is the anchoring evaluation's `signed_at`, and for an `EXTENSION_14D`
        successor it is the predecessor hold's `release_deadline_at`."

        Design: Difficulty/dual_variant_calc/hold_deadline_calendar_vs_judicial_day_variants_diverge
        """
        case, hold = _hold_on(
            api,
            roster,
            "MRN-2367-A2",
            "Dana Whitlock",
            34,
            "FEMALE",
            DIVERGENT_SIGNATURE,
        )
        # The hold row itself is written a moment later in the same clock reading,
        # so only the signature can explain the anchor.
        set_clock(api, "2026-09-03T20:00:00Z")

        stored = read_hold(api, hold["id"])
        assert stored["statutory_hours"] == STATUTORY_HOURS_EMERGENCY_72H
        assert stored["clock_started_at"] == "2026-09-03T14:30:00.000Z"
        assert stored["clock_started_at"] == case["evaluation"]["signed_at"]
        assert stored["certification_deadline_at"] == "2026-09-03T18:30:00.000Z"
        assert stored["status"] == HoldStatus.PENDING_CERTIFICATION.value
        for field_name in (
            "clock_started_at",
            "certification_deadline_at",
            "release_deadline_at",
            "petition_filing_deadline_at",
        ):
            assert_millisecond_instant(stored[field_name], field_name)
