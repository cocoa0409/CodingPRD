"""Individual triggerability of the award, clearance, milestone and audit errors."""

from test_helpers import (
    ApiErrorId,
    api_client,
    add_milestone,
    append_evidence,
    claim_location,
    clear_environmental_review,
    create_application,
    create_award_payload,
    create_compliance_audit_payload,
    create_environmental_determination_payload,
    create_milestone_payload,
    disburse_milestone,
    file_challenge,
    issue_clawback_notice,
    obligate_award,
    open_environmental_review,
    read_application,
    read_award,
    read_location,
    read_program,
    read_subgrantee,
    record_audit_result,
    record_environmental_determination,
    schedule_compliance_audit,
    score_application,
    select_application,
    set_clock,
    setup_challenge_open_program,
    setup_construction_authorized_award,
    setup_obligated_award,
    setup_qualified_subgrantee,
    setup_submitted_application,
    submit_application,
    submit_milestone_evidence,
    submit_milestone_evidence_payload,
    triage_challenge,
    validate_error,
    validate_paginated,
    validate_success,
    verify_milestone,
)
from test_helpers.fixtures import (
    ADMIN,
    ANALYST_OTHER,
    AUDITOR,
    AUDITOR_OTHER,
    EHP,
    advance_program_to_scoring,
    make_subgrantee_headers,
)

UNKNOWN_AWARD = "00000000-0000-4000-8000-0000000000b1"
UNKNOWN_MILESTONE = "00000000-0000-4000-8000-0000000000b2"
UNKNOWN_AUDIT = "00000000-0000-4000-8000-0000000000b3"


def _only_row(response):
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 1
    return rows[0]


def test_existence_outranks_state_on_every_child_of_a_freshly_obligated_award():
    """A newly obligated award has no milestones, no audits and no environmental
    review, so three requests naming children that do not exist report the missing
    child rather than the wrong award phase — and the one request whose ids all
    resolve reports that phase instead.

    PRD 2.12: "**Priorities 20 through 28 — existence,** resolved in this order:
    `program_id` in path or body → `ERR_PROGRAM_NOT_FOUND`; `location_id` in path or
    body → `ERR_LOCATION_NOT_FOUND`; the challenge id in the path →
    `ERR_CHALLENGE_NOT_FOUND`; `subgrantee_id` in path or body →
    `ERR_SUBGRANTEE_NOT_FOUND`; `application_id` in path or body →
    `ERR_APPLICATION_NOT_FOUND`; `award_id` in path or body →
    `ERR_AWARD_NOT_FOUND`; the milestone id in the path, which must belong to the
    award named earlier in the path → `ERR_MILESTONE_NOT_FOUND`; the audit id in the
    path, which must likewise belong to that award, and the environmental-review
    sub-path, which must resolve to an existing review of that award →
    `ERR_AUDIT_NOT_FOUND`; and, for environmental-review sub-actions, the award
    having a review row at all → `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`."
    PRD 3.8: "An attempt to record a determination or to clear a review that was
    never opened is refused with `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`."
    PRD 2.12: "13. **Priority 45 — award state** → `ERR_AWARD_STATE_INVALID`.
    Environmental-review actions require `OBLIGATED`; authorising construction
    requires `OBLIGATED` with a cleared review; milestone operations require
    `CONSTRUCTION_AUTHORIZED` or `IN_CONSTRUCTION`; compliance-audit operations
    require `IN_CONSTRUCTION` or `CLOSED`. `TERMINATED` is terminal."
    PRD 2.12: "When more than one rule could reject a request, the rule with the
    lowest priority number wins and its error is the one returned; evaluation stops at
    the first violation."

    Design: Corner/errors/errors_obligated_award_family_rejected
    """
    ctx = setup_obligated_award(
        location_keys=("L2", "L3"), claims=[("L2", 900002), ("L3", 900002)]
    )
    assert ctx["award"]["award_state"] == "OBLIGATED"
    assert ctx["award"]["obligation_amount_cents"] == 1350002
    assert ctx["award"]["confirmed_location_count"] == 2

    validate_error(
        api_client.get_award(UNKNOWN_AWARD, ADMIN),
        ApiErrorId.ERR_AWARD_NOT_FOUND,
        404,
    )

    owner = make_subgrantee_headers(ctx["subgrantee_id"])
    ghost_milestone = api_client.submit_milestone_evidence(
        ctx["award_id"],
        UNKNOWN_MILESTONE,
        submit_milestone_evidence_payload([ctx["location_ids"]["L2"]]),
        owner,
    )
    validate_error(ghost_milestone, ApiErrorId.ERR_MILESTONE_NOT_FOUND, 404)

    ghost_audit = api_client.record_audit_result(
        ctx["award_id"],
        UNKNOWN_AUDIT,
        {"result": "PASSED", "tested_location_ids": [ctx["location_ids"]["L2"]]},
        AUDITOR_OTHER,
    )
    validate_error(ghost_audit, ApiErrorId.ERR_AUDIT_NOT_FOUND, 404)

    unopened_review = api_client.record_environmental_determination(
        ctx["award_id"],
        create_environmental_determination_payload("CATEGORICAL_EXCLUSION"),
        EHP,
    )
    validate_error(
        unopened_review, ApiErrorId.ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND, 404
    )

    too_early_for_audits = api_client.create_compliance_audit(
        ctx["award_id"],
        create_compliance_audit_payload(
            "SPEED_TEST", "2027-01-05T00:00:00Z", "2027-01-10T00:00:00Z"
        ),
        AUDITOR_OTHER,
    )
    validate_error(too_early_for_audits, ApiErrorId.ERR_AWARD_STATE_INVALID, 409)

    _, milestone_meta = validate_paginated(
        api_client.list_milestones(ctx["award_id"], ADMIN)
    )
    assert milestone_meta["total_count"] == 0
    _, audit_meta = validate_paginated(
        api_client.list_compliance_audits(ctx["award_id"], ADMIN)
    )
    assert audit_meta["total_count"] == 0
    _, review_meta = validate_paginated(
        api_client.list_environmental_review(ctx["award_id"], ADMIN)
    )
    assert review_meta["total_count"] == 0
    assert read_award(ctx["award_id"])["award_state"] == "OBLIGATED"


def test_the_build_plan_refuses_a_stranger_location_a_second_final_and_an_early_draw():
    """A cleared review carries the award into construction, and the build plan then
    guards three separate things: a milestone may only name locations this award
    bound, only one milestone may be the closing draw, and money moves only once a
    milestone has actually been verified.

    PRD 3.8: "A `CATEGORICAL_EXCLUSION` determination moves the review
    `SCREENING → CATEGORICAL_EXCLUSION` and is available only when both
    `tribal_consultation_required` and `shpo_consultation_required` are false — with
    no consultation obligations, clearance needs no mitigation record."
    PRD 2.12: "16. **Priority 48 — environmental review state** →
    `ERR_EHP_STATE_INVALID`. Recording a determination requires `SCREENING` or
    `EA_REQUIRED`; clearing requires `CATEGORICAL_EXCLUSION`, `MITIGATION_REQUIRED`
    or `BLOCKED`."
    PRD 3.8: "Every id in `planned_location_ids` must name a location `AWARD_BOUND`
    under this award, or the request is refused with
    `ERR_LOCATION_NOT_IN_AWARD_SCOPE`."
    PRD 3.8: "At most one milestone per award may have `is_final` true; a second is
    refused with `ERR_FINAL_MILESTONE_CONFLICT`, as is verification of the final
    milestone while any other milestone of the award is still `PLANNED`,
    `EVIDENCE_SUBMITTED` or `HELD`."
    PRD 3.8: "Disbursement is a `ProgramAdmin` act on an `APPROVED` milestone."
    PRD 2.12: "14. **Priority 46 — milestone state** →
    `ERR_MILESTONE_STATE_INVALID`. Submitting evidence requires `PLANNED` or
    `REJECTED`; verification requires `EVIDENCE_SUBMITTED`; disbursement requires
    `APPROVED`. `DISBURSED` and `VOIDED` are terminal, and a `HELD` milestone
    accepts no direct call — it returns to `EVIDENCE_SUBMITTED` only through
    remediation verification on the audit that held it."

    Design: Corner/errors/errors_authorized_award_family_rejected
    """
    ctx = setup_obligated_award(
        location_keys=("L2", "L3", "L5"), claims=[("L2", 900002), ("L3", 900002)]
    )
    unclaimed = ctx["location_ids"]["L5"]
    bound = [ctx["location_ids"]["L2"], ctx["location_ids"]["L3"]]
    assert ctx["award"]["confirmed_location_count"] == 2

    review = open_environmental_review(ctx["award_id"])
    assert review["ehp_state"] == "SCREENING"
    excluded = record_environmental_determination(
        ctx["award_id"], "CATEGORICAL_EXCLUSION"
    )
    assert excluded["ehp_state"] == "CATEGORICAL_EXCLUSION"
    assert excluded["pathway"] == "CATEGORICAL_EXCLUSION"

    settled_pathway = api_client.record_environmental_determination(
        ctx["award_id"], create_environmental_determination_payload("EA_REQUIRED"), EHP
    )
    validate_error(settled_pathway, ApiErrorId.ERR_EHP_STATE_INVALID, 409)

    cleared = clear_environmental_review(ctx["award_id"])
    assert cleared["ehp_state"] == "CLEARED"
    assert cleared["pathway"] == "CATEGORICAL_EXCLUSION"

    authorized = validate_success(
        api_client.authorize_construction(ctx["award_id"], ADMIN)
    )
    assert authorized["award_state"] == "CONSTRUCTION_AUTHORIZED"

    out_of_scope = api_client.create_milestone(
        ctx["award_id"], create_milestone_payload(1, [unclaimed]), ADMIN
    )
    validate_error(out_of_scope, ApiErrorId.ERR_LOCATION_NOT_IN_AWARD_SCOPE, 422)

    closing_draw = add_milestone(ctx["award_id"], 1, bound, is_final=True)
    assert closing_draw["is_final"] is True
    assert closing_draw["milestone_state"] == "PLANNED"

    second_final = api_client.create_milestone(
        ctx["award_id"],
        create_milestone_payload(2, bound, is_final=True),
        ADMIN,
    )
    validate_error(second_final, ApiErrorId.ERR_FINAL_MILESTONE_CONFLICT, 409)

    unverified_draw = api_client.disburse_milestone(
        ctx["award_id"], closing_draw["id"], ADMIN
    )
    validate_error(unverified_draw, ApiErrorId.ERR_MILESTONE_STATE_INVALID, 409)

    stranger = read_location(unclaimed)
    assert stranger["eligibility_state"] == "AFFIRMED"
    assert stranger["awarded_award_id"] is None
    assert stranger["service_state"] == "NOT_BUILT"

    _, milestone_meta = validate_paginated(
        api_client.list_milestones(ctx["award_id"], ADMIN)
    )
    assert milestone_meta["total_count"] == 1
    _, ledger_meta = validate_paginated(
        api_client.list_ledger_entries(ctx["award_id"], ADMIN)
    )
    assert ledger_meta["total_count"] == 1, "Only the obligation entry so far"
    funded = read_award(ctx["award_id"])
    assert funded["disbursed_to_date_cents"] == 0
    assert funded["award_state"] == "CONSTRUCTION_AUTHORIZED"


def test_an_adverse_effect_finding_can_be_neither_cleared_nor_bypassed():
    """A consultation obligation forces the assessment route, and an adverse-effect
    finding blocks the review permanently: the clearance attempt is admitted past the
    state ladder only to be refused on its merits, and the authorisation behind it is
    refused for want of a cleared review.

    PRD 3.8: "An `EA_REQUIRED` determination moves the review
    `SCREENING → EA_REQUIRED` and is available only when at least one of the two
    flags is true: an environmental assessment must precede any clearance."
    PRD 3.8: "An `ADVERSE_EFFECT` determination moves the review
    `EA_REQUIRED → BLOCKED` and stamps nothing else at all: no mitigation record, no
    clearance fields, ever."
    PRD 3.8: "Clearance attempted on a `BLOCKED` review is admitted past the state
    ladder specifically so that it can be refused with
    `ERR_EHP_ADVERSE_EFFECT_BLOCKING`; an adverse-effect finding cannot be cleared."
    PRD 3.8: "Authorisation without a `CLEARED` review is refused with
    `ERR_EHP_NOT_CLEARED`."

    Design: Corner/errors/errors_ehp_adverse_effect_and_not_cleared_rejected
    """
    ctx = setup_obligated_award(
        location_keys=("L2", "L3"), claims=[("L2", 900002), ("L3", 900002)]
    )

    review = open_environmental_review(ctx["award_id"], tribal_consultation_required=True)
    assert review["ehp_state"] == "SCREENING"
    assert review["tribal_consultation_required"] is True
    assert review["shpo_consultation_required"] is False

    assessed = record_environmental_determination(ctx["award_id"], "EA_REQUIRED")
    assert assessed["ehp_state"] == "EA_REQUIRED"

    blocked = record_environmental_determination(ctx["award_id"], "ADVERSE_EFFECT")
    assert blocked["ehp_state"] == "BLOCKED"
    assert blocked["pathway"] == "ADVERSE_EFFECT"
    assert blocked["mitigation_summary"] is None
    assert blocked["cleared_by_user_id"] is None
    assert blocked["cleared_at"] is None

    refused_clearance = api_client.clear_environmental_review(ctx["award_id"], EHP)
    validate_error(
        refused_clearance, ApiErrorId.ERR_EHP_ADVERSE_EFFECT_BLOCKING, 422
    )

    refused_authorisation = api_client.authorize_construction(ctx["award_id"], ADMIN)
    validate_error(refused_authorisation, ApiErrorId.ERR_EHP_NOT_CLEARED, 409)

    still_blocked = _only_row(
        api_client.list_environmental_review(ctx["award_id"], ADMIN)
    )
    assert still_blocked["ehp_state"] == "BLOCKED"
    assert still_blocked["cleared_by_user_id"] is None

    assert read_award(ctx["award_id"])["award_state"] == "OBLIGATED"
    for key in ("L2", "L3"):
        assert read_location(ctx["location_ids"][key])["service_state"] == "NOT_BUILT"


def test_the_two_fiscal_refusals_of_obligation_are_separately_reachable():
    """Two selected applications in one small round hit the two fiscal rungs in turn:
    the first has nothing left to fund once its only claim is deferred out as
    extremely high cost, and the second is affordable in principle but larger than the
    appropriation still uncommitted.

    PRD 3.7: "5. If the retained set is empty, the obligation is refused with
    `ERR_ALL_LOCATIONS_EHCL_DEFERRED`."
    PRD 3.7: "9. If `obligation_amount_cents` exceeds the program's
    `uncommitted_balance_cents`, the obligation is refused with
    `ERR_PROGRAM_FUNDS_EXHAUSTED`."
    PRD 3.7: "When all nine steps pass, an **Award** is created with `award_state`
    `OBLIGATED` and `compliance_state` `COMPLIANT`, its `confirmed_location_count`
    counting the claims now bound to it, `disbursed_to_date_cents` at 0, and
    `certified_location_count` and `failed_location_count` at 0."
    PRD 2.12: "42. **Priority 90 — everything deferred** →
    `ERR_ALL_LOCATIONS_EHCL_DEFERRED`."
    PRD 2.12: "43. **Priority 91 — appropriation exhausted** →
    `ERR_PROGRAM_FUNDS_EXHAUSTED`."

    Design: Corner/errors/errors_ehcl_and_funds_family_rejected
    """
    ctx = setup_challenge_open_program(("L3", "L5"), total_appropriation_cents=1000000)
    assert ctx["program"]["ehcl_threshold_cents"] == 2500000
    assert ctx["program"]["ehcl_waiver_enabled"] is True
    applicant = setup_qualified_subgrantee(ctx["program_id"])

    extreme, _ = setup_submitted_application(
        ctx["program_id"], applicant["id"], [(ctx["location_ids"]["L3"], 3000000)]
    )
    affordable_shape, _ = setup_submitted_application(
        ctx["program_id"],
        applicant["id"],
        [(ctx["location_ids"]["L5"], 2000000)],
    )
    advance_program_to_scoring(ctx["program_id"])
    score_application(extreme["id"])
    score_application(affordable_shape["id"])
    select_application(extreme["id"])
    select_application(affordable_shape["id"])

    nothing_retained = api_client.create_award(
        create_award_payload(extreme["id"]), ADMIN
    )
    validate_error(nothing_retained, ApiErrorId.ERR_ALL_LOCATIONS_EHCL_DEFERRED, 422)

    over_appropriation = api_client.create_award(
        create_award_payload(affordable_shape["id"]), ADMIN
    )
    validate_error(over_appropriation, ApiErrorId.ERR_PROGRAM_FUNDS_EXHAUSTED, 422)

    for application_id in (extreme["id"], affordable_shape["id"]):
        assert read_application(application_id)["application_state"] == "SELECTED", (
            "The move to AWARDED belongs to the successful pass only"
        )
        _, award_meta = validate_paginated(
            api_client.list_application_awards(application_id, ADMIN)
        )
        assert award_meta["total_count"] == 0

    for key in ("L3", "L5"):
        assert read_location(ctx["location_ids"][key])["awarded_award_id"] is None

    program = read_program(ctx["program_id"])
    assert program["obligated_balance_cents"] == 0
    assert program["disbursed_balance_cents"] == 0
    assert program["uncommitted_balance_cents"] == 1000000
    _, ledger_meta = validate_paginated(api_client.list_awards(ADMIN))
    assert ledger_meta["total_count"] == 0


def test_obligation_needs_a_selection_first_and_refuses_a_location_already_bound():
    """Two applications of the same applicant share a location under non-overlapping
    construction windows. The second cannot be obligated while it is merely scored,
    and once selected it still cannot be obligated, because the shared location is
    already bound to the first award.

    PRD 3.7: "The application must be `SELECTED`, or the request is refused with
    `ERR_APPLICATION_NOT_SELECTED`; the program's `scoring_posture` must be `OPEN`;
    the applicant must be `QUALIFIED`; and the application must not already have a
    non-`TERMINATED` award, nor may any claimed location already be `AWARD_BOUND` to
    another award, or the request is refused with `ERR_AWARD_ALREADY_EXISTS`."
    PRD 3.6: "Selection is a `ProgramAdmin` act that moves an application
    `SCORED → SELECTED` while the program is `SCORING` and its `scoring_posture` is
    `OPEN`."
    PRD 3.7: "Every retained claim moves to `AWARD_BOUND` and its location moves on
    the eligibility axis to `AWARD_BOUND` with `awarded_award_id` stamped to the new
    award — `AFFIRMED → AWARD_BOUND` for a location the challenge process left alone,
    and `RECLASSIFIED → AWARD_BOUND` for one a sustained challenge reclassified, and
    in both cases only when a claim on that location for this application is
    `CLAIMED_ELIGIBLE` and either its `claimed_cost_cents` is at most the
    extremely-high-cost threshold or the program has disabled the waiver."

    Design: Corner/errors/errors_award_already_exists_and_not_selected_rejected
    """
    ctx = setup_challenge_open_program(("L2", "L3"))
    shared = ctx["location_ids"]["L2"]
    applicant = setup_qualified_subgrantee(ctx["program_id"])

    winner, _ = setup_submitted_application(
        ctx["program_id"],
        applicant["id"],
        [(shared, 900002), (ctx["location_ids"]["L3"], 900002)],
    )
    latecomer = create_application(
        ctx["program_id"],
        applicant["id"],
        proposed_construction_start="2027-10-01T00:00:00Z",
        proposed_construction_end="2028-10-01T00:00:00Z",
    )
    claim_location(latecomer["id"], shared, applicant["id"], claimed_cost_cents=900002)
    submit_application(latecomer["id"], applicant["id"])

    advance_program_to_scoring(ctx["program_id"])
    score_application(winner["id"])
    select_application(winner["id"])
    award = obligate_award(winner["id"])
    assert award["award_state"] == "OBLIGATED"
    assert award["confirmed_location_count"] == 2
    assert award["obligation_amount_cents"] == 1350002
    assert read_location(shared)["eligibility_state"] == "AWARD_BOUND"
    assert read_location(shared)["awarded_award_id"] == award["id"]

    score_application(latecomer["id"])
    assert read_application(latecomer["id"])["application_state"] == "SCORED"

    not_yet_selected = api_client.create_award(
        create_award_payload(latecomer["id"]), ADMIN
    )
    validate_error(not_yet_selected, ApiErrorId.ERR_APPLICATION_NOT_SELECTED, 409)

    selected = select_application(latecomer["id"])
    assert selected["application_state"] == "SELECTED"

    location_taken = api_client.create_award(
        create_award_payload(latecomer["id"]), ADMIN
    )
    validate_error(location_taken, ApiErrorId.ERR_AWARD_ALREADY_EXISTS, 409)

    assert read_application(latecomer["id"])["application_state"] == "SELECTED"
    shared_claims, shared_meta = validate_paginated(
        api_client.list_location_claims_of_location(shared, ADMIN)
    )
    assert shared_meta["total_count"] == 2
    by_application = {row["application_id"]: row["claim_state"] for row in shared_claims}
    assert by_application[winner["id"]] == "AWARD_BOUND"
    assert by_application[latecomer["id"]] == "CLAIMED_ELIGIBLE"

    awards, award_meta = validate_paginated(api_client.list_awards(ADMIN))
    assert award_meta["total_count"] == 1
    assert awards[0]["id"] == award["id"]
    assert read_program(ctx["program_id"])["obligated_balance_cents"] == 1350002


def test_an_exhausted_holdback_a_buffer_clash_and_two_impossible_settlements():
    """A cost-reimbursement draw eats the whole holdback ceiling, so the next
    milestone is approved at nothing payable; the audit that follows must clear a
    twenty-four-hour buffer and must be recorded by someone other than the last
    verifier; and the clawback it produces refuses a settlement of zero as firmly as
    one a single cent above the recovery.

    PRD 3.8: "Disbursement is a `ProgramAdmin` act on an `APPROVED` milestone. It
    requires the award's `compliance_state` to be `COMPLIANT` or `CURED` and
    `payable_amount_cents` to be strictly greater than 0; a payable amount at or
    below zero — typically because the holdback ceiling is already exhausted — is
    refused with `ERR_NO_DISBURSABLE_AMOUNT`."
    PRD 3.9: "The start must be strictly before the end, and the new window must
    neither overlap nor sit within twenty-four hours of the window of any existing
    non-terminal audit on the same award; a violation is refused with
    `ERR_AUDIT_WINDOW_BUFFER_CONFLICT`."
    PRD 2.6: "Three separations are enforced on `X-User-ID`, and all three surface
    as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.6: "Third, the operator recorded in an award's `last_verifier_user_id` —
    the caller who most recently verified a milestone on that award — may neither
    record an audit result nor verify remediation on the same award."
    PRD 3.9: "`settled_amount_cents` takes the payload's `settled_amount_cents` when
    one is supplied — which must fall between 1 and `recovery_amount_cents`
    inclusive, or the request is refused with `ERR_CLAWBACK_AMOUNT_INVALID` — and
    otherwise defaults to the full `recovery_amount_cents`."
    PRD 2.12: "15. **Priority 47 — audit state** → `ERR_AUDIT_STATE_INVALID`.
    Recording a result requires `SCHEDULED`; issuing a clawback notice requires
    `FAILED` or `APPEALED`; appealing requires `CLAWBACK_NOTICE_ISSUED`; resolving
    with settlement requires `CLAWBACK_NOTICE_ISSUED` while resolving with waiver
    requires `APPEALED`; verifying remediation requires `FAILED`. `PASSED`,
    `REMEDIATED`, `CLAWBACK_SETTLED` and `CLAWBACK_WAIVED` are terminal."

    Design: Corner/errors/errors_holdback_and_clawback_family_rejected
    """
    ctx = setup_construction_authorized_award(
        location_keys=("L2", "L3"), claims=[("L2", 900002), ("L3", 900002)]
    )
    first_scope = [ctx["location_ids"]["L2"]]
    second_scope = [ctx["location_ids"]["L3"]]
    assert ctx["award"]["obligation_amount_cents"] == 1350002
    assert ctx["award"]["holdback_cap_cents"] == 1215002

    invoiced = add_milestone(
        ctx["award_id"], 1, first_scope, evidence_basis="INVOICED_COST"
    )
    submit_milestone_evidence(
        ctx["award_id"],
        invoiced["id"],
        first_scope,
        ctx["subgrantee_id"],
        invoiced_cost_cents=2000000,
    )
    approved_invoice = verify_milestone(ctx["award_id"], invoiced["id"], "APPROVED")
    assert approved_invoice["payable_amount_cents"] == 1215002, (
        "The 1500000 federal share of the invoice is clamped to the headroom"
    )
    disburse_milestone(ctx["award_id"], invoiced["id"])
    exhausted = read_award(ctx["award_id"])
    assert exhausted["disbursed_to_date_cents"] == 1215002
    assert exhausted["award_state"] == "IN_CONSTRUCTION"
    assert exhausted["last_verifier_user_id"] == "auditor-1"

    pro_rata = add_milestone(ctx["award_id"], 2, second_scope)
    submit_milestone_evidence(
        ctx["award_id"], pro_rata["id"], second_scope, ctx["subgrantee_id"]
    )
    approved_progress = verify_milestone(ctx["award_id"], pro_rata["id"], "APPROVED")
    assert approved_progress["milestone_state"] == "APPROVED"
    assert approved_progress["verified_location_count"] == 1
    assert approved_progress["payable_amount_cents"] == 0, (
        "The 675001 gross figure meets zero remaining headroom"
    )

    nothing_payable = api_client.disburse_milestone(
        ctx["award_id"], pro_rata["id"], ADMIN
    )
    validate_error(nothing_payable, ApiErrorId.ERR_NO_DISBURSABLE_AMOUNT, 422)

    set_clock("2027-01-15T00:00:00Z")
    audit = schedule_compliance_audit(
        ctx["award_id"], "SPEED_TEST", "2027-01-01T00:00:00Z", "2027-01-10T00:00:00Z"
    )
    assert audit["audit_state"] == "SCHEDULED"
    assert audit["auditor_user_id"] == "auditor-2"

    inside_buffer = api_client.create_compliance_audit(
        ctx["award_id"],
        create_compliance_audit_payload(
            "SERVICE_AVAILABILITY", "2027-01-10T12:00:00Z", "2027-01-20T00:00:00Z"
        ),
        AUDITOR_OTHER,
    )
    validate_error(inside_buffer, ApiErrorId.ERR_AUDIT_WINDOW_BUFFER_CONFLICT, 409)

    tested = first_scope + second_scope
    by_last_verifier = api_client.record_audit_result(
        ctx["award_id"],
        audit["id"],
        {
            "result": "FAILED",
            "tested_location_ids": tested,
            "failed_location_ids": first_scope,
        },
        AUDITOR,
    )
    validate_error(by_last_verifier, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    failed = record_audit_result(
        ctx["award_id"],
        audit["id"],
        "FAILED",
        tested,
        failed_location_ids=first_scope,
    )
    assert failed["audit_state"] == "FAILED"
    assert failed["noncompliant_share"] == 0.5000
    assert failed["penalty_multiplier"] == 1.25
    assert read_award(ctx["award_id"])["compliance_state"] == "NONCOMPLIANT"
    suspended = read_subgrantee(ctx["subgrantee_id"])
    assert suspended["capability_state"] == "SUSPENDED"
    assert suspended["open_noncompliance_count"] == 1

    noticed = issue_clawback_notice(ctx["award_id"], audit["id"])
    assert noticed["audit_state"] == "CLAWBACK_NOTICE_ISSUED"
    assert noticed["recovery_amount_cents"] == 759376
    assert noticed["notice_issued_by_user_id"] == "auditor-2"

    below_floor = api_client.resolve_clawback(
        ctx["award_id"],
        audit["id"],
        {"resolution": "SETTLED", "settled_amount_cents": 0},
        ADMIN,
    )
    validate_error(below_floor, ApiErrorId.ERR_CLAWBACK_AMOUNT_INVALID, 422)

    above_recovery = api_client.resolve_clawback(
        ctx["award_id"],
        audit["id"],
        {"resolution": "SETTLED", "settled_amount_cents": 759377},
        ADMIN,
    )
    validate_error(above_recovery, ApiErrorId.ERR_CLAWBACK_AMOUNT_INVALID, 422)

    remediation_by_last_verifier = api_client.verify_remediation(
        ctx["award_id"], audit["id"], AUDITOR
    )
    validate_error(
        remediation_by_last_verifier, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403
    )

    already_decided = api_client.record_audit_result(
        ctx["award_id"],
        audit["id"],
        {"result": "PASSED", "tested_location_ids": tested},
        AUDITOR_OTHER,
    )
    validate_error(already_decided, ApiErrorId.ERR_AUDIT_STATE_INVALID, 409)

    resting = _only_row(api_client.list_compliance_audits(ctx["award_id"], ADMIN))
    assert resting["audit_state"] == "CLAWBACK_NOTICE_ISSUED"
    assert resting["settled_amount_cents"] is None
    assert resting["recovery_amount_cents"] == 759376

    _, ledger_meta = validate_paginated(
        api_client.list_ledger_entries(ctx["award_id"], ADMIN)
    )
    assert ledger_meta["total_count"] == 2, "One obligation and one disbursement"
    assert read_award(ctx["award_id"])["disbursed_to_date_cents"] == 1215002


def test_one_late_sustain_halts_both_selection_and_obligation_across_the_program():
    """A determination that lands after scoring has opened reclassifies a location on
    a third application, staling that application's sheet and restricting the whole
    programme's posture — so an award that was ready to obligate and an application
    that was ready to be selected are both refused, neither of them the one the
    challenge touched.

    PRD 2.9: "Both `FROZEN` and `RESTRICTED` block application selection and award
    obligation with `ERR_SCORING_POSTURE_RESTRICTED`; only `OPEN` permits them."
    PRD 3.3: "- **Hop 2**, caused by hop 1. Because the location's classification is
    now `UNSERVED` or `UNDERSERVED`, every location claim on that location sitting in
    `CLAIMED_INELIGIBLE` flips to `CLAIMED_ELIGIBLE`. For each owning application,
    `confirmed_location_count` rises by one, `eligible_project_cost_cents` rises by
    that claim's `claimed_cost_cents`, and `final_cost_per_location_cents` is
    recomputed."
    PRD 3.3: "- **Hop 3**, caused by hop 2. Because that application's confirmed
    location count changed, each of its score sheets in `score_state` `FINAL` moves
    to `STALE`, the application moves `SCORED → RESCORE_REQUIRED` with
    `rescore_required_reason` set to `CHALLENGE_RECLASSIFICATION`, and the
    application's `version` increments by one."
    PRD 3.3: "- **Hop 4**, caused by hop 3. Because the program's
    `stale_score_sheet_count` has now reached at least one, the program's
    `scoring_posture` moves `OPEN → RESTRICTED`, which blocks award obligation across
    the entire program until every stale sheet has been superseded."

    Design: Corner/errors/errors_scoring_posture_restricted_blocks_select_and_obligate_rejected
    """
    ctx = setup_challenge_open_program(("L3", "L1", "L5"))
    untouched = ctx["location_ids"]["L3"]
    contested = ctx["location_ids"]["L1"]
    neighbour = ctx["location_ids"]["L5"]
    assert ctx["locations"]["L1"]["classification_status"] == "SERVED"

    challenge = file_challenge(
        ctx["program_id"],
        contested,
        asserted_classification="UNDERSERVED",
        challenger_type="COMMUNITY",
        rationale="Two households report no service at this address.",
    )
    append_evidence(challenge["id"], "SERVICE_DENIAL_LETTER", "2026-06-01T00:00:00Z")
    append_evidence(challenge["id"], "SPEED_TEST", "2026-07-01T00:00:00Z")
    triaged = triage_challenge(challenge["id"])
    assert triaged["challenge_state"] == "REBUTTAL_OPEN"
    assert triaged["evidence_sufficiency_score"] == 45.00
    assert triaged["rebuttal_strength_score"] == 0.00

    applicant = setup_qualified_subgrantee(ctx["program_id"])
    ready_to_obligate, _ = setup_submitted_application(
        ctx["program_id"], applicant["id"], [(untouched, 900002)]
    )
    ready_to_select = create_application(
        ctx["program_id"],
        applicant["id"],
        proposed_construction_start="2027-10-01T00:00:00Z",
        proposed_construction_end="2028-10-01T00:00:00Z",
    )
    claim_location(
        ready_to_select["id"], untouched, applicant["id"], claimed_cost_cents=900002
    )
    submit_application(ready_to_select["id"], applicant["id"])
    bystander, bystander_claims = setup_submitted_application(
        ctx["program_id"], applicant["id"], [(neighbour, 900002), (contested, 900002)]
    )
    assert {row["claim_state"] for row in bystander_claims} == {
        "CLAIMED_ELIGIBLE",
        "CLAIMED_INELIGIBLE",
    }

    advance_program_to_scoring(ctx["program_id"])
    assert read_program(ctx["program_id"])["scoring_posture"] == "OPEN"
    obligation_sheet = score_application(ready_to_obligate["id"])
    selection_sheet = score_application(ready_to_select["id"])
    bystander_sheet = score_application(bystander["id"])
    select_application(ready_to_obligate["id"])

    sustained = validate_success(
        api_client.determine_challenge(
            challenge["id"],
            {"outcome": "SUSTAINED", "determination_note": "Denials corroborated."},
            ANALYST_OTHER,
        )
    )
    assert sustained["challenge_state"] == "SUSTAINED"

    reclassified = read_location(contested)
    assert reclassified["eligibility_state"] == "RECLASSIFIED"
    assert reclassified["classification_status"] == "UNDERSERVED"
    assert reclassified["classification_source"] == "CHALLENGE_DETERMINATION"

    widened = read_application(bystander["id"])
    assert widened["application_state"] == "RESCORE_REQUIRED"
    assert widened["rescore_required_reason"] == "CHALLENGE_RECLASSIFICATION"
    assert widened["confirmed_location_count"] == 2
    assert widened["eligible_project_cost_cents"] == 1800004

    sheets, _ = validate_paginated(
        api_client.list_application_score_sheets(bystander["id"], ADMIN)
    )
    assert [row["score_state"] for row in sheets if row["id"] == bystander_sheet["id"]] == [
        "STALE"
    ]

    restricted = read_program(ctx["program_id"])
    assert restricted["stale_score_sheet_count"] == 1
    assert restricted["scoring_posture"] == "RESTRICTED"

    blocked_obligation = api_client.create_award(
        create_award_payload(ready_to_obligate["id"]), ADMIN
    )
    validate_error(
        blocked_obligation, ApiErrorId.ERR_SCORING_POSTURE_RESTRICTED, 409
    )

    blocked_selection = api_client.select_application(ready_to_select["id"], ADMIN)
    validate_error(blocked_selection, ApiErrorId.ERR_SCORING_POSTURE_RESTRICTED, 409)

    assert read_application(ready_to_obligate["id"])["application_state"] == "SELECTED"
    assert read_application(ready_to_select["id"])["application_state"] == "SCORED"
    for sheet_owner, sheet in (
        (ready_to_obligate["id"], obligation_sheet),
        (ready_to_select["id"], selection_sheet),
    ):
        rows, _ = validate_paginated(
            api_client.list_application_score_sheets(sheet_owner, ADMIN)
        )
        assert [row["score_state"] for row in rows if row["id"] == sheet["id"]] == [
            "FINAL"
        ]

    _, award_meta = validate_paginated(api_client.list_awards(ADMIN))
    assert award_meta["total_count"] == 0
    held = read_program(ctx["program_id"])
    assert held["obligated_balance_cents"] == 0
    assert held["uncommitted_balance_cents"] == 100000000
