"""Interagency consultation: the closed occupied interval and the aggregate
capacity rule, the derived requirement set, the late response, and the two
refusals that guard who may open and who may answer.
"""
from test_helpers import (
    NEPA_COORDINATOR_HEADERS,
    POLICY_ADMIN_HEADERS,
    ApiErrorId,
    agency_payload,
    assert_consultation,
    assert_instant_equals,
    consultation_payload,
    consultation_response_payload,
    ec_finding,
    fixtures,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The two contrasting schedulers the design pins.
NOAA_PARAMETERS = {
    "agency_code": "NOAA",
    "name": "National Marine Fisheries Service",
    "agency_role": "BOTH",
    "max_concurrent_consultations": 2,
    "handoff_buffer_days": 3,
    "statutory_response_days": 135,
}
SHPO_PARAMETERS = {
    "agency_code": "SHPO",
    "name": "State Historic Preservation Office",
    "agency_role": "CONSULTING",
    "max_concurrent_consultations": 1,
    "handoff_buffer_days": 3,
    "statutory_response_days": 30,
}

#: A screen on an action with every sensitivity flag true, where each present
#: finding still sits below the office severity trigger threshold.
ALL_PRESENT_LOW_SEVERITY_FINDINGS = [
    ec_finding("EC_HISTORIC", True, 2, "Bridge abutment is a contributing element"),
    ec_finding("EC_ENDANGERED_SPECIES", True, 2,
               "Designated critical habitat downstream"),
    ec_finding("EC_WETLAND", True, 2, "Fringe wetland at the north abutment"),
]


class TestAgencyCapacityIntervals:
    """A consultation occupies a closed interval on its agency, extended by the
    handoff buffer, and the refusal is an aggregate-count rule."""

    def test_capacity_is_reached_by_a_count_of_colliding_intervals(self, client):
        """A second overlapping request still fits under a capacity of two, and
        the third — colliding with both — is refused.

        PRD 3.6: "The `statutory_due_at` is `requested_start_at` advanced by the
        agency's `statutory_response_days` whole days, and it is the inclusive end
        of the response obligation."
        PRD 3.6: "Capacity is enforced at creation under the closed-interval rule
        of §2.7: the candidate's occupied interval runs from `requested_start_at`
        through `statutory_due_at` advanced by the agency's `handoff_buffer_days`,
        both ends inclusive, and the candidate is rejected with
        `ERR_AGENCY_CAPACITY_EXCEEDED` when the number of the agency's `PENDING`
        consultations whose own occupied intervals share any instant with it — a
        shared endpoint counts — reaches or exceeds the agency's
        `max_concurrent_consultations`."

        Design: Difficulty/resource_temporal_overlap/consultation_closed_intervals_with_handoff_buffer_and_agency_capacity
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        noaa = fixtures.create_agency(**NOAA_PARAMETERS)

        first = fixtures.open_consultation(action_id, noaa["id"],
                                          consultation_type="ESA_SECTION_7",
                                          requested_start_at="2026-08-05T00:00:00Z")
        assert_instant_equals(first["statutory_due_at"], "2026-12-18T00:00:00Z",
                              "statutory_due_at 135 whole days after the start")
        assert first["status"] == "PENDING"
        assert_consultation(first)

        second = validate_success(
            client.create_consultation(
                consultation_payload(action_id, noaa["id"],
                                     consultation_type="CWA_SECTION_404",
                                     requested_start_at="2026-09-01T00:00:00Z"),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert_instant_equals(second["statutory_due_at"], "2027-01-14T00:00:00Z",
                              "statutory_due_at 135 whole days after 2026-09-01")

        refused = client.create_consultation(
            consultation_payload(action_id, noaa["id"],
                                 consultation_type="COOPERATING_AGENCY",
                                 requested_start_at="2026-10-01T00:00:00Z"),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.AGENCY_CAPACITY_EXCEEDED.value,
                       expected_status=409)

        assert fixtures.read_agency(noaa["id"])["active_consultation_count"] == 2, (
            "the refused request never became a pending row"
        )

    def test_a_start_on_the_buffered_end_instant_collides_but_the_next_day_does_not(
        self, client
    ):
        """Both ends of the occupied interval are inclusive, so a request starting
        exactly three days after the due date collides, and one day later does not.

        PRD 2.7: "A consultation, by contrast, occupies a closed interval on its
        agency that begins at `requested_start_at` and ends at `statutory_due_at`
        advanced by the agency's `handoff_buffer_days` whole days, with both ends
        inclusive."
        PRD 2.7: "A candidate consultation collides with an existing one when the
        two closed intervals share any instant at all, including a single shared
        endpoint; only rows whose `status` is `PENDING` on the same `agency_id`
        participate; and the rule is an aggregate-capacity rule rather than a
        pairwise one, so the candidate is rejected when the number of colliding
        pending rows reaches or exceeds the agency's
        `max_concurrent_consultations`."

        Design: Difficulty/resource_temporal_overlap/consultation_closed_intervals_with_handoff_buffer_and_agency_capacity
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        shpo = fixtures.create_agency(**SHPO_PARAMETERS)

        first = fixtures.open_consultation(action_id, shpo["id"],
                                          consultation_type="NHPA_SECTION_106",
                                          requested_start_at="2026-08-05T00:00:00Z")
        assert_instant_equals(first["statutory_due_at"], "2026-09-04T00:00:00Z",
                              "statutory_due_at 30 whole days after the start")

        on_the_endpoint = client.create_consultation(
            consultation_payload(action_id, shpo["id"],
                                 consultation_type="NHPA_SECTION_106",
                                 requested_start_at="2026-09-07T00:00:00Z"),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(on_the_endpoint, ApiErrorId.AGENCY_CAPACITY_EXCEEDED.value,
                       expected_status=409)

        after_the_endpoint = validate_success(
            client.create_consultation(
                consultation_payload(action_id, shpo["id"],
                                     consultation_type="NHPA_SECTION_106",
                                     requested_start_at="2026-09-08T00:00:00Z"),
                NEPA_COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        assert after_the_endpoint["status"] == "PENDING", (
            "the buffer extends the occupied interval by exactly three days, so "
            "the fourth day is free"
        )
        assert fixtures.read_agency(shpo["id"])["active_consultation_count"] == 2


class TestConsultationRequirementAndResponse:
    """`is_required` reads the action's flags, and the response fields move
    together."""

    def test_requirement_set_is_read_from_the_action_flags(self, client):
        """On an action with all four flags true the three statutory tracks are
        required and the cooperating track never is.

        PRD 3.6: "The boolean `is_required` records whether the action's own
        circumstances make this statutory track mandatory: `ESA_SECTION_7` is
        required when the action's `in_critical_habitat` is true;
        `NHPA_SECTION_106` is required when either `affects_historic_property` or
        `tribal_interest` is true; `CWA_SECTION_404` is required when
        `floodplain_or_wetland` is true; and `COOPERATING_AGENCY` is never a
        required track."
        PRD 3.6: "A request whose `consultation_type` is in the action's required
        set has `is_required` true, and any other request has it false."

        Design: Corner/calculations/corner_consultation_requirement_set_derived_from_action_flags
        """
        ctx = fixtures.setup_classified_action(
            action_overrides={
                "title": "River Crossing Replacement",
                "affects_historic_property": True,
                "tribal_interest": True,
                "floodplain_or_wetland": True,
            },
            screen_findings=ALL_PRESENT_LOW_SEVERITY_FINDINGS,
        )
        action_id = ctx["action"]["id"]
        epa = fixtures.create_agency(agency_code="EPA",
                                     name="Environmental Protection Agency",
                                     agency_role="BOTH",
                                     max_concurrent_consultations=5,
                                     handoff_buffer_days=3,
                                     statutory_response_days=135)

        requirement_by_type = {}
        for consultation_type in ("ESA_SECTION_7", "NHPA_SECTION_106",
                                  "CWA_SECTION_404", "COOPERATING_AGENCY"):
            created = validate_success(
                client.create_consultation(
                    consultation_payload(action_id, epa["id"],
                                        consultation_type=consultation_type,
                                        requested_start_at="2026-08-05T00:00:00Z"),
                    NEPA_COORDINATOR_HEADERS,
                ),
                expected_status=201,
            )
            requirement_by_type[consultation_type] = created
            assert created["status"] == "PENDING"
            assert_instant_equals(created["statutory_due_at"],
                                  "2026-12-18T00:00:00Z",
                                  f"{consultation_type} statutory_due_at")

        assert requirement_by_type["ESA_SECTION_7"]["is_required"] is True, (
            "the action lies in critical habitat"
        )
        assert requirement_by_type["NHPA_SECTION_106"]["is_required"] is True, (
            "the action affects a historic property and carries tribal interest"
        )
        assert requirement_by_type["CWA_SECTION_404"]["is_required"] is True, (
            "the action lies in a floodplain or wetland"
        )
        assert requirement_by_type["COOPERATING_AGENCY"]["is_required"] is False, (
            "the cooperating track is never mandatory"
        )
        assert fixtures.read_agency(epa["id"])["active_consultation_count"] == 4, (
            "a capacity of five accommodates all four pending requests"
        )

    def test_conditional_concurrence_after_the_due_date_is_recorded_as_late(
        self, client
    ):
        """The response stores its conditions, marks itself late, and frees the
        agency's capacity in one move.

        PRD 3.6: "`PENDING → CONCURRED` and `PENDING → NOT_CONCURRED` set
        `responded_at` to the current logical time and set `late` to true exactly
        when `responded_at` is strictly later than `statutory_due_at`."
        PRD 3.6: "`PENDING → CONDITIONAL_CONCURRENCE` does the same and
        additionally records the `conditions_text` supplied with the response,
        which must be present and non-empty for that outcome."

        Design: Corner/state_machines/corner_consultation_response_after_statutory_due_at_is_marked_late
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        shpo = fixtures.create_agency(**SHPO_PARAMETERS)
        consultation = fixtures.open_consultation(
            action_id, shpo["id"], consultation_type="NHPA_SECTION_106",
            requested_start_at="2026-08-05T00:00:00Z",
        )
        assert consultation["is_required"] is False, (
            "neither a historic property nor a tribal interest is recorded on the "
            "action"
        )

        fixtures.set_clock("2026-09-10T00:00:00Z")
        conditions = "Monitoring required during ground disturbance"
        responded = validate_success(
            client.respond_to_consultation(
                consultation["id"],
                consultation_response_payload("CONDITIONAL_CONCURRENCE",
                                              conditions_text=conditions),
                make_agency_liaison_headers(shpo["id"]),
            )
        )
        assert responded["status"] == "CONDITIONAL_CONCURRENCE"
        assert_instant_equals(responded["statutory_due_at"], "2026-09-04T00:00:00Z")
        assert_instant_equals(responded["responded_at"], "2026-09-10T00:00:00Z",
                              "responded_at is the current logical time")
        assert responded["late"] is True, (
            "the response landed strictly later than the statutory due instant"
        )
        assert responded["conditions_text"] == conditions
        assert fixtures.read_agency(shpo["id"])["active_consultation_count"] == 0, (
            "a terminal outcome releases the agency's pending slot"
        )


class TestConsultationAccessRules:
    """Who may be consulted, and who may answer."""

    def test_a_suspended_agency_cannot_receive_a_new_request(self, client):
        """Availability is settled before any interval arithmetic, so free
        capacity does not rescue a suspended agency.

        PRD 3.1: "An agency's `status` is `ACTIVE` or `SUSPENDED`, defaulting to
        `ACTIVE`; only an `ACTIVE` agency may receive new consultation requests."
        PRD 3.6: "Opening a consultation against an agency whose `status` is
        `SUSPENDED` is rejected with `ERR_AGENCY_SUSPENDED`."

        Design: Corner/errors/corner_error_agency_suspended_rejects_consultation_open
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        shpo = validate_success(
            client.create_agency(
                agency_payload(status="SUSPENDED", **SHPO_PARAMETERS),
                POLICY_ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert shpo["status"] == "SUSPENDED"

        refused = client.create_consultation(
            consultation_payload(action_id, shpo["id"],
                                 consultation_type="NHPA_SECTION_106",
                                 requested_start_at="2026-08-05T00:00:00Z"),
            NEPA_COORDINATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.AGENCY_SUSPENDED.value,
                       expected_status=409)

        assert fixtures.read_agency(shpo["id"])["active_consultation_count"] == 0
        _, meta = validate_paginated(
            client.list_consultations(NEPA_COORDINATOR_HEADERS,
                                      params={"action_id": action_id})
        )
        assert meta["total_count"] == 0, "no consultation row was created"

    def test_a_liaison_may_not_answer_another_agency_s_consultation(self, client):
        """The liaison's own identifier must match the consultation's agency, and
        the rightful liaison's identical call is accepted.

        PRD 3.6: "An `AgencyLiaison` supplies an `outcome` of `CONCURRED`,
        `CONDITIONAL_CONCURRENCE` or `NOT_CONCURRED`, and may only do so for a
        consultation whose `agency_id` equals its own `X-User-ID`."
        PRD 2.5: "Agency scoping, when an `AgencyLiaison` responds to a
        consultation — `ERR_AGENCY_SCOPE_VIOLATION`."

        Design: Corner/rbac/corner_agency_liaison_cannot_respond_for_another_agency
        """
        ctx = fixtures.setup_classified_action()
        action_id = ctx["action"]["id"]
        usfws = fixtures.create_agency(agency_code="USFWS",
                                       name="US Fish and Wildlife Service",
                                       agency_role="CONSULTING",
                                       max_concurrent_consultations=2,
                                       handoff_buffer_days=3,
                                       statutory_response_days=135)
        shpo = fixtures.create_agency(**SHPO_PARAMETERS)
        consultation = fixtures.open_consultation(action_id, usfws["id"])

        refused = client.respond_to_consultation(
            consultation["id"], consultation_response_payload("NOT_CONCURRED"),
            make_agency_liaison_headers(shpo["id"]),
        )
        validate_error(refused, ApiErrorId.AGENCY_SCOPE_VIOLATION.value,
                       expected_status=403)

        untouched = validate_success(
            client.get_consultation(consultation["id"], NEPA_COORDINATOR_HEADERS)
        )
        assert untouched["status"] == "PENDING"
        assert untouched["responded_at"] is None

        accepted = validate_success(
            client.respond_to_consultation(
                consultation["id"], consultation_response_payload("CONCURRED"),
                make_agency_liaison_headers(usfws["id"]),
            )
        )
        assert accepted["status"] == "CONCURRED"
        assert fixtures.read_agency(shpo["id"])["active_consultation_count"] == 0, (
            "the refused response left the other agency's ledger alone"
        )
