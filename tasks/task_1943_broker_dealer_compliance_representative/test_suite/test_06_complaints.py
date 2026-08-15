"""Customer complaints: reportability threshold, dual reserve variants,
parallel status/regulatory axes, amendment, and the award-disclosure
cascade (PRD §3.5).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_complaint_payload,
    make_branch_with_rep,
    patch_complaint_payload,
    resolve_complaint_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]


def _make_complaint(rep_id, **overrides):
    """Intake a complaint as the analyst. Returns the RECEIVED complaint."""
    return validate_success(
        api_client.create_complaint(
            create_complaint_payload(rep_id, **overrides), ANALYST
        ),
        201,
    )


# ─── dual-variant complaint reserve ───────────────────

class TestDualComplaintReserveVariants:
    def test_provisional_reserve_uses_allegation_rate(self, api, any_headers):
        """PRD §3.5: "The `provisional_reserve_cents` is the claimed amount
        multiplied by an allegation rate — one hundred percent for `FORGERY`
        and `THEFT`, sixty percent for `MISREPRESENTATION`, fifty percent for
        `UNAUTHORIZED_TRADING`, forty percent for `SUITABILITY`, and
        twenty-five percent for `OTHER` — rounded half-up to whole cents."
        A SUITABILITY claim of 2000000 cents provisions at 800000.

        Design: Difficulty/dual_variant_calc/dual_complaint_reserve_variants
        """
        _branch, rep = make_branch_with_rep(region="SE", crd_number="100002")
        complaint = _make_complaint(
            rep["id"], allegation_type="SUITABILITY",
            damages_claimed_cents=2000000, received_date="2026-08-02",
        )
        assert complaint["provisional_reserve_cents"] == 800000
        assert complaint["status"] == "RECEIVED"
        assert complaint.get("final_reserve_cents") is None

    def test_final_reserve_uses_actuals_capped_at_125_percent(self, api,
                                                              any_headers):
        """PRD §3.5: "the system computes the `final_reserve_cents` as the
        lesser of two figures: the sum of damages paid and legal costs, or
        one hundred twenty-five percent of the claimed damages rounded
        half-up to whole cents." On identical claimed damages (2000000) the
        variants diverge: provisional 800000 vs final
        min(1500000 + 100000, 2500000) = 1600000.

        Design: Difficulty/dual_variant_calc/dual_complaint_reserve_variants
        """
        _branch, rep = make_branch_with_rep(region="SE", crd_number="100002")
        complaint = _make_complaint(
            rep["id"], allegation_type="SUITABILITY",
            damages_claimed_cents=2000000, received_date="2026-08-02",
        )
        resolved = validate_success(
            api.resolve_complaint(
                complaint["id"],
                resolve_complaint_payload(damages_paid_cents=1500000,
                                          legal_cost_cents=100000),
                PRINCIPAL_A,
            ),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["final_reserve_cents"] == 1600000
        assert resolved["final_reserve_cents"] != resolved["provisional_reserve_cents"]


# ─── reportability boundary ───────────────────────────

class TestComplaintReportabilityThreshold:
    def test_499999_is_not_reportable(self, api, any_headers):
        """PRD §3.5: "The `reportable` flag is true when claimed damages are
        at least 500000 cents (five thousand dollars) — exactly 500000 is
        reportable, 499999 is not — or when the allegation is `FORGERY` or
        `THEFT`, regardless of amount." and "its `regulatory_status` — a
        parallel dimension independent of `status` — initializes to
        `REQUIRED` when the complaint is reportable and `NOT_REQUIRED`
        otherwise."

        Design: Difficulty/boundary_precision_check/boundary_complaint_reportability_threshold
        """
        _branch, rep = make_branch_with_rep(region="E", crd_number="400001")
        complaint = _make_complaint(
            rep["id"], allegation_type="OTHER", damages_claimed_cents=499999,
        )
        assert complaint["reportable"] is False
        assert complaint["regulatory_status"] == "NOT_REQUIRED"

    def test_500000_is_reportable(self, api, any_headers):
        """PRD §3.5: "exactly 500000 is reportable, 499999 is not" — the
        threshold is inclusive, so a claim of exactly 500000 cents
        initializes `regulatory_status` to `REQUIRED`.

        Design: Difficulty/boundary_precision_check/boundary_complaint_reportability_threshold
        """
        _branch, rep = make_branch_with_rep(region="E", crd_number="400001")
        complaint = _make_complaint(
            rep["id"], allegation_type="OTHER", damages_claimed_cents=500000,
        )
        assert complaint["reportable"] is True
        assert complaint["regulatory_status"] == "REQUIRED"


# ─── parallel axes ────────────────────────────────────

class TestComplaintParallelAxes:
    def test_resolve_then_report_on_independent_axes(self, api, any_headers):
        """PRD §3.5: "The two axes never interact: a complaint may be
        resolved before or after its report is filed, and resolution neither
        requires nor performs a filing." A reportable complaint (600000
        claimed) resolves while still REQUIRED, then the report files:
        "Filing stamps `reported_at` with the current clock date, sets
        `is_late_report` to true when the filing date falls after the
        `report_deadline`, and moves `regulatory_status` to `FILED`, which is
        terminal for the regulatory axis."

        Design: Difficulty/cross_cutting/compound_complaint_parallel_axes
        """
        _branch, rep = make_branch_with_rep(region="S", crd_number="820001")
        complaint = _make_complaint(
            rep["id"], allegation_type="MISREPRESENTATION",
            damages_claimed_cents=600000, received_date="2026-08-02",
        )
        assert complaint["regulatory_status"] == "REQUIRED"

        resolved = validate_success(
            api.resolve_complaint(
                complaint["id"],
                resolve_complaint_payload(damages_paid_cents=100000,
                                          legal_cost_cents=0),
                PRINCIPAL_A,
            ),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["regulatory_status"] == "REQUIRED"

        reported = validate_success(
            api.report_complaint(complaint["id"], PRINCIPAL_A), 200
        )
        assert reported["regulatory_status"] == "FILED"
        assert reported["status"] == "RESOLVED"

    def test_amend_resolved_complaint_rejected_without_touching_axis(
        self, api, any_headers
    ):
        """PRD §3.5: "Amending a complaint no longer in `RECEIVED` is
        rejected with `ERR_COMPLAINT_NOT_RESOLVABLE`." The regulatory axis
        (FILED after the report) is untouched by the rejected amendment.

        Design: Difficulty/cross_cutting/compound_complaint_parallel_axes
        """
        _branch, rep = make_branch_with_rep(region="S", crd_number="820001")
        complaint = _make_complaint(
            rep["id"], allegation_type="MISREPRESENTATION",
            damages_claimed_cents=600000, received_date="2026-08-02",
        )
        validate_success(
            api.resolve_complaint(
                complaint["id"],
                resolve_complaint_payload(damages_paid_cents=100000,
                                          legal_cost_cents=0),
                PRINCIPAL_A,
            ),
            200,
        )
        validate_success(api.report_complaint(complaint["id"], PRINCIPAL_A), 200)

        res = api.patch_complaint(
            complaint["id"], patch_complaint_payload(700000), ANALYST
        )
        validate_error(res, ApiErrorId.ERR_COMPLAINT_NOT_RESOLVABLE)

        after = validate_success(api.get_complaint(complaint["id"], ANY), 200)
        assert after["status"] == "RESOLVED"
        assert after["regulatory_status"] == "FILED"
        assert after["damages_claimed_cents"] == 600000


# ─── amendment flips reportability both ways ──────────

def test_patch_complaint_threshold_flips_reportability(api, any_headers):
    """PRD §3.5: "Amendment recomputes reportability and the provisional
    reserve, and flips `regulatory_status` in whichever direction the
    threshold was crossed — a downward amendment that drops claimed damages
    below the threshold on a non-forgery allegation moves `regulatory_status`
    from `REQUIRED` back to `NOT_REQUIRED`, and an upward crossing moves it
    from `NOT_REQUIRED` to `REQUIRED`."

    Design: Corner/validations/patch_complaint_threshold_flips_reportability
    """
    _branch, rep = make_branch_with_rep(region="E", crd_number="930005")
    complaint = _make_complaint(
        rep["id"], allegation_type="OTHER", damages_claimed_cents=400000,
        received_date="2026-08-01",
    )
    assert complaint["regulatory_status"] == "NOT_REQUIRED"

    up = validate_success(
        api.patch_complaint(complaint["id"], patch_complaint_payload(500000),
                            ANALYST),
        200,
    )
    assert up["reportable"] is True
    assert up["regulatory_status"] == "REQUIRED"

    down = validate_success(
        api.patch_complaint(complaint["id"], patch_complaint_payload(499999),
                            ANALYST),
        200,
    )
    assert down["reportable"] is False
    assert down["regulatory_status"] == "NOT_REQUIRED"


# ─── report gate ──────────────────────────────────────

def test_report_not_required_complaint_rejected(api, any_headers):
    """PRD §3.5: "A principal files the regulatory report for a complaint
    only while its `regulatory_status` is `REQUIRED`; filing from any other
    regulatory state is rejected with `ERR_REPORT_NOT_REQUIRED`."

    Design: Corner/validations/report_not_required_complaint_rejected
    """
    _branch, rep = make_branch_with_rep(region="N", crd_number="930007")
    complaint = _make_complaint(
        rep["id"], allegation_type="OTHER", damages_claimed_cents=100000,
        received_date="2026-08-01",
    )
    assert complaint["regulatory_status"] == "NOT_REQUIRED"
    res = api.report_complaint(complaint["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_REQUIRED)


# ─── award disclosure cascade ─────────────────────────

def test_resolve_at_award_threshold_creates_disclosure(api, any_headers):
    """PRD §3.5: "when `damages_paid_cents` is at least 150000 cents —
    exactly 150000 triggers — resolution automatically creates a
    DisclosureEvent in `DRAFT` with `event_type` of `CUSTOMER_AWARD`,
    `event_date` set to the current clock date, `rep_id` taken from the
    resolved complaint, and `source_complaint_id` recording the complaint's
    `id`." Also: "the system computes the `final_reserve_cents` as the
    lesser of two figures: the sum of damages paid and legal costs, or one
    hundred twenty-five percent of the claimed damages rounded half-up to
    whole cents" — min(1500000 + 0, 2500000) = 1500000.

    Design: Corner/cross_cutting/resolve_complaint_creates_award_disclosure
    """
    _branch, rep = make_branch_with_rep(region="W", crd_number="960002")
    complaint = _make_complaint(
        rep["id"], allegation_type="MISREPRESENTATION",
        damages_claimed_cents=2000000, received_date="2026-07-15",
    )
    resolved = validate_success(
        api.resolve_complaint(
            complaint["id"],
            resolve_complaint_payload(damages_paid_cents=1500000,
                                      legal_cost_cents=0),
            PRINCIPAL_A,
        ),
        200,
    )
    assert resolved["final_reserve_cents"] == 1500000

    data, meta = validate_paginated(
        api.list_disclosure_events(ANY, params={"rep_id": rep["id"]})
    )
    assert len(data) == 1, f"expected exactly one auto-created disclosure: {data}"
    event = data[0]
    assert event["event_type"] == "CUSTOMER_AWARD"
    assert event["status"] == "DRAFT"
    assert event.get("source_complaint_id") == complaint["id"]
    assert event["event_date"] == "2026-08-01"


# ─── schema validation ────────────────────────────────

def test_complaint_invalid_allegation_enum_rejected(api, any_headers):
    """PRD §2.10: "Only after all domain rules pass are field-level checks
    applied: required fields present, enum membership exact, and monetary or
    count fields non-negative integers" — violations "are reported as
    `ERR_VALIDATION` (HTTP 400)". §3.5 limits intake to "an `allegation_type`
    of `FORGERY`, `THEFT`, `MISREPRESENTATION`, `SUITABILITY`,
    `UNAUTHORIZED_TRADING`, or `OTHER`".

    Design: Corner/validations/complaint_invalid_enum_rejected
    """
    _branch, rep = make_branch_with_rep(region="N", crd_number="930003")
    res = api.create_complaint(
        create_complaint_payload(rep["id"], allegation_type="WITCHCRAFT",
                                 damages_claimed_cents=100,
                                 received_date="2026-08-01"),
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_complaint_missing_damages_rejected(api, any_headers):
    """PRD §2.10: "Only after all domain rules pass are field-level checks
    applied: required fields present, enum membership exact, and monetary or
    count fields non-negative integers" — violations "are reported as
    `ERR_VALIDATION` (HTTP 400)". §3.5 intake requires "the
    `damages_claimed_cents` as a non-negative integer of cents".

    Design: Corner/validations/complaint_missing_damages_rejected
    """
    _branch, rep = make_branch_with_rep(region="S", crd_number="930004")
    payload = create_complaint_payload(rep["id"], received_date="2026-08-01")
    del payload["damages_claimed_cents"]
    res = api.create_complaint(payload, ANALYST)
    validate_error(res, ApiErrorId.ERR_VALIDATION)
