"""Role authorization, carrier ownership, and segregation-of-duties on adjudication.

Corner (breadth) translations from the `rbac` section.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_inspection_finalized_oos,
    setup_overweight_citation_assessed,
    setup_overweight_citation_contested,
    create_carrier,
    make_carrier_rep_headers,
    make_officer_headers,
)

SCREENER = TEST_USERS["screener_headers"]


def test_screener_cannot_issue_citation(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the targeted
    operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/screener_cannot_issue_citation_returns_403
    """
    d = setup_inspection_finalized_oos(
        severity_weight=5, carrier_overrides={"usdot_number": "DOT-C18", "legal_name": "Corner Eighteen"},
        station_overrides={"name": "S18", "state_code": "CA"})
    resp = api.create_citation(
        {"inspection_id": d["inspection"]["id"], "carrier_id": d["carrier"]["id"], "kind": "OVERWEIGHT"},
        SCREENER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_carrier_rep_cannot_settle_foreign_citation(api):
    """PRD §2.1: "A `CarrierRep` who acts on a carrier, driver, or citation that does not
    belong to their own carrier is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/carrierrep_settle_foreign_citation_returns_403
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-C19A", "legal_name": "Corner 19A"},
        station_overrides={"name": "S19", "state_code": "CA"})
    carrier_b = create_carrier(usdot_number="DOT-C19B", legal_name="Corner 19B")
    resp = api.settle_citation(
        d["citation"]["id"], {"payment_cents": 145000}, make_carrier_rep_headers(carrier_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_issuing_officer_cannot_adjudicate_own_citation(api):
    """PRD §3.8: "Segregation of duties governs this step: the adjudicating officer's
    `X-User-ID` must differ from the citation's `issued_by_user_id`, and if they are the
    same the request is rejected with `ERR_SOD_CONFLICT`."

    Design: Corner/rbac/adjudicate_same_officer_returns_403_sod
    """
    d = setup_overweight_citation_contested(
        officer_id="officer-1",
        carrier_overrides={"usdot_number": "DOT-C20", "legal_name": "Corner Twenty"},
        station_overrides={"name": "S20", "state_code": "CA"})
    resp = api.adjudicate_citation(
        d["citation"]["id"],
        {"result": "UPHOLD", "certified_gross_lbs": 86000, "certified_axle_lbs": 21000},
        make_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)
