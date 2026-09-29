"""Audit planning across methodologies, and the seed ceremony's canvass precondition."""

import pytest

from test_helpers import ApiErrorId, api_client, assertions, constants, factories, fixtures
from test_helpers import validate_error, validate_success
from test_helpers.test_users import TEST_USERS

AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
DIRECTOR = TEST_USERS["elections_director_headers"]


def _plan(contest_id, payload):
    return api_client.create_audit({"contest_id": contest_id, **payload}, AUDIT_MANAGER)


class TestSampleSizingAcrossConfigurations:
    """One canvassed contest sized four different ways."""

    @pytest.mark.parametrize(
        "config, expected_sample_size",
        [
            ({"audit_type": "RISK_LIMITING", "risk_limit_alpha": 0.05}, 3),
            ({"audit_type": "RISK_LIMITING", "risk_limit_alpha": 0.01}, 4),
            (
                {
                    "audit_type": "COMPARISON",
                    "risk_limit_alpha": 0.05,
                    "prior_error_rate": 0.10,
                },
                2,
            ),
            ({"audit_type": "FIXED_PERCENTAGE", "fixed_percentage_pct": 5}, 2),
        ],
        ids=["rla_alpha_05", "rla_alpha_01", "comparison_alpha_05", "fixed_five_pct"],
    )
    def test_planned_sample_size_per_methodology_and_alpha(
        self, config, expected_sample_size
    ):
        """PRD §3.3: "`planned_sample_size` is then the smaller of the total batch count
        and the larger of two and the raw batch requirement — a floor of two batches,
        applied before the ceiling of the whole pool, so an audit never asks for fewer
        than two batches and never asks for more batches than the contest has."

        Design: Difficulty/combinatorial_formula/combinatorial_sample_size_four_configurations_one_contest
        """
        scenario = fixtures.setup_canvassed_contest()
        assert scenario["contest"]["margin_votes"] == 300
        assert scenario["contest"]["ballots_cast"] == 6000

        audit = validate_success(_plan(scenario["contest"]["id"], config), 201)
        assertions.assert_audit(audit)
        assert audit["planned_sample_size"] == expected_sample_size
        assert audit["status"] == "PLANNED"

    def test_measure_variant_is_derived_from_the_methodology(self):
        """PRD §3.3: "risk-limiting and fixed-percentage audits take the variant
        `NET_MARGIN_SHIFT`, while comparison audits take `MAX_RELATIVE_OVERSTATEMENT`."

        Design: Difficulty/combinatorial_formula/combinatorial_sample_size_four_configurations_one_contest
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]

        risk_limiting = validate_success(
            _plan(contest_id, {"audit_type": "RISK_LIMITING", "risk_limit_alpha": 0.05}),
            201,
        )
        comparison = validate_success(
            _plan(
                contest_id,
                {
                    "audit_type": "COMPARISON",
                    "risk_limit_alpha": 0.05,
                    "prior_error_rate": 0.10,
                },
            ),
            201,
        )
        fixed = validate_success(
            _plan(
                contest_id,
                {"audit_type": "FIXED_PERCENTAGE", "fixed_percentage_pct": 5},
            ),
            201,
        )

        assert risk_limiting["measure_variant"] == "NET_MARGIN_SHIFT"
        assert comparison["measure_variant"] == "MAX_RELATIVE_OVERSTATEMENT"
        assert fixed["measure_variant"] == "NET_MARGIN_SHIFT"
        assert risk_limiting["risk_limit_alpha"] == pytest.approx(0.05, abs=0.00005)
        assert fixed["risk_limit_alpha"] is None
        assert fixed["fixed_percentage_pct"] == pytest.approx(5, abs=0.00005)
        assert risk_limiting["fixed_percentage_pct"] is None

    def test_four_configurations_coexist_unseeded_on_one_contest(self):
        """PRD §3.3: "A newly planned audit is `PLANNED` with `escalation_level` zero,
        `random_seed` and `seed_published_at` null, `cumulative_sampled_batches`,
        `counted_ballots` and `cumulative_net_error_votes` zero, `discrepancy_measure`
        zero, `sample_size_stale` false, `public_report_published` false,
        `terminated_reason` null and `extension_days_granted` zero."

        Design: Difficulty/combinatorial_formula/combinatorial_sample_size_four_configurations_one_contest
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]
        configs = [
            {"audit_type": "RISK_LIMITING", "risk_limit_alpha": 0.05},
            {"audit_type": "RISK_LIMITING", "risk_limit_alpha": 0.01},
            {
                "audit_type": "COMPARISON",
                "risk_limit_alpha": 0.05,
                "prior_error_rate": 0.10,
            },
            {"audit_type": "FIXED_PERCENTAGE", "fixed_percentage_pct": 5},
        ]

        planned = [validate_success(_plan(contest_id, cfg), 201) for cfg in configs]

        for audit in planned:
            assert audit["status"] == "PLANNED"
            assert audit["random_seed"] is None
            assert audit["seed_published_at"] is None
            assert audit["escalation_level"] == 0
            assert audit["cumulative_sampled_batches"] == 0
            assert audit["counted_ballots"] == 0
            assert audit["cumulative_net_error_votes"] == 0
            assert audit["discrepancy_measure"] == pytest.approx(0.0, abs=0.00005)
            assert audit["sample_size_stale"] is False
            assert audit["public_report_published"] is False
            assert audit["extension_days_granted"] == 0
        assert [audit["planned_sample_size"] for audit in planned] == [3, 4, 2, 2]
        assert fixtures.read_election(scenario["election"]["id"])["open_audit_count"] == 4


class TestSeedCeremonyRequiresCanvassedContest:
    """The ceremony reads the contest's margin, so the contest must be canvassed."""

    def test_seed_ceremony_before_the_canvass_is_refused(self):
        """PRD §2.9: "The parent contest is `CANVASSED` — otherwise
        `ERR_CONTEST_NOT_CANVASSED`. Applies to the seed ceremony and to recount filing;
        a contest still awaiting canvass has no margin to size a sample or price a
        recount against."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_seed_requires_canvassed_contest
        """
        scenario = fixtures.setup_election_with_contest_and_batches()
        assert scenario["contest"]["status"] == "PENDING_CANVASS"
        audit = fixtures.create_audit(scenario["contest"]["id"])
        assert audit["planned_sample_size"] is None

        response = api_client.seed_audit(
            audit["id"], factories.seed_audit_payload(), AUDIT_MANAGER
        )

        validate_error(response, ApiErrorId.ERR_CONTEST_NOT_CANVASSED.value, 409)
        unchanged = fixtures.read_audit(audit["id"])
        assert unchanged["status"] == "PLANNED"
        assert unchanged["random_seed"] is None
        assert unchanged["seed_published_at"] is None
        assert unchanged["planned_sample_size"] is None

    def test_seed_ceremony_after_the_canvass_publishes_the_seed_and_sizes_the_sample(
        self,
    ):
        """PRD §3.4: "The ceremony stamps `seed_published_at` from the clock, moves the
        audit from `PLANNED` to `SEEDED`, recomputes `planned_sample_size`, and
        increments the audit's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_seed_requires_canvassed_contest
        """
        scenario = fixtures.setup_election_with_contest_and_batches()
        audit = fixtures.create_audit(scenario["contest"]["id"])
        api_client.seed_audit(audit["id"], factories.seed_audit_payload(), AUDIT_MANAGER)

        contest = fixtures.canvass_contest(scenario["contest"]["id"])
        seeded = validate_success(
            api_client.seed_audit(
                audit["id"], factories.seed_audit_payload(), AUDIT_MANAGER
            )
        )

        assert contest["status"] == "CANVASSED"
        assert contest["margin_votes"] == 300
        assert contest["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        assert seeded["status"] == "SEEDED"
        assert seeded["random_seed"] == constants.TEST_DEFAULTS["AUDIT_SEED"]
        assertions.assert_same_instant(
            seeded["seed_published_at"],
            constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"],
            "seed_published_at",
        )
        assert seeded["planned_sample_size"] == 3
        assert seeded["version"] == audit["version"] + 1

    def test_the_canvass_cascade_reaches_the_election_and_no_round_is_drawn_by_seeding(
        self,
    ):
        """PRD §3.1: "when every contest of the election has reached `CANVASSED` and at
        least one contest exists, the election moves from `OPEN` to `CANVASSED`, its
        `timeline_status` and `certification_risk_flag` are recomputed, and its `version`
        is incremented by one."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_seed_requires_canvassed_contest
        """
        scenario = fixtures.setup_election_with_contest_and_batches()
        audit = fixtures.create_audit(scenario["contest"]["id"])
        fixtures.canvass_contest(scenario["contest"]["id"])
        fixtures.seed_audit(audit["id"])

        election = fixtures.read_election(scenario["election"]["id"])
        assert election["status"] == "CANVASSED"
        assert election["certification_risk_flag"] is False
        assert fixtures.list_audit_rounds(audit["id"]) == []
        assert fixtures.read_audit(audit["id"])["cumulative_sampled_batches"] == 0
