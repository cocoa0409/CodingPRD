"""
Composite setup helpers.

The harness restarts the service before every individual test, so each test
begins against an empty database with the logical clock at its
2026-08-01T00:00:00Z default (PRD §2.5). Everything a test needs must therefore
be built here through PRD-declared endpoints only.

Every GroundTenant call below is made with the real `Lessee.id` as `X-User-ID`,
because §2.1 makes the tenant's identity entity-backed.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    make_accountant_headers,
    make_arbitrator_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
)


def set_clock(api, current_utc):
    """PRD §2.5: the service keeps a logical clock settable by the harness."""
    return get_success_data(api.set_clock(current_utc, make_lessor_admin_headers()))


def create_lessee(api, **overrides):
    return get_success_data(
        api.create_lessee(f.lessee_payload(**overrides), make_lessor_admin_headers())
    )


def create_lease(api, lessee_id, premises_code, **overrides):
    return get_success_data(
        api.create_lease(
            f.lease_payload(lessee_id, premises_code, **overrides),
            make_lessor_admin_headers(),
        )
    )


def standard_lease(api, premises_code="PIER-40-A", lessee_overrides=None, **lease_overrides):
    """One Lessee plus one Lease on an empty DB — the standard fixture the two
    design indices assume, with premises_code varied so nothing collides."""
    lessee = create_lessee(api, **(lessee_overrides or {}))
    lease = create_lease(api, lessee["id"], premises_code, **lease_overrides)
    return {
        "lessee": lessee,
        "lessee_id": lessee["id"],
        "lease": lease,
        "lease_id": lease["id"],
        "tenant": make_ground_tenant_headers(lessee["id"]),
    }


def read_lease(api, lease_id, headers=None):
    return get_success_data(
        api.get_lease(lease_id, headers or make_lessor_admin_headers())
    )


def lease_version(api, lease_id, headers=None):
    """Re-read the lease so a version-pinned write carries a fresh value
    (PRD §2.7: both pinned writes themselves increment the lease version)."""
    return read_lease(api, lease_id, headers)["version"]


def add_arrears(api, lease_id, amount_cents=1000000, user_id="acct-1"):
    return get_success_data(
        api.post_rent_charge(
            lease_id, f.rent_charge_payload(amount_cents), make_accountant_headers(user_id)
        )
    )


def file_insurance(api, lease_id, **overrides):
    return get_success_data(
        api.file_insurance_endorsement(
            lease_id, f.insurance_payload(**overrides), make_lessor_admin_headers()
        )
    )


def record_senior_mortgage(api, lease_id, **overrides):
    return get_success_data(
        api.record_mortgage(
            lease_id, f.senior_mortgage_payload(**overrides), make_lessor_admin_headers()
        )
    )


def record_mezz_mortgage(api, lease_id, **overrides):
    return get_success_data(
        api.record_mortgage(
            lease_id, f.mezz_mortgage_payload(**overrides), make_lessor_admin_headers()
        )
    )


def open_revaluation(api, lease_id, valuation_date="2027-06-01T00:00:00Z"):
    return get_success_data(
        api.open_revaluation(
            lease_id, f.revaluation_payload(valuation_date), make_lessor_admin_headers()
        )
    )


def lodge_both_appraisals(api, revaluation_id, lessee_id,
                          lessor_cents=14000000, lessee_cents=10000000,
                          lessor_method="COMPARABLE_LAND", lessee_method="INCOME_CAP",
                          appraiser_user_id="appraiser-lessor-1"):
    """§2.1: a LESSOR-side appraisal must be lodged by the lessor's appointee and
    a LESSEE-side one by the tenant, or ERR_APPRAISAL_SIDE_MISMATCH bites."""
    lessor_row = get_success_data(
        api.lodge_appraisal(
            revaluation_id,
            f.appraisal_payload("LESSOR", lessor_cents, lessor_method),
            make_lessor_admin_headers(appraiser_user_id),
        )
    )
    lessee_row = get_success_data(
        api.lodge_appraisal(
            revaluation_id,
            f.appraisal_payload("LESSEE", lessee_cents, lessee_method),
            make_ground_tenant_headers(lessee_id),
        )
    )
    return lessor_row, lessee_row


def exchanged_revaluation(api, lease_id, lessee_id,
                          valuation_date="2027-06-01T00:00:00Z",
                          lessor_cents=14000000, lessee_cents=10000000):
    """Walk a revaluation to PROPOSALS_EXCHANGED: open, lodge both sides, exchange."""
    reval = open_revaluation(api, lease_id, valuation_date)
    lodge_both_appraisals(api, reval["id"], lessee_id, lessor_cents, lessee_cents)
    return get_success_data(
        api.exchange_proposals(reval["id"], make_lessor_admin_headers())
    )


def referred_revaluation(api, lease_id, lessee_id,
                         arbitrator_user_id="arb-neutral-1",
                         valuation_date="2027-06-01T00:00:00Z",
                         lessor_cents=14000000, lessee_cents=10000000):
    reval = exchanged_revaluation(
        api, lease_id, lessee_id, valuation_date, lessor_cents, lessee_cents
    )
    arbitration = get_success_data(
        api.refer_to_arbitration(
            reval["id"],
            f.referral_payload(arbitrator_user_id),
            make_lessor_admin_headers(),
        )
    )
    # PRD §3.3: the referral moves the revaluation
    # `PROPOSALS_EXCHANGED → ARBITRATION_REFERRED`, so the row captured at
    # exchange is stale — re-read it before handing it to the caller.
    referred = get_success_data(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    return referred, arbitration


def render_award(api, arbitration_id, independent_annual_rent_cents,
                 arbitrator_user_id="arb-neutral-1"):
    return get_success_data(
        api.render_award(
            arbitration_id,
            f.award_payload(independent_annual_rent_cents),
            make_arbitrator_headers(arbitrator_user_id),
        )
    )


def consented_sublease(api, lease_id, lessee_id, premises_unit_code,
                       annual_sublease_rent_cents, **overrides):
    """Create a SUBLEASE transfer request and grant consent (CONSENT_GRANTED)."""
    created = get_success_data(
        api.create_transfer(
            f.sublease_payload(
                lease_id, premises_unit_code, annual_sublease_rent_cents, **overrides
            ),
            make_ground_tenant_headers(lessee_id),
        )
    )
    return get_success_data(
        api.decide_transfer(
            created["id"], f.decision_payload("APPROVE"), make_asset_manager_headers()
        )
    )


def active_sublease(api, lease_id, lessee_id, premises_unit_code,
                    annual_sublease_rent_cents, **overrides):
    """Carry a sublease all the way to ACTIVE by paying the assessed fee exactly.
    PRD §3.6 requires the payment to equal the outstanding balance to the cent."""
    granted = consented_sublease(
        api, lease_id, lessee_id, premises_unit_code,
        annual_sublease_rent_cents, **overrides
    )
    outstanding = granted["total_transfer_fee_cents"] - granted["transfer_fee_paid_cents"]
    return get_success_data(
        api.pay_transfer_fee(
            granted["id"],
            f.fee_payment_payload(outstanding),
            make_ground_tenant_headers(lessee_id),
        )
    )


def file_statement(api, lease_id, lessee_id,
                   period_start="2025-01-01T00:00:00Z",
                   period_end="2026-01-01T00:00:00Z",
                   reported_gross_sales_cents=120000000, **overrides):
    """Re-read the lease immediately before filing so expected_lease_version is
    current (PRD §2.7 pins the version on exactly this write)."""
    version = lease_version(api, lease_id)
    return get_success_data(
        api.file_statement(
            f.statement_payload(
                lease_id, version, period_start, period_end,
                reported_gross_sales_cents, **overrides
            ),
            make_ground_tenant_headers(lessee_id),
        )
    )


def issue_estoppel(api, lease_id, mortgage_id):
    version = lease_version(api, lease_id)
    return get_success_data(
        api.issue_estoppel(
            f.estoppel_payload(lease_id, mortgage_id, version),
            make_mortgagee_agent_headers(mortgage_id),
        )
    )


def submitted_alteration(api, lease_id, lessee_id, **overrides):
    return get_success_data(
        api.create_alteration(
            lease_id, f.alteration_payload(**overrides),
            make_ground_tenant_headers(lessee_id),
        )
    )


def approved_alteration(api, lease_id, lessee_id, user_id="am-1", **overrides):
    created = submitted_alteration(api, lease_id, lessee_id, **overrides)
    return get_success_data(
        api.decide_alteration(
            created["id"], f.decision_payload("APPROVE"),
            make_asset_manager_headers(user_id),
        )
    )


def served_default_notice(api, lease_id, default_type="MONETARY_RENT_ARREARS",
                          claimed_amount_cents=None, user_id="acct-1"):
    return get_success_data(
        api.serve_default_notice(
            lease_id,
            f.default_notice_payload(default_type, claimed_amount_cents),
            make_accountant_headers(user_id),
        )
    )


def reported_loss_event(api, lease_id, headers=None, **overrides):
    return get_success_data(
        api.report_loss_event(
            lease_id, f.loss_event_payload(**overrides),
            headers or make_asset_manager_headers(),
        )
    )


def adjusted_loss_event(api, lease_id, distributable_pool_cents,
                        allocation_method="BONUS_VALUE", rent_abatement_bps=0,
                        headers=None, **overrides):
    event = reported_loss_event(api, lease_id, headers=headers, **overrides)
    return get_success_data(
        api.adjust_loss_event(
            event["id"],
            f.adjust_payload(distributable_pool_cents, allocation_method,
                             rent_abatement_bps),
            headers or make_asset_manager_headers(),
        )
    )


def run_sweep(api):
    """PRD §3.10: the administration run is the five-phase scheduled sweep."""
    return get_success_data(api.run_administration(make_lessor_admin_headers()))


def expire_lease_via_sweep(api, lease_id, clock="2026-09-02T00:00:00Z"):
    """The only route to a reversion: advance the clock past expiration and let
    the sweep expire the lease, which opens the assessment in PENDING_INSPECTION."""
    set_clock(api, clock)
    run_report = run_sweep(api)
    rows, _meta = _paginate(api.list_reversion_assessments(
        make_asset_manager_headers(), {"lease_id": lease_id}
    ))
    assert rows, f"the sweep did not open a reversion assessment on {lease_id}"
    return run_report, rows[0]


def _paginate(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})
