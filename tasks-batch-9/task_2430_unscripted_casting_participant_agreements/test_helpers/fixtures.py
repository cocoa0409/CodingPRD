"""Composite setup helpers.

These are plain functions (not pytest fixtures) that build the multi-step
states the tests need: a production, a published call, a fully cleared
applicant, a drafted / sent / executed agreement, an active duty-of-care
protocol, a scheduled or rolling shoot block, a filed complaint, and the minor
pathway with its protection packet and trust deposit.

Each helper returns the created record (or a dict of records) so that a test can
read a version counter or an id straight off it.  They use ``get_success_data``
deliberately: a setup step that trips a validation should surface as a KeyError
or an assertion in the test body, not as a confusing status-code mismatch inside
the helper.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    counter_offer_payload,
    create_agreement_payload,
    create_applicant_payload,
    create_casting_call_payload,
    create_complaint_payload,
    create_docusoap_production_payload,
    create_location_payload,
    create_minor_applicant_payload,
    create_minor_protection_payload,
    create_open_call_payload,
    create_production_payload,
    create_release_payload,
    create_screening_item_payload,
    create_shoot_block_payload,
    create_welfare_protocol_payload,
    resolve_payload,
    revise_payload,
    route_payload,
    trust_deposit_payload,
    void_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]
WO2 = TEST_USERS["welfare_officer_2_headers"]

# The full required screening set for a production that requires a psych
# evaluation.  PSYCH_EVAL is recorded by a second compliance officer so that the
# four-eyes screening rule is satisfied.
FULL_PASS_SCREENING = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("MEDICAL_EXAM", "PASS", 0, CO1),
    ("PSYCH_EVAL", "PASS", 0, CO2),
)

# The required set where no psych evaluation is demanded.
NO_PSYCH_SCREENING = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("MEDICAL_EXAM", "PASS", 0, CO1),
)


# ---------------------------------------------------------------- clock


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock; administrative control, ProductionAdmin only."""
    response = api_client.set_logical_clock(to_iso8601, PA)
    assert response.status_code == 200, (
        f"could not move the logical clock to {to_iso8601}: {response.text}"
    )
    return response.json()


# ------------------------------------------------------- tier 1: single rows


def setup_production(headers=PA, **overrides) -> dict:
    """A COMPETITION_HIGH_STRESS / CA production."""
    return get_success_data(
        api_client.create_production(create_production_payload(**overrides), headers)
    )


def setup_docusoap_production(headers=PA, **overrides) -> dict:
    """A DOCUSOAP production, which opens at the STANDARD duty-of-care tier."""
    return get_success_data(
        api_client.create_production(
            create_docusoap_production_payload(**overrides), headers
        )
    )


def setup_location(headers=PA, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(create_location_payload(**overrides), headers)
    )


def setup_casting_call(production_id: str, headers=CD, **overrides) -> dict:
    """A DRAFT casting call."""
    return get_success_data(
        api_client.create_casting_call(
            create_casting_call_payload(production_id, **overrides), headers
        )
    )


def setup_published_casting_call(production_id: str, headers=CD, **overrides) -> dict:
    call = setup_casting_call(production_id, headers=headers, **overrides)
    return get_success_data(api_client.publish_casting_call(call["id"], headers))


def setup_open_call(
    production_id: str, venue_location_id: str, headers=CD, publish: bool = True, **overrides
) -> dict:
    call = get_success_data(
        api_client.create_casting_call(
            create_open_call_payload(production_id, venue_location_id, **overrides), headers
        )
    )
    if publish:
        call = get_success_data(api_client.publish_casting_call(call["id"], headers))
    return call


def setup_applicant(casting_call_id: str, headers=CD, **overrides) -> dict:
    return get_success_data(
        api_client.create_applicant(
            create_applicant_payload(casting_call_id, **overrides), headers
        )
    )


def setup_minor_applicant(casting_call_id: str, headers=CD, **overrides) -> dict:
    return get_success_data(
        api_client.create_applicant(
            create_minor_applicant_payload(casting_call_id, **overrides), headers
        )
    )


# ---------------------------------------------- tier 2: applicant screening


def record_screening_items(applicant_id: str, items=FULL_PASS_SCREENING) -> list:
    """Create one screening item per tuple ``(kind, outcome, severity, headers)``."""
    created = []
    for kind, outcome, severity, headers in items:
        if outcome is None:
            payload = create_screening_item_payload(kind, outcome=None)
        else:
            payload = create_screening_item_payload(
                kind, outcome=outcome, severity_flags=severity
            )
        created.append(
            get_success_data(
                api_client.create_screening_item(applicant_id, payload, headers)
            )
        )
    return created


def setup_cleared_applicant(
    casting_call_id: str, items=FULL_PASS_SCREENING, minor: bool = False, **overrides
) -> dict:
    """An applicant with every required screening item recorded PASS."""
    maker = setup_minor_applicant if minor else setup_applicant
    applicant = maker(casting_call_id, **overrides)
    record_screening_items(applicant["id"], items)
    return get_applicant(applicant["id"])


def get_applicant(applicant_id: str, headers=BA1) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, headers))


def get_applicant_version(applicant_id: str, headers=BA1) -> int:
    return get_applicant(applicant_id, headers)["version"]


def get_production(production_id: str, headers=PA) -> dict:
    return get_success_data(api_client.get_production(production_id, headers))


def get_agreement(agreement_id: str, headers=BA1) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, headers))


def get_shoot_block(block_id: str, headers=PA) -> dict:
    return get_success_data(api_client.get_shoot_block(block_id, headers))


# ----------------------------------------- tier 3: production + applicant set


def setup_production_with_cleared_applicant(
    production_overrides=None,
    call_overrides=None,
    applicant_overrides=None,
    items=FULL_PASS_SCREENING,
    docusoap: bool = False,
) -> dict:
    """Production -> published call -> fully cleared adult applicant."""
    maker = setup_docusoap_production if docusoap else setup_production
    production = maker(**(production_overrides or {}))
    call = setup_published_casting_call(production["id"], **(call_overrides or {}))
    applicant = setup_cleared_applicant(
        call["id"], items=items, **(applicant_overrides or {})
    )
    return {"production": production, "casting_call": call, "applicant": applicant}


# --------------------------------------------------- tier 3: agreement chain


def setup_drafted_agreement(
    applicant_id: str, production_id: str, headers=BA1, **overrides
) -> dict:
    """A DRAFTED agreement, reading the applicant's current version first."""
    version = get_applicant_version(applicant_id)
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(applicant_id, production_id, version, **overrides),
            headers,
        )
    )


def setup_sent_agreement(
    applicant_id: str, production_id: str, headers=BA1, **overrides
) -> dict:
    agreement = setup_drafted_agreement(
        applicant_id, production_id, headers=headers, **overrides
    )
    return get_success_data(api_client.send_agreement(agreement["id"], headers))


def setup_executed_agreement(
    applicant_id: str,
    production_id: str,
    proposer_headers=BA1,
    executor_headers=BA2,
    **overrides,
) -> dict:
    """DRAFTED -> SENT -> EXECUTED, with the two four-eyes identities distinct."""
    agreement = setup_sent_agreement(
        applicant_id, production_id, headers=proposer_headers, **overrides
    )
    return get_success_data(
        api_client.execute_agreement(agreement["id"], executor_headers)
    )


def setup_full_executed_agreement(
    production_overrides=None,
    call_overrides=None,
    applicant_overrides=None,
    agreement_overrides=None,
    items=FULL_PASS_SCREENING,
    docusoap: bool = False,
) -> dict:
    """The whole happy path from an empty database to one EXECUTED agreement."""
    context = setup_production_with_cleared_applicant(
        production_overrides=production_overrides,
        call_overrides=call_overrides,
        applicant_overrides=applicant_overrides,
        items=items,
        docusoap=docusoap,
    )
    context["agreement"] = setup_executed_agreement(
        context["applicant"]["id"],
        context["production"]["id"],
        **(agreement_overrides or {}),
    )
    return context


def setup_countered_agreement(
    applicant_id: str, production_id: str, **overrides
) -> dict:
    """DRAFTED -> SENT -> COUNTERED, the counter coming from the participant."""
    agreement = setup_sent_agreement(applicant_id, production_id, **overrides)
    return get_success_data(
        api_client.counter_offer_agreement(
            agreement["id"],
            counter_offer_payload(agreement["version"]),
            make_applicant_headers(applicant_id),
        )
    )


def setup_revised_agreement(applicant_id: str, production_id: str, **overrides) -> dict:
    """One full negotiation cycle: SENT -> COUNTERED -> REVISED."""
    agreement = setup_countered_agreement(applicant_id, production_id, **overrides)
    return get_success_data(
        api_client.revise_agreement(agreement["id"], revise_payload(), BA1)
    )


def void_agreement(agreement_id: str, void_reason: str = "BUSINESS_AFFAIRS_VOID", headers=BA2) -> dict:
    return get_success_data(
        api_client.void_agreement(agreement_id, void_payload(void_reason), headers)
    )


# ------------------------------------------------- tier 3: welfare protocols


def setup_planned_welfare_protocol(
    production_id: str, kind: str = "DUTY_OF_CARE_OFFICER", headers=WO1, **overrides
) -> dict:
    return get_success_data(
        api_client.plan_welfare_protocol(
            production_id, create_welfare_protocol_payload(kind, **overrides), headers
        )
    )


def setup_active_welfare_protocol(
    production_id: str, kind: str = "DUTY_OF_CARE_OFFICER", headers=WO1, **overrides
) -> dict:
    protocol = setup_planned_welfare_protocol(
        production_id, kind=kind, headers=headers, **overrides
    )
    return get_success_data(
        api_client.activate_welfare_protocol(protocol["id"], headers)
    )


# ----------------------------------------------- tier 3: minor protections


def setup_minor_protection(applicant_id: str, headers=CO1, **overrides) -> dict:
    """Filing a packet is a ComplianceOfficer act."""
    return get_success_data(
        api_client.create_minor_protection(
            applicant_id, create_minor_protection_payload(**overrides), headers
        )
    )


def setup_minor_with_executed_agreement(
    production_overrides=None,
    call_overrides=None,
    applicant_overrides=None,
    protection_overrides=None,
    agreement_overrides=None,
    items=FULL_PASS_SCREENING,
) -> dict:
    """Minor applicant -> complete protection packet -> EXECUTED agreement."""
    production = setup_production(**(production_overrides or {"minor_participant_cap": 2}))
    call_kwargs = {"min_age": 13, "max_age": 60}
    call_kwargs.update(call_overrides or {})
    call = setup_published_casting_call(production["id"], **call_kwargs)
    applicant = setup_cleared_applicant(
        call["id"], items=items, minor=True, **(applicant_overrides or {})
    )
    protection = setup_minor_protection(
        applicant["id"], **(protection_overrides or {})
    )
    agreement = setup_executed_agreement(
        applicant["id"], production["id"], **(agreement_overrides or {})
    )
    return {
        "production": production,
        "casting_call": call,
        "applicant": applicant,
        "minor_protection": protection,
        "agreement": agreement,
    }


def setup_trust_deposit(protection_id: str, installment_count: int, headers=BA1) -> dict:
    """Depositing the blocked-trust share is a BusinessAffairs act."""
    return get_success_data(
        api_client.create_trust_deposit(
            protection_id, trust_deposit_payload(installment_count), headers
        )
    )


# -------------------------------------------------- tier 4: shoot blocks


def setup_shoot_block(production_id: str, location_id: str, headers=PA, **overrides) -> dict:
    return get_success_data(
        api_client.create_shoot_block(
            create_shoot_block_payload(production_id, location_id, **overrides), headers
        )
    )


def setup_rolling_shoot_block(
    production_id: str, location_id: str, headers=PA, **overrides
) -> dict:
    """A block that has been rolled; requires active duty-of-care coverage."""
    block = setup_shoot_block(production_id, location_id, headers=headers, **overrides)
    return get_success_data(api_client.roll_shoot_block(block["id"], headers))


def setup_block_ready_to_roll(
    production_overrides=None, location_overrides=None, block_overrides=None
) -> dict:
    """Production with active duty-of-care coverage plus one SCHEDULED block."""
    production = setup_production(**(production_overrides or {}))
    protocol = setup_active_welfare_protocol(production["id"])
    location = setup_location(**(location_overrides or {}))
    block = setup_shoot_block(
        production["id"], location["id"], **(block_overrides or {})
    )
    return {
        "production": production,
        "welfare_protocol": protocol,
        "location": location,
        "shoot_block": block,
    }


def collect_release(block_id: str, headers=PA, **overrides) -> dict:
    return get_success_data(
        api_client.collect_release(block_id, create_release_payload(**overrides), headers)
    )


# ------------------------------------------------ tier 5: complaint chain


def setup_complaint(agreement_id: str, applicant_id: str, **overrides) -> dict:
    """A complaint filed by the participant against their own agreement."""
    return get_success_data(
        api_client.file_complaint(
            agreement_id,
            create_complaint_payload(**overrides),
            make_applicant_headers(applicant_id),
        )
    )


def setup_triaged_complaint(
    agreement_id: str, applicant_id: str, headers=WO1, **overrides
) -> dict:
    complaint = setup_complaint(agreement_id, applicant_id, **overrides)
    return get_success_data(api_client.triage_complaint(complaint["id"], headers))


def setup_routed_complaint(
    agreement_id: str,
    applicant_id: str,
    route: str = "AFTERCARE",
    triage_headers=WO1,
    route_headers=WO2,
    **overrides,
) -> dict:
    complaint = setup_triaged_complaint(
        agreement_id, applicant_id, headers=triage_headers, **overrides
    )
    return get_success_data(
        api_client.route_complaint(complaint["id"], route_payload(route), route_headers)
    )


def resolve_complaint(complaint_id: str, headers=WO1, note: str = None) -> dict:
    payload = resolve_payload() if note is None else resolve_payload(note)
    return get_success_data(api_client.resolve_complaint(complaint_id, payload, headers))


# ---------------------------------------------------- tier 5: epoch sweep


def run_welfare_epoch(production_id: str, headers=PA) -> dict:
    """The epoch sweep is a ProductionAdmin act."""
    return get_success_data(api_client.run_welfare_epoch(production_id, headers))
