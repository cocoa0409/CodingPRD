"""Similar-exposure groups and memberships (PRD §3.2, §4)."""
from test_helpers import (
    ApiErrorId,
    create_membership_payload,
    create_seg_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

IH = TEST_USERS["ih_headers"]


def test_seg_analyte_must_match_limit(api):
    """PRD §3.2: "Every SEG is governed by exactly one exposure limit,
    referenced as `exposure_limit_id`, and the group's `analyte_code` must
    equal the analyte of that linked limit; a mismatch is rejected with
    `ERR_ANALYTE_MISMATCH` (422)."

    Design: Corner/entities/seg_analyte_must_match_limit
    """
    site = fx.create_site()
    limit = fx.create_limit(analyte_code="PB")
    res = api.create_seg(
        create_seg_payload(site["id"], limit["id"], analyte_code="CR"), IH
    )
    validate_error(res, ApiErrorId.ERR_ANALYTE_MISMATCH, 422)


def test_membership_duplicate_rejected(api):
    """PRD §3.2: "The membership's `uniqueness` constraint binds the pair: a
    second membership for the same employee in the same group is rejected with
    `ERR_DUPLICATE_MEMBERSHIP` (409). Each creation increments the group's
    `headcount` by one and advances the group's `version`."

    Design: Corner/entities/membership_duplicate_rejected
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]

    res = api.create_membership(
        create_membership_payload(ctx.seg["id"], employee["id"]), IH
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP, 409)

    seg = fx.get_seg(ctx.seg["id"])
    assert seg["headcount"] == 1, "rejected insert must not inflate headcount"


def test_membership_transfer_conserves_site_headcount(api):
    """PRD §3.2: "A transfer decrements the source group's `headcount` by one
    and increments the destination group's by one — the site-wide sum of
    headcounts is conserved — and each of the two groups and the membership
    itself takes a `version` increment."

    Design: Difficulty/compensating_invariant/membership_transfer_conserves_site_headcount
    """
    ctx = fx.setup_site_seg(member_count=2)
    seg_a = ctx.seg
    seg_b = fx.create_seg(ctx.site["id"], ctx.limit["id"], name="Painters B")
    e3 = fx.create_employee(ctx.site["id"], external_ref="E3")
    fx.create_membership(seg_b["id"], e3["id"])

    membership = ctx.memberships[0]
    before_a = fx.get_seg(seg_a["id"])
    before_b = fx.get_seg(seg_b["id"])
    assert before_a["headcount"] == 2 and before_b["headcount"] == 1

    moved = validate_success(
        api.transfer_membership(
            membership["id"], {"target_seg_id": seg_b["id"]}, IH
        ),
        200,
    )
    assert moved["seg_id"] == seg_b["id"]

    after_a = fx.get_seg(seg_a["id"])
    after_b = fx.get_seg(seg_b["id"])
    assert after_a["headcount"] == 1
    assert after_b["headcount"] == 2
    assert after_a["headcount"] + after_b["headcount"] == 3, (
        "site-wide headcount is conserved"
    )
    assert after_a["version"] == before_a["version"] + 1
    assert after_b["version"] == before_b["version"] + 1
    assert moved["version"] == membership["version"] + 1


def test_membership_transfer_to_other_site_rejected(api):
    """PRD §3.2: "A membership may later be transferred to another group of
    the same site by supplying `target_seg_id`; a target group belonging to a
    different site is rejected with `ERR_INVALID_REQUEST`."

    Design: Difficulty/compensating_invariant/membership_transfer_conserves_site_headcount
    """
    ctx = fx.setup_site_seg(member_count=1)
    other_site = fx.create_site(name="Other Co", industry_code="332710")
    foreign_seg = fx.create_seg(other_site["id"], ctx.limit["id"], name="Foreign")

    res = api.transfer_membership(
        ctx.memberships[0]["id"], {"target_seg_id": foreign_seg["id"]}, IH
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    seg = fx.get_seg(ctx.seg["id"])
    assert seg["headcount"] == 1, "rejected transfer must not move headcount"


def test_fk_reverse_reachability_lists(api):
    """PRD §4: "List memberships; optional `seg_id` and `employee_id` filters"
    PRD §4: "List plans; optional `seg_id` filter"
    PRD §4: "List samples; optional `sampling_plan_id`, `employee_id`,
    `pump_id`, `pre_calibration_id` filters"

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])
    sample = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=cal["id"],
    )

    memberships, meta_m = validate_paginated(
        api.list_memberships(IH, params={"seg_id": ctx.seg["id"]})
    )
    assert meta_m["total_count"] == 1
    assert [m["id"] for m in memberships] == [ctx.memberships[0]["id"]]

    plans, meta_p = validate_paginated(
        api.list_sampling_plans(IH, params={"seg_id": ctx.seg["id"]})
    )
    assert meta_p["total_count"] == 1
    assert [p["id"] for p in plans] == [ctx.plan["id"]]

    samples, meta_s = validate_paginated(
        api.list_field_samples(
            IH,
            params={
                "sampling_plan_id": ctx.plan["id"],
                "pump_id": pump["id"],
                "pre_calibration_id": cal["id"],
            },
        )
    )
    assert meta_s["total_count"] == 1
    assert [s["id"] for s in samples] == [sample["id"]]
