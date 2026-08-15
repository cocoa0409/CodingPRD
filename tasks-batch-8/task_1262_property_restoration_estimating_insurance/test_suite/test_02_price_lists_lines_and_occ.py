"""Price-list windows, estimate line composition, and single-writer OCC.

Covers half-open price windows, line defaults and pinning, removed-line
exclusion, sales tax scoping, immediate consistency of computed fields, and the
estimate-create / line-edit optimistic concurrency rules.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId, make_carrier, make_price_entry,
    setup_estimating_claim, setup_draft_estimate, setup_submitted_estimate,
    make_estimate, add_line,
    read_estimate, read_claim, create_estimate_payload,
    create_estimate_line_payload, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]


class TestPriceListWindows:
    def test_adjacent_window_accepted_interior_overlap_rejected(self, api):
        """PRD §3.1: "Within one carrier, windows for the same `category_code` may
        not overlap — a new entry whose window intersects an existing entry's
        window for that carrier and category code is rejected with
        `ERR_PRICE_WINDOW_OVERLAP` (HTTP 409) — but adjacency is allowed: an entry
        whose `effective_from` equals the prior entry's `effective_to` is a legal
        succession, not an overlap."

        Design: Difficulty/resource_temporal_overlap/price_list_half_open_window_overlap
        """
        carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
        make_price_entry(carrier["id"], category_code="WTR-DEMO",
                         trade="DEMOLITION", unit_price_cents=200,
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-06-01T00:00:00Z")
        # adjacency: effective_from == prior effective_to -> legal succession
        entry_b = validate_success(api.create_price_list_entry(
            carrier["id"],
            {"category_code": "WTR-DEMO", "trade": "DEMOLITION", "kind": "LABOR",
             "unit": "SF", "unit_price_cents": 210,
             "effective_from": "2026-06-01T00:00:00Z",
             "effective_to": "2027-01-01T00:00:00Z"}, ADMIN), 201)
        assert is_valid_uuid(entry_b["id"])
        # interior intersection: [2026-05-31, 2026-09-01) cuts into A by one day
        res = api.create_price_list_entry(
            carrier["id"],
            {"category_code": "WTR-DEMO", "trade": "DEMOLITION", "kind": "LABOR",
             "unit": "SF", "unit_price_cents": 220,
             "effective_from": "2026-05-31T00:00:00Z",
             "effective_to": "2026-09-01T00:00:00Z"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_PRICE_WINDOW_OVERLAP)

    def test_overlap_scoped_to_carrier_and_category(self, api):
        """PRD §3.1: "Within one carrier, windows for the same `category_code` may
        not overlap — a new entry whose window intersects an existing entry's
        window for that carrier and category code is rejected with
        `ERR_PRICE_WINDOW_OVERLAP` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/price_list_half_open_window_overlap
        """
        carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
        make_price_entry(carrier["id"], category_code="WTR-DEMO",
                         effective_from="2026-01-01T00:00:00Z",
                         effective_to="2026-06-01T00:00:00Z")
        # contained window on the same category_code -> overlap
        res = api.create_price_list_entry(
            carrier["id"],
            {"category_code": "WTR-DEMO", "trade": "DEMOLITION", "kind": "LABOR",
             "unit": "SF", "unit_price_cents": 205,
             "effective_from": "2026-02-01T00:00:00Z",
             "effective_to": "2026-03-01T00:00:00Z"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_PRICE_WINDOW_OVERLAP)
        # identical window under a different category_code -> no constraint
        other = validate_success(api.create_price_list_entry(
            carrier["id"],
            {"category_code": "DRY-SHEET", "trade": "DRYWALL", "kind": "MATERIAL",
             "unit": "SF", "unit_price_cents": 150,
             "effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2026-06-01T00:00:00Z"}, ADMIN), 201)
        assert is_valid_uuid(other["id"])


class TestLineComposition:
    def test_line_defaults_inherit_price_entry_depreciation(self, api):
        """PRD §3.4: "At add time the line pins `unit_price_cents` from the entry
        and copies the entry's `category_code`, `trade`, `kind`, `tax_applicable`,
        and `o_and_p_eligible`; when `depreciation_pct` is omitted it defaults to
        the entry's `default_depreciation_pct`."
        PRD §3.4: "Each line's `extended_cents` is its `qty` multiplied by its
        `unit_price_cents`, rounded half up to integer cents **per line first**"

        Design: Corner/entities/line_defaults_inherit_price_entry_depreciation
        """
        ctx = setup_estimating_claim(
            with_completed_inspection=False,
            entry_specs=({"category_code": "GEN-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 200,
                          "default_depreciation_pct": 0.20},))
        # estimate creation is legal in ASSESSING: walk only to ASSESSING
        estimate = make_estimate(ctx["claim"]["id"])
        line = validate_success(api.create_estimate_line(
            estimate["id"],
            create_estimate_line_payload(ctx["entries"][0]["id"], 100),
            ESTIMATOR), 201)
        assert line["depreciation_pct"] == pytest.approx(0.20), \
            "inherited from the entry default"
        assert line["extended_cents"] == 20000, "round_half_up(100 * 200)"
        assert line["unit_price_cents"] == 200, "pinned from the entry"
        assert line["negotiation_status"] == "PENDING", "initial line state"

    def test_removed_line_excluded_from_totals(self, api):
        """PRD §3.4: "the estimate's `rcv_total_cents` is then the sum of
        `extended_cents` over all lines whose `negotiation_status` is not
        `REMOVED`."
        PRD §3.4: "While the estimate is `DRAFT` or `REVISED` an `Estimator` may
        also edit a line's `qty` or pinned `unit_price_cents` (the OCC-guarded edit
        of §2.9, taking `expected_estimate_version`), or remove a line entirely,
        which sets its `negotiation_status` to `REMOVED` and excludes it from every
        total."

        Design: Corner/calculations/removed_line_excluded_from_totals
        """
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            entry_specs=(
                {"category_code": "A-100", "trade": "GENERAL", "kind": "LABOR",
                 "unit": "EA", "unit_price_cents": 100},
                {"category_code": "B-200", "trade": "GENERAL", "kind": "LABOR",
                 "unit": "EA", "unit_price_cents": 200},
            ),
            line_specs=[(0, 100), (1, 50)])
        est_id = ctx["estimate"]["id"]
        assert read_estimate(est_id)["rcv_total_cents"] == 20000
        removed = validate_success(api.remove_estimate_line(
            est_id, ctx["lines"][1]["id"], ESTIMATOR), 200)
        assert removed["negotiation_status"] == "REMOVED"
        est = read_estimate(est_id)
        assert est["rcv_total_cents"] == 10000
        assert est["grand_total_cents"] == 10000, \
            "REMOVED lines contribute nothing (single trade -> no O&P, tax 0)"

    def test_tax_only_on_taxable_material_lines(self, api):
        """PRD §3.4: "Sales tax rides on the extended price before overhead and
        profit: each non-removed line with `tax_applicable` true contributes a
        `tax_cents` of its `extended_cents` multiplied by the carrier's `tax_rate`,
        rounded half up per line, and the estimate's `tax_total_cents` is their
        sum."

        Design: Corner/calculations/tax_only_on_taxable_material_lines
        """
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            carrier_overrides={"name": "TaxMutual", "tax_rate": 0.10},
            entry_specs=(
                {"category_code": "MAT-1", "trade": "GENERAL", "kind": "MATERIAL",
                 "unit": "EA", "unit_price_cents": 100, "tax_applicable": True},
                {"category_code": "LAB-1", "trade": "GENERAL", "kind": "LABOR",
                 "unit": "EA", "unit_price_cents": 100, "tax_applicable": False},
            ),
            line_specs=[])
        est_id = ctx["estimate"]["id"]
        taxable = validate_success(api.create_estimate_line(
            est_id, create_estimate_line_payload(ctx["entries"][0]["id"], 100),
            ESTIMATOR), 201)
        labor = validate_success(api.create_estimate_line(
            est_id, create_estimate_line_payload(ctx["entries"][1]["id"], 100),
            ESTIMATOR), 201)
        assert taxable["tax_cents"] == 1000, "round_half_up(10,000 * 0.10)"
        assert labor["tax_cents"] == 0
        est = read_estimate(est_id)
        assert est["tax_total_cents"] == 1000
        assert est["grand_total_cents"] == 21000, \
            "20,000 rcv + 1,000 tax + 0 O&P (single trade)"

    def test_line_with_unknown_price_entry_not_found(self, api):
        """PRD §2.6: "The same error and status apply when a body-supplied
        reference does not resolve — a `policy_id` on claim creation, a
        `price_list_entry_id` on a new estimate line, a `claim_id` on a photo, an
        `inspection_id` or `supplement_id` on a photo or reading, or an
        `estimate_line_id` inside a negotiation disposition."

        Design: Corner/validations/line_with_unknown_price_entry_not_found
        """
        ctx = setup_estimating_claim(with_completed_inspection=False)
        estimate = make_estimate(ctx["claim"]["id"])
        res = api.create_estimate_line(
            estimate["id"],
            create_estimate_line_payload(NON_EXISTENT_UUID, 10), ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_line_patch_on_submitted_estimate_returns_not_editable(self, api):
        """PRD §3.4: "Any line mutation against an estimate that is not in an
        editable state — and any recording of actuals outside its window (§3.8) —
        is rejected with `ERR_ESTIMATE_NOT_EDITABLE` (HTTP 409)."
        PRD §3.4: "While the estimate is `DRAFT` or `REVISED` an `Estimator` may
        also edit a line's `qty` or pinned `unit_price_cents` (the OCC-guarded edit
        of §2.9, taking `expected_estimate_version`)"

        Design: Corner/validations/line_patch_on_submitted_estimate_returns_not_editable
        """
        ctx = setup_submitted_estimate(line_specs=[(0, 100)])
        est_id = ctx["estimate"]["id"]
        current = read_estimate(est_id)["version"]
        # SUBMITTED is not DRAFT/REVISED; the current OCC version does not save it
        res = api.patch_estimate_line(
            est_id, ctx["lines"][0]["id"],
            {"expected_estimate_version": current, "qty": 110}, ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_ESTIMATE_NOT_EDITABLE)

    def test_mutation_visible_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "Each non-removed line's `depreciation_cents` is its
        `extended_cents` multiplied by its `depreciation_pct`, rounded half up."

        Design: Corner/consistency_model/mutation_visible_in_same_response
        """
        ctx = setup_estimating_claim(
            with_completed_inspection=False,
            entry_specs=({"category_code": "GEN-1", "trade": "GENERAL",
                          "kind": "LABOR", "unit": "EA", "unit_price_cents": 200,
                          "default_depreciation_pct": 0.10},))
        estimate = make_estimate(ctx["claim"]["id"])
        line = validate_success(api.create_estimate_line(
            estimate["id"],
            create_estimate_line_payload(ctx["entries"][0]["id"], 100),
            ESTIMATOR), 201)
        assert line["extended_cents"] == 20000, "computed server-side, immediately"
        assert line["unit_price_cents"] == 200, "pinned server-side, immediately"
        assert line["depreciation_cents"] == 2000, "round_half_up(20,000 * 0.10)"


class TestSingleWriterOcc:
    def test_occ_estimate_create_stale_claim_version(self, api):
        """PRD §2.9: "**Estimate creation** — `POST /v1/claims/{id}/estimates`
        requires `expected_claim_version` carrying the client's last observed
        `version` of the claim."
        PRD §2.9: "A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_estimate_create_stale_claim_version
        """
        ctx = setup_estimating_claim(with_completed_inspection=False)
        claim_id = ctx["claim"]["id"]
        observed_version = ctx["claim"]["version"]
        first = validate_success(api.create_estimate(
            claim_id, create_estimate_payload(observed_version), ESTIMATOR), 201)
        assert is_valid_uuid(first["id"])
        # replay with the now-stale observed version
        res = api.create_estimate(
            claim_id, create_estimate_payload(observed_version), ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert read_claim(claim_id)["version"] == observed_version + 1, \
            "creating an estimate increments the claim's version (PRD §3.4)"

    def test_occ_line_patch_stale_estimate_version(self, api):
        """PRD §2.9: "**Line edit** — `PATCH /v1/estimates/{id}/lines/{line_id}`
        requires `expected_estimate_version` matching the estimate's current
        `version`."
        PRD §2.9: "A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_line_patch_stale_estimate_version
        """
        ctx = setup_draft_estimate(with_completed_inspection=False,
                                   line_specs=[(0, 100)])
        est_id = ctx["estimate"]["id"]
        line_id = ctx["lines"][0]["id"]
        observed = read_estimate(est_id)["version"]
        patched = validate_success(api.patch_estimate_line(
            est_id, line_id,
            {"expected_estimate_version": observed, "qty": 110}, ESTIMATOR), 200)
        assert patched["qty"] == 110
        res = api.patch_estimate_line(
            est_id, line_id,
            {"expected_estimate_version": observed, "qty": 120}, ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert read_estimate(est_id)["version"] == observed + 1
