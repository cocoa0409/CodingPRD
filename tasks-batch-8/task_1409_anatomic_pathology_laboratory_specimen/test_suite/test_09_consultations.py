"""Second-opinion consultations: creation segregation checks, subspecialty
and due-date gates, wrong-state actions, unavailability at accept, the
decline/reroute cycle, and the strict expiry sweep boundary."""
from test_helpers import (
    ApiErrorId,
    accept_consultation,
    assign_case,
    create_case,
    create_consultation,
    create_coverage_window,
    create_patient,
    create_pathologist,
    decline_consultation,
    get_consultation,
    make_pathologist_headers,
    reroute_consultation,
    set_clock,
    setup_consulted_case,
    setup_workup_case,
    validate_error,
    validate_success,
)


def test_consult_self_and_assigned_rejected(api):
    """PRD §3.7: "The consultant identity checks run in a fixed order (§2.9):
    the consultant must differ from the requester (`ERR_SELF_CONSULTATION`,
    HTTP 422), then from the case's assigned pathologist
    (`ERR_CONSULTANT_IS_ASSIGNED`, HTTP 422)"

    Design: Corner/validations/consult_self_and_assigned_rejected
    """
    ctx = setup_workup_case(mrn="MRN-V7", num_blocks=0)
    case_id = ctx["case"]["id"]
    p1 = create_pathologist(full_name="Dr A")
    p2 = create_pathologist(full_name="Dr B")
    assign_case(case_id, p1["id"])

    # p2 names themself consultant.
    resp = api.create_consultation(
        case_id,
        {
            "consultant_pathologist_id": p2["id"],
            "subspecialty": "GI",
            "question_text": "self",
            "due_at": "2026-08-10T00:00:00Z",
        },
        make_pathologist_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_CONSULTATION)

    # p2 names the case assignee p1 as consultant.
    resp = api.create_consultation(
        case_id,
        {
            "consultant_pathologist_id": p1["id"],
            "subspecialty": "GI",
            "question_text": "assigned",
            "due_at": "2026-08-10T00:00:00Z",
        },
        make_pathologist_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSULTANT_IS_ASSIGNED)


def test_consult_subspecialty_and_due_at_rejected(api):
    """PRD §3.7: "the requested `subspecialty` must be a member of the
    consultant's `subspecialties` (`ERR_SUBSPECIALTY_MISMATCH`, HTTP 422); and
    `due_at` must be strictly in the future (`ERR_DUE_AT_NOT_FUTURE`,
    HTTP 422)."

    Design: Corner/validations/consult_subspecialty_and_due_at_rejected
    """
    ctx = setup_workup_case(mrn="MRN-V8", num_blocks=0)
    case_id = ctx["case"]["id"]
    p1 = create_pathologist(full_name="Dr A")
    p2 = create_pathologist(full_name="Dr B")
    p3 = create_pathologist(full_name="Dr C", subspecialties=("HEME",))
    assign_case(case_id, p1["id"])

    # p3 holds HEME only, not the requested GI.
    resp = api.create_consultation(
        case_id,
        {
            "consultant_pathologist_id": p3["id"],
            "subspecialty": "GI",
            "question_text": "heme doc",
            "due_at": "2026-08-10T00:00:00Z",
        },
        make_pathologist_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBSPECIALTY_MISMATCH)

    # due_at precedes the 2026-08-01T00:00:00Z startup logical clock.
    resp = api.create_consultation(
        case_id,
        {
            "consultant_pathologist_id": p2["id"],
            "subspecialty": "GI",
            "question_text": "past due",
            "due_at": "2026-07-01T00:00:00Z",
        },
        make_pathologist_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUE_AT_NOT_FUTURE)


def test_consult_on_open_case_rejected(api):
    """PRD §3.7: "The case must be in `WORKUP`, `PENDING_SIGNOUT`, `FINAL`, or
    `AMENDING` — an `OPEN` or `CANCELLED` case is not consultable and yields
    `ERR_CASE_NOT_CONSULTABLE` (HTTP 409)."

    Design: Corner/errors/consult_on_open_case_rejected
    """
    patient = create_patient(mrn="MRN-RC", full_name="Err Twelve")
    p1 = create_pathologist(full_name="Dr Q1")
    p2 = create_pathologist(full_name="Dr Q2")
    case = create_case(patient["id"], subspecialty="GI")
    assert case["status"] == "OPEN"

    resp = api.create_consultation(
        case["id"],
        {
            "consultant_pathologist_id": p2["id"],
            "subspecialty": "GI",
            "question_text": "too early",
            "due_at": "2026-08-10T00:00:00Z",
        },
        make_pathologist_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_CONSULTABLE)


def test_consult_answer_before_accept_rejected(api):
    """PRD §3.7: "Consultation actions from disallowed states — accept or
    decline when not `REQUESTED`, answer when not `ACCEPTED`, incorporate when
    not `ANSWERED`, reroute when not `DECLINED` or `EXPIRED` — are rejected
    with `ERR_CONSULTATION_WRONG_STATE` (HTTP 409)."

    Design: Corner/errors/consult_answer_before_accept_rejected
    """
    ctx = setup_consulted_case(mrn="MRN-R5")
    consultation = ctx["consultation"]
    assert consultation["status"] == "REQUESTED"

    resp = api.answer_consultation(
        consultation["id"],
        {"opinion_text": "early", "concordance": "CONCORDANT"},
        make_pathologist_headers(ctx["consultant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSULTATION_WRONG_STATE)


def test_consult_accept_inside_unavailable_window_rejected(api):
    """PRD §3.7: "Accepting moves `REQUESTED → ACCEPTED` and requires the
    caller to be the named consultant, the logical clock to be strictly before
    `due_at` (a consultation past its deadline will already have been swept to
    `EXPIRED`), and the consultant not to be inside an `ACTIVE` `UNAVAILABLE`
    window under closed containment — `start_at` at or before now and `end_at`
    at or after now — with a violation rejected as `ERR_CONSULTANT_UNAVAILABLE`
    (HTTP 422)."

    Design: Corner/validations/consult_accept_inside_unavailable_window_rejected
    """
    ctx = setup_consulted_case(mrn="MRN-V9", consultant_name="Dr Away")
    consultant = ctx["consultant"]
    consultation = ctx["consultation"]
    create_coverage_window(
        consultant["id"], "UNAVAILABLE", "2026-08-03T09:00:00Z", "2026-08-03T17:00:00Z"
    )
    set_clock("2026-08-03T12:00:00Z")

    resp = api.accept_consultation(
        consultation["id"], make_pathologist_headers(consultant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONSULTANT_UNAVAILABLE)
    assert get_consultation(consultation["id"])["status"] == "REQUESTED"


def test_consultation_decline_then_reroute_cycle(api):
    """PRD §3.7: "Declining moves `REQUESTED → DECLINED` and records the
    supplied `reason` in `decline_reason`."
    PRD §3.7: "Consultations cycle: from `DECLINED` or `EXPIRED`, the
    requester may reroute to a new consultant with a new `due_at`, returning
    the consultation to `REQUESTED`."
    PRD §3.7: "success replaces `consultant_pathologist_id` and `due_at` and
    increments `reroute_count` by 1."

    Design: Corner/state_machines/consultation_decline_then_reroute_cycle
    """
    ctx = setup_consulted_case(mrn="MRN-S5", due_at="2026-08-10T00:00:00Z")
    consultation = ctx["consultation"]
    p3 = create_pathologist(full_name="Dr Free")

    declined = decline_consultation(
        consultation["id"], ctx["consultant"]["id"], reason="overloaded"
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "overloaded"

    rerouted = reroute_consultation(
        consultation["id"], ctx["requester"]["id"], p3["id"], "2026-08-12T00:00:00Z"
    )
    assert rerouted["status"] == "REQUESTED", "the cycle returned to REQUESTED"
    assert rerouted["consultant_pathologist_id"] == p3["id"]
    assert rerouted["due_at"].startswith("2026-08-12T00:00:00")
    assert rerouted["reroute_count"] == 1


def test_consultation_expiry_sweep_strict_boundary(api):
    """PRD §2.5: "Every consultation still in `REQUESTED` whose `due_at` is
    strictly before the new clock value transitions to `EXPIRED` — a `due_at`
    exactly equal to the new clock value is not expired."

    Design: Corner/state_machines/consultation_expiry_sweep_strict_boundary
    """
    ctx = setup_consulted_case(mrn="MRN-S6", due_at="2026-08-05T00:00:00Z")
    consultation = ctx["consultation"]

    # At exactly due_at the consultation is not expired.
    set_clock("2026-08-05T00:00:00Z")
    assert get_consultation(consultation["id"])["status"] == "REQUESTED"

    # One second past due_at the sweep expires it.
    set_clock("2026-08-05T00:00:01Z")
    assert get_consultation(consultation["id"])["status"] == "EXPIRED"
