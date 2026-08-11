"""Core domain services: clock, corporations, bylaws, directors,
committees, and committee memberships.

Validation ordering follows PRD section 2.11:
  role -> schema -> existence -> ownership -> state -> temporal ->
  compliance -> uniqueness/overlap/capacity -> cross-reference/lifecycle.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    ERR_AUDIT_COMMITTEE_INDEPENDENCE,
    ERR_CROSS_CORPORATION_REFERENCE,
    ERR_DIRECTOR_NOT_ACTIVE,
    ERR_DUPLICATE_EMAIL,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_ROTATION_LIMIT_EXCEEDED,
    ERR_SEAT_CAPACITY_EXCEEDED,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    raise_err,
)
from response import list_response, serialize_row, success_object
from util import (
    SECONDS_PER_DAY,
    check_range_int,
    iso_ms,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def get_or_404(store, row_id, label="Resource"):
    row = store.get(row_id)
    if row is None:
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (label, row_id))
    return row


def adopted_bylaws_for(corporation_id):
    """The corporation's currently ADOPTED bylaws row, or None."""
    corp = db.corporations.get(corporation_id)
    if corp is None:
        return None
    current_id = corp.get("current_bylaws_id")
    if not current_id:
        return None
    row = db.bylaws.get(current_id)
    if row is None or row["status"] != "ADOPTED":
        return None
    return row


def active_directors_of(corporation_id):
    return [
        d
        for d in db.directors.values()
        if d["corporation_id"] == corporation_id and d["status"] == "ACTIVE"
    ]


def has_open_matching_disclosure(director_id, related_party):
    """True when the director holds an OPEN disclosure whose related_party
    matches (a null related_party never matches)."""
    if related_party is None:
        return False
    for disc in db.conflict_disclosures.values():
        if (
            disc["director_id"] == director_id
            and disc["status"] == "OPEN"
            and disc["related_party"] == related_party
        ):
            return True
    return False


def recompute_committee(committee):
    """Refresh active_member_count / chair_vacant and apply the
    ACTIVE <-> BELOW_QUORUM posture rules. Touches the committee."""
    memberships = [
        m
        for m in db.committee_memberships.values()
        if m["committee_id"] == committee["id"] and m["status"] == "ACTIVE"
    ]
    committee["active_member_count"] = len(memberships)
    committee["chair_vacant"] = not any(
        m["committee_role"] == "CHAIR" for m in memberships
    )
    if (
        committee["status"] == "ACTIVE"
        and committee["active_member_count"] < committee["quorum_fixed_count"]
    ):
        committee["status"] = "BELOW_QUORUM"
    elif (
        committee["status"] == "BELOW_QUORUM"
        and committee["active_member_count"] >= committee["quorum_fixed_count"]
    ):
        committee["status"] = "ACTIVE"
    db.touch(committee)


def end_membership(membership, reason):
    membership["status"] = "ENDED"
    membership["ended_reason"] = reason
    db.touch(membership)


def director_departure_cascade(director, ended_reason):
    """End the director's ACTIVE memberships, re-evaluate each affected
    committee, and decrement the corporation's active director count."""
    affected_committee_ids = set()
    for membership in db.committee_memberships.values():
        if membership["director_id"] == director["id"] and membership["status"] == "ACTIVE":
            end_membership(membership, ended_reason)
            affected_committee_ids.add(membership["committee_id"])
    for committee_id in affected_committee_ids:
        committee = db.committees.get(committee_id)
        if committee is not None and committee["status"] != "DISSOLVED":
            recompute_committee(committee)
    corporation = db.corporations.get(director["corporation_id"])
    if corporation is not None:
        corporation["active_director_count"] = max(
            0, corporation.get("active_director_count", 0) - 1
        )
        db.touch(corporation)


# --- Resolution/vote helpers (shared with the meetings and voting modules) ---


def recompute_resolution_tallies(resolution):
    counts = {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0, "RECUSED": 0}
    for vote in db.vote_records.values():
        if vote["resolution_id"] == resolution["id"] and vote["status"] == "ACTIVE":
            counts[vote["vote"]] = counts.get(vote["vote"], 0) + 1
    resolution["for_count"] = counts["FOR"]
    resolution["against_count"] = counts["AGAINST"]
    resolution["abstain_count"] = counts["ABSTAIN"]
    resolution["recused_count"] = counts["RECUSED"]


def void_active_votes(resolution):
    for vote in db.vote_records.values():
        if vote["resolution_id"] == resolution["id"] and vote["status"] == "ACTIVE":
            vote["status"] = "VOIDED"
            db.touch(vote)


def revert_resolution_to_draft(resolution):
    """Agenda-drop / meeting-cancel cascade: TABLED or VOTE_OPEN -> DRAFT,
    voiding ACTIVE ballots."""
    if resolution["status"] not in ("TABLED", "VOTE_OPEN"):
        return
    void_active_votes(resolution)
    resolution["status"] = "DRAFT"
    recompute_resolution_tallies(resolution)
    db.touch(resolution)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_current_utc(body):
    moment = req_datetime(body, "to_iso8601")
    db.set_clock(moment)
    return success_object({"current_utc": iso_ms(db.clock_now())})


# ---------------------------------------------------------------------------
# Corporations
# ---------------------------------------------------------------------------


def create_corporation(body):
    name = req_string(body, "name")
    incorporation_state = req_string(body, "incorporation_state")
    row = db.new_row()
    row.update(
        {
            "name": name,
            "incorporation_state": incorporation_state,
            "current_bylaws_id": None,
            "active_director_count": 0,
        }
    )
    db.corporations[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_corporations(args):
    return list_response(
        db.corporations.values(),
        [("current_bylaws_id", args.get("current_bylaws_id"))],
        args,
    )


def get_corporation(corporation_id):
    return success_object(serialize_row(get_or_404(db.corporations, corporation_id, "Corporation")))


# ---------------------------------------------------------------------------
# Bylaws
# ---------------------------------------------------------------------------


def create_bylaws(body):
    corporation_id = req_string(body, "corporation_id")
    notice_days_regular = check_range_int(req_int(body, "notice_days_regular"), "notice_days_regular", minimum=0)
    notice_days_special = check_range_int(req_int(body, "notice_days_special"), "notice_days_special", minimum=0)
    package_lead_days = check_range_int(req_int(body, "package_lead_days"), "package_lead_days", minimum=0)
    quorum_percent = check_range_int(req_int(body, "quorum_percent"), "quorum_percent", minimum=1, maximum=100)
    quorum_fixed_count = check_range_int(req_int(body, "quorum_fixed_count"), "quorum_fixed_count", minimum=0)
    consent_window_days = check_range_int(req_int(body, "consent_window_days"), "consent_window_days", minimum=1)
    consent_unanimity_required = req_bool(body, "consent_unanimity_required")
    minute_retention_years = check_range_int(req_int(body, "minute_retention_years"), "minute_retention_years", minimum=1)
    rotation_max_years = check_range_int(req_int(body, "rotation_max_years"), "rotation_max_years", minimum=1)
    board_seat_count = check_range_int(req_int(body, "board_seat_count"), "board_seat_count", minimum=1)

    get_or_404(db.corporations, corporation_id, "Corporation")

    existing = [b for b in db.bylaws.values() if b["corporation_id"] == corporation_id]
    version_no = max((b["version_no"] for b in existing), default=0) + 1

    row = db.new_row()
    row.update(
        {
            "corporation_id": corporation_id,
            "version_no": version_no,
            "notice_days_regular": notice_days_regular,
            "notice_days_special": notice_days_special,
            "package_lead_days": package_lead_days,
            "quorum_percent": quorum_percent,
            "quorum_fixed_count": quorum_fixed_count,
            "consent_window_days": consent_window_days,
            "consent_unanimity_required": consent_unanimity_required,
            "minute_retention_years": minute_retention_years,
            "rotation_max_years": rotation_max_years,
            "board_seat_count": board_seat_count,
            "status": "DRAFT",
            "adopted_at": None,
            "superseded_by_id": None,
        }
    )
    db.bylaws[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_bylaws(args):
    return list_response(
        db.bylaws.values(),
        [
            ("corporation_id", args.get("corporation_id")),
            ("superseded_by_id", args.get("superseded_by_id")),
            ("status", args.get("status")),
        ],
        args,
    )


def get_bylaws(bylaws_id):
    return success_object(serialize_row(get_or_404(db.bylaws, bylaws_id, "Bylaws")))


def adopt_bylaws(bylaws_id, body):
    expected_corporation_version = req_int(body, "expected_corporation_version")
    row = get_or_404(db.bylaws, bylaws_id, "Bylaws")
    corporation = get_or_404(db.corporations, row["corporation_id"], "Corporation")

    if row["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT bylaws can be adopted")
    if expected_corporation_version != corporation["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_corporation_version %s does not match corporation version %s"
            % (expected_corporation_version, corporation["version"]),
        )

    prior = None
    if corporation.get("current_bylaws_id"):
        candidate = db.bylaws.get(corporation["current_bylaws_id"])
        if candidate is not None and candidate["status"] == "ADOPTED":
            prior = candidate
    if prior is None:
        for candidate in db.bylaws.values():
            if (
                candidate["corporation_id"] == corporation["id"]
                and candidate["status"] == "ADOPTED"
                and candidate["id"] != row["id"]
            ):
                prior = candidate
                break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = row["id"]
        db.touch(prior)

    corporation["current_bylaws_id"] = row["id"]
    db.touch(corporation)

    row["status"] = "ADOPTED"
    row["adopted_at"] = db.clock_now()
    db.touch(row)
    return success_object(serialize_row(row))


# ---------------------------------------------------------------------------
# Directors
# ---------------------------------------------------------------------------


def _seat_capacity_check(corporation_id, new_start, new_end):
    """Instant-wise occupancy of ACTIVE directors over the proposed
    half-open term; reject when any instant would exceed board_seat_count."""
    bylaws_row = adopted_bylaws_for(corporation_id)
    if bylaws_row is None:
        return  # no adopted bylaws -> capacity unbounded
    seat_count = bylaws_row["board_seat_count"]
    actives = [
        d
        for d in db.directors.values()
        if d["corporation_id"] == corporation_id and d["status"] == "ACTIVE"
    ]
    candidates = {new_start}
    for d in actives:
        if new_start < d["term_start"] < new_end:
            candidates.add(d["term_start"])
    for instant in candidates:
        occupants = sum(
            1 for d in actives if d["term_start"] <= instant < d["term_end"]
        )
        if occupants + 1 > seat_count:
            raise_err(
                ERR_SEAT_CAPACITY_EXCEEDED,
                "Director term would push occupancy above board_seat_count %d"
                % seat_count,
            )


def create_director(body):
    corporation_id = req_string(body, "corporation_id")
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    term_start = req_datetime(body, "term_start")
    term_end = req_datetime(body, "term_end")
    if term_end <= term_start:
        raise_err(ERR_VALIDATION, "term_end must be strictly after term_start")

    get_or_404(db.corporations, corporation_id, "Corporation")

    # Uniqueness / capacity tier (seat capacity first, then email).
    _seat_capacity_check(corporation_id, term_start, term_end)
    for existing in db.directors.values():
        if existing["corporation_id"] == corporation_id and existing["email"] == email:
            raise_err(ERR_DUPLICATE_EMAIL, "Email already used within the corporation")

    row = db.new_row()
    row.update(
        {
            "corporation_id": corporation_id,
            "full_name": full_name,
            "email": email,
            "independence_status": "PENDING_REVIEW",
            "term_start": term_start,
            "term_end": term_end,
            "status": "ACTIVE",
        }
    )
    db.directors[row["id"]] = row

    corporation = db.corporations[corporation_id]
    corporation["active_director_count"] = corporation.get("active_director_count", 0) + 1
    db.touch(corporation)
    return success_object(serialize_row(row), status=201)


def list_directors(args):
    return list_response(
        db.directors.values(),
        [
            ("corporation_id", args.get("corporation_id")),
            ("status", args.get("status")),
            ("independence_status", args.get("independence_status")),
        ],
        args,
    )


def get_director(director_id):
    return success_object(serialize_row(get_or_404(db.directors, director_id, "Director")))


def resign_director(director_id, caller_role, caller_id):
    row = get_or_404(db.directors, director_id, "Director")
    if caller_role == "Director" and caller_id != row["id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "A Director may only resign themselves")
    if row["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE director can resign")
    row["status"] = "RESIGNED"
    db.touch(row)
    director_departure_cascade(row, "DIRECTOR_RESIGNED")
    return success_object(serialize_row(row))


def review_independence(director_id, body):
    independence_status = req_enum(
        body, "independence_status", ("INDEPENDENT", "NON_INDEPENDENT", "PENDING_REVIEW")
    )
    row = get_or_404(db.directors, director_id, "Director")
    row["independence_status"] = independence_status
    db.touch(row)
    return success_object(serialize_row(row))


# ---------------------------------------------------------------------------
# Committees
# ---------------------------------------------------------------------------


def create_committee(body):
    corporation_id = req_string(body, "corporation_id")
    name = req_string(body, "name")
    committee_type = req_enum(
        body, "committee_type", ("AUDIT", "COMPENSATION", "NOMINATING", "SPECIAL")
    )
    charter_text = req_string(body, "charter_text")
    quorum_fixed_count = check_range_int(
        req_int(body, "quorum_fixed_count"), "quorum_fixed_count", minimum=1
    )
    get_or_404(db.corporations, corporation_id, "Corporation")

    row = db.new_row()
    row.update(
        {
            "corporation_id": corporation_id,
            "name": name,
            "committee_type": committee_type,
            "charter_text": charter_text,
            "quorum_fixed_count": quorum_fixed_count,
            "status": "CHARTER_DRAFT",
            "chair_vacant": True,
            "active_member_count": 0,
        }
    )
    db.committees[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_committees(args):
    return list_response(
        db.committees.values(),
        [
            ("corporation_id", args.get("corporation_id")),
            ("status", args.get("status")),
            ("committee_type", args.get("committee_type")),
        ],
        args,
    )


def get_committee(committee_id):
    return success_object(serialize_row(get_or_404(db.committees, committee_id, "Committee")))


def activate_committee(committee_id):
    row = get_or_404(db.committees, committee_id, "Committee")
    if row["status"] != "CHARTER_DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a CHARTER_DRAFT committee can be activated")
    if not row["charter_text"] or not row["charter_text"].strip():
        raise_err(ERR_VALIDATION, "charter_text must be non-empty to activate")
    row["status"] = "ACTIVE"
    db.touch(row)
    return success_object(serialize_row(row))


def dissolve_committee(committee_id):
    row = get_or_404(db.committees, committee_id, "Committee")
    if row["status"] == "DISSOLVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Committee is already DISSOLVED")
    for membership in db.committee_memberships.values():
        if membership["committee_id"] == row["id"] and membership["status"] == "ACTIVE":
            end_membership(membership, "COMMITTEE_DISSOLVED")
    row["status"] = "DISSOLVED"
    row["active_member_count"] = 0
    row["chair_vacant"] = True
    db.touch(row)
    return success_object(serialize_row(row))


# ---------------------------------------------------------------------------
# Committee memberships
# ---------------------------------------------------------------------------


def _rotation_check(committee, director_id, new_start, new_end):
    bylaws_row = adopted_bylaws_for(committee["corporation_id"])
    if bylaws_row is None:
        return  # no adopted bylaws -> rotation unbounded
    max_years = bylaws_row["rotation_max_years"]
    total_seconds = 0
    for membership in db.committee_memberships.values():
        if (
            membership["committee_id"] == committee["id"]
            and membership["director_id"] == director_id
        ):
            total_seconds += int(
                (membership["term_end"] - membership["term_start"]).total_seconds()
            )
    total_seconds += int((new_end - new_start).total_seconds())
    years = Decimal(total_seconds) / Decimal(SECONDS_PER_DAY * 365)
    years = years.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if years > Decimal(max_years):
        raise_err(
            ERR_ROTATION_LIMIT_EXCEEDED,
            "Cumulative tenure %s years exceeds rotation_max_years %s"
            % (years, max_years),
        )


def create_membership(body):
    committee_id = req_string(body, "committee_id")
    director_id = req_string(body, "director_id")
    committee_role = req_enum(body, "committee_role", ("CHAIR", "MEMBER"))
    term_start = req_datetime(body, "term_start")
    term_end = req_datetime(body, "term_end")
    if term_end <= term_start:
        raise_err(ERR_VALIDATION, "term_end must be strictly after term_start")

    committee = get_or_404(db.committees, committee_id, "Committee")
    director = get_or_404(db.directors, director_id, "Director")

    if committee["status"] == "DISSOLVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Cannot add members to a DISSOLVED committee")

    # Compliance tier: AUDIT committees admit INDEPENDENT directors only.
    if committee["committee_type"] == "AUDIT" and director["independence_status"] != "INDEPENDENT":
        raise_err(
            ERR_AUDIT_COMMITTEE_INDEPENDENCE,
            "AUDIT committee members must be INDEPENDENT",
        )

    # Uniqueness / capacity tier: rotation tenure, then single active chair.
    _rotation_check(committee, director_id, term_start, term_end)
    if committee_role == "CHAIR":
        for membership in db.committee_memberships.values():
            if (
                membership["committee_id"] == committee["id"]
                and membership["status"] == "ACTIVE"
                and membership["committee_role"] == "CHAIR"
            ):
                raise_err(ERR_VALIDATION, "Committee already has an ACTIVE chair")

    # Cross-reference / lifecycle tier.
    if director["corporation_id"] != committee["corporation_id"]:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Director and committee belong to different corporations",
        )
    if director["status"] != "ACTIVE":
        raise_err(ERR_DIRECTOR_NOT_ACTIVE, "Director is not ACTIVE")

    row = db.new_row()
    row.update(
        {
            "committee_id": committee_id,
            "director_id": director_id,
            "committee_role": committee_role,
            "term_start": term_start,
            "term_end": term_end,
            "status": "ACTIVE",
            "ended_reason": None,
        }
    )
    db.committee_memberships[row["id"]] = row
    recompute_committee(committee)
    return success_object(serialize_row(row), status=201)


def list_memberships(args):
    return list_response(
        db.committee_memberships.values(),
        [
            ("committee_id", args.get("committee_id")),
            ("director_id", args.get("director_id")),
            ("status", args.get("status")),
        ],
        args,
    )


def get_membership(membership_id):
    return success_object(
        serialize_row(get_or_404(db.committee_memberships, membership_id, "CommitteeMembership"))
    )


def end_membership_endpoint(membership_id):
    row = get_or_404(db.committee_memberships, membership_id, "CommitteeMembership")
    if row["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE membership can be ended")
    end_membership(row, "MANUAL")
    committee = db.committees.get(row["committee_id"])
    if committee is not None and committee["status"] != "DISSOLVED":
        recompute_committee(committee)
    return success_object(serialize_row(row))
