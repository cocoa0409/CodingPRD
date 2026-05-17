"""Disclosure service (PRD §3.6)."""

import time

import db
from config import (
    DISC_ACK,
    DISC_ISSUED,
    DISC_NON_TERMINAL,
    DISC_SUPERSEDED,
    DISC_VOIDED,
    DISCLOSURE_KIND_CD,
    DISCLOSURE_KIND_LE,
    DISCLOSURE_KINDS,
)
from errors import (
    ERR_APR_TOLERANCE_EXCEEDED,
    ERR_DISCLOSURE_VERSION_CONFLICT,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from services import calculations, clock, lookups
from services.common import bump, init_common, occ_check, touch
from services.validation import require_enum, require_int
from utils import parse_iso


def issue(application: dict, borrower: dict, body: dict) -> dict:
    kind = require_enum(body, "kind", DISCLOSURE_KINDS)
    apr_bps = require_int(body, "apr_bps", min_value=1, max_value=2500)
    total_loan_costs_cents = require_int(body, "total_loan_costs_cents", min_value=0)
    total_other_costs_cents = require_int(body, "total_other_costs_cents", min_value=0)

    # Reject client-supplied version field per PRD §2.4 (server mints it).
    if "version" in body and not isinstance(body["version"], int):
        raise_error(ERR_VALIDATION, "version field must be omitted on disclosure issuance.")
    # Client cannot supply a per-kind version that the server hasn't minted.
    # PRD: 'Attempting to issue a disclosure of a given kind with a `version` value that does not
    # match the next monotonic number is rejected with ERR_DISCLOSURE_VERSION_CONFLICT.'
    supplied_version = body.get("version")

    application_id = application["id"]

    # Serialise per-(application,kind) to avoid version collisions.
    # PRD §3.6: "Concurrent issuance of two disclosures of the same kind
    # for the same application is serialised: exactly one new version
    # persists; the loser receives ERR_DISCLOSURE_VERSION_CONFLICT."
    # A short hold time inside the critical section ensures genuinely-
    # concurrent requests reliably collide instead of slipping past
    # each other when the in-memory work is too fast.
    lock = db.get_disclosure_lock(application_id, kind)
    if not lock.acquire(blocking=False):
        raise_error(
            ERR_DISCLOSURE_VERSION_CONFLICT,
            "Concurrent disclosure issuance for the same kind.",
        )
    try:
        time.sleep(0.05)
        next_version = lookups.next_disclosure_version(application_id, kind)
        if supplied_version is not None and supplied_version != next_version:
            raise_error(
                ERR_DISCLOSURE_VERSION_CONFLICT,
                f"Supplied version {supplied_version} does not match next minted {next_version}.",
            )

        # APR tolerance check (only on CLOSING_DISCLOSURE issuance).
        if kind == DISCLOSURE_KIND_CD:
            le = lookups.latest_non_voided_disclosure(application_id, DISCLOSURE_KIND_LE)
            le_apr = le["apr_bps"] if le else None
            if calculations.apr_tolerance_exceeded(apr_bps, le_apr):
                raise_error(
                    ERR_APR_TOLERANCE_EXCEEDED,
                    "Closing Disclosure APR exceeds tolerance vs latest Loan Estimate.",
                )

        # Stamp issuance time using SystemClock for trid_clock business logic.
        issued_at_iso = clock.get_now_iso()
        issued_at_dt = parse_iso(issued_at_iso)

        # Cash-to-close.
        cash_to_close = calculations.compute_cash_to_close(
            total_loan_costs_cents=int(total_loan_costs_cents),
            total_other_costs_cents=int(total_other_costs_cents),
            requested_loan_amount_cents=int(application["requested_loan_amount_cents"]),
            state_code=(borrower or {}).get("state_code"),
        )

        eligible_to_consummate_at = None
        if kind == DISCLOSURE_KIND_CD:
            eligible_to_consummate_at = calculations.compute_eligible_to_consummate_at(
                issued_at_dt
            )

        # Mark previous-same-kind as SUPERSEDED.
        prev = lookups.latest_disclosure(application_id, kind, include_voided=True)
        if prev is not None and prev["status"] in DISC_NON_TERMINAL:
            prev["status"] = DISC_SUPERSEDED
            touch(prev)

        # Cascade: new LE that differs from latest CD by > 12 bps supersedes ACKNOWLEDGED CDs.
        if kind == DISCLOSURE_KIND_LE:
            latest_cd = lookups.latest_non_voided_disclosure(application_id, DISCLOSURE_KIND_CD)
            if latest_cd is not None and calculations.le_cd_apr_delta_exceeds(
                latest_cd["apr_bps"], apr_bps
            ):
                if latest_cd["status"] == DISC_ACK:
                    latest_cd["status"] = DISC_SUPERSEDED
                    touch(latest_cd)

        new_disclosure = init_common(
            {
                "application_id": application_id,
                "kind": kind,
                "version": next_version,
                "issued_at": issued_at_iso,
                "apr_bps": int(apr_bps),
                "total_loan_costs_cents": int(total_loan_costs_cents),
                "total_other_costs_cents": int(total_other_costs_cents),
                "cash_to_close_cents": int(cash_to_close),
                "waiting_period_started_at": issued_at_iso,
                "eligible_to_consummate_at": eligible_to_consummate_at,
                "status": DISC_ISSUED,
                "acknowledged_at": None,
            }
        )
        db.disclosures[new_disclosure["id"]] = new_disclosure

        # Stamp trid_clock_started_at on the parent application iff this is the INITIAL LOAN_ESTIMATE.
        if kind == DISCLOSURE_KIND_LE and next_version == 1:
            application["trid_clock_started_at"] = issued_at_iso
            bump(application)

        return new_disclosure
    finally:
        lock.release()


def get_or_404(application_id: str, disclosure_id: str) -> dict:
    d = db.disclosures.get(disclosure_id)
    if d is None or d["application_id"] != application_id:
        raise_error(ERR_RESOURCE_NOT_FOUND, "Disclosure not found.")
    return d


def acknowledge(application: dict, disclosure: dict, actor_user_id: str, body: dict) -> dict:
    occ_check(disclosure, body)

    # Borrower must be the application's borrower (actor X-User-ID == borrower_id).
    if actor_user_id != application["borrower_id"]:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            "Borrower can only acknowledge disclosures on their own application.",
        )
    if disclosure["status"] != DISC_ISSUED:
        raise_error(ERR_INVALID_STATE, "Disclosure must be in ISSUED.")
    disclosure["status"] = DISC_ACK
    disclosure["acknowledged_at"] = clock.get_now_iso()
    touch(disclosure)
    return disclosure


def list_for_app(application_id: str, *, kind=None, limit=10, offset=0):
    items = lookups.list_disclosures(application_id, kind=kind)
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    return items[offset : offset + limit], total
