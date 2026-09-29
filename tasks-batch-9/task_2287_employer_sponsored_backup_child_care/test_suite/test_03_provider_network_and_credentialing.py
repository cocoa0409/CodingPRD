"""Provider onboarding, the required credential set and network-posture movement."""

import pytest
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_provider,
    assert_envelope,
    create_provider,
    credential_payload,
    employer_payload,
    provider_payload,
    read_provider,
    setup_credentialed_provider,
    substantiated_incident,
    validate_error,
    validate_paginated,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]

REQUIRED_TYPES = ["LICENSE", "BACKGROUND_CHECK", "CPR", "INSURANCE"]


class TestProviderOnboarding:
    def test_new_provider_starts_pending_with_perfect_scores(self, api):
        """Onboarding writes a PENDING provider whose score variants both start at 100.

        PRD 3.3: "Four provider figures are derived: `quality_score` and
        `lifetime_quality_score`, the two scoring variants described in Section
        3.8, both starting at 100".

        Design: Corner/entities/corner_provider_creation_returns_pending_network_status
        """
        response = api.create_provider(
            provider_payload(
                owner_user_id="u_pm_new",
                provider_name="Sunrise Learning Center",
                market_code="MKT-LAX",
                daily_capacity_slots=6,
                max_concurrent_assignments=2,
                same_day_available=True,
            ),
            NETWORK_ADMIN,
        )
        provider = validate_success(response, expected_status=201)
        assert_envelope(response.json(), "object")
        assert_provider(provider)

        assert provider["network_status"] == "PENDING"
        assert provider["quality_score"] == pytest.approx(100, abs=0.01)
        assert provider["lifetime_quality_score"] == pytest.approx(100, abs=0.01)
        assert provider["substantiated_incident_count"] == 0
        assert provider["completed_reservation_count"] == 0
        assert provider["last_status_reason_code"] is None
        assert provider["version"] == 1

    def test_provider_listing_reports_total_count_and_more_pages(self, api):
        """Filtering happens before pagination and the meta block tracks both.

        PRD 2.3: "`limit` caps the number of rows returned; it defaults to 10, may
        be no smaller than 1, and may be no larger than 100."

        Design: Corner/entities/corner_provider_listing_paginates_with_total_count_and_has_more
        """
        create_provider(api, provider_name="Harbor Kids One", market_code="MKT-LAX")
        create_provider(api, provider_name="Harbor Kids Two", market_code="MKT-LAX")
        create_provider(api, provider_name="Harbor Kids Three", market_code="MKT-SFO")

        response = api.list_providers(NETWORK_ADMIN, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(response)
        assert_envelope(response.json(), "array")
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        rows, meta = validate_paginated(
            api.list_providers(NETWORK_ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        rows, meta = validate_paginated(
            api.list_providers(NETWORK_ADMIN, params={"market_code": "MKT-LAX"})
        )
        assert meta["total_count"] == 2
        assert all(row["market_code"] == "MKT-LAX" for row in rows)

    def test_capacity_block_under_an_unknown_provider_reports_the_provider(self, api):
        """The outermost path identifier is the one whose absence is reported.

        PRD 2.8 band 3: "Path identifiers resolve first, strictly left to right, so
        the outermost identifier in a nested path is the one whose absence is
        reported".

        Design: Corner/entities/corner_capacity_block_under_unknown_provider_returns_not_found
        """
        validate_error(
            api.create_capacity_block(
                NON_EXISTENT_UUID,
                {
                    "start_time_utc": "2026-08-20T08:00:00Z",
                    "end_time_utc": "2026-08-20T18:00:00Z",
                    "total_slots": 4,
                },
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_PROVIDER_NOT_FOUND.value,
        )
        validate_error(
            api.get_capacity_block(NON_EXISTENT_UUID, NETWORK_ADMIN),
            ApiErrorId.ERR_CAPACITYBLOCK_NOT_FOUND.value,
        )

    def test_out_of_enum_and_out_of_range_inputs_fail_request_shape(self, api):
        """Type and range violations are band 1, so nothing is written.

        PRD 2.8 band 1: "Then `admin_fee_pct` must be a decimal between 0 and 0.5
        inclusive with at most four decimal places, and `fiscal_year_start_month`
        must be an integer between 1 and 12 inclusive".

        Design: Corner/entities/corner_type_constraint_violations_rejected_as_invalid_request
        """
        validate_error(
            api.create_provider(provider_payload(care_mode="HYBRID"), NETWORK_ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )
        validate_error(
            api.create_employer(employer_payload(admin_fee_pct=0.9), NETWORK_ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        provider = create_provider(api)
        validate_error(
            api.create_capacity_block(
                provider["id"],
                {
                    "start_time_utc": "2026-08-20T08:00:00Z",
                    "end_time_utc": "2026-08-20T08:00:00Z",
                    "total_slots": 4,
                },
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
        )

        _, provider_meta = validate_paginated(api.list_providers(NETWORK_ADMIN))
        assert provider_meta["total_count"] == 1
        _, block_meta = validate_paginated(
            api.list_capacity_blocks(provider["id"], NETWORK_ADMIN)
        )
        assert block_meta["total_count"] == 0


class TestNetworkPostureErrors:
    def test_posture_state_terminal_and_immutability_guards_each_name_themselves(self, api):
        """A battery over the provider, credential and incident state guards.

        PRD 3.3: "a target unreachable from the current posture — `PENDING` to
        `PROBATION`, or `SUSPENDED` to `PROBATION`, for instance — returns
        `ERR_PROVIDER_STATE_INVALID`, while any request against a `DEPROVISIONED`
        provider returns `ERR_PROVIDER_TERMINAL`".

        Design: Corner/errors/corner_network_domain_state_and_terminal_error_battery
        """
        from test_helpers import (
            add_all_credentials,
            file_incident,
            make_care_coordinator_headers,
            review_incident,
            run_credential_review,
        )

        pending = create_provider(
            api, owner_user_id="u_pm_p1", market_code="MKT-SLC", provider_name="Salt Flats Care"
        )

        validate_error(
            api.set_network_status(
                pending["id"], {"target_status": "PROBATION", "reason_code": "EARLY"}, NETWORK_ADMIN
            ),
            ApiErrorId.ERR_PROVIDER_STATE_INVALID.value,
        )
        validate_error(
            api.credential_review(pending["id"], {"reason_code": "INITIAL"}, NETWORK_ADMIN),
            ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED.value,
        )
        validate_error(
            api.patch_provider(pending["id"], {"care_mode": "IN_HOME"}, NETWORK_ADMIN),
            ApiErrorId.ERR_PROVIDER_FIELD_IMMUTABLE.value,
        )

        patched = validate_success(
            api.patch_provider(
                pending["id"],
                {"care_mode": "CENTER_BASED", "same_day_available": False},
                NETWORK_ADMIN,
            )
        )
        assert patched["version"] == pending["version"] + 1
        assert patched["same_day_available"] is False

        second = create_provider(
            api, owner_user_id="u_pm_p2", market_code="MKT-BOI", provider_name="Boise Bright Days"
        )
        credentials = add_all_credentials(api, second["id"])
        reviewed = run_credential_review(api, second["id"])
        assert reviewed["network_status"] == "CREDENTIALED"

        insurance = credentials["INSURANCE"]
        revoked = validate_success(
            api.revoke_credential(
                insurance["id"], {"revoked_reason_code": "ISSUER_WITHDRAWN"}, NETWORK_ADMIN
            )
        )
        assert revoked["status"] == "REVOKED"
        assert read_provider(api, second["id"])["network_status"] == "SUSPENDED"

        validate_error(
            api.revoke_credential(
                insurance["id"], {"revoked_reason_code": "ISSUER_WITHDRAWN"}, NETWORK_ADMIN
            ),
            ApiErrorId.ERR_CREDENTIAL_TERMINAL.value,
        )

        deprovisioned = validate_success(
            api.set_network_status(
                second["id"],
                {"target_status": "DEPROVISIONED", "reason_code": "EXIT_NETWORK"},
                NETWORK_ADMIN,
            )
        )
        assert deprovisioned["network_status"] == "DEPROVISIONED"
        validate_error(
            api.set_network_status(
                second["id"],
                {"target_status": "CREDENTIALED", "reason_code": "REVERSE_EXIT"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_PROVIDER_TERMINAL.value,
        )

        incident = file_incident(
            api,
            pending["id"],
            "MINOR",
            filer_headers=make_care_coordinator_headers("u_cc_9"),
            category="FACILITY",
        )
        validate_error(
            api.substantiate_incident_report(
                incident["id"],
                {"qa_action": "NONE", "resolution_reason_code": "TOO_SOON"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_INCIDENTREPORT_STATE_INVALID.value,
        )
        assert review_incident(api, incident["id"])["incident_status"] == "UNDER_REVIEW"
        dismissed = validate_success(
            api.dismiss_incident_report(
                incident["id"], {"resolution_reason_code": "UNFOUNDED"}, NETWORK_ADMIN
            )
        )
        assert dismissed["incident_status"] == "DISMISSED"
        assert dismissed["qa_action"] == "NONE"
        validate_error(
            api.review_incident_report(incident["id"], NETWORK_ADMIN),
            ApiErrorId.ERR_INCIDENTREPORT_TERMINAL.value,
        )

        assert read_provider(api, pending["id"])["quality_score"] == pytest.approx(100, abs=0.01)

    def test_reinstatement_below_the_lifetime_floor_is_refused(self, api):
        """A suspended provider cannot return while its lifetime score sits under 60.

        PRD 3.3: "Reinstatement from suspension, `SUSPENDED → CREDENTIALED`,
        carries the same two preconditions as reinstatement from probation (the
        full unexpired required set, and a `lifetime_quality_score` of at least 60,
        else `ERR_REINSTATE_SCORE_TOO_LOW`)".

        Design: Corner/errors/corner_reinstate_score_too_low_blocks_return_to_network
        """
        bundle = setup_credentialed_provider(
            api, owner_user_id="u_pm_r1", market_code="MKT-ABQ", provider_name="High Desert Care"
        )
        provider_id = bundle["provider"]["id"]
        assert bundle["provider"]["network_status"] == "CREDENTIALED"
        assert bundle["provider"]["lifetime_quality_score"] == pytest.approx(100, abs=0.01)

        first = substantiated_incident(
            api,
            provider_id,
            "SEVERE",
            qa_action="PROBATION",
            filer_user_id="u_cc_7",
            resolution_reason_code="CONFIRMED_FINDING",
        )
        second = substantiated_incident(
            api,
            provider_id,
            "SEVERE",
            qa_action="SUSPENSION",
            filer_user_id="u_cc_7",
            resolution_reason_code="REPEAT_FINDING",
        )
        assert first["incident_status"] == "SUBSTANTIATED"
        assert second["incident_status"] == "SUBSTANTIATED"

        provider = read_provider(api, provider_id)
        assert provider["network_status"] == "SUSPENDED"
        assert provider["lifetime_quality_score"] == pytest.approx(40.00, abs=0.01)
        assert provider["quality_score"] == pytest.approx(40.00, abs=0.01)

        validate_error(
            api.set_network_status(
                provider_id,
                {"target_status": "CREDENTIALED", "reason_code": "REINSTATE_REQUEST"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_REINSTATE_SCORE_TOO_LOW.value,
        )

        deprovisioned = validate_success(
            api.set_network_status(
                provider_id,
                {"target_status": "DEPROVISIONED", "reason_code": "NETWORK_EXIT"},
                NETWORK_ADMIN,
            )
        )
        assert deprovisioned["network_status"] == "DEPROVISIONED"
        validate_error(
            api.set_network_status(
                provider_id,
                {"target_status": "CREDENTIALED", "reason_code": "TOO_LATE"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_PROVIDER_TERMINAL.value,
        )


class TestCredentialReviewTracksTheCredentialSet:
    """Review is a pure function of the credential set at the moment it is run."""

    def test_review_fails_on_a_partial_set_and_passes_once_it_is_complete(self, api):
        """Three of four required types is a gap, not a pass.

        PRD 3.3: "Credential review lifts `PENDING → CREDENTIALED` and requires
        that, for every one of the four required types, the provider holds a
        credential whose `status` is `VALID` and whose `expires_on` is on or after
        the logical clock's date; a gap in that set returns
        `ERR_PROVIDER_NOT_CREDENTIALED`."

        Design: Difficulty/cross_entity_state_dependency/provider_credential_review_flips_with_credential_status
        """
        provider = create_provider(
            api, owner_user_id="u_pm_cr", market_code="MKT-PIT", provider_name="Three Rivers Care"
        )
        for credential_type in ("LICENSE", "BACKGROUND_CHECK", "CPR"):
            validate_success(
                api.create_credential(
                    provider["id"], credential_payload(credential_type), NETWORK_ADMIN
                ),
                expected_status=201,
            )

        validate_error(
            api.credential_review(provider["id"], {"reason_code": "INITIAL_REVIEW"}, NETWORK_ADMIN),
            ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED.value,
        )
        assert read_provider(api, provider["id"])["network_status"] == "PENDING"

        validate_success(
            api.create_credential(
                provider["id"], credential_payload("INSURANCE"), NETWORK_ADMIN
            ),
            expected_status=201,
        )
        reviewed = validate_success(
            api.credential_review(provider["id"], {"reason_code": "INITIAL_REVIEW"}, NETWORK_ADMIN)
        )
        assert reviewed["network_status"] == "CREDENTIALED"

    def test_revoking_a_required_credential_suspends_and_blocks_manual_reinstatement(self, api):
        """The gap reopens the moment a required credential is revoked.

        PRD 3.3: "A provider may hold at most one credential per `credential_type`
        that is not `REVOKED`; a second attempt returns `ERR_DUPLICATE_KEY`."

        Design: Difficulty/cross_entity_state_dependency/provider_credential_review_flips_with_credential_status
        """
        provider = create_provider(
            api, owner_user_id="u_pm_cr2", market_code="MKT-PIT", provider_name="Allegheny Care"
        )
        credentials = {}
        for credential_type in REQUIRED_TYPES:
            credentials[credential_type] = validate_success(
                api.create_credential(
                    provider["id"], credential_payload(credential_type), NETWORK_ADMIN
                ),
                expected_status=201,
            )
        assert (
            validate_success(
                api.credential_review(
                    provider["id"], {"reason_code": "INITIAL_REVIEW"}, NETWORK_ADMIN
                )
            )["network_status"]
            == "CREDENTIALED"
        )

        revoked = validate_success(
            api.revoke_credential(
                credentials["CPR"]["id"],
                {"revoked_reason_code": "ISSUER_WITHDRAWN"},
                NETWORK_ADMIN,
            )
        )
        assert revoked["status"] == "REVOKED"
        assert read_provider(api, provider["id"])["network_status"] == "SUSPENDED"

        validate_error(
            api.set_network_status(
                provider["id"],
                {"target_status": "CREDENTIALED", "reason_code": "MANUAL_REINSTATE"},
                NETWORK_ADMIN,
            ),
            ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED.value,
        )
        assert read_provider(api, provider["id"])["network_status"] == "SUSPENDED"

        rows, meta = validate_paginated(
            api.list_credentials(provider["id"], NETWORK_ADMIN, params={"status": "VALID"})
        )
        assert meta["total_count"] == 3
        assert {row["credential_type"] for row in rows} == {
            "LICENSE",
            "BACKGROUND_CHECK",
            "INSURANCE",
        }
