"""Skill offer / request creation, defaults, enum & minute constraints, FK filters."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, make_member_headers,
    member_payload, skill_offer_payload, skill_request_payload,
    ApiErrorId,
    create_member,
)


def test_required_trust_tier_defaults_to_unverified_when_omitted(api):
    """PRD §3.2: "an offer may also declare a required_trust_tier (defaulting to
    UNVERIFIED) that a requester must meet or exceed before booking."

    Design: Corner/entities/defaults_offer_required_trust_tier
    """
    m = create_member(email_prefix="def")
    resp = api.create_skill_offer(
        {"member_id": m["id"], "skill_code": "GARDENING",
         "title": "G", "minutes_per_session": 60},
        headers=make_member_headers(m["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["required_trust_tier"] == "UNVERIFIED"


def test_invalid_trust_tier_enum_rejected(api):
    """PRD §2.4: "Member.trust_tier is one of UNVERIFIED, BASIC, TRUSTED, or ANCHOR,
    ordered strictly ascending."
    PRD §2.11: "Schema-shape validation — required fields present, enum values
    in the allowed set, minute inputs as integer multiples of 15 in the closed
    interval from 15 to 480, latest_start_utc strictly greater than
    earliest_start_utc, window_end_utc strictly greater than window_start_utc,
    ISO 8601 UTC datetimes — runs as the last band of checks and produces
    ERR_INVALID_REQUEST."

    Design: Corner/entities/type_constraint_invalid_enum_trust_tier
    """
    m = create_member(email_prefix="enum")
    resp = api.create_skill_offer(
        {"member_id": m["id"], "skill_code": "GARDENING",
         "title": "G", "minutes_per_session": 60,
         "required_trust_tier": "SUPERSTAR"},
        headers=make_member_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_minutes_per_session_must_be_multiple_of_15(api):
    """PRD §3.2: "Every offer commits to a fixed session length,
    minutes_per_session, which must be an integer multiple of 15 in the closed
    interval from 15 to 480 minutes"

    Design: Corner/entities/minutes_per_session_multiple_of_15_boundary
    """
    m = create_member(email_prefix="mps")
    resp = api.create_skill_offer(
        {"member_id": m["id"], "skill_code": "GARDENING",
         "title": "G", "minutes_per_session": 17},
        headers=make_member_headers(m["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# Design instance `Corner/endpoints/fk_reverse_reachability_offer_by_member_id`
# is SKIPPED: PRD does not state a rule mandating a member_id filter's
# semantics on GET /skill-offers — only the endpoint table row
# "List skill offers with filters" appears, which is endpoint-titular (C2) and
# does not uniquely-derive the expected filter behavior (two PRD-only readers
# could reasonably ship different filter surfaces).
