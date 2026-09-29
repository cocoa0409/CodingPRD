"""Endpoint behaviour: the run counter that retires an instrument, the one-shot
protein restatement, the finality of a broken seal, the scoped nested
certificate listing and the closed set of retunable area settings."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    BUSINESS_HOURS_CLOCK,
    CORN_NO_1_FACTORS_MOISTURE_12_8,
    INSPECTOR,
    SUPERVISOR,
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    break_seal_payload,
    certify_payload,
    comparison_check_payload,
    create_certified_instrument,
    create_designated_area,
    create_inspector_row,
    file_check,
    grading_result_payload,
    issue_certificate,
    protein_analysis_payload,
    read_analysis,
    read_area,
    read_equipment,
    read_inspector,
    read_request,
    read_sample,
    record_analysis,
    record_grading,
    set_clock,
    setup_graded_and_weighed_request,
    setup_graded_request,
    setup_office,
    setup_sampled_request,
    validate_error,
    validate_paginated,
    validate_success,
)


GRADING_SCHEDULE = {
    "service_class": "GRADING",
    "base_fee_cents": 8000,
    "per_thousand_bushel_rate_cents": 2000,
    "minimum_fee_cents": 10000,
}

WEIGHING_SCHEDULE = {
    "service_class": "WEIGHING",
    "base_fee_cents": 6000,
    "per_thousand_bushel_rate_cents": 1000,
    "minimum_fee_cents": 8000,
}


def test_the_third_consecutive_out_of_tolerance_check_retires_the_instrument():
    """An `OUT_OF_TOLERANCE` resolution moves `APPROVED → OUT_OF_TOLERANCE` or
    `DRIFT_WATCH → OUT_OF_TOLERANCE` — the two paths run the identical cascade
    — and increments `consecutive_out_of_tolerance_checks` by one. When that
    counter reaches 3, the instrument moves `OUT_OF_TOLERANCE → WITHDRAWN` and
    is permanently unusable: no further certification and no further comparison
    check will be accepted on it.

    The instrument's `recent_deviations_pct` keeps at most the three most recent
    deviations including this one, oldest first in ascending creation order, and
    `rolling_bias_pct` is the arithmetic mean of those retained deviations,
    rounded half up to 2 decimals.

    A `WITHDRAWN` row accepts no certification at all and is refused with
    `ERR_EQUIPMENT_WITHDRAWN`.

    The instrument must be of kind `PROTEIN_INSTRUMENT`, must belong to the
    request's area, and — uniquely among equipment uses — may be either
    `APPROVED` or `DRIFT_WATCH` provided its `certified_until` is still in the
    future; anything else is `ERR_EQUIPMENT_NOT_APPROVED`.

    The score is a weighted deduction from a perfect 100: subtract 18 for each
    appeal reversed against the inspector, subtract 10 for each proficiency
    deviation counted against them, subtract 3 for each late certificate, then
    add a training credit equal to the whole number of complete ten-hour blocks
    of `training_hours_completed`, capped at 12.

    Automatic suspension is the threshold trigger: whenever a recomputation
    leaves an `ACTIVE` inspector with a `performance_score` strictly below 70,
    the licence moves `ACTIVE → SUSPENDED` on the spot with `suspension_reason`
    recorded as `AUTO_PERFORMANCE`, that inspector's `SCHEDULED` watches are
    aborted with the area's `open_watch_count` decremented accordingly, and any
    non-terminal appeal on which they are the sole panel member stays
    `UNDER_REVIEW` while their further votes are refused. A score of exactly 70
    does not trigger it.

    Otherwise, when the absolute `rolling_bias_pct` exceeds 0.15, it resolves to
    `DRIFT_WATCH`.

    Note also that a deviation of 0.30 counts against the inspector's
    `check_sample_deviation_count`, because that counter's bar is 0.25, while
    leaving the instrument merely on drift watch.

    Design: Corner/endpoints/three_consecutive_failed_checks_withdraw_the_instrument
    """
    office = setup_office("DESIGNATED")
    instrument = office["instrument"]
    checked = create_inspector_row(office["area"]["id"], "L-6001")
    assert checked["license_status"] == "PROBATIONARY"

    file_check(instrument["id"], checked["id"], 12.00, 12.65, SUPERVISOR)
    file_check(instrument["id"], checked["id"], 12.00, 12.65, SUPERVISOR)
    twice = read_equipment(instrument["id"])
    assert twice["approval_status"] == "OUT_OF_TOLERANCE"
    assert twice["consecutive_out_of_tolerance_checks"] == 2

    third = api_client.create_comparison_check(
        comparison_check_payload(instrument["id"], checked["id"], 12.00, 12.65),
        SUPERVISOR,
    )
    validate_success(third, 201)

    withdrawn = read_equipment(instrument["id"])
    assert withdrawn["approval_status"] == "WITHDRAWN"
    assert withdrawn["consecutive_out_of_tolerance_checks"] == 3
    assert withdrawn["recent_deviations_pct"] == [0.65, 0.65, 0.65]
    assert withdrawn["rolling_bias_pct"] == 0.65
    assert withdrawn["last_comparison_deviation_pct"] == 0.65
    assert withdrawn["comparison_check_count"] == 3

    fourth = api_client.create_comparison_check(
        comparison_check_payload(instrument["id"], checked["id"], 12.00, 12.10),
        SUPERVISOR,
    )
    validate_error(fourth, ApiErrorId.ERR_EQUIPMENT_WITHDRAWN.value, 409)

    revival = api_client.certify_equipment(
        instrument["id"], certify_payload(), ADMIN
    )
    validate_error(revival, ApiErrorId.ERR_EQUIPMENT_WITHDRAWN.value, 409)
    assert read_equipment(instrument["id"])["approval_status"] == "WITHDRAWN"

    staged = setup_sampled_request(
        office,
        requested_services=("GRADING", "PROTEIN"),
        portions_count=2,
        lot_identifier="LOT-NIR",
        seal_number="SEAL-NIR",
    )
    unusable = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            staged["sample"]["id"],
            instrument["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(unusable, ApiErrorId.ERR_EQUIPMENT_NOT_APPROVED.value, 409)

    on_the_floor = read_inspector(checked["id"])
    assert on_the_floor["check_sample_deviation_count"] == 3
    assert on_the_floor["performance_score"] == 70
    assert on_the_floor["license_status"] == "PROBATIONARY"
    assert on_the_floor["suspension_reason"] is None

    # The two bars are independent: 0.30 leaves the instrument usable while
    # still counting against the inspector.
    replacement = create_certified_instrument(office["area"]["id"], "NIR-6002")
    validate_success(
        api_client.create_comparison_check(
            comparison_check_payload(replacement["id"], checked["id"], 12.00, 12.30),
            SUPERVISOR,
        ),
        201,
    )
    drifting = read_equipment(replacement["id"])
    assert drifting["approval_status"] == "DRIFT_WATCH"
    assert drifting["rolling_bias_pct"] == 0.30
    assert drifting["consecutive_out_of_tolerance_checks"] == 0

    counted = read_inspector(checked["id"])
    assert counted["check_sample_deviation_count"] == 4
    assert counted["performance_score"] == 60
    assert counted["license_status"] == "PROBATIONARY"


def test_the_official_basis_restatement_is_refused_then_accepted_then_spent():
    """An analysis created before grading finished can be restated afterwards.
    Restatement is permitted only when a `FINAL` grading determination now
    exists on the request, the analysis's `status` is still `ACCEPTED`, and its
    `basis_source` is still `INSTRUMENT_MOISTURE`; any other combination is
    refused with `ERR_ANALYSIS_RECOMPUTE_NOT_APPLICABLE`. Restatement sets
    `basis_source` to `OFFICIAL_MOISTURE`, adopts the official rounded moisture
    as `moisture_source_pct`, recomputes `protein_reported_pct` and
    `basis_adjustment_pct` by the same arithmetic, and sets `status` to
    `RECOMPUTED`.

    Which moisture the conversion uses depends on what the office already knows:
    when no `FINAL` grading determination exists for the request at the moment
    the analysis is created, `basis_source` is `INSTRUMENT_MOISTURE` and
    `moisture_source_pct` is the `instrument_moisture_pct`; when a `FINAL`
    determination does exist, `basis_source` is `OFFICIAL_MOISTURE` and
    `moisture_source_pct` is that determination's rounded `moisture_pct` from
    `rounded_factors`. In both cases `protein_reported_pct` is the as-is protein
    multiplied by the difference between 100 and 13.0, divided by the difference
    between 100 and `moisture_source_pct`, rounded half up to 2 decimals, and
    `basis_adjustment_pct` is `protein_reported_pct` less `protein_pct_as_is`,
    likewise rounded half up to 2 decimals.

    Every accepted analysis receives a `sequence_no`, a counter that is
    monotonically increasing per instrument and starts at 1, used to break ties
    when two analyses share a `created_at` during an ordered cascade.

    **Protein and specialty analysis** is ordered separately and consumes its
    own portion.

    Design: Corner/endpoints/protein_recompute_is_a_one_shot_restatement
    """
    office = setup_office("DELEGATED")
    staged = setup_sampled_request(
        office,
        requested_services=("GRADING", "PROTEIN"),
        portions_count=4,
        lot_identifier="LOT-RC1",
        seal_number="SEAL-RC1",
    )
    analysis = record_analysis(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["instrument"]["id"],
        office["inspector"]["id"],
        protein_pct_as_is=8.60,
        instrument_moisture_pct=11.20,
    )
    assert analysis["status"] == "ACCEPTED"
    assert analysis["sequence_no"] == 1
    assert analysis["basis_source"] == "INSTRUMENT_MOISTURE"
    assert analysis["moisture_source_pct"] == 11.20
    assert analysis["protein_reported_pct"] == 8.43
    assert analysis["basis_adjustment_pct"] == -0.17

    too_early = api_client.recompute_protein_analysis(analysis["id"], INSPECTOR)
    validate_error(
        too_early, ApiErrorId.ERR_ANALYSIS_RECOMPUTE_NOT_APPLICABLE.value, 422
    )
    unmoved = read_analysis(analysis["id"])
    assert unmoved["basis_source"] == "INSTRUMENT_MOISTURE"
    assert unmoved["protein_reported_pct"] == 8.43
    assert unmoved["version"] == analysis["version"]

    grading = record_grading(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["inspector"]["id"],
        factors=CORN_NO_1_FACTORS_MOISTURE_12_8,
    )
    assert grading["status"] == "FINAL"
    assert grading["rounded_factors"]["moisture_pct"] == 12.8

    restated = validate_success(
        api_client.recompute_protein_analysis(analysis["id"], INSPECTOR), 200
    )
    assert restated["status"] == "RECOMPUTED"
    assert restated["basis_source"] == "OFFICIAL_MOISTURE"
    assert restated["moisture_source_pct"] == 12.8
    assert restated["protein_reported_pct"] == 8.58
    assert restated["basis_adjustment_pct"] == -0.02
    assert restated["version"] == analysis["version"] + 1

    spent = api_client.recompute_protein_analysis(analysis["id"], INSPECTOR)
    validate_error(spent, ApiErrorId.ERR_ANALYSIS_RECOMPUTE_NOT_APPLICABLE.value, 422)

    final = read_analysis(analysis["id"])
    assert final["status"] == "RECOMPUTED"
    assert final["protein_reported_pct"] == 8.58
    assert final["version"] == restated["version"]

    sample = read_sample(staged["sample"]["id"])
    assert sample["portions_consumed"] == 2
    assert sample["portions_available"] == 2
    assert sample["integrity_status"] == "SEALED"


def test_a_broken_seal_ends_every_analytical_use_of_that_sample():
    """Integrity is the sample's other scarce resource, and its loss is final. A
    `SupervisingInspector` may record a broken seal with an optional `reason`,
    moving the sample `SEALED → BROKEN` or `CONSUMED → BROKEN`; from `SEALED`
    this is only permitted when no non-terminal appeal currently holds the
    sample as its assigned regrade sample, and from `CONSUMED` there is no
    further precondition. A broken sample is treated as having no available
    portions and can never be analysed again. Both `BROKEN` and `EXPIRED` are
    terminal, and a sample in either state that is offered for a grading
    determination, an analysis or an appeal assignment is refused with
    `ERR_SAMPLE_INTEGRITY_BROKEN`. Samples may be listed by
    `inspection_request_id`, `sampling_device_id`, `inspector_id`, `sample_type`
    and `integrity_status`.

    `portions_available` is always `portions_count` less `portions_consumed`
    less `portions_retained`.

    2. **Authorization** — the declared role must be permitted for the endpoint,
    else `ERR_UNAUTHORIZED` (403). Applies to every endpoint.

    Design: Corner/endpoints/breaking_a_seal_freezes_every_analytical_use_of_the_sample
    """
    office = setup_office("DESIGNATED")
    staged = setup_sampled_request(
        office,
        requested_services=("GRADING", "PROTEIN"),
        portions_count=4,
        lot_identifier="LOT-BS1",
        seal_number="SEAL-BS1",
    )
    sample_id = staged["sample"]["id"]
    assert staged["sample"]["integrity_status"] == "SEALED"

    # Breaking a seal is a supervisor's act; a line inspector never reaches it.
    line_inspector = api_client.break_seal(
        sample_id, INSPECTOR, break_seal_payload("seal found cut on arrival")
    )
    validate_error(line_inspector, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_sample(sample_id)["integrity_status"] == "SEALED"

    broken = validate_success(
        api_client.break_seal(
            sample_id, SUPERVISOR, break_seal_payload("seal found cut on arrival")
        ),
        200,
    )
    assert broken["integrity_status"] == "BROKEN"
    assert broken["portions_consumed"] == 0
    assert broken["portions_retained"] == 0
    assert broken["portions_available"] == 4

    refused_grading = api_client.create_grading_result(
        grading_result_payload(
            staged["request"]["id"], sample_id, office["inspector"]["id"]
        ),
        INSPECTOR,
    )
    validate_error(
        refused_grading, ApiErrorId.ERR_SAMPLE_INTEGRITY_BROKEN.value, 409
    )

    refused_analysis = api_client.create_protein_analysis(
        protein_analysis_payload(
            staged["request"]["id"],
            sample_id,
            office["instrument"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(
        refused_analysis, ApiErrorId.ERR_SAMPLE_INTEGRITY_BROKEN.value, 409
    )

    again = api_client.break_seal(
        sample_id, SUPERVISOR, break_seal_payload("second look")
    )
    validate_error(again, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    _rows, meta = validate_paginated(
        api_client.list_samples(ADMIN, {"integrity_status": "BROKEN"})
    )
    assert meta["total_count"] == 1
    _sealed, sealed_meta = validate_paginated(
        api_client.list_samples(ADMIN, {"integrity_status": "SEALED"})
    )
    assert sealed_meta["total_count"] == 0

    assert read_request(staged["request"]["id"])["grading_status"] == "SAMPLED"


def test_the_nested_certificate_listing_is_scoped_filtered_and_windowed():
    """Certificates may be listed by `inspection_request_id`,
    `issuing_inspector_id`, `superseded_certificate_id`, `appeal_id`,
    `certificate_type`, `status` and `fee_settlement_status`.

    Every list endpoint returns rows sorted by `created_at` in ascending order
    unless a specific requirement says otherwise. Collection endpoints also
    accept the filter parameters named in their §4 descriptions and in the
    workflow narratives — filters narrow the result set but never change the
    ordering or the pagination arithmetic.

    `limit` caps the number of rows returned; it defaults to 10, may not be
    smaller than 1 and may not be larger than 100. `offset` skips rows from the
    head of the result and defaults to 0, its smallest permitted value. Both are
    echoed back in `meta` alongside `total_count` (the number of rows matching
    the filters before the window is applied) and `has_more` (true when rows
    remain beyond the returned window).

    Design: Corner/endpoints/nested_certificate_read_is_scoped_and_filterable
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(GRADING_SCHEDULE, WEIGHING_SCHEDULE),
    )
    first = setup_graded_and_weighed_request(office, lot_identifier="LOT-NC1")
    grade = issue_certificate(
        first["request"]["id"], office["inspector"]["id"], "GRADE"
    )
    weight = issue_certificate(
        first["request"]["id"], office["inspector"]["id"], "WEIGHT"
    )
    second = setup_graded_request(
        office,
        declared_quantity_bushels=500,
        portions_count=1,
        lot_identifier="LOT-NC2",
        seal_number="SEAL-NC2",
    )
    elsewhere = issue_certificate(
        second["request"]["id"], office["inspector"]["id"], "GRADE"
    )

    rows, meta = validate_paginated(
        api_client.list_request_certificates(first["request"]["id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [grade["id"], weight["id"]]
    assert elsewhere["id"] not in {row["id"] for row in rows}

    typed, typed_meta = validate_paginated(
        api_client.list_request_certificates(
            first["request"]["id"], ADMIN, {"certificate_type": "WEIGHT"}
        )
    )
    assert typed_meta["total_count"] == 1
    assert [row["id"] for row in typed] == [weight["id"]]

    head, head_meta = validate_paginated(
        api_client.list_request_certificates(
            first["request"]["id"], ADMIN, {"limit": 1, "offset": 0}
        )
    )
    assert head_meta["total_count"] == 2
    assert head_meta["limit"] == 1
    assert head_meta["has_more"] is True
    assert [row["id"] for row in head] == [grade["id"]]

    tail, tail_meta = validate_paginated(
        api_client.list_request_certificates(
            first["request"]["id"], ADMIN, {"limit": 1, "offset": 1}
        )
    )
    assert tail_meta["total_count"] == 2
    assert tail_meta["offset"] == 1
    assert tail_meta["has_more"] is False
    assert [row["id"] for row in tail] == [weight["id"]]

    scoped, scoped_meta = validate_paginated(
        api_client.list_certificates(
            AUDITOR, {"inspection_request_id": second["request"]["id"]}
        )
    )
    assert scoped_meta["total_count"] == 1
    assert [row["id"] for row in scoped] == [elsewhere["id"]]

    _all_rows, all_meta = validate_paginated(api_client.list_certificates(AUDITOR))
    assert all_meta["total_count"] == 3

    over = api_client.list_request_certificates(
        first["request"]["id"], ADMIN, {"limit": 101}
    )
    validate_error(over, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    under = api_client.list_request_certificates(
        first["request"]["id"], ADMIN, {"limit": 0}
    )
    validate_error(under, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_only_the_four_retunable_area_settings_may_be_patched():
    """The same administrator may later retune `status`, `fee_multiplier_bp`,
    `supervision_required` and `concurrent_watch_capacity` on an existing area;
    suspending an area stops new intake without disturbing work already
    recorded.

    Four further settings may be supplied and otherwise default: `status` starts
    `ACTIVE` (the alternative is `SUSPENDED`); `fee_multiplier_bp` starts at
    10000, meaning no adjustment, and may be set anywhere from 10000 up to
    15000; `supervision_required` starts true; and `concurrent_watch_capacity`
    starts at 2 and must be at least 1.

    5. **Schema** — required body fields present, correctly typed, inside their
    declared ranges and enum domains, with unknown fields rejected, else
    `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.

    All resources except appeal votes additionally carry `updated_at` — the same
    format, refreshed on every mutation of the row — and `version`, an integer
    that begins at 1 and increments by exactly one on every mutation.

    Design: Corner/endpoints/service_area_patch_touches_only_the_declared_mutable_fields
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    assert area["fee_multiplier_bp"] == 10000
    assert area["supervision_required"] is True
    assert area["concurrent_watch_capacity"] == 2
    assert area["status"] == "ACTIVE"

    retuned = validate_success(
        api_client.update_service_area(
            area["id"], {"fee_multiplier_bp": 12500}, ADMIN
        ),
        200,
    )
    assert retuned["fee_multiplier_bp"] == 12500
    assert retuned["name"] == area["name"]
    assert retuned["state_code"] == area["state_code"]
    assert retuned["authority_type"] == area["authority_type"]
    assert retuned["status"] == "ACTIVE"
    assert retuned["supervision_required"] is True
    assert retuned["concurrent_watch_capacity"] == 2
    assert retuned["open_watch_count"] == 0
    assert retuned["created_at"] == area["created_at"]
    assert retuned["version"] == area["version"] + 1
    assert retuned["updated_at"].startswith("2026-08-03T09:00:00")

    below = api_client.update_service_area(
        area["id"], {"fee_multiplier_bp": 9999}, ADMIN
    )
    validate_error(below, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    above = api_client.update_service_area(
        area["id"], {"fee_multiplier_bp": 15001}, ADMIN
    )
    validate_error(above, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    assert read_area(area["id"])["fee_multiplier_bp"] == 12500

    floor = validate_success(
        api_client.update_service_area(
            area["id"], {"fee_multiplier_bp": 10000}, ADMIN
        ),
        200,
    )
    assert floor["fee_multiplier_bp"] == 10000

    ceiling = validate_success(
        api_client.update_service_area(
            area["id"], {"fee_multiplier_bp": 15000}, ADMIN
        ),
        200,
    )
    assert ceiling["fee_multiplier_bp"] == 15000

    renamed = api_client.update_service_area(
        area["id"], {"name": "Renamed Office"}, ADMIN
    )
    validate_error(renamed, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    reauthorised = api_client.update_service_area(
        area["id"], {"authority_type": "DELEGATED"}, ADMIN
    )
    validate_error(reauthorised, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    settled = read_area(area["id"])
    assert settled["name"] == area["name"]
    assert settled["authority_type"] == "DESIGNATED"

    not_an_admin = api_client.update_service_area(
        area["id"], {"supervision_required": False}, SUPERVISOR
    )
    validate_error(not_an_admin, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_area(area["id"])["supervision_required"] is True

    nowhere = api_client.update_service_area(
        UNKNOWN_UUID, {"fee_multiplier_bp": 11000}, ADMIN
    )
    validate_error(nowhere, ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND.value, 404)
