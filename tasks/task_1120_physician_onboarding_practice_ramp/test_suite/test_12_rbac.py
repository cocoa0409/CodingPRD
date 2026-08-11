"""Role-based access control: exclusive operations stay segregated, and
entity-backed physician identity is enforced on the offer negotiation path."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_physician, create_case, create_offer, extend_offer,
    create_credential_item, get_offer, get_credential_item,
    make_physician_headers,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]
PM = TEST_USERS["practice_manager_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]


def test_rbac_exclusive_operations_cannot_cross_roles(api):
    """PRD §2.9: "Endpoint authorization: the role is listed on the endpoint, else `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`ContractAdministrator` executes accepted offers, a step deliberately segregated from recruiting."
    PRD §2.1: "`CredentialingSpecialist` registers credential items and moves them through document submission, verification, and filing."

    Design: Corner/rbac/rbac_exclusive_operations_cannot_cross_roles
    """
    physician = create_physician(full_name="Dr. Jen", specialty="INTERNAL_MEDICINE")
    case = create_case(physician["id"])
    offer = create_offer(case)
    offer = extend_offer(offer["id"])
    validate_success(api_client.accept_offer(offer["id"], make_physician_headers(physician["id"])), 200)
    item = create_credential_item(case["id"], "STATE_LICENSE")
    validate_success(api_client.submit_credential_docs(item["id"], {}, CS1), 200)

    # PracticeManager is not on the verify endpoint's roles.
    resp = api_client.verify_credential_item(item["id"], {}, PM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # Recruiter is not on the execute endpoint's roles.
    resp = api_client.execute_offer(offer["id"], RECRUITER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # Physician is not on the submit-docs endpoint's roles.
    resp = api_client.submit_credential_docs(
        item["id"], {}, make_physician_headers(physician["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    assert get_offer(offer["id"])["status"] == "ACCEPTED", "denied calls must not mutate the offer"
    assert get_credential_item(item["id"])["status"] == "DOCS_SUBMITTED", (
        "denied calls must not mutate the item"
    )


def test_physician_cannot_accept_other_physicians_offer(api):
    """PRD §2.1: "a `Physician` caller may counter, accept, or decline only an offer belonging to their own case chain, and may complete only training modules of their own case's plan."
    PRD §2.1: "Once authenticated, a caller whose role is not listed on the target operation — or who fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/physician_cannot_accept_other_physicians_offer
    """
    physician_a = create_physician(full_name="Dr. Aaa", email="aaa@x.com")
    physician_b = create_physician(full_name="Dr. Bbb", email="bbb@x.com")
    case_b = create_case(physician_b["id"])
    offer_b = create_offer(case_b)
    offer_b = extend_offer(offer_b["id"])

    resp = api_client.accept_offer(offer_b["id"], make_physician_headers(physician_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_offer(offer_b["id"])["status"] == "EXTENDED"
