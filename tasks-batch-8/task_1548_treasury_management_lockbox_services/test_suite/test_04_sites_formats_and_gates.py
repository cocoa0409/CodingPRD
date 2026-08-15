"""LockboxSite go-live gates and TransmissionFormat supersession lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_transmission_format,
    create_transmission_format_payload,
    get_agreement,
    get_transmission_format,
    setup_active_agreement,
    setup_live_lockbox,
    validate_error,
    validate_success,
)

ACTIVATOR = TEST_USERS["activator_headers"]
IMPLEMENTER = TEST_USERS["implementer_headers"]


def _go_live(api, ws):
    return api.go_live_site(ws["bank"]["id"], ws["customer"]["id"],
                            ws["agreement"]["id"], ws["site"]["id"], ACTIVATOR)


class TestSiteGoLiveGates:
    def test_go_live_blocked_without_active_transmission_format(self, api):
        """PRD §3.3: "Going live moves `PROVISIONING → LIVE` and gates on three
        things: the parent agreement must be `ACTIVE`; the site must have at
        least one `ACTIVE` AvailabilitySchedule
        (`ERR_SITE_LACKS_AVAILABILITY_SCHEDULE`); and the agreement must have
        at least one `ACTIVE` TransmissionFormat
        (`ERR_SITE_LACKS_TRANSMISSION_FORMAT`)."

        Design: Difficulty/cross_entity_state_dependency/site_go_live_requires_active_agreement_and_transmission_format
        """
        # ACTIVE agreement + ACTIVE schedule, but no transmission format at all.
        ws = setup_live_lockbox(with_format=False, with_schedule=True,
                                go_live=False)
        assert ws["site"]["status"] == "PROVISIONING"
        resp = _go_live(api, ws)
        validate_error(resp, ApiErrorId.ERR_SITE_LACKS_TRANSMISSION_FORMAT)

    def test_go_live_blocked_without_active_availability_schedule(self, api):
        """PRD §3.3: "Going live moves `PROVISIONING → LIVE` and gates on three
        things: the parent agreement must be `ACTIVE`; the site must have at
        least one `ACTIVE` AvailabilitySchedule
        (`ERR_SITE_LACKS_AVAILABILITY_SCHEDULE`); and the agreement must have
        at least one `ACTIVE` TransmissionFormat
        (`ERR_SITE_LACKS_TRANSMISSION_FORMAT`)."

        Design: Difficulty/cross_entity_state_dependency/site_go_live_requires_active_agreement_and_transmission_format
        """
        # ACTIVE agreement + ACTIVE format, but no availability schedule.
        ws = setup_live_lockbox(with_format=True, with_schedule=False,
                                go_live=False)
        assert ws["site"]["status"] == "PROVISIONING"
        resp = _go_live(api, ws)
        validate_error(resp, ApiErrorId.ERR_SITE_LACKS_AVAILABILITY_SCHEDULE)


class TestTransmissionFormatSupersedeChain:
    def _setup_two_formats(self, api):
        ws = setup_active_agreement()
        b_id = ws["bank"]["id"]
        c_id = ws["customer"]["id"]
        a_id = ws["agreement"]["id"]
        f1 = create_transmission_format(b_id, c_id, a_id, version_label="v1")
        current = get_agreement(b_id, c_id, a_id)
        f1 = validate_success(
            api.activate_transmission_format(b_id, c_id, a_id, f1["id"],
                                             current["version"], ACTIVATOR))
        f2 = create_transmission_format(
            b_id, c_id, a_id, format_kind="EDI820", version_label="v2",
            supersedes_format_id=f1["id"])
        return ws, f1, f2

    def test_activation_cascades_superseded_format(self, api):
        """PRD §3.3: "Activating a format requires the agreement `ACTIVE` and
        `expected_agreement_version` matching the parent agreement's current
        `version` (`ERR_STALE_VERSION`, HTTP 412), because activation mutates
        the parent — the agreement's `version` increments by one, and the
        format named by `supersedes_format_id`, if any, cascades to
        `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/transmission_format_supersede_chain
        """
        ws, f1, f2 = self._setup_two_formats(api)
        b_id = ws["bank"]["id"]
        c_id = ws["customer"]["id"]
        a_id = ws["agreement"]["id"]
        current = get_agreement(b_id, c_id, a_id)
        f2_active = validate_success(
            api.activate_transmission_format(b_id, c_id, a_id, f2["id"],
                                             current["version"], ACTIVATOR))
        assert f2_active["status"] == "ACTIVE"
        f1_after = get_transmission_format(b_id, c_id, a_id, f1["id"])
        assert f1_after["status"] == "SUPERSEDED", (
            "F1 must cascade to SUPERSEDED when F2 (supersedes_format_id=F1) "
            "is activated"
        )

    def test_retire_from_superseded_is_unconditional(self, api):
        """PRD §3.3: "Retiring runs to `RETIRED`: from `ACTIVE` it is allowed
        only while no batch still holds a `PENDING` transmission for that
        format; from `SUPERSEDED` it is unconditional."

        Design: Difficulty/non_linear_state_machine/transmission_format_supersede_chain
        """
        ws, f1, f2 = self._setup_two_formats(api)
        b_id = ws["bank"]["id"]
        c_id = ws["customer"]["id"]
        a_id = ws["agreement"]["id"]
        current = get_agreement(b_id, c_id, a_id)
        validate_success(
            api.activate_transmission_format(b_id, c_id, a_id, f2["id"],
                                             current["version"], ACTIVATOR))
        f1_after = get_transmission_format(b_id, c_id, a_id, f1["id"])
        assert f1_after["status"] == "SUPERSEDED"
        retired = validate_success(
            api.retire_transmission_format(b_id, c_id, a_id, f1["id"],
                                           ACTIVATOR))
        assert retired["status"] == "RETIRED"


class TestTransmissionFormatValidation:
    def test_invalid_enum_value_rejected(self, api):
        """PRD §2.9: "Independently of this business ordering, a request body
        that is malformed — a missing required field, an unrecognized enum
        value, or an out-of-range numeric — is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "a `format_kind` of `BAI2`, `EDI820`, or `CUSTOM_CSV`".

        Design: Corner/entities/invalid_enum_value_rejected
        """
        ws = setup_active_agreement()
        resp = api.create_transmission_format(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            create_transmission_format_payload(format_kind="X12"),
            IMPLEMENTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_stale_version_on_transmission_format_activate(self, api):
        """PRD §3.3: "Activating a format requires the agreement `ACTIVE` and
        `expected_agreement_version` matching the parent agreement's current
        `version` (`ERR_STALE_VERSION`, HTTP 412)".

        Design: Corner/errors/err_stale_version_on_transmission_format_activate
        """
        ws = setup_active_agreement()
        b_id = ws["bank"]["id"]
        c_id = ws["customer"]["id"]
        a_id = ws["agreement"]["id"]
        observed = get_agreement(b_id, c_id, a_id)["version"]
        f1 = create_transmission_format(b_id, c_id, a_id, version_label="v1")
        validate_success(
            api.activate_transmission_format(b_id, c_id, a_id, f1["id"],
                                             observed, ACTIVATOR))
        # F1's activation bumped the parent agreement's version, so the
        # observed token is now stale for the next format activation.
        f2 = create_transmission_format(b_id, c_id, a_id, format_kind="EDI820",
                                        version_label="v2")
        resp = api.activate_transmission_format(b_id, c_id, a_id, f2["id"],
                                                observed, ACTIVATOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
