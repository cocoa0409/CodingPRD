"""Closed-loop chemical program: dispenser placement safety rules, the
technician half-open window rule, dilution training gates, and the training
expiry sweep boundary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_dispenser,
    create_facility,
    create_product,
    create_technician,
    create_training_record,
    certify_training_record,
    make_field_technician_headers,
    run_daily,
    set_clock,
    setup_certified_training,
    setup_facility_with_product,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


def _setup_dilution_dispenser(api, zone="laundry"):
    """Facility + dilution-required NEUTRAL chemical + technician + SCHEDULED
    dispenser. Returns (facility, product, technician, dispenser)."""
    facility, product = setup_facility_with_product(
        facility_name="Fac M", category="CHEMICAL", base_price_cents=2500,
        qty_on_hand=50, dilution_required=True, chemical_family="NEUTRAL",
        unit_of_measure="GAL")
    technician = create_technician(name="Tech M")
    dispenser = create_dispenser(facility, product, technician, zone=zone)
    return facility, product, technician, dispenser


class TestDispenserTrainingGate:
    def test_complete_without_certified_training_rejected(self, api):
        """PRD: "when the dispensed product has `dilution_required` set, there
        must already exist a `CERTIFIED` training record for that facility and
        product, or the completion is rejected with
        `ERR_TRAINING_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/dispenser_complete_requires_certified_training
        """
        _facility, _product, technician, dispenser = \
            _setup_dilution_dispenser(api)
        resp = api.complete_dispenser(
            dispenser["id"], make_field_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CERTIFIED)
        after = validate_success(api.get_dispenser(dispenser["id"], ADMIN))
        assert after["status"] == "SCHEDULED"

    def test_complete_after_certification_installs_and_enrolls(self, api):
        """PRD: "A successful completion moves `SCHEDULED → INSTALLED`, stamps
        `installed_at`, and bubbles upward: the facility's
        `closed_loop_enrolled` becomes true as soon as it has at least one
        `INSTALLED` dispenser."
        PRD: "Before any clock-setting call has been made, the clock starts at
        exactly 2026-08-01T00:00:00Z"

        Design: Difficulty/cross_entity_state_dependency/dispenser_complete_requires_certified_training
        """
        facility, product, technician, dispenser = \
            _setup_dilution_dispenser(api)
        setup_certified_training(facility, product, score_pct=90)
        completed = validate_success(api.complete_dispenser(
            dispenser["id"], make_field_technician_headers(technician["id"])))
        assert completed["status"] == "INSTALLED"
        assert completed["installed_at"].startswith("2026-08-01T00:00:00"), (
            "installed_at is stamped from the logical clock at its default")
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["closed_loop_enrolled"] is True


class TestTechnicianHalfOpenWindows:
    def test_adjacent_windows_do_not_conflict(self, api):
        """PRD: "Technician load treats the window as a half-open interval
        that must not overlap any other `SCHEDULED` or `INSTALLED` dispenser
        owned by the same technician; under half-open semantics one install
        ending at exactly the moment another begins is not a conflict, but any
        true overlap is rejected with `ERR_TECHNICIAN_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_windows_adjacent_ok
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac N", category="CHEMICAL", base_price_cents=2500,
            qty_on_hand=50, chemical_family="NEUTRAL", unit_of_measure="GAL")
        other = create_product(sku="SKU-N2", name="N2", category="CHEMICAL",
                               base_price_cents=2500, unit_of_measure="GAL",
                               chemical_family="NEUTRAL", qty_on_hand=50)
        technician = create_technician(name="Tech N")
        create_dispenser(facility, product, technician, zone="z1",
                         install_start="2026-08-10T09:00:00Z",
                         install_end="2026-08-10T10:00:00Z")
        adjacent = create_dispenser(
            facility, other, technician, zone="z2",
            install_start="2026-08-10T10:00:00Z",
            install_end="2026-08-10T11:00:00Z")
        assert adjacent["status"] == "SCHEDULED", (
            "Half-open semantics: end == start is not an overlap")

    def test_overlapping_window_rejected(self, api):
        """PRD: "Technician load treats the window as a half-open interval
        that must not overlap any other `SCHEDULED` or `INSTALLED` dispenser
        owned by the same technician; under half-open semantics one install
        ending at exactly the moment another begins is not a conflict, but any
        true overlap is rejected with `ERR_TECHNICIAN_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_windows_adjacent_ok
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac N", category="CHEMICAL", base_price_cents=2500,
            qty_on_hand=50, chemical_family="NEUTRAL", unit_of_measure="GAL")
        technician = create_technician(name="Tech N")
        create_dispenser(facility, product, technician, zone="z1",
                         install_start="2026-08-10T09:00:00Z",
                         install_end="2026-08-10T10:00:00Z")
        resp = api.create_dispenser(
            {"facility_id": facility["id"], "product_id": product["id"],
             "zone": "z3", "technician_id": technician["id"],
             "install_start": "2026-08-10T09:30:00Z",
             "install_end": "2026-08-10T10:30:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_WINDOW_CONFLICT)


class TestZoneSafetyBeatsWindowConflict:
    def test_incompatible_placement_reported_when_both_violated(self, api):
        """PRD: "When several checks could reject the same request, the system
        evaluates them in the following fixed order, and the first failing
        check determines the response:"
        PRD: "12. **Zone incompatibility.** No two dispensers in `SCHEDULED`
        or `INSTALLED` status in the same facility and zone may pair chemical
        family `ACID` with `OXIDIZER`; otherwise `ERR_INCOMPATIBLE_PLACEMENT`
        (409)."
        PRD: "13. **Technician window conflict.** A new install window must
        not overlap another `SCHEDULED` or `INSTALLED` install of the same
        technician under half-open interval semantics, so one window ending
        exactly when another begins does not conflict; otherwise
        `ERR_TECHNICIAN_WINDOW_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/incompatible_placement_beats_window_conflict
        """
        facility = create_facility(name="Fac I")
        technician = create_technician(name="Tech One")
        acid = create_product(sku="SKU-CA", name="Acid cleaner",
                              category="CHEMICAL", base_price_cents=2500,
                              unit_of_measure="GAL", chemical_family="ACID",
                              qty_on_hand=50)
        oxidizer = create_product(sku="SKU-CO", name="Oxidizer",
                                  category="CHEMICAL", base_price_cents=2600,
                                  unit_of_measure="GAL",
                                  chemical_family="OXIDIZER", qty_on_hand=50)
        create_dispenser(facility, acid, technician, zone="kitchen",
                         install_start="2026-08-10T09:00:00Z",
                         install_end="2026-08-10T10:00:00Z")
        resp = api.create_dispenser(
            {"facility_id": facility["id"], "product_id": oxidizer["id"],
             "zone": "kitchen", "technician_id": technician["id"],
             "install_start": "2026-08-10T09:30:00Z",
             "install_end": "2026-08-10T10:30:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INCOMPATIBLE_PLACEMENT)

    def test_dual_violation_persists_no_dispenser(self, api):
        """PRD: "12. **Zone incompatibility.** No two dispensers in
        `SCHEDULED` or `INSTALLED` status in the same facility and zone may
        pair chemical family `ACID` with `OXIDIZER`; otherwise
        `ERR_INCOMPATIBLE_PLACEMENT` (409)."
        PRD: "the dispenser list accepts `facility_id`, `product_id`,
        `technician_id`, and `status` filters"

        Design: Difficulty/priority_pair_validation_conflict/incompatible_placement_beats_window_conflict
        """
        facility = create_facility(name="Fac I")
        technician = create_technician(name="Tech One")
        acid = create_product(sku="SKU-CA", name="Acid cleaner",
                              category="CHEMICAL", base_price_cents=2500,
                              unit_of_measure="GAL", chemical_family="ACID",
                              qty_on_hand=50)
        oxidizer = create_product(sku="SKU-CO", name="Oxidizer",
                                  category="CHEMICAL", base_price_cents=2600,
                                  unit_of_measure="GAL",
                                  chemical_family="OXIDIZER", qty_on_hand=50)
        create_dispenser(facility, acid, technician, zone="kitchen",
                         install_start="2026-08-10T09:00:00Z",
                         install_end="2026-08-10T10:00:00Z")
        resp = api.create_dispenser(
            {"facility_id": facility["id"], "product_id": oxidizer["id"],
             "zone": "kitchen", "technician_id": technician["id"],
             "install_start": "2026-08-10T09:30:00Z",
             "install_end": "2026-08-10T10:30:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INCOMPATIBLE_PLACEMENT)
        data, meta = validate_paginated(api.list_dispensers(
            ADMIN, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 1, (
            "The rejected create persists no second dispenser")


class TestTrainingCertifyAndExpiry:
    def test_certify_low_score_marks_failed(self, api):
        """PRD: "Certification, also by a `DistributorAdmin`, supplies a
        `score_pct` between 0 and 100: a score of at least 80 moves the record
        to `CERTIFIED`, stamping `certified_at` and setting `expires_at`
        exactly 365 days later, while a score below 80 moves it to `FAILED`,
        which is terminal."

        Design: Corner/validations/certify_low_score_marks_failed
        """
        facility, product, technician, dispenser = \
            _setup_dilution_dispenser(api, zone="kitchen")
        record = create_training_record(facility, product)
        failed = certify_training_record(record["id"], 79)
        assert failed["status"] == "FAILED", "79 < 80 marks FAILED"

        resp = api.certify_training_record(record["id"], 95, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # FAILED is terminal

        resp = api.complete_dispenser(
            dispenser["id"], make_field_technician_headers(technician["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CERTIFIED)

    def test_training_expiry_boundary_sweep(self, api):
        """PRD: "Certification does not last forever — when the daily sweep
        (§3.9) finds a `CERTIFIED` record whose `expires_at` is strictly in
        the past, the record moves to `EXPIRED`; at the exact `expires_at`
        instant it is still `CERTIFIED`."
        PRD: "Because every expiry test is strict — strictly greater than the
        recorded deadline — a record whose deadline equals the current clock
        time survives the sweep for one more day."

        Design: Corner/state_machines/training_expiry_boundary_sweep
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AC", category="CHEMICAL", base_price_cents=2500,
            qty_on_hand=50, dilution_required=True, chemical_family="NEUTRAL",
            unit_of_measure="GAL")
        record = setup_certified_training(facility, product, score_pct=95)
        assert record["status"] == "CERTIFIED"
        assert record["expires_at"].startswith("2027-08-01T00:00:00"), (
            "expires_at is exactly 365 days after certification at the "
            "default clock")

        set_clock("2027-08-01T00:00:00Z")
        run_daily()
        after_first = validate_success(
            api.get_training_record(record["id"], ADMIN))
        assert after_first["status"] == "CERTIFIED", (
            "At the exact expires_at instant the record is still CERTIFIED")

        set_clock("2027-08-01T00:00:01Z")
        run_daily()
        after_second = validate_success(
            api.get_training_record(record["id"], ADMIN))
        assert after_second["status"] == "EXPIRED", (
            "One second past expires_at the sweep moves it to EXPIRED")
