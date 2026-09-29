"""Depth tests for the `priority_pair_validation_conflict`,
`boundary_precision_check` and `cross_entity_state_dependency` rules.

Every test below translates exactly one non-stub instance of
`SCAFFOLD_DIFFICULTY_DESIGN.yaml`; the trailing `Design:` line of each docstring
names the instance it came from.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BUILDER_SAMPLING_INELIGIBLE,
    ERR_CERTIFICATION_INVALID,
    ERR_PACKAGE_NOT_ELIGIBLE,
    ERR_RATING_VOID,
    ERR_SAMPLE_SET_NO_TESTED_RATING,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_count,
    assert_home_sampling_state,
    assert_index,
    assert_normalized_value,
    assert_package_state,
    assert_rater_standing,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    build_confirmed_world,
    build_rating_world,
    build_sample_world,
    complete_inspection,
    confirm_rating,
    create_home,
    create_rating,
    draft_package,
    get_builder,
    get_home,
    get_inspection,
    get_rater,
    get_rating,
    get_sample_set,
    list_diagnostic_tests,
    list_packages,
    record_test,
    schedule_inspection,
    select_sample_set,
    set_clock,
    void_rating,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_certified_rater_headers,
    make_field_inspector_headers,
)

BIG_3000 = {
    "plan_code": "BIG-3000",
    "conditioned_floor_area_sqft": 3000,
    "conditioned_volume_cuft": 27000,
    "bedrooms": 5,
    "envelope_ua_btu_per_hr_f": 520,
    "design_ach50": 4.00,
    "design_duct_leakage_cfm25_per_100sqft": 4.00,
    "hvac_efficiency_index": 8,
    "pv_capacity_kw_dc": 0,
}


def _voided_with_expired_inspector(api: ApiClient):
    """A scheduled FINAL checkpoint whose rating has been voided and whose
    inspector's certificate has since lapsed against the logical clock."""
    world = build_rating_world(
        api,
        builder_name="Foxglove Homes",
        subdivision_name="Wrenfield",
        lot_number="L-55",
        inspector_cert_expires_at="2026-09-01T00:00:00Z",
    )
    inspection = schedule_inspection(
        api,
        world.rating_id,
        world.inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc="2026-08-20T09:00:00Z",
        scheduled_end_utc="2026-08-20T11:00:00Z",
        air_handler_installed=True,
    )
    void_rating(api, world.rating_id)
    set_clock(api, "2026-09-02T00:00:00Z")
    return world, inspection


def _oversized_package_on_a_tiny_budget(api: ApiClient):
    """A PASSING rating whose confirmed index 54 breaks the utility programme's
    ceiling of 50 while its amount also breaks a 1,000-cent builder budget."""
    world = build_confirmed_world(
        api,
        builder_name="Larkfield Homes",
        subdivision_name="Ashbourne",
        utility_program_budget_cents=1000,
        plan_overrides=BIG_3000,
        lot_number="L-9",
        blower_door=810,
        duct_leakage=90,
    )
    package = draft_package(api, world.rating_id, world.builder_id, "UTILITY_PROGRAM")
    return world, package


def _selected_pair(api: ApiClient):
    """Two identical lots in one set, selected but with no confirmed rating yet."""
    world = build_sample_world(
        api,
        member_count=2,
        builder_name="Alder Homes",
        subdivision_name="Quarry Bend",
        lot_numbers=["L-13a", "L-13b"],
        permit_dates=["2026-08-04", "2026-08-05"],
    )
    world.sample_set = select_sample_set(api, world.sample_set_id)
    return world


def _suspended_builder_with_forming_set(api: ApiClient):
    """A forming two-member set whose builder has just picked up an open action on
    a third, unrelated lot."""
    world = build_sample_world(
        api,
        member_count=2,
        builder_name="Alder Homes",
        subdivision_name="Quarry Bend",
        lot_numbers=["L-13a", "L-13b"],
        permit_dates=["2026-08-04", "2026-08-05"],
    )
    outsider = create_home(
        api,
        world.subdivision_id,
        world.base.plan_model_id,
        world.builder_id,
        lot_number="L-99",
        permit_date="2026-08-06",
    )
    rating = create_rating(api, outsider["id"], world.rater_id)
    inspection = schedule_inspection(
        api,
        rating["id"],
        world.inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc="2026-08-20T09:00:00Z",
        scheduled_end_utc="2026-08-20T11:00:00Z",
        air_handler_installed=True,
    )
    record_test(api, inspection["id"], world.inspector_id, "BLOWER_DOOR", 1200)
    record_test(api, inspection["id"], world.inspector_id, "DUCT_LEAKAGE_TOTAL", 96)
    complete_inspection(api, inspection["id"], world.inspector_id)
    confirm_rating(api, rating["id"], world.rater_id)
    return world


# ================================================ priority_pair_validation_conflict
def test_void_rating_error_precedes_the_expired_certification_error(
    api: ApiClient,
) -> None:
    """Recording a test on a voided rating with a lapsed inspector reports the
    lower-numbered void check, not the certification check.

    PRD §2.8: "This ordering is normative: when two checks would both fail on the same request, the lower-numbered one is the error the client sees."

    Design: Difficulty/priority_pair_validation_conflict/void_rating_state_beats_expired_inspector_certification
    """
    world, inspection = _voided_with_expired_inspector(api)
    response = api.create_diagnostic_test(
        inspection["id"],
        factories.diagnostic_test_payload("BLOWER_DOOR", 1080),
        make_field_inspector_headers(world.inspector_id),
    )
    validate_error(response, ERR_RATING_VOID, 409)


def test_both_conflicting_conditions_really_hold_and_nothing_was_recorded(
    api: ApiClient,
) -> None:
    """The inspector genuinely reads `EXPIRED` and the rating genuinely reads
    `VOID`, and the rejected request left the checkpoint's evidence empty.

    PRD §2.11: "`effective_certification_status` is the field every gate in the system actually reads: it equals `certification_status` except that it reports `EXPIRED` whenever the logical clock stands at or after `cert_expires_at`."

    Design: Difficulty/priority_pair_validation_conflict/void_rating_state_beats_expired_inspector_certification
    """
    world, inspection = _voided_with_expired_inspector(api)
    api.create_diagnostic_test(
        inspection["id"],
        factories.diagnostic_test_payload("BLOWER_DOOR", 1080),
        make_field_inspector_headers(world.inspector_id),
    )
    assert_rater_standing(
        get_rater(api, world.inspector_id), effective_certification_status="EXPIRED"
    )
    assert_rating_dimensions(get_rating(api, world.rating_id), stage="VOID")
    assert get_inspection(api, inspection["id"])["failed_test_count"] == 0
    assert_count(list_diagnostic_tests(api, inspection["id"]), 0)


def test_package_eligibility_error_precedes_the_programme_budget_error(
    api: ApiClient,
) -> None:
    """Confirmed index 54 exceeds the utility programme's ceiling of 50 and the
    amount also exceeds the 1,000-cent budget; eligibility is checked first.

    PRD §3.9: "It further requires the rating to be efficient enough for the programme in question: a `TAX_CREDIT_45L` package needs a `confirmed_index` of 55 or lower and a `UTILITY_PROGRAM` package needs a `confirmed_index` of 50 or lower, and an index above the applicable ceiling is refused with `ERR_PACKAGE_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/package_eligibility_constraint_beats_program_cap_fiscal
    """
    world, package = _oversized_package_on_a_tiny_budget(api)
    assert_index(get_rating(api, world.rating_id)["confirmed_index"], 54)
    response = api.issue_document_package(package["id"], ADMIN_HEADERS)
    validate_error(response, ERR_PACKAGE_NOT_ELIGIBLE, 422)


def test_refused_issuance_leaves_the_draft_and_the_money_ledger_untouched(
    api: ApiClient,
) -> None:
    """No certified amount is written and the builder's ledger never moves, because
    only a successful issuance touches it.

    PRD §3.9: "Only the certified figure ever moves `certified_incentive_cents`."

    Design: Difficulty/priority_pair_validation_conflict/package_eligibility_constraint_beats_program_cap_fiscal
    """
    world, package = _oversized_package_on_a_tiny_budget(api)
    api.issue_document_package(package["id"], ADMIN_HEADERS)
    (still_draft,) = list_packages(api, world.rating_id)
    assert_package_state(still_draft, status="DRAFT", certified_amount_cents=None)
    assert_builder_ledger(get_builder(api, world.builder_id), certified_incentive_cents=0)
    assert_rating_dimensions(get_rating(api, world.rating_id), compliance_status="PASSING")


# ==================================================== boundary_precision_check
def test_blower_door_reading_exactly_at_the_limit_passes(api: ApiClient) -> None:
    """1080 CFM50 over 21,600 cubic feet normalizes to exactly 3.00, and the
    inclusive comparison against the 3.0 limit therefore passes.

    PRD §2.6: "A reading that normalizes to 3.00 therefore passes a limit of 3.0, and a reading that normalizes to 3.01 fails it."

    Design: Difficulty/boundary_precision_check/blower_door_exactly_at_ach50_threshold_passes
    """
    world = build_rating_world(
        api, builder_name="Marlowe Homes", subdivision_name="Sable Ridge", lot_number="L-70"
    )
    inspection = schedule_inspection(
        api,
        world.rating_id,
        world.inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc="2026-08-12T09:00:00Z",
        scheduled_end_utc="2026-08-12T11:00:00Z",
        air_handler_installed=True,
    )
    reading = record_test(api, inspection["id"], world.inspector_id, "BLOWER_DOOR", 1080)
    assert_normalized_value(reading["normalized_value"], 3.00)
    assert_normalized_value(reading["threshold_value"], 3.0)
    assert reading["result"] == "PASS", reading
    assert get_inspection(api, inspection["id"])["failed_test_count"] == 0


def test_blower_door_reading_one_hundredth_above_the_limit_fails(api: ApiClient) -> None:
    """1084 CFM50 normalizes to 3.0111... which rounds half-up to 3.01, one
    hundredth above the limit, so the reading fails and is counted.

    PRD §3.3: "In both cases the graded outcome follows one rule: `result` is `PASS` when the rounded `normalized_value` is less than or equal to `threshold_value`, and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/blower_door_exactly_at_ach50_threshold_passes
    """
    world = build_rating_world(
        api, builder_name="Marlowe Homes", subdivision_name="Sable Ridge", lot_number="L-70"
    )
    inspection = schedule_inspection(
        api,
        world.rating_id,
        world.inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc="2026-08-14T09:00:00Z",
        scheduled_end_utc="2026-08-14T11:00:00Z",
        air_handler_installed=True,
    )
    reading = record_test(api, inspection["id"], world.inspector_id, "BLOWER_DOOR", 1084)
    assert_normalized_value(reading["normalized_value"], 3.01)
    assert reading["result"] == "FAIL", reading
    assert get_inspection(api, inspection["id"])["failed_test_count"] == 1


def test_closing_a_selected_set_without_a_confirmed_rating_is_refused(
    api: ApiClient,
) -> None:
    """The set has a tested home but that home has never been confirmed, so the
    aggregation input is empty and closure is refused outright.

    PRD §3.5: "Attempting to close a set that is still merely `SELECTED` — that is, one whose tested home has not been confirmed and therefore has no confirmed index at all — always fails with `ERR_SAMPLE_SET_NO_TESTED_RATING`, because the aggregation below would have an empty input set."

    Design: Difficulty/boundary_precision_check/close_sample_set_with_zero_tested_ratings_rejected
    """
    world = _selected_pair(api)
    assert_sample_set_counters(
        world.sample_set, status="SELECTED", tested_home_id=world.homes[0]["id"]
    )
    response = api.close_sample_set(world.sample_set_id, ADMIN_HEADERS)
    validate_error(response, ERR_SAMPLE_SET_NO_TESTED_RATING, 409)


def test_refused_closure_leaves_the_selected_set_exactly_as_it_was(
    api: ApiClient,
) -> None:
    """No partial aggregation is written: the set stays `SELECTED` with a null
    representative index and its member roles unchanged.

    PRD §3.5: "Selection then records the winner's identifier in the set's `tested_home_id`, moves that home's `sampling_role` from `MEMBER` to `TESTED`, sets `tested_member_count` to 1, and moves the set's `status` from `FORMING` to `SELECTED`."

    Design: Difficulty/boundary_precision_check/close_sample_set_with_zero_tested_ratings_rejected
    """
    world = _selected_pair(api)
    api.close_sample_set(world.sample_set_id, ADMIN_HEADERS)
    assert_sample_set_counters(
        get_sample_set(api, world.sample_set_id),
        status="SELECTED",
        member_count=2,
        tested_member_count=1,
        represented_member_count=0,
        representative_index=None,
    )
    assert_home_sampling_state(get_home(api, world.homes[0]["id"]), sampling_role="TESTED")
    assert_home_sampling_state(get_home(api, world.homes[1]["id"]), sampling_role="MEMBER")


# ================================================= cross_entity_state_dependency
def test_registry_submission_is_blocked_by_the_raters_lapsed_certificate(
    api: ApiClient,
) -> None:
    """Advancing the clock past `cert_expires_at` disables the rater of record and
    the otherwise-admissible submission is refused.

    PRD §2.11: "A person who is suspended, or whose certification has expired, blocks the operation with `ERR_CERTIFICATION_INVALID` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/registry_submit_blocked_by_expired_rater_certification
    """
    world = build_confirmed_world(
        api,
        builder_name="Hollow Creek Homes",
        subdivision_name="Ivyfield",
        lot_number="L-31",
        rater_cert_expires_at="2026-09-01T00:00:00Z",
        blower_door=1080,
        duct_leakage=96,
    )
    set_clock(api, "2026-09-02T00:00:00Z")
    response = api.submit_rating_to_registry(
        world.rating_id, make_certified_rater_headers(world.rater_id)
    )
    validate_error(response, ERR_CERTIFICATION_INVALID, 422)


def test_lapsed_certificate_is_derived_from_the_clock_not_from_discipline(
    api: ApiClient,
) -> None:
    """The stored `certification_status` is still `ACTIVE`; only the derived field
    reads `EXPIRED`, and the blocked rating keeps its unlocked, passing file.

    PRD §2.5: "Moving the clock immediately re-derives every rater's `effective_certification_status` against the new instant, so advancing time past a certification expiry is sufficient to disable that person without touching their row."

    Design: Difficulty/cross_entity_state_dependency/registry_submit_blocked_by_expired_rater_certification
    """
    world = build_confirmed_world(
        api,
        builder_name="Hollow Creek Homes",
        subdivision_name="Ivyfield",
        lot_number="L-31",
        rater_cert_expires_at="2026-09-01T00:00:00Z",
        blower_door=1080,
        duct_leakage=96,
    )
    set_clock(api, "2026-09-02T00:00:00Z")
    api.submit_rating_to_registry(
        world.rating_id, make_certified_rater_headers(world.rater_id)
    )
    assert_rater_standing(
        get_rater(api, world.rater_id),
        certification_status="ACTIVE",
        effective_certification_status="EXPIRED",
        registry_hold=False,
    )
    rating = get_rating(api, world.rating_id)
    assert rating["file_locked"] is False, rating
    assert_rating_dimensions(
        rating, stage="CONFIRMED", compliance_status="PASSING", registry_status="NOT_SUBMITTED"
    )


def test_selection_is_blocked_by_an_action_opened_elsewhere_in_the_portfolio(
    api: ApiClient,
) -> None:
    """A corrective action on an unrelated lot strips the builder's sampling
    eligibility, and the untouched set can no longer be selected.

    PRD §3.5: "A subdivision with `sampling_enabled` false refuses the request with `ERR_SAMPLING_NOT_ENABLED`, and a builder that is not `sampling_eligible` — because it is `CUSTOM`, because its `status` is `SAMPLING_SUSPENDED`, or because it has open corrective actions — refuses it with `ERR_BUILDER_SAMPLING_INELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/sample_set_select_blocked_by_builder_sampling_suspended
    """
    world = _suspended_builder_with_forming_set(api)
    response = api.select_sample_set(world.sample_set_id, ADMIN_HEADERS)
    validate_error(response, ERR_BUILDER_SAMPLING_INELIGIBLE, 422)


def test_eligibility_is_derived_and_the_blocked_set_stays_forming(
    api: ApiClient,
) -> None:
    """One open action is enough: `sampling_eligible` recomputes to false and the
    set keeps both members with no tested home chosen.

    PRD §3.1: "It is true when, and only when, all three of the following hold: `builder_type` is `PRODUCTION`, `status` is `ACTIVE`, and `open_corrective_action_count` is zero."

    Design: Difficulty/cross_entity_state_dependency/sample_set_select_blocked_by_builder_sampling_suspended
    """
    world = _suspended_builder_with_forming_set(api)
    api.select_sample_set(world.sample_set_id, ADMIN_HEADERS)
    assert_builder_ledger(
        get_builder(api, world.builder_id),
        open_corrective_action_count=1,
        sampling_eligible=False,
    )
    assert_sample_set_counters(
        get_sample_set(api, world.sample_set_id),
        status="FORMING",
        member_count=2,
        tested_member_count=0,
        tested_home_id=None,
    )
    assert_home_sampling_state(get_home(api, world.homes[0]["id"]), sampling_role="MEMBER")
