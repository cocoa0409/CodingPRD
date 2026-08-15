"""Access control: authentication, role authorization, entity-backed ownership
(PRD §2.1, §3.4, §4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_veterinarian_payload, create_vfd_authorization_payload,
    setup_clinic_with_vet, setup_producer_with_group, setup_drug,
    record_vcpr, issue_vfd, setup_order_chain,
    make_veterinarian_headers, make_producer_headers,
)


def test_missing_role_header_rejected_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing, malformed, or not
    one of these four values is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_missing_role_header
    """
    headers_without_role = {
        "X-User-ID": "test-inspector-1",
        "Content-Type": "application/json",
    }
    res = api.list_clinics(headers_without_role)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_veterinarian_cannot_validate_feed_order(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /vfd/feed-orders/{id}/validate is authorized for FeedMillOperator.

    Design: Corner/roles/vet_cannot_validate_feed_order
    """
    chain = setup_order_chain()
    vet_headers = make_veterinarian_headers(chain["vet"]["id"])
    res = api.validate_feed_order(
        chain["order"]["id"],
        {"expected_vfd_authorization_version": chain["vfd"]["version"]},
        vet_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_producer_cannot_issue_vfd(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /vfd/vfd-authorizations is authorized for Veterinarian.

    Design: Corner/roles/producer_cannot_issue_vfd
    """
    clinic, vet = setup_clinic_with_vet()
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    res = api.create_vfd_authorization(
        create_vfd_authorization_payload(producer["id"], group["id"], vet["id"], drug["id"]),
        make_producer_headers(producer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_wrong_vet_cannot_revoke_other_vets_vfd(api, inspector_headers):
    """PRD §3.4: "it can be revoked by the veterinarian who issued it, which requires
    `X-User-ID` to equal the VFD's `vet_id` (otherwise `ERR_FORBIDDEN`)"

    Design: Corner/roles/wrong_vet_cannot_revoke_other_vets_vfd
    """
    clinic, vet_a = setup_clinic_with_vet()
    vet_b = validate_success(api.create_veterinarian(
        clinic["id"], create_veterinarian_payload(full_name="Dr. B"),
        inspector_headers,
    ), 201)
    producer, group = setup_producer_with_group()
    drug = setup_drug()
    record_vcpr(vet_a, producer)
    vfd = issue_vfd(vet_a, producer, group, drug)

    res = api.revoke_vfd_authorization(vfd["id"], make_veterinarian_headers(vet_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
