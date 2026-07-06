"""Role-based access control, ownership gating, and auth-before-existence ordering."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_party_headers, make_neutral_headers, make_unknown_headers,
    create_case_payload, create_ranking_payload, add_candidate_payload,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    ADMIN, create_case, create_neutral, add_two_parties, open_selection,
    case_version, setup_selection_with_candidate,
)

ADM = ADMIN
P_ID = "00000000-0000-0000-0000-000000000001"
N_ID = "00000000-0000-0000-0000-000000000003"


# ---- Exclusive-operation denials -----------------------------------------

def test_party_cannot_file_case(api):
    """PRD 2.1: "A request whose role is authenticated but is not permitted to perform the
    requested operation ... is rejected with `ERR_UNAUTHORIZED`." PRD 3.1: "A
    `CaseAdministrator` opens a matter by filing a **Case**."

    Design: Corner/rbac/party_cannot_file_case
    """
    resp = api.create_case(create_case_payload(
        title="PartyFile", claim_amount_cents=500_000, panel_size=1), make_party_headers(P_ID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_party_cannot_disclose_candidate(api):
    """PRD 2.1: "A request whose role is authenticated but is not permitted to perform the
    requested operation ... is rejected with `ERR_UNAUTHORIZED`." PRD 3.3: "The proposed
    neutral submits a disclosure ... This action is reserved to the `Neutral` who owns the
    candidacy".

    Design: Corner/rbac/party_cannot_disclose_candidate
    """
    resp = api.disclose_candidate(NON_EXISTENT_UUID,
                                  {"disclosure_text": "x", "has_conflict": False},
                                  make_party_headers(P_ID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_admin_cannot_create_ranking(api):
    """PRD 2.1: "A request whose role is authenticated but is not permitted to perform the
    requested operation ... is rejected with `ERR_UNAUTHORIZED`." PRD 3.4: "A `Party`
    casts a **Ranking**".

    Design: Corner/rbac/admin_cannot_create_ranking
    """
    resp = api.create_ranking(create_ranking_payload(
        candidate_id=NON_EXISTENT_UUID, party_id="00000000-0000-0000-0000-000000000002",
        action="RANK", rank_value=1), ADM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_neutral_cannot_pay_deposit(api):
    """PRD 2.1: "A request whose role is authenticated but is not permitted to perform the
    requested operation ... is rejected with `ERR_UNAUTHORIZED`." PRD 3.8: "A `Party` pays
    a requested deposit".

    Design: Corner/rbac/neutral_cannot_pay_deposit
    """
    resp = api.pay_deposit(NON_EXISTENT_UUID, make_neutral_headers(N_ID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---- Ownership gating ----------------------------------------------------

def test_party_cannot_withdraw_another_partys_ranking(api):
    """PRD 2.1: "withdrawing a ranking requires that the ranking's `party_id` equal
    `X-User-ID`". PRD 3.4: "A `Party` may withdraw its own ranking ... the acting
    `X-User-ID` must equal the ranking's `party_id`."

    Design: Corner/rbac/party_cannot_withdraw_another_partys_ranking
    """
    ctx = setup_selection_with_candidate(api, disclose_it=False)
    r1 = validate_success(api.create_ranking(create_ranking_payload(
        candidate_id=ctx["candidate"]["id"], party_id=ctx["pA"]["id"], action="RANK", rank_value=5),
        make_party_headers(ctx["pA"]["id"])), 201)
    resp = api.withdraw_ranking(r1["id"], make_party_headers(ctx["pB"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_neutral_cannot_disclose_another_neutrals_candidate(api):
    """PRD 2.1: "submitting a disclosure requires that the target candidate's `neutral_id`
    equal `X-User-ID`". PRD 3.3: "This action is reserved to the `Neutral` who owns the
    candidacy — the acting `X-User-ID` must equal the candidate's `neutral_id`".

    Design: Corner/rbac/neutral_cannot_disclose_another_neutrals_candidate
    """
    n1 = create_neutral(api, full_name="N1")
    n2 = create_neutral(api, full_name="N2")
    case = create_case(api, claim_amount_cents=500_000)
    add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    cand = validate_success(api.add_candidate(case["id"], add_candidate_payload(
        neutral_id=n1["id"], expected_case_version=case_version(api, case["id"])), ADM), 201)
    resp = api.disclose_candidate(cand["id"], {"disclosure_text": "not mine", "has_conflict": False},
                                  make_neutral_headers(n2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---- Authentication and shared reads -------------------------------------

def test_unknown_role_returns_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or that names a role the system does
    not recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    case = create_case(api, claim_amount_cents=500_000)
    resp = api.get_case(case["id"], make_unknown_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_neutral_can_read_case_shared_get(api):
    """PRD 4 (endpoint): "Get a case | CaseAdministrator, Party, Neutral". PRD 2.1: "When
    `X-User-Role` is `Neutral`, `X-User-ID` is the `id` of the acting `Neutral`."

    Design: Corner/rbac/neutral_can_read_case_shared_get
    """
    neutral = create_neutral(api, full_name="Reader N")
    case = create_case(api, title="SharedRead", claim_amount_cents=500_000)
    data = validate_success(api.get_case(case["id"], make_neutral_headers(neutral["id"])), 200)
    assert data["title"] == "SharedRead"


# ---- Priority: auth/authz precede existence ------------------------------

def test_unauthenticated_precedes_not_found_priority(api):
    """PRD 2.8: "1. **Authentication** — headers present and the role known; otherwise
    `ERR_UNAUTHENTICATED` (401). ... 3. **Existence** — every identifier in the path ...
    resolves". PRD 2.8: "an unauthenticated caller never learns that a resource is
    missing".

    Design: Corner/validations/unauthenticated_precedes_not_found_priority
    """
    resp = api.get_case("00000000-0000-0000-0000-000000000000", make_unknown_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_unauthorized_precedes_not_found_priority(api):
    """PRD 2.8: "2. **Authorization** — the role is permitted for the operation ...
    otherwise `ERR_UNAUTHORIZED` (403). 3. **Existence** ... produces `ERR_NOT_FOUND`
    (404)". PRD 2.8: "An earlier check always takes precedence over a later one".

    Design: Corner/validations/unauthorized_precedes_not_found_priority
    """
    resp = api.appoint_case("00000000-0000-0000-0000-000000000000",
                            {"expected_case_version": 1}, make_party_headers(P_ID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
