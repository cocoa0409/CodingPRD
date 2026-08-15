"""Validation-order pairs: when two tiers could each fail a request, the
earlier tier's error is reported (PRD §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_active_agreement,
    create_draft_application,
    create_payer_config,
    create_practice_group,
    create_provider,
    create_submitted_application,
    roster_add_line,
    roster_term_line,
    setup_group_provider_payer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestStateBeatsSafety:
    def test_submit_withdrawn_application_of_terminated_provider(self, api):
        """PRD §2.8: "When several checks could fail on the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.8: "7. **State guards** — the target resource's state permits
        the transition, else `ERR_INVALID_STATE_TRANSITION`,
        `ERR_ROSTER_LINE_NOT_PENDING`, `ERR_CLAIM_NOT_RECOUPED`, or
        `ERR_REVALIDATION_NOT_DUE` (409)."
        PRD §2.8: "8. **Compliance gates** — the provider is not terminated,
        the CAQH attestation is current, and the agreement is active where
        required, else `ERR_PROVIDER_TERMINATED`,
        `ERR_CAQH_ATTESTATION_NOT_CURRENT`, or `ERR_AGREEMENT_NOT_ACTIVE`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_withdrawn_submit
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_draft_application(provider["id"], payer["id"])
        validate_success(api.withdraw_application(app["id"], SPECIALIST), 200)
        validate_success(
            api.terminate_provider(
                provider["id"],
                {"termination_effective_date": "2026-08-01", "reason": "departed"},
                OFFICER,
            ),
            200,
        )

        # Both tier 7 (WITHDRAWN is terminal) and tier 8 (provider TERMINATED)
        # are violated; the earlier tier wins.
        res = api.submit_application(app["id"], SPECIALIST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_enrollment_application(app["id"], SPECIALIST), 200)
        assert after["status"] == "WITHDRAWN"

    def test_approve_rejected_application_of_terminated_provider(self, api):
        """PRD §2.8: "When several checks could fail on the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §3.3: "`APPROVED`, `REJECTED`, and `WITHDRAWN` are terminal;
        invoking any further transition on a terminal application is
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_withdrawn_submit
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_submitted_application(provider["id"], payer["id"])
        validate_success(
            api.reject_application(app["id"], {"reason": "incomplete"}, PAYER_REP), 200
        )
        validate_success(
            api.terminate_provider(
                provider["id"],
                {"termination_effective_date": "2026-08-01", "reason": "departed"},
                OFFICER,
            ),
            200,
        )

        # Tier 7 (REJECTED terminal) beats tier 8 (ERR_PROVIDER_TERMINATED).
        res = api.approve_application(app["id"], PAYER_REP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_enrollment_application(app["id"], SPECIALIST), 200)
        assert after["status"] == "REJECTED"


class TestReferentialBeatsTemporal:
    def test_group_mismatch_reported_over_retro_window_breach(self, api):
        """PRD §2.8: "9. **Referential business rules** — roster-line providers
        belong to the agreement's practice group and TERM lines target an
        existing enrollment, else `ERR_PROVIDER_GROUP_MISMATCH` or
        `ERR_NO_ACTIVE_ENROLLMENT` (422)."
        PRD §2.8: "10. **Temporal rules** — retroactive windows,
        termination-date floors, and future service dates, else
        `ERR_RETRO_WINDOW_EXCEEDED`, `ERR_TERMINATION_DATE_INVALID`, or
        `ERR_FUTURE_SERVICE_DATE` (422)."
        PRD §3.4: "Every line's provider must belong to the agreement's
        practice group, or submission fails with `ERR_PROVIDER_GROUP_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_roster_line
        """
        g1 = create_practice_group(name="G1", tax_id="T1", group_npi="GNPI1")
        g2 = create_practice_group(name="G2", tax_id="T2", group_npi="GNPI2")
        provider = create_provider(g2["id"])  # belongs to G2, not G1
        payer = create_payer_config()
        agreement = create_active_agreement(g1["id"], payer["id"])

        # The line violates tier 9 (wrong group) AND tier 10 (2026-01-20 is
        # more than 90 days before the startup date 2026-08-01).
        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": agreement["version"],
                "lines": [
                    roster_add_line(
                        provider["id"], expected_effective_date="2026-01-20",
                    )
                ],
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_PROVIDER_GROUP_MISMATCH)

        files, meta = validate_paginated(
            api.list_roster_files(SPECIALIST, params={"agreement_id": agreement["id"]})
        )
        assert files == [] and meta["total_count"] == 0, "no roster persisted"

    def test_group_mismatch_reported_for_term_line_with_retro_breach(self, api):
        """PRD §2.8: "When several checks could fail on the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §3.4: "Every line's provider must belong to the agreement's
        practice group, or submission fails with `ERR_PROVIDER_GROUP_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_roster_line
        """
        g1 = create_practice_group(name="G1", tax_id="T1", group_npi="GNPI1")
        g2 = create_practice_group(name="G2", tax_id="T2", group_npi="GNPI2")
        provider = create_provider(g2["id"])
        payer = create_payer_config()
        agreement = create_active_agreement(g1["id"], payer["id"])

        # TERM line: wrong group (tier 9) plus a retro-window breach by one day
        # (2026-05-02 < 2026-08-01 - 90d; tier 10).
        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": agreement["version"],
                "lines": [
                    roster_term_line(
                        provider["id"], expected_effective_date="2026-05-02",
                    )
                ],
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_PROVIDER_GROUP_MISMATCH)

        files, meta = validate_paginated(
            api.list_roster_files(SPECIALIST, params={"agreement_id": agreement["id"]})
        )
        assert files == [] and meta["total_count"] == 0
