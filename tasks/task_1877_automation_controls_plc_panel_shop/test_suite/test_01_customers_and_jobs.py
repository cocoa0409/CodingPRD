"""Customer intake, job creation rules, job listing, and terminal lockdown."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_bom_line,
    assert_customer,
    assert_job,
    assert_job_ledger_invariant,
    create_change_order_payload,
    create_component_payload,
    create_customer_payload,
    create_job_payload,
    create_panel_payload,
    create_startup_session_payload,
    create_warranty_claim_payload,
    get_success_data,
    make_customer_headers,
    make_qa_headers,
    new_change_order,
    new_component,
    new_customer,
    new_job,
    new_panel,
    set_clock,
    setup_commissioned_job,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerCreation:
    def test_customer_creation_applies_defaults(self, api, pm_headers):
        """PRD §3.1: "A `ProjectManager` registers a new customer by supplying the
        legal `company_name`, the two-letter `site_state_code` (which drives freight
        zone and the dispatch tier for warranty labor), and optionally `credit_hold`
        (defaulting to `false`) and `warranty_labor_tier` (one of `TIER_LOCAL`,
        `TIER_REGIONAL`, `TIER_NATIONAL`, defaulting to `TIER_REGIONAL`)."
        PRD §2.4: "`version` (an integer starting at `1` on creation and incremented
        by exactly `1` on every state transition, side-effect write, or PATCH of that
        entity)".

        Design: Corner/entities/customer_creation_applies_defaults
        """
        created = validate_success(
            api.create_customer(
                create_customer_payload(company_name="Default Co", site_state_code="UT"),
                pm_headers,
            ),
            201,
        )
        customer = validate_success(api.get_customer(created["id"], pm_headers), 200)
        assert_customer(customer)
        assert customer["credit_hold"] is False
        assert customer["warranty_labor_tier"] == "TIER_REGIONAL"
        assert customer["version"] == 1


class TestJobCreation:
    def test_job_creation_rejects_negative_price(self, api, pm_headers):
        """PRD §3.1: "Two fiscal validators run on job creation: a negative
        `quoted_price_cents` or an out-of-range `warranty_months` is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/job_creation_rejects_negative_price
        """
        customer = new_customer(company_name="Neg Co")
        resp = api.create_job(
            create_job_payload(customer["id"], job_number="J-NEG", quoted_price_cents=-1),
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_job_number_unique_per_customer_duplicate_rejected(self, api, pm_headers):
        """PRD §3.1: "the `ProjectManager` opens a job by supplying `customer_id`, a
        human-readable `job_number` that must be unique within that customer".
        PRD §2.9: "16. `ERR_DUPLICATE` — uniqueness violation on `part_number`,
        `content_hash` per panel, `version_tag` per panel, `panel_tag` per job,
        `job_number` per customer, or duplicate component on a panel."

        Design: Corner/entities/job_number_unique_per_customer_duplicate_rejected
        """
        cust_a = new_customer(company_name="Dup A")
        cust_b = new_customer(company_name="Dup B")
        new_job(cust_a["id"], job_number="J-DUP", quoted_price_cents=100)

        # Same job_number under a DIFFERENT customer succeeds.
        other = validate_success(
            api.create_job(
                create_job_payload(cust_b["id"], job_number="J-DUP", quoted_price_cents=100),
                pm_headers,
            ),
            201,
        )
        assert_job(other)
        assert other["job_number"] == "J-DUP"

        # Same customer reusing the same job_number is a uniqueness violation.
        resp = api.create_job(
            create_job_payload(cust_a["id"], job_number="J-DUP", quoted_price_cents=100),
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)

    def test_error_invalid_request_missing_required_field(self, api, pm_headers):
        """PRD §3.1: "the `ProjectManager` opens a job by supplying `customer_id`, a
        human-readable `job_number` that must be unique within that customer, a
        `quoted_price_cents` contract baseline that must be at least zero, and
        optionally `warranty_months`".
        PRD §2.9: "22. `ERR_INVALID_REQUEST` (shape) — missing required fields, wrong
        types, enum violations; and `ERR_INVALID_REQUEST_BODY` for malformed JSON."

        Design: Corner/errors/error_invalid_request_missing_required_field
        """
        customer = new_customer(company_name="Miss Co")
        resp = api.create_job(
            {"customer_id": customer["id"], "job_number": "J-MS1"}, pm_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_error_reference_not_found_on_fk_body(self, api, pm_headers):
        """PRD §2.9: "5. `ERR_REFERENCE_NOT_FOUND` — body-referenced foreign key
        missing (`customer_id`, `component_id`, `panel_id`, `original_line_id`,
        `proposed_component_id`)."

        Design: Corner/errors/error_reference_not_found_on_fk_body
        """
        resp = api.create_job(
            {
                "customer_id": NON_EXISTENT_UUID,
                "job_number": "J-NF1",
                "quoted_price_cents": 100,
            },
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, 404)

    def test_credit_hold_blocks_job_creation_satisfaction_passes(self, api, pm_headers):
        """PRD §3.1: "creating a job for a customer whose `credit_hold` is `true` is
        rejected with `ERR_CREDIT_HOLD` (HTTP 402)".

        Design: Corner/validations/credit_hold_blocks_job_creation_satisfaction_passes
        """
        customer = new_customer(company_name="CH Co")
        job = new_job(customer["id"], job_number="J-CH1", quoted_price_cents=100000)
        assert_job(job)

        get_success_data(api.update_customer(customer["id"], {"credit_hold": True}, pm_headers), 200)
        resp = api.create_job(
            create_job_payload(customer["id"], job_number="J-CH2", quoted_price_cents=100000),
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD, 402)


class TestInitialStates:
    def test_initial_states_on_creation(self, api, pm_headers, de_headers):
        """PRD §3.1: "A job begins life in `OPEN`."
        PRD §3.2: "The new panel starts in `DESIGN`."
        PRD §3.8: "The server assigns a monotonic `co_number` within the job (the
        first is `1`, the next `2`, and so on — ordering is by `co_number`, never by
        `id`), records the acting `ProjectManager`'s id as `requested_by_id`,
        computes `computed_delta_cents` via the pricing rule below, and starts the
        order in `PROPOSED`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        customer = new_customer(company_name="Init Co")
        job = validate_success(
            api.create_job(
                create_job_payload(customer["id"], job_number="J-IN1", quoted_price_cents=100000),
                pm_headers,
            ),
            201,
        )
        assert job["status"] == "OPEN", f"new job must start OPEN, got {job['status']}"

        panel = validate_success(
            api.create_panel(
                job["id"],
                create_panel_payload(panel_tag="P-IN1", design_engineer_id="de-in"),
                de_headers,
            ),
            201,
        )
        assert panel["status"] == "DESIGN", f"new panel must start DESIGN, got {panel['status']}"

        order = validate_success(
            api.create_change_order(
                job["id"],
                create_change_order_payload(description="init probe", price_delta_cents=1000),
                pm_headers,
            ),
            201,
        )
        assert order["status"] == "PROPOSED", (
            f"new change order must start PROPOSED, got {order['status']}"
        )


class TestTerminalLockdown:
    def test_terminal_job_close_rejects_further_transitions(self, api, pm_headers):
        """PRD §3.1: "A mid-flight job can be paused: the `ProjectManager` may place
        a job in `ON_HOLD` from any of `DESIGN`, `PROCUREMENT`, `BUILD`, or `TEST`."
        PRD §2.9: "6. `ERR_INVALID_STATE` — target entity not in a state from which
        the requested transition is defined."

        Design: Corner/state_machines/terminal_job_close_rejects_further_transitions
        """
        ctx = setup_commissioned_job(
            company_name="Term Co",
            job_number="J-TM1",
            warranty_months=12,
            panel_tag="P-TM1",
            design_engineer_id="de-tm",
            qa_user_id="qa-tm",
            technician_id="tt-tm",
            engineer_id="fe-tm",
            labor_hours=4,
        )
        job_id = ctx["job"]["id"]
        closed = validate_success(api.close_job(job_id, pm_headers), 200)
        assert closed["status"] == "CLOSED"

        resp = api.hold_job(job_id, pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestCustomerRbac:
    def test_customer_cannot_create_jobs_or_components(self, api, pm_headers):
        """PRD §2.1: "A request whose role is authenticated but not listed in the
        target endpoint's Authorized Role(s) column is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4 endpoint table: POST `/panel-shop/jobs` — "Create a panel-build job
        for a customer." — Authorized Role(s): ProjectManager; POST
        `/panel-shop/components` — "Register a catalog component." — Authorized
        Role(s): QAManager.

        Design: Corner/rbac/customer_cannot_create_jobs_or_components
        """
        customer = new_customer(company_name="RB Co")
        cust_headers = make_customer_headers(customer["id"])

        resp_jobs = api.create_job(
            create_job_payload(customer["id"], job_number="J-RB1", quoted_price_cents=100),
            cust_headers,
        )
        validate_error(resp_jobs, ApiErrorId.ERR_UNAUTHORIZED, 403)

        resp_components = api.create_component(
            create_component_payload(
                part_number="RB-1", component_class="CONTACTOR", unit_cost_cents=100,
                lead_time_days=1, sccr_ka=10, heat_dissipation_w=1,
            ),
            cust_headers,
        )
        validate_error(resp_components, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestJobListing:
    def test_jobs_list_pagination_envelope(self, api, pm_headers):
        """PRD §2.3: "The `meta` block of a list response includes `limit`, `offset`,
        `total_count`, and `has_more`, where `total_count` is the total number of
        matching records before pagination and `has_more` is true exactly when
        `offset + limit < total_count`."

        Design: Corner/endpoints/jobs_list_pagination_envelope
        """
        customer = new_customer(company_name="Page Co")
        for n in ("J-PG1", "J-PG2", "J-PG3"):
            new_job(customer["id"], job_number=n, quoted_price_cents=100)

        resp = api.list_jobs(
            pm_headers, params={"customer_id": customer["id"], "limit": 2, "offset": 1}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"expected 2 rows on page, got {len(data)}"
        assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
        assert meta["has_more"] is False, "offset 1 + limit 2 covers all 3 rows"

    def test_jobs_list_filter_by_status(self, api, pm_headers):
        """PRD §4: GET /panel-shop/jobs — "List jobs with optional `customer_id` and
        `status` filters."
        PRD §3.1: "A mid-flight job can be paused: the `ProjectManager` may place a
        job in `ON_HOLD` from any of `DESIGN`, `PROCUREMENT`, `BUILD`, or `TEST`."

        Design: Corner/endpoints/jobs_list_filter_by_status
        """
        customer = new_customer(company_name="Filt Co")
        job_a = new_job(customer["id"], job_number="J-FL1", quoted_price_cents=100)
        job_b = new_job(customer["id"], job_number="J-FL2", quoted_price_cents=100)
        get_success_data(api.advance_job(job_a["id"], pm_headers), 200)
        get_success_data(api.hold_job(job_a["id"], pm_headers), 200)

        data, meta = validate_paginated(
            api.list_jobs(
                pm_headers, params={"customer_id": customer["id"], "status": "ON_HOLD"}
            )
        )
        ids = [row["id"] for row in data]
        assert ids == [job_a["id"]], f"only the held job may match, got {ids}"
        assert job_b["id"] not in ids

    def test_fk_reverse_reachability_all_children(self, api, pm_headers, de_headers):
        """PRD §2.3: "All list endpoints accept optional `limit` and `offset` query
        parameters."
        PRD §2.3: "The `meta` block of a list response includes `limit`, `offset`,
        `total_count`, and `has_more`, where `total_count` is the total number of
        matching records before pagination and `has_more` is true exactly when
        `offset + limit < total_count`."
        PRD §4 declares the reverse-reachability reads exercised here: "List jobs of
        a customer.", "List panels of a job.", "List BOM lines of a panel.", "Fetch
        the as-built package of a panel (1:1, returns array of 0–1).", "List
        substitution requests of a panel.", "List test points of a panel.", "List
        test sessions of a panel.", "List program versions of a panel.", "List
        startup sessions of a panel.", "List change orders of a job.", "List warranty
        claims of a job."

        Design: Corner/endpoints/fk_reverse_reachability_all_children
        """
        customer = new_customer(company_name="FK Co")
        job = new_job(customer["id"], job_number="J-FK1", quoted_price_cents=100)
        panel = new_panel(job["id"], design_engineer_id="de-fk", panel_tag="P-FK1")
        component = new_component(
            part_number="FK-C1", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=10, heat_dissipation_w=20,
        )
        add_bom_line(panel["id"], component["id"])

        jobs, _ = validate_paginated(api.list_customer_jobs(customer["id"], pm_headers))
        assert [j["id"] for j in jobs] == [job["id"]]

        panels, _ = validate_paginated(api.list_job_panels(job["id"], pm_headers))
        assert [p["id"] for p in panels] == [panel["id"]]

        lines, _ = validate_paginated(api.list_panel_components(panel["id"], de_headers))
        assert len(lines) == 1

        packages, _ = validate_paginated(api.list_panel_asbuilt_packages(panel["id"], de_headers))
        assert len(packages) == 1

        # Child collections with no rows yet must return empty arrays, not errors.
        empty_reads = [
            api.list_panel_substitution_requests(panel["id"], de_headers),
            api.list_test_points(panel["id"], de_headers),
            api.list_panel_test_sessions(panel["id"], pm_headers),
            api.list_panel_program_versions(panel["id"], pm_headers),
            api.list_panel_startup_sessions(panel["id"], pm_headers),
            api.list_job_change_orders(job["id"], pm_headers),
            api.list_job_warranty_claims(job["id"], pm_headers),
        ]
        for resp in empty_reads:
            data, _meta = validate_paginated(resp)
            assert data == [], f"expected empty array, got {data}"
