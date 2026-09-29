"""Cross-cutting corners: the two optimistic-concurrency guards, the version ledger of an
ordinary walk, and filter-plus-pagination composition on the segment listing.

Two deviations from the design are recorded here.  The listing instance labels an
out-of-range `limit` a 422, but §2.4 and §5 both map `ERR_INVALID_REQUEST` to 400, so those
two legs are asserted at 400.  The same instance names individual rows by creation order;
because `created_at` is minted from the logical clock, twelve segments created at one
instant share a timestamp and the PRD pins no tie-break, so page contents are pinned
against a single full-page read taken in the same run instead.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_ascending, assert_pagination_meta, ids_of
from test_helpers.test_users import ANALYST_1, BILLING_1, INTAKE_1, PRIVACY_1


# --------------------------------------------------------------------------
# stale_expected_request_version_is_refused_ahead_of_every_business_check_rejected
# --------------------------------------------------------------------------
def _release_ready_request_of_25_pages(api):
    """A third-party request at RELEASE_READY whose 25 billable pages price to 2188."""
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(api, world, 25)
    return world, scenario["request_id"]


def test_the_version_one_behind_the_truth_is_refused_and_the_current_one_is_taken(api):
    """A value that was correct a moment ago is exactly what the guard exists to refuse.

    PRD: "If `expected_request_version` does not equal the request's current `version`, the creation is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_expected_request_version_is_refused_ahead_of_every_business_check_rejected
    """
    world, request_id = _release_ready_request_of_25_pages(api)
    version = fx.request_version(api, request_id)
    assert version > 1

    validate_error(
        api.create_invoice(f.invoice_payload(request_id, version - 1), BILLING_1),
        e.ERR_STALE_REQUEST_VERSION,
        412,
    )
    _, rejected = fx.list_invoices_for(api, request_id)
    assert rejected["total_count"] == 0
    assert fx.request_version(api, request_id) == version

    invoice = validate_success(
        api.create_invoice(f.invoice_payload(request_id, version), BILLING_1), 201
    )

    assert invoice["status"] == "DRAFT"
    assert invoice["amount_due_cents"] == 2188
    assert fx.request_version(api, request_id) == version + 1


def test_the_replayed_version_is_refused_ahead_of_the_already_exists_rule(api):
    """Priority 8 runs before priority 44, so the replay is stale rather than duplicated.

    PRD: "Validation is a single ordered pipeline, and the **first** violated rule determines the response; later violations are not reported."

    Design: Corner/cross-cutting complexity layers/stale_expected_request_version_is_refused_ahead_of_every_business_check_rejected
    """
    _, request_id = _release_ready_request_of_25_pages(api)
    version = fx.request_version(api, request_id)
    invoice = validate_success(
        api.create_invoice(f.invoice_payload(request_id, version), BILLING_1), 201
    )
    fx.issue_invoice(api, invoice["id"])

    data = validate_error(
        api.create_invoice(f.invoice_payload(request_id, version), BILLING_1),
        e.ERR_STALE_REQUEST_VERSION,
        412,
    )

    assert data["error_id"] != e.ERR_INVOICE_ALREADY_EXISTS
    assert fx.read_invoice(api, invoice["id"])["status"] == "ISSUED"


def test_exactly_one_invoice_and_one_ledger_entry_survive_the_five_calls(api):
    """Two refusals either side of two accepted writes post nothing at all.

    PRD: "Issuance sets `issued_at` to the current logical clock, moves the invoice to `ISSUED`, moves the request's `billing_status` from `PENDING_INVOICE` to `INVOICED`, adds the invoice's `amount_due_cents` to the facility's `receivable_cents`, and increments the invoice's `version` by 1."

    Design: Corner/cross-cutting complexity layers/stale_expected_request_version_is_refused_ahead_of_every_business_check_rejected
    """
    world, request_id = _release_ready_request_of_25_pages(api)
    version = fx.request_version(api, request_id)

    validate_error(
        api.create_invoice(f.invoice_payload(request_id, version - 1), BILLING_1),
        e.ERR_STALE_REQUEST_VERSION,
        412,
    )
    invoice = validate_success(
        api.create_invoice(f.invoice_payload(request_id, version), BILLING_1), 201
    )
    fx.issue_invoice(api, invoice["id"])
    validate_error(
        api.create_invoice(f.invoice_payload(request_id, version), BILLING_1),
        e.ERR_STALE_REQUEST_VERSION,
        412,
    )

    rows, meta = fx.list_invoices_for(api, request_id)
    assert meta["total_count"] == 1
    assert ids_of(rows) == [invoice["id"]]
    assert rows[0]["status"] == "ISSUED"
    assert fx.read_facility(api, world["facility_id"])["receivable_cents"] == 2188


# --------------------------------------------------------------------------
# stale_expected_patient_version_on_authorization_create_rejected
# --------------------------------------------------------------------------
def _patient_with_two_waiting_attorneys(api):
    """One patient at its initial version and two attorneys about to be authorized."""
    world = fx.base_world(api)
    return {
        "world": world,
        "patient_id": world["patient_id"],
        "attorney_a": fx.make_attorney(api)["id"],
        "attorney_b": fx.make_attorney(api)["id"],
        "pinned": fx.patient_version(api, world["patient_id"]),
    }


def test_a_foreign_authorization_invalidates_a_pin_the_other_writer_still_holds(api):
    """The pinned entity is the patient, so B's untouched paperwork is stale all the same.

    PRD: "An authorization creation request must carry `expected_patient_version`, a non-optional integer field holding the client's last observed `version` of the `Patient` named by `patient_id`."

    Design: Corner/cross-cutting complexity layers/stale_expected_patient_version_on_authorization_create_rejected
    """
    scenario = _patient_with_two_waiting_attorneys(api)
    patient_id, pinned = scenario["patient_id"], scenario["pinned"]

    first = validate_success(
        api.create_authorization(
            f.authorization_payload(patient_id, scenario["attorney_a"], pinned), INTAKE_1
        ),
        201,
    )
    assert first["status"] == "VALID"
    assert fx.patient_version(api, patient_id) == pinned + 1

    validate_error(
        api.create_authorization(
            f.authorization_payload(patient_id, scenario["attorney_b"], pinned), INTAKE_1
        ),
        e.ERR_STALE_PATIENT_VERSION,
        412,
    )


def test_the_stale_pin_is_reported_ahead_of_the_window_overlap_rule(api):
    """Priority 8 precedes priority 30, so an overlapping window never gets examined.

    PRD: "If `expected_patient_version` does not equal that patient's current `version`, the creation is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_expected_patient_version_on_authorization_create_rejected
    """
    scenario = _patient_with_two_waiting_attorneys(api)
    patient_id, pinned = scenario["patient_id"], scenario["pinned"]
    validate_success(
        api.create_authorization(
            f.authorization_payload(patient_id, scenario["attorney_a"], pinned), INTAKE_1
        ),
        201,
    )

    data = validate_error(
        api.create_authorization(
            f.authorization_payload(patient_id, scenario["attorney_a"], pinned), INTAKE_1
        ),
        e.ERR_STALE_PATIENT_VERSION,
        412,
    )

    assert data["error_id"] != e.ERR_AUTHORIZATION_WINDOW_OVERLAP
    assert fx.patient_version(api, patient_id) == pinned + 1


def test_the_refreshed_pin_is_accepted_and_the_two_refusals_wrote_nothing(api):
    """Only accepted creations move the patient, and only they leave rows behind.

    PRD: "A successful authorization creation increments the patient's `version` by 1, which is what makes the guard bite: a new authorization carrying `supersedes_authorization_id` retires the named predecessor and is exempt from the coverage-window overlap check, so a specialist who has not observed the patient's changed authorization set would otherwise retire an authorization it never saw."

    Design: Corner/cross-cutting complexity layers/stale_expected_patient_version_on_authorization_create_rejected
    """
    scenario = _patient_with_two_waiting_attorneys(api)
    patient_id, pinned = scenario["patient_id"], scenario["pinned"]
    validate_success(
        api.create_authorization(
            f.authorization_payload(patient_id, scenario["attorney_a"], pinned), INTAKE_1
        ),
        201,
    )
    for requester_id in (scenario["attorney_b"], scenario["attorney_a"]):
        validate_error(
            api.create_authorization(
                f.authorization_payload(patient_id, requester_id, pinned), INTAKE_1
            ),
            e.ERR_STALE_PATIENT_VERSION,
            412,
        )
    refreshed = fx.patient_version(api, patient_id)
    assert refreshed == pinned + 1

    second = validate_success(
        api.create_authorization(
            f.authorization_payload(patient_id, scenario["attorney_b"], refreshed), INTAKE_1
        ),
        201,
    )

    assert second["status"] == "VALID"
    assert fx.patient_version(api, patient_id) == refreshed + 1
    _, meta = validate_paginated(
        api.list_authorizations(PRIVACY_1, {"patient_id": patient_id, "limit": 10})
    )
    assert meta["total_count"] == 2


# --------------------------------------------------------------------------
# version_advances_by_exactly_one_per_accepted_parent_write_and_never_on_reads
# --------------------------------------------------------------------------
def _accepted_request_in_compilation(api):
    """One accepted third-party request with no segments yet."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])
    return world, request["id"]


def test_repeated_reads_and_a_pending_segment_creation_leave_the_parent_alone(api):
    """Two GETs and one child creation, and the request's counters never move.

    PRD: "Most resources also carry three further common properties: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted; `updated_at`, the same format, refreshed on every mutation of that resource; and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource."

    Design: Corner/cross-cutting complexity layers/version_advances_by_exactly_one_per_accepted_parent_write_and_never_on_reads
    """
    _, request_id = _accepted_request_in_compilation(api)
    first_read = fx.read_request(api, request_id)
    second_read = fx.read_request(api, request_id)
    assert second_read["version"] == first_read["version"]
    assert second_read["updated_at"] == first_read["updated_at"]

    segment = validate_success(
        api.create_record_segment(
            f.record_segment_payload(request_id, "GENERAL_MEDICAL", "EHR_CURRENT"), ANALYST_1
        ),
        201,
    )

    assert segment["version"] == 1
    assert segment["retrieval_status"] == "PENDING"
    assert segment["sensitivity_status"] == "UNCLASSIFIED"
    assert segment["page_count"] == 0
    after_create = fx.read_request(api, request_id)
    assert after_create["version"] == first_read["version"]
    assert after_create["updated_at"] == first_read["updated_at"]
    assert after_create["page_count_total"] == 0


def test_the_disposition_advances_parent_and_child_by_exactly_one_each(api):
    """Two counters move together but independently, one step each.

    PRD: "This guard exists because pricing reads `billable_page_count` and `penalty_exposure_cents`, and every segment disposition, redaction approval, denial overturn and extension notice moves the request's `version`."

    Design: Corner/cross-cutting complexity layers/version_advances_by_exactly_one_per_accepted_parent_write_and_never_on_reads
    """
    _, request_id = _accepted_request_in_compilation(api)
    segment = validate_success(
        api.create_record_segment(
            f.record_segment_payload(request_id, "GENERAL_MEDICAL", "EHR_CURRENT"), ANALYST_1
        ),
        201,
    )
    before = fx.read_request(api, request_id)

    retrieved = validate_success(
        api.segment_disposition(segment["id"], f.retrieved_payload(40), ANALYST_1), 200
    )

    assert retrieved["version"] == segment["version"] + 1
    assert retrieved["retrieval_status"] == "RETRIEVED"
    after = fx.read_request(api, request_id)
    assert after["version"] == before["version"] + 1
    assert after["page_count_total"] == 40


def test_the_rejected_second_completion_leaves_both_counters_untouched(api):
    """Exactly one of the two identical completion calls counted.

    PRD: "On success all four page-ledger fields and both penalty measures are re-derived and the request's `version` increments by 1."

    Design: Corner/cross-cutting complexity layers/version_advances_by_exactly_one_per_accepted_parent_write_and_never_on_reads
    """
    _, request_id = _accepted_request_in_compilation(api)
    fx.add_retrieved_segment(api, request_id, 40)
    before = fx.read_request(api, request_id)

    accepted = validate_success(api.complete_compilation(request_id, {}, ANALYST_1), 200)
    assert accepted["fulfillment_status"] == "SENSITIVE_REVIEW"
    assert accepted["version"] == before["version"] + 1

    validate_error(
        api.complete_compilation(request_id, {}, ANALYST_1), e.ERR_REQUEST_STATE_INVALID, 409
    )

    after = fx.read_request(api, request_id)
    assert after["version"] == before["version"] + 1
    assert after["updated_at"] == accepted["updated_at"]
    assert after["fulfillment_status"] == "SENSITIVE_REVIEW"


# --------------------------------------------------------------------------
# record_segment_listing_composes_filter_with_pagination_and_bounds
# --------------------------------------------------------------------------
def _twelve_segments_split_across_two_source_systems(api):
    """Eight EHR_CURRENT and four IMAGING_PACS segments, all still PENDING."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])
    for source_system, count in (("EHR_CURRENT", 8), ("IMAGING_PACS", 4)):
        for _ in range(count):
            get_success_data(
                api.create_record_segment(
                    f.record_segment_payload(request["id"], "GENERAL_MEDICAL", source_system),
                    ANALYST_1,
                )
            )
    return world, request["id"]


def _page(api, request_id, **params):
    query = {"request_id": request_id}
    query.update(params)
    return validate_paginated(api.list_record_segments(ANALYST_1, query))


def test_the_default_page_and_the_last_page_partition_the_twelve_rows(api):
    """The default page size is 10, and has_more is false exactly on the last page.

    PRD: "For list responses the `meta` object carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filter before pagination), and `has_more` (true when rows remain beyond this page)."

    Design: Corner/cross-cutting complexity layers/record_segment_listing_composes_filter_with_pagination_and_bounds
    """
    _, request_id = _twelve_segments_split_across_two_source_systems(api)
    everything, whole_meta = _page(api, request_id, limit=100)
    assert whole_meta["limit"] == 100
    assert whole_meta["offset"] == 0
    assert_pagination_meta(whole_meta, total_count=12, has_more=False)
    assert len(everything) == 12
    assert_ascending([row["created_at"] for row in everything])

    response = api.list_record_segments(ANALYST_1, {"request_id": request_id})
    first_rows, first_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert first_meta["limit"] == 10
    assert first_meta["offset"] == 0
    assert_pagination_meta(first_meta, total_count=12, has_more=True)
    assert ids_of(first_rows) == ids_of(everything[:10])

    tail_rows, tail_meta = _page(api, request_id, limit=5, offset=10)
    assert tail_meta["limit"] == 5
    assert tail_meta["offset"] == 10
    assert_pagination_meta(tail_meta, total_count=12, has_more=False)
    assert ids_of(tail_rows) == ids_of(everything[10:])
    assert tail_rows[-1]["id"] == everything[11]["id"]


def test_the_total_count_reports_the_filtered_set_and_never_a_not_found(api):
    """A filter narrows total_count itself, and running off the end is an empty 200.

    PRD: "Segments are readable individually — showing all three of their state dimensions at once — and listable with optional `request_id`, `source_system`, `category` and `sensitivity_status` filters."

    Design: Corner/cross-cutting complexity layers/record_segment_listing_composes_filter_with_pagination_and_bounds
    """
    _, request_id = _twelve_segments_split_across_two_source_systems(api)
    imaging_all, imaging_meta = _page(api, request_id, source_system="IMAGING_PACS", limit=100)
    assert_pagination_meta(imaging_meta, total_count=4, has_more=False)

    imaging_page, page_meta = _page(api, request_id, source_system="IMAGING_PACS", limit=3)
    assert_pagination_meta(page_meta, total_count=4, has_more=True)
    assert page_meta["total_count"] != 12
    assert ids_of(imaging_page) == ids_of(imaging_all[:3])

    past_end, past_meta = _page(api, request_id, offset=12)
    assert past_end == []
    assert_pagination_meta(past_meta, total_count=12, has_more=False)

    unmatched, unmatched_meta = _page(api, request_id, sensitivity_status="AUTHORIZED_INCLUDE")
    assert unmatched == []
    assert_pagination_meta(unmatched_meta, total_count=0, has_more=False)


def test_the_declared_limit_bounds_are_enforced_at_both_ends(api):
    """1 and 100 are inside the bound; 0 and 101 are schema violations.

    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/cross-cutting complexity layers/record_segment_listing_composes_filter_with_pagination_and_bounds
    """
    _, request_id = _twelve_segments_split_across_two_source_systems(api)

    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        query = {"request_id": request_id}
        query.update(bad)
        validate_error(
            api.list_record_segments(ANALYST_1, query), e.ERR_INVALID_REQUEST, 400
        )

    rows, meta = _page(api, request_id, limit=100)
    assert len(rows) == 12
    assert_pagination_meta(meta, total_count=12, has_more=False)
    single, single_meta = _page(api, request_id, limit=1)
    assert len(single) == 1
    assert_pagination_meta(single_meta, total_count=12, has_more=True)
