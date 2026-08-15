"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at 2026-08-01T00:00:00Z).

The canonical lifecycle chain is layered:
  create_district / create_owner / create_parcel        (roll building, DRAFT)
  open_petition -> sign_and_verify (per parcel) -> close_petition
      -> district in SCOPING
  submit_estimate (+ OCC version fetch) -> approve_estimate
      -> ready for hearing
  schedule_hearing -> record_hearing_held -> close_objection_window
      -> district in COUNCIL_REVIEW
  record_resolution(APPROVE) -> district APPROVED, assessments LEVIED
  create_phase -> start_phase -> district CONSTRUCTION
  complete_phase -> complete_construction -> finalize_true_up -> BILLING
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_change_order_payload,
    create_district_payload,
    create_hearing_payload,
    create_objection_payload,
    create_owner_payload,
    create_parcel_payload,
    create_payment_payload,
    create_phase_payload,
)
from .test_users import TEST_USERS, make_engineer_headers, make_property_owner_headers


def _ok(response, what: str):
    """Lenient setup validation: any 2xx is fine; failures raise a clear
    'Setup failed' error naming the step."""
    if response.status_code // 100 != 2:
        try:
            body = response.json()
        except Exception:
            body = response.text
        raise AssertionError(
            f"Setup failed at '{what}': HTTP {response.status_code} — {body}"
        )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return _ok(
        api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["admin_headers"]),
        f"set_clock({to_iso8601})",
    )


def create_district(name="Test District", methodology="PER_PARCEL",
                    interest_method="SIMPLE", **overrides) -> dict:
    payload = create_district_payload(
        name=name, methodology=methodology, interest_method=interest_method, **overrides
    )
    return _ok(
        api_client.create_district(payload, TEST_USERS["clerk_headers"]),
        f"create_district({name})",
    )


def create_owner(full_name="Test Owner", email="owner@x.test",
                 mailing_address="1 Main St") -> dict:
    payload = create_owner_payload(
        full_name=full_name, email=email, mailing_address=mailing_address
    )
    return _ok(
        api_client.create_owner(payload, TEST_USERS["clerk_headers"]),
        f"create_owner({email})",
    )


def create_parcel(district_id: str, owner_id: str, parcel_number="P-001",
                  frontage_ft=100.0, exempt=None) -> dict:
    overrides = {}
    if exempt is not None:
        overrides["exempt"] = exempt
    payload = create_parcel_payload(
        district_id=district_id, owner_id=owner_id,
        parcel_number=parcel_number, frontage_ft=frontage_ft, **overrides
    )
    return _ok(
        api_client.create_parcel(payload, TEST_USERS["clerk_headers"]),
        f"create_parcel({parcel_number})",
    )


def get_district(district_id: str) -> dict:
    return _ok(
        api_client.get_district(district_id, TEST_USERS["clerk_headers"]),
        f"get_district({district_id})",
    )


def district_version(district_id: str) -> int:
    return get_district(district_id)["version"]


def get_assessment(assessment_id: str, owner_id: str = None) -> dict:
    headers = (make_property_owner_headers(owner_id) if owner_id
               else TEST_USERS["finance_headers"])
    return _ok(
        api_client.get_assessment(assessment_id, headers),
        f"get_assessment({assessment_id})",
    )


def list_district_assessments(district_id: str) -> list:
    return _ok(
        api_client.list_district_assessments(district_id, TEST_USERS["finance_headers"]),
        f"list_district_assessments({district_id})",
    )


def list_district_invoices(district_id: str) -> list:
    return _ok(
        api_client.list_district_invoices(district_id, TEST_USERS["finance_headers"]),
        f"list_district_invoices({district_id})",
    )


def list_assessment_invoices(assessment_id: str) -> list:
    return _ok(
        api_client.list_assessment_invoices(assessment_id, TEST_USERS["finance_headers"]),
        f"list_assessment_invoices({assessment_id})",
    )


def list_assessment_payments(assessment_id: str) -> list:
    return _ok(
        api_client.list_assessment_payments(assessment_id, TEST_USERS["finance_headers"]),
        f"list_assessment_payments({assessment_id})",
    )


def get_petition(petition_id: str) -> dict:
    return _ok(
        api_client.get_petition(petition_id, TEST_USERS["clerk_headers"]),
        f"get_petition({petition_id})",
    )


# ---------------------------------------------------------------------------
# Tier 1: petition circulation
# ---------------------------------------------------------------------------

def open_petition(district_id: str) -> dict:
    return _ok(
        api_client.create_petition({"district_id": district_id},
                                   TEST_USERS["clerk_headers"]),
        f"open_petition({district_id})",
    )


def sign_petition(petition_id: str, parcel_id: str, owner_id: str) -> dict:
    return _ok(
        api_client.create_signature(
            {"petition_id": petition_id, "parcel_id": parcel_id},
            make_property_owner_headers(owner_id),
        ),
        f"sign_petition(petition={petition_id}, parcel={parcel_id})",
    )


def verify_signature(signature_id: str) -> dict:
    return _ok(
        api_client.verify_signature(signature_id, TEST_USERS["clerk_headers"]),
        f"verify_signature({signature_id})",
    )


def sign_and_verify(petition_id: str, parcel_id: str, owner_id: str) -> dict:
    sig = sign_petition(petition_id, parcel_id, owner_id)
    return verify_signature(sig["id"])


def close_petition(petition_id: str) -> dict:
    return _ok(
        api_client.close_petition(petition_id, TEST_USERS["clerk_headers"]),
        f"close_petition({petition_id})",
    )


# ---------------------------------------------------------------------------
# Tier 2: estimates and hearings
# ---------------------------------------------------------------------------

def submit_estimate(district_id: str, contract_price_cents=100000,
                    contingency_cents=0, engineer_id="eng-1") -> dict:
    version = district_version(district_id)
    payload = {
        "district_id": district_id,
        "expected_district_version": version,
        "contract_price_cents": contract_price_cents,
        "contingency_cents": contingency_cents,
    }
    return _ok(
        api_client.create_cost_estimate(payload, make_engineer_headers(engineer_id)),
        f"submit_estimate({district_id}, {contract_price_cents})",
    )


def approve_estimate(estimate_id: str, engineer_id="eng-1") -> dict:
    return _ok(
        api_client.approve_cost_estimate(estimate_id, make_engineer_headers(engineer_id)),
        f"approve_estimate({estimate_id})",
    )


def submit_and_approve_estimate(district_id: str, contract_price_cents=100000,
                                contingency_cents=0, engineer_id="eng-1") -> dict:
    estimate = submit_estimate(district_id, contract_price_cents,
                               contingency_cents, engineer_id)
    return approve_estimate(estimate["id"], engineer_id)


def schedule_hearing(district_id: str, hearing_date="2026-08-15T00:00:00Z",
                     venue="City Hall Room A") -> dict:
    payload = create_hearing_payload(
        district_id=district_id, hearing_date=hearing_date, venue=venue
    )
    return _ok(
        api_client.create_hearing(payload, TEST_USERS["clerk_headers"]),
        f"schedule_hearing({district_id}, {venue})",
    )


def record_hearing_held(hearing_id: str, at="2026-08-15T10:00:00Z") -> dict:
    if at is not None:
        set_clock(at)
    return _ok(
        api_client.record_hearing_held(hearing_id, TEST_USERS["clerk_headers"]),
        f"record_hearing_held({hearing_id})",
    )


def close_objection_window(district_id: str, at="2026-08-31T00:00:00Z") -> dict:
    if at is not None:
        set_clock(at)
    return _ok(
        api_client.close_objection_window(district_id, TEST_USERS["clerk_headers"]),
        f"close_objection_window({district_id})",
    )


def record_resolution(district_id: str, motion="APPROVE", votes_for=3,
                      votes_against=0, president_id="council-1") -> dict:
    version = district_version(district_id)
    payload = {
        "district_id": district_id,
        "expected_district_version": version,
        "motion": motion,
        "votes_for": votes_for,
        "votes_against": votes_against,
    }
    return _ok(
        api_client.create_resolution(
            payload, {"X-User-ID": president_id, "X-User-Role": "CouncilPresident"}
        ),
        f"record_resolution({district_id}, {motion} {votes_for}-{votes_against})",
    )


# ---------------------------------------------------------------------------
# Tier 3: objections
# ---------------------------------------------------------------------------

def file_objection(hearing_id: str, parcel_id: str, owner_id: str,
                   grounds="objection grounds") -> dict:
    payload = create_objection_payload(
        hearing_id=hearing_id, parcel_id=parcel_id, grounds=grounds
    )
    return _ok(
        api_client.create_objection(payload, make_property_owner_headers(owner_id)),
        f"file_objection(hearing={hearing_id}, parcel={parcel_id})",
    )


# ---------------------------------------------------------------------------
# Tier 4: construction
# ---------------------------------------------------------------------------

def create_phase(district_id: str, name="PH1", crew_name="Alpha",
                 start_date="2026-09-10", end_date="2026-10-10",
                 estimated_cost_cents=50000, engineer_id="eng-1") -> dict:
    payload = create_phase_payload(
        district_id=district_id, name=name, crew_name=crew_name,
        start_date=start_date, end_date=end_date,
        estimated_cost_cents=estimated_cost_cents,
    )
    return _ok(
        api_client.create_construction_phase(payload, make_engineer_headers(engineer_id)),
        f"create_phase({district_id}, {name})",
    )


def start_phase(phase_id: str, at="2026-09-10T09:00:00Z",
                engineer_id="eng-1") -> dict:
    if at is not None:
        set_clock(at)
    return _ok(
        api_client.start_phase(phase_id, make_engineer_headers(engineer_id)),
        f"start_phase({phase_id})",
    )


def complete_phase(phase_id: str, at="2026-10-10T17:00:00Z",
                   engineer_id="eng-1") -> dict:
    if at is not None:
        set_clock(at)
    return _ok(
        api_client.complete_phase(phase_id, make_engineer_headers(engineer_id)),
        f"complete_phase({phase_id})",
    )


def complete_construction(district_id: str, engineer_id="eng-1") -> dict:
    return _ok(
        api_client.complete_construction(district_id, make_engineer_headers(engineer_id)),
        f"complete_construction({district_id})",
    )


def propose_change_order(district_id: str, amount_cents=5000, phase_id=None,
                         description="overrun", engineer_id="eng-1") -> dict:
    overrides = {}
    if phase_id is not None:
        overrides["phase_id"] = phase_id
    payload = create_change_order_payload(
        district_id=district_id, description=description,
        amount_cents=amount_cents, **overrides
    )
    return _ok(
        api_client.create_change_order(payload, make_engineer_headers(engineer_id)),
        f"propose_change_order({district_id}, {amount_cents})",
    )


def approve_change_order(change_order_id: str, engineer_id="eng-2") -> dict:
    return _ok(
        api_client.approve_change_order(change_order_id, make_engineer_headers(engineer_id)),
        f"approve_change_order({change_order_id})",
    )


# ---------------------------------------------------------------------------
# Tier 5: assessments, options, payments, true-up
# ---------------------------------------------------------------------------

def select_payment_option(assessment_id: str, owner_id: str, option="INSTALLMENTS",
                          term_years=5) -> dict:
    payload = {"option": option}
    if term_years is not None:
        payload["term_years"] = term_years
    return _ok(
        api_client.select_payment_option(
            assessment_id, payload, make_property_owner_headers(owner_id)
        ),
        f"select_payment_option({assessment_id}, {option})",
    )


def post_payment(assessment_id: str, owner_id: str, amount_cents: int,
                 method="ACH") -> dict:
    version = get_assessment(assessment_id, owner_id)["version"]
    payload = create_payment_payload(
        parcel_assessment_id=assessment_id,
        expected_parcel_assessment_version=version,
        amount_cents=amount_cents,
        method=method,
    )
    return _ok(
        api_client.create_payment(payload, make_property_owner_headers(owner_id)),
        f"post_payment({assessment_id}, {amount_cents})",
    )


def finalize_true_up(district_id: str, at="2026-10-20T00:00:00Z") -> dict:
    if at is not None:
        set_clock(at)
    return _ok(
        api_client.finalize_true_up(district_id, TEST_USERS["finance_headers"]),
        f"finalize_true_up({district_id})",
    )


def billing_run(district_id: str) -> dict:
    return _ok(
        api_client.billing_run(district_id, TEST_USERS["finance_headers"]),
        f"billing_run({district_id})",
    )


# ---------------------------------------------------------------------------
# Composite lifecycle drivers
# ---------------------------------------------------------------------------

def make_roll(district_id: str, frontages, prefix: str):
    """Create one owner + one parcel per frontage value. Parcels are numbered
    P-001.. in order. Returns list of (owner, parcel) tuples."""
    pairs = []
    for i, frontage in enumerate(frontages, start=1):
        owner = create_owner(full_name=f"Owner {prefix}{i}",
                             email=f"{prefix}-o{i}@x.test",
                             mailing_address=f"{i} Main St")
        parcel = create_parcel(district_id, owner["id"],
                               parcel_number=f"P-{i:03d}", frontage_ft=frontage)
        pairs.append((owner, parcel))
    return pairs


def drive_to_scoping(name, frontages=(100.0,), sign_slice=None, prefix="fx",
                     methodology="PER_PARCEL", interest_method="SIMPLE",
                     **district_overrides):
    """District -> DRAFT roll -> petition signed+verified by the chosen parcels
    (default: all) -> close -> SCOPING. Returns a context dict."""
    district = create_district(name=name, methodology=methodology,
                               interest_method=interest_method, **district_overrides)
    pairs = make_roll(district["id"], frontages, prefix)
    petition = open_petition(district["id"])
    chosen = pairs if sign_slice is None else [pairs[i] for i in sign_slice]
    signatures = [sign_and_verify(petition["id"], parcel["id"], owner["id"])
                  for owner, parcel in chosen]
    petition = close_petition(petition["id"])
    district = get_district(district["id"])
    return {
        "district": district,
        "pairs": pairs,
        "petition": petition,
        "signatures": signatures,
    }


def drive_to_hearing_scheduled(name, frontages=(100.0,), prefix="fx",
                               methodology="PER_PARCEL", interest_method="SIMPLE",
                               contract_price_cents=100000, contingency_cents=0,
                               hearing_date="2026-08-15T00:00:00Z",
                               venue="City Hall Room A", sign_slice=None,
                               **district_overrides):
    """Full chain through SCOPING to HEARING_SCHEDULED: approved estimate and
    scheduled hearing (which publishes the preliminary roll)."""
    ctx = drive_to_scoping(name, frontages, sign_slice=sign_slice, prefix=prefix,
                           methodology=methodology, interest_method=interest_method,
                           **district_overrides)
    estimate = submit_and_approve_estimate(
        ctx["district"]["id"], contract_price_cents, contingency_cents
    )
    hearing = schedule_hearing(ctx["district"]["id"], hearing_date, venue)
    ctx["estimate"] = estimate
    ctx["hearing"] = hearing
    ctx["district"] = get_district(ctx["district"]["id"])
    return ctx


def drive_to_objection_window(name, frontages=(100.0,), prefix="fx",
                              held_at="2026-08-15T10:00:00Z", **kwargs):
    """Through HEARING_SCHEDULED, then record the hearing held so the district
    sits in OBJECTION_WINDOW."""
    ctx = drive_to_hearing_scheduled(name, frontages, prefix=prefix, **kwargs)
    ctx["hearing"] = record_hearing_held(ctx["hearing"]["id"], at=held_at)
    ctx["district"] = get_district(ctx["district"]["id"])
    return ctx


def drive_to_council_review(name, frontages=(100.0,), prefix="fx",
                            close_at="2026-08-31T00:00:00Z", **kwargs):
    """Through OBJECTION_WINDOW, then close the window -> COUNCIL_REVIEW."""
    ctx = drive_to_objection_window(name, frontages, prefix=prefix, **kwargs)
    ctx["district"] = close_objection_window(ctx["district"]["id"], at=close_at)
    return ctx


def drive_to_approved(name, frontages=(100.0,), prefix="fx", **kwargs):
    """Through COUNCIL_REVIEW, then record an adopted APPROVE resolution ->
    APPROVED with the roll LEVIED."""
    ctx = drive_to_council_review(name, frontages, prefix=prefix, **kwargs)
    ctx["resolution"] = record_resolution(ctx["district"]["id"], motion="APPROVE",
                                          votes_for=3, votes_against=0)
    ctx["district"] = get_district(ctx["district"]["id"])
    ctx["assessments"] = list_district_assessments(ctx["district"]["id"])
    return ctx


def drive_to_construction(name, frontages=(100.0,), prefix="fx",
                          phase_start_at="2026-09-10T09:00:00Z", **kwargs):
    """Through APPROVED, then plan + start one phase -> district CONSTRUCTION."""
    ctx = drive_to_approved(name, frontages, prefix=prefix, **kwargs)
    phase = create_phase(ctx["district"]["id"])
    ctx["phase"] = start_phase(phase["id"], at=phase_start_at)
    ctx["district"] = get_district(ctx["district"]["id"])
    return ctx


def drive_to_billing(name, frontages=(100.0,), prefix="fx",
                     option=None, term_years=5,
                     true_up_at="2026-10-20T00:00:00Z",
                     prepay_amounts=None, **kwargs):
    """Full chain to BILLING: one phase completed, construction completed,
    true-up finalized.

    option: None (leave assessments unselected -> defaulted at true-up),
            "INSTALLMENTS" (select with term_years on every assessment), or
            "PREPAY_FULL" (select and post the full preliminary payment).
    prepay_amounts: optional list of explicit amounts for PREPAY_FULL.
    Returns context with assessments and invoices after true-up."""
    ctx = drive_to_construction(name, frontages, prefix=prefix, **kwargs)
    district_id = ctx["district"]["id"]
    if option is not None:
        for i, assessment in enumerate(ctx["assessments"]):
            owner = ctx["pairs"][i][0]
            select_payment_option(
                assessment["id"], owner["id"], option=option,
                term_years=term_years if option == "INSTALLMENTS" else None,
            )
            if option == "PREPAY_FULL":
                amount = (prepay_amounts[i] if prepay_amounts
                          else assessment["preliminary_amount_cents"])
                post_payment(assessment["id"], owner["id"], amount)
    complete_phase(ctx["phase"]["id"])
    complete_construction(district_id)
    ctx["district"] = finalize_true_up(district_id, at=true_up_at)
    ctx["assessments"] = list_district_assessments(district_id)
    ctx["invoices"] = list_district_invoices(district_id)
    return ctx
