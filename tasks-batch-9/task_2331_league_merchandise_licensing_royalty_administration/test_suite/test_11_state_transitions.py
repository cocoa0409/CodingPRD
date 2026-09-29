"""First states, single legal hops, refused hops and the cascades a hop drags along."""

from test_helpers import *  # noqa: F401,F403


def test_a_fresh_agreement_starts_draft_and_clear_with_an_empty_ledger(api, ops_headers):
    """PRD §3.3: "A fresh agreement starts with `contract_status` `DRAFT` and
    `compliance_posture` `CLEAR`, which are independent dimensions;
    `contract_year_start_quarter` is set to the quarter of `term_start_date` and identifies
    the first quarter of contract year one"

    Design: Corner/state_machines/agreement_starts_in_draft_with_clear_posture_and_zero_ledger
    """
    category = create_jersey_category()
    licensee = create_active_licensee(legal_name="Ivywood Sportswear")

    payload = agreement_payload(
        licensee["id"],
        category["id"],
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        central_licensing_flag=False,
    )
    agreement = validate_success(api.create_agreement(payload, ops_headers), 201)

    assert agreement["contract_status"] == "DRAFT"
    assert agreement["compliance_posture"] == "CLEAR"
    assert agreement["posture_as_of_quarter"] is None
    # The term starts in 2026Q1 even though the clock stands in 2026Q3.
    assert agreement["contract_year_start_quarter"] == "2026Q1"

    for zeroed in (
        "advance_paid_cents",
        "unrecouped_advance_cents",
        "recouped_advance_cents",
        "cumulative_royalty_cents",
        "mg_accrued_shortfall_cents",
        "approved_sku_count",
        "authorized_channel_count",
    ):
        assert agreement[zeroed] == 0, zeroed
    assert agreement["distribution_ready"] is False
    assert agreement["mg_final_shortfall_cents"] is None
    assert agreement["countersigned_by"] is None
    assert agreement["suspension_reason"] is None
    assert agreement["termination_reason"] is None
    assert agreement["version"] == 1


def test_opening_an_investigation_moves_the_action_and_nothing_else(api, compliance_headers):
    """PRD §3.2: "Opening an investigation with `INVESTIGATE` moves `REPORTED` to
    `INVESTIGATING`."

    Design: Corner/state_machines/enforcement_action_reported_to_investigating
    """
    licensee = create_active_licensee(legal_name="Junction Merch")
    reported = create_enforcement_action(
        suspected_licensee_id=licensee["id"], venue_type="ONLINE"
    )
    assert reported["status"] == "REPORTED"
    assert reported["version"] == 1

    investigating = validate_success(
        api.set_enforcement_action_status(
            reported["id"], enforcement_status_payload("INVESTIGATE"), compliance_headers
        ),
        200,
    )

    assert investigating["status"] == "INVESTIGATING"
    # Only a seizure stamps the quarter, stores units or scores the licensee.
    assert investigating["occurrence_quarter"] is None
    assert investigating["seized_units"] == 0
    assert investigating["seizure_authority"] is None
    assert investigating["recovered_cents"] == 0
    assert investigating["version"] == 2
    assert get_licensee(licensee["id"])["compliance_risk_index"] == 0


def test_submitting_for_signature_needs_a_granted_territory(api, ops_headers):
    """PRD §3.3: "Submitting for signature takes `DRAFT` to `PENDING_SIGNATURE` and requires
    four things: the agreement is in `DRAFT`, its `minimum_guarantee_cents` is still at least
    the category's floor, its `advance_paid_cents` is at least its `required_advance_cents`,
    and at least one territory grant of this agreement has `status` `GRANTED`."

    Design: Corner/state_machines/submit_for_signature_without_territory_grant_rejected
    """
    category = create_jersey_category()
    licensee = create_active_licensee(legal_name="Kenwood Athletic")
    agreement = create_draft_agreement(
        licensee["id"],
        category["id"],
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
    )
    pay_advance(agreement["id"], 250000)
    version_before = agreement_version(agreement["id"])

    response = api.set_contract_status(
        agreement["id"], contract_status_payload("SUBMIT_FOR_SIGNATURE"), ops_headers
    )
    validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    refused = get_agreement(agreement["id"])
    assert refused["contract_status"] == "DRAFT"
    assert refused["version"] == version_before

    grant = grant_territory(agreement["id"])
    assert grant["status"] == "GRANTED"
    assert grant["exclusivity_mode_snapshot"] == "NON_EXCLUSIVE"

    accepted = validate_success(
        api.set_contract_status(
            agreement["id"], contract_status_payload("SUBMIT_FOR_SIGNATURE"), ops_headers
        ),
        200,
    )
    assert accepted["contract_status"] == "PENDING_SIGNATURE"


def test_activating_a_licensee_twice_is_refused(api, ops_headers):
    """PRD §3.2: "Activation requires the licensee to be in `PROSPECT` and requires the
    payload's `vendor_compliance_certified` to be true — the social-compliance audit must be
    on file — and it sets the stored `vendor_compliance_certified` to true."

    Design: Corner/state_machines/activate_licensee_twice_second_returns_invalid_state
    """
    licensee = create_prospect_licensee(legal_name="Larkspur Goods")
    assert licensee["version"] == 1

    activated = validate_success(
        api.set_licensee_status(licensee["id"], activate_licensee_payload(), ops_headers), 200
    )
    assert activated["status"] == "ACTIVE"
    assert activated["vendor_compliance_certified"] is True
    assert activated["version"] == 2

    response = api.set_licensee_status(
        licensee["id"], activate_licensee_payload(), ops_headers
    )
    validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    # The refusal is not a silent no-op that still bumps the row.
    assert get_licensee(licensee["id"])["version"] == 2


def test_a_terminated_agreement_admits_no_further_transition(api, ops_headers):
    """PRD §3.3: "Termination is permitted from `DRAFT`, `PENDING_SIGNATURE`, `ACTIVE` and
    `SUSPENDED`, and produces the terminal `TERMINATED`."

    Design: Corner/state_machines/terminated_agreement_admits_no_transition_returns_invalid_state
    """
    category = create_jersey_category()
    licensee = create_active_licensee(legal_name="Marlowe Brands")
    agreement = create_draft_agreement(licensee["id"], category["id"])

    terminated = terminate_agreement(
        agreement["id"], reason="Licensee withdrew from the category"
    )
    assert terminated["contract_status"] == "TERMINATED"
    version_after_termination = terminated["version"]

    for payload in (
        contract_status_payload("SUBMIT_FOR_SIGNATURE"),
        contract_status_payload("ACTIVATE", countersigned_by="R. Vance"),
        contract_status_payload("TERMINATE", reason="Second attempt"),
    ):
        response = api.set_contract_status(agreement["id"], payload, ops_headers)
        validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    unchanged = get_agreement(agreement["id"])
    assert unchanged["contract_status"] == "TERMINATED"
    assert unchanged["termination_reason"] == "Licensee withdrew from the category"
    assert unchanged["countersigned_by"] is None
    assert unchanged["version"] == version_after_termination


def test_approving_a_draft_submission_is_refused(api, ops_headers):
    """PRD §3.5: "A submission in `SAMPLE_PASSED` may be approved; a submission in
    `IN_REVIEW` may be approved only when its `sample_required` is false."

    Design: Corner/state_machines/approve_a_draft_submission_returns_invalid_state
    """
    context = setup_active_agreement()
    mark = create_league_mark()
    submission = create_submission(
        context["agreement"]["id"], context["licensee"]["id"], [mark["id"]]
    )
    assert submission["status"] == "DRAFT"

    response = api.create_submission_review_decision(
        submission["id"], submission_review_decision_payload("APPROVE"), ops_headers
    )
    validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    unchanged = get_submission(submission["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["approved_at"] is None
    assert unchanged["approved_by_user_id"] is None
    assert unchanged["approved_mark_snapshot"] == []

    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["approved_sku_count"] == 0
    assert agreement["distribution_ready"] is False


def test_suspending_a_licensee_holds_only_the_open_reviews(api):
    """PRD §3.2: "It requires a non-empty `reason`, which is stored as the licensee's
    `suspension_reason`, and it cascades downward twice: every agreement of that licensee
    whose `contract_status` is `ACTIVE` moves to `SUSPENDED` with its own `suspension_reason`
    set to the literal `LICENSEE_SUSPENDED`, and for each agreement suspended by that effect,
    every product submission of that agreement whose `status` is `SUBMITTED`, `IN_REVIEW` or
    `SAMPLE_REQUESTED` has `review_hold` set to true."

    Design: Corner/state_machines/licensee_suspension_cascades_review_hold_to_open_submissions
    """
    context = setup_approved_submission()
    approved_id = context["submission"]["id"]
    open_review = setup_submission_in_review(
        mark_ids=[context["league_mark"]["id"]],
        context=dict(context),
        product_name="Away Replica Jersey",
    )["submission"]
    assert open_review["id"] != approved_id
    assert open_review["review_hold"] is False

    suspended = suspend_licensee(
        context["licensee"]["id"], reason="Unresolved mark misuse notice"
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "Unresolved mark misuse notice"

    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["contract_status"] == "SUSPENDED"
    # The cascade writes its own constant, not the officer's free text.
    assert agreement["suspension_reason"] == "LICENSEE_SUSPENDED"
    # The contract dimension moved; the posture dimension did not.
    assert agreement["compliance_posture"] == "CLEAR"

    held = get_submission(open_review["id"])
    assert held["status"] == "IN_REVIEW"
    assert held["review_hold"] is True

    untouched = get_submission(approved_id)
    assert untouched["status"] == "APPROVED"
    assert untouched["review_hold"] is False


def test_accepting_a_report_posts_the_ledger_and_stamps_the_acceptance(api, finance_headers):
    """PRD §3.7: "Acceptance is where money moves. The same six-step waterfall is applied,
    with the recoupment cap re-read from the agreement's posture at accept time — which may
    differ from the posture projected at file time — and the result is posted to the
    agreement's ledger: `unrecouped_advance_cents` decreases by `recoupment_applied_cents`,
    `recouped_advance_cents` increases by the same amount, and `cumulative_royalty_cents`
    increases by `royalty_due_cents`."

    Design: Corner/state_machines/report_accept_posts_ledger_and_stamps_acceptance_fields
    """
    context = setup_licensed_operation(
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        central_licensing_flag=False,
    )
    licensee_id = context["licensee"]["id"]
    lines = simple_report_lines(context["authorization"]["id"], 2500000, units=5000)
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    filed = file_report(report["id"], licensee_id)

    before = get_agreement(context["agreement"]["id"])
    assert before["unrecouped_advance_cents"] == 250000
    assert before["recouped_advance_cents"] == 0
    assert before["cumulative_royalty_cents"] == 0

    assert filed["status"] == "FILED"
    assert filed["applied_tier_rate_bps"] == 1000
    assert filed["royalty_due_cents"] == 250000
    assert filed["recoupment_applied_cents"] == 250000
    assert filed["cash_due_pre_fee_cents"] == 0
    assert filed["late_days"] == 0
    assert filed["admin_fee_cents"] == 0
    assert filed["total_payable_cents"] == 0

    accepted = validate_success(
        api.create_report_review_decision(
            report["id"], report_review_decision_payload("ACCEPT"), finance_headers
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == "u_fin_1"
    assert accepted["accepted_at"] is not None
    assert_timestamp_format(accepted["accepted_at"])

    after = get_agreement(context["agreement"]["id"])
    assert after["unrecouped_advance_cents"] == 0
    assert after["recouped_advance_cents"] == 250000
    assert after["cumulative_royalty_cents"] == 250000
    assert after["advance_paid_cents"] == 250000
    assert_advance_ledger_conserved(after)


def test_terminating_an_agreement_reaches_the_sku_and_the_channel(api, compliance_headers):
    """PRD §3.5: "The system moves it from `APPROVED` to the terminal `REVOKED` when a cascade
    names it — because a mark in its pinned snapshot was withdrawn, because its licensee was
    terminated, or because its agreement was terminated — and `revocation_reason` records
    which: `MARK_WITHDRAWN`, `LICENSEE_TERMINATED` or `COMPLIANCE_ORDER` respectively."

    Design: Corner/state_machines/agreement_termination_revokes_approved_sku_and_suspends_authorization
    """
    context = setup_licensed_operation(sku_classes=["JERSEY"], central_licensing_flag=False)
    context = setup_approved_submission(context=context)
    assert get_agreement(context["agreement"]["id"])["approved_sku_count"] == 1

    terminated = terminate_agreement(
        context["agreement"]["id"],
        reason="Counterfeit consent order",
        headers=compliance_headers,
    )
    assert terminated["contract_status"] == "TERMINATED"
    assert terminated["termination_reason"] == "Counterfeit consent order"
    assert terminated["approved_sku_count"] == 0
    assert terminated["distribution_ready"] is False

    submission = get_submission(context["submission"]["id"])
    assert submission["status"] == "REVOKED"
    assert submission["revocation_reason"] == "COMPLIANCE_ORDER"

    authorization = get_authorization(context["authorization"]["id"])
    assert authorization["status"] == "SUSPENDED"
    assert authorization["suspension_reason"] == "NO_APPROVED_SKUS"

    grant = validate_success(
        api.get_territory_grant(context["territory_grant"]["id"], compliance_headers), 200
    )
    assert grant["status"] == "REVOKED"

    # The cascade runs downward only.
    assert get_licensee(context["licensee"]["id"])["status"] == "ACTIVE"
