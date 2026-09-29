"""Version guards on the three guarded writes and the sanction disregard."""
from test_helpers import fiscal_officer_headers, work_specialist_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx


def _active_case_with_an_activated_assignment(api, name):
    """An ACTIVE case whose activity is ACTIVE and ready to carry funding."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=(),
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    return context, assignment["id"]


def test_replaying_a_consumed_case_version_on_an_authorization_is_refused(api):
    """PRD §2.7: "Creating a supportive service authorization requires
    `expected_case_version` in the request body, carrying the client's last observed
    `version` of the target `AssistanceCase`."
    PRD §2.7: "If it does not equal the case's current `version`, the request is rejected
    with `ERR_STALE_CASE_VERSION` (HTTP 412)."
    PRD §2.7: "A successful create increments the case's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_case_version_on_authorization_create_is_rejected
    """
    context, assignment_id = _active_case_with_an_activated_assignment(
        api, "Corner Stale Case Version Household"
    )
    observed = fx.case_version(api, context.case_id)
    first = fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        expected_case_version=observed,
        service_type="TRANSPORTATION",
        requested_amount_cents=10000,
        period_start="2026-08-01",
        period_end="2026-08-31",
    )

    response = api.create_supportive_authorization(
        factories.supportive_authorization_payload(
            context.case_id,
            assignment_id,
            observed,
            service_type="TRANSPORTATION",
            requested_amount_cents=10000,
            period_start="2026-09-01",
            period_end="2026-09-30",
        ),
        work_specialist_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_STALE_CASE_VERSION)
    assert len(fx.search_authorizations(api, case_id=context.case_id)) == 1
    refreshed = fx.case_version(api, context.case_id)
    assert refreshed == observed + 1

    second = fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        expected_case_version=refreshed,
        service_type="TRANSPORTATION",
        requested_amount_cents=10000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )

    asrt.assert_authorization(
        fx.read_authorization(api, second["id"]),
        status="REQUESTED",
        authorized_amount_cents=0,
    )
    asrt.assert_authorization(
        fx.read_authorization(api, first["id"]), status="REQUESTED"
    )


def test_an_episode_carrying_a_pre_authorization_case_version_is_refused(api):
    """PRD §2.7: "Creating a compliance episode likewise requires
    `expected_case_version` matching the target case's current `version`, and a mismatch
    is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."
    PRD §2.7: "This is the serialization point for the fiscal-year cap ledger and for
    compliance posture: another authorization may already have consumed the headroom the
    requester was sizing against, or a cascade may already have pushed the case into
    `CONCILIATION_PENDING`."
    PRD §3.7: "A successful referral puts the case's `compliance_status` into
    `CONCILIATION_PENDING` and increments the case's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_case_version_on_compliance_episode_create_is_rejected
    """
    context, assignment_id = _active_case_with_an_activated_assignment(
        api, "Corner Stale Episode Version Household"
    )
    observed = fx.case_version(api, context.case_id)
    authorization = fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        expected_case_version=observed,
        service_type="WORK_EXPENSE",
        requested_amount_cents=5000,
        period_start="2026-08-01",
        period_end="2026-08-31",
    )

    response = api.create_compliance_episode(
        factories.compliance_episode_payload(
            context.case_id, observed, allegation_reason="MISSED_APPOINTMENT"
        ),
        work_specialist_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_STALE_CASE_VERSION)
    assert fx.search_episodes(api, case_id=context.case_id) == []
    asrt.assert_case_state(
        fx.read_case(api, context.case_id), compliance_status="ASSIGNED"
    )
    asrt.assert_authorization(
        fx.read_authorization(api, authorization["id"]), status="REQUESTED"
    )


def test_replaying_a_consumed_claim_version_on_the_ledger_is_refused(api):
    """PRD §2.7: "Posting a recovery transaction requires `expected_overpayment_version`
    in the request body, carrying the client's last observed `version` of the target
    `Overpayment`."
    PRD §2.7: "If it does not equal the claim's current `version`, the request is rejected
    with `ERR_STALE_OVERPAYMENT_VERSION` (HTTP 412), because the balance the entry was
    sized against no longer holds."
    PRD §3.9: "The claim's `recoupment_status` becomes `ACTIVE` and the claim moves
    `ESTABLISHED → IN_RECOVERY`, or stays `IN_RECOVERY` on a subsequent entry, and each
    posting increments the claim's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_overpayment_version_on_recovery_transaction_is_rejected
    """
    context = fx.build_active_case(
        api,
        household_overrides={
            "head_of_household_name": "Corner Stale Overpayment Household"
        },
        incomes=(),
    )
    claim = fx.build_established_overpayment(
        api,
        context.case_id,
        claim_type="CLIENT_ERROR",
        months_covered=["2026-08"],
        computation_method="GROSS",
        gross_amount_cents=30000,
    )
    observed = fx.overpayment_version(api, claim["id"])
    first = fx.post_recovery(
        api,
        claim["id"],
        expected_overpayment_version=observed,
        method="CASH_PAYMENT",
        amount_cents=10000,
        applied_month="2026-09",
    )

    response = api.post_recovery_transaction(
        claim["id"],
        factories.recovery_transaction_payload(
            observed,
            method="CASH_PAYMENT",
            amount_cents=5000,
            applied_month="2026-10",
        ),
        fiscal_officer_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_STALE_OVERPAYMENT_VERSION)
    assert first["signed_amount_cents"] == 10000
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim["id"]),
        status="IN_RECOVERY",
        total_recovered_cents=10000,
        balance_cents=20000,
    )
    assert len(fx.list_recoveries(api, claim["id"])) == 1


def test_sanctioned_months_leave_the_denominator_but_not_the_caseload_credit(api):
    """PRD §3.10: "A case-month counts as sanctioned when the case has a compliance
    episode whose `sanction_imposed_month` is at or before that month and whose `status`
    is `SANCTION_IMPOSED` or `CURE_PENDING`."
    PRD §3.10: "The first three such months are removed from their raw denominators; the
    fourth sanctioned month and every later one *remains* in its denominator."
    PRD §3.10: "When the denominator is zero, `wpr_all_families_pct` is 0.00; otherwise
    it is the numerator divided by the denominator, expressed as a percentage, rounded
    half up to two decimal places."
    PRD §3.10: "The `current_caseload` figure is the total size of the *unadjusted* raw
    denominators from stage one across the quarter's three months, divided by three,
    rounded half up to two decimal places."
    PRD §3.10: "The `caseload_reduction_credit_pct` is that raw decline less the
    `eligibility_change_caseload_effect`, rounded half up to two decimal places, then
    floored at 0.00 and capped at 50.00."

    Design: Corner/cross_cutting_complexity_layers/sanctioned_case_months_drop_out_of_the_participation_denominator
    """
    context = fx.build_active_case(
        api,
        household_overrides={
            "head_of_household_name": "Corner Sanction Disregard Household"
        },
        incomes=(),
        certification_start_month="2026-10",
        benefit_months=("2026-10",),
    )
    episode = fx.open_episode(
        api, context.case_id, allegation_reason="REFUSED_ASSIGNMENT"
    )
    fx.start_conciliation(api, episode["id"])
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    fx.impose_sanction(api, episode["id"])
    fx.issue_months(api, context.case_id, ("2026-11", "2026-12"))
    period = fx.open_period(
        api,
        fiscal_year=2027,
        quarter=1,
        prior_year_caseload=2.00,
        eligibility_change_caseload_effect=0.00,
    )

    fx.calculate_period(api, period["id"])

    imposed = fx.read_episode(api, episode["id"])
    assert imposed["status"] == "SANCTION_IMPOSED"
    assert imposed["sanction_imposed_month"] == "2026-10"
    asrt.assert_case_state(fx.read_case(api, context.case_id), benefit_status="ACTIVE")
    stored = fx.read_period(api, period["id"])
    assert stored["status"] == "CALCULATED"
    asrt.assert_pct(stored["wpr_all_families_pct"], 0.00, "wpr_all_families_pct")
    asrt.assert_pct(stored["wpr_two_parent_pct"], 0.00, "wpr_two_parent_pct")
    asrt.assert_pct(stored["current_caseload"], 1.00, "current_caseload")
    asrt.assert_pct(
        stored["caseload_reduction_credit_pct"], 50.00, "caseload_reduction_credit_pct"
    )
    asrt.assert_pct(
        stored["adjusted_target_all_families_pct"],
        0.00,
        "adjusted_target_all_families_pct",
    )
    assert stored["target_met"] is True
