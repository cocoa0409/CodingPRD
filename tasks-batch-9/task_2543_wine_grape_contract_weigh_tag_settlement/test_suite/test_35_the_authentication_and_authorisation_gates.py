"""The two gates every request passes through before anything else is looked at. The first asks
only whether both headers are there, and it has to answer before the path id is resolved, before
the body is validated and before the pagination bounds are read — otherwise an anonymous caller
learns from the shape of the refusal whether a row exists. The second asks whether the declared
role is one of the six and whether that role appears on this particular endpoint, and both clauses
have to be enforced with the same 403.
"""
from test_helpers import (
    CLERK,
    MANAGER,
    MANAGER_USER_ID,
    SCALE_OPERATOR,
    ApiErrorId,
    build_user_headers,
    create_grower,
    move_clock,
    read_contract,
    setup_drafted_contract,
    validate_error,
    validate_success,
)

SETUP_AT = "2026-08-01T00:00:00Z"

# No X-User-ID and no X-User-Role at all.
NO_AUTH_HEADERS = {}
# Both headers present, but the role is the empty string — "absent or blank" covers this too.
A_BLANK_ROLE = {"X-User-ID": MANAGER_USER_ID, "X-User-Role": ""}
# A role name that is not one of the six the specification declares.
AN_UNRECOGNISED_ROLE = build_user_headers("intern-1", "WineryIntern")

ALL_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
A_LIMIT_BELOW_THE_FLOOR = 0

A_PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
A_BODY_MISSING_ITS_MANDATORY_FIELDS = {"name": "No Licence Supplied"}
A_SECOND_PRODUCER = {
    "name": "Cellar Intern Ltd",
    "license_number": "PL-99999",
    "region_code": "NAPA-NORTH",
}


# --- Gate one: are both headers there at all? --------------------------------------------


def _one_registered_producer() -> dict:
    """A single producer, registered properly, so that the unauthenticated probes below are
    aimed at a row that genuinely exists."""
    move_clock(SETUP_AT)
    return create_grower(**A_PRODUCER)


def test_a_headerless_read_of_a_real_row_is_refused(api):
    """The request would have succeeded with any of the four roles that may read a producer, so
    the only thing standing in its way is the pair of missing headers.

    PRD: "Every request — without exception, including the clock endpoints — must carry two
    headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the
    capacity in which that principal acts. If either header is absent or blank, the request is
    refused with `ERR_MISSING_AUTH_HEADER` and HTTP 401."

    Design: Corner/rbac/missing_auth_headers_returns_401_before_any_other_check
    """
    grower = _one_registered_producer()

    validate_error(
        api.get_grower(grower["id"], NO_AUTH_HEADERS),
        ApiErrorId.ERR_MISSING_AUTH_HEADER.value,
        401,
    )
    validate_success(api.get_grower(grower["id"], MANAGER))


def test_authentication_answers_before_the_path_id_is_resolved(api):
    """An id that resolves to nothing gets the same 401 rather than a 404: no row was probed, so
    the caller learns nothing about what does or does not exist.

    PRD: "Ranks 1 through 4 are authentication and authorisation, in this order: (1) both auth
    headers present and non-blank, else `ERR_MISSING_AUTH_HEADER`, on every endpoint"

    Design: Corner/rbac/missing_auth_headers_returns_401_before_any_other_check
    """
    _one_registered_producer()

    validate_error(
        api.get_grower(ALL_ZERO_UUID, NO_AUTH_HEADERS),
        ApiErrorId.ERR_MISSING_AUTH_HEADER.value,
        401,
    )


def test_authentication_answers_before_the_body_is_validated(api):
    """Two of the three mandatory registration fields are missing, and the refusal still names the
    headers — rank 1 sits above the rank-7 shape check.

    PRD: "Ranks 7 and 8 are request shape: (7) required fields present, JSON types correct, enum
    values inside their declared sets, numeric ranges and decimal-place limits respected, ISO-8601
    instants parseable, and any window's `window_end` strictly after its `window_start` — else
    `ERR_VALIDATION` with HTTP 422, on every endpoint"

    Design: Corner/rbac/missing_auth_headers_returns_401_before_any_other_check
    """
    _one_registered_producer()

    validate_error(
        api.create_grower(dict(A_BODY_MISSING_ITS_MANDATORY_FIELDS), NO_AUTH_HEADERS),
        ApiErrorId.ERR_MISSING_AUTH_HEADER.value,
        401,
    )


def test_authentication_answers_before_the_pagination_bounds_are_read(api):
    """A limit below the floor would be a 400 on an authenticated call; unauthenticated it never
    gets that far.

    PRD: "(8) pagination bounds, else `ERR_INVALID_PAGINATION` with HTTP 400, on every list
    endpoint."

    Design: Corner/rbac/missing_auth_headers_returns_401_before_any_other_check
    """
    _one_registered_producer()

    validate_error(
        api.list_growers(NO_AUTH_HEADERS, params={"limit": A_LIMIT_BELOW_THE_FLOOR}),
        ApiErrorId.ERR_MISSING_AUTH_HEADER.value,
        401,
    )


def test_a_blank_role_alongside_a_present_user_id_is_the_same_refusal(api):
    """The rule is about both headers being non-blank, not merely present, so an empty role string
    is treated exactly as a missing one — and not as an unrecognised role name.

    PRD: "If either header is absent or blank, the request is refused with
    `ERR_MISSING_AUTH_HEADER` and HTTP 401."

    Design: Corner/rbac/missing_auth_headers_returns_401_before_any_other_check
    """
    grower = _one_registered_producer()

    validate_error(
        api.get_grower(grower["id"], dict(A_BLANK_ROLE)),
        ApiErrorId.ERR_MISSING_AUTH_HEADER.value,
        401,
    )


# --- Gate two: is this role allowed through this door? ------------------------------------


def _a_contract_waiting_on_the_right_roles() -> dict:
    """One producer, block, specification and DRAFT contract with its block already allocated, so
    every wrongly-roled call below fails on authorisation rather than on state."""
    move_clock(SETUP_AT)
    return setup_drafted_contract({"contract_code": "GC-RBAC"})


def test_a_role_outside_the_six_declared_names_is_refused(api):
    """`WineryIntern` is not one of the six spellings the specification declares, so the first
    clause of the authorisation rule rejects it before any endpoint's own list is consulted.

    PRD: "If `X-User-Role` is not one of those six strings, or is one of them but is not listed
    among the roles authorised for the endpoint being called, the request is refused with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/role_not_listed_on_the_endpoint_returns_403
    """
    move_clock(SETUP_AT)

    validate_error(
        api.create_grower(dict(A_SECOND_PRODUCER), AN_UNRECOGNISED_ROLE),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )


def test_the_scale_house_cannot_put_a_contract_on_the_table(api):
    """Offering is exclusive to the producer-relations desk; the scale house holds a perfectly
    valid role that simply is not on this endpoint, and the contract does not move.

    PRD: "Put the contract on the table (`DRAFT` or `COUNTERED` to `OFFERED`), optionally
    repricing it with an optional `base_price_per_ton_cents`. | GrowerRelationsManager"

    Design: Corner/rbac/role_not_listed_on_the_endpoint_returns_403
    """
    ctx = _a_contract_waiting_on_the_right_roles()

    validate_error(
        api.offer_contract(ctx["contract"]["id"], SCALE_OPERATOR),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "DRAFT"


def test_the_winery_cannot_accept_its_own_offer(api):
    """Acceptance belongs to the producer alone, so the desk that wrote the offer cannot sign it
    too — the negotiation genuinely needs two parties.

    PRD: "The producer accepts (`OFFERED` to `ACTIVE`); derives the tonnage caps, the renewal
    window and the installment rows. | Grower"

    Design: Corner/rbac/role_not_listed_on_the_endpoint_returns_403
    """
    ctx = _a_contract_waiting_on_the_right_roles()
    validate_success(api.offer_contract(ctx["contract"]["id"], MANAGER))

    validate_error(
        api.accept_contract(ctx["contract"]["id"], MANAGER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "OFFERED"


def test_the_authorisation_refusal_precedes_the_existence_check(api):
    """The body names a crew id that belongs to a block, which an authorised caller would be told
    is not a crew; the unauthorised caller is refused first.

    PRD: "Ranks 5 and 6 are existence: (5) every identifier in the URL path resolves, checked left
    to right; (6) every foreign-key identifier in the request body resolves, checked in the field
    order described for the target resource."

    Design: Corner/rbac/role_not_listed_on_the_endpoint_returns_403
    """
    ctx = _a_contract_waiting_on_the_right_roles()

    validate_error(
        api.create_sampling_visit(
            {
                "contract_id": ctx["contract"]["id"],
                "block_id": ctx["block"]["id"],
                "crew_id": ctx["block"]["id"],
                "window_start": "2026-08-01T09:00:00Z",
                "window_end": "2026-08-01T11:00:00Z",
            },
            CLERK,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )


def test_a_read_endpoint_is_guarded_just_as_tightly_as_a_write(api):
    """The installment collection is limited to the two money-facing roles, so the scale house is
    refused a plain GET — the role table is per endpoint, not per verb.

    PRD: "List installments; filter by `contract_id`, `status` or `lien_protected`.
    Cascade-created on acceptance, so this is their only discovery channel; rows come back ordered
    by `installment_no` ascending then `created_at` ascending. | GrowerRelationsManager,
    AccountsPayableClerk"

    Design: Corner/rbac/role_not_listed_on_the_endpoint_returns_403
    """
    ctx = _a_contract_waiting_on_the_right_roles()

    validate_error(
        api.list_installments(SCALE_OPERATOR, params={"contract_id": ctx["contract"]["id"]}),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_success(api.list_installments(CLERK, params={"contract_id": ctx["contract"]["id"]}))


def test_the_same_two_calls_go_through_from_the_roles_that_own_them(api):
    """Nothing about the offer or the acceptance was wrong except who sent it: from the desk and
    from the producer respectively, the identical calls carry the contract all the way to `ACTIVE`.

    PRD: "(2) the declared role is recognised and is authorised for this endpoint, else
    `ERR_UNAUTHORIZED`, on every endpoint"

    Design: Corner/rbac/role_not_listed_on_the_endpoint_returns_403
    """
    ctx = _a_contract_waiting_on_the_right_roles()

    offered = validate_success(api.offer_contract(ctx["contract"]["id"], MANAGER))
    assert offered["lifecycle_status"] == "OFFERED"

    accepted = validate_success(
        api.accept_contract(ctx["contract"]["id"], ctx["grower_headers"])
    )
    assert accepted["lifecycle_status"] == "ACTIVE"
