"""Match scoring: dual screening/forensic variants, conditional evidence weights,
the 7000bp notify threshold, and scan input-set scoping (PRD §3.5)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    register_owner,
    register_bicycle,
    owner_headers,
    file_theft_report,
    flag_report,
    create_active_partner_org,
    partner_headers,
    create_intake,
    scan_intake,
    get_single_match_for_intake,
    get_notifications_for_owner,
    setup_notified_match,
    assert_match_candidate,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestDualVariantScoring:
    def test_match_score_screening_vs_forensic_divergence_missing_photo(self, api):
        """PRD §3.5: "Identical inputs can diverge — when the photo is missing and
        serial, manufacturer, and temporal evidence are all full while color
        mismatches, the screening score is 8500 while the forensic score is 6000."
        PRD §3.5: "Only the screening score ever drives status and notification;
        the forensic score is advisory, computed and stored alongside for registrar
        review."

        Design: Difficulty/dual_variant_calc/match_score_screening_vs_forensic_divergence
        """
        # PRD scenario: photo missing on BOTH sides (photo_pts = 0), full serial /
        # manufacturer / temporal evidence, color mismatch. The intake omits
        # photo_hash entirely; the bicycle likewise has none.
        scenario = setup_notified_match(
            serial="ABC123",
            manufacturer="Trek",
            model="FX3",
            color="Black",
            declared_value_cents=150000,
            occurred_at="2026-05-10T00:00:00Z",
            appraised_value_cents=80000,
            found_at="2026-05-15T00:00:00Z",
            intake_overrides={"primary_color": "Blue"},  # color mismatch; no intake photo
        )
        match = scenario["match"]
        assert_match_candidate(match)
        assert match["screening_score"] == 8500, (
            f"screening must be 8500, got {match['screening_score']}"
        )
        assert match["forensic_score"] == 6000, (
            f"forensic must be 6000, got {match['forensic_score']}"
        )
        assert match["status"] == "NOTIFIED", (
            "status NOTIFIED is driven by the screening variant alone (8500 >= 7000) "
            "even though the forensic score 6000 sits below the threshold"
        )

    def test_match_score_screening_vs_forensic_divergence_full_evidence(self, api):
        """PRD §3.5: "The **screening** variant weights serial evidence heaviest:
        0.50 on serial points, 0.20 on manufacturer, 0.15 on color, and 0.15 on
        temporal, ignoring photo evidence entirely. The **forensic** variant
        rebalances toward physical evidence: 0.35 on serial, 0.30 on photo, 0.15 on
        manufacturer, 0.10 on color, and 0.10 on temporal."
        PRD §3.5: "Photo points are zero whenever either side lacks a
        `photo_hash`."

        Full serial/mfr/color/temporal evidence with no photo on either side:
        screening 10000 vs forensic 7000 — the variants diverge again.

        Design: Difficulty/dual_variant_calc/match_score_screening_vs_forensic_divergence
        """
        scenario = setup_notified_match(
            serial="ABC999",
            manufacturer="Giant",
            model="Defy",
            color="Red",
            occurred_at="2026-05-10T00:00:00Z",
            appraised_value_cents=40000,
            found_at="2026-05-12T00:00:00Z",
        )
        match = scenario["match"]
        assert match["screening_score"] == 10000, (
            f"screening must be 10000, got {match['screening_score']}"
        )
        assert match["forensic_score"] == 7000, (
            f"forensic must be 7000 with photo_pts 0, got {match['forensic_score']}"
        )
        assert match["status"] == "NOTIFIED"


class TestConditionalWeights:
    def test_match_score_multi_input_conditional_weights(self, api):
        """PRD §3.5: "Serial points compare the intake's normalized serial to the
        bicycle's normalized serial: full credit on equality, otherwise one minus
        the Levenshtein distance divided by the longer serial's length, never below
        zero."
        PRD §3.5: "The **screening** variant weights serial evidence heaviest:
        0.50 on serial points, 0.20 on manufacturer, 0.15 on color, and 0.15 on
        temporal ... The **forensic** variant rebalances toward physical evidence:
        0.35 on serial, 0.30 on photo, 0.15 on manufacturer, 0.10 on color, and
        0.10 on temporal."

        Partial serial ABC12 vs ABC123 (serial_pts 5/6), identical photo hashes
        (photo_pts 1.0), full mfr/color/temporal credit: screening 9167, forensic
        9417.

        Design: Difficulty/combinatorial_formula/match_score_multi_input_conditional_weights
        """
        scenario = setup_notified_match(
            serial="ABC123",
            manufacturer="Trek",
            model="FX3",
            color="Black",
            declared_value_cents=150000,
            photo_hash="1111222233334444",
            occurred_at="2026-05-10T00:00:00Z",
            appraised_value_cents=50000,
            found_at="2026-05-20T00:00:00Z",
            intake_overrides={"serial_number_raw": "ABC12"},
        )
        match = scenario["match"]
        assert match["screening_score"] == 9167, (
            f"expected screening 9167, got {match['screening_score']}"
        )
        assert match["forensic_score"] == 9417, (
            f"expected forensic 9417, got {match['forensic_score']}"
        )
        assert match["status"] == "NOTIFIED"

    def test_match_score_null_intake_fields_half_credit(self, api):
        """PRD §3.5: "Manufacturer points grant half credit when the intake's
        `manufacturer` was not observed (null), and otherwise full credit on a
        case-insensitive match with the bicycle's manufacturer or zero on a
        mismatch; color points follow the identical pattern over `primary_color`."

        Exact serial, unobserved manufacturer (0.5), color mismatch (0), matching
        photo hashes (photo_pts 1.0), temporal full credit: screening
        10000*(0.5 + 0.1 + 0 + 0.15) == 7500, forensic
        10000*(0.35 + 0.30 + 0.075 + 0 + 0.10) == 8250.

        Design: Difficulty/combinatorial_formula/match_score_multi_input_conditional_weights
        """
        set_clock("2026-05-01T00:00:00Z")
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(
            owner, serial_number="ABC123", manufacturer="Trek", model="FX3",
            primary_color="Black", declared_value_cents=150000,
            photo_hash="1111222233334444",
        )
        report = file_theft_report(owner, bicycle, occurred_at="2026-05-10T00:00:00Z")
        flag_report(report["id"])
        org = create_active_partner_org()
        intake = create_intake(
            org,
            serial_number_raw="ABC123",
            primary_color="Blue",   # observed, mismatched -> 0 color points
            found_at="2026-05-12T00:00:00Z",
            appraised_value_cents=50000,
            photo_hash="1111222233334444",  # manufacturer deliberately omitted (null)
        )
        scan_intake(intake["id"], partner_headers(org))
        match = get_single_match_for_intake(intake["id"])
        assert match["screening_score"] == 7500, (
            f"expected screening 7500, got {match['screening_score']}"
        )
        assert match["forensic_score"] == 8250, (
            f"expected forensic 8250, got {match['forensic_score']}"
        )
        assert match["status"] == "NOTIFIED"


class TestNotifyThreshold:
    def _threshold_setup(self, api):
        """One FLAGGED report + two intakes straddling the 7000bp boundary."""
        set_clock("2026-05-01T00:00:00Z")
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(
            owner, serial_number="THR500", manufacturer="Specialized",
            model="Sirrus", primary_color="Blue", declared_value_cents=90000,
        )
        report = file_theft_report(owner, bicycle, occurred_at="2026-05-10T00:00:00Z")
        flag_report(report["id"])
        org = create_active_partner_org()
        # iX: serial/mfr full, color mismatch, temporal zero (365-day gap) -> 7000.
        intake_x = create_intake(
            org,
            serial_number_raw="THR500",
            primary_color="Green",
            found_at="2027-05-10T00:00:00Z",
            appraised_value_cents=50000,
            manufacturer="Specialized",
        )
        # iY: same but manufacturer unobserved (half credit) -> 6000.
        intake_y = create_intake(
            org,
            serial_number_raw="THR500",
            primary_color="Green",
            found_at="2027-05-10T00:00:00Z",
            appraised_value_cents=50000,
        )
        return owner, org, intake_x, intake_y

    def test_match_notify_threshold_exact_7000(self, api):
        """PRD §3.5: "A candidate's initial status is chosen at scan time:
        `NOTIFIED` when the screening score reaches at least 7000 basis points,
        otherwise `PROPOSED`."
        PRD §3.5: "Temporal points are full credit when the gap is no more than
        thirty days; beyond that the credit is one minus the excess days beyond
        thirty divided by three hundred thirty-five, never below zero, so it
        reaches exactly zero at a gap of three hundred sixty-five days."

        iX scores exactly 7000 (0.5 serial + 0.2 mfr + 0 color + 0 temporal) and is
        NOTIFIED; iY scores 6000 and stays PROPOSED.

        Design: Difficulty/boundary_precision_check/match_notify_threshold_exact_7000
        """
        _owner, org, intake_x, intake_y = self._threshold_setup(api)
        scan_intake(intake_x["id"], partner_headers(org))
        scan_intake(intake_y["id"], partner_headers(org))
        match_x = get_single_match_for_intake(intake_x["id"])
        match_y = get_single_match_for_intake(intake_y["id"])
        assert match_x["screening_score"] == 7000, (
            f"expected exactly 7000, got {match_x['screening_score']}"
        )
        assert match_x["status"] == "NOTIFIED", (
            "the notify threshold is >= inclusive: exactly 7000 must notify"
        )
        assert match_y["screening_score"] == 6000, (
            f"expected 6000, got {match_y['screening_score']}"
        )
        assert match_y["status"] == "PROPOSED"

    def test_match_notify_threshold_notification_side_effect(self, api):
        """PRD §3.5: "Entering `NOTIFIED` — whether at first scan or later, when a
        re-scan recomputes a `PROPOSED` candidate's screening score at 7000 or
        above — creates a `MATCH_FOUND` notification for the theft report's owner."

        Design: Difficulty/boundary_precision_check/match_notify_threshold_exact_7000
        """
        owner, org, intake_x, intake_y = self._threshold_setup(api)
        scan_intake(intake_x["id"], partner_headers(org))
        scan_intake(intake_y["id"], partner_headers(org))
        notifications = get_notifications_for_owner(owner["id"])
        match_found = [n for n in notifications if n["kind"] == "MATCH_FOUND"]
        assert len(match_found) == 1, (
            f"exactly one MATCH_FOUND (from the 7000-score match) must exist, "
            f"got {len(match_found)}"
        )
        assert match_found[0]["owner_id"] == owner["id"]


class TestScanInputSet:
    def test_match_scan_input_set_excludes_non_flagged(self, api):
        """PRD §3.5: "A `Partner` or `Registrar` triggers a scan of an intake, and
        the scan computes a match score against every theft report currently in
        `FLAGGED` status — reports in any other status are excluded from the
        candidate set entirely."
        PRD §3.5: "the response reports the `created_match_ids` alongside the
        `scanned_report_count`."

        Design: Corner/calculations/match_scan_input_set_excludes_non_flagged
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(
            owner, serial_number="FLT100", manufacturer="Trek", declared_value_cents=60000
        )
        file_theft_report(owner, bicycle)  # left UNDER_REVIEW, never flagged
        org = create_active_partner_org()
        intake = create_intake(
            org,
            serial_number_raw="FLT100",
            primary_color="Black",
            found_at="2026-05-04T00:00:00Z",
            appraised_value_cents=40000,
            manufacturer="Trek",
        )
        result = scan_intake(intake["id"], partner_headers(org))
        assert result["scanned_report_count"] == 0, (
            f"UNDER_REVIEW reports must be excluded, scanned {result['scanned_report_count']}"
        )
        assert result["created_match_ids"] == [], (
            f"no matches may be created, got {result['created_match_ids']}"
        )
        _data, meta = validate_paginated(
            api.list_matches(REGISTRAR, params={"recovery_intake_id": intake["id"]})
        )
        assert meta["total_count"] == 0

    def test_partner_other_org_scan_forbidden(self, api):
        """PRD §2.1: "a partner's access to recovery intakes is restricted to rows
        whose `partner_org_id` equals `X-User-ID`, with the same
        `ERR_FORBIDDEN_RESOURCE_ACCESS` rejection on mismatch."
        PRD §4: POST /registry/recovery-intakes/{id}/scan is authorized for Partner
        and Registrar.

        Design: Corner/rbac/partner_other_org_scan_forbidden
        """
        org_a = create_active_partner_org(
            name="PD A", jurisdiction_code="A", contact_email="a@x.gov"
        )
        org_b = create_active_partner_org(
            name="PD B", jurisdiction_code="B", contact_email="b@x.gov"
        )
        intake = create_intake(org_a, serial_number_raw="RBC600", appraised_value_cents=50000)
        resp = api.scan_recovery_intake(intake["id"], partner_headers(org_b))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS, expected_status=403)
        # The same scan is a shared operation for the Registrar and succeeds.
        result = scan_intake(intake["id"], REGISTRAR)
        assert result["scanned_report_count"] == 0
