"""
Role-gate corners of the Digital Estate Fiduciary Access API.

Authorization here is two gates deep. The first asks whether the caller's role
appears among the endpoint's authorized roles at all; the second asks whether
that role owns the particular action submitted to a transitions endpoint. Both
sit in the first band of the rejection ladder, above every state check, and the
two entity-backed identities add a third, tenancy-scoped refusal on top.

Every test builds its own estate from scratch against an empty database whose
logical clock sits at the fresh-server epoch.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    factories as f,
    fixtures as fx,
    make_platform_compliance_headers,
    make_unknown_role_headers,
)
from test_helpers.api_errors import (
    ERR_ACTION_ROLE_MISMATCH,
    ERR_FIDUCIARY_ESTATE_MISMATCH,
    ERR_MISSING_AUTH_HEADERS,
    ERR_PLATFORM_SCOPE_MISMATCH,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    DECISION_APPROVED,
    DOC_ACTION_REVOKE,
    DOC_VERIFIED,
    REQUEST_DRAFT,
    REQUEST_SUBMITTED,
    REQUEST_UNDER_REVIEW,
    REQ_ACTION_DECIDE,
    REQ_ACTION_START_REVIEW,
    REQ_ACTION_SUBMIT,
)
from test_helpers.test_users import (
    EMPTY_USER_ID_HEADERS,
    MISSING_ROLE_HEADERS,
    NO_AUTH_HEADERS,
)


def _rbac_estate(api, case_number):
    """One provider, one authorized estate, one DRAFT catalogue-access request."""
    fx.set_clock(api, CLOCK_EPOCH)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, case_number)
    request = fx.draft_request(api, ctx, platform["id"], platform["form_code"])
    assert request["status"] == REQUEST_DRAFT
    return platform, ctx, request


@pytest.mark.parametrize(
    "attempt",
    [
        "open_an_estate_as_a_fiduciary",
        "register_a_provider_as_the_registry",
        "value_an_estate_as_the_service_operator",
        "revoke_letters_as_a_fiduciary",
        "sweep_expiries_as_a_fiduciary",
    ],
)
def test_a_role_missing_from_the_endpoints_list_is_refused_before_anything_else(api, attempt):
    """
    Five writes, each attempted by a recognised role the endpoint does not list,
    are all refused with ERR_ROLE_NOT_PERMITTED. The refusal lands before the
    estate concurrency token is even looked at — the valuation attempt carries a
    perfectly current expected_estate_version — and nothing it touched moved: the
    verified letters are still verified and the request is still a draft.

    PRD §2.1: A recognised role that is not listed among the target endpoint's authorized roles is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

    PRD §2.7: **Optimistic concurrency.** The estate-version check (`ERR_STALE_ESTATE_VERSION`, 412) then the asset-version check (`ERR_STALE_ASSET_VERSION`, 412).

    Design: Corner/rbac/role_gates_separate_the_endpoint_from_the_individual_action
    """
    platform, ctx, request = _rbac_estate(api, "PR-2737-C36A")

    if attempt == "open_an_estate_as_a_fiduciary":
        response = api.create_estate(
            f.estate_payload(
                decedent_name="Someone Else",
                date_of_death="2026-03-01",
                domicile_state="NV",
                court_case_number="PR-2737-C36A-X",
            ),
            ctx.fid_headers,
        )
    elif attempt == "register_a_provider_as_the_registry":
        response = api.create_platform(
            f.platform_payload(name="RogueVault", form_code="RV-FORM"),
            COURT_REGISTRAR_HEADERS,
        )
    elif attempt == "value_an_estate_as_the_service_operator":
        current_version = fx.estate_version(api, ctx)
        response = api.create_valuation_run(
            ctx.estate_id, f.valuation_run_payload(current_version), ESTATE_ADMIN_HEADERS
        )
    elif attempt == "revoke_letters_as_a_fiduciary":
        response = api.transition_document(
            ctx.letters_id,
            f.document_transition_payload(DOC_ACTION_REVOKE, revocation_reason="not my letters"),
            ctx.fid_headers,
        )
    else:
        response = api.run_grant_expiry_sweep(ctx.estate_id, ctx.fid_headers)

    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    assert fx.read_document(api, ctx, ctx.letters_id)["verification_status"] == DOC_VERIFIED
    assert fx.read_request(api, ctx, request["id"])["status"] == REQUEST_DRAFT
    assert platform["form_code"] == "CV-FORM-1"


@pytest.mark.parametrize(
    "attempt", ["decide_as_a_fiduciary", "submit_as_a_provider_desk"]
)
def test_an_action_its_role_does_not_own_is_refused_on_an_endpoint_it_may_use(api, attempt):
    """
    Both roles are authorized for the request transitions endpoint, yet neither
    owns the other's action: a fiduciary submitting DECIDE and a provider desk
    submitting SUBMIT are both refused with ERR_ACTION_ROLE_MISMATCH. The refusal
    is the action-ownership one and not a state conflict, even though the request
    is still a draft from which DECIDE is not defined at all.

    PRD §2.1: A caller whose role is authorized for the endpoint but does not own the submitted action — a `Fiduciary` submitting `DECIDE`, or a `PlatformCompliance` desk submitting `COUNTERSIGN` — is rejected with `ERR_ACTION_ROLE_MISMATCH` (HTTP 403).

    PRD §2.7: **Entity state.** Estate closure first (`ERR_ESTATE_CLOSED`, 409), then whether the target record is in a state from which the submitted action is defined, per entity in this order: document (`ERR_INVALID_DOCUMENT_STATE`), platform request (`ERR_INVALID_REQUEST_STATE`), authority grant (`ERR_INVALID_GRANT_STATE`), disposition election (`ERR_INVALID_ELECTION_STATE`), cancellation order (`ERR_INVALID_ORDER_STATE`), refund claim (`ERR_INVALID_CLAIM_STATE`), valuation run (`ERR_INVALID_RUN_STATE`) — all HTTP 409 — and lastly the once-per-estate finalization guard (`ERR_VALUATION_ALREADY_FINALIZED`, 409).

    Design: Corner/rbac/role_gates_separate_the_endpoint_from_the_individual_action
    """
    platform, ctx, request = _rbac_estate(api, "PR-2737-C36B")

    if attempt == "decide_as_a_fiduciary":
        response = api.transition_platform_request(
            request["id"],
            f.request_transition_payload(
                REQ_ACTION_DECIDE,
                decision=DECISION_APPROVED,
                decision_note="self-approval attempt",
            ),
            ctx.fid_headers,
        )
    else:
        response = api.transition_platform_request(
            request["id"],
            f.request_transition_payload(REQ_ACTION_SUBMIT),
            make_platform_compliance_headers(platform["id"]),
        )

    validate_error(response, ERR_ACTION_ROLE_MISMATCH)
    assert fx.read_request(api, ctx, request["id"])["status"] == REQUEST_DRAFT


@pytest.mark.parametrize(
    "identity", ["no_headers_at_all", "empty_user_id", "missing_role", "unrecognised_role"]
)
def test_a_malformed_identity_answers_401_ahead_of_every_403(api, identity):
    """
    The same DECIDE-as-a-fiduciary call that earns a 403 for action ownership
    never gets that far when the identity itself is malformed. Absent or empty
    headers report ERR_MISSING_AUTH_HEADERS and an unrecognised role name reports
    ERR_UNKNOWN_ROLE, both at HTTP 401, and the request stays a draft.

    PRD §2.1: If either header is absent or empty the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before the body is parsed and before any path parameter is resolved.

    PRD §2.1: If `X-User-Role` carries a string that is not one of the four recognised roles — `Fiduciary`, `PlatformCompliance`, `CourtRegistrar`, `EstateAdmin` — the request is rejected with `ERR_UNKNOWN_ROLE`, also HTTP 401: an unrecognised role is treated as an authentication failure, not as a permission failure.

    Design: Corner/rbac/role_gates_separate_the_endpoint_from_the_individual_action
    """
    _platform, ctx, request = _rbac_estate(api, "PR-2737-C36C")

    headers, expected_error = {
        "no_headers_at_all": (NO_AUTH_HEADERS, ERR_MISSING_AUTH_HEADERS),
        "empty_user_id": (EMPTY_USER_ID_HEADERS, ERR_MISSING_AUTH_HEADERS),
        "missing_role": (MISSING_ROLE_HEADERS, ERR_MISSING_AUTH_HEADERS),
        "unrecognised_role": (make_unknown_role_headers(), ERR_UNKNOWN_ROLE),
    }[identity]

    response = api.transition_platform_request(
        request["id"],
        f.request_transition_payload(
            REQ_ACTION_DECIDE, decision=DECISION_APPROVED, decision_note="anonymous approval"
        ),
        headers,
    )
    validate_error(response, expected_error)

    assert fx.read_request(api, ctx, request["id"])["status"] == REQUEST_DRAFT


def _two_estates_and_two_providers(api):
    """Providers P and Q, estate A with a SUBMITTED request on P, and estate B."""
    fx.set_clock(api, CLOCK_EPOCH)
    p = fx.register_platform(api, name="CloudVaultP", form_code="CVP-FORM")
    q = fx.register_platform(api, name="CloudVaultQ", form_code="CVQ-FORM")
    ctx_a = fx.authorized_estate(api, "PR-2737-C37A")
    ctx_b = fx.authorized_estate(
        api, "PR-2737-C37B",
        decedent_name="Noor Sadik", date_of_death="2026-03-02", domicile_state="NV",
    )
    request_a = fx.draft_request(api, ctx_a, p["id"], p["form_code"])
    submitted = fx.submit_request(api, ctx_a, request_a["id"])
    assert submitted["status"] == REQUEST_SUBMITTED
    return p, q, ctx_a, ctx_b, request_a


def test_a_fiduciary_of_another_estate_is_refused_on_both_a_create_and_the_close(api):
    """
    Estate B's fiduciary is a perfectly valid fiduciary, so the endpoint-level
    gate lets the role through — and the tenancy check then refuses both an
    inventory write and a closure attempt on estate A with
    ERR_FIDUCIARY_ESTATE_MISMATCH. The closure refusal arrives from the tenancy
    band, well before any of the four closure gates could have spoken, and estate
    A's inventory is still empty.

    PRD §2.1: When `X-User-Role` is `Fiduciary`, `X-User-ID` is the `id` of the acting `Fiduciary` row; ownership checks on any resource that references a `Fiduciary` compare the resource's foreign-key field to `X-User-ID`, and the acting fiduciary's own `estate_id` must equal the estate that owns the target resource — a fiduciary of one estate acting on another estate's resource is rejected with `ERR_FIDUCIARY_ESTATE_MISMATCH` (HTTP 403).

    PRD §2.7: **Tenancy and scope.** The fiduciary-to-estate check (`ERR_FIDUCIARY_ESTATE_MISMATCH`, 403) is evaluated first, then the provider-to-platform check (`ERR_PLATFORM_SCOPE_MISMATCH`, 403).

    PRD §3.4: Adding an account increments the estate's `inventory_total_count` and `assets_pending_disposition_count` and re-derives the `administration_phase`.

    Design: Corner/rbac/an_outside_fiduciary_and_an_outside_provider_are_both_refused_403
    """
    p, _q, ctx_a, ctx_b, _request_a = _two_estates_and_two_providers(api)

    validate_error(
        api.create_digital_asset(
            ctx_a.estate_id,
            f.digital_asset_payload(p["id"], account_handle="intruder-1", quoted_value_cents=1000),
            ctx_b.fid_headers,
        ),
        ERR_FIDUCIARY_ESTATE_MISMATCH,
    )
    assert fx.read_estate(api, ctx_a)["inventory_total_count"] == 0

    validate_error(
        api.close_estate(
            ctx_a.estate_id,
            f.close_estate_payload(closing_statement="closing somebody else's estate"),
            ctx_b.fid_headers,
        ),
        ERR_FIDUCIARY_ESTATE_MISMATCH,
    )
    assert fx.read_estate(api, ctx_a)["closed_at"] is None


def test_the_wrong_providers_desk_is_refused_where_the_addressed_one_succeeds(api):
    """
    Provider Q's desk starting review on a request addressed to provider P is
    refused with ERR_PLATFORM_SCOPE_MISMATCH and the package stays SUBMITTED. The
    byte-identical action from provider P's own desk then advances it to
    UNDER_REVIEW, which proves the first refusal was about identity rather than
    about the state of the package.

    PRD §2.1: When `X-User-Role` is `PlatformCompliance`, `X-User-ID` is the `id` of the acting `Platform`; ownership checks compare `X-User-ID` to the `platform_id` of the target resource — the `platform_id` of the `PlatformRequest` itself, or the `platform_id` of the `DigitalAsset` behind a disposition election, a cancellation order or a refund claim.

    PRD §2.1: A mismatch is rejected with `ERR_PLATFORM_SCOPE_MISMATCH` (HTTP 403).

    PRD §3.5: Starting review advances the package `SUBMITTED → UNDER_REVIEW` and changes nothing else.

    Design: Corner/rbac/an_outside_fiduciary_and_an_outside_provider_are_both_refused_403
    """
    p, q, ctx_a, _ctx_b, request_a = _two_estates_and_two_providers(api)

    validate_error(
        api.transition_platform_request(
            request_a["id"],
            f.request_transition_payload(REQ_ACTION_START_REVIEW),
            make_platform_compliance_headers(q["id"]),
        ),
        ERR_PLATFORM_SCOPE_MISMATCH,
    )
    assert fx.read_request(api, ctx_a, request_a["id"])["status"] == REQUEST_SUBMITTED

    reviewed = validate_success(
        api.transition_platform_request(
            request_a["id"],
            f.request_transition_payload(REQ_ACTION_START_REVIEW),
            make_platform_compliance_headers(p["id"]),
        ),
        200,
    )
    assert reviewed["status"] == REQUEST_UNDER_REVIEW
