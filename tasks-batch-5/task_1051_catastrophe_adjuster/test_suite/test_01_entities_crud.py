"""Entity CRUD, defaults, system fields, envelopes, and existence resolution."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    TEST_USERS, make_field_adjuster_headers,
    create_adjuster_payload, create_claim_payload, create_license_payload,
    assert_adjuster,
)
from test_helpers import fixtures as fx

DESK = TEST_USERS["desk_examiner_headers"]
ADMIN = TEST_USERS["licensing_admin_headers"]


def test_create_adjuster_returns_201_with_fields(api):
    """PRD 3.1: "A new adjuster's status begins as ACTIVE and may only ever be
    ACTIVE or INACTIVE." The create supplies full_name, email, adjuster_type and
    home_state, and the created resource echoes them (PRD 4: creation endpoints
    return HTTP 201 with the newly created resource).

    Design: Corner/entities/create_adjuster_returns_201_with_fields
    """
    resp = api.create_adjuster(
        create_adjuster_payload(full_name="Casey", email="casey@x.com",
                                adjuster_type="CAT", home_state="TX"),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_adjuster(data)
    assert data["full_name"] == "Casey"
    assert data["home_state"] == "TX"
    assert data["adjuster_type"] == "CAT"
    assert data["status"] == "ACTIVE"


def test_system_fields_minted_on_adjuster(api):
    """PRD 2.5: "Every persisted resource carries a server-minted id that is a UUID
    with no type prefix" and "an integer version that begins at 1 and increments by
    1 on each mutation."

    Design: Corner/entities/system_fields_minted_on_adjuster
    """
    data = validate_success(api.create_adjuster(
        create_adjuster_payload(full_name="Sys", adjuster_type="CAT"), ADMIN), 201)
    assert is_valid_uuid(data["id"]), "id must be a UUID with no type prefix"
    assert data["version"] == 1


def test_get_claim_nonexistent_returns_not_found(api):
    """PRD 2.9: "Any endpoint that references resource ids ... resolves those ids
    left to right, in path-then-body order, and returns the corresponding not-found
    error the moment an id fails to resolve (for example ERR_CLAIM_NOT_FOUND...)."

    Design: Corner/entities/get_claim_nonexistent_returns_not_found
    """
    resp = api.get_claim(NON_EXISTENT_UUID, DESK)
    validate_error(resp, "ERR_CLAIM_NOT_FOUND")


def test_create_claim_missing_loss_state_returns_invalid(api):
    """PRD 2.10: "Request shape — body-level field constraints, else
    ERR_INVALID_REQUEST." loss_state is one of the fields a DeskExaminer supplies on
    claim creation (PRD 3.3), so omitting it violates the request shape.

    Design: Corner/entities/create_claim_missing_loss_state_returns_invalid
    """
    payload = create_claim_payload()
    payload.pop("loss_state")
    resp = api.create_claim(payload, DESK)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_claim_starts_in_intake(api):
    """PRD 3.3: "A new claim opens in INTAKE with rcv_cents and reserve_consumed_cents
    both 0."

    Design: Corner/state_machines/claim_starts_in_intake
    """
    data = validate_success(api.create_claim(create_claim_payload(), DESK), 201)
    assert data["status"] == "INTAKE"
    assert data["rcv_cents"] == 0
    assert data["reserve_consumed_cents"] == 0


def test_create_report_omits_photo_count_defaults_zero(api):
    """PRD 3.5: "a photo_count (a non-negative integer that defaults to 0 when
    omitted)."

    Design: Corner/entities/create_report_omits_photo_count_defaults_zero
    """
    ctx = fx.setup_completed_inspection(api)
    # Draft a report without supplying photo_count.
    payload = {"inspection_id": ctx["insp_id"], "assignment_id": ctx["asg_id"],
               "scope_narrative": "s"}
    resp = api.create_report(payload, make_field_adjuster_headers(ctx["adj_id"]))
    data = validate_success(resp, 201)
    assert data["photo_count"] == 0


def test_list_adjusters_pagination_envelope(api):
    """PRD 2.3: "The meta block of a list response carries limit, offset, total_count
    (the total number of matching resources across all pages), and has_more (true when
    further resources exist beyond the current page)."

    Design: Corner/entities/list_adjusters_pagination_envelope
    """
    fx.create_adjuster(api, full_name="P1", adjuster_type="CAT", home_state="FL")
    fx.create_adjuster(api, full_name="P2", adjuster_type="STAFF", home_state="GA")
    data, meta = validate_paginated(api.list_adjusters(DESK))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_success_envelope_shape_on_get_adjuster(api):
    """PRD 2.2: "The api_request_id is a server-generated unique identifier for the
    request that starts with req_." and the success envelope carries response_type
    "object" with the resource in data.

    Design: Corner/endpoints/success_envelope_shape_on_get_adjuster
    """
    adj = fx.create_adjuster(api, full_name="Env", adjuster_type="CAT")
    resp = api.get_adjuster(adj["id"], DESK)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["data"]["id"] == adj["id"]


def test_license_with_unknown_adjuster_returns_not_found(api):
    """PRD 2.9: referenced ids "in the URL path or the request body" are resolved and
    the matching not-found error is returned "the moment an id fails to resolve". A
    license names its adjuster_id (PRD 3.1); an unknown adjuster yields
    ERR_ADJUSTER_NOT_FOUND.

    Design: Corner/entities/license_with_unknown_adjuster_returns_not_found
    """
    payload = create_license_payload(NON_EXISTENT_UUID)
    resp = api.create_license(payload, ADMIN)
    validate_error(resp, "ERR_ADJUSTER_NOT_FOUND")
