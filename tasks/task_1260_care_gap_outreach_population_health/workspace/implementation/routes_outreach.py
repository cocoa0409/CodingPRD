"""Routes: campaigns, outreach attempts, appointments, transportation assists."""

import db
import errors as E
import domain as D
import util as U
from errors import ApiError
from routes_registry import PA, PM, QR, TC, DRB, ALL_ROLES, READ4, _get

CHANNELS = {"CALL", "TEXT", "MAIL"}
OUTCOMES = {"CONTACTED", "LEFT_MESSAGE", "NO_ANSWER", "BAD_ADDRESS", "REFUSED", "REVERSED"}


def _in_quiet_hours(dt, campaign):
    mins = dt.hour * 60 + dt.minute
    return mins >= campaign["quiet_hours_start_min"] or mins < campaign["quiet_hours_end_min"]


def _active_appointments_for_provider(provider_id, exclude_id=None):
    return [
        a
        for a in db.appointments.values()
        if a["provider_id"] == provider_id
        and a["status"] in ("SCHEDULED", "CONFIRMED")
        and a["id"] != exclude_id
    ]


def _slots_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _check_provider_capacity(provider_id, capacity, slot_start, slot_end, exclude_id=None):
    overlapping = [
        a
        for a in _active_appointments_for_provider(provider_id, exclude_id)
        if _slots_overlap(a["slot_start_at"], a["slot_end_at"], slot_start, slot_end)
    ]
    if len(overlapping) >= capacity:
        raise ApiError(
            E.ERR_PROVIDER_SLOT_FULL,
            "Overlapping appointment would exceed provider_capacity_per_slot",
            409,
        )


def _check_slot_valid(slot_start, slot_end, now):
    if not (slot_start < slot_end) or slot_start < now:
        raise ApiError(
            E.ERR_INVALID_SLOT,
            "slot_start_at must be strictly before slot_end_at and not in the past",
            400,
        )


def register_routes(app):

    # --------------------------------------------------------------- campaigns
    @app.route("/population-health/registries/<rid>/outreach-campaigns", methods=["POST"])
    def create_campaign(rid):
        body = U.get_body()
        panel_id = U.req_str(body, "panel_id")
        measure_id = U.req_str(body, "measure_id")
        name = U.req_str(body, "name")
        channel = U.req_enum(body, "channel", CHANNELS)
        starts_at = U.req_dt(body, "starts_at")
        ends_at = U.req_dt(body, "ends_at")
        quiet_hours_start_min = U.opt_int(body, "quiet_hours_start_min", 1260)
        quiet_hours_end_min = U.opt_int(body, "quiet_hours_end_min", 480)
        min_attempt_interval_hours = U.opt_int(body, "min_attempt_interval_hours", 72)
        max_attempts_per_member = U.opt_int(body, "max_attempts_per_member", 5)
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, rid, "PopulationRegistry")
        panel = db.panels.get(panel_id)
        if panel is None or panel["registry_id"] != rid:
            raise ApiError(E.ERR_INVALID_REQUEST, "panel_id does not reference a panel in this registry", 400)
        measure = db.measures.get(measure_id)
        if measure is None or measure["registry_id"] != rid:
            raise ApiError(E.ERR_INVALID_REQUEST, "measure_id does not reference a measure in this registry", 400)
        now = D.clock_of(registry)
        c = {
            "registry_id": rid,
            "panel_id": panel_id,
            "measure_id": measure_id,
            "name": name,
            "channel": channel,
            "quiet_hours_start_min": quiet_hours_start_min,
            "quiet_hours_end_min": quiet_hours_end_min,
            "min_attempt_interval_hours": min_attempt_interval_hours,
            "max_attempts_per_member": max_attempts_per_member,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "DRAFT",
        }
        D.stamp_new(c, now)
        db.campaigns[c["id"]] = c
        return U.success_object(D.ser_campaign(c), 201)

    def _campaign_or_404(cid):
        return _get(db.campaigns, cid, "OutreachCampaign")

    @app.route("/population-health/outreach-campaigns/<cid>/schedule", methods=["POST"])
    def schedule_campaign(cid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _campaign_or_404(cid)
        if c["status"] != "DRAFT":
            raise ApiError(E.ERR_INVALID_STATE, "Only a DRAFT campaign can be scheduled", 409)
        now = D.clock_of(db.registries[c["registry_id"]])
        if not (c["starts_at"] < c["ends_at"]):
            raise ApiError(
                E.ERR_INVALID_CAMPAIGN_WINDOW, "starts_at must be strictly before ends_at", 400
            )
        if not (c["ends_at"] > now):
            raise ApiError(
                E.ERR_CAMPAIGN_WINDOW_PAST, "The campaign window lies entirely in the past", 409
            )
        c["status"] = "SCHEDULED"
        D.bump(c, now)
        return U.success_object(D.ser_campaign(c), 200)

    @app.route("/population-health/outreach-campaigns/<cid>/launch", methods=["POST"])
    def launch_campaign(cid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _campaign_or_404(cid)
        if c["status"] != "SCHEDULED":
            raise ApiError(E.ERR_INVALID_STATE, "Only a SCHEDULED campaign can be launched", 409)
        now = D.clock_of(db.registries[c["registry_id"]])
        if now < c["starts_at"]:
            raise ApiError(
                E.ERR_CAMPAIGN_NOT_YET_OPEN, "The campaign has not reached its starts_at", 409
            )
        panel = db.panels.get(c["panel_id"])
        if panel is None or panel["status"] != "ACTIVE":
            raise ApiError(
                E.ERR_PANEL_NOT_ACTIVE, "The linked RegistryPanel must be ACTIVE to launch", 409
            )
        c["status"] = "ACTIVE"
        D.bump(c, now)
        return U.success_object(D.ser_campaign(c), 200)

    @app.route("/population-health/outreach-campaigns/<cid>/pause", methods=["POST"])
    def pause_campaign(cid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _campaign_or_404(cid)
        if c["status"] != "ACTIVE":
            raise ApiError(E.ERR_INVALID_STATE, "Only an ACTIVE campaign can be paused", 409)
        now = D.clock_of(db.registries[c["registry_id"]])
        c["status"] = "PAUSED"
        D.bump(c, now)
        return U.success_object(D.ser_campaign(c), 200)

    @app.route("/population-health/outreach-campaigns/<cid>/resume", methods=["POST"])
    def resume_campaign(cid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _campaign_or_404(cid)
        if c["status"] != "PAUSED":
            raise ApiError(E.ERR_INVALID_STATE, "Only a PAUSED campaign can be resumed", 409)
        now = D.clock_of(db.registries[c["registry_id"]])
        if now >= c["ends_at"]:
            raise ApiError(
                E.ERR_CAMPAIGN_WINDOW_PAST, "The campaign window has already passed", 409
            )
        c["status"] = "ACTIVE"
        D.bump(c, now)
        return U.success_object(D.ser_campaign(c), 200)

    @app.route("/population-health/outreach-campaigns/<cid>/complete", methods=["POST"])
    def complete_campaign(cid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _campaign_or_404(cid)
        if c["status"] not in ("ACTIVE", "PAUSED"):
            raise ApiError(
                E.ERR_INVALID_STATE, "Only an ACTIVE or PAUSED campaign can be completed", 409
            )
        now = D.clock_of(db.registries[c["registry_id"]])
        c["status"] = "COMPLETED"
        D.bump(c, now)
        return U.success_object(D.ser_campaign(c), 200)

    @app.route("/population-health/outreach-campaigns/<cid>/cancel", methods=["POST"])
    def cancel_campaign(cid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _campaign_or_404(cid)
        if c["status"] not in ("DRAFT", "SCHEDULED", "ACTIVE", "PAUSED"):
            raise ApiError(E.ERR_INVALID_STATE, "This campaign can no longer be cancelled", 409)
        now = D.clock_of(db.registries[c["registry_id"]])
        c["status"] = "CANCELLED"
        D.bump(c, now)
        return U.success_object(D.ser_campaign(c), 200)

    @app.route("/population-health/registries/<rid>/outreach-campaigns", methods=["GET"])
    def list_campaigns_in_registry(rid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.registries, rid, "PopulationRegistry")
        limit, offset = U.pagination_params()
        items = [c for c in db.campaigns.values() if c["registry_id"] == rid]
        items = U.apply_filters(items, [("status", "status")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_campaign(c) for c in page], total, limit, offset)

    @app.route("/population-health/outreach-campaigns/<cid>", methods=["GET"])
    def get_campaign(cid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        c = _campaign_or_404(cid)
        return U.success_object(D.ser_campaign(c), 200)

    # ---------------------------------------------------------------- attempts
    @app.route("/population-health/care-gaps/<gid>/outreach-attempts", methods=["POST"])
    def create_attempt(gid):
        body = U.get_body()
        campaign_id = U.req_str(body, "campaign_id")
        channel = U.req_enum(body, "channel", CHANNELS)
        outcome = U.req_enum(body, "outcome", OUTCOMES)
        expected_version = U.req_int(body, "expected_care_gap_version")
        notes = U.opt_str(body, "notes")
        reversal_reason = U.opt_str(body, "reversal_reason")
        if outcome == "REVERSED" and not reversal_reason:
            raise ApiError(
                E.ERR_INVALID_REQUEST,
                "reversal_reason is required when outcome is REVERSED",
                400,
            )
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        gap = _get(db.care_gaps, gid, "CareGap")
        # State check (priority 4).
        if gap["status"] not in ("OPEN", "OUTREACH_IN_PROGRESS"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Outreach attempts require the care gap to be OPEN or OUTREACH_IN_PROGRESS",
                409,
            )
        # OCC (priority 5).
        if expected_version != gap["version"]:
            raise ApiError(
                E.ERR_STALE_VERSION,
                "expected_care_gap_version does not match the care gap's current version",
                412,
            )
        reg = D.registry_of_gap(gap)
        now = D.clock_of(reg)
        campaign = db.campaigns.get(campaign_id)
        if campaign is None:
            raise ApiError(
                E.ERR_INVALID_REQUEST, "campaign_id does not reference an outreach campaign", 400
            )
        # Priority 6: cadence timing.
        nea = gap["next_eligible_attempt_at"]
        if nea is not None and now < nea:
            raise ApiError(
                E.ERR_ATTEMPT_TOO_EARLY,
                "current_business_date has not reached next_eligible_attempt_at",
                409,
            )
        # Priority 7: campaign window and quiet hours.
        if (
            now < campaign["starts_at"]
            or now >= campaign["ends_at"]
            or _in_quiet_hours(now, campaign)
        ):
            raise ApiError(
                E.ERR_CAMPAIGN_WINDOW_VIOLATION,
                "The attempt falls outside the campaign window or inside quiet hours",
                409,
            )
        # Priority 8: channel consent.
        member = db.members[gap["member_id"]]
        if channel in ("CALL", "TEXT") and not member["phone_ok"]:
            raise ApiError(
                E.ERR_CHANNEL_CONSENT_MISSING,
                "Member has not consented to phone/text outreach",
                403,
            )
        if channel == "MAIL" and not member["mail_ok"]:
            raise ApiError(
                E.ERR_CHANNEL_CONSENT_MISSING,
                "Member has not consented to postal outreach",
                403,
            )
        # Priority 9: attempt cap.
        if gap["attempt_count"] >= campaign["max_attempts_per_member"]:
            raise ApiError(
                E.ERR_ATTEMPT_CAP_REACHED,
                "The member has reached the campaign's max_attempts_per_member",
                409,
            )
        # Priority 10: exclusion screening.
        if D.member_excluded_for_measure(member["id"], gap["measure_id"], now):
            raise ApiError(
                E.ERR_MEMBER_EXCLUDED,
                "An APPROVED exclusion covers this measure for the member",
                409,
            )
        # Priority 11: campaign liveness.
        if campaign["status"] != "ACTIVE":
            raise ApiError(
                E.ERR_CAMPAIGN_NOT_ACTIVE, "The referenced campaign is not ACTIVE", 409
            )

        attempt = {
            "care_gap_id": gap["id"],
            "campaign_id": campaign_id,
            "member_id": gap["member_id"],
            "channel": channel,
            "attempted_at": now,
            "outcome": outcome,
            "notes": notes,
            "reversal_reason": reversal_reason,
        }
        # Append-only ledger entry: id + created_at only.
        attempt["id"] = db.new_id()
        attempt["_seq"] = db.next_seq()
        attempt["created_at"] = now
        db.attempts[attempt["id"]] = attempt

        if outcome != "REVERSED":
            if gap["status"] == "OPEN":
                gap["status"] = "OUTREACH_IN_PROGRESS"
            gap["attempt_count"] += 1
            gap["next_eligible_attempt_at"] = D.compute_next_eligible_attempt_at(
                gap, campaign, now
            )
            D.recompute_gap_priority(gap)
        D.bump(gap, now)
        return U.success_object(D.ser_attempt(attempt), 201)

    @app.route("/population-health/care-gaps/<gid>/outreach-attempts", methods=["GET"])
    def list_attempts_for_gap(gid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.care_gaps, gid, "CareGap")
        limit, offset = U.pagination_params()
        items = [a for a in db.attempts.values() if a["care_gap_id"] == gid]
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_attempt(a) for a in page], total, limit, offset)

    # ------------------------------------------------------------ appointments
    @app.route("/population-health/care-gaps/<gid>/appointments", methods=["POST"])
    def create_appointment(gid):
        body = U.get_body()
        provider_id = U.req_str(body, "provider_id")
        slot_start_at = U.req_dt(body, "slot_start_at")
        slot_end_at = U.req_dt(body, "slot_end_at")
        capacity = U.opt_int(body, "provider_capacity_per_slot", 1)
        if capacity < 1:
            raise ApiError(
                E.ERR_INVALID_REQUEST, "provider_capacity_per_slot must be >= 1", 400
            )
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        gap = _get(db.care_gaps, gid, "CareGap")
        if gap["status"] not in ("OPEN", "OUTREACH_IN_PROGRESS"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Appointments require the care gap to be OPEN or OUTREACH_IN_PROGRESS",
                409,
            )
        reg = D.registry_of_gap(gap)
        now = D.clock_of(reg)
        member = db.members[gap["member_id"]]
        # Priority 10: exclusion screening.
        if D.member_excluded_for_measure(member["id"], gap["measure_id"], now):
            raise ApiError(
                E.ERR_MEMBER_EXCLUDED,
                "An APPROVED exclusion covers this measure for the member",
                409,
            )
        # Priority 12: no other active appointment for this gap.
        if any(
            a["care_gap_id"] == gid and a["status"] in ("SCHEDULED", "CONFIRMED")
            for a in db.appointments.values()
        ):
            raise ApiError(
                E.ERR_APPOINTMENT_ALREADY_ACTIVE,
                "An appointment in SCHEDULED or CONFIRMED already exists for this care gap",
                409,
            )
        # Priority 13: provider aggregate capacity.
        _check_provider_capacity(provider_id, capacity, slot_start_at, slot_end_at)
        # Priority 14: slot validity.
        _check_slot_valid(slot_start_at, slot_end_at, now)

        appt = {
            "care_gap_id": gid,
            "member_id": gap["member_id"],
            "provider_id": provider_id,
            "slot_start_at": slot_start_at,
            "slot_end_at": slot_end_at,
            "provider_capacity_per_slot": capacity,
            "status": "SCHEDULED",
        }
        D.stamp_new(appt, now)
        db.appointments[appt["id"]] = appt
        gap["status"] = "AWAITING_APPOINTMENT"
        D.bump(gap, now)
        return U.success_object(D.ser_appointment(appt), 201)

    @app.route("/population-health/care-gaps/<gid>/appointments", methods=["GET"])
    def list_appointments_for_gap(gid):
        _, role = U.authenticate()
        U.authorize(role, ALL_ROLES)
        _get(db.care_gaps, gid, "CareGap")
        limit, offset = U.pagination_params()
        items = [a for a in db.appointments.values() if a["care_gap_id"] == gid]
        items = U.apply_filters(items, [("status", "status")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_appointment(a) for a in page], total, limit, offset)

    @app.route("/population-health/appointments/<aid>", methods=["GET"])
    def get_appointment(aid):
        _, role = U.authenticate()
        U.authorize(role, ALL_ROLES)
        a = _get(db.appointments, aid, "Appointment")
        return U.success_object(D.ser_appointment(a), 200)

    def _transport_block_statuses(aid):
        return [
            t
            for t in db.transports.values()
            if t["appointment_id"] == aid and t["status"] in ("REQUESTED", "ARRANGED")
        ]

    @app.route("/population-health/appointments/<aid>/confirm", methods=["POST"])
    def confirm_appointment(aid):
        U.get_body()
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        a = _get(db.appointments, aid, "Appointment")
        if a["status"] != "SCHEDULED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only a SCHEDULED appointment can be confirmed", 409
            )
        if any(t["status"] != "ARRANGED" for t in _transport_block_statuses(aid)):
            raise ApiError(
                E.ERR_TRANSPORT_NOT_ARRANGED,
                "A linked transportation assist must be ARRANGED before confirmation",
                409,
            )
        now = D.clock_of(D.registry_of_appointment(a))
        a["status"] = "CONFIRMED"
        D.bump(a, now)
        return U.success_object(D.ser_appointment(a), 200)

    @app.route("/population-health/appointments/<aid>/complete", methods=["POST"])
    def complete_appointment(aid):
        U.get_body()
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        a = _get(db.appointments, aid, "Appointment")
        if a["status"] != "CONFIRMED":
            raise ApiError(
                E.ERR_APPOINTMENT_NOT_CONFIRMED,
                "Appointment must be CONFIRMED before it can be completed",
                409,
            )
        blocking = _transport_block_statuses(aid)
        if any(t["status"] not in ("ARRANGED", "COMPLETED") for t in blocking):
            raise ApiError(
                E.ERR_TRANSPORT_NOT_ARRANGED,
                "A linked transportation assist must be ARRANGED or COMPLETED before completion",
                409,
            )
        now = D.clock_of(D.registry_of_appointment(a))
        gap = db.care_gaps[a["care_gap_id"]]
        a["status"] = "COMPLETED"
        D.bump(a, now)
        # Auto-create closure evidence derived from the completed appointment.
        evidence = {
            "care_gap_id": gap["id"],
            "member_id": gap["member_id"],
            "evidence_type": "CHART_REVIEW",
            "service_date": a["slot_start_at"],
            "document_uri": None,
            "submitted_by_role": role,
            "status": "SUBMITTED",
            "_submitted_by_user_id": uid,
            "_auto_from_appointment": True,
        }
        D.stamp_new(evidence, now)
        db.evidences[evidence["id"]] = evidence
        gap["status"] = "PENDING_EVIDENCE"
        gap["closure_source"] = "APPOINTMENT_COMPLETED"
        D.bump(gap, now)
        return U.success_object(D.ser_appointment(a), 200)

    @app.route("/population-health/appointments/<aid>/mark-no-show", methods=["POST"])
    def mark_no_show_appointment(aid):
        U.get_body()
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        a = _get(db.appointments, aid, "Appointment")
        if a["status"] not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Only a SCHEDULED or CONFIRMED appointment can be marked no-show",
                409,
            )
        now = D.clock_of(D.registry_of_appointment(a))
        if not (now > a["slot_end_at"]):
            raise ApiError(
                E.ERR_CANNOT_MARK_FUTURE_APPOINTMENT,
                "Cannot mark no-show before the appointment slot has ended",
                409,
            )
        gap = db.care_gaps[a["care_gap_id"]]
        a["status"] = "NO_SHOW"
        D.bump(a, now)
        D.cancel_open_transports(aid, now)
        # Automatic outreach attempt (CALL / NO_ANSWER / auto:no-show); it
        # counts toward the gap's cadence and attempt cap.
        auto = {
            "care_gap_id": gap["id"],
            "campaign_id": None,
            "member_id": gap["member_id"],
            "channel": "CALL",
            "attempted_at": now,
            "outcome": "NO_ANSWER",
            "notes": "auto:no-show",
            "reversal_reason": None,
        }
        auto["id"] = db.new_id()
        auto["_seq"] = db.next_seq()
        auto["created_at"] = now
        db.attempts[auto["id"]] = auto
        gap["status"] = "OUTREACH_IN_PROGRESS"
        gap["attempt_count"] += 1
        # Cadence recompute using the most recent real campaign if known.
        last_campaign = None
        prior = [
            at for at in db.attempts.values()
            if at["care_gap_id"] == gap["id"] and at["campaign_id"] is not None
        ]
        if prior:
            last_campaign = db.campaigns.get(
                max(prior, key=lambda x: x["_seq"])["campaign_id"]
            )
        if last_campaign is None:
            candidates = [
                c for c in db.campaigns.values() if c["panel_id"] == gap["panel_id"]
            ]
            active = [c for c in candidates if c["status"] == "ACTIVE"]
            pool = active or candidates
            if pool:
                last_campaign = max(pool, key=lambda c: c["_seq"])
        if last_campaign is not None:
            gap["next_eligible_attempt_at"] = D.compute_next_eligible_attempt_at(
                gap, last_campaign, now
            )
        D.recompute_gap_priority(gap)
        D.bump(gap, now)
        return U.success_object(D.ser_appointment(a), 200)

    @app.route("/population-health/appointments/<aid>/cancel", methods=["POST"])
    def cancel_appointment(aid):
        U.get_body()  # optional reason
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        a = _get(db.appointments, aid, "Appointment")
        if a["status"] not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Only a SCHEDULED or CONFIRMED appointment can be cancelled",
                409,
            )
        now = D.clock_of(D.registry_of_appointment(a))
        gap = db.care_gaps[a["care_gap_id"]]
        a["status"] = "CANCELLED"
        D.bump(a, now)
        D.cancel_open_transports(aid, now)
        if gap["status"] == "AWAITING_APPOINTMENT":
            gap["status"] = "OUTREACH_IN_PROGRESS"
            D.bump(gap, now)
        return U.success_object(D.ser_appointment(a), 200)

    @app.route("/population-health/appointments/<aid>/reschedule", methods=["POST"])
    def reschedule_appointment(aid):
        body = U.get_body()
        slot_start_at = U.req_dt(body, "slot_start_at")
        slot_end_at = U.req_dt(body, "slot_end_at")
        uid, role = U.authenticate()
        U.authorize(role, [PM])
        a = _get(db.appointments, aid, "Appointment")
        if a["status"] not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Only a SCHEDULED or CONFIRMED appointment can be rescheduled",
                409,
            )
        now = D.clock_of(D.registry_of_appointment(a))
        _check_provider_capacity(
            a["provider_id"], a["provider_capacity_per_slot"], slot_start_at, slot_end_at,
            exclude_id=aid,
        )
        _check_slot_valid(slot_start_at, slot_end_at, now)
        a["slot_start_at"] = slot_start_at
        a["slot_end_at"] = slot_end_at
        if a["status"] == "CONFIRMED":
            a["status"] = "SCHEDULED"  # back-transition: must re-confirm
        D.bump(a, now)
        return U.success_object(D.ser_appointment(a), 200)

    # ---------------------------------------------------- transportation assists
    @app.route("/population-health/appointments/<aid>/transportation-assists", methods=["POST"])
    def create_transport(aid):
        body = U.get_body()
        vendor = U.req_str(body, "vendor")
        pickup_at = U.req_dt(body, "pickup_at")
        cost_cents = U.req_int(body, "cost_cents")
        uid, role = U.authenticate()
        U.authorize(role, [PM, TC])
        a = _get(db.appointments, aid, "Appointment")
        if cost_cents < 0:
            raise ApiError(E.ERR_INVALID_COST, "cost_cents must be non-negative", 400)
        now = D.clock_of(D.registry_of_appointment(a))
        t = {
            "appointment_id": aid,
            "member_id": a["member_id"],
            "vendor": vendor,
            "pickup_at": pickup_at,
            "cost_cents": cost_cents,
            "status": "REQUESTED",
        }
        D.stamp_new(t, now)
        db.transports[t["id"]] = t
        return U.success_object(D.ser_transport(t), 201)

    @app.route("/population-health/transportation-assists/<tid>/arrange", methods=["POST"])
    def arrange_transport(tid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [TC])
        t = _get(db.transports, tid, "TransportationAssist")
        if t["status"] != "REQUESTED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only a REQUESTED assist can be arranged", 409
            )
        now = D.clock_of(D.registry_of_transport(t))
        t["status"] = "ARRANGED"
        D.bump(t, now)
        return U.success_object(D.ser_transport(t), 200)

    @app.route("/population-health/transportation-assists/<tid>/complete", methods=["POST"])
    def complete_transport(tid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [TC])
        t = _get(db.transports, tid, "TransportationAssist")
        if t["status"] != "ARRANGED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only an ARRANGED assist can be completed", 409
            )
        appt = db.appointments.get(t["appointment_id"])
        if appt is None or appt["status"] != "COMPLETED":
            raise ApiError(
                E.ERR_INVALID_STATE,
                "The parent appointment must be COMPLETED before the assist completes",
                409,
            )
        now = D.clock_of(D.registry_of_transport(t))
        t["status"] = "COMPLETED"
        D.bump(t, now)
        return U.success_object(D.ser_transport(t), 200)

    @app.route("/population-health/transportation-assists/<tid>/cancel", methods=["POST"])
    def cancel_transport(tid):
        U.get_body()  # optional reason
        _, role = U.authenticate()
        U.authorize(role, [TC])
        t = _get(db.transports, tid, "TransportationAssist")
        if t["status"] not in ("REQUESTED", "ARRANGED"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Only a REQUESTED or ARRANGED assist can be cancelled",
                409,
            )
        now = D.clock_of(D.registry_of_transport(t))
        t["status"] = "CANCELLED"
        D.bump(t, now)
        return U.success_object(D.ser_transport(t), 200)

    @app.route("/population-health/appointments/<aid>/transportation-assists", methods=["GET"])
    def list_transports_for_appointment(aid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM, TC, QR])
        _get(db.appointments, aid, "Appointment")
        limit, offset = U.pagination_params()
        items = [t for t in db.transports.values() if t["appointment_id"] == aid]
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_transport(t) for t in page], total, limit, offset)

    @app.route("/population-health/transportation-assists/<tid>", methods=["GET"])
    def get_transport(tid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM, TC, QR])
        t = _get(db.transports, tid, "TransportationAssist")
        return U.success_object(D.ser_transport(t), 200)
