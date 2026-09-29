"""
The posting threshold is strict: exactly 1.000 does not post, 0.999 does.

PRD §3.4: "`posting_required` is true exactly when `rating_factor_operating` is
strictly less than 1.000 — a factor of exactly 1.000 does not require posting."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def test_an_operating_factor_of_exactly_one_does_not_require_posting(
    client, roster, bridge, accepted
):
    """
    The numerator lands exactly on the operating denominator, so the factor is
    exactly 1.000 and the strict comparison leaves the structure unposted while
    the inventory variant still reports a real tonnage.

    PRD §3.4: "With the same capacity, dynamic allowance and factors but a
    structural dead load of 465.6 and a wearing-surface dead load of 33.5, the
    numerator is 1530 minus 582.0 minus 50.25, which is exactly 897.75 — identical
    to the operating denominator — so the operating factor is exactly 1.000 and
    posting is **not** required, leaving `posted_limit_tons` null while
    `operating_rating_tons` reads 36.0. The inventory factor is 897.75 divided by
    1163.75, which is 0.77143…, rounded to 0.771, giving 27.756 and 27.8 tons."

    Design: Difficulty/boundary_precision_check/rating_factor_exactly_one_no_posting
    """
    rating = fx.create_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=465.6,
        dead_load_dw_kn_m=33.5,
    )

    assert rating["rating_factor_operating"] == 1.000
    assert rating["posting_required"] is False
    assert rating["posted_limit_tons"] is None
    assert rating["operating_rating_tons"] == 36.0
    assert rating["rating_factor_inventory"] == 0.771
    assert rating["inventory_rating_tons"] == 27.8
    assert rating["condition_factor_phi_c"] == 0.85


def test_nudging_the_dead_loads_flips_posting_on(client, roster, bridge, accepted):
    """
    A tiny increase in dead load drops the operating factor to 0.999, which *is*
    below the threshold, and the posted limit is then floored out of the inventory
    tonnage.

    PRD §3.4: "Nudge the dead loads to 466.0 and 34.0 and the numerator falls to
    896.5; the operating factor becomes 0.99860…, rounded to 0.999, which *is*
    below 1.000, so posting flips to required. The inventory factor becomes
    0.77035…, rounded to 0.770, giving 27.72 and 27.7 tons, and the posted limit is
    27.7 doubled to 55.4, floored to 55, halved to 27.5 tons."

    Design: Difficulty/boundary_precision_check/rating_factor_exactly_one_no_posting
    """
    boundary = fx.create_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=465.6,
        dead_load_dw_kn_m=33.5,
    )
    assert boundary["posting_required"] is False

    nudged = fx.create_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=466.0,
        dead_load_dw_kn_m=34.0,
    )

    assert nudged["rating_factor_operating"] == 0.999
    assert nudged["posting_required"] is True
    assert nudged["rating_factor_inventory"] == 0.770
    assert nudged["inventory_rating_tons"] == 27.7
    assert nudged["posted_limit_tons"] == 27.5
    a.assert_half_ton_step(nudged["posted_limit_tons"])


def test_neither_draft_rating_posts_the_structure(client, roster, bridge, accepted):
    """
    Both ratings sit in `DRAFT`, and governing-rating selection excludes drafts
    entirely, so the structure carries no posted limit however the arithmetic came
    out.

    PRD §3.4: "it considers only that structure's ratings whose `rating_status` is
    `APPROVED`, excluding `DRAFT`, `SEALED`, `REJECTED` and `SUPERSEDED` rows
    entirely. If none qualify, `governing_load_rating_id` is null and the structure
    has no posted limit and no rating tonnages."

    Design: Difficulty/boundary_precision_check/rating_factor_exactly_one_no_posting
    """
    fx.create_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=465.6,
        dead_load_dw_kn_m=33.5,
    )
    fx.create_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=466.0,
        dead_load_dw_kn_m=34.0,
    )

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["governing_load_rating_id"] is None
    assert structure["posting_required"] is False
    assert structure["posted_limit_tons"] is None
    assert structure["service_posture"] == "OPEN"


def test_approving_the_sub_threshold_rating_posts_the_structure(
    client, roster, bridge, accepted
):
    """
    Once the 0.999 rating is sealed and approved it becomes the governing rating,
    and the posting decision it carries is copied onto the structure, moving the
    posture down one rung.

    PRD §3.4: "The system re-selects the structure's governing rating and copies its
    results onto the structure — `governing_load_rating_id`, `posting_required`,
    `posted_limit_tons`, `operating_rating_tons` and `inventory_rating_tons` —
    recomputes `service_posture`, and increments the structure's `version` by one."
    PRD §3.4: "When a rating that requires posting becomes the governing rating on a
    structure carrying no unresolved restriction, the structure moves `OPEN →
    POSTED`, `posting_required` becomes true and `posted_limit_tons` is copied from
    the governing rating."

    Design: Difficulty/boundary_precision_check/rating_factor_exactly_one_no_posting
    """
    rating = fx.approved_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=466.0,
        dead_load_dw_kn_m=34.0,
    )

    assert rating["rating_status"] == "APPROVED"

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["governing_load_rating_id"] == rating["id"]
    assert structure["posting_required"] is True
    assert structure["posted_limit_tons"] == 27.5
    assert structure["operating_rating_tons"] == rating["operating_rating_tons"]
    assert structure["inventory_rating_tons"] == 27.7
    assert structure["service_posture"] == "POSTED"


def test_approving_the_boundary_rating_leaves_the_structure_open(
    client, roster, bridge, accepted
):
    """
    The same lifecycle applied to the exactly-1.000 rating publishes tonnages
    without a posted limit, because the rating itself does not require posting.

    PRD §3.4: "When posting is not required, `posted_limit_tons` is null."
    PRD §2.11: "Otherwise, if the structure has a governing load rating and that
    rating requires posting, the posture is `POSTED`. Otherwise the posture is
    `OPEN`."

    Design: Difficulty/boundary_precision_check/rating_factor_exactly_one_no_posting
    """
    rating = fx.approved_rating(
        client,
        bridge["id"],
        roster,
        accepted["inspection"]["id"],
        dead_load_dc_kn_m=465.6,
        dead_load_dw_kn_m=33.5,
    )

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["governing_load_rating_id"] == rating["id"]
    assert structure["posting_required"] is False
    assert structure["posted_limit_tons"] is None
    assert structure["operating_rating_tons"] == 36.0
    assert structure["inventory_rating_tons"] == 27.8
    assert structure["service_posture"] == "OPEN"
