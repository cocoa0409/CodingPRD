"""Authentication, role authorization, ownership, optimistic concurrency,
and not-found reads.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_category_payload,
    create_contest_event_payload,
)
from test_helpers.test_users import TEST_USERS

LEAD = TEST_USERS["contest_lead_headers"]


# ---------------------------------------------------------------------------
# Authentication and role authorization
# ---------------------------------------------------------------------------

def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request to the API carries two mandatory HTTP headers: `X-User-ID`, which identifies the acting caller, and `X-User-Role`, which names the caller's operational capacity."
    PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value not in this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    The request is sent with no auth headers at all.

    Design: Corner/validations/missing_headers_unauthenticated
    """
    resp = api.create_contest_event(
        create_contest_event_payload(name="CosCon"), headers=None
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_contestant_cannot_create_category(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/categories` | Create a category in a contest (starts `DRAFT`) | ContestLead |"

    Design: Corner/rbac/rbac_contestant_cannot_create_category
    """
    contest = fx.create_contest()
    contestant = fx.create_contestant()
    resp = api.create_category(
        create_category_payload(contest["id"], name="Sneaky",
                                skill_division="NOVICE", prize_purse_cents=1000),
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_judge_cannot_perform_safety_check(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/entries/{id}/safety-check` | Record a prop/weapon safety verdict (supports re-inspection) | SafetyOfficer |"

    Design: Corner/rbac/rbac_judge_cannot_perform_safety_check
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, category["id"], title="E1")
    judge = fx.create_judge(contest["id"], [category["id"]])

    resp = api.safety_check_entry(
        entry["id"], {"verdict": "APPROVED"}, fx.judge_headers(judge)
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert fx.get_entry(entry["id"])["safety_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_entry_patch_by_non_owner_rejected(api):
    """PRD §2.1: "When `X-User-Role` is `Contestant`, `X-User-ID` is the `id` of the acting `Contestant`; ownership checks on any resource that references a `Contestant` compare the resource's foreign-key field (such as `contestant_id`) to `X-User-ID`."
    PRD §3.3: "The request must originate from the contestant themselves — a body `contestant_id` that does not equal the caller's `X-User-ID` is rejected with `ERR_NOT_OWNER`"

    Another contestant's PATCH — even with a correct OCC version — fails.

    Design: Corner/validations/entry_patch_by_non_owner_returns_not_owner
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    c1 = fx.create_contestant(full_name="C One")
    c2 = fx.create_contestant(full_name="C Two")
    entry = fx.create_entry(c1, category["id"], title="E1")

    resp = api.update_entry(
        entry["id"],
        {"title": "Hijack", "expected_entry_version": entry["version"]},
        fx.contestant_headers(c2),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)

    after = fx.get_entry(entry["id"])
    assert after["title"] == "E1"
    assert after["version"] == entry["version"]


# ---------------------------------------------------------------------------
# Optimistic concurrency control
# ---------------------------------------------------------------------------

def test_category_update_stale_version_rejected(api):
    """PRD §2.6: "A category edit request must carry `expected_category_version` equal to the `version` the caller last observed on that `Category`; if the category's current `version` has since advanced (because another lead changed the configuration, or a contest-level cascade bumped the category), the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.4: "`version` is an integer that increments on every mutation."

    Design: Corner/cross_cutting_layers/occ_category_update_stale_version
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    observed = category["version"]

    first = validate_success(
        api.update_category(
            category["id"],
            {"max_entries": 9, "expected_category_version": observed},
            LEAD,
        )
    )
    assert first["max_entries"] == 9
    assert first["version"] == observed + 1

    resp_stale = api.update_category(
        category["id"],
        {"max_entries": 7, "expected_category_version": observed},
        LEAD,
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

    after = fx.get_category(category["id"])
    assert after["max_entries"] == 9
    assert after["version"] == observed + 1


def test_entry_update_stale_version_rejected(api):
    """PRD §2.6: "An entry edit request must carry `expected_entry_version` equal to the `version` the caller last observed on that `Entry`; if the entry's current `version` has since advanced (because a safety re-inspection wrote a new verdict, for example), the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.4: "`version` is an integer that increments on every mutation."

    Design: Corner/cross_cutting_layers/occ_entry_update_stale_version
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, category["id"], title="E1")
    headers = fx.contestant_headers(contestant)
    observed = entry["version"]

    first = validate_success(
        api.update_entry(
            entry["id"],
            {"title": "Renamed", "expected_entry_version": observed},
            headers,
        )
    )
    assert first["title"] == "Renamed"
    assert first["version"] == observed + 1

    resp_stale = api.update_entry(
        entry["id"],
        {"title": "Hijack", "expected_entry_version": observed},
        headers,
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

    after = fx.get_entry(entry["id"])
    assert after["title"] == "Renamed"
    assert after["version"] == observed + 1


# ---------------------------------------------------------------------------
# Not-found reads
# ---------------------------------------------------------------------------

def test_get_missing_entry_returns_not_found(api):
    """PRD §2.8: "then path-id and body-foreign-key resolution in left-to-right order (`ERR_NOT_FOUND`)"

    A well-formed but nonexistent entry id returns 404 ERR_NOT_FOUND.

    Design: Corner/entities/get_missing_entry_returns_not_found
    """
    resp = api.get_entry(NON_EXISTENT_UUID, LEAD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
