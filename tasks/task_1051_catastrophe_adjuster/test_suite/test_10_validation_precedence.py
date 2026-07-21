"""Validation precedence pairs, the photo-count boundary, and claim reopen guard."""
from test_helpers import (
    validate_error, validate_success,
    TEST_USERS, make_field_adjuster_headers,
    create_claim_payload,
)
from test_helpers import fixtures as fx

DESK = TEST_USERS["desk_examiner_headers"]


# --------------------------------------------------------------------------
# Difficulty: state check (offered) beats license gate
# --------------------------------------------------------------------------
def _declined_assignment_no_active_license(api):
    adj = fx.create_adjuster(api)
    fx.create_license(api, adj["id"], state_code="FL")  # PENDING, never activated
    claim = fx.create_claim(api, loss_state="FL", peril_type="HAIL", policy_type="ACV")
    asg = fx.create_assignment(api, claim["id"], adj["id"])
    fx.get_success_data(api.decline_assignment(asg["id"], make_field_adjuster_headers(adj["id"])))
    return adj, asg


def test_accept_declined_assignment_reports_state_error(api):
    """PRD 2.10: "On assignment accept, the assignment's own state is checked before
    the cross-entity license gate, so an assignment that is not in the offered state
    surfaces its state error rather than a licensing error."

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_referential
    """
    adj, asg = _declined_assignment_no_active_license(api)
    resp = api.accept_assignment(asg["id"], make_field_adjuster_headers(adj["id"]))
    validate_error(resp, "ERR_ASSIGNMENT_NOT_OFFERED")


def test_accept_declined_assignment_stays_declined(api):
    """PRD 3.3: "Declining an offer instead moves the assignment OFFERED -> DECLINED
    (again requiring the offered state and ownership); DECLINED is terminal for that
    assignment." A rejected accept leaves it DECLINED.

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_referential
    """
    adj, asg = _declined_assignment_no_active_license(api)
    api.accept_assignment(asg["id"], make_field_adjuster_headers(adj["id"]))
    data = validate_success(api.get_assignment(asg["id"], DESK))
    assert data["work_status"] == "DECLINED"


# --------------------------------------------------------------------------
# Difficulty: photo_count zero boundary on report submit
# --------------------------------------------------------------------------
def _ready_for_report(api, photo_count):
    ctx = fx.setup_completed_inspection(api, loss_state="FL", peril_type="HAIL", policy_type="ACV")
    est = fx.create_estimate(api, ctx["insp_id"], ctx["claim_id"], ctx["adj_id"])
    fx.approve_estimate(api, est["id"], ctx["adj_id"])
    rpt = fx.create_report(api, ctx["insp_id"], ctx["asg_id"], ctx["adj_id"], photo_count=photo_count)
    ctx["rpt_id"] = rpt["id"]
    return ctx


def test_report_submit_zero_photos_rejected(api):
    """PRD 3.5: "and the report's photo_count must be at least 1 (otherwise
    ERR_REPORT_NO_PHOTOS)."

    Design: Difficulty/boundary_precision_check/report_photo_zero_boundary
    """
    ctx = _ready_for_report(api, photo_count=0)
    resp = api.submit_report(ctx["rpt_id"], make_field_adjuster_headers(ctx["adj_id"]))
    validate_error(resp, "ERR_REPORT_NO_PHOTOS")
    report = validate_success(api.get_report(ctx["rpt_id"], DESK))
    assert report["status"] == "DRAFT", "a rejected submit leaves the report in DRAFT"


def test_report_submit_one_photo_allowed(api):
    """PRD 3.5: "and the report's photo_count must be at least 1 (otherwise
    ERR_REPORT_NO_PHOTOS). A successful submission carries two forward side effects:
    the parent assignment advances FIELDWORK -> WORK_COMPLETE, and the claim advances
    IN_PROGRESS -> UNDER_REVIEW."

    Design: Difficulty/boundary_precision_check/report_photo_zero_boundary
    """
    ctx = _ready_for_report(api, photo_count=1)
    data = validate_success(api.submit_report(ctx["rpt_id"], make_field_adjuster_headers(ctx["adj_id"])))
    assert data["status"] == "SUBMITTED"


# --------------------------------------------------------------------------
# Corner: reopen a non-CLOSED claim
# --------------------------------------------------------------------------
def test_reopen_non_closed_claim_returns_not_closed(api):
    """PRD 3.3: "A DeskExaminer reopens a claim, moving it CLOSED -> REOPENED, only when
    the claim is CLOSED (otherwise ERR_CLAIM_NOT_CLOSED)."

    Design: Corner/endpoints/reopen_non_closed_claim_returns_not_closed
    """
    claim = validate_success(api.create_claim(create_claim_payload(), DESK), 201)
    resp = api.reopen_claim(claim["id"], DESK)
    validate_error(resp, "ERR_CLAIM_NOT_CLOSED")
