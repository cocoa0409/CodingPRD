"""Who may act: identity resolution, role exclusivity, assignment and duties."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ConsultingApiClient,
    make_client_headers,
    make_headers,
    make_headers_without_user_id,
    make_leadership_headers,
    make_partner_headers,
    make_reviewer_headers,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_two_dp,
)

OUTSIDER_CLIENT_CODE = "NWR005"
LOWER_BUDGET_CENTS = 55000000


def test_an_empty_and_an_unknown_user_id_never_reach_the_role_check(
    api: ConsultingApiClient,
) -> None:
    """Two ways to be nobody, one code, and the real partner then succeeds.

    PRD 2.1: "Every request to this API — without exception, including reads —
    must carry two headers: `X-User-ID`, identifying the acting principal, and
    `X-User-Role`, naming the role the principal is acting in. If either header
    is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). The same code and status are returned when the supplied `X-User-ID`
    cannot be resolved to a known actor of the declared role."

    Design: Corner/rbac/unknown_or_empty_user_id_is_unauthenticated
    """
    sc = fx.build_master_data(api)
    payload = F.opportunity_payload(sc.client_id, sc.partner_id, sc.manager_id)

    validate_error(
        api.create_opportunity(
            payload, make_headers_without_user_id(C.ROLE_ENGAGEMENT_PARTNER)
        ),
        E.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.create_opportunity(
            payload, make_headers(C.NON_EXISTENT_ID, C.ROLE_ENGAGEMENT_PARTNER)
        ),
        E.ERR_UNAUTHENTICATED,
    )

    _, meta = validate_paginated(api.list_opportunities(sc.partner, {}))
    assert_pagination_meta(meta, total_count=0, has_more=False)

    row = validate_success(api.create_opportunity(payload, sc.partner), 201)
    assert_fields(row, status="SCREENING", owner_partner_consultant_id=sc.partner_id)


def test_the_practice_administrator_may_read_but_never_decide(
    api: ConsultingApiClient,
) -> None:
    """Master data and the clock are its whole remit; three writes are refused.

    PRD 2.1: "A practice administrator holds no engagement assignment whatsoever
    and therefore cannot approve, price, review or decide anything on a pursuit
    or an engagement; the role exists to maintain client and consultant master
    data and to drive the logical clock."

    PRD 4: "| GET | `/consulting/engagements/{id}` | Read one engagement with its
    contracted economics and both state dimensions. | EngagementPartner,
    EngagementManager, QualityReviewer, FirmLeadership, PracticeAdmin,
    ClientContact |"

    Design: Corner/rbac/practice_admin_holds_master_data_only
    """
    sc = fx.build_active_engagement(api)
    before = fx.read_opportunity(sc)

    validate_error(
        api.create_opportunity(
            F.opportunity_payload(sc.client_id, sc.partner_id, sc.manager_id),
            sc.admin,
        ),
        E.ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.patch_scope(
            sc.opportunity_id, {"objective_summary": "Rewritten by admin"}, sc.admin
        ),
        E.ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.close_engagement(sc.engagement_id, {}, sc.admin), E.ERR_FORBIDDEN_ROLE
    )

    after = fx.read_opportunity(sc)
    assert_fields(
        after,
        objective_summary=before["objective_summary"],
        version=before["version"],
    )
    # The same identity reads the engagement it is not allowed to close
    engagement = get_success_data(api.get_engagement(sc.engagement_id, sc.admin))
    assert_fields(engagement, delivery_state=C.DELIVERY_ACTIVE)


def test_each_step_of_the_document_chain_belongs_to_exactly_one_role(
    api: ConsultingApiClient,
) -> None:
    """Manager, client and leadership each try someone else's step and are refused.

    PRD 4: "| POST | `/consulting/sows/{id}/submit-internal` | Send a DRAFT
    statement of work into internal review. | EngagementPartner |"

    PRD 4: "| POST | `/consulting/sows/{id}/internal-decision` | Firm-side review
    decision: APPROVE releases to the client, RETURN sends it back to DRAFT. |
    FirmLeadership |"

    PRD 4: "| POST | `/consulting/sows/{id}/client-decision` | Client decision on
    a released statement of work: SIGN, REQUEST_REVISION or DECLINE. |
    ClientContact |"

    PRD 2.1: "If the headers resolve cleanly but the named role is not one the
    target operation admits, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/approval_chain_roles_cannot_take_each_others_step
    """
    sc = fx.build_sow_draft(api)

    validate_error(
        api.submit_sow_internal(sc.sow_id, {}, sc.manager), E.ERR_FORBIDDEN_ROLE
    )
    assert_fields(fx.submit_sow_internal(sc), status="INTERNAL_REVIEW")

    validate_error(
        api.sow_internal_decision(sc.sow_id, {"decision": "APPROVE"}, sc.manager),
        E.ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.sow_internal_decision(
            sc.sow_id, {"decision": "APPROVE"}, sc.client_contact
        ),
        E.ERR_FORBIDDEN_ROLE,
    )
    assert_fields(fx.approve_sow_internally(sc), status="CLIENT_REVIEW")

    validate_error(
        api.sow_client_decision(
            sc.sow_id, F.sign_payload(signature_name="L. Brandt"), sc.leadership
        ),
        E.ERR_FORBIDDEN_ROLE,
    )

    assert_fields(fx.read_sow(sc), status="CLIENT_REVIEW", signed_at=None)
    assert_fields(fx.read_opportunity(sc), status="SOW_ISSUED")


def test_the_owning_partner_cannot_review_its_own_document_in_any_role(
    api: ConsultingApiClient,
) -> None:
    """Correct role, wrong person: duties are checked against identity.

    PRD 2.1: "**Segregation of duties** forbids an actor from reviewing,
    approving or assuring their own work, and is enforced with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) on exactly four operations: `POST
    /consulting/sows/{id}/internal-decision` (the internal reviewer must not be
    the pursuit's `owner_partner_consultant_id`), `POST
    /consulting/change-requests/{id}/leadership-decision` (the leadership
    decision maker must not be the request's `requested_by_consultant_id`), `POST
    /consulting/time-entries/{id}/decision` (the approver must not be the line's
    own `consultant_id`) and `POST /consulting/quality-reviews` (the nominated
    reviewer must be neither the engagement's lead partner nor its engagement
    manager)."

    PRD 3.5: "Either way the reviewing leader must not be the pursuit's owning
    partner, and the `version` advances by 1."

    Design: Corner/rbac/owning_partner_cannot_internally_approve_own_sow
    """
    sc = fx.build_sow_internal_review(api)
    before = fx.read_sow(sc)

    validate_error(
        api.sow_internal_decision(
            sc.sow_id,
            {"decision": "APPROVE"},
            make_leadership_headers(sc.partner_id),
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    assert_fields(
        fx.read_sow(sc), status="INTERNAL_REVIEW", version=before["version"]
    )

    released = get_success_data(
        api.sow_internal_decision(sc.sow_id, {"decision": "APPROVE"}, sc.leadership)
    )

    assert_fields(released, status="CLIENT_REVIEW", version=before["version"] + 1)


def test_a_manager_cannot_clear_a_line_booked_in_their_own_name(
    api: ConsultingApiClient,
) -> None:
    """The only role on the endpoint is still refused on its own hours.

    PRD 3.7: "The deciding manager must be the engagement's
    `engagement_manager_consultant_id` and must not be the line's own
    `consultant_id` — self-approval is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.7: "Only `APPROVED` timesheet lines count towards the burn:
    `SUBMITTED` lines are excluded, and `REJECTED` and `REVERSED` lines are
    excluded too."

    Design: Corner/rbac/consultant_cannot_approve_their_own_timesheet_line
    """
    sc = fx.build_started_engagement(api)
    own_line = fx.log_time(
        sc, 20.0, C.SEED_WEEK_1, consultant_id=sc.manager_id, headers=sc.manager
    )
    partner_line = fx.log_time(sc, 20.0, C.SEED_WEEK_1)

    validate_error(
        api.time_entry_decision(own_line["id"], {"decision": "APPROVE"}, sc.manager),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    assert_fields(
        fx.read_time_entry(sc, own_line["id"]), status=C.TIME_ENTRY_SUBMITTED
    )

    approved = fx.approve_time(sc, partner_line["id"])

    assert_fields(approved, status=C.TIME_ENTRY_APPROVED)
    # 20.00 * 62000 internal cost and 20.00 * 92500 * 0.95 billed
    assert_money(approved, "cost_cents", 1240000)
    assert_money(approved, "billed_value_cents", 1757500)
    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 20.00)
    assert_money(engagement, "burned_cost_cents", 1240000)
    assert_two_dp(fx.read_deliverable(sc, sc.d1_id), "hours_consumed", 20.00)


def test_the_manager_who_raised_a_change_cannot_be_its_leadership_approver(
    api: ConsultingApiClient,
) -> None:
    """The bar is the requester's identity, whichever role that identity wears.

    PRD 3.8: "The request must be at `PENDING_LEADERSHIP_APPROVAL`, and the
    deciding leader must not be the request's `requested_by_consultant_id`,
    otherwise `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.8: "Either decision writes `leadership_approver_consultant_id` from the
    deciding leader's `X-User-ID` and advances the request's `version` by 1."

    Design: Corner/rbac/leadership_cannot_decide_a_change_request_it_raised
    """
    sc = fx.build_burned_engagement(api)
    request = fx.raise_change_request(sc)
    assessed = fx.assess_change_request(sc, request["id"])
    assert_fields(
        assessed,
        status=C.CR_PENDING_LEADERSHIP_APPROVAL,
        requested_by_consultant_id=sc.manager_id,
        leadership_approver_consultant_id=None,
    )

    validate_error(
        api.change_request_leadership_decision(
            request["id"],
            {"decision": "APPROVE"},
            make_leadership_headers(sc.manager_id),
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    assert_fields(
        fx.read_change_request(sc, request["id"]),
        status=C.CR_PENDING_LEADERSHIP_APPROVAL,
        leadership_approver_consultant_id=None,
    )

    approved = fx.leadership_approve_change(sc, request["id"])

    assert_fields(
        approved,
        status=C.CR_PENDING_CLIENT_APPROVAL,
        leadership_approver_consultant_id=sc.leadership_id,
    )
    engagement = fx.read_engagement(sc)
    assert_money(engagement, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(engagement, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)


def test_a_second_client_is_scoped_out_of_the_first_clients_rows(
    api: ConsultingApiClient,
) -> None:
    """The scope check outranks the state check on the assessment endpoint.

    PRD 2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of
    the acting `Client`. Every row a client contact touches must be reachable
    from that client: the `client_id` of an opportunity, the `client_id` of an
    engagement, or the client of the opportunity that owns a deliverable must
    equal `X-User-ID`. A mismatch is rejected with `ERR_CLIENT_SCOPE_VIOLATION`
    (HTTP 403)."

    PRD 2.10: "Authorisation follows in four steps in this order — role
    membership (`ERR_FORBIDDEN_ROLE`), client scoping for a `ClientContact`
    (`ERR_CLIENT_SCOPE_VIOLATION`), assignment binding for a firm actor
    (`ERR_NOT_ASSIGNED_TO_ENGAGEMENT`), and finally segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/rbac/client_contact_cannot_reach_another_clients_rows
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)
    outsider = make_client_headers(
        fx.create_client(
            api, client_code=OUTSIDER_CLIENT_CODE, name="Southbank Utilities"
        )["id"]
    )

    validate_error(
        api.set_deliverable_status(
            sc.d1_id, {"target_status": C.DELIVERABLE_ACCEPTED}, outsider
        ),
        E.ERR_CLIENT_SCOPE_VIOLATION,
    )
    # An ACTIVE engagement could never take an assessment, yet the scope check
    # answers first, so the state error is never reached
    validate_error(
        api.create_satisfaction_assessment(
            F.satisfaction_payload(
                sc.engagement_id,
                delivery_score=1,
                value_score=1,
                communication_score=1,
                would_refer=False,
            ),
            outsider,
        ),
        E.ERR_CLIENT_SCOPE_VIOLATION,
    )

    accepted = fx.set_status(
        sc, sc.d1_id, C.DELIVERABLE_ACCEPTED, headers=sc.client_contact
    )

    assert_fields(accepted, status=C.DELIVERABLE_ACCEPTED)
    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_two_dp(view, "completion_pct", 40.00)
    _, meta = validate_paginated(
        api.list_satisfaction_assessments(
            sc.partner, {"engagement_id": sc.engagement_id}
        )
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_the_right_role_in_the_wrong_person_is_still_unassigned(
    api: ConsultingApiClient,
) -> None:
    """A second partner and a second certified reviewer are both turned away.

    PRD 2.1: "**Assignment binding** requires that a firm actor be the specific
    individual nominated for the operation — the owning partner for partner-side
    pursuit operations, the scoping manager for scope editing and baselining, the
    lead partner for engagement partner operations, the engagement manager for
    delivery operations, and the named reviewer for outcome recording. A firm
    actor of the right role but the wrong identity is rejected with
    `ERR_NOT_ASSIGNED_TO_ENGAGEMENT` (HTTP 403). This rule guards budget
    verification, qualification, scope editing, scope baselining, deliverable
    lead assignment, deliverable status changes, engagement mobilisation,
    begin-closing, timesheet decisions, timesheet reversal, change-request impact
    assessment and quality-review outcome recording."

    PRD 3.9: "Only the nominated reviewer records the outcome, and only inside
    the window."

    Design: Corner/rbac/firm_actors_must_be_the_assigned_individual
    """
    sc = fx.build_started_engagement(api)
    review = fx.schedule_review(sc)
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)
    other_partner = make_partner_headers(
        fx.create_consultant(
            api,
            name="B. Sorensen",
            grade=C.GRADE_PARTNER,
            cost_rate_cents_per_hour=C.SEED_PARTNER_COST_RATE,
        )["id"]
    )
    other_reviewer = make_reviewer_headers(
        fx.create_consultant(
            api,
            name="T. Nowak",
            grade=C.GRADE_CONSULTANT,
            cost_rate_cents_per_hour=C.SEED_REVIEWER_COST_RATE,
            quality_reviewer_certified=True,
        )["id"]
    )

    validate_error(
        api.verify_budget(
            sc.opportunity_id, F.verify_budget_payload(LOWER_BUDGET_CENTS), other_partner
        ),
        E.ERR_NOT_ASSIGNED_TO_ENGAGEMENT,
    )
    validate_error(
        api.record_outcome(review["id"], F.record_outcome_payload(), other_reviewer),
        E.ERR_NOT_ASSIGNED_TO_ENGAGEMENT,
    )

    opportunity = fx.read_opportunity(sc)
    assert_money(opportunity, "verified_budget_cents", C.SEED_VERIFIED_BUDGET_CENTS)
    assert_two_dp(opportunity, "qualification_score_verified", 68.00)

    recorded = fx.record_review_outcome(
        sc, review["id"], C.REVIEW_PASSED, C.SEVERITY_NONE
    )

    assert_fields(
        recorded, status=C.REVIEW_PASSED, reviewer_consultant_id=sc.reviewer_id
    )
    assert fx.list_escalations(sc) == []
