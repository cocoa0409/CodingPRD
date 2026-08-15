"""Fire-safety configuration rules, scoped uniqueness, and referential coherence."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_order, make_opening, configure_order, make_drawing,
    submit_drawing, approve_drawing, make_program, get_opening, get_order,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
ANY_H = TEST_USERS["any_headers"]


class TestRatingRank:
    def test_opening_rating_exceeds_order_rank(self, api):
        """PRD §2.9: "Fire ratings are ranked `NONE`, then `MIN_20`, then
        `MIN_45`, then `MIN_90` in increasing severity; an opening may carry
        any rating up to and including the maximum its order declares."
        PRD §3.2: "an opening demanding more than the order allows fails with
        `ERR_OPENING_RATING_EXCEEDS_ORDER`."

        Design: Corner/validations/opening_rating_exceeds_order_rank
        """
        project = make_project(name="P", contract_code="CV-3")
        template = get_success_data(api.create_hardware_template(
            {"template_code": "T-V3", "manufacturer": "ACME", "fire_rated_compatible": True}, PM_H,
        ))
        ord20 = make_order(project["id"], order_code="O-R20", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_20", hardware_template_id=template["id"])
        ord45 = make_order(project["id"], order_code="O-R45", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_45", hardware_template_id=template["id"])

        # MIN_45 opening under a MIN_20 order outranks the declared maximum.
        resp = api.create_opening(
            {"order_id": ord20["id"], "opening_no": "X1", "width_in": 36, "height_in": 84,
             "fire_rating": "MIN_45", "required_on_site_date": "2026-10-01"}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_RATING_EXCEEDS_ORDER, 409)

        # MIN_20 under MIN_20 (equal rank) is allowed.
        ok1 = validate_success(api.create_opening(
            {"order_id": ord20["id"], "opening_no": "X2", "width_in": 36, "height_in": 84,
             "fire_rating": "MIN_20", "required_on_site_date": "2026-10-01"}, EST_H,
        ), 201)
        # MIN_45 under MIN_45 is allowed.
        ok2 = validate_success(api.create_opening(
            {"order_id": ord45["id"], "opening_no": "X3", "width_in": 36, "height_in": 84,
             "fire_rating": "MIN_45", "required_on_site_date": "2026-10-01"}, EST_H,
        ), 201)
        assert get_opening(ok1["id"])["fab_status"] == "QUEUED"
        assert get_opening(ok2["id"])["fab_status"] == "QUEUED"


class TestRatedConfigSafety:
    def test_rated_config_safety_rules(self, api):
        """PRD §3.2: "Second, an order whose `hardware_prep_mode` is
        `TEMPLATE_PREP` must reference a template through `hardware_template_id`,
        failing with `ERR_TEMPLATE_REQUIRED`. Third, an order whose
        `fire_rating_required` is anything other than `NONE` must use
        `TEMPLATE_PREP` — field prep by an installer is forbidden on rated
        work — failing with `ERR_RATED_ORDER_REQUIRES_TEMPLATE_PREP` (HTTP 403).
        Fourth, such a rated order's referenced template must have
        `fire_rated_compatible` true, failing with `ERR_TEMPLATE_NOT_FIRE_RATED`
        (HTTP 403)."

        Design: Corner/validations/rated_config_safety_rules
        """
        project = make_project(name="P", contract_code="CV-4")
        tmpl_nr = get_success_data(api.create_hardware_template(
            {"template_code": "T-NR", "manufacturer": "ACME", "fire_rated_compatible": False}, PM_H,
        ))
        # Rated + INSTALLER_PREP -> ERR_RATED_ORDER_REQUIRES_TEMPLATE_PREP
        ord_i = make_order(project["id"], order_code="O-I", species="MAPLE", profile_code="PR-7",
                           hardware_prep_mode="INSTALLER_PREP", fire_rating_required="MIN_20")
        make_opening(ord_i["id"], opening_no="1", fire_rating="MIN_20")
        # Rated + non-fire-rated template -> ERR_TEMPLATE_NOT_FIRE_RATED
        ord_t = make_order(project["id"], order_code="O-T", species="MAPLE", profile_code="PR-7",
                           hardware_prep_mode="TEMPLATE_PREP", fire_rating_required="MIN_20",
                           hardware_template_id=tmpl_nr["id"])
        make_opening(ord_t["id"], opening_no="1", fire_rating="MIN_20")
        # TEMPLATE_PREP without a template id -> ERR_TEMPLATE_REQUIRED
        ord_m = make_order(project["id"], order_code="O-M", species="MAPLE", profile_code="PR-7",
                           hardware_prep_mode="TEMPLATE_PREP", fire_rating_required="NONE")
        make_opening(ord_m["id"], opening_no="1", fire_rating="NONE")

        resp = api.set_order_status(ord_i["id"], {"target_status": "CONFIGURED"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_RATED_ORDER_REQUIRES_TEMPLATE_PREP, 403)
        resp = api.set_order_status(ord_t["id"], {"target_status": "CONFIGURED"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_FIRE_RATED, 403)
        resp = api.set_order_status(ord_m["id"], {"target_status": "CONFIGURED"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_REQUIRED, 409)

        for order in (ord_i, ord_t, ord_m):
            assert get_order(order["id"])["status"] == "DRAFT", (
                "a failed configure leaves the order in DRAFT"
            )


class TestScopedUniqueness:
    def test_duplicate_codes_rejected(self, api):
        """PRD §3.2: "supplying an `order_code` that must be unique within that
        project — a duplicate fails with `ERR_ORDER_CODE_NOT_UNIQUE`" and
        "supplying an `opening_no` unique within the order (duplicates fail
        with `ERR_OPENING_NO_NOT_UNIQUE`)".

        Design: Corner/validations/duplicate_codes_rejected
        """
        proj1 = make_project(name="P1", contract_code="CV-5A")
        proj2 = make_project(name="P2", site_address="2 Main St", contract_code="CV-5B")
        order = make_order(proj1["id"], order_code="DUP")
        make_opening(order["id"], opening_no="N1")

        # Same order_code within the same project is rejected.
        resp = api.create_order(
            {"project_id": proj1["id"], "order_code": "DUP", "species": "MAPLE",
             "profile_code": "PR-1", "finish_system": "STAIN", "sheen_target": "SATIN",
             "hardware_prep_mode": "INSTALLER_PREP", "fire_rating_required": "NONE"}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_CODE_NOT_UNIQUE, 409)

        # The same code is allowed in a different project.
        ok = validate_success(api.create_order(
            {"project_id": proj2["id"], "order_code": "DUP", "species": "MAPLE",
             "profile_code": "PR-1", "finish_system": "STAIN", "sheen_target": "SATIN",
             "hardware_prep_mode": "INSTALLER_PREP", "fire_rating_required": "NONE"}, EST_H,
        ), 201)
        assert ok["status"] == "DRAFT"

        # Duplicate opening_no within the same order is rejected.
        resp = api.create_opening(
            {"order_id": order["id"], "opening_no": "N1", "width_in": 32, "height_in": 84,
             "fire_rating": "NONE", "required_on_site_date": "2026-10-01"}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_NO_NOT_UNIQUE, 409)


class TestActiveDrawing:
    def test_second_active_drawing_rejected(self, api):
        """PRD §3.3: "only when no other drawing of the same order sits in
        `DRAFT` or `SUBMITTED`, failing otherwise with `ERR_ACTIVE_DRAWING_EXISTS`."
        and "The server assigns `revision_no` as one greater than the count of
        the order's existing drawings".

        Design: Corner/validations/second_active_drawing_rejected
        """
        project = make_project(name="P", contract_code="CV-6")
        order = make_order(project["id"], order_code="O-D6")
        make_opening(order["id"], opening_no="1")
        configure_order(order["id"])
        drawing1 = make_drawing(order["id"])

        # A second DRAFT while the first is active is rejected.
        version = get_order(order["id"])["version"]
        resp = api.create_shop_drawing(
            {"order_id": order["id"], "expected_order_version": version}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_DRAWING_EXISTS, 409)

        # After voiding the first, creation succeeds and the counter advances.
        resp = api.set_shop_drawing_status(drawing1["id"], {"target_status": "VOID"}, EST_H)
        validate_success(resp, 200)
        version = get_order(order["id"])["version"]
        drawing2 = validate_success(api.create_shop_drawing(
            {"order_id": order["id"], "expected_order_version": version}, EST_H,
        ), 201)
        assert drawing2["revision_no"] == 2, "revision counter advances across VOID"
        assert drawing2["status"] == "DRAFT"


class TestProgramOrderCoherence:
    def test_program_order_mismatch_rejected(self, api):
        """PRD §3.4: "the payload's `order_id` must equal the drawing's own
        order (`ERR_PROGRAM_ORDER_MISMATCH`)."

        Design: Corner/validations/program_order_mismatch_rejected
        """
        project = make_project(name="P", contract_code="CV-7")
        order_a = make_order(project["id"], order_code="O-A7")
        make_opening(order_a["id"], opening_no="1")
        configure_order(order_a["id"])
        drawing = make_drawing(order_a["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")
        order_b = make_order(project["id"], order_code="O-B7", species="MAPLE")

        resp = api.create_machining_program(
            {"drawing_id": drawing["id"], "order_id": order_b["id"], "estimated_minutes": 30},
            TEST_USERS["production_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_ORDER_MISMATCH, 409)
