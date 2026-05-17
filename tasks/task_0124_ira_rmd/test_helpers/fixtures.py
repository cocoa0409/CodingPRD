"""Composite setup helpers — multi-step preambles tests can reuse.

The IRA pipeline is long: clock set -> participant create -> account
open -> (optional) contributions to seed balance -> year-roll to
snapshot prior_year_end_balance_cents -> (optional) conversion request
create / approve / complete -> distributions / RMD.

IDENTITY THREADING — PRD §2.1:

- Custodian / ComplianceOfficer / Auditor are OPAQUE. Shared constants
  (custodian_headers, compliance_headers, auditor_headers) are
  canonical for every operator-only call.

- Participant is ENTITY-BACKED. Every Participant-driven call whose
  success depends on owning the targeted resource MUST mint headers
  via make_participant_headers(participant["id"]) — never via the
  shared PARTICIPANT_FALLBACK_ID. The fixtures here return the actual
  Participant row so consumer tests / consumer fixtures can route
  participant-acting calls through this header builder.

SEGREGATION OF DUTIES — PRD §2.1: a Custodian whose X-User-ID equals
the requesting participant's id cannot approve that participant's own
conversion request. The default custodian id used in these fixtures
is custodian-001, which never equals any minted Participant.id;
fixtures that intentionally trigger ERR_SEGREGATION_VIOLATION pass
make_custodian_headers(participant["id"]) explicitly.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_advance_payload,
    create_account_payload,
    create_contribution_payload,
    create_conversion_request_payload,
    create_distribution_payload,
    create_participant_payload,
    decease_participant_payload,
    iso_date_str,
    random_full_name,
)
from .test_users import (
    TEST_USERS,
    make_participant_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.10
# ===========================================================================
def get_clock_state(headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    """GET /_clock. Returns the parsed data payload.

    PRD §2.10: 'The clock-read endpoint returns the current logical
    date and clock year without mutating anything.' The exact field
    names are not pinned by the PRD; tests/fixtures should access
    `clock_year` first, fall back to `current_year`, then derive from
    `current_date` if neither is present.
    """
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.get_clock(headers)
    return get_success_data(resp)


def clock_year_of(state: Dict[str, Any]) -> int:
    """Extract the clock year integer from a ClockState dict in a
    PRD-silent-name-tolerant way."""
    for key in ("clock_year", "current_year", "year"):
        v = state.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    # Fall back to year-portion of current_date if it's ISO 8601.
    cd = state.get("current_date") or state.get("today")
    if isinstance(cd, str) and len(cd) >= 4 and cd[:4].isdigit():
        return int(cd[:4])
    raise AssertionError(
        f"could not extract clock year from ClockState: {state!r}"
    )


def advance_clock_days(days: int,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """POST /_clock/advance days=N. Returns ClockState dict."""
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.clock_advance(clock_advance_payload(days=days),
                                    headers)
    return get_success_data(resp)


def advance_clock_year(headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """POST /_clock/advance-year. Runs snapshot, ytd reset, excess sweep,
    missed-RMD sweep."""
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.clock_advance_year(None, headers)
    return get_success_data(resp)


def advance_clock_to_year(target_year: int,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    """Roll the clock forward year-by-year until clock_year == target_year.
    Useful when tests need the clock at a specific reporting year.
    """
    state = get_clock_state(headers)
    current = clock_year_of(state)
    while current < target_year:
        state = advance_clock_year(headers)
        try:
            new_year = clock_year_of(state)
        except AssertionError:
            new_year = current + 1
        if new_year <= current:
            break  # avoid infinite loop if response doesn't advance
        current = new_year
    return state


# ===========================================================================
# Tier 1: Participant + Account creation — PRD §3.1, §3.2
# ===========================================================================
def create_participant(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    tax_status: str = "SINGLE",
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /participants. Returns the created Participant dict.

    PRD §3.1: only a Custodian may create a Participant.
    """
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    payload = create_participant_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        tax_status=tax_status,
    )
    resp = api_client.create_participant(payload, custodian_headers)
    return get_success_data(resp)


def create_participant_born(
    year: int,
    month: int = 1,
    day: int = 15,
    *,
    tax_status: str = "SINGLE",
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Convenience: create a participant with a specific date_of_birth.
    Used for age-boundary tests (catchup, RMD age 73, early-distribution
    age 59 threshold).
    """
    return create_participant(
        date_of_birth=iso_date_str(date(year, month, day)),
        tax_status=tax_status,
        custodian_headers=custodian_headers,
    )


def open_account(
    participant_id: str,
    *,
    account_type: str = "TRADITIONAL",
    inherited_from_participant_id: Optional[str] = None,
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /participants/{participant_id}/accounts. Returns Account dict.

    PRD §3.2: only a Custodian may open accounts. When
    inherited_from_participant_id is supplied a BeneficiaryClaim is also
    created.
    """
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    payload = create_account_payload(
        account_type=account_type,
        inherited_from_participant_id=inherited_from_participant_id,
    )
    resp = api_client.create_account(participant_id, payload,
                                     custodian_headers)
    return get_success_data(resp)


def get_account(participant_id: str, account_id: str,
                headers: Optional[Dict[str, str]] = None
                ) -> Dict[str, Any]:
    """GET /participants/{pid}/accounts/{aid}. Returns latest Account
    snapshot. Defaults to custodian headers so the call always passes the
    self-only scope check."""
    headers = headers or TEST_USERS["custodian_headers"]
    resp = api_client.get_account(participant_id, account_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Contributions — PRD §3.3
# ===========================================================================
def post_contribution(
    account_id: str,
    *,
    amount_cents: int,
    contribution_type: str = "REGULAR",
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{id}/contributions, posted by a Custodian.

    PRD §3.3: both Participant and Custodian may post. Defaulting to
    Custodian avoids the ownership burden in setup paths; tests that
    explicitly want a Participant-acting contribution should call
    api_client.create_contribution directly with
    make_participant_headers(participant["id"]).
    """
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    payload = create_contribution_payload(
        amount_cents=amount_cents,
        contribution_type=contribution_type,
    )
    resp = api_client.create_contribution(account_id, payload,
                                          custodian_headers)
    return get_success_data(resp)


def reverse_contribution(contribution_id: str,
                         custodian_headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """POST /contributions/{id}/reverse, by Custodian.
    PRD §3.3."""
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    resp = api_client.reverse_contribution(contribution_id,
                                           custodian_headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Account-posture transitions — PRD §3.2
# ===========================================================================
def freeze_account(account_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["custodian_headers"]
    resp = api_client.freeze_account(account_id, headers)
    return get_success_data(resp)


def unfreeze_account(account_id: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["custodian_headers"]
    resp = api_client.unfreeze_account(account_id, headers)
    return get_success_data(resp)


def close_account(account_id: str,
                  custodian_headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    resp = api_client.close_account(account_id, custodian_headers)
    return get_success_data(resp)


def decease_participant(participant_id: str,
                        *,
                        date_of_death: str,
                        custodian_headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    """POST /participants/{id}/decease — Custodian only."""
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    payload = decease_participant_payload(date_of_death=date_of_death)
    resp = api_client.decease_participant(participant_id, payload,
                                          custodian_headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 4: RMD-targeting setup — seeds prior_year_end_balance_cents
# ===========================================================================
def seed_prior_year_balance(
    *,
    participant: Dict[str, Any],
    account: Dict[str, Any],
    balance_cents: int,
) -> Dict[str, Any]:
    """Drive Account.prior_year_end_balance_cents to a known value.

    Strategy: post REGULAR contributions until Account.balance_cents
    reaches `balance_cents`, then advance the clock by one year so the
    year-roll endpoint snapshots balance_cents into
    prior_year_end_balance_cents and resets ytd_contribution_cents to 0.

    Because annual REGULAR/CATCHUP contribution caps apply (PRD §3.3),
    this fixture posts across multiple years if needed, calling
    advance_clock_year between fills. Each year's posting stays under
    the applicable cap (REGULAR base = 700_000 cents; CATCHUP +100_000
    if participant is age >= 50 on Dec 31).

    Returns the Account snapshot after the year-roll.
    """
    custodian = TEST_USERS["custodian_headers"]
    target = balance_cents
    # Re-read account to learn current balance + age-cap context.
    acct = get_account(participant["id"], account["id"], custodian)
    current = int(acct["balance_cents"])
    # Determine the per-year contribution ceiling for this participant
    # to stay below ERR_CONTRIBUTION_CAP_EXCEEDED.
    dob = participant["date_of_birth"]
    birth_year = int(dob[:4])
    state = get_clock_state(custodian)
    clock_year = clock_year_of(state)
    while current < target:
        age_dec31 = clock_year - birth_year
        per_year_cap = 700_000 + (100_000 if age_dec31 >= 50 else 0)
        # ytd_contribution_cents may already be non-zero this year.
        acct = get_account(participant["id"], account["id"], custodian)
        ytd = int(acct["ytd_contribution_cents"])
        room_this_year = per_year_cap - ytd
        needed = target - int(acct["balance_cents"])
        if room_this_year <= 0:
            # Year is full; roll to next year and try again.
            advance_clock_year(custodian)
            state = get_clock_state(custodian)
            clock_year = clock_year_of(state)
            continue
        # Post in chunks of at most MAX_SINGLE_CONTRIBUTION_CENTS (1_000_000).
        chunk = min(needed, room_this_year, 1_000_000)
        post_contribution(
            account["id"],
            amount_cents=chunk,
            contribution_type="REGULAR",
            custodian_headers=custodian,
        )
        acct = get_account(participant["id"], account["id"], custodian)
        current = int(acct["balance_cents"])
    # Now advance one year so the current balance becomes
    # prior_year_end_balance_cents.
    advance_clock_year(custodian)
    return get_account(participant["id"], account["id"], custodian)


# ===========================================================================
# Tier 5: Conversion request lifecycle — PRD §3.7
# ===========================================================================
def create_conversion_request(
    *,
    participant: Dict[str, Any],
    source_account: Dict[str, Any],
    destination_account: Dict[str, Any],
    amount_cents: int,
    backdoor_flag: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /conversion-requests. ENTITY-BACKED Participant call —
    headers default to make_participant_headers(participant['id']).

    PRD §2.1: Participant is the only role that may create a
    ConversionRequest, and the ConversionRequest.participant_id is
    threaded from X-User-ID.
    """
    headers = headers or make_participant_headers(participant["id"])
    payload = create_conversion_request_payload(
        source_account_id=source_account["id"],
        destination_account_id=destination_account["id"],
        amount_cents=amount_cents,
        backdoor_flag=backdoor_flag,
    )
    resp = api_client.create_conversion_request(payload, headers)
    return get_success_data(resp)


def approve_conversion_request(
    conversion_id: str,
    *,
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /conversion-requests/{id}/approve.

    Defaults to a Custodian whose X-User-ID never equals any
    Participant.id (custodian-001). Tests that wish to trigger
    ERR_SEGREGATION_VIOLATION must pass
    make_custodian_headers(participant['id']) explicitly.
    """
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    resp = api_client.approve_conversion_request(conversion_id,
                                                 custodian_headers)
    return get_success_data(resp)


def complete_conversion_request(
    conversion_id: str,
    *,
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /conversion-requests/{id}/complete."""
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    resp = api_client.complete_conversion_request(conversion_id,
                                                  custodian_headers)
    return get_success_data(resp)


def reject_conversion_request(
    conversion_id: str,
    *,
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    resp = api_client.reject_conversion_request(conversion_id,
                                                custodian_headers)
    return get_success_data(resp)


def cancel_conversion_request(
    conversion_id: str,
    *,
    participant: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /conversion-requests/{id}/cancel — Participant-only.

    PRD §3.7: 'the cancel endpoint requires the canceller's X-User-ID
    to equal the request's participant_id'. Mints headers via
    make_participant_headers to satisfy that ownership check.
    """
    headers = make_participant_headers(participant["id"])
    resp = api_client.cancel_conversion_request(conversion_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 6: Distributions & RMD — PRD §3.4, §3.5
# ===========================================================================
def take_distribution(
    account_id: str,
    *,
    gross_amount_cents: int,
    distribution_reason: str = "NORMAL",
    custodian_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{id}/distributions, by Custodian."""
    custodian_headers = custodian_headers or TEST_USERS["custodian_headers"]
    payload = create_distribution_payload(
        gross_amount_cents=gross_amount_cents,
        distribution_reason=distribution_reason,
    )
    resp = api_client.create_distribution(account_id, payload,
                                          custodian_headers)
    return get_success_data(resp)


def get_rmd_quote(account_id: str,
                  *,
                  tax_year: int,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.get_rmd(account_id, headers,
                              params={"tax_year": tax_year})
    return get_success_data(resp)


# ===========================================================================
# Tier 7: Beneficiary-claim helpers — PRD §3.6
# ===========================================================================
def get_beneficiary_claim(claim_id: str,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.get_beneficiary_claim(claim_id, headers)
    return get_success_data(resp)


def suspend_beneficiary_claim(claim_id: str,
                              headers: Optional[Dict[str, str]] = None
                              ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_headers"]
    resp = api_client.suspend_beneficiary_claim(claim_id, headers)
    return get_success_data(resp)


def resume_beneficiary_claim(claim_id: str,
                             headers: Optional[Dict[str, str]] = None
                             ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_headers"]
    resp = api_client.resume_beneficiary_claim(claim_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 8: Forms 1099-R — PRD §3.9
# ===========================================================================
def list_forms_1099r(participant_id: str,
                     *,
                     tax_year: int,
                     limit: Optional[int] = None,
                     offset: Optional[int] = None,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """GET /participants/{id}/forms-1099r?tax_year=YYYY.

    Returns (data_list, meta_dict). Defaults to Custodian headers to
    avoid ownership burden in setup.
    """
    headers = headers or TEST_USERS["custodian_headers"]
    params: Dict[str, Any] = {"tax_year": tax_year}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    resp = api_client.list_forms_1099r(participant_id, headers,
                                       params=params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data, {}
    # Some implementations wrap list payload under data; tolerate both.
    if isinstance(data, dict) and "data" in data and isinstance(
        data["data"], list,
    ):
        return data["data"], data.get("meta", {})
    return data if isinstance(data, list) else [], {}


# ===========================================================================
# Composite setups — multi-step preambles driven by SCAFFOLD_DIFFICULTY_DESIGN
# ===========================================================================

def setup_owner_rmd_eligible(
    *,
    target_age_on_dec31: int = 73,
    dob_year: Optional[int] = None,
    dob_month: int = 1,
    dob_day: int = 15,
    prior_year_end_balance_cents: int = 10_000_000,
    tax_status: str = "SINGLE",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an RMD-eligible TRADITIONAL account for an original owner.

    The fixture seeds the requested prior_year_end_balance_cents and
    then ensures the participant's age on Dec 31 of the final clock
    year is exactly target_age_on_dec31. It does this by:
      1. Creating a placeholder participant born long ago (so the
         clock-only seeding can complete without cap-age constraints).
         Actually, contributions are scoped to the actual participant,
         so we create the real participant up-front but choose their
         dob_year dynamically AFTER we estimate the post-seeding clock
         year, so the participant ends up at target_age_on_dec31 on
         Dec 31 of that year.

    For backward compatibility, if dob_year is supplied explicitly it
    is used as-is and target_age_on_dec31 is ignored. Tests that pin
    expected RMD values to a specific divisor (e.g., 26.5 at age 73)
    should leave dob_year as None and rely on target_age_on_dec31.

    Returns (participant, account) where the account's
    prior_year_end_balance_cents == prior_year_end_balance_cents and
    the participant's age on Dec 31 of the current clock year ==
    target_age_on_dec31.
    """
    custodian = TEST_USERS["custodian_headers"]
    # Pick the per-year cap based on what initial age the dob will land at.
    # For target_age_on_dec31 such that the participant will be age >= 50
    # throughout seeding, the catchup cap of 800K applies; the loop will
    # then complete in ceil(balance/800K) year-rolls. The trial below picks
    # dob = final_clock_year - target_age and then verifies the math.
    def _estimate_years(use_catchup: bool) -> int:
        per_year_cap = 800_000 if use_catchup else 700_000
        return (
            prior_year_end_balance_cents + per_year_cap - 1
        ) // per_year_cap
    # First attempt: assume catchup applies (target_age implies initial age
    # >= 50, which is true for any target_age >= 50 + years_needed_catchup).
    estimated_years = _estimate_years(use_catchup=True)
    clock_now = get_clock_state(custodian)
    cur_year = clock_year_of(clock_now)
    final_clock_year = cur_year + estimated_years
    if dob_year is None:
        candidate_dob = final_clock_year - target_age_on_dec31
        # Verify candidate's initial age would actually be >= 50 (so cap=800K
        # holds throughout). If not, fall back to under-50 cap and recompute.
        initial_age = cur_year - candidate_dob
        if initial_age < 50:
            estimated_years = _estimate_years(use_catchup=False)
            final_clock_year = cur_year + estimated_years
            candidate_dob = final_clock_year - target_age_on_dec31
        dob_year = candidate_dob
    p = create_participant_born(dob_year, dob_month, dob_day,
                                tax_status=tax_status)
    a = open_account(p["id"], account_type="TRADITIONAL")
    a = seed_prior_year_balance(
        participant=p, account=a,
        balance_cents=prior_year_end_balance_cents,
    )
    return p, a


def setup_inherited_account(
    *,
    decedent_dob_year: int = 1948,
    beneficiary_target_age_on_dec31: int = 50,
    beneficiary_dob_year: Optional[int] = None,
    beneficiary_dob_month: int = 1,
    beneficiary_dob_day: int = 15,
    prior_year_end_balance_cents: int = 10_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[str]]:
    """Create an Inherited IRA for `beneficiary` referencing a
    `decedent` participant. Returns (beneficiary, inherited_account,
    claim_id_or_None).

    The inheritance starts on the current clock day, so deadline_date
    is claim_date + 10 years (PRD §3.2).

    Prior-year-end balance is seeded by posting contributions and then
    year-rolling. The contributions are scoped to the beneficiary's
    cap. The dob is computed dynamically (unless beneficiary_dob_year
    is supplied) so that beneficiary age on Dec 31 of the FINAL clock
    year equals beneficiary_target_age_on_dec31. This is how RMD-math
    tests pin expected values (e.g., divisor 36.2 at age 50 ->
    10_000_000 / 36.2 = 276_243).
    """
    custodian = TEST_USERS["custodian_headers"]
    estimated_years = (
        prior_year_end_balance_cents + 700_000 - 1
    ) // 700_000
    clock_now = get_clock_state(custodian)
    cur_year = clock_year_of(clock_now)
    final_clock_year = cur_year + estimated_years
    if beneficiary_dob_year is None:
        beneficiary_dob_year = (
            final_clock_year - beneficiary_target_age_on_dec31
        )
    decedent = create_participant_born(decedent_dob_year, 1, 1)
    beneficiary = create_participant_born(
        beneficiary_dob_year,
        beneficiary_dob_month,
        beneficiary_dob_day,
    )
    inherited = open_account(
        beneficiary["id"],
        account_type="TRADITIONAL",
        inherited_from_participant_id=decedent["id"],
    )
    inherited = seed_prior_year_balance(
        participant=beneficiary, account=inherited,
        balance_cents=prior_year_end_balance_cents,
    )
    return beneficiary, inherited, find_claim_id_from_account(inherited)


def find_claim_id_from_account(account: Dict[str, Any]) -> Optional[str]:
    """Best-effort lookup of the auto-created BeneficiaryClaim id from
    an inherited Account row.

    PRD §3.2 guarantees the claim is created with the inherited
    account, and PRD §4 exposes GET /beneficiary-claims/{claim_id};
    the field name used to surface the id on the Account row is not
    pinned by the PRD, so this helper tries the common candidates.
    Returns None if none of the candidate field names are present.
    """
    for candidate in (
        "beneficiary_claim_id",
        "claim_id",
        "beneficiary_claim",
    ):
        val = account.get(candidate)
        if isinstance(val, str) and val:
            return val
        if isinstance(val, dict) and isinstance(val.get("id"), str):
            return val["id"]
    return None


def setup_inherited_with_claim(
    *,
    beneficiary_dob_year: int = 1976,
    decedent_dob_year: int = 1948,
    balance_cents: int = 5_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[str]]:
    """Inherited IRA seeded to a CURRENT balance of `balance_cents`
    (NOT snapshotted into prior_year). Useful for deadline / forfeit
    tests.

    Returns (beneficiary, account, claim_id_or_None).
    """
    decedent = create_participant_born(decedent_dob_year, 1, 1)
    beneficiary = create_participant_born(beneficiary_dob_year, 1, 15)
    acct = open_account(
        beneficiary["id"],
        account_type="TRADITIONAL",
        inherited_from_participant_id=decedent["id"],
    )
    # Post contributions up to balance_cents without year-rolling, so
    # the live balance is at `balance_cents` and prior_year is 0.
    custodian = TEST_USERS["custodian_headers"]
    remaining = balance_cents
    while remaining > 0:
        a_now = get_account(beneficiary["id"], acct["id"], custodian)
        ytd = int(a_now["ytd_contribution_cents"])
        cap_this_year = 700_000  # conservative; beneficiary age unknown
        room = cap_this_year - ytd
        if room <= 0:
            advance_clock_year(custodian)
            continue
        chunk = min(remaining, room, 1_000_000)
        post_contribution(acct["id"], amount_cents=chunk,
                          contribution_type="REGULAR",
                          custodian_headers=custodian)
        remaining -= chunk
    acct = get_account(beneficiary["id"], acct["id"], custodian)
    return beneficiary, acct, find_claim_id_from_account(acct)


def setup_traditional_to_roth_pair(
    *,
    participant_dob_year: int = 1980,
    seed_source_balance_cents: int = 700_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a Participant with a TRADITIONAL account (seeded balance)
    and a ROTH account (empty). Returns (participant, traditional,
    roth)."""
    p = create_participant_born(participant_dob_year, 1, 15)
    trad = open_account(p["id"], account_type="TRADITIONAL")
    roth = open_account(p["id"], account_type="ROTH")
    if seed_source_balance_cents > 0:
        # Stay within REGULAR cap (700_000) within the same year; if
        # caller asks for more, fail loudly rather than silently looping
        # because tests downstream rely on TRADITIONAL holding ONLY
        # this fresh contribution.
        if seed_source_balance_cents > 700_000:
            raise ValueError(
                "setup_traditional_to_roth_pair: "
                "seed_source_balance_cents must be <= 700_000 "
                "(annual REGULAR cap). Use a larger pipeline if "
                "more balance is needed."
            )
        post_contribution(trad["id"],
                          amount_cents=seed_source_balance_cents,
                          contribution_type="REGULAR")
        trad = get_account(p["id"], trad["id"])
        roth = get_account(p["id"], roth["id"])
    return p, trad, roth


def setup_backdoor_pair(
    *,
    participant_dob_year: int = 1980,
    backdoor_amount_cents: int = 700_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a Participant with TRADITIONAL holding ONLY BACKDOOR_-
    NONDEDUCTIBLE contributions equal to backdoor_amount_cents, plus
    an empty ROTH. Returns (participant, traditional, roth).

    PRD §3.7: the Backdoor precondition requires the source account's
    balance_cents to equal the sum of POSTED BACKDOOR_NONDEDUCTIBLE
    contributions for the current tax_year, with no other postings and
    no accumulated earnings.
    """
    p = create_participant_born(participant_dob_year, 1, 15)
    trad = open_account(p["id"], account_type="TRADITIONAL")
    roth = open_account(p["id"], account_type="ROTH")
    if backdoor_amount_cents > 700_000:
        raise ValueError(
            "Backdoor amount exceeds per-call/per-year cap; PRD §3.3 "
            "constraints prevent a single-shot setup beyond 700_000."
        )
    post_contribution(trad["id"], amount_cents=backdoor_amount_cents,
                      contribution_type="BACKDOOR_NONDEDUCTIBLE")
    trad = get_account(p["id"], trad["id"])
    roth = get_account(p["id"], roth["id"])
    return p, trad, roth


def setup_approved_conversion(
    *,
    participant_dob_year: int = 1980,
    amount_cents: int = 700_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Create participant with TRADITIONAL+ROTH, seed source balance,
    create + APPROVE a conversion request. Returns (participant, trad,
    roth, conversion). Useful for completion-cascade tests."""
    p, trad, roth = setup_traditional_to_roth_pair(
        participant_dob_year=participant_dob_year,
        seed_source_balance_cents=amount_cents,
    )
    cr = create_conversion_request(
        participant=p, source_account=trad,
        destination_account=roth, amount_cents=amount_cents,
        backdoor_flag=False,
    )
    cr = approve_conversion_request(cr["id"])
    return p, trad, roth, cr


def setup_pending_conversion(
    *,
    participant_dob_year: int = 1980,
    amount_cents: int = 100_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Create participant with TRADITIONAL+ROTH, seed minor source
    balance, open a PENDING conversion request. Returns (participant,
    trad, roth, conversion)."""
    p, trad, roth = setup_traditional_to_roth_pair(
        participant_dob_year=participant_dob_year,
        seed_source_balance_cents=amount_cents,
    )
    cr = create_conversion_request(
        participant=p, source_account=trad,
        destination_account=roth, amount_cents=amount_cents,
        backdoor_flag=False,
    )
    return p, trad, roth, cr


__all__ = [
    "get_clock_state",
    "clock_year_of",
    "advance_clock_days",
    "advance_clock_year",
    "advance_clock_to_year",
    "find_claim_id_from_account",
    "create_participant",
    "create_participant_born",
    "open_account",
    "get_account",
    "post_contribution",
    "reverse_contribution",
    "freeze_account",
    "unfreeze_account",
    "close_account",
    "decease_participant",
    "seed_prior_year_balance",
    "create_conversion_request",
    "approve_conversion_request",
    "complete_conversion_request",
    "reject_conversion_request",
    "cancel_conversion_request",
    "take_distribution",
    "get_rmd_quote",
    "get_beneficiary_claim",
    "suspend_beneficiary_claim",
    "resume_beneficiary_claim",
    "list_forms_1099r",
    "setup_owner_rmd_eligible",
    "setup_inherited_account",
    "setup_inherited_with_claim",
    "setup_traditional_to_roth_pair",
    "setup_backdoor_pair",
    "setup_approved_conversion",
    "setup_pending_conversion",
]
