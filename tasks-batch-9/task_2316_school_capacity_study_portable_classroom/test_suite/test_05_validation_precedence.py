"""Pairs of rules violated on one call, where only the earlier one may answer."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ASSET_HEADERS, PLANNER_HEADERS, SCHEDULER_HEADERS
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    condition_payload,
    placement_request_payload,
    schedule_payload,
)
from test_helpers.fixtures import (
    build_campus,
    build_request_context,
    certify_study,
    create_crew,
    create_site,
    create_study,
    create_unit,
    study_version,
    submit_study,
)


def _two_campus_pads(api):
    """One study on Alder, two pads on Birch and one undersized pad on Alder."""
    alder = build_campus(api, school_overrides={"name": "Alder Middle",
                                               "site_acreage": 8.0,
                                               "electrical_spare_capacity_kw": 40,
                                               "sewer_spare_connections": 1})
    birch = build_campus(api, clock=None, policy_id=alder["policy_id"],
                         budget_cents=None,
                         school_overrides={"name": "Birch Middle",
                                           "site_acreage": 8.0,
                                           "electrical_spare_capacity_kw": 40,
                                           "sewer_spare_connections": 1})

    ctx = dict(alder)
    ctx["wrong_small_site_id"] = create_site(
        api, birch["school_id"], pad_code="PAD-SMALL", pad_length_ft=42,
    )["id"]
    ctx["wrong_big_site_id"] = create_site(
        api, birch["school_id"], pad_code="PAD-BIG", pad_length_ft=60,
    )["id"]
    ctx["right_small_site_id"] = create_site(
        api, alder["school_id"], pad_code="PAD-SMALL", pad_length_ft=42,
    )["id"]
    ctx["unit_id"] = create_unit(api, asset_tag="PU-9001")["id"]

    study = create_study(api, alder["school_id"], alder["policy_id"])
    submit_study(api, study["id"])
    ctx["study_id"] = study["id"]
    return ctx


def _request_payload_for(api, ctx, site_id):
    return placement_request_payload(
        ctx["study_id"], site_id, ctx["budget_id"],
        study_version(api, ctx["study_id"]),
        haul_miles=10, portable_unit_id=ctx["unit_id"],
    )


def test_pad_on_the_wrong_campus_answers_before_pad_geometry(api):
    """PRD §2.6: "The evaluation order below is normative: the server reports the
    failure of the earliest applicable rule and stops." Rule 20 — "The pad's `school_id`
    is equal to the `school_id` of the study named by `capacity_study_id` —
    `ERR_SITE_SCHOOL_MISMATCH`, 422" — precedes rule 30 — "Pad geometry admits the unit:
    `pad_length_ft` is at least the unit's chassis length plus 10 feet ... —
    `ERR_PAD_TOO_SMALL`, 422". PRD §3.5 also holds that only a successful create
    "reserves the named unit by moving its `allocation_status` from `IN_STORAGE` to
    `RESERVED`".

    Design: Difficulty/priority_pair_validation_conflict/site_school_mismatch_outranks_pad_too_small
    """
    ctx = _two_campus_pads(api)

    response = api.create_placement_request(
        _request_payload_for(api, ctx, ctx["wrong_small_site_id"]), PLANNER_HEADERS
    )
    body = validate_error(response, ApiErrorId.SITE_SCHOOL_MISMATCH, expected_status=422)
    assert body["error_id"] != ApiErrorId.PAD_TOO_SMALL

    assert validate_success(
        api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS)
    )["allocation_status"] == "IN_STORAGE"


def test_each_placement_pad_rule_still_fires_when_it_is_alone(api):
    """PRD §2.6 rule 30: "Pad geometry admits the unit: `pad_length_ft` is at least the
    unit's chassis length plus 10 feet and `pad_width_ft` is at least the unit's chassis
    width plus 10 feet — `ERR_PAD_TOO_SMALL`, 422, on `POST
    /facilities/placement-requests`." PRD §2.6 rule 20: "The pad's `school_id` is equal
    to the `school_id` of the study named by `capacity_study_id` —
    `ERR_SITE_SCHOOL_MISMATCH`, 422".

    Design: Difficulty/priority_pair_validation_conflict/site_school_mismatch_outranks_pad_too_small
    """
    ctx = _two_campus_pads(api)

    geometry_only = api.create_placement_request(
        _request_payload_for(api, ctx, ctx["right_small_site_id"]), PLANNER_HEADERS
    )
    validate_error(geometry_only, ApiErrorId.PAD_TOO_SMALL, expected_status=422)

    campus_only = api.create_placement_request(
        _request_payload_for(api, ctx, ctx["wrong_big_site_id"]), PLANNER_HEADERS
    )
    validate_error(campus_only, ApiErrorId.SITE_SCHOOL_MISMATCH, expected_status=422)

    assert validate_success(
        api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS)
    )["allocation_status"] == "IN_STORAGE"


def _uncertified_study_with_downgraded_unit(api):
    """A draft request whose study is only SUBMITTED and whose unit needs rehab."""
    ctx = build_request_context(
        api,
        stage="draft",
        certify=False,
        school_overrides={"name": "Cedar Middle", "site_acreage": 8.0,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
        unit_overrides={"asset_tag": "PU-9101"},
    )
    validate_success(
        api.record_condition(ctx["unit_id"], condition_payload("NEEDS_REHAB", "C"),
                             ASSET_HEADERS)
    )
    return ctx


def test_uncertified_study_answers_before_the_unserviceable_unit(api):
    """PRD §2.6: "the server reports the failure of the earliest applicable rule and
    stops." Rule 11 — "The capacity study referenced by the request is `CERTIFIED` —
    `ERR_STUDY_NOT_CERTIFIED`, 409, on `POST
    /facilities/placement-requests/{id}/assess-site`" — precedes rule 15 — "The
    referenced portable unit's `condition_status` is `SERVICEABLE` —
    `ERR_UNIT_NOT_SERVICEABLE`, 422, on exactly four endpoints ... `POST
    /facilities/placement-requests/{id}/assess-site`".

    Design: Difficulty/priority_pair_validation_conflict/study_not_certified_outranks_unit_not_serviceable
    """
    ctx = _uncertified_study_with_downgraded_unit(api)

    response = api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS)
    body = validate_error(response, ApiErrorId.STUDY_NOT_CERTIFIED, expected_status=409)
    assert body["error_id"] != ApiErrorId.UNIT_NOT_SERVICEABLE

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "DRAFT"


def test_certifying_the_study_exposes_the_unserviceable_unit_and_then_the_success(api):
    """PRD §2.6 rule 15: "The referenced portable unit's `condition_status` is
    `SERVICEABLE` — `ERR_UNIT_NOT_SERVICEABLE`, 422". PRD §3.5: "Confirming the site
    closes the `DRAFT → SITE_ASSESSED` gap and is the point at which the certification
    requirement lands", and PRD §3.9 lets an
    inspection restore a unit because "`condition_status` records serviceability and
    moves only when an `AssetManager` records an inspection".

    Design: Difficulty/priority_pair_validation_conflict/study_not_certified_outranks_unit_not_serviceable
    """
    ctx = _uncertified_study_with_downgraded_unit(api)
    certify_study(api, ctx["study_id"])

    safety_only = api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS)
    validate_error(safety_only, ApiErrorId.UNIT_NOT_SERVICEABLE, expected_status=422)

    validate_success(
        api.record_condition(ctx["unit_id"], condition_payload("SERVICEABLE", "B"),
                             ASSET_HEADERS)
    )
    assessed = validate_success(api.assess_site(ctx["request_id"], {}, PLANNER_HEADERS))
    assert assessed["status"] == "SITE_ASSESSED"


def _permitted_off_summer_request(api):
    """A permitted request for a September window, plus one crew of each kind."""
    ctx = build_request_context(
        api,
        stage="permitted",
        school_overrides={"name": "Dogwood Middle", "site_acreage": 8.0,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
        unit_overrides={"asset_tag": "PU-9201"},
        crew_overrides={"name": "Crew Relocate Only",
                        "certified_work_types": ["RELOCATE"]},
        request_overrides={"requested_window_start": "2027-09-01",
                           "requested_window_end": "2027-09-10"},
    )
    ctx["uncertified_crew_id"] = ctx["crew_id"]
    ctx["certified_crew_id"] = create_crew(api, name="Crew Alpha")["id"]
    return ctx


def test_uncertified_crew_answers_before_the_waiver_role(api):
    """PRD §2.6: "the server reports the failure of the earliest applicable rule and
    stops." Rule 33 — "The crew's `certified_work_types` contains the requested
    `work_type` — `ERR_CREW_NOT_CERTIFIED`, 422, on `POST
    /facilities/installation-schedules`" — precedes rule 36 — "`off_summer_waiver` may
    be set true only by a `DistrictAdmin` — `ERR_WAIVER_ROLE_REQUIRED`, 403".

    Design: Difficulty/priority_pair_validation_conflict/crew_certification_outranks_waiver_role
    """
    ctx = _permitted_off_summer_request(api)

    response = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["uncertified_crew_id"],
                         window_start="2027-09-01", window_end="2027-09-10",
                         off_summer_waiver=True),
        SCHEDULER_HEADERS,
    )
    body = validate_error(response, ApiErrorId.CREW_NOT_CERTIFIED, expected_status=422)
    assert body["error_id"] != ApiErrorId.WAIVER_ROLE_REQUIRED

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "PERMITTED"


def test_waiver_role_answers_once_the_crew_is_certified(api):
    """PRD §3.8: "The window must lie entirely inside June 15 through August 15 of a
    single calendar year unless `off_summer_waiver` is true
    (`ERR_OUTSIDE_SUMMER_WINDOW`), and only a `DistrictAdmin` may set that flag true
    (`ERR_WAIVER_ROLE_REQUIRED`)." PRD §2.6 rule 36 fixes the status: "403, on `POST
    /facilities/installation-schedules`".

    Design: Difficulty/priority_pair_validation_conflict/crew_certification_outranks_waiver_role
    """
    ctx = _permitted_off_summer_request(api)

    response = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["certified_crew_id"],
                         window_start="2027-09-01", window_end="2027-09-10",
                         off_summer_waiver=True),
        SCHEDULER_HEADERS,
    )
    validate_error(response, ApiErrorId.WAIVER_ROLE_REQUIRED, expected_status=403)

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "PERMITTED"
