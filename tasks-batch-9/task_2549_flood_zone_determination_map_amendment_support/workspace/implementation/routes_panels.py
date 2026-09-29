"""The map timeline and the preliminary-map projection (PRD sections 3.2, 3.3)."""
from datetime import timedelta

from flask import Blueprint

import calc
import enums
from authz import (
    ROLE_AGENCY_OFFICER,
    ROLE_PROVIDER_ANALYST,
    ROLE_PROVIDER_REVIEWER,
    authorize,
)
from db import all_rows, db, new_row, touch
from errors import fail
from response import created, ok
from services import must, panel_effective_cascade, store
from shape import Field, no_body, read_body

bp = Blueprint("panels", __name__)

AGENCY = [ROLE_AGENCY_OFFICER]
PROJECTION_ROLES = [ROLE_PROVIDER_ANALYST, ROLE_PROVIDER_REVIEWER, ROLE_AGENCY_OFFICER]


@bp.post("/map-panels")
def publish_panel():
    authorize(AGENCY)
    body = read_body(
        [
            Field("community_id"),
            Field("map_panel_number"),
            Field("revision_sequence", "int", min_value=1),
            Field("zone_code", "enum", enum=enums.PANEL_ZONE_CODES),
            Field("base_flood_elevation_ft", "number", scale=2, nullable=True),
            Field("effective_date", "datetime"),
            Field(
                "supersedes_panel_id", "string", required=False, default=None,
                nullable=True,
            ),
            Field("sfha_boundary_shift_ft", "number", required=False, default=0),
            Field(
                "horizontal_uncertainty_ft", "number", required=False, default=0,
                min_value=0,
            ),
            Field("study_case_number", "string", required=False, default=None, nullable=True),
        ]
    )
    # body foreign keys resolve in declared order
    must("communities", body["community_id"])
    predecessor = None
    if body["supersedes_panel_id"] is not None:
        predecessor = must("map_panels", body["supersedes_panel_id"])

    community_id = body["community_id"]
    number = body["map_panel_number"]
    sequence = body["revision_sequence"]
    timeline = [
        p
        for p in all_rows("map_panels")
        if p["community_id"] == community_id and p["map_panel_number"] == number
    ]

    for panel in timeline:
        if panel["revision_sequence"] == sequence:
            fail(
                "ERR_PANEL_SEQUENCE_INVALID",
                "revision_sequence %d already exists for this map timeline." % sequence,
            )

    if sequence == 1:
        if predecessor is not None:
            fail(
                "ERR_PANEL_SEQUENCE_INVALID",
                "An initial FIRM may not name a superseded panel.",
            )
        for panel in timeline:
            if panel["revision_status"] == "EFFECTIVE":
                fail(
                    "ERR_PANEL_SEQUENCE_INVALID",
                    "An EFFECTIVE panel already exists for this map timeline.",
                )
    else:
        if predecessor is None:
            fail(
                "ERR_PANEL_SEQUENCE_INVALID",
                "A revision panel must name the panel it supersedes.",
            )
        if (
            predecessor["community_id"] != community_id
            or predecessor["map_panel_number"] != number
            or predecessor["revision_status"] != "EFFECTIVE"
            or predecessor["revision_sequence"] != sequence - 1
        ):
            fail(
                "ERR_PANEL_SEQUENCE_INVALID",
                "supersedes_panel_id must name the EFFECTIVE panel of this timeline "
                "whose revision_sequence is exactly one less.",
            )

    row = new_row(
        community_id=community_id,
        map_panel_number=number,
        revision_sequence=sequence,
        supersedes_panel_id=body["supersedes_panel_id"],
        revision_status="EFFECTIVE" if sequence == 1 else "PRELIMINARY",
        zone_code=body["zone_code"],
        base_flood_elevation_ft=body["base_flood_elevation_ft"],
        sfha_boundary_shift_ft=body["sfha_boundary_shift_ft"],
        horizontal_uncertainty_ft=body["horizontal_uncertainty_ft"],
        effective_date=body["effective_date"],
        appeal_period_end_date=None,
        lfd_issued_at=None,
        superseded_at=None,
        revision_round=0,
        study_case_number=body["study_case_number"],
    )
    return created(store("map_panels", row))


@bp.post("/map-panels/<map_panel_id>/appeal-period")
def open_appeal_period(map_panel_id):
    authorize(AGENCY)
    body = read_body(
        [Field("appeal_period_end_date", "datetime", required=False, default=None)]
    )
    panel = must("map_panels", map_panel_id)
    if panel["revision_status"] != "PRELIMINARY" or panel["revision_sequence"] < 2:
        fail(
            "ERR_INVALID_PANEL_STATE",
            "Only a PRELIMINARY revision panel may open an appeal period.",
        )
    end = body["appeal_period_end_date"]
    if end is None:
        end = db.now() + timedelta(days=calc.APPEAL_PERIOD_DAYS)
    panel["appeal_period_end_date"] = end
    panel["revision_status"] = "APPEAL_OPEN"
    touch(panel)
    return ok(panel)


@bp.post("/map-panels/<map_panel_id>/appeal-decision")
def decide_appeal(map_panel_id):
    authorize(AGENCY)
    body = read_body([Field("outcome", "enum", enum=enums.APPEAL_OUTCOMES)])
    panel = must("map_panels", map_panel_id)
    if panel["revision_status"] != "APPEAL_OPEN":
        fail(
            "ERR_INVALID_PANEL_STATE",
            "An appeal decision requires a panel in APPEAL_OPEN.",
        )
    now = db.now()
    end = panel["appeal_period_end_date"]
    if end is None or now < end:
        fail(
            "ERR_APPEAL_PERIOD_OPEN",
            "The posted appeal period has not closed yet.",
        )
    if body["outcome"] == "REVISED_PRELIMINARY":
        panel["revision_status"] = "PRELIMINARY"
        panel["revision_round"] = panel["revision_round"] + 1
        panel["appeal_period_end_date"] = None
    else:
        panel["revision_status"] = "LFD_ISSUED"
        panel["lfd_issued_at"] = now
    touch(panel)
    return ok(panel)


@bp.post("/map-panels/<map_panel_id>/effective")
def make_panel_effective(map_panel_id):
    authorize(AGENCY)
    no_body()
    panel = must("map_panels", map_panel_id)
    if panel["revision_status"] != "LFD_ISSUED":
        fail(
            "ERR_INVALID_PANEL_STATE",
            "Only a panel in LFD_ISSUED may be made effective.",
        )
    now = db.now()
    end = panel["appeal_period_end_date"]
    lfd = panel["lfd_issued_at"]
    if (
        end is None
        or end > now
        or lfd is None
        or lfd + timedelta(days=calc.LFD_WAITING_PERIOD_DAYS) > now
    ):
        fail(
            "ERR_LFD_WAITING_PERIOD",
            "The letter-of-final-determination waiting period has not elapsed.",
        )
    predecessor = db.map_panels.get(panel["supersedes_panel_id"])
    if panel["effective_date"] > now or (
        predecessor is not None
        and panel["effective_date"] <= predecessor["effective_date"]
    ):
        fail(
            "ERR_PANEL_EFFECTIVE_DATE_OVERLAP",
            "The panel's effective_date does not satisfy the half-open interval rule.",
        )
    panel_effective_cascade(panel)
    return ok(panel)


@bp.get("/map-panels/<map_panel_id>/impact-analysis")
def impact_analysis(map_panel_id):
    authorize(PROJECTION_ROLES)
    panel = must("map_panels", map_panel_id)
    if panel["revision_status"] not in ("PRELIMINARY", "APPEAL_OPEN", "LFD_ISSUED"):
        fail(
            "ERR_PANEL_NOT_PRELIMINARY",
            "A live panel is not a hypothesis; the projection requires a "
            "PRELIMINARY, APPEAL_OPEN or LFD_ISSUED panel.",
        )
    community = db.communities[panel["community_id"]]
    property_ids = set(
        p["id"]
        for p in all_rows("properties")
        if p["community_id"] == panel["community_id"]
        and p["map_panel_number"] == panel["map_panel_number"]
        and p["geocode_status"] == "GEOCODED"
    )

    structures_evaluated = 0
    newly_in = 0
    newly_out = 0
    bfe_increase = 0
    notice_folio_ids = set()
    aggregate = 0

    for structure in all_rows("structures"):
        if structure["property_id"] not in property_ids:
            continue
        folio = None
        current = None
        for candidate in all_rows("loan_folios"):
            if candidate["property_id"] != structure["property_id"]:
                continue
            determination = db.determinations.get(candidate["current_determination_id"])
            if determination is not None and determination["structure_id"] == structure["id"]:
                folio = candidate
                current = determination
                break
        if folio is None or current is None:
            continue
        structures_evaluated += 1
        prop = db.properties[structure["property_id"]]
        prospect = calc.classify(structure, prop, panel, "origination_strict")
        if not current["sfha_flag"] and prospect["sfha_flag"]:
            newly_in += 1
            if folio["insurance_status"] in ("NONE", "NOT_REQUIRED"):
                notice_folio_ids.add(folio["id"])
            aggregate += calc.required_coverage_cents(
                prospect, structure, folio, community
            )
        elif current["sfha_flag"] and not prospect["sfha_flag"]:
            newly_out += 1
        if (
            current["base_flood_elevation_ft"] is not None
            and panel["base_flood_elevation_ft"] is not None
            and calc.dec(panel["base_flood_elevation_ft"])
            > calc.dec(current["base_flood_elevation_ft"])
        ):
            bfe_increase += 1

    return ok(
        {
            "map_panel_id": panel["id"],
            "revision_status": panel["revision_status"],
            "structures_evaluated": structures_evaluated,
            "newly_in_sfha_count": newly_in,
            "newly_out_of_sfha_count": newly_out,
            "bfe_increase_count": bfe_increase,
            "folios_requiring_new_notice_count": len(notice_folio_ids),
            "aggregate_new_required_coverage_cents": aggregate,
        }
    )
