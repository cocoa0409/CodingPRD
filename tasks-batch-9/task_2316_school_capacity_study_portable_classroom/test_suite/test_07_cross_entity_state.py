"""Writes on one entity gated on the current status of a different entity."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ASSET_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    condition_payload,
    disposal_payload,
    legacy_placement_payload,
    schedule_payload,
)
from test_helpers.fixtures import (
    approve_all_permits,
    approve_permit,
    build_request_context,
    certify_study,
    create_school,
    create_site,
    create_unit,
    reopen_study,
    return_study,
    set_clock,
    submit_study,
)


def _draft_request_on_a_submitted_study(api):
    return build_request_context(
        api,
        stage="draft",
        certify=False,
        school_overrides={"name": "Fernwood Middle", "site_acreage": 8.0,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
        unit_overrides={"asset_tag": "PU-A101"},
    )


def test_site_confirmation_is_refused_while_the_study_is_only_submitted(api):
    """PRD §3.5: "A `FacilitiesPlanner` may confirm only a request in `DRAFT`, only when
    the study named by `capacity_study_id` has reached `CERTIFIED` (otherwise
    `ERR_STUDY_NOT_CERTIFIED`)". PRD §2.6 rule 11 fixes the status: "The capacity study
    referenced by the request is `CERTIFIED` — `ERR_STUDY_NOT_CERTIFIED`, 409, on `POST
    /facilities/placement-requests/{id}/assess-site`."

    Design: Difficulty/cross_entity_state_dependency/request_site_assessment_requires_certified_study
    """
    ctx = _draft_request_on_a_submitted_study(api)

    response = api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS)
    validate_error(response, ApiErrorId.STUDY_NOT_CERTIFIED, expected_status=409)

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "DRAFT"
    assert validate_success(
        api.get_capacity_study(ctx["study_id"], PLANNER_HEADERS)
    )["status"] == "SUBMITTED"


def test_a_returned_study_is_refused_and_only_certification_opens_the_gate(api):
    """PRD §3.5: "only when the study named by `capacity_study_id` has reached
    `CERTIFIED` (otherwise `ERR_STUDY_NOT_CERTIFIED`)" — a status test, not a history
    test. PRD §3.3: "A `FacilitiesPlanner` reopens a study in `RETURNED`, moving it
    `RETURNED → DRAFT`", and certification is performed "on a study in
    `SUBMITTED`, moving it `SUBMITTED → CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/request_site_assessment_requires_certified_study
    """
    ctx = _draft_request_on_a_submitted_study(api)

    return_study(api, ctx["study_id"], "Revisit the grade 8 cohort.")
    refused = api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS)
    validate_error(refused, ApiErrorId.STUDY_NOT_CERTIFIED, expected_status=409)

    reopen_study(api, ctx["study_id"])
    submit_study(api, ctx["study_id"])
    certified = certify_study(api, ctx["study_id"])
    assert certified["status"] == "CERTIFIED"

    assessed = validate_success(api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS))
    assert assessed["status"] == "SITE_ASSESSED"


def _site_assessed_request(api):
    return build_request_context(
        api,
        stage="site_assessed",
        school_overrides={"name": "Glenview Middle", "site_acreage": 8.0,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
        unit_overrides={"asset_tag": "PU-B101"},
    )


def test_crew_booking_is_refused_while_the_request_is_only_site_assessed(api):
    """PRD §2.6 rule 12: "The placement request named by the booking is `PERMITTED` and
    no sibling schedule of that request is `PLANNED`, `IN_PROGRESS` or `COMPLETED` —
    `ERR_REQUEST_NOT_PERMITTED`, 409, on `POST /facilities/installation-schedules`."

    Design: Difficulty/cross_entity_state_dependency/schedule_creation_requires_permitted_request
    """
    ctx = _site_assessed_request(api)

    response = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["crew_id"]), SCHEDULER_HEADERS
    )
    validate_error(response, ApiErrorId.REQUEST_NOT_PERMITTED, expected_status=409)

    rows, meta = validate_paginated(
        api.list_installation_schedules(SCHEDULER_HEADERS,
                                        {"placement_request_id": ctx["request_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "SITE_ASSESSED"


def test_crew_booking_is_refused_mid_fan_out_and_accepted_once_permitted(api):
    """PRD §3.7: "When, and only when, every permit of the request now stands
    `APPROVED`, the request joins on the favourable arm: it moves `PERMIT_PENDING →
    PERMITTED`". PRD §3.8 on booking: "The request must be `PERMITTED` and must have no
    sibling schedule in `PLANNED`, `IN_PROGRESS` or `COMPLETED` ...
    (`ERR_REQUEST_NOT_PERMITTED`)."

    Design: Difficulty/cross_entity_state_dependency/schedule_creation_requires_permitted_request
    """
    ctx = _site_assessed_request(api)
    validate_success(api.submit_permits(ctx["request_id"], {}, PERMIT_HEADERS))
    permits = approve_all_permits(api, ctx["request_id"], skip=("ELECTRICAL",))

    mid_fan_out = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["crew_id"]), SCHEDULER_HEADERS
    )
    validate_error(mid_fan_out, ApiErrorId.REQUEST_NOT_PERMITTED, expected_status=409)
    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "PERMIT_PENDING"

    approve_permit(api, permits["ELECTRICAL"])

    booked = validate_success(
        api.create_installation_schedule(
            schedule_payload(ctx["request_id"], ctx["crew_id"]), SCHEDULER_HEADERS
        ),
        expected_status=201,
    )
    assert booked["status"] == "PLANNED"
    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "SCHEDULED"


def _stored_and_installed_units(api):
    """One stored grade B portable and one identical portable standing on a pad."""
    set_clock(api, "2027-03-15T00:00:00Z")
    school = create_school(api, name="Hollyhock Middle", site_acreage=8.0,
                          electrical_spare_capacity_kw=40, sewer_spare_connections=1)
    legacy_site = create_site(api, school["id"], pad_code="PAD-LEGACY")
    stored = create_unit(api, asset_tag="PU-C101", in_service_year=2011)
    installed = create_unit(api, asset_tag="PU-C102", in_service_year=2011)
    validate_success(
        api.record_existing_placement(
            installed["id"],
            legacy_placement_payload(school["id"], legacy_site["id"],
                                     installed_on="2027-03-15"),
            ASSET_HEADERS,
        )
    )
    return {"school_id": school["id"], "stored_unit_id": stored["id"],
            "installed_unit_id": installed["id"]}


def test_a_serviceable_grade_b_portable_cannot_be_written_off(api):
    """PRD §3.9: "Disposal requires the unit to be `IN_STORAGE`, requires either its
    `condition_status` to be `UNSAFE` or its `condition_grade` to be `D`, and requires
    that no disposal record already reference that unit; any of these failing yields
    `ERR_UNIT_NOT_DISPOSABLE`." PRD §2.6 rule 13 fixes the status at 409.

    Design: Difficulty/cross_entity_state_dependency/disposal_requires_unit_condemned_or_grade_d
    """
    ctx = _stored_and_installed_units(api)

    response = api.create_disposal_record(
        disposal_payload(ctx["stored_unit_id"]), ASSET_HEADERS
    )
    validate_error(response, ApiErrorId.UNIT_NOT_DISPOSABLE, expected_status=409)

    unit = validate_success(api.get_portable_unit(ctx["stored_unit_id"], ASSET_HEADERS))
    assert unit["allocation_status"] == "IN_STORAGE"
    assert unit["condition_status"] == "SERVICEABLE"

    rows, meta = validate_paginated(
        api.list_disposal_records(ASSET_HEADERS,
                                 {"portable_unit_id": ctx["stored_unit_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_grade_d_alone_satisfies_disposal_but_only_off_the_pad(api):
    """PRD §3.9: "requires either its `condition_status` to be `UNSAFE` or its
    `condition_grade` to be `D`" — a disjunction over the condition dimension, conjoined
    with "requires the unit to be `IN_STORAGE`". On success "The unit moves `IN_STORAGE →
    DISPOSED`", and under the `CONDITION_ADJUSTED` basis the salvage figure "is then
    lifted to a floor equal to 5 percent of `acquisition_cost_cents` rounded half up".

    Design: Difficulty/cross_entity_state_dependency/disposal_requires_unit_condemned_or_grade_d
    """
    ctx = _stored_and_installed_units(api)

    validate_success(
        api.record_condition(ctx["stored_unit_id"],
                             condition_payload("NEEDS_REHAB", "D"), ASSET_HEADERS)
    )
    record = validate_success(
        api.create_disposal_record(disposal_payload(ctx["stored_unit_id"]),
                                   ASSET_HEADERS),
        expected_status=201,
    )
    assert record["salvage_value_cents"] == 480_000
    assert record["net_disposal_result_cents"] == -480_000
    assert validate_success(
        api.get_portable_unit(ctx["stored_unit_id"], ASSET_HEADERS)
    )["allocation_status"] == "DISPOSED"

    validate_success(
        api.record_condition(ctx["installed_unit_id"],
                             condition_payload("NEEDS_REHAB", "D"), ASSET_HEADERS)
    )
    refused = api.create_disposal_record(
        disposal_payload(ctx["installed_unit_id"]), ASSET_HEADERS
    )
    validate_error(refused, ApiErrorId.UNIT_NOT_DISPOSABLE, expected_status=409)
    assert validate_success(
        api.get_portable_unit(ctx["installed_unit_id"], ASSET_HEADERS)
    )["allocation_status"] == "INSTALLED"
