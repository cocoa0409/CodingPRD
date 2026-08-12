"""
Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient validator) so a setup failure
surfaces as a clear "setup failed" message rather than an assertion error.
Identity threading: ownership-gated Member-role calls always use
make_member_headers(member_id) with the actual Member.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    district_payload, member_payload, fiscal_year_payload, delivery_payload,
    delegate_payload, resolution_payload, cycle_payload,
    redemption_request_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
OPERATOR = TEST_USERS["operator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]
SECRETARY = TEST_USERS["secretary_headers"]


# ─── Tier 1: atomic builders ──────────────────────────

def set_clock(to_iso8601: str) -> dict:
    res = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(res)


def create_district(code=None, name="District", max_delegates=3) -> dict:
    res = api_client.create_delegate_district(
        district_payload(code=code, name=name, max_delegates=max_delegates),
        ADMIN,
    )
    return get_success_data(res)


def create_member(district_id, patron_ref=None, legal_name="Test Farm",
                  member_class="INDIVIDUAL", joined_at="2020-01-01T00:00:00Z",
                  is_producer_member=True, **overrides) -> dict:
    res = api_client.create_member(
        member_payload(
            district_id, patron_ref=patron_ref, legal_name=legal_name,
            member_class=member_class, joined_at=joined_at,
            is_producer_member=is_producer_member, **overrides,
        ),
        REGISTRAR,
    )
    return get_success_data(res)


def create_fiscal_year(year_code=None, net_margin_cents=100000,
                       retained_reserve_pct=0.10, qualified_payout_pct=0.30,
                       start_date="2025-09-01T00:00:00Z",
                       end_date="2026-08-31T00:00:00Z") -> dict:
    res = api_client.create_fiscal_year(
        fiscal_year_payload(
            year_code=year_code, net_margin_cents=net_margin_cents,
            retained_reserve_pct=retained_reserve_pct,
            qualified_payout_pct=qualified_payout_pct,
            start_date=start_date, end_date=end_date,
        ),
        ACCOUNTANT,
    )
    return get_success_data(res)


def book_delivery(member_id, fiscal_year_id, commodity="CORN",
                  gross_bushels=100, dockage_pct=0.0, is_patron_sourced=True,
                  **overrides) -> dict:
    res = api_client.book_delivery(
        delivery_payload(
            member_id, fiscal_year_id, commodity=commodity,
            gross_bushels=gross_bushels, dockage_pct=dockage_pct,
            is_patron_sourced=is_patron_sourced, **overrides,
        ),
        OPERATOR,
    )
    return get_success_data(res)


def settle_delivery(delivery_id) -> dict:
    res = api_client.settle_delivery(delivery_id, OPERATOR)
    return get_success_data(res)


def book_and_settle_delivery(member_id, fiscal_year_id, commodity="CORN",
                             gross_bushels=100, dockage_pct=0.0,
                             is_patron_sourced=True, **overrides) -> dict:
    delivery = book_delivery(
        member_id, fiscal_year_id, commodity=commodity,
        gross_bushels=gross_bushels, dockage_pct=dockage_pct,
        is_patron_sourced=is_patron_sourced, **overrides,
    )
    return settle_delivery(delivery["id"])


def seat_delegate(district_id, member_id, term_start="2025-01-01T00:00:00Z",
                  term_end="2035-01-01T00:00:00Z") -> dict:
    res = api_client.seat_delegate(
        district_id,
        delegate_payload(member_id, term_start=term_start, term_end=term_end),
        REGISTRAR,
    )
    return get_success_data(res)


def get_fiscal_year(fy_id) -> dict:
    return get_success_data(api_client.get_fiscal_year(fy_id, ACCOUNTANT))


def get_member(member_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_member(member_id, headers or REGISTRAR),
    )


def get_certificate(cert_id) -> dict:
    return get_success_data(api_client.get_certificate(cert_id, TREASURER))


def list_member_certificates(member_id, headers=None) -> list:
    res = api_client.list_member_certificates(member_id, headers or TREASURER)
    return get_success_data(res)


def list_year_allocations(fy_id) -> list:
    res = api_client.list_year_allocations(fy_id, ACCOUNTANT)
    return get_success_data(res)


def get_allocation_for_member(fy_id, member_id) -> dict:
    for alloc in list_year_allocations(fy_id):
        if alloc["member_id"] == member_id:
            return alloc
    raise AssertionError(
        f"setup failed: no allocation found for member {member_id} in {fy_id}"
    )


def list_member_tax_forms(member_id, headers=None) -> list:
    res = api_client.list_member_tax_forms(member_id, headers or ACCOUNTANT)
    return get_success_data(res)


# ─── Tier 2: governance ───────────────────────────────

def pass_resolution(kind, subject_ref_id, delegate_id, quorum_required=1,
                    resolution_code=None) -> dict:
    """Propose → open voting → one FOR vote from the only seated delegate.
    The voting window is pinned in the far past (see factories) so the
    tally fires immediately. Returns the PASSED resolution."""
    res = api_client.create_board_resolution(
        resolution_payload(
            kind, subject_ref_id, quorum_required=quorum_required,
            resolution_code=resolution_code,
        ),
        SECRETARY,
    )
    resolution = get_success_data(res)
    get_success_data(api_client.open_voting(resolution["id"], SECRETARY))
    voted = get_success_data(
        api_client.record_vote(
            resolution["id"], {"delegate_id": delegate_id, "vote": "FOR"},
            SECRETARY,
        ),
    )
    final = get_success_data(
        api_client.get_board_resolution(resolution["id"], SECRETARY),
    )
    assert final["status"] == "PASSED", (
        f"setup failed: resolution did not pass (got {final['status']}); "
        f"tally body was {voted}"
    )
    return final


# ─── Tier 3: fiscal-year lifecycle ────────────────────

def close_year_provisional(fy_id, close_clock="2026-09-01T00:00:00Z") -> dict:
    """Advance the logical clock past year end, then OPEN → CLOSED_PROVISIONAL.
    Spawns PROVISIONAL allocations and ISSUED certificates."""
    set_clock(close_clock)
    closed = get_success_data(api_client.close_provisional(fy_id, ACCOUNTANT))
    assert closed["status"] == "CLOSED_PROVISIONAL", (
        f"setup failed: close_provisional yielded {closed['status']}"
    )
    return closed


def finalize_year(fy_id) -> dict:
    """CLOSED_PROVISIONAL → UNDER_AUDIT → CLOSED_FINAL (OCC-guarded).
    Allocations FINALIZED, certificates ISSUED → ACTIVE, tax forms issued."""
    get_success_data(api_client.begin_audit(fy_id, AUDITOR))
    current = get_fiscal_year(fy_id)
    finalized = get_success_data(
        api_client.finalize_close(
            fy_id,
            {"expected_fiscal_year_version": current["version"]},
            ACCOUNTANT,
        ),
    )
    assert finalized["status"] == "CLOSED_FINAL", (
        f"setup failed: finalize_close yielded {finalized['status']}"
    )
    return finalized


def setup_year_with_deliveries(delivery_specs, net_margin_cents=100000,
                               retained_reserve_pct=0.10,
                               qualified_payout_pct=0.30,
                               start_clock="2025-09-01T00:00:00Z",
                               with_delegate=False,
                               delegate_term_end="2035-01-01T00:00:00Z") -> dict:
    """Full intake chain: district + members + OPEN fiscal year + each
    member's settled deliveries. Returns a context dict:
      {district, fiscal_year, members: {key: member}, deliveries: [delivery],
       delegate: <delegate or None>}

    delivery_specs: list of dicts with keys
      member_key, commodity, gross_bushels, dockage_pct (optional),
      is_patron_sourced (optional).
    """
    set_clock(start_clock)
    district = create_district()
    members = {}
    for spec in delivery_specs:
        key = spec["member_key"]
        if key not in members:
            members[key] = create_member(
                district["id"], legal_name=f"{key} Farm",
            )
    fy = create_fiscal_year(
        net_margin_cents=net_margin_cents,
        retained_reserve_pct=retained_reserve_pct,
        qualified_payout_pct=qualified_payout_pct,
    )
    deliveries = []
    for spec in delivery_specs:
        member = members[spec["member_key"]]
        deliveries.append(book_and_settle_delivery(
            member["id"], fy["id"],
            commodity=spec.get("commodity", "CORN"),
            gross_bushels=spec["gross_bushels"],
            dockage_pct=spec.get("dockage_pct", 0.0),
            is_patron_sourced=spec.get("is_patron_sourced", True),
        ))
    delegate = None
    if with_delegate:
        delegate_member = members.get("delegate")
        if delegate_member is None:
            delegate_member = create_member(
                district["id"], legal_name="Delegate Farm",
            )
            members["delegate"] = delegate_member
        delegate = seat_delegate(
            district["id"], delegate_member["id"], term_end=delegate_term_end,
        )
    return {
        "district": district,
        "fiscal_year": fy,
        "members": members,
        "deliveries": deliveries,
        "delegate": delegate,
    }


def setup_closed_final_year(delivery_specs, net_margin_cents=100000,
                            retained_reserve_pct=0.10, qualified_payout_pct=0.30,
                            with_delegate=True,
                            delegate_term_end="2060-01-01T00:00:00Z") -> dict:
    """Full lifecycle through CLOSED_FINAL: intake chain + provisional close
    + audit + finalize. Certificates are ACTIVE afterwards."""
    ctx = setup_year_with_deliveries(
        delivery_specs,
        net_margin_cents=net_margin_cents,
        retained_reserve_pct=retained_reserve_pct,
        qualified_payout_pct=qualified_payout_pct,
        with_delegate=with_delegate,
        delegate_term_end=delegate_term_end,
    )
    ctx["fiscal_year"] = close_year_provisional(ctx["fiscal_year"]["id"])
    ctx["fiscal_year"] = finalize_year(ctx["fiscal_year"]["id"])
    return ctx


# ─── Tier 4: redemption lifecycle ─────────────────────

def create_redemption_request(member_id, kind, certificate_ids,
                              requested_amount_cents, appointment_at,
                              appeal_of_request_id=None) -> dict:
    headers = make_member_headers(member_id)
    res = api_client.create_redemption_request(
        redemption_request_payload(
            member_id, kind, certificate_ids, requested_amount_cents,
            appointment_at, appeal_of_request_id=appeal_of_request_id,
        ),
        headers,
    )
    return get_success_data(res)


def submit_request(request_id, member_id) -> dict:
    res = api_client.submit_for_review(
        request_id, make_member_headers(member_id),
    )
    return get_success_data(res)


def decide_request(request_id, decision, resolution_id):
    """Raw response — the decision may legitimately fail under test."""
    return api_client.decide_redemption(
        request_id,
        {"decision": decision, "resolution_id": resolution_id},
        SECRETARY,
    )


def approve_request(request_id, member_id, kind="RETIREMENT",
                    delegate_id=None) -> dict:
    """Pass a matching-kind resolution referencing the request, then decide
    APPROVE. Returns the APPROVED request."""
    kind_to_resolution = {
        "ESTATE": "APPROVE_ESTATE",
        "RETIREMENT": "APPROVE_RETIREMENT",
        "SPECIAL_HARDSHIP": "APPROVE_SPECIAL_REDEMPTION",
    }
    resolution = pass_resolution(
        kind_to_resolution[kind], request_id, delegate_id,
    )
    decided = decide_request(request_id, "APPROVE", resolution["id"])
    approved = get_success_data(decided)
    assert approved["status"] == "APPROVED", (
        f"setup failed: decide yielded {approved['status']}"
    )
    return approved


def disburse_request(request_id, certificate_versions) -> dict:
    res = api_client.disburse_redemption(
        request_id,
        {"expected_certificate_versions": list(certificate_versions)},
        TREASURER,
    )
    return get_success_data(res)


def setup_under_review_request(net_margin_cents=100000,
                               retained_reserve_pct=0.20,
                               qualified_payout_pct=0.30,
                               gross_bushels=100,
                               requested_amount_cents=100,
                               request_clock="2031-09-01T00:00:00Z",
                               appointment_at="2031-10-01T10:00:00Z",
                               kind="RETIREMENT") -> dict:
    """CLOSED_FINAL year, one member with ACTIVE certificates, and one
    request of the given kind in UNDER_REVIEW. Returns ctx with keys:
    district, fiscal_year, member, certificate, request, delegate."""
    ctx = setup_closed_final_year(
        [{"member_key": "patron", "commodity": "CORN",
          "gross_bushels": gross_bushels}],
        net_margin_cents=net_margin_cents,
        retained_reserve_pct=retained_reserve_pct,
        qualified_payout_pct=qualified_payout_pct,
    )
    member = ctx["members"]["patron"]
    certs = list_member_certificates(
        member["id"], headers=make_member_headers(member["id"]),
    )
    assert certs, "setup failed: no certificates issued for member"
    cert = certs[0]
    set_clock(request_clock)
    request = create_redemption_request(
        member["id"], kind, [cert["id"]], requested_amount_cents,
        appointment_at,
    )
    submitted = submit_request(request["id"], member["id"])
    assert submitted["status"] == "UNDER_REVIEW", (
        f"setup failed: submit yielded {submitted['status']}"
    )
    return {
        "district": ctx["district"],
        "fiscal_year": ctx["fiscal_year"],
        "member": member,
        "certificate": cert,
        "request": submitted,
        "delegate": ctx["delegate"],
    }


# ─── Tier 5: estate lifecycle ─────────────────────────

def record_death(member_id, executor_member_id, date_of_death,
                 clock_iso) -> dict:
    """Set the clock, then ACTIVE → DECEASED: spawns FILED estate claim and
    freezes the decedent's ACTIVE certificates."""
    set_clock(clock_iso)
    res = api_client.record_death(
        member_id,
        {"date_of_death": date_of_death,
         "executor_member_id": executor_member_id},
        REGISTRAR,
    )
    return get_success_data(res)


def get_estate_claim_for(deceased_member_id) -> dict:
    claims = get_success_data(
        api_client.list_member_estate_claims(deceased_member_id, REGISTRAR),
    )
    assert claims, "setup failed: no estate claim spawned for deceased member"
    return claims[0]


def setup_estate_claim_filed(death_clock="2026-01-01T00:00:00Z",
                             date_of_death="2026-01-01T00:00:00Z",
                             with_certificates=False) -> dict:
    """District + deceased member + ESTATE-class executor + FILED claim.
    When with_certificates=True, the decedent first runs a full year through
    CLOSED_FINAL so ACTIVE certificates exist to be frozen."""
    if with_certificates:
        ctx = setup_closed_final_year(
            [{"member_key": "decedent", "commodity": "CORN",
              "gross_bushels": 500}],
            net_margin_cents=100000,
        )
        district = ctx["district"]
        decedent = ctx["members"]["decedent"]
    else:
        set_clock(death_clock)
        district = create_district()
        decedent = create_member(district["id"], legal_name="Decedent Farm")
    executor = create_member(
        district["id"], legal_name="Decedent Estate",
        member_class="ESTATE", is_producer_member=False,
        joined_at="2020-06-01T00:00:00Z",
    )
    record_death(decedent["id"], executor["id"], date_of_death, death_clock)
    claim = get_estate_claim_for(decedent["id"])
    delegate_member = create_member(district["id"], legal_name="Voting Farm")
    delegate = seat_delegate(district["id"], delegate_member["id"])
    return {
        "district": district,
        "decedent": decedent,
        "executor": executor,
        "claim": claim,
        "delegate": delegate,
        "delegate_member": delegate_member,
    }


# ─── Tier 6: revolvement cycles ───────────────────────

def create_cycle(window_start, window_end, equity_class="QUALIFIED",
                 budget_cap_cents=100000, cycle_code=None) -> dict:
    res = api_client.create_revolvement_cycle(
        cycle_payload(
            cycle_code=cycle_code, equity_class=equity_class,
            window_start=window_start, window_end=window_end,
            budget_cap_cents=budget_cap_cents,
        ),
        SECRETARY,
    )
    return get_success_data(res)


def create_and_open_cycle(window_start, window_end, delegate_id,
                          equity_class="QUALIFIED", budget_cap_cents=100000,
                          open_clock=None) -> dict:
    """PLANNED cycle + PASSED OPEN_REVOLVEMENT resolution referencing it +
    open at a clock that has reached window_start."""
    cycle = create_cycle(
        window_start, window_end, equity_class=equity_class,
        budget_cap_cents=budget_cap_cents,
    )
    pass_resolution("OPEN_REVOLVEMENT", cycle["id"], delegate_id)
    if open_clock is not None:
        set_clock(open_clock)
    opened = get_success_data(api_client.open_cycle(cycle["id"], SECRETARY))
    assert opened["status"] == "OPEN", (
        f"setup failed: cycle open yielded {opened['status']}"
    )
    return opened
