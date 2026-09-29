"""The service version token guards notice drafting and consent creation alike."""

from test_helpers import (
    OFFICER_HEADERS,
    add_design_factor,
    api_client,
    consent_request_payload,
    create_service,
    parental_notice_payload,
    publish_notice,
    read_service,
    run_determination,
    service_version,
    validate_error,
    validate_paginated,
    validate_success,
)

_COMPLETE_CONTENT_KEYS = [
    "OPERATOR_IDENTITY_CONTACT",
    "ELEMENTS_COLLECTED",
    "USE_PURPOSES",
    "THIRD_PARTY_DISCLOSURE",
    "PARENTAL_RIGHTS",
    "NO_CONDITIONING_OF_PARTICIPATION",
    "RETENTION_AND_DISPOSAL",
]


def _service_at_version_three() -> str:
    """Register, evidence and determine one service, so its version reaches 3."""
    service = create_service(name="OCC Token Kids")
    assert service["version"] == 1, (
        f"version begins at 1 when the resource is created, got {service['version']}"
    )
    add_design_factor(service["id"], "SUBJECT_MATTER", "MODERATE")
    determined = run_determination(service["id"])
    assert determined["determination_status"] == "MIXED_AUDIENCE"
    reached = service_version(service["id"])
    assert reached == 3, (
        "creation, the evidence row and the determination run are three accepted writes, got "
        f"{reached}"
    )
    return service["id"]


class TestNoticeDraftingConsumesItsToken:
    """A client's own successful draft invalidates the token it was holding."""

    def test_01_reusing_the_token_after_a_successful_draft_is_refused_with_412(self):
        """The same body fails, then succeeds unchanged once the token is refreshed.

        "`POST /parental-notices` requires `expected_service_version` as a non-optional body
        field carrying the client's last observed `OnlineService.version`. If it does not equal
        the target service's current `version`, the request is rejected with
        `ERR_STALE_SERVICE_VERSION` (HTTP 412)." "an accepted request increments
        `OnlineService.version` by **exactly one**". "Drafting is one of the two operations
        guarded by `expected_service_version` as described in §2.6, and it advances the
        service's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/notice_create_against_a_stale_service_version_is_refused_with_412
        """
        service_id = _service_at_version_three()
        stale_token = service_version(service_id)
        assert stale_token == 3

        accepted = validate_success(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service_id,
                    stale_token,
                    _COMPLETE_CONTENT_KEYS,
                    notice_label="Notice r1",
                    delivery_channel="EMAIL",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == "DRAFT", (
            f"the first draft consumed token 3, got {accepted['status']}"
        )

        validate_error(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service_id,
                    stale_token,
                    _COMPLETE_CONTENT_KEYS,
                    notice_label="Notice r2 stale",
                    delivery_channel="EMAIL",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_STALE_SERVICE_VERSION",
            412,
        )

        refreshed_token = service_version(service_id)
        assert refreshed_token == 4, (
            "exactly one increment from the accepted draft and none from the refused one, got "
            f"{refreshed_token}"
        )

        retried = validate_success(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service_id,
                    refreshed_token,
                    _COMPLETE_CONTENT_KEYS,
                    notice_label="Notice r2 stale",
                    delivery_channel="EMAIL",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert retried["status"] == "DRAFT", (
            "the identical body succeeds once the token is refreshed, got "
            f"{retried['status']}"
        )

        _, meta = validate_paginated(
            api_client.list_service_parental_notices(
                service_id, OFFICER_HEADERS, {"limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, (
            f"the refused attempt left no notice row behind, got {meta['total_count']}"
        )


class TestConsentCreationConsumesItsToken:
    """The token guards the service aggregate, not the parent and child pair."""

    def test_02_a_token_that_predates_a_preceding_consent_create_is_refused_with_412(self):
        """A different parent and a different child do not excuse a stale token.

        "`POST /consent-requests` likewise requires `expected_service_version` as a
        non-optional body field carrying the client's last observed `OnlineService.version`,
        and a mismatch with the service's current `version` is rejected with
        `ERR_STALE_SERVICE_VERSION` (HTTP 412)." Creation "advances the service's `version` by
        one", and the grant recomputes "`active_consent_count` — the number of that service's
        consent requests whose `status` is `GRANTED`".

        Design: Corner/cross_cutting_complexity_layers/consent_create_against_a_stale_service_version_is_refused_with_412
        """
        service_id = _service_at_version_three()
        notice = validate_success(
            api_client.create_parental_notice(
                parental_notice_payload(
                    service_id,
                    service_version(service_id),
                    _COMPLETE_CONTENT_KEYS,
                    notice_label="Consent OCC notice",
                    delivery_channel="EMAIL",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        published = publish_notice(notice["id"])
        assert published["status"] == "PUBLISHED"

        stale_token = service_version(service_id)
        assert stale_token == 5, (
            "the notice draft and its publication each add one to version 3, got "
            f"{stale_token}"
        )

        accepted = validate_success(
            api_client.create_consent_request(
                consent_request_payload(
                    service_id,
                    notice["id"],
                    "guardian.kk@x.test",
                    "child-623",
                    stale_token,
                    intended_uses=["PARTICIPATION_CORE"],
                    consent_method="KNOWLEDGE_BASED_AUTH",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == "INITIATED"
        assert accepted["required_tier_at_creation"] == 1, (
            "core-only participation with no approved persistent-identifier integration "
            f"requires tier 1, got {accepted['required_tier_at_creation']}"
        )

        validate_error(
            api_client.create_consent_request(
                consent_request_payload(
                    service_id,
                    notice["id"],
                    "guardian.ll@x.test",
                    "child-624",
                    stale_token,
                    intended_uses=["PARTICIPATION_CORE"],
                    consent_method="KNOWLEDGE_BASED_AUTH",
                ),
                OFFICER_HEADERS,
            ),
            "ERR_STALE_SERVICE_VERSION",
            412,
        )

        after = read_service(service_id)
        assert after["version"] == 6, (
            "one increment for the accepted creation and none for the refused one, got "
            f"{after['version']}"
        )
        assert after["active_consent_count"] == 0, (
            "an INITIATED request is not yet an active consent, got "
            f"{after['active_consent_count']}"
        )

        retried = validate_success(
            api_client.create_consent_request(
                consent_request_payload(
                    service_id,
                    notice["id"],
                    "guardian.ll@x.test",
                    "child-624",
                    after["version"],
                    intended_uses=["PARTICIPATION_CORE"],
                    consent_method="KNOWLEDGE_BASED_AUTH",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert retried["status"] == "INITIATED", (
            f"the refreshed token admits the same pair, got {retried['status']}"
        )

        _, meta = validate_paginated(
            api_client.list_consent_requests(
                OFFICER_HEADERS, {"service_id": service_id, "limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, (
            f"the refused creation left no consent row behind, got {meta['total_count']}"
        )
