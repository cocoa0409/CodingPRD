"""Collection: the order the gates fire in, and the terms pinned onto a record."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    api_client,
    assert_instant,
    child_data_record_payload,
    collect_record,
    create_activity,
    create_age_screen,
    create_consent,
    create_retention_schedule,
    deliver_notice_to_consent,
    grant_consent,
    mixed_audience_service,
    open_verification,
    published_notice,
    read_service,
    set_screen_status,
    validate_error,
)


def _collection_surroundings(child_pseudonym: str = "child-201", activate_screen: bool = True) -> dict:
    """A mixed-audience service with a screen, an activity, a schedule and a notice."""
    service = mixed_audience_service(name="Collection Gate Service")
    service_id = service["id"]
    screen = create_age_screen(service_id)
    screen = set_screen_status(screen["id"], "IN_REVIEW", ENGINEER_HEADERS)
    if activate_screen:
        screen = set_screen_status(screen["id"], "ACTIVE", OFFICER_HEADERS)
    activity = create_activity(
        service_id, participation_required_elements=["SCREEN_NAME"]
    )
    create_retention_schedule(
        service_id,
        data_element_code="SCREEN_NAME",
        purpose_code="PARTICIPATION_CORE",
        retention_days=30,
        disposal_method="ANONYMIZE",
    )
    notice = published_notice(service_id)
    consent = create_consent(
        service_id,
        notice["id"],
        parent_email="parent@example.com",
        child_pseudonym=child_pseudonym,
    )
    return {
        "service_id": service_id,
        "screen": screen,
        "activity_id": activity["id"],
        "notice_id": notice["id"],
        "consent_id": consent["id"],
    }


class TestConsentStateGatePrecedesMinimization:
    """Transition legality is decided before the whitelist is consulted."""

    def test_01_an_ungranted_consent_reports_the_consent_state_not_the_whitelist(self):
        """A pending consent short-circuits the minimization check.

        The precedence list places "9. **Transition legality.**" — including
        `ERR_CONSENT_NOT_GRANTED` — ahead of "20. **Data minimization**, else
        `ERR_ELEMENT_NOT_REASONABLY_NECESSARY`". "a consent whose `status` is neither
        `GRANTED` nor `REVOKED` is refused with `ERR_CONSENT_NOT_GRANTED`".

        Design: Difficulty/priority_pair_validation_conflict/consent_state_gate_p70_beats_minimization_p110
        """
        surroundings = _collection_surroundings()
        deliver_notice_to_consent(surroundings["consent_id"])
        open_verification(surroundings["consent_id"])

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    surroundings["service_id"],
                    surroundings["consent_id"],
                    surroundings["activity_id"],
                    data_element_code="FULL_NAME",
                    purpose_code="PARTICIPATION_CORE",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_CONSENT_NOT_GRANTED",
        )

        service = read_service(surroundings["service_id"])
        assert service["live_child_data_element_count"] == 0
        assert service["lifetime_collected_element_count"] == 0

    def test_02_once_granted_the_same_payload_fails_the_whitelist(self):
        """With the consent usable, the element outside the whitelist is refused.

        "When the purpose is `PARTICIPATION_CORE`, the `data_element_code` must appear in
        the referenced activity's `participation_required_elements`; anything else is not
        reasonably necessary for participation and is refused with
        `ERR_ELEMENT_NOT_REASONABLY_NECESSARY`."

        Design: Difficulty/priority_pair_validation_conflict/consent_state_gate_p70_beats_minimization_p110
        """
        surroundings = _collection_surroundings()
        deliver_notice_to_consent(surroundings["consent_id"])
        open_verification(surroundings["consent_id"])
        grant_consent(surroundings["consent_id"])

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    surroundings["service_id"],
                    surroundings["consent_id"],
                    surroundings["activity_id"],
                    data_element_code="FULL_NAME",
                    purpose_code="PARTICIPATION_CORE",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_ELEMENT_NOT_REASONABLY_NECESSARY",
        )

        service = read_service(surroundings["service_id"])
        assert service["lifetime_collected_element_count"] == 0, (
            "a refused collection creates no record, got "
            f"{service['lifetime_collected_element_count']}"
        )

    def test_03_a_whitelisted_element_is_collected_with_pinned_retention_terms(self):
        """The accepted record copies the pseudonym and pins the schedule's terms.

        "Its `child_pseudonym` is copied from the referenced consent rather than supplied
        by the caller ... The governing schedule's `retention_days` and `disposal_method`
        are copied onto the record as `retention_days_applied` and
        `disposal_method_applied` — pinned copies ... and `disposal_due_at` is set to
        `collected_at` plus `retention_days_applied` days."

        Design: Difficulty/priority_pair_validation_conflict/consent_state_gate_p70_beats_minimization_p110
        """
        surroundings = _collection_surroundings()
        deliver_notice_to_consent(surroundings["consent_id"])
        open_verification(surroundings["consent_id"])
        grant_consent(surroundings["consent_id"])

        record = collect_record(
            surroundings["service_id"],
            surroundings["consent_id"],
            surroundings["activity_id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
        )

        assert record["status"] == "COLLECTED"
        assert record["child_pseudonym"] == "child-201", (
            f"the pseudonym is copied from the consent, got {record['child_pseudonym']}"
        )
        assert record["retention_days_applied"] == 30
        assert record["disposal_method_applied"] == "ANONYMIZE"
        assert_instant(record["collected_at"], STARTUP_CLOCK, "collected_at")
        assert_instant(record["disposal_due_at"], "2026-08-31T00:00:00Z", "disposal_due_at")
        assert record["scheduled_run_sequence"] is None
        assert record["disposed_at"] is None

        service = read_service(surroundings["service_id"])
        assert service["live_child_data_element_count"] == 1
        assert service["lifetime_collected_element_count"] == 1


class TestCollectionGatedByAgeScreenState:
    """A mixed-audience service needs a live screen and an under-13 outcome."""

    def test_04_a_screen_still_in_review_does_not_permit_collection(self):
        """Review is not activation.

        "the service must have an age screen whose `status` is `ACTIVE`, otherwise
        collection is refused with `ERR_AGE_SCREEN_NOT_ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/collection_gated_by_age_screen_status_and_screening_outcome
        """
        surroundings = _collection_surroundings(activate_screen=False)
        assert surroundings["screen"]["status"] == "IN_REVIEW"
        assert surroundings["screen"]["neutrality_violation_codes"] == []
        deliver_notice_to_consent(surroundings["consent_id"])
        open_verification(surroundings["consent_id"])
        grant_consent(surroundings["consent_id"])

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    surroundings["service_id"],
                    surroundings["consent_id"],
                    surroundings["activity_id"],
                    data_element_code="SCREEN_NAME",
                    purpose_code="PARTICIPATION_CORE",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_AGE_SCREEN_NOT_ACTIVE",
        )

        service = read_service(surroundings["service_id"])
        assert service["live_child_data_element_count"] == 0
        assert service["lifetime_collected_element_count"] == 0

    def test_05_activating_the_screen_opens_collection(self):
        """Officer activation stamps the screen and lets the same call through.

        "A `ComplianceOfficer` moves the screen `IN_REVIEW → ACTIVE` ... A successful
        activation stamps `activated_at` with the current logical-clock instant".

        Design: Difficulty/cross_entity_state_dependency/collection_gated_by_age_screen_status_and_screening_outcome
        """
        surroundings = _collection_surroundings(activate_screen=False)
        deliver_notice_to_consent(surroundings["consent_id"])
        open_verification(surroundings["consent_id"])
        grant_consent(surroundings["consent_id"])

        activated = set_screen_status(surroundings["screen"]["id"], "ACTIVE", OFFICER_HEADERS)
        assert activated["status"] == "ACTIVE"
        assert_instant(activated["activated_at"], STARTUP_CLOCK, "activated_at")

        record = collect_record(
            surroundings["service_id"],
            surroundings["consent_id"],
            surroundings["activity_id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
        )

        assert record["status"] == "COLLECTED"
        assert_instant(record["disposal_due_at"], "2026-08-31T00:00:00Z", "disposal_due_at")
        service = read_service(surroundings["service_id"])
        assert service["live_child_data_element_count"] == 1
        assert service["lifetime_collected_element_count"] == 1

    def test_06_a_thirteen_plus_outcome_on_a_mixed_service_is_not_a_child_subject(self):
        """On a mixed-audience service the outcome itself must say under 13.

        "the `age_screen_outcome` presented must be `UNDER_13`, because an outcome of
        `THIRTEEN_PLUS` means the subject is outside the child-data surface and is refused
        with `ERR_NOT_CHILD_SUBJECT`" — the code reserved for the child-directed-primary
        case, `ERR_AGE_SCREEN_NOT_PERMITTED`, belongs to the other determination.

        Design: Difficulty/cross_entity_state_dependency/collection_gated_by_age_screen_status_and_screening_outcome
        """
        surroundings = _collection_surroundings()
        deliver_notice_to_consent(surroundings["consent_id"])
        open_verification(surroundings["consent_id"])
        grant_consent(surroundings["consent_id"])
        collect_record(
            surroundings["service_id"],
            surroundings["consent_id"],
            surroundings["activity_id"],
            data_element_code="SCREEN_NAME",
            purpose_code="PARTICIPATION_CORE",
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    surroundings["service_id"],
                    surroundings["consent_id"],
                    surroundings["activity_id"],
                    data_element_code="SCREEN_NAME",
                    purpose_code="PARTICIPATION_CORE",
                    age_screen_outcome="THIRTEEN_PLUS",
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_NOT_CHILD_SUBJECT",
        )

        service = read_service(surroundings["service_id"])
        assert service["live_child_data_element_count"] == 1, (
            "the refused collection adds nothing, got "
            f"{service['live_child_data_element_count']}"
        )
        assert service["lifetime_collected_element_count"] == 1
