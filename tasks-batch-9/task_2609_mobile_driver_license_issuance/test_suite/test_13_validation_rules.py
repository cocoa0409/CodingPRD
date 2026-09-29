"""Business rules that accept at the boundary and refuse just past it.

Aggregate caps, cross-entity assurance gates, an inclusive retention ceiling, a
strict minimisation posture and a gate that cannot be answered without replaying
another entity's ledger.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED,
    ERR_ASSURANCE_LEVEL_INSUFFICIENT,
    ERR_DATA_MINIMIZATION_VIOLATION,
    ERR_DEVICE_LIMIT_EXCEEDED,
    ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED,
    ERR_PROOFING_ASSURANCE_EXPIRED,
    ERR_PROTECTION_METHOD_MISMATCH,
    ERR_REVOCATION_STATUS_STALE,
)
from test_helpers.assertions import assert_field_values, assert_instant, rows_of
from test_helpers.factories import credential_payload, presentation_session_payload
from test_helpers.fixtures import (
    activate_credential,
    attest_device,
    create_active_credential,
    create_attested_device,
    create_approved_verifier,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    create_verified_session,
    device_version,
    first_delivery_of,
    open_address_change,
    open_presentation_session,
    provision_credential,
    register_device,
    register_reader_app,
    set_clock,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    make_holder_headers,
    make_verifier_operator_headers,
)

_SECOND_EVIDENCE = [
    {
        "evidence_type": "DOCUMENT_SCAN",
        "quality": "STRONG",
        "captured_at": "2026-07-25T09:00:00Z",
        "source_reference": "doc-2",
    },
    {
        "evidence_type": "BIOMETRIC_MATCH",
        "quality": "STRONG",
        "captured_at": "2026-07-25T09:05:00Z",
        "source_reference": "bio-2",
    },
]


def _retail_world(api, **reader_overrides):
    reader_app_overrides = {
        "app_identifier": "till-a",
        "certificate_serial": "SER-A1",
        "requested_elements": ["family_name", "age_over_21"],
        "base_rate_cents": 30,
    }
    reader_app_overrides.update(reader_overrides)
    return create_presentation_ready_world(
        api,
        verifier_overrides={
            "organization_name": "Prairie Cellars",
            "category": "AGE_RESTRICTED_RETAIL",
            "purpose_scope": ["family_name", "age_over_21"],
            "retention_ceiling_days": 30,
        },
        reader_app_overrides=reader_app_overrides,
    )


class TestMinimisationPostures:
    """AGE_ONLY refuses where ROUTINE would merely withhold."""

    def test_an_age_only_request_outside_the_allow_list_creates_no_row(self, api):
        """The strict posture means refusal, not a partial answer, and the refusal
        must leave the presentation list empty.

        PRD 3.8: "**`AGE_ONLY` is strict**: if anything at all would be withheld -
        that is, if the excess count would be greater than zero because some
        requested element is not a member of `age_only_allowed_elements` - the
        request is rejected with `ERR_DATA_MINIMIZATION_VIOLATION` (HTTP 422) and
        **no session row is created at all**."

        Design: Corner/validations/age_only_context_with_element_outside_allow_list_rejected
        """
        world = _retail_world(
            api, requested_elements=["age_over_21", "address"]
        )

        refused = api.create_presentation_session(
            presentation_session_payload(
                world["credential"]["id"],
                world["reader_app"]["id"],
                requested_elements=["age_over_21", "address"],
                context="AGE_ONLY",
                purpose="age gate",
                handset_handling="NO_SURRENDER",
                retention_days=7,
            ),
            make_verifier_operator_headers(world["verifier"]["id"]),
        )
        validate_error(refused, ERR_DATA_MINIMIZATION_VIOLATION, 422)

        _, meta = validate_paginated(
            api.list_presentation_sessions(
                PRIVACY_AUDITOR, {"credential_id": world["credential"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_a_law_enforcement_context_is_refused_to_a_retail_verifier(self, api):
        """The context entitlement is decided by the verifier's category, and it is
        decided before the reader application's un-listed state can be raised.

        PRD 3.8: "Second, a `context` of `LAW_ENFORCEMENT` is permitted only when
        the owning verifier's `category` is `LAW_ENFORCEMENT`; otherwise
        `ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED` (HTTP 403). Third, the reader
        application's `trust_state` must be `LISTED` **and** the newest trust-list
        snapshot of the active profile must actually cover the current logical
        instant"

        Design: Corner/validations/law_enforcement_context_from_a_retail_verifier_is_forbidden
        """
        bundle = create_active_credential(api)
        verifier = create_approved_verifier(
            api,
            organization_name="Prairie Cellars",
            category="AGE_RESTRICTED_RETAIL",
            purpose_scope=["family_name", "age_over_21"],
            retention_ceiling_days=30,
        )
        reader_app = register_reader_app(
            api,
            verifier["id"],
            app_identifier="till-a",
            certificate_serial="SER-A1",
            requested_elements=["family_name", "driving_privileges"],
            base_rate_cents=30,
        )

        refused = api.create_presentation_session(
            presentation_session_payload(
                bundle["credential"]["id"],
                reader_app["id"],
                requested_elements=["family_name", "driving_privileges"],
                context="LAW_ENFORCEMENT",
                purpose="roadside stop",
                handset_handling="NO_SURRENDER",
                retention_days=7,
            ),
            make_verifier_operator_headers(verifier["id"]),
        )
        validate_error(refused, ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED, 403)

        _, meta = validate_paginated(
            api.list_presentation_sessions(
                PRIVACY_AUDITOR, {"credential_id": bundle["credential"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestRetentionCeiling:
    """The ceiling comparison is inclusive, so exactly the ceiling is allowed."""

    def test_a_retention_period_equal_to_the_ceiling_is_accepted(self, api):
        """Thirty days against a thirty-day ceiling satisfies the rule and the
        session opens normally.

        PRD 3.8: "and finally `retention_days` must be no greater than the
        verifier's `retention_ceiling_days` - exactly the ceiling is accepted - or
        the request is rejected with `ERR_RETENTION_CEILING_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/retention_days_exactly_at_the_ceiling_is_accepted
        """
        world = _retail_world(api)

        session = open_presentation_session(
            api,
            world,
            context="ROUTINE",
            purpose="age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="TAP_TO_READ",
            retention_days=30,
        )
        assert_field_values(
            session,
            {
                "state": "CONSENT_PENDING",
                "retention_days": 30,
                "excess_element_count": 0,
            },
        )


class TestProvisioningAssuranceGates:
    """Provisioning is judged on the *other* entity's achieved assurance."""

    def test_a_session_one_band_short_of_the_profile_cannot_provision(self, api):
        """290 points verifies the session but does not reach the profile's
        required IAL2, so the credential is refused and none is stored.

        PRD 3.4: "The session's `achieved_assurance_level` must sit at or above the
        profile's `required_assurance_level` on the ordered ladder where `IAL1` is
        weakest, `IAL1_5` sits in the middle and `IAL2` is strongest; a shortfall is
        `ERR_ASSURANCE_LEVEL_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/provisioning_below_required_assurance_level_rejected
        """
        create_profile(api)
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])
        session = create_verified_session(
            api,
            holder["id"],
            [
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "STRONG",
                    "captured_at": "2026-07-20T09:00:00Z",
                    "source_reference": "doc-1",
                },
                {
                    "evidence_type": "BIOMETRIC_MATCH",
                    "quality": "WEAK",
                    "captured_at": "2026-07-20T09:05:00Z",
                    "source_reference": "bio-1",
                },
            ],
        )
        assert_field_values(
            session,
            {
                "state": "VERIFIED",
                "adjudication_score": 290,
                "achieved_assurance_level": "IAL1_5",
            },
        )

        refused = api.create_credential(
            credential_payload(
                holder["id"],
                device["id"],
                session["id"],
                device_version(api, device["id"]),
            ),
            ADJUDICATOR,
        )
        validate_error(refused, ERR_ASSURANCE_LEVEL_INSUFFICIENT, 422)

        _, meta = validate_paginated(
            api.list_credentials(ADJUDICATOR, {"holder_id": holder["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_lapsed_proofing_result_cannot_back_a_credential(self, api):
        """The 180-day shelf life runs out on 2027-01-28; a provisioning at
        2027-02-01 is refused and the read lapses the session.

        PRD 3.4: "The named proofing session's `assurance_expires_at` must fall
        strictly later than the current logical instant - and a session that has
        already lapsed into `EXPIRED` fails the same way - with
        `ERR_PROOFING_ASSURANCE_EXPIRED` (HTTP 409)."
        PRD 3.2: "Reading a verified session lazily applies its lapse: when the
        logical clock has reached or passed `assurance_expires_at`, the session
        moves `VERIFIED -> EXPIRED` and its `achieved_assurance_level` is retained
        for audit rather than cleared."

        Design: Corner/validations/provisioning_after_assurance_expiry_rejected
        """
        create_profile(api)
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])
        session = create_verified_session(api, holder["id"])
        assert_instant(
            session["assurance_expires_at"],
            "2027-01-28T00:00:00Z",
            "assurance_expires_at",
        )

        set_clock(api, "2027-02-01T00:00:00Z")

        refused = api.create_credential(
            credential_payload(
                holder["id"],
                device["id"],
                session["id"],
                device_version(api, device["id"]),
                valid_from="2027-02-01T00:00:00Z",
                valid_until="2032-01-01T00:00:00Z",
            ),
            ADJUDICATOR,
        )
        validate_error(refused, ERR_PROOFING_ASSURANCE_EXPIRED, 409)

        lapsed = validate_success(
            api.get_proofing_session(session["id"], ADJUDICATOR)
        )
        assert_field_values(
            lapsed,
            {"state": "EXPIRED", "assurance_expires_at": "2027-01-28T00:00:00Z"},
        )


class TestAggregateCaps:
    """Caps are read from the aggregate counter, not from the request."""

    def test_the_third_passing_attestation_is_refused_at_the_device_cap(self, api):
        """Two handsets already occupy the holder's slots, so the third handset's
        passing attestation is refused and it stays registered.

        PRD 3.3: "The **multi-device policy** is enforced on the passing branch
        only, and it is enforced before the counter moves: the holder's
        `bound_device_count` must be strictly below the profile's
        `max_devices_per_holder` for a passing attestation to be accepted, and a
        holder already at the cap is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`
        (HTTP 409)."

        Design: Corner/validations/third_device_attestation_exceeds_the_multi_device_cap
        """
        create_profile(api)
        holder = create_holder(api)
        for model in ("Pixel 9", "Galaxy Tab"):
            device = register_device(api, holder["id"], model_name=model)
            attest_device(api, device["id"])

        third = register_device(api, holder["id"], model_name="Pixel 8a")
        validate_error(
            api.attest_device(
                third["id"],
                {
                    "attestation_result": "PASS",
                    "secure_element_grade": "HARDWARE_STRONGBOX",
                },
                ADMIN,
            ),
            ERR_DEVICE_LIMIT_EXCEEDED,
            409,
        )

        stored_device = validate_success(api.get_device(third["id"], ADMIN))
        assert_field_values(stored_device, {"state": "REGISTERED", "version": 1})

        stored_holder = validate_success(api.get_holder(holder["id"], ADMIN))
        assert stored_holder["bound_device_count"] == 2

    def test_the_second_activation_is_refused_at_the_credential_slot_cap(self, api):
        """Both credentials provision because their windows do not overlap, but the
        slot cap of one bites at activation and nothing about the row changes.

        PRD 3.4: "Finally the **active-credential slot cap** applies: the holder's
        `active_credential_count` must be strictly below the profile's
        `max_active_credentials_per_holder`, and a holder already at the cap is
        rejected with `ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED` (HTTP 409). A
        credential that supersedes an `ACTIVE` predecessor is exempt from that cap"

        Design: Corner/validations/second_activation_exceeds_the_active_credential_cap
        """
        create_profile(
            api, profile_code="AAMVA-MDL-CAP1", max_active_credentials_per_holder=1
        )
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])

        first_session = create_verified_session(api, holder["id"])
        first = provision_credential(
            api,
            holder["id"],
            device["id"],
            first_session["id"],
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z",
        )
        activate_credential(api, first["id"], holder["id"])

        second_session = create_verified_session(api, holder["id"], _SECOND_EVIDENCE)
        second = provision_credential(
            api,
            holder["id"],
            device["id"],
            second_session["id"],
            valid_from="2027-08-01T00:00:00Z",
            valid_until="2028-08-01T00:00:00Z",
        )

        validate_error(
            api.activate_credential(
                second["id"],
                {"device_unlock_proof": "BIOMETRIC"},
                make_holder_headers(holder["id"]),
            ),
            ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED,
            409,
        )

        stored = validate_success(api.get_credential(second["id"], ADJUDICATOR))
        assert_field_values(
            stored, {"lifecycle_state": "PENDING_PROVISION", "activated_at": None}
        )

        stored_holder = validate_success(api.get_holder(holder["id"], ADMIN))
        assert stored_holder["active_credential_count"] == 1


class TestUnlockProofAtConsent:
    """The second of the two points where an unlock proof is demanded."""

    def test_consenting_with_the_wrong_unlock_method_is_refused(self, api):
        """The credential was activated on a biometric handset, so a passcode
        consent is refused and the session waits where it was.

        PRD 3.8: "The supplied `unlock_method` must equal the credential's
        `protection_method_at_activation` exactly, or the request is rejected with
        `ERR_PROTECTION_METHOD_MISMATCH` - the same code and the same kind of check
        as the activation-time `device_unlock_proof` comparison, applied at the
        second of the two points where an unlock proof is demanded."

        Design: Corner/validations/consent_unlock_method_not_matching_the_credential_rejected
        """
        world = _retail_world(api)
        session = open_presentation_session(
            api,
            world,
            context="ROUTINE",
            purpose="age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )

        validate_error(
            api.consent_presentation(
                session["id"],
                {"consent_decision": "APPROVE", "unlock_method": "PASSCODE"},
                make_holder_headers(world["holder"]["id"]),
            ),
            ERR_PROTECTION_METHOD_MISMATCH,
            422,
        )

        stored = validate_success(
            api.get_presentation_session(
                session["id"], make_holder_headers(world["holder"]["id"])
            )
        )
        assert_field_values(
            stored, {"state": "CONSENT_PENDING", "consent_unlock_method": None}
        )


class TestDeliveryFreshnessGate:
    """The freshness gate has to replay the ledger before it can answer."""

    def test_a_delivery_to_a_credential_suspended_by_the_plastic_is_refused(self, api):
        """Suspending the physical credential suspends the digital one and appends a
        ledger entry, so the replayed status is no longer valid and the push is
        refused with the delivery untouched.

        PRD 3.5: "requires the credential's replayed revocation status to read valid
        and to be fresh within the profile's `revocation_freshness_seconds`,
        otherwise `ERR_REVOCATION_STATUS_STALE` (HTTP 409)."
        PRD 3.5: "Recording a failed push ... The delivery moves `PENDING ->
        FAILED`, its `attempt_count` increments by 1"

        Design: Corner/validations/delivery_to_a_suspended_credential_fails_the_freshness_check
        """
        bundle = create_active_credential(api)
        order = open_address_change(
            api, bundle["holder"]["id"], address_line1="22 Birch Lane"
        )
        delivery = first_delivery_of(api, order["id"])

        validate_success(
            api.patch_physical_credential(
                bundle["holder"]["id"],
                {"physical_credential_status": "SUSPENDED"},
                ADMIN,
            )
        )

        validate_error(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-tok-1"}, ADMIN
            ),
            ERR_REVOCATION_STATUS_STALE,
            409,
        )

        status = validate_success(
            api.get_revocation_status(bundle["credential"]["id"], ADMIN)
        )
        assert_field_values(
            status, {"status": "SUSPENDED", "entry_sequence": 1, "is_fresh": True}
        )

        untouched = rows_of(api.list_order_deliveries(order["id"], ADMIN))
        assert_field_values(
            untouched[0], {"status": "PENDING", "attempt_count": 0}
        )
