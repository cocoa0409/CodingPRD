"""Reduced-fare approval, purchase precedence, and optimistic concurrency on applications."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_passenger_headers,
    create_application_payload,
)
from test_helpers import fixtures as fx


# ==========================================================================
# priority_pair_validation_conflict / purchase_referential_beats_fiscal
# ==========================================================================

def test_purchase_reduced_ineligible_beats_wallet_shortfall(api):
    """PRD 2.7: "then (6) business-referential rules such as reduced-fare eligibility and
    inspection/ticket linkage, then (7) time-window rules such as activation deadlines and
    refund windows, then (8) remaining business constraints such as evasion or upgrade
    preconditions, then (9) fiscal sufficiency of the wallet"
    PRD 3.3: "the passenger must currently hold a reduced-fare category other than none and
    a `reduced_fare_valid_until` that is at or after the current clock instant; otherwise
    the purchase is rejected with `ERR_REDUCED_FARE_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/purchase_referential_beats_fiscal
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)  # NONE eligibility, wallet 0
    resp = api.create_ticket(
        {"passenger_id": pax["id"], "fare_product_id": fp["id"], "travel_period": "PEAK",
         "use_reduced_fare": True, "wallet_apply_cents": 100},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REDUCED_FARE_NOT_ELIGIBLE.value)


def test_purchase_wallet_shortfall_fires_when_eligibility_passes(api):
    """PRD 2.8: "Any attempt to spend more wallet credit than the passenger currently holds
    is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 402). This guard applies both when
    purchasing a ticket and when exchanging one."

    Design: Difficulty/priority_pair_validation_conflict/purchase_referential_beats_fiscal
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)  # wallet 0, no reduced fare requested
    resp = api.create_ticket(
        {"passenger_id": pax["id"], "fare_product_id": fp["id"], "travel_period": "PEAK",
         "wallet_apply_cents": 100},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)


# ==========================================================================
# Corner: SENIOR age gate
# ==========================================================================

def test_approve_senior_under_age_returns_age_not_met(api):
    """PRD 3.2: "For a `SENIOR` application, the passenger's age computed against the logical
    clock must be at least 65 years; if the rider is younger than 65, approval fails with
    `ERR_SENIOR_AGE_NOT_MET`."

    Design: Corner/validations/approve_senior_under_age_returns_age_not_met
    """
    fx.set_clock(api)  # 2026-03-01
    pax = fx.create_passenger(api, dob="2000-01-01")  # age 26
    app = fx.submit_application(api, pax["id"], "SENIOR", pax["version"])
    resp = api.approve_application(app["id"], fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_SENIOR_AGE_NOT_MET.value)


# ==========================================================================
# cross_cutting_complexity_layers / OCC on application create
# ==========================================================================

def test_occ_stale_passenger_version_on_second_application(api):
    """PRD 2.10: "If that value does not equal the passenger's current `version` at the
    moment the create is processed"
    PRD 2.10: "the create is rejected with `ERR_STALE_PASSENGER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_passenger_version_on_second_application
    """
    fx.set_clock(api)
    pax = fx.create_passenger(api)  # version 1
    fx.submit_application(api, pax["id"], "STUDENT", pax["version"])  # advances version to 2
    resp = api.create_application(
        create_application_payload(pax["id"], "STUDENT", pax["version"], proof_document_ref="d2"),
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PASSENGER_VERSION.value)


def test_occ_fresh_version_supersedes_prior_application(api):
    """PRD 3.2: "A fresh application legitimately supersedes any earlier application by the
    same passenger that is still in `SUBMITTED` status: on create, that prior application
    moves to `SUPERSEDED` and the passenger's `version` advances."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_version_supersedes_prior_application
    """
    fx.set_clock(api)
    pax = fx.create_passenger(api)  # version 1
    app1 = fx.submit_application(api, pax["id"], "STUDENT", pax["version"])  # version -> 2
    current_version = fx.get_passenger(api, pax["id"])["version"]
    app2 = validate_success(
        api.create_application(
            create_application_payload(pax["id"], "DISABILITY", current_version,
                                       proof_document_ref="d2"),
            make_passenger_headers(pax["id"]),
        ),
        201,
    )
    assert app2["status"] == "SUBMITTED"
    assert fx.get_application(api, app1["id"])["status"] == "SUPERSEDED"
