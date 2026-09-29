"""The clearance gate on construction and the two milestone payment bases."""

from test_helpers import (
    ApiErrorId,
    add_milestone,
    api_client,
    authorize_construction,
    clear_environmental_review,
    disburse_milestone,
    open_environmental_review,
    read_award,
    read_location,
    record_environmental_determination,
    setup_construction_authorized_award,
    setup_obligated_award,
    submit_milestone_evidence,
    validate_error,
    validate_paginated,
    verify_milestone,
)
from test_helpers.fixtures import ADMIN, EHP


def _award_with_a_mitigation_required_review():
    """An OBLIGATED award whose environmental review took the assessment route
    and is parked at MITIGATION_REQUIRED rather than CLEARED."""
    ctx = setup_obligated_award()
    review = open_environmental_review(
        ctx["award_id"],
        tribal_consultation_required=True,
        shpo_consultation_required=True,
    )
    assert review["ehp_state"] == "SCREENING"

    assessment = record_environmental_determination(ctx["award_id"], "EA_REQUIRED")
    assert assessment["ehp_state"] == "EA_REQUIRED"

    ctx["review"] = record_environmental_determination(
        ctx["award_id"],
        "MITIGATION_PLAN_ACCEPTED",
        mitigation_summary="Seasonal work window and archaeological monitoring.",
    )
    return ctx


def test_construction_authorization_is_refused_while_the_review_needs_mitigation():
    """The award is legally OBLIGATED and the caller is a program admin, yet
    authorisation is refused solely because a separate review row is not
    CLEARED, and nothing on the award or its locations moves.

    PRD 3.8: "With clearance in hand, a `ProgramAdmin` authorises construction,
    moving the award `OBLIGATED → CONSTRUCTION_AUTHORIZED` and moving every
    `AWARD_BOUND` location on the service axis `NOT_BUILT → UNDER_CONSTRUCTION`.
    Authorisation without a `CLEARED` review is refused with
    `ERR_EHP_NOT_CLEARED`."
    PRD 2.12: "20. **Priority 55 — clearance precondition.** Authorising
    construction requires the award's environmental review to be `CLEARED` →
    `ERR_EHP_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/construction_authorization_gated_by_environmental_review_state
    """
    ctx = _award_with_a_mitigation_required_review()
    assert ctx["review"]["ehp_state"] == "MITIGATION_REQUIRED"

    refused = api_client.authorize_construction(ctx["award_id"], ADMIN)
    validate_error(refused, ApiErrorId.ERR_EHP_NOT_CLEARED)

    assert read_award(ctx["award_id"])["award_state"] == "OBLIGATED"
    for key in ("L2", "L3", "L5"):
        location = read_location(ctx["location_ids"][key])
        assert location["service_state"] == "NOT_BUILT"
        assert location["eligibility_state"] == "AWARD_BOUND"


def test_clearing_the_other_entity_alone_unlocks_the_identical_authorization():
    """Clearing the review changes nothing on the award, yet the identical
    authorisation call now succeeds and advances every bound location on the
    service axis.

    PRD 3.8: "Clearance moves the review to `CLEARED`, stamping the acting
    reviewer as `cleared_by_user_id` and the current logical instant as
    `cleared_at`. It runs as `CATEGORICAL_EXCLUSION → CLEARED` unconditionally,
    and as `MITIGATION_REQUIRED → CLEARED` only when `mitigation_summary` is not
    null."
    PRD 3.8: "With clearance in hand, a `ProgramAdmin` authorises construction,
    moving the award `OBLIGATED → CONSTRUCTION_AUTHORIZED` and moving every
    `AWARD_BOUND` location on the service axis `NOT_BUILT → UNDER_CONSTRUCTION`."
    PRD 3.8: "Authorisation without a `CLEARED` review is refused with
    `ERR_EHP_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/construction_authorization_gated_by_environmental_review_state
    """
    ctx = _award_with_a_mitigation_required_review()
    validate_error(
        api_client.authorize_construction(ctx["award_id"], ADMIN),
        ApiErrorId.ERR_EHP_NOT_CLEARED,
    )

    cleared = clear_environmental_review(ctx["award_id"], EHP)
    assert cleared["ehp_state"] == "CLEARED"
    assert cleared["pathway"] == "MITIGATION_PLAN_ACCEPTED"
    assert cleared["cleared_by_user_id"] == "ehp-1"
    assert cleared["cleared_at"] is not None

    assert read_award(ctx["award_id"])["award_state"] == "OBLIGATED", (
        "The award itself has not moved between the refusal and the clearance"
    )

    authorized = authorize_construction(ctx["award_id"])
    assert authorized["award_state"] == "CONSTRUCTION_AUTHORIZED"

    for key in ("L2", "L3", "L5"):
        location = read_location(ctx["location_ids"][key])
        assert location["service_state"] == "UNDER_CONSTRUCTION"
        assert location["eligibility_state"] == "AWARD_BOUND"


def test_pro_rata_and_cost_reimbursement_bases_diverge_by_one_cent():
    """Two milestones each covering exactly one location of the same award are
    paid under different rules purely because of `evidence_basis`, and the two
    figures differ by a single cent.

    PRD 3.8: "When `is_final` is false and `evidence_basis` is `BUILD_PROGRESS`,
    the **pro-rata build** variant applies: a gross figure is the award's
    `obligation_amount_cents` multiplied by `verified_location_count` and divided
    by the award's `confirmed_location_count`, rounded half up to a whole cent,
    and the payable amount is the smaller of that gross figure and the remaining
    headroom."
    PRD 3.8: "When `is_final` is false and `evidence_basis` is `INVOICED_COST`,
    the **cost-reimbursement** variant applies: an eligible figure is
    `invoiced_cost_cents` multiplied by the quantity 100 minus the program's
    `min_match_pct`, divided by 100 — the federal share of what was invoiced —
    rounded half up to a whole cent, and the payable amount is the smaller of
    that eligible figure and the remaining headroom."

    Design: Difficulty/dual_variant_calc/milestone_disbursement_pro_rata_vs_cost_reimbursement
    """
    ctx = setup_construction_authorized_award()
    award = read_award(ctx["award_id"])
    assert award["obligation_amount_cents"] == 2025003
    assert award["holdback_cap_cents"] == 1822503
    assert award["confirmed_location_count"] == 3

    build = add_milestone(
        ctx["award_id"], 1, [ctx["location_ids"]["L2"]], evidence_basis="BUILD_PROGRESS"
    )
    submit_milestone_evidence(
        ctx["award_id"], build["id"], [ctx["location_ids"]["L2"]], ctx["subgrantee_id"]
    )
    build_approved = verify_milestone(ctx["award_id"], build["id"], "APPROVED")
    assert build_approved["verified_location_count"] == 1
    assert build_approved["payable_amount_cents"] == 675001, (
        "2025003 times one third is exactly 675001"
    )

    invoiced = add_milestone(
        ctx["award_id"], 2, [ctx["location_ids"]["L3"]], evidence_basis="INVOICED_COST"
    )
    submit_milestone_evidence(
        ctx["award_id"],
        invoiced["id"],
        [ctx["location_ids"]["L3"]],
        ctx["subgrantee_id"],
        invoiced_cost_cents=900002,
    )
    invoiced_approved = verify_milestone(ctx["award_id"], invoiced["id"], "APPROVED")
    assert invoiced_approved["milestone_state"] == "APPROVED"
    assert invoiced_approved["payable_amount_cents"] == 675002, (
        "900002 at a 75 percent federal share is 675001.5, rounded half up to "
        "675002"
    )
    assert (
        build_approved["payable_amount_cents"]
        != invoiced_approved["payable_amount_cents"]
    )

    disburse_milestone(ctx["award_id"], build["id"])
    assert read_award(ctx["award_id"])["disbursed_to_date_cents"] == 675001

    rows, _ = validate_paginated(api_client.list_milestones(ctx["award_id"], ADMIN))
    states = {m["id"]: m["milestone_state"] for m in rows}
    assert states[build["id"]] == "DISBURSED"
    assert states[invoiced["id"]] == "APPROVED"


def test_cost_reimbursement_ignores_the_verified_location_count():
    """The cost-reimbursement figure is driven entirely by the invoice, so a
    milestone covering two of the award's three locations is paid the same as one
    covering a single location — unlike the pro-rata rule, whose gross figure
    would double.

    PRD 3.8: "Identical build progress therefore yields a different payable
    amount under the two bases."
    PRD 3.8: "When `is_final` is false and `evidence_basis` is `INVOICED_COST`,
    the **cost-reimbursement** variant applies: an eligible figure is
    `invoiced_cost_cents` multiplied by the quantity 100 minus the program's
    `min_match_pct`, divided by 100 — the federal share of what was invoiced —
    rounded half up to a whole cent, and the payable amount is the smaller of
    that eligible figure and the remaining headroom."

    Design: Difficulty/dual_variant_calc/milestone_disbursement_pro_rata_vs_cost_reimbursement
    """
    ctx = setup_construction_authorized_award()
    two_locations = [ctx["location_ids"]["L2"], ctx["location_ids"]["L3"]]

    invoiced = add_milestone(
        ctx["award_id"], 1, two_locations, evidence_basis="INVOICED_COST"
    )
    submit_milestone_evidence(
        ctx["award_id"],
        invoiced["id"],
        two_locations,
        ctx["subgrantee_id"],
        invoiced_cost_cents=900002,
    )
    approved = verify_milestone(ctx["award_id"], invoiced["id"], "APPROVED")

    assert approved["verified_location_count"] == 2
    assert approved["payable_amount_cents"] == 675002
    assert approved["payable_amount_cents"] != 1350002, (
        "The pro-rata gross for two of three locations would be 1350002; the "
        "invoiced basis never reads the verified count"
    )

    disbursed = disburse_milestone(ctx["award_id"], invoiced["id"])
    assert disbursed["milestone_state"] == "DISBURSED"
    assert read_award(ctx["award_id"])["disbursed_to_date_cents"] == 675002
