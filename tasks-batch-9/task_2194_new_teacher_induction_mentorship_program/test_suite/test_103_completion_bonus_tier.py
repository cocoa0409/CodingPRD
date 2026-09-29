"""The completion score's retention bonus is resolved against the pre-bonus base
score, which is what keeps the calculation from being circular.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.assertions import assert_two_decimals
from test_helpers.fixtures import (
    attest_attainment,
    build_program,
    define_milestone,
    document_observation_cycle,
    hold_session,
    open_observation_cycle,
    read_novice,
    record_attendance,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, make_site_lead_headers


def _novice_ready_for_a_packet(api: InductionApiClient) -> dict:
    """Build a novice whose live readiness is 82.00 with three attained milestones."""
    program = build_program(api)
    lead = make_site_lead_headers(program["site_id"])
    set_clock(api, "2026-08-15T12:00:00Z")

    for contact_date in ("2026-08-03T09:00:00Z", "2026-08-04T09:00:00Z"):
        log = submit_contact_log(
            api,
            program["match_id"],
            contact_date,
            minutes=180,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, log["id"], lead)

    for cycle_index, day in ((1, "2026-08-10"), (2, "2026-08-11")):
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            cycle_index,
            f"{day}T09:00:00Z",
            f"{day}T10:00:00Z",
        )
        document_observation_cycle(
            api, cycle["id"], program["mentor_id"], program["site_id"]
        )

    session = schedule_seminar_session(
        api,
        program["cohort_id"],
        1,
        "2026-08-12T15:00:00Z",
        "2026-08-12T17:00:00Z",
        topic="Classroom routines and equitable participation",
    )
    record_attendance(api, session["id"], program["novice_id"], "PRESENT", 120, lead)
    hold_session(api, session["id"])

    program["attainment_ids"] = []
    for code, sequence_index, title in (
        ("IND_ENTRY", 1, "Entry conference complete"),
        ("IND_PRACTICE", 2, "Practice evidence complete"),
        ("IND_PORTFOLIO", 3, "Portfolio review complete"),
    ):
        milestone = define_milestone(api, code, sequence_index, title=title)
        attainment = validate_success(
            api.create_attainment(
                f.attainment_payload(
                    program["novice_id"],
                    milestone["id"],
                    evidence_note="Evidence binder on file for the panel review",
                ),
                ADMIN,
            ),
            201,
        )
        attest_attainment(api, attainment["id"], ADMIN)
        program["attainment_ids"].append(attainment["id"])

    validate_success(
        api.record_retention_outcome(
            program["novice_id"],
            f.retention_outcome_payload("RETAINED_SAME_SITE", "2026-08-14T00:00:00Z"),
            ADMIN,
        )
    )
    return program


class TestCompletionBonusTierReadsBaseScore:
    """A base score of 89.20 earns the mid tier even though the total clears 90.00."""

    def test_bonus_is_pinned_to_the_pre_bonus_base_score(self, api: InductionApiClient):
        """base_score 89.20 earns 2.50, not the 5.00 that reading 91.70 would award.

        The PRD forbids resolving the tier against the total: "The tier comparison
        in step three reads the **rounded `base_score`** written in step two,
        never the `completion_score` that step four produces — the bonus depends
        on the score before the bonus, and resolving it the other way round is
        circular."

        Design: Difficulty/combinatorial_formula/completion_bonus_tier_reads_base_score
        """
        program = _novice_ready_for_a_packet(api)
        novice_version = read_novice(api, program["novice_id"])["version"]

        packet = validate_success(
            api.create_packet(
                f.packet_payload(program["novice_id"], novice_version), ADMIN
            ),
            201,
        )

        assert_two_decimals(packet["base_score"], 89.20, "base_score")
        assert_two_decimals(packet["retention_bonus"], 2.50, "retention_bonus")
        assert packet["retention_bonus"] != 5.00, (
            "reading the post-bonus completion score of 91.70 would wrongly award "
            "the 5.00 high tier"
        )
        assert_two_decimals(packet["completion_score"], 91.70, "completion_score")
        assert packet["completion_score"] != 94.20, (
            "94.20 is what a circular resolution of the bonus tier would produce"
        )

    def test_packet_scores_from_live_readiness_and_attained_rows(
        self, api: InductionApiClient
    ):
        """The 82.00 live index and three ATTAINED rows produce the 89.20 base score.

        The PRD names both inputs of step two: "Step two forms `base_score` as the
        novice's `readiness_index_live` weighted by 0.60 plus 100 multiplied by
        the milestone component weighted by 0.40, rounded half up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/completion_bonus_tier_reads_base_score
        """
        program = _novice_ready_for_a_packet(api)
        novice = read_novice(api, program["novice_id"])

        assert_two_decimals(novice["readiness_index_live"], 82.00, "readiness_index_live")
        assert novice["documented_observation_cycles"] == 2, (
            f"two cycles reached DOCUMENTED, got {novice['documented_observation_cycles']}"
        )
        assert novice["credited_seminar_sessions"] == 1, (
            f"one credited row on a HELD session, got {novice['credited_seminar_sessions']}"
        )
        assert novice["attained_milestone_count"] == 3, (
            f"three rows reached ATTAINED, got {novice['attained_milestone_count']}"
        )

        packet = validate_success(
            api.create_packet(
                f.packet_payload(program["novice_id"], novice["version"]), ADMIN
            ),
            201,
        )
        assert packet["evidence_milestone_count"] == 3, (
            "evidence_milestone_count stores the count of ATTAINED rows, got "
            f"{packet['evidence_milestone_count']}"
        )
        assert packet["packet_status"] == "ASSEMBLING", (
            f"a new packet opens ASSEMBLING, got {packet['packet_status']}"
        )
        assert packet["resubmission_count"] == 0, (
            f"a new packet opens with resubmission_count at zero, got "
            f"{packet['resubmission_count']}"
        )
        assert read_novice(api, program["novice_id"])["program_status"] == "COMPLETION_PENDING", (
            "creating a completion packet advances ACTIVE to COMPLETION_PENDING"
        )
