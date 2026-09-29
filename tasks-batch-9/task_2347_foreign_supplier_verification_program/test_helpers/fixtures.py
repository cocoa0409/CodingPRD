"""Precondition builders.

The harness restarts the API before every individual test, so every test starts
against an empty database. Nothing here assumes pre-existing data: each builder
constructs the world it needs from scratch, using only documented endpoints.

Layering
--------
1. Primitive builders -- one call each (``set_clock``, ``create_importer``, ...).
2. Chain builders -- ``base_program`` (importer + two designated qualified
   individuals + approved supplier + food + pair) and its variants.
3. Lifecycle shortcuts -- ``analyzed_program`` (approved hazard analysis),
   ``verified_program`` (verification approval signed), ``entered_program``
   (an accepted entry line).
4. Threshold / accumulation targeting -- ``suspended_program`` drives the
   supplier below the suspension threshold and returns the synthesized
   corrective action.
5. Terminal-state helpers -- ``decide_corrective_action`` and
   ``close_corrective_action``.

Every builder returns plain dictionaries (the ``data`` payload of the response)
so tests can assert on them directly, and the chain builders return a
``SimpleNamespace`` whose attributes are the rows created along the way.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    ENTRY_FILER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_qualified_individual_headers,
)

# ---------------------------------------------------------------------------
# 1. Primitive builders
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Pin the logical clock. Every temporal rule reads this instant."""
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN_HEADERS))


def create_importer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_importer(f.importer_payload(**overrides), COMPLIANCE_OFFICER_HEADERS)
    )


def create_second_importer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_importer(
            f.second_importer_payload(**overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_small_importer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_importer(
            f.small_importer_payload(**overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_qualified_individual(
    api: ApiClient, importer_id: str, designate: bool = True, **overrides: Any
) -> Dict[str, Any]:
    qi = get_success_data(
        api.create_qualified_individual(
            f.qualified_individual_payload(importer_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    if designate:
        qi = designate_qualified_individual(api, qi["id"], "DESIGNATE")
    return qi


def create_second_qualified_individual(
    api: ApiClient, importer_id: str, designate: bool = True, **overrides: Any
) -> Dict[str, Any]:
    qi = get_success_data(
        api.create_qualified_individual(
            f.second_qualified_individual_payload(importer_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    if designate:
        qi = designate_qualified_individual(api, qi["id"], "DESIGNATE")
    return qi


def designate_qualified_individual(
    api: ApiClient, qi_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_designation(
            qi_id, f.designation_payload(action, **overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_supplier(
    api: ApiClient,
    importer_id: str,
    approve_by_qi_id: Optional[str] = None,
    decision: str = "APPROVE",
    **overrides: Any,
) -> Dict[str, Any]:
    supplier = get_success_data(
        api.create_foreign_supplier(
            f.foreign_supplier_payload(importer_id, **overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )
    if approve_by_qi_id is not None:
        supplier = evaluate_supplier(api, supplier["id"], approve_by_qi_id, decision)
    return supplier


def evaluate_supplier(
    api: ApiClient, supplier_id: str, acting_qi_id: str, decision: str = "APPROVE"
) -> Dict[str, Any]:
    return get_success_data(
        api.post_supplier_evaluation(
            supplier_id,
            f.evaluation_payload(decision),
            make_qualified_individual_headers(acting_qi_id),
        )
    )


def set_supplier_compliance_status(
    api: ApiClient, supplier_id: str, status: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.patch_supplier_compliance_status(
            supplier_id,
            f.compliance_status_payload(status, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def create_food(api: ApiClient, importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_food(f.food_payload(importer_id, **overrides), COMPLIANCE_OFFICER_HEADERS)
    )


def create_plain_food(api: ApiClient, importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_food(
            f.plain_food_payload(importer_id, **overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_juice_food(api: ApiClient, importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_food(
            f.juice_food_payload(importer_id, **overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_infant_food(api: ApiClient, importer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_food(
            f.infant_food_payload(importer_id, **overrides), COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_pair(
    api: ApiClient,
    importer_id: str,
    supplier_id: str,
    food_id: str,
    designated_qi_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_supplier_food_pair(
            f.pair_payload(importer_id, supplier_id, food_id, designated_qi_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def get_pair(api: ApiClient, pair_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_supplier_food_pair(pair_id, COMPLIANCE_OFFICER_HEADERS))


def get_importer(api: ApiClient, importer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_importer(importer_id, COMPLIANCE_OFFICER_HEADERS))


def get_supplier(api: ApiClient, supplier_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_foreign_supplier(supplier_id, COMPLIANCE_OFFICER_HEADERS))


def get_analysis(api: ApiClient, analysis_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hazard_analysis(analysis_id, COMPLIANCE_OFFICER_HEADERS))


def get_activity(api: ApiClient, activity_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_verification_activity(activity_id, COMPLIANCE_OFFICER_HEADERS)
    )


def get_record(api: ApiClient, record_id: str, **params: Any) -> Dict[str, Any]:
    return get_success_data(
        api.get_verification_record(record_id, COMPLIANCE_OFFICER_HEADERS, params or None)
    )


def get_corrective_action(api: ApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_corrective_action(action_id, COMPLIANCE_OFFICER_HEADERS))


def get_entry(api: ApiClient, entry_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_entry_submission(entry_id, COMPLIANCE_OFFICER_HEADERS))


def get_records_package(api: ApiClient, importer_id: str, **params: Any) -> Dict[str, Any]:
    return get_success_data(
        api.get_records_package(importer_id, COMPLIANCE_OFFICER_HEADERS, params or None)
    )


def list_corrective_actions(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    body = api.list_corrective_actions(COMPLIANCE_OFFICER_HEADERS, params or None)
    return get_success_data(body)


def create_hazard_analysis(
    api: ApiClient,
    pair_id: str,
    acting_qi_id: str,
    expected_pair_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a hazard analysis, reading the pair's current version when not given."""
    if expected_pair_version is None:
        expected_pair_version = get_pair(api, pair_id)["version"]
    return get_success_data(
        api.create_hazard_analysis(
            f.hazard_analysis_payload(pair_id, expected_pair_version, **overrides),
            make_qualified_individual_headers(acting_qi_id),
        )
    )


def add_hazard(
    api: ApiClient, analysis_id: str, acting_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_hazard(
            analysis_id,
            f.hazard_payload(**overrides),
            make_qualified_individual_headers(acting_qi_id),
        )
    )


def approve_analysis(
    api: ApiClient, analysis_id: str, acting_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_hazard_analysis_approval(
            analysis_id,
            f.hazard_analysis_approval_payload(**overrides),
            make_qualified_individual_headers(acting_qi_id),
        )
    )


def create_activity(
    api: ApiClient,
    pair_id: str,
    proposing_qi_id: str,
    assigned_qi_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_verification_activity(
            f.activity_payload(pair_id, assigned_qi_id, **overrides),
            make_qualified_individual_headers(proposing_qi_id),
        )
    )


def review_activity(
    api: ApiClient,
    activity_id: str,
    reviewing_qi_id: str,
    decision: str = "APPROVE",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_activity_review(
            activity_id,
            f.activity_review_payload(decision, **overrides),
            make_qualified_individual_headers(reviewing_qi_id),
        )
    )


def patch_activity(
    api: ApiClient, activity_id: str, acting_qi_id: str, **payload: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.patch_verification_activity(
            activity_id, payload, make_qualified_individual_headers(acting_qi_id)
        )
    )


def approve_pair_verification(
    api: ApiClient, pair_id: str, designated_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_pair_verification_approval(
            pair_id,
            f.verification_approval_payload(**overrides),
            make_qualified_individual_headers(designated_qi_id),
        )
    )


def claim_exemption(
    api: ApiClient, pair_id: str, exemption_type: str, acting_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_pair_exemption(
            pair_id,
            f.exemption_claim_payload(exemption_type, **overrides),
            make_qualified_individual_headers(acting_qi_id),
        )
    )


def determine_exemption(
    api: ApiClient, pair_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """VERIFY / REJECT / REVOKE the pair's claimed exemption (compliance office)."""
    return get_success_data(
        api.post_pair_exemption(
            pair_id,
            f.exemption_determination_payload(action, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def file_record(
    api: ApiClient, activity_id: str, submitting_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_verification_record(
            f.record_payload(activity_id, **overrides),
            make_qualified_individual_headers(submitting_qi_id),
        )
    )


def attest_record(
    api: ApiClient, record_id: str, attesting_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_record_attestation(
            record_id,
            f.attestation_payload(**overrides),
            make_qualified_individual_headers(attesting_qi_id),
        )
    )


def rescind_record(
    api: ApiClient, record_id: str, acting_qi_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_record_rescission(
            record_id,
            f.rescission_payload(**overrides),
            make_qualified_individual_headers(acting_qi_id),
        )
    )


def file_entry(api: ApiClient, pair_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_entry_submission(
            f.entry_submission_payload(pair_id, **overrides), ENTRY_FILER_HEADERS
        )
    )


def decide_corrective_action(
    api: ApiClient,
    action_id: str,
    decision: str,
    supplier_id: str,
    expected_supplier_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Decide a corrective action, pinning the supplier's current version."""
    if expected_supplier_version is None:
        expected_supplier_version = get_supplier(api, supplier_id)["version"]
    return get_success_data(
        api.post_corrective_action_decision(
            action_id,
            f.corrective_action_decision_payload(
                decision, expected_supplier_version, **overrides
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def close_corrective_action(
    api: ApiClient, action_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.post_corrective_action_closure(
            action_id,
            f.corrective_action_closure_payload(action, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# 2. Chain builders
# ---------------------------------------------------------------------------

CLOCK_BASE = "2026-09-01T00:00:00Z"

# The canonical hazard set on the mango pair.
#   Listeria       BIOLOGICAL 4 x 3, foreign supplier, ready-to-eat -> 13.80
#   Pesticide      CHEMICAL   3 x 2, importer control              ->  4.20
#   Salmonella     BIOLOGICAL 5 x 3, foreign supplier, ready-to-eat -> 17.25
HAZARD_LISTERIA = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Listeria monocytogenes",
    severity=4,
    probability=3,
    control_owner="FOREIGN_SUPPLIER",
)
HAZARD_SALMONELLA = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Salmonella spp.",
    severity=5,
    probability=3,
    control_owner="FOREIGN_SUPPLIER",
)
HAZARD_PESTICIDE = dict(
    hazard_type="CHEMICAL_INCL_RADIOLOGICAL",
    hazard_name="Pesticide residue",
    severity=3,
    probability=2,
    control_owner="IMPORTER",
)

ACTIVITY_ONSITE_AUDIT = dict(
    activity_type="ONSITE_AUDIT",
    frequency_per_year=1,
    justification_text=(
        "Annual onsite audit of the foreign supplier for pathogen control"
    ),
    window_start="2026-09-10T00:00:00Z",
    window_end="2026-09-20T00:00:00Z",
)
ACTIVITY_SAMPLING = dict(
    activity_type="SAMPLING_AND_TESTING",
    frequency_per_year=2,
    justification_text=(
        "Semiannual finished product sampling for Listeria and Salmonella at the "
        "port of entry"
    ),
    window_start="2026-10-01T00:00:00Z",
    window_end="2026-10-15T00:00:00Z",
)
ACTIVITY_RECORDS_REVIEW = dict(
    activity_type="RECORDS_REVIEW",
    frequency_per_year=1,
    justification_text=(
        "Annual review of the supplier sanitation and environmental monitoring records"
    ),
    window_start="2026-09-15T00:00:00Z",
    window_end="2026-09-25T00:00:00Z",
)


def base_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    food_overrides: Optional[Dict[str, Any]] = None,
    evaluate_supplier_first: bool = True,
) -> SimpleNamespace:
    """Importer, two designated qualified individuals, an approved supplier, a
    ready-to-eat food and one pair in its initial state."""
    set_clock(api, clock)
    importer = create_importer(api)
    qi_a = create_qualified_individual(api, importer["id"])
    qi_b = create_second_qualified_individual(api, importer["id"])
    supplier = create_supplier(
        api,
        importer["id"],
        approve_by_qi_id=qi_a["id"] if evaluate_supplier_first else None,
        **(supplier_overrides or {}),
    )
    food = create_food(api, importer["id"], **(food_overrides or {}))
    pair = create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    return SimpleNamespace(
        importer=importer,
        importer_id=importer["id"],
        qi_a=qi_a,
        qi_a_id=qi_a["id"],
        qi_b=qi_b,
        qi_b_id=qi_b["id"],
        supplier=supplier,
        supplier_id=supplier["id"],
        food=food,
        food_id=food["id"],
        pair=pair,
        pair_id=pair["id"],
    )


def single_qi_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    food_overrides: Optional[Dict[str, Any]] = None,
    evaluate_supplier_first: bool = True,
) -> SimpleNamespace:
    """Same as :func:`base_program` but with a single designated individual."""
    set_clock(api, clock)
    importer = create_importer(api)
    qi_a = create_qualified_individual(api, importer["id"])
    supplier = create_supplier(
        api,
        importer["id"],
        approve_by_qi_id=qi_a["id"] if evaluate_supplier_first else None,
        **(supplier_overrides or {}),
    )
    food = create_food(api, importer["id"], **(food_overrides or {}))
    pair = create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    return SimpleNamespace(
        importer=importer,
        importer_id=importer["id"],
        qi_a=qi_a,
        qi_a_id=qi_a["id"],
        supplier=supplier,
        supplier_id=supplier["id"],
        food=food,
        food_id=food["id"],
        pair=pair,
        pair_id=pair["id"],
    )


# ---------------------------------------------------------------------------
# 3. Lifecycle shortcuts
# ---------------------------------------------------------------------------


def analyzed_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    hazards: Optional[List[Dict[str, Any]]] = None,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    food_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """:func:`base_program` plus an APPROVED hazard analysis on the pair.

    ``hazards`` defaults to the two control-bearing hazards (Listeria 13.80 and
    Salmonella 17.25), giving a hazard load of 31.05.
    """
    world = base_program(
        api,
        clock=clock,
        supplier_overrides=supplier_overrides,
        food_overrides=food_overrides,
    )
    analysis = create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    world.hazards = [
        add_hazard(api, analysis["id"], world.qi_a_id, **spec)
        for spec in (hazards if hazards is not None else [HAZARD_LISTERIA, HAZARD_SALMONELLA])
    ]
    world.analysis = approve_analysis(api, analysis["id"], world.qi_a_id)
    world.analysis_id = analysis["id"]
    world.pair = get_pair(api, world.pair_id)
    return world


def planned_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    hazards: Optional[List[Dict[str, Any]]] = None,
    supplier_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """:func:`analyzed_program` plus the three APPROVED verification activities.

    The plan is an onsite audit once a year, sampling and testing twice a year and
    a records review once a year, reviewed and approved by the second individual.
    """
    world = analyzed_program(
        api, clock=clock, hazards=hazards, supplier_overrides=supplier_overrides
    )
    world.activity_onsite = create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_a_id, **ACTIVITY_ONSITE_AUDIT
    )
    world.activity_sampling = create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_b_id, **ACTIVITY_SAMPLING
    )
    world.activity_records = create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_a_id, **ACTIVITY_RECORDS_REVIEW
    )
    for activity in (
        world.activity_onsite,
        world.activity_sampling,
        world.activity_records,
    ):
        review_activity(api, activity["id"], world.qi_b_id, "APPROVE")
    world.pair = get_pair(api, world.pair_id)
    return world


def verified_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    hazards: Optional[List[Dict[str, Any]]] = None,
    supplier_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """:func:`planned_program` with the pair's verification approval signed.

    The pair reaches VERIFICATION_APPROVED and ELIGIBLE with required_coverage
    40.58 and adequacy_score_planned 61.61.
    """
    world = planned_program(
        api, clock=clock, hazards=hazards, supplier_overrides=supplier_overrides
    )
    world.pair = approve_pair_verification(api, world.pair_id, world.qi_a_id)
    return world


def entered_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    hazards: Optional[List[Dict[str, Any]]] = None,
) -> SimpleNamespace:
    """:func:`verified_program` plus one accepted entry line on the pair."""
    world = verified_program(api, clock=clock, hazards=hazards)
    world.entry = file_entry(api, world.pair_id)
    world.entry_id = world.entry["id"]
    return world


def sampling_only_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    frequency_per_year: int = 2,
    hazards: Optional[List[Dict[str, Any]]] = None,
) -> SimpleNamespace:
    """A pair with an APPROVED hazard analysis and one APPROVED sampling activity.

    Used by every record-scoring scenario: the sampling window is
    [2026-10-01, 2026-10-15) and the assignee is the second individual, so the
    first individual may file records and the second may attest them.
    """
    world = analyzed_program(
        api, clock=clock, hazards=hazards if hazards is not None else [HAZARD_LISTERIA]
    )
    spec = dict(ACTIVITY_SAMPLING)
    spec["frequency_per_year"] = frequency_per_year
    world.activity = create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_b_id, **spec
    )
    world.activity_id = world.activity["id"]
    review_activity(api, world.activity_id, world.qi_b_id, "APPROVE")
    world.activity = get_activity(api, world.activity_id)
    world.pair = get_pair(api, world.pair_id)
    return world


def onsite_only_program(
    api: ApiClient,
    clock: str = CLOCK_BASE,
    hazards: Optional[List[Dict[str, Any]]] = None,
) -> SimpleNamespace:
    """A pair with an APPROVED hazard analysis and one APPROVED onsite audit."""
    world = analyzed_program(
        api, clock=clock, hazards=hazards if hazards is not None else [HAZARD_LISTERIA]
    )
    world.activity = create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_a_id, **ACTIVITY_ONSITE_AUDIT
    )
    world.activity_id = world.activity["id"]
    review_activity(api, world.activity_id, world.qi_b_id, "APPROVE")
    world.activity = get_activity(api, world.activity_id)
    world.pair = get_pair(api, world.pair_id)
    return world


def exempt_program(
    api: ApiClient,
    exemption_type: str = "JUICE_HACCP_CONTROL",
    clock: str = CLOCK_BASE,
    small_importer: bool = False,
    evaluate_supplier_first: bool = True,
) -> SimpleNamespace:
    """A pair whose entry eligibility comes only from a VERIFIED exemption.

    The pair's verification dimension is never touched, so it stays in DRAFT.
    """
    set_clock(api, clock)
    if small_importer:
        importer = create_small_importer(api)
        qi_a = create_qualified_individual(
            api,
            importer["id"],
            full_name="Dara Kim",
            email="dara@harborline.example",
            qualification_summary=(
                "Owner operator with FSVP training for a very small importer program"
            ),
            training_completed_at="2025-05-01T00:00:00Z",
        )
        food = create_plain_food(
            api, importer["id"], food_name="Quinoa grain", fda_product_code="23-QUI-07",
            is_raw_agricultural_commodity=True,
        )
        supplier = create_supplier(
            api,
            importer["id"],
            approve_by_qi_id=qi_a["id"] if evaluate_supplier_first else None,
            name="Andes Grains SAC",
            facility_registration_number="FRN-PE-88002",
        )
    else:
        importer = create_importer(api)
        qi_a = create_qualified_individual(api, importer["id"])
        supplier = create_supplier(
            api,
            importer["id"],
            approve_by_qi_id=qi_a["id"] if evaluate_supplier_first else None,
        )
        food = create_juice_food(api, importer["id"])
    pair = create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    claim_exemption(api, pair["id"], exemption_type, qi_a["id"])
    pair = determine_exemption(api, pair["id"], "VERIFY")
    return SimpleNamespace(
        importer=importer,
        importer_id=importer["id"],
        qi_a=qi_a,
        qi_a_id=qi_a["id"],
        supplier=supplier,
        supplier_id=supplier["id"],
        food=food,
        food_id=food["id"],
        pair=pair,
        pair_id=pair["id"],
    )


# ---------------------------------------------------------------------------
# 4. Threshold / accumulation targeting
# ---------------------------------------------------------------------------


def suspended_program(
    api: ApiClient,
    with_entry: bool = True,
    record_clock: str = "2026-10-20T00:00:00Z",
) -> SimpleNamespace:
    """Drive the supplier below the suspension threshold.

    A failed onsite audit with two findings scores 10.00 points on weight 3.00,
    so the attested final score is 10.00 -- under 60.00. The attestation
    suspends the supplier, lapses the pair, blocks it, holds its entry lines and
    synthesizes one open corrective action.
    """
    world = entered_program(api) if with_entry else verified_program(api)
    set_clock(api, record_clock)
    world.record = file_record(
        api,
        world.activity_onsite["id"],
        world.qi_a_id,
        outcome="FAIL",
        performed_start="2026-09-12T00:00:00Z",
        performed_end="2026-09-14T00:00:00Z",
        findings_count=2,
        document_reference="AUD-2026-0912-RV",
    )
    world.record_id = world.record["id"]
    world.record = attest_record(api, world.record_id, world.qi_b_id)
    actions = list_corrective_actions(api, supplier_id=world.supplier_id)
    world.corrective_actions = actions
    world.corrective_action = actions[0] if actions else None
    world.corrective_action_id = actions[0]["id"] if actions else None
    world.supplier = get_supplier(api, world.supplier_id)
    world.pair = get_pair(api, world.pair_id)
    world.importer = get_importer(api, world.importer_id)
    return world


def reverified_after_decision(
    api: ApiClient,
    decision: str = "IMPORT_SUSPENSION",
    with_entry: bool = True,
) -> SimpleNamespace:
    """:func:`suspended_program`, a corrective-action decision, then a passing
    re-verification performed strictly after the decision instant."""
    world = suspended_program(api, with_entry=with_entry)
    world.corrective_action = decide_corrective_action(
        api, world.corrective_action_id, decision, world.supplier_id
    )
    world.reverification_activity = create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=2,
        justification_text=(
            "Post suspension sampling campaign to re-establish the supplier hazard control"
        ),
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-11-30T00:00:00Z",
    )
    review_activity(api, world.reverification_activity["id"], world.qi_b_id, "APPROVE")
    set_clock(api, "2026-12-01T00:00:00Z")
    world.pass_record = file_record(
        api,
        world.reverification_activity["id"],
        world.qi_a_id,
        outcome="PASS",
        performed_start="2026-11-10T00:00:00Z",
        performed_end="2026-11-12T00:00:00Z",
        findings_count=0,
        document_reference="LAB-2026-1110-D",
    )
    world.pass_record = attest_record(api, world.pass_record["id"], world.qi_b_id)
    world.supplier = get_supplier(api, world.supplier_id)
    world.pair = get_pair(api, world.pair_id)
    world.importer = get_importer(api, world.importer_id)
    return world
