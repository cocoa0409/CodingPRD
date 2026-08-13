"""Composite setup helpers.

The interesting claims in this PRD require the system to be in a state that
takes 5-15 API calls to reach (a published cycle, a rejected attestation, a
confirmed discrepancy, ...). These helpers encapsulate those multi-step
preambles so tests can focus on assertions. Every helper builds its state from
scratch against PRD-declared endpoints and uses the lenient get_success_data
validator so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_charge_record_payload,
    create_contract_payload,
    create_cycle_payload,
    create_discrepancy_payload,
    create_facility_payload,
    create_machine_file_payload,
    create_payer_payload,
    create_rate_payload,
    create_service_item_payload,
    create_shoppable_list_payload,
    shoppable_entry,
)
from .test_users import TEST_USERS, make_officer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["contract_manager_headers"]
OFFICER = TEST_USERS["transparency_officer_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
CONSUMER = TEST_USERS["consumer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------
def create_facility(**overrides) -> dict:
    """Register a facility. Returns the created Facility."""
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), ADMIN))


def create_payer(**overrides) -> dict:
    """Register a payer. Returns the created Payer."""
    return get_success_data(
        api_client.create_payer(create_payer_payload(**overrides), MANAGER))


def create_contract(facility_id, payer_id=None, **overrides) -> dict:
    """Create a DRAFT payer contract (creating a payer when none is given)."""
    if payer_id is None:
        payer_id = create_payer()["id"]
    return get_success_data(api_client.create_payer_contract(
        create_contract_payload(facility_id, payer_id, **overrides), MANAGER))


def activate_contract(contract_id) -> dict:
    return get_success_data(api_client.activate_contract(contract_id, MANAGER))


def create_active_contract(facility_id, payer_id=None, **overrides) -> dict:
    """Create a contract and activate it. Returns the ACTIVE contract."""
    contract = create_contract(facility_id, payer_id, **overrides)
    return activate_contract(contract["id"])


def create_service_item(facility_id, **overrides) -> dict:
    """Register a service item (born ACTIVE). Returns the ServiceItem."""
    return get_success_data(api_client.create_service_item(
        create_service_item_payload(facility_id, **overrides), OFFICER))


def create_rate(contract_id, service_item_id, **overrides) -> dict:
    """Create a negotiated rate under a DRAFT/RENEGOTIATING contract."""
    return get_success_data(api_client.create_rate(
        create_rate_payload(contract_id, service_item_id, **overrides),
        MANAGER))


def create_cycle(facility_id, **overrides) -> dict:
    """Open a publication cycle (born OPEN, posture COLLECTING)."""
    return get_success_data(api_client.create_cycle(
        create_cycle_payload(facility_id, **overrides), OFFICER))


def create_charge_record(facility_id, publication_cycle_id, service_item_id,
                         **overrides) -> dict:
    """Extract a charge record into an OPEN cycle (born DRAFT)."""
    return get_success_data(api_client.create_charge_record(
        create_charge_record_payload(
            facility_id, publication_cycle_id, service_item_id, **overrides),
        OFFICER))


def validate_record(record_id) -> dict:
    return get_success_data(
        api_client.validate_charge_record(record_id, OFFICER))


def freeze_cycle(cycle_id) -> dict:
    """Freeze an OPEN cycle. Returns the FROZEN cycle (with fresh version)."""
    return get_success_data(api_client.freeze_cycle(cycle_id, OFFICER))


def get_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, OFFICER))


def generate_machine_file(cycle_id, file_format="JSON",
                          expected_version=None) -> dict:
    """Generate (seal) a machine-readable file for a FROZEN cycle, reading the
    current cycle version first to satisfy the OCC guard."""
    if expected_version is None:
        expected_version = get_cycle(cycle_id)["version"]
    return get_success_data(api_client.create_machine_file(
        create_machine_file_payload(cycle_id, expected_version,
                                    file_format=file_format),
        OFFICER))


def validate_machine_file(file_id) -> dict:
    return get_success_data(api_client.validate_machine_file(file_id, OFFICER))


def publish_cycle(cycle_id) -> dict:
    return get_success_data(api_client.publish_cycle(cycle_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: rated-item scenarios (facility + contract + rate chain)
# ---------------------------------------------------------------------------
def setup_rated_item(facility_overrides=None, item_overrides=None,
                     contract_overrides=None, rate_overrides=None,
                     payer_overrides=None) -> dict:
    """Facility + payer + DISCLOSE_ALLOWED contract + item + rate, with the
    contract ACTIVATED (so the rate is ACTIVE and includible)."""
    facility = create_facility(**(facility_overrides or {}))
    payer = create_payer(**(payer_overrides or {}))
    contract = create_contract(facility["id"], payer["id"],
                               **(contract_overrides or {}))
    item = create_service_item(facility["id"], **(item_overrides or {}))
    rate = create_rate(contract["id"], item["id"], **(rate_overrides or {}))
    contract = activate_contract(contract["id"])
    return {"facility": facility, "payer": payer, "contract": contract,
            "item": item, "rate": rate}


def setup_open_cycle_with_record(cash=50000, **kwargs) -> dict:
    """Rated-item scenario plus an OPEN cycle holding one DRAFT record."""
    cycle_overrides = kwargs.pop("cycle_overrides", None) or {}
    ctx = setup_rated_item(**kwargs)
    cycle = create_cycle(ctx["facility"]["id"], **cycle_overrides)
    record = create_charge_record(ctx["facility"]["id"], cycle["id"],
                                  ctx["item"]["id"], discounted_cash_cents=cash)
    ctx.update({"cycle": cycle, "record": record})
    return ctx


def setup_validated_record(cash=50000, **kwargs) -> dict:
    """OPEN cycle with one VALIDATED record (default rate 40% of gross
    100000 -> min/max/derived 40000 under EXACT_MIN)."""
    ctx = setup_open_cycle_with_record(cash=cash, **kwargs)
    ctx["record"] = validate_record(ctx["record"]["id"])
    return ctx


def setup_frozen_cycle(cash=50000, **kwargs) -> dict:
    """One VALIDATED record, cycle FROZEN (default min_records_per_cycle == 1,
    so posture is FREEZABLE with one validated record)."""
    ctx = setup_validated_record(cash=cash, **kwargs)
    ctx["cycle"] = freeze_cycle(ctx["cycle"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full publication lifecycle
# ---------------------------------------------------------------------------
def setup_published_cycle(cash=50000, file_format="JSON",
                          cycle_overrides=None, **kwargs) -> dict:
    """Full chain: facility + payer + ACTIVE contract + item + ACTIVE rate +
    cycle with one record VALIDATED + cycle FROZEN + file SEALED/VALID +
    cycle PUBLISHED. Returns every entity, incl. the PUBLISHED file."""
    ctx = setup_frozen_cycle(cash=cash,
                             cycle_overrides=cycle_overrides, **kwargs)
    cycle_id = ctx["cycle"]["id"]
    file_ = generate_machine_file(cycle_id, file_format=file_format)
    file_ = validate_machine_file(file_["id"])
    ctx["file"] = file_
    ctx["cycle"] = publish_cycle(cycle_id)
    ctx["record"] = get_success_data(
        api_client.get_charge_record(ctx["record"]["id"], OFFICER))
    return ctx


def setup_published_annual_cycle(**kwargs) -> dict:
    """Published ANNUAL cycle covering calendar year 2026 — the evidence an
    attestation submission relies on."""
    kwargs.setdefault("cycle_overrides", {
        "cycle_type": "ANNUAL",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2027-01-01T00:00:00Z",
    })
    return setup_published_cycle(**kwargs)


def setup_submitted_attestation(**kwargs) -> dict:
    """Published ANNUAL cycle + attestation SUBMITTED for 2026 (the default
    logical clock reads 2026-08-01, so the year matches)."""
    ctx = setup_published_annual_cycle(**kwargs)
    facility = get_success_data(api_client.submit_attestation(
        ctx["facility"]["id"], {"attestation_year": 2026}, AUDITOR))
    ctx["facility"] = facility
    return ctx


def setup_rejected_attestation(plan_due_date="2026-09-01T00:00:00Z",
                               **kwargs) -> dict:
    """Facility in REJECTED attestation state with rejected_at stamped at the
    default logical clock (2026-08-01T00:00:00Z)."""
    ctx = setup_submitted_attestation(**kwargs)
    facility = get_success_data(api_client.cms_decision(
        ctx["facility"]["id"],
        {"decision": "REJECT_ATTESTATION", "plan_due_date": plan_due_date},
        ADMIN))
    ctx["facility"] = facility
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: discrepancy / correction pipeline states
# ---------------------------------------------------------------------------
def setup_confirmed_discrepancy(reporter_headers=None, **kwargs) -> dict:
    """Published cycle + discrepancy report triaged CONFIRMED (the disputed
    record is FLAGGED)."""
    ctx = setup_published_cycle(**kwargs)
    discrepancy = get_success_data(api_client.create_discrepancy(
        create_discrepancy_payload(ctx["cycle"]["id"], ctx["record"]["id"]),
        reporter_headers or CONSUMER))
    discrepancy = get_success_data(api_client.triage_discrepancy(
        discrepancy["id"], {"outcome": "CONFIRMED"}, AUDITOR))
    ctx["discrepancy"] = discrepancy
    ctx["record"] = get_success_data(
        api_client.get_charge_record(ctx["record"]["id"], OFFICER))
    return ctx


def setup_correction_proposed(proposer="officer-a", proposal=None, **kwargs):
    """CONFIRMED discrepancy with a correction PROPOSED by `proposer`."""
    ctx = setup_confirmed_discrepancy(**kwargs)
    payload = proposal if proposal is not None else {
        "proposed_gross_charge_cents": 90000}
    discrepancy = get_success_data(api_client.propose_correction(
        ctx["discrepancy"]["id"], payload, make_officer_headers(proposer)))
    ctx["discrepancy"] = discrepancy
    ctx["proposer"] = proposer
    return ctx


def setup_correction_approved(proposer="officer-a", approver="officer-b",
                              **kwargs) -> dict:
    """Correction at CORRECTION_APPROVED (proposed by proposer, approved by a
    different approver — segregation of duties)."""
    ctx = setup_correction_proposed(proposer=proposer, **kwargs)
    discrepancy = get_success_data(api_client.approve_correction(
        ctx["discrepancy"]["id"], make_officer_headers(approver)))
    ctx["discrepancy"] = discrepancy
    ctx["approver"] = approver
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: shoppable list states
# ---------------------------------------------------------------------------
def create_shoppable_list(facility_id, entries, **overrides) -> dict:
    """Create a DRAFT shoppable-service list."""
    return get_success_data(api_client.create_shoppable_list(
        create_shoppable_list_payload(facility_id, entries, **overrides),
        OFFICER))


def certify_list(list_id) -> dict:
    return get_success_data(api_client.certify_list(list_id, OFFICER))


def publish_list(list_id) -> dict:
    return get_success_data(api_client.publish_list(list_id, OFFICER))


def setup_published_shoppable_list(entry_overrides=None,
                                   facility_overrides=None, **kwargs) -> dict:
    """Published cycle (record for the mandated item) + a list certified and
    published for that item. Facility thresholds default to 1/1 so a
    single-entry list certifies."""
    fac_ov = {"shoppable_min_entries": 1, "mandated_min_entries": 1}
    fac_ov.update(facility_overrides or {})
    item_ov = {"cms_shoppable_mandated": True}
    item_ov.update((kwargs.pop("item_overrides", None) or {}))
    ctx = setup_published_cycle(facility_overrides=fac_ov,
                                item_overrides=item_ov, **kwargs)
    entry = shoppable_entry(ctx["item"]["id"], **(entry_overrides or {}))
    lst = create_shoppable_list(ctx["facility"]["id"], [entry])
    lst = certify_list(lst["id"])
    lst = publish_list(lst["id"])
    ctx["list"] = lst
    return ctx
