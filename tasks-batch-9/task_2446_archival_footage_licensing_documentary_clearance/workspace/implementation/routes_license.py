"""Licences, negotiation rounds, execution (MFN settlement) and renewal."""
from fractions import Fraction

from flask import Blueprint, g, request

import core
from calc import (NEGOTIATION_ROUND_LIMIT, RENEWAL_WINDOW_DAYS, billable_units_for,
                  license_rate_card_fee_cents, round_half_up)
from core import (ROLE_ARCHIVE_RESEARCHER, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL,
                  ROLE_PRODUCTION_ADMIN, ROLE_RIGHTS_HOLDER_REP, add_months, body, by_seq, created,
                  db, days_between, fail, guard, invalid, is_int, iso_date, new_row, ok, ok_list,
                  opt_str, pagination, parse_date, public, req_date, req_enum, req_int, req_str,
                  term_months_consistent, touch)
from domain import (LIVE_COVERAGE, active_rate_card, candidates_of_asset, get_archive, get_asset,
                    get_license, get_production, has_term_overlap, licenses_of_asset,
                    recompute_production, rollup_asset)

bp = Blueprint("licenses", __name__)

RIGHTS_LEGS = ("FOOTAGE", "MASTER", "PUBLISHING")
MEDIA = ("THEATRICAL", "BROADCAST", "STREAMING", "ALL_MEDIA")
TERRITORIES = ("WORLD", "DOMESTIC")
WINDOW_CLASSES = ("FESTIVAL_ONLY", "ALL_MEDIA_WINDOW")
LICENSE_STATUSES = ("DRAFT", "QUOTED", "COUNTERED", "EXECUTED", "ACTIVE", "EXPIRING", "EXPIRED",
                    "TERMINATED", "LAPSED")
PARTIES = ("LICENSOR", "PRODUCER")


def _body_fk(data, key, resolver):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        invalid("Field '%s' is required and must be a non-empty string." % key)
    return resolver(value)


@bp.post("/licenses")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def create_license():
    data = body()

    # rung 6 — body foreign keys, left to right in declaration order
    production = _body_fk(data, "production_id", get_production)
    asset = _body_fk(data, "asset_id", get_asset)
    archive = _body_fk(data, "archive_id", get_archive)

    # rung 7 — body well-formedness
    rights_leg = req_enum(data, "rights_leg", RIGHTS_LEGS)
    media = req_enum(data, "media", MEDIA)
    territory = req_enum(data, "territory", TERRITORIES)
    window_class = req_enum(data, "window_class", WINDOW_CLASSES)
    term_months = req_int(data, "term_months", minimum=1)
    term_start = req_date(data, "term_start_date")
    term_end = req_date(data, "term_end_date")
    if "mfn_requested" in data and data["mfn_requested"] is not None:
        if not isinstance(data["mfn_requested"], bool):
            invalid("Field 'mfn_requested' must be a boolean.")
        mfn_requested = data["mfn_requested"]
    else:
        mfn_requested = archive["mfn_policy"] == "RATE_MFN"

    # rung 11
    if production["status"] not in ("DEVELOPMENT", "CLEARANCE"):
        fail("ERR_PRODUCTION_NOT_IN_CLEARANCE",
             "A %s production accepts no new licences." % production["status"])

    # rung 13
    if rights_leg == "FOOTAGE":
        selected = [c for c in candidates_of_asset(asset["id"])
                    if c["selection_status"] == "SELECTED"]
        if len(selected) != 1:
            fail("ERR_NO_SELECTED_SOURCE",
                 "A FOOTAGE leg requires exactly one SELECTED source candidate.")
        if selected[0]["archive_id"] != archive["id"]:
            fail("ERR_NO_SELECTED_SOURCE",
                 "The licence archive does not hold the selected source element.")

    # rung 16
    if archive["status"] != "ACTIVE":
        fail("ERR_ARCHIVE_SUSPENDED", "A SUSPENDED archive may not receive a new licence.")

    # rung 17
    if asset["production_id"] != production["id"]:
        fail("ERR_ASSET_PRODUCTION_MISMATCH",
             "The asset does not belong to the named production.")

    # rung 18
    card = active_rate_card(archive["id"], term_start)
    if card is None:
        fail("ERR_NO_ACTIVE_RATE_CARD",
             "The archive has no ACTIVE rate card effective on or before the term start.")

    # rung 36
    legal_legs = ("MASTER", "PUBLISHING") if asset["asset_type"] == "MUSIC" else ("FOOTAGE",)
    if rights_leg not in legal_legs:
        fail("ERR_MUSIC_LEG_REQUIRED",
             "A %s asset does not take a %s leg." % (asset["asset_type"], rights_leg))

    # rung 37
    if not (term_start < term_end) or not term_months_consistent(term_start, term_end,
                                                                term_months):
        fail("ERR_TERM_DATES_INVALID",
             "term_start_date, term_end_date and term_months are not coherent.")

    # rung 38
    if has_term_overlap(asset["id"], rights_leg, media, territory, term_start, term_end):
        fail("ERR_LICENSE_TERM_OVERLAP",
             "A live sibling licence already covers this leg, media, territory and term.")

    fee, units = license_rate_card_fee_cents(asset["duration_seconds"], media, territory,
                                             window_class, term_months, card)
    row = new_row()
    row.update({
        "production_id": production["id"],
        "asset_id": asset["id"],
        "archive_id": archive["id"],
        "rate_card_id": card["id"],
        "rights_leg": rights_leg,
        "media": media,
        "territory": territory,
        "window_class": window_class,
        "term_months": term_months,
        "term_start_date": iso_date(term_start),
        "term_end_date": iso_date(term_end),
        "billable_units": units,
        "rate_card_fee_cents": fee,
        "current_proposed_fee_cents": fee,
        "mfn_requested": mfn_requested,
        "mfn_benchmark_fee_cents": 0,
        "mfn_topup_cents": 0,
        "executed_fee_cents": None,
        "round_count": 0,
        "status": "DRAFT",
        "termination_reason": None,
    })
    db.licenses[row["id"]] = row

    rollup_asset(asset)
    recompute_production(production)
    touch(production)
    return created(public(row))


@bp.get("/licenses/<lid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_RIGHTS_HOLDER_REP,
       ROLE_LEGAL_COUNSEL)
def read_license(lid):
    lic = get_license(lid)
    _own_license_or_fail(lic)
    return ok(public(lic))


@bp.get("/licenses")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL,
       ROLE_ARCHIVE_RESEARCHER)
def list_licenses():
    limit, offset = pagination()
    rows = by_seq(list(db.licenses.values()))
    for key in ("production_id", "asset_id", "archive_id", "rate_card_id", "rights_leg",
                "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    cutoff = request.args.get("term_end_on_or_before")
    if cutoff:
        limit_date = parse_date(cutoff, "term_end_on_or_before")
        rows = [r for r in rows
                if parse_date(r["term_end_date"], "term_end_date") <= limit_date]
    return ok_list([public(r) for r in rows], limit, offset)


def _own_license_or_fail(lic):
    if g.role == ROLE_RIGHTS_HOLDER_REP and g.user_id != lic["archive_id"]:
        fail("ERR_ARCHIVE_OWNERSHIP_MISMATCH",
             "A RightsHolderRep may only act on its own archive's licences.")


# --- negotiation rounds -----------------------------------------------------
@bp.post("/licenses/<lid>/negotiation-rounds")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_RIGHTS_HOLDER_REP)
def create_round(lid):
    lic = get_license(lid)
    _own_license_or_fail(lic)
    data = body()

    party = req_enum(data, "party", PARTIES)
    proposed = req_int(data, "proposed_fee_cents", minimum=0)
    if "expected_license_version" not in data or not is_int(data["expected_license_version"]):
        invalid("Field 'expected_license_version' is required and must be an integer.")
    expected = data["expected_license_version"]
    note = opt_str(data, "note")

    # rung 9
    if expected != lic["version"]:
        fail("ERR_STALE_LICENSE_VERSION",
             "expected_license_version %s does not match the licence version %s."
             % (expected, lic["version"]))

    # rung 33 — the party/role pairing is the rung the precedence ladder scopes to
    # appending a negotiation round; rung 10 is scoped to the eight state-driving
    # operations, so it may not pre-empt this check.
    if party == "LICENSOR" and g.role != ROLE_RIGHTS_HOLDER_REP:
        fail("ERR_PARTY_ROLE_MISMATCH", "A LICENSOR round requires the RightsHolderRep role.")
    if party == "PRODUCER" and g.role not in (ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR):
        fail("ERR_PARTY_ROLE_MISMATCH",
             "A PRODUCER round requires ProductionAdmin or ClearanceSupervisor.")

    if party == "LICENSOR" and lic["status"] in ("DRAFT", "COUNTERED"):
        next_status = "QUOTED"
    elif party == "PRODUCER" and lic["status"] == "QUOTED":
        next_status = "COUNTERED"
    else:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A %s round is not available on a licence in %s." % (party, lic["status"]))

    # rung 34
    if lic["round_count"] >= NEGOTIATION_ROUND_LIMIT:
        fail("ERR_NEGOTIATION_ROUND_LIMIT",
             "A licence supports at most %d negotiation rounds." % NEGOTIATION_ROUND_LIMIT)

    round_number = lic["round_count"] + 1
    lic["round_count"] = round_number
    lic["current_proposed_fee_cents"] = proposed
    lic["status"] = next_status
    touch(lic)

    row = new_row(with_version=False)
    row.update({
        "license_id": lic["id"],
        "round_number": round_number,
        "party": party,
        "proposed_fee_cents": proposed,
        "note": note,
        "license_status_after": lic["status"],
        "license_version_after": lic["version"],
    })
    db.negotiation_rounds[row["id"]] = row
    return created(public(row))


@bp.get("/licenses/<lid>/negotiation-rounds")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_RIGHTS_HOLDER_REP,
       ROLE_LEGAL_COUNSEL)
def list_rounds(lid):
    get_license(lid)
    limit, offset = pagination()
    rows = sorted([r for r in db.negotiation_rounds.values() if r["license_id"] == lid],
                  key=lambda r: r["round_number"])
    return ok_list([public(r) for r in rows], limit, offset)


# --- execution / lapse / termination ---------------------------------------
def _settle_mfn(lic):
    base = max(lic["current_proposed_fee_cents"], lic["rate_card_fee_cents"])
    peers = [p for p in licenses_of_asset(lic["asset_id"])
             if p["id"] != lic["id"] and p["mfn_requested"]
             and p["status"] in LIVE_COVERAGE and p["executed_fee_cents"] is not None]

    if not lic["mfn_requested"] or not peers:
        benchmark = 0
    else:
        best = max(Fraction(p["executed_fee_cents"], p["billable_units"]) for p in peers)
        benchmark = round_half_up(best * lic["billable_units"])

    executed = max(base, benchmark)
    lic["mfn_benchmark_fee_cents"] = benchmark
    lic["executed_fee_cents"] = executed

    own_rate = Fraction(executed, lic["billable_units"])
    for peer in peers:  # created_at ASC
        peer_rate = Fraction(peer["executed_fee_cents"], peer["billable_units"])
        if peer_rate < own_rate:
            target = round_half_up(own_rate * peer["billable_units"])
            topup = target - peer["executed_fee_cents"]
            peer["mfn_topup_cents"] += topup
            peer["executed_fee_cents"] = target
            touch(peer)


@bp.post("/licenses/<lid>/state")
@guard(ROLE_CLEARANCE_SUPERVISOR, ROLE_PRODUCTION_ADMIN, ROLE_RIGHTS_HOLDER_REP)
def license_state(lid):
    lic = get_license(lid)
    _own_license_or_fail(lic)
    data = body()
    to_status = req_enum(data, "to_status", LICENSE_STATUSES)
    reason = opt_str(data, "reason")

    production = get_production(lic["production_id"])
    asset = get_asset(lic["asset_id"])
    current = lic["status"]

    if to_status == "EXECUTED":
        # rung 12 displaces the generic invalid-transition answer
        if current != "QUOTED":
            fail("ERR_LICENSE_NOT_QUOTED",
                 "Execution is only reachable from QUOTED (licence is %s)." % current)
        archive = get_archive(lic["archive_id"])
        if archive["status"] != "ACTIVE":
            fail("ERR_ARCHIVE_SUSPENDED",
                 "A licence cannot be executed against a SUSPENDED holder.")
        if production["status"] != "CLEARANCE":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The production must be in CLEARANCE to execute a licence.")
        if has_term_overlap(lic["asset_id"], lic["rights_leg"], lic["media"], lic["territory"],
                            parse_date(lic["term_start_date"], "term_start_date"),
                            parse_date(lic["term_end_date"], "term_end_date"),
                            exclude_id=lic["id"]):
            fail("ERR_LICENSE_TERM_OVERLAP",
                 "The term now conflicts with a live sibling licence.")
        _settle_mfn(lic)
        lic["status"] = "EXECUTED"
    elif to_status == "LAPSED":
        if current not in ("QUOTED", "COUNTERED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A licence in %s cannot lapse." % current)
        lic["status"] = "LAPSED"
    elif to_status == "TERMINATED":
        if current not in ("EXECUTED", "ACTIVE", "EXPIRING"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A licence in %s cannot be terminated." % current)
        lic["status"] = "TERMINATED"
        lic["termination_reason"] = reason
    else:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not requestable through this endpoint." % to_status)

    touch(lic)
    rollup_asset(asset)
    recompute_production(production)
    touch(production)
    return ok(public(lic))


# --- renewal ----------------------------------------------------------------
@bp.post("/licenses/<lid>/renew")
@guard(ROLE_CLEARANCE_SUPERVISOR)
def renew_license(lid):
    lic = get_license(lid)
    data = body()

    additional = data.get("additional_term_months")
    if additional is not None and not is_int(additional):
        invalid("Field 'additional_term_months' must be an integer.")

    # rung 12
    if lic["status"] not in ("ACTIVE", "EXPIRING"):
        fail("ERR_LICENSE_NOT_QUOTED",
             "Only an ACTIVE or EXPIRING licence may be renewed (licence is %s)."
             % lic["status"])

    production = get_production(lic["production_id"])
    term_start = parse_date(lic["term_start_date"], "term_start_date")
    term_end = parse_date(lic["term_end_date"], "term_end_date")

    # rung 18
    if active_rate_card(lic["archive_id"], term_start) is None:
        fail("ERR_NO_ACTIVE_RATE_CARD",
             "The archive has no ACTIVE rate card effective on or before the term start.")

    # rung 38 — the extended term must still stand clear of live siblings
    months = additional if is_int(additional) else 0
    new_end = add_months(term_end, months)
    if has_term_overlap(lic["asset_id"], lic["rights_leg"], lic["media"], lic["territory"],
                        term_start, new_end, exclude_id=lic["id"]):
        fail("ERR_LICENSE_TERM_OVERLAP",
             "The extended term conflicts with a live sibling licence.")

    # rung 40
    distance = days_between(core.clock_date(), term_end)
    if not (0 <= distance <= RENEWAL_WINDOW_DAYS):
        fail("ERR_OUTSIDE_RENEWAL_WINDOW",
             "Renewal is only permitted within %d days of the term end."
             % RENEWAL_WINDOW_DAYS)

    # rung 41
    if additional is None or additional < 1:
        fail("ERR_INVALID_RENEWAL_TERM", "additional_term_months must be at least 1.")

    card = db.rate_cards[lic["rate_card_id"]]
    old_fee = lic["rate_card_fee_cents"]
    asset = get_asset(lic["asset_id"])
    lic["term_months"] += additional
    lic["term_end_date"] = iso_date(new_end)
    new_fee, units = license_rate_card_fee_cents(asset["duration_seconds"], lic["media"],
                                                 lic["territory"], lic["window_class"],
                                                 lic["term_months"], card)
    lic["billable_units"] = units
    lic["rate_card_fee_cents"] = new_fee
    delta = max(0, new_fee - old_fee)
    if lic["executed_fee_cents"] is not None:
        lic["executed_fee_cents"] += delta
    if lic["status"] == "EXPIRING":
        lic["status"] = "ACTIVE"
    touch(lic)

    recompute_production(production)
    touch(production)
    return ok(public(lic))
