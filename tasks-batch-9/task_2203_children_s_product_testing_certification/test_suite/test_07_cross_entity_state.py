"""Transitions on one row that are gated entirely by the state of a neighbour."""

from test_helpers import ApiErrorId, fixtures as fx, validate_error, validate_success
from test_helpers.test_users import (
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_laboratory_user_headers,
)


FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
}

ATTESTATION_EXPIRY = "2026-09-01T00:00:00Z"


def _two_orders_at_one_laboratory_env(api):
    """Two scheduled orders whose laboratory's attestation expires before the second."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        attestation_valid_through=ATTESTATION_EXPIRY,
        accreditation_overrides=[
            {"valid_from": "2026-01-01T00:00:00Z", "valid_through": "2027-01-01T00:00:00Z"}
        ],
        plan_overrides={"plan_type": "INITIAL"},
    )
    laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
    assert laboratory["operational_state"] == "ACTIVE"
    assert laboratory["influence_attestation_state"] == "CURRENT"
    assert laboratory["influence_attestation_valid_through"] == ATTESTATION_EXPIRY

    def book(window_start, window_end):
        return fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=1,
            window_start=window_start,
            window_end=window_end,
        )

    env["first_order"] = book("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z")
    env["later_order"] = book("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z")
    assert env["first_order"]["order_state"] == "SCHEDULED"
    assert env["later_order"]["order_state"] == "SCHEDULED"
    return env


class TestStartTestingDependsOnTheLaboratory:
    """The order is faultless; only its laboratory blocks the move."""

    def test_barring_the_laboratory_blocks_a_faultless_scheduled_order(self, api):
        """PRD 2.10: "A laboratory whose `operational_state` is `BARRED` may not be
        assigned new work and may not take an order into testing; attempts are refused
        with `ERR_LAB_BARRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_test_order_start_blocked_by_laboratory_operational_state_and_by_attestation_expiry
        """
        env = _two_orders_at_one_laboratory_env(api)
        order = env["first_order"]
        lab_id = env["laboratory"]["id"]

        barred = fx.set_lab_state(api, lab_id, "BARRED")
        assert barred["operational_state"] == "BARRED"

        validate_error(
            api.start_testing(
                order["id"], headers=make_laboratory_user_headers(lab_id)
            ),
            ApiErrorId.LAB_BARRED.value,
            422,
        )
        unchanged = fx.get_order(api, order["id"])
        assert unchanged["order_state"] == "SCHEDULED"
        assert unchanged["version"] == order["version"]

    def test_reinstating_the_laboratory_unblocks_the_identical_request(self, api):
        """PRD 3.2: "The same administrator may bar or reinstate a laboratory by
        submitting a new `operational_state` value, which is stored directly and likewise
        increments `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_test_order_start_blocked_by_laboratory_operational_state_and_by_attestation_expiry
        """
        env = _two_orders_at_one_laboratory_env(api)
        order = env["first_order"]
        lab_id = env["laboratory"]["id"]
        fx.set_lab_state(api, lab_id, "BARRED")
        api.start_testing(order["id"], headers=make_laboratory_user_headers(lab_id))

        restored = fx.set_lab_state(api, lab_id, "ACTIVE")
        assert restored["operational_state"] == "ACTIVE"

        started = fx.start_order(api, order["id"], lab_id)
        assert started["order_state"] == "IN_TESTING"

    def test_the_clock_alone_expires_the_attestation_and_blocks_the_start(self, api):
        """PRD 2.10: "An attestation that is `MISSING`, that has been marked `EXPIRED`,
        or whose validity instant is at or before the logical clock, blocks the operation
        with `ERR_UNDUE_INFLUENCE_ATTESTATION_MISSING` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_test_order_start_blocked_by_laboratory_operational_state_and_by_attestation_expiry
        """
        env = _two_orders_at_one_laboratory_env(api)
        lab_id = env["laboratory"]["id"]
        before = fx.get_laboratory(api, lab_id)

        fx.set_clock(api, "2026-09-02T00:00:00Z")
        validate_error(
            api.start_testing(
                env["later_order"]["id"], headers=make_laboratory_user_headers(lab_id)
            ),
            ApiErrorId.UNDUE_INFLUENCE_ATTESTATION_MISSING.value,
            422,
        )

        # Moving the clock wrote nothing to the laboratory row.
        after = fx.get_laboratory(api, lab_id)
        assert after["version"] == before["version"]
        assert after["operational_state"] == "ACTIVE"
        assert after["influence_attestation_valid_through"] == ATTESTATION_EXPIRY
        assert fx.get_order(api, env["later_order"]["id"])["order_state"] == "SCHEDULED"

    def test_renewing_the_attestation_closes_the_dependency_again(self, api):
        """PRD 3.2: "Before any work may be assigned, an administrator records the
        laboratory's standing undue-influence prevention attestation by supplying an
        `attestation_valid_through` instant. Doing so sets `influence_attestation_state`
        to `CURRENT`, writes the supplied instant into
        `influence_attestation_valid_through`, and increments the laboratory's `version`
        by 1."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_test_order_start_blocked_by_laboratory_operational_state_and_by_attestation_expiry
        """
        env = _two_orders_at_one_laboratory_env(api)
        lab_id = env["laboratory"]["id"]
        fx.set_clock(api, "2026-09-02T00:00:00Z")
        api.start_testing(
            env["later_order"]["id"], headers=make_laboratory_user_headers(lab_id)
        )

        renewed = fx.attest(api, lab_id, "2027-06-01T00:00:00Z")
        assert renewed["influence_attestation_state"] == "CURRENT"
        assert renewed["influence_attestation_valid_through"] == "2027-06-01T00:00:00Z"

        started = fx.start_order(api, env["later_order"]["id"], lab_id)
        assert started["order_state"] == "IN_TESTING"


def _two_held_batches_env(api):
    """A drafted certificate over two label-compliant held batches of 300 and 200 units."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.evidence_complete_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
    )
    product = fx.get_product(api, env["product"]["id"])
    assert product["certification_state"] == "EVIDENCE_COMPLETE"
    assert product["risk_weighted_gap_score"] == 0
    assert product["compliance_posture"] == "CLEARED"

    certificate = fx.draft_certificate(
        api, product["id"], product["version"], manufacture_date_month="2026-08"
    )
    assert certificate["content_completeness_pct"] == 100
    assert certificate["issuance_status"] == "DRAFT"
    assert certificate["accompaniment_status"] == "NOT_FURNISHED"

    batches = [
        fx.create_batch(
            api,
            product["id"],
            certificate["id"],
            batch_code=code,
            produced_on="2026-08-01T00:00:00Z",
            quantity=quantity,
        )
        for code, quantity in (("HELDA1-000301", 300), ("HELDA1-000302", 200))
    ]
    for batch in batches:
        assert batch["distribution_state"] == "HELD"
        assert batch["tracking_label_compliant"] is True
    env["certificate"] = certificate
    env["first_batch"], env["second_batch"] = batches
    return env


class TestBatchReleaseDependsOnBothCertificateAxes:
    """Release reads the certificate's two axes afresh on every attempt."""

    def test_release_is_refused_while_the_certificate_is_still_a_draft(self, api):
        """PRD 3.8: "Releasing a held batch for distribution is the moment every upstream
        control converges, and it demands four things at once beyond the batch being
        `HELD`: `tracking_label_compliant` is true, or the release is refused with
        `ERR_TRACKING_LABEL_NONCOMPLIANT`; the referenced certificate's `issuance_status`
        is `ISSUED` **and** its `accompaniment_status` is `FURNISHED`, both axes satisfied
        simultaneously, or the release is refused with `ERR_CERTIFICATE_STATE_INVALID`;
        and the owning product's `compliance_posture` is `CLEARED`, or the release is
        refused with `ERR_PRODUCT_POSTURE_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_batch_release_blocked_until_certificate_satisfies_both_parallel_axes
        """
        env = _two_held_batches_env(api)
        validate_error(
            api.release_batch(env["first_batch"]["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        batch = fx.get_batch(api, env["first_batch"]["id"])
        assert batch["distribution_state"] == "HELD"
        assert batch["released_at"] is None

    def test_one_satisfied_axis_is_not_enough_to_release(self, api):
        """PRD 3.7: "Issuance leaves `accompaniment_status` untouched at `NOT_FURNISHED` —
        the newly issued certificate does not automatically accompany anything."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_batch_release_blocked_until_certificate_satisfies_both_parallel_axes
        """
        env = _two_held_batches_env(api)
        api.release_batch(env["first_batch"]["id"], headers=MANAGER_HEADERS)

        issued = validate_success(
            api.issue_certificate(env["certificate"]["id"], headers=OFFICER_HEADERS), 200
        )
        assert issued["issuance_status"] == "ISSUED"
        assert issued["accompaniment_status"] == "NOT_FURNISHED"

        product = fx.get_product(api, env["product"]["id"])
        assert product["compliance_posture"] == "CLEARED"
        assert fx.get_batch(api, env["first_batch"]["id"])["tracking_label_compliant"] is True

        validate_error(
            api.release_batch(env["first_batch"]["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )

    def test_release_succeeds_once_both_axes_are_satisfied(self, api):
        """PRD 3.8: "On success the batch moves `HELD → RELEASED`, `released_at` is
        stamped with the logical clock, and the batch's `quantity` moves from the
        product's `units_held` to its `units_released`; both the batch's and the
        product's `version` increment by 1."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_batch_release_blocked_until_certificate_satisfies_both_parallel_axes
        """
        env = _two_held_batches_env(api)
        fx.issue_certificate(api, env["certificate"]["id"])
        fx.furnish_certificate(api, env["certificate"]["id"])

        released = fx.release_batch(api, env["first_batch"]["id"])
        assert released["distribution_state"] == "RELEASED"
        assert released["released_at"] == "2026-08-01T00:00:00Z"

        product = fx.get_product(api, env["product"]["id"])
        assert product["units_held"] == 200
        assert product["units_released"] == 300

    def test_recalling_accompaniment_reblocks_the_second_batch(self, api):
        """PRD 3.7: "The same manager may later withdraw the certificate from shipments,
        moving it `FURNISHED → RECALLED_FROM_SHIPMENTS`, which blocks further batch
        releases against it; `issuance_status` is explicitly left unchanged by that move,
        so an `ISSUED` certificate stays `ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_batch_release_blocked_until_certificate_satisfies_both_parallel_axes
        """
        env = _two_held_batches_env(api)
        fx.issue_certificate(api, env["certificate"]["id"])
        fx.furnish_certificate(api, env["certificate"]["id"])
        fx.release_batch(api, env["first_batch"]["id"])

        recalled = fx.recall_accompaniment(api, env["certificate"]["id"])
        assert recalled["accompaniment_status"] == "RECALLED_FROM_SHIPMENTS"
        assert recalled["issuance_status"] == "ISSUED"

        validate_error(
            api.release_batch(env["second_batch"]["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        assert (
            fx.get_batch(api, env["first_batch"]["id"])["distribution_state"] == "RELEASED"
        )
        product = fx.get_product(api, env["product"]["id"])
        assert product["units_released"] == 300
        assert product["units_held"] == 200
