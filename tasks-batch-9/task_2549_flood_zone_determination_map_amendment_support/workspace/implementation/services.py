"""Shared domain services: lookups, full re-counts, notice mechanics, cascades."""
import calc
from db import all_rows, db, new_row, ordered, touch
from errors import fail

NOT_FOUND = {
    "communities": "ERR_COMMUNITY_NOT_FOUND",
    "lenders": "ERR_LENDER_NOT_FOUND",
    "map_panels": "ERR_MAP_PANEL_NOT_FOUND",
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "structures": "ERR_STRUCTURE_NOT_FOUND",
    "loan_folios": "ERR_LOAN_FOLIO_NOT_FOUND",
    "determinations": "ERR_DETERMINATION_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "elevation_certificates": "ERR_ELEVATION_CERTIFICATE_NOT_FOUND",
    "map_amendment_requests": "ERR_MAP_AMENDMENT_REQUEST_NOT_FOUND",
    "compliance_notices": "ERR_COMPLIANCE_NOTICE_NOT_FOUND",
}


def get(collection, row_id):
    if row_id is None:
        return None
    return getattr(db, collection).get(row_id)


def must(collection, row_id):
    row = get(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection], "No %s matches id '%s'." % (collection[:-1], row_id))
    return row


def store(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


# --- navigation ------------------------------------------------------------
def folio_property(folio):
    return db.properties[folio["property_id"]]


def folio_community(folio):
    return db.communities[folio_property(folio)["community_id"]]


def structure_property(structure):
    return db.properties[structure["property_id"]]


def structure_community(structure):
    return db.communities[structure_property(structure)["community_id"]]


def notices_for(folio):
    return [
        n for n in all_rows("compliance_notices") if n["loan_folio_id"] == folio["id"]
    ]


def determinations_for(folio):
    return [
        d for d in all_rows("determinations") if d["loan_folio_id"] == folio["id"]
    ]


def structures_of(prop):
    return [s for s in all_rows("structures") if s["property_id"] == prop["id"]]


# --- full re-counts (never incremental deltas) -----------------------------
def recount_structure_count(prop):
    prop["structure_count"] = len(structures_of(prop))


def recount_active_folio_count(community):
    total = 0
    for folio in all_rows("loan_folios"):
        prop = db.properties.get(folio["property_id"])
        if (
            prop is not None
            and prop["community_id"] == community["id"]
            and folio["monitoring_status"] in ("ACTIVE", "SUSPENDED")
        ):
            total += 1
    community["active_folio_count"] = total


def recount_open_force_placements(lender):
    lender["open_force_placement_count"] = len(
        [
            f
            for f in all_rows("loan_folios")
            if f["lender_id"] == lender["id"] and f["insurance_status"] == "FORCE_PLACED"
        ]
    )


def recompute_folio(folio):
    """Re-derive every computed field of a folio from its inputs."""
    prop = folio_property(folio)
    community = db.communities[prop["community_id"]]
    determination = get("determinations", folio["current_determination_id"])
    structure = (
        get("structures", determination["structure_id"]) if determination else None
    )

    folio["pending_redetermination_count"] = len(
        [d for d in determinations_for(folio) if d["status"] == "FLAGGED_FOR_REVIEW"]
    )
    folio["open_notice_count"] = len(
        [n for n in notices_for(folio) if n["status"] == "SENT"]
    )
    required = calc.required_coverage_cents(determination, structure, folio, community)
    folio["required_coverage_cents"] = required
    folio["uninsured_exposure_cents"] = calc.uninsured_exposure_cents(folio, required)
    folio["compliance_posture"] = calc.compliance_posture(
        folio, community, notices_for(folio)
    )
    return folio


def touch_folio(folio):
    recompute_folio(folio)
    touch(folio)
    return folio


# --- notices ---------------------------------------------------------------
def create_notice(folio, determination, notice_type, annual_premium_rate_cents):
    now = db.now()
    deadline = now + _days(calc.NOTICE_RESPONSE_DAYS[notice_type])
    estimate = calc.forward_looking_estimate_cents(
        annual_premium_rate_cents, folio["policy_anniversary_date"], deadline
    )
    notice = new_row(
        loan_folio_id=folio["id"],
        determination_id=determination["id"],
        notice_type=notice_type,
        annual_premium_rate_cents=annual_premium_rate_cents,
        status="SENT",
        sent_at=now,
        response_deadline_at=deadline,
        required_coverage_snapshot_cents=folio["required_coverage_cents"],
        estimated_force_place_premium_cents=estimate,
        acknowledged_at=None,
        acknowledged_by_role=None,
        closed_at=None,
    )
    return store("compliance_notices", notice)


def _days(count):
    from datetime import timedelta

    return timedelta(days=count)


def supersede_notices(folio, notice_types=None):
    """SENT -> SUPERSEDED for the folio's notices; returns how many closed."""
    now = db.now()
    closed = 0
    for notice in notices_for(folio):
        if notice["status"] != "SENT":
            continue
        if notice_types is not None and notice["notice_type"] not in notice_types:
            continue
        notice["status"] = "SUPERSEDED"
        notice["closed_at"] = now
        touch(notice)
        closed += 1
    return closed


def expire_lapsed_notices(folio):
    """SENT -> EXPIRED for every notice of this folio whose deadline has passed."""
    now = db.now()
    expired = 0
    for notice in notices_for(folio):
        if notice["status"] == "SENT" and notice["response_deadline_at"] < now:
            notice["status"] = "EXPIRED"
            notice["closed_at"] = now
            touch(notice)
            expired += 1
    return expired


def latest_mandatory_notice(folio):
    """The notice that made the folio force-place eligible."""
    candidates = [
        n
        for n in notices_for(folio)
        if n["notice_type"] == "MANDATORY_PURCHASE" and n["status"] in ("SENT", "EXPIRED")
    ]
    best = None
    for notice in ordered(candidates):
        if best is None or notice["sent_at"] > best["sent_at"]:
            best = notice
    return best


# --- determinations --------------------------------------------------------
def build_determination(
    folio, structure, prop, community, panel, determination_type, issued_by, prior
):
    variant = (
        "life_of_loan_lenient"
        if determination_type == "LIFE_OF_LOAN_REVIEW"
        else "origination_strict"
    )
    geometry = calc.classify(structure, prop, panel, variant, prior)
    now = db.now()
    row = new_row(
        loan_folio_id=folio["id"],
        structure_id=structure["id"],
        map_panel_id=panel["id"],
        determination_type=determination_type,
        status="ISSUED",
        position_class=geometry["position_class"],
        zone_code=geometry["zone_code"],
        sfha_flag=geometry["sfha_flag"],
        base_flood_elevation_ft=geometry["base_flood_elevation_ft"],
        freeboard_ft=geometry["freeboard_ft"],
        mandatory_purchase_flag=calc.mandatory_purchase_flag(
            geometry["sfha_flag"], community
        ),
        issued_by_user_id=issued_by,
        supersedes_determination_id=prior["id"] if prior else None,
        superseded_at=None,
        flagged_reason=None,
        issued_at=now,
    )
    return store("determinations", row)


def retire_determination(prior):
    prior["status"] = "SUPERSEDED"
    prior["superseded_at"] = db.now()
    touch(prior)


def adopt_determination(folio, determination, allow_force_placed_release=False):
    """Repoint the folio at a new current determination and react to it."""
    folio["current_determination_id"] = determination["id"]
    mandatory = determination["mandatory_purchase_flag"]
    if folio["insurance_status"] == "NONE" and not mandatory:
        folio["insurance_status"] = "NOT_REQUIRED"
    elif folio["insurance_status"] == "NOT_REQUIRED" and mandatory:
        folio["insurance_status"] = "NONE"
    elif (
        allow_force_placed_release
        and folio["insurance_status"] == "FORCE_PLACED"
        and not mandatory
    ):
        settle_escrow(folio)
        folio["insurance_status"] = "NOT_REQUIRED"
    recompute_folio(folio)


def settle_escrow(folio):
    """Recognise the earned premium and refund the rest (conservation invariant)."""
    now = db.now()
    days_in_force = (now - folio["force_placed_at"]).days
    if days_in_force < 0:
        days_in_force = 0
    earned = calc.earned_premium_cents(
        folio["force_placed_premium_cents"],
        days_in_force,
        folio["force_placed_coverage_days"],
    )
    refund = folio["force_placed_premium_cents"] - earned
    folio["escrow_balance_cents"] = folio["escrow_balance_cents"] + refund
    folio["cumulative_earned_premium_cents"] = (
        folio["cumulative_earned_premium_cents"] + earned
    )
    folio["force_placed_premium_cents"] = 0
    folio["force_placed_coverage_days"] = 0
    folio["force_placed_at"] = None
    return earned, refund


# --- cascades --------------------------------------------------------------
def _folios_of(determinations):
    seen = []
    ids = set()
    for det in determinations:
        folio = get("loan_folios", det["loan_folio_id"])
        if folio is not None and folio["id"] not in ids:
            ids.add(folio["id"])
            seen.append(folio)
    return ordered(seen)


def flag_determinations(candidates, reason):
    """ISSUED -> FLAGGED_FOR_REVIEW for each candidate, then re-posture folios."""
    flagged = []
    for det in candidates:
        if det["status"] != "ISSUED":
            continue
        det["status"] = "FLAGGED_FOR_REVIEW"
        det["flagged_reason"] = reason
        touch(det)
        flagged.append(det)
    for folio in _folios_of(flagged):
        touch_folio(folio)
    return flagged


def panel_effective_cascade(panel):
    """The five-hop panel-effective cascade of PRD section 3.2."""
    now = db.now()

    # HOP 1: the panel itself goes live.
    panel["revision_status"] = "EFFECTIVE"
    touch(panel)

    predecessor = get("map_panels", panel["supersedes_panel_id"])
    if predecessor is None:
        return

    # HOP 2: the predecessor it names is retired.
    predecessor["revision_status"] = "SUPERSEDED"
    predecessor["superseded_at"] = now
    touch(predecessor)

    # HOP 3: determinations citing the predecessor are flagged.
    citing = [
        d
        for d in all_rows("determinations")
        if d["map_panel_id"] == predecessor["id"] and d["status"] == "ISSUED"
    ]
    flagged = []
    for det in citing:
        det["status"] = "FLAGGED_FOR_REVIEW"
        det["flagged_reason"] = "MAP_REVISION"
        touch(det)
        flagged.append(det)

    affected = _folios_of(flagged)

    # HOP 4: their folios re-count and re-posture (REVIEW_PENDING).
    for folio in affected:
        touch_folio(folio)

    # HOP 5: the mandatory-purchase and warning notices they carry are closed.
    for folio in affected:
        closed = supersede_notices(
            folio, ("MANDATORY_PURCHASE", "FORCE_PLACEMENT_WARNING")
        )
        if closed:
            touch_folio(folio)


def geocode_correction_cascade(prop):
    """HOP 2 of the geocode-correction cascade of PRD section 3.4."""
    structure_ids = set(s["id"] for s in structures_of(prop))
    candidates = [
        d
        for d in all_rows("determinations")
        if d["structure_id"] in structure_ids and d["status"] == "ISSUED"
    ]
    return flag_determinations(candidates, "GEOCODE_CORRECTION")


def dispute_sustained_cascade(dispute, determination, resolution):
    """The five-hop dispute-sustained cascade of PRD section 3.9."""
    now = db.now()

    # HOP 1: the dispute is sustained (the row is touched once by the caller).
    dispute["status"] = "SUSTAINED"
    dispute["resolution"] = resolution
    dispute["resolved_at"] = now

    structure = db.structures[determination["structure_id"]]
    folio = db.loan_folios[determination["loan_folio_id"]]
    prop = structure_property(structure)
    community = db.communities[prop["community_id"]]

    # HOP 2: the borrower's asserted offset is written onto the structure.
    structure["sfha_offset_ft"] = dispute["asserted_sfha_offset_ft"]
    touch(structure)

    # HOP 3: the disputed determination is superseded by a DISPUTE_REVISION row
    # recomputed from the corrected offset under the strict variant.
    panel = calc.effective_panel(prop)
    if panel is None:
        panel = db.map_panels[determination["map_panel_id"]]
    retire_determination(determination)
    revision = build_determination(
        folio,
        structure,
        prop,
        community,
        panel,
        "DISPUTE_REVISION",
        "system",
        determination,
    )
    dispute["revised_determination_id"] = revision["id"]

    # HOP 4: the folio adopts it, releasing a force placement when the
    # obligation has gone away.
    adopt_determination(folio, revision, allow_force_placed_release=True)
    touch(folio)
    recount_open_force_placements(db.lenders[folio["lender_id"]])
    touch(db.lenders[folio["lender_id"]])

    # HOP 5: every open notice is closed and a RE_DETERMINATION notice is sent.
    supersede_notices(folio)
    create_notice(folio, revision, "RE_DETERMINATION", 0)
    touch_folio(folio)
    return revision
