"""The milestone reject-and-resubmit cycle, and the clawback penalty tier edge."""

from test_helpers import (
    ApiErrorId,
    api_client,
    add_milestone,
    assert_compliance_audit,
    assert_four_decimal_places,
    assert_milestone,
    disburse_milestone,
    issue_clawback_notice,
    read_award,
    read_location,
    setup_construction_authorized_award,
    setup_failed_audit,
    submit_milestone_evidence,
    validate_error,
    validate_paginated,
    verify_milestone,
)
from test_helpers.fixtures import ADMIN


def _milestone_row(award_id, milestone_id):
    """Re-read one milestone through the award's milestone collection."""
    rows, _ = validate_paginated(api_client.list_milestones(award_id, ADMIN))
    matches = [row for row in rows if row["id"] == milestone_id]
    assert len(matches) == 1
    return matches[0]


def test_a_rejected_milestone_is_resubmitted_once_and_then_verified():
    """Rejection zeroes the payable amount and parks the milestone; the applicant's
    single resubmission carries it back for verification, approval then pays the
    pro-rata share and moves the built location on the service axis, and a second
    verification of the approved milestone is refused.

    PRD 3.8: "A `REJECTED` verification moves the milestone
    `EVIDENCE_SUBMITTED → REJECTED`, stamps `rejection_reason`, sets
    `payable_amount_cents` to 0, and likewise records the caller as the award's
    `last_verifier_user_id`."
    PRD 3.8: "A rejected milestone may be resubmitted, moving it
    `REJECTED → EVIDENCE_SUBMITTED` with `resubmission_count` incremented and
    `built_location_ids` replaced, requiring `resubmission_count` to be strictly
    below two and the award's compliance posture again to be `COMPLIANT` or
    `CURED`; a third resubmission is refused with `ERR_RESUBMISSION_LIMIT_REACHED`."
    PRD 3.8: "When `is_final` is false and `evidence_basis` is `BUILD_PROGRESS`,
    the **pro-rata build** variant applies: a gross figure is the award's
    `obligation_amount_cents` multiplied by `verified_location_count` and divided by
    the award's `confirmed_location_count`, rounded half up to a whole cent, and the
    payable amount is the smaller of that gross figure and the remaining headroom."
    PRD 2.12: "14. **Priority 46 — milestone state** →
    `ERR_MILESTONE_STATE_INVALID`. Submitting evidence requires `PLANNED` or
    `REJECTED`; verification requires `EVIDENCE_SUBMITTED`; disbursement requires
    `APPROVED`."

    Design: Corner/state_machines/milestone_reject_then_resubmit_cycle_and_verified_count
    """
    ctx = setup_construction_authorized_award()
    built = ctx["location_ids"]["L2"]
    assert ctx["award"]["obligation_amount_cents"] == 2025003
    assert ctx["award"]["confirmed_location_count"] == 3
    assert ctx["award"]["holdback_cap_cents"] == 1822503

    milestone = add_milestone(ctx["award_id"], 1, [built])
    assert_milestone(milestone)
    assert milestone["milestone_state"] == "PLANNED"
    assert milestone["resubmission_count"] == 0

    submit_milestone_evidence(
        ctx["award_id"], milestone["id"], [built], ctx["subgrantee_id"]
    )
    rejected = verify_milestone(
        ctx["award_id"],
        milestone["id"],
        "REJECTED",
        rejection_reason="Splice photographs do not cover the drop.",
    )
    assert rejected["milestone_state"] == "REJECTED"
    assert rejected["payable_amount_cents"] == 0
    assert rejected["rejection_reason"] == "Splice photographs do not cover the drop."
    assert read_award(ctx["award_id"])["last_verifier_user_id"] == "auditor-1"
    assert read_location(built)["service_state"] == "UNDER_CONSTRUCTION", (
        "A rejection moves nothing on the service axis"
    )

    resubmitted = submit_milestone_evidence(
        ctx["award_id"], milestone["id"], [built], ctx["subgrantee_id"]
    )
    assert resubmitted["milestone_state"] == "EVIDENCE_SUBMITTED"
    assert resubmitted["resubmission_count"] == 1

    approved = verify_milestone(ctx["award_id"], milestone["id"], "APPROVED")
    assert approved["milestone_state"] == "APPROVED"
    assert approved["verified_location_count"] == 1
    assert approved["payable_amount_cents"] == 675001, (
        "2025003 times one of three locations, rounded half up"
    )
    assert approved["verified_by_user_id"] == "auditor-1"
    assert approved["resubmission_count"] == 1
    assert read_location(built)["service_state"] == "SERVICE_AVAILABLE"

    already_verified = api_client.verify_milestone(
        ctx["award_id"], milestone["id"], {"outcome": "APPROVED"}, ADMIN
    )
    validate_error(already_verified, ApiErrorId.ERR_MILESTONE_STATE_INVALID)

    settled = _milestone_row(ctx["award_id"], milestone["id"])
    assert settled["milestone_state"] == "APPROVED"
    assert settled["payable_amount_cents"] == 675001
    assert settled["resubmission_count"] == 1


def test_a_failure_share_of_exactly_one_half_selects_the_lower_penalty_tier():
    """One failed location out of two bound locations is a share of exactly 0.5000,
    which sits on the inclusive upper edge of the third tier, so the multiplier is
    1.25 and the recovery is the pro-rata base uplifted by it.

    PRD 3.9: "The share is `failed_location_count` divided by the award's
    `confirmed_location_count`, rounded half up to 4 decimal places."
    PRD 3.9: "The multiplier is then selected by tier, with every tier boundary
    inclusive on its upper edge: 1.00 when the share is at most 0.10, 1.10 when it
    is at most 0.25, 1.25 when it is at most 0.50, and 1.50 above that — so a share
    of exactly 0.5000 selects 1.25, not 1.50."
    PRD 3.9: "The recovery is computed in two rounded steps: a base recovery is the
    award's `disbursed_to_date_cents` multiplied by `failed_location_count` and
    divided by the award's `confirmed_location_count` — using the exact unrounded
    fraction — rounded half up to a whole cent; that base is then multiplied by
    `penalty_multiplier`, rounded half up to a whole cent again, and the result is
    capped at the award's `disbursed_to_date_cents`, because the office can never
    recover more than it paid."

    Design: Corner/calculations/clawback_penalty_tier_inclusive_upper_edge
    """
    ctx = setup_construction_authorized_award(location_keys=("L2", "L3"))
    scope = [ctx["location_ids"]["L2"], ctx["location_ids"]["L3"]]
    assert ctx["award"]["obligation_amount_cents"] == 1350002
    assert ctx["award"]["holdback_cap_cents"] == 1215002
    assert ctx["award"]["confirmed_location_count"] == 2

    milestone = add_milestone(
        ctx["award_id"], 1, scope, evidence_basis="INVOICED_COST"
    )
    submit_milestone_evidence(
        ctx["award_id"],
        milestone["id"],
        scope,
        ctx["subgrantee_id"],
        invoiced_cost_cents=2000000,
    )
    approved = verify_milestone(ctx["award_id"], milestone["id"], "APPROVED")
    assert approved["payable_amount_cents"] == 1215002, (
        "The 1500000 federal share of the invoice is clamped to the headroom"
    )
    disburse_milestone(ctx["award_id"], milestone["id"])

    funded = read_award(ctx["award_id"])
    assert funded["disbursed_to_date_cents"] == 1215002
    assert funded["award_state"] == "IN_CONSTRUCTION"

    audit = setup_failed_audit(ctx, ("L2", "L3"), ("L2",))
    assert_compliance_audit(audit)
    assert audit["audit_state"] == "FAILED"
    assert audit["tested_location_count"] == 2
    assert audit["failed_location_count"] == 1
    assert_four_decimal_places(audit["noncompliant_share"], "noncompliant_share")
    assert audit["noncompliant_share"] == 0.5000
    assert audit["penalty_multiplier"] == 1.25, (
        "A share of exactly 0.5000 selects 1.25, not 1.50"
    )

    noticed = issue_clawback_notice(ctx["award_id"], audit["id"])
    assert noticed["audit_state"] == "CLAWBACK_NOTICE_ISSUED"
    assert noticed["recovery_amount_cents"] == 759376, (
        "607501 base recovery uplifted by 1.25 and rounded half up"
    )
    assert noticed["recovery_amount_cents"] <= funded["disbursed_to_date_cents"]
    assert noticed["notice_issued_by_user_id"] == "auditor-2"
    assert read_award(ctx["award_id"])["compliance_state"] == "NONCOMPLIANT"
