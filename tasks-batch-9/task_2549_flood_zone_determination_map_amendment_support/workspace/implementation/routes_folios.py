"""Loan folios, determinations, coverage reports and force placement."""
from flask import Blueprint

import calc
import enums
from authz import ROLE_LENDER, ROLE_PROVIDER_ANALYST, authorize
from db import all_rows, db, new_row, touch
from errors import fail
from response import created, ok
from services import (
    adopt_determination,
    build_determination,
    determinations_for,
    expire_lapsed_notices,
    folio_community,
    folio_property,
    latest_mandatory_notice,
    must,
    recompute_folio,
    recount_active_folio_count,
    recount_open_force_placements,
    retire_determination,
    settle_escrow,
    store,
    supersede_notices,
    touch_folio,
)
from shape import Field, no_body, read_body

bp = Blueprint("folios", __name__)

LENDER = [ROLE_LENDER]
ANALYST = [ROLE_PROVIDER_ANALYST]


def _require_owner(actor, folio):
    """Ladder priority 7: a Lender caller may act only on its own folio."""
    if actor.is_lender and actor.user_id != folio["lender_id"]:
        fail(
            "ERR_FOLIO_NOT_OWNED",
            "The acting lender does not own loan folio '%s'." % folio["id"],
        )


@bp.post("/loan-folios")
def open_folio():
    actor = authorize(LENDER)
    body = read_body(
        [
            Field("lender_id"),
            Field("property_id"),
            Field("loan_number"),
            Field("borrower_user_id"),
            Field("principal_balance_cents", "int", gt=0),
            Field("policy_anniversary_date", "datetime"),
            Field("escrow_balance_cents", "int", required=False, default=0, min_value=0),
        ]
    )
    must("lenders", body["lender_id"])
    prop = must("properties", body["property_id"])
    for existing in all_rows("loan_folios"):
        if (
            existing["lender_id"] == body["lender_id"]
            and existing["loan_number"] == body["loan_number"]
        ):
            fail(
                "ERR_INVALID_REQUEST",
                "loan_number '%s' already exists for this lender." % body["loan_number"],
            )
    row = new_row(
        lender_id=body["lender_id"],
        property_id=prop["id"],
        loan_number=body["loan_number"],
        borrower_user_id=body["borrower_user_id"],
        principal_balance_cents=body["principal_balance_cents"],
        escrow_balance_cents=body["escrow_balance_cents"],
        initial_escrow_balance_cents=body["escrow_balance_cents"],
        policy_anniversary_date=body["policy_anniversary_date"],
        monitoring_status="ACTIVE",
        insurance_status="NONE",
        current_determination_id=None,
        required_coverage_cents=0,
        reported_coverage_cents=0,
        uninsured_exposure_cents=0,
        force_placed_premium_cents=0,
        force_placed_at=None,
        force_placed_coverage_days=0,
        cumulative_earned_premium_cents=0,
        open_notice_count=0,
        pending_redetermination_count=0,
        compliance_posture="COMPLIANT",
    )
    store("loan_folios", row)
    recompute_folio(row)
    community = db.communities[prop["community_id"]]
    recount_active_folio_count(community)
    touch(community)
    return created(row)


@bp.post("/determinations")
def issue_determination():
    actor = authorize(ANALYST)
    body = read_body(
        [
            Field("loan_folio_id"),
            Field("structure_id"),
            Field(
                "determination_type", "enum", enum=enums.CLIENT_DETERMINATION_TYPES
            ),
            Field("expected_loan_folio_version", "int", min_value=0),
        ]
    )
    folio = must("loan_folios", body["loan_folio_id"])
    structure = must("structures", body["structure_id"])

    # priority 10: stale-folio protection
    if body["expected_loan_folio_version"] != folio["version"]:
        fail(
            "ERR_STALE_LOAN_FOLIO_VERSION",
            "expected_loan_folio_version %d does not match the folio version %d."
            % (body["expected_loan_folio_version"], folio["version"]),
        )

    live = [
        d
        for d in determinations_for(folio)
        if d["structure_id"] == structure["id"] and d["status"] != "SUPERSEDED"
    ]
    # priority 11: a determination locked for a joint review may not be replaced
    for det in live:
        if det["status"] == "UNDER_DISPUTE":
            fail(
                "ERR_INVALID_DETERMINATION_STATE",
                "The current determination is locked by an open dispute.",
            )
    prior = None
    for det in live:
        if det["status"] in ("ISSUED", "FLAGGED_FOR_REVIEW"):
            prior = det

    # priority 17: the structure must sit on the folio's property
    if structure["property_id"] != folio["property_id"]:
        fail(
            "ERR_STRUCTURE_FOLIO_MISMATCH",
            "The structure does not sit on the property named by the loan folio.",
        )

    prop = folio_property(folio)
    # priority 19: the property must be geocoded
    if prop["geocode_status"] != "GEOCODED":
        fail(
            "ERR_PROPERTY_NOT_GEOCODED",
            "The property's geocode is unresolved.",
        )

    # priority 20: an effective panel must govern the property
    panel = calc.effective_panel(prop)
    if panel is None:
        fail(
            "ERR_NO_EFFECTIVE_PANEL",
            "No EFFECTIVE map panel governs this property.",
        )

    # priority 29: origination happens once per folio
    if (
        body["determination_type"] == "ORIGINATION"
        and folio["current_determination_id"] is not None
    ):
        fail(
            "ERR_ORIGINATION_ALREADY_COMPLETE",
            "This folio already carries an origination determination.",
        )

    community = db.communities[prop["community_id"]]
    determination = build_determination(
        folio,
        structure,
        prop,
        community,
        panel,
        body["determination_type"],
        actor.user_id,
        prior,
    )
    if prior is not None:
        retire_determination(prior)
    adopt_determination(folio, determination)
    touch(folio)
    return created(determination)


@bp.post("/loan-folios/<loan_folio_id>/insurance-reports")
def report_insurance(loan_folio_id):
    actor = authorize(LENDER)
    body = read_body([Field("reported_coverage_cents", "int", min_value=0)])
    folio = must("loan_folios", loan_folio_id)
    _require_owner(actor, folio)

    if folio["insurance_status"] not in ("NONE", "FORCE_PLACED"):
        fail(
            "ERR_INVALID_FOLIO_STATE",
            "Coverage may not be reported while insurance_status is %s."
            % folio["insurance_status"],
        )

    reported = body["reported_coverage_cents"]
    determination = db.determinations.get(folio["current_determination_id"])
    structure = (
        db.structures.get(determination["structure_id"]) if determination else None
    )
    if reported < folio["required_coverage_cents"]:
        fail(
            "ERR_COVERAGE_BELOW_REQUIRED",
            "Reported coverage %d is below the required %d."
            % (reported, folio["required_coverage_cents"]),
        )
    if structure is not None and reported > structure["replacement_cost_cents"]:
        fail(
            "ERR_COVERAGE_BELOW_REQUIRED",
            "Reported coverage %d exceeds the structure's replacement cost %d."
            % (reported, structure["replacement_cost_cents"]),
        )

    was_force_placed = folio["insurance_status"] == "FORCE_PLACED"
    folio["reported_coverage_cents"] = reported
    if was_force_placed:
        settle_escrow(folio)
    folio["insurance_status"] = "BORROWER_PROVIDED"
    supersede_notices(folio, ("MANDATORY_PURCHASE", "FORCE_PLACEMENT_WARNING"))
    touch_folio(folio)
    if was_force_placed:
        lender = db.lenders[folio["lender_id"]]
        recount_open_force_placements(lender)
        touch(lender)
    return ok(folio)


@bp.post("/loan-folios/<loan_folio_id>/force-placements")
def force_place(loan_folio_id):
    actor = authorize(LENDER)
    no_body()
    folio = must("loan_folios", loan_folio_id)
    _require_owner(actor, folio)

    # the action first sweeps this folio's lapsed notices, which is what lets the
    # posture ladder read FORCE_PLACE_ELIGIBLE rather than NOTICE_PENDING
    if expire_lapsed_notices(folio):
        touch_folio(folio)
    else:
        recompute_folio(folio)

    if folio["insurance_status"] != "NONE" or folio["monitoring_status"] == "SUSPENDED":
        fail(
            "ERR_INVALID_FOLIO_STATE",
            "Force placement requires insurance_status NONE on an actively monitored folio.",
        )

    community = folio_community(folio)
    if community["coverage_availability"] == "UNAVAILABLE":
        fail(
            "ERR_COVERAGE_UNAVAILABLE",
            "Federal flood insurance cannot be written in this community.",
        )

    if folio["compliance_posture"] != "FORCE_PLACE_ELIGIBLE":
        fail(
            "ERR_NOTICE_PERIOD_NOT_EXPIRED",
            "The folio is not force-place eligible (posture %s)."
            % folio["compliance_posture"],
        )

    lender = db.lenders[folio["lender_id"]]
    if not lender["force_placement_authorized_flag"]:
        fail(
            "ERR_FORCE_PLACEMENT_NOT_AUTHORIZED",
            "The lender's servicing agreement forbids force placement.",
        )
    if not lender["escrow_servicing_flag"]:
        fail(
            "ERR_FORCE_PLACEMENT_NOT_AUTHORIZED",
            "A non-escrowing lender may not have force-placed premiums debited.",
        )

    notice = latest_mandatory_notice(folio)
    premium, days = calc.chronological_actual(
        notice["annual_premium_rate_cents"], folio["policy_anniversary_date"], db.now()
    )
    if folio["escrow_balance_cents"] < premium:
        fail(
            "ERR_ESCROW_INSUFFICIENT",
            "Escrow holds %d cents but the premium is %d cents."
            % (folio["escrow_balance_cents"], premium),
        )

    now = db.now()
    folio["insurance_status"] = "FORCE_PLACED"
    folio["force_placed_premium_cents"] = premium
    folio["force_placed_coverage_days"] = days
    folio["force_placed_at"] = now
    folio["escrow_balance_cents"] = folio["escrow_balance_cents"] - premium
    if notice["status"] == "SENT":
        notice["status"] = "EXPIRED"
        notice["closed_at"] = now
        touch(notice)
    touch_folio(folio)
    recount_open_force_placements(lender)
    touch(lender)
    return ok(folio)
