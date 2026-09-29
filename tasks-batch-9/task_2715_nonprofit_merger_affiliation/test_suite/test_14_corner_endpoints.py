"""Endpoint-behaviour compliance tests.

Each test exercises one endpoint contract end to end: the round trip between a
write and the reads that must observe it, the derived figures the read must
carry, and the pagination and filter semantics of PRD 2.3.

The harness restarts the server and empties the registry before every test, so
each test registers its own organizations and walks its own deal forward.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_full_common_fields,
    assert_money_equals,
    assert_null,
    assert_status,
    assert_three_fractional_digits,
    assert_version_is,
    find_by_id,
)
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_strategy_officer_headers,
)


def test_programs_round_trip_through_the_owning_organization_listing(api):
    """A registered program is born ACTIVE with no transfer recipient and is reachable
    only from its own organization's program listing, which filters and paginates.

    PRD 3.1 states that a new program's continuity_status is ACTIVE and its
    transferred_to_org_id is null, and PRD 4 defines the organization program
    listing as "the programs operated by one organization", filterable by
    service_category and by continuity_status. PRD 2.3 fixes the list contract:
    rows come back sorted by created_at ascending, total_count counts the rows
    that match the filter rather than the page, and limit/offset select the page.
    PRD 2.4 starts every mutable entity at version 1.

    Design: Corner/endpoints/programs_round_trip_through_the_owning_organization_listing
    """
    ctx = fx.setup_two_orgs(api)
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    prog_one = validate_success(
        api.create_program(
            f.program_payload(
                org_a,
                name="After-School Mentoring",
                service_category="YOUTH_MENTORING",
                county_code="CA-ALAMEDA",
                annual_expense_cents=12000000,
                clients_served=400,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    prog_two = validate_success(
        api.create_program(
            f.program_payload(
                org_a,
                name="Weekend Meal Pantry",
                service_category="FOOD_SECURITY",
                county_code="CA-SONOMA",
                annual_expense_cents=8000000,
                clients_served=900,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    prog_three = validate_success(
        api.create_program(
            f.program_payload(
                org_b,
                name="Harbor Peer Mentors",
                service_category="YOUTH_MENTORING",
                county_code="CA-ALAMEDA",
                annual_expense_cents=9000000,
                clients_served=300,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )

    for name, prog in (("prog_one", prog_one), ("prog_two", prog_two), ("prog_three", prog_three)):
        assert_full_common_fields(prog, name)
        assert_field(prog, "continuity_status", "ACTIVE")
        assert_null(prog, "transferred_to_org_id")
        assert_version_is(prog, 1, name)
    assert_field(prog_one, "org_id", org_a)
    assert_field(prog_three, "org_id", org_b)

    rows, meta = validate_paginated(api.list_organization_programs(org_a, PLATFORM_ADMIN))
    assert meta["total_count"] == 2, f"initiator listing total_count expected 2, got {meta}"
    assert [r["id"] for r in rows] == [prog_one["id"], prog_two["id"]], (
        "the initiator listing must return its own two programs in created_at order"
    )
    assert find_by_id(rows, prog_three["id"]) is None, (
        "the target's program must never appear in the initiator's listing"
    )

    rows, meta = validate_paginated(
        api.list_organization_programs(
            org_a, PLATFORM_ADMIN, {"service_category": "YOUTH_MENTORING"}
        )
    )
    assert meta["total_count"] == 1, f"filtered total_count expected 1, got {meta}"
    assert [r["id"] for r in rows] == [prog_one["id"]], (
        "the service_category filter must keep only the mentoring program"
    )

    rows, meta = validate_paginated(
        api.list_organization_programs(org_a, PLATFORM_ADMIN, {"limit": 1, "offset": 1})
    )
    assert len(rows) == 1, f"limit 1 must return one row, got {len(rows)}"
    assert rows[0]["id"] == prog_two["id"], "offset 1 must skip to the second program"
    assert meta["total_count"] == 2, (
        f"total_count counts matching rows, not the page size, got {meta}"
    )


def test_financial_restatement_recomputes_the_monthly_expense_on_the_half_cent(api):
    """A financial restatement replaces both stored figures, re-derives the monthly
    expense with round-half-up, and bumps the organization's version.

    PRD 3.1 derives monthly_expense_cents by dividing annual_expense_cents by twelve
    and rounding half up, and states that the restatement replaces the two stored
    figures and bumps the organization's version. 100000002 / 12 is exactly
    8333333.5 and rounds up to 8333334; 120000006 / 12 is exactly 10000000.5 and
    rounds up to 10000001. PRD 3.1 also fixes a newly registered organization at
    affiliation_role INDEPENDENT with restricted_corpus_cents 0 and
    governance_seats 0, and the restatement touches neither.

    Design: Corner/endpoints/financial_restatement_recomputes_the_monthly_expense_on_the_half_cent
    """
    created = fx.create_organization(api, fx.ORG_A)
    assert_money_equals(created["monthly_expense_cents"], 8333334, "monthly_expense_cents")

    restated = validate_success(
        api.financial_restatement(
            created["id"],
            f.financial_restatement_payload(
                annual_expense_cents=120000006,
                unrestricted_net_assets_cents=50000000,
                restatement_reason="Audited FY2026 statements replaced the interim figures",
            ),
            make_strategy_officer_headers(created["id"]),
        ),
        200,
    )
    assert_money_equals(restated["annual_expense_cents"], 120000006, "annual_expense_cents")
    assert_money_equals(
        restated["unrestricted_net_assets_cents"], 50000000, "unrestricted_net_assets_cents"
    )
    assert_money_equals(restated["monthly_expense_cents"], 10000001, "monthly_expense_cents")
    assert_version_is(restated, 2, "organization")
    assert_field(restated, "affiliation_role", "INDEPENDENT")
    assert_money_equals(restated["restricted_corpus_cents"], 0, "restricted_corpus_cents")
    assert_field(restated, "governance_seats", 0)

    read_back = validate_success(api.get_organization(created["id"], PLATFORM_ADMIN))
    assert_money_equals(read_back["monthly_expense_cents"], 10000001, "monthly_expense_cents")
    assert_version_is(read_back, 2, "organization")


def test_a_second_sweep_at_the_same_clock_value_reports_three_empty_lists(api):
    """A sweep re-run without moving the clock returns three empty lists and mutates
    nothing, so the first sweep's version bump is not repeated.

    PRD 3.9 states that the sweep lapses every ISSUED letter whose expires_at the
    clock has reached or passed, releasing its exclusivity, and that the sweep is
    idempotent with respect to the clock: running it a second time without moving
    the clock returns three empty lists and mutates nothing. PRD 3.4 sets the
    exclusivity window's last day at start plus days minus one, so a 60-day window
    opening 2026-08-01 ends 2026-09-29 and expires_at is 2026-09-29T00:00:00.000Z.

    Design: Corner/endpoints/a_second_sweep_at_the_same_clock_value_reports_three_empty_lists
    """
    ctx = fx.setup_deal_loi_negotiation(api)
    loi_id = ctx["loi"]["id"]
    deal_id = ctx["deal"]["id"]
    assert_field(ctx["loi"], "exclusivity_end_date", "2026-09-29")
    assert_field(ctx["loi"], "expires_at", "2026-09-29T00:00:00.000Z")

    fx.set_clock(api, "2026-09-29T00:00:00Z")

    first = validate_success(api.run_regulatory_sweep({}, PLATFORM_ADMIN), 200)
    assert first["lapsed_letter_of_intent_ids"] == [loi_id], (
        f"the first sweep must name the expired letter, got {first!r}"
    )
    assert_field(first, "swept_at", "2026-09-29T00:00:00.000Z")
    assert_three_fractional_digits(first["swept_at"], "swept_at")

    letter = fx.lenient_data(api.list_deal_letters_of_intent(deal_id, PLATFORM_ADMIN))[0]
    assert_status(letter, "LAPSED")
    assert_field(letter, "exclusivity_status", "RELEASED")
    assert_version_is(letter, 2, "letter_of_intent")

    second = validate_success(api.run_regulatory_sweep({}, PLATFORM_ADMIN), 200)
    assert second["lapsed_letter_of_intent_ids"] == [], (
        f"the second sweep must re-report nothing, got {second!r}"
    )
    assert second["expired_exclusivity_letter_of_intent_ids"] == [], (
        f"the second sweep must re-report nothing, got {second!r}"
    )
    assert second["deemed_approved_filing_ids"] == [], (
        f"the second sweep must re-report nothing, got {second!r}"
    )

    letter = fx.lenient_data(api.list_deal_letters_of_intent(deal_id, PLATFORM_ADMIN))[0]
    assert_version_is(letter, 2, "letter_of_intent")
    assert_status(letter, "LAPSED")
    assert_status(fx.read_deal(api, deal_id), "LOI_NEGOTIATION")


def test_waiving_the_last_open_finding_closes_diligence_and_clears_the_exposure(api):
    """Waiving the only open finding moves it to WAIVED, closes diligence, and leaves
    the next diligence-adjusted snapshot with no open exposure to net out.

    PRD 3.5 states that a waiver accepts the finding as unresolved, moves it
    OPEN -> WAIVED, and that once no finding of the deal is still OPEN or ESCALATED
    the deal advances DILIGENCE -> DILIGENCE_CLOSED. PRD 3.2 nets only findings that
    are still OPEN or ESCALATED out of available_unrestricted_cents, so a waived
    finding contributes nothing: 59916670 + 40000000 leaves 99916670 against a
    combined monthly expense of 8333334 + 8333334, giving reserve_months 5.99, which
    scores 20.00 of the sustainability band; an identical mission code scores 40.00
    and a deal with no programs on either side scores 0.00 for overlap, so the
    composite is 60.00 and lands in the MODERATE band. PRD 3.2 also numbers each
    snapshot one plus the count of prior snapshots of the same deal and the same
    variant, so this first diligence-adjusted snapshot is sequence_no 1.

    Design: Corner/endpoints/waiving_the_last_open_finding_closes_diligence_and_clears_the_exposure
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]

    finding = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal_id,
                workstream="WORKFORCE",
                severity="MEDIUM",
                summary="Unfunded accrued leave liability for transferring staff",
                exposure_cents=33250000,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )

    waived = validate_success(
        api.waive_diligence_request(
            finding["id"],
            f.diligence_waive_payload(
                waiver_justification=(
                    "Liability priced into the closing memo and indemnified by the target board"
                )
            ),
            DILIGENCE_LEAD_2,
        ),
        200,
    )
    assert_status(waived, "WAIVED")
    assert_status(fx.read_deal(api, deal_id), "DILIGENCE_CLOSED")

    adjusted = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "DILIGENCE_ADJUSTED"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )
    assert_field(adjusted, "sequence_no", 1)
    assert_money_equals(
        adjusted["open_diligence_exposure_cents"], 0, "open_diligence_exposure_cents"
    )
    assert_money_equals(
        adjusted["available_unrestricted_cents"], 99916670, "available_unrestricted_cents"
    )
    assert_decimal_equals(adjusted["reserve_months"], 5.99, 2, "reserve_months")
    assert_decimal_equals(adjusted["composite_score"], 60.00, 2, "composite_score")
    assert_field(adjusted, "composite_rating", "MODERATE")


def test_a_transferred_fund_is_reachable_from_the_deal_and_from_both_parties(api):
    """An executed charitable-asset transfer stays reverse-reachable from the deal, from
    the recipient, from the authorising deal filter and from its original holder.

    PRD 4 defines the deal sub-resource as "every restricted fund attached to either
    party of one deal, whether as holder of record or as transfer recipient", so both
    of the initiator's funds belong to that listing whatever their transfer status,
    and defines the collection listing as filterable by holder, recipient,
    authorising deal, transfer status and fund type. PRD 3.6 releases the fund's
    entire value under DONOR_CONSENT, so a fund of 50000000 principal plus 12000000
    accumulated appreciation transfers 62000000 and retains 0, and records the
    recipient in transferred_to_org_id and the authorising deal in
    transfer_restructuring_id.

    Design: Corner/endpoints/a_transferred_fund_is_reachable_from_the_deal_and_from_both_parties
    """
    ctx = fx.setup_deal_structure_selected(api)
    deal_id = ctx["deal"]["id"]
    org_a, org_b = ctx["org_a"]["id"], ctx["org_b"]["id"]

    fund_moved = fx.setup_fund_consent_granted(
        api,
        org_a,
        fund_name="Nakamura Family Program Fund",
        principal_cents=50000000,
        accumulated_appreciation_cents=12000000,
        restriction_purpose_code="AF-AFTERSCHOOL",
    )
    fund_held = fx.create_fund(
        api,
        org_a,
        fund_name="Anonymous Tutoring Bequest",
        principal_cents=3000000,
        accumulated_appreciation_cents=0,
        restriction_purpose_code="TU-TUTORING",
    )
    fx.transfer_fund(api, fund_moved["id"], deal_id, "DONOR_CONSENT")

    rows, meta = validate_paginated(
        api.list_deal_restricted_funds(deal_id, TRUST_COUNSEL, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 2, (
        f"both of the initiator's funds are attached to the deal's parties, got {meta}"
    )
    assert find_by_id(rows, fund_moved["id"]) is not None, (
        "the transferred fund must be reachable from the deal it was transferred under"
    )
    assert find_by_id(rows, fund_held["id"]) is not None, (
        "a fund still held by a party is attached to the deal as holder of record"
    )

    rows, meta = validate_paginated(
        api.list_restricted_funds(
            CHARITIES_REGULATOR,
            {"transferred_to_org_id": org_b, "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, f"recipient filter total_count expected 1, got {meta}"
    assert [r["id"] for r in rows] == [fund_moved["id"]], (
        "the recipient filter must return the fund the recipient never created"
    )

    rows, meta = validate_paginated(
        api.list_restricted_funds(
            CHARITIES_REGULATOR,
            {"org_id": org_a, "transfer_status": "HELD", "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, f"holder plus status filter expected 1, got {meta}"
    assert [r["id"] for r in rows] == [fund_held["id"]], (
        "only the untouched fund is still HELD by the initiator"
    )

    rows, meta = validate_paginated(
        api.list_restricted_funds(
            CHARITIES_REGULATOR,
            {"transfer_restructuring_id": deal_id, "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, f"authorising deal filter expected 1, got {meta}"
    assert [r["id"] for r in rows] == [fund_moved["id"]], (
        "only the transferred fund carries the authorising deal"
    )

    one = validate_success(api.get_restricted_fund(fund_moved["id"], CHARITIES_REGULATOR))
    assert_field(one, "transfer_status", "TRANSFERRED")
    assert_field(one, "transferred_to_org_id", org_b)
    assert_field(one, "transfer_restructuring_id", deal_id)
    assert_money_equals(one["transferred_amount_cents"], 62000000, "transferred_amount_cents")
    assert_money_equals(one["retained_amount_cents"], 0, "retained_amount_cents")


def test_the_continuity_decision_routes_a_programme_to_transfer_or_to_sunset(api):
    """One continuity decision keeps a program inside the diligence-adjusted inclusion set
    and the other removes it, and neither assigns a recipient yet.

    PRD 3.1 states that a continuity decision records TRANSFER as PLANNED_TRANSFER and
    SUNSET as PLANNED_SUNSET, bumping the program's version, and that
    transferred_to_org_id is only assigned when the deal is consummated. PRD 3.2 admits
    only programs whose continuity_status is ACTIVE or PLANNED_TRANSFER into a
    DILIGENCE_ADJUSTED snapshot, so of the initiator's two programs only the
    transferred one counts; with no admitted target programs the denominator is 0, so
    program_overlap_index is 0.0000 and program_overlap_points 0.00, leaving the
    composite at 40.00 for identical mission codes plus 20.00 for a reserve of 5.99
    months. PRD 3.1 also keeps the deal's own status untouched by the decision.

    Design: Corner/endpoints/the_continuity_decision_routes_a_programme_to_transfer_or_to_sunset
    """
    ctx = fx.setup_deal_diligence(api)
    deal_id = ctx["deal"]["id"]
    org_a = ctx["org_a"]["id"]

    prog_keep = fx.create_program(
        api,
        org_a,
        name="Riverside Mentor Match",
        service_category="YOUTH_MENTORING",
        county_code="CA-ALAMEDA",
        annual_expense_cents=9000000,
        clients_served=240,
    )
    prog_sunset = fx.create_program(
        api,
        org_a,
        name="Riverside Weekend Pantry",
        service_category="FOOD_SECURITY",
        county_code="CA-SONOMA",
        annual_expense_cents=4000000,
        clients_served=900,
    )

    kept = validate_success(
        api.continuity_decision(
            prog_keep["id"],
            f.continuity_decision_payload(deal_id, disposition="TRANSFER"),
            INTEGRATION_MANAGER,
        ),
        200,
    )
    sunset = validate_success(
        api.continuity_decision(
            prog_sunset["id"],
            f.continuity_decision_payload(deal_id, disposition="SUNSET"),
            INTEGRATION_MANAGER,
        ),
        200,
    )
    assert_field(kept, "continuity_status", "PLANNED_TRANSFER")
    assert_null(kept, "transferred_to_org_id")
    assert_version_is(kept, 2, "prog_keep")
    assert_field(sunset, "continuity_status", "PLANNED_SUNSET")
    assert_null(sunset, "transferred_to_org_id")

    adjusted = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(deal_id, "DILIGENCE_ADJUSTED"),
            make_strategy_officer_headers(org_a),
        ),
        201,
    )
    assert_field(adjusted, "included_program_count", 1)
    assert_field(adjusted, "overlap_pair_count", 0)
    assert_decimal_equals(adjusted["program_overlap_index"], 0.0, 4, "program_overlap_index")
    assert_decimal_equals(adjusted["program_overlap_points"], 0.0, 2, "program_overlap_points")
    assert_decimal_equals(adjusted["composite_score"], 60.00, 2, "composite_score")
    assert_status(fx.read_deal(api, deal_id), "DILIGENCE")
