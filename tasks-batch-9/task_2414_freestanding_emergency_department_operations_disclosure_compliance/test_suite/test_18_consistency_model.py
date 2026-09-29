"""Nothing here settles later: the response that causes a cascade already shows it.

One attestation and one observation admission, each read only out of its own response
body, and then a single confirming facility read taken immediately afterwards.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_ledger_entry, assert_posture
from test_helpers.factories import make_observation_payload
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PHYSICIAN,
    acknowledge_disclosure,
    attest_signage,
    create_facility,
    draft_template,
    ledger_entries,
    publish_template,
    read_facility,
    register_encounter,
    screen_encounter,
    set_clock,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}


def test_the_attestation_and_the_admission_each_report_their_own_cascade():
    """The posture flip and the bed count are both in the body that caused them.

    PRD 2.8: "It is recomputed synchronously at the end of every facility-scoped mutation —
    facility creation, facility configuration update, a signage attestation, a template
    publication, and every side effect anywhere in the system that changes the facility's
    `open_compliance_defect_count` — and the recomputation is a fixed, first-match-wins
    ladder." with "When the posture is `OPEN` the list is empty."  PRD 3.1 lists what the
    attestation response therefore has to carry: "An accepted attestation sets
    `signage_attestation_status` to `ATTESTED`, stamps `signage_attested_at` with the logical
    clock, computes `signage_expires_at` as that instant plus one year of validity (365 days),
    and records the acting operator as `signage_attested_by_user_id`." and it appends the
    posture entry described in PRD 2.8: "A ledger entry is appended with `event_type`
    `POSTURE_CHANGE`, `subject_type` `FACILITY`, `subject_id` set to the facility's own id, and
    `defect_counted` false; its `severity` is `INFO` when the new posture is `OPEN`, `MINOR`
    when the new posture is `RESTRICTED`, and `MAJOR` when the new posture is `SUSPENDED`."
    The admission is the same story on the encounter: PRD 3.7 says "On success the encounter
    moves `MSE_COMPLETE → OBSERVATION`, `observation_bed_held` becomes true,
    `observation_started_at` is stamped with the logical clock on first entry into observation,
    the facility's `observation_beds_occupied` is recomputed upward by one, and the facility's
    `version` is incremented by 1."

    Design: Corner/consistency model/every_cascade_is_visible_in_the_same_response_that_caused_it
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)
    template = draft_template(facility["id"], ADMIN)
    after_publish = publish_template(template["id"], facility["version"], ADMIN)
    assert after_publish["status"] == "PUBLISHED"
    facility_after_publish = read_facility(facility["id"])
    assert_posture(facility_after_publish, "RESTRICTED")
    assert facility_after_publish["signage_attestation_status"] == "PENDING"

    encounter = register_encounter(
        facility["id"],
        CLERK,
        patient_reference="PT-4101",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screened = screen_encounter(encounter["id"], "STABLE")
    assert screened["clinical_state"] == "MSE_COMPLETE"

    attested = attest_signage(facility["id"], OFFICER)

    assert attested["signage_attestation_status"] == "ATTESTED"
    assert_posture(attested, "OPEN")
    assert attested["restricted_service_codes"] == []

    admitted = validate_success(
        api_client.admit_to_observation(
            encounter["id"],
            make_observation_payload(observation_plan_note="serial troponins"),
            PHYSICIAN,
        )
    )

    assert admitted["clinical_state"] == "OBSERVATION"
    assert admitted["observation_bed_held"] is True

    assert read_facility(facility["id"])["observation_beds_occupied"] == 1

    entries = ledger_entries(facility["id"])
    assert_ledger_entry(entries, "SIGNAGE_ATTESTED", severity="INFO", count=1)
    assert_ledger_entry(
        entries,
        "POSTURE_CHANGE",
        severity="INFO",
        subject_type="FACILITY",
        subject_id=facility["id"],
        defect_counted=False,
        count=1,
    )
