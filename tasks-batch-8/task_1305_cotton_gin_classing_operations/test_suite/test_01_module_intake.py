"""Module intake: ticket/weight validation, estimated turnout, conditioning
cycle, rejection lockdown, and intake-side validation priority."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_module,
    create_grower,
    create_module,
    create_module_payload,
    create_shift,
    get_module,
    gin_module,
    queue_module,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]


class TestModuleCreateValidation:
    def test_missing_gross_weight_returns_invalid_request(self, api):
        """PRD: "Request body shape — required fields present, enum members valid,
        window ordering, non-empty bale lists, numeric ranges — is checked next
        with `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, or `ERR_EMPTY_SHIPMENT`."
        PRD: "The scale house records `gross_weight_lbs` and `tare_weight_lbs`"

        Design: Corner/entities/module_create_missing_required_field_returns_invalid_request
        """
        grower = create_grower("MB-C02", "Req Farm")
        payload = create_module_payload(grower["id"])
        del payload["gross_weight_lbs"]
        resp = api.create_module(payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(
            api.list_modules(OPERATOR, params={"grower_id": grower["id"]}))
        assert meta["total_count"] == 0, "no module may be persisted by the rejected create"

    def test_foreign_matter_exactly_at_limit_allowed(self, api):
        """PRD: "a module arriving with foreign matter above 10.0 percent is
        rejected outright with `ERR_FOREIGN_MATTER_LIMIT_EXCEEDED` (HTTP 422) as
        a contamination safety measure."
        PRD: "A successfully received module enters status `RECEIVED`."

        Design: Corner/validations/foreign_matter_exactly_at_limit_allowed
        """
        grower = create_grower("MB-C53", "Edge Farm")
        module = validate_success(api.create_module(
            create_module_payload(grower["id"], ticket_number="T-1",
                                  module_tag="MT-FM", moisture_pct=8.0,
                                  foreign_matter_pct=10.0), OPERATOR),
            expected_status=201)
        assert_module(module)
        assert module["status"] == "RECEIVED", "10.0 exactly passes (only above 10.0 is rejected)"


class TestModuleInitialState:
    def test_initial_state_and_estimates_on_create(self, api):
        """PRD: "A successfully received module enters status `RECEIVED`."
        PRD: "the system derives `net_weight_lbs` as gross minus tare"
        PRD: "moisture above 8.0 percent subtracts 0.4 percentage points per
        point of excess, capped at a 2.0-point total discount; foreign matter
        above 4.0 percent subtracts 0.5 points per point of excess, capped at
        2.5 points; and the resulting lint percentage is floored at 30 percent"
        PRD: "`est_seed_lbs` is simpler: net weight multiplied by 55 percent,
        rounded half-up to whole pounds."

        Design: Corner/state_machines/module_initial_state_and_estimate_on_create
        """
        grower = create_grower("MB-C10", "Init Farm")
        module = validate_success(api.create_module(
            create_module_payload(grower["id"], ticket_number="T-1",
                                  module_tag="MT-I", gross_weight_lbs=22000,
                                  tare_weight_lbs=2000, moisture_pct=9.0,
                                  foreign_matter_pct=3.0), OPERATOR),
            expected_status=201)
        assert_module(module)
        assert module["status"] == "RECEIVED"
        assert module.get("gin_shift_id") is None, "no shift until queued"
        assert module.get("reconciled_seed_lbs") is None
        assert module.get("ginned_at") is None
        # net 20000; moisture 9.0 -> -0.004, fm 3.0 -> 0; pct 0.376 -> 7520
        assert module["net_weight_lbs"] == 20000
        assert module["est_lint_lbs"] == 7520
        assert module["est_seed_lbs"] == 11000

    def test_turnout_adjustment_caps_applied(self, api):
        """PRD: "moisture above 8.0 percent subtracts 0.4 percentage points per
        point of excess, capped at a 2.0-point total discount; foreign matter
        above 4.0 percent subtracts 0.5 points per point of excess, capped at
        2.5 points; and the resulting lint percentage is floored at 30 percent
        no matter how wet or trashy the module."
        PRD: "`est_lint_lbs` is the module's net weight multiplied by that final
        percentage, rounded half-up to whole pounds."

        Design: Corner/calculations/turnout_adjustment_caps_applied
        """
        grower = create_grower("MB-C30", "Cap Farm")
        module = validate_success(api.create_module(
            create_module_payload(grower["id"], ticket_number="T-1",
                                  module_tag="MT-CAP", gross_weight_lbs=11000,
                                  tare_weight_lbs=1000, moisture_pct=16.0,
                                  foreign_matter_pct=9.0), OPERATOR),
            expected_status=201)
        # moisture 16.0 -> raw 0.032 capped at 0.020; fm 9.0 -> 0.025 capped
        # pct = 0.38 - 0.020 - 0.025 = 0.335; net 10000 -> 3350
        assert module["est_lint_lbs"] == 3350
        assert module["est_seed_lbs"] == 5500
        assert module["status"] == "RECEIVED"


class TestConditioningCycle:
    def test_conditioning_cycle_recomputes_turnout(self, api):
        """PRD: "Conditioning replaces the module's `moisture_pct` with the new
        reading from the payload, recomputes both estimates, and cycles the
        module's status: from `RECEIVED` a conditioning pass moves it to
        `CONDITIONING`; while in `CONDITIONING`, a reading still above 12.0
        percent keeps it in `CONDITIONING` (a self-loop — the module stays in
        the dryer), and a reading at or below 12.0 returns it to `RECEIVED`."
        PRD: "Each conditioning pass increments the module's `version`."

        Design: Corner/state_machines/module_conditioning_cycle_recomputes_turnout
        """
        grower = create_grower("MB-C11", "Dryer Farm")
        module = create_module(grower["id"], ticket_number="T-1",
                               module_tag="MT-D", gross_weight_lbs=13000,
                               tare_weight_lbs=1000, moisture_pct=14.0,
                               foreign_matter_pct=2.0)
        # net 12000; moisture 14.0 -> adj capped 0.020 -> pct 0.36 -> 4320
        assert module["status"] == "RECEIVED"
        assert module["est_lint_lbs"] == 4320
        v0 = module["version"]

        m = validate_success(api.condition_module(module["id"],
                                                  {"moisture_pct": 14.0}, OPERATOR))
        assert m["status"] == "CONDITIONING"
        assert m["est_lint_lbs"] == 4320
        assert m["version"] == v0 + 1

        m = validate_success(api.condition_module(module["id"],
                                                  {"moisture_pct": 13.0}, OPERATOR))
        assert m["status"] == "CONDITIONING", "still above 12.0: self-loop"
        assert m["est_lint_lbs"] == 4320, "moisture 13.0 still caps the discount at 0.020"
        assert m["version"] == v0 + 2

        m = validate_success(api.condition_module(module["id"],
                                                  {"moisture_pct": 9.5}, OPERATOR))
        assert m["status"] == "RECEIVED"
        assert m["moisture_pct"] == 9.5
        # adj 0.004 * 1.5 = 0.006 -> pct 0.374 -> 12000 * 0.374 = 4488
        assert m["est_lint_lbs"] == 4488
        assert m["version"] == v0 + 3


class TestModuleTransitionErrors:
    def test_invalid_transitions_from_received_and_queued(self, api):
        """PRD: "a module not in `QUEUED` yields `ERR_MODULE_NOT_GINNABLE`
        (HTTP 409)"
        PRD: "The module must be in `GINNING` (else `ERR_MODULE_NOT_COMPLETABLE`,
        HTTP 409)"
        PRD: "attempting it from any later state fails with
        `ERR_MODULE_NOT_CONDITIONABLE` (HTTP 409)."

        Design: Corner/state_machines/module_invalid_transitions_from_received_and_queued
        """
        grower = create_grower("MB-C12", "Invalid Farm")
        shift = create_shift("2026", "STAND-IV")
        module = create_module(grower["id"], ticket_number="T-1",
                               module_tag="MT-IV")

        e1 = api.start_ginning(module["id"], OPERATOR)
        validate_error(e1, ApiErrorId.ERR_MODULE_NOT_GINNABLE)

        queue_module(module["id"], shift["id"])

        e2 = api.complete_ginning(module["id"],
                                  {"bales": [{"bale_tag": "B-IV1",
                                              "net_weight_lbs": 500}]},
                                  OPERATOR)
        validate_error(e2, ApiErrorId.ERR_MODULE_NOT_COMPLETABLE)

        e3 = api.condition_module(module["id"], {"moisture_pct": 10.0}, OPERATOR)
        validate_error(e3, ApiErrorId.ERR_MODULE_NOT_CONDITIONABLE)

        module = get_module(module["id"])
        assert module["status"] == "QUEUED", "no partial state drift after rejections"

    def test_reject_terminal_lockdown(self, api):
        """PRD: "rejection moves a `RECEIVED` or `CONDITIONING` module to
        terminal `REJECTED`, records the operator's `reason`, and is refused
        from any other state with `ERR_MODULE_NOT_REJECTABLE` (HTTP 409)."
        PRD: "the module must currently be `RECEIVED` (else
        `ERR_MODULE_NOT_QUEUABLE`, HTTP 409)"
        PRD: "Conditioning is only meaningful from `RECEIVED` or `CONDITIONING`;
        attempting it from any later state fails with
        `ERR_MODULE_NOT_CONDITIONABLE` (HTTP 409)."

        Design: Corner/state_machines/module_reject_terminal_lockdown
        """
        grower = create_grower("MB-C13", "Reject Farm")
        shift = create_shift("2026", "STAND-RJ")
        m1 = create_module(grower["id"], ticket_number="T-1", module_tag="MT-R1")
        m2 = create_module(grower["id"], ticket_number="T-2", module_tag="MT-R2")
        gin_module(m2["id"], shift["id"], [("B-R2", 500)])

        m1 = validate_success(api.reject_module(
            m1["id"], {"reason": "plastic contamination"}, OPERATOR))
        assert m1["status"] == "REJECTED"

        e1 = api.queue_module(m1["id"], {"gin_shift_id": shift["id"]}, OPERATOR)
        validate_error(e1, ApiErrorId.ERR_MODULE_NOT_QUEUABLE)
        e2 = api.condition_module(m1["id"], {"moisture_pct": 10.0}, OPERATOR)
        validate_error(e2, ApiErrorId.ERR_MODULE_NOT_CONDITIONABLE)

        e3 = api.reject_module(m2["id"], {"reason": "too late"}, OPERATOR)
        validate_error(e3, ApiErrorId.ERR_MODULE_NOT_REJECTABLE)
        assert get_module(m2["id"])["status"] == "GINNED"


class TestIntakeUniqueness:
    def test_duplicate_ticket_number_same_grower_season(self, api):
        """PRD: "A `GinOperator` receives each module by cutting a grower
        ticket: the payload names the delivering grower via `grower_id`, the
        `season`, a `ticket_number` unique per grower per season, and a
        `module_tag` unique per season across all growers. A duplicate ticket
        surfaces `ERR_DUPLICATE_TICKET_NUMBER` (HTTP 409)"

        Design: Corner/validations/duplicate_ticket_number_same_grower_season
        """
        grower = create_grower("MB-C41", "Ticket Farm")
        create_module(grower["id"], ticket_number="T-1", module_tag="MT-T1")
        resp = api.create_module(
            create_module_payload(grower["id"], ticket_number="T-1",
                                  module_tag="MT-T2", gross_weight_lbs=12000),
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TICKET_NUMBER)
        _data, meta = validate_paginated(
            api.list_modules(OPERATOR, params={"grower_id": grower["id"],
                                               "season": "2026"}))
        assert meta["total_count"] == 1, "only the first T-1 module may exist"

    def test_same_module_tag_different_season_allowed(self, api):
        """PRD: "a `module_tag` unique per season across all growers"
        PRD: "a `ticket_number` unique per grower per season"

        Design: Corner/validations/same_module_tag_different_season_allowed
        """
        grower = create_grower("MB-C42", "Season Tag Farm")
        create_module(grower["id"], season="2026", ticket_number="T-1",
                      module_tag="MT-SEASON")
        m2 = validate_success(api.create_module(
            create_module_payload(grower["id"], season="2027", ticket_number="T-1",
                                  module_tag="MT-SEASON"), OPERATOR),
            expected_status=201)
        assert_module(m2)
        assert m2["season"] == "2027"


class TestCreateValidationPriority:
    def test_safety_error_beats_duplicate_tag(self, api):
        """PRD: "Only then do state-gate checks run (the transition gates and
        the OCC version match), then contamination and moisture safety plus
        segregation of duties, then uniqueness and quota rules"
        PRD: "A request failing an earlier tier never surfaces a later tier's
        error."
        PRD: "a module arriving with foreign matter above 10.0 percent is
        rejected outright with `ERR_FOREIGN_MATTER_LIMIT_EXCEEDED` (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/module_create_safety_beats_duplicate_tag
        """
        grower = create_grower("MB-601", "Dup Farm")
        create_module(grower["id"], ticket_number="T-1", module_tag="MT-DUP",
                      gross_weight_lbs=11000, moisture_pct=9.0,
                      foreign_matter_pct=5.0)
        resp = api.create_module(
            create_module_payload(grower["id"], ticket_number="T-2",
                                  module_tag="MT-DUP", gross_weight_lbs=12000,
                                  moisture_pct=9.0, foreign_matter_pct=12.0),
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FOREIGN_MATTER_LIMIT_EXCEEDED)

    def test_duplicate_tag_alone_surfaces_constraint_error(self, api):
        """PRD: "a duplicate tag within the season surfaces
        `ERR_DUPLICATE_MODULE_TAG` (HTTP 409)."
        PRD: "then contamination and moisture safety plus segregation of duties,
        then uniqueness and quota rules"

        Design: Difficulty/priority_pair_validation_conflict/module_create_safety_beats_duplicate_tag
        """
        grower = create_grower("MB-601", "Dup Farm")
        create_module(grower["id"], ticket_number="T-1", module_tag="MT-DUP",
                      gross_weight_lbs=11000, moisture_pct=9.0,
                      foreign_matter_pct=5.0)
        resp = api.create_module(
            create_module_payload(grower["id"], ticket_number="T-3",
                                  module_tag="MT-DUP", gross_weight_lbs=12000,
                                  moisture_pct=9.0, foreign_matter_pct=5.0),
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MODULE_TAG)
        _data, meta = validate_paginated(
            api.list_modules(OPERATOR, params={"grower_id": grower["id"],
                                               "season": "2026"}))
        assert meta["total_count"] == 1, "no second module with tag MT-DUP in season 2026"
