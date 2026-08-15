"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its 2026-08-01T00:00:00Z default). Setup
calls use get_success_data so failures surface as clear "Setup failed"
errors. Actor-recording calls (proposal create/approve, ticket claim/QC,
researcher-owned calls) take explicit user ids so segregation-of-duties and
ownership tests can control identities.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    catalog_item_payload,
    create_accession_payload,
    create_appointment_payload,
    create_assessment_payload,
    create_collection_payload,
    create_finding_aid_payload,
    create_item_payload,
    create_oral_history_payload,
    create_project_payload,
    create_proposal_payload,
    create_reproduction_order_payload,
    create_request_payload,
    create_researcher_payload,
    create_storage_zone_payload,
    create_ticket_payload,
    zone_reading_payload,
)
from .test_users import (
    TEST_USERS,
    make_board_officer_headers,
    make_registrar_headers,
    make_researcher_headers,
    make_volunteer_headers,
)

REG = TEST_USERS["registrar_headers"]
ARCH = TEST_USERS["archivist_headers"]
RRS = TEST_USERS["reading_room_staff_headers"]
COORD = TEST_USERS["volunteer_coordinator_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, SYSADMIN)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 1 — zones, collections, accessions, deeds
# ---------------------------------------------------------------------------

def create_zone(zone_code="Z1", name="Vault A", **thresholds):
    """Create a storage zone (born OPEN, streak 0). Returns the zone dict."""
    resp = api_client.create_storage_zone(
        create_storage_zone_payload(
            zone_code=zone_code, name=name, **thresholds),
        REG,
    )
    return _ok("create_storage_zone", resp)


def create_collection(zone_id, collection_code="C1", title="Papers",
                      parent_collection_id=None):
    payload = create_collection_payload(
        title=title, collection_code=collection_code,
        storage_zone_id=zone_id)
    if parent_collection_id is not None:
        payload["parent_collection_id"] = parent_collection_id
    resp = api_client.create_collection(payload, REG)
    return _ok("create_collection", resp)


def get_collection(collection_id):
    return _ok("get_collection",
               api_client.get_collection(collection_id, REG))


def get_zone(zone_id):
    return _ok("get_zone", api_client.get_storage_zone(zone_id, REG))


def create_accession(**overrides):
    resp = api_client.create_accession(create_accession_payload(**overrides),
                                       REG)
    return _ok("create_accession", resp)


def get_accession(accession_id):
    return _ok("get_accession", api_client.get_accession(accession_id, REG))


def submit_accession(accession_id):
    return _ok("submit_accession",
               api_client.submit_accession(accession_id, REG))


def create_deed(accession_id, **deed_fields):
    resp = api_client.create_deed(accession_id, deed_fields, REG)
    return _ok("create_deed", resp)


def execute_deed(deed_id, expected_accession_version):
    resp = api_client.execute_deed(
        deed_id, {"expected_accession_version": expected_accession_version},
        REG)
    return _ok("execute_deed", resp)


def create_accessioned(deed_fields=None, **accession_overrides):
    """Create an accession and drive it to ACCESSIONED with one EXECUTED deed.

    Returns (accession_after_execute, deed). The accession's version is read
    fresh immediately before the OCC-checked execute.
    """
    accession = create_accession(**accession_overrides)
    submit_accession(accession["id"])
    deed = create_deed(accession["id"], **(deed_fields or {}))
    current = get_accession(accession["id"])
    execute_deed(deed["id"], current["version"])
    return get_accession(accession["id"]), deed


# ---------------------------------------------------------------------------
# Tier 1 — finding aids, items, assessments
# ---------------------------------------------------------------------------

def create_published_finding_aid(collection_id, **overrides):
    """Create a finding aid and walk it DRAFT -> IN_REVIEW -> PUBLISHED."""
    resp = api_client.create_finding_aid(
        create_finding_aid_payload(collection_id=collection_id, **overrides),
        ARCH)
    aid = _ok("create_finding_aid", resp)
    _ok("submit_finding_aid_review",
        api_client.submit_finding_aid_review(aid["id"], ARCH))
    _ok("publish_finding_aid", api_client.publish_finding_aid(aid["id"], ARCH))
    return _ok("get_finding_aid", api_client.get_finding_aid(aid["id"], ARCH))


def create_item(accession_id, collection_id, title="I1"):
    resp = api_client.create_item(
        create_item_payload(accession_id=accession_id,
                            collection_id=collection_id, title=title),
        ARCH)
    return _ok("create_item", resp)


def get_item(item_id):
    return _ok("get_item", api_client.get_item(item_id, ARCH))


def catalog_item(item_id, **overrides):
    resp = api_client.catalog_item(item_id, catalog_item_payload(**overrides),
                                   ARCH)
    return _ok("catalog_item", resp)


def make_item_available(item_id):
    return _ok("make_item_available",
               api_client.make_item_available(item_id, ARCH))


def setup_available_item(title="I1", condition_grade="GOOD",
                         appraised_value_cents=100, item_format="MAP",
                         deed_fields=None, zone_code="Z1",
                         collection_code="C1", **accession_overrides):
    """Full chain: zone + collection + ACCESSIONED accession (EXECUTED deed)
    + PUBLISHED finding aid + item cataloged and AVAILABLE.

    Returns a dict with keys: zone, collection, accession, deed, finding_aid,
    item.
    """
    zone = create_zone(zone_code=zone_code)
    collection = create_collection(zone["id"], collection_code=collection_code)
    accession, deed = create_accessioned(deed_fields=deed_fields,
                                         **accession_overrides)
    finding_aid = create_published_finding_aid(collection["id"])
    item = create_item(accession["id"], collection["id"], title=title)
    catalog_item(item["id"], condition_grade=condition_grade,
                 appraised_value_cents=appraised_value_cents,
                 format=item_format)
    item = make_item_available(item["id"])
    return {
        "zone": zone,
        "collection": collection,
        "accession": accession,
        "deed": deed,
        "finding_aid": finding_aid,
        "item": item,
    }


def create_assessment(item_id, **overrides):
    """Create a conservation assessment with a fresh OCC version read.

    Returns the created assessment dict.
    """
    item = get_item(item_id)
    payload = create_assessment_payload(
        expected_item_version=item["version"], **overrides)
    resp = api_client.create_conservation_assessment(item_id, payload, ARCH)
    return _ok("create_conservation_assessment", resp)


def get_assessment_list(item_id):
    return _ok("list_conservation_assessments",
               api_client.list_conservation_assessments(item_id, ARCH))


def setup_approved_assessment(item_id, **overrides):
    """Create + approve an assessment. Returns the APPROVED assessment."""
    assessment = create_assessment(item_id, **overrides)
    resp = api_client.approve_assessment(assessment["id"], ARCH)
    return _ok("approve_assessment", resp)


def setup_in_treatment_item(**item_overrides):
    """Item driven AVAILABLE -> (assessment APPROVED) -> FLAGGED_CONSERVATION
    -> IN_TREATMENT. Returns the setup dict plus 'assessment'."""
    ctx = setup_available_item(condition_grade="POOR",
                               appraised_value_cents=100,
                               **item_overrides)
    assessment = setup_approved_assessment(
        ctx["item"]["id"], condition_grade_observed="POOR", urgency_score=50,
        treatment_estimate_hours=3)
    _ok("flag_item_conservation",
        api_client.flag_item_conservation(ctx["item"]["id"], ARCH))
    _ok("begin_treatment", api_client.begin_treatment(assessment["id"], ARCH))
    ctx["assessment"] = assessment
    return ctx


# ---------------------------------------------------------------------------
# Tier 1 — researchers, requests, appointments
# ---------------------------------------------------------------------------

def register_researcher(full_name="R. Reader", email="r1@example.org"):
    resp = api_client.create_researcher(
        create_researcher_payload(full_name=full_name, email=email), RRS)
    return _ok("create_researcher", resp)


def get_researcher(researcher_id):
    return _ok("get_researcher", api_client.get_researcher(researcher_id, RRS))


def create_request(researcher_id, item_ids, topic="t", purpose="PERSONAL"):
    """Create a research request as the owning researcher (entity-backed)."""
    headers = make_researcher_headers(researcher_id)
    resp = api_client.create_research_request(
        create_request_payload(item_ids=list(item_ids), topic=topic,
                               purpose=purpose),
        headers)
    return _ok("create_research_request", resp)


def approve_request(request_id):
    _ok("begin_request_review", api_client.begin_request_review(request_id, RRS))
    return _ok("approve_request", api_client.approve_request(request_id, RRS))


def setup_approved_request(item_ids, purpose="PERSONAL", topic="t",
                           researcher_email="r1@example.org"):
    """Register a researcher, create + approve a request over item_ids.
    Returns (researcher, request)."""
    researcher = register_researcher(email=researcher_email)
    request = create_request(researcher["id"], item_ids, topic=topic,
                             purpose=purpose)
    request = approve_request(request["id"])
    return researcher, request


def create_appointment(request_id, researcher_id, room_code="MAIN",
                       scheduled_date="2026-08-10", start_time="10:00",
                       end_time="12:00", seats=None):
    payload = create_appointment_payload(
        research_request_id=request_id, room_code=room_code,
        scheduled_date=scheduled_date, start_time=start_time,
        end_time=end_time)
    if seats is not None:
        payload["seats"] = seats
    resp = api_client.create_appointment(
        payload, make_researcher_headers(researcher_id))
    return _ok("create_appointment", resp)


def get_appointment(appointment_id):
    return _ok("get_appointment",
               api_client.get_appointment(appointment_id, RRS))


def setup_confirmed_appointment(item_id, room_code="MAIN",
                                scheduled_date="2026-08-10",
                                start_time="10:00", end_time="12:00",
                                seats=None, purpose="PERSONAL"):
    """Researcher + APPROVED request over [item_id] + CONFIRMED appointment.
    Returns (researcher, request, appointment)."""
    researcher, request = setup_approved_request([item_id], purpose=purpose)
    appointment = create_appointment(
        request["id"], researcher["id"], room_code=room_code,
        scheduled_date=scheduled_date, start_time=start_time,
        end_time=end_time, seats=seats)
    return researcher, request, appointment


def record_no_show_at(appointment_id, clock_iso):
    """Move the logical clock and record a no-show (slot must have ended)."""
    set_clock(clock_iso)
    resp = api_client.record_no_show(appointment_id, RRS)
    return _ok("record_no_show", resp)


# ---------------------------------------------------------------------------
# Tier 1 — reproduction orders
# ---------------------------------------------------------------------------

def create_order(request_id, researcher_id, item_ids,
                 format="SCAN_STANDARD", page_estimate=60,
                 license_class="PERSONAL", rush=False):
    resp = api_client.create_reproduction_order(
        create_reproduction_order_payload(
            research_request_id=request_id, item_ids=list(item_ids),
            format=format, page_estimate=page_estimate,
            license_class=license_class, rush=rush),
        make_researcher_headers(researcher_id))
    return _ok("create_reproduction_order", resp)


def get_order(order_id):
    return _ok("get_order", api_client.get_reproduction_order(order_id, RRS))


def approve_order_quote(order_id, researcher_id):
    return _ok("approve_quote",
               api_client.approve_quote(
                   order_id, make_researcher_headers(researcher_id)))


def invoice_order(order_id, actual_pages):
    return _ok("invoice_order",
               api_client.invoice_order(order_id, {"actual_pages": actual_pages},
                                        RRS))


def pay_order(order_id, researcher_id, amount_cents):
    return _ok("pay_order",
               api_client.pay_order(order_id, {"amount_cents": amount_cents},
                                    make_researcher_headers(researcher_id)))


# ---------------------------------------------------------------------------
# Tier 1 — volunteer projects and tickets
# ---------------------------------------------------------------------------

def create_project(name="P1", **overrides):
    resp = api_client.create_volunteer_project(
        create_project_payload(name=name, **overrides), COORD)
    return _ok("create_volunteer_project", resp)


def activate_project(project_id):
    return _ok("activate_project", api_client.activate_project(project_id, COORD))


def create_active_project(name="P1", **overrides):
    project = create_project(name, **overrides)
    return activate_project(project["id"])


def get_project(project_id):
    return _ok("get_project", api_client.get_volunteer_project(project_id, COORD))


def create_ticket(project_id, item_id):
    resp = api_client.create_ticket(project_id, create_ticket_payload(
        item_id=item_id), COORD)
    return _ok("create_ticket", resp)


def get_ticket(ticket_id):
    return _ok("get_ticket", api_client.get_ticket(ticket_id, COORD))


def claim_next(project_id, volunteer_id="vol_1"):
    resp = api_client.claim_next_ticket(project_id,
                                        make_volunteer_headers(volunteer_id))
    return _ok("claim_next", resp)


def setup_project_with_ticket(item_id, project_name="P1", **project_overrides):
    """ACTIVE project + one QUEUED ticket on item_id. Returns (project, ticket)."""
    project = create_active_project(project_name, **project_overrides)
    ticket = create_ticket(project["id"], item_id)
    return project, ticket


def setup_claimed_ticket(item_id, volunteer_id="vol_1", **project_overrides):
    """ACTIVE project + ticket CLAIMED by volunteer_id. Returns (project, ticket)."""
    project, ticket = setup_project_with_ticket(item_id, **project_overrides)
    claimed = claim_next(project["id"], volunteer_id)
    assert claimed["id"] == ticket["id"], (
        f"claim-next picked {claimed['id']}, expected {ticket['id']}")
    return project, claimed


def setup_qc_review_ticket(item_id, volunteer_id="vol_1", **project_overrides):
    """Ticket driven CLAIMED -> IN_CAPTURE -> QC_REVIEW."""
    project, ticket = setup_claimed_ticket(item_id, volunteer_id,
                                           **project_overrides)
    vol_headers = make_volunteer_headers(volunteer_id)
    _ok("begin_capture", api_client.begin_capture(ticket["id"], vol_headers))
    _ok("submit_qc", api_client.submit_qc(ticket["id"], vol_headers))
    return project, get_ticket(ticket["id"])


# ---------------------------------------------------------------------------
# Tier 1 — environmental readings
# ---------------------------------------------------------------------------

def post_reading(zone_id, recorded_at, temperature_c, humidity_pct=50.0):
    resp = api_client.post_zone_reading(
        zone_id,
        zone_reading_payload(recorded_at=recorded_at,
                             temperature_c=temperature_c,
                             humidity_pct=humidity_pct),
        SYSADMIN)
    return _ok("post_reading", resp)


def post_breach_run(zone_id, count, start_hour=1, temperature_c=25.0,
                    date="2026-08-01"):
    """Post `count` consecutive breach readings (temp 25.0 > default high 24.0).
    Returns the final zone dict."""
    zone = None
    for k in range(count):
        zone = post_reading(zone_id, f"{date}T{start_hour + k:02d}:00:00Z",
                            temperature_c)
    return zone


def post_clean_run(zone_id, count, start_hour, temperature_c=20.0,
                   humidity_pct=50.0, date="2026-08-01"):
    """Post `count` consecutive in-range readings. Returns the final zone dict."""
    zone = None
    for k in range(count):
        zone = post_reading(zone_id, f"{date}T{start_hour + k:02d}:00:00Z",
                            temperature_c, humidity_pct)
    return zone


# ---------------------------------------------------------------------------
# Tier 1 — deaccession proposals
# ---------------------------------------------------------------------------

def create_proposal(item_ids, disposal_method="TRANSFER",
                    justification="Duplicates", proposer_id="reg_1"):
    resp = api_client.create_deaccession_proposal(
        create_proposal_payload(item_ids=list(item_ids),
                                justification=justification,
                                disposal_method=disposal_method),
        make_registrar_headers(proposer_id))
    return _ok("create_deaccession_proposal", resp)


def get_proposal(proposal_id):
    return _ok("get_proposal",
               api_client.get_deaccession_proposal(proposal_id, REG))


def proposal_to_board_review(proposal_id, proposer_id="reg_1"):
    headers = make_registrar_headers(proposer_id)
    _ok("submit_proposal", api_client.submit_proposal(proposal_id, headers))
    return _ok("send_proposal_to_board",
               api_client.send_proposal_to_board(proposal_id, headers))


def approve_proposal(proposal_id, officer_id="board_1"):
    resp = api_client.approve_proposal(
        proposal_id, make_board_officer_headers(officer_id))
    return _ok("approve_proposal", resp)


def setup_approved_proposal(item_ids, disposal_method="TRANSFER",
                            proposer_id="reg_1", officer_id="board_1",
                            justification="Duplicates"):
    """Proposal driven DRAFT -> SUBMITTED -> BOARD_REVIEW -> APPROVED."""
    proposal = create_proposal(item_ids, disposal_method=disposal_method,
                               justification=justification,
                               proposer_id=proposer_id)
    proposal_to_board_review(proposal["id"], proposer_id)
    return approve_proposal(proposal["id"], officer_id)


def setup_cooled_off_proposal(item_ids, disposal_method="TRANSFER",
                              proposer_id="reg_1", officer_id="board_1",
                              justification="Duplicates",
                              sweep_to="2026-08-31T00:00:00Z"):
    """APPROVED proposal swept to COOLED_OFF by advancing the clock exactly
    to finalize_not_before (approved at the 2026-08-01 default + 30 days)."""
    proposal = setup_approved_proposal(item_ids, disposal_method=disposal_method,
                                       proposer_id=proposer_id,
                                       officer_id=officer_id,
                                       justification=justification)
    set_clock(sweep_to)
    return get_proposal(proposal["id"])


# ---------------------------------------------------------------------------
# Tier 1 — oral histories
# ---------------------------------------------------------------------------

def create_oral_history(collection_id, **overrides):
    resp = api_client.create_oral_history(
        create_oral_history_payload(collection_id=collection_id, **overrides),
        ARCH)
    return _ok("create_oral_history", resp)


def get_oral_history(recording_id):
    return _ok("get_oral_history", api_client.get_oral_history(recording_id, ARCH))


def walk_recording_to_review(recording_id):
    """SCHEDULED -> RECORDED -> TRANSCRIBED -> IN_REVIEW."""
    _ok("mark_recorded", api_client.mark_recorded(recording_id, ARCH))
    _ok("submit_transcript", api_client.submit_transcript(recording_id, ARCH))
    return _ok("send_recording_to_review",
               api_client.send_recording_to_review(recording_id, ARCH))
