"""External-system event ingestion and idempotency.

Anchored in PRD §2.10 and §3.9.
"""
from __future__ import annotations
from datetime import date
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_elder, top_up_deposit,
    external_event_payload,
    full_cycle_window, create_bill, finalize_bill,
    ingest_external_event,
    pay_bill,
    setup_admitted_elder_v2,
    setup_admitted_with_finalized_bill,
    unique_idempotency_key,
    ADMIN, FAMILY, FINANCE, SYSTEMSYNC,
    validate_error, validate_success,
)


# ===========================================================================
# Duplicate-event idempotency (PRD §2.10, §3.9)
# ===========================================================================
class TestExternalEventIdempotency:

    def test_duplicate_event_returns_duplicate_status(self):
        """PRD §2.10: "The second submission with the same pair is
        recognised as a duplicate: `result_status` is set to `DUPLICATE`,
        the prior result is returned to the caller, no side effects are
        re-applied, and the response carries `ERR_DUPLICATE_EVENT`."

        Claim: re-posting an event with the same (source, idempotency_key)
        yields ERR_DUPLICATE_EVENT.
        """
        idem = unique_idempotency_key()
        # First send — apply to a finalized bill so it has somewhere to
        # land. Use a PAYMENT_RECEIVED carrying a fake bill_id; if the bill
        # ref isn't found, the event records REJECTED rather than APPLIED,
        # but the duplicate-replay rule still applies (PRD §2.10).
        body = external_event_payload(
            source="PAYMENT",
            event_type="PAYMENT_RECEIVED",
            payload={"bill_id": "00000000-0000-0000-0000-000000000000",
                     "amount_cents": 1000},
            idempotency_key=idem,
        )
        api_client.ingest_external_event(body, SYSTEMSYNC)
        # Second send — same (source, idempotency_key).
        resp = api_client.ingest_external_event(body, SYSTEMSYNC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EVENT.value)
