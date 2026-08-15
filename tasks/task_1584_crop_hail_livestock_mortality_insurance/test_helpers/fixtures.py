"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints —
each test runs against a freshly restarted server with an empty database.
Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: Policyholder calls always use the acting Grower's id and
Adjuster calls always use the acting Adjuster's id (PRD §2.1 — both roles are
entity-backed).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_acreage_report_payload,
    create_adjuster_payload,
    create_assign_adjuster_payload,
    create_carrier_payload,
    create_crop_hail_rate_payload,
    create_crop_hail_unit_payload,
    create_determination_payload,
    create_dual_coverage_link_payload,
    create_federal_crop_policy_payload,
    create_grower_payload,
    create_hail_claim_payload,
    create_hail_inspection_payload,
    create_head_report_payload,
    create_indemnity_payment_payload,
    create_livestock_claim_payload,
    create_livestock_inspection_payload,
    create_livestock_rate_payload,
    create_livestock_unit_payload,
    create_policy_payload,
    create_premium_payment_payload,
    create_renewal_payload,
    create_veterinary_report_payload,
)
from .test_users import TEST_USERS, make_adjuster_headers, make_policyholder_headers

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
APPROVER = TEST_USERS["claims_approver_headers"]

DEFAULT_RATE = 333  # premium cents per 100 cents of liability
STANDARD_EFFECTIVE = "2026-08-02T00:00:00Z"
STANDARD_EXPIRATION = "2026-12-31T00:00:00Z"
ACTIVATE_CLOCK = "2026-08-03T00:00:00Z"
STANDARD_LOSS_DATE = "2026-08-04T00:00:00Z"


# ─── Tier 1: single-resource creation and transitions ───────────────────────

def create_carrier(**overrides) -> dict:
    """Create a carrier. Its logical clock starts at 2026-08-01T00:00:00Z (PRD §2.5)."""
    res = api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    return get_success_data(res)


def set_clock(carrier_id: str, to_iso8601: str) -> dict:
    """Advance the carrier logical clock (Underwriter-only; triggers automatic
    time-driven transitions per PRD §2.5)."""
    res = api_client.set_clock(carrier_id, {"to_iso8601": to_iso8601}, UW)
    return get_success_data(res)


def create_grower(carrier_id: str, **overrides) -> dict:
    res = api_client.create_grower(carrier_id, create_grower_payload(**overrides), UW)
    return get_success_data(res)


def create_adjuster(carrier_id: str, **overrides) -> dict:
    res = api_client.create_adjuster(carrier_id, create_adjuster_payload(**overrides), UW)
    return get_success_data(res)


def create_rate_row(carrier_id: str, kind: str = "CROP_HAIL", **overrides) -> dict:
    """Create a DRAFT rate-table row (not yet published)."""
    if kind == "CROP_HAIL":
        payload = create_crop_hail_rate_payload(**overrides)
    else:
        payload = create_livestock_rate_payload(**overrides)
    res = api_client.create_rate_table(carrier_id, payload, UW)
    return get_success_data(res)


def publish_rate(carrier_id: str, rate_table_id: str) -> dict:
    res = api_client.publish_rate_table(carrier_id, rate_table_id, UW)
    return get_success_data(res)


def create_published_rate(carrier_id: str, kind: str = "CROP_HAIL", **overrides) -> dict:
    """Create + publish a rate-table row. Returns the PUBLISHED row."""
    row = create_rate_row(carrier_id, kind, **overrides)
    return publish_rate(carrier_id, row["id"])


def create_federal_policy(carrier_id: str, grower_id: str, **overrides) -> dict:
    res = api_client.create_federal_crop_policy(
        carrier_id, create_federal_crop_policy_payload(grower_id, **overrides), UW
    )
    return get_success_data(res)


def create_policy_application(carrier_id: str, grower_id: str,
                              kind: str = "CROP_HAIL", **overrides) -> dict:
    """Create a policy application (APPLICATION / UNBILLED / OPEN)."""
    res = api_client.create_policy(
        carrier_id, create_policy_payload(grower_id, kind, **overrides), UW
    )
    return get_success_data(res)


def add_coverage_unit(carrier_id: str, policy_id: str, kind: str = "CROP_HAIL",
                      **overrides) -> dict:
    if kind == "CROP_HAIL":
        payload = create_crop_hail_unit_payload(**overrides)
    else:
        payload = create_livestock_unit_payload(**overrides)
    res = api_client.create_coverage_unit(carrier_id, policy_id, payload, UW)
    return get_success_data(res)


def bind_policy(carrier_id: str, policy_id: str) -> dict:
    res = api_client.bind_policy(carrier_id, policy_id, UW)
    return get_success_data(res)


def pay_premium(carrier_id: str, policy_id: str, grower_id: str, amount_cents: int) -> dict:
    res = api_client.create_premium_payment(
        carrier_id, policy_id, create_premium_payment_payload(amount_cents),
        make_policyholder_headers(grower_id),
    )
    return get_success_data(res)


def read_policy(carrier_id: str, policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(carrier_id, policy_id, UW))


def read_grower(carrier_id: str, grower_id: str) -> dict:
    return get_success_data(api_client.get_grower(carrier_id, grower_id, UW))


def read_claim(carrier_id: str, policy_id: str, claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(carrier_id, policy_id, claim_id, UW))


def read_unit(carrier_id: str, policy_id: str, unit_id: str) -> dict:
    return get_success_data(api_client.get_coverage_unit(carrier_id, policy_id, unit_id, UW))


# ─── Tier 2: bound / active policy scenarios ────────────────────────────────

def setup_bound_crop_hail_policy(acres_list=(10,), rate=DEFAULT_RATE,
                                 effective_date=STANDARD_EFFECTIVE,
                                 expiration_date=STANDARD_EXPIRATION,
                                 carrier_overrides=None,
                                 policy_overrides=None) -> dict:
    """Carrier + grower + PUBLISHED crop-hail rate + policy with one unit per
    entry of acres_list, bound. Returns a context dict."""
    carrier = create_carrier(**(carrier_overrides or {}))
    cid = carrier["id"]
    grower = create_grower(cid)
    create_published_rate(cid, "CROP_HAIL", rate_per_100_cents_of_liability=rate)
    pkw = {"effective_date": effective_date, "expiration_date": expiration_date}
    pkw.update(policy_overrides or {})
    policy = create_policy_application(cid, grower["id"], "CROP_HAIL", **pkw)
    units = [
        add_coverage_unit(cid, policy["id"], "CROP_HAIL", declared_acres=a)
        for a in acres_list
    ]
    bound = bind_policy(cid, policy["id"])
    return {
        "carrier": carrier, "grower": grower, "policy": bound, "units": units,
        "carrier_id": cid, "grower_id": grower["id"], "policy_id": bound["id"],
    }


def setup_active_paid_crop_hail_policy(acres_list=(10,), rate=DEFAULT_RATE,
                                       effective_date=STANDARD_EFFECTIVE,
                                       expiration_date=STANDARD_EXPIRATION,
                                       activate_clock=ACTIVATE_CLOCK,
                                       **kwargs) -> dict:
    """Bound crop-hail policy, premium paid in full, clock advanced so the
    policy is ACTIVE. Returns the context dict."""
    ctx = setup_bound_crop_hail_policy(
        acres_list=acres_list, rate=rate, effective_date=effective_date,
        expiration_date=expiration_date, **kwargs,
    )
    premium = ctx["policy"]["premium_cents"]
    pay_premium(ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"], premium)
    if activate_clock is not None:
        set_clock(ctx["carrier_id"], activate_clock)
        ctx["policy"] = read_policy(ctx["carrier_id"], ctx["policy_id"])
    return ctx


def setup_active_paid_livestock_policy(head_count=10, per_head_value=200_000,
                                       band_floor=150_000, band_ceiling=250_000,
                                       rate=400, species="CATTLE",
                                       effective_date="2026-08-02T00:00:00Z",
                                       expiration_date="2027-08-02T00:00:00Z",
                                       activate_clock=ACTIVATE_CLOCK,
                                       adjuster_species=None,
                                       carrier_overrides=None) -> dict:
    """Carrier + grower + qualified adjuster + PUBLISHED livestock rate +
    bound, fully paid, ACTIVE livestock policy with one unit."""
    carrier = create_carrier(**(carrier_overrides or {}))
    cid = carrier["id"]
    grower = create_grower(cid)
    adjuster = create_adjuster(
        cid, species_qualified=(adjuster_species or [species])
    )
    create_published_rate(
        cid, "LIVESTOCK_MORTALITY", species=species,
        value_band_floor_cents=band_floor, value_band_ceiling_cents=band_ceiling,
        rate_per_100_cents_of_liability=rate,
    )
    policy = create_policy_application(
        cid, grower["id"], "LIVESTOCK_MORTALITY",
        effective_date=effective_date, expiration_date=expiration_date,
    )
    unit = add_coverage_unit(
        cid, policy["id"], "LIVESTOCK_MORTALITY", species=species,
        declared_head_count=head_count, per_head_value_cents=per_head_value,
    )
    bound = bind_policy(cid, policy["id"])
    pay_premium(cid, policy["id"], grower["id"], bound["premium_cents"])
    if activate_clock is not None:
        set_clock(cid, activate_clock)
        bound = read_policy(cid, policy["id"])
    return {
        "carrier": carrier, "grower": grower, "adjuster": adjuster,
        "policy": bound, "units": [unit],
        "carrier_id": cid, "grower_id": grower["id"], "policy_id": bound["id"],
        "adjuster_id": adjuster["id"],
    }


# ─── Tier 3: reports and claim lifecycle shortcuts ──────────────────────────

def submit_planting_report(carrier_id: str, policy_id: str, unit_id: str,
                           grower_id: str, reported_acres: int = 10) -> dict:
    res = api_client.create_acreage_report(
        carrier_id, policy_id, unit_id,
        create_acreage_report_payload(report_kind="PLANTING", reported_acres=reported_acres),
        make_policyholder_headers(grower_id),
    )
    return get_success_data(res)


def submit_initial_head_report(carrier_id: str, policy_id: str, unit_id: str,
                               grower_id: str, reported_head_count: int = 10) -> dict:
    res = api_client.create_head_report(
        carrier_id, policy_id, unit_id,
        create_head_report_payload(report_kind="INITIAL",
                                   reported_head_count=reported_head_count),
        make_policyholder_headers(grower_id),
    )
    return get_success_data(res)


def file_hail_claim(carrier_id: str, policy_id: str, grower_id: str, unit_id: str,
                    loss_date: str = STANDARD_LOSS_DATE,
                    percent_damage_estimate_pct: int = 10) -> dict:
    res = api_client.create_claim(
        carrier_id, policy_id,
        create_hail_claim_payload(
            unit_id, loss_date=loss_date,
            percent_damage_estimate_pct=percent_damage_estimate_pct,
        ),
        make_policyholder_headers(grower_id),
    )
    return get_success_data(res)


def file_livestock_claim(carrier_id: str, policy_id: str, grower_id: str, unit_id: str,
                         loss_date: str = STANDARD_LOSS_DATE,
                         appraisal_value_cents: int = 100_000,
                         deceased_head_count: int = 1) -> dict:
    res = api_client.create_claim(
        carrier_id, policy_id,
        create_livestock_claim_payload(
            unit_id, loss_date=loss_date,
            appraisal_value_cents=appraisal_value_cents,
            deceased_head_count=deceased_head_count,
        ),
        make_policyholder_headers(grower_id),
    )
    return get_success_data(res)


def assign_adjuster(carrier_id: str, policy_id: str, claim_id: str,
                    adjuster_id: str) -> dict:
    res = api_client.assign_adjuster(
        carrier_id, policy_id, claim_id,
        create_assign_adjuster_payload(adjuster_id), APPROVER,
    )
    return get_success_data(res)


def submit_hail_inspection(carrier_id: str, policy_id: str, claim_id: str,
                           adjuster_id: str, observed_percent_damage_pct: int = 10,
                           scheduled_for: str = "2026-08-04T12:00:00Z") -> dict:
    res = api_client.create_field_inspection(
        carrier_id, policy_id, claim_id,
        create_hail_inspection_payload(
            adjuster_id, scheduled_for=scheduled_for,
            observed_percent_damage_pct=observed_percent_damage_pct,
        ),
        make_adjuster_headers(adjuster_id),
    )
    return get_success_data(res)


def submit_livestock_inspection(carrier_id: str, policy_id: str, claim_id: str,
                                adjuster_id: str, observed_appraisal_cents: int = 95_000,
                                observed_deceased_count: int = 1,
                                scheduled_for: str = "2026-08-04T12:00:00Z") -> dict:
    res = api_client.create_field_inspection(
        carrier_id, policy_id, claim_id,
        create_livestock_inspection_payload(
            adjuster_id, scheduled_for=scheduled_for,
            observed_appraisal_cents=observed_appraisal_cents,
            observed_deceased_count=observed_deceased_count,
        ),
        make_adjuster_headers(adjuster_id),
    )
    return get_success_data(res)


def submit_claim_for_review(carrier_id: str, policy_id: str, claim_id: str,
                            adjuster_id: str) -> dict:
    res = api_client.submit_for_review(
        carrier_id, policy_id, claim_id, make_adjuster_headers(adjuster_id)
    )
    return get_success_data(res)


def issue_determination(carrier_id: str, policy_id: str, claim_id: str,
                        decision: str, approved_indemnity_cents: int,
                        expected_policy_version: int, approver_headers=None,
                        **extra):
    """POST a loss determination. Returns the raw Response (callers validate
    success or error themselves)."""
    headers = approver_headers or APPROVER
    payload = create_determination_payload(
        decision, approved_indemnity_cents, expected_policy_version, **extra
    )
    return api_client.create_determination(carrier_id, policy_id, claim_id, payload, headers)


def approve_claim(carrier_id: str, policy_id: str, claim_id: str,
                  approved_indemnity_cents: int, decision: str = "APPROVE") -> dict:
    """Issue an APPROVE/PARTIAL determination with the policy's current version."""
    version = read_policy(carrier_id, policy_id)["version"]
    res = issue_determination(
        carrier_id, policy_id, claim_id, decision, approved_indemnity_cents, version
    )
    return get_success_data(res)


# ─── Tier 4: full claim-cycle drivers ───────────────────────────────────────

def drive_hail_claim_to_under_review(carrier_id: str, policy_id: str, grower_id: str,
                                     unit_id: str, adjuster_id: str,
                                     loss_date: str = STANDARD_LOSS_DATE,
                                     percent_damage_estimate_pct: int = 10,
                                     observed_percent_damage_pct: int = 10) -> dict:
    """File a hail claim against a REPORTED unit and walk it
    REPORTED -> INSPECTION_SCHEDULED -> INSPECTED -> UNDER_REVIEW.
    Returns the claim dict in UNDER_REVIEW."""
    claim = file_hail_claim(
        carrier_id, policy_id, grower_id, unit_id,
        loss_date=loss_date, percent_damage_estimate_pct=percent_damage_estimate_pct,
    )
    assign_adjuster(carrier_id, policy_id, claim["id"], adjuster_id)
    submit_hail_inspection(
        carrier_id, policy_id, claim["id"], adjuster_id,
        observed_percent_damage_pct=observed_percent_damage_pct,
    )
    return submit_claim_for_review(carrier_id, policy_id, claim["id"], adjuster_id)


def drive_livestock_claim_to_under_review(carrier_id: str, policy_id: str, grower_id: str,
                                          unit_id: str, adjuster_id: str,
                                          loss_date: str = STANDARD_LOSS_DATE,
                                          appraisal_value_cents: int = 100_000,
                                          deceased_head_count: int = 1,
                                          observed_appraisal_cents: int = 95_000,
                                          observed_deceased_count: int = 1) -> dict:
    """File a livestock claim against a REPORTED unit and walk it to
    UNDER_REVIEW. Caller must pre-satisfy the necropsy gate when the claimed
    appraisal exceeds $5,000 (500,000 cents)."""
    claim = file_livestock_claim(
        carrier_id, policy_id, grower_id, unit_id, loss_date=loss_date,
        appraisal_value_cents=appraisal_value_cents,
        deceased_head_count=deceased_head_count,
    )
    assign_adjuster(carrier_id, policy_id, claim["id"], adjuster_id)
    submit_livestock_inspection(
        carrier_id, policy_id, claim["id"], adjuster_id,
        observed_appraisal_cents=observed_appraisal_cents,
        observed_deceased_count=observed_deceased_count,
    )
    return submit_claim_for_review(carrier_id, policy_id, claim["id"], adjuster_id)


def file_and_approve_hail_claim(carrier_id: str, policy_id: str, grower_id: str,
                                unit_id: str, adjuster_id: str,
                                approved_indemnity_cents: int,
                                loss_date: str = STANDARD_LOSS_DATE,
                                observed_percent_damage_pct: int = 10) -> dict:
    """Full cycle: file hail claim -> inspect -> review -> APPROVE.
    Increments the grower's prior_claims_count by one (PRD §3.8)."""
    claim = drive_hail_claim_to_under_review(
        carrier_id, policy_id, grower_id, unit_id, adjuster_id,
        loss_date=loss_date, observed_percent_damage_pct=observed_percent_damage_pct,
    )
    determination = approve_claim(
        carrier_id, policy_id, claim["id"], approved_indemnity_cents
    )
    return {"claim": read_claim(carrier_id, policy_id, claim["id"]),
            "determination": determination}


def setup_hail_claim_under_review(acres=10, rate=DEFAULT_RATE,
                                  observed_percent_damage_pct: int = 10,
                                  adjuster_overrides=None) -> dict:
    """ACTIVE+PAID crop-hail policy (one unit, timely planting report) with a
    claim walked to UNDER_REVIEW. Returns a context dict."""
    ctx = setup_active_paid_crop_hail_policy(acres_list=(acres,), rate=rate)
    cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
    adjuster = create_adjuster(cid, **(adjuster_overrides or {}))
    submit_planting_report(cid, pid, ctx["units"][0]["id"], gid,
                           reported_acres=acres)
    claim = drive_hail_claim_to_under_review(
        cid, pid, gid, ctx["units"][0]["id"], adjuster["id"],
        observed_percent_damage_pct=observed_percent_damage_pct,
    )
    ctx.update({"adjuster": adjuster, "adjuster_id": adjuster["id"], "claim": claim})
    return ctx


def setup_livestock_claim_under_review(head_count=10, per_head_value=200_000,
                                       appraisal_value_cents=100_000,
                                       deceased_head_count=1,
                                       observed_appraisal_cents=95_000,
                                       observed_deceased_count=1,
                                       adjuster_overrides=None,
                                       **policy_kwargs) -> dict:
    """ACTIVE+PAID livestock policy with a timely INITIAL head report and a
    claim walked to UNDER_REVIEW (no veterinary reports submitted)."""
    ctx = setup_active_paid_livestock_policy(
        head_count=head_count, per_head_value=per_head_value, **policy_kwargs
    )
    cid, pid, gid = ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"]
    if adjuster_overrides:
        adjuster = create_adjuster(cid, **adjuster_overrides)
        ctx["adjuster"] = adjuster
        ctx["adjuster_id"] = adjuster["id"]
    unit = ctx["units"][0]
    submit_initial_head_report(cid, pid, unit["id"], gid,
                               reported_head_count=head_count)
    claim = drive_livestock_claim_to_under_review(
        cid, pid, gid, unit["id"], ctx["adjuster_id"],
        appraisal_value_cents=appraisal_value_cents,
        deceased_head_count=deceased_head_count,
        observed_appraisal_cents=observed_appraisal_cents,
        observed_deceased_count=observed_deceased_count,
    )
    ctx["claim"] = claim
    return ctx


# ─── Tier 5: renewal / expiration helpers ───────────────────────────────────

def expire_policy(carrier_id: str, policy_id: str, clock_to: str) -> dict:
    """Advance the clock past the policy's expiration_date so the policy moves
    ACTIVE -> EXPIRED (PRD §2.5). Returns the re-read policy."""
    set_clock(carrier_id, clock_to)
    return read_policy(carrier_id, policy_id)


def post_renewal(carrier_id: str, prior_policy_id: str, decision: str,
                 effective_date: str, expiration_date: str,
                 expected_prior_policy_version: int):
    """POST a renewal decision. Returns the raw Response."""
    return api_client.create_renewal(
        carrier_id, prior_policy_id,
        create_renewal_payload(
            decision, effective_date, expiration_date,
            expected_prior_policy_version,
        ),
        UW,
    )


def issue_payment(carrier_id: str, policy_id: str, claim_id: str,
                  payment_method: str = "ACH") -> dict:
    res = api_client.create_indemnity_payment(
        carrier_id, policy_id, claim_id,
        create_indemnity_payment_payload(payment_method=payment_method), APPROVER,
    )
    return get_success_data(res)


def link_dual_coverage(carrier_id: str, policy_id: str,
                       federal_crop_policy_id: str) -> dict:
    res = api_client.create_dual_coverage_link(
        carrier_id, policy_id,
        create_dual_coverage_link_payload(federal_crop_policy_id), UW,
    )
    return get_success_data(res)


def submit_veterinary_report(carrier_id: str, policy_id: str, claim_id: str,
                             grower_id: str, **overrides) -> dict:
    res = api_client.create_veterinary_report(
        carrier_id, policy_id, claim_id,
        create_veterinary_report_payload(**overrides),
        make_policyholder_headers(grower_id),
    )
    return get_success_data(res)
