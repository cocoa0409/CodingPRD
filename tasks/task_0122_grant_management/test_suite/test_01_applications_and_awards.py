"""Application lifecycle, the award it issues, and award OCC/terminal behavior.

Sources: Difficulty queue (non_linear_state_machine, dual_variant ceiling at award
issuance) and Corner queue (entities, state_machines, cross_cutting OCC).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client,
    ApiErrorId,
    assert_application, assert_award,
    create_application_payload,
    TEST_USERS,
)
from test_helpers.test_users import ANONYMOUS_HEADERS
import test_helpers.fixtures as fx

GW = TEST_USERS["grant_writer_headers"]
AO = TEST_USERS["agency_officer_headers"]


# ==========================================================================
# Application creation / retrieval / listing / not-found / required fields
# ==========================================================================
def test_create_application_defaults_and_draft_status(api):
    """PRD §3.1: "A new application is born in DRAFT."
    PRD §3.1: "The writer may also supply federal_share_pct, the federal share of
    total project cost expressed as a decimal fraction greater than 0 and at most 1;
    when omitted it defaults to 0.80, and the recipient's cost-share is understood to
    be one minus this value."
    PRD §3.1: "this field is nullable and defaults to null on a first submission."

    Design: Corner/entities/create_application_returns_201_with_defaults_and_draft_status
    """
    payload = {
        "nofo_number": "NOFO-2026-C1",
        "applicant_org_name": "Corner Org 1",
        "requested_amount_cents": 30_000_000,
        "period_start_date": "2026-01-01T00:00:00Z",
        "period_end_date": "2026-12-31T00:00:00Z",
    }
    data = validate_success(api.create_application(payload, GW), expected_status=201)
    assert_application(data)
    assert data["status"] == "DRAFT"
    assert data["federal_share_pct"] == 0.80
    assert data["supersedes_application_id"] is None
    assert data["version"] == 1


def test_get_application_returns_stored_entity(api):
    """PRD §3.1: "Creating an application records the nofo_number it responds to,
    the applicant_org_name of the grantee, the requested_amount_cents (total federal
    funds requested across the full period of performance, which must be at least 1),
    and the proposed period of performance as period_start_date and period_end_date."

    Design: Corner/entities/get_application_by_id_returns_stored_entity
    """
    created = fx.create_draft_application(
        nofo_number="NOFO-2026-C2", applicant_org_name="Corner Org 2",
    )
    data = validate_success(api.get_application(created["id"], GW))
    assert data["nofo_number"] == "NOFO-2026-C2"
    assert data["applicant_org_name"] == "Corner Org 2"


def test_list_applications_paginated_envelope(api):
    """PRD §2.3: "For every list response, the meta block carries limit, offset,
    total_count (the number of records matching the query before pagination), and
    has_more (true when records remain beyond the current page)."

    Design: Corner/entities/list_applications_paginated_envelope_total_count_has_more
    """
    fx.create_draft_application(nofo_number="NOFO-2026-C3a", applicant_org_name="Corner Org 3a")
    fx.create_draft_application(nofo_number="NOFO-2026-C3b", applicant_org_name="Corner Org 3b")
    resp = api.list_applications(GW, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
    assert resp.json()["response_type"] == "array"


def test_get_application_nonexistent_returns_not_found(api):
    """PRD §2.8: "a body that names an award, a drawdown, a restricted fund, or a
    single audit that does not exist is rejected with ERR_NOT_FOUND."
    PRD §3.9: "Existence comes third: any path resource or required foreign key that
    does not exist fails with ERR_NOT_FOUND, with path segments resolved left to right."

    Design: Corner/entities/get_application_nonexistent_id_returns_not_found
    """
    resp = api.get_application("00000000-0000-4000-8000-000000000000", GW)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_application_missing_required_field_invalid_request(api):
    """PRD §3.9: "general request validity — required fields present, correct types,
    valid enum members, integer-cent fields non-negative (or at least 1 where noted),
    and contextual requirements such as a present negotiated_rate for a NEGOTIATED rate
    and an allocation_plan summing to amount_cents — fails with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_application_missing_required_field_returns_invalid_request
    """
    payload = {
        "nofo_number": "NOFO-2026-C5",
        "applicant_org_name": "Corner Org 5",
        "period_start_date": "2026-01-01T00:00:00Z",
        "period_end_date": "2026-12-31T00:00:00Z",
    }  # requested_amount_cents omitted
    resp = api.create_application(payload, GW)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# ==========================================================================
# Non-linear state machine: application revision cycle (Difficulty Rule 3)
# ==========================================================================
def test_application_revision_cycle_then_award(api):
    """PRD §3.1: "Requesting revisions returns the application to REVISIONS_REQUESTED,
    from which the writer may resubmit — so the cycle REVISIONS_REQUESTED → SUBMITTED
    → UNDER_REVIEW may repeat any number of times."
    PRD §3.1: "Awarding moves it to the terminal AWARDED state and, in the same step,
    issues the Award."
    PRD §3.2: "It then computes federal_ceiling_cents as the product of total_award_cents
    and federal_share_pct, rounded half-up to whole cents."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_under_review_to_revisions_and_back
    """
    app = fx.create_under_review_application(
        nofo_number="NOFO-2026-A5", applicant_org_name="Org E",
        requested_amount_cents=30_000_000,
    )
    validate_success(api.request_revisions_application(app["id"], AO))
    resubmitted = validate_success(api.submit_application(app["id"], GW))
    assert resubmitted["status"] == "SUBMITTED"
    rereviewed = validate_success(api.begin_review_application(app["id"], AO))
    assert rereviewed["status"] == "UNDER_REVIEW"
    award = validate_success(api.award_application(app["id"], AO), expected_status=201)
    assert award["status"] == "ACTIVE"
    assert award["federal_ceiling_cents"] == 24_000_000

    final_app = validate_success(api.get_application(app["id"], GW))
    assert final_app["status"] == "AWARDED"


def test_application_revision_cycle_reaches_awarded_status(api):
    """PRD §3.1: "the cycle REVISIONS_REQUESTED → SUBMITTED → UNDER_REVIEW may repeat
    any number of times."
    PRD §3.1: "Awarding moves it to the terminal AWARDED state and, in the same step,
    issues the Award."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_under_review_to_revisions_and_back
    """
    app = fx.create_under_review_application(
        nofo_number="NOFO-2026-A5b", applicant_org_name="Org E2",
        requested_amount_cents=30_000_000,
    )
    api.request_revisions_application(app["id"], AO)
    api.submit_application(app["id"], GW)
    api.begin_review_application(app["id"], AO)
    award = validate_success(api.award_application(app["id"], AO), expected_status=201)
    assert_award(award)
    app_after = validate_success(api.get_application(app["id"], GW))
    assert app_after["status"] == "AWARDED"


# ==========================================================================
# Award: system-minted fields, terminal lockdown
# ==========================================================================
def test_award_fields_copied_from_application(api):
    """PRD §3.2: "It copies total_award_cents from the application's requested_amount_cents,
    copies federal_share_pct from the application, and copies the period_start_date and
    period_end_date."
    PRD §3.2: "The award opens in ACTIVE status with its two running ledgers initialized
    to zero: federal_drawn_cents (federal cash actually disbursed) and
    federal_approved_expenditures_cents (cumulative approved federal-eligible expenditures)."

    Design: Corner/entities/award_system_fields_copied_from_application_not_client_supplied
    """
    app = fx.create_under_review_application(
        nofo_number="NOFO-2026-C7", applicant_org_name="Corner Org 7",
        requested_amount_cents=30_000_000, federal_share_pct=0.80,
    )
    award = validate_success(api.award_application(app["id"], AO), expected_status=201)
    assert award["total_award_cents"] == 30_000_000
    assert award["federal_share_pct"] == 0.80
    assert award["federal_ceiling_cents"] == 24_000_000
    assert award["federal_drawn_cents"] == 0
    assert award["status"] == "ACTIVE"


def test_closed_award_rejects_further_transitions(api):
    """PRD §3.2: "When all preconditions hold, the award moves to the terminal CLOSED state."
    PRD §3.2: "An ACTIVE award may be suspended, moving it to SUSPENDED... Each of these
    requires the award to be in the corresponding source state, failing otherwise with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/award_terminal_closed_rejects_further_transitions
    """
    award = fx.create_active_award(nofo_number="NOFO-2026-C14", applicant_org_name="Corner Org 14")
    pc = fx.initiate_closeout(award)
    closed = validate_success(api.close_award(pc["id"], {"expected_award_version": pc["version"]}, AO))
    assert closed["status"] == "CLOSED"
    resp = api.suspend_award(award["id"], {"expected_award_version": closed["version"]}, AO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = validate_success(api.get_award(award["id"], AO))
    assert after["status"] == "CLOSED"


# ==========================================================================
# State machine corners: invalid-from, idempotency
# ==========================================================================
def test_begin_review_on_draft_returns_invalid_state(api):
    """PRD §3.1: "Beginning review moves a SUBMITTED application to UNDER_REVIEW."
    PRD §3.9: "State validity comes fourth: a transition attempted from a state in
    which it is not defined fails with ERR_INVALID_STATE."

    Design: Corner/state_machines/begin_review_on_draft_application_returns_invalid_state
    """
    app = fx.create_draft_application(nofo_number="NOFO-2026-C13", applicant_org_name="Corner Org 13")
    resp = api.begin_review_application(app["id"], AO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = validate_success(api.get_application(app["id"], GW))
    assert after["status"] == "DRAFT"


def test_submit_application_twice_second_invalid_state(api):
    """PRD §3.1: "Submitting from any state other than DRAFT or REVISIONS_REQUESTED is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/submit_application_twice_second_returns_invalid_state
    """
    app = fx.create_submitted_application(nofo_number="NOFO-2026-C15", applicant_org_name="Corner Org 15")
    resp = api.submit_application(app["id"], GW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = validate_success(api.get_application(app["id"], GW))
    assert after["status"] == "SUBMITTED"


# ==========================================================================
# Award OCC happy path (cross_cutting_complexity_layers)
# ==========================================================================
def test_occ_suspend_with_current_version_succeeds_and_increments(api):
    """PRD §2.6: "The server compares it to the award's current version; if they differ,
    the request is rejected with ERR_STALE_VERSION (HTTP 412) and no change is made."
    PRD §3.2: "every one of these transitions is optimistic-concurrency-guarded on
    expected_award_version as described in §2.6 and increments the award's version. An
    ACTIVE award may be suspended, moving it to SUSPENDED."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_suspend_succeeds_and_increments
    """
    award = fx.create_active_award(nofo_number="NOFO-2026-C42", applicant_org_name="Corner Org 42")
    v0 = award["version"]
    suspended = validate_success(
        api.suspend_award(award["id"], {"expected_award_version": v0}, AO)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == v0 + 1
