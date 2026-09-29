"""Initial states, legal edges, refused edges and the cascades that hang off them."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_bank_scenario,
    dispatch_kit,
    latest_excursion,
    make_collection_site_headers,
    make_facilities_engineer_headers,
    make_intake_coordinator_headers,
    make_medical_director_headers,
    make_parent_guardian_headers,
    make_technologist_headers,
    open_consent_amendment,
    post_temperature_reading,
    read_enrollment,
    read_kit,
    read_tank,
    read_unit,
    register_enrollment,
    set_clock,
    sign_consent,
    validate_error,
    validate_paginated,
    validate_success,
)

INTAKE = make_intake_coordinator_headers("ic-001")


class TestInitialStates:
    def test_the_two_enrollment_axes_are_seeded_independently(self):
        """Registration writes both axes, each at its own declared starting value.

        "`lifecycle_status` tracks operational progress through `CONSENT_PENDING`, `ACTIVE`,
        `KIT_DISPATCHED`, `COLLECTED` and the two terminal values `CLOSED` and `WITHDRAWN`.
        `consent_status` tracks the currency of the consent document through `PENDING`,
        `CONSENTED`, `AMENDMENT_PENDING` and the terminal `REVOKED`."

        Design: Corner/state_machines/corner_enrollment_starts_on_both_axes_at_their_initial_states
        """
        set_clock("2026-08-01T00:00:00Z")

        created = validate_success(
            api_client.create_enrollment(
                {
                    "program_type": "PRIVATE_FAMILY",
                    "primary_parent_name": "Avery Lin",
                    "expected_delivery_date": "2026-08-10",
                    "collection_site_code": "SITE-01",
                },
                INTAKE,
            ),
            201,
        )

        assert created["lifecycle_status"] == "CONSENT_PENDING"
        assert created["consent_status"] == "PENDING"
        assert created["consent_signed_at"] is None
        assert created["consent_version"] == 0

    def test_a_kit_is_born_dispatched_rather_than_reaching_it_by_a_transition(self):
        """The kit machine's initial state is observable in the creation response itself.

        "A kit's status ranges over `DISPATCHED`, `HELD`, and the three terminal values `USED`,
        `EXPIRED` and `RETURNED`, and `hold_reason_code` is populated only while the kit is
        `HELD`."

        Design: Corner/state_machines/corner_enrollment_starts_on_both_axes_at_their_initial_states
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")

        kit = validate_success(
            api_client.create_collection_kit(
                {
                    "enrollment_id": enrollment["id"],
                    "kit_lot_code": "LOT-1",
                    "courier_tracking_code": "TRK-1",
                },
                INTAKE,
            ),
            201,
        )

        assert kit["status"] == "DISPATCHED"
        assert kit["hold_reason_code"] is None
        assert kit["version"] == 1


class TestKitDispatchDrivesTheEnrollmentAxis:
    def test_dispatch_stamps_the_shelf_life_and_advances_the_lifecycle_axis(self):
        """One POST against a child entity moves the parent's operational axis.

        "Dispatch stamps `dispatched_at` from the logical clock and computes `expires_at` as
        `dispatched_at` plus a shelf life of 120 days; the kit begins in `DISPATCHED`, and the
        enrollment advances `ACTIVE → KIT_DISPATCHED`."

        Design: Corner/state_machines/corner_kit_creation_drives_enrollment_active_to_kit_dispatched
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")

        kit = dispatch_kit(enrollment["id"], kit_lot_code="LOT-1", courier_tracking_code="TRK-1")

        assert kit["dispatched_at"].startswith("2026-08-01T00:00:00")
        assert kit["expires_at"].startswith("2026-11-29T00:00:00")
        assert read_enrollment(enrollment["id"])["lifecycle_status"] == "KIT_DISPATCHED"

    def test_the_consent_axis_and_the_version_counter_behave_independently(self):
        """The dispatch is a mutation of the enrollment, but only of its lifecycle axis.

        "a counter that starts at 1 on creation and increments by exactly 1 on every mutation of
        the row. Recomputing a derived value such as `balance_cents`, `occupied_slots` or
        `quality_acceptance_score` is a mutation for this purpose."

        Design: Corner/state_machines/corner_kit_creation_drives_enrollment_active_to_kit_dispatched
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        assert enrollment["version"] == 1
        signed = sign_consent(enrollment["id"], consent_document_hash="hash-aaa")
        assert signed["version"] == 2

        dispatch_kit(enrollment["id"], kit_lot_code="LOT-1", courier_tracking_code="TRK-1")

        after = read_enrollment(enrollment["id"])
        assert after["consent_status"] == "CONSENTED"
        assert after["consent_version"] == 1
        assert after["version"] == 3


class TestPreconditionsOfTheCollectionEdge:
    def test_a_kit_returned_by_the_withdrawal_cascade_cannot_be_collected_against(self):
        """The kit's own state answers before the revoked consent is ever consulted.

        "The kit must be in `DISPATCHED` at that moment: a kit sitting in `HELD` because of an
        open amendment, or already `USED`, `EXPIRED` or `RETURNED`, yields
        `ERR_INVALID_KIT_STATE`."

        Design: Corner/state_machines/corner_collection_on_a_returned_kit_violates_the_edge_precondition
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")
        kit = dispatch_kit(enrollment["id"], kit_lot_code="LOT-1", courier_tracking_code="TRK-1")
        validate_success(
            api_client.withdraw_enrollment(
                enrollment["id"],
                {"withdrawal_reason_code": "PARENT_REQUEST"},
                make_parent_guardian_headers(enrollment["id"]),
            )
        )
        set_clock("2026-08-10T06:00:00Z")

        response = api_client.create_collection(
            {
                "kit_id": kit["id"],
                "collected_at": "2026-08-10T05:00:00Z",
                "collection_volume_ml": 130.0,
                "anticoagulant_volume_ml": 25.0,
                "delivery_mode": "VAGINAL",
            },
            make_collection_site_headers("cs-001"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_KIT_STATE.value, 409)

        assert read_kit(kit["id"])["status"] == "RETURNED"
        assert read_kit(kit["id"])["hold_reason_code"] is None
        withdrawn = read_enrollment(enrollment["id"])
        assert withdrawn["lifecycle_status"] == "WITHDRAWN"
        assert withdrawn["consent_status"] == "REVOKED"
        assert withdrawn["withdrawal_reason_code"] == "PARENT_REQUEST"
        _, meta = validate_paginated(
            api_client.list_kit_collections(
                kit["id"], make_collection_site_headers("cs-001")
            )
        )
        assert meta["total_count"] == 0


class TestTheConsentAmendmentLoop:
    def test_opening_an_amendment_holds_the_dispatched_kit(self):
        """The forward leg of the cascade names its reason on the kit row.

        "Every collection kit of the enrollment in status `DISPATCHED` moves to `HELD` and
        records a `hold_reason_code` of `CONSENT_AMENDMENT_PENDING`."

        Design: Corner/state_machines/corner_consent_amendment_holds_the_kit_and_reconsent_releases_it
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")
        kit = dispatch_kit(enrollment["id"], kit_lot_code="LOT-1", courier_tracking_code="TRK-1")

        amended = open_consent_amendment(enrollment["id"], amendment_reason_code="RESEARCH_OPT_IN")

        assert amended["consent_status"] == "AMENDMENT_PENDING"
        assert amended["consent_amendment_count"] == 1
        assert amended["consent_version"] == 1
        assert amended["lifecycle_status"] == "KIT_DISPATCHED"

        held = read_kit(kit["id"])
        assert held["status"] == "HELD"
        assert held["hold_reason_code"] == "CONSENT_AMENDMENT_PENDING"

    def test_the_re_signature_releases_the_kit_without_extending_its_shelf_life(self):
        """The reverse leg restores the kit exactly, counter and expiry included.

        "every `HELD` kit of the enrollment whose `expires_at` has not yet passed returns to
        `DISPATCHED` and has its `hold_reason_code` cleared to null"

        Design: Corner/state_machines/corner_consent_amendment_holds_the_kit_and_reconsent_releases_it
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")
        kit = dispatch_kit(enrollment["id"], kit_lot_code="LOT-1", courier_tracking_code="TRK-1")
        open_consent_amendment(enrollment["id"], amendment_reason_code="RESEARCH_OPT_IN")

        resigned = sign_consent(enrollment["id"], consent_document_hash="hash-bbb")

        assert resigned["consent_status"] == "CONSENTED"
        assert resigned["consent_version"] == 2
        assert resigned["consent_amendment_count"] == 1

        released = read_kit(kit["id"])
        assert released["status"] == "DISPATCHED"
        assert released["hold_reason_code"] is None
        assert released["expires_at"] == kit["expires_at"]


class TestTheAmendmentCascadeIsFiltered:
    def test_a_used_kit_is_left_alone_by_the_amendment(self):
        """The cascade is predicated on the child's state, not applied to every child.

        "Recording a collection consumes the kit (`DISPATCHED → USED`) and advances the
        enrollment `KIT_DISPATCHED → COLLECTED`."

        Design: Corner/state_machines/corner_consent_amendment_holds_only_kits_still_dispatched
        """
        scenario = build_bank_scenario(stage="collected", tank_code=None)
        kit_before = read_kit(scenario["kit"]["id"])
        assert kit_before["status"] == "USED"
        assert read_enrollment(scenario["enrollment"]["id"])["lifecycle_status"] == "COLLECTED"

        amended = open_consent_amendment(
            scenario["enrollment"]["id"], amendment_reason_code="RESEARCH_OPT_IN"
        )

        assert amended["consent_status"] == "AMENDMENT_PENDING"
        assert amended["consent_amendment_count"] == 1
        assert amended["lifecycle_status"] == "COLLECTED"

        kit_after = read_kit(scenario["kit"]["id"])
        assert kit_after["status"] == "USED"
        assert kit_after["hold_reason_code"] is None


class TestUndeclaredEdges:
    def test_a_received_unit_cannot_jump_straight_into_a_tank(self):
        """The only inbound edge to cryopreservation starts at the reduced state.

        "It drives the unit `VOLUME_REDUCED → CRYOPRESERVED` and is guarded by five conditions
        beyond consent currency"

        Design: Corner/state_machines/corner_cryopreserve_from_processing_status_received_is_rejected
        """
        scenario = build_bank_scenario(stage="received", tank_code="TANK-A", capacity_slots=4)

        response = api_client.cryopreserve_unit(
            scenario["unit"]["id"],
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-01",
                "freeze_at": "2026-08-11T02:00:00Z",
            },
            make_technologist_headers("tech-001"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_UNIT_STATE.value, 409)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["processing_status"] == "RECEIVED"
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["tank_id"] is None

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 0
        assert tank["status"] == "ONLINE"

    def test_a_second_signature_on_a_current_consent_is_refused(self):
        """Replaying the signature is neither idempotent nor a second version bump.

        "Signature is admissible from `consent_status` of `PENDING` and from
        `AMENDMENT_PENDING`, and is refused with `ERR_INVALID_ENROLLMENT_STATE` when the
        enrollment's `lifecycle_status` has already reached `CLOSED` or `WITHDRAWN`."

        Design: Corner/state_machines/corner_second_initial_consent_is_not_idempotent_but_refused
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")

        response = api_client.sign_consent(
            enrollment["id"],
            {"consent_document_hash": "hash-aaa"},
            make_parent_guardian_headers(enrollment["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value, 409)

        after = read_enrollment(enrollment["id"])
        assert after["consent_version"] == 1
        assert after["consent_signed_at"].startswith("2026-08-01T00:00:00")
        assert after["lifecycle_status"] == "ACTIVE"


class TestTerminalStateLockdown:
    def test_a_withdrawn_enrollment_refuses_withdraw_consent_and_amendment_alike(self):
        """Three different triggers all bounce off the same terminal pair.

        "It is admissible only while `lifecycle_status` is not already `CLOSED` or `WITHDRAWN`,
        and from `COLLECTED` it carries one extra guard: no unit of the enrollment may have an
        `availability_status` of `RESERVED` or `RELEASED`, because a unit already promised to, or
        shipped to, a patient cannot be recalled."

        Design: Corner/state_machines/corner_withdrawn_enrollment_admits_no_further_transition
        """
        set_clock("2026-08-01T00:00:00Z")
        enrollment = register_enrollment(primary_parent_name="Avery Lin")
        sign_consent(enrollment["id"], consent_document_hash="hash-aaa")
        parent = make_parent_guardian_headers(enrollment["id"])
        withdrawn = validate_success(
            api_client.withdraw_enrollment(
                enrollment["id"], {"withdrawal_reason_code": "PARENT_REQUEST"}, parent
            )
        )
        version_after_withdraw = withdrawn["version"]

        again = api_client.withdraw_enrollment(
            enrollment["id"], {"withdrawal_reason_code": "PARENT_REQUEST"}, parent
        )
        resign = api_client.sign_consent(
            enrollment["id"], {"consent_document_hash": "hash-ccc"}, parent
        )
        amend = api_client.open_consent_amendment(
            enrollment["id"], {"amendment_reason_code": "RESEARCH_OPT_IN"}, parent
        )

        for response in (again, resign, amend):
            validate_error(response, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value, 409)

        final = read_enrollment(enrollment["id"])
        assert final["lifecycle_status"] == "WITHDRAWN"
        assert final["consent_status"] == "REVOKED"
        assert final["consent_version"] == 1
        assert final["consent_amendment_count"] == 0
        assert final["version"] == version_after_withdraw


def _stored_private_unit():
    """One eligible private unit frozen in slot A-01 of a four-slot tank."""
    return build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
        consent_document_hash="hash-aaa",
        kit_lot_code="LOT-1",
        courier_tracking_code="TRK-1",
        slot_code="A-01",
    )


class TestTheQuarantineCascadeAndItsCompensation:
    def test_an_alarm_reading_quarantines_the_unit_without_moving_its_other_axes(self):
        """The alarm writes the availability axis and nothing else on the unit.

        "Every unit in the alarmed tank whose `availability_status` is `PRIVATE_STORED` or
        `LISTED` moves to `QUARANTINED` with a `quarantine_reason_code` of `EXCURSION_OPEN`,
        processed in `created_at` ascending order."

        Design: Corner/state_machines/corner_excursion_resolution_reverses_every_quarantine_side_effect
        """
        scenario = _stored_private_unit()
        set_clock("2026-08-11T03:00:00Z")

        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-11T03:00:00Z"
        )

        tank = read_tank(scenario["tank"]["id"])
        assert tank["status"] == "ALARM"
        assert tank["last_temperature_c"] == pytest.approx(-140.0, abs=0.01)
        assert tank["last_reading_at"].startswith("2026-08-11T03:00:00")

        excursion = latest_excursion(scenario["tank"]["id"])
        assert excursion["status"] == "OPEN"
        assert excursion["detected_at"].startswith("2026-08-11T03:00:00")
        assert excursion["peak_temperature_c"] == pytest.approx(-140.0, abs=0.01)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "QUARANTINED"
        assert unit["quarantine_reason_code"] == "EXCURSION_OPEN"
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["tank_id"] == scenario["tank"]["id"]

    def test_a_benign_disposition_reverses_every_field_the_alarm_wrote(self):
        """Resolution restores the unit and the tank while the occupancy never drifted.

        "A `disposition` of `NO_IMPACT` or `REQUALIFY` moves the excursion to `RESOLVED`, returns
        the tank `ALARM → ONLINE`, and compensates the quarantine cascade: each quarantined unit
        of that tank returns to `PRIVATE_STORED` if it is `PRIVATE_FAMILY`, or `LISTED` if it is
        `PUBLIC_DONATION` and it has a listing suspended for `UNIT_QUARANTINED`, with
        `quarantine_reason_code` cleared to null in both cases and units walked in `created_at`
        ascending order"

        Design: Corner/state_machines/corner_excursion_resolution_reverses_every_quarantine_side_effect
        """
        scenario = _stored_private_unit()
        set_clock("2026-08-11T03:00:00Z")
        post_temperature_reading(
            scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-11T03:00:00Z"
        )
        excursion = latest_excursion(scenario["tank"]["id"])

        set_clock("2026-08-11T03:10:00Z")
        acknowledged = validate_success(
            api_client.acknowledge_excursion(
                excursion["id"],
                {"acknowledgement_note": "engineer on site"},
                make_facilities_engineer_headers("fe-002"),
            )
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_at"].startswith("2026-08-11T03:10:00")
        assert acknowledged["acknowledged_by_user_id"] == "fe-002"

        set_clock("2026-08-11T03:45:00Z")
        resolved = validate_success(
            api_client.resolve_excursion(
                excursion["id"],
                {"disposition": "NO_IMPACT", "peak_temperature_c": -140.0},
                make_medical_director_headers("md-001"),
            )
        )

        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"].startswith("2026-08-11T03:45:00")
        assert resolved["duration_minutes"] == 45

        unit = read_unit(scenario["unit"]["id"])
        assert unit["availability_status"] == "PRIVATE_STORED"
        assert unit["quarantine_reason_code"] is None

        tank = read_tank(scenario["tank"]["id"])
        assert tank["status"] == "ONLINE"
        assert tank["occupied_slots"] == 1
        assert tank["cumulative_excursion_minutes_30d"] == 45


class TestDisposalBubblesUpToTheEnrollment:
    def test_disposing_the_only_unit_closes_the_enrollment_and_frees_the_slot(self):
        """A terminal child drives its parent terminal with no request naming the parent.

        "Finally, if this was the enrollment's last live unit, the enrollment moves to `CLOSED`."

        Design: Corner/state_machines/corner_disposing_the_last_unit_closes_its_enrollment
        """
        scenario = _stored_private_unit()
        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 1
        set_clock("2026-09-01T00:00:00Z")

        disposed = validate_success(
            api_client.dispose_unit(
                scenario["unit"]["id"],
                {"reason": "QUALITY_FAILURE"},
                make_medical_director_headers("md-002"),
            )
        )

        assert disposed["availability_status"] == "DISPOSED"
        assert disposed["processing_status"] == "DISCARDED"
        assert disposed["disposition_reason"] == "QUALITY_FAILURE"
        assert disposed["disposed_at"].startswith("2026-09-01T00:00:00")

        enrollment = read_enrollment(scenario["enrollment"]["id"])
        assert enrollment["lifecycle_status"] == "CLOSED"
        assert enrollment["consent_status"] == "CONSENTED"

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 0
        assert tank["status"] == "ONLINE"
