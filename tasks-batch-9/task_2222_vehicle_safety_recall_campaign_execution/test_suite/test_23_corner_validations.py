"""
Boundary validation: the admissibility cap on billed hours, the mailing calendar,
the safety holds, the reimbursement window and ceiling, the duplicate and
parts-availability guards, and the closure gate.
"""

from test_helpers import (
    AdjudicationDecision,
    AllocationStatus,
    ApiErrorId,
    CampaignStatus,
    ClaimStatus,
    RegionCode,
    ReimbursementStatus,
    RemedyStatus,
    SaleStatus,
    VehicleRemedyStatus,
    WaveStatus,
    WaveType,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_dealer_service_manager_headers,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
)

TWO_NE_BUILDS = [
    {
        "vin": "1HGCM82633A004352",
        "production_date": "2024-03-15",
        "suspect_part_number": 1500,
        "owner_name": "Ann Vega",
    },
    {
        "vin": "1HGCM82633A004353",
        "production_date": "2024-03-16",
        "suspect_part_number": 1501,
        "owner_name": "Ben Ito",
    },
]

# A window wide enough to hold both a pre-recall invoice date and the repair
# dates the reimbursement scenarios use.
WIDE_WINDOW = {"effective_from": "2025-01-01", "effective_to": "2027-12-31"}


def test_claimed_hours_a_tick_over_the_admissibility_cap_are_refused(api):
    """
    The published flat time is 1.10 hours, so the admissibility ceiling is 1.65;
    billing 1.70 is refused and nothing downstream moves — no unit is reserved and
    the row stays unrepaired.

    PRD §3.7: "The claimed hours are capped for admissibility at **one and a half
    times** the labor operation's published `flat_hours`, with a value exactly
    equal to that product still admissible and anything above it rejected with
    `ERR_LABOR_HOURS_EXCEED_CAP`."

    PRD §3.7: "When no candidate qualifies, the submission is rejected with
    `ERR_NO_PARTS_AVAILABLE`."

    Design: Corner/validations/claimed_hours_one_tick_over_the_tolerance_returns_labor_hours_exceed_cap
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-312"},
        labor_operation={"labor_op_code": "R312-01", "flat_hours": 1.10},
        remedy_part={"part_number": "P-88312"},
    )
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    response = api.create_repair_claim(
        f.repair_claim_payload(
            row["id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-08-03",
            claimed_labor_hours=1.70,
            parts_used_qty=1,
        ),
        state["dealer_headers"],
    )
    validate_error(response, ApiErrorId.LABOR_HOURS_EXCEED_CAP, 422)

    read_list(
        api.list_repair_claims(CLAIMS_AUDITOR, {"campaign_id": state["campaign_id"]}),
        expected_total=0,
    )

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0
    assert allocation["status"] == AllocationStatus.ALLOCATED

    unchanged = get_success_data(api.get_affected_vehicle(row["id"], OPERATIONS_MANAGER))
    assert unchanged["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert unchanged["approved_claim_count"] == 0


def test_claimed_hours_exactly_at_the_cap_product_are_admitted(api):
    """
    1.65 is the cap itself, so the claim is accepted and priced off the dealer's own
    posted numbers with no ceiling applied: 228.92 labour plus 25.19 marked-up parts
    plus the 12.00 allowance.

    PRD §3.7: "The claimed hours are capped for admissibility at **one and a half
    times** the labor operation's published `flat_hours`, with a value exactly
    equal to that product still admissible and anything above it rejected with
    `ERR_LABOR_HOURS_EXCEED_CAP`."

    PRD §3.7: "The labor component is the `claimed_labor_hours` multiplied by the
    dealer's `labor_rate_per_hour`, rounded to two decimal places. The parts
    component is the dealer's full reported `parts_used_qty` multiplied by the
    remedy part's `unit_cost`, then increased by a fifteen percent parts-handling
    markup — that is, multiplied by one plus fifteen hundredths — and rounded to two
    decimal places. A flat administrative allowance of 12.00 dollars is always
    added."

    Design: Corner/validations/claimed_hours_exactly_at_the_tolerance_product_is_accepted
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-313"},
        labor_operation={"labor_op_code": "R313-01", "flat_hours": 1.10},
        remedy_part={"part_number": "P-88313", "unit_cost": 21.90},
    )
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    claim = validate_success(
        api.create_repair_claim(
            f.repair_claim_payload(
                row["id"],
                state["dealer_id"],
                state["labor_operation_id"],
                repair_date="2026-08-03",
                claimed_labor_hours=1.65,
                parts_used_qty=1,
            ),
            state["dealer_headers"],
        ),
        201,
    )

    assert claim["status"] == ClaimStatus.SUBMITTED
    assert claim["claimed_labor_hours"] == 1.65
    assert claim["provisional_amount_cents"] == 26611
    assert claim["final_amount_cents"] is None


def test_wave_thirteen_days_from_a_sibling_drop_is_refused(api):
    """
    Thirteen days of separation is closer than the fourteen the rule demands, so the
    second NE drop is refused; moving it one day further out clears the rule and the
    wave opens as sibling number two.

    PRD §3.6: "**A new wave's `scheduled_mail_date` must be at least fourteen whole
    days away from the `scheduled_mail_date` of every non-`CANCELLED` wave of the
    same campaign and the same `target_region_code`**, measured as an absolute
    difference in calendar days in either direction; a separation of exactly
    fourteen days is acceptable and anything closer is rejected with
    `ERR_WAVE_MAILING_TOO_CLOSE`."

    PRD §3.6: "It receives a `sequence_number` equal to one more than the number of
    its non-`CANCELLED` sibling waves on the same campaign, where siblings are
    ordered by `scheduled_mail_date` ascending and then `created_at` ascending."

    Design: Corner/validations/wave_scheduled_thirteen_days_from_a_sibling_returns_mailing_too_close
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-314"})
    fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.INTERIM,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-20",
    )

    response = api.create_notification_wave(
        state["campaign_id"],
        f.notification_wave_payload(
            wave_type=WaveType.INTERIM,
            target_region_code=RegionCode.NE,
            scheduled_mail_date="2026-09-02",
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.WAVE_MAILING_TOO_CLOSE, 409)

    accepted = validate_success(
        api.create_notification_wave(
            state["campaign_id"],
            f.notification_wave_payload(
                wave_type=WaveType.INTERIM,
                target_region_code=RegionCode.NE,
                scheduled_mail_date="2026-09-03",
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert accepted["sequence_number"] == 2
    assert accepted["status"] == WaveStatus.PLANNED

    read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER), expected_total=2
    )


def test_mailing_before_the_scheduled_drop_date_is_refused(api):
    """
    The wave is approved for a 20 August drop while the clock still reads 3 August,
    so the drop is refused and the wave keeps its approval untouched; once the clock
    reaches the drop date the same call succeeds, and an interim drop leaves the
    campaign where it stood.

    PRD §3.6: "Dropping the wave requires status `RELEASE_APPROVED` and requires the
    logical clock's current date to have reached the `scheduled_mail_date`; an
    earlier attempt is rejected with `ERR_WAVE_MAIL_DATE_NOT_REACHED`."

    PRD §3.6: "An `INTERIM` drop never changes `campaign_status`."

    Design: Corner/validations/mailing_a_wave_before_its_scheduled_drop_date_is_refused
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-315"})
    campaign = fx.issue_interim_advisory(
        api, state["campaign_id"], stop_sale=False, do_not_drive=False
    )
    assert campaign["campaign_status"] == CampaignStatus.INTERIM_NOTIFIED
    assert campaign["remedy_status"] == RemedyStatus.INTERIM_ONLY

    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.INTERIM,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-20",
    )
    fx.release_wave(api, wave["id"])

    validate_error(
        api.mail_wave(wave["id"], {}, OPERATIONS_MANAGER),
        ApiErrorId.WAVE_MAIL_DATE_NOT_REACHED,
        409,
    )

    waves, _ = read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER), expected_total=1
    )
    assert waves[0]["status"] == WaveStatus.RELEASE_APPROVED
    assert waves[0]["mailed_vehicle_count"] == 0
    assert waves[0]["actual_mail_date"] is None

    fx.set_clock(api, "2026-08-20T08:00:00Z")
    mailed = validate_success(api.mail_wave(wave["id"], {}, OPERATIONS_MANAGER), 200)
    assert mailed["status"] == WaveStatus.MAILED
    assert mailed["mailed_vehicle_count"] == 1
    assert mailed["actual_mail_date"].startswith("2026-08-20")

    assert fx.read_campaign(api, state["campaign_id"])["campaign_status"] == (
        CampaignStatus.INTERIM_NOTIFIED
    )


def test_selling_a_held_stock_unit_is_refused(api):
    """
    The advisory raises the hold on the unit still sitting in dealer stock, and while
    the hold stands the unit cannot be retitled as sold.

    PRD §3.4: "When `stop_sale` is true, every build record whose `sale_status` is
    `IN_DEALER_STOCK` and which has an affected-vehicle row for this campaign has
    its `stop_sale_hold` raised to true. A held vehicle may not be moved to
    `sale_status` `SOLD` while the hold stands; such an update is rejected with
    `ERR_STOP_SALE_ACTIVE`."

    Design: Corner/validations/selling_a_vehicle_under_stop_sale_hold_is_refused
    """
    state = fx.filed_campaign(
        api,
        campaign={"campaign_number": "26V-316"},
        vehicles=[{"sale_status": SaleStatus.IN_DEALER_STOCK, "owner_name": "Stock Unit"}],
    )
    fx.issue_interim_advisory(api, state["campaign_id"], stop_sale=True, do_not_drive=False)

    held = get_success_data(api.get_vehicle(state["vehicle_id"], OPERATIONS_MANAGER))
    assert held["stop_sale_hold"] is True

    response = api.update_vehicle(
        state["vehicle_id"],
        f.vehicle_update_payload(sale_status=SaleStatus.SOLD),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.STOP_SALE_ACTIVE, 409)

    unchanged = get_success_data(api.get_vehicle(state["vehicle_id"], OPERATIONS_MANAGER))
    assert unchanged["sale_status"] == SaleStatus.IN_DEALER_STOCK
    assert unchanged["stop_sale_hold"] is True


def test_interim_advisory_after_the_remedy_shipped_is_refused(api):
    """
    The campaign is still in FILED so the status gate passes, but the remedy has
    already been released — an interim notice has nothing left to warn about.

    PRD §3.4: "Issuing an interim advisory is a `SafetyEngineer` action available
    only from `campaign_status` `FILED` and only while `remedy_status` is
    `REMEDY_UNDER_DEVELOPMENT` — an interim notice is lawful only when no remedy
    exists, so attempting it once any remedy has been released or revised is
    rejected with `ERR_REMEDY_ALREADY_AVAILABLE`"

    Design: Corner/validations/interim_advisory_after_the_remedy_shipped_is_refused
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-317"},
        labor_operation={"labor_op_code": "R317-01"},
        remedy_part={"part_number": "P-88317"},
    )
    assert state["campaign"]["campaign_status"] == CampaignStatus.FILED
    assert state["campaign"]["remedy_status"] == RemedyStatus.REMEDY_RELEASED

    response = api.issue_interim_advisory(
        state["campaign_id"],
        f.interim_advisory_payload(stop_sale=True, do_not_drive=True),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.REMEDY_ALREADY_AVAILABLE, 409)

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["campaign_status"] == CampaignStatus.FILED
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_RELEASED
    assert campaign["stop_sale_flag"] is False
    assert campaign["do_not_drive_flag"] is False


def test_invoice_one_day_outside_the_lookback_is_refused(api):
    """
    The determination fell on 3 August 2026, so the 365-day lookback opens inclusively
    on 3 August 2025: an invoice dated the day before is outside the window, and the
    boundary date itself is inside it.

    PRD §3.9: "And the `invoice_date` must fall inside the reimbursement window: it
    must be on or after the calendar date of the campaign's
    `defect_determination_date` less a **one-year lookback of 365 days**, that
    boundary being inclusive"

    PRD §3.9: "A date outside the window is rejected with
    `ERR_REIMBURSEMENT_WINDOW_CLOSED`."

    Design: Corner/validations/invoice_one_day_outside_the_lookback_window_is_refused
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-318"})
    fx.add_labor_operation(
        api, state["campaign_id"], labor_op_code="R318-01", flat_hours=1.40, **WIDE_WINDOW
    )

    response = api.create_owner_reimbursement(
        f.owner_reimbursement_payload(
            state["campaign_id"],
            state["vehicle_id"],
            invoice_date="2025-08-02",
            invoice_amount=400.00,
            labor_hours_claimed=1.30,
            parts_amount=62.00,
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.REIMBURSEMENT_WINDOW_CLOSED, 422)

    accepted = validate_success(
        api.create_owner_reimbursement(
            f.owner_reimbursement_payload(
                state["campaign_id"],
                state["vehicle_id"],
                invoice_date="2025-08-03",
                invoice_amount=400.00,
                labor_hours_claimed=1.30,
                parts_amount=62.00,
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == ReimbursementStatus.SUBMITTED
    assert accepted["document_round"] == 0

    assert fx.read_campaign(api, state["campaign_id"])["reimbursement_obligation_cents"] == 0


def test_towing_pays_nothing_when_do_not_drive_was_never_declared(api):
    """
    No do-not-drive order was ever issued, so the 85.00 towing line is allowed
    nothing: the cap is 149.50 of labour plus 30.66 of parts, and the 400.00 invoice
    is settled at that 180.16 cap.

    PRD §3.9: "The towing allowance is paid only when the campaign's
    `do_not_drive_flag` is true, in which case it is the smaller of the owner's
    `towing_amount` and a towing cap of 100.00 dollars, rounded to two decimal
    places; when the flag is false the towing allowance is 0.00 regardless of what
    the invoice shows."

    PRD §3.9: "The payable amount is the smaller of the owner's `invoice_amount` and
    that cap, rounded to two decimal places, and `approved_amount_cents` is that
    amount multiplied by 100 and rounded to whole cents."

    Design: Corner/validations/towing_is_not_reimbursed_when_do_not_drive_was_never_declared
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-319"})
    fx.add_labor_operation(
        api, state["campaign_id"], labor_op_code="R319-01", flat_hours=1.40, **WIDE_WINDOW
    )
    fx.add_remedy_part(api, state["campaign_id"], part_number="P-88319", unit_cost=21.90)

    request = fx.submit_reimbursement(
        api,
        state["campaign_id"],
        state["vehicle_id"],
        invoice_date="2026-07-01",
        invoice_amount=400.00,
        labor_hours_claimed=1.30,
        parts_amount=62.00,
        towing_amount=85.00,
    )

    approved = validate_success(
        api.adjudicate_owner_reimbursement(
            request["id"],
            f.adjudicate_payload(decision=AdjudicationDecision.APPROVE),
            CLAIMS_AUDITOR,
        ),
        200,
    )
    assert approved["status"] == ReimbursementStatus.APPROVED
    assert approved["approved_amount_cents"] == 18016

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["reimbursement_obligation_cents"] == 18016
    assert campaign["do_not_drive_flag"] is False


def test_reimbursement_for_a_vehicle_outside_the_population_is_refused(api):
    """
    The second build came off a plant the inclusion rule never named, so no
    affected-vehicle row joins it to the campaign and the intake is refused before
    the window is even consulted.

    PRD §3.9: "An affected-vehicle row must already link the named `campaign_id` and
    `vehicle_id`; without one the request is rejected with
    `ERR_VEHICLE_NOT_IN_POPULATION`."

    Design: Corner/validations/reimbursement_for_a_vehicle_outside_the_population_is_refused
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-320"})
    fx.add_labor_operation(
        api, state["campaign_id"], labor_op_code="R320-01", flat_hours=1.40, **WIDE_WINDOW
    )
    outsider = fx.create_vehicle(
        api,
        vin="1HGCM82633A004399",
        plant_code="PLT9",
        production_date="2024-03-20",
        suspect_part_number=1505,
        owner_name="Zoe Park",
    )

    response = api.create_owner_reimbursement(
        f.owner_reimbursement_payload(
            state["campaign_id"],
            outsider["id"],
            invoice_date="2026-07-01",
            invoice_amount=400.00,
            labor_hours_claimed=1.30,
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.VEHICLE_NOT_IN_POPULATION, 422)

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["affected_vehicle_count"] == 1
    assert campaign["recall_population_count"] == 1

    read_list(
        api.list_owner_reimbursements(CLAIMS_AUDITOR, {"campaign_id": state["campaign_id"]}),
        expected_total=0,
    )


def test_invoice_one_cent_over_the_owner_maximum_is_refused(api):
    """
    The ceiling is an "above" test, so 5000.01 is refused while 5000.00 exactly is
    taken in.

    PRD §3.9: "Separately, an `invoice_amount` above 5000.00 dollars is rejected
    with `ERR_REIMBURSEMENT_INVOICE_EXCEEDS_MAX`, both at intake and on any
    re-keying."

    Design: Corner/validations/invoice_one_cent_over_the_owner_maximum_is_refused
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-321"})
    fx.add_labor_operation(
        api, state["campaign_id"], labor_op_code="R321-01", flat_hours=1.40, **WIDE_WINDOW
    )

    response = api.create_owner_reimbursement(
        f.owner_reimbursement_payload(
            state["campaign_id"],
            state["vehicle_id"],
            invoice_date="2026-07-01",
            invoice_amount=5000.01,
            labor_hours_claimed=1.30,
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.REIMBURSEMENT_INVOICE_EXCEEDS_MAX, 422)

    accepted = validate_success(
        api.create_owner_reimbursement(
            f.owner_reimbursement_payload(
                state["campaign_id"],
                state["vehicle_id"],
                invoice_date="2026-07-01",
                invoice_amount=5000.00,
                labor_hours_claimed=1.30,
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert accepted["invoice_amount"] == 5000.00
    assert accepted["status"] == ReimbursementStatus.SUBMITTED

    read_list(
        api.list_owner_reimbursements(CLAIMS_AUDITOR, {"campaign_id": state["campaign_id"]}),
        expected_total=1,
    )


def test_second_open_claim_on_the_same_vehicle_and_date_is_refused(api):
    """
    One SUBMITTED claim already stands for this row and this repair date, and a
    SUBMITTED claim is enough to block a second — the first need not have been
    approved.

    PRD §3.7: "Finally, no other claim for the same `affected_vehicle_id` and the
    same `repair_date` may already stand in status `SUBMITTED` or `APPROVED`, or the
    claim is rejected with `ERR_DUPLICATE_REPAIR_CLAIM`."

    Design: Corner/validations/second_open_claim_for_the_same_vehicle_and_repair_date_is_refused
    """
    state = fx.campaign_with_submitted_claim(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-322"},
        labor_operation={"labor_op_code": "R322-01"},
        remedy_part={"part_number": "P-88322"},
        claim={"repair_date": "2026-08-03", "claimed_labor_hours": 1.10, "parts_used_qty": 1},
    )

    response = api.create_repair_claim(
        f.repair_claim_payload(
            state["affected_vehicle_id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-08-03",
            claimed_labor_hours=1.10,
            parts_used_qty=1,
        ),
        state["dealer_headers"],
    )
    validate_error(response, ApiErrorId.DUPLICATE_REPAIR_CLAIM, 409)

    claims, _ = read_list(
        api.list_repair_claims(
            CLAIMS_AUDITOR, {"affected_vehicle_id": state["affected_vehicle_id"]}
        ),
        expected_total=1,
    )
    assert claims[0]["id"] == state["claim_id"]
    assert claims[0]["status"] == ClaimStatus.SUBMITTED


def test_claim_from_a_dealer_holding_no_kits_is_refused(api):
    """
    A hundred kits sit in the central pool but none of them have been allocated to
    this dealer, so there is no holding to draw the physical unit from.

    PRD §3.7: "Among the submitting dealer's parts allocations for the claim's
    campaign that are still in status `ALLOCATED` and still have at least one
    uncommitted unit — that is, an `allocated_qty` exceeding its `consumed_qty` by at
    least the one kit a repair consumes — the server ranks candidates by `created_at`
    ascending so the oldest holding drains first"

    PRD §3.7: "When no candidate qualifies, the submission is rejected with
    `ERR_NO_PARTS_AVAILABLE`."

    Design: Corner/validations/claim_without_any_allocated_units_returns_no_parts_available
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-323"},
        labor_operation={"labor_op_code": "R323-01"},
        remedy_part={"part_number": "P-88323", "total_procured_qty": 100},
    )
    dealer = fx.create_dealer(api)
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    response = api.create_repair_claim(
        f.repair_claim_payload(
            row["id"],
            dealer["id"],
            state["labor_operation_id"],
            repair_date="2026-08-03",
            claimed_labor_hours=1.10,
            parts_used_qty=1,
        ),
        make_dealer_service_manager_headers(dealer["id"]),
    )
    validate_error(response, ApiErrorId.NO_PARTS_AVAILABLE, 409)

    part = fx.read_part(api, state["campaign_id"], "P-88323")
    assert part["unallocated_qty"] == 100
    assert part["consumed_qty"] == 0

    unchanged = get_success_data(api.get_affected_vehicle(row["id"], OPERATIONS_MANAGER))
    assert unchanged["remedy_status"] == VehicleRemedyStatus.UNREPAIRED


def test_repair_dated_before_the_remedy_release_is_refused(api):
    """
    The remedy shipped on 3 August, and the labor operation's window opened a month
    earlier, so the 1 August repair clears the effectivity check and is caught by the
    remedy-release date instead; the same claim dated on the release day is accepted.

    PRD §3.7: "The `repair_date` must fall on or after the calendar date of the
    campaign's `remedy_released_at`; earlier work is rejected with
    `ERR_REPAIR_DATE_BEFORE_REMEDY`."

    Design: Corner/validations/repair_dated_before_the_remedy_release_is_refused
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-324"},
        labor_operation={
            "labor_op_code": "R324-01",
            "flat_hours": 1.10,
            "effective_from": "2026-07-01",
            "effective_to": "2027-12-31",
        },
        remedy_part={"part_number": "P-88324"},
    )
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    response = api.create_repair_claim(
        f.repair_claim_payload(
            row["id"],
            state["dealer_id"],
            state["labor_operation_id"],
            repair_date="2026-08-01",
            claimed_labor_hours=1.10,
            parts_used_qty=1,
        ),
        state["dealer_headers"],
    )
    validate_error(response, ApiErrorId.REPAIR_DATE_BEFORE_REMEDY, 422)

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0

    accepted = validate_success(
        api.create_repair_claim(
            f.repair_claim_payload(
                row["id"],
                state["dealer_id"],
                state["labor_operation_id"],
                repair_date="2026-08-03",
                claimed_labor_hours=1.10,
                parts_used_qty=1,
            ),
            state["dealer_headers"],
        ),
        201,
    )
    assert accepted["status"] == ClaimStatus.SUBMITTED
    assert accepted["repair_date"] == "2026-08-03"


def test_closing_below_the_completion_gate_is_refused(api):
    """
    One of two owners has been repaired, so the completion rate stands at 50.00 and
    only one quarter has been reported: closure is refused and the campaign is left
    exactly as it was, still in MONITORING with no closure note.

    PRD §3.9: "Beyond those, five gates must all hold, and a failure of any of them
    is reported as `ERR_CLOSURE_CRITERIA_NOT_MET`: `remedy_status` must be
    `REMEDY_RELEASED`, so a campaign sitting in `REMEDY_REVISED` cannot be closed;
    `completion_rate_pct` must be at least 95.00 percent; `remedy_effectiveness_score`
    must be at least 70.00 points; `quarterly_filing_count` must be at least 2,
    meaning two full quarters of reporting; and no notification wave of the campaign
    may remain in status `PLANNED` or `RELEASE_APPROVED`."

    PRD §3.9: "Closing the campaign is the last act, and it is a `ComplianceOfficer`
    action available only from `campaign_status` `MONITORING`."

    Design: Corner/validations/closing_a_campaign_below_the_completion_gate_is_refused
    """
    state = fx.monitored_campaign(
        api,
        report_period="2026Q3",
        scheduled_mail_date="2026-08-03",
        vehicles=TWO_NE_BUILDS,
        requested_qty=2,
        campaign={"campaign_number": "26V-325"},
        labor_operation={"labor_op_code": "R325-01"},
        remedy_part={"part_number": "P-88325"},
    )
    assert state["campaign"]["campaign_status"] == CampaignStatus.MONITORING
    assert state["campaign"]["completion_rate_pct"] == 50.00

    response = api.close_campaign(
        state["campaign_id"], f.close_campaign_payload(), COMPLIANCE_OFFICER_2
    )
    validate_error(response, ApiErrorId.CLOSURE_CRITERIA_NOT_MET, 409)

    campaign = fx.read_campaign(api, state["campaign_id"], COMPLIANCE_OFFICER_1)
    assert campaign["campaign_status"] == CampaignStatus.MONITORING
    assert campaign["closure_note"] is None
    assert campaign["completion_rate_pct"] == 50.00
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_RELEASED
    assert campaign["remedy_effectiveness_score"] == 100.00
    assert campaign["quarterly_filing_count"] == 1
