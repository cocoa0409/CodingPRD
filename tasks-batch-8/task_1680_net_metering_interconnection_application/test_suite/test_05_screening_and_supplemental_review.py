"""Technical screens (transformer/feeder/fast-track) and supplemental review."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_documents,
    add_customer_account,
    api_client,
    assert_screening_report,
    create_draft_application,
    create_feeder,
    create_supplemental_review_payload,
    create_transformer,
    decide_completeness,
    get_application,
    get_success_data,
    setup_program_with_grid,
    upload_required_documents,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _submit_for_capacity(sc, ctx, size, production=30_000_000):
    app = create_draft_application(sc, ctx, size=size, production=production)
    accept_documents(upload_required_documents(ctx, app["id"]))
    get_success_data(
        api_client.submit_application(app["id"], ctx["applicant"]))
    return decide_completeness(app["id"], "COMPLETE")


def _build_basis_pair():
    """Two programs with identical grid data and queue contents, differing
    only in screening basis: C runs COMMITTED, Q runs INCLUDE_QUEUED.

    Each program (cap 35,000 W): app A 20,000 W reserved, app B 10,000 W
    reserved, app W 18,000 W queued at position 1. The shared feeder per
    program has peak 1,000,000 W (limit 150,000) with 115,000 W pre-existing.
    """
    pair = {}
    for key, basis in (("c", "COMMITTED"), ("q", "INCLUDE_QUEUED")):
        name = key.upper()
        sc = setup_program_with_grid(
            name,
            program_overrides={"aggregate_cap_watts": 35_000,
                               "screening_basis": basis},
            feeder_overrides={"peak_load_watts": 1_000_000,
                              "pre_existing_der_watts": 115_000})
        ctx_a = add_customer_account(sc, "A",
                                     prior_annual_usage_wh=50_000_000)
        ctx_b = add_customer_account(sc, "B",
                                     prior_annual_usage_wh=50_000_000)
        ctx_w = add_customer_account(sc, "W",
                                     prior_annual_usage_wh=50_000_000)
        app_a = _submit_for_capacity(sc, ctx_a, 20_000)
        app_b = _submit_for_capacity(sc, ctx_b, 10_000)
        app_w = _submit_for_capacity(sc, ctx_w, 18_000)
        assert app_a["application_status"] == "CAPACITY_RESERVED"
        assert app_b["application_status"] == "CAPACITY_RESERVED"
        assert app_w["application_status"] == "WAITING_FOR_CAPACITY"
        pair[key] = {"sc": sc, "app_a": app_a, "app_b": app_b,
                     "app_w": app_w}
    return pair


class TestScreeningBasisVariants:
    def test_identical_grid_data_flips_outcome_between_bases(self, api):
        """PRD §3.4: "When the program's basis is `INCLUDE_QUEUED`, the sizes
        of queued (`WAITING_FOR_CAPACITY`) applications on the node are added
        as well; under `COMMITTED` they are excluded, so identical grid data
        can flip a screen between the two bases."
        PRD §3.4: "The feeder screen compares `feeder_aggregate_after_watts`
        against `feeder_limit_watts`, which is fifteen percent of
        `peak_load_watts` floored to whole watts; this screen is strict — the
        after-figure must be strictly less than the limit, and equality fails —
        with the verdict in `feeder_screen_passed`."

        Design: Difficulty/dual_variant_calc/dvc_screening_basis_committed_vs_include_queued
        """
        pair = _build_basis_pair()
        # Screen each program's app B (10,000 W).
        rep_c = validate_success(api.create_screening_report(
            {"application_id": pair["c"]["app_b"]["id"]}, ENGINEER), 201)
        rep_q = validate_success(api.create_screening_report(
            {"application_id": pair["q"]["app_b"]["id"]}, ENGINEER), 201)

        # COMMITTED: 115,000 + 20,000 (A) + 10,000 (B) = 145,000 < 150,000.
        assert_screening_report(rep_c)
        assert rep_c["aggregate_basis"] == "COMMITTED"
        assert rep_c["outcome"] == "PASSED"
        assert rep_c["feeder_aggregate_after_watts"] == 145_000
        assert rep_c["feeder_limit_watts"] == 150_000
        assert rep_c["feeder_screen_passed"] is True

        # INCLUDE_QUEUED: + 18,000 (W queued) = 163,000 >= 150,000.
        assert_screening_report(rep_q)
        assert rep_q["aggregate_basis"] == "INCLUDE_QUEUED"
        assert rep_q["outcome"] == "FAILED"
        assert rep_q["feeder_aggregate_after_watts"] == 163_000
        assert rep_q["feeder_screen_passed"] is False
        assert rep_q["failing_screens"] == ["FEEDER_PENETRATION"]

        assert (get_application(pair["c"]["app_b"]["id"])
                ["application_status"] == "SCREEN_PASSED")
        assert (get_application(pair["q"]["app_b"]["id"])
                ["application_status"] == "SUPPLEMENTAL_REVIEW")
        # Screening does not disturb the queues.
        assert (get_application(pair["c"]["app_w"]["id"])
                ["queue_position"] == 1)
        assert (get_application(pair["q"]["app_w"]["id"])
                ["queue_position"] == 1)

    def test_report_pins_basis_and_screen_verdicts_at_compute_time(self, api):
        """PRD §3.4: "The report copies the program's `screening_basis` into
        its own `aggregate_basis` at compute time, so a report forever reflects
        the basis under which it was run."
        PRD §3.4: "Each report carries a `screening_round` equal to one plus
        the number of prior reports for that application, is created with
        `report_status` `CURRENT`, and supersedes any previously `CURRENT`
        report, which moves to `SUPERSEDED`."

        Design: Difficulty/dual_variant_calc/dvc_screening_basis_committed_vs_include_queued
        """
        pair = _build_basis_pair()
        rep_c = validate_success(api.create_screening_report(
            {"application_id": pair["c"]["app_b"]["id"]}, ENGINEER), 201)
        rep_q = validate_success(api.create_screening_report(
            {"application_id": pair["q"]["app_b"]["id"]}, ENGINEER), 201)

        for rep, basis in ((rep_c, "COMMITTED"), (rep_q, "INCLUDE_QUEUED")):
            assert rep["aggregate_basis"] == basis
            assert rep["screening_round"] == 1
            assert rep["report_status"] == "CURRENT"
            # Both 10 kW applications sit far inside the transformer limit
            # (5,000,000 W) and the 2 MW fast-track size.
            assert rep["transformer_screen_passed"] is True
            assert rep["size_within_fast_track"] is True

        assert rep_c["failing_screens"] == [], (
            "a PASSED report has an empty failing_screens subset")
        assert rep_q["failing_screens"] == ["FEEDER_PENETRATION"], (
            "the queued 18 kW is the only thing that flipped the feeder "
            "screen under INCLUDE_QUEUED")


class TestFeederScreenStrictBoundary:
    def test_equality_fails_and_one_watt_under_passes(self, api):
        """PRD §3.4: "The feeder screen compares `feeder_aggregate_after_watts`
        against `feeder_limit_watts`, which is fifteen percent of
        `peak_load_watts` floored to whole watts; this screen is strict — the
        after-figure must be strictly less than the limit, and equality fails —
        with the verdict in `feeder_screen_passed`."
        PRD §3.4: "The report's `outcome` is `PASSED` when all three screens
        pass and `FAILED` otherwise, with `failing_screens` holding the ordered
        subset of `TRANSFORMER_CAPACITY`, `FEEDER_PENETRATION`, and
        `FAST_TRACK_SIZE` that failed."

        Design: Difficulty/boundary_precision_check/bpc_feeder_screen_strict_boundary
        """
        sc = setup_program_with_grid("FB")
        feeder1 = create_feeder("F-FB1", peak_load_watts=1_000_000,
                                pre_existing_der_watts=140_000)
        tx1 = create_transformer(feeder1["id"], "T-FB1",
                                 nameplate_watts=10_000_000,
                                 pre_existing_der_watts=0)
        feeder2 = create_feeder("F-FB2", peak_load_watts=1_000_000,
                                pre_existing_der_watts=139_999)
        tx2 = create_transformer(feeder2["id"], "T-FB2",
                                 nameplate_watts=10_000_000,
                                 pre_existing_der_watts=0)

        ctx_x = add_customer_account(sc, "X",
                                     prior_annual_usage_wh=100_000_000,
                                     transformer=tx1)
        app_x = _submit_for_capacity(sc, ctx_x, 10_000)
        ctx_y = add_customer_account(sc, "Y",
                                     prior_annual_usage_wh=100_000_000,
                                     transformer=tx2)
        app_y = _submit_for_capacity(sc, ctx_y, 10_000)

        # X: 140,000 + 10,000 = 150,000 == limit -> strict screen FAILS.
        rep_x = validate_success(api.create_screening_report(
            {"application_id": app_x["id"]}, ENGINEER), 201)
        assert rep_x["feeder_aggregate_after_watts"] == 150_000
        assert rep_x["feeder_limit_watts"] == 150_000
        assert rep_x["feeder_screen_passed"] is False
        assert rep_x["outcome"] == "FAILED"
        assert rep_x["failing_screens"] == ["FEEDER_PENETRATION"]

        # Y: 139,999 + 10,000 = 149,999 < 150,000 -> passes.
        rep_y = validate_success(api.create_screening_report(
            {"application_id": app_y["id"]}, ENGINEER), 201)
        assert rep_y["feeder_aggregate_after_watts"] == 149_999
        assert rep_y["feeder_screen_passed"] is True
        assert rep_y["outcome"] == "PASSED"

        assert (get_application(app_x["id"])["application_status"]
                == "SUPPLEMENTAL_REVIEW")
        assert (get_application(app_y["id"])["application_status"]
                == "SCREEN_PASSED")

    def test_feeder_aggregate_spans_all_transformers_on_the_feeder(self, api):
        """PRD §3.4: "For the transformer and feeder screens, the server first
        builds a basis aggregate at each node: the node's
        `pre_existing_der_watts`, plus the sizes of other reservation-holding
        applications — those in `CAPACITY_RESERVED`, `SUPPLEMENTAL_REVIEW`,
        `SCREEN_PASSED`, `AWAITING_COST_ESTIMATE`, `CUSTOMER_DECISION_PENDING`,
        or `UPGRADE_IN_PROGRESS` — whose accounts sit on the node, plus the
        sizes of interconnected applications (`PTO_GRANTED` or `OPERATING`) on
        the node."
        PRD §3.4: "this screen is strict — the after-figure must be strictly
        less than the limit, and equality fails"

        Design: Difficulty/boundary_precision_check/bpc_feeder_screen_strict_boundary
        """
        sc = setup_program_with_grid("FB2")
        feeder = create_feeder("F-FBX", peak_load_watts=1_000_000,
                               pre_existing_der_watts=100_000)
        tx1 = create_transformer(feeder["id"], "T-FBX1",
                                 nameplate_watts=10_000_000,
                                 pre_existing_der_watts=0)
        tx2 = create_transformer(feeder["id"], "T-FBX2",
                                 nameplate_watts=10_000_000,
                                 pre_existing_der_watts=0)

        ctx_a = add_customer_account(sc, "A",
                                     prior_annual_usage_wh=100_000_000,
                                     transformer=tx1)
        app_a = _submit_for_capacity(sc, ctx_a, 49_999)
        assert app_a["application_status"] == "CAPACITY_RESERVED"

        ctx_b = add_customer_account(sc, "B",
                                     prior_annual_usage_wh=100_000_000,
                                     transformer=tx2)
        app_b = _submit_for_capacity(sc, ctx_b, 10_000)

        # Feeder after = 100,000 pre-existing + 49,999 (A on tx1) + 10,000 (B)
        # = 159,999 >= 150,000: the reserved sibling on the sibling transformer
        # pushes the screened application over the strict limit.
        rep_b = validate_success(api.create_screening_report(
            {"application_id": app_b["id"]}, ENGINEER), 201)
        assert rep_b["feeder_aggregate_after_watts"] == 159_999
        assert rep_b["feeder_screen_passed"] is False
        assert rep_b["outcome"] == "FAILED"
        assert rep_b["failing_screens"] == ["FEEDER_PENETRATION"]
        # B's own transformer is clean: 0 + 10,000 <= 5,000,000.
        assert rep_b["transformer_screen_passed"] is True


class TestTransformerScreenInclusiveBoundary:
    def test_equality_passes_and_one_watt_over_fails(self, api):
        """PRD §3.4: "The transformer screen compares
        `transformer_aggregate_after_watts` — the transformer's basis aggregate
        plus the screened size — against `transformer_limit_watts`, which is
        half of `nameplate_watts` floored to whole watts; the screen passes
        when the after-figure is less than or equal to the limit, and
        `transformer_screen_passed` records the verdict."

        Design: Corner/calculations/c_transformer_screen_inclusive_boundary
        """
        sc = setup_program_with_grid("TB")
        feeder = sc["feeder"]
        tx1 = create_transformer(feeder["id"], "T-TB1",
                                 nameplate_watts=100_000,
                                 pre_existing_der_watts=45_000)
        tx2 = create_transformer(feeder["id"], "T-TB2",
                                 nameplate_watts=100_000,
                                 pre_existing_der_watts=45_000)

        ctx1 = add_customer_account(sc, "1",
                                    prior_annual_usage_wh=100_000_000,
                                    transformer=tx1)
        app1 = _submit_for_capacity(sc, ctx1, 5_000)
        ctx2 = add_customer_account(sc, "2",
                                    prior_annual_usage_wh=100_000_000,
                                    transformer=tx2)
        app2 = _submit_for_capacity(sc, ctx2, 5_001)

        # App1: 45,000 + 5,000 = 50,000 == floor(100,000 * 50 / 100) -> passes
        # on the inclusive comparison.
        rep1 = validate_success(api.create_screening_report(
            {"application_id": app1["id"]}, ENGINEER), 201)
        assert rep1["transformer_aggregate_after_watts"] == 50_000
        assert rep1["transformer_limit_watts"] == 50_000
        assert rep1["transformer_screen_passed"] is True
        assert rep1["outcome"] == "PASSED"

        # App2: 50,001 > 50,000 -> TRANSFORMER_CAPACITY fails.
        rep2 = validate_success(api.create_screening_report(
            {"application_id": app2["id"]}, ENGINEER), 201)
        assert rep2["transformer_aggregate_after_watts"] == 50_001
        assert rep2["transformer_screen_passed"] is False
        assert rep2["outcome"] == "FAILED"
        assert rep2["failing_screens"] == ["TRANSFORMER_CAPACITY"]


class TestScreeningStateGate:
    def test_screening_requires_capacity_reserved(self, api):
        """PRD §3.4: "With capacity reserved, a `DistributionEngineer` runs the
        technical screens by commissioning a screening report for the
        application."
        PRD §2.10: "Eighth, the primary resource being in a state that permits
        the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline)."

        Design: Corner/state_machines/sm_screening_requires_capacity_reserved
        """
        sc = setup_program_with_grid("SR", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        resp = api.create_screening_report({"application_id": app["id"]},
                                           ENGINEER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestOneOpenSupplementalReview:
    def test_second_open_review_rejected(self, api):
        """PRD §3.4: "In supplemental review, the engineer opens a study — at
        most one `OPEN` review per application, with a second attempt rejected
        as `ERR_SUPPLEMENTAL_REVIEW_OPEN` — choosing a `review_type` of
        `FACILITIES_STUDY` or `SYSTEM_IMPACT_STUDY` and optionally recording
        `findings`"

        Design: Corner/errors/err_supplemental_review_open_blocks_second
        """
        sc = setup_program_with_grid(
            "SO",
            feeder_overrides={"peak_load_watts": 1_000_000,
                              "pre_existing_der_watts": 140_000})
        ctx = add_customer_account(sc, "1",
                                   prior_annual_usage_wh=100_000_000)
        app = _submit_for_capacity(sc, ctx, 20_000)
        report = validate_success(api.create_screening_report(
            {"application_id": app["id"]}, ENGINEER), 201)
        assert report["outcome"] == "FAILED"

        review = validate_success(api.create_supplemental_review(
            create_supplemental_review_payload(app["id"]), ENGINEER), 201)
        assert review["review_status"] == "OPEN"

        resp = api.create_supplemental_review(
            create_supplemental_review_payload(
                app["id"], review_type="SYSTEM_IMPACT_STUDY"), ENGINEER)
        validate_error(resp, ApiErrorId.ERR_SUPPLEMENTAL_REVIEW_OPEN, 422)
