"""Pre-built role headers for every role in the PRD (section 2.1).

PRD 2.1: Driver and CustomerRep are entity-backed roles — their X-User-ID must
equal a real Driver.id / Customer.id on ownership-gated calls, so per-instance
builders are mandatory for them. The other five roles use opaque identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import OP_METER, OP_SCALE, SO_1

# Shared constants — safe for opaque roles and for tests that don't exercise
# entity-backed ownership.
TEST_USERS = {
    "fleet_admin_headers": build_user_headers("fa-1", "FleetAdmin"),
    "dispatcher_headers": build_user_headers("disp-1", "Dispatcher"),
    "terminal_operator_headers": build_user_headers(OP_METER, "TerminalOperator"),
    "terminal_operator_scale_headers": build_user_headers(OP_SCALE, "TerminalOperator"),
    "wash_operator_headers": build_user_headers("wo-1", "WashOperator"),
    "safety_officer_headers": build_user_headers(SO_1, "SafetyOfficer"),
    # entity_backed fallbacks — ONLY for non-ownership tests (e.g. 404s):
    "driver_headers": build_user_headers("driver-unbound", "Driver"),
    "customer_rep_headers": build_user_headers("customer-unbound", "CustomerRep"),
}


def make_terminal_operator_headers(user_id: str) -> dict:
    """Opaque TerminalOperator id — pick per scenario (meter closer vs scale)."""
    return build_user_headers(user_id, "TerminalOperator")


def make_safety_officer_headers(user_id: str) -> dict:
    """Opaque SafetyOfficer id — pick per scenario (closer vs reopener)."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_driver_headers(user_id: str) -> dict:
    """Entity-backed Driver role (PRD 2.1). Pass the actual Driver.id as user_id
    whenever the call is ownership-gated (start-delivery, delivery close, spill
    report)."""
    return build_user_headers(user_id, "Driver")


def make_customer_rep_headers(user_id: str) -> dict:
    """Entity-backed CustomerRep role (PRD 2.1). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (shipment create/cancel, plan
    create/submit)."""
    return build_user_headers(user_id, "CustomerRep")
