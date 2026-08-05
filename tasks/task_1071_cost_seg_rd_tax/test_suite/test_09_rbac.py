"""Role-based access control and segregation of duties.

Translates queue B (Corner/rbac) instances.
"""
from test_helpers import (
    validate_error, TEST_USERS, fixtures,
    make_engineer_headers, make_reviewer_headers, ApiErrorId,
)
import test_helpers.factories as f

SM = TEST_USERS["study_manager_headers"]
CPA = TEST_USERS["cpa_headers"]


def _cost_seg_in_review(api):
    ctx = fixtures.setup_cost_seg_engineering(api, with_reviewer=True)
    fixtures.add_allocated_components(api, ctx, [("5yr", "FIVE_YEAR", 10000000)])
    fixtures.submit(api, ctx)
    return ctx


# ---------------------------------------------------------------------------
# Corner/rbac/engineer_cannot_finalize_study
# ---------------------------------------------------------------------------
def test_engineer_cannot_finalize_study(api):
    """PRD §4: "POST /studies/{id}/finalize | Finalize study; cascade report issue, fee,
    ledger | Reviewer".
    PRD §2.1: "A request whose role is recognized but is not permitted to perform the requested
    operation is rejected with ERR_UNAUTHORIZED."

    Finalize is Reviewer-exclusive; an Engineer is denied.

    Design: Corner/rbac/engineer_cannot_finalize_study
    """
    ctx = _cost_seg_in_review(api)
    resp = api.finalize_study(ctx["study_id"], make_engineer_headers(ctx["engineer_id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner/rbac/cpa_cannot_create_study
# ---------------------------------------------------------------------------
def test_cpa_cannot_create_study(api):
    """PRD §4: "POST /studies | Create a study for an active client | StudyManager".
    PRD §2.1: "A request whose role is recognized but is not permitted to perform the requested
    operation is rejected with ERR_UNAUTHORIZED."

    Study creation is StudyManager-exclusive; a CPA is denied.

    Design: Corner/rbac/cpa_cannot_create_study
    """
    cli = fixtures.create_client(api)
    resp = api.create_study(f.create_study_payload(cli["id"], "RD_CREDIT", tax_year=2024), CPA)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner/rbac/reviewer_cannot_finalize_own_preparation_sod
# ---------------------------------------------------------------------------
def test_reviewer_cannot_finalize_own_preparation(api):
    """PRD §2.8: "Whenever a Reviewer rejects a study back for revision or finalizes it, the
    reviewer's own engineer id (their X-User-ID) must differ from the study's
    assigned_engineer_id. If they are the same person, the operation is rejected with
    ERR_SOD_VIOLATION."

    The Reviewer acts under the preparer engineer's own id → SoD violation.

    Design: Corner/rbac/reviewer_cannot_finalize_own_preparation_sod
    """
    ctx = _cost_seg_in_review(api)
    resp = api.finalize_study(ctx["study_id"], make_reviewer_headers(ctx["engineer_id"]))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)
