"""Four-level synchronous cascades, driven from opposite ends of the pipeline.

Writing a box off blocks the style, then its items, then unlocks the session
holding them. Delivering the last asset completes the style and pushes its
sample into the return queue.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, CONTENT_OPS, COORDINATOR, PRODUCER


def _locked_session_over_a_single_sample(api):
    """One required item of a matched style, assigned to a session and then locked."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api,
        world,
        item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}],
        with_photographer_booking=False,
    )
    fx.lock_session(api, world.session_id)
    return world


def test_write_off_charges_the_vendor_and_leaves_the_match_axis_alone(api):
    """Level one of the cascade: the ledger moves, the box's identity does not.

    PRD: "Custody moves to `LOST`, which is terminal, and `match_state` is deliberately left exactly as it was — the axes are independent, and a lost box is still a box we knew the identity of."

    Design: Difficulty/transitive_cascade/report_lost_sample_blocks_style_then_items_then_unlocks_session
    """
    world = _locked_session_over_a_single_sample(api)

    sample = validate_success(
        api.report_lost_sample(
            world.sample_id, COORDINATOR, {"reason": "not found on rack at pull"}
        )
    )

    assert sample["custody_state"] == "LOST"
    assert sample["match_state"] == "MATCHED"
    vendor = validate_success(api.get_vendor(world.vendor_id, ADMIN))
    assert vendor["outstanding_sample_count"] == 0
    assert vendor["late_return_count"] == 1
    assert vendor["coordination_hold"] is False


def test_write_off_blocks_the_style_and_then_its_assigned_item(api):
    """Levels two and three: no matched sample remains, so style and item block.

    PRD: "At the second level, if the write-off leaves no sample at all still matched to that style with `match_state` of `MATCHED` and `custody_state` of either `IN_STUDIO` or `ON_SET`, and the style's `content_state` is currently `NOT_STARTED`, `SAMPLE_READY` or `SCHEDULED`, then the style's `content_state` becomes `BLOCKED` and its `version` increments by one."

    Design: Difficulty/transitive_cascade/report_lost_sample_blocks_style_then_items_then_unlocks_session
    """
    world = _locked_session_over_a_single_sample(api)

    validate_success(
        api.report_lost_sample(
            world.sample_id, COORDINATOR, {"reason": "not found on rack at pull"}
        )
    )

    assert world.read_style()["content_state"] == "BLOCKED"
    assert world.read_item(0)["item_state"] == "BLOCKED"


def test_write_off_auto_unlocks_the_session_stripped_of_its_call_sheet(api):
    """Level four: the locked session loses its only required item and reopens.

    PRD: "At the fourth level, caused by those items being blocked, each shoot session that had been holding one of them is re-examined: if that session is left with no shot-list item at all whose `required` flag is true and whose `item_state` is `ASSIGNED` or `CAPTURED`, then the session auto-unlocks from `LOCKED` back to `BOOKED` and its `version` increments by one."

    Design: Difficulty/transitive_cascade/report_lost_sample_blocks_style_then_items_then_unlocks_session
    """
    world = _locked_session_over_a_single_sample(api)

    validate_success(
        api.report_lost_sample(
            world.sample_id, COORDINATOR, {"reason": "not found on rack at pull"}
        )
    )

    assert world.read_session()["session_state"] == "BOOKED"


def _approved_asset_awaiting_publication(api):
    """A single-item style shot, retouched and QC-approved, with its sample on the rack."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.retoucher = fx.create_retoucher(api, minimum_call_hours=0)
    fx.build_style_on_the_rack(api, world, style_kw={"priority_tier": "B"})
    fx.build_planned_session(
        api, world, item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}]
    )
    fx.build_shooting_session(api, world)
    fx.build_ingested_asset(api, world)
    fx.build_queued_task(api, world)
    fx.build_submitted_task(api, world)
    fx.build_approved_asset(api, world)
    return world


def test_delivery_stamps_the_cms_key_and_the_delivery_instant(api):
    """Level one of the delivery cascade mints the key from category, number and file.

    PRD: "At the first level the asset moves `APPROVED → DELIVERED`, `delivered_at` is stamped from the logical clock, and `cms_asset_key` is minted as the style's `category`, a slash, the style's `style_number`, a slash, and the asset's `file_name` — so a front shot of an apparel top is filed as `APPAREL_TOP/TS10442/TS10442_FRONT_007`."

    Design: Difficulty/transitive_cascade/deliver_asset_completes_style_and_pushes_sample_into_return_queue
    """
    world = _approved_asset_awaiting_publication(api)

    asset = validate_success(
        api.deliver_asset(world.asset_id, CONTENT_OPS, {"cms_collection": "fw26-launch"})
    )

    assert asset["asset_state"] == "DELIVERED"
    assert asset["cms_asset_key"] == "APPAREL_TOP/TOP1001/TOP1001_FRONT_001"
    assert asset["delivered_at"] == "2026-08-03T09:00:00.000Z"


def test_delivery_completes_the_style_that_was_waiting_on_that_shot(api):
    """Levels two and three: the counter rises and the content axis reaches its terminal.

    PRD: "At the third level, caused by that delivery having covered the last outstanding shot, the system checks whether every shot-list item of the style whose `required` flag is true and whose `item_state` is not `WAIVED` now owns at least one asset in `DELIVERED` state; when that holds and the style is `IN_POST`, the style advances `IN_POST → DELIVERED`, which is terminal for its content axis."

    Design: Difficulty/transitive_cascade/deliver_asset_completes_style_and_pushes_sample_into_return_queue
    """
    world = _approved_asset_awaiting_publication(api)

    validate_success(
        api.deliver_asset(world.asset_id, CONTENT_OPS, {"cms_collection": "fw26-launch"})
    )

    style = validate_success(api.get_style(world.style_id, PRODUCER))
    assert style["delivered_asset_count"] == 1
    assert style["content_state"] == "DELIVERED"


def test_delivery_pushes_the_finished_sample_into_the_return_queue(api):
    """Level four: the goods are no longer needed, so the box joins the return queue.

    PRD: "At the fourth level, caused by the style reaching `DELIVERED`, every sample matched to that style whose `custody_state` is `IN_STUDIO` or `ON_SET` is moved to `RETURN_PENDING` — the goods are no longer needed and the return clock, already ticking since `due_return_at` was set, now has somewhere to go."

    Design: Difficulty/transitive_cascade/deliver_asset_completes_style_and_pushes_sample_into_return_queue
    """
    world = _approved_asset_awaiting_publication(api)

    validate_success(
        api.deliver_asset(world.asset_id, CONTENT_OPS, {"cms_collection": "fw26-launch"})
    )

    sample = validate_success(api.get_sample(world.sample_id, COORDINATOR))
    assert sample["custody_state"] == "RETURN_PENDING"
    assert sample["match_state"] == "MATCHED"
