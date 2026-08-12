"""Intake: client/referral validation, defaults, system fields, activation
cascade, referral RBAC and auth envelope rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, ANONYMOUS_HEADERS,
    create_client_payload, create_referral_payload, create_evaluation_payload,
    create_client, is_valid_uuid,
    make_billing_specialist_headers, make_vision_specialist_headers,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def test_client_create_missing_full_name_rejected(api):
    """PRD §2.7: "3. **Body schema** — required fields present, types correct,
    enum members valid, numeric ranges honored (`ERR_VALIDATION`, HTTP 400)."
    PRD §3.1: "an `IntakeCoordinator` registers a **Client** with a `full_name`
    and `date_of_birth`".

    Design: Corner/entities/ent_client_create_missing_required_returns_validation
    """
    resp = api.create_client({"date_of_birth": "1958-03-04"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_client_copay_tier_defaults_to_standard(api):
    """PRD §3.1: "The coordinator may also record a `copay_tier` of `STANDARD`
    or `LOW_INCOME`; when omitted it defaults to `STANDARD`."
    PRD §3.1: "A freshly registered client has `status` `INTAKE`."

    Design: Corner/entities/ent_client_copay_tier_default_applied
    """
    c = get_success_data(api.create_client(
        {"full_name": "Ada Lo", "date_of_birth": "1960-01-01"}, INTAKE))
    assert c["copay_tier"] == "STANDARD"
    assert c["status"] == "INTAKE"


def test_client_system_fields_in_input_ignored(api):
    """PRD §2.4: "`id` — a server-minted UUID with no type prefix; it serves
    identity only and is never an input to any business decision or ranking rule."
    PRD §2.4: "`version` — an integer starting at 1 at creation".

    Design: Corner/entities/ent_client_system_fields_input_ignored

    Note: PRD is silent on whether supplying system-managed fields in a create
    payload is ignored or rejected, so this test only asserts the PRD-pinned
    creation values on a well-formed request.
    """
    c = get_success_data(api.create_client(
        {"full_name": "Sys Field", "date_of_birth": "1960-01-01"}, INTAKE))
    assert is_valid_uuid(c["id"]), "id is a server-minted UUID"
    assert c["version"] == 1


def test_get_unknown_client_returns_not_found(api):
    """PRD §2.7: "4. **Existence** — path ids and body foreign keys resolve
    (`ERR_NOT_FOUND`)."

    Design: Corner/entities/ent_client_get_not_found_returns_404
    """
    resp = api.get_client("123e4567-e89b-42d3-a456-426614174000", SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_referral_with_unknown_client_not_found(api):
    """PRD §2.7: "foreign keys supplied in a request body are existence-checked
    under the same rule."

    Design: Corner/entities/ent_referral_create_with_unknown_client_not_found
    """
    resp = api.create_referral(
        {"client_id": "123e4567-e89b-42d3-a456-426614174000",
         "source_type": "SELF", "referring_party": "self"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_referral_invalid_source_type_rejected(api):
    """PRD §3.1: "Creating a **Referral** records the `client_id`, a
    `source_type` of `PHYSICIAN`, `VR_AGENCY`, `INSURANCE`, or `SELF`".
    PRD §2.7: "3. **Body schema** — required fields present, types correct, enum
    members valid, numeric ranges honored, and ordering constraints such as
    `scheduled_start` strictly before `scheduled_end` and `valid_from` on or
    before `valid_until` (`ERR_VALIDATION`, HTTP 400)."

    Design: Corner/entities/ent_referral_invalid_enum_rejected
    """
    c = create_client(full_name="Enum Test")
    resp = api.create_referral(
        {"client_id": c["id"], "source_type": "CARRIER_PIGEON", "referring_party": "x"},
        INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_referral_decide_twice_rejected(api):
    """PRD §3.1: "A referral is born `RECEIVED` and ends either `ACCEPTED` or
    `DECLINED`; both are terminal."
    PRD §2.7: "the target entity is in a state from which the requested
    transition exists; terminal states reject everything (`ERR_INVALID_STATE`,
    or `ERR_PLAN_SUSPENDED` when scheduling onto a suspended or completed plan)".

    Design: Corner/state_machines/sm_referral_decide_twice_rejected
    """
    c = create_client(full_name="Twice Dec")
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    resp = api.decide_referral(r["id"], {"decision": "DECLINE"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    referrals = get_success_data(api.list_client_referrals(c["id"], INTAKE))
    assert referrals[0]["status"] == "ACCEPTED", "unchanged"


def test_client_activates_on_referral_accept(api):
    """PRD §3.1: "Acceptance carries one further effect: if the owning client is
    still `INTAKE`, the client's `status` flips to `ACTIVE` and the client's
    `version` increments — the client's activation is a side effect of referral
    acceptance, never a standalone call."

    Design: Corner/state_machines/sm_client_auto_activation_on_referral_accept
    """
    c = create_client(full_name="Auto Act")
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    after = get_success_data(api.get_client(c["id"], INTAKE))
    assert after["status"] == "ACTIVE"
    assert after["version"] == 2, "one mutation from the cascade"


def test_client_referrals_reverse_lookup(api):
    """PRD §3.1: "The referrals belonging to a client can be listed via the
    client's referral collection."

    Design: Corner/endpoints/ep_fk_reverse_referrals_of_client
    """
    c = create_client(full_name="FK Rev")
    r1 = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    r2 = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="PHYSICIAN", referring_party="Dr. Z"), INTAKE))
    referrals = get_success_data(api.list_client_referrals(c["id"], INTAKE))
    ids = {x["id"] for x in referrals}
    assert ids == {r1["id"], r2["id"]}


def test_evaluation_create_forbidden_for_billing(api):
    """PRD §4: "Create an evaluation (OCC-guarded; supersedes the client's prior
    drafts) | VisionSpecialist".
    PRD §2.1: "If the role is recognized but is not among the roles authorized
    for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/rbac_evaluation_create_forbidden_for_billing
    """
    c = create_client(full_name="RBAC One")
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    resp = api.create_evaluation(create_evaluation_payload(c["id"], r["id"], c_v),
                                 make_billing_specialist_headers("bs-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_catalog_create_forbidden_for_specialist(api):
    """PRD §4: "Create a catalog device model | ClinicAdmin".
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_catalog_forbidden_for_specialist
    """
    resp = api.create_device_model(
        {"name": "Rogue", "category": "CCTV", "list_price_cents": 1}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_run_daily_forbidden_for_intake(api):
    """PRD §4: "Run the daily sweep against the logical clock | ClinicAdmin".
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_run_daily_forbidden_for_intake
    """
    resp = api.run_daily(INTAKE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or the role value is not one of
    the recognized role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/val_missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_client(
        {"full_name": "No Auth", "date_of_birth": "1960-01-01"}, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_schema_checked_before_existence(api):
    """PRD §2.7: "3. **Body schema** — required fields present, types correct,
    enum members valid, numeric ranges honored".
    PRD §2.7: "4. **Existence** — path ids and body foreign keys resolve".
    PRD §2.7: "every request passes through a fixed validation funnel, and the
    **first** failing check determines the error returned".

    Design: Corner/validations/val_schema_checked_before_existence
    """
    resp = api.create_referral(
        {"client_id": "123e4567-e89b-42d3-a456-426614174000", "referring_party": "self"},
        INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_http_status_mapping_distinctness(api):
    """PRD §2.1: "If either header is missing, or the role value is not one of
    the recognized role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). ... the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.7: "short-circuits the request with `ERR_NOT_FOUND` (HTTP 404)".
    PRD §5: "`ERR_INVALID_STATE` | 409".

    Design: Corner/errors/err_http_status_mapping_distinctness
    """
    c = create_client(full_name="HTTP Map")
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="x"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))

    resp401 = api.create_client(
        {"full_name": "No Role", "date_of_birth": "1960-01-01"}, ANONYMOUS_HEADERS)
    validate_error(resp401, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    resp403 = api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="x"), SPECIALIST)
    validate_error(resp403, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    resp404 = api.get_client("123e4567-e89b-42d3-a456-426614174000", INTAKE)
    validate_error(resp404, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    resp409 = api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE)
    validate_error(resp409, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
