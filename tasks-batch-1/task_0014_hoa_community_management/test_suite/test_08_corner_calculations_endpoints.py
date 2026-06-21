"""Corner-design translations from queue (B): calculations §3 and endpoints §5."""
from test_helpers import (
    bootstrap_tenant,
    create_assessment,
    create_community,
    create_reserve_study,
    set_clock,
    validate_success,
)
from test_helpers.test_users import (
    make_board_secretary_headers,
    make_homeowner_headers,
    make_treasurer_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Section: calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_late_fee_zero_at_exact_grace_boundary(api):
    """PRD §3.3: "The system first calculates the number of full days
    elapsed since `due_date` by taking the difference between `current_utc`
    and `due_date` and rounding down to whole days. If the elapsed days
    are strictly less than the community's `late_fee_grace_days`, then
    `late_fee_cents` is zero."
    PRD §3.3: "The transition from `DUE` to `OVERDUE` requires both that
    `outstanding_cents` is greater than zero and that the elapsed time
    since `due_date` strictly exceeds `late_fee_grace_days` whole days."

    At clock 2026-01-16 with due_date 2026-01-01 and grace=15:
    elapsed_days = 15. PRD requires "strictly exceeds 15" → still DUE,
    late_fee_cents == 0.

    Design: Corner/calculations/late_fee_zero_when_within_grace_window
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Grace", owner_email="gr@x.com", owner_name="GR",
        unit_label="GR-1",
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=30000,
        due_date="2026-01-01T00:00:00Z",
    )
    set_clock("2026-01-16T00:00:00Z")
    refreshed = validate_success(
        api.get_assessment(a["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert refreshed["late_fee_cents"] == 0
    assert refreshed["status"] == "DUE"


def test_violation_tier_resets_when_prior_outside_365_day_window(api):
    """PRD §3.5: "At issuance, the system computes the violation's `tier`
    by counting the property's prior `Violation` rows of the SAME `category`
    whose `opened_at` falls within the rolling 365-day window ending
    strictly at `current_utc` and whose lifecycle `status` is one of
    `OPEN`, `CONTESTED`, `UPHELD`, or `PAID` (i.e., everything except
    `DISMISSED`). The new violation's `tier` is that count of priors plus
    one (so the first violation in the window is tier 1, the second is
    tier 2, and so on, with each tier 1-indexed). The `fine_cents` is then
    assigned from a flat tier schedule: tier 1 is 10000 cents, tier 2 is
    25000 cents, tier 3 is 50000 cents, and tier 4 or higher caps at
    100000 cents."

    Setup: open a PARKING violation at clock=2025-01-01 (this becomes the
    "prior"); advance clock to 2026-03-01 (>365 days later); open a new
    PARKING violation — old one is outside the rolling 365-day window
    → new tier == 1, fine_cents == 10000.

    Design: Corner/calculations/violation_tier_resets_after_365_day_window
    """
    _community, owner, prop = bootstrap_tenant(
        community_name="Window", owner_email="win@x.com", owner_name="WIN",
        unit_label="WIN-1",
    )
    set_clock("2025-01-01T00:00:00Z")
    v_old = validate_success(
        api.create_violation(
            {"property_id": prop["id"], "category": "PARKING"},
            make_board_secretary_headers(),
        ),
        expected_status=201,
    )
    # Pay it so it stays in a status counted by the window (PAID is counted)
    # — but the new violation is opened after the 365-day window, so the
    # window filter alone (not the status filter) excludes it.
    validate_success(
        api.pay_violation_fine(v_old["id"], make_homeowner_headers(owner["id"])),
        expected_status=200,
    )
    set_clock("2026-03-01T00:00:00Z")
    v_new = validate_success(
        api.create_violation(
            {"property_id": prop["id"], "category": "PARKING"},
            make_board_secretary_headers(),
        ),
        expected_status=201,
    )
    assert v_new["tier"] == 1, (
        f"prior violation 2025-01-01 is outside 365-day window from 2026-03-01; "
        f"new tier must be 1, got {v_new['tier']}"
    )
    assert v_new["fine_cents"] == 10000, (
        f"tier-1 fine must be 10000, got {v_new['fine_cents']}"
    )


def test_violation_tier_schedule_three_priors_then_tier_4_cap(api):
    """PRD §3.5: "At issuance, the system computes the violation's `tier`
    by counting the property's prior `Violation` rows of the SAME `category`
    whose `opened_at` falls within the rolling 365-day window ending
    strictly at `current_utc` and whose lifecycle `status` is one of
    `OPEN`, `CONTESTED`, `UPHELD`, or `PAID` (i.e., everything except
    `DISMISSED`). The new violation's `tier` is that count of priors plus
    one (so the first violation in the window is tier 1, the second is
    tier 2, and so on, with each tier 1-indexed). The `fine_cents` is then
    assigned from a flat tier schedule: tier 1 is 10000 cents, tier 2 is
    25000 cents, tier 3 is 50000 cents, and tier 4 or higher caps at
    100000 cents."

    Setup: open four sequential NOISE violations within the window —
    tiers must be 1,2,3,4 and fines 10000, 25000, 50000, 100000.

    Design: Corner/calculations/violation_tier_three_fine_50000
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Tiers", owner_email="ti@x.com", owner_name="TI",
        unit_label="TI-1",
    )
    set_clock("2026-03-01T00:00:00Z")
    headers = make_board_secretary_headers()
    fines = []
    tiers = []
    for _ in range(4):
        v = validate_success(
            api.create_violation(
                {"property_id": prop["id"], "category": "NOISE"},
                headers,
            ),
            expected_status=201,
        )
        tiers.append(v["tier"])
        fines.append(v["fine_cents"])
    assert tiers == [1, 2, 3, 4], f"tier progression must be 1-4, got {tiers}"
    assert fines == [10000, 25000, 50000, 100000], (
        f"fine schedule must be [10000, 25000, 50000, 100000], got {fines}"
    )


def test_reserve_adequacy_full_funded_when_no_components(api):
    """PRD §3.8: "If `projected_obligation_cents` is zero, `percent_funded_bps`
    is set to 10000 by convention (100 percent — no obligation)."

    Setup: Community with NO ReserveComponents → projected_obligation_cents
    == 0 → percent_funded_bps == 10000 regardless of accumulated_funds_cents.

    Design: Corner/calculations/reserve_adequacy_zero_obligation_returns_full_percent
    """
    community = create_community(name="ZeroObl")
    study = create_reserve_study(
        community["id"], fiscal_year=2026, method="COMPONENT",
        accumulated_funds_cents=5_000_000,
    )
    assert study["projected_obligation_cents"] == 0
    assert study["percent_funded_bps"] == 10000


# ─────────────────────────────────────────────────────────────────────────────
# Section: endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_list_assessments_filtered_by_status_overdue(api):
    """PRD §3.3: "The transition from `DUE` to `OVERDUE` requires both
    that `outstanding_cents` is greater than zero and that the elapsed
    time since `due_date` strictly exceeds `late_fee_grace_days` whole days."
    PRD §4: "GET `/hoa/assessments` ... List Assessments (filtered by
    `property_id`, `status`)".

    Setup: two Assessments — one DUE (future due_date), one OVERDUE
    (driven via clock advance). GET ?status=OVERDUE must return only the
    OVERDUE row.

    Design: Corner/endpoints/list_assessments_filtered_by_status_overdue
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Filter", owner_email="fl@x.com", owner_name="FL",
        unit_label="FL-1", regular_assessment_cents=10000,
    )
    a_overdue = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2026-01-01T00:00:00Z",
    )
    a_due = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2027-06-01T00:00:00Z",
    )
    set_clock("2026-02-01T00:00:00Z")
    resp = api.list_assessments(
        make_treasurer_headers(),
        params={"property_id": prop["id"], "status": "OVERDUE"},
    )
    data = validate_success(resp, expected_status=200)
    rows = data if isinstance(data, list) else (
        data.get("items") or data.get("data") or []
    )
    ids = {r["id"] for r in rows}
    assert a_overdue["id"] in ids, "OVERDUE assessment must appear in filtered list"
    assert a_due["id"] not in ids, (
        "DUE assessment must NOT appear in OVERDUE-filtered list"
    )
    for r in rows:
        assert r["status"] == "OVERDUE", (
            f"every row in filtered list must have status OVERDUE, "
            f"got {r['status']}"
        )


def test_projected_balance_does_not_mutate_assessment(api):
    """PRD §3.3: "The response carries `projected_late_fee_cents` and
    `projected_outstanding_cents` and does NOT mutate any state."
    PRD §3.3: "The projection variant rounds up to a whole number the
    count of cycles inclusive of the partial cycle the caller asked about
    (so a date partway through a grace cycle is treated as having entered
    the next cycle) and applies the final floor only at the very end of
    the projection rather than per cycle."

    Setup: principal=30000 due_date=2026-01-01; clock at 2026-01-10
    (within grace, no actual fee). Ask projected-balance at as_of=2026-02-01.
    Forward-looking: ceil(31/15)=3 cycles, total=3*(2500+3000)=16500.
    After the GET, Assessment.late_fee_cents must still be 0 and version
    must be unchanged.

    Design: Corner/endpoints/projected_balance_endpoint_does_not_mutate_assessment
    """
    _community, owner, prop = bootstrap_tenant(
        community_name="ProjOnly", owner_email="po@x.com", owner_name="PO",
        unit_label="PO-1",
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=30000,
        due_date="2026-01-01T00:00:00Z",
    )
    v_before = a["version"]
    set_clock("2026-01-10T00:00:00Z")
    resp = api.get_projected_balance(
        a["id"], "2026-02-01T00:00:00Z", make_homeowner_headers(owner["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["projected_late_fee_cents"] == 16500, (
        f"forward-looking projection must be 16500, "
        f"got {data['projected_late_fee_cents']}"
    )
    a_after = validate_success(
        api.get_assessment(a["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert a_after["late_fee_cents"] == 0, (
        "projected-balance GET must NOT set Assessment.late_fee_cents"
    )
    assert a_after["version"] == v_before, (
        "projected-balance GET must NOT advance Assessment.version"
    )
