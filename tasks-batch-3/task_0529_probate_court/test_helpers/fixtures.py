"""Composite setup helpers.

Every mutation that governs an estate carries expected_estate_version equal to
the estate's current version, so each helper re-reads the estate immediately
before the call it guards (get_success_data is used throughout so setup failures
surface as clear "Setup failed" errors rather than confusing assertions).

The logical clock starts at 2026-05-01T00:00:00Z. Helpers that do not touch the
clock leave it at its startup default.

Role headers:
  - Clerk / ProbateJudge are opaque; a fixed judge id "judge-1" is used except
    where a scenario needs a specific segregation-of-duties id.
  - PersonalRepresentative acts under the representative_user_id the PR was
    nominated with (default "pr-user-1"); administration calls pass that id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_clerk_headers, make_judge_headers, make_representative_headers

CLERK = make_clerk_headers("clerk-1")
JUDGE = make_judge_headers("judge-1")


def _rep_headers(user_id="pr-user-1"):
    return make_representative_headers(user_id)


def _estate_version(estate_id):
    est = get_success_data(api_client.get_estate(estate_id, CLERK))
    return est["version"]


def set_clock(iso: str):
    """Advance the logical clock to the supplied instant (Clerk-authorized)."""
    get_success_data(api_client.set_clock(iso, CLERK))


# --------------------------------------------------------------------------- #
# Tier 1 — estate / petition / representative progression
# --------------------------------------------------------------------------- #
def create_estate(gross_estate_value_cents=6_000_000, estate_type="INTESTATE",
                  county_code="LA", decedent_name="Dec"):
    """Create a DRAFT estate. Returns the estate dict."""
    payload = {
        "decedent_name": decedent_name,
        "date_of_death": "2026-04-01T00:00:00Z",
        "county_code": county_code,
        "estate_type": estate_type,
        "gross_estate_value_cents": gross_estate_value_cents,
    }
    return get_success_data(api_client.create_estate(payload, CLERK))


def create_petition(estate_id, will_lodged=False, will_date=None,
                    nominated_representative_name="R"):
    payload = {
        "estate_id": estate_id,
        "petitioner_name": "P",
        "will_lodged": will_lodged,
        "nominated_representative_name": nominated_representative_name,
    }
    if will_date is not None:
        payload["will_date"] = will_date
    return get_success_data(api_client.create_petition(payload, CLERK))


def grant_petition(estate_id, petition_id):
    v = _estate_version(estate_id)
    return get_success_data(api_client.grant_petition(
        petition_id, {"expected_estate_version": v}, JUDGE))


def nominate_representative(estate_id, petition_id, representative_user_id="pr-user-1"):
    payload = {
        "estate_id": estate_id,
        "petition_id": petition_id,
        "full_name": "R",
        "representative_user_id": representative_user_id,
    }
    return get_success_data(api_client.create_representative(payload, CLERK))


def create_open_estate_with_nominated_pr(gross=6_000_000, estate_type="INTESTATE",
                                         representative_user_id="pr-user-1"):
    """DRAFT estate -> petition -> grant (estate OPEN) -> nominate PR (NOMINATED).
    Returns (estate, petition, representative)."""
    est = create_estate(gross, estate_type)
    pet = create_petition(est["id"])
    grant_petition(est["id"], pet["id"])
    rep = nominate_representative(est["id"], pet["id"], representative_user_id)
    return est, pet, rep


def file_bond(estate_id, representative_id, penal_amount_cents):
    payload = {
        "estate_id": estate_id,
        "representative_id": representative_id,
        "surety_name": "Acme Surety",
        "penal_amount_cents": penal_amount_cents,
    }
    return get_success_data(api_client.create_bond(payload, CLERK))


def approve_bond(estate_id, bond_id):
    v = _estate_version(estate_id)
    return get_success_data(api_client.approve_bond(
        bond_id, {"expected_estate_version": v}, JUDGE))


def appoint_representative(estate_id, rep_id, judge_user_id="judge-1"):
    v = _estate_version(estate_id)
    return get_success_data(api_client.appoint_representative(
        rep_id, {"expected_estate_version": v}, make_judge_headers(judge_user_id)))


def create_estate_with_appointed_pr(gross=6_000_000, estate_type="INTESTATE",
                                    penal_amount_cents=3_250_000,
                                    representative_user_id="pr-user-1"):
    """Full FULL-estate path to an APPOINTED PR with an APPROVED bound bond.
    Returns (estate, petition, representative, bond).

    For an INDEPENDENT estate (gross < 500000) no bond is required; the bond
    steps are skipped and bond is None.
    """
    est, pet, rep = create_open_estate_with_nominated_pr(
        gross, estate_type, representative_user_id)
    bond = None
    if rep["bond_required"]:
        bond = file_bond(est["id"], rep["id"], penal_amount_cents)
        approve_bond(est["id"], bond["id"])
    appoint_representative(est["id"], rep["id"])
    return est, pet, rep, bond


def create_independent_estate_with_appointed_pr(representative_user_id="pr-user-1"):
    """INDEPENDENT estate (gross 300000, no bond) -> APPOINTED PR.
    Returns (estate, petition, representative)."""
    est, pet, rep, _ = create_estate_with_appointed_pr(
        gross=300_000, representative_user_id=representative_user_id)
    return est, pet, rep


# --------------------------------------------------------------------------- #
# Tier 2/3 — assets and claims under an APPOINTED PR
# --------------------------------------------------------------------------- #
def list_asset(estate_id, asset_class="CASH", declared_value_cents=100_000,
               description="Asset", rep_user_id="pr-user-1"):
    payload = {
        "estate_id": estate_id,
        "description": description,
        "asset_class": asset_class,
        "declared_value_cents": declared_value_cents,
    }
    return get_success_data(api_client.create_asset(payload, _rep_headers(rep_user_id)))


def appraise_asset(estate_id, asset_id, appraised_value_cents, rep_user_id="pr-user-1"):
    v = _estate_version(estate_id)
    return get_success_data(api_client.appraise_asset(
        asset_id,
        {"appraised_value_cents": appraised_value_cents, "expected_estate_version": v},
        _rep_headers(rep_user_id)))


def marshal_asset(estate_id, asset_id, rep_user_id="pr-user-1"):
    v = _estate_version(estate_id)
    return get_success_data(api_client.marshal_asset(
        asset_id, {"expected_estate_version": v}, _rep_headers(rep_user_id)))


def file_claim(estate_id, claim_class="GENERAL", claimed_amount_cents=100_000,
               creditor_name="C"):
    payload = {
        "estate_id": estate_id,
        "creditor_name": creditor_name,
        "claim_class": claim_class,
        "claimed_amount_cents": claimed_amount_cents,
    }
    return get_success_data(api_client.create_claim(payload, CLERK))


def allow_claim(estate_id, claim_id, allowed_amount_cents, rep_user_id="pr-user-1"):
    v = _estate_version(estate_id)
    return get_success_data(api_client.allow_claim(
        claim_id,
        {"allowed_amount_cents": allowed_amount_cents, "expected_estate_version": v},
        _rep_headers(rep_user_id)))


def add_beneficiary(estate_id, share_bps=10_000, relationship="CHILD", full_name="Heir"):
    payload = {
        "estate_id": estate_id,
        "full_name": full_name,
        "relationship": relationship,
        "share_bps": share_bps,
    }
    return get_success_data(api_client.create_beneficiary(payload, CLERK))


# --------------------------------------------------------------------------- #
# Accounting phase progression
# --------------------------------------------------------------------------- #
def _file_and_approve_accounting(estate_id, report_type, rep_user_id="pr-user-1"):
    acct = get_success_data(api_client.create_accounting(
        {"estate_id": estate_id, "report_type": report_type},
        _rep_headers(rep_user_id)))
    v = _estate_version(estate_id)
    get_success_data(api_client.file_accounting(
        acct["id"], {"expected_estate_version": v}, _rep_headers(rep_user_id)))
    v = _estate_version(estate_id)
    get_success_data(api_client.approve_accounting(
        acct["id"], {"expected_estate_version": v}, JUDGE))
    return acct


def advance_open_to_accounting(estate_id, rep_user_id="pr-user-1"):
    """OPEN -> (file+approve INVENTORY) -> INVENTORIED -> (file+approve INTERIM)
    -> ACCOUNTING. Assets should be appraised before this if they must count in
    the inventory snapshot; marshaling of appraised assets happens in ACCOUNTING."""
    _file_and_approve_accounting(estate_id, "INVENTORY", rep_user_id)
    _file_and_approve_accounting(estate_id, "INTERIM", rep_user_id)


def file_final_accounting(estate_id, rep_user_id="pr-user-1"):
    """ACCOUNTING -> file FINAL -> estate DISTRIBUTING. Returns the FINAL report.
    (Filing a FINAL report requires every ALLOWED claim already PAID.)"""
    acct = get_success_data(api_client.create_accounting(
        {"estate_id": estate_id, "report_type": "FINAL"}, _rep_headers(rep_user_id)))
    v = _estate_version(estate_id)
    get_success_data(api_client.file_accounting(
        acct["id"], {"expected_estate_version": v}, _rep_headers(rep_user_id)))
    return acct


def approve_final_accounting(estate_id, acct_id):
    """DISTRIBUTING -> approve FINAL -> estate CLOSED."""
    v = _estate_version(estate_id)
    return get_success_data(api_client.approve_accounting(
        acct_id, {"expected_estate_version": v}, JUDGE))


# --------------------------------------------------------------------------- #
# Tier 4/5 — composite states used by multiple difficulty/corner instances
# --------------------------------------------------------------------------- #
def setup_accounting_estate_with_marshaled_cash(cash_cents=200_000, gross=6_000_000):
    """FULL estate driven to ACCOUNTING with one CASH asset (appraised = cash_cents)
    marshaled into the ledger. Returns (estate, representative, asset).
    Estate.marshaled_cash_cents == cash_cents on return.
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=gross)
    # PRD requires an asset's declared_value_cents to be greater than zero, so a
    # zero-cash pool cannot be modeled by a zero-value asset. When cash_cents is 0
    # we simply list/marshal no asset, leaving marshaled_cash_cents at its initial 0.
    asset = None
    if cash_cents > 0:
        asset = list_asset(est["id"], "CASH", cash_cents, "Cash")
        appraise_asset(est["id"], asset["id"], cash_cents)
    advance_open_to_accounting(est["id"])
    if cash_cents > 0:
        marshal_asset(est["id"], asset["id"])
    return est, rep, asset


def setup_distributing_estate_with_cash(cash_cents=1_000_000, gross=6_000_000,
                                        share_bps=10_000):
    """FULL estate driven all the way to DISTRIBUTING with a marshaled CASH asset
    (no claims), a sole beneficiary holding share_bps, and residue == cash_cents.
    Returns (estate, representative, beneficiary).
    """
    est, pet, rep, bond = create_estate_with_appointed_pr(gross=gross)
    ben = add_beneficiary(est["id"], share_bps=share_bps)
    asset = list_asset(est["id"], "CASH", cash_cents, "Cash")
    appraise_asset(est["id"], asset["id"], cash_cents)
    advance_open_to_accounting(est["id"])
    marshal_asset(est["id"], asset["id"])
    final = file_final_accounting(est["id"])          # -> DISTRIBUTING
    return est, rep, ben


def propose_distribution(estate_id, beneficiary_id, proposed_amount_cents,
                         rep_user_id="pr-user-1"):
    payload = {
        "estate_id": estate_id,
        "beneficiary_id": beneficiary_id,
        "proposed_amount_cents": proposed_amount_cents,
    }
    return get_success_data(api_client.create_distribution(
        payload, _rep_headers(rep_user_id)))


def approve_distribution(estate_id, dist_id):
    v = _estate_version(estate_id)
    return get_success_data(api_client.approve_distribution(
        dist_id, {"expected_estate_version": v}, JUDGE))


def pay_distribution(estate_id, dist_id, receipt_reference="RCPT",
                     rep_user_id="pr-user-1"):
    v = _estate_version(estate_id)
    return get_success_data(api_client.pay_distribution(
        dist_id,
        {"receipt_reference": receipt_reference, "expected_estate_version": v},
        _rep_headers(rep_user_id)))


def schedule_hearing(estate_id, courtroom_code, judge_user_id, start_at, end_at,
                     hearing_type="PETITION"):
    payload = {
        "estate_id": estate_id,
        "hearing_type": hearing_type,
        "courtroom_code": courtroom_code,
        "judge_user_id": judge_user_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    return get_success_data(api_client.create_hearing(payload, CLERK))
