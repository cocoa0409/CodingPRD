"""Creation defaults, required-field and FK validation, computed-field handling,
immutability, RBAC, pagination envelopes, and segment evaluation.

Corner queue: entities, rbac, and endpoints (listing / segment) sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    create_open_campaign, create_donor, create_household,
    setup_household_with_members, create_acknowledged_gift, record_gift,
    setup_open_campaign_with_donor, create_segment, rows_of,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


# ---------------------------------------------------------------------------
# Corner — entities section
# ---------------------------------------------------------------------------
class TestDonorCreation:
    def test_create_donor_returns_201_with_defaults(self, api):
        """PRD §3.2: "The lifecycle dimension, `lifecycle_status`, begins at `PROSPECT`".
        PRD §3.2: "The giving dimension, `giving_status`, begins at `NONE`". PRD §3.2:
        "A donor may also set `lapse_threshold_days` ... it must be an integer from 30 to
        3650 and defaults to 365." PRD §2.4: "The `version` field is an integer that
        begins at its initial value and increments by one on every mutation".

        Design: Corner/entities/create_donor_returns_201_with_defaults
        """
        data = validate_success(api.create_donor({"full_name": "New", "email": "new@example.com"}, GA),
                                expected_status=201)
        assert data["lifecycle_status"] == "PROSPECT"
        assert data["giving_status"] == "NONE"
        assert data["lapse_threshold_days"] == 365
        assert data["version"] == 1

    def test_get_donor_not_found_returns_404(self, api):
        """PRD §2.6: "The first identifier that does not resolve to an existing entity
        causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/get_donor_not_found_returns_404
        """
        validate_error(api.get_donor(NON_EXISTENT_UUID, GA), ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_donor_missing_email_returns_invalid_request(self, api):
        """PRD §3.2: "A donor carries a `full_name` (1 to 120 characters) and an `email`
        that must be unique across all donors". PRD §2.6: "finally the body's own
        field-type and range checks, which yield `ERR_INVALID_REQUEST` (HTTP 400)."

        email is required; omitting it -> ERR_INVALID_REQUEST.

        Design: Corner/entities/create_donor_missing_email_returns_invalid_request
        """
        validate_error(api.create_donor({"full_name": "NoEmail"}, GA), ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_donor_duplicate_email_returns_conflict(self, api):
        """PRD §3.2: "an `email` that must be unique across all donors when compared
        case-insensitively; a duplicate email is rejected with `ERR_DUPLICATE_EMAIL`
        (HTTP 409)."

        Design: Corner/entities/create_donor_duplicate_email_returns_conflict
        """
        get_success_data(api.create_donor({"full_name": "First", "email": "dup@example.com"}, GA))
        validate_error(
            api.create_donor({"full_name": "Second", "email": "DUP@EXAMPLE.COM"}, GA),
            ApiErrorId.ERR_DUPLICATE_EMAIL.value,
        )

    def test_donor_wrong_household_parent_returns_not_found(self, api):
        """PRD §2.6: "Whenever a request ... references another entity by a foreign key
        in its body, the referenced entity must already exist ... causes immediate
        rejection with `ERR_NOT_FOUND` (HTTP 404)".

        A non-existent household_id FK -> ERR_NOT_FOUND.

        Design: Corner/entities/donor_wrong_household_parent_returns_not_found
        """
        validate_error(
            api.create_donor({"full_name": "Wh", "email": "wh@example.com",
                              "household_id": NON_EXISTENT_UUID}, GA),
            ApiErrorId.ERR_NOT_FOUND.value,
        )


class TestGiftComputedAndImmutable:
    def test_gift_computed_status_ignores_input(self, api):
        """PRD §3.3: "A freshly recorded gift starts in `RECORDED` with no ledger
        postings yet". PRD §3.3: "A gift's `deductible_amount_cents` is the tax-deductible
        portion, computed at acknowledgement and pinned thereafter."

        A newly recorded gift is RECORDED with deductible 0 regardless of input.

        Design: Corner/entities/gift_computed_status_ignores_input
        """
        camp, donor = setup_open_campaign_with_donor()
        gift = validate_success(
            api.create_gift({"donor_id": donor["id"], "campaign_id": camp["id"],
                             "amount_cents": 5000, "status": "ACKNOWLEDGED",
                             "deductible_amount_cents": 9999}, GA),
            expected_status=201,
        )
        assert gift["status"] == "RECORDED", "server ignores client-supplied status"
        assert gift["deductible_amount_cents"] == 0, "deductible is 0 before acknowledgement"

    def test_softcredit_immutable_no_version_field(self, api):
        """PRD §2.4: "A soft-credit row is an immutable artifact of a gift
        acknowledgement; such rows carry only `id` and `created_at`. They have neither
        `updated_at` nor `version`."

        Design: Corner/entities/softcredit_immutable_no_version_field
        """
        hh, donors = setup_household_with_members(policy="FULL_TO_ALL", member_count=2)
        giver = donors[0]
        camp = create_open_campaign(goal_cents=1000000)
        _, gift_id = create_acknowledged_gift(camp["id"], giver["id"], amount_cents=6000)
        data = get_success_data(api.list_gift_soft_credits(gift_id, GA, params={"limit": 100}))
        rows = rows_of(data)
        assert len(rows) == 1, "FULL_TO_ALL with one other member mints exactly one row"
        row = rows[0]
        assert row["soft_credit_cents"] == 6000
        assert row["reversed"] is False
        assert "version" not in row, "SoftCredit exposes no version"
        assert "updated_at" not in row, "SoftCredit exposes no updated_at"


# ---------------------------------------------------------------------------
# Corner — rbac section
# ---------------------------------------------------------------------------
class TestRBAC:
    def test_campaign_manager_cannot_record_gift(self, api):
        """PRD §2.1: "When a syntactically valid request is made by a role that is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." Per Section 4, POST /gifts is a GiftAdmin
        operation.

        Design: Corner/rbac/campaign_manager_cannot_record_gift
        """
        camp, donor = setup_open_campaign_with_donor()
        validate_error(
            api.create_gift({"donor_id": donor["id"], "campaign_id": camp["id"],
                             "amount_cents": 5000}, CM),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    def test_giftadmin_cannot_acknowledge_gift(self, api):
        """PRD §2.1: "When a syntactically valid request is made by a role that is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." Per Section 4, POST /gifts/{id}/acknowledge is a
        DonorRelations operation.

        Design: Corner/rbac/giftadmin_cannot_acknowledge_gift
        """
        camp, donor = setup_open_campaign_with_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000)
        validate_error(api.acknowledge_gift(gift["id"], GA), ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        validate_error(api.get_donor(NON_EXISTENT_UUID, {}), ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Corner — endpoints section (listing / segment)
# ---------------------------------------------------------------------------
class TestListingAndSegments:
    def test_list_gifts_paginated_envelope_and_filter(self, api):
        """PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope." Per Section 4,
        GET /gifts filters by `donor_id`.

        Design: Corner/endpoints/list_gifts_paginated_envelope
        """
        camp, donor = setup_open_campaign_with_donor()
        record_gift(camp["id"], donor["id"], amount_cents=5000)
        record_gift(camp["id"], donor["id"], amount_cents=7000)
        data, meta = validate_paginated(api.list_gifts(GA, params={"donor_id": donor["id"]}))
        assert meta["total_count"] == 2, "two gifts for this donor"
        assert meta["has_more"] is False
        for g in data:
            assert g["donor_id"] == donor["id"], "filter narrows to the named donor"

    def test_segment_members_computed_read(self, api):
        """PRD §3.10: "A donor is a member when its `lifetime_hard_credit_cents` is at
        least `min_lifetime_cents`, its `giving_status` is among `giving_status_in` (or
        that array is empty) ... The segment exposes a computed `member_count`, which is
        the number of donors satisfying the predicate evaluated against the current donor
        population at read time".

        Design: Corner/endpoints/segment_members_computed_read
        """
        camp = create_open_campaign(goal_cents=5000000)
        donor = create_donor()
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=1000000)  # MAJOR
        seg = create_segment(name="Majors", min_lifetime_cents=500000, giving_status_in=["MAJOR"])

        members = get_success_data(api.list_segment_members(seg["id"], CM, params={"limit": 100}))
        member_ids = [d["id"] for d in rows_of(members)]
        assert donor["id"] in member_ids, "the MAJOR donor matches the segment predicate"
        seg_data = validate_success(api.get_segment(seg["id"], CM))
        assert seg_data["member_count"] == 1, "member_count recomputed on read"
