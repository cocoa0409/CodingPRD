"""Concurrency and consistency: the two version guards, run idempotence and same-request visibility."""
from test_helpers import (
    CO,
    CRM,
    SYS,
    ApiErrorId,
    api_client,
    assert_credit_line_capacity_identity,
    assert_utc_millisecond_timestamp,
    credit_line_version,
    dealer_version,
    fund_advance_payload,
    list_unit_obligations,
    move_title_custody,
    read_credit_line,
    read_dealer,
    read_unit,
    reconcile_audit,
    record_observation,
    register_unit,
    remittance_payload,
    request_advance,
    run_curtailment,
    schedule_audit,
    set_clock,
    setup_active_line,
    setup_floored_unit,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

NEW_TIER_1000 = {
    "inventory_class": "NEW",
    "age_days_from": 90,
    "age_days_to": None,
    "cumulative_paydown_bps": 1000,
}


def test_the_second_funding_on_a_stale_capacity_view_is_refused_then_retried():
    """One version read serves two advances: the first disbursement invalidates it for the second.

    PRD: "Disbursing a funding advance requires `expected_credit_line_version` as a mandatory input field carrying the client's last observed `version` of the governing `CreditLine`. If that value does not equal the line's current `version`, the request is rejected with `ERR_STALE_CREDIT_LINE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_credit_line_version_on_the_second_fund_returns_precondition_failed
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={"legal_name": "Corner Stale Line Motors LLC", "state_code": "MT"},
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]

    advances = []
    for index, seed in enumerate(("CRNSTALEUNITA001", "CRNSTALEUNITB001")):
        unit = register_unit(
            dealer_id,
            line_id,
            seed,
            dealer_headers=ctx["dealer_headers"],
            invoice_amount_cents=3000000,
        )
        move_title_custody(unit["id"], "LENDER_HELD", f"MSO-C34-{index}")
        advances.append(
            (
                unit,
                request_advance(
                    unit["id"], ctx["dealer_headers"], 3000000, f"INV-C34-{index}"
                ),
            )
        )

    shared_version = credit_line_version(line_id)
    assert read_credit_line(line_id)["available_credit_cents"] == 500000000

    first = validate_success(
        api_client.fund_advance(
            advances[0][1]["id"],
            fund_advance_payload(shared_version, "WIRE-C34-A"),
            CO,
        )
    )
    assert first["status"] == "FUNDED"
    assert credit_line_version(line_id) != shared_version

    validate_error(
        api_client.fund_advance(
            advances[1][1]["id"],
            fund_advance_payload(shared_version, "WIRE-C34-B"),
            CO,
        ),
        ApiErrorId.ERR_STALE_CREDIT_LINE_VERSION,
        412,
    )

    blocked_unit, blocked_advance = advances[1]
    assert validate_success(
        api_client.get_funding_advance(blocked_advance["id"], CO)
    )["status"] == "REQUESTED"
    assert read_unit(blocked_unit["id"])["funding_status"] == "PENDING_FUNDING"
    assert len(list_unit_obligations(blocked_unit["id"])) == 0

    after_refusal = read_credit_line(line_id)
    assert after_refusal["available_credit_cents"] == 497000000
    assert_credit_line_capacity_identity(after_refusal)

    retried = validate_success(
        api_client.fund_advance(
            blocked_advance["id"],
            fund_advance_payload(credit_line_version(line_id), "WIRE-C34-B"),
            CO,
        )
    )
    assert retried["status"] == "FUNDED"
    settled = read_credit_line(line_id)
    assert settled["available_credit_cents"] == 494000000
    assert settled["outstanding_principal_cents"] == 6000000
    assert_credit_line_capacity_identity(settled)


def test_the_cure_payment_must_be_composed_against_the_post_reconcile_dealer():
    """The reconcile that opens the incident moves the dealer version, so the pre-reconcile view is refused.

    PRD: "The remittance is the second of the two optimistically-concurrent writes described in §2.8: `expected_dealer_version` must equal the dealership's current `version` or the request is refused with `ERR_STALE_DEALER_VERSION`."

    PRD: "For every observation of this audit whose `is_out_of_trust` is true, in `created_at` ascending order, an `OutOfTrustIncident` is created in `OPEN` carrying `dealer_id`, `unit_id`, `audit_id` and `observation_id`, with `exposure_cents` set to that unit's live `outstanding_principal_cents`, `cure_deadline_at` set to `reconciled_at` plus 10 days, `cured_at`, `charged_off_at` and `resolution_reason_code` null, and `version` 1."

    PRD: "An incident that receives at least its full `exposure_cents` moves `OPEN → CURED` with `cured_at` stamped from the logical clock and `resolution_reason_code` `DEALER_PAYOFF`; the unit's `outstanding_principal_cents` falls and its `principal_paid_cents` rises by the cure amount; the unit returns `SOT_OPEN → FLOORED` with `eligibility_status` restored to `ELIGIBLE` and `ineligibility_reason_code` cleared to null; and the dealership's `open_sot_incident_count` and `open_sot_exposure_cents` both fall."

    PRD: "When the dealership's `open_sot_exposure_cents` reaches or exceeds 10,000,000 cents (one hundred thousand dollars), the credit line moves `ACTIVE → SUSPENDED` with `suspension_reason_code` `SOT_EXPOSURE_THRESHOLD`."

    Design: Corner/complexity_layers/stale_dealer_version_on_the_cure_remittance_returns_precondition_failed
    """
    ctx = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNSTALEDEALER01",
        unit_overrides={"invoice_amount_cents": 3000000},
        dealer_overrides={"legal_name": "Corner Stale Dealer Motors LLC", "state_code": "NV"},
    )
    dealer_id = ctx["dealer"]["id"]
    line_id = ctx["credit_line"]["id"]
    unit_id = ctx["unit"]["id"]
    assert read_dealer(dealer_id)["risk_rating"] == "A"

    audit = schedule_audit(dealer_id, "2026-08-01", "2026-08-03", audit_type="UNANNOUNCED")
    start_audit(audit["id"])
    observation = record_observation(
        audit["id"], unit_id, observed_condition="MISSING", title_verified=False
    )
    assert observation["classification"] == "SOLD_OUT_OF_TRUST"
    assert observation["is_out_of_trust"] is True

    stale_version = dealer_version(dealer_id)
    reconciled = reconcile_audit(audit["id"], "Corner stale dealer sign-off")
    assert reconciled["status"] == "RECONCILED_EXCEPTIONS"
    assert reconciled["sot_exposure_cents"] == 3000000

    stale_payload = remittance_payload(
        dealer_id, "SOT_CURE", 3000000, stale_version, "PAY-C35", target_unit_id=unit_id
    )
    validate_error(
        api_client.create_remittance(stale_payload, ctx["dealer_headers"]),
        ApiErrorId.ERR_STALE_DEALER_VERSION,
        412,
    )

    _, remittance_meta = validate_paginated(
        api_client.list_remittances(CO, params={"dealer_id": dealer_id})
    )
    assert remittance_meta["total_count"] == 0

    incidents, incident_meta = validate_paginated(
        api_client.list_out_of_trust_incidents(CO, params={"unit_id": unit_id})
    )
    assert incident_meta["total_count"] == 1
    incident = incidents[0]
    assert incident["status"] == "OPEN"
    assert incident["exposure_cents"] == 3000000
    assert str(incident["cure_deadline_at"]).startswith("2026-08-11T00:00:00")
    assert incident["cured_at"] is None
    assert incident["resolution_reason_code"] is None
    assert read_unit(unit_id)["funding_status"] == "SOT_OPEN"

    dealer_after_refusal = read_dealer(dealer_id)
    assert dealer_after_refusal["open_sot_incident_count"] == 1
    assert dealer_after_refusal["open_sot_exposure_cents"] == 3000000
    assert dealer_after_refusal["risk_score"] == 85
    assert dealer_after_refusal["risk_rating"] == "B"
    assert dealer_after_refusal["audit_frequency_days"] == 90
    assert str(dealer_after_refusal["next_audit_due_at"]).startswith("2026-10-30T00:00:00")
    assert read_credit_line(line_id)["status"] == "ACTIVE"

    fresh_payload = remittance_payload(
        dealer_id,
        "SOT_CURE",
        3000000,
        dealer_version(dealer_id),
        "PAY-C35",
        target_unit_id=unit_id,
    )
    applied = validate_success(
        api_client.create_remittance(fresh_payload, ctx["dealer_headers"]), 201
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_sot_cure_cents"] == 3000000
    assert applied["unapplied_cents"] == 0

    cured = validate_success(
        api_client.get_out_of_trust_incident(incident["id"], CRM)
    )
    assert cured["status"] == "CURED"
    assert str(cured["cured_at"]).startswith("2026-08-01T00:00:00")
    assert cured["resolution_reason_code"] == "DEALER_PAYOFF"

    unit_after = read_unit(unit_id)
    assert unit_after["funding_status"] == "FLOORED"
    assert unit_after["eligibility_status"] == "ELIGIBLE"
    assert unit_after["ineligibility_reason_code"] is None

    dealer_final = read_dealer(dealer_id)
    assert dealer_final["open_sot_incident_count"] == 0
    assert dealer_final["open_sot_exposure_cents"] == 0
    assert dealer_final["risk_score"] == 100
    assert dealer_final["risk_rating"] == "A"
    assert dealer_final["audit_frequency_days"] == 180
    assert str(dealer_final["next_audit_due_at"]).startswith("2027-01-28T00:00:00")


def test_running_the_same_sweep_twice_moves_nothing_the_second_time():
    """Maturity fires once: the repeat sweep still walks the dealership but reports every counter at zero.

    PRD: "An obligation in `SCHEDULED` whose `due_date` is at or before the run date matures to `DUE`: `became_due_at` is stamped from the logical clock, and `required_principal_cents` is written from the **assessed** variant of the curtailment requirement — the variant that reads what the dealership has actually paid."

    PRD: "Each count is exactly the number of rows that made the corresponding transition during this sweep."

    PRD: "An obligation in `DUE` becomes `DELINQUENT` when the run date is **strictly** past its `due_date` plus the line's `curtailment_grace_days`, and its `principal_paid_cents` is still short of its `required_principal_cents`."

    Design: Corner/complexity_layers/a_repeated_curtailment_run_on_the_same_date_advances_nothing
    """
    ctx = setup_floored_unit(
        tiers=[NEW_TIER_1000],
        vin_seed="CRNREPEATRUN0001",
        unit_overrides={"invoice_amount_cents": 3000000},
        curtailment_grace_days=5,
        dealer_overrides={"legal_name": "Corner Repeat Run Motors LLC", "state_code": "IA"},
    )
    dealer_id = ctx["dealer"]["id"]
    unit_id = ctx["unit"]["id"]
    scheduled = list_unit_obligations(unit_id)
    assert len(scheduled) == 1
    assert scheduled[0]["status"] == "SCHEDULED"
    assert str(scheduled[0]["due_date"])[:10] == "2026-10-30"

    set_clock("2026-10-30T00:00:00Z")
    first_run = run_curtailment(dealer_id=dealer_id)
    assert first_run["obligations_marked_due_count"] == 1
    assert first_run["total_required_paydown_cents"] == 300000
    assert first_run["obligations_marked_delinquent_count"] == 0
    matured = list_unit_obligations(unit_id)[0]
    assert matured["status"] == "DUE"
    matured_version = matured["version"]

    second_response = api_client.run_curtailment({"dealer_id": dealer_id}, SYS)
    second_run = validate_success(second_response, 200)
    assert second_run["obligations_marked_due_count"] == 0
    assert second_run["total_required_paydown_cents"] == 0
    assert second_run["obligations_marked_delinquent_count"] == 0
    assert second_run["units_flagged_delinquent_count"] == 0
    assert second_run["exceptions_expired_count"] == 0
    assert_utc_millisecond_timestamp(second_run["run_completed_at"], "run_completed_at")
    assert str(second_run["run_completed_at"]).startswith("2026-10-30T00:00:00")
    assert second_run["dealer_ids_processed"] == [dealer_id]

    unchanged = list_unit_obligations(unit_id)[0]
    assert unchanged["status"] == "DUE"
    assert unchanged["required_principal_cents"] == 300000
    assert str(unchanged["became_due_at"]).startswith("2026-10-30T00:00:00")
    assert unchanged["version"] == matured_version

    assert read_unit(unit_id)["funding_status"] == "FLOORED"
    dealer_after = read_dealer(dealer_id)
    assert dealer_after["delinquent_unit_count"] == 0
    assert dealer_after["risk_score"] == 100


def test_a_disbursement_settles_every_derived_field_inside_the_same_request():
    """The fund response already carries the computed figures and the immediate reads agree with it.

    PRD: "A successful disbursement writes a wide cascade in one request. On the advance: `approved_advance_amount_cents` set to the computed figure, `effective_advance_rate_bps`, `rate_adjustment_codes` and `invoice_age_days_at_funding` recorded, `funded_at` stamped from the logical clock, `funded_by_user_id` set from `X-User-ID`, and the status moving `REQUESTED → FUNDED`."

    PRD: "`available_credit_cents` is `credit_limit_cents` reduced by `outstanding_principal_cents` and reduced again by `charged_off_principal_cents`."

    Design: Corner/consistency_model/every_derived_field_of_a_funding_lands_in_the_same_response
    """
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000],
        dealer_overrides={
            "legal_name": "Corner Immediate Motors LLC",
            "state_code": "NE",
        },
    )
    line_id = ctx["credit_line"]["id"]
    unit = register_unit(
        ctx["dealer"]["id"],
        line_id,
        "CRNIMMEDIATEUNT1",
        dealer_headers=ctx["dealer_headers"],
        invoice_amount_cents=3000000,
        invoice_date="2026-08-01",
    )
    move_title_custody(unit["id"], "LENDER_HELD", "MSO-C37")
    advance = request_advance(unit["id"], ctx["dealer_headers"], 3000000, "INV-C37")

    funded = validate_success(
        api_client.fund_advance(
            advance["id"],
            fund_advance_payload(credit_line_version(line_id), "WIRE-C37"),
            CO,
        ),
        200,
    )
    assert funded["status"] == "FUNDED"
    assert funded["approved_advance_amount_cents"] == 3000000
    assert funded["effective_advance_rate_bps"] == 10000
    assert funded["invoice_age_days_at_funding"] == 0
    assert funded["rate_adjustment_codes"] == []
    assert str(funded["funded_at"]).startswith("2026-08-01T00:00:00")
    assert funded["funded_by_user_id"] == CO["X-User-ID"]

    settled_unit = read_unit(unit["id"])
    assert settled_unit["funding_status"] == "FLOORED"
    assert settled_unit["advance_amount_cents"] == 3000000
    assert settled_unit["outstanding_principal_cents"] == 3000000
    assert settled_unit["principal_paid_cents"] == 0
    assert str(settled_unit["floored_at"]).startswith("2026-08-01T00:00:00")

    settled_line = read_credit_line(line_id)
    assert settled_line["outstanding_principal_cents"] == 3000000
    assert settled_line["available_credit_cents"] == 497000000
    assert_credit_line_capacity_identity(settled_line)

    rows, meta = validate_paginated(
        api_client.list_curtailment_obligations(CO, params={"unit_id": unit["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "SCHEDULED"
    assert str(rows[0]["due_date"])[:10] == "2026-10-30"
    assert rows[0]["projected_principal_cents"] == 300000
