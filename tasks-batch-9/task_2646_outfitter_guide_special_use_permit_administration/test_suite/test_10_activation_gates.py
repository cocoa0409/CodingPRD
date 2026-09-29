"""The activation gate: one linked plan status at a time, and the pinned tier order.

Covers the operating-plan dependency walked across all four non-approved
statuses, and the seven-precondition ladder revealed one error at a time.
"""
from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    SPECIALIST_USER_ID,
    approve_operating_plan,
    authorize_guide,
    create_operating_plan,
    create_qualified_guide,
    file_bond,
    file_insurance_certificate,
    read_operating_plan,
    read_outfitter,
    read_permit,
    setup_issued_permit,
    staff_roster_to_party_size,
    start_plan_review,
    submit_operating_plan,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]

RITA_LEAD_WFR_7 = {
    "full_name": "Rita Long",
    "qualification_level": "LEAD",
    "first_aid_cert_type": "WFR",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 7,
}
SAM_LEAD_WFR_7 = {
    "full_name": "Sam Vale",
    "qualification_level": "LEAD",
    "first_aid_cert_type": "WFR",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 7,
}


def _permit_ready_but_for_its_plan():
    """An ISSUED permit whose only unmet activation precondition is the status of
    its 2027 operating plan, which is left in DRAFT."""
    context = setup_issued_permit()
    permit = context["permit"]
    outfitter_id = context["outfitter"]["id"]
    staff_roster_to_party_size(context)
    file_insurance_certificate(
        permit["id"],
        outfitter_id,
        coverage_amount_cents=context["use_area"]["min_liability_coverage_cents"],
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    file_bond(
        permit["id"],
        outfitter_id,
        bond_amount_cents=1_000_000,
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    context["operating_plan"] = create_operating_plan(permit["id"], outfitter_id, 2027)
    return context


def _assert_only_the_plan_is_pending(permit_id):
    permit = read_permit(permit_id)
    assert permit["administrative_status"] == "ISSUED"
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["insurance_current"] is True
    assert permit["bond_current"] is True
    assert permit["indemnification_acknowledged"] is True
    assert permit["authorized_client_capacity_total"] == 12


def test_activation_is_refused_from_every_non_approved_plan_status_with_one_error():
    """PRD §3.4: "an operating plan for the calendar year of `term_start_date` must exist against
    this permit in `APPROVED`, else `ERR_OPERATING_PLAN_NOT_APPROVED`"
    PRD §3.5: "A new plan enters `DRAFT` with `revision_round` 0, `deficiency_sections` an empty
    array, and `reviewed_by_user_id`, `approved_by_user_id` and `rejection_reason_code` all null."
    PRD §3.5: "A `PermitSpecialist` or an `AuthorizedOfficer` takes a `SUBMITTED` plan under
    review, moving it `SUBMITTED → UNDER_REVIEW` and stamping `reviewed_by_user_id` with the
    acting `X-User-ID`."
    PRD §3.5: "A reviewer may return the plan to the holder, moving it `UNDER_REVIEW →
    REVISION_REQUESTED` with the `deficiency_sections` array naming the sections at fault"
    PRD §3.5: "An `AuthorizedOfficer` or `ProgramAdministrator` may approve the plan, moving it
    `UNDER_REVIEW → APPROVED` and stamping `approved_by_user_id` from the acting `X-User-ID` —
    this is what unblocks activation for that `plan_year`."

    Design: Difficulty/cross_entity_state_dependency/permit_activation_gated_by_operating_plan_status
    """
    context = _permit_ready_but_for_its_plan()
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    plan_id = context["operating_plan"]["id"]

    assert context["operating_plan"]["status"] == "DRAFT"
    assert context["operating_plan"]["completeness_score"] == 100.0
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_APPROVED,
    )
    _assert_only_the_plan_is_pending(permit_id)

    assert submit_operating_plan(plan_id, outfitter_id)["status"] == "SUBMITTED"
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_APPROVED,
    )
    _assert_only_the_plan_is_pending(permit_id)

    under_review = start_plan_review(plan_id, SPECIALIST_USER_ID)
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["reviewed_by_user_id"] == SPECIALIST_USER_ID
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_APPROVED,
    )
    _assert_only_the_plan_is_pending(permit_id)

    returned = validate_success(
        api_client.request_operating_plan_revision(
            plan_id, {"deficiency_sections": ["stock_section"]}, SPECIALIST
        )
    )
    assert returned["status"] == "REVISION_REQUESTED"
    assert returned["revision_round"] == 1
    assert returned["deficiency_sections"] == ["stock_section"]
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_APPROVED,
    )
    _assert_only_the_plan_is_pending(permit_id)

    resubmitted = submit_operating_plan(plan_id, outfitter_id)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["deficiency_sections"] == []
    assert resubmitted["reviewed_by_user_id"] is None
    start_plan_review(plan_id, SPECIALIST_USER_ID)
    approved = approve_operating_plan(plan_id, OFFICER_USER_ID)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == OFFICER_USER_ID

    activated = validate_success(api_client.activate_permit(permit_id, OFFICER))
    assert activated["administrative_status"] == "ACTIVE"
    assert activated["compliance_status"] == "COMPLIANT"
    assert activated["authorized_client_capacity_total"] == 12
    holder = read_outfitter(outfitter_id)
    assert holder["active_permit_count"] == 1
    assert holder["status"] == "PERMITTED"


def test_only_an_approved_plan_for_the_terms_own_calendar_year_unblocks_the_gate():
    """PRD §3.4: "an operating plan for the calendar year of `term_start_date` must exist against
    this permit in `APPROVED`, else `ERR_OPERATING_PLAN_NOT_APPROVED`"
    PRD §3.5: "Only one plan may occupy a given permit-and-`plan_year` pair in any status other
    than `REJECTED`; a second filing is `ERR_DUPLICATE_PLAN_YEAR` (HTTP 409)."
    PRD §3.5: "Or they may reject it with a `rejection_reason_code`, moving it `UNDER_REVIEW →
    REJECTED`, which frees the permit-and-`plan_year` slot for a fresh filing. Both `APPROVED` and
    `REJECTED` are terminal."

    Design: Difficulty/cross_entity_state_dependency/permit_activation_gated_by_operating_plan_status
    """
    context = setup_issued_permit()
    permit = context["permit"]
    permit_id = permit["id"]
    outfitter_id = context["outfitter"]["id"]
    staff_roster_to_party_size(context)
    file_insurance_certificate(
        permit_id,
        outfitter_id,
        coverage_amount_cents=context["use_area"]["min_liability_coverage_cents"],
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    file_bond(
        permit_id,
        outfitter_id,
        bond_amount_cents=1_000_000,
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    assert permit["term_start_date"].startswith("2027-01-01")

    wrong_year = create_operating_plan(permit_id, outfitter_id, 2028)
    submit_operating_plan(wrong_year["id"], outfitter_id)
    start_plan_review(wrong_year["id"], SPECIALIST_USER_ID)
    assert approve_operating_plan(wrong_year["id"], OFFICER_USER_ID)["status"] == "APPROVED"
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_APPROVED,
    )
    _assert_only_the_plan_is_pending(permit_id)

    doomed = create_operating_plan(permit_id, outfitter_id, 2027)
    submit_operating_plan(doomed["id"], outfitter_id)
    start_plan_review(doomed["id"], SPECIALIST_USER_ID)
    rejected = validate_success(
        api_client.reject_operating_plan(
            doomed["id"], {"rejection_reason_code": "INADEQUATE_STOCK_CONTAINMENT"}, OFFICER
        )
    )
    assert rejected["status"] == "REJECTED"
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_APPROVED,
    )

    replacement = create_operating_plan(permit_id, outfitter_id, 2027)
    assert replacement["id"] != doomed["id"], "a REJECTED plan frees the year slot"
    submit_operating_plan(replacement["id"], outfitter_id)
    start_plan_review(replacement["id"], SPECIALIST_USER_ID)
    approve_operating_plan(replacement["id"], OFFICER_USER_ID)

    activated = validate_success(api_client.activate_permit(permit_id, OFFICER))
    assert activated["administrative_status"] == "ACTIVE"
    assert read_operating_plan(wrong_year["id"])["plan_year"] == 2028
    assert read_outfitter(outfitter_id)["status"] == "PERMITTED"


def test_the_activation_ladder_reveals_one_precondition_at_a_time_in_the_pinned_order():
    """PRD §3.4: "Then, in this fixed order: the permit's `authorized_client_capacity_total` must
    be at least its area's `party_size_max`, else `ERR_CLIENT_GUIDE_RATIO_UNMET` — the
    client-to-guide ratio must be satisfiable for the largest party the area allows; an operating
    plan for the calendar year of `term_start_date` must exist against this permit in `APPROVED`,
    else `ERR_OPERATING_PLAN_NOT_APPROVED`; `indemnification_acknowledged` must be true, else
    `ERR_INDEMNIFICATION_NOT_ACKNOWLEDGED`; the active certificate set must leave no uncovered
    calendar day inside the term, else `ERR_INSURANCE_COVERAGE_GAP`; general-liability coverage
    must reach the area's minimum with the endorsement in place, else
    `ERR_INSURANCE_COVERAGE_INSUFFICIENT`; an active bond must meet the required assurance, else
    `ERR_BOND_INSUFFICIENT`; and no fee assessment may carry an outstanding balance, else
    `ERR_FEE_BALANCE_OUTSTANDING`."
    PRD §2.5: "When a permit is activated or reinstated, the three fiscal checks run as: coverage
    sufficiency (`ERR_INSURANCE_COVERAGE_INSUFFICIENT`), then bond sufficiency
    (`ERR_BOND_INSUFFICIENT`), then outstanding balance (`ERR_FEE_BALANCE_OUTSTANDING`)."
    PRD §3.6: "Continuity is checked at a higher priority than sufficiency, but it has nothing to
    measure against an empty set: when the permit holds *no* `ACTIVE` general-liability
    certificate at all, the answer is the sufficiency error rather than the gap error."
    PRD §3.6: "Its `authorized_client_capacity` is computed once, at this instant, as the lesser of
    the area's `max_clients_per_guide` and the guide's `base_client_capacity`, and is then
    **frozen**"
    PRD §3.4: "The indemnification acknowledgement is a small, separate, holder-only act with
    outsized consequences: the holder accepts the hold-harmless and indemnification clause,
    `indemnification_acknowledged` flips to true, and it is irreversible once set."

    Design: Corner/validations/activation_gates_are_revealed_one_tier_at_a_time_in_the_pinned_order
    """
    context = setup_issued_permit(
        permit_overrides={"indemnification_acknowledged": False}
    )
    permit = context["permit"]
    permit_id = permit["id"]
    outfitter_id = context["outfitter"]["id"]
    holder = context["holder_headers"]
    assert permit["indemnification_acknowledged"] is False
    assert permit["authorized_client_capacity_total"] == 0
    assert context["use_area"]["party_size_max"] == 12

    rita = create_qualified_guide(outfitter_id, **RITA_LEAD_WFR_7)
    sam = create_qualified_guide(outfitter_id, **SAM_LEAD_WFR_7)
    assert rita["base_client_capacity"] == 10 and sam["base_client_capacity"] == 10

    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_CLIENT_GUIDE_RATIO_UNMET,
    )

    first = authorize_guide(permit_id, rita["id"], outfitter_id)
    assert first["authorized_client_capacity"] == 8
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_CLIENT_GUIDE_RATIO_UNMET,
    )

    authorize_guide(permit_id, sam["id"], outfitter_id)
    plan = create_operating_plan(permit_id, outfitter_id, 2027)
    submit_operating_plan(plan["id"], outfitter_id)
    start_plan_review(plan["id"], SPECIALIST_USER_ID)
    approve_operating_plan(plan["id"], OFFICER_USER_ID)
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 16

    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_INDEMNIFICATION_NOT_ACKNOWLEDGED,
    )

    acknowledged = validate_success(
        api_client.acknowledge_indemnification(permit_id, holder)
    )
    assert acknowledged["indemnification_acknowledged"] is True

    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_INSURANCE_COVERAGE_INSUFFICIENT,
    )

    file_insurance_certificate(
        permit_id,
        outfitter_id,
        carrier_name="Cascade Mutual",
        coverage_amount_cents=100_000_000,
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    validate_error(
        api_client.activate_permit(permit_id, OFFICER),
        ApiErrorId.ERR_BOND_INSUFFICIENT,
    )

    bond = file_bond(
        permit_id,
        outfitter_id,
        bond_amount_cents=1_000_000,
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    assert bond["required_amount_cents"] == 1_000_000

    activated = validate_success(api_client.activate_permit(permit_id, OFFICER))
    assert activated["administrative_status"] == "ACTIVE"
    assert activated["compliance_status"] == "COMPLIANT"
    assert activated["insurance_current"] is True
    assert activated["bond_current"] is True
    assert activated["authorized_client_capacity_total"] == 16
    holder_row = read_outfitter(outfitter_id)
    assert holder_row["status"] == "PERMITTED"
    assert holder_row["active_permit_count"] == 1
