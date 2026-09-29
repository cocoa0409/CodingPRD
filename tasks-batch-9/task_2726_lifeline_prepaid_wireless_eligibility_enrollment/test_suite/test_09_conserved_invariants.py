"""Two conserved quantities restored by their compensating action: money and physical units."""

from test_helpers import (
    AUDITOR_ADJUDICATOR_ID,
    PROGRAM_ADMIN_ID,
    assert_audit_sample,
    assert_de_enrollment_cascade,
    assert_device,
    assert_device_counters,
    assert_instant,
    assert_instant_null,
    assert_ledger_tuple,
    assert_subscriber_case,
    expected_recoupment,
    fixtures as fx,
)

BENEFIT_START = "2026-06-01T00:00:00Z"
JUNE_FILING = "2026-07-02T00:00:00Z"
JULY_FILING = "2026-08-02T00:00:00Z"

DEVICE_CLOCK = "2026-08-01T00:00:00Z"


def _carrier_with_two_filed_claims(api):
    """Two full-month 1850 cent claims filed a month apart, both benefits still ACTIVE."""
    fx.set_clock(api, BENEFIT_START)
    provider = fx.register_provider(api)

    benefits = []
    for index in (1, 2):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        enrollment = fx.enroll(
            api,
            provider,
            applicant["subscriber"],
            applicant["check"],
            address,
            service_type="VOICE",
            benefit_start_date=BENEFIT_START,
        )
        benefits.append(
            {
                "address": address,
                "subscriber": applicant["subscriber"],
                "enrollment": enrollment,
            }
        )

    fx.set_clock(api, JUNE_FILING)
    june = fx.file_claim(api, fx.draft_claim(api, provider, "2026-06")["id"], provider)
    fx.set_clock(api, JULY_FILING)
    july = fx.file_claim(api, fx.draft_claim(api, provider, "2026-07")["id"], provider)

    assert june["final_amount_cents"] == 1850, (
        f"30 of 30 days on two voice lines, got {june['final_amount_cents']}"
    )
    assert july["final_amount_cents"] == 1850, (
        f"31 of 31 days on two voice lines, got {july['final_amount_cents']}"
    )
    return {
        "provider": provider,
        "june": june,
        "july": july,
        "first": benefits[0],
        "second": benefits[1],
    }


def _audit_failure_with_an_appeal_under_review(api):
    """The June claim fails one of two samples, stopping E1, whose appeal is then assigned."""
    context = _carrier_with_two_filed_claims(api)
    ledger_before = fx.refresh_provider(api, context["provider"]["id"])
    assert_ledger_tuple(ledger_before, 3700, 0, 3700, False)

    samples = fx.draw_samples(api, context["june"]["id"], sample_size=2)
    fx.adjudicate(
        api,
        samples[0]["id"],
        finding="INELIGIBLE_SUBSCRIBER",
        finding_note="income proof unverifiable",
    )

    case = fx.file_case(
        api,
        context["first"]["subscriber"]["id"],
        context["first"]["enrollment"]["id"],
        case_type="DE_ENROLLMENT_APPEAL",
        narrative="I filed my income documents on time and remain eligible",
    )
    fx.assign_review(api, case["id"], reviewer_ref="REV-1")

    context["samples"] = samples
    context["case"] = case
    context["ledger_before"] = ledger_before
    return context


def test_the_granted_appeal_restores_all_four_ledger_figures_exactly(api):
    """The money the audit took back is returned with no residual drift anywhere.

    PRD: "When a granted appeal reverses an audit failure, all four ledger figures must
    return to precisely the values they held before the adjudication."

    Design: Difficulty/compensating_invariant/provider_money_ledger_restored_byte_for_byte_by_appeal_reinstatement
    """
    context = _audit_failure_with_an_appeal_under_review(api)
    provider_id = context["provider"]["id"]

    during = fx.refresh_provider(api, provider_id)
    assert_ledger_tuple(during, 3700, 1018, 2682, True)
    assert expected_recoupment(1850, 1, 2)["recoupment_amount_cents"] == 1018
    assert fx.refresh_claim(api, context["june"]["id"])["status"] == "AUDIT_FAILED"
    assert fx.refresh_claim(api, context["july"]["id"])["status"] == "HELD", (
        "the hold flag swept the carrier's other filed claim aside"
    )

    fx.decide_case(
        api,
        context["case"]["id"],
        "GRANT_REINSTATE",
        rationale="documentation located in the verifier queue; eligibility confirmed",
    )

    after = fx.refresh_provider(api, provider_id)
    assert_ledger_tuple(after, 3700, 0, 3700, False)
    for field in (
        "claim_gross_cents",
        "recouped_cents",
        "net_reimbursed_cents",
        "audit_hold_flag",
    ):
        assert after[field] == context["ledger_before"][field], (
            f"{field} drifted: {context['ledger_before'][field]} became {after[field]}"
        )

    assert fx.refresh_claim(api, context["july"]["id"])["status"] == "FILED", (
        "the collateral hold is lifted with the flag that caused it"
    )


def test_the_reversal_unwinds_the_sample_the_claim_and_the_benefit_together(api):
    """The compensation reaches the failing sample, its owning claim and the stopped benefit.

    PRD: "The newest `ADJUDICATED_FAIL` sample for that benefit — when several exist, the one
    with the greatest `created_at` — moves `ADJUDICATED_FAIL → ADJUDICATED_PASS` with its
    `finding` rewritten to `COMPLIANT` and its `disallowed_support_cents` returned to 0, and
    the owning claim's `failed_sample_count` is recomputed."

    Design: Difficulty/compensating_invariant/provider_money_ledger_restored_byte_for_byte_by_appeal_reinstatement
    """
    context = _audit_failure_with_an_appeal_under_review(api)
    failing, untouched = context["samples"][0], context["samples"][1]
    enrollment_id = context["first"]["enrollment"]["id"]

    assert_audit_sample(failing)
    assert failing["enrollment_id"] == enrollment_id, (
        "the earlier benefit ranks first on equal risk scores"
    )
    assert failing["selection_rank"] == 1
    assert failing["claimed_line_cents"] == 925
    assert untouched["selection_rank"] == 2
    assert fx.refresh_sample(api, untouched["id"])["status"] == "DRAWN", (
        "only the adjudicated sample moves"
    )
    assert_de_enrollment_cascade(
        fx.refresh_enrollment(api, enrollment_id),
        "AUDIT_INELIGIBLE",
        JULY_FILING,
        AUDITOR_ADJUDICATOR_ID,
    )

    case = fx.decide_case(
        api,
        context["case"]["id"],
        "GRANT_REINSTATE",
        rationale="documentation located in the verifier queue; eligibility confirmed",
    )
    assert_subscriber_case(case)
    assert case["status"] == "GRANTED"
    assert case["decision"] == "GRANT_REINSTATE"
    assert case["review_round"] == 1
    assert case["reviewer_ref"] == "REV-1"
    assert case["decided_by_ref"] == PROGRAM_ADMIN_ID
    assert case["reinstated_enrollment_flag"] is True

    reversed_sample = fx.refresh_sample(api, failing["id"])
    assert reversed_sample["status"] == "ADJUDICATED_PASS", (
        f"the overturned finding flips the sample, got {reversed_sample['status']}"
    )
    assert reversed_sample["finding"] == "COMPLIANT"
    assert reversed_sample["disallowed_support_cents"] == 0

    claim = fx.refresh_claim(api, context["june"]["id"])
    assert claim["status"] == "AUDIT_PASSED", (
        f"zero failing samples carries the claim to AUDIT_PASSED, got {claim['status']}"
    )
    assert claim["failed_sample_count"] == 0
    assert claim["audit_sample_count"] == 2, "the drawn samples are not discarded"
    assert claim["recoupment_amount_cents"] == 0
    assert claim["penalty_cents"] == 0
    assert claim["final_amount_cents"] == 1850, "the gross figure never moved"
    assert claim["net_payable_cents"] == 1850

    benefit = fx.refresh_enrollment(api, enrollment_id)
    assert benefit["benefit_status"] == "ACTIVE"
    assert benefit["de_enrollment_reason"] is None
    assert_instant_null(benefit["benefit_end_date"], "benefit_end_date")
    assert_instant_null(benefit["de_enrolled_at"], "de_enrolled_at")
    assert benefit["de_enrolled_by_ref"] is None
    assert_instant_null(benefit["appeal_deadline_at"], "appeal_deadline_at")
    assert_instant(benefit["benefit_start_date"], BENEFIT_START, "benefit_start_date")
    assert benefit["reinstatement_count"] == 1
    assert benefit["recert_status"] == "NOT_DUE"
    assert benefit["usage_status"] == "PENDING_FIRST_USE"

    assert (
        fx.refresh_subscriber(api, context["first"]["subscriber"]["id"])["status"]
        == "ENROLLED"
    )
    assert fx.refresh_address(api, context["first"]["address"]["id"])["occupied_benefit_slots"] == 1
    assert fx.refresh_provider(api, context["provider"]["id"])["active_enrollment_count"] == 2


def _carrier_with_three_handsets_and_one_bare_benefit(api):
    """Three in-stock handsets, D1 and D2 identical BASIC units and D3 a cheaper STANDARD."""
    fx.set_clock(api, DEVICE_CLOCK)
    provider = fx.register_provider(api)
    first, second, third = fx.stock_devices(
        api, provider, [("BASIC", 2100), ("BASIC", 2100), ("STANDARD", 1200)]
    )
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    enrollment = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=DEVICE_CLOCK,
    )
    assert enrollment["device_status"] == "AWAITING_DEVICE"
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "first": first,
        "second": second,
        "third": third,
        "enrollment": enrollment,
    }


def test_the_five_counters_return_to_their_opening_tuple_after_a_good_return(api):
    """Sampled at all four points of the reclaim cycle, the partition closes where it opened.

    PRD: "Issuing a handset and then taking it back in good condition must restore all five
    counters to the values they held before the issuance; taking it back damaged or lost
    instead leaves the total unchanged but does not return the unit to stock."

    Design: Difficulty/compensating_invariant/device_inventory_partition_conserved_across_issue_reclaim_return_cycle
    """
    context = _carrier_with_three_handsets_and_one_bare_benefit(api)
    provider_id = context["provider"]["id"]

    opening = fx.refresh_provider(api, provider_id)
    assert_device_counters(opening, 3, 3, 0, 0, 0)

    fx.issue_device(api, context["enrollment"]["id"], context["provider"])
    assert_device_counters(fx.refresh_provider(api, provider_id), 3, 2, 1, 0, 0)

    fx.de_enroll(
        api,
        context["enrollment"]["id"],
        reason="SUBSCRIBER_REQUEST",
        headers=context["agent"],
        note="moving in with family",
    )
    assert_device_counters(fx.refresh_provider(api, provider_id), 3, 2, 0, 1, 0)

    fx.return_device(api, context["first"]["id"], return_condition="GOOD")
    closing = fx.refresh_provider(api, provider_id)
    assert_device_counters(closing, 3, 3, 0, 0, 0)

    for field in (
        "devices_total_count",
        "devices_in_stock_count",
        "devices_issued_count",
        "devices_reclaim_pending_count",
        "devices_retired_count",
    ):
        assert closing[field] == opening[field], (
            f"{field} drifted: {opening[field]} became {closing[field]}"
        )


def test_the_reclaim_cycle_routes_one_handset_without_ever_deleting_a_row(api):
    """Custody walks IN_STOCK to ISSUED to RECLAIM_PENDING and back while the total holds at 3.

    PRD: "A carrier with three handsets in stock reads 3 / 0 / 0 / 0 with a total of 3; after
    one issuance, 2 / 1 / 0 / 0 with a total of 3; after that benefit is de-enrolled and the
    handset reclaimed, 2 / 0 / 1 / 0 with a total of 3; after the handset comes back
    `DAMAGED`, 2 / 0 / 0 / 1 with a total of 3."

    Design: Difficulty/compensating_invariant/device_inventory_partition_conserved_across_issue_reclaim_return_cycle
    """
    context = _carrier_with_three_handsets_and_one_bare_benefit(api)
    enrollment_id = context["enrollment"]["id"]

    fx.issue_device(api, enrollment_id, context["provider"])
    picked = fx.refresh_device(api, context["first"]["id"])
    assert_device(picked)
    assert picked["status"] == "ISSUED", (
        "two identical BASIC units tie on cost, so the older row is selected"
    )
    assert picked["issued_enrollment_id"] == enrollment_id
    assert_instant(picked["issued_at"], DEVICE_CLOCK, "issued_at")
    assert fx.refresh_device(api, context["second"]["id"])["status"] == "IN_STOCK"
    assert fx.refresh_device(api, context["third"]["id"])["status"] == "IN_STOCK"
    assert fx.refresh_enrollment(api, enrollment_id)["device_status"] == "DEVICE_ISSUED"

    fx.de_enroll(
        api,
        enrollment_id,
        reason="SUBSCRIBER_REQUEST",
        headers=context["agent"],
        note="moving in with family",
    )
    reclaimed = fx.refresh_device(api, context["first"]["id"])
    assert reclaimed["status"] == "RECLAIM_PENDING", (
        f"stopping the benefit reclaims the handset, got {reclaimed['status']}"
    )
    assert_instant_null(reclaimed["returned_at"], "returned_at")
    assert reclaimed["return_condition"] is None
    stopped = fx.refresh_enrollment(api, enrollment_id)
    assert stopped["device_status"] == "RECLAIM_PENDING"
    assert stopped["benefit_status"] == "DE_ENROLLED"

    fx.return_device(api, context["first"]["id"], return_condition="GOOD")
    restocked = fx.refresh_device(api, context["first"]["id"])
    assert restocked["status"] == "IN_STOCK", (
        f"a GOOD return re-enters stock, got {restocked['status']}"
    )
    assert restocked["return_condition"] == "GOOD"
    assert_instant(restocked["returned_at"], DEVICE_CLOCK, "returned_at")

    settled = fx.refresh_enrollment(api, enrollment_id)
    assert settled["device_status"] == "AWAITING_DEVICE"
    assert settled["device_issuance_count"] == 1, (
        f"one handset was issued across the whole cycle, got {settled['device_issuance_count']}"
    )
    assert settled["benefit_status"] == "DE_ENROLLED", "the return does not revive the benefit"
    assert fx.refresh_provider(api, context["provider"]["id"])["devices_total_count"] == 3
