"""Order authorization: segregation of duties, optimistic concurrency on the
patient version, and coinsurance rounding at invoice.

Covers PRD §2.6 (OCC), §2.9 (segregation of duties), §3.5 (authorize/ship/invoice).
"""
import pytest

from test_helpers import (
    authorize_order,
    build_user_headers,
    clinical_clear,
    create_cleared_order,
    create_order_for_plan,
    current_patient_version,
    deliver_order,
    expected_coinsurance_share,
    finalize_compliant_report,
    get_patient,
    invoice_order,
    occ_payload,
    setup_therapy_patient,
    ship_order,
    validate_error,
    validate_success,
)

RT_SAME_AS_CLEARER = build_user_headers("rt-1", "BillingSpecialist")


class TestSegregationOfDutiesVsStaleVersion:
    """Authorize checks run state, then SoD, then OCC — SoD beats staleness."""

    def test_sod_and_stale_version_reports_sod(
            self, api, billing_specialist_headers):
        """PRD §3.5: "its checks run in this order: the order must be in
        `PENDING_PAYER_AUTH` with fulfillment still `NOT_READY`
        (`ERR_ORDER_NOT_PENDING_AUTH`); then segregation of duties — the
        authorizer's `X-User-ID` must differ from `clinical_cleared_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`); then the optimistic-concurrency check of
        §2.6"

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_stale_version_on_authorize
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        plan = ctx["plans"]["TUBING"]

        stale_version = current_patient_version(patient["id"])
        order = create_order_for_plan(patient["id"], plan,
                                      expected_patient_version=stale_version)
        clinical_clear(order["id"], user_id="rt-1")

        # Advance Patient.version so the authorize snapshot is genuinely stale:
        # finalization settles the patient record (PRD §3.4) and §2.4 increments
        # version on any side effect. Compliant report keeps therapy ACTIVE.
        finalize_compliant_report(patient["id"], ctx["enrollment"]["id"],
                                  window_end_on="2026-08-30",
                                  nights_reported=30, compliant_nights=28)
        assert current_patient_version(patient["id"]) > stale_version

        # Same operator id as the clearing clinician, acting as BillingSpecialist.
        res = api.authorize_order(order["id"], occ_payload(stale_version),
                                  RT_SAME_AS_CLEARER)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    def test_sod_fires_even_when_version_stale_from_order_event(
            self, api, billing_specialist_headers):
        """PRD §2.9: "The system enforces this by recording the clearing
        clinician's opaque user id at clearance time and comparing it against
        the authorizer's identity at authorization time; a match is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_stale_version_on_authorize
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        plans = ctx["plans"]

        version_pre = current_patient_version(patient["id"])

        # Order A: full path through authorize, which increments Patient.version.
        order_a = create_cleared_order(patient["id"], plans["FILTER"],
                                       clearer_id="rt-1")
        authorize_order(order_a["id"], patient["id"], user_id="bs-1")
        assert current_patient_version(patient["id"]) == version_pre + 1

        # Order B: created and cleared after A's authorization; authorize
        # attempted by the clearing clinician with the stale pre-A version.
        order_b = create_cleared_order(patient["id"], plans["TUBING"],
                                       clearer_id="rt-1")
        res = api.authorize_order(order_b["id"], occ_payload(version_pre),
                                  RT_SAME_AS_CLEARER)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


class TestOptimisticConcurrency:
    def test_authorize_with_stale_patient_version_rejected(
            self, api, billing_specialist_headers):
        """PRD §2.6: "If that value does not equal the patient's current
        `version` at the moment the request is evaluated — because an adherence
        finalization, a mask-exchange completion, a discontinuation, or another
        order event has advanced the patient record since the client last read
        it — the request is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP
        412)."

        Design: Corner/errors/error_stale_patient_version
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        filter_plan = ctx["plans"]["FILTER"]

        version_pre = current_patient_version(patient["id"])

        # Order A authorizes and bumps Patient.version.
        order_a = create_cleared_order(patient["id"], filter_plan,
                                       clearer_id="rt-1")
        authorize_order(order_a["id"], patient["id"], user_id="bs-1",
                        expected_patient_version=version_pre)

        # Order B: state check passes (PENDING_PAYER_AUTH) and SoD passes
        # (different operator); only the OCC check fails.
        order_b = create_cleared_order(patient["id"], filter_plan,
                                       clearer_id="rt-1")
        res = api.authorize_order(order_b["id"], occ_payload(version_pre),
                                  billing_specialist_headers)
        validate_error(res, "ERR_STALE_PATIENT_VERSION", expected_status=412)

    def test_authorize_with_current_version_succeeds_and_increments(
            self, api, billing_specialist_headers):
        """PRD §3.5: "A successful authorization moves `auth_status` to
        `AUTHORIZED` and `fulfillment_status` to `READY_TO_SHIP`, snapshots the
        payer's fee schedule into the order's `unit_allowable_cents`, records
        the authorizer in `authorized_by_user_id`, and **increments the
        patient's `version` by one**"

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        order = create_cleared_order(patient["id"], ctx["plans"]["FILTER"],
                                     clearer_id="rt-1")
        version_pre = current_patient_version(patient["id"])

        authorized = validate_success(api.authorize_order(
            order["id"], occ_payload(version_pre), billing_specialist_headers))
        assert authorized["auth_status"] == "AUTHORIZED"
        assert authorized["fulfillment_status"] == "READY_TO_SHIP"
        assert authorized["authorized_by_user_id"] == "bs-1"
        assert isinstance(authorized["unit_allowable_cents"], int)

        assert current_patient_version(patient["id"]) == version_pre + 1

    def test_ship_with_stale_patient_version_rejected(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "it carries the same `expected_patient_version` OCC check
        — evaluated before the readiness checks — with
        `ERR_STALE_PATIENT_VERSION` on mismatch."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_ship
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        version_pre = current_patient_version(patient["id"])
        order = create_order_for_plan(patient["id"], ctx["plans"]["FILTER"],
                                      expected_patient_version=version_pre)
        clinical_clear(order["id"], user_id="rt-1")
        authorize_order(order["id"], patient["id"], user_id="bs-1",
                        expected_patient_version=version_pre)
        # Authorization advanced Patient.version past version_pre.
        assert current_patient_version(patient["id"]) == version_pre + 1

        res = api.ship_order(order["id"], occ_payload(version_pre),
                             intake_coordinator_headers)
        validate_error(res, "ERR_STALE_PATIENT_VERSION", expected_status=412)


class TestCoinsuranceRoundingOrder:
    """Per-line rounding: round the line total after multiplication."""

    def _invoiced_order(self, api, component="CUSHION"):
        """Drive one order to INVOICED; returns (patient_id, invoiced order)."""
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        plan = ctx["plans"][component]
        order = create_cleared_order(patient["id"], plan, clearer_id="rt-1")
        authorized = authorize_order(order["id"], patient["id"], user_id="bs-1")
        unit_allowable = authorized["unit_allowable_cents"]
        ship_order(order["id"], patient["id"])
        deliver_order(order["id"])
        invoiced = invoice_order(order["id"])
        return patient["id"], invoiced, unit_allowable

    def test_patient_share_rounds_line_total_not_per_unit(self, api):
        """PRD §3.5: "The line total is the order's `unit_allowable_cents`
        multiplied by its `requested_quantity`; the patient's share, stored in
        `patient_responsibility_cents`, is twenty percent of that line total,
        rounded half-up to a whole cent. Rounding applies to the line total
        after multiplication — never per unit."

        Design: Difficulty/combinatorial_formula/coinsurance_line_total_rounding_order
        """
        patient_id, invoiced, unit_allowable = self._invoiced_order(api)
        expected = expected_coinsurance_share(unit_allowable,
                                              invoiced["requested_quantity"])
        assert invoiced["patient_responsibility_cents"] == expected, (
            f"per-line rounding: round_half_up({unit_allowable} * "
            f"{invoiced['requested_quantity']} * 0.20) = {expected}, got "
            f"{invoiced['patient_responsibility_cents']}")

    def test_invoice_share_added_to_outstanding_balance(self, api):
        """PRD §3.5: "The computed share is added to the patient's
        `outstanding_balance_cents`, which in general aggregates the
        `patient_responsibility_cents` of all the patient's orders in
        `INVOICED` status, less any payments applied."

        Design: Difficulty/combinatorial_formula/coinsurance_line_total_rounding_order
        """
        patient_id, invoiced, _ = self._invoiced_order(api)
        patient = get_patient(patient_id)
        assert patient["outstanding_balance_cents"] == \
            invoiced["patient_responsibility_cents"]
