"""Cross-entity referential-state dependencies and temporal-overlap booking rules.

Translates queue A (Difficulty) rules cross_entity_state_dependency and
resource_temporal_overlap.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import make_judge_headers, make_mediator_headers

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Rule: cross_entity_state_dependency — instance answer_serve_requires_petition_served
# =========================================================================
def test_answer_serve_requires_petition_served(api):
    """PRD §3.2: "An answer may only be served after the case's petition has already been
    served; attempting to serve an answer while the petition is not yet served is rejected
    with `ERR_PETITION_NOT_SERVED`."

    Design: Difficulty/cross_entity_state_dependency/answer_serve_requires_petition_served
    """
    case, pet, petition = FX.setup_filed_case_with_petitioner()  # petition still DRAFT
    res = FX.add_respondent(case["id"])
    answer = FX.file_pleading(case["id"], "ANSWER", res["id"])
    resp = api.serve_pleading(answer["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_SERVED.value)


def test_answer_serve_succeeds_once_petition_served(api):
    """PRD §3.2: "If the respondent files an answer (which must be filed by the respondent
    party) and that answer is served, the case advances from `AWAITING_RESPONSE` to
    `CONTESTED` ... as a system side effect the original petition transitions from
    `SERVED` to `ANSWERED`".

    Positive control: once the petition is SERVED, serving the answer succeeds and the
    petition becomes ANSWERED — confirming the dependency was the only blocker.

    Design: Difficulty/cross_entity_state_dependency/answer_serve_requires_petition_served
    """
    case, pet, petition = FX.setup_awaiting_response()  # petition SERVED
    res = FX.add_respondent(case["id"])
    answer = FX.file_pleading(case["id"], "ANSWER", res["id"])
    validate_success(api.serve_pleading(answer["id"], CLERK), 200)
    fetched_petition = validate_success(api.get_pleading(petition["id"], CLERK), 200)
    assert fetched_petition["status"] == "ANSWERED"


# =========================================================================
# Rule: cross_entity_state_dependency — instance final_judgment_requires_disclosures_verified
# =========================================================================
def test_final_judgment_requires_disclosures_verified(api):
    """PRD §3.7: "the disclosures must be verified: both parties' financial disclosures
    must be `VERIFIED` ... except on the default path, where the petitioner's disclosure
    being verified suffices; failing this, entry is rejected with
    `ERR_DISCLOSURES_NOT_VERIFIED`."

    Contested-path FINAL_JUDGMENT with the respondent disclosure only SUBMITTED.

    Design: Difficulty/cross_entity_state_dependency/final_judgment_requires_disclosures_verified
    """
    # Contested case in MEDIATION; petitioner VERIFIED, respondent SUBMITTED only.
    ctx = FX.setup_case_in_mediation(pet_gross=800000, res_gross=400000,
                                     verify_respondent=False, children=1)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    FX.agree_plan(plan["id"], "u-res", "RESPONDENT")
    session = FX.schedule_session(case["id"], "u-med")
    FX.start_session(session["id"], "u-med")
    FX.conclude_session(session["id"], "FULL_AGREEMENT", "u-med")  # case -> AWAITING_JUDGMENT
    support = FX.create_support_order(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY")
    final_order = FX.draft_court_order(case["id"], "FINAL_JUDGMENT", [support["id"]],
                                       parenting_plan_id=plan["id"])
    version = FX.current_case_version(case["id"])
    resp = api.enter_court_order(
        final_order["id"], {"expected_case_version": version}, make_judge_headers("u-judge"))
    validate_error(resp, ApiErrorId.ERR_DISCLOSURES_NOT_VERIFIED.value)


def test_final_judgment_enters_once_both_disclosures_verified(api):
    """PRD §3.7: "A `FINAL_JUDGMENT` may be entered only while the case is in
    `AWAITING_JUDGMENT` ... both parties' financial disclosures must be `VERIFIED` (the
    case's `petitioner_disclosure_verified` and `respondent_disclosure_verified` flags
    both true)".

    Positive control: with both disclosures VERIFIED, entry succeeds and the case becomes
    JUDGMENT_ENTERED — confirming the disclosure-state dependency was the only blocker.

    Design: Difficulty/cross_entity_state_dependency/final_judgment_requires_disclosures_verified
    """
    ctx = FX.setup_default_awaiting_judgment_with_temp_order()
    case, final_order = ctx["case"], ctx["final_order"]
    version = FX.current_case_version(case["id"])
    entered = validate_success(api.enter_court_order(
        final_order["id"], {"expected_case_version": version}, make_judge_headers("u-judge")), 200)
    assert entered["status"] == "ENTERED"
    fetched_case = validate_success(api.get_case(case["id"], CLERK), 200)
    assert fetched_case["status"] == "JUDGMENT_ENTERED"


# =========================================================================
# Rule: resource_temporal_overlap — instance mediator_double_booking_closed_interval_adjacency
# =========================================================================
def _setup_mediation_with_session(start, end):
    ctx = FX.setup_case_in_mediation(pet_gross=800000, res_gross=400000)
    case = ctx["case"]
    FX.schedule_session(case["id"], "u-med", scheduled_start=start, scheduled_end=end)
    return case


def test_mediator_adjacent_session_rejected_closed_interval(api):
    """PRD §3.5: "the booking interval is treated as a **closed** interval
    `[scheduled_start, scheduled_end]`, so two sessions that merely touch at an endpoint
    (a gap of zero) are still considered a conflict — a mandatory clearance buffer means
    adjacent sessions collide. A colliding session is rejected with
    `ERR_MEDIATOR_DOUBLE_BOOKED` (HTTP 409)."

    First session 09:00-11:00; second starts exactly at 11:00 -> rejected.

    Design: Difficulty/resource_temporal_overlap/mediator_double_booking_closed_interval_adjacency
    """
    case = _setup_mediation_with_session("2026-07-01T09:00:00Z", "2026-07-01T11:00:00Z")
    resp = api.create_mediation_session(F.mediation_session_payload(
        case["id"], "u-med", "2026-07-01T11:00:00Z", "2026-07-01T12:00:00Z"),
        make_mediator_headers("u-med"))
    validate_error(resp, ApiErrorId.ERR_MEDIATOR_DOUBLE_BOOKED.value)


def test_mediator_overlapping_session_rejected(api):
    """PRD §3.5: "A new session must not collide with an existing non-terminal session of
    the *same* mediator".

    A genuinely overlapping session (10:00-12:00 over an existing 09:00-11:00) is rejected.

    Design: Difficulty/resource_temporal_overlap/mediator_double_booking_closed_interval_adjacency
    """
    case = _setup_mediation_with_session("2026-07-01T09:00:00Z", "2026-07-01T11:00:00Z")
    resp = api.create_mediation_session(F.mediation_session_payload(
        case["id"], "u-med", "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z"),
        make_mediator_headers("u-med"))
    validate_error(resp, ApiErrorId.ERR_MEDIATOR_DOUBLE_BOOKED.value)


# =========================================================================
# Rule: resource_temporal_overlap — instance hearing_back_to_back_half_open_allowed_but_overlap_rejected
# =========================================================================
def test_hearing_back_to_back_allowed_half_open(api):
    """PRD §3.8: "courtroom intervals are treated as **half-open**
    `[scheduled_start, scheduled_end)`, so back-to-back hearings where one's end exactly
    equals the next one's start are allowed".

    First hearing 09:00-10:00; a back-to-back 10:00-11:00 in the same courtroom succeeds.

    Design: Difficulty/resource_temporal_overlap/hearing_back_to_back_half_open_allowed_but_overlap_rejected
    """
    case = FX.create_case()
    validate_success(api.create_hearing(F.hearing_payload(
        case["id"], "DEPT-3", "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z"), CLERK), 201)
    back_to_back = validate_success(api.create_hearing(F.hearing_payload(
        case["id"], "DEPT-3", "2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z"), CLERK), 201)
    assert back_to_back["status"] == "SCHEDULED"


def test_hearing_genuine_overlap_rejected(api):
    """PRD §3.8: "any true overlap is rejected with `ERR_COURTROOM_DOUBLE_BOOKED`
    (HTTP 409)."

    A hearing 09:30-10:30 overlapping an existing 09:00-10:00 in the same courtroom is
    rejected.

    Design: Difficulty/resource_temporal_overlap/hearing_back_to_back_half_open_allowed_but_overlap_rejected
    """
    case = FX.create_case()
    validate_success(api.create_hearing(F.hearing_payload(
        case["id"], "DEPT-3", "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z"), CLERK), 201)
    validate_success(api.create_hearing(F.hearing_payload(
        case["id"], "DEPT-3", "2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z"), CLERK), 201)
    resp = api.create_hearing(F.hearing_payload(
        case["id"], "DEPT-3", "2026-07-02T09:30:00Z", "2026-07-02T10:30:00Z"), CLERK)
    validate_error(resp, ApiErrorId.ERR_COURTROOM_DOUBLE_BOOKED.value)
