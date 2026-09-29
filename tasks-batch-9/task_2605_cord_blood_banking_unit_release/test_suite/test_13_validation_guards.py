"""Uniqueness, range, shelf-life, aggregate-capacity and conditional guards."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_registry_code_sequence,
    build_bank_scenario,
    commission_tank,
    dispatch_kit,
    make_billing_admin_headers,
    make_collection_site_headers,
    make_facilities_engineer_headers,
    make_medical_director_headers,
    make_technologist_headers,
    open_storage_account,
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


def _private_enrollment_with_one_account():
    """A consented private enrollment carrying exactly one five-year account."""
    set_clock("2026-08-01T00:00:00Z")
    enrollment = register_enrollment(
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
    )
    sign_consent(enrollment["id"], consent_document_hash="hash-dup-v1")
    account = open_storage_account(
        enrollment["id"],
        billing_contact_email="avery@example.test",
        plan_term_years=5,
        prepaid_through_date="2027-08-01",
    )
    return enrollment, account


class TestOneAccountPerEnrollment:
    def test_a_second_account_on_the_same_enrollment_is_refused(self):
        """The uniqueness rule is the only thing standing between the two requests.

        "the enrollment must not already own an account, and a second attempt is
        `ERR_DUPLICATE_STORAGE_ACCOUNT`."

        Design: Corner/validations/corner_second_storage_account_on_one_enrollment_is_rejected
        """
        enrollment, account = _private_enrollment_with_one_account()

        response = api_client.create_storage_account(
            {
                "enrollment_id": enrollment["id"],
                "billing_contact_email": "second@example.test",
                "plan_term_years": 18,
                "prepaid_through_date": "2044-08-01",
            },
            make_billing_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_STORAGE_ACCOUNT.value, 409)

        rows, meta = validate_paginated(
            api_client.list_enrollment_storage_accounts(
                enrollment["id"], make_billing_admin_headers()
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == account["id"]
        assert rows[0]["plan_term_years"] == 5

    def test_the_surviving_account_opens_on_a_zeroed_ledger(self):
        """Nothing about the accepted account is disturbed by the refused one.

        "A new account begins with `status` of `ACTIVE`, `balance_cents` of 0,
        `lifetime_paid_cents` of 0, and `paid_through_date` seeded from `prepaid_through_date`."

        Design: Corner/validations/corner_second_storage_account_on_one_enrollment_is_rejected
        """
        enrollment, account = _private_enrollment_with_one_account()
        assert account["status"] == "ACTIVE"
        assert account["balance_cents"] == 0
        assert account["lifetime_paid_cents"] == 0
        assert account["last_settlement_total_cents"] is None
        assert account["paid_through_date"].startswith("2027-08-01")

        api_client.create_storage_account(
            {
                "enrollment_id": enrollment["id"],
                "billing_contact_email": "second@example.test",
                "plan_term_years": 18,
                "prepaid_through_date": "2044-08-01",
            },
            make_billing_admin_headers(),
        )

        after = validate_success(
            api_client.get_storage_account(account["id"], make_billing_admin_headers())
        )
        assert after == account


def _collection_awaiting_a_shipper():
    """A private collection drawn 19 hours before the clock, still unreceived."""
    return build_bank_scenario(
        stage="collected",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        collected_at="2026-08-10T05:00:00Z",
        collection_clock="2026-08-10T06:00:00Z",
        collection_volume_ml=130.0,
        anticoagulant_volume_ml=25.0,
        delivery_mode="CESAREAN",
    )


class TestTransportTemperatureUpperBound:
    def test_a_shipper_at_exactly_thirty_degrees_is_accepted(self):
        """The upper endpoint of the transport range is inside it.

        "Receipt also demands that the kit be `USED`, that the kit's `expires_at` not have
        passed, and that `transport_temp_c` lie within the closed range from 2.0 to 30.0 degrees
        Celsius — a shipper at exactly 2.0 or exactly 30.0 is acceptable, anything outside is
        `ERR_TRANSPORT_TEMP_OUT_OF_RANGE`."

        Design: Corner/validations/corner_transport_temperature_at_exactly_thirty_degrees_is_accepted
        """
        scenario = _collection_awaiting_a_shipper()

        set_clock("2026-08-11T00:00:00Z")
        received = validate_success(
            api_client.receive_collection(
                scenario["collection"]["id"],
                {"transport_temp_c": 30.0},
                make_technologist_headers("tech-001"),
            ),
            201,
        )

        assert received["status"] == "RECEIVED"
        assert received["transport_temp_c"] == pytest.approx(30.0, abs=0.01)
        assert received["received_at"].startswith("2026-08-11T00:00:00")
        assert received["hours_to_receipt"] == pytest.approx(19.00, abs=0.01)

    def test_the_accepted_receipt_mints_the_first_unit_of_the_bank(self):
        """Every field of the newborn unit is dictated, including its label.

        "The new unit records its `collection_id`, starts with a `processing_status` of
        `RECEIVED`, an `availability_status` of `UNAVAILABLE` and an `eligibility_status` of
        `PENDING`, copies `program_type` from the owning enrollment, receives its
        `unit_registry_code` from the bank-wide creation sequence"

        Design: Corner/validations/corner_transport_temperature_at_exactly_thirty_degrees_is_accepted
        """
        scenario = _collection_awaiting_a_shipper()

        set_clock("2026-08-11T00:00:00Z")
        validate_success(
            api_client.receive_collection(
                scenario["collection"]["id"],
                {"transport_temp_c": 30.0},
                make_technologist_headers("tech-001"),
            ),
            201,
        )

        rows, meta = validate_paginated(
            api_client.list_collection_units(
                scenario["collection"]["id"], make_technologist_headers("tech-001")
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        unit = rows[0]
        assert_registry_code_sequence(unit, 1)
        assert unit["collection_id"] == scenario["collection"]["id"]
        assert unit["processing_status"] == "RECEIVED"
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["eligibility_status"] == "PENDING"
        assert unit["program_type"] == "PRIVATE_FAMILY"
        assert unit["tank_id"] is None
        assert unit["slot_code"] is None


def _kit_one_day_past_its_shelf_life():
    """A kit dispatched on 1 August, read on 30 November — one day too late."""
    set_clock("2026-08-01T00:00:00Z")
    enrollment = register_enrollment(
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        expected_delivery_date="2026-11-25",
        collection_site_code="SITE-01",
    )
    sign_consent(enrollment["id"], consent_document_hash="hash-shelf-v1")
    kit = dispatch_kit(
        enrollment["id"], kit_lot_code="LOT-2026-S", courier_tracking_code="TRK-0500"
    )
    set_clock("2026-11-30T00:00:00Z")
    return enrollment, kit


class TestKitShelfLife:
    def test_a_collection_on_a_kit_past_its_shelf_life_is_refused(self):
        """The kit row is untouched, so only the shelf-life rung can answer.

        "Separately, a kit whose `expires_at` already lies in the past yields `ERR_KIT_EXPIRED`."

        Design: Corner/validations/corner_collection_on_a_kit_past_its_shelf_life_returns_kit_expired
        """
        _, kit = _kit_one_day_past_its_shelf_life()

        before = read_kit(kit["id"])
        assert before["status"] == "DISPATCHED"
        assert before["dispatched_at"].startswith("2026-08-01T00:00:00")
        assert before["expires_at"].startswith("2026-11-29T00:00:00")
        assert before["hold_reason_code"] is None

        response = api_client.create_collection(
            {
                "kit_id": kit["id"],
                "collected_at": "2026-11-30T00:00:00Z",
                "collection_volume_ml": 120.0,
                "anticoagulant_volume_ml": 25.0,
                "delivery_mode": "VAGINAL",
            },
            make_collection_site_headers("cs-001"),
        )

        validate_error(response, ApiErrorId.ERR_KIT_EXPIRED.value, 409)

    def test_the_expired_kit_writes_no_collection_and_does_not_advance_the_enrollment(self):
        """A refused collection cannot consume the kit nor move the operational axis.

        "Recording a collection consumes the kit (`DISPATCHED → USED`) and advances the
        enrollment `KIT_DISPATCHED → COLLECTED`."

        Design: Corner/validations/corner_collection_on_a_kit_past_its_shelf_life_returns_kit_expired
        """
        enrollment, kit = _kit_one_day_past_its_shelf_life()

        api_client.create_collection(
            {
                "kit_id": kit["id"],
                "collected_at": "2026-11-30T00:00:00Z",
                "collection_volume_ml": 120.0,
                "anticoagulant_volume_ml": 25.0,
                "delivery_mode": "VAGINAL",
            },
            make_collection_site_headers("cs-001"),
        )

        rows, meta = validate_paginated(
            api_client.list_kit_collections(kit["id"], make_collection_site_headers("cs-001"))
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert read_kit(kit["id"])["status"] == "DISPATCHED"
        assert read_enrollment(enrollment["id"])["lifecycle_status"] == "KIT_DISPATCHED"


def _one_slot_tank_holding_its_only_unit():
    """A single-slot tank with the first unit frozen in A-01 and a second unit ready."""
    tank = commission_tank(tank_code="TANK-A", tank_class="STANDARD", capacity_slots=1)
    first = build_bank_scenario(
        stage="cryopreserved",
        tank=tank,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
        consent_document_hash="hash-cap-a1",
        kit_lot_code="LOT-2026-P1",
        courier_tracking_code="TRK-0601",
        slot_code="A-01",
        freeze_at="2026-08-11T02:00:00Z",
    )
    second = build_bank_scenario(
        stage="determined",
        set_epoch=False,
        tank=tank,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Blair Nakamura",
        expected_delivery_date="2026-08-20",
        collection_site_code="SITE-02",
        consent_document_hash="hash-cap-b1",
        kit_lot_code="LOT-2026-P2",
        courier_tracking_code="TRK-0602",
        screening_collected_at="2026-08-20T05:00:00Z",
        screening_director="md-002",
        collected_at="2026-08-20T05:00:00Z",
        collection_clock="2026-08-20T06:00:00Z",
        receipt_clock="2026-08-21T00:00:00Z",
        technologist_user_id="tech-002",
        director_user_id="md-002",
    )
    return tank, first, second


class TestTankSlotAggregate:
    def test_the_second_unit_clears_every_gate_of_its_own(self):
        """The unit itself is faultless; only the collective slot count is short.

        "Otherwise, if the unit's `quality_acceptance_score` is at least its program tier's
        accept minimum — 70.00 for `PUBLIC_DONATION`, 55.00 for `PRIVATE_FAMILY` — the unit moves
        `PENDING → ELIGIBLE` with an `eligibility_reason_code` of `ACCEPTED`."

        Design: Corner/validations/corner_two_individually_valid_units_exceed_a_single_slot_tank
        """
        _, _, second = _one_slot_tank_holding_its_only_unit()

        unit = read_unit(second["unit"]["id"])
        assert unit["eligibility_status"] == "ELIGIBLE"
        assert unit["eligibility_reason_code"] == "ACCEPTED"
        assert unit["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)

    def test_a_second_freeze_into_a_single_slot_tank_is_refused(self):
        """The count, not the unit, is what fails at the capacity rung.

        "the tank's `occupied_slots` must be strictly below its `capacity_slots`, and a tank
        already at capacity yields `ERR_TANK_CAPACITY_EXCEEDED`"

        Design: Corner/validations/corner_two_individually_valid_units_exceed_a_single_slot_tank
        """
        tank, _, second = _one_slot_tank_holding_its_only_unit()

        response = api_client.cryopreserve_unit(
            second["unit"]["id"],
            {"tank_id": tank["id"], "slot_code": "A-02", "freeze_at": "2026-08-21T02:00:00Z"},
            make_technologist_headers("tech-002"),
        )

        validate_error(response, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED.value, 409)

    def test_the_full_tank_keeps_exactly_one_occupant_and_the_refused_unit_stays_unfrozen(self):
        """The occupancy figure is a count of live units and no count changed.

        "Because the unit now occupies a slot, the tank's `occupied_slots` is recomputed as the
        count of its units that are neither `RELEASED` nor `DISPOSED`."

        Design: Corner/validations/corner_two_individually_valid_units_exceed_a_single_slot_tank
        """
        tank, first, second = _one_slot_tank_holding_its_only_unit()

        api_client.cryopreserve_unit(
            second["unit"]["id"],
            {"tank_id": tank["id"], "slot_code": "A-02", "freeze_at": "2026-08-21T02:00:00Z"},
            make_technologist_headers("tech-002"),
        )

        after = read_tank(tank["id"])
        assert after["capacity_slots"] == 1
        assert after["occupied_slots"] == 1
        assert after["status"] == "ONLINE"

        rows, meta = validate_paginated(
            api_client.list_tank_units(tank["id"], make_facilities_engineer_headers("fe-001"))
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["unit"]["id"]
        assert rows[0]["slot_code"] == "A-01"

        refused = read_unit(second["unit"]["id"])
        assert refused["processing_status"] == "VOLUME_REDUCED"
        assert refused["availability_status"] == "UNAVAILABLE"
        assert refused["tank_id"] is None
        assert refused["slot_code"] is None
        assert refused["cryopreserved_at"] is None


def _two_enrollments_differing_only_in_program_type():
    """One public and one private enrollment, neither owning an account."""
    set_clock("2026-08-01T00:00:00Z")
    public = register_enrollment(
        program_type="PUBLIC_DONATION",
        primary_parent_name="Dana Ruiz",
        collection_site_code="SITE-02",
        hla_typing_consent=True,
    )
    sign_consent(public["id"], consent_document_hash="hash-pub-v1")
    private = register_enrollment(
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
    )
    sign_consent(private["id"], consent_document_hash="hash-prv-v1")
    return public, private


def _account_request(enrollment_id, email):
    return {
        "enrollment_id": enrollment_id,
        "billing_contact_email": email,
        "plan_term_years": 5,
        "prepaid_through_date": "2027-08-01",
    }


class TestBillingIsPrivateOnly:
    def test_an_account_on_a_public_donation_enrollment_is_refused(self):
        """Only a private family enrollment is billed at all.

        "The enrollment must have `program_type` equal to `PRIVATE_FAMILY`, and a
        public-donation enrollment is refused with `ERR_PROGRAM_TYPE_MISMATCH`; the enrollment
        must not already own an account, and a second attempt is
        `ERR_DUPLICATE_STORAGE_ACCOUNT`."

        Design: Corner/validations/corner_storage_account_on_a_public_donation_enrollment_is_rejected
        """
        public, _ = _two_enrollments_differing_only_in_program_type()

        response = api_client.create_storage_account(
            _account_request(public["id"], "dana@example.test"), make_billing_admin_headers()
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_TYPE_MISMATCH.value, 422)

        rows, meta = validate_paginated(
            api_client.list_enrollment_storage_accounts(public["id"], make_billing_admin_headers())
        )
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert rows == []

    def test_the_identical_request_on_a_private_enrollment_is_accepted(self):
        """The program-type flag is provably the only discriminator between the two.

        "Exactly one storage account may exist per enrollment, only a `PRIVATE_FAMILY` enrollment
        may have one, and invoices may only be issued against accounts of such enrollments; a
        mismatch anywhere along that chain is `ERR_PROGRAM_TYPE_MISMATCH`."

        Design: Corner/validations/corner_storage_account_on_a_public_donation_enrollment_is_rejected
        """
        public, private = _two_enrollments_differing_only_in_program_type()
        api_client.create_storage_account(
            _account_request(public["id"], "dana@example.test"), make_billing_admin_headers()
        )

        accepted = validate_success(
            api_client.create_storage_account(
                _account_request(private["id"], "avery@example.test"),
                make_billing_admin_headers(),
            ),
            201,
        )

        assert accepted["status"] == "ACTIVE"
        assert accepted["plan_term_years"] == 5
        assert accepted["balance_cents"] == 0
        assert accepted["enrollment_id"] == private["id"]


def _reduced_unit_with_no_quality_test():
    """A reduced private unit with a clean governing panel and no quality test at all."""
    return build_bank_scenario(
        stage="reduced",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
        consent_document_hash="hash-nq-v1",
        kit_lot_code="LOT-2026-Q",
        courier_tracking_code="TRK-0700",
    )


class TestTheMissingAcceptanceTest:
    def test_determination_without_any_quality_test_names_the_missing_test(self):
        """The panel rung is satisfied, so the answer can only be the missing test.

        "It is admissible only when the unit's `processing_status` is `VOLUME_REDUCED` or
        `CRYOPRESERVED`, and it requires a governing completed panel, exactly one
        `POST_PROCESSING` quality test on the unit, and a `sterility_result` of `NEGATIVE` on
        that test."

        Design: Corner/validations/corner_missing_quality_test_is_detected_before_the_sterility_check
        """
        scenario = _reduced_unit_with_no_quality_test()

        rows, meta = validate_paginated(
            api_client.list_unit_quality_tests(
                scenario["unit"]["id"], make_medical_director_headers("md-001")
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

        response = api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "premature determination"},
            make_medical_director_headers("md-001"),
        )

        validate_error(response, ApiErrorId.ERR_NO_QUALITY_TEST.value, 409)

    def test_the_refused_determination_leaves_the_unit_wholly_undetermined(self):
        """Neither the eligibility axis nor the reduction figures move.

        "In all three cases the determining director's `X-User-ID` is written to
        `eligibility_determined_by_user_id`, which is what later bars that same person from
        authorizing the release."

        Design: Corner/validations/corner_missing_quality_test_is_detected_before_the_sterility_check
        """
        scenario = _reduced_unit_with_no_quality_test()

        api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "premature determination"},
            make_medical_director_headers("md-001"),
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "PENDING"
        assert unit["eligibility_reason_code"] is None
        assert unit["eligibility_determined_by_user_id"] is None
        assert unit["quality_acceptance_score"] is None
        assert unit["processing_status"] == "VOLUME_REDUCED"
        assert unit["post_processing_volume_ml"] == pytest.approx(25.0, abs=0.01)
