"""Role-based access control, ownership checks, and optimistic-concurrency guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    build_user_headers, make_attorney_headers, TEST_USERS,
    setup_motion_under_submission, setup_motion_filed, setup_open_case,
    setup_draft_case, setup_judgment_entered, add_party, efile, add_fee_waiver,
    add_deadline,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"
ATT_DF = "att_2"


# =====================================================================
# Queue B (Corner): rbac
# =====================================================================
def test_attorney_cannot_create_case(api):
    """PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation under the access matrix, the request is rejected with
    ERR_FORBIDDEN."

    Design: Corner/rbac/attorney_cannot_create_case
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00.000Z", ADMIN))
    court = get_success_data(api.create_court(
        {"name": "Sup Ct BH", "jurisdiction_code": "CA", "filing_fee_cents": 43500}, ADMIN))
    resp = api.create_case(
        {"court_id": court["id"], "caption": "Sneaky", "case_type": "CONTRACT"},
        make_attorney_headers(ATT_PL))
    validate_error(resp, "ERR_FORBIDDEN")


def test_clerk_cannot_rule_motion(api):
    """PRD 2.1: "A Judge takes motions under submission and rules on them, schedules and
    manages hearings, enters and vacates judgments, lifts stays, vacates deadlines, and
    dismisses appeals."

    Design: Corner/rbac/clerk_cannot_rule_motion
    """
    base = setup_motion_under_submission(clock="2026-03-01T00:00:00.000Z")
    resp = api.rule_motion(base["motion"]["id"], {"ruling": "GRANT", "order_text": "x"}, CLERK)
    validate_error(resp, "ERR_FORBIDDEN")


def test_attorney_not_moving_party_cannot_withdraw(api):
    """PRD 2.1: "an attorney may only withdraw a motion whose moving party they represent
    — a mismatch is rejected with ERR_NOT_MOVING_PARTY."

    Design: Corner/rbac/attorney_not_moving_party_cannot_withdraw
    """
    base = setup_motion_filed(clock="2026-03-01T00:00:00.000Z")
    # The moving party is represented by att_1; act as att_99.
    resp = api.withdraw_motion(base["motion"]["id"], make_attorney_headers("att_99"))
    validate_error(resp, "ERR_NOT_MOVING_PARTY")


def test_attorney_not_requesting_party_cannot_resubmit_fee_waiver(api):
    """PRD 2.1: "may only resubmit a fee waiver whose requesting party they represent, a
    mismatch being rejected with ERR_NOT_REQUESTING_PARTY."

    Design: Corner/rbac/attorney_not_requesting_party_cannot_resubmit_feewaiver
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    fw = add_fee_waiver(case_id, complaint["id"], pl["id"], attorney_user_id=ATT_PL)
    get_success_data(api.request_info_fee_waiver(fw["id"], CLERK))

    resp = api.resubmit_fee_waiver(
        fw["id"], {"monthly_income_cents": 100000, "household_size": 1},
        make_attorney_headers("att_99"))
    validate_error(resp, "ERR_NOT_REQUESTING_PARTY")


def test_missing_role_header_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or X-User-Role is not one of these four
    values, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00.000Z", ADMIN))
    court = get_success_data(api.create_court(
        {"name": "Sup Ct BK", "jurisdiction_code": "CA", "filing_fee_cents": 43500}, ADMIN))
    resp = api.get_court(court["id"], {})  # no auth headers
    validate_error(resp, "ERR_UNAUTHENTICATED")


# =====================================================================
# Queue B (Corner): cross_cutting_complexity_layers (OCC)
# =====================================================================
def test_occ_judgment_stale_case_version_rejected(api):
    """PRD 2.9: "Entering a judgment requires the request to carry expected_case_version
    matching the target case's current version. If another writer has advanced the case's
    version since the client last read it — for instance by ruling a final motion or
    recomputing posture — the create is rejected with ERR_STALE_VERSION at HTTP 412,
    preventing entry of a judgment against a case the client has not observed in its
    current state."

    Design: Corner/cross_cutting_complexity_layers/occ_judgment_stale_case_version_rejected
    """
    base = setup_open_case(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    stale_version = base["case_version"]  # version observed right after open
    # A deadline create + vacate bumps Case.version beyond the observed value.
    dl = add_deadline(case_id, anchor_date="2026-04-04T00:00:00.000Z",
                      interval_days=10, counting_mode="CALENDAR")
    get_success_data(api.vacate_deadline(dl["id"], JUDGE))

    resp = api.create_judgment({
        "case_id": case_id, "judgment_type": "TRIAL",
        "prevailing_party_id": base["plaintiff"]["id"],
        "principal_cents": 0, "interest_rate_bps": 0,
        "expected_case_version": stale_version,
    }, JUDGE)
    validate_error(resp, "ERR_STALE_VERSION")


def test_occ_appeal_correct_version_succeeds(api):
    """PRD 2.9: "Filing a notice of appeal carries the same requirement: the request must
    supply expected_case_version matching the case's current version, and a mismatch is
    rejected with ERR_STALE_VERSION at HTTP 412, since the new appeal supersedes the prior
    case view by driving the case to ON_APPEAL."
    PRD 3.8: "The appeal is created in status `NOTICE_FILED`; the appealed judgment
    cascades `ENTERED → APPEALED`, which in turn drives the case
    `JUDGMENT_ENTERED → ON_APPEAL`; and the case's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/occ_appeal_correct_version_succeeds
    """
    base = setup_judgment_entered(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    current = get_success_data(api.get_case(case_id, CLERK))

    appeal = validate_success(api.create_appeal({
        "case_id": case_id, "judgment_id": base["judgment"]["id"],
        "appellant_party_id": base["defendant"]["id"],
        "filed_on": "2026-04-10T00:00:00.000Z",
        "expected_case_version": current["version"],
    }, make_attorney_headers(ATT_DF)), expected_status=201)
    case_after = validate_success(api.get_case(case_id, CLERK))

    assert appeal["status"] == "NOTICE_FILED", appeal["status"]
    assert case_after["status"] == "ON_APPEAL", case_after["status"]
