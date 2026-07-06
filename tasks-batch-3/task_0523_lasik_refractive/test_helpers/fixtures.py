"""Composite setup helpers.

Each helper drives the API through PRD-declared endpoints only, using the
lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors. Every ownership-gated call threads the acting entity's
real id through the matching make_<role>_headers builder.

All helpers use "safe" clinical inputs (corneal_thickness_um 550, k 44.0,
refractive_error 3.0, DOB 2000-01-01) so that screening approval always
succeeds; the screening safety-gate thresholds themselves are never asserted.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_surgeon_headers, make_optometrist_headers, make_patient_headers,
)
from . import factories as F

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base configuration + staff
# ---------------------------------------------------------------------------
def create_package(**overrides):
    return get_success_data(api_client.create_package(F.create_package_payload(**overrides), COORD))


def create_suite(**overrides):
    return get_success_data(api_client.create_suite(F.create_suite_payload(**overrides), COORD))


def create_surgeon(**overrides):
    return get_success_data(api_client.create_surgeon(F.create_surgeon_payload(**overrides), COORD))


def create_optometrist(**overrides):
    return get_success_data(api_client.create_optometrist(F.create_optometrist_payload(**overrides), COORD))


def create_patient(**overrides):
    return get_success_data(api_client.create_patient(F.create_patient_payload(**overrides), COORD))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


def setup_config():
    """Package + suite + surgeon + optometrist. Returns dict of the four."""
    return {
        "package": create_package(),
        "suite": create_suite(),
        "surgeon": create_surgeon(),
        "optometrist": create_optometrist(),
    }


# ---------------------------------------------------------------------------
# Tier 1/2: screenings
# ---------------------------------------------------------------------------
def create_submitted_screening(optometrist_id, patient_id, **screening_overrides):
    """DRAFT -> SUBMITTED. Returns the submitted screening."""
    scr = get_success_data(api_client.create_screening(
        F.create_screening_payload(patient_id, optometrist_id, **screening_overrides),
        make_optometrist_headers(optometrist_id),
    ))
    return get_success_data(api_client.submit_screening(
        scr["id"], make_optometrist_headers(optometrist_id),
    ))


def create_approved_screening(optometrist_id, surgeon_id, patient_id, **screening_overrides):
    """DRAFT -> SUBMITTED -> APPROVED. Returns the approved screening."""
    scr = create_submitted_screening(optometrist_id, patient_id, **screening_overrides)
    return get_success_data(api_client.adjudicate_screening(
        scr["id"], {"decision": "APPROVE"}, make_surgeon_headers(surgeon_id),
    ))


# ---------------------------------------------------------------------------
# Tier 2/3: cases with an approved screening
# ---------------------------------------------------------------------------
def create_planned_case(package_id, optometrist_id, surgeon_id,
                        patient=None, **screening_overrides):
    """Approve a screening then open a PLANNED/UNFUNDED case.

    Returns (case, patient). If patient is None a fresh patient is registered.
    """
    if patient is None:
        patient = create_patient()
    scr = create_approved_screening(optometrist_id, surgeon_id, patient["id"], **screening_overrides)
    case = get_success_data(api_client.create_case(
        F.create_case_payload(patient["id"], scr["id"], package_id), COORD,
    ))
    return case, patient


def fund_case_in_full(case_id, base_price_cents):
    """UNFUNDED -> PAID_IN_FULL via down payment == base price. Returns plan."""
    return get_success_data(api_client.create_financing(
        case_id, F.create_financing_payload(base_price_cents, term_months=1, apr_bps=0), COORD,
    ))


def fund_case_deposit(case_id, down_payment_cents, term_months=12, apr_bps=1200):
    """UNFUNDED -> DEPOSIT_PAID via partial down payment. Returns OPEN plan."""
    return get_success_data(api_client.create_financing(
        case_id,
        F.create_financing_payload(down_payment_cents, term_months=term_months, apr_bps=apr_bps),
        COORD,
    ))


def create_booking(case_id, suite_id, surgeon_id, expected_case_version,
                   slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z"):
    """Create an ACTIVE booking (case PLANNED -> SCHEDULED). Returns booking."""
    return get_success_data(api_client.create_booking(
        case_id,
        F.create_booking_payload(suite_id, surgeon_id, slot_start, slot_end, expected_case_version),
        COORD,
    ))


# ---------------------------------------------------------------------------
# Tier 3: funded + scheduled cases
# ---------------------------------------------------------------------------
def setup_scheduled_case(pay_in_full=True, down_payment_cents=None,
                         slot_start="2026-06-01T09:00:00Z", slot_end="2026-06-01T10:00:00Z",
                         clock="2026-06-01T12:00:00Z"):
    """Full setup through a SCHEDULED, funded case with one ACTIVE booking.

    Returns a dict with package, suite, surgeon, optometrist, patient, case,
    plan, booking. The case object returned is the freshly-fetched one so its
    version reflects the booking bump.
    """
    cfg = setup_config()
    case, patient = create_planned_case(
        cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"],
    )
    base = cfg["package"]["base_price_cents"]
    if pay_in_full:
        plan = fund_case_in_full(case["id"], base)
    else:
        dp = down_payment_cents if down_payment_cents is not None else 100000
        plan = fund_case_deposit(case["id"], dp)
    if clock:
        set_clock(clock)
    # Funding mutated the case (financial status change bumps version per PRD
    # 2.4), so re-read the current version before supplying expected_case_version.
    funded_case = get_success_data(api_client.get_case(case["id"], COORD))
    booking = create_booking(
        case["id"], cfg["suite"]["id"], cfg["surgeon"]["id"], funded_case["version"],
        slot_start=slot_start, slot_end=slot_end,
    )
    fresh_case = get_success_data(api_client.get_case(case["id"], COORD))
    return {
        **cfg,
        "patient": patient,
        "case": fresh_case,
        "plan": plan,
        "booking": booking,
    }


# ---------------------------------------------------------------------------
# Tier 3: consented / operated / healed cases
# ---------------------------------------------------------------------------
def setup_consented_case(**kwargs):
    """SCHEDULED -> CONSENTED (signed consent). Returns setup_scheduled_case dict
    plus 'consent'."""
    ctx = setup_scheduled_case(**kwargs)
    consent = get_success_data(api_client.create_consent(
        ctx["case"]["id"],
        F.create_consent_payload(ctx["patient"]["id"], drops_regimen_started=True),
        make_patient_headers(ctx["patient"]["id"]),
    ))
    ctx["consent"] = consent
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], COORD))
    return ctx


def setup_operated_case(operate_clock="2026-06-01T12:00:00Z", **kwargs):
    """CONSENTED -> OPERATED. surgery_completed_at is stamped at operate_clock."""
    ctx = setup_consented_case(**kwargs)
    if operate_clock:
        set_clock(operate_clock)
    get_success_data(api_client.operate_case(
        ctx["case"]["id"], make_surgeon_headers(ctx["surgeon"]["id"]),
    ))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], COORD))
    return ctx


def setup_healed_case(final_uncorrected_va=0.5, heal_clock="2026-07-02T00:00:00Z",
                      operate_clock="2026-06-01T12:00:00Z", **kwargs):
    """OPERATED -> HEALED. heal_clock is well past the settling period.

    Default final VA 0.5 (< guarantee 1.0) so the case has missed its guarantee.
    """
    ctx = setup_operated_case(operate_clock=operate_clock, **kwargs)
    if heal_clock:
        set_clock(heal_clock)
    get_success_data(api_client.heal_case(
        ctx["case"]["id"], {"final_uncorrected_va": final_uncorrected_va},
        make_surgeon_headers(ctx["surgeon"]["id"]),
    ))
    ctx["case"] = get_success_data(api_client.get_case(ctx["case"]["id"], COORD))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: enhancement-ready and refund-ready setups
# ---------------------------------------------------------------------------
def setup_healed_with_requested_enhancement(**kwargs):
    """A HEALED, within-window case plus a REQUESTED EnhancementRequest and a
    separately APPROVED re-screening. Returns setup_healed_case dict plus
    'enhancement' and 'rescreening'."""
    ctx = setup_healed_case(**kwargs)
    rescr = create_approved_screening(
        ctx["optometrist"]["id"], ctx["surgeon"]["id"], ctx["patient"]["id"],
        corneal_thickness_um=545, topography_k_max=44.0, refractive_error_diopters=1.5,
    )
    enh = get_success_data(api_client.create_enhancement(
        F.create_enhancement_payload(ctx["case"]["id"], ctx["patient"]["id"], "regression"),
        make_patient_headers(ctx["patient"]["id"]),
    ))
    ctx["enhancement"] = enh
    ctx["rescreening"] = rescr
    return ctx


def setup_healed_with_pending_refund(final_uncorrected_va=0.5, **kwargs):
    """A HEALED, PAID_IN_FULL, guarantee-missed case with a PENDING RefundClaim.
    Returns setup_healed_case dict plus 'claim'."""
    ctx = setup_healed_case(final_uncorrected_va=final_uncorrected_va, pay_in_full=True, **kwargs)
    claim = get_success_data(api_client.create_refund_claim(
        F.create_refund_claim_payload(ctx["case"]["id"]), COORD,
    ))
    ctx["claim"] = claim
    return ctx


def setup_healed_with_fulfilled_enhancement_and_pending_refund(**kwargs):
    """A HEALED, PAID_IN_FULL, guarantee-missed case that has a FULFILLED
    EnhancementRequest AND a PENDING RefundClaim on the same origin case.
    Returns dict with the standard keys plus 'enhancement' and 'claim'."""
    ctx = setup_healed_case(pay_in_full=True, final_uncorrected_va=0.5, **kwargs)
    rescr = create_approved_screening(
        ctx["optometrist"]["id"], ctx["surgeon"]["id"], ctx["patient"]["id"],
        corneal_thickness_um=545, topography_k_max=44.0, refractive_error_diopters=1.5,
    )
    enh = get_success_data(api_client.create_enhancement(
        F.create_enhancement_payload(ctx["case"]["id"], ctx["patient"]["id"], "regression"),
        make_patient_headers(ctx["patient"]["id"]),
    ))
    get_success_data(api_client.rescreen_enhancement(
        enh["id"], {"re_screening_id": rescr["id"]},
        make_optometrist_headers(ctx["optometrist"]["id"]),
    ))
    get_success_data(api_client.adjudicate_enhancement(
        enh["id"], {"decision": "APPROVE"}, make_surgeon_headers(ctx["surgeon"]["id"]),
    ))
    get_success_data(api_client.fulfill_enhancement(
        enh["id"], make_surgeon_headers(ctx["surgeon"]["id"]),
    ))
    claim = get_success_data(api_client.create_refund_claim(
        F.create_refund_claim_payload(ctx["case"]["id"]), COORD,
    ))
    ctx["enhancement"] = enh
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: an already-booked "blocker" occupying suite/surgeon time
# ---------------------------------------------------------------------------
def setup_blocker_booking(suite_id=None, surgeon_id=None, package_id=None,
                          optometrist_id=None,
                          slot_start="2026-06-01T09:00:00Z",
                          slot_end="2026-06-01T10:00:00Z"):
    """Create a second funded, PAID_IN_FULL case and book it into the given
    suite/surgeon slot, so it occupies scheduling capacity. Any of the resource
    ids may be provided to reuse existing config; missing ones are created.

    Returns a dict of every resource created/used, including 'blocker_booking'.
    """
    package = ({"id": package_id, "base_price_cents": F.DEFAULTS["BASE_PRICE_CENTS"]}
               if package_id else create_package())
    suite = {"id": suite_id} if suite_id else create_suite()
    surgeon = {"id": surgeon_id} if surgeon_id else create_surgeon()
    optometrist = {"id": optometrist_id} if optometrist_id else create_optometrist()
    case, patient = create_planned_case(
        package["id"], optometrist["id"], surgeon["id"],
    )
    fund_case_in_full(case["id"], package["base_price_cents"])
    # Funding bumped the case version (PRD 2.4); re-read before booking.
    funded_case = get_success_data(api_client.get_case(case["id"], COORD))
    booking = create_booking(
        case["id"], suite["id"], surgeon["id"], funded_case["version"],
        slot_start=slot_start, slot_end=slot_end,
    )
    return {
        "package": package, "suite": suite, "surgeon": surgeon,
        "optometrist": optometrist, "case": case, "patient": patient,
        "blocker_booking": booking,
    }
