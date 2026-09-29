"""Who may act, on whose behalf, and which statutory switches open or close a path.

This module exercises the access-control layer of the annexation record — role
exclusivity, municipal and owner scope, the segregation-of-duties bar between
the fiscal analyst and the boundary commission, and the authentication gate that
outranks every other check — together with the revision guards on the two
supersession-prone creates and the three statute flags that rewrite the tail of
the lifecycle.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    boundary_commissioner_headers,
    constants,
    factories,
    fiscal_analyst_headers,
    fixtures,
    get_success_data,
    make_city_clerk_headers,
    make_headers,
    make_municipal_planner_headers,
    make_property_owner_headers,
    state_law_admin_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import (
    ERR_COMMISSION_APPROVAL_REQUIRED,
    ERR_DE_ANNEXATION_NOT_ALLOWED,
    ERR_MSD_ALTERNATIVE_NOT_ALLOWED,
    ERR_MUNICIPALITY_SCOPE_VIOLATION,
    ERR_OWNER_SCOPE_VIOLATION,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CASE_VERSION,
    ERR_STALE_PLAN_VERSION,
    ERR_UNAUTHENTICATED,
)

# One operator identifier used first as a FiscalAnalyst and then as a
# BoundaryCommissioner, so that both role checks pass and only the
# segregation-of-duties comparison can refuse the decision.
DUAL_ROLE_OPERATOR_ID = "55555555-5555-4555-8555-555555555555"

# A request carrying no operator identity at all: neither X-User-ID nor
# X-User-Role, only the content type.
_NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}


def _jurisdiction_overrides(**statute_flags):
    """Statute and municipality overrides that share one state code, because a
    municipality's `state_code` must equal its statute profile's."""
    state_code = factories.unique_state_code()
    statute = dict(statute_flags)
    statute["state_code"] = state_code
    return statute, {"state_code": state_code}


def _standing_jurisdiction(api, **statute_flags):
    """A published statute profile and one municipality registered under it."""
    statute_overrides, municipality_overrides = _jurisdiction_overrides(**statute_flags)
    statute = fixtures.create_statute(api, **statute_overrides)
    municipality = fixtures.create_municipality(
        api, statute["id"], **municipality_overrides
    )
    return statute, municipality


def _list_records(api, path, **filters):
    """Read a collection as a StateLawAdmin; list endpoints are open to every
    role, and an opaque operator identifier is never scope-compared."""
    response = api.client.get(
        path, headers=state_law_admin_headers(), params=filters or None
    )
    return validate_paginated(response)


def _get_without_identity(api, path):
    response = api.client.get(path, headers=_NO_IDENTITY_HEADERS)
    return response


# ==========================================================================
# Role exclusivity: an operation reserved to one role refuses every other
# ==========================================================================
def test_a_planner_cannot_certify_petition_sufficiency(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles listed for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=[100000000],
    )
    fixtures.open_petition(api, ctx)

    # Certifying sufficiency is the clerk's act; the petition is genuinely
    # circulating, so only the role can explain a refusal.
    response = api.certify_sufficiency(fixtures.planner(ctx), ctx["petition"]["id"])
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    petition = fixtures.read_petition(
        api, ctx["municipality"]["id"], ctx["petition"]["id"]
    )
    assert petition["sufficiency_status"] == "CIRCULATING"


def test_a_clerk_cannot_open_an_annexation_case(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles listed for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    _statute, municipality = _standing_jurisdiction(api)
    payload = factories.annexation_case_payload(
        municipality["id"], method="PETITION_MAJORITY"
    )

    # The clerk acts for the right city with a well-formed body; opening a case
    # is nonetheless reserved to the planning officer.
    response = api.create_annexation_case(
        make_city_clerk_headers(municipality["id"]), payload
    )
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    _records, meta = _list_records(
        api, "/annexation-cases", municipality_id=municipality["id"]
    )
    assert meta["total_count"] == 0


def test_a_property_owner_cannot_open_an_annexation_case(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles listed for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    _statute, municipality = _standing_jurisdiction(api)
    owner = fixtures.create_owner(api)
    payload = factories.annexation_case_payload(
        municipality["id"], method="PETITION_MAJORITY"
    )

    response = api.create_annexation_case(
        make_property_owner_headers(owner["id"]), payload
    )
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    _records, meta = _list_records(
        api, "/annexation-cases", municipality_id=municipality["id"]
    )
    assert meta["total_count"] == 0


def test_a_clerk_cannot_author_the_fiscal_impact_analysis(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles listed for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )

    # The revision guard carries the case's current version, so the refusal
    # cannot be blamed on a stale read.
    payload = factories.fiscal_analysis_payload(
        ctx["case"]["id"], fixtures.case_version(api, ctx), projected_population=5
    )
    response = api.create_fiscal_impact_analysis(fixtures.clerk(ctx), payload)
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    _records, meta = _list_records(
        api, "/fiscal-impact-analyses", annexation_case_id=ctx["case"]["id"]
    )
    assert meta["total_count"] == 0


def test_a_planner_cannot_post_the_municipal_tax_roll(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles listed for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )

    # Posting the roll belongs to the county assessor. The role check precedes
    # the case-state check, so a 403 rather than a 409 is the answer even though
    # this case is nowhere near effective.
    response = api.post_tax_roll(fixtures.planner(ctx), ctx["case"]["id"])
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "TERRITORY_CERTIFIED"
    assert case["tax_roll_status"] == "NOT_TRANSFERRED"


# ==========================================================================
# Municipal scope: a peer city's clerk is still a stranger to this case
# ==========================================================================
def test_a_foreign_clerk_cannot_schedule_a_hearing_on_another_citys_case(api):
    """PRD §2.1: "A mismatch is rejected with
    `ERR_MUNICIPALITY_SCOPE_VIOLATION` (HTTP 403). This scope check guards every
    municipal write: case creation and every case-level action, parcel addition
    and exclusion, petition creation and certification, plan creation and
    adoption, commitment creation, activation and voiding, hearing scheduling,
    notice publication, holding and protest closure, utility account
    registration, and service provider registration."

    Design: Corner/rbac/a_clerk_of_another_municipality_cannot_act_on_this_municipalitys_case
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    neighbour = fixtures.create_municipality(api, ctx["statute"]["id"], **municipality)

    # The payload names the owning city correctly; the isolation is by acting
    # operator identity, not by payload.
    payload = factories.public_hearing_payload(
        ctx["case"]["id"], ctx["municipality"]["id"]
    )
    response = api.create_public_hearing(
        make_city_clerk_headers(neighbour["id"]), payload
    )
    validate_error(response, ERR_MUNICIPALITY_SCOPE_VIOLATION)

    _records, meta = _list_records(
        api, "/public-hearings", annexation_case_id=ctx["case"]["id"]
    )
    assert meta["total_count"] == 0


def test_a_foreign_clerk_cannot_adopt_another_citys_plan_of_services(api):
    """PRD §2.1: "A mismatch is rejected with
    `ERR_MUNICIPALITY_SCOPE_VIOLATION` (HTTP 403). This scope check guards every
    municipal write: case creation and every case-level action, parcel addition
    and exclusion, petition creation and certification, plan creation and
    adoption, commitment creation, activation and voiding, hearing scheduling,
    notice publication, holding and protest closure, utility account
    registration, and service provider registration."

    Design: Corner/rbac/a_clerk_of_another_municipality_cannot_act_on_this_municipalitys_case
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    neighbour = fixtures.create_municipality(api, ctx["statute"]["id"], **municipality)
    fixtures.open_plan(api, ctx)

    # The plan reaches its municipality only transitively, through the case.
    response = api.adopt_plan_of_services(
        make_city_clerk_headers(neighbour["id"]), ctx["plan"]["id"]
    )
    validate_error(response, ERR_MUNICIPALITY_SCOPE_VIOLATION)

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["adoption_status"] == "DRAFT"


def test_a_foreign_planner_cannot_add_a_parcel_to_another_citys_case(api):
    """PRD §2.1: "A mismatch is rejected with
    `ERR_MUNICIPALITY_SCOPE_VIOLATION` (HTTP 403). This scope check guards every
    municipal write: case creation and every case-level action, parcel addition
    and exclusion, petition creation and certification, plan creation and
    adoption, commitment creation, activation and voiding, hearing scheduling,
    notice publication, holding and protest closure, utility account
    registration, and service provider registration."

    Design: Corner/rbac/a_clerk_of_another_municipality_cannot_act_on_this_municipalitys_case
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_draft_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    neighbour = fixtures.create_municipality(api, ctx["statute"]["id"], **municipality)

    # The case is still DRAFT, so the addition is admissible in every respect
    # except the identity of the operator attempting it.
    payload = factories.parcel_payload(
        ctx["owners"][0]["id"], assessed_value_cents=10000000, acreage=1.00
    )
    response = api.create_parcel(
        make_municipal_planner_headers(neighbour["id"]), ctx["case"]["id"], payload
    )
    validate_error(response, ERR_MUNICIPALITY_SCOPE_VIOLATION)

    _records, meta = _list_records(
        api, "/parcels", annexation_case_id=ctx["case"]["id"]
    )
    assert meta["total_count"] == 1


# ==========================================================================
# Owner scope: the PropertyOwner role is self-scoped
# ==========================================================================
def test_an_owner_cannot_sign_a_consent_naming_another_owner(api):
    """PRD §2.1: "On consent creation and on protest filing creation,
    `X-User-ID` must equal the `property_owner_id` supplied in the payload; on
    withdrawal of a consent or a filing, it must equal the `property_owner_id`
    recorded on the target `ParcelOwnerConsent` or `ProtestFiling`. A mismatch
    is rejected with `ERR_OWNER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/an_owner_cannot_sign_or_protest_on_behalf_of_another_owner
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=[50000000, 50000000],
    )
    fixtures.open_petition(api, ctx)

    # The named owner genuinely owns the named parcel and the petition is
    # genuinely circulating; only the acting operator is wrong.
    payload = factories.consent_payload(
        ctx["petition"]["id"], ctx["parcels"][0]["id"], ctx["owners"][0]["id"], 100.00
    )
    response = api.create_consent(
        make_property_owner_headers(ctx["owners"][1]["id"]), payload
    )
    validate_error(response, ERR_OWNER_SCOPE_VIOLATION)

    _records, meta = _list_records(
        api, "/parcel-owner-consents", petition_id=ctx["petition"]["id"]
    )
    assert meta["total_count"] == 0


def test_an_owner_cannot_withdraw_another_owners_consent(api):
    """PRD §2.1: "On consent creation and on protest filing creation,
    `X-User-ID` must equal the `property_owner_id` supplied in the payload; on
    withdrawal of a consent or a filing, it must equal the `property_owner_id`
    recorded on the target `ParcelOwnerConsent` or `ProtestFiling`. A mismatch
    is rejected with `ERR_OWNER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/an_owner_cannot_sign_or_protest_on_behalf_of_another_owner
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=[50000000, 50000000],
    )
    fixtures.open_petition(api, ctx)
    consent = fixtures.sign_consent(api, ctx, parcel_index=0)

    response = api.withdraw_consent(
        make_property_owner_headers(ctx["owners"][1]["id"]), consent["id"]
    )
    validate_error(response, ERR_OWNER_SCOPE_VIOLATION)

    stored = get_success_data(
        api.get_consent(make_property_owner_headers(ctx["owners"][0]["id"]), consent["id"])
    )
    assert stored["consent_status"] == "SIGNED"
    assert stored["qualified_value_cents"] == 50000000


def test_an_owner_cannot_file_a_protest_naming_another_owner(api):
    """PRD §2.1: "On consent creation and on protest filing creation,
    `X-User-ID` must equal the `property_owner_id` supplied in the payload; on
    withdrawal of a consent or a filing, it must equal the `property_owner_id`
    recorded on the target `ParcelOwnerConsent` or `ProtestFiling`. A mismatch
    is rejected with `ERR_OWNER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/an_owner_cannot_sign_or_protest_on_behalf_of_another_owner
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[50000000, 50000000],
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)

    # Inside the written-objection window, so the filing is refused on identity
    # rather than on the clock.
    fixtures.set_clock(api, constants.CLOCK_DURING_PROTEST_WINDOW)
    payload = factories.protest_filing_payload(
        ctx["hearing"]["id"], ctx["parcels"][0]["id"], ctx["owners"][0]["id"], 100.00
    )
    response = api.create_protest_filing(
        make_property_owner_headers(ctx["owners"][1]["id"]), payload
    )
    validate_error(response, ERR_OWNER_SCOPE_VIOLATION)

    _records, meta = _list_records(
        api, "/protest-filings", public_hearing_id=ctx["hearing"]["id"]
    )
    assert meta["total_count"] == 0


# ==========================================================================
# Segregation of duties on the commission decision
# ==========================================================================
def test_the_analyst_who_finalized_the_numbers_cannot_decide_as_the_commission(api):
    """PRD §2.1: "The `BoundaryCommissioner` deciding a case must not be the
    operator who finalized that case's analysis of record: if the commissioner's
    `X-User-ID` equals the case's `fiscal_finalized_by_user_id`, the decision is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_operator_who_finalized_the_fiscal_analysis_cannot_decide_as_the_commission
    """
    statute, municipality = _jurisdiction_overrides(boundary_commission_required=True)
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[100000000],
        analyst_user_id=DUAL_ROLE_OPERATOR_ID,
    )
    assert ctx["analysis"]["finalized_by_user_id"] == DUAL_ROLE_OPERATOR_ID

    adopted = fixtures.adopt_ordinance(api, ctx)
    assert adopted["commission_review_status"] == "PENDING"
    submitted = get_success_data(
        api.submit_to_commission(fixtures.planner(ctx), ctx["case"]["id"])
    )
    assert submitted["status"] == "COMMISSION_REVIEW"

    # The same opaque operator now declares the commissioner role, so both role
    # and state checks pass and only the duties bar can refuse.
    response = api.commission_decision(
        boundary_commissioner_headers(DUAL_ROLE_OPERATOR_ID),
        ctx["case"]["id"],
        "APPROVED",
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES)

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "COMMISSION_REVIEW"
    assert case["commission_review_status"] == "PENDING"
    assert case["fiscal_finalized_by_user_id"] == DUAL_ROLE_OPERATOR_ID


def test_a_commissioner_who_did_not_finalize_the_numbers_may_approve(api):
    """PRD §3.7: "The case must be in `COMMISSION_REVIEW`, or
    `ERR_CASE_STATE_INVALID` is returned, with `commission_review_status` still
    `PENDING`, or `ERR_COMMISSION_REVIEW_NOT_PENDING` is returned, and the
    commissioner's `X-User-ID` must differ from the case's
    `fiscal_finalized_by_user_id` or the decision is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_operator_who_finalized_the_fiscal_analysis_cannot_decide_as_the_commission
    """
    statute, municipality = _jurisdiction_overrides(boundary_commission_required=True)
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[100000000],
        analyst_user_id=DUAL_ROLE_OPERATOR_ID,
    )
    fixtures.adopt_ordinance(api, ctx)
    get_success_data(api.submit_to_commission(fixtures.planner(ctx), ctx["case"]["id"]))

    # A different commissioner deciding the very same case proves the block is
    # on the operator and not on the case.
    decided = get_success_data(
        api.commission_decision(
            boundary_commissioner_headers(), ctx["case"]["id"], "APPROVED"
        )
    )
    assert decided["status"] == "COMMISSION_APPROVED"
    assert decided["commission_review_status"] == "APPROVED"


# ==========================================================================
# Authentication outranks every other check
# ==========================================================================
def test_a_read_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is any string
    other than those seven, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_requests_are_rejected_before_any_other_check
    """
    _statute, municipality = _standing_jurisdiction(api)

    response = _get_without_identity(api, f"/municipalities/{municipality['id']}")
    validate_error(response, ERR_UNAUTHENTICATED)


def test_a_write_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is any string
    other than those seven, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_requests_are_rejected_before_any_other_check
    """
    _statute, municipality = _standing_jurisdiction(api)
    payload = factories.annexation_case_payload(municipality["id"])

    response = api.raw_post(
        "/annexation-cases", payload, headers=_NO_IDENTITY_HEADERS
    )
    validate_error(response, ERR_UNAUTHENTICATED)

    _records, meta = _list_records(
        api, "/annexation-cases", municipality_id=municipality["id"]
    )
    assert meta["total_count"] == 0


def test_a_missing_header_outranks_an_unresolvable_path_identifier(api):
    """PRD §2.10: "Because many endpoints in this domain stack half a dozen
    checks, the precedence between them is fixed rather than incidental. Checks
    are evaluated in the following order, and the first one that fails is the
    one reported:" — with header presence and role recognition first and path
    identifier resolution sixth.

    Design: Corner/rbac/unauthenticated_requests_are_rejected_before_any_other_check
    """
    _standing_jurisdiction(api)

    # Authenticated, this read would answer ERR_CASE_NOT_FOUND; unauthenticated,
    # the higher-precedence check wins.
    response = _get_without_identity(api, f"/annexation-cases/{NON_EXISTENT_UUID}")
    validate_error(response, ERR_UNAUTHENTICATED)


def test_an_unrecognized_role_string_outranks_an_unresolvable_reference(api):
    """PRD §2.1: "Seven roles are recognized, spelled exactly as follows:
    `StateLawAdmin`, `MunicipalPlanner`, `CityClerk`, `PropertyOwner`,
    `FiscalAnalyst`, `BoundaryCommissioner`, and `CountyAssessor`. If either
    header is absent, or if `X-User-Role` is any string other than those seven,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_requests_are_rejected_before_any_other_check
    """
    _statute, municipality = _standing_jurisdiction(api)

    # "Mayor" is not one of the seven, and the body names a municipality that
    # does not exist — the role recognition check still reports first.
    headers = make_headers(municipality["id"], "Mayor")
    payload = factories.annexation_case_payload(NON_EXISTENT_UUID)
    response = api.create_annexation_case(headers, payload)
    validate_error(response, ERR_UNAUTHENTICATED)


# ==========================================================================
# The one shared pair of operations: recording and withdrawing a signature
# ==========================================================================
def test_both_the_owner_and_the_clerk_may_record_a_signature(api):
    """PRD §2.1: "A `CityClerk` may perform these same four operations on any
    owner's behalf — clerks transcribe paper filings — and is therefore not
    subject to the owner-scope comparison, only to the municipality-scope one."
    PRD §3.3: "`qualified_signature_assessed_value_cents` is the exact integer
    sum of the qualifying consents' already-rounded `qualified_value_cents`, and
    `qualified_signature_owner_count` is the number of distinct
    `property_owner_id` values among them."

    Design: Corner/rbac/both_the_owner_and_the_clerk_may_use_the_shared_consent_operations
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=[50000000, 50000000],
    )
    fixtures.open_petition(api, ctx)

    signed_by_owner = get_success_data(
        api.create_consent(
            make_property_owner_headers(ctx["owners"][0]["id"]),
            factories.consent_payload(
                ctx["petition"]["id"],
                ctx["parcels"][0]["id"],
                ctx["owners"][0]["id"],
                100.00,
            ),
        ),
        201,
    )
    # The clerk transcribes a walk-in signature for a different owner.
    transcribed_by_clerk = get_success_data(
        api.create_consent(
            fixtures.clerk(ctx),
            factories.consent_payload(
                ctx["petition"]["id"],
                ctx["parcels"][1]["id"],
                ctx["owners"][1]["id"],
                100.00,
            ),
        ),
        201,
    )

    assert signed_by_owner["qualified_value_cents"] == 50000000
    assert transcribed_by_clerk["qualified_value_cents"] == 50000000

    petition = fixtures.read_petition(
        api, ctx["municipality"]["id"], ctx["petition"]["id"]
    )
    assert petition["qualified_signature_assessed_value_cents"] == 100000000
    assert petition["qualified_signature_owner_count"] == 2


def test_the_clerk_may_withdraw_a_signature_the_owner_recorded(api):
    """PRD §3.3: "Withdrawal sets `consent_status` to `WITHDRAWN`, stamps
    `withdrawn_at` from the clock, and resets that consent's
    `qualified_value_cents` to 0 so it stops contributing."

    Design: Corner/rbac/both_the_owner_and_the_clerk_may_use_the_shared_consent_operations
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=[50000000, 50000000],
    )
    fixtures.open_petition(api, ctx)
    owner_consent = fixtures.sign_consent(api, ctx, parcel_index=0)
    fixtures.sign_consent(api, ctx, parcel_index=1)

    withdrawn = get_success_data(
        api.withdraw_consent(fixtures.clerk(ctx), owner_consent["id"])
    )
    assert withdrawn["consent_status"] == "WITHDRAWN"
    assert withdrawn["qualified_value_cents"] == 0

    petition = fixtures.read_petition(
        api, ctx["municipality"]["id"], ctx["petition"]["id"]
    )
    assert petition["qualified_signature_assessed_value_cents"] == 50000000


# ==========================================================================
# Optimistic concurrency on the case revision
# ==========================================================================
def test_a_stale_case_version_refuses_the_fiscal_analysis(api):
    """PRD §2.8: "`POST /fiscal-impact-analyses` requires a non-optional
    `expected_case_version` field carrying the `version` of the target
    `AnnexationCase` as the client last observed it. If that value does not
    equal the case's current `version`, the create is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/a_stale_expected_case_version_on_a_fiscal_analysis_is_rejected
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_draft_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    observed_version = fixtures.case_version(api, ctx)

    # A certification the analyst never saw invalidates the version he read.
    certified = get_success_data(
        api.certify_territory(fixtures.planner(ctx), ctx["case"]["id"])
    )
    assert certified["version"] == observed_version + 1

    payload = factories.fiscal_analysis_payload(
        ctx["case"]["id"], observed_version, projected_population=5
    )
    response = api.create_fiscal_impact_analysis(fiscal_analyst_headers(), payload)
    validate_error(response, ERR_STALE_CASE_VERSION)

    # The refused write left neither an analysis nor a version bump behind.
    assert fixtures.case_version(api, ctx) == certified["version"]
    _records, meta = _list_records(
        api, "/fiscal-impact-analyses", annexation_case_id=ctx["case"]["id"]
    )
    assert meta["total_count"] == 0


def test_the_current_case_version_admits_the_fiscal_analysis(api):
    """PRD §2.8: "`POST /fiscal-impact-analyses` requires a non-optional
    `expected_case_version` field carrying the `version` of the target
    `AnnexationCase` as the client last observed it. If that value does not
    equal the case's current `version`, the create is rejected with
    `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/a_stale_expected_case_version_on_a_fiscal_analysis_is_rejected
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )

    # Re-read the case and quote the version it actually carries: the identical
    # body that a stale quote would lose is admitted.
    payload = factories.fiscal_analysis_payload(
        ctx["case"]["id"], fixtures.case_version(api, ctx), projected_population=5
    )
    analysis = get_success_data(
        api.create_fiscal_impact_analysis(fiscal_analyst_headers(), payload), 201
    )
    assert analysis["annexation_case_id"] == ctx["case"]["id"]
    assert analysis["status"] == "DRAFT"

    _records, meta = _list_records(
        api, "/fiscal-impact-analyses", annexation_case_id=ctx["case"]["id"]
    )
    assert meta["total_count"] == 1


# ==========================================================================
# Optimistic concurrency on the plan revision
# ==========================================================================
def test_a_stale_plan_version_refuses_the_service_commitment(api):
    """PRD §2.8: "`POST /service-commitments` requires a non-optional
    `expected_plan_of_services_version` field carrying the `version` of the
    target `PlanOfServices` as the client last observed it. If that value does
    not equal the plan's current `version`, the create is rejected with
    `ERR_STALE_PLAN_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/a_stale_expected_plan_version_on_a_service_commitment_is_rejected
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    fixtures.open_plan(api, ctx)
    observed_version = fixtures.plan_version(api, ctx)

    # The first commitment spends the version the plan was created with.
    first = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        window_start_date="2026-08-01",
        window_end_date="2026-09-15",
        cost_cents=500000,
        committed_account_count=0,
    )

    payload = factories.service_commitment_payload(
        ctx["plan"]["id"],
        ctx["provider"]["id"],
        "POLICE",
        observed_version,
        window_start_date="2026-08-01",
        window_end_date="2026-09-10",
        cost_cents=400000,
        committed_account_count=0,
    )
    response = api.create_service_commitment(fixtures.planner(ctx), payload)
    validate_error(response, ERR_STALE_PLAN_VERSION)

    assert fixtures.plan_version(api, ctx) == observed_version + 1
    surviving = fixtures.read_commitment(
        api, ctx["municipality"]["id"], first["id"]
    )
    assert surviving["commitment_status"] == "DRAFT"


def test_the_current_plan_version_admits_the_superseding_commitment(api):
    """PRD §2.8: "The guard exists because a new commitment voids the plan's
    existing draft commitment for the same service type; a writer holding a
    stale view of the plan would destroy a commitment authored after its read."

    Design: Corner/complexity_layers/a_stale_expected_plan_version_on_a_service_commitment_is_rejected
    """
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_certified_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    fixtures.open_plan(api, ctx)
    first = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        window_start_date="2026-08-01",
        window_end_date="2026-09-15",
        cost_cents=500000,
        committed_account_count=0,
    )

    # Re-reading the plan yields the version the first commitment produced, and
    # the second write goes through — superseding the draft it was guarding.
    payload = factories.service_commitment_payload(
        ctx["plan"]["id"],
        ctx["provider"]["id"],
        "POLICE",
        fixtures.plan_version(api, ctx),
        window_start_date="2026-08-01",
        window_end_date="2026-09-10",
        cost_cents=400000,
        committed_account_count=0,
    )
    second = get_success_data(
        api.create_service_commitment(fixtures.planner(ctx), payload), 201
    )
    assert second["commitment_status"] == "DRAFT"
    assert fixtures.read_commitment(api, ctx["municipality"]["id"], first["id"])[
        "commitment_status"
    ] == "VOIDED"


# ==========================================================================
# The boundary-commission flag
# ==========================================================================
def test_effectuation_is_locked_while_the_commission_review_is_pending(api):
    """PRD §3.8: "Where the statute's `boundary_commission_required` is true,
    `commission_review_status` must be `APPROVED`, or the request is refused
    with `ERR_COMMISSION_APPROVAL_REQUIRED`; where the statute does not require
    commission review, no such check applies."

    Design: Corner/complexity_layers/the_commission_flag_locks_effectuation_until_the_commission_approves
    """
    statute, municipality = _jurisdiction_overrides(boundary_commission_required=True)
    ctx = fixtures.setup_case_ready_for_ordinance(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )

    adopted = fixtures.adopt_ordinance(api, ctx)
    assert adopted["status"] == "ORDINANCE_ADOPTED"
    # Stamped by the statute flag, not by anything in the request.
    assert adopted["commission_review_status"] == "PENDING"

    response = api.effectuate(
        fixtures.planner(ctx),
        ctx["case"]["id"],
        constants.EFFECTIVE_DATE_AFTER_PROTEST,
    )
    validate_error(response, ERR_COMMISSION_APPROVAL_REQUIRED)

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "ORDINANCE_ADOPTED"
    parcel = fixtures.read_parcel(
        api, ctx["municipality"]["id"], ctx["parcels"][0]["id"]
    )
    assert parcel["parcel_status"] == "PENDING_ANNEX"


def test_effectuation_is_admitted_once_the_commission_has_approved(api):
    """PRD §3.8: "Where the statute's `boundary_commission_required` is true,
    `commission_review_status` must be `APPROVED`, or the request is refused
    with `ERR_COMMISSION_APPROVAL_REQUIRED`; where the statute does not require
    commission review, no such check applies."

    Design: Corner/complexity_layers/the_commission_flag_locks_effectuation_until_the_commission_approves
    """
    statute, municipality = _jurisdiction_overrides(boundary_commission_required=True)
    ctx = fixtures.setup_case_ready_for_ordinance(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    fixtures.adopt_ordinance(api, ctx)

    submitted = get_success_data(
        api.submit_to_commission(fixtures.planner(ctx), ctx["case"]["id"])
    )
    assert submitted["status"] == "COMMISSION_REVIEW"
    approved = get_success_data(
        api.commission_decision(
            boundary_commissioner_headers(), ctx["case"]["id"], "APPROVED"
        )
    )
    assert approved["status"] == "COMMISSION_APPROVED"
    assert approved["commission_review_status"] == "APPROVED"

    # The identical effectuate call that was refused now succeeds.
    effective = fixtures.effectuate(api, ctx, constants.EFFECTIVE_DATE_AFTER_PROTEST)
    assert effective["status"] == "EFFECTIVE"
    parcel = fixtures.read_parcel(
        api, ctx["municipality"]["id"], ctx["parcels"][0]["id"]
    )
    assert parcel["parcel_status"] == "INCORPORATED"


# ==========================================================================
# The de-annexation flag
# ==========================================================================
def test_a_de_annexation_case_is_refused_where_the_statute_forbids_it(api):
    """PRD §3.2: "Supplying a predecessor on an annexation case, omitting one on
    a de-annexation case, or opening a de-annexation case under a statute whose
    `de_annexation_allowed` is false all draw `ERR_DE_ANNEXATION_NOT_ALLOWED`."

    Design: Corner/complexity_layers/the_de_annexation_flag_off_rejects_a_de_annexation_case_at_creation
    """
    statute, municipality = _jurisdiction_overrides(de_annexation_allowed=False)
    # A real, already-effective annexation to unwind, so the predecessor is
    # beyond reproach and only the statute flag can explain a refusal.
    predecessor_ctx = fixtures.setup_effective_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    assert predecessor_ctx["case"]["status"] == "EFFECTIVE"

    payload = factories.de_annexation_case_payload(
        predecessor_ctx["municipality"]["id"], predecessor_ctx["case"]["id"]
    )
    response = api.create_annexation_case(fixtures.planner(predecessor_ctx), payload)
    validate_error(response, ERR_DE_ANNEXATION_NOT_ALLOWED)

    _records, meta = _list_records(
        api,
        "/annexation-cases",
        municipality_id=predecessor_ctx["municipality"]["id"],
        case_type="DE_ANNEXATION",
    )
    assert meta["total_count"] == 0


def test_a_de_annexation_case_opens_under_the_default_flag(api):
    """PRD §2.6: "`de_annexation_allowed` is a boolean defaulting to true that
    gates whether de-annexation cases may exist under the statute at all."

    Design: Corner/complexity_layers/the_de_annexation_flag_off_rejects_a_de_annexation_case_at_creation
    """
    # The flag is left at its declared default, and nothing else about the
    # request changes.
    statute, municipality = _jurisdiction_overrides()
    predecessor_ctx = fixtures.setup_effective_case(
        api, statute=statute, municipality=municipality, parcel_values_cents=[100000000]
    )
    predecessor = predecessor_ctx["case"]
    assert predecessor["status"] == "EFFECTIVE"

    payload = factories.de_annexation_case_payload(
        predecessor_ctx["municipality"]["id"], predecessor["id"]
    )
    case = get_success_data(
        api.create_annexation_case(fixtures.planner(predecessor_ctx), payload), 201
    )
    assert case["case_type"] == "DE_ANNEXATION"
    assert case["predecessor_case_id"] == predecessor["id"]
    assert case["status"] == "DRAFT"

    _records, meta = _list_records(
        api, "/annexation-cases", predecessor_case_id=predecessor["id"]
    )
    assert meta["total_count"] == 1


# ==========================================================================
# The municipal-service-district flag
# ==========================================================================
def test_the_district_alternative_is_refused_where_the_statute_forbids_it(api):
    """PRD §3.6: "When `protest_pct` is at or above the statute's
    `protest_threshold_pct`, the hearing's `protest_outcome` moves
    `OPEN → SUSTAINED`, the hearing's `protest_pct` is stamped, the case mirrors
    both — `protest_pct` copied and `protest_outcome` set to `SUSTAINED` — and
    the case's `status` advances `HEARING_HELD → PROTEST_SUSTAINED`."
    PRD §3.9: "The statute's `msd_alternative_allowed` must be true, or the
    request is refused with `ERR_MSD_ALTERNATIVE_NOT_ALLOWED`, and the case must
    have an `ADOPTED` plan of services, or `ERR_PLAN_NOT_ADOPTED`."

    Design: Corner/complexity_layers/the_msd_flag_off_rejects_the_alternative_after_a_sustained_protest
    """
    statute, municipality = _jurisdiction_overrides(msd_alternative_allowed=False)
    # One 40,000,000-cent parcel objects out of a 100,000,000-cent territory, so
    # the protest is 40.00% against the default 20.00 threshold.
    ctx = fixtures.setup_protest_sustained_case(
        api,
        protesting_parcels=1,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[40000000, 30000000, 20000000, 10000000],
    )
    assert float(ctx["hearing"]["protest_pct"]) == 40.00
    assert ctx["hearing"]["protest_outcome"] == "SUSTAINED"
    assert ctx["case"]["status"] == "PROTEST_SUSTAINED"
    assert ctx["case"]["protest_outcome"] == "SUSTAINED"

    # PROTEST_SUSTAINED is exactly the state the district alternative exists to
    # rescue, and the flag closes that escape.
    response = api.adopt_msd_alternative(fixtures.clerk(ctx), ctx["case"]["id"])
    validate_error(response, ERR_MSD_ALTERNATIVE_NOT_ALLOWED)

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "PROTEST_SUSTAINED"


def test_the_district_alternative_is_adopted_under_the_default_flag(api):
    """PRD §3.9: "With the case in `PROTEST_SUSTAINED`, a `CityClerk` may adopt
    a municipal service district instead of the boundary change, advancing the
    case `PROTEST_SUSTAINED → MSD_ALTERNATIVE_ADOPTED`, which is terminal."

    Design: Corner/complexity_layers/the_msd_flag_off_rejects_the_alternative_after_a_sustained_protest
    """
    # The same sustained protest under a statute that leaves
    # `msd_alternative_allowed` at its declared default.
    statute, municipality = _jurisdiction_overrides()
    ctx = fixtures.setup_protest_sustained_case(
        api,
        protesting_parcels=1,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[40000000, 30000000, 20000000, 10000000],
    )
    assert ctx["case"]["status"] == "PROTEST_SUSTAINED"

    adopted = get_success_data(
        api.adopt_msd_alternative(fixtures.clerk(ctx), ctx["case"]["id"])
    )
    assert adopted["status"] == "MSD_ALTERNATIVE_ADOPTED"
