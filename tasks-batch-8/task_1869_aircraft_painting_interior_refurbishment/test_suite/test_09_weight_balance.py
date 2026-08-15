"""Weight & balance: dual-variant film math, sign-off gate, SoD (PRD §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_scheme,
    create_and_approve_scheme,
    create_engagement,
    create_scheme,
    get_program,
    make_customer_rep_headers,
    make_quality_inspector_headers,
    prepare_weight_record,
    sign_off_weight_record,
    submit_scheme,
    validate_error,
    validate_paginated,
    validate_success,
)

_QI = TEST_USERS["quality_inspector_headers"]
_PM = TEST_USERS["program_manager_headers"]


def _quoted_with_approved_scheme(api=None):
    """QUOTED program + APPROVED scheme (2400 sqft, 2 coats, stripe 0.10; no
    assessment recorded, so the STRIP factor 1.0 applies)."""
    ctx = create_engagement()
    ctx["scheme"] = create_and_approve_scheme(
        ctx["program"]["id"], ctx["customer"]["id"]
    )
    return ctx


class TestWeightDeltaVariants:
    def test_provisional_variant_uses_estimated_film_factor(self, api):
        """PRD §3.9: "The paint film weight `film_lbs` is the pinned scheme's
        `painted_area_sqft` multiplied by its `coat_count`, multiplied by a
        film factor, multiplied by one plus the scheme's `stripe_pct`; the film
        factor is 0.006 pounds per square foot per coat for a `PROVISIONAL`
        record and 0.0058 for a `FINAL` record, and when the program's current
        decided assessment is `SCUFF` the whole film figure is scaled by 0.85.
        The `delta_lbs` is then the installed weight minus the removal weight
        plus the film weight, rounded half-up to one decimal place".

        Design: Difficulty/dual_variant_calc/weight_delta_provisional_vs_final_diverge
        """
        ctx = _quoted_with_approved_scheme()
        record = prepare_weight_record(
            ctx["program"]["id"], ctx["scheme"]["id"],
            variant="PROVISIONAL", removal=100.0, installed=110.0,
        )
        # film = 2400 x 2 x 0.006 x 1.1 = 31.68; delta = 10.0 + 31.68 = 41.68 -> 41.7
        assert record["film_lbs"] == pytest.approx(31.68, abs=1e-6)
        assert record["delta_lbs"] == pytest.approx(41.7, abs=1e-9)

    def test_final_variant_uses_measured_film_factor_and_diverges(self, api):
        """PRD §3.9: "the film factor is 0.006 pounds per square foot per coat
        for a `PROVISIONAL` record and 0.0058 for a `FINAL` record" — for
        identical area/coats the provisional delta differs from final.

        Design: Difficulty/dual_variant_calc/weight_delta_provisional_vs_final_diverge
        """
        ctx = _quoted_with_approved_scheme()
        provisional = prepare_weight_record(
            ctx["program"]["id"], ctx["scheme"]["id"],
            variant="PROVISIONAL", removal=100.0, installed=110.0,
        )
        final = prepare_weight_record(
            ctx["program"]["id"], ctx["scheme"]["id"],
            variant="FINAL", removal=100.0, installed=108.0,
        )
        # film = 2400 x 2 x 0.0058 x 1.1 = 30.624; delta = 8.0 + 30.624 = 38.624 -> 38.6
        assert final["film_lbs"] == pytest.approx(30.624, abs=1e-6)
        assert final["delta_lbs"] == pytest.approx(38.6, abs=1e-9)
        assert provisional["delta_lbs"] != final["delta_lbs"], (
            "variant selection, not input, drives the difference"
        )


class TestDeltaBoundaryAtSignOff:
    def test_delta_rounding_to_exact_limit_signs_off(self, api):
        """PRD §3.1: "the gate is strict — a delta whose absolute value exceeds
        `max_delta_lbs` requires the acknowledgment, while one exactly equal to
        it does not." PRD §2.9: "any gate that compares a delta against a limit
        compares the rounded stored value."

        Design: Difficulty/boundary_precision_check/weight_delta_exact_limit_allowed
        """
        ctx = _quoted_with_approved_scheme()
        # raw delta 119.4 - 100 + 30.624 = 50.024 -> stored 50.0 == max 50.0.
        record = prepare_weight_record(
            ctx["program"]["id"], ctx["scheme"]["id"],
            variant="FINAL", removal=100.0, installed=119.4,
        )
        assert record["delta_lbs"] == pytest.approx(50.0, abs=1e-9)
        signed = sign_off_weight_record(record["id"])
        assert signed["status"] == "SIGNED_OFF", "the rounded value equals the limit"

    def test_delta_one_tenth_over_limit_rejected(self, api):
        """PRD §3.9: "the absolute value of the rounded `delta_lbs` must be at
        most the aircraft's `max_delta_lbs`, unless an `APPROVED` change order
        of kind `WEIGHT_ACK` exists whose `acknowledges_weight_record_id` is
        this record — otherwise the sign-off is rejected with
        `ERR_WEIGHT_DELTA_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/weight_delta_exact_limit_allowed
        """
        ctx = _quoted_with_approved_scheme()
        # raw delta 119.5 - 100 + 30.624 = 50.124 -> stored 50.1 > 50.0.
        record = prepare_weight_record(
            ctx["program"]["id"], ctx["scheme"]["id"],
            variant="FINAL", removal=100.0, installed=119.5,
        )
        assert record["delta_lbs"] == pytest.approx(50.1, abs=1e-9)
        resp = api.sign_off_weight_balance_record(
            record["id"], make_quality_inspector_headers("qi-1")
        )
        validate_error(resp, ApiErrorId.ERR_WEIGHT_DELTA_EXCEEDED)


class TestSignOffSupersedePair:
    def test_second_signoff_supersedes_prior_record(self, api):
        """PRD §3.9: "When a record is signed off, any previously `SIGNED_OFF`
        record of the same program and the same `variant` is automatically
        superseded, keeping the count of signed-off records per program and
        variant at most one."

        Design: Difficulty/compensating_invariant/weight_signoff_supersede_single_signed
        """
        ctx = _quoted_with_approved_scheme()
        first = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
        signed1 = sign_off_weight_record(first["id"])
        assert signed1["status"] == "SIGNED_OFF"

        second = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
        signed2 = sign_off_weight_record(second["id"])
        assert signed2["status"] == "SIGNED_OFF"

        first_after = validate_success(api.get_weight_balance_record(first["id"], _QI))
        assert first_after["status"] == "SUPERSEDED", (
            "compensating auto-transition on the second sign-off"
        )

    def test_exactly_one_signed_off_record_per_program_and_variant(self, api):
        """PRD §3.9: "When a record is signed off, any previously `SIGNED_OFF`
        record of the same program and the same `variant` is automatically
        superseded, keeping the count of signed-off records per program and
        variant at most one."

        Design: Difficulty/compensating_invariant/weight_signoff_supersede_single_signed
        """
        ctx = _quoted_with_approved_scheme()
        first = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
        sign_off_weight_record(first["id"])
        second = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
        sign_off_weight_record(second["id"])

        records, meta = validate_paginated(api.list_weight_balance_records(_QI))
        assert meta["total_count"] == 2
        signed_off = [r for r in records if r["status"] == "SIGNED_OFF"]
        assert len(signed_off) == 1, "signed-off count per (program, variant) is one"
        assert signed_off[0]["id"] == second["id"]


class TestSchemePinEnforcement:
    def test_unapproved_scheme_reference_rejected(self, api):
        """PRD §3.9: a record is prepared "naming the `scheme_id` — which must
        equal the program's currently pinned `approved_scheme_id` at creation
        time (`ERR_REFERENTIAL_INTEGRITY` otherwise)".

        Design: Corner/validations/wbr_unapproved_scheme_rejected
        """
        ctx = create_engagement()
        scheme = create_scheme(ctx["program"]["id"])
        submit_scheme(scheme["id"])  # SUBMITTED, never approved
        resp = api.create_weight_balance_record(
            {
                "program_id": ctx["program"]["id"],
                "scheme_id": scheme["id"],
                "variant": "PROVISIONAL",
                "removal_weight_lbs": 100.0,
                "installed_weight_lbs": 110.0,
            },
            TEST_USERS["shop_technician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_superseded_scheme_pin_rejected(self, api):
        """PRD §3.9: "naming the `scheme_id` — which must equal the program's
        currently pinned `approved_scheme_id` at creation time
        (`ERR_REFERENTIAL_INTEGRITY` otherwise)". PRD §3.3: "a later
        superseding approval re-baselines that ground truth."

        Design: Corner/cross_cutting_complexity_layers/wbr_rejects_superseded_scheme_pin
        """
        ctx = create_engagement()
        scheme_a = create_and_approve_scheme(ctx["program"]["id"], ctx["customer"]["id"])
        scheme_b = create_scheme(ctx["program"]["id"], drawing_ref="DWG-1869-B")
        submit_scheme(scheme_b["id"])
        approve_scheme(
            scheme_b["id"], ctx["customer"]["id"],
            get_program(ctx["program"]["id"])["version"],
        )
        resp = api.create_weight_balance_record(
            {
                "program_id": ctx["program"]["id"],
                "scheme_id": scheme_a["id"],  # SUPERSEDED — no longer the pin
                "variant": "FINAL",
                "removal_weight_lbs": 100.0,
                "installed_weight_lbs": 108.0,
            },
            TEST_USERS["shop_technician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestSegregationOfDuties:
    def test_preparer_cannot_sign_off_own_record(self, api):
        """PRD §3.9: "First, segregation of duties: the signing `X-User-ID`
        must differ from the record's `prepared_by_user_id` — a match is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/weight_signoff_segregation_of_duties
        """
        ctx = _quoted_with_approved_scheme()
        record = prepare_weight_record(
            ctx["program"]["id"], ctx["scheme"]["id"], preparer="tech-1"
        )
        assert record["prepared_by_user_id"] == "tech-1"

        same_user = api.sign_off_weight_balance_record(
            record["id"], make_quality_inspector_headers("tech-1")
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other = validate_success(
            api.sign_off_weight_balance_record(
                record["id"], make_quality_inspector_headers("qi-1")
            )
        )
        assert other["status"] == "SIGNED_OFF"
