"""Derived values are recomputed inside the write, not behind it."""

from test_helpers import validate_success
from test_helpers.constants import CLOCK_TEST_UTC
from test_helpers.fixtures import (
    add_participant,
    create_booking,
    create_funded_client,
    set_clock,
    staffed_course,
    submit_packet,
)
from test_helpers.test_users import PROGRAM_DIRECTOR

CLEARANCE_NOTE = "Cardiology clearance letter on file"
DECLARED_FLAGS = ["ASTHMA", "CARDIAC"]


class TestClearanceResponseCarriesTheRecomputedStatus:
    """The clearance response body already shows the screening verdict it caused."""

    def test_the_clearance_body_reads_eligible_and_the_booking_reads_ready(self, api):
        """One blocking flag among two is lifted, and both dimensions settle in the same call.

        PRD 3.6: "Four of those flags are blocking — `CARDIAC`, `SEIZURE`,
        `PREGNANCY` and `RECENT_SURGERY` — and a packet whose flags intersect that
        set moves the participant `MISSING → FLAGGED`; a packet with no blocking flag
        moves it `MISSING → SUBMITTED`."

        PRD 3.6: "The transition `FLAGGED → CLEARED` sets
        `medical_clearance_granted` true."

        PRD 3.6: "`screening_status` is derived after every one of those writes by an
        ordered first-match walk in which the blocked outcome outranks the
        conditional one."

        PRD 3.6: "`roster_status` is the booking's second, independent state
        dimension, and it is re-derived from the whole roster after every participant
        write by another ordered walk."

        Design: Corner/consistency_model/medical_clearance_response_body_shows_the_recomputed_screening_status
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
        p1_id = add_participant(api, gc_id, b_id, "ADULT", screen=False)

        flagged = submit_packet(api, gc_id, p1_id, health_flags=DECLARED_FLAGS)
        assert flagged["health_form_status"] == "FLAGGED"
        assert flagged["screening_status"] == "CONDITIONAL"
        assert flagged["health_flags"] == DECLARED_FLAGS

        cleared = validate_success(
            api.grant_medical_clearance(
                p1_id, {"clearance_note": CLEARANCE_NOTE}, world["so_headers"]
            )
        )

        assert cleared["health_form_status"] == "CLEARED"
        assert cleared["medical_clearance_granted"] is True
        assert cleared["screening_status"] == "ELIGIBLE"

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["roster_status"] == "READY"
