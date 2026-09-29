"""Endpoint-level behaviour of the programme's read and write surfaces.

The certified pre-owned service exposes four kinds of surface that are easy to
implement almost correctly. The programme configuration is a singleton with no
creation operation, so a retune has to accumulate onto the generation already in
force rather than reset the tunables it does not mention. The repair listing
under an inspection is the only channel through which a repair's identifier is
discoverable, so it has to filter, paginate and carry each row's computed
reimbursement at the same time — with a `total_count` that describes the
filtered set. The results endpoint accepts an array but has no partial-success
semantics, so one bad row must leave the attempt already on file untouched. And
a complaint's link to its certification has to be observable from the child read
and from the parent's collection alike, without leaking a sibling
certification's complaints. These tests exercise all four.
"""

from test_helpers import (
    ADMIN,
    ADVOCATE,
    AUDIT_SAMPLE_PCT,
    AUDITOR,
    BASE_FEE_CENTS,
    CLOCK_EPOCH,
    DEFAULT_LIMIT,
    PROGRAM_CONFIG_TUNABLES,
    REINSPECTION_DEADLINE_DAYS,
    REQUIRED_DOC_TYPES,
    VOLUME_DISCOUNT_TIERS,
    ApiErrorId,
    activate_many,
    assert_complaint,
    assert_created_at_ascending,
    assert_instant_equals,
    assert_pagination_meta,
    assert_program_config,
    assert_reconditioning_item,
    bootstrap_program,
    clean_attempt_rows,
    complete_reconditioning,
    file_complaint,
    item_b1_payload,
    item_p1_payload,
    item_s1_payload,
    item_t1_payload,
    iso_shift,
    open_inspection_for,
    read_certification,
    read_complaint,
    read_config,
    read_inspection,
    reconditioning_item_for,
    record_results,
    reimbursable_for,
    result_row,
    results_payload,
    retune_config,
    submit_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    waive_reconditioning,
)

#: The two tunables the retune test moves, and therefore restores afterwards.
_RETUNED_TUNABLES = ("audit_sample_pct", "audit_sample_min_per_run")


def _inspection_with_three_repairs(api):
    """Close one attempt that fails every reconditioning-eligible point.

    The checklist carries an uncurable critical point that passes plus three
    repairable points that fail, so the close lands on
    `RECONDITIONING_REQUIRED` with one repair per failure. The brake repair is
    then completed at 1001 cents by a second technician, the tyre repair is
    waived by the administrator, and the safety repair is left outstanding, so
    the three rows sit in three different statuses.
    """
    program = bootstrap_program(
        api,
        items=[
            item_p1_payload(),
            item_s1_payload(),
            item_b1_payload(),
            item_t1_payload(),
        ],
    )
    walk = open_inspection_for(api, program)
    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "FAIL", measured_value=2.0),
            result_row("T1", "FAIL"),
        ],
    )
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    assert walk.inspection["status"] == "RECONDITIONING_REQUIRED"
    brakes = reconditioning_item_for(api, walk.inspection_id, "B1")
    tyres = reconditioning_item_for(api, walk.inspection_id, "T1")
    complete_reconditioning(api, brakes["id"], 1001, program.other_technician_headers)
    waive_reconditioning(api, tyres["id"], "tyre wear within regional tolerance")
    return walk


def test_the_live_programme_configuration_is_seeded_once_for_every_role_to_read(
    api, program
):
    """All five roles see the same first generation of the seeded rulebook.

    PRD §2.6: "there is exactly one such row and it is never created or deleted
    through the API"
    PRD §2.6: "All five roles may read the live configuration, including its
    `version`, so that dealers and tests can see the tunables in force."
    PRD §2.4: "a monotonically increasing integer that starts at 1 on creation"

    Design: Corner/endpoints/program_config_read_and_partial_update
    """
    viewers = (
        ADMIN,
        AUDITOR,
        ADVOCATE,
        program.dealer_headers,
        program.technician_headers,
    )
    views = []
    for headers in viewers:
        response = api.get_program_config(headers)
        data = validate_success(response)
        assert response.json()["response_type"] == "object", (
            "the live configuration is a single resource, not a collection"
        )
        assert_program_config(data)
        for tunable in PROGRAM_CONFIG_TUNABLES:
            assert tunable in data, f"the configuration must expose {tunable}"
        assert data["version"] == 1, "no retune has happened, so the seed is generation 1"
        assert data["base_fee_cents"] == BASE_FEE_CENTS
        assert data["audit_sample_pct"] == AUDIT_SAMPLE_PCT
        assert data["required_doc_types"] == list(REQUIRED_DOC_TYPES)
        assert len(data["required_doc_types"]) == 4
        assert data["volume_discount_tiers"] == [dict(t) for t in VOLUME_DISCOUNT_TIERS]
        assert len(data["volume_discount_tiers"]) == 3
        views.append({key: data[key] for key in PROGRAM_CONFIG_TUNABLES})
    assert all(view == views[0] for view in views), (
        "every role reads the same live generation of the rulebook"
    )


def test_partial_retunes_accumulate_and_a_rejected_retune_publishes_no_generation(
    api, admin_headers
):
    """Successive partial retunes stack, and a schema violation moves nothing.

    PRD §2.6: "every field is optional and an omitted field keeps the value of
    the current generation"
    PRD §2.6: "`max_age_days` is 2190 and must be at least 1"
    PRD §2.10: "Schema validity of the request body and query parameters:
    required fields present, enum members recognised, numbers in range"

    Design: Corner/endpoints/program_config_read_and_partial_update
    """
    seed = read_config(api, admin_headers)
    assert seed["version"] == 1
    untouched = [key for key in PROGRAM_CONFIG_TUNABLES if key not in _RETUNED_TUNABLES]

    first = retune_config(api, admin_headers, audit_sample_pct=0.5)
    assert first["audit_sample_pct"] == 0.5
    assert first["version"] == 2
    assert first["audit_sample_min_per_run"] == seed["audit_sample_min_per_run"]
    for tunable in untouched:
        assert first[tunable] == seed[tunable], (
            f"an omitted field keeps its current value, but {tunable} drifted"
        )

    second = retune_config(api, admin_headers, audit_sample_min_per_run=2)
    assert second["audit_sample_min_per_run"] == 2
    assert second["audit_sample_pct"] == 0.5, (
        "a later partial retune must not restore an earlier retune's field"
    )
    assert second["version"] == 3
    for tunable in untouched:
        assert second[tunable] == seed[tunable]

    rejected = api.update_program_config({"max_age_days": 0}, admin_headers)
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)

    after = read_config(api, admin_headers)
    assert after["version"] == 3, "a rejected retune publishes no new generation"
    assert after["max_age_days"] == seed["max_age_days"]
    assert after["audit_sample_pct"] == 0.5
    assert after["audit_sample_min_per_run"] == 2
    for tunable in untouched:
        assert after[tunable] == seed[tunable]


def test_the_repair_listing_pages_over_every_repair_an_inspection_generated(api):
    """Two pages cover the three repairs, and an out-of-range page size is refused.

    PRD §2.3: "`total_count` giving the number of rows matching the filter before
    pagination, and `has_more`, which is true when rows remain beyond the current
    page"
    PRD §2.3: "A `limit` outside the range from 1 through 100, or a negative
    `offset`, is a schema violation rejected with `ERR_INVALID_REQUEST` (HTTP
    400)"
    PRD §3.5: "the repair listing under an inspection, filterable by `status` and
    `severity` with `limit` and `offset`, is the only channel through which their
    identifiers are discovered"

    Design: Corner/endpoints/reconditioning_items_read_filters_paginates_and_reports_reimbursement
    """
    walk = _inspection_with_three_repairs(api)
    response = api.list_reconditioning_items(
        walk.inspection_id, AUDITOR, params={"limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(first_page) == 2
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_page, second_meta = validate_paginated(
        api.list_reconditioning_items(
            walk.inspection_id, AUDITOR, params={"limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    every_row = first_page + second_page
    assert sorted(row["item_code"] for row in every_row) == ["B1", "S1", "T1"]
    assert_created_at_ascending(every_row)
    for row in every_row:
        assert_reconditioning_item(row)
        assert row["inspection_id"] == walk.inspection_id

    refused = api.list_reconditioning_items(
        walk.inspection_id, AUDITOR, params={"limit": 101}
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST)


def test_repair_filters_intersect_and_each_row_carries_its_own_reimbursement(api):
    """The status and severity filters cut the same collection, count included.

    PRD §3.5: "take `actual_cost_cents`, multiply by the programme's
    reimbursement share (60 percent by default), round that product half up to
    whole cents, and then take the smaller of that rounded figure and the point's
    `max_reconditioning_cost_cents`"
    PRD §3.5: "A waived item keeps `actual_cost_cents` null and
    `reimbursable_cents` 0."
    PRD §3.5: "`total_recon_cost_cents` is the plain sum of `actual_cost_cents`
    over the inspection's repairs whose status is `COMPLETED`."

    Design: Corner/endpoints/reconditioning_items_read_filters_paginates_and_reports_reimbursement
    """
    walk = _inspection_with_three_repairs(api)
    waived, waived_meta = validate_paginated(
        api.list_reconditioning_items(
            walk.inspection_id, AUDITOR, params={"status": "WAIVED"}
        )
    )
    assert len(waived) == 1
    assert_pagination_meta(
        waived_meta, limit=DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )
    assert waived[0]["item_code"] == "T1"
    assert waived[0]["status"] == "WAIVED"
    assert waived[0]["actual_cost_cents"] is None
    assert waived[0]["reimbursable_cents"] == 0
    assert waived[0]["waiver_reason"] == "tyre wear within regional tolerance"

    empty, empty_meta = validate_paginated(
        api.list_reconditioning_items(
            walk.inspection_id,
            AUDITOR,
            params={"status": "COMPLETED", "severity": "CRITICAL"},
        )
    )
    assert empty == [], "the two filters intersect: the completed repair is MAJOR"
    assert_pagination_meta(
        empty_meta, limit=DEFAULT_LIMIT, offset=0, total_count=0, has_more=False
    )

    majors, major_meta = validate_paginated(
        api.list_reconditioning_items(
            walk.inspection_id, AUDITOR, params={"severity": "MAJOR"}
        )
    )
    assert sorted(row["item_code"] for row in majors) == ["B1", "T1"]
    assert_pagination_meta(
        major_meta, limit=DEFAULT_LIMIT, offset=0, total_count=2, has_more=False
    )

    brakes = reconditioning_item_for(api, walk.inspection_id, "B1")
    assert brakes["status"] == "COMPLETED"
    assert brakes["actual_cost_cents"] == 1001
    assert brakes["reimbursable_cents"] == 601
    assert brakes["reimbursable_cents"] == reimbursable_for(1001, 100000)
    assert brakes["closed_by_user_id"] == walk.program.other_technician_id
    assert_instant_equals(brakes["completed_at"], CLOCK_EPOCH, "completed_at")

    outstanding = reconditioning_item_for(api, walk.inspection_id, "S1")
    assert outstanding["status"] == "REQUIRED"
    assert outstanding["reimbursable_cents"] == 0

    inspection = read_inspection(api, walk.inspection_id)
    assert inspection["total_recon_cost_cents"] == 1001
    assert inspection["total_reimbursable_cents"] == 601


def test_a_contradicted_measurement_rejects_the_batch_without_consuming_an_attempt(
    api, program, open_walk
):
    """One bad row voids the whole batch and leaves the stored attempt intact.

    PRD §3.4: "A `PASS` with a reading outside the band, a `FAIL` with a reading
    inside it, or a measured point recorded with no reading at all is rejected
    with `ERR_MEASUREMENT_CONTRADICTS_OUTCOME`."
    PRD §3.4: "Instead it increments the inspection's `attempt_count` by exactly
    1 and then writes one result row per supplied entry"
    PRD §3.4: "Earlier attempts remain visible forever."

    Design: Corner/endpoints/results_batch_rejected_whole_on_a_single_bad_row
    """
    record_results(
        api, open_walk.inspection_id, program.technician_headers, clean_attempt_rows()
    )
    before = read_inspection(api, open_walk.inspection_id)
    assert before["attempt_count"] == 1
    assert before["recorded_item_count"] == 3
    assert before["status"] == "IN_PROGRESS"

    refused = api.record_results(
        open_walk.inspection_id,
        results_payload(
            [
                result_row("P1", "FAIL"),
                result_row("S1", "PASS"),
                result_row("B1", "FAIL", measured_value=11.0),
            ]
        ),
        program.technician_headers,
    )
    validate_error(refused, ApiErrorId.ERR_MEASUREMENT_CONTRADICTS_OUTCOME)

    after = read_inspection(api, open_walk.inspection_id)
    assert after["attempt_count"] == 1, "the refused batch opened no attempt"
    assert after["recorded_item_count"] == 3
    assert after["failed_critical_count"] == 0
    assert after["failed_recon_count"] == 0
    assert after["status"] == "IN_PROGRESS"
    assert after["version"] == before["version"], "a refused batch mutates nothing"

    stored, stored_meta = validate_paginated(
        api.list_results(open_walk.inspection_id, ADMIN, params={"attempt_index": 1})
    )
    assert len(stored) == 3
    assert stored_meta["total_count"] == 3
    assert {row["outcome"] for row in stored} == {"PASS"}, (
        "the refused batch did not overwrite the attempt already on file"
    )

    corrected = record_results(
        api,
        open_walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "FAIL"),
            result_row("S1", "PASS"),
            result_row("B1", "FAIL", measured_value=2.0),
        ],
    )
    assert corrected["attempt_count"] == 2, "the refused batch consumed no attempt index"
    assert corrected["recorded_item_count"] == 3
    assert corrected["failed_critical_count"] == 1
    assert corrected["failed_recon_count"] == 1
    assert corrected["status"] == "IN_PROGRESS"

    every_row, every_meta = validate_paginated(
        api.list_results(open_walk.inspection_id, ADMIN)
    )
    assert every_meta["total_count"] == 6
    assert len([row for row in every_row if row["attempt_index"] == 1]) == 3
    assert len([row for row in every_row if row["attempt_index"] == 2]) == 3


def test_a_complaint_is_readable_from_the_child_and_from_its_parent_collection(
    api, program
):
    """One filing is visible from the complaint itself and from its certification.

    PRD §3.11: "a derived `reinspection_deadline_at` equal to `filed_at` plus
    five days"
    PRD §3.11: "Complaints are readable through a per-certification listing that
    accepts `status` and `category` filters with `limit` and `offset`"
    PRD §2.7: "A vehicle may be `RETAIL_SOLD` while its `cpo_state` is still
    `NOT_CERTIFIED`, and its `cpo_state` may be `CERTIFIED` while an unrelated
    complaint sits open against it."

    Design: Corner/endpoints/complaint_links_certification_and_is_readable_from_both_ends
    """
    first, second = activate_many(api, program, 2)
    against_first = file_complaint(
        api,
        first.certification_id,
        category="MARKETING_MISREPRESENTATION",
        customer_reference="CUST-A",
    )
    against_second = file_complaint(
        api,
        second.certification_id,
        category="WARRANTY_DENIAL",
        customer_reference="CUST-B",
    )

    assert_complaint(against_first)
    assert against_first["certification_id"] == first.certification_id
    assert against_first["status"] == "OPEN"
    assert against_first["reinspection_ordered_at"] is None
    assert against_first["resolved_at"] is None
    assert_instant_equals(against_first["filed_at"], CLOCK_EPOCH, "filed_at")
    assert_instant_equals(
        against_first["reinspection_deadline_at"],
        iso_shift(CLOCK_EPOCH, days=REINSPECTION_DEADLINE_DAYS),
        "reinspection_deadline_at",
    )

    from_child = read_complaint(api, against_first["id"], program.dealer_headers)
    assert from_child["id"] == against_first["id"]
    assert from_child["certification_id"] == first.certification_id
    assert from_child["category"] == "MARKETING_MISREPRESENTATION"
    assert from_child["customer_reference"] == "CUST-A"

    owned, owned_meta = validate_paginated(
        api.list_complaints(first.certification_id, AUDITOR)
    )
    assert [row["id"] for row in owned] == [against_first["id"]], (
        "a sibling certification's complaint must not leak into this collection"
    )
    assert_pagination_meta(
        owned_meta, limit=DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )

    by_other_category, other_meta = validate_paginated(
        api.list_complaints(
            first.certification_id, AUDITOR, params={"category": "WARRANTY_DENIAL"}
        )
    )
    assert by_other_category == []
    assert_pagination_meta(
        other_meta, limit=DEFAULT_LIMIT, offset=0, total_count=0, has_more=False
    )

    still_open, open_meta = validate_paginated(
        api.list_complaints(first.certification_id, AUDITOR, params={"status": "OPEN"})
    )
    assert [row["id"] for row in still_open] == [against_first["id"]]
    assert open_meta["total_count"] == 1

    peer, peer_meta = validate_paginated(
        api.list_complaints(second.certification_id, AUDITOR)
    )
    assert [row["id"] for row in peer] == [against_second["id"]]
    assert peer_meta["total_count"] == 1

    assert read_certification(api, first.certification_id)["status"] == "ACTIVE"
    assert read_certification(api, second.certification_id)["status"] == "ACTIVE"
