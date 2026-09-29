"""Endpoint workflow behaviours for the corporate fitness centre API.

Each test walks a real operator workflow end to end against an empty database:
the site-wide readiness posture read, the equipment-downtime credit that a
repair accrues into the month's invoice, the amendment that mints a successor
contract, and the agreement between every collection read and its matching
detail read.
"""
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, api_client, factories
from test_helpers import fixtures as scenarios
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["operator_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


# ==========================================================================
# Local composite setups (no shared helper covers these exact chains)
# ==========================================================================
def _setup_repaired_defibrillator_after_a_completed_session() -> dict:
    """ACTIVE programme, one 55-minute session on 2026-08-05 carrying 4517 cents
    of direct supply cost, led by a CONFIRMED instructor at 4700 cents an hour,
    started and completed at 12:00Z; the defibrillator then goes out of service
    at that same instant and is repaired six days later at 2026-08-11T12:00Z.
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={
            "participation_target": 8,
            "max_participants_per_session": 6,
            "eligible_member_classes": ["EMPLOYEE"],
        }
    )
    scenario, session, lead_assignment = scenarios.setup_in_progress_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=4517,
    )
    scenarios.complete_session(scenario, session["id"])
    scenario["repaired_asset"] = scenarios.setup_asset_downtime(
        scenario,
        scenario["aed_id"],
        out_on="2026-08-05T12:00:00Z",
        back_on="2026-08-11T12:00:00Z",
    )
    scenario["session"] = scenarios.read_session(session["id"])
    scenario["lead_assignment"] = scenarios.read_assignment(lead_assignment["id"])
    return scenario


def _management_fee_amendment_payload() -> dict:
    """A successor's terms: the commercial model switches to MANAGEMENT_FEE, so
    the payload carries management_fee_cents and no annual ceiling at all."""
    payload = factories.amendment_payload(
        fee_structure="MANAGEMENT_FEE",
        staffing_model="HYBRID",
        budgeted_staff_fte=4.0,
        participation_target_pct=45,
        term_start_on="2027-07-01",
        term_end_on="2028-06-30",
        management_fee_cents=40000,
    )
    payload.pop("not_to_exceed_cents", None)
    return payload


def _setup_populated_site() -> dict:
    """One ACTIVE programme with every aggregate populated exactly once: an OPEN
    room, a READY defibrillator, a site manager and an instructor both on active
    duty with VERIFIED credentials, an ELIGIBLE employee holding a SIGNED waiver
    and an ACTIVE badge, one STAFFED session with a CONFIRMED LEAD assignment,
    one MINOR slip-and-fall incident, and the 2026-08 invoice in DRAFT.

    Nobody has checked in, so the participation collection is legitimately empty.
    """
    scenario = scenarios.setup_active_program(
        offering_overrides={
            "participation_target": 8,
            "max_participants_per_session": 6,
            "eligible_member_classes": ["EMPLOYEE"],
        }
    )
    member = scenarios.setup_ready_member(
        scenario,
        member_class="EMPLOYEE",
        full_name="Iris Okafor",
        employee_number="E-1001",
    )
    scenario["member"] = member
    scenario["member_id"] = member["id"]
    scenario["waiver_id"] = member["_waiver"]["id"]

    scenario, session, lead_assignment = scenarios.setup_staffed_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    scenario["session"] = session
    scenario["session_id"] = session["id"]
    scenario["lead_assignment"] = lead_assignment
    scenario["assignment_id"] = lead_assignment["id"]

    incident = scenarios.file_incident(
        scenario,
        occurred_at_utc="2026-07-31T16:05:00Z",
        severity="MINOR",
        cause_category="SLIP_FALL",
        narrative="Member slipped near the fountain; no injury.",
    )
    scenario["incident_id"] = incident["id"]

    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    scenario["invoice_id"] = invoice["id"]
    return scenario


# ==========================================================================
# The site-wide readiness posture read
# ==========================================================================
def test_readiness_summary_reports_zero_problem_counters_on_a_clean_site(api):
    """PRD §3.9: "It reports the `contract_id`, then `aed_ready_count` and
    `aed_not_ready_count` across the site's defibrillators,
    `credentials_expiring_soon` and `credentials_expired`,
    `staff_suspended_count`, `sessions_at_risk`, `rooms_restricted`, and
    `assets_out_of_service`."

    PRD §3.9: "It is available to the operator, to the site manager, and to the
    compliance auditor, and it never mutates a record."

    Design: Corner/endpoints/readiness_summary_reports_site_wide_counts
    """
    scenario = scenarios.setup_active_program()
    contract_id = scenario["contract_id"]
    version_before = scenarios.contract_version(contract_id)

    summary = validate_success(
        api.get_readiness_summary(
            scenario["manager_headers"], params={"contract_id": contract_id}
        )
    )

    assert summary["contract_id"] == contract_id, (
        f"the summary must name the contract it ran against, got "
        f"{summary['contract_id']!r} instead of {contract_id!r}"
    )
    assert summary["aed_ready_count"] == 1, (
        f"expected 1 READY defibrillator on a freshly registered site, got "
        f"{summary['aed_ready_count']}"
    )
    for counter in (
        "aed_not_ready_count",
        "credentials_expiring_soon",
        "credentials_expired",
        "staff_suspended_count",
        "sessions_at_risk",
        "rooms_restricted",
        "assets_out_of_service",
    ):
        assert summary[counter] == 0, (
            f"expected {counter} to be 0 on a site with no problems, got "
            f"{summary[counter]}"
        )

    assert scenarios.contract_version(contract_id) == version_before, (
        f"the readiness summary must mutate no record, but the contract's "
        f"version moved from {version_before} to "
        f"{scenarios.contract_version(contract_id)}"
    )


def test_readiness_summary_flips_when_the_defibrillator_is_taken_out_of_service(api):
    """PRD §3.3: "A `TAKE_OUT_OF_SERVICE` on an asset in either `IN_SERVICE` or
    `MAINTENANCE_DUE` moves it to `OUT_OF_SERVICE` and stamps
    `out_of_service_since` with the current instant; when the asset is a
    defibrillator its `readiness_status` becomes `NOT_READY`, which is what
    silently blocks session starts across the whole site until it is repaired."

    PRD §3.9: "It reports the `contract_id`, then `aed_ready_count` and
    `aed_not_ready_count` across the site's defibrillators,
    `credentials_expiring_soon` and `credentials_expired`,
    `staff_suspended_count`, `sessions_at_risk`, `rooms_restricted`, and
    `assets_out_of_service`."

    Design: Corner/endpoints/readiness_summary_reports_site_wide_counts
    """
    scenario = scenarios.setup_active_program()
    contract_id = scenario["contract_id"]

    before = validate_success(
        api.get_readiness_summary(
            scenario["manager_headers"], params={"contract_id": contract_id}
        )
    )
    assert (before["aed_ready_count"], before["aed_not_ready_count"]) == (1, 0), (
        f"expected one READY and no NOT_READY defibrillator before the service "
        f"event, got {before['aed_ready_count']} and {before['aed_not_ready_count']}"
    )

    validate_success(
        api.create_service_event(
            scenario["aed_id"],
            {
                "event_type": "TAKE_OUT_OF_SERVICE",
                "note": "Vendor recall on the pad harness",
            },
            scenario["manager_headers"],
        ),
        # PRD §4: a service event brings no new record into existence -- it moves
        # the asset through its lifecycle, so the endpoint answers with 200.
        200,
    )

    asset = scenarios.read_asset(scenario["aed_id"])
    assert asset["status"] == "OUT_OF_SERVICE", (
        f"TAKE_OUT_OF_SERVICE must move the asset to OUT_OF_SERVICE, got "
        f"{asset['status']!r}"
    )
    assert asset["readiness_status"] == "NOT_READY", (
        f"a defibrillator that is not IN_SERVICE must read NOT_READY, got "
        f"{asset['readiness_status']!r}"
    )
    assert asset["out_of_service_since"] is not None, (
        "out_of_service_since must be stamped with the current instant, got null"
    )
    assert asset["out_of_service_since"].startswith("2026-08-01T00:00:00"), (
        f"out_of_service_since must be stamped at the logical clock instant "
        f"2026-08-01T00:00:00Z, got {asset['out_of_service_since']!r}"
    )

    after = validate_success(
        api.get_readiness_summary(
            scenario["manager_headers"], params={"contract_id": contract_id}
        )
    )
    assert after["aed_ready_count"] == 0, (
        f"expected aed_ready_count 0 once the only defibrillator is out of "
        f"service, got {after['aed_ready_count']}"
    )
    assert after["aed_not_ready_count"] == 1, (
        f"expected aed_not_ready_count 1 once the only defibrillator is out of "
        f"service, got {after['aed_not_ready_count']}"
    )
    assert after["assets_out_of_service"] == 1, (
        f"expected assets_out_of_service 1 after the service event, got "
        f"{after['assets_out_of_service']}"
    )
    assert after["rooms_restricted"] == 0, (
        f"a service event restricts no room, so rooms_restricted must stay 0, "
        f"got {after['rooms_restricted']}"
    )


# ==========================================================================
# Repair accrues downtime days, and those days become money on the invoice
# ==========================================================================
def test_repair_complete_accrues_six_downtime_days_onto_the_defibrillator(api):
    """PRD §3.3: "A `REPAIR_COMPLETE` on an asset in `OUT_OF_SERVICE` returns it
    to `IN_SERVICE`, sets `last_service_on` to today, clears
    `out_of_service_since` back to null, recomputes `readiness_status` for
    defibrillators, and — importantly — accrues the outage: the number of days
    from the date the asset went out of service to today, rounded up to a whole
    day, is **added** to `out_of_service_days_current_period`."

    PRD §3.3: "The inspection-age boundary is inclusive on the ready side: a
    unit last inspected exactly 30 days ago is still eligible for `READY`, and
    one day older is `NOT_READY`."

    Design: Corner/endpoints/repair_complete_accrues_downtime_days_into_the_invoice
    """
    scenario = _setup_repaired_defibrillator_after_a_completed_session()
    asset = scenarios.read_asset(scenario["aed_id"])

    assert asset["status"] == "IN_SERVICE", (
        f"REPAIR_COMPLETE must return the asset to IN_SERVICE, got "
        f"{asset['status']!r}"
    )
    assert asset["out_of_service_since"] is None, (
        f"REPAIR_COMPLETE must clear out_of_service_since back to null, got "
        f"{asset['out_of_service_since']!r}"
    )
    assert asset["out_of_service_days_current_period"] == 6, (
        f"an outage from 2026-08-05T12:00Z to 2026-08-11T12:00Z accrues 6 whole "
        f"days, got {asset['out_of_service_days_current_period']}"
    )
    assert asset["readiness_status"] == "READY", (
        f"the repaired defibrillator was last inspected on 2026-07-20, 22 days "
        f"before 2026-08-11, so it is READY again; got "
        f"{asset['readiness_status']!r}"
    )


def test_accrued_downtime_credits_the_cost_plus_invoice_after_the_markup(api):
    """PRD §3.3: "For each asset of the contract, subtract a grace allowance of
    3 days from that asset's `out_of_service_days_current_period` and floor the
    result at 0, then multiply the remaining chargeable days by a per-day rate
    that depends on the asset's type: 1200 cents per day for a defibrillator and
    250 cents per day for any other asset."

    PRD §3.9: "Start from a base equal to `labor_subtotal_cents` plus
    `program_direct_cost_cents`."

    PRD §3.9: "The markup rate steps down as that base grows: 12 percent when
    the base is 15000 cents or less, otherwise 9 percent when it is 30000 cents
    or less, otherwise 7 percent."

    PRD §3.9: "`gross_amount_cents` is the base plus `admin_markup_cents`."

    PRD §3.9: "The volume credit rate then steps **up** with the gross: 3
    percent when the gross is 70000 cents or more, otherwise 1.5 percent when it
    is 35000 cents or more, otherwise nothing at all."

    PRD §3.9: "A provisional net is the gross less `volume_credit_cents` less
    `downtime_credit_cents`."

    PRD §3.9: "If the provisional net exceeds that headroom, `net_amount_cents`
    is set to the headroom and `nte_capped` is set to true; otherwise
    `net_amount_cents` is the provisional net and `nte_capped` is false."

    Design: Corner/endpoints/repair_complete_accrues_downtime_days_into_the_invoice
    """
    scenario = _setup_repaired_defibrillator_after_a_completed_session()
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    invoice = scenarios.read_invoice(invoice["id"])

    assert invoice["labor_subtotal_cents"] == 5483, (
        f"the completed LEAD assignment books 70 paid minutes at 4700 cents an "
        f"hour, so labor_subtotal_cents is 5483; got "
        f"{invoice['labor_subtotal_cents']}"
    )
    assert invoice["program_direct_cost_cents"] == 4517, (
        f"the completed session carried 4517 cents of direct supply cost, got "
        f"{invoice['program_direct_cost_cents']}"
    )
    assert invoice["admin_markup_cents"] == 1200, (
        f"a base of 10000 cents takes the 12 percent tier, so "
        f"admin_markup_cents is 1200; got {invoice['admin_markup_cents']}"
    )
    assert invoice["gross_amount_cents"] == 11200, (
        f"gross is the base 10000 plus the markup 1200, so 11200; got "
        f"{invoice['gross_amount_cents']}"
    )
    assert invoice["volume_credit_cents"] == 0, (
        f"a gross of 11200 is below 35000, so no volume credit applies; got "
        f"{invoice['volume_credit_cents']}"
    )
    assert invoice["downtime_credit_cents"] == 3600, (
        f"6 accrued days less the 3-day grace, at 1200 cents a day for a "
        f"defibrillator, is 3600; got {invoice['downtime_credit_cents']}"
    )
    assert invoice["net_amount_cents"] == 7600, (
        f"net is the gross 11200 less the volume credit 0 less the downtime "
        f"credit 3600, so 7600; got {invoice['net_amount_cents']}"
    )
    assert invoice["nte_capped"] is False, (
        f"a 7600-cent net sits far inside a 5000000-cent annual ceiling, so "
        f"nte_capped must be false; got {invoice['nte_capped']!r}"
    )


# ==========================================================================
# An amendment mints a successor and leaves its predecessor running
# ==========================================================================
def test_amendment_mints_a_draft_successor_that_supersedes_its_predecessor(api):
    """PRD §3.1: "The result is a brand-new contract in `DRAFT` whose
    `supersedes_contract_id` names the predecessor and whose `client_name` and
    `site_code` are inherited from it; because the site code is inherited rather
    than chosen, amendments are exempt from the site-code uniqueness rule that
    governs originals."

    PRD §3.1: "The amendment payload carries a fresh `fee_structure`,
    `staffing_model`, `budgeted_staff_fte`, `participation_target_pct`,
    `term_start_on`, `term_end_on`, and whichever of `management_fee_cents` or
    `not_to_exceed_cents` the new commercial model requires."

    PRD §3.1: "A `MANAGEMENT_FEE` contract must carry `management_fee_cents` — a
    flat monthly amount of at least zero — and must leave `not_to_exceed_cents`
    null."

    Design: Corner/endpoints/amendment_creates_successor_contract_and_supersedes_predecessor
    """
    scenario = scenarios.setup_active_contract()
    predecessor = scenarios.read_contract(scenario["contract_id"])

    successor = validate_success(
        api.create_amendment(
            predecessor["id"], _management_fee_amendment_payload(), ADMIN
        ),
        201,
    )

    assert successor["id"] != predecessor["id"], (
        "the amendment must mint a new contract rather than mutate the "
        f"predecessor, but both carry id {successor['id']!r}"
    )
    assert successor["status"] == "DRAFT", (
        f"the successor must land in DRAFT, got {successor['status']!r}"
    )
    assert successor["supersedes_contract_id"] == predecessor["id"], (
        f"supersedes_contract_id must name the predecessor {predecessor['id']!r}, "
        f"got {successor['supersedes_contract_id']!r}"
    )
    assert successor["site_code"] == predecessor["site_code"], (
        f"the successor inherits the predecessor's site_code "
        f"{predecessor['site_code']!r} without tripping the uniqueness rule, got "
        f"{successor['site_code']!r}"
    )
    assert successor["client_name"] == predecessor["client_name"], (
        f"the successor inherits client_name {predecessor['client_name']!r}, got "
        f"{successor['client_name']!r}"
    )
    assert successor["fee_structure"] == "MANAGEMENT_FEE", (
        f"the amendment may switch the commercial model, so fee_structure must "
        f"be MANAGEMENT_FEE; got {successor['fee_structure']!r}"
    )
    assert successor["management_fee_cents"] == 40000, (
        f"a MANAGEMENT_FEE successor must carry the supplied flat fee 40000, got "
        f"{successor['management_fee_cents']!r}"
    )
    assert successor["not_to_exceed_cents"] is None, (
        f"a MANAGEMENT_FEE contract must leave not_to_exceed_cents null, got "
        f"{successor['not_to_exceed_cents']!r}"
    )
    assert successor["staffing_model"] == "HYBRID", (
        f"the successor takes the freshly supplied staffing_model HYBRID, got "
        f"{successor['staffing_model']!r}"
    )
    assert successor["participation_target_pct"] == 45, (
        f"the successor takes the freshly supplied participation_target_pct 45, "
        f"got {successor['participation_target_pct']!r}"
    )


def test_amendment_successor_starts_with_every_counter_at_zero(api):
    """PRD §3.1: "A newly created contract lands in `DRAFT` with
    `revision_round`, `ytd_billed_cents`, `pending_penalty_cents`,
    `uncovered_session_count`, and `eligible_member_count` all initialised to 0,
    `supersedes_contract_id` null, and `approved_at` null."

    PRD §3.1: "The result is a brand-new contract in `DRAFT` whose
    `supersedes_contract_id` names the predecessor and whose `client_name` and
    `site_code` are inherited from it; because the site code is inherited rather
    than chosen, amendments are exempt from the site-code uniqueness rule that
    governs originals."

    Design: Corner/endpoints/amendment_creates_successor_contract_and_supersedes_predecessor
    """
    scenario = scenarios.setup_active_contract()

    successor = validate_success(
        api.create_amendment(
            scenario["contract_id"], _management_fee_amendment_payload(), ADMIN
        ),
        201,
    )

    assert successor["version"] == 1, (
        f"a brand-new record starts at version 1, got {successor['version']!r}"
    )
    for counter in (
        "revision_round",
        "ytd_billed_cents",
        "pending_penalty_cents",
        "uncovered_session_count",
        "eligible_member_count",
    ):
        assert successor[counter] == 0, (
            f"a brand-new successor initialises {counter} to 0, got "
            f"{successor[counter]!r}"
        )
    assert successor["approved_at"] is None, (
        f"an unapproved successor draft leaves approved_at null, got "
        f"{successor['approved_at']!r}"
    )


def test_amendment_leaves_the_predecessor_contract_active_and_untouched(api):
    """PRD §3.1: "The predecessor is left entirely untouched — it keeps running,
    and keeps billing, until the operator terminates it."

    PRD §3.1: "The `fee_structure` is either `MANAGEMENT_FEE` or `COST_PLUS` and
    is immutable once the contract exists — a commercial model change is
    expressed as an amendment producing a new contract, never as an edit."

    Design: Corner/endpoints/amendment_creates_successor_contract_and_supersedes_predecessor
    """
    scenario = scenarios.setup_active_contract()
    before = scenarios.read_contract(scenario["contract_id"])

    validate_success(
        api.create_amendment(
            scenario["contract_id"], _management_fee_amendment_payload(), ADMIN
        ),
        201,
    )

    after = scenarios.read_contract(scenario["contract_id"])
    assert after["status"] == "ACTIVE", (
        f"the predecessor keeps running, so it must still be ACTIVE, got "
        f"{after['status']!r}"
    )
    assert after["fee_structure"] == "COST_PLUS", (
        f"fee_structure is immutable on the predecessor, so it must still be "
        f"COST_PLUS, got {after['fee_structure']!r}"
    )
    assert after["not_to_exceed_cents"] == before["not_to_exceed_cents"], (
        f"the predecessor's annual ceiling is untouched: expected "
        f"{before['not_to_exceed_cents']!r}, got {after['not_to_exceed_cents']!r}"
    )
    assert after["supersedes_contract_id"] is None, (
        f"the predecessor supersedes nothing, so supersedes_contract_id stays "
        f"null; got {after['supersedes_contract_id']!r}"
    )
    assert after["version"] == before["version"], (
        f"the predecessor is left entirely untouched, so its version must stay "
        f"at {before['version']}, got {after['version']}"
    )


def test_amendment_against_a_draft_successor_is_refused(api):
    """PRD §3.1: "An operator may create a successor draft against a contract
    that is `ACTIVE` or `SUSPENDED`; against any other status the request is
    refused with `ERR_AMENDMENT_NOT_ALLOWED`."

    Design: Corner/endpoints/amendment_creates_successor_contract_and_supersedes_predecessor
    """
    scenario = scenarios.setup_active_contract()
    successor = validate_success(
        api.create_amendment(
            scenario["contract_id"], _management_fee_amendment_payload(), ADMIN
        ),
        201,
    )
    assert successor["status"] == "DRAFT", (
        f"the successor must be a DRAFT for this rejection to be about status, "
        f"got {successor['status']!r}"
    )

    second = factories.amendment_payload(
        fee_structure="MANAGEMENT_FEE",
        staffing_model="HYBRID",
        budgeted_staff_fte=4.0,
        participation_target_pct=45,
        term_start_on="2028-07-01",
        term_end_on="2029-06-30",
        management_fee_cents=41000,
    )
    second.pop("not_to_exceed_cents", None)

    validate_error(
        api.create_amendment(successor["id"], second, ADMIN),
        ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED.value,
    )


def test_amendment_lineage_is_discoverable_by_the_supersedes_filter(api):
    """PRD §3.1: "Contract listings can be filtered by `status`, by
    `fee_structure`, by `client_name`, and by `supersedes_contract_id`, which is
    what makes an amendment lineage discoverable."

    PRD §2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied, and `has_more` is true exactly when rows remain beyond
    the current page."

    Design: Corner/endpoints/amendment_creates_successor_contract_and_supersedes_predecessor
    """
    scenario = scenarios.setup_active_contract()
    predecessor_id = scenario["contract_id"]
    successor = validate_success(
        api.create_amendment(
            predecessor_id, _management_fee_amendment_payload(), ADMIN
        ),
        201,
    )

    items, meta = validate_paginated(
        api.list_client_contracts(
            ADMIN, params={"supersedes_contract_id": predecessor_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one contract supersedes {predecessor_id!r}, so total_count "
        f"must be 1; got {meta['total_count']}"
    )
    assert [row["id"] for row in items] == [successor["id"]], (
        f"the lineage listing must return only the successor "
        f"{successor['id']!r}, got {[row['id'] for row in items]}"
    )


# ==========================================================================
# Every collection read agrees with its matching detail read
# ==========================================================================
def _collection_and_detail(scenario: dict, entity_kind: str) -> dict:
    """Issue one filtered collection read and the matching detail read for one
    kind of aggregate, and describe what the pair must show."""
    contract_id = scenario["contract_id"]

    if entity_kind == "staff_members":
        return {
            "listing": api_client.list_staff_members(
                AUDITOR,
                params={"contract_id": contract_id, "duty_status": "ACTIVE_DUTY"},
            ),
            "expected_total": 2,
            "row_filters": {"contract_id": contract_id, "duty_status": "ACTIVE_DUTY"},
            "detail": api_client.get_staff_member(scenario["instructor_id"], AUDITOR),
            "detail_fields": {
                "duty_status": "ACTIVE_DUTY",
                "role_type": "GROUP_EX_INSTRUCTOR",
            },
        }

    if entity_kind == "staff_credentials":
        return {
            "listing": api_client.list_staff_member_credentials(
                scenario["instructor_id"], AUDITOR, params={"status": "VERIFIED"}
            ),
            "expected_total": 1,
            "row_filters": {
                "status": "VERIFIED",
                "staff_member_id": scenario["instructor_id"],
            },
            "detail": api_client.get_staff_credential(
                scenario["instructor_credential"]["id"], AUDITOR
            ),
            "detail_fields": {
                "status": "VERIFIED",
                "credential_type": "GROUP_EX_CERT",
            },
        }

    if entity_kind == "facility_rooms":
        return {
            "listing": api_client.list_facility_rooms(
                AUDITOR, params={"contract_id": contract_id, "room_state": "OPEN"}
            ),
            "expected_total": 1,
            "row_filters": {"contract_id": contract_id, "room_state": "OPEN"},
            "detail": api_client.get_facility_room(scenario["room_id"], AUDITOR),
            "detail_fields": {"room_state": "OPEN", "open_deficiency_count": 0},
        }

    if entity_kind == "facility_assets":
        return {
            "listing": api_client.list_facility_assets(
                AUDITOR,
                params={"contract_id": contract_id, "readiness_status": "READY"},
            ),
            "expected_total": 1,
            "row_filters": {"contract_id": contract_id, "readiness_status": "READY"},
            "detail": api_client.get_facility_asset(scenario["aed_id"], AUDITOR),
            "detail_fields": {
                "asset_type": "AED",
                "status": "IN_SERVICE",
                "readiness_status": "READY",
            },
        }

    if entity_kind == "program_offerings":
        return {
            "listing": api_client.list_program_offerings(
                AUDITOR, params={"contract_id": contract_id, "status": "ACTIVE"}
            ),
            "expected_total": 1,
            "row_filters": {"contract_id": contract_id, "status": "ACTIVE"},
            "detail": api_client.get_program_offering(scenario["offering_id"], AUDITOR),
            "detail_fields": {"status": "ACTIVE", "coverage_gap_count": 0},
        }

    if entity_kind == "program_sessions":
        return {
            "listing": api_client.list_program_sessions(
                AUDITOR,
                params={"offering_id": scenario["offering_id"], "status": "STAFFED"},
            ),
            "expected_total": 1,
            "row_filters": {
                "offering_id": scenario["offering_id"],
                "status": "STAFFED",
            },
            "detail": api_client.get_program_session(scenario["session_id"], AUDITOR),
            "detail_fields": {"status": "STAFFED", "scheduled_minutes": 55},
        }

    if entity_kind == "staff_assignments":
        return {
            "listing": api_client.list_staff_assignments(
                AUDITOR,
                params={
                    "session_id": scenario["session_id"],
                    "role_on_session": "LEAD",
                },
            ),
            "expected_total": 1,
            "row_filters": {
                "session_id": scenario["session_id"],
                "role_on_session": "LEAD",
            },
            "detail": api_client.get_staff_assignment(
                scenario["assignment_id"], AUDITOR
            ),
            "detail_fields": {"status": "CONFIRMED", "paid_minutes": 70},
        }

    if entity_kind == "liability_waivers":
        return {
            "listing": api_client.list_member_waivers(
                scenario["member_id"], AUDITOR, params={"status": "SIGNED"}
            ),
            "expected_total": 1,
            "row_filters": {"status": "SIGNED", "member_id": scenario["member_id"]},
            "detail": api_client.get_liability_waiver(scenario["waiver_id"], AUDITOR),
            "detail_fields": {"status": "SIGNED", "waiver_version_code": "WVR-2026A"},
        }

    if entity_kind == "participation_records":
        return {
            "listing": api_client.list_participation_records(
                AUDITOR, params={"member_id": scenario["member_id"]}
            ),
            "expected_total": 0,
            "row_filters": {"member_id": scenario["member_id"]},
            "detail": None,
            "detail_fields": {},
        }

    if entity_kind == "incident_reports":
        return {
            "listing": api_client.list_incident_reports(
                AUDITOR, params={"contract_id": contract_id, "severity": "MINOR"}
            ),
            "expected_total": 1,
            "row_filters": {"contract_id": contract_id, "severity": "MINOR"},
            "detail": api_client.get_incident_report(scenario["incident_id"], AUDITOR),
            "detail_fields": {"status": "REPORTED", "cause_category": "SLIP_FALL"},
        }

    if entity_kind == "monthly_invoices":
        return {
            "listing": api_client.list_monthly_invoices(
                AUDITOR, params={"contract_id": contract_id, "status": "DRAFT"}
            ),
            "expected_total": 1,
            "row_filters": {"contract_id": contract_id, "status": "DRAFT"},
            "detail": api_client.get_monthly_invoice(scenario["invoice_id"], AUDITOR),
            "detail_fields": {
                "fee_structure_snapshot": "COST_PLUS",
                "net_amount_cents": 0,
            },
        }

    raise AssertionError(f"no collection walk defined for {entity_kind!r}")


@pytest.mark.parametrize(
    "entity_kind",
    [
        "staff_members",
        "staff_credentials",
        "facility_rooms",
        "facility_assets",
        "program_offerings",
        "program_sessions",
        "staff_assignments",
        "liability_waivers",
        "participation_records",
        "incident_reports",
        "monthly_invoices",
    ],
)
def test_every_collection_and_detail_read_agrees_on_the_same_row(api, entity_kind):
    """PRD §2.6: "Every aggregate in this system is its own top-level
    collection: client contracts, staff members, staff credentials, facility
    rooms, facility assets, program offerings, program sessions, staffing
    assignments, members, liability waivers, participation records, incident
    reports, and monthly invoices."

    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object."

    PRD §2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied, and `has_more` is true exactly when rows remain beyond
    the current page."

    PRD §3.3: "A newly registered room opens for business immediately:
    `room_state` is `OPEN`, `open_deficiency_count` is 0, and both
    `last_inspection_on` and `last_cleanliness_score` are null until the first
    inspection lands."

    PRD §3.4: "`coverage_gap_count` is a cumulative tally of how many times a
    session of this offering has been pushed into `STAFFING_AT_RISK` by a loss of
    covered staff; it only ever grows."

    PRD §3.5: "`paid_minutes` is computed as the session's `scheduled_minutes`
    plus a setup allowance of 15 minutes when the `role_on_session` is `LEAD`,
    and simply the session's `scheduled_minutes` when it is `SUPPORT`."

    PRD §3.9: "The draft **pins** the contract's current `fee_structure` into
    `fee_structure_snapshot`, so that a contract amended mid-dispute is still
    rebilled under the terms that were in force when the period was first
    invoiced; every subsequent recomputation of that invoice reads the snapshot
    rather than the live contract."

    Design: Corner/endpoints/every_collection_and_detail_read_agrees_on_the_same_row
    """
    scenario = _setup_populated_site()
    walk = _collection_and_detail(scenario, entity_kind)

    items, meta = validate_paginated(walk["listing"])
    assert meta["total_count"] == walk["expected_total"], (
        f"the {entity_kind} collection must report total_count "
        f"{walk['expected_total']} for its filters, got {meta['total_count']}"
    )
    assert len(items) == walk["expected_total"], (
        f"the {entity_kind} collection must return {walk['expected_total']} rows "
        f"on the first page, got {len(items)}"
    )
    assert meta["has_more"] is False, (
        f"every {entity_kind} row fits on the first page, so has_more must be "
        f"false; got {meta['has_more']!r}"
    )
    for row in items:
        for field, expected in walk["row_filters"].items():
            assert row[field] == expected, (
                f"the {entity_kind} collection must honour its {field} filter: "
                f"row {row.get('id')!r} carries {row[field]!r}, expected "
                f"{expected!r}"
            )

    if walk["detail"] is None:
        assert items == [], (
            f"an empty {entity_kind} collection answers with an empty list "
            f"rather than an error, got {items!r}"
        )
        return

    detail = validate_success(walk["detail"])
    for field, expected in walk["detail_fields"].items():
        assert detail[field] == expected, (
            f"the {entity_kind} detail read must show {field} {expected!r}, got "
            f"{detail[field]!r}"
        )

    matches = [row for row in items if row["id"] == detail["id"]]
    assert len(matches) == 1, (
        f"the {entity_kind} collection must carry exactly one row for "
        f"{detail['id']!r}, found {len(matches)}"
    )
    listed = matches[0]
    differences = {
        field: (listed.get(field), detail.get(field))
        for field in set(listed) | set(detail)
        if listed.get(field) != detail.get(field)
    }
    assert not differences, (
        f"the {entity_kind} row read through its collection must be identical to "
        f"the same row read through its detail endpoint, but these fields differ "
        f"(collection, detail): {differences}"
    )
