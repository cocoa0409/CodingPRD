"""Composable setup chains, expressed only through the PRD's own endpoints.

The harness restarts the API server before every individual test, so each test
begins against an empty database: there is no seeded facility, no clock setting
and no published disclosure to inherit.  Every helper here therefore rebuilds
whatever state it needs from scratch through declared routes and returns plain
dictionaries, so a test can pin the exact figures each operation produced.

``get_success_data`` is used inside these helpers rather than ``validate_success``
because a setup step's job is to hand back the created row; the envelope itself
is asserted by the tests that are actually about the envelope.
"""

from prd_bench_local_runner.testing import get_success_data

import pytest

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    canonical_ancillary_line_payloads,
    make_adjudicate_payload,
    make_ambulance_mou_payload,
    make_ancillary_order_payload,
    make_ancillary_resolve_payload,
    make_award_payload,
    make_begin_mse_payload,
    make_claim_payload,
    make_complete_mse_payload,
    make_disclosure_decision_payload,
    make_discharge_payload,
    make_dispute_case_payload,
    make_encounter_payload,
    make_facility_payload,
    make_facility_update_payload,
    make_initiate_idr_payload,
    make_observation_payload,
    make_offer_payload,
    make_payer_contract_payload,
    make_physician_shift_payload,
    make_publish_payload,
    make_signage_attestation_payload,
    make_template_payload,
    make_transfer_agreement_payload,
    make_transfer_order_payload,
    make_volume_forecast_payload,
    make_withdraw_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
SECOND_ADMIN = TEST_USERS["second_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_OFFICER = TEST_USERS["second_compliance_officer_headers"]
CLERK = TEST_USERS["clerk_headers"]
SECOND_CLERK = TEST_USERS["second_clerk_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
PAYER = TEST_USERS["payer_headers"]
IDRE = TEST_USERS["idre_headers"]

# PRD 3.7: a facility licensed for plain-film and CT imaging plus a red-top and a
# troponin, which is narrow enough for a licensed-scope breach to be reachable.
NARROW_IMAGING_SCOPE = ["XRAY", "CT"]
NARROW_LAB_SCOPE = ["CBC", "TROPONIN"]


# ----------------------------------------------------------------- clock ------
def set_clock(instant: str, headers: dict = ADMIN) -> str:
    """Pin the logical clock that stamps every timestamp and drives every window."""
    get_success_data(api_client.set_clock(instant, headers))
    return instant


def read_clock(headers: dict = ADMIN) -> dict:
    return get_success_data(api_client.get_clock(headers))


# -------------------------------------------------------------- facility ------
def create_facility(headers: dict = ADMIN, **overrides) -> dict:
    """Register a freestanding emergency department and hand back the row."""
    return get_success_data(
        api_client.create_facility(make_facility_payload(**overrides), headers)
    )


def read_facility(facility_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api_client.get_facility(facility_id, headers))


def patch_facility(
    facility_id: str, expected_version: int, headers: dict = ADMIN, **overrides
) -> dict:
    return get_success_data(
        api_client.update_facility(
            facility_id,
            make_facility_update_payload(expected_version, **overrides),
            headers,
        )
    )


def draft_template(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_disclosure_template(
            facility_id, make_template_payload(**overrides), headers
        )
    )


def publish_template(
    template_id: str, expected_facility_version: int, headers: dict = ADMIN
) -> dict:
    return get_success_data(
        api_client.publish_disclosure_template(
            template_id, make_publish_payload(expected_facility_version), headers
        )
    )


def attest_signage(facility_id: str, headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_signage_attestation(
            facility_id, make_signage_attestation_payload(**overrides), headers
        )
    )


def ledger_entries(facility_id: str, headers: dict = OFFICER, params: dict = None) -> list:
    """The facility's append-only compliance ledger, oldest entry first."""
    return get_success_data(
        api_client.list_compliance_ledger_entries(facility_id, headers, params=params)
    )


def coverage_summary(facility_id: str, headers: dict = ADMIN, params: dict = None) -> dict:
    return get_success_data(
        api_client.get_coverage_summary(facility_id, headers, params=params)
    )


def open_facility(
    *,
    clock: str = DEFAULT_CLOCK,
    facility_overrides: dict = None,
    template_overrides: dict = None,
    publisher_headers: dict = ADMIN,
    attester_headers: dict = OFFICER,
) -> dict:
    """Drive a brand-new facility all the way to an ``OPEN`` compliance posture.

    A new facility has no published disclosure and a ``PENDING`` signage
    attestation, so its very first posture computation is ``RESTRICTED``.  The
    two things that clear it are a published template and a filed attestation,
    and both are done here — by two *different* operators, because a signage
    attestation may not be filed by the operator who published the template.
    """
    set_clock(clock, publisher_headers)
    facility = create_facility(publisher_headers, **(facility_overrides or {}))
    template = draft_template(
        facility["id"], publisher_headers, **(template_overrides or {})
    )
    published = publish_template(template["id"], facility["version"], publisher_headers)
    after_publish = read_facility(facility["id"], publisher_headers)
    attested = attest_signage(facility["id"], attester_headers)
    return {
        "facility_id": facility["id"],
        "facility": attested,
        "created_facility": facility,
        "facility_after_publish": after_publish,
        "template_id": template["id"],
        "template": published,
        "version": attested["version"],
        "clock": clock,
    }


def open_facility_with_narrow_scope(**kwargs) -> dict:
    """An ``OPEN`` facility whose licensed scope omits MRI, chemistry and cultures."""
    overrides = dict(kwargs.pop("facility_overrides", None) or {})
    overrides.setdefault("imaging_scope", NARROW_IMAGING_SCOPE)
    overrides.setdefault("lab_scope", NARROW_LAB_SCOPE)
    return open_facility(facility_overrides=overrides, **kwargs)


def suspend_facility(facility_id: str, expected_version: int, headers: dict = ADMIN) -> dict:
    """Downgrade the licence, which drives the posture straight to ``SUSPENDED``."""
    return patch_facility(
        facility_id, expected_version, headers, license_status="SUSPENDED"
    )


def restore_licence(facility_id: str, expected_version: int, headers: dict = ADMIN) -> dict:
    return patch_facility(facility_id, expected_version, headers, license_status="ACTIVE")


# -------------------------------------------------------- payer contract ------
def create_payer_contract(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_payer_contract(
            facility_id, make_payer_contract_payload(**overrides), headers
        )
    )


def protected_nsa_contract(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    """An out-of-network contract under the federal regime only."""
    overrides.setdefault("network_status", "OUT_OF_NETWORK")
    overrides.setdefault("state_protection_regime", "FEDERAL_NSA_ONLY")
    return create_payer_contract(facility_id, headers, **overrides)


def protected_state_contract(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    """An out-of-network contract under a state freestanding-ED protection."""
    overrides.setdefault("network_status", "OUT_OF_NETWORK")
    overrides.setdefault("state_protection_regime", "STATE_PROTECTED_FSED")
    return create_payer_contract(facility_id, headers, **overrides)


def unprotected_contract(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    """An out-of-network contract under a state exemption, so balance billing is open."""
    overrides.setdefault("network_status", "OUT_OF_NETWORK")
    overrides.setdefault("state_protection_regime", "STATE_EXEMPT_FSED")
    return create_payer_contract(facility_id, headers, **overrides)


# ---------------------------------------------------- coverage and volume -----
def create_volume_forecast(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_volume_forecast(
            facility_id, make_volume_forecast_payload(**overrides), headers
        )
    )


def create_physician_shift(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_physician_shift(
            facility_id, make_physician_shift_payload(**overrides), headers
        )
    )


def list_physician_shifts(facility_id: str, headers: dict = ADMIN, params: dict = None):
    return get_success_data(
        api_client.list_physician_shifts(facility_id, headers, params=params)
    )


# --------------------------------------------- transfer-side arrangements -----
def create_transfer_agreement(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_transfer_agreement(
            facility_id, make_transfer_agreement_payload(**overrides), headers
        )
    )


def create_ambulance_mou(facility_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_ambulance_mou(
            facility_id, make_ambulance_mou_payload(**overrides), headers
        )
    )


def read_ambulance_mou(mou_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api_client.get_ambulance_mou(mou_id, headers))


# ------------------------------------------------------------- encounter ------
def register_encounter(facility_id: str, headers: dict = CLERK, **overrides) -> dict:
    return get_success_data(
        api_client.register_encounter(
            facility_id, make_encounter_payload(**overrides), headers
        )
    )


def read_encounter(encounter_id: str, headers: dict = PHYSICIAN) -> dict:
    return get_success_data(api_client.get_encounter(encounter_id, headers))


def record_decision(
    encounter_id: str, decision: str = "ACKNOWLEDGED", headers: dict = CLERK, **overrides
) -> dict:
    return get_success_data(
        api_client.record_disclosure_decision(
            encounter_id, make_disclosure_decision_payload(decision, **overrides), headers
        )
    )


def acknowledge_disclosure(encounter_id: str, headers: dict = CLERK) -> dict:
    return record_decision(encounter_id, "ACKNOWLEDGED", headers)


def refuse_disclosure(encounter_id: str, headers: dict = CLERK) -> dict:
    return record_decision(encounter_id, "REFUSED", headers)


def begin_mse(encounter_id: str, headers: dict = PHYSICIAN, **overrides) -> dict:
    return get_success_data(
        api_client.begin_mse(encounter_id, make_begin_mse_payload(**overrides), headers)
    )


def complete_mse(
    encounter_id: str, stabilization_status: str = "STABLE", headers: dict = PHYSICIAN
) -> dict:
    return get_success_data(
        api_client.complete_mse(
            encounter_id, make_complete_mse_payload(stabilization_status), headers
        )
    )


def screen_encounter(
    encounter_id: str, stabilization_status: str = "STABLE", headers: dict = PHYSICIAN
) -> dict:
    """Begin and complete the screening, leaving the encounter in ``MSE_COMPLETE``."""
    begin_mse(encounter_id, headers)
    return complete_mse(encounter_id, stabilization_status, headers)


def admit_to_observation(encounter_id: str, headers: dict = PHYSICIAN, **overrides) -> dict:
    return get_success_data(
        api_client.admit_to_observation(
            encounter_id, make_observation_payload(**overrides), headers
        )
    )


def discharge(encounter_id: str, headers: dict = PHYSICIAN, **overrides) -> dict:
    return get_success_data(
        api_client.discharge_encounter(
            encounter_id, make_discharge_payload(**overrides), headers
        )
    )


def order_ancillary(
    encounter_id: str,
    category: str = "IMAGING",
    code: str = "CT",
    quantity: int = 1,
    headers: dict = PHYSICIAN,
) -> dict:
    return get_success_data(
        api_client.create_ancillary_order(
            encounter_id,
            make_ancillary_order_payload(category, code, quantity),
            headers,
        )
    )


def resolve_ancillary(
    order_id: str, outcome: str = "RESULTED", headers: dict = PHYSICIAN
) -> dict:
    return get_success_data(
        api_client.resolve_ancillary_order(
            order_id, make_ancillary_resolve_payload(outcome), headers
        )
    )


def add_resulted_line(
    encounter_id: str,
    category: str,
    code: str,
    quantity: int = 1,
    headers: dict = PHYSICIAN,
) -> dict:
    """Order a line and result it, which is what makes it billable."""
    order = order_ancillary(encounter_id, category, code, quantity, headers)
    return resolve_ancillary(order["id"], "RESULTED", headers)


def add_canonical_resulted_lines(encounter_id: str, headers: dict = PHYSICIAN) -> list:
    """CT x2, TROPONIN x2 and ANALGESIC x1, all resulted, in creation order."""
    return [
        add_resulted_line(
            encounter_id, line["category"], line["code"], line["quantity"], headers
        )
        for line in canonical_ancillary_line_payloads()
    ]


# -------------------------------------------------------- transfer orders -----
def create_transfer_order(
    encounter_id: str,
    transfer_agreement_id: str,
    ambulance_mou_id: str,
    expected_encounter_version: int,
    headers: dict = PHYSICIAN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_transfer_order(
            encounter_id,
            make_transfer_order_payload(
                transfer_agreement_id,
                ambulance_mou_id,
                expected_encounter_version,
                **overrides,
            ),
            headers,
        )
    )


def transfer_ready_encounter(
    *,
    clock: str = DEFAULT_CLOCK,
    acuity_level: int = 3,
    service_line: str = "CARDIAC",
    stabilization_status: str = "STABLE",
    facility_overrides: dict = None,
    agreement_overrides: dict = None,
    mou_overrides: dict = None,
    acknowledge: bool = True,
) -> dict:
    """An ``OPEN`` facility, a live agreement and memorandum, and a screened patient.

    The encounter's ``version`` is re-read after screening, because a transfer
    order carries the encounter-level concurrency token and screening moved it.
    """
    context = open_facility(clock=clock, facility_overrides=facility_overrides)
    agreement_kwargs = dict(agreement_overrides or {})
    agreement_kwargs.setdefault("service_line", service_line)
    agreement = create_transfer_agreement(context["facility_id"], **agreement_kwargs)
    mou = create_ambulance_mou(context["facility_id"], **(mou_overrides or {}))
    encounter = register_encounter(
        context["facility_id"],
        acuity_level=acuity_level,
        presenting_service_line=service_line,
    )
    if acknowledge:
        acknowledge_disclosure(encounter["id"])
    screened = screen_encounter(encounter["id"], stabilization_status)
    context.update(
        {
            "agreement": agreement,
            "agreement_id": agreement["id"],
            "mou": mou,
            "mou_id": mou["id"],
            "encounter": screened,
            "encounter_id": screened["id"],
            "encounter_version": screened["version"],
        }
    )
    return context


# ---------------------------------------------------- claims and disputes -----
def create_claim(
    encounter_id: str, payer_contract_id: str, headers: dict = OFFICER, **overrides
) -> dict:
    return get_success_data(
        api_client.create_claim(
            encounter_id, make_claim_payload(payer_contract_id, **overrides), headers
        )
    )


def adjudicate_claim(claim_id: str, headers: dict = PAYER) -> dict:
    return get_success_data(
        api_client.adjudicate_claim(claim_id, make_adjudicate_payload(), headers)
    )


def read_claim(claim_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers))


def closed_encounter_with_canonical_lines(
    *,
    clock: str = DEFAULT_CLOCK,
    acuity_level: int = 3,
    decision: str = "ACKNOWLEDGED",
    facility_overrides: dict = None,
) -> dict:
    """A discharged patient carrying the canonical resulted ancillary bundle.

    Only a closed encounter can be billed, so every settlement chain starts
    here: register, close out the disclosure conversation, screen, result the
    three ancillary lines and discharge a stable patient.
    """
    context = open_facility(clock=clock, facility_overrides=facility_overrides)
    encounter = register_encounter(context["facility_id"], acuity_level=acuity_level)
    if decision is not None:
        record_decision(
            encounter["id"],
            decision,
            SECOND_CLERK if decision == "EMERGENT_WAIVER" else CLERK,
        )
    screen_encounter(encounter["id"], "STABLE")
    lines = add_canonical_resulted_lines(encounter["id"])
    discharged = discharge(encounter["id"])
    context.update(
        {
            "encounter": discharged,
            "encounter_id": discharged["id"],
            "ancillary_orders": lines,
        }
    )
    return context


def adjudicated_claim(
    *,
    contract_builder=protected_nsa_contract,
    contract_overrides: dict = None,
    clock: str = DEFAULT_CLOCK,
    acuity_level: int = 3,
    decision: str = "ACKNOWLEDGED",
) -> dict:
    """The canonical billed bundle, opened as a claim and adjudicated."""
    context = closed_encounter_with_canonical_lines(
        clock=clock, acuity_level=acuity_level, decision=decision
    )
    contract = contract_builder(context["facility_id"], **(contract_overrides or {}))
    claim = create_claim(context["encounter_id"], contract["id"])
    adjudicated = adjudicate_claim(claim["id"])
    context.update(
        {
            "contract": contract,
            "contract_id": contract["id"],
            "claim": adjudicated,
            "claim_id": adjudicated["id"],
            "draft_claim": claim,
        }
    )
    return context


def create_dispute_case(claim_id: str, headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_dispute_case(
            claim_id, make_dispute_case_payload(**overrides), headers
        )
    )


def submit_offer(case_id: str, offer_cents: int, headers: dict = OFFICER) -> dict:
    return get_success_data(
        api_client.submit_offer(case_id, make_offer_payload(offer_cents), headers)
    )


def negotiate_rounds(case_id: str, rounds) -> dict:
    """Walk complete negotiation rounds, each closed by the payer's counteroffer.

    ``rounds`` is a sequence of ``(facility_offer_cents, payer_counteroffer_cents)``
    pairs; a round is only counted once the payer has answered.
    """
    case = None
    for facility_offer, payer_counteroffer in rounds:
        submit_offer(case_id, facility_offer, OFFICER)
        case = submit_offer(case_id, payer_counteroffer, PAYER)
    return case


def exhausted_dispute_case(
    *,
    contract_builder=protected_nsa_contract,
    contract_overrides: dict = None,
    rounds=((240000, 200000), (240000, 200000), (240000, 200000)),
    acuity_level: int = 3,
) -> dict:
    """An adjudicated claim whose dispute case has walked the three-round bound."""
    context = adjudicated_claim(
        contract_builder=contract_builder,
        contract_overrides=contract_overrides,
        acuity_level=acuity_level,
    )
    case = create_dispute_case(context["claim_id"])
    negotiated = negotiate_rounds(case["id"], rounds) or case
    context.update(
        {"case": negotiated, "case_id": case["id"], "opened_case": case}
    )
    return context


def initiate_idr(case_id: str, headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.initiate_idr(case_id, make_initiate_idr_payload(**overrides), headers)
    )


def award_dispute(case_id: str, award_cents: int, headers: dict = IDRE) -> dict:
    return get_success_data(
        api_client.award_dispute(case_id, make_award_payload(award_cents), headers)
    )


def withdraw_award(case_id: str, headers: dict = IDRE, **overrides) -> dict:
    return get_success_data(
        api_client.withdraw_award(case_id, make_withdraw_payload(**overrides), headers)
    )


def idr_initiated_case(**kwargs) -> dict:
    """An exhausted negotiation escalated to a certified dispute-resolution entity."""
    context = exhausted_dispute_case(**kwargs)
    context["case"] = initiate_idr(context["case_id"])
    return context


# ------------------------------------------------------ defect accumulation ---
def accumulate_disclosure_refusals(facility_id: str, count: int) -> list:
    """Register ``count`` patients and record a refusal for each one.

    A refusal is a counted compliance defect, so this is the cheapest way to
    walk the facility's ``open_compliance_defect_count`` up to a threshold.
    """
    encounters = []
    for index in range(count):
        encounter = register_encounter(
            facility_id, patient_reference=f"PT-REFUSE-{index + 1}"
        )
        encounters.append(refuse_disclosure(encounter["id"]))
    return encounters


# ------------------------------------------------------------- pytest tier ----
@pytest.fixture
def default_clock():
    """The working instant every deterministic chain is pinned to."""
    return set_clock(DEFAULT_CLOCK)


@pytest.fixture
def bare_facility(default_clock):
    """A freshly registered facility: no template, ``PENDING`` signage, no clock drift."""
    return create_facility()


@pytest.fixture
def open_facility_context():
    """A facility driven to ``OPEN`` with a published template and filed signage."""
    return open_facility()


@pytest.fixture
def narrow_scope_facility_context():
    """An ``OPEN`` facility whose licensed scope is deliberately narrow."""
    return open_facility_with_narrow_scope()


@pytest.fixture
def transfer_context():
    """An ``OPEN`` facility, a live agreement and memorandum, and a screened patient."""
    return transfer_ready_encounter()


@pytest.fixture
def adjudicated_claim_context():
    """The canonical billed bundle, adjudicated under the federal protected variant."""
    return adjudicated_claim()


CANONICAL_CONTRACT_WINDOW = (
    TEST_DEFAULTS["CONTRACT_START"],
    TEST_DEFAULTS["CONTRACT_END"],
)
