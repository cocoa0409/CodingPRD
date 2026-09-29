"""Composite setup helpers.

The harness restarts the server before every individual test, so each helper
here builds its state from an empty database using only endpoints the PRD
declares. Nothing is cached across tests.

Tiers, in dependency order:

1. the logical clock,
2. single-entity creators,
3. lifecycle chains (diligence, signature, an effective agreement, the close),
4. domain composites (scheduled batches, approved enrollments, tranches),
5. named scenario builders reused by whole groups of tests.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_CLOSE_DAY, TEST_DEFAULTS
from .factories import (
    create_affiliation_payload,
    create_clinical_quality_review_payload,
    create_conversion_vendor_payload,
    create_doctor_employment_payload,
    create_doctor_payload,
    create_earnout_tranche_payload,
    create_fee_schedule_item_payload,
    create_migration_batch_payload,
    create_payer_contract_payload,
    create_payer_enrollment_payload,
    create_practice_payload,
    create_service_agreement_payload,
    create_service_line_item_payload,
    create_supply_preference_exception_payload,
    create_vendor_consolidation_payload,
    schedule_cutover_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinical_director_headers,
    make_dentist_headers,
)

COUNSEL = TEST_USERS["deal_counsel_headers"]
LEAD = TEST_USERS["integration_lead_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]
SETTLER = TEST_USERS["finance_settler_headers"]


# ----------------------------------------------------------------------
# Tier 1 — the logical clock
# ----------------------------------------------------------------------


def set_clock(current_utc, headers=None):
    """Move the logical clock to `current_utc` and return the clock payload."""
    res = api_client.set_clock({"current_utc": current_utc}, headers or LEAD)
    return get_success_data(res)


# ----------------------------------------------------------------------
# Tier 2 — single-entity creators
# ----------------------------------------------------------------------


def create_affiliation(headers=None, **overrides):
    res = api_client.create_affiliation(
        create_affiliation_payload(**overrides), headers or COUNSEL
    )
    return get_success_data(res)


def create_conversion_vendor(headers=None, **overrides):
    res = api_client.create_conversion_vendor(
        create_conversion_vendor_payload(**overrides), headers or LEAD
    )
    return get_success_data(res)


def create_practice(affiliation_id, conversion_vendor_id, headers=None, **overrides):
    res = api_client.create_practice(
        create_practice_payload(affiliation_id, conversion_vendor_id, **overrides),
        headers or LEAD,
    )
    return get_success_data(res)


def create_doctor(headers=None, **overrides):
    res = api_client.create_doctor(create_doctor_payload(**overrides), headers or LEAD)
    return get_success_data(res)


def create_employment(practice_id, doctor_id, headers=None, **overrides):
    res = api_client.create_doctor_employment(
        create_doctor_employment_payload(practice_id, doctor_id, **overrides),
        headers or LEAD,
    )
    return get_success_data(res)


def create_service_agreement(practice_id, headers=None, **overrides):
    res = api_client.create_service_agreement(
        create_service_agreement_payload(practice_id, **overrides), headers or COUNSEL
    )
    return get_success_data(res)


def add_service_line_item(service_agreement_id, headers=None, **overrides):
    res = api_client.add_service_line_item(
        service_agreement_id, create_service_line_item_payload(**overrides), headers or COUNSEL
    )
    return get_success_data(res)


def create_payer_contract(practice_id, headers=None, **overrides):
    res = api_client.create_payer_contract(
        create_payer_contract_payload(practice_id, **overrides), headers or FINANCE
    )
    return get_success_data(res)


def add_fee_schedule_item(payer_contract_id, headers=None, **overrides):
    res = api_client.add_fee_schedule_item(
        payer_contract_id, create_fee_schedule_item_payload(**overrides), headers or FINANCE
    )
    return get_success_data(res)


def create_payer_enrollment(
    payer_contract_id, doctor_employment_id, effective_date, headers=None, **overrides
):
    res = api_client.create_payer_enrollment(
        create_payer_enrollment_payload(
            payer_contract_id, doctor_employment_id, effective_date, **overrides
        ),
        headers or LEAD,
    )
    return get_success_data(res)


def create_supply_preference_exception(
    doctor_employment_id, dentist_doctor_id, **overrides
):
    """A dentist requests a formulary exception for their own employment."""
    res = api_client.create_supply_preference_exception(
        create_supply_preference_exception_payload(doctor_employment_id, **overrides),
        make_dentist_headers(dentist_doctor_id),
    )
    return get_success_data(res)


def create_vendor_consolidation(practice_id, headers=None, **overrides):
    res = api_client.create_vendor_consolidation(
        create_vendor_consolidation_payload(practice_id, **overrides), headers or LEAD
    )
    return get_success_data(res)


def create_clinical_quality_review(
    doctor_employment_id, director_doctor_id, **overrides
):
    """A licensed clinical director opens a retrospective chart review."""
    res = api_client.create_clinical_quality_review(
        create_clinical_quality_review_payload(doctor_employment_id, **overrides),
        make_clinical_director_headers(director_doctor_id),
    )
    return get_success_data(res)


def read_practice(practice_id, headers=None):
    return get_success_data(api_client.get_practice(practice_id, headers or LEAD))


def read_affiliation(affiliation_id, headers=None):
    return get_success_data(api_client.get_affiliation(affiliation_id, headers or COUNSEL))


def read_employment(doctor_employment_id, headers=None):
    return get_success_data(
        api_client.get_doctor_employment(doctor_employment_id, headers or LEAD)
    )


def read_migration_batch(migration_batch_id, headers=None):
    return get_success_data(
        api_client.get_migration_batch(migration_batch_id, headers or LEAD)
    )


def read_service_agreement(service_agreement_id, headers=None):
    return get_success_data(
        api_client.get_service_agreement(service_agreement_id, headers or COUNSEL)
    )


def read_doctor(doctor_id, headers=None):
    return get_success_data(api_client.get_doctor(doctor_id, headers or LEAD))


def read_payer_contract(payer_contract_id, headers=None):
    return get_success_data(
        api_client.get_payer_contract(payer_contract_id, headers or FINANCE)
    )


def read_payer_enrollment(payer_enrollment_id, headers=None):
    return get_success_data(
        api_client.get_payer_enrollment(payer_enrollment_id, headers or LEAD)
    )


def read_earnout_tranche(earnout_tranche_id, headers=None):
    return get_success_data(
        api_client.get_earnout_tranche(earnout_tranche_id, headers or FINANCE)
    )


def read_conversion_vendor(conversion_vendor_id, headers=None):
    return get_success_data(
        api_client.get_conversion_vendor(conversion_vendor_id, headers or LEAD)
    )


def read_quality_review(clinical_quality_review_id, director_doctor_id):
    return get_success_data(
        api_client.get_clinical_quality_review(
            clinical_quality_review_id, make_clinical_director_headers(director_doctor_id)
        )
    )


def read_vendor_consolidation(vendor_consolidation_id, headers=None):
    return get_success_data(
        api_client.get_vendor_consolidation(vendor_consolidation_id, headers or LEAD)
    )


def read_supply_preference_exception(supply_preference_exception_id, headers=None):
    return get_success_data(
        api_client.get_supply_preference_exception(
            supply_preference_exception_id, headers or LEAD
        )
    )


def practice_version(practice_id, headers=None):
    """The practice's current `version`, for the optimistic-concurrency guard."""
    return read_practice(practice_id, headers)["version"]


def affiliation_version(affiliation_id, headers=None):
    """The affiliation's current `version`, for the optimistic-concurrency guard."""
    return read_affiliation(affiliation_id, headers)["version"]


# ----------------------------------------------------------------------
# Tier 3 — lifecycle chains
# ----------------------------------------------------------------------


def build_deal_in_draft(
    *,
    clock_utc=None,
    affiliation=None,
    vendor=None,
    practice=None,
    doctor=None,
    employment=None,
):
    """An affiliation in DRAFT with one practice, one doctor and one offer.

    Returns a mutable context dict carrying every entity created, so callers
    can extend it with further practices, doctors or contracts.
    """
    if clock_utc is not None:
        set_clock(clock_utc)
    aff = create_affiliation(**(affiliation or {}))
    ven = create_conversion_vendor(**(vendor or {}))
    prac = create_practice(aff["id"], ven["id"], **(practice or {}))
    doc = create_doctor(**(doctor or {}))
    emp = create_employment(prac["id"], doc["id"], **(employment or {}))
    return {
        "affiliation": aff,
        "affiliation_id": aff["id"],
        "vendor": ven,
        "vendor_id": ven["id"],
        "practice": prac,
        "practice_id": prac["id"],
        "doctor": doc,
        "doctor_id": doc["id"],
        "employment": emp,
        "employment_id": emp["id"],
    }


def add_practice_with_doctor(
    ctx, *, practice=None, doctor=None, employment=None, key="second"
):
    """Attach one more practice, doctor and offer to an existing deal context."""
    prac = create_practice(ctx["affiliation_id"], ctx["vendor_id"], **(practice or {}))
    doc = create_doctor(**(doctor or {}))
    emp = create_employment(prac["id"], doc["id"], **(employment or {}))
    ctx[f"{key}_practice"] = prac
    ctx[f"{key}_practice_id"] = prac["id"]
    ctx[f"{key}_doctor"] = doc
    ctx[f"{key}_doctor_id"] = doc["id"]
    ctx[f"{key}_employment"] = emp
    ctx[f"{key}_employment_id"] = emp["id"]
    return ctx


def add_doctor_with_offer(ctx, practice_id, *, doctor=None, employment=None, key="other"):
    """Offer terms to one more doctor at an existing practice."""
    doc = create_doctor(**(doctor or {}))
    emp = create_employment(practice_id, doc["id"], **(employment or {}))
    ctx[f"{key}_doctor"] = doc
    ctx[f"{key}_doctor_id"] = doc["id"]
    ctx[f"{key}_employment"] = emp
    ctx[f"{key}_employment_id"] = emp["id"]
    return ctx


def advance_to_diligence(affiliation_id, headers=None):
    return get_success_data(
        api_client.advance_diligence(affiliation_id, headers or COUNSEL)
    )


def sign_deal(affiliation_id, headers=None):
    return get_success_data(api_client.sign_affiliation(affiliation_id, headers or COUNSEL))


def make_agreement_effective_at(practice_id, *, line_items=None, **agreement_overrides):
    """Draft, populate, review and make effective one agreement at a practice.

    The affiliation owning the practice must already be `SIGNED` or `CLOSED`,
    because making an agreement effective checks that status.
    """
    agreement = create_service_agreement(practice_id, **agreement_overrides)
    for line in line_items if line_items is not None else [{}]:
        add_service_line_item(agreement["id"], **line)
    get_success_data(api_client.submit_legal_review(agreement["id"], COUNSEL))
    return get_success_data(api_client.make_agreement_effective(agreement["id"], COUNSEL))


def accept_offer(doctor_employment_id, doctor_id):
    """The doctor named by the employment accepts their own offer."""
    return get_success_data(
        api_client.accept_offer(doctor_employment_id, make_dentist_headers(doctor_id))
    )


def close_deal(affiliation_id, headers=None):
    return get_success_data(api_client.close_affiliation(affiliation_id, headers or LEAD))


def build_closed_deal(
    *,
    clock_utc=CLOCK_CLOSE_DAY,
    accept=True,
    affiliation=None,
    vendor=None,
    practice=None,
    doctor=None,
    employment=None,
    line_items=None,
    agreement_overrides=None,
):
    """One affiliation carried all the way from DRAFT to CLOSED.

    With `accept` true the single offer is accepted before the close, so hop
    three of the cascade activates it; with `accept` false it lapses instead.
    """
    ctx = build_deal_in_draft(
        clock_utc=clock_utc,
        affiliation=affiliation,
        vendor=vendor,
        practice=practice,
        doctor=doctor,
        employment=employment,
    )
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])
    ctx["agreement"] = make_agreement_effective_at(
        ctx["practice_id"], line_items=line_items, **(agreement_overrides or {})
    )
    ctx["agreement_id"] = ctx["agreement"]["id"]
    if accept:
        accept_offer(ctx["employment_id"], ctx["doctor_id"])
    ctx["affiliation"] = close_deal(ctx["affiliation_id"])
    ctx["practice"] = read_practice(ctx["practice_id"])
    ctx["employment"] = read_employment(ctx["employment_id"])
    return ctx


def build_closed_deal_two_doctors(
    *,
    clock_utc=CLOCK_CLOSE_DAY,
    second_doctor=None,
    second_employment=None,
    accept_second=False,
    **kwargs,
):
    """A closed deal whose practice offered terms to two doctors.

    By default only the first doctor accepts, so hop three of the close
    cascade writes both of its branches — one activation and one lapse.
    """
    ctx = build_deal_in_draft(clock_utc=clock_utc, **_deal_kwargs(kwargs))
    add_doctor_with_offer(
        ctx,
        ctx["practice_id"],
        doctor=second_doctor or {"full_name": "Beto Alvarez", "npi": "1710000002"},
        employment=second_employment,
        key="second",
    )
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])
    ctx["agreement"] = make_agreement_effective_at(
        ctx["practice_id"],
        line_items=kwargs.get("line_items"),
        **(kwargs.get("agreement_overrides") or {}),
    )
    ctx["agreement_id"] = ctx["agreement"]["id"]
    accept_offer(ctx["employment_id"], ctx["doctor_id"])
    if accept_second:
        accept_offer(ctx["second_employment_id"], ctx["second_doctor_id"])
    ctx["affiliation"] = close_deal(ctx["affiliation_id"])
    ctx["practice"] = read_practice(ctx["practice_id"])
    ctx["employment"] = read_employment(ctx["employment_id"])
    ctx["second_employment"] = read_employment(ctx["second_employment_id"])
    return ctx


def _deal_kwargs(kwargs):
    """Filter a kwargs bag down to the entity-override keys of the draft chain."""
    return {
        key: kwargs[key]
        for key in ("affiliation", "vendor", "practice", "doctor", "employment")
        if key in kwargs
    }


def build_clinical_director(*, state_code=None, **overrides):
    """A licensed doctor who will act in the ClinicalDirector role.

    A director's `X-User-ID` resolves to a Doctor row, and closing a quality
    review requires that doctor's `license_state` to equal the reviewed
    practice's `state_code`.
    """
    payload = {
        "full_name": "Dana Whitfield",
        "npi": "1710000009",
        "license_number": "IL-DDS-9001",
        "license_state": state_code or TEST_DEFAULTS["PRACTICE_STATE_CODE"],
    }
    payload.update(overrides)
    director = create_doctor(**payload)
    return director, make_clinical_director_headers(director["id"])


# ----------------------------------------------------------------------
# Tier 4 — domain composites
# ----------------------------------------------------------------------


def stage_batch(practice_id, *, headers=None, **overrides):
    """Stage one migration batch, reading the practice version guard first."""
    version = practice_version(practice_id)
    res = api_client.create_migration_batch(
        create_migration_batch_payload(practice_id, version, **overrides), headers or LEAD
    )
    return get_success_data(res)


def schedule_batch(migration_batch_id, cutover_start_at, cutover_end_at, headers=None):
    res = api_client.schedule_cutover(
        migration_batch_id,
        schedule_cutover_payload(cutover_start_at, cutover_end_at),
        headers or LEAD,
    )
    return get_success_data(res)


def build_scheduled_batch(
    practice_id, cutover_start_at, cutover_end_at, *, batch_label=None, records_total=None
):
    """Stage one batch and reserve its cutover window in a single step."""
    overrides = {}
    if batch_label is not None:
        overrides["batch_label"] = batch_label
    if records_total is not None:
        overrides["records_total"] = records_total
    batch = stage_batch(practice_id, **overrides)
    return schedule_batch(batch["id"], cutover_start_at, cutover_end_at)


def validate_batch(migration_batch_id, quarantined_count, headers=None):
    res = api_client.validate_batch(
        migration_batch_id, {"quarantined_count": quarantined_count}, headers or LEAD
    )
    return get_success_data(res)


def remediate_batch(migration_batch_id, headers=None, **payload):
    res = api_client.remediate_batch(migration_batch_id, headers or LEAD, payload or None)
    return get_success_data(res)


def rollback_batch(migration_batch_id, rollback_reason, headers=None):
    res = api_client.rollback_batch(
        migration_batch_id, {"rollback_reason": rollback_reason}, headers or LEAD
    )
    return get_success_data(res)


def reconcile_batch(migration_batch_id, headers=None):
    return get_success_data(api_client.reconcile_batch(migration_batch_id, headers or LEAD))


def build_priced_contract(practice_id, *, lines=None, **contract_overrides):
    """A payer contract with one or more priced procedures already stored."""
    contract = create_payer_contract(practice_id, **contract_overrides)
    for line in lines if lines is not None else [{}]:
        add_fee_schedule_item(contract["id"], **line)
    return read_payer_contract(contract["id"])


def submit_enrollment(payer_enrollment_id, headers=None):
    return get_success_data(
        api_client.submit_enrollment(payer_enrollment_id, headers or LEAD)
    )


def approve_enrollment(payer_enrollment_id, headers=None):
    res = api_client.decide_enrollment(
        payer_enrollment_id, {"decision": "APPROVE"}, headers or LEAD
    )
    return get_success_data(res)


def deny_enrollment(payer_enrollment_id, denial_reason, headers=None):
    res = api_client.decide_enrollment(
        payer_enrollment_id,
        {"decision": "DENY", "denial_reason": denial_reason},
        headers or LEAD,
    )
    return get_success_data(res)


def build_approved_enrollment(
    payer_contract_id, doctor_employment_id, effective_date, **overrides
):
    """Open, submit and approve one credentialing enrollment."""
    enrollment = create_payer_enrollment(
        payer_contract_id, doctor_employment_id, effective_date, **overrides
    )
    submit_enrollment(enrollment["id"])
    return approve_enrollment(enrollment["id"])


def activate_fee_schedule(payer_contract_id, dso_schedule_effective_date, headers=None, **extra):
    payload = {"dso_schedule_effective_date": dso_schedule_effective_date}
    payload.update(extra)
    return api_client.activate_fee_schedule(payer_contract_id, payload, headers or FINANCE)


def project_tranche(affiliation_id, *, headers=None, **overrides):
    """Project one earn-out measurement period, reading the version guard first."""
    version = affiliation_version(affiliation_id)
    res = api_client.create_earnout_tranche(
        create_earnout_tranche_payload(affiliation_id, version, **overrides),
        headers or FINANCE,
    )
    return get_success_data(res)


def reserve_tranche(
    earnout_tranche_id,
    reported_net_collections_cents,
    reported_expenses_cents,
    headers=None,
):
    res = api_client.reserve_tranche(
        earnout_tranche_id,
        {
            "reported_net_collections_cents": reported_net_collections_cents,
            "reported_expenses_cents": reported_expenses_cents,
        },
        headers or FINANCE,
    )
    return get_success_data(res)


def settle_tranche(
    earnout_tranche_id, final_net_collections_cents, final_expenses_cents, headers=None
):
    """Settle a reserved tranche; the settling user differs from the reserver."""
    res = api_client.settle_tranche(
        earnout_tranche_id,
        {
            "final_net_collections_cents": final_net_collections_cents,
            "final_expenses_cents": final_expenses_cents,
        },
        headers or SETTLER,
    )
    return get_success_data(res)


def claw_back_tranche(earnout_tranche_id, clawback_reason, headers=None):
    res = api_client.claw_back_tranche(
        earnout_tranche_id, {"clawback_reason": clawback_reason}, headers or SETTLER
    )
    return get_success_data(res)


def harmonize_compensation(doctor_employment_id, monthly_collections_cents, headers=None):
    res = api_client.harmonize_compensation(
        doctor_employment_id,
        {"monthly_collections_cents": list(monthly_collections_cents)},
        headers or FINANCE,
    )
    return get_success_data(res)


def separate_employment(doctor_employment_id, separation_reason="VOLUNTARY", headers=None):
    res = api_client.separate_employment(
        doctor_employment_id, {"separation_reason": separation_reason}, headers or LEAD
    )
    return get_success_data(res)


def decide_supply_exception(
    supply_preference_exception_id, decision, director_doctor_id, **extra
):
    payload = {"decision": decision}
    payload.update(extra)
    res = api_client.decide_supply_preference_exception(
        supply_preference_exception_id,
        payload,
        make_clinical_director_headers(director_doctor_id),
    )
    return get_success_data(res)


def close_quality_review(
    clinical_quality_review_id, outcome, director_doctor_id, **extra
):
    payload = {"outcome": outcome}
    payload.update(extra)
    return api_client.close_clinical_quality_review(
        clinical_quality_review_id,
        payload,
        make_clinical_director_headers(director_doctor_id),
    )


def finalize_consolidation(vendor_consolidation_id, headers=None):
    res = api_client.finalize_vendor_consolidation(
        vendor_consolidation_id, headers or LEAD
    )
    return get_success_data(res)


def standardize_staffing(practice_id, fte_hygiene_ratio_bps, headers=None):
    return api_client.standardize_staffing(
        practice_id, {"fte_hygiene_ratio_bps": fte_hygiene_ratio_bps}, headers or LEAD
    )


# ----------------------------------------------------------------------
# Tier 5 — named scenario builders
# ----------------------------------------------------------------------


def build_closed_deal_with_contract(
    *,
    clock_utc=CLOCK_CLOSE_DAY,
    lines=None,
    payer_name=None,
    **kwargs,
):
    """A closed deal whose practice already held one payer contract at close.

    Because the contract exists before the close, hop four of the cascade
    opens one enrollment against it and hop five carries it to
    `PENDING_CREDENTIALING`.
    """
    ctx = build_deal_in_draft(clock_utc=clock_utc, **_deal_kwargs(kwargs))
    contract_overrides = {}
    if payer_name is not None:
        contract_overrides["payer_name"] = payer_name
    ctx["contract"] = build_priced_contract(
        ctx["practice_id"], lines=lines if lines is not None else [], **contract_overrides
    )
    ctx["contract_id"] = ctx["contract"]["id"]
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])
    ctx["agreement"] = make_agreement_effective_at(
        ctx["practice_id"], line_items=kwargs.get("line_items")
    )
    ctx["agreement_id"] = ctx["agreement"]["id"]
    accept_offer(ctx["employment_id"], ctx["doctor_id"])
    ctx["affiliation"] = close_deal(ctx["affiliation_id"])
    ctx["practice"] = read_practice(ctx["practice_id"])
    ctx["employment"] = read_employment(ctx["employment_id"])
    ctx["contract"] = read_payer_contract(ctx["contract_id"])
    enrollments, _ = _list_enrollments_for_contract(ctx["contract_id"])
    ctx["cascade_enrollments"] = enrollments
    if enrollments:
        ctx["cascade_enrollment_id"] = enrollments[0]["id"]
    return ctx


def _list_enrollments_for_contract(payer_contract_id):
    from prd_bench_local_runner.testing import validate_paginated

    res = api_client.list_payer_enrollments(
        LEAD, {"payer_contract_id": payer_contract_id}
    )
    return validate_paginated(res)


def build_contract_ready_for_activation(
    ctx,
    *,
    lead_effective_date,
    submit_clock,
    lines=None,
    payer_name=None,
):
    """A post-close contract with one priced line and one approved enrollment.

    The contract is created after the close, so the close cascade never
    touched it and its only enrollment is the one opened here.
    """
    contract = build_priced_contract(
        ctx["practice_id"],
        lines=lines if lines is not None else [{}],
        **({"payer_name": payer_name} if payer_name is not None else {}),
    )
    enrollment = create_payer_enrollment(
        contract["id"], ctx["employment_id"], lead_effective_date
    )
    set_clock(submit_clock)
    submit_enrollment(enrollment["id"])
    return read_payer_contract(contract["id"]), read_payer_enrollment(enrollment["id"])


def build_reserved_tranche(
    ctx,
    *,
    reserve_clock,
    reported_net_collections_cents,
    reported_expenses_cents,
    period_label="EO-Y1",
    measurement_start="2026-09-01T00:00:00Z",
    measurement_end="2027-09-01T00:00:00Z",
):
    """Project one tranche on a closed deal and reserve it provisionally."""
    tranche = project_tranche(
        ctx["affiliation_id"],
        period_label=period_label,
        measurement_start=measurement_start,
        measurement_end=measurement_end,
    )
    set_clock(reserve_clock)
    return reserve_tranche(
        tranche["id"], reported_net_collections_cents, reported_expenses_cents
    )


def build_settled_tranche(
    ctx,
    *,
    reserve_clock,
    settle_clock,
    reported_net_collections_cents,
    reported_expenses_cents,
    final_net_collections_cents,
    final_expenses_cents,
    period_label="EO-Y1",
    measurement_start="2026-09-01T00:00:00Z",
    measurement_end="2027-09-01T00:00:00Z",
):
    """Project, reserve and settle one tranche under segregation of duties."""
    reserved = build_reserved_tranche(
        ctx,
        reserve_clock=reserve_clock,
        reported_net_collections_cents=reported_net_collections_cents,
        reported_expenses_cents=reported_expenses_cents,
        period_label=period_label,
        measurement_start=measurement_start,
        measurement_end=measurement_end,
    )
    set_clock(settle_clock)
    return settle_tranche(
        reserved["id"], final_net_collections_cents, final_expenses_cents
    )


def build_approved_supply_exception(ctx, *, director_doctor_id=None, **overrides):
    """One approved formulary exception raised by the deal's active dentist."""
    if director_doctor_id is None:
        director, _ = build_clinical_director()
        director_doctor_id = director["id"]
    exception = create_supply_preference_exception(
        ctx["employment_id"], ctx["doctor_id"], **overrides
    )
    approved = decide_supply_exception(exception["id"], "APPROVE", director_doctor_id)
    return approved, director_doctor_id


__all__ = [
    "COUNSEL",
    "LEAD",
    "FINANCE",
    "SETTLER",
    "set_clock",
    "create_affiliation",
    "create_conversion_vendor",
    "create_practice",
    "create_doctor",
    "create_employment",
    "create_service_agreement",
    "add_service_line_item",
    "create_payer_contract",
    "add_fee_schedule_item",
    "create_payer_enrollment",
    "create_supply_preference_exception",
    "create_vendor_consolidation",
    "create_clinical_quality_review",
    "read_practice",
    "read_affiliation",
    "read_employment",
    "read_migration_batch",
    "read_service_agreement",
    "read_doctor",
    "read_payer_contract",
    "read_payer_enrollment",
    "read_earnout_tranche",
    "read_conversion_vendor",
    "read_quality_review",
    "read_vendor_consolidation",
    "read_supply_preference_exception",
    "practice_version",
    "affiliation_version",
    "build_deal_in_draft",
    "add_practice_with_doctor",
    "add_doctor_with_offer",
    "advance_to_diligence",
    "sign_deal",
    "make_agreement_effective_at",
    "accept_offer",
    "close_deal",
    "build_closed_deal",
    "build_closed_deal_two_doctors",
    "build_clinical_director",
    "stage_batch",
    "schedule_batch",
    "build_scheduled_batch",
    "validate_batch",
    "remediate_batch",
    "rollback_batch",
    "reconcile_batch",
    "build_priced_contract",
    "submit_enrollment",
    "approve_enrollment",
    "deny_enrollment",
    "build_approved_enrollment",
    "activate_fee_schedule",
    "project_tranche",
    "reserve_tranche",
    "settle_tranche",
    "claw_back_tranche",
    "harmonize_compensation",
    "separate_employment",
    "decide_supply_exception",
    "close_quality_review",
    "finalize_consolidation",
    "standardize_staffing",
    "build_closed_deal_with_contract",
    "build_contract_ready_for_activation",
    "build_reserved_tranche",
    "build_settled_tranche",
    "build_approved_supply_exception",
]
