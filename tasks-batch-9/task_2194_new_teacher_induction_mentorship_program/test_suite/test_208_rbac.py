"""Role reach: the district office's exclusive operations, the operations genuinely
shared with the school, the state officer's single write, and the duty separation.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_PACKET_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money_cents,
    ids_of,
)
from test_helpers.fixtures import (
    activate_match,
    attainment_decision_request,
    attainment_for,
    build_program,
    define_milestone,
    propose_match,
    read_cycle,
    read_mentor,
    read_novice,
    read_packet,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_2,
    PROGRAM_OFFICE_1,
    PROGRAM_OFFICE_2,
    STATE_OFFICER,
    make_mentor_headers,
    make_site_lead_headers,
)


class TestProgramAdminExclusiveOperations:
    """The district office's own operations all succeed under its role."""

    def test_program_admin_exclusive_configuration_fiscal_and_clock_operations_succeed(
        self, api: InductionApiClient
    ):
        """Configuration, certification, the clock, the void and cohort closure all pass.

        The PRD reserves this reach to the district office: "`ProgramAdmin` is the
        district induction office: it owns configuration, certification, fiscal and
        cohort lifecycle operations, and it is the only role permitted to void
        verified evidence or move the logical clock."

        Design: Corner/rbac/program_admin_exclusive_configuration_fiscal_and_clock_operations_succeed
        """
        clock = validate_success(api.set_clock("2026-08-01T00:00:00Z", ADMIN))
        assert_instant_equals(clock["current_utc"], "2026-08-01T00:00:00Z", "current_utc")

        site = validate_success(api.create_site(f.site_payload(), ADMIN), 201)
        cohort = validate_success(api.create_cohort(f.cohort_payload(), ADMIN), 201)
        mentor = validate_success(api.create_mentor(f.mentor_payload(site["id"]), ADMIN), 201)
        for module, hours, day in (
            ("FOUNDATIONS", 8.00, "2026-07-10"),
            ("OBSERVATION_PROTOCOL", 6.00, "2026-07-11"),
            ("EQUITY", 4.00, "2026-07-12"),
        ):
            credited = validate_success(
                api.post_training_credit(
                    mentor["id"],
                    f.training_credit_payload(module_code=module, hours=hours, completed_on=day),
                    ADMIN,
                )
            )
            assert module in credited["training_modules_current_cycle"]
        certified = validate_success(
            api.certification_action(mentor["id"], f.certification_payload("CERTIFY"), ADMIN)
        )
        assert certified["certification_status"] == "CERTIFIED"

        novice = validate_success(
            api.create_novice(
                f.novice_payload(site["id"], cohort["id"], full_name="Dana Pike"), ADMIN
            ),
            201,
        )
        match = propose_match(api, novice["id"], certified["version"], mentor["id"])
        activate_match(api, match["id"])
        milestone = validate_success(
            api.create_milestone(
                f.milestone_payload("IND_ORIENT", 1, title="Orientation complete"), ADMIN
            ),
            201,
        )
        assert milestone["sequence_index"] == 1

        set_clock(api, "2026-08-05T12:00:00Z")
        log = validate_success(
            api.create_contact_log(
                f.contact_log_payload(
                    match["id"],
                    "2026-08-03T09:00:00Z",
                    60,
                    "ONE_ON_ONE",
                    description="Weekly one-on-one on questioning technique",
                ),
                make_mentor_headers(mentor["id"]),
            ),
            201,
        )
        validate_success(
            api.review_contact_log(
                log["id"],
                f.review_payload("VERIFY", note="Minutes confirmed against the sign-in sheet"),
                make_site_lead_headers(site["id"]),
            )
        )
        voided = validate_success(
            api.void_contact_log(
                log["id"],
                f.void_payload(void_reason="Log was filed against the wrong novice"),
                ADMIN,
            )
        )
        assert voided["verification_status"] == "VOIDED", (
            f"only the district office may void verified evidence, got "
            f"{voided['verification_status']}"
        )

        session = validate_success(
            api.create_seminar_session(
                f.seminar_session_payload(
                    cohort["id"],
                    1,
                    "2026-08-12T15:00:00Z",
                    "2026-08-12T16:00:00Z",
                    topic="Classroom routines",
                ),
                ADMIN,
            ),
            201,
        )
        cancelled = validate_success(
            api.set_session_status(session["id"], f.session_status_payload("CANCELLED"), ADMIN)
        )
        assert cancelled["status"] == "CANCELLED"

        retention = validate_success(
            api.record_retention_outcome(
                novice["id"],
                f.retention_outcome_payload(
                    retention_outcome="RETAINED_SAME_SITE",
                    observed_on="2026-08-05T12:00:00Z",
                ),
                ADMIN,
            )
        )
        assert retention["retention_outcome"] == "RETAINED_SAME_SITE"
        assert_instant_equals(
            retention["retention_observed_on"], "2026-08-05T12:00:00Z", "retention_observed_on"
        )

        closed = validate_success(
            api.close_cohort(cohort["id"], f.close_cohort_payload("CLOSED"), ADMIN)
        )
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None, "closure stamps the instant it happened"


class TestSharedEvidenceCreation:
    """Log and cycle creation are shared; feedback authoring is not."""

    def test_contact_log_and_observation_cycle_creation_shared_by_mentor_and_site_lead(
        self, api: InductionApiClient
    ):
        """The same payload succeeds under both identities and differs only in the stamp.

        The two identities are backed by different entities, and the PRD says which
        id each carries: "When `X-User-Role` is `Mentor`, `X-User-ID` is the `id` of
        the acting `Mentor`. That mentor may only touch resources reachable from its
        own matches: the `mentor_id` of the match behind a contact log or an
        observation cycle must equal `X-User-ID`."

        Design: Corner/rbac/contact_log_and_observation_cycle_creation_shared_by_mentor_and_site_lead
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-05T12:00:00Z")

        mentor_log = validate_success(
            api.create_contact_log(
                f.contact_log_payload(
                    program["match_id"],
                    "2026-08-03T09:00:00Z",
                    45,
                    "ONE_ON_ONE",
                    description="Mentor-filed coaching conversation on pacing",
                ),
                mentor_headers,
            ),
            201,
        )
        lead_log = validate_success(
            api.create_contact_log(
                f.contact_log_payload(
                    program["match_id"],
                    "2026-08-04T09:00:00Z",
                    45,
                    "ONE_ON_ONE",
                    description="Site-lead-filed coaching conversation on pacing",
                ),
                lead,
            ),
            201,
        )
        assert mentor_log["verification_status"] == "SUBMITTED"
        assert lead_log["verification_status"] == "SUBMITTED"
        assert mentor_log["submitted_by_user_id"] == program["mentor_id"], (
            f"the mentor's own id is stamped, got {mentor_log['submitted_by_user_id']}"
        )
        assert lead_log["submitted_by_user_id"] == program["site_id"], (
            f"the acting site's id is stamped, got {lead_log['submitted_by_user_id']}"
        )

        mentor_cycle = validate_success(
            api.create_observation_cycle(
                f.observation_cycle_payload(
                    program["match_id"], 1, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
                ),
                mentor_headers,
            ),
            201,
        )
        # The lead's cycle is booked into a window that has already closed at the
        # 12:00 logical clock, because "Advancing PRE_CONFERENCE → OBSERVED
        # additionally requires the logical clock to have reached or passed
        # window_end"; the 60-minute gap from the mentor's 10:00 end clears the
        # 30-minute travel buffer of the same-mentor conflict rule.
        lead_cycle = validate_success(
            api.create_observation_cycle(
                f.observation_cycle_payload(
                    program["match_id"], 2, "2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"
                ),
                lead,
            ),
            201,
        )
        for cycle in (mentor_cycle, lead_cycle):
            assert cycle["phase"] == "PRE_CONFERENCE"
            assert cycle["feedback_review_status"] == "NONE"

        advanced = validate_success(
            api.advance_cycle(lead_cycle["id"], f.advance_payload("OBSERVED"), lead)
        )
        assert advanced["phase"] == "OBSERVED", (
            f"phase advancement is shared with the school, got {advanced['phase']}"
        )

        lead_feedback = api.write_feedback(
            lead_cycle["id"], f.feedback_payload(submit=False, growth_area_codes=["PLANNING"]), lead
        )
        validate_error(lead_feedback, ERR_FORBIDDEN_ROLE, 403)
        assert read_cycle(api, lead_cycle["id"])["feedback_review_status"] == "NONE", (
            "the refused authoring attempt stored nothing"
        )

        drafted = validate_success(
            api.write_feedback(
                lead_cycle["id"],
                f.feedback_payload(submit=False, growth_area_codes=["PLANNING"]),
                mentor_headers,
            )
        )
        assert drafted["feedback_review_status"] == "DRAFT", (
            "feedback authoring is reachable only under the mentor identity, got "
            f"{drafted['feedback_review_status']}"
        )

        for identity in (mentor_headers, lead):
            rows, meta = validate_paginated(
                api.list_contact_logs(identity, {"match_id": program["match_id"]})
            )
            assert meta["total_count"] == 2, (
                f"both identities see both logs, got total_count {meta['total_count']}"
            )
            assert sorted(ids_of(rows)) == sorted([mentor_log["id"], lead_log["id"]])


class TestStateOfficerReach:
    """The officer owns the state half of the packet and nothing on the district half."""

    def test_state_decision_reachable_only_under_the_officer_identity(
        self, api: InductionApiClient
    ):
        """The officer clears the role gate and is stopped by the packet state instead.

        The role gate runs first and hides everything behind it: "Once the role is
        recognised, the system checks whether that role appears in the addressed
        endpoint's authorized list; if it does not, the request fails with
        `ERR_FORBIDDEN_ROLE` (HTTP 403). This check runs *before* any existence
        lookup, so a forbidden role probing an identifier that does not exist still
        receives 403 and learns nothing about which identifiers are real."

        Design: Corner/rbac/state_decision_reachable_only_under_the_officer_identity
        """
        program = build_program(api)
        packet = validate_success(
            api.create_packet(
                f.packet_payload(
                    program["novice_id"], read_novice(api, program["novice_id"])["version"]
                ),
                ADMIN,
            ),
            201,
        )

        officer_read = validate_success(api.get_packet(packet["id"], STATE_OFFICER))
        assert officer_read["id"] == packet["id"], (
            "the officer reads district data even before submission"
        )

        officer_decision = api.packet_state_decision(
            packet["id"],
            f.state_decision_payload("RETURN", return_reason="Packet reviewed before submission"),
            STATE_OFFICER,
        )
        state_gate = validate_error(officer_decision, ERR_PACKET_STATE_INVALID, 409)
        assert state_gate["error_id"] != ERR_FORBIDDEN_ROLE, (
            "the officer holds the role, so the packet's own status is what refuses it"
        )

        admin_decision = api.packet_state_decision(
            packet["id"], f.state_decision_payload("ACCEPT"), ADMIN
        )
        role_gate = validate_error(admin_decision, ERR_FORBIDDEN_ROLE, 403)
        assert role_gate["error_id"] != ERR_PACKET_STATE_INVALID, (
            "a role-denied caller never reaches the state check"
        )

        officer_transition = api.packet_transition(
            packet["id"],
            f.packet_transition_payload("WITHDRAW", reason="Officer reaching into district work"),
            STATE_OFFICER,
        )
        validate_error(officer_transition, ERR_FORBIDDEN_ROLE, 403)

        withdrawn = validate_success(
            api.packet_transition(
                packet["id"],
                f.packet_transition_payload(
                    "WITHDRAW", reason="District withdrew the packet for rework"
                ),
                ADMIN,
            )
        )
        assert withdrawn["packet_status"] == "WITHDRAWN"

        final = read_packet(api, packet["id"])
        assert final["packet_status"] == "WITHDRAWN"
        assert final["return_reason"] is None, (
            f"the refused officer decision left no trace, got {final['return_reason']}"
        )
        assert final["decided_by_user_id"] is None, (
            f"and stamped no decider, got {final['decided_by_user_id']}"
        )


class TestSeparationOfEvidenceDuties:
    """Three links of one evidence chain each refuse the same acting identity."""

    def test_segregation_of_duties_blocks_self_review_self_attestation_and_self_approval(
        self, api: InductionApiClient
    ):
        """Verifying, attesting and approving your own work are each refused as 403.

        The PRD names all four collisions in one rule: "A contact log's
        `verified_by_user_id` may not equal its `submitted_by_user_id`. A milestone
        attestation's `attested_by_user_id` may not equal the `verified_by_user_id`
        of any verified contact log on any match of that novice. A disbursement's
        `approved_by_user_id` may not equal its `prepared_by_user_id`. And a packet's
        `decided_by_user_id` may not equal its `submitted_by_user_id`. Any collision
        is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_blocks_self_review_self_attestation_and_self_approval
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-05T12:00:00Z")
        log = validate_success(
            api.create_contact_log(
                f.contact_log_payload(
                    program["match_id"],
                    "2026-08-03T09:00:00Z",
                    60,
                    "ONE_ON_ONE",
                    description="Site-lead-filed one-on-one on questioning technique",
                ),
                lead,
            ),
            201,
        )
        milestone = define_milestone(
            api,
            "IND_HRS60",
            1,
            title="First sixty verified minutes",
            required_contact_minutes=60,
            gates_license_recommendation=False,
        )
        attainment = attainment_for(api, program["novice_id"], milestone["id"])

        self_review = api.review_contact_log(
            log["id"], f.review_payload("VERIFY", note="Self-review by the filing site lead"), lead
        )
        validate_error(self_review, ERR_SEGREGATION_OF_DUTIES, 403)

        verified = validate_success(
            api.review_contact_log(
                log["id"],
                f.review_payload("VERIFY", note="Minutes confirmed by the program office"),
                ADMIN,
            )
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["credited_minutes"] == 60
        assert verified["verified_by_user_id"] == PROGRAM_OFFICE_1, (
            f"the independent verifier is stamped, got {verified['verified_by_user_id']}"
        )

        self_attestation = attainment_decision_request(
            api,
            attainment["id"],
            "ATTEST",
            ADMIN,
            evidence_note="Attested by the same officer who verified the log",
        )
        conflict = validate_error(self_attestation, ERR_SEGREGATION_OF_DUTIES, 403)
        assert conflict["error_id"] != "ERR_MILESTONE_REQUIREMENTS_NOT_MET", (
            "the sixty minutes are in fact on file, so the duty conflict is the refusal"
        )

        attested = validate_success(
            attainment_decision_request(
                api,
                attainment["id"],
                "ATTEST",
                ADMIN_2,
                evidence_note="Attested by an independent officer",
            )
        )
        assert attested["status"] == "ATTAINED"
        assert attested["attested_by_user_id"] == PROGRAM_OFFICE_2, (
            f"the independent attester is stamped, got {attested['attested_by_user_id']}"
        )

        set_clock(api, "2026-09-01T09:00:00Z")
        draft = validate_success(
            api.create_disbursement(
                f.disbursement_payload(
                    program["mentor_id"],
                    read_mentor(api, program["mentor_id"])["version"],
                    period_code="2026-Q3",
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        assert_money_cents(draft["gross_cents"], 4200, "gross_cents")
        assert_money_cents(draft["net_cents"], 4200, "net_cents")
        assert draft["prepared_by_user_id"] == PROGRAM_OFFICE_1

        self_approval = api.set_disbursement_status(
            draft["id"], f.disbursement_status_payload("APPROVED"), ADMIN
        )
        validate_error(self_approval, ERR_SEGREGATION_OF_DUTIES, 403)

        approved = validate_success(
            api.set_disbursement_status(
                draft["id"], f.disbursement_status_payload("APPROVED"), ADMIN_2
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == PROGRAM_OFFICE_2, (
            "the identical payload succeeds under an independent identity, got "
            f"{approved['approved_by_user_id']}"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 60
        assert novice["attained_milestone_count"] == 1
