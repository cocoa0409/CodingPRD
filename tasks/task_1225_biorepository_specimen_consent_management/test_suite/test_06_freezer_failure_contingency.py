"""Freezer failure contingency: posture cycle and the failure cascade."""
from test_helpers import (
    validate_success,
    QO_HEADERS,
    create_donor_with_consent,
    create_unit_with_slot,
    create_stored_specimen,
    create_aliquot_for,
    ingest_reading,
    book_reservation,
    get_unit,
    get_slot,
    get_aliquot,
    get_specimen,
)


def _unit_with_stored_aliquot(unit_code, **unit_kwargs):
    """Unit+slot with a 50.0ml specimen and one 20.0ml aliquot in the slot."""
    donor, consent = create_donor_with_consent()
    unit, slot = create_unit_with_slot(unit_code=unit_code, **unit_kwargs)
    specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                         initial_volume_ml=50.0)
    aliquot, _ = create_aliquot_for(specimen["id"], 20.0, storage_slot_id=slot["id"])
    return unit, slot, specimen, aliquot


class TestStorageUnitPostureCycle:
    """Cyclic posture machine: OPERATIONAL -> WARNING -> OPERATIONAL -> FAILURE -> OPERATIONAL."""

    def test_warning_posture_recovers_via_reading(self, api):
        """PRD §3.4: "A reading strictly above the unit's `warn_threshold_c` but at or
        below its `fail_threshold_c` moves an `OPERATIONAL` unit to `WARNING`."
        PRD §3.4: "A reading at or below `warn_threshold_c` returns a `WARNING` unit to
        `OPERATIONAL`; a unit in `FAILURE` never recovers through readings alone and
        stays failed until the return-to-service action below."

        Design: Difficulty/non_linear_state_machine/storage_unit_posture_cycle
        """
        unit, _, _, _ = _unit_with_stored_aliquot(
            "FRZ-CYC-A", warn_threshold_c=-70.0, fail_threshold_c=-60.0)
        ingest_reading(unit["id"], "2026-05-03T00:00:00Z", -69.9)
        assert get_unit(unit["id"])["posture"] == "WARNING"
        ingest_reading(unit["id"], "2026-05-03T01:00:00Z", -80.0)
        assert get_unit(unit["id"])["posture"] == "OPERATIONAL", (
            "a reading at/below the warn threshold cycles WARNING back to OPERATIONAL")

    def test_failure_then_return_to_service_releases_quarantine(self, api):
        """PRD §3.4: "Returning a unit flips every `OFFLINE` slot back to `AVAILABLE`
        and then reviews each `QUARANTINED` aliquot against a hard viability ceiling:
        if the degree-minute delta the unit accumulated over that aliquot's quarantine
        window is at most 120 degree-minutes, the aliquot returns to `IN_STORAGE`, and
        its specimen's `viability_status` returns to `USABLE` once no child aliquot
        remains quarantined."

        Design: Difficulty/non_linear_state_machine/storage_unit_posture_cycle
        """
        unit, slot, _, aliquot = _unit_with_stored_aliquot(
            "FRZ-CYC-B", warn_threshold_c=-70.0, fail_threshold_c=-60.0)
        # No excursion readings: quarantine-window degree-minute delta is 0.
        resp = api.declare_failure(unit["id"], {}, QO_HEADERS)
        validate_success(resp, expected_status=200)
        assert get_unit(unit["id"])["posture"] == "FAILURE"
        assert get_aliquot(aliquot["id"])["status"] == "QUARANTINED"
        assert get_slot(slot["id"])["status"] == "OFFLINE"
        resp = api.return_to_service(unit["id"], {}, QO_HEADERS)
        validate_success(resp, expected_status=200)
        assert get_unit(unit["id"])["posture"] == "OPERATIONAL"
        assert get_aliquot(aliquot["id"])["status"] == "IN_STORAGE", (
            "degree-minute delta 0 <= 120: quarantined aliquot must return to IN_STORAGE")
        assert get_slot(slot["id"])["status"] == "AVAILABLE"


class TestFreezerFailureCascadeDepth2:
    """Declare-failure cascade: unit FAILURE -> slots OFFLINE -> future BOOKED
    reservations CANCELLED, and contained aliquots QUARANTINED."""

    def _setup(self, api):
        donor, consent = create_donor_with_consent()
        unit, slot = create_unit_with_slot(unit_code="FRZ-TC2")
        reservation = book_reservation(slot["id"], "2026-06-01T10:00:00Z",
                                       "2026-06-01T12:00:00Z", purpose="MAINTENANCE")
        specimen, _ = create_stored_specimen(donor["id"], consent["id"], slot["id"],
                                             initial_volume_ml=50.0)
        aliquot, _ = create_aliquot_for(specimen["id"], 20.0, storage_slot_id=slot["id"])
        return unit, slot, reservation, specimen, aliquot

    def test_failure_cascades_slots_offline_and_cancels_future_reservations(self, api):
        """PRD §3.4: "Declaration moves the unit's `posture` from `OPERATIONAL` or
        `WARNING` to `FAILURE` and fires the contingency cascade: every slot of the
        unit flips from `AVAILABLE` to `OFFLINE`; every `BOOKED` reservation on those
        slots whose `ends_at` is still in the future is `CANCELLED`"

        Design: Difficulty/transitive_cascade/freezer_failure_cascade_depth2
        """
        unit, slot, reservation, _, _ = self._setup(api)
        resp = api.declare_failure(unit["id"], {}, QO_HEADERS)
        validate_success(resp, expected_status=200)
        assert get_unit(unit["id"])["posture"] == "FAILURE"
        assert get_slot(slot["id"])["status"] == "OFFLINE"
        reservations = validate_success(api.list_slot_reservations(slot["id"], QO_HEADERS))
        by_id = {r["id"]: r for r in reservations}
        assert by_id[reservation["id"]]["status"] == "CANCELLED", (
            "the future BOOKED reservation must be CANCELLED by the slot going offline")

    def test_failure_quarantines_contained_aliquot(self, api):
        """PRD §3.4: "every aliquot housed in the unit's slots and currently
        `IN_STORAGE` flips to `QUARANTINED`; and every specimen housed in those slots
        takes `viability_status` `QUARANTINED`."

        Design: Difficulty/transitive_cascade/freezer_failure_cascade_depth2
        """
        unit, slot, _, specimen, aliquot = self._setup(api)
        resp = api.declare_failure(unit["id"], {}, QO_HEADERS)
        validate_success(resp, expected_status=200)
        assert get_aliquot(aliquot["id"])["status"] == "QUARANTINED"
        assert get_specimen(specimen["id"])["viability_status"] == "QUARANTINED"
