"""Role lists, ownership, and the standing that bars a member from resuming."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    log_leg,
    make_member_headers,
    make_vendor_headers,
    new_hub,
    new_member,
    read_lot,
    read_member,
    read_subscription,
    setup_fleet,
    setup_landed_lot,
    setup_member_subscription,
    setup_no_show_sequence,
    setup_open_season,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def test_a_member_may_not_run_the_catch_allocation(api):
    """PRD 2.1: "A request whose role is recognised but is not listed among the authorised roles
    for the endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "A `CsfAdmin` creates and advances seasons, creates the entire catalogue (share
    plans, delivery zones, pickup hubs, pickup windows, members, vessels, quota ledgers), creates
    and activates subscriptions, runs catch allocations and lot splits, verifies landings,
    creates and finalizes and pays settlement statements, raises and remediates recall notices,
    proposes substitutions, moves vessel compliance status, and sets the logical clock."

    Design: Corner/rbac/member_cannot_run_a_catch_allocation
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    member = new_member(full_name="Mara One", email="m1@csf.test")
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)

    response = api.run_allocation(
        landing["lot_id"],
        {"week_index": 1, "expected_landing_lot_version": landing["lot"]["version"]},
        make_member_headers(member["id"]),
    )
    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert read_lot(landing["lot_id"])["status"] == "RECORDED"


def test_a_member_may_not_pause_another_members_subscription(api):
    """PRD 2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting member;
    ownership checks compare the `member_id` recorded on the subscription behind the addressed
    resource to `X-User-ID`, and this applies to subscription actions, skip requests, pickups,
    substitution responses and share-transfer responses alike."
    PRD 2.1: "An entity-backed actor addressing a resource it does not own is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403), the same code used for the role-list check, and this
    ownership rung applies to every endpoint whose authorised-role list includes `Member` or
    `Vendor`."

    Design: Corner/rbac/member_cannot_pause_another_members_subscription
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    owner = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    stranger = new_member(full_name="Nils Two", email="m2@csf.test")

    response = api.pause_subscription(
        owner["subscription_id"], make_member_headers(stranger["id"])
    )
    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert read_subscription(owner["subscription_id"])["lifecycle_status"] == "ACTIVE"


def test_a_vendor_may_not_issue_a_quality_disposition(api):
    """PRD 2.1: "A `QualityOfficer` alone issues a quality disposition, and shares cold-chain
    logging with a `HubOperator`."
    PRD 3.6: "A hold is resolved by a quality officer, and by nobody else, through a
    `disposition` of `RELEASE`, `DISCOUNT` or `DISCARD`."

    Design: Corner/rbac/vendor_cannot_issue_a_quality_disposition
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)
    log_leg(landing["lot_id"], "DOCK_TO_HUB", 25, 6.0)

    response = api.disposition_lot(
        landing["lot_id"], {"disposition": "RELEASE"}, make_vendor_headers(fleet["vessel_id"])
    )
    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert read_lot(landing["lot_id"])["quality_status"] == "HOLD"


def test_a_restricted_member_cannot_resume_their_auto_paused_subscription(api):
    """PRD 2.5: "The acting or referenced member does not have standing `RESTRICTED` —
    otherwise `ERR_MEMBER_RESTRICTED` (HTTP 403). This guards subscription creation,
    subscription activation and subscription resumption."
    PRD 3.2: "There is also a second, system-driven route into `PAUSED`: when a member's
    `standing` becomes `RESTRICTED`, every `ACTIVE` subscription that member holds is paused,
    and while the standing remains `RESTRICTED` an attempt to resume is refused with
    `ERR_MEMBER_RESTRICTED`."

    Design: Corner/errors/error_member_restricted_blocks_resume_after_two_no_shows
    """
    ctx = setup_no_show_sequence(close_second_window=True)

    response = api.resume_subscription(
        ctx["subscription_id"], make_member_headers(ctx["member_id"])
    )
    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_MEMBER_RESTRICTED.value)

    member = read_member(ctx["member_id"])
    assert member["standing"] == "RESTRICTED"
    assert member["season_no_show_count"] == 2
    assert read_subscription(ctx["subscription_id"])["lifecycle_status"] == "PAUSED"
