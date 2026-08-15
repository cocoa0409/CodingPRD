"""Community stand-up, catalog intake, and price-phase windows (PRD §2.6, §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_community,
    assert_instant_equals,
    api_client,
    create_community,
    create_price_phase,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["sales_director_headers"]
AGENT = TEST_USERS["sales_agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_community_creation_defaults_and_envelope():
    """PRD §3.1: "The new community starts in `SETUP` status with
    `incentive_budget_remaining_cents` initialized to the full total."
    PRD §2.6: "At startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`."

    Design: Corner/entities/community_creation_defaults_and_envelope
    """
    resp = api_client.create_community(
        {"name": "Cedar Ridge", "incentive_budget_total_cents": 1_000_000},
        DIRECTOR,
    )
    community = validate_success(resp, 201)
    assert_community(community)
    assert community["status"] == "SETUP", "initial status must be SETUP"
    assert community["incentive_budget_remaining_cents"] == 1_000_000, (
        "remaining budget must begin equal to the total"
    )
    assert isinstance(community["version"], int)
    assert_instant_equals(
        community["created_at"], DEFAULT_CLOCK_ISO,
        "created_at stamped from the logical clock at startup",
    )


def test_option_item_invalid_enum_category_rejected():
    """PRD §3.1: "are created with a `community_id`, an `option_name`, a
    `category` drawn from `STRUCTURAL`, `KITCHEN`, `BATH`, `FLOORING`,
    `ELECTRICAL`, or `OUTDOOR`, a unit `price_cents` strictly greater than
    zero, and two stage markers: `cutoff_stage`, the last build stage during
    which the option may be freely selected or re-opened, and `install_stage`,
    the stage after which a confirmed selection is treated as physically
    installed."
    PRD §3.1: "A malformed payload — a missing required field, a wrong type, an
    unknown enum member, a negative price, or an elevations list violating its
    shape constraints — is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/option_item_invalid_enum_category_rejected
    """
    community = create_community()
    resp = api_client.create_option_catalog_item(
        {
            "community_id": community["id"],
            "option_name": "Fridge",
            "category": "APPLIANCES",
            "price_cents": 300_000,
            "cutoff_stage": "DRYWALL",
            "install_stage": "FINAL_WALKTHROUGH",
        },
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_overlapping_price_phase_window_rejected():
    """PRD §3.1: "A community's phase windows may touch but never overlap: a new
    phase whose window intersects an existing phase of the same community is
    rejected with `ERR_PHASE_WINDOW_OVERLAP`, while one whose `effective_from`
    lands exactly on the previous phase's `effective_to` is legal adjacency."

    Design: Difficulty/resource_temporal_overlap/price_phase_window_overlap_vs_adjacency
    """
    community = create_community()
    create_price_phase(community["id"])  # P1 [2026-08-01, 2026-09-01)

    resp = api_client.create_price_phase(
        {
            "community_id": community["id"],
            "phase_name": "P-Overlap",
            "uplift_pct": 0.04,
            "effective_from": "2026-08-15T00:00:00Z",
            "effective_to": "2026-10-01T00:00:00Z",
        },
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_PHASE_WINDOW_OVERLAP)

    data, meta = validate_paginated(
        api_client.list_price_phases(community["id"], AGENT)
    )
    assert meta["total_count"] == 1, (
        f"rejected overlapping phase must not persist, got {meta['total_count']}"
    )
    assert data[0]["phase_name"] == "P1"


def test_adjacent_price_phase_window_allowed():
    """PRD §3.1: "A community's phase windows may touch but never overlap: a new
    phase whose window intersects an existing phase of the same community is
    rejected with `ERR_PHASE_WINDOW_OVERLAP`, while one whose `effective_from`
    lands exactly on the previous phase's `effective_to` is legal adjacency."
    PRD §3.1: "A phase's `status` is never set by the client — it is derived
    from the logical clock at creation and re-derived on every clock set:
    `SCHEDULED` while the current instant is earlier than `effective_from`,
    `ACTIVE` while the instant is at or after `effective_from` and strictly
    before `effective_to`, and `EXPIRED` once the instant reaches
    `effective_to`."

    Design: Difficulty/resource_temporal_overlap/price_phase_window_overlap_vs_adjacency
    """
    community = create_community()
    create_price_phase(community["id"])  # P1 [2026-08-01, 2026-09-01)

    resp = api_client.create_price_phase(
        {
            "community_id": community["id"],
            "phase_name": "P2",
            "uplift_pct": 0.05,
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_to": "2026-10-01T00:00:00Z",
        },
        DIRECTOR,
    )
    phase2 = validate_success(resp, 201)
    assert phase2["status"] == "SCHEDULED", (
        "now (2026-08-01) is earlier than effective_from, so the new phase is SCHEDULED"
    )

    _data, meta = validate_paginated(
        api_client.list_price_phases(community["id"], AGENT)
    )
    assert meta["total_count"] == 2, "adjacent phase is legal and persists"


def test_phase_status_sweep_on_clock():
    """PRD §3.1: "A phase's `status` is never set by the client — it is derived
    from the logical clock at creation and re-derived on every clock set:
    `SCHEDULED` while the current instant is earlier than `effective_from`,
    `ACTIVE` while the instant is at or after `effective_from` and strictly
    before `effective_to`, and `EXPIRED` once the instant reaches
    `effective_to`."
    PRD §2.6: "Setting the clock deterministically executes a scheduled sweep
    at the new instant, in three parts: every price phase's status is re-derived
    against its window, every reservation hold whose expiry has been reached is
    released, and every agreement whose contingency deadline has passed with
    unresolved contingencies is auto-cancelled."

    Design: Corner/complexity_layers/phase_status_sweep_on_clock
    """
    from test_helpers import advance_clock

    community = create_community()
    phase = create_price_phase(
        community["id"],
        phase_name="P2",
        uplift_pct=0.05,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    assert phase["status"] == "SCHEDULED", "future window at creation"

    advance_clock("2026-09-15T00:00:00Z")
    data, _meta = validate_paginated(
        api_client.list_price_phases(community["id"], AGENT)
    )
    assert data[0]["id"] == phase["id"]
    assert data[0]["status"] == "ACTIVE", "inside [from, to) is ACTIVE"

    advance_clock("2026-10-02T00:00:00Z")
    data, _meta = validate_paginated(
        api_client.list_price_phases(community["id"], AGENT)
    )
    assert data[0]["status"] == "EXPIRED", "at or past effective_to is EXPIRED"
