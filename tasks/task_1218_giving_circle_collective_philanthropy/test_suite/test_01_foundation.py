"""Foundational contracts: resource creation rules, identity, existence,
pagination envelope, and authentication ordering (PRD §2.1-§2.5, §3.1-§3.4).
"""
from test_helpers import (
    EMPTY_HEADERS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_nonprofit,
    create_circle_and_cycle,
    create_member_payload,
    create_membership_payload,
    create_nonprofit_payload,
    get_ledger,
    is_iso8601_timestamp,
    is_valid_uuid,
    unique_ein,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestFoundation:
    def test_create_circle_missing_required_fields_rejected(self, api):
        """PRD §3.1: "A `CircleAdmin` founds a circle by supplying its `name`
        and the five numbers that govern its economics: `admin_fee_percent`,
        the host organization's percentage share of received funds, an integer
        from 0 to 20; `quorum_percent`, the percentage of active memberships
        that must cast ballots for a valid vote, an integer from 1 to 100;
        `standard_minimum_cents`, the minimum contribution for the `STANDARD`
        tier, strictly greater than zero; `leader_minimum_cents`, the minimum
        for the `LEADER` tier, strictly greater than `standard_minimum_cents`;
        and `operating_reserve_cents`, the reserve subtracted from pooled funds
        before grant budgeting, zero or greater."
        PRD §3.1: "A request whose values fall outside these ranges or whose
        enum value is unrecognized is malformed and fails with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_circle_missing_required_name_rejected
        """
        resp = api.create_circle({}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api.list_circles(ADMIN))
        assert meta["total_count"] == 0, f"no circle may persist after a malformed create, got {meta['total_count']}"
        assert data == []

    def test_nonprofit_defaults_standing_good(self, api):
        """PRD §3.4: "Every nonprofit's `standing` begins at `GOOD`."

        Design: Corner/entities/nonprofit_defaults_standing_good
        """
        data = validate_success(
            api.create_nonprofit(create_nonprofit_payload(legal_name="NP Def"), ADMIN),
            expected_status=201,
        )
        assert_nonprofit(data)
        assert data["standing"] == "GOOD", f"new nonprofit standing must be GOOD, got {data['standing']}"

    def test_create_member_client_supplied_id_ignored(self, api):
        """PRD §2.5: "Every resource in the system — circles, cycles, members,
        memberships, contributions, nonprofits, nominations, site visits,
        learning sessions, ballots, awards, payouts, reports, and rollover
        decisions — carries a standard set of system-managed fields"
        PRD §2.5: "a unique, server-minted identifier formatted as a UUID, with
        no type prefix."

        Design: Corner/entities/create_member_id_input_ignored
        """
        sentinel_id = "00000000-0000-0000-0000-0000000000aa"
        payload = create_member_payload(full_name="M Sys")
        payload["id"] = sentinel_id
        data = validate_success(api.create_member(payload, ADMIN), expected_status=201)
        assert is_valid_uuid(data["id"]), "id must be a UUID"
        assert data["id"] != sentinel_id, (
            "the server mints its own id; a client-supplied id must not be adopted"
        )
        assert is_iso8601_timestamp(data["created_at"]), "created_at is server-stamped"

    def test_get_cycle_not_found_returns_404(self, api):
        """PRD §2.9: "Next, every identifier the request names — path identifiers
        and body foreign keys alike — is resolved left to right, and the first
        identifier that does not correspond to an existing resource fails the
        request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_cycle_not_found_returns_404
        """
        resp = api.get_cycle(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_members_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/list_members_pagination_envelope
        """
        for i in range(1, 12):
            validate_success(
                api.create_member(
                    create_member_payload(full_name=f"P{i:02d}"), ADMIN
                ),
                expected_status=201,
            )
        page1, meta1 = validate_paginated(
            api.list_members(ADMIN, params={"limit": 10, "offset": 0})
        )
        assert len(page1) == 10, f"page 1 must hold 10 rows, got {len(page1)}"
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_members(ADMIN, params={"limit": 10, "offset": 10})
        )
        assert len(page2) == 1, f"page 2 must hold 1 row, got {len(page2)}"
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False

    def test_create_membership_invalid_enum_tier_rejected(self, api):
        """PRD §3.2: "A `CircleAdmin` then invites a member into a circle at a
        contribution `tier` — `STANDARD` or `LEADER` — by supplying `member_id`
        and `circle_id`."
        PRD §3.1: "A request whose values fall outside these ranges or whose
        enum value is unrecognized is malformed and fails with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_membership_invalid_enum_tier_rejected
        """
        ctx = create_circle_and_cycle("Circle EN")
        member = validate_success(
            api.create_member(create_member_payload(full_name="M E"), ADMIN),
            expected_status=201,
        )
        resp = api.create_membership(
            create_membership_payload(member["id"], ctx["circle"]["id"], tier="GOLD"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_membership_unknown_circle_not_found(self, api):
        """PRD §2.9: "Next, every identifier the request names — path identifiers
        and body foreign keys alike — is resolved left to right, and the first
        identifier that does not correspond to an existing resource fails the
        request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/create_membership_unknown_circle_not_found
        """
        member = validate_success(
            api.create_member(create_member_payload(full_name="M FK"), ADMIN),
            expected_status=201,
        )
        resp = api.create_membership(
            create_membership_payload(member["id"], NON_EXISTENT_UUID, tier="STANDARD"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_cycle_created_in_draft_with_snapshots(self, api):
        """PRD §3.1: "The cycle is created in `DRAFT` and snapshots three circle
        settings at creation: `quorum_percent`, `admin_fee_percent`, and
        `operating_reserve_cents` are copied onto the cycle, so later edits to
        the circle never retroactively change a cycle in flight."
        PRD §2.6: "A dedicated ledger read on the cycle returns exactly these
        ten figures — the six totals, the pooled balance, and both budget
        variants."

        Design: Corner/state_machines/cycle_initial_phase_draft
        """
        ctx = create_circle_and_cycle("Circle SM0", quorum_percent=60)
        cycle = ctx["cycle"]
        assert cycle["phase"] == "DRAFT", f"new cycle phase must be DRAFT, got {cycle['phase']}"
        assert cycle["quorum_percent"] == 60, (
            f"quorum_percent snapshot must be copied from the circle, got {cycle['quorum_percent']}"
        )
        ledger = get_ledger(cycle["id"])
        assert ledger["received_total_cents"] == 0
        assert ledger["pooled_balance_cents"] == 0

    def test_nonprofit_ein_uniqueness_rejected(self, api):
        """PRD §3.4: "The EIN is unique across the registry; a duplicate
        registration fails with `ERR_EIN_CONFLICT`."

        Design: Corner/errors/nonprofit_ein_uniqueness_rejected
        """
        ein = unique_ein()
        validate_success(
            api.create_nonprofit(
                create_nonprofit_payload(ein=ein, legal_name="NP First"), ADMIN
            ),
            expected_status=201,
        )
        resp = api.create_nonprofit(
            create_nonprofit_payload(
                ein=ein, legal_name="NP Second", mission_category="health"
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_EIN_CONFLICT)

    def test_missing_auth_header_beats_not_found(self, api):
        """PRD §2.9: "Authentication comes first (§2.1, `ERR_UNAUTHENTICATED`),
        then role authorization for the endpoint (`ERR_FORBIDDEN`), then the
        ownership check on member- and grantee-scoped resources (`ERR_FORBIDDEN`).
        Next, every identifier the request names — path identifiers and body
        foreign keys alike — is resolved left to right, and the first identifier
        that does not correspond to an existing resource fails the request with
        `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.1: "A request missing either header, or carrying a role value
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_beats_not_found
        """
        resp = api.get_cycle(NON_EXISTENT_UUID, EMPTY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
