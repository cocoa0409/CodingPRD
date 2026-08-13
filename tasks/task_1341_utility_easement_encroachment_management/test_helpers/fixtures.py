"""Composite setup helpers.

Encapsulates the multi-step setup sequences demanded by the PRD's derived-state
aggregate: cases must be walked INTAKE -> MAPPING -> ACTIVE_MONITORING with a
clean title search and a recorded document before encroachments, offers, or
permits can meaningfully be exercised. All helpers build preconditions from
scratch via PRD-declared endpoints and use the lenient setup validator so
failures surface as clear "Setup step failed" errors.

Setup ordering note: the case is moved to MAPPING before the first document is
recorded, because recording is permitted only while the case is in MAPPING,
ACTIVE_MONITORING, or RESOLUTION_PENDING (PRD section 3.2), and beginning
mapping requires at least one document on the case (PRD section 3.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    complete_title_search_payload,
    create_case_payload,
    create_document_payload,
    create_encroachment_payload,
    create_offer_payload,
    create_permit_payload,
    create_title_search_payload,
    create_vegetation_violation_payload,
    create_vegetation_zone_payload,
)
from .test_users import (
    DEPARTMENT_DIRECTOR,
    LITIGATION_COUNSEL,
    ROW_AGENT,
    ROW_AGENT_CREATOR,
    TITLE_EXAMINER,
    VEGETATION_INSPECTOR,
)


# ---------------------------------------------------------------------------
# Tier 1/2: case state progression and the recorded-document/title spine
# ---------------------------------------------------------------------------

def create_case(**overrides) -> dict:
    """Create an EasementCase (INTAKE). Returns the created case."""
    resp = api_client.create_case(create_case_payload(**overrides), ROW_AGENT)
    return get_success_data(resp)


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, ROW_AGENT))


def get_case_version(case_id) -> int:
    """Freshly read the case's current version for case-sensitive writes."""
    return int(get_case(case_id)["version"])


def add_document(case_id, **overrides) -> dict:
    """Create a DRAFT EasementDocument on the case."""
    resp = api_client.create_document(case_id, create_document_payload(**overrides), TITLE_EXAMINER)
    return get_success_data(resp)


def begin_mapping(case_id) -> dict:
    return get_success_data(api_client.begin_mapping(case_id, ROW_AGENT))


def create_case_in_mapping(**case_overrides):
    """Case with one DRAFT document, walked INTAKE -> MAPPING. Returns (case, doc)."""
    case = create_case(**case_overrides)
    doc = add_document(case["id"])
    begin_mapping(case["id"])
    return get_case(case["id"]), doc


def order_title_search(case_id, search_scope="FULL_CHAIN") -> dict:
    resp = api_client.create_title_search(
        case_id, create_title_search_payload(search_scope=search_scope), TITLE_EXAMINER
    )
    return get_success_data(resp)


def complete_title_search(case_id, task_id, liens_found=0, defects_found=0) -> dict:
    """Begin then complete a title search. Returns the completed task."""
    get_success_data(api_client.begin_title_search(case_id, task_id, TITLE_EXAMINER))
    resp = api_client.complete_title_search(
        case_id,
        task_id,
        complete_title_search_payload(liens_found=liens_found, defects_found=defects_found),
        TITLE_EXAMINER,
    )
    return get_success_data(resp)


def order_and_complete_clean_title_search(case_id) -> dict:
    task = order_title_search(case_id)
    return complete_title_search(case_id, task["id"], liens_found=0, defects_found=0)


def record_document(case_id, doc_id) -> dict:
    return get_success_data(api_client.record_document(case_id, doc_id, TITLE_EXAMINER))


def activate_monitoring(case_id) -> dict:
    return get_success_data(api_client.activate_monitoring(case_id, ROW_AGENT))


def create_active_case(**case_overrides):
    """Full road to monitoring: case + DRAFT doc -> MAPPING -> clean title
    search -> record doc -> ACTIVE_MONITORING. Returns (case, recorded_doc)."""
    case = create_case(**case_overrides)
    doc = add_document(case["id"])
    begin_mapping(case["id"])
    order_and_complete_clean_title_search(case["id"])
    record_document(case["id"], doc["id"])
    activate_monitoring(case["id"])
    return get_case(case["id"]), get_success_data(
        api_client.get_document(case["id"], doc["id"], TITLE_EXAMINER)
    )


# ---------------------------------------------------------------------------
# Tier 2/3: encroachments and the negotiation loop
# ---------------------------------------------------------------------------

def add_encroachment(case_id, document_id, **overrides) -> dict:
    """Report an encroachment (DISCOVERED) against a recorded document."""
    resp = api_client.create_encroachment(
        case_id, create_encroachment_payload(document_id, **overrides), ROW_AGENT
    )
    return get_success_data(resp)


def get_encroachment(case_id, enc_id) -> dict:
    return get_success_data(api_client.get_encroachment(case_id, enc_id, ROW_AGENT))


def notify_encroachment(case_id, enc_id) -> dict:
    """DISCOVERED -> NOTIFIED with a fresh expected_case_version (OCC write)."""
    version = get_case_version(case_id)
    resp = api_client.notify_encroachment(
        case_id, enc_id, {"expected_case_version": version}, ROW_AGENT
    )
    return get_success_data(resp)


def create_encroachment_negotiating(case_id, document_id, **overrides) -> dict:
    """Report -> notify -> begin-negotiation. Returns the NEGOTIATING encroachment."""
    enc = add_encroachment(case_id, document_id, **overrides)
    notify_encroachment(case_id, enc["id"])
    get_success_data(api_client.begin_encroachment_negotiation(case_id, enc["id"], ROW_AGENT))
    return get_encroachment(case_id, enc["id"])


def create_encroachment_removal_agreed(case_id, document_id, **overrides) -> dict:
    """Encroachment walked to REMOVAL_AGREED."""
    enc = create_encroachment_negotiating(case_id, document_id, **overrides)
    get_success_data(api_client.agree_encroachment_removal(case_id, enc["id"], ROW_AGENT))
    return get_encroachment(case_id, enc["id"])


def create_encroachment_removed(case_id, document_id, **overrides) -> dict:
    """Encroachment walked all the way to REMOVED (terminal)."""
    enc = create_encroachment_removal_agreed(case_id, document_id, **overrides)
    get_success_data(api_client.confirm_encroachment_removal(case_id, enc["id"], ROW_AGENT))
    return get_encroachment(case_id, enc["id"])


# ---------------------------------------------------------------------------
# Tier 2/3: acquisition offers
# ---------------------------------------------------------------------------

def add_offer(case_id, **overrides) -> dict:
    """Create a DRAFT offer. The creator is a dedicated RightOfWayAgent identity
    distinct from the agent used by tender_offer, so tender flows never trip the
    segregation-of-duties self-tender prohibition regardless of how
    requires_director_approval comes out."""
    resp = api_client.create_offer(case_id, create_offer_payload(**overrides), ROW_AGENT_CREATOR)
    return get_success_data(resp)


def get_offer(case_id, offer_id) -> dict:
    return get_success_data(api_client.get_offer(case_id, offer_id, ROW_AGENT))


def tender_offer(case_id, offer_id) -> dict:
    """DRAFT -> TENDERED with a fresh expected_case_version, tendered by an
    agent other than the offer's creator."""
    version = get_case_version(case_id)
    resp = api_client.tender_offer(
        case_id, offer_id, {"expected_case_version": version}, ROW_AGENT
    )
    return get_success_data(resp)


def counter_offer(case_id, offer_id, counter_amount_cents) -> dict:
    resp = api_client.counter_offer(
        case_id, offer_id, {"counter_amount_cents": counter_amount_cents}, ROW_AGENT
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: third-party permits
# ---------------------------------------------------------------------------

def add_permit(case_id, **overrides) -> dict:
    """Request a permit (approval PENDING, inspection NOT_SCHEDULED)."""
    resp = api_client.create_permit(case_id, create_permit_payload(**overrides), ROW_AGENT)
    return get_success_data(resp)


def get_permit(case_id, permit_id) -> dict:
    return get_success_data(api_client.get_permit(case_id, permit_id, ROW_AGENT))


def pass_permit_inspection(case_id, permit_id) -> dict:
    """Schedule then record a PASSED inspection."""
    get_success_data(api_client.schedule_permit_inspection(case_id, permit_id, VEGETATION_INSPECTOR))
    resp = api_client.record_permit_inspection(
        case_id, permit_id, {"result": "PASSED"}, VEGETATION_INSPECTOR
    )
    return get_success_data(resp)


def approve_permit(case_id, permit_id) -> dict:
    """PENDING -> APPROVED with a fresh expected_case_version (OCC write)."""
    version = get_case_version(case_id)
    resp = api_client.approve_permit(
        case_id, permit_id, {"expected_case_version": version}, ROW_AGENT
    )
    return get_success_data(resp)


def create_approved_permit(case_id, **overrides) -> dict:
    """Permit requested, inspection PASSED, then approved. Returns the permit."""
    permit = add_permit(case_id, **overrides)
    pass_permit_inspection(case_id, permit["id"])
    approve_permit(case_id, permit["id"])
    return get_permit(case_id, permit["id"])


# ---------------------------------------------------------------------------
# Tier 2: vegetation zones and violations
# ---------------------------------------------------------------------------

def add_vegetation_zone(case_id, **overrides) -> dict:
    resp = api_client.create_vegetation_zone(
        case_id, create_vegetation_zone_payload(**overrides), VEGETATION_INSPECTOR
    )
    return get_success_data(resp)


def get_vegetation_zone(case_id, zone_id) -> dict:
    return get_success_data(api_client.get_vegetation_zone(case_id, zone_id, VEGETATION_INSPECTOR))


def add_vegetation_violation(case_id, zone_id, **overrides) -> dict:
    resp = api_client.create_vegetation_violation(
        case_id, zone_id, create_vegetation_violation_payload(**overrides), VEGETATION_INSPECTOR
    )
    return get_success_data(resp)


def get_vegetation_violation(case_id, zone_id, viol_id) -> dict:
    items = get_success_data(
        api_client.list_vegetation_violations(case_id, zone_id, VEGETATION_INSPECTOR)
    )
    for item in items:
        if item["id"] == viol_id:
            return item
    raise AssertionError(f"Violation {viol_id} not found in zone {zone_id}")


def create_notified_violation(case_id, zone_id, **overrides) -> dict:
    """Violation recorded (DETECTED) then owner notified (NOTIFIED)."""
    viol = add_vegetation_violation(case_id, zone_id, **overrides)
    get_success_data(
        api_client.notify_vegetation_violation(case_id, zone_id, viol["id"], VEGETATION_INSPECTOR)
    )
    return get_vegetation_violation(case_id, zone_id, viol["id"])


# ---------------------------------------------------------------------------
# Tier 3: litigation referrals
# ---------------------------------------------------------------------------

def list_litigation_referrals(case_id) -> list:
    return get_success_data(api_client.list_litigation_referrals(case_id, LITIGATION_COUNSEL))


def only_referral(case_id) -> dict:
    """Fetch the single referral on the case (post-auto-create scenarios)."""
    referrals = list_litigation_referrals(case_id)
    assert len(referrals) == 1, f"Expected exactly one referral, got {len(referrals)}"
    return referrals[0]


def counsel_accept_file(case_id, ref_id) -> dict:
    """REFERRED -> ACCEPTED -> FILED by LitigationCounsel."""
    get_success_data(api_client.accept_litigation_referral(case_id, ref_id, LITIGATION_COUNSEL))
    return get_success_data(api_client.file_litigation_referral(case_id, ref_id, LITIGATION_COUNSEL))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_current_utc(to_iso8601, ROW_AGENT))
