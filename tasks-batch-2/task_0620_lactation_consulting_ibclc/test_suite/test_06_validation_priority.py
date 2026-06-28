"""Independent-firing validation categories across endpoints, plus the
cross-practice, no-package-credits, and parent-completion preconditions.

Depth instances (queue A): priority_pair_validation_conflict (temporal vs
referential), cross_entity_state_dependency (superbill requires completed
consult); plus corner-design breadth for cross-practice and no-package-credits.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_practice, create_consultant, create_client, set_clock,
    setup_practice_with_consultant_and_client, create_consult,
    create_completed_consult, create_in_progress_consult,
    create_package,
    create_consult_payload, create_superbill_payload, create_feeding_assessment_payload,
    make_consultant_headers,
    TEST_USERS,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ─── priority_pair / temporal_vs_referential_independent_firing ─────────────

def test_consultant_double_booked_fires_on_consult_create(api):
    """PRD §2.7: "10. Consultant calendar conflict — on consult scheduling and
    rescheduling, the buffer-padded interval must not collide on the consultant, else
    `ERR_CONSULTANT_DOUBLE_BOOKED`."

    A new TELEHEALTH consult on a consultant already booked 15:00-16:00 overlaps and
    is rejected with ERR_CONSULTANT_DOUBLE_BOOKED — the temporal rule firing on its
    own endpoint (consult create).

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_independent_firing
    """
    ctx = setup_practice_with_consultant_and_client(
        aca_preventive_enabled=False, clock_utc="2026-06-10T15:00:00Z")
    prac, cons, client_a = ctx["practice"], ctx["consultant"], ctx["client"]
    client_b = create_client(prac["id"], full_name="Parent B")
    create_consult(prac["id"], client_a["id"], cons["id"],
                   "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")

    resp = api.create_consult(create_consult_payload(
        prac["id"], client_b["id"], cons["id"],
        "2026-06-10T15:30:00Z", "2026-06-10T16:30:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CONSULTANT_DOUBLE_BOOKED.value)


def test_aca_preventive_disabled_fires_on_superbill_create(api):
    """PRD §2.7: "12. ACA-preventive availability — on superbill drafting, if
    `is_aca_preventive` is requested true the practice must have
    `aca_preventive_enabled` true, else `ERR_ACA_PREVENTIVE_DISABLED`."

    Drafting an ACA-preventive superbill against a practice with
    aca_preventive_enabled false is rejected with ERR_ACA_PREVENTIVE_DISABLED — the
    referential rule firing on its own endpoint (superbill create), never bleeding
    into the consultant-calendar rule.

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_independent_firing
    """
    ctx = create_completed_consult(aca_preventive_enabled=False)
    resp = api.create_superbill(create_superbill_payload(
        ctx["consult"]["id"], 25000, 15000, is_aca_preventive=True), BILLING)
    validate_error(resp, ApiErrorId.ERR_ACA_PREVENTIVE_DISABLED.value)


# ─── cross_entity_state_dependency / superbill_create_requires_consult_completed ─

def test_superbill_against_in_progress_consult_rejected(api):
    """PRD §3.9: "Drafting requires the parent consult to be `COMPLETED`, otherwise
    `ERR_CONSULT_NOT_COMPLETED`."

    A superbill drafted against an IN_PROGRESS (started, not completed) consult is
    rejected with ERR_CONSULT_NOT_COMPLETED.

    Design: Difficulty/cross_entity_state_dependency/superbill_create_requires_consult_completed
    """
    ctx = create_in_progress_consult()
    resp = api.create_superbill(create_superbill_payload(
        ctx["consult"]["id"], 25000, 15000, is_aca_preventive=True), BILLING)
    validate_error(resp, ApiErrorId.ERR_CONSULT_NOT_COMPLETED.value)


def test_superbill_against_completed_consult_succeeds(api):
    """PRD §3.9: "Against a `COMPLETED` consult, the specialist drafts a `Superbill`
    by naming the `consult_id`, the provider's `billed_amount_cents` submitted to the
    insurer, and the insurer's `allowed_amount_cents`".

    The complementary positive path: a superbill drafted against a COMPLETED consult
    is accepted and opens in DRAFT.

    Design: Difficulty/cross_entity_state_dependency/superbill_create_requires_consult_completed
    """
    ctx = create_completed_consult()
    sb = validate_success(api.create_superbill(create_superbill_payload(
        ctx["consult"]["id"], 25000, 15000, is_aca_preventive=True), BILLING), 201)
    assert sb["status"] == "DRAFT", f"expected DRAFT, got {sb['status']}"


# ─── Corner: validations / create_consult_cross_practice_consultant_returns_409 ─

def test_consult_with_cross_practice_consultant_rejected(api):
    """PRD §3.3: "The consultant and client must both belong to the same practice as
    the consult itself; a mismatch is rejected with `ERR_CROSS_PRACTICE_REFERENCE`."

    A consult under practice 2 naming a consultant from practice 1 is rejected with
    ERR_CROSS_PRACTICE_REFERENCE.

    Design: Corner/validations/create_consult_cross_practice_consultant_returns_409
    """
    prac1 = create_practice(name="Practice One")
    prac2 = create_practice(name="Practice Two")
    cons1 = create_consultant(prac1["id"])
    client2 = create_client(prac2["id"])

    resp = api.create_consult(create_consult_payload(
        prac2["id"], client2["id"], cons1["id"],
        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CROSS_PRACTICE_REFERENCE.value)


# ─── Corner: validations / package_consult_no_credits_returns_402 ───────────

def test_package_consult_with_no_credits_rejected_402(api):
    """PRD §3.3: "A package-paid consult may only be scheduled when the client has at
    least one remaining credit — `package_credits_remaining` of one or more — and
    otherwise the request is rejected with `ERR_NO_PACKAGE_CREDITS`."

    An ACTIVE client whose 1-visit package is fully consumed cannot schedule another
    PACKAGE consult -> ERR_NO_PACKAGE_CREDITS (402).

    Design: Corner/validations/package_consult_no_credits_returns_402
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T15:00:00Z")
    prac, cons = ctx["practice"], ctx["consultant"]
    pkg = create_package(prac["id"], "ONE_VISIT", included_visits=1, price_cents=10000)
    client = create_client(prac["id"], package_id=pkg["id"])

    c1 = create_consult(prac["id"], client["id"], cons["id"],
                        "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z", pay_method="PACKAGE")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(c1["id"]), make_consultant_headers(cons["id"])))
    get_success_data(api.start_consult(c1["id"], make_consultant_headers(cons["id"])))
    get_success_data(api.complete_consult(c1["id"], make_consultant_headers(cons["id"])))

    resp = api.create_consult(create_consult_payload(
        prac["id"], client["id"], cons["id"],
        "2026-06-11T15:00:00Z", "2026-06-11T16:00:00Z", pay_method="PACKAGE"), FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_NO_PACKAGE_CREDITS.value)
