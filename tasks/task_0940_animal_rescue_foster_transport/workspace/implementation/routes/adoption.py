"""Adoption: application, screening, finalization, the fee waterfall, payment,
the adopter return and the deferred-alteration deposit."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import gates
import services
from errors import ApiError
from routing import listing, must, query_filters
from store import DB, ordered, touch
from validation import Field, parse_body

bp = Blueprint("adoption", __name__)


# =====================================================================
#  Applications
# =====================================================================

@bp.post("/rescue/adoption-applications")
def submit_application():
    ctx = auth.authenticate(["PlatformAdmin", "AdoptionCounselor", "Adopter"])
    body = parse_body(request, [
        Field("animal_id", "string", required=True),
        Field("applicant_person_id", "string", required=True),
    ])
    auth.own_if(ctx, "Adopter", body["applicant_person_id"])
    animal = must("Animal", body["animal_id"])
    applicant = must("Person", body["applicant_person_id"])
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)

    # Rung 24: the five criteria are evaluated in a PINNED order and the first
    # failure ends the evaluation.  The match happens at create time, which is
    # why no application row ever carries a household-mismatch decline reason.
    if applicant["youngest_child_age_years"] < animal["restriction_no_children_under_years"]:
        raise ApiError("ERR_HOUSEHOLD_MISMATCH", "The household's youngest child is too young.")
    if animal["restriction_no_cats"] and applicant["resident_cat_count"] != 0:
        raise ApiError("ERR_HOUSEHOLD_MISMATCH", "The animal may not live with resident cats.")
    if animal["restriction_no_dogs"] and applicant["resident_dog_count"] != 0:
        raise ApiError("ERR_HOUSEHOLD_MISMATCH", "The animal may not live with resident dogs.")
    if animal["restriction_requires_fenced_yard"] and not applicant["has_fenced_yard"]:
        raise ApiError("ERR_HOUSEHOLD_MISMATCH", "The animal requires a fenced yard.")
    if applicant["housing_type"] in (animal["restriction_housing_types_excluded"] or []):
        raise ApiError("ERR_HOUSEHOLD_MISMATCH", "The applicant's housing type is excluded.")

    app = DB.insert("AdoptionApplication", {
        "animal_id": animal["id"],
        "applicant_person_id": applicant["id"],
        "attempt_count": 1,
        "status": "SUBMITTED",
        "screened_by_user_id": None,
        "screened_at": None,
        "decline_reason": None,
    })
    return envelope.created(derive.adoption_application(app))


@bp.get("/rescue/adoption-applications/<app_id>")
def read_application(app_id):
    ctx = auth.authenticate(["PlatformAdmin", "AdoptionCounselor", "Adopter"])
    app = DB.get("AdoptionApplication", app_id)
    if app is not None:
        auth.own_if(ctx, "Adopter", app["applicant_person_id"])
    return envelope.ok(derive.adoption_application(must("AdoptionApplication", app_id)))


@bp.get("/rescue/adoption-applications")
def list_applications():
    auth.authenticate(["PlatformAdmin", "AdoptionCounselor"])
    return listing("AdoptionApplication", DB.all("AdoptionApplication"),
                   query_filters(["animal_id", "applicant_person_id", "status"]))


@bp.post("/rescue/adoption-applications/<app_id>/screen")
def screen_application(app_id):
    ctx = auth.authenticate(["PlatformAdmin", "AdoptionCounselor"])
    body = parse_body(request, [Field("decision", "string", required=True, enum="decision")])
    app = must("AdoptionApplication", app_id)
    animal = DB.get("Animal", app["animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))
    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED application may be screened.")
    # Screening is deliberately permitted while the stray hold is still
    # HOLD_ACTIVE; only finalization must wait.
    if body["decision"] == "APPROVE":
        app["status"] = "APPROVED"
    else:
        app["status"] = "DECLINED"
        app["decline_reason"] = "COUNSELOR_DECISION"
    app["screened_by_user_id"] = ctx.user_id
    app["screened_at"] = clock.stamp()                 # (c) clock-derived
    touch(app)
    return envelope.ok(derive.adoption_application(app))


@bp.post("/rescue/adoption-applications/<app_id>/resubmit")
def resubmit_application(app_id):
    ctx = auth.authenticate(["PlatformAdmin", "Adopter"])
    app = DB.get("AdoptionApplication", app_id)
    if app is not None:
        auth.own_if(ctx, "Adopter", app["applicant_person_id"])
    parse_body(request, [])
    app = must("AdoptionApplication", app_id)
    animal = DB.get("Animal", app["animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))
    if app["status"] != "DECLINED":
        raise ApiError("ERR_INVALID_STATE", "Only a DECLINED application may be resubmitted.")
    # Rung 30: the loop is capped at three submissions counting the original.
    if app["attempt_count"] >= calc.MAX_ADOPTION_APPLICATION_ATTEMPTS:
        raise ApiError("ERR_APPLICATION_ATTEMPT_LIMIT", "The submission cap has been reached.")
    app["status"] = "SUBMITTED"
    app["attempt_count"] += 1
    app["decline_reason"] = None
    app["screened_by_user_id"] = None
    app["screened_at"] = None
    touch(app)
    return envelope.ok(derive.adoption_application(app))


# =====================================================================
#  Finalization
# =====================================================================

@bp.post("/rescue/adoptions")
def finalize_adoption():
    ctx = auth.authenticate(["PlatformAdmin", "AdoptionCounselor"])
    body = parse_body(request, [
        Field("adoption_application_id", "string", required=True),
        Field("expected_animal_version", "integer", required=True, fmt="gte0"),
        Field("credit_application_order", "string", default="CREDIT_FIRST",
              enum="credit_application_order"),
        Field("refund_basis", "string", default="FEE_PAID", enum="refund_basis"),
        Field("deposit_basis", "string", default="FLAT", enum="deposit_basis"),
    ])
    app = must("AdoptionApplication", body["adoption_application_id"])
    animal = must("Animal", app["animal_id"])

    # Adoption finalization is the only operation inside EVERY gate's scope.
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal,
                    gate2=True, gate3=True, gate4=True, gate5=True)

    if body["expected_animal_version"] != animal["version"]:            # rung 17
        raise ApiError("ERR_STALE_VERSION", "The animal has been modified since it was read.")
    if app["status"] != "APPROVED":                                     # rung 18
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED application may be finalized.")
    # Rung 22: segregation of duties -- PlatformAdmin gets no exemption.
    if app["screened_by_user_id"] is not None and app["screened_by_user_id"] == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The screening actor may not finalize the same application.")
    episode = derive.current_episode(animal) or derive.open_episode(animal)
    if episode is None:
        raise ApiError("ERR_INTAKE_RECORD_NOT_FOUND",
                       "The animal has no currently open custody episode.")
    if episode["hold_status"] != "HOLD_EXPIRED":                        # rung 23
        raise ApiError("ERR_STRAY_HOLD_NOT_EXPIRED", "The animal's stray hold has not expired.")
    # Rung 28: alteration compliance.
    age_weeks = derive.age_weeks(animal)
    if animal["alteration_status"] != "ALTERED" and age_weeks >= calc.ALTERATION_MIN_AGE_WEEKS:
        raise ApiError("ERR_ALTERATION_REQUIRED",
                       "An unaltered animal at or over 16 weeks cannot be adopted out.")

    # ---- the fee, assembled in four stages ----------------------------
    base_fee = calc.adoption_base_fee(animal["species"])
    waiver_kind, waiver_pct = calc.adoption_waiver_selection(animal)
    pool, pool_total = calc.adoption_sponsorship_pool(animal["id"])
    sponsorship, waiver_cents, charged, residual = calc.adoption_fee_waterfall(
        base_fee, waiver_pct, pool_total, body["credit_application_order"])

    deposit = 0
    if animal["alteration_status"] != "ALTERED" and age_weeks < calc.ALTERATION_MIN_AGE_WEEKS:
        deposit = calc.alteration_deposit(animal, body["deposit_basis"])

    adoption = DB.insert("Adoption", {
        "adoption_application_id": app["id"],
        "animal_id": animal["id"],
        "adopter_person_id": app["applicant_person_id"],
        "credit_application_order": body["credit_application_order"],
        "refund_basis": body["refund_basis"],
        "deposit_basis": body["deposit_basis"],
        "base_fee_cents": base_fee,
        "waiver_kind": waiver_kind,
        "waiver_applied_cents": waiver_cents,
        "sponsorship_applied_cents": sponsorship,
        "adopter_charged_cents": charged,
        "residual_credit_cents": residual,
        "alteration_deposit_cents": deposit,
        "alteration_deposit_refunded_cents": 0,
        "adopter_paid_cents": 0,
        "refund_issued_cents": 0,
        "credit_restored_cents": 0,
        "finalized_at": clock.stamp(),                 # (c) clock-derived
        "returned_at": None,
        "finalized_by_user_id": ctx.user_id,
        "status": "FINALIZED",
        "fee_status": "UNPAID",
        # Private: which contributions the waterfall drew and by how much, so a
        # FEE_ASSESSED return can put the credit back where it came from.  Not
        # a response field.
        "_sponsorship_lines": [],
    })

    remaining = sponsorship
    for contribution in pool:
        if remaining <= 0:
            break
        line = min(derive.available_cents(contribution), remaining)
        if line <= 0:
            continue
        services.draw_contribution(contribution, line)
        adoption["_sponsorship_lines"].append((contribution["id"], line))
        remaining -= line

    if deposit > 0:
        animal["alteration_status"] = "DEFERRED_DEPOSIT"

    app["status"] = "FINALIZED"
    touch(app)
    for sibling in ordered(DB.where("AdoptionApplication", animal_id=animal["id"])):
        if sibling["id"] == app["id"]:
            continue
        if sibling["status"] in ("SUBMITTED", "APPROVED"):
            sibling["status"] = "AUTO_DECLINED"
            sibling["decline_reason"] = "SUPERSEDED_BY_FINALIZED_SIBLING"
            touch(sibling)

    converted = services.active_placement_in_home_of(animal["id"], app["applicant_person_id"])
    outcome_type = "FOSTER_TO_ADOPT" if converted is not None else "ADOPTION"
    services.write_outcome(animal, outcome_type,
                           counterparty_person_id=app["applicant_person_id"],
                           adoption_id=adoption["id"],
                           foster_to_adopt_placement=converted)
    return envelope.created(derive.adoption(adoption))


@bp.get("/rescue/adoptions/<adoption_id>")
def read_adoption(adoption_id):
    ctx = auth.authenticate(["PlatformAdmin", "AdoptionCounselor", "FinanceOfficer", "Adopter"])
    adoption = DB.get("Adoption", adoption_id)
    if adoption is not None:
        auth.own_if(ctx, "Adopter", adoption["adopter_person_id"])
    return envelope.ok(derive.adoption(must("Adoption", adoption_id)))


@bp.get("/rescue/adoptions")
def list_adoptions():
    auth.authenticate(["PlatformAdmin", "AdoptionCounselor", "FinanceOfficer"])
    return listing("Adoption", DB.all("Adoption"),
                   query_filters(["adoption_application_id", "animal_id", "adopter_person_id",
                                  "status", "fee_status"]))


@bp.post("/rescue/adoptions/<adoption_id>/payment")
def record_payment(adoption_id):
    ctx = auth.authenticate(["PlatformAdmin", "FinanceOfficer", "Adopter"])
    adoption = DB.get("Adoption", adoption_id)
    if adoption is not None:
        auth.own_if(ctx, "Adopter", adoption["adopter_person_id"])
    body = parse_body(request, [Field("amount_cents", "integer", required=True, fmt="gte0")])
    adoption = must("Adoption", adoption_id)
    animal = DB.get("Animal", adoption["animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))

    # The money axis declares payment transitions only out of UNPAID and
    # PARTIALLY_PAID.
    if adoption["fee_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_STATE", "No payment transition is declared from this state.")
    adoption["adopter_paid_cents"] += body["amount_cents"]
    # The target is adopter_charged_cents PLUS alteration_deposit_cents.
    target = adoption["adopter_charged_cents"] + adoption["alteration_deposit_cents"]
    adoption["fee_status"] = "PAID" if adoption["adopter_paid_cents"] >= target else "PARTIALLY_PAID"
    touch(adoption)
    return envelope.ok(derive.adoption(adoption))


@bp.post("/rescue/adoptions/<adoption_id>/return")
def adopter_return(adoption_id):
    auth.authenticate(["PlatformAdmin", "AdoptionCounselor"])
    parse_body(request, [Field("reason", "string")])
    adoption = must("Adoption", adoption_id)
    animal = DB.get("Animal", adoption["animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))

    if adoption["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", "Only a FINALIZED adoption may be returned.")
    outcome = services.standing_outcome(adoption["animal_id"])
    if outcome is None or outcome["outcome_type"] not in ("ADOPTION", "FOSTER_TO_ADOPT"):
        raise ApiError("ERR_INVALID_STATE",
                       "The animal's standing outcome is not an unreversed adoption.")
    elapsed = clock.elapsed_days(clock.now(), clock.parse(adoption["finalized_at"]))
    if elapsed > calc.RETURN_WINDOW_PARTIAL_DAYS:                        # rung 38
        raise ApiError("ERR_RETURN_WINDOW_CLOSED", "The outer return window has closed.")

    pct = calc.return_refund_pct(elapsed)
    refund = calc.round_half_up(Decimal(adoption["adopter_paid_cents"]) * pct)
    if adoption["refund_basis"] == "FEE_ASSESSED":
        restored = calc.round_half_up(Decimal(adoption["sponsorship_applied_cents"]) * pct)
    else:
        restored = 0

    # Hop 1
    adoption["returned_at"] = clock.stamp()            # (c) clock-derived
    adoption["refund_issued_cents"] = refund
    adoption["credit_restored_cents"] = restored
    # Adjudication of friction 10: Reading A -- the money axis declares refund
    # transitions out of PAID ONLY, so an adoption returned while its fee_status
    # is PARTIALLY_PAID (or UNPAID) keeps that state even though the refund is
    # computed and written.  Reading B would have to invent two transitions the
    # state machine does not declare; Reading A invents nothing and strands
    # nothing, since REFUNDED_PARTIAL and REFUNDED_FULL both stay reachable from
    # PAID.
    if adoption["fee_status"] == "PAID":
        if refund > 0 and refund < adoption["adopter_paid_cents"]:
            adoption["fee_status"] = "REFUNDED_PARTIAL"
        elif refund > 0 and refund == adoption["adopter_paid_cents"]:
            adoption["fee_status"] = "REFUNDED_FULL"

    if restored > 0:
        for cid, share in calc.allocate_restoration(adoption["_sponsorship_lines"], restored):
            contribution = DB.get("Contribution", cid)
            if contribution is not None:
                services.restore_contribution(contribution, share)

    # Hop 2: the standing outcome is reversed, leaving numerator and
    # denominator together.
    outcome["reversed_at"] = clock.stamp()             # (c) clock-derived
    outcome["reversal_reason"] = "ADOPTER_RETURN"
    touch(outcome)

    # Hop 3: the superseded episode is voided and a fresh RETURN episode opens.
    superseded = DB.get("IntakeRecord", outcome["intake_record_id"]) if outcome["intake_record_id"] else None
    if superseded is not None and superseded["status"] == "CLOSED":
        superseded["status"] = "VOIDED"
        touch(superseded)
    intake_raw = clock.stamp()
    new_episode = DB.insert("IntakeRecord", {
        "animal_id": animal["id"],
        "source_person_id": None,
        "intake_type": "RETURN",
        "intake_datetime": intake_raw,
        "impound_billing_basis": "CALENDAR_DAY",
        "identifiable_at_intake": bool(animal["identifiable"]),
        "hold_days": calc.STRAY_HOLD_RETURN_DAYS,
        "hold_expires_at": clock.derive(
            clock.plus_days(clock.parse(intake_raw), calc.STRAY_HOLD_RETURN_DAYS), intake_raw),
        # An animal coming back from an adoption serves no stray hold.
        "hold_status": "HOLD_EXPIRED",
        "status": "OPEN",
        "reclaim_base_fee_cents": None,
        "impound_billable_days": None,
        "impound_subtotal_cents": None,
        "repeat_offense_multiplier": None,
        "hardship_waiver_cents": None,
        "reclaim_total_cents": None,
    })

    # Hop 4
    animal["lifecycle_status"] = "IN_CUSTODY"
    animal["current_intake_record_id"] = new_episode["id"]
    touch(animal)

    adoption["status"] = "RETURNED"
    touch(adoption)
    return envelope.ok(derive.adoption(adoption))


@bp.post("/rescue/adoptions/<adoption_id>/alteration-proof")
def alteration_proof(adoption_id):
    auth.authenticate(["PlatformAdmin", "Veterinarian", "AdoptionCounselor"])
    parse_body(request, [Field("proof_reference", "string", required=True)])
    adoption = must("Adoption", adoption_id)
    animal = DB.get("Animal", adoption["animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))
    if animal is None or animal["alteration_status"] != "DEFERRED_DEPOSIT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DEFERRED_DEPOSIT animal may have its deposit redeemed.")
    # Adjudication of friction 8: Reading A -- the FULL alteration_deposit_cents
    # assessed at finalization is recorded as refunded, regardless of how much
    # cash the adopter actually handed over.  Reading B ("only the portion the
    # adopter covered") has no formula anywhere in the PRD -- it would have to
    # be invented, and any invention here is unverifiable -- while Reading A is
    # spelled out concretely and strands nothing.
    adoption["alteration_deposit_refunded_cents"] = adoption["alteration_deposit_cents"]
    touch(adoption)
    animal["alteration_status"] = "ALTERED"
    touch(animal)
    # This operation does not touch fee_status; no transition is declared for it.
    return envelope.ok(derive.adoption(adoption))
