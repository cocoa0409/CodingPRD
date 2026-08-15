"""Authz, ownership, identifier resolution, enum shape, pagination envelope,
and the state-vs-safety priority pair on checkout."""
from test_helpers import (
    ApiErrorId,
    api_client,
    borrow_packet,
    create_member,
    create_site,
    create_variety,
    make_checkouts_overdue,
    make_member_headers,
    make_volunteer_headers,
    NON_EXISTENT_UUID,
    record_test,
    setup_active_lot,
    setup_quarantine_lot,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStateBeatsSafetyOnCheckout:
    def test_suspended_member_borrowing_invasive_packet_gets_member_suspended(self):
        """PRD §3.5: "The creation pipeline evaluates its guards in a fixed
        order, and the first failure is the answer. The packet must be
        `AVAILABLE` (`ERR_PACKET_NOT_AVAILABLE`). The borrowing member must be
        `ACTIVE` — a `SUSPENDED` or `CLOSED` member is refused with
        `ERR_MEMBER_SUSPENDED`. The packet's lot must be `ACTIVE`, else
        `ERR_LOT_NOT_ACTIVE`; a variety retired behind the lot likewise blocks
        creation under the generic state rule. The variety's `invasive_flag`
        must be false, else `ERR_INVASIVE_SPECIES_BLOCKED`."

        A SUSPENDED member borrowing an invasive packet hits the standing guard
        before the safety screen.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_checkout
        """
        ctx = setup_active_lot(
            num_packets=3, seeds_per_packet=10, seeds_received=200,
            label_stock=20,
        )
        inv = setup_active_lot(
            num_packets=1, seeds_per_packet=10, seeds_received=100,
            label_stock=20, lot_code="I1",
            variety_overrides={"invasive_flag": True},
        )
        member = create_member(ctx["site"]["id"])
        for pid in ctx["packet_ids"]:
            borrow_packet(member, pid)
        make_checkouts_overdue()
        assert get_member_status(member) == "SUSPENDED"
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": inv["packet_ids"][0]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)

    def test_suspended_member_borrowing_clean_packet_gets_member_suspended(self):
        """PRD §3.5: "The borrowing member must be `ACTIVE` — a `SUSPENDED` or
        `CLOSED` member is refused with `ERR_MEMBER_SUSPENDED`."

        The same guard in isolation: SUSPENDED member, clean packet.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_checkout
        """
        ctx = setup_active_lot(
            num_packets=4, seeds_per_packet=10, seeds_received=200,
            label_stock=20,
        )
        member = create_member(ctx["site"]["id"])
        for pid in ctx["packet_ids"][:3]:
            borrow_packet(member, pid)
        make_checkouts_overdue()
        assert get_member_status(member) == "SUSPENDED"
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": ctx["packet_ids"][3]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def get_member_status(member) -> str:
    return validate_success(api_client.get_member(member["id"], ADMIN), 200)[
        "status"
    ]


class TestSegregationOfDuties:
    def test_volunteer_cannot_certify(self):
        """PRD §3.3: "Certification belongs exclusively to `ProgramAdmin` — a
        deliberate segregation of duties: the volunteer who recorded an assay
        can never certify it, because recording and certification sit in
        different roles."
        PRD §2.1: "A properly authenticated caller whose role is not in an
        endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/rbac_volunteer_cannot_certify_segregation_of_duties
        """
        ctx = setup_quarantine_lot(
            seeds_received=50, provisional_viability_pct=80.00,
            zone="ZONE_7A", site_type="GARDEN",
        )
        test = record_test(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            seeds_tested=100, sprouted_count=90,
        )
        resp = api_client.certify_germination_test(
            test["id"], {"outcome": "PASS"},
            make_volunteer_headers(ctx["volunteer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestRolePermission:
    def test_member_cannot_create_site(self):
        """PRD §2.1: "A properly authenticated caller whose role is not in an
        endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: POST /api/sites is authorized for "ProgramAdmin" only.

        Design: Corner/validations/val_role_not_permitted_unauthorized
        """
        site = create_site(site_type="GARDEN")
        member = create_member(site["id"])
        resp = api_client.create_site(
            {"name": "Evil", "site_type": "GARDEN", "region_zone": "ZONE_5A"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnershipEnforcement:
    def test_member_cannot_create_checkout_for_other_member(self):
        """PRD §3.5: "Only then does the ownership rule of §2.1 apply, refusing
        a member who named someone else's `member_id` with
        `ERR_SELF_SERVICE_FORBIDDEN`."
        PRD §2.1: "Self-service is enforced by an ownership rule: a `Member`
        may act only on resources whose `member_id` equals the presented
        `X-User-ID`".

        Design: Corner/validations/val_member_cannot_act_for_other_member
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member1 = create_member(ctx["site"]["id"])
        member2 = create_member(ctx["site"]["id"])
        resp = api_client.create_checkout(
            {"member_id": member2["id"], "packet_id": ctx["packet_ids"][0]},
            make_member_headers(member1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_SERVICE_FORBIDDEN)

    def test_member_reads_own_record_only(self):
        """PRD §3.1: "a member may read only their own record and their own
        credit summary."
        PRD §2.1: "Violations are rejected with `ERR_SELF_SERVICE_FORBIDDEN`
        (HTTP 403). The rule governs exactly ten operations: ... reading one's
        own member record, reading one's own credit summary, ..."

        Design: Corner/rbac/rbac_member_reads_own_record_only
        """
        site = create_site()
        member1 = create_member(site["id"], email="m1@x.com")
        member2 = create_member(site["id"], email="m2@x.com")
        own = validate_success(
            api_client.get_member(
                member1["id"], make_member_headers(member1["id"])
            ),
            200,
        )
        assert own["email"] == "m1@x.com"
        resp = api_client.get_member(
            member2["id"], make_member_headers(member1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SELF_SERVICE_FORBIDDEN)


class TestEnumShape:
    def test_invalid_site_type_rejected(self):
        """PRD §2.9: "a value outside an enum's declared set — for `site_type`,
        `category`, `item_type`, `condition`, `outcome`, `mode`, or any
        `status` target — draws `ERR_INVALID_ENUM` (HTTP 400)."
        PRD §3.1: "Registering a site takes a display `name`, a `site_type` of
        either `LIBRARY_BRANCH` or `GARDEN`".

        Design: Corner/validations/val_invalid_enum_rejected
        """
        resp = api_client.create_site(
            {"name": "S", "site_type": "FARM", "region_zone": "ZONE_5A"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


class TestIdentifierResolution:
    def test_nonexistent_path_id_returns_not_found(self):
        """PRD §2.8: "An identifier that resolves to no existing entity —
        whether it appears in the path or in the request body as a foreign key
        such as `member_id`, `packet_id`, `variety_id`, `site_id`, or
        `volunteer_id` — is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_get_nonexistent_returns_not_found
        """
        resp = api_client.get_seed_lot(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_path_existence_precedes_state_check(self):
        """PRD §2.8: "Paths that nest one resource beneath another resolve
        their identifiers strictly left to right".
        PRD §2.9: validation band "3. Left-to-right resolution of path
        identifiers (`ERR_NOT_FOUND`)." runs before band "6. State
        preconditions for the operation against a non-terminal resource
        (`ERR_INVALID_STATE`, HTTP 409)".

        submit-for-review on a nonexistent lot: 404 wins over any state
        reasoning.

        Design: Corner/validations/val_priority_existence_before_state
        """
        resp = api_client.submit_lot_for_review(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_body_fk_not_found(self):
        """PRD §2.8: "An identifier that resolves to no existing entity —
        whether it appears in the path or in the request body as a foreign key
        such as `member_id`, `packet_id`, `variety_id`, `site_id`, or
        `volunteer_id` — is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Checkout body references a nonexistent packet_id.

        Design: Corner/entities/entity_body_fk_not_found
        """
        site = create_site()
        member = create_member(site["id"])
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": NON_EXISTENT_UUID}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPaginationEnvelope:
    def _create_three_varieties(self):
        for name in ("A", "B", "C"):
            create_variety(
                variety_name=name, species=f"Sp {name}", category="HERB",
                approved_zones=["ZONE_7A"],
            )

    def test_defaults_and_envelope(self):
        """PRD §2.3: "List endpoints accept two query parameters. `limit`
        defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
        defaults to 0. Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` object."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/ep_pagination_defaults_and_envelope
        """
        self._create_three_varieties()
        resp = api_client.list_seed_varieties(ADMIN)
        body = resp.json()
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

    def test_limit_within_bounds_paginates(self):
        """PRD §2.3: "List endpoints accept two query parameters. `limit`
        defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
        defaults to 0. Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` object."
        PRD §2.3: "Collections are returned in `created_at` ascending order —
        oldest first — unless a more specific ordering is pinned by a rule in
        §3."

        limit=2 over a 3-row collection returns the first page with
        has_more true.

        Design: Corner/endpoints/ep_pagination_limit_bounds
        """
        self._create_three_varieties()
        resp = api_client.list_seed_varieties(ADMIN, params={"limit": 2})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
