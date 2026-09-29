"""Individual endpoints: their gates, their computed reads and their link fields.

Three shapes appear here. A guarded action has more than one reason to refuse and
must refuse in the declared order. A computed read persists nothing and must
recompute from the rows as they stand at the moment of the call. And a plain
create/read/list surface must expose its derived counters at creation, echo them
on the read, and honour the filter and pagination envelope on the list.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_grinding_wheel,
    assert_recondition_job,
    assert_wheel_life_conserved,
)
from test_helpers.fixtures import APP, APPROVER, GEO, PLAN
from test_helpers.test_users import TEST_USERS
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

BUYER = TEST_USERS["customer_headers"]


# ─── Product release: the state gate and then the evidence gate ──────────────

def test_a_product_still_in_development_cannot_be_released_at_all(api):
    """Release is not a transition out of DEVELOPMENT, so the state gate fires first.

    PRD §2.11: "12. **Subject state permits the transition.** The addressed
    entity is not in a state from which the requested transition is declared →
    the entity's own invalid-state code"

    PRD §3.5: "Release is the `QualityApprover`'s decision and is the only path
    from `QUALIFICATION` to `RELEASED`."

    Design: Corner/endpoints/product_release_needs_an_approved_dossier_not_merely_the_right_state
    """
    grade = fx.carbide_grade(api)
    geometry = fx.released_geometry(api)
    product = validate_success(
        api.create_tool_product(
            f.tool_product_payload(grade["id"], geometry["id"]), GEO
        ),
        201,
    )
    assert product["release_status"] == "DEVELOPMENT", (
        f"the product has not entered qualification yet, got {product['release_status']}"
    )

    response = api.release_tool_product(product["id"], APPROVER)

    validate_error(response, ApiErrorId.ERR_INVALID_PRODUCT_STATE, 409)
    standing = validate_success(api.get_tool_product(product["id"], APP))
    assert standing["release_status"] == "DEVELOPMENT", (
        f"the refused release changes nothing, got {standing['release_status']}"
    )
    assert standing["version"] == product["version"], (
        f"a refused request is not a mutation, got version {standing['version']}"
    )


def test_a_product_in_qualification_with_an_open_dossier_lacks_the_evidence(api):
    """The right state is not enough: the folder must actually have been approved.

    PRD §2.11: "39. **Release requires an approved dossier.** →
    `ERR_NO_APPROVED_DOSSIER`, on product release."

    PRD §3.5: "It requires at least one qualification dossier on the product to
    be `APPROVED` and `tool_life_index` to be non-null — a failure of either is
    `ERR_NO_APPROVED_DOSSIER` — and it requires all three pins to still match the
    current revisions of the referenced rows, otherwise
    `ERR_PINNED_REVISION_STALE`."

    Design: Corner/endpoints/product_release_needs_an_approved_dossier_not_merely_the_right_state
    """
    state = fx.open_dossier(api, coated=False)
    assert state["dossier"]["status"] == "OPEN", (
        f"the dossier is open and undecided, got {state['dossier']['status']}"
    )

    response = api.release_tool_product(state["product"]["id"], APPROVER)

    validate_error(response, ApiErrorId.ERR_NO_APPROVED_DOSSIER, 409)
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["release_status"] == "QUALIFICATION", (
        f"the product stays in qualification, got {product['release_status']}"
    )
    assert product["tool_life_index"] is None, (
        f"no life index has been written, got {product['tool_life_index']}"
    )
    assert product["supply_status"] == "UNAVAILABLE", (
        "the supply dimension must not move on a refused release, got "
        f"{product['supply_status']}"
    )


# ─── The speeds-and-feeds computed read ──────────────────────────────────────

def _uncoated_product_in_development(api) -> dict:
    """A 6.0 %-cobalt P grade under a MEDIUM CNMG geometry, nose 0.8, max ap 4.0."""
    grade = fx.carbide_grade(api)
    geometry = fx.insert_geometry(api)
    product = validate_success(
        api.create_tool_product(
            f.tool_product_payload(grade["id"], geometry["id"]), GEO
        ),
        201,
    )
    return {"grade": grade, "geometry": geometry, "product": product}


def test_the_envelope_multiplies_the_grade_factor_and_clamps_feed_and_depth(api):
    """220 x 1.08 rounds to 238, the feed clamps at the nose fraction, ap at 3.00.

    PRD §3.5: "The grade factor is 1.00 plus 0.02 for each percentage point by
    which `co_binder_pct` falls below 10.0 — equivalently, 1.00 plus 0.02
    multiplied by the quantity 10.0 minus `co_binder_pct`, which is negative for a
    high-binder grade — and the result is then clamped to lie between a floor of
    0.85 and a ceiling of 1.20."

    PRD §3.5: "`recommended_fz` is the geometry's `nose_radius_mm` multiplied by
    0.35, capped by the class feed ceiling of 0.55 millimetres for `ROUGHING`,
    0.30 for `MEDIUM` or 0.14 for `FINISHING`, and rounded half up to three
    decimal places."

    PRD §3.5: "`recommended_ap` is the geometry's `max_depth_of_cut_mm`, capped by
    the class depth ceiling of 6.0 millimetres for `ROUGHING`, 3.0 for `MEDIUM`
    or 1.0 for `FINISHING`, and rounded half up to two decimal places."

    PRD §3.5: "Finally `confidence_class` is `HIGH` when the requested
    `workpiece_group` appears in the product's `qualified_workpiece_groups`;
    otherwise `MEDIUM` when the product's `release_status` is `RELEASED`;
    otherwise `LOW`."

    Design: Corner/endpoints/speeds_feeds_read_multiplies_every_factor_and_reports_low_confidence
    """
    state = _uncoated_product_in_development(api)

    response = api.get_speeds_feeds(
        state["product"]["id"],
        f.speeds_feeds_params(
            workpiece_group="P", machine_rigidity="RIGID", coolant="FLOOD"
        ),
        APP,
    )

    envelope = validate_success(response)
    assert envelope["recommended_vc"] == 238, (
        "220 multiplied by a 1.08 grade factor is 237.6, which rounds to 238, "
        f"got {envelope['recommended_vc']}"
    )
    assert envelope["recommended_fz"] == 0.280, (
        f"0.8 mm of nose radius at 0.35 is 0.280, under the 0.30 MEDIUM ceiling, "
        f"got {envelope['recommended_fz']}"
    )
    assert envelope["recommended_ap"] == 3.00, (
        f"4.0 mm of depth is clamped by the 3.0 MEDIUM ceiling, got {envelope['recommended_ap']}"
    )
    assert envelope["confidence_class"] == "LOW", (
        "the product is neither qualified for P nor released, got "
        f"{envelope['confidence_class']}"
    )
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["version"] == state["product"]["version"], (
        f"a computed read persists nothing, got version {product['version']}"
    )


def test_a_weak_machine_running_dry_on_an_uncoated_tool_takes_the_full_penalty(api):
    """0.70 rigidity and the 0.60 uncoated dry factor drop 237.6 to 100.

    PRD §3.5: "The rigidity factor is 1.00 for `RIGID`, 0.85 for `MEDIUM` and
    0.70 for `WEAK`. The coolant factor is 1.00 for `FLOOD` and 1.10 for
    `THROUGH_TOOL`; for `DRY` it depends on the tool, being 0.60 for an uncoated
    product and 0.75 for a coated one."

    PRD §3.5: "The material baseline cutting speed in metres per minute is 220 for
    group `P`, 170 for `M`, 150 for `K`, 400 for `N`, 60 for `S` and 45 for `H`."

    PRD §3.5: "`recommended_vc` is that baseline multiplied by all four factors,
    then capped by the geometry's `application_class` ceiling — 260 for
    `ROUGHING`, 340 for `MEDIUM`, 420 for `FINISHING` — and rounded half up to a
    whole number of metres per minute."

    Design: Corner/endpoints/speeds_feeds_read_multiplies_every_factor_and_reports_low_confidence
    """
    state = _uncoated_product_in_development(api)

    dry_and_weak = api.get_speeds_feeds(
        state["product"]["id"],
        f.speeds_feeds_params(
            workpiece_group="P", machine_rigidity="WEAK", coolant="DRY"
        ),
        BUYER,
    )
    stainless_steel = api.get_speeds_feeds(
        state["product"]["id"],
        f.speeds_feeds_params(
            workpiece_group="S", machine_rigidity="RIGID", coolant="THROUGH_TOOL"
        ),
        APP,
    )

    penalised = validate_success(dry_and_weak)
    assert penalised["recommended_vc"] == 100, (
        "220 x 1.08 x 0.70 x 0.60 is 99.792, which rounds to 100 — the dry "
        f"factor is the uncoated 0.60, not 0.75, got {penalised['recommended_vc']}"
    )
    assert penalised["confidence_class"] == "LOW", (
        f"the buyer gets the same low-confidence flag, got {penalised['confidence_class']}"
    )
    superalloy = validate_success(stainless_steel)
    assert superalloy["recommended_vc"] == 71, (
        "60 x 1.08 x 1.10 is 71.28, far below the 340 MEDIUM ceiling, got "
        f"{superalloy['recommended_vc']}"
    )


# ─── A reconditioning job and its three links ────────────────────────────────

def _returned_first_pass(api) -> dict:
    """RJ-1 driven intake to RETURNED on a 90.0 mm measurement, wheel WH-8."""
    state = fx.refurbished_recondition_job(
        api,
        wheel_overrides={"wheel_code": "WH-8"},
        inspect_overrides={
            "measured_length_mm": 90.0,
            "measured_corner_wear_um": 210.0,
        },
        customer_overrides={
            "customer_code": "CU-8",
            "name": "Theta Regrind",
            "tier": "STANDARD",
        },
    )
    state["job"] = validate_success(
        api.return_recondition_job(state["job"]["id"], f.return_job_payload(), PLAN)
    )
    return state


def test_a_second_pass_derives_its_pass_number_from_the_chain_it_names(api):
    """The caller supplies a predecessor, never a pass number, and 1 becomes 2.

    PRD §3.9: "Intake may be requested by the owning `Customer` or by a
    `ProductionPlanner` and carries the `customer_id`, the `product_id` of the
    tools, a `job_code` unique across all jobs, `units_received`, the count of
    tools received, at least 1 and at most 500, optionally the
    `predecessor_job_id` of the prior regrind pass on the same tools, and the
    mandatory `expected_customer_version` described in §2.10."

    PRD §3.9: "On success the job opens at `status` `RECEIVED`, `regrind_pass_no`
    is set to the length of the `predecessor_job_id` chain plus one,
    `reserved_credit_cents` is set to `units_received` multiplied by 1850, the
    customer's `regrind_credit_cents` is reduced by that reservation while
    `reserved_credit_cents` rises by it, and the customer's `version` advances by
    1."

    Design: Corner/endpoints/recondition_job_links_customer_product_and_predecessor_job
    """
    state = _returned_first_pass(api)
    assert state["job"]["regrind_pass_no"] == 1, (
        f"the first pass carries pass number 1, got {state['job']['regrind_pass_no']}"
    )

    response = api.create_recondition_job(
        f.recondition_job_payload(
            state["customer"]["id"],
            state["product"]["id"],
            fx.current_customer_version(api, state["customer"]["id"]),
            predecessor_job_id=state["job"]["id"],
            job_code="RJ-2",
        ),
        PLAN,
    )

    second = validate_success(response, 201)
    assert_recondition_job(second)
    assert second["regrind_pass_no"] == 2, (
        f"one predecessor in the chain makes this the second pass, got {second['regrind_pass_no']}"
    )
    assert second["predecessor_job_id"] == state["job"]["id"], (
        f"the self-referential link is recorded, got {second['predecessor_job_id']}"
    )
    assert second["customer_id"] == state["customer"]["id"], (
        f"the job points at the buying account, got {second['customer_id']}"
    )
    assert second["product_id"] == state["product"]["id"], (
        f"the job points at the reconditioned product, got {second['product_id']}"
    )
    customer = validate_success(api.get_customer(state["customer"]["id"], PLAN))
    assert customer["reserved_credit_cents"] == 18500, (
        "only the open second pass holds a reservation, the first was consumed "
        f"on its return, got {customer['reserved_credit_cents']}"
    )


def test_each_of_the_three_links_is_observable_through_its_own_list_filter(api):
    """The predecessor, the account and the wheel each select the job that carries it.

    PRD §4: "List reconditioning jobs, filterable by customer, product,
    predecessor job, wheel and status"

    PRD §3.9: "On success the job moves `INSPECTED` → `REFURBISHED`, `wheel_id`
    and `recoat_applied` are recorded, `units_inspected` multiplied by
    `grind_units_per_tool` is added to the wheel's `consumed_life_units`, and if
    that charge takes the wheel's `remaining_life_units` below 150 the wheel moves
    `AVAILABLE` → `DRESSING`."

    Design: Corner/endpoints/recondition_job_links_customer_product_and_predecessor_job
    """
    state = _returned_first_pass(api)
    second = validate_success(
        api.create_recondition_job(
            f.recondition_job_payload(
                state["customer"]["id"],
                state["product"]["id"],
                fx.current_customer_version(api, state["customer"]["id"]),
                predecessor_job_id=state["job"]["id"],
                job_code="RJ-2",
            ),
            PLAN,
        ),
        201,
    )

    successors, successor_meta = validate_paginated(
        api.list_recondition_jobs(PLAN, params={"predecessor_job_id": state["job"]["id"]})
    )
    settled, _settled_meta = validate_paginated(
        api.list_recondition_jobs(
            PLAN,
            params={"customer_id": state["customer"]["id"], "status": "RETURNED"},
        )
    )
    ground, _ground_meta = validate_paginated(
        api.list_recondition_jobs(PLAN, params={"wheel_id": state["wheel"]["id"]})
    )

    assert successor_meta["total_count"] == 1, (
        f"the first pass has exactly one successor, got {successor_meta['total_count']}"
    )
    assert successors[0]["job_code"] == "RJ-2", (
        f"the successor is the second pass, got {successors[0]['job_code']}"
    )
    assert [row["job_code"] for row in settled] == ["RJ-1"], (
        f"only the first pass has been returned, got {[r['job_code'] for r in settled]}"
    )
    assert [row["job_code"] for row in ground] == ["RJ-1"], (
        "the wheel link is written by refurbishment, which the second pass has "
        f"not reached, got {[r['job_code'] for r in ground]}"
    )
    assert second["wheel_id"] is None, (
        f"an unrefurbished job names no wheel, got {second['wheel_id']}"
    )


# ─── The grinding wheel resource: create, read, list ─────────────────────────

def test_a_new_wheel_computes_its_life_counters_and_reads_them_back(api):
    """Creation answers 201 with remaining life equal to the initial figure.

    PRD §3.4: "A `ProductionPlanner` registers a wheel with a `wheel_code` unique
    across all wheels, a `spec_code` naming the abrasive specification (for
    example D46-C75-B), and `initial_life_units`, the abrasive life available
    between dressings, at least 100 and at most 100000."

    PRD §3.4: "A new wheel opens at `status` `AVAILABLE`, with
    `consumed_life_units` at 0, `remaining_life_units` equal to
    `initial_life_units`, and `dress_count` at 0."

    Design: Corner/endpoints/grinding_wheel_crud_surface_is_create_read_list_only
    """
    response = api.create_grinding_wheel(
        f.grinding_wheel_payload(
            wheel_code="WH-A", spec_code="D46-C75-B", initial_life_units=5000
        ),
        PLAN,
    )

    wheel = validate_success(response, 201)
    assert_grinding_wheel(wheel)
    assert wheel["status"] == "AVAILABLE", (
        f"a fresh wheel is available, got {wheel['status']}"
    )
    assert wheel["consumed_life_units"] == 0, (
        f"nothing has been ground yet, got {wheel['consumed_life_units']}"
    )
    assert wheel["remaining_life_units"] == 5000, (
        f"the whole abrasive life is available, got {wheel['remaining_life_units']}"
    )
    assert wheel["dress_count"] == 0, (
        f"the wheel has never been dressed, got {wheel['dress_count']}"
    )
    assert_wheel_life_conserved(wheel)

    read_back = validate_success(api.get_grinding_wheel(wheel["id"], APPROVER))
    assert read_back["spec_code"] == "D46-C75-B", (
        f"the read echoes the abrasive specification, got {read_back['spec_code']}"
    )
    assert read_back["remaining_life_units"] == 5000, (
        f"the read echoes the life counters, got {read_back['remaining_life_units']}"
    )


def test_the_wheel_list_filters_by_status_and_walks_a_one_row_page(api):
    """A limit of 1 at an offset of 1 returns the second wheel and no more.

    PRD §2.3: "`limit` sets the maximum number of rows returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100. `offset` sets the number of rows to skip before the returned
    page begins; when omitted it defaults to 0. Unless a specific endpoint says
    otherwise, list results are ordered by `created_at` ascending, so a stable
    page walk with a fixed `limit` and an advancing `offset` visits every row
    exactly once."

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of rows matching the request's filters before pagination is applied
    and `has_more` states whether any matching row remains beyond the returned
    page."

    Design: Corner/endpoints/grinding_wheel_crud_surface_is_create_read_list_only
    """
    validate_success(
        api.create_grinding_wheel(
            f.grinding_wheel_payload(
                wheel_code="WH-A", spec_code="D46-C75-B", initial_life_units=5000
            ),
            PLAN,
        ),
        201,
    )
    second = validate_success(
        api.create_grinding_wheel(
            f.grinding_wheel_payload(wheel_code="WH-B", initial_life_units=100),
            PLAN,
        ),
        201,
    )
    assert second["remaining_life_units"] == 100, (
        "100 units is the declared lower bound and is accepted, got "
        f"{second['remaining_life_units']}"
    )

    rows, meta = validate_paginated(
        api.list_grinding_wheels(
            PLAN, params={"status": "AVAILABLE", "limit": 1, "offset": 1}
        )
    )

    assert meta["total_count"] == 2, (
        f"both wheels match the AVAILABLE filter, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"the second row is the last one, got has_more {meta['has_more']}"
    )
    assert len(rows) == 1, (
        f"a limit of 1 returns a single row, got {len(rows)}"
    )
    assert rows[0]["wheel_code"] == "WH-B", (
        "ordered by creation, skipping one row lands on the second wheel, got "
        f"{rows[0]['wheel_code']}"
    )
