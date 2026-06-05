"""UNOS reporting, role-based access control, validation-priority ordering, and
the exact-deadline acceptance boundary.

Translates difficulty instances ppvc_owner_before_state_on_accept and
bpc_offer_accept_at_exact_deadline, plus corner instances for report
reject / removal-subject-invalid, unauthenticated / unauthorized / non-owner
access control.
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_center, create_opo, create_candidate,
    create_listed_candidate, create_organ, run_match, issue_offer,
    setup_matching_organ_with_offer,
    create_candidate_payload, create_unos_report_payload, reject_unos_report_payload,
    remove_candidate_payload, decline_offer_payload, accept_offer_payload,
    create_match_run_payload,
    make_admin_headers, make_center_headers, make_opo_headers,
)


# ─── UNOS reporting ────────────────────────────────────────────────────

def test_reject_report_sets_rejection_reason(api):
    """PRD §3.10: "Alternatively a UNOSAdmin rejects a report, moving it from
    SUBMITTED to REJECTED and recording the supplied rejection_reason (free text)."

    Design: Corner/state_machines/corner_unos_report_reject_sets_reason
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    center_headers = make_center_headers(center["id"])
    cand = create_listed_candidate(center, mrn="U1", date_of_birth="1980-01-01T00:00:00Z")
    validate_success(api.remove_candidate(
        cand["id"], remove_candidate_payload("DECEASED"), center_headers), 200)
    report = validate_success(api.create_unos_report(
        create_unos_report_payload("REMOVAL", candidate_id=cand["id"]), center_headers), 201)
    rejected = validate_success(api.reject_unos_report(
        report["id"], reject_unos_report_payload("incomplete documentation"),
        make_admin_headers()), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "incomplete documentation"


def test_removal_report_for_listed_candidate_rejected(api):
    """PRD §3.10: "a REMOVAL report requires a candidate_id whose candidate is in
    REMOVED listing status; a report whose subject is missing or whose removal
    candidate is not actually removed is rejected with ERR_REPORT_SUBJECT_INVALID."

    Design: Corner/validations/corner_unos_report_removal_subject_not_removed
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    center_headers = make_center_headers(center["id"])
    cand = create_listed_candidate(center, mrn="RP1", date_of_birth="1980-01-01T00:00:00Z")
    # Candidate is LISTED, not REMOVED.
    res = api.create_unos_report(
        create_unos_report_payload("REMOVAL", candidate_id=cand["id"]), center_headers)
    validate_error(res, "ERR_REPORT_SUBJECT_INVALID")


# ─── Access control ────────────────────────────────────────────────────

def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a value that is not
    a recognized role, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/corner_unauthenticated_missing_headers
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    payload = create_candidate_payload(center["id"], mrn="NA1",
                                       date_of_birth="1980-01-01T00:00:00Z")
    # No auth headers at all.
    res = api.create_candidate(payload, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_opo_cannot_create_candidate(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/corner_opo_cannot_create_candidate_unauthorized
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center()
    opo = create_opo(opo_code="OPO5", region_code=5)
    payload = create_candidate_payload(center["id"], mrn="UZ1",
                                       date_of_birth="1980-01-01T00:00:00Z")
    res = api.create_candidate(payload, make_opo_headers(opo["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_center_cannot_run_match(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/corner_center_cannot_run_match_unauthorized
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85)
    res = api.create_match_run(
        create_match_run_payload(organ["id"], organ["version"], "STANDARD"),
        make_center_headers(center["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_non_owner_center_cannot_deactivate(api):
    """PRD §2.1: "a candidate's center_id must equal X-User-ID for the acting center
    to mutate that candidate ... A center attempting to mutate a candidate, offer,
    transplant, or follow-up that it does not own is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/corner_non_owner_center_cannot_deactivate
    """
    set_clock("2026-06-01T00:00:00Z")
    c5 = create_center(unos_center_code="C005", region_code=5)
    c9 = create_center(unos_center_code="C009", region_code=5,
                       latitude=41.0, longitude=-87.0)
    cand = create_candidate(c5, mrn="OW1", date_of_birth="1980-01-01T00:00:00Z")
    # C9 attempts to deactivate C5's candidate.
    res = api.deactivate_candidate(cand["id"], make_center_headers(c9["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── Validation-priority ordering (P4 owner before P7 state) ───────────

def test_non_owner_accept_of_declined_offer_returns_owner_error(api):
    """PRD §2.8: "4. Resource ownership — the acting transplant center owns the
    candidate, offer, transplant, or follow-up being mutated ... else
    ERR_NOT_RESOURCE_OWNER." PRD §2.8: "7. State — the target resource is in a
    state from which the requested transition is defined, else ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_owner_before_state_on_accept
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="Y1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85))
    c5_headers = make_center_headers(scenario["center"]["id"])
    # The owning center C5 declines the offer (now DECLINED → would be a state error).
    validate_success(api.decline_offer(
        scenario["offer"]["id"], decline_offer_payload("CENTER_DECLINE"), c5_headers), 200)
    # A different center C9 (non-owner) attempts to accept.
    c9 = create_center(unos_center_code="C009", region_code=5,
                       latitude=41.0, longitude=-87.0)
    res = api.accept_offer(scenario["offer"]["id"],
                           accept_offer_payload(scenario["organ"]["version"]),
                           make_center_headers(c9["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── Exact-deadline acceptance boundary ────────────────────────────────

def test_accept_at_exact_deadline_succeeds(api):
    """PRD §3.8: "The response window must still be open: the current clock instant
    must be at or before response_deadline_at ... acceptance is valid exactly at
    the deadline, while expiry requires strictly after it." PRD §3.7: "first the
    response window, which is offered_at plus one hour."

    Design: Difficulty/boundary_precision_check/bpc_offer_accept_at_exact_deadline
    """
    set_clock("2026-06-01T00:00:00Z")
    center = create_center(unos_center_code="C005", region_code=5)
    opo = create_opo(opo_code="OPO5", region_code=5)
    cand = create_listed_candidate(center, mrn="B1", blood_type="A",
                                   date_of_birth="1975-01-01T00:00:00Z",
                                   height_cm=178, weight_kg=80)
    organ = create_organ(opo, blood_type="O", donor_weight_kg=85,
                         recovered_at="2026-06-01T00:00:00Z", max_cold_ischemia_hours=10)
    match_run, organ = run_match(opo, organ, "STANDARD")
    offer, organ = issue_offer(opo, organ, cand, match_run)
    assert offer["response_deadline_at"][:19] == "2026-06-01T01:00:00"
    # Advance the clock to exactly the deadline.
    set_clock("2026-06-01T01:00:00Z")
    center_headers = make_center_headers(center["id"])
    accepted = validate_success(api.accept_offer(
        offer["id"], accept_offer_payload(organ["version"]), center_headers), 200)
    assert accepted["status"] == "ACCEPTED"
