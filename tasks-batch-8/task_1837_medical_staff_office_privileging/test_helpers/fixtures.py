"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. The dominant chain is the approval pipeline of
PRD §3.1-§3.4: criteria -> member -> application -> verification item ->
delineation -> submit -> receive/verify -> evaluate -> advance -> vote ->
MEC endorse -> board ratify, which leaves the member ACTIVE with a
PROVISIONAL grant.

OCC threading (PRD §2.7): application creation carries expected_member_version
and delineation creation carries expected_application_version. Because derived
counts/versions move as the file is built (PRD §2.4), every guarded create
re-reads the parent's version immediately before posting, so helpers work no
matter which intermediate reconciliations bumped the parent version.

Identity threading: DepartmentChief and Practitioner calls are entity-backed
by MedicalStaffMember, so ownership-gated calls use make_*_headers with the
real member id — never the shared fallback constants.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    DEFAULT_SPECIALTY,
    REVIEW_PERIOD_END,
    REVIEW_PERIOD_START,
)
from .factories import (
    create_adverse_action_case_payload,
    create_agenda_item_payload,
    create_application_payload,
    create_delineation_payload,
    create_expirable_credential_payload,
    create_hearing_panel_payload,
    create_member_payload,
    create_npdb_report_payload,
    create_performance_metric_payload,
    create_performance_review_payload,
    create_specialty_criteria_payload,
    create_temporary_privilege_payload,
    create_verification_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_board_member_headers,
    make_department_chief_headers,
    make_practitioner_headers,
)

COORD = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]
MEC = TEST_USERS["mec_chair_headers"]
BOARD = TEST_USERS["board_member_headers"]
HEARING = TEST_USERS["hearing_officer_headers"]


# ---------------------------------------------------------------------------
# Timestamp helpers (tests compare instants, not string formats)
# ---------------------------------------------------------------------------

def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(value: datetime, days: int) -> datetime:
    return value + timedelta(days=days)


# ---------------------------------------------------------------------------
# Tier 0: clock and single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_STARTUP_DEFAULT):
    """Advance the logical clock (coordinator-only, PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


def create_criteria(**overrides):
    """Create a SpecialtyCriteria row. Defaults to EMED/EMED-GEN."""
    return get_success_data(
        api_client.create_specialty_criteria(
            create_specialty_criteria_payload(**overrides), COORD),
        201)


def create_member_record(full_name="Dr. Test", npdb_subject_id="NPDB-T",
                         primary_specialty_code="EMED"):
    """Create a member record (born APPLICANT / posture NONE)."""
    return get_success_data(
        api_client.create_member(
            create_member_payload(full_name, npdb_subject_id,
                                  primary_specialty_code), COORD),
        201)


def refresh_member(member_id):
    return get_success_data(api_client.get_member(member_id, COORD))


def refresh_application(application_id):
    return get_success_data(api_client.get_application(application_id, COORD))


def refresh_verification_item(item_id):
    return get_success_data(api_client.get_verification_item(item_id, COORD))


def refresh_delineation(delineation_id):
    return get_success_data(api_client.get_delineation(delineation_id, COORD))


def refresh_grant(grant_id):
    return get_success_data(api_client.get_privilege_grant(grant_id, COORD))


def refresh_review(review_id):
    return get_success_data(api_client.get_performance_review(review_id, COORD))


def refresh_credential(credential_id):
    return get_success_data(api_client.get_expirable_credential(credential_id, COORD))


def refresh_temp(temp_id):
    return get_success_data(api_client.get_temporary_privilege(temp_id, COORD))


def refresh_case(case_id):
    return get_success_data(api_client.get_adverse_action_case(case_id, COORD))


def refresh_agenda_item(item_id):
    return get_success_data(api_client.get_agenda_item(item_id, COORD))


def refresh_npdb_report(report_id):
    return get_success_data(api_client.get_npdb_report(report_id, COORD))


# ---------------------------------------------------------------------------
# Tier 1: application pipeline steps
# ---------------------------------------------------------------------------

def create_draft_application(member, application_kind="INITIAL",
                             supersedes_application_id=None):
    """Create an application, threading the member's CURRENT version (OCC)."""
    fresh = refresh_member(member["id"])
    payload = create_application_payload(
        fresh["id"], fresh["version"],
        application_kind=application_kind,
        supersedes_application_id=supersedes_application_id)
    return get_success_data(api_client.create_application(payload, COORD), 201)


def add_verification_item(application_id, item_kind="WORK_HISTORY",
                          is_primary_source=False):
    return get_success_data(
        api_client.create_verification_item(
            create_verification_item_payload(application_id, item_kind,
                                             is_primary_source), COORD),
        201)


def add_delineation(application_id, privilege_line="EMED-GEN",
                    documented_training_months=24, documented_cases_24mo=100):
    """Create a delineation, threading the application's CURRENT version (OCC)."""
    fresh = refresh_application(application_id)
    payload = create_delineation_payload(
        application_id, fresh["version"],
        privilege_line=privilege_line,
        documented_training_months=documented_training_months,
        documented_cases_24mo=documented_cases_24mo)
    return get_success_data(api_client.create_delineation(payload, COORD), 201)


def submit_application(application_id):
    return get_success_data(api_client.submit_application(application_id, COORD))


def receive_item(item_id):
    return get_success_data(
        api_client.mark_verification_item_received(item_id, COORD))


def verify_item(item_id):
    return get_success_data(api_client.verify_verification_item(item_id, COORD))


def receive_and_verify_item(item_id):
    """REQUESTED -> RECEIVED -> VERIFIED."""
    receive_item(item_id)
    return verify_item(item_id)


def evaluate_delineation_ok(delineation_id):
    return get_success_data(api_client.evaluate_delineation(delineation_id, COORD))


def advance_to_committee(application_id):
    return get_success_data(
        api_client.advance_application_to_committee(application_id, CHAIR))


def get_agenda_item_for_application(application_id):
    """The APPLICATION_APPROVAL agenda item auto-created at advancement."""
    data, meta = validate_paginated(
        api_client.list_agenda_items(
            COORD, params={"ref_application_id": application_id}))
    assert len(data) >= 1, (
        f"Expected an agenda item referencing application {application_id}")
    return data[0]


def committee_approve_item(item_id, votes_for=3, votes_against=0):
    return get_success_data(
        api_client.committee_vote_agenda_item(item_id, votes_for,
                                              votes_against, CHAIR))


def mec_endorse_item(item_id, voter_id="mec-voter-1"):
    return get_success_data(
        api_client.mec_endorse_agenda_item(item_id, voter_id, MEC))


def board_ratify_item(item_id, headers=None):
    return get_success_data(
        api_client.board_ratify_agenda_item(item_id, headers or BOARD))


def board_decline_item(item_id, headers=None):
    return get_success_data(
        api_client.board_decline_agenda_item(item_id, headers or BOARD))


# ---------------------------------------------------------------------------
# Tier 2: application pipeline composites
# ---------------------------------------------------------------------------

def create_submitted_application(full_name="Dr. Sub", npdb_subject_id="NPDB-SUB",
                                 criteria_overrides=None,
                                 item_kind="WORK_HISTORY",
                                 is_primary_source=False,
                                 with_delineation=True,
                                 delineation_overrides=None,
                                 credentials=None):
    """Criteria + member + application + one verification item (+ delineation),
    submitted. Application is in SUBMITTED or PSV_IN_PROGRESS. Returns a
    workspace dict."""
    ws = {}
    ws["criteria"] = create_criteria(**(criteria_overrides or {}))
    ws["member"] = create_member_record(full_name, npdb_subject_id,
                                        ws["criteria"]["specialty_code"])
    for cred in (credentials or []):
        add_credential(ws["member"]["id"], **cred)
    ws["application"] = create_draft_application(ws["member"])
    ws["item"] = add_verification_item(ws["application"]["id"], item_kind,
                                       is_primary_source)
    if with_delineation:
        ws["delineation"] = add_delineation(
            ws["application"]["id"],
            **(delineation_overrides or {}))
    else:
        ws["delineation"] = None
    ws["application"] = submit_application(ws["application"]["id"])
    return ws


def create_psv_complete_application(full_name="Dr. Sub",
                                    npdb_subject_id="NPDB-SUB", **kwargs):
    """create_submitted_application + the item verified; the application has
    reached PSV_COMPLETE (single item) and any delineation is still as left."""
    ws = create_submitted_application(full_name, npdb_subject_id, **kwargs)
    ws["item"] = receive_and_verify_item(ws["item"]["id"])
    ws["application"] = refresh_application(ws["application"]["id"])
    return ws


def create_committee_review_application(full_name="Dr. Sub",
                                        npdb_subject_id="NPDB-SUB",
                                        evaluate=True, **kwargs):
    """Application advanced to COMMITTEE_REVIEW with its agenda item."""
    ws = create_psv_complete_application(full_name, npdb_subject_id, **kwargs)
    if evaluate and ws["delineation"] is not None:
        ws["delineation"] = evaluate_delineation_ok(ws["delineation"]["id"])
    ws["application"] = advance_to_committee(ws["application"]["id"])
    ws["agenda_item"] = get_agenda_item_for_application(ws["application"]["id"])
    return ws


def create_approved_member(full_name="Dr. Appr", npdb_subject_id="NPDB-APPR",
                           voter_id="mec-voter-1", **kwargs):
    """Full pipeline through board ratification: member ACTIVE, delineation
    GRANTED, one PROVISIONAL PrivilegeGrant. Returns a workspace dict."""
    ws = create_committee_review_application(full_name, npdb_subject_id,
                                             **kwargs)
    ws["agenda_item"] = committee_approve_item(ws["agenda_item"]["id"])
    ws["agenda_item"] = mec_endorse_item(ws["agenda_item"]["id"], voter_id)
    ws["agenda_item"] = board_ratify_item(ws["agenda_item"]["id"])
    ws["application"] = refresh_application(ws["application"]["id"])
    ws["delineation"] = (
        refresh_delineation(ws["delineation"]["id"])
        if ws["delineation"] is not None else None)
    ws["member"] = refresh_member(ws["member"]["id"])
    grants, _meta = validate_paginated(
        api_client.list_privilege_grants(
            COORD, params={"member_id": ws["member"]["id"]}))
    ws["grant"] = grants[0] if grants else None
    return ws


# ---------------------------------------------------------------------------
# Tier 3: performance reviews and the FPPE maturation flip
# ---------------------------------------------------------------------------

def open_review(member_id, grant_id, review_kind="FPPE",
                period_start=REVIEW_PERIOD_START, period_end=REVIEW_PERIOD_END):
    return get_success_data(
        api_client.create_performance_review(
            create_performance_review_payload(
                member_id, grant_id, review_kind, period_start, period_end),
            COORD),
        201)


def add_metric(review_id, metric_domain="CLINICAL_QUALITY", raw_value=1.0,
               domain_weight=1.0, collected_at="2026-09-05T00:00:00Z",
               passed_fppe_case=None):
    payload = create_performance_metric_payload(
        review_id, metric_domain, raw_value, domain_weight, collected_at,
        passed_fppe_case)
    return get_success_data(
        api_client.create_performance_metric(payload, COORD), 201)


def review_to_provisional(review_id):
    """COLLECTING -> EVALUATION -> PROVISIONAL_RESULT."""
    get_success_data(api_client.close_review_collection(review_id, COORD))
    return get_success_data(api_client.compute_review_provisional(review_id, COORD))


def review_to_final(review_id):
    """... -> FINAL_RESULT via the committee chair."""
    return get_success_data(api_client.finalize_performance_review(review_id, CHAIR))


def flip_grant_active_via_fppe(ws, collected_at="2026-08-10T00:00:00Z",
                               period_start="2026-08-02T00:00:00Z",
                               period_end="2026-09-01T00:00:00Z"):
    """Run an FPPE review with one passed proctored case so the grant's
    fppe_cases_completed reaches the criteria's fppe_case_count (default 1)
    and the grant flips PROVISIONAL -> ACTIVE (PRD §3.5). Returns the review."""
    review = open_review(ws["member"]["id"], ws["grant"]["id"], "FPPE",
                         period_start, period_end)
    add_metric(review["id"], "CLINICAL_QUALITY", 1.0, 1.0, collected_at,
               passed_fppe_case=True)
    review_to_provisional(review["id"])
    finalized = review_to_final(review["id"])
    ws["review"] = finalized
    ws["grant"] = refresh_grant(ws["grant"]["id"])
    ws["member"] = refresh_member(ws["member"]["id"])
    return finalized


def create_member_with_active_grant(full_name="Dr. Act",
                                    npdb_subject_id="NPDB-ACT", **kwargs):
    """Approved member whose single grant has matured PROVISIONAL -> ACTIVE
    via FPPE completion (criteria fppe_case_count must be 1)."""
    ws = create_approved_member(full_name, npdb_subject_id, **kwargs)
    flip_grant_active_via_fppe(ws)
    return ws


# ---------------------------------------------------------------------------
# Tier 4: credentials, temp privileges, NPDB
# ---------------------------------------------------------------------------

def add_credential(member_id, credential_kind="STATE_LICENSE",
                   credential_number="CRED-1", issued_on="2026-01-01T00:00:00Z",
                   expires_on="2027-08-01T00:00:00Z"):
    return get_success_data(
        api_client.create_expirable_credential(
            create_expirable_credential_payload(
                member_id, credential_kind, credential_number, issued_on,
                expires_on),
            COORD),
        201)


def create_temp_privilege(member_id, sponsor_member_id, temp_kind="TEMPORARY",
                          privilege_line="EMED-GEN",
                          window_start="2026-09-01T00:00:00Z",
                          window_end="2026-09-15T00:00:00Z",
                          disaster_declaration_ref=None):
    return get_success_data(
        api_client.create_temporary_privilege(
            create_temporary_privilege_payload(
                member_id, sponsor_member_id, temp_kind, privilege_line,
                window_start, window_end, disaster_declaration_ref),
            COORD),
        201)


def activate_temp_privilege(temp_id):
    return get_success_data(api_client.activate_temporary_privilege(temp_id, CHAIR))


def file_npdb_report(member_id, report_kind="QUERY_INITIAL", case_id=None):
    return get_success_data(
        api_client.create_npdb_report(
            create_npdb_report_payload(member_id, report_kind, case_id), COORD),
        201)


# ---------------------------------------------------------------------------
# Tier 5: adverse action / fair hearing pipeline
# ---------------------------------------------------------------------------

def create_proposed_case(subject_id, proposer_id, case_kind="SUSPENSION",
                         restriction_days=None, linked_review_id=None):
    """Propose a case as the proposer chief (entity-backed identity)."""
    payload = create_adverse_action_case_payload(
        subject_id, proposer_id, case_kind, restriction_days, linked_review_id)
    return get_success_data(
        api_client.create_adverse_action_case(
            payload, make_department_chief_headers(proposer_id)),
        201)


def create_endorsed_case(subject_id, proposer_id, case_kind="SUSPENSION",
                         restriction_days=None, linked_review_id=None):
    """PROPOSED -> MEC_ENDORSED (subject must be ACTIVE)."""
    case = create_proposed_case(subject_id, proposer_id, case_kind,
                                restriction_days, linked_review_id)
    return get_success_data(
        api_client.endorse_adverse_action_case(case["id"], MEC))


def request_hearing_for_case(case_id, subject_id):
    """MEC_ENDORSED -> HEARING_REQUESTED by the subject practitioner."""
    return get_success_data(
        api_client.request_hearing(case_id, make_practitioner_headers(subject_id)))


def seat_panelists(case_id, count=3, name_prefix="Panelist"):
    """Create `count` fresh member records and seat them on the case.
    Returns the list of HearingPanel rows."""
    panels = []
    for i in range(count):
        panelist = create_member_record(
            f"{name_prefix} {i + 1}", f"NPDB-{name_prefix.upper()}-{i + 1}",
            "EMED")
        role = "CHAIR" if i == 0 else "MEMBER"
        panels.append(get_success_data(
            api_client.create_hearing_panel(
                create_hearing_panel_payload(case_id, panelist["id"], role),
                HEARING),
            201))
    return panels


def create_hearing_held_case(subject_id, proposer_id, case_kind="SUSPENSION",
                             restriction_days=None, linked_review_id=None):
    """Full hearing pipeline: PROPOSED -> MEC_ENDORSED -> HEARING_REQUESTED
    -> (3 panelists seated) -> HEARING_HELD. Returns (case, panels)."""
    case = create_endorsed_case(subject_id, proposer_id, case_kind,
                                restriction_days, linked_review_id)
    case = request_hearing_for_case(case["id"], subject_id)
    panels = seat_panelists(case["id"], 3)
    case = get_success_data(api_client.hold_hearing(case["id"], HEARING))
    return case, panels


# ---------------------------------------------------------------------------
# Convenience: full adverse-action scenario on a freshly approved member
# ---------------------------------------------------------------------------

def create_active_member_with_case(case_kind="SUSPENSION", restriction_days=None,
                                   member_name="Dr. Subject",
                                   member_npdb="NPDB-SUBJ",
                                   chief_name="Dr. Chief",
                                   chief_npdb="NPDB-CHIEF"):
    """Approved (ACTIVE) member plus a proposed case from a second member
    record acting as department chief. Returns (ws, case, chief)."""
    ws = create_approved_member(member_name, member_npdb)
    chief = create_member_record(chief_name, chief_npdb, "EMED")
    case = create_proposed_case(ws["member"]["id"], chief["id"], case_kind,
                                restriction_days)
    return ws, case, chief


def agenda_item_for_case(case_id):
    """Manually created ADVERSE_ACTION agenda item referencing the case."""
    return get_success_data(
        api_client.create_agenda_item(
            create_agenda_item_payload("ADVERSE_ACTION", ref_case_id=case_id),
            CHAIR),
        201)
