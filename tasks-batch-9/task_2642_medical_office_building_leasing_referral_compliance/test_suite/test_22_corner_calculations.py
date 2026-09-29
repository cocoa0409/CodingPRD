"""Derived-figure tests: tenant-mix counting, arrears aging, the parking
reserve, the parking waiver tier, the write-off weight, the minimum term,
the tenant-improvement cost split, the two risk-score variants and the
fair-market-value band.

Every expectation is computed with `decimal.Decimal` so that money lands on
exactly 2 half-up decimal places and shares on exactly 4.
"""
from decimal import Decimal

from test_helpers import (
    COMPLIANCE_OFFICER,
    LEASING_AGENT,
    PROPERTY_MANAGER,
    ApiErrorId,
    assert_invoice_breakdown,
    assert_line_split,
    assert_mix_figures,
    assert_parking_counters,
    assert_project_rollups,
    assert_total_count,
    expected_aging_weight,
    expected_invoice_total,
    expected_line_split,
    expected_patient_reserve_minimum,
    published_band,
    round_money,
    round_share,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _row_by_id(rows, row_id):
    """Pick one row out of a listing by its identifier."""
    matches = [row for row in rows if row["id"] == row_id]
    assert matches, "row {} is missing from the listing".format(row_id)
    return matches[0]


def test_tenant_mix_excludes_a_merely_certified_lease(api):
    """An FMV_CERTIFIED lease contributes no rentable area until it is executed.

    PRD: "The counted lease set for a building comprises the leases whose
    `building_id` is that building, whose status is `EXECUTED`, `ACTIVE` or
    `HOLDOVER`, and whose `lease_type` is `DIRECT` or `MASTER`."
    PRD: "Leases in `DRAFT`, `PENDING_FMV_REVIEW`, `SUSPENDED_MIX_REVIEW`,
    `FMV_CERTIFIED`, `TERMINATED` and `WITHDRAWN` are all excluded as well — a
    certified lease holds no area until it is executed."
    PRD: "`anchor_share_pct` is `anchor_rentable_sf` divided by
    `leased_rentable_sf`, rounded half up to 4 decimal places; when
    `leased_rentable_sf` is zero the share reads 0.0000 rather than being
    undefined."
    PRD: "Otherwise, if `anchor_share_pct` is strictly greater than 0.7500 the
    posture is `RESTRICTED`; otherwise, if it is strictly greater than 0.6000
    the posture is `ANCHOR_CONCENTRATED`; otherwise it is `BALANCED`."
    PRD: "`VACANT → RESERVED` when a lease over that suite is executed"

    Design: Corner/calculations/building_tenant_mix_counts_only_executed_active_and_holdover_leases
    """
    building = fx.register_building(api)
    anchor_suite = fx.register_suite(api, building["id"], suite_number="100", floor=1,
                                     rentable_sf=12000, power_amps_available=400)
    indep_suite = fx.register_suite(api, building["id"], suite_number="210", floor=2,
                                    rentable_sf=5000, power_amps_available=200)
    anchor_tenant = fx.register_tenant(api, legal_name="Meridian Health System Clinics",
                                       affiliation="HEALTH_SYSTEM_ANCHOR",
                                       primary_specialty="PRIMARY_CARE")
    indep_tenant = fx.register_tenant(api, legal_name="Northgate Medical Group PC",
                                      affiliation="INDEPENDENT_PRACTICE",
                                      primary_specialty="GASTROENTEROLOGY")

    anchor_lease = fx.draft_lease(api, building["id"], anchor_suite["id"],
                                  anchor_tenant["id"], term_start="2026-09-01",
                                  term_end="2031-08-31", base_rent_psf_annual=28.00)
    fx.file_attestation(api, anchor_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, anchor_lease["id"])
    fx.certify(api, anchor_lease["id"])
    fx.execute(api, anchor_lease["id"])

    indep_lease = fx.draft_lease(api, building["id"], indep_suite["id"],
                                 indep_tenant["id"], term_start="2026-09-01",
                                 term_end="2029-08-31", base_rent_psf_annual=30.00)
    fx.file_attestation(api, indep_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, indep_lease["id"])
    certified = fx.certify(api, indep_lease["id"])
    assert certified["status"] == "FMV_CERTIFIED", (
        "expected FMV_CERTIFIED, got {}".format(certified["status"]))

    # Only the anchor lease is counted while the independent deal is certified.
    before = fx.read_building(api, building["id"])
    assert_mix_figures(before, anchor_sf=12000, independent_sf=0, leased_sf=12000,
                       vacant_sf=88000, anchor_share_pct=1.0000, posture="RESTRICTED")
    held_suite = fx.read_suite(api, indep_suite["id"])
    assert held_suite["occupancy_status"] == "VACANT", (
        "a certified lease must not reserve its suite, got {}".format(
            held_suite["occupancy_status"]))

    executed = validate_success(
        api.execute_lease(indep_lease["id"], {"execution_note": "Countersigned"},
                          LEASING_AGENT), 200)
    assert executed["status"] == "EXECUTED", (
        "expected EXECUTED, got {}".format(executed["status"]))

    after = fx.read_building(api, building["id"])
    expected_share = round_share(Decimal(12000) / Decimal(17000))
    assert expected_share == 0.7059, "expected 0.7059, got {}".format(expected_share)
    assert_mix_figures(after, anchor_sf=12000, independent_sf=5000, leased_sf=17000,
                       vacant_sf=83000, anchor_share_pct=expected_share,
                       posture="ANCHOR_CONCENTRATED")
    reserved_suite = fx.read_suite(api, indep_suite["id"])
    assert reserved_suite["occupancy_status"] == "RESERVED", (
        "expected RESERVED after execution, got {}".format(
            reserved_suite["occupancy_status"]))


def test_arrears_aging_walks_every_tier_boundary_at_one_close(api):
    """One close over four staggered due dates yields weights 0, 15, 30 and 50.

    PRD: "Aging is measured in whole calendar days as the clock date less
    `due_date`, and the figure is negative before the due date arrives."
    PRD: "An invoice becomes delinquent only when that day count is **strictly
    greater than** the ten-day grace period, so a count of exactly 10 leaves the
    invoice in `ISSUED` carrying no weight."
    PRD: "a day count of at most 30 carries a weight of 15, a count of at most
    60 carries 30, and a count beyond 60 carries 50."
    PRD: "At the daily close on which the invoice is first flagged, the day
    count is frozen into `days_past_due_at_flag` and the corresponding weight
    into `delinquency_tier_weight`, and neither is revised on any later close
    even though `days_past_due` continues to grow."
    PRD: "`delinquency_event_count` is a running tally: it counts the invoices
    across every one of that tenant's leases whose status is `DELINQUENT` or
    `WRITTEN_OFF`, and it increases by 1 each time an invoice is flagged
    delinquent by the daily close."

    Design: Corner/calculations/rent_arrears_aging_walks_every_tier_boundary_at_one_close
    """
    ctx = fx.active_lease(api)
    lease_id = ctx["lease"]["id"]

    grace_edge = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-11-20")
    first_tier = fx.issue_invoice(api, lease_id, "2026-10-01", "2026-10-31", "2026-11-19")
    second_tier = fx.issue_invoice(api, lease_id, "2026-11-01", "2026-11-30", "2026-10-30")
    third_tier = fx.issue_invoice(api, lease_id, "2026-12-01", "2026-12-31", "2026-09-28")

    fx.set_clock_date(api, "2026-11-30")
    fx.run_daily_close(api)

    rows, _meta = validate_paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))

    at_grace = _row_by_id(rows, grace_edge["id"])
    assert at_grace["days_past_due"] == 10, (
        "expected days_past_due 10, got {}".format(at_grace["days_past_due"]))
    assert at_grace["status"] == "ISSUED", (
        "a day count of exactly 10 must stay ISSUED, got {}".format(at_grace["status"]))
    assert at_grace["delinquency_tier_weight"] == 0, (
        "expected weight 0 at the grace boundary, got {}".format(
            at_grace["delinquency_tier_weight"]))
    assert at_grace["days_past_due_at_flag"] is None, (
        "days_past_due_at_flag must stay null while the invoice is ISSUED")

    for invoice, day_count, weight in ((first_tier, 11, 15),
                                       (second_tier, 31, 30),
                                       (third_tier, 63, 50)):
        row = _row_by_id(rows, invoice["id"])
        assert row["status"] == "DELINQUENT", (
            "expected DELINQUENT at {} days, got {}".format(day_count, row["status"]))
        assert row["days_past_due"] == day_count, (
            "expected days_past_due {}, got {}".format(day_count, row["days_past_due"]))
        assert row["days_past_due_at_flag"] == day_count, (
            "expected days_past_due_at_flag {}, got {}".format(
                day_count, row["days_past_due_at_flag"]))
        assert row["delinquency_tier_weight"] == weight, (
            "expected delinquency_tier_weight {} at {} days, got {}".format(
                weight, day_count, row["delinquency_tier_weight"]))
        assert expected_aging_weight(day_count) == weight

    tenant = fx.read_tenant(api, ctx["tenant"]["id"])
    assert tenant["referral_compliance_risk_score"] == 95, (
        "expected rolling score 15 + 30 + 50 == 95, got {}".format(
            tenant["referral_compliance_risk_score"]))
    assert tenant["strict_cumulative_risk_score"] == 95, (
        "expected strict score 95, got {}".format(
            tenant["strict_cumulative_risk_score"]))
    assert tenant["delinquency_event_count"] == 3, (
        "expected three delinquency events, got {}".format(
            tenant["delinquency_event_count"]))
    assert tenant["compliance_watch_status"] == "WATCH", (
        "a rolling score of 95 must raise the watch, got {}".format(
            tenant["compliance_watch_status"]))


def test_patient_parking_reserve_rounds_up_on_a_fractional_product(api):
    """A 401-stall pool reserving 0.60 rounds 240.6 up to 241, capping staff at 160.

    PRD: "The patient parking reserve minimum is the ceiling of a fractional
    product, so a fractional reserve always rounds up in the patients' favour."
    PRD: "The patient-reserve test comes second and applies only to `STAFF`
    requests: the reserve minimum is `total_parking_stalls` multiplied by
    `patient_min_reserve_pct` and raised to the next whole stall by ceiling —
    fractional reserves always round up in the patients' favour — and the
    request is refused with `ERR_PATIENT_PARKING_RESERVE_BREACH` when
    `total_parking_stalls` less the post-request staff total would fall below
    that minimum."
    PRD: "The reserve is measured against every stall **not** allocated to
    staff, that is patient stalls plus unallocated stalls, and not against
    `patient_allocated_stalls` alone; measuring it the narrow way would make the
    very first staff stall in an empty building a breach."
    PRD: "`staff_allocated_stalls` is the summed `stall_count` of active staff
    allocations, `patient_allocated_stalls` the summed `stall_count` of active
    patient allocations, and `unallocated_stalls` is `total_parking_stalls` less
    those two sums."

    Design: Corner/calculations/patient_parking_reserve_rounds_up_on_a_fractional_product
    """
    ctx = fx.drafted_lease(api, building_overrides={"total_parking_stalls": 401,
                                                    "patient_min_reserve_pct": 0.60})
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    reserve = expected_patient_reserve_minimum(401, 0.60)
    assert reserve == 241, "expected a reserve minimum of 241 stalls, got {}".format(reserve)

    version = fx.read_building(api, building_id)["version"]
    over = api.create_parking_allocation(
        f.create_parking_allocation_payload(version, building_id, lease_id, "STAFF", 161),
        PROPERTY_MANAGER)
    validate_error(over, ApiErrorId.ERR_PATIENT_PARKING_RESERVE_BREACH)

    untouched = fx.read_building(api, building_id)
    assert_parking_counters(untouched, staff=0, patient=0, unallocated=401)

    allocation = fx.allocate_stalls(api, building_id, lease_id, "STAFF", 160)
    assert allocation["status"] == "ACTIVE", (
        "expected ACTIVE, got {}".format(allocation["status"]))
    assert allocation["category"] == "STAFF", (
        "expected STAFF, got {}".format(allocation["category"]))
    assert allocation["stall_count"] == 160, (
        "expected 160 stalls, got {}".format(allocation["stall_count"]))

    after = fx.read_building(api, building_id)
    assert_parking_counters(after, staff=160, patient=0, unallocated=241)


def test_parking_waiver_tier_boundary_at_exactly_five_thousand(api):
    """A combined total of exactly 5000.00 waives nothing; a fifth stall lowers the bill.

    PRD: "The tier is keyed on `pre_waiver_total`, the **combined** figure from
    step 4, and not on the parking component alone."
    PRD: "Walk the tiers in order and take the first whose upper bound is
    satisfied: a combined total of at most 5000.00 selects a
    `parking_waiver_tier_pct` of 0.00, a combined total of at most 12000.00
    selects 0.25, and anything above that selects 0.50."
    PRD: "The bounds are inclusive upper bounds, so a combined total of exactly
    5000.00 sits in the 0.00 tier and 5000.01 sits in the 0.25 tier."
    PRD: "A 1500 square foot suite billed at an annual figure of 43200.00 in a
    building recovering 9.60 per square foot, with 4 staff stalls, produces
    3600.00 of base rent, 1200.00 of recovery and 200.00 of parking, for a
    combined total of exactly 5000.00: the 0.00 tier applies and the invoice is
    5000.00."
    PRD: "Add a fifth staff stall and the components become 3600.00, 1200.00 and
    250.00 for a combined 5050.00, which crosses into the 0.25 tier, waives
    62.50 of parking, and produces a total of 4987.50."
    PRD: "The tenant with more parking owes 12.50 less."

    Design: Corner/calculations/parking_waiver_tier_boundary_at_exactly_five_thousand
    """
    ctx = fx.active_lease(api,
                          suite_overrides={"rentable_sf": 1500, "suite_number": "150"},
                          lease_overrides={"base_rent_psf_annual": 28.80})
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    lease = fx.read_lease(api, lease_id)
    assert round_money(lease["certified_base_rent_annual"]) == 43200.00, (
        "expected a certified annual figure of 43200.00, got {}".format(
            lease["certified_base_rent_annual"]))

    fx.allocate_stalls(api, building_id, lease_id, "STAFF", 4)
    at_boundary = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")

    four_stalls = expected_invoice_total(43200.00, 9.60, 1500, staff_stalls=4)
    assert four_stalls["pre_waiver_total"] == 5000.00
    assert four_stalls["parking_waiver_tier_pct"] == 0.00
    assert four_stalls["total_amount"] == 5000.00
    assert_invoice_breakdown(at_boundary, four_stalls)
    assert round_money(at_boundary["base_rent_amount"]) == 3600.00
    assert round_money(at_boundary["cam_amount"]) == 1200.00
    assert round_money(at_boundary["parking_fee_gross"]) == 200.00
    assert round_money(at_boundary["parking_waiver_amount"]) == 0.00
    assert round_money(at_boundary["total_amount"]) == 5000.00

    fx.allocate_stalls(api, building_id, lease_id, "STAFF", 1)
    over_boundary = fx.issue_invoice(api, lease_id, "2026-10-01", "2026-10-31", "2026-10-05")

    five_stalls = expected_invoice_total(43200.00, 9.60, 1500, staff_stalls=5)
    assert five_stalls["pre_waiver_total"] == 5050.00
    assert round_share(five_stalls["parking_waiver_tier_pct"]) == 0.2500
    assert five_stalls["total_amount"] == 4987.50
    assert_invoice_breakdown(over_boundary, five_stalls)
    assert round_money(over_boundary["parking_fee_gross"]) == 250.00
    assert round_money(over_boundary["parking_waiver_amount"]) == 62.50
    assert round_money(over_boundary["total_amount"]) == 4987.50

    saving = round_money(Decimal("5000.00") - Decimal("4987.50"))
    assert saving == 12.50, "the fifth stall must lower the bill by 12.50, got {}".format(saving)

    building = fx.read_building(api, building_id)
    assert_parking_counters(building, staff=5, patient=0, unallocated=395)


def test_write_off_replaces_the_aging_tier_with_the_write_off_weight(api):
    """Writing off a 63-day invoice replaces its weight of 50 with 40, not 90.

    PRD: "On success the invoice moves `DELINQUENT → WRITTEN_OFF`, the
    justification and the acting `X-User-ID` are recorded as
    `write_off_justification` and `written_off_by_user_id`, and
    `delinquency_tier_weight` is **replaced** by 40 rather than adjusted, because
    forgiving rent owed by a referral source is a larger remuneration exposure
    than merely tolerating late rent."
    PRD: "Both score variants are then recomputed, the tenant's
    `compliance_watch_status` is re-evaluated, and both the tenant's and the
    invoice's `version` advance."
    PRD: "A written-off invoice contributes the write-off weight instead of its
    aging tier, never both."
    PRD: "`compliance_watch_status` reads `WATCH` when the rolling
    `referral_compliance_risk_score` is at least 45, or when the tenant has any
    compliance case in status `OPEN`, `REMEDIATION_PLANNED` or `REPORTED`;
    otherwise it reads `CLEAR`."

    Design: Corner/calculations/write_off_replaces_the_aging_tier_with_the_write_off_weight
    """
    ctx = fx.active_lease(api)
    lease_id = ctx["lease"]["id"]
    tenant_id = ctx["tenant"]["id"]

    invoice = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    fx.set_clock_date(api, "2026-11-07")
    fx.run_daily_close(api)

    rows, _meta = validate_paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    flagged = _row_by_id(rows, invoice["id"])
    assert flagged["status"] == "DELINQUENT", (
        "expected DELINQUENT, got {}".format(flagged["status"]))
    assert flagged["days_past_due_at_flag"] == 63, (
        "expected days_past_due_at_flag 63, got {}".format(flagged["days_past_due_at_flag"]))
    assert flagged["delinquency_tier_weight"] == 50, (
        "expected the late tier weight 50, got {}".format(flagged["delinquency_tier_weight"]))

    before_tenant = fx.read_tenant(api, tenant_id)
    assert before_tenant["referral_compliance_risk_score"] == 50
    assert before_tenant["strict_cumulative_risk_score"] == 50
    assert before_tenant["compliance_watch_status"] == "WATCH"

    cases, cases_meta = validate_paginated(
        api.list_tenant_compliance_cases(tenant_id, COMPLIANCE_OFFICER))
    assert_total_count(cases_meta, 1)
    assert cases[0]["case_type"] == "RENT_DELINQUENCY", (
        "expected RENT_DELINQUENCY, got {}".format(cases[0]["case_type"]))
    assert cases[0]["status"] == "OPEN", (
        "expected OPEN, got {}".format(cases[0]["status"]))
    assert cases[0]["opened_by_user_id"] == "system", (
        "expected opened_by_user_id 'system', got {}".format(cases[0]["opened_by_user_id"]))

    written_off = fx.write_off_invoice(api, invoice["id"],
                                      justification="Practice dissolved; arrears uncollectable")
    assert written_off["status"] == "WRITTEN_OFF", (
        "expected WRITTEN_OFF, got {}".format(written_off["status"]))
    assert written_off["written_off_by_user_id"] == "compliance-002", (
        "expected written_off_by_user_id 'compliance-002', got {}".format(
            written_off["written_off_by_user_id"]))
    assert written_off["write_off_justification"] == "Practice dissolved; arrears uncollectable"
    assert written_off["delinquency_tier_weight"] == 40, (
        "the write-off weight must replace the aging tier, expected 40, got {}".format(
            written_off["delinquency_tier_weight"]))
    assert written_off["days_past_due_at_flag"] == 63, (
        "the frozen day count survives the write-off, got {}".format(
            written_off["days_past_due_at_flag"]))
    assert written_off["version"] == flagged["version"] + 1, (
        "expected the invoice version to advance by 1, got {}".format(written_off["version"]))

    after_tenant = fx.read_tenant(api, tenant_id)
    assert after_tenant["referral_compliance_risk_score"] == 40, (
        "expected the rolling score to be replaced by 40, not 90, got {}".format(
            after_tenant["referral_compliance_risk_score"]))
    assert after_tenant["strict_cumulative_risk_score"] == 40, (
        "expected the strict score to be replaced by 40, not 90, got {}".format(
            after_tenant["strict_cumulative_risk_score"]))
    assert after_tenant["version"] == before_tenant["version"] + 1, (
        "expected the tenant version to advance by 1, got {}".format(after_tenant["version"]))
    assert after_tenant["compliance_watch_status"] == "WATCH", (
        "the OPEN rent-delinquency case holds the watch even at 40, got {}".format(
            after_tenant["compliance_watch_status"]))


def test_lease_minimum_term_boundary_eleven_versus_twelve_months(api):
    """The month count is taken against the exclusive end, so 31 August 2027 admits.

    PRD: "Term length is derived at draft time as `term_months`, and the
    derivation is subtle because `term_end` is the **last day of occupancy**
    rather than the day after it."
    PRD: "The count is therefore taken against the exclusive end, which is the
    day following `term_end`."
    PRD: "Take the difference in years between that exclusive end and
    `term_start` and multiply by 12, add the difference in their month numbers,
    and then, if the exclusive end's day of the month is earlier than
    `term_start`'s day of the month, subtract one whole month because the
    anniversary day has not been reached."
    PRD: "A term running from 1 September 2026 through 31 August 2027 therefore
    yields exactly 12 months and is admissible, while the same term ending one
    day earlier, on 30 August 2027, yields 11 and is refused with
    `ERR_MIN_TERM_NOT_MET`; a term of 31 January 2026 through 28 February 2026
    yields 1."
    PRD: "Using `term_end` directly instead of the exclusive end is the classic
    off-by-one here: it makes a clean twelve-month term read 11."

    Design: Corner/calculations/lease_minimum_term_boundary_eleven_versus_twelve_months
    """
    ctx = fx.leasing_baseline(api)
    building_id = ctx["building"]["id"]
    suite_id = ctx["suite"]["id"]
    tenant_id = ctx["tenant"]["id"]

    for short_end in ("2027-07-31", "2027-08-30"):
        refused = api.create_lease(
            f.create_lease_payload(building_id, suite_id, tenant_id,
                                   term_start="2026-09-01", term_end=short_end),
            LEASING_AGENT)
        validate_error(refused, ApiErrorId.ERR_MIN_TERM_NOT_MET)

    admitted = validate_success(
        api.create_lease(f.create_lease_payload(building_id, suite_id, tenant_id,
                                                term_start="2026-09-01",
                                                term_end="2027-08-31"),
                         LEASING_AGENT), 201)
    assert admitted["term_months"] == 12, (
        "1 September 2026 through 31 August 2027 must read 12 months, got {}".format(
            admitted["term_months"]))
    assert admitted["status"] == "DRAFT", (
        "expected DRAFT, got {}".format(admitted["status"]))

    rows, meta = validate_paginated(api.list_leases(LEASING_AGENT, {"suite_id": suite_id}))
    assert_total_count(meta, 1)
    assert rows[0]["id"] == admitted["id"], "the refused drafts must not have been persisted"


def test_ti_cost_share_applies_three_level_share_precedence(api):
    """Category rule, then line override, then project default, on one project.

    PRD: "First, the category rule: a line whose `category` is `SHIELDING` on a
    project whose `target_suite_class` is `IMAGING` is borne entirely by the
    landlord, so its `effective_share_pct` is 1.0000 — the landlord pays 100% of
    radiation shielding in an imaging build-out regardless of anything else the
    project or the line says."
    PRD: "Second, the line override: where the category rule does not apply and
    `landlord_share_pct_override` is non-null, `effective_share_pct` takes the
    override."
    PRD: "Third, the project default: otherwise `effective_share_pct` takes the
    project's `landlord_share_pct`."
    PRD: "From the resolved share, `landlord_share_amount` is the line's
    `cost_amount` multiplied by `effective_share_pct`, rounded half up to 2
    decimal places, and `tenant_share_amount` is the line's `cost_amount`
    **less** that rounded landlord amount."
    PRD: "The project's totals are then sums of the **already-rounded** per-line
    figures, taken over the lines in `sequence_no` order:
    `landlord_committed_amount` sums the per-line landlord amounts,
    `tenant_committed_amount` sums the per-line tenant amounts, and
    `allowance_remaining` is `authorized_allowance_total` less
    `landlord_committed_amount`."
    PRD: "and assigns `sequence_no`, a 1-based index that increases
    monotonically within the project and is the pinned processing order for every
    cost figure derived below."

    Design: Corner/calculations/ti_cost_share_applies_three_level_share_precedence
    """
    ctx = fx.drafted_lease(api, suite_overrides={"suite_number": "300", "floor": 3,
                                                 "power_amps_available": 400})
    imaging = fx.open_ti_project(api, ctx["lease"]["id"], ctx["suite"]["id"],
                                target_suite_class="IMAGING", lead_thickness_mm=2.5,
                                power_amps_requested=150,
                                authorized_allowance_total=500000.00,
                                landlord_share_pct=0.60)

    shielding = fx.add_line_item(api, imaging["id"], fx.read_project(api, imaging["id"])["version"],
                                description="Lead-lined wall assemblies", category="SHIELDING",
                                cost_amount=88000.00)
    overridden = fx.add_line_item(api, imaging["id"], fx.read_project(api, imaging["id"])["version"],
                                 description="Reception millwork", category="FINISHES",
                                 cost_amount=40000.00, landlord_share_pct_override=0.25)
    defaulted = fx.add_line_item(api, imaging["id"], fx.read_project(api, imaging["id"])["version"],
                                description="Dedicated feeder and panel", category="POWER",
                                cost_amount=30000.00)

    # The category rule outranks both the override slot and the project default.
    assert shielding["sequence_no"] == 1, (
        "expected sequence_no 1, got {}".format(shielding["sequence_no"]))
    assert_line_split(shielding, 1.0000, 88000.00, 0.00)
    assert expected_line_split(88000.00, 1.0000) == (88000.00, 0.00)

    assert overridden["sequence_no"] == 2, (
        "expected sequence_no 2, got {}".format(overridden["sequence_no"]))
    assert_line_split(overridden, 0.2500, 10000.00, 30000.00)
    assert expected_line_split(40000.00, 0.2500) == (10000.00, 30000.00)

    assert defaulted["sequence_no"] == 3, (
        "expected sequence_no 3, got {}".format(defaulted["sequence_no"]))
    assert_line_split(defaulted, 0.6000, 18000.00, 12000.00)
    assert expected_line_split(30000.00, 0.6000) == (18000.00, 12000.00)

    project = fx.read_project(api, imaging["id"])
    assert_project_rollups(project, expected_landlord_total=116000.00,
                           expected_tenant_total=42000.00,
                           expected_allowance_remaining=384000.00, expected_line_count=3)

    lines, lines_meta = validate_paginated(api.list_ti_line_items(imaging["id"], LEASING_AGENT))
    assert_total_count(lines_meta, 3)
    assert [row["sequence_no"] for row in lines] == [1, 2, 3], (
        "lines must read back in sequence_no order, got {}".format(
            [row["sequence_no"] for row in lines]))

    # The category rule keys on the target class, not on the category alone.
    second = fx.add_lease_on_new_suite(api, ctx, suite_overrides={"floor": 4})
    procedure = fx.open_ti_project(api, second["lease"]["id"], second["suite"]["id"],
                                  target_suite_class="PROCEDURE",
                                  authorized_allowance_total=300000.00,
                                  landlord_share_pct=0.60)
    plain_shielding = fx.add_line_item(
        api, procedure["id"], fx.read_project(api, procedure["id"])["version"],
        description="Partial shielding upgrade", category="SHIELDING", cost_amount=50000.00)
    assert_line_split(plain_shielding, 0.6000, 30000.00, 20000.00)
    assert_project_rollups(fx.read_project(api, procedure["id"]),
                           expected_landlord_total=30000.00, expected_tenant_total=20000.00,
                           expected_allowance_remaining=270000.00, expected_line_count=1)


def test_rolling_score_caps_at_one_hundred_while_the_strict_score_does_not(api):
    """Three maximum-tier events read 100 rolling and 150 strict on the same tenant.

    PRD: "`referral_compliance_risk_score` is the **rolling twelve-month**
    operational figure: it considers only those events whose `due_date` falls on
    or after the clock date minus 365 days, sums their weights, and then caps the
    result at 100."
    PRD: "`strict_cumulative_risk_score` is the **audit** figure: it sums the
    weights of every qualifying event of that tenant with no date window at all
    and applies no cap, which is the number an external reviewer reconstructs
    from the ledger."
    PRD: "And the rolling figure saturates while the strict one keeps climbing,
    so a practice with four maximum-tier events reads 100 rolling and 200
    strict."
    PRD: "The tenant's leases are resolved first, then their invoices; the
    invoices are filtered to those carrying a weight above zero; for the rolling
    variant only, they are then filtered by the inclusive lower bound on
    `due_date` (never on `paid_on`); the weights are summed; the rolling sum
    alone is capped at 100; and finally the **rolling** figure — never the strict
    one — is compared to the watch threshold."
    PRD: "Both figures are integers and no rounding is involved anywhere in their
    derivation, which is why no rounding argument can reconcile them."
    PRD: "a day count of at most 30 carries a weight of 15, a count of at most 60
    carries 30, and a count beyond 60 carries 50."

    Design: Corner/calculations/rolling_score_caps_at_one_hundred_while_the_strict_score_does_not
    """
    ctx = fx.active_lease(api)
    lease_id = ctx["lease"]["id"]
    tenant_id = ctx["tenant"]["id"]

    first = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    second = fx.issue_invoice(api, lease_id, "2026-10-01", "2026-10-31", "2026-10-05")
    third = fx.issue_invoice(api, lease_id, "2026-11-01", "2026-11-30", "2026-11-05")

    fx.set_clock_date(api, "2027-01-10")
    fx.run_daily_close(api)

    rows, _meta = validate_paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    for invoice, day_count in ((first, 127), (second, 97), (third, 66)):
        row = _row_by_id(rows, invoice["id"])
        assert row["status"] == "DELINQUENT", (
            "expected DELINQUENT, got {}".format(row["status"]))
        assert row["days_past_due_at_flag"] == day_count, (
            "expected days_past_due_at_flag {}, got {}".format(
                day_count, row["days_past_due_at_flag"]))
        assert row["delinquency_tier_weight"] == 50, (
            "a day count beyond 60 carries 50, got {}".format(
                row["delinquency_tier_weight"]))

    delinquent, delinquent_meta = validate_paginated(
        api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER, {"status": "DELINQUENT"}))
    assert_total_count(delinquent_meta, 3)
    assert len(delinquent) == 3

    tenant = fx.read_tenant(api, tenant_id)
    assert tenant["referral_compliance_risk_score"] == 100, (
        "three weights of 50 must saturate the rolling figure at 100, got {}".format(
            tenant["referral_compliance_risk_score"]))
    assert tenant["strict_cumulative_risk_score"] == 150, (
        "the strict figure applies no cap and must read 150, got {}".format(
            tenant["strict_cumulative_risk_score"]))
    assert tenant["delinquency_event_count"] == 3, (
        "expected three delinquency events, got {}".format(
            tenant["delinquency_event_count"]))
    assert tenant["compliance_watch_status"] == "WATCH", (
        "expected WATCH, got {}".format(tenant["compliance_watch_status"]))
    assert isinstance(tenant["referral_compliance_risk_score"], int), (
        "the rolling score is an integer, got {!r}".format(
            tenant["referral_compliance_risk_score"]))
    assert isinstance(tenant["strict_cumulative_risk_score"], int), (
        "the strict score is an integer, got {!r}".format(
            tenant["strict_cumulative_risk_score"]))

    cases, _cases_meta = validate_paginated(
        api.list_tenant_compliance_cases(tenant_id, COMPLIANCE_OFFICER))
    rent_cases = [case for case in cases if case["case_type"] == "RENT_DELINQUENCY"]
    assert rent_cases, "flagging arrears above the threshold must open a rent-delinquency case"
    for case in rent_cases:
        assert case["scoring_variant"] == "ROLLING_12M", (
            "expected scoring_variant ROLLING_12M, got {}".format(case["scoring_variant"]))
        assert case["opened_by_user_id"] == "system", (
            "expected opened_by_user_id 'system', got {}".format(case["opened_by_user_id"]))


def test_fmv_band_ignores_appraisals_for_a_non_physician_tenant(api):
    """A non-physician tenant is banded on the rate card alone, appraisal or not.

    PRD: "The published floor is 80% of that figure and the published ceiling is
    115% of it, each rounded half up to 2 decimal places."
    PRD: "For a tenant whose `is_physician_owned` is false, that published pair
    **is** the band: `certified_fmv_floor_psf` is the published floor and
    `certified_fmv_ceiling_psf` is the published ceiling, and no appraisal is
    consulted."
    PRD: "Filing computes two fields immediately. `opinion_midpoint_psf` is the
    mean of the two ends, rounded half up to 2 decimal places."
    PRD: "Once `fmv_certification_status` reads `CERTIFIED`, the lease is carried
    at the negotiated rate: `certified_base_rent_annual` is
    `base_rent_psf_annual` multiplied by the suite's `rentable_sf`, rounded half
    up to 2 decimal places, and `effective_base_rent_annual` equals it — except
    while the lease is in `HOLDOVER`, where the effective figure is the certified
    figure multiplied by 1.50 and rounded half up to 2 decimal places."
    PRD: "One further consequence fires conditionally: when the **absolute
    value** of `fmv_variance_pct` is strictly greater than 0.1500, the system
    opens an `FMV_DEVIATION` compliance case against the tenant in status `OPEN`,
    measured under the rolling twelve-month variant, with `opened_by_user_id`
    recorded as the literal value `system`, and then re-evaluates that tenant's
    `compliance_watch_status`."

    Design: Corner/calculations/fmv_band_ignores_appraisals_for_a_non_physician_tenant
    """
    building = fx.register_building(api)
    high_suite = fx.register_suite(api, building["id"], suite_number="220", rentable_sf=5000)
    low_suite = fx.register_suite(api, building["id"], suite_number="230", rentable_sf=5000)
    tenant = fx.register_tenant(api, is_physician_owned=False)

    published_floor, published_ceiling = published_band(30.00, "STANDARD_EXAM")
    assert (published_floor, published_ceiling) == (24.00, 34.50), (
        "expected the published pair 24.00 / 34.50, got {} / {}".format(
            published_floor, published_ceiling))

    # A stingy opinion would clamp the ceiling to 28.60 if it were consulted.
    high_lease = fx.draft_lease(api, building["id"], high_suite["id"], tenant["id"],
                                base_rent_psf_annual=32.00)
    stingy = fx.file_appraisal(api, high_lease["id"], high_lease["version"],
                              opinion_low_psf=24.00, opinion_high_psf=28.00)
    assert round_money(stingy["opinion_midpoint_psf"]) == 26.00, (
        "expected a midpoint of 26.00, got {}".format(stingy["opinion_midpoint_psf"]))
    fx.qualify_appraisal(api, stingy["id"])

    # A generous opinion would clamp the floor to 28.80 if it were consulted.
    low_lease = fx.draft_lease(api, building["id"], low_suite["id"], tenant["id"],
                               base_rent_psf_annual=26.00)
    generous = fx.file_appraisal(api, low_lease["id"], low_lease["version"],
                                opinion_low_psf=30.00, opinion_high_psf=34.00)
    assert round_money(generous["opinion_midpoint_psf"]) == 32.00, (
        "expected a midpoint of 32.00, got {}".format(generous["opinion_midpoint_psf"]))
    fx.qualify_appraisal(api, generous["id"])

    fx.submit_for_review(api, high_lease["id"])
    certified_high = validate_success(
        api.certify_fmv(high_lease["id"], {"certification_note": "Rate card band applies"},
                        COMPLIANCE_OFFICER), 200)
    assert certified_high["status"] == "FMV_CERTIFIED", (
        "32.00 sits inside the published band and must certify, got {}".format(
            certified_high["status"]))
    assert certified_high["fmv_certification_status"] == "CERTIFIED", (
        "expected CERTIFIED, got {}".format(certified_high["fmv_certification_status"]))
    assert round_money(certified_high["certified_fmv_ceiling_psf"]) == 34.50, (
        "the ceiling must stay at the published 34.50, got {}".format(
            certified_high["certified_fmv_ceiling_psf"]))
    assert round_money(certified_high["certified_fmv_floor_psf"]) == 24.00, (
        "the floor must stay at the published 24.00, got {}".format(
            certified_high["certified_fmv_floor_psf"]))
    assert round_money(certified_high["certified_base_rent_annual"]) == 160000.00, (
        "expected 160000.00, got {}".format(certified_high["certified_base_rent_annual"]))

    fx.submit_for_review(api, low_lease["id"])
    certified_low = validate_success(
        api.certify_fmv(low_lease["id"], {"certification_note": "Rate card band applies"},
                        COMPLIANCE_OFFICER), 200)
    assert certified_low["status"] == "FMV_CERTIFIED", (
        "26.00 sits inside the published band and must certify, got {}".format(
            certified_low["status"]))
    assert round_money(certified_low["certified_fmv_floor_psf"]) == 24.00, (
        "the floor must stay at the published 24.00, got {}".format(
            certified_low["certified_fmv_floor_psf"]))
    assert round_money(certified_low["certified_fmv_ceiling_psf"]) == 34.50, (
        "the ceiling must stay at the published 34.50, got {}".format(
            certified_low["certified_fmv_ceiling_psf"]))
    assert round_money(certified_low["certified_base_rent_annual"]) == 130000.00, (
        "expected 130000.00, got {}".format(certified_low["certified_base_rent_annual"]))

    # Both variances stay inside 0.1500, so no deviation case is opened.
    assert round_share(certified_high["fmv_variance_pct"]) == 0.0667, (
        "expected 0.0667, got {}".format(certified_high["fmv_variance_pct"]))
    assert round_share(certified_low["fmv_variance_pct"]) == -0.1333, (
        "expected -0.1333, got {}".format(certified_low["fmv_variance_pct"]))
    _cases, cases_meta = validate_paginated(
        api.list_tenant_compliance_cases(tenant["id"], COMPLIANCE_OFFICER))
    assert_total_count(cases_meta, 0)

    appraisals, _appraisal_meta = validate_paginated(
        api.list_lease_appraisals(high_lease["id"], COMPLIANCE_OFFICER))
    assert len(appraisals) == 1
    assert appraisals[0]["status"] == "QUALIFIED", (
        "expected QUALIFIED, got {}".format(appraisals[0]["status"]))
