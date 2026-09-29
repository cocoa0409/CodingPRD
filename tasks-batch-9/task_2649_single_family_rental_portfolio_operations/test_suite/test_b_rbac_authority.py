"""Who may call an endpoint, and who may decide the thing they themselves submitted.

Two separate controls are exercised here and they sit at different ranks. Authority is a
role check that runs before the system even looks up the row, so a forbidden caller on a
non-existent home is told 403 rather than 404. Segregation of duties is a principal check
that runs deep in the ladder, on a request that is otherwise perfectly authorised.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_page_meta,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    ASSET_ACQUIRED,
    ASSET_PIPELINE,
    CASE_APPROVED,
    CASE_SUBMITTED,
    CLOCK_AUG_01,
    OBLIGATION_RESOLUTION_SUBMITTED,
    OBLIGATION_RESOLVED,
    POSTURE_RESTRICTED,
)
from test_helpers.test_users import (
    ACQUISITION_ANALYST_USER_ID,
    ROLE_INVESTMENT_COMMITTEE,
    make_headers,
)

MISSING_HOME_ID = "00000000-0000-0000-0000-000000000000"


def test_the_wrong_role_is_refused_even_on_a_home_that_does_not_exist(api):
    """Four denials, nothing written, and then the committee's own call carries the case.

    PRD SS2.1: "When both headers are well-formed but the named role is not among the roles
    authorised for the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."  The
    ladder puts that check above every lookup -- PRD SS2.7: "**Rank 40 -- role not permitted.**
    `ERR_UNAUTHORIZED` (403), on every endpoint" precedes "**Rank 54 -- unknown home.**
    `ERR_HOME_NOT_FOUND` (404), on every endpoint carrying `homeId` in the path or `home_id` in the
    payload", and "**Evaluation stops at the first violated rule, and only that rule's error is
    reported.**"  The three endpoints are single-role by PRD SS4's table: `POST
    /underwriting-cases/{caseId}/decision` and `POST /homes/{homeId}/disposition-decision` are both
    `InvestmentCommittee`, and `POST /vendors` is `VendorManager`.  The accepted decision is PRD
    SS3.2's: "An approval moves the case `SUBMITTED -> APPROVED`, stamps `decided_by_user_id`, and
    cascades: the home advances `PIPELINE -> ACQUIRED` and its `leasing_posture` is recomputed, which
    for both `PIPELINE` and `ACQUIRED` leaves it `RESTRICTED` unless some freezing input applies."

    Design: Corner/rbac/exclusive_operations_deny_other_roles_with_unauthorized
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_general())
    home = x.create_home(api, market["id"])
    case = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"], home["version"], [f.scope_line(paint["id"], 1)]
            ),
            x.ANALYST,
        )
    )
    ok(api.submit_underwriting_case(case["id"], {}, x.ANALYST))

    failed(
        api.decide_underwriting_case(case["id"], f.decision_payload("APPROVE"), x.ANALYST_2),
        ERR_UNAUTHORIZED,
    )
    failed(api.create_vendor(f.vendor_payload(market["id"]), x.OPS), ERR_UNAUTHORIZED)
    failed(
        api.disposition_decision(home["id"], f.approve_sale_payload(), x.OPS),
        ERR_UNAUTHORIZED,
    )
    failed(
        api.disposition_decision(MISSING_HOME_ID, f.approve_sale_payload(), x.OPS),
        ERR_UNAUTHORIZED,
    )

    assert_fields(
        ok(api.get_underwriting_case(case["id"], x.ANALYST)), status=CASE_SUBMITTED
    )
    assert_fields(ok(api.get_home(home["id"], x.ANALYST)), asset_status=ASSET_PIPELINE)
    _, meta = page(api.list_vendors(x.VENDOR_MANAGER, {"market_id": market["id"]}))
    assert_page_meta(meta, total_count=0)

    decided = ok(
        api.decide_underwriting_case(case["id"], f.decision_payload("APPROVE"), x.COMMITTEE)
    )
    assert_fields(decided, status=CASE_APPROVED, decided_by_user_id="ic-1")
    assert_fields(
        ok(api.get_home(home["id"], x.ANALYST)),
        asset_status=ASSET_ACQUIRED,
        leasing_posture=POSTURE_RESTRICTED,
    )


def test_the_submitter_may_not_decide_its_own_case_nor_review_its_own_evidence(api):
    """The same control fires twice, keyed on the principal and not on the role.

    PRD SS3.2: "All three require the case to be in `SUBMITTED`, and all three require that the
    deciding `InvestmentCommittee` member's `X-User-ID` differs from the case's
    `submitted_by_user_id`; a self-decision is refused with `ERR_SEGREGATION_OF_DUTIES`."  PRD SS3.9
    says the same of the cure: "Because this is the segregation-of-duties control, the reviewer may
    not be the submitter: a caller whose `X-User-ID` equals the obligation's `submitted_by_user_id`
    is refused with `ERR_SEGREGATION_OF_DUTIES`."  The control sits well below the role check -- PRD
    SS2.7: "**Rank 350 -- segregation of duties.** `ERR_SEGREGATION_OF_DUTIES` (409) on the
    underwriting-case decision and on compliance review-resolution" -- so the refusal is a conflict
    and not a denial.  A refused decision writes nothing, PRD SS2.9: "if a guard rejects the
    operation, nothing at all is written, including the cascade targets", the stamp starting life
    empty per PRD SS3.2: "The new case is created in `DRAFT` with `revision_round` 0 and both
    `submitted_by_user_id` and `decided_by_user_id` the empty string".  Acceptance is PRD SS3.9's:
    "`ACCEPT` moves it `RESOLUTION_SUBMITTED` -> `RESOLVED`",
    after which clause 4 of PRD SS2.8 no longer holds and clause 5 -- "if `asset_status` is
    `PIPELINE` or `ACQUIRED`, the posture is `RESTRICTED`" -- decides.

    Design: Corner/rbac/segregation_of_duties_blocks_the_submitter_from_deciding
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_general())
    home = x.create_home(api, market["id"])
    case = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"], home["version"], [f.scope_line(paint["id"], 1)]
            ),
            x.ANALYST,
        )
    )
    ok(api.submit_underwriting_case(case["id"], {}, x.ANALYST))

    obligation = x.planned_obligation(
        api,
        home["id"],
        severity="MAJOR",
        planned_resolution_on="2026-08-20",
        description="Peeling exterior trim",
        due_on="2026-10-31",
    )
    ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="trim-repaint-441"),
            x.COMPLIANCE,
        )
    )

    committee_analyst = make_headers(
        ACQUISITION_ANALYST_USER_ID, ROLE_INVESTMENT_COMMITTEE
    )
    failed(
        api.decide_underwriting_case(
            case["id"], f.decision_payload("APPROVE"), committee_analyst
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    untouched = ok(api.get_underwriting_case(case["id"], x.ANALYST))
    assert_fields(untouched, status=CASE_SUBMITTED)
    assert_absent_or_empty(untouched, "decided_by_user_id")

    decided = ok(
        api.decide_underwriting_case(case["id"], f.decision_payload("APPROVE"), x.COMMITTEE)
    )
    assert_fields(
        decided,
        status=CASE_APPROVED,
        submitted_by_user_id=ACQUISITION_ANALYST_USER_ID,
        decided_by_user_id="ic-1",
    )

    failed(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload("ACCEPT", review_note="Reviewing my own work"),
            x.COMPLIANCE,
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert_fields(
        ok(api.get_compliance_obligation(obligation["id"], x.COMPLIANCE)),
        status=OBLIGATION_RESOLUTION_SUBMITTED,
    )

    resolved = ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload("ACCEPT", review_note="Trim repainted to palette"),
            x.COMPLIANCE_2,
        )
    )
    assert_fields(resolved, status=OBLIGATION_RESOLVED)
    assert_fields(
        ok(api.get_home(home["id"], x.COMPLIANCE)),
        asset_status=ASSET_ACQUIRED,
        leasing_posture=POSTURE_RESTRICTED,
    )
