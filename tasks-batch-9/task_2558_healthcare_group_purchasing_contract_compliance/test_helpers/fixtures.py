"""Composite setup: builders that drive real endpoints, plus pytest fixtures.

The harness relaunches the API before every single test, so each test starts
against an empty store.  Nothing here seeds data behind the API's back: every
precondition is created by calling the same endpoints the PRD publishes, in the
order the PRD requires (contract, then items, then members, then commitments,
then cross-references, then activations, then distributor files, then
measurements and fee distributions).

The builders are plain functions so a test can vary one field without inheriting
a whole fixture; the fixtures below compose the builders for the setups that more
than one test needs.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import GpoApiClient
from .constants import (
    DEFAULT_CLOCK_INSTANT,
    TIER_0,
)
from .test_users import (
    clinical_reviewer_2_headers,
    clinical_reviewer_headers,
    compliance_analyst_headers,
    contract_manager_2_headers,
    contract_manager_headers,
    distributor_agent_headers,
    finance_administrator_headers,
    make_member_materials_manager_headers,
)

Json = Dict[str, Any]


# ===========================================================================
# Primitive builders
# ===========================================================================


def set_clock(api: GpoApiClient, instant: str = DEFAULT_CLOCK_INSTANT) -> Json:
    return validate_success(api.set_clock(instant, headers=contract_manager_headers()), 200)


def create_contract(api: GpoApiClient, **overrides: Any) -> Json:
    """Create a DRAFT contract."""
    payload = f.contract_payload(**overrides)
    return validate_success(api.create_contract(payload, headers=contract_manager_headers()), 201)


def activate_contract(api: GpoApiClient, contract_id: str) -> Json:
    return validate_success(
        api.activate_contract(contract_id, {}, headers=contract_manager_headers()), 200
    )


def create_active_contract(api: GpoApiClient, **overrides: Any) -> Json:
    """Create a contract and move it to ACTIVE, endorsing evidence first if required."""
    contract = create_contract(api, **overrides)
    if contract.get("requires_clinical_review"):
        endorse_evidence(api, contract["id"])
    activate_contract(api, contract["id"])
    return read_contract(api, contract["id"])


def read_contract(api: GpoApiClient, contract_id: str) -> Json:
    return validate_success(api.get_contract(contract_id, headers=contract_manager_headers()), 200)


def create_item(api: GpoApiClient, contract_id: str, **overrides: Any) -> Json:
    payload = f.contract_item_payload(**overrides)
    return validate_success(
        api.create_contract_item(contract_id, payload, headers=contract_manager_headers()), 201
    )


def read_item(api: GpoApiClient, item_id: str) -> Json:
    return validate_success(
        api.get_contract_item(item_id, headers=contract_manager_headers()), 200
    )


def create_member(api: GpoApiClient, **overrides: Any) -> Json:
    payload = f.member_payload(**overrides)
    return validate_success(api.create_member(payload, headers=contract_manager_headers()), 201)


def read_member(api: GpoApiClient, member_id: str) -> Json:
    return validate_success(api.get_member(member_id, headers=contract_manager_headers()), 200)


def suspend_member(api: GpoApiClient, member_id: str, reason: str = "audit hold") -> Json:
    return validate_success(
        api.suspend_member(
            member_id, f.reason_payload(reason), headers=compliance_analyst_headers()
        ),
        200,
    )


def create_commitment(
    api: GpoApiClient,
    member_id: str,
    contract_id: str,
    elected_tier_code: str = TIER_0,
    committed_volume_units: int = 100,
    effective_from: str = "2026-08-01",
) -> Json:
    payload = f.commitment_payload(
        member_id,
        contract_id,
        elected_tier_code=elected_tier_code,
        committed_volume_units=committed_volume_units,
        effective_from=effective_from,
    )
    return validate_success(
        api.create_commitment(
            payload, headers=make_member_materials_manager_headers(member_id)
        ),
        201,
    )


def read_commitment(api: GpoApiClient, commitment_id: str) -> Json:
    return validate_success(
        api.get_commitment(commitment_id, headers=compliance_analyst_headers()), 200
    )


def commitment_version(api: GpoApiClient, commitment_id: str) -> int:
    return read_commitment(api, commitment_id)["version"]


def countersign_commitment(
    api: GpoApiClient,
    commitment_id: str,
    member_id: str,
    signer_name: str = "R. Vasquez",
) -> Json:
    """Walk the letter of participation from NOT_ISSUED to COUNTERSIGNED."""
    validate_success(api.issue_lop(commitment_id, {}, headers=contract_manager_headers()), 200)
    validate_success(
        api.sign_lop(
            commitment_id,
            f.signer_payload(signer_name),
            headers=make_member_materials_manager_headers(member_id),
        ),
        200,
    )
    return validate_success(
        api.countersign_lop(commitment_id, {}, headers=contract_manager_headers()), 200
    )


def open_requalification(
    api: GpoApiClient, commitment_id: str, reason: str = "annual tier review"
) -> Json:
    return validate_success(
        api.open_requalification(
            commitment_id, f.reason_payload(reason), headers=compliance_analyst_headers()
        ),
        200,
    )


def terminate_commitment(
    api: GpoApiClient, commitment_id: str, reason: str = "member left the aggregation group"
) -> Json:
    return validate_success(
        api.terminate_commitment(
            commitment_id, f.reason_payload(reason), headers=compliance_analyst_headers()
        ),
        200,
    )


def create_evidence_review(
    api: GpoApiClient,
    contract_id: str,
    clinical_efficacy_score: float = 8.00,
    safety_score: float = 7.00,
    supply_resilience_score: float = 6.00,
    summary: Optional[str] = "Meta-analysis of 14 trials.",
) -> Json:
    payload = f.evidence_review_payload(
        contract_id,
        clinical_efficacy_score=clinical_efficacy_score,
        safety_score=safety_score,
        supply_resilience_score=supply_resilience_score,
        summary=summary,
    )
    return validate_success(
        api.create_evidence_review(payload, headers=clinical_reviewer_headers()), 201
    )


def endorse_evidence(
    api: GpoApiClient,
    contract_id: str,
    clinical_efficacy_score: float = 8.00,
    safety_score: float = 7.00,
    supply_resilience_score: float = 6.00,
) -> Json:
    """Submit a CONVERT dossier as one reviewer and endorse it as the other."""
    review = create_evidence_review(
        api,
        contract_id,
        clinical_efficacy_score=clinical_efficacy_score,
        safety_score=safety_score,
        supply_resilience_score=supply_resilience_score,
    )
    return validate_success(
        api.endorse_review(review["id"], {}, headers=clinical_reviewer_2_headers()), 200
    )


def read_evidence_review(api: GpoApiClient, review_id: str) -> Json:
    return validate_success(
        api.get_evidence_review(review_id, headers=clinical_reviewer_headers()), 200
    )


def create_cross_reference(
    api: GpoApiClient,
    member_id: str,
    contract_item_id: str,
    member_item_number: str = "MI-1",
    match_type: str = "EXACT",
    conversion_factor: float = 1.0,
) -> Json:
    payload = f.cross_reference_payload(
        member_id,
        contract_item_id,
        member_item_number=member_item_number,
        match_type=match_type,
        conversion_factor=conversion_factor,
    )
    return validate_success(
        api.create_cross_reference(
            payload, headers=make_member_materials_manager_headers(member_id)
        ),
        201,
    )


def approve_cross_reference(api: GpoApiClient, xref_id: str) -> Json:
    return validate_success(
        api.approve_cross_reference(xref_id, {}, headers=contract_manager_headers()), 200
    )


def create_approved_cross_reference(
    api: GpoApiClient,
    member_id: str,
    contract_item_id: str,
    member_item_number: str = "MI-1",
    match_type: str = "EXACT",
    conversion_factor: float = 1.0,
) -> Json:
    xref = create_cross_reference(
        api,
        member_id,
        contract_item_id,
        member_item_number=member_item_number,
        match_type=match_type,
        conversion_factor=conversion_factor,
    )
    return approve_cross_reference(api, xref["id"])


def create_tier_activation(
    api: GpoApiClient,
    commitment_id: str,
    contract_item_id: str,
    effective_from: str = "2026-08-01",
    effective_to: str = "2026-12-31",
) -> Json:
    """A TIER_PRICE activation left in DRAFT."""
    payload = f.price_activation_payload(
        commitment_id,
        contract_item_id,
        activation_type="TIER_PRICE",
        effective_from=effective_from,
        effective_to=effective_to,
    )
    return validate_success(
        api.create_price_activation(payload, headers=contract_manager_headers()), 201
    )


def activate_tier_activation(api: GpoApiClient, activation_id: str) -> Json:
    return validate_success(
        api.activate_price_activation(activation_id, {}, headers=contract_manager_headers()), 200
    )


def create_active_tier_activation(
    api: GpoApiClient,
    commitment_id: str,
    contract_item_id: str,
    effective_from: str = "2026-08-01",
    effective_to: str = "2026-12-31",
) -> Json:
    draft = create_tier_activation(
        api, commitment_id, contract_item_id, effective_from, effective_to
    )
    return activate_tier_activation(api, draft["id"])


def create_local_exception(
    api: GpoApiClient,
    commitment_id: str,
    member_id: str,
    contract_item_id: str,
    requested_price_cents: int,
    effective_from: str = "2026-08-01",
    effective_to: str = "2026-12-31",
    stage: str = "ACTIVE",
) -> Json:
    """A LOCAL_EXCEPTION walked to ``stage``: DRAFT, ENDORSED, APPROVED or ACTIVE.

    The endorser and the approver are deliberately different contract managers,
    since the API refuses an approval by the endorsing user.
    """
    payload = f.price_activation_payload(
        commitment_id,
        contract_item_id,
        activation_type="LOCAL_EXCEPTION",
        effective_from=effective_from,
        effective_to=effective_to,
        requested_price_cents=requested_price_cents,
    )
    row = validate_success(
        api.create_price_activation(
            payload, headers=make_member_materials_manager_headers(member_id)
        ),
        201,
    )
    if stage == "DRAFT":
        return row
    row = validate_success(
        api.endorse_price_activation(row["id"], {}, headers=contract_manager_headers()), 200
    )
    if stage == "ENDORSED":
        return row
    row = validate_success(
        api.approve_price_activation(row["id"], {}, headers=contract_manager_2_headers()), 200
    )
    if stage == "APPROVED":
        return row
    return validate_success(
        api.activate_price_activation(row["id"], {}, headers=contract_manager_headers()), 200
    )


def read_activation(api: GpoApiClient, activation_id: str) -> Json:
    return validate_success(
        api.get_price_activation(activation_id, headers=contract_manager_headers()), 200
    )


def submit_distributor_file(
    api: GpoApiClient,
    member_id: str,
    contract_id: str,
    lines: List[Json],
    distributor_code: str = "D-A",
    period_start: str = "2026-08-01",
    period_end: str = "2026-09-01",
    stage: str = "LOADED",
) -> Json:
    """Submit a statement and walk it to ``stage``: RECEIVED, VALIDATED, LOADED or REVERSED."""
    payload = f.distributor_file_payload(
        member_id,
        contract_id,
        lines,
        distributor_code=distributor_code,
        period_start=period_start,
        period_end=period_end,
    )
    row = validate_success(
        api.create_distributor_file(payload, headers=distributor_agent_headers()), 201
    )
    if stage == "RECEIVED":
        return row
    row = validate_success(
        api.validate_distributor_file(row["id"], {}, headers=distributor_agent_headers()), 200
    )
    if stage in ("VALIDATED", "VALIDATING"):
        return row
    row = validate_success(
        api.load_distributor_file(row["id"], {}, headers=compliance_analyst_headers()), 200
    )
    if stage == "LOADED":
        return row
    return validate_success(
        api.reverse_distributor_file(
            row["id"], f.reason_payload("distributor restated the file"),
            headers=compliance_analyst_headers(),
        ),
        200,
    )


def load_distributor_file(api: GpoApiClient, file_id: str) -> Json:
    return validate_success(
        api.load_distributor_file(file_id, {}, headers=compliance_analyst_headers()), 200
    )


def reverse_distributor_file(
    api: GpoApiClient, file_id: str, reason: str = "distributor restated the file"
) -> Json:
    return validate_success(
        api.reverse_distributor_file(
            file_id, f.reason_payload(reason), headers=compliance_analyst_headers()
        ),
        200,
    )


def read_distributor_file(api: GpoApiClient, file_id: str) -> Json:
    return validate_success(
        api.get_distributor_file(file_id, headers=compliance_analyst_headers()), 200
    )


def lines_of_file(api: GpoApiClient, file_id: str, **filters: Any) -> List[Json]:
    params = dict(filters)
    params["distributor_file_id"] = file_id
    params.setdefault("limit", 100)
    body = validate_success(
        api.list_purchase_lines(params, headers=compliance_analyst_headers()), 200
    )
    return body["data"] if isinstance(body, dict) and "data" in body else body


def open_measurement(
    api: GpoApiClient,
    commitment_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-09-01",
) -> Json:
    """Open a DRAFT measurement, reading the commitment's live version first."""
    version = commitment_version(api, commitment_id)
    payload = f.measurement_payload(
        commitment_id, version, period_start=period_start, period_end=period_end
    )
    return validate_success(
        api.create_measurement(payload, headers=compliance_analyst_headers()), 201
    )


def measure(api: GpoApiClient, measurement_id: str) -> Json:
    return validate_success(
        api.measure(measurement_id, {}, headers=compliance_analyst_headers()), 200
    )


def finalize_measurement(api: GpoApiClient, measurement_id: str) -> Json:
    return validate_success(
        api.finalize_measurement(measurement_id, {}, headers=compliance_analyst_headers()), 200
    )


def read_measurement(api: GpoApiClient, measurement_id: str) -> Json:
    return validate_success(
        api.get_measurement(measurement_id, headers=compliance_analyst_headers()), 200
    )


def create_distribution(
    api: GpoApiClient,
    contract_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-09-01",
) -> Json:
    payload = f.distribution_payload(
        contract_id, period_start=period_start, period_end=period_end
    )
    return validate_success(
        api.create_distribution(payload, headers=finance_administrator_headers()), 201
    )


def collect_distribution(api: GpoApiClient, distribution_id: str, cents: int) -> Json:
    return validate_success(
        api.collect_distribution(
            distribution_id, f.collect_payload(cents), headers=finance_administrator_headers()
        ),
        200,
    )


def distribute_distribution(api: GpoApiClient, distribution_id: str) -> Json:
    return validate_success(
        api.distribute_distribution(
            distribution_id, {}, headers=finance_administrator_headers()
        ),
        200,
    )


def read_distribution(api: GpoApiClient, distribution_id: str) -> Json:
    return validate_success(
        api.get_distribution(distribution_id, headers=finance_administrator_headers()), 200
    )


# ===========================================================================
# Composite scenario builders
# ===========================================================================


def build_priced_setup(
    api: GpoApiClient,
    contract_overrides: Optional[Json] = None,
    item_overrides: Optional[Json] = None,
    member_overrides: Optional[Json] = None,
    elected_tier_code: str = TIER_0,
    committed_volume_units: int = 100,
    effective_from: str = "2026-08-01",
    countersign: bool = True,
    with_xref: bool = True,
    member_item_number: str = "MI-1",
    match_type: str = "EXACT",
    conversion_factor: float = 1.0,
    with_activation: bool = True,
    activation_from: str = "2026-08-01",
    activation_to: str = "2026-12-31",
    pin_clock: bool = True,
) -> Json:
    """The recurring spine: ACTIVE contract, one catalog item, one elected member.

    Optionally walks the letter of participation to COUNTERSIGNED (so the
    commitment is ACTIVE at its elected tier), approves a cross-reference from
    the member's item number to the catalog item, and activates a TIER_PRICE
    activation so purchases have a governing price to compare against.
    """
    if pin_clock:
        set_clock(api)
    contract = create_active_contract(api, **(contract_overrides or {}))
    item = create_item(api, contract["id"], **(item_overrides or {}))
    member = create_member(api, **(member_overrides or {}))
    commitment = create_commitment(
        api,
        member["id"],
        contract["id"],
        elected_tier_code=elected_tier_code,
        committed_volume_units=committed_volume_units,
        effective_from=effective_from,
    )
    if countersign:
        commitment = countersign_commitment(api, commitment["id"], member["id"])
    xref = None
    if with_xref:
        xref = create_approved_cross_reference(
            api,
            member["id"],
            item["id"],
            member_item_number=member_item_number,
            match_type=match_type,
            conversion_factor=conversion_factor,
        )
    activation = None
    if with_activation:
        activation = create_active_tier_activation(
            api, commitment["id"], item["id"], activation_from, activation_to
        )
    return {
        "contract": contract,
        "item": item,
        "member": member,
        "commitment": commitment,
        "xref": xref,
        "activation": activation,
        "member_headers": make_member_materials_manager_headers(member["id"]),
    }


def build_second_member(
    api: GpoApiClient,
    contract_id: str,
    item_id: str,
    member_code: str = "M-B",
    name: str = "Lakeshore Community Hospital",
    member_item_number: str = "MI-1",
    elected_tier_code: str = TIER_0,
    committed_volume_units: int = 100,
    with_xref: bool = True,
    with_activation: bool = True,
    activation_from: str = "2026-08-01",
    activation_to: str = "2026-12-31",
) -> Json:
    """A second member elected onto an existing contract, priced the same way."""
    member = create_member(
        api,
        member_code=member_code,
        name=name,
        item_master=[f.item_master_row(member_item_number)],
    )
    commitment = create_commitment(
        api,
        member["id"],
        contract_id,
        elected_tier_code=elected_tier_code,
        committed_volume_units=committed_volume_units,
    )
    commitment = countersign_commitment(api, commitment["id"], member["id"])
    xref = None
    if with_xref:
        xref = create_approved_cross_reference(
            api, member["id"], item_id, member_item_number=member_item_number
        )
    activation = None
    if with_activation:
        activation = create_active_tier_activation(
            api, commitment["id"], item_id, activation_from, activation_to
        )
    return {
        "member": member,
        "commitment": commitment,
        "xref": xref,
        "activation": activation,
        "member_headers": make_member_materials_manager_headers(member["id"]),
    }


# ===========================================================================
# Tier 1 — API handle and single-entity state progression
# ===========================================================================


@pytest.fixture
def api() -> GpoApiClient:
    return GpoApiClient()


@pytest.fixture
def clock(api: GpoApiClient) -> Json:
    """Pin the logical clock at its documented default instant."""
    return set_clock(api)


@pytest.fixture
def draft_contract(api: GpoApiClient) -> Json:
    return create_contract(api)


@pytest.fixture
def active_contract(api: GpoApiClient) -> Json:
    return create_active_contract(api)


@pytest.fixture
def contract_with_item(api: GpoApiClient) -> Json:
    contract = create_active_contract(api)
    item = create_item(api, contract["id"])
    return {"contract": contract, "item": item}


@pytest.fixture
def member(api: GpoApiClient) -> Json:
    return create_member(api)


@pytest.fixture
def elected_commitment(api: GpoApiClient) -> Json:
    """A commitment that exists but whose letter has never been issued."""
    return build_priced_setup(
        api, countersign=False, with_xref=False, with_activation=False
    )


@pytest.fixture
def active_commitment(api: GpoApiClient) -> Json:
    """A countersigned commitment with no cross-reference and no activation yet."""
    return build_priced_setup(api, with_xref=False, with_activation=False)


# ===========================================================================
# Tier 2 — the priced entity hierarchy
# ===========================================================================


@pytest.fixture
def priced_setup(api: GpoApiClient) -> Json:
    """Contract, catalog item, member, ACTIVE commitment, approved xref, live price."""
    return build_priced_setup(api)


@pytest.fixture
def priced_setup_with_unmatched_item(api: GpoApiClient) -> Json:
    """As ``priced_setup`` but the member's master also holds an uncrossreferenced MI-9."""
    return build_priced_setup(
        api,
        member_overrides={
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-9", "Unlisted suture kit"),
            ]
        },
    )


# ===========================================================================
# Tier 3 — full lifecycle shortcuts
# ===========================================================================


@pytest.fixture
def dual_variant_setup(api: GpoApiClient) -> Json:
    """A measurement already taken to PRELIMINARY over a period with mixed spend.

    One fully accepted file contributes 5000 on-contract units at 9500 plus 500
    unmatched units at 6000; a second file of the same period is only partially
    loaded and carries the 1500-unit leakage line at 10500.  The commitment is in
    REQUAL_REVIEW so the measurement can be finalized.
    """
    setup = build_priced_setup(api)
    member_id = setup["member"]["id"]
    contract_id = setup["contract"]["id"]
    file_a = submit_distributor_file(
        api,
        member_id,
        contract_id,
        [
            f.purchase_line_row("MI-1", 5000, 9500, "2026-08-05"),
            f.purchase_line_row("MI-9", 500, 6000, "2026-08-06"),
        ],
        distributor_code="D-A",
    )
    file_b = submit_distributor_file(
        api,
        member_id,
        contract_id,
        [
            f.purchase_line_row("MI-1", 1500, 10500, "2026-08-07"),
            f.purchase_line_row("MI-1", 0, 9500, "2026-08-08"),
        ],
        distributor_code="D-B",
    )
    open_requalification(api, setup["commitment"]["id"])
    measurement = open_measurement(api, setup["commitment"]["id"])
    preliminary = measure(api, measurement["id"])
    setup.update(
        {
            "file_a": file_a,
            "file_b": file_b,
            "measurement": measurement,
            "preliminary": preliminary,
        }
    )
    return setup


@pytest.fixture
def watchlist_chain_setup(api: GpoApiClient) -> Json:
    """One loaded file under the leakage threshold, one validated file that will cross it.

    A local exception at 9600 sits on top of the tier price, so it is the
    governing price the second file's 10500 line is judged against.
    """
    setup = build_priced_setup(
        api,
        member_overrides={
            "item_master": [
                f.item_master_row("MI-1"),
                f.item_master_row("MI-9", "Unlisted suture kit"),
            ]
        },
    )
    member_id = setup["member"]["id"]
    contract_id = setup["contract"]["id"]
    exception = create_local_exception(
        api,
        setup["commitment"]["id"],
        member_id,
        setup["item"]["id"],
        9600,
        effective_from="2026-08-01",
        effective_to="2026-12-31",
    )
    file_a = submit_distributor_file(
        api,
        member_id,
        contract_id,
        [
            f.purchase_line_row("MI-1", 5000, 9500, "2026-08-05"),
            f.purchase_line_row("MI-9", 500, 6000, "2026-08-10"),
        ],
        distributor_code="D-A",
    )
    file_b = submit_distributor_file(
        api,
        member_id,
        contract_id,
        [
            f.purchase_line_row("MI-1", 1500, 10500, "2026-08-12"),
            f.purchase_line_row("MI-1", 0, 9500, "2026-08-20"),
        ],
        distributor_code="D-B",
        stage="VALIDATED",
    )
    setup.update({"exception": exception, "file_a": file_a, "file_b": file_b})
    return setup


@pytest.fixture
def per_line_fee_setup(api: GpoApiClient) -> Json:
    """An accrual-basis contract whose loaded file holds two 1150-cent lines."""
    setup = build_priced_setup(api, contract_overrides={"share_basis": "ACCRUAL"})
    file_a = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-05"),
            f.purchase_line_row("MI-1", 1, 1150, "2026-08-06"),
        ],
    )
    setup["file_a"] = file_a
    return setup


@pytest.fixture
def holdback_two_member_setup(api: GpoApiClient) -> Json:
    """Two priced members, 4750000 and 1900000 of on-contract spend, fee collected at 100200."""
    setup = build_priced_setup(
        api,
        contract_overrides={"contract_code": "C-COL", "share_basis": "COLLECTED"},
        member_overrides={"member_code": "M-A"},
    )
    contract_id = setup["contract"]["id"]
    item_id = setup["item"]["id"]
    second = build_second_member(
        api,
        contract_id,
        item_id,
        member_code="M-B",
        name="Lakeshore Surgical Center",
    )
    file_a = submit_distributor_file(
        api,
        setup["member"]["id"],
        contract_id,
        [f.purchase_line_row("MI-1", 500, 9500, "2026-08-05")],
    )
    file_b = submit_distributor_file(
        api,
        second["member"]["id"],
        contract_id,
        [f.purchase_line_row("MI-1", 200, 9500, "2026-08-07")],
    )
    distribution = create_distribution(api, contract_id)
    collected = collect_distribution(api, distribution["id"], 100200)
    setup.update(
        {
            "member_a": setup["member"],
            "commitment_a": setup["commitment"],
            "member_b": second["member"],
            "commitment_b": second["commitment"],
            "second": second,
            "file_a": file_a,
            "file_b": file_b,
            "distribution": distribution,
            "collected": collected,
        }
    )
    return setup


@pytest.fixture
def accrual_and_collected_setup(api: GpoApiClient) -> Json:
    """One member on two contracts that differ only in ``share_basis``.

    Each contract accrues an identical 142500 of administrative fee from a single
    500-unit line at 9500; the collected-basis contract has additionally recorded
    a 100200 remittance, so the two settlements start from different gross pools.
    """
    set_clock(api)
    accrual_contract = create_active_contract(
        api, contract_code="C-ACC", share_basis="ACCRUAL"
    )
    accrual_item = create_item(api, accrual_contract["id"])
    collected_contract = create_active_contract(
        api, contract_code="C-COL", share_basis="COLLECTED"
    )
    collected_item = create_item(api, collected_contract["id"])
    member = create_member(
        api,
        item_master=[
            f.item_master_row("MI-1"),
            f.item_master_row("MI-2", "Suture 3-0 alt"),
        ],
    )
    accrual_commitment = create_commitment(api, member["id"], accrual_contract["id"])
    accrual_commitment = countersign_commitment(
        api, accrual_commitment["id"], member["id"]
    )
    collected_commitment = create_commitment(api, member["id"], collected_contract["id"])
    collected_commitment = countersign_commitment(
        api, collected_commitment["id"], member["id"]
    )
    create_approved_cross_reference(
        api, member["id"], accrual_item["id"], member_item_number="MI-1"
    )
    create_approved_cross_reference(
        api, member["id"], collected_item["id"], member_item_number="MI-2"
    )
    create_active_tier_activation(api, accrual_commitment["id"], accrual_item["id"])
    create_active_tier_activation(api, collected_commitment["id"], collected_item["id"])
    submit_distributor_file(
        api,
        member["id"],
        accrual_contract["id"],
        [f.purchase_line_row("MI-1", 500, 9500, "2026-08-05")],
    )
    submit_distributor_file(
        api,
        member["id"],
        collected_contract["id"],
        [f.purchase_line_row("MI-2", 500, 9500, "2026-08-05")],
    )
    accrual_distribution = create_distribution(api, accrual_contract["id"])
    collected_distribution = create_distribution(api, collected_contract["id"])
    collect_distribution(api, collected_distribution["id"], 100200)
    return {
        "member": member,
        "accrual_contract": accrual_contract,
        "accrual_item": accrual_item,
        "accrual_commitment": accrual_commitment,
        "accrual_distribution": accrual_distribution,
        "collected_contract": collected_contract,
        "collected_item": collected_item,
        "collected_commitment": collected_commitment,
        "collected_distribution": collected_distribution,
    }


@pytest.fixture
def revision_cycle_setup(api: GpoApiClient) -> Json:
    """A DRAFT conversion contract with one dossier scored below the convert threshold."""
    set_clock(api)
    contract = create_contract(
        api,
        contract_code="C-CONV",
        supplier_name="Northline Ortho",
        category_code="CAT-ORTHO",
        requires_clinical_review=True,
    )
    review = create_evidence_review(
        api,
        contract["id"],
        clinical_efficacy_score=6.00,
        safety_score=6.50,
        supply_resilience_score=7.50,
        summary="Initial category dossier: efficacy comparable, safety data thin.",
    )
    return {"contract": contract, "review": review}


@pytest.fixture
def loaded_ledger_setup(api: GpoApiClient) -> Json:
    """A single fully accepted, loaded file: 5000 on-contract units plus 500 unmatched."""
    setup = build_priced_setup(api)
    file_a = submit_distributor_file(
        api,
        setup["member"]["id"],
        setup["contract"]["id"],
        [
            f.purchase_line_row("MI-1", 5000, 9500, "2026-08-05"),
            f.purchase_line_row("MI-9", 500, 6000, "2026-08-06"),
        ],
    )
    setup["file_a"] = file_a
    return setup
