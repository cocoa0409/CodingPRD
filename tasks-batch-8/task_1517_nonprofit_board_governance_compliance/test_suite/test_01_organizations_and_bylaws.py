"""Organizations, founding bylaws, amendments, logical clock, profile OCC."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestNonprofitCreation:
    def test_nonprofit_create_defaults_and_initial_posture(self, api):
        """PRD §3.1: "The `compliance_posture` — one of `COMPLIANT`, `AT_RISK`, or
        `NON_COMPLIANT` — is derived from registrations, filings, coverage, and
        disclosure delinquency per §3.9, and a freshly incorporated organization
        starts at `NON_COMPLIANT` because no directors-and-officers coverage exists
        yet."
        PRD §3.1: "The `current_fiscal_year` is the calendar year of the fiscal-year
        end that contains the logical clock date, where a fiscal year runs from the
        first day of the month following the end month through the last day of the
        end month of the label year — so a December year-end yields fiscal years
        aligned to calendar years, while a June year-end labels the year by the
        calendar year in which it closes."

        Design: Corner/entities/nonprofit_create_defaults_and_initial_posture
        """
        data = th.validate_success(api.create_nonprofit(
            th.create_nonprofit_payload(
                name="Fresh Org", ein="EIN-C1", state_of_incorporation="CA",
                fiscal_year_end_month=12, annual_gross_receipts_cents=4_000_000_000),
            ADMIN), 201)
        th.assert_nonprofit(data)
        assert data["compliance_posture"] == "NON_COMPLIANT", (
            f"fresh org must start NON_COMPLIANT (no D&O coverage), got {data['compliance_posture']}")
        assert data["current_fiscal_year"] == 2026, (
            f"December FYE at the default clock 2026-08-01 must label FY2026, got {data['current_fiscal_year']}")
        assert isinstance(data["version"], int) and data["version"] >= 1

        fetched = th.validate_success(api.get_nonprofit(data["id"], ADMIN))
        assert fetched["ein"] == "EIN-C1"
        assert fetched["compliance_posture"] == "NON_COMPLIANT"
        assert fetched["current_fiscal_year"] == 2026

    def test_nonprofit_duplicate_ein_rejected(self, api):
        """PRD §3.1: "A `GovernanceAdmin` incorporates an organization by providing
        its legal `name`, its `ein` (the Employer Identification Number, which must
        be globally unique across all nonprofits — a collision is rejected with
        `ERR_DUPLICATE_EIN`), the two-letter `state_of_incorporation`, the
        `fiscal_year_end_month` as an integer from 1 to 12, and the most recently
        reported `annual_gross_receipts_cents`."

        Design: Corner/entities/nonprofit_duplicate_ein_rejected
        """
        th.validate_success(api.create_nonprofit(
            th.create_nonprofit_payload(name="First", ein="EIN-DUP-1"), ADMIN), 201)
        resp = api.create_nonprofit(
            th.create_nonprofit_payload(
                name="Second", ein="EIN-DUP-1", state_of_incorporation="NY",
                fiscal_year_end_month=6, annual_gross_receipts_cents=2_000_000),
            ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE_EIN)

    def test_nonprofit_get_not_found_returns_404(self, api):
        """PRD §2.7: "5. **Path existence.** Path resource identifiers are validated
        left to right; the first identifier that does not resolve rejects the request
        with `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/nonprofit_get_not_found_returns_404
        """
        resp = api.get_nonprofit(th.NON_EXISTENT_UUID, ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_NOT_FOUND, 404)


class TestLogicalClockAndFiscalYear:
    def test_clock_default_and_fiscal_year_determinism(self, api):
        """PRD §2.4: "At startup, before any client call, the logical clock is
        exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."
        PRD §3.1: "The `current_fiscal_year` is the calendar year of the fiscal-year
        end that contains the logical clock date, where a fiscal year runs from the
        first day of the month following the end month through the last day of the
        end month of the label year — so a December year-end yields fiscal years
        aligned to calendar years, while a June year-end labels the year by the
        calendar year in which it closes."

        Design: Corner/cross_cutting_layers/clock_default_and_fiscal_year_determinism
        """
        dec = fx.create_nonprofit(name="Dec", ein="EIN-CK-1", fye_month=12)
        jun = fx.create_nonprofit(name="Jun", ein="EIN-CK-2", fye_month=6)
        assert dec["current_fiscal_year"] == 2026, (
            f"December FYE at the 2026-08-01 default clock must be FY2026, got {dec['current_fiscal_year']}")
        assert jun["current_fiscal_year"] == 2027, (
            f"June FYE at the 2026-08-01 default clock must be FY2027, got {jun['current_fiscal_year']}")

        fx.set_clock("2025-12-01T00:00:00Z")
        dec2 = th.validate_success(api.get_nonprofit(dec["id"], ADMIN))
        jun2 = th.validate_success(api.get_nonprofit(jun["id"], ADMIN))
        assert dec2["current_fiscal_year"] == 2025
        assert jun2["current_fiscal_year"] == 2026


class TestFoundingBylaws:
    def test_bylaws_double_adoption_and_second_founding_rejected(self, api):
        """PRD §3.1: "Founding adoption — the incorporator's act, performed by a
        `GovernanceAdmin` — moves a `DRAFT` document to `ADOPTED` and stamps
        `adopted_at` from the logical clock; it is refused with
        `ERR_BYLAWS_ALREADY_ADOPTED` when another bylaws document is already
        `ADOPTED` for the same nonprofit, and attempting it on a non-draft document
        is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/bylaws_double_adoption_and_second_founding_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-BL-1")
        b1 = th.validate_success(api.create_bylaws(
            th.create_bylaws_payload(org["id"]), ADMIN), 201)
        b2 = th.validate_success(api.create_bylaws(
            th.create_bylaws_payload(org["id"], quorum_pct=60,
                                     quorum_basis="AUTHORIZED",
                                     amendment_threshold_pct=75,
                                     term_length_years=3,
                                     max_consecutive_terms=2,
                                     term_cooloff_years=2, board_size=7),
            ADMIN), 201)

        adopted = th.validate_success(api.adopt_bylaws(b1["id"], ADMIN))
        assert adopted["status"] == "ADOPTED"

        th.validate_error(api.adopt_bylaws(b1["id"], ADMIN),
                          th.ApiErrorId.ERR_INVALID_STATE)
        th.validate_error(api.adopt_bylaws(b2["id"], ADMIN),
                          th.ApiErrorId.ERR_BYLAWS_ALREADY_ADOPTED)
        b2_after = th.validate_success(api.get_bylaws(b2["id"], ADMIN))
        assert b2_after["status"] == "DRAFT"

    def test_election_and_amendment_require_adopted_bylaws(self, api):
        """PRD §3.2: "Election requires an `ADOPTED` bylaws to exist, else
        `ERR_BYLAWS_NOT_ADOPTED`, and the term is version-pinned to that document
        via its `bylaws_id`: its `end_date` is computed as the `start_date` plus the
        pinned bylaws' `term_length_years` on the same calendar day, and later
        amendments never mutate an existing term's end date."
        PRD §3.1: "An empty subset is rejected with `ERR_INVALID_REQUEST`, and a
        base that is not `ADOPTED` is rejected with `ERR_BYLAWS_NOT_ADOPTED`."

        Design: Corner/validations/election_and_amendment_require_adopted_bylaws
        """
        org = fx.create_nonprofit(name="O", ein="EIN-BN-1")
        bylaws = th.validate_success(api.create_bylaws(
            th.create_bylaws_payload(org["id"]), ADMIN), 201)  # stays DRAFT
        member = fx.create_board_member(org["id"], "M", "m@x.org",
                                        skills=["FINANCE"])

        resp_term = api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2026-01-01T00:00:00Z"),
            ADMIN)
        th.validate_error(resp_term, th.ApiErrorId.ERR_BYLAWS_NOT_ADOPTED)

        resp_am = api.create_amendment(
            th.create_amendment_payload(org["id"], bylaws["id"],
                                        title="Premature",
                                        proposed_fields={"quorum_pct": 60}),
            ADMIN)
        th.validate_error(resp_am, th.ApiErrorId.ERR_BYLAWS_NOT_ADOPTED)


class TestAmendmentMotionLink:
    def test_amendment_withdraw_blocked_while_motion_open(self, api):
        """PRD §3.1: "Withdrawal behaves differently by state: a `DRAFT` amendment
        may be withdrawn freely, while withdrawing a `PROPOSED` amendment is refused
        with `ERR_AMENDMENT_HAS_OPEN_MOTION` if any non-terminal motion — one still
        `INTRODUCED`, `VOTING_OPEN`, or `TABLED` — references it."
        PRD §3.5: "Withdrawal is available from `INTRODUCED` or `TABLED` and moves
        the motion to `WITHDRAWN`; withdrawing a bylaws motion also frees the
        amendment's motion link."

        Design: Corner/state_machines/amendment_withdraw_blocked_while_motion_open
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",), ein="EIN-AW-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        amendment = fx.create_proposed_amendment(
            np_id, sc["bylaws"]["id"], chair, title="Quorum tweak",
            proposed_fields={"quorum_pct": 55})
        meeting = fx.create_meeting(np_id, start="2026-08-02T10:00:00Z")
        motion = fx.introduce_motion(np_id, meeting["id"], chair, title="Adopt",
                                     category="BYLAWS",
                                     bylaws_amendment_id=amendment["id"])

        th.validate_error(api.withdraw_amendment(amendment["id"], chair_headers),
                          th.ApiErrorId.ERR_AMENDMENT_HAS_OPEN_MOTION)

        withdrawn_motion = th.validate_success(
            api.withdraw_motion(motion["id"], chair_headers))
        assert withdrawn_motion["status"] == "WITHDRAWN"

        withdrawn = th.validate_success(
            api.withdraw_amendment(amendment["id"], chair_headers))
        assert withdrawn["status"] == "WITHDRAWN"

    def test_amendment_motion_link_exclusivity_and_proposed_gate(self, api):
        """PRD §3.5: "A `BYLAWS` motion must carry the `bylaws_amendment_id` of a
        `PROPOSED` amendment (`ERR_AMENDMENT_NOT_PROPOSED`), no other non-terminal
        motion may already reference that amendment
        (`ERR_AMENDMENT_HAS_OPEN_MOTION`), the amendment's `motion_id` is set to the
        new motion, and the `threshold` and `threshold_basis` inputs are ignored
        because the amendment-adoption threshold governs passage."

        Design: Corner/state_machines/amendment_motion_link_exclusivity_and_proposed_gate
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",), ein="EIN-AM-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])

        am_a = th.validate_success(api.create_amendment(
            th.create_amendment_payload(np_id, sc["bylaws"]["id"], title="A",
                                        proposed_fields={"quorum_pct": 55}),
            chair_headers), 201)  # stays DRAFT
        am_b = fx.create_proposed_amendment(np_id, sc["bylaws"]["id"], chair,
                                            title="B", proposed_fields={"board_size": 7})
        mt1 = fx.create_meeting(np_id, start="2026-08-02T10:00:00Z")
        mt2 = fx.create_meeting(np_id, start="2026-08-03T10:00:00Z")
        fx.introduce_motion(np_id, mt1["id"], chair, title="Adopt B",
                            category="BYLAWS", bylaws_amendment_id=am_b["id"])

        resp_draft = api.create_motion(
            th.create_motion_payload(np_id, mt1["id"], title="Adopt A",
                                     category="BYLAWS",
                                     bylaws_amendment_id=am_a["id"]),
            chair_headers)
        th.validate_error(resp_draft, th.ApiErrorId.ERR_AMENDMENT_NOT_PROPOSED)

        resp_open = api.create_motion(
            th.create_motion_payload(np_id, mt2["id"], title="Adopt B twice",
                                     category="BYLAWS",
                                     bylaws_amendment_id=am_b["id"]),
            chair_headers)
        th.validate_error(resp_open, th.ApiErrorId.ERR_AMENDMENT_HAS_OPEN_MOTION)


class TestNonprofitProfileOcc:
    def test_nonprofit_patch_occ_stale_version_rejected(self, api):
        """PRD §2.6: "`PATCH /boardgov/nonprofits/{id}` requires
        `expected_nonprofit_version`, carrying the client's last observed `version`
        of the nonprofit. Because profile fields such as
        `annual_gross_receipts_cents` feed registration fee estimates and the
        insurance coverage floor, a stale write is rejected with `ERR_STALE_VERSION`
        (HTTP 412) rather than allowed to overwrite profile changes it could not
        have seen."
        PRD §3.1: "Profile maintenance is a guarded write per §2.6: the request must
        carry `expected_nonprofit_version`, may update `name`,
        `state_of_incorporation`, `fiscal_year_end_month`, or
        `annual_gross_receipts_cents`, increments the nonprofit's `version` by 1,
        and recomputes the posture whenever the receipts figure changes, since both
        the fee estimate and the coverage floor read the new value."

        Design: Corner/cross_cutting_layers/nonprofit_patch_occ_stale_version_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-OC-1", receipts=1_000_000)
        v1 = org["version"]

        patched = th.validate_success(api.patch_nonprofit(
            org["id"], {"expected_nonprofit_version": v1,
                        "annual_gross_receipts_cents": 2_000_000}, ADMIN))
        assert patched["annual_gross_receipts_cents"] == 2_000_000
        assert patched["version"] == v1 + 1, (
            f"profile write must increment version by 1: {v1} -> {patched['version']}")
        v2 = patched["version"]

        th.validate_error(api.patch_nonprofit(
            org["id"], {"expected_nonprofit_version": v1,
                        "annual_gross_receipts_cents": 3_000_000}, ADMIN),
            th.ApiErrorId.ERR_STALE_VERSION, 412)

        patched2 = th.validate_success(api.patch_nonprofit(
            org["id"], {"expected_nonprofit_version": v2,
                        "state_of_incorporation": "DE"}, ADMIN))
        assert patched2["version"] == v2 + 1
        assert patched2["state_of_incorporation"] == "DE"
