"""Patients, eligibility screening, dose administration, and registry lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    administer_dose,
    assert_dose_administration,
    assert_eligibility_screening,
    create_dose_administration_payload,
    get_lot,
    make_patient,
    make_private_lot,
    make_product,
    make_public_dose,
    make_public_lot,
    make_screened_patient,
    make_screening,
    make_site,
    make_unit,
    open_and_close_excursion,
    open_excursion,
    resolve_excursion_viable,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    is_valid_uuid,
)

VM = TEST_USERS["vaccine_manager_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


class TestPatientAndScreeningRetrieval:
    def test_screenings_reverse_reachable_via_patient_list(self, api):
        """PRD §3.6: "Every visit that may end in a vaccination begins with an
        eligibility screening. The manager records the `screening_date` and the
        `insurance_category_at_visit`". PRD §2.3: "Paginated list responses
        carry `limit`, `offset`, `total_count`, and `has_more` in the `meta`
        object of the envelope."

        Design: Corner/entities/patient_fk_reverse_reachable_via_screenings_list
        """
        site = make_site()
        patient, screening = make_screened_patient(site["id"])
        resp = api.list_eligibility_screenings(patient["id"], VM)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["id"] == screening["id"]
        assert_eligibility_screening(data[0])


class TestEligibilityDetermination:
    def test_medicaid_under_19_is_vfc_eligible(self, api):
        """PRD §3.6: "The screening's `vfc_eligible` is then computed from two
        conjuncts: the patient's age on the screening date, taken as the number
        of days between `date_of_birth` and `screening_date` divided by 365.25
        and rounded down to whole years, is less than nineteen; and the
        `insurance_category_at_visit` is one of the four VFC-eligible
        categories. The derived `outcome` reads `VFC_ELIGIBLE` when both
        conjuncts hold and `PRIVATE_ONLY` otherwise."

        Design: Corner/calculations/eligibility_medicaid_under_19_is_vfc_eligible
        """
        site = make_site()
        patient = make_patient(site["id"], date_of_birth="2020-01-15",
                               insurance_category="MEDICAID")
        resp = api.create_eligibility_screening(
            patient["id"],
            {"screening_date": "2026-08-05", "insurance_category_at_visit": "MEDICAID"},
            VM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["vfc_eligible"] is True
        assert data["outcome"] == "VFC_ELIGIBLE"

    def test_commercial_insurance_is_private_only(self, api):
        """PRD §3.6: "The first four categories are VFC-eligible; `COMMERCIAL`
        is not." and "The derived `outcome` reads `VFC_ELIGIBLE` when both
        conjuncts hold and `PRIVATE_ONLY` otherwise."

        Design: Corner/calculations/eligibility_commercial_insurance_is_private_only
        """
        site = make_site()
        patient = make_patient(site["id"], date_of_birth="2020-01-15",
                               insurance_category="COMMERCIAL")
        resp = api.create_eligibility_screening(
            patient["id"],
            {"screening_date": "2026-08-05", "insurance_category_at_visit": "COMMERCIAL"},
            VM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["vfc_eligible"] is False
        assert data["outcome"] == "PRIVATE_ONLY"

    def test_nineteenth_birthday_is_not_vfc_eligible(self, api):
        """PRD §3.6: "the patient's age on the screening date, taken as the
        number of days between `date_of_birth` and `screening_date` divided by
        365.25 and rounded down to whole years, is less than nineteen". A
        patient whose 19th birthday falls on the screening date is exactly 19
        and fails the strict inequality.

        Design: Corner/calculations/eligibility_age_19_boundary_is_private_only
        """
        site = make_site()
        patient = make_patient(site["id"], date_of_birth="2007-08-05",
                               insurance_category="MEDICAID")
        resp = api.create_eligibility_screening(
            patient["id"],
            {"screening_date": "2026-08-05", "insurance_category_at_visit": "MEDICAID"},
            VM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["vfc_eligible"] is False, "age 19 is not less than 19"
        assert data["outcome"] == "PRIVATE_ONLY"

    def test_underinsured_and_native_categories_are_vfc_eligible(self, api):
        """PRD §3.6: categories are "`MEDICAID`, `UNINSURED`, `UNDERINSURED`,
        `AMERICAN_INDIAN_ALASKA_NATIVE`, or `COMMERCIAL`. The first four
        categories are VFC-eligible; `COMMERCIAL` is not."

        Design: Corner/calculations/eligibility_underinsurer_category_included
        """
        site = make_site()
        for category in ("UNDERINSURED", "AMERICAN_INDIAN_ALASKA_NATIVE"):
            patient = make_patient(site["id"], date_of_birth="2020-01-15",
                                   insurance_category=category)
            resp = api.create_eligibility_screening(
                patient["id"],
                {"screening_date": "2026-08-05",
                 "insurance_category_at_visit": category},
                VM,
            )
            data = validate_success(resp, expected_status=201)
            assert data["vfc_eligible"] is True, f"{category} must be VFC-eligible"
            assert data["outcome"] == "VFC_ELIGIBLE"


class TestDoseAdministrationGuards:
    def test_vfc_eligible_screening_on_private_lot_rejected(self, api):
        """PRD §3.6: "the lot's `stock_type` must agree with the screening
        `outcome`: a `VFC_ELIGIBLE` outcome requires a `PUBLIC_VFC` lot and a
        `PRIVATE_ONLY` outcome requires a `PRIVATE` lot, and a mismatch is
        rejected with `ERR_STOCK_ELIGIBILITY_MISMATCH` unless an `OPEN` borrow
        ticket covers the dose and `borrowed_context_ticket_id` is set to
        reference it."

        Design: Corner/validations/stock_eligibility_mismatch_vfc_patient_on_private_lot
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        priv_lot = make_private_lot(site["id"], unit["id"], product["id"],
                                    quantity_on_hand=5)
        patient, screening = make_screened_patient(site["id"], category="MEDICAID")
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], priv_lot["id"]
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_ELIGIBILITY_MISMATCH)

    def test_screening_date_must_equal_administration_date(self, api):
        """PRD §3.6: "Fifth, the screening must belong to the same patient as
        the dose and its `screening_date` must equal the `administration_date`
        (`ERR_SCREENING_MISMATCH`)."

        Design: Corner/validations/screening_date_must_match_administration_date
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        pub = make_public_lot(site["id"], unit["id"], product["id"], 3)
        patient, screening = make_screened_patient(
            site["id"], category="MEDICAID", visit_date="2026-08-04"
        )
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], pub["lot_id"],
                administration_date="2026-08-05",
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_SCREENING_MISMATCH)

    def test_depleted_lot_rejects_further_draws(self, api):
        """PRD §3.4: "Any operation that draws doses from a lot — dose
        administration, transfer shipment, opening a borrow from it, or using
        it as the source of a payback — requires the lot to be `AVAILABLE`. A
        lot that is `QUARANTINED`, `EXPIRED`, `DEPLETED`, or `WASTED_CLOSED`
        rejects such draws with `ERR_LOT_NOT_AVAILABLE` (HTTP 409)." PRD §3.6:
        "a lot whose on-hand reaches zero transitions to `DEPLETED`."

        Design: Corner/validations/insufficient_stock_blocks_dose_administration
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=1)
        patient, screening = make_screened_patient(site["id"], category="COMMERCIAL")
        first = administer_dose(site["id"], patient["id"], screening["id"], lot["id"])
        assert_dose_administration(first)
        assert get_lot(lot["id"])["status"] == "DEPLETED"
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], lot["id"]
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)

    def test_adult_patient_on_public_lot_fails_stock_match_first(self, api):
        """PRD §3.6: "Fourth, the lot's `stock_type` must agree with the
        screening `outcome` ... and a mismatch is rejected with
        `ERR_STOCK_ELIGIBILITY_MISMATCH`". "Sixth, when the dose draws from a
        `PUBLIC_VFC` lot, the patient must be active and still under nineteen
        years of age on the `administration_date`
        (`ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE`)." The 19-year-old's screening
        computes `PRIVATE_ONLY`, so the fourth check fires before the sixth.

        Design: Corner/errors/error_patient_not_vfc_eligible_age_blocks_public_dose
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        pub = make_public_lot(site["id"], unit["id"], product["id"], 3)
        patient, screening = make_screened_patient(
            site["id"], dob="2007-08-05", category="MEDICAID"
        )
        assert screening["outcome"] == "PRIVATE_ONLY"
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], pub["lot_id"]
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_ELIGIBILITY_MISMATCH)

    def test_dose_rejected_while_unit_quarantined(self, api):
        """PRD §3.6: "The checks run in this order. First, the storage unit
        holding the lot must not be quarantined
        (`ERR_STORAGE_UNIT_QUARANTINED`)."

        Design: Difficulty/cross_entity_state_dependency/dose_administration_gated_by_storage_unit_quarantine
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=5)
        patient, screening = make_screened_patient(site["id"], category="COMMERCIAL")
        open_excursion(unit["id"], recorded_at="2026-08-05T08:00:00Z")
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], lot["id"]
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_STORAGE_UNIT_QUARANTINED)

    def test_dose_allowed_after_excursion_resolves_viable(self, api):
        """PRD §3.3: "Resolving as viable — with free-text `resolution_notes`
        recorded — moves the excursion to `RESOLVED_VIABLE`, returns every
        `QUARANTINED` lot in the unit to `AVAILABLE`, clears the unit's
        `active_excursion_id` and drops `is_quarantined` to false". With the
        lot back to `AVAILABLE`, PRD §3.6's first and second checks pass and
        the dose records.

        Design: Difficulty/cross_entity_state_dependency/dose_administration_gated_by_storage_unit_quarantine
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=5)
        patient, screening = make_screened_patient(site["id"], category="COMMERCIAL")
        excursion = open_and_close_excursion(
            unit["id"], open_at="2026-08-05T08:00:00Z", close_at="2026-08-05T09:00:00Z"
        )
        resolve_excursion_viable(unit["id"], excursion["id"])
        dose = administer_dose(site["id"], patient["id"], screening["id"], lot["id"])
        assert_dose_administration(dose)
        assert get_lot(lot["id"])["quantity_on_hand"] == 4


class TestExpirationWindow:
    def test_administration_on_expiry_day_allowed(self, api):
        """PRD §2.10: "Administration from a lot is permitted while the
        administration date is on or before the lot's `expires_on`; it is
        forbidden once that date has passed."

        Design: Difficulty/resource_temporal_overlap/expiration_window_and_administration_date_interval_semantics
        """
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=5, expires_on="2026-08-15")
        patient, screening = make_screened_patient(
            site["id"], category="COMMERCIAL", visit_date="2026-08-15"
        )
        dose = administer_dose(
            site["id"], patient["id"], screening["id"], lot["id"],
            administration_date="2026-08-15",
        )
        assert is_valid_uuid(dose["id"]), (
            "administration_date == expires_on is inside the closed interval"
        )
        assert get_lot(lot["id"])["quantity_on_hand"] == 4

    def test_administration_after_expiry_sweep_rejected(self, api):
        """PRD §2.10: the expiration sweep moves a lot past its `expires_on`
        with doses remaining to `EXPIRED` and zeroes it. PRD §3.6: "Second,
        the lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE`). Third, the
        `administration_date` must be on or before the lot's `expires_on`
        (`ERR_LOT_EXPIRED`)." The swept lot fails the earlier state check.

        Design: Difficulty/resource_temporal_overlap/expiration_window_and_administration_date_interval_semantics
        """
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=5, expires_on="2026-08-15")
        patient, scr_ok = make_screened_patient(
            site["id"], category="COMMERCIAL", visit_date="2026-08-15"
        )
        administer_dose(
            site["id"], patient["id"], scr_ok["id"], lot["id"],
            administration_date="2026-08-15",
        )
        scr_late = make_screening(
            patient["id"], screening_date="2026-08-16",
            insurance_category_at_visit="COMMERCIAL",
        )
        set_clock("2026-08-16T00:00:00Z")
        assert get_lot(lot["id"])["status"] == "EXPIRED"
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], scr_late["id"], lot["id"],
                administration_date="2026-08-16",
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)


class TestExpiredLotCheckOrder:
    def test_expired_lot_draw_reports_state_error_not_date_error(self, api):
        """PRD §3.6: "The checks run in this order. First, the storage unit
        holding the lot must not be quarantined
        (`ERR_STORAGE_UNIT_QUARANTINED`). Second, the lot must be `AVAILABLE`
        (`ERR_LOT_NOT_AVAILABLE`). Third, the `administration_date` must be
        on or before the lot's `expires_on` (`ERR_LOT_EXPIRED`)." A lot
        already swept to `EXPIRED` fails the second check before the date
        comparison is ever reached.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_lot_expired_on_quarantined_unit
        """
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=5, expires_on="2026-08-03",
                               lot_number="L-OLD")
        set_clock("2026-08-04T00:00:00Z")
        patient, screening = make_screened_patient(
            site["id"], category="COMMERCIAL", visit_date="2026-08-05"
        )
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], lot["id"],
                administration_date="2026-08-05",
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)

    def test_clock_sweep_zeroes_expired_lot(self, api):
        """PRD §2.10: "every lot still `AVAILABLE` whose manufacturer
        expiration date now lies strictly in the past — the current calendar
        date is later than the lot's `expires_on` — and whose
        `quantity_on_hand` is still above zero transitions to `EXPIRED`, its
        `quantity_on_hand` is set to zero".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_lot_expired_on_quarantined_unit
        """
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=5, expires_on="2026-08-03",
                               lot_number="L-OLD")
        set_clock("2026-08-04T00:00:00Z")
        reloaded = get_lot(lot["id"])
        assert reloaded["status"] == "EXPIRED"
        assert reloaded["quantity_on_hand"] == 0


class TestRegistryLifecycle:
    def _dose(self, api):
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        pub = make_public_lot(site["id"], unit["id"], product["id"], 3)
        dose_ctx = make_public_dose(site["id"], pub["lot_id"])
        return site["id"], dose_ctx["dose"]["id"]

    def test_reject_reset_cycles_then_submit(self, api):
        """PRD §3.6: "A rejected dose is not terminal: resetting it returns
        the record from `REJECTED_BY_REGISTRY` to `PENDING_SUBMISSION` so the
        clinic can correct and re-file."

        Design: Difficulty/non_linear_state_machine/dose_administration_registry_cyclic_resubmission
        """
        site_id, dose_id = self._dose(api)
        for _ in range(2):
            rejected = validate_success(
                api.mark_registry_rejected(site_id, dose_id, VM)
            )
            assert rejected["registry_status"] == "REJECTED_BY_REGISTRY"
            reset = validate_success(api.reset_registry(site_id, dose_id, VM))
            assert reset["registry_status"] == "PENDING_SUBMISSION"
        submitted = validate_success(api.submit_registry(site_id, dose_id, VM))
        assert submitted["registry_status"] == "SUBMITTED"

    def test_single_reject_reset_roundtrip(self, api):
        """PRD §3.6: "A dose awaiting submission may be marked `SUBMITTED`
        once the state immunization registry accepts the filing, or marked
        `REJECTED_BY_REGISTRY` when the registry bounces it" and "resetting it
        returns the record from `REJECTED_BY_REGISTRY` to
        `PENDING_SUBMISSION`".

        Design: Difficulty/non_linear_state_machine/dose_administration_registry_cyclic_resubmission
        """
        site_id, dose_id = self._dose(api)
        rejected = validate_success(api.mark_registry_rejected(site_id, dose_id, VM))
        assert rejected["registry_status"] == "REJECTED_BY_REGISTRY"
        reset = validate_success(api.reset_registry(site_id, dose_id, VM))
        assert reset["registry_status"] == "PENDING_SUBMISSION"

    def test_submitted_dose_locks_registry_transitions(self, api):
        """PRD §3.6: "both transitions require the dose to currently be
        `PENDING_SUBMISSION`, drawing `ERR_INVALID_STATE` otherwise", and
        reset "returns the record from `REJECTED_BY_REGISTRY` to
        `PENDING_SUBMISSION`" — a `SUBMITTED` dose permits none of the three.

        Design: Corner/state_machines/dose_administration_terminal_submitted_lockdown
        """
        site_id, dose_id = self._dose(api)
        validate_success(api.submit_registry(site_id, dose_id, VM))
        for call in (api.submit_registry, api.mark_registry_rejected,
                     api.reset_registry):
            resp = call(site_id, dose_id, VM)
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDoseImmediateEffect:
    def test_dose_creation_decrements_lot_and_opens_pending_submission(self, api):
        """PRD §3.6: "A recorded administration takes immediate effect: the
        lot's `quantity_on_hand` decreases by one; `funding_source` is derived
        from the lot's `stock_type` — `PUBLIC_VFC` stock yields a `PUBLIC_VFC`
        funding source and `PRIVATE` stock yields `PRIVATE`; `registry_status`
        opens at `PENDING_SUBMISSION`".

        Design: Corner/consistency_model/dose_administration_atomic_decrement_and_response
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(site["id"], unit["id"], product["id"],
                               quantity_on_hand=3)
        patient, screening = make_screened_patient(site["id"], category="COMMERCIAL")
        resp = api.create_dose_administration(
            site["id"],
            create_dose_administration_payload(
                patient["id"], screening["id"], lot["id"]
            ),
            VM,
        )
        dose = validate_success(resp, expected_status=201)
        assert dose["registry_status"] == "PENDING_SUBMISSION"
        assert get_lot(lot["id"])["quantity_on_hand"] == 2, (
            "the decrement must be visible on immediate re-read"
        )
