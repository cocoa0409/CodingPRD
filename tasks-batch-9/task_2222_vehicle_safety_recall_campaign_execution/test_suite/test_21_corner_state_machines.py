"""
Lifecycle transitions: the two campaign dimensions, the wave and claim state
gates, the row-level remedy statuses driven by outreach, and the supersession
and amendment fan-outs.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    AuditDecision,
    CampaignStatus,
    CancelReason,
    ClaimStatus,
    FilingStatus,
    FilingType,
    OutreachChannel,
    OutreachOutcome,
    RegionCode,
    ReimbursementStatus,
    RemedyStatus,
    RevokedReason,
    VehicleRemedyStatus,
    WaveStatus,
    WaveType,
    assert_notification_wave,
    assert_outreach_attempt,
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
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
    SAFETY_ENGINEER_1_ID,
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

STOCK_UNIT = {"sale_status": "IN_DEALER_STOCK", "owner_name": "Stock Unit"}

HISTORICAL_LABOR_OP = {
    "labor_op_code": "R210-00",
    "description": "Pre-recall inflator replacement performed at owner expense",
    "flat_hours": 1.30,
    "rate_type": "PREVAILING",
    "effective_from": "2025-01-01",
    "effective_to": "2026-07-31",
}


def test_defect_determination_carries_the_draft_file_to_defect_determined(api):
    """
    The determination is the only exit from DRAFT: it advances the regulatory
    dimension, overwrites the severity band recorded at creation, stamps the
    deciding operator, and leaves the remedy dimension where it was.

    PRD §3.1: "The safety committee's decision is recorded next, moving the file
    from `DRAFT` to `DEFECT_DETERMINED`; attempting it from any other
    `campaign_status` yields `ERR_INVALID_CAMPAIGN_STATE`."

    PRD §3.1: "The `SafetyEngineer` supplies `defect_determination_date` as a
    valid ISO 8601 UTC instant, and may supply `risk_severity` at the same time to
    overwrite the severity band recorded at creation. The server stamps
    `determined_by_user_id` with the caller's `X-User-ID`, increments `version` by
    1, and computes the statutory `filing_deadline_utc`."

    Design: Corner/state_machines/defect_determination_moves_campaign_from_draft_to_defect_determined
    """
    state = fx.draft_campaign(api, campaign_number="26V-200")
    assert state["campaign"]["campaign_status"] == CampaignStatus.DRAFT

    campaign = validate_success(
        api.record_defect_determination(
            state["campaign_id"],
            f.defect_determination_payload(
                defect_determination_date="2026-08-03T09:00:00Z", risk_severity="HIGH"
            ),
            SAFETY_ENGINEER_1,
        ),
        200,
    )

    assert campaign["campaign_status"] == CampaignStatus.DEFECT_DETERMINED
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_UNDER_DEVELOPMENT
    assert campaign["risk_severity"] == "HIGH"
    assert campaign["determined_by_user_id"] == SAFETY_ENGINEER_1_ID
    assert campaign["filing_deadline_utc"] == "2026-08-10T23:59:59Z"


def test_second_defect_determination_on_a_filed_campaign_is_refused(api):
    """
    DRAFT is the only legal origin, so once the notice is filed a fresh
    determination cannot re-open the clock: the deadline computed from the first
    determination stands.

    PRD §3.1: "The safety committee's decision is recorded next, moving the file
    from `DRAFT` to `DEFECT_DETERMINED`; attempting it from any other
    `campaign_status` yields `ERR_INVALID_CAMPAIGN_STATE`."

    PRD §3.1: "Starting from the UTC calendar date of `defect_determination_date`,
    the server steps forward one calendar day at a time, counting a day only when
    it falls Monday through Friday and is not a federal holiday, until five such
    days have been counted; `filing_deadline_utc` is that fifth counted date
    pinned to 23:59:59Z."

    Design: Corner/state_machines/second_defect_determination_from_filed_returns_invalid_campaign_state
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-201"})
    assert state["campaign"]["campaign_status"] == CampaignStatus.FILED

    response = api.record_defect_determination(
        state["campaign_id"],
        f.defect_determination_payload(defect_determination_date="2026-08-05T09:00:00Z"),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.INVALID_CAMPAIGN_STATE, 409)

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["campaign_status"] == CampaignStatus.FILED
    assert campaign["filing_deadline_utc"] == "2026-08-10T23:59:59Z"


def test_interim_advisory_advances_both_dimensions_and_holds_dealer_stock(api):
    """
    One request moves the regulatory dimension to INTERIM_NOTIFIED and the remedy
    dimension to INTERIM_ONLY, records both advisory booleans, and raises the
    sales hold on the unsold unit sitting in dealer stock.

    PRD §3.4: "Acceptance advances both dimensions at once — `campaign_status`
    from `FILED` to `INTERIM_NOTIFIED` and `remedy_status` from
    `REMEDY_UNDER_DEVELOPMENT` to `INTERIM_ONLY` — records the two booleans into
    `stop_sale_flag` and `do_not_drive_flag`, and increments the campaign's
    `version` by 1."

    PRD §3.4: "When `stop_sale` is true, every build record whose `sale_status` is
    `IN_DEALER_STOCK` and which has an affected-vehicle row for this campaign has
    its `stop_sale_hold` raised to true."

    Design: Corner/state_machines/interim_advisory_places_stop_sale_hold_on_dealer_stock_vehicle
    """
    state = fx.filed_campaign(
        api, vehicles=[STOCK_UNIT], campaign={"campaign_number": "26V-202"}
    )

    campaign = validate_success(
        api.issue_interim_advisory(
            state["campaign_id"],
            f.interim_advisory_payload(
                stop_sale=True,
                do_not_drive=True,
                justification="Remedy parts not yet available; rupture risk on deployment",
            ),
            SAFETY_ENGINEER_1,
        ),
        200,
    )

    assert campaign["campaign_status"] == CampaignStatus.INTERIM_NOTIFIED
    assert campaign["remedy_status"] == RemedyStatus.INTERIM_ONLY
    assert campaign["stop_sale_flag"] is True
    assert campaign["do_not_drive_flag"] is True

    vehicle = get_success_data(api.get_vehicle(state["vehicle_id"], OPERATIONS_MANAGER))
    assert vehicle["stop_sale_hold"] is True


def test_mailing_a_wave_that_was_never_released_is_refused(api):
    """
    PLANNED is not a legal origin for the drop: the mailing is refused on the wave
    state gate, and nothing about the wave or the campaign moves.

    PRD §3.6: "Dropping the wave requires status `RELEASE_APPROVED` and requires
    the logical clock's current date to have reached the `scheduled_mail_date`; an
    earlier attempt is rejected with `ERR_WAVE_MAIL_DATE_NOT_REACHED`."

    PRD §2.7: "**State gates**, in this precedence: campaign state
    (`ERR_INVALID_CAMPAIGN_STATE`), wave state (`ERR_WAVE_INVALID_STATE`), claim
    state (`ERR_CLAIM_INVALID_STATE`), reimbursement state
    (`ERR_REIMBURSEMENT_INVALID_STATE`), allocation state
    (`ERR_ALLOCATION_INVALID_STATE`), affected-vehicle repairability
    (`ERR_VEHICLE_NOT_REPAIRABLE`)."

    Design: Corner/state_machines/mailing_a_wave_that_was_never_released_returns_wave_invalid_state
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-203"})
    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-03",
    )
    assert wave["status"] == WaveStatus.PLANNED

    validate_error(
        api.mail_wave(wave["id"], {}, OPERATIONS_MANAGER),
        ApiErrorId.WAVE_INVALID_STATE,
        409,
    )

    waves, _ = read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER),
        expected_total=1,
    )
    assert waves[0]["status"] == WaveStatus.PLANNED
    assert waves[0]["mailed_vehicle_count"] == 0
    assert waves[0]["actual_mail_date"] is None

    assert fx.read_campaign(api, state["campaign_id"])["campaign_status"] == CampaignStatus.FILED


def test_newly_planned_wave_enters_at_planned_with_sequence_one(api):
    """
    A hand-planned wave is the operator's own: it enters PLANNED with
    `auto_created` false, takes sequence number one as the campaign's first
    non-cancelled wave, and carries every quota field at zero.

    PRD §3.6: "A planned wave starts in status `PLANNED` with `auto_created`
    false, all its quota fields at their zero defaults, `mailed_vehicle_count` 0,
    and `actual_mail_date` and `cancel_reason` unset."

    PRD §3.6: "It receives a `sequence_number` equal to one more than the number
    of its non-`CANCELLED` sibling waves on the same campaign, where siblings are
    ordered by `scheduled_mail_date` ascending and then `created_at` ascending."

    Design: Corner/state_machines/newly_created_notification_wave_starts_in_planned_with_sequence_one
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-204"})

    wave = validate_success(
        api.create_notification_wave(
            state["campaign_id"],
            f.notification_wave_payload(
                wave_type=WaveType.INTERIM,
                target_region_code=RegionCode.NE,
                scheduled_mail_date="2026-08-20",
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert_notification_wave(wave)

    assert wave["status"] == WaveStatus.PLANNED
    assert wave["sequence_number"] == 1
    assert wave["auto_created"] is False
    assert wave["cancel_reason"] is None
    assert wave["wave_type"] == WaveType.INTERIM
    assert wave["target_region_code"] == RegionCode.NE
    assert wave["scheduled_mail_date"] == "2026-08-20"
    assert wave["planned_vehicle_count"] == 0
    assert wave["mailed_vehicle_count"] == 0
    assert wave["actual_mail_date"] is None


def test_auditing_an_already_rejected_claim_is_refused(api):
    """
    A rejected claim is finished: a second decision — even an approval — cannot
    reach it, so the kit stays uncommitted and the ledger never moves.

    PRD §3.7: "The claim must be in status `SUBMITTED`; auditing a claim in any
    other status is rejected with `ERR_CLAIM_INVALID_STATE`."

    PRD §3.7: "A **rejection** stores the `audit_note`, leaves `final_amount_cents`
    null, moves the claim to `REJECTED`, decrements the labor operation's
    `claim_count` by 1, and increments the claim's `version` by 1. Nothing else
    moves: no affected-vehicle transition, no part consumption, and no ledger
    movement whatsoever."

    Design: Corner/state_machines/auditing_an_already_rejected_claim_returns_claim_invalid_state
    """
    state = fx.campaign_with_submitted_claim(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-205"},
        labor_operation={"labor_op_code": "R205-01"},
        remedy_part={"part_number": "P-88205"},
    )
    rejected = fx.audit_claim(
        api,
        state["claim_id"],
        AuditDecision.REJECT,
        audit_note="Repair order does not match the labor operation performed",
    )
    assert rejected["status"] == ClaimStatus.REJECTED

    validate_error(
        api.audit_repair_claim(
            state["claim_id"],
            f.audit_payload(decision=AuditDecision.APPROVE, audit_note="Re-reviewed and allowed"),
            CLAIMS_AUDITOR,
        ),
        ApiErrorId.CLAIM_INVALID_STATE,
        409,
    )

    claim = get_success_data(api.get_repair_claim(state["claim_id"], CLAIMS_AUDITOR))
    assert claim["status"] == ClaimStatus.REJECTED
    assert claim["provisional_amount_cents"] == 18980
    assert claim["final_amount_cents"] is None

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["reimbursement_obligation_cents"] == 0
    assert campaign["remedied_count"] == 0
    assert campaign["completion_rate_pct"] == 0.00

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0
    assert allocation["status"] == AllocationStatus.ALLOCATED

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert row["approved_claim_count"] == 0


def _monitoring_campaign_after_one_quarterly(api, campaign_number, labor_op_code, part_number):
    """One NE owner notified by a mailed REMEDY wave, with 2026Q3 on file."""
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": campaign_number},
        labor_operation={"labor_op_code": labor_op_code},
        remedy_part={"part_number": part_number},
    )
    state = fx.mailed_remedy_wave(api, state, scheduled_mail_date="2026-08-03")
    state["quarterly_filing"] = fx.file_quarterly(api, state["campaign_id"], "2026Q3")
    state["campaign"] = fx.read_campaign(api, state["campaign_id"])
    return state


def test_second_quarterly_report_for_the_same_period_is_refused(api):
    """
    MONITORING accepts quarter after quarter, so the state gate lets the retry
    through; what stops it is that 2026Q3 is already claimed.

    PRD §3.3: "Either way, a report is refused with `ERR_FILING_PERIOD_DUPLICATE`
    when another filing for the campaign already claims the same `report_period`,
    and refused with `ERR_INVALID_CAMPAIGN_STATE` when the campaign is in neither
    `OWNER_NOTIFIED` nor `MONITORING`."

    PRD §3.3: "A **quarterly completion report** is what moves the campaign from
    `OWNER_NOTIFIED` into `MONITORING`, and once in `MONITORING` each subsequent
    quarter's report is accepted as a self-loop that leaves `campaign_status` at
    `MONITORING`."

    Design: Corner/state_machines/second_quarterly_filing_for_same_report_period_returns_period_duplicate
    """
    state = _monitoring_campaign_after_one_quarterly(api, "26V-206", "R206-01", "P-88206")
    assert state["campaign"]["campaign_status"] == CampaignStatus.MONITORING

    validate_error(
        api.create_filing(
            state["campaign_id"],
            f.quarterly_filing_payload(
                report_period="2026Q3",
                narrative="Corrected quarterly completion report 2026Q3",
            ),
            COMPLIANCE_OFFICER_1,
        ),
        ApiErrorId.FILING_PERIOD_DUPLICATE,
        409,
    )

    read_list(
        api.list_filings(
            state["campaign_id"], COMPLIANCE_OFFICER_1, {"filing_type": FilingType.QUARTERLY}
        ),
        expected_total=1,
    )

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["quarterly_filing_count"] == 1
    assert campaign["campaign_status"] == CampaignStatus.MONITORING


def test_remedy_drop_reaches_owner_notified_without_an_interim_notice(api):
    """
    Because the remedy shipped before any interim letter was needed, the campaign
    joins OWNER_NOTIFIED straight from FILED, and the owner's row is stamped with
    a REMEDY notice rather than an INTERIM one.

    PRD §3.6: "A `REMEDY` or `FOLLOW_UP` drop also carries the campaign from
    `FILED` or from `INTERIM_NOTIFIED` to `OWNER_NOTIFIED` — the diamond join,
    since `FILED` reaches `OWNER_NOTIFIED` either directly, when the remedy
    shipped before any interim notice was needed, or by way of
    `INTERIM_NOTIFIED`"

    PRD §3.6: "Each stamped row records the wave in `notification_wave_id`, has
    `notice_count` incremented by one, has `last_notice_type` set to the wave's
    `wave_type` and `last_notice_date` set to the clock, and has
    `requires_renotification` cleared to false."

    Design: Corner/state_machines/campaign_reaches_owner_notified_without_passing_through_interim_notified
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-207"},
        labor_operation={"labor_op_code": "R207-01"},
        remedy_part={"part_number": "P-88207"},
    )
    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-03",
    )
    approved = fx.release_wave(api, wave["id"])
    assert approved["status"] == WaveStatus.RELEASE_APPROVED

    mailed = validate_success(api.mail_wave(wave["id"], {}, OPERATIONS_MANAGER), 200)
    assert mailed["status"] == WaveStatus.MAILED
    assert mailed["mailed_vehicle_count"] == 1
    assert mailed["actual_mail_date"].startswith("2026-08-03")

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["campaign_status"] == CampaignStatus.OWNER_NOTIFIED
    assert campaign["stop_sale_flag"] is False
    assert campaign["do_not_drive_flag"] is False

    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    assert row["notice_count"] == 1
    assert row["last_notice_type"] == WaveType.REMEDY
    assert row["last_notice_date"].startswith("2026-08-03")
    assert row["notification_wave_id"] == wave["id"]
    assert row["requires_renotification"] is False

    vehicle = get_success_data(api.get_vehicle(state["vehicle_id"], OPERATIONS_MANAGER))
    assert vehicle["stop_sale_hold"] is False


def test_booking_a_repair_before_the_remedy_exists_is_refused(api):
    """
    The appointment is blocked by a state the row does not itself carry — the
    parent campaign's remedy dimension — so the dealer, the date and the row are
    all fine and the booking still fails.

    PRD §3.4: "Three operations are gated on the remedy actually existing:
    releasing a `REMEDY` or `FOLLOW_UP` notification wave, booking a repair
    appointment, and submitting a repair claim. Each requires `remedy_status` to
    be either `REMEDY_RELEASED` or `REMEDY_REVISED`; attempting any of the three
    while `remedy_status` is `REMEDY_UNDER_DEVELOPMENT` or `INTERIM_ONLY` is
    rejected with `ERR_REMEDY_NOT_AVAILABLE`."

    PRD §3.7: "Booking stores `dealer_id` and `scheduled_repair_date` on the row,
    advances its `remedy_status` to `SCHEDULED`, and increments the row's
    `version` by 1."

    Design: Corner/state_machines/scheduling_a_repair_while_remedy_under_development_returns_remedy_not_available
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-208"})
    assert state["campaign"]["remedy_status"] == RemedyStatus.REMEDY_UNDER_DEVELOPMENT

    dealer = fx.create_dealer(api)
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    validate_error(
        api.schedule_repair(
            row["id"],
            f.schedule_payload(dealer["id"], scheduled_repair_date="2026-08-20"),
            make_dealer_service_manager_headers(dealer["id"]),
        ),
        ApiErrorId.REMEDY_NOT_AVAILABLE,
        409,
    )

    unchanged = get_success_data(api.get_affected_vehicle(row["id"], OPERATIONS_MANAGER))
    assert unchanged["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert unchanged["dealer_id"] is None
    assert unchanged["scheduled_repair_date"] is None


def test_exporting_a_repaired_vehicle_pulls_its_row_out_of_the_population(api):
    """
    The disposal cascade reaches rows that were already REMEDIED: the row leaves
    the population, the remedied count and the regulatory rate fall back to zero,
    and the money already earned on the approved claim stands.

    PRD §3.2: "`REMOVED_FROM_POPULATION` is terminal for a row: once entered it is
    never left, and it is reachable from `UNREPAIRED`, `SCHEDULED`, `REMEDIED` and
    `UNREACHABLE` alike, which happens when a build record's `sale_status` is
    updated to `SCRAPPED` or `EXPORTED`."

    PRD §3.2: "That update leaves the campaign's `affected_vehicle_count`
    unchanged but decrements `recall_population_count`, recomputes
    `remedied_count` and `completion_rate_pct`, and increments the campaign's
    `version` by 1 alongside the vehicle's own."

    Design: Corner/state_machines/exporting_an_already_remedied_vehicle_cascades_row_out_of_population
    """
    state = fx.campaign_with_approved_claim(
        api,
        requested_qty=1,
        vehicles=TWO_NE_BUILDS,
        campaign={"campaign_number": "26V-209"},
        labor_operation={"labor_op_code": "R209-01"},
        remedy_part={"part_number": "P-88209"},
    )
    assert state["claim"]["final_amount_cents"] == 18980

    vehicle = validate_success(
        api.update_vehicle(
            state["vehicle_id"],
            f.vehicle_update_payload(sale_status="EXPORTED"),
            OPERATIONS_MANAGER,
        ),
        200,
    )
    assert vehicle["sale_status"] == "EXPORTED"

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.REMOVED_FROM_POPULATION
    assert row["approved_claim_count"] == 1

    metrics = get_success_data(
        api.get_completion_metrics(state["campaign_id"], COMPLIANCE_OFFICER_1)
    )
    assert metrics["affected_vehicle_count"] == 2
    assert metrics["recall_population_count"] == 1
    assert metrics["removed_count"] == 1
    assert metrics["remedied_count"] == 0
    assert metrics["regulatory_completion_rate_pct"] == 0.00

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["reimbursement_obligation_cents"] == 18980

    claim = get_success_data(api.get_repair_claim(state["claim_id"], CLAIMS_AUDITOR))
    assert claim["status"] == ClaimStatus.APPROVED
    assert claim["final_amount_cents"] == 18980


def test_denying_an_owner_reimbursement_moves_no_money(api):
    """
    The obligation ledger tracks the decision, not the intake: a denied
    pre-recall invoice pins the payable amount at zero, records the reason, and
    leaves the campaign's ledger where it started.

    PRD §3.9: "A **denial** may be taken from either `SUBMITTED` or
    `DOCUMENTS_REQUESTED`, stores the supplied `denial_reason`, records
    `approved_amount_cents` as 0, moves the request to the terminal `DENIED`
    state, moves no money, and increments the request's `version` by 1."

    PRD §2.10: "Approving an owner reimbursement request adds its
    `approved_amount_cents`; denying one records `approved_amount_cents` as 0 and
    moves no money."

    Design: Corner/state_machines/owner_reimbursement_denial_leaves_obligation_ledger_at_zero
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-210"},
        labor_operation={"labor_op_code": "R210-01"},
        remedy_part={"part_number": "P-88210"},
    )
    fx.add_labor_operation(api, state["campaign_id"], **HISTORICAL_LABOR_OP)

    request = fx.submit_reimbursement(
        api,
        state["campaign_id"],
        state["vehicle_id"],
        invoice_date="2026-07-15",
        invoice_amount=412.75,
        labor_hours_claimed=1.30,
    )
    assert request["status"] == ReimbursementStatus.SUBMITTED

    denial_reason = "Invoice is for an unrelated accessory, not the recalled inflator"
    denied = validate_success(
        api.adjudicate_owner_reimbursement(
            request["id"],
            f.adjudicate_payload(decision="DENY", denial_reason=denial_reason),
            CLAIMS_AUDITOR,
        ),
        200,
    )

    assert denied["status"] == ReimbursementStatus.DENIED
    assert denied["approved_amount_cents"] == 0
    assert denied["denial_reason"] == denial_reason

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["reimbursement_obligation_cents"] == 0


def test_third_unanswered_attempt_moves_the_row_to_unreachable(api):
    """
    Two silent attempts leave the row in play; the third reaches the accumulation
    threshold and retires the owner as unreachable, while the mailing address —
    never returned undeliverable — is still marked valid.

    PRD §3.8: "A row in `UNREPAIRED` becomes `UNREACHABLE` either immediately,
    when the new attempt's `outcome` is `BAD_ADDRESS`, or on accumulation, when
    the row's attempt count reaches three and every one of those attempts ended
    in `NO_RESPONSE`, `BAD_ADDRESS` or `OWNER_REFUSED`"

    PRD §3.9: "Its denominator is the total minus the removed rows — the same
    figure the campaign carries as `recall_population_count` — and **unreachable
    rows stay in it**, because the regulator does not forgive an owner the
    automaker could not find."

    Design: Corner/state_machines/third_unanswered_outreach_attempt_moves_row_to_unreachable
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-211"})
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    for note in ("First attempt, no contact", "Second attempt, no contact"):
        fx.log_outreach(
            api,
            row["id"],
            channel=OutreachChannel.PHONE,
            outcome=OutreachOutcome.NO_RESPONSE,
            note=note,
        )
    still_open = get_success_data(api.get_affected_vehicle(row["id"], OPERATIONS_MANAGER))
    assert still_open["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert still_open["outreach_attempt_count"] == 2

    third = validate_success(
        api.create_outreach_attempt(
            row["id"],
            f.outreach_attempt_payload(
                channel=OutreachChannel.MAIL,
                outcome=OutreachOutcome.NO_RESPONSE,
                note="Third attempt, no contact",
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert_outreach_attempt(third)
    assert third["attempt_number"] == 3

    unreachable = get_success_data(api.get_affected_vehicle(row["id"], OPERATIONS_MANAGER))
    assert unreachable["remedy_status"] == VehicleRemedyStatus.UNREACHABLE
    assert unreachable["outreach_attempt_count"] == 3

    vehicle = get_success_data(api.get_vehicle(state["vehicle_id"], OPERATIONS_MANAGER))
    assert vehicle["owner_address_valid"] is True

    metrics = get_success_data(
        api.get_completion_metrics(state["campaign_id"], COMPLIANCE_OFFICER_1)
    )
    assert metrics["unreachable_count"] == 1
    assert metrics["recall_population_count"] == 1
    assert metrics["regulatory_completion_rate_pct"] == 0.00

    read_list(api.list_outreach_attempts(row["id"], CLAIMS_AUDITOR), expected_total=3)


def test_owner_refusal_cancels_a_booked_appointment(api):
    """
    Against a SCHEDULED row an OWNER_REFUSED outcome is a cancellation, not an
    escalation: the row drops back to UNREPAIRED with the dealer and the date
    cleared, and it does not jump to UNREACHABLE on a single attempt.

    PRD §3.8: "Separately, an `OWNER_REFUSED` outcome logged against a row
    currently in `SCHEDULED` returns that row to `UNREPAIRED` and clears both its
    `dealer_id` and its `scheduled_repair_date`."

    PRD §3.8: "Each attempt records `attempt_number` as one more than the number
    of prior attempts on the same row, and `attempted_at` from the logical clock;
    the row's `outreach_attempt_count` increments accordingly."

    Design: Corner/state_machines/owner_refusal_returns_a_scheduled_row_to_unrepaired_and_clears_the_dealer
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-212"},
        labor_operation={"labor_op_code": "R212-01"},
        remedy_part={"part_number": "P-88212"},
    )
    dealer = fx.create_dealer(api)
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    booked = fx.book_appointment(
        api, row["id"], dealer["id"], scheduled_repair_date="2026-08-20"
    )
    assert booked["remedy_status"] == VehicleRemedyStatus.SCHEDULED

    attempt = validate_success(
        api.create_outreach_attempt(
            row["id"],
            f.outreach_attempt_payload(
                channel=OutreachChannel.PHONE,
                outcome=OutreachOutcome.OWNER_REFUSED,
                note="Owner declined the appointment",
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert attempt["attempt_number"] == 1
    assert attempt["outcome"] == OutreachOutcome.OWNER_REFUSED

    cleared = get_success_data(api.get_affected_vehicle(row["id"], OPERATIONS_MANAGER))
    assert cleared["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert cleared["dealer_id"] is None
    assert cleared["scheduled_repair_date"] is None
    assert cleared["outreach_attempt_count"] == 1

    read_list(
        api.list_affected_vehicles(OPERATIONS_MANAGER, {"dealer_id": dealer["id"]}),
        expected_total=0,
    )


def test_revoking_an_already_revoked_allocation_is_refused(api):
    """
    The first revoke returns the uncommitted unit to the pool; the second is
    refused on the allocation state gate, so the pool is credited once and not
    twice.

    PRD §3.5: "Revoking an allocation, optionally recording a `revoke_note`,
    requires the allocation to be in status `ALLOCATED` — a second revoke of the
    same allocation is rejected with `ERR_ALLOCATION_INVALID_STATE` — moves it to
    `REVOKED` with `revoked_reason` `MANUAL`, adds its `allocated_qty` minus
    `consumed_qty` back to the remedy part's `unallocated_qty`, and increments
    both the allocation's `version` and the remedy part's `version` by 1."

    PRD §2.9: "Granting an allocation moves units out of `unallocated_qty` into
    the allocation's `allocated_qty`; revoking an allocation moves that
    allocation's `allocated_qty` minus `consumed_qty` back into
    `unallocated_qty`."

    Design: Corner/state_machines/revoking_an_already_revoked_allocation_returns_allocation_invalid_state
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-213"},
        labor_operation={"labor_op_code": "R213-01"},
        remedy_part={"part_number": "P-88213"},
    )
    validate_success(
        api.revoke_parts_allocation(
            state["allocation_id"],
            f.revoke_allocation_payload(revoke_note="Returned to the central pool"),
            OPERATIONS_MANAGER,
        ),
        200,
    )

    validate_error(
        api.revoke_parts_allocation(
            state["allocation_id"],
            f.revoke_allocation_payload(revoke_note="Duplicate revoke request"),
            OPERATIONS_MANAGER,
        ),
        ApiErrorId.ALLOCATION_INVALID_STATE,
        409,
    )

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["status"] == AllocationStatus.REVOKED
    assert allocation["revoked_reason"] == RevokedReason.MANUAL
    assert allocation["allocated_qty"] == 1
    assert allocation["consumed_qty"] == 0

    part = fx.read_part(api, state["campaign_id"], "P-88213")
    assert part["unallocated_qty"] == 100
    assert part["consumed_qty"] == 0


def test_resubmitting_a_reimbursement_that_was_never_queried_is_refused(api):
    """
    The re-key is the return leg of the document cycle, so it only runs from
    DOCUMENTS_REQUESTED; against a request still in SUBMITTED it is refused and
    none of the keyed figures change.

    PRD §3.9: "A step attempted from the wrong status — a document request on a
    row not `SUBMITTED`, a re-key on a row not `DOCUMENTS_REQUESTED`, or an
    adjudication on a row that is neither `SUBMITTED` nor `DOCUMENTS_REQUESTED` —
    is rejected with `ERR_REIMBURSEMENT_INVALID_STATE`."

    PRD §3.9: "A request starts in status `SUBMITTED` with `document_round` 0,
    `labor_operation_id`, `approved_amount_cents`, `requested_items` and
    `denial_reason` all unset."

    Design: Corner/state_machines/resubmitting_a_reimbursement_that_is_still_submitted_returns_invalid_state
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-214"},
        labor_operation={"labor_op_code": "R214-01"},
        remedy_part={"part_number": "P-88214"},
    )
    fx.add_labor_operation(
        api,
        state["campaign_id"],
        labor_op_code="R214-00",
        description="Pre-recall inflator replacement performed at owner expense",
        flat_hours=1.30,
        rate_type="PREVAILING",
        effective_from="2025-01-01",
        effective_to="2026-07-31",
    )
    request = fx.submit_reimbursement(
        api,
        state["campaign_id"],
        state["vehicle_id"],
        invoice_date="2026-07-15",
        invoice_amount=412.75,
        labor_hours_claimed=1.30,
    )
    assert request["document_round"] == 0

    validate_error(
        api.resubmit_owner_reimbursement(
            request["id"],
            f.resubmit_payload(invoice_amount=380.00, documentation_complete=True),
            OPERATIONS_MANAGER,
        ),
        ApiErrorId.REIMBURSEMENT_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(api.get_owner_reimbursement(request["id"], CLAIMS_AUDITOR))
    assert unchanged["status"] == ReimbursementStatus.SUBMITTED
    assert unchanged["document_round"] == 0
    assert unchanged["invoice_amount"] == 412.75


def test_opening_a_successor_campaign_cancels_waves_and_revokes_kits(api):
    """
    Creating the successor is what retires the predecessor: the supersession link
    drives the old file to SUPERSEDED, cancels its open wave and revokes its
    holding, both stamped with the CAMPAIGN_SUPERSEDED reason.

    PRD §3.1: "When the target is valid it moves to `SUPERSEDED` immediately, from
    whichever of `DEFECT_DETERMINED`, `FILED`, `INTERIM_NOTIFIED`,
    `OWNER_NOTIFIED` or `MONITORING` it occupied, and its own `version` increments
    by 1."

    PRD §3.1: "That supersession carries two cascades on the old campaign: every
    one of its notification waves in status `PLANNED` or `RELEASE_APPROVED` moves
    to `CANCELLED` with `cancel_reason` recorded as `CAMPAIGN_SUPERSEDED`, and
    every one of its parts allocations in status `ALLOCATED` moves to `REVOKED`
    with `revoked_reason` `CAMPAIGN_SUPERSEDED`, each returning its
    `allocated_qty` minus `consumed_qty` to the owning remedy part's
    `unallocated_qty` and incrementing that remedy part's `version` by 1."

    Design: Corner/state_machines/superseding_campaign_cancels_waves_and_revokes_allocations
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-215"},
        labor_operation={"labor_op_code": "R215-01"},
        remedy_part={"part_number": "P-88215"},
    )
    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-20",
    )
    assert wave["status"] == WaveStatus.PLANNED

    successor = validate_success(
        api.create_campaign(
            f.campaign_payload(
                campaign_number="26V-216",
                defect_type="SAFETY_DEFECT",
                defect_description="Expanded inflator population supersedes 26V-215",
                supersedes_campaign_id=state["campaign_id"],
            ),
            SAFETY_ENGINEER_1,
        ),
        201,
    )
    assert successor["supersedes_campaign_id"] == state["campaign_id"]
    assert successor["campaign_status"] == CampaignStatus.DRAFT

    superseded = fx.read_campaign(api, state["campaign_id"])
    assert superseded["campaign_status"] == CampaignStatus.SUPERSEDED

    waves, _ = read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER),
        expected_total=1,
    )
    assert waves[0]["status"] == WaveStatus.CANCELLED
    assert waves[0]["cancel_reason"] == CancelReason.CAMPAIGN_SUPERSEDED

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["status"] == AllocationStatus.REVOKED
    assert allocation["revoked_reason"] == RevokedReason.CAMPAIGN_SUPERSEDED
    assert allocation["consumed_qty"] == 0

    part = fx.read_part(api, state["campaign_id"], "P-88215")
    assert part["unallocated_qty"] == 100
    assert part["consumed_qty"] == 0

    read_list(
        api.list_campaigns(
            SAFETY_ENGINEER_1, {"supersedes_campaign_id": state["campaign_id"]}
        ),
        expected_total=1,
    )


def test_amendment_retires_the_quarterly_report_it_corrects(api):
    """
    A filing's only transition is driven from outside itself: the amendment for
    2026Q3 enters at SUBMITTED and pushes the earlier quarterly row to AMENDED
    with its amendment flag cleared, so two filings for one period coexist.

    PRD §3.3: "When it is accepted, the prior quarterly filing moves from
    `SUBMITTED` to `AMENDED`, its `amendment_required` flag is cleared to false,
    and its own `version` increments by 1; the amendment itself is created in
    status `SUBMITTED` with freshly computed completion and effectiveness
    snapshots."

    PRD §3.3: "It requires an existing `QUARTERLY` filing for the campaign with
    the same `report_period` and status `SUBMITTED`; without one, the request is
    rejected with `ERR_NO_QUARTERLY_FILING_TO_AMEND`."

    Design: Corner/state_machines/amendment_filing_marks_the_prior_quarterly_filing_amended
    """
    state = _monitoring_campaign_after_one_quarterly(api, "26V-217", "R217-01", "P-88217")
    quarterly_id = state["quarterly_filing"]["id"]

    amendment = validate_success(
        api.create_filing(
            state["campaign_id"],
            f.amendment_filing_payload(
                report_period="2026Q3",
                narrative="Amended 2026Q3 completion report restating the remedied count",
            ),
            COMPLIANCE_OFFICER_1,
        ),
        201,
    )
    assert amendment["filing_type"] == FilingType.AMENDMENT
    assert amendment["report_period"] == "2026Q3"
    assert amendment["status"] == FilingStatus.SUBMITTED

    filings, _ = read_list(
        api.list_filings(
            state["campaign_id"], COMPLIANCE_OFFICER_1, {"report_period": "2026Q3"}
        ),
        expected_total=2,
    )
    quarterly = next(row for row in filings if row["id"] == quarterly_id)
    assert quarterly["status"] == FilingStatus.AMENDED
    assert quarterly["amendment_required"] is False

    assert fx.read_campaign(api, state["campaign_id"])["campaign_status"] == CampaignStatus.MONITORING
