"""Validation priority ordering, posture gates, and cross-entity state dependencies."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    rule_motion_payload, create_filing_payload, create_motion_payload,
    make_attorney_headers, TEST_USERS,
    setup_open_case, setup_motion_filed, setup_stayed_case, setup_draft_case,
    setup_restricted_case, add_party, efile, add_attempted_service,
    add_accepted_motion_filing, file_motion,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"
ATT_DF = "att_2"


# =====================================================================
# Queue A: priority_pair_validation_conflict
# =====================================================================
def test_frozen_gate_outranks_fee_unpaid_on_accept(api):
    """PRD 2.10: "Domain safety and business gates are evaluated only after all of the
    foregoing pass: the frozen-case gate (ERR_CASE_FROZEN), the restricted-case gate
    (ERR_CASE_RESTRICTED), hearing-conflict checks (ERR_HEARING_CONFLICT), the
    statute-of-limitations bar (ERR_STATUTE_EXPIRED), the unpaid-fee bar
    (ERR_FILING_FEE_UNPAID), and the appeal-window check (ERR_APPEAL_WINDOW_CLOSED)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_fee_unpaid_on_accept
    """
    # Stay the case (FROZEN), then submit a second unpaid (ASSESSED) complaint UNDER_REVIEW.
    base = setup_stayed_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    assert base["case"]["posture"] == "FROZEN", base["case"]["posture"]

    f2 = efile(case_id, base["plaintiff"]["id"], ATT_PL,
               document_type="COMPLAINT", title="Complaint 2 unpaid")
    get_success_data(api.claim_review_filing(f2["id"], CLERK))

    resp = api.accept_filing(f2["id"], CLERK)
    validate_error(resp, "ERR_CASE_FROZEN")


def test_forbidden_outranks_invalid_state_on_motion_rule(api):
    """PRD 2.10: "Authentication of the headers comes first (ERR_UNAUTHENTICATED), then
    role authorization (ERR_FORBIDDEN), then existence of all path and foreign-key
    resources (ERR_NOT_FOUND), then request-body well-formedness (ERR_INVALID_REQUEST),
    then same-case referential integrity (ERR_CROSS_CASE_REFERENCE), then the
    optimistic-concurrency version check on guarded writes (ERR_STALE_VERSION), then
    whether the target resource is in a state from which the requested transition is
    defined (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_motion_rule
    """
    # Motion is in FILED (not UNDER_SUBMISSION) and the caller is an Attorney (not Judge).
    base = setup_motion_filed(clock="2026-03-01T00:00:00.000Z")
    resp = api.rule_motion(
        base["motion"]["id"], rule_motion_payload(ruling="GRANT", order_text="x"),
        make_attorney_headers(ATT_PL))
    validate_error(resp, "ERR_FORBIDDEN")


# =====================================================================
# Queue A: cross_entity_state_dependency
# =====================================================================
def test_filing_accept_blocked_by_case_frozen(api):
    """PRD 3.2: "Accepting requires that the owning case's posture is not FROZEN (else
    ERR_CASE_FROZEN) and, when the document is a COMPLAINT with a positive fee_cents,
    that its fee_status is PAID or WAIVED rather than still ASSESSED (else
    ERR_FILING_FEE_UNPAID)."

    Design: Difficulty/cross_entity_state_dependency/filing_accept_blocked_by_case_frozen
    """
    base = setup_stayed_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    # Second complaint, fee PAID, UNDER_REVIEW — only the frozen gate should bar accept.
    f2 = efile(case_id, base["plaintiff"]["id"], ATT_PL,
               document_type="COMPLAINT", title="Complaint 2")
    get_success_data(api.pay_fee(f2["id"], CLERK))
    get_success_data(api.claim_review_filing(f2["id"], CLERK))

    resp = api.accept_filing(f2["id"], CLERK)
    validate_error(resp, "ERR_CASE_FROZEN")


def test_service_complete_blocked_by_case_not_open(api):
    """PRD 3.3: "Completing service is the depth-three cascade at the heart of the
    early-case timeline, and it carries three preconditions: the record must be
    `ATTEMPTED`, the owning case must be `OPEN` (else `ERR_CASE_NOT_OPEN`), and the
    `served_party_id` must refer to a `DEFENDANT` party whose `service_status` is not
    already `SERVED` (else `ERR_PARTY_ALREADY_SERVED`)."

    Design: Difficulty/cross_entity_state_dependency/service_complete_blocked_by_case_not_open
    """
    # DRAFT case (never opened) with a defendant and an ATTEMPTED service.
    base = setup_draft_case(clock="2026-03-02T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    df = add_party(case_id, role="DEFENDANT", attorney_user_id=ATT_DF)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    sop = add_attempted_service(case_id, complaint["id"], df["id"],
                                service_date="2026-03-02T00:00:00.000Z")

    resp = api.complete_service(sop["id"], CLERK)
    validate_error(resp, "ERR_CASE_NOT_OPEN")


# =====================================================================
# Queue B (Corner): validations section
# =====================================================================
def test_statute_expired_blocks_complaint_accept(api):
    """PRD 3.2: "A further bar applies to complaints: a COMPLAINT filing cannot be
    accepted once the case's STATUTE_OF_LIMITATIONS deadline due_date has passed relative
    to the current clock; such an attempt is rejected with ERR_STATUTE_EXPIRED."

    Design: Corner/validations/statute_expired_blocks_complaint_accept
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    # A manual STATUTE_OF_LIMITATIONS deadline due 2026-03-16.
    get_success_data(api.create_deadline({
        "case_id": case_id, "deadline_type": "STATUTE_OF_LIMITATIONS",
        "anchor_event": "MANUAL", "anchor_date": "2026-03-06T00:00:00.000Z",
        "interval_days": 10, "counting_mode": "CALENDAR",
    }, CLERK))
    # A second complaint, paid + under review.
    f2 = efile(case_id, base["plaintiff"]["id"], ATT_PL,
               document_type="COMPLAINT", title="Complaint late")
    get_success_data(api.pay_fee(f2["id"], CLERK))
    get_success_data(api.claim_review_filing(f2["id"], CLERK))
    # Advance past the statute due date.
    get_success_data(api.set_clock("2026-04-01T00:00:00.000Z", ADMIN))

    resp = api.accept_filing(f2["id"], CLERK)
    validate_error(resp, "ERR_STATUTE_EXPIRED")


def test_cross_case_reference_motion_party_wrong_case(api):
    """PRD 2.5: "A motion's moving_party_id must be a party of the motion's case_id ...
    A foreign key that resolves to a resource belonging to a different case, or to a
    party with the wrong role, is rejected with ERR_CROSS_CASE_REFERENCE."

    Design: Corner/validations/cross_case_reference_motion_party_wrong_case
    """
    set_a = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    court_id = set_a["court"]["id"]
    case_a = set_a["case"]["id"]
    pa_pl = add_party(case_a, role="PLAINTIFF", attorney_user_id=ATT_PL)
    fa_mot = add_accepted_motion_filing(case_a, pa_pl["id"], title="Mtn A")

    # Second case under the same court with its own plaintiff.
    case_b = get_success_data(api.create_case({
        "court_id": court_id, "caption": "Case B", "case_type": "TORT"}, CLERK))
    pb_pl = add_party(case_b["id"], role="PLAINTIFF", attorney_user_id=ATT_PL)

    resp = api.create_motion(
        create_motion_payload(case_a, fa_mot["id"], pb_pl["id"], motion_type="DISMISS"),
        make_attorney_headers(ATT_PL))
    validate_error(resp, "ERR_CROSS_CASE_REFERENCE")


def test_appeal_window_closed_late_filing(api):
    """PRD 3.8: "It requires the case to be in JUDGMENT_ENTERED, requires the filed_on
    date to fall within the court's appeal_window_days after the judgment's entered_at
    inclusive — an appeal filed past that window is rejected with ERR_APPEAL_WINDOW_CLOSED
    — and is OCC-guarded on the case as described in Section 2.9."

    Design: Corner/validations/appeal_window_closed_late_filing
    """
    from test_helpers import setup_judgment_entered
    base = setup_judgment_entered(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    get_success_data(api.set_clock("2026-05-15T00:00:00.000Z", ADMIN))

    resp = api.create_appeal({
        "case_id": case_id, "judgment_id": base["judgment"]["id"],
        "appellant_party_id": base["defendant"]["id"],
        "filed_on": "2026-05-15T00:00:00.000Z",
        "expected_case_version": base["case_version"],
    }, make_attorney_headers(ATT_DF))
    validate_error(resp, "ERR_APPEAL_WINDOW_CLOSED")


def test_judgment_blocked_by_pending_motion(api):
    """PRD 3.7: "It requires that the case be OPEN, that no motion under the case remains
    in status FILED or UNDER_SUBMISSION (else ERR_PENDING_MOTIONS), and that the request
    carry an expected_case_version matching the case's current version as described in
    Section 2.9."

    Design: Corner/validations/judgment_blocked_by_pending_motion
    """
    base = setup_motion_filed(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    case_now = get_success_data(api.get_case(case_id, CLERK))

    resp = api.create_judgment({
        "case_id": case_id, "judgment_type": "TRIAL",
        "prevailing_party_id": base["plaintiff"]["id"],
        "principal_cents": 0, "interest_rate_bps": 0,
        "expected_case_version": case_now["version"],
    }, JUDGE)
    validate_error(resp, "ERR_PENDING_MOTIONS")


# =====================================================================
# Queue B (Corner): consistency_model (posture)
# =====================================================================
def test_restricted_posture_visible_immediately(api):
    """PRD 2.7: "Otherwise, if the case has at least one deadline in status MISSED, or
    the number of its deadlines in status PENDING is five or more, the posture is
    RESTRICTED."

    Design: Corner/consistency_model/immediate_posture_visible_in_same_response
    """
    base = setup_restricted_case(clock="2026-03-01T00:00:00.000Z")
    case = validate_success(api.get_case(base["case"]["id"], CLERK))
    assert case["open_deadline_count"] == 5, case["open_deadline_count"]
    assert case["posture"] == "RESTRICTED", case["posture"]


def test_restricted_posture_blocks_new_motion(api):
    """PRD 2.7: "A RESTRICTED posture blocks the filing of a new motion — rejected with
    ERR_CASE_RESTRICTED — but still permits deadline-satisfying filings to proceed, so
    that a litigant can cure an overdue obligation even while the case is restricted."

    Design: Corner/consistency_model/restricted_blocks_new_motion
    """
    base = setup_restricted_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    mfiling = add_accepted_motion_filing(case_id, base["plaintiff"]["id"])

    resp = api.create_motion(
        create_motion_payload(case_id, mfiling["id"], base["plaintiff"]["id"],
                              motion_type="DISMISS"),
        make_attorney_headers(ATT_PL))
    validate_error(resp, "ERR_CASE_RESTRICTED")
