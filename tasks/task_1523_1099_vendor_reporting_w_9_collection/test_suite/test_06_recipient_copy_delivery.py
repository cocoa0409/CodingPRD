"""Recipient Copy B delivery: the parallel recipient_copy_status dimension,
deadline boundary, consent guard, and the postal bounce feed."""
import pytest

from test_helpers import (
    IRS,
    SPEC,
    ApiErrorId,
    create_matched_vendor,
    create_payment,
    create_tax_year,
    create_validated_return,
    generate_returns,
    get_single_return,
    make_tax_specialist_headers,
    make_tax_transmitter_headers,
    record_match,
    set_clock,
    submit_w9,
    validate_error,
    validate_success,
)


class TestCopyDeliveryGuards:
    def test_copy_delivery_deadline_boundary(self, api):
        """PRD §3.7: "Either channel requires the return's `federal_status` to be
        `VALIDATED`, `TRANSMITTED`, or `ACCEPTED` (otherwise
        `ERR_INVALID_STATE_TRANSITION`) and the logical clock to read at or before
        the year's `recipient_copy_deadline` (otherwise `ERR_COPY_DEADLINE_PASSED`)..."
        PRD §3.1: "a `recipient_copy_deadline`, the latest logical-clock instant at
        which recipient copy delivery is accepted, inclusive of that instant."

        Design: Corner/state_machines/c_copy_delivery_deadline_boundary
        """
        create_tax_year(recipient_copy_deadline="2026-01-31T00:00:00Z")
        _vendor, _payment, tax_return = create_validated_return(
            legal_name="Dl V", tin="369369369"
        )

        # At exactly the deadline (inclusive): delivery succeeds.
        set_clock("2026-01-31T00:00:00Z")
        delivered = validate_success(
            api.deliver_copy(tax_return["id"], {"channel": "POSTAL"}, SPEC), 200
        )
        assert delivered["recipient_copy_status"] == "POSTAL_SENT"
        # copy_delivered_at is stamped with the logical clock (millisecond
        # rendering is an implementation detail; compare the second precision).
        assert str(delivered["copy_delivered_at"]).startswith("2026-01-31T00:00:00")

        validate_success(api.record_copy_bounce(tax_return["id"], IRS), 200)

        # One second past the deadline: the identical call is rejected.
        set_clock("2026-01-31T00:00:01Z")
        resp = api.deliver_copy(tax_return["id"], {"channel": "POSTAL"}, SPEC)
        validate_error(resp, ApiErrorId.ERR_COPY_DEADLINE_PASSED, 409)

    def test_record_bounce_requires_postal_sent(self, api):
        """PRD §3.7: "When a postal copy comes back undeliverable, the `IRSSystem`
        bounce feed moves the copy status from `POSTAL_SENT` to `UNDELIVERABLE`..."

        Design: Corner/state_machines/c_record_bounce_requires_postal_sent
        """
        create_tax_year()
        _vendor, _payment, tax_return = create_validated_return(
            legal_name="Bounce V", tin="741741741"
        )
        # Copy is still PENDING — never postal-sent — so the bounce feed cannot fire.
        resp = api.record_copy_bounce(tax_return["id"], IRS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert after["recipient_copy_status"] == "PENDING"

    def test_electronic_copy_requires_consent(self, api):
        """PRD §3.7: "`ELECTRONIC` moves it to `E_DELIVERED` but only when the
        vendor's `e_delivery_consent` is true, failing with
        `ERR_ELECTRONIC_CONSENT_REQUIRED` otherwise."

        Design: Corner/validations/c_electronic_copy_requires_consent
        """
        create_tax_year(recipient_copy_deadline="2026-01-31T00:00:00Z")
        set_clock("2026-01-15T00:00:00Z")
        _vendor, _payment, tax_return = create_validated_return(
            legal_name="NoConsent V", tin="654987321"
        )

        resp = api.deliver_copy(tax_return["id"], {"channel": "ELECTRONIC"}, SPEC)
        validate_error(resp, ApiErrorId.ERR_ELECTRONIC_CONSENT_REQUIRED, 409)

        after = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert after["recipient_copy_status"] == "PENDING"


class TestParallelDimensions:
    def _setup_consented_validated_return(self, api, tin="888888888"):
        create_tax_year(recipient_copy_deadline="2026-01-31T00:00:00Z")
        set_clock("2026-01-15T00:00:00Z")
        return create_validated_return(
            legal_name="Par V", tin=tin, e_delivery_consent=True
        )

    def test_tax_return_parallel_dimensions(self, api):
        """PRD §3.7: "Recipient copy delivery runs on a parallel status dimension,
        `recipient_copy_status`, which starts at `PENDING` and moves independently of
        the federal lifecycle."
        PRD §3.7: "When a postal copy comes back undeliverable, the `IRSSystem`
        bounce feed moves the copy status from `POSTAL_SENT` to `UNDELIVERABLE`, and
        from `UNDELIVERABLE` either channel may be attempted again under the same
        guards."

        Design: Difficulty/non_linear_state_machine/tax_return_parallel_dimensions
        """
        _vendor, _payment, tax_return = self._setup_consented_validated_return(api)
        rid = tax_return["id"]

        # Copy dimension moves while the federal dimension stays VALIDATED.
        postal = validate_success(api.deliver_copy(rid, {"channel": "POSTAL"}, SPEC), 200)
        assert postal["federal_status"] == "VALIDATED"
        assert postal["recipient_copy_status"] == "POSTAL_SENT"

        bounced = validate_success(api.record_copy_bounce(rid, IRS), 200)
        assert bounced["federal_status"] == "VALIDATED"
        assert bounced["recipient_copy_status"] == "UNDELIVERABLE"

        # The federal dimension advances; the copy dimension is undisturbed.
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        validate_success(
            api.seal_transmittal(transmittal["id"], make_tax_specialist_headers("spec-1")), 200
        )
        validate_success(
            api.submit_transmittal(
                transmittal["id"], {"channel": "PAPER"}, make_tax_transmitter_headers("xmtr-1")
            ),
            200,
        )
        validate_success(
            api.record_transmittal_outcome(transmittal["id"], {"outcome": "ACCEPTED"}, IRS), 200
        )
        accepted = validate_success(api.get_return(rid, SPEC), 200)
        assert accepted["federal_status"] == "ACCEPTED"
        assert accepted["recipient_copy_status"] == "UNDELIVERABLE"

        # E-delivery from UNDELIVERABLE closes the copy loop (consent on file).
        edelivered = validate_success(
            api.deliver_copy(rid, {"channel": "ELECTRONIC"}, SPEC), 200
        )
        assert edelivered["recipient_copy_status"] == "E_DELIVERED"
        assert edelivered["federal_status"] == "ACCEPTED"
        assert str(edelivered["copy_delivered_at"]).startswith("2026-01-15T00:00:00")

    def test_undeliverable_copy_redeliverable_by_postal(self, api):
        """PRD §3.7: "When a postal copy comes back undeliverable, the `IRSSystem`
        bounce feed moves the copy status from `POSTAL_SENT` to `UNDELIVERABLE`, and
        from `UNDELIVERABLE` either channel may be attempted again under the same
        guards."
        PRD §3.7: "Each successful delivery stamps `copy_delivered_at` with the
        logical clock."

        Design: Difficulty/non_linear_state_machine/tax_return_parallel_dimensions
        """
        _vendor, _payment, tax_return = self._setup_consented_validated_return(
            api, tin="888888889"
        )
        rid = tax_return["id"]

        validate_success(api.deliver_copy(rid, {"channel": "POSTAL"}, SPEC), 200)
        validate_success(api.record_copy_bounce(rid, IRS), 200)

        # From UNDELIVERABLE the POSTAL channel may be attempted again.
        redelivered = validate_success(api.deliver_copy(rid, {"channel": "POSTAL"}, SPEC), 200)
        assert redelivered["recipient_copy_status"] == "POSTAL_SENT"
        assert redelivered["federal_status"] == "VALIDATED"
        assert str(redelivered["copy_delivered_at"]).startswith("2026-01-15T00:00:00")
