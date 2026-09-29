"""Every rejection the PRD names, raised by the request that earns it.

The ladder decides which code answers when several rules would object, so each
test drives a request that fails two rules at once and pins the code the
higher-priority rule owns, then checks the refused write left nothing behind.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_DELIVERY_NOT_PENDING,
    ERR_DEVICE_BINDING_MISMATCH,
    ERR_DEVICE_NOT_BOUND,
    ERR_DEVICE_NOT_FOUND,
    ERR_DUPLICATE_READER_APP,
    ERR_FORBIDDEN_ROLE,
    ERR_INTEROP_PROFILE_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PHYSICAL_CREDENTIAL_INELIGIBLE,
    ERR_PRESENTATION_SESSION_NOT_FOUND,
    ERR_PROOFING_SESSION_NOT_FOUND,
    ERR_READER_APP_NOT_FOUND,
    ERR_READER_NOT_TRUSTED,
    ERR_SESSION_NOT_CONSENT_PENDING,
    ERR_UNAUTHENTICATED,
    ERR_UPDATE_DELIVERY_NOT_FOUND,
    ERR_UPDATE_ORDER_NOT_FOUND,
    ERR_VERIFIER_ACCOUNT_DELINQUENT,
)
from test_helpers.assertions import assert_cents, assert_field_values, rows_of
from test_helpers.factories import (
    credential_payload,
    presentation_session_payload,
    proofing_session_payload,
    reader_app_payload,
)
from test_helpers.fixtures import (
    create_active_credential,
    create_approved_verifier,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    create_verified_session,
    device_version,
    first_delivery_of,
    grant_consent,
    open_address_change,
    open_presentation_session,
    publish_trust_list,
    register_device,
    register_reader_app,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    PROOFING_AGENT,
    make_holder_headers,
    make_verifier_operator_headers,
)

_ROLE_WITHOUT_IDENTITY = {
    "X-User-Role": "SystemAdmin",
    "Content-Type": "application/json",
}

_RETAIL_VERIFIER = {
    "organization_name": "Prairie Cellars",
    "category": "AGE_RESTRICTED_RETAIL",
    "purpose_scope": ["family_name", "age_over_21"],
    "retention_ceiling_days": 30,
}


def _retail_world(api, base_rate_cents=30):
    return create_presentation_ready_world(
        api,
        verifier_overrides=dict(_RETAIL_VERIFIER),
        reader_app_overrides={
            "app_identifier": "till-a",
            "certificate_serial": "SER-A1",
            "requested_elements": ["family_name", "age_over_21"],
            "base_rate_cents": base_rate_cents,
        },
    )


class TestAuthenticationAndRole:
    """The top two rungs of the ladder answer before anything is looked up."""

    def test_a_request_without_the_identity_header_is_unauthenticated(self, api):
        """The holder exists and the role is a legitimate one, but the actor is
        unidentified, so the answer is 401 rather than the 200 the row would
        otherwise produce.

        PRD 2.1: "Every request to the service must carry two headers:
        `X-User-ID`, identifying the actor, and `X-User-Role`, naming the capacity
        in which the actor is operating. If either header is absent or empty, or
        if `X-User-Role` is not one of the six role names declared below, the
        request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other
        consideration."

        Design: Corner/errors/request_missing_x_user_id_header_returns_unauthenticated
        """
        create_profile(api)
        holder = create_holder(api)

        validate_error(
            api.get_holder(holder["id"], _ROLE_WITHOUT_IDENTITY),
            ERR_UNAUTHENTICATED,
            401,
        )

    def test_a_proofing_agent_cannot_create_the_governing_profile(self, api):
        """The body is perfectly valid, so only the role check can be what rejects
        it, and no profile is stored.

        PRD 2.1: "If both headers are well formed but the named role is not among
        the roles authorized for the endpoint being called (see the Authorized
        Role(s) column in 4), the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD 2.6: "2. The acting role is authorized for the endpoint -
        `ERR_FORBIDDEN_ROLE`. 3. Request-body schema conformance"

        Design: Corner/errors/proofing_agent_creating_an_interop_profile_returns_forbidden
        """
        refused = api.create_interop_profile(
            {
                "profile_code": "AAMVA-MDL-2026",
                "standard_version": "ISO_18013_5_2021",
            },
            PROOFING_AGENT,
        )
        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)


class TestOwnershipBeatsState:
    """Rung 6 answers before rung 7 can object to the handset's state."""

    def test_one_holder_cannot_report_another_holders_handset_lost(self, api):
        """The handset is only REGISTERED, so a state rule would also have
        objected; the ownership rule is higher and the row is left untouched.

        PRD 2.6: "6. Ownership for the entity-backed roles -
        `ERR_NOT_RESOURCE_OWNER`. This applies to credential activation, loss
        reporting, handset recovery, reader-app registration, presentation-session
        creation, presentation consent, disclosure, and retention attestation."
        PRD 2.1: "A `Holder` may act only within its own `holder_id` chain - its
        own handsets, its own credentials, its own propagation orders, and the
        presentation sessions raised against its own credentials."

        Design: Corner/errors/holder_cannot_report_another_holders_handset_lost
        """
        create_profile(api)
        holder_a = create_holder(api, legal_name="Rosa Ibarra")
        holder_b = create_holder(api, legal_name="Dmitri Vance")
        device_b = register_device(
            api, holder_b["id"], platform="IOS", model_name="iPhone 17"
        )

        validate_error(
            api.report_device_lost(device_b["id"], make_holder_headers(holder_a["id"])),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

        stored = validate_success(api.get_device(device_b["id"], ADMIN))
        assert_field_values(
            stored,
            {"state": "REGISTERED", "version": 1, "lost_reported_at": None},
        )


class TestPathScopedNotFound:
    """Each resource answers with the not-found code named for itself."""

    def test_every_remaining_path_scoped_not_found_code_is_reachable(self, api):
        """Eight endpoints, eight unknown identifiers, eight distinct codes - a
        single generic not-found answer fails here.

        PRD 2.5: "The per-entity not-found codes are
        `ERR_INTEROP_PROFILE_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`,
        `ERR_PROOFING_SESSION_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
        `ERR_CREDENTIAL_NOT_FOUND`, `ERR_UPDATE_ORDER_NOT_FOUND`,
        `ERR_UPDATE_DELIVERY_NOT_FOUND`, `ERR_VERIFIER_NOT_FOUND`,
        `ERR_READER_APP_NOT_FOUND` and `ERR_PRESENTATION_SESSION_NOT_FOUND`, each
        returning HTTP 404."
        PRD 2.6: "4. Every path-templated resource resolves, left to right - the
        per-entity 404 codes."

        Design: Corner/errors/every_remaining_path_scoped_not_found_error_is_triggerable
        """
        validate_error(
            api.get_interop_profile(NON_EXISTENT_UUID, ADMIN),
            ERR_INTEROP_PROFILE_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_proofing_session(NON_EXISTENT_UUID, PROOFING_AGENT),
            ERR_PROOFING_SESSION_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_device(NON_EXISTENT_UUID, ADMIN), ERR_DEVICE_NOT_FOUND, 404
        )
        validate_error(
            api.get_credential(NON_EXISTENT_UUID, ADMIN),
            ERR_CREDENTIAL_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_update_order(NON_EXISTENT_UUID, ADMIN),
            ERR_UPDATE_ORDER_NOT_FOUND,
            404,
        )
        validate_error(
            api.deliver_update(
                NON_EXISTENT_UUID, {"device_receipt_token": "receipt-tok-x"}, ADMIN
            ),
            ERR_UPDATE_DELIVERY_NOT_FOUND,
            404,
        )
        validate_error(
            api.decide_reader_listing(
                NON_EXISTENT_UUID, {"decision": "LIST"}, ADMIN
            ),
            ERR_READER_APP_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_presentation_session(NON_EXISTENT_UUID, ADMIN),
            ERR_PRESENTATION_SESSION_NOT_FOUND,
            404,
        )


class TestReaderApplicationUniqueness:
    """The uniqueness key is the pair, not the identifier the humans read."""

    def test_reusing_a_certificate_serial_under_a_new_identifier_is_a_duplicate(
        self, api
    ):
        """Because `app_identifier` differs, the renewal-buffer rule has nothing to
        say; the serial collision is what rejects the registration.

        PRD 3.7: "Separately, the pair of owning verifier and `certificate_serial`
        must not already be registered; a repeat is `ERR_DUPLICATE_READER_APP`
        (HTTP 409)."
        PRD 2.6: "22. Reader-certificate renewal buffer - `ERR_CERT_WINDOW_CONFLICT`.
        23. Reader-certificate serial uniqueness - `ERR_DUPLICATE_READER_APP`."

        Design: Corner/errors/duplicate_certificate_serial_for_the_same_verifier_rejected
        """
        verifier = create_approved_verifier(
            api,
            organization_name="Prairie Cellars",
            category="AGE_RESTRICTED_RETAIL",
            purpose_scope=["family_name", "age_over_21"],
            retention_ceiling_days=30,
        )
        operator = make_verifier_operator_headers(verifier["id"])
        register_reader_app(
            api,
            verifier["id"],
            app_identifier="till-a",
            certificate_serial="SER-A1",
            base_rate_cents=30,
        )

        refused = api.create_reader_app(
            reader_app_payload(
                verifier["id"],
                app_identifier="till-b",
                certificate_serial="SER-A1",
                base_rate_cents=30,
            ),
            operator,
        )
        validate_error(refused, ERR_DUPLICATE_READER_APP, 409)

        _, meta = validate_paginated(
            api.list_verifier_reader_apps(verifier["id"], ADMIN)
        )
        assert meta["total_count"] == 1


class TestPhysicalCredentialEligibility:
    """The plastic is the root of trust at the very first step of proofing."""

    def test_proofing_cannot_open_for_a_suspended_plastic_credential(self, api):
        """Enrolment succeeded with a suspended plastic, but the first proofing
        gate refuses and no session row is created.

        PRD 3.2: "The physical-credential gate requires both that
        `physical_credential_status` reads `VALID` and that
        `physical_credential_expires_on` falls strictly later than the current
        logical date, and it is evaluated when a proofing session is opened, when a
        proofing session is submitted for adjudication, when a credential is
        provisioned, and when a credential is activated. In all four the rejection
        is `ERR_PHYSICAL_CREDENTIAL_INELIGIBLE` (HTTP 422)."

        Design: Corner/errors/proofing_session_for_a_suspended_physical_credential_rejected
        """
        create_profile(api)
        holder = create_holder(api, physical_credential_status="SUSPENDED")

        refused = api.create_proofing_session(
            proofing_session_payload(holder["id"], requested_assurance_level="IAL2"),
            PROOFING_AGENT,
        )
        validate_error(refused, ERR_PHYSICAL_CREDENTIAL_INELIGIBLE, 422)

        _, meta = validate_paginated(
            api.list_holder_proofing_sessions(holder["id"], PROOFING_AGENT)
        )
        assert meta["total_count"] == 0


class TestHandsetBindingIntegrity:
    """Two codes share rung 17: one for provisioning, one for delivery."""

    def test_provisioning_onto_a_never_attested_handset_is_a_binding_mismatch(
        self, api
    ):
        """The proofing session is VERIFIED and the echoed handset version is
        correct, so the only remaining objection is the handset's state.

        PRD 3.4: "The named handset must be in `ATTESTED` or `BOUND` and its
        `holder_id` must match the credential's subject; otherwise
        `ERR_DEVICE_BINDING_MISMATCH` (HTTP 409)."

        Design: Corner/errors/provisioning_onto_a_never_attested_handset_returns_binding_mismatch
        """
        create_profile(api)
        holder = create_holder(api)
        device = register_device(api, holder["id"], model_name="Pixel 9")
        session = create_verified_session(api, holder["id"])

        refused = api.create_credential(
            credential_payload(
                holder["id"],
                device["id"],
                session["id"],
                device_version(api, device["id"]),
            ),
            ADJUDICATOR,
        )
        validate_error(refused, ERR_DEVICE_BINDING_MISMATCH, 409)

        _, meta = validate_paginated(
            api.list_credentials(ADJUDICATOR, {"holder_id": holder["id"]})
        )
        assert meta["total_count"] == 0

    def test_pushing_to_a_lost_handset_names_the_binding_not_the_staleness(self, api):
        """The loss cascade both un-bound the handset and suspended the credential,
        so two rules object; the binding rule sits higher and the delivery is left
        pending for a later retry.

        PRD 3.5: "requires the handset behind the credential to be in `BOUND`,
        otherwise `ERR_DEVICE_NOT_BOUND` (HTTP 409)"
        PRD 2.6: "17. Device binding integrity - `ERR_DEVICE_BINDING_MISMATCH` or
        `ERR_DEVICE_NOT_BOUND`. ... 29. Revocation-status freshness on the delivery
        path - `ERR_REVOCATION_STATUS_STALE`."

        Design: Corner/errors/delivering_to_a_lost_handset_returns_device_not_bound
        """
        bundle = create_active_credential(api)
        order = open_address_change(
            api, bundle["holder"]["id"], address_line1="44 Sorghum Lane"
        )
        delivery = first_delivery_of(api, order["id"])
        validate_success(
            api.report_device_lost(
                bundle["device"]["id"], make_holder_headers(bundle["holder"]["id"])
            )
        )

        validate_error(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-tok-1"}, ADMIN
            ),
            ERR_DEVICE_NOT_BOUND,
            409,
        )

        rows = rows_of(api.list_order_deliveries(order["id"], ADMIN))
        assert_field_values(rows[0], {"status": "PENDING", "attempt_count": 0})


class TestOneShotWrites:
    """Replaying a completed transition must perform no second write."""

    def test_confirming_the_same_delivery_twice_is_refused(self, api):
        """The first confirmation synced the payload; the replay is refused and the
        document revision does not advance a second time.

        PRD 3.5: "It requires the delivery to still be in `PENDING` - otherwise
        `ERR_DELIVERY_NOT_PENDING` (HTTP 409) ... The credential's
        `pending_update_count` decrements by 1, and when that leaves no outstanding
        delivery - that is, when the count had been exactly 1 - the credential's
        sync axis moves `UPDATE_PENDING -> IN_SYNC`, its `doc_version` increments by
        1"

        Design: Corner/errors/second_deliver_on_the_same_delivery_returns_delivery_not_pending
        """
        bundle = create_active_credential(api)
        order = open_address_change(
            api, bundle["holder"]["id"], address_line1="44 Sorghum Lane"
        )
        delivery = first_delivery_of(api, order["id"])
        validate_success(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-tok-1"}, ADMIN
            )
        )

        validate_error(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-tok-2"}, ADMIN
            ),
            ERR_DELIVERY_NOT_PENDING,
            409,
        )

        rows = rows_of(api.list_order_deliveries(order["id"], ADMIN))
        assert_field_values(
            rows[0],
            {
                "status": "DELIVERED",
                "attempt_count": 1,
                "device_receipt_token": "receipt-tok-1",
            },
        )

        credential = validate_success(
            api.get_credential(bundle["credential"]["id"], ADMIN)
        )
        assert_field_values(
            credential, {"pending_update_count": 0, "doc_version": 2}
        )

    def test_consenting_twice_on_the_same_session_is_refused(self, api):
        """Consent is the resident's one decision: the replay is refused and the
        session's version proves the second call wrote nothing.

        PRD 3.8: "The session must be in `CONSENT_PENDING`, or the request fails
        with `ERR_SESSION_NOT_CONSENT_PENDING` (HTTP 409), and the acting
        `X-User-ID` must equal the presented credential's `holder_id`, or
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/errors/second_consent_on_a_granted_session_returns_session_not_consent_pending
        """
        world = _retail_world(api)
        session = open_presentation_session(
            api,
            world,
            purpose="age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )
        grant_consent(api, session["id"], world["holder"]["id"])

        validate_error(
            api.consent_presentation(
                session["id"],
                {"consent_decision": "APPROVE", "unlock_method": "BIOMETRIC"},
                make_holder_headers(world["holder"]["id"]),
            ),
            ERR_SESSION_NOT_CONSENT_PENDING,
            409,
        )

        stored = validate_success(
            api.get_presentation_session(session["id"], ADMIN)
        )
        assert_field_values(stored, {"state": "CONSENT_GRANTED", "version": 2})


class TestReaderTrustAndAccountStanding:
    """Verifier-level standing is not reader-level trust, and money is separate."""

    def test_a_reader_application_never_listed_cannot_open_a_presentation(self, api):
        """The verifier is APPROVED and the snapshot covers the current instant, so
        the only failing gate is the application's own trust state - and nothing is
        recorded against the verifier.

        PRD 3.8: "Third, the reader application's `trust_state` must be `LISTED`
        **and** the newest trust-list snapshot of the active profile must actually
        cover the current logical instant, meaning the instant falls at or after
        `effective_from` and strictly before `effective_until`; either failure is
        `ERR_READER_NOT_TRUSTED` (HTTP 403)."

        Design: Corner/errors/presentation_from_a_never_listed_reader_app_returns_reader_not_trusted
        """
        bundle = create_active_credential(api)
        verifier = create_approved_verifier(api, **dict(_RETAIL_VERIFIER))
        reader_app = register_reader_app(
            api,
            verifier["id"],
            app_identifier="till-a",
            certificate_serial="SER-A1",
            requested_elements=["family_name", "age_over_21"],
            base_rate_cents=30,
        )
        publish_trust_list(api, bundle["profile"]["id"])

        refused = api.create_presentation_session(
            presentation_session_payload(
                bundle["credential"]["id"],
                reader_app["id"],
                requested_elements=["family_name", "age_over_21"],
                purpose="age check at till",
                handset_handling="NO_SURRENDER",
                retention_days=7,
            ),
            make_verifier_operator_headers(verifier["id"]),
        )
        validate_error(refused, ERR_READER_NOT_TRUSTED, 403)

        _, meta = validate_paginated(api.list_presentation_sessions(PRIVACY_AUDITOR))
        assert meta["total_count"] == 0

        stored = validate_success(api.get_verifier(verifier["id"], ADMIN))
        assert stored["open_session_count"] == 0

    def test_the_disclosure_after_the_balance_passes_the_cap_is_refused(self, api):
        """The cap is measured before the new charge, so a single 50001-cent query
        goes through and the next one is refused with the balance untouched.

        PRD 3.9: "the verifier's `billable_query_balance_cents` must be no greater
        than 50000 cents - that is, 500 dollars of unsettled query charges - or the
        disclosure is refused with `ERR_VERIFIER_ACCOUNT_DELINQUENT` (HTTP 402)."

        Design: Corner/errors/second_disclosure_over_the_balance_cap_returns_account_delinquent
        """
        world = _retail_world(api, base_rate_cents=50001)
        operator = make_verifier_operator_headers(world["verifier"]["id"])

        first = open_presentation_session(
            api,
            world,
            purpose="age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )
        grant_consent(api, first["id"], world["holder"]["id"])
        validate_success(api.disclose_presentation(first["id"], operator))

        second = open_presentation_session(
            api,
            world,
            purpose="second age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )
        grant_consent(api, second["id"], world["holder"]["id"])

        validate_error(
            api.disclose_presentation(second["id"], operator),
            ERR_VERIFIER_ACCOUNT_DELINQUENT,
            402,
        )

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert_cents(verifier, "billable_query_balance_cents", 50001)

        apps = rows_of(api.list_verifier_reader_apps(world["verifier"]["id"], ADMIN))
        assert apps[0]["query_count"] == 1

        stored = validate_success(api.get_presentation_session(second["id"], ADMIN))
        assert_field_values(
            stored, {"state": "CONSENT_GRANTED", "billing_state": "UNBILLED"}
        )
