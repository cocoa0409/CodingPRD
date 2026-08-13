"""Core tests: lifecycle, SoD lock, duplicate guard, OCC-free transitions,
certified repricing cascade."""
from test_helpers import (
    ApiErrorId,
    lock_core_test,
    make_ranch_manager_headers,
    make_wool_pool_operator_headers,
    post_results,
    setup_advanced_consignment,
    setup_graded_lot,
    setup_resulted_core_test,
    submit_core_test,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCoreTestLifecycle:

    def test_core_test_lock_from_submitted_rejected(self, api, ranch_manager_headers):
        """PRD §3.4: "A successful lock (`RESULTED -> LOCKED`) stamps
        `locked_by_user_id`" — locking is defined only from RESULTED.
        PRD §3.4: "Any transition outside this machine is rejected with
        `ERR_CORE_TEST_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/core_test_lock_from_submitted_rejected
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Test Ranch", crew_name="Crew CT")
        test = submit_core_test(lot["id"], lab_ref="LAB-CT1", user_id="wpo-1")
        assert test["test_status"] == "SUBMITTED"
        resp = api.transition_core_test(test["id"], {"to": "LOCKED"}, make_ranch_manager_headers("rm-9"))
        validate_error(resp, ApiErrorId.ERR_CORE_TEST_INVALID_STATE.value, expected_status=409)
        test = validate_success(api.get_core_test(test["id"], ranch_manager_headers))
        assert test["test_status"] == "SUBMITTED"
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["certified_micron"] is None
        assert lot["certified_value_cents"] is None

    def test_duplicate_active_core_test_rejected(self, api, ranch_manager_headers):
        """PRD §3.4: "submission is allowed only while the lot is `GRADED` or
        `CONSIGNED` (otherwise `ERR_LOT_INVALID_STATE`, HTTP 409) and only
        while no other test of the same lot sits in `SUBMITTED`, `RESULTED`, or
        `LOCKED` (otherwise `ERR_DUPLICATE_ACTIVE_TEST`, HTTP 409)".
        PRD §3.4: "A test can also be rejected — from `SUBMITTED` or from
        `RESULTED` — moving it to `REJECTED`, after which a fresh core test may
        be created for the lot."

        Design: Corner/validations/duplicate_active_core_test_rejected
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Dup Ranch", crew_name="Crew D")
        test1 = submit_core_test(lot["id"], lab_ref="LAB-D1", user_id="wpo-1")
        # Second submission while the first is SUBMITTED -> duplicate-active.
        resp = api.create_core_test(
            {"lot_id": lot["id"], "lab_ref": "LAB-D2"},
            make_wool_pool_operator_headers("wpo-1"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_TEST.value, expected_status=409)
        # Reject the first (REJECTED is terminal), then a fresh test is allowed.
        validate_success(api.transition_core_test(
            test1["id"], {"to": "REJECTED"}, make_ranch_manager_headers("rm-1")))
        test3 = validate_success(api.create_core_test(
            {"lot_id": lot["id"], "lab_ref": "LAB-D3"},
            make_wool_pool_operator_headers("wpo-1")), expected_status=201)
        assert test3["test_status"] == "SUBMITTED"

    def test_core_test_sod_lock_forbidden(self, api, ranch_manager_headers):
        """PRD §3.4: "Locking is the ranch's acceptance of the lab result and
        is performed by the manager under segregation of duties: the
        `X-User-ID` of the locking manager must differ from the test's
        `submitted_by_user_id`, else `ERR_CORE_TEST_SOD` (HTTP 403)."

        Design: Corner/validations/core_test_sod_lock_forbidden
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Sod Ranch", crew_name="Crew SD")
        test = setup_resulted_core_test(
            lot["id"], measured_micron=19.0, clean_yield_pct=62.0,
            vegetable_matter_pct=1.0, lab_ref="LAB-SD1", submitter_id="wpo-1")
        assert test["test_status"] == "RESULTED"
        # The locking manager presents the same user id as the submitter.
        resp = api.transition_core_test(
            test["id"], {"to": "LOCKED"}, make_ranch_manager_headers("wpo-1"))
        validate_error(resp, ApiErrorId.ERR_CORE_TEST_SOD.value, expected_status=403)
        test = validate_success(api.get_core_test(test["id"], ranch_manager_headers))
        assert test["test_status"] == "RESULTED"
        # A different user id locks successfully.
        test = lock_core_test(test["id"], user_id="rm-1")
        assert test["test_status"] == "LOCKED"
        assert test["locked_by_user_id"] == "rm-1"

    def test_core_test_create_as_ranch_manager_forbidden(self, api, ranch_manager_headers):
        """PRD §4: POST /api/core-tests is authorized for WoolPoolOperator only.
        PRD §2.1: "A request whose role is not listed among the roles permitted
        on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/core_test_create_as_ranch_manager_forbidden
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Rbac2 Ranch", crew_name="Crew RB2")
        resp = api.create_core_test(
            {"lot_id": lot["id"], "lab_ref": "LAB-RB2"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
        _, meta = validate_paginated(
            api.list_core_tests(ranch_manager_headers, params={"lot_id": lot["id"]}))
        assert meta["total_count"] == 0, "no CoreTest row created for the lot"


class TestCoreTestLockCascade:

    def test_wool_lot_provisional_vs_certified_value(self, api, ranch_manager_headers):
        """PRD §3.4: "Link one reprices the lot: `certified_micron` takes
        `measured_micron`, `certified_yield_pct` takes `clean_yield_pct`,
        `grade_code` is rebanded from the certified micron, and
        `certified_value_cents` is computed on a clean basis — the lot's
        `weight_lbs` multiplied by `certified_yield_pct` divided by 100, kept
        at full precision without intermediate rounding, then multiplied by the
        clean-pound price of the certified band (720 cents per clean pound for
        `SUPERFINE`, 640 for `FINE`, 520 for `MEDIUM`, 400 for `STRONG`, and
        280 for `COARSE`) and rounded half-up to a whole cent; from that moment
        `effective_value_cents` is the certified value, superseding the
        provisional one".

        Design: Difficulty/dual_variant_calc/wool_lot_provisional_vs_certified_value
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="DV Ranch", crew_name="Crew DV",
            lot_weight_lbs=100.0, greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0)
        assert lot["grade_code"] == "FINE"
        assert lot["provisional_value_cents"] == 33000, "100.0 * 330"
        assert lot["certified_value_cents"] is None
        assert lot["effective_value_cents"] == 33000

        test = setup_resulted_core_test(
            lot["id"], measured_micron=19.0, clean_yield_pct=62.0,
            vegetable_matter_pct=1.2, lab_ref="LAB-DV-1", submitter_id="wpo-1")
        lock_core_test(test["id"], user_id="rm-1")

        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["certified_micron"] == 19.0
        assert lot["certified_yield_pct"] == 62.0
        assert lot["grade_code"] == "SUPERFINE", "certified 19.0 < 19.5"
        # clean_lbs = 100.0 * 62.0 / 100 = 62.0; 62.0 * 720 = 44640
        assert lot["certified_value_cents"] == 44640
        assert lot["effective_value_cents"] == 44640, "certified supersedes provisional 33000"

    def test_certified_value_uses_full_precision_intermediate(self, api, ranch_manager_headers):
        """PRD §3.4: "the lot's `weight_lbs` multiplied by `certified_yield_pct`
        divided by 100, kept at full precision without intermediate rounding,
        then multiplied by the clean-pound price of the certified band".
        PRD §2.7: "Where a formula multiplies an unrounded intermediate (the
        clean-pounds figure in certified lot valuation), the intermediate is
        kept at full precision and rounding happens only once, at the final
        cent amount."

        Design: Difficulty/dual_variant_calc/wool_lot_provisional_vs_certified_value
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=23.0, flock_name="DV2 Ranch", crew_name="Crew DV2",
            lot_weight_lbs=100.0, greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0)
        assert lot["grade_code"] == "MEDIUM"
        assert lot["provisional_value_cents"] == 26000, "100.0 * 260"
        test = setup_resulted_core_test(
            lot["id"], measured_micron=22.0, clean_yield_pct=55.5,
            vegetable_matter_pct=2.0, lab_ref="LAB-DV-2", submitter_id="wpo-1")
        lock_core_test(test["id"], user_id="rm-1")
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["grade_code"] == "MEDIUM", "21.5 <= 22.0 < 24.5"
        # clean_lbs = 55.5; 55.5 * 520 = 28860 exactly; round-half-up at the end.
        assert lot["certified_value_cents"] == 28860
        assert lot["effective_value_cents"] == 28860

    def test_core_test_lock_repricing_cascade(self, api, ranch_manager_headers):
        """PRD §3.4: "Link two reaches the consignment: if the lot currently
        has a consignment in `ACCEPTED` or `ADVANCED`, that consignment's
        `version` increments, and when it is `ADVANCED` its
        `pending_clawback_cents` is set to the excess of `advance_cents` over
        70 percent of the new `certified_value_cents` (that product rounded
        half-up), or zero when the certified value has grown enough to cover
        the advance."
        PRD §3.5: "`advance_cents` becomes 70 percent of the lot's
        `effective_value_cents` at that moment — certified when a locked core
        test exists, provisional otherwise — rounded half-up to a whole cent."

        Design: Difficulty/transitive_cascade/core_test_lock_repricing_cascade
        """
        flock, clip, lot, con = setup_advanced_consignment(
            estimated_micron=20.0, pool_ref="WWPA-LOCK", flock_name="Lock Ranch",
            crew_name="Crew L", lot_weight_lbs=100.0,
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0)
        con_before = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con_before["advance_cents"] == 23100, "round_half_up(0.70 * 33000)"
        con_version_before = con_before["version"]

        test = setup_resulted_core_test(
            lot["id"], measured_micron=24.0, clean_yield_pct=55.0,
            vegetable_matter_pct=2.0, lab_ref="LAB-L1", submitter_id="wpo-1")
        lock_core_test(test["id"], user_id="rm-1")

        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["certified_micron"] == 24.0
        assert lot["grade_code"] == "MEDIUM", "21.5 <= 24.0 < 24.5"
        # clean_lbs = 55.0; 55.0 * 520 = 28600
        assert lot["certified_value_cents"] == 28600

        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        # pending_clawback = 23100 - round_half_up(0.70 * 28600) = 23100 - 20020 = 3080
        assert con["pending_clawback_cents"] == 3080
        assert con["version"] > con_version_before, "cascade bumped the consignment version"
        assert con["consignment_status"] == "ADVANCED", "cascade reprices; it does not move the machine"

    def test_lock_cascade_zero_clawback_when_certified_covers_advance(self, api, ranch_manager_headers):
        """PRD §3.4: "or zero when the certified value has grown enough to
        cover the advance."

        Design: Difficulty/transitive_cascade/core_test_lock_repricing_cascade
        """
        flock, clip, lot, con = setup_advanced_consignment(
            estimated_micron=26.0, pool_ref="WWPA-LOCK2", flock_name="Lock2 Ranch",
            crew_name="Crew L2", lot_weight_lbs=100.0,
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0)
        con_before = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        # provisional = 100.0 * 190 = 19000; advance = round(0.70 * 19000) = 13300
        assert con_before["advance_cents"] == 13300
        # Certified comes back BETTER than the estimate: SUPERFINE at high yield.
        test = setup_resulted_core_test(
            lot["id"], measured_micron=18.0, clean_yield_pct=80.0,
            vegetable_matter_pct=1.0, lab_ref="LAB-L2", submitter_id="wpo-1")
        lock_core_test(test["id"], user_id="rm-1")
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        # clean_lbs = 80.0; 80.0 * 720 = 57600 -> 0.70 * 57600 = 40320 >= 13300
        assert lot["certified_value_cents"] == 57600
        con = validate_success(api.get_consignment(con["id"], ranch_manager_headers))
        assert con["pending_clawback_cents"] == 0, "certified value covers the advance"
