"""Photo attachment rules and the supplement scope-drift cascade.

Covers photo parent exclusivity, the supplement creation state gate, the
supplement evidence gate, and the depth-3 cascade where approving a SUPPLEMENT
estimate recomputes the claim RCV, voids the signed work authorization on drift
beyond 10%, and drops the claim to ON_HOLD.
"""
from test_helpers import (
    validate_success, validate_error, is_valid_uuid, ApiErrorId,
    make_claim_ctx, claim_to_assessing, claim_to_estimating,
    setup_estimating_claim, setup_in_progress_claim, make_submitted_supplement,
    approve_supplement_and_get_estimate, add_line, submit_estimate,
    approve_estimate, read_claim, create_photo_payload, create_supplement_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
TECH = TEST_USERS["field_technician_headers"]

_WATER_POLICY = {"coverage_a_limit_cents": 100000000, "flat_deductible_cents": 100000}
_ACME_CARRIER = {"name": "Acme Mutual", "tax_rate": 0.07}


class TestPhotoParentRules:
    def test_photo_requires_exactly_one_parent_rejected(self, api):
        """PRD §3.3: "Photos attach to the claim with a `claim_id` plus exactly one
        of `inspection_id` or `supplement_id` — never both, never neither — and a
        `tag` of `LOSS_OVERVIEW`, `AREA`, `MOISTURE_PROOF`, `SUPPLEMENT_EVIDENCE`,
        or `COMPLETION`, along with an opaque `file_ref` and the `captured_at`
        timestamp."
        PRD §3.3: "Violations of the parent exclusivity or tag consistency are
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/photo_requires_exactly_one_parent_rejected
        """
        # Claim IN_PROGRESS: has a completed inspection and can hold a supplement,
        # so both parent references resolve and only the exclusivity rule can fail.
        ctx = setup_in_progress_claim(cause_of_loss="WATER",
                                      carrier_overrides=_ACME_CARRIER,
                                      policy_overrides=_WATER_POLICY,
                                      line_specs=[(0, 100)], direct_pay=False)
        claim_id = ctx["claim"]["id"]
        inspection_id = ctx["inspection"]["id"]
        supp = validate_success(api.create_supplement(
            claim_id, create_supplement_payload("Hidden damage"), ESTIMATOR), 201)

        # neither parent set
        res = api.create_photo(create_photo_payload(claim_id, tag="AREA",
                                                    file_ref="x.jpg"), TECH)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        # both parents set (both resolve to real resources)
        both = create_photo_payload(claim_id, tag="AREA", file_ref="y.jpg")
        both["inspection_id"] = inspection_id
        both["supplement_id"] = supp["id"]
        validate_error(api.create_photo(both, TECH),
                       ApiErrorId.ERR_INVALID_REQUEST)


class TestSupplementGates:
    def test_supplement_create_before_work_returns_409(self, api):
        """PRD §3.6: "An `Estimator` creates one against a claim carrying a
        `narrative` of the discovery; creation is permitted only while the claim is
        `IN_PROGRESS`, and is otherwise rejected with `ERR_SUPPLEMENT_NOT_PERMITTED`
        (HTTP 409)."

        Design: Corner/state_machines/supplement_create_before_work_returns_409
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides=_ACME_CARRIER,
                             policy_overrides=_WATER_POLICY)
        claim_to_assessing(ctx)
        claim_to_estimating(ctx)
        res = api.create_supplement(ctx["claim"]["id"],
                                    create_supplement_payload("Too early"), ESTIMATOR)
        validate_error(res, ApiErrorId.ERR_SUPPLEMENT_NOT_PERMITTED)

    def test_supplement_submit_without_evidence_returns_422(self, api):
        """PRD §3.6: "Submitting it requires a non-empty `narrative` and at least 2
        photos attached to this supplement with the `SUPPLEMENT_EVIDENCE` tag;
        failure is `ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT` (HTTP 422)."

        Design: Corner/state_machines/supplement_submit_without_evidence_returns_422
        """
        ctx = setup_in_progress_claim(cause_of_loss="WATER",
                                      carrier_overrides=_ACME_CARRIER,
                                      policy_overrides=_WATER_POLICY,
                                      line_specs=[(0, 100)], direct_pay=False)
        claim_id = ctx["claim"]["id"]
        supp = validate_success(api.create_supplement(
            claim_id,
            create_supplement_payload("Hidden damage behind cabinets"),
            ESTIMATOR), 201)
        # 0 < 2 evidence photos
        validate_error(api.submit_supplement(supp["id"], ESTIMATOR),
                       ApiErrorId.ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT)
        for i in (1, 2):
            validate_success(api.create_photo(
                create_photo_payload(claim_id, tag="SUPPLEMENT_EVIDENCE",
                                     file_ref=f"s{i}.jpg",
                                     captured_at=f"2026-05-06T09:0{i - 1}:00Z",
                                     supplement_id=supp["id"]), ESTIMATOR), 201)
        # exactly 2 photos satisfies the >= 2 boundary
        submitted = validate_success(api.submit_supplement(supp["id"], ESTIMATOR), 200)
        assert submitted["status"] == "SUBMITTED"


# Main-estimate spec shared by the scope-drift tests: three trades so O&P
# applies, matching the carrier-standard water-restoration estimate.
_DRIFT_CARRIER = {"name": "Acme Mutual", "tax_rate": 0.07, "overhead_rate": 0.10,
                  "profit_rate": 0.10, "o_and_p_min_trades": 3}
_DRIFT_ENTRIES = (
    {"category_code": "WTR-DEMO", "trade": "DEMOLITION", "kind": "LABOR",
     "unit": "SF", "unit_price_cents": 200, "tax_applicable": False,
     "o_and_p_eligible": True, "default_depreciation_pct": 0.10},
    {"category_code": "DRY-SHEET", "trade": "DRYWALL", "kind": "MATERIAL",
     "unit": "SF", "unit_price_cents": 150, "tax_applicable": True,
     "o_and_p_eligible": True, "default_depreciation_pct": 0.20},
    {"category_code": "PNT-WALL", "trade": "PAINT", "kind": "MATERIAL",
     "unit": "SF", "unit_price_cents": 120, "tax_applicable": True,
     "o_and_p_eligible": True, "default_depreciation_pct": 0.25},
)
_DRIFT_POLICY = {"coverage_a_limit_cents": 100000000, "flat_deductible_cents": 100000,
                 "ordinance_coverage_pct": 0.10, "ordinance_flat_cap_cents": 250000}


def _supplement_estimate_with_lines(ctx, line_specs):
    make_submitted_supplement(
        ctx, "Hidden mold behind kitchen cabinets discovered during demolition")
    approve_supplement_and_get_estimate(ctx)
    sest = ctx["supplement_estimate"]
    for entry_idx, qty in line_specs:
        add_line(sest["id"], ctx["entries"][entry_idx]["id"], qty)
    submit_estimate(sest["id"])
    return sest


class TestScopeDriftCascade:
    def test_supplement_approval_voids_authorization_holds_claim(self, api):
        """PRD §3.6: "Approving a `SUPPLEMENT` estimate fires the scope-drift
        cascade, in order: the estimate moves to `APPROVED`; the claim's
        `rcv_total_cents` is recomputed over the now-larger approved set; and the
        new total is compared against the `scope_rcv_cents` snapshot on the claim's
        `SIGNED` work authorization."
        PRD §3.6: "When the absolute drift is strictly greater than 10 percent of
        `scope_rcv_cents` — with the 10 percent threshold itself rounded half up to
        integer cents, and a drift of exactly 10 percent *not* voiding — the
        authorization is auto-voided with `voided_reason` `SCOPE_DRIFT`, and a
        claim in `IN_PROGRESS` drops to `ON_HOLD` with its `version` incremented."

        Design: Difficulty/transitive_cascade/supplement_approval_voids_authorization_holds_claim
        """
        ctx = setup_in_progress_claim(
            cause_of_loss="WATER", carrier_overrides=_DRIFT_CARRIER,
            policy_overrides=_DRIFT_POLICY, entry_specs=_DRIFT_ENTRIES,
            line_specs=[(0, 10000), (1, 10000), (2, 10000)],
            direct_pay=True, clear_advance=False)
        # signed WA snapshot: scope_rcv_cents = 5,876,000 (claim grand total)
        assert ctx["wa"]["scope_rcv_cents"] == 5876000
        claim_id = ctx["claim"]["id"]
        # supplement adds one untaxed single-trade line: 4,000 x 200c = 800,000c
        sest = _supplement_estimate_with_lines(ctx, [(0, 4000)])
        approved = approve_estimate(sest["id"])
        assert approved["status"] == "APPROVED", "hop 1"
        claim = read_claim(claim_id)
        assert claim["rcv_total_cents"] == 6676000, \
            "hop 2: 5,876,000 + 800,000 supplement"
        was = validate_success(api.list_work_authorizations(claim_id, ADMIN), 200)
        assert was[0]["status"] == "VOIDED"
        assert was[0]["voided_reason"] == "SCOPE_DRIFT", \
            "hop 3: |6,676,000 - 5,876,000| = 800,000 > 587,600 (10% of scope)"
        assert claim["status"] == "ON_HOLD", \
            "hop 4: the WA void forced the claim off IN_PROGRESS"

    def test_drift_within_and_at_tolerance_does_not_void(self, api):
        """PRD §3.6: "When the absolute drift is strictly greater than 10 percent
        of `scope_rcv_cents` — with the 10 percent threshold itself rounded half up
        to integer cents, and a drift of exactly 10 percent *not* voiding — the
        authorization is auto-voided with `voided_reason` `SCOPE_DRIFT`, and a
        claim in `IN_PROGRESS` drops to `ON_HOLD` with its `version` incremented."

        Design: Difficulty/transitive_cascade/supplement_approval_voids_authorization_holds_claim
        """
        # scope 200,000 (one line 1,000 @ 200c, single trade, tax 0);
        # threshold = round_half_up(10% * 200,000) = 20,000.
        def run(drift_lines):
            ctx = setup_in_progress_claim(cause_of_loss="WATER",
                                          carrier_overrides={"name": "ZeroTax Mutual",
                                                             "tax_rate": 0},
                                          policy_overrides=_WATER_POLICY,
                                          line_specs=[(0, 1000)], direct_pay=False)
            assert ctx["wa"]["scope_rcv_cents"] == 200000
            sest = _supplement_estimate_with_lines(ctx, drift_lines)
            approve_estimate(sest["id"])
            claim = read_claim(ctx["claim"]["id"])
            was = validate_success(
                api.list_work_authorizations(ctx["claim"]["id"], ADMIN), 200)
            return claim, was[0]

        # exactly 10% drift (100 @ 200c = 20,000): NOT voided
        claim_a, wa_a = run([(0, 100)])
        assert wa_a["status"] == "SIGNED", "drift of exactly 10 percent not voiding"
        assert claim_a["status"] == "IN_PROGRESS"
        # one cent beyond the threshold (20,001): voided
        claim_b, wa_b = run([(0, 100), (0, 0.005)])
        assert wa_b["status"] == "VOIDED" and wa_b["voided_reason"] == "SCOPE_DRIFT"
        assert claim_b["status"] == "ON_HOLD"
