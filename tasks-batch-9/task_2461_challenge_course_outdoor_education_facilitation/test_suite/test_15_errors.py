"""Declared error identifiers that need a reachable trigger of their own."""

from test_helpers import (
    ERR_ELEMENT_NOT_RESTRICTED,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_UTC, ELEMENT_NAME_LOW
from test_helpers.fixtures import (
    create_course,
    create_element,
    create_safety_officer,
    set_clock,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_safety_officer_headers


class TestReturnToServiceNeedsSomethingToRestore:
    """The countersignature has no meaning on an element that was never taken out."""

    def test_returning_a_serviceable_element_to_service_is_refused(self, api):
        """Nothing is restricted, so the state precondition of the transition fails.

        PRD 3.3: "Attempting it on an element that is already `SERVICEABLE` is
        refused with `ERR_ELEMENT_NOT_RESTRICTED`."

        PRD 2.12: "State precondition for the requested transition — one of
        `ERR_ELEMENT_NOT_RESTRICTED`, `ERR_ELEMENT_NOT_SERVICEABLE`,
        `ERR_ELEMENT_RETIRED`, `ERR_INSPECTION_NOT_DRAFT`,
        `ERR_INSPECTION_NOT_FILED`, `ERR_BOOKING_NOT_QUOTABLE`,
        `ERR_BOOKING_NOT_CONFIRMABLE`, `ERR_BOOKING_NOT_CONFIRMED`,
        `ERR_BOOKING_ALREADY_TERMINAL`, `ERR_BLOCK_NOT_SCHEDULED`,
        `ERR_BLOCK_NOT_IN_PROGRESS`, `ERR_INCIDENT_NOT_REPORTED`,
        `ERR_INCIDENT_NOT_UNDER_REVIEW`, `ERR_EQUIPMENT_RETIRED` or
        `ERR_INVALID_STATE`, all HTTP 409."

        PRD 3.3: "Returning an element to service is the `SafetyOfficer`'s
        countersignature on somebody else's defect, and it carries a `note`."

        Design: Corner/errors/return_to_service_on_a_serviceable_element_rejected
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)

        validate_error(
            api.return_element_to_service(
                l_id, {"note": "Nothing to restore"}, make_safety_officer_headers(so_id)
            ),
            ERR_ELEMENT_NOT_RESTRICTED,
            409,
        )

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["status"] == "SERVICEABLE"
        assert element["restricting_log_id"] is None

        course = validate_success(api.get_course(course_id, PROGRAM_DIRECTOR))
        assert course["restricted_element_count"] == 0
