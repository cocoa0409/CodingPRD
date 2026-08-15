"""Composite setup helpers: canonical journeys through the emissions workflow.

Every test boots against an empty database (the runner restarts the server
before each test), so each journey below is built purely from PRD-declared
endpoints. The ladders mirror the cycle lifecycle of PRD §3.2, the record
workflow of §3.3, evidence handling of §3.4, engagements of §3.5, instruments
of §3.6, inventory recalculation of §3.7, targets of §3.8, and questionnaires
of §3.9.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    answer_payload, clock_payload, create_activity_record_payload,
    create_cycle_payload, create_emission_factor_payload,
    create_engagement_payload, create_evidence_payload, create_instrument_payload,
    create_questionnaire_payload, create_site_payload, create_target_payload,
    decision_payload, recalc_inventory_payload, respond_payload,
    retire_payload, review_decision_payload, sha256_hex, transition_payload,
)
from .test_users import (
    ASSURER_ID, SUPPLIER_ID, TEST_USERS, make_assurer_headers,
    make_supplier_headers,
)

# Canonical role headers (module-level aliases for one-import test files).
MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]
LEAD = TEST_USERS["lead_headers"]
ASSURER = TEST_USERS["assurer_headers"]
SUPPLIER = TEST_USERS["supplier_headers"]


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def make_site(**overrides) -> dict:
    """Create an ACTIVE site (PRD §3.1)."""
    return get_success_data(
        api_client.create_site(create_site_payload(**overrides), MANAGER), 201
    )


def make_factor(publish=True, **overrides) -> dict:
    """Create an EmissionFactor; publish it by default (PRD §3.1)."""
    factor = get_success_data(
        api_client.create_emission_factor(create_emission_factor_payload(**overrides), MANAGER),
        201,
    )
    if publish:
        factor = get_success_data(
            api_client.transition_emission_factor(
                factor["id"], transition_payload("PUBLISHED"), MANAGER
            )
        )
    return factor


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), MANAGER))


# ---------------------------------------------------------------------------
# Cycles and inventory
# ---------------------------------------------------------------------------

def make_cycle(name="FY2026", reporting_year=2026) -> dict:
    """Create a DRAFT cycle (its singleton InventoryResult is created with it)."""
    return get_success_data(
        api_client.create_cycle(
            create_cycle_payload(name=name, reporting_year=reporting_year), MANAGER
        ),
        201,
    )


def transition_cycle(cycle_id, to_state, headers=None, **extras) -> dict:
    return get_success_data(
        api_client.transition_cycle(cycle_id, transition_payload(to_state, **extras), headers or MANAGER)
    )


def make_collecting_cycle(name="FY2026", reporting_year=2026) -> dict:
    """Create a cycle and advance it DRAFT -> DATA_COLLECTION."""
    cycle = make_cycle(name=name, reporting_year=reporting_year)
    return transition_cycle(cycle["id"], "DATA_COLLECTION")


def get_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, MANAGER))


def cycle_version(cycle_id) -> int:
    return get_cycle(cycle_id)["version"]


def recalc_inventory(cycle_id) -> dict:
    """Recalculate the cycle's inventory under OCC (PRD §2.8, §3.7).

    Reads the current cycle version, then recalculates with it.
    Returns the CURRENT InventoryResult.
    """
    version = cycle_version(cycle_id)
    return get_success_data(
        api_client.recalculate_inventory(
            cycle_id, recalc_inventory_payload(version), MANAGER
        )
    )


def get_inventory_for_cycle(cycle_id) -> dict:
    """Fetch the singleton InventoryResult of a cycle via the filtered list."""
    data, _meta = validate_paginated(
        api_client.list_inventory_results(MANAGER, params={"cycle_id": cycle_id})
    )
    assert len(data) == 1, f"expected exactly one InventoryResult for cycle {cycle_id}"
    return data[0]


def drive_cycle_to_locked(cycle_id) -> dict:
    """UNDER_REVIEW -> LOCKED. Caller must have inventory CURRENT and no open
    records/engagements (PRD §3.2 lock gates)."""
    transition_cycle(cycle_id, "UNDER_REVIEW")
    return transition_cycle(cycle_id, "LOCKED")


# ---------------------------------------------------------------------------
# Activity records
# ---------------------------------------------------------------------------

def submit_record(cycle_id, site_id, factor_id, steward_headers=None, **overrides) -> dict:
    """Create an ActivityRecord in SUBMITTED (PRD §3.3)."""
    return get_success_data(
        api_client.create_activity_record(
            create_activity_record_payload(cycle_id, site_id, factor_id, **overrides),
            steward_headers or STEWARD,
        ),
        201,
    )


def review_record(record_id, steward_headers=None) -> dict:
    """SUBMITTED -> UNDER_REVIEW (steward hand-off, PRD §3.3)."""
    return get_success_data(
        api_client.transition_activity_record(
            record_id, transition_payload("UNDER_REVIEW"), steward_headers or STEWARD
        )
    )


def approve_record(record_id, analyst_headers=None) -> dict:
    """UNDER_REVIEW -> APPROVED (analyst decision, PRD §3.3)."""
    return get_success_data(
        api_client.transition_activity_record(
            record_id, transition_payload("APPROVED"), analyst_headers or ANALYST
        )
    )


def create_approved_record(cycle_id, site_id, factor_id, **overrides) -> dict:
    """Create a record and walk it SUBMITTED -> UNDER_REVIEW -> APPROVED."""
    record = submit_record(cycle_id, site_id, factor_id, **overrides)
    review_record(record["id"])
    return approve_record(record["id"])


def get_activity_record(record_id) -> dict:
    return get_success_data(api_client.get_activity_record(record_id, MANAGER))


def make_approved_records(cycle_id, site_id, factor_id, quantity, periods) -> list:
    """Approve one record per (period_start, period_end) pair at `quantity`."""
    records = []
    for period_start, period_end in periods:
        records.append(
            create_approved_record(
                cycle_id, site_id, factor_id,
                quantity=quantity, period_start=period_start, period_end=period_end,
            )
        )
    return records


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def upload_evidence(record_id, steward_headers=None, **overrides) -> dict:
    """Upload an EvidenceItem (lands UPLOADED, PRD §3.4)."""
    return get_success_data(
        api_client.upload_evidence(
            record_id, create_evidence_payload(**overrides), steward_headers or STEWARD
        ),
        201,
    )


def verify_evidence(evidence_id, analyst_headers=None) -> dict:
    """UPLOADED -> VERIFIED (analyst, PRD §3.4)."""
    return get_success_data(
        api_client.transition_evidence_item(
            evidence_id, transition_payload("VERIFIED"), analyst_headers or ANALYST
        )
    )


def upload_and_verify_evidence(record_id, seed=1, **overrides) -> dict:
    """Upload then verify one evidence item for a record."""
    overrides.setdefault("file_name", f"invoice-{seed}.pdf")
    overrides.setdefault("sha256_hex", sha256_hex(seed))
    item = upload_evidence(record_id, **overrides)
    return verify_evidence(item["id"])


def get_evidence_item(evidence_id) -> dict:
    return get_success_data(api_client.get_evidence_item(evidence_id, MANAGER))


def verify_evidence_for_records(records, count, seed_start=1) -> list:
    """Upload + verify one evidence item on each of the first `count` records."""
    items = []
    for index, record in enumerate(records[:count]):
        items.append(upload_and_verify_evidence(record["id"], seed=seed_start + index))
    return items


# ---------------------------------------------------------------------------
# Supplier engagements
# ---------------------------------------------------------------------------

def make_engagement(cycle_id, **overrides) -> dict:
    """Create a SupplierEngagement in INVITED at round 1 (PRD §3.5)."""
    return get_success_data(
        api_client.create_supplier_engagement(
            create_engagement_payload(cycle_id, **overrides), ANALYST
        ),
        201,
    )


def respond_to_engagement(engagement_id, supplier_tco2e, contact_user_id=SUPPLIER_ID) -> dict:
    """Supplier respond (must be called with the engagement's contact id)."""
    return get_success_data(
        api_client.respond_to_engagement(
            engagement_id, respond_payload(supplier_tco2e),
            make_supplier_headers(contact_user_id),
        )
    )


def decide_engagement(engagement_id, decision) -> dict:
    """Analyst decision: ACCEPT | REQUEST_REVISION | REINVITE (PRD §3.5)."""
    return get_success_data(
        api_client.decide_engagement(engagement_id, decision_payload(decision), ANALYST)
    )


# ---------------------------------------------------------------------------
# Emission targets
# ---------------------------------------------------------------------------

def make_target(**overrides) -> dict:
    """Create a DRAFT EmissionTarget (PRD §3.8)."""
    return get_success_data(
        api_client.create_target(create_target_payload(**overrides), MANAGER), 201
    )


def transition_target(target_id, to_state) -> dict:
    return get_success_data(
        api_client.transition_target(target_id, transition_payload(to_state), MANAGER)
    )


def activate_target(target_id) -> dict:
    """DRAFT -> APPROVED -> ACTIVE (PRD §3.8)."""
    transition_target(target_id, "APPROVED")
    return transition_target(target_id, "ACTIVE")


def get_target(target_id) -> dict:
    return get_success_data(api_client.get_target(target_id, MANAGER))


# ---------------------------------------------------------------------------
# Renewable instruments
# ---------------------------------------------------------------------------

def make_instrument(**overrides) -> dict:
    """Register a PROCURED RenewableInstrument (PRD §3.6)."""
    return get_success_data(
        api_client.create_instrument(create_instrument_payload(**overrides), MANAGER), 201
    )


def retire_instrument(instrument_id, cycle_id, site_id) -> dict:
    """PROCURED -> RETIRED against (cycle, site) (PRD §3.6)."""
    return get_success_data(
        api_client.retire_instrument(instrument_id, retire_payload(cycle_id, site_id), MANAGER)
    )


def get_instrument(instrument_id) -> dict:
    return get_success_data(api_client.get_instrument(instrument_id, MANAGER))


# ---------------------------------------------------------------------------
# Questionnaire responses
# ---------------------------------------------------------------------------

def make_questionnaire(cycle_id, framework="CDP", lead_headers=None) -> dict:
    """Create a DRAFT QuestionnaireResponse (PRD §3.9)."""
    return get_success_data(
        api_client.create_questionnaire(
            create_questionnaire_payload(cycle_id, framework=framework),
            lead_headers or LEAD,
        ),
        201,
    )


def answer_section(questionnaire_id, section_key, answer_text, lead_headers=None) -> dict:
    return get_success_data(
        api_client.answer_section(
            questionnaire_id, answer_payload(section_key, answer_text), lead_headers or LEAD
        )
    )


def get_questionnaire(questionnaire_id) -> dict:
    return get_success_data(api_client.get_questionnaire(questionnaire_id, MANAGER))


_CDP_ANSWERS = {
    "GOVERNANCE": "Board oversight",
    "RISKS": "Risk register",
    "EMISSIONS": "Inventory summary",
    "TARGETS": "50 by 2030",
}


def answer_all_cdp_sections(questionnaire_id, lead_headers=None) -> dict:
    """Answer all four required CDP sections; returns the final response."""
    questionnaire = None
    for section_key, answer_text in _CDP_ANSWERS.items():
        questionnaire = answer_section(
            questionnaire_id, section_key, answer_text, lead_headers=lead_headers
        )
    return questionnaire


def make_fully_answered_cdp(cycle_id, lead_headers=None) -> dict:
    """CDP questionnaire in DRAFT with every required section answered."""
    questionnaire = make_questionnaire(cycle_id, framework="CDP", lead_headers=lead_headers)
    return answer_all_cdp_sections(questionnaire["id"], lead_headers=lead_headers)


def make_submitted_cdp(cycle_id, lead_headers=None, manager_headers=None) -> dict:
    """CDP questionnaire walked DRAFT -> IN_REVIEW -> APPROVED -> SUBMITTED."""
    lead_headers = lead_headers or LEAD
    manager_headers = manager_headers or MANAGER
    questionnaire = make_fully_answered_cdp(cycle_id, lead_headers=lead_headers)
    questionnaire = get_success_data(
        api_client.transition_questionnaire(
            questionnaire["id"], transition_payload("IN_REVIEW"), lead_headers
        )
    )
    questionnaire = get_success_data(
        api_client.review_questionnaire(
            questionnaire["id"],
            review_decision_payload("APPROVE", review_notes="Controls pass"),
            manager_headers,
        )
    )
    return get_success_data(
        api_client.transition_questionnaire(
            questionnaire["id"], transition_payload("SUBMITTED"), lead_headers
        )
    )


# ---------------------------------------------------------------------------
# Composite lifecycle ladders
# ---------------------------------------------------------------------------

def setup_locked_cycle_with_evidence(name="FY2026", reporting_year=2026,
                                     quantity=100, factor_value=None) -> dict:
    """A cycle driven to LOCKED with one APPROVED record backed by VERIFIED
    evidence (readiness 100.0) and a FROZEN inventory.

    Returns dict with keys: cycle, site, factor, record, evidence, inventory.
    """
    factor_kwargs = {}
    if factor_value is not None:
        factor_kwargs["value_tco2e_per_unit"] = factor_value
    if reporting_year != 2026:
        from .constants import year_window
        start, end = year_window(reporting_year)
        factor_kwargs.update(valid_from=start, valid_to=end)
    site = make_site()
    factor = make_factor(**factor_kwargs)
    cycle = make_collecting_cycle(name=name, reporting_year=reporting_year)
    record = create_approved_record(
        cycle["id"], site["id"], factor["id"],
        quantity=quantity,
        period_start=f"{reporting_year}-01-01T00:00:00Z",
        period_end=f"{reporting_year}-02-01T00:00:00Z",
    )
    evidence = upload_and_verify_evidence(record["id"], seed=101)
    inventory = recalc_inventory(cycle["id"])
    cycle = drive_cycle_to_locked(cycle["id"])
    return {
        "cycle": cycle, "site": site, "factor": factor,
        "record": record, "evidence": evidence, "inventory": inventory,
    }


def setup_under_assurance_cycle(**kwargs) -> dict:
    """LOCKED cycle advanced to UNDER_ASSURANCE (readiness gate satisfied)."""
    bundle = setup_locked_cycle_with_evidence(**kwargs)
    bundle["cycle"] = transition_cycle(bundle["cycle"]["id"], "UNDER_ASSURANCE")
    return bundle


def setup_assured_cycle(**kwargs) -> dict:
    """UNDER_ASSURANCE cycle attested by the AssuranceProvider (PRD §3.2)."""
    bundle = setup_under_assurance_cycle(**kwargs)
    bundle["cycle"] = transition_cycle(
        bundle["cycle"]["id"], "ASSURED",
        headers=make_assurer_headers(ASSURER_ID),
        assurance_statement="Limited assurance, ISAE 3410",
    )
    return bundle


def setup_disclosed_cycle(name="FY2026", reporting_year=2026) -> dict:
    """Full end-to-end drive to the terminal DISCLOSED state (PRD §3.2, §3.9).

    Builds one APPROVED record with VERIFIED evidence (readiness 100.0) and a
    SUBMITTED CDP questionnaire while the cycle is collecting, then walks the
    cycle DATA_COLLECTION -> UNDER_REVIEW -> LOCKED -> UNDER_ASSURANCE ->
    ASSURED -> DISCLOSED.
    """
    site = make_site()
    factor_kwargs = {}
    if reporting_year != 2026:
        from .constants import year_window
        start, end = year_window(reporting_year)
        factor_kwargs.update(valid_from=start, valid_to=end)
    factor = make_factor(**factor_kwargs)
    cycle = make_collecting_cycle(name=name, reporting_year=reporting_year)
    record = create_approved_record(
        cycle["id"], site["id"], factor["id"],
        quantity=100,
        period_start=f"{reporting_year}-01-01T00:00:00Z",
        period_end=f"{reporting_year}-02-01T00:00:00Z",
    )
    evidence = upload_and_verify_evidence(record["id"], seed=101)
    questionnaire = make_submitted_cdp(cycle["id"])
    inventory = recalc_inventory(cycle["id"])
    cycle = drive_cycle_to_locked(cycle["id"])
    cycle = transition_cycle(cycle["id"], "UNDER_ASSURANCE")
    cycle = transition_cycle(
        cycle["id"], "ASSURED",
        headers=make_assurer_headers(ASSURER_ID),
        assurance_statement="Limited assurance, ISAE 3410",
    )
    cycle = transition_cycle(cycle["id"], "DISCLOSED")
    return {
        "cycle": cycle, "site": site, "factor": factor, "record": record,
        "evidence": evidence, "questionnaire": questionnaire,
        "inventory": inventory,
    }
