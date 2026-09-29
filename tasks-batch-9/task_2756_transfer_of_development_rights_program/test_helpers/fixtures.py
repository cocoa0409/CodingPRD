"""Composite setup helpers.

Every test starts against an empty registry, so each helper here builds its
preconditions from scratch through the program's own endpoints.  Setup calls use
the lenient validator so a broken precondition surfaces as a setup failure
rather than as a confusing assertion failure inside the test body.

Ownership discipline: a `Landowner` or `Developer` call whose subject belongs to
a party always travels under `make_landowner_headers(party_id)` /
`make_developer_headers(party_id)`, never under the shared header constants.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    account_action_payload,
    allocate_redemption_payload,
    create_appraisal_schedule_payload,
    create_evaluation_payload,
    create_inspection_payload,
    create_market_transaction_payload,
    create_party_payload,
    create_receiving_area_payload,
    create_receiving_site_application_payload,
    create_sending_area_payload,
    create_sending_parcel_payload,
    create_severance_application_payload,
    cure_verification_payload,
    design_review_payload,
    resubmit_design_payload,
    retire_certificate_payload,
    review_decision_payload,
    split_certificate_payload,
)
from .test_users import (
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    DESIGN_BOARD_USER_ID,
    MONITOR_USER_ID,
    MONITOR_USER_ID_ALT,
    REVIEWER_USER_ID,
    TEST_USERS,
    make_admin_headers,
    make_design_board_headers,
    make_developer_headers,
    make_landowner_headers,
    make_monitor_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
MONITOR = TEST_USERS["monitor_headers"]
DESIGN_BOARD = TEST_USERS["design_board_headers"]


# ── Logical clock and operations ────────────────────────────────────────────

def set_clock(current_utc: str) -> dict:
    """Move the logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def run_compliance_sweep(headers=None) -> dict:
    return get_success_data(api_client.run_compliance_sweep(headers or ADMIN))


# ── Parties ─────────────────────────────────────────────────────────────────

def register_party(kind: str = "LANDOWNER", **overrides) -> dict:
    return get_success_data(
        api_client.create_party(create_party_payload(kind, **overrides), ADMIN)
    )


def register_landowner(**overrides) -> dict:
    return register_party("LANDOWNER", **overrides)


def register_developer(**overrides) -> dict:
    return register_party("DEVELOPER", **overrides)


def register_bank(**overrides) -> dict:
    """The single MUNICIPAL_BANK party that stands behind both bank channels."""
    overrides.setdefault("legal_name", "Municipal TDR Bank")
    return register_party("MUNICIPAL_BANK", **overrides)


def fetch_party(party_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_party(party_id, headers or ADMIN))


def account_action(party_id: str, action: str, amount_cents: Optional[int] = None,
                   expected_party_version: Optional[int] = None, headers=None, **overrides) -> dict:
    """Run an administrative account action, reading the party's live version when
    the caller does not pin one."""
    if expected_party_version is None:
        expected_party_version = fetch_party(party_id)["version"]
    payload = account_action_payload(action, expected_party_version, **overrides)
    if action in ("CREDIT", "DEBIT"):
        payload["amount_cents"] = amount_cents if amount_cents is not None else 1_000_000
    else:
        payload.pop("amount_cents", None)
    return get_success_data(
        api_client.party_account_action(party_id, payload, headers or ADMIN)
    )


def credit_party(party_id: str, amount_cents: int) -> dict:
    return account_action(party_id, "CREDIT", amount_cents=amount_cents)


def debit_party(party_id: str, amount_cents: int) -> dict:
    return account_action(party_id, "DEBIT", amount_cents=amount_cents)


def suspend_party(party_id: str) -> dict:
    return account_action(party_id, "SUSPEND")


def reinstate_party(party_id: str) -> dict:
    return account_action(party_id, "REINSTATE")


def program_parties(headers=None) -> list:
    """Every party in the register, for the cash-conservation identity."""
    resp = api_client.list_parties(headers or ADMIN, params={"limit": 100, "offset": 0})
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"Setup failed listing parties: {resp.text}"
    return body["data"]


def program_cash_total_now(headers=None) -> int:
    return sum(
        p["cash_balance_cents"] + p["fee_revenue_cents"] for p in program_parties(headers)
    )


# ── Designations ────────────────────────────────────────────────────────────

def designate_sending_area(**overrides) -> dict:
    return get_success_data(
        api_client.create_sending_area(create_sending_area_payload(**overrides), ADMIN)
    )


def activate_sending_area(area_id: str, headers=None) -> dict:
    return get_success_data(api_client.activate_sending_area(area_id, headers or ADMIN))


def create_active_sending_area(**overrides) -> dict:
    """Designate a sending area and take it DRAFT -> ACTIVE."""
    area = designate_sending_area(**overrides)
    return activate_sending_area(area["id"])


def close_sending_area(area_id: str, reason: Optional[str] = None) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.close_sending_area(area_id, ADMIN, payload))


def fetch_sending_area(area_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sending_area(area_id, headers or ADMIN))


def designate_receiving_area(**overrides) -> dict:
    return get_success_data(
        api_client.create_receiving_area(create_receiving_area_payload(**overrides), ADMIN)
    )


def activate_receiving_area(area_id: str, headers=None) -> dict:
    return get_success_data(api_client.activate_receiving_area(area_id, headers or ADMIN))


def create_active_receiving_area(**overrides) -> dict:
    area = designate_receiving_area(**overrides)
    return activate_receiving_area(area["id"])


def fetch_receiving_area(area_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_receiving_area(area_id, headers or ADMIN))


def publish_appraisal_schedule(**overrides) -> dict:
    return get_success_data(
        api_client.create_appraisal_schedule(
            create_appraisal_schedule_payload(**overrides), ADMIN
        )
    )


# ── Parcels and severance review ────────────────────────────────────────────

def enroll_parcel(owner_party_id: str, sending_area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sending_parcel(
            create_sending_parcel_payload(owner_party_id, sending_area_id, **overrides), ADMIN
        )
    )


def fetch_parcel(parcel_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sending_parcel(parcel_id, headers or ADMIN))


def file_severance(parcel_id: str, applicant_party_id: str, requested_units: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_severance_application(
            create_severance_application_payload(
                parcel_id, applicant_party_id, requested_units, **overrides
            ),
            make_landowner_headers(applicant_party_id),
        )
    )


def screen_application(app_id: str, reviewer_user_id: str = REVIEWER_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.screen_severance_application(
            app_id, make_reviewer_headers(reviewer_user_id), overrides or {}
        )
    )


def decide_application(app_id: str, decision: str,
                       reviewer_user_id: str = REVIEWER_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.review_severance_application(
            app_id, review_decision_payload(decision, **overrides),
            make_reviewer_headers(reviewer_user_id),
        )
    )


def resubmit_application(app_id: str, applicant_party_id: str, requested_units: int, **overrides) -> dict:
    payload = {"requested_units": requested_units}
    payload.update(overrides)
    return get_success_data(
        api_client.resubmit_severance_application(
            app_id, payload, make_landowner_headers(applicant_party_id)
        )
    )


def certify_application(app_id: str, admin_user_id: str = ADMIN_USER_ID, **overrides) -> dict:
    """Certify an APPROVED severance.  Returns the newly issued certificate.

    The default certifying operator differs from the default reviewing operator,
    so the segregation-of-duties gate is satisfied.
    """
    return get_success_data(
        api_client.certify_severance_application(
            app_id, make_admin_headers(admin_user_id), overrides or {}
        )
    )


def fetch_application(app_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_severance_application(app_id, headers or ADMIN))


def approve_application(parcel_id: str, applicant_party_id: str, requested_units: int,
                        reviewer_user_id: str = REVIEWER_USER_ID) -> dict:
    """File -> screen -> APPROVE.  Returns the APPROVED application."""
    app = file_severance(parcel_id, applicant_party_id, requested_units)
    screen_application(app["id"], reviewer_user_id)
    return decide_application(app["id"], "APPROVE", reviewer_user_id)


# ── Easements, certificates and the registry ────────────────────────────────

def fetch_easement(easement_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_conservation_easement(easement_id, headers or ADMIN))


def easement_for_parcel(parcel_id: str, headers=None) -> dict:
    """The single easement recorded against a parcel."""
    resp = api_client.list_conservation_easements(
        headers or ADMIN, params={"sending_parcel_id": parcel_id, "limit": 100, "offset": 0}
    )
    assert 200 <= resp.status_code < 300, f"Setup failed listing easements: {resp.text}"
    rows = resp.json()["data"]
    assert rows, f"Setup failed: no easement recorded against parcel {parcel_id}"
    return rows[0]


def fetch_certificate(certificate_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_certificate(certificate_id, headers or ADMIN))


def certificates_of(headers=None, **filters) -> list:
    params = {"limit": 100, "offset": 0}
    params.update(filters)
    resp = api_client.list_certificates(headers or ADMIN, params=params)
    assert 200 <= resp.status_code < 300, f"Setup failed listing certificates: {resp.text}"
    return resp.json()["data"]


def transfers_of(certificate_id: str, headers=None) -> list:
    """Chain-of-title rows for one certificate, in creation order."""
    resp = api_client.list_certificate_transfers(
        headers or ADMIN, params={"certificate_id": certificate_id, "limit": 100, "offset": 0}
    )
    assert 200 <= resp.status_code < 300, f"Setup failed listing transfers: {resp.text}"
    return resp.json()["data"]


def split_certificate(certificate_id: str, units: int, actor_headers=None,
                      expected_certificate_version: Optional[int] = None) -> dict:
    """Split units off a certificate.  Returns the child certificate."""
    if expected_certificate_version is None:
        expected_certificate_version = fetch_certificate(certificate_id)["version"]
    return get_success_data(
        api_client.split_certificate(
            certificate_id,
            split_certificate_payload(units, expected_certificate_version),
            actor_headers or ADMIN,
        )
    )


def retire_units(certificate_id: str, units: int, actor_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.retire_certificate_units(
            certificate_id, retire_certificate_payload(units, **overrides), actor_headers or ADMIN
        )
    )


# ── Market ──────────────────────────────────────────────────────────────────

def propose_transaction(certificate_id: str, seller_party_id: str, buyer_party_id: str,
                        units: int, channel: str = "PRIVATE", actor_headers=None,
                        conveyance_mode: str = "WHOLE", **overrides) -> dict:
    """Propose a deal.  A PRIVATE deal is filed by the selling side; both bank
    channels are filed by the administrator."""
    if actor_headers is None:
        actor_headers = ADMIN if channel != "PRIVATE" else make_landowner_headers(seller_party_id)
    payload = create_market_transaction_payload(
        certificate_id, seller_party_id, buyer_party_id, units, channel, conveyance_mode, **overrides
    )
    return get_success_data(api_client.create_market_transaction(payload, actor_headers))


def settle_transaction(tx_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.settle_market_transaction(tx_id, headers or ADMIN, overrides or {})
    )


def cancel_transaction(tx_id: str, actor_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_market_transaction(tx_id, actor_headers or ADMIN, overrides or {})
    )


def reverse_transaction(tx_id: str, reversal_reason: str = "TITLE_DEFECT", headers=None) -> dict:
    return get_success_data(
        api_client.reverse_market_transaction(
            tx_id, {"reversal_reason": reversal_reason}, headers or ADMIN
        )
    )


def fetch_transaction(tx_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_market_transaction(tx_id, headers or ADMIN))


# ── Receiving side ──────────────────────────────────────────────────────────

def file_receiving_site_application(developer_party_id: str, receiving_area_id: str,
                                    site_acres: float = 12.00,
                                    requested_bonus_units: int = 10, **overrides) -> dict:
    return get_success_data(
        api_client.create_receiving_site_application(
            create_receiving_site_application_payload(
                developer_party_id, receiving_area_id, site_acres, requested_bonus_units, **overrides
            ),
            make_developer_headers(developer_party_id),
        )
    )


def fetch_receiving_site_application(app_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_receiving_site_application(app_id, headers or ADMIN))


def allocate_redemption(app_id: str, developer_party_id: str, certificate_id: str, units: int,
                        expected_version: Optional[int] = None) -> dict:
    """Allocate certificate units to back an application, pinning the application's
    live version unless the caller supplies a stale one deliberately."""
    if expected_version is None:
        expected_version = fetch_receiving_site_application(app_id)["version"]
    return get_success_data(
        api_client.allocate_redemption(
            app_id,
            allocate_redemption_payload(certificate_id, units, expected_version),
            make_developer_headers(developer_party_id),
        )
    )


def release_redemption(redemption_id: str, actor_headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.release_redemption(redemption_id, actor_headers or ADMIN, overrides or {})
    )


def fetch_redemption(redemption_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_certificate_redemption(redemption_id, headers or ADMIN))


def design_decision(app_id: str, decision: str,
                    design_board_user_id: str = DESIGN_BOARD_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.design_review_decision(
            app_id, design_review_payload(decision, **overrides),
            make_design_board_headers(design_board_user_id),
        )
    )


def resubmit_design(app_id: str, developer_party_id: str, requested_bonus_units: int, **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_design(
            app_id, resubmit_design_payload(requested_bonus_units, **overrides),
            make_developer_headers(developer_party_id),
        )
    )


def finalize_application(app_id: str, developer_party_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.finalize_receiving_site_application(
            app_id, make_developer_headers(developer_party_id), overrides or {}
        )
    )


# ── Stewardship ─────────────────────────────────────────────────────────────

def record_inspection(easement_id: str, inspection_date: str, finding: str = "COMPLIANT",
                      affected_acres: float = 0.00,
                      monitor_user_id: str = MONITOR_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection(
            easement_id,
            create_inspection_payload(inspection_date, finding, affected_acres, **overrides),
            make_monitor_headers(monitor_user_id),
        )
    )


def verify_cure(inspection_id: str, outcome: str = "CURED",
                verifier_user_id: str = MONITOR_USER_ID_ALT, **overrides) -> dict:
    """Verify a cure under an identity that differs from the recording inspector."""
    return get_success_data(
        api_client.verify_cure(
            inspection_id, cure_verification_payload(outcome, **overrides),
            make_monitor_headers(verifier_user_id),
        )
    )


def fetch_inspection(inspection_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_monitoring_inspection(inspection_id, headers or ADMIN))


def compute_evaluation(period_start: str, period_end: str,
                       equity_weighting: str = "ACREAGE_WEIGHTED", **overrides) -> dict:
    return get_success_data(
        api_client.create_evaluation(
            create_evaluation_payload(period_start, period_end, equity_weighting, **overrides), ADMIN
        )
    )


# ── Composite scenarios ─────────────────────────────────────────────────────
# The canonical parcel geometry below yields a 22-unit baseline allocation under
# V1_NET_ACRE: eligible acreage (100.00 - 22.00) x 0.25 units/acre x the PRIME
# multiplier 1.25 = 24.375, floored to 24, less 2 existing dwelling units.
CANONICAL_PARCEL = {
    "gross_acres": 100.00,
    "constrained_acres": 22.00,
    "soil_class": "PRIME",
    "existing_dwelling_units": 2,
}
CANONICAL_BASELINE_UNITS = 22
DEFAULT_CLOCK = "2026-08-10T00:00:00Z"
DEFAULT_PER_UNIT_VALUE_CENTS = 1_234_567
DEFAULT_EQUITY_ADJUSTMENT_BPS = 250
DEFAULT_PRIVATE_PRICE_CENTS = 30_000_000


def setup_certified_severance(units: int = CANONICAL_BASELINE_UNITS,
                              clock: Optional[str] = DEFAULT_CLOCK,
                              equity_tier: str = "UNDERSERVED",
                              neighborhood_code: str = "NB-EAST",
                              area_overrides: Optional[dict] = None,
                              parcel_overrides: Optional[dict] = None,
                              landowner: Optional[dict] = None,
                              reviewer_user_id: str = REVIEWER_USER_ID,
                              admin_user_id: str = ADMIN_USER_ID) -> dict:
    """Clock -> landowner -> ACTIVE sending area -> parcel -> filed, screened,
    approved and certified severance.

    Returns {landowner, area, parcel, application, certificate, easement}, each
    read back after the certification cascade has settled.
    """
    if clock:
        set_clock(clock)
    landowner = landowner or register_landowner(neighborhood_code=neighborhood_code)
    area_kwargs = {
        "neighborhood_code": neighborhood_code,
        "equity_tier": equity_tier,
        "allocation_formula_version": "V1_NET_ACRE",
        "base_rate_units_per_acre": 0.25,
        "gross_discount_factor": 0.80,
        "sending_cap_units": TEST_DEFAULTS["SENDING_CAP_UNITS"],
    }
    area_kwargs.update(area_overrides or {})
    area = create_active_sending_area(**area_kwargs)

    parcel_kwargs = dict(CANONICAL_PARCEL)
    parcel_kwargs.update(parcel_overrides or {})
    parcel = enroll_parcel(landowner["id"], area["id"], **parcel_kwargs)

    application = approve_application(parcel["id"], landowner["id"], units, reviewer_user_id)
    certificate = certify_application(application["id"], admin_user_id)
    return {
        "landowner": landowner,
        "area": fetch_sending_area(area["id"]),
        "parcel": fetch_parcel(parcel["id"]),
        "application": fetch_application(application["id"]),
        "certificate": certificate,
        "easement": fetch_easement(certificate["conservation_easement_id"]),
    }


def setup_developer_holding_certificate(units: int = CANONICAL_BASELINE_UNITS,
                                        clock: Optional[str] = DEFAULT_CLOCK,
                                        equity_tier: str = "UNDERSERVED",
                                        per_unit_value_cents: int = DEFAULT_PER_UNIT_VALUE_CENTS,
                                        equity_adjustment_bps: int = DEFAULT_EQUITY_ADJUSTMENT_BPS,
                                        agreed_price_cents: int = DEFAULT_PRIVATE_PRICE_CENTS,
                                        buyer_credit_cents: Optional[int] = None,
                                        **scenario_overrides) -> dict:
    """The full sending-side chain, then a settled PRIVATE sale of the whole
    certificate to a developer, so the developer holds it HELD and unencumbered.

    Returns the sending-side keys plus {developer, bank, schedule, transaction,
    certificate} where `certificate` is re-read after settlement.
    """
    scenario = setup_certified_severance(units=units, clock=clock, equity_tier=equity_tier,
                                         **scenario_overrides)
    developer = register_developer(neighborhood_code="NB-CORE")
    bank = register_bank(neighborhood_code="NB-CORE")
    schedule = publish_appraisal_schedule(
        neighborhood_code=scenario["area"]["neighborhood_code"],
        per_unit_value_cents=per_unit_value_cents,
        equity_adjustment_bps=equity_adjustment_bps,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    credit_party(developer["id"], buyer_credit_cents if buyer_credit_cents is not None
                 else agreed_price_cents)
    transaction = propose_transaction(
        scenario["certificate"]["id"], scenario["landowner"]["id"], developer["id"],
        units=scenario["certificate"]["units_remaining"], channel="PRIVATE",
        agreed_price_cents=agreed_price_cents,
    )
    transaction = settle_transaction(transaction["id"])
    scenario.update({
        "developer": developer,
        "bank": bank,
        "schedule": schedule,
        "transaction": transaction,
        "certificate": fetch_certificate(scenario["certificate"]["id"]),
    })
    return scenario


def setup_backed_receiving_application(backing_units: int = 5,
                                       site_acres: float = 4.00,
                                       requested_bonus_units: int = 5,
                                       absorption_cap_units: int = 500,
                                       design_review_required: bool = False,
                                       receiving_area_overrides: Optional[dict] = None,
                                       **holder_overrides) -> dict:
    """A developer holding a certificate, an ACTIVE receiving area, a filed
    receiving-site application and one ALLOCATED redemption backing it.

    Returns the holder-scenario keys plus {receiving_area, rsa, redemption}.
    """
    scenario = setup_developer_holding_certificate(**holder_overrides)
    ra_kwargs = {
        "neighborhood_code": "NB-CORE",
        "base_density_units_per_acre": 4.00,
        "max_bonus_pct": 0.35,
        "absorption_cap_units": absorption_cap_units,
        "design_review_required": design_review_required,
        "eligible_sending_area_codes": [],
    }
    ra_kwargs.update(receiving_area_overrides or {})
    receiving_area = create_active_receiving_area(**ra_kwargs)
    rsa = file_receiving_site_application(
        scenario["developer"]["id"], receiving_area["id"], site_acres, requested_bonus_units
    )
    redemption = allocate_redemption(
        rsa["id"], scenario["developer"]["id"], scenario["certificate"]["id"], backing_units
    )
    scenario.update({
        "receiving_area": fetch_receiving_area(receiving_area["id"]),
        "rsa": fetch_receiving_site_application(rsa["id"]),
        "redemption": redemption,
        "certificate": fetch_certificate(scenario["certificate"]["id"]),
    })
    return scenario


def notice_violation(easement_id: str, inspection_date: str = "2026-08-10",
                     finding: str = "MAJOR_VIOLATION", affected_acres: float = 12.00,
                     monitor_user_id: str = MONITOR_USER_ID) -> dict:
    """Record a violation finding, driving the easement out of compliance and
    freezing every certificate derived from it."""
    return record_inspection(easement_id, inspection_date, finding, affected_acres, monitor_user_id)


def setup_frozen_certificate(units: int = CANONICAL_BASELINE_UNITS,
                             inspection_date: str = "2026-08-10",
                             finding: str = "MAJOR_VIOLATION",
                             affected_acres: float = 12.00,
                             **scenario_overrides) -> dict:
    """A certified certificate whose source easement is out of compliance, so the
    certificate's market_status is FROZEN.

    Returns the sending-side keys plus {inspection}.
    """
    scenario = setup_certified_severance(units=units, **scenario_overrides)
    inspection = notice_violation(scenario["easement"]["id"], inspection_date, finding, affected_acres)
    scenario.update({
        "inspection": inspection,
        "certificate": fetch_certificate(scenario["certificate"]["id"]),
        "easement": fetch_easement(scenario["easement"]["id"]),
    })
    return scenario


def setup_settled_bank_sale(channel: str = "BANK_PURCHASE",
                            units: Optional[int] = None,
                            bank_credit_cents: int = 100_000_000,
                            **scenario_overrides) -> dict:
    """A certified certificate sold to (BANK_PURCHASE) the municipal bank at the
    administered price, settled.

    Returns the sending-side keys plus {bank, schedule, transaction}.
    """
    scenario = setup_certified_severance(**scenario_overrides)
    bank = register_bank(neighborhood_code="NB-CORE")
    schedule = publish_appraisal_schedule(
        neighborhood_code=scenario["area"]["neighborhood_code"],
        per_unit_value_cents=DEFAULT_PER_UNIT_VALUE_CENTS,
        equity_adjustment_bps=DEFAULT_EQUITY_ADJUSTMENT_BPS,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    credit_party(bank["id"], bank_credit_cents)
    traded = units if units is not None else scenario["certificate"]["units_remaining"]
    transaction = propose_transaction(
        scenario["certificate"]["id"], scenario["landowner"]["id"], bank["id"],
        units=traded, channel=channel, actor_headers=ADMIN,
    )
    transaction = settle_transaction(transaction["id"])
    scenario.update({
        "bank": bank,
        "schedule": schedule,
        "transaction": transaction,
        "certificate": fetch_certificate(scenario["certificate"]["id"]),
    })
    return scenario
