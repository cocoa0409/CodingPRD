"""Composite setup helpers.

The harness restarts the API before every test, so each test begins against an
empty database and every precondition below is built from scratch through the
documented endpoints. Helpers return plain dicts of the resources they created,
and always thread the entity-backed identities: a facility acts as itself and a
responsible person acts as itself.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import constants as K
from . import factories as F
from .api_client import CosmeticsApiClient
from .test_users import (
    OFFICER_HEADERS,
    OPERATOR_HEADERS,
    REVIEWER_HEADERS,
    make_facility_registrant_headers,
    make_responsible_person_agent_headers,
)


# ----------------------------------------------------------------------
# Tier 1 — logical clock and establishment state progression
# ----------------------------------------------------------------------
def set_clock(api: CosmeticsApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock, which performs no state transitions of its own."""
    return get_success_data(api.set_clock(current_utc, OPERATOR_HEADERS))


def run_sweep(api: CosmeticsApiClient) -> Dict[str, Any]:
    """Run the compliance-sweep checkpoint and return its counters."""
    return get_success_data(api.run_compliance_sweep(OPERATOR_HEADERS))


def create_draft_facility(api: CosmeticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """A brand-new establishment sitting in DRAFT."""
    return get_success_data(
        api.create_facility(F.facility_payload(**overrides), make_facility_registrant_headers("seed"))
    )


def create_pending_facility(api: CosmeticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """An establishment submitted for agency review."""
    facility = create_draft_facility(api, **overrides)
    registrant = make_facility_registrant_headers(facility["id"])
    return get_success_data(api.submit_registration(facility["id"], registrant))


def create_registered_facility(api: CosmeticsApiClient, **overrides: Any) -> Dict[str, Any]:
    """An approved establishment carrying its INITIAL coverage period."""
    facility = create_pending_facility(api, **overrides)
    return get_success_data(
        api.decide_registration(
            facility["id"], F.registration_decision_payload("APPROVE"), REVIEWER_HEADERS
        )
    )


def create_rejected_facility(api: CosmeticsApiClient, **overrides: Any) -> Dict[str, Any]:
    facility = create_pending_facility(api, **overrides)
    return get_success_data(
        api.decide_registration(
            facility["id"], F.registration_decision_payload("REJECT"), REVIEWER_HEADERS
        )
    )


def read_facility(api: CosmeticsApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_facility(facility_id, make_facility_registrant_headers(facility_id))
    )


def read_listing(api: CosmeticsApiClient, listing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_listing(listing_id, REVIEWER_HEADERS))


def read_responsible_person(api: CosmeticsApiClient, responsible_person_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_responsible_person(responsible_person_id, REVIEWER_HEADERS))


def read_ledger(api: CosmeticsApiClient, facility_id: str,
                params: Optional[Dict] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    query = {"limit": K.MAX_LIMIT}
    if params:
        query.update(params)
    return validate_paginated(api.list_ledger_entries(facility_id, REVIEWER_HEADERS, query))


def ledger_entries(api: CosmeticsApiClient, facility_id: str,
                   entry_type: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if entry_type:
        params["entry_type"] = entry_type
    rows, _ = read_ledger(api, facility_id, params)
    return rows


# ----------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ----------------------------------------------------------------------
def create_responsible_person(api: CosmeticsApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_responsible_person(
            F.responsible_person_payload(**overrides),
            make_responsible_person_agent_headers("seed"),
        )
    )


def create_draft_listing(api: CosmeticsApiClient, facility_id: str,
                         responsible_person_id: str, **overrides: Any) -> Dict[str, Any]:
    agent = make_responsible_person_agent_headers(responsible_person_id)
    return get_success_data(
        api.create_listing(
            F.listing_payload(facility_id, responsible_person_id, **overrides), agent
        )
    )


def registered_facility_with_listing(api: CosmeticsApiClient,
                                     listing_overrides: Optional[Dict[str, Any]] = None,
                                     person_overrides: Optional[Dict[str, Any]] = None,
                                     facility_overrides: Optional[Dict[str, Any]] = None,
                                     ) -> Dict[str, Any]:
    """The standard hierarchy: registered establishment, designee, DRAFT listing.

    Returns a bundle carrying every id plus ready-made headers for the two
    entity-backed roles.
    """
    facility = create_registered_facility(api, **(facility_overrides or {}))
    person = create_responsible_person(api, **(person_overrides or {}))
    listing = create_draft_listing(
        api, facility["id"], person["id"], **(listing_overrides or {})
    )
    return {
        "facility": facility,
        "facility_id": facility["id"],
        "person": person,
        "person_id": person["id"],
        "listing": listing,
        "listing_id": listing["id"],
        "registrant": make_facility_registrant_headers(facility["id"]),
        "agent": make_responsible_person_agent_headers(person["id"]),
    }


# ----------------------------------------------------------------------
# Tier 3 — substantiation and listing lifecycle shortcuts
# ----------------------------------------------------------------------
def open_dossier(api: CosmeticsApiClient, listing_id: str, agent: Dict[str, str],
                 **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.open_substantiation(listing_id, F.substantiation_payload(**overrides), agent)
    )


def attach_items(api: CosmeticsApiClient, substantiation_id: str, agent: Dict[str, str],
                 items: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Attach one evidence item per (evidence_type, reviewer_credential) pair."""
    created = []
    for evidence_type, credential in items:
        created.append(
            get_success_data(
                api.add_review_item(
                    substantiation_id, F.review_item_payload(evidence_type, credential), agent
                )
            )
        )
    return created


def submit_dossier(api: CosmeticsApiClient, substantiation_id: str,
                   agent: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.submit_substantiation(substantiation_id, agent))


def decide_dossier(api: CosmeticsApiClient, substantiation_id: str,
                   review_mode: str = K.REVIEW_MODE_SCREENING,
                   reviewer: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.decide_substantiation_review(
            substantiation_id,
            F.review_decision_payload(review_mode),
            reviewer or REVIEWER_HEADERS,
        )
    )


#: A clinical study by a board-certified toxicologist (40.00) plus an in-vitro
#: item by an ERT (25.00) scores 65.00 under either review mode.
PASSING_EVIDENCE = [
    (K.EVIDENCE_CLINICAL, K.CREDENTIAL_BOARD_CERTIFIED),
    (K.EVIDENCE_IN_VITRO, K.CREDENTIAL_ERT),
]

#: Three read-across items by board-certified toxicologists plus one in-vitro
#: item by a qualified safety assessor: 75.00 screening, 45.00 full.
DIVERGENT_EVIDENCE = [
    (K.EVIDENCE_READ_ACROSS, K.CREDENTIAL_BOARD_CERTIFIED),
    (K.EVIDENCE_READ_ACROSS, K.CREDENTIAL_BOARD_CERTIFIED),
    (K.EVIDENCE_READ_ACROSS, K.CREDENTIAL_BOARD_CERTIFIED),
    (K.EVIDENCE_IN_VITRO, K.CREDENTIAL_QSA),
]


def dossier_at_decision(api: CosmeticsApiClient, listing_id: str, agent: Dict[str, str],
                        items: Optional[List[Tuple[str, str]]] = None,
                        review_mode: str = K.REVIEW_MODE_SCREENING,
                        reviewer: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Open a dossier, attach evidence, submit it and have it scored."""
    dossier = open_dossier(api, listing_id, agent)
    attach_items(api, dossier["id"], agent, items if items is not None else PASSING_EVIDENCE)
    submit_dossier(api, dossier["id"], agent)
    return decide_dossier(api, dossier["id"], review_mode, reviewer)


def substantiate_listing(api: CosmeticsApiClient, bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Take the bundle's listing to safety_status SUBSTANTIATED."""
    return dossier_at_decision(api, bundle["listing_id"], bundle["agent"])


def submit_listing(api: CosmeticsApiClient, bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Substantiate then submit the bundle's listing."""
    substantiate_listing(api, bundle)
    return get_success_data(api.submit_listing(bundle["listing_id"], bundle["agent"]))


def list_the_listing(api: CosmeticsApiClient, bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Carry the bundle's listing all the way to LISTED and marketable."""
    submit_listing(api, bundle)
    return get_success_data(
        api.decide_listing(
            bundle["listing_id"], F.listing_decision_payload("LIST"), REVIEWER_HEADERS
        )
    )


def listed_bundle(api: CosmeticsApiClient,
                  listing_overrides: Optional[Dict[str, Any]] = None,
                  person_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A registered establishment whose single listing has reached LISTED."""
    bundle = registered_facility_with_listing(
        api, listing_overrides=listing_overrides, person_overrides=person_overrides
    )
    bundle["listing"] = list_the_listing(api, bundle)
    return bundle


def add_ingredient(api: CosmeticsApiClient, listing_id: str, agent: Dict[str, str],
                   payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.add_ingredient(listing_id, payload, agent))


# ----------------------------------------------------------------------
# Tier 4 — points accumulation and threshold targeting
# ----------------------------------------------------------------------
def record_serious_event(api: CosmeticsApiClient, listing_id: str, agent: Dict[str, str],
                         received_at: str = K.DEFAULT_CLOCK_UTC,
                         **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_adverse_event(
            listing_id,
            F.adverse_event_payload(received_at, K.SERIOUSNESS_SERIOUS, **overrides),
            agent,
        )
    )


def record_retained_event(api: CosmeticsApiClient, listing_id: str, agent: Dict[str, str],
                          received_at: str = K.DEFAULT_CLOCK_UTC,
                          **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.record_adverse_event(
            listing_id,
            F.adverse_event_payload(received_at, K.SERIOUSNESS_NON_SERIOUS, **overrides),
            agent,
        )
    )


def file_report(api: CosmeticsApiClient, adverse_event_id: str,
                agent: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.file_adverse_event_report(adverse_event_id, agent))


def late_report_at(api: CosmeticsApiClient, listing_id: str, agent: Dict[str, str],
                   received_at: str, filed_at: str) -> Dict[str, Any]:
    """Record a serious event, move the clock to ``filed_at`` and file the report."""
    event = record_serious_event(api, listing_id, agent, received_at)
    set_clock(api, filed_at)
    return file_report(api, event["id"], agent)


def freeze_facility_with_points(api: CosmeticsApiClient, bundle: Dict[str, Any]) -> None:
    """Push the establishment to 30.00 points, forcing posture FROZEN.

    Three consumer-listing reports each ten or more days late score 10.00
    apiece, and 30.00 is at or above the frozen threshold of 25.00.
    """
    for _ in range(3):
        set_clock(api, K.DEFAULT_CLOCK_UTC)
        event = record_serious_event(api, bundle["listing_id"], bundle["agent"],
                                     K.DEFAULT_CLOCK_UTC)
        set_clock(api, "2026-08-31T10:00:00Z")
        file_report(api, event["id"], bundle["agent"])
    set_clock(api, K.DEFAULT_CLOCK_UTC)


def lapse_facility_via_sweep(api: CosmeticsApiClient, clock_after_period_end: str
                             = "2028-08-01T00:00:00Z") -> Dict[str, Any]:
    """Advance past the coverage window and let the sweep lapse the establishment."""
    set_clock(api, clock_after_period_end)
    return run_sweep(api)


# ----------------------------------------------------------------------
# Tier 5 — inspections, recalls, withdrawals and their terminal states
# ----------------------------------------------------------------------
def schedule_inspection(api: CosmeticsApiClient, facility_id: str,
                        window_start: str = "2026-09-01", window_end: str = "2026-09-05",
                        inspection_type: str = K.INSPECTION_TYPE_GMP_ROUTINE
                        ) -> Dict[str, Any]:
    return get_success_data(
        api.schedule_inspection(
            facility_id,
            F.inspection_payload(window_start, window_end, inspection_type),
            REVIEWER_HEADERS,
        )
    )


def issue_observations(api: CosmeticsApiClient, facility_id: str, inspection_id: str,
                       observations: List[Dict[str, str]]) -> Dict[str, Any]:
    return get_success_data(
        api.issue_observations(
            facility_id, inspection_id, F.observations_payload(observations), REVIEWER_HEADERS
        )
    )


def inspection_with_observations(api: CosmeticsApiClient, facility_id: str,
                                 observations: List[Dict[str, str]],
                                 window_start: str = "2026-09-01",
                                 window_end: str = "2026-09-05") -> Dict[str, Any]:
    """Schedule an engagement and issue findings against it in one step."""
    engagement = schedule_inspection(api, facility_id, window_start, window_end)
    return issue_observations(api, facility_id, engagement["id"], observations)


def respond_to_inspection(api: CosmeticsApiClient, facility_id: str, inspection_id: str
                          ) -> Dict[str, Any]:
    return get_success_data(
        api.submit_inspection_response(
            facility_id, inspection_id, F.inspection_response_payload(),
            make_facility_registrant_headers(facility_id),
        )
    )


def open_recall(api: CosmeticsApiClient, listing_id: str,
                initiation_basis: str = K.INITIATION_BASIS_VOLUNTARY,
                hazard_class: str = "CLASS_II",
                officer: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.open_recall_action(
            listing_id,
            F.recall_action_payload(initiation_basis, hazard_class),
            officer or OFFICER_HEADERS,
        )
    )


def recall_with_accepted_plan(api: CosmeticsApiClient, listing_id: str,
                              agent: Dict[str, str],
                              initiation_basis: str = K.INITIATION_BASIS_VOLUNTARY,
                              officer: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Open a recall, submit a plan and have an officer accept it."""
    recall = open_recall(api, listing_id, initiation_basis, officer=officer)
    get_success_data(api.submit_recall_plan(recall["id"], F.recall_plan_payload(), agent))
    return get_success_data(
        api.decide_recall_plan(
            recall["id"], F.plan_decision_payload("ACCEPT"), officer or OFFICER_HEADERS
        )
    )


def open_withdrawal(api: CosmeticsApiClient, recall: Dict[str, Any],
                    actor: Optional[Dict[str, str]] = None,
                    scope_depth: str = K.DEPTH_RETAIL) -> Dict[str, Any]:
    """Open a withdrawal round declaring the recall version just read."""
    return get_success_data(
        api.open_withdrawal(
            recall["id"],
            F.withdrawal_payload(recall["version"], scope_depth),
            actor or OFFICER_HEADERS,
        )
    )


def create_distribution_records(api: CosmeticsApiClient, listing_id: str,
                                agent: Dict[str, str],
                                specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create one shipment record per spec dict of factory overrides."""
    records = []
    for spec in specs:
        records.append(
            get_success_data(
                api.create_distribution_record(
                    listing_id, F.distribution_record_payload(**spec), agent
                )
            )
        )
    return records


def produce_records(api: CosmeticsApiClient, withdrawal_id: str, record_ids: List[str],
                    agent: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api.produce_records(withdrawal_id, F.records_production_payload(record_ids), agent)
    )


def withdrawal_with_produced_records(api: CosmeticsApiClient, bundle: Dict[str, Any],
                                     specs: Optional[List[Dict[str, Any]]] = None,
                                     lot_authorized_units: int = 5000,
                                     officer: Optional[Dict[str, str]] = None
                                     ) -> Dict[str, Any]:
    """A listed product with an executing recall whose records have been produced.

    ``bundle`` must already carry a listing whose ``lot_authorized_units`` is
    large enough for the shipments in ``specs``. Returns the bundle extended
    with the recall, the withdrawal and the distribution records.
    """
    specs = specs if specs is not None else [
        {"lot_code": "LOT-A", "ship_date": "2026-08-02", "delivery_date": "2026-08-04",
         "units_shipped": 1000},
    ]
    records = create_distribution_records(api, bundle["listing_id"], bundle["agent"], specs)
    recall = recall_with_accepted_plan(api, bundle["listing_id"], bundle["agent"],
                                      officer=officer)
    withdrawal = open_withdrawal(api, recall, officer or OFFICER_HEADERS)
    produced = produce_records(api, withdrawal["id"], [r["id"] for r in records],
                               bundle["agent"])
    result = dict(bundle)
    result.update({
        "recall": recall,
        "recall_id": recall["id"],
        "withdrawal": produced,
        "withdrawal_id": withdrawal["id"],
        "records": records,
    })
    return result


def post_recovery(api: CosmeticsApiClient, withdrawal_id: str, record_id: str, units: int,
                  agent: Dict[str, str],
                  entry_kind: str = K.ENTRY_KIND_VERIFIED_RETURN) -> Dict[str, Any]:
    return get_success_data(
        api.post_recovery_entry(
            withdrawal_id,
            F.recovery_entry_payload(record_id, units, entry_kind),
            agent,
        )
    )


def run_effectiveness_check(api: CosmeticsApiClient, withdrawal_id: str,
                            basis: str = K.BASIS_VERIFIED,
                            officer: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.run_effectiveness_check(
            withdrawal_id, F.effectiveness_check_payload(basis), officer or OFFICER_HEADERS
        )
    )


def read_withdrawal(api: CosmeticsApiClient, withdrawal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_withdrawal(withdrawal_id, OFFICER_HEADERS))


def read_recall(api: CosmeticsApiClient, recall_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_recall_action(recall_id, OFFICER_HEADERS))


def read_record(api: CosmeticsApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_distribution_record(record_id, OFFICER_HEADERS))


def read_substantiation(api: CosmeticsApiClient, substantiation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_substantiation(substantiation_id, REVIEWER_HEADERS))


def read_inspection(api: CosmeticsApiClient, facility_id: str, inspection_id: str
                    ) -> Dict[str, Any]:
    rows, _ = validate_paginated(
        api.list_inspections(facility_id, REVIEWER_HEADERS, {"limit": K.MAX_LIMIT})
    )
    for row in rows:
        if row["id"] == inspection_id:
            return row
    raise AssertionError(f"engagement {inspection_id} not found under facility {facility_id}")
