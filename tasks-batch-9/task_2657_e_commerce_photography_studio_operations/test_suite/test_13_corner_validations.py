"""Validation corners: violation, satisfaction, conditional pairs and check order.

Each rule is exercised on the failing side and, where the design asks for it, on
the side where the very same rule must stay silent.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CATEGORY_PROFILE_MISMATCH,
    ERR_INVALID_BASE_STYLE,
    ERR_INVALID_TIME_WINDOW,
    ERR_SAMPLE_NOT_MATCHED,
)
from test_helpers.test_users import ADMIN, COORDINATOR


def test_a_style_whose_category_disagrees_with_its_profile_is_refused(api):
    """Every foreign key resolves, and the pairing rule still rejects the style.

    PRD: "The style's own `category` must equal the `category` of the referenced asset profile; a disagreement is `ERR_CATEGORY_PROFILE_MISMATCH`."

    Design: Corner/validations/style_category_that_disagrees_with_its_profile_is_rejected
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])

    validate_error(
        api.create_style(
            f.style_payload(
                vendor["id"],
                profile["id"],
                style_number="SHOE9001",
                category="FOOTWEAR",
            ),
            ADMIN,
        ),
        ERR_CATEGORY_PROFILE_MISMATCH,
        422,
    )


def test_a_style_whose_category_matches_its_profile_is_accepted(api):
    """The same shape with the agreeing category registers cleanly.

    PRD: "The style's own `category` must equal the `category` of the referenced asset profile; a disagreement is `ERR_CATEGORY_PROFILE_MISMATCH`."

    Design: Corner/validations/style_whose_category_matches_its_profile_is_accepted
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])

    style = validate_success(
        api.create_style(f.style_payload(vendor["id"], profile["id"]), ADMIN), 201
    )

    assert style["category"] == "APPAREL_TOP"
    assert style["content_state"] == "NOT_STARTED"
    assert style["priority_tier"] == "C"
    assert style["required_item_count"] == 0
    assert style["allocated_cost_cents"] == 0
    assert style["base_style_id"] is None


def _a_base_style_to_hang_colourways_from(api):
    """Vendor, profile and one parent style whose own base_style_id is null."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(api, required_angles=["FRONT"])
    base = fx.create_style(api, vendor["id"], profile["id"])
    return vendor, profile, base


def test_a_parent_named_without_a_colourway_code_is_refused(api):
    """Half of the pair is not enough to register a colourway.

    PRD: "The two fields are strictly paired: a `colorway_code` without a `base_style_id`, or a `base_style_id` without a `colorway_code`, is rejected. Parentage is one level deep only, so the referenced base style must itself have no `base_style_id`; a colorway of a colorway is refused. And the pair of parent and code must be unique, so the same colorway code cannot appear twice under one base style. All three of these failures surface as `ERR_INVALID_BASE_STYLE`."

    Design: Corner/validations/colorway_code_is_required_exactly_when_a_base_style_is_named
    """
    vendor, profile, base = _a_base_style_to_hang_colourways_from(api)

    validate_error(
        api.create_style(
            f.style_payload(
                vendor["id"],
                profile["id"],
                style_number="TOP1001BLK",
                base_style_id=base["id"],
            ),
            ADMIN,
        ),
        ERR_INVALID_BASE_STYLE,
        422,
    )


def test_a_colourway_code_named_without_a_parent_is_refused(api):
    """The other half of the pair fails the same rule with the same code.

    PRD: "The two fields are strictly paired: a `colorway_code` without a `base_style_id`, or a `base_style_id` without a `colorway_code`, is rejected. Parentage is one level deep only, so the referenced base style must itself have no `base_style_id`; a colorway of a colorway is refused. And the pair of parent and code must be unique, so the same colorway code cannot appear twice under one base style. All three of these failures surface as `ERR_INVALID_BASE_STYLE`."

    Design: Corner/validations/colorway_code_is_required_exactly_when_a_base_style_is_named
    """
    vendor, profile, _ = _a_base_style_to_hang_colourways_from(api)

    validate_error(
        api.create_style(
            f.style_payload(
                vendor["id"],
                profile["id"],
                style_number="TOP1001NVY",
                colorway_code="NVY",
            ),
            ADMIN,
        ),
        ERR_INVALID_BASE_STYLE,
        422,
    )


def test_the_parent_and_the_code_supplied_together_register_a_colourway(api):
    """Both halves present satisfies the conditional rule.

    PRD: "Supplying `base_style_id` makes the new row a colorway of the referenced style, and `colorway_code` — 2 to 8 uppercase alphanumeric characters — must then be present."

    Design: Corner/validations/colorway_code_is_required_exactly_when_a_base_style_is_named
    """
    vendor, profile, base = _a_base_style_to_hang_colourways_from(api)

    colorway = validate_success(
        api.create_style(
            f.style_payload(
                vendor["id"],
                profile["id"],
                style_number="TOP1001RED",
                base_style_id=base["id"],
                colorway_code="RED",
            ),
            ADMIN,
        ),
        201,
    )

    assert colorway["base_style_id"] == base["id"]
    assert colorway["colorway_code"] == "RED"


def test_a_release_window_that_ends_where_it_starts_is_refused(api):
    """The bound is strict, so a zero-length grant is not a window at all.

    PRD: "The window is inclusive at `valid_from` and exclusive at `valid_until`, and `valid_until` must fall strictly after `valid_from`, or the record is refused with `ERR_INVALID_TIME_WINDOW`; an unresolvable `talent_id` is `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/release_window_that_ends_before_it_starts_is_an_invalid_time_window
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    model = fx.create_model(api, minimum_call_hours=0, max_daily_minutes=600)

    validate_error(
        api.create_release_document(
            f.release_payload(
                model["id"],
                territory="GLOBAL",
                valid_from="2026-08-01T00:00:00Z",
                valid_until="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )


def test_a_declared_custody_edge_still_waits_on_the_match_axis(api):
    """The edge is legal, so the refusal comes from the later match check instead.

    PRD: "`RECEIVED → IN_STUDIO` puts the box on the rack, and `IN_STUDIO → ON_SET` walks it to the floor; both of these require that the sample's `match_state` is already `MATCHED`, because the studio refuses to put unidentified goods into production — a move to either destination while the sample is `UNMATCHED` or in `MISMATCH_HOLD` is refused with `ERR_SAMPLE_NOT_MATCHED`."

    Design: Corner/validations/custody_advance_waits_for_the_match_axis_after_the_edge_is_admitted
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    sample = fx.create_sample(api, vendor["id"])
    fx.receive_sample(api, sample["id"])

    validate_error(
        api.custody_move_sample(
            sample["id"], f.custody_move_payload("IN_STUDIO"), COORDINATOR
        ),
        ERR_SAMPLE_NOT_MATCHED,
        409,
    )

    after = validate_success(api.get_sample(sample["id"], COORDINATOR))
    assert after["custody_state"] == "RECEIVED"
    assert after["match_state"] == "UNMATCHED"
