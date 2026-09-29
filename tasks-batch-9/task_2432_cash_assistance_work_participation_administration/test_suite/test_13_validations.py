"""Guards that turn an otherwise well-formed request into a business refusal."""
from test_helpers import caseworker_headers, fiscal_officer_headers, supervisor_headers
from test_helpers import work_specialist_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx


def _active_case_with_an_august_assignment(api, name):
    """An ACTIVE case whose community-service activity runs August to December."""
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


def test_a_second_report_for_the_same_assignment_month_is_refused(api):
    """PRD §3.6: "A report duplicating an existing `SUBMITTED` or `VERIFIED` report for
    the same assignment and the same reported month is refused with
    `ERR_DUPLICATE_REPORT_MONTH`; a previously `REJECTED` report for that month does not
    block a replacement."
    PRD §3.6: "The report opens in `status` `SUBMITTED` with `verified_hours` null,
    `core_hours_credited` and `non_core_hours_credited` both 0, and `rejection_reason`
    null."

    Design: Corner/validations/second_report_for_the_same_assignment_month_is_refused
    """
    _context, assignment_id = _active_case_with_an_august_assignment(
        api, "Corner Duplicate Report Household"
    )
    first = fx.file_report(
        api,
        assignment_id,
        report_month="2026-08",
        reported_hours=40,
        verification_source="TIMESHEET",
    )

    response = api.file_participation_report(
        assignment_id,
        factories.participation_report_payload(
            report_month="2026-08",
            reported_hours=60,
            verification_source="EMPLOYER_ATTESTATION",
        ),
        caseworker_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_DUPLICATE_REPORT_MONTH)
    rows = fx.list_reports(api, assignment_id)
    assert len(rows) == 1
    stored = fx.read_report(api, assignment_id, first["id"])
    assert stored["reported_hours"] == 40
    assert stored["status"] == "SUBMITTED"


def test_a_report_month_beginning_on_the_assignment_end_date_is_outside_it(api):
    """PRD §3.6: "The reported month must actually intersect the assignment's half-open
    interval, and the test is specific: the first calendar day of the reported month must
    fall strictly before the assignment's `end_date`, and the last calendar day of the
    reported month must fall on or after the assignment's `start_date`."
    PRD §3.6: "A month failing either half is refused with
    `ERR_REPORT_MONTH_OUTSIDE_ASSIGNMENT`."

    Design: Corner/validations/report_month_starting_on_the_assignment_end_date_is_refused
    """
    _context, assignment_id = _active_case_with_an_august_assignment(
        api, "Corner Outside Range Household"
    )

    response = api.file_participation_report(
        assignment_id,
        factories.participation_report_payload(
            report_month="2026-12", reported_hours=80, verification_source="TIMESHEET"
        ),
        work_specialist_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_REPORT_MONTH_OUTSIDE_ASSIGNMENT)

    november = fx.file_report(
        api,
        assignment_id,
        report_month="2026-11",
        reported_hours=80,
        verification_source="TIMESHEET",
    )

    stored = fx.read_report(api, assignment_id, november["id"])
    assert stored["report_month"] == "2026-11"
    assert stored["status"] == "SUBMITTED"
    assert len(fx.list_reports(api, assignment_id)) == 1


def test_the_ledger_refuses_an_entry_over_the_balance_and_a_reversal_over_the_total(api):
    """PRD §3.9: "Two amount guards then apply: any entry whose method is not
    `RECOUPMENT_REVERSAL` may not exceed the claim's current `balance_cents`, and one
    that does is refused with `ERR_RECOVERY_EXCEEDS_BALANCE`; a `RECOUPMENT_REVERSAL`
    may not exceed the claim's current `total_recovered_cents`, and one that does is
    refused with `ERR_REVERSAL_EXCEEDS_RECOVERED`."
    PRD §3.9: "When the balance reaches exactly zero after an entry, the claim moves
    `IN_RECOVERY → SATISFIED` and its `recoupment_status` returns to `NOT_STARTED`."

    Design: Corner/validations/ledger_guards_refuse_over_recovery_and_over_reversal_amounts
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Ledger Guard Household"},
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

    over_balance = api.post_recovery_transaction(
        claim["id"],
        factories.recovery_transaction_payload(
            fx.overpayment_version(api, claim["id"]),
            method="TAX_INTERCEPT",
            amount_cents=30001,
            applied_month="2026-09",
        ),
        fiscal_officer_headers(),
    )

    asrt.assert_rejected(over_balance, errs.ERR_RECOVERY_EXCEEDS_BALANCE)
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim["id"]),
        status="ESTABLISHED",
        balance_cents=30000,
    )

    settled = fx.post_recovery(
        api,
        claim["id"],
        method="TAX_INTERCEPT",
        amount_cents=30000,
        applied_month="2026-09",
    )

    assert settled["signed_amount_cents"] == 30000
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim["id"]),
        status="SATISFIED",
        recoupment_status="NOT_STARTED",
        total_recovered_cents=30000,
        balance_cents=0,
    )

    over_reversal = api.post_recovery_transaction(
        claim["id"],
        factories.recovery_transaction_payload(
            fx.overpayment_version(api, claim["id"]),
            method="RECOUPMENT_REVERSAL",
            amount_cents=30001,
            applied_month="2026-10",
        ),
        fiscal_officer_headers(),
    )

    asrt.assert_rejected(over_reversal, errs.ERR_REVERSAL_EXCEEDS_RECOVERED)
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim["id"]),
        status="SATISFIED",
        total_recovered_cents=30000,
    )
    assert len(fx.list_recoveries(api, claim["id"])) == 1


def test_a_grant_that_would_pass_the_twelve_month_hardship_allowance_is_refused(api):
    """PRD §3.4: "Two arithmetic guards then apply and both surface as
    `ERR_EXTENSION_LIMIT_EXCEEDED`: the granted figure must be at least 1 and no greater
    than the `months_requested` figure, and the household's existing
    `extension_months_used` plus the granted figure must not exceed the lifetime hardship
    allowance of 12 months."
    PRD §3.4: "`extension_months_used` is the number of those rows whose non-countable
    reason is `GRANTED_EXTENSION`."
    PRD §3.4: "The new request opens in `status` `REQUESTED` with `months_granted` at 0,
    `last_effective_month` null, and `denial_reason`, `revocation_reason` and
    `decided_by_user_id` all null."

    Design: Corner/validations/extension_grant_beyond_the_twelve_month_hardship_cap_is_refused
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Extension Cap Household"},
        incomes=(),
        benefit_months=fx.consecutive_months("2026-08", 13),
    )
    first = fx.request_extension(
        api,
        context.case_id,
        extension_type="HARDSHIP_LOCAL_LABOR_MARKET",
        months_requested=12,
        first_effective_month="2026-08",
    )
    second = fx.request_extension(
        api,
        context.case_id,
        extension_type="HARDSHIP_CARETAKER",
        months_requested=1,
        first_effective_month="2027-09",
    )

    fx.grant_extension(api, first["id"], 12)

    granted = fx.read_extension(api, context.case_id, first["id"])
    assert granted["status"] == "GRANTED"
    assert granted["months_granted"] == 12
    assert granted["last_effective_month"] == "2027-07"
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=1,
        extension_months_used=12,
        issued_countable_months=13,
    )

    response = api.grant_extension(
        second["id"], factories.grant_extension_payload(1), supervisor_headers()
    )

    asrt.assert_rejected(response, errs.ERR_EXTENSION_LIMIT_EXCEEDED)
    refused = fx.read_extension(api, context.case_id, second["id"])
    assert refused["status"] == "REQUESTED"
    assert refused["months_granted"] == 0
    assert refused["last_effective_month"] is None


def test_establishing_a_claim_for_a_month_that_was_never_issued_is_refused(api):
    """PRD §3.9: "Every month in the `months_covered` list must correspond to a
    time-limit month row on that case with assistance actually issued; a month that was
    never issued is refused with `ERR_OVERPAID_MONTH_NOT_ISSUED`."
    PRD §3.9: "The draft opens in `status` `DRAFT` with every ledger figure zeroed —
    `established_amount_cents`, `total_recovered_cents`, `balance_cents` and
    `monthly_recoupment_cents` all 0 — with `recoupment_status` `NOT_STARTED`,
    `fraud_referral_status` `NOT_REFERRED`, and `established_by_user_id`,
    `write_off_reason` and `referral_note` all null."

    Design: Corner/validations/overpayment_covering_a_month_that_was_never_issued_is_refused
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Unissued Month Household"},
        incomes=(),
    )
    claim = fx.draft_overpayment(
        api,
        context.case_id,
        claim_type="AGENCY_ERROR",
        months_covered=["2026-08", "2026-09"],
        gross_amount_cents=20000,
        computation_method="GROSS",
    )
    assert claim["status"] == "DRAFT"

    response = api.establish_overpayment(claim["id"], fiscal_officer_headers())

    asrt.assert_rejected(response, errs.ERR_OVERPAID_MONTH_NOT_ISSUED)
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim["id"]),
        status="DRAFT",
        recoupment_status="NOT_STARTED",
        established_amount_cents=0,
        balance_cents=0,
    )


def test_chaining_a_new_episode_to_a_resolved_predecessor_is_refused(api):
    """PRD §3.7: "It must reference a compliance episode of the *same* case whose own
    `status` is `SANCTION_IMPOSED` or `CURE_PENDING`; a reference to another case's
    episode, or to an episode in any other status, is refused with
    `ERR_PRIOR_EPISODE_MISMATCH`."
    PRD §3.7: "The episode moves to `RESOLVED_COMPLIANT`, its `sanction_level` returns to
    0 and its `sanction_pct` to 0.00, and the case's `compliance_status` returns to
    `ASSIGNED`."

    Design: Corner/validations/prior_episode_reference_to_a_resolved_episode_is_refused
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Prior Episode Household"},
        incomes=(),
    )
    first = fx.open_episode(api, context.case_id, allegation_reason="MISSED_APPOINTMENT")
    fx.start_conciliation(api, first["id"])
    fx.resolve_compliant(api, first["id"])

    response = api.create_compliance_episode(
        factories.compliance_episode_payload(
            context.case_id,
            fx.case_version(api, context.case_id),
            allegation_reason="QUIT_EMPLOYMENT",
            prior_episode_id=first["id"],
        ),
        work_specialist_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_PRIOR_EPISODE_MISMATCH)
    assert fx.read_episode(api, first["id"])["status"] == "RESOLVED_COMPLIANT"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        compliance_status="ASSIGNED",
        sanction_level=0,
    )
    assert len(fx.search_episodes(api, case_id=context.case_id)) == 1


def test_a_sanction_waits_for_the_conciliation_deadline_and_then_lands(api):
    """PRD §3.7: "The date portion of the logical clock at that moment is stamped into
    `conciliation_start_date`, and `conciliation_deadline_date` is set to 30 days after
    that start date."
    PRD §3.7: "Two guards apply before anything is written: the episode's
    `good_cause_reason` must still be `NONE`, or the request is refused with
    `ERR_GOOD_CAUSE_ACTIVE`; and the current logical clock date must have reached or
    passed the episode's `conciliation_deadline_date`, or the request is refused with
    `ERR_CONCILIATION_NOT_COMPLETE`."
    PRD §3.7: "The logical clock's month is stamped into `sanction_imposed_month` on the
    episode's first imposition, and that stamp is what the federal sanction disregard in
    §3.10 reads."

    Design: Corner/validations/sanction_before_the_conciliation_deadline_is_refused_then_allowed
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Conciliation Household"},
        incomes=(),
    )
    episode = fx.open_episode(
        api, context.case_id, allegation_reason="REFUSED_ASSIGNMENT"
    )
    conciliating = fx.start_conciliation(api, episode["id"])
    assert conciliating["conciliation_start_date"] == "2026-08-01"
    assert conciliating["conciliation_deadline_date"] == "2026-08-31"

    response = api.impose_sanction(episode["id"], supervisor_headers())

    asrt.assert_rejected(response, errs.ERR_CONCILIATION_NOT_COMPLETE)
    assert fx.read_episode(api, episode["id"])["status"] == "CONCILIATION"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id), benefit_amount_cents=41650
    )

    fx.set_clock_date(api, "2026-09-01")
    fx.impose_sanction(api, episode["id"])

    stored = fx.read_episode(api, episode["id"])
    assert stored["status"] == "SANCTION_IMPOSED"
    assert stored["sanction_level"] == 1
    asrt.assert_pct(stored["sanction_pct"], 0.25, "episode sanction_pct")
    assert stored["sanction_imposed_month"] == "2026-09"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        sanction_level=1,
        benefit_amount_cents=31237,
    )


def test_fully_excluded_property_leaves_countable_resources_at_zero(api):
    """PRD §3.2: "The item's `countable_value_cents` is derived on write: an item claiming
    any exclusion other than `NONE` counts zero, and an item claiming `NONE` counts its
    gross value less its encumbrance, floored at zero so that an underwater asset counts
    nothing rather than a negative amount."
    PRD §3.2: "Countable resources for the application are simply the total of
    `countable_value_cents` across the application's resource items, and an application
    with no resource items has countable resources of zero."
    PRD §3.3: "The application's `countable_resources_cents` must not exceed the program
    resource limit of 200000 cents — exactly at the limit is eligible, and strictly above
    it is refused with `ERR_RESOURCE_LIMIT_EXCEEDED`."

    Design: Corner/validations/fully_excluded_resources_satisfy_the_resource_test_and_approve_passes
    """
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": "Corner Excluded Resources Household"
        },
        incomes=(),
        resources=(
            {
                "item_type": "VEHICLE",
                "gross_value_cents": 500000,
                "encumbrance_cents": 0,
                "exclusion_type": "PRIMARY_VEHICLE",
            },
            {
                "item_type": "REAL_PROPERTY",
                "gross_value_cents": 900000,
                "encumbrance_cents": 100000,
                "exclusion_type": "HOMESTEAD",
            },
        ),
    )
    application = built["application"]
    items = asrt.assert_page(
        api.list_resource_items(application["id"], caseworker_headers()), total_count=2
    )
    for item_id in built["resource_item_ids"]:
        asrt.assert_money(
            asrt.find_by_id(items, item_id)["countable_value_cents"],
            0,
            "countable_value_cents",
        )
    asrt.assert_money(
        application["countable_resources_cents"], 0, "countable resources"
    )

    case = fx.approve(api, application["id"])

    assert fx.read_application(api, application["id"])["status"] == "APPROVED"
    asrt.assert_case_state(
        case, benefit_status="PENDING_ISSUANCE", benefit_amount_cents=41650
    )
