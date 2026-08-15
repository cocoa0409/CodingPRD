"""Diversion reports: dual variants, per-event rounding, empty window,
SoD at certification, supersede cascade, cross-role denials."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_accept_drop,
    create_diversion_report_payload,
    create_drop_at_site,
    get_success_data,
    make_municipal_auditor_headers,
    make_participant_headers,
    make_processing_partner_headers,
    setup_closed_accepted_batch,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
AUDITOR = TEST_USERS["municipal_auditor_headers"]
AUD1 = make_municipal_auditor_headers("aud-1")
AUD2 = make_municipal_auditor_headers("aud-2")


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / diversion_report_provisional_vs_final_net
# (2 tests)
# ---------------------------------------------------------------------------

def _setup_reconciled_drop(api):
    """One drop 10.00/1.00 (provisional 9.00) reconciled by a batch closed
    with measured contamination 2.00 -> final_net 8.00, FINALLY_CREDITED."""
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)

    # occurred_at must satisfy both PRD §3.4 (not after the logical clock,
    # which starts at 2026-08-01T00:00:00Z) and the report period window
    # [period_start, period_end) of §3.8 — the default period starts at
    # 2026-08-01T00:00:00Z, so exactly the clock start qualifies.
    create_and_accept_drop(prog_id, site_id, part["part_id"], part["grant_id"],
                           mat_id, gross_weight_kg=10.00,
                           contamination_kg=1.00,
                           occurred_at="2026-08-01T00:00:00Z")
    chain = setup_closed_accepted_batch(
        prog_id, site_id, planned_pickup_kg=9, actual_pickup_kg=10.00,
        measured_contamination_kg=2.00, yield_ratio=0.5)
    return ids, part, chain


def test_provisional_and_final_variants_disagree_after_reconciliation(api):
    """PRD §3.8: "The `PROVISIONAL_NET` variant is the fast, unaudited number:
    it includes drops whose `verification_state` is `PENDING_AUDIT`,
    `ACCEPTED`, or `FLAGGED_CONTAMINATED` — `REJECTED` drops are excluded —
    and sums each drop's `provisional_net_kg`. The `FINAL_NET` variant is the
    certified year-end figure: it includes only drops whose `credit_state` is
    `FINALLY_CREDITED` and sums each drop's batch-reconciled `final_net_kg`."

    Design: Difficulty/dual_variant_calc/diversion_report_provisional_vs_final_net
    """
    ids, _part, _chain = _setup_reconciled_drop(api)
    prog_id = ids["prog_id"]

    rep_prov = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUDITOR), expected_status=201)
    rep_final = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="FINAL_NET"),
        AUDITOR), expected_status=201)

    assert rep_prov["net_diverted_kg"] == pytest.approx(9.00)
    assert rep_final["net_diverted_kg"] == pytest.approx(8.00)
    assert rep_prov["net_diverted_kg"] != rep_final["net_diverted_kg"]


def test_final_variant_rate_uses_batch_reconciled_net(api):
    """PRD §3.8: "`diversion_rate_pct` is `net_diverted_kg` divided by
    `gross_diverted_kg` and multiplied by 100, rounded half-up to two decimal
    places — or exactly 0 when the gross is 0."
    PRD §3.8: "Both variants draw from drop events in the program whose
    `occurred_at` falls within the period window, and both compute
    `gross_diverted_kg` as the sum of `gross_weight_kg` and `contamination_kg`
    as the sum of `contamination_kg` over the included set."

    Design: Difficulty/dual_variant_calc/diversion_report_provisional_vs_final_net
    """
    ids, _part, _chain = _setup_reconciled_drop(api)
    prog_id = ids["prog_id"]

    rep_final = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="FINAL_NET"),
        AUDITOR), expected_status=201)
    assert rep_final["gross_diverted_kg"] == pytest.approx(10.00)
    assert rep_final["diversion_rate_pct"] == pytest.approx(80.00)


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula /
#             diversion_nested_rounding_per_event_then_sum (2 tests)
# ---------------------------------------------------------------------------

def _setup_three_rounding_drops(api):
    """Three ACCEPTED drops engineered so per-event rounding before summation
    matters: 3.333-0.001=3.332->3.33 (x2), 3.334-0.002=3.332->3.33."""
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)

    specs = [(3.333, 0.001, "2026-08-01T00:00:00Z"),
             (3.333, 0.001, "2026-08-01T00:00:00Z"),
             (3.334, 0.002, "2026-08-01T00:00:00Z")]
    for gross, contam, occurred in specs:
        create_and_accept_drop(prog_id, site_id, part["part_id"],
                               part["grant_id"], mat_id,
                               gross_weight_kg=gross, contamination_kg=contam,
                               occurred_at=occurred)
    return ids


def test_report_rounds_each_event_before_summing(api):
    """PRD §3.8: "The per-event rounding order is pinned: each event's net
    value is rounded half-up to two decimal places first, and the rounded
    per-event values are then summed into `net_diverted_kg`."
    PRD §3.4: "the drop's `provisional_net_kg` is computed as
    `gross_weight_kg` minus `contamination_kg`, rounded half-up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/diversion_nested_rounding_per_event_then_sum
    """
    ids = _setup_three_rounding_drops(api)

    rep = validate_success(api.create_diversion_report(
        ids["prog_id"], create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUDITOR), expected_status=201)
    assert rep["net_diverted_kg"] == pytest.approx(9.99), (
        f"per-event-then-sum must yield 3.33+3.33+3.33=9.99, got "
        f"{rep['net_diverted_kg']}")


def test_report_sums_gross_and_contamination_over_included_set(api):
    """PRD §3.8: "both compute `gross_diverted_kg` as the sum of
    `gross_weight_kg` and `contamination_kg` as the sum of `contamination_kg`
    over the included set."
    PRD §3.8: "`diversion_rate_pct` is `net_diverted_kg` divided by
    `gross_diverted_kg` and multiplied by 100, rounded half-up to two decimal
    places"

    Design: Difficulty/combinatorial_formula/diversion_nested_rounding_per_event_then_sum
    """
    ids = _setup_three_rounding_drops(api)

    rep = validate_success(api.create_diversion_report(
        ids["prog_id"], create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUDITOR), expected_status=201)
    assert rep["gross_diverted_kg"] == pytest.approx(10.00)
    # PRD §3.8 pins contamination_kg as the plain sum over the included set
    # (0.001+0.001+0.002); §2.6's 0.01 rounding is invoked only for
    # net_diverted_kg (per-event-then-sum) and diversion_rate_pct, so accept
    # either the raw or the rounded presentation of the sum.
    assert rep["contamination_kg"] in (
        pytest.approx(0.004), pytest.approx(0.00)), (
        f"contamination_kg must be the sum over the included set, got "
        f"{rep['contamination_kg']}")
    assert rep["diversion_rate_pct"] == pytest.approx(99.90)


# ---------------------------------------------------------------------------
# Corner: calculations/diversion_report_empty_window_zero_division (1 test)
# ---------------------------------------------------------------------------

def test_empty_window_report_has_zero_gross_and_zero_rate(api):
    """PRD §3.8: "`diversion_rate_pct` is `net_diverted_kg` divided by
    `gross_diverted_kg` and multiplied by 100, rounded half-up to two decimal
    places — or exactly 0 when the gross is 0."

    Design: Corner/calculations/diversion_report_empty_window_zero_division
    """
    ids = setup_program_with_operational_site()

    rep = validate_success(api.create_diversion_report(
        ids["prog_id"], create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUDITOR), expected_status=201)
    assert rep["gross_diverted_kg"] == pytest.approx(0)
    assert rep["diversion_rate_pct"] == pytest.approx(0)


# ---------------------------------------------------------------------------
# Corner: validations/sod_same_user_certify_blocked (1 test)
# ---------------------------------------------------------------------------

def test_self_certification_rejected_different_auditor_allowed(api):
    """PRD §3.8: "Certifying a report moves it from `DRAFT` to `CERTIFIED` and
    requires the certifying auditor's `X-User-ID` to differ from the id that
    created the report — the creator's id is captured from the caller at
    report creation time — failing with `ERR_SOD_SAME_USER` (HTTP 403) on a
    self-certification"
    PRD §3.8: "it also requires the report's `period_end` to be at or before
    the current logical clock"

    Design: Corner/validations/sod_same_user_certify_blocked
    """
    ids = setup_program_with_operational_site()
    prog_id = ids["prog_id"]
    # Move clock past period_end so certification is allowed on the time axis
    get_success_data(api.set_clock("2026-09-02T00:00:00Z", ADMIN))

    rep = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUD1), expected_status=201)

    resp_self = api.certify_diversion_report(prog_id, rep["id"], AUD1)
    validate_error(resp_self, ApiErrorId.ERR_SOD_SAME_USER)

    certified = validate_success(api.certify_diversion_report(
        prog_id, rep["id"], AUD2))
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by"] == "aud-2"


# ---------------------------------------------------------------------------
# Corner: validations/participant_cannot_certify_diversion_report (1 test)
# ---------------------------------------------------------------------------

def test_participant_cannot_certify_diversion_report(api):
    """PRD §2.1: "If the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §4: POST /programs/{id}/diversion-reports/{reportId}/certify is
    authorized for MunicipalAuditor only.

    Design: Corner/validations/participant_cannot_certify_diversion_report
    """
    ids = setup_program_with_operational_site()
    prog_id = ids["prog_id"]
    rep = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUDITOR), expected_status=201)
    part = setup_verified_participant_with_grant(prog_id, ids["site_id"])

    resp = api.certify_diversion_report(
        prog_id, rep["id"], make_participant_headers(part["part_id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


# ---------------------------------------------------------------------------
# Corner: endpoints/supersede_replaces_certified_report (1 test)
# ---------------------------------------------------------------------------

def test_certifying_duplicate_period_method_supersedes_prior_report(api):
    """PRD §3.8: "Certification also supersedes: when a new report with an
    identical period start, period end, and method is certified, any
    previously `CERTIFIED` report with that same period and method
    automatically transitions to `SUPERSEDED`."

    Design: Corner/endpoints/supersede_replaces_certified_report
    """
    ids = setup_program_with_operational_site()
    prog_id = ids["prog_id"]
    get_success_data(api.set_clock("2026-09-02T00:00:00Z", ADMIN))

    r1 = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUD1), expected_status=201)
    get_success_data(api.certify_diversion_report(prog_id, r1["id"], AUD2))

    r2 = validate_success(api.create_diversion_report(
        prog_id, create_diversion_report_payload(method="PROVISIONAL_NET"),
        AUD1), expected_status=201)
    get_success_data(api.certify_diversion_report(prog_id, r2["id"], AUD2))

    r1_after = validate_success(api.get_diversion_report(prog_id, r1["id"],
                                                         AUDITOR))
    assert r1_after["status"] == "SUPERSEDED"
