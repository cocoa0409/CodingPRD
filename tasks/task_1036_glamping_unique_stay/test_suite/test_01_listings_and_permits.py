"""Listing creation, the permit gate, and the listing/permit state cycles.

Covers difficulty queue A (non-linear state machine, cross-entity dependency)
and corner queue B (entity creation/validation, permit transitions).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_host_headers, make_guest_headers, make_permit_reviewer_headers,
    TEST_USERS,
    create_listing_payload, create_permit_payload, create_seasonal_rate_payload,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["permit_reviewer_headers"]


# ---------------------------------------------------------------- corner: entities
def test_create_listing_returns_201_with_system_fields(api):
    """PRD §3.2: "A host creates a listing whose `status` field begins at `DRAFT`."
    PRD §3.2: "`min_nights` (the default floor on stay length, at least 1,
    defaulting to 1 when omitted)"
    PRD §3.2: "A new listing's `reserved_nights_count` is 0 and its `version` is 1."

    Design: Corner/entities/create_listing_returns_201_with_system_fields
    """
    host = fx.onboard_host()
    resp = api.create_listing(
        create_listing_payload(host["id"], title="New Yurt", site_type="YURT",
                               max_guests=3, base_nightly_rate_cents=15000),
        make_host_headers(host["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["reserved_nights_count"] == 0
    assert data["min_nights"] == 1


def test_create_listing_missing_required_field_returns_validation(api):
    """PRD §2.9: "Then body well-formedness — required fields present, enum values
    legal, integers within range, `rating` between 1 and 5 inclusive, dates
    parseable, and `check_out` strictly after `check_in` — any breach yields
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_listing_missing_required_field_returns_validation
    """
    host = fx.onboard_host()
    payload = {"host_id": host["id"], "title": "No Type", "max_guests": 3,
               "base_nightly_rate_cents": 15000}  # site_type omitted
    resp = api.create_listing(payload, make_host_headers(host["id"]))
    validate_error(resp, "ERR_VALIDATION")


def test_create_listing_invalid_enum_returns_validation(api):
    """PRD §2.9: "Then body well-formedness — required fields present, enum values
    legal, integers within range, `rating` between 1 and 5 inclusive, dates
    parseable, and `check_out` strictly after `check_in` — any breach yields
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_listing_invalid_enum_returns_validation
    """
    host = fx.onboard_host()
    resp = api.create_listing(
        create_listing_payload(host["id"], title="Bad Enum", site_type="CASTLE",
                               max_guests=3, base_nightly_rate_cents=15000),
        make_host_headers(host["id"]),
    )
    validate_error(resp, "ERR_VALIDATION")


def test_get_listing_nonexistent_returns_not_found(api):
    """PRD §2.9: "the first identifier that names a non-existent resource produces
    `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier or body content is
    examined."

    Design: Corner/entities/get_listing_nonexistent_returns_not_found
    """
    resp = api.get_listing("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(resp, "ERR_NOT_FOUND")


# --------------------------------------------------------- corner: seasonal rate
def test_seasonal_rate_overlap_rejected(api):
    """PRD §3.3: "A new window that would overlap an existing window on the same
    listing is rejected with `ERR_RATE_OVERLAP` (HTTP 409)."

    Design: Corner/validations/seasonal_rate_overlap_rejected
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"], site_type="CABIN", max_guests=4,
                                base_nightly_rate_cents=20000)
    fx.add_rate(host["id"], listing["id"], "2026-07-01T00:00:00Z",
                "2026-07-15T00:00:00Z", 20000)
    resp = api.create_seasonal_rate(
        listing["id"],
        create_seasonal_rate_payload(listing["id"], "2026-07-05T00:00:00Z",
                                     "2026-07-20T00:00:00Z", 22000),
        make_host_headers(host["id"]),
    )
    validate_error(resp, "ERR_RATE_OVERLAP")


# ------------------------------------------------- corner: permit state machine
def test_submit_permit_from_approved_returns_invalid_state(api):
    """PRD §2.9: "Then the target's state admits the requested transition — a
    generic mismatch yields `ERR_INVALID_STATE` (HTTP 400)."

    Design: Corner/state_machines/submit_permit_from_approved_returns_invalid_state
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"])
    permit = fx.file_permit(host["id"], listing["id"])
    fx.submit_permit(host["id"], permit["id"])
    fx.decide_permit(permit["id"], outcome="APPROVE")
    resp = api.submit_permit(permit["id"], make_host_headers(host["id"]))
    validate_error(resp, "ERR_INVALID_STATE")


def test_decision_on_already_decided_permit_returns_already_decided(api):
    """PRD §3.2: "the decision is only valid while the permit is in `SUBMITTED`,
    and any decision attempted on a permit not in `SUBMITTED` is rejected with
    `ERR_PERMIT_ALREADY_DECIDED` (HTTP 400)."

    Design: Corner/state_machines/decision_on_already_decided_permit_returns_already_decided
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"])
    permit = fx.file_permit(host["id"], listing["id"])
    fx.submit_permit(host["id"], permit["id"])
    fx.decide_permit(permit["id"], outcome="APPROVE")
    resp = api.decide_permit(permit["id"], {"outcome": "REJECT"}, REVIEWER)
    validate_error(resp, "ERR_PERMIT_ALREADY_DECIDED")


# --------------------------------- difficulty: non_linear_state_machine (3a)
def test_listing_suspend_moves_to_suspended(api):
    """PRD §3.2: "A host may suspend a `LISTED` listing, moving it to `SUSPENDED`
    and declining its `REQUESTED` bookings as above."

    Design: Difficulty/non_linear_state_machine/listing_suspend_reinstate_cycle
    """
    env = fx.setup_listed_listing(site_type="CABIN", cancellation_policy="MODERATE")
    listing = fx.suspend(env["host"]["id"], env["listing"]["id"])
    assert listing["status"] == "SUSPENDED"


def test_listing_reinstate_returns_to_listed_after_cycle(api):
    """PRD §3.2: "Reinstating a `SUSPENDED` listing returns it to `LISTED`, but
    only when the listing's permit is still `APPROVED` — otherwise the
    reinstatement is likewise rejected with `ERR_PERMIT_NOT_APPROVED`."

    Design: Difficulty/non_linear_state_machine/listing_suspend_reinstate_cycle
    """
    env = fx.setup_listed_listing(site_type="CABIN", cancellation_policy="MODERATE")
    fx.suspend(env["host"]["id"], env["listing"]["id"])
    resp = api.reinstate_listing(env["listing"]["id"],
                                 make_host_headers(env["host"]["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "LISTED"


# --------------------------------- difficulty: non_linear_state_machine (3b)
def test_permit_resubmit_returns_to_submitted(api):
    """PRD §3.2: "a host may revise and resubmit, which moves the permit from
    `REJECTED` back to `SUBMITTED` and clears `review_notes` to null."

    Design: Difficulty/non_linear_state_machine/permit_reject_resubmit_cycle
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"])
    permit = fx.file_permit(host["id"], listing["id"], permit_type="CAMPING")
    fx.submit_permit(host["id"], permit["id"])
    fx.decide_permit(permit["id"], outcome="REJECT", review_notes="Setback too small")
    resp = api.submit_permit(permit["id"], make_host_headers(host["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED"


def test_permit_resubmit_clears_review_notes(api):
    """PRD §3.2: "a host may revise and resubmit, which moves the permit from
    `REJECTED` back to `SUBMITTED` and clears `review_notes` to null."

    Design: Difficulty/non_linear_state_machine/permit_reject_resubmit_cycle
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"])
    permit = fx.file_permit(host["id"], listing["id"], permit_type="CAMPING")
    fx.submit_permit(host["id"], permit["id"])
    fx.decide_permit(permit["id"], outcome="REJECT", review_notes="Setback too small")
    resp = api.submit_permit(permit["id"], make_host_headers(host["id"]))
    data = validate_success(resp, 200)
    assert data["review_notes"] is None


# --------------------- difficulty: cross_entity_state_dependency (7b) publish
def test_publish_with_unapproved_permit_rejected(api):
    """PRD §3.2: "the listing's permit must be `APPROVED`, else the request is
    rejected with `ERR_PERMIT_NOT_APPROVED` (HTTP 400)"

    Design: Difficulty/cross_entity_state_dependency/listing_publish_requires_permit_approved
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"])
    permit = fx.file_permit(host["id"], listing["id"])
    fx.submit_permit(host["id"], permit["id"])  # SUBMITTED, not APPROVED
    fx.add_rate(host["id"], listing["id"], "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z", 20000)
    resp = api.publish_listing(listing["id"], make_host_headers(host["id"]))
    validate_error(resp, "ERR_PERMIT_NOT_APPROVED")


def test_publish_with_unapproved_permit_leaves_listing_pending(api):
    """PRD §3.2: "With an `APPROVED` permit and at least one seasonal rate on the
    books, a host publishes the listing, transitioning it from `PENDING_PERMIT`
    to `LISTED`."
    PRD §3.2: "Submitting a permit moves it from `DRAFT` to `SUBMITTED`. As a side
    effect, if the parent listing was still in `DRAFT`, that submission advances
    the listing from `DRAFT` to `PENDING_PERMIT`."

    Design: Difficulty/cross_entity_state_dependency/listing_publish_requires_permit_approved
    """
    host = fx.onboard_host()
    listing = fx.create_listing(host["id"])
    permit = fx.file_permit(host["id"], listing["id"])
    fx.submit_permit(host["id"], permit["id"])
    fx.add_rate(host["id"], listing["id"], "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z", 20000)
    api.publish_listing(listing["id"], make_host_headers(host["id"]))
    after = get_success_data(api.get_listing(listing["id"], make_host_headers(host["id"])))
    assert after["status"] == "PENDING_PERMIT"
