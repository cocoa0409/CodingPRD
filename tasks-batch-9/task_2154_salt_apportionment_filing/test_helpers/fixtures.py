"""Composite setup helpers.

Most interesting claims in this API require the system to be somewhere deep in
the multistate compliance chain: a group with member entities, a state profile
whose nexus has been evaluated and whose registration has been completed, a
return with modification lines, computed factors, credit claims, a review
trail, a transmission and sometimes a state notice on top. These helpers build
those preconditions from scratch using only PRD-declared endpoints, so tests can
focus on assertions.

Every helper uses the lenient ``get_success_data`` validator internally so a
broken precondition surfaces as a clear "Setup step failed" message.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASELINE, DEFAULT_CLOCK_UTC
from .factories import (
    REFERENCE_CREDITS,
    REFERENCE_MODIFICATIONS,
    filing_payload,
    group_payload,
    legal_entity_payload,
    member_a_activity_payload,
    member_b_activity_payload,
    registration_payload,
)
from .test_users import TEST_USERS, make_controller_headers, make_state_analyst_headers

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
CTRL = TEST_USERS["controller_headers"]
AUD = TEST_USERS["auditor_headers"]


# ─── Primitive steps ──────────────────────────────────────────────────────────

def set_clock(instant: str = DEFAULT_CLOCK_UTC) -> dict:
    """Move the logical compliance clock to an explicit instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": instant}, TM))


def create_group(**overrides) -> dict:
    return get_success_data(api_client.create_group(group_payload(**overrides), TM))


def create_legal_entity(group_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_legal_entity(group_id, legal_entity_payload(**overrides), TM)
    )


def create_registration(group_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_registration(group_id, registration_payload(**overrides), TM)
    )


def create_activity_record(registration_id: str, payload: dict) -> dict:
    return get_success_data(
        api_client.create_activity_record(registration_id, payload, SA)
    )


def create_election(registration_id: str, **overrides) -> dict:
    payload = {"election_basis": "COMBINED_UNITARY", "effective_tax_year": 2024,
               "binding_years": 3}
    payload.update(overrides)
    return get_success_data(api_client.create_election(registration_id, payload, TM))


def create_filing(registration_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_filing(registration_id, filing_payload(**overrides), SA)
    )


def add_modification(filing_id: str, payload: dict) -> dict:
    return get_success_data(api_client.create_modification(filing_id, payload, SA))


def compute_factors(filing_id: str, variant: str = "JOYCE") -> dict:
    return get_success_data(
        api_client.compute_factors(filing_id, {"apportionment_variant": variant}, SA)
    )


def read_group(group_id: str) -> dict:
    return get_success_data(api_client.get_group(group_id, TM))


def read_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, TM))


def read_legal_entity(legal_entity_id: str) -> dict:
    return get_success_data(api_client.get_legal_entity(legal_entity_id, TM))


def read_election(election_id: str) -> dict:
    return get_success_data(api_client.get_election(election_id, TM))


def read_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_filing(filing_id, SA))


def read_credit_claim(credit_claim_id: str) -> dict:
    return get_success_data(api_client.get_credit_claim(credit_claim_id, SA))


def read_payment(payment_id: str) -> dict:
    return get_success_data(api_client.get_payment(payment_id, CTRL))


def read_notice(notice_id: str) -> dict:
    return get_success_data(api_client.get_notice(notice_id, CTRL))


def read_vda_agreement(vda_id: str) -> dict:
    return get_success_data(api_client.get_vda_agreement(vda_id, TM))


def list_factors(filing_id: str) -> list:
    body = api_client.list_filing_factors(filing_id, AUD, {"limit": 100, "offset": 0})
    return get_success_data(body)


def filing_version(filing_id: str) -> int:
    return read_filing(filing_id)["version"]


def registration_version(registration_id: str) -> int:
    return read_registration(registration_id)["version"]


def add_credit_claim(filing_id: str, expected_filing_version=None, **overrides) -> dict:
    """Claim a credit, supplying the return's current version unless one is given."""
    payload = {
        "credit_code": "RD_CREDIT",
        "granted_amount": 30000.00,
        "priority_order": 1,
        "refundable": False,
        "expires_after_years": 5,
    }
    payload.update(overrides)
    payload["expected_filing_version"] = (
        expected_filing_version if expected_filing_version is not None
        else filing_version(filing_id)
    )
    return get_success_data(api_client.create_credit_claim(filing_id, payload, SA))


def record_payment(registration_id: str, expected_registration_version=None,
                   **overrides) -> dict:
    """Record an estimated installment, supplying the registration's current version."""
    payload = {
        "tax_year": BASELINE["TAX_YEAR"],
        "installment_number": 1,
        "amount": 8000.00,
        "paid_on_date": "2026-04-15T00:00:00Z",
    }
    payload.update(overrides)
    payload["expected_registration_version"] = (
        expected_registration_version if expected_registration_version is not None
        else registration_version(registration_id)
    )
    return get_success_data(api_client.create_payment(registration_id, payload, CTRL))


# ─── Tier 1/2: group, members and the state profile ───────────────────────────

def setup_group_with_members(*, group_overrides=None, include_member_b=True,
                             clock=DEFAULT_CLOCK_UTC) -> dict:
    """Logical clock + one combined group + its member entities.

    Returns a context dict carrying ``group``, ``le_a`` and (optionally) ``le_b``.
    """
    set_clock(clock)
    group = create_group(**(group_overrides or {}))
    le_a = create_legal_entity(
        group["id"], name=BASELINE["MEMBER_A_NAME"], incorporation_state_code="DE",
        entity_type="CORP", is_unitary_member=True,
    )
    ctx = {"group": group, "group_id": group["id"], "le_a": le_a, "le_a_id": le_a["id"]}
    if include_member_b:
        le_b = create_legal_entity(
            group["id"], name=BASELINE["MEMBER_B_NAME"], incorporation_state_code="NV",
            entity_type="CORP", is_unitary_member=True,
        )
        ctx["le_b"] = le_b
        ctx["le_b_id"] = le_b["id"]
    return ctx


def setup_state_profile(*, group_overrides=None, registration_overrides=None,
                        member_a_activity=None, member_b_activity=None,
                        include_member_b=True, write_activity=True,
                        evaluate_nexus=True, complete_registration=True,
                        clock=DEFAULT_CLOCK_UTC) -> dict:
    """The reference CA state profile: group, two members, two activity rows.

    ``member_a_activity`` / ``member_b_activity`` accept field overrides on the
    two reference activity rows. When ``evaluate_nexus`` is true the nexus
    ladder is run for tax year 2026, and when ``complete_registration`` is true
    the state's account number is recorded, closing the obligation.
    """
    ctx = setup_group_with_members(
        group_overrides=group_overrides, include_member_b=include_member_b, clock=clock,
    )
    registration = create_registration(
        ctx["group_id"],
        **{"due_month": 4, "due_day": 15, "extension_months": 6,
           **(registration_overrides or {})},
    )
    ctx["registration"] = registration
    ctx["registration_id"] = registration["id"]

    if write_activity:
        ctx["ar_a"] = create_activity_record(
            registration["id"],
            member_a_activity_payload(ctx["le_a_id"], **(member_a_activity or {})),
        )
        if include_member_b:
            ctx["ar_b"] = create_activity_record(
                registration["id"],
                member_b_activity_payload(ctx["le_b_id"], **(member_b_activity or {})),
            )

    if evaluate_nexus:
        ctx["registration"] = get_success_data(
            api_client.evaluate_nexus(
                registration["id"], {"as_of_tax_year": BASELINE["TAX_YEAR"]}, TM
            )
        )
    if complete_registration:
        ctx["registration"] = get_success_data(
            api_client.complete_registration(
                registration["id"], {"state_account_number": "CA-99887766"}, TM
            )
        )
    return ctx


# ─── Tier 3: the return, through every preparation stage ──────────────────────

def setup_draft_filing(*, filing_overrides=None, with_modifications=True,
                       **profile_kwargs) -> dict:
    """Reference state profile plus one DRAFT return for tax year 2026.

    With ``with_modifications`` the three reference modification lines are
    written, giving the return a ``modification_total`` of 676.57.
    """
    ctx = setup_state_profile(**profile_kwargs)
    filing = create_filing(ctx["registration_id"], **(filing_overrides or {}))
    ctx["filing"] = filing
    ctx["filing_id"] = filing["id"]
    if with_modifications:
        ctx["modifications"] = [
            add_modification(filing["id"], dict(line)) for line in REFERENCE_MODIFICATIONS
        ]
    ctx["filing"] = read_filing(filing["id"])
    return ctx


def setup_computed_filing(*, variant="JOYCE", **kwargs) -> dict:
    """A DRAFT return whose apportionment factors have been computed."""
    ctx = setup_draft_filing(**kwargs)
    ctx["filing"] = compute_factors(ctx["filing_id"], variant)
    ctx["filing_version_after_compute"] = ctx["filing"]["version"]
    return ctx


def setup_filing_with_credits(*, credits=None, variant="JOYCE", **kwargs) -> dict:
    """A computed DRAFT return carrying an ordered set of credit claims."""
    ctx = setup_computed_filing(variant=variant, **kwargs)
    claims = []
    for spec in (credits if credits is not None else REFERENCE_CREDITS):
        claims.append(add_credit_claim(ctx["filing_id"], **dict(spec)))
    ctx["credit_claims"] = claims
    ctx["filing"] = read_filing(ctx["filing_id"])
    return ctx


def setup_locked_filing(*, credits=None, variant="JOYCE", **kwargs) -> dict:
    """A return frozen at FACTORS_LOCKED."""
    ctx = setup_filing_with_credits(credits=credits, variant=variant, **kwargs)
    ctx["filing"] = get_success_data(api_client.lock_factors(ctx["filing_id"], {}, SA))
    return ctx


def setup_filing_in_review(*, preparer_user_id="analyst-01", preparer_role="StateAnalyst",
                           **kwargs) -> dict:
    """A return submitted for review, with the preparer recorded."""
    ctx = setup_locked_filing(**kwargs)
    headers = (
        make_state_analyst_headers(preparer_user_id) if preparer_role == "StateAnalyst"
        else make_controller_headers(preparer_user_id)
    )
    ctx["preparer_user_id"] = preparer_user_id
    ctx["filing"] = get_success_data(
        api_client.submit_review(ctx["filing_id"], {"preparer_note": "prepared"}, headers)
    )
    return ctx


def setup_approved_filing(*, approver_user_id="controller-01", **kwargs) -> dict:
    """A return approved by a Controller other than its preparer."""
    ctx = setup_filing_in_review(**kwargs)
    ctx["approver_user_id"] = approver_user_id
    ctx["filing"] = get_success_data(
        api_client.approve_filing(
            ctx["filing_id"], {"approval_note": "reviewed"},
            make_controller_headers(approver_user_id),
        )
    )
    return ctx


def setup_filed_filing(*, confirmation_number="CA-EFILE-2026-0001",
                       approver_user_id="controller-01", **kwargs) -> dict:
    """A return transmitted to the state."""
    ctx = setup_approved_filing(approver_user_id=approver_user_id, **kwargs)
    ctx["confirmation_number"] = confirmation_number
    ctx["filing"] = get_success_data(
        api_client.file_filing(
            ctx["filing_id"], {"confirmation_number": confirmation_number},
            make_controller_headers(approver_user_id),
        )
    )
    return ctx


# ─── Tier 4: correspondence and cash on top of a filed return ─────────────────

def setup_filed_filing_with_notice(*, notice_overrides=None, **kwargs) -> dict:
    """A filed return carrying one OPEN state notice."""
    ctx = setup_filed_filing(**kwargs)
    payload = {
        "notice_type": "PROPOSED_ASSESSMENT",
        "state_notice_number": "CA-NOT-2027-77",
        "assessed_tax": 50000.00,
        "notice_date": "2027-05-01T00:00:00Z",
        "response_due_days": 45,
    }
    payload.update(notice_overrides or {})
    notice = get_success_data(api_client.create_notice(ctx["filing_id"], payload, CTRL))
    ctx["notice"] = notice
    ctx["notice_id"] = notice["id"]
    return ctx


def setup_notice_under_appeal(*, notice_overrides=None,
                              respond_at="2027-05-15T00:00:00Z",
                              decide_at="2027-07-01T00:00:00Z", **kwargs) -> dict:
    """A filed return whose notice has been answered and appealed.

    The clock is left at ``decide_at`` so an appellate decision accrues a known
    number of days of interest.
    """
    ctx = setup_filed_filing_with_notice(notice_overrides=notice_overrides, **kwargs)
    set_clock(respond_at)
    get_success_data(api_client.respond_notice(
        ctx["notice_id"],
        {"response_summary": "Factor numerator disputed", "contested_amount": 50000.00},
        CTRL,
    ))
    ctx["notice"] = get_success_data(api_client.appeal_notice(
        ctx["notice_id"],
        {"appeal_grounds": "Sales sourcing under market-based rules"},
        CTRL,
    ))
    set_clock(decide_at)
    return ctx


def setup_filed_filing_with_applied_payment(*, amount=10000.00, installment_number=1,
                                            paid_on_date="2026-04-15T00:00:00Z",
                                            **kwargs) -> dict:
    """A filed return with one estimated remittance applied against it."""
    ctx = setup_filed_filing(**kwargs)
    payment = record_payment(
        ctx["registration_id"], amount=amount, installment_number=installment_number,
        paid_on_date=paid_on_date, tax_year=BASELINE["TAX_YEAR"],
    )
    ctx["payment"] = get_success_data(
        api_client.apply_payment(payment["id"], {"filing_id": ctx["filing_id"]}, CTRL)
    )
    ctx["payment_id"] = payment["id"]
    ctx["filing"] = read_filing(ctx["filing_id"])
    return ctx


# ─── Tier 5: standalone profiles for calendar, cash and disclosure work ───────

def setup_bare_registration(*, group_overrides=None, registration_overrides=None,
                            include_member=False, clock=DEFAULT_CLOCK_UTC) -> dict:
    """A group and one state profile with no activity, nexus or returns."""
    set_clock(clock)
    group = create_group(**(group_overrides or {}))
    ctx = {"group": group, "group_id": group["id"]}
    if include_member:
        le_a = create_legal_entity(
            group["id"], name="Corner Member", incorporation_state_code="DE",
            entity_type="CORP", is_unitary_member=True,
        )
        ctx["le_a"] = le_a
        ctx["le_a_id"] = le_a["id"]
    registration = create_registration(group["id"], **(registration_overrides or {}))
    ctx["registration"] = registration
    ctx["registration_id"] = registration["id"]
    return ctx


def setup_economic_nexus_registration(*, state_code="CA", destination_sales=900000,
                                      tax_rate=0.0884, group_overrides=None,
                                      registration_overrides=None,
                                      clock=DEFAULT_CLOCK_UTC) -> dict:
    """A single-member state profile pushed to ECONOMIC nexus by receipts alone.

    No payroll, no property and no employee days, so the physical rung of the
    nexus ladder cannot fire and the economic rung decides.
    """
    ctx = setup_bare_registration(
        group_overrides=group_overrides,
        registration_overrides={
            "state_code": state_code, "factor_formula": "SINGLE_SALES_FACTOR",
            "tax_rate": tax_rate, "throwback_rule": "NONE",
            "service_sourcing_rule": "MARKET_BASED",
            **(registration_overrides or {}),
        },
        include_member=True, clock=clock,
    )
    create_activity_record(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "tax_year": BASELINE["TAX_YEAR"],
        "destination_sales": destination_sales, "payroll_compensation": 0,
        "property_average_value": 0, "employee_days_in_state": 0,
        "protected_solicitation_only": False,
    })
    ctx["registration"] = get_success_data(api_client.evaluate_nexus(
        ctx["registration_id"], {"as_of_tax_year": BASELINE["TAX_YEAR"]}, TM
    ))
    return ctx
