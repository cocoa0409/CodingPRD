"""Who may act: the two header checks, the peer split, and the three identity proofs."""
from test_helpers import (
    NON_EXISTENT_UUID,
    VERIFIED_REGISTRANT_EMAIL,
    ApiErrorId,
    CASE_MANAGER,
    CASE_MANAGER_ONE,
    PROVIDER_ADMIN,
    RESPONDENT,
    api_client,
    assert_ground,
    build_docket,
    build_user_headers,
    deficiency_notice_payload,
    file_complaint,
    get_success_data,
    ground_payload,
    make_complainant_headers,
    make_respondent_headers,
    panelist_payload,
    read_case,
    register_complainant,
    response_payload,
    setup_delivered_case,
    validate_error,
    validate_paginated,
)

AUTH_DOCKET = {
    "iana_id": "IANA-9036",
    "domain_name": "auth.example",
    "legal_name": "Auth Ltd",
    "country_code": "GB",
    "registrar_name": "Auth Registrar",
}
UNAUTH_DOCKET = {
    "iana_id": "IANA-9037",
    "domain_name": "unauth.example",
    "legal_name": "Unauth Ltd",
    "country_code": "GB",
    "registrar_name": "Unauth Registrar",
}
OWNER_DOCKET = {
    "iana_id": "IANA-9038",
    "domain_name": "owner.example",
    "legal_name": "Owner Ltd",
    "country_code": "GB",
    "registrar_name": "Owner Registrar",
}
IDENT_DOCKET = {
    "iana_id": "IANA-9039",
    "domain_name": "ident.example",
    "legal_name": "Ident Ltd",
    "country_code": "GB",
    "registrar_name": "Ident Registrar",
}


class TestAuthenticationRunsBeforeAnyLookup:
    def test_a_missing_header_or_an_undeclared_role_is_a_401_even_on_a_fabricated_case(self):
        """PRD §2.1: "Every request to every endpoint — including the two
        test-driving endpoints — must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, naming the capacity in which that user acts."
        PRD §2.1: "Six roles are recognised, spelled exactly as follows:
        `ProviderAdmin`, `CaseManager`, `Complainant`, `Respondent`, `Panelist`, and
        `RegistrarAgent`."
        PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not
        one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "These two checks run ahead of everything else, in that order."

        Design: Corner/rbac/absent_headers_and_an_undeclared_role_are_refused_before_any_lookup
        """
        docket = build_docket(**AUTH_DOCKET)
        case = file_complaint(docket["complainant"], docket["domain"])

        no_role = api_client.get_case(
            case["id"], {"X-User-ID": CASE_MANAGER_ONE, "Content-Type": "application/json"}
        )
        validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        no_id = api_client.get_case(
            case["id"], {"X-User-Role": "CaseManager", "Content-Type": "application/json"}
        )
        validate_error(no_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        misspelled = api_client.get_case(
            case["id"], build_user_headers(docket["registrar"]["id"], "Registrar")
        )
        validate_error(misspelled, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        ladder = api_client.get_case(
            NON_EXISTENT_UUID,
            {"X-User-ID": CASE_MANAGER_ONE, "Content-Type": "application/json"},
        )
        validate_error(ladder, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert ladder.json()["data"]["error_id"] != ApiErrorId.ERR_CASE_NOT_FOUND.value

        readable = read_case(case["id"])
        assert readable["status"] == "FILED"
        assert readable["id"] == case["id"]


class TestPeerRolesCannotReachEachOthersOperations:
    def test_each_exclusive_operation_turns_away_every_other_role(self):
        """PRD §2.1: "A request whose role is well-formed but is not among the roles
        authorised for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."
        PRD §2.1: "Provider-side work is deliberately split. Roster admission,
        registrar accreditation, decision publication, court dispositions, the logical
        clock and the deadline sweep belong to `ProviderAdmin`; the day-to-day conduct
        of a proceeding belongs to `CaseManager`."
        PRD §2.1: "The three party-side roles are peers over disjoint resources."
        PRD §2.10: "2. **Role authorisation.** The acting role appears among the roles
        authorised for the operation, else `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
        """
        docket = build_docket(**UNAUTH_DOCKET)
        complainant_id = docket["complainant"]["id"]
        case = file_complaint(docket["complainant"], docket["domain"])
        case_id = case["id"]

        complainant_answering = api_client.create_response(
            case_id,
            response_payload(
                "unauth@proxy.example",
                content_summary="The complainant tries to file the respondent's own answer.",
            ),
            make_complainant_headers(complainant_id),
        )
        validate_error(complainant_answering, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        respondent_clearing = api_client.clear_compliance(
            case_id, {"reviewer_notes": "Respondent clearing its own case."}, RESPONDENT
        )
        validate_error(respondent_clearing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        manager_admitting = api_client.create_panelist(
            panelist_payload(
                full_name="Oliver Grant", nationality_code="GB",
                roster_admitted_at="2018-01-01T00:00:00Z",
            ),
            CASE_MANAGER,
        )
        validate_error(manager_admitting, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        admin_issuing = api_client.create_deficiency_notice(
            case_id,
            deficiency_notice_payload(deficiency_codes=["MISSING_GROUND"], correction_days=5),
            PROVIDER_ADMIN,
        )
        validate_error(admin_issuing, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        ladder = api_client.clear_compliance(
            NON_EXISTENT_UUID,
            {"reviewer_notes": "Wrong role against a case that does not exist."},
            RESPONDENT,
        )
        validate_error(ladder, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert ladder.json()["data"]["error_id"] != ApiErrorId.ERR_CASE_NOT_FOUND.value

        unchanged = read_case(case_id)
        assert unchanged["status"] == "FILED"
        assert unchanged["version"] == case["version"]
        assert unchanged["compliance_cleared_by_user_id"] is None
        assert unchanged["deficiency_round_count"] == 0
        _, notice_meta = validate_paginated(
            api_client.list_deficiency_notices(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert notice_meta["total_count"] == 0
        _, response_meta = validate_paginated(
            api_client.list_responses(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert response_meta["total_count"] == 0

    def test_the_case_list_is_provider_side_while_the_single_read_is_shared(self):
        """PRD §4: "| GET | `/udrp/cases` | List cases, filterable by complainant_id
        (the reverse of Case.complainant_id) and domain_id (the reverse of
        Case.domain_id). | ProviderAdmin, CaseManager |"
        PRD §4: "| GET | `/udrp/cases/{id}` | Read one case. | ProviderAdmin,
        CaseManager, Complainant, Respondent, Panelist, RegistrarAgent |"
        PRD §2.1: "A request whose role is well-formed but is not among the roles
        authorised for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP
        403)."

        Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
        """
        docket = build_docket(**UNAUTH_DOCKET)
        case = file_complaint(docket["complainant"], docket["domain"])

        listed = api_client.list_cases(RESPONDENT, params={"limit": 10, "offset": 0})
        validate_error(listed, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        shared = get_success_data(api_client.get_case(case["id"], RESPONDENT))
        assert shared["id"] == case["id"]
        assert shared["status"] == "FILED"

        _, meta = validate_paginated(
            api_client.list_cases(CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1


class TestComplainantOwnershipPrecedesTheSchemaCheck:
    def _case_with_a_stranger_on_the_roll(self):
        docket = build_docket(**OWNER_DOCKET)
        stranger = register_complainant(
            legal_name="Stranger Ltd", country_code="GB", email="ip@stranger.example"
        )
        case = file_complaint(docket["complainant"], docket["domain"])
        return docket["complainant"], stranger, case

    def test_a_stranger_is_turned_away_as_a_non_owner_even_with_a_malformed_body(self):
        """PRD §2.1: "When `X-User-Role` is `Complainant`, `X-User-ID` is the `id` of
        the acting `Complainant` row. Ownership checks on any case-scoped resource
        compare the case's `complainant_id` to `X-User-ID`; a mismatch is
        `ERR_NOT_OWNER` (HTTP 403). This applies when a complainant asserts a ground,
        files a correction, withdraws a complaint, or files a court challenge as the
        complainant."
        PRD §2.10: "5. **Schema.** Required fields present, enum values drawn from
        their declared sets, integer fields non-negative where the field requires it,
        and any two-letter country code exactly two letters — else
        `ERR_INVALID_REQUEST`."

        Design: Corner/rbac/complainant_ownership_is_checked_before_the_body_is_validated
        """
        owner, stranger, case = self._case_with_a_stranger_on_the_roll()
        case_id = case["id"]
        stranger_headers = make_complainant_headers(stranger["id"])
        assert stranger["id"] != owner["id"]

        borrowed_ground = api_client.create_ground(
            case_id,
            ground_payload(
                "TRADEMARK_RIGHTS", evidence_count=1, similarity_claim="IDENTICAL",
                assertion_text="A stranger asserting rights on someone else's case.",
            ),
            stranger_headers,
        )
        validate_error(borrowed_ground, ApiErrorId.ERR_NOT_OWNER.value, 403)

        borrowed_withdrawal = api_client.withdraw_case(
            case_id, {"reason": "A stranger withdrawing someone else's case."}, stranger_headers
        )
        validate_error(borrowed_withdrawal, ApiErrorId.ERR_NOT_OWNER.value, 403)
        assert read_case(case_id)["status"] == "FILED"

        malformed = api_client.create_ground(
            case_id,
            {
                "ground_type": "NOT_A_GROUND_TYPE",
                "assertion_text": "Malformed and unowned at once.",
                "evidence_count": -4,
            },
            stranger_headers,
        )
        validate_error(malformed, ApiErrorId.ERR_NOT_OWNER.value, 403)
        assert malformed.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

        _, meta = validate_paginated(
            api_client.list_grounds(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0

    def test_the_ownership_rule_binds_the_complainant_role_only(self):
        """PRD §2.1: "When `X-User-Role` is `CaseManager`, `X-User-ID` is likewise an
        opaque operator identifier not tied to any persisted entity — case managers
        are addressed by pinned operator ids such as `cm-001` and `cm-002`."
        PRD §3.2: "Each is written with a `ground_type` of `TRADEMARK_RIGHTS`,
        `NO_LEGITIMATE_INTEREST` or `BAD_FAITH`, a narrative pleading in
        `assertion_text` between 10 and 4000 characters, and an `evidence_count`
        between 0 and 200 recording how many annexes were filed in support."

        Design: Corner/rbac/complainant_ownership_is_checked_before_the_body_is_validated
        """
        owner, stranger, case = self._case_with_a_stranger_on_the_roll()
        case_id = case["id"]

        manager_ground = get_success_data(
            api_client.create_ground(
                case_id,
                ground_payload(
                    "TRADEMARK_RIGHTS", evidence_count=1, similarity_claim="IDENTICAL",
                    assertion_text="OWNER is a registered mark, exhibit A attached.",
                ),
                CASE_MANAGER,
            ),
            201,
        )
        assert_ground(manager_ground)
        assert manager_ground["ground_type"] == "TRADEMARK_RIGHTS"

        owner_ground = get_success_data(
            api_client.create_ground(
                case_id,
                ground_payload(
                    "NO_LEGITIMATE_INTEREST", evidence_count=1,
                    assertion_text="No trading history under the name.",
                ),
                make_complainant_headers(owner["id"]),
            ),
            201,
        )
        assert owner_ground["ground_type"] == "NO_LEGITIMATE_INTEREST"

        rows, meta = validate_paginated(
            api_client.list_grounds(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2, "exactly the two legitimate rows exist"
        assert [row["ground_type"] for row in rows] == [
            "TRADEMARK_RIGHTS", "NO_LEGITIMATE_INTEREST",
        ]


class TestRespondentIdentityIsProvenByThePayload:
    def test_the_wrong_email_fails_and_the_disclosed_one_succeeds_from_any_operator_id(self):
        """PRD §2.1: "When `X-User-Role` is `Respondent`, `X-User-ID` is an opaque
        operator identifier not tied to any persisted entity either — there is no
        `Respondent` resource at all, because the true registrant is unknown to the
        provider until the registrar discloses it. A respondent instead proves identity
        per request by supplying `respondent_email` in the payload, which must equal
        the case's `verified_registrant_email`; a mismatch is
        `ERR_RESPONDENT_IDENTITY_MISMATCH` (HTTP 403)."
        PRD §3.4: "The disclosed identity is copied onto the case as its own
        `verified_registrant_name` and `verified_registrant_email` — this is the address
        against which the respondent's identity is later checked."
        PRD §3.5: "The answering party must prove they are the disclosed registrant:
        the supplied `respondent_email` must equal the case's
        `verified_registrant_email`, and any other address is refused with
        `ERR_RESPONDENT_IDENTITY_MISMATCH`."

        Design: Corner/rbac/respondent_identity_is_proven_by_the_payload_email_not_by_the_header
        """
        bundle = setup_delivered_case(**IDENT_DOCKET)
        case_id = bundle["case"]["id"]
        assert bundle["case"]["status"] == "COMMENCED"
        assert bundle["case"]["verified_registrant_email"] == VERIFIED_REGISTRANT_EMAIL

        impostor = api_client.create_response(
            case_id,
            response_payload(
                "impostor@elsewhere.example",
                content_summary="An unrelated party answering the complaint.",
                requests_three_member_panel=True,
            ),
            make_respondent_headers(),
        )
        validate_error(impostor, ApiErrorId.ERR_RESPONDENT_IDENTITY_MISMATCH.value, 403)

        mid = read_case(case_id)
        assert mid["status"] == "COMMENCED"
        assert mid["required_seat_count"] == 1, (
            "the refused body's three-member election had no effect"
        )
        assert mid["respondent_panel_election"] == "NONE"
        assert mid["assessed_fee_cents"] == 150000
        _, refused_meta = validate_paginated(
            api_client.list_responses(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert refused_meta["total_count"] == 0

        accepted = get_success_data(
            api_client.create_response(
                case_id,
                response_payload(
                    VERIFIED_REGISTRANT_EMAIL,
                    content_summary="The disclosed registrant answers and denies the allegations.",
                    requests_three_member_panel=False,
                ),
                make_respondent_headers("resp-an-operator-id-matching-no-row"),
            ),
            201,
        )
        assert accepted["respondent_email"] == VERIFIED_REGISTRANT_EMAIL
        assert accepted["case_id"] == case_id

        rows, meta = validate_paginated(
            api_client.list_responses(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert rows[0]["respondent_email"] == VERIFIED_REGISTRANT_EMAIL
        assert read_case(case_id)["status"] == "RESPONSE_RECEIVED"
