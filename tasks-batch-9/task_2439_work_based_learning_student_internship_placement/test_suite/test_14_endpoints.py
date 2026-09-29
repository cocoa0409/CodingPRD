"""Endpoint coverage on the three shapes a collection or single-row read can
take: the stored worksite row read back by a reviewer, the supervisor that
appears under its parent worksite on the very next read, and the page-size
argument that is outside its declared band.
"""

from test_helpers import (
    COORDINATOR,
    REVIEWER,
    ApiErrorId,
    api_client,
    create_supervisor_payload,
    create_worksite_payload,
    get_success_data,
    recruit_employer_partner,
    register_worksite,
    set_clock,
    validate_error,
    validate_success,
)

HARBORVIEW_MARINA = {
    "legal_name": "Harborview Marina",
    "naics_code": "713930",
    "industry_sector": "HOSPITALITY",
    "workers_comp_policy_no": "WC-10181",
}
IVY_COURT_DENTAL = {
    "legal_name": "Ivy Court Dental",
    "naics_code": "621210",
    "industry_sector": "HEALTHCARE",
    "workers_comp_policy_no": "WC-10191",
}
KILNBROOK_CERAMICS = {
    "legal_name": "Kilnbrook Ceramics",
    "naics_code": "327110",
    "industry_sector": "MANUFACTURING",
    "workers_comp_policy_no": "WC-10201",
}


class TestWorksiteReadBackAfterRegistration:
    def test_a_reviewer_reads_the_stored_row_with_its_counters_still_at_zero(self):
        """A freshly registered worksite has `safety_status` of `UNREVIEWED`,
        `slots_committed` of 0, and both `safety_review_expires_on` and
        `corrective_actions_due_on` null. `has_power_machinery` records whether power-driven
        machinery is operated there and defaults to false.

        Design: Corner/endpoints/worksite_get_returns_the_stored_row_with_zeroed_counters
        """
        set_clock("2026-09-01T08:00:00Z")
        partner = recruit_employer_partner(**HARBORVIEW_MARINA)
        registered = validate_success(
            api_client.create_worksite(
                create_worksite_payload(
                    partner["id"],
                    site_name="Harborview Boat Shed",
                    address_line="1 Harborview Pier",
                    hazard_class="LIMITED_HAZARD",
                    has_power_machinery=True,
                    max_concurrent_students=3,
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        worksite = validate_success(
            api_client.get_worksite(registered["id"], REVIEWER)
        )

        assert worksite["id"] == registered["id"]
        assert worksite["employer_partner_id"] == partner["id"]
        assert worksite["site_name"] == "Harborview Boat Shed"
        assert worksite["hazard_class"] == "LIMITED_HAZARD"
        assert worksite["has_power_machinery"] is True
        assert worksite["max_concurrent_students"] == 3
        assert worksite["safety_status"] == "UNREVIEWED"
        assert worksite["safety_review_expires_on"] is None
        assert worksite["corrective_actions_due_on"] is None
        assert worksite["slots_committed"] == 0
        assert worksite["version"] == 1


class TestSupervisorRegistrationUnderAWorksite:
    def test_a_new_supervisor_is_listed_under_its_worksite_with_no_load(self):
        """Supervisors are registered against a worksite by naming its `worksite_id` and
        supplying `full_name`, `email`, `training_completed_on` — the `YYYY-MM-DD` date the
        supervisor finished district mentor training, valid for 365 days from that date — and
        `max_student_load`, at least 1. A new supervisor starts with `active_student_load` of
        0.

        Design: Corner/endpoints/supervisor_create_links_the_supervisor_to_its_worksite
        """
        set_clock("2026-09-01T08:00:00Z")
        partner = recruit_employer_partner(**IVY_COURT_DENTAL)
        worksite = register_worksite(
            partner["id"],
            site_name="Ivy Court Front Office",
            address_line="9 Ivy Court",
            max_concurrent_students=2,
        )

        supervisor = validate_success(
            api_client.create_supervisor(
                create_supervisor_payload(
                    worksite["id"],
                    full_name="Jo Villanueva",
                    email="jo@ivycourt.example",
                    training_completed_on="2026-07-01",
                    max_student_load=2,
                ),
                COORDINATOR,
            ),
            expected_status=201,
        )

        assert supervisor["worksite_id"] == worksite["id"]
        assert supervisor["active_student_load"] == 0
        assert supervisor["max_student_load"] == 2

        listed = get_success_data(
            api_client.list_worksite_supervisors(worksite["id"], COORDINATOR)
        )
        assert len(listed) == 1
        assert listed[0]["id"] == supervisor["id"]


class TestPageSizeOutsideTheAcceptedBand:
    def test_asking_for_a_hundred_and_one_rows_is_a_malformed_request(self):
        """`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and
        its maximum is 100. A `limit` below 1 or above 100 is a malformed request and is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/endpoints/employer_partner_list_with_limit_over_the_maximum_rejected
        """
        set_clock("2026-09-01T08:00:00Z")
        recruit_employer_partner(**KILNBROOK_CERAMICS)

        response = api_client.list_employer_partners(
            COORDINATOR, {"limit": 101, "offset": 0}
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert response.status_code == 400
