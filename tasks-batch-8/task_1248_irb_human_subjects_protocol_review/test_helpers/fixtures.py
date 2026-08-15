"""Composite setup helpers.

Multi-step scenario builders so tests can focus on assertions. All helpers
hit the live API through the module-level api_client and use the lenient
get_success_data() validator so that a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Identity threading: after creating an Investigator or IrbMember, every
ownership-gated call passes make_pi_headers(entity["id"]) /
make_reviewer_headers(entity["id"]) / make_chair_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_adverse_event_payload,
    create_board_meeting_payload,
    create_case_payload,
    create_conflict_declaration_payload,
    create_consent_document_payload,
    create_investigator_payload,
    create_member_payload,
    create_modification_payload,
    create_protocol_payload,
    create_reliance_agreement_payload,
    unique_email,
)
from .test_users import (
    TEST_USERS,
    make_chair_headers,
    make_pi_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def register_investigator(training_expires_at="2027-01-01T00:00:00Z", **overrides):
    """Register an investigator (IrbAdmin). Returns the Investigator."""
    payload = create_investigator_payload(
        training_expires_at=training_expires_at, **overrides
    )
    resp = api_client.create_investigator(payload, ADMIN)
    return get_success_data(resp)


def register_member(member_category="SCIENTIST", is_chair=False, **overrides):
    """Register an IRB member (IrbAdmin). Returns the IrbMember."""
    payload = create_member_payload(**overrides)
    payload["member_category"] = member_category
    if is_chair:
        payload["is_chair"] = True
    resp = api_client.create_member(payload, ADMIN)
    return get_success_data(resp)


def register_chair(**overrides):
    """Register an ACTIVE SCIENTIST member with is_chair true."""
    overrides.setdefault("member_category", "SCIENTIST")
    return register_member(is_chair=True, **overrides)


# ---------------------------------------------------------------------------
# Protocol drafting / submission / determination
# ---------------------------------------------------------------------------

def create_draft_protocol(investigator_id, **overrides):
    """Create a DRAFT protocol owned by the given investigator."""
    resp = api_client.create_protocol(
        create_protocol_payload(**overrides), make_pi_headers(investigator_id)
    )
    return get_success_data(resp)


def upload_consent(protocol_id, investigator_id, **overrides):
    """Upload a consent document version (owner PI). Returns the document."""
    resp = api_client.upload_consent_document(
        protocol_id, create_consent_document_payload(**overrides),
        make_pi_headers(investigator_id),
    )
    return get_success_data(resp)


def approve_consent_document(consent_document_id, chair_id):
    resp = api_client.review_consent_document(
        consent_document_id, {"outcome": "APPROVE"}, make_chair_headers(chair_id)
    )
    return get_success_data(resp)


def submit_protocol_ok(protocol_id, investigator_id):
    resp = api_client.submit_protocol(protocol_id, make_pi_headers(investigator_id))
    return get_success_data(resp)


def record_determination_ok(protocol_id, determined_review_level):
    resp = api_client.record_determination(
        protocol_id, {"determined_review_level": determined_review_level}, COORDINATOR
    )
    return get_success_data(resp)


def get_protocol(protocol_id):
    return get_success_data(api_client.get_protocol(protocol_id, COORDINATOR))


# ---------------------------------------------------------------------------
# Reviewer assignments
# ---------------------------------------------------------------------------

def offer_assignment(protocol_id, reviewer_id=None, reviewer_role="PRIMARY"):
    payload = {}
    if reviewer_id is not None:
        payload["reviewer_id"] = reviewer_id
    if reviewer_role is not None:
        payload["reviewer_role"] = reviewer_role
    resp = api_client.create_review_assignment(protocol_id, payload, COORDINATOR)
    return get_success_data(resp)


def respond_to_assignment(assignment_id, reviewer_id, response):
    resp = api_client.respond_to_assignment(
        assignment_id, {"response": response}, make_reviewer_headers(reviewer_id)
    )
    return get_success_data(resp)


def file_recommendation(assignment_id, reviewer_id, recommendation="APPROVE"):
    resp = api_client.submit_recommendation(
        assignment_id, {"recommendation": recommendation},
        make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Composite lifecycle scenarios
# ---------------------------------------------------------------------------

def drive_to_under_expedited_review(protocol_id, investigator_id):
    """submit + coordinator determination EXPEDITED. Returns the protocol."""
    submit_protocol_ok(protocol_id, investigator_id)
    return record_determination_ok(protocol_id, "EXPEDITED")


def drive_to_awaiting_full_board(protocol_id, investigator_id):
    """submit + coordinator determination FULL_BOARD. Returns the protocol."""
    submit_protocol_ok(protocol_id, investigator_id)
    return record_determination_ok(protocol_id, "FULL_BOARD")


def approve_via_expedited(protocol_id, chair_id, reviewer_ids,
                          recommendation="APPROVE"):
    """Offer/accept/recommend for each reviewer, then chair APPROVE.

    Requires the protocol to be UNDER_EXPEDITED_REVIEW. Returns the list of
    SUBMITTED assignments.
    """
    assignments = []
    for idx, reviewer_id in enumerate(reviewer_ids):
        role = "PRIMARY" if idx == 0 else "SECONDARY"
        asg = offer_assignment(protocol_id, reviewer_id=reviewer_id, reviewer_role=role)
        respond_to_assignment(asg["id"], reviewer_id, "ACCEPT")
        assignments.append(
            file_recommendation(asg["id"], reviewer_id, recommendation)
        )
    resp = api_client.expedited_determination(
        protocol_id, {"outcome": "APPROVE"}, make_chair_headers(chair_id)
    )
    validate_success(resp)
    return assignments


def setup_approved_protocol(risk_level="MINIMAL", is_industry_sponsored=False,
                            claimed_review_level="EXPEDITED",
                            training_expires_at="2027-01-01T00:00:00Z",
                            title="Approved Study"):
    """Full expedited-track approval from an empty database.

    Investigator + chair + two reviewers; protocol with an APPROVED consent
    document, submitted, determined EXPEDITED, two APPROVE recommendations,
    chair approval. Returns a dict of all artifacts, including the first
    continuing-review cycle.
    """
    inv = register_investigator(training_expires_at=training_expires_at)
    chair = register_chair(email=unique_email("chair"))
    rev1 = register_member("SCIENTIST", email=unique_email("rev"))
    rev2 = register_member("NON_SCIENTIST", email=unique_email("rev"))
    proto = create_draft_protocol(
        inv["id"], title=title, claimed_review_level=claimed_review_level,
        risk_level=risk_level, is_industry_sponsored=is_industry_sponsored,
    )
    cd = upload_consent(proto["id"], inv["id"])
    approve_consent_document(cd["id"], chair["id"])
    drive_to_under_expedited_review(proto["id"], inv["id"])
    assignments = approve_via_expedited(
        proto["id"], chair["id"], [rev1["id"], rev2["id"]]
    )
    from prd_bench_local_runner.testing import validate_paginated
    cr_rows, _ = validate_paginated(
        api_client.list_continuing_reviews(proto["id"], COORDINATOR)
    )
    return {
        "investigator": inv,
        "chair": chair,
        "reviewers": (rev1, rev2),
        "protocol": get_success_data(api_client.get_protocol(proto["id"], COORDINATOR)),
        "consent_document": cd,
        "assignments": tuple(assignments),
        "continuing_reviews": cr_rows,
    }


def setup_awaiting_full_board_scenario(involves_prisoners=False,
                                       risk_level="GREATER_THAN_MINIMAL",
                                       approve_consent=True,
                                       chair=None):
    """Protocol driven to AWAITING_FULL_BOARD with (by default) an APPROVED
    consent document. Returns investigator/chair/protocol/consent.

    Pass an existing chair entity via ``chair`` when the test already
    registered its roster — registering a second chair would inflate the
    ACTIVE-member count and shift the §3.6 quorum threshold.
    """
    inv = register_investigator()
    if chair is None:
        chair = register_chair(email=unique_email("chair"))
    proto = create_draft_protocol(
        inv["id"], claimed_review_level="FULL_BOARD", risk_level=risk_level,
        involves_prisoners=involves_prisoners,
    )
    cd = upload_consent(proto["id"], inv["id"])
    if approve_consent:
        approve_consent_document(cd["id"], chair["id"])
    drive_to_awaiting_full_board(proto["id"], inv["id"])
    return {
        "investigator": inv,
        "chair": chair,
        "protocol": get_success_data(api_client.get_protocol(proto["id"], COORDINATOR)),
        "consent_document": cd,
    }


def register_quorum_members():
    """Five ACTIVE members covering every category (chair SCIENTIST + SCIENTIST
    + NON_SCIENTIST + UNAFFILIATED + PRISONER_REPRESENTATIVE), so the quorum
    threshold is floor(5/2)+1 == 3 (PRD §3.6)."""
    chair = register_chair(email=unique_email("chair"))
    sci = register_member("SCIENTIST", email=unique_email("sci"))
    nonsci = register_member("NON_SCIENTIST", email=unique_email("nonsci"))
    unaff = register_member("UNAFFILIATED", email=unique_email("unaff"))
    pris = register_member("PRISONER_REPRESENTATIVE", email=unique_email("pris"))
    return {"chair": chair, "sci": sci, "nonsci": nonsci, "unaff": unaff, "pris": pris}


# ---------------------------------------------------------------------------
# Board meetings
# ---------------------------------------------------------------------------

def schedule_meeting(room_id="R-TEST", scheduled_at="2026-06-01T10:00:00Z",
                     duration_minutes=60):
    resp = api_client.create_board_meeting(
        create_board_meeting_payload(
            room_id=room_id, scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
        ),
        COORDINATOR,
    )
    return get_success_data(resp)


def add_agenda_item_ok(meeting_id, protocol_id, expected_meeting_version,
                       modification_id=None):
    payload = {
        "protocol_id": protocol_id,
        "expected_meeting_version": expected_meeting_version,
    }
    if modification_id is not None:
        payload["modification_id"] = modification_id
    resp = api_client.add_agenda_item(meeting_id, payload, COORDINATOR)
    return get_success_data(resp)


def convene_meeting_ok(meeting_id, chair_id, attendee_member_ids):
    resp = api_client.convene_meeting(
        meeting_id, {"attendee_member_ids": attendee_member_ids},
        make_chair_headers(chair_id),
    )
    return get_success_data(resp)


def get_meeting(meeting_id):
    return get_success_data(api_client.get_board_meeting(meeting_id, COORDINATOR))


def get_agenda_item(agenda_item_id):
    return get_success_data(api_client.get_agenda_item(agenda_item_id, COORDINATOR))


# ---------------------------------------------------------------------------
# Non-compliance cases / suspension
# ---------------------------------------------------------------------------

def open_manual_case(protocol_id, reason="manual case"):
    resp = api_client.create_non_compliance_case(
        protocol_id, create_case_payload(reason=reason), OFFICER
    )
    return get_success_data(resp)


def investigate_case(case_id):
    return get_success_data(api_client.open_investigation(case_id, OFFICER))


def issue_finding_ok(case_id, finding):
    return get_success_data(
        api_client.issue_finding(case_id, {"finding": finding}, OFFICER)
    )


def close_case_ok(case_id, closure_note=None):
    payload = {}
    if closure_note is not None:
        payload["closure_note"] = closure_note
    return get_success_data(api_client.close_case(case_id, payload, OFFICER))


def suspend_protocol_via_confirmed_finding(protocol_id, reason="audit finding"):
    """Open a MANUAL case, investigate, issue CONFIRMED — suspends an
    APPROVED/EXEMPT_ACTIVE protocol (PRD §3.8). Returns the case."""
    case = open_manual_case(protocol_id, reason=reason)
    investigate_case(case["id"])
    return issue_finding_ok(case["id"], "CONFIRMED")


# ---------------------------------------------------------------------------
# Reliance agreements
# ---------------------------------------------------------------------------

def create_reliance(protocol_id, ceding_institution_code="INST_A",
                    effective_start_date="2026-06-01T00:00:00Z",
                    effective_end_date="2026-12-31T00:00:00Z"):
    resp = api_client.create_reliance_agreement(
        create_reliance_agreement_payload(
            protocol_id,
            ceding_institution_code=ceding_institution_code,
            effective_start_date=effective_start_date,
            effective_end_date=effective_end_date,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def execute_reliance_ok(reliance_id):
    return get_success_data(api_client.execute_reliance_agreement(reliance_id, ADMIN))


def get_reliance(reliance_id):
    return get_success_data(api_client.get_reliance_agreement(reliance_id, ADMIN))


# ---------------------------------------------------------------------------
# Modifications / continuing reviews / adverse events
# ---------------------------------------------------------------------------

def create_modification_ok(protocol_id, investigator_id, expected_protocol_version,
                           **overrides):
    resp = api_client.create_modification(
        protocol_id,
        create_modification_payload(expected_protocol_version, **overrides),
        make_pi_headers(investigator_id),
    )
    return get_success_data(resp)


def submit_continuing_review_ok(cr_id, investigator_id):
    return get_success_data(
        api_client.submit_continuing_review(cr_id, make_pi_headers(investigator_id))
    )


def adjudicate_continuing_review_ok(cr_id, chair_id, outcome):
    return get_success_data(
        api_client.adjudicate_continuing_review(
            cr_id, {"outcome": outcome}, make_chair_headers(chair_id)
        )
    )


def file_adverse_event_ok(protocol_id, investigator_id, **overrides):
    resp = api_client.file_adverse_event(
        protocol_id, create_adverse_event_payload(**overrides),
        make_pi_headers(investigator_id),
    )
    return get_success_data(resp)


def declare_conflict(protocol_id, reviewer_id, declaration_type="FINANCIAL",
                     detail="test conflict"):
    resp = api_client.create_conflict_declaration(
        protocol_id,
        create_conflict_declaration_payload(
            declaration_type=declaration_type, detail=detail
        ),
        make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def adjudicate_declaration(declaration_id, chair_id, outcome):
    return get_success_data(
        api_client.adjudicate_conflict_declaration(
            declaration_id, {"outcome": outcome}, make_chair_headers(chair_id)
        )
    )


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )
