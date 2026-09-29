"""Parental rights: the two fulfilment scopes and the deletion cascade."""

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
    create_integration,
    create_retention_schedule,
    create_rights_request,
    deliver_notice_to_consent,
    grant_consent,
    mixed_audience_service,
    open_verification,
    published_notice,
    read_consent,
    read_integration,
    read_record,
    read_service,
    set_integration_status,
    set_rights_status,
    set_screen_status,
    validate_error,
)


def _ready_service(name: str, elements, vendors=None) -> dict:
    """A mixed-audience service with a live screen, an activity, schedules and a notice."""
    service = mixed_audience_service(name=name)
    service_id = service["id"]
    screen = create_age_screen(service_id)
    set_screen_status(screen["id"], "IN_REVIEW", ENGINEER_HEADERS)
    set_screen_status(screen["id"], "ACTIVE", OFFICER_HEADERS)
    activity = create_activity(
        service_id,
        participation_required_elements=[element for element, _, _ in elements],
    )
    for element, retention_days, disposal_method in elements:
        create_retention_schedule(
            service_id,
            data_element_code=element,
            purpose_code="PARTICIPATION_CORE",
            retention_days=retention_days,
            disposal_method=disposal_method,
        )
    notice = published_notice(
        service_id, disclosed_integration_vendors=list(vendors or [])
    )
    return {"service_id": service_id, "activity_id": activity["id"], "notice_id": notice["id"]}


def _granted_consent(
    service_id: str,
    notice_id: str,
    parent_email: str,
    child_pseudonym: str,
    consent_method: str = "KNOWLEDGE_BASED_AUTH",
    intended_uses=None,
) -> dict:
    consent = create_consent(
        service_id,
        notice_id,
        parent_email=parent_email,
        child_pseudonym=child_pseudonym,
        consent_method=consent_method,
        intended_uses=intended_uses or ["PARTICIPATION_CORE"],
    )
    deliver_notice_to_consent(consent["id"])
    open_verification(consent["id"])
    return grant_consent(consent["id"])


def _verified_request(
    service_id: str,
    consent_id: str,
    right_type: str,
    requester_email: str,
    verification_method: str,
) -> dict:
    request = create_rights_request(
        service_id, consent_id, right_type=right_type, requester_email=requester_email
    )
    set_rights_status(
        request["id"], "VERIFYING", OFFICER_HEADERS, verification_method=verification_method
    )
    return set_rights_status(request["id"], "VERIFIED", OFFICER_HEADERS)


class TestRightsScopeVariants:
    """The same child, two consents, and two very different resolved scopes."""

    def test_01_parent_consent_scope_sees_only_its_own_consents_records(self):
        """The narrow scope is drawn around one consent record.

        "Under `PARENT_CONSENT_SCOPE`, the scope is the set of that service's child data
        records whose `consent_request_id` equals the referenced consent's own identifier
        and whose `status` is `COLLECTED` or `SCHEDULED_FOR_DISPOSAL` — only what was
        collected under the single consent this parent holds".

        Design: Difficulty/dual_variant_calc/rights_scope_variant_divergence_parent_consent_vs_child_identity
        """
        ready = _ready_service("Two Guardian Service", [("SCREEN_NAME", 30, "ANONYMIZE")])
        first = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian.one@x.test", "child-014"
        )
        second = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian.two@x.test", "child-014"
        )
        collect_record(ready["service_id"], first["id"], ready["activity_id"])
        collect_record(ready["service_id"], second["id"], ready["activity_id"])

        request = _verified_request(
            ready["service_id"], first["id"], "REVIEW", "guardian.one@x.test", "GOVT_ID_MATCH"
        )
        fulfilled = set_rights_status(
            request["id"],
            "FULFILLED",
            OFFICER_HEADERS,
            scope_mode="PARENT_CONSENT_SCOPE",
        )

        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["scope_mode"] == "PARENT_CONSENT_SCOPE"
        assert fulfilled["in_scope_record_count"] == 1, (
            "only the record collected under this consent is in scope, got "
            f"{fulfilled['in_scope_record_count']}"
        )
        assert_instant(fulfilled["fulfilled_at"], STARTUP_CLOCK, "fulfilled_at")

    def test_02_child_identity_scope_sees_every_record_about_the_child(self):
        """The wide scope crosses every consent record for the same child.

        "Under `CHILD_IDENTITY_SCOPE`, the scope is the set of records belonging to the
        referenced consent's own service whose `child_pseudonym` equals the referenced
        consent's `child_pseudonym` ... which is a strictly larger set whenever the child
        has more than one consent record." For `REVIEW`, "nothing is mutated".

        Design: Difficulty/dual_variant_calc/rights_scope_variant_divergence_parent_consent_vs_child_identity
        """
        ready = _ready_service("Child Identity Scope Service", [("SCREEN_NAME", 30, "ANONYMIZE")])
        first = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian.one@x.test", "child-014"
        )
        second = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian.two@x.test", "child-014"
        )
        record_one = collect_record(ready["service_id"], first["id"], ready["activity_id"])
        record_two = collect_record(ready["service_id"], second["id"], ready["activity_id"])

        request = _verified_request(
            ready["service_id"], second["id"], "REVIEW", "guardian.two@x.test", "GOVT_ID_MATCH"
        )
        fulfilled = set_rights_status(
            request["id"],
            "FULFILLED",
            OFFICER_HEADERS,
            scope_mode="CHILD_IDENTITY_SCOPE",
        )

        assert fulfilled["in_scope_record_count"] == 2, (
            "both records about the child are in scope, got "
            f"{fulfilled['in_scope_record_count']}"
        )
        assert read_record(record_one["id"])["status"] == "COLLECTED", (
            "a review fulfilment destroys nothing"
        )
        assert read_record(record_two["id"])["status"] == "COLLECTED"
        service = read_service(ready["service_id"])
        assert service["live_child_data_element_count"] == 2
        assert service["lifetime_collected_element_count"] == 2
        assert service["active_consent_count"] == 2
        assert read_consent(first["id"])["status"] == "GRANTED"
        assert read_consent(second["id"])["status"] == "GRANTED"


class TestDeletionCascadeUnfreezesToRestricted:
    """Deleting the last live data walks the whole six-link chain in one request."""

    def test_03_an_approved_behavioral_network_with_a_persistent_identifier_freezes(self):
        """Eighty exposure points freeze the service.

        The base weights include "`BEHAVIORAL_AD_NETWORK` 40 ... doubled when
        `collects_persistent_identifier` is true", and "if `third_party_exposure_points` is
        80 or more, the posture is `FROZEN`."

        Design: Difficulty/transitive_cascade/deletion_fulfilment_six_link_cascade_unfreezes_to_restricted
        """
        ready = _ready_service(
            "Frozen Exposure Service",
            [("SCREEN_NAME", 30, "ANONYMIZE"), ("GEOLOCATION_PRECISE", 30, "CRYPTO_ERASE")],
            vendors=["AdKid Network"],
        )
        consent = _granted_consent(
            ready["service_id"],
            ready["notice_id"],
            "guardian@x.test",
            "child-77",
            consent_method="GOVT_ID_MATCH",
            intended_uses=["PARTICIPATION_CORE", "THIRD_PARTY_DISCLOSURE"],
        )
        assert consent["required_tier_at_creation"] == 3
        collect_record(ready["service_id"], consent["id"], ready["activity_id"])
        collect_record(
            ready["service_id"],
            consent["id"],
            ready["activity_id"],
            data_element_code="GEOLOCATION_PRECISE",
        )

        integration = create_integration(
            ready["service_id"],
            vendor_name="AdKid Network",
            integration_type="BEHAVIORAL_AD_NETWORK",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        assert integration["exposure_points"] == 80
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")

        service = read_service(ready["service_id"])
        assert service["third_party_exposure_points"] == 80
        assert service["compliance_posture"] == "FROZEN", (
            f"80 points freezes the service, got {service['compliance_posture']}"
        )
        assert service["live_child_data_element_count"] == 2
        assert service["granted_disclosure_consent_count"] == 1

    def test_04_deleting_every_record_revokes_the_consent_and_reopens_the_audit(self):
        """The chain disposes, revokes, reopens the audit and lands on restricted.

        "every child data record in the resolved scope ... is moved to `DISPOSED` ... that
        consent is moved `GRANTED → REVOKED` with `revocation_reason` set to
        `DELETION_FULFILLED` ... every third-party integration of the service whose `status`
        is `APPROVED`, whose `placement_area` is `CHILD_DIRECTED_AREA` and whose
        `collects_persistent_identifier` is true is moved `APPROVED → AUDIT_PENDING`. And
        because those integrations left `APPROVED`, `third_party_exposure_points` and
        `open_audit_count` are recomputed and `compliance_posture` is re-derived".

        Design: Difficulty/transitive_cascade/deletion_fulfilment_six_link_cascade_unfreezes_to_restricted
        """
        ready = _ready_service(
            "Deletion Cascade Service",
            [("SCREEN_NAME", 30, "ANONYMIZE"), ("GEOLOCATION_PRECISE", 30, "CRYPTO_ERASE")],
            vendors=["AdKid Network"],
        )
        consent = _granted_consent(
            ready["service_id"],
            ready["notice_id"],
            "guardian@x.test",
            "child-77",
            consent_method="GOVT_ID_MATCH",
            intended_uses=["PARTICIPATION_CORE", "THIRD_PARTY_DISCLOSURE"],
        )
        screen_name_record = collect_record(
            ready["service_id"], consent["id"], ready["activity_id"]
        )
        geo_record = collect_record(
            ready["service_id"],
            consent["id"],
            ready["activity_id"],
            data_element_code="GEOLOCATION_PRECISE",
        )
        integration = create_integration(
            ready["service_id"],
            vendor_name="AdKid Network",
            integration_type="BEHAVIORAL_AD_NETWORK",
            collects_persistent_identifier=True,
            placement_area="CHILD_DIRECTED_AREA",
        )
        set_integration_status(integration["id"], "AUDIT_PENDING")
        set_integration_status(integration["id"], "APPROVED")

        request = _verified_request(
            ready["service_id"], consent["id"], "DELETE", "guardian@x.test", "GOVT_ID_MATCH"
        )
        fulfilled = set_rights_status(
            request["id"],
            "FULFILLED",
            OFFICER_HEADERS,
            scope_mode="CHILD_IDENTITY_SCOPE",
        )

        assert fulfilled["in_scope_record_count"] == 2
        assert_instant(fulfilled["fulfilled_at"], STARTUP_CLOCK, "fulfilled_at")

        disposed_screen_name = read_record(screen_name_record["id"])
        disposed_geo = read_record(geo_record["id"])
        assert disposed_screen_name["status"] == "DISPOSED"
        assert disposed_geo["status"] == "DISPOSED"
        assert disposed_screen_name["disposal_method_applied"] == "ANONYMIZE", (
            "destruction uses each record's own pinned method"
        )
        assert disposed_geo["disposal_method_applied"] == "CRYPTO_ERASE"
        assert_instant(disposed_screen_name["disposed_at"], STARTUP_CLOCK, "disposed_at")

        revoked = read_consent(consent["id"])
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "DELETION_FULFILLED", (
            f"the cascade records DELETION_FULFILLED, got {revoked['revocation_reason']}"
        )

        re_audited = read_integration(ready["service_id"], integration["id"])
        assert re_audited["status"] == "AUDIT_PENDING"
        assert re_audited["exposure_points"] == 80, (
            "the integration keeps the weight of its own declaration"
        )

        service = read_service(ready["service_id"])
        assert service["live_child_data_element_count"] == 0
        assert service["lifetime_collected_element_count"] == 2
        assert service["active_consent_count"] == 0
        assert service["granted_disclosure_consent_count"] == 0
        assert service["third_party_exposure_points"] == 0, (
            "the re-audited integration's points leave the total, got "
            f"{service['third_party_exposure_points']}"
        )
        assert service["open_audit_count"] == 1
        assert service["compliance_posture"] == "RESTRICTED", (
            "with the freeze gone and one audit open the service is RESTRICTED, got "
            f"{service['compliance_posture']}"
        )
        assert service["audit_decision_count"] == 1
        assert service["posture_override"] is None


class TestLiveCountFallsWhileLifetimeCountGrows:
    """One counter rises and falls; the other only ever rises."""

    def test_05_deletion_returns_the_live_count_to_zero_without_touching_the_lifetime_count(
        self,
    ):
        """Disposal empties the live set and leaves the lifetime total alone.

        "`live_child_data_element_count` counts the service's records whose `status` is
        `COLLECTED` or `SCHEDULED_FOR_DISPOSAL` — the data actually still held — and it
        rises and falls. `lifetime_collected_element_count` counts every record the service
        has ever created, including those already `DISPOSED`, and is monotonically
        non-decreasing."

        Design: Difficulty/compensating_invariant/live_element_count_returns_to_zero_while_lifetime_count_only_grows
        """
        ready = _ready_service(
            "Live Versus Lifetime Service",
            [("SCREEN_NAME", 30, "ANONYMIZE"), ("SCHOOL_NAME", 60, "OVERWRITE")],
        )
        consent = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian@x.test", "child-33"
        )
        first = collect_record(ready["service_id"], consent["id"], ready["activity_id"])
        second = collect_record(
            ready["service_id"],
            consent["id"],
            ready["activity_id"],
            data_element_code="SCHOOL_NAME",
        )
        assert_instant(first["disposal_due_at"], "2026-08-31T00:00:00Z", "disposal_due_at")
        assert_instant(second["disposal_due_at"], "2026-09-30T00:00:00Z", "disposal_due_at")
        before = read_service(ready["service_id"])
        assert before["live_child_data_element_count"] == 2
        assert before["lifetime_collected_element_count"] == 2
        assert before["active_consent_count"] == 1

        request = _verified_request(
            ready["service_id"],
            consent["id"],
            "DELETE",
            "guardian@x.test",
            "SIGNED_FORM_RETURN",
        )
        fulfilled = set_rights_status(
            request["id"],
            "FULFILLED",
            OFFICER_HEADERS,
            scope_mode="PARENT_CONSENT_SCOPE",
        )

        assert fulfilled["in_scope_record_count"] == 2
        assert read_record(first["id"])["disposal_method_applied"] == "ANONYMIZE"
        assert read_record(second["id"])["disposal_method_applied"] == "OVERWRITE"
        after = read_service(ready["service_id"])
        assert after["live_child_data_element_count"] == 0, (
            f"every record was destroyed, got {after['live_child_data_element_count']}"
        )
        assert after["lifetime_collected_element_count"] == 2, (
            "the lifetime total never falls, got "
            f"{after['lifetime_collected_element_count']}"
        )
        assert after["active_consent_count"] == 0
        assert read_consent(consent["id"])["revocation_reason"] == "DELETION_FULFILLED"

    def test_06_a_fresh_consent_grows_the_lifetime_count_past_the_revoked_one(self):
        """A revoked consent refuses further collection while the lifetime total climbs.

        "attempting to collect against a revoked consent surfaces here as
        `ERR_CONSENT_REVOKED` (409)", and each accepted collection recomputes both counters,
        of which the lifetime one "is monotonically non-decreasing."

        Design: Difficulty/compensating_invariant/live_element_count_returns_to_zero_while_lifetime_count_only_grows
        """
        ready = _ready_service(
            "Recollection Service",
            [("SCREEN_NAME", 30, "ANONYMIZE"), ("SCHOOL_NAME", 60, "OVERWRITE")],
        )
        consent = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian@x.test", "child-33"
        )
        collect_record(ready["service_id"], consent["id"], ready["activity_id"])
        collect_record(
            ready["service_id"],
            consent["id"],
            ready["activity_id"],
            data_element_code="SCHOOL_NAME",
        )
        request = _verified_request(
            ready["service_id"],
            consent["id"],
            "DELETE",
            "guardian@x.test",
            "SIGNED_FORM_RETURN",
        )
        set_rights_status(
            request["id"],
            "FULFILLED",
            OFFICER_HEADERS,
            scope_mode="PARENT_CONSENT_SCOPE",
        )

        validate_error(
            api_client.create_child_data_record(
                child_data_record_payload(
                    ready["service_id"], consent["id"], ready["activity_id"]
                ),
                ENGINEER_HEADERS,
            ),
            "ERR_CONSENT_REVOKED",
        )

        replacement = _granted_consent(
            ready["service_id"], ready["notice_id"], "guardian.new@x.test", "child-34"
        )
        collect_record(ready["service_id"], replacement["id"], ready["activity_id"])

        after = read_service(ready["service_id"])
        assert after["live_child_data_element_count"] == 1, (
            f"only the new record is still held, got {after['live_child_data_element_count']}"
        )
        assert after["lifetime_collected_element_count"] == 3, (
            "three records have ever been created, got "
            f"{after['lifetime_collected_element_count']}"
        )
        assert after["active_consent_count"] == 1
