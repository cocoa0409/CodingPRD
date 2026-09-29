"""Role-based access control: peer disciplines, shared routes and identity.

The role model is flat. No role inherits another's rights, so each discipline is
locked out of the others' exclusive routes, while the routes that are declared
shared must genuinely accept every role named on them. And one guard is not about
roles at all: the quality decision on a dossier is refused on the strength of the
deciding user's *identity*, however correct that user's role may be.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_no_row_with_code, assert_tool_product
from test_helpers.constants import (
    DOSSIER_SUBMITTER,
    INDEPENDENT_APPROVER,
    TRIAL_OPERATOR_ONE,
    TRIAL_OPERATOR_TWO,
)
from test_helpers.fixtures import APP, APPROVER, COAT, GEO, MET, PLAN
from test_helpers.test_users import (
    make_customer_headers,
    make_quality_approver_headers,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Exclusive routes are closed to every peer role ─────────────────────────

def test_neither_engineering_discipline_may_define_the_others_master_data(api):
    """Metallurgy cannot cut a geometry and geometry cannot mix a grade.

    PRD §4: "| POST | `/tooling/insert-geometries` | Create an insert/tool
    geometry with its chip breaker definition, in DRAFT at revision 1 |
    GeometryEngineer |"

    PRD §4: "| POST | `/tooling/carbide-grades` | Open a new carbide grade
    development record in DRAFT at revision 1 | MetallurgyEngineer |"

    PRD §4: "A request from a role not listed for an endpoint is rejected with
    `ERR_ROLE_NOT_PERMITTED` before any other rule is evaluated."

    Design: Corner/rbac/exclusive_operations_are_closed_to_every_peer_role
    """
    fx.carbide_grade(api)
    fx.insert_geometry(api)

    geometry_by_metallurgy = api.create_insert_geometry(
        f.insert_geometry_payload(
            geometry_code="CNMG-XX",
            iso_designation="CNMG120404",
            application_class="FINISHING",
        ),
        MET,
    )
    grade_by_geometry = api.create_carbide_grade(
        f.stainless_grade_payload(grade_code="WC-M20"), GEO
    )

    validate_error(geometry_by_metallurgy, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(grade_by_geometry, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    geometries, geometry_meta = validate_paginated(api.list_insert_geometries(GEO))
    grades, grade_meta = validate_paginated(api.list_carbide_grades(MET))
    assert geometry_meta["total_count"] == 1, (
        f"only the geometry engineer's own row exists, got {geometry_meta['total_count']}"
    )
    assert_no_row_with_code(geometries, "geometry_code", "CNMG-XX")
    assert grade_meta["total_count"] == 1, (
        f"only the metallurgist's own row exists, got {grade_meta['total_count']}"
    )
    assert_no_row_with_code(grades, "grade_code", "WC-M20")


def test_the_release_and_supply_dimensions_belong_to_two_different_roles(api):
    """Application engineering cannot release, and quality cannot move supply.

    PRD §4: "| POST | `/tooling/tool-products/{productId}/release` | Release a
    product in QUALIFICATION to the catalog | QualityApprover |"

    PRD §4: "| POST | `/tooling/tool-products/{productId}/set-supply-status` | Set
    the supply dimension (UNAVAILABLE / MAKE_TO_ORDER / STOCKED) independently of
    the | ProductionPlanner |"

    PRD §3.5: "A new product opens at `release_status` `DEVELOPMENT` and
    `supply_status` `UNAVAILABLE`, captures the three pinned revisions from its
    referenced grade, geometry and recipe, computes `engineering_lead_time_days`
    and `expedite_eligible`, and sets `tool_life_index` to null,
    `qualified_workpiece_groups` to the empty list and `open_order_units` to 0."

    Design: Corner/rbac/exclusive_operations_are_closed_to_every_peer_role
    """
    grade = fx.carbide_grade(api)
    geometry = fx.insert_geometry(api)
    product = validate_success(
        api.create_tool_product(
            f.tool_product_payload(grade["id"], geometry["id"]), GEO
        ),
        201,
    )
    assert_tool_product(product)

    release_by_application = api.release_tool_product(product["id"], APP)
    supply_by_quality = api.set_product_supply_status(
        product["id"], f.set_supply_status_payload("STOCKED"), APPROVER
    )

    validate_error(release_by_application, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(supply_by_quality, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    standing = validate_success(api.get_tool_product(product["id"], APP))
    assert standing["release_status"] == "DEVELOPMENT", (
        f"the release dimension did not move, got {standing['release_status']}"
    )
    assert standing["supply_status"] == "UNAVAILABLE", (
        f"the supply dimension did not move, got {standing['supply_status']}"
    )
    assert standing["version"] == product["version"], (
        f"a refused call is not a mutation, got version {standing['version']}"
    )


def test_coating_may_not_commission_wheels_and_quality_may_not_start_a_pilot(api):
    """The planner's shop floor and the metallurgist's ladder are equally closed.

    PRD §4: "| POST | `/tooling/grinding-wheels` | Register a grinding wheel with
    its initial usable life in abrasive units | ProductionPlanner |"

    PRD §4: "| POST | `/tooling/carbide-grades/{gradeId}/start-pilot` | Move a
    DRAFT grade into PILOT once the current recipe revision has produced a
    QC-passed | MetallurgyEngineer |"

    Design: Corner/rbac/exclusive_operations_are_closed_to_every_peer_role
    """
    grade = fx.carbide_grade(api)

    wheel_by_coating = api.create_grinding_wheel(
        f.grinding_wheel_payload(
            wheel_code="WH-Z", spec_code="D46-C75-B", initial_life_units=5000
        ),
        COAT,
    )
    pilot_by_quality = api.start_grade_pilot(grade["id"], APPROVER)

    validate_error(wheel_by_coating, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(pilot_by_quality, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    _wheels, wheel_meta = validate_paginated(api.list_grinding_wheels(PLAN))
    assert wheel_meta["total_count"] == 0, (
        f"the coating engineer commissioned nothing, got {wheel_meta['total_count']}"
    )
    standing = validate_success(api.get_carbide_grade(grade["id"], MET))
    assert standing["status"] == "DRAFT", (
        f"the grade is still in draft, got {standing['status']}"
    )


# ─── Shared routes accept every role declared on them ───────────────────────

def test_the_planner_may_blend_and_press_but_may_not_sinter(api):
    """Two shared batch routes open to the planner sandwich one exclusive step.

    PRD §4: "| POST | `/tooling/powder-blend-batches/{batchId}/press` | Press the
    blended powder into green compacts | ProductionPlanner, MetallurgyEngineer |"

    PRD §4: "| POST | `/tooling/powder-blend-batches/{batchId}/sinter` | Sinter the
    pressed compacts and record density, hardness and scrap | MetallurgyEngineer |"

    PRD §3.1: "The new batch opens at `stage` `BLENDED` with `qc_status` `PENDING`,
    captures `pinned_grade_revision` from the grade's current `revision`, and sets
    `pressed_units`, `sintered_units`, `scrap_units` and `remaining_units` all to
    0."

    PRD §3.1: "The `qc_status` dimension is untouched by pressing — a pressed batch
    is still `PENDING`, because nothing has yet been measured."

    Design: Corner/rbac/shared_operations_accept_either_declared_role
    """
    grade = fx.carbide_grade(api)

    batch = validate_success(
        api.create_powder_blend_batch(
            f.powder_blend_batch_payload(grade["id"], batch_code="BLD-P"), PLAN
        ),
        201,
    )
    assert batch["stage"] == "BLENDED", (
        f"the planner may weigh out a blend, got {batch['stage']}"
    )
    pressed = validate_success(
        api.press_powder_blend_batch(batch["id"], f.press_payload(), PLAN)
    )
    assert pressed["stage"] == "PRESSED", (
        f"the planner may press the compacts, got {pressed['stage']}"
    )

    response = api.sinter_powder_blend_batch(batch["id"], f.sinter_payload(), PLAN)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
    standing = validate_success(api.get_powder_blend_batch(batch["id"], MET))
    assert standing["stage"] == "PRESSED", (
        f"the furnace step did not happen, got {standing['stage']}"
    )
    assert standing["qc_status"] == "PENDING", (
        f"no QC verdict has been reached, got {standing['qc_status']}"
    )
    assert standing["sintered_units"] == 0, (
        f"nothing came out of the furnace, got {standing['sintered_units']}"
    )


def test_product_definition_is_open_to_both_engineering_roles(api):
    """Geometry and application engineering may each bind grade to geometry.

    PRD §4: "| POST | `/tooling/tool-products` | Create a catalog or special tool
    product bound to a grade, a geometry and optionally a | GeometryEngineer,
    ApplicationEngineer |"

    PRD §3.5: "A tool product is the join of the three engineering disciplines into
    something a customer can buy, and it may be created by a `GeometryEngineer` or
    an `ApplicationEngineer`."

    Design: Corner/rbac/shared_operations_accept_either_declared_role
    """
    grade = fx.carbide_grade(api)
    geometry = fx.insert_geometry(api)

    by_geometry = api.create_tool_product(
        f.tool_product_payload(grade["id"], geometry["id"], sku="CAT-INS-1"), GEO
    )
    by_application = api.create_tool_product(
        f.tool_product_payload(grade["id"], geometry["id"], sku="CAT-INS-AE"), APP
    )

    first = validate_success(by_geometry, 201)
    second = validate_success(by_application, 201)
    assert_tool_product(second)
    assert second["sku"] == "CAT-INS-AE", (
        f"the application engineer's own product was created, got {second['sku']}"
    )
    assert second["id"] != first["id"], (
        "the two calls created two distinct products"
    )
    _rows, meta = validate_paginated(api.list_tool_products(APP))
    assert meta["total_count"] == 2, (
        f"both engineering roles succeeded, got {meta['total_count']}"
    )


def test_a_customer_may_pull_the_speeds_and_feeds_advice(api):
    """The envelope read is the one engineering route open to the buying account.

    PRD §4: "| GET | `/tooling/tool-products/{productId}/speeds-feeds` |
    Application-engineering computed read: recommended cutting speed, feed per
    tooth and depth | ApplicationEngineer, GeometryEngineer, MetallurgyEngineer,
    CoatingEngineer, QualityApprover, Customer |"

    PRD §4: "| POST | `/tooling/customers` | Register a customer account with an
    opening regrind credit balance | ProductionPlanner, ApplicationEngineer |"

    Design: Corner/rbac/shared_operations_accept_either_declared_role
    """
    grade = fx.carbide_grade(api)
    geometry = fx.insert_geometry(api)
    product = validate_success(
        api.create_tool_product(
            f.tool_product_payload(grade["id"], geometry["id"]), GEO
        ),
        201,
    )
    buyer = validate_success(
        api.create_customer(
            f.customer_payload(customer_code="CU-B", name="Lambda Tooling"), APP
        ),
        201,
    )

    response = api.get_speeds_feeds(
        product["id"], f.speeds_feeds_params(), make_customer_headers(buyer["id"])
    )

    envelope = validate_success(response)
    assert envelope["recommended_vc"] == 238, (
        "the buyer gets the same 220 x 1.08 figure any engineer would, got "
        f"{envelope['recommended_vc']}"
    )
    assert envelope["confidence_class"] == "LOW", (
        f"the product is unqualified and unreleased, got {envelope['confidence_class']}"
    )


# ─── Segregation of duties is enforced on identity, not on role ──────────────

def test_neither_the_submitter_nor_a_trial_operator_may_decide_the_dossier(api):
    """The right role carrying a tainted user id is refused on all three tries.

    PRD §2.12: "Concretely, the `X-User-ID` deciding a dossier must differ from the
    dossier's recorded `submitted_by_user_id`, and must differ from the
    `operator_user_id` of **every** machining trial attached to that dossier —
    including trials that were later invalidated. A violation of either condition
    is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, and the rule is
    enforced identically on approval and on rejection: a `QualityApprover` cannot
    escape the constraint by rejecting instead of approving."

    PRD §3.7: "Only third is the independence of the approver checked, as described
    in §2.12."

    Design: Corner/rbac/dossier_decision_is_closed_to_the_submitter_and_to_every_trial_operator
    """
    state = fx.submitted_dossier(api, coated=False)
    dossier_id = state["dossier"]["id"]
    assert state["dossier"]["composite_score"] == 1.20, (
        "two subscores of 1.20 average to 1.20, so the score gate is cleared and "
        f"the independence gate is reachable, got {state['dossier']['composite_score']}"
    )

    by_submitter = api.approve_qualification_dossier(
        dossier_id,
        f.approve_dossier_payload(decision_note="Self-approval attempt"),
        make_quality_approver_headers(DOSSIER_SUBMITTER),
    )
    by_first_operator = api.approve_qualification_dossier(
        dossier_id,
        f.approve_dossier_payload(decision_note="Approval by the first operator"),
        make_quality_approver_headers(TRIAL_OPERATOR_ONE),
    )
    by_second_operator = api.reject_qualification_dossier(
        dossier_id,
        f.reject_dossier_payload(decision_note="Rejection by the second operator"),
        make_quality_approver_headers(TRIAL_OPERATOR_TWO),
    )

    validate_error(by_submitter, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    validate_error(by_first_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    validate_error(by_second_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    dossier = validate_success(api.get_qualification_dossier(dossier_id, APP))
    assert dossier["status"] == "SUBMITTED", (
        f"the dossier is still awaiting a clean decision, got {dossier['status']}"
    )
    assert dossier["decided_by_user_id"] is None, (
        f"nobody has decided it, got {dossier['decided_by_user_id']}"
    )


def test_an_untainted_approver_decides_it_and_the_grade_qualifies(api):
    """Only a third identity closes the dossier, and that carries the grade up.

    PRD §3.7: "An approval moves the dossier `SUBMITTED` → `APPROVED`, which is
    terminal. It records `decided_by_user_id` and the optional `decision_note`, of
    at most 400 characters, and then recomputes the product's qualification figures
    from all PASS trials inside all `APPROVED` dossiers of that product."

    PRD §3.7: "It does, however, complete the grade's own qualification: if the
    product's grade is at `PILOT`, the grade moves `PILOT` → `QUALIFIED` in the
    same request."

    Design: Corner/rbac/dossier_decision_is_closed_to_the_submitter_and_to_every_trial_operator
    """
    state = fx.submitted_dossier(api, coated=False)

    response = api.approve_qualification_dossier(
        state["dossier"]["id"],
        f.approve_dossier_payload(decision_note="Independent quality sign-off"),
        make_quality_approver_headers(INDEPENDENT_APPROVER),
    )

    dossier = validate_success(response)
    assert dossier["status"] == "APPROVED", (
        f"an independent approver may decide, got {dossier['status']}"
    )
    assert dossier["decided_by_user_id"] == INDEPENDENT_APPROVER, (
        f"the deciding identity is recorded, got {dossier['decided_by_user_id']}"
    )
    grade = validate_success(api.get_carbide_grade(state["grade"]["id"], MET))
    assert grade["status"] == "QUALIFIED", (
        f"the pilot grade is carried up by the approval, got {grade['status']}"
    )


# ─── The Customer role is entity-backed and scoped to its own rows ───────────

def _two_accounts_and_a_released_product(api) -> dict:
    """A STOCKED catalogue insert plus the caller CU-M and a third party CU-O."""
    state = fx.released_product(api, coated=False)
    state["mine"] = fx.customer(api, customer_code="CU-M", name="Mu Machining")
    state["theirs"] = fx.customer(
        api, customer_code="CU-O", name="Omicron Machining"
    )
    return state


def test_a_customer_may_not_raise_an_order_in_another_accounts_name(api):
    """A body naming a foreign `customer_id` is refused however correct it is.

    PRD §2.1: "The `Customer` role is entity-backed. When `X-User-Role` is
    `Customer`, `X-User-ID` is the `id` of the acting `Customer` row; ownership
    checks on any resource that references a `Customer` compare that resource's
    `customer_id` to `X-User-ID`. A `Customer` caller that reads or mutates a tool
    order or a reconditioning job whose `customer_id` is not its own value, or that
    supplies a `customer_id` other than its own in a request body, is rejected with
    `ERR_CUSTOMER_SCOPE_VIOLATION`."

    PRD §2.11: "9. **Customer scoping.** → `ERR_CUSTOMER_SCOPE_VIOLATION`, on the
    six operations listed in §2.1."

    Design: Corner/rbac/customer_role_may_only_touch_its_own_orders
    """
    state = _two_accounts_and_a_released_product(api)

    response = api.create_tool_order(
        f.tool_order_payload(
            state["theirs"]["id"],
            state["product"]["id"],
            fx.current_product_version(api, state["product"]["id"]),
            order_code="SO-SPOOF",
            quantity=25,
        ),
        make_customer_headers(state["mine"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION, 403)
    rows, meta = validate_paginated(api.list_tool_orders(PLAN))
    assert meta["total_count"] == 0, (
        f"the spoofed order was not written, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "order_code", "SO-SPOOF")


def test_the_scope_check_pre_empts_the_stale_product_version_check(api):
    """A stale pin and a foreign account together report the scope violation.

    PRD §2.11: "10. **Parent version currency.** → `ERR_STALE_PRODUCT_VERSION` on
    order creation and `ERR_STALE_CUSTOMER_VERSION` on reconditioning-job intake,
    per §2.10."

    PRD §3.8: "The order opens at `status` `DRAFT` with `requires_reconfirmation`
    false, and the product's `version` advances by 1 because the quoted product row
    is now pinned by an order."

    Design: Corner/rbac/customer_role_may_only_touch_its_own_orders
    """
    state = _two_accounts_and_a_released_product(api)
    stale_version = fx.current_product_version(api, state["product"]["id"])
    validate_success(
        api.create_tool_order(
            f.tool_order_payload(
                state["theirs"]["id"],
                state["product"]["id"],
                stale_version,
                order_code="SO-OTHER",
                quantity=25,
            ),
            APP,
        ),
        201,
    )
    assert fx.current_product_version(api, state["product"]["id"]) == stale_version + 1, (
        "raising the third party's order advanced the product version, so the "
        "captured figure is now stale"
    )

    response = api.create_tool_order(
        f.tool_order_payload(
            state["theirs"]["id"],
            state["product"]["id"],
            stale_version,
            order_code="SO-SPOOF2",
            quantity=25,
        ),
        make_customer_headers(state["mine"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION, 403)
    rows, meta = validate_paginated(api.list_tool_orders(PLAN))
    assert meta["total_count"] == 1, (
        f"only the third party's own order exists, got {meta['total_count']}"
    )
    assert_no_row_with_code(rows, "order_code", "SO-SPOOF2")


def test_a_customer_reads_and_raises_only_its_own_orders(api):
    """A foreign order is a 403 rather than a 404, and its own order is fine.

    PRD §2.1: "This scope check governs order creation, order submission, order
    cancellation, single-order reads, reconditioning job creation and single-job
    reads. The staff roles are not scope-restricted: an `ApplicationEngineer` may
    raise an order on behalf of any customer."

    PRD §4: "| GET | `/tooling/tool-orders` | List orders, filterable by customer,
    product and status | Customer, ApplicationEngineer, ProductionPlanner,
    QualityApprover |"

    Design: Corner/rbac/customer_role_may_only_touch_its_own_orders
    """
    state = _two_accounts_and_a_released_product(api)
    buyer = make_customer_headers(state["mine"]["id"])
    foreign_order = validate_success(
        api.create_tool_order(
            f.tool_order_payload(
                state["theirs"]["id"],
                state["product"]["id"],
                fx.current_product_version(api, state["product"]["id"]),
                order_code="SO-OTHER",
                quantity=25,
            ),
            APP,
        ),
        201,
    )

    foreign_read = api.get_tool_order(foreign_order["id"], buyer)
    own_order = api.create_tool_order(
        f.tool_order_payload(
            state["mine"]["id"],
            state["product"]["id"],
            fx.current_product_version(api, state["product"]["id"]),
            order_code="SO-MINE",
            quantity=25,
        ),
        buyer,
    )

    validate_error(foreign_read, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION, 403)
    mine = validate_success(own_order, 201)
    assert mine["customer_id"] == state["mine"]["id"], (
        f"the buyer's own order is written to its own account, got {mine['customer_id']}"
    )
    rows, meta = validate_paginated(
        api.list_tool_orders(buyer, params={"customer_id": state["mine"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the account-filtered page holds one order, got {meta['total_count']}"
    )
    assert rows[0]["order_code"] == "SO-MINE", (
        f"and it is the buyer's own, got {rows[0]['order_code']}"
    )
