"""Party registration, normalization, identity, listing, and affiliate reach."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_matter,
    assert_party,
    create_attorney,
    create_matter,
    create_party,
    get_success_data,
    is_valid_uuid,
    setup_basic_matter,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


class TestPartyNormalizationOnCreate:
    def test_legal_name_normalized_and_soundex_computed(self):
        """PRD §3.1: "The party's `normalized_name` and four-character
        `phonetic_key` are computed at creation and stored."
        PRD §2.6: "First, the string is lowercased; every character that is not
        a lowercase letter, a digit, or a space is replaced with a single
        space; runs of whitespace are collapsed; and the result is trimmed.
        Second, trailing tokens are dropped repeatedly while the last remaining
        token is one of the twelve corporate suffixes `inc`, `incorporated`,
        `corp`, `corporation`, `co`, `company`, `llc`, `llp`, `lp`, `ltd`,
        `pc`, or `pllc`, continuing until no trailing token matches."

        Design: Corner/entities/c_party_normalization_on_create
        """
        party = create_party("Acme & Co., Inc.")
        assert party["normalized_name"] == "acme", (
            f"punctuation stripped, suffix tokens co/inc dropped; got "
            f"{party['normalized_name']!r}"
        )
        assert party["phonetic_key"] == "A250", (
            f"American Soundex of 'acme': A kept, c->2, m->5, e dropped, "
            f"right-padded to 4; got {party['phonetic_key']!r}"
        )

    def test_party_created_with_server_id_and_version_one(self):
        """PRD §2.4: "**`id`** (string): a server-minted UUID with no type
        prefix."
        PRD §2.4: "**`version`** (integer): starts at 1 and increments by one
        on every mutation of that row, including mutations written by cascaded
        side effects that originate from another resource."

        Design: Corner/entities/c_party_normalization_on_create
        """
        party = create_party("Acme & Co., Inc.")
        assert is_valid_uuid(party["id"]), "id must be a server-minted UUID"
        assert party["version"] == 1
        assert_party(party)


class TestPartyMissingRequiredFieldReturns400:
    def test_create_party_without_party_type_rejected(self):
        """PRD §3.1: "A `FirmAdmin` registers a party by supplying its
        `legal_name`, a `party_type` of `CORPORATION`, `INDIVIDUAL`,
        `PARTNERSHIP`, `TRUST`, or `GOVERNMENT`, an optional `aliases` list,
        and an optional `affiliate_of_id`."
        PRD §2.11: "The tiers are: (1) header authentication, failing as
        `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint and
        action, failing as `ERR_FORBIDDEN`; (3) existence of path and body
        references, failing as `ERR_NOT_FOUND`; (4) the ethical-wall read gate
        of §2.9, failing as `ERR_WALL_EXCLUDED`; (5) ownership — attorney-scoped
        operations failing as `ERR_NOT_RESPONSIBLE_ATTORNEY` and client-scoped
        ownership mismatches failing as `ERR_FORBIDDEN`; (6) state and
        concurrency gates, failing as `ERR_MATTER_NOT_INTAKE`,
        `ERR_MATTER_NOT_OPEN`, `ERR_MATTER_TERMINAL`, `ERR_HIT_NOT_PENDING`,
        `ERR_WAIVER_INVALID_STATE`, `ERR_LETTER_INVALID_STATE`,
        `ERR_WALL_INVALID_STATE`, or `ERR_STALE_VERSION`; (7) business safety,
        failing as `ERR_MATTER_CLEARANCE_BLOCKED`, `ERR_SOD_SELF_APPROVAL`,
        `ERR_ATTORNEY_ADVERSE_OVERLAP`, or `ERR_ATTORNEY_NOT_ACTIVE`; (8)
        business temporal rules, failing as `ERR_LETTER_STALE`; (9) business
        referential rules, failing as `ERR_CHECK_SUPERSEDED` or
        `ERR_HIT_NOT_CONFIRMED`; (10) business constraints, failing as
        `ERR_WAIVER_ACTIVE_EXISTS`, `ERR_WALL_INVALID_STATE`,
        `ERR_ATTORNEY_ALREADY_EXCLUDED`, `ERR_ATTORNEY_NOT_EXCLUDED`, or
        `ERR_PARTY_ALREADY_ON_MATTER`; (11) business fiscal rules, failing as
        `ERR_CREDIT_MISSING`, `ERR_CREDIT_STALE`, `ERR_RETAINER_UNFUNDED`, or
        `ERR_REFUND_EXCEEDS_BALANCE`; and (12) request shape, failing as
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/c_party_missing_required_field_returns_400
        """
        resp = api_client.create_party({"legal_name": "No Type Corp"}, FIRM_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestGetMatterNotFoundReturns404:
    def test_read_nonexistent_matter_returns_not_found(self):
        """PRD §2.11: "Requests that address nested resources resolve path
        identifiers strictly left to right — the matter first, then the letter,
        waiver, wall, deposit, hit, party, or attorney beneath it — and the
        first identifier that does not resolve fails the whole request with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/c_get_matter_not_found_returns_404
        """
        resp = api_client.get_matter(
            "00000000-0000-4000-8000-000000000000", INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMattersListPaginationEnvelope:
    def test_limit_offset_total_count_and_has_more(self):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit`
        parameter caps the number of items returned; it defaults to 10, with a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/c_matters_list_pagination_envelope
        """
        party = create_party("Page Client Inc")
        atty = create_attorney()
        create_matter(party["id"], atty["id"], practice_group="LITIGATION",
                      matter_title="M1")
        create_matter(party["id"], atty["id"], practice_group="TAX",
                      matter_title="M2")
        create_matter(party["id"], atty["id"], practice_group="IP",
                      matter_title="M3")

        page1, meta1 = validate_paginated(
            api_client.list_matters(INTAKE, params={"limit": 2, "offset": 0})
        )
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api_client.list_matters(INTAKE, params={"limit": 2, "offset": 2})
        )
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1

        for matter in page1 + page2:
            assert_matter(matter)


class TestAffiliateTreeAndReverseLookup:
    def test_affiliate_of_id_filter_returns_child_from_parent(self):
        """PRD §3.1: "Party search accepts an optional `q` that filters on
        substrings of `normalized_name`, plus optional `party_type` and
        `affiliate_of_id` filters — the latter returns the parties naming the
        given party as their parent, giving reverse reach down the affiliate
        tree."

        Design: Corner/entities/c_affiliate_tree_and_reverse_lookup
        """
        parent = create_party("Holdings Parent Inc")
        child = create_party("Sub Child LLC", affiliate_of_id=parent["id"])

        data = get_success_data(
            api_client.list_parties(
                FIRM_ADMIN, params={"affiliate_of_id": parent["id"]}
            ),
            200,
        )
        assert data[0]["id"] == child["id"], (
            "the affiliate child is found from the parent id"
        )
