"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For entity_backed roles (AirlineRep) the shared constant is a
# fallback only; ownership-gated calls must use make_airline_rep_headers with
# the actual airline id.
TEST_USERS = {
    "station_admin_headers": build_user_headers("test-station-admin-1", "StationAdmin"),
    "airline_rep_headers": build_user_headers("test-airline-rep-1", "AirlineRep"),
    "pad_operator_headers": build_user_headers("test-pad-operator-1", "PadOperator"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "environmental_officer_headers": build_user_headers(
        "test-environmental-officer-1", "EnvironmentalOfficer"
    ),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
}


def make_airline_rep_headers(user_id: str) -> dict:
    """For AirlineRep (entity_backed:Airline). Pass the actual Airline.id as
    user_id whenever the call is ownership-gated (own requests, own invoices,
    own airline record)."""
    return build_user_headers(user_id, "AirlineRep")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (opaque). Use a distinct user_id per inspector when a
    test needs segregation-of-duties separation (e.g. insp-1 vs insp-2)."""
    return build_user_headers(user_id, "Inspector")


def make_environmental_officer_headers(user_id: str) -> dict:
    """For EnvironmentalOfficer (opaque). Use a distinct user_id per officer
    when a test needs segregation-of-duties separation (e.g. eo-1 vs eo-2)."""
    return build_user_headers(user_id, "EnvironmentalOfficer")
