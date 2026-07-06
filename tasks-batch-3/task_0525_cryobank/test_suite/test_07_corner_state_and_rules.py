"""Breadth coverage: state transitions, business validations, action
endpoints, regulatory-report snapshot, and optimistic concurrency control."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_recipient_headers,
    create_under_review_application,
    setup_listed_inventory,
    setup_listed_inventory_with_consented_recipient,
    setup_preparing_shipment, setup_shipped_reservation,
    defer_donor_via_second_application, place_hold, confirm_one_family,
)

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["catalog_manager_headers"]


# ---------------------------------------------------------------------------
# state_machines
# ---------------------------------------------------------------------------
def test_approve_from_submitted_without_review_returns_invalid_state(api):
    """PRD §2.6: "An action is only accepted when the target entity's status
    currently sits in a state from which the requested transition is defined;
    otherwise the request is rejected with ERR_INVALID_STATE." PRD §3.1: "Approval
    advances it UNDER_REVIEW -> APPROVED: this requires that the application be in
    UNDER_REVIEW".

    Design: Corner/state_machines/approve_from_submitted_without_review_returns_invalid_state
    """
    donor = validate_success(api.create_donor({
        "display_code": "D-C5", "full_name": "Corner Five", "donor_type": "SPERM",
        "blood_type": "O_POS", "family_limit": 5}, SO), expected_status=201)
    app = validate_success(api.create_screening_application({
        "donor_id": donor["id"], "fda_risk_flag": False,
        "genetic_carrier_count": 0, "partner_screening_required": False,
    }, SO), expected_status=201)
    resp = api.approve_application(app["id"], SO)  # still SUBMITTED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    donor_after = validate_success(api.get_donor(donor["id"], SO))
    assert donor_after["status"] == "APPLICANT"


def test_deliver_from_preparing_returns_invalid_state(api):
    """PRD §3.6: "Delivery is a LabTech action advancing the shipment DISPATCHED ->
    DELIVERED, requiring only that the shipment be DISPATCHED".

    Design: Corner/state_machines/deliver_from_preparing_returns_invalid_state
    """
    ctx = setup_preparing_shipment(display_code="D-C6", dewar_code="T-C6", vial_count=1)
    resp = api.deliver_shipment(ctx["shipment_id"], LT)  # still PREPARING
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    ship = validate_success(api.get_shipment(ctx["shipment_id"], LT))
    assert ship["status"] == "PREPARING"


def test_consent_revoke_blocked_by_active_reservation(api):
    """PRD §3.3: "Revocation requires that the consent be SIGNED and that the same
    recipient-and-donor pairing has no vial reservation in HELD, CONFIRMED, or
    SHIPPED; if such an active reservation exists, the revocation is blocked with
    ERR_ACTIVE_RESERVATION_EXISTS."

    Design: Corner/state_machines/consent_revoke_blocked_by_active_reservation
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-C7", dewar_code="T-C7", initial_vial_count=5)
    place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 1,
               ctx["inventory_version"])
    resp = api.revoke_consent(ctx["consent_id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_ACTIVE_RESERVATION_EXISTS.value)
    consent = validate_success(api.get_recipient_consent(ctx["consent_id"], ctx["headers"]))
    assert consent["status"] == "SIGNED"


def test_consent_sign_without_acknowledgement_returns_error(api):
    """PRD §3.3: "A sign attempt where acknowledges_open_id is false is rejected with
    ERR_CONSENT_NOT_ACKNOWLEDGED."

    Design: Corner/state_machines/consent_sign_without_acknowledgement_returns_error
    """
    donor_id, app_id = create_under_review_application(display_code="D-C8")
    validate_success(api.approve_application(app_id, SO))
    recipient = validate_success(api.create_recipient({
        "family_name": "F C8", "contact_email": "c8@x.com"}, CM), expected_status=201)
    rcp_headers = make_recipient_headers(recipient["id"])
    consent = validate_success(api.create_recipient_consent({
        "recipient_id": recipient["id"], "donor_id": donor_id,
        "acknowledges_open_id": False,
    }, rcp_headers), expected_status=201)
    resp = api.sign_consent(consent["id"], rcp_headers)
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACKNOWLEDGED.value)
    consent_after = validate_success(api.get_recipient_consent(consent["id"], rcp_headers))
    assert consent_after["status"] == "DRAFT"


def test_terminal_deferred_application_cannot_restart_review(api):
    """PRD §3.1: "Deferral advances the application UNDER_REVIEW -> DEFERRED, a
    terminal outcome". PRD §2.6: "An action is only accepted when the target entity's
    status currently sits in a state from which the requested transition is defined;
    otherwise the request is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_deferred_application_cannot_restart_review
    """
    donor_id, app_id = create_under_review_application(display_code="D-C9")
    validate_success(api.defer_application(app_id, SO))
    resp = api.start_review(app_id, SO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    app = validate_success(api.get_screening_application(app_id, SO))
    assert app["status"] == "DEFERRED"


def test_release_quarantine_before_date_returns_temporal_error(api):
    """PRD §3.2: "a release attempt before the quarantine window has elapsed — the
    current UTC instant still earlier than quarantine_release_date — is rejected with
    ERR_QUARANTINE_NOT_ELAPSED."

    retest_negative=true and clock before the date so only the temporal check fails,
    isolating ERR_QUARANTINE_NOT_ELAPSED.

    Design: Corner/state_machines/release_quarantine_before_date_returns_temporal_error
    """
    donor_id, app_id = create_under_review_application(display_code="D-C10")
    validate_success(api.approve_application(app_id, SO))
    specimen = validate_success(api.create_specimen({
        "donor_id": donor_id, "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 5, "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": True,
    }, LT), expected_status=201)
    validate_success(api.begin_quarantine(specimen["id"], "T-C10", LT))
    # clock still at default 2026-05-01, before 2026-06-01.
    resp = api.release_quarantine(specimen["id"], CO)
    validate_error(resp, ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED.value)
    spec = validate_success(api.get_specimen(specimen["id"], CO))
    assert spec["status"] == "QUARANTINE"


def test_sibling_confirm_without_shipment_returns_error(api):
    """PRD §3.8: "Confirmation requires that the entry be PENDING and that the
    recipient has at least one SHIPPED vial reservation for that donor; a confirmation
    attempted without such a shipped reservation is rejected with
    ERR_REGISTRY_NO_SHIPMENT."

    Design: Corner/state_machines/sibling_confirm_without_shipment_returns_error
    """
    donor = validate_success(api.create_donor({
        "display_code": "D-C11", "full_name": "Corner Eleven", "donor_type": "SPERM",
        "blood_type": "O_POS", "family_limit": 5}, SO), expected_status=201)
    recipient = validate_success(api.create_recipient({
        "family_name": "F C11", "contact_email": "c11@x.com"}, CM), expected_status=201)
    rcp_headers = make_recipient_headers(recipient["id"])
    entry = validate_success(api.create_sibling_registry_entry({
        "donor_id": donor["id"], "recipient_id": recipient["id"],
        "birth_reported_date": "2026-06-05T00:00:00Z",
    }, rcp_headers), expected_status=201)
    resp = api.confirm_sibling_registry(entry["id"], CO)
    validate_error(resp, ApiErrorId.ERR_REGISTRY_NO_SHIPMENT.value)
    entry_after = validate_success(api.get_sibling_registry_entry(entry["id"], CO))
    assert entry_after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------
def test_reservation_without_consent_returns_consent_missing(api):
    """PRD §3.4: "the recipient must hold a SIGNED RecipientConsent for the pairing of
    that recipient and the donor owning the target inventory; absent such a consent,
    the create is rejected with ERR_CONSENT_MISSING."

    Design: Corner/validations/reservation_without_consent_returns_consent_missing
    """
    inv = setup_listed_inventory(display_code="D-C14", family_limit=5,
                                 initial_vial_count=5, dewar_code="T-C14")
    recipient = validate_success(api.create_recipient({
        "family_name": "F C14", "contact_email": "c14@x.com"}, CM), expected_status=201)
    lot = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    resp = api.create_vial_reservation({
        "recipient_id": recipient["id"], "inventory_id": inv["inventory_id"],
        "vial_count": 1, "expected_inventory_version": lot["version"],
    }, make_recipient_headers(recipient["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING.value)


def test_reservation_on_frozen_inventory_returns_not_listed(api):
    """PRD §3.4: "the inventory must be listable — its hold_status must be OPEN, its
    specimen must be RELEASED, and its is_listed must be true; a create against a lot
    that is FROZEN, whose specimen is not RELEASED, or that is otherwise unlisted is
    rejected with ERR_INVENTORY_NOT_LISTED."

    Design: Corner/validations/reservation_on_frozen_inventory_returns_not_listed
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-C15", dewar_code="T-C15", initial_vial_count=5)
    defer_donor_via_second_application(ctx["donor_id"])
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["hold_status"] == "FROZEN"
    resp = api.create_vial_reservation({
        "recipient_id": ctx["recipient_id"], "inventory_id": ctx["inventory_id"],
        "vial_count": 1, "expected_inventory_version": inv["version"],
    }, ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_INVENTORY_NOT_LISTED.value)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
def test_confirm_reservation_updates_state_without_changing_counts(api):
    """PRD §3.4: "Confirmation is a CatalogManager action advancing the reservation
    HELD -> CONFIRMED ... Confirmation does not change any vial counts — a confirmed
    reservation continues to be counted in the lot's reserved_vials".

    Design: Corner/endpoints/reserve_then_confirm_updates_state
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-C16", dewar_code="T-C16", initial_vial_count=5)
    res = place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 1,
                     ctx["inventory_version"])
    data = validate_success(api.confirm_reservation(res["id"], CM))
    assert data["status"] == "CONFIRMED"
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["reserved_vials"] == 1
    assert inv["available_vials"] == 4


# ---------------------------------------------------------------------------
# calculations
# ---------------------------------------------------------------------------
def test_report_snapshot_totals_correct(api):
    """PRD §3.10: "Filing snapshots two figures onto the report:
    total_families_at_report, which captures the donor's reported_family_count as of
    the report, and total_vials_shipped_at_report, which is the sum of vial_count
    over that donor's reservations in SHIPPED status."

    Design: Corner/calculations/report_snapshot_totals_correct
    """
    ctx = setup_shipped_reservation(display_code="D-C13", dewar_code="T-C13",
                                    vial_count=2)
    confirm_one_family(ctx["donor_id"], ctx["recipient_id"], ctx["headers"])
    report = validate_success(api.create_regulatory_report({
        "donor_id": ctx["donor_id"], "report_type": "FDA_ANNUAL",
        "as_of": "2026-06-10T00:00:00Z",
    }, CO), expected_status=201)
    assert report["total_vials_shipped_at_report"] == 2
    assert report["total_families_at_report"] == 1
    assert report["status"] == "FILED"


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers (OCC)
# ---------------------------------------------------------------------------
def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.7: "The request that creates a vial reservation must carry
    expected_inventory_version, which is the value of the target donor inventory
    lot's version that the client last read." PRD §3.4: "On a successful hold, the
    reservation is created in HELD, its hold_expiry is set, the donor inventory lot's
    version is incremented by one".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-C20", dewar_code="T-C20", initial_vial_count=5)
    iv = ctx["inventory_version"]
    res = validate_success(api.create_vial_reservation({
        "recipient_id": ctx["recipient_id"], "inventory_id": ctx["inventory_id"],
        "vial_count": 1, "expected_inventory_version": iv,
    }, ctx["headers"]), expected_status=201)
    assert res["status"] == "HELD"
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["version"] == iv + 1, "reservation create increments inventory version by 1"


def test_occ_stale_version_returns_412(api):
    """PRD §2.7: "If the inventory lot's current version has advanced beyond that
    value — because another writer has since placed a hold that legitimately consumed
    some of the availability the current writer believed was free — the create is
    rejected with ERR_STALE_INVENTORY_VERSION at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_returns_412
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-C21", dewar_code="T-C21", initial_vial_count=5)
    iv = ctx["inventory_version"]
    # First hold advances the version past iv.
    place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 1, iv)
    # Second create reuses the now-stale iv.
    resp = api.create_vial_reservation({
        "recipient_id": ctx["recipient_id"], "inventory_id": ctx["inventory_id"],
        "vial_count": 1, "expected_inventory_version": iv,
    }, ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_INVENTORY_VERSION.value)
