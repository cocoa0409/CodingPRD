"""The adherence chain: the strict coaching edge and the three-hop excusal cascade."""

from test_helpers.assertions import (
    assert_agent_coaching,
    assert_shift_adherence,
    assert_shift_axes,
)
from test_helpers.constants import (
    ADHERENCE_EXCUSED,
    ADHERENCE_ON_TRACK,
    ADHERENCE_OUT_OF_ADHERENCE,
    COACHING_ACTIVE,
    COACHING_CLEARED,
    COACHING_NONE,
    EXCEPTION_STATUS_APPROVED,
)
from test_helpers.fixtures import (
    build_exception_case,
    build_published_week,
    decide_exception,
    read_agent,
    read_exception,
    read_shift,
    record_observation,
)
from test_helpers.test_users import COACH_USER_ID


class TestCoachingThresholdBoundary:
    """The 0.8500 coaching comparison is strict."""

    def test_a_score_of_exactly_the_threshold_lands_on_track(self, api):
        """4050 non-adherent seconds of 27000 score exactly 0.8500 and are not flagged.

        "The comparison is strict, so a score of exactly 0.8500 is on track and is
        **not** flagged."

        Design: Difficulty/boundary_precision_check/adherence_threshold_exactly_85_not_flagged
        """
        world = build_published_week(api)
        assert world["shift"]["scheduled_seconds"] == 27000

        observed = record_observation(api, world["shift"]["id"], 4050)

        assert_shift_adherence(observed, adherence_pct=0.8500)
        assert_shift_axes(observed, adherence_status=ADHERENCE_ON_TRACK)

    def test_the_boundary_observation_raises_no_coaching_flag(self, api):
        """An on-track shift leaves the agent's flag count at zero and the ratchet untouched.

        "`coaching_flag_count` counts the agent's scored shifts that are
        **flagged**, where a shift is flagged when its `publication_status` is
        `PUBLISHED`, its `adherence_status` is `OUT_OF_ADHERENCE` and its own
        `adherence_pct` is strictly below 0.8500."

        Design: Difficulty/boundary_precision_check/adherence_threshold_exactly_85_not_flagged
        """
        world = build_published_week(api)

        record_observation(api, world["shift"]["id"], 4050)

        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            coaching_flag_count=0,
            coaching_status=COACHING_NONE,
        )

    def test_fifty_seconds_past_the_boundary_flips_the_axis_and_flags(self, api):
        """4100 non-adherent seconds score 0.8481 and move the shift out of adherence.

        "A resulting `adherence_pct` strictly below 0.8500 moves the axis to
        `OUT_OF_ADHERENCE`: from `PENDING → OUT_OF_ADHERENCE` on a first
        observation, from `ON_TRACK → OUT_OF_ADHERENCE` when a worse observation
        arrives, or from `EXCUSED → OUT_OF_ADHERENCE` when a fresh observation
        lands below the threshold again."

        Design: Difficulty/boundary_precision_check/adherence_threshold_exactly_85_not_flagged
        """
        world = build_published_week(api)
        record_observation(api, world["shift"]["id"], 4050)

        worse = record_observation(api, world["shift"]["id"], 4100)

        assert_shift_adherence(worse, adherence_pct=0.8481)
        assert_shift_axes(worse, adherence_status=ADHERENCE_OUT_OF_ADHERENCE)

    def test_crossing_the_boundary_starts_the_coaching_ratchet(self, api):
        """The flagged shift lifts the agent to one flag and an active coaching status.

        "`coaching_status` then follows a simple ratchet: it is `NONE` until the
        agent has ever been flagged, `COACHING_ACTIVE` while `coaching_flag_count`
        is 1 or more, and `CLEARED` when the count falls back to zero having
        previously been `COACHING_ACTIVE`."

        Design: Difficulty/boundary_precision_check/adherence_threshold_exactly_85_not_flagged
        """
        world = build_published_week(api)
        record_observation(api, world["shift"]["id"], 4050)

        record_observation(api, world["shift"]["id"], 4100)

        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            adherence_pct=0.8481,
            coaching_flag_count=1,
            coaching_status=COACHING_ACTIVE,
        )


class TestExceptionApprovalCascade:
    """One approval travels from the exception to the agent's coaching ratchet."""

    def test_approval_moves_the_shift_adherence_axis_to_excused(self, api):
        """The approved excusal takes the shift from out of adherence to excused.

        "Approval stamps `decided_by_user_id` with the deciding coach's identifier,
        then reaches across into the shift and moves its adherence axis
        `OUT_OF_ADHERENCE → EXCUSED`, adding the exception's `duration_seconds` to
        the shift's `excused_seconds`."

        Design: Difficulty/transitive_cascade/exception_approval_three_hop_coaching_clear
        """
        world = build_exception_case(
            api, out_of_adherence_seconds=4100, duration_seconds=4100
        )

        decide_exception(api, world["exception"]["id"])

        approved = read_exception(api, world["exception"]["id"])
        assert approved["status"] == EXCEPTION_STATUS_APPROVED
        assert approved["decided_by_user_id"] == COACH_USER_ID
        shift = read_shift(api, world["shift"]["id"])
        assert_shift_axes(shift, adherence_status=ADHERENCE_EXCUSED)
        assert_shift_adherence(shift, excused_seconds=4100)

    def test_approval_rescores_the_shift_back_to_a_perfect_hour(self, api):
        """Excusing every charged second restores the shift's own score to 1.0000.

        "That in turn recomputes the shift's `adherence_pct`, then the agent's
        `adherence_pct`, `coaching_flag_count` and `coaching_status` — so an
        approval on one entity can clear a coaching ratchet three hops away,
        setting `coaching_status` to `CLEARED` when the flag count falls to zero
        from `COACHING_ACTIVE`."

        Design: Difficulty/transitive_cascade/exception_approval_three_hop_coaching_clear
        """
        world = build_exception_case(
            api, out_of_adherence_seconds=4100, duration_seconds=4100
        )
        assert_shift_adherence(
            read_shift(api, world["shift"]["id"]), adherence_pct=0.8481
        )

        decide_exception(api, world["exception"]["id"])

        assert_shift_adherence(
            read_shift(api, world["shift"]["id"]), adherence_pct=1.0000
        )

    def test_approval_clears_the_agent_coaching_ratchet(self, api):
        """The agent's rollup returns to 1.0000 and the ratchet walks to CLEARED.

        "`coaching_status` then follows a simple ratchet: it is `NONE` until the
        agent has ever been flagged, `COACHING_ACTIVE` while `coaching_flag_count`
        is 1 or more, and `CLEARED` when the count falls back to zero having
        previously been `COACHING_ACTIVE`."

        Design: Difficulty/transitive_cascade/exception_approval_three_hop_coaching_clear
        """
        world = build_exception_case(
            api, out_of_adherence_seconds=4100, duration_seconds=4100
        )
        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            coaching_flag_count=1,
            coaching_status=COACHING_ACTIVE,
        )

        decide_exception(api, world["exception"]["id"])

        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            adherence_pct=1.0000,
            coaching_flag_count=0,
            coaching_status=COACHING_CLEARED,
        )
