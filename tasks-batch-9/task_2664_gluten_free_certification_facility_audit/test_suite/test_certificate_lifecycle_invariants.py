"""Compensating writes on a certificate: reinstatement undoing a suspension, and a
refund-eligible revocation undoing an issuance fee, each with one part that must not
be undone.
"""

from test_helpers import (
    IngredientSpec,
    MarkTier,
    RiskClass,
    add_certified_product,
    issue_certificate,
    make_decision_maker_headers,
    read_applicant,
    read_certificate,
    read_product,
    reinstate_certificate,
    revoke_certificate,
    set_clock,
    setup_issued_certificate,
    suspend_certificate,
    validate_paginated,
    make_admin_headers,
)

SANITATION_DAY = "2026-08-01T00:00:00Z"
ISSUE_DAY = "2026-08-11T00:00:00Z"
REFUND_EDGE = "2026-09-10T00:00:00Z"
ONE_SECOND_LATE = "2026-09-10T00:00:01Z"
FEE = 178800

SHARED_LINE = IngredientSpec(
    name="Brown Rice Flour",
    risk_class=RiskClass.INHERENTLY_GF,
    inclusion_pct=60,
    doc_issued_on="2026-07-01T00:00:00Z",
    doc_expires_on="2029-07-01T00:00:00Z",
)


def _one_certificate_through_a_full_suspension_lap(api):
    """A single certified product issued 2026-08-11 for 178800 cents, suspended for
    CHANGE_REQUIRES_RECERT by dm-1 and then reinstated by dm-2.

    Nothing else ever touches the applicant, so every counter reading below is the
    lap itself rather than a side effect of some other finding or certificate.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SHARED_LINE,),
        issue_clock=ISSUE_DAY,
    )
    at_issue = read_applicant(api, context.applicant_id)
    suspended = suspend_certificate(
        api,
        context.certificate_id,
        suspension_reason="CHANGE_REQUIRES_RECERT",
        decision_maker_user_id="dm-1",
    )
    at_suspension = read_applicant(api, context.applicant_id)
    reinstated = reinstate_certificate(
        api, context.certificate_id, decision_maker_user_id="dm-2"
    )
    at_reinstatement = read_applicant(api, context.applicant_id)
    return {
        "context": context,
        "at_issue": at_issue,
        "suspended": suspended,
        "at_suspension": at_suspension,
        "reinstated": reinstated,
        "at_reinstatement": at_reinstatement,
    }


def test_the_first_suspension_costs_the_active_count_and_five_posture_points(api):
    """Issuance reads 1 active at 100; the suspension moves the product out of the
    active count into the suspended count and takes the score to 95.

    PRD: "However it is reached, suspension sets `suspended_on` to the logical clock,
    records the `suspension_reason`, increases `suspension_count` by 1 and sets
    `mark_usage_locked` to true, which is the flag that tells the applicant the mark
    may no longer be displayed."
    PRD: "`active_certified_product_count` is a plain count of this applicant's
    certificates whose `status` is `ISSUED`."

    Design: Difficulty/compensating_invariant/suspend_reinstate_suspend_conserves_active_count_while_suspension_count_only_climbs
    """
    lap = _one_certificate_through_a_full_suspension_lap(api)

    assert lap["at_issue"]["active_certified_product_count"] == 1
    assert lap["at_issue"]["suspended_certificate_count"] == 0
    assert lap["at_issue"]["posture_score_cycle"] == 100
    assert lap["at_issue"]["fee_balance_cents"] == FEE

    assert lap["suspended"]["status"] == "SUSPENDED"
    assert lap["suspended"]["suspension_reason"] == "CHANGE_REQUIRES_RECERT"
    assert lap["suspended"]["suspension_count"] == 1
    assert lap["suspended"]["mark_usage_locked"] is True
    assert lap["suspended"]["suspended_on"] == ISSUE_DAY

    assert lap["at_suspension"]["active_certified_product_count"] == 0
    assert lap["at_suspension"]["suspended_certificate_count"] == 1
    assert lap["at_suspension"]["posture_score_cycle"] == 95


def test_reinstatement_restores_every_reversible_field_and_keeps_the_lap_counter(api):
    """The round trip returns the counters, the score and the label to their exact
    pre-suspension values, while `suspension_count` stays at 1.

    PRD: "On success the certificate moves `SUSPENDED → ISSUED`, clears `suspended_on`
    and `suspension_reason` to null and sets `mark_usage_locked` back to false, while
    `suspension_count` is **not** decreased — it is the permanent record of how many
    suspensions this certificate has survived."
    PRD: "The applicant's `active_certified_product_count` increases again and
    `suspended_certificate_count` decreases, and the posture fields are recomputed,
    restoring exactly the values that held before the suspension."

    Design: Difficulty/compensating_invariant/suspend_reinstate_suspend_conserves_active_count_while_suspension_count_only_climbs
    """
    lap = _one_certificate_through_a_full_suspension_lap(api)

    assert lap["reinstated"]["status"] == "ISSUED"
    assert lap["reinstated"]["suspension_count"] == 1
    assert lap["reinstated"]["mark_usage_locked"] is False
    assert lap["reinstated"]["suspended_on"] is None
    assert lap["reinstated"]["suspension_reason"] is None

    product = read_product(api, lap["context"].product_id)
    assert product["label_status"] == "APPROVED"
    assert product["mark_tier_granted"] == MarkTier.STANDARD

    after = lap["at_reinstatement"]
    assert after["active_certified_product_count"] == 1
    assert after["suspended_certificate_count"] == 0
    assert after["posture_score_cycle"] == 100
    assert after["compliance_posture"] == "GOOD_STANDING"
    assert after["fee_balance_cents"] == FEE


def test_a_second_suspension_climbs_to_two_laps_on_the_same_certificate(api):
    """Suspending again — this time for SURVEILLANCE_OVERDUE and by the other
    decision maker — reads 2 laps, not 1, and the fee ledger never moved.

    PRD: "Suspended, revoked and expired certificates are excluded, which is what
    makes a suspend-then-reinstate round trip return the count to its exact
    pre-suspension value while `suspension_count` on the certificate keeps a permanent
    record of how many laps were run."
    PRD: "Suspension, reinstatement, expiry and every non-refund-eligible revocation
    leave the balance completely untouched — a suspended certificate is still a billed
    certificate."

    Design: Difficulty/compensating_invariant/suspend_reinstate_suspend_conserves_active_count_while_suspension_count_only_climbs
    """
    lap = _one_certificate_through_a_full_suspension_lap(api)

    response = api.suspend_certificate(
        lap["context"].certificate_id,
        make_decision_maker_headers("dm-2"),
        suspension_reason="SURVEILLANCE_OVERDUE",
    )
    assert response.status_code == 200, response.text

    certificate = read_certificate(api, lap["context"].certificate_id)
    assert certificate["status"] == "SUSPENDED"
    assert certificate["suspension_count"] == 2
    assert certificate["suspension_reason"] == "SURVEILLANCE_OVERDUE"
    assert certificate["mark_usage_locked"] is True
    assert certificate["fee_refunded"] is False

    assert read_product(api, lap["context"].product_id)["label_status"] == "FROZEN"

    applicant = read_applicant(api, lap["context"].applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 1
    assert applicant["revoked_certificate_count"] == 0
    assert applicant["fee_balance_cents"] == FEE
    assert applicant["posture_score_cycle"] == 95
    assert applicant["compliance_posture"] == "GOOD_STANDING"


def _two_identically_priced_certificates_with_the_first_refunded(api):
    """Two STANDARD products sharing one approved ingredient at 60 pct inclusion, both
    certified 2026-08-11 for 178800 cents each, with the first revoked for
    VOLUNTARY_WITHDRAWAL at exactly 2026-09-10 — issuance plus 30 days.

    Neither product ever has an UNANNOUNCED lot pulled, so the only refund condition
    left in play on the second revocation is the 30-day boundary; the clock is then
    moved one second past it.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SHARED_LINE,),
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        issue_clock=ISSUE_DAY,
    )
    second = add_certified_product(
        api, context, name="Rice Dinner Roll", sku="RDR-002", inclusion_pct=60
    )
    certificate_b = issue_certificate(api, second["product"]["id"], second["version"])
    at_issue = read_applicant(api, context.applicant_id)

    set_clock(api, REFUND_EDGE)
    revoked_a = revoke_certificate(
        api, context.certificate_id, revocation_reason="VOLUNTARY_WITHDRAWAL"
    )
    after_a = read_applicant(api, context.applicant_id)
    set_clock(api, ONE_SECOND_LATE)
    return {
        "context": context,
        "product_b": second["product"],
        "certificate_b": certificate_b,
        "at_issue": at_issue,
        "revoked_a": revoked_a,
        "after_a": after_a,
    }


def test_a_revocation_exactly_thirty_days_after_issuance_refunds_the_whole_fee(api):
    """Both certificates bill 178800 for a balance of 357600, and the revocation on
    the inclusive edge takes exactly one fee back off.

    PRD: "The fee is refunded on revocation only when **all three** of the following
    hold: the `revocation_reason` is `VOLUNTARY_WITHDRAWAL`; the logical clock is at or
    before 30 days after `issued_on`, with the boundary inclusive so that revoking
    exactly 30 days after issuance still refunds and 30 days plus one second does not;
    and no lot test of the certificate's product exists whose `test_type` is
    `UNANNOUNCED`."
    PRD: "When all three hold, `fee_refunded` becomes true and the applicant's
    `fee_balance_cents` decreases by exactly this certificate's `total_fee_cents`,
    restoring the balance held before the certificate was issued."

    Design: Difficulty/compensating_invariant/voluntary_withdrawal_refund_is_exact_and_one_second_late_forfeits_it
    """
    built = _two_identically_priced_certificates_with_the_first_refunded(api)

    assert built["context"].certificate["total_fee_cents"] == FEE
    assert built["context"].certificate["fee_charged"] is True
    assert built["context"].certificate["issued_on"] == ISSUE_DAY
    assert built["certificate_b"]["total_fee_cents"] == FEE
    assert built["at_issue"]["fee_balance_cents"] == 2 * FEE
    assert built["at_issue"]["active_certified_product_count"] == 2

    assert built["revoked_a"]["status"] == "REVOKED"
    assert built["revoked_a"]["fee_refunded"] is True
    assert built["revoked_a"]["fee_charged"] is True
    assert built["revoked_a"]["revoked_on"] == REFUND_EDGE
    assert built["after_a"]["fee_balance_cents"] == FEE
    assert built["after_a"]["revoked_certificate_count"] == 1


def test_one_second_past_the_edge_the_revocation_succeeds_without_a_refund(api):
    """The second withdrawal is accepted and permanent, but its fee is forfeit: the
    balance holds at 178800 rather than falling to zero.

    PRD: "Otherwise `fee_refunded` stays false and the balance is untouched."
    PRD: "The certificate records `revoked_on` as the logical clock and the supplied
    reason, sets `mark_usage_locked` to true, and freezes the product's `label_status`
    from `APPROVED` to `FROZEN`."

    Design: Difficulty/compensating_invariant/voluntary_withdrawal_refund_is_exact_and_one_second_late_forfeits_it
    """
    built = _two_identically_priced_certificates_with_the_first_refunded(api)

    response = api.revoke_certificate(
        built["certificate_b"]["id"],
        make_decision_maker_headers("dm-1"),
        revocation_reason="VOLUNTARY_WITHDRAWAL",
    )
    assert response.status_code == 200, response.text
    revoked_b = response.json()["data"]

    assert revoked_b["status"] == "REVOKED"
    assert revoked_b["revocation_reason"] == "VOLUNTARY_WITHDRAWAL"
    assert revoked_b["revoked_on"] == ONE_SECOND_LATE
    assert revoked_b["fee_charged"] is True
    assert revoked_b["fee_refunded"] is False
    assert revoked_b["mark_usage_locked"] is True
    assert revoked_b["total_fee_cents"] == FEE

    assert read_applicant(api, built["context"].applicant_id)["fee_balance_cents"] == FEE


def test_both_withdrawals_leave_two_frozen_labels_and_a_clean_posture(api):
    """With both certificates revoked the applicant holds no active and no suspended
    certificate, two revoked ones, and — because withdrawal is not fraud — a full score.

    PRD: "in both cases `revoked_certificate_count` increases by 1 and the posture
    fields are recomputed, applying the override that forces `compliance_posture` to
    `SUSPENDED` when the reason was `FRAUD` or `REPEAT_FAILURE`."
    PRD: "At every observable instant it equals the sum of `total_fee_cents` over that
    applicant's certificates whose `fee_charged` is true and whose `fee_refunded` is
    false."

    Design: Difficulty/compensating_invariant/voluntary_withdrawal_refund_is_exact_and_one_second_late_forfeits_it
    """
    built = _two_identically_priced_certificates_with_the_first_refunded(api)

    revoke_certificate(
        api, built["certificate_b"]["id"], revocation_reason="VOLUNTARY_WITHDRAWAL"
    )

    assert read_product(api, built["context"].product_id)["label_status"] == "FROZEN"
    assert read_product(api, built["product_b"]["id"])["label_status"] == "FROZEN"

    rows, meta = validate_paginated(
        api.list_certificates(
            make_admin_headers(), applicant_id=built["context"].applicant_id
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["REVOKED", "REVOKED"]
    assert sorted(row["fee_refunded"] for row in rows) == [False, True]

    applicant = read_applicant(api, built["context"].applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 0
    assert applicant["revoked_certificate_count"] == 2
    assert applicant["fee_balance_cents"] == FEE
    assert applicant["posture_score_cycle"] == 100
    assert applicant["compliance_posture"] == "GOOD_STANDING"
