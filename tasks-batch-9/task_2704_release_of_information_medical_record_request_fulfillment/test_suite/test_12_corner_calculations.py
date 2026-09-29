"""Calculation corners: the page-ledger input population, the cap boundary, line-set
membership, configuration-driven classification and the facility penalty roll-up."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    Instant,
    assert_line,
    assert_line_sequence_contiguous,
    assert_no_line_type,
    assert_page_ledger,
)
from test_helpers.constants import DEFAULT_SENSITIVE_CATEGORIES
from test_helpers.test_users import ANALYST_1, INTAKE_1, PLATFORM_ADMIN


# --------------------------------------------------------------------------
# page_ledger_input_set_excludes_pending_unavailable_and_withdrawn
# --------------------------------------------------------------------------
def _five_segment_request_in_compilation(api):
    """40 + 15 general-medical pages retrieved, 22 behavioural-health pages segregated, and
    two segments left PENDING."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"]
    )
    fx.accept_request(api, request["id"])
    ids = fx.build_segments(
        api,
        request["id"],
        [
            {"label": "a", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "b", "category": "GENERAL_MEDICAL", "page_count": 15},
            {"label": "d", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
            {
                "label": "c",
                "category": "GENERAL_MEDICAL",
                "page_count": 0,
                "source_system": "IMAGING_PACS",
                "disposition": "PENDING",
            },
            {
                "label": "e",
                "category": "GENERAL_MEDICAL",
                "page_count": 0,
                "source_system": "SCANNED_PAPER",
                "disposition": "PENDING",
            },
        ],
    )
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def test_pending_and_segregated_pages_leave_the_ledger_for_different_reasons(api):
    """77 gross against 55 billable: PENDING contributes nothing, segregation is not releasable.

    PRD: "Four fields on the request summarise the compiled set, all defaulting to 0, all re-derived on every segment write and on every `fulfillment_status` transition, and all computed over the same input population: the segments of this request whose `retrieval_status` is `RETRIEVED`."

    Design: Corner/calculations/page_ledger_input_set_excludes_pending_unavailable_and_withdrawn
    """
    scenario = _five_segment_request_in_compilation(api)

    request = fx.read_request(api, scenario["request_id"])

    assert_page_ledger(request, total=77, billable=55, withheld=0, redacted=0)
    assert request["page_count_total"] - request["billable_page_count"] == 22
    assert fx.read_segment(api, scenario["segment_ids"]["c"])["retrieval_status"] == "PENDING"
    assert fx.read_segment(api, scenario["segment_ids"]["d"])["sensitivity_status"] == (
        "SEGREGATED_PENDING_REVIEW"
    )


def test_withdrawal_and_unavailability_shrink_the_gross_total_the_withhold_does_not(api):
    """WITHDRAWN and UNAVAILABLE leave every aggregate; WITHHELD only moves between buckets.

    PRD: "Segments that are still `PENDING`, or that ended `UNAVAILABLE` or `WITHDRAWN`, appear in no aggregate."

    Design: Corner/calculations/page_ledger_input_set_excludes_pending_unavailable_and_withdrawn
    """
    scenario = _five_segment_request_in_compilation(api)
    ids = scenario["segment_ids"]

    get_success_data(api.segment_disposition(ids["b"], f.withdrawn_payload(), ANALYST_1))
    for label in ("c", "e"):
        get_success_data(
            api.segment_disposition(
                ids[label], f.unavailable_payload("chart destroyed"), ANALYST_1
            )
        )

    checkpoint_2 = fx.read_request(api, scenario["request_id"])
    assert_page_ledger(checkpoint_2, total=62, billable=40, withheld=0, redacted=0)
    assert fx.read_segment(api, ids["b"])["page_count"] == 15
    assert fx.read_segment(api, ids["c"])["page_count"] == 0

    fx.complete_compilation(api, scenario["request_id"])
    fx.run_sensitive_review(api, scenario["request_id"], [f.withhold_decision(ids["d"])])

    checkpoint_3 = fx.read_request(api, scenario["request_id"])
    assert_page_ledger(checkpoint_3, total=62, billable=40, withheld=22, redacted=0)
    assert checkpoint_3["fulfillment_status"] == "RELEASE_READY"


# --------------------------------------------------------------------------
# subtotal_exactly_at_electronic_cap_emits_no_adjustment_line
# --------------------------------------------------------------------------
def test_a_subtotal_exactly_at_the_electronic_cap_emits_no_adjustment(api):
    """650 flat-rate pages price to precisely 6500 cents; the cap bites only on strict excess.

    PRD: "The boundary is strict: a `subtotal_cents` exactly equal to `applicable_cap_cents` leaves `cap_adjustment_cents` at 0 and emits no adjustment line, because the cap bites only on strict excess."

    Design: Corner/calculations/subtotal_exactly_at_electronic_cap_emits_no_adjustment_line
    """
    world = fx.patient_access_world(api)
    scenario = fx.simple_patient_access_request_at_release_ready(api, world, 650)
    request = fx.read_request(api, scenario["request_id"])
    assert request["billable_page_count"] == 650
    assert request["statutory_due_at"] == Instant("2026-08-16T00:00:00Z")

    invoice = fx.create_invoice(api, scenario["request_id"])

    assert invoice["variant"] == "PATIENT_ACCESS_COST_BASED"
    assert invoice["billable_page_count_snapshot"] == 650
    assert invoice["subtotal_cents"] == 6500
    assert invoice["applicable_cap_cents"] == 6500
    assert invoice["applicable_cap_cents"] != 12000
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["gross_total_cents"] == 6500
    assert invoice["penalty_snapshot_cents"] == 0
    assert invoice["forfeiture_cents"] == 0
    assert invoice["amount_due_cents"] == 6500

    lines, meta = fx.list_lines_of(api, invoice["id"])
    assert meta["total_count"] == 1
    assert_line(lines[0], "PER_PAGE_FLAT", 650, 10000, 6500)
    assert_no_line_type(lines, "CAP_ADJUSTMENT")
    assert_no_line_type(lines, "LATE_FEE_FORFEITURE")

    _, event_meta = fx.list_events_of(
        api, scenario["request_id"], event_type="FEE_CAP_APPLIED"
    )
    assert event_meta["total_count"] == 0


# --------------------------------------------------------------------------
# electronic_delivery_omits_media_postage_and_empty_tier_lines
# --------------------------------------------------------------------------
def test_four_of_the_seven_retail_line_types_are_absent_for_four_reasons(api):
    """Omitted line types leave no gap: the three survivors renumber 1, 2, 3.

    PRD: "The `sequence` field is 1-based over the **emitted** lines only, assigned contiguously from 1 upward in the pinned order, so an omitted line type leaves no gap; `sequence` is the sole ordering key for reading lines back."

    Design: Corner/calculations/electronic_delivery_omits_media_postage_and_empty_tier_lines
    """
    world = fx.third_party_world(api)
    assert fx.read_facility(api, world["facility_id"])["legacy_retrieval_surcharge_cents"] == 2000
    scenario = fx.simple_third_party_request_at_release_ready(
        api, world, 25, delivery_format="SECURE_PORTAL", certification_requested=True
    )

    invoice = fx.create_invoice(api, scenario["request_id"])
    lines, meta = fx.list_lines_of(api, invoice["id"])

    assert meta["total_count"] == 3
    assert_line_sequence_contiguous(lines)
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "CERTIFICATION", 1, 1000000, 1000)
    assert lines[2]["sequence"] == 3
    for absent in ("PER_PAGE_TIER2", "LEGACY_RETRIEVAL", "MEDIA", "POSTAGE"):
        assert_no_line_type(lines, absent)
    assert invoice["subtotal_cents"] == 3188
    assert invoice["amount_due_cents"] == 3188
    assert invoice["forfeiture_cents"] == 0


# --------------------------------------------------------------------------
# segment_sensitivity_follows_facility_configured_category_list
# --------------------------------------------------------------------------
def _facility_scenario(api, fee_rule_id, categories, **facility_overrides):
    """One facility under a shared fee rule, with a patient, an attorney and an authorization
    covering the given categories."""
    facility = fx.make_facility(api, fee_rule_id, **facility_overrides)
    patient = fx.make_patient(api, facility["id"])
    attorney = fx.make_attorney(api)
    authorization = fx.make_authorization(
        api, patient["id"], attorney["id"], scope_categories=list(categories)
    )
    request = get_success_data(
        api.create_request(
            f.third_party_request_payload(
                facility["id"],
                patient["id"],
                attorney["id"],
                authorization["id"],
                requested_categories=list(categories),
            ),
            INTAKE_1,
        )
    )
    fx.accept_request(api, request["id"])
    return {"facility": facility, "request_id": request["id"]}


def test_the_same_category_classifies_oppositely_under_two_facility_lists(api):
    """The classifier reads the facility's configured list, not a hard-coded category set.

    PRD: "A `disposition` of `RETRIEVED` moves the segment's `retrieval_status` from `PENDING` to `RETRIEVED`; it requires that the parent request's `fulfillment_status` be `COMPILATION` and that `page_count` be supplied as zero or greater. It sets `retrieved_at` to the current logical clock and classifies the segment's `sensitivity_status`: the segment's `category` is tested for membership in the governing facility's `sensitive_categories_requiring_specific_authorization` list, and the `sensitivity_status` becomes `SEGREGATED_PENDING_REVIEW` when the category is in that list and `NOT_SENSITIVE` when it is not."

    Design: Corner/calculations/segment_sensitivity_follows_facility_configured_category_list
    """
    fx.set_clock(api)
    fee_rule = fx.make_fee_rule(api)
    narrow = _facility_scenario(
        api,
        fee_rule["id"],
        ["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
        sensitive_categories_requiring_specific_authorization=["HIV"],
    )
    default = _facility_scenario(api, fee_rule["id"], ["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"])
    assert default["facility"]["sensitive_categories_requiring_specific_authorization"] == (
        DEFAULT_SENSITIVE_CATEGORIES
    )

    narrow_ids = fx.build_segments(
        api,
        narrow["request_id"],
        [
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 30},
            {"label": "hiv", "category": "HIV", "page_count": 12},
        ],
    )
    default_ids = fx.build_segments(
        api,
        default["request_id"],
        [{"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 30}],
    )

    assert fx.read_segment(api, narrow_ids["bh"])["sensitivity_status"] == "NOT_SENSITIVE"
    assert fx.read_segment(api, narrow_ids["hiv"])["sensitivity_status"] == (
        "SEGREGATED_PENDING_REVIEW"
    )
    assert fx.read_segment(api, default_ids["bh"])["sensitivity_status"] == (
        "SEGREGATED_PENDING_REVIEW"
    )

    narrow_request = fx.read_request(api, narrow["request_id"])
    assert_page_ledger(narrow_request, total=42, billable=30, withheld=0, redacted=0)
    default_request = fx.read_request(api, default["request_id"])
    assert_page_ledger(default_request, total=30, billable=0, withheld=0, redacted=0)


# --------------------------------------------------------------------------
# facility_penalty_exposure_aggregates_and_honours_the_per_request_cap
# --------------------------------------------------------------------------
def _two_open_requests_on_one_facility(api):
    """A patient-access request due 2026-08-16 and a third-party request due 2026-08-31, both
    left open on the same facility so their lateness keeps growing."""
    fx.set_clock(api)
    fee_rule = fx.make_fee_rule(api)
    facility = fx.make_facility(api, fee_rule["id"])
    patient = fx.make_patient(api, facility["id"])
    patient_requester = fx.make_patient_requester(api, patient["id"])
    attorney = fx.make_attorney(api)
    authorization = fx.make_authorization(api, patient["id"], attorney["id"])

    patient_request = get_success_data(
        api.create_request(
            f.patient_access_request_payload(
                facility["id"], patient["id"], patient_requester["id"]
            ),
            INTAKE_1,
        )
    )
    third_party_request = get_success_data(
        api.create_request(
            f.third_party_request_payload(
                facility["id"], patient["id"], attorney["id"], authorization["id"]
            ),
            INTAKE_1,
        )
    )
    assert patient_request["statutory_due_at"] == Instant("2026-08-16T00:00:00Z")
    assert third_party_request["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    return {
        "facility_id": facility["id"],
        "patient_request_id": patient_request["id"],
        "third_party_request_id": third_party_request["id"],
    }


def test_the_first_sweep_rolls_up_only_the_request_that_is_actually_late(api):
    """Five days past the 15-day deadline is 12500 strict and 7500 after the two-day grace.

    PRD: "When the effective completion instant is strictly later than `statutory_due_at`, the statutory measure, reported as `penalty_exposure_cents`, counts raw elapsed time with no grace: take the seconds between `statutory_due_at` and the effective completion instant, divide by 86400 seconds per day, and round the quotient **up** to the next whole day to obtain the strict days-late figure; multiply that figure by the fee rule's `penalty_per_day_cents`; and take the smaller of that product and the rule's `penalty_cap_cents`."

    Design: Corner/calculations/facility_penalty_exposure_aggregates_and_honours_the_per_request_cap
    """
    scenario = _two_open_requests_on_one_facility(api)
    fx.set_clock(api, "2026-08-21T00:00:00Z")

    sweep = validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    assert scenario["patient_request_id"] in sweep["breached_request_ids"]
    assert scenario["third_party_request_id"] not in sweep["breached_request_ids"]

    late = fx.read_request(api, scenario["patient_request_id"])
    assert late["penalty_exposure_cents"] == 12500
    assert late["safe_harbor_penalty_cents"] == 7500
    on_time = fx.read_request(api, scenario["third_party_request_id"])
    assert on_time["penalty_exposure_cents"] == 0
    assert on_time["safe_harbor_penalty_cents"] == 0
    assert fx.read_facility(api, scenario["facility_id"])["penalty_exposure_cents"] == 12500

    turnaround = validate_success(
        api.get_turnaround(scenario["patient_request_id"], PLATFORM_ADMIN), 200
    )
    assert turnaround["breached"] is True
    assert turnaround["days_late_strict"] == 5
    assert turnaround["days_late_business"] == 5
    assert turnaround["chargeable_days"] == 3


def test_the_facility_roll_up_sums_post_cap_figures_and_is_not_itself_clamped(api):
    """25000 + 12500 == 37500 on a facility whose per-request ceiling is 25000.

    PRD: "The fourth field, `penalty_exposure_cents` on the facility, is the sum of `penalty_exposure_cents` over every request whose `facility_id` names this facility, and it is refreshed whenever any request's penalty exposure moves."

    Design: Corner/calculations/facility_penalty_exposure_aggregates_and_honours_the_per_request_cap
    """
    scenario = _two_open_requests_on_one_facility(api)
    fx.set_clock(api, "2026-08-21T00:00:00Z")
    validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    fx.set_clock(api, "2026-09-05T00:00:00Z")
    sweep = validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    assert scenario["patient_request_id"] in sweep["breached_request_ids"]
    assert scenario["third_party_request_id"] in sweep["breached_request_ids"]

    capped = fx.read_request(api, scenario["patient_request_id"])
    assert capped["penalty_exposure_cents"] == 25000
    uncapped = fx.read_request(api, scenario["third_party_request_id"])
    assert uncapped["penalty_exposure_cents"] == 12500
    assert uncapped["safe_harbor_penalty_cents"] == 5000

    facility = fx.read_facility(api, scenario["facility_id"])
    assert facility["penalty_exposure_cents"] == 37500
    assert facility["penalty_exposure_cents"] != 25000
