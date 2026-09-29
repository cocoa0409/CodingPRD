"""Endpoint corners: the non-persisting computed read, cross-request references in a bulk
decision list, the sweep's report shape, the suspension gate and the single extension."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_ascending, assert_event_count, event_types
from test_helpers.test_users import INTAKE_1, PLATFORM_ADMIN, REVIEWER_1

TURNAROUND_FIELDS = (
    "statutory_due_at",
    "effective_completion_at",
    "tolled_seconds",
    "extension_applied",
    "breached",
    "days_late_strict",
    "days_late_business",
    "chargeable_days",
    "penalty_exposure_cents",
    "safe_harbor_penalty_cents",
)


# --------------------------------------------------------------------------
# turnaround_computed_read_recomputes_without_persisting
# --------------------------------------------------------------------------
def _accepted_patient_access_request(api):
    """One patient right-of-access request accepted at 2026-08-01, so it is due 2026-08-16 and
    left open thereafter."""
    world = fx.patient_access_world(api)
    request = fx.open_patient_access_request(api, world)
    fx.accept_request(api, request["id"])
    return world, request["id"]


def test_the_turnaround_read_reports_all_ten_declared_fields_at_zero_before_the_deadline(api):
    """Fifteen days ahead of the deadline every measure is 0 and nothing is breached.

    PRD: "A non-persisting computed read exposes the whole calculation for one request: it returns `statutory_due_at`, `effective_completion_at`, `tolled_seconds`, `extension_applied`, a `breached` boolean that is true exactly when the effective completion instant is strictly later than `statutory_due_at`, `days_late_strict`, `days_late_business`, `chargeable_days`, `penalty_exposure_cents` and `safe_harbor_penalty_cents`."

    Design: Corner/endpoints/turnaround_computed_read_recomputes_without_persisting
    """
    _, request_id = _accepted_patient_access_request(api)

    read = validate_success(api.get_turnaround(request_id, PLATFORM_ADMIN), 200)

    for field in TURNAROUND_FIELDS:
        assert field in read, f"turnaround read is missing {field}"
    assert read["statutory_due_at"] == Instant("2026-08-16T00:00:00Z")
    assert read["effective_completion_at"] == Instant("2026-08-01T00:00:00Z")
    assert read["tolled_seconds"] == 0
    assert read["extension_applied"] is False
    assert read["breached"] is False
    assert read["days_late_strict"] == 0
    assert read["days_late_business"] == 0
    assert read["chargeable_days"] == 0
    assert read["penalty_exposure_cents"] == 0
    assert read["safe_harbor_penalty_cents"] == 0


def test_the_computed_read_knows_a_lateness_the_stored_request_has_not_learned(api):
    """A bare clock advance is not a recompute trigger, so the read and the record disagree.

    PRD: "It writes nothing and moves no `version`."

    Design: Corner/endpoints/turnaround_computed_read_recomputes_without_persisting
    """
    world, request_id = _accepted_patient_access_request(api)
    stored_before = fx.read_request(api, request_id)
    fx.set_clock(api, "2026-08-21T00:00:00Z")

    read = validate_success(api.get_turnaround(request_id, PLATFORM_ADMIN), 200)

    assert read["breached"] is True
    assert read["effective_completion_at"] == Instant("2026-08-21T00:00:00Z")
    assert read["days_late_strict"] == 5
    assert read["days_late_business"] == 5
    assert read["chargeable_days"] == 3
    assert read["penalty_exposure_cents"] == 12500
    assert read["safe_harbor_penalty_cents"] == 7500
    assert read["tolled_seconds"] == 0
    assert read["extension_applied"] is False

    stored = fx.read_request(api, request_id)
    assert stored["penalty_exposure_cents"] == 0
    assert stored["safe_harbor_penalty_cents"] == 0
    assert stored["version"] == stored_before["version"]
    assert fx.read_facility(api, world["facility_id"])["penalty_exposure_cents"] == 0
    _, meta = fx.list_events_of(api, request_id)
    assert meta["total_count"] == 0


def test_only_the_sweep_publishes_the_figures_the_read_had_already_computed(api):
    """The sweep changes what is stored, not what is computed: the read is unmoved.

    PRD: "Both measures are re-derived on every `fulfillment_status` transition, at the first step of invoice creation, during the compliance sweep, and when the statutory extension is noticed."

    Design: Corner/endpoints/turnaround_computed_read_recomputes_without_persisting
    """
    world, request_id = _accepted_patient_access_request(api)
    fx.set_clock(api, "2026-08-21T00:00:00Z")
    read_before_sweep = validate_success(api.get_turnaround(request_id, PLATFORM_ADMIN), 200)

    validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    stored = fx.read_request(api, request_id)
    assert stored["penalty_exposure_cents"] == 12500
    assert stored["safe_harbor_penalty_cents"] == 7500
    assert fx.read_facility(api, world["facility_id"])["penalty_exposure_cents"] == 12500

    read_after_sweep = validate_success(api.get_turnaround(request_id, PLATFORM_ADMIN), 200)
    assert read_after_sweep == read_before_sweep


# --------------------------------------------------------------------------
# sensitive_review_naming_a_segment_of_another_request_not_found
# --------------------------------------------------------------------------
def _two_sibling_requests_in_sensitive_review(api):
    """Two requests of the same patient, requester and facility over different date ranges, each
    holding one 20-page behavioural-health segment awaiting review."""
    world = fx.third_party_world(
        api,
        scope_categories=["BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    first = fx.open_third_party_request(
        api,
        world,
        requested_categories=["BEHAVIORAL_HEALTH"],
        date_range_start="2023-01-01",
        date_range_end="2023-12-31",
    )
    second = fx.open_third_party_request(
        api,
        world,
        requested_categories=["BEHAVIORAL_HEALTH"],
        date_range_start="2024-01-01",
        date_range_end="2024-12-31",
    )
    specs = [{"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 20}]
    own = fx.walk_to_sensitive_review(api, first["id"], specs)
    sibling = fx.walk_to_sensitive_review(api, second["id"], specs)
    return {
        "first_id": first["id"],
        "second_id": second["id"],
        "own_segment_id": own["bh"],
        "sibling_segment_id": sibling["bh"],
    }


def test_a_sibling_requests_segment_is_a_not_found_rather_than_a_completeness_error(api):
    """Position 7 answers ahead of the completeness rule, alone or alongside the right segment.

    PRD: "A `record_segment_id` naming a segment that belongs to a different request reports `ERR_SEGMENT_NOT_FOUND` instead."

    Design: Corner/endpoints/sensitive_review_naming_a_segment_of_another_request_not_found
    """
    scenario = _two_sibling_requests_in_sensitive_review(api)
    first_before = fx.read_request(api, scenario["first_id"])
    second_before = fx.read_request(api, scenario["second_id"])

    validate_error(
        api.sensitive_review(
            scenario["first_id"],
            f.sensitive_review_payload([f.include_decision(scenario["sibling_segment_id"])]),
            REVIEWER_1,
        ),
        e.ERR_SEGMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.sensitive_review(
            scenario["first_id"],
            f.sensitive_review_payload(
                [
                    f.include_decision(scenario["own_segment_id"]),
                    f.include_decision(scenario["sibling_segment_id"]),
                ]
            ),
            REVIEWER_1,
        ),
        e.ERR_SEGMENT_NOT_FOUND,
        404,
    )

    for segment_id in (scenario["own_segment_id"], scenario["sibling_segment_id"]):
        assert fx.read_segment(api, segment_id)["sensitivity_status"] == (
            "SEGREGATED_PENDING_REVIEW"
        )
    assert fx.read_request(api, scenario["first_id"])["version"] == first_before["version"]
    assert fx.read_request(api, scenario["second_id"])["version"] == second_before["version"]


def test_the_sibling_request_is_untouched_by_the_pass_that_finally_succeeds(api):
    """Deciding one request's own segment leaves the other exactly where it stood.

    PRD: "A `ReleaseReviewer` decides every segregated segment of a request in a single pass, supplying `segment_decisions`: an array whose entries each carry a `record_segment_id`, a `decision` of either `INCLUDE` or `WITHHOLD`, an optional `redaction_required` boolean, and an optional `note`."

    Design: Corner/endpoints/sensitive_review_naming_a_segment_of_another_request_not_found
    """
    scenario = _two_sibling_requests_in_sensitive_review(api)

    moved = validate_success(
        api.sensitive_review(
            scenario["first_id"],
            f.sensitive_review_payload([f.include_decision(scenario["own_segment_id"])]),
            REVIEWER_1,
        ),
        200,
    )

    assert moved["fulfillment_status"] == "RELEASE_READY"
    assert moved["billable_page_count"] == 20
    assert fx.read_segment(api, scenario["own_segment_id"])["sensitivity_status"] == (
        "AUTHORIZED_INCLUDE"
    )

    sibling_request = fx.read_request(api, scenario["second_id"])
    assert sibling_request["fulfillment_status"] == "SENSITIVE_REVIEW"
    assert sibling_request["billable_page_count"] == 0
    assert fx.read_segment(api, scenario["sibling_segment_id"])["sensitivity_status"] == (
        "SEGREGATED_PENDING_REVIEW"
    )


# --------------------------------------------------------------------------
# compliance_sweep_report_shape_and_repeat_sweep_accrues_nothing
# --------------------------------------------------------------------------
def _one_request_on_a_short_lived_authorization(api):
    """An accepted third-party request due 2026-08-31, governed by an authorization that lapses
    on 2026-08-10."""
    world = fx.third_party_world(api, expires_at="2026-08-10T00:00:00Z")
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])
    assert fx.read_request(api, request["id"])["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    return world, request["id"]


def test_the_first_sweep_lapses_the_authorization_and_reports_no_breach(api):
    """Five of the five report fields at once: one expiry, no breach, no penalty.

    PRD: "The response reports `swept_request_count`, the number of requests examined; `breached_request_ids`, the identifiers of requests whose deadline is breached; `penalized_request_ids`, the identifiers of requests whose statutory penalty moved; `total_penalty_delta_cents`, the summed increase across the sweep; and `expired_authorization_ids`, the identifiers of the authorizations that lapsed."

    Design: Corner/endpoints/compliance_sweep_report_shape_and_repeat_sweep_accrues_nothing
    """
    world, request_id = _one_request_on_a_short_lived_authorization(api)
    fx.set_clock(api, "2026-08-11T00:00:00Z")

    sweep = validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    assert sweep["swept_request_count"] == 1
    assert sweep["expired_authorization_ids"] == [world["authorization_id"]]
    assert sweep["breached_request_ids"] == []
    assert sweep["penalized_request_ids"] == []
    assert sweep["total_penalty_delta_cents"] == 0

    authorization = validate_success(
        api.get_authorization(world["authorization_id"], INTAKE_1), 200
    )
    assert authorization["status"] == "EXPIRED"
    assert_event_count(fx.read_events(api, request_id), "AUTHORIZATION_EXPIRED", 1)


def test_the_second_sweep_reports_the_penalty_delta_and_publishes_the_aggregates(api):
    """A lapsed authorization cannot lapse twice, and the breach arrives with its money.

    PRD: "It then re-derives both penalty measures on every request whose `fulfillment_status` is non-terminal, appending `STATUTORY_DEADLINE_BREACHED` and `PENALTY_ACCRUED` events where the rules above call for them, and re-derives every affected facility's `penalty_exposure_cents`."

    Design: Corner/endpoints/compliance_sweep_report_shape_and_repeat_sweep_accrues_nothing
    """
    world, request_id = _one_request_on_a_short_lived_authorization(api)
    fx.set_clock(api, "2026-08-11T00:00:00Z")
    validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    fx.set_clock(api, "2026-09-05T00:00:00Z")
    sweep = validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    assert sweep["swept_request_count"] == 1
    assert sweep["breached_request_ids"] == [request_id]
    assert sweep["penalized_request_ids"] == [request_id]
    assert sweep["total_penalty_delta_cents"] == 12500
    assert sweep["expired_authorization_ids"] == []

    request = fx.read_request(api, request_id)
    assert request["penalty_exposure_cents"] == 12500
    assert request["safe_harbor_penalty_cents"] == 5000
    assert fx.read_facility(api, world["facility_id"])["penalty_exposure_cents"] == 12500


def test_a_repeat_sweep_at_one_clock_reports_a_status_but_no_further_delta(api):
    """The breach list is a status report; the penalty list is a delta report.

    PRD: "Compliance events are the system's evidentiary record and are never updated or deleted."

    Design: Corner/endpoints/compliance_sweep_report_shape_and_repeat_sweep_accrues_nothing
    """
    _, request_id = _one_request_on_a_short_lived_authorization(api)
    fx.set_clock(api, "2026-08-11T00:00:00Z")
    validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)
    fx.set_clock(api, "2026-09-05T00:00:00Z")
    validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    third = validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    assert third["total_penalty_delta_cents"] == 0
    assert third["penalized_request_ids"] == []
    assert third["breached_request_ids"] == [request_id]

    events, meta = fx.list_events_of(api, request_id)
    assert meta["total_count"] == 3
    assert sorted(event_types(events)) == [
        "AUTHORIZATION_EXPIRED",
        "PENALTY_ACCRUED",
        "STATUTORY_DEADLINE_BREACHED",
    ]
    assert_ascending([event["occurred_at"] for event in events])
    assert fx.read_request(api, request_id)["penalty_exposure_cents"] == 12500


# --------------------------------------------------------------------------
# suspended_facility_blocks_new_request_and_pending_accept_rejected
#
# The design also expects the un-accepted request's statutory_due_at to be
# null, but §3.4 has intake creation compute that field, so the assertion below
# pins it to the value the creation returned instead.
# --------------------------------------------------------------------------
def _suspended_facility_with_a_pending_request(api):
    """One request left in INTAKE_REVIEW, then the governing facility suspended under it."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    facility = validate_success(
        api.set_facility_status(
            world["facility_id"],
            f.facility_status_payload("SUSPENDED", reason="OCR corrective action plan"),
            PLATFORM_ADMIN,
        ),
        200,
    )
    return world, request, facility


def test_suspension_gates_the_two_intake_routes_and_nothing_else(api):
    """Neither an accept nor a new filing survives; registration and reads are untouched.

    PRD: "Suspension is a hard gate on intake: while a facility's `status` is `SUSPENDED`, no new request may be created for it and no existing intake decision may be accepted, both refused with `ERR_FACILITY_SUSPENDED`."

    Design: Corner/endpoints/suspended_facility_blocks_new_request_and_pending_accept_rejected
    """
    world, request, facility = _suspended_facility_with_a_pending_request(api)
    assert facility["status"] == "SUSPENDED"
    assert facility["version"] == 2

    validate_error(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1),
        e.ERR_FACILITY_SUSPENDED,
        409,
    )
    validate_error(
        api.create_request(
            f.third_party_request_payload(
                world["facility_id"],
                world["patient_id"],
                world["requester_id"],
                world["authorization_id"],
                date_range_start="2023-01-01",
                date_range_end="2023-12-31",
            ),
            INTAKE_1,
        ),
        e.ERR_FACILITY_SUSPENDED,
        409,
    )

    stalled = fx.read_request(api, request["id"])
    assert stalled["fulfillment_status"] == "INTAKE_REVIEW"
    assert stalled["statutory_due_at"] == request["statutory_due_at"]
    assert stalled["version"] == request["version"]

    validate_success(
        api.create_patient(
            f.patient_payload(world["facility_id"], mrn="MRN-1002", full_name="Kit Alvarez"),
            world["facility_admin_headers"],
        ),
        201,
    )
    validate_success(api.get_facility(world["facility_id"], PLATFORM_ADMIN), 200)
    _, meta = validate_paginated(
        api.list_requests(INTAKE_1, {"facility_id": world["facility_id"], "limit": 10})
    )
    assert meta["total_count"] == 1


def test_reactivation_restores_the_accept_with_no_residue(api):
    """The gate is checked per call, not latched onto the request that met it.

    PRD: "A `PlatformAdmin` may flip that `status` at any time, supplying the new `status` and an optional `reason`."

    Design: Corner/endpoints/suspended_facility_blocks_new_request_and_pending_accept_rejected
    """
    world, request, _ = _suspended_facility_with_a_pending_request(api)
    validate_error(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1),
        e.ERR_FACILITY_SUSPENDED,
        409,
    )

    reactivated = validate_success(
        api.set_facility_status(
            world["facility_id"],
            f.facility_status_payload("ACTIVE", reason="plan accepted"),
            PLATFORM_ADMIN,
        ),
        200,
    )
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["version"] == 3

    accepted = validate_success(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1), 200
    )
    assert accepted["fulfillment_status"] == "COMPILATION"
    assert accepted["received_at"] == Instant("2026-08-01T00:00:00Z")
    assert accepted["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")


# --------------------------------------------------------------------------
# extension_is_available_once_and_only_up_to_the_deadline_rejected
# --------------------------------------------------------------------------
def _three_accepted_requests_sharing_one_deadline(api):
    """Three sibling third-party requests over different date ranges, all accepted at
    2026-08-01 and therefore all due 2026-08-31."""
    world = fx.third_party_world(api)
    request_ids = []
    for year in ("2021", "2022", "2023"):
        request = fx.open_third_party_request(
            api,
            world,
            date_range_start=f"{year}-01-01",
            date_range_end=f"{year}-12-31",
        )
        fx.accept_request(api, request["id"])
        assert fx.read_request(api, request["id"])["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
        request_ids.append(request["id"])
    return world, request_ids


def test_the_statutory_extension_may_be_noticed_exactly_once(api):
    """The first notice buys fifteen days; the second is refused and buys nothing.

    PRD: "An `IntakeSpecialist` may notice the statutory extension exactly once per request, supplying a `notice_note`."

    Design: Corner/endpoints/extension_is_available_once_and_only_up_to_the_deadline_rejected
    """
    _, request_ids = _three_accepted_requests_sharing_one_deadline(api)
    first_id = request_ids[0]

    noticed = validate_success(
        api.notice_extension(
            first_id, f.extension_payload("volume of legacy records"), INTAKE_1
        ),
        200,
    )
    assert noticed["extension_applied"] is True
    assert noticed["extension_noticed_at"] == Instant("2026-08-01T00:00:00Z")
    assert noticed["statutory_due_at"] == Instant("2026-09-15T00:00:00Z")

    validate_error(
        api.notice_extension(first_id, f.extension_payload("still not done"), INTAKE_1),
        e.ERR_EXTENSION_NOT_AVAILABLE,
        409,
    )

    after = fx.read_request(api, first_id)
    assert after["statutory_due_at"] == Instant("2026-09-15T00:00:00Z")
    assert after["version"] == noticed["version"]


def test_a_notice_at_the_deadline_instant_is_in_time_and_one_second_later_is_not(api):
    """The window closes strictly after `statutory_due_at`, so one second decides it.

    PRD: "The notice is refused with `ERR_EXTENSION_NOT_AVAILABLE` when `extension_applied` is already true, when the governing rule's `extension_days` is 0, or when the current logical clock is already past `statutory_due_at`; at an instant exactly equal to `statutory_due_at` the extension is still available."

    Design: Corner/endpoints/extension_is_available_once_and_only_up_to_the_deadline_rejected
    """
    _, request_ids = _three_accepted_requests_sharing_one_deadline(api)
    extended_early, on_the_instant, one_second_late = request_ids
    get_success_data(
        api.notice_extension(
            extended_early, f.extension_payload("volume of legacy records"), INTAKE_1
        )
    )

    fx.set_clock(api, "2026-08-31T00:00:00Z")
    boundary = validate_success(
        api.notice_extension(
            on_the_instant, f.extension_payload("noticed on the deadline itself"), INTAKE_1
        ),
        200,
    )
    assert boundary["statutory_due_at"] == Instant("2026-09-15T00:00:00Z")

    fx.set_clock(api, "2026-08-31T00:00:01Z")
    validate_error(
        api.notice_extension(
            one_second_late, f.extension_payload("one second too late"), INTAKE_1
        ),
        e.ERR_EXTENSION_NOT_AVAILABLE,
        409,
    )

    refused = fx.read_request(api, one_second_late)
    assert refused["extension_applied"] is False
    assert refused["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")

    late_read = validate_success(api.get_turnaround(one_second_late, PLATFORM_ADMIN), 200)
    assert late_read["breached"] is True
    assert late_read["days_late_strict"] == 1
    assert late_read["extension_applied"] is False
    assert validate_success(api.get_turnaround(extended_early, PLATFORM_ADMIN), 200)["breached"] is (
        False
    )
