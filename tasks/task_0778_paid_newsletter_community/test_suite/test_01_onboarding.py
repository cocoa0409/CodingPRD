"""Publication, tier, and member onboarding (queue B — entities & endpoints)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, is_valid_uuid, is_iso8601_timestamp,
    TEST_USERS, make_creator_headers,
    new_publication, new_member, new_verified_member,
)

CREATOR = TEST_USERS["creator_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_publication_returns_201_with_system_fields(api):
    """PRD §3.1: "The server records the creating operator's identifier as
    `creator_user_id`, sets `status` to `ACTIVE` and `deliverability_status` to
    `HEALTHY`, and initializes every computed counter ... to zero."
    PRD §3.1: "supplying its `name` and optionally its `platform_fee_bps`; when
    the fee is omitted it defaults to 1000 basis points."

    Design: Corner/entities/create_publication_returns_201_with_system_fields
    """
    resp = api.create_publication({"name": "P"}, CREATOR)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"]), "id must be a system-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["status"] == "ACTIVE"
    assert data["deliverability_status"] == "HEALTHY"
    assert data["platform_fee_bps"] == 1000, "omitted fee defaults to 1000 bps"
    assert data["payout_balance_cents"] == 0
    assert data["mrr_cents"] == 0


def test_new_member_defaults_pending_with_token(api):
    """PRD §3.2: "On creation the member's `status` is `PENDING`, a one-time
    `verification_token` is issued, `email_bounced` is false, and the member
    records its `publication_id`."

    Design: Corner/entities/member_default_status_pending_and_token_issued
    """
    pub = new_publication(api)
    resp = api.create_member(pub["id"], {"email": "m@x.com", "display_name": "M"}, ANON)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"
    assert data["email_bounced"] is False
    assert data.get("verification_token"), "a verification_token must be issued"


def test_tier_is_free_true_for_rank_zero(api):
    """PRD §3.1: "the computed `is_free` flag is true exactly when `tier_rank` is
    zero (equivalently, when the monthly price is zero)."

    Design: Corner/entities/computed_tier_is_free_true_for_rank_zero
    """
    pub = new_publication(api)
    resp = api.create_tier(
        pub["id"],
        {"name": "Free", "tier_rank": 0, "monthly_price_cents": 0, "trial_days": 0},
        CREATOR,
    )
    data = validate_success(resp, expected_status=201)
    assert data["is_free"] is True


def test_create_tier_missing_tier_rank_returns_422(api):
    """PRD §2.5: "the request body is present with all required fields, valid
    types and enum values, and honored numeric ranges; otherwise `ERR_VALIDATION`
    (422)."
    PRD §3.1: "A tier carries a `name`, a `tier_rank`, a `monthly_price_cents`,
    and an optional `trial_days` that defaults to zero."

    Design: Corner/entities/create_tier_missing_required_returns_422
    """
    pub = new_publication(api)
    resp = api.create_tier(pub["id"], {"name": "Bad", "monthly_price_cents": 1000}, CREATOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_member_email_unique_per_publication(api):
    """PRD §3.2: "The email must be unique within the publication, and a collision
    is rejected with `ERR_EMAIL_TAKEN`."

    Design: Corner/entities/member_email_unique_per_publication_returns_409
    """
    pub = new_publication(api)
    api.create_member(pub["id"], {"email": "m@x.com", "display_name": "M"}, ANON)
    resp = api.create_member(pub["id"], {"email": "m@x.com", "display_name": "M2"}, ANON)
    validate_error(resp, ApiErrorId.ERR_EMAIL_TAKEN.value)


def test_tier_rank_unique_per_publication(api):
    """PRD §3.1: "The `tier_rank` is a non-negative integer that must be unique
    within the publication ... and a duplicate rank is rejected with
    `ERR_TIER_RANK_TAKEN`."

    Design: Corner/entities/tier_rank_unique_per_publication_returns_409
    """
    pub = new_publication(api)
    api.create_tier(
        pub["id"],
        {"name": "Plus", "tier_rank": 1, "monthly_price_cents": 1000, "trial_days": 0},
        CREATOR,
    )
    resp = api.create_tier(
        pub["id"],
        {"name": "Plus2", "tier_rank": 1, "monthly_price_cents": 2000, "trial_days": 0},
        CREATOR,
    )
    validate_error(resp, ApiErrorId.ERR_TIER_RANK_TAKEN.value)


def test_verify_member_transitions_to_verified(api):
    """PRD §3.2: "To activate their account, the member (or an anonymous holder
    of the token) submits the `verification_token`; a match moves `status` from
    `PENDING` to `VERIFIED`."

    Design: Corner/endpoints/verify_member_transitions_to_verified
    """
    pub = new_publication(api)
    member = new_member(api, pub["id"])
    resp = api.verify_member(
        member["id"], {"verification_token": member["verification_token"]}, ANON
    )
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "VERIFIED"


def test_list_members_returns_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list responses include `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/endpoints/list_members_returns_pagination_envelope
    """
    pub = new_publication(api)
    api.create_member(pub["id"], {"email": "m@x.com", "display_name": "M"}, ANON)
    resp = api.list_members(pub["id"], CREATOR)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
