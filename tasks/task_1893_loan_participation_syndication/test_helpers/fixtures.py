"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
the lenient get_success_data() so failures surface as clear "Setup failed"
errors. Entity-backed role calls always thread the real entity id through
make_borrower_headers / make_participant_headers (PRD §2.1 ownership rules).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULTS
from .factories import (
    create_borrower_payload,
    create_buyback_demand_payload,
    create_default_case_payload,
    create_draw_payload,
    create_facility_payload,
    create_modification_payload,
    create_package_payload,
    create_participant_payload,
    create_payment_payload,
    create_statement_payload,
    create_transfer_payload,
)
from .test_users import (
    make_agent_headers,
    make_borrower_headers,
    make_participant_headers,
)

AGENT = make_agent_headers()


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Advance the server logical clock (PRD §2.4)."""
    get_success_data(api_client.set_clock(to_iso8601, AGENT))


def create_borrower(**overrides) -> dict:
    return get_success_data(
        api_client.create_borrower(create_borrower_payload(**overrides), AGENT)
    )


def create_facility(borrower_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility(create_facility_payload(borrower_id, **overrides), AGENT)
    )


def add_participant(facility_id: str, name: str, commitment_cents: int) -> dict:
    return get_success_data(
        api_client.create_participant(
            create_participant_payload(
                facility_id, participant_name=name, commitment_cents=commitment_cents
            ),
            AGENT,
        )
    )


def commit_participant(participant_id: str) -> dict:
    return get_success_data(api_client.commit_participant(participant_id, AGENT))


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, AGENT))


def get_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, AGENT))


def get_borrower(borrower_id: str) -> dict:
    return get_success_data(api_client.get_borrower(borrower_id, AGENT))


def get_draw(draw_id: str) -> dict:
    return get_success_data(api_client.get_draw(draw_id, AGENT))


def get_modification_request(modification_id: str) -> dict:
    return get_success_data(api_client.get_modification_request(modification_id, AGENT))


def get_consent_vote(vote_id: str) -> dict:
    return get_success_data(api_client.get_consent_vote(vote_id, AGENT))


def get_default_case(case_id: str) -> dict:
    return get_success_data(api_client.get_default_case(case_id, AGENT))


def get_default_vote(vote_id: str) -> dict:
    return get_success_data(api_client.get_default_vote(vote_id, AGENT))


def get_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer(transfer_id, AGENT))


def facility_version(facility_id: str) -> int:
    return get_facility(facility_id)["version"]


def create_draw(facility_id: str, draw_amount_cents: int,
                accrual_start_date: str = DEFAULTS["DRAW_START"],
                accrual_end_date: str = DEFAULTS["DRAW_END"]) -> dict:
    """Create a draw, threading the facility's CURRENT version for the OCC check."""
    version = facility_version(facility_id)
    return get_success_data(
        api_client.create_draw(
            create_draw_payload(
                facility_id,
                expected_facility_version=version,
                draw_amount_cents=draw_amount_cents,
                accrual_start_date=accrual_start_date,
                accrual_end_date=accrual_end_date,
            ),
            AGENT,
        )
    )


def settlements_for_participant(participant_id: str, draw_id: str = None) -> list:
    params = {"participant_id": participant_id}
    if draw_id:
        params["draw_id"] = draw_id
    return get_success_data(api_client.list_funding_settlements(AGENT, params=params))


def settlement_for_participant(participant_id: str, draw_id: str = None) -> dict:
    settlements = settlements_for_participant(participant_id, draw_id)
    assert settlements, f"Setup failed: no settlement found for participant {participant_id}"
    return settlements[0]


def wire_and_confirm(settlement_id: str, participant_id: str, amount_cents: int,
                     penalty_received_cents=None) -> dict:
    """Participant wires exactly amount_cents; agent confirms (with penalty if late)."""
    get_success_data(
        api_client.report_wire(
            settlement_id,
            {"amount_cents": amount_cents},
            make_participant_headers(participant_id),
        )
    )
    payload = {}
    if penalty_received_cents is not None:
        payload["penalty_received_cents"] = penalty_received_cents
    return get_success_data(api_client.confirm_settlement(settlement_id, payload, AGENT))


def wire_and_confirm_due(settlement: dict) -> dict:
    """Wire exactly the settlement's due_cents and confirm (on-time path)."""
    return wire_and_confirm(
        settlement["id"], settlement["participant_id"], settlement["due_cents"]
    )


def create_payment(facility_id: str, borrower_id: str, amount_cents: int,
                   value_date: str = "2026-08-31", payment_type: str = "REGULAR") -> dict:
    """Record a borrower payment as the facility's own borrower (ownership rule)."""
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(
                facility_id,
                payment_type=payment_type,
                amount_cents=amount_cents,
                value_date=value_date,
            ),
            make_borrower_headers(borrower_id),
        )
    )


def create_run(payment_id: str) -> dict:
    """Compute a distribution run, threading the payment's CURRENT version (OCC)."""
    payment = get_success_data(api_client.get_payment(payment_id, AGENT))
    return get_success_data(
        api_client.create_distribution_run(
            payment_id, {"expected_payment_version": payment["version"]}, AGENT
        )
    )


def create_and_remit_run(payment_id: str) -> dict:
    run = create_run(payment_id)
    return get_success_data(api_client.remit_distribution_run(run["id"], AGENT))


def lines_for_run(run_id: str) -> list:
    return get_success_data(
        api_client.list_distribution_lines(AGENT, params={"run_id": run_id})
    )


# ---------------------------------------------------------------------------
# Tier 1/2: facility hierarchies
# ---------------------------------------------------------------------------

def setup_committed_facility(commitments, total_commitment_cents=None,
                             facility_overrides=None) -> dict:
    """Borrower + facility + one participant per commitment, all committed.

    commitments: list of (name, commitment_cents) tuples.
    total_commitment_cents defaults to the exact sum (facility lands COMMITTED);
    pass a larger total to leave the facility SYNDICATING.
    """
    borrower = create_borrower()
    facility_kwargs = dict(facility_overrides or {})
    if total_commitment_cents is not None:
        facility_kwargs["total_commitment_cents"] = total_commitment_cents
    else:
        facility_kwargs["total_commitment_cents"] = sum(c for _, c in commitments)
    facility = create_facility(borrower["id"], **facility_kwargs)
    participants = [add_participant(facility["id"], name, c) for name, c in commitments]
    for p in participants:
        commit_participant(p["id"])
    return {
        "borrower": borrower,
        "facility": get_facility(facility["id"]),
        "participants": [get_participant(p["id"]) for p in participants],
    }


def setup_funded_facility(commitments, draw_amount_cents,
                          draw_start=DEFAULTS["DRAW_START"],
                          draw_end=DEFAULTS["DRAW_END"],
                          total_commitment_cents=None,
                          facility_overrides=None) -> dict:
    """Committed facility + one draw + every settlement wired for its exact
    due_cents and confirmed (on time). Facility ends ACTIVE (first draw settled).

    Returns borrower, facility (refreshed), participants, draw, settlements.
    """
    base = setup_committed_facility(
        commitments,
        total_commitment_cents=total_commitment_cents,
        facility_overrides=facility_overrides,
    )
    facility = base["facility"]
    draw = create_draw(facility["id"], draw_amount_cents, draw_start, draw_end)
    settlements = []
    for p in base["participants"]:
        settlement = settlement_for_participant(p["id"], draw["id"])
        wire_and_confirm_due(settlement)
        settlements.append(
            get_success_data(api_client.get_funding_settlement(settlement["id"], AGENT))
        )
    return {
        "borrower": base["borrower"],
        "facility": get_facility(facility["id"]),
        "participants": [get_participant(p["id"]) for p in base["participants"]],
        "draw": get_success_data(api_client.get_draw(draw["id"], AGENT)),
        "settlements": settlements,
    }


# ---------------------------------------------------------------------------
# Tier 3: governance helpers (modifications, defaults)
# ---------------------------------------------------------------------------

def create_modification(facility_id: str, borrower_id: str, modification_type: str,
                        terms: dict) -> dict:
    return get_success_data(
        api_client.create_modification_request(
            create_modification_payload(facility_id, modification_type, terms),
            make_borrower_headers(borrower_id),
        )
    )


def solicit_modification(modification_id: str) -> dict:
    return get_success_data(api_client.solicit_modification(modification_id, AGENT))


def cast_consent_vote(modification_id: str, participant_id: str, vote: str) -> dict:
    return get_success_data(
        api_client.cast_consent_vote(
            modification_id, {"vote": vote}, make_participant_headers(participant_id)
        )
    )


def declare_default(facility_id: str, default_type: str = "PAYMENT_DEFAULT") -> dict:
    return get_success_data(
        api_client.create_default_case(
            create_default_case_payload(facility_id, default_type=default_type), AGENT
        )
    )


def cast_default_vote(case_id: str, participant_id: str, vote: str) -> dict:
    return get_success_data(
        api_client.cast_default_vote(
            case_id, {"vote": vote}, make_participant_headers(participant_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: transfer / buyback helpers
# ---------------------------------------------------------------------------

def propose_transfer(facility_id: str, from_participant_id: str,
                     transfer_amount_cents: int, settlement_date: str = "2026-08-20",
                     transferee_name=None, transferee_participant_id=None) -> dict:
    payload = create_transfer_payload(
        facility_id,
        transfer_amount_cents=transfer_amount_cents,
        settlement_date=settlement_date,
    )
    if transferee_participant_id is not None:
        payload.pop("transferee_name", None)
        payload["transferee_participant_id"] = transferee_participant_id
    elif transferee_name is not None:
        payload["transferee_name"] = transferee_name
    return get_success_data(
        api_client.create_transfer(
            payload, make_participant_headers(from_participant_id)
        )
    )


def settle_transfer(transfer_id: str, from_participant_id: str) -> dict:
    """Approve then settle, threading the transferor's CURRENT version (OCC)."""
    get_success_data(api_client.approve_transfer(transfer_id, AGENT))
    transferor = get_participant(from_participant_id)
    return get_success_data(
        api_client.settle_transfer(
            transfer_id,
            {"expected_from_participant_version": transferor["version"]},
            AGENT,
        )
    )


def demand_buyback(facility_id: str, participant_id: str,
                   breach_type: str = "MISREPRESENTATION") -> dict:
    return get_success_data(
        api_client.create_buyback_demand(
            create_buyback_demand_payload(facility_id, breach_type=breach_type),
            make_participant_headers(participant_id),
        )
    )


def settle_buyback(demand_id: str) -> dict:
    get_success_data(api_client.acknowledge_buyback_demand(demand_id, AGENT))
    return get_success_data(api_client.settle_buyback_demand(demand_id, AGENT))


# ---------------------------------------------------------------------------
# Tier 3: reporting helpers
# ---------------------------------------------------------------------------

def create_statement(facility_id: str, borrower_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_financial_statement(
            create_statement_payload(facility_id, **overrides),
            make_borrower_headers(borrower_id),
        )
    )


def create_package(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_reporting_package(
            create_package_payload(facility_id, **overrides), AGENT
        )
    )
