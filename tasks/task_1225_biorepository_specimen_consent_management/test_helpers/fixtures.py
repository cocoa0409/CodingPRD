"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, and validates setup calls with the lenient
get_success_data so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_consent_record_payload,
    create_collection_kit_payload,
    create_deidentification_key_payload,
    create_key_access_grant_payload,
    create_sample_request_payload,
    create_sharing_agreement_payload,
    create_slot_reservation_payload,
    create_specimen_payload,
    create_storage_slot_payload,
    create_storage_unit_payload,
    create_temperature_reading_payload,
    create_vote_payload,
    _unique,
)
from .test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_lab_headers,
    make_reviewer_headers,
    make_researcher_headers,
    make_quality_officer_headers,
)

COORD_HEADERS = make_coordinator_headers("coord-setup")
LAB_HEADERS = make_lab_headers("lab-setup")
ADMIN_HEADERS = make_admin_headers("admin-setup")
QO_HEADERS = make_quality_officer_headers("qo-setup")

DEFAULT_REVIEWERS = ("rev-1", "rev-2", "rev-3")


def _setup_ok(response, what: str):
    data = get_success_data(response)
    assert isinstance(data, dict), f"Setup failed for {what}: {response.status_code} {response.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: basic entity hierarchy
# ---------------------------------------------------------------------------

def create_donor(donor_reference_code=None):
    """Register a donor. Returns the donor dict."""
    payload = {"donor_reference_code": donor_reference_code or _unique("D")}
    resp = api_client.create_donor(payload, COORD_HEADERS)
    return _setup_ok(resp, "donor")


def create_active_consent(donor_id, permitted_uses=None, **overrides):
    """File a consent record for the donor. Returns the consent dict."""
    if permitted_uses is not None:
        overrides["permitted_uses"] = permitted_uses
    payload = create_consent_record_payload(**overrides)
    resp = api_client.create_consent_record(donor_id, payload, COORD_HEADERS)
    return _setup_ok(resp, "consent record")


def create_donor_with_consent(permitted_uses=None, donor_reference_code=None, **consent_overrides):
    """Donor + ACTIVE consent. Returns (donor, consent)."""
    donor = create_donor(donor_reference_code)
    consent = create_active_consent(donor["id"], permitted_uses, **consent_overrides)
    return donor, consent


def create_in_stock_kit(kit_type="BLOOD", expires_at=None):
    """Register a kit into stock. Returns the kit dict."""
    overrides = {"kit_type": kit_type}
    if expires_at is not None:
        overrides["expires_at"] = expires_at
    payload = create_collection_kit_payload(**overrides)
    resp = api_client.create_collection_kit(payload, COORD_HEADERS)
    return _setup_ok(resp, "collection kit")


def create_distributed_kit(donor_id, kit_type="BLOOD", expires_at=None, coordinator_user="coord-setup"):
    """Kit distributed to the donor. Returns the kit dict."""
    kit = create_in_stock_kit(kit_type, expires_at)
    resp = api_client.distribute_kit(kit["id"], {"donor_id": donor_id},
                                     make_coordinator_headers(coordinator_user))
    return _setup_ok(resp, "kit distribute")


def create_returned_kit(donor_id, kit_type="BLOOD", expires_at=None, coordinator_user="coord-setup"):
    """Kit distributed to and returned from the donor. Returns the kit dict."""
    kit = create_distributed_kit(donor_id, kit_type, expires_at, coordinator_user)
    resp = api_client.receive_return_kit(kit["id"], {}, make_coordinator_headers(coordinator_user))
    return _setup_ok(resp, "kit receive-return")


def create_unit_with_slot(unit_code=None, setpoint_c=None, warn_threshold_c=None,
                          fail_threshold_c=None, slot_code="A1", capacity_ml=500):
    """Storage unit + one slot. Returns (unit, slot)."""
    unit_overrides = {}
    if setpoint_c is not None:
        unit_overrides["setpoint_c"] = setpoint_c
    if warn_threshold_c is not None:
        unit_overrides["warn_threshold_c"] = warn_threshold_c
    if fail_threshold_c is not None:
        unit_overrides["fail_threshold_c"] = fail_threshold_c
    unit_payload = create_storage_unit_payload(**unit_overrides)
    if unit_code is not None:
        unit_payload["unit_code"] = unit_code
    resp = api_client.create_storage_unit(unit_payload, ADMIN_HEADERS)
    unit = _setup_ok(resp, "storage unit")
    slot_payload = create_storage_slot_payload(slot_code=slot_code, capacity_ml=capacity_ml)
    resp = api_client.create_storage_slot(unit["id"], slot_payload, ADMIN_HEADERS)
    slot = _setup_ok(resp, "storage slot")
    return unit, slot


def accession_specimen(donor_id, kit_id, consent_record_id, specimen_type="BLOOD",
                       initial_volume_ml=100.0, collected_at=None, storage_slot_id=None):
    """Accession a specimen from a returned kit. Returns the specimen dict."""
    overrides = {}
    if collected_at is not None:
        overrides["collected_at"] = collected_at
    payload = create_specimen_payload(
        specimen_type=specimen_type, initial_volume_ml=initial_volume_ml, **overrides)
    payload.update({
        "donor_id": donor_id,
        "kit_id": kit_id,
        "consent_record_id": consent_record_id,
    })
    if storage_slot_id is not None:
        payload["storage_slot_id"] = storage_slot_id
    resp = api_client.create_specimen(payload, LAB_HEADERS)
    return _setup_ok(resp, "specimen accession")


def create_stored_specimen(donor_id, consent_id, slot_id, kit_type="BLOOD",
                           specimen_type="BLOOD", initial_volume_ml=100.0,
                           collected_at=None):
    """Returned kit + accession into the given slot (specimen starts IN_STORAGE).
    Returns (specimen, kit)."""
    kit = create_returned_kit(donor_id, kit_type=kit_type)
    specimen = accession_specimen(
        donor_id, kit["id"], consent_id, specimen_type=specimen_type,
        initial_volume_ml=initial_volume_ml, collected_at=collected_at,
        storage_slot_id=slot_id)
    return specimen, kit


def create_aliquot_for(specimen_id, initial_volume_ml, storage_slot_id=None, expected_version=None):
    """Create an aliquot, reading the specimen version when not supplied.
    Returns (aliquot, fresh_specimen)."""
    if expected_version is None:
        expected_version = _setup_ok(api_client.get_specimen(specimen_id, LAB_HEADERS),
                                     "specimen read")["version"]
    payload = {
        "initial_volume_ml": initial_volume_ml,
        "expected_specimen_version": expected_version,
    }
    if storage_slot_id is not None:
        payload["storage_slot_id"] = storage_slot_id
    resp = api_client.create_aliquot(specimen_id, payload, LAB_HEADERS)
    aliquot = _setup_ok(resp, "aliquot create")
    fresh = _setup_ok(api_client.get_specimen(specimen_id, LAB_HEADERS), "specimen re-read")
    return aliquot, fresh


def create_active_agreement(total_committed_volume_ml=1000.0, scope_uses=None, **overrides):
    """Agreement created and activated. Returns the agreement dict."""
    if scope_uses is not None:
        overrides["scope_uses"] = scope_uses
    payload = create_sharing_agreement_payload(
        total_committed_volume_ml=total_committed_volume_ml, **overrides)
    resp = api_client.create_sharing_agreement(payload, ADMIN_HEADERS)
    agreement = _setup_ok(resp, "sharing agreement")
    resp = api_client.activate_sharing_agreement(agreement["id"], {}, ADMIN_HEADERS)
    return _setup_ok(resp, "agreement activate")


# ---------------------------------------------------------------------------
# Tier 3: sample-request lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_request(agreement_id, researcher_id="researcher-1", **overrides):
    """Create a DRAFT sample request. Returns the request dict."""
    payload = create_sample_request_payload(sharing_agreement_id=agreement_id, **overrides)
    resp = api_client.create_sample_request(payload, make_researcher_headers(researcher_id))
    return _setup_ok(resp, "sample request")


def submit_request(request_id, researcher_id="researcher-1"):
    resp = api_client.submit_sample_request(request_id, {}, make_researcher_headers(researcher_id))
    return _setup_ok(resp, "request submit")


def cast_approve_vote(request_id, reviewer_id):
    resp = api_client.cast_vote(
        request_id,
        create_vote_payload(decision="APPROVE", rationale=f"committee approval rationale from {reviewer_id}"),
        make_reviewer_headers(reviewer_id),
    )
    return _setup_ok(resp, "approve vote")


def cast_reject_vote(request_id, reviewer_id):
    resp = api_client.cast_vote(
        request_id,
        create_vote_payload(decision="REJECT", rationale=f"committee rejection rationale from {reviewer_id}"),
        make_reviewer_headers(reviewer_id),
    )
    return _setup_ok(resp, "reject vote")


def create_under_review_request(agreement_id, researcher_id="researcher-1", **overrides):
    """Create + submit a request. Returns the UNDER_REVIEW request dict."""
    request = create_draft_request(agreement_id, researcher_id, **overrides)
    submit_request(request["id"], researcher_id)
    return _setup_ok(api_client.get_sample_request(request["id"], ADMIN_HEADERS),
                     "request re-read")


def create_approved_request(agreement_id, researcher_id="researcher-1",
                            reviewers=DEFAULT_REVIEWERS, **overrides):
    """Create + submit + 3 APPROVE votes (quorum). Returns the APPROVED request dict."""
    request = create_under_review_request(agreement_id, researcher_id, **overrides)
    for reviewer_id in reviewers:
        cast_approve_vote(request["id"], reviewer_id)
    return _setup_ok(api_client.get_sample_request(request["id"], ADMIN_HEADERS),
                     "approved request re-read")


# ---------------------------------------------------------------------------
# Tier 4: full fulfillment chain
# ---------------------------------------------------------------------------

def setup_reserved_aliquot(volume_needed_ml=40.0, aliquot_volume_ml=40.0,
                           specimen_volume_ml=100.0, agreement_total_ml=1000.0,
                           specimen_collected_at=None, researcher_id="researcher-1",
                           unit_overrides=None):
    """Full chain through fulfillment reservation:
    donor/consent/kit/unit/slot -> specimen IN_STORAGE with one aliquot ->
    ACTIVE agreement -> APPROVED request -> fulfill.

    Returns a dict with keys: donor, consent, kit, unit, slot, specimen,
    aliquot, agreement, request.
    """
    unit_kwargs = unit_overrides or {}
    donor, consent = create_donor_with_consent()
    unit, slot = create_unit_with_slot(**unit_kwargs)
    specimen, kit = create_stored_specimen(
        donor["id"], consent["id"], slot["id"],
        specimen_type="BLOOD", initial_volume_ml=specimen_volume_ml,
        collected_at=specimen_collected_at)
    aliquot, _ = create_aliquot_for(specimen["id"], aliquot_volume_ml,
                                    storage_slot_id=slot["id"])
    agreement = create_active_agreement(total_committed_volume_ml=agreement_total_ml)
    request = create_approved_request(
        agreement["id"], researcher_id,
        specimen_type="BLOOD", volume_needed_ml=volume_needed_ml)
    resp = api_client.fulfill_sample_request(request["id"], {}, ADMIN_HEADERS)
    _setup_ok(resp, "fulfill")
    aliquot = _setup_ok(api_client.get_aliquot(aliquot["id"], LAB_HEADERS), "aliquot re-read")
    agreement = _setup_ok(api_client.get_sharing_agreement(agreement["id"], ADMIN_HEADERS),
                          "agreement re-read")
    request = _setup_ok(api_client.get_sample_request(request["id"], ADMIN_HEADERS),
                        "request re-read")
    specimen = _setup_ok(api_client.get_specimen(specimen["id"], LAB_HEADERS), "specimen re-read")
    return {
        "donor": donor, "consent": consent, "kit": kit, "unit": unit, "slot": slot,
        "specimen": specimen, "aliquot": aliquot, "agreement": agreement, "request": request,
        "researcher_id": researcher_id,
    }


def checkout_reserved_aliquot(aliquot_id, request_id):
    """Checkout a RESERVED aliquot. Returns the aliquot dict."""
    resp = api_client.checkout_aliquot(aliquot_id, {"request_id": request_id}, LAB_HEADERS)
    return _setup_ok(resp, "checkout")


# ---------------------------------------------------------------------------
# Tier 5: consent withdrawal & destruction
# ---------------------------------------------------------------------------

def withdraw_consent_and_finalize(consent_id, deadline_iso="2026-05-04T00:00:00Z"):
    """Withdraw the consent at the default clock, advance to the grace deadline,
    run the sweep. Returns the sweep response data."""
    resp = api_client.withdraw_consent(consent_id, {}, COORD_HEADERS)
    _setup_ok(resp, "withdraw")
    resp = api_client.set_clock({"to_iso8601": deadline_iso}, ADMIN_HEADERS)
    _setup_ok(resp, "set clock")
    resp = api_client.run_sweep({}, ADMIN_HEADERS)
    return _setup_ok(resp, "sweep")


def create_pending_destruction_order(specimen_id, reason="QUALITY_FAILURE", creator="qo-setup"):
    """Manually create a destruction order. Returns the order dict."""
    resp = api_client.create_destruction_order(
        {"specimen_id": specimen_id, "reason": reason},
        make_quality_officer_headers(creator),
    )
    return _setup_ok(resp, "destruction order")


# ---------------------------------------------------------------------------
# De-identification keys & grants
# ---------------------------------------------------------------------------

def create_key_for_specimen(specimen_id):
    resp = api_client.create_deidentification_key(
        create_deidentification_key_payload(specimen_id=specimen_id), COORD_HEADERS)
    return _setup_ok(resp, "de-identification key")


def create_grant_for_key(key_id, **overrides):
    resp = api_client.create_key_access_grant(
        key_id, create_key_access_grant_payload(**overrides), COORD_HEADERS)
    return _setup_ok(resp, "key access grant")


# ---------------------------------------------------------------------------
# Misc composite helpers
# ---------------------------------------------------------------------------

def ingest_reading(unit_id, recorded_at, temp_c):
    resp = api_client.create_temperature_reading(
        unit_id, create_temperature_reading_payload(recorded_at=recorded_at, temp_c=temp_c),
        LAB_HEADERS)
    return _setup_ok(resp, "temperature reading")


def book_reservation(slot_id, starts_at, ends_at, purpose="MAINTENANCE"):
    resp = api_client.create_slot_reservation(
        slot_id,
        create_slot_reservation_payload(starts_at=starts_at, ends_at=ends_at, purpose=purpose),
        LAB_HEADERS)
    return _setup_ok(resp, "slot reservation")


def set_clock_to(iso_timestamp):
    resp = api_client.set_clock({"to_iso8601": iso_timestamp}, ADMIN_HEADERS)
    return _setup_ok(resp, "set clock")


def run_sweep():
    resp = api_client.run_sweep({}, ADMIN_HEADERS)
    return _setup_ok(resp, "sweep")


def get_specimen(specimen_id):
    return _setup_ok(api_client.get_specimen(specimen_id, LAB_HEADERS), "specimen get")


def get_aliquot(aliquot_id):
    return _setup_ok(api_client.get_aliquot(aliquot_id, LAB_HEADERS), "aliquot get")


def get_agreement(agreement_id):
    return _setup_ok(api_client.get_sharing_agreement(agreement_id, ADMIN_HEADERS),
                     "agreement get")


def get_request(request_id):
    return _setup_ok(api_client.get_sample_request(request_id, ADMIN_HEADERS), "request get")


def get_consent(consent_id):
    return _setup_ok(api_client.get_consent_record(consent_id, COORD_HEADERS), "consent get")


def get_unit(unit_id):
    return _setup_ok(api_client.get_storage_unit(unit_id, ADMIN_HEADERS), "unit get")


def get_slot(slot_id):
    return _setup_ok(api_client.get_storage_slot(slot_id, ADMIN_HEADERS), "slot get")


def get_kit(kit_id):
    return _setup_ok(api_client.get_collection_kit(kit_id, COORD_HEADERS), "kit get")


def get_destruction_order(order_id):
    return _setup_ok(api_client.get_destruction_order(order_id, ADMIN_HEADERS), "order get")


def get_key(key_id):
    return _setup_ok(api_client.get_deidentification_key(key_id, COORD_HEADERS), "key get")
