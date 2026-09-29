"""Corner coverage for role fencing, resource ownership and segregation of duties."""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    COACH_ALT_USER_ID,
    COACH_USER_ID,
    REVIEWER_ALT_USER_ID,
    REVIEWER_USER_ID,
    TEST_USERS,
    build_rating_spine,
    create_coaching_allocation_payload,
    create_coaching_session_payload,
    create_enrolled_provider,
    create_reliable_observer,
    create_staff_credential_payload,
    create_subsidy_claim_payload,
    file_appeal,
    make_coach_headers,
    make_observer_headers,
    make_provider_headers,
    make_reviewer_headers,
    points_map,
    registry_link_payload,
    score_payload,
    set_clock,
    setup_active_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FAMILY = TEST_USERS["family_headers"]

TIER_ONE_POINTS = points_map(learning=12, staff=8)


def test_peer_roles_cannot_enter_each_others_exclusive_operations(api):
    """PRD §2.7: "Second, role authorization: the acting role must appear in the target
    endpoint's permitted-role list, or the request fails with `ERR_FORBIDDEN_ROLE` and HTTP
    403."
    PRD §4: "| POST | `/providers/{provider_id}/subsidy-claims` | Submit a monthly subsidy
    reimbursement claim with child-days by age band. | `Provider` |"
    PRD §4: "| POST | `/providers/{provider_id}/coaching-allocations` | Allocate coaching hours
    to a provider for a period, computing the administrative fee and the binding spend cap. |
    `StateAdministrator` |"
    PRD §4: "| GET | `/providers/{provider_id}/credential-compliance` | Computed read of the
    provider's credential compliance breakdown. | `StateAdministrator`, `Provider` |"

    Design: Corner/rbac/peer_roles_cannot_enter_each_others_exclusive_operations
    """
    set_clock("2026-08-03T00:00:00Z")
    provider = create_enrolled_provider(active_staff_fte=1.00)
    provider_id = provider["id"]

    validate_error(
        api.create_subsidy_claim(
            provider_id,
            create_subsidy_claim_payload("2026-09", infant=4, toddler=0, preschool=0),
            make_coach_headers(COACH_USER_ID),
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_coaching_allocation(
            provider_id,
            create_coaching_allocation_payload(COACH_USER_ID),
            make_provider_headers(provider_id),
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.get_credential_compliance(provider_id, FAMILY), "ERR_FORBIDDEN_ROLE", 403
    )

    _, claim_meta = validate_paginated(
        api.list_subsidy_claims(ADMIN, params={"provider_id": provider_id})
    )
    assert claim_meta["total_count"] == 0, (
        f"the coach's refused claim must not exist, got {claim_meta['total_count']}"
    )
    _, allocation_meta = validate_paginated(
        api.list_coaching_allocations(ADMIN, params={"provider_id": provider_id})
    )
    assert allocation_meta["total_count"] == 0, (
        f"the provider's refused allocation must not exist, got {allocation_meta['total_count']}"
    )
    unchanged = validate_success(api.get_provider(provider_id, ADMIN))
    assert unchanged["status"] == "ENROLLED", (
        f"no refused request may change provider standing, got {unchanged['status']}"
    )
    assert unchanged["credential_compliance_pct"] == pytest.approx(0.00, abs=0.005)


def test_uninvolved_observer_is_blocked_then_the_named_lead_scores_but_cannot_finalize(api):
    """PRD §2.7: "Fourth, ownership: for the two entity-backed roles the acting `X-User-ID`
    must equal the owning entity's `id` — a `Provider` acts only on resources whose provider
    linkage resolves to its own identifier, whether that linkage is direct, or reached through
    a rating cycle, or reached from a self-assessment through its cycle to the provider, or
    reached from a grant or allocation to its provider; an `Observer` may write scores only for
    a visit that names it as `lead_observer_id` or `secondary_observer_id`. A failure is
    `ERR_NOT_RESOURCE_OWNER` with HTTP 403."
    PRD §3.4: "Scores are append-only: a submission records a new row whose
    `observation_visit_id` names the visit, whose `observer_id` names the acting observer,
    whose `attempt_no` is one greater than the highest attempt already recorded for that
    combination of visit, observer, and subscale, and whose `is_current` flag is true; the
    previously current row for that same combination has its `is_current` set to false."
    PRD §3.4: "Finalization is reserved to the `StateAdministrator` — an observer may never
    finalize the visit whose scores they entered — and it forks into two branches that carry
    deliberately different side effects."

    Design: Corner/rbac/uninvolved_observer_blocked_then_named_observer_scores_and_cannot_finalize
    """
    window_start = "2026-08-06T09:00:00Z"
    ctx = build_rating_spine(
        stop_at="OBSERVATION_SCHEDULED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        window_start=window_start,
    )
    visit_id = ctx["visit"]["id"]
    outsider = create_reliable_observer("Uninvolved Observer", anchor_agreement_pct=95.00)
    set_clock(window_start)

    validate_error(
        api.submit_score(
            visit_id,
            score_payload("SPACE_FURNISHINGS", 5.0),
            make_observer_headers(outsider["id"]),
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )

    row = validate_success(
        api.submit_score(
            visit_id,
            score_payload("SPACE_FURNISHINGS", 5.0),
            make_observer_headers(ctx["lead"]["id"]),
        ),
        201,
    )
    assert row["observer_id"] == ctx["lead"]["id"], (
        f"the row records the acting observer, got {row['observer_id']}"
    )
    assert row["attempt_no"] == 1, f"the first attempt carries attempt_no 1, got {row['attempt_no']}"
    assert row["is_current"] is True

    validate_error(
        api.finalize_visit(visit_id, make_observer_headers(ctx["lead"]["id"])),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    visit = validate_success(api.get_observation_visit(visit_id, ADMIN))
    assert visit["status"] == "IN_PROGRESS", (
        f"the first accepted score advances SCHEDULED -> IN_PROGRESS, got {visit['status']}"
    )
    assert visit["finalized_on"] is None
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_SCHEDULED", (
        f"the refused finalize leaves the cycle untouched, got {cycle['status']}"
    )
    rows, meta = validate_paginated(
        api.list_observation_scores(ADMIN, params={"observation_visit_id": visit_id})
    )
    assert meta["total_count"] == 1, (
        f"the outsider's refused write created no row, got {meta['total_count']}"
    )
    assert rows[0]["observer_id"] == ctx["lead"]["id"]


def test_coach_identifier_mismatch_blocks_the_session_write_before_the_period_check(api):
    """PRD §2.1: "The server records it as `coach_user_id` on the `CoachingAllocation` the
    administrator creates, and session writes require the acting `X-User-ID` to equal that
    allocation's `coach_user_id`; it is never compared to any entity's `id`."
    PRD §3.9: "Second, the period bounds: both `scheduled_start` and `scheduled_end` must fall
    inside the allocation's period from `period_start` to `period_end` inclusive, and
    `scheduled_end` must be strictly later than `scheduled_start`, or the request is refused
    with `ERR_SESSION_OUTSIDE_ALLOCATION_PERIOD` and HTTP 422."
    PRD §3.9: "An accepted session is created in `SCHEDULED`, adds its hours to the
    allocation's `scheduled_hours`, and subtracts them from the allocation's
    `remaining_hours`."

    Design: Corner/rbac/coach_user_id_mismatch_blocks_session_write_before_period_checks
    """
    ctx, allocation = setup_active_allocation(
        coach_user_id=COACH_USER_ID,
        period_start="2026-09-01",
        period_end="2026-09-30",
        allocated_hours=10.0,
        hourly_rate_cents=10_000,
    )
    assert allocation["status"] == "ACTIVE"
    outside_payload = create_coaching_session_payload(
        "2026-10-07T09:00:00Z", "2026-10-07T11:00:00Z"
    )

    validate_error(
        api.create_coaching_session(
            allocation["id"], outside_payload, make_coach_headers(COACH_ALT_USER_ID)
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.create_coaching_session(
            allocation["id"], outside_payload, make_coach_headers(COACH_USER_ID)
        ),
        "ERR_SESSION_OUTSIDE_ALLOCATION_PERIOD",
        422,
    )

    ledger = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(ledger["scheduled_hours"]) == pytest.approx(0.0, abs=0.05), (
        f"neither refused write may book hours, got {ledger['scheduled_hours']}"
    )
    assert float(ledger["remaining_hours"]) == pytest.approx(10.0, abs=0.05), (
        f"remaining_hours stays at allocated_hours, got {ledger['remaining_hours']}"
    )
    assert ledger["status"] == "ACTIVE"
    _, meta = validate_paginated(
        api.list_coaching_sessions(ADMIN, params={"coaching_allocation_id": allocation["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no session row may exist, got {meta['total_count']}"
    )


def test_credential_creation_is_shared_but_the_registry_link_is_administrator_only(api):
    """PRD §3.2: "Either the provider itself or a `StateAdministrator` registers a staff member
    by supplying that person's `staff_registry_id` — the identifier the professional development
    registry knows them by, which must be unique within the provider and otherwise raises
    `ERR_DUPLICATE_RESOURCE` — a `role_type` of `DIRECTOR`, `LEAD_TEACHER`, or `ASSISTANT`, a
    `credential_level` from 1 to 6, and an `fte` share greater than 0 and no greater than 1 with
    two decimal places."
    PRD §3.2: "The record is created with `registry_status` at `UNLINKED`, which contributes
    nothing to the numerator of compliance, and the provider's `credential_compliance_pct` is
    recomputed and its `version` incremented anyway."
    PRD §4: "| POST | `/staff-credentials/{credential_id}/registry-link` | Record the
    professional development registry's response for one staff credential. |
    `StateAdministrator` |"

    Design: Corner/rbac/staff_credential_creation_is_shared_but_provider_cannot_registry_link
    """
    set_clock("2026-08-03T00:00:00Z")
    provider = create_enrolled_provider(active_staff_fte=2.00)
    provider_id = provider["id"]
    provider_headers = make_provider_headers(provider_id)

    by_provider = validate_success(
        api.create_staff_credential(
            provider_id,
            create_staff_credential_payload(
                staff_registry_id="REG-P-001", role_type="DIRECTOR",
                credential_level=5, fte=1.00,
            ),
            provider_headers,
        ),
        201,
    )
    assert by_provider["registry_status"] == "UNLINKED", (
        f"a new record starts UNLINKED, got {by_provider['registry_status']}"
    )

    by_admin = validate_success(
        api.create_staff_credential(
            provider_id,
            create_staff_credential_payload(
                staff_registry_id="REG-A-001", role_type="LEAD_TEACHER",
                credential_level=4, fte=1.00,
            ),
            ADMIN,
        ),
        201,
    )
    assert by_admin["registry_status"] == "UNLINKED"

    validate_error(
        api.registry_link(by_provider["id"], registry_link_payload(), provider_headers),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    still_unlinked = validate_success(api.get_staff_credential(by_provider["id"], ADMIN))
    assert still_unlinked["registry_status"] == "UNLINKED", (
        f"the refused link changes nothing, got {still_unlinked['registry_status']}"
    )
    compliance = validate_success(api.get_provider(provider_id, ADMIN))
    assert compliance["credential_compliance_pct"] == pytest.approx(0.00, abs=0.005), (
        "UNLINKED records contribute nothing to the numerator, so compliance stays 0.00; "
        f"got {compliance['credential_compliance_pct']}"
    )
    rows, meta = validate_paginated(
        api.list_staff_credentials(
            ADMIN, params={"provider_id": provider_id, "registry_status": "UNLINKED"}
        )
    )
    assert meta["total_count"] == 2, (
        f"both records exist and both are UNLINKED, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {by_provider["id"], by_admin["id"]}


def test_segregation_of_duties_blocks_the_awarder_and_any_unassigned_reviewer(api):
    """PRD §2.7: "Fifth, segregation of duties on appeal review actions: the acting
    `AppealReviewer` identifier must differ from the awarding administrator's identifier stored
    on the cycle, and on every review action after the review has been started it must equal
    the identifier already recorded on the appeal; a failure is `ERR_SEGREGATION_OF_DUTIES`
    with HTTP 403."
    PRD §3.6: "Starting the review moves the appeal `FILED → UNDER_REVIEW` and stamps
    `reviewer_user_id` with the acting identifier; it requires that identifier to differ from
    the awarding administrator recorded on the cycle."
    PRD §3.6: "Filing immediately drives the cycle to `UNDER_APPEAL`, drives its publication
    state to `SUPPRESSED`, sets the provider's `public_listing_visible` to false, and
    increments the provider's `version` by 1."

    Design: Corner/rbac/segregation_of_duties_blocks_the_awarder_and_any_unassigned_reviewer
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        award_clock="2026-08-11T00:00:00Z",
    )
    cycle_id = ctx["cycle"]["id"]
    assert ctx["cycle"]["awarded_by_user_id"] == ADMIN_USER_ID, (
        f"the spine awards as {ADMIN_USER_ID}, got {ctx['cycle']['awarded_by_user_id']}"
    )
    appeal = file_appeal(ctx["provider"]["id"], cycle_id, "SCORING_ERROR",
                        "the learning environment composite is wrong")
    assert appeal["status"] == "FILED"

    validate_error(
        api.appeal_review_action(
            appeal["id"], {"action": "START"}, make_reviewer_headers(ADMIN_USER_ID)
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    started = validate_success(
        api.appeal_review_action(
            appeal["id"], {"action": "START"}, make_reviewer_headers(REVIEWER_USER_ID)
        )
    )
    assert started["status"] == "UNDER_REVIEW", (
        f"a distinct reviewer may start the review, got {started['status']}"
    )
    assert started["reviewer_user_id"] == REVIEWER_USER_ID, (
        f"START stamps the acting identifier, got {started['reviewer_user_id']}"
    )

    validate_error(
        api.appeal_review_action(
            appeal["id"],
            {"action": "DENY", "note": "not persuaded"},
            make_reviewer_headers(REVIEWER_ALT_USER_ID),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    held = validate_success(api.get_appeal(appeal["id"], ADMIN))
    assert held["status"] == "UNDER_REVIEW", (
        f"the second reviewer's DENY changes nothing, got {held['status']}"
    )
    assert held["decided_on"] is None
    assert held["info_request_count"] == 0
    assert held["reviewer_user_id"] == REVIEWER_USER_ID
    cycle = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert cycle["status"] == "UNDER_APPEAL", (
        f"filing drove the cycle to UNDER_APPEAL, got {cycle['status']}"
    )
    assert cycle["publication_status"] == "SUPPRESSED", (
        f"filing suppressed publication, got {cycle['publication_status']}"
    )
    assert cycle["awarded_by_user_id"] == ADMIN_USER_ID
    assert cycle["awarded_tier"] == 1
    _, meta = validate_paginated(api.list_appeals(ADMIN, params={"rating_cycle_id": cycle_id}))
    assert meta["total_count"] == 1, (
        f"exactly one appeal exists, got {meta['total_count']}"
    )
