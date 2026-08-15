"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints;
the runner relaunches the server before every test, so nothing carries over.
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" assertion rather than a confusing test assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_photographer_payload,
    create_story_request_payload,
    commission_decision_payload,
    wire_stock_decision_payload,
    assignment_image_payload,
    ingest_image_payload,
    create_license_payload,
    usage_run_payload,
    create_release_payload,
    create_claim_payload,
    create_payment_run_payload,
)
from .test_users import TEST_USERS, make_photographer_headers, make_rights_manager_headers

EDITOR = TEST_USERS["photo_editor_headers"]
RIGHTS = TEST_USERS["rights_manager_headers"]
ARCHIVIST = TEST_USERS["archivist_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


def _setup(resp, what: str):
    assert resp.status_code // 100 == 2, (
        f"Setup failed ({what}): HTTP {resp.status_code}: {resp.text}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return _setup(api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM), "set clock")


# ---------------------------------------------------------------------------
# Photographers / stories
# ---------------------------------------------------------------------------

def create_photographer(**overrides) -> dict:
    return _setup(
        api_client.create_photographer(create_photographer_payload(**overrides), EDITOR),
        "create photographer",
    )


def create_story(**overrides) -> dict:
    return _setup(
        api_client.create_story_request(create_story_request_payload(**overrides), EDITOR),
        "create story request",
    )


def get_photographer_fresh(photographer_id: str, headers=None) -> dict:
    return _setup(api_client.get_photographer(photographer_id, headers or FINANCE), "read photographer")


def get_story_fresh(story_id: str, headers=None) -> dict:
    return _setup(api_client.get_story_request(story_id, headers or EDITOR), "read story request")


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

def commission_assignment(photographer_id: str, story_id: str = None,
                          story_overrides: dict = None, **decide_overrides):
    """Open (or reuse) a story and decide COMMISSION against the photographer.

    Returns (decided_story, assignment_id).
    """
    if story_id is None:
        story = create_story(**(story_overrides or {}))
        story_id = story["id"]
    decided = _setup(
        api_client.decide_story_request(
            story_id, commission_decision_payload(photographer_id, **decide_overrides), EDITOR,
        ),
        "decide COMMISSION",
    )
    return decided, decided["commissioned_assignment_id"]


def submit_assignment_image(assignment_id: str, photographer_id: str, **overrides) -> dict:
    """Photographer submits one image to an own assignment (ownership-gated,
    so the entity-backed identity is threaded through)."""
    return _setup(
        api_client.submit_assignment_image(
            assignment_id,
            assignment_image_payload(**overrides),
            make_photographer_headers(photographer_id),
        ),
        "submit assignment image",
    )


def submit_assignment(assignment_id: str, photographer_id: str) -> dict:
    return _setup(
        api_client.submit_assignment(assignment_id, make_photographer_headers(photographer_id)),
        "submit assignment",
    )


def get_assignment_fresh(assignment_id: str, headers=None) -> dict:
    return _setup(api_client.get_assignment(assignment_id, headers or EDITOR), "read assignment")


def create_accepted_assignment(photographer_overrides: dict = None,
                               shoot_start: str = "2026-08-10T09:00:00Z",
                               shoot_end: str = "2026-08-11T17:00:00Z",
                               num_images: int = 1,
                               accept_at: str = "2026-08-12T00:00:00Z",
                               decide_overrides: dict = None) -> dict:
    """Full lifecycle: photographer -> story -> COMMISSION -> images -> submit ->
    (clock to accept_at) -> accept. Returns photographer/story/assignment/images."""
    photographer = create_photographer(**(photographer_overrides or {}))
    story = create_story()
    _, assignment_id = commission_assignment(
        photographer["id"], story_id=story["id"],
        shoot_start=shoot_start, shoot_end=shoot_end, **(decide_overrides or {}),
    )
    images = [
        submit_assignment_image(assignment_id, photographer["id"],
                                caption=f"Assignment take frame number {i + 1} on scene")
        for i in range(num_images)
    ]
    submit_assignment(assignment_id, photographer["id"])
    if accept_at is not None:
        set_logical_clock(accept_at)
    assignment = _setup(api_client.accept_assignment(assignment_id, EDITOR), "accept assignment")
    return {
        "photographer": photographer,
        "story": story,
        "assignment": assignment,
        "assignment_id": assignment_id,
        "images": images,
    }


# ---------------------------------------------------------------------------
# Images / licenses / usage runs
# ---------------------------------------------------------------------------

def ingest_wire_image(**overrides) -> dict:
    """Ingest a WIRE (or STOCK) image; returns the INGESTED image."""
    return _setup(api_client.ingest_image(ingest_image_payload(**overrides), RIGHTS), "ingest image")


def ingest_cleared_wire_image(**overrides) -> dict:
    """Ingest + clear; returns the CLEARED image."""
    image = ingest_wire_image(**overrides)
    return _setup(api_client.clear_image(image["id"], RIGHTS), "clear image")


def get_image_fresh(image_id: str, headers=None) -> dict:
    return _setup(api_client.get_image(image_id, headers or RIGHTS), "read image")


def get_image_version(image_id: str) -> int:
    return get_image_fresh(image_id)["version"]


def create_draft_license(image_id: str, **overrides) -> dict:
    """Create a DRAFT license, threading the OCC field expected_image_version
    from a fresh read (PRD §2.7)."""
    version = get_image_version(image_id)
    return _setup(
        api_client.create_license(
            image_id, create_license_payload(expected_image_version=version, **overrides), RIGHTS,
        ),
        "create license",
    )


def create_active_license(image_id: str, **overrides) -> dict:
    lic = create_draft_license(image_id, **overrides)
    return _setup(api_client.activate_license(lic["id"], RIGHTS), "activate license")


def record_usage_run(image_id: str, license_id: str, headers=None, **overrides) -> dict:
    return _setup(
        api_client.create_usage_run(
            image_id, usage_run_payload(license_id, **overrides), headers or RIGHTS,
        ),
        "record usage run",
    )


def setup_cleared_image_with_active_license(image_overrides: dict = None,
                                            license_overrides: dict = None):
    """CLEARED wire image + one ACTIVE license. Returns (image, license)."""
    image = ingest_cleared_wire_image(**(image_overrides or {}))
    lic = create_active_license(image["id"], **(license_overrides or {}))
    return get_image_fresh(image["id"]), lic


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

def create_release(image_id: str, **overrides) -> dict:
    return _setup(
        api_client.create_release(image_id, create_release_payload(**overrides), RIGHTS),
        "create release",
    )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def intake_claim(image_id: str, intaker_id: str = "rm_alice", **overrides) -> dict:
    """Intake a claim as a specific RightsManager user id (SoD stamping)."""
    return _setup(
        api_client.create_claim(
            create_claim_payload(image_id, **overrides),
            make_rights_manager_headers(intaker_id),
        ),
        "intake claim",
    )


def move_claim_under_review(claim_id: str, user_id: str = "rm_alice") -> dict:
    return _setup(
        api_client.review_claim(claim_id, make_rights_manager_headers(user_id)),
        "review claim",
    )


def get_claim_fresh(claim_id: str, headers=None) -> dict:
    return _setup(api_client.get_claim(claim_id, headers or RIGHTS), "read claim")


# ---------------------------------------------------------------------------
# Payment runs
# ---------------------------------------------------------------------------

def get_photographer_version(photographer_id: str) -> int:
    return get_photographer_fresh(photographer_id)["version"]


def create_payment_run(photographer_id: str,
                       period_start: str = "2026-08-01T00:00:00Z",
                       period_end: str = "2026-09-01T00:00:00Z") -> dict:
    """Create a DRAFT payment run, threading the OCC field
    expected_photographer_version from a fresh read (PRD §2.7)."""
    version = get_photographer_version(photographer_id)
    return _setup(
        api_client.create_payment_run(
            photographer_id,
            create_payment_run_payload(
                expected_photographer_version=version,
                period_start=period_start,
                period_end=period_end,
            ),
            FINANCE,
        ),
        "create payment run",
    )
