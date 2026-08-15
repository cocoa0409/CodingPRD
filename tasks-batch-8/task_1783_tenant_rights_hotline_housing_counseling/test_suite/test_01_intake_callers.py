"""Caller intake, pseudonymity defaults, and caller-role ownership (PRD §2.1, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_caller,
    assert_instant_equal,
    create_caller,
    create_caller_payload,
    is_valid_uuid,
    make_caller_headers,
    open_case,
    setup_hotline,
    start_active_session,
    validate_error,
    validate_success,
)


def test_caller_creation_defaults(api):
    """PRD §3.4: "New callers begin with `pii_purged` false and `do_not_aggregate` false."
    PRD §2.4: "`version` (integer): starts at 1 at creation and increments by one on
    every mutation, including mutations caused by cascaded side effects originating
    elsewhere."
    PRD §2.5: "At startup, before any operator intervention, the logical clock reads
    exactly 2026-08-01T00:00:00Z."
    PRD §3.4: "Intake is public. An unauthenticated caller — role `Anonymous` —
    registers with a pseudonymous `alias`, an optional `phone` callback number, a
    `preferred_language`, a contact `channel` of `PHONE`, `CHAT`, `TTY`, or `VIDEO`,
    optional `accessibility_needs` flags such as TTY, ASL, or LARGE_PRINT (defaulting
    to an empty list), and the `is_anonymous` flag."

    Design: Corner/entities/caller_creation_defaults
    """
    resp = api.create_caller(
        create_caller_payload(
            alias="caller-1", phone="+15550001", preferred_language="en",
            channel="PHONE", is_anonymous=False,
        ),
        TEST_USERS["anonymous_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert_caller(data)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert_instant_equal(data["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"
    assert data["pii_purged"] is False
    assert data["do_not_aggregate"] is False
    assert data["accessibility_needs"] == [], "accessibility_needs defaults to []"


def test_anonymous_caller_with_phone_rejected(api):
    """PRD §3.4: "Anonymous callers must have a null `phone`; a non-null value is
    rejected as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/caller_anonymous_phone_rejected
    """
    resp = api.create_caller(
        create_caller_payload(
            alias="anon-1", phone="+15550009", preferred_language="en",
            channel="PHONE", is_anonymous=True,
        ),
        TEST_USERS["anonymous_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_caller_cannot_read_other_caller(api):
    """PRD §2.1: "When `X-User-Role` is `Caller`, `X-User-ID` is the `id` of the
    acting `Caller`; ownership checks on any caller-scoped resource compare the
    path's caller identifier — or a consent's `caller_id` — to `X-User-ID`."
    PRD §2.10: "a `Caller` may act only on their own record, a counselor may submit
    or withdraw only their own scripts, and the actor recording a training
    certification must differ from the subject counselor — otherwise `ERR_FORBIDDEN`."

    Design: Corner/rbac/caller_cannot_read_other_caller
    """
    caller_a = create_caller(alias="caller-a", phone="+15550010")
    caller_b = create_caller(alias="caller-b", phone="+15550011")

    cross = api.get_caller(caller_b["id"], make_caller_headers(caller_a["id"]))
    validate_error(cross, ApiErrorId.ERR_FORBIDDEN)

    own = api.get_caller(caller_a["id"], make_caller_headers(caller_a["id"]))
    own_data = validate_success(own, expected_status=200)
    assert own_data["id"] == caller_a["id"]


def test_anonymous_cannot_read_case(api):
    """PRD §2.1: "Each endpoint admits a defined set of roles (see §4); an
    authenticated party attempting an operation outside that set is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/anonymous_cannot_read_case
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)

    resp = api.get_case(case["id"], TEST_USERS["anonymous_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
