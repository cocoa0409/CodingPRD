"""The money engine (PRD 2.6 / 3.9).  Integer cents everywhere, Decimal for the
two roundings, round-half-up, and a pinned evaluation order."""

from decimal import ROUND_HALF_UP, Decimal

from core import clock, db
from core.constants import (
    ADMIN_FEE_PCT,
    BLOCK_RATE_CENTS_BY_MODALITY,
    CANCEL_DISPATCHED_PCT,
    CANCEL_FREE_LEAD_MINUTES,
    CANCEL_LATE_PCT,
    CANCEL_PARTIAL_LEAD_MINUTES,
    CANCEL_PARTIAL_PCT,
    LIST_PRICE_CENTS_BY_MODALITY,
    NO_SHOW_PCT,
    STAT_SURCHARGE_CENTS,
)
from services import derive
from services.timecalc import wall_minutes_between


def round_half_up(value):
    """Decimal -> int, half away from zero (PRD 2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_cents, pct):
    return round_half_up(Decimal(amount_cents) * Decimal(pct) / Decimal(100))


# --------------------------------------------------------------------------
# step 1/2 — contract resolution and base price
# --------------------------------------------------------------------------

def resolve_contract(clinic_id):
    """The clinic's single contract computing to ACTIVE, or None."""
    actives = derive.active_contracts_for_clinic(clinic_id)
    if len(actives) == 1:
        return actives[0]
    return None


def base_price(study, contract):
    """(price_basis, base_price_cents).

    # Adjudication of friction 6: the read-only pricing view answers rather than
    # failing when the clinic has no ACTIVE contract — chosen in reachability
    # terms.  ERR_CONTRACT_NOT_ACTIVE is nominated for POSTING only (rung 16);
    # attaching it to GET /studies/{id}/pricing as well would strand the whole
    # read-only decomposition for every contract-less clinic — a declared
    # endpoint made unreachable — while leaving the error itself reachable
    # through posting anyway.  With no contract there is no block to draw on, so
    # the LIST_PRICE branch (the same branch a PER_STUDY_LIST contract takes)
    # applies.  Posting still enforces rung 16 before it ever reaches here.
    """
    if study["billing_status"] == "NON_BILLABLE":
        return "NON_BILLABLE", 0
    # Once a study has actually been posted, its base price is the amount that
    # was billed.  The block boundary is a COUNTER, so re-deriving it later would
    # make a posted study's own `base_price_cents` drift away from its own
    # STUDY_READ charge line the moment the next study drew the block down.
    # calculations.study_base_price_cents is triggered at exactly two moments —
    # the pricing view and posting — never on every read, so serving the billed
    # figure after a posting is the faithful reading.
    if study.get("_billed_price_basis") is not None:
        return study["_billed_price_basis"], study["_billed_base_price_cents"]
    if (
        contract is not None
        and contract["kind"] == "PREPAID_BLOCK"
        and derive.contract_remaining(contract) > 0
    ):
        return "BLOCK_RATE", BLOCK_RATE_CENTS_BY_MODALITY[study["modality"]]
    return "LIST_PRICE", LIST_PRICE_CENTS_BY_MODALITY[study["modality"]]


# --------------------------------------------------------------------------
# step 3 — trip share (floor + remainder, created_at ASC)
# --------------------------------------------------------------------------

def trip_share_cents(study):
    if study["study_kind"] == "TELERAD":
        return 0
    stop = derive.stop_of_study(study)
    if stop is None:
        return 0
    billable = derive.billable_set_at_stop(stop)
    n = len(billable)
    if n == 0:
        return 0
    index = None
    for i, s in enumerate(billable):
        if s["id"] == study["id"]:
            index = i
            break
    if index is None:
        return 0
    fee = stop["trip_fee_cents"]
    base = fee // n
    remainder = fee - base * n
    return base + (1 if index < remainder else 0)


def billable_studies_at_stop(study):
    stop = derive.stop_of_study(study)
    if stop is None:
        return 0
    return len(derive.billable_set_at_stop(stop))


# --------------------------------------------------------------------------
# steps 4/5/6 — surcharge, admin fee, total
# --------------------------------------------------------------------------

def stat_surcharge_cents(study):
    return STAT_SURCHARGE_CENTS if study["priority"] == "STAT" else 0


def admin_fee_cents(base_cents, trip_cents, surcharge_cents):
    """ONE rounding over the study's subtotal, never per component."""
    subtotal = base_cents + trip_cents + surcharge_cents
    return pct_of(subtotal, ADMIN_FEE_PCT)


def decomposition(study, contract=None, resolved=False):
    """The pinned six-step evaluation order of PRD 3.9."""
    if not resolved:
        contract = resolve_contract(derive.clinic_id_of_study(study))
    basis, base = base_price(study, contract)
    if basis == "NON_BILLABLE":
        # PRD 3.9: for a NON_BILLABLE study "its base price, trip share,
        # surcharge and administrative fee are all 0".
        return {
            "price_basis": "NON_BILLABLE",
            "base_price_cents": 0,
            "trip_share_cents": 0,
            "stat_surcharge_cents": 0,
            "admin_fee_cents": 0,
            "total_price_cents": 0,
            "cancellation_fee_cents": study.get("cancellation_fee_cents", 0),
            "billable_studies_at_stop": billable_studies_at_stop(study),
        }
    trip = trip_share_cents(study)
    surcharge = stat_surcharge_cents(study)
    admin = admin_fee_cents(base, trip, surcharge)
    return {
        "price_basis": basis,
        "base_price_cents": base,
        "trip_share_cents": trip,
        "stat_surcharge_cents": surcharge,
        "admin_fee_cents": admin,
        "total_price_cents": base + trip + surcharge + admin,
        "cancellation_fee_cents": study.get("cancellation_fee_cents", 0),
        "billable_studies_at_stop": billable_studies_at_stop(study),
    }


# --------------------------------------------------------------------------
# cancellation fee (PRD 3.9)
# --------------------------------------------------------------------------

def cancellation_fee_cents(study, trigger):
    """`trigger` is one of PROVIDER / NO_SHOW / CLINIC.

    Branch order is exactly the four numbered branches of PRD 3.9.
    """
    list_price = LIST_PRICE_CENTS_BY_MODALITY[study["modality"]]
    if trigger == "PROVIDER":
        return 0
    if study["study_kind"] == "TELERAD":
        return 0
    if trigger == "NO_SHOW":
        return pct_of(list_price, NO_SHOW_PCT)

    stop = derive.stop_of_study(study)
    if stop is None:
        return 0
    route = derive.route_of_stop(stop)
    if route is None:
        return 0

    service_date = clock.parse_date(route["service_date"])
    arrival = clock.plus_minutes(
        clock.midnight_utc(service_date), stop["planned_arrival_minute"]
    )
    lead = wall_minutes_between(clock.now(), arrival)

    if route["status"] == "DISPATCHED":
        others = len(
            [
                s
                for s in derive.studies_at_stop(stop)
                if s["id"] != study["id"] and s["workflow_status"] == "ORDERED"
            ]
        )
        fee = pct_of(list_price, CANCEL_DISPATCHED_PCT)
        if others == 0:
            fee += stop["trip_fee_cents"]
        return fee
    if lead >= CANCEL_FREE_LEAD_MINUTES:
        return 0
    if lead >= CANCEL_PARTIAL_LEAD_MINUTES:
        return pct_of(list_price, CANCEL_PARTIAL_PCT)
    return pct_of(list_price, CANCEL_LATE_PCT)


# --------------------------------------------------------------------------
# in-place re-pricing of a stop's surviving siblings
# --------------------------------------------------------------------------

def reprice_stop_siblings(stop, exclude_invoice_check=False):
    """Re-derive the stop's billable set and re-price the surviving members'
    ACTIVE TRIP_FEE_SHARE and ADMIN_FEE charge lines IN PLACE.

    Lines stay ACTIVE; only `amount_cents` changes.  Only lines on an OPEN
    invoice are touched — gate G1 forbids re-pricing a FINALIZED invoice's lines,
    and the callers check that gate before they get here.
    """
    if stop is None:
        return
    for study in derive.billable_set_at_stop(stop):
        new_trip = trip_share_cents(study)
        lines = db.where("charge_lines", study_id=study["id"])
        trip_lines = [
            l for l in lines if l["kind"] == "TRIP_FEE_SHARE" and l["status"] == "ACTIVE"
        ]
        admin_lines = [
            l for l in lines if l["kind"] == "ADMIN_FEE" and l["status"] == "ACTIVE"
        ]
        read_lines = [
            l for l in lines if l["kind"] == "STUDY_READ" and l["status"] == "ACTIVE"
        ]
        stat_lines = [
            l for l in lines if l["kind"] == "STAT_SURCHARGE" and l["status"] == "ACTIVE"
        ]
        for line in trip_lines:
            invoice = db.get("invoices", line["invoice_id"])
            if invoice is None or invoice["status"] != "OPEN":
                continue
            if line["amount_cents"] != new_trip:
                line["amount_cents"] = new_trip
                db.touch(line)
        for line in admin_lines:
            invoice = db.get("invoices", line["invoice_id"])
            if invoice is None or invoice["status"] != "OPEN":
                continue
            base_component = sum(
                l["amount_cents"] for l in read_lines if l["invoice_id"] == invoice["id"]
            )
            surcharge_component = sum(
                l["amount_cents"] for l in stat_lines if l["invoice_id"] == invoice["id"]
            )
            trip_component = sum(
                l["amount_cents"]
                for l in trip_lines
                if l["invoice_id"] == invoice["id"]
            )
            new_admin = admin_fee_cents(
                base_component, trip_component, surcharge_component
            )
            if line["amount_cents"] != new_admin:
                line["amount_cents"] = new_admin
                db.touch(line)
