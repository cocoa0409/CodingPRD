"""Authentication, authorization, and the fixed validation pipeline order:
missing headers, role denial on exclusive endpoints, existence before business
safety, and state preconditions before operator-certification gating."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    make_operator,
    make_released_drawing,
    scrap_unit,
    setup_order_in_build,
    validate_error,
)
from test_helpers import TEST_USERS
from test_helpers import make_quality_inspector_headers

ENG = TEST_USERS["harness_engineer_headers"]
MAT = TEST_USERS["materials_clerk_headers"]
QM = TEST_USERS["quality_manager_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestAuthenticationAndAuthorization:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/c_missing_auth_headers_unauthenticated
        """
        resp = api.create_drawing(
            {
                "drawing_number": "DWG-V1",
                "customer_code": "ACME",
                "revision": "A",
                "workmanship_class": "IPC_CLASS_2",
            },
            {},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_on_drawing_create(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`HarnessEngineer` — owns harness drawings, BOM components, and engineering change notices."

        Design: Corner/validations/c_forbidden_role_on_drawing_create
        """
        resp = api.create_drawing(
            {
                "drawing_number": "DWG-V2",
                "customer_code": "ACME",
                "revision": "A",
                "workmanship_class": "IPC_CLASS_2",
            },
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_quality_manager_cannot_create_build_order(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`QualityManager` — owns operators, operator certifications, and the logical clock."
        PRD §2.1: "`ProductionPlanner` — owns build orders and release to kitting."

        Design: Corner/rbac/c_quality_manager_cannot_create_build_order
        """
        drawing, _components = make_released_drawing(api, tag="R3")
        resp = api.create_build_order(
            {"order_code": "BO-R3", "drawing_id": drawing["id"], "qty_ordered": 1},
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestValidationPipelineOrder:
    def test_existence_precedes_state_and_safety(self, api):
        """PRD §2.6: "When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure."
        PRD §2.6: "4. **Existence** — path identifiers and body foreign-key identifiers resolve to existing resources, validated left-to-right; otherwise `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.4: "When a request references resources by identifier — whether in the path or in the body — each identifier must resolve to an existing resource; the first unresolvable identifier, validated left-to-right, yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/c_existence_priority_not_found_before_state
        """
        # The acting inspector exists but holds no certification; the harness
        # reference is bogus. Existence (tier 4) fires before state (tier 6)
        # and before operator-certification gating (tier 7).
        operator = make_operator(api, name="NC V3", badge="B-NC-V3")
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": NON_EXISTENT_UUID,
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_state_error_wins_over_cert_error_on_scrapped_unit(self, api):
        """PRD §2.6: "When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure."
        PRD §2.6: "6. **State preconditions** — the target resource is in a status that permits the operation (drawing `DRAFT` for component add and release, drawing `RELEASED` for program/build-order/ECN creation, program `DRAFT` for edit, applicator tooling preconditions for pull tests, build order `OPEN` for edit and cancel, build order `IN_BUILD` for harness creation, unit testable or shippable, kit `PICKING` for issues, kit `STAGED` for delivery, ECN `OPEN` for apply and cancel, and so on). These reject with the operation's dedicated 409 error."
        PRD §2.6: "7. **Business safety** — operator certification gating, segregation of duties, hipot class minimums, and consigned supply-type compliance. On electrical test recording, this tier has a fixed internal order: the certification check runs first, then segregation of duties, then the hipot voltage floor."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_scrapped_harness_test
        """
        ctx = setup_order_in_build(api, tag="PP1", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        scrap_unit(api, unit["id"], inspector["id"], reason="DAMAGE")
        # The acting operator holds NO certification, so tiers 6 and 7 both
        # fail; the state precondition is evaluated first.
        uncertified = make_operator(api, name="NC PP1", badge="B-NC-PP1")
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(uncertified["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_HARNESS_NOT_TESTABLE)
        assert error["error_id"] != ApiErrorId.ERR_OPERATOR_NOT_CERTIFIED, (
            "the tier-6 state rejection surfaces before the tier-7 certification gate"
        )

    def test_scrapped_unit_rejects_even_certified_inspector(self, api):
        """PRD §3.7: "The unit must be `BUILT`, `REWORK`, or `SUSPECT`; testing a unit in any other status rejects with `ERR_HARNESS_NOT_TESTABLE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_scrapped_harness_test
        """
        ctx = setup_order_in_build(api, tag="PP1S", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        scrap_unit(api, unit["id"], inspector["id"], reason="DAMAGE")
        # Isolated single failure: the inspector's certification is ACTIVE, so
        # only the unit-state rule can fire.
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HARNESS_NOT_TESTABLE)
