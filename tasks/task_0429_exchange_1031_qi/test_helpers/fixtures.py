"""Composite setup helpers.

These encapsulate the multi-step API sequences the test claims require so test
bodies focus on assertions. Every helper builds its preconditions from scratch
using only PRD-declared endpoints, because the harness restarts the server (empty
DB, clock reset to the 2026-01-01 default) before every test.

Identity threading: the opaque coordinator id passed at exchange creation is the
anchor for the four-eyes segregation check, so callers control it via the
`coordinator_id` argument and the helpers consistently use the matching header.
Settlement-officer ids are passed explicitly per call.

All helpers use get_success_data() (lenient) so a setup misstep surfaces as a clear
"Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_qi_coordinator_headers,
    make_settlement_officer_headers,
)
from .factories import (
    create_exchanger_payload,
    create_exchange_payload,
    create_relinquished_property_payload,
    create_identification_payload,
    create_candidate_payload,
    create_replacement_property_payload,
    create_disbursement_payload,
)


DAY_ZERO = "2026-03-01T00:00:00Z"


# ── Low-level building blocks ────────────────────────────────────────

def set_clock(iso: str, coordinator_id: str = "coord-default"):
    """Move the logical clock to an absolute UTC instant."""
    headers = make_qi_coordinator_headers(coordinator_id)
    return get_success_data(api_client.set_clock(iso, headers))


def create_exchanger(coordinator_id: str = "coord-default", **overrides) -> dict:
    headers = make_qi_coordinator_headers(coordinator_id)
    payload = create_exchanger_payload(**overrides)
    return get_success_data(api_client.create_exchanger(payload, headers))


def create_exchange(exchanger_id: str, exchange_type: str = "FORWARD",
                    coordinator_id: str = "coord-default") -> dict:
    """Create a DRAFT exchange; coordinator_id becomes coordinator_user_id."""
    headers = make_qi_coordinator_headers(coordinator_id)
    payload = create_exchange_payload(exchanger_id, exchange_type)
    return get_success_data(api_client.create_exchange(payload, headers))


def trust_version(exchange_id: str, coordinator_id: str = "coord-default") -> int:
    """Read the exchange's current QualifiedTrust.version (for OCC on create)."""
    headers = make_qi_coordinator_headers(coordinator_id)
    data = get_success_data(api_client.list_trust(exchange_id, headers))
    return data[0]["version"]


def get_trust(exchange_id: str, coordinator_id: str = "coord-default") -> dict:
    headers = make_qi_coordinator_headers(coordinator_id)
    data = get_success_data(api_client.list_trust(exchange_id, headers))
    return data[0]


# ── Tier 1/2: Build an exchange up to a chosen lifecycle stage ───────

def setup_draft_exchange_with_children(exchange_type: str = "FORWARD",
                                       coordinator_id: str = "coord-default",
                                       rel_overrides: dict = None,
                                       day_zero: str = DAY_ZERO):
    """Set clock to Day-0, register exchanger, open a DRAFT exchange, attach the
    relinquished property and an empty trust. Returns (exchange, relinquished, trust).

    Stops BEFORE close-relinquished so close-order / terminate tests can run.
    """
    set_clock(day_zero, coordinator_id)
    exchanger = create_exchanger(coordinator_id)
    exchange = create_exchange(exchanger["id"], exchange_type, coordinator_id)
    headers = make_qi_coordinator_headers(coordinator_id)
    rel_payload = create_relinquished_property_payload(**(rel_overrides or {}))
    rel = get_success_data(
        api_client.create_relinquished_property(exchange["id"], rel_payload, headers)
    )
    trust = get_success_data(api_client.create_trust(exchange["id"], headers))
    return exchange, rel, trust


def setup_closed_exchange(exchange_type: str = "FORWARD",
                          coordinator_id: str = "coord-default",
                          rel_overrides: dict = None,
                          day_zero: str = DAY_ZERO):
    """Build through close-relinquished. The exchange is ACTIVE, posture OPEN, trust
    funded with net_proceeds. Returns (exchange_after_close, relinquished, trust).
    """
    exchange, rel, trust = setup_draft_exchange_with_children(
        exchange_type, coordinator_id, rel_overrides, day_zero
    )
    headers = make_qi_coordinator_headers(coordinator_id)
    closed = get_success_data(api_client.close_relinquished(exchange["id"], headers))
    trust = get_trust(exchange["id"], coordinator_id)
    return closed, rel, trust


# ── Identification stages ────────────────────────────────────────────

def setup_draft_identification(exchange_type: str = "FORWARD",
                               coordinator_id: str = "coord-default",
                               method: str = "THREE_PROPERTY",
                               candidate_fmvs=(420000,),
                               rel_overrides: dict = None,
                               day_zero: str = DAY_ZERO):
    """Closed exchange + a DRAFT identification holding the given candidates.
    Returns (exchange, trust, identification, candidates).
    """
    exchange, rel, trust = setup_closed_exchange(
        exchange_type, coordinator_id, rel_overrides, day_zero
    )
    headers = make_qi_coordinator_headers(coordinator_id)
    idn = get_success_data(
        api_client.create_identification(
            exchange["id"], create_identification_payload(method), headers
        )
    )
    candidates = []
    for fmv in candidate_fmvs:
        cand = get_success_data(
            api_client.add_candidate(
                idn["id"], create_candidate_payload(estimated_fmv=fmv), headers
            )
        )
        candidates.append(cand)
    return exchange, trust, idn, candidates


def setup_finalized_identification(exchange_type: str = "FORWARD",
                                   coordinator_id: str = "coord-default",
                                   method: str = "THREE_PROPERTY",
                                   candidate_fmvs=(420000,),
                                   rel_overrides: dict = None,
                                   day_zero: str = DAY_ZERO):
    """Closed exchange + a FINALIZED identification (posture IDENTIFIED).
    Returns (exchange, trust, identification, candidates).
    """
    exchange, trust, idn, candidates = setup_draft_identification(
        exchange_type, coordinator_id, method, candidate_fmvs, rel_overrides, day_zero
    )
    headers = make_qi_coordinator_headers(coordinator_id)
    idn = get_success_data(api_client.finalize_identification(idn["id"], headers))
    return exchange, trust, idn, candidates


# ── Replacement stage ────────────────────────────────────────────────

def setup_with_replacement(exchange_type: str = "FORWARD",
                           coordinator_id: str = "coord-default",
                           method: str = "THREE_PROPERTY",
                           candidate_fmv=420000,
                           purchase_price=420000,
                           replacement_debt=120000,
                           improvement_value=None,
                           rel_overrides: dict = None,
                           day_zero: str = DAY_ZERO):
    """Closed exchange + FINALIZED identification + one recorded replacement
    (candidate now ACQUIRED, gain figures set).
    Returns (exchange_after_replacement, trust, identification, candidate, replacement).
    """
    exchange, trust, idn, candidates = setup_finalized_identification(
        exchange_type, coordinator_id, method, (candidate_fmv,), rel_overrides, day_zero
    )
    headers = make_qi_coordinator_headers(coordinator_id)
    overrides = {}
    if improvement_value is not None:
        overrides["improvement_value"] = improvement_value
    rp_payload = create_replacement_property_payload(
        candidates[0]["id"], purchase_price=purchase_price,
        replacement_debt=replacement_debt, **overrides
    )
    rp = get_success_data(
        api_client.create_replacement_property(exchange["id"], rp_payload, headers)
    )
    exchange = get_success_data(
        api_client.get_exchange(exchange["id"], headers)
    )
    return exchange, trust, idn, candidates[0], rp


def setup_completed_exchange(coordinator_id: str = "coord-default",
                             candidate_fmv=420000,
                             purchase_price=420000,
                             replacement_debt=120000,
                             rel_overrides: dict = None,
                             day_zero: str = DAY_ZERO):
    """Full happy path through COMPLETED (trust locked).
    Returns (exchange_after_complete, trust, identification, candidate, replacement).
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        "FORWARD", coordinator_id, "THREE_PROPERTY", candidate_fmv,
        purchase_price, replacement_debt, None, rel_overrides, day_zero
    )
    headers = make_qi_coordinator_headers(coordinator_id)
    exchange = get_success_data(api_client.complete_exchange(exchange["id"], headers))
    trust = get_trust(exchange["id"], coordinator_id)
    return exchange, trust, idn, cand, rp


def setup_failed_exchange(coordinator_id: str = "coord-default",
                          rel_overrides: dict = None,
                          day_zero: str = DAY_ZERO,
                          fail_clock: str = "2026-09-01T00:00:00Z"):
    """Closed exchange driven to FAILED via clock advance past the 180-day deadline
    and a /fail call (trust locked). Returns (exchange_after_fail, trust).
    """
    exchange, rel, trust = setup_closed_exchange(
        "FORWARD", coordinator_id, rel_overrides, day_zero
    )
    set_clock(fail_clock, coordinator_id)
    headers = make_qi_coordinator_headers(coordinator_id)
    exchange = get_success_data(api_client.fail_exchange(exchange["id"], headers))
    trust = get_trust(exchange["id"], coordinator_id)
    return exchange, trust


# ── Disbursement helpers ─────────────────────────────────────────────

def create_requested_disbursement(exchange_id: str, purpose: str, amount: float,
                                  coordinator_id: str = "coord-default",
                                  replacement_property_id: str = None):
    """Create a REQUESTED disbursement using the trust's current version."""
    headers = make_qi_coordinator_headers(coordinator_id)
    ver = trust_version(exchange_id, coordinator_id)
    overrides = {}
    if replacement_property_id is not None:
        overrides["replacement_property_id"] = replacement_property_id
    payload = create_disbursement_payload(exchange_id, purpose, amount, ver, **overrides)
    return get_success_data(api_client.create_disbursement(payload, headers))


def setup_settled_disbursement(purpose: str = "QI_FEE", amount: float = 1500,
                               coordinator_id: str = "coord-default",
                               officer_id: str = "officer-1",
                               rel_overrides: dict = None,
                               day_zero: str = DAY_ZERO):
    """Closed exchange + one APPROVED (SETTLED) disbursement; trust debited by amount.
    Returns (exchange, trust_after_debit, disbursement).
    """
    exchange, rel, trust = setup_closed_exchange(
        "FORWARD", coordinator_id, rel_overrides, day_zero
    )
    dis = create_requested_disbursement(exchange["id"], purpose, amount, coordinator_id)
    officer_headers = make_settlement_officer_headers(officer_id)
    dis = get_success_data(api_client.approve_disbursement(dis["id"], officer_headers))
    trust = get_trust(exchange["id"], coordinator_id)
    return exchange, trust, dis


def setup_requested_disbursement(purpose: str = "QI_FEE", amount: float = 1500,
                                 coordinator_id: str = "coord-default",
                                 rel_overrides: dict = None,
                                 day_zero: str = DAY_ZERO):
    """Closed exchange + one REQUESTED (un-approved) disbursement.
    Returns (exchange, trust, disbursement).
    """
    exchange, rel, trust = setup_closed_exchange(
        "FORWARD", coordinator_id, rel_overrides, day_zero
    )
    dis = create_requested_disbursement(exchange["id"], purpose, amount, coordinator_id)
    return exchange, trust, dis
