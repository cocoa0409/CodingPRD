"""Two-variant calculations: provisional accrual vs final disbursement, and
live readiness vs the frozen snapshot.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.assertions import assert_money_cents, assert_two_decimals
from test_helpers.fixtures import (
    attest_attainment,
    build_program,
    define_milestone,
    read_mentor,
    read_match,
    read_novice,
    read_readiness,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, PREPARER, make_site_lead_headers


class TestStipendProvisionalVersusFinal:
    """The accrual counts pending work; the disbursement counts only verified work."""

    @staticmethod
    def _two_logs(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-03T12:00:00Z")
        log_a = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-01T09:00:00Z",
            minutes=90,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, log_a["id"], lead)
        log_b = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=60,
            contact_type="MODEL_LESSON",
            mentor_id=program["mentor_id"],
            description="Model lesson delivered in the novice classroom for the whole period",
        )
        set_clock(api, "2026-10-05T00:00:00Z")
        program["log_a_id"] = log_a["id"]
        program["log_b_id"] = log_b["id"]
        return program

    def test_draft_gross_excludes_the_still_submitted_log(self, api: InductionApiClient):
        """A draft prices only VERIFIED logs while the accrual also prices a SUBMITTED one.

        The mentor holds one VERIFIED 90-minute one-on-one worth 6300 cents and
        one SUBMITTED 60-minute model lesson projected at floor(60 * 1.25) = 75
        credited minutes, worth 5250 cents. The PRD says of the draft's narrower
        input set: "The consequence is that the same stored data yields a
        strictly smaller gross than the accrual whenever any log is still
        awaiting verification, and a different gross whenever the mentor's
        certification changed after a log was verified."

        Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final_divergence
        """
        program = self._two_logs(api)
        mentor_v2 = read_mentor(api, program["mentor_id"])["version"]

        response = api.create_disbursement(
            f.disbursement_payload(
                program["mentor_id"],
                mentor_v2,
                period_code="2026-Q3",
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-09-30T23:59:59Z",
            ),
            PREPARER,
        )
        disbursement = validate_success(response, 201)

        assert_money_cents(disbursement["gross_cents"], 6300, "gross_cents")
        assert_money_cents(disbursement["net_cents"], 6300, "net_cents")
        assert disbursement["eligible_log_count"] == 1, (
            "only the VERIFIED log enters the draft's input set, "
            f"got eligible_log_count {disbursement['eligible_log_count']}"
        )

        mentor = read_mentor(api, program["mentor_id"])
        assert_money_cents(mentor["stipend_accrued_cents"], 11550, "stipend_accrued_cents")
        assert mentor["stipend_accrued_cents"] - disbursement["gross_cents"] == 5250, (
            "the accrual must exceed the draft gross by exactly the projected "
            "5250 cents of the still-SUBMITTED log"
        )
        assert_money_cents(
            read_match(api, program["match_id"])["accrued_stipend_cents"],
            6300,
            "match accrued_stipend_cents",
        )

    def test_submitted_log_carries_no_credited_minutes_or_cents_of_its_own(
        self, api: InductionApiClient
    ):
        """The projected accrual never writes anything onto the pending log itself.

        The PRD confines the projection to the accrual figure: "For a log that is
        merely `SUBMITTED` nothing has been pinned yet, so the tier is read live
        from the match's current `subject_match_tier`, the multiplier is read
        live from the mentor's current `certification_status`, and the credited
        minutes are replaced by the projected figure — the raw minutes scaled by
        the contact type's weight and floored, then capped by whatever room is
        left in that day's ceiling."

        Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final_divergence
        """
        program = self._two_logs(api)

        verified = validate_success(api.get_contact_log(program["log_a_id"], ADMIN))
        assert verified["verification_status"] == "VERIFIED"
        assert verified["credited_minutes"] == 90, (
            f"a 90-minute one-on-one credits 90 minutes, got {verified['credited_minutes']}"
        )
        assert_money_cents(verified["stipend_cents"], 6300, "stipend_cents")

        pending = validate_success(api.get_contact_log(program["log_b_id"], ADMIN))
        assert pending["verification_status"] == "SUBMITTED"
        assert pending["credited_minutes"] == 0, (
            "a SUBMITTED log enters verification_status SUBMITTED with credited_minutes "
            f"at zero, got {pending['credited_minutes']}"
        )
        assert_money_cents(pending["stipend_cents"], 0, "stipend_cents")
        assert pending["rate_tier_at_verification"] is None, (
            "nothing is pinned on a log that has not been verified"
        )
        assert pending["cert_multiplier_at_verification"] is None, (
            "nothing is pinned on a log that has not been verified"
        )


class TestReadinessLiveVersusSnapshot:
    """The live index tracks today's counters; the snapshot keeps what was attested."""

    @staticmethod
    def _attested_novice(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-06T12:00:00Z")
        for contact_date, minutes in (
            ("2026-08-03T09:00:00Z", 180),
            ("2026-08-04T09:00:00Z", 180),
            ("2026-08-05T09:00:00Z", 120),
        ):
            log = submit_contact_log(
                api,
                program["match_id"],
                contact_date,
                minutes=minutes,
                contact_type="ONE_ON_ONE",
                mentor_id=program["mentor_id"],
            )
            verify_contact_log(api, log["id"], lead)
            program.setdefault("log_ids", []).append(log["id"])

        milestone = define_milestone(
            api,
            "IND_CONTACT_HOURS",
            1,
            title="Foundational contact hours",
            required_contact_minutes=300,
        )
        attainment = validate_success(
            api.create_attainment(
                f.attainment_payload(
                    program["novice_id"],
                    milestone["id"],
                    evidence_note="Contact hour ledger attached for review",
                ),
                ADMIN,
            ),
            201,
        )
        attest_attainment(
            api,
            attainment["id"],
            ADMIN,
            evidence_note="Verified contact ledger exceeds the 300 minute requirement",
        )
        program["attainment_id"] = attainment["id"]
        return program

    def test_void_moves_the_live_index_and_leaves_the_snapshot_frozen(
        self, api: InductionApiClient
    ):
        """Voiding 120 of 480 verified minutes drops live readiness to 27.00 while the
        attested snapshot stays at 36.00.

        The PRD makes the divergence the point of carrying two figures: "Because
        the snapshot survives a later void of a contact log while the live figure
        does not, the two variants routinely diverge on identical stored data,
        and that divergence is the point: the snapshot is what the district
        attested to, the live figure is what is true now."

        Design: Difficulty/dual_variant_calc/readiness_live_vs_snapshot_divergence
        """
        program = self._attested_novice(api)
        voided_log_id = program["log_ids"][2]

        before = read_novice(api, program["novice_id"])
        assert_two_decimals(before["readiness_index_live"], 36.00, "readiness_index_live")
        assert_two_decimals(
            before["readiness_index_snapshot"], 36.00, "readiness_index_snapshot"
        )

        validate_success(
            api.void_contact_log(
                voided_log_id,
                f.void_payload(
                    void_reason="Duplicate entry discovered during the monthly ledger audit"
                ),
                ADMIN,
            )
        )

        log = validate_success(api.get_contact_log(voided_log_id, ADMIN))
        assert log["verification_status"] == "VOIDED"
        assert log["credited_minutes"] == 0, "a voided log credits nothing"

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 360, (
            "480 verified minutes less the voided 120 leaves 360, got "
            f"{novice['verified_contact_minutes']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 27.00, "readiness_index_live")
        assert_two_decimals(
            novice["readiness_index_snapshot"], 36.00, "readiness_index_snapshot"
        )
        assert novice["readiness_index_live"] != novice["readiness_index_snapshot"], (
            "the two readiness variants must be allowed to disagree after a void"
        )
        assert novice["attained_milestone_count"] == 1, (
            "the 300-minute requirement is still met by 360 minutes, so the "
            "attainment survives the void"
        )

    def test_snapshot_reads_the_evidence_frozen_on_the_attained_row(
        self, api: InductionApiClient
    ):
        """The snapshot figure is computed from the attainment row's frozen counters.

        The PRD pins the snapshot's input set: "`readiness_index_snapshot` runs
        it over the five frozen figures of a single attainment row — the
        novice's `ATTAINED` row ranked by its milestone's `sequence_index`
        descending, and where two `ATTAINED` rows share a `sequence_index`, by
        the attainment's own `created_at` descending, the first row winning."

        Design: Difficulty/dual_variant_calc/readiness_live_vs_snapshot_divergence
        """
        program = self._attested_novice(api)
        validate_success(
            api.void_contact_log(
                program["log_ids"][2],
                f.void_payload(
                    void_reason="Duplicate entry discovered during the monthly ledger audit"
                ),
                ADMIN,
            )
        )

        attainment = validate_success(
            api.get_attainment(program["attainment_id"], ADMIN)
        )
        assert attainment["status"] == "ATTAINED"
        assert attainment["snapshot_contact_minutes"] == 480, (
            "the row must still carry the 480 minutes frozen at attestation, got "
            f"{attainment['snapshot_contact_minutes']}"
        )

        readiness = read_readiness(api, program["novice_id"])
        assert_two_decimals(readiness["readiness_index_live"], 27.00, "readiness_index_live")
        assert_two_decimals(
            readiness["readiness_index_snapshot"], 36.00, "readiness_index_snapshot"
        )
        assert readiness["snapshot_source_attainment_id"] == program["attainment_id"], (
            "the readiness read must name the attainment row that supplied the "
            "frozen evidence"
        )
