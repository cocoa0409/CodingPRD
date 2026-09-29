"""
The declared error envelope, checked at every status class the catalogue uses.

Every test builds its own world from scratch through declared endpoints — the harness
restarts the API with an empty database before each test — and sets the logical clock
explicitly whenever the scenario names an instant.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    DEFAULT_LIMIT,
    ERR_CONTRACT_INVALID_STATE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ROLE_FORBIDDEN,
    ERR_STALE_CONTRACT_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_USAGE_REGRESSION,
    SERVICE_COORDINATOR,
    UNKNOWN_UUID,
    assert_error_envelope,
    assert_fields,
    assert_pagination_meta,
    assert_two_decimals,
    build_fleet,
    club_payload,
    contract_version,
    credit_reconciliation_payload,
    read_contract,
    read_equipment,
    usage_reading_payload,
    validate_error,
    validate_paginated,
)

# Well-formed transport headers that carry no identity at all.
NO_IDENTITY = {"Content-Type": "application/json"}


def test_every_refusal_class_returns_the_declared_error_envelope_and_changes_nothing(api):
    """
    Authentication, authorisation, lookup, validation, state, version and semantic refusals
    all answer in the one declared error shape.

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/error_replies_use_the_declared_envelope_at_every_status_class
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-EV-1"],
        equipment_kwargs={"initial_usage_hours": 500},
    )
    club_id = fleet["club_id"]
    contract_id = fleet["contract_id"]
    e1 = fleet["equipment_ids"][0]

    # 401 — the identity headers are missing entirely.
    missing_identity = api.get_club(club_id, NO_IDENTITY)
    assert missing_identity.status_code == 401
    validate_error(missing_identity, ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(missing_identity.json(), ERR_UNAUTHENTICATED)

    # 403 — a well-formed role that this endpoint does not list.
    wrong_role = api.create_club(
        club_payload(name="Westside Fitness", region_code="WEST"), SERVICE_COORDINATOR
    )
    assert wrong_role.status_code == 403
    validate_error(wrong_role, ERR_ROLE_FORBIDDEN, 403)
    assert_error_envelope(wrong_role.json(), ERR_ROLE_FORBIDDEN)

    # 404 — a syntactically valid id that names nothing.
    absent = api.get_contract(UNKNOWN_UUID, CONTRACT_ADMIN)
    assert absent.status_code == 404
    validate_error(absent, ERR_CONTRACT_NOT_FOUND, 404)
    assert_error_envelope(absent.json(), ERR_CONTRACT_NOT_FOUND)

    # 400 — a required field is absent from the body.
    incomplete = api.create_club({"name": "Regionless Fitness"}, CONTRACT_ADMIN)
    assert incomplete.status_code == 400
    validate_error(incomplete, ERR_INVALID_REQUEST, 400)
    assert_error_envelope(incomplete.json(), ERR_INVALID_REQUEST)

    # 409 — the transition is not available from the row's current state.
    already_active = api.activate_contract(contract_id, CONTRACT_ADMIN)
    assert already_active.status_code == 409
    validate_error(already_active, ERR_CONTRACT_INVALID_STATE, 409)
    assert_error_envelope(already_active.json(), ERR_CONTRACT_INVALID_STATE)

    # 412 — the write carries a version the contract has already left behind.
    live_version = contract_version(api, contract_id)
    stale = api.reconcile_credits(
        contract_id,
        credit_reconciliation_payload("2026-08", live_version - 1),
        CONTRACT_ADMIN,
    )
    assert stale.status_code == 412
    validate_error(stale, ERR_STALE_CONTRACT_VERSION, 412)
    assert_error_envelope(stale.json(), ERR_STALE_CONTRACT_VERSION)

    # 422 — the body is well formed but the domain rule refuses it.
    regressed = api.record_usage_reading(
        e1, usage_reading_payload(1), SERVICE_COORDINATOR
    )
    assert regressed.status_code == 422
    validate_error(regressed, ERR_USAGE_REGRESSION, 422)
    assert_error_envelope(regressed.json(), ERR_USAGE_REGRESSION)

    # None of the seven refusals left a trace behind them.
    clubs, clubs_meta = validate_paginated(api.list_clubs(CONTRACT_ADMIN))
    assert_pagination_meta(clubs_meta, DEFAULT_LIMIT, 0, 1, False)
    assert clubs[0]["id"] == club_id
    assert_fields(read_contract(api, contract_id), status="ACTIVE", version=live_version)
    assert_two_decimals(read_equipment(api, e1)["usage_hours"], 500, "usage_hours")
