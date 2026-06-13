"""Creation, computed fields, defaults, listing, and the filing/case/deadline
state machines (corner-design breadth probes).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, make_attorney_headers, TEST_USERS,
    create_filing_payload, create_party_payload,
    setup_draft_case, setup_open_case, add_party, efile, review_accept,
    schedule_hearing, add_accepted_motion_filing, file_motion,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"
ATT_DF = "att_2"


# =====================================================================
# Queue B (Corner): entities
# =====================================================================
def test_create_case_returns_201_with_minted_number(api):
    """PRD 3.1: "The new case is created in status DRAFT with posture ACTIVE, and its
    case_number is minted at creation as described in Section 2.4."
    PRD 2.4: "The first case for a given court in a given year therefore receives
    sequence 000001."

    Design: Corner/entities/create_case_returns_201_with_minted_case_number
    """
    get_success_data(api.set_clock("2026-01-15T00:00:00.000Z", ADMIN))
    court = get_success_data(api.create_court(
        {"name": "Sup Ct AA", "jurisdiction_code": "CA", "filing_fee_cents": 43500}, ADMIN))
    case = validate_success(api.create_case(
        {"court_id": court["id"], "caption": "Acme v Beta", "case_type": "CONTRACT"}, CLERK),
        expected_status=201)
    assert case["status"] == "DRAFT", case["status"]
    assert case["posture"] == "ACTIVE", case["posture"]
    assert case["case_number"] == "CA-2026-CV-000001", case["case_number"]


def test_case_number_sequence_increments_per_court_per_year(api):
    """PRD 2.4: "the sequence is one greater than the number of existing cases already
    minted for the same court in that same year."

    Design: Corner/entities/case_number_sequence_increments_per_court_per_year
    """
    get_success_data(api.set_clock("2026-02-01T00:00:00.000Z", ADMIN))
    court = get_success_data(api.create_court(
        {"name": "Sup Ct AB", "jurisdiction_code": "CA", "filing_fee_cents": 43500}, ADMIN))
    get_success_data(api.create_case(
        {"court_id": court["id"], "caption": "First", "case_type": "CONTRACT"}, CLERK))
    c2 = validate_success(api.create_case(
        {"court_id": court["id"], "caption": "Second", "case_type": "TORT"}, CLERK),
        expected_status=201)
    assert c2["case_number"] == "CA-2026-CV-000002", c2["case_number"]


def test_get_case_nonexistent_returns_not_found(api):
    """PRD 2.5: "a request that names a case, a filing, and a party resolves them in that
    order and is rejected at the first identifier that does not correspond to an existing
    resource. Any such failure yields ERR_NOT_FOUND."

    Design: Corner/entities/get_case_nonexistent_returns_not_found
    """
    resp = api.get_case(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, "ERR_NOT_FOUND")


def test_create_filing_missing_document_type_invalid_request(api):
    """PRD 2.10: "Request-body well-formedness under ERR_INVALID_REQUEST covers the
    presence of required fields, valid enum values, non-negative numbers, and the rule
    that any end_at strictly exceeds its corresponding start_at."

    Design: Corner/entities/create_filing_missing_required_field_returns_invalid_request
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    pl = add_party(base["case"]["id"], role="PLAINTIFF", attorney_user_id=ATT_PL)
    payload = {"case_id": base["case"]["id"], "filed_by_party_id": pl["id"], "title": "No type"}
    resp = api.create_filing(payload, make_attorney_headers(ATT_PL))
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_party_invalid_role_enum_invalid_request(api):
    """PRD 3.2: "A Clerk adds parties to a case by supplying the case_id, the party's
    display_name, its role (one of PLAINTIFF or DEFENDANT), and the attorney_user_id of
    the attorney who represents that party."

    Design: Corner/entities/create_party_invalid_enum_role_returns_invalid_request
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    resp = api.create_party(create_party_payload(
        base["case"]["id"], display_name="W", role="WITNESS", attorney_user_id=ATT_PL), CLERK)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_noncomplaint_filing_has_zero_fee(api):
    """PRD 3.2: "Its fee_cents is computed at this point: a COMPLAINT is charged the
    owning court's filing_fee_cents, and every other document type is charged zero. The
    fee_status follows from that amount — ASSESSED when fee_cents is greater than zero,
    and NONE when fee_cents is zero."

    Design: Corner/entities/filing_default_fee_zero_for_noncomplaint
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    pl = add_party(base["case"]["id"], role="PLAINTIFF", attorney_user_id=ATT_PL)
    answer = validate_success(api.create_filing(create_filing_payload(
        base["case"]["id"], pl["id"], document_type="ANSWER", title="Answer"),
        make_attorney_headers(ATT_PL)), expected_status=201)
    assert answer["fee_cents"] == 0, answer["fee_cents"]
    assert answer["fee_status"] == "NONE", answer["fee_status"]


def test_list_cases_pagination_envelope(api):
    """PRD 2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_cases_pagination_envelope
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00.000Z", ADMIN))
    court = get_success_data(api.create_court(
        {"name": "Sup Ct AF", "jurisdiction_code": "CA", "filing_fee_cents": 43500}, ADMIN))
    get_success_data(api.create_case(
        {"court_id": court["id"], "caption": "C1", "case_type": "CONTRACT"}, CLERK))
    get_success_data(api.create_case(
        {"court_id": court["id"], "caption": "C2", "case_type": "TORT"}, CLERK))

    data, meta = validate_paginated(
        api.list_cases(CLERK, params={"court_id": court["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)


def test_create_case_ignores_client_status(api):
    """PRD 3.1: "The new case is created in status DRAFT with posture ACTIVE, and its
    case_number is minted at creation as described in Section 2.4."

    Design: Corner/entities/system_fields_input_ignored_on_create_case
    """
    get_success_data(api.set_clock("2026-03-01T00:00:00.000Z", ADMIN))
    court = get_success_data(api.create_court(
        {"name": "Sup Ct AG", "jurisdiction_code": "CA", "filing_fee_cents": 43500}, ADMIN))
    case = validate_success(api.create_case(
        {"court_id": court["id"], "caption": "Acme v Beta", "case_type": "CONTRACT",
         "status": "OPEN", "case_number": "ZZ-9999-CV-999999"}, CLERK),
        expected_status=201)
    assert case["status"] == "DRAFT", case["status"]


# =====================================================================
# Queue B (Corner): state_machines (case-open preconditions, filing cycle)
# =====================================================================
def test_open_case_missing_defendant_rejected(api):
    """PRD 3.1: "There must be at least one PLAINTIFF party and at least one DEFENDANT
    party on the case, failing which the open is rejected with ERR_CASE_MISSING_PARTIES."

    Design: Corner/state_machines/open_case_missing_defendant_returns_missing_parties
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    get_success_data(api.pay_fee(complaint["id"], CLERK))
    get_success_data(api.claim_review_filing(complaint["id"], CLERK))
    get_success_data(api.accept_filing(complaint["id"], CLERK))

    resp = api.open_case(case_id, CLERK)
    validate_error(resp, "ERR_CASE_MISSING_PARTIES")


def test_open_case_without_accepted_complaint_rejected(api):
    """PRD 3.1: "there must be at least one `ACCEPTED` filing whose `document_type` is
    `COMPLAINT`, failing which it is rejected with `ERR_NO_ACCEPTED_COMPLAINT`."

    Design: Corner/state_machines/open_case_without_accepted_complaint_returns_no_complaint
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    add_party(case_id, role="DEFENDANT", attorney_user_id=ATT_DF)
    # Complaint stays SUBMITTED (never accepted).
    efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")

    resp = api.open_case(case_id, CLERK)
    validate_error(resp, "ERR_NO_ACCEPTED_COMPLAINT")


def test_claim_review_on_accepted_filing_invalid_state(api):
    """PRD 3.2: "Both `ACCEPTED` and `REJECTED` are terminal for that filing row."

    Design: Corner/state_machines/claim_review_from_accepted_returns_invalid_state
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    answer = efile(case_id, pl["id"], ATT_PL, document_type="ANSWER", title="Answer")
    review_accept(answer["id"])

    resp = api.claim_review_filing(answer["id"], CLERK)
    validate_error(resp, "ERR_INVALID_STATE")


def test_reject_filing_without_reason_rejected(api):
    """PRD 3.2: "Rejecting a filing requires a rejection_reason to be supplied; without
    one the rejection is refused with ERR_REJECTION_REASON_REQUIRED."

    Design: Corner/state_machines/reject_filing_without_reason_returns_reason_required
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    ex = efile(case_id, pl["id"], ATT_PL, document_type="EXHIBIT", title="Ex")
    get_success_data(api.claim_review_filing(ex["id"], CLERK))

    resp = api.reject_filing(ex["id"], {}, CLERK)
    validate_error(resp, "ERR_REJECTION_REASON_REQUIRED")


def test_resubmit_links_rejected_predecessor(api):
    """PRD 3.2: "the attorney files afresh, the new row is created in SUBMITTED, the
    referenced rejected filing stays REJECTED, and the two are linked."

    Design: Corner/state_machines/resubmit_filing_links_rejected_predecessor
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    bad = efile(case_id, pl["id"], ATT_PL, document_type="EXHIBIT", title="Ex bad")
    get_success_data(api.claim_review_filing(bad["id"], CLERK))
    get_success_data(api.reject_filing(bad["id"], {"rejection_reason": "Illegible"}, CLERK))

    new = validate_success(api.create_filing(create_filing_payload(
        case_id, pl["id"], document_type="EXHIBIT", title="Ex fixed",
        resubmits_filing_id=bad["id"]), make_attorney_headers(ATT_PL)), expected_status=201)
    bad_after = validate_success(api.get_filing(bad["id"], CLERK))

    assert new["status"] == "SUBMITTED", new["status"]
    assert new["resubmits_filing_id"] == bad["id"], new["resubmits_filing_id"]
    assert bad_after["status"] == "REJECTED", bad_after["status"]


def test_resubmit_target_not_rejected_rejected(api):
    """PRD 3.2: "The resubmission target must itself be in status REJECTED; pointing
    resubmits_filing_id at a filing in any other state is rejected with
    ERR_RESUBMIT_TARGET_NOT_REJECTED."

    Design: Corner/errors/resubmit_target_not_rejected_returns_error
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    ok = efile(case_id, pl["id"], ATT_PL, document_type="EXHIBIT", title="Ex")  # SUBMITTED

    resp = api.create_filing(create_filing_payload(
        case_id, pl["id"], document_type="EXHIBIT", title="Ex2",
        resubmits_filing_id=ok["id"]), make_attorney_headers(ATT_PL))
    validate_error(resp, "ERR_RESUBMIT_TARGET_NOT_REJECTED")


def test_judgment_satisfied_then_vacate_invalid_state(api):
    """PRD 3.7: "`SATISFIED` and `VACATED` are terminal judgment states."

    Design: Corner/state_machines/terminal_judgment_satisfied_lockdown
    """
    from test_helpers import setup_judgment_entered
    base = setup_judgment_entered(clock="2026-04-01T00:00:00.000Z")
    get_success_data(api.satisfy_judgment(base["judgment"]["id"], CLERK))

    resp = api.vacate_judgment(base["judgment"]["id"], JUDGE)
    validate_error(resp, "ERR_INVALID_STATE")


def test_deadline_mark_missed_before_due_rejected(api):
    """PRD 3.4: "It may be marked missed by a clerk, but only once the current clock is
    strictly past its due_date; an attempt before then is rejected with
    ERR_DEADLINE_NOT_YET_DUE."

    Design: Corner/state_machines/deadline_mark_missed_before_due_returns_not_yet_due
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    dl = get_success_data(api.create_deadline({
        "case_id": case_id, "deadline_type": "DISCOVERY", "anchor_event": "MANUAL",
        "anchor_date": "2026-03-04T00:00:00.000Z", "interval_days": 10,
        "counting_mode": "CALENDAR"}, CLERK))

    resp = api.mark_missed_deadline(dl["id"], CLERK)
    validate_error(resp, "ERR_DEADLINE_NOT_YET_DUE")


def test_hold_hearing_before_start_rejected(api):
    """PRD 3.5: "Holding a hearing is allowed only once the current clock is at or after
    its start_at; an earlier attempt is rejected with ERR_HEARING_NOT_STARTED."

    Design: Corner/state_machines/hold_hearing_before_start_returns_not_started
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    hearing = schedule_hearing(case_id, courtroom="A", judge_user_id="jdg_1",
                               start_at="2026-03-05T10:00:00.000Z",
                               end_at="2026-03-05T11:00:00.000Z")
    # Clock still at 2026-03-01, before start_at.
    resp = api.hold_hearing(hearing["id"], JUDGE)
    validate_error(resp, "ERR_HEARING_NOT_STARTED")


# =====================================================================
# Queue B (Corner): endpoints (filtered lists)
# =====================================================================
def test_list_motions_filtered_by_case(api):
    """PRD 2.5: "reverse navigation is provided through filtered list endpoints (for
    example, listing motions for a given case)."

    Design: Corner/endpoints/list_motions_filtered_by_case_id
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    mfiling = add_accepted_motion_filing(case_id, pl["id"])
    file_motion(case_id, mfiling["id"], pl["id"], motion_type="DISMISS")

    data, meta = validate_paginated(api.list_motions(JUDGE, params={"case_id": case_id}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert len(data) == 1, len(data)


def test_order_discoverable_via_filtered_list_by_motion(api):
    """PRD 2.5: "Resources in this system are peers that reference their owners by foreign
    key rather than by deep URL nesting, so reverse navigation is provided through
    filtered list endpoints (for example, listing motions for a given case)."

    Design: Corner/endpoints/order_discoverable_via_filtered_list_by_motion
    """
    from test_helpers import setup_motion_under_submission
    base = setup_motion_under_submission(clock="2026-03-01T00:00:00.000Z",
                                         motion_overrides={"opposed": True})
    get_success_data(api.rule_motion(
        base["motion"]["id"], {"ruling": "DENY", "order_text": "Denied"}, JUDGE))

    data, meta = validate_paginated(
        api.list_orders(CLERK, params={"motion_id": base["motion"]["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert len(data) == 1, len(data)
