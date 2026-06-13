"""Harvest reporting and season windows: bag-limit boundary, the half-open season window,
the strictly-before entry deadline, cross-entity state dependencies, and budget release.

PRD §3.4 (seasons/pools), §3.6 (entry window), §3.8 (execute-draw), §3.9 (harvest/bag budget).
"""
from test_helpers import (
    validate_success, validate_error,
    create_applicant, create_resident_applicant,
    create_product, create_season, create_tag_product_for_season,
    create_pool, enter_draw, close_pool,
    issue_otc_license, submit_harvest, setup_resident_with_tag_license,
    set_clock, create_harvest_report_payload, create_draw_application_payload,
    make_applicant_headers, TEST_USERS,
)

OFFICER = TEST_USERS["draw_officer_headers"]
WARDEN = TEST_USERS["game_warden_headers"]
AGENT = TEST_USERS["license_agent_headers"]


def test_bag_limit_at_boundary_accepted(api):
    """PRD §3.9: "A new report of some quantity is admissible only when the already-counted quantity plus that new quantity does not exceed the season's `bag_limit`; otherwise it is rejected with `ERR_BAG_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bag_limit_exact_boundary_accept_then_reject
    """
    season, product, applicant, license_ = setup_resident_with_tag_license(
        bag_limit=2, clock="2026-09-15T00:00:00Z")
    submit_harvest(license_["id"], applicant["id"],
                   harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    # counted 1 + 1 == 2 == bag_limit -> admissible.
    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-09-16T08:00:00Z", quantity=1),
        make_applicant_headers(applicant["id"]))
    report = validate_success(res, 201)
    assert report["status"] == "SUBMITTED"


def test_bag_limit_over_boundary_rejected(api):
    """PRD §3.9: "the season bag budget counts the summed `quantity` of all harvest reports
    filed under the applicant's licenses for that season whose status is `SUBMITTED` or
    `ACCEPTED` (reports in `REJECTED` are excluded and do not count)."
    PRD §3.9: "A new report of some quantity is admissible only when the already-counted
    quantity plus that new quantity does not exceed the season's `bag_limit`; otherwise it is
    rejected with `ERR_BAG_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bag_limit_exact_boundary_accept_then_reject
    """
    season, product, applicant, license_ = setup_resident_with_tag_license(
        bag_limit=2, clock="2026-09-15T00:00:00Z")
    submit_harvest(license_["id"], applicant["id"],
                   harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    # counted 1 + 2 == 3 > bag_limit 2 -> rejected.
    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-09-17T08:00:00Z", quantity=2),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_BAG_LIMIT_EXCEEDED", expected_status=409)


def test_execute_draw_blocked_when_season_not_open(api):
    """PRD §3.8: "Execution is defined only when the pool is `CLOSED`; otherwise it is an
    `ERR_INVALID_STATE` conflict. It additionally requires that the bound `SpeciesSeason` be `OPEN`
    at execution time".

    Design: Difficulty/cross_entity_state_dependency/execute_draw_blocked_when_season_not_open
    """
    set_clock("2026-03-01T00:00:00Z")
    # Season left in DRAFT (never opened).
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=False)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-10T00:00:00Z")
    enter_draw(pool["id"], create_applicant(full_name="A1")["id"])
    closed = close_pool(pool["id"], "2026-03-11T00:00:00Z")

    res = api.execute_draw(
        pool["id"], {"expected_draw_pool_version": closed["version"]}, OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_execute_draw_blocked_leaves_pool_closed(api):
    """PRD §3.8: "It additionally requires that the bound `SpeciesSeason` be `OPEN` at execution
    time, and it requires the optimistic-concurrency token of §2.7".

    Design: Difficulty/cross_entity_state_dependency/execute_draw_blocked_when_season_not_open
    """
    set_clock("2026-03-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=False)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-03-10T00:00:00Z")
    enter_draw(pool["id"], create_applicant(full_name="A1")["id"])
    closed = close_pool(pool["id"], "2026-03-11T00:00:00Z")

    api.execute_draw(pool["id"], {"expected_draw_pool_version": closed["version"]}, OFFICER)
    # The blocked draw must not advance the pool out of CLOSED.
    refreshed = validate_success(api.get_draw_pool(pool["id"], OFFICER), 200)
    assert refreshed["status"] == "CLOSED"
    assert refreshed["awarded_count"] == 0


def test_harvest_blocked_when_season_closed(api):
    """PRD §3.9: "the `harvest_datetime` must fall within the bound season's window — at or
    after `season_open` and strictly before `season_close` — and the season must be `OPEN` at
    report time; a violation of either is rejected with `ERR_SEASON_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/harvest_report_blocked_when_season_not_open
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])
    # Officer closes the season after issuance.
    validate_success(api.close_species_season(season["id"], OFFICER), 200)

    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-09-16T08:00:00Z", quantity=1),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_SEASON_NOT_OPEN", expected_status=409)


def test_harvest_blocked_season_closed_window_in_range(api):
    """PRD §3.9: "the `harvest_datetime` must fall within the bound season's window — at or
    after `season_open` and strictly before `season_close` — and the season must be `OPEN` at
    report time; a violation of either is rejected with `ERR_SEASON_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/harvest_report_blocked_when_season_not_open
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res2", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])
    validate_success(api.close_species_season(season["id"], OFFICER), 200)

    # Datetime is inside the [open, close) window but the season is CLOSED -> rejected.
    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-09-20T08:00:00Z", quantity=1),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_SEASON_NOT_OPEN", expected_status=409)


def test_draw_entry_deadline_exclusive_upper_bound(api):
    """PRD §3.6: "an application may be created only while the pool is `ACCEPTING` and the clock
    is strictly before the pool's `entry_deadline`; an attempt once the pool is no longer
    accepting or the deadline has arrived is rejected with `ERR_ENTRY_CLOSED`."

    Design: Difficulty/resource_temporal_overlap/draw_entry_deadline_exclusive_upper_bound
    """
    set_clock("2026-05-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-05-10T00:00:00Z")
    applicant = create_applicant(full_name="A1")
    # Clock advanced to exactly the entry_deadline: now == deadline is NOT strictly before.
    set_clock("2026-05-10T00:00:00Z")

    res = api.create_draw_application(
        create_draw_application_payload(pool["id"], applicant["id"]), OFFICER)
    validate_error(res, "ERR_ENTRY_CLOSED", expected_status=409)


def test_harvest_season_close_exclusive_upper_bound(api):
    """PRD §3.4: "the `season_close` instant (ISO 8601 UTC, exclusive — so an admissible
    harvest instant is one at or after the open instant and strictly before the close
    instant)".
    PRD §3.9: "the `harvest_datetime` must fall within the bound season's window — at or after
    `season_open` and strictly before `season_close` — and the season must be `OPEN` at report
    time; a violation of either is rejected with `ERR_SEASON_NOT_OPEN`."

    Design: Difficulty/resource_temporal_overlap/harvest_season_close_exclusive_upper_bound
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])
    set_clock("2026-10-01T00:00:00Z")

    # harvest_datetime exactly at season_close is NOT strictly before -> rejected.
    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-10-01T00:00:00Z", quantity=1),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_SEASON_NOT_OPEN", expected_status=409)


def test_harvest_at_season_open_inclusive_lower_bound(api):
    """PRD §3.4: "an admissible harvest instant is one at or after the open instant and
    strictly before the close instant".
    PRD §3.9: "the `harvest_datetime` must fall within the bound season's window — at or after
    `season_open` and strictly before `season_close`".

    Design: Difficulty/resource_temporal_overlap/harvest_season_close_exclusive_upper_bound
    """
    set_clock("2026-09-15T00:00:00Z")
    season = create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                           season_close="2026-10-01T00:00:00Z", bag_limit=2,
                           draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-OTC",
                                            base_fee_cents=4500)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")
    license_ = issue_otc_license(applicant["id"], product["id"])

    # harvest_datetime exactly at season_open is "at or after open" -> admissible.
    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-09-01T00:00:00Z", quantity=1),
        make_applicant_headers(applicant["id"]))
    report = validate_success(res, 201)
    assert report["status"] == "SUBMITTED"


def test_bag_budget_excludes_rejected_reports(api):
    """PRD §3.9: "the season bag budget counts the summed `quantity` of all harvest reports filed under the applicant's licenses for that season whose status is `SUBMITTED` or `ACCEPTED` (reports in `REJECTED` are excluded and do not count)."

    Design: Corner/calculations/bag_budget_excludes_rejected_reports
    """
    season, product, applicant, license_ = setup_resident_with_tag_license(
        bag_limit=2, clock="2026-09-15T00:00:00Z")
    accepted = submit_harvest(license_["id"], applicant["id"],
                              harvest_datetime="2026-09-15T08:00:00Z", quantity=1)
    rejected = submit_harvest(license_["id"], applicant["id"],
                              harvest_datetime="2026-09-16T08:00:00Z", quantity=1)
    validate_success(api.accept_harvest_report(accepted["id"], WARDEN), 200)
    validate_success(api.reject_harvest_report(rejected["id"], WARDEN), 200)

    budget = validate_success(api.get_bag_budget(license_["id"], WARDEN), 200)
    assert budget["counted"] == 1, (
        f"counted should exclude the REJECTED report, got {budget['counted']}")
    assert budget["remaining"] == 1


def test_harvest_reject_releases_budget(api):
    """PRD §3.9: "Rejecting it moves the report `SUBMITTED → REJECTED` and releases its quantity from the budget so that it no longer counts."

    Design: Corner/state_machines/harvest_report_reject_releases_budget
    """
    season, product, applicant, license_ = setup_resident_with_tag_license(
        bag_limit=2, clock="2026-09-15T00:00:00Z")
    report = submit_harvest(license_["id"], applicant["id"],
                            harvest_datetime="2026-09-15T08:00:00Z", quantity=1)

    rejected = validate_success(api.reject_harvest_report(report["id"], WARDEN), 200)
    assert rejected["status"] == "REJECTED"
    budget = validate_success(api.get_bag_budget(license_["id"], OFFICER), 200)
    assert budget["counted"] == 0
    assert budget["remaining"] == 2


def test_harvest_negative_quantity_rejected(api):
    """PRD §3.9: "the `quantity` taken, which must be at least 1."
    PRD §2.6: "Field-level request validation — required fields present, enum values legal,
    numeric fields within their declared bounds — is the lowest-priority check and yields
    `ERR_INVALID_REQUEST`".

    Design: Corner/errors/error_invalid_request_negative_quantity
    """
    season, product, applicant, license_ = setup_resident_with_tag_license(
        bag_limit=2, clock="2026-09-15T00:00:00Z")

    res = api.create_harvest_report(
        create_harvest_report_payload(license_["id"],
                                      harvest_datetime="2026-09-15T08:00:00Z", quantity=0),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_entry_closed_triggerable(api):
    """PRD §3.6: "an attempt once the pool is no longer accepting or the deadline has arrived
    is rejected with `ERR_ENTRY_CLOSED`."

    Design: Difficulty/resource_temporal_overlap/draw_entry_deadline_exclusive_upper_bound
    """
    set_clock("2026-05-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-05-10T00:00:00Z")
    applicant = create_applicant(full_name="A1")
    set_clock("2026-05-11T00:00:00Z")  # past the deadline

    res = api.create_draw_application(
        create_draw_application_payload(pool["id"], applicant["id"]), OFFICER)
    validate_error(res, "ERR_ENTRY_CLOSED", expected_status=409)
