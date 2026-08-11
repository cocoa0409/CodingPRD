"""Negotiation cycle, signature gates, OCC on revise, terminal lockdown."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    create_employer,
    create_approved_assessment,
    create_agreement,
    create_quoted_agreement,
    api_client,
    TEST_USERS,
    make_employer_contact_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestNegotiateReviseCycle:
    def test_negotiate_then_revise_closes_cycle(self, api):
        """PRD §3.2: "An `EmployerContact` requests changes, moving the
        agreement from `QUOTED` to `NEGOTIATING`". "A successful revision
        moves the agreement from `NEGOTIATING` back to `QUOTED`, increments
        `negotiation_round` by one, recomputes `quoted_total_cents` through
        the same pricing rule from whatever revised inputs were supplied".

        Design: Difficulty/non_linear_state_machine/agreement_quote_negotiate_revise_cycle
        """
        emp = create_employer(legal_name="Zeta Group", industry_code="561320",
                              contact_email="hr@zeta.example")
        na = create_approved_assessment(
            emp["id"],
            curriculum_modules=[{"code": "OPS-1", "hours": 10,
                                 "required_credential_codes": []}],
        )
        agr = create_quoted_agreement(
            emp["id"], na["id"],
            pricing_model="PER_PARTICIPANT", delivery_mode="ON_SITE",
            est_participant_count=20, est_delivery_hours=10,
            target_start_date="2026-07-01T00:00:00Z", max_cohorts=2,
        )
        ec = make_employer_contact_headers(emp["id"])
        neg = validate_success(api_client.negotiate_training_agreement(agr["id"], ec))
        assert neg["contract_status"] == "NEGOTIATING"

        cur = get_success_data(api_client.get_training_agreement(agr["id"], COORD))
        rev = validate_success(
            api_client.revise_training_agreement(
                agr["id"],
                {"expected_agreement_version": cur["version"], "est_participant_count": 25},
                COORD,
            )
        )
        assert rev["contract_status"] == "QUOTED"
        assert rev["negotiation_round"] == 1
        # n=25: tuition 450000+600000; materials 187500; surcharge 25000
        assert rev["quoted_total_cents"] == 1262500, (
            f"expected 1262500, got {rev['quoted_total_cents']}"
        )

    def test_revise_increments_round_each_cycle(self, api):
        """PRD §3.2: "increments `negotiation_round` by one" on every
        successful revision through the QUOTED -> NEGOTIATING -> QUOTED loop.

        Design: Difficulty/non_linear_state_machine/agreement_quote_negotiate_revise_cycle
        """
        emp = create_employer()
        na = create_approved_assessment(emp["id"])
        agr = create_quoted_agreement(emp["id"], na["id"], est_participant_count=20,
                                      est_delivery_hours=10,
                                      target_start_date="2026-07-01T00:00:00Z")
        ec = make_employer_contact_headers(emp["id"])
        for expected_round in (1, 2):
            validate_success(api_client.negotiate_training_agreement(agr["id"], ec))
            cur = get_success_data(api_client.get_training_agreement(agr["id"], COORD))
            rev = validate_success(
                api_client.revise_training_agreement(
                    agr["id"], {"expected_agreement_version": cur["version"]}, COORD
                )
            )
            assert rev["negotiation_round"] == expected_round
            assert rev["contract_status"] == "QUOTED"


class TestStaleAssessmentPin:
    def test_stale_pin_blocks_sign_then_refresh_allows(self, api):
        """PRD §3.2: "the pinned assessment must still be current —
        `assessment_version_pinned` equal to the assessment's present
        `version`, with the assessment still `APPROVED` — otherwise the sign
        fails with `ERR_STALE_ASSESSMENT`."
        PRD §3.2: "refreshing the pin is allowed while the agreement is in
        `DRAFT`, `QUOTED`, or `NEGOTIATING`, requires the assessment to be
        `APPROVED` (otherwise `ERR_ASSESSMENT_NOT_APPROVED`), and sets
        `assessment_version_pinned` to the assessment's current `version`."

        Design: Corner/validations/stale_assessment_version_blocks_sign_proper
        """
        emp = create_employer(legal_name="Pin2Co", industry_code="111188",
                              contact_email="hr@pin2.example")
        # Create assessment and agreement BEFORE approval: pin captures v1.
        na = get_success_data(
            api_client.create_needs_assessment(
                emp["id"],
                {"title": "T", "skill_gaps": ["t"], "target_roles": ["r"],
                 "curriculum_modules": [{"code": "T-1", "hours": 2,
                                         "required_credential_codes": []}]},
                COORD,
            )
        )
        agr = create_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                               est_participant_count=2, est_delivery_hours=2)
        pin0 = agr["assessment_version_pinned"]

        # Walk assessment through a full revision cycle, then approve.
        validate_success(api_client.submit_needs_assessment(na["id"], COORD))
        validate_success(api_client.request_revision_needs_assessment(na["id"], ADMIN))
        validate_success(api_client.submit_needs_assessment(na["id"], COORD))
        approved = validate_success(api_client.approve_needs_assessment(na["id"], ADMIN))

        q = validate_success(api_client.quote_training_agreement(agr["id"], COORD))
        # FLAT_COHORT n=2: 480000 + 0 overage + 25000 surcharge
        assert q["quoted_total_cents"] == 505000

        ec = make_employer_contact_headers(emp["id"])
        err = api_client.sign_training_agreement(agr["id"], ec)
        validate_error(err, ApiErrorId.ERR_STALE_ASSESSMENT)

        repinned = validate_success(api_client.refresh_assessment_pin(agr["id"], COORD))
        assert repinned["assessment_version_pinned"] == approved["version"]
        assert repinned["assessment_version_pinned"] != pin0

        signed = validate_success(api_client.sign_training_agreement(agr["id"], ec))
        assert signed["contract_status"] == "SIGNED"


class TestQuoteExpiry:
    def test_sign_after_quote_expiry_rejected(self, api):
        """PRD §3.2: "the quote must still be within its window (otherwise
        `ERR_QUOTE_EXPIRED`)". PRD §3.2: "A successful quote stamps
        `quote_issued_at` with the current time and sets `quote_expires_at`
        thirty days later."

        Design: Corner/validations/quote_expired_sign_rejected
        """
        emp = create_employer(legal_name="ExpCo", industry_code="111187",
                              contact_email="hr@exp.example")
        na = create_approved_assessment(emp["id"])
        agr = create_quoted_agreement(
            emp["id"], na["id"], pricing_model="FLAT_COHORT",
            est_participant_count=2, est_delivery_hours=2,
            target_start_date="2026-07-15T00:00:00Z",
        )
        # quoted at 2026-05-01 -> expires 2026-05-31; advance past it
        validate_success(api_client.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))
        resp = api_client.sign_training_agreement(
            agr["id"], make_employer_contact_headers(emp["id"])
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)


class TestTerminalLockdown:
    def test_sign_on_cancelled_agreement_rejected(self, api):
        """PRD §2.8 item 5: "the target entity must be in a state from which
        the requested transition exists (`ERR_INVALID_STATE`), which also
        covers duplicate transitions and terminal lockdown."
        PRD §3.2: "Operations that target an agreement already in `COMPLETED`
        or `CANCELLED` are rejected with `ERR_AGREEMENT_TERMINAL`."
        Both gates apply to a sign attempted on a CANCELLED agreement: §2.8
        item 5 (state legality, priority 5) names terminal lockdown as
        `ERR_INVALID_STATE`, while §3.2's sentence names
        `ERR_AGREEMENT_TERMINAL` (priority 6) for any operation on a terminal
        agreement. The PRD does not state which pre-empts, so either error_id
        satisfies the lockdown rule.

        Design: Corner/state_machines/cancelled_agreement_terminal_lockdown_rejected
        """
        emp = create_employer(legal_name="TermCo", industry_code="111198",
                              contact_email="hr@term.example")
        na = create_approved_assessment(emp["id"])
        agr = create_quoted_agreement(emp["id"], na["id"])
        validate_success(api_client.cancel_training_agreement(agr["id"], COORD))
        resp = api_client.sign_training_agreement(
            agr["id"], make_employer_contact_headers(emp["id"])
        )
        validate_error_is_one_of(resp, ["ERR_AGREEMENT_TERMINAL", "ERR_INVALID_STATE"])
        cur = get_success_data(api_client.get_training_agreement(agr["id"], COORD))
        assert cur["contract_status"] == "CANCELLED"
