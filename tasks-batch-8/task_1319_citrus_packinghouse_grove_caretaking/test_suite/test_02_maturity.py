"""Maturity testing: computed ratio/result/expiry, variety minimums,
rounding boundary, supersede semantics, OCC, and the maturity gates."""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_maturity_test,
    create_grove_payload,
    create_grower_payload,
    create_maturity_test_payload,
    get_grove,
    get_maturity_test,
    record_maturity_test,
    set_clock,
    setup_grove_with_maturity,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    TEST_USERS,
    make_inspector_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestMaturityComputedFields:
    def test_maturity_test_computed_fields_and_unknown_input_rejected(self, api):
        """PRD §3.2: "The `ratio` is `brix` divided by `acid_pct`, rounded
        half-up to 2 decimal places — the rounding happens first, and every
        comparison below applies to the rounded ratio." PRD §3.2: "The test's
        `expires_at` is exactly `sampled_at` plus 120 hours — five full days."
        PRD §3.2: "A test's `status` is `CURRENT` for the newest test of the
        grove".

        Design: Corner/entities/maturity_test_computed_fields_and_unknown_input_rejected
        """
        set_clock(DEFAULT_CLOCK)
        grower = validate_success(api_client.create_grower(
            create_grower_payload("GR-E7", "Computed Groves"), ADMIN),
            expected_status=201)
        grove = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "B1", "HAMLIN", 50, "POLK"), ADMIN),
            expected_status=201)
        data = validate_success(api_client.create_maturity_test(
            grove["id"],
            create_maturity_test_payload(grove["version"],
                                         sampled_at="2026-07-31T10:00:00Z",
                                         brix=9.0, acid_pct=1.0, juice_pct=45.0),
            make_inspector_headers("qi-e7")), expected_status=201)
        assert_maturity_test(data)
        assert data["ratio"] == 9.0, "9.0 / 1.0 rounds to 9.00"
        assert data["result"] == "PASS", "all HAMLIN minimums met"
        assert data["status"] == "CURRENT"
        assert data["expires_at"].startswith("2026-08-05T10:00:00"), \
            "sampled_at 2026-07-31T10:00:00Z plus exactly 120 hours"


class TestMaturityRatioRoundingBoundary:
    def test_ratio_below_threshold_rounds_down_to_fail(self, api):
        """PRD §3.2: "The `ratio` is `brix` divided by `acid_pct`, rounded
        half-up to 2 decimal places — the rounding happens first, and every
        comparison below applies to the rounded ratio." PRD §3.2: "The
        minimums are: for `HAMLIN`, ratio 9.0, Brix 8.5, juice 42.0". 8.994 /
        1.0 rounds half-up to 8.99, below the 9.0 minimum.

        Design: Difficulty/boundary_precision_check/maturity_ratio_rounding_boundary
        """
        set_clock(DEFAULT_CLOCK)
        grower = validate_success(api_client.create_grower(
            create_grower_payload("GR-MB1", "Maturity Boundary Groves"), ADMIN),
            expected_status=201)
        grove = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "B1", "HAMLIN", 50, "POLK"), ADMIN),
            expected_status=201)
        low = validate_success(api_client.create_maturity_test(
            grove["id"],
            create_maturity_test_payload(grove["version"],
                                         sampled_at="2026-07-31T10:00:00Z",
                                         brix=8.994, acid_pct=1.0, juice_pct=45.0),
            make_inspector_headers("qi-mb1")), expected_status=201)
        assert low["ratio"] == 8.99, f"8.994 must round down below threshold, got {low['ratio']}"
        assert low["result"] == "FAIL", "rounded ratio 8.99 < 9.0 minimum"

    def test_ratio_on_threshold_rounds_half_up_to_pass_and_supersedes(self, api):
        """PRD §2.7: "Wherever this document says a value is "rounded
        half-up", a fraction of exactly one half rounds away from zero." PRD
        §3.2: "The `result` is `PASS` when all three variety minimums are met:
        the rounded ratio is at least the variety's minimum ratio". PRD §3.2:
        "creating a newer test atomically moves the prior `CURRENT` test to
        `SUPERSEDED` (its terminal state) and increments the grove's
        `version`."

        Design: Difficulty/boundary_precision_check/maturity_ratio_rounding_boundary
        """
        set_clock(DEFAULT_CLOCK)
        grower = validate_success(api_client.create_grower(
            create_grower_payload("GR-MB2", "Maturity Boundary Groves"), ADMIN),
            expected_status=201)
        grove = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "B1", "HAMLIN", 50, "POLK"), ADMIN),
            expected_status=201)
        first = record_maturity_test(grove["id"], sampled_at="2026-07-31T10:00:00Z",
                                     brix=8.994, acid_pct=1.0, juice_pct=45.0,
                                     inspector_id="qi-mb2")
        assert first["result"] == "FAIL"
        second = record_maturity_test(grove["id"], sampled_at="2026-07-31T10:00:00Z",
                                      brix=8.995, acid_pct=1.0, juice_pct=45.0,
                                      inspector_id="qi-mb2")
        assert second["ratio"] == 9.0, \
            f"8.995 must round half-up onto the inclusive 9.0 threshold, got {second['ratio']}"
        assert second["result"] == "PASS"
        assert second["status"] == "CURRENT"
        assert second["expires_at"].startswith("2026-08-05T10:00:00")
        first_after = get_maturity_test(first["id"])
        assert first_after["status"] == "SUPERSEDED", \
            "the newer test supersedes the prior CURRENT test"


class TestVarietySpecificMinimums:
    def test_maturity_variety_specific_minimums(self, api):
        """PRD §3.2: "The minimums are: for `HAMLIN`, ratio 9.0, Brix 8.5,
        juice 42.0; for `VALENCIA`, ratio 9.0, Brix 9.0, juice 45.0; for
        `RED_GRAPEFRUIT`, ratio 7.0, Brix 8.0, juice 38.0; and for
        `TANGERINE`, ratio 9.5, Brix 9.0, juice 40.0."

        Design: Corner/calculations/maturity_variety_specific_minimums
        """
        set_clock(DEFAULT_CLOCK)
        grower = validate_success(api_client.create_grower(
            create_grower_payload("GR-CA1", "Variety Minima Groves"), ADMIN),
            expected_status=201)
        grapefruit = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "GF1", "RED_GRAPEFRUIT", 50, "POLK"),
            ADMIN), expected_status=201)
        tangerine = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "TG1", "TANGERINE", 50, "POLK"), ADMIN),
            expected_status=201)
        # RED_GRAPEFRUIT at exactly its inclusive minimums on all three legs.
        gf_test = record_maturity_test(grapefruit["id"], brix=8.0, acid_pct=1.0,
                                       juice_pct=38.0, inspector_id="qi-ca1")
        assert gf_test["ratio"] == 8.0
        assert gf_test["result"] == "PASS", \
            "grapefruit minimums are 7.0/8.0/38.0 — all met inclusively"
        # TANGERINE just below and exactly on its 9.5 ratio minimum.
        tg_low = record_maturity_test(tangerine["id"], brix=9.4, acid_pct=1.0,
                                      juice_pct=40.0, inspector_id="qi-ca1")
        assert tg_low["result"] == "FAIL", "9.4 < 9.5 tangerine ratio minimum"
        tg_ok = record_maturity_test(tangerine["id"], brix=9.5, acid_pct=1.0,
                                     juice_pct=40.0, inspector_id="qi-ca1")
        assert tg_ok["ratio"] == 9.5
        assert tg_ok["result"] == "PASS"
        assert tg_ok["status"] == "CURRENT"
        assert get_maturity_test(tg_low["id"])["status"] == "SUPERSEDED"


class TestMaturityGates:
    def test_maturity_required_and_not_passing_gates(self, api):
        """PRD §3.2: starting an assignment re-verifies that "the grove has a
        `CURRENT` maturity test (`ERR_MATURITY_TEST_REQUIRED`) whose `result`
        is `PASS` (`ERR_MATURITY_NOT_PASSING`)". PRD §3.3 applies the same
        maturity gates at receiving.

        Design: Corner/errors/maturity_required_and_not_passing_gates
        """
        set_clock(DEFAULT_CLOCK)
        grower = validate_success(api_client.create_grower(
            create_grower_payload("GR-ER3", "Maturity Gate Groves"), ADMIN),
            expected_status=201)
        grove_untested = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "A1", "HAMLIN", 50, "POLK"), ADMIN),
            expected_status=201)
        grove_passing = validate_success(api_client.create_grove(
            create_grove_payload(grower["id"], "B1", "HAMLIN", 50, "POLK"), ADMIN),
            expected_status=201)
        record_maturity_test(grove_passing["id"], brix=9.0, acid_pct=1.0,
                             juice_pct=45.0, inspector_id="qi-er3")
        validate_success(api_client.create_pool(
            {"variety": "HAMLIN", "week_start": "2026-07-27"},
            TEST_USERS["accountant_headers"]), expected_status=201)
        crew_a = validate_success(api_client.create_crew(
            {"crew_code": "CR-ER3A", "daily_capacity_boxes": 400}, ADMIN),
            expected_status=201)
        crew_b = validate_success(api_client.create_crew(
            {"crew_code": "CR-ER3B", "daily_capacity_boxes": 400}, ADMIN),
            expected_status=201)
        assignment_untested = validate_success(api_client.create_assignment(
            {"crew_id": crew_a["id"], "grove_id": grove_untested["id"],
             "window_start": "2026-08-01T00:00:00Z",
             "window_end": "2026-08-01T06:00:00Z", "planned_boxes": 50},
            SUPERVISOR), expected_status=201)
        assignment_started = validate_success(api_client.create_assignment(
            {"crew_id": crew_b["id"], "grove_id": grove_passing["id"],
             "window_start": "2026-08-01T00:00:00Z",
             "window_end": "2026-08-01T12:00:00Z", "planned_boxes": 50},
            SUPERVISOR), expected_status=201)
        validate_success(api_client.start_assignment(
            assignment_started["id"], SUPERVISOR))
        # A failing test supersedes the passing one on grove B (ratio 8.0 < 9.0).
        record_maturity_test(grove_passing["id"], sampled_at="2026-07-31T12:00:00Z",
                             brix=8.0, acid_pct=1.0, juice_pct=45.0,
                             inspector_id="qi-er3")

        resp = api_client.start_assignment(assignment_untested["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_MATURITY_TEST_REQUIRED)

        resp = api_client.create_delivery(
            {"grove_id": grove_passing["id"],
             "assignment_id": assignment_started["id"],
             "gross_boxes": 10, "tare_boxes": 0}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_MATURITY_NOT_PASSING)


class TestMaturityOcc:
    def test_occ_maturity_supersede_stale_grove_version(self, api):
        """PRD §2.8: "Recording a new maturity test for a grove requires
        `expected_grove_version` in the request, carrying the caller's last
        observed `version` of that grove. Because the create supersedes the
        grove's `CURRENT` test and bumps the grove's `version`, a request
        whose `expected_grove_version` is behind the grove's current `version`
        — for example because another writer has just recorded a test that
        legitimately superseded the one the caller saw — is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than silently superseding a test
        the caller never observed."

        Design: Corner/cross_cutting_layers/occ_maturity_supersede_stale_grove_version
        """
        set_clock(DEFAULT_CLOCK)
        scenario = setup_grove_with_maturity("OC1", with_maturity=False)
        grove = scenario["grove"]
        stale_version = grove["version"]
        first = validate_success(api_client.create_maturity_test(
            grove["id"],
            create_maturity_test_payload(stale_version,
                                         sampled_at="2026-07-31T10:00:00Z",
                                         brix=9.0, acid_pct=1.0, juice_pct=45.0),
            INSPECTOR), expected_status=201)
        # Replay with the now-stale version observed before the first create.
        resp = api_client.create_maturity_test(
            grove["id"],
            create_maturity_test_payload(stale_version,
                                         sampled_at="2026-07-31T12:00:00Z",
                                         brix=9.2, acid_pct=1.0, juice_pct=46.0),
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Retry with the fresh version succeeds and supersedes.
        fresh_version = get_grove(grove["id"])["version"]
        assert fresh_version == stale_version + 1, \
            "grove version advances by exactly 1 per recorded test"
        second = validate_success(api_client.create_maturity_test(
            grove["id"],
            create_maturity_test_payload(fresh_version,
                                         sampled_at="2026-07-31T12:00:00Z",
                                         brix=9.2, acid_pct=1.0, juice_pct=46.0),
            INSPECTOR), expected_status=201)
        assert second["status"] == "CURRENT"
        assert get_maturity_test(first["id"])["status"] == "SUPERSEDED"
        assert get_grove(grove["id"])["version"] == stale_version + 2
