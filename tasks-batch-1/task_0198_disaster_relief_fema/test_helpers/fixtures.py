"""Composite setup helpers for the disaster-relief IHP workflow.

These encapsulate the multi-step preambles that most test claims require — a
household carried from registration, through inspection and verification, into an
IHP case, an approved award, disbursements, and on into appeals / SBA cascades /
recoupments. Each fixture uses get_success_data() internally so a broken setup
surfaces a clear "Setup step failed" error.

Identity threading: the Inspector and Caseworker roles are entity-backed, so every
ownership- or segregation-gated call uses make_inspector_headers(inspector["id"])
or make_caseworker_headers(caseworker["id"]) with the real entity id — never the
shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_inspector_headers, make_caseworker_headers,
)
from . import factories as F


ADMIN = TEST_USERS["program_admin_headers"]


# ─── Atomic builders ───────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Pin the server's logical UTC clock (PRD §2.10)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_declaration(**overrides):
    return get_success_data(
        api_client.create_declaration(F.create_declaration_payload(**overrides), ADMIN)
    )


def create_inspector(**overrides):
    return get_success_data(
        api_client.create_inspector(F.create_inspector_payload(**overrides), ADMIN)
    )


def create_caseworker(**overrides):
    return get_success_data(
        api_client.create_caseworker(F.create_caseworker_payload(**overrides), ADMIN)
    )


def create_applicant(declaration_id, caseworker, **overrides):
    """Register an applicant as the given caseworker (entity-backed identity)."""
    hdrs = make_caseworker_headers(caseworker["id"])
    return get_success_data(
        api_client.create_applicant(
            F.create_applicant_payload(declaration_id, **overrides), hdrs
        )
    )


# ─── Tier 1/2: build a household up to a chosen lifecycle stage ─────────────
def setup_program(
    *,
    clock="2026-02-01T00:00:00Z",
    decl_overrides=None,
    inspector_badge="INS-1",
    cw_employee_id="CW-1",
):
    """Clock + declaration + one inspector + one caseworker.

    Returns a context dict: clock, decl, inspector, caseworker, plus
    inspector_headers / caseworker_headers bound to the real entity ids.
    """
    set_clock(clock)
    decl = create_declaration(**(decl_overrides or {}))
    inspector = create_inspector(badge_number=inspector_badge)
    caseworker = create_caseworker(employee_id=cw_employee_id)
    return {
        "clock": clock,
        "decl": decl,
        "inspector": inspector,
        "caseworker": caseworker,
        "inspector_headers": make_inspector_headers(inspector["id"]),
        "caseworker_headers": make_caseworker_headers(caseworker["id"]),
    }


def setup_scheduled_assessment(
    ctx=None,
    *,
    applicant_overrides=None,
    scheduled_start="2026-02-11T09:00:00Z",
    scheduled_end="2026-02-11T10:00:00Z",
    **program_kwargs,
):
    """Program + applicant (REGISTERED) + one SCHEDULED assessment.

    Adds applicant, assessment to the context.
    """
    if ctx is None:
        ctx = setup_program(**program_kwargs)
    insp_h = ctx["inspector_headers"]
    applicant = create_applicant(ctx["decl"]["id"], ctx["caseworker"], **(applicant_overrides or {}))
    assessment = get_success_data(
        api_client.create_assessment(
            F.create_assessment_payload(
                applicant["id"], ctx["inspector"]["id"],
                scheduled_start=scheduled_start, scheduled_end=scheduled_end,
            ),
            insp_h,
        )
    )
    ctx["applicant"] = applicant
    ctx["assessment"] = assessment
    return ctx


def setup_verified_assessment(
    ctx=None,
    *,
    inspect_overrides=None,
    applicant_overrides=None,
    **program_kwargs,
):
    """Program + applicant + assessment carried SCHEDULED -> INSPECTED -> VERIFIED.

    Adds applicant, assessment (now VERIFIED) to the context. inspect_overrides
    controls the verified amounts and habitability.
    """
    ctx = setup_scheduled_assessment(
        ctx, applicant_overrides=applicant_overrides, **program_kwargs
    )
    insp_h = ctx["inspector_headers"]
    cw_h = ctx["caseworker_headers"]
    asm_id = ctx["assessment"]["id"]
    get_success_data(
        api_client.inspect_assessment(asm_id, F.inspect_assessment_payload(**(inspect_overrides or {})), insp_h)
    )
    ctx["assessment"] = get_success_data(api_client.verify_assessment(asm_id, cw_h))
    return ctx


def setup_pending_case(
    ctx=None,
    *,
    monthly_fmr_cents=100_000,
    inspect_overrides=None,
    applicant_overrides=None,
    **program_kwargs,
):
    """Carry a household to an IHP case in ELIGIBILITY_PENDING (provisional computed).

    Adds case to the context.
    """
    ctx = setup_verified_assessment(
        ctx, inspect_overrides=inspect_overrides,
        applicant_overrides=applicant_overrides, **program_kwargs,
    )
    cw_h = ctx["caseworker_headers"]
    case = get_success_data(
        api_client.create_ihp_case(
            F.create_ihp_case_payload(
                ctx["applicant"]["id"], ctx["assessment"]["id"],
                monthly_fmr_cents=monthly_fmr_cents,
            ),
            cw_h,
        )
    )
    ctx["case"] = case
    return ctx


def setup_approved_case(
    ctx=None,
    *,
    monthly_fmr_cents=100_000,
    inspect_overrides=None,
    applicant_overrides=None,
    approve_clock=None,
    **program_kwargs,
):
    """Carry a household to an AWARD_APPROVED IHP case (final award computed).

    If approve_clock is given, the clock is re-pinned right before approve (used by
    DOB at-award filter tests). Adds case (refreshed post-approve) to the context.
    """
    ctx = setup_pending_case(
        ctx, monthly_fmr_cents=monthly_fmr_cents,
        inspect_overrides=inspect_overrides,
        applicant_overrides=applicant_overrides, **program_kwargs,
    )
    if approve_clock is not None:
        set_clock(approve_clock)
    cw_h = ctx["caseworker_headers"]
    ctx["case"] = get_success_data(api_client.approve_ihp_case(ctx["case"]["id"], cw_h))
    return ctx


# ─── Tier 3: line-item lookup + disbursement shortcuts ─────────────────────
def get_line_item(case_id, category, headers):
    """Return the single AwardLineItem of a case in a given category."""
    data, _ = _list_line_items(case_id, category, headers)
    assert data, f"No {category} line item found for case {case_id}"
    return data[0]


def _list_line_items(case_id, category, headers):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_award_line_items(
        headers, params={"ihp_case_id": case_id, "category": category}
    )
    return validate_paginated(resp)


def disburse(case_id, line_item_id, expected_version, amount_cents, headers):
    """Create a PAID disbursement; returns the disbursement data."""
    return get_success_data(
        api_client.create_disbursement(
            F.create_disbursement_payload(
                case_id, line_item_id, expected_version, amount_cents=amount_cents
            ),
            headers,
        )
    )


def current_case_version(case_id, headers):
    """Read the case's current version (after a mutation advanced it)."""
    return get_success_data(api_client.get_ihp_case(case_id, headers))["version"]


def setup_approved_case_with_two_caseworkers(
    *,
    clock="2026-02-14T00:00:00Z",
    monthly_fmr_cents=120_000,
    inspect_overrides=None,
    applicant_overrides=None,
    decl_overrides=None,
    cw1_employee_id="CW-A",
    cw2_employee_id="CW-B",
    inspector_badge="INS-2CW",
):
    """Approved case determined by cw1, with a second SoD-compliant caseworker cw2.

    Returns a context dict with case, cw1/cw2 entities + headers (cw1 bound to the
    determiner identity, cw2 a distinct identity for appeal decisions).
    """
    set_clock(clock)
    decl = create_declaration(**(decl_overrides or {}))
    inspector = create_inspector(badge_number=inspector_badge)
    cw1 = create_caseworker(employee_id=cw1_employee_id)
    cw2 = create_caseworker(employee_id=cw2_employee_id)
    cw1_h = make_caseworker_headers(cw1["id"])
    cw2_h = make_caseworker_headers(cw2["id"])
    insp_h = make_inspector_headers(inspector["id"])

    applicant = get_success_data(
        api_client.create_applicant(
            F.create_applicant_payload(decl["id"], **(applicant_overrides or {})), cw1_h
        )
    )
    assessment = get_success_data(
        api_client.create_assessment(
            F.create_assessment_payload(
                applicant["id"], inspector["id"],
                scheduled_start="2026-02-15T09:00:00Z",
                scheduled_end="2026-02-15T10:00:00Z",
            ),
            insp_h,
        )
    )
    get_success_data(
        api_client.inspect_assessment(
            assessment["id"], F.inspect_assessment_payload(**(inspect_overrides or {})), insp_h
        )
    )
    get_success_data(api_client.verify_assessment(assessment["id"], cw1_h))
    case = get_success_data(
        api_client.create_ihp_case(
            F.create_ihp_case_payload(
                applicant["id"], assessment["id"], monthly_fmr_cents=monthly_fmr_cents
            ),
            cw1_h,
        )
    )
    case = get_success_data(api_client.approve_ihp_case(case["id"], cw1_h))
    return {
        "decl": decl,
        "inspector": inspector,
        "cw1": cw1,
        "cw2": cw2,
        "cw1_headers": cw1_h,
        "cw2_headers": cw2_h,
        "inspector_headers": insp_h,
        "applicant": applicant,
        "assessment": assessment,
        "case": case,
    }


# ─── Tier 4/5: cascade-driven recoupment shortcut ──────────────────────────
def setup_disbursing_case_with_late_dob_recoupment(
    *, clock_setup="2026-02-05T00:00:00Z", approve_clock="2026-03-01T00:00:00Z",
    decl_overrides=None, inspector_badge="INS-RCP", cw_employee_id="CW-RCP",
):
    """DISBURSING case carrying an ESTABLISHED LATE_DOB Recoupment of 600,000.

    gross 1,800,000; a pre-approve INSURANCE DOB 400,000 -> net 1,400,000; fully
    disbursed (REPAIR 900,000 + PERSONAL 500,000); an SBA loan 600,000 drops net to
    800,000, so a LATE_DOB Recoupment of debt 600,000 is auto-established.
    Returns a context dict: case, applicant, caseworker_headers, recoupment.
    """
    from prd_bench_local_runner.testing import validate_paginated
    ctx = setup_verified_assessment(
        clock=clock_setup,
        decl_overrides=decl_overrides,
        inspector_badge=inspector_badge, cw_employee_id=cw_employee_id,
        applicant_overrides={
            "household_name": "Recoup Household", "household_size": 3,
            "annual_income_cents": 3_000_000, "damage_date": "2026-01-20T00:00:00Z",
            "reported_repair_cost_cents": 1_000_000,
            "reported_personal_property_cents": 500_000, "reported_rental_months": 3,
        },
        inspect_overrides={
            "habitability": "UNINHABITABLE",
            "verified_repair_cost_cents": 1_000_000,
            "verified_personal_property_cents": 500_000, "verified_rental_months": 3,
        },
        scheduled_start="2026-02-06T09:00:00Z", scheduled_end="2026-02-06T10:00:00Z",
    )
    cw_h = ctx["caseworker_headers"]
    app_id = ctx["applicant"]["id"]
    get_success_data(api_client.create_dob_record(
        F.create_dob_record_payload(app_id, source_type="INSURANCE",
                                    amount_cents=400_000, received_at="2026-02-05T00:00:00Z"), ADMIN))
    case = get_success_data(api_client.create_ihp_case(
        F.create_ihp_case_payload(app_id, ctx["assessment"]["id"], monthly_fmr_cents=100_000), cw_h))
    set_clock(approve_clock)
    case = get_success_data(api_client.approve_ihp_case(case["id"], cw_h))
    case_id = case["id"]
    v = case["version"]
    repair_li = get_line_item(case_id, "REPAIR_ASSISTANCE", cw_h)
    disburse(case_id, repair_li["id"], v, 900_000, cw_h)
    v = current_case_version(case_id, cw_h)
    pp_li = get_line_item(case_id, "PERSONAL_PROPERTY", cw_h)
    disburse(case_id, pp_li["id"], v, 500_000, cw_h)
    ref = get_success_data(api_client.create_sba_referral(
        F.create_sba_referral_payload(case_id), cw_h))
    get_success_data(api_client.record_sba_outcome(
        ref["id"], {"outcome": "APPROVED", "sba_loan_amount_cents": 600_000}, cw_h))
    recoups, _ = validate_paginated(api_client.list_recoupments(
        ADMIN, params={"ihp_case_id": case_id, "origin": "LATE_DOB"}))
    assert recoups, "Expected a LATE_DOB recoupment from the SBA cascade"
    ctx["case"] = get_success_data(api_client.get_ihp_case(case_id, cw_h))
    ctx["recoupment"] = recoups[0]
    return ctx
