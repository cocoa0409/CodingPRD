"""Case service-level deadlines: provisional vs final variants, nested-min effective
window, and strict SLA-breach boundary."""
import pytest
from test_helpers import (
    validate_success,
    new_representative, new_constituent, new_template, new_case, triage, set_clock,
    make_constituent_headers,
    TEST_USERS,
)

CASEWORKER = TEST_USERS["caseworker_headers"]


# --- Difficulty: dual_variant_calc / deadline_provisional_vs_final ---

def test_provisional_deadline_at_intake(api):
    """PRD §3.3: "`provisional_due_at` is the case's `created_at` advanced by the
    default window for its category, where the default window in hours is 168 for
    `IMMIGRATION`, 120 for `HEALTHCARE`, 120 for `HOUSING`, 72 for `TAX`, 96 for
    `BENEFITS`, and 168 for `OTHER`."

    Design: Difficulty/dual_variant_calc/deadline_provisional_vs_final
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"], data_sharing_consent=True)
    case = new_case(api, con["id"], category="HEALTHCARE")
    # created at the startup-default clock 2026-03-01T00:00:00Z; +120h = 2026-03-06.
    assert case["provisional_due_at"] == "2026-03-06T00:00:00.000Z", \
        f"unexpected provisional_due_at {case['provisional_due_at']}"


def test_final_deadline_at_triage(api):
    """PRD §3.3: "the system first multiplies the window by the multiplier, then adds
    the surcharge, then takes the lesser of that sum and 720, and rounds the result
    to two decimal places using round-half-up."
    PRD §3.3: "`final_due_at` is set to `triaged_at` advanced by `effective_window_hours` hours."

    Design: Difficulty/dual_variant_calc/deadline_provisional_vs_final
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"], data_sharing_consent=True)
    tmpl = new_template(api, "HEALTHCARE", response_window_hours=100)
    case = new_case(api, con["id"], category="HEALTHCARE")
    set_clock(api, "2026-03-02T00:00:00Z")
    triaged = triage(api, case["id"], tmpl["id"], priority="HIGH")
    # 100 * 0.5 (HIGH) + 12 (HEALTHCARE surcharge) = 62; min(62, 720) = 62.
    assert triaged["effective_window_hours"] == pytest.approx(62, abs=0.01)
    assert triaged["final_due_at"] == "2026-03-04T14:00:00.000Z", \
        f"unexpected final_due_at {triaged['final_due_at']}"


# --- Difficulty: combinatorial_formula / deadline_effective_window_nested_min ---

def test_effective_window_nested_min(api):
    """PRD §3.3: "The priority multiplier is 1.5 for `LOW`, 1.0 for `NORMAL`, 0.5 for
    `HIGH`, and 0.25 for `URGENT`. The category surcharge in hours is 24 for
    `IMMIGRATION`, 12 for `HEALTHCARE`, 12 for `HOUSING`, and 0 for `TAX`, `BENEFITS`,
    and `OTHER`."

    Design: Difficulty/combinatorial_formula/deadline_effective_window_nested_min
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "IMMIGRATION", response_window_hours=200)
    case = new_case(api, con["id"], category="IMMIGRATION")
    triaged = triage(api, case["id"], tmpl["id"], priority="URGENT")
    # 200 * 0.25 (URGENT) + 24 (IMMIGRATION) = 74; min(74, 720) = 74.
    assert triaged["effective_window_hours"] == pytest.approx(74, abs=0.01)


def test_final_due_at_nested_min(api):
    """PRD §3.3: "`final_due_at` is set to `triaged_at` advanced by
    `effective_window_hours` hours."

    Design: Difficulty/combinatorial_formula/deadline_effective_window_nested_min
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "IMMIGRATION", response_window_hours=200)
    case = new_case(api, con["id"], category="IMMIGRATION")
    triaged = triage(api, case["id"], tmpl["id"], priority="URGENT")
    # triaged at the default clock 2026-03-01T00:00:00Z; +74h = 2026-03-04T02:00:00Z.
    assert triaged["final_due_at"] == "2026-03-04T02:00:00.000Z", \
        f"unexpected final_due_at {triaged['final_due_at']}"


# --- Difficulty: boundary_precision_check / sla_breach_strict_greater_than ---

def test_net_elapsed_at_window_boundary(api):
    """PRD §3.4: "The **net** figure, `net_elapsed_hours`, subtracts from the gross
    figure both the case's accumulated `cumulative_paused_hours` and any
    currently-open pause".

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "TAX", response_window_hours=48)
    case = new_case(api, con["id"], category="TAX")
    triaged = triage(api, case["id"], tmpl["id"], priority="NORMAL")
    assert triaged["effective_window_hours"] == pytest.approx(48, abs=0.01)
    set_clock(api, "2026-03-03T00:00:00Z")  # exactly 48h after triage, no pauses
    data = validate_success(api.get_case(case["id"], CASEWORKER))
    assert data["net_elapsed_hours"] == pytest.approx(48.00, abs=0.01)


def test_not_breached_at_exact_window(api):
    """PRD §3.4: "A case is `breached` when its rounded `net_elapsed_hours` is
    strictly greater than its `effective_window_hours`".

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "TAX", response_window_hours=48)
    case = new_case(api, con["id"], category="TAX")
    triage(api, case["id"], tmpl["id"], priority="NORMAL")
    set_clock(api, "2026-03-03T00:00:00Z")  # net == window == 48; strict > means no breach
    data = validate_success(api.get_case(case["id"], CASEWORKER))
    assert data["breached"] is False, "48h == window must not breach (strict greater-than)"


# --- Corner: calculations / provisional_deadline_tax_default_window ---

def test_provisional_deadline_tax_default_window(api):
    """PRD §3.3: "`provisional_due_at` is the case's `created_at` advanced by the
    default window for its category, where the default window in hours is 168 for
    `IMMIGRATION`, 120 for `HEALTHCARE`, 120 for `HOUSING`, 72 for `TAX`, 96 for
    `BENEFITS`, and 168 for `OTHER`."
    PRD §3.3: "On success the case is created in `status` `NEW` with `priority` `NORMAL`".

    Design: Corner/calculations/provisional_deadline_tax_default_window
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    case = new_case(api, con["id"], category="TAX")
    # +72h from default clock 2026-03-01T00:00:00Z.
    assert case["provisional_due_at"] == "2026-03-04T00:00:00.000Z"
    assert case["status"] == "NEW"
    assert case["priority"] == "NORMAL"


# --- Corner: calculations / net_elapsed_excludes_paused_interval ---

def test_net_elapsed_excludes_paused_interval(api):
    """PRD §3.4: "On resume, the number of hours between the current clock and
    `paused_since` is added to the case's running `cumulative_paused_hours`".
    PRD §3.4: "The **net** figure, `net_elapsed_hours`, subtracts from the gross
    figure both the case's accumulated `cumulative_paused_hours` and any
    currently-open pause".

    Design: Corner/calculations/net_elapsed_excludes_paused_interval
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "TAX", response_window_hours=100)
    case = new_case(api, con["id"], category="TAX")
    triage(api, case["id"], tmpl["id"], priority="NORMAL")  # triaged at 2026-03-01T00:00
    con_headers = make_constituent_headers(con["id"])

    set_clock(api, "2026-03-01T10:00:00Z")
    validate_success(api.request_info(case["id"], {}, CASEWORKER))
    set_clock(api, "2026-03-02T10:00:00Z")  # 24h pause
    validate_success(api.constituent_reply(case["id"], {}, con_headers))
    set_clock(api, "2026-03-03T00:00:00Z")  # 48h gross after triage

    data = validate_success(api.get_case(case["id"], CASEWORKER))
    assert data["gross_elapsed_hours"] == pytest.approx(48.00, abs=0.01)
    assert data["net_elapsed_hours"] == pytest.approx(24.00, abs=0.01)
    assert data["cumulative_paused_hours"] == pytest.approx(24.00, abs=0.01)
