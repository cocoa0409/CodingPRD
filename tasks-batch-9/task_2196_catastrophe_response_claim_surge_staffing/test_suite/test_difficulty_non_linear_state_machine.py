"""Queue A — rule_id: non_linear_state_machine.

Parallel independent axes on the Claim, a genuine cycle on the Adjuster credential
axis, and a branching fork out of CatastropheEvent with divergent side effects.
"""
from test_helpers import validate_success
from test_helpers.assertions import assert_adjuster, assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CO = make_compliance_officer_headers("co_1")


# ---------------------------------------------------------------------------
# Instance 1 — claim_handling_and_payment_axes_evolve_independently
# ---------------------------------------------------------------------------
def _fast_track_claim_and_desk_adjuster(api):
    """CAT-2026-301 DECLARED (WINTER_STORM/NY @ 0.1000); one DESK-certified STAFF
    adjuster; one claim TRIAGED to FAST_TRACK / DESK."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-301",
                "peril_type": "WINTER_STORM",
                "jurisdiction_state": "NY",
                "event_start_utc": "2026-07-30T00:00:00.000Z",
                "exposure_count": 200,
                "avg_insured_value": 220000,
                "expected_severity_index": 0.1000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Dana Desk",
                "employment_type": "STAFF",
                "home_state": "NY",
                "licensed_states": ["NY"],
                "license_expiry_utc": "2027-11-30T00:00:00.000Z",
                "max_open_claims": 5,
                "daily_rate": 700,
                "per_diem_rate": 0,
                "desk_certified": True,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-9001",
                "loss_state": "NY",
                "loss_date_utc": "2026-07-30T00:00:00.000Z",
                "reported_loss_amount": 8000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 100000,
                        "deductible_amount": 500,
                        "estimated_damage_amount": 9000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    return event, adjuster, triaged


def test_payment_axis_advances_while_handling_axis_stays_at_triaged(api):
    """PRD §3.8: "The claim moves `NONE → ADVANCE_ISSUED` on the payment axis and,
    when `advance_issuing_examiner_user_id` was previously null, the acting
    `X-User-ID` is recorded there as the segregation-of-duties anchor that will later
    block this same user from closing the claim."
    PRD §3.6: "Otherwise, if the tier is `FAST_TRACK` and the `reported_loss_amount`
    is 10000.00 or less, the mode is `DESK` — the boundary is inclusive, so a reported
    loss of exactly 10000.00 resolves to `DESK` while 10000.01 resolves to `FIELD`."

    Design: Difficulty/non_linear_state_machine/claim_handling_and_payment_axes_evolve_independently
    """
    _, _, claim = _fast_track_claim_and_desk_adjuster(api)
    assert_money_equals(claim["severity_score"], 9.20, "severity_score")
    assert claim["triage_tier"] == "FAST_TRACK"
    assert claim["inspection_mode"] == "DESK"
    # DWELLING eligible 8500.00 * 0.30 = 2550.00, tiered * 0.40 = 1020.00.
    assert_money_equals(claim["advance_cap"], 1020.00, "advance_cap")

    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 500, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )

    assert_money_equals(advance["amount"], 500.00, "amount")
    after = validate_success(api.get_claim(claim["id"], CE))
    assert after["payment_status"] == "ADVANCE_ISSUED"
    assert after["handling_status"] == "TRIAGED", "the handling axis must not move"
    assert_money_equals(after["advance_paid_total"], 500.00, "advance_paid_total")
    assert_money_equals(after["paid_amount"], 500.00, "paid_amount")
    assert_money_equals(after["case_reserve"], 1625.00, "case_reserve")


def test_handling_axis_advances_while_payment_axis_stays_at_advance_issued(api):
    """PRD §3.3: "Each adjuster row carries **two state axes that evolve
    independently and never gate each other**."
    PRD §3.7: "A created assignment is `SCHEDULED`, records `EXPLICIT_ADJUSTER` or
    `SELECTOR_RANKED` in `selection_reason`, and starts with `report_submitted_at_utc`
    and `verified_damage_amount` both null."
    PRD §3.7: "Creation also pulls the claim onto the inspection track: a claim in
    `TRIAGED` moves `TRIAGED → INSPECTION_PENDING`, and a claim in `REOPENED` moves
    `REOPENED → INSPECTION_PENDING`; both branches are driven by the same event — an
    assignment for the claim coming into existence in `SCHEDULED` — and both leave no
    further side effects of their own."

    Design: Difficulty/non_linear_state_machine/claim_handling_and_payment_axes_evolve_independently
    """
    _, adjuster, claim = _fast_track_claim_and_desk_adjuster(api)
    validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 500, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )

    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-02T00:00:00.000Z",
                "window_end_utc": "2026-08-03T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )

    assert assignment["status"] == "SCHEDULED"
    assert assignment["selection_reason"] == "EXPLICIT_ADJUSTER"
    after = validate_success(api.get_claim(claim["id"], CE))
    assert after["handling_status"] == "INSPECTION_PENDING"
    assert after["payment_status"] == "ADVANCE_ISSUED", "the payment axis must not move"


# ---------------------------------------------------------------------------
# Instance 2 — adjuster_credential_axis_cycles_expired_waived_expired
# ---------------------------------------------------------------------------
def _expired_independent_adjuster_under_waiver(api):
    """CAT-2026-302 DECLARED with an EFFECTIVE ADJUSTER_LICENSE_WAIVER bulletin
    binding FL from 2026-08-05 (inclusive) to 2026-08-20 (exclusive), plus an
    INDEPENDENT adjuster whose licence lapsed at 2026-08-10. Clock left at
    2026-08-11, so the adjuster reads EXPIRED."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-302",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-28T00:00:00.000Z",
                "exposure_count": 900,
                "avg_insured_value": 260000,
                "expected_severity_index": 0.0600,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "FL-2026-W1",
                "jurisdiction_state": "FL",
                "bulletin_type": "ADJUSTER_LICENSE_WAIVER",
                "effective_from": "2026-08-05T00:00:00.000Z",
                "effective_to": "2026-08-20T00:00:00.000Z",
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(bulletin["id"], CO))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Ike Indie",
                "employment_type": "INDEPENDENT",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2026-08-10T00:00:00.000Z",
                "max_open_claims": 10,
                "daily_rate": 800,
                "per_diem_rate": 120,
                "desk_certified": False,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    assert adjuster["credential_status"] == "EXPIRING", (
        "registration inside the warning window stamps EXPIRING immediately"
    )
    validate_success(api.set_clock("2026-08-11T00:00:00.000Z", DC))
    return event, bulletin, adjuster


def test_license_waiver_moves_expired_adjuster_to_waived(api):
    """PRD §3.3: "An expired independent adjuster can be rescued: a
    `ComplianceOfficer` applies an emergency licence waiver, naming the `event_id`
    whose regulator issued the waiver, which moves the adjuster `EXPIRED → WAIVED`
    and recomputes the score with an 8-point credential penalty."
    PRD §3.3: "A `WAIVED` adjuster can be `DEPLOYED`; an `AVAILABLE` adjuster can be
    `EXPIRED`."

    Design: Difficulty/non_linear_state_machine/adjuster_credential_axis_cycles_expired_waived_expired
    """
    event, _, adjuster = _expired_independent_adjuster_under_waiver(api)
    expired = validate_success(api.get_adjuster(adjuster["id"], CO))
    assert expired["credential_status"] == "EXPIRED"

    waived = validate_success(
        api.apply_license_waiver(adjuster["id"], {"event_id": event["id"]}, CO)
    )

    assert_adjuster(waived)
    assert waived["credential_status"] == "WAIVED"
    assert waived["deployment_status"] == "AVAILABLE", "the deployment axis never moved"


def test_waiver_lapse_returns_adjuster_to_expired_completing_the_cycle(api):
    """PRD §3.3: "A waiver is not permanent. Once no effective
    `ADJUSTER_LICENSE_WAIVER` bulletin covers the current instant for the adjuster's
    licensed jurisdiction, they fall back `WAIVED → EXPIRED` on the next read or
    write, their score is recomputed, and every `SCHEDULED` assignment of theirs is
    cancelled — the same credential-axis cycle running in reverse:
    `EXPIRED → WAIVED → EXPIRED`."
    PRD §3.3: "From that, the **credential penalty** for the adjuster's current
    `credential_status` is subtracted: zero points for `VALID`, 15 points for
    `EXPIRING`, 8 points for `WAIVED`, and 100 points for `EXPIRED`."
    PRD §3.2: "Expiry works the same way and needs no operator: once the clock
    reaches or passes `effective_to`, the bulletin moves `EFFECTIVE → EXPIRED` on the
    next read or write, the event's `moratorium_active` and posture are recomputed,
    and the same population of claims has `deadline_utc` recomputed."

    Design: Difficulty/non_linear_state_machine/adjuster_credential_axis_cycles_expired_waived_expired
    """
    event, bulletin, adjuster = _expired_independent_adjuster_under_waiver(api)
    waived = validate_success(
        api.apply_license_waiver(adjuster["id"], {"event_id": event["id"]}, CO)
    )
    assert waived["credential_status"] == "WAIVED"

    validate_success(api.set_clock("2026-08-20T00:00:00.000Z", CO))

    after = validate_success(api.get_adjuster(adjuster["id"], CO))
    assert after["credential_status"] == "EXPIRED"
    assert after["deployment_status"] == "AVAILABLE"
    # availability 100.00 - credential penalty 100.00, clamped at 0.
    assert_money_equals(after["surge_capacity_score"], 0.00, "surge_capacity_score")
    assert validate_success(api.get_bulletin(bulletin["id"], CO))["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Instance 3 — event_close_branch_standdown_vs_demobilizing_divergent_side_effects
# ---------------------------------------------------------------------------
def _standdown_eligible_event(api):
    """CAT-2026-303 DECLARED with zero claims and zero deployments, one ACTIVE
    12-room block, and one VendorFirm ACTIVATED onto the event."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-303",
                "peril_type": "FLOOD",
                "jurisdiction_state": "LA",
                "event_start_utc": "2026-07-27T00:00:00.000Z",
                "exposure_count": 300,
                "avg_insured_value": 180000,
                "expected_severity_index": 0.0800,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Bayou Suites",
                "city": "Baton Rouge",
                "rooms_total": 12,
                "nightly_rate": 180,
                "block_start_date": "2026-08-05T00:00:00.000Z",
                "block_end_date": "2026-08-19T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Delta Tarp Co",
                "vendor_type": "TARP",
                "service_states": ["LA", "MS"],
                "max_concurrent_jobs": 4,
                "performance_score": 88.50,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    firm = validate_success(
        api.activate_vendor_firm(
            firm["id"],
            {"event_id": event["id"]},
            make_vendor_coordinator_headers(firm["id"]),
        )
    )
    return event, block, firm


def test_standdown_branch_releases_housing_and_freezes_posture(api):
    """PRD §3.1: "Its side-effect set is strictly smaller than the full path's: every
    housing block on the event in `PENDING` or `ACTIVE` moves to `RELEASED`, and
    `posture` becomes `FROZEN`."
    PRD §3.1: "The **stand-down branch** closes the event `DECLARED → CLOSED` for a
    storm that veered away and never surged. It requires the event to be in `DECLARED`
    with `open_claim_count` of zero and `surge_adjuster_count` of zero; a `DECLARED`
    event failing either count is refused with `ERR_EVENT_NOT_STANDDOWN_ELIGIBLE`."
    PRD §3.1: "`housing_committed_cost` sums, over every housing block on the event
    whose `status` is `PENDING`, `ACTIVE` or `EXHAUSTED`, that block's `nightly_rate`
    multiplied by its `rooms_total` multiplied by its `block_night_count`, to 2 decimal
    places; released blocks drop out of the sum entirely."

    Design: Difficulty/non_linear_state_machine/event_close_branch_standdown_vs_demobilizing_divergent_side_effects
    """
    event, block, _ = _standdown_eligible_event(api)

    closed = validate_success(api.close_event(event["id"], CM))

    assert closed["status"] == "CLOSED"
    assert closed["posture"] == "FROZEN"
    assert_money_equals(closed["housing_committed_cost"], 0.00, "housing_committed_cost")
    refreshed_block = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed_block["status"] == "RELEASED"
    assert refreshed_block["rooms_occupied"] == 0


def test_standdown_branch_leaves_activated_vendor_firm_untouched(api):
    """PRD §3.1: "There is no vendor deactivation on this branch and no
    file-transfer-batch gate, because a stand-down event has no vendor jobs and no
    transferred files to account for."
    PRD §3.9: "When the parent event closes from `DEMOBILIZING`, every firm activated
    onto it moves `ACTIVATED → NETWORK_INACTIVE` and its `activated_for_event_id` is
    cleared."

    Design: Difficulty/non_linear_state_machine/event_close_branch_standdown_vs_demobilizing_divergent_side_effects
    """
    event, _, firm = _standdown_eligible_event(api)

    validate_success(api.close_event(event["id"], CM))

    refreshed = validate_success(
        api.get_vendor_firm(firm["id"], make_vendor_coordinator_headers(firm["id"]))
    )
    assert refreshed["status"] == "ACTIVATED"
    assert refreshed["activated_for_event_id"] == event["id"]
