"""Records as the PRD declares them: echoes, defaults, computed fields, shape.

These tests hold the API to what the resource *is* - which inputs survive a
round trip, which values the server mints itself, and which fields must not
exist at all on an append-only row.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_HOLDER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_VERIFIER_NOT_FOUND,
)
from test_helpers.assertions import assert_field_values, rows_of
from test_helpers.factories import (
    device_payload,
    holder_payload,
    reader_app_payload,
)
from test_helpers.fixtures import (
    append_evidence,
    create_approved_verifier,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    open_presentation_session,
    open_proofing_session,
    register_reader_app,
)
from test_helpers.test_users import (
    ADMIN,
    PRIVACY_AUDITOR,
    PROOFING_AGENT,
    make_verifier_operator_headers,
)


class TestInteropProfileRecord:
    """The governing profile round-trips its inputs and mints its own fields."""

    def test_every_supplied_optional_is_echoed_back_unchanged(self, api):
        """A profile created with all nine optionals supplied returns each of
        them verbatim rather than a jurisdiction default.

        PRD 3.1: "Everything else may be omitted and takes a jurisdiction
        default. `accepted_issuer_states` carries the two-letter codes of the
        issuing jurisdictions whose mDLs this state will accept for cross-state
        presentation and defaults to an empty array."

        Design: Corner/entities/interop_profile_creation_echoes_every_declared_input_field
        """
        supplied = {
            "profile_code": "AAMVA-MDL-FULL",
            "standard_version": "ISO_18013_7_2024",
            "accepted_issuer_states": ["IA", "KS"],
            "required_assurance_level": "IAL1_5",
            "max_devices_per_holder": 3,
            "max_active_credentials_per_holder": 4,
            "proofing_validity_days": 90,
            "revocation_freshness_seconds": 45,
            "age_only_allowed_elements": ["age_over_21"],
        }

        created = validate_success(
            api.create_interop_profile(dict(supplied), ADMIN), 201
        )
        assert_field_values(created, supplied)

    def test_omitted_optionals_take_the_declared_jurisdiction_defaults(self, api):
        """Supplying only the two required inputs yields the documented default
        for every optional, including the three-element age-only allow-list.

        PRD 3.1: "`required_assurance_level` names the minimum identity assurance
        a proofing session must reach before a credential may be provisioned and
        defaults to `IAL2` ... `max_devices_per_holder` is the multi-device policy
        cap and defaults to 2, and `max_active_credentials_per_holder` caps
        simultaneous live credentials per resident and also defaults to 2 ...
        `proofing_validity_days` - the shelf life of a verified proofing result -
        defaults to 180 days ... `revocation_freshness_seconds` defaults to 300
        seconds ... `age_only_allowed_elements` is the exact element allow-list
        for an age-only presentation and defaults to the three elements
        `age_over_18`, `age_over_21` and `portrait`."

        Design: Corner/entities/interop_profile_omitted_optionals_take_declared_defaults
        """
        created = validate_success(
            api.create_interop_profile(
                {
                    "profile_code": "AAMVA-MDL-MIN",
                    "standard_version": "ISO_18013_5_2021",
                },
                ADMIN,
            ),
            201,
        )
        assert_field_values(
            created,
            {
                "accepted_issuer_states": [],
                "required_assurance_level": "IAL2",
                "max_devices_per_holder": 2,
                "max_active_credentials_per_holder": 2,
                "proofing_validity_days": 180,
                "revocation_freshness_seconds": 300,
                "age_only_allowed_elements": [
                    "age_over_18",
                    "age_over_21",
                    "portrait",
                ],
            },
        )

    def test_the_server_mints_the_identity_and_the_governance_fields(self, api):
        """Nothing in the request names the id, the timestamps, the version, the
        active flag or the republish counter, and all five come back set.

        PRD 3.1: "A newly created profile is marked `is_active` as true - it is
        the profile currently governing issuance - starts with
        `pending_republish_count` at zero, and starts at `version` 1."

        Design: Corner/entities/interop_profile_system_fields_are_server_generated
        """
        created = validate_success(
            api.create_interop_profile(
                {
                    "profile_code": "AAMVA-MDL-SYS",
                    "standard_version": "ISO_18013_5_2024",
                },
                ADMIN,
            ),
            201,
        )
        assert is_valid_uuid(created["id"]), created["id"]
        assert is_iso8601_timestamp(created["created_at"]), created["created_at"]
        assert is_iso8601_timestamp(created["updated_at"]), created["updated_at"]
        assert_field_values(
            created,
            {"version": 1, "is_active": True, "pending_republish_count": 0},
        )


class TestHolderRecord:
    """Enrolment stores the plastic facts and starts every counter at its base."""

    def test_a_fresh_holder_reads_back_with_its_counters_at_the_base(self, api):
        """The stored record carries the optional defaults and starts
        address_version at 1, not 0.

        PRD 3.2: "Two further inputs are optional: `physical_credential_status`,
        which defaults to `VALID` ... and `restriction_codes`, the driving
        restrictions carried on the credential such as corrective lenses or
        daylight-only operation, defaulting to an empty array. A new holder
        starts with `active_credential_count`, `bound_device_count` and
        `revoked_credential_count` all at zero and `address_version` at 1."

        Design: Corner/entities/holder_retrieval_returns_stored_record_with_zeroed_counters
        """
        holder = create_holder(api, legal_name="Rosa Ibarra")

        stored = validate_success(api.get_holder(holder["id"], ADMIN))
        assert_field_values(
            stored,
            {
                "legal_name": "Rosa Ibarra",
                "physical_credential_number": holder["physical_credential_number"],
                "physical_credential_status": "VALID",
                "restriction_codes": [],
                "active_credential_count": 0,
                "bound_device_count": 0,
                "revoked_credential_count": 0,
                "address_version": 1,
            },
        )

    def test_an_unknown_holder_id_is_a_named_not_found(self, api):
        """A read for an id that matches no holder is a 404 carrying the holder's
        own not-found code.

        PRD 2.5: "The per-entity not-found codes are
        `ERR_INTEROP_PROFILE_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`,
        `ERR_PROOFING_SESSION_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
        `ERR_CREDENTIAL_NOT_FOUND`, `ERR_UPDATE_ORDER_NOT_FOUND`,
        `ERR_UPDATE_DELIVERY_NOT_FOUND`, `ERR_VERIFIER_NOT_FOUND`,
        `ERR_READER_APP_NOT_FOUND` and `ERR_PRESENTATION_SESSION_NOT_FOUND`, each
        returning HTTP 404."

        Design: Corner/entities/holder_get_with_unknown_id_returns_holder_not_found
        """
        validate_error(
            api.get_holder(NON_EXISTENT_UUID, ADMIN), ERR_HOLDER_NOT_FOUND, 404
        )

    def test_enrolment_without_the_eligibility_number_is_refused(self, api):
        """The plastic credential number has no default, so omitting it is a
        schema failure rather than a stored null.

        PRD 2.6: "3. Request-body schema conformance: every required field
        present, every enum value a member of its declared set, every integer
        inside its declared range, every array an array of strings, every datetime
        parseable as ISO 8601, and every interval's start strictly before its end
        - `ERR_INVALID_REQUEST`."

        Design: Corner/entities/holder_create_missing_required_physical_credential_number_rejected
        """
        payload = holder_payload()
        payload.pop("physical_credential_number")

        validate_error(api.create_holder(payload, ADMIN), ERR_INVALID_REQUEST, 400)


class TestProofingEvidenceRecord:
    """Evidence is scored at capture and never carries a mutable shape."""

    @staticmethod
    def _collecting_session(api):
        create_profile(api)
        holder = create_holder(api)
        return open_proofing_session(api, holder["id"])

    def test_strength_points_are_resolved_from_the_fixed_table(self, api):
        """A FAIR document scan is stored at 150 points and is not superseded
        while it is the only item of its type.

        PRD 3.2: "On creation the item's `strength_points` are resolved from its
        type and quality band and its `superseded` label is written as false ...
        The strength table is fixed: a document scan is worth 250 points when
        strong, 150 when fair and 60 when weak"

        Design: Corner/entities/proofing_evidence_strength_points_computed_from_type_and_quality
        """
        session = self._collecting_session(api)

        item = validate_success(
            api.add_proofing_evidence(
                session["id"],
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "FAIR",
                    "captured_at": "2026-07-20T09:00:00Z",
                    "source_reference": "doc-1",
                },
                PROOFING_AGENT,
            ),
            201,
        )
        assert_field_values(
            item,
            {
                "strength_points": 150,
                "superseded": False,
                "evidence_type": "DOCUMENT_SCAN",
                "quality": "FAIR",
            },
        )

    def test_an_evidence_row_carries_no_version_and_no_updated_at(self, api):
        """Append-only rows expose an id and a creation stamp and nothing that
        would imply they can be rewritten.

        PRD 3.2: "Evidence is captured one item at a time and is **append-only**
        - an evidence row is never mutated after creation."

        Design: Corner/entities/proofing_evidence_is_immutable_with_no_version_field
        """
        session = self._collecting_session(api)
        append_evidence(
            api,
            session["id"],
            [
                {
                    "evidence_type": "BIOMETRIC_MATCH",
                    "quality": "STRONG",
                    "captured_at": "2026-07-20T09:05:00Z",
                    "source_reference": "bio-1",
                }
            ],
        )

        items = rows_of(api.list_proofing_evidence(session["id"], PROOFING_AGENT))
        assert len(items) == 1
        row = items[0]
        assert is_valid_uuid(row["id"]), row["id"]
        assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
        assert "version" not in row
        assert "updated_at" not in row
        assert row["strength_points"] == 200


class TestDeviceRecord:
    """Registration is schema-checked before anything is stored."""

    def test_a_platform_outside_the_declared_set_stores_nothing(self, api):
        """An unknown platform value is rejected and leaves the holder with no
        handset at all.

        PRD 3.3: "Registration names the `holder_id` that owns the handset, the
        `platform` - `IOS` or `ANDROID` - a human-readable `model_name`, the
        opaque platform `hardware_attestation_token` the operating system
        produced, and the `protection_method` the resident will use to unlock the
        credential: `BIOMETRIC` or `PASSCODE`."

        Design: Corner/entities/device_create_with_invalid_enum_platform_rejected
        """
        holder = create_holder(api)

        refused = api.create_device(
            device_payload(
                holder["id"], platform="WINDOWS_PHONE", model_name="Lumia"
            ),
            ADMIN,
        )
        validate_error(refused, ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_holder_devices(holder["id"], ADMIN))
        assert meta["total_count"] == 0


class TestReaderApplicationRecord:
    """Listing pages honour the window while the count reports the whole set."""

    def test_a_page_window_narrows_the_rows_but_not_the_total(self, api):
        """With two applications registered, the last page of size one returns one
        row, a total of two and no more beyond it.

        PRD 2.4: "The `meta` object of a list response carries `limit` and
        `offset` echoing the effective values used, `total_count` giving the
        number of rows matching the filters before the page window was applied,
        and `has_more` indicating whether any matching row remains beyond the
        current window."

        Design: Corner/entities/reader_app_listing_honours_limit_and_offset_with_total_count
        """
        verifier = create_approved_verifier(api)
        for identifier, serial in (("till-a", "SER-A1"), ("till-b", "SER-B1")):
            register_reader_app(
                api,
                verifier["id"],
                app_identifier=identifier,
                certificate_serial=serial,
                base_rate_cents=30,
            )

        page, meta = validate_paginated(
            api.list_verifier_reader_apps(
                verifier["id"], ADMIN, {"limit": 1, "offset": 1}
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(page) == 1
        assert_field_values(page[0], {"trust_state": "PENDING", "query_count": 0})

    def test_registering_under_an_unknown_verifier_is_a_verifier_not_found(self, api):
        """The body foreign key resolves before the ownership and trust checks, so
        the answer names the missing verifier.

        PRD 2.6: "5. Every body-supplied foreign key resolves, in the endpoint's
        declared field order - the per-entity 404 codes."

        Design: Corner/entities/reader_app_with_unknown_verifier_id_returns_not_found
        """
        refused = api.create_reader_app(
            reader_app_payload(
                NON_EXISTENT_UUID,
                requested_elements=["family_name"],
                app_identifier="till-a",
                certificate_serial="SER-A1",
            ),
            make_verifier_operator_headers(NON_EXISTENT_UUID),
        )
        validate_error(refused, ERR_VERIFIER_NOT_FOUND, 404)


class TestPresentationSessionRecord:
    """The junction row is reachable from both arms of the graph."""

    def test_both_foreign_keys_find_the_same_session(self, api):
        """Filtering the presentation list by the credential and by the reader
        application each return that one session.

        PRD 3.8: "Presentation sessions can be listed and filtered by
        `credential_id`, `reader_app_id`, `state` or `context`."

        Design: Corner/entities/presentation_session_joins_credential_and_reader_app_graph
        """
        world = create_presentation_ready_world(
            api,
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "base_rate_cents": 30,
            },
        )
        session = open_presentation_session(
            api,
            world,
            purpose="age check at till",
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )

        by_credential, credential_meta = validate_paginated(
            api.list_presentation_sessions(
                PRIVACY_AUDITOR, {"credential_id": world["credential"]["id"]}
            )
        )
        assert credential_meta["total_count"] == 1
        assert by_credential[0]["id"] == session["id"]

        by_reader, reader_meta = validate_paginated(
            api.list_presentation_sessions(
                PRIVACY_AUDITOR, {"reader_app_id": world["reader_app"]["id"]}
            )
        )
        assert reader_meta["total_count"] == 1
        assert by_reader[0]["id"] == session["id"]
        assert by_reader[0]["state"] == "CONSENT_PENDING"
