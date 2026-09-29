"""Validation contracts: conditional field applicability, scoped uniqueness,
aggregate and temporal checks, and the rungs of the validation ladder that
decide which of two broken rules is reported."""

from test_helpers import (
    ADMIN,
    APPLICANT,
    BUSINESS_HOURS_CLOCK,
    INSPECTOR,
    SUPERVISOR,
    ApiErrorId,
    activate_licence,
    api_client,
    appeal_payload,
    appeal_vote_payload,
    assign_appeal_sample,
    cast_vote,
    certificate_payload,
    certify_payload,
    clock_payload,
    create_active_inspector,
    create_active_schedule,
    create_applicant_account,
    create_certified_sampling_device,
    create_certified_scale,
    create_delegated_area,
    create_designated_area,
    create_equipment_row,
    create_inspector_row,
    create_request,
    decide,
    dismiss,
    draft_schedule,
    draw_sample,
    equipment_payload,
    fee_schedule_payload,
    file_appeal,
    file_training_hours,
    grading_result_payload,
    inspection_request_payload,
    inspector_payload,
    issue_certificate,
    applicant_payload,
    protein_analysis_payload,
    comparison_check_payload,
    read_appeal,
    read_area,
    read_certificate,
    read_equipment,
    read_inspector,
    read_request,
    read_sample,
    read_schedule,
    record_grading,
    sample_payload,
    set_clock,
    setup_filed_appeal,
    setup_graded_and_weighed_request,
    setup_office,
    validate_error,
    validate_paginated,
    validate_success,
    vessel_watch_payload,
    weighing_record_payload,
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

APPEAL_SCHEDULE = {"service_class": "APPEAL", "base_fee_cents": 20000}

TWO_DRAFTS_AT_CAPACITY = [
    {"gross_lbs": 50000, "tare_lbs": 20000},
    {"gross_lbs": 50000, "tare_lbs": 20000},
]

THREE_DRAFTS_OVER_CAPACITY = [
    {"gross_lbs": 40000, "tare_lbs": 15000},
    {"gross_lbs": 40000, "tare_lbs": 15000},
    {"gross_lbs": 40000, "tare_lbs": 15000},
]

ONE_DRAFT = [{"gross_lbs": 40000, "tare_lbs": 15000}]


def test_the_two_scale_only_fields_are_forbidden_on_every_other_kind():
    """Two fields are scale-only: `capacity_lbs`, the rated capacity in pounds, and
    `tolerance_lbs`, the maintenance tolerance. Both are required when
    `equipment_kind` is `SCALE` and both must be omitted for the other two kinds;
    either mistake is `ERR_EQUIPMENT_FIELD_APPLICABILITY`.

    For a `SCALE`, `test_error_lbs` — the error observed on the test — is required,
    and must be omitted for a sampling device or protein instrument
    (`ERR_EQUIPMENT_FIELD_APPLICABILITY`).

    Design: Corner/validations/equipment_field_applicability_is_conditional_on_the_kind
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()

    probe_with_scale_fields = api_client.create_equipment(
        equipment_payload(
            area["id"],
            "SAMPLING_DEVICE",
            asset_code="PROBE-APP",
            capacity_lbs=400000,
            tolerance_lbs=20.0,
        ),
        ADMIN,
    )
    validate_error(
        probe_with_scale_fields,
        ApiErrorId.ERR_EQUIPMENT_FIELD_APPLICABILITY.value,
        422,
    )

    scale_without_them = api_client.create_equipment(
        equipment_payload(
            area["id"],
            "SCALE",
            asset_code="SCALE-APP",
            capacity_lbs=...,
            tolerance_lbs=...,
        ),
        ADMIN,
    )
    validate_error(
        scale_without_them, ApiErrorId.ERR_EQUIPMENT_FIELD_APPLICABILITY.value, 422
    )

    scale = create_equipment_row(area["id"], "SCALE", asset_code="SCALE-OK")
    untested = api_client.certify_equipment(scale["id"], certify_payload(), ADMIN)
    validate_error(untested, ApiErrorId.ERR_EQUIPMENT_FIELD_APPLICABILITY.value, 422)

    certified_scale = validate_success(
        api_client.certify_equipment(
            scale["id"], certify_payload(test_error_lbs=5.0), ADMIN
        ),
        200,
    )
    assert certified_scale["approval_status"] == "APPROVED"
    assert certified_scale["last_certification_error_lbs"] == 5.0

    probe = create_equipment_row(area["id"], "SAMPLING_DEVICE", asset_code="PROBE-OK")
    over_reported = api_client.certify_equipment(
        probe["id"], certify_payload(test_error_lbs=5.0), ADMIN
    )
    validate_error(
        over_reported, ApiErrorId.ERR_EQUIPMENT_FIELD_APPLICABILITY.value, 422
    )

    certified_probe = validate_success(
        api_client.certify_equipment(probe["id"], certify_payload(), ADMIN), 200
    )
    assert certified_probe["approval_status"] == "APPROVED"
    assert certified_probe["last_certification_error_lbs"] is None

    _rows, meta = validate_paginated(
        api_client.list_equipment(
            ADMIN,
            {"service_area_id": area["id"], "equipment_kind": "SAMPLING_DEVICE"},
        )
    )
    assert meta["total_count"] == 1


def test_a_certified_device_of_the_wrong_kind_is_refused_in_every_role():
    """`ERR_EQUIPMENT_KIND_MISMATCH` guards sample creation, weighing-record
    creation, protein-analysis creation and comparison-check filing.

    The scale must be of kind `SCALE`, `APPROVED`, with `certified_until` in the
    future, and belong to the request's area; the weigher must hold the `WEIGHING`
    endorsement and a `PROBATIONARY` or `ACTIVE` licence.

    The instrument must be a `PROTEIN_INSTRUMENT` (`ERR_EQUIPMENT_KIND_MISMATCH`);
    a `WITHDRAWN`, `PENDING_APPROVAL` or `EXPIRED` instrument accepts no check and
    is refused with `ERR_EQUIPMENT_WITHDRAWN`; and a supervisor may not name
    themselves as the checked inspector (`ERR_SELF_CHECK_FORBIDDEN`).

    Design: Corner/validations/equipment_kind_must_match_the_role_it_is_used_in
    """
    office = setup_office("DELEGATED", area_overrides={"supervision_required": False})
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        declared_quantity_bushels=3500,
        requested_services=["GRADING", "WEIGHING", "PROTEIN"],
        lot_identifier="LOT-KIND",
    )

    probe_as_scale = api_client.create_weighing_record(
        weighing_record_payload(
            request["id"], office["probe"]["id"], office["inspector"]["id"]
        ),
        INSPECTOR,
    )
    validate_error(probe_as_scale, ApiErrorId.ERR_EQUIPMENT_KIND_MISMATCH.value, 422)

    assert read_request(request["id"])["weighing_status"] == "PENDING"
    _rows, meta = validate_paginated(
        api_client.list_weighing_records(ADMIN, {"inspection_request_id": request["id"]})
    )
    assert meta["total_count"] == 0

    scale_as_probe = api_client.create_sample(
        sample_payload(
            request["id"],
            office["scale"]["id"],
            office["inspector"]["id"],
            seal_number="SEAL-KIND-1",
            portions_count=2,
        ),
        INSPECTOR,
    )
    validate_error(scale_as_probe, ApiErrorId.ERR_EQUIPMENT_KIND_MISMATCH.value, 422)

    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=2,
        seal_number="SEAL-KIND-2",
    )
    probe_as_instrument = api_client.create_protein_analysis(
        protein_analysis_payload(
            request["id"],
            sample["id"],
            office["probe"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(
        probe_as_instrument, ApiErrorId.ERR_EQUIPMENT_KIND_MISMATCH.value, 422
    )

    scale_under_comparison = api_client.create_comparison_check(
        comparison_check_payload(
            office["scale"]["id"], office["inspector"]["id"], 12.00, 12.10
        ),
        ADMIN,
    )
    validate_error(
        scale_under_comparison, ApiErrorId.ERR_EQUIPMENT_KIND_MISMATCH.value, 422
    )

    accepted = api_client.create_weighing_record(
        weighing_record_payload(
            request["id"], office["scale"]["id"], office["inspector"]["id"]
        ),
        INSPECTOR,
    )
    validate_success(accepted, 201)


def test_each_identifier_is_unique_only_inside_its_own_container():
    """A tamper-evident `seal_number` is recorded and must be unique within that
    inspection request (`ERR_DUPLICATE_IDENTIFIER` otherwise), and `portions_count`
    states into how many official portions the sample was divided — at least 1 and
    at most 10.

    Licensing an **inspector** attaches a person to one area through
    `service_area_id` and records a `license_number` — unique within that area, so a
    collision yields `ERR_DUPLICATE_IDENTIFIER` — a `full_name` that is printed on
    certificates, a non-empty set of `endorsements` drawn from `SAMPLING`,
    `GRADING`, `PROTEIN`, `WEIGHING` and `SUPERVISION`, and a `license_expires_at`
    instant.

    Equipment is registered against an area with `service_area_id`, an
    `equipment_kind` of `SAMPLING_DEVICE`, `SCALE` or `PROTEIN_INSTRUMENT`, an
    `asset_code` of 1 to 40 characters that must be unique within the area
    (`ERR_DUPLICATE_IDENTIFIER` otherwise) and a manufacturer `model`.

    A duplicate `account_code` is refused with `ERR_DUPLICATE_IDENTIFIER`.

    Design: Corner/validations/identifier_uniqueness_is_scoped_to_its_container
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    first_area = create_delegated_area()
    second_area = create_delegated_area(name="Second Delegated Office")
    applicant = create_applicant_account(account_code="DUP-100")
    inspector = create_active_inspector(first_area["id"], "L-DUP")
    probe = create_certified_sampling_device(first_area["id"], "PROBE-DUP")

    first_request = create_request(
        applicant["id"], first_area["id"], lot_identifier="LOT-DUP-1"
    )
    second_request = create_request(
        applicant["id"], first_area["id"], lot_identifier="LOT-DUP-2"
    )
    draw_sample(
        first_request["id"],
        probe["id"],
        inspector["id"],
        portions_count=2,
        seal_number="SEAL-DUP",
    )

    def file_sample(request_id):
        return api_client.create_sample(
            sample_payload(
                request_id,
                probe["id"],
                inspector["id"],
                sample_type="FILE",
                seal_number="SEAL-DUP",
                portions_count=2,
            ),
            INSPECTOR,
        )

    validate_error(
        file_sample(first_request["id"]), ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 422
    )
    validate_success(file_sample(second_request["id"]), 201)

    _rows, meta = validate_paginated(
        api_client.list_samples(ADMIN, {"inspection_request_id": first_request["id"]})
    )
    assert meta["total_count"] == 1

    duplicate_account = api_client.create_applicant(
        applicant_payload(account_code="DUP-100", name="Second Elevator Co"), ADMIN
    )
    validate_error(
        duplicate_account, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 422
    )

    same_licence_same_area = api_client.create_inspector(
        inspector_payload(first_area["id"], license_number="L-DUP"), ADMIN
    )
    validate_error(
        same_licence_same_area, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 422
    )
    validate_success(
        api_client.create_inspector(
            inspector_payload(second_area["id"], license_number="L-DUP"), ADMIN
        ),
        201,
    )

    same_asset_same_area = api_client.create_equipment(
        equipment_payload(first_area["id"], "SAMPLING_DEVICE", asset_code="PROBE-DUP"),
        ADMIN,
    )
    validate_error(same_asset_same_area, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 422)
    validate_success(
        api_client.create_equipment(
            equipment_payload(
                second_area["id"], "SAMPLING_DEVICE", asset_code="PROBE-DUP"
            ),
            ADMIN,
        ),
        201,
    )


def test_capacity_is_measured_on_the_sum_of_the_drafts_not_on_any_one_of_them():
    """The sum of `gross_lbs` across all drafts may not exceed the scale's
    `capacity_lbs`, and a draft whose gross does not strictly exceed its tare is
    equally invalid — both fail with `ERR_SCALE_CAPACITY_EXCEEDED`.

    `dockage_lbs` is the sum of the per-draft deductions and `net_lbs` is the sum of
    the per-draft nets — these are the numbers printed on the certificate.

    Finally, `net_bushels` is `net_lbs` divided by the commodity's pounds per bushel
    — 56 for `CORN` and 60 for `SOYBEANS` — rounded half up to 2 decimals.

    Design: Corner/validations/draft_gross_weights_are_checked_against_capacity_in_aggregate
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_delegated_area(supervision_required=False)
    applicant = create_applicant_account()
    inspector = create_active_inspector(
        area["id"], "L-CAP", endorsements=["WEIGHING", "GRADING"]
    )
    scale = create_certified_scale(
        area["id"], "SCALE-CAP", capacity_lbs=100000, tolerance_lbs=20.0
    )
    request = create_request(
        applicant["id"],
        area["id"],
        declared_quantity_bushels=1100,
        requested_services=["GRADING", "WEIGHING"],
        lot_identifier="LOT-CAP-1",
    )

    over_capacity = api_client.create_weighing_record(
        weighing_record_payload(
            request["id"], scale["id"], inspector["id"], THREE_DRAFTS_OVER_CAPACITY
        ),
        INSPECTOR,
    )
    validate_error(over_capacity, ApiErrorId.ERR_SCALE_CAPACITY_EXCEEDED.value, 422)

    untouched = read_request(request["id"])
    assert untouched["weighing_status"] == "PENDING"
    assert untouched["certified_quantity_bushels"] == 1100

    exactly_at_capacity = api_client.create_weighing_record(
        weighing_record_payload(
            request["id"], scale["id"], inspector["id"], TWO_DRAFTS_AT_CAPACITY
        ),
        INSPECTOR,
    )
    record = validate_success(exactly_at_capacity, 201)
    assert record["dockage_pct"] == 0
    assert record["dockage_lbs"] == 0
    assert record["net_lbs"] == 60000
    assert record["net_bushels"] == 1071.43

    second_request = create_request(
        applicant["id"],
        area["id"],
        declared_quantity_bushels=1100,
        requested_services=["GRADING", "WEIGHING"],
        lot_identifier="LOT-CAP-2",
    )
    gross_equals_tare = api_client.create_weighing_record(
        weighing_record_payload(
            second_request["id"],
            scale["id"],
            inspector["id"],
            [{"gross_lbs": 20000, "tare_lbs": 20000}],
        ),
        INSPECTOR,
    )
    validate_error(gross_equals_tare, ApiErrorId.ERR_SCALE_CAPACITY_EXCEEDED.value, 422)


def test_heat_damage_above_total_damage_is_inconsistent_while_equality_is_legal():
    """Since heat damage is a subset of total damage, `heat_damaged_pct` may not
    exceed `damaged_total_pct`, and a set that breaks this is refused with
    `ERR_FACTOR_SET_INCONSISTENT`.

    A **grading determination** is filed against the `inspection_request_id`, on a
    specific `sample_id`, by a specific `inspector_id`, and reports five observed
    factors: `test_weight_lbs_per_bushel` between 20.0 and 70.0 pounds per bushel,
    `moisture_pct` between 0.0 and 40.0, `damaged_total_pct` between 0.0 and 100.0,
    `heat_damaged_pct` between 0.0 and 100.0, and `foreign_material_pct` between 0.0
    and 100.0.

    When the assigned grade is the best grade of the commodity's table,
    `limiting_factor` is `NONE`.

    Design: Corner/validations/heat_damage_may_not_exceed_total_damage
    """
    office = setup_office("DELEGATED")
    request = create_request(
        office["applicant"]["id"], office["area"]["id"], lot_identifier="LOT-FAC"
    )
    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=4,
        seal_number="SEAL-FAC",
    )
    inconsistent = {
        "test_weight_lbs_per_bushel": 56.0,
        "moisture_pct": 13.0,
        "damaged_total_pct": 0.3,
        "heat_damaged_pct": 0.5,
        "foreign_material_pct": 1.5,
    }
    refused = api_client.create_grading_result(
        grading_result_payload(
            request["id"], sample["id"], office["inspector"]["id"], inconsistent
        ),
        INSPECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_FACTOR_SET_INCONSISTENT.value, 422)

    intact = read_sample(sample["id"])
    assert intact["portions_consumed"] == 0
    assert intact["integrity_status"] == "SEALED"
    assert read_request(request["id"])["grading_status"] == "SAMPLED"

    out_of_range = dict(inconsistent, moisture_pct=-1.0, heat_damaged_pct=0.1)
    validate_error(
        api_client.create_grading_result(
            grading_result_payload(
                request["id"], sample["id"], office["inspector"]["id"], out_of_range
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    zero_test_weight = dict(inconsistent, test_weight_lbs_per_bushel=0, heat_damaged_pct=0.1)
    validate_error(
        api_client.create_grading_result(
            grading_result_payload(
                request["id"], sample["id"], office["inspector"]["id"], zero_test_weight
            ),
            INSPECTOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    equal_damage = dict(inconsistent, damaged_total_pct=0.1, heat_damaged_pct=0.1)
    accepted = validate_success(
        api_client.create_grading_result(
            grading_result_payload(
                request["id"], sample["id"], office["inspector"]["id"], equal_damage
            ),
            INSPECTOR,
        ),
        201,
    )
    assert accepted["assigned_grade"] == "US_NO_1"
    assert accepted["limiting_factor"] == "NONE"


def test_activation_is_refused_one_hour_short_of_the_training_requirement():
    """It requires at least 24 completed training hours and a `performance_score` of
    at least 80; falling short of either yields `ERR_INSPECTOR_NOT_QUALIFIED`.

    Training is filed against an inspector as a `course_code` and a number of
    `hours`, which is added to `training_hours_completed` and immediately triggers a
    recomputation of `performance_score`.

    The result is clamped so that it never falls below 0 and never rises above 100.

    Design: Corner/validations/activation_requires_both_training_hours_and_a_passing_score
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    inspector = create_inspector_row(area["id"], "L-ACT")
    almost = file_training_hours(inspector["id"], 23)
    assert almost["training_hours_completed"] == 23
    assert almost["performance_score"] == 100

    too_soon = api_client.activate_inspector(inspector["id"], ADMIN)
    validate_error(too_soon, ApiErrorId.ERR_INSPECTOR_NOT_QUALIFIED.value, 422)

    stalled = read_inspector(inspector["id"])
    assert stalled["license_status"] == "PROBATIONARY"
    assert stalled["training_hours_completed"] == 23
    assert stalled["performance_score"] == 100

    file_training_hours(inspector["id"], 1)
    activated = activate_licence(inspector["id"])
    assert activated["license_status"] == "ACTIVE"
    assert activated["training_hours_completed"] == 24

    repeat = api_client.activate_inspector(inspector["id"], ADMIN)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


def test_a_certified_until_equal_to_now_is_not_strictly_in_the_future():
    """The administrator supplies the new `certified_until`, which must be strictly
    in the future relative to the logical clock or the attempt fails with
    `ERR_EXPIRY_IN_PAST`.

    Three sweeps run: equipment whose `certified_until` is now in the past moves
    from `APPROVED` or `DRIFT_WATCH` to `EXPIRED` and can no longer be used for new
    samples, weighings or analyses; samples whose `file_retention_until` has passed
    move from `SEALED` or `CONSUMED` to `EXPIRED` and can no longer be analysed or
    assigned to an appeal; inspectors whose `license_expires_at` has passed move
    from `ACTIVE` or `PROBATIONARY` to `EXPIRED`, and each such inspector's
    `SCHEDULED` vessel watches are aborted with the owning area's `open_watch_count`
    decremented once per aborted watch.

    Design: Corner/validations/certification_expiry_must_be_strictly_in_the_future
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    probe = create_equipment_row(area["id"], "SAMPLING_DEVICE", asset_code="PROBE-EXP")

    in_the_past = api_client.certify_equipment(
        probe["id"], certify_payload(certified_until="2026-07-01T00:00:00Z"), ADMIN
    )
    validate_error(in_the_past, ApiErrorId.ERR_EXPIRY_IN_PAST.value, 422)

    stalled = read_equipment(probe["id"])
    assert stalled["approval_status"] == "PENDING_APPROVAL"
    assert stalled["certified_until"] is None

    exactly_now = api_client.certify_equipment(
        probe["id"], certify_payload(certified_until=BUSINESS_HOURS_CLOCK), ADMIN
    )
    validate_error(exactly_now, ApiErrorId.ERR_EXPIRY_IN_PAST.value, 422)

    one_second_later = validate_success(
        api_client.certify_equipment(
            probe["id"], certify_payload(certified_until="2026-08-03T09:00:01Z"), ADMIN
        ),
        200,
    )
    assert one_second_later["approval_status"] == "APPROVED"

    sweep = set_clock("2026-08-03T09:00:02Z")
    assert sweep["expired_equipment_count"] == 1
    assert read_equipment(probe["id"])["approval_status"] == "EXPIRED"

    stale_again = api_client.certify_equipment(
        probe["id"], certify_payload(certified_until="2026-08-03T09:00:01Z"), ADMIN
    )
    validate_error(stale_again, ApiErrorId.ERR_EXPIRY_IN_PAST.value, 422)


def test_the_logical_clock_accepts_its_own_instant_but_never_an_earlier_one():
    """The clock may move forward or be set to its present value; a strictly earlier
    instant is refused with `ERR_CLOCK_NOT_MONOTONIC`.

    A logical clock supplies "now" to every deadline, window and expiry comparison,
    and it starts at `2026-08-01T00:00:00Z`.

    The clock response reports the accepted `current_utc` together with
    `expired_equipment_count`, `expired_sample_count` and
    `expired_inspector_count`.

    Design: Corner/validations/logical_clock_refuses_to_move_backwards
    """
    opening = set_clock(BUSINESS_HOURS_CLOCK)
    assert opening["expired_equipment_count"] == 0
    assert opening["expired_sample_count"] == 0
    assert opening["expired_inspector_count"] == 0

    backwards = api_client.set_current_utc(
        clock_payload("2026-08-03T08:59:59Z"), ADMIN
    )
    validate_error(backwards, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value, 422)

    standing_still = api_client.set_current_utc(
        clock_payload(BUSINESS_HOURS_CLOCK), ADMIN
    )
    validate_success(standing_still, 200)

    validate_success(
        api_client.set_current_utc(clock_payload("2026-08-03T09:00:01Z"), ADMIN), 200
    )
    now_behind = api_client.set_current_utc(clock_payload(BUSINESS_HOURS_CLOCK), ADMIN)
    validate_error(now_behind, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value, 422)

    malformed = api_client.set_current_utc(clock_payload("2026-08-03 09:00"), ADMIN)
    validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_two_active_schedules_for_one_class_may_never_share_an_instant():
    """Only a `DRAFT` schedule may be activated — a schedule already `ACTIVE` or
    already `SUPERSEDED` is refused with `ERR_FEE_SCHEDULE_NOT_DRAFT` — and
    activation is refused with `ERR_FEE_SCHEDULE_WINDOW_CONFLICT` when the
    schedule's window overlaps that of another `ACTIVE` schedule for the same area
    and the same `service_class`.

    `effective_to`, when given, must be strictly after `effective_from`, or the
    draft is refused with `ERR_FEE_SCHEDULE_WINDOW_CONFLICT`.

    Design: Corner/validations/fee_schedule_activation_guards_windows_and_draft_status
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_delegated_area()
    incumbent = create_active_schedule(
        area["id"],
        "GRADING",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-06-01T00:00:00Z",
    )
    overlapping = draft_schedule(
        area["id"], "GRADING", effective_from="2026-05-01T00:00:00Z"
    )

    conflict = api_client.activate_fee_schedule(overlapping["id"], ADMIN)
    validate_error(conflict, ApiErrorId.ERR_FEE_SCHEDULE_WINDOW_CONFLICT.value, 422)

    assert read_schedule(overlapping["id"])["status"] == "DRAFT"
    assert read_schedule(incumbent["id"])["status"] == "ACTIVE"

    abutting = draft_schedule(
        area["id"], "GRADING", effective_from="2026-06-01T00:00:00Z"
    )
    validate_success(api_client.activate_fee_schedule(abutting["id"], ADMIN), 200)

    already_used = api_client.activate_fee_schedule(incumbent["id"], ADMIN)
    validate_error(already_used, ApiErrorId.ERR_FEE_SCHEDULE_NOT_DRAFT.value, 409)

    inverted = api_client.create_fee_schedule(
        fee_schedule_payload(
            area["id"],
            "PROTEIN",
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-01-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(inverted, ApiErrorId.ERR_FEE_SCHEDULE_WINDOW_CONFLICT.value, 422)

    other_class = draft_schedule(
        area["id"],
        "WEIGHING",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-06-01T00:00:00Z",
    )
    validate_success(api_client.activate_fee_schedule(other_class["id"], ADMIN), 200)


def test_suspending_an_area_freezes_writes_two_hops_away_and_leaves_reads_alone():
    """An area whose `status` is `SUSPENDED` accepts no new work: creating an
    inspection request, sample, weighing record, protein analysis, certificate or
    vessel watch in a suspended area fails with `ERR_SERVICE_AREA_SUSPENDED` (HTTP
    409), while rows already in flight are left untouched.

    The same administrator may later retune `status`, `fee_multiplier_bp`,
    `supervision_required` and `concurrent_watch_capacity` on an existing area;
    suspending an area stops new intake without disturbing work already recorded.

    Design: Corner/validations/suspended_service_area_blocks_new_operations
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_delegated_area()
    applicant = create_applicant_account()
    inspector = create_active_inspector(area["id"], "L-SUSP")
    probe = create_certified_sampling_device(area["id"], "PROBE-SUSP")
    request = create_request(applicant["id"], area["id"], lot_identifier="LOT-SUSP")

    suspended = validate_success(
        api_client.update_service_area(area["id"], {"status": "SUSPENDED"}, ADMIN), 200
    )
    assert suspended["status"] == "SUSPENDED"

    def sample_attempt():
        return api_client.create_sample(
            sample_payload(
                request["id"],
                probe["id"],
                inspector["id"],
                seal_number="SEAL-SUSP",
                portions_count=2,
            ),
            INSPECTOR,
        )

    validate_error(
        sample_attempt(), ApiErrorId.ERR_SERVICE_AREA_SUSPENDED.value, 409
    )
    validate_error(
        api_client.create_inspection_request(
            inspection_request_payload(
                applicant["id"], area["id"], lot_identifier="LOT-SUSP-2"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_SERVICE_AREA_SUSPENDED.value,
        409,
    )

    # Reads are entirely unaffected by the suspension.
    assert read_request(request["id"])["grading_status"] == "OPEN"
    assert read_area(area["id"])["status"] == "SUSPENDED"
    assert read_equipment(probe["id"])["approval_status"] == "APPROVED"
    _rows, meta = validate_paginated(
        api_client.list_inspection_requests(ADMIN, {"service_area_id": area["id"]})
    )
    assert meta["total_count"] == 1

    validate_success(
        api_client.update_service_area(area["id"], {"status": "ACTIVE"}, ADMIN), 200
    )
    resumed = validate_success(sample_attempt(), 201)
    assert resumed["integrity_status"] == "SEALED"
    assert read_request(request["id"])["grading_status"] == "SAMPLED"

    immutable_field = api_client.update_service_area(
        area["id"], {"name": "Renamed Office"}, ADMIN
    )
    validate_error(immutable_field, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_the_endorsements_a_certificate_demands_follow_its_content():
    """Independently, the named inspector must hold the endorsement the task
    requires, or the operation fails with `ERR_ENDORSEMENT_MISSING`: `SAMPLING` to
    draw a sample, `GRADING` to record a grading determination, `PROTEIN` to run an
    instrument analysis, `WEIGHING` to record a weighing, and — for the inspector
    issuing a certificate — every endorsement the certificate's content requires
    (`GRADING` for grade content, `WEIGHING` for weight content, and additionally
    `SUPERVISION` for an export cargo certificate).

    10. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (grading-result
    creation and vote casting), `ERR_SELF_SUPERVISION_FORBIDDEN` (weighing
    countersignature), `ERR_SELF_CHECK_FORBIDDEN` (comparison-check filing),
    `ERR_DUPLICATE_PANEL_VOTE` (vote casting), `ERR_ENDORSEMENT_MISSING` (sample,
    grading-result, protein-analysis, weighing-record creation and certificate
    issuance), `ERR_EXPORT_REQUIRES_DESIGNATED_AREA` (certificate issuance). All are
    422.

    Design: Corner/validations/endorsement_check_follows_the_content_the_certificate_carries
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(GRADING_SCHEDULE, WEIGHING_SCHEDULE),
    )
    grade_only = create_active_inspector(
        office["area"]["id"], "L-GONLY", endorsements=["GRADING"]
    )
    staged = setup_graded_and_weighed_request(office, lot_identifier="LOT-END")

    weight_content = api_client.create_certificate(
        certificate_payload(staged["request"]["id"], grade_only["id"], "COMBINED"),
        INSPECTOR,
    )
    validate_error(weight_content, ApiErrorId.ERR_ENDORSEMENT_MISSING.value, 422)

    unmoved = read_request(staged["request"]["id"])
    assert unmoved["grading_status"] == "GRADED"
    assert unmoved["weighing_status"] == "WEIGHED"
    _rows, meta = validate_paginated(
        api_client.list_certificates(
            ADMIN, {"inspection_request_id": staged["request"]["id"]}
        )
    )
    assert meta["total_count"] == 0

    unsampled = api_client.create_sample(
        sample_payload(
            staged["request"]["id"],
            office["probe"]["id"],
            grade_only["id"],
            sample_type="FILE",
            seal_number="SEAL-END",
            portions_count=2,
        ),
        INSPECTOR,
    )
    validate_error(unsampled, ApiErrorId.ERR_ENDORSEMENT_MISSING.value, 422)

    # Priority 10 outranks priority 11: the missing endorsement is reported even
    # though the request already carries an operative weighing record.
    unweighable = api_client.create_weighing_record(
        weighing_record_payload(
            staged["request"]["id"], office["scale"]["id"], grade_only["id"]
        ),
        INSPECTOR,
    )
    validate_error(unweighable, ApiErrorId.ERR_ENDORSEMENT_MISSING.value, 422)

    grade_content = api_client.create_certificate(
        certificate_payload(staged["request"]["id"], grade_only["id"], "GRADE"),
        INSPECTOR,
    )
    validate_success(grade_content, 201)


def test_a_regrade_binding_failure_pre_empts_the_appeal_state_error():
    """The named appeal must be in `SAMPLE_ASSIGNED`, its certificate must belong to
    the same inspection request as the determination, and the determination's
    `sample_id` must equal the appeal's `assigned_sample_id`; any of these broken
    yields `ERR_APPEAL_REGRADE_BINDING_INVALID`.

    Attempting assignment from any state other than `FILED` is
    `ERR_APPEAL_STATE_INVALID`.

    The regrade itself is a grading determination carrying the `appeal_id`, and it
    moves the appeal `SAMPLE_ASSIGNED → UNDER_REVIEW`.

    Design: Corner/validations/appeal_regrade_binding_is_checked_before_the_appeal_state
    """
    office = setup_office(
        "DELEGATED", fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE)
    )
    regrader = create_active_inspector(
        office["area"]["id"], "L-RA", endorsements=["GRADING"]
    )
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        declared_quantity_bushels=500,
        lot_identifier="LOT-BIND",
    )
    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=6,
        seal_number="SEAL-BIND-1",
    )
    other_sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        sample_type="FILE",
        portions_count=2,
        seal_number="SEAL-BIND-2",
    )
    record_grading(request["id"], sample["id"], office["inspector"]["id"])
    certificate = issue_certificate(request["id"], office["inspector"]["id"], "GRADE")
    appeal = file_appeal(
        certificate["id"],
        office["applicant"]["id"],
        read_certificate(certificate["id"])["version"],
        "APPEAL",
    )
    assert appeal["status"] == "FILED"

    def regrade(sample_id):
        return api_client.create_grading_result(
            grading_result_payload(
                request["id"],
                sample_id,
                regrader["id"],
                appeal_id=appeal["id"],
            ),
            INSPECTOR,
        )

    too_early = regrade(sample["id"])
    validate_error(
        too_early, ApiErrorId.ERR_APPEAL_REGRADE_BINDING_INVALID.value, 422
    )

    waiting = read_appeal(appeal["id"])
    assert waiting["status"] == "FILED"
    assert waiting["assigned_sample_id"] is None
    assert read_sample(sample["id"])["portions_consumed"] == 1

    # The state code the priority-7 binding rule pre-empted on the regrade path.
    validate_error(
        api_client.decide_appeal(appeal["id"], ADMIN),
        ApiErrorId.ERR_APPEAL_STATE_INVALID.value,
        409,
    )

    assign_appeal_sample(appeal["id"], sample["id"])
    wrong_sample = regrade(other_sample["id"])
    validate_error(
        wrong_sample, ApiErrorId.ERR_APPEAL_REGRADE_BINDING_INVALID.value, 422
    )

    validate_success(regrade(sample["id"]), 201)
    assert read_appeal(appeal["id"])["status"] == "UNDER_REVIEW"


def test_the_under_appeal_freeze_is_reported_before_the_one_appeal_rule():
    """The certificate must be `ISSUED` and its `certificate_type` must not be
    `APPEAL_GRADE`; a certificate already `UNDER_APPEAL` is refused with
    `ERR_CERTIFICATE_UNDER_APPEAL`, and a certificate that already carries a
    non-terminal appeal is refused with `ERR_DUPLICATE_OPERATIVE_RECORD`.

    A certificate whose predecessor of the same type is currently `UNDER_APPEAL`
    cannot be issued (`ERR_CERTIFICATE_UNDER_APPEAL`).

    In both cases `refund_cents` is half of `deposit_cents` truncated downward,
    credited to the applicant, and the challenged certificate returns to `ISSUED`;
    where the appeal had already reached `SAMPLE_ASSIGNED`, the retained portion is
    additionally released with `portions_retained` decreasing by one.

    Design: Corner/validations/certificate_under_appeal_outranks_the_uniqueness_rule
    """
    office = setup_office(
        "DELEGATED", fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE)
    )
    staged = setup_filed_appeal(
        office,
        appeal_type="APPEAL",
        portions_count=4,
        declared_quantity_bushels=500,
        lot_identifier="LOT-FREEZE",
        seal_number="SEAL-FREEZE",
    )
    certificate_id = staged["certificate"]["id"]
    fresh_version = read_certificate(certificate_id)["version"]

    second_filing = api_client.create_appeal(
        appeal_payload(
            certificate_id,
            office["applicant"]["id"],
            fresh_version,
            "REINSPECTION",
        ),
        APPLICANT,
    )
    validate_error(
        second_filing, ApiErrorId.ERR_CERTIFICATE_UNDER_APPEAL.value, 409
    )

    _rows, meta = validate_paginated(
        api_client.list_certificate_appeals(certificate_id, ADMIN)
    )
    assert meta["total_count"] == 1
    assert read_certificate(certificate_id)["status"] == "UNDER_APPEAL"

    reissue = api_client.create_certificate(
        certificate_payload(staged["request"]["id"], office["inspector"]["id"], "GRADE"),
        INSPECTOR,
    )
    validate_error(reissue, ApiErrorId.ERR_CERTIFICATE_UNDER_APPEAL.value, 409)

    dismissed = dismiss(staged["appeal"]["id"])
    assert dismissed["refund_cents"] == 10000
    assert read_certificate(certificate_id)["status"] == "ISSUED"

    accepted = api_client.create_appeal(
        appeal_payload(
            certificate_id,
            office["applicant"]["id"],
            read_certificate(certificate_id)["version"],
            "REINSPECTION",
        ),
        APPLICANT,
    )
    validate_success(accepted, 201)


def test_a_request_may_carry_only_one_operative_weighing_record():
    """A request that already has a weighing record in `WEIGHED` or `SUPERVISED`
    status cannot have another (`ERR_DUPLICATE_OPERATIVE_RECORD`), and the request's
    weighing dimension must be `PENDING`, which in turn means `WEIGHING` must have
    been among the `requested_services`.

    An optional `appeal_id` marks the determination as an appeal or reinspection
    regrade rather than the original work; when it is absent the determination is
    the original one, requires the request to be in `SAMPLED`, and is refused with
    `ERR_DUPLICATE_OPERATIVE_RECORD` if a `FINAL` determination with no appeal
    linkage already exists for the request.

    Design: Corner/validations/one_operative_weighing_record_per_request
    """
    office = setup_office("DELEGATED", area_overrides={"supervision_required": False})
    staged = setup_graded_and_weighed_request(office, lot_identifier="LOT-ONE")

    second_record = api_client.create_weighing_record(
        weighing_record_payload(
            staged["request"]["id"],
            office["scale"]["id"],
            office["inspector"]["id"],
            ONE_DRAFT,
        ),
        INSPECTOR,
    )
    validate_error(
        second_record, ApiErrorId.ERR_DUPLICATE_OPERATIVE_RECORD.value, 422
    )

    _rows, meta = validate_paginated(
        api_client.list_weighing_records(
            ADMIN, {"inspection_request_id": staged["request"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    still_weighed = read_request(staged["request"]["id"])
    assert still_weighed["weighing_status"] == "WEIGHED"
    assert still_weighed["certified_quantity_bushels"] == 3609.27

    second_determination = api_client.create_grading_result(
        grading_result_payload(
            staged["request"]["id"], staged["sample"]["id"], office["inspector"]["id"]
        ),
        INSPECTOR,
    )
    validate_error(
        second_determination, ApiErrorId.ERR_DUPLICATE_OPERATIVE_RECORD.value, 422
    )

    other_request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        declared_quantity_bushels=3500,
        requested_services=["GRADING", "WEIGHING"],
        lot_identifier="LOT-ONE-2",
    )
    elsewhere = api_client.create_weighing_record(
        weighing_record_payload(
            other_request["id"],
            office["scale"]["id"],
            office["inspector"]["id"],
            ONE_DRAFT,
        ),
        INSPECTOR,
    )
    validate_success(elsewhere, 201)


def test_the_watch_window_is_ordered_at_creation_and_half_open_at_start():
    """First, `window_end_at` must be strictly after `window_start_at`, or the watch
    is refused with `ERR_WATCH_WINDOW_INVALID`.

    It may only be done inside the window — the clock must be at or after
    `window_start_at` and strictly before `window_end_at`, otherwise
    `ERR_WATCH_WINDOW_INVALID` — and only by a supervising inspector whose licence
    is `ACTIVE` and who holds the `SUPERVISION` endorsement.

    Standing the watch moves it `SCHEDULED → IN_PROGRESS`, stamping `started_at`
    from the logical clock.

    Design: Corner/validations/watch_window_bounds_are_checked_at_creation_and_at_start
    """
    office = setup_office(
        "DESIGNATED",
        area_overrides={"concurrent_watch_capacity": 2},
        second_supervisor=True,
    )
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier="LOT-WIN",
        requested_services=["GRADING", "EXPORT_SUPERVISION"],
    )

    def attempt(inspector_id, start, end):
        return api_client.create_vessel_watch(
            vessel_watch_payload(request["id"], inspector_id, start, end), SUPERVISOR
        )

    zero_length = attempt(
        office["supervisor"]["id"], "2026-08-04T08:00:00Z", "2026-08-04T08:00:00Z"
    )
    validate_error(zero_length, ApiErrorId.ERR_WATCH_WINDOW_INVALID.value, 422)

    _rows, meta = validate_paginated(
        api_client.list_vessel_watches(ADMIN, {"inspection_request_id": request["id"]})
    )
    assert meta["total_count"] == 0
    assert read_area(office["area"]["id"])["open_watch_count"] == 0

    inverted = attempt(
        office["supervisor"]["id"], "2026-08-04T16:00:00Z", "2026-08-04T08:00:00Z"
    )
    validate_error(inverted, ApiErrorId.ERR_WATCH_WINDOW_INVALID.value, 422)

    watch = validate_success(
        attempt(
            office["supervisor"]["id"], "2026-08-04T08:00:00Z", "2026-08-04T16:00:00Z"
        ),
        201,
    )
    assert watch["status"] == "SCHEDULED"
    assert read_area(office["area"]["id"])["open_watch_count"] == 1

    later_watch = validate_success(
        attempt(
            office["supervisor_2"]["id"],
            "2026-08-04T10:00:00Z",
            "2026-08-04T16:00:00Z",
        ),
        201,
    )

    too_early = api_client.start_vessel_watch(watch["id"], SUPERVISOR)
    validate_error(too_early, ApiErrorId.ERR_WATCH_WINDOW_INVALID.value, 422)

    set_clock("2026-08-04T08:00:00Z")
    started = validate_success(
        api_client.start_vessel_watch(watch["id"], SUPERVISOR), 200
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["started_at"].startswith("2026-08-04T08:00:00")

    set_clock("2026-08-04T16:00:00Z")
    too_late = api_client.start_vessel_watch(later_watch["id"], SUPERVISOR)
    validate_error(too_late, ApiErrorId.ERR_WATCH_WINDOW_INVALID.value, 422)


def test_a_board_appeal_needs_an_upheld_round_and_a_panel_from_another_area():
    """A `BOARD_APPEAL` is round 3, decided by a five-member panel drawn from other
    service areas, and may only be filed when a prior `APPEAL` on the same
    certificate was decided `DECIDED_UPHELD` — otherwise
    `ERR_APPEAL_ESCALATION_INVALID` — and no later than 20 days after that appeal's
    `decided_at`.

    The `round_number` and `required_panel_size` are derived from `appeal_type` and
    are never supplied by the client: 1 and 1 for a `REINSPECTION`, 2 and 3 for an
    `APPEAL`, 3 and 5 for a `BOARD_APPEAL`.

    A member may cast at most one vote per appeal (`ERR_DUPLICATE_PANEL_VOTE`); the
    inspector who produced the challenged determination may not vote at all
    (`ERR_SEGREGATION_OF_DUTIES`); the voter must hold an `ACTIVE` licence; and on a
    `BOARD_APPEAL` every panel member must belong to a service area other than the
    challenged certificate's area (`ERR_BOARD_PANEL_COMPOSITION_INVALID`).

    Design: Corner/validations/board_appeal_needs_an_upheld_predecessor_and_an_outside_panel
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE),
    )
    outside_area = create_delegated_area(name="Neighbouring Delegated Office")
    outside_voter = create_active_inspector(outside_area["id"], "L-B1")
    regrader = create_active_inspector(
        office["area"]["id"], "L-RB", endorsements=["GRADING"]
    )
    home_voters = [
        create_active_inspector(office["area"]["id"], f"L-V{index}")
        for index in (1, 2, 3)
    ]

    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        declared_quantity_bushels=500,
        lot_identifier="LOT-BOARD",
    )
    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=8,
        seal_number="SEAL-BOARD",
    )
    record_grading(request["id"], sample["id"], office["inspector"]["id"])
    certificate = issue_certificate(request["id"], office["inspector"]["id"], "GRADE")

    premature = api_client.create_appeal(
        appeal_payload(
            certificate["id"],
            office["applicant"]["id"],
            read_certificate(certificate["id"])["version"],
            "BOARD_APPEAL",
        ),
        APPLICANT,
    )
    validate_error(premature, ApiErrorId.ERR_APPEAL_ESCALATION_INVALID.value, 422)

    round_one = file_appeal(
        certificate["id"],
        office["applicant"]["id"],
        read_certificate(certificate["id"])["version"],
        "APPEAL",
    )
    assign_appeal_sample(round_one["id"], sample["id"])
    record_grading(
        request["id"], sample["id"], regrader["id"], appeal_id=round_one["id"]
    )
    for voter in home_voters:
        cast_vote(round_one["id"], voter["id"], "UPHOLD")
    upheld = decide(round_one["id"])
    assert upheld["status"] == "DECIDED_UPHELD"
    assert read_certificate(certificate["id"])["status"] == "ISSUED"

    round_two = file_appeal(
        certificate["id"],
        office["applicant"]["id"],
        read_certificate(certificate["id"])["version"],
        "BOARD_APPEAL",
    )
    assign_appeal_sample(round_two["id"], sample["id"])
    record_grading(
        request["id"], sample["id"], regrader["id"], appeal_id=round_two["id"]
    )
    staged = read_appeal(round_two["id"])
    assert staged["round_number"] == 3
    assert staged["required_panel_size"] == 5
    assert staged["status"] == "UNDER_REVIEW"
    version_before = staged["version"]

    inside_voter = api_client.create_appeal_vote(
        appeal_vote_payload(
            round_two["id"], home_voters[0]["id"], "REVISE", version_before
        ),
        SUPERVISOR,
    )
    validate_error(
        inside_voter, ApiErrorId.ERR_BOARD_PANEL_COMPOSITION_INVALID.value, 422
    )

    refused = read_appeal(round_two["id"])
    assert refused["votes_cast_count"] == 0
    assert refused["effective_votes_count"] == 0
    assert refused["version"] == version_before

    validate_success(
        api_client.create_appeal_vote(
            appeal_vote_payload(
                round_two["id"], outside_voter["id"], "REVISE", version_before
            ),
            SUPERVISOR,
        ),
        201,
    )
    tallied = read_appeal(round_two["id"])
    assert tallied["votes_cast_count"] == 1
    assert tallied["effective_votes_count"] == 1

    short_panel = api_client.decide_appeal(round_two["id"], ADMIN)
    validate_error(short_panel, ApiErrorId.ERR_APPEAL_QUORUM_NOT_MET.value, 422)

    accounting = read_sample(sample["id"])
    assert accounting["portions_consumed"] == 3
    assert accounting["portions_retained"] == 1
