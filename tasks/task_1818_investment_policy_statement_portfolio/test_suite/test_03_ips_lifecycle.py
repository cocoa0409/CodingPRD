"""IPS drafting, target replacement, review pipeline, and cadence math (PRD §3.2)."""
from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    ApiErrorId,
    add_position,
    allocation_targets_payload,
    assert_iso_instant_equal,
    create_active_client,
    create_active_ips,
    create_benchmark,
    create_ips_payload,
    create_security,
    deposit,
    get_success_data,
    make_client_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

T_60_40 = [
    {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
]
T_CASH = [
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
]


class TestIpsCreation:
    def test_ips_risk_score_range_enforced(self, api):
        """PRD §3.2: "a `risk_tolerance_score` snapshot between 1 and 100
        inclusive" — values 0 and 101 fall outside the range.
        PRD §2.7: "required fields present; types valid; enum values within
        their declared sets; ranges enforced (risk scores between 1 and 100
        inclusive; `target_pct` greater than 0 and at most 100; `band_pct`
        greater than 0 and at most 50; quantities at least 1 on intake;
        `amount_cents` greater than 0; price inputs at least 1;
        `review_cadence_months` between 1 and 24 inclusive; dates in
        `YYYY-MM-DD` form; datetimes in ISO 8601 UTC); a duplicate
        `asset_class` inside a `targets` array; unknown request fields — all
        rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/ips_default_cadence_and_risk_range
        """
        client = create_active_client(full_name="Def Client", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        validate_error(
            api.create_ips(create_ips_payload(client["id"], bench["id"],
                                              objective_text="X",
                                              risk_tolerance_score=0), ADVISOR),
            ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(
            api.create_ips(create_ips_payload(client["id"], bench["id"],
                                              objective_text="X",
                                              risk_tolerance_score=101), ADVISOR),
            ApiErrorId.ERR_INVALID_REQUEST)

    def test_ips_defaults_applied_on_create(self, api):
        """PRD §3.2: "optionally `review_cadence_months` — the number of months
        between required reviews, between 1 and 24 inclusive, defaulting to 12
        when omitted. The new statement starts in `DRAFT`."
        PRD §3.2: "The statement's `activated_at` — which remains null until
        the statement first reaches `ACTIVE`"

        Design: Corner/entities/ips_default_cadence_and_risk_range
        """
        client = create_active_client(full_name="Def Client", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        payload = create_ips_payload(client["id"], bench["id"], objective_text="X",
                                     risk_tolerance_score=50)
        del payload["review_cadence_months"]
        ips = validate_success(api.create_ips(payload, ADVISOR), 201)
        assert ips["review_cadence_months"] == 12, "cadence defaults to 12"
        assert ips["status"] == "DRAFT"
        assert ips["activated_at"] is None
        assert ips["supersedes_ips_id"] is None


class TestIpsPipeline:
    def test_ips_happy_path_activation_timestamps(self, api):
        """PRD §3.2: "The statement's `activated_at` — which remains null until
        the statement first reaches `ACTIVE` — is set to the current logical
        clock, and `next_review_due` is computed by adding
        `review_cadence_months` calendar months to `activated_at`"
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`"

        Design: Corner/state_machines/ips_happy_path_and_self_referential_supersede
        """
        client = create_active_client(full_name="Sup Client", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips1 = create_active_ips(client, bench, targets=T_60_40, risk=50, cadence=12,
                                 objective_text="V1")
        assert ips1["status"] == "ACTIVE"
        assert_iso_instant_equal(ips1["activated_at"], "2026-08-01T00:00:00Z")
        assert_iso_instant_equal(ips1["next_review_due"], "2027-08-01T00:00:00Z")
        assert ips1["supersedes_ips_id"] is None

    def test_ips_successor_supersedes_and_reverse_filter(self, api):
        """PRD §3.2: "Any prior `ACTIVE` statement of the same client
        transitions to `SUPERSEDED`, and the newly active statement records
        that predecessor in `supersedes_ips_id` (null when there is no
        predecessor)."
        PRD §3.2: "IPS records may be listed with filters on `client_id`,
        `benchmark_id`, `supersedes_ips_id`, and `status`"

        Design: Corner/state_machines/ips_happy_path_and_self_referential_supersede
        """
        client = create_active_client(full_name="Sup Client", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips1 = create_active_ips(client, bench, targets=T_60_40, risk=50, cadence=12,
                                 objective_text="V1")
        ips2 = create_active_ips(client, bench, targets=[
            {"asset_class": "US_EQUITY", "target_pct": 55.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 45.00, "band_pct": 5.00},
        ], risk=55, cadence=6, objective_text="V2")
        assert validate_success(api.get_ips(ips1["id"], ADVISOR))["status"] == (
            "SUPERSEDED")
        assert ips2["status"] == "ACTIVE"
        assert ips2["supersedes_ips_id"] == ips1["id"]
        assert ips2["review_cadence_months"] == 6
        rows, meta = validate_paginated(
            api.list_ips(ADVISOR, params={"supersedes_ips_id": ips1["id"]}))
        assert len(rows) == 1 and rows[0]["id"] == ips2["id"], (
            "reverse reachability of the self-reference")

    def test_ips_compliance_reject_loop_back_to_draft(self, api):
        """PRD §3.2: "compliance rejection — which may carry an optional
        `reason` — returns it `PENDING_COMPLIANCE → DRAFT` for rework."
        PRD §3.2: "Replacement is permitted only while the statement is in
        `DRAFT` — against any other status it is rejected with
        `ERR_IPS_INVALID_STATE`"

        Design: Corner/state_machines/ips_compliance_reject_loop_back_to_draft
        """
        client = create_active_client(full_name="Loop1", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload(T_60_40), ADVISOR))
        get_success_data(api.submit_ips(ips["id"], ADVISOR))
        rejected = validate_success(
            api.compliance_reject_ips(ips["id"], COMPLIANCE, reason="bands too wide"))
        assert rejected["status"] == "DRAFT", "compliance-reject loops back to DRAFT"
        # Targets replaceable again in DRAFT; resubmission works.
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload([
                {"asset_class": "US_EQUITY", "target_pct": 50.00, "band_pct": 2.00},
                {"asset_class": "CASH_EQUIVALENT", "target_pct": 50.00, "band_pct": 2.00},
            ]), ADVISOR))
        resubmitted = validate_success(api.submit_ips(ips["id"], ADVISOR))
        assert resubmitted["status"] == "PENDING_COMPLIANCE"

    def test_ips_client_decline_loop_back_to_draft(self, api):
        """PRD §3.2: "Client decline — also ownership-checked, with an optional
        `reason` — returns `PENDING_CLIENT → DRAFT`."
        PRD §3.2: "the acting client's id must equal the statement's
        `client_id`, else `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/state_machines/ips_client_decline_loop_back_to_draft
        """
        owner = create_active_client(full_name="Owner", risk_tolerance_score=50)
        other = create_active_client(full_name="Other", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(owner["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload(T_60_40), ADVISOR))
        get_success_data(api.submit_ips(ips["id"], ADVISOR))
        get_success_data(api.compliance_approve_ips(ips["id"], COMPLIANCE))
        # Non-owner decline: ownership rejection.
        validate_error(
            api.client_decline_ips(ips["id"], make_client_headers(other["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        declined = validate_success(
            api.client_decline_ips(ips["id"], make_client_headers(owner["id"])))
        assert declined["status"] == "DRAFT", "owner decline returns the IPS to DRAFT"


class TestSubmitValidation:
    def test_allocation_sum_must_equal_exactly_100(self, api):
        """PRD §3.2: "at least one allocation target must exist and the
        `target_pct` values must total exactly 100.00, else
        `ERR_ALLOCATION_SUM_INVALID`"

        Design: Corner/validations/allocation_sum_must_equal_exactly_100
        """
        client = create_active_client(full_name="Sum", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50), ADVISOR))
        # Zero targets.
        validate_error(api.submit_ips(ips["id"], ADVISOR),
                       ApiErrorId.ERR_ALLOCATION_SUM_INVALID)
        # Sum 99.99.
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload([
                {"asset_class": "US_EQUITY", "target_pct": 59.99, "band_pct": 5.00},
                {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
            ]), ADVISOR))
        validate_error(api.submit_ips(ips["id"], ADVISOR),
                       ApiErrorId.ERR_ALLOCATION_SUM_INVALID)
        # Sum exactly 100.00.
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload(T_60_40), ADVISOR))
        submitted = validate_success(api.submit_ips(ips["id"], ADVISOR))
        assert submitted["status"] == "PENDING_COMPLIANCE"

    def test_risk_tolerance_delta_boundary_10_passes_11_fails(self, api):
        """PRD §3.2: "the statement's `risk_tolerance_score` must sit within 10
        points of the owning client's current `risk_tolerance_score` in either
        direction, else `ERR_RISK_TOLERANCE_MISMATCH`"

        Design: Corner/validations/risk_tolerance_delta_boundary_10_passes_11_fails
        """
        client = create_active_client(full_name="Risk", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips_a = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="A",
                               risk_tolerance_score=61), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips_a["id"], allocation_targets_payload(T_CASH), ADVISOR))
        ips_b = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="B",
                               risk_tolerance_score=60), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips_b["id"], allocation_targets_payload(T_CASH), ADVISOR))
        # Delta 11 rejected; the statement stays DRAFT.
        validate_error(api.submit_ips(ips_a["id"], ADVISOR),
                       ApiErrorId.ERR_RISK_TOLERANCE_MISMATCH)
        assert validate_success(api.get_ips(ips_a["id"], ADVISOR))["status"] == "DRAFT"
        # Delta exactly 10 accepted.
        submitted = validate_success(api.submit_ips(ips_b["id"], ADVISOR))
        assert submitted["status"] == "PENDING_COMPLIANCE"

    def test_allocation_targets_bulk_replace_is_atomic(self, api):
        """PRD §3.2: "The replacement is all-or-nothing: every element is
        validated, and the whole set is swapped atomically, with each stored
        row's `ips_id` taken from the path. A duplicate `asset_class` inside
        the array is a request-shape failure (`ERR_INVALID_REQUEST`)."

        Design: Corner/endpoints/allocation_targets_bulk_replace_is_atomic
        """
        client = create_active_client(full_name="Bulk", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload(T_60_40), ADVISOR))
        # Duplicate asset_class in the array: 400 and no partial write.
        validate_error(
            api.replace_allocation_targets(
                ips["id"], allocation_targets_payload([
                    {"asset_class": "US_EQUITY", "target_pct": 50.00, "band_pct": 5.00},
                    {"asset_class": "US_EQUITY", "target_pct": 50.00, "band_pct": 5.00},
                ]), ADVISOR),
            ApiErrorId.ERR_INVALID_REQUEST)
        rows, _ = validate_paginated(api.list_allocation_targets(ips["id"], ADVISOR))
        assert len(rows) == 2, "the previous 60/40 set is fully intact"
        # A valid PUT fully replaces the set.
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload([
                {"asset_class": "FIXED_INCOME", "target_pct": 100.00, "band_pct": 3.00},
            ]), ADVISOR))
        rows, _ = validate_paginated(api.list_allocation_targets(ips["id"], ADVISOR))
        assert len(rows) == 1
        assert rows[0]["asset_class"] == "FIXED_INCOME"
        assert float(rows[0]["target_pct"]) == 100.00
        assert float(rows[0]["band_pct"]) == 3.00
        assert rows[0]["ips_id"] == ips["id"]

    def test_ips_sign_requires_active_benchmark(self, api):
        """PRD §3.2: "the referenced benchmark must still be `ACTIVE`, else
        `ERR_BENCHMARK_NOT_ACTIVE`"

        Design: Corner/state_machines/ips_sign_requires_active_benchmark
        """
        client = create_active_client(full_name="SignG", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload(T_CASH), ADVISOR))
        get_success_data(api.submit_ips(ips["id"], ADVISOR))
        get_success_data(api.compliance_approve_ips(ips["id"], COMPLIANCE))
        # Retire the benchmark while the IPS awaits signature (no ACTIVE IPS
        # references it yet, so retirement succeeds).
        get_success_data(api.retire_benchmark(bench["id"], COMPLIANCE))
        validate_error(
            api.client_sign_ips(ips["id"], make_client_headers(client["id"])),
            ApiErrorId.ERR_BENCHMARK_NOT_ACTIVE)
        assert validate_success(api.get_ips(ips["id"], ADVISOR))["status"] == (
            "PENDING_CLIENT")


class TestReviewSchedule:
    def test_complete_review_advances_due_by_cadence_until_future(self, api):
        """PRD §3.2: "the schedule advances by repeatedly adding
        `review_cadence_months` to `next_review_due` — same month-addition
        clamp — until the result lands strictly in the future; a single
        completion can therefore consume several missed cycles."

        Design: Corner/calculations/complete_review_advances_due_by_cadence_until_future
        """
        client = create_active_client(full_name="Rev", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_CASH, risk=50, cadence=12)
        assert_iso_instant_equal(ips["next_review_due"], "2027-08-01T00:00:00Z")
        set_clock("2027-09-15T00:00:00Z")
        overdue = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert overdue["review_overdue"] is True, "2027-09-15 > 2027-08-01 due"
        reviewed = validate_success(api.complete_review_ips(ips["id"], ADVISOR))
        assert_iso_instant_equal(reviewed["next_review_due"], "2028-08-01T00:00:00Z",
                                 "accumulated from the old due date, strictly past now")
        reread = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert reread["review_overdue"] is False

    def test_month_add_clamps_to_short_month_end(self, api):
        """PRD §3.2: "`next_review_due` is computed by adding
        `review_cadence_months` calendar months to `activated_at`, clamping the
        day-of-month to the target month's last day when necessary — a
        statement signed on 31 January with a one-month cadence comes due on
        28 February."

        Design: Corner/calculations/month_add_clamps_to_short_month_end
        """
        client = create_active_client(full_name="Clamp", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50, review_cadence_months=1),
            ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload(T_CASH), ADVISOR))
        get_success_data(api.submit_ips(ips["id"], ADVISOR))
        get_success_data(api.compliance_approve_ips(ips["id"], COMPLIANCE))
        set_clock("2026-08-31T10:00:00Z")
        signed = validate_success(
            api.client_sign_ips(ips["id"], make_client_headers(client["id"])))
        assert_iso_instant_equal(signed["activated_at"], "2026-08-31T10:00:00Z")
        assert_iso_instant_equal(signed["next_review_due"], "2026-09-30T10:00:00Z",
                                 "day clamped 31 -> 30, time-of-day preserved")

    def test_review_overdue_false_at_exact_due_instant(self, api):
        """PRD §3.2: "On any read, `review_overdue` is true exactly when the
        statement's status is `ACTIVE` and the current logical clock is
        strictly later than `next_review_due`; at the precise instant of
        `next_review_due` the review is not yet overdue."

        Design: Difficulty/boundary_precision_check/review_overdue_strictly_after_due_instant
        """
        client = create_active_client(full_name="Cadence Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40, risk=50, cadence=12)
        assert_iso_instant_equal(ips["next_review_due"], "2027-08-01T00:00:00Z")
        set_clock("2027-08-01T00:00:00Z")
        at_due = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert_iso_instant_equal(at_due["next_review_due"], "2027-08-01T00:00:00Z")
        assert at_due["review_overdue"] is False, "strict >: equality is not overdue"

    def test_review_overdue_true_one_second_after_due(self, api):
        """PRD §3.2: "On any read, `review_overdue` is true exactly when the
        statement's status is `ACTIVE` and the current logical clock is
        strictly later than `next_review_due`; at the precise instant of
        `next_review_due` the review is not yet overdue."

        Design: Difficulty/boundary_precision_check/review_overdue_strictly_after_due_instant
        """
        client = create_active_client(full_name="Cadence Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40, risk=50, cadence=12)
        set_clock("2027-08-01T00:00:01Z")
        past_due = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert past_due["review_overdue"] is True, "one second past the due instant"

    def test_drift_recomputed_against_superseding_ips_targets(self, api):
        """PRD §3.5: "for each allocation target of the active IPS" — the
        assessment reads only the currently `ACTIVE` statement's targets.
        PRD §3.2: "the drift status of every non-`CLOSED` portfolio of the
        client is recomputed, moving each from `UNTRACKED` to `WITHIN_BANDS` or
        `BREACHED` as the assessment finds."

        Design: Corner/calculations/drift_recomputed_against_superseding_ips_targets
        """
        client = create_active_client(full_name="Flip", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips_a = create_active_ips(client, bench, targets=[
            {"asset_class": "US_EQUITY", "target_pct": 65.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 35.00, "band_pct": 5.00},
        ], risk=50, objective_text="A")
        portfolio = get_success_data(api.create_portfolio(
            {"client_id": client["id"], "name": "P", "tax_status": "TAXABLE"}, ADVISOR))
        get_success_data(api.activate_portfolio(portfolio["id"], ADVISOR))
        deposit(portfolio["id"], 360000)
        security = create_security("EQA", "US_EQUITY", 1000)
        add_position(portfolio["id"], security["id"], 640, 640000)
        before = validate_success(api.get_portfolio(portfolio["id"], ADVISOR))
        assert before["drift_status"] == "WITHIN_BANDS", (
            "drift 100bps within the 500bps band of the 65/35 policy")
        # Sign a 55/45 successor; nothing about positions or prices changed.
        ips_b = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="B",
                               risk_tolerance_score=50), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips_b["id"], allocation_targets_payload([
                {"asset_class": "US_EQUITY", "target_pct": 55.00, "band_pct": 5.00},
                {"asset_class": "CASH_EQUIVALENT", "target_pct": 45.00, "band_pct": 5.00},
            ]), ADVISOR))
        get_success_data(api.submit_ips(ips_b["id"], ADVISOR))
        get_success_data(api.compliance_approve_ips(ips_b["id"], COMPLIANCE))
        get_success_data(
            api.client_sign_ips(ips_b["id"], make_client_headers(client["id"])))
        after = validate_success(api.get_portfolio(portfolio["id"], ADVISOR))
        assert after["drift_status"] == "BREACHED", (
            "|6400 - 5500| = 900 > 500 under the new ACTIVE policy")
        assert validate_success(api.get_ips(ips_a["id"], ADVISOR))["status"] == (
            "SUPERSEDED")
