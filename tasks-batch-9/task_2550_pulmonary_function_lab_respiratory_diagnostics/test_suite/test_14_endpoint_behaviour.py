"""How four endpoints behave at their own edges rather than in the happy path.

A disinfection cycle is graded rather than merely recorded, a partial update
touches only what it names, a creating request resolves its body identifiers
left to right, and an action endpoint with a from-state is not idempotent.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DEVICE_NOT_AVAILABLE,
    ERR_DEVICE_NOT_FOUND,
    ERR_INFECTION_CONTROL_INCOMPLETE,
    ERR_ORDER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_device_cleared,
    assert_page,
    assert_version_is,
)
from test_helpers.constants import MORNING_CLOCK, UNKNOWN_UUID
from test_helpers.test_users import LAB_MANAGER

MORNING_SLOT = ("2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z")


def _device_awaiting_its_disinfection(api):
    """Calibrated, controlled and refiltered, but never yet disinfected."""
    fx.set_clock(api, MORNING_CLOCK)
    roster = fx.build_roster(api)
    fx.publish_reference_equation(api)
    device = fx.register_device(api)
    fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(), roster.tech1
    )
    fx.append_quality_event(
        api,
        device["id"],
        f.biologic_control_event_payload(roster.bcs_id),
        roster.tech1,
    )
    fx.append_quality_event(
        api, device["id"], f.filter_replacement_event_payload("F-1001"), roster.tech1
    )
    patient = fx.register_patient(api)
    order = fx.draft_and_submit_order(api, patient["id"], roster.doc1)
    return roster, device["id"], order


class TestDisinfectionDwellGrading:
    """Nineteen minutes in disinfectant is recorded, and worth nothing."""

    def test_a_short_dwell_is_stored_incomplete_and_leaves_the_gate_unsatisfied(self, api):
        """One further minute of dwell time unlocks the identical booking.

        PRD 3.3: "**High-level disinfection** carries `dwell_minutes`, the number
        of whole minutes the instrument sat in disinfectant. A dwell of at least
        20 minutes computes `outcome` `COMPLETE` with `failure_reason` null; a
        shorter dwell computes `outcome` `INCOMPLETE` with `failure_reason`
        `DWELL_TIME_SHORT`, and an incomplete disinfection is worth nothing to the
        protocol — the device stays `SOILED` and the disinfection must be repeated
        in full."

        PRD 3.5: "The infection-control pair must be satisfied: a filter
        replacement with `outcome` `COMPLETE` and a high-level disinfection with
        `outcome` `COMPLETE` both performed strictly after `last_session_end_at`,
        or, when `last_session_end_at` is null because the device has never been
        used, at any time since registration."

        Design: Corner/endpoints/high_level_disinfect_below_the_minimum_dwell_records_an_incomplete_cycle
        """
        roster, device_id, order = _device_awaiting_its_disinfection(api)
        start, end = MORNING_SLOT

        short = fx.append_quality_event(
            api, device_id, f.disinfection_event_payload(19), roster.tech1
        )
        assert short["outcome"] == "INCOMPLETE"
        assert short["failure_reason"] == "DWELL_TIME_SHORT"

        validate_error(
            api.create_test_session(
                f.test_session_payload(order["id"], device_id, start, end), roster.tech1
            ),
            ERR_INFECTION_CONTROL_INCOMPLETE,
        )

        complete = fx.append_quality_event(
            api, device_id, f.disinfection_event_payload(20), roster.tech1
        )
        assert complete["outcome"] == "COMPLETE"
        assert complete["failure_reason"] is None

        session = validate_success(
            api.create_test_session(
                f.test_session_payload(order["id"], device_id, start, end), roster.tech1
            ),
            expected_status=201,
        )
        assert session["session_status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api.list_quality_events(
                LAB_MANAGER, device_id=device_id, event_type="HIGH_LEVEL_DISINFECT"
            )
        )
        assert_page(meta, total_count=2, has_more=False)


class TestDraftOrderRevision:
    """A revision replaces what it names and leaves the rest of the row alone."""

    def test_a_two_field_revision_leaves_the_other_two_inputs_untouched(self, api):
        """The order stays a draft and its version moves by exactly one.

        PRD 3.4: "While the order is a draft the physician who owns it may revise
        `indication_code`, `requested_modalities`, `bronchodilator_requested` and
        `challenge_type`, supplying any subset of the four; supplied fields
        replace their stored values and omitted fields are left untouched."

        PRD 2.5: "**`version`** (integer): starts at 1 on creation and increments
        by exactly 1 on every mutation, again including server-initiated ones."

        Design: Corner/endpoints/patch_on_a_draft_order_updates_only_the_supplied_fields
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)
        patient = fx.register_patient(api)
        order = fx.draft_order(api, patient["id"], roster.doc1)
        assert order["indication_code"] == "DYSPNEA_EVALUATION"
        assert order["requested_modalities"] == ["SPIROMETRY"]
        assert order["bronchodilator_requested"] is False
        assert order["challenge_type"] == "NONE"

        revised = validate_success(
            api.patch_test_order(
                order["id"],
                {"indication_code": "COPD_STAGING", "bronchodilator_requested": True},
                roster.doc1,
            )
        )
        assert revised["indication_code"] == "COPD_STAGING"
        assert revised["bronchodilator_requested"] is True
        assert revised["requested_modalities"] == ["SPIROMETRY"]
        assert revised["challenge_type"] == "NONE"
        assert revised["status"] == "DRAFT"
        assert_version_is(revised, 2)

        reread = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert reread["indication_code"] == "COPD_STAGING"
        assert reread["bronchodilator_requested"] is True
        assert reread["requested_modalities"] == ["SPIROMETRY"]
        assert reread["challenge_type"] == "NONE"
        assert reread["status"] == "DRAFT"
        assert_version_is(reread, 2)


class TestSessionBodyIdentifierOrder:
    """Both identifiers are unknown, so which code comes back is the whole test."""

    def test_the_order_identifier_is_resolved_before_the_device_identifier(self, api):
        """A request naming two unknown rows reports the order, not the device.

        PRD 2.9: "Identifiers arriving in the **request body** are resolved after
        path identifiers, and among themselves in the fixed left-to-right order in
        which they are declared for that operation: `patient_id`, then `order_id`,
        then `device_id`, then `rescue_lot_id`, then `subject_staff_id`. Each
        resolves to its own not-found code: `ERR_PATIENT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_LOT_NOT_FOUND` and
        `ERR_STAFF_NOT_FOUND` respectively, all HTTP 404."

        Design: Corner/endpoints/session_creation_resolves_the_order_before_the_device
        """
        lab = fx.build_lab(api)
        order = fx.build_ready_order(api, lab)
        start, end = MORNING_SLOT

        validate_error(
            api.create_test_session(
                f.test_session_payload(UNKNOWN_UUID, lab.device_id, start, end),
                lab.tech1,
            ),
            ERR_ORDER_NOT_FOUND,
        )
        validate_error(
            api.create_test_session(
                f.test_session_payload(order["id"], UNKNOWN_UUID, start, end),
                lab.tech1,
            ),
            ERR_DEVICE_NOT_FOUND,
        )
        validate_error(
            api.create_test_session(
                f.test_session_payload(UNKNOWN_UUID, UNKNOWN_UUID, start, end),
                lab.tech1,
            ),
            ERR_ORDER_NOT_FOUND,
        )

        session = validate_success(
            api.create_test_session(
                f.test_session_payload(order["id"], lab.device_id, start, end),
                lab.tech1,
            ),
            expected_status=201,
        )
        assert session["order_id"] == order["id"]
        assert session["device_id"] == lab.device_id


def _quarantined_device_with_independent_clearance(api):
    """A device condemned by T-001 and re-measured by T-002 an hour later."""
    fx.set_clock(api, MORNING_CLOCK)
    roster = fx.build_roster(api, second_technologist=True)
    device = fx.register_device(api)
    fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(), roster.tech1
    )
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(2.848), roster.tech1
    )
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(), roster.tech2
    )
    fx.append_quality_event(
        api,
        device["id"],
        f.biologic_control_event_payload(roster.bcs_id),
        roster.tech2,
    )
    fx.append_quality_event(
        api, device["id"], f.filter_replacement_event_payload("F-1002"), roster.tech2
    )
    fx.append_quality_event(
        api, device["id"], f.disinfection_event_payload(), roster.tech2
    )
    return roster, device["id"]


class TestReturnToServiceFromState:
    """Return-to-service has a from-state, so calling it twice is not the same."""

    def test_the_second_return_to_service_is_refused_and_moves_no_version(self, api):
        """The first call clears three fields at once; the second finds nothing to clear.

        PRD 3.3: "A quarantined device is out of the laboratory's hands until a
        `LabManager` explicitly returns it to service, supplying a
        `clearance_note` that records the engineering or clinical judgement behind
        the decision. Four conditions must all hold, and the endpoint refuses a
        device whose `status` is anything other than `QUARANTINED` with
        `ERR_DEVICE_NOT_AVAILABLE`."

        PRD 3.3: "When all four hold, the `status` returns to `AVAILABLE` and
        `quarantined_at`, `quarantine_reason` and `quarantine_trigger_staff_id`
        are all cleared to null. Failing any of the evidence conditions reports
        `ERR_QUARANTINE_CLEARANCE_INCOMPLETE`. Requests that satisfy every gate
        leave the device's `version` one higher than before."

        Design: Corner/endpoints/return_to_service_is_refused_once_the_device_is_already_available
        """
        _, device_id = _quarantined_device_with_independent_clearance(api)

        quarantined = validate_success(api.get_device(device_id, LAB_MANAGER))
        assert quarantined["status"] == "QUARANTINED"

        cleared = validate_success(
            api.return_device_to_service(
                device_id, f.return_to_service_payload(), LAB_MANAGER
            )
        )
        assert_device_cleared(cleared)
        assert_version_is(cleared, quarantined["version"] + 1)

        validate_error(
            api.return_device_to_service(
                device_id, f.return_to_service_payload(), LAB_MANAGER
            ),
            ERR_DEVICE_NOT_AVAILABLE,
        )

        final = validate_success(api.get_device(device_id, LAB_MANAGER))
        assert_device_cleared(final)
        assert_version_is(final, cleared["version"])
