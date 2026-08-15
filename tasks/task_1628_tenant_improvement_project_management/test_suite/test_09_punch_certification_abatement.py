"""Punch list handshake, occupancy certification, and rent abatement."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    create_active_lease,
    create_approved_change_order,
    create_lease_space_record,
    create_property_record,
    create_punch_item_record,
    create_qualified_contractor,
    create_tenant_record,
    drive_lease_to_pre_construction,
    drive_project_to_construction,
    get_success_data,
    make_contractor_rep_headers,
    make_tenant_rep_headers,
    parse_instant,
    resolve_punch_item_flow,
    set_logical_clock,
    setup_project_in_construction,
    setup_project_in_punch,
    validate_error,
    validate_success,
)


class TestPunchItemCycle:
    def test_punch_item_reopen_cycle(self, api, landlord_pm_headers, building_engineer_headers):
        """PRD 3.7: "Verification belongs to the `BuildingEngineer` alone and
        requires the project to be in `PUNCH`: a passed inspection moves
        `RESOLVED` → `VERIFIED`, the item's terminal state, while a failed one
        reopens the item (`RESOLVED` → `OPEN`), sending it back around the
        `IN_PROGRESS` → `RESOLVED` loop again." PRD 2.4: "`version` is an
        integer that increments by exactly one on every mutation of the
        resource".

        Design: Difficulty/non_linear_state_machine/punch_item_reopen_cycle
        """
        sc = setup_project_in_punch(with_milestone=True)
        ctr = sc["contractor"]["id"]
        item = create_punch_item_record(
            sc["project"]["id"], sc["engagement"]["id"], description="Paint touch-up"
        )
        created_version = item["version"]

        item = resolve_punch_item_flow(item["id"], ctr)
        assert item["status"] == "RESOLVED"

        # Failed verification: the engineer reopens the item.
        item = get_success_data(api.reopen_punch_item(item["id"], building_engineer_headers))
        assert item["status"] == "OPEN", "a failed verification returns the item to OPEN"

        # The item traverses the loop again and passes the second time.
        item = get_success_data(
            api.start_punch_item(item["id"], make_contractor_rep_headers(ctr))
        )
        item = get_success_data(
            api.resolve_punch_item(item["id"], make_contractor_rep_headers(ctr))
        )
        item = get_success_data(api.verify_punch_item(item["id"], building_engineer_headers))
        assert item["status"] == "VERIFIED"
        assert item["version"] == created_version + 6, (
            f"six transitions after creation must advance the version by exactly 6, "
            f"got {item['version']} from {created_version}"
        )

    def test_verify_requires_resolved_state(self, api, landlord_pm_headers, building_engineer_headers):
        """PRD 3.7: "a passed inspection moves `RESOLVED` → `VERIFIED`, the
        item's terminal state". PRD 2.7: "The targeted entity must be in a
        state from which the requested transition exists — including the
        parent-phase gates named throughout §3 — and terminal states reject
        every transition, else `ERR_INVALID_STATE` (409)." PRD 3.7: "The
        responsible firm's `ContractorRep` starts work (`OPEN` → `IN_PROGRESS`)
        — permitted only while the assigned engagement is `ACTIVE` — and later
        marks the fix done (`IN_PROGRESS` → `RESOLVED`)."

        Design: Difficulty/non_linear_state_machine/punch_item_reopen_cycle
        """
        sc = setup_project_in_punch()
        ctr = sc["contractor"]["id"]
        item = create_punch_item_record(sc["project"]["id"], sc["engagement"]["id"])
        assert item["status"] == "OPEN"

        # verify is a RESOLVED -> VERIFIED transition; an OPEN item rejects it.
        resp = api.verify_punch_item(item["id"], building_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # The straight path OPEN -> IN_PROGRESS -> RESOLVED -> VERIFIED works.
        item = resolve_punch_item_flow(item["id"], ctr)
        item = get_success_data(api.verify_punch_item(item["id"], building_engineer_headers))
        assert item["status"] == "VERIFIED"


class TestCertificateCascade:
    def _project_with_invoiced_overage(self, api, landlord_pm_headers, lease_overrides=None):
        """CONSTRUCTION project with CO1 (share 0) and CO2 (share 2100000)
        approved and a DRAFT invoice snapshotting the share."""
        sc = setup_project_in_construction(lease_overrides=lease_overrides)
        set_logical_clock("2026-08-15T00:00:00Z")
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])
        create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "x", "amount_cents": 6_000_000}], approver_id="approver-2",
        )
        co2 = create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "y", "amount_cents": 5_000_000}], approver_id="approver-2",
        )
        assert co2["tenant_overage_share_cents"] == 2_100_000
        invoice = get_success_data(
            api.create_overage_invoice(sc["project"]["id"], landlord_pm_headers)
        )
        assert invoice["status"] == "DRAFT"
        assert invoice["line_total_cents"] == 2_100_000
        return sc, invoice

    def test_occupancy_certificate_three_hop_cascade(self, api, landlord_pm_headers):
        """PRD 3.7: "On issuance the project stamps its
        `substantial_completion_date` from `issued_on` alongside the
        certificate reference, the suite returns `UNDER_CONSTRUCTION` →
        `LEASED`, and every `DRAFT` overage invoice of the project is issued
        automatically — its `invoice_number` unchanged and its due date
        computed from the certificate's `issued_on` per §3.8." PRD 3.8:
        "invoices issued through the certificate cascade of §3.7 instead take
        their effective issue date from the certificate's `issued_on`, so their
        `due_date` falls thirty days after substantial completion." PRD 3.7:
        "When responsibility is `LANDLORD`, the lease's
        `rent_abatement_credit_cents` becomes the delay count times the daily
        rent and its `actual_rent_commencement_date` becomes
        `substantial_completion_date`."

        Design: Difficulty/transitive_cascade/occupancy_certificate_three_hop_cascade
        """
        sc, invoice = self._project_with_invoiced_overage(
            api,
            landlord_pm_headers,
            lease_overrides={
                "base_rent_annual_cents": 36_500_000,
                "scheduled_rent_commencement_date": "2026-09-01T00:00:00Z",
                "abatement_basis": "CALENDAR",
            },
        )
        set_logical_clock("2026-09-04T00:00:00Z")
        get_success_data(api.begin_punch(sc["project"]["id"], landlord_pm_headers))

        project = validate_success(
            api.issue_occupancy_certificate(
                sc["project"]["id"],
                {
                    "occupancy_certificate_ref": "CO-H-1",
                    "issued_on": "2026-09-11T00:00:00Z",
                    "delay_responsibility": "LANDLORD",
                },
                landlord_pm_headers,
            ),
            200,
        )
        assert project["status"] == "CLOSEOUT", "hop 1: PUNCH -> CLOSEOUT"
        assert parse_instant(project["substantial_completion_date"]) == parse_instant(
            "2026-09-11T00:00:00Z"
        )

        lease = get_success_data(api.get_lease(sc["lease"]["id"], landlord_pm_headers))
        # hop 2: 10 calendar delay days (2026-09-02..2026-09-11) x 100000 cents.
        assert lease["rent_abatement_credit_cents"] == 1_000_000, (
            f"CALENDAR delay credit must be 10 x 100000, got {lease['rent_abatement_credit_cents']}"
        )
        assert parse_instant(lease["actual_rent_commencement_date"]) == parse_instant(
            "2026-09-11T00:00:00Z"
        )

        invoice_after = get_success_data(api.get_overage_invoice(invoice["id"], landlord_pm_headers))
        assert invoice_after["status"] == "ISSUED", "hop 3: the DRAFT invoice is auto-issued"
        assert invoice_after["line_total_cents"] == 2_100_000
        assert parse_instant(invoice_after["due_date"]) == parse_instant("2026-10-11T00:00:00Z"), (
            "due_date falls thirty days after the certificate's issued_on"
        )

        space = get_success_data(api.get_lease_space(sc["space"]["id"], landlord_pm_headers))
        assert space["status"] == "LEASED", "the suite is released from UNDER_CONSTRUCTION"

    def test_manual_invoice_issue_dates_from_logical_clock(self, api, landlord_pm_headers):
        """PRD 3.8: "An invoice may be issued manually while the project is in
        `CONSTRUCTION`, `PUNCH`, or `CLOSEOUT`, moving `DRAFT` → `ISSUED` and
        setting `due_date` to thirty days after the logical clock's current
        date".

        Design: Difficulty/transitive_cascade/occupancy_certificate_three_hop_cascade
        """
        sc, invoice = self._project_with_invoiced_overage(api, landlord_pm_headers)
        set_logical_clock("2026-08-15T00:00:00Z")

        issued = validate_success(api.issue_invoice(invoice["id"], landlord_pm_headers), 200)
        assert issued["status"] == "ISSUED"
        assert parse_instant(issued["due_date"]) == parse_instant("2026-09-14T00:00:00Z"), (
            "manual issue sets due_date thirty days after the clock date 2026-08-15"
        )


class TestRentAbatementVariants:
    def _two_abatement_projects_in_punch(self, api):
        """One property (capacity 5), two leases — CALENDAR and BUSINESS,
        rent 36500000/yr, scheduled RCD 2026-09-01 — each with a project
        driven to PUNCH."""
        prop = create_property_record(max_concurrent_construction_projects=5)
        space_a = create_lease_space_record(prop["id"], suite_number="600", floor=6)
        space_b = create_lease_space_record(prop["id"], suite_number="700", floor=7)
        tenant_a = create_tenant_record()
        tenant_b = create_tenant_record()
        lease_terms = {
            "base_rent_annual_cents": 36_500_000,
            "scheduled_rent_commencement_date": "2026-09-01T00:00:00Z",
            "lease_term_months": 60,
        }
        lease_a = create_active_lease(
            space_a["id"], tenant_a["id"], abatement_basis="CALENDAR", **lease_terms
        )
        lease_b = create_active_lease(
            space_b["id"], tenant_b["id"], abatement_basis="BUSINESS", **lease_terms
        )
        contractor = create_qualified_contractor()
        projects = {}
        for key, lease, tenant in (("a", lease_a, tenant_a), ("b", lease_b, tenant_b)):
            pre = drive_lease_to_pre_construction(lease, tenant)
            driven = drive_project_to_construction(pre["project"], contractor)
            projects[key] = {
                "lease": lease,
                "tenant": tenant,
                "project": driven["project"],
                "engagement": driven["engagement"],
            }
        set_logical_clock(TEST_DEFAULTS["CLOCK_CONSTRUCTION_END"])
        return projects

    def test_rent_abatement_calendar_vs_business_on_lease(self, api, landlord_pm_headers):
        """PRD 3.7: "The daily rent is the lease's `base_rent_annual_cents`
        divided by 365, rounded half up to a whole cent. The delay period opens
        the day after `scheduled_rent_commencement_date` and closes on
        `substantial_completion_date`, inclusive of the closing date". PRD 3.7:
        "Under the `CALENDAR` basis the delay count is every date in that
        period; under the `BUSINESS` basis only dates falling on a Monday
        through Friday count, so a period spanning a weekend yields a strictly
        smaller count." PRD 3.7: "When responsibility is `LANDLORD`, the
        lease's `rent_abatement_credit_cents` becomes the delay count times the
        daily rent and its `actual_rent_commencement_date` becomes
        `substantial_completion_date`."

        Design: Difficulty/dual_variant_calc/rent_abatement_calendar_vs_business_on_lease
        """
        projects = self._two_abatement_projects_in_punch(api)
        for key in ("a", "b"):
            get_success_data(api.begin_punch(projects[key]["project"]["id"], landlord_pm_headers))

        for key in ("a", "b"):
            validate_success(
                api.issue_occupancy_certificate(
                    projects[key]["project"]["id"],
                    {
                        "occupancy_certificate_ref": f"CO-{key.upper()}-1",
                        "issued_on": "2026-09-11T00:00:00Z",
                        "delay_responsibility": "LANDLORD",
                    },
                    landlord_pm_headers,
                ),
                200,
            )
            projects[key]["project"] = get_success_data(
                api.get_project(projects[key]["project"]["id"], landlord_pm_headers)
            )
            assert projects[key]["project"]["status"] == "CLOSEOUT"

        # Delay period (2026-09-01, 2026-09-11]: 10 calendar days, of which
        # 2026-09-05/06 are the weekend -> 8 business days. Daily rent 100000.
        lease_a = get_success_data(api.get_lease(projects["a"]["lease"]["id"], landlord_pm_headers))
        lease_b = get_success_data(api.get_lease(projects["b"]["lease"]["id"], landlord_pm_headers))
        assert lease_a["rent_abatement_credit_cents"] == 1_000_000, (
            f"CALENDAR: 10 days x 100000, got {lease_a['rent_abatement_credit_cents']}"
        )
        assert lease_b["rent_abatement_credit_cents"] == 800_000, (
            f"BUSINESS: 8 days x 100000 (weekend excluded), got "
            f"{lease_b['rent_abatement_credit_cents']}"
        )
        for lease in (lease_a, lease_b):
            assert parse_instant(lease["actual_rent_commencement_date"]) == parse_instant(
                "2026-09-11T00:00:00Z"
            )

    def test_rent_abatement_business_basis_short_delay(self, api, landlord_pm_headers):
        """PRD 3.7: "under the `BUSINESS` basis only dates falling on a Monday
        through Friday count, so a period spanning a weekend yields a strictly
        smaller count." PRD 3.7: "When responsibility is `LANDLORD`, the
        lease's `rent_abatement_credit_cents` becomes the delay count times the
        daily rent and its `actual_rent_commencement_date` becomes
        `substantial_completion_date`."

        Design: Difficulty/dual_variant_calc/rent_abatement_calendar_vs_business_on_lease
        """
        projects = self._two_abatement_projects_in_punch(api)
        get_success_data(api.begin_punch(projects["b"]["project"]["id"], landlord_pm_headers))
        validate_success(
            api.issue_occupancy_certificate(
                projects["b"]["project"]["id"],
                {
                    "occupancy_certificate_ref": "CO-B-2",
                    "issued_on": "2026-09-07T00:00:00Z",
                    "delay_responsibility": "LANDLORD",
                },
                landlord_pm_headers,
            ),
            200,
        )
        lease_b = get_success_data(api.get_lease(projects["b"]["lease"]["id"], landlord_pm_headers))
        # (2026-09-01, 2026-09-07]: Sep 2,3,4,5,6,7 -> business days 2,3,4,7 = 4.
        assert lease_b["rent_abatement_credit_cents"] == 400_000, (
            f"BUSINESS over a weekend-spanning week counts 4 days, got "
            f"{lease_b['rent_abatement_credit_cents']}"
        )
        assert parse_instant(lease_b["actual_rent_commencement_date"]) == parse_instant(
            "2026-09-07T00:00:00Z"
        )

    def test_rent_abatement_tenant_responsible_yields_zero_credit(self, api, landlord_pm_headers):
        """PRD 3.7: "When responsibility is `TENANT` — the tenant caused the
        delay — the credit is zero and rent still commences on
        `scheduled_rent_commencement_date`".

        Design: Corner/calculations/rent_abatement_tenant_responsible_yields_zero_credit
        """
        sc = setup_project_in_punch(
            lease_overrides={
                "base_rent_annual_cents": 36_500_000,
                "scheduled_rent_commencement_date": "2026-09-01T00:00:00Z",
                "abatement_basis": "CALENDAR",
            }
        )
        validate_success(
            api.issue_occupancy_certificate(
                sc["project"]["id"],
                {
                    "occupancy_certificate_ref": "CO-X",
                    "issued_on": "2026-09-11T00:00:00Z",
                    "delay_responsibility": "TENANT",
                },
                landlord_pm_headers,
            ),
            200,
        )
        lease = get_success_data(api.get_lease(sc["lease"]["id"], landlord_pm_headers))
        assert lease["rent_abatement_credit_cents"] == 0, "the tenant bears its own delay"
        assert parse_instant(lease["actual_rent_commencement_date"]) == parse_instant(
            "2026-09-01T00:00:00Z"
        ), "rent still commences on the scheduled date"

    def test_rent_abatement_on_time_completion_keeps_scheduled_rcd(self, api, landlord_pm_headers):
        """PRD 3.7: "when substantial completion falls on or before the
        scheduled date there is no delay at all and the delay count is zero".
        PRD 3.7: "the same zero-credit, on-schedule outcome applies when
        responsibility is `NONE`, the on-time delivery case."

        Design: Corner/calculations/rent_abatement_on_time_completion_keeps_scheduled_rcd
        """
        sc = setup_project_in_punch(
            construction_end_date="2026-08-25T00:00:00Z",
            lease_overrides={
                "base_rent_annual_cents": 36_500_000,
                "scheduled_rent_commencement_date": "2026-09-01T00:00:00Z",
                "abatement_basis": "CALENDAR",
            },
        )
        validate_success(
            api.issue_occupancy_certificate(
                sc["project"]["id"],
                {
                    "occupancy_certificate_ref": "CO-Y",
                    "issued_on": "2026-08-28T00:00:00Z",
                    "delay_responsibility": "NONE",
                },
                landlord_pm_headers,
            ),
            200,
        )
        lease = get_success_data(api.get_lease(sc["lease"]["id"], landlord_pm_headers))
        assert lease["rent_abatement_credit_cents"] == 0
        assert parse_instant(lease["actual_rent_commencement_date"]) == parse_instant(
            "2026-09-01T00:00:00Z"
        )


class TestPunchPhaseGates:
    def test_begin_punch_before_window_end_rejected(self, api, landlord_pm_headers):
        """PRD 3.7: "The landlord opens the punch phase (`CONSTRUCTION` →
        `PUNCH`) only once the current logical clock has reached or passed the
        project's `construction_end_date` — earlier attempts fail with
        `ERR_CONSTRUCTION_WINDOW_NOT_ENDED` (HTTP 422)".

        Design: Corner/validations/begin_punch_before_window_end_rejected
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-20T00:00:00Z")  # window ends 2026-09-04
        resp = api.begin_punch(sc["project"]["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_CONSTRUCTION_WINDOW_NOT_ENDED)
        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["status"] == "CONSTRUCTION"

    def test_certificate_blocked_by_life_safety_then_generic_open(
        self, api, landlord_pm_headers, building_engineer_headers
    ):
        """PRD 2.7: "Occupancy certificate issuance checks life-safety punch
        items first (`ERR_LIFE_SAFETY_ITEM_OPEN`), then the all-items check
        (`ERR_PUNCH_ITEMS_OPEN`) — so an open `LIFE_SAFETY` item always
        surfaces as the life-safety error rather than the generic one." PRD
        3.7: "any `LIFE_SAFETY` item not yet `VERIFIED` blocks issuance with
        `ERR_LIFE_SAFETY_ITEM_OPEN` (HTTP 422), and once those are clear, any
        remaining item of any severity not `VERIFIED` blocks it with
        `ERR_PUNCH_ITEMS_OPEN` (HTTP 422)."

        Design: Corner/validations/certificate_blocked_by_life_safety_then_generic_open
        """
        sc = setup_project_in_punch()
        ctr = sc["contractor"]["id"]
        life = create_punch_item_record(
            sc["project"]["id"], sc["engagement"]["id"],
            description="Exit sign not illuminated", location="Corridor",
            severity="LIFE_SAFETY", as_engineer=True,
        )
        create_punch_item_record(
            sc["project"]["id"], sc["engagement"]["id"],
            description="Paint scuff", location="Lobby",
            severity="COSMETIC", as_engineer=True,
        )
        payload = {
            "occupancy_certificate_ref": "CO-Z",
            "issued_on": "2026-09-05T00:00:00Z",
            "delay_responsibility": "NONE",
        }

        resp = api.issue_occupancy_certificate(sc["project"]["id"], payload, landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_LIFE_SAFETY_ITEM_OPEN)

        # Clear only the life-safety item; the cosmetic one stays OPEN.
        life = resolve_punch_item_flow(life["id"], ctr)
        get_success_data(api.verify_punch_item(life["id"], building_engineer_headers))

        resp = api.issue_occupancy_certificate(sc["project"]["id"], payload, landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_PUNCH_ITEMS_OPEN)

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["status"] == "PUNCH"

    def test_contractor_cannot_verify_own_punch_item_unauthorized(
        self, api, landlord_pm_headers
    ):
        """PRD 3.7: "Verification belongs to the `BuildingEngineer` alone and
        requires the project to be in `PUNCH`". PRD 2.1: "A request whose role
        is not on the endpoint's authorized list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/contractor_cannot_verify_own_punch_item_unauthorized
        """
        sc = setup_project_in_punch()
        ctr = sc["contractor"]["id"]
        item = create_punch_item_record(
            sc["project"]["id"], sc["engagement"]["id"],
            description="Paint", location="Lobby", severity="COSMETIC",
        )
        item = resolve_punch_item_flow(item["id"], ctr)
        assert item["status"] == "RESOLVED"

        resp = api.verify_punch_item(item["id"], make_contractor_rep_headers(ctr))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_punch_item(item["id"], landlord_pm_headers))
        assert after["status"] == "RESOLVED"
