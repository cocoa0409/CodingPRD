"""Transmittal lifecycle: sealing, the e-file threshold evaluation order,
segregation of duties, the unresolved-SECOND-B-notice safety gate, rejection
and reopen, and the accepted-return cardinality invariant under correction."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    SPEC,
    ApiErrorId,
    assert_transmittal,
    create_accepted_return,
    create_b_notice,
    create_matched_vendor,
    create_payment,
    create_tax_year,
    create_validated_return,
    generate_returns,
    get_single_return,
    list_returns,
    make_ap_clerk_headers,
    make_tax_specialist_headers,
    make_tax_transmitter_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _seal(api, transmittal_id, sealer="spec-1"):
    return api.seal_transmittal(transmittal_id, make_tax_specialist_headers(sealer))


def _submit(api, transmittal_id, channel, submitter="xmtr-1"):
    return api.submit_transmittal(
        transmittal_id, {"channel": channel}, make_tax_transmitter_headers(submitter)
    )


class TestSealRules:
    def test_seal_empty_transmittal_returns_409(self, api):
        """PRD §3.7: "Sealing the batch, again a `TaxSpecialist` action, requires the
        transmittal to be `OPEN` (`ERR_INVALID_STATE_TRANSITION`) and at least one
        eligible return (`ERR_TRANSMITTAL_EMPTY`)."

        Design: Corner/validations/c_seal_empty_transmittal_returns_409
        """
        create_tax_year()
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        assert_transmittal(transmittal)
        assert transmittal["status"] == "OPEN"

        resp = _seal(api, transmittal["id"])
        validate_error(resp, ApiErrorId.ERR_TRANSMITTAL_EMPTY, 409)

        after = validate_success(api.get_transmittal(transmittal["id"], SPEC), 200)
        assert after["status"] == "OPEN"

    def test_apclerk_cannot_submit_transmittal(self, api):
        """PRD §2.7: "Every request walks an ordered ladder of checks, and a failure
        at any rung short-circuits the ladder — the caller always receives the
        earliest applicable rejection, never a later one that an earlier failure
        would have masked."
        PRD §2.7: "2. **Authorization.** The caller's role must be listed for the
        endpoint, and a `VendorPortal` caller's `X-User-ID` must equal the path
        vendor's id (`ERR_FORBIDDEN_FOR_ROLE`)."

        Design: Corner/roles/c_apclerk_cannot_submit_transmittal
        """
        create_tax_year()
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        # The transmittal is OPEN (not SEALED), but the role check (rung 2) fires
        # long before the state check (rung 4) would.
        resp = api.submit_transmittal(
            transmittal["id"], {"channel": "PAPER"}, make_ap_clerk_headers("clerk-1")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestEfileThreshold:
    def test_efile_channel_evaluation_order_submit_reevaluates(self, api):
        """PRD §3.7: "a declared `PAPER` channel is accepted only when the qualifying
        count recomputed at submit time — the same three-step evaluation as at seal —
        is below the year's `efiling_threshold_count`, failing with
        `ERR_EFILE_REQUIRED` otherwise."

        Design: Difficulty/combinatorial_formula/efile_channel_evaluation_order
        """
        create_tax_year(efiling_threshold_count=2)
        vendor_a, _ = create_matched_vendor(legal_name="A Co", tin="555555555")
        create_payment(vendor_a["id"], amount_cents=100000, payment_date="2025-04-01T00:00:00Z",
                       payment_type="SERVICE")
        vendor_b, _ = create_matched_vendor(
            legal_name="B Co", tin="666666666", tin_type="EIN",
            entity_classification="PARTNERSHIP",
        )
        create_payment(vendor_b["id"], amount_cents=70000, payment_date="2025-04-02T00:00:00Z",
                       payment_type="RENT")
        generate_returns(2025)
        return_a = get_single_return(vendor_a["id"], form_type="NEC")
        return_b = get_single_return(vendor_b["id"], form_type="MISC")

        validate_success(api.validate_return(return_a["id"], SPEC), 200)
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        sealed = validate_success(_seal(api, transmittal["id"]), 200)
        # At seal, only this batch's member qualifies: count 1 < threshold 2.
        assert sealed["filing_channel"] == "PAPER"

        # A second return validated after the seal lifts the qualifying count to 2.
        validate_success(api.validate_return(return_b["id"], SPEC), 200)

        # The submit re-evaluates: count 2 >= 2, so declared PAPER is rejected...
        rejected = _submit(api, transmittal["id"], "PAPER")
        validate_error(rejected, ApiErrorId.ERR_EFILE_REQUIRED, 409)
        # ...while the matching EFILE declaration succeeds.
        submitted = validate_success(_submit(api, transmittal["id"], "EFILE"), 200)
        assert submitted["status"] == "SUBMITTED"

    def test_efile_channel_counts_own_members_at_seal(self, api):
        """PRD §3.7: "Only after the member transition does the system compute
        `filing_channel`: the qualifying count is the number of returns for the tax
        year whose `federal_status` is `VALIDATED`, `TRANSMITTED`, or `ACCEPTED`, and
        the recommended channel is `EFILE` when that count is at least the year's
        `efiling_threshold_count`, otherwise `PAPER`. Because the members are already
        `TRANSMITTED` when the count is taken, the count includes this transmittal's
        own returns — an intentional, pinned evaluation order."

        Design: Difficulty/combinatorial_formula/efile_channel_evaluation_order
        """
        create_tax_year(efiling_threshold_count=1)
        _vendor, _payment, tax_return = create_validated_return(
            legal_name="Solo V", tin="121212121"
        )
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        sealed = validate_success(_seal(api, transmittal["id"]), 200)
        # The transmittal's own single member already meets threshold 1.
        assert sealed["return_count"] == 1
        assert sealed["filing_channel"] == "EFILE"

    def test_efile_threshold_below_boundary_seals_and_submits_paper(self, api):
        """PRD §3.7: "the recommended channel is `EFILE` when that count is at least
        the year's `efiling_threshold_count`, otherwise `PAPER`."
        PRD §3.7: "a declared `PAPER` channel is accepted only when the qualifying
        count recomputed at submit time — the same three-step evaluation as at seal —
        is below the year's `efiling_threshold_count`, failing with
        `ERR_EFILE_REQUIRED` otherwise."

        Design: Difficulty/boundary_precision_check/efile_threshold_exactly_at_count
        """
        create_tax_year(efiling_threshold_count=2)
        vendor_a, _ = create_matched_vendor(legal_name="EA", tin="565656565")
        create_payment(vendor_a["id"], amount_cents=70000, payment_date="2025-04-01T00:00:00Z")
        vendor_b, _ = create_matched_vendor(
            legal_name="EB", tin="676767676", tin_type="EIN",
            entity_classification="PARTNERSHIP",
        )
        create_payment(vendor_b["id"], amount_cents=70000, payment_date="2025-04-02T00:00:00Z")
        generate_returns(2025)
        return_a = get_single_return(vendor_a["id"])
        return_b = get_single_return(vendor_b["id"])

        # Only A validated before the first seal: qualifying count 1 < 2.
        validate_success(api.validate_return(return_a["id"], SPEC), 200)
        t1 = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        sealed1 = validate_success(_seal(api, t1["id"]), 200)
        assert sealed1["filing_channel"] == "PAPER"
        submitted1 = validate_success(_submit(api, t1["id"], "PAPER"), 200)
        assert submitted1["status"] == "SUBMITTED"

    def test_efile_threshold_exactly_at_count(self, api):
        """PRD §3.7: "the recommended channel is `EFILE` when that count is at least
        the year's `efiling_threshold_count`, otherwise `PAPER`."
        PRD §3.7: "a declared `PAPER` channel is accepted only when the qualifying
        count recomputed at submit time — the same three-step evaluation as at seal —
        is below the year's `efiling_threshold_count`, failing with
        `ERR_EFILE_REQUIRED` otherwise."

        Design: Difficulty/boundary_precision_check/efile_threshold_exactly_at_count
        """
        create_tax_year(efiling_threshold_count=2)
        vendor_a, _ = create_matched_vendor(legal_name="EA", tin="565656565")
        create_payment(vendor_a["id"], amount_cents=70000, payment_date="2025-04-01T00:00:00Z")
        vendor_b, _ = create_matched_vendor(
            legal_name="EB", tin="676767676", tin_type="EIN",
            entity_classification="PARTNERSHIP",
        )
        create_payment(vendor_b["id"], amount_cents=70000, payment_date="2025-04-02T00:00:00Z")
        generate_returns(2025)
        return_a = get_single_return(vendor_a["id"])
        return_b = get_single_return(vendor_b["id"])

        validate_success(api.validate_return(return_a["id"], SPEC), 200)
        t1 = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        validate_success(_seal(api, t1["id"]), 200)
        validate_success(_submit(api, t1["id"], "PAPER"), 200)

        # B validates after T1's seal; the second transmittal seals at count exactly 2.
        validate_success(api.validate_return(return_b["id"], SPEC), 200)
        t2 = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        sealed2 = validate_success(_seal(api, t2["id"]), 200)
        assert sealed2["filing_channel"] == "EFILE"

        paper = _submit(api, t2["id"], "PAPER")
        validate_error(paper, ApiErrorId.ERR_EFILE_REQUIRED, 409)
        efiled = validate_success(_submit(api, t2["id"], "EFILE"), 200)
        assert efiled["status"] == "SUBMITTED"


class TestTransmittalSafetyGate:
    def test_submit_safety_beats_channel_constraint(self, api):
        """PRD §2.7: "6. **W-9 and TIN compliance.** Operations that require a
        resolved W-9 or a clean second-B-notice posture (`ERR_W9_NOT_ON_FILE`,
        `ERR_UNRESOLVED_SECOND_B_NOTICE`)."
        PRD §2.7: "10. **Structural rules.** TIN shape, period and rule-interval
        overlap, transmittal non-emptiness, channel and consent constraints, the
        single-active-correction rule, and payment voidability
        (`ERR_INVALID_TIN_FORMAT`, `ERR_TAX_YEAR_OVERLAP`, `ERR_STATE_RULE_OVERLAP`,
        `ERR_TRANSMITTAL_EMPTY`, `ERR_EFILE_REQUIRED`,
        `ERR_ELECTRONIC_CONSENT_REQUIRED`, `ERR_RETURN_NOT_CORRECTABLE`,
        `ERR_PAYMENT_NOT_VOIDABLE`)."
        PRD §2.7: "the caller always receives the earliest applicable rejection,
        never a later one that an earlier failure would have masked."

        Design: Difficulty/priority_pair_validation_conflict/submit_safety_beats_channel_constraint
        """
        create_tax_year(efiling_threshold_count=1)
        vendor, _ = create_matched_vendor(legal_name="Safety V", tin="121212121")
        create_payment(vendor["id"], amount_cents=100000, payment_date="2025-03-01T00:00:00Z")
        generate_returns(2025)
        tax_return = get_single_return(vendor["id"])
        validate_success(api.validate_return(tax_return["id"], SPEC), 200)
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        sealed = validate_success(_seal(api, transmittal["id"]), 200)
        assert sealed["filing_channel"] == "EFILE"

        first_notice = create_b_notice(vendor["id"], notice_year=2024)
        assert first_notice["stage"] == "FIRST"
        second_notice = create_b_notice(vendor["id"], notice_year=2025)
        assert second_notice["stage"] == "SECOND"

        # PAPER violates the e-file rule (rung 10) AND the open SECOND notice
        # violates the safety rule (rung 6); safety must win.
        resp = _submit(api, transmittal["id"], "PAPER")
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SECOND_B_NOTICE, 409)

    def test_submit_blocked_by_open_second_b_notice_alone(self, api):
        """PRD §3.7: "The transmittal must be `SEALED`; the submitter must differ
        from `sealed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); no member return's
        vendor may have an `OPEN` `SECOND` B-notice
        (`ERR_UNRESOLVED_SECOND_B_NOTICE`)..."

        Design: Difficulty/priority_pair_validation_conflict/submit_safety_beats_channel_constraint
        """
        create_tax_year()
        vendor, _payment, tax_return = create_validated_return(
            legal_name="Safety2 V", tin="121212121"
        )
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        sealed = validate_success(_seal(api, transmittal["id"]), 200)
        # Default threshold 10: count 1 keeps PAPER legal — no confound.
        assert sealed["filing_channel"] == "PAPER"

        create_b_notice(vendor["id"], notice_year=2024)
        second_notice = create_b_notice(vendor["id"], notice_year=2025)
        assert second_notice["stage"] == "SECOND"

        resp = _submit(api, transmittal["id"], "PAPER")
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SECOND_B_NOTICE, 409)

        after = validate_success(api.get_transmittal(transmittal["id"], SPEC), 200)
        assert after["status"] == "SEALED"


class TestTransmittalRejection:
    def test_transmittal_reject_reverts_members(self, api):
        """PRD §3.7: "A `REJECTED` outcome returns every member to `VALIDATED` with
        its `transmittal_id` cleared."
        PRD §3.7: "A `TaxSpecialist` may reopen a `REJECTED` transmittal, returning
        it to `OPEN` with `filing_channel`, `return_count`, and `sealed_by_user_id`
        reset to empty values."

        Design: Corner/state_machines/c_transmittal_reject_reverts_members
        """
        create_tax_year()
        _vendor, _payment, tax_return = create_validated_return(
            legal_name="Rej V", tin="258258258"
        )
        transmittal = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        validate_success(_seal(api, transmittal["id"]), 200)
        validate_success(_submit(api, transmittal["id"], "PAPER"), 200)

        rejected = validate_success(
            api.record_transmittal_outcome(transmittal["id"], {"outcome": "REJECTED"}, IRS), 200
        )
        assert rejected["status"] == "REJECTED"

        member = validate_success(api.get_return(tax_return["id"], SPEC), 200)
        assert member["federal_status"] == "VALIDATED"
        assert member.get("transmittal_id") is None

        reopened = validate_success(api.reopen_transmittal(transmittal["id"], SPEC), 200)
        assert reopened["status"] == "OPEN"
        assert reopened["return_count"] == 0
        assert reopened.get("filing_channel") is None

        # The reverted member is eligible again.
        resealed = validate_success(_seal(api, transmittal["id"]), 200)
        assert resealed["return_count"] == 1


class TestCorrectionCardinality:
    def test_accepted_return_cardinality_invariant_under_correction(self, api):
        """PRD §3.6: "The correction then walks the ordinary lifecycle — validation,
        seal, transmission — and at the moment it reaches `ACCEPTED`, the original
        named by `corrects_return_id` transitions from `ACCEPTED` to `SUPERSEDED`
        atomically in the same step."
        PRD §3.6: "The new return starts `DRAFT` with `is_correction` set to true,
        `corrects_return_id` naming the original, `box_amounts` recomputed on the
        final basis over the current ledger, and `provisional_box_amounts`
        initialized to that same final snapshot."

        Design: Difficulty/compensating_invariant/accepted_return_cardinality_invariant_under_correction
        """
        create_tax_year()
        vendor, _payment, original, _t1 = create_accepted_return(
            legal_name="Corr V", tin="101010101"
        )
        assert original["federal_status"] == "ACCEPTED"

        correction = validate_success(
            api.correct_return(
                original["id"], {"expected_return_version": original["version"]}, SPEC
            ),
            201,
        )
        assert correction["is_correction"] is True
        assert correction["corrects_return_id"] == original["id"]
        assert correction["federal_status"] == "DRAFT"

        # Creating the correction leaves exactly one ACCEPTED row for the key.
        rows, meta = validate_paginated(
            api.list_returns(
                SPEC, params={"vendor_id": vendor["id"], "federal_status": "ACCEPTED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == original["id"]

        # Walk the correction through the ordinary lifecycle.
        validate_success(api.validate_return(correction["id"], SPEC), 200)
        t2 = validate_success(
            api.create_transmittal({"tax_year": 2025, "form_type": "NEC"}, SPEC), 201
        )
        validate_success(_seal(api, t2["id"], sealer="spec-2"), 200)
        validate_success(_submit(api, t2["id"], "PAPER", submitter="xmtr-2"), 200)
        validate_success(
            api.record_transmittal_outcome(t2["id"], {"outcome": "ACCEPTED"}, IRS), 200
        )

        # Acceptance atomically supersedes the original: still exactly one ACCEPTED.
        rows2, meta2 = validate_paginated(
            api.list_returns(
                SPEC, params={"vendor_id": vendor["id"], "federal_status": "ACCEPTED"}
            )
        )
        assert meta2["total_count"] == 1
        assert rows2[0]["id"] == correction["id"]

        original_after = validate_success(api.get_return(original["id"], SPEC), 200)
        assert original_after["federal_status"] == "SUPERSEDED"

    def test_single_active_correction_per_original(self, api):
        """PRD §3.6: "A `TaxSpecialist` creates a correction against an original
        whose `federal_status` is `ACCEPTED`; correcting anything else, or correcting
        while another non-terminal correction of the same original exists, is
        rejected with `ERR_RETURN_NOT_CORRECTABLE`."

        Design: Difficulty/compensating_invariant/accepted_return_cardinality_invariant_under_correction
        """
        create_tax_year()
        _vendor, _payment, original, _t1 = create_accepted_return(
            legal_name="Corr2 V", tin="101010101"
        )
        correction = validate_success(
            api.correct_return(
                original["id"], {"expected_return_version": original["version"]}, SPEC
            ),
            201,
        )
        assert correction["is_correction"] is True

        # The successful correction incremented the original's version (PRD §3.6).
        refreshed = validate_success(api.get_return(original["id"], SPEC), 200)
        assert refreshed["version"] == original["version"] + 1

        # A second correction against the same original — with a FRESH version so
        # OCC passes — is blocked by the single-active-correction rule.
        resp = api.correct_return(
            original["id"], {"expected_return_version": refreshed["version"]}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_CORRECTABLE, 409)
