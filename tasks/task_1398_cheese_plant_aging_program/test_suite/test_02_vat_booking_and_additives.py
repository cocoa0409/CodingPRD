"""Vat booking gates (OCC, half-open overlap, cleanliness), make scheduling,
and the additive-lot consume/deplete/refund cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_make_sheet,
    assert_vat,
    complete_make,
    create_intake,
    create_make_sheet,
    create_plant,
    create_released_additive_pair,
    create_vat,
    get_vat,
    make_completed_batch,
    set_clock,
    sign_steps_through_curd_ready,
    start_make,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
RECEIVER = TEST_USERS["milk_receiver_headers"]
PLANNER = TEST_USERS["make_planner_headers"]
QA = TEST_USERS["qa_grader_headers"]


def _booking_base(license_number, volume_liters=5000.0, culture_qty=None, coagulant_qty=None):
    """Clock -> plant -> vat -> accepted intake -> released culture/coagulant."""
    set_clock("2026-08-01T00:00:00Z")
    plant = create_plant(license_number=license_number)
    vat = create_vat(plant["id"])
    intake = create_intake(plant["id"], volume_liters=volume_liters)
    culture, coagulant = create_released_additive_pair(
        plant["id"], culture_qty=culture_qty, coagulant_qty=coagulant_qty
    )
    return plant, vat, intake, culture, coagulant


class TestMakeScheduling:
    def test_make_sheet_variety_pins_steps_required(self, api):
        """PRD §3.3: "The variety pins `make_steps_required` at creation —
        eight steps for `CHEDDAR`, six for `COLBY`, five each for `BRICK` and
        `MUENSTER` — while `make_steps_completed` starts at zero and
        `step_signer_ids` starts empty."

        Design: Corner/entities/make_sheet_variety_pins_steps_required
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-204")
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            variety="MUENSTER",
        )
        assert_make_sheet(make)
        assert make["make_steps_required"] == 5, (
            f"MUENSTER pins 5 required steps, got {make['make_steps_required']}"
        )
        assert make["make_steps_completed"] == 0
        assert make["status"] == "SCHEDULED"

    def test_make_sheet_create_occ_stale_vat_version(self, api):
        """PRD §2.8: "Creating a make sheet (`POST /plant/make-sheets`)
        requires a non-optional `expected_vat_version` field carrying the
        target vat's `version` as the client last observed it. If the vat's
        current `version` differs — because another planner has since booked
        or cancelled a make on that vat, each of which advances the vat's
        version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and nothing is written."

        Design: Corner/endpoints/make_sheet_create_occ_stale_vat_version
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-242", volume_liters=20000.0)
        stale_version = vat["version"]
        create_make_sheet(
            vat["id"], stale_version, intake["id"], culture["id"], coagulant["id"],
            scheduled_start="2026-08-01T02:00:00Z", scheduled_end="2026-08-01T04:00:00Z",
        )
        resp = api.create_make_sheet(
            {
                "vat_id": vat["id"],
                "milk_intake_id": intake["id"],
                "variety": "MUENSTER",
                "scheduled_start": "2026-08-01T06:00:00Z",
                "scheduled_end": "2026-08-01T08:00:00Z",
                "liters_committed": 5000.0,
                "culture_lot_id": culture["id"],
                "coagulant_lot_id": coagulant["id"],
                "culture_units_planned": 5.0,
                "coagulant_ml_planned": 250.0,
                "expected_vat_version": stale_version,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestVatBookingOverlap:
    def test_vat_booking_half_open_adjacency_allowed(self, api):
        """PRD §3.3: "Back-to-back adjacency — the requested start equalling an
        existing end, or the requested end equalling an existing start — does
        not overlap and is always allowed; a true collision fails with
        `ERR_VAT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vat_booking_half_open_interval_adjacency
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-114", volume_liters=20000.0)
        create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            scheduled_start="2026-08-01T02:00:00Z", scheduled_end="2026-08-01T06:00:00Z",
        )
        vat_now = get_vat(vat["id"])
        adjacent = create_make_sheet(
            vat["id"], vat_now["version"], intake["id"], culture["id"], coagulant["id"],
            scheduled_start="2026-08-01T06:00:00Z", scheduled_end="2026-08-01T10:00:00Z",
        )
        assert adjacent["status"] == "SCHEDULED", (
            "a booking whose start equals the existing end must be allowed"
        )

    def test_vat_booking_true_overlap_rejected(self, api):
        """PRD §3.3: "Intervals are half-open: each booking includes its start
        instant and excludes its end instant, so a collision exists exactly
        when the requested start falls before an existing booking's end and
        the requested end falls after that booking's start. Back-to-back
        adjacency — the requested start equalling an existing end, or the
        requested end equalling an existing start — does not overlap and is
        always allowed; a true collision fails with `ERR_VAT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vat_booking_half_open_interval_adjacency
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-114B", volume_liters=20000.0)
        create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            scheduled_start="2026-08-01T02:00:00Z", scheduled_end="2026-08-01T06:00:00Z",
        )
        vat_now = get_vat(vat["id"])
        resp = api.create_make_sheet(
            {
                "vat_id": vat["id"],
                "milk_intake_id": intake["id"],
                "variety": "MUENSTER",
                "scheduled_start": "2026-08-01T05:59:00Z",
                "scheduled_end": "2026-08-01T09:00:00Z",
                "liters_committed": 5000.0,
                "culture_lot_id": culture["id"],
                "coagulant_lot_id": coagulant["id"],
                "culture_units_planned": 5.0,
                "coagulant_ml_planned": 250.0,
                "expected_vat_version": vat_now["version"],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_VAT_OVERLAP, 409)

    def test_error_vat_not_clean_on_booking(self, api):
        """PRD §3.3: "The vat must be clean: `cip_clean` of `false` fails with
        `ERR_VAT_NOT_CLEAN`."
        PRD §3.4: "The vat moves `IN_MAKE` → `CLEANING` with `cip_clean` set to
        `false`, closing the vat to new bookings until cleaning completes."

        Design: Corner/errors/error_vat_not_clean_on_booking
        """
        ctx = make_completed_batch(volume_liters=12000.0, liters_committed=5000.0)
        vat_now = get_vat(ctx["vat"]["id"])
        assert vat_now["status"] == "CLEANING" and vat_now["cip_clean"] is False
        resp = api.create_make_sheet(
            {
                "vat_id": ctx["vat"]["id"],
                "milk_intake_id": ctx["intake"]["id"],
                "variety": "MUENSTER",
                "scheduled_start": "2026-08-01T06:00:00Z",
                "scheduled_end": "2026-08-01T08:00:00Z",
                "liters_committed": 5000.0,
                "culture_lot_id": ctx["culture"]["id"],
                "coagulant_lot_id": ctx["coagulant"]["id"],
                "culture_units_planned": 5.0,
                "coagulant_ml_planned": 250.0,
                "expected_vat_version": vat_now["version"],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_VAT_NOT_CLEAN, 409)


class TestAdditiveConsumeAndRefund:
    def test_additive_quantities_consumed_at_start(self, api):
        """PRD §3.4: "Starting consumes. The culture lot's `quantity_on_hand`
        drops by `culture_units_planned` and the coagulant lot's by
        `coagulant_ml_planned`, with any lot driven to exactly zero cascading
        to `DEPLETED`."

        Design: Difficulty/compensating_invariant/additive_quantity_conserved_across_start_and_cancel
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-116A")
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            culture_units_planned=10.0, coagulant_ml_planned=250.0,
        )
        start_make(make["id"])
        culture_now = validate_success(api.get_additive_lot(culture["id"], QA))
        coagulant_now = validate_success(api.get_additive_lot(coagulant["id"], QA))
        assert culture_now["quantity_on_hand"] == pytest.approx(90.0), (
            f"culture must drop by 10.0 at start, got {culture_now['quantity_on_hand']}"
        )
        assert coagulant_now["quantity_on_hand"] == pytest.approx(4750.0), (
            f"coagulant must drop by 250.0 at start, got {coagulant_now['quantity_on_hand']}"
        )

    def test_additive_quantity_conserved_across_start_and_cancel(self, api):
        """PRD §3.3: "A make already `IN_PROGRESS` is cancelled with full
        compensation: the culture lot's `quantity_on_hand` is increased by
        `culture_units_planned` and the coagulant lot's by
        `coagulant_ml_planned` — a lot sitting `DEPLETED` returns to `RELEASED`
        when the refund lifts it above zero — and the intake's
        `consumed_liters` is decreased by `liters_committed`, reversing the
        commit."

        Design: Difficulty/compensating_invariant/additive_quantity_conserved_across_start_and_cancel
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-116")
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            culture_units_planned=10.0, coagulant_ml_planned=250.0,
        )
        start_make(make["id"])
        validate_success(api.cancel_make_sheet(make["id"], PLANNER))
        culture_now = validate_success(api.get_additive_lot(culture["id"], QA))
        coagulant_now = validate_success(api.get_additive_lot(coagulant["id"], QA))
        assert culture_now["quantity_on_hand"] == pytest.approx(100.0), (
            "start+cancel must restore the culture lot to its pre-start quantity"
        )
        assert coagulant_now["quantity_on_hand"] == pytest.approx(5000.0), (
            "start+cancel must restore the coagulant lot to its pre-start quantity"
        )
        make_now = validate_success(api.get_make_sheet(make["id"], PLANNER))
        assert make_now["status"] == "CANCELLED"

    def test_additive_lot_depleted_then_released_via_refund(self, api):
        """PRD §3.1: "a `RELEASED` lot whose `quantity_on_hand` reaches zero
        through make-start consumption becomes `DEPLETED`, and a `DEPLETED` lot
        returns to `RELEASED` when a make-sheet cancellation refunds a quantity
        that lifts `quantity_on_hand` above zero."

        Design: Difficulty/non_linear_state_machine/additive_lot_depleted_released_cycle_via_refund
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-105", culture_qty=10.0)
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            culture_units_planned=10.0, coagulant_ml_planned=250.0,
        )
        start_make(make["id"])
        depleted = validate_success(api.get_additive_lot(culture["id"], QA))
        assert depleted["status"] == "DEPLETED", (
            f"lot driven to exactly zero must be DEPLETED, got {depleted['status']}"
        )
        assert depleted["quantity_on_hand"] == pytest.approx(0.0)
        validate_success(api.cancel_make_sheet(make["id"], PLANNER))
        restored = validate_success(api.get_additive_lot(culture["id"], QA))
        assert restored["status"] == "RELEASED", (
            f"refund above zero must return the lot to RELEASED, got {restored['status']}"
        )
        assert restored["quantity_on_hand"] == pytest.approx(10.0)
        make_now = validate_success(api.get_make_sheet(make["id"], PLANNER))
        assert make_now["status"] == "CANCELLED"

    def test_cancel_reverses_milk_commit_and_frees_vat(self, api):
        """PRD §3.3: "A make already `IN_PROGRESS` is cancelled with full
        compensation: the culture lot's `quantity_on_hand` is increased by
        `culture_units_planned` and the coagulant lot's by
        `coagulant_ml_planned` — a lot sitting `DEPLETED` returns to `RELEASED`
        when the refund lifts it above zero — and the intake's
        `consumed_liters` is decreased by `liters_committed`, reversing the
        commit. In both cases the vat returns to `IDLE` only when no other
        make sheet on it remains in `SCHEDULED`, `IN_PROGRESS`, or
        `CURD_READY`; with a queue still active, the vat stays `BOOKED`."

        Design: Difficulty/non_linear_state_machine/additive_lot_depleted_released_cycle_via_refund
        """
        # volume 8000 with 5000 committed keeps the intake ACCEPTED (non-terminal)
        # at cancel time, so the PRD 3.3 milk un-commit applies unambiguously
        # (PRD 2.5 exempts terminal resources from compensating reversals).
        plant, vat, intake, culture, coagulant = _booking_base(
            "WI-105B", volume_liters=8000.0, culture_qty=10.0
        )
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            culture_units_planned=10.0, coagulant_ml_planned=250.0,
        )
        start_make(make["id"])
        committed = validate_success(api.get_milk_intake(intake["id"], RECEIVER))
        assert committed["consumed_liters"] == pytest.approx(5000.0)
        validate_success(api.cancel_make_sheet(make["id"], PLANNER))
        restored_intake = validate_success(api.get_milk_intake(intake["id"], RECEIVER))
        assert restored_intake["consumed_liters"] == pytest.approx(0.0), (
            "the cancel must reverse the milk commit"
        )
        vat_now = get_vat(vat["id"])
        assert vat_now["status"] == "IDLE", (
            f"with no active booking left the vat returns to IDLE, got {vat_now['status']}"
        )


class TestMakeStartGates:
    def test_make_start_gated_by_recalled_culture_lot(self, api):
        """PRD §3.1: "Recall does not auto-cancel make sheets that already
        reference the lot: such a make sheet stays `SCHEDULED` but will fail at
        start time with `ERR_ADDITIVE_LOT_UNUSABLE`, which is the intended
        cross-entity gate."

        Design: Difficulty/cross_entity_state_dependency/make_start_gated_by_additive_lot_and_intake_states
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-112")
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
        )
        validate_success(api.recall_additive_lot(culture["id"], QA))
        resp = api.start_make_sheet(make["id"], TEST_USERS["cheesemaker_headers"])
        validate_error(resp, ApiErrorId.ERR_ADDITIVE_LOT_UNUSABLE, 422)
        make_now = validate_success(api.get_make_sheet(make["id"], PLANNER))
        assert make_now["status"] == "SCHEDULED", "the make must stay SCHEDULED"
        culture_now = validate_success(api.get_additive_lot(culture["id"], QA))
        assert culture_now["quantity_on_hand"] == pytest.approx(100.0), (
            "a rejected start consumes nothing"
        )

    def test_make_start_gated_by_quarantined_lot(self, api):
        """PRD §3.4: "Both additive lots must be `RELEASED` with an
        `expires_at` strictly later than the current logical time — a lot
        quarantined, recalled, depleted, or expired (including expiry exactly
        at the current time) fails with `ERR_ADDITIVE_LOT_UNUSABLE`."

        Design: Difficulty/cross_entity_state_dependency/make_start_gated_by_additive_lot_and_intake_states
        """
        from test_helpers import create_additive_lot_payload

        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(license_number="WI-112B")
        vat = create_vat(plant["id"])
        intake = create_intake(plant["id"])
        # Only the coagulant is released; the culture lot stays QUARANTINE.
        culture_q = validate_success(
            api.create_additive_lot(
                plant["id"],
                create_additive_lot_payload(
                    kind="CULTURE", supplier_lot_no="CUL-Q", quantity_initial=100.0
                ),
                ADMIN,
            ),
            201,
        )
        _, coagulant = create_released_additive_pair(plant["id"])
        assert culture_q["status"] == "QUARANTINE"
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture_q["id"], coagulant["id"],
        )
        resp = api.start_make_sheet(make["id"], TEST_USERS["cheesemaker_headers"])
        validate_error(resp, ApiErrorId.ERR_ADDITIVE_LOT_UNUSABLE, 422)
        make_now = validate_success(api.get_make_sheet(make["id"], PLANNER))
        assert make_now["status"] == "SCHEDULED"

    def test_milk_shortfall_on_overcommit(self, api):
        """PRD §3.4: "The intake's unconsumed volume — its `volume_liters`
        minus its `consumed_liters` — must be at least `liters_committed`,
        failing `ERR_MILK_SHORTFALL`; an unconsumed volume exactly equal to the
        commitment passes."

        Design: Corner/validations/milk_shortfall_on_overcommit
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-233", volume_liters=8000.0)
        make1 = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            scheduled_start="2026-08-01T02:00:00Z", scheduled_end="2026-08-01T04:00:00Z",
        )
        start_make(make1["id"])
        vat_now = get_vat(vat["id"])
        make2 = create_make_sheet(
            vat["id"], vat_now["version"], intake["id"], culture["id"], coagulant["id"],
            scheduled_start="2026-08-01T06:00:00Z", scheduled_end="2026-08-01T08:00:00Z",
            liters_committed=4000.0,
        )
        resp = api.start_make_sheet(make2["id"], TEST_USERS["cheesemaker_headers"])
        validate_error(resp, ApiErrorId.ERR_MILK_SHORTFALL, 422)
        make2_now = validate_success(api.get_make_sheet(make2["id"], PLANNER))
        assert make2_now["status"] == "SCHEDULED", (
            "a start rejected for milk shortfall leaves the make SCHEDULED"
        )

    def test_additive_insufficient_at_start(self, api):
        """PRD §3.4: "Each lot's `quantity_on_hand` must be at least the
        planned draw, failing `ERR_ADDITIVE_INSUFFICIENT`; exact equality
        passes."

        Design: Corner/validations/additive_insufficient_at_start
        """
        plant, vat, intake, culture, coagulant = _booking_base("WI-234", culture_qty=10.0)
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"],
            culture_units_planned=50.0, coagulant_ml_planned=250.0,
        )
        resp = api.start_make_sheet(make["id"], TEST_USERS["cheesemaker_headers"])
        validate_error(resp, ApiErrorId.ERR_ADDITIVE_INSUFFICIENT, 422)
        culture_now = validate_success(api.get_additive_lot(culture["id"], QA))
        assert culture_now["quantity_on_hand"] == pytest.approx(10.0), (
            "a rejected start consumes nothing"
        )
