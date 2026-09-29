"""Cascades where each link is caused by the previous one: the four-hop contact-log
void and the two-hop mentor suspension.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.assertions import assert_instant_equals, assert_two_decimals
from test_helpers.fixtures import (
    attest_attainment,
    build_program,
    define_milestone,
    document_observation_cycle,
    hold_session,
    open_observation_cycle,
    read_attainment,
    read_cycle,
    read_match,
    read_mentor,
    read_novice,
    read_packet,
    read_site,
    record_attendance,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, make_mentor_headers, make_site_lead_headers


def _novice_recommended_with_a_submitted_packet(api: InductionApiClient) -> dict:
    """Readiness exactly at the gate, three attained milestones, packet at the state."""
    program = build_program(api)
    lead = make_site_lead_headers(program["site_id"])
    set_clock(api, "2026-08-10T12:00:00Z")

    program["log_ids"] = []
    for day, minutes in (
        ("2026-08-03", 180),
        ("2026-08-04", 180),
        ("2026-08-05", 180),
        ("2026-08-06", 60),
    ):
        log = submit_contact_log(
            api,
            program["match_id"],
            f"{day}T09:00:00Z",
            minutes=minutes,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, log["id"], lead)
        program["log_ids"].append(log["id"])

    cycle = open_observation_cycle(
        api,
        program["match_id"],
        program["mentor_id"],
        1,
        "2026-08-07T09:00:00Z",
        "2026-08-07T10:00:00Z",
    )
    document_observation_cycle(api, cycle["id"], program["mentor_id"], program["site_id"])

    session = schedule_seminar_session(
        api,
        program["cohort_id"],
        1,
        "2026-08-08T15:00:00Z",
        "2026-08-08T17:00:00Z",
        topic="Data driven instruction seminar",
    )
    record_attendance(api, session["id"], program["novice_id"], "PRESENT", 120, lead)
    hold_session(api, session["id"])

    program["attainment_ids"] = []
    definitions = (
        ("IND_ENTRY", 1, "Entry conference complete", {}),
        ("IND_PRACTICE", 2, "Practice evidence complete", {}),
        (
            "IND_RECOMMEND",
            3,
            "Licence recommendation evidence complete",
            {
                "required_contact_minutes": 600,
                "required_observation_cycles": 1,
                "required_credited_seminars": 1,
                "gates_license_recommendation": True,
            },
        ),
    )
    for code, sequence_index, title, thresholds in definitions:
        milestone = define_milestone(api, code, sequence_index, title=title, **thresholds)
        attainment = validate_success(
            api.create_attainment(
                f.attainment_payload(
                    program["novice_id"],
                    milestone["id"],
                    evidence_note="Contact ledger, observation cycle and seminar credit on file",
                ),
                ADMIN,
            ),
            201,
        )
        attest_attainment(api, attainment["id"], ADMIN)
        program["attainment_ids"].append(attainment["id"])

    validate_success(
        api.close_cohort(program["cohort_id"], f.close_cohort_payload("CLOSED"), ADMIN)
    )

    novice = read_novice(api, program["novice_id"])
    packet = validate_success(
        api.create_packet(f.packet_payload(program["novice_id"], novice["version"]), ADMIN),
        201,
    )
    validate_success(
        api.packet_transition(packet["id"], f.packet_transition_payload("SUBMIT"), ADMIN)
    )
    program["packet_id"] = packet["id"]
    return program


class TestContactVoidFourHopCascade:
    """One void of 60 minutes travels from the ledger all the way to the state."""

    def test_void_lowers_the_ledger_and_revokes_only_the_starved_attainment(
        self, api: InductionApiClient
    ):
        """600 verified minutes fall to 540, and only the 600-minute milestone is revoked.

        The PRD makes hop two conditional on the reduced counters: "Because the
        novice's verified contact minutes have fallen, every attainment row of
        that novice in `ATTAINED` whose milestone's evidence requirements the
        reduced counters no longer satisfy transitions `ATTAINED → REVOKED` with
        a `revoke_reason` of `EVIDENCE_WITHDRAWN`, processed in ascending
        `sequence_index` of the milestone definitions. Rows still above their
        thresholds are untouched."

        Design: Difficulty/transitive_cascade/contact_void_four_hop_cascade
        """
        program = _novice_recommended_with_a_submitted_packet(api)
        voided_log_id = program["log_ids"][3]
        entry_id, practice_id, recommend_id = program["attainment_ids"]

        validate_success(
            api.void_contact_log(
                voided_log_id,
                f.void_payload(
                    void_reason="Duplicate entry discovered during the state monitoring audit"
                ),
                ADMIN,
            )
        )

        log = validate_success(api.get_contact_log(voided_log_id, ADMIN))
        assert log["verification_status"] == "VOIDED"
        assert log["credited_minutes"] == 0, "hop one resets the log's credited minutes"
        assert log["stipend_cents"] == 0, "hop one resets the log's stipend to zero"

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 540, (
            f"600 less the voided 60 is 540, got {novice['verified_contact_minutes']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 80.50, "readiness_index_live")
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 540

        recommend = read_attainment(api, recommend_id)
        assert recommend["status"] == "REVOKED", (
            "540 minutes no longer satisfies the 600-minute requirement, got "
            f"{recommend['status']}"
        )
        assert recommend["revoke_reason"] == "EVIDENCE_WITHDRAWN", (
            f"the cascaded revocation names its own reason, got {recommend['revoke_reason']}"
        )
        assert read_attainment(api, entry_id)["status"] == "ATTAINED", (
            "a milestone with no evidence requirement stays attained"
        )
        assert read_attainment(api, practice_id)["status"] == "ATTAINED", (
            "a milestone with no evidence requirement stays attained"
        )
        assert novice["attained_milestone_count"] == 2, (
            f"three attainments less the revoked one is two, got "
            f"{novice['attained_milestone_count']}"
        )

    def test_revocation_withdraws_the_recommendation_and_returns_the_packet(
        self, api: InductionApiClient
    ):
        """Hops three and four: the licence recommendation falls and the state packet returns.

        The PRD carries the chain two links further: "*Hop three* follows from
        any such revocation on a milestone that gates the licence recommendation:
        the novice's `license_advancement_status` falls from `RECOMMENDED` to
        `NOT_ELIGIBLE` and `license_stage` reverts to `PRELIMINARY`." And of hop
        four: "Every completion packet of that novice sitting in
        `SUBMITTED_TO_STATE` transitions to `RETURNED` with a `return_reason` of
        `EVIDENCE_REVOKED`; on this cascaded path `decided_at` and
        `decided_by_user_id` are left null, because no state officer decided
        anything."

        Design: Difficulty/transitive_cascade/contact_void_four_hop_cascade
        """
        program = _novice_recommended_with_a_submitted_packet(api)

        before = read_novice(api, program["novice_id"])
        assert before["license_advancement_status"] == "RECOMMENDED", (
            "the gating milestone lifted the novice to RECOMMENDED, got "
            f"{before['license_advancement_status']}"
        )
        assert before["license_stage"] == "PROVISIONAL", (
            f"attestation wrote the unlocked stage, got {before['license_stage']}"
        )
        assert read_packet(api, program["packet_id"])["packet_status"] == "SUBMITTED_TO_STATE"

        validate_success(
            api.void_contact_log(
                program["log_ids"][3],
                f.void_payload(
                    void_reason="Duplicate entry discovered during the state monitoring audit"
                ),
                ADMIN,
            )
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["license_advancement_status"] == "NOT_ELIGIBLE", (
            "the withdrawn evidence drops the recommendation, got "
            f"{novice['license_advancement_status']}"
        )
        assert novice["license_stage"] == "PRELIMINARY", (
            f"the licence stage reverts, got {novice['license_stage']}"
        )

        packet = read_packet(api, program["packet_id"])
        assert packet["packet_status"] == "RETURNED", (
            f"the submitted packet comes back from the state, got {packet['packet_status']}"
        )
        assert packet["return_reason"] == "EVIDENCE_REVOKED", (
            f"the cascaded return names its own reason, got {packet['return_reason']}"
        )
        assert packet["decided_by_user_id"] is None, (
            "no officer decided this return, so no decider is recorded"
        )
        assert packet["decided_at"] is None, (
            "no officer decided this return, so no decision instant is recorded"
        )
        assert novice["program_status"] == "ACTIVE", (
            "a returned packet drops the novice back to ACTIVE so the district can "
            f"rebuild it, got {novice['program_status']}"
        )


class TestMentorSuspensionTwoHopCascade:
    """Suspending a mentor suspends the match, which abandons its open cycles."""

    @staticmethod
    def _mentor_with_three_cycles(api: InductionApiClient) -> dict:
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-08T12:00:00Z")

        first = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:00:00Z",
        )
        second = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            2,
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:00:00Z",
        )
        validate_success(
            api.advance_cycle(second["id"], f.advance_payload("OBSERVED"), mentor_headers)
        )
        validate_success(
            api.advance_cycle(
                second["id"], f.advance_payload("POST_CONFERENCE"), mentor_headers
            )
        )
        third = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            3,
            "2026-08-07T09:00:00Z",
            "2026-08-07T10:00:00Z",
        )
        document_observation_cycle(
            api, third["id"], program["mentor_id"], program["site_id"]
        )

        program["cycle_ids"] = [first["id"], second["id"], third["id"]]
        return program

    def test_suspension_suspends_the_match_and_releases_both_slots(
        self, api: InductionApiClient
    ):
        """Hop one: the ACTIVE match is suspended and the caseload and site slot are freed.

        The PRD spells out the trigger and its first hop: "**Suspend** moves a
        `CERTIFIED` mentor to `SUSPENDED` and requires a `reason`, which is
        stored as `suspension_reason`." And: "A deliberate suspension behaves
        exactly like a lapse in this respect: it too suspends every `ACTIVE`
        match of the mentor in `created_at` ascending order." What that suspension
        costs is also spelled out: "It stamps the match's `suspended_at` from the
        logical clock, decrements both the mentor's `active_caseload_count` and
        the site's `active_match_count` — a `SUSPENDED` match does not occupy a
        slot".

        Design: Difficulty/transitive_cascade/mentor_suspension_two_hop_cascade
        """
        program = self._mentor_with_three_cycles(api)
        reason = "Mandated reporter training lapsed pending district review"

        mentor = validate_success(
            api.certification_action(
                program["mentor_id"],
                f.certification_payload("SUSPEND", reason=reason),
                ADMIN,
            )
        )
        assert mentor["certification_status"] == "SUSPENDED", (
            f"the trigger itself moves the mentor, got {mentor['certification_status']}"
        )
        assert mentor["suspension_reason"] == reason, (
            f"the supplied reason is stored, got {mentor['suspension_reason']}"
        )

        match = read_match(api, program["match_id"])
        assert match["match_status"] == "SUSPENDED", (
            f"hop one suspends the ACTIVE match, got {match['match_status']}"
        )
        assert_instant_equals(match["suspended_at"], "2026-08-08T12:00:00Z", "suspended_at")
        assert read_mentor(api, program["mentor_id"])["active_caseload_count"] == 0, (
            "the suspended match releases the mentor's caseload slot"
        )
        assert read_site(api, program["site_id"])["active_match_count"] == 0, (
            "the suspended match releases the site's slot"
        )

    def test_only_the_non_terminal_cycles_are_abandoned_and_the_chain_stops(
        self, api: InductionApiClient
    ):
        """Hop two abandons the open cycles, spares the documented one and goes no further.

        The PRD confines hop two to the open cycles: "Suspending a match is not a
        bookkeeping no-op. It stamps the match's `suspended_at` from the logical
        clock, decrements both the mentor's `active_caseload_count` and the
        site's `active_match_count` — a `SUSPENDED` match does not occupy a slot
        — abandons every observation cycle on that match whose `phase` is
        `PRE_CONFERENCE`, `OBSERVED` or `POST_CONFERENCE` (processed in ascending
        `cycle_index`), and bumps the versions of the match, the mentor and the
        site."

        Design: Difficulty/transitive_cascade/mentor_suspension_two_hop_cascade
        """
        program = self._mentor_with_three_cycles(api)
        pre_conference_id, post_conference_id, documented_id = program["cycle_ids"]

        validate_success(
            api.certification_action(
                program["mentor_id"],
                f.certification_payload(
                    "SUSPEND", reason="Mandated reporter training lapsed pending review"
                ),
                ADMIN,
            )
        )

        assert read_cycle(api, pre_conference_id)["phase"] == "ABANDONED", (
            "a cycle still in PRE_CONFERENCE is abandoned by the cascade"
        )
        assert read_cycle(api, post_conference_id)["phase"] == "ABANDONED", (
            "a cycle in POST_CONFERENCE is abandoned by the cascade"
        )
        assert read_cycle(api, documented_id)["phase"] == "DOCUMENTED", (
            "DOCUMENTED is terminal, so the cascade leaves it alone"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["program_status"] == "ACTIVE", (
            "the chain stops at the cycles: the novice's participation is untouched, "
            f"got {novice['program_status']}"
        )
        assert novice["documented_observation_cycles"] == 1, (
            "the documented cycle still counts as evidence, got "
            f"{novice['documented_observation_cycles']}"
        )
