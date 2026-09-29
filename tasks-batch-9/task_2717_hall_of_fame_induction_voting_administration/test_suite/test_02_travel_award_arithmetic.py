"""Travel award arithmetic: variants, tiers, per-traveller rounding, reversal."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    OMIT,
    build_election_world,
    read_cycle,
    read_grant,
    read_induction,
    refresh_cycle,
    request_travel_grant,
    approve_travel_grant,
    setup_artifact_intake,
)

ESCORT_FROM = "2026-11-14T00:00:00Z"
ESCORT_TO = "2026-11-16T00:00:00Z"

POSTHUMOUS_RULES = [{}, {"pathway": "POSTHUMOUS"}]

MIXED_CANDIDATES = [
    {
        "full_name": "Living Inductee",
        "retirement_year": 2018,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Late Inductee",
        "retirement_year": 2015,
        "career_seasons": 14,
        "career_metric_value": 2800,
        "is_deceased": True,
        "death_year": 2020,
    },
    {
        "full_name": "Also Ran One",
        "retirement_year": 2016,
        "career_seasons": 13,
        "career_metric_value": 2600,
    },
    {
        "full_name": "Also Ran Two",
        "retirement_year": 2014,
        "career_seasons": 12,
        "career_metric_value": 2400,
    },
]

MIXED_NOMINATIONS = [
    {"candidate_index": 0, "pathway": "MODERN"},
    {"candidate_index": 1, "pathway": "POSTHUMOUS"},
    {"candidate_index": 2, "pathway": "MODERN"},
    {"candidate_index": 3, "pathway": "MODERN"},
]


def build_two_inductee_ceremony(api):
    """A CEREMONY_PLANNED cycle holding one living and one posthumous induction."""
    return build_election_world(
        api,
        stage="ceremony",
        rules=POSTHUMOUS_RULES,
        elector_count=4,
        candidate_specs=MIXED_CANDIDATES,
        nominations=MIXED_NOMINATIONS,
        votes=[(index, [0, 1]) for index in range(4)],
    )


def living_induction(world):
    return world["inductions"][world["candidacies"][0]["id"]]


def posthumous_induction(world):
    return world["inductions"][world["candidacies"][1]["id"]]


class TestLivingVersusPosthumousAward:
    """Two identical request bodies, two different delegation variants."""

    @pytest.fixture
    def grants(self, api):
        """One living and one posthumous grant, both three nights at a 120,000 airfare."""
        world = build_two_inductee_ceremony(api)
        living = request_travel_grant(
            world,
            living_induction(world)["id"],
            nights=3,
            requested_airfare_cents=120000,
        )
        posthumous = request_travel_grant(
            world,
            posthumous_induction(world)["id"],
            nights=3,
            requested_airfare_cents=120000,
            escort_from=ESCORT_FROM,
            escort_to=ESCORT_TO,
        )
        return world, living, posthumous

    def test_living_grant_funds_one_traveller_at_the_full_per_diem(self, grants):
        """The nightly per-diem allowance is 18,333 cents — one hundred eighty-three dollars and
        thirty-three cents a night — and one traveller's per-diem is that allowance multiplied
        by `nights`, multiplied by the tier's spending factor, multiplied by the variant's
        per-diem factor, then rounded half-up to whole cents.

        Design: Difficulty/dual_variant_calc/travel_award_living_vs_posthumous_delegation
        """
        _, living, _ = grants
        assert living["variant"] == "LIVING_INDUCTEE"
        assert living["traveler_count"] == 1
        assert living["award_cents"] == 149999
        assert living["status"] == "REQUESTED"

    def test_posthumous_grant_funds_two_travellers_at_three_quarter_per_diem(self, grants):
        """A `POSTHUMOUS_DELEGATION` grant funds two travellers — the delegation that accepts on
        the inductee's behalf — at a per-diem factor of three quarters.

        Design: Difficulty/dual_variant_calc/travel_award_living_vs_posthumous_delegation
        """
        _, _, posthumous = grants
        assert posthumous["variant"] == "POSTHUMOUS_DELEGATION"
        assert posthumous["traveler_count"] == 2
        assert posthumous["award_cents"] == 272498

    def test_the_two_variants_diverge_by_exactly_the_delegation_uplift(self, grants):
        """Those two figures are added to give one traveller's total, and `award_cents` is that
        per-traveller total multiplied by `traveler_count`.

        Design: Difficulty/dual_variant_calc/travel_award_living_vs_posthumous_delegation
        """
        _, living, posthumous = grants
        assert posthumous["award_cents"] - living["award_cents"] == 122499

    def test_airfare_above_the_cap_is_absorbed_per_traveller(self, grants):
        """One traveller's airfare is the lesser of `requested_airfare_cents` and the airfare cap
        of 95,000 cents, so a nine-hundred-fifty-dollar cap silently absorbs any larger request.

        Design: Difficulty/dual_variant_calc/travel_award_living_vs_posthumous_delegation
        """
        _, living, posthumous = grants
        assert living["requested_airfare_cents"] == 120000
        assert posthumous["requested_airfare_cents"] == 120000
        # The capped airfare, not the requested figure, is what each award carries.
        assert living["award_cents"] - 18333 * 3 == 95000
        assert posthumous["award_cents"] // 2 == 41249 + 95000

    def test_merely_requested_grants_commit_nothing_and_keep_the_full_tier(self, api, grants):
        """Only grants already in `APPROVED` status contribute to `travel_committed_cents`;
        grants sitting in `REQUESTED`, `DENIED` or `CANCELLED` contribute nothing, so the tier
        reflects committed money rather than pending intent.

        Design: Difficulty/dual_variant_calc/travel_award_living_vs_posthumous_delegation
        """
        world, living, posthumous = grants
        assert living["austerity_tier_applied"] == "FULL"
        assert posthumous["austerity_tier_applied"] == "FULL"
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 0
        assert cycle["austerity_tier"] == "FULL"


class TestPerTravellerRounding:
    """A long living grant tips the cycle into REDUCED and exposes the rounding order."""

    @pytest.fixture
    def world(self, api):
        """A 23-night living grant at the airfare cap, approved."""
        world = build_two_inductee_ceremony(api)
        grant = request_travel_grant(
            world,
            living_induction(world)["id"],
            nights=23,
            requested_airfare_cents=95000,
        )
        assert grant["award_cents"] == 516659
        approve_travel_grant(world, grant["id"])
        world["first_grant"] = grant
        return world

    def test_approval_recomputes_the_austerity_tier_from_the_new_ratio(self, api, world):
        """Approval then increases the cycle's `travel_committed_cents` by `award_cents`, which
        recomputes the cycle's `austerity_tier` from the new ratio and increments the cycle's
        `version` by 1; drives the induction's `travel_status` `REQUESTED` → `APPROVED`, which
        recomputes that induction's `ceremony_ready` and, when readiness flips to true,
        increments the cycle's `ceremony_ready_count` by 1; and occupies the escort interval
        for posthumous delegations.

        Design: Difficulty/combinatorial_formula/per_diem_rounded_per_traveler_then_summed
        """
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 516659
        assert cycle["austerity_tier"] == "REDUCED"

    def test_posthumous_per_diem_rounds_per_traveller_before_multiplying(self, world):
        """A three-night posthumous grant at the `REDUCED` tier illustrates it: each traveller's
        raw per-diem is 32,999.4 cents, which rounds to 32,999 cents per traveller and
        therefore 65,998 cents for the pair, whereas summing first and rounding once would give
        65,999.

        Design: Difficulty/combinatorial_formula/per_diem_rounded_per_traveler_then_summed
        """
        grant = request_travel_grant(
            world,
            posthumous_induction(world)["id"],
            nights=3,
            requested_airfare_cents=0,
            escort_from=ESCORT_FROM,
            escort_to=ESCORT_TO,
        )
        assert grant["traveler_count"] == 2
        assert grant["award_cents"] == 65998
        assert grant["award_cents"] != 65999

    def test_the_tier_read_at_creation_is_frozen_on_the_grant(self, api, world):
        """That tier is written onto the grant as `austerity_tier_applied` and never revisited.

        Design: Difficulty/combinatorial_formula/per_diem_rounded_per_traveler_then_summed
        """
        grant = request_travel_grant(
            world,
            posthumous_induction(world)["id"],
            nights=3,
            requested_airfare_cents=0,
            escort_from=ESCORT_FROM,
            escort_to=ESCORT_TO,
        )
        assert grant["austerity_tier_applied"] == "REDUCED"
        assert read_grant(api, world["first_grant"]["id"])["austerity_tier_applied"] == "FULL"


class TestGrantCancellationRestoresCommitment:
    """Cancelling an approved grant is a true compensating reversal."""

    @pytest.fixture
    def world(self, api):
        """One artifact-exempt, travel-approved induction that is ceremony-ready."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=4,
            candidate_count=2,
            votes=[(index, [0]) for index in range(4)],
        )
        induction = world["inductions"][world["candidacies"][0]["id"]]
        setup_artifact_intake(api, induction["id"], artifact_count=OMIT, is_exempt=True)
        grant = request_travel_grant(
            world, induction["id"], nights=23, requested_airfare_cents=95000
        )
        approve_travel_grant(world, grant["id"])
        world["grant"] = grant
        world["induction"] = induction
        return world

    def test_approved_grant_makes_the_induction_ceremony_ready(self, api, world):
        """Concretely: `travel_status` must be either `APPROVED` or `WAIVED`; and either
        `artifact_status` is `RECEIVED` with `exhibit_status` at `INSTALLED`, or
        `artifact_status` is `EXEMPT` — an exempt induction has nothing to display and is ready
        without any installation.

        Design: Difficulty/compensating_invariant/travel_commitment_restored_exactly_on_grant_cancellation
        """
        induction = read_induction(api, world["induction"]["id"])
        assert induction["travel_status"] == "APPROVED"
        assert induction["artifact_status"] == "EXEMPT"
        assert induction["ceremony_ready"] is True
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["ceremony_ready_count"] == 1
        assert cycle["travel_committed_cents"] == 516659
        assert cycle["austerity_tier"] == "REDUCED"

    def test_cancellation_restores_the_committed_total_exactly(self, api, world):
        """The cycle's `travel_committed_cents` decreases by exactly this grant's `award_cents`,
        restoring the pre-approval budget position precisely, and that decrease recomputes the
        cycle's `austerity_tier` and increments the cycle's `version` by 1.

        Design: Difficulty/compensating_invariant/travel_commitment_restored_exactly_on_grant_cancellation
        """
        api.cancel_travel_grant(
            world["grant"]["id"], {"cancellation_reason": "Inductee declined"}, ADMIN_HEADERS
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 0
        assert cycle["austerity_tier"] == "FULL"

    def test_cancellation_returns_the_induction_to_pending_and_drops_readiness(self, api, world):
        """The induction's `travel_status` moves `APPROVED` → `PENDING`, which recomputes
        `ceremony_ready` and, when readiness flips from true to false, decrements the cycle's
        `ceremony_ready_count` by 1.

        Design: Difficulty/compensating_invariant/travel_commitment_restored_exactly_on_grant_cancellation
        """
        api.cancel_travel_grant(
            world["grant"]["id"], {"cancellation_reason": "Inductee declined"}, ADMIN_HEADERS
        )
        induction = read_induction(api, world["induction"]["id"])
        assert induction["travel_status"] == "PENDING"
        assert induction["ceremony_ready"] is False
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 0

    def test_the_cancelled_grant_keeps_its_frozen_award(self, api, world):
        """`award_cents` is computed once, at creation, and frozen; approval never recomputes it.

        Design: Difficulty/compensating_invariant/travel_commitment_restored_exactly_on_grant_cancellation
        """
        api.cancel_travel_grant(
            world["grant"]["id"], {"cancellation_reason": "Inductee declined"}, ADMIN_HEADERS
        )
        grant = read_grant(api, world["grant"]["id"])
        assert grant["status"] == "CANCELLED"
        assert grant["award_cents"] == 516659

    def test_a_fresh_grant_may_be_requested_at_the_restored_tier(self, api, world):
        """Note that returning the induction to `PENDING` rather than `REQUESTED` is what allows
        a fresh grant to be requested for that inductee at the current tier.

        Design: Difficulty/compensating_invariant/travel_commitment_restored_exactly_on_grant_cancellation
        """
        api.cancel_travel_grant(
            world["grant"]["id"], {"cancellation_reason": "Inductee declined"}, ADMIN_HEADERS
        )
        refresh_cycle(world)
        replacement = request_travel_grant(
            world, world["induction"]["id"], nights=23, requested_airfare_cents=95000
        )
        assert replacement["austerity_tier_applied"] == "FULL"
        assert replacement["award_cents"] == 516659
