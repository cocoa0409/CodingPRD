"""Error selection: not-found families, schema range checks and state refusals.

Each test assembles its own account through the published endpoints, since the
database is empty and the logical clock reads 2026-08-01T00:00:00Z when the test
begins.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers import factories
from test_helpers import fixtures
from test_helpers.assertions import allocation_line

# A small FIRE_RESISTIVE / INLAND warehouse: 6 risk points, so it screens
# ELIGIBLE and rates to QUOTED, and it prices at 320000 cents over a 200-day
# term (4000 rated units at 80 cents, no cat, duration, soft-cost or renovation
# load and no deductible credit).
CEDAR_MILLS_PROJECT = {
    "engineering_grade": "A",
    "name": "Cedar Mills Warehouse",
    "site_address": "12 Mill Rd, Cedar",
    "construction_type": "FIRE_RESISTIVE",
    "project_kind": "NEW_CONSTRUCTION",
    "hard_cost_value_cents": 400000000,
    "cat_zone": "INLAND",
    "planned_start_date": "2026-09-01T00:00:00Z",
    "projected_completion_date": "2027-03-01T00:00:00Z",
}

CEDAR_MILLS_POLICY = {
    "term_start_date": "2026-09-01T00:00:00Z",
    "term_end_date": "2027-03-20T00:00:00Z",
    "includes_existing_structure": False,
    "deductible_tier": "STANDARD_25K",
    "limit_cents": 200000000,
    "daily_delay_rate_cents": 0,
}


def _cedar_mills_project_overrides(**extra):
    overrides = dict(CEDAR_MILLS_PROJECT)
    overrides.update(extra)
    return overrides


def _cedar_mills_in_force(parts, **project_extra):
    return fixtures.in_force_account(
        parts=parts,
        project_overrides=_cedar_mills_project_overrides(**project_extra),
        **CEDAR_MILLS_POLICY)


def test_every_not_found_error_id_is_reachable_from_an_empty_database():
    """Each entity family answers an unknown id with its own 404 error.

    Section 2.11 resolves "existence of every identifier in the request path" with
    "the collection-specific 404 codes", and section 5 lists one not-found id per
    entity family rather than a shared generic code.

    Design: Corner/errors/corner_every_not_found_error_id_is_reachable_from_an_empty_database
    """
    unknown = "00000000-0000-4000-8000-0000000000{:02x}"
    reads = (
        (api_client.get_project, "ERR_PROJECT_NOT_FOUND"),
        (api_client.get_policy, "ERR_POLICY_NOT_FOUND"),
        (api_client.get_coverage_part, "ERR_COVERAGE_PART_NOT_FOUND"),
        (api_client.get_named_insured_interest, "ERR_INTEREST_NOT_FOUND"),
        (api_client.get_extension_endorsement, "ERR_ENDORSEMENT_NOT_FOUND"),
        (api_client.get_claim, "ERR_CLAIM_NOT_FOUND"),
        (api_client.get_loss_payment, "ERR_PAYMENT_NOT_FOUND"),
        (api_client.get_testing_notice, "ERR_NOTICE_NOT_FOUND"),
        (api_client.get_facility, "ERR_FACILITY_NOT_FOUND"),
        (api_client.get_storage_assignment, "ERR_ASSIGNMENT_NOT_FOUND"),
    )
    for index, (read, error_id) in enumerate(reads, start=1):
        validate_error(
            read(unknown.format(index), fixtures.UW),
            error_id, expected_status=404)

    # The reads created nothing.
    for listing in (api_client.list_projects, api_client.list_policies,
                    api_client.list_claims, api_client.list_facilities):
        rows, meta = validate_paginated(listing(fixtures.UW))
        assert meta["total_count"] == 0, meta
        assert meta["has_more"] is False, meta
        assert rows == [], rows


def test_body_foreign_key_not_found_outranks_the_body_schema_check():
    """An unresolvable body foreign key beats a malformed field in the same body.

    Section 2.11 places "existence of every foreign key supplied in the request
    body" at step 5 and "request-body schema conformance" at step 8, so a body
    that names a missing policy and also carries a negative sublimit is answered
    with the policy's own not-found error.

    Design: Corner/errors/corner_body_foreign_key_not_found_outranks_the_body_schema_check
    """
    account = fixtures.draft_account(
        parts=(), with_owner=False,
        project_overrides=_cedar_mills_project_overrides(),
        **CEDAR_MILLS_POLICY)

    validate_error(
        api_client.create_coverage_part(
            {
                "policy_id": "00000000-0000-4000-8000-0000000000ff",
                "part_type": "MATERIALS_ON_SITE",
                "sublimit_cents": -5,
            },
            fixtures.UW),
        "ERR_POLICY_NOT_FOUND", expected_status=404)

    # The interest endpoint reports the missing policy, not a missing interest.
    validate_error(
        api_client.create_named_insured_interest(
            {
                "policy_id": "00000000-0000-4000-8000-0000000000fe",
                "party_name": "Ghost Owner",
                "party_role": "OWNER",
                "insurable_interest_pct": 100,
            },
            fixtures.UW),
        "ERR_POLICY_NOT_FOUND", expected_status=404)

    # With the foreign key resolvable the negative sublimit is the top defect.
    validate_error(
        api_client.create_coverage_part(
            {
                "policy_id": account.policy_id,
                "part_type": "MATERIALS_ON_SITE",
                "sublimit_cents": -5,
            },
            fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    _parts, parts_meta = validate_paginated(
        api_client.list_policy_coverage_parts(account.policy_id, fixtures.UW))
    assert parts_meta["total_count"] == 0, parts_meta
    _interests, interests_meta = validate_paginated(
        api_client.list_policy_named_insured_interests(
            account.policy_id, fixtures.UW))
    assert interests_meta["total_count"] == 0, interests_meta


def test_invalid_request_covers_missing_fields_bad_enums_and_negative_money():
    """One error id answers an absent field, a bad enum and negative money alike.

    Section 2.11 step 8 requires "every non-optional field present, every enum
    value within its declared set, money amounts non-negative where declared",
    all reported as ERR_INVALID_REQUEST.

    Design: Corner/errors/corner_invalid_request_covers_missing_fields_bad_enums_and_negative_money
    """
    missing_type = {
        "name": "Missing Type",
        "site_address": "9 Void Rd",
        "project_kind": "NEW_CONSTRUCTION",
        "hard_cost_value_cents": 400000000,
        "cat_zone": "INLAND",
        "planned_start_date": "2026-09-01T00:00:00Z",
        "projected_completion_date": "2027-03-01T00:00:00Z",
    }
    validate_error(
        api_client.create_project(missing_type, fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    bad_zone = dict(missing_type, name="Bad Zone",
                    construction_type="FIRE_RESISTIVE",
                    cat_zone="TORNADO_ALLEY")
    validate_error(
        api_client.create_project(bad_zone, fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    negative_value = dict(missing_type, name="Negative Value",
                          construction_type="FIRE_RESISTIVE",
                          hard_cost_value_cents=-1)
    validate_error(
        api_client.create_project(negative_value, fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    well_formed = dict(missing_type, name="Well Formed",
                       construction_type="FIRE_RESISTIVE")
    created = validate_success(
        api_client.create_project(well_formed, fixtures.UW),
        expected_status=201)
    assert created["status"] == "SUBMITTED", created
    assert created["submission_risk_score"] is None, created
    assert created["version"] == 1, created

    # Exactly the one well-formed row survives.
    rows, meta = validate_paginated(api_client.list_projects(fixtures.UW))
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [created["id"]], rows


def test_invalid_request_covers_the_range_constrained_fields():
    """The declared numeric ranges are enforced ahead of every business rule.

    Section 2.11 step 8 spells the ranges out: "requested_extension_days between 1
    and 180 inclusive, continuing_pm_weeks between 0 and 12 inclusive,
    insurable_interest_pct between 0 and 100 inclusive, loss_payee_priority at
    least 1 when present, loss_items non-empty for every peril other than DELAY".

    Design: Corner/errors/corner_invalid_request_covers_the_range_constrained_fields
    """
    account = _cedar_mills_in_force((("MATERIALS_ON_SITE", 100000000),))
    claim = fixtures.report_claim(
        account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
        description="Formwork fire on the third floor")

    # 101 percent is out of range before the aggregate-share rule is reached.
    validate_error(
        api_client.create_named_insured_interest(
            factories.create_interest_payload(
                account.policy_id, party_role="LENDER",
                insurable_interest_pct=101,
                party_name="Overweight Lender", loss_payee_priority=2),
            fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    # loss_payee_priority must be at least 1 even with no other payee present.
    validate_error(
        api_client.create_named_insured_interest(
            factories.create_interest_payload(
                account.policy_id, party_role="LENDER",
                insurable_interest_pct=0,
                party_name="Zero Priority Lender", loss_payee_priority=0),
            fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    policy_version = account.refresh_policy()["version"]
    validate_error(
        api_client.create_extension_endorsement(
            factories.create_endorsement_payload(
                account.policy_id, policy_version, 181,
                "2027-08-29T00:00:00Z"),
            fixtures.UW),
        "ERR_INVALID_REQUEST", expected_status=400)

    # continuing_pm_weeks is not silently clamped to the twelve-week maximum.
    validate_error(
        api_client.adjust_claim(
            claim["id"],
            factories.adjust_claim_payload(
                adjustment_basis="RECONSTRUCTION_COST",
                loss_items=[factories.loss_item("MATERIALS_ON_SITE", 10000000)],
                continuing_pm_weeks=13),
            fixtures.CA),
        "ERR_INVALID_REQUEST", expected_status=400)

    validate_error(
        api_client.adjust_claim(
            claim["id"],
            factories.adjust_claim_payload(
                adjustment_basis="RECONSTRUCTION_COST", loss_items=[],
                continuing_pm_weeks=12),
            fixtures.CA),
        "ERR_INVALID_REQUEST", expected_status=400)

    _interests, interests_meta = validate_paginated(
        api_client.list_policy_named_insured_interests(
            account.policy_id, fixtures.UW))
    assert interests_meta["total_count"] == 1, interests_meta
    _endorsements, endorsement_meta = validate_paginated(
        api_client.list_policy_extension_endorsements(
            account.policy_id, fixtures.UW))
    assert endorsement_meta["total_count"] == 0, endorsement_meta

    unchanged = validate_success(
        api_client.get_claim(claim["id"], fixtures.CA))
    assert unchanged["adjustment_status"] == "REPORTED", unchanged
    assert unchanged["allocation_lines"] == [], unchanged


def test_voiding_an_already_voided_payment_hits_the_payment_state_error():
    """The refused second void must not credit the coverage part a second time.

    Voiding "reverses the erosion it created, restores the claim's outstanding
    reserve and returns the claim to UNPAID"; a payment that is already VOIDED
    cannot be voided again and answers ERR_INVALID_PAYMENT_STATE.

    Design: Corner/errors/corner_voiding_an_already_voided_payment_hits_the_payment_state_error
    """
    account = _cedar_mills_in_force((("MATERIALS_ON_SITE", 60000000),))
    part_id = account.part("MATERIALS_ON_SITE")["id"]
    claim = fixtures.report_claim(
        account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
        description="Formwork fire on the third floor")
    adjusted = fixtures.adjust_claim(
        account, claim,
        loss_items=[factories.loss_item("MATERIALS_ON_SITE", 15000000)],
        adjustment_basis="ACTUAL_LOSS")
    assert adjusted["indemnity_cents"] == 12500000, adjusted
    settled = fixtures.settle_claim(adjusted, headers=fixtures.CA2)
    payment = fixtures.issue_payment(
        account, settled, "MATERIALS_ON_SITE", 12500000)
    assert account.part("MATERIALS_ON_SITE")["eroded_cents"] == 12500000, account.parts

    voided = fixtures.void_payment(account, payment, headers=fixtures.UM)
    assert voided["status"] == "VOIDED", voided
    assert voided["voided_by_user_id"] == fixtures.UM["X-User-ID"], voided

    part = validate_success(api_client.get_coverage_part(part_id, fixtures.UW))
    assert part["eroded_cents"] == 0, part
    assert part["available_cents"] == 60000000, part
    reopened_reserve = validate_success(
        api_client.get_claim(claim["id"], fixtures.CA))
    assert reopened_reserve["paid_cents"] == 0, reopened_reserve
    assert reopened_reserve["outstanding_reserve_cents"] == 12500000, reopened_reserve
    assert reopened_reserve["payment_status"] == "UNPAID", reopened_reserve
    assert reopened_reserve["adjustment_status"] == "SETTLED", reopened_reserve

    validate_error(
        api_client.void_loss_payment(payment["id"], fixtures.UM),
        "ERR_INVALID_PAYMENT_STATE", expected_status=409)

    # The credit is not applied twice: erosion stays at zero, never negative.
    part_after = validate_success(api_client.get_coverage_part(part_id, fixtures.UW))
    assert part_after["eroded_cents"] == 0, part_after
    policy = account.refresh_policy()
    assert policy["eroded_total_cents"] == 0, policy

    payments, meta = validate_paginated(api_client.list_loss_payments(
        fixtures.CA, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1, meta
    assert [row["status"] for row in payments] == ["VOIDED"], payments


def test_repeating_the_release_and_the_notice_decision_hits_their_own_state_errors():
    """Two entity families each answer their own repeat-action state error.

    A released assignment is terminal, so a second release is refused with
    ERR_INVALID_ASSIGNMENT_STATE and the facility's committed value is not
    credited twice; a decided notice is terminal too and a second decision is
    refused with ERR_INVALID_NOTICE_STATE, leaving the recorded decision intact.

    Design: Corner/errors/corner_repeating_the_release_and_the_notice_decision_hits_their_own_state_errors
    """
    account = _cedar_mills_in_force((
        ("MATERIALS_ON_SITE", 100000000),
        ("TEMPORARY_STORAGE", 10000000),
    ))
    facility = fixtures.register_facility(
        headers=fixtures.RE, name="Northside Warehouse", site_code="WH-01",
        distance_from_site_miles=12, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")
    assignment = fixtures.assign_storage(
        account, facility, 5000000, "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z", headers=fixtures.RE)
    notice = fixtures.schedule_notice(
        account, "2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z",
        system_type="SPRINKLER_HYDROSTATIC", headers=fixtures.RE)

    released = fixtures.release_storage(assignment, headers=fixtures.RE)
    assert released["status"] == "RELEASED", released
    assert released["release_reason"] == "MANUAL", released
    # released_at is stamped from the logical clock, not from the window end.
    assert released["released_at"] == "2026-09-01T00:00:00Z", released

    decided = fixtures.decide_notice(notice, "APPROVE", headers=fixtures.RE)
    assert decided["status"] == "APPROVED", decided
    assert decided["decided_by_user_id"] == fixtures.RE["X-User-ID"], decided

    validate_error(
        api_client.release_storage_assignment(assignment["id"], fixtures.RE),
        "ERR_INVALID_ASSIGNMENT_STATE", expected_status=409)
    validate_error(
        api_client.decide_testing_notice(
            notice["id"],
            {"decision": "REJECT", "rejection_reason": "Second thoughts"},
            fixtures.RE),
        "ERR_INVALID_NOTICE_STATE", expected_status=409)

    refreshed_facility = validate_success(
        api_client.get_facility(facility["id"], fixtures.RE))
    assert refreshed_facility["committed_value_cents"] == 0, refreshed_facility
    final_notice = validate_success(
        api_client.get_testing_notice(notice["id"], fixtures.RE))
    assert final_notice["status"] == "APPROVED", final_notice
    assert final_notice["rejection_reason"] is None, final_notice


def test_the_fourth_resubmission_of_an_endorsement_is_refused():
    """Three resubmissions are accepted; the fourth is a hard refusal.

    An endorsement may be returned for information and resubmitted, but "an
    endorsement may be resubmitted at most three times; a fourth resubmission is
    refused with ERR_RESUBMISSION_LIMIT_REACHED".

    Design: Corner/errors/corner_the_fourth_resubmission_of_an_endorsement_is_refused
    """
    account = _cedar_mills_in_force((("MATERIALS_ON_SITE", 100000000),))
    assert account.policy["written_premium_cents"] == 320000, account.policy
    assert account.policy["original_term_days"] == 200, account.policy

    endorsement = fixtures.file_endorsement(
        account, 20, revised_completion_date="2027-03-21T00:00:00Z")
    # 320000 / 200 = 1600 a day, so twenty days of slip prices at 32000.
    assert endorsement["additional_premium_cents"] == 32000, endorsement

    notes = ("Send the updated critical path", "Still missing the weather log",
             "Weather log unreadable")
    for cycle, note in enumerate(notes, start=1):
        returned = validate_success(api_client.return_endorsement_for_info(
            endorsement["id"], {"info_request_note": note}, fixtures.UM))
        assert returned["status"] == "RETURNED_FOR_INFO", returned
        resubmitted = validate_success(api_client.resubmit_endorsement(
            endorsement["id"],
            factories.resubmit_endorsement_payload(
                20, "2027-03-21T00:00:00Z", slip_reason="WEATHER"),
            fixtures.UW))
        assert resubmitted["resubmission_count"] == cycle, resubmitted
        # Every resubmission re-prices from scratch against a still-unextended term.
        assert resubmitted["additional_premium_cents"] == 32000, resubmitted
        assert float(resubmitted["slip_factor"]) == 1.00, resubmitted

    fourth_return = validate_success(api_client.return_endorsement_for_info(
        endorsement["id"], {"info_request_note": "Final chance"}, fixtures.UM))
    assert fourth_return["status"] == "RETURNED_FOR_INFO", fourth_return

    validate_error(
        api_client.resubmit_endorsement(
            endorsement["id"],
            factories.resubmit_endorsement_payload(
                20, "2027-03-21T00:00:00Z", slip_reason="WEATHER"),
            fixtures.UW),
        "ERR_RESUBMISSION_LIMIT_REACHED", expected_status=409)

    final = validate_success(api_client.get_extension_endorsement(
        endorsement["id"], fixtures.UW))
    assert final["status"] == "RETURNED_FOR_INFO", final
    assert final["resubmission_count"] == 3, final
    assert final["additional_premium_cents"] == 32000, final

    policy = account.refresh_policy()
    assert policy["cumulative_extension_days"] == 0, policy
    assert policy["term_end_date"] == "2027-03-20T00:00:00Z", policy


def test_the_third_reopening_of_a_claim_is_refused_after_a_denial_and_a_closure():
    """One counter governs reopening whether the claim was denied or closed.

    A claim may be reopened from DENIED or from CLOSED, but "a claim may be
    reopened at most twice; a third reopen is refused with
    ERR_REOPEN_LIMIT_REACHED".

    Design: Corner/errors/corner_the_third_reopening_of_a_claim_is_refused_after_a_denial_and_a_closure
    """
    account = _cedar_mills_in_force((("MATERIALS_ON_SITE", 60000000),))
    part_id = account.part("MATERIALS_ON_SITE")["id"]
    claim = fixtures.report_claim(
        account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
        description="Formwork fire on the third floor")

    denied = validate_success(api_client.adjust_claim(
        claim["id"], factories.adjust_claim_payload(outcome="DENY"),
        fixtures.CA))
    assert denied["adjustment_status"] == "DENIED", denied
    assert denied["indemnity_cents"] == 0, denied
    assert denied["allocation_lines"] == [], denied

    first_reopen = validate_success(
        api_client.reopen_claim(claim["id"], fixtures.CA))
    assert first_reopen["adjustment_status"] == "REOPENED", first_reopen
    assert first_reopen["reopen_count"] == 1, first_reopen

    adjusted = fixtures.adjust_claim(
        account, claim,
        loss_items=[factories.loss_item("MATERIALS_ON_SITE", 15000000)],
        adjustment_basis="ACTUAL_LOSS")
    assert adjusted["indemnity_cents"] == 12500000, adjusted
    settled = fixtures.settle_claim(adjusted, headers=fixtures.CA2)
    fixtures.issue_payment(account, settled, "MATERIALS_ON_SITE", 12500000)

    second_reopen = validate_success(
        api_client.reopen_claim(claim["id"], fixtures.CA))
    assert second_reopen["reopen_count"] == 2, second_reopen
    # Reopening leaves the money already paid and the erosion it caused alone.
    assert second_reopen["paid_cents"] == 12500000, second_reopen

    readjusted = fixtures.adjust_claim(
        account, claim,
        loss_items=[factories.loss_item("MATERIALS_ON_SITE", 30000000)],
        adjustment_basis="ACTUAL_LOSS")
    assert readjusted["indemnity_cents"] == 27500000, readjusted
    assert readjusted["outstanding_reserve_cents"] == 15000000, readjusted
    resettled = fixtures.settle_claim(readjusted, headers=fixtures.CA2)
    balance = fixtures.issue_payment(
        account, resettled, "MATERIALS_ON_SITE", 15000000)
    assert balance["status"] == "ISSUED", balance

    validate_error(
        api_client.reopen_claim(claim["id"], fixtures.CA),
        "ERR_REOPEN_LIMIT_REACHED", expected_status=409)

    final = validate_success(api_client.get_claim(claim["id"], fixtures.CA))
    assert final["adjustment_status"] == "CLOSED", final
    assert final["payment_status"] == "PAID", final
    assert final["reopen_count"] == 2, final
    assert final["paid_cents"] == 27500000, final
    assert final["outstanding_reserve_cents"] == 0, final
    assert final["total_incurred_cents"] == 27500000, final

    part = validate_success(api_client.get_coverage_part(part_id, fixtures.UW))
    assert part["eroded_cents"] == 27500000, part
    assert part["available_cents"] == 32500000, part

    payments, meta = validate_paginated(api_client.list_loss_payments(
        fixtures.CA, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2, meta
    assert [row["status"] for row in payments] == ["ISSUED", "ISSUED"], payments


def test_mitigation_plan_is_demanded_only_for_grade_c_and_d_hazardous_notices():
    """The plan is demanded only where a poor grade meets a hazardous window.

    A notice that declares hot work or a charged water system on a project graded
    C or D must carry a mitigation_plan_ref, otherwise
    ERR_MITIGATION_PLAN_REQUIRED; a benign notice, or the same hazardous notice on
    a better-graded project, needs no plan. The loss-control gate is also
    evaluated ahead of the window-conflict gate.

    Design: Corner/errors/corner_mitigation_plan_is_demanded_only_for_grade_c_and_d_hazardous_notices
    """
    poor_grade = fixtures.screen_project(
        fixtures.submit_project(**_cedar_mills_project_overrides()),
        engineering_grade="C", loss_control_report_ref="LC-2026-441")
    assert poor_grade["engineering_grade"] == "C", poor_grade
    # FIRE_RESISTIVE 6 + INLAND 0 + value 0 + duration 0 = 6, well under 90.
    assert poor_grade["submission_risk_score"] == 6, poor_grade
    assert poor_grade["status"] == "ELIGIBLE", poor_grade

    good_grade = fixtures.screen_project(
        fixtures.submit_project(**_cedar_mills_project_overrides(
            name="Cedar Mills Annex", site_address="14 Mill Rd, Cedar")),
        engineering_grade="A", loss_control_report_ref="LC-2026-442")

    hazardous_water = factories.create_testing_notice_payload(
        poor_grade["id"], "2026-10-05T08:00:00Z", "2026-10-05T17:00:00Z",
        system_type="SPRINKLER_HYDROSTATIC", water_charged=True)
    validate_error(
        api_client.create_testing_notice(hazardous_water, fixtures.RE),
        "ERR_MITIGATION_PLAN_REQUIRED", expected_status=422)

    hazardous_hot_work = factories.create_testing_notice_payload(
        poor_grade["id"], "2026-10-05T08:00:00Z", "2026-10-05T17:00:00Z",
        system_type="ELECTRICAL_ENERGIZATION", hot_work=True)
    validate_error(
        api_client.create_testing_notice(hazardous_hot_work, fixtures.RE),
        "ERR_MITIGATION_PLAN_REQUIRED", expected_status=422)

    benign = validate_success(api_client.create_testing_notice(
        factories.create_testing_notice_payload(
            poor_grade["id"], "2026-10-05T08:00:00Z", "2026-10-05T17:00:00Z",
            system_type="ELEVATOR"),
        fixtures.RE), expected_status=201)
    assert benign["status"] == "SCHEDULED", benign
    assert benign["hot_work"] is False, benign
    assert benign["water_charged"] is False, benign
    assert benign["mitigation_plan_ref"] is None, benign

    planned = validate_success(api_client.create_testing_notice(
        factories.create_testing_notice_payload(
            poor_grade["id"], "2026-10-07T08:00:00Z", "2026-10-07T17:00:00Z",
            system_type="SPRINKLER_HYDROSTATIC", water_charged=True,
            mitigation_plan_ref="MIT-2026-014"),
        fixtures.RE), expected_status=201)
    assert planned["status"] == "SCHEDULED", planned
    assert planned["mitigation_plan_ref"] == "MIT-2026-014", planned

    # The identical hazardous notice is admissible on the grade A project.
    on_good_grade = validate_success(api_client.create_testing_notice(
        factories.create_testing_notice_payload(
            good_grade["id"], "2026-10-05T08:00:00Z", "2026-10-05T17:00:00Z",
            system_type="SPRINKLER_HYDROSTATIC", water_charged=True),
        fixtures.RE), expected_status=201)
    assert on_good_grade["status"] == "SCHEDULED", on_good_grade

    # This window also collides with the ELEVATOR notice, but the loss-control
    # gate is evaluated before the window-conflict gate.
    validate_error(
        api_client.create_testing_notice(
            factories.create_testing_notice_payload(
                poor_grade["id"], "2026-10-05T10:00:00Z", "2026-10-05T12:00:00Z",
                system_type="ELECTRICAL_ENERGIZATION", hot_work=True),
            fixtures.RE),
        "ERR_MITIGATION_PLAN_REQUIRED", expected_status=422)

    notices, meta = validate_paginated(api_client.list_project_testing_notices(
        poor_grade["id"], fixtures.RE))
    assert meta["total_count"] == 2, meta
    assert {row["id"] for row in notices} == {benign["id"], planned["id"]}, notices


def test_storage_window_bounds_outrank_the_facility_distance_cap():
    """The window gate answers first, and the distance cap includes 100 miles.

    A storage window has to sit inside the policy term and may not run past the
    adjusted completion date; a facility further than 100 miles from the site
    cannot hold insured materials. The window check is evaluated before the
    structural distance check.

    Design: Corner/errors/corner_storage_window_bounds_outrank_the_facility_distance_cap
    """
    account = _cedar_mills_in_force((
        ("MATERIALS_ON_SITE", 100000000),
        ("TEMPORARY_STORAGE", 10000000),
    ))
    assert account.policy["adjusted_completion_date"] == "2027-03-01T00:00:00Z", account.policy
    assert account.policy["term_end_date"] == "2027-03-20T00:00:00Z", account.policy

    near = fixtures.register_facility(
        headers=fixtures.RE, name="Northside Warehouse", site_code="WH-NEAR",
        distance_from_site_miles=12, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")
    edge = fixtures.register_facility(
        headers=fixtures.RE, name="Ridgeline Depot", site_code="WH-EDGE",
        distance_from_site_miles=100, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")
    far = fixtures.register_facility(
        headers=fixtures.RE, name="Far Valley Store", site_code="WH-FAR",
        distance_from_site_miles=101, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")

    def assign(facility, window_start, window_end):
        return api_client.create_storage_assignment(
            factories.create_storage_assignment_payload(
                account.policy_id, facility["id"], 5000000,
                window_start, window_end),
            fixtures.RE)

    validate_error(
        assign(far, "2026-09-01T00:00:00Z", "2027-03-01T00:00:00Z"),
        "ERR_FACILITY_TOO_DISTANT", expected_status=422)
    # 2027-03-02 is inside the term but past the adjusted completion date.
    validate_error(
        assign(near, "2026-09-01T00:00:00Z", "2027-03-02T00:00:00Z"),
        "ERR_WINDOW_OUTSIDE_POLICY_TERM", expected_status=422)
    validate_error(
        assign(near, "2026-08-31T00:00:00Z", "2027-01-01T00:00:00Z"),
        "ERR_WINDOW_OUTSIDE_POLICY_TERM", expected_status=422)
    # Both rules are broken here; the window gate is the one that answers.
    validate_error(
        assign(far, "2026-09-01T00:00:00Z", "2027-03-02T00:00:00Z"),
        "ERR_WINDOW_OUTSIDE_POLICY_TERM", expected_status=422)

    accepted = validate_success(
        assign(edge, "2026-09-01T00:00:00Z", "2027-03-01T00:00:00Z"),
        expected_status=201)
    assert accepted["status"] == "APPROVED", accepted

    edge_after = validate_success(api_client.get_facility(edge["id"], fixtures.RE))
    assert edge_after["committed_value_cents"] == 5000000, edge_after
    for facility in (near, far):
        refused = validate_success(
            api_client.get_facility(facility["id"], fixtures.RE))
        assert refused["committed_value_cents"] == 0, refused

    _rows, meta = validate_paginated(api_client.list_policy_storage_assignments(
        account.policy_id, fixtures.UW))
    assert meta["total_count"] == 1, meta


def test_adjust_rejects_a_repeated_part_type_and_an_unscheduled_one():
    """A duplicated part type is refused rather than merged, and so is an unscheduled one.

    Every entry in loss_items must name a distinct coverage part, otherwise
    ERR_DUPLICATE_LOSS_ITEM; every named part must be scheduled on the policy,
    otherwise ERR_COVERAGE_PART_MISSING. A refused adjustment leaves the claim as
    it was.

    Design: Corner/errors/corner_adjust_rejects_a_repeated_part_type_and_an_unscheduled_one
    """
    account = _cedar_mills_in_force((("MATERIALS_ON_SITE", 60000000),))
    part_id = account.part("MATERIALS_ON_SITE")["id"]
    claim = fixtures.report_claim(
        account, peril="FIRE", loss_date="2026-11-15T00:00:00Z",
        description="Formwork fire on the third floor")

    # The two MATERIALS_ON_SITE entries must not be merged into one 15000000 line.
    validate_error(
        api_client.adjust_claim(
            claim["id"],
            factories.adjust_claim_payload(
                adjustment_basis="ACTUAL_LOSS",
                loss_items=[
                    factories.loss_item("MATERIALS_ON_SITE", 10000000),
                    factories.loss_item("MATERIALS_ON_SITE", 5000000),
                ]),
            fixtures.CA),
        "ERR_DUPLICATE_LOSS_ITEM", expected_status=422)

    # WATER_DAMAGE was never scheduled on this policy.
    validate_error(
        api_client.adjust_claim(
            claim["id"],
            factories.adjust_claim_payload(
                adjustment_basis="ACTUAL_LOSS",
                loss_items=[factories.loss_item("WATER_DAMAGE", 10000000)]),
            fixtures.CA),
        "ERR_COVERAGE_PART_MISSING", expected_status=422)

    untouched = validate_success(api_client.get_claim(claim["id"], fixtures.CA))
    assert untouched["adjustment_status"] == "REPORTED", untouched
    assert untouched["indemnity_cents"] == 0, untouched
    assert untouched["allocation_lines"] == [], untouched
    assert untouched["adjusted_by_user_id"] is None, untouched

    accepted = validate_success(api_client.adjust_claim(
        claim["id"],
        factories.adjust_claim_payload(
            adjustment_basis="ACTUAL_LOSS",
            loss_items=[factories.loss_item("MATERIALS_ON_SITE", 10000000)]),
        fixtures.CA))
    assert accepted["adjustment_status"] == "ADJUSTED", accepted
    assert accepted["indemnity_cents"] == 7500000, accepted
    assert len(accepted["allocation_lines"]) == 1, accepted
    line = allocation_line(accepted, "MATERIALS_ON_SITE")
    assert line["covered_basis_cents"] == 10000000, line
    assert line["deductible_applied_cents"] == 2500000, line
    assert line["allocated_cents"] == 7500000, line

    # Adjusting reserves nothing: erosion waits for a payment.
    part = validate_success(api_client.get_coverage_part(part_id, fixtures.UW))
    assert part["eroded_cents"] == 0, part
