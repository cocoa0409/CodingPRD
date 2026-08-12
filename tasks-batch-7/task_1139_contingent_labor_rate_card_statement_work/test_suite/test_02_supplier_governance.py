"""Supplier onboarding validation, tier scoring, listing pagination, and the
audit-driven violation counter lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_supplier,
    create_active_rate_card,
    create_assignment_payload,
    create_engagement_in_open,
    create_supplier_payload,
    create_worker_payload,
    get_success_data,
    get_supplier,
    make_supplier_coordinator_headers,
    onboard_supplier,
    pick_offer_for_supplier,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def test_supplier_missing_required_tier_returns_400(api):
    """PRD: "Suppliers enter the program through a `ProgramAdmin` onboarding
    call carrying the legal `name`, a `supplier_code` (a short code unique
    across suppliers, used as the deterministic final tie-break in
    distribution ranking), and an initial `tier` of `PREFERRED`, `APPROVED`
    or `PROBATION`."
    PRD: "Violations yield `ERR_VALIDATION` (400) on all creation and action
    endpoints."

    Design: Corner/entities/supplier_missing_required_tier_returns_400
    """
    resp = api.create_supplier({"name": "No Tier Co", "supplier_code": "SUP-NT"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(api.list_suppliers(ADMIN))
    assert meta["total_count"] == 0, "rejected create must persist no supplier"


def test_invalid_enum_tier_rejected(api):
    """PRD: "required fields present, types valid, enum values within their
    declared sets, dates in `YYYY-MM-DD` form, hour values carried to at most
    two decimal places."
    PRD: "an initial `tier` of `PREFERRED`, `APPROVED` or `PROBATION`."

    Design: Corner/entities/invalid_enum_tier_rejected
    """
    resp = api.create_supplier(
        create_supplier_payload(name="Gold Co", supplier_code="SUP-GOLD", tier="GOLD"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_tier_evaluation_insufficient_data_keeps_tier(api):
    """PRD: "The scoring rule has an explicit insufficient-data branch: a
    supplier with fewer than 3 completed assignments is not scored at all —
    `tier_score` stays null and the existing `tier` is left unchanged."

    Design: Corner/calculations/tier_evaluation_insufficient_data_keeps_tier
    """
    supplier = onboard_supplier(tier="PREFERRED", name="Quiet Co", supplier_code="SUP-Q")
    evaluated = validate_success(api.evaluate_supplier_tier(supplier["id"], ADMIN))
    assert evaluated["tier"] == "PREFERRED", "insufficient data leaves tier unchanged"
    assert evaluated["tier_score"] is None, "insufficient data leaves tier_score null"
    assert evaluated["completed_assignments_count"] == 0


def _complete_four_assignments_for_single_supplier(api):
    """Drive one supplier to offers_made 4, offers_filled 4, completed 4.

    Returns (rate_card, supplier, assignment_ids).
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    rate_card = create_active_rate_card(
        effective_from="2026-01-01", effective_to="2026-06-01"
    )
    supplier = onboard_supplier(tier="PREFERRED", name="Solo Staffing",
                                supplier_code="SUP-S1")
    coordinator = make_supplier_coordinator_headers(supplier["id"])
    assignment_ids = []
    for i in range(1, 5):
        engagement = create_engagement_in_open(
            title=f"E{i}", duration_months=3, budget_cents=2_000_000
        )
        offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
        offer = pick_offer_for_supplier(offers, supplier["id"])
        get_success_data(
            api.respond_to_offer(offer["id"], {"action": "ACCEPT"}, coordinator)
        )
        worker = get_success_data(
            api.create_worker(
                create_worker_payload(
                    supplier["id"], full_name=f"Worker {i}",
                    email=f"w{i}@example.com",
                ),
                coordinator,
            )
        )
        assignment = get_success_data(
            api.create_assignment(
                create_assignment_payload(
                    worker["id"], engagement["id"], offer["id"], rate_card["id"],
                    bill_rate_cents=9500, pay_rate_cents=8000,
                    start_date="2026-05-01", end_date="2026-06-30",
                ),
                ADMIN,
            )
        )
        get_success_data(api.activate_assignment(assignment["id"], ADMIN))
        get_success_data(api.complete_assignment(assignment["id"], ADMIN))
        assignment_ids.append(assignment["id"])
    return rate_card, supplier, assignment_ids


class TestSupplierTierScoreWeighted:
    def test_audit_markup_finding_feeds_violation_counter(self, api):
        """PRD: "`MARKUP_EXCEEDED` (severity `HIGH`) is raised when the markup
        transparency check of §3.5 fails against the governing card — again
        comparing against the tighter of the card cap and the supplier's tier
        cap."
        PRD: "Each finding derives its `supplier_id` from the subject (the
        assignment's supplier, or the timesheet's assignment's supplier),
        carries a machine-generated `details` explanation, starts in `OPEN`
        status, and increments the supplier's `open_violation_count` by one."

        Design: Difficulty/combinatorial_formula/supplier_tier_score_weighted_with_branch
        """
        rate_card, supplier, assignment_ids = (
            _complete_four_assignments_for_single_supplier(api)
        )
        source = get_success_data(api.get_rate_card(rate_card["id"], ADMIN))
        revision = get_success_data(
            api.create_rate_card_revision(
                rate_card["id"],
                {
                    "expected_rate_card_version": source["version"],
                    "max_markup_pct": 0.10,
                    "effective_from": "2026-06-01",
                    "effective_to": "2027-01-01",
                },
                ADMIN,
            )
        )
        get_success_data(api.activate_rate_card(revision["id"], ADMIN))
        set_logical_clock("2026-06-15T00:00:00Z")

        findings = validate_success(
            api.run_compliance_audit({"assignment_id": assignment_ids[0]}, ADMIN),
            expected_status=201,
        )
        assert len(findings) == 1, (
            "markup 0.1875 > min(0.10, 0.25) fails, but bill 9500 <= ceiling 12000"
        )
        assert findings[0]["finding"] == "MARKUP_EXCEEDED"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["status"] == "OPEN"
        assert findings[0]["supplier_id"] == supplier["id"]
        after = get_supplier(supplier["id"])
        assert after["open_violation_count"] == 1

    def test_weighted_score_lands_on_approved_band_boundary(self, api):
        """PRD: "The score is 100 times the weighted blend — 0.4 times the
        fill component plus 0.4 times the compliance component plus 0.2 times
        the acceptance component — rounded half up to a whole integer."
        PRD: "the acceptance component is `milestones_accepted_count` divided
        by `milestones_delivered_count`, capped at 1.0 with the denominator
        treated as at least 1 — which pins the empty-pool case: a supplier
        that has delivered no milestones scores exactly 0 on the acceptance
        component, it does not skip the component."
        PRD: "The tier band boundaries are inclusive at the bottom: a score of
        85 or better earns `PREFERRED`, 70 through 84 earns `APPROVED`, and
        below 70 drops to `PROBATION` — so exactly 85 is `PREFERRED` and
        exactly 70 is `APPROVED`."

        Design: Difficulty/combinatorial_formula/supplier_tier_score_weighted_with_branch
        """
        rate_card, supplier, assignment_ids = (
            _complete_four_assignments_for_single_supplier(api)
        )
        source = get_success_data(api.get_rate_card(rate_card["id"], ADMIN))
        revision = get_success_data(
            api.create_rate_card_revision(
                rate_card["id"],
                {
                    "expected_rate_card_version": source["version"],
                    "max_markup_pct": 0.10,
                    "effective_from": "2026-06-01",
                    "effective_to": "2027-01-01",
                },
                ADMIN,
            )
        )
        get_success_data(api.activate_rate_card(revision["id"], ADMIN))
        set_logical_clock("2026-06-15T00:00:00Z")
        get_success_data(
            api.run_compliance_audit({"assignment_id": assignment_ids[0]}, ADMIN)
        )

        evaluated = validate_success(api.evaluate_supplier_tier(supplier["id"], ADMIN))
        assert_supplier(evaluated)
        # fill 4/4 = 1.0, compliance 1 - 1/4 = 0.75, acceptance 0/1 = 0
        # -> 100 * (0.4 + 0.3 + 0) = 70 exactly.
        assert evaluated["tier_score"] == 70
        assert evaluated["tier"] == "APPROVED", (
            "exactly 70 satisfies the >= 70 boundary; demoted from PREFERRED"
        )
        assert evaluated["open_violation_count"] == 1


class TestSupplierListPagination:
    def test_limit_offset_and_has_more(self, api):
        """PRD: "`limit` controls page size: it defaults to 10, with a minimum
        of 1 and a maximum of 100. `offset` controls how many records are
        skipped and defaults to 0."
        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` in its `meta` object, so a client can page deterministically
        to the end of a collection."

        Design: Corner/endpoints/pagination_limit_offset_has_more
        """
        onboard_supplier(tier="PREFERRED", name="P1", supplier_code="SUP-P1")
        onboard_supplier(tier="APPROVED", name="P2", supplier_code="SUP-P2")
        onboard_supplier(tier="PROBATION", name="P3", supplier_code="SUP-P3")

        page1, meta1 = validate_paginated(
            api.list_suppliers(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_suppliers(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_filter_composes_and_default_pagination(self, api):
        """PRD: "List suppliers; filters `tier`, `status`" (endpoint routing
        summary).
        PRD: "`limit` controls page size: it defaults to 10, with a minimum
        of 1 and a maximum of 100. `offset` controls how many records are
        skipped and defaults to 0."

        Design: Corner/endpoints/pagination_limit_offset_has_more
        """
        onboard_supplier(tier="PREFERRED", name="P1", supplier_code="SUP-P1")
        onboard_supplier(tier="APPROVED", name="P2", supplier_code="SUP-P2")
        onboard_supplier(tier="PROBATION", name="P3", supplier_code="SUP-P3")

        filtered, meta_f = validate_paginated(
            api.list_suppliers(ADMIN, params={"tier": "APPROVED"})
        )
        assert meta_f["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["supplier_code"] == "SUP-P2"

        _, meta_default = validate_paginated(api.list_suppliers(ADMIN))
        assert meta_default["limit"] == 10, "default page size is 10"
        assert meta_default["offset"] == 0, "default offset is 0"
        assert meta_default["total_count"] == 3


class TestAuditLifecycleDrivesSupplierViolationCounter:
    def _setup_markup_finding(self, api):
        """Book an assignment legal under the original card, then tighten the
        card via revision so an audit run raises exactly one MARKUP_EXCEEDED."""
        set_logical_clock("2026-05-01T00:00:00Z")
        rate_card = create_active_rate_card(
            effective_from="2026-01-01", effective_to="2026-06-01"
        )
        supplier = onboard_supplier(tier="PREFERRED", name="Audit Co",
                                    supplier_code="SUP-AU")
        coordinator = make_supplier_coordinator_headers(supplier["id"])
        engagement = create_engagement_in_open(
            title="Audit", duration_months=6, budget_cents=2_000_000
        )
        offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
        offer = pick_offer_for_supplier(offers, supplier["id"])
        get_success_data(api.respond_to_offer(offer["id"], {"action": "ACCEPT"}, coordinator))
        worker = get_success_data(
            api.create_worker(
                create_worker_payload(supplier["id"], full_name="Worker One",
                                      email="w1@example.com"),
                coordinator,
            )
        )
        assignment = get_success_data(
            api.create_assignment(
                create_assignment_payload(
                    worker["id"], engagement["id"], offer["id"], rate_card["id"],
                    bill_rate_cents=9500, pay_rate_cents=8000,
                    start_date="2026-05-04", end_date="2026-08-31",
                ),
                ADMIN,
            )
        )
        get_success_data(api.activate_assignment(assignment["id"], ADMIN))
        source = get_success_data(api.get_rate_card(rate_card["id"], ADMIN))
        revision = get_success_data(
            api.create_rate_card_revision(
                rate_card["id"],
                {
                    "expected_rate_card_version": source["version"],
                    "max_markup_pct": 0.10,
                    "effective_from": "2026-06-01",
                    "effective_to": "2027-01-01",
                },
                ADMIN,
            )
        )
        get_success_data(api.activate_rate_card(revision["id"], ADMIN))
        set_logical_clock("2026-06-15T00:00:00Z")
        findings = get_success_data(
            api.run_compliance_audit({"assignment_id": assignment["id"]}, ADMIN)
        )
        assert len(findings) == 1 and findings[0]["finding"] == "MARKUP_EXCEEDED"
        return supplier, findings[0]

    def test_acknowledge_keeps_violation_open(self, api):
        """PRD: "starts in `OPEN` status, and increments the supplier's
        `open_violation_count` by one."
        PRD: "Audit disposition walks a strict chain: acknowledging moves
        `OPEN` → `ACKNOWLEDGED`"

        Design: Corner/cross_cutting/audit_lifecycle_drives_supplier_violation_counter
        """
        supplier, finding = self._setup_markup_finding(api)
        assert get_supplier(supplier["id"])["open_violation_count"] == 1

        acknowledged = validate_success(api.acknowledge_audit(finding["id"], ADMIN))
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert get_supplier(supplier["id"])["open_violation_count"] == 1, (
            "ACKNOWLEDGED keeps the violation open"
        )

    def test_resolve_compensates_violation_counter(self, api):
        """PRD: "from `ACKNOWLEDGED` the audit may be resolved or dismissed —
        both record the request's `resolution_note`, both are terminal, and
        both decrement the supplier's `open_violation_count` by one as
        compensation."

        Design: Corner/cross_cutting/audit_lifecycle_drives_supplier_violation_counter
        """
        supplier, finding = self._setup_markup_finding(api)
        get_success_data(api.acknowledge_audit(finding["id"], ADMIN))
        resolved = validate_success(
            api.resolve_audit(finding["id"], {"resolution_note": "rate renegotiated"}, ADMIN)
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "rate renegotiated"
        assert get_supplier(supplier["id"])["open_violation_count"] == 0, (
            "the resolve transition compensates the creation increment"
        )
