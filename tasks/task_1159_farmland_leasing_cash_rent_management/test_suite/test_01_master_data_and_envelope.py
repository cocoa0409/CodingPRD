"""Master-data creation rules, resource identity, and the response envelope.

Covers landlord defaults, 404 on unresolvable ids, required-field and
enum/conditional-parameter body validation, and the fixed success/error
envelope shape.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_landlord,
    create_bid_payload,
    create_field_payload,
    create_landlord_payload,
    is_valid_uuid,
    make_tenant_headers,
    setup_field,
    setup_landlord,
    setup_offering,
    setup_tenant,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


def test_landlord_creation_applies_defaults_and_system_fields(api):
    """PRD §3.1: "The `absentee` flag, defaulting to false, marks owners who are not involved day to day and drives report-acknowledgment escalation. The `report_channel`, one of `EMAIL`, `MAIL`, or `PORTAL` and defaulting to `EMAIL`, records the owner's preferred delivery channel. The `ack_required_days` value, a positive integer defaulting to 14, is the number of days an absentee owner has to acknowledge a report before escalation is required."
    PRD §3.1: "Each landlord's two ledger balances, `total_received_cents` and `pending_receivable_cents`, start at zero and are maintained thereafter per the ledger principles of §2.10."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/landlord_creation_applies_defaults_and_system_fields
    """
    resp = api.create_landlord(
        create_landlord_payload(name="L Dflt", contact_email="ld@x.com"), MGR
    )
    data = validate_success(resp, 201)
    assert_landlord(data)
    assert data["absentee"] is False, "absentee must default to false"
    assert data["report_channel"] == "EMAIL", "report_channel must default to EMAIL"
    assert data["ack_required_days"] == 14, "ack_required_days must default to 14"
    assert data["total_received_cents"] == 0, "total_received_cents starts at zero"
    assert data["pending_receivable_cents"] == 0, "pending_receivable_cents starts at zero"
    assert is_valid_uuid(data["id"]), "id is a server-minted UUID"


def test_lease_get_nonexistent_returns_not_found(api):
    """PRD §2.4: "Path identifiers are validated left to right: every id appearing in a URL path must resolve to an existing resource, and the first id that does not resolve fails the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/lease_get_nonexistent_returns_not_found
    """
    resp = api.get_lease(NON_EXISTENT_UUID, MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_field_creation_missing_required_acres_rejected(api):
    """PRD §3.1: "A manager creates one for a landlord by supplying the owning `landlord_id`, a `name`, the tillable `acres` as a positive integer, and the `soil_csr2` productivity rating on the 0-to-100 CSR2 scale"
    PRD §2.8: "Request-body shape — missing required fields, invalid enum members, non-positive amounts where a positive amount is required, missing conditional bid parameters for the declared `lease_type`, an `escalation_pct` present when it should be absent or vice versa, a `term_end_date` that is not later than `term_start_date`, a `conservation_practices` amendment attempted while the lease is `ACTIVE`, or a notice `served_by` value that does not match the caller's role all yield `ERR_VALIDATION` (HTTP 400), on every endpoint that takes a body."

    Design: Corner/entities/field_creation_missing_required_acres_rejected
    """
    landlord = setup_landlord(name="L Req", contact_email="lr@x.com")
    payload = create_field_payload(landlord["id"], name="FNoAcres")
    del payload["acres"]
    resp = api.create_field(payload, MGR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_bid_create_with_invalid_enum_rejected(api):
    """PRD §2.8: "Request-body shape — missing required fields, invalid enum members, non-positive amounts where a positive amount is required, missing conditional bid parameters for the declared `lease_type`, an `escalation_pct` present when it should be absent or vice versa, a `term_end_date` that is not later than `term_start_date`, a `conservation_practices` amendment attempted while the lease is `ACTIVE`, or a notice `served_by` value that does not match the caller's role all yield `ERR_VALIDATION` (HTTP 400), on every endpoint that takes a body."
    PRD §3.2: "A tenant bids by submitting a payload containing the target `offering_id` and a declared `lease_type` of `CASH`, `FLEX`, or `SHARE`"

    Design: Corner/entities/bid_create_with_invalid_enum_rejected
    """
    landlord = setup_landlord(name="L En", contact_email="le@x.com")
    tenant = setup_tenant(name="T En", years_experience=5)
    field = setup_field(landlord["id"], name="FEn")
    offering = setup_offering(field["id"])
    payload = create_bid_payload(offering["id"], "CASH")
    payload["lease_type"] = "GROSS"
    resp = api.create_bid(payload, make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_bid_create_flex_missing_conditional_params_rejected(api):
    """PRD §2.8: "Request-body shape — missing required fields, invalid enum members, non-positive amounts where a positive amount is required, missing conditional bid parameters for the declared `lease_type`, an `escalation_pct` present when it should be absent or vice versa, a `term_end_date` that is not later than `term_start_date`, a `conservation_practices` amendment attempted while the lease is `ACTIVE`, or a notice `served_by` value that does not match the caller's role all yield `ERR_VALIDATION` (HTTP 400), on every endpoint that takes a body."
    PRD §3.2: "A `FLEX` bid requires `flex_base_per_acre_cents` (the guaranteed base per acre), `flex_bonus_pct` (the landlord's bonus share of revenue above the trigger, between 0 and 1), `flex_cap_cents` (the annual bonus cap), and `revenue_trigger_cents` (the gross revenue above which the bonus applies)."

    Design: Corner/entities/bid_create_flex_missing_conditional_params_rejected
    """
    landlord = setup_landlord(name="L Cn", contact_email="lc2@x.com")
    tenant = setup_tenant(name="T Cn", years_experience=5)
    field = setup_field(landlord["id"], name="FCn")
    offering = setup_offering(field["id"])
    payload = create_bid_payload(offering["id"], "FLEX")
    del payload["flex_cap_cents"]
    resp = api.create_bid(payload, make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_response_envelope_shape_on_success_and_error(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    landlord = setup_landlord(name="L EV", contact_email="lev@x.com")

    ok_resp = api.get_landlord(landlord["id"], MGR)
    ok_body = ok_resp.json()
    data = validate_success(ok_resp)
    assert data["name"] == "L EV"
    assert isinstance(ok_body["meta"].get("api_request_id"), str)
    assert ok_body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )
    assert ok_body["response_type"] == "object"

    err_resp = api.get_landlord(NON_EXISTENT_UUID, MGR)
    err_data = validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)
    assert err_data["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_data.get("message"), str) and err_data["message"].strip()
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
