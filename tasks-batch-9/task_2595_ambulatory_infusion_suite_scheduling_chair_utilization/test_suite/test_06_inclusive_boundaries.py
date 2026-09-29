"""Inclusive boundaries that must admit at the edge and refuse one step past it."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    DoseTier,
    LotStatus,
    PHARMACIST,
    SCHEDULER,
    add_patient_with_plan,
    assert_lot_ledger_conserved,
    book_appointment,
    create_lot,
    make_appointment_payload,
    make_preparation_payload,
    read_chair,
    read_lot,
    read_nurse,
    read_preparation,
    request_dose,
    setup_suite,
    validate_error,
    validate_paginated,
)


class TestNurseAcuityCeilingIsInclusive:
    """A slot load of exactly the capacity is admitted; one point more is refused."""

    def _two_visits_at_exactly_capacity(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            chair_labels=("A1", "A2", "A3"),
            drug_kind="gate",
            drug_overrides={
                "requires_lab_gate": False,
                "lab_min_anc": None,
                "lab_min_platelets": None,
            },
        )
        patient2, plan2 = add_patient_with_plan(api, suite, "MRN-0002", "Pat Two")
        patient3, plan3 = add_patient_with_plan(api, suite, "MRN-0003", "Pat Three")
        first = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        second = book_appointment(
            api,
            suite.center_id,
            patient2["id"],
            plan2["id"],
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        return suite, first, second, patient3, plan3

    def _attempt_third_booking(self, api: ApiClient, suite, patient3, plan3):
        return api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                patient3["id"],
                plan3["id"],
                suite.template_id,
                service_date="2026-08-10",
                requested_start_minute=540,
                cycle_number=1,
            ),
            SCHEDULER,
        )

    def test_the_second_visit_is_admitted_at_exactly_the_capacity_figure(self, api):
        """The comparison is load plus this visit's points against the capacity, so a
        resulting load of exactly the capacity is legal.

        Design: Difficulty/boundary_precision_check/nurse_acuity_exactly_at_capacity_admitted_then_one_point_over_refused
        """
        suite, first, second, _patient3, _plan3 = self._two_visits_at_exactly_capacity(api)

        assert first["acuity_points"] == 3
        assert first["chair_id"] == suite.chair_id("A1")
        assert first["start_minute"] == 540
        assert first["end_minute"] == 780

        assert second["acuity_points"] == 3
        assert second["chair_id"] == suite.chair_id("A2")
        assert second["start_minute"] == 540
        assert second["end_minute"] == 780

        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 6

    def test_one_point_past_the_ceiling_is_refused_by_the_acuity_rule(self, api):
        """A free chair remains and the single nurse's shift covers every candidate start,
        so the acuity ceiling is the only thing that can refuse the third visit.

        Design: Difficulty/boundary_precision_check/nurse_acuity_exactly_at_capacity_admitted_then_one_point_over_refused
        """
        suite, _first, _second, patient3, plan3 = self._two_visits_at_exactly_capacity(api)

        response = self._attempt_third_booking(api, suite, patient3, plan3)

        body = validate_error(response, ApiErrorId.ERR_NURSE_ACUITY_EXCEEDED, 409)
        assert body["error_id"] != ApiErrorId.ERR_NO_CHAIR_CAPACITY
        assert body["error_id"] != ApiErrorId.ERR_NO_NURSE_ON_SHIFT

    def test_the_refused_booking_reserved_neither_acuity_nor_chair_minutes(self, api):
        """A refused booking is a no-op on every derived figure.

        Design: Difficulty/boundary_precision_check/nurse_acuity_exactly_at_capacity_admitted_then_one_point_over_refused
        """
        suite, _first, _second, patient3, plan3 = self._two_visits_at_exactly_capacity(api)

        self._attempt_third_booking(api, suite, patient3, plan3)

        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 6
        assert read_chair(api, suite.chair_id("A3"))["committed_minutes"] == 0

        rows, _meta = validate_paginated(
            api.list_appointments(
                SCHEDULER,
                {"center_id": suite.center_id, "service_date": "2026-08-10"},
            )
        )
        assert len(rows) == 2


class TestLotEligibilityBoundaryDecidesTheSelection:
    """units_available at least units_requested is inclusive, and it picks the lot."""

    def _two_lots_and_two_doses(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            drug_kind="ungated",
            dose_tier=DoseTier.LOW,
            plan_overrides={"dose_mg_per_kg": 5, "total_cycles": 4},
        )
        early = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-EARLY",
            units_received=1,
            expires_on="2026-11-01T00:00:00Z",
        )
        late = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-LATE",
            units_received=3,
            expires_on="2026-12-01T00:00:00Z",
        )
        appointment = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        three_units = request_dose(api, appointment["id"], 3)
        one_unit = request_dose(api, appointment["id"], 1)
        return suite, early, late, appointment, three_units, one_unit

    def test_the_first_expiring_lot_is_skipped_when_it_cannot_cover_the_request(self, api):
        """A lot holding fewer units than the request is not a candidate at all, so the
        later-expiring lot wins at the exact boundary of three against three.

        Design: Difficulty/boundary_precision_check/lot_selection_units_available_boundary_then_exhausted_candidate_pool
        """
        _suite, _early, late, _appointment, three_units, _one_unit = (
            self._two_lots_and_two_doses(api)
        )

        assert read_preparation(api, three_units["id"])["drug_lot_id"] == late["id"]

    def test_the_smaller_request_returns_to_expiry_order(self, api):
        """Once only the earliest-expiring lot can cover the request, expiry order picks
        it, and both lots fall out of the candidate pool as their units reach zero.

        Design: Difficulty/boundary_precision_check/lot_selection_units_available_boundary_then_exhausted_candidate_pool
        """
        _suite, early, late, _appointment, _three_units, one_unit = (
            self._two_lots_and_two_doses(api)
        )

        assert read_preparation(api, one_unit["id"])["drug_lot_id"] == early["id"]

        late_row = read_lot(api, late["id"])
        assert late_row["units_committed"] == 3
        assert late_row["units_available"] == 0
        assert late_row["status"] == LotStatus.DEPLETED

        early_row = read_lot(api, early["id"])
        assert early_row["units_committed"] == 1
        assert early_row["units_available"] == 0
        assert early_row["status"] == LotStatus.DEPLETED

    def test_an_exhausted_candidate_pool_refuses_the_next_request(self, api):
        """With no lot left holding enough units the request is refused outright; the
        units are never split across two lots.

        Design: Difficulty/boundary_precision_check/lot_selection_units_available_boundary_then_exhausted_candidate_pool
        """
        _suite, early, late, appointment, _three_units, _one_unit = (
            self._two_lots_and_two_doses(api)
        )

        response = api.create_drug_preparation(
            appointment["id"], make_preparation_payload(1), PHARMACIST
        )

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOT, 409)

        rows, _meta = validate_paginated(
            api.list_drug_preparations(PHARMACIST, {"appointment_id": appointment["id"]})
        )
        assert len(rows) == 2

        early_row = read_lot(api, early["id"])
        late_row = read_lot(api, late["id"])
        assert early_row["units_committed"] == 1
        assert late_row["units_committed"] == 3
        assert_lot_ledger_conserved(early_row)
        assert_lot_ledger_conserved(late_row)
