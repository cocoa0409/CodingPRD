"""License negotiation rounds, execution gates (OCC, COI coverage,
exclusivity overlap, upfront floor), and the clock-driven sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_license,
    add_milestone,
    assert_license,
    create_approved_coi_plan,
    create_license,
    create_license_payload,
    create_startup_fixture,
    execute_license,
    execute_license_payload,
    set_clock,
    setup_active_license,
    setup_patent_pursued_disclosure,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import api_client

ADMIN = TEST_USERS["system_admin_headers"]
TTO = TEST_USERS["tto_headers"]
LM = TEST_USERS["licensing_manager_headers"]


class TestNegotiationCycle:
    def test_negotiation_and_default_cure_cycle(self, api):
        """PRD: "A counter by the `LicensingManager` toggles the license
        between `IN_NEGOTIATION` and `COUNTERED` — countering from either
        state is legal, from any other state it is
        `ERR_LICENSE_NOT_NEGOTIABLE` — overwriting whichever of
        `royalty_rate_bp`, `minimum_annual_royalty_cents`,
        `upfront_fee_cents`, or `expiration_date` appear in the payload and
        incrementing the license's `version` by 1 each round."
        PRD: "Curing returns the license to `ACTIVE` and clears both
        `default_notice_date` and `cure_deadline`".

        Design: Difficulty/non_linear_state_machine/license_negotiation_and_default_cure_cycles
        """
        ctx = setup_patent_pursued_disclosure()
        lic = create_license(ctx["disclosure"]["id"])

        r1 = validate_success(api.counter_license(
            lic["id"], {"royalty_rate_bp": 450}, LM))
        assert r1["status"] == "COUNTERED"
        r2 = validate_success(api.counter_license(
            lic["id"], {"royalty_rate_bp": 475}, LM))
        assert r2["status"] == "IN_NEGOTIATION"
        r3 = validate_success(api.counter_license(
            lic["id"], {"upfront_fee_cents": 10000}, LM))
        assert r3["status"] == "COUNTERED"
        assert r3["royalty_rate_bp"] == 475, \
            "a counter overwrites only the fields present in its payload"
        executed = validate_success(api.execute_license(
            lic["id"], execute_license_payload(r3["version"]), LM))
        assert executed["status"] == "EXECUTED"

        set_clock("2026-08-01T00:00:00Z")  # sweep -> ACTIVE
        add_milestone(lic["id"], due_date="2026-06-01T00:00:00Z",
                      description="First sale", amount_cents=50000)
        defaulted = validate_success(api.declare_default(
            lic["id"], {"reason": "Milestone overdue"}, LM))
        assert defaulted["status"] == "DEFAULT_NOTICE"
        cured = validate_success(api.cure_license(lic["id"], LM))
        assert cured["status"] == "ACTIVE"
        assert cured.get("default_notice_date") is None
        assert cured.get("cure_deadline") is None

    def test_counter_rounds_overwrite_terms_and_bump_version(self, api):
        """PRD: "overwriting whichever of `royalty_rate_bp`,
        `minimum_annual_royalty_cents`, `upfront_fee_cents`, or
        `expiration_date` appear in the payload and incrementing the
        license's `version` by 1 each round."

        Design: Difficulty/non_linear_state_machine/license_negotiation_and_default_cure_cycles
        """
        ctx = setup_patent_pursued_disclosure()
        lic = create_license(ctx["disclosure"]["id"],
                             minimum_annual_royalty_cents=5000)
        r1 = validate_success(api.counter_license(
            lic["id"], {"royalty_rate_bp": 450}, LM))
        assert r1["version"] == lic["version"] + 1, "each round increments version"
        r2 = validate_success(api.counter_license(
            lic["id"], {"minimum_annual_royalty_cents": 7000}, LM))
        assert r2["version"] == r1["version"] + 1
        assert r2["royalty_rate_bp"] == 450, "untouched fields persist"
        assert r2["minimum_annual_royalty_cents"] == 7000

    def test_counter_on_executed_license_rejected(self, api):
        """PRD: "A counter by the `LicensingManager` toggles the license
        between `IN_NEGOTIATION` and `COUNTERED` — countering from either
        state is legal, from any other state it is
        `ERR_LICENSE_NOT_NEGOTIABLE`".

        Design: Corner/state_machines/counter_on_executed_license_rejected
        """
        ctx = setup_patent_pursued_disclosure()
        lic = create_license(ctx["disclosure"]["id"])
        execute_license(lic["id"], lic["version"])
        resp = api.counter_license(lic["id"], {"royalty_rate_bp": 400}, LM)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_NEGOTIABLE, 409)
        refreshed = validate_success(api.get_license(lic["id"], ADMIN))
        assert refreshed["royalty_rate_bp"] == 500


class TestExecutionGates:
    def test_exclusive_upfront_floor_exact_boundary(self, api):
        """PRD: "Fourth — checked last, after every other execution gate —
        an `EXCLUSIVE` license must carry an `upfront_fee_cents` of at least
        500,000 cents, else `ERR_UPFRONT_BELOW_FLOOR` (HTTP 402)."

        Design: Corner/validations/exclusive_upfront_floor_exact_boundary
        """
        ctx_a = setup_patent_pursued_disclosure(title="A")
        lic_low = create_license(ctx_a["disclosure"]["id"],
                                 licensee_name="Alpha", exclusivity="EXCLUSIVE",
                                 upfront_fee_cents=499_999)
        resp = api.execute_license(
            lic_low["id"], execute_license_payload(lic_low["version"]), LM)
        validate_error(resp, ApiErrorId.ERR_UPFRONT_BELOW_FLOOR, 402)

        ctx_b = setup_patent_pursued_disclosure(title="B")
        lic_ok = create_license(ctx_b["disclosure"]["id"],
                                licensee_name="Beta", exclusivity="EXCLUSIVE",
                                upfront_fee_cents=500_000)
        executed = validate_success(api.execute_license(
            lic_ok["id"], execute_license_payload(lic_ok["version"]), LM))
        assert executed["status"] == "EXECUTED", \
            "upfront exactly at the 500,000-cent floor passes"

    def test_rate_out_of_range_rejected(self, api):
        """PRD: "a `royalty_rate_bp` between 100 and 2000 basis points".
        PRD: "fourth, request-body schema conformance — required fields
        present, enum membership valid, integer ranges respected, unknown
        payload fields rejected — with `ERR_INVALID_REQUEST`".

        Design: Corner/validations/rate_out_of_range_rejected
        """
        ctx = setup_patent_pursued_disclosure()
        resp_low = api.create_license(
            ctx["disclosure"]["id"],
            create_license_payload(royalty_rate_bp=99), LM)
        validate_error(resp_low, ApiErrorId.ERR_INVALID_REQUEST, 400)
        resp_high = api.create_license(
            ctx["disclosure"]["id"],
            create_license_payload(royalty_rate_bp=2001), LM)
        validate_error(resp_high, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_exclusive_overlap_closed_interval(self, api):
        """PRD: "Third, for an `EXCLUSIVE` license, the closed interval from
        `effective_date` through `expiration_date` — both ends inclusive —
        must not intersect the corresponding closed interval of any other
        `EXECUTED`, `ACTIVE`, or `DEFAULT_NOTICE` exclusive license on the
        same disclosure; an intersection is `ERR_EXCLUSIVE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/exclusive_license_closed_interval_overlap
        """
        ctx = setup_patent_pursued_disclosure()
        disc_id = ctx["disclosure"]["id"]
        l1 = create_license(disc_id, licensee_name="Alpha",
                            exclusivity="EXCLUSIVE",
                            effective_date="2026-01-01T00:00:00Z",
                            expiration_date="2027-12-31T00:00:00Z",
                            upfront_fee_cents=600_000)
        execute_license(l1["id"], l1["version"])
        l2 = create_license(disc_id, licensee_name="Beta",
                            exclusivity="EXCLUSIVE",
                            effective_date="2027-12-31T00:00:00Z",
                            expiration_date="2029-01-01T00:00:00Z",
                            upfront_fee_cents=600_000)
        resp = api.execute_license(
            l2["id"], execute_license_payload(l2["version"]), LM)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_OVERLAP, 409)

        # Strictly after the executed license's expiration is free.
        l3 = create_license(disc_id, licensee_name="Gamma",
                            exclusivity="EXCLUSIVE",
                            effective_date="2028-01-01T00:00:00Z",
                            expiration_date="2029-01-01T00:00:00Z",
                            upfront_fee_cents=600_000)
        executed = validate_success(api.execute_license(
            l3["id"], execute_license_payload(l3["version"]), LM))
        assert executed["status"] == "EXECUTED"

    def test_nonexclusive_license_immune_to_exclusivity_overlap(self, api):
        """PRD: "Third, for an `EXCLUSIVE` license, the closed interval from
        `effective_date` through `expiration_date` — both ends inclusive —
        must not intersect the corresponding closed interval of any other
        `EXECUTED`, `ACTIVE`, or `DEFAULT_NOTICE` exclusive license on the
        same disclosure; an intersection is `ERR_EXCLUSIVE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/exclusive_license_closed_interval_overlap
        """
        ctx = setup_patent_pursued_disclosure()
        disc_id = ctx["disclosure"]["id"]
        l1 = create_license(disc_id, licensee_name="Alpha",
                            exclusivity="EXCLUSIVE",
                            effective_date="2026-01-01T00:00:00Z",
                            expiration_date="2027-12-31T00:00:00Z",
                            upfront_fee_cents=600_000)
        execute_license(l1["id"], l1["version"])
        # A NON_EXCLUSIVE license fully inside the exclusive window is not
        # subject to the exclusivity intersection rule.
        l2 = create_license(disc_id, licensee_name="Beta",
                            exclusivity="NON_EXCLUSIVE",
                            effective_date="2026-06-01T00:00:00Z",
                            expiration_date="2027-06-01T00:00:00Z")
        executed = validate_success(api.execute_license(
            l2["id"], execute_license_payload(l2["version"]), LM))
        assert executed["status"] == "EXECUTED"


class TestExecutionPriorityAndOcc:
    def test_execute_safety_coi_beats_fiscal_upfront(self, api):
        """PRD: "The pipeline runs: ... sixth, segregation-of-duties and
        compliance gates (`ERR_SEGREGATION_OF_DUTIES`,
        `ERR_TITLE_NOT_ELECTED`, `ERR_COI_COVERAGE_REQUIRED`); ... and last,
        fiscal floors — notably the exclusive-license upfront floor."
        PRD: "Second, when a `startup_id` is linked, an `APPROVED`
        conflict-of-interest plan for that startup must cover the current
        clock, else `ERR_COI_COVERAGE_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/execute_safety_coi_beats_fiscal_upfront
        """
        ctx = setup_patent_pursued_disclosure()
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        lic = create_license(ctx["disclosure"]["id"],
                             licensee_name="SpinCo", exclusivity="EXCLUSIVE",
                             upfront_fee_cents=100_000, startup_id=su["id"])
        set_clock("2026-08-01T00:00:00Z")
        resp = api.execute_license(
            lic["id"], execute_license_payload(lic["version"]), LM)
        validate_error(resp, ApiErrorId.ERR_COI_COVERAGE_REQUIRED, 409)
        refreshed = validate_success(api.get_license(lic["id"], ADMIN))
        assert refreshed["status"] == "IN_NEGOTIATION"

    def test_execute_upfront_floor_after_safety_passes(self, api):
        """PRD: "Fourth — checked last, after every other execution gate —
        an `EXCLUSIVE` license must carry an `upfront_fee_cents` of at least
        500,000 cents, else `ERR_UPFRONT_BELOW_FLOOR` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/execute_safety_coi_beats_fiscal_upfront
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        create_approved_coi_plan(su["id"], inv_id)
        lic = create_license(ctx["disclosure"]["id"],
                             licensee_name="SpinCo", exclusivity="EXCLUSIVE",
                             upfront_fee_cents=100_000, startup_id=su["id"])
        set_clock("2026-08-01T00:00:00Z")
        resp = api.execute_license(
            lic["id"], execute_license_payload(lic["version"]), LM)
        validate_error(resp, ApiErrorId.ERR_UPFRONT_BELOW_FLOOR, 402)

    def test_occ_execute_stale_after_counter(self, api):
        """PRD: "First, optimistic concurrency: the request must carry
        `expected_license_version` matching the license's current `version`;
        if counter rounds have advanced the version since the client last
        read the terms, execution is rejected with `ERR_STALE_VERSION`
        (HTTP 412) so a client never signs terms it has not seen."

        Design: Corner/cross_cutting_layers/occ_execute_stale_after_counter
        """
        ctx = setup_patent_pursued_disclosure()
        lic = create_license(ctx["disclosure"]["id"])
        stale_version = lic["version"]
        countered = validate_success(api.counter_license(
            lic["id"], {"royalty_rate_bp": 450}, LM))
        resp = api.execute_license(
            lic["id"], execute_license_payload(stale_version), LM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        executed = validate_success(api.execute_license(
            lic["id"], execute_license_payload(countered["version"]), LM))
        assert executed["status"] == "EXECUTED"


class TestClockSweep:
    def test_clock_sweep_activates_and_expires_licenses(self, api):
        """PRD: "Advancing the clock triggers a license sweep: every
        `EXECUTED` license whose `effective_date` has been reached
        transitions to `ACTIVE`, and every `EXECUTED` or `ACTIVE` license
        whose `expiration_date` has been reached transitions to `EXPIRED`.
        The sweep response reports the new clock value together with the
        lists of activated and expired license identifiers."

        Design: Corner/endpoints/clock_sweep_activates_and_expires_licenses
        """
        ctx = setup_patent_pursued_disclosure()
        disc_id = ctx["disclosure"]["id"]
        l1 = create_license(disc_id, licensee_name="Alpha",
                            effective_date="2026-01-01T00:00:00Z",
                            expiration_date="2026-12-31T00:00:00Z")
        execute_license(l1["id"], l1["version"])
        l2 = create_license(disc_id, licensee_name="Beta",
                            effective_date="2027-01-01T00:00:00Z",
                            expiration_date="2027-06-30T00:00:00Z")
        execute_license(l2["id"], l2["version"])

        sweep1 = validate_success(api.set_clock(
            {"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN))
        assert l1["id"] in sweep1["activated_license_ids"], \
            "L1's effective date has been reached"
        l2_mid = validate_success(api.get_license(l2["id"], ADMIN))
        assert l2_mid["status"] == "EXECUTED", \
            "L2's effective date is in the future — not yet ACTIVE"

        sweep2 = validate_success(api.set_clock(
            {"to_iso8601": "2027-07-01T00:00:00Z"}, ADMIN))
        l1_end = validate_success(api.get_license(l1["id"], ADMIN))
        l2_end = validate_success(api.get_license(l2["id"], ADMIN))
        assert l1_end["status"] == "EXPIRED"
        assert l2_end["status"] == "EXPIRED", \
            "a license whose window never opened expires EXECUTED -> EXPIRED"
        assert l1["id"] in sweep2["expired_license_ids"]
        assert l2["id"] in sweep2["expired_license_ids"]
