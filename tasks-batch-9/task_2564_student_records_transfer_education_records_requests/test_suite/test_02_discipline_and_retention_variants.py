"""Two calculations that each run twice over one input set.

The discipline-inclusion function is applied once with the responding state's
rule and once with the requesting state's rule; the retention eligibility date
is computed once from the exit anchor and once from the latest activity.
"""
from test_helpers import (
    api_client,
    assert_discipline_incident,
    assert_incident_counts_partition,
    assert_records_request,
    assert_retention_schedule,
    create_district,
    create_incidents,
    create_records_request,
    create_state_rule,
    create_student,
    create_withdrawal,
    complete_withdrawal,
    directory_disclosure_payload,
    get_cumulative_file_id,
    get_retention_schedules,
    make_compliance_officer_headers,
    make_records_clerk_headers,
    make_records_officer_headers,
    mark_ready_request,
    set_clock,
    setup_transfer_scenario,
    validate_request,
    validate_success,
)

CLERK = make_records_clerk_headers()
OFFICER = make_records_officer_headers("officer-1")
COMPLIANCE = make_compliance_officer_headers()

FIVE_INCIDENTS = [
    {
        "incident_date": "2026-03-02",
        "action_type": "SUSPENSION",
        "days_removed": 12,
        "incident_status": "SUSTAINED",
        "adjudicated_by_court": False,
        "description": "Long suspension, sustained",
    },
    {
        "incident_date": "2026-03-09",
        "action_type": "SUSPENSION",
        "days_removed": 3,
        "incident_status": "SUSTAINED",
        "adjudicated_by_court": False,
        "description": "Short suspension, sustained",
    },
    {
        "incident_date": "2026-04-06",
        "action_type": "EXPULSION",
        "days_removed": 30,
        "incident_status": "PENDING_INVESTIGATION",
        "adjudicated_by_court": False,
        "description": "Expulsion under investigation",
    },
    {
        "incident_date": "2026-04-20",
        "action_type": "DETENTION",
        "days_removed": 0,
        "incident_status": "SUSTAINED",
        "adjudicated_by_court": False,
        "description": "Lunch detention",
    },
    {
        "incident_date": "2026-05-11",
        "action_type": "SUSPENSION",
        "days_removed": 20,
        "incident_status": "DISMISSED",
        "adjudicated_by_court": False,
        "description": "Suspension later dismissed",
    },
]


def _snapshot_across_two_states():
    """CA responds and governs; TX requests and is advisory only. The same five
    incidents are evaluated by both rules at the moment the packet is taken."""
    scenario = setup_transfer_scenario(
        responding_state="CA",
        requesting_state="TX",
        student_overrides={
            "first_name": "Ada",
            "last_name": "Nguyen",
            "dob": "2012-03-04",
            "grade_level": 8,
            "guardian_user_id": "guardian-ada",
        },
        pages={"ACADEMIC": 120, "HEALTH": 34, "DISCIPLINE": 18},
        redactions={"HEALTH": 4, "DISCIPLINE": 2},
        certify=("ACADEMIC", "HEALTH", "DISCIPLINE"),
        file_request=False,
    )
    incidents = create_incidents(scenario["student"]["id"], FIVE_INCIDENTS)
    request = create_records_request(
        scenario["student"]["id"],
        scenario["requesting_district"]["id"],
        scenario["responding_district"]["id"],
        headers=scenario["registrar_headers"],
        request_priority="STANDARD",
        includes_special_education=False,
        sped_consent_on_file=False,
        authorization_reference="ENR-2026-0001",
    )
    validate_request(request["id"])
    marked = mark_ready_request(request["id"], scenario["file_id"])
    scenario["incidents"] = incidents
    scenario["request"] = marked
    return scenario


class TestDisciplineInclusionAcrossStates:
    def test_governing_and_advisory_counts_diverge_on_identical_incidents(self):
        """CA's SUSPENSIONS_AND_EXPULSIONS rule with pending investigations
        excluded includes one of five incidents, while TX's ALL_INCIDENTS rule
        with pending investigations allowed would have taken four.

        PRD: "The **advisory pass** applies the state rule of the requesting district — the receiving district — to the very same incident set and writes only the request's `receiving_state_inclusion_count`."

        Design: Difficulty/dual_variant_calc/discipline_inclusion_responding_vs_requesting_state
        """
        scenario = _snapshot_across_two_states()
        data = scenario["request"]

        assert_records_request(data)
        assert data["status"] == "READY_FOR_RELEASE"
        assert data["packet_status"] == "SNAPSHOT"
        assert data["included_incident_count"] == 1
        assert data["withheld_incident_count"] == 4
        assert data["receiving_state_inclusion_count"] == 4
        assert data["included_incident_count"] != data["receiving_state_inclusion_count"]
        assert_incident_counts_partition(data, 5)
        assert data["packet_page_count"] == 166

    def test_only_the_governing_pass_stamps_the_incidents(self):
        """The twelve-day suspension clears CA's ten-day threshold and is stamped
        INCLUDED; the three-day suspension, the pending expulsion and the
        dismissed suspension are all stamped WITHHELD.

        PRD: "The **governing pass** applies the state rule of the responding district, the district that owns the record, and it is the only pass that writes anything to the incidents themselves: each incident's `transfer_inclusion_state` becomes `INCLUDED` or `WITHHELD` accordingly, the request's `included_incident_count` becomes the number of included incidents, and its `withheld_incident_count` becomes the total number of the student's incidents minus that count, so the two always sum to the student's incident count."

        Design: Difficulty/dual_variant_calc/discipline_inclusion_responding_vs_requesting_state
        """
        scenario = _snapshot_across_two_states()
        susp12, susp3, pending_expulsion, detention, dismissed = scenario["incidents"]

        expected = {
            susp12["id"]: "INCLUDED",
            susp3["id"]: "WITHHELD",
            pending_expulsion["id"]: "WITHHELD",
            detention["id"]: "WITHHELD",
            dismissed["id"]: "WITHHELD",
        }
        for incident_id, state in expected.items():
            data = validate_success(
                api_client.get_discipline_incident(incident_id, OFFICER)
            )
            assert_discipline_incident(data)
            assert data["transfer_inclusion_state"] == state, (
                f"incident {incident_id} should be {state}"
            )


class TestRetentionAnchors:
    def test_advisory_date_freezes_at_the_exit_anchor(self):
        """exit_anchored_eligible_at is the exit anchor advanced by five whole
        years and ignores the later directory disclosure entirely.

        PRD: "The advisory date, `exit_anchored_eligible_at`, is `exit_anchor_at` advanced by the same number of whole years."

        Design: Difficulty/dual_variant_calc/retention_last_activity_vs_exit_anchor
        """
        schedule_id, _student_id = _withdrawn_student_with_one_disclosure()

        data = validate_success(api_client.get_retention_schedule(schedule_id, COMPLIANCE))

        assert_retention_schedule(data)
        assert data["exit_anchor_at"] == "2026-08-14T00:00:00.000Z"
        assert data["exit_anchored_eligible_at"] == "2031-08-14T00:00:00.000Z"
        assert data["status"] == "ACTIVE"

    def test_governing_date_advances_with_the_latest_disclosure(self):
        """A single directory disclosure logged on 2026-09-10 pulls
        last_activity_at forward and pushes the governing eligibility date
        twenty-seven days past the advisory one.

        PRD: "The governing value moves forward with every later disclosure or certification, so an actively disclosed record is never destroyed on schedule; the advisory value freezes at the student's exit and ignores everything afterwards, which makes it always at or before the governing value and makes the gap between them a direct measure of post-exit activity."

        Design: Difficulty/dual_variant_calc/retention_last_activity_vs_exit_anchor
        """
        schedule_id, student_id = _withdrawn_student_with_one_disclosure()

        data = validate_success(api_client.get_retention_schedule(schedule_id, COMPLIANCE))

        assert data["last_activity_at"] == "2026-09-10T00:00:00.000Z"
        assert data["destruction_eligible_at"] == "2031-09-10T00:00:00.000Z"
        assert data["destruction_eligible_at"] != data["exit_anchored_eligible_at"]

        student = validate_success(api_client.get_student(student_id, OFFICER))
        assert student["records_disposition_date"] == "2031-09-10T00:00:00.000Z"


def _withdrawn_student_with_one_disclosure():
    """Withdraw a student with no collected components, then log one directory
    disclosure a month later so nothing but that entry can set last_activity_at."""
    create_state_rule("CA")
    sending = create_district("SEND01", "CA", name="Sending Unified")
    student = create_student(
        sending["id"],
        first_name="Ben",
        last_name="Ortiz",
        dob="2011-05-20",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-ben",
    )
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="OUTOFSTATE",
        withdrawal_reason="MOVED",
    )
    set_clock("2026-08-14T09:00:00Z")
    complete_withdrawal(withdrawal["id"])

    file_id = get_cumulative_file_id(student["id"])
    schedule = get_retention_schedules(file_id)[0]

    set_clock("2026-09-10T00:00:00Z")
    validate_success(
        api_client.create_directory_disclosure(
            student["id"],
            directory_disclosure_payload(
                recipient_name="Regional Yearbook Co",
                disclosed_categories=["NAME", "HONORS"],
                legitimate_interest_note="Yearbook listing",
            ),
            CLERK,
        ),
        201,
    )
    return schedule["id"], student["id"]
