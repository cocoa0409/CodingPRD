"""Closing scheduling window overlap, the award-FUNDED precondition on
completion, and the appraisal prerequisite.

Difficulty:
  resource_temporal_overlap / closing_window_overlap_on_property
  cross_entity_state_dependency / closing_complete_depends_on_award_funded
Corner:
  validations / complete_without_appraisal_returns_error
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import create_closing_payload

CLOSING_COORDINATOR = fx.CLOSING_COORDINATOR
CASE_MANAGER = fx.CASE_MANAGER


# --- resource_temporal_overlap / closing_window_overlap_on_property ---------
def test_overlapping_closing_windows_conflict(api):
    """PRD 3.6: "if any other non-`CANCELLED` closing on the same property has an
    occupation window that overlaps this one, the schedule is rejected with
    `ERR_CLOSING_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/closing_window_overlap_on_property
    """
    ctx = fx.setup_eligible_application(api, with_education=False)
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    fx.schedule_closing(api, award["id"], ctx["property"]["id"], scheduled_date="2026-08-01T00:00:00Z", window_days=7)
    # Window [08-05, 08-12) overlaps [08-01, 08-08) because 08-05 < 08-08.
    payload = create_closing_payload(
        property_id=ctx["property"]["id"], scheduled_date="2026-08-05T00:00:00Z", window_days=7
    )
    resp = api.schedule_closing(award["id"], payload, CLOSING_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CLOSING_WINDOW_CONFLICT.value)


def test_adjacent_closing_windows_allowed(api):
    """PRD 3.6: "Because the windows are half-open, exact adjacency — a new
    window that starts precisely when a prior window ends — is allowed and does
    not conflict."

    Design: Difficulty/resource_temporal_overlap/closing_window_overlap_on_property
    """
    ctx = fx.setup_eligible_application(api, with_education=False)
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    fx.schedule_closing(api, award["id"], ctx["property"]["id"], scheduled_date="2026-08-01T00:00:00Z", window_days=7)
    # Window [08-08, 08-15) starts exactly when [08-01, 08-08) ends.
    payload = create_closing_payload(
        property_id=ctx["property"]["id"], scheduled_date="2026-08-08T00:00:00Z", window_days=7
    )
    data = validate_success(api.schedule_closing(award["id"], payload, CLOSING_COORDINATOR), 201)
    assert data["status"] == "SCHEDULED"


# --- cross_entity_state_dependency / closing_complete_depends_on_award_funded -
def test_complete_rejected_when_award_not_funded(api):
    """PRD 3.6: "Two further preconditions guard it: the award must be in
    `FUNDED` status (otherwise `ERR_INVALID_STATE`, HTTP 409), and the property
    must have a recorded appraisal — its `appraised_value_cents` must be set —
    otherwise the completion is rejected with `ERR_APPRAISAL_MISSING`
    (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/closing_complete_depends_on_award_funded
    """
    # Only a partial allocation (2,000,000 of a 5,000,000 award): award stays APPROVED.
    ctx = fx.setup_approved_award(api, total_appropriation_cents=10_000_000)
    fx.record_appraisal(api, ctx["property"]["id"], 31_000_000)
    fs = ctx["funding_source"]
    fx.allocate(api, ctx["award"]["id"], fs["id"], 2_000_000, 1, fs["version"])
    closing = fx.schedule_closing(api, ctx["award"]["id"], ctx["property"]["id"])
    fx.docs_pending(api, closing["id"])
    resp = api.complete_closing(
        closing["id"], {"final_purchase_price_cents": 30_000_000, "final_first_mortgage_cents": 24_000_000},
        CLOSING_COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert award["status"] == "APPROVED", f"award must stay APPROVED, got {award['status']}"


def test_complete_succeeds_when_award_funded(api):
    """PRD 3.6: "Completing a closing is the pivotal fiscal event and is
    permitted only from `DOCS_PENDING`."
    PRD 3.6: "A successful completion moves the closing to `COMPLETED` and drives
    a four-hop cascade that carries the award from `FUNDED` to `SERVICING`:"

    Design: Difficulty/cross_entity_state_dependency/closing_complete_depends_on_award_funded
    """
    # Full allocation drives the award to FUNDED, so completion is permitted.
    ctx = fx.setup_servicing_account(api)
    closing = validate_success(api.get_closing(ctx["closing"]["id"], CLOSING_COORDINATOR), 200)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert closing["status"] == "COMPLETED", f"expected COMPLETED, got {closing['status']}"
    assert award["status"] == "SERVICING", f"expected SERVICING, got {award['status']}"


# --- Corner / complete_without_appraisal_returns_error ----------------------
def test_complete_without_appraisal_returns_error(api):
    """PRD 3.6: "the property must have a recorded appraisal — its
    `appraised_value_cents` must be set — otherwise the completion is rejected
    with `ERR_APPRAISAL_MISSING` (HTTP 422)."

    Design: Corner/validations/complete_without_appraisal_returns_error
    """
    # Award FUNDED but the property has never been appraised.
    ctx = fx.setup_funded_award(api)
    closing = fx.schedule_closing(api, ctx["award"]["id"], ctx["property"]["id"])
    fx.docs_pending(api, closing["id"])
    resp = api.complete_closing(
        closing["id"], {"final_purchase_price_cents": 30_000_000, "final_first_mortgage_cents": 24_000_000},
        CLOSING_COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_APPRAISAL_MISSING.value)
