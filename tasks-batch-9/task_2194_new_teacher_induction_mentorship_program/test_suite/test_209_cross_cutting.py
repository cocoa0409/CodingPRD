"""The three optimistic-concurrency guards, each invalidated by a write the client
did not issue against the parent it named.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_CASELOAD_CAP_EXCEEDED,
    ERR_NOVICE_PROGRAM_STATE_INVALID,
    ERR_STALE_PARENT_VERSION,
)
from test_helpers.assertions import assert_money_cents
from test_helpers.fixtures import (
    activate_match,
    build_program,
    create_novice,
    read_mentor,
    read_novice,
    set_clock,
    submit_and_verify_contact_log,
)
from test_helpers.test_users import ADMIN, make_site_lead_headers


class TestMatchCreationStaleMentorVersion:
    """Proposing a match is itself the write that invalidates the guard."""

    def test_occ_match_creation_rejects_mentor_version_stale_by_one_match(
        self, api: InductionApiClient
    ):
        """Two proposals from one read of the mentor: the second is a 412.

        The PRD explains why the proposal advances its own guard: "Proposing a
        mentor-novice match requires `expected_mentor_version`, carrying the client's
        last observed `version` of the target `Mentor`. On the automatic-selection
        path the value is compared against the `version` of the mentor the ranking
        policy selects. A previous match proposal against the same mentor
        legitimately consumed caseload headroom and advanced `Mentor.version`, so a
        client holding an older number is working from a stale view of that mentor's
        caseload and is told to re-read rather than being allowed to over-commit the
        mentor."

        Design: Corner/cross_cutting_complexity_layers/occ_match_creation_rejects_mentor_version_stale_by_one_match
        """
        program = build_program(api, activate=False)
        stale_version = program["mentor_version_at_proposal"]
        second_novice = create_novice(
            api, program["site_id"], program["cohort_id"], full_name="Ira Vance"
        )

        stale_proposal = api.create_match(
            f.match_payload(second_novice["id"], stale_version, program["mentor_id"]), ADMIN
        )
        refusal = validate_error(stale_proposal, ERR_STALE_PARENT_VERSION, 412)
        assert refusal["error_id"] != ERR_CASELOAD_CAP_EXCEEDED, (
            "the staleness check runs before any business rule, and caseload room remains"
        )

        mentor = read_mentor(api, program["mentor_id"])
        assert mentor["version"] == stale_version + 1, (
            "the first proposal advanced the guard by exactly one, got version "
            f"{mentor['version']} against a captured {stale_version}"
        )
        assert mentor["active_caseload_count"] == 0, (
            "a proposed match occupies no slot yet, got "
            f"{mentor['active_caseload_count']}"
        )

        accepted = validate_success(
            api.create_match(
                f.match_payload(second_novice["id"], mentor["version"], program["mentor_id"]),
                ADMIN,
            ),
            201,
        )
        assert accepted["match_status"] == "PROPOSED"
        assert accepted["novice_id"] == second_novice["id"]
        assert accepted["subject_match_tier"] == "EXACT"

        after = read_mentor(api, program["mentor_id"])
        assert after["version"] == stale_version + 2, (
            f"the re-read proposal advanced it again, got {after['version']}"
        )
        assert after["active_caseload_count"] == 0

        _, meta = validate_paginated(
            api.list_matches(ADMIN, {"mentor_id": program["mentor_id"]})
        )
        assert meta["total_count"] == 2, (
            f"the refused proposal created no row, got total_count {meta['total_count']}"
        )
        assert read_novice(api, second_novice["id"])["program_status"] == "MATCHED"


class TestStipendDraftStaleMentorVersion:
    """Evidence writes advance the same counter the fiscal write is guarded by."""

    def test_occ_stipend_draft_rejects_mentor_version_stale_by_match_activation(
        self, api: InductionApiClient
    ):
        """A draft prepared from the post-certification version is refused before any money.

        The PRD explains what the guard protects on this endpoint: "Drafting a stipend
        disbursement requires `expected_mentor_version` against the same
        `Mentor.version`. A new draft for a mentor and period legitimately supersedes
        the prior draft for that same period, so the write is destructive with respect
        to whatever the client last observed; a stale version means the client would
        be superseding a draft it never saw."

        Design: Corner/cross_cutting_complexity_layers/occ_stipend_draft_rejects_mentor_version_stale_by_match_activation
        """
        program = build_program(api)
        stale_version = program["mentor_version_at_proposal"]
        set_clock(api, "2026-08-05T12:00:00Z")
        submit_and_verify_contact_log(
            api,
            program["match_id"],
            program["mentor_id"],
            "2026-08-03T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            verifier=make_site_lead_headers(program["site_id"]),
            description="Weekly one-on-one on questioning technique",
        )
        set_clock(api, "2026-09-01T09:00:00Z")

        def august(version: int) -> dict:
            return f.disbursement_payload(
                program["mentor_id"],
                version,
                period_code="2026-Q3",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            )

        stale_draft = api.create_disbursement(august(stale_version), ADMIN)
        validate_error(stale_draft, ERR_STALE_PARENT_VERSION, 412)

        _, empty = validate_paginated(
            api.list_disbursements(ADMIN, {"mentor_id": program["mentor_id"]})
        )
        assert empty["total_count"] == 0, (
            f"the refused draft left no row behind, got {empty['total_count']}"
        )

        fresh_version = read_mentor(api, program["mentor_id"])["version"]
        assert fresh_version > stale_version, (
            "activation and verification each advanced the mentor past the captured "
            f"version, got {fresh_version} against {stale_version}"
        )

        draft = validate_success(api.create_disbursement(august(fresh_version), ADMIN), 201)
        assert draft["status"] == "DRAFT"
        assert draft["eligible_log_count"] == 1
        assert_money_cents(draft["gross_cents"], 4200, "gross_cents")
        assert_money_cents(draft["net_cents"], 4200, "net_cents")

        mentor = read_mentor(api, program["mentor_id"])
        assert mentor["version"] == fresh_version + 1, (
            f"a successful draft advances the guard again, got {mentor['version']}"
        )
        assert_money_cents(mentor["stipend_accrued_cents"], 4200, "stipend_accrued_cents")
        assert_money_cents(mentor["stipend_paid_cents"], 0, "stipend_paid_cents")


class TestPacketCreationStaleNoviceVersion:
    """The invalidating write is a bubble-up the client never issued on the novice."""

    def test_occ_packet_creation_rejects_novice_version_stale_by_activation(
        self, api: InductionApiClient
    ):
        """Activating the match moves the novice, so the earlier read is one write behind.

        The PRD ties the guard to the counters the score reads: "Creating a completion
        certification packet requires `expected_novice_version`, carrying the client's
        last observed `version` of the target `NoviceTeacher`. Packet scoring reads
        the novice's readiness and milestone counters at creation time, and those
        counters advance `NoviceTeacher.version` whenever contact logs, observation
        cycles, seminar attendance or milestone attainments change; a stale version
        means the packet would be scored from evidence the client never observed."

        Design: Corner/cross_cutting_complexity_layers/occ_packet_creation_rejects_novice_version_stale_by_activation
        """
        program = build_program(api, activate=False)
        while_matched = read_novice(api, program["novice_id"])
        assert while_matched["program_status"] == "MATCHED"
        stale_version = while_matched["version"]

        activated = activate_match(api, program["match_id"])
        assert activated["match_status"] == "ACTIVE"
        assert activated["pinned_stipend_rate_cents_per_hour"] is not None, (
            "activation is what pins the rate"
        )

        stale_packet = api.create_packet(
            f.packet_payload(program["novice_id"], stale_version), ADMIN
        )
        refusal = validate_error(stale_packet, ERR_STALE_PARENT_VERSION, 412)
        assert refusal["error_id"] != ERR_NOVICE_PROGRAM_STATE_INVALID, (
            "the novice is now ACTIVE and therefore eligible; only the client's view is stale"
        )

        after_activation = read_novice(api, program["novice_id"])
        assert after_activation["program_status"] == "ACTIVE"
        assert after_activation["version"] == stale_version + 1, (
            "the bubble-up advanced the novice by exactly one, got version "
            f"{after_activation['version']}"
        )

        packet = validate_success(
            api.create_packet(
                f.packet_payload(program["novice_id"], after_activation["version"]), ADMIN
            ),
            201,
        )
        assert packet["packet_status"] == "ASSEMBLING"
        assert packet["resubmission_count"] == 0

        final = read_novice(api, program["novice_id"])
        assert final["program_status"] == "COMPLETION_PENDING"
        assert final["version"] == after_activation["version"] + 1, (
            f"assembly advanced the novice once more, got {final['version']}"
        )

        _, meta = validate_paginated(
            api.list_packets(ADMIN, {"novice_id": program["novice_id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused creation stored nothing, got total_count {meta['total_count']}"
        )
