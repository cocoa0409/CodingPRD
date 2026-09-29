"""The two optimistic-concurrency guards, and the immediacy of the approval cascade."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_density
from test_helpers.factories import closure_cost_estimate_payload
from test_helpers.test_users import TEST_USERS

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]
CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]


def _site_whose_version_moved_behind_the_filer():
    """A site read at version 1, then certified behind the filer's back.

    The QA approval cascade recomputes the airspace ledger — the very basis a closure
    cost estimate is priced against — and increments the landfill's version to 2.
    """
    landfill = fixtures.create_landfill()
    before = fixtures.read_landfill(landfill["id"])
    stale_version = int(before["version"])
    assert stale_version == 1
    assert_amount(before["certified_airspace_cy"], 0, "certified airspace before the approval")

    certified = fixtures.setup_qa_certified_cell(landfill["id"])
    assert certified["cell"]["status"] == "QA_CERTIFIED"
    return landfill, stale_version


def _file_estimate(landfill_id, expected_landfill_version, **overrides):
    return api_client.create_closure_cost_estimate(
        closure_cost_estimate_payload(landfill_id, expected_landfill_version, **overrides),
        FINANCE_FILER,
    )


def _estimates_of(landfill_id, **filters):
    params = {"landfill_id": landfill_id}
    params.update(filters)
    return validate_paginated(api_client.list_closure_cost_estimates(FINANCE_FILER, params))


def test_the_annual_filing_is_refused_on_the_version_the_certification_superseded():
    """The filer quotes the version it read; certification has since moved the basis.

    PRD: "If `expected_landfill_version` does not equal the landfill's current `version`,
    the create is rejected with `ERR_STALE_LANDFILL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/closure_estimate_create_with_a_stale_landfill_version_is_rejected
    """
    landfill, stale_version = _site_whose_version_moved_behind_the_filer()

    response = _file_estimate(landfill["id"], stale_version)

    validate_error(response, ApiErrorId.ERR_STALE_LANDFILL_VERSION.value, 412)
    _rows, meta = _estimates_of(landfill["id"])
    assert meta["total_count"] == 0, "the refused filing must not have been stored"


def test_the_freshly_read_version_files_the_update_and_bumps_the_version_again():
    """Re-reading the site yields version 2 and the certified basis the estimate prices.

    PRD: "A filed update opens in `DRAFT` with `instrument_type` null and `version` at 1,
    computes all four of its money fields immediately, and increments the landfill's
    `version` by 1."

    Design: Corner/cross_cutting_layers/closure_estimate_create_with_a_stale_landfill_version_is_rejected
    """
    landfill, stale_version = _site_whose_version_moved_behind_the_filer()
    fresh = fixtures.read_landfill(landfill["id"])
    fresh_version = int(fresh["version"])
    assert fresh_version == 2 and fresh_version != stale_version
    assert_amount(fresh["certified_airspace_cy"], 1000000, "certified airspace after the approval")

    estimate = validate_success(_file_estimate(landfill["id"], fresh_version), 201)

    assert estimate["status"] == "DRAFT"
    assert estimate["instrument_type"] is None
    assert int(estimate["version"]) == 1
    assert_amount(estimate["closure_cost_total"], 222601.86, "closure cost total")
    assert_amount(estimate["post_closure_cost_total"], 4519664.50, "post-closure cost total")
    assert_amount(estimate["required_assurance_amount"], 4742266.36, "required assurance")
    assert int(fixtures.read_landfill(landfill["id"])["version"]) == 3, (
        "the successful create increments the landfill version in turn"
    )


def _site_with_one_filed_2026_update():
    """The 2026 filing has been accepted at version 2, leaving the site at version 3."""
    landfill, _stale_version = _site_whose_version_moved_behind_the_filer()
    used_version = int(fixtures.read_landfill(landfill["id"])["version"])
    estimate = validate_success(_file_estimate(landfill["id"], used_version), 201)
    assert int(fixtures.read_landfill(landfill["id"])["version"]) == used_version + 1
    return landfill, estimate, used_version


def test_the_version_a_filer_just_spent_is_already_stale_for_the_next_years_update():
    """Version 2 bought the 2026 filing; the 2027 filing needs version 3.

    PRD: "Two write operations are guarded by optimistic concurrency against the parent
    `Landfill`, and both use the same non-optional input field: `expected_landfill_version`,
    carrying the `version` value of the landfill that the client last observed."

    Design: Corner/cross_cutting_layers/closure_estimate_create_with_a_stale_landfill_version_is_rejected
    """
    landfill, estimate, used_version = _site_with_one_filed_2026_update()

    response = _file_estimate(landfill["id"], used_version, estimate_year=2027)

    validate_error(response, ApiErrorId.ERR_STALE_LANDFILL_VERSION.value, 412)
    rows, meta = _estimates_of(landfill["id"])
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [estimate["id"]]


def test_a_stale_version_answers_before_the_duplicate_year_rung_is_consulted():
    """The re-filing breaks two rungs at once and only the concurrency one is reported.

    PRD: "Because several rules can be violated by one request, the evaluation order below
    is part of the contract: the *first* rule that fails determines the response, and later
    rules are never reached."

    Design: Corner/cross_cutting_layers/closure_estimate_create_with_a_stale_landfill_version_is_rejected
    """
    landfill, estimate, used_version = _site_with_one_filed_2026_update()
    assert int(estimate["estimate_year"]) == 2026

    response = _file_estimate(landfill["id"], used_version, estimate_year=2026)

    validate_error(response, ApiErrorId.ERR_STALE_LANDFILL_VERSION.value, 412)
    _rows, meta = _estimates_of(landfill["id"], estimate_year=2026)
    assert meta["total_count"] == 1


def _drafted_agreement_with_a_certification_behind_its_back():
    """HCA-1 sits in DRAFT; an unrelated cell certification then moves the site to version 2."""
    landfill = fixtures.create_landfill()
    agreement = fixtures.draft_host_agreement(landfill["id"])
    assert agreement["status"] == "DRAFT"
    assert int(agreement["amendment_round"]) == 0
    stale_version = int(fixtures.read_landfill(landfill["id"])["version"])

    fixtures.setup_qa_certified_cell(landfill["id"])
    return landfill, agreement, stale_version


def test_execution_on_a_stale_version_leaves_the_agreement_in_draft():
    """Drafting never touched the site's version, so the stale read was version 1.

    PRD: "If `expected_landfill_version` does not equal the landfill's current `version`,
    the execution is rejected with `ERR_STALE_LANDFILL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/host_agreement_execute_with_a_stale_landfill_version_is_rejected
    """
    landfill, agreement, stale_version = _drafted_agreement_with_a_certification_behind_its_back()
    assert stale_version == 1, "drafting an agreement does not increment the landfill version"

    response = api_client.execute_host_community_agreement(
        agreement["id"], {"expected_landfill_version": stale_version}, FINANCE_FILER
    )

    validate_error(response, ApiErrorId.ERR_STALE_LANDFILL_VERSION.value, 412)
    unchanged = get_success_data(
        api_client.get_host_community_agreement(agreement["id"], FINANCE_FILER)
    )
    assert unchanged["status"] == "DRAFT"
    assert int(unchanged["amendment_round"]) == 0
    assert int(unchanged["version"]) == 1, "the refused execute applied none of its side effects"
    assert unchanged["termination_reason"] is None


def test_the_retry_on_the_current_version_takes_the_agreement_live():
    """The identical execute succeeds once it quotes the version certification left behind.

    PRD: "The newly executed agreement has its own `version` incremented by 1, and the
    landfill's `version` is incremented by 1 as well."

    Design: Corner/cross_cutting_layers/host_agreement_execute_with_a_stale_landfill_version_is_rejected
    """
    landfill, agreement, stale_version = _drafted_agreement_with_a_certification_behind_its_back()
    api_client.execute_host_community_agreement(
        agreement["id"], {"expected_landfill_version": stale_version}, FINANCE_FILER
    )
    fresh_version = int(fixtures.read_landfill(landfill["id"])["version"])
    assert fresh_version == 2

    executed = validate_success(
        api_client.execute_host_community_agreement(
            agreement["id"], {"expected_landfill_version": fresh_version}, FINANCE_FILER
        ),
        200,
    )

    assert executed["status"] == "EXECUTED"
    assert int(executed["version"]) == 2
    assert int(fixtures.read_landfill(landfill["id"])["version"]) == 3, (
        "executing increments the landfill version, so the version just quoted is stale in turn"
    )


def _package_one_call_away_from_certifying_its_cell():
    """QA-1 is UNDER_REVIEW at a perfect score over a 1,000,000 cy cell; the ledger is empty."""
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"])
    package = fixtures.submit_liner_qa_package(landfill["id"], cell["id"])
    assert_amount(package["qa_conformance_score"], 100.00, "conformance score")
    reviewing = fixtures.begin_liner_review(package["id"])
    assert reviewing["status"] == "UNDER_REVIEW"

    before = fixtures.read_landfill(landfill["id"])
    assert_amount(before["certified_airspace_cy"], 0, "certified airspace before approval")
    assert_amount(before["remaining_life_years"], 0.00, "remaining life before approval")
    return landfill, cell, package


def _approve(package):
    return api_client.approve_liner_qa_package(
        package["id"], {"certification_reference": "CQA-2026-01"}, CQA_ENGINEER
    )


def test_the_approval_cascade_is_already_visible_in_the_very_next_read():
    """One write, then one read: the ledger has already absorbed the certified cell.

    PRD: "Because the cell has entered the certified set, the site's `certified_airspace_cy`
    is recomputed and now includes this cell's `design_airspace_cy`; `remaining_airspace_cy`
    and `remaining_life_years` are recomputed from it, and the landfill's `version` is
    incremented by 1."

    Design: Corner/consistency_model/qa_approval_side_effects_are_visible_in_the_very_next_read
    """
    landfill, cell, package = _package_one_call_away_from_certifying_its_cell()

    approved = validate_success(_approve(package), 200)

    assert approved["status"] == "APPROVED"
    after = fixtures.read_landfill(landfill["id"])
    assert_amount(after["certified_airspace_cy"], 1000000, "certified airspace")
    assert_amount(after["remaining_airspace_cy"], 1000000.00, "remaining airspace")
    assert_amount(after["remaining_life_years"], 3.00, "remaining life")
    certified = get_success_data(api_client.get_cell(cell["id"], PLATFORM_ADMIN))
    assert certified["status"] == "QA_CERTIFIED", "link 1 fired inside the approving request"


def test_the_cascade_stops_where_the_declared_chain_stops():
    """No certified estimate exists, so link 3 is a no-op and link 4 never fires.

    PRD: "It stays `UNFUNDED` until a closure cost estimate of the site reaches `CERTIFIED`."

    Design: Corner/consistency_model/qa_approval_side_effects_are_visible_in_the_very_next_read
    """
    landfill, _cell, package = _package_one_call_away_from_certifying_its_cell()
    version_before = int(fixtures.read_landfill(landfill["id"])["version"])

    validate_success(_approve(package), 200)

    after = fixtures.read_landfill(landfill["id"])
    assert after["financial_assurance_status"] == "UNFUNDED"
    assert int(after["version"]) == version_before + 1, (
        "link 4 would have incremented the landfill version a second time"
    )
    _rows, meta = _estimates_of(landfill["id"])
    assert meta["total_count"] == 0


def test_the_computed_projection_and_the_stored_derived_field_agree_immediately():
    """The recomputed read and the field the cascade wrote report the same 3.00 years.

    PRD: "Under `ledger_based`, the remaining airspace is the site's `certified_airspace_cy`
    minus its `consumed_airspace_cy`, rounded to 2 decimal places; the density is the site's
    `planned_density_tons_per_cy`; and `source_survey_id` is null."

    Design: Corner/consistency_model/qa_approval_side_effects_are_visible_in_the_very_next_read
    """
    landfill, _cell, package = _package_one_call_away_from_certifying_its_cell()
    validate_success(_approve(package), 200)

    projection = get_success_data(
        api_client.get_remaining_life_projection(landfill["id"], PLATFORM_ADMIN)
    )

    assert projection["variant"] == "ledger_based"
    assert projection["source_survey_id"] is None
    assert_amount(projection["remaining_airspace_cy"], 1000000.00, "projected remaining airspace")
    assert_density(projection["density_tons_per_cy"], 0.9000, "ledger density")
    assert_amount(projection["remaining_life_years"], 3.00, "projected remaining life")
    stored = fixtures.read_landfill(landfill["id"])["remaining_life_years"]
    assert float(stored) == float(projection["remaining_life_years"])
