"""Legacy society stewardship: the inclusive recognition threshold."""
from test_helpers import (
    LEGACY_THRESHOLD_CENTS,
    ApiErrorId,
    make_active_rate_table,
    make_donor,
    make_executed_agreement,
    validate_error,
    validate_success,
)


class TestLegacyRecognitionThreshold:
    def test_recognize_at_exact_threshold_inclusive_and_one_cent_below(
        self, api, gift_officer_headers
    ):
        """PRD §3.1: "Recognition requires the donor to be `ENROLLED` and to have
        a `documented_gift_total_cents` of at least 10000000 cents (one hundred
        thousand dollars), an inclusive boundary".
        PRD §3.1: "Enrollment requires the donor to be `LIVING` and to have at
        least one **documented planned gift** — a gift agreement in `EXECUTED`,
        `FUNDED`, `ACTIVE`, `SUSPENDED`, `MATURED`, or `SETTLED` status —
        otherwise the request is rejected with `ERR_LEGACY_SOCIETY_INELIGIBLE`
        (HTTP 422)."

        Design: Corner/calculations/legacy_recognition_threshold_inclusive
        """
        make_active_rate_table()

        # Donor A: documented total exactly at the 10000000 threshold.
        donor_a = make_donor(full_name="Threshold A", date_of_birth="1950-01-01T00:00:00Z")
        make_executed_agreement(
            donor_a["id"], vehicle_type="BEQUEST", gift_amount_cents=LEGACY_THRESHOLD_CENTS
        )
        # Donor B: documented total one cent below the threshold.
        donor_b = make_donor(full_name="Threshold B", date_of_birth="1950-01-01T00:00:00Z")
        make_executed_agreement(
            donor_b["id"], vehicle_type="BEQUEST", gift_amount_cents=LEGACY_THRESHOLD_CENTS - 1
        )

        # A enrolls, then recognizes at the inclusive boundary.
        data = validate_success(
            api.legacy_society_transition(donor_a["id"], {"action": "ENROLL"}, gift_officer_headers)
        )
        assert data["legacy_society_status"] == "ENROLLED"
        data = validate_success(
            api.legacy_society_transition(
                donor_a["id"], {"action": "RECOGNIZE"}, gift_officer_headers
            )
        )
        assert data["legacy_society_status"] == "RECOGNIZED"
        assert data["documented_gift_total_cents"] == LEGACY_THRESHOLD_CENTS

        # B enrolls (an EXECUTED bequest is a documented planned gift) but
        # recognition fails one cent below the inclusive threshold.
        data = validate_success(
            api.legacy_society_transition(donor_b["id"], {"action": "ENROLL"}, gift_officer_headers)
        )
        assert data["legacy_society_status"] == "ENROLLED"
        resp = api.legacy_society_transition(
            donor_b["id"], {"action": "RECOGNIZE"}, gift_officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_LEGACY_SOCIETY_INELIGIBLE)
        assert resp.status_code == 422
        donor_b_after = validate_success(api.get_donor(donor_b["id"], gift_officer_headers))
        assert donor_b_after["documented_gift_total_cents"] == LEGACY_THRESHOLD_CENTS - 1
        assert donor_b_after["legacy_society_status"] == "ENROLLED"
