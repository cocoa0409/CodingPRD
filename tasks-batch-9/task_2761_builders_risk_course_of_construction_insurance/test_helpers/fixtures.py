"""Composite setup chains.

Every test starts against an empty database, so any state richer than a single
POST has to be assembled here from the endpoints the contract publishes. The
chains below climb the account lifecycle: submitted project -> screened project
-> draft policy with a coverage and insured schedule -> quoted -> bound ->
in force, and from there claims, payments, storage and testing exposures.
"""
from dataclasses import dataclass, field

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import add_days
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_loss_payee_headers,
)

UW = TEST_USERS["underwriter_headers"]
UW2 = TEST_USERS["underwriter_2_headers"]
UM = TEST_USERS["manager_headers"]
UM2 = TEST_USERS["manager_2_headers"]
RE = TEST_USERS["risk_engineer_headers"]
CA = TEST_USERS["claim_adjuster_headers"]
CA2 = TEST_USERS["claim_adjuster_2_headers"]

# The canonical coverage schedule. Only SOFT_COST and DELAY_IN_COMPLETION feed
# the soft-cost premium component, so this schedule prices at 2750440 cents.
DEFAULT_PART_PLAN = (
    ("MATERIALS_ON_SITE", 1000000000),
    ("IN_TRANSIT", 200000000),
    ("SOFT_COST", 300000000),
    ("DELAY_IN_COMPLETION", 250000000),
)


@dataclass
class Account:
    """A policy under assembly together with everything hanging off it."""

    project: dict
    policy: dict = None
    parts: dict = field(default_factory=dict)
    interests: list = field(default_factory=list)

    @property
    def project_id(self):
        return self.project["id"]

    @property
    def policy_id(self):
        return self.policy["id"]

    @property
    def owner_interest(self):
        for interest in self.interests:
            if interest["party_role"] == "OWNER":
                return interest
        raise AssertionError("account has no OWNER interest")

    def part(self, part_type):
        return self.parts[part_type]

    def refresh_project(self, headers=UW):
        self.project = get_success_data(
            api_client.get_project(self.project_id, headers))
        return self.project

    def refresh_policy(self, headers=UW):
        self.policy = get_success_data(
            api_client.get_policy(self.policy_id, headers))
        return self.policy

    def refresh_parts(self, headers=UW):
        response = api_client.list_policy_coverage_parts(
            self.policy_id, headers, params={"limit": 100})
        for part in get_success_data(response):
            self.parts[part["part_type"]] = part
        return self.parts

    def refresh_interests(self, headers=UW):
        response = api_client.list_policy_named_insured_interests(
            self.policy_id, headers, params={"limit": 100})
        self.interests = get_success_data(response)
        return self.interests


def set_clock(current_utc, headers=UW):
    """Move the logical clock; the response reports the expiry sweep counters."""
    return get_success_data(api_client.set_clock(current_utc, headers))


def submit_project(headers=UW, **overrides) -> dict:
    return get_success_data(
        api_client.create_project(f.create_project_payload(**overrides), headers),
        expected_status=201)


def screen_project(project, engineering_grade="B", headers=RE, **overrides) -> dict:
    payload = f.screen_project_payload(
        engineering_grade=engineering_grade, **overrides)
    return get_success_data(
        api_client.screen_project(project["id"], payload, headers))


def eligible_project(engineering_grade="B", headers=UW, **overrides) -> dict:
    """Submit and screen in one step; the result is ELIGIBLE."""
    project = submit_project(headers=headers, **overrides)
    return screen_project(project, engineering_grade=engineering_grade)


def gulfside_project_overrides() -> dict:
    """FRAME / FLOOD_A account whose submission score lands exactly on 75."""
    return gulfside_project_inputs()


def cedar_lane_project_overrides() -> dict:
    """Small FIRE_RESISTIVE / INLAND account that prices at the premium floor."""
    return {
        "name": "Cedar Lane Cottages",
        "construction_type": "FIRE_RESISTIVE",
        "cat_zone": "INLAND",
        "hard_cost_value_cents": 312500000,
    }


def schedule_part(account, part_type, sublimit_cents, headers=UW, **overrides) -> dict:
    payload = f.create_coverage_part_payload(
        account.policy_id, part_type=part_type,
        sublimit_cents=sublimit_cents, **overrides)
    part = get_success_data(
        api_client.create_coverage_part(payload, headers), expected_status=201)
    account.parts[part_type] = part
    account.refresh_policy(headers)
    return part


def add_interest(account, party_role="OWNER", insurable_interest_pct=100,
                 headers=UW, **overrides) -> dict:
    # loss_payee_priority is unique within a policy, so hand out the next free one.
    if "loss_payee_priority" not in overrides:
        taken = [i.get("loss_payee_priority") for i in account.interests]
        overrides["loss_payee_priority"] = 1 + len(
            [value for value in taken if value is not None])
    payload = f.create_interest_payload(
        account.policy_id, party_role=party_role,
        insurable_interest_pct=insurable_interest_pct, **overrides)
    interest = get_success_data(
        api_client.create_named_insured_interest(payload, headers),
        expected_status=201)
    account.interests.append(interest)
    account.refresh_policy(headers)
    return interest


def acknowledge_interest(account, interest) -> dict:
    """The named party acknowledges its own row; X-User-ID is the interest id."""
    acknowledged = get_success_data(api_client.acknowledge_interest(
        interest["id"], make_loss_payee_headers(interest["id"])))
    for index, existing in enumerate(account.interests):
        if existing["id"] == acknowledged["id"]:
            account.interests[index] = acknowledged
    return acknowledged


def draft_account(project=None, parts=DEFAULT_PART_PLAN, with_owner=True,
                  headers=UW, project_overrides=None, **policy_overrides) -> Account:
    """A DRAFT policy with its coverage schedule and an acknowledged owner."""
    if project is None:
        project = eligible_project(**(project_overrides or {}))
    account = Account(project=project)
    payload = f.create_policy_payload(
        project["id"], project["version"], **policy_overrides)
    account.policy = get_success_data(
        api_client.create_policy(payload, headers), expected_status=201)
    account.refresh_project(headers)
    for part_type, sublimit_cents in parts or ():
        schedule_part(account, part_type, sublimit_cents, headers=headers)
    if with_owner:
        owner = add_interest(account, headers=headers)
        acknowledge_interest(account, owner)
    return account


def quote_account(account, headers=UW) -> Account:
    account.policy = get_success_data(
        api_client.quote_policy(account.policy_id, headers))
    return account


def approve_referral(account, referral_load_pct=None, headers=UM) -> Account:
    payload = {"decision": "APPROVE"}
    if referral_load_pct is not None:
        payload["referral_load_pct"] = referral_load_pct
    account.policy = get_success_data(
        api_client.referral_decision(account.policy_id, payload, headers))
    return account


def bind_account(account, headers=UW) -> Account:
    account.policy = get_success_data(
        api_client.bind_policy(account.policy_id, headers))
    return account


def incept_account(account, headers=UW) -> Account:
    """The clock has to reach term_start_date before the risk can attach."""
    set_clock(account.policy["term_start_date"], headers)
    account.policy = get_success_data(
        api_client.incept_policy(account.policy_id, headers))
    account.refresh_project(headers)
    account.refresh_parts(headers)
    account.refresh_interests(headers)
    return account


def quoted_account(parts=DEFAULT_PART_PLAN, **kwargs) -> Account:
    return quote_account(draft_account(parts=parts, **kwargs))


def bound_account(parts=DEFAULT_PART_PLAN, **kwargs) -> Account:
    return bind_account(quoted_account(parts=parts, **kwargs))


def in_force_account(parts=DEFAULT_PART_PLAN, **kwargs) -> Account:
    """The workhorse fixture: an IN_FORCE policy on an UNDER_CONSTRUCTION project."""
    return incept_account(bound_account(parts=parts, **kwargs))


def declare_substantial_completion(account, when, headers=UW, advance_clock=True):
    """Delay cover only unlocks once the site has declared completion."""
    if advance_clock:
        set_clock(when, headers)
    account.project = get_success_data(api_client.declare_substantial_completion(
        account.project_id, f.substantial_completion_payload(when), headers))
    return account.project


def file_endorsement(account, requested_extension_days, headers=UW,
                     revised_completion_date=None, **overrides) -> dict:
    """Price a schedule slip; the revised date has to reconcile with the days."""
    account.refresh_policy(headers)
    if revised_completion_date is None:
        revised_completion_date = add_days(
            account.policy["adjusted_completion_date"], requested_extension_days)
    payload = f.create_endorsement_payload(
        account.policy_id, account.policy["version"],
        requested_extension_days, revised_completion_date, **overrides)
    endorsement = get_success_data(
        api_client.create_extension_endorsement(payload, headers),
        expected_status=201)
    account.refresh_policy(headers)
    return endorsement


def decide_endorsement(account, endorsement, decision="APPROVE", headers=UM,
                       **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    decided = get_success_data(
        api_client.decide_endorsement(endorsement["id"], payload, headers))
    account.refresh_policy()
    account.refresh_project()
    return decided


def approved_endorsement(account, requested_extension_days, filer=UW,
                         decider=UM, **overrides) -> dict:
    endorsement = file_endorsement(
        account, requested_extension_days, headers=filer, **overrides)
    return decide_endorsement(account, endorsement, "APPROVE", headers=decider)


def report_claim(account, peril="FIRE", loss_date="2027-02-10T00:00:00Z",
                 headers=CA, **overrides) -> dict:
    payload = f.create_claim_payload(
        account.policy_id, peril=peril, loss_date=loss_date, **overrides)
    return get_success_data(
        api_client.create_claim(payload, headers), expected_status=201)


def adjust_claim(account, claim, loss_items=None,
                 adjustment_basis="ACTUAL_LOSS", headers=CA, **overrides) -> dict:
    payload = f.adjust_claim_payload(
        outcome="ADJUST", adjustment_basis=adjustment_basis,
        loss_items=loss_items, **overrides)
    adjusted = get_success_data(
        api_client.adjust_claim(claim["id"], payload, headers))
    account.refresh_project()
    return adjusted


def adjusted_claim(account, loss_items, adjustment_basis="ACTUAL_LOSS",
                   peril="FIRE", loss_date="2027-02-10T00:00:00Z",
                   headers=CA, **overrides) -> dict:
    claim = report_claim(account, peril=peril, loss_date=loss_date, headers=headers)
    return adjust_claim(account, claim, loss_items=loss_items,
                        adjustment_basis=adjustment_basis, headers=headers, **overrides)


def settle_claim(claim, headers=CA2) -> dict:
    """Settlement is a checker step: never the adjuster who valued the claim."""
    return get_success_data(api_client.settle_claim(claim["id"], headers))


def settled_claim(account, loss_items, adjustment_basis="ACTUAL_LOSS",
                  **kwargs) -> dict:
    claim = adjusted_claim(account, loss_items,
                           adjustment_basis=adjustment_basis, **kwargs)
    return settle_claim(claim)


def issue_payment(account, claim, part_type, amount_cents, payee=None,
                  headers=CA, **overrides) -> dict:
    interest = payee or account.owner_interest
    payload = f.create_loss_payment_payload(
        claim["id"], claim["version"], interest["id"], part_type,
        amount_cents, **overrides)
    payment = get_success_data(
        api_client.create_loss_payment(payload, headers), expected_status=201)
    account.refresh_policy()
    account.refresh_parts()
    return payment


def void_payment(account, payment, headers=UM) -> dict:
    voided = get_success_data(api_client.void_loss_payment(payment["id"], headers))
    account.refresh_policy()
    account.refresh_parts()
    return voided


def register_facility(headers=RE, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility(f.create_facility_payload(**overrides), headers),
        expected_status=201)


def suspend_facility(facility, headers=RE) -> dict:
    return get_success_data(api_client.patch_facility(
        facility["id"], {"status": "SUSPENDED"}, headers))


def reinstate_facility(facility, headers=RE) -> dict:
    return get_success_data(api_client.patch_facility(
        facility["id"], {"status": "ACTIVE"}, headers))


def assign_storage(account, facility, stored_value_cents, window_start,
                   window_end, headers=UW, **overrides) -> dict:
    payload = f.create_storage_assignment_payload(
        account.policy_id, facility["id"], stored_value_cents,
        window_start, window_end, **overrides)
    return get_success_data(
        api_client.create_storage_assignment(payload, headers),
        expected_status=201)


def release_storage(assignment, headers=UW) -> dict:
    return get_success_data(
        api_client.release_storage_assignment(assignment["id"], headers))


def schedule_notice(account, window_start, window_end,
                    system_type="SPRINKLER_HYDROSTATIC", headers=RE,
                    **overrides) -> dict:
    payload = f.create_testing_notice_payload(
        account.project_id, window_start, window_end,
        system_type=system_type, **overrides)
    return get_success_data(
        api_client.create_testing_notice(payload, headers), expected_status=201)


def decide_notice(notice, decision="APPROVE", headers=RE, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api_client.decide_testing_notice(notice["id"], payload, headers))


def approved_notice(account, window_start, window_end, **kwargs) -> dict:
    notice = schedule_notice(account, window_start, window_end, **kwargs)
    return decide_notice(notice, "APPROVE")


def cancel_account(account, cancel_reason="INSURED_REQUEST",
                   cancel_effective_date=None, headers=UM) -> dict:
    account.policy = get_success_data(api_client.cancel_policy(
        account.policy_id,
        f.cancel_policy_payload(cancel_reason, cancel_effective_date),
        headers))
    return account.policy


def premium_ledger(account, headers=UW) -> list:
    response = api_client.list_policy_premium_transactions(
        account.policy_id, headers, params={"limit": 100})
    return get_success_data(response)


def premium_summary(account, headers=UW) -> dict:
    return get_success_data(api_client.get_premium_summary(account.policy_id, headers))


# The Gulfside account: a FRAME tower in FLOOD_A whose submission score lands
# exactly on the 75-point referral threshold, so it rates to REFERRED.
GULFSIDE_PART_PLAN = (
    ("MATERIALS_ON_SITE", 6000000000),
    ("SOFT_COST", 500000000),
    ("DELAY_IN_COMPLETION", 400000000),
)


def gulfside_project_inputs() -> dict:
    return {
        "name": "Gulfside Frame Towers",
        "site_address": "88 Bayou Blvd, Gulfport",
        "construction_type": "FRAME",
        "project_kind": "NEW_CONSTRUCTION",
        "hard_cost_value_cents": 7500000000,
        "cat_zone": "FLOOD_A",
        "planned_start_date": "2026-09-01T00:00:00Z",
        "projected_completion_date": "2027-08-25T00:00:00Z",
        "engineering_grade": "C",
    }


def gulfside_policy_inputs() -> dict:
    return {
        "term_start_date": "2026-09-01T00:00:00Z",
        "term_end_date": "2027-08-31T00:00:00Z",
        "deductible_tier": "HIGH_250K",
        "limit_cents": 8000000000,
        "daily_delay_rate_cents": 5000000,
    }


def gulfside_referred_account() -> Account:
    """A REFERRED policy: rated at 20385450 on a 364-day term."""
    return quoted_account(
        parts=GULFSIDE_PART_PLAN,
        project_overrides=gulfside_project_inputs(),
        **gulfside_policy_inputs())


def gulfside_in_force_account(referral_load_pct=0.10) -> Account:
    """The referred account approved with a load, bound and incepted."""
    account = gulfside_referred_account()
    approve_referral(account, referral_load_pct=referral_load_pct)
    return incept_account(bind_account(account))
