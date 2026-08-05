"""Holder reports: per-line rounding of the remitted total, optimistic-concurrency
on attach, the reject/revise loop, per-(holder,state,year) uniqueness, and the
submit-time remittance and escheat-state gates.

Translates queue A (combinatorial_formula/report_total, non_linear_state_machine/
report_reject_revise_loop, resource_temporal_overlap/report_period_calendar_overlap)
and queue B (remittance mismatch, escheat mismatch, OCC stale/increment).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
)
from test_helpers.test_users import make_holder_headers, make_examiner_headers


def _two_interest_props_report(api):
    """Holder + AC01 (interest, no DD) + two DORMANT CA properties (100010, 100510),
    clock 2026-07-15, and a DRAFT CA report with property A already attached (version 2)."""
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="AC01", dormancy_basis="LAST_ACTIVITY",
                                       dormancy_period_years=3, interest_bearing=True)
    pa = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="A A", owner_last_known_state="CA",
        amount_cents=100010, last_activity_date="2020-01-01T00:00:00Z"), hh), 201)
    pc = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="C C", owner_last_known_state="CA",
        amount_cents=100510, last_activity_date="2020-01-01T00:00:00Z"), hh), 201)
    validate_success(api.evaluate_dormancy(pa["id"], hh), 200)
    validate_success(api.evaluate_dormancy(pc["id"], hh), 200)
    fixtures.set_clock(api, "2026-07-15T00:00:00Z")
    report = validate_success(api.create_report(
        f.create_report_payload(holder["id"], "CA", 2026), hh), 201)
    r1 = validate_success(api.add_property(
        report["id"], f.add_property_payload(pa["id"], report["version"]), hh), 200)
    return holder, hh, report, pa, pc, r1


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/report_total_round_per_line_then_sum
# ---------------------------------------------------------------------------
def test_report_total_rounds_each_property_first(api):
    """PRD §3.4: "A report's total_remitted_cents is defined as the sum, over every property
    currently attached to it ..., of that property's remittance amount rounded to whole cents
    first, then summed. Each property's remittance is rounded to cents individually before the
    summation; the total is never formed by summing raw un-rounded remittances and rounding
    once at the end, because the two can differ by a cent."

    Faces 100010 and 100510, interest-bearing, 3 dormant years: raw 106010.6 -> 106011 and
    106540.6 -> 106541; per-line sum is 212552 (not the round-once 212551).

    Design: Difficulty/combinatorial_formula/report_total_round_per_line_then_sum
    """
    holder, hh, report, pa, pc, r1 = _two_interest_props_report(api)
    r2 = validate_success(api.add_property(
        report["id"], f.add_property_payload(pc["id"], r1["version"]), hh), 200)
    assert r2["total_remitted_cents"] == 212552, \
        f"per-line-then-sum must be 212552, got {r2['total_remitted_cents']}"


def test_report_total_not_round_once_and_counts(api):
    """PRD §3.4: "the total is never formed by summing raw un-rounded remittances and rounding
    once at the end, because the two can differ by a cent."
    PRD §3.4: "The report's property_count is simply the number of properties currently attached."

    The forbidden round-once total would be 212551; per-line-then-sum is 212552, over 2 attached.

    Design: Difficulty/combinatorial_formula/report_total_round_per_line_then_sum
    """
    holder, hh, report, pa, pc, r1 = _two_interest_props_report(api)
    r2 = validate_success(api.add_property(
        report["id"], f.add_property_payload(pc["id"], r1["version"]), hh), 200)
    assert r2["total_remitted_cents"] != 212551, "must not use the round-once total 212551"
    assert r2["total_remitted_cents"] == 212552
    assert r2["property_count"] == 2


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/report_reject_revise_loop
# ---------------------------------------------------------------------------
def _report_under_audit(api):
    ctx = fixtures.setup_draft_report_with_property(api, dormancy_basis="ISSUANCE",
                                                    interest_bearing=False, amount_cents=50000)
    hh = ctx["holder_headers"]
    validate_success(api.submit_report(ctx["report_id"],
                     {"declared_total_cents": ctx["total_remitted_cents"]}, hh), 200)
    ex = make_examiner_headers()
    validate_success(api.begin_review(ctx["report_id"], ex), 200)
    return ctx, hh, ex


def test_report_reject_moves_to_rejected(api):
    """PRD §3.5: "From UNDER_AUDIT, the examiner either rejects the report — moving it to
    REJECTED — or accepts it."

    Design: Difficulty/non_linear_state_machine/report_reject_revise_loop
    """
    ctx, hh, ex = _report_under_audit(api)
    data = validate_success(api.reject_report(ctx["report_id"], ex), 200)
    assert data["status"] == "REJECTED", f"reject must yield REJECTED, got {data['status']}"


def test_report_revise_returns_rejected_to_draft(api):
    """PRD §3.5: "A REJECTED report is not terminal: the holder may return it from REJECTED to
    DRAFT to correct and refile it, forming a revise loop."

    Design: Difficulty/non_linear_state_machine/report_reject_revise_loop
    """
    ctx, hh, ex = _report_under_audit(api)
    validate_success(api.reject_report(ctx["report_id"], ex), 200)
    data = validate_success(api.revise_report(ctx["report_id"], hh), 200)
    assert data["status"] == "DRAFT", f"revise must return the report to DRAFT, got {data['status']}"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/report_period_calendar_overlap
# ---------------------------------------------------------------------------
def test_duplicate_report_period_rejected(api):
    """PRD §3.4: "At most one report may exist for a given combination of holder, jurisdiction,
    and year; a duplicate is rejected with ERR_REPORT_PERIOD_OVERLAP (HTTP 409)."

    A second report for the same (holder, CA, 2026) collides.

    Design: Difficulty/resource_temporal_overlap/report_period_calendar_overlap
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    validate_success(api.create_report(f.create_report_payload(holder["id"], "CA", 2026), hh), 201)
    validate_error(api.create_report(f.create_report_payload(holder["id"], "CA", 2026), hh),
                   ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value)


def test_report_different_year_same_holder_state_allowed(api):
    """PRD §3.4: "At most one report may exist for a given combination of holder, jurisdiction,
    and year; a duplicate is rejected with ERR_REPORT_PERIOD_OVERLAP (HTTP 409)."

    The uniqueness key is (holder, state, year): a second report for the same holder and CA but
    a different year (2027) does not collide and is created in DRAFT.

    Design: Difficulty/resource_temporal_overlap/report_period_calendar_overlap
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    validate_success(api.create_report(f.create_report_payload(holder["id"], "CA", 2026), hh), 201)
    data = validate_success(api.create_report(f.create_report_payload(holder["id"], "CA", 2027), hh), 201)
    assert data["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/cross_cutting/report_version_increments_on_successful_add
# ---------------------------------------------------------------------------
def test_add_property_increments_report_version(api):
    """PRD §2.9: "each successful attach recomputes the report's derived property_count and
    total_remitted_cents and bumps the report's version by one."
    PRD §3.4: "A successful attach transitions the property to REPORTED, sets its report_id to
    the report, increments the report's version by one, and recomputes the report's
    property_count and total_remitted_cents."

    Design: Corner/cross_cutting/report_version_increments_on_successful_add
    """
    ctx = fixtures.setup_draft_report_with_property(api, dormancy_basis="ISSUANCE",
                                                    interest_bearing=False, amount_cents=50000)
    report = validate_success(api.get_report(ctx["report_id"], ctx["holder_headers"]), 200)
    assert report["version"] == 2, f"version must be 2 after one add, got {report['version']}"
    assert report["property_count"] == 1
    assert report["total_remitted_cents"] == 50000


# ---------------------------------------------------------------------------
# Corner/cross_cutting/occ_stale_report_version_rejected
# ---------------------------------------------------------------------------
def test_add_property_stale_version_rejected(api):
    """PRD §2.9: "The attach request must carry expected_report_version bearing the version of
    the target HolderReport that the client last observed. If that value does not equal the
    report's current version, the request is rejected with ERR_STALE_REPORT_VERSION (HTTP 412),
    and no property is attached."

    After one add bumps the report to version 2, a second add still carrying version 1 is stale.

    Design: Corner/cross_cutting/occ_stale_report_version_rejected
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    pa = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="A", owner_last_known_state="CA", amount_cents=50000,
        last_activity_date="2020-01-01T00:00:00Z", issue_date="2020-01-01T00:00:00Z"), hh), 201)
    pb = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="B", owner_last_known_state="CA", amount_cents=60000,
        last_activity_date="2020-01-01T00:00:00Z", issue_date="2020-01-01T00:00:00Z"), hh), 201)
    validate_success(api.evaluate_dormancy(pa["id"], hh), 200)
    validate_success(api.evaluate_dormancy(pb["id"], hh), 200)
    report = validate_success(api.create_report(f.create_report_payload(holder["id"], "CA", 2026), hh), 201)
    v0 = report["version"]
    validate_success(api.add_property(report["id"], f.add_property_payload(pa["id"], v0), hh), 200)
    validate_error(api.add_property(report["id"], f.add_property_payload(pb["id"], v0), hh),
                   ApiErrorId.ERR_STALE_REPORT_VERSION.value)
    after = validate_success(api.get_report(report["id"], hh), 200)
    assert after["property_count"] == 1, "no property attached by the stale request"


# ---------------------------------------------------------------------------
# Corner/validations/add_property_escheat_mismatch_from_valid_state
# ---------------------------------------------------------------------------
def test_add_property_escheat_state_mismatch_rejected(api):
    """PRD §3.4 / §2.7: "the property's escheat_state must equal the report's report_state
    (else ERR_ESCHEAT_STATE_MISMATCH, HTTP 422, per Section 2.7)".

    A DORMANT property with escheat_state CA attached to an NV report is rejected; count stays 0.

    Design: Corner/validations/add_property_escheat_mismatch_from_valid_state
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_name="Jane", owner_last_known_state="CA", amount_cents=50000,
        last_activity_date="2020-01-01T00:00:00Z", issue_date="2020-01-01T00:00:00Z"), hh), 201)
    validate_success(api.evaluate_dormancy(prop["id"], hh), 200)
    report = validate_success(api.create_report(f.create_report_payload(holder["id"], "NV", 2026), hh), 201)
    validate_error(api.add_property(report["id"], f.add_property_payload(prop["id"], report["version"]), hh),
                   ApiErrorId.ERR_ESCHEAT_STATE_MISMATCH.value)
    after = validate_success(api.get_report(report["id"], hh), 200)
    assert after["property_count"] == 0


# ---------------------------------------------------------------------------
# Corner/validations/report_submit_wrong_total_returns_remittance_mismatch
# ---------------------------------------------------------------------------
def test_report_submit_wrong_declared_total_rejected(api):
    """PRD §3.4: "the submitted declared_total_cents must equal the report's computed
    total_remitted_cents; a mismatch is rejected with ERR_REMITTANCE_MISMATCH (HTTP 422)."

    Computed total is 50000; declaring 1 mismatches and the report stays DRAFT.

    Design: Corner/validations/report_submit_wrong_total_returns_remittance_mismatch
    """
    ctx = fixtures.setup_draft_report_with_property(api, dormancy_basis="ISSUANCE",
                                                    interest_bearing=False, amount_cents=50000)
    hh = ctx["holder_headers"]
    validate_error(api.submit_report(ctx["report_id"], {"declared_total_cents": 1}, hh),
                   ApiErrorId.ERR_REMITTANCE_MISMATCH.value)
    after = validate_success(api.get_report(ctx["report_id"], hh), 200)
    assert after["status"] == "DRAFT"
