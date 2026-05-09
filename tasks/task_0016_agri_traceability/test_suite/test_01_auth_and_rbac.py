"""Auth, RBAC, and resource-existence tests (PRD §2.1, §2.6)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_planting_batch_payload,
    create_storage_bin_payload,
    create_registry_payload,
    create_distributor_payload,
    create_recall_payload,
    setup_batch_harvested,
    setup_batch_inspected_pass,
    make_grower_headers,
    DEFAULT_GROWER_ID,
)


# --------------------------------------------------------------------------
# PRD §2.1 — auth header presence and role recognition
# --------------------------------------------------------------------------

def test_missing_user_id_header_yields_auth_missing():
    """PRD §2.1: "If either header is missing or empty, the request is rejected
    with ERR_AUTH_MISSING."

    Claim: an empty X-User-ID rejects with ERR_AUTH_MISSING (HTTP 401).
    """
    headers = {"X-User-Role": "Grower"}
    res = api.create_planting_batch(create_planting_batch_payload(), headers)
    validate_error(res, "ERR_AUTH_MISSING")


def test_missing_user_role_header_yields_auth_missing():
    """PRD §2.1: "If either header is missing or empty, the request is rejected
    with ERR_AUTH_MISSING."

    Claim: missing X-User-Role rejects with ERR_AUTH_MISSING.
    """
    headers = {"X-User-ID": "some-user"}
    res = api.create_planting_batch(create_planting_batch_payload(), headers)
    validate_error(res, "ERR_AUTH_MISSING")


def test_unrecognized_role_yields_auth_invalid_role():
    """PRD §2.1: "If X-User-Role is not one of the recognized roles, the request
    is rejected with ERR_AUTH_INVALID_ROLE."

    Claim: an unrecognized role string yields ERR_AUTH_INVALID_ROLE.
    """
    headers = build_user_headers("user-x", "BogusRole")
    res = api.create_planting_batch(create_planting_batch_payload(), headers)
    validate_error(res, "ERR_AUTH_INVALID_ROLE")


# --------------------------------------------------------------------------
# PRD §2.1 / §4 — RBAC: role recognized but not permitted
# --------------------------------------------------------------------------

def test_grower_cannot_create_pesticide_registry():
    """PRD §2.1: "If the role is recognized but not permitted on the requested
    endpoint, the request is rejected with ERR_FORBIDDEN."
    PRD §3.1: "A RegulatoryOfficer populates and curates the registry."

    Claim: a Grower posting to /pesticide-registry → ERR_FORBIDDEN.
    """
    res = api.create_registry(create_registry_payload(), TEST_USERS["grower_headers"])
    validate_error(res, "ERR_FORBIDDEN")


def test_consumer_cannot_create_planting_batch():
    """PRD §2.1: "If the role is recognized but not permitted on the requested
    endpoint, the request is rejected with ERR_FORBIDDEN."

    Claim: Consumer cannot register a planting batch (Grower-exclusive).
    """
    res = api.create_planting_batch(
        create_planting_batch_payload(), TEST_USERS["consumer_headers"]
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_distributor_cannot_initiate_recall():
    """PRD §2.10: "Recall initiation and recall completion are reserved to
    RegulatoryOfficers."

    Claim: a Distributor calling POST /recall-orders → ERR_FORBIDDEN.
    """
    payload = create_recall_payload(NON_EXISTENT_UUID)
    res = api.create_recall(payload, TEST_USERS["distributor_headers"])
    validate_error(res, "ERR_FORBIDDEN")


def test_grower_cannot_create_storage_bin():
    """PRD §3.4: "A storage bin is created by a LogisticsOperator."

    Claim: a Grower posting to /storage-bins → ERR_FORBIDDEN.
    """
    res = api.create_storage_bin(
        create_storage_bin_payload(), TEST_USERS["grower_headers"]
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_inspector_cannot_revoke_inspection():
    """PRD §3.5: "A RegulatoryOfficer may revoke an issued report."

    Claim: an Inspector posting /inspection-reports/{id}/revoke → ERR_FORBIDDEN.
    """
    batch, _bin, _harvest, report = setup_batch_inspected_pass()
    res = api.revoke_inspection(report["id"], TEST_USERS["inspector_headers"])
    validate_error(res, "ERR_FORBIDDEN")


def test_distributor_cannot_acknowledge_when_not_destination():
    """PRD §2.10: "A Distributor who acknowledges a leg must be the leg's
    destination party — the acknowledger's X-User-ID must equal to_party_id."

    Claim: a distributor whose X-User-ID != leg.to_party_id → ERR_FORBIDDEN.
    """
    from test_helpers import setup_logistics_leg_in_transit
    _batch, leg, _distributor = setup_logistics_leg_in_transit()
    # Build headers using a different distributor id
    foreign = build_user_headers("some-other-distributor-id", "Distributor")
    res = api.acknowledge_leg(leg["id"], foreign)
    validate_error(res, "ERR_FORBIDDEN")


# --------------------------------------------------------------------------
# PRD §2.6 — resource existence (left-to-right path validation)
# --------------------------------------------------------------------------

def test_get_nonexistent_planting_batch_yields_not_found(regulatory_headers):
    """PRD §2.6: "The first unresolved identifier yields ERR_NOT_FOUND
    immediately; the request never proceeds to deeper path components or to
    body validation."

    Claim: GET /planting-batches/{unknown} → ERR_NOT_FOUND (HTTP 404).
    """
    res = api.get_planting_batch(NON_EXISTENT_UUID, regulatory_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_post_application_under_unknown_batch_yields_not_found():
    """PRD §2.6: "The outer identifier must resolve before any inner identifier
    is even looked up. The first unresolved identifier yields ERR_NOT_FOUND
    immediately."

    Claim: POST /planting-batches/{unknown}/agrochemical-applications →
    ERR_NOT_FOUND.
    """
    from test_helpers import create_agrochemical_application_payload
    headers = make_grower_headers(DEFAULT_GROWER_ID)
    res = api.create_agrochemical_application(
        NON_EXISTENT_UUID,
        create_agrochemical_application_payload(),
        headers,
    )
    validate_error(res, "ERR_NOT_FOUND")


def test_get_storage_bin_unknown_id_yields_not_found(regulatory_headers):
    """PRD §2.6: "The first unresolved identifier yields ERR_NOT_FOUND immediately."

    Claim: GET /storage-bins/{unknown} → ERR_NOT_FOUND.
    """
    res = api.get_storage_bin(NON_EXISTENT_UUID, regulatory_headers)
    validate_error(res, "ERR_NOT_FOUND")
