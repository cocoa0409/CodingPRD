"""Error identity: which code, from which collection, at which priority."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_two_dp,
)

DECLINE_NOTE = "Budget pulled for the year"
RETURN_NOTE = "Assumptions too thin for a fixed fee"
REJECT_NOTE = "Not funded this year"
BAD_DECISION_PROCESS = "BOARD_VOTE"


def test_the_same_unknown_id_names_six_different_collections(
    api: ConsultingApiClient,
) -> None:
    """One placeholder identifier, six paths, six distinct 404 codes.

    PRD 2.5: "A missing row yields HTTP 404 with the error code specific to the
    entity that was not found: `ERR_CLIENT_NOT_FOUND`,
    `ERR_CONSULTANT_NOT_FOUND`, `ERR_OPPORTUNITY_NOT_FOUND`,
    `ERR_DELIVERABLE_NOT_FOUND`, `ERR_SOW_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
    `ERR_TIME_ENTRY_NOT_FOUND`, `ERR_QUALITY_REVIEW_NOT_FOUND`,
    `ERR_RISK_ESCALATION_NOT_FOUND` or `ERR_SATISFACTION_ASSESSMENT_NOT_FOUND`."

    Design: Corner/errors/unknown_path_id_returns_the_entity_specific_not_found
    """
    sc = fx.build_master_data(api)
    missing = C.NON_EXISTENT_ID

    probes = [
        (api.get_sow(missing, sc.partner), E.ERR_SOW_NOT_FOUND),
        (api.get_engagement(missing, sc.partner), E.ERR_ENGAGEMENT_NOT_FOUND),
        (
            api.get_change_request(missing, sc.manager),
            E.ERR_CHANGE_REQUEST_NOT_FOUND,
        ),
        (api.get_quality_review(missing, sc.reviewer), E.ERR_QUALITY_REVIEW_NOT_FOUND),
        (
            api.get_risk_escalation(missing, sc.leadership),
            E.ERR_RISK_ESCALATION_NOT_FOUND,
        ),
        (api.get_time_entry(missing, sc.manager), E.ERR_TIME_ENTRY_NOT_FOUND),
    ]

    for response, expected_error in probes:
        validate_error(response, expected_error)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == expected_error
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_four_wrong_state_refusals_each_name_their_own_entity(
    api: ConsultingApiClient,
) -> None:
    """A document, a timesheet line, a checkpoint and a change request, four codes.

    PRD 3.5: "Its terminal states are `SIGNED`, `DECLINED` and `SUPERSEDED`, and
    any operation attempted from a state that does not permit it is refused with
    `ERR_SOW_STATE_INVALID`."

    PRD 3.7: "The line must still be `SUBMITTED`, otherwise
    `ERR_TIME_ENTRY_STATE_INVALID`, and the engagement's delivery must be either
    `ACTIVE` or `CLOSING`, otherwise `ERR_ENGAGEMENT_STATE_INVALID` —
    deliberately permitting late timesheet clean-up during closing."

    PRD 3.9: "The checkpoint must still be `SCHEDULED`; recording an outcome on
    one that has already reached `PASSED`, `CONDITIONAL` or `FAILED` is refused
    with `ERR_QUALITY_REVIEW_STATE_INVALID`."

    PRD 3.8: "Any operation attempted from a status that does not permit it is
    refused with `ERR_CHANGE_REQUEST_STATE_INVALID`."

    Design: Corner/errors/entity_specific_state_invalid_errors_are_distinct
    """
    sc = fx.build_pending_client_change(api)
    change_request_id = sc.extras["change_request_id"]
    approved_entry_id = sc.extras["time_entry_ids"][0]
    review = fx.schedule_review(sc)
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)
    fx.record_review_outcome(sc, review["id"], C.REVIEW_PASSED, C.SEVERITY_NONE)

    validate_error(
        api.submit_sow_internal(sc.sow_id, {}, sc.partner), E.ERR_SOW_STATE_INVALID
    )
    validate_error(
        api.time_entry_decision(approved_entry_id, {"decision": "REJECT"}, sc.manager),
        E.ERR_TIME_ENTRY_STATE_INVALID,
    )
    validate_error(
        api.record_outcome(
            review["id"],
            F.record_outcome_payload(C.REVIEW_FAILED, C.SEVERITY_HIGH),
            sc.reviewer,
        ),
        E.ERR_QUALITY_REVIEW_STATE_INVALID,
    )
    validate_error(
        api.assess_impact(change_request_id, {}, sc.manager),
        E.ERR_CHANGE_REQUEST_STATE_INVALID,
    )

    assert_fields(fx.read_sow(sc), status="SIGNED")
    assert_fields(
        fx.read_time_entry(sc, approved_entry_id), status=C.TIME_ENTRY_APPROVED
    )
    assert_fields(
        fx.read_quality_review(sc, review["id"]),
        status=C.REVIEW_PASSED,
        findings_severity=C.SEVERITY_NONE,
    )
    request = fx.read_change_request(sc, change_request_id)
    assert_fields(request, status=C.CR_PENDING_CLIENT_APPROVAL)
    assert_money(request, "fee_delta_cents", 3921600)
    assert_two_dp(fx.read_engagement(sc), "approved_hours_burned", 100.00)


def test_a_malformed_body_is_refused_before_the_unknown_client_is_looked_up(
    api: ConsultingApiClient,
) -> None:
    """Shape, enum and range all beat existence; a clean body reaches the 404.

    PRD 2.10: "Request well-formedness comes next: body shape and enum
    membership (`ERR_INVALID_REQUEST`), then pagination bounds on list endpoints
    (`ERR_INVALID_PAGINATION`), then submitted date ranges
    (`ERR_INVALID_DATE_RANGE`)."

    PRD 2.10: "Existence checks follow — path identifiers first, then body
    foreign keys, both at HTTP 404."

    PRD 3.1: "A client organisation is registered with its legal `name`, between
    1 and 200 characters and required; a `client_code`, a short firm-wide code of
    between 2 and 10 characters drawn only from uppercase letters and digits; an
    `industry_code`, which must be one of `RETAIL`, `INDUSTRIAL`, `FINSVC`,
    `PUBLIC` or `HEALTH`; a `decision_process` describing how the organisation
    approves professional-services purchases, which must be `SINGLE_APPROVER`,
    `COMMITTEE` or `PROCUREMENT_LED`; and a `stated_budget_authority_cents`
    figure, the annual professional-services budget authority the client claims
    to hold, which must be zero or greater."

    PRD 3.2: "It also carries `requested_practice_code`, the practice the client
    is buying, drawn from the same four-value set as a consultant's practice;
    `estimated_value_cents`, the firm's own estimate of contract value, which
    must be greater than zero and which becomes the denominator of the
    budget-coverage term in scoring; `stated_budget_cents`, the budget the client
    verbally states at intake, which must be zero or greater; the boolean
    `decision_maker_identified`, true only when an economic buyer with signature
    authority has actually been named; the requested delivery window
    `target_start_date` and `target_end_date`, both plain `YYYY-MM-DD` dates; and
    `objective_summary`, a one-paragraph statement of the client's objective."

    Design: Corner/errors/malformed_body_is_refused_before_any_lookup
    """
    sc = fx.build_master_data(api)

    shapeless = F.opportunity_payload(
        C.NON_EXISTENT_ID, sc.partner_id, sc.manager_id
    )
    shapeless.pop("objective_summary")
    # Two faults in one body: the missing field wins over the unknown client
    validate_error(api.create_opportunity(shapeless, sc.partner), E.ERR_INVALID_REQUEST)

    validate_error(
        api.create_client(
            F.client_payload(
                name="Bad Enum Co",
                client_code="NWR009",
                decision_process=BAD_DECISION_PROCESS,
            ),
            sc.admin,
        ),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_opportunity(
            F.opportunity_payload(
                sc.client_id, sc.partner_id, sc.manager_id, estimated_value_cents=-1
            ),
            sc.partner,
        ),
        E.ERR_INVALID_REQUEST,
    )

    # The same body, now well-formed, gets as far as the foreign-key lookup
    validate_error(
        api.create_opportunity(
            F.opportunity_payload(C.NON_EXISTENT_ID, sc.partner_id, sc.manager_id),
            sc.partner,
        ),
        E.ERR_CLIENT_NOT_FOUND,
    )

    _, client_meta = validate_paginated(api.list_clients(sc.admin, {}))
    assert_pagination_meta(client_meta, total_count=1, has_more=False)
    _, pursuit_meta = validate_paginated(api.list_opportunities(sc.partner, {}))
    assert_pagination_meta(pursuit_meta, total_count=0, has_more=False)


def test_a_declined_document_is_terminal_and_loses_the_pursuit(
    api: ConsultingApiClient,
) -> None:
    """DECLINE ends both rows, and re-drafting the dead document is refused.

    PRD 3.5: "A decline moves the document `CLIENT_REVIEW → DECLINED` and the
    pursuit `SOW_ISSUED → LOST`, again advancing both versions."

    PRD 3.5: "Its terminal states are `SIGNED`, `DECLINED` and `SUPERSEDED`, and
    any operation attempted from a state that does not permit it is refused with
    `ERR_SOW_STATE_INVALID`."

    Design: Corner/errors/declined_sow_and_rejected_change_request_reach_their_terminal_errors
    """
    sc = fx.build_sow_client_review(api)

    declined = get_success_data(
        api.sow_client_decision(
            sc.sow_id, {"decision": "DECLINE", "note": DECLINE_NOTE}, sc.client_contact
        )
    )

    assert_fields(declined, status="DECLINED", signed_at=None)
    assert_fields(fx.read_opportunity(sc), status="LOST")

    validate_error(api.revise_sow(sc.sow_id, {}, sc.partner), E.ERR_SOW_STATE_INVALID)

    assert_fields(fx.read_sow(sc), status="DECLINED", revision_round=0)
    _, meta = validate_paginated(
        api.list_engagements(sc.partner, {"sow_id": sc.sow_id})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)
    assert_fields(fx.read_client(sc), completed_engagement_count=0)


def test_a_client_rejected_change_keeps_its_figures_and_moves_no_contract(
    api: ConsultingApiClient,
) -> None:
    """The rejected row retains its assessment for audit and is then untouchable.

    PRD 3.8: "A rejection moves the request `PENDING_CLIENT_APPROVAL →
    REJECTED` with no engagement field changes."

    PRD 3.8: "Any operation attempted from a status that does not permit it is
    refused with `ERR_CHANGE_REQUEST_STATE_INVALID`."

    Design: Corner/errors/client_change_request_rejection_leaves_the_ledger_untouched
    """
    sc = fx.build_pending_client_change(api)
    change_request_id = sc.extras["change_request_id"]

    rejected = get_success_data(
        api.change_request_client_decision(
            change_request_id,
            {"decision": "REJECT", "note": REJECT_NOTE},
            sc.client_contact,
        )
    )

    assert_fields(rejected, status=C.CR_REJECTED, approved_at=None, rescinded_at=None)
    assert_money(rejected, "fee_delta_cents", 3921600)
    assert_two_dp(rejected, "cumulative_change_pct_at_assessment", 38.15)

    engagement = fx.read_engagement(sc)
    assert_money(engagement, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(engagement, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    assert_two_dp(engagement, "cumulative_change_pct", 0.00)
    assert_fields(engagement, schedule_relief_days=0)

    validate_error(
        api.rescind_change_request(
            change_request_id, {"note": "Too late"}, sc.manager
        ),
        E.ERR_CHANGE_REQUEST_STATE_INVALID,
    )

    assert_fields(fx.read_change_request(sc, change_request_id), status=C.CR_REJECTED)
    assert_economics_view(
        get_success_data(api.get_economics(sc.engagement_id, sc.partner)),
        hours_burn_pct=49.81,
        completion_pct=40.00,
        progress_variance_pct=9.81,
        projected_cost_cents=9625500,
        projected_margin_pct=6.37,
        economics_state=C.ECONOMICS_AT_RISK,
    )


def test_an_inactive_client_cannot_sign_until_its_standing_is_restored(
    api: ConsultingApiClient,
) -> None:
    """The commercial-standing gate is reversible, and the same signature then lands.

    PRD 3.5: "A signature additionally requires `signature_name` to be present —
    its absence is an `ERR_INVALID_REQUEST` — requires the client's `status` to
    be `ACTIVE`, since a client on `CREDIT_HOLD` or one that is `INACTIVE` is
    refused with `ERR_CLIENT_NOT_ELIGIBLE_FOR_SIGNATURE`, and requires a cleared
    conflict position."

    PRD 3.1: "A client's `status` — its commercial standing — begins at `ACTIVE`
    and can be moved to `CREDIT_HOLD` or `INACTIVE` only by a practice
    administrator's dedicated standing operation, which accepts the target
    `status` and increments the client's `version`."

    Design: Corner/errors/client_status_endpoint_reaches_inactive_and_blocks_signature
    """
    sc = fx.build_sow_client_review(api)
    parked = get_success_data(
        api.set_client_status(
            sc.client_id, {"status": C.CLIENT_STATUS_INACTIVE}, sc.admin
        )
    )
    assert_fields(parked, status=C.CLIENT_STATUS_INACTIVE)

    validate_error(
        api.sow_client_decision(sc.sow_id, F.sign_payload(), sc.client_contact),
        E.ERR_CLIENT_NOT_ELIGIBLE_FOR_SIGNATURE,
    )
    assert_fields(fx.read_sow(sc), status="CLIENT_REVIEW", signed_at=None)

    restored = get_success_data(
        api.set_client_status(
            sc.client_id, {"status": C.CLIENT_STATUS_ACTIVE}, sc.admin
        )
    )
    assert_fields(restored, status=C.CLIENT_STATUS_ACTIVE)

    signed = get_success_data(
        api.sow_client_decision(sc.sow_id, F.sign_payload(), sc.client_contact)
    )

    assert_fields(signed, status="SIGNED", signature_name=C.SEED_SIGNATURE_NAME)
    assert signed["signed_at"].startswith("2026-08-03T09:00:00")
    fx.discover_engagement(sc)
    engagement = fx.read_engagement(sc)
    assert_fields(engagement, delivery_state=C.DELIVERY_MOBILIZING)
    assert_money(engagement, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(
        engagement, "pinned_scope_discount_pct", C.CANON_SCOPE_DISCOUNT_PCT
    )


def test_an_internally_returned_document_is_invisible_to_the_client(
    api: ConsultingApiClient,
) -> None:
    """RETURN is not a client revision: it re-prices nothing and counts nothing.

    PRD 3.5: "An approval moves the document `INTERNAL_REVIEW → CLIENT_REVIEW`,
    again requiring a cleared conflict position; a return moves it
    `INTERNAL_REVIEW → DRAFT`."

    PRD 3.5: "All three require the document to be in `CLIENT_REVIEW`."

    Design: Corner/errors/sow_return_branch_and_deliverable_rework_branch_are_reachable
    """
    sc = fx.build_sow_internal_review(api)

    returned = get_success_data(
        api.sow_internal_decision(
            sc.sow_id, {"decision": "RETURN", "note": RETURN_NOTE}, sc.leadership
        )
    )

    assert_fields(returned, status="DRAFT", revision_round=0)

    validate_error(
        api.sow_client_decision(sc.sow_id, F.sign_payload(), sc.client_contact),
        E.ERR_SOW_STATE_INVALID,
    )

    resubmitted = get_success_data(api.submit_sow_internal(sc.sow_id, {}, sc.partner))
    assert_fields(resubmitted, status="INTERNAL_REVIEW", revision_round=0)
    # An internal round trip does not touch the price
    assert_money(resubmitted, "quoted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)


def test_the_second_acknowledgement_has_no_edge_to_travel(
    api: ConsultingApiClient,
) -> None:
    """ACKNOWLEDGED is not reachable from ACKNOWLEDGED, and nothing else moves.

    PRD 3.9: "A response not reachable from the escalation's current status —
    including any response at all after `RESOLVED` — is refused with
    `ERR_RISK_ESCALATION_STATE_INVALID`."

    PRD 3.9: "Acknowledging moves the escalation `OPEN → ACKNOWLEDGED` and does
    nothing else."

    Design: Corner/errors/escalation_double_acknowledge_and_unknown_assessment_id
    """
    sc = fx.build_started_engagement(api)
    review = fx.schedule_review(sc)
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)
    fx.record_review_outcome(sc, review["id"], C.REVIEW_FAILED, C.SEVERITY_HIGH)
    escalation = fx.first_escalation(sc)
    assert_fields(escalation, status=C.ESCALATION_OPEN, leadership_response=None)

    acknowledged = fx.respond_to_escalation(
        sc, escalation["id"], C.RESPONSE_ACKNOWLEDGE
    )
    assert_fields(
        acknowledged,
        status=C.ESCALATION_ACKNOWLEDGED,
        leadership_response=C.RESPONSE_ACKNOWLEDGE,
    )

    validate_error(
        api.leadership_response(
            escalation["id"], {"response": C.RESPONSE_ACKNOWLEDGE}, sc.leadership
        ),
        E.ERR_RISK_ESCALATION_STATE_INVALID,
    )

    unchanged = get_success_data(
        api.get_risk_escalation(escalation["id"], sc.leadership)
    )
    assert_fields(
        unchanged,
        status=C.ESCALATION_ACKNOWLEDGED,
        leadership_response=C.RESPONSE_ACKNOWLEDGE,
        version=acknowledged["version"],
    )
    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
    )

    validate_error(
        api.get_satisfaction_assessment(C.NON_EXISTENT_ID, sc.partner),
        E.ERR_SATISFACTION_ASSESSMENT_NOT_FOUND,
    )
