"""Preemption interconnection timing check, commissioning gates, and the
one-open-interconnection rule (PRD §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_preemption_interconnection,
    create_locality,
    create_preemption_interconnection_payload,
    get_success_data,
    setup_locality_and_crossing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestTimingCheckBoundary:
    def test_equality_passes_and_derived_fields_computed(self, api, admin_headers):
        """PRD §3.8: "The `approach_seconds` is the approach distance divided by
        the design train speed converted to feet per second — at 1.46667 feet per
        second per mile per hour — rounded up to the next whole second. The
        `required_clearance_green_seconds` is the clear storage distance divided
        by a clearance speed of 15.0 feet per second, rounded up to the next whole
        second. The `required_advance_preemption_seconds` is the required
        clearance green plus a 5-second preemption buffer minus a 10-second
        overlap allowance, floored at zero." and "All three comparisons admit
        equality — meeting a requirement exactly passes. When all three hold,
        `timing_check_pass` is set to `true` and the design is verified".

        Design: Corner/endpoints/preemption_timing_boundary_pass_and_fail
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-050001"}
        )
        resp = api.create_preemption_interconnection(
            create_preemption_interconnection_payload(
                crossing_id=crossing["id"],
                traffic_signal_ref="SIG-100",
                track_approach_distance_ft=1500,
                design_train_speed_mph=40,
                clear_storage_distance_ft=75,
                advance_preemption_seconds=0,
                track_clearance_green_seconds=5,
            ),
            admin_headers,
        )
        ic = validate_success(resp, expected_status=201)
        assert_preemption_interconnection(ic)
        # ceil(1500 / (40 * 1.46667)) = ceil(25.57...) = 26
        assert ic["approach_seconds"] == 26
        # ceil(75 / 15.0) = 5
        assert ic["required_clearance_green_seconds"] == 5
        # max(0, 5 + 5 - 10) = 0
        assert ic["required_advance_preemption_seconds"] == 0
        assert ic["status"] == "DRAFT"

        verified = get_success_data(
            api.transition_preemption_interconnection(
                ic["id"], {"to_status": "TIMING_VERIFIED"}, OFFICER
            )
        )
        assert verified["status"] == "TIMING_VERIFIED"
        assert verified["timing_check_pass"] is True, (
            "approach 26 >= 20, green 5 >= 5, advance 0 >= 0 — equality passes"
        )

    def test_green_one_second_below_required_fails_and_stays_draft(
        self, api, admin_headers
    ):
        """PRD §3.8: "when any fails, the request is rejected with
        `ERR_PREEMPTION_TIMING_INADEQUATE` and the design stays `DRAFT`."

        Design: Corner/endpoints/preemption_timing_boundary_pass_and_fail
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-050002"}
        )
        ic = get_success_data(
            api.create_preemption_interconnection(
                create_preemption_interconnection_payload(
                    crossing_id=crossing["id"],
                    traffic_signal_ref="SIG-200",
                    track_approach_distance_ft=1500,
                    design_train_speed_mph=40,
                    clear_storage_distance_ft=75,
                    advance_preemption_seconds=0,
                    track_clearance_green_seconds=4,  # required is 5
                ),
                admin_headers,
            )
        )
        resp = api.transition_preemption_interconnection(
            ic["id"], {"to_status": "TIMING_VERIFIED"}, OFFICER
        )
        validate_error(
            resp, ApiErrorId.ERR_PREEMPTION_TIMING_INADEQUATE, expected_status=422
        )
        after = get_success_data(api.get_preemption_interconnection(ic["id"], ADMIN))
        assert after["status"] == "DRAFT"

    def test_second_open_interconnection_on_same_crossing_rejected(
        self, api, admin_headers
    ):
        """PRD §3.8: "A crossing may have at most one interconnection that is not
        `DECOMMISSIONED` — a second registration is rejected with
        `ERR_ACTIVE_INTERCONNECTION_EXISTS`".

        Design: Corner/endpoints/preemption_timing_boundary_pass_and_fail
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-050003"}
        )
        get_success_data(
            api.create_preemption_interconnection(
                create_preemption_interconnection_payload(
                    crossing_id=crossing["id"], traffic_signal_ref="SIG-100"
                ),
                admin_headers,
            )
        )
        resp = api.create_preemption_interconnection(
            create_preemption_interconnection_payload(
                crossing_id=crossing["id"], traffic_signal_ref="SIG-101"
            ),
            admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_ACTIVE_INTERCONNECTION_EXISTS, expected_status=409
        )


class TestCommissionRequiresGates:
    def test_flashing_lights_rejected_then_gates_commission_succeeds(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.8: "Commissioning puts the design into service: a
        `RailSafetyOfficer` moves `TIMING_VERIFIED` → `COMMISSIONED`, which
        requires the crossing still `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`) and
        equipped with gates — the crossing's `warning_device_class` must be
        `GATES` or `FOUR_QUADRANT_GATES`, since preemption without a gate
        mechanism is not permitted (else `ERR_PREEMPTION_REQUIRES_GATES`)."

        Design: Corner/endpoints/preemption_commission_requires_gates
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-050011",
                "warning_device_class": "FLASHING_LIGHTS",
            }
        )
        ic = get_success_data(
            api.create_preemption_interconnection(
                create_preemption_interconnection_payload(
                    crossing_id=crossing["id"], traffic_signal_ref="SIG-300"
                ),
                admin_headers,
            )
        )
        get_success_data(
            api.transition_preemption_interconnection(
                ic["id"], {"to_status": "TIMING_VERIFIED"}, officer_headers
            )
        )

        resp = api.transition_preemption_interconnection(
            ic["id"], {"to_status": "COMMISSIONED"}, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_PREEMPTION_REQUIRES_GATES, expected_status=409)

        # OCC-guarded inventory patch upgrades the device class to GATES.
        patched = get_success_data(
            api.patch_crossing_inventory(
                crossing["id"],
                {
                    "expected_crossing_version": crossing["version"],
                    "warning_device_class": "GATES",
                },
                admin_headers,
            )
        )
        assert patched["warning_device_class"] == "GATES"

        commissioned = get_success_data(
            api.transition_preemption_interconnection(
                ic["id"], {"to_status": "COMMISSIONED"}, officer_headers
            )
        )
        assert commissioned["status"] == "COMMISSIONED"

    def test_four_quadrant_gates_also_satisfy_commission_gate(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.8: "the crossing's `warning_device_class` must be `GATES` or
        `FOUR_QUADRANT_GATES`, since preemption without a gate mechanism is not
        permitted (else `ERR_PREEMPTION_REQUIRES_GATES`)."

        Design: Corner/endpoints/preemption_commission_requires_gates
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-050012",
                "warning_device_class": "FOUR_QUADRANT_GATES",
            }
        )
        ic = get_success_data(
            api.create_preemption_interconnection(
                create_preemption_interconnection_payload(
                    crossing_id=crossing["id"], traffic_signal_ref="SIG-301"
                ),
                admin_headers,
            )
        )
        get_success_data(
            api.transition_preemption_interconnection(
                ic["id"], {"to_status": "TIMING_VERIFIED"}, officer_headers
            )
        )
        commissioned = get_success_data(
            api.transition_preemption_interconnection(
                ic["id"], {"to_status": "COMMISSIONED"}, officer_headers
            )
        )
        assert commissioned["status"] == "COMMISSIONED"
