"""Registration and CRUD-level claims (queue B — entities section)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_pole_owner, assert_attacher, assert_pole,
    create_pole_owner_payload, create_attacher_payload, create_pole_payload,
    create_application_payload,
    TEST_USERS, NON_EXISTENT_UUID,
    make_attacher_headers,
    setup_owner, setup_pole, setup_attacher,
)

COORD = TEST_USERS["coordinator_headers"]


def test_create_pole_owner_returns_201_and_version_one(api):
    """PRD §4: "Operations that register a new, stand-alone resource return
    `201 Created`; this includes registering owners, crews, poles, and attachers".
    PRD §2.4: "The `version` field is an integer that starts at 1 and increments
    by one on each mutation".

    Design: Corner/entities/create_pole_owner_success
    """
    res = api.create_pole_owner(create_pole_owner_payload(legal_name="O"), COORD)
    owner = validate_success(res, 201)
    assert_pole_owner(owner)
    assert owner["version"] == 1, f"fresh owner version must be 1, got {owner['version']}"
    body = res.json()
    assert body["response_type"] == "object"


def test_attacher_default_credit_limit_applied(api):
    """PRD §3.1: "a `credit_limit_cents` that defaults to 5,000,000 cents when
    omitted. Its `account_balance_cents` opens at zero and thereafter tracks the
    attacher's outstanding invoices."

    Design: Corner/entities/attacher_default_credit_limit_applied
    """
    res = api.create_attacher(create_attacher_payload(company_name="Acme", cin="CIN1"), COORD)
    attacher = validate_success(res, 201)
    assert attacher["credit_limit_cents"] == 5000000
    assert attacher["account_balance_cents"] == 0


def test_pole_computed_space_starts_zero(api):
    """PRD §3.1: "A freshly registered pole begins with `occupied_space_inches`
    and `reserved_space_inches` both at zero and `status` set to `ACTIVE`."

    Design: Corner/entities/pole_computed_space_starts_zero
    """
    owner = setup_owner(owner_category="ILEC")
    res = api.create_pole(create_pole_payload(owner["id"], usable_communication_space_inches=60), COORD)
    pole = validate_success(res, 201)
    assert_pole(pole)
    assert pole["occupied_space_inches"] == 0
    assert pole["reserved_space_inches"] == 0
    assert pole["status"] == "ACTIVE"


def test_get_unknown_application_returns_404(api):
    """PRD §2.5: "A path identifier that does not exist yields the
    resource-specific not-found error — `ERR_POLE_OWNER_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_POLE_NOT_FOUND`, `ERR_ATTACHER_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`".

    Design: Corner/entities/application_not_found_returns_404
    """
    res = api.get_application(NON_EXISTENT_UUID, COORD)
    validate_error(res, "ERR_APPLICATION_NOT_FOUND", expected_status=404)


def test_create_application_missing_required_field_rejected(api):
    """PRD §2.10: "Then body well-formedness — required fields present, enums
    valid, integers positive where required, and a survey window whose end is
    after its start — yielding `ERR_VALIDATION` (422)".

    Design: Corner/entities/create_application_missing_required_field_rejected
    """
    owner = setup_owner()
    pole = setup_pole(owner["id"])
    attacher = setup_attacher()
    payload = create_application_payload(pole["id"], attacher["id"])
    del payload["requested_space_inches"]
    res = api.create_application(payload, make_attacher_headers(attacher["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_duplicate_cin_rejected(api):
    """PRD §2.5: "An attacher's `cin` is globally unique; a second registration
    of the same value is rejected with `ERR_DUPLICATE_CIN`."

    Design: Corner/entities/duplicate_cin_rejected
    """
    setup_attacher(company_name="Acme", cin="CIN1")
    res = api.create_attacher(create_attacher_payload(company_name="Beta", cin="CIN1",
                                                      contact_email="b@x.com"), COORD)
    validate_error(res, "ERR_DUPLICATE_CIN", expected_status=409)


def test_duplicate_pole_tag_rejected(api):
    """PRD §2.5: "A pole's `tag` is unique within its owner; a second pole
    carrying the same `tag` under the same `pole_owner_id` is rejected with
    `ERR_DUPLICATE_POLE_TAG`."

    Design: Corner/entities/duplicate_pole_tag_rejected
    """
    owner = setup_owner(owner_category="MUNICIPAL")
    setup_pole(owner["id"], tag="P1")
    res = api.create_pole(create_pole_payload(owner["id"], tag="P1", height_ft=40,
                                              usable_communication_space_inches=72), COORD)
    validate_error(res, "ERR_DUPLICATE_POLE_TAG", expected_status=409)
