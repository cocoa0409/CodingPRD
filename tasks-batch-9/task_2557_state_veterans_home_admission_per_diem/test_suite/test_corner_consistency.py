"""The consistency model: derived counters settle inside the writing request.

The API keeps no deferred reconciliation pass, so a counter that a write moves is
already moved for the very next read — on the single-resource read, on the
collection read and on the parent record alike. This file drives one admission and
one discharge and reads every affected counter immediately after each write.

The server is restarted before every test, so the test builds its own world and
starts from an empty database with the logical clock at its documented starting
instant.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_bed_counts, assert_fields


def _waitlisted_candidate(api):
    """One eligible applicant queued on a two-bed certified nursing unit."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api, name="Ambleside State Veterans Home")
    unit = fx.create_unit(
        api,
        home["id"],
        unit_name="Nursing A",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )
    applicant = fx.create_applicant(
        api,
        home["id"],
        full_name="Cato Rennemo",
        date_of_birth="1943-02-02",
        state_residency_years=6,
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant["id"])
    entry = fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    assessment = fx.create_assessment(api, applicant["id"], assessment_date="2026-08-01")
    fx.submit_assessment(api, assessment["id"])
    return home, unit, applicant, entry, assessment


def test_derived_counters_are_visible_on_the_immediately_following_read(
    api, coordinator_headers
):
    """Every counter an admission or a discharge moves is settled before the next read.

    The admission is taken and then the unit, the unit list, the home and the unit's
    waitlist are read without any intervening checkpoint or refresh call: the bed
    counts, the queue counter, the posture, the parent home's resident count and the
    entry's own status all already show the post-admission world, and the collection
    read agrees with the single-resource read to the digit. The discharge then puts
    every one of those numbers back where it started, again within the one request.

    Per the PRD: "§3 states each chain hop by hop; implementers must apply the whole
    chain within the request that triggered it, because this system's consistency
    model is immediate — there is no deferred reconciliation pass."

    Per the PRD: "Any change to a resident's `occupancy_status` or `care_unit_id`
    recomputes the affected unit's `occupied_bed_count` and `held_bed_count`, which
    recomputes `available_bed_count`, which recomputes `operational_posture`; a
    posture change can in turn revoke outstanding bed offers on that unit."

    Per the PRD: "`active_resident_count` is the number of residents in any of this
    home's units whose `occupancy_status` is either `ADMITTED` or `HOSPITALIZED`."

    Per the PRD: "Discharge sets `occupancy_status` to `DISCHARGED`, stores
    `discharge_date` and `discharge_reason`, sets `billing_status` to `CLOSED`, and
    sets `bed_hold_active` to false while leaving `bed_hold_started_on` in place."

    Design: Corner/consistency_model/consistency_derived_counters_visible_on_the_immediately_following_read
    """
    home, unit, applicant, entry, assessment = _waitlisted_candidate(api)

    before = validate_success(api.get_care_unit(unit["id"], coordinator_headers))
    assert_bed_counts(before, occupied=0, held=0, available=2, posture="OPEN")

    resident = validate_success(
        api.admission_decision(
            applicant["id"],
            f.admission_decision_payload(
                unit["id"], assessment["id"], before["version"], "2026-08-01"
            ),
            coordinator_headers,
        ),
        201,
    )
    assert resident["occupancy_status"] == "ADMITTED"

    after_admission = validate_success(api.get_care_unit(unit["id"], coordinator_headers))
    assert_bed_counts(after_admission, occupied=1, held=0, available=1, posture="OPEN")
    assert after_admission["waitlist_active_count"] == 0, (
        "the admitted entry leaves the queue inside the deciding request"
    )

    listed, listed_meta = validate_paginated(
        api.list_home_care_units(
            home["id"], coordinator_headers, {"care_level": "NURSING", "limit": 10}
        )
    )
    assert listed_meta["total_count"] == 1
    assert_fields(listed[0], occupied_bed_count=1, available_bed_count=1)

    home_after_admission = validate_success(
        api.get_veterans_home(home["id"], coordinator_headers)
    )
    assert home_after_admission["active_resident_count"] == 1

    admitted_entries, admitted_meta = validate_paginated(
        api.list_unit_waitlist_entries(
            unit["id"], coordinator_headers, {"status": "ADMITTED", "limit": 10}
        )
    )
    assert admitted_meta["total_count"] == 1
    assert admitted_entries[0]["id"] == entry["id"]

    discharged = validate_success(
        api.discharge_resident(
            resident["id"], f.discharge_payload("2026-08-01", "VOLUNTARY"), coordinator_headers
        ),
        200,
    )
    assert_fields(discharged, occupancy_status="DISCHARGED", billing_status="CLOSED")

    after_discharge = validate_success(api.get_care_unit(unit["id"], coordinator_headers))
    assert_bed_counts(after_discharge, occupied=0, held=0, available=2, posture="OPEN")

    home_after_discharge = validate_success(
        api.get_veterans_home(home["id"], coordinator_headers)
    )
    assert home_after_discharge["active_resident_count"] == 0
