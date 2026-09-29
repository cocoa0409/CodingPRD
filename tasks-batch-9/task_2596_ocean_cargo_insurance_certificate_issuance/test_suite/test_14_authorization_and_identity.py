"""
Authorisation and acting identity on the Ocean Cargo Insurance API.

Every request is screened twice before anything else happens: the two auth
headers must be present and name one of the declared roles, and that role must
be authorised for the endpoint. Beyond those two screens the two entity-backed
identities — the assured acting as its own open cover and the surveyor acting as
its own panel row — are held to ownership of the resource they touch, and the
two segregation-of-duties gates keep the premium submitter out of the audit and
the adjusting adjuster out of the settlement.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADJUSTER_2_USER_ID,
    ADJUSTER_USER_ID,
    AUDITOR_USER_ID,
    CERTIFICATE_DECLARED_SHIPMENT,
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_2,
    COMPLIANCE_OFFICER,
    ERR_MISSING_AUTH_HEADERS,
    ERR_OWNERSHIP_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
    EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
    EXPECTED_TOTAL_PREMIUM,
    PLATFORM_ADMIN,
    PORT_NLRTM,
    PORT_SGSIN,
    PORT_USNYC,
    PREMIUM_AUDITOR,
    ROLE_ASSURED,
    ROLE_PREMIUM_AUDITOR,
    ROLE_UNDERWRITER,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    assert_money,
    assert_rate,
    build_adjusted_claim,
    build_canonical_environment,
    build_draft_certificate,
    build_environment_with_issued_certificate,
    build_issued_certificate,
    build_submitted_declaration,
    create_open_policy,
    create_survey_order,
    create_surveyor,
    make_assured_headers,
    make_headers,
    make_surveyor_headers,
    open_claim_file,
    policy_version,
    read_certificate,
    read_claim_file,
    read_declaration,
    read_policy,
    read_port,
    read_survey_order,
    read_surveyor,
    set_clock,
    headers_without_role,
    headers_without_user_id,
)

# A role string outside the seven the API declares.
UNDECLARED_ROLE = "MarineBroker"


def _two_policy_environment(api: ApiClient) -> JsonDict:
    """
    Two active open covers held by different assureds. The canonical cover is
    policy A; policy B is a second cover whose assured is a peer with no claim
    on A's resources.
    """
    env = build_canonical_environment(api)
    policy_b = create_open_policy(api, activate=True,
                                  policy_number="OP-OWN-B",
                                  assured_name="Falcon Freight BV")
    env["policy_b"] = policy_b
    env["policy_b_id"] = policy_b["id"]
    env["assured_b"] = make_assured_headers(policy_b["id"])
    return env


def _order_with_two_panel_surveyors(api: ApiClient) -> JsonDict:
    """
    An issued certificate with an open claim, two active surveyors both
    certified for the shipment's susceptibility rating, and an appointment held
    by the first of them whose attendance window the clock has just reached.
    """
    env = build_environment_with_issued_certificate(api)
    env["surveyor_one"] = create_surveyor(
        api, env["loading_port_id"], name="Lim Marine Surveys",
        panel_code="PANEL-ONE", certified_commodity_ratings=["S3"])
    env["surveyor_two"] = create_surveyor(
        api, env["loading_port_id"], name="Ng Marine",
        panel_code="PANEL-TWO", certified_commodity_ratings=["S3"])
    env["surveyor_one_id"] = env["surveyor_one"]["id"]
    env["surveyor_two_id"] = env["surveyor_two"]["id"]
    env["claim"] = open_claim_file(api, env["certificate_id"],
                                  damage_percentage=12.5)
    env["claim_id"] = env["claim"]["id"]
    env["order"] = create_survey_order(api, env["claim_id"],
                                       env["surveyor_one_id"])
    env["order_id"] = env["order"]["id"]
    set_clock(api, "2026-09-08T09:00:00Z")
    return env


def _declaration_payload(policy_id: str) -> JsonDict:
    """A reporting period covering the month the canonical certificate sails in."""
    return {
        "open_policy_id": policy_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Declaring and issuing sit on opposite sides of the contract
# ---------------------------------------------------------------------------
def test_the_assured_that_declared_a_shipment_may_not_issue_it(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """The assured owns the draft certificate but may not underwrite it.

    Issue is where the insurer accepts the risk, and it is reserved to the `Underwriter`.

    Design: Corner/rbac/assured_cannot_issue_and_underwriter_cannot_declare_a_shipment
    """
    draft = build_draft_certificate(api, canonical_env)
    version_before = policy_version(api, canonical_env["policy_id"])

    refused = api.issue_certificate(
        draft["id"], {"expected_open_policy_version": version_before},
        canonical_env["assured"])
    validate_error(refused, ERR_UNAUTHORIZED)

    # The identical payload from the underwriter succeeds, so the refusal was
    # about the acting role and not about the request.
    issued = validate_success(api.issue_certificate(
        draft["id"], {"expected_open_policy_version": version_before},
        UNDERWRITER))
    assert issued["status"] == "ISSUED"

    policy = read_policy(api, canonical_env["policy_id"])
    assert policy["version"] == version_before + 1, (
        "only the accepted issue may move the open cover's version"
    )


def test_a_platform_admin_may_not_issue_a_certificate(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """Read access everywhere is not write access anywhere.

    If both headers are well formed but the named role is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/assured_cannot_issue_and_underwriter_cannot_declare_a_shipment
    """
    draft = build_draft_certificate(api, canonical_env)
    version_before = policy_version(api, canonical_env["policy_id"])

    refused = api.issue_certificate(
        draft["id"], {"expected_open_policy_version": version_before},
        PLATFORM_ADMIN)
    validate_error(refused, ERR_UNAUTHORIZED)

    certificate = read_certificate(api, draft["id"])
    assert certificate["status"] == "DRAFT"
    assert certificate.get("issued_by_user_id") is None
    assert certificate.get("issued_at") is None

    policy = read_policy(api, canonical_env["policy_id"])
    assert policy["version"] == version_before, (
        "a refused issue must not consume the open cover's version"
    )


def test_an_underwriter_may_not_declare_a_shipment(
        api: ApiClient, canonical_env: JsonDict) -> None:
    """The underwriter that will issue a certificate cannot declare one.

    An `Assured` declares a shipment under its own open cover by naming the cover through `open_policy_id`, the goods through `commodity_class_id`, the carrying conveyance through `vessel_id`, and the voyage endpoints through `loading_port_id` and `discharge_port_id`.

    Design: Corner/rbac/assured_cannot_issue_and_underwriter_cannot_declare_a_shipment
    """
    build_draft_certificate(api, canonical_env)

    payload = dict(CERTIFICATE_DECLARED_SHIPMENT)
    payload.update({
        "open_policy_id": canonical_env["policy_id"],
        "commodity_class_id": canonical_env["commodity_class_id"],
        "vessel_id": canonical_env["vessel_id"],
        "loading_port_id": canonical_env["loading_port_id"],
        "discharge_port_id": canonical_env["discharge_port_id"],
        "certificate_number": "CERT-RBAC2",
        "declared_value": 400000,
        "package_count": 40,
        "gross_weight_kg": 6000,
    })
    validate_error(api.create_certificate(payload, UNDERWRITER),
                   ERR_UNAUTHORIZED)

    # The premium auditor holds read access, and the refused declaration
    # created nothing.
    _, meta = validate_paginated(api.list_certificates(
        PREMIUM_AUDITOR, {"open_policy_id": canonical_env["policy_id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The two header screens: 401 before 403
# ---------------------------------------------------------------------------
def test_a_request_with_no_role_header_is_refused_as_unauthenticated(
        api: ApiClient) -> None:
    """Omitting X-User-Role is an authentication failure, not an authorisation one.

    If either header is absent, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401).

    Design: Corner/rbac/requests_missing_auth_headers_or_carrying_an_unknown_role_are_refused
    """
    get_success_data(api.create_port(dict(PORT_SGSIN), UNDERWRITER))

    validate_error(
        api.create_port(dict(PORT_NLRTM), headers_without_role("underwriter-1")),
        ERR_MISSING_AUTH_HEADERS)

    _, meta = validate_paginated(api.list_ports(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the refused request must not create a port"


def test_a_request_with_no_user_id_header_is_refused_as_unauthenticated(
        api: ApiClient) -> None:
    """The acting identity matters as much as the role, so its absence is a 401.

    If either header is absent, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401).

    Design: Corner/rbac/requests_missing_auth_headers_or_carrying_an_unknown_role_are_refused
    """
    get_success_data(api.create_port(dict(PORT_SGSIN), UNDERWRITER))

    validate_error(
        api.create_port(dict(PORT_USNYC),
                        headers_without_user_id(ROLE_UNDERWRITER)),
        ERR_MISSING_AUTH_HEADERS)

    _, meta = validate_paginated(api.list_ports(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the refused request must not create a port"


def test_a_role_outside_the_declared_seven_is_refused_as_unauthenticated(
        api: ApiClient) -> None:
    """An unrecognised role name is a 401, never a 403.

    If either header is absent, or if `X-User-Role` is not one of the seven role names below, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401).

    Design: Corner/rbac/requests_missing_auth_headers_or_carrying_an_unknown_role_are_refused
    """
    get_success_data(api.create_port(dict(PORT_SGSIN), UNDERWRITER))

    payload = dict(PORT_NLRTM)
    payload.update({"unlocode": "AUSYD", "name": "Sydney", "country_code": "AU"})
    validate_error(
        api.create_port(payload, make_headers("broker-1", UNDECLARED_ROLE)),
        ERR_MISSING_AUTH_HEADERS)

    _, meta = validate_paginated(api.list_ports(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the refused request must not create a port"


def test_a_declared_role_off_the_endpoints_list_is_refused_as_unauthorised(
        api: ApiClient) -> None:
    """A well-formed request from a role the endpoint does not grant is a 403.

    If both headers are well formed but the named role is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/requests_missing_auth_headers_or_carrying_an_unknown_role_are_refused
    """
    get_success_data(api.create_port(dict(PORT_SGSIN), UNDERWRITER))

    payload = dict(PORT_NLRTM)
    payload.update({"unlocode": "JPTYO", "name": "Tokyo", "country_code": "JP"})
    validate_error(api.create_port(payload, CLAIMS_ADJUSTER), ERR_UNAUTHORIZED)

    _, meta = validate_paginated(api.list_ports(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the refused request must not create a port"


# ---------------------------------------------------------------------------
# Two assureds are peers with disjoint resources
# ---------------------------------------------------------------------------
def test_an_assured_may_not_confirm_delivery_on_another_policys_certificate(
        api: ApiClient) -> None:
    """A foreign assured is refused on ownership even on its own allowed endpoint.

    Concretely, an `Assured` may declare a shipment, confirm its delivery, open and submit a premium declaration, and post general average security only where the certificate, declaration or security posting resolves back to the policy whose `id` equals `X-User-ID`.

    Design: Corner/rbac/an_assured_cannot_act_on_another_policys_certificate
    """
    env = _two_policy_environment(api)
    certificate = build_issued_certificate(api, env)
    set_clock(api, "2026-08-15T00:00:00Z")

    validate_error(api.confirm_delivery(certificate["id"], env["assured_b"]),
                   ERR_OWNERSHIP_MISMATCH)
    assert read_certificate(api, certificate["id"])["status"] == "ISSUED", (
        "the refused confirmation must not end transit"
    )

    # The rightful assured makes the identical call succeed.
    delivered = validate_success(
        api.confirm_delivery(certificate["id"], env["assured"]))
    assert delivered["status"] == "TRANSIT_ENDED"

    intruder_policy = read_policy(api, env["policy_b_id"])
    assert_money(intruder_policy["aggregate_insured_value_booked"], 0.00,
                 "policy B aggregate_insured_value_booked")


def test_an_assured_may_not_declare_a_shipment_under_another_policy(
        api: ApiClient) -> None:
    """The body's open_policy_id, not the header, names the foreign cover.

    Concretely, an `Assured` may declare a shipment, confirm its delivery, open and submit a premium declaration, and post general average security only where the certificate, declaration or security posting resolves back to the policy whose `id` equals `X-User-ID`.

    Design: Corner/rbac/an_assured_cannot_act_on_another_policys_certificate
    """
    env = _two_policy_environment(api)
    build_draft_certificate(api, env)

    payload = dict(CERTIFICATE_DECLARED_SHIPMENT)
    payload.update({
        "open_policy_id": env["policy_id"],
        "commodity_class_id": env["commodity_class_id"],
        "vessel_id": env["vessel_id"],
        "loading_port_id": env["loading_port_id"],
        "discharge_port_id": env["discharge_port_id"],
        "certificate_number": "CERT-OWN-X",
        "declared_value": 400000,
        "package_count": 40,
        "gross_weight_kg": 6000,
    })
    validate_error(api.create_certificate(payload, env["assured_b"]),
                   ERR_OWNERSHIP_MISMATCH)

    _, meta = validate_paginated(api.list_certificates(
        UNDERWRITER, {"open_policy_id": env["policy_id"]}))
    assert meta["total_count"] == 1, "CERT-OWN-X must never have been created"

    intruder_policy = read_policy(api, env["policy_b_id"])
    assert_money(intruder_policy["aggregate_insured_value_booked"], 0.00,
                 "policy B aggregate_insured_value_booked")


def test_an_assured_may_not_open_a_premium_declaration_on_another_policy(
        api: ApiClient) -> None:
    """Reporting a period is only open to the assured that holds the cover.

    Concretely, an `Assured` may declare a shipment, confirm its delivery, open and submit a premium declaration, and post general average security only where the certificate, declaration or security posting resolves back to the policy whose `id` equals `X-User-ID`.

    Design: Corner/rbac/an_assured_cannot_act_on_another_policys_certificate
    """
    env = _two_policy_environment(api)
    build_issued_certificate(api, env)

    validate_error(
        api.create_premium_declaration(_declaration_payload(env["policy_id"]),
                                       env["assured_b"]),
        ERR_OWNERSHIP_MISMATCH)

    _, meta = validate_paginated(api.list_premium_declarations(
        UNDERWRITER, {"open_policy_id": env["policy_id"]}))
    assert meta["total_count"] == 0, (
        "the refused request must leave no declaration on the foreign cover"
    )

    # The rightful assured opens the same period without difficulty.
    opened = get_success_data(api.create_premium_declaration(
        _declaration_payload(env["policy_id"]), env["assured"]))
    assert opened["status"] == "OPEN"


# ---------------------------------------------------------------------------
# An appointment binds one named panel member
# ---------------------------------------------------------------------------
def test_a_surveyor_may_not_file_the_report_on_another_surveyors_order(
        api: ApiClient) -> None:
    """A second, equally certified and equally active surveyor still may not file.

    Only the appointed `Surveyor` may file, and only on their own order: the acting `X-User-ID` must equal the order's `surveyor_id`, or the request is refused with `ERR_OWNERSHIP_MISMATCH`.

    Design: Corner/rbac/a_surveyor_cannot_file_the_report_on_another_surveyors_order
    """
    env = _order_with_two_panel_surveyors(api)
    intruder = make_surveyor_headers(env["surveyor_two_id"])

    validate_error(
        api.file_survey_report(
            env["order_id"],
            {"packaging_compliant": True, "report_reference": "SR-INTRUDER",
             "damage_percentage_found": 12.5},
            intruder),
        ERR_OWNERSHIP_MISMATCH)

    _, meta = validate_paginated(
        api.list_claim_documents(env["claim_id"], CLAIMS_ADJUSTER))
    assert meta["total_count"] == 0, "the refusal must append no evidence row"

    order = read_survey_order(api, env["order_id"], CLAIMS_ADJUSTER)
    assert order["status"] == "APPOINTED"
    assert order.get("report_reference") is None

    # The appointed surveyor files the identical report successfully.
    filed = validate_success(api.file_survey_report(
        env["order_id"],
        {"packaging_compliant": True, "report_reference": "SR-RIGHTFUL",
         "damage_percentage_found": 12.5},
        make_surveyor_headers(env["surveyor_one_id"])))
    assert filed["status"] == "REPORT_FILED"
    assert filed["report_reference"] == "SR-RIGHTFUL"

    documents, meta = validate_paginated(
        api.list_claim_documents(env["claim_id"], CLAIMS_ADJUSTER))
    assert meta["total_count"] == 1
    assert documents[0]["origin"] == "SURVEYOR"

    intruder_row = read_surveyor(api, env["surveyor_two_id"], COMPLIANCE_OFFICER)
    assert intruder_row["booked_minutes_total"] == 0, (
        "the intruder's calendar must never have been touched"
    )

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "SURVEY_RECEIVED"


# ---------------------------------------------------------------------------
# Segregation of duties on the premium audit
# ---------------------------------------------------------------------------
def test_the_premium_submitter_may_not_audit_its_own_declaration(
        api: ApiClient) -> None:
    """The audit gate is on the acting identity, not on the role.

    The auditor may not be the principal who submitted the declaration: an `X-User-ID` equal to the stored `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

    Design: Corner/rbac/premium_audit_segregation_refuses_the_submitting_user_as_auditor
    """
    env = build_submitted_declaration(
        api, declared_premium_total=EXPECTED_TOTAL_PREMIUM)
    declaration_id = env["declaration_id"]
    submitted = env["declaration"]

    assert submitted["submitted_by_user_id"] == env["policy_id"]
    assert_money(submitted["computed_premium_total"], EXPECTED_TOTAL_PREMIUM,
                 "computed_premium_total")
    assert submitted["certificate_count"] == 1
    assert_money(submitted["variance_amount"], 0.00, "variance_amount")

    # A premium auditor whose acting identity is the submitter's is refused.
    validate_error(
        api.start_declaration_audit(
            declaration_id, make_headers(env["policy_id"], ROLE_PREMIUM_AUDITOR)),
        ERR_SEGREGATION_OF_DUTIES)

    mid = read_declaration(api, declaration_id, PREMIUM_AUDITOR)
    assert mid["status"] == "SUBMITTED"
    assert mid.get("auditor_user_id") is None, (
        "the refused audit must store no auditor"
    )

    opened = validate_success(
        api.start_declaration_audit(declaration_id, PREMIUM_AUDITOR))
    assert opened["status"] == "UNDER_AUDIT"
    assert opened["auditor_user_id"] == AUDITOR_USER_ID

    closed = validate_success(api.finish_declaration_audit(
        declaration_id, PREMIUM_AUDITOR,
        {"audit_note": "Nil variance, accepted"}))
    assert closed["status"] == "ACCEPTED"
    assert_money(closed["audit_adjustment_amount"], 0.00,
                 "audit_adjustment_amount")
    assert closed["submission_count"] == 1, (
        "the refused audit must not count as a resubmission"
    )


# ---------------------------------------------------------------------------
# Segregation of duties on the settlement
# ---------------------------------------------------------------------------
def test_the_adjusting_adjuster_may_not_settle_the_claim_it_adjusted(
        api: ApiClient) -> None:
    """Four eyes on the money: the adjuster who quantified the loss may not pay it.

    Settling an `ADJUSTED` claim is a `ClaimsAdjuster` action, and it must be a different adjuster: an acting `X-User-ID` equal to the recorded `adjusted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`.

    Design: Corner/rbac/claim_settlement_segregation_refuses_the_adjusting_user_as_settler
    """
    env = build_adjusted_claim(api)
    claim_id = env["claim_id"]

    assert env["claim"]["adjusted_by_user_id"] == ADJUSTER_USER_ID
    assert_money(env["claim"]["adjusted_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "adjusted_amount")

    validate_error(api.settle_claim_file(claim_id, CLAIMS_ADJUSTER),
                   ERR_SEGREGATION_OF_DUTIES)

    mid = read_claim_file(api, claim_id, CLAIMS_ADJUSTER)
    assert mid["status"] == "ADJUSTED"
    assert mid.get("settled_amount") is None, (
        "nothing may be paid on the refused attempt"
    )
    assert mid.get("settled_by_user_id") is None

    settled = validate_success(api.settle_claim_file(claim_id, CLAIMS_ADJUSTER_2))
    assert settled["status"] == "SETTLED"
    assert_money(settled["settled_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "settled_amount")
    assert_money(settled["net_loss_amount"],
                 EXPECTED_CLAIM_ADJUSTED_DEPRECIATION, "net_loss_amount")
    assert settled["settled_by_user_id"] == ADJUSTER_2_USER_ID

    assert read_certificate(api, env["certificate_id"])["status"] == "CLAIMED", (
        "settlement does not end the certificate's transit"
    )


# ---------------------------------------------------------------------------
# Port creation is shared; re-tiering is not
# ---------------------------------------------------------------------------
def test_both_the_underwriter_and_the_compliance_officer_register_ports(
        api: ApiClient) -> None:
    """The shared grant on port registration is symmetric between the two writers.

    A port may be registered by an `Underwriter` or a `ComplianceOfficer` with its `unlocode` (unique across all ports and exactly five characters), its `name`, its two-letter ISO `country_code` and its `port_accumulation_limit_amount`, greater than zero, being the largest aggregate insured value permitted at that port for any overlapping storage window.

    Design: Corner/rbac/port_creation_is_shared_between_underwriter_and_compliance_officer
    """
    by_underwriter = get_success_data(
        api.create_port(dict(PORT_SGSIN), UNDERWRITER), 201)
    assert by_underwriter["war_risk_tier"] == "GREEN"
    assert_rate(by_underwriter["war_rate_multiplier"], 1.0,
                label="green war_rate_multiplier")

    amber = dict(PORT_NLRTM)
    amber["war_risk_tier"] = "AMBER"
    by_compliance = get_success_data(
        api.create_port(amber, COMPLIANCE_OFFICER), 201)
    assert by_compliance["war_risk_tier"] == "AMBER"
    assert_rate(by_compliance["war_rate_multiplier"], 1.5,
                label="amber war_rate_multiplier")

    _, meta = validate_paginated(api.list_ports(PLATFORM_ADMIN))
    assert meta["total_count"] == 2


def test_no_other_role_may_register_a_port(api: ApiClient) -> None:
    """Neither the read-everywhere admin nor an assured may write to the register.

    If both headers are well formed but the named role is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/port_creation_is_shared_between_underwriter_and_compliance_officer
    """
    validate_error(api.create_port(dict(PORT_USNYC), PLATFORM_ADMIN),
                   ERR_UNAUTHORIZED)

    sydney = dict(PORT_NLRTM)
    sydney.update({"unlocode": "AUSYD", "name": "Sydney", "country_code": "AU"})
    validate_error(
        api.create_port(sydney, make_headers("not-a-policy", ROLE_ASSURED)),
        ERR_UNAUTHORIZED)

    _, meta = validate_paginated(api.list_ports(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "neither refused request may create a port"


def test_only_the_compliance_officer_may_re_tier_a_port(api: ApiClient) -> None:
    """A shared create does not imply a shared update: re-tiering stays exclusive.

    In this system that designation is a `ComplianceOfficer` re-tiering a port by supplying a new `war_risk_tier`.

    Design: Corner/rbac/port_creation_is_shared_between_underwriter_and_compliance_officer
    """
    port = get_success_data(api.create_port(dict(PORT_SGSIN), UNDERWRITER), 201)

    validate_error(
        api.set_port_war_risk_tier(port["id"], {"war_risk_tier": "AMBER"},
                                   UNDERWRITER),
        ERR_UNAUTHORIZED)
    unchanged = read_port(api, port["id"])
    assert unchanged["war_risk_tier"] == "GREEN"
    assert unchanged["version"] == port["version"]

    re_tiered = validate_success(api.set_port_war_risk_tier(
        port["id"], {"war_risk_tier": "AMBER"}, COMPLIANCE_OFFICER))
    assert re_tiered["war_risk_tier"] == "AMBER"
    assert_rate(re_tiered["war_rate_multiplier"], 1.5,
                label="amber war_rate_multiplier")
