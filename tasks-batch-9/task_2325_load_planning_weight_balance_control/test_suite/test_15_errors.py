"""The failure envelope and the single shape code that covers every malformation."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ADMIN, RAMP_AGENT, api_client
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx


class TestUniformFailureEnvelope:
    def test_a_role_refusal_and_a_missing_row_answer_in_the_same_shape(self):
        """Two failures raised at different ladder rungs share one envelope.

        PRD: "The `meta` object for error responses contains only `api_request_id`
        and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_is_uniform_across_unauthorized_and_not_found
        """
        aircraft = fx.create_aircraft("HB-AAA")

        refused = api_client.ground_aircraft(str(aircraft["id"]), RAMP_AGENT)
        missing = api_client.get_aircraft(
            "00000000-0000-0000-0000-0000000000a1", RAMP_AGENT
        )

        assert refused.status_code == 403, (
            f"an unauthorised role should be refused with 403 but got {refused.status_code}"
        )
        A.assert_error_envelope(refused.json(), E.UNAUTHORIZED.value)
        assert missing.status_code == 404, (
            f"an unknown airframe should be reported with 404 but got {missing.status_code}"
        )
        A.assert_error_envelope(missing.json(), E.AIRCRAFT_NOT_FOUND.value)
        current = api_client.get_aircraft(str(aircraft["id"]), RAMP_AGENT).json()
        A.assert_object_envelope(current)
        assert current["data"]["status"] == "IN_SERVICE", (
            "neither failure should have changed the airframe's posture"
        )


class TestInvalidRequestVarieties:
    def test_five_kinds_of_malformation_all_report_the_one_shape_code(self):
        """Five varieties of malformation, one code, and nothing persisted.

        PRD: "Request shape — every required input field present, every enum value a
        declared member, every weight, length and count field at least 0, with
        consignment `weight_kg` and compartment `length_m` required to be strictly
        greater than 0, and `limit` within 1 through 100 with `offset` at least 0 on
        list endpoints; otherwise `ERR_INVALID_REQUEST`, 400."

        Design: Corner/errors/invalid_request_is_raised_for_shape_enum_and_range_faults
        """
        fx.position_clock()
        aircraft = fx.create_aircraft("HB-AAA")
        runway = fx.create_runway()
        aircraft_id = str(aircraft["id"])
        runway_id = str(runway["id"])
        without_ceiling = F.compartment_payload(
            aircraft_id, "OC", "CABIN_ZONE", 22.900, 8000, 2000, 8.0, seat_capacity=60
        )
        without_ceiling.pop("max_weight_kg")

        probes = [
            api_client.create_compartment(without_ceiling, ADMIN),
            api_client.create_compartment(
                F.compartment_payload(aircraft_id, "OD", "GALLEY", 22.900, 8000, 2000, 8.0),
                ADMIN,
            ),
            api_client.create_performance_band(
                F.performance_band_payload(runway_id, "cold", 15, 79000), ADMIN
            ),
            api_client.create_weight_program(
                F.weight_program_payload(code="NEG-1", male_kg=-88.0), ADMIN
            ),
            api_client.set_clock_raw({"to_iso8601": "the fifteenth of August"}, ADMIN),
        ]

        for response in probes:
            validate_error(response, E.INVALID_REQUEST, 400)
        rows, meta = validate_paginated(
            api_client.list_aircraft_compartments(aircraft_id, ADMIN)
        )
        A.assert_pagination_meta(meta, total_count=0)
        rows, meta = validate_paginated(
            api_client.list_runway_performance_bands(runway_id, ADMIN)
        )
        A.assert_pagination_meta(meta, total_count=0)
