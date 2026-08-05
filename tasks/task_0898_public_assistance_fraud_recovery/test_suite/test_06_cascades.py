"""Cross-record cascades: IPV imposition reclassification, satisfaction bubble-up,
compensating rescission, and write-off cancellation."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_overpayment_in_recovery,
    setup_imposed_disqualification,
    add_adh_referred_disqualification,
    add_held_hearing,
    create_disqualification_payload,
    create_transaction_payload,
    decide_hearing_payload,
    write_off_payload,
)

ADJUDICATOR = TEST_USERS["adjudicator_headers"]
RECOVERY = TEST_USERS["recovery_officer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


def _setup_ihe_recovery_with_held_hearing(api):
    """SUBSTANTIATED case whose IHE overpayment (final 45050) is IN_RECOVERY under an
    ACTIVE RECOUPMENT plan (recoupment 1940 at the IHE rate), with an ADH_REFERRED
    disqualification and a HELD hearing (adjudicator adj-1 != investigator inv-1)."""
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")
    add_adh_referred_disqualification(api, ctx)
    add_held_hearing(api, ctx)
    return ctx


# --------------------------------------------------------------------------- #
# Depth-3 imposition cascade
# --------------------------------------------------------------------------- #
def test_ipv_imposition_reclassifies_and_recomputes_recoupment(api):
    """PRD 3.5: "The third link, caused by the second, recomputes that overpayment's
    active recovery plan: its `monthly_recoupment_cents` is re-derived using the `IPV`
    rate and floor, and its projections are refreshed."

    Design: Difficulty/transitive_cascade/hearing_ipv_impose_reclassify_recoup_depth3
    """
    ctx = _setup_ihe_recovery_with_held_hearing(api)
    assert ctx["recovery_plan"]["monthly_recoupment_cents"] == 1940, (
        f"pre-cascade IHE recoupment expected 1940, got {ctx['recovery_plan']['monthly_recoupment_cents']}"
    )
    validate_success(
        api.decide_hearing(ctx["hearing"]["id"], decide_hearing_payload("IPV"), ADJUDICATOR)
    )
    disq = validate_success(api.get_disqualification(ctx["disqualification"]["id"], ADJUDICATOR))
    assert disq["status"] == "IMPOSED", f"expected IMPOSED, got {disq['status']}"
    plan = validate_success(api.get_recovery_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert plan["monthly_recoupment_cents"] == 3880, (
        f"post-cascade IPV recoupment expected 3880, got {plan['monthly_recoupment_cents']}"
    )


def test_ipv_imposition_increments_subject_and_reclassifies_claim(api):
    """PRD 3.5: "The first cascade link then increments the subject's `prior_ipv_count` by
    1 and recomputes the subject's `disqualification_status`. The second link, caused by
    the first, reclassifies the linked case's overpayment — if one exists and is
    non-terminal — by setting its `claim_type` to `IPV` and bumping its `updated_at` and
    `version`."

    Design: Difficulty/transitive_cascade/hearing_ipv_impose_reclassify_recoup_depth3
    """
    ctx = _setup_ihe_recovery_with_held_hearing(api)
    validate_success(
        api.decide_hearing(ctx["hearing"]["id"], decide_hearing_payload("IPV"), ADJUDICATOR)
    )
    subj = validate_success(api.get_subject(ctx["subject"]["id"], SUPERVISOR))
    assert subj["prior_ipv_count"] == 1, f"expected prior_ipv_count 1, got {subj['prior_ipv_count']}"
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert op["claim_type"] == "IPV", f"expected claim_type reclassified to IPV, got {op['claim_type']}"


# --------------------------------------------------------------------------- #
# Depth-2 satisfaction bubble-up
# --------------------------------------------------------------------------- #
def test_full_payment_satisfies_and_completes_plan(api):
    """PRD 3.7: "When both `outstanding_principal_cents` and `outstanding_interest_cents`
    reach zero, the overpayment bubbles up from `IN_RECOVERY` to `SATISFIED` and each of
    its active plans moves to `COMPLETED`."

    Design: Difficulty/transitive_cascade/transaction_full_payment_satisfy_complete_depth2
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # final 45050, zero interest
    txn = validate_success(
        api.create_transaction(
            create_transaction_payload(ctx["recovery_plan"]["id"], 45050,
                                       transaction_date="2026-05-01", method="PAYMENT"),
            RECOVERY,
        ),
        expected_status=201,
    )
    assert txn["applied_to_interest_cents"] == 0, f"expected 0 interest, got {txn['applied_to_interest_cents']}"
    assert txn["applied_to_principal_cents"] == 45050, (
        f"expected 45050 principal, got {txn['applied_to_principal_cents']}"
    )
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert op["outstanding_principal_cents"] == 0
    assert op["status"] == "SATISFIED", f"expected SATISFIED, got {op['status']}"
    plan = validate_success(api.get_recovery_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert plan["status"] == "COMPLETED", f"expected COMPLETED, got {plan['status']}"


def test_partial_payment_does_not_satisfy(api):
    """PRD 3.7: "When both `outstanding_principal_cents` and `outstanding_interest_cents`
    reach zero, the overpayment bubbles up from `IN_RECOVERY` to `SATISFIED` and each of
    its active plans moves to `COMPLETED`."

    Design: Difficulty/transitive_cascade/transaction_full_payment_satisfy_complete_depth2
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # final 45050, zero interest
    validate_success(
        api.create_transaction(
            create_transaction_payload(ctx["recovery_plan"]["id"], 20000,
                                       transaction_date="2026-05-01", method="PAYMENT"),
            RECOVERY,
        ),
        expected_status=201,
    )
    op = validate_success(api.get_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert op["outstanding_principal_cents"] == 25050, (
        f"expected 25050 remaining, got {op['outstanding_principal_cents']}"
    )
    assert op["status"] == "IN_RECOVERY", f"expected IN_RECOVERY, got {op['status']}"
    plan = validate_success(api.get_recovery_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert plan["status"] == "ACTIVE", f"expected ACTIVE, got {plan['status']}"


# --------------------------------------------------------------------------- #
# Compensating rescission
# --------------------------------------------------------------------------- #
def test_rescind_restores_prior_ipv_count(api):
    """PRD 3.5: "Rescission is a compensating action: it decrements the subject's
    `prior_ipv_count` by 1, recomputes the subject's `disqualification_status`, and clears
    the disqualification's `disqualified_until`."

    Design: Difficulty/compensating_invariant/rescind_restores_prior_ipv_count
    """
    ctx = setup_imposed_disqualification(api)  # prior_ipv_count == 1
    disq = validate_success(
        api.rescind_disqualification(ctx["disqualification"]["id"], {"reason": "Overturned"}, SUPERVISOR)
    )
    assert disq["status"] == "RESCINDED", f"expected RESCINDED, got {disq['status']}"
    subj = validate_success(api.get_subject(ctx["subject"]["id"], SUPERVISOR))
    assert subj["prior_ipv_count"] == 0, f"expected prior_ipv_count restored to 0, got {subj['prior_ipv_count']}"
    assert subj["disqualification_status"] == "NONE", (
        f"expected disqualification_status NONE, got {subj['disqualification_status']}"
    )


def test_rescind_allows_new_proposal(api):
    """PRD 3.5: "Rescission is a compensating action: it decrements the subject's
    `prior_ipv_count` by 1, recomputes the subject's `disqualification_status`, and clears
    the disqualification's `disqualified_until`."
    PRD 3.5: "A proposal is refused with `ERR_SUBJECT_ALREADY_DISQUALIFIED` (HTTP 409) if
    the subject already carries an active imposed disqualification — that is, if the
    subject's `disqualification_status` is `DISQUALIFIED` or `PERMANENTLY_DISQUALIFIED`."

    Design: Difficulty/compensating_invariant/rescind_restores_prior_ipv_count
    """
    ctx = setup_imposed_disqualification(api)
    validate_success(
        api.rescind_disqualification(ctx["disqualification"]["id"], {"reason": "Overturned"}, SUPERVISOR)
    )
    # With disqualification_status back to NONE, a fresh proposal is accepted.
    resp = api.create_disqualification(create_disqualification_payload(ctx["case"]["id"]), INVESTIGATOR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PROPOSED", f"expected PROPOSED, got {data['status']}"


# --------------------------------------------------------------------------- #
# Write-off cancellation cascade
# --------------------------------------------------------------------------- #
def test_write_off_cancels_active_plan(api):
    """PRD 3.4: "a `Supervisor` may write off an uncollectible claim, advancing it from
    `IN_RECOVERY` to `WRITTEN_OFF` with a `reason`; write-off is permitted only while
    `outstanding_principal_cents` is greater than zero, and it cancels every non-terminal
    recovery plan of the claim (moving each to `CANCELLED`)."

    Design: Corner/state_machines/write_off_cancels_recovery_plan
    """
    ctx = setup_overpayment_in_recovery(api, claim_type="IHE")  # balance 45050
    op = validate_success(
        api.write_off_overpayment(ctx["overpayment"]["id"], write_off_payload(reason="Bankruptcy"), SUPERVISOR)
    )
    assert op["status"] == "WRITTEN_OFF", f"expected WRITTEN_OFF, got {op['status']}"
    plan = validate_success(api.get_recovery_plan(ctx["recovery_plan"]["id"], RECOVERY))
    assert plan["status"] == "CANCELLED", f"expected CANCELLED, got {plan['status']}"
