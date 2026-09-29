"""Endpoint corners: the read surface, action endpoints and computed reads.

Create-read-list round trips, an action firing once its preconditions hold, a
computed read on an empty style, and the link endpoint's two-sided existence.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ASSET_NOT_APPROVED, ERR_SESSION_NOT_FOUND
from test_helpers.test_users import CONTENT_OPS, COORDINATOR, PRODUCER

UNKNOWN_SESSION_UUID = "00000000-0000-4000-8000-00000000ffff"


def _one_vendor_holding_a_received_box(api):
    """Vendor NRTH with SMP-B already booked into the dock."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    received = fx.create_sample(
        api, vendor["id"], barcode="SMP-B", declared_style_number="TOP1002"
    )
    fx.receive_sample(api, received["id"])
    return vendor, received


def test_a_pre_advised_box_reads_back_exactly_as_it_was_created(api):
    """Create then read: the surface has no update and no delete, only a round trip.

    PRD: "A pre-advised sample starts `EXPECTED` and `UNMATCHED` with `matched_style_id` null."

    Design: Corner/endpoints/sample_create_read_and_filtered_list_round_trip
    """
    vendor, _ = _one_vendor_holding_a_received_box(api)

    created = validate_success(
        api.create_sample(
            f.sample_payload(
                vendor["id"], barcode="SMP-A", declared_style_number="TOP1001"
            ),
            COORDINATOR,
        ),
        201,
    )
    read_back = validate_success(api.get_sample(created["id"], PRODUCER))

    assert read_back["id"] == created["id"]
    assert read_back["barcode"] == "SMP-A"
    assert read_back["declared_style_number"] == "TOP1001"
    assert read_back["custody_state"] == "EXPECTED"
    assert read_back["match_state"] == "UNMATCHED"


def test_the_sample_list_filters_on_vendor_and_custody_state_together(api):
    """Conjunctive filters return the one expected box and leave the received one out.

    PRD: "Samples may be filtered by `vendor_id`, `matched_style_id`, `custody_state` and `match_state` — the two state axes filter independently."

    Design: Corner/endpoints/sample_create_read_and_filtered_list_round_trip
    """
    vendor, received = _one_vendor_holding_a_received_box(api)
    expected = fx.create_sample(
        api, vendor["id"], barcode="SMP-A", declared_style_number="TOP1001"
    )

    rows, meta = validate_paginated(
        api.list_samples(
            COORDINATOR,
            {
                "vendor_id": vendor["id"],
                "custody_state": "EXPECTED",
                "limit": 10,
                "offset": 0,
            },
        )
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    identifiers = [row["id"] for row in rows]
    assert expected["id"] in identifiers
    assert received["id"] not in identifiers


def test_the_lock_action_freezes_the_call_sheet_once_the_goods_are_in(api):
    """Both substantive conditions hold, so the freeze goes through.

    PRD: "On success the session moves `BOOKED → LOCKED` and further shot-list assignment to it is rejected."

    Design: Corner/endpoints/lock_action_fires_once_every_precondition_is_satisfied
    """
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(api, world)
    version_before = fx.session_version(api, world.session_id)

    locked = validate_success(api.lock_session(world.session_id, PRODUCER))

    assert locked["session_state"] == "LOCKED"
    assert locked["version"] > version_before
    assert world.read_item(0)["item_state"] == "ASSIGNED"
    assert world.read_station()["committed_minutes_today"] == 240


def _a_style_with_one_planned_item_and_no_session(api):
    """Style TOP1001 owns a single PLANNED required item; the only provider is in-house."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    fx.create_provider(api)
    style = fx.create_style(api, vendor["id"], profile["id"])
    fx.create_shot_item(api, style["id"])
    return style


def test_the_provisional_projection_of_an_unscheduled_style_is_zero(api):
    """With no session to walk, the forward-looking variant never leaves zero.

    PRD: "It starts at zero and walks every session that holds at least one shot-list item of this style and whose `session_state` is not `CANCELLED`."

    Design: Corner/endpoints/cost_summary_of_an_unshot_style_reports_zeros_and_recommends_in_house
    """
    style = _a_style_with_one_planned_item_and_no_session(api)

    summary = validate_success(api.get_cost_summary(style["id"], CONTENT_OPS))

    assert summary["style_id"] == style["id"]
    assert summary["provisional_cost_cents"] == 0


def test_the_final_actual_of_an_unwrapped_style_is_its_persisted_allocation(api):
    """Nothing has wrapped, so the finance figure is the style's own zeroed ledger.

    PRD: "The **final** variant is the finance-facing actual, and it is not recomputed at all: `final_cost_cents` is simply the style's persisted `allocated_cost_cents`, which is to say the sum of the per-item allocations already posted at each session wrap."

    Design: Corner/endpoints/cost_summary_of_an_unshot_style_reports_zeros_and_recommends_in_house
    """
    style = _a_style_with_one_planned_item_and_no_session(api)

    summary = validate_success(api.get_cost_summary(style["id"], CONTENT_OPS))

    assert summary["final_cost_cents"] == 0
    assert validate_success(api.get_style(style["id"], CONTENT_OPS))[
        "allocated_cost_cents"
    ] == 0


def test_with_no_outsourced_house_on_file_the_comparison_stays_in_house(api):
    """No eligible provider means a null quote, a null variance and the in-house verdict.

    PRD: "When no provider is eligible, `outsourced_quote_cents` and `outsourced_provider_id` are null. `variance_cents` is the final cost less the outsourced quote, and is null whenever there is no quote. `recommended_source` is the string `IN_HOUSE` when there is no quote at all or when the final cost is less than or equal to the quote, and the string `OUTSOURCED` only when the final cost is strictly greater than the quote — a tie always favours keeping the work in the building."

    Design: Corner/endpoints/cost_summary_of_an_unshot_style_reports_zeros_and_recommends_in_house
    """
    style = _a_style_with_one_planned_item_and_no_session(api)

    summary = validate_success(api.get_cost_summary(style["id"], CONTENT_OPS))

    assert summary["outsourced_quote_cents"] is None
    assert summary["outsourced_provider_id"] is None
    assert summary["variance_cents"] is None
    assert summary["recommended_source"] == "IN_HOUSE"


def test_delivering_a_file_that_has_not_cleared_review_is_refused(api):
    """The gate is the asset's own state, and no CMS key is minted on the way out.

    PRD: "The asset must be `APPROVED`; anything else is refused with `ERR_ASSET_NOT_APPROVED`."

    Design: Corner/endpoints/delivery_is_conditional_on_the_asset_having_cleared_qc
    """
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(api, world)
    fx.build_shooting_session(api, world)
    fx.build_ingested_asset(api, world)

    validate_error(
        api.deliver_asset(
            world.asset_id, CONTENT_OPS, {"cms_collection": "fw26-tops"}
        ),
        ERR_ASSET_NOT_APPROVED,
        409,
    )

    asset = world.read_asset()
    assert asset["asset_state"] == "INGESTED"
    assert asset["cms_asset_key"] is None
    assert asset["delivered_at"] is None
    assert world.read_style()["delivered_asset_count"] == 0


def _one_planned_item_and_one_booked_session(api):
    """Style TOP1001 owns a required ON_MODEL item; a 09:00-13:00 MODEL bay is booked."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    world.items.append(fx.create_shot_item(api, world.style_id))
    world.session = fx.create_session(api, world.station_id, world.provider_id)
    return world


def test_assigning_an_item_to_a_real_session_links_the_two(api):
    """The link endpoint sets the item's session_id and advances its state.

    PRD: "On success the item moves `PLANNED → ASSIGNED` with its `session_id` set, and if the item's `required` flag is true and the parent style's `content_state` is `SAMPLE_READY`, that style advances to `SCHEDULED` and its `version` increments by one."

    Design: Corner/endpoints/assign_links_an_item_to_a_session_and_refuses_an_unknown_one
    """
    world = _one_planned_item_and_one_booked_session(api)

    assigned = validate_success(
        api.assign_shot_list_item(
            world.item_id, {"session_id": world.session_id}, PRODUCER
        )
    )

    assert assigned["item_state"] == "ASSIGNED"
    assert assigned["session_id"] == world.session_id


def test_assigning_an_item_to_an_unknown_session_leaves_the_link_intact(api):
    """The body foreign key fails to resolve, and the earlier link survives it.

    PRD: "A missing `Vendor`, `Station`, `TalentProfile`, `StudioProvider`, `AssetProfile` or `ReleaseDocument` reference all raise `ERR_REFERENCE_NOT_FOUND`; a missing `Style`, `ShootSession`, `ShotListItem` or `Asset` reference raises that entity's own not-found code."

    Design: Corner/endpoints/assign_links_an_item_to_a_session_and_refuses_an_unknown_one
    """
    world = _one_planned_item_and_one_booked_session(api)
    fx.assign_item(api, world.item_id, world.session_id)

    validate_error(
        api.assign_shot_list_item(
            world.item_id, {"session_id": UNKNOWN_SESSION_UUID}, PRODUCER
        ),
        ERR_SESSION_NOT_FOUND,
        404,
    )

    assert world.read_item(0)["session_id"] == world.session_id
