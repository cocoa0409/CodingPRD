"""Exemption applications and abatement agreements: program gates, interval
overlap semantics, the compliance cycle, and the termination clawback."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_abatement_agreement,
    assert_bill_allocation_invariant,
    assert_date_is,
    audit_event_types,
    client_headers_for,
    create_abatement_payload,
    create_compliance_payload,
    create_disposal_payload,
    create_exemption_application_payload,
    create_notice_payload,
    create_payment_schedule_payload,
    create_review_payload,
    create_tax_bill_payload,
    file_it,
    find_installment,
    generate,
    list_audit_events,
    open_rendition,
    setup_abated_asset,
    setup_approved_exemption,
    setup_classified_asset,
    api_client,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["assessor_clerk_headers"]


def test_exemption_program_unavailable_beats_cap_exceeded(api):
    """PRD §3.7: "Three program gates apply at creation, in §2.9 order: the
    asset's jurisdiction must list the requested type in its
    `offered_exemption_types` (otherwise `ERR_EXEMPTION_PROGRAM_UNAVAILABLE`,
    HTTP 422); the requested percentage may not exceed the jurisdiction's
    `max_exemption_pct` (otherwise `ERR_EXEMPTION_CAP_EXCEEDED`, HTTP 422)" and
    PRD §2.9: "Incoming requests are checked against a fixed, ascending sequence
    of rules, and the first failing rule determines the error response — earlier
    checks mask later ones."

    Design: Difficulty/priority_pair_validation_conflict/exemption_program_beats_exemption_cap
    """
    ctx = setup_classified_asset(
        jurisdiction_overrides={"offered_exemption_types": ["HISTORIC"],
                                "max_exemption_pct": 40},
        asset_overrides={"asset_tag": "X1"},
        classify_asset=False,
    )
    # Both gates fail: FREEPORT is not offered AND 90 > 40. The program
    # availability gate (rule 14) precedes the ceiling gate (rule 28).
    res = api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=90,
            effective_date="2027-01-01", expiration_date="2028-01-01"),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_EXEMPTION_PROGRAM_UNAVAILABLE,
                   expected_status=422)


def test_exemption_cap_exceeded_fires_in_isolation(api):
    """PRD §3.7: "the requested percentage may not exceed the jurisdiction's
    `max_exemption_pct` (otherwise `ERR_EXEMPTION_CAP_EXCEEDED`, HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/exemption_program_beats_exemption_cap
    """
    ctx = setup_classified_asset(
        jurisdiction_overrides={"offered_exemption_types": ["FREEPORT"],
                                "max_exemption_pct": 40},
        asset_overrides={"asset_tag": "X2"},
        classify_asset=False,
    )
    res = api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=90,
            effective_date="2027-01-01", expiration_date="2028-01-01"),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_EXEMPTION_CAP_EXCEEDED, expected_status=422)


def test_exemption_submit_blocked_by_disposed_asset(api):
    """PRD §3.7: "A `TaxAnalyst` submits a `DRAFT` application, moving it to
    `SUBMITTED`; submission is gated cross-entity on the asset, so submitting an
    application whose linked asset is `DISPOSED` is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/cross_entity_state_dependency/exemption_submit_blocked_by_disposed_asset
    """
    ctx = setup_classified_asset(asset_overrides={"asset_tag": "V1"},
                                 classify_asset=False)
    application = validate_success(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=30,
            effective_date="2027-01-01", expiration_date="2028-01-01"),
        ctx["analyst"]["headers"]), 201)
    validate_success(api_client.create_disposal(
        ctx["asset"]["id"],
        create_disposal_payload(disposal_date="2026-07-15",
                                disposal_proceeds_cents=0),
        ctx["analyst"]["headers"]), 201)

    res = api_client.submit_exemption_application(application["id"],
                                                  ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    after = validate_success(api_client.get_exemption_application(
        application["id"], ctx["analyst"]["headers"]), 200)
    assert after["application_status"] == "DRAFT"


def test_exemption_submit_succeeds_after_disposal_reversed(api):
    """PRD §3.7: "A `TaxAnalyst` submits a `DRAFT` application, moving it to
    `SUBMITTED`; submission is gated cross-entity on the asset, so submitting an
    application whose linked asset is `DISPOSED` is rejected with
    `ERR_INVALID_STATE_TRANSITION`." and PRD §3.3: "reversing restores the asset
    from `DISPOSED` to `ACTIVE`, clears `disposed_date` and
    `disposal_proceeds_cents`, moves the addressed record to `REVERSED`"

    Design: Difficulty/cross_entity_state_dependency/exemption_submit_blocked_by_disposed_asset
    """
    ctx = setup_classified_asset(asset_overrides={"asset_tag": "V1"},
                                 classify_asset=False)
    application = validate_success(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=30,
            effective_date="2027-01-01", expiration_date="2028-01-01"),
        ctx["analyst"]["headers"]), 201)
    disposal = validate_success(api_client.create_disposal(
        ctx["asset"]["id"],
        create_disposal_payload(disposal_date="2026-07-15",
                                disposal_proceeds_cents=0),
        ctx["analyst"]["headers"]), 201)
    validate_success(api_client.reverse_disposal(disposal["id"],
                                                 ctx["analyst"]["headers"]), 200)

    submitted = validate_success(api_client.submit_exemption_application(
        application["id"], ctx["analyst"]["headers"]), 200)
    assert submitted["application_status"] == "SUBMITTED", (
        "with the asset ACTIVE again, the cross-entity gate lifts"
    )


def test_abatement_shared_endpoint_year_overlaps(api):
    """PRD §3.7: "No other agreement for the same asset in `ACTIVE` or
    `RECERTIFICATION_DUE` status may have a covered-year interval intersecting the
    requested one — and because the intervals are closed, sharing even a single
    endpoint year counts as an intersection — (otherwise `ERR_ABATEMENT_OVERLAP`,
    HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/abatement_closed_year_interval_overlap
    """
    ctx = setup_abated_asset(
        asset_overrides={"asset_tag": "AA"},
        abatement_overrides={"first_tax_year": 2027, "last_tax_year": 2031,
                             "abatement_pct": 50},
        classify_asset=False,
    )
    assert ctx["abatement"]["agreement_status"] == "ACTIVE"

    res = api_client.create_abatement(
        ctx["asset"]["id"],
        create_abatement_payload(first_tax_year=2031, last_tax_year=2035,
                                 abatement_pct=25),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_ABATEMENT_OVERLAP, expected_status=409)


def test_abatement_interval_after_inclusive_end_accepted(api):
    """PRD §3.7: "No other agreement for the same asset in `ACTIVE` or
    `RECERTIFICATION_DUE` status may have a covered-year interval intersecting the
    requested one — and because the intervals are closed, sharing even a single
    endpoint year counts as an intersection" and "A new agreement starts `ACTIVE`,
    with `last_recertified_year` initialized to `first_tax_year`."

    Design: Difficulty/resource_temporal_overlap/abatement_closed_year_interval_overlap
    """
    ctx = setup_abated_asset(
        asset_overrides={"asset_tag": "AA"},
        abatement_overrides={"first_tax_year": 2027, "last_tax_year": 2031,
                             "abatement_pct": 50},
        classify_asset=False,
    )
    created = validate_success(api_client.create_abatement(
        ctx["asset"]["id"],
        create_abatement_payload(first_tax_year=2032, last_tax_year=2036,
                                 abatement_pct=25),
        ctx["analyst"]["headers"]), 201)
    assert_abatement_agreement(created)
    assert created["agreement_status"] == "ACTIVE"
    assert created["last_recertified_year"] == 2032

    agreements = validate_success(api_client.list_abatements(
        ctx["asset"]["id"], ctx["analyst"]["headers"]), 200)
    assert len(agreements) == 2


def test_exemption_touching_half_open_endpoints_disjoint(api):
    """PRD §3.7: "no other application for the same asset and the same
    `exemption_type` in `SUBMITTED`, `APPROVED`, or `SUSPENDED` status may have an
    effective period intersecting the requested one — with the half-open
    convention, one application's `expiration_date` exactly equal to the other's
    `effective_date` does not count as an intersection — (otherwise
    `ERR_EXEMPTION_PERIOD_OVERLAP`, HTTP 409). A new application starts in `DRAFT`
    status."

    Design: Difficulty/resource_temporal_overlap/exemption_half_open_date_interval_overlap
    """
    ctx = setup_classified_asset(asset_overrides={"asset_tag": "AE"},
                                 classify_asset=False)
    first = validate_success(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=30,
            effective_date="2026-01-01", expiration_date="2028-01-01"),
        ctx["analyst"]["headers"]), 201)
    validate_success(api_client.submit_exemption_application(
        first["id"], ctx["analyst"]["headers"]), 200)

    # effective_date == prior expiration_date: disjoint under half-open semantics.
    second = validate_success(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=20,
            effective_date="2028-01-01", expiration_date="2029-01-01"),
        ctx["analyst"]["headers"]), 201)
    assert second["application_status"] == "DRAFT"


def test_exemption_overlapping_half_open_period_rejected(api):
    """PRD §3.7: "no other application for the same asset and the same
    `exemption_type` in `SUBMITTED`, `APPROVED`, or `SUSPENDED` status may have an
    effective period intersecting the requested one — with the half-open
    convention, one application's `expiration_date` exactly equal to the other's
    `effective_date` does not count as an intersection — (otherwise
    `ERR_EXEMPTION_PERIOD_OVERLAP`, HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/exemption_half_open_date_interval_overlap
    """
    ctx = setup_classified_asset(asset_overrides={"asset_tag": "AE"},
                                 classify_asset=False)
    first = validate_success(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=30,
            effective_date="2026-01-01", expiration_date="2028-01-01"),
        ctx["analyst"]["headers"]), 201)
    validate_success(api_client.submit_exemption_application(
        first["id"], ctx["analyst"]["headers"]), 200)

    # 2027-12-31 lies inside [2026-01-01, 2028-01-01): a real intersection.
    res = api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(
            exemption_type="FREEPORT", exemption_pct=20,
            effective_date="2027-12-31", expiration_date="2028-12-31"),
        ctx["analyst"]["headers"])
    validate_error(res, ApiErrorId.ERR_EXEMPTION_PERIOD_OVERLAP,
                   expected_status=409)


def test_exemption_suspend_reinstate_cycle(api):
    """PRD §3.7: "When a compliance failure is found, an `AssessorClerk` suspends
    the certificate with a compliance `action` of `SUSPEND`: the application moves
    from `APPROVED` to `SUSPENDED`, the `suspended_date` is set to the current
    clock date, the exemption stops reducing bill validation while suspended, and
    `EXEMPTION_SUSPENDED` is appended. Reinstatement with an `action` of
    `REINSTATE` moves a `SUSPENDED` application back to `APPROVED`, clears the
    `suspended_date`, and restores the exemption's effect on bill validation."

    Design: Corner/state_machines/exemption_suspend_reinstate_cycle
    """
    ctx = setup_approved_exemption(
        asset_overrides={"asset_tag": "CE1"},
        exemption_overrides={"exemption_pct": 30},
    )
    assert ctx["exemption"]["application_status"] == "APPROVED"

    suspended = validate_success(api_client.exemption_compliance(
        ctx["exemption"]["id"], create_compliance_payload("SUSPEND"), CLERK), 200)
    assert suspended["application_status"] == "SUSPENDED"
    # The clock has never been set: it stands at the default 2026-08-01 (§2.5).
    assert_date_is(suspended["suspended_date"], "2026-08-01", "suspended_date")

    events = list_audit_events(ctx["client"]["id"])
    assert "EXEMPTION_SUSPENDED" in audit_event_types(events)

    reinstated = validate_success(api_client.exemption_compliance(
        ctx["exemption"]["id"], create_compliance_payload("REINSTATE"), CLERK), 200)
    assert reinstated["application_status"] == "APPROVED"
    assert reinstated.get("suspended_date") is None


def test_abatement_termination_clawback_revalidates_bill(api):
    """PRD §3.7: "An `AssessorClerk` may terminate an agreement in `ACTIVE` or
    `RECERTIFICATION_DUE` status, moving it to `TERMINATED`. The abatement
    immediately stops reducing bill validation, and every tax bill in `MATCHED` or
    `DISCREPANCY` status whose notice's rendition covers the abated asset's
    (client, jurisdiction) pair and whose tax year falls within the agreement's
    covered interval is revalidated under §3.6's computation, the clawback landing
    in `validated_amount_cents`; each revalidated bill cancels its `SCHEDULED` or
    `LATE` installments and resets `unscheduled_amount_cents` per the bill cascade
    rule of §3.5." and "`ABATEMENT_TERMINATED` closes the sequence."

    Design: Corner/cross_cutting_complexity_layers/abatement_termination_clawback_revalidates_bill
    """
    ctx = setup_abated_asset(
        rule_overrides={"percent_good_vector": [100, 100]},
        asset_overrides={"asset_tag": "CW1", "acquisition_cost_cents": 800000},
        abatement_overrides={"first_tax_year": 2027, "last_tax_year": 2031,
                             "abatement_pct": 50},
        with_manager=True,
    )
    rendition = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"], 2027,
                               ctx["analyst"]["headers"])
    generate(rendition["id"], ctx["analyst"]["headers"])
    file_it(rendition["id"], ctx["analyst"]["headers"])
    notice = validate_success(api_client.create_notice(
        rendition["id"],
        create_notice_payload(notice_value_cents=800000,
                              protest_deadline_date="2028-06-01"),
        CLERK), 201)
    validate_success(api_client.accept_notice(notice["id"],
                                              ctx["analyst"]["headers"]), 200)
    bill = validate_success(api_client.create_tax_bill(
        notice["id"],
        create_tax_bill_payload(billed_amount_cents=10000, tax_rate=0.025,
                                due_date="2027-06-30"),
        ctx["analyst"]["headers"]), 201)
    bill = validate_success(api_client.validate_bill(
        bill["id"], ctx["manager"]["headers"]), 200)
    # 20000 gross - min(round(round(800000 * 50/100) * 0.025), 20000) = 10000.
    assert bill["validated_amount_cents"] == 10000
    assert bill["validation_status"] == "MATCHED"
    bill = validate_success(api_client.create_payment_schedule(
        bill["id"], create_payment_schedule_payload(installment_count=2),
        ctx["analyst"]["headers"]), 200)
    assert [i["amount_cents"] for i in bill["installments"]] == [5000, 5000]
    validate_success(api_client.pay_installment(
        bill["id"], {"installment_no": 1}, client_headers_for(ctx["client"])), 200)

    terminated = validate_success(api_client.terminate_abatement(
        ctx["abatement"]["id"], CLERK), 200)
    assert terminated["agreement_status"] == "TERMINATED"

    bill = validate_success(api_client.get_tax_bill(bill["id"],
                                                    ctx["analyst"]["headers"]), 200)
    assert bill["validated_amount_cents"] == 20000, "clawback removes the credit"
    assert bill["validation_status"] == "DISCREPANCY"
    assert bill["variance_cents"] == -10000, "10000 billed - 20000 validated"
    assert find_installment(bill, 1)["installment_status"] == "PAID"
    assert find_installment(bill, 2)["installment_status"] == "CANCELLED"
    assert bill["unscheduled_amount_cents"] == 15000, "20000 - 5000 paid"
    assert bill["payment_status"] == "PARTIALLY_PAID"
    assert_bill_allocation_invariant(bill)

    events = list_audit_events(ctx["client"]["id"])
    assert "ABATEMENT_TERMINATED" in audit_event_types(events)
    assert "BILL_REVALIDATED" in audit_event_types(events)
