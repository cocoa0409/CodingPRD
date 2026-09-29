"""Lifecycle behaviour of the Cruise Shore Excursions API.

These tests walk the port-call, catalog, vetting, departure, booking, incident,
claim and commission-statement state machines: the edges each state declares,
the refusals a terminal or premature edge produces, and the side effects a
successful transition drives across the other entities.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS


def test_open_sales_promotes_the_scheduled_departure_to_selling(api):
    """PRD §3.1: "Opening sales flips every `SCHEDULED` departure on the call whose excursion is `PUBLISHED` to `SELLING`, freezing each one's `return_guarantee_eligible` as it goes."
    PRD §3.4: "The scheduled band's one job happens at the `SCHEDULED → SELLING` transition, which freezes `return_guarantee_eligible` to true exactly when the excursion's `return_guarantee` is true and `timing_risk_band_scheduled` is not `RED` at that instant."
    PRD §3.3: "Finally, `is_line_operated` declares whether the cruise line itself runs the tour; the read-only `return_guarantee` mirrors it exactly, because the line guarantees a return before all-aboard only for its own excursions."
    PRD §3.5: "`seats_available_total` is `total_capacity` less both sold counts."

    Design: Corner/state_machines/open_sales_on_the_port_call_promotes_the_scheduled_departure_to_selling
    """
    world = fixtures.setup_selling_departure(api, open_sales=False)
    assert world.port_call["status"] == "PLANNED"
    assert world.excursion["catalog_status"] == "PUBLISHED"
    assert world.excursion["is_line_operated"] is False
    assert world.departure["status"] == "SCHEDULED"

    port_call = fixtures.open_port_call_sales(api, world.port_call["id"])

    assert port_call["status"] == "OPEN_FOR_SALE"
    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "SELLING"
    assert departure["return_guarantee_eligible"] is False
    assert departure["total_capacity"] == 40
    assert departure["precruise_sold_seats"] == 0
    assert departure["onboard_sold_seats"] == 0
    assert departure["seats_available_total"] == 40


def test_open_sales_leaves_the_promoted_departure_on_a_green_scheduled_band(api):
    """PRD §3.4: "The ashore leg is then the excursion's `duration_minutes` plus 30 minutes of transfer buffer — 15 minutes at each end — plus the egress leg."
    PRD §3.4: "On the **scheduled basis**, the group is assumed to start at its ticketed `meeting_time_utc`, ignoring both the call's accumulated `delay_minutes` and the assigned wave's landing window entirely."
    PRD §3.4: "`slack_minutes_scheduled` is the number of minutes from `projected_return_scheduled_utc` to the call's `all_aboard_utc`, less the port's `risk_buffer_minutes`; it may be negative."
    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Corner/state_machines/open_sales_on_the_port_call_promotes_the_scheduled_departure_to_selling
    """
    world = fixtures.setup_selling_departure(api, open_sales=False)

    fixtures.open_port_call_sales(api, world.port_call["id"])

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "SELLING"
    assert departure["projected_return_scheduled_utc"].startswith("2026-09-15T14:30:00")
    assert departure["slack_minutes_scheduled"] == 90
    assert departure["timing_risk_band_scheduled"] == "GREEN"


def test_excursion_create_lands_in_draft_with_no_published_timestamp(api):
    """PRD §3.3: "The item is created in `catalog_status` `DRAFT` with `published_at` null."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/excursion_create_lands_in_draft_with_no_published_timestamp
    """
    world = fixtures.setup_port_world(api)
    operator = fixtures.create_approved_operator(api, world.port["id"])

    excursion = fixtures.create_excursion(api, world.port["id"], operator["id"])

    assert excursion["catalog_status"] == "DRAFT"
    assert excursion.get("published_at") is None
    assert excursion["version"] == 1


def test_excursion_create_mirrors_the_guarantee_and_leaves_optional_fields_empty(api):
    """PRD §3.3: "Finally, `is_line_operated` declares whether the cruise line itself runs the tour; the read-only `return_guarantee` mirrors it exactly, because the line guarantees a return before all-aboard only for its own excursions."
    PRD §3.3: "An optional `medical_warning_codes` array, empty by default, draws from `CARDIAC`, `RESPIRATORY`, `PREGNANCY`, `MOTION_SICKNESS` and `ALTITUDE`."
    PRD §3.3: "Eligibility is declared up front: `min_age` between 0 and 21 inclusive, an optional `max_age` that is either absent (meaning no ceiling) or an integer between 0 and 120 inclusive, and a `mobility_level` of `LEVEL_1`, `LEVEL_2`, `LEVEL_3` or `LEVEL_4`."

    Design: Corner/state_machines/excursion_create_lands_in_draft_with_no_published_timestamp
    """
    world = fixtures.setup_port_world(api)
    operator = fixtures.create_approved_operator(api, world.port["id"])

    excursion = fixtures.create_excursion(api, world.port["id"], operator["id"])

    assert excursion["is_line_operated"] is False
    assert excursion["return_guarantee"] is False
    assert excursion["medical_warning_codes"] == []
    assert excursion.get("max_age") is None


def test_arrive_one_minute_before_the_effective_arrival_is_refused(api):
    """PRD §3.1: "A `PortAgent` marks arrival, moving `OPEN_FOR_SALE → IN_PORT`, and may do so only once the logical clock has reached `effective_arrival_utc`; earlier, the request is `ERR_INVALID_PORT_CALL_ACTION`."
    PRD §2.8: "14: the requested port-call transition is declared for the call's current `status` and its clock precondition holds, else `ERR_INVALID_PORT_CALL_ACTION`; the same code refuses a delay recorded against a `CLOSED` or `CANCELLED` call."
    PRD §3.1: "The call is born in `PLANNED` with `delay_minutes` at 0 and `effective_arrival_utc` equal to `arrival_utc`."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/arrive_one_minute_before_the_effective_arrival_is_refused
    """
    world = fixtures.setup_selling_departure(api)
    assert world.port_call["status"] == "OPEN_FOR_SALE"
    assert world.port_call["effective_arrival_utc"].startswith("2026-09-15T08:00:00")
    fixtures.set_clock(api, "2026-09-15T07:59:00Z")

    resp = api.port_call_transition(
        world.port_call["id"], {"action": "ARRIVE"}, TEST_USERS["port_agent_headers"]
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_PORT_CALL_ACTION, 422)
    port_call = validate_success(
            api.get_port_call(world.port_call["id"], TEST_USERS["port_agent_headers"])
        )
    
    assert port_call["status"] == "OPEN_FOR_SALE"
    assert port_call["delay_minutes"] == 0
    assert port_call["version"] == 2


def test_publishing_straight_from_draft_is_refused(api):
    """PRD §3.3: "Publication from review moves `PENDING_REVIEW → PUBLISHED` and demands three checks."
    PRD §2.8: "15: the requested catalog action is declared for the excursion's `catalog_status`, and an amendment targets only an excursion in `DRAFT` or `PENDING_REVIEW`, else `ERR_INVALID_CATALOG_ACTION`."
    PRD §3.3: "The item is created in `catalog_status` `DRAFT` with `published_at` null."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/publishing_straight_from_draft_is_refused
    """
    world = fixtures.setup_port_world(api)
    operator = fixtures.create_approved_operator(api, world.port["id"])
    excursion = fixtures.create_excursion(api, world.port["id"], operator["id"])
    assert excursion["catalog_status"] == "DRAFT"

    resp = api.catalog_action(
        excursion["id"], {"action": "PUBLISH"}, TEST_USERS["manager_headers"]
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_CATALOG_ACTION, 422)
    stored = validate_success(
            api.get_excursion(excursion["id"], TEST_USERS["manager_headers"])
        )
    
    assert stored["catalog_status"] == "DRAFT"
    assert stored.get("published_at") is None
    assert stored["version"] == 1


def test_approving_an_already_approved_operator_is_refused_rather_than_ignored(api):
    """PRD §3.2: "Approval moves `SUBMITTED → APPROVED` and is the most heavily guarded edge in the system."
    PRD §2.8: "16: the requested vetting action is declared for the operator's `vetting_status`, else `ERR_INVALID_VETTING_ACTION` — `TERMINATED` is terminal, so every action on a terminated operator fails here."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/approving_an_already_approved_operator_is_refused_rather_than_ignored
    """
    world = fixtures.setup_port_world(api)
    operator = fixtures.create_approved_operator(api, world.port["id"])
    assert operator["vetting_status"] == "APPROVED"
    version_before = operator["version"]

    resp = api.vetting_action(
        operator["id"], {"action": "APPROVE"}, TEST_USERS["vetting_officer_headers"]
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_VETTING_ACTION, 422)
    stored = fixtures.get_operator(api, operator["id"])
    assert stored["vetting_status"] == "APPROVED"
    assert stored["version"] == version_before


def test_cancelling_an_already_cancelled_booking_is_refused(api):
    """PRD §3.7: "A booking still in `BOOKED` moves `BOOKED → CANCELLED_BY_GUEST` with `financial_status` `AUTHORIZED → VOIDED`, an `AUTH_VOID` entry of `amount_cents` 0 and `refund_pct_bps` 0 on the `GUEST_INITIATED` `basis`, `retained_cents` left at 0, and its seats returned to its channel bucket."
    PRD §2.8: "19: the requested fulfillment action is declared for the booking's current pair of `fulfillment_status` and `financial_status`, else `ERR_INVALID_BOOKING_ACTION`; both dimensions are consulted, so ticketing requires `financial_status` of `AUTHORIZED`, a guest cancellation requires `fulfillment_status` of `BOOKED` or `TICKETED`, check-in requires the owning port call to be `IN_PORT`, and an incident may only be filed against a booking whose `fulfillment_status` is `CHECKED_IN`, `COMPLETED` or `NO_SHOW`."
    PRD §3.5: "`precruise_sold_seats` counts the seats consumed by bookings on this departure whose `channel` is `PRE_CRUISE` and whose `fulfillment_status` is neither `CANCELLED_BY_GUEST` nor `CANCELLED_BY_LINE`; `onboard_sold_seats` counts the same for `ONBOARD`."

    Design: Corner/state_machines/cancelling_an_already_cancelled_booking_is_refused
    """
    world = fixtures.setup_booked_booking(api)
    cancelled = fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGE_OF_PLAN"
    )
    assert cancelled["fulfillment_status"] == "CANCELLED_BY_GUEST"
    assert cancelled["financial_status"] == "VOIDED"

    resp = api.cancel_booking(
        world.booking["id"],
        {"reason_code": "GUEST_CHANGE_OF_PLAN"},
        TEST_USERS["desk_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_ACTION, 422)
    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CANCELLED_BY_GUEST"
    assert booking["financial_status"] == "VOIDED"
    assert booking["retained_cents"] == 0
    entries = fixtures.ledger_entries_for_booking(api, world.booking["id"])
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "AUTH_VOID"
    assert entries[0]["amount_cents"] == 0
    assert entries[0]["refund_pct_bps"] == 0
    assert entries[0]["basis"] == "GUEST_INITIATED"
    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 0


def test_settling_a_statement_that_was_never_issued_is_refused(api):
    """PRD §2.8: "21: the requested statement transition is declared for the statement's `status`, and settlement requires a `FINAL` `basis`, else `ERR_INVALID_STATEMENT_ACTION`; a `PROVISIONAL` statement can be issued, disputed and adjusted but never settled."
    PRD §3.9: "Settlement is reachable from both `ISSUED` and `ADJUSTED`, identically in both cases, and requires the statement's `basis` to be `FINAL`, else `ERR_INVALID_STATEMENT_ACTION` — a provisional statement may be issued, disputed and adjusted but never settled."
    PRD §3.9: "The new statement is created in `DRAFT` with `issued_at` and `settled_at` both absent, and all nine waterfall steps computed onto it."

    Design: Corner/state_machines/settling_a_statement_that_was_never_issued_is_refused
    """
    world = fixtures.setup_selling_departure(api)
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL"
    )
    assert statement["status"] == "DRAFT"

    resp = api.statement_transition(
        statement["id"], {"action": "SETTLE"}, TEST_USERS["finance_headers"]
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_STATEMENT_ACTION, 422)
    stored = validate_success(
            api.get_commission_statement(
                statement["id"], TEST_USERS["finance_headers"]
            )
        )
    
    assert stored["status"] == "DRAFT"
    assert stored.get("issued_at") is None
    assert stored.get("settled_at") is None


def test_closing_the_all_aboard_deadline_retains_the_ticketed_party_as_a_no_show(api):
    """PRD §3.1: "The same agent closes the call at the all-aboard deadline, moving `IN_PORT → CLOSED`, permitted only once the logical clock has reached `all_aboard_utc`."
    PRD §3.1: "Closure is the busiest cascade of the day: every departure still `SELLING` moves `SELLING → CLOSED`; every booking still in `TICKETED` moves `TICKETED → NO_SHOW` with `financial_status` moving `CHARGED → RETAINED` and a `RETENTION` ledger entry whose `amount_cents` equals the booking's `charge_total_cents` on the `NO_SHOW` `basis`; and every booking whose `alternative_offer_status` is `OFFERED` flips to `EXPIRED`, because an unaccepted rebooking offer has no meaning once the ship has sailed."
    PRD §3.7: "On the booking side, `refunded_cents` is the running sum of `REFUND` entries, `goodwill_credit_cents` is the running sum of `GOODWILL_CREDIT` and `REPATRIATION_ALLOWANCE` entries together, and `retained_cents` is `charge_total_cents` less `refunded_cents` once `financial_status` is terminal and 0 while it is still `AUTHORIZED`."

    Design: Corner/state_machines/closing_the_all_aboard_deadline_turns_ticketed_bookings_into_retained_no_shows
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.booking["fulfillment_status"] == "TICKETED"
    assert world.booking["financial_status"] == "CHARGED"
    assert world.booking["charge_total_cents"] == 27007
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T16:30:00Z")

    port_call = fixtures.port_call_transition(
        api, world.port_call["id"], "CLOSE_ALL_ABOARD"
    )

    assert port_call["status"] == "CLOSED"
    assert fixtures.get_departure(api, world.departure["id"])["status"] == "CLOSED"
    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "NO_SHOW"
    assert booking["financial_status"] == "RETAINED"
    assert booking["refunded_cents"] == 0
    assert booking["retained_cents"] == 27007
    entries = fixtures.ledger_entries_for_booking(api, world.booking["id"])
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "RETENTION"
    assert entries[0]["amount_cents"] == 27007
    assert entries[0]["refund_pct_bps"] == 0
    assert entries[0]["basis"] == "NO_SHOW"


def test_closing_the_all_aboard_deadline_re_rates_commission_to_the_no_show_floor(api):
    """PRD §3.9: "**On the final basis**, the lines in scope are instead the bookings whose `fulfillment_status` is `COMPLETED` or `NO_SHOW`, and each line's basis is `quoted_total_cents` less `refunded_cents`, floored at zero; a `COMPLETED` line is rated at the operator's `commission_rate_bps` while a `NO_SHOW` line is rated at the smaller of `commission_rate_bps` and 500 basis points, since the line performed no service."
    PRD §3.9: "The provisional figure is what lands in a booking's `commission_accrued_cents` at ticketing; the final figure replaces it when the departure completes or the booking becomes a no-show; a refund or retention event re-accrues it in between; and a line cancellation zeroes it."
    PRD §3.5: "A no-show returns nothing at all: that seat was consumed."
    PRD §3.5: "`seats_available_total` is `total_capacity` less both sold counts."

    Design: Corner/state_machines/closing_the_all_aboard_deadline_turns_ticketed_bookings_into_retained_no_shows
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.booking["quoted_total_cents"] == 26220
    assert world.booking["commission_accrued_cents"] == 4720
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T16:30:00Z")

    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "NO_SHOW"
    assert booking["commission_accrued_cents"] == 1311
    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 2
    assert departure["onboard_sold_seats"] == 0
    assert departure["seats_available_total"] == 38


def test_closing_an_incident_that_already_carries_a_claim_is_refused(api):
    """PRD §3.8: "From `FILED` the `RiskOfficer` either closes it without a claim, moving `FILED → CLOSED_NO_CLAIM` and optionally recording a `resolution_note`, or opens a claim, moving `FILED → CLAIM_OPENED`."
    PRD §3.8: "A claim may only be opened when no claim already exists for the incident, and an incident that already carries a claim may not be closed; both breaches are `ERR_INVALID_CLAIM_ACTION`."
    PRD §3.8: "The claim is created in `status` `SUBMITTED` with `submitted_by_user_id` from the header, `dispute_round_count` 0, and `liability_share_bps`, `settlement_amount_cents`, `operator_charge_cents` and `adjudicated_by_user_id` all at their zero or absent defaults."

    Design: Corner/state_machines/closing_an_incident_that_already_carries_a_claim_is_refused
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    assert incident["status"] == "FILED"
    claim = fixtures.open_claim(
        api, incident["id"], claimed_amount_cents=5000000
    )
    assert claim["status"] == "SUBMITTED"

    resp = api.close_incident(
        incident["id"],
        {"resolution_note": "Desk believes no claim is warranted."},
        TEST_USERS["risk_officer_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_ACTION, 422)
    stored_incident = validate_success(
            api.get_incident(incident["id"], TEST_USERS["risk_officer_headers"])
        )
    
    assert stored_incident["status"] == "CLAIM_OPENED"
    stored_claim = validate_success(
            api.get_claim(claim["id"], TEST_USERS["risk_officer_headers"])
        )
    
    assert stored_claim["status"] == "SUBMITTED"
    assert stored_claim["dispute_round_count"] == 0


def test_upholding_a_claim_charges_the_operator_and_grows_the_reserve(api):
    """PRD §3.8: "The `operator_charge_cents` actually charged to the operator is `settlement_amount_cents` multiplied by `liability_share_bps`, divided by ten thousand, rounded half up, and it may not exceed the operator's `insurance_liability_limit_cents` — the limit itself is acceptable — else `ERR_CLAIM_EXCEEDS_INSURANCE_LIMIT`."
    PRD §3.8: "And the adjudicating `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the adjudicator's identifier is stored as `adjudicated_by_user_id`."
    PRD §3.8: "Upholding then moves four things."
    PRD §3.8: "The claim reaches `ADJUDICATED_UPHELD` and records `operator_charge_cents`."
    PRD §3.8: "The operator's `liability_reserve_cents` grows by that amount."

    Design: Corner/state_machines/upholding_a_claim_charges_the_operator_penalises_the_score_and_closes_the_incident
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=5000000)
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR",
        headers=TEST_USERS["risk_officer_headers"],
    )
    assert fixtures.get_operator(api, world.operator["id"])[
        "liability_reserve_cents"
    ] == 0

    adjudicated = fixtures.adjudicate_upheld(api, claim["id"], 4000, 4000000)

    assert adjudicated["status"] == "ADJUDICATED_UPHELD"
    assert adjudicated["liability_share_bps"] == 4000
    assert adjudicated["settlement_amount_cents"] == 4000000
    assert adjudicated["operator_charge_cents"] == 1600000
    assert adjudicated["submitted_by_user_id"] == "u_risk_1"
    assert adjudicated["adjudicated_by_user_id"] == "u_risk_2"
    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["liability_reserve_cents"] == 1600000


def test_upholding_a_claim_penalises_the_score_and_closes_the_incident(api):
    """PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."
    PRD §3.2: "The weighted average is the sum of each audit's `raw_score` multiplied by its renormalised weight."
    PRD §3.2: "From that average subtract 8 points for every critical finding, counting `critical_finding_count` summed across the audits in the window only, and subtract a further 5 points for every liability claim against this operator whose `status` is `ADJUDICATED_UPHELD` or `SETTLED`."
    PRD §3.8: "The operator's `safety_score` is recomputed, now carrying a 5-point penalty for this newly adverse claim, and if the recomputed score falls below 60 the operator moves `APPROVED → SUSPENDED`, dragging the whole four-hop suspension cascade of §3.2 with it — an adjudication can therefore cancel live departures and refund guests, even though the `RiskOfficer` has no power to cancel a departure directly."
    PRD §3.8: "And the underlying incident moves `CLAIM_OPENED → CLOSED_UPHELD`."

    Design: Corner/state_machines/upholding_a_claim_charges_the_operator_penalises_the_score_and_closes_the_incident
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.operator["safety_score"] == 82
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=5000000)
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR",
        headers=TEST_USERS["risk_officer_headers"],
    )

    fixtures.adjudicate_upheld(api, claim["id"], 4000, 4000000)

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["safety_score"] == 77
    assert operator["vetting_status"] == "APPROVED"
    stored_incident = validate_success(
            api.get_incident(incident["id"], TEST_USERS["risk_officer_headers"])
        )
    
    assert stored_incident["status"] == "CLOSED_UPHELD"


def test_issuing_the_final_statement_freezes_the_waterfall_on_the_delivered_line(api):
    """PRD §3.9: "Step one aggregates gross: with a `PROVISIONAL` `basis`, the lines in scope are the in-scope bookings whose `financial_status` is `CHARGED` or `PARTIALLY_REFUNDED` and `gross_ticket_cents` is the exact sum of their `quoted_total_cents`; with a `FINAL` `basis`, the lines are the in-scope bookings whose `fulfillment_status` is `COMPLETED` or `NO_SHOW` and `gross_ticket_cents` is the exact sum of each one's `quoted_total_cents` less its `refunded_cents`, each term floored at zero."
    PRD §3.9: "`booking_line_count` is the number of lines that entered the gross, and `refunds_cents` is the sum of `amount_cents` over those lines' `REFUND` ledger entries."
    PRD §3.9: "Step two charges the port infrastructure fee on gross, before any commission is deducted: `port_fee_cents` is 250 basis points of `gross_ticket_cents` rounded half up."
    PRD §3.9: "Step three sets `line_commission_cents` to the commission accrual for this statement's own `basis`, computed per booking line and summed as described above."
    PRD §3.9: "**On the final basis**, the lines in scope are instead the bookings whose `fulfillment_status` is `COMPLETED` or `NO_SHOW`, and each line's basis is `quoted_total_cents` less `refunded_cents`, floored at zero; a `COMPLETED` line is rated at the operator's `commission_rate_bps` while a `NO_SHOW` line is rated at the smaller of `commission_rate_bps` and 500 basis points, since the line performed no service."
    PRD §3.9: "Step four sets `claim_offset_cents` to the exact sum of `operator_charge_cents` over the liability claims for the same operator and port call whose `status` is `ADJUDICATED_UPHELD` or `SETTLED`."
    PRD §3.9: "Step six computes `payable_pre_rebate_cents` as `gross_ticket_cents` less `port_fee_cents`, less `line_commission_cents`, less `claim_offset_cents`, less `operational_penalty_cents`, floored at zero — all exact integer arithmetic."

    Design: Corner/state_machines/settling_the_final_statement_settles_the_upheld_claim_and_releases_the_reserve
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=5000000)
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR",
        headers=TEST_USERS["risk_officer_headers"],
    )
    fixtures.adjudicate_upheld(api, claim["id"], 4000, 4000000)
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:30:00Z")
    fixtures.complete_departure(
        api, world.departure["id"], "2026-09-15T14:30:00Z"
    )
    fixtures.set_clock(api, "2026-09-15T16:30:00Z")
    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL"
    )

    issued = fixtures.statement_transition(api, statement["id"], "ISSUE")

    assert issued["status"] == "ISSUED"
    assert issued["basis"] == "FINAL"
    assert issued["booking_line_count"] == 1
    assert issued["gross_ticket_cents"] == 26220
    assert issued["refunds_cents"] == 0
    assert issued["port_fee_cents"] == 656
    assert issued["line_commission_cents"] == 4720
    assert issued["claim_offset_cents"] == 1600000
    assert issued["operational_penalty_cents"] == 0
    assert issued["payable_pre_rebate_cents"] == 0


def test_settling_the_final_statement_settles_the_upheld_claim_and_releases_the_reserve(api):
    """PRD §3.9: "Settlement is reachable from both `ISSUED` and `ADJUSTED`, identically in both cases, and requires the statement's `basis` to be `FINAL`, else `ERR_INVALID_STATEMENT_ACTION` — a provisional statement may be issued, disputed and adjusted but never settled."
    PRD §3.9: "Settling stamps `settled_at` with the logical-clock instant, then closes out liability: every claim for the same operator and port call whose `status` is `ADJUDICATED_UPHELD` moves to `SETTLED`, and each such move debits the operator's `liability_reserve_cents` by that claim's `operator_charge_cents`."
    PRD §3.6: "It is recorded on the departure, and every booking in `CHECKED_IN` moves `CHECKED_IN → COMPLETED`."
    PRD §3.6: "A departure that returns on time leaves `return_guarantee_honored` true on every booking, and so does a late return on an excursion that never carried the guarantee — the flag reflects breach of promise, not lateness as such."

    Design: Corner/state_machines/settling_the_final_statement_settles_the_upheld_claim_and_releases_the_reserve
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])
    incident = fixtures.file_incident(
        api, world.booking["id"], occurred_utc="2026-09-15T08:25:00Z"
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=5000000)
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR",
        headers=TEST_USERS["risk_officer_headers"],
    )
    fixtures.adjudicate_upheld(api, claim["id"], 4000, 4000000)
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:30:00Z")
    fixtures.complete_departure(api, world.departure["id"], "2026-09-15T14:30:00Z")
    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "COMPLETED"
    assert booking["return_guarantee_honored"] is True
    fixtures.set_clock(api, "2026-09-15T16:30:00Z")
    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL"
    )
    fixtures.statement_transition(api, statement["id"], "ISSUE")

    settled = fixtures.statement_transition(api, statement["id"], "SETTLE")

    assert settled["status"] == "SETTLED"
    assert settled["settled_at"].startswith("2026-09-15T16:30:00")
    stored_claim = validate_success(
            api.get_claim(claim["id"], TEST_USERS["risk_officer_headers"])
        )
    
    assert stored_claim["status"] == "SETTLED"
    assert stored_claim["operator_charge_cents"] == 1600000
    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["liability_reserve_cents"] == 0


def test_a_weather_cancellation_tops_up_a_partially_refunded_booking_to_whole(api):
    """PRD §3.7: "Below that but at 1440 minutes or more, the refund is 7500 basis points of `quoted_total_cents`."
    PRD §3.7: "A booking that had already been cancelled by the guest keeps its `fulfillment_status` of `CANCELLED_BY_GUEST` untouched, but if its `financial_status` was `PARTIALLY_REFUNDED` the retained remainder is refunded too, moving `PARTIALLY_REFUNDED → REFUNDED` with a `REFUND` entry for `charge_total_cents` less `refunded_cents`; a booking already `RETAINED`, `REFUNDED` or `VOIDED` is left entirely alone."
    PRD §3.7: "On the booking side, `refunded_cents` is the running sum of `REFUND` entries, `goodwill_credit_cents` is the running sum of `GOODWILL_CREDIT` and `REPATRIATION_ALLOWANCE` entries together, and `retained_cents` is `charge_total_cents` less `refunded_cents` once `financial_status` is terminal and 0 while it is still `AUTHORIZED`."

    Design: Corner/state_machines/a_weather_cancellation_tops_up_a_partially_refunded_booking_to_whole
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.booking["quoted_total_cents"] == 26220
    assert world.booking["charge_total_cents"] == 27007
    fixtures.set_clock(api, "2026-09-14T09:00:00Z")
    guest_cancelled = fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGE_OF_PLAN"
    )
    assert guest_cancelled["fulfillment_status"] == "CANCELLED_BY_GUEST"
    assert guest_cancelled["financial_status"] == "PARTIALLY_REFUNDED"
    assert guest_cancelled["refunded_cents"] == 19665
    assert guest_cancelled["retained_cents"] == 7342

    fixtures.cancel_departure(api, world.departure["id"], "WEATHER")

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "CANCELLED_BY_GUEST"
    assert booking["financial_status"] == "REFUNDED"
    assert booking["refunded_cents"] == 27007
    assert booking["retained_cents"] == 0
    refunds = [
        entry
        for entry in fixtures.ledger_entries_for_booking(api, world.booking["id"])
        if entry["entry_kind"] == "REFUND"
    ]
    assert [entry["amount_cents"] for entry in refunds] == [19665, 7342]


def test_a_weather_cancellation_pays_no_goodwill_and_records_no_reliability_strike(api):
    """PRD §3.7: "The departure's `status` becomes `CANCELLED_WEATHER` or `CANCELLED_OPERATIONAL` accordingly and `cancellation_cause` records `WEATHER` or `OPERATIONAL`."
    PRD §3.7: "In both branches seats return to each booking's own channel bucket and `seats_available_total` is recomputed, the assigned tender wave's `assigned_guest_count` is reduced by the departure's `total_capacity` where a wave was assigned, every booking line's `commission_accrued_cents` is set to 0, and any draft commission statement in scope is recomputed."
    PRD §3.7: "The `WEATHER` branch stops there: no goodwill credit, no reliability strike for the operator, no settlement penalty."
    PRD §3.7: "On the booking side, `refunded_cents` is the running sum of `REFUND` entries, `goodwill_credit_cents` is the running sum of `GOODWILL_CREDIT` and `REPATRIATION_ALLOWANCE` entries together, and `retained_cents` is `charge_total_cents` less `refunded_cents` once `financial_status` is terminal and 0 while it is still `AUTHORIZED`."

    Design: Corner/state_machines/a_weather_cancellation_tops_up_a_partially_refunded_booking_to_whole
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-14T09:00:00Z")
    fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGE_OF_PLAN"
    )

    cancelled = fixtures.cancel_departure(api, world.departure["id"], "WEATHER")

    assert cancelled["status"] == "CANCELLED_WEATHER"
    assert cancelled["cancellation_cause"] == "WEATHER"
    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["goodwill_credit_cents"] == 0
    assert booking["commission_accrued_cents"] == 0
    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["reliability_strikes"] == 0
    assert operator["vetting_status"] == "APPROVED"


def test_the_return_guarantee_is_frozen_true_only_for_a_line_operated_departure(api):
    """PRD §3.3: "Finally, `is_line_operated` declares whether the cruise line itself runs the tour; the read-only `return_guarantee` mirrors it exactly, because the line guarantees a return before all-aboard only for its own excursions."
    PRD §3.4: "The scheduled band's one job happens at the `SCHEDULED → SELLING` transition, which freezes `return_guarantee_eligible` to true exactly when the excursion's `return_guarantee` is true and `timing_risk_band_scheduled` is not `RED` at that instant."
    PRD §3.4: "`slack_minutes_scheduled` is the number of minutes from `projected_return_scheduled_utc` to the call's `all_aboard_utc`, less the port's `risk_buffer_minutes`; it may be negative."
    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Corner/state_machines/the_return_guarantee_is_frozen_true_only_for_a_line_operated_departure
    """
    world = fixtures.setup_selling_departure(
        api,
        open_sales=False,
        excursion={"title": "Line Beach Club", "is_line_operated": True},
    )
    assert world.excursion["is_line_operated"] is True
    assert world.excursion["return_guarantee"] is True
    assert world.departure["status"] == "SCHEDULED"

    fixtures.open_port_call_sales(api, world.port_call["id"])

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "SELLING"
    assert departure["return_guarantee_eligible"] is True
    assert departure["slack_minutes_scheduled"] == 90
    assert departure["timing_risk_band_scheduled"] == "GREEN"
