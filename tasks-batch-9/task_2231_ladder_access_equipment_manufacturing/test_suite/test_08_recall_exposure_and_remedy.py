"""Recall exposure accounting and the consumer remedy ledger."""

from test_helpers import (
    ApiErrorId,
    acknowledge_payload,
    api_client,
    assert_instant_equals,
    get_listing_record_data,
    get_product_data,
    get_recall_data,
    get_registration_data,
    notify_recall,
    setup_announced_recall,
    setup_shipping_product_with_registered_units,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

CONSUMER = TEST_USERS["consumer_headers"]


def _announced_recall(registration_count=2, produced_units=400):
    """A shipping model with one released lot, `registration_count`
    registrations against it, and an `ANNOUNCED` recall covering it."""
    ctx = setup_shipping_product_with_registered_units(
        registration_count=registration_count, produced_units=produced_units
    )
    recall = setup_announced_recall(ctx)
    return ctx, recall


class TestRecallExposureBases:
    def test_the_two_bases_count_units_and_registrations_over_the_same_lots(self):
        """PRD §3.9: "`exposure_units_shipped_basis` is the units-in-commerce
        figure published with the regulatory notice: it is the sum of
        `produced_units` across every lot in the in-scope set, so it sees every
        unit that left the plant, including unregistered ones."
        PRD §3.9: "`exposure_units_registered_basis` is the consumer-outreach
        figure that drives the remedy ledger: it is the count of consumer
        registrations whose `production_lot_id` is one of the in-scope lots and
        whose `registration_status` is `REGISTERED`, `NOTIFIED`, or
        `ACKNOWLEDGED`."

        Design: Difficulty/dual_variant_calc/recall_exposure_shipped_versus_registered_basis
        """
        _, recall = _announced_recall()

        assert recall["status"] == "ANNOUNCED"
        assert recall["exposure_units_shipped_basis"] == 400
        assert recall["exposure_units_registered_basis"] == 2
        assert (
            recall["exposure_units_registered_basis"]
            < recall["exposure_units_shipped_basis"]
        )
        assert_instant_equals(
            recall["announced_at"], "2026-08-01T00:00:00Z", "announced_at"
        )

    def test_notification_coverage_is_the_registered_share_of_the_shipped_basis(self):
        """PRD §3.9: "`notification_coverage_pct` is the registered basis divided
        by the shipped basis expressed as a percentage, rounded half up to two
        decimal places; when the shipped basis is 0 the calculation short-circuits
        to 0.00 rather than dividing."
        PRD §3.9: "sets `units_remedied` to 0 and `units_outstanding` to the
        registered basis, and stamps `recall_event_id` on every in-scope consumer
        registration whose `registration_status` is `REGISTERED`."

        Design: Difficulty/dual_variant_calc/recall_exposure_shipped_versus_registered_basis
        """
        ctx, recall = _announced_recall()

        # Two registrations against four hundred shipped units.
        assert float(recall["notification_coverage_pct"]) == 0.50
        assert recall["units_remedied"] == 0
        assert recall["units_outstanding"] == 2

        for registration in ctx["registrations"]:
            reread = get_registration_data(registration["id"])
            assert reread["recall_event_id"] == recall["id"]
            assert reread["registration_status"] == "REGISTERED", (
                "announcement stamps the recall without notifying anyone yet"
            )

    def test_announcement_reshapes_both_dimensions_and_withdraws_the_listing(self):
        """PRD §3.9: "It then reshapes the model in both dimensions at once:
        `market_status` moves to the terminal `RECALLED` from whichever of
        `RETAIL_RELEASED` or `STOP_SHIP` it held, with `market_status_changed_at`
        stamped; `design_status` moves `DESIGN_FROZEN` → the terminal
        `DESIGN_OBSOLETE`; every listing record of the model in `LISTED` or
        `SUSPENDED` moves to the terminal `WITHDRAWN` with `audit_due_at` cleared
        to null, after which no further audit campaign may be planned against that
        record"

        Design: Difficulty/dual_variant_calc/recall_exposure_shipped_versus_registered_basis
        """
        ctx, _ = _announced_recall()

        product = get_product_data(ctx["product"]["id"])
        assert product["market_status"] == "RECALLED"
        assert product["design_status"] == "DESIGN_OBSOLETE"
        assert_instant_equals(
            product["market_status_changed_at"],
            "2026-08-01T00:00:00Z",
            "market_status_changed_at",
        )

        record = get_listing_record_data(ctx["listing_record"]["id"])
        assert record["status"] == "WITHDRAWN"
        assert record["audit_due_at"] is None

    def test_lot_release_wins_the_retention_tie_against_the_recall_instant(self):
        """PRD §2.10: "When two or more candidates are exactly equal to the
        anchor, `retention_anchor_source` is decided by a fixed precedence:
        `LOT_RELEASE` first, then `INCIDENT_CLOSURE`, then `RECALL`, then
        `DESIGN_FREEZE`."
        PRD §2.10: "Otherwise the anchor is the latest of the candidates that are
        not null, and `dhf_retention_until` is that anchor plus seven calendar
        years."

        Design: Difficulty/dual_variant_calc/recall_exposure_shipped_versus_registered_basis
        """
        ctx, _ = _announced_recall()

        product = get_product_data(ctx["product"]["id"])

        # The lot release, the recall instant and the design freeze all sit on the
        # same instant, so the fixed precedence decides the source.
        assert_instant_equals(
            product["dhf_retention_until"],
            "2033-08-01T00:00:00Z",
            "dhf_retention_until",
        )
        assert product["retention_anchor_source"] == "LOT_RELEASE"


class TestAcknowledgementGatedOnNotification:
    def _single_registration_recall(self):
        ctx, recall = _announced_recall(registration_count=1)
        assert recall["exposure_units_shipped_basis"] == 400
        assert recall["exposure_units_registered_basis"] == 1
        # One registration against four hundred shipped units.
        assert float(recall["notification_coverage_pct"]) == 0.25
        return ctx, recall

    def test_acknowledgement_before_notification_is_rejected(self):
        """PRD §3.9: "The registration must be in `NOTIFIED`; one still
        `REGISTERED` or already `ACKNOWLEDGED` is rejected with
        `ERR_REGISTRATION_NOT_NOTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/recall_acknowledgement_gated_on_notification_state
        """
        ctx, recall = self._single_registration_recall()
        registration = ctx["registrations"][0]

        response = api_client.acknowledge_recall(
            registration["id"], acknowledge_payload("REPAIR_KIT"), CONSUMER
        )
        validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_NOTIFIED.value, 409)

        reread = get_registration_data(registration["id"])
        assert reread["registration_status"] == "REGISTERED"
        assert reread["acknowledged_at"] is None
        assert reread["remedy_choice"] is None
        assert get_recall_data(recall["id"])["units_remedied"] == 0

    def test_notification_moves_the_recall_and_its_registrations_forward(self):
        """PRD §3.9: "Notification moves the recall `ANNOUNCED` → `IN_PROGRESS`
        and may be performed by a `SafetyDirector` or a `ComplianceOfficer`; a
        recall that is not `ANNOUNCED` is rejected with
        `ERR_RECALL_STATE_INVALID`."
        PRD §3.9: "Every consumer registration stamped with this `recall_event_id`
        and still in `REGISTERED` moves `REGISTERED` → `NOTIFIED` with
        `notified_at` stamped at the logical clock."

        Design: Difficulty/cross_entity_state_dependency/recall_acknowledgement_gated_on_notification_state
        """
        ctx, recall = self._single_registration_recall()

        in_progress = notify_recall(recall["id"])

        assert in_progress["status"] == "IN_PROGRESS"
        reread = get_registration_data(ctx["registrations"][0]["id"])
        assert reread["registration_status"] == "NOTIFIED"
        assert_instant_equals(
            reread["notified_at"], "2026-08-01T00:00:00Z", "notified_at"
        )

    def test_acknowledgement_after_notification_settles_the_remedy_ledger(self):
        """PRD §3.9: "On success the registration moves `NOTIFIED` → the terminal
        `ACKNOWLEDGED`, `acknowledged_at` is stamped with the logical clock,
        `remedy_choice` is stored, the recall's `units_remedied` increases by one,
        and its `units_outstanding` decreases by one — so `units_remedied` plus
        `units_outstanding` always equals `exposure_units_registered_basis`."

        Design: Difficulty/cross_entity_state_dependency/recall_acknowledgement_gated_on_notification_state
        """
        ctx, recall = self._single_registration_recall()
        notify_recall(recall["id"])

        acknowledged = validate_success(
            api_client.acknowledge_recall(
                ctx["registrations"][0]["id"],
                acknowledge_payload("REPAIR_KIT"),
                CONSUMER,
            )
        )

        assert acknowledged["registration_status"] == "ACKNOWLEDGED"
        assert acknowledged["remedy_choice"] == "REPAIR_KIT"
        assert_instant_equals(
            acknowledged["acknowledged_at"], "2026-08-01T00:00:00Z", "acknowledged_at"
        )

        reread = get_recall_data(recall["id"])
        assert reread["units_remedied"] == 1
        assert reread["units_outstanding"] == 0
        assert (
            reread["units_remedied"] + reread["units_outstanding"]
            == reread["exposure_units_registered_basis"]
        )
