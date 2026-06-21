"""Validation violations (window, jurisdiction, requirements-met, carryover-cap,
provider window) and RBAC denial (role, ownership, authentication).
"""
from test_helpers import (
    validate_error,
    get_success_data,
    build_user_headers,
    ApiErrorId,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
)

ADMIN = FX.ADMIN


# ===========================================================================
# Corner/validations
# ===========================================================================
def test_completion_out_of_cycle_window_returns_422(api):
    """PRD §3.4: "The `completed_at` instant must fall inside the renewal window,
    meaning at or after `cycle_start` and strictly before `cycle_end`; a
    completion logged outside that window is rejected with
    `ERR_COMPLETION_OUT_OF_WINDOW`."

    Design: Corner/validations/completion_out_of_cycle_window_returns_422
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "GENERAL", 24.0)

    # completed_at 2025-12-01 is before cycle_start 2026-01-01.
    payload = F.create_completion_payload(
        licensee["id"], course["id"], cycle["id"], completed_at="2025-12-01T00:00:00Z")
    resp = api.create_completion(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPLETION_OUT_OF_WINDOW.value, 422)


def test_reciprocity_same_jurisdiction_returns_422(api):
    """PRD §3.7: "The `source_jurisdiction_code` must differ from the
    `jurisdiction_code` of the target cycle's board; a same-jurisdiction request
    is rejected with `ERR_SAME_JURISDICTION`, and this same-jurisdiction check is
    enforced both at request time and again at approval time."

    Design: Corner/validations/reciprocity_same_jurisdiction_returns_422
    """
    base = FX.setup_board_provider_licensee_cycle(
        with_requirements=False, with_provider=False)
    licensee, cycle = base["licensee"], base["cycle"]

    # Board jurisdiction is CA; source CA is identical.
    payload = F.create_reciprocity_grant_payload(
        licensee["id"], cycle["id"], "CA", "GENERAL", 2.0)
    resp = api.create_reciprocity_grant(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_SAME_JURISDICTION.value, 422)


def test_renew_without_requirements_met_returns_invalid_state(api):
    """PRD §3.8: "Renewal is permitted only when the cycle is in
    `REQUIREMENTS_MET`."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/validations/renew_without_requirements_met_returns_invalid_state
    """
    base = FX.setup_board_provider_licensee_cycle(
        with_requirements=False, with_provider=False)
    licensee, cycle = base["licensee"], base["cycle"]
    lic = make_licensee_headers(licensee["id"])

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], lic))
    resp = api.renew_cycle(cycle["id"], F.renew_cycle_payload(cyc["version"]), lic)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_carryover_in_exceeds_cap_returns_422(api):
    """PRD §3.3: "A supplied `carryover_in_hours` that exceeds either the prior
    cycle's `carryover_out_hours` or the board's `carryover_cap_hours` is rejected
    with `ERR_CARRYOVER_EXCEEDS_CAP`."

    Design: Corner/validations/carryover_in_exceeds_cap_returns_422
    """
    board = FX.create_board(with_requirements=False, carryover_cap_hours=10.0)
    licensee = FX.create_licensee(board["id"])

    payload = F.create_renewal_cycle_payload(
        licensee["id"], board["id"], "2026-01-01T00:00:00Z", carryover_in_hours=12.0)
    resp = api.create_renewal_cycle(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_CARRYOVER_EXCEEDS_CAP.value, 422)


# ===========================================================================
# Corner/errors
# ===========================================================================
def test_error_completion_out_of_provider_window_on_verify(api):
    """PRD §3.4: "The system also re-checks that `completed_at` lies within the
    half-open provider accreditation window from `accredited_from` inclusive to
    `accredited_until` exclusive; a verify outside that window is rejected with
    `ERR_COMPLETION_OUT_OF_WINDOW`."

    Design: Corner/errors/error_completion_out_of_provider_window_on_verify
    """
    board = FX.create_board(with_requirements=False)
    # Provider accredited from 2026-01-01 until 2026-01-15.
    provider = FX.create_accredited_provider(board["id"], accredited_until="2026-01-15T00:00:00Z")
    course = FX.create_course(provider["id"], "GENERAL", 24.0)
    licensee = FX.create_licensee(board["id"])
    cycle = FX.open_cycle(licensee["id"], board["id"])
    # completed_at 2026-02-01 is inside the cycle window but past accreditation.
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"], completed_at="2026-02-01T00:00:00Z")

    resp = api.verify_completion(comp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COMPLETION_OUT_OF_WINDOW.value, 422)


# ===========================================================================
# Corner/rbac
# ===========================================================================
def test_licensee_cannot_verify_completion_forbidden(api):
    """PRD §4 (endpoint table): "POST `/completions/{id}/verify` ... Authorized
    Role(s) `BoardAdmin`."
    PRD §2.1: "When the headers are present and well-formed but the acting role
    is not permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/licensee_cannot_verify_completion_forbidden
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])

    resp = api.verify_completion(comp["id"], make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_licensee_cannot_act_on_other_licensees_completion_not_owner(api):
    """PRD §2.1: "A licensee may act only on its own completions, renewal cycles,
    and reciprocity grants; otherwise the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/licensee_cannot_act_on_other_licensees_completion_not_owner
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, lic1, cycle1 = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "GENERAL", 24.0)
    lic2 = FX.create_licensee(base["board"]["id"])

    # L2 attempts to log a completion under L1's licensee_id.
    payload = F.create_completion_payload(lic1["id"], course["id"], cycle1["id"])
    resp = api.create_completion(payload, make_licensee_headers(lic2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one,
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    board = FX.create_board(with_requirements=False)

    # No X-User-ID / X-User-Role headers at all.
    resp = api.get_license_board(board["id"], headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
