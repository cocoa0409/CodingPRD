"""Bad-debt write-off endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..calculations import (
    MIN_DAYS_SINCE_BILLED,
    days_since_billed,
    outstanding_balance_calc,
)
from ..errors import ApiError
from ..services.serializers import serialize_bad_debt
from ..services.validation import get_encounter_or_404
from ..store import LOCK, append_only_fields_create, bump_version, get_store, now_iso
from ._helpers import created


def register(app: Flask) -> None:
    @app.route("/encounters/<encounter_id>/write-off", methods=["POST"])
    @require_auth("Biller")
    def write_off(encounter_id):
        enc = get_encounter_or_404(encounter_id)

        # State guard: must be BILLED.
        if enc["status"] != "BILLED":
            raise ApiError(
                "ERR_INVALID_STATE",
                f"Encounter must be BILLED to write off; is {enc['status']}.",
            )

        store = get_store()

        with LOCK:
            # Duplicate check.
            if encounter_id in store.bad_debt_by_encounter:
                raise ApiError(
                    "ERR_DUPLICATE_WRITE_OFF",
                    "A bad-debt record already exists for this encounter.",
                )

            # Temporal gate: >= 90 days since billed_at (inclusive).
            day_count = days_since_billed(enc)
            if day_count < MIN_DAYS_SINCE_BILLED:
                raise ApiError(
                    "ERR_WRITE_OFF_TOO_EARLY",
                    f"Write-off requires >= {MIN_DAYS_SINCE_BILLED} days since billed_at (got {day_count}).",
                )

            # Fiscal gate: outstanding > 0.
            outstanding = outstanding_balance_calc(enc)["outstanding_balance_cents"]
            if outstanding <= 0:
                raise ApiError(
                    "ERR_WRITE_OFF_NO_BALANCE",
                    "Write-off requires outstanding_balance_cents > 0.",
                )

            base = append_only_fields_create()
            record = {
                **base,
                "encounter_id": encounter_id,
                "write_off_cents": outstanding,
                "days_since_billed": day_count,
                "written_off_at": now_iso(),
            }
            store.bad_debt_records[record["id"]] = record
            store.bad_debt_by_encounter[encounter_id] = record["id"]
            enc["write_off_cents"] = outstanding
            enc["status"] = "WRITTEN_OFF"
            bump_version(enc)

        return created(serialize_bad_debt(record))
